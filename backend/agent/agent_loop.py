import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable

from llm.ollama_client import OllamaClient
from models.schemas import ProposedFile
from agent.retrieval import collect_repository_evidence
from agent.tool_agent import run_change_agent
from security.path_guard import guard
from services.conversation_store import conversations
from services.proposal_validator import validate_proposal
from tools.file_tools import list_files, read_file, read_file_range, repository_map, resolve_source_file, search_code, search_regex
from tools.git_tools import commit as git_commit
from tools.git_tools import branches as git_branches
from tools.git_tools import checkout as git_checkout
from tools.git_tools import diff as git_diff
from tools.git_tools import repository_info as git_repository_info
from tools.git_tools import stage_all as git_stage_all
from tools.git_tools import status as git_status
from tools.git_tools import unstage_all as git_unstage_all
from tools.patch_tools import clear, preview, propose, propose_failed, reject

EXPLORATION_TOOLS = [
    {"type": "function", "function": {"name": "project_map", "description": "열린 프로젝트의 언어, 빌드 시스템, 매니페스트, 진입점과 최상위 구조를 간결하게 조회합니다. 프로젝트 종류를 파악할 때 사용하세요.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "list_files", "description": "파일명을 모르거나 구조 탐색이 필요할 때 수정 가능한 텍스트 소스 파일의 상대 경로 목록을 조회합니다. 동작이나 원인을 이 목록만으로 추측하지 마세요.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_code", "description": "프로젝트 전체에서 사용자 질문의 식별자, 오류 문구, 화면 문구, 함수명 또는 설정 키와 정확히 일치하는 문자열을 검색합니다. 검색 결과의 관련 파일을 반드시 읽고 답하세요.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "search_regex", "description": "정확한 검색으로 찾지 못했을 때 이름 변형, 선언, 호출 패턴을 대소문자 무시 정규식으로 검색합니다. C/C++ 헤더·구현, 함수·클래스·파일 API 추적에 사용할 수 있습니다.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "프로젝트 루트 기준 상대 경로의 UTF-8 텍스트 파일 전체를 읽습니다. 검색에서 찾은 구현과 호출 관계를 실제 코드로 확인할 때 사용하세요.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file_range", "description": "큰 소스 파일에서 필요한 줄 범위만 읽습니다. 검색 결과 줄 주변, 함수 구현, 호출부를 확인할 때 사용하세요.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path", "start_line", "end_line"]}}},
]

PROPOSE_TOOL = {"type": "function", "function": {
        "name": "propose_changes",
        "description": "검토 가능한 변경안을 생성합니다. path는 list_files의 상대 경로를 그대로 사용하고, old는 read_file에서 읽은 고유한 원문을 글자 하나까지 정확히 복사해야 합니다. 실제 파일에는 쓰지 않습니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "changes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                                    "required": ["old", "new"],
                                },
                            },
                        },
                        "required": ["path", "changes"],
                    },
                }
            },
            "required": ["files"],
        },
    }}


def _arguments(call: dict) -> dict:
    arguments = call.get("function", {}).get("arguments", {})
    return json.loads(arguments) if isinstance(arguments, str) else arguments


def _configuration_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _embedded_tool_calls(content: str, allowed_names: set[str]) -> list[dict]:
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content or "", re.DOTALL | re.IGNORECASE)
    stripped = (content or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name") or payload.get("tool")
        arguments = payload.get("arguments", payload.get("parameters", {}))
        if name in allowed_names and isinstance(arguments, dict):
            return [{"function": {"name": name, "arguments": arguments}}]
    return []


def _line_operation_change(source_lines: list[str], start_line: int, end_line: int, kind: str, content: str) -> dict[str, str]:
    source = "".join(source_lines)
    selected_start = start_line - 1
    selected_end = end_line
    context_start = selected_start
    context_end = selected_end
    expand_up_first = kind == "insert_after_line"
    expand_down_first = kind == "insert_before_line"
    while source.count("".join(source_lines[context_start:context_end])) != 1:
        expanded = False
        if (expand_up_first or not expand_down_first) and context_start > 0:
            context_start -= 1
            expanded = True
        if source.count("".join(source_lines[context_start:context_end])) == 1:
            break
        if context_end < len(source_lines):
            context_end += 1
            expanded = True
        if source.count("".join(source_lines[context_start:context_end])) == 1:
            break
        if not expand_up_first and context_start > 0:
            context_start -= 1
            expanded = True
        if not expanded:
            break

    anchor = "".join(source_lines[context_start:context_end])
    prefix = "".join(source_lines[context_start:selected_start])
    selected = "".join(source_lines[selected_start:selected_end])
    suffix = "".join(source_lines[selected_end:context_end])
    if source.count(anchor) != 1:
        raise ValueError("선택한 줄 주변에서 유일한 변경 위치를 만들 수 없습니다.")

    inserted = content
    if kind == "insert_after_line" and inserted and not selected.endswith(("\n", "\r")) and not inserted.startswith(("\n", "\r")):
        inserted = "\n" + inserted
    if inserted and not inserted.endswith(("\n", "\r")) and (suffix or selected.endswith(("\n", "\r"))):
        inserted += "\n"
    if kind == "insert_after_line":
        replacement = prefix + selected + inserted + suffix
    elif kind == "insert_before_line":
        replacement = prefix + inserted + selected + suffix
    elif kind == "replace_lines":
        replacement = prefix + inserted + suffix
    else:
        replacement = prefix + suffix
    return {"old": anchor, "new": replacement}


def _line_operations_change(source: str, operations: list[dict]) -> dict[str, str]:
    """Apply non-overlapping operations against one immutable line-number coordinate system."""
    source_lines = source.splitlines(keepends=True)
    normalized: list[tuple[int, int, str, str]] = []
    for operation in operations:
        kind = str(operation.get("op", "")).strip().casefold()
        try:
            start_line = int(operation.get("start_line"))
            end_line = int(operation.get("end_line"))
        except (TypeError, ValueError) as exc:
            raise ValueError("줄 기반 변경 연산에는 올바른 start_line과 end_line이 필요합니다.") from exc
        if start_line < 1 or end_line < start_line or end_line > len(source_lines):
            raise ValueError(f"변경 줄 범위가 파일 범위를 벗어났습니다: {start_line}-{end_line}")
        content = operation.get("content", "")
        if not isinstance(content, str):
            raise ValueError("변경 연산의 content는 문자열이어야 합니다.")
        normalized.append((start_line - 1, end_line, kind, content))

    ordered = sorted(normalized, key=lambda item: (item[0], item[1]))
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError(
                f"같은 파일의 변경 줄 범위가 겹칩니다: {previous[0] + 1}-{previous[1]}, {current[0] + 1}-{current[1]}"
            )

    modified_lines = list(source_lines)
    for start, end, kind, content in reversed(ordered):
        selected = "".join(source_lines[start:end])
        inserted = content
        if kind == "insert_after_line" and inserted and not selected.endswith(("\n", "\r")) and not inserted.startswith(("\n", "\r")):
            inserted = "\n" + inserted
        if inserted and not inserted.endswith(("\n", "\r")):
            inserted += "\n"
        if kind == "insert_after_line":
            replacement = selected + inserted
        elif kind == "insert_before_line":
            replacement = inserted + selected
        elif kind == "replace_lines":
            replacement = inserted
        elif kind == "delete_lines":
            replacement = ""
        else:
            raise ValueError(f"지원하지 않는 줄 기반 변경 연산입니다: {kind or '이름 없음'}")
        modified_lines[start:end] = replacement.splitlines(keepends=True)
    return {"old": source, "new": "".join(modified_lines)}


def _proposal_files(arguments: dict) -> list[ProposedFile]:
    if not isinstance(arguments, dict):
        raise ValueError("변경안 인수는 객체 형식이어야 합니다.")

    for _ in range(3):
        nested = arguments.get("arguments")
        if "files" not in arguments and isinstance(nested, dict):
            arguments = nested
            continue
        break

    raw_files = arguments.get("files")
    if not raw_files:
        raw_files = arguments.get("file")
    if not raw_files and "path" in arguments:
        raw_files = arguments
    if not raw_files:
        raise ValueError("변경할 파일 정보가 없습니다. files 또는 path를 포함해야 합니다.")

    if isinstance(raw_files, dict):
        raw_files = [raw_files]
    if not isinstance(raw_files, list):
        raise ValueError("files는 파일 객체의 배열이어야 합니다.")

    normalized: list[ProposedFile] = []
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            raise ValueError("각 변경 파일은 path와 changes를 가진 객체여야 합니다.")
        item = dict(raw_file)
        changes = item.get("changes")
        operations = item.pop("operations", None)
        if changes is None and operations is not None:
            if not isinstance(operations, list):
                raise ValueError("operations는 변경 연산 객체의 배열이어야 합니다.")
            changes = []
            line_kinds = {"insert_after_line", "insert_before_line", "replace_lines", "delete_lines"}
            if operations and all(
                isinstance(operation, dict) and str(operation.get("op", "")).strip().casefold() in line_kinds
                for operation in operations
            ):
                source = read_file(str(item.get("path", "")))
                changes = [_line_operations_change(source, operations)]
                item["changes"] = changes
                normalized.append(ProposedFile(**item))
                continue
            source_lines: list[str] | None = None
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ValueError("각 변경 연산은 객체여야 합니다.")
                kind = str(operation.get("op", "")).strip().casefold()
                if kind in {"insert_after_line", "insert_before_line", "replace_lines", "delete_lines"}:
                    if source_lines is None:
                        source_lines = read_file(str(item.get("path", ""))).splitlines(keepends=True)
                    try:
                        start_line = int(operation.get("start_line"))
                        end_line = int(operation.get("end_line"))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("줄 기반 변경 연산에는 올바른 start_line과 end_line이 필요합니다.") from exc
                    if start_line < 1 or end_line < start_line or end_line > len(source_lines):
                        raise ValueError(f"변경 줄 범위가 파일 범위를 벗어났습니다: {start_line}-{end_line}")
                    content = operation.get("content", "")
                    if not isinstance(content, str):
                        raise ValueError("변경 연산의 content는 문자열이어야 합니다.")
                    changes.append(_line_operation_change(source_lines, start_line, end_line, kind, content))
                    continue
                anchor = operation.get("anchor")
                content = operation.get("content", "")
                if not isinstance(anchor, str) or not anchor:
                    raise ValueError("변경 연산에는 실제 코드에서 복사한 anchor가 필요합니다.")
                if not isinstance(content, str):
                    raise ValueError("변경 연산의 content는 문자열이어야 합니다.")
                if kind == "insert_after":
                    changes.append({"old": anchor, "new": anchor + content})
                elif kind == "insert_before":
                    changes.append({"old": anchor, "new": content + anchor})
                elif kind == "replace":
                    changes.append({"old": anchor, "new": content})
                elif kind == "delete":
                    changes.append({"old": anchor, "new": ""})
                else:
                    raise ValueError(f"지원하지 않는 변경 연산입니다: {kind or '이름 없음'}")
        if changes is None and "old" in item and "new" in item:
            changes = [{"old": item.pop("old"), "new": item.pop("new")}]
        elif isinstance(changes, dict):
            changes = [changes]
        item["changes"] = changes
        normalized.append(ProposedFile(**item))
    return normalized


EventCallback = Callable[[dict[str, str]], Awaitable[None]]


def _korean_response(content: str, proposal_created: bool = False) -> str:
    text = (content or "").strip()
    if not text:
        return "변경 제안을 준비했습니다. 오른쪽 변경 제안 탭에서 확인해 주세요." if proposal_created else "요청 처리를 완료했습니다."
    hangul = len(re.findall(r"[가-힣]", text))
    han = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
    japanese = len(re.findall(r"[\u3040-\u30ff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if japanese >= 2 or han >= 2 or (latin > 60 and hangul < 4):
        return "변경 제안을 준비했습니다. 오른쪽 변경 제안 탭에서 확인해 주세요." if proposal_created else "모델이 한국어가 아닌 응답을 생성하여 표시하지 않았습니다. 요청 내용을 다시 확인해 주세요."
    return text


def _requests_change(message: str) -> bool:
    lowered = message.casefold()
    korean_intents = ("변경", "바꿔", "수정", "추가", "삭제", "제거", "교체", "고쳐", "만들어")
    english_intents = ("change", "replace", "edit", "modify", "rename", "remove", "delete", "add", "fix")
    return any(intent in lowered for intent in (*korean_intents, *english_intents))


def _requires_repository_evidence(message: str) -> bool:
    lowered = message.casefold()
    repository_terms = (
        "프로젝트", "코드", "소스", "파일", "경로", "폴더", "함수", "메서드", "클래스", "변수",
        "설정", "저장", "생성", "호출", "참조", "정의", "구현", "동작", "실행", "빌드", "테스트",
        "오류", "에러", "예외", "로그", "api", "endpoint", "route", "symbol", "function", "class",
        "method", "config", "path", "build", "compile", "runtime", "cmake", "makefile",
    )
    if _requests_change(message) or any(term in lowered for term in repository_terms):
        return True
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_:<>.]{2,}\b", message) and any(word in lowered for word in ("어디", "어떻게", "왜", "뭐", "무엇")):
        return True
    return any(term in lowered for term in ("안 돼", "안돼", "실패해", "깨져", "크래시", "멈춰"))


def _requires_source_read(message: str) -> bool:
    lowered = message.casefold()
    behavior_terms = (
        "어디", "경로", "왜", "원인", "어떻게", "동작", "실행", "호출", "참조", "정의", "구현",
        "저장", "생성", "읽", "쓰", "변환", "처리", "오류", "에러", "예외", "버그", "흐름",
        "위치", "기록",
        "where", "why", "how", "path", "call", "reference", "implementation", "error", "flow",
    )
    return any(term in lowered for term in behavior_terms)


def _is_evasive_response(content: str) -> bool:
    lowered = (content or "").casefold()
    phrases = (
        "정보를 더", "더 많은 정보", "구체적으로 알려", "알려주시면", "제공해 주시면", "제공해주시면",
        "어떤 종류의", "특정 위치가 있다면", "확인할 수 없습니다", "도와드릴 수 있을",
        "more information", "please provide", "could you clarify", "cannot determine",
    )
    return any(phrase in lowered for phrase in phrases)


def _contains_tool_markup(content: str) -> bool:
    names = "project_map|list_files|search_code|search_regex|read_file|read_file_range|propose_changes"
    return bool(re.search(rf'"(?:name|tool)"\s*:\s*"(?:{names})"', content or "", re.IGNORECASE))


def _required_change_paths(message: str, evidence: dict) -> list[str]:
    lowered = message.casefold()
    required: list[str] = []
    for item in evidence.get("files", []):
        path = str(item.get("path", ""))
        filename = path.rsplit("/", 1)[-1]
        if path and (path.casefold() in lowered or filename.casefold() in lowered):
            required.append(path)
    return required


def _ungrounded_identifiers(content: str, project_map: dict, evidence: dict) -> list[str]:
    source = json.dumps({"project_map": project_map, "evidence": evidence}, ensure_ascii=False).casefold()
    candidates = set(re.findall(r"`([^`\n]{2,160})`", content or ""))
    candidates.update(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:(?:::|->|\.)[A-Za-z_][A-Za-z0-9_]*)+\b", content or ""))
    candidates.update(re.findall(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b", content or ""))
    return sorted(candidate for candidate in candidates if candidate.casefold() not in source)


def _commit_message(message: str) -> str:
    quoted = re.search(r'["“”\']([^"“”\']+)["“”\']', message)
    if quoted:
        return quoted.group(1).strip()
    match = re.search(r"(?:제목|메시지|message)\s*(?:은|는|:|=)?\s*(.+)$", message, re.IGNORECASE)
    return match.group(1).strip().rstrip(".") if match else ""


def _checkout_branch(message: str) -> str:
    patterns = (
        r"(?:체크아웃|checkout|switch)\s+(?:브랜치\s*)?([A-Za-z0-9._/-]+)",
        r"(?:브랜치|branch)\s*(?:를|을)?\s*([A-Za-z0-9._/-]+)\s*(?:로|으로)?\s*(?:전환|변경|체크아웃|switch)",
        r"([A-Za-z0-9._/-]+)\s*(?:브랜치|branch)\s*(?:로|으로)?\s*(?:전환|변경|체크아웃|switch)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _direct_git_intent(message: str) -> tuple[str, str] | None:
    lowered = message.casefold()
    git_words = ("git", "깃", "커밋", "commit", "스테이징", "stage", "브랜치", "branch", "체크아웃", "checkout", "푸시", "푸쉬", "push", "diff", "차이", "상태", "status")
    if not any(word in lowered for word in git_words):
        return None
    if "푸시" in lowered or "푸쉬" in lowered or "push" in lowered:
        return "push", ""
    if "커밋" in lowered or "commit" in lowered:
        return "commit", _commit_message(message)
    if "스테이징 해제" in lowered or "스테이지 해제" in lowered or "unstage" in lowered:
        return "unstage", ""
    if "diff" in lowered or "차이" in lowered or "변경 내역" in lowered:
        return "diff_staged" if any(word in lowered for word in ("스테이징", "스테이지", "staged", "cached")) else "diff", ""
    if "스테이징" in lowered or "스테이지" in lowered or re.search(r"\bstage\b", lowered):
        return "stage", ""
    if any(word in lowered for word in ("체크아웃", "checkout", "switch")) or ("브랜치" in lowered and any(word in lowered for word in ("전환", "변경", "바꿔"))):
        return "checkout", _checkout_branch(message)
    if ("브랜치" in lowered or "branch" in lowered) and any(word in lowered for word in ("목록", "리스트", "보여", "알려", "현재", "확인", "list")):
        return "branches", ""
    if "상태" in lowered or "status" in lowered:
        return "status", ""
    return None


def _awaiting_commit_message(history: list[dict[str, str]]) -> bool:
    if len(history) < 2:
        return False
    previous_user, previous_assistant = history[-2], history[-1]
    return (
        previous_user.get("role") == "user"
        and previous_assistant.get("role") == "assistant"
        and _direct_git_intent(previous_user.get("content", "")) == ("commit", "")
        and "커밋 메시지가 필요" in previous_assistant.get("content", "")
    )


def _standalone_commit_message(message: str) -> str:
    text = message.strip()
    if len(text) >= 2 and text[0] in "\"'“”" and text[-1] in "\"'“”":
        text = text[1:-1].strip()
    return text[:500]


async def _direct_git_response(message: str, on_event: EventCallback | None = None) -> dict | None:
    intent = _direct_git_intent(message)
    if not intent:
        return None
    action, value = intent
    events: list[dict[str, str]] = []

    async def execute(tool: str, operation) -> dict:
        event = {"tool": tool, "status": "completed"}
        try:
            result = await operation
            if isinstance(result, dict) and result.get("return_code", 0) != 0:
                event["status"] = "failed"
                event["detail"] = (result.get("stderr") or result.get("stdout") or "Git 명령에 실패했습니다.").strip()
        except Exception as exc:
            event["status"] = "failed"
            event["detail"] = str(exc).strip() or "Git 명령에 실패했습니다."
            result = {"command": tool, "return_code": -1, "stdout": "", "stderr": event["detail"], "duration": 0}
        events.append(event)
        if on_event:
            await on_event(event)
        return result

    if action == "push":
        info = await execute("git_status", git_repository_info())
        if events[-1]["status"] == "failed":
            return {"message": f"Push 준비에 실패했습니다: {events[-1]['detail']}", "events": events, "relevant_files": [], "git_result": info}
        if not info.get("remote"):
            return {"message": "origin 원격 저장소가 설정되어 있지 않아 Push할 수 없습니다.", "events": events, "relevant_files": []}
        return {
            "message": f"{info['branch']} 브랜치를 {info['remote']}에 Push하려면 확인해 주세요.",
            "events": events,
            "relevant_files": [],
            "pending_git_action": {"type": "push", "branch": info["branch"], "remote": info["remote"]},
        }

    if action == "commit":
        if not value:
            return {"message": "커밋 메시지가 필요합니다. 예: 현재 코드를 커밋해줘. 제목은 \"로그인 오류 수정\"", "events": [], "relevant_files": []}
        info = await execute("git_status", git_repository_info())
        if events[-1]["status"] == "failed":
            return {"message": f"Git 상태 확인에 실패했습니다: {events[-1]['detail']}", "events": events, "relevant_files": [], "git_result": info}
        if not info.get("has_changes"):
            return {"message": "커밋할 변경사항이 없습니다.", "events": events, "relevant_files": [], "git_result": info}
        if info.get("has_unstaged"):
            staged = await execute("git_stage_all", git_stage_all())
            if events[-1]["status"] == "failed":
                return {"message": f"스테이징에 실패했습니다: {events[-1]['detail']}", "events": events, "relevant_files": [], "git_result": staged}
        result = await execute("git_commit", git_commit(value))
        if events[-1]["status"] == "failed":
            return {"message": f"커밋에 실패했습니다: {events[-1]['detail']}", "events": events, "relevant_files": [], "git_result": result}
        return {"message": f'현재 변경사항을 "{value}" 제목으로 커밋했습니다.', "events": events, "relevant_files": [], "git_result": result, "git_changed": True}

    if action == "stage":
        result = await execute("git_stage_all", git_stage_all())
        message_text = "현재 변경사항을 모두 스테이징했습니다." if events[-1]["status"] == "completed" else f"스테이징에 실패했습니다: {events[-1]['detail']}"
        return {"message": message_text, "events": events, "relevant_files": [], "git_result": result, "git_changed": events[-1]["status"] == "completed"}
    if action == "unstage":
        result = await execute("git_unstage_all", git_unstage_all())
        message_text = "모든 파일의 스테이징을 해제했습니다." if events[-1]["status"] == "completed" else f"스테이징 해제에 실패했습니다: {events[-1]['detail']}"
        return {"message": message_text, "events": events, "relevant_files": [], "git_result": result, "git_changed": events[-1]["status"] == "completed"}
    if action == "checkout":
        if not value:
            return {"message": "전환할 브랜치 이름을 알려주세요. 예: feature/login 브랜치로 전환해줘", "events": [], "relevant_files": []}
        result = await execute("git_checkout", git_checkout(value))
        if events[-1]["status"] == "completed":
            clear()
        message_text = f"{value} 브랜치로 전환했습니다." if events[-1]["status"] == "completed" else f"브랜치 전환에 실패했습니다: {events[-1]['detail']}"
        return {"message": message_text, "events": events, "relevant_files": [], "git_result": result, "git_changed": events[-1]["status"] == "completed", "project_changed": events[-1]["status"] == "completed"}
    if action == "branches":
        result = await execute("git_branches", git_branches())
        if events[-1]["status"] == "failed":
            return {"message": f"브랜치 조회에 실패했습니다: {events[-1]['detail']}", "events": events, "relevant_files": []}
        names = ", ".join(result.get("branches", [])) or "없음"
        return {"message": f"현재 브랜치는 {result.get('current', 'HEAD')}입니다. 사용 가능한 브랜치: {names}", "events": events, "relevant_files": []}
    if action in ("diff", "diff_staged"):
        result = await execute("git_diff", git_diff(staged=action == "diff_staged"))
        message_text = "Git 변경 내역을 아래 Git 결과 창에 표시했습니다." if events[-1]["status"] == "completed" else f"Git Diff 조회에 실패했습니다: {events[-1]['detail']}"
        return {"message": message_text, "events": events, "relevant_files": [], "git_result": result}
    result = await execute("git_status", git_status())
    message_text = "Git 상태를 아래 Git 결과 창에 표시했습니다." if events[-1]["status"] == "completed" else f"Git 상태 확인에 실패했습니다: {events[-1]['detail']}"
    return {"message": message_text, "events": events, "relevant_files": [], "git_result": result}


async def run_agent(message: str, model: str, on_event: EventCallback | None = None):
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    project = guard.root

    def finish(result: dict) -> dict:
        events = result.get("events", [])
        workspace_started = any(item.get("tool") == "workspace" for item in events)
        proposal_created = any(
            item.get("tool") == "propose_changes" and item.get("status") == "completed"
            for item in events
        )
        if not workspace_started or proposal_created:
            conversations.append_turn(project, message, str(result.get("message", "")))
        return result

    history = conversations.messages(project)
    direct_message = message
    if _direct_git_intent(message) is None and _awaiting_commit_message(history):
        if any(word in message.casefold() for word in ("취소", "안 할", "안할", "cancel")):
            return finish({"message": "Git 커밋 요청을 취소했습니다.", "events": [], "relevant_files": []})
        title = _standalone_commit_message(message)
        if title:
            direct_message = f'커밋 메시지는 "{title}"'
    direct_git = await _direct_git_response(direct_message, on_event)
    if direct_git is not None:
        return finish(direct_git)
    project_overview = repository_map()
    raw_context = conversations.context(project)
    failed_turn_markers = (
        "작업을 중단했습니다", "변경안을 만들지 못했습니다",
        "변경안 생성에 실패", "도구 호출 한도에 도달",
    )
    conversation_context: list[dict[str, str]] = []
    index = 0
    while index < len(raw_context):
        current = raw_context[index]
        following = raw_context[index + 1] if index + 1 < len(raw_context) else None
        if (
            current.get("role") == "user"
            and following
            and following.get("role") == "assistant"
            and any(marker in following.get("content", "") for marker in failed_turn_markers)
        ):
            index += 2
            continue
        conversation_context.append(current)
        index += 1
    if _requests_change(message):
        client = OllamaClient()
        local_map = {**project_overview, "absolute_root": project}
        try:
            timeout_seconds = int(os.getenv("AURA_AGENT_TIMEOUT_SECONDS", "180"))
        except ValueError:
            timeout_seconds = 180
        timeout_seconds = min(max(timeout_seconds, 60), 600)
        try:
            result = await asyncio.wait_for(run_change_agent(
                message=message,
                model=model,
                project_map=local_map,
                conversation_context=conversation_context,
                client=client,
                on_event=on_event,
            ), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            result = {
                "message": (
                    f"에이전트 작업이 {timeout_seconds}초 제한을 초과해 중단됐습니다. "
                    "현재 모델이 요청한 구조 변경을 제한 시간 안에 만들지 못했습니다. "
                    "요청을 더 작은 단계로 나누거나 더 큰 코딩 모델을 선택해 주세요."
                ),
                "events": [
                    {"tool": "workspace", "status": "completed"},
                    {"tool": "agent_timeout", "status": "failed"},
                ],
                "relevant_files": [],
            }
        return finish(result)
    events: list[dict[str, str]] = []
    relevant_files: list[str] = []
    failed_calls: dict[str, int] = {}
    completed_call_signatures: set[str] = set()
    missing_proposal_retries = 0
    change_requested = _requests_change(message)
    evidence_required = _requires_repository_evidence(message)
    source_read_required = evidence_required and _requires_source_read(message)
    evidence_retries = 0
    available_tools = [*EXPLORATION_TOOLS, PROPOSE_TOOL] if change_requested else EXPLORATION_TOOLS
    available_tool_names = {item["function"]["name"] for item in available_tools}
    client = OllamaClient()
    if "tools" not in await client.model_capabilities(model):
        raise ValueError(f"'{model}' 모델은 Agent 도구 호출을 지원하지 않습니다. 도구 지원 모델을 선택해 주세요.")

    automatic_evidence = {"queries": [], "match_count": 0, "matches": [], "files": []}
    if evidence_required:
        change_max_files = _configuration_int("AURA_CHANGE_EVIDENCE_MAX_FILES", 6, 1, 12) if change_requested else None
        change_max_chars = _configuration_int("AURA_CHANGE_EVIDENCE_MAX_CHARS", 24_000, 4_000, 100_000) if change_requested else None
        change_max_file_chars = _configuration_int("AURA_CHANGE_EVIDENCE_MAX_FILE_CHARS", 8_000, 1_000, 20_000) if change_requested else None
        automatic_evidence = collect_repository_evidence(
            message, max_files=change_max_files, max_chars=change_max_chars, max_file_chars=change_max_file_chars
        )
        if not automatic_evidence["files"]:
            planner = getattr(client, "plan_search_terms", None)
            try:
                planned_terms = await planner(model, message, project_overview) if planner else []
            except Exception:
                planned_terms = []
            if planned_terms:
                automatic_evidence = collect_repository_evidence(
                    message, planned_terms, max_files=change_max_files, max_chars=change_max_chars,
                    max_file_chars=change_max_file_chars,
                )
        if automatic_evidence["match_count"]:
            event = {"tool": "search_code", "status": "completed"}
            events.append(event)
            if on_event:
                await on_event(event)
        if automatic_evidence["files"]:
            event = {"tool": "read_file_range", "status": "completed"}
            events.append(event)
            if on_event:
                await on_event(event)
            relevant_files.extend(item["path"] for item in automatic_evidence["files"])

    model_evidence = {
        "queries": automatic_evidence["queries"],
        "files": automatic_evidence["files"],
    }
    if change_requested:
        model_evidence["required_change_paths"] = _required_change_paths(message, model_evidence)

    if evidence_required and not change_requested and automatic_evidence["files"]:
        answerer = getattr(client, "answer_from_evidence", None)
        validation_feedback = ""
        for attempt in range(2):
            try:
                if not answerer:
                    grounded_content = ""
                elif attempt == 0:
                    grounded_content = await answerer(model, message, project_overview, model_evidence, conversation_context)
                else:
                    grounded_content = await answerer(model, message, project_overview, model_evidence, conversation_context, validation_feedback)
            except Exception:
                grounded_content = ""
            grounded_answer = _korean_response(grounded_content)
            mentioned_file = any(item["path"].rsplit("/", 1)[-1].casefold() in grounded_answer.casefold() for item in automatic_evidence["files"])
            ungrounded = _ungrounded_identifiers(grounded_answer, project_overview, model_evidence)
            answer_is_grounded = grounded_answer and not ungrounded and not _is_evasive_response(grounded_answer) and not _contains_tool_markup(grounded_answer)
            if answer_is_grounded and not mentioned_file:
                source_paths = [item["path"] for item in automatic_evidence["files"][:3]]
                grounded_answer = f"{grounded_answer}\n\n근거 파일: {', '.join(source_paths)}"
                mentioned_file = True
            valid_answer = answer_is_grounded and mentioned_file
            if valid_answer:
                return finish({"message": grounded_answer, "events": events, "relevant_files": relevant_files})
            validation_feedback = (
                "이전 답변은 검증을 통과하지 못했습니다. 도구 호출이나 추가 질문 없이 다시 답하세요. "
                f"근거에서 확인되지 않은 식별자: {', '.join(ungrounded) if ungrounded else '없음'}. "
                "repository_evidence의 실제 함수·파일 이름만 복사하고 근거 파일 경로를 반드시 포함하세요."
            )

    proposal_generation_feedback = ""
    if change_requested and automatic_evidence["files"]:
        proposal_generator = getattr(client, "propose_from_evidence", None)
        proposal_attempts = _configuration_int("AURA_PROPOSAL_ATTEMPTS", 2, 1, 4)
        last_failed_preview: list[dict] = []
        last_failure_reason = ""
        for attempt in range(proposal_attempts):
            attempt_preview: list[dict] = []
            try:
                if not proposal_generator:
                    raise ValueError("구조화된 변경안 생성기를 사용할 수 없습니다.")
                if attempt == 0:
                    proposal_payload = await proposal_generator(
                        model, message, project_overview, model_evidence, conversation_context[-4:]
                    )
                else:
                    proposal_payload = await proposal_generator(
                        model, message, project_overview, model_evidence, conversation_context[-4:], proposal_generation_feedback
                    )
                proposal_files = _proposal_files(proposal_payload)
                proposed_paths = {item.path for item in proposal_files}
                missing_required = [
                    path for path in model_evidence.get("required_change_paths", []) if path not in proposed_paths
                ]
                if missing_required:
                    raise ValueError(f"필수 변경 파일이 누락되었습니다: {', '.join(missing_required)}")
                previewed = preview(proposal_files)
                attempt_preview = previewed
                if last_failed_preview:
                    reject([str(item["path"]) for item in last_failed_preview])
                last_failed_preview = previewed
                propose_failed(previewed, "변경안을 검증하고 있습니다.", message)
                reviewer = getattr(client, "review_proposal", None)
                if reviewer:
                    review = await reviewer(
                        model, message, project_overview, model_evidence, proposal_payload, previewed
                    )
                    if not review.get("complete"):
                        problems = [
                            *review.get("missing_requirements", []),
                            *review.get("unsafe_or_inconsistent_changes", []),
                        ]
                        files = review.get("files_needing_changes", [])
                        actionable = [str(item).strip() for item in problems if str(item).strip()]
                        if actionable:
                            detail = "; ".join(actionable)
                            if files:
                                detail += f" 다시 변경할 파일: {', '.join(str(path) for path in files)}"
                            raise ValueError(f"독립 변경안 검토 실패: {detail}")
                validation = await validate_proposal(previewed)
                if not validation.get("ok"):
                    repairer = getattr(client, "repair_from_validation", None)
                    if not repairer:
                        raise ValueError(f"격리된 프로젝트 검증 실패: {validation.get('message', '빌드 또는 구문 검사에 실패했습니다.')}")
                    repaired_payload = await repairer(
                        model,
                        message,
                        proposal_payload,
                        previewed,
                        str(validation.get("message", "빌드 또는 구문 검사에 실패했습니다.")),
                    )
                    repaired_files = _proposal_files(repaired_payload)
                    repaired_preview = preview(repaired_files)
                    attempt_preview = repaired_preview
                    reject([str(item["path"]) for item in last_failed_preview])
                    last_failed_preview = repaired_preview
                    propose_failed(repaired_preview, "재생성한 변경안을 검증하고 있습니다.", message)
                    repaired_validation = await validate_proposal(repaired_preview)
                    if not repaired_validation.get("ok"):
                        raise ValueError(
                            f"격리된 프로젝트 검증 실패: {repaired_validation.get('message', '수리 후에도 빌드 또는 구문 검사에 실패했습니다.')}"
                        )
                    if reviewer:
                        repaired_review = await reviewer(
                            model, message, project_overview, model_evidence, repaired_payload, repaired_preview
                        )
                        if not repaired_review.get("complete"):
                            problems = [
                                *repaired_review.get("missing_requirements", []),
                                *repaired_review.get("unsafe_or_inconsistent_changes", []),
                            ]
                            files = [
                                str(path).strip() for path in repaired_review.get("files_needing_changes", [])
                                if str(path).strip()
                            ]
                            actionable = [str(item).strip() for item in problems if str(item).strip()]
                            if actionable:
                                detail = "; ".join(actionable)
                                if files:
                                    detail += f" 다시 변경할 파일: {', '.join(files)}"
                                raise ValueError(f"검증 오류 수리 후 독립 검토 실패: {detail}")
                    proposal_payload = repaired_payload
                    proposal_files = repaired_files
                    previewed = repaired_preview
                validation_event = {"tool": "validate_changes", "status": "completed"}
                events.append(validation_event)
                if on_event:
                    await on_event(validation_event)
                proposed = propose(proposal_files)
                event = {"tool": "propose_changes", "status": "completed"}
                events.append(event)
                if on_event:
                    await on_event(event)
                for item in proposed:
                    if item["path"] not in relevant_files:
                        relevant_files.append(item["path"])
                return finish({
                    "message": "검토 가능한 변경안을 만들었습니다. 변경 제안 탭에서 전후 코드를 확인한 뒤 적용해 주세요.",
                    "events": events,
                    "relevant_files": relevant_files,
                })
            except Exception as exc:
                current_failure_reason = str(exc).strip() or "알 수 없는 오류"
                if attempt_preview or not last_failure_reason:
                    last_failure_reason = current_failure_reason
                if attempt_preview:
                    propose_failed(attempt_preview, current_failure_reason, message)
                proposal_generation_feedback = (
                    f"이전 변경안이 서버 검증에 실패했습니다: {current_failure_reason}. "
                    "실패 원인을 반영해 파일 계획과 줄 기반 operations를 다시 생성하세요. "
                    "repository_evidence의 실제 path와 표시된 줄 번호만 사용하고 전체 파일을 다시 작성하지 마세요."
                )
                if isinstance(exc, TimeoutError):
                    break
        if proposal_generation_feedback:
            detail = last_failure_reason or proposal_generation_feedback.removeprefix("이전 변경안이 서버 검증에 실패했습니다: ").strip()
            if last_failed_preview:
                propose_failed(last_failed_preview, last_failure_reason or detail, message)
                for item in last_failed_preview:
                    if item["path"] not in relevant_files:
                        relevant_files.append(item["path"])
            event = {"tool": "propose_changes", "status": "failed", "detail": detail}
            events.append(event)
            if on_event:
                await on_event(event)
            return finish({
                "message": "변경안 검증에 실패했습니다. 실패한 전후 코드와 자세한 진단을 변경 제안 탭에 보존했습니다. 다시 생성하거나 폐기해 주세요.",
                "events": events,
                "relevant_files": relevant_files,
            })

    evidence_message = []
    if automatic_evidence["files"]:
        evidence_message = [{"role": "system", "content": (
            "AURA가 현재 저장소에서 사용자 질문과 관련된 코드를 자동 조사했습니다. 다음 근거를 우선 사용해 질문에 직접 답하고, "
            "불충분할 때만 추가 도구를 호출하세요. 검색 목록 자체가 아니라 files의 실제 코드 구간을 근거로 삼으세요: "
            f"{json.dumps(model_evidence, ensure_ascii=False)} "
            f"구조화된 변경안 생성 단계의 검증 피드백: {proposal_generation_feedback or '없음'}"
        )}]
    messages = [{"role": "system", "content": (
            "당신은 현재 열린 저장소를 직접 조사하는 로컬 코딩 에이전트입니다. 최종 답변과 사용자에게 보이는 모든 설명은 반드시 자연스러운 한국어로만 작성하세요. "
            "중국어, 일본어, 영어 문장으로 답하지 마세요. 단, 코드·식별자·파일 경로는 원문을 유지하세요. "
            "프로젝트의 코드, 동작, 구조, 경로, 원인에 관한 질문에는 일반 지식이나 추측으로 답하지 말고 반드시 현재 저장소 도구로 근거를 조사하세요. "
            "사용자에게 다시 물어보기 전에 질문에 포함된 식별자·오류 문구·설정 키·화면 문구를 검색하세요. 정확한 검색 결과가 없으면 정규식과 프로젝트 구조로 범위를 넓히세요. "
            "언어나 프레임워크에 의존하지 말고 정의, 구현, 호출부, 설정, 파일 입출력 흐름을 따라가세요. C/C++에서는 헤더와 구현, CMake·MSBuild 매니페스트 및 참조를 함께 확인하세요. "
            "검색 결과나 파일 목록만으로 동작을 추측하지 말고 관련 구현 파일을 read_file 또는 read_file_range로 읽은 뒤 답하세요. "
            "최종 답변에는 결론을 먼저 쓰고, 근거가 된 상대 파일 경로와 확인한 코드 흐름을 간결하게 포함하세요. 근거를 찾지 못했다면 무엇을 검색했는지 밝히고 추측하지 마세요. "
            "변경 요청은 관련 구현을 읽은 뒤 read_file에서 확인한 고유한 원문을 정확히 복사하여 propose_changes를 호출하세요. "
            "도구가 실패하면 같은 인수로 반복 호출하지 말고 오류 원인을 반영해 다른 검색어나 정확한 경로로 한 번만 수정해서 재시도하세요. "
            "일반 셸 명령을 실행하거나 프로젝트 밖의 경로에 접근하지 마세요. Git 작업은 전용 처리 경로만 사용합니다. Push를 수행했다고 임의로 주장하지 마세요. "
            "변경안이 실제 적용됐다고 주장하지 마세요. 이전 대화의 사용자 의도는 기억으로 활용할 수 있지만 이전 AI 답변은 코드 근거가 아닙니다. 파일 상태와 프로젝트 사실은 현재 도구로 다시 확인하세요. "
            f"프로젝트 루트 이름은 {guard.root.name}이며 모든 도구 경로는 이 루트 기준 상대 경로입니다. "
            f"현재 프로젝트 지도는 다음과 같습니다: {json.dumps(project_overview, ensure_ascii=False)}"
        )}, *evidence_message, *conversation_context, {"role": "user", "content": message}]
    for _ in range(12):
        reply = await client.chat(model, messages, available_tools)
        messages.append(reply)
        calls = reply.get("tool_calls", [])
        if not calls:
            calls = _embedded_tool_calls(reply.get("content", ""), available_tool_names)
        if not calls:
            proposal_created = any(event["tool"] == "propose_changes" and event["status"] == "completed" for event in events)
            if change_requested and not proposal_created and missing_proposal_retries < 2:
                missing_proposal_retries += 1
                messages.append({"role": "system", "content": (
                    "사용자가 파일 변경을 요청했지만 아직 변경 제안이 생성되지 않았습니다. "
                    "코드 블록이나 설명으로 완료했다고 답하지 마세요. read_file로 정확한 현재 원문을 확인한 뒤 반드시 propose_changes 도구를 호출하세요."
                )})
                continue
            if change_requested and not proposal_created:
                detail = proposal_generation_feedback.removeprefix("이전 변경안이 서버 검증에 실패했습니다: ").strip()
                return finish({
                    "message": (
                        "변경안 생성 또는 서버 검증에 실패했습니다. "
                        f"실패 원인: {detail or '모델이 유효한 변경안을 제출하지 않았습니다.'}"
                    ),
                    "events": events,
                    "relevant_files": relevant_files,
                })
            completed_tools = {event["tool"] for event in events if event["status"] == "completed"}
            investigated = bool(completed_tools & {"project_map", "search_code", "search_regex", "read_file", "read_file_range"})
            source_read = bool(completed_tools & {"read_file", "read_file_range"})
            evidence_missing = evidence_required and (not investigated or (source_read_required and not source_read))
            evasive_response = evidence_required and _is_evasive_response(reply.get("content", ""))
            if (evidence_missing or evasive_response) and evidence_retries < 3:
                evidence_retries += 1
                instruction = (
                    "이 질문은 현재 프로젝트에 관한 사실 확인이 필요하지만 아직 코드 근거를 충분히 조사하지 않았습니다. "
                    "일반적인 설명이나 추가 정보 요청으로 답하지 마세요. 질문의 핵심 식별자·문구·오류를 search_code로 검색하고, "
                    "정확한 결과가 없으면 search_regex 또는 project_map으로 범위를 넓힌 뒤 관련 구현을 read_file 또는 read_file_range로 읽으세요."
                )
                if investigated and not source_read:
                    instruction = (
                        "검색 또는 구조 확인은 했지만 구현 파일을 아직 읽지 않았습니다. 검색 결과에서 가장 관련 있는 파일의 구현과 호출부를 "
                        "read_file 또는 read_file_range로 확인한 뒤에만 답하세요. 파일 목록만으로 추측하지 마세요."
                    )
                elif evasive_response and source_read:
                    instruction = (
                        "관련 코드 근거가 이미 제공되었습니다. 사용자에게 정보를 더 요구하거나 질문을 되돌리지 말고, 제공된 files 코드 구간에서 "
                        "확인되는 결론과 상대 파일 경로를 한국어로 직접 답하세요. 근거에 없는 내용만 명확히 제한하세요."
                    )
                messages.append({"role": "system", "content": instruction})
                continue
            if evidence_missing or evasive_response:
                return finish({
                    "message": "현재 프로젝트의 관련 코드를 충분히 확인하지 못해 근거 없는 답변은 표시하지 않았습니다. 검색할 식별자나 오류 문구가 있다면 그대로 포함해 다시 요청해 주세요.",
                    "events": events,
                    "relevant_files": relevant_files,
                })
            return finish({"message": _korean_response(reply.get("content", ""), proposal_created), "events": events, "relevant_files": relevant_files})
        for call in calls:
            name = call.get("function", {}).get("name", "")
            event = {"tool": name, "status": "completed"}
            events.append(event)
            signature = json.dumps(call.get("function", {}), ensure_ascii=False, sort_keys=True, default=str)
            try:
                if signature in completed_call_signatures:
                    raise ValueError("같은 도구 호출은 이미 성공했습니다. 기존 결과를 사용해 다음 단계로 진행하세요.")
                args = _arguments(call)
                if name == "project_map":
                    result = repository_map()
                elif name == "list_files":
                    result = list_files()
                elif name == "search_code":
                    result = search_code(args["query"])
                elif name == "search_regex":
                    result = search_regex(args["pattern"])
                elif name == "read_file":
                    result = read_file(args["path"])
                    normalized_path = guard.relative(resolve_source_file(args["path"]))
                    if normalized_path not in relevant_files:
                        relevant_files.append(normalized_path)
                elif name == "read_file_range":
                    result = read_file_range(args["path"], int(args["start_line"]), int(args["end_line"]))
                    normalized_path = result["path"]
                    if normalized_path not in relevant_files:
                        relevant_files.append(normalized_path)
                elif name == "propose_changes":
                    if not any(event["tool"] in {"read_file", "read_file_range"} and event["status"] == "completed" for event in events[:-1]):
                        raise ValueError("변경안을 만들기 전에 관련 구현 파일을 먼저 읽어야 합니다.")
                    result = propose(_proposal_files(args))
                    for item in result:
                        if item["path"] not in relevant_files:
                            relevant_files.append(item["path"])
                elif name == "git_status":
                    result = await git_status()
                elif name == "git_diff":
                    result = await git_diff(staged=bool(args.get("staged", False)))
                elif name == "git_stage_all":
                    result = await git_stage_all()
                elif name == "git_unstage_all":
                    result = await git_unstage_all()
                elif name == "git_commit":
                    result = await git_commit(str(args.get("message", "")))
                elif name == "git_branches":
                    result = await git_branches()
                elif name == "git_checkout":
                    result = await git_checkout(str(args.get("branch", "")))
                    if result.get("return_code") == 0:
                        clear()
                else:
                    raise ValueError(f"지원하지 않는 도구입니다: {name or '이름 없음'}")
                completed_call_signatures.add(signature)
            except Exception as exc:
                detail = str(exc).strip() or "알 수 없는 오류"
                failed_calls[signature] = failed_calls.get(signature, 0) + 1
                duplicate_call = signature in completed_call_signatures
                result = {
                    "error": detail,
                    "recovery": (
                        "이 도구 결과는 이미 대화에 있습니다. 같은 호출을 다시 하지 말고 기존 결과를 근거로 답하거나 다음 단계로 진행하세요."
                        if duplicate_call
                        else "같은 호출을 반복하지 말고 read_file로 현재 원문을 다시 확인한 뒤 path와 old 값을 정확히 수정하세요."
                    ),
                }
                event["status"] = "failed"
                event["detail"] = detail
            if on_event:
                await on_event(event)
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
            if event["status"] == "failed" and failed_calls[signature] >= 2:
                return finish({
                    "message": f"같은 도구 호출을 반복해서 작업을 중단했습니다. 원인: {event['detail']}",
                    "events": events,
                    "relevant_files": relevant_files,
                })
    return finish({"message": "도구 호출 한도에 도달했습니다. 수집된 결과를 검토해 주세요.", "events": events, "relevant_files": relevant_files})
