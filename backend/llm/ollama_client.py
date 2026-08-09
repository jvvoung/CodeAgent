import asyncio
import difflib
import json
import re
from collections.abc import AsyncIterator

import httpx

from services.app_settings import get_int_setting, get_string_setting


def recover_json_string_field(content: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*', content)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(content[match.end():])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, str) else None


def normalize_tool_arguments(payload) -> dict:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    for _ in range(3):
        if not isinstance(payload, dict):
            return {}
        nested = payload.get("arguments")
        if "files" not in payload and isinstance(nested, (dict, str)):
            if isinstance(nested, str):
                try:
                    nested = json.loads(nested)
                except json.JSONDecodeError:
                    break
            payload = nested
            continue
        break
    return payload if isinstance(payload, dict) else {}


def _payload_from_message_content(content: str) -> dict:
    stripped = (content or "").strip()
    candidates = [stripped]
    first_brace, last_brace = stripped.find("{"), stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        candidates.append(stripped[first_brace:last_brace + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = normalize_tool_arguments(json.loads(candidate))
        except json.JSONDecodeError:
            continue
        if payload:
            return payload
    return {}


def _compact_prior_patches(planned_files: list[dict]) -> list[dict]:
    """Share identifiers only; never leak another file's code or coordinates."""
    ignored = {
        "button", "content", "style", "width", "height", "margin", "padding", "private", "public",
        "string", "void", "return", "static", "class", "grid", "column", "click", "object", "sender",
    }
    compact: list[dict] = []
    for item in planned_files[-4:]:
        identifiers: list[str] = []
        for operation in item.get("operations", [])[:4]:
            if not isinstance(operation, dict):
                continue
            content = str(operation.get("content", ""))
            for identifier in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", content):
                if identifier.casefold() in ignored:
                    continue
                looks_named = "_" in identifier or any(character.isupper() for character in identifier[1:])
                if looks_named and identifier not in identifiers:
                    identifiers.append(identifier)
                if len(identifiers) >= 16:
                    break
        compact.append({"path": item.get("path"), "introduced_identifiers": identifiers})
    return compact


def _operations_change_evidence(target_file: dict, operations: list[dict]) -> bool:
    """Reject obvious no-op patches before restarting the whole proposal flow."""
    evidence_lines = str(target_file.get("content", "")).splitlines()
    first_line = int(target_file.get("start_line", 1))
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        kind = str(operation.get("op", "")).strip().casefold()
        content = str(operation.get("content", ""))
        if kind in {"insert_before_line", "insert_after_line"}:
            if content:
                return True
            continue
        if kind == "delete_lines":
            return True
        if kind != "replace_lines":
            continue
        try:
            local_start = int(operation.get("start_line")) - first_line
            local_end = int(operation.get("end_line")) - first_line + 1
        except (TypeError, ValueError):
            return True
        if local_start < 0 or local_end > len(evidence_lines) or local_end <= local_start:
            return True
        selected = "\n".join(evidence_lines[local_start:local_end]).strip()
        if selected != content.strip():
            return True
    return False


def _coalesce_insert_operations(source: str, operations: list[dict], first_line: int = 1) -> list[dict]:
    """Merge insertions sharing one anchor while preserving the selected source line."""
    grouped: dict[tuple[int, int], list[dict]] = {}
    order: list[tuple[int, int]] = []
    for operation in operations:
        try:
            key = (int(operation.get("start_line")), int(operation.get("end_line")))
        except (AttributeError, TypeError, ValueError):
            return operations
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(operation)

    source_lines = source.splitlines(keepends=True)
    merged: list[dict] = []
    for start, end in order:
        items = grouped[(start, end)]
        if len(items) == 1:
            merged.append(items[0])
            continue
        kinds = [str(item.get("op", "")).strip().casefold() for item in items]
        if not all(kind in {"insert_before_line", "insert_after_line"} for kind in kinds):
            merged.extend(items)
            continue
        local_start = start - first_line
        local_end = end - first_line + 1
        if local_start < 0 or local_end > len(source_lines):
            merged.extend(items)
            continue

        def joined(kind: str) -> str:
            parts = [str(item.get("content", "")) for item, item_kind in zip(items, kinds) if item_kind == kind]
            return "\n".join(part.rstrip("\r\n") for part in parts if part)

        before = joined("insert_before_line")
        after = joined("insert_after_line")
        selected = "".join(source_lines[local_start:local_end]).rstrip("\r\n")
        content = "\n".join(part for part in (before, selected, after) if part)
        merged.append({
            "op": "replace_lines",
            "start_line": start,
            "end_line": end,
            "content": content,
        })
    return merged


def _operations_are_valid_for_evidence(target_file: dict, operations: list[dict]) -> bool:
    return not _operation_validation_error(target_file, operations)


def _operation_validation_error(target_file: dict, operations: list[dict]) -> str:
    first_line = int(target_file.get("start_line", 1))
    line_count = len(str(target_file.get("content", "")).splitlines())
    last_line = first_line + line_count - 1
    ranges: list[tuple[int, int]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            return "연산이 JSON 객체가 아닙니다"
        if str(operation.get("op", "")).strip().casefold() not in {
            "insert_before_line", "insert_after_line", "replace_lines", "delete_lines",
        }:
            return "지원하지 않는 op 값입니다"
        try:
            start = int(operation.get("start_line"))
            end = int(operation.get("end_line"))
        except (TypeError, ValueError):
            return "start_line 또는 end_line이 정수가 아닙니다"
        if start < first_line or end < start or end > last_line:
            return f"줄 범위 {start}-{end}가 표시된 허용 범위 {first_line}-{last_line} 밖입니다"
        ranges.append((start, end))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] <= previous[1]:
            return f"줄 범위 {previous[0]}-{previous[1]}와 {current[0]}-{current[1]}가 겹칩니다"
    return ""


def _structural_boundary_hints(target_file: dict) -> list[str]:
    first_line = int(target_file.get("start_line", 1))
    lines = str(target_file.get("content", "")).splitlines()
    candidates: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        is_boundary = stripped in {"}", "};", "]", ");", "end"} or bool(
            re.fullmatch(r"</[A-Za-z_][^>]*>", stripped)
        )
        if is_boundary:
            indentation = len(line) - len(line.lstrip())
            candidates.append((indentation, first_line + index, stripped))
    candidates = sorted(candidates, key=lambda item: (item[0], -item[1]))[:6]
    return [f"line {line_number} (indent {indentation}): {text}" for indentation, line_number, text in candidates]


def _apply_repair_operations(source: str, operations: list[dict]) -> str:
    """Apply model repair operations against the current failing file."""
    source_lines = source.splitlines(keepends=True)
    normalized: list[tuple[int, int, str, str]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("검증 수리 연산은 객체여야 합니다.")
        kind = str(operation.get("op", "")).strip().casefold()
        if kind not in {"replace_lines", "insert_before_line", "insert_after_line", "delete_lines"}:
            raise ValueError(f"지원하지 않는 검증 수리 연산입니다: {kind or '이름 없음'}")
        try:
            start = int(operation.get("start_line")) - 1
            end = int(operation.get("end_line"))
        except (TypeError, ValueError) as exc:
            raise ValueError("검증 수리 연산에는 올바른 줄 번호가 필요합니다.") from exc
        if start < 0 or end <= start or end > len(source_lines):
            raise ValueError(f"검증 수리 줄 범위가 파일을 벗어났습니다: {start + 1}-{end}")
        content = operation.get("content", "")
        if not isinstance(content, str):
            raise ValueError("검증 수리 연산의 content는 문자열이어야 합니다.")
        normalized.append((start, end, kind, content))

    ordered = sorted(normalized, key=lambda item: (item[0], item[1]))
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("검증 수리 연산의 줄 범위가 서로 겹칩니다.")

    repaired = list(source_lines)
    for start, end, kind, content in reversed(ordered):
        selected = "".join(source_lines[start:end])
        inserted = content
        if inserted and not inserted.endswith(("\n", "\r")):
            inserted += "\n"
        if kind == "replace_lines":
            replacement = inserted
        elif kind == "insert_before_line":
            replacement = inserted + selected
        elif kind == "insert_after_line":
            replacement = selected + inserted
        else:
            replacement = ""
        repaired[start:end] = replacement.splitlines(keepends=True)
    return "".join(repaired)


def _repair_excerpt(original: str, current: str, diagnostics: str, path: str) -> str:
    """Return numbered windows around changed and compiler-reported lines."""
    current_lines = current.splitlines()
    anchors: set[int] = set()
    matcher = difflib.SequenceMatcher(None, original.splitlines(), current_lines, autojunk=False)
    for tag, _old_start, _old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if new_start == new_end:
            anchors.add(max(0, min(new_start, len(current_lines) - 1)))
        else:
            anchors.update(range(new_start, new_end))

    normalized_path = path.replace("\\", "/").casefold()
    basename = normalized_path.rsplit("/", 1)[-1]
    for diagnostic_line in diagnostics.splitlines():
        normalized_line = diagnostic_line.replace("\\", "/").casefold()
        if normalized_path not in normalized_line and basename not in normalized_line:
            continue
        for match in re.finditer(r"(?:\(|:|\[)(\d+)(?:[,):\]])", diagnostic_line):
            line_number = int(match.group(1))
            if 1 <= line_number <= len(current_lines):
                anchors.add(line_number - 1)

    if not anchors:
        anchors.add(0)
    windows: list[tuple[int, int]] = []
    for anchor in sorted(anchors):
        start = max(0, anchor - 18)
        end = min(len(current_lines), anchor + 19)
        if windows and start <= windows[-1][1] + 3:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))

    rendered: list[str] = []
    emitted = 0
    for start, end in windows:
        if emitted >= 220:
            break
        end = min(end, start + (220 - emitted))
        if rendered:
            rendered.append("... omitted unchanged lines ...")
        rendered.extend(f"{index + 1}: {current_lines[index]}" for index in range(start, end))
        emitted += end - start
    return "\n".join(rendered)


def _validation_repair_targets(previewed_files: list[dict], diagnostics: str) -> set[str]:
    normalized_diagnostics = diagnostics.replace("\\", "/").casefold()
    matched: set[str] = set()
    for item in previewed_files:
        path = str(item.get("path", ""))
        normalized_path = path.replace("\\", "/").casefold()
        basename = normalized_path.rsplit("/", 1)[-1]
        if normalized_path in normalized_diagnostics or (basename and basename in normalized_diagnostics):
            matched.add(path)
    return matched or {str(item.get("path", "")) for item in previewed_files}


def _duplicate_definition_error(original: str, candidate: str, diagnostics: str, path: str) -> str:
    """Reject repeated definitions for symbols explicitly reported as duplicates by a validator."""
    normalized_path = path.replace("\\", "/").casefold()
    basename = normalized_path.rsplit("/", 1)[-1]
    symbols: set[str] = set()
    duplicate_markers = ("cs0102", "cs0111", "duplicate", "already defined", "already contains", "미리 정의", "정의가 포함")
    for line in diagnostics.splitlines():
        normalized_line = line.replace("\\", "/").casefold()
        if normalized_path not in normalized_line and basename not in normalized_line:
            continue
        if not any(marker in normalized_line for marker in duplicate_markers):
            continue
        quoted = re.findall(r"['\"`]([A-Za-z_][A-Za-z0-9_]*)['\"`]", line)
        if quoted:
            symbols.add(quoted[-1])

    for symbol in sorted(symbols):
        escaped = re.escape(symbol)
        definition_patterns = (
            rf"\bx:Name\s*=\s*['\"]{escaped}['\"]",
            rf"(?m)^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract|sealed|async|extern|new|partial)\s+)*[A-Za-z_][\w<>,.\[\]?\s]*\s+{escaped}\s*\([^;{{}}]*\)\s*(?:\{{|=>)",
            rf"(?m)^\s*(?:async\s+)?def\s+{escaped}\s*\(",
            rf"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+{escaped}\s*\(",
            rf"(?m)^\s*(?:class|struct|interface|enum)\s+{escaped}\b",
        )
        original_count = sum(len(re.findall(pattern, original)) for pattern in definition_patterns)
        candidate_count = sum(len(re.findall(pattern, candidate)) for pattern in definition_patterns)
        if candidate_count > original_count and candidate_count > max(1, original_count):
            return f"검증 진단에 보고된 심볼을 한 파일에 중복 정의했습니다: {symbol} ({candidate_count}회)"
    return ""


class OllamaClient:
    def __init__(self, base: str | None = None) -> None:
        self.base = (base or get_string_setting("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.num_ctx = get_int_setting("OLLAMA_NUM_CTX", 8_192, 4_096, 131_072)

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base}/api/tags")
            response.raise_for_status()
            return sorted(model["name"] for model in response.json().get("models", []))

    async def model_capabilities(self, model: str) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base}/api/show", json={"model": model})
            response.raise_for_status()
            return response.json().get("capabilities", [])

    async def list_model_details(self) -> list[dict]:
        names = await self.list_models()
        capabilities = await asyncio.gather(
            *(self.model_capabilities(name) for name in names), return_exceptions=True
        )
        return [
            {
                "name": name,
                "capabilities": value if isinstance(value, list) else [],
                "supports_tools": isinstance(value, list) and "tools" in value,
            }
            for name, value in zip(names, capabilities)
        ]

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
            response = await client.post(
                f"{self.base}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1536},
                },
            )
            if response.is_error:
                try:
                    detail = response.json().get("error", response.text)
                except ValueError:
                    detail = response.text
                raise RuntimeError(f"Ollama 요청 오류: {detail or response.status_code}")
            return response.json()["message"]

    async def force_tool_call(self, model: str, messages: list[dict], tools: list[dict]) -> dict | None:
        """Recover when a small model answers in prose instead of selecting an available tool."""
        allowed = {
            str(item.get("function", {}).get("name", "")): item.get("function", {})
            for item in tools
            if item.get("function", {}).get("name")
        }
        if not allowed:
            return None
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": list(allowed)},
                "arguments": {"type": "object"},
            },
            "required": ["name", "arguments"],
        }
        tool_catalog = [
            {
                "name": name,
                "description": definition.get("description", ""),
                "parameters": definition.get("parameters", {}),
            }
            for name, definition in allowed.items()
        ]
        forced_messages = [
            *messages,
            {"role": "system", "content": (
                "직전 응답에는 실행 도구가 없었습니다. 완료 설명이나 계획을 쓰지 말고, 현재 작업을 실제로 "
                "진행할 다음 도구 하나를 JSON으로 선택하세요. 아직 파일을 수정하지 않았다면 finish_changes를 "
                "선택하지 마세요. 대화에서 가장 마지막 user 메시지만 현재 실행할 작업이며, 이전 assistant의 "
                "완료 요약이나 과거 사용자 요청을 다시 실행하지 마세요. arguments는 선택한 도구의 parameters를 "
                "정확히 따라야 합니다. apply_patch를 선택하면 patch는 반드시 정확히 `*** Begin Patch`, "
                "`*** Update File: path`, `@@`, 변경 줄, `*** End Patch` 형식으로 작성하고 ---/+++ 헤더, "
                "타임스탬프, 숫자 hunk 헤더를 사용하지 마세요. 변경 전 문맥은 최근 tool 읽기 결과에서 공백까지 "
                "그대로 복사하고 placeholder가 아닌 완전한 구현을 작성하세요.\n"
                "사용 가능한 도구: " + json.dumps(tool_catalog, ensure_ascii=False)
            )},
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5)) as client:
            response = await client.post(
                f"{self.base}/api/chat",
                json={
                    "model": model,
                    "messages": forced_messages,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1024},
                },
            )
            response.raise_for_status()
        try:
            payload = json.loads(str(response.json()["message"].get("content", "")))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        name = str(payload.get("name", "")) if isinstance(payload, dict) else ""
        arguments = normalize_tool_arguments(payload.get("arguments", {})) if isinstance(payload, dict) else {}
        if name not in allowed or not isinstance(arguments, dict):
            return None
        return {"function": {"name": name, "arguments": arguments}}

    async def plan_search_terms(self, model: str, question: str, project_map: dict) -> list[str]:
        messages = [
            {"role": "system", "content": (
                "You plan repository searches for a coding agent. Return JSON only with a queries array. "
                "Generate 4 to 10 grep-ready code tokens, not natural-language questions. Each query must be an identifier, filename fragment, string literal, or API name of 1 to 3 words. "
                "Include exact identifiers from the question and likely English source-code synonyms appropriate for the detected languages. "
                "Examples: a C++ storage question should yield tokens like settings, config, save, persist, ofstream, fopen, filesystem; a network question might yield socket, connect, send, recv. "
                "Be framework agnostic. Never output phrases such as 'where is' or answer the question."
            )},
            {"role": "user", "content": json.dumps({"question": question, "project_map": project_map}, ensure_ascii=False)},
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
            response = await client.post(
                f"{self.base}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 128},
                },
            )
            response.raise_for_status()
        try:
            content = response.json()["message"]["content"]
            payload = json.loads(content)
            queries = payload.get("queries", []) if isinstance(payload, dict) else []
            return [str(query).strip() for query in queries if str(query).strip()][:8]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []

    async def answer_from_evidence(self, model: str, question: str, project_map: dict, evidence: dict, history: list[dict] | None = None, feedback: str = "") -> str:
        messages = [
            {"role": "system", "content": (
                "당신은 저장소 코드 근거만 사용해 답하는 코딩 에이전트의 최종 답변 단계입니다. 반드시 자연스러운 한국어로 답하세요. "
                "도구 호출, JSON, 도구 사용 계획, 추가 정보 요청을 출력하지 마세요. 결론을 먼저 말하고 확인한 상대 파일 경로와 코드 흐름을 짧게 설명하세요. "
                "함수·클래스·파일 이름은 repository_evidence의 content에 나온 철자를 그대로 복사하고, 근거에서 확인되지 않은 심볼명은 만들지 마세요. "
                "근거에 없는 내용은 추측하지 말고 확인 가능한 범위만 명시하세요."
            )},
            {"role": "user", "content": json.dumps({
                "question": question,
                "validation_feedback": feedback,
                "conversation_context": history or [],
                "project_map": project_map,
                "repository_evidence": evidence,
            }, ensure_ascii=False)},
        ]
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
            response = await client.post(
                f"{self.base}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1024},
                },
            )
            response.raise_for_status()
        return str(response.json()["message"].get("content", "")).strip()

    async def propose_from_evidence(self, model: str, request: str, project_map: dict, evidence: dict, history: list[dict] | None = None, feedback: str = "") -> dict:
        submit_tool = {"type": "function", "function": {
            "name": "submit_file_patch",
            "description": "현재 파일에 필요한 변경 연산만 제출합니다. 설명 대신 반드시 이 도구를 호출하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["insert_after_line", "insert_before_line", "replace_lines", "delete_lines"]},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                                "content": {"type": "string"},
                            },
                            "required": ["op", "start_line", "end_line", "content"],
                        },
                    }
                },
                "required": ["operations"],
            },
        }}
        plan_tool = {"type": "function", "function": {
            "name": "submit_patch_plan",
            "description": "요청을 파일별 책임에 맞는 짧은 작업으로 분해합니다. 코드는 작성하지 않습니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}, "task": {"type": "string"}},
                            "required": ["path", "task"],
                        },
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                },
                "required": ["files", "acceptance_criteria"],
            },
        }}
        evidence_files = evidence.get("files", [])
        candidate_files = [{
            "path": item.get("path"),
            "matched_queries": item.get("matched_queries", []),
            "content_preview": str(item.get("content", ""))[:1_000],
        } for item in evidence_files]
        plan_messages = [
            {"role": "system", "content": (
                "Call submit_patch_plan exactly once. Split the request by each file's existing responsibility and write no code. "
                "First convert every part of the user's request into observable acceptance criteria. Then choose every candidate file "
                "whose existing responsibility must change to satisfy those criteria, including definitions, callers, contracts, tests, "
                "configuration, and surrounding existing behavior when applicable. Do not assume a framework or project type. "
                "When the request depends on where or how an existing operation stores, loads, sends, or deletes data, trace that operation's "
                "implementation and plan the new behavior beside the existing source of truth. Do not reconstruct paths, endpoints, keys, or "
                "configuration values in a caller when an existing service, provider, or configuration already owns them. "
                "Use only candidate file paths, omit files that need no change, and do not treat touching one file as task completion. "
                "Most changes need only one to three files. Selecting a file without a concrete, request-specific responsibility is an error; "
                "never select a file merely because it appears in candidate_files."
            )},
            {"role": "user", "content": json.dumps({
                "request": request,
                "project_languages": project_map.get("languages", []),
                "candidate_files": candidate_files,
                "previous_validation_feedback": feedback,
            }, ensure_ascii=False)},
        ]
        plan_payload: dict = {}
        for plan_attempt in range(2):
            attempt_messages = list(plan_messages)
            if plan_attempt:
                attempt_messages.append({"role": "system", "content": (
                    "The previous plan response was missing or malformed. Do not call a tool. Output exactly one JSON object matching "
                    "the supplied schema, with files and acceptance_criteria arrays. Use only candidate file paths."
                )})
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5)) as client:
                    request_payload = {
                        "model": model,
                        "messages": attempt_messages,
                        "stream": False,
                        "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 384},
                    }
                    if plan_attempt == 0:
                        request_payload["tools"] = [plan_tool]
                    else:
                        request_payload["format"] = plan_tool["function"]["parameters"]
                    plan_response = await client.post(f"{self.base}/api/chat", json=request_payload)
                    plan_response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise TimeoutError("파일별 변경 계획 생성 시간이 90초를 초과했습니다.") from exc
            plan_message = plan_response.json().get("message", {})
            plan_calls = plan_message.get("tool_calls", [])
            plan_payload = normalize_tool_arguments(
                plan_calls[0].get("function", {}).get("arguments", {}) if plan_calls else {}
            )
            if not plan_payload:
                plan_payload = _payload_from_message_content(str(plan_message.get("content", "")))
            if isinstance(plan_payload.get("files"), list) and isinstance(plan_payload.get("acceptance_criteria"), list):
                break
        if not isinstance(plan_payload.get("files"), list):
            raise ValueError("모델이 구조화된 파일별 변경 계획을 생성하지 못했습니다.")
        valid_paths = {item.get("path") for item in evidence_files}
        tasks_by_path = {
            item.get("path"): str(item.get("task", "")).strip()
            for item in plan_payload.get("files", [])
            if isinstance(item, dict) and item.get("path") in valid_paths and str(item.get("task", "")).strip()
        }
        acceptance_criteria = [
            str(item).strip() for item in plan_payload.get("acceptance_criteria", [])
            if str(item).strip()
        ][:8]
        if not acceptance_criteria:
            acceptance_criteria = ["Every explicitly requested behavior is implemented and reachable through the project's existing structure."]
        required_paths = [path for path in evidence.get("required_change_paths", []) if path in valid_paths]
        for required_path in required_paths:
            tasks_by_path.setdefault(
                required_path,
                "Implement every part of the request that belongs to this file's existing responsibility. A non-empty patch is required.",
            )
        if not tasks_by_path:
            raise ValueError("파일별 변경 계획이 비어 있습니다.")
        planned_files: list[dict] = []
        operation_count = 0
        for target_file in reversed(evidence_files):
            if operation_count >= 12:
                break
            assigned_task = tasks_by_path.get(target_file.get("path"))
            if not assigned_task:
                continue
            numbered_content = "\n".join(
                f"{target_file.get('start_line', 1) + index}: {line}"
                for index, line in enumerate(str(target_file.get("content", "")).splitlines())
            )
            numbered_target_file = {
                **target_file,
                "content": numbered_content,
                "header": "\n".join(
                    f"{index + 1}: {line}"
                    for index, line in enumerate(str(target_file.get("header", "")).splitlines())
                ),
                "structural_boundary_hints": _structural_boundary_hints(target_file),
            }
            payload = {}
            file_rejection = ""
            for file_attempt in range(2):
                payload = {}
                required_non_empty = target_file.get("path") in tasks_by_path
                retry_instruction = (
                    f" Your previous response was rejected: {file_rejection}. "
                    "Return exactly one JSON object with an operations array whose result differs from the displayed source. Every range must "
                    "use displayed line numbers and must not overlap another operation. Output no explanation."
                    if file_attempt else ""
                )
                if required_non_empty:
                    retry_instruction += " This is a required change file, so the submitted change must not be empty."
                response_mode = (
                    "Call submit_file_patch exactly once and output no explanation."
                    if file_attempt == 0
                    else "Do not call a tool. Output exactly one JSON object matching the supplied schema and no explanation."
                )
                messages = [
                    {"role": "system", "content": (
                        f"You generate a patch for exactly one source file. {response_mode} "
                        "Return an empty operations array if this file needs no change. target_file.content has real line numbers. "
                        "Choose start_line and end_line only from those displayed lines. For insertion normally use the same line for both. "
                        "Insert content contains only new source code, without line-number prefixes. "
                        "Implement the assigned task completely in the file's existing structure and language. Inspect surrounding declarations, "
                        "callers, ordering, indices, contracts, and control flow; modify existing code whenever the requested behavior requires it. "
                        "target_file.header contains the real numbered file header when the main excerpt starts later. Check it for imports, includes, "
                        "namespace/package declarations, and aliases. Add a required import/include there or fully qualify a symbol; never introduce an "
                        "unresolved bare identifier. "
                        "Respect this file's existing architectural responsibility: keep reusable operations in service/library files and caller, "
                        "controller, or UI event wiring in the corresponding caller/controller files. When inserting an ordered item, update any "
                        "conflicting positions or indices in the surrounding existing items. "
                        "If an existing operation already owns a path, endpoint, key, or configuration source, reuse that same owner instead of "
                        "reconstructing the value independently in this file. "
                        "Never add an event handler to a service/library file unless that file already owns similar handlers. Never insert code "
                        "between a declaration/signature and its body, between an opening tag and its required children, or inside an unrelated "
                        "method/block. Insert a new class member immediately before the class's closing boundary; insert statements only inside "
                        "the intended existing body. Use replace_lines for the complete surrounding construct when a one-line insertion boundary "
                        "is ambiguous. Every operation must leave delimiters, braces, tags, and declarations structurally balanced. "
                        "target_file.structural_boundary_hints lists low-indentation closing boundaries found in the displayed excerpt. When adding "
                        "a class/type member, use the boundary that closes that type, not an inner method boundary and not the outer namespace/module boundary. "
                        "Do not confuse adding an isolated snippet with satisfying the assigned acceptance criteria. Avoid unrelated behavior changes. "
                        "Never add duplicate functions, placeholders, or TODO implementations. Keep names consistent with prior_file_patches."
                        f"{retry_instruction}"
                    )},
                    {"role": "user", "content": json.dumps({
                        "request": request,
                        "assigned_task_for_this_file": assigned_task,
                        "acceptance_criteria": acceptance_criteria,
                        "complete_file_plan": tasks_by_path,
                        "scope_rule": "Implement only assigned_task_for_this_file. Do not implement responsibilities assigned to other files.",
                        "validation_feedback": feedback,
                        "conversation_context": history or [],
                        "project_languages": project_map.get("languages", []),
                        "target_file": numbered_target_file,
                        "prior_file_identifiers": _compact_prior_patches(planned_files),
                    }, ensure_ascii=False)},
                ]
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
                        request_payload = {
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 896},
                        }
                        if file_attempt == 0:
                            request_payload["tools"] = [submit_tool]
                        else:
                            request_payload["format"] = submit_tool["function"]["parameters"]
                        response = await client.post(
                            f"{self.base}/api/chat",
                            json=request_payload,
                        )
                        response.raise_for_status()
                except httpx.TimeoutException as exc:
                    raise TimeoutError(f"{target_file.get('path', '파일')} 변경 생성 시간이 120초를 초과했습니다.") from exc
                message = response.json().get("message", {})
                calls = message.get("tool_calls", [])
                if calls:
                    payload = normalize_tool_arguments(calls[0].get("function", {}).get("arguments", {}))
                if not payload:
                    payload = _payload_from_message_content(str(message.get("content", "")))
                valid_payload = isinstance(payload.get("operations"), list)
                non_empty_payload = bool(payload.get("operations"))
                if non_empty_payload:
                    payload["operations"] = _coalesce_insert_operations(
                        str(target_file.get("content", "")),
                        payload.get("operations", []),
                        int(target_file.get("start_line", 1)),
                    )
                operation_error = (
                    _operation_validation_error(target_file, payload.get("operations", []))
                    if non_empty_payload else ""
                )
                valid_operations = non_empty_payload and not operation_error
                changes_evidence = valid_operations and _operations_change_evidence(target_file, payload.get("operations", []))
                if valid_payload and ((valid_operations and changes_evidence) or not required_non_empty):
                    break
                if not valid_payload:
                    file_rejection = "operations 배열이 없는 응답입니다"
                elif not non_empty_payload:
                    file_rejection = "필수 변경 파일인데 operations 배열이 비어 있습니다"
                elif operation_error:
                    file_rejection = operation_error
                else:
                    file_rejection = "원문과 결과가 같은 무변경 연산입니다"
            if (
                not isinstance(payload.get("operations"), list)
                or (required_non_empty and not payload.get("operations"))
                or (required_non_empty and not _operations_are_valid_for_evidence(target_file, payload.get("operations", [])))
                or (required_non_empty and not _operations_change_evidence(target_file, payload.get("operations", [])))
            ):
                raise ValueError(
                    f"{target_file.get('path', '파일')}에서 구조화된 줄 변경 연산을 생성하지 못했습니다: "
                    f"{file_rejection or '알 수 없는 형식 오류'}"
                )
            operations = payload.get("operations")
            operations = operations[:12 - operation_count]
            if operations:
                planned_files.append({"path": target_file["path"], "operations": operations})
                operation_count += len(operations)
        return {
            "files": planned_files,
            "acceptance_criteria": acceptance_criteria,
            "file_plan": tasks_by_path,
        }

    async def review_proposal(
        self,
        model: str,
        request: str,
        project_map: dict,
        evidence: dict,
        proposal: dict,
        previewed_files: list[dict],
    ) -> dict:
        review_tool = {"type": "function", "function": {
            "name": "submit_change_review",
            "description": "Judge whether the complete proposed change satisfies the user's request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "complete": {"type": "boolean"},
                    "missing_requirements": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                    "unsafe_or_inconsistent_changes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                    "files_needing_changes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                },
                "required": ["complete", "missing_requirements", "unsafe_or_inconsistent_changes", "files_needing_changes"],
            },
        }}
        diffs: list[dict] = []
        remaining = 14_000
        for item in previewed_files:
            diff = "\n".join(difflib.unified_diff(
                str(item.get("original", "")).splitlines(),
                str(item.get("modified", "")).splitlines(),
                fromfile=f"before/{item.get('path', '')}",
                tofile=f"after/{item.get('path', '')}",
                n=5,
                lineterm="",
            ))
            excerpt = diff[:min(remaining, 5_000)]
            remaining -= len(excerpt)
            diffs.append({"path": item.get("path"), "diff": excerpt})
            if remaining <= 0:
                break
        candidate_files = [{
            "path": item.get("path"),
            "content_preview": str(item.get("content", ""))[:1_200],
        } for item in evidence.get("files", [])]
        messages = [
            {"role": "system", "content": (
                "You are an independent, framework-agnostic code change reviewer. Call submit_change_review exactly once. "
                "Judge the user's observable intent, not whether files were merely touched. Reject a proposal when any requested behavior "
                "is unreachable, a definition/caller/contract/configuration/test or surrounding existing code still needs adaptation, an insertion "
                "collides with or replaces required existing behavior, code is placed in an invalid scope, or unrelated behavior changes. "
                "Reject duplicated sources of truth: if repository evidence shows an existing service/provider/configuration owns a path, endpoint, "
                "key, or resource location, a caller must reuse that owner rather than reconstructing a potentially different value. "
                "Use the repository evidence and diffs only. Do not invent project conventions and do not write code."
            )},
            {"role": "user", "content": json.dumps({
                "request": request,
                "languages": project_map.get("languages", []),
                "acceptance_criteria": proposal.get("acceptance_criteria", []),
                "file_plan": proposal.get("file_plan", {}),
                "candidate_files": candidate_files,
                "proposed_diffs": diffs,
            }, ensure_ascii=False)},
        ]
        payload: dict = {}
        for review_attempt in range(2):
            attempt_messages = list(messages)
            if review_attempt:
                attempt_messages.append({"role": "system", "content": (
                    "Your previous incomplete verdict had no actionable reason and is invalid. Review again. If complete is false, "
                    "missing_requirements or unsafe_or_inconsistent_changes MUST contain a concrete, code-specific reason that explains "
                    "what must change and why. A filename alone is not a reason. Output exactly one JSON object and no explanation."
                )})
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
                    request_payload = {
                        "model": model,
                        "messages": attempt_messages,
                        "stream": False,
                        "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 512},
                    }
                    if review_attempt == 0:
                        request_payload["tools"] = [review_tool]
                    else:
                        request_payload["format"] = review_tool["function"]["parameters"]
                    response = await client.post(f"{self.base}/api/chat", json=request_payload)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise TimeoutError("변경안 완결성 검토 시간이 120초를 초과했습니다.") from exc
            message = response.json().get("message", {})
            calls = message.get("tool_calls", [])
            payload = normalize_tool_arguments(calls[0].get("function", {}).get("arguments", {})) if calls else {}
            if not payload:
                payload = _payload_from_message_content(str(message.get("content", "")))
            if not isinstance(payload.get("complete"), bool):
                continue
            actionable = [
                str(item).strip()
                for item in [
                    *payload.get("missing_requirements", []),
                    *payload.get("unsafe_or_inconsistent_changes", []),
                ]
                if str(item).strip()
            ]
            if payload.get("complete") or actionable:
                return payload
        if not isinstance(payload.get("complete"), bool):
            raise ValueError("모델이 구조화된 변경안 검토 결과를 반환하지 않았습니다.")
        return payload

    async def repair_from_validation(
        self,
        model: str,
        request: str,
        proposal: dict,
        previewed_files: list[dict],
        validation_feedback: str,
    ) -> dict:
        repair_tool = {"type": "function", "function": {
            "name": "submit_file_patch",
            "description": "Regenerate the requested change as line-based operations against the clean original file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["replace_lines", "insert_before_line", "insert_after_line", "delete_lines"]},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                                "content": {"type": "string"},
                            },
                            "required": ["op", "start_line", "end_line", "content"],
                        },
                    }
                },
                "required": ["operations"],
            },
        }}
        repaired_files: list[dict] = []
        repair_targets = _validation_repair_targets(previewed_files, validation_feedback)
        for item in previewed_files:
            current = str(item.get("modified", ""))
            original = str(item.get("original", ""))
            path = str(item.get("path", ""))
            if path not in repair_targets:
                repaired_files.append({"path": path, "changes": [{"old": original, "new": current}]})
                continue
            clean_original = original
            numbered_clean_original = "\n".join(
                f"{index + 1}: {line}" for index, line in enumerate(clean_original.splitlines())
            )
            if len(numbered_clean_original) > 18_000:
                numbered_clean_original = _repair_excerpt(current, clean_original, validation_feedback, path)
            numbered_clean_header = "\n".join(
                f"{index + 1}: {line}" for index, line in enumerate(clean_original.splitlines()[:80])
            )
            base_messages = [
                {"role": "system", "content": (
                    "You regenerate one validation-failing source-file change from its CLEAN ORIGINAL. Discard the rejected candidate completely; "
                    "do not repair or copy code from it. Call submit_file_patch exactly once with the smallest line-based operations that implement "
                    "the original request and avoid the reported diagnostics. Line numbers refer only to clean_original_with_line_numbers. Never rewrite "
                    "the entire file, never modify omitted lines except lines explicitly shown in clean_original_header_with_line_numbers, and preserve "
                    "unrelated code. Always inspect the header for imports/includes/package declarations. For unresolved identifiers, add the required "
                    "import/include in the shown header or use a valid fully-qualified name. Re-check declarations, return types, "
                    "includes/imports, call sites, scopes, markup structure, and duplicate symbols. Output no explanation. Content must not contain "
                    "line-number prefixes. Never insert between a declaration/signature and its body or inside an unrelated construct. New class "
                    "members belong immediately before the class closing boundary. Prefer one non-overlapping replacement of the complete broken "
                    "construct when several small operations would overlap. The rejected candidate is intentionally unavailable: infer a fresh, "
                    "self-contained implementation from the request, acceptance criteria, clean original, and validation diagnostics."
                )},
                {"role": "user", "content": json.dumps({
                    "request": request,
                    "acceptance_criteria": proposal.get("acceptance_criteria", []),
                    "validation_diagnostics": validation_feedback[-6_000:],
                    "path": path,
                    "clean_original_with_line_numbers": numbered_clean_original,
                    "clean_original_header_with_line_numbers": numbered_clean_header,
                }, ensure_ascii=False)},
            ]
            final_content: str | None = None
            repair_error = ""
            for repair_attempt in range(2):
                messages = list(base_messages)
                if repair_attempt:
                    messages.append({"role": "system", "content": (
                        f"The previous repair was rejected: {repair_error}. Return a new JSON operations array. "
                        "Every range must be inside the displayed clean original file and operations must not overlap. Output JSON only."
                    )})
                async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
                    request_payload = {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1024},
                    }
                    if repair_attempt == 0:
                        request_payload["tools"] = [repair_tool]
                    else:
                        request_payload["format"] = repair_tool["function"]["parameters"]
                    response = await client.post(f"{self.base}/api/chat", json=request_payload)
                    response.raise_for_status()
                message = response.json().get("message", {})
                calls = message.get("tool_calls", [])
                payload = normalize_tool_arguments(calls[0].get("function", {}).get("arguments", {})) if calls else {}
                if not payload:
                    payload = _payload_from_message_content(str(message.get("content", "")))
                operations = payload.get("operations")
                if not isinstance(operations, list) or not operations:
                    repair_error = "구조화된 수리 연산이 없습니다"
                    continue
                try:
                    candidate_content = _apply_repair_operations(
                        clean_original, _coalesce_insert_operations(clean_original, operations)
                    )
                except ValueError as exc:
                    repair_error = str(exc)
                    continue
                duplicate_error = _duplicate_definition_error(
                    clean_original, candidate_content, validation_feedback, path
                )
                if duplicate_error:
                    repair_error = duplicate_error
                    continue
                if candidate_content == clean_original:
                    repair_error = "실제 변경이 없습니다"
                    continue
                final_content = candidate_content
                break
            if final_content is None:
                raise ValueError(f"{item.get('path', '파일')}의 검증 오류를 수리하지 못했습니다: {repair_error or '결과 없음'}")
            repaired_files.append({
                "path": path,
                "changes": [{"old": original, "new": final_content}],
            })
        return {
            "files": repaired_files,
            "acceptance_criteria": proposal.get("acceptance_criteria", []),
            "file_plan": proposal.get("file_plan", {}),
        }

    async def chat_stream(self, model: str, messages: list[dict]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
            async with client.stream(
                "POST", f"{self.base}/api/chat", json={"model": model, "messages": messages, "stream": True}
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line
