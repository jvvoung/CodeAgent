import logging
import asyncio
import json
import platform

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.agent_loop import run_agent
from llm.ollama_client import OllamaClient
from models.schemas import ApplyRequest, ChatRequest, OpenProjectRequest, SearchRequest
from security.path_guard import guard
from tools.build_tools import run_build
from tools.file_tools import read_file, search_code, tree
from tools.git_tools import diff as git_diff_command
from tools.git_tools import status as git_status_command
from tools.patch_tools import apply, clear, pending, reject

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
    raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "python": platform.python_version(),
        "project": str(guard.root) if guard.root else None,
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
        return {"ok": True, "paths": apply(body.paths)}
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
