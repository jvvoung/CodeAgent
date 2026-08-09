import hashlib
import json
import os
import threading
from pathlib import Path

from services.app_settings import get_int_setting


class ConversationStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            base = Path(os.getenv("LOCALAPPDATA") or os.getenv("TEMP") or ".") / "AURA"
            path = base / "conversations.json"
        self.path = path
        self._lock = threading.RLock()
        self._data = self._load()

    @staticmethod
    def _key(project: Path) -> str:
        normalized = str(project.resolve()).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and isinstance(data.get("projects"), dict) else {"projects": {}}
        except (OSError, ValueError, TypeError):
            return {"projects": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            # 기억 저장 실패가 에이전트 작업 자체를 막지는 않도록 메모리 상태는 유지합니다.
            pass

    def messages(self, project: Path) -> list[dict[str, str]]:
        with self._lock:
            item = self._data["projects"].get(self._key(project), {})
            messages = item.get("messages", []) if isinstance(item, dict) else []
            return [dict(message) for message in messages if message.get("role") in ("user", "assistant") and isinstance(message.get("content"), str)]

    def context(self, project: Path, max_messages: int = 16, max_chars: int | None = None) -> list[dict[str, str]]:
        if max_chars is None:
            max_chars = get_int_setting("AURA_HISTORY_MAX_CHARS", 12_000, 4_000, 100_000)
        selected: list[dict[str, str]] = []
        total = 0
        for message in reversed(self.messages(project)):
            content = message["content"]
            if selected and (len(selected) >= max_messages or total + len(content) > max_chars):
                break
            selected.append(message)
            total += len(content)
        selected.reverse()
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)
        return selected

    def append_turn(self, project: Path, user_message: str, assistant_message: str) -> None:
        user_message = user_message.strip()[:20_000]
        assistant_message = assistant_message.strip()[:20_000]
        if not user_message or not assistant_message:
            return
        with self._lock:
            key = self._key(project)
            item = self._data["projects"].setdefault(key, {"path": str(project), "messages": []})
            item["path"] = str(project)
            item["messages"].extend([
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ])
            item["messages"] = item["messages"][-100:]
            self._save()

    def clear(self, project: Path) -> None:
        with self._lock:
            self._data["projects"].pop(self._key(project), None)
            self._save()


conversations = ConversationStore()
