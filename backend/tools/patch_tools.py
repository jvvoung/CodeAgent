import difflib
import re

from models.schemas import ProposedFile
from security.path_guard import guard
from tools.file_tools import read_file, resolve_source_file

pending: dict[str, dict[str, object]] = {}


def clear() -> None:
    pending.clear()


def _resolve_unique_old(source: str, requested: str) -> str:
    occurrences = source.count(requested)
    if occurrences == 1:
        return requested
    if occurrences > 1:
        raise ValueError(f"원본 텍스트가 {occurrences}곳에서 발견되어 변경 위치를 확정할 수 없습니다.")

    tokens = re.split(r"\s+", requested.strip())
    if not tokens or any(not token for token in tokens):
        raise ValueError("원본 텍스트가 현재 파일과 일치하지 않습니다.")
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    matches = list(re.finditer(pattern, source, re.MULTILINE))
    if len(matches) == 1:
        return matches[0].group(0)
    if len(matches) > 1:
        raise ValueError(f"공백을 정규화한 원본 텍스트가 {len(matches)}곳에서 발견되어 변경 위치를 확정할 수 없습니다.")
    raise ValueError("원본 텍스트가 현재 파일과 일치하지 않습니다.")


def preview(files: list[ProposedFile]) -> list[dict]:
    result: list[dict] = []
    for proposed in files:
        normalized_path = guard.relative(resolve_source_file(proposed.path))
        original = read_file(normalized_path)
        modified = original
        for change in proposed.changes:
            try:
                actual_old = _resolve_unique_old(modified, change.old)
            except ValueError as exc:
                raise ValueError(f"{exc} 파일: {normalized_path}") from exc
            actual_new = change.new
            if actual_old != change.old:
                if change.new.startswith(change.old):
                    actual_new = actual_old + change.new[len(change.old):]
                elif change.new.endswith(change.old):
                    actual_new = change.new[:-len(change.old)] + actual_old
            modified = modified.replace(actual_old, actual_new, 1)
        if modified == original:
            raise ValueError(f"실제 변경 내용이 없습니다: {normalized_path}")
        line_diff = list(difflib.ndiff(original.splitlines(), modified.splitlines()))
        item: dict[str, str | int] = {
            "original": original,
            "modified": modified,
            "additions": sum(line.startswith("+ ") for line in line_diff),
            "deletions": sum(line.startswith("- ") for line in line_diff),
        }
        result.append({"path": normalized_path, **item})
    return result


def propose(files: list[ProposedFile]) -> list[dict]:
    result = preview(files)
    stage_preview(result)
    return result


def stage_preview(
    result: list[dict],
    *,
    validation_status: str = "ready",
    validation_error: str = "",
    retry_request: str = "",
) -> list[dict]:
    staged = {
        str(item["path"]): {
            "original": item["original"],
            "modified": item["modified"],
            "additions": item["additions"],
            "deletions": item["deletions"],
            "original_exists": item.get("original_exists", True),
            "modified_exists": item.get("modified_exists", True),
            "change_type": item.get("change_type", "modified"),
            "validation_status": validation_status,
            "validation_error": validation_error,
            "retry_request": retry_request,
        }
        for item in result
    }
    pending.update(staged)
    return result


def propose_failed(result: list[dict], validation_error: str, retry_request: str) -> list[dict]:
    return stage_preview(
        result,
        validation_status="failed",
        validation_error=validation_error,
        retry_request=retry_request,
    )


def apply(paths: list[str] | None, *, confirm_unverified: bool = False) -> list[str]:
    selected = paths if paths is not None else list(pending)
    unknown = [path for path in selected if path not in pending]
    if unknown:
        raise ValueError(f"알 수 없는 대기 중 변경사항입니다: {unknown[0]}")
    for path in selected:
        item = pending[path]
        if item.get("validation_status") in {"failed", "scope_review_incomplete"} and not confirm_unverified:
            raise ValueError(f"검증 또는 범위 검토가 완료되지 않은 변경안을 적용하려면 사용자 확인이 필요합니다: {path}")
        target = guard.resolve(path)
        original_exists = bool(item.get("original_exists", True))
        if original_exists:
            if not target.is_file() or read_file(path) != item["original"]:
                raise ValueError(f"변경안 생성 후 파일 내용이 달라졌습니다: {path}")
        elif target.exists():
            raise ValueError(f"변경안 생성 후 같은 경로에 파일이 생겼습니다: {path}")
    for path in selected:
        item = pending[path]
        target = guard.resolve(path)
        if bool(item.get("modified_exists", True)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(item["modified"]), encoding="utf-8")
        elif target.is_file():
            target.unlink()
        pending.pop(path)
    return selected


def reject(paths: list[str] | None) -> list[str]:
    selected = paths if paths is not None else list(pending)
    for path in selected:
        pending.pop(path, None)
    return selected
