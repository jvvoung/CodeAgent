import argparse
import asyncio
import difflib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent.agent_loop import run_agent
from security.path_guard import guard
from services.conversation_store import ConversationStore
from tools.patch_tools import pending


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--question", default="저장이라는 버튼을 누르면 파일이 생성되는 경로가 어디야?")
    parser.add_argument("--show-diff", action="store_true")
    args = parser.parse_args()

    guard.open(args.project)
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(dict(event))
        print(json.dumps({"event": event}, ensure_ascii=False), flush=True)

    try:
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "conversations.json")
            with patch("agent.agent_loop.conversations", store):
                result = await run_agent(args.question, args.model, on_event)
        print(json.dumps({"result": result}, ensure_ascii=False, indent=2), flush=True)
        if args.show_diff:
            for path, item in pending.items():
                diff = "\n".join(difflib.unified_diff(
                    str(item["original"]).splitlines(),
                    str(item["modified"]).splitlines(),
                    fromfile=f"before/{path}",
                    tofile=f"after/{path}",
                    lineterm="",
                ))
                print(diff, flush=True)
        completed = {event["tool"] for event in events if event.get("status") == "completed"}
        grounded = bool(completed & {"read_file", "read_file_range"}) and bool(result.get("relevant_files"))
        change_requested = any(term in args.question.casefold() for term in ("추가", "수정", "변경", "삭제", "add", "change", "modify", "delete"))
        proposal_completed = "propose_changes" in completed
        return 0 if grounded and (proposal_completed or not change_requested) else 1
    finally:
        guard.root = None


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
