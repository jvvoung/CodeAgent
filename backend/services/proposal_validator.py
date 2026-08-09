import json
import re
import shutil
import tempfile
from pathlib import Path

from security.path_guard import guard
from services.command_runner import run_command


IGNORED_DIRECTORIES = {
    ".git", ".idea", ".vs", ".venv", ".aura-build", ".aura-validation", ".aura-workspaces", "bin", "build", "coverage",
    "dist", "node_modules", "obj", "target", "__pycache__",
}
IGNORED_COPY_SUFFIXES = {
    ".7z", ".avi", ".bin", ".dll", ".exe", ".gguf", ".gz", ".iso", ".mov",
    ".mp3", ".mp4", ".onnx", ".pdb", ".so", ".tar", ".wav", ".zip",
}
MAX_VALIDATION_COPY_FILE_SIZE = 25_000_000


def _ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    base = Path(directory)
    for name in names:
        candidate = base / name
        if name in IGNORED_DIRECTORIES or candidate.suffix.casefold() in IGNORED_COPY_SUFFIXES:
            ignored.add(name)
            continue
        try:
            if candidate.is_file() and candidate.stat().st_size > MAX_VALIDATION_COPY_FILE_SIZE:
                ignored.add(name)
        except OSError:
            ignored.add(name)
    return ignored


def _commands(root: Path) -> list[list[str]]:
    if (root / "CMakeLists.txt").exists():
        configure = ["cmake", "-S", ".", "-B", ".aura-build"]
        if shutil.which("ninja"):
            configure.extend(["-G", "Ninja"])
        return [
            configure,
            ["cmake", "--build", ".aura-build", "--config", "Debug"],
        ]
    if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
        return [["dotnet", "build", "--nologo", "--no-restore"]]
    if (root / "Cargo.toml").exists():
        return [["cargo", "check"]]
    if (root / "go.mod").exists():
        return [["go", "test", "./..."]]
    if (root / "pom.xml").exists():
        return [["mvn.cmd", "test", "-DskipTests"]]
    if (root / "gradlew.bat").exists():
        return [["gradlew.bat", "classes"]]
    if (root / "package.json").exists():
        try:
            scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError, json.JSONDecodeError):
            scripts = {}
        if "build" in scripts:
            return [["npm.cmd", "run", "build"]]
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        import sys
        return [[sys.executable, "-m", "compileall", "-q", "."]]
    return []


async def _run_validation(root: Path) -> dict:
    commands = _commands(root)
    if not commands:
        return {"supported": False, "ok": True, "output": ""}
    outputs: list[str] = []
    for command in commands:
        result = await run_command(command, str(root), timeout=240)
        outputs.append((result.get("stdout", "") + "\n" + result.get("stderr", "")).strip())
        if result.get("return_code") != 0:
            return {
                "supported": True,
                "ok": False,
                "command": result.get("command", " ".join(command)),
                "output": "\n".join(outputs)[-12_000:],
            }
    return {
        "supported": True,
        "ok": True,
        "command": " && ".join(" ".join(command) for command in commands),
        "output": "\n".join(outputs)[-4_000:],
    }


async def run_workspace_validation(root: Path) -> dict:
    """Run validation inside a caller-owned isolated workspace."""
    return await _run_validation(root)


def _copy_project(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=_ignore)
    if list(source.glob("*.sln")) or list(source.glob("*.csproj")):
        restore_names = {"project.assets.json", "project.nuget.cache"}
        for source_obj in source.rglob("obj"):
            if not source_obj.is_dir():
                continue
            relative_obj = source_obj.relative_to(source)
            if any(part in IGNORED_DIRECTORIES - {"obj"} for part in relative_obj.parts):
                continue
            destination_obj = destination / relative_obj
            for restore_file in source_obj.iterdir():
                if not restore_file.is_file():
                    continue
                if restore_file.name in restore_names or ".nuget.g." in restore_file.name:
                    destination_obj.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(restore_file, destination_obj / restore_file.name)


def _apply_preview(root: Path, previewed_files: list[dict]) -> None:
    for item in previewed_files:
        relative = Path(str(item.get("path", "")))
        target = (root / relative).resolve(strict=False)
        if root != target and root not in target.parents:
            raise ValueError(f"검증 작업공간 밖의 변경 경로입니다: {relative.as_posix()}")
        if not target.is_file():
            raise ValueError(f"검증할 원본 파일을 찾을 수 없습니다: {relative.as_posix()}")
        target.write_text(str(item.get("modified", "")), encoding="utf-8")


def _diagnostic_lines(output: str) -> set[str]:
    lines: set[str] = set()
    for raw in output.splitlines():
        cleaned = raw.strip()
        if not cleaned or cleaned.startswith(("-- ", "[", "Microsoft (R)")):
            continue
        normalized = re.sub(
            r"\.(?:aura-validation[\\/]+proposal-|aura-workspaces[\\/]+task-)[^\\/]+[\\/]+(?:baseline|proposed|worktree)",
            ".aura-workspace/<task>",
            cleaned,
            flags=re.IGNORECASE,
        )
        lines.add(normalized[-500:])
    return lines


def _infrastructure_failure(output: str) -> bool:
    lowered = output.casefold()
    markers = (
        "nu1301", "unable to load the service index", "서비스 인덱스를 로드할 수 없습니다",
        "api.nuget.org", "socket access", "소켓에 액세스를 시도했습니다",
        "network is unreachable", "temporary failure in name resolution",
    )
    return any(marker in lowered for marker in markers)


def _compact_failure_output(output: str) -> str:
    selected: list[str] = []
    diagnostic_pattern = re.compile(
        r"(?:\berror\s+[A-Z]{1,5}\d+\b|\berror:|\bfatal error:|\bundefined reference\b|"
        r"\bredefinition\b|\bundeclared\b|\bFAILED:)" ,
        re.IGNORECASE,
    )
    validation_path = re.compile(
        r"^.*?\.(?:aura-validation[\\/]+proposal-|aura-workspaces[\\/]+task-)[^\\/]+[\\/]+(?:proposed|worktree)[\\/]+",
        re.IGNORECASE,
    )
    for raw in output.splitlines():
        if not diagnostic_pattern.search(raw):
            continue
        cleaned = validation_path.sub("", raw.strip())
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        if cleaned and cleaned not in selected:
            selected.append(cleaned)
    if selected:
        return "\n".join(selected[:12])[-6_000:]
    fallback = [line.strip() for line in output.splitlines() if line.strip()][-20:]
    return "\n".join(fallback)[-3_000:]


def classify_validation(baseline: dict, proposed: dict) -> dict:
    """Classify a candidate relative to its baseline, which may already be broken."""
    if not proposed.get("supported"):
        return {
            "supported": False,
            "ok": True,
            "status": "unavailable",
            "message": "자동 빌드 구성을 찾지 못해 변경 내용만 검토했습니다.",
        }
    if proposed.get("ok"):
        return {
            "supported": True,
            "ok": True,
            "status": "verified",
            "command": proposed.get("command", ""),
        }
    if _infrastructure_failure(str(proposed.get("output", ""))):
        return {
            "supported": False,
            "ok": True,
            "status": "unavailable",
            "message": "패키지 복원 또는 실행 환경 문제로 빌드 검증을 완료하지 못했습니다.",
        }
    if baseline.get("ok"):
        return {
            "supported": True,
            "ok": False,
            "status": "failed",
            "message": f"변경 전에는 성공하던 검증이 변경 후 실패했습니다.\n{_compact_failure_output(str(proposed.get('output', '')))}",
        }
    new_diagnostics = _diagnostic_lines(str(proposed.get("output", ""))) - _diagnostic_lines(str(baseline.get("output", "")))
    if new_diagnostics:
        return {
            "supported": True,
            "ok": False,
            "status": "failed",
            "message": "변경안이 새로운 빌드 오류를 만들었습니다.\n" + "\n".join(sorted(new_diagnostics))[-10_000:],
        }
    return {
        "supported": True,
        "ok": True,
        "status": "baseline_failed",
        "command": proposed.get("command", ""),
        "warning": "프로젝트가 변경 전부터 빌드되지 않았지만 변경 후 새로운 진단은 확인되지 않았습니다.",
    }


async def validate_proposal(previewed_files: list[dict]) -> dict:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    source = guard.root
    validation_parent = Path(__file__).resolve().parents[2] / ".aura-validation"
    validation_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="proposal-", dir=validation_parent, ignore_cleanup_errors=True
    ) as temporary:
        temporary_root = Path(temporary)
        baseline_root = temporary_root / "baseline"
        proposed_root = temporary_root / "proposed"
        _copy_project(source, baseline_root)
        _copy_project(source, proposed_root)
        _apply_preview(proposed_root, previewed_files)
        baseline = await _run_validation(baseline_root)
        proposed = await _run_validation(proposed_root)

    return classify_validation(baseline, proposed)
