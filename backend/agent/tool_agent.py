from __future__ import annotations

import json
import os
import re
import difflib
from collections.abc import Awaitable, Callable

from agent.workspace import AgentWorkspace, PatchError
from llm.ollama_client import OllamaClient, normalize_tool_arguments
from services.app_settings import get_int_setting
from services.proposal_validator import classify_validation, run_workspace_validation
from tools.patch_tools import stage_preview


EventCallback = Callable[[dict[str, str]], Awaitable[None]]


TOOLS = [
    {"type": "function", "function": {
        "name": "project_map",
        "description": "현재 프로젝트의 언어, 빌드 시스템, 매니페스트와 진입점 요약을 확인합니다.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "격리 작업공간의 수정 가능한 텍스트 파일 상대 경로를 확인합니다.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}},
    }},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "격리 작업공간 전체에서 정확한 문자열을 대소문자 구분 없이 검색합니다.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "search_regex",
        "description": "격리 작업공간 전체에서 정규식으로 정의, 호출부, 설정과 관련 코드를 검색합니다.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "격리 작업공간의 텍스트 파일 전체를 읽습니다. 수정 후에는 수정된 최신 내용이 반환됩니다.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "read_file_range",
        "description": "격리 작업공간 파일의 지정된 줄 범위를 읽습니다.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        }, "required": ["path", "start_line", "end_line"]},
    }},
    {"type": "function", "function": {
        "name": "replace_text",
        "description": "한 파일에서 정확히 일치하는 원문을 결정적으로 교체합니다. 사용자가 A를 B로 변경하라고 했다면 old에는 저장소에 현재 존재하는 A, new에는 요청한 결과 B를 넣습니다. 검색 결과는 후보일 뿐이므로 요청한 의미적 대상만 최소 변경하고, 명시적으로 요구하지 않은 주석·문서·로그·상태 문구까지 같은 단어를 일괄 교체하지 않습니다. old의 실제 출현 횟수가 expected_count와 다르면 파일을 변경하지 않습니다.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
            "expected_count": {"type": "integer", "minimum": 1, "maximum": 100, "default": 1},
        }, "required": ["path", "old", "new"]},
    }},
    {"type": "function", "function": {
        "name": "apply_patch",
        "description": (
            "하나 이상의 파일에 diff를 원자적으로 적용합니다. 구조 변경에는 반드시 다음 Codex 형식만 사용하세요: "
            "*** Begin Patch, *** Update File: 실제/상대/경로, @@, 정확한 원문 문맥과 +/- 변경 줄, *** End Patch. "
            "*** Begin Patch 뒤에 별표를 더 붙이지 말고 ---/+++ 헤더, 타임스탬프, 임의의 hunk 줄 번호를 섞지 마세요. "
            "공백과 들여쓰기를 포함한 변경 전 문맥은 가장 최근 read_file/read_file_range 결과에서 그대로 복사해야 합니다. "
            "생성하는 핸들러·함수는 placeholder나 TODO가 아니라 요청 기능을 실제로 수행하는 완전한 구현이어야 합니다."
        ),
        "parameters": {"type": "object", "properties": {
            "patch": {"type": "string"},
            "path": {"type": "string", "description": "파일 헤더 없는 단일 파일 patch의 대상 상대 경로"},
        }, "required": ["patch"]},
    }},
    {"type": "function", "function": {
        "name": "revert_file",
        "description": "현재 작업에서 해당 파일에 누적한 변경 전체가 사용자 요청과 무관할 때 격리 작업공간의 원본으로 되돌립니다.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "validate_changes",
        "description": "현재까지 누적한 변경을 격리 작업공간에서 빌드 또는 구문 검증하고, 변경 전 기준 결과와 비교합니다. 실패 진단을 읽고 같은 대화에서 수정하세요.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "finish_changes",
        "description": "요청한 변경을 모두 구현했다고 판단할 때 호출합니다. 서버가 최종 검증하고 Diff를 변경 제안으로 보존합니다.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    }},
]


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    return get_int_setting(name, default, minimum, maximum)


def _arguments(call: dict) -> dict:
    arguments = call.get("function", {}).get("arguments", {})
    return normalize_tool_arguments(arguments)


def _tool_message(name: str, payload: object) -> dict:
    rendered = json.dumps(payload, ensure_ascii=False, default=str)
    return {"role": "tool", "tool_name": name, "content": rendered[-16_000:]}


def _embedded_call(content: str) -> list[dict]:
    """Recover a tool call when a small local model prints JSON instead of native tool_calls."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content or "", re.DOTALL | re.IGNORECASE)
    stripped = (content or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    first_brace, last_brace = stripped.find("{"), stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        candidates.append(stripped[first_brace:last_brace + 1])
    allowed = {item["function"]["name"] for item in TOOLS}
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name") or payload.get("tool")
        arguments = payload.get("arguments", payload.get("parameters", {}))
        if name in allowed and isinstance(arguments, dict):
            return [{"function": {"name": name, "arguments": arguments}}]
    return []


def _grounding_fallback_call(
    term_evidence: dict[str, list[dict]], attempt: int, message: str = ""
) -> dict | None:
    """Bootstrap a stalled small model using only request terms grounded in the repository."""
    grounded = [(term, hits) for term, hits in term_evidence.items() if hits]
    if not grounded:
        return None
    path_scores: dict[str, tuple[set[str], list[int]]] = {}
    for term, hits in grounded:
        for hit in hits:
            path = str(hit.get("path", ""))
            if not path:
                continue
            if not _request_allows_comment_changes(message) and _is_comment_line(
                path, str(hit.get("text", ""))
            ):
                continue
            terms, lines = path_scores.setdefault(path, (set(), []))
            terms.add(term)
            try:
                lines.append(int(hit.get("line", 1)))
            except (TypeError, ValueError):
                lines.append(1)
    if not path_scores:
        return None
    documentation_suffixes = {".md", ".markdown", ".rst", ".txt", ".adoc"}
    documentation_requested = any(term in message.casefold() for term in (
        "readme", "documentation", "document", "docs", "문서", "가이드", "설명서",
    ))

    def path_rank(item: tuple[str, tuple[set[str], list[int]]]) -> tuple[int, int, int]:
        path, (terms, lines) = item
        is_document = os.path.splitext(path)[1].casefold() in documentation_suffixes
        preferred_type = is_document if documentation_requested else not is_document
        return int(preferred_type), len(terms), len(lines)

    ranked_paths = sorted(path_scores.items(), key=path_rank, reverse=True)
    selected_index = min(max(attempt - 1, 0), len(ranked_paths) - 1)
    path, (_terms, lines) = ranked_paths[selected_index]

    def nearby_count(line: int) -> int:
        return sum(abs(other - line) <= 50 for other in lines)

    center = max(lines, key=lambda line: (nearby_count(line), -line))
    return {"function": {"name": "read_file_range", "arguments": {
        "path": path,
        "start_line": max(1, center - 25),
        "end_line": center + 75,
    }}}


def _request_term_evidence(workspace: AgentWorkspace, message: str) -> dict[str, list[dict]]:
    """Collect exact-case repository matches for terms already present in the request."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*|[가-힣]{2,}", message)
    unique_tokens = list(dict.fromkeys(token for token in tokens if len(token) >= 2))[:24]
    evidence: dict[str, list[dict]] = {token: [] for token in unique_tokens}
    if not evidence:
        return {}
    for path in workspace.list_files(limit=5_000):
        try:
            lines = workspace.read_file(path).splitlines()
        except (OSError, ValueError):
            continue
        for line_number, line in enumerate(lines, 1):
            for token in unique_tokens:
                if token in line and len(evidence[token]) < 5:
                    evidence[token].append({
                        "path": path,
                        "line": line_number,
                        "text": line.strip()[:240],
                    })
    return {token: hits for token, hits in evidence.items() if hits}


def _request_needs_conversation_context(message: str) -> bool:
    lowered = message.casefold()
    references = (
        "아까", "방금", "이전", "앞에서", "위에서", "그 파일", "그 코드", "그 함수",
        "그 버튼", "그 변경", "그거", "그것", "같은 파일", "계속해서", "이어서",
        "previous", "earlier", "above", "that file", "that code", "continue",
    )
    return any(reference in lowered for reference in references)


def _request_prefers_patch(message: str) -> bool:
    lowered = message.casefold()
    structural_terms = (
        "추가", "만들", "생성", "구현", "삽입", "제거", "삭제 기능", "기능을",
        "add ", "create ", "implement ", "insert ", "remove ", "new function",
        "new method", "new class", "new file",
    )
    return any(term in lowered for term in structural_terms)


def _review_diff(preview: list[dict], limit: int = 12_000) -> str:
    sections: list[str] = []
    for item in preview:
        diff = "\n".join(difflib.unified_diff(
            str(item.get("original", "")).splitlines(),
            str(item.get("modified", "")).splitlines(),
            fromfile=f"a/{item['path']}",
            tofile=f"b/{item['path']}",
            lineterm="",
            n=3,
        ))
        sections.append(diff)
    rendered = "\n".join(sections)
    return rendered[:limit]


def _scope_review_tools(changed_paths: list[str]) -> list[dict]:
    allowed = {"read_file", "read_file_range", "revert_file", "validate_changes", "finish_changes"}
    selected = [
        json.loads(json.dumps(item, ensure_ascii=False))
        for item in TOOLS
        if item["function"]["name"] in allowed
    ]
    for item in selected:
        if item["function"]["name"] == "revert_file":
            item["function"]["parameters"]["properties"]["path"]["enum"] = changed_paths
            item["function"]["description"] += " path는 enum에 제시된 현재 변경 파일 중 하나만 선택합니다."
    return selected


def _request_allows_comment_changes(message: str) -> bool:
    lowered = message.casefold()
    negative = (
        "주석은 변경하지", "주석 변경하지", "주석 제외", "주석 빼고",
        "don't change comment", "do not change comment", "without comment", "exclude comment",
    )
    if any(phrase in lowered for phrase in negative):
        return False
    return any(term in lowered for term in ("주석", "코멘트", "comment", "docstring", "문서 주석"))


def _is_comment_line(path: str, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(("//", "///", "/*", "*/", "*", "<!--", "-- ")):
        return True
    suffix = os.path.splitext(path)[1].casefold()
    hash_comment_suffixes = {
        ".py", ".pyi", ".sh", ".bash", ".zsh", ".ps1", ".psm1",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    }
    return suffix in hash_comment_suffixes and stripped.startswith("#")


def _comment_only_change(item: dict) -> bool:
    path = str(item.get("path", ""))
    changed_lines = [
        line[2:]
        for line in difflib.ndiff(
            str(item.get("original", "")).splitlines(),
            str(item.get("modified", "")).splitlines(),
        )
        if line.startswith(("+ ", "- "))
    ]
    return bool(changed_lines) and all(_is_comment_line(path, line) for line in changed_lines)


def _strip_comment_edits(item: dict) -> dict:
    path = str(item.get("path", ""))
    original = str(item.get("original", ""))
    modified = str(item.get("modified", ""))
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=original_lines, b=modified_lines, autojunk=False)
    filtered: list[str] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_block = original_lines[old_start:old_end]
        new_block = modified_lines[new_start:new_end]
        changed_block = [*old_block, *new_block]
        if tag == "replace" and len(old_block) == len(new_block):
            for old_line, new_line in zip(old_block, new_block):
                if _is_comment_line(path, old_line) and _is_comment_line(path, new_line):
                    filtered.append(old_line)
                else:
                    filtered.append(new_line)
        elif tag != "equal" and changed_block and all(
            _is_comment_line(path, line) for line in changed_block
        ):
            filtered.extend(old_block)
        else:
            filtered.extend(new_block)
    filtered_modified = "".join(filtered)
    line_diff = list(difflib.ndiff(original.splitlines(), filtered_modified.splitlines()))
    return {
        **item,
        "modified": filtered_modified,
        "additions": sum(line.startswith("+ ") for line in line_diff),
        "deletions": sum(line.startswith("- ") for line in line_diff),
    }


def _scoped_preview(preview: list[dict], message: str) -> tuple[list[dict], list[str]]:
    if _request_allows_comment_changes(message):
        return preview, []
    filtered = [_strip_comment_edits(item) for item in preview]
    excluded = [item["path"] for item in filtered if item.get("original", "") == item.get("modified", "")]
    return [item for item in filtered if item["path"] not in excluded], excluded


async def run_change_agent(
    *,
    message: str,
    model: str,
    project_map: dict,
    conversation_context: list[dict],
    client: OllamaClient,
    on_event: EventCallback | None = None,
) -> dict:
    """Run one persistent Ollama tool conversation against a local shadow worktree."""
    max_steps = _integer_setting("AURA_AGENT_MAX_STEPS", 18, 4, 30)
    max_failed_finishes = _integer_setting("AURA_VALIDATION_REPAIR_ATTEMPTS", 2, 0, 5)
    events: list[dict[str, str]] = []
    relevant_files: list[str] = []

    async def emit(tool: str, status: str, detail: str = "") -> None:
        event = {"tool": tool, "status": status}
        if detail:
            event["detail"] = detail
        events.append(event)
        if on_event:
            await on_event(event)

    with AgentWorkspace(project_map["absolute_root"]) as workspace:
        await emit("workspace", "completed")
        baseline_result: dict | None = None
        latest_validation: dict = {
            "supported": False,
            "ok": True,
            "status": "not_run",
            "message": "검증을 실행하지 않았습니다.",
        }
        failed_finishes = 0
        validation_revision = -1
        read_paths: set[str] = set()
        failed_signatures: dict[str, int] = {}
        successful_readonly_signatures: set[str] = set()
        duplicate_readonly_counts: dict[str, int] = {}
        searches_without_read = 0
        total_tool_failures = 0
        no_tool_responses = 0
        recovery_call_signatures: set[str] = set()
        stop_reason = ""
        scope_review_requested = False
        scope_review_resolved = False
        scope_review_revision = -1
        scope_review_rounds = 0
        scope_review_active = False

        async def validate() -> dict:
            nonlocal baseline_result, latest_validation, validation_revision
            if validation_revision == workspace.revision:
                return latest_validation
            if baseline_result is None:
                baseline_result = await run_workspace_validation(workspace.baseline_root)
            proposed_result = await run_workspace_validation(workspace.root)
            latest_validation = classify_validation(baseline_result, proposed_result)
            validation_revision = workspace.revision
            return latest_validation

        system = (
            "당신은 회사 PC 내부에서 실행되는 AURA 로컬 코딩 에이전트입니다. 하나의 지속적인 작업 대화에서 도구를 사용해 요청을 끝까지 구현하세요. "
            "모든 설명과 최종 요약은 자연스러운 한국어로 작성하고 코드·식별자·경로만 원문을 유지하세요. "
            "현재 도구는 실제 프로젝트가 아니라 로컬 격리 작업공간을 수정하므로 변경을 누적해도 됩니다. 사용자의 실제 프로젝트에는 절대 직접 쓰지 않습니다. "
            "언어와 프레임워크를 가정하지 마세요. 먼저 project_map, 검색, 파일 읽기로 정의·호출부·구성·테스트를 조사하세요. "
            "문자열 ALPHA를 BETA로 바꾸라는 요청에서 변경 전 값은 ALPHA이고 변경 후 값은 BETA입니다. 반드시 ALPHA를 먼저 검색하고 old=ALPHA, new=BETA로 호출하세요. BETA 또는 그 대소문자 변형을 old로 검색하거나 교체하지 마세요. "
            "사용자가 지정한 의미적 대상만 바꾸는 최소 Diff를 만드세요. 검색된 같은 단어를 모두 바꾸는 작업이 아닙니다. 요청하지 않은 주석, 문서, 로그, 상태 메시지, 식별자는 바꾸지 말고 정확한 대상 변경이 성공하면 불필요한 추가 교체를 하지 마세요. "
            "검색 결과가 있으면 같은 검색을 반복하지 말고 결과의 path와 line을 사용해 read_file_range 또는 read_file을 호출한 뒤 수정하세요. "
            "첫 finish_changes 호출에서는 서버가 전체 Diff를 다시 보여줍니다. 그 Diff를 사용자 원요청과 줄별로 비교하고 불필요한 변경은 revert_file 또는 수정 도구로 제거한 뒤 finish_changes를 다시 호출하세요. "
            "단순한 문구나 정확한 값 교체는 replace_text를 사용하세요. 구조 변경이나 여러 파일 변경은 *** Begin Patch / *** Update File / @@ / *** End Patch 형식의 apply_patch만 사용하고, 최근 읽기 결과의 실제 문맥을 공백까지 그대로 복사하세요. 타임스탬프가 있는 ---/+++ 헤더나 임의 줄 번호 hunk를 만들지 마세요. "
            "파일별로 독립적인 조각을 만들지 말고 한 작업공간에서 관련 파일의 계약과 호출부를 함께 맞추세요. 읽지 않은 코드를 추측하거나 존재하지 않는 식별자를 만들지 마세요. "
            "변경 후 validate_changes를 실행하세요. 오류가 있으면 그 결과를 근거로 같은 대화에서 검색·읽기·수정을 계속하고 다시 검증하세요. "
            "원래 프로젝트가 빌드되지 않거나 빌드 구성이 없어도 작업을 포기하지 마세요. 요청을 구현한 최종 후보가 있으면 finish_changes를 호출하세요. "
            "finish_changes 이전에는 사용자에게 완료했다고 말하지 마세요. Git, 네트워크, 프로젝트 밖 파일과 일반 셸은 사용할 수 없습니다."
        )
        public_map = {key: value for key, value in project_map.items() if key != "absolute_root"}
        term_evidence = _request_term_evidence(workspace, message)
        messages = [
            {"role": "system", "content": (
                system
                + "\n현재 프로젝트 지도: " + json.dumps(public_map, ensure_ascii=False)
                + "\n사용자 요청에 실제로 등장하며 현재 저장소에도 대소문자까지 정확히 존재하는 용어 근거: "
                + json.dumps(term_evidence, ensure_ascii=False)
                + "\n이 근거는 변경 후보 전체 목록이 아닙니다. 요청의 변경 전 값과 의미적 대상을 판단하는 데만 사용하세요."
            )},
            *(conversation_context[-6:] if _request_needs_conversation_context(message) else []),
            {"role": "user", "content": message},
        ]

        final_summary = ""
        completed = False
        for _step in range(max_steps):
            structural_request = _request_prefers_patch(message)
            active_tools = [
                item for item in TOOLS
                if not structural_request or item["function"]["name"] != "replace_text"
            ]
            if scope_review_active:
                review_preview, _ = _scoped_preview(workspace.preview(), message)
                active_tools = _scope_review_tools([item["path"] for item in review_preview])
            elif not _scoped_preview(workspace.preview(), message)[0]:
                if structural_request and len(read_paths) >= 2:
                    active_tools = [
                        item for item in active_tools
                        if item["function"]["name"] == "apply_patch"
                    ]
                elif structural_request:
                    active_tools = [
                        item for item in active_tools
                        if item["function"]["name"] not in {"validate_changes", "finish_changes"}
                    ]
                elif len(read_paths) >= 2:
                    mutation_tools = {"apply_patch"} if _request_prefers_patch(message) else {
                        "replace_text", "apply_patch"
                    }
                    active_tools = [
                        item for item in TOOLS
                        if item["function"]["name"] in mutation_tools
                    ]
                else:
                    active_tools = [
                        item for item in TOOLS
                        if item["function"]["name"] not in {"validate_changes", "finish_changes"}
                    ]
            reply = await client.chat(model, messages, active_tools)
            messages.append(reply)
            calls = reply.get("tool_calls", [])
            if not calls:
                calls = _embedded_call(str(reply.get("content", "")))
            active_tool_names = {
                item["function"]["name"] for item in active_tools
            }
            invalid_calls = [
                call for call in calls
                if str(call.get("function", {}).get("name", "")) not in active_tool_names
            ]
            if invalid_calls:
                calls = [
                    call for call in calls
                    if str(call.get("function", {}).get("name", "")) in active_tool_names
                ]
                messages.append({"role": "system", "content": (
                    "직전 tool_calls에는 현재 단계에서 허용되지 않은 과거 도구가 포함되어 실행하지 않았습니다. "
                    "현재 제공된 tools 안에서만 다음 작업을 선택하세요."
                )})
                await emit("reject_inactive_tool", "completed")
            if not calls and not workspace.preview():
                force_tool_call = getattr(client, "force_tool_call", None)
                if force_tool_call:
                    force_tools = active_tools
                    if structural_request and read_paths:
                        force_tools = [
                            item for item in active_tools
                            if item["function"]["name"] == "apply_patch"
                        ]
                    elif len(read_paths) >= 2:
                        mutation_tools = {"apply_patch"} if _request_prefers_patch(message) else {
                            "replace_text", "apply_patch"
                        }
                        force_tools = [
                            item for item in active_tools
                            if item["function"]["name"] in mutation_tools
                        ]
                    try:
                        forced_call = await force_tool_call(model, messages, force_tools)
                    except Exception as exc:
                        forced_call = None
                        await emit("force_tool_call", "failed", str(exc))
                    if forced_call:
                        forced_signature = json.dumps(forced_call, ensure_ascii=False, sort_keys=True)
                        if forced_signature in recovery_call_signatures:
                            fallback_attempt = max(1, len(read_paths) + 1)
                            fallback_call = _grounding_fallback_call(
                                term_evidence, fallback_attempt, message
                            )
                            fallback_signature = json.dumps(
                                fallback_call, ensure_ascii=False, sort_keys=True
                            ) if fallback_call else ""
                            if fallback_call and fallback_signature not in recovery_call_signatures:
                                forced_call = fallback_call
                                forced_signature = fallback_signature
                        recovery_call_signatures.add(forced_signature)
                        calls = [forced_call]
                        messages.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [forced_call],
                        })
                        await emit("force_tool_call", "completed")
            if not calls:
                no_tool_responses += 1
                await emit(
                    "model_no_tool",
                    "failed",
                    str(reply.get("content", "")).strip()[:1200] or "모델이 빈 응답을 반환했습니다.",
                )
                previewed = workspace.preview()
                if previewed:
                    calls = [{"function": {"name": "finish_changes", "arguments": {"summary": reply.get("content", "")}}}]
                else:
                    fallback_call = _grounding_fallback_call(term_evidence, no_tool_responses, message)
                    if fallback_call is not None and no_tool_responses <= 2:
                        calls = [fallback_call]
                        messages.append({"role": "system", "content": (
                            "도구 호출이 없어 서버가 사용자 요청과 저장소에 공통으로 존재하는 근거를 이용해 "
                            "다음 조회 도구를 대신 선택했습니다. 반환되는 실제 코드 문맥을 사용해 작업을 계속하세요."
                        )})
                    elif no_tool_responses >= 3:
                        stop_reason = "모델이 저장소 근거를 제공받은 뒤에도 필요한 도구를 호출하지 않아 작업을 중단했습니다."
                        break
                    else:
                        messages.append({"role": "system", "content": (
                            "아직 실제 파일 변경이 없습니다. 사용자 요청을 구현하려면 검색하고 파일을 읽은 뒤 replace_text 또는 apply_patch를 호출하세요."
                        )})
                        continue
            else:
                no_tool_responses = 0

            should_continue = False
            for call in calls:
                name = str(call.get("function", {}).get("name", ""))
                arguments = _arguments(call)
                signature = json.dumps(
                    {
                        "name": name,
                        "arguments": arguments,
                        "revision": workspace.revision,
                        "failure_epoch": total_tool_failures,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                readonly_tools = {
                    "project_map", "list_files", "search_code", "search_regex",
                    "read_file", "read_file_range",
                }
                if name in readonly_tools and signature in successful_readonly_signatures:
                    duplicate_readonly_counts[signature] = duplicate_readonly_counts.get(signature, 0) + 1
                    if name in {"read_file", "read_file_range"}:
                        fallback_call = _grounding_fallback_call(
                            term_evidence, max(1, len(read_paths) + 1), message
                        )
                        if fallback_call:
                            fallback_name = str(fallback_call.get("function", {}).get("name", ""))
                            fallback_arguments = _arguments(fallback_call)
                            current_identity = json.dumps(
                                {"name": name, "arguments": arguments},
                                ensure_ascii=False, sort_keys=True,
                            )
                            fallback_identity = json.dumps(
                                {"name": fallback_name, "arguments": fallback_arguments},
                                ensure_ascii=False, sort_keys=True,
                            )
                            if fallback_identity != current_identity:
                                calls.append(fallback_call)
                                messages.append(_tool_message(name, {
                                    "ok": False,
                                    "error": "같은 파일 구간은 이미 읽었습니다.",
                                    "instruction": "서버가 다음 순위 관련 소스 파일 읽기로 전환했습니다.",
                                }))
                                should_continue = True
                                continue
                    if duplicate_readonly_counts[signature] >= 2:
                        stop_reason = f"동일한 조회 도구 호출이 반복되어 작업을 중단했습니다: {name}"
                        await emit(name, "failed", stop_reason)
                        break
                    messages.append(_tool_message(name, {
                        "ok": False,
                        "error": "동일한 조회는 이미 완료되었습니다.",
                        "instruction": "같은 조회를 반복하지 말고 직전 결과의 path와 line을 사용해 파일을 읽은 뒤 수정하세요.",
                    }))
                    should_continue = True
                    continue
                if name in {"search_code", "search_regex"} and searches_without_read >= 2:
                    fallback_call = _grounding_fallback_call(term_evidence, 1, message)
                    if fallback_call:
                        calls.append(fallback_call)
                        messages.append(_tool_message(name, {
                            "ok": False,
                            "error": "코드 검색만 반복할 수 없습니다.",
                            "instruction": "서버가 가장 관련도 높은 실제 소스 구간 읽기로 전환했습니다.",
                        }))
                        should_continue = True
                        continue
                    stop_reason = "파일을 읽지 않고 코드 검색만 반복하여 작업을 중단했습니다."
                    await emit(name, "failed", stop_reason)
                    break
                try:
                    if name == "project_map":
                        result = public_map
                    elif name == "list_files":
                        result = workspace.list_files(int(arguments.get("limit", 500)))
                    elif name == "search_code":
                        result = workspace.search(str(arguments.get("query", "")))
                        searches_without_read += 1
                        for item in result[:20]:
                            if item["path"] not in relevant_files:
                                relevant_files.append(item["path"])
                    elif name == "search_regex":
                        result = workspace.search(str(arguments.get("pattern", "")), regex=True)
                        searches_without_read += 1
                        for item in result[:20]:
                            if item["path"] not in relevant_files:
                                relevant_files.append(item["path"])
                    elif name == "read_file":
                        path = str(arguments.get("path", ""))
                        target = workspace.resolve(path)
                        normalized_path = workspace.relative(target)
                        content = workspace.read_file(normalized_path)
                        read_paths.add(normalized_path)
                        searches_without_read = 0
                        result = {"path": normalized_path, "content": content}
                        if normalized_path not in relevant_files:
                            relevant_files.append(normalized_path)
                    elif name == "read_file_range":
                        result = workspace.read_file_range(
                            str(arguments.get("path", "")),
                            int(arguments.get("start_line", 1)),
                            int(arguments.get("end_line", 1)),
                        )
                        read_paths.add(result["path"])
                        searches_without_read = 0
                        if result["path"] not in relevant_files:
                            relevant_files.append(result["path"])
                    elif name == "replace_text":
                        if scope_review_active:
                            raise ValueError(
                                "현재는 변경 범위 검토 단계입니다. 새 교체를 추가하지 말고, "
                                "불필요한 파일은 revert_file로 되돌리거나 현재 Diff가 모두 필요하면 finish_changes를 호출하세요."
                            )
                        target = workspace.resolve(str(arguments.get("path", "")))
                        normalized_path = workspace.relative(target)
                        old_text = str(arguments.get("old", ""))
                        new_text = str(arguments.get("new", ""))
                        if (
                            old_text
                            and old_text != new_text
                            and old_text.casefold() == new_text.casefold()
                            and old_text not in message
                        ):
                            raise ValueError(
                                "변경 전 원문(old)을 변경 후 값(new)의 대소문자 변형으로 추측했습니다. "
                                "사용자 요청에서 변경 전 값을 다시 확인하고 그 원문을 먼저 검색하세요."
                            )
                        if normalized_path not in read_paths:
                            raise ValueError(
                                f"수정 전에 현재 파일을 읽어야 합니다: {normalized_path}. "
                                "검색 결과는 파일 문맥을 대신하지 않습니다. read_file 또는 "
                                "read_file_range로 실제 원문과 주변 코드를 확인한 뒤 다시 시도하세요."
                            )
                        try:
                            expected_count = int(arguments.get("expected_count", 1))
                        except (TypeError, ValueError):
                            expected_count = 1
                        if not 1 <= expected_count <= 100:
                            expected_count = 1
                        source_text = workspace.read_file(normalized_path)
                        arguments_corrected = False
                        if (
                            old_text
                            and new_text
                            and old_text in message
                            and new_text in message
                            and source_text.count(old_text) == 0
                            and source_text.count(new_text) == expected_count
                        ):
                            old_text, new_text = new_text, old_text
                            arguments_corrected = True
                        result = workspace.replace_text(
                            normalized_path,
                            old_text,
                            new_text,
                            expected_count,
                        )
                        if arguments_corrected:
                            result = {
                                **result,
                                "arguments_corrected": True,
                                "instruction": (
                                    "실제 파일에는 old가 없고 new만 존재하여 교체 방향을 "
                                    "사용자 요청과 저장소 원문에 맞게 자동 교정했습니다."
                                ),
                            }
                        searches_without_read = 0
                        if result["path"] not in relevant_files:
                            relevant_files.append(result["path"])
                    elif name == "apply_patch":
                        if scope_review_active:
                            raise ValueError(
                                "현재는 변경 범위 검토 단계입니다. 새 patch를 추가하지 말고, "
                                "불필요한 파일은 revert_file로 되돌리거나 finish_changes를 호출하세요."
                            )
                        patch_text = str(arguments.get("patch", ""))
                        default_path = str(arguments.get("path", "")).strip() or None
                        inferred_from_context = False
                        try:
                            targets = workspace.patch_targets(patch_text, default_path=default_path)
                        except PatchError:
                            candidates = list(dict.fromkeys([*read_paths, *relevant_files]))
                            default_path = workspace.infer_patch_target(patch_text, candidates)
                            if default_path is None:
                                default_path = workspace.infer_patch_target(patch_text)
                            if default_path is None:
                                raise
                            inferred_from_context = True
                            targets = workspace.patch_targets(patch_text, default_path=default_path)
                        unread = [
                            item["path"] for item in targets
                            if not item["creating"] and item["path"] not in read_paths
                        ]
                        if unread and not inferred_from_context:
                            raise ValueError(
                                "patch 적용 전에 대상 파일을 읽어야 합니다: " + ", ".join(unread[:5])
                            )
                        result = workspace.apply_patch(patch_text, default_path=default_path)
                        searches_without_read = 0
                        for path in result["paths"]:
                            if path not in relevant_files:
                                relevant_files.append(path)
                    elif name == "revert_file":
                        result = workspace.revert_file(str(arguments.get("path", "")))
                    elif name == "validate_changes":
                        if not workspace.preview():
                            raise ValueError("검증할 변경이 없습니다.")
                        result = await validate()
                    elif name == "finish_changes":
                        previewed, _ = _scoped_preview(workspace.preview(), message)
                        if not previewed:
                            raise ValueError("변경 제안으로 표시할 실제 Diff가 없습니다.")
                        final_summary = str(arguments.get("summary", "")).strip()
                        if len(previewed) > 1 and (
                            not scope_review_requested
                            or scope_review_revision != workspace.revision
                            or scope_review_rounds < 2
                        ):
                            scope_review_requested = True
                            scope_review_revision = workspace.revision
                            scope_review_rounds += 1
                            scope_review_active = True
                            result = {
                                "status": "scope_review_required",
                                "action": "continue_review",
                                "user_request": message,
                                "changed_paths": [item["path"] for item in previewed],
                                "diff": _review_diff(previewed),
                                "instruction": (
                                    "이 Diff의 모든 변경 줄이 사용자 원요청에 반드시 필요한지 검토하세요. "
                                    "같은 단어가 검색됐다는 이유만으로 바꾼 주석·문서·로그·상태 문구·식별자는 제거하세요. "
                                    "파일의 변경 전체가 불필요하면 revert_file을 사용하고, 검토 완료 후 finish_changes를 다시 호출하세요."
                                ),
                            }
                            should_continue = True
                        else:
                            scope_review_resolved = True
                            scope_review_active = False
                            result = await validate()
                        if result.get("status") == "scope_review_required":
                            should_continue = True
                        elif result.get("status") == "failed" and failed_finishes < max_failed_finishes:
                            failed_finishes += 1
                            result = {
                                **result,
                                "action": "continue_fixing",
                                "remaining_repair_attempts": max_failed_finishes - failed_finishes,
                                "instruction": "오류가 발생한 최신 파일을 읽고 진단을 반영해 수정한 뒤 다시 검증하고 finish_changes를 호출하세요.",
                            }
                            should_continue = True
                        else:
                            completed = True
                    else:
                        raise ValueError(f"지원하지 않는 도구입니다: {name or '이름 없음'}")
                    if name in {"replace_text", "apply_patch"}:
                        current_preview, excluded_comment_paths = _scoped_preview(
                            workspace.preview(), message
                        )
                        if excluded_comment_paths:
                            for ignored_path in excluded_comment_paths:
                                workspace.revert_file(ignored_path)
                            result = {
                                "edit_result": result,
                                "status": "comment_changes_ignored",
                                "ignored_paths": excluded_comment_paths,
                                "instruction": (
                                    "사용자가 주석 변경을 요청하지 않았으므로 주석만 바뀐 내용은 "
                                    "최종 변경 제안에서 자동 제외됩니다. 이 교체를 작업 완료로 간주하지 말고 "
                                    "사용자가 지정한 실제 코드·설정·UI 값의 정의를 읽고 정확한 대상만 수정하세요."
                                ),
                            }
                            should_continue = True
                        if len(current_preview) > 1 and not scope_review_requested:
                            scope_review_requested = True
                            scope_review_revision = workspace.revision
                            scope_review_rounds = 1
                            scope_review_active = True
                            result = {
                                "edit_result": result,
                                "status": "scope_review_required",
                                "action": "continue_review",
                                "user_request": message,
                                "changed_paths": [item["path"] for item in current_preview],
                                "diff": _review_diff(current_preview),
                                "instruction": (
                                    "두 개 이상의 파일이 변경됐습니다. 지금 추가 수정을 멈추고 모든 변경 줄을 사용자 원요청과 비교하세요. "
                                    "같은 단어가 있다는 이유만으로 바꾼 주석·문서·로그·상태 문구·식별자는 제거하세요. "
                                    "파일 변경 전체가 불필요하면 revert_file을 사용하고, 검토 후 finish_changes를 호출하세요."
                                ),
                            }
                            should_continue = True
                    if name in readonly_tools:
                        successful_readonly_signatures.add(signature)
                    await emit(name, "completed")
                    messages.append(_tool_message(name, {"ok": True, "result": result}))
                except Exception as exc:
                    detail = str(exc).strip() or "알 수 없는 도구 오류"
                    if name == "replace_text":
                        diagnostic = {
                            "path": arguments.get("path"),
                            "old": arguments.get("old"),
                            "new": arguments.get("new"),
                            "expected_count": arguments.get("expected_count", 1),
                        }
                        detail += " | 호출 인수: " + json.dumps(diagnostic, ensure_ascii=False, default=str)
                    elif name == "apply_patch":
                        diagnostic = {
                            "path": arguments.get("path"),
                            "patch": str(arguments.get("patch", ""))[:5000],
                        }
                        detail += " | 호출 인수: " + json.dumps(
                            diagnostic, ensure_ascii=False, default=str
                        )
                    failure_signature = json.dumps(
                        {
                            "name": name,
                            "arguments": arguments,
                            "revision": workspace.revision,
                            "read_paths": sorted(read_paths),
                            "relevant_files": sorted(relevant_files),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                    failed_signatures[failure_signature] = failed_signatures.get(failure_signature, 0) + 1
                    total_tool_failures += 1
                    await emit(name or "unknown", "failed", detail)
                    repeat_limit = 3 if name == "revert_file" else 2
                    repeated = failed_signatures[failure_signature] >= repeat_limit
                    messages.append(_tool_message(name or "unknown", {
                        "ok": False,
                        "error": detail,
                        "same_call_failure_count": failed_signatures[failure_signature],
                        "instruction": "같은 인수로 반복하지 말고 검색 결과에서 정확한 경로를 선택해 파일을 읽은 후 새 인수로 시도하세요.",
                    }))
                    if repeated:
                        stop_reason = f"동일한 실패 도구 호출이 반복되어 작업을 중단했습니다: {name}"
                    elif total_tool_failures >= 6:
                        stop_reason = "도구 오류가 6회 누적되어 작업을 중단했습니다."
                    should_continue = True
                    if stop_reason:
                        break
                if completed:
                    break
            if completed:
                break
            if stop_reason:
                break
            if should_continue:
                continue

        previewed, excluded_comment_paths = _scoped_preview(workspace.preview(), message)
        if not previewed:
            return {
                "message": stop_reason or "요청한 코드 변경을 만들지 못했습니다. 검색 범위를 넓히거나 요청을 더 작은 단위로 나눠 다시 시도해 주세요.",
                "events": events,
                "relevant_files": relevant_files,
            }
        if excluded_comment_paths:
            await emit("filter_comment_only", "completed", ", ".join(excluded_comment_paths))
        if validation_revision != workspace.revision:
            latest_validation = await validate()
            await emit("validate_changes", "completed")

        status = str(latest_validation.get("status", "not_run"))
        error = str(latest_validation.get("message") or latest_validation.get("warning") or "")
        if len(previewed) > 1 and not scope_review_resolved:
            status = "scope_review_incomplete"
            error = (
                "모델의 자동 변경 범위 검토가 완료되지 않았습니다. "
                "파일별 Diff를 확인한 뒤 필요한 파일만 적용하고 나머지는 폐기하세요."
            )
        stage_preview(
            previewed,
            validation_status=status,
            validation_error=error,
            retry_request=message,
        )
        await emit("propose_changes", "completed")
        for item in previewed:
            if item["path"] not in relevant_files:
                relevant_files.append(item["path"])

        if status == "verified":
            message_text = "검증을 통과한 변경안을 만들었습니다. 변경 제안에서 Diff를 확인한 뒤 적용하거나 폐기해 주세요."
        elif status == "baseline_failed":
            message_text = "원래 프로젝트의 빌드 오류는 유지됐지만 새로운 오류는 확인되지 않았습니다. Diff를 확인한 뒤 적용 여부를 선택해 주세요."
        elif status == "failed":
            message_text = "빌드 검증에 실패했지만 최종 Diff를 보존했습니다. 오류와 변경 내용을 확인한 뒤 적용·폐기·다시 생성을 선택해 주세요."
        elif status == "scope_review_incomplete":
            message_text = "자동 범위 검토를 완료하지 못했지만 현재 Diff를 변경 제안에 보존했습니다. 파일별로 확인해 필요한 변경만 적용하거나 폐기해 주세요."
        else:
            message_text = "자동 검증은 완료하지 못했지만 최종 Diff를 보존했습니다. 변경 내용을 확인한 뒤 적용 여부를 선택해 주세요."
        if final_summary and 0 < len(final_summary) <= 400:
            message_text += f"\n\n에이전트 요약: {final_summary}"
        return {"message": message_text, "events": events, "relevant_files": relevant_files}
