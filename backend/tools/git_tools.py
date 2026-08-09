from difflib import SequenceMatcher

from security.path_guard import guard
from services.command_runner import run_command


MAX_DIFF_FILE_CHARS = 2_000_000


async def git_command(args: list[str], timeout: float = 60) -> dict:
    if not guard.root:
        raise ValueError("먼저 프로젝트를 열어주세요.")
    if not (guard.root / ".git").exists():
        raise ValueError("열린 프로젝트가 Git 저장소가 아닙니다.")
    return await run_command(["git", *args], str(guard.root), timeout=timeout)


async def status() -> dict:
    return await git_command(["status", "--short", "--branch"])


async def diff(staged: bool = False) -> dict:
    args = ["diff", "--no-ext-diff"]
    if staged:
        args.append("--cached")
    return await git_command(args)


async def _git_blob(reference: str) -> str:
    result = await git_command(["show", reference], timeout=120)
    return result["stdout"] if result["return_code"] == 0 else ""


def _line_stats(original: str, modified: str) -> tuple[int, int]:
    matcher = SequenceMatcher(a=original.splitlines(), b=modified.splitlines(), autojunk=False)
    additions = 0
    deletions = 0
    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if operation in ("insert", "replace"):
            additions += new_end - new_start
        if operation in ("delete", "replace"):
            deletions += old_end - old_start
    return additions, deletions


async def staged_changes() -> dict:
    result = await git_command(["diff", "--cached", "--name-status", "-z", "--find-renames"], timeout=120)
    if result["return_code"] != 0:
        raise ValueError(result["stderr"].strip() or "스테이징 변경 파일을 확인하지 못했습니다.")

    parts = result["stdout"].split("\0")
    files = []
    index = 0
    status_names = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "modified"}
    while index < len(parts) and parts[index]:
        raw_status = parts[index]
        index += 1
        status_code = raw_status[0]
        old_path = ""
        if status_code in ("R", "C"):
            if index + 1 >= len(parts):
                break
            old_path = parts[index]
            path = parts[index + 1]
            index += 2
        else:
            if index >= len(parts):
                break
            path = parts[index]
            index += 1

        source_path = old_path or path
        original = "" if status_code == "A" else await _git_blob(f"HEAD:{source_path}")
        modified = "" if status_code == "D" else await _git_blob(f":{path}")
        binary = "\0" in original or "\0" in modified
        truncated = len(original) > MAX_DIFF_FILE_CHARS or len(modified) > MAX_DIFF_FILE_CHARS
        if binary:
            original = ""
            modified = ""
        elif truncated:
            original = original[:MAX_DIFF_FILE_CHARS]
            modified = modified[:MAX_DIFF_FILE_CHARS]
        additions, deletions = _line_stats(original, modified)
        files.append({
            "path": path,
            "old_path": old_path or None,
            "status": status_names.get(status_code, "modified"),
            "additions": additions,
            "deletions": deletions,
            "original": original,
            "modified": modified,
            "binary": binary,
            "truncated": truncated,
        })
    return {"files": files}


async def stage_all() -> dict:
    return await git_command(["add", "-A"])


async def unstage_all() -> dict:
    result = await git_command(["restore", "--staged", "."])
    if result["return_code"] != 0:
        return await git_command(["reset"])
    return result


async def commit(message: str) -> dict:
    message = message.strip()
    if not message:
        raise ValueError("커밋 메시지를 입력해 주세요.")
    return await git_command(["commit", "-m", message], timeout=120)


async def branches() -> dict:
    result = await git_command([
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
        "refs/remotes/origin",
    ])
    if result["return_code"] != 0:
        return {"current": "", "branches": [], "result": result}

    local_result = await git_command([
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
    ])
    local = {line.strip() for line in local_result["stdout"].splitlines() if line.strip()}
    names = set(local)
    for line in result["stdout"].splitlines():
        reference = line.strip()
        if reference.startswith("origin/") and reference != "origin/HEAD":
            names.add(reference.removeprefix("origin/"))

    current_result = await git_command(["branch", "--show-current"])
    return {
        "current": current_result["stdout"].strip() or "HEAD",
        "branches": sorted(names, key=str.casefold),
        "local_branches": sorted(local, key=str.casefold),
    }


async def checkout(branch: str) -> dict:
    branch = branch.strip()
    available = await branches()
    if branch not in available["branches"]:
        raise ValueError(f"Git 저장소에 없는 브랜치입니다: {branch}")
    if branch == available["current"]:
        return {
            "command": f"git switch {branch}",
            "return_code": 0,
            "stdout": f"이미 {branch} 브랜치입니다.",
            "stderr": "",
            "duration": 0,
        }
    if branch in available["local_branches"]:
        return await git_command(["switch", branch], timeout=120)
    return await git_command(["switch", "--track", f"origin/{branch}"], timeout=120)


async def repository_info() -> dict:
    branch_result = await git_command(["branch", "--show-current"])
    remote_result = await git_command(["remote", "get-url", "origin"])
    changes_result = await git_command(["status", "--porcelain"])
    branch = branch_result["stdout"].strip() or "HEAD"
    remote = remote_result["stdout"].strip()
    lines = [line for line in changes_result["stdout"].splitlines() if line]
    has_staged = any(line[0] not in (" ", "?") for line in lines)
    has_unstaged = any(len(line) > 1 and (line[1] != " " or line.startswith("??")) for line in lines)
    branch_info = await branches()
    return {
        "branch": branch,
        "branches": branch_info["branches"],
        "remote": remote,
        "has_changes": bool(lines),
        "has_staged": has_staged,
        "has_unstaged": has_unstaged,
    }


async def push() -> dict:
    info = await repository_info()
    if not info["remote"]:
        raise ValueError("origin 원격 저장소가 설정되어 있지 않습니다.")
    upstream = await git_command(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream["return_code"] == 0:
        return await git_command(["push"], timeout=300)
    return await git_command(["push", "-u", "origin", info["branch"]], timeout=300)
