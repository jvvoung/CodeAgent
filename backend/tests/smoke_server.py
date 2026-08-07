"""Start Uvicorn briefly and verify that it runs on the active Python runtime."""

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8010"],
        cwd=backend,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read() if process.stderr else "Uvicorn exited early")
            try:
                with urlopen("http://127.0.0.1:8010/api/health", timeout=1) as response:
                    health = json.load(response)
                assert health["python"].startswith("3.10."), health
                print(f"Uvicorn smoke test passed on Python {health['python']}")
                return
            except OSError:
                time.sleep(0.25)
        raise TimeoutError("Uvicorn startup timed out")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
