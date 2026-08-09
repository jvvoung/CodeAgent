import logging
import asyncio
import json
import platform

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.agent_loop import run_agent
from llm.ollama_client import OllamaClient
from models.schemas import ApplyRequest, BranchCheckoutRequest, ChatRequest, CommitRequest, OpenProjectRequest, PushRequest, SearchRequest, TerminalRequest
from security.path_guard import guard
from services.conversation_store import conversations
from tools.build_tools import run_build
from tools.file_tools import read_file, search_code, tree
from tools.git_tools import commit as git_commit_command
from tools.git_tools import checkout as git_checkout_command
from tools.git_tools import diff as git_diff_command
from tools.git_tools import push as git_push_command
from tools.git_tools import repository_info as git_info_command
from tools.git_tools import stage_all as git_stage_command
from tools.git_tools import staged_changes as git_staged_changes_command
from tools.git_tools import status as git_status_command
from tools.git_tools import unstage_all as git_unstage_command
from tools.patch_tools import apply, clear, pending, reject
from tools.terminal_tools import run_terminal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Local Coding Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def fail(exc: object) -> None:
    logger.warning("Request failed: %s", exc)
    message = str(exc).strip() or f"{type(exc).__name__}: 자세한 오류 메시지가 없습니다."
    raise HTTPException(status_code=400, detail=message)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "python": platform.python_version(),
        "project": str(guard.root) if guard.root else None,
        "agent_core": "persistent-ollama-tools-v1",
    }


@app.get("/api/ollama/models")
async def models():
    try:
        return {"models": await OllamaClient().list_model_details()}
    except Exception as exc:
        return {"models": [], "error": f"Ollama unavailable: {exc}"}


@app.post("/api/project/open")
async def open_project(body: OpenProjectRequest):
    try:
        root = guard.open(body.path)
        clear()
        return {"path": str(root), "name": root.name, "tree": tree()}
    except Exception as exc:
        fail(exc)


@app.get("/api/project/tree")
async def project_tree():
    try:
        return {"tree": tree()}
    except Exception as exc:
        fail(exc)


@app.get("/api/conversation")
async def conversation_history():
    try:
        if not guard.root:
            raise ValueError("먼저 프로젝트를 열어주세요.")
        return {"messages": conversations.messages(guard.root)}
    except Exception as exc:
        fail(exc)


@app.delete("/api/conversation")
async def clear_conversation():
    try:
        if not guard.root:
            raise ValueError("먼저 프로젝트를 열어주세요.")
        conversations.clear(guard.root)
        return {"ok": True}
    except Exception as exc:
        fail(exc)


@app.get("/api/file")
async def file(path: str):
    try:
        return {"path": path, "content": read_file(path)}
    except Exception as exc:
        fail(exc)


@app.post("/api/search")
async def search(body: SearchRequest):
    try:
        return {"results": search_code(body.query)}
    except Exception as exc:
        fail(exc)


@app.post("/api/agent/chat")
async def chat(body: ChatRequest):
    try:
        return await run_agent(body.message, body.model)
    except Exception as exc:
        fail(exc)


@app.post("/api/agent/chat/stream")
async def chat_stream(body: ChatRequest):
    async def stream():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def emit(event: dict[str, str]) -> None:
            await queue.put({"type": "status", "event": event})

        async def execute() -> dict:
            return await run_agent(body.message, body.model, on_event=emit)

        yield json.dumps({"type": "started"}, ensure_ascii=False) + "\n"
        task = asyncio.create_task(execute())
        try:
            while not task.done() or not queue.empty():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                    yield json.dumps(item, ensure_ascii=False) + "\n"
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
            result = await task
            yield json.dumps({"type": "complete", "result": result}, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.exception("Streaming agent failed")
            message = str(exc).strip() or "AI 응답 처리 중 알 수 없는 오류가 발생했습니다."
            yield json.dumps({"type": "error", "message": message}, ensure_ascii=False) + "\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/changes")
async def changes():
    return {"changes": [{"path": path, **item} for path, item in pending.items()]}


@app.post("/api/change/apply")
async def apply_changes(body: ApplyRequest):
    try:
        return {"ok": True, "paths": apply(body.paths, confirm_unverified=body.confirm_unverified)}
    except Exception as exc:
        fail(exc)


@app.post("/api/change/reject")
async def reject_changes(body: ApplyRequest):
    return {"ok": True, "paths": reject(body.paths)}


@app.get("/api/git/status")
async def git_status():
    try:
        return await git_status_command()
    except Exception as exc:
        fail(exc)


@app.get("/api/git/diff")
async def git_diff():
    try:
        return await git_diff_command()
    except Exception as exc:
        fail(exc)


@app.get("/api/git/diff/staged")
async def git_staged_diff():
    try:
        return await git_diff_command(staged=True)
    except Exception as exc:
        fail(exc)


@app.get("/api/git/staged-changes")
async def git_staged_changes():
    try:
        return await git_staged_changes_command()
    except Exception as exc:
        fail(exc)


@app.get("/api/git/info")
async def git_info():
    try:
        return await git_info_command()
    except Exception as exc:
        fail(exc)


@app.post("/api/git/checkout")
async def git_checkout(body: BranchCheckoutRequest):
    try:
        result = await git_checkout_command(body.branch)
        if result["return_code"] != 0:
            raise ValueError(result["stderr"].strip() or result["stdout"].strip() or "브랜치 전환에 실패했습니다.")
        clear()
        return {
            "result": result,
            "tree": tree(),
            "git": await git_info_command(),
        }
    except Exception as exc:
        fail(exc)


@app.post("/api/git/stage")
async def git_stage():
    try:
        return await git_stage_command()
    except Exception as exc:
        fail(exc)


@app.post("/api/git/unstage")
async def git_unstage():
    try:
        return await git_unstage_command()
    except Exception as exc:
        fail(exc)


@app.post("/api/git/commit")
async def git_commit(body: CommitRequest):
    try:
        return await git_commit_command(body.message)
    except Exception as exc:
        fail(exc)


@app.post("/api/git/push")
async def git_push(body: PushRequest):
    try:
        return await git_push_command()
    except Exception as exc:
        fail(exc)


@app.post("/api/build")
async def build():
    try:
        return await run_build()
    except Exception as exc:
        fail(exc)


@app.post("/api/test")
async def test():
    try:
        return await run_build(test=True)
    except Exception as exc:
        fail(exc)


@app.post("/api/terminal")
async def terminal(body: TerminalRequest):
    try:
        return await run_terminal(body.shell, body.command, cwd=body.cwd)
    except Exception as exc:
        fail(exc)
