from pathlib import Path


class PathGuard:
    def __init__(self) -> None:
        self.root: Path | None = None

    def open(self, raw: str) -> Path:
        if not raw.strip():
            raise ValueError("프로젝트 폴더 경로가 필요합니다.")
        path = Path(raw).expanduser().resolve(strict=False)
        if not path.is_dir():
            raise ValueError("프로젝트 폴더가 존재하지 않습니다.")
        self.root = path
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
