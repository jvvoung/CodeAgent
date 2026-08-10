from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict


UserRole = Literal["developer", "non-developer"]
DEFAULT_REGISTRATION_ROLE: UserRole = "non-developer"
USERS_FILE = Path(__file__).resolve().parents[2] / "config" / "users.json"


class StoredUser(TypedDict, total=False):
    id: str
    password: str
    password_hash: str
    role: UserRole


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    role: UserRole
    token: str


def verify_password(candidate: str, user: StoredUser) -> bool:
    """Password verification boundary; replace this body with bcrypt later."""
    stored = user.get("password")
    return isinstance(stored, str) and secrets.compare_digest(stored, candidate)


class UserStore:
    """Single read/write boundary for the JSON user store."""

    def __init__(self, path: Path = USERS_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _read_unlocked(self) -> list[StoredUser]:
        if not self.path.is_file():
            raise RuntimeError(f"사용자 정보 파일을 찾을 수 없습니다: {self.path}")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("사용자 정보 파일을 읽을 수 없습니다.") from exc
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, list):
            raise RuntimeError("사용자 정보 파일 형식이 올바르지 않습니다.")
        validated: list[StoredUser] = []
        for value in users:
            if not isinstance(value, dict):
                raise RuntimeError("사용자 정보 파일 형식이 올바르지 않습니다.")
            user_id = value.get("id")
            role = value.get("role")
            if not isinstance(user_id, str) or role not in ("developer", "non-developer"):
                raise RuntimeError("사용자 정보 파일 형식이 올바르지 않습니다.")
            validated.append(value)  # type: ignore[arg-type]
        return validated

    def users(self) -> list[StoredUser]:
        with self._lock:
            return self._read_unlocked()

    def find(self, user_id: str) -> StoredUser | None:
        return next((user for user in self.users() if user["id"] == user_id), None)

    def id_exists(self, user_id: str) -> bool:
        return self.find(user_id) is not None

    def authenticate(self, user_id: str, password: str) -> StoredUser | None:
        user = self.find(user_id)
        return user if user and verify_password(password, user) else None

    def add_registered_user(self, user_id: str, password_value: str, *, hashed: bool = False) -> StoredUser:
        """Future registration seam. The client cannot choose a privileged role."""
        with self._lock:
            users = self._read_unlocked()
            if any(user["id"] == user_id for user in users):
                raise ValueError("이미 사용 중인 아이디입니다.")
            user: StoredUser = {"id": user_id, "role": DEFAULT_REGISTRATION_ROLE}
            user["password_hash" if hashed else "password"] = password_value
            users.append(user)
            self._write_unlocked(users)
            return user

    def _write_unlocked(self, users: list[StoredUser]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({"users": users}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class AuthService:
    def __init__(self, users: UserStore | None = None) -> None:
        self.users = users or UserStore()
        self._sessions: dict[str, tuple[str, UserRole]] = {}
        self._session_lock = threading.RLock()

    def login(self, user_id: str, password: str) -> AuthenticatedUser | None:
        stored = self.users.authenticate(user_id, password)
        if not stored:
            return None
        token = secrets.token_urlsafe(32)
        with self._session_lock:
            self._sessions[token] = (stored["id"], stored["role"])
        return AuthenticatedUser(stored["id"], stored["role"], token)

    def session(self, token: str) -> AuthenticatedUser | None:
        with self._session_lock:
            value = self._sessions.get(token)
        return AuthenticatedUser(value[0], value[1], token) if value else None

    def logout(self, token: str) -> None:
        with self._session_lock:
            self._sessions.pop(token, None)


auth_service = AuthService()
