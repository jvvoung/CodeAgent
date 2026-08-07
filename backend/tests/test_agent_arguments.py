import unittest

from agent.agent_loop import _proposal_files


class AgentArgumentsTest(unittest.TestCase):
    def test_accepts_standard_files_array(self) -> None:
        files = _proposal_files({
            "files": [{"path": "MainWindow.xaml", "changes": [{"old": "변화", "new": "CHANGE"}]}]
        })
        self.assertEqual(files[0].path, "MainWindow.xaml")
        self.assertEqual(files[0].changes[0].new, "CHANGE")

    def test_accepts_single_file_shape(self) -> None:
        files = _proposal_files({
            "path": "MainWindow.xaml",
            "changes": {"old": "변화", "new": "CHANGE"},
        })
        self.assertEqual(files[0].path, "MainWindow.xaml")
        self.assertEqual(files[0].changes[0].old, "변화")

    def test_accepts_flat_single_change_shape(self) -> None:
        files = _proposal_files({"path": "MainWindow.xaml", "old": "변화", "new": "CHANGE"})
        self.assertEqual(files[0].changes[0].new, "CHANGE")

    def test_missing_file_has_korean_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "변경할 파일 정보가 없습니다"):
            _proposal_files({"changes": [{"old": "변화", "new": "CHANGE"}]})


if __name__ == "__main__":
    unittest.main()
