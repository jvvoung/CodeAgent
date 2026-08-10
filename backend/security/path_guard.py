import subprocess
from pathlib import Path


class PathGuard:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.git_root: Path | None = None

    @staticmethod
    def _git_root_from_cli(path: Path) -> Path | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        candidate = Path(result.stdout.strip()).expanduser().resolve(strict=False)
        return candidate if candidate == path or candidate in path.parents else None

    @staticmethod
    def _git_root_from_parents(path: Path) -> Path | None:
        current = path
        while True:
            if (current / ".git").exists():
                return current
            if current.parent == current:
                return None
            current = current.parent

    def discover_git_root(self, path: Path) -> Path | None:
        return self._git_root_from_cli(path) or self._git_root_from_parents(path)

    def open(self, raw: str) -> Path:
        if not raw.strip():
            raise ValueError("프로젝트 폴더 경로가 필요합니다.")
        path = Path(raw).expanduser().resolve(strict=False)
        if not path.is_dir():
            raise ValueError("프로젝트 폴더가 존재하지 않습니다.")
        self.root = path
        self.git_root = self.discover_git_root(path)
        return path

    def resolve(self, raw: str) -> Path:
        if not self.root:
            raise ValueError("먼저 프로젝트를 열어주세요.")
        candidate = Path(raw)
        path = candidate.resolve(strict=False) if candidate.is_absolute() else (self.root / candidate).resolve(strict=False)
        if path != self.root and self.root not in path.parents:
            raise ValueError("프로젝트 루트 밖의 경로에는 접근할 수 없습니다.")
        return path

    def relative(self, path: Path) -> str:
        if not self.root:
            raise ValueError("먼저 프로젝트를 열어주세요.")
        return path.relative_to(self.root).as_posix()

guard = PathGuard()
