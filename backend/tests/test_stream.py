import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class AgentStreamTest(unittest.TestCase):
    def test_stream_emits_progress_and_result(self) -> None:
        async def fake_agent(message: str, model: str, on_event=None):
            if on_event:
                await on_event({"tool": "search_code", "status": "completed"})
                await on_event({"tool": "read_file", "status": "failed", "detail": "파일을 찾을 수 없습니다"})
            return {
                "message": "변경안을 준비했습니다.",
                "events": [],
                "relevant_files": ["MainWindow.xaml"],
            }

        with patch("main.run_agent", new=fake_agent):
            response = TestClient(app).post(
                "/api/agent/chat/stream",
                json={"message": "버튼 문구를 바꿔줘", "model": "test-model"},
            )

        self.assertEqual(response.status_code, 200)
        payloads = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(payloads[0]["type"], "started")
        self.assertEqual([item["event"]["tool"] for item in payloads if item["type"] == "status"], ["search_code", "read_file"])
        self.assertEqual([item["event"].get("detail") for item in payloads if item["type"] == "status"][-1], "파일을 찾을 수 없습니다")
        self.assertEqual(payloads[-1]["type"], "complete")
        self.assertEqual(payloads[-1]["result"]["relevant_files"], ["MainWindow.xaml"])


if __name__ == "__main__":
    unittest.main()
