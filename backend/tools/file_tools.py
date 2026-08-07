import shutil
import subprocess
from pathlib import Path

from security.path_guard import guard

IGNORED = {".git", "node_modules", ".venv", "venv", "dist", "build", "bin", "obj", "__pycache__", ".idea", ".vs"}
BINARY_SUFFIXES = {
    ".7z", ".avi", ".bin", ".bmp", ".class", ".dll", ".doc", ".docx", ".exe",
    ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".mov", ".mp3", ".mp4",
    ".gguf", ".onnx", ".pdf", ".png", ".pyd", ".pyc", ".so", ".tar", ".webp", ".xlsx", ".zip",
}
MAX_FILE_SIZE = 1_000_000


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED or part.startswith(".") for part in path.parts)


def tree(path: Path | None = None, depth: int = 0) -> list[dict]:
    base = path or guard.root
    if not base:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    if depth > 7:
        return []
    result: list[dict] = []
    try:
        entries = sorted(base.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError:
        return []
    for item in entries:
        if item.name in IGNORED or item.name.startswith("."):
            continue
        is_directory = item.is_dir()
        if not is_directory and item.suffix.lower() in BINARY_SUFFIXES:
            continue
        result.append({
            "name": item.name,
            "path": guard.relative(item),
            "type": "directory" if is_directory else "file",
            "children": tree(item, depth + 1) if is_directory else [],
        })
    return result


def list_files(limit: int = 500) -> list[str]:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    files: list[str] = []
    for file in guard.root.rglob("*"):
        relative = file.relative_to(guard.root)
        if _is_ignored(relative) or not file.is_file() or file.suffix.lower() in BINARY_SUFFIXES:
            continue
        files.append(relative.as_posix())
        if len(files) >= limit:
            break
    return sorted(files)


def resolve_source_file(path: str) -> Path:
    target = guard.resolve(path)
    if target.is_file():
        return target
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")

    filename = Path(path.replace("\\", "/")).name
    matches = [
        candidate for candidate in guard.root.rglob(filename)
        if candidate.is_file() and not _is_ignored(candidate.relative_to(guard.root))
    ] if filename else []
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(guard.relative(candidate) for candidate in matches[:5])
        raise ValueError(f"같은 이름의 파일이 여러 개 있습니다. 정확한 상대 경로가 필요합니다: {choices}")
    raise ValueError(f"파일을 찾을 수 없습니다: {path}")


def read_file(path: str) -> str:
    target = resolve_source_file(path)
    size = target.stat().st_size
    if size > MAX_FILE_SIZE:
        raise ValueError(f"파일 용량이 제한을 초과했습니다: {guard.relative(target)} ({size:,}바이트, 제한 {MAX_FILE_SIZE:,}바이트)")
    if target.suffix.lower() in BINARY_SUFFIXES or b"\0" in target.read_bytes()[:4096]:
        raise ValueError(f"바이너리 파일은 열 수 없습니다: {guard.relative(target)}")
    return target.read_text(encoding="utf-8", errors="replace")


def _python_search(query: str, limit: int) -> list[dict]:
    hits: list[dict] = []
    assert guard.root
    for file in guard.root.rglob("*"):
        relative = file.relative_to(guard.root)
        if _is_ignored(relative) or not file.is_file() or file.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            if file.stat().st_size > MAX_FILE_SIZE:
                continue
            for number, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if query.casefold() in line.casefold():
                    hits.append({"path": relative.as_posix(), "line": number, "text": line[:300]})
                if len(hits) >= limit:
                    return hits
        except OSError:
            continue
    return hits


def search_code(query: str, limit: int = 100) -> list[dict]:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    query = query.strip()
    if not query:
        raise ValueError("검색어를 입력해 주세요.")
    if shutil.which("rg"):
        command = ["rg", "-n", "--no-heading", "--color", "never", "--fixed-strings", "-i"]
        for name in sorted(IGNORED):
            command.extend(["--glob", f"!{name}/**"])
        command.extend([query, "."])
        completed = subprocess.run(
            command, cwd=guard.root, capture_output=True, timeout=15, check=False
        )
        if completed.returncode in (0, 1):
            hits: list[dict] = []
            output = completed.stdout.decode("utf-8", errors="replace")
            for raw_line in output.splitlines():
                parts = raw_line.split(":", 2)
                if len(parts) != 3:
                    continue
                path, line_number, text = parts
                hits.append({"path": Path(path).as_posix().removeprefix("./"), "line": int(line_number), "text": text[:300]})
                if len(hits) >= limit:
                    break
            return hits
    return _python_search(query, limit)
