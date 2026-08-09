import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.agent_loop import run_agent
from security.path_guard import guard
from services.conversation_store import ConversationStore


class ConversationStoreTest(unittest.TestCase):
    def test_persists_and_separates_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "memory" / "conversations.json"
            project_a = root / "project-a"
            project_b = root / "project-b"
            project_a.mkdir()
            project_b.mkdir()
            store = ConversationStore(path)
            store.append_turn(project_a, "첫 질문", "첫 답변")
            store.append_turn(project_b, "다른 질문", "다른 답변")

            reloaded = ConversationStore(path)
            self.assertEqual([item["content"] for item in reloaded.messages(project_a)], ["첫 질문", "첫 답변"])
            self.assertEqual([item["content"] for item in reloaded.messages(project_b)], ["다른 질문", "다른 답변"])
            reloaded.clear(project_a)
            self.assertEqual(reloaded.messages(project_a), [])
            self.assertEqual(len(reloaded.messages(project_b)), 2)

    def test_agent_receives_previous_project_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as memory_directory:
            project = Path(directory)
            guard.open(str(project))
            store = ConversationStore(Path(memory_directory) / "conversations.json")

            class FakeOllamaClient:
                captured: list[list[dict]] = []

                async def model_capabilities(self, model: str) -> list[str]:
                    return ["tools"]

                async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                    self.captured.append(messages)
                    return {"role": "assistant", "content": "기억했습니다."}

            try:
                with patch("agent.agent_loop.conversations", store), patch("agent.agent_loop.OllamaClient", FakeOllamaClient):
                    asyncio.run(run_agent("내가 좋아하는 색은 파란색이야", "test"))
                    asyncio.run(run_agent("내가 좋아하는 색을 기억해?", "test"))
                second_messages = FakeOllamaClient.captured[1]
                self.assertIn({"role": "user", "content": "내가 좋아하는 색은 파란색이야"}, second_messages)
                self.assertIn({"role": "assistant", "content": "기억했습니다."}, second_messages)
            finally:
                guard.root = None


if __name__ == "__main__":
    unittest.main()
