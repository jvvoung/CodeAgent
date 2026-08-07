import json
import re
from collections.abc import Awaitable, Callable

from llm.ollama_client import OllamaClient
from models.schemas import ProposedFile
from security.path_guard import guard
from tools.file_tools import list_files, read_file, resolve_source_file, search_code
from tools.patch_tools import propose

TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "열린 프로젝트에서 수정 가능한 텍스트 소스 파일의 상대 경로 목록을 조회합니다.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_code", "description": "열린 프로젝트의 소스 코드에서 정확한 문자열을 검색합니다.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "프로젝트 루트 기준 상대 경로의 UTF-8 텍스트 파일을 읽습니다. list_files가 반환한 경로를 그대로 사용하세요.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
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
    }},
]


def _arguments(call: dict) -> dict:
    arguments = call.get("function", {}).get("arguments", {})
    return json.loads(arguments) if isinstance(arguments, str) else arguments


def _proposal_files(arguments: dict) -> list[ProposedFile]:
    if not isinstance(arguments, dict):
        raise ValueError("변경안 인수는 객체 형식이어야 합니다.")

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


async def run_agent(message: str, model: str, on_event: EventCallback | None = None):
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    messages = [
        {"role": "system", "content": (
            "당신은 신중한 로컬 코딩 에이전트입니다. 최종 답변과 사용자에게 보이는 모든 설명은 반드시 자연스러운 한국어로만 작성하세요. "
            "중국어, 일본어, 영어 문장으로 답하지 마세요. 단, 코드·식별자·파일 경로는 원문을 유지하세요. "
            "변경안을 만들기 전에 도구로 프로젝트를 조사하세요. 요청에 포함된 구체적인 식별자를 검색하고 관련 파일만 읽으세요. "
            "수정할 때는 read_file에서 확인한 고유한 원문을 정확히 복사하여 propose_changes를 호출하세요. "
            "도구가 실패하면 같은 인수로 반복 호출하지 말고 오류 원인을 반영하여 파일을 다시 읽은 뒤 한 번만 수정해서 재시도하세요. "
            "명령을 실행하거나 프로젝트 밖의 경로에 접근하지 말고, 변경안이 실제 적용됐다고 주장하지 마세요. "
            f"프로젝트 루트 이름은 {guard.root.name}이며 모든 도구 경로는 이 루트 기준 상대 경로입니다."
        )},
        {"role": "user", "content": message},
    ]
    events: list[dict[str, str]] = []
    relevant_files: list[str] = []
    failed_calls: dict[str, int] = {}
    missing_proposal_retries = 0
    change_requested = _requests_change(message)
    client = OllamaClient()
    if "tools" not in await client.model_capabilities(model):
        raise ValueError(f"'{model}' 모델은 Agent 도구 호출을 지원하지 않습니다. 도구 지원 모델을 선택해 주세요.")
    for _ in range(12):
        reply = await client.chat(model, messages, TOOLS)
        messages.append(reply)
        calls = reply.get("tool_calls", [])
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
                return {
                    "message": "모델이 변경 도구를 호출하지 않아 변경 제안을 만들지 못했습니다. 파일명과 바꿀 원문을 더 구체적으로 입력해 주세요.",
                    "events": events,
                    "relevant_files": relevant_files,
                }
            return {"message": _korean_response(reply.get("content", ""), proposal_created), "events": events, "relevant_files": relevant_files}
        for call in calls:
            name = call.get("function", {}).get("name", "")
            event = {"tool": name, "status": "completed"}
            events.append(event)
            signature = json.dumps(call.get("function", {}), ensure_ascii=False, sort_keys=True, default=str)
            try:
                args = _arguments(call)
                if name == "list_files":
                    result = list_files()
                elif name == "search_code":
                    result = search_code(args["query"])
                elif name == "read_file":
                    result = read_file(args["path"])
                    normalized_path = guard.relative(resolve_source_file(args["path"]))
                    if normalized_path not in relevant_files:
                        relevant_files.append(normalized_path)
                elif name == "propose_changes":
                    result = propose(_proposal_files(args))
                    for item in result:
                        if item["path"] not in relevant_files:
                            relevant_files.append(item["path"])
                else:
                    raise ValueError(f"지원하지 않는 도구입니다: {name or '이름 없음'}")
            except Exception as exc:
                detail = str(exc).strip() or "알 수 없는 오류"
                failed_calls[signature] = failed_calls.get(signature, 0) + 1
                result = {
                    "error": detail,
                    "recovery": "같은 호출을 반복하지 말고 read_file로 현재 원문을 다시 확인한 뒤 path와 old 값을 정확히 수정하세요.",
                }
                event["status"] = "failed"
                event["detail"] = detail
            if on_event:
                await on_event(event)
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
            if event["status"] == "failed" and failed_calls[signature] >= 2:
                return {
                    "message": f"같은 변경 도구 호출이 반복해서 실패하여 작업을 중단했습니다. 실패 원인: {event['detail']}",
                    "events": events,
                    "relevant_files": relevant_files,
                }
    return {"message": "도구 호출 한도에 도달했습니다. 수집된 결과를 검토해 주세요.", "events": events, "relevant_files": relevant_files}
