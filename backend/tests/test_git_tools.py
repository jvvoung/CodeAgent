import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from security.path_guard import guard
from tests import auth_headers
from tools.git_tools import branches, checkout, commit, diff, repository_info, stage_all, staged_changes, status, unstage_all


class GitToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "CodeAgent Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("# Test\n", encoding="utf-8")
        guard.open(str(self.root))
        self.client = TestClient(app)
        self.headers = auth_headers(self.client)

    def tearDown(self) -> None:
        guard.root = None
        guard.git_root = None
        self.temporary.cleanup()

    def test_nested_project_path_uses_parent_git_repository(self) -> None:
        nested = self.root / "src" / "feature"
        nested.mkdir(parents=True)
        response = self.client.post("/api/project/open", json={"path": str(nested)}, headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Path(response.json()["git_root"]), self.root.resolve())
        self.assertEqual(guard.root, nested.resolve())
        self.assertEqual(guard.git_root, self.root.resolve())
        self.assertEqual(asyncio.run(stage_all())["return_code"], 0)
        self.assertEqual(asyncio.run(commit("Initial nested project"))["return_code"], 0)
        info = asyncio.run(repository_info())
        self.assertEqual(Path(info["root"]), self.root.resolve())
        self.assertEqual(info["branch"], "main")

    def test_project_without_parent_git_repository_reports_none(self) -> None:
        isolated = self.root.parent / f"{self.root.name}-isolated"
        isolated.mkdir()
        try:
            guard.open(str(isolated))
            self.assertIsNone(guard.git_root)
            with self.assertRaisesRegex(ValueError, "Git 저장소를 찾지 못했습니다"):
                asyncio.run(status())
        finally:
            isolated.rmdir()

    def test_stage_commit_diff_and_unstage(self) -> None:
        self.assertEqual(asyncio.run(stage_all())["return_code"], 0)
        self.assertEqual(asyncio.run(commit("Initial test"))["return_code"], 0)
        (self.root / "README.md").write_text("# Test\nChanged\n", encoding="utf-8")
        info = asyncio.run(repository_info())
        self.assertTrue(info["has_unstaged"])
        self.assertFalse(info["has_staged"])

        asyncio.run(stage_all())
        info = asyncio.run(repository_info())
        self.assertTrue(info["has_staged"])
        self.assertIn("Changed", asyncio.run(diff(staged=True))["stdout"])

        self.assertEqual(asyncio.run(unstage_all())["return_code"], 0)
        self.assertFalse(asyncio.run(repository_info())["has_staged"])
        self.assertIn("README.md", asyncio.run(status())["stdout"])

    def test_push_requires_explicit_confirmation(self) -> None:
        response = self.client.post("/api/git/push", json={"confirmed": False}, headers=self.headers)
        self.assertEqual(response.status_code, 422)

        async def fake_push():
            return {"command": "git push", "return_code": 0, "stdout": "ok", "stderr": "", "duration": 0.1}

        with patch("main.git_push_command", new=fake_push):
            response = self.client.post("/api/git/push", json={"confirmed": True}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["return_code"], 0)

    def test_lists_and_checks_out_branches(self) -> None:
        asyncio.run(stage_all())
        asyncio.run(commit("Initial test"))
        subprocess.run(["git", "switch", "-c", "feature/ui"], cwd=self.root, check=True, capture_output=True)
        (self.root / "feature.txt").write_text("feature\n", encoding="utf-8")
        asyncio.run(stage_all())
        asyncio.run(commit("Feature branch"))
        subprocess.run(["git", "switch", "main"], cwd=self.root, check=True, capture_output=True)

        info = asyncio.run(branches())
        self.assertEqual(info["current"], "main")
        self.assertEqual(info["branches"], ["feature/ui", "main"])

        result = asyncio.run(checkout("feature/ui"))
        self.assertEqual(result["return_code"], 0)
        self.assertEqual(asyncio.run(repository_info())["branch"], "feature/ui")
        self.assertTrue((self.root / "feature.txt").exists())

    def test_returns_structured_staged_changes(self) -> None:
        asyncio.run(stage_all())
        asyncio.run(commit("Initial test"))
        (self.root / "README.md").write_text("# Test\nChanged\n", encoding="utf-8")
        (self.root / "new-file.txt").write_text("new\n", encoding="utf-8")
        asyncio.run(stage_all())

        files = asyncio.run(staged_changes())["files"]
        by_path = {item["path"]: item for item in files}
        self.assertEqual(by_path["README.md"]["status"], "modified")
        self.assertEqual(by_path["README.md"]["original"], "# Test\n")
        self.assertEqual(by_path["README.md"]["modified"], "# Test\nChanged\n")
        self.assertEqual(by_path["new-file.txt"]["status"], "added")
        self.assertEqual(by_path["new-file.txt"]["original"], "")
        self.assertEqual(by_path["new-file.txt"]["additions"], 1)


if __name__ == "__main__":
    unittest.main()
