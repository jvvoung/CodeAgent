import asyncio
import os
import shutil
import time
import uuid
from pathlib import Path

from security.path_guard import guard


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _git_bash() -> str:
    candidates: list[Path] = []
    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.extend([
            git_path.parent.parent / "bin" / "bash.exe",
            git_path.parent.parent / "usr" / "bin" / "bash.exe",
        ])
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.getenv(variable)
        if base:
            candidates.extend([
                Path(base) / "Git" / "bin" / "bash.exe",
                Path(base) / "Programs" / "Git" / "bin" / "bash.exe",
            ])
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise ValueError("Git Bash를 찾을 수 없습니다. Git for Windows가 설치되어 있는지 확인해 주세요.")


def _wrapped_command(shell: str, command: str, marker: str) -> str:
    if shell == "cmd":
        normalized = command.replace("\r\n", " & ").replace("\n", " & ")
        return f'{normalized} & set "AURA_EXIT=!ERRORLEVEL!" & for %A in (.) do @echo {marker}%~fA & exit /b !AURA_EXIT!'
    if shell == "powershell":
        return (
            "try {\n"
            f"{command}\n"
            "$auraExit = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } elseif ($?) { 0 } else { 1 }\n"
            "} catch {\n"
            "Write-Error $_\n"
            "$auraExit = 1\n"
            "}\n"
            f'Write-Output "{marker}$((Get-Location).Path)"\n'
            "exit $auraExit"
        )
    if shell == "git-bash":
        return (
            f"{command}\n"
            "aura_exit=$?\n"
            f"printf '\\n%s%s\\n' '{marker}' \"$(pwd -W)\"\n"
            "exit $aura_exit"
        )
    raise ValueError(f"지원하지 않는 터미널입니다: {shell}")


def _shell_command(shell: str, command: str, marker: str) -> list[str]:
    wrapped = _wrapped_command(shell, command, marker)
    if shell == "cmd":
        executable = shutil.which("cmd.exe") or str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "cmd.exe")
        return [executable, "/d", "/v:on", "/s", "/c", wrapped]
    if shell == "powershell":
        executable = shutil.which("powershell.exe") or str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped]
    if shell == "git-bash":
        return [_git_bash(), "--noprofile", "--norc", "-lc", wrapped]
    raise ValueError(f"지원하지 않는 터미널입니다: {shell}")


def _extract_cwd(output: str, marker: str, fallback: Path) -> tuple[str, Path]:
    cwd_value = ""
    visible_lines: list[str] = []
    for line in output.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped.startswith(marker):
            cwd_value = stripped[len(marker):].strip()
        else:
            visible_lines.append(line)

    if not cwd_value:
        return "".join(visible_lines), fallback
    candidate = Path(cwd_value).resolve(strict=False)
    if not candidate.is_dir():
        return "".join(visible_lines), fallback
    return "".join(visible_lines), candidate


async def run_terminal(shell: str, command: str, timeout: int = 300, cwd: str | None = None) -> dict:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    command = command.strip()
    if not command:
        raise ValueError("실행할 명령어를 입력해 주세요.")
    working_directory = Path(cwd).expanduser().resolve(strict=False) if cwd else guard.root
    if not working_directory.is_dir():
        raise ValueError("터미널 작업 폴더가 존재하지 않습니다.")

    started = time.monotonic()
    marker = f"__AURA_CWD_{uuid.uuid4().hex}__"
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *_shell_command(shell, command, marker),
            cwd=str(working_directory),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        visible_stdout, final_cwd = _extract_cwd(_decode(stdout), marker, working_directory)
        return {
            "command": command,
            "shell": shell,
            "cwd": str(final_cwd),
            "return_code": process.returncode,
            "stdout": visible_stdout,
            "stderr": _decode(stderr),
            "duration": round(time.monotonic() - started, 2),
        }
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.communicate()
        return {
            "command": command,
            "shell": shell,
            "cwd": str(working_directory),
            "return_code": -1,
            "stdout": "",
            "stderr": f"명령 실행 시간이 {timeout}초를 초과했습니다.",
            "duration": round(time.monotonic() - started, 2),
        }
    except OSError as exc:
        return {
            "command": command,
            "shell": shell,
            "cwd": str(working_directory),
            "return_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "duration": round(time.monotonic() - started, 2),
        }
