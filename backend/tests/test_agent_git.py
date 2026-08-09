import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.agent_loop import _direct_git_intent, run_agent
from security.path_guard import guard
from services.conversation_store import ConversationStore


class AgentGitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.memory_temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.memory_patch = patch(
            "agent.agent_loop.conversations",
            ConversationStore(Path(self.memory_temporary.name) / "conversations.json"),
        )
        self.memory_patch.start()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "AURA Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "aura@example.com"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("# AURA\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=self.root, check=True, capture_output=True)
        guard.open(str(self.root))

    def tearDown(self) -> None:
        guard.root = None
        self.memory_patch.stop()
        self.temporary.cleanup()
        self.memory_temporary.cleanup()

    def test_commit_request_bypasses_model_and_commits_current_changes(self) -> None:
        (self.root / "README.md").write_text("# AURA\nChanged\n", encoding="utf-8")
        events = []

        async def on_event(event):
            events.append(event)

        response = asyncio.run(run_agent(
            '현재코드를 깃에 커밋해줘. 제목은 "변환으로 변경"',
            "model-is-not-needed",
            on_event,
        ))

        subject = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], cwd=self.root, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout.strip()
        self.assertEqual(subject, "변환으로 변경")
        self.assertEqual([event["tool"] for event in events], ["git_status", "git_stage_all", "git_commit"])
        self.assertTrue(response["git_changed"])
        self.assertNotIn("src/main/java", response["message"])

    def test_next_short_reply_is_used_as_pending_commit_message(self) -> None:
        (self.root / "README.md").write_text("# AURA\nPending title\n", encoding="utf-8")
        first = asyncio.run(run_agent("현재코드를 커밋해줘.", "model-is-not-needed"))
        self.assertIn("커밋 메시지가 필요", first["message"])

        second = asyncio.run(run_agent('"테스트 커밋 제목"', "model-is-not-needed"))
        subject = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], cwd=self.root, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout.strip()
        self.assertEqual(subject, "테스트 커밋 제목")
        self.assertTrue(second["git_changed"])

    def test_push_request_requires_frontend_confirmation(self) -> None:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/aura.git"],
            cwd=self.root,
            check=True,
        )
        response = asyncio.run(run_agent("현재코드를 깃에 푸쉬해줘", "model-is-not-needed"))
        self.assertEqual(response["pending_git_action"]["type"], "push")
        self.assertEqual(response["pending_git_action"]["branch"], "main")
        self.assertEqual(response["pending_git_action"]["remote"], "https://github.com/example/aura.git")

    def test_branch_checkout_request(self) -> None:
        subprocess.run(["git", "branch", "feature/agent"], cwd=self.root, check=True)
        response = asyncio.run(run_agent("feature/agent 브랜치로 전환해줘", "model-is-not-needed"))
        current = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(current, "feature/agent")
        self.assertTrue(response["project_changed"])

    def test_recognizes_git_intents(self) -> None:
        self.assertEqual(_direct_git_intent("깃 상태를 보여줘"), ("status", ""))
        self.assertEqual(_direct_git_intent("스테이징 Diff 보여줘"), ("diff_staged", ""))
        self.assertEqual(_direct_git_intent("Push 해줘"), ("push", ""))
        self.assertEqual(_direct_git_intent("현재코드를 깃에 푸쉬해줘"), ("push", ""))


if __name__ == "__main__":
    unittest.main()
