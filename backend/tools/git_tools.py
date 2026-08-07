from security.path_guard import guard
from services.command_runner import run_command


async def git_command(args: list[str]) -> dict:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    if not (guard.root / ".git").exists():
        raise ValueError("열린 프로젝트가 Git 저장소가 아닙니다.")
    return await run_command(["git", *args], str(guard.root), timeout=60)


async def status() -> dict:
    return await git_command(["status", "--short", "--branch"])


async def diff() -> dict:
    return await git_command(["diff", "--no-ext-diff"])
