import unittest
from unittest.mock import patch

from agent.agent_loop import (
    _embedded_tool_calls,
    _line_operation_change,
    _line_operations_change,
    _proposal_files,
)


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

    def test_accepts_compact_insert_and_replace_operations(self) -> None:
        files = _proposal_files({
            "files": [{
                "path": "MainWindow.xaml",
                "operations": [
                    {"op": "insert_after", "anchor": "<Button />", "content": "\n<Button Content=\"삭제\" />"},
                    {"op": "replace", "anchor": "Content=\"저장\"", "content": "Content=\"SAVE\""},
                ],
            }]
        })
        self.assertEqual(files[0].changes[0].old, "<Button />")
        self.assertEqual(files[0].changes[0].new, "<Button />\n<Button Content=\"삭제\" />")
        self.assertEqual(files[0].changes[1].new, "Content=\"SAVE\"")

    def test_accepts_nested_ollama_tool_arguments(self) -> None:
        files = _proposal_files({
            "name": "submit_patch",
            "arguments": {
                "files": [{
                    "path": "MainWindow.xaml",
                    "operations": [{"op": "delete", "anchor": "<Button />", "content": ""}],
                }]
            },
        })
        self.assertEqual(files[0].path, "MainWindow.xaml")
        self.assertEqual(files[0].changes[0].old, "<Button />")
        self.assertEqual(files[0].changes[0].new, "")

    def test_accepts_line_based_insert_operation(self) -> None:
        with patch("agent.agent_loop.read_file", return_value="<Button />"):
            files = _proposal_files({
                "files": [{
                    "path": "MainWindow.xaml",
                    "operations": [{
                        "op": "insert_after_line",
                        "start_line": 1,
                        "end_line": 1,
                        "content": "<Button Content=\"삭제\" />\n",
                    }],
                }]
            })
        self.assertEqual(files[0].changes[0].old, "<Button />")
        self.assertEqual(files[0].changes[0].new, "<Button />\n<Button Content=\"삭제\" />\n")

    def test_line_insert_expands_repeated_blank_line_to_unique_context(self) -> None:
        lines = ["first\n", "\n", "middle\n", "\n", "last\n"]
        change = _line_operation_change(lines, 4, 4, "insert_after_line", "inserted")
        self.assertEqual(change["old"], "middle\n\n")
        self.assertEqual(change["new"], "middle\n\ninserted\n")

    def test_applies_multiple_line_operations_against_original_coordinates(self) -> None:
        source = "one\ntwo\nthree\nfour\n"
        change = _line_operations_change(source, [
            {"op": "replace_lines", "start_line": 2, "end_line": 2, "content": "TWO"},
            {"op": "insert_before_line", "start_line": 4, "end_line": 4, "content": "three-and-half"},
        ])
        self.assertEqual(change["old"], source)
        self.assertEqual(change["new"], "one\nTWO\nthree\nthree-and-half\nfour\n")

    def test_rejects_overlapping_line_operations(self) -> None:
        with self.assertRaisesRegex(ValueError, "줄 범위가 겹칩니다"):
            _line_operations_change("one\ntwo\nthree\n", [
                {"op": "replace_lines", "start_line": 1, "end_line": 2, "content": "first"},
                {"op": "replace_lines", "start_line": 2, "end_line": 3, "content": "second"},
            ])

    def test_missing_file_has_korean_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "변경할 파일 정보가 없습니다"):
            _proposal_files({"changes": [{"old": "변화", "new": "CHANGE"}]})

    def test_recovers_tool_call_printed_as_json_code_block(self) -> None:
        content = '파일을 확인하겠습니다.\n```json\n{"name":"read_file","arguments":{"path":"src/main.cpp"}}\n```'

        calls = _embedded_tool_calls(content, {"read_file", "search_code"})

        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(calls[0]["function"]["arguments"]["path"], "src/main.cpp")

    def test_does_not_execute_unavailable_embedded_tool(self) -> None:
        content = '```json\n{"name":"git_push","arguments":{}}\n```'
        self.assertEqual(_embedded_tool_calls(content, {"read_file"}), [])


if __name__ == "__main__":
    unittest.main()
