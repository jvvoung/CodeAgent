import difflib

from models.schemas import ProposedFile
from security.path_guard import guard
from tools.file_tools import read_file, resolve_source_file

pending: dict[str, dict[str, str | int]] = {}


def clear() -> None:
    pending.clear()


def propose(files: list[ProposedFile]) -> list[dict]:
    result: list[dict] = []
    for proposed in files:
        normalized_path = guard.relative(resolve_source_file(proposed.path))
        original = read_file(normalized_path)
        modified = original
        for change in proposed.changes:
            occurrences = modified.count(change.old)
            if occurrences == 0:
                raise ValueError(f"원본 텍스트가 현재 파일과 일치하지 않습니다: {normalized_path}")
            if occurrences > 1:
                raise ValueError(f"원본 텍스트가 {occurrences}곳에서 발견되어 변경 위치를 확정할 수 없습니다: {normalized_path}")
            modified = modified.replace(change.old, change.new, 1)
        if modified == original:
            raise ValueError(f"실제 변경 내용이 없습니다: {normalized_path}")
        line_diff = list(difflib.ndiff(original.splitlines(), modified.splitlines()))
        item: dict[str, str | int] = {
            "original": original,
            "modified": modified,
            "additions": sum(line.startswith("+ ") for line in line_diff),
            "deletions": sum(line.startswith("- ") for line in line_diff),
        }
        pending[normalized_path] = item
        result.append({"path": normalized_path, **item})
    return result


def apply(paths: list[str] | None) -> list[str]:
    selected = paths if paths is not None else list(pending)
    unknown = [path for path in selected if path not in pending]
    if unknown:
        raise ValueError(f"알 수 없는 대기 중 변경사항입니다: {unknown[0]}")
    for path in selected:
        item = pending[path]
        if read_file(path) != item["original"]:
            raise ValueError(f"변경안 생성 후 파일 내용이 달라졌습니다: {path}")
    for path in selected:
        item = pending[path]
        guard.resolve(path).write_text(str(item["modified"]), encoding="utf-8")
        pending.pop(path)
    return selected


def reject(paths: list[str] | None) -> list[str]:
    selected = paths if paths is not None else list(pending)
    for path in selected:
        pending.pop(path, None)
    return selected
