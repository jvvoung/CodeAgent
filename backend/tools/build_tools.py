import sys
from pathlib import Path

from security.path_guard import guard
from services.command_runner import run_command


def detect_command(root: Path, test: bool = False) -> list[str]:
    if list(root.glob("*.sln")) or list(root.glob("*.csproj")):
        return ["dotnet", "test" if test else "build"]
    if (root / "package.json").exists():
        return ["npm.cmd", "test"] if test else ["npm.cmd", "run", "build"]
    if (root / "CMakeLists.txt").exists():
        if test:
            return ["ctest", "--test-dir", "build", "--output-on-failure"]
        return ["cmake", "--build", "build"]
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return [sys.executable, "-m", "pytest"] if test else [sys.executable, "-m", "compileall", "-q", "."]
    raise ValueError(f"지원하는 {'테스트' if test else '빌드'} 설정을 찾지 못했습니다.")


async def run_build(test: bool = False) -> dict:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    command = detect_command(guard.root, test=test)
    return await run_command(command, str(guard.root), timeout=300)
