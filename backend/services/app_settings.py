from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"

SETTING_PATHS: dict[str, tuple[str, ...]] = {
    "OLLAMA_BASE_URL": ("ollama", "base_url"),
    "OLLAMA_NUM_CTX": ("ollama", "num_ctx"),
    "AURA_AGENT_TIMEOUT_SECONDS": ("agent", "timeout_seconds"),
    "AURA_AGENT_MAX_STEPS": ("agent", "max_steps"),
    "AURA_VALIDATION_REPAIR_ATTEMPTS": ("agent", "validation_repair_attempts"),
    "AURA_EVIDENCE_MAX_FILES": ("evidence", "max_files"),
    "AURA_EVIDENCE_MAX_CHARS": ("evidence", "max_chars"),
    "AURA_EVIDENCE_MAX_FILE_CHARS": ("evidence", "max_file_chars"),
    "AURA_HISTORY_MAX_CHARS": ("conversation", "history_max_chars"),
    # 아래 키는 이전 변경 생성 경로와 호환하기 위해 환경 변수 지원만 유지합니다.
    "AURA_CHANGE_EVIDENCE_MAX_FILES": ("legacy", "change_evidence_max_files"),
    "AURA_CHANGE_EVIDENCE_MAX_CHARS": ("legacy", "change_evidence_max_chars"),
    "AURA_CHANGE_EVIDENCE_MAX_FILE_CHARS": ("legacy", "change_evidence_max_file_chars"),
    "AURA_PROPOSAL_ATTEMPTS": ("legacy", "proposal_attempts"),
}


def settings_path() -> Path:
    configured = os.getenv("AURA_SETTINGS_FILE", "").strip()
    if not configured:
        return DEFAULT_SETTINGS_PATH
    path = Path(configured).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else (PROJECT_ROOT / path).resolve(strict=False)


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        if os.getenv("AURA_SETTINGS_FILE", "").strip():
            raise ValueError(f"AURA 설정 파일을 찾을 수 없습니다: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"AURA 설정 파일의 JSON 형식이 올바르지 않습니다: {path} ({exc})") from exc
    except OSError as exc:
        raise ValueError(f"AURA 설정 파일을 읽을 수 없습니다: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"AURA 설정 파일의 최상위 값은 JSON 객체여야 합니다: {path}")
    return payload


def _file_value(name: str, default: Any) -> Any:
    path = SETTING_PATHS.get(name)
    if not path:
        return default
    value: Any = load_settings()
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def get_string_setting(name: str, default: str) -> str:
    file_value = _file_value(name, default)
    environment_value = os.getenv(name)
    candidate = environment_value if environment_value is not None else file_value
    rendered = str(candidate).strip()
    if rendered:
        return rendered
    fallback = str(file_value).strip()
    return fallback or default


def get_int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    file_value = _file_value(name, default)
    environment_value = os.getenv(name)
    candidate = environment_value if environment_value is not None else file_value
    try:
        value = int(candidate)
    except (TypeError, ValueError):
        try:
            value = int(file_value)
        except (TypeError, ValueError):
            value = default
    return min(max(value, minimum), maximum)
