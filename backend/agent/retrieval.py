import os
import re
from collections import defaultdict

from tools.file_tools import read_file_range, search_code


KOREAN_SUFFIXES = (
    "이라는", "라고", "에서는", "으로는", "으로", "에서", "되는", "하는", "하면", "되어", "돼서",
    "인지", "인가", "나요", "해줘", "한다", "된다", "됐다", "번째", "처럼", "까지", "부터",
    "의", "을", "를", "이", "가", "은", "는", "에", "로", "와", "과", "야", "줘",
)
STOP_WORDS = {
    "프로젝트", "코드", "소스", "파일", "경로", "폴더", "질문", "현재", "어디", "어떻게", "무엇",
    "뭐", "왜", "알려", "확인", "관련", "해줘", "대한", "사용", "project", "code", "file", "path",
    "where", "what", "why", "how", "please", "current", "this", "that", "does", "when",
    "에서", "으로", "에게", "부터", "까지",
}


def _normalize_korean(token: str) -> str:
    for suffix in KOREAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[:-len(suffix)]
    return token


def extract_search_terms(message: str, limit: int = 8) -> list[str]:
    terms: list[str] = []

    def add(value: str) -> None:
        value = value.strip().strip("`'\"")
        if len(value) < 2 or value.casefold() in STOP_WORDS or value.casefold() in {term.casefold() for term in terms}:
            return
        terms.append(value)

    for quoted in re.findall(r"[`\"'“”]([^`\"'“”]{2,120})[`\"'“”]", message):
        add(quoted)
    for identifier in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:(?:::|->|\.)[A-Za-z_][A-Za-z0-9_]*)+(?![A-Za-z0-9_])", message):
        add(identifier)
        for part in re.split(r"::|->|\.", identifier):
            add(part)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[가-힣]{2,}", message):
        add(_normalize_korean(token) if re.fullmatch(r"[가-힣]+", token) else token)
    return terms[:limit]


def _environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def collect_repository_evidence(
    message: str,
    extra_terms: list[str] | None = None,
    max_files: int | None = None,
    max_chars: int | None = None,
    max_file_chars: int | None = None,
) -> dict:
    if max_files is None:
        max_files = _environment_int("AURA_EVIDENCE_MAX_FILES", 5, 1, 12)
    if max_chars is None:
        max_chars = _environment_int("AURA_EVIDENCE_MAX_CHARS", 15_000, 4_000, 100_000)
    if max_file_chars is None:
        max_file_chars = _environment_int("AURA_EVIDENCE_MAX_FILE_CHARS", 4_000, 1_000, 20_000)
    terms = extract_search_terms(message)
    for term in extra_terms or []:
        cleaned = str(term).strip()
        if cleaned and cleaned.casefold() not in {item.casefold() for item in terms}:
            terms.append(cleaned)
        if len(terms) >= 12:
            break

    matches: list[dict] = []
    by_path: dict[str, list[dict]] = defaultdict(list)
    for term in terms:
        try:
            hits = search_code(term, limit=40)
        except ValueError:
            continue
        for hit in hits:
            item = {**hit, "query": term}
            matches.append(item)
            by_path[hit["path"]].append(item)
        if len(matches) >= 120:
            break

    term_weights = {term: max(1, len(terms) - index) for index, term in enumerate(terms)}

    def path_score(path: str) -> tuple[int, int, str]:
        lowered = path.casefold()
        score = sum(term_weights.get(item["query"], 1) for item in by_path[path])
        score += len({item["query"] for item in by_path[path]}) * 4
        if path.rsplit(".", 1)[-1].casefold() in {"c", "cc", "cpp", "cxx", "h", "hpp", "cs", "java", "kt", "py", "js", "ts", "tsx", "xaml", "rs", "go"}:
            score += 5
        if any(part in lowered for part in ("readme", "guide", "/docs/", "/test", "mock", "sample", "example")):
            score -= 60
        return (-score, min(item["line"] for item in by_path[path]), path)

    ranked = sorted(by_path, key=path_score)
    documentation_markers = ("readme", "guide", "/docs/", "/test", "mock", "sample", "example")
    source_paths = [path for path in ranked if not any(marker in path.casefold() for marker in documentation_markers)]
    documentation_paths = [path for path in ranked if path not in source_paths]
    ranked = [*source_paths, *documentation_paths]

    def logical_stem(path: str) -> str:
        lowered = path.casefold()
        for suffix in (".xaml.cs", ".designer.cs", ".g.cs", ".cpp", ".cxx", ".cc", ".hpp", ".hh", ".cs", ".xaml", ".h", ".c"):
            if lowered.endswith(suffix):
                return lowered[:-len(suffix)]
        return lowered.rsplit(".", 1)[0]

    if ranked:
        lead = ranked[0]
        lead_stem = logical_stem(lead)
        paired = [path for path in ranked[1:] if logical_stem(path) == lead_stem]
        ranked = [lead, *paired, *(path for path in ranked[1:] if path not in paired)]
    ranked_paths = ranked[:max_files]
    excerpts: list[dict] = []
    total_chars = 0
    for path in ranked_paths:
        path_hits = by_path[path]
        best_start = max(1, path_hits[0]["line"] - 24)
        best_score = -1
        for hit in path_hits:
            candidate_start = max(1, hit["line"] - 24)
            candidate_end = candidate_start + 139
            candidate_score = sum(
                term_weights.get(item["query"], 1)
                for item in path_hits
                if candidate_start <= item["line"] <= candidate_end
            )
            if candidate_score > best_score:
                best_start = candidate_start
                best_score = candidate_score
        start = best_start
        end = start + 139
        try:
            excerpt = read_file_range(path, start, end)
        except (OSError, ValueError):
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        header_content = ""
        if start > 1:
            try:
                header_content = read_file_range(path, 1, min(60, start - 1))["content"][:2_000]
            except (OSError, ValueError):
                header_content = ""
        content_budget = max(0, remaining - len(header_content))
        excerpt["content"] = excerpt["content"][:min(content_budget, max_file_chars)]
        excerpt["header"] = header_content
        excerpt["matched_queries"] = sorted({item["query"] for item in by_path[path]})
        excerpts.append(excerpt)
        total_chars += len(excerpt["content"]) + len(header_content)

    return {
        "queries": terms,
        "match_count": len(matches),
        "matches": matches[:40],
        "files": excerpts,
    }
