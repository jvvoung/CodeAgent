import asyncio
import os
import unittest
from unittest.mock import patch

from llm.ollama_client import (
    OllamaClient,
    _apply_repair_operations,
    _compact_prior_patches,
    _coalesce_insert_operations,
    _duplicate_definition_error,
    _operations_change_evidence,
    _operations_are_valid_for_evidence,
    _operation_validation_error,
    _payload_from_message_content,
    _repair_excerpt,
    _structural_boundary_hints,
    _validation_repair_targets,
    normalize_tool_arguments,
    recover_json_string_field,
)


class OllamaClientTest(unittest.TestCase):
    def test_uses_larger_configurable_agent_context(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_NUM_CTX", None)
            self.assertEqual(OllamaClient().num_ctx, 8_192)

        with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "16384"}):
            self.assertEqual(OllamaClient().num_ctx, 16_384)

    def test_invalid_context_falls_back_safely(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_NUM_CTX": "invalid"}):
            self.assertEqual(OllamaClient().num_ctx, 8_192)

    def test_normalizes_nested_ollama_tool_arguments(self) -> None:
        payload = normalize_tool_arguments({
            "name": "submit_patch",
            "arguments": {"files": [{"path": "src/main.cpp", "operations": []}]},
        })
        self.assertEqual(payload["files"][0]["path"], "src/main.cpp")

    def test_recovers_complete_content_from_truncated_tool_json(self) -> None:
        truncated = '{"name":"submit_file_patch","arguments":{"operations":[{"content":"line 1\\nline 2"}]}'
        self.assertEqual(recover_json_string_field(truncated, "content"), "line 1\nline 2")

    def test_extracts_operations_json_from_model_text(self) -> None:
        payload = _payload_from_message_content(
            '```json\n{"operations":[{"op":"delete_lines","start_line":4,"end_line":4,"content":""}]}\n```'
        )
        self.assertEqual(payload["operations"][0]["op"], "delete_lines")

    def test_compacts_prior_patch_code_for_small_model_context(self) -> None:
        compact = _compact_prior_patches([{
            "path": "src/large.cpp",
            "operations": [{
                "op": "replace_lines",
                "start_line": 1,
                "end_line": 1,
                "content": 'class CacheWorker { void RefreshCacheState(); }',
            }],
        }])
        self.assertIn("CacheWorker", compact[0]["introduced_identifiers"])
        self.assertIn("RefreshCacheState", compact[0]["introduced_identifiers"])
        self.assertNotIn("class CacheWorker", str(compact))
        self.assertNotIn("start_line", str(compact))

    def test_detects_noop_and_effective_line_operations(self) -> None:
        target = {"start_line": 20, "content": "alpha\nbeta\ngamma"}
        self.assertFalse(_operations_change_evidence(target, [{
            "op": "replace_lines", "start_line": 21, "end_line": 21, "content": "beta"
        }]))
        self.assertTrue(_operations_change_evidence(target, [{
            "op": "replace_lines", "start_line": 21, "end_line": 21, "content": "changed"
        }]))

    def test_rejects_overlapping_operations_before_full_proposal(self) -> None:
        target = {"start_line": 20, "content": "alpha\nbeta\ngamma"}
        self.assertFalse(_operations_are_valid_for_evidence(target, [
            {"op": "insert_after_line", "start_line": 21, "end_line": 21, "content": "one"},
            {"op": "insert_after_line", "start_line": 21, "end_line": 21, "content": "two"},
        ]))
        self.assertTrue(_operations_are_valid_for_evidence(target, [
            {"op": "replace_lines", "start_line": 20, "end_line": 20, "content": "one"},
            {"op": "replace_lines", "start_line": 22, "end_line": 22, "content": "two"},
        ]))
        self.assertIn("겹칩니다", _operation_validation_error(target, [
            {"op": "insert_after_line", "start_line": 21, "end_line": 21, "content": "one"},
            {"op": "insert_before_line", "start_line": 21, "end_line": 21, "content": "two"},
        ]))

    def test_coalesces_before_and_after_insertions_at_same_anchor(self) -> None:
        merged = _coalesce_insert_operations("alpha\nbeta\ngamma\n", [
            {"op": "insert_before_line", "start_line": 2, "end_line": 2, "content": "before"},
            {"op": "insert_after_line", "start_line": 2, "end_line": 2, "content": "after"},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["op"], "replace_lines")
        self.assertEqual(merged[0]["content"], "before\nbeta\nafter")

    def test_applies_local_repair_without_rewriting_large_file(self) -> None:
        source = "".join(f"line {index}\n" for index in range(1, 401))
        repaired = _apply_repair_operations(source, [{
            "op": "replace_lines",
            "start_line": 250,
            "end_line": 250,
            "content": "fixed line",
        }])
        self.assertIn("line 249\nfixed line\nline 251", repaired)
        self.assertTrue(repaired.startswith("line 1\n"))
        self.assertTrue(repaired.endswith("line 400\n"))

    def test_repair_excerpt_focuses_on_changes_in_large_file(self) -> None:
        original = "".join(f"line {index}\n" for index in range(1, 401))
        current = original.replace("line 250\n", "broken line\n")
        excerpt = _repair_excerpt(original, current, "src/main.cpp:250: error", "src/main.cpp")
        self.assertIn("250: broken line", excerpt)
        self.assertNotIn("1: line 1", excerpt)
        self.assertLess(len(excerpt.splitlines()), 100)

    def test_finds_outer_structural_boundaries_for_member_insertion(self) -> None:
        target = {
            "start_line": 10,
            "content": "namespace Demo\n{\n    class Service\n    {\n        void Save()\n        {\n        }\n    }\n}\n",
        }
        hints = _structural_boundary_hints(target)
        self.assertIn("line 18 (indent 0): }", hints)
        self.assertIn("line 17 (indent 4): }", hints)

    def test_repairs_only_files_named_by_validation_diagnostics(self) -> None:
        files = [{"path": "ui/MainWindow.xaml"}, {"path": "src/main.cpp"}]
        targets = _validation_repair_targets(files, "ui/MainWindow.xaml(170,4): error")
        self.assertEqual(targets, {"ui/MainWindow.xaml"})

    def test_rejects_duplicate_definitions_named_by_compiler_diagnostics(self) -> None:
        original_markup = '<Button x:Name="SaveButton" />\n'
        candidate_markup = original_markup + '<Button x:Name="DeleteButton" />\n<Button x:Name="DeleteButton" />\n'
        markup_error = _duplicate_definition_error(
            original_markup,
            candidate_markup,
            "ui/View.xaml(20,2): error CS0102: type already contains a definition for 'DeleteButton'",
            "ui/View.xaml",
        )
        self.assertIn("DeleteButton", markup_error)

        original_code = "class View { }\n"
        candidate_code = "class View {\n void Delete_Click() {}\n void Delete_Click() {}\n}\n"
        method_error = _duplicate_definition_error(
            original_code,
            candidate_code,
            "ui/View.cs(3,2): error CS0111: type already defines member 'Delete_Click'",
            "ui/View.cs",
        )
        self.assertIn("Delete_Click", method_error)

    def test_validation_regeneration_uses_clean_original_not_rejected_candidate(self) -> None:
        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"message": {"tool_calls": [{"function": {"arguments": {"operations": [{
                    "op": "replace_lines", "start_line": 1, "end_line": 1, "content": "updated"
                }]}}}]}}

        class FakeHttpClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                return None

            async def post(self, url: str, json: dict):
                captured.update(json)
                return FakeResponse()

        with patch("llm.ollama_client.httpx.AsyncClient", FakeHttpClient):
            result = asyncio.run(OllamaClient().repair_from_validation(
                "test-model",
                "첫 줄을 변경해줘",
                {"acceptance_criteria": ["첫 줄 변경"]},
                [{"path": "src/example.txt", "original": "alpha\nstable\n", "modified": "alpha\nBROKEN\n"}],
                "src/example.txt:2: syntax error",
            ))

        self.assertEqual(result["files"][0]["changes"][0]["new"], "updated\nstable\n")
        prompt_payload = captured["messages"][1]["content"]
        self.assertIn("clean_original_with_line_numbers", prompt_payload)
        self.assertIn("clean_original_header_with_line_numbers", prompt_payload)
        self.assertNotIn("BROKEN", prompt_payload)


if __name__ == "__main__":
    unittest.main()
