import unittest

from agent.agent_loop import _korean_response, _requests_change


class AgentLanguageTest(unittest.TestCase):
    def test_keeps_korean_response(self) -> None:
        text = "변경 제안을 준비했습니다. 오른쪽 패널에서 확인해 주세요."
        self.assertEqual(_korean_response(text), text)

    def test_blocks_chinese_response(self) -> None:
        chinese = "看來在提出更改時出現了問題。讓我直接再次正確地調用工具並提出修改建議。"
        self.assertNotIn("看來", _korean_response(chinese))
        self.assertIn("한국어가 아닌 응답", _korean_response(chinese))

    def test_uses_proposal_message_when_foreign_answer_follows_success(self) -> None:
        chinese = "已經成功建立修改提案，請在右側面板確認後繼續進行。"
        self.assertEqual(
            _korean_response(chinese, proposal_created=True),
            "변경 제안을 준비했습니다. 오른쪽 변경 제안 탭에서 확인해 주세요.",
        )

    def test_blocks_mixed_korean_and_chinese_response(self) -> None:
        mixed = "버튼 문구를 변경했습니다. <!-- 其余内容保持不变 -->"
        self.assertIn("한국어가 아닌 응답", _korean_response(mixed))

    def test_detects_change_request(self) -> None:
        self.assertTrue(_requests_change("변환 버튼의 문구를 CHANGE로 바꿔줘"))
        self.assertFalse(_requests_change("MainWindow.xaml의 역할을 설명해줘"))


if __name__ == "__main__":
    unittest.main()
