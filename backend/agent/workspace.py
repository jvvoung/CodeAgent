from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from pathlib import Path

from services.proposal_validator import IGNORED_DIRECTORIES, _copy_project
from tools.file_tools import BINARY_SUFFIXES, MAX_FILE_SIZE


class PatchError(ValueError):
    pass


def _safe_relative(raw: str) -> Path:
    cleaned = raw.strip().replace("\\", "/")
    while cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    path = Path(cleaned)
    if not cleaned or path.is_absolute() or ".." in path.parts:
        raise PatchError(f"프로젝트 내부의 상대 경로만 사용할 수 있습니다: {raw}")
    return path


def _split_unified_patch(
    patch: str, *, default_path: str | None = None
) -> list[tuple[str, str, list[str]]]:
    lines = patch.replace("\r\n", "\n").splitlines()
    if any(line.strip() == "*** Begin Patch" for line in lines):
        return _split_codex_patch(lines)

    files: list[tuple[str, str, list[str]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = lines[index][4:].split("\t", 1)[0].strip()
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchError("unified diff의 +++ 파일 헤더가 없습니다.")
        new_path = lines[index][4:].split("\t", 1)[0].strip()
        index += 1
        hunks: list[str] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            hunks.append(lines[index])
            index += 1
        files.append((old_path, new_path, hunks))
    if not files and default_path:
        body = [
            line for line in lines
            if line.strip() not in {"*** Begin Patch", "*** End Patch", "*** End of File"}
            and not line.startswith("```")
        ]
        return [(default_path, default_path, body)]
    if not files:
        raise PatchError("unified diff에서 변경 파일 헤더를 찾지 못했습니다.")
    return files


def _split_codex_patch(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """Parse the apply_patch envelope used by Codex-style tool callers."""
    files: list[tuple[str, str, list[str]]] = []
    index = 0
    header_pattern = re.compile(r"^\*\*\* (Update|Add|Delete) File:\s*(.+?)\s*$")
    while index < len(lines):
        match = header_pattern.match(lines[index])
        if not match:
            index += 1
            continue
        operation, path = match.groups()
        index += 1
        hunks: list[str] = []
        while index < len(lines):
            line = lines[index]
            if header_pattern.match(line) or line.strip() == "*** End Patch":
                break
            if line.strip() != "*** End of File":
                hunks.append(line)
            index += 1
        if operation == "Add":
            files.append(("/dev/null", path, hunks))
        elif operation == "Delete":
            files.append((path, "/dev/null", hunks))
        else:
            files.append((path, path, hunks))
    if not files:
        raise PatchError("apply_patch 형식에서 변경 파일 헤더를 찾지 못했습니다.")
    return files


def _apply_context_hunks(original: str, hunks: list[str]) -> str:
    """Apply Codex-style hunks whose @@ headers do not carry line numbers."""
    source = original.replace("\r\n", "\n").splitlines()
    sections: list[list[str]] = []
    current: list[str] = []
    for line in hunks:
        if line.startswith("@@"):
            if current:
                sections.append(current)
                current = []
            continue
        if line.startswith("\\ No newline"):
            continue
        current.append(line)
    if current:
        sections.append(current)
    if not sections:
        raise PatchError("patch에 적용할 변경 줄이 없습니다.")

    cursor = 0
    for body in sections:
        if any(line[:1] not in (" ", "-", "+") for line in body):
            invalid = next(line for line in body if line[:1] not in (" ", "-", "+"))
            raise PatchError(f"지원하지 않는 patch 줄입니다: {invalid}")
        consumed = [line[1:] for line in body if line[:1] in (" ", "-")]
        produced = [line[1:] for line in body if line[:1] in (" ", "+")]
        if not consumed:
            if source or cursor:
                raise PatchError("문맥 없는 추가 hunk는 새 파일에서만 사용할 수 있습니다.")
            source = produced
            cursor = len(source)
            continue
        matches = [
            offset for offset in range(cursor, len(source) - len(consumed) + 1)
            if source[offset:offset + len(consumed)] == consumed
        ]
        if len(matches) != 1:
            raise PatchError(f"patch 문맥을 원본에서 고유하게 찾지 못했습니다: 일치 {len(matches)}개")
        location = matches[0]
        source[location:location + len(consumed)] = produced
        cursor = location + len(produced)
    rendered = "\n".join(source)
    if source and (original.endswith(("\n", "\r")) or not original):
        rendered += "\n"
    return rendered


def _apply_hunks(original: str, hunks: list[str]) -> str:
    numbered_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    if not any(numbered_header.match(line) for line in hunks if line.startswith("@@")):
        return _apply_context_hunks(original, hunks)

    source = original.replace("\r\n", "\n").splitlines()
    trailing_newline = original.endswith(("\n", "\r"))
    result: list[str] = []
    cursor = 0
    index = 0
    header_pattern = numbered_header
    while index < len(hunks):
        if not hunks[index].startswith("@@"):
            index += 1
            continue
        match = header_pattern.match(hunks[index])
        if not match:
            raise PatchError(f"잘못된 hunk 헤더입니다: {hunks[index]}")
        expected = max(int(match.group(1)) - 1, 0)
        index += 1
        body: list[str] = []
        while index < len(hunks) and not hunks[index].startswith("@@"):
            if hunks[index].startswith("\\ No newline"):
                index += 1
                continue
            body.append(hunks[index])
            index += 1
        consumed = [line[1:] for line in body if line[:1] in (" ", "-")]
        location = expected
        if source[location:location + len(consumed)] != consumed:
            matches = [
                offset for offset in range(0, len(source) - len(consumed) + 1)
                if source[offset:offset + len(consumed)] == consumed
            ]
            if len(matches) != 1:
                raise PatchError(f"patch 문맥을 원본에서 고유하게 찾지 못했습니다: {hunks[index - len(body) - 1]}")
            location = matches[0]
        if location < cursor:
            raise PatchError("서로 겹치는 patch hunk는 적용할 수 없습니다.")
        result.extend(source[cursor:location])
        source_index = location
        for line in body:
            marker = line[:1]
            text = line[1:]
            if marker == " ":
                if source_index >= len(source) or source[source_index] != text:
                    raise PatchError("patch 문맥이 현재 파일과 일치하지 않습니다.")
                result.append(text)
                source_index += 1
            elif marker == "-":
                if source_index >= len(source) or source[source_index] != text:
                    raise PatchError("patch 삭제 대상이 현재 파일과 일치하지 않습니다.")
                source_index += 1
            elif marker == "+":
                result.append(text)
            else:
                raise PatchError(f"지원하지 않는 patch 행입니다: {line}")
        cursor = source_index
    result.extend(source[cursor:])
    rendered = "\n".join(result)
    if trailing_newline and result:
        rendered += "\n"
    return rendered


class AgentWorkspace:
    """Two local shadow copies: an immutable baseline and a mutable agent worktree."""

    def __init__(self, source: Path) -> None:
        self.source = source.resolve()
        parent = Path(__file__).resolve().parents[2] / ".aura-workspaces"
        parent.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="task-", dir=parent, ignore_cleanup_errors=True
        )
        temporary_root = Path(self._temporary.name)
        self.baseline_root = temporary_root / "baseline"
        self.root = temporary_root / "worktree"
        _copy_project(self.source, self.baseline_root)
        _copy_project(self.source, self.root)
        self._touched: set[str] = set()
        self.revision = 0

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> AgentWorkspace:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def resolve(self, raw: str, *, must_exist: bool = True) -> Path:
        relative = _safe_relative(raw)
        target = (self.root / relative).resolve(strict=False)
        if target != self.root and self.root not in target.parents:
            raise ValueError("격리 작업공간 밖의 경로에는 접근할 수 없습니다.")
        if must_exist and not target.is_file():
            raise ValueError(f"파일을 찾을 수 없습니다: {relative.as_posix()}")
        return target

    def relative(self, target: Path) -> str:
        return target.relative_to(self.root).as_posix()

    def _read_path(self, target: Path) -> str:
        if target.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"파일 용량이 제한을 초과했습니다: {self.relative(target)}")
        if target.suffix.casefold() in BINARY_SUFFIXES or b"\0" in target.read_bytes()[:4096]:
            raise ValueError(f"바이너리 파일은 읽거나 수정할 수 없습니다: {self.relative(target)}")
        return target.read_text(encoding="utf-8", errors="replace")

    def read_file(self, path: str) -> str:
        return self._read_path(self.resolve(path))

    def read_file_range(self, path: str, start_line: int, end_line: int) -> dict:
        if start_line < 1 or end_line < start_line or end_line - start_line >= 500:
            raise ValueError("읽을 줄 범위는 1줄 이상 500줄 이하여야 합니다.")
        target = self.resolve(path)
        lines = self._read_path(target).splitlines(keepends=True)
        actual_end = min(end_line, len(lines))
        return {
            "path": self.relative(target),
            "start_line": start_line,
            "end_line": actual_end,
            "total_lines": len(lines),
            "content": "".join(lines[start_line - 1:actual_end]),
        }

    def list_files(self, limit: int = 500) -> list[str]:
        files: list[str] = []
        for target in self.root.rglob("*"):
            relative = target.relative_to(self.root)
            if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts):
                continue
            if target.is_file() and target.suffix.casefold() not in BINARY_SUFFIXES:
                files.append(relative.as_posix())
                if len(files) >= limit:
                    break
        return sorted(files)

    def search(self, query: str, *, regex: bool = False, limit: int = 100) -> list[dict]:
        if not query.strip():
            raise ValueError("검색어가 필요합니다.")
        try:
            expression = re.compile(query, re.IGNORECASE) if regex else None
        except re.error as exc:
            raise ValueError(f"잘못된 검색 정규식입니다: {exc}") from exc
        hits: list[dict] = []
        for path in self.list_files(limit=10_000):
            target = self.resolve(path)
            try:
                content = self._read_path(target)
            except (OSError, ValueError):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                matched = bool(expression.search(line)) if expression else query.casefold() in line.casefold()
                if matched:
                    hits.append({"path": path, "line": number, "text": line[:300]})
                    if len(hits) >= limit:
                        return hits
        return hits

    def replace_text(self, path: str, old: str, new: str, expected_count: int = 1) -> dict:
        if not old:
            raise ValueError("replace_text의 old는 비어 있을 수 없습니다.")
        if expected_count < 1 or expected_count > 100:
            raise ValueError("expected_count는 1부터 100 사이여야 합니다.")
        target = self.resolve(path)
        source = self._read_path(target)
        actual = source.count(old)
        if actual != expected_count:
            occurrences: list[str] = []
            if actual:
                for line_number, line in enumerate(source.splitlines(), 1):
                    if old in line:
                        occurrences.append(f"{line_number}: {line.strip()[:240]}")
                        if len(occurrences) >= 10:
                            break
            detail = f"교체 대상 개수가 다릅니다: 예상 {expected_count}개, 실제 {actual}개"
            if occurrences:
                detail += ". 일치 위치: " + " | ".join(occurrences)
            raise ValueError(detail)
        target.write_text(source.replace(old, new), encoding="utf-8")
        relative = self.relative(target)
        self._touched.add(relative)
        self.revision += 1
        return {"path": relative, "replacements": actual}

    def infer_patch_target(self, patch: str, candidates: list[str] | None = None) -> str | None:
        """Find one existing text file whose contents uniquely match a headerless hunk."""
        lines = patch.replace("\r\n", "\n").splitlines()
        consumed = [
            line[1:] for line in lines
            if line[:1] in (" ", "-")
            and not line.startswith("---")
            and not line.startswith("***")
        ]
        candidate_paths = candidates or self.list_files(limit=10_000)
        normalized_candidates = list(dict.fromkeys(candidate_paths))
        matches: list[str] = []
        for path in normalized_candidates:
            try:
                content = self.read_file(path).replace("\r\n", "\n").splitlines()
            except (OSError, ValueError):
                continue
            if consumed:
                found = any(
                    content[offset:offset + len(consumed)] == consumed
                    for offset in range(0, len(content) - len(consumed) + 1)
                )
            else:
                found = len(normalized_candidates) == 1
            if found:
                matches.append(path)
        return matches[0] if len(matches) == 1 else None

    def apply_patch(self, patch: str, *, default_path: str | None = None) -> dict:
        planned: list[tuple[Path, str, str, bool]] = []
        for old_header, new_header, hunks in _split_unified_patch(patch, default_path=default_path):
            deleting = new_header == "/dev/null"
            creating = old_header == "/dev/null"
            raw_path = old_header if deleting else new_header
            relative = _safe_relative(raw_path)
            target = self.resolve(relative.as_posix(), must_exist=not creating)
            original = "" if creating else self._read_path(target)
            modified = _apply_hunks(original, hunks)
            if modified == original and not deleting:
                raise PatchError(f"실제 변경이 없는 patch입니다: {relative.as_posix()}")
            normalized = relative.as_posix()
            planned.append((target, normalized, modified, deleting))
        changed: list[str] = []
        for target, normalized, modified, deleting in planned:
            if deleting:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(modified, encoding="utf-8")
            self._touched.add(normalized)
            changed.append(normalized)
        if changed:
            self.revision += 1
        return {"paths": changed}

    def patch_targets(self, patch: str, *, default_path: str | None = None) -> list[dict]:
        targets: list[dict] = []
        for old_header, new_header, _hunks in _split_unified_patch(patch, default_path=default_path):
            creating = old_header == "/dev/null"
            raw_path = old_header if new_header == "/dev/null" else new_header
            targets.append({"path": _safe_relative(raw_path).as_posix(), "creating": creating})
        return targets

    def revert_file(self, path: str) -> dict:
        relative = _safe_relative(path).as_posix()
        if relative not in self._touched:
            changed_paths = [item["path"] for item in self.preview()]
            raise ValueError(
                f"현재 작업에서 변경되지 않은 파일입니다: {relative}. "
                f"현재 실제 변경 파일: {', '.join(changed_paths) if changed_paths else '없음'}"
            )
        target = self.resolve(relative, must_exist=False)
        baseline = self.baseline_root / Path(relative)
        if baseline.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(baseline, target)
        elif target.exists():
            target.unlink()
        self.revision += 1
        return {"path": relative, "reverted": True}

    def preview(self) -> list[dict]:
        result: list[dict] = []
        for path in sorted(self._touched):
            baseline = self.baseline_root / Path(path)
            proposed = self.root / Path(path)
            original_exists = baseline.is_file()
            modified_exists = proposed.is_file()
            original = baseline.read_text(encoding="utf-8", errors="replace") if original_exists else ""
            modified = proposed.read_text(encoding="utf-8", errors="replace") if modified_exists else ""
            if original_exists == modified_exists and original == modified:
                continue
            line_diff = list(difflib.ndiff(original.splitlines(), modified.splitlines()))
            change_type = "modified"
            if not original_exists:
                change_type = "added"
            elif not modified_exists:
                change_type = "deleted"
            result.append({
                "path": path,
                "original": original,
                "modified": modified,
                "original_exists": original_exists,
                "modified_exists": modified_exists,
                "change_type": change_type,
                "additions": sum(line.startswith("+ ") for line in line_diff),
                "deletions": sum(line.startswith("- ") for line in line_diff),
            })
        return result
