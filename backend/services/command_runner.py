import asyncio
import time


async def run_command(command: list[str], cwd: str, timeout: int = 120) -> dict:
    started = time.monotonic()
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), timeout)
        return {
            "command": " ".join(command),
            "return_code": process.returncode,
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
            "duration": round(time.monotonic() - started, 2),
        }
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.communicate()
        return {
            "command": " ".join(command),
            "return_code": -1,
            "stdout": "",
            "stderr": f"명령 실행 시간이 {timeout}초를 초과했습니다.",
            "duration": round(time.monotonic() - started, 2),
        }
    except OSError as exc:
        return {
            "command": " ".join(command),
            "return_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "duration": round(time.monotonic() - started, 2),
        }
