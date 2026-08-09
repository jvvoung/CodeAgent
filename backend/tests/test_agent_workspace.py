import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.tool_agent import (
    _comment_only_change, _embedded_call, _grounding_fallback_call,
    _request_allows_comment_changes, _request_needs_conversation_context,
    _request_prefers_patch, _request_term_evidence, _scope_review_tools, _scoped_preview,
    _strip_comment_edits, run_change_agent,
)
from agent.workspace import AgentWorkspace, PatchError
from security.path_guard import guard
from services.proposal_validator import classify_validation
from tools.patch_tools import apply, clear, pending


class AgentWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
        (self.root / "README.md").write_text("before\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_replace_text_is_exact_and_does_not_touch_source(self) -> None:
        with AgentWorkspace(self.root) as workspace:
            result = workspace.replace_text("src/app.py", "30", "60", 1)
            preview = workspace.preview()

        self.assertEqual(result["replacements"], 1)
        self.assertEqual(preview[0]["modified"], "TIMEOUT = 60\n")
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "TIMEOUT = 30\n")

    def test_replace_text_rejects_wrong_expected_count(self) -> None:
        with AgentWorkspace(self.root) as workspace:
            with self.assertRaisesRegex(ValueError, "일치 위치: 1: TIMEOUT = 30"):
                workspace.replace_text("src/app.py", "TIMEOUT", "LIMIT", 2)
            self.assertFalse(workspace.preview())

    def test_unified_patch_modifies_and_creates_files(self) -> None:
        patch_text = """--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,1 @@
-TIMEOUT = 30
+TIMEOUT = 60
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,1 @@
+ENABLED = True
"""
        with AgentWorkspace(self.root) as workspace:
            result = workspace.apply_patch(patch_text)
            preview = {item["path"]: item for item in workspace.preview()}

        self.assertEqual(result["paths"], ["src/app.py", "src/new.py"])
        self.assertEqual(preview["src/app.py"]["change_type"], "modified")
        self.assertEqual(preview["src/new.py"]["change_type"], "added")
        self.assertFalse((self.root / "src" / "new.py").exists())

    def test_codex_patch_modifies_and_creates_files(self) -> None:
        patch_text = """*** Begin Patch
*** Update File: src/app.py
@@
-TIMEOUT = 30
+TIMEOUT = 60
*** Add File: src/new.py
+ENABLED = True
*** End Patch"""
        with AgentWorkspace(self.root) as workspace:
            targets = workspace.patch_targets(patch_text)
            result = workspace.apply_patch(patch_text)
            preview = {item["path"]: item for item in workspace.preview()}

        self.assertEqual(targets, [
            {"path": "src/app.py", "creating": False},
            {"path": "src/new.py", "creating": True},
        ])
        self.assertEqual(result["paths"], ["src/app.py", "src/new.py"])
        self.assertEqual(preview["src/app.py"]["modified"], "TIMEOUT = 60\n")
        self.assertEqual(preview["src/new.py"]["modified"], "ENABLED = True\n")

    def test_headerless_patch_infers_one_target_from_context(self) -> None:
        patch_text = """@@
-TIMEOUT = 30
+TIMEOUT = 60
"""
        with AgentWorkspace(self.root) as workspace:
            target = workspace.infer_patch_target(patch_text)
            result = workspace.apply_patch(patch_text, default_path=target)
            preview = workspace.preview()

        self.assertEqual(target, "src/app.py")
        self.assertEqual(result["paths"], ["src/app.py"])
        self.assertEqual(preview[0]["modified"], "TIMEOUT = 60\n")

    def test_patch_rejects_unmatched_context(self) -> None:
        with AgentWorkspace(self.root) as workspace:
            with self.assertRaises(PatchError):
                workspace.apply_patch("""--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,1 @@
-MISSING
+CHANGED
""")

    def test_recovers_tool_json_printed_by_small_model(self) -> None:
        calls = _embedded_call('```json\n{"name":"read_file","arguments":{"path":"src/app.py"}}\n```')
        self.assertEqual(calls[0]["function"]["name"], "read_file")

    def test_recovers_tool_json_surrounded_by_explanatory_text(self) -> None:
        calls = _embedded_call(
            '파일을 읽겠습니다. <tool_call>{"name":"read_file","arguments":{"path":"src/app.py"}}</tool_call>'
        )
        self.assertEqual(calls[0]["function"]["name"], "read_file")

    def test_grounding_fallback_reads_ranked_source_evidence(self) -> None:
        evidence = {
            "alpha": [{"path": "src/a.py", "line": 10, "text": "alpha = 1"}],
            "beta": [
                {"path": "src/a.py", "line": 30, "text": "beta = 2"},
                {"path": "src/b.py", "line": 5, "text": "beta = 3"},
            ],
            "request": [
                {"path": "GUIDE.md", "line": 20, "text": "request setup"},
                {"path": "GUIDE.md", "line": 30, "text": "request usage"},
                {"path": "GUIDE.md", "line": 40, "text": "request notes"},
            ],
        }

        first_read = _grounding_fallback_call(evidence, 1)
        second_read = _grounding_fallback_call(evidence, 2)

        self.assertEqual(first_read["function"]["name"], "read_file_range")
        self.assertEqual(first_read["function"]["arguments"]["path"], "src/a.py")
        self.assertEqual(second_read["function"]["arguments"]["path"], "src/b.py")

        documentation_read = _grounding_fallback_call(evidence, 1, "GUIDE 문서를 수정해줘")
        self.assertEqual(documentation_read["function"]["arguments"]["path"], "GUIDE.md")

    def test_request_term_evidence_only_reports_exact_repository_terms(self) -> None:
        with AgentWorkspace(self.root) as workspace:
            evidence = _request_term_evidence(workspace, "TIMEOUT 값을 LIMIT으로 변경")

        self.assertIn("TIMEOUT", evidence)
        self.assertEqual(evidence["TIMEOUT"][0]["path"], "src/app.py")
        self.assertNotIn("LIMIT", evidence)

    def test_only_referential_followups_receive_conversation_context(self) -> None:
        self.assertFalse(_request_needs_conversation_context("새 저장 기능을 추가해줘"))
        self.assertTrue(_request_needs_conversation_context("방금 변경한 그 파일에 테스트도 추가해줘"))

    def test_structural_requests_prefer_patch_over_literal_replace(self) -> None:
        self.assertTrue(_request_prefers_patch("새 저장 기능을 추가해줘"))
        self.assertTrue(_request_prefers_patch("create a new method for cleanup"))
        self.assertFalse(_request_prefers_patch("TIMEOUT 값을 30에서 60으로 변경해줘"))

    def test_scope_review_tools_constrain_revert_path(self) -> None:
        tools = _scope_review_tools(["src/app.py", "README.md"])
        names = {item["function"]["name"] for item in tools}
        revert = next(item for item in tools if item["function"]["name"] == "revert_file")

        self.assertNotIn("replace_text", names)
        self.assertNotIn("search_code", names)
        self.assertEqual(
            revert["function"]["parameters"]["properties"]["path"]["enum"],
            ["src/app.py", "README.md"],
        )

    def test_comment_only_file_is_excluded_unless_requested(self) -> None:
        comment_change = {
            "path": "src/View.xaml",
            "original": "<!-- old note -->\n<Button Content=\"Save\" />\n",
            "modified": "<!-- new note -->\n<Button Content=\"Save\" />\n",
        }
        code_change = {
            "path": "src/app.py",
            "original": "TIMEOUT = 30\n",
            "modified": "TIMEOUT = 60\n",
        }

        self.assertTrue(_comment_only_change(comment_change))
        self.assertFalse(_comment_only_change(code_change))
        scoped, excluded = _scoped_preview([comment_change, code_change], "설정값을 변경해줘")
        self.assertEqual([item["path"] for item in scoped], ["src/app.py"])
        self.assertEqual(excluded, ["src/View.xaml"])
        self.assertTrue(_request_allows_comment_changes("주석 문구를 변경해줘"))
        scoped_with_comment, excluded_with_comment = _scoped_preview(
            [comment_change, code_change], "주석 문구를 변경해줘"
        )
        self.assertEqual(len(scoped_with_comment), 2)
        self.assertFalse(excluded_with_comment)

    def test_comment_edits_are_removed_from_a_mixed_source_change(self) -> None:
        mixed_change = {
            "path": "src/service.py",
            "original": "# keep this explanation\nTIMEOUT = 30\n",
            "modified": "# rewritten explanation\nTIMEOUT = 60\n",
            "additions": 2,
            "deletions": 2,
        }

        filtered = _strip_comment_edits(mixed_change)

        self.assertEqual(filtered["modified"], "# keep this explanation\nTIMEOUT = 60\n")
        self.assertEqual(filtered["additions"], 1)
        self.assertEqual(filtered["deletions"], 1)


class PersistentToolAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
        guard.open(str(self.root))
        self.project_map = {
            "absolute_root": self.root,
            "root": self.root.name,
            "languages": [{"name": "Python", "files": 1}],
            "build_systems": [],
            "manifests": [],
            "entry_points": [],
        }

    def tearDown(self) -> None:
        clear()
        guard.root = None
        self.temporary.cleanup()

    def test_one_conversation_searches_reads_edits_and_finishes(self) -> None:
        class FakeClient:
            calls = 0
            messages = []

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                self.__class__.messages.append(messages)
                sequence = [
                    {"name": "search_code", "arguments": {"query": "TIMEOUT"}},
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "30", "new": "60", "expected_count": 1}},
                    {"name": "finish_changes", "arguments": {"summary": "설정값을 변경했습니다."}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="TIMEOUT 값을 30에서 60으로 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=FakeClient(),
            ))

        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["validation_status"], "verified")
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "TIMEOUT = 30\n")
        tool_results = [item for batch in FakeClient.messages for item in batch if item.get("role") == "tool"]
        self.assertTrue(any(item.get("tool_name") == "read_file" for item in tool_results))

    def test_headerless_patch_uses_unique_search_evidence(self) -> None:
        class HeaderlessPatchClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                sequence = [
                    {"name": "search_code", "arguments": {"query": "TIMEOUT = 30"}},
                    {"name": "apply_patch", "arguments": {
                        "patch": "@@\n-TIMEOUT = 30\n+TIMEOUT = 60\n",
                    }},
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="설정값을 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=HeaderlessPatchClient(),
            ))

        self.assertEqual(HeaderlessPatchClient.calls, 3)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")

    def test_search_evidence_does_not_replace_before_explicit_read(self) -> None:
        class SearchThenReplaceClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                sequence = [
                    {"name": "search_code", "arguments": {"query": "TIMEOUT = 30"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "TIMEOUT = 30",
                        "new": "TIMEOUT = 60", "expected_count": 0,
                    }},
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "TIMEOUT = 30",
                        "new": "TIMEOUT = 60", "expected_count": 0,
                    }},
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="설정값을 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=SearchThenReplaceClient(),
            ))

        self.assertEqual(SearchThenReplaceClient.calls, 5)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")

    def test_reversed_replace_arguments_are_corrected_from_file_evidence(self) -> None:
        class ReversedArgumentsClient:
            calls = 0

            async def chat(self, model, messages, tools):
                sequence = [
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "60", "new": "30",
                        "expected_count": 1,
                    }},
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls]
                self.__class__.calls += 1
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="TIMEOUT 값을 30에서 60으로 변경해줘", model="fake",
                project_map=self.project_map, conversation_context=[],
                client=ReversedArgumentsClient(),
            ))

        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")

    def test_multifile_finish_requires_scope_review_and_can_revert_file(self) -> None:
        (self.root / "README.md").write_text("before\n", encoding="utf-8")

        class ReviewingClient:
            calls = 0
            saw_review = False

            async def chat(self, model, messages, tools):
                self.__class__.saw_review = self.__class__.saw_review or any(
                    "scope_review_required" in item.get("content", "")
                    for item in messages if item.get("role") == "tool"
                )
                sequence = [
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "30", "new": "60",
                    }},
                    {"name": "read_file", "arguments": {"path": "README.md"}},
                    {"name": "replace_text", "arguments": {
                        "path": "README.md", "old": "before", "new": "unrelated",
                    }},
                    {"name": "revert_file", "arguments": {"path": "README.md"}},
                    {"name": "finish_changes", "arguments": {"summary": "검토 완료"}},
                ]
                item = sequence[self.__class__.calls]
                self.__class__.calls += 1
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="설정값만 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=ReviewingClient(),
            ))

        self.assertEqual(ReviewingClient.calls, 6)
        self.assertTrue(ReviewingClient.saw_review)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(list(pending), ["src/app.py"])

    def test_comment_only_edit_is_reverted_before_a_real_edit(self) -> None:
        (self.root / "src" / "app.py").write_text(
            "# timeout documentation\nTIMEOUT = 30\n", encoding="utf-8"
        )

        class CommentThenCodeClient:
            calls = 0
            finish_was_hidden_after_comment_edit = False

            async def chat(self, model, messages, tools):
                self.__class__.finish_was_hidden_after_comment_edit = (
                    self.__class__.finish_was_hidden_after_comment_edit
                    or self.__class__.calls == 2 and all(
                        item["function"]["name"] != "finish_changes" for item in tools
                    )
                )
                sequence = [
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "# timeout documentation",
                        "new": "# rewritten documentation", "expected_count": 1,
                    }},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "TIMEOUT = 30",
                        "new": "TIMEOUT = 60", "expected_count": 1,
                    }},
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls]
                self.__class__.calls += 1
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="TIMEOUT 값을 60으로 변경해줘", model="fake",
                project_map=self.project_map, conversation_context=[],
                client=CommentThenCodeClient(),
            ))

        self.assertTrue(CommentThenCodeClient.finish_was_hidden_after_comment_edit)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(
            pending["src/app.py"]["modified"],
            "# timeout documentation\nTIMEOUT = 60\n",
        )

    def test_build_error_returns_to_same_model_then_retries(self) -> None:
        class RepairingClient:
            calls = 0
            saw_failure = False

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                self.__class__.saw_failure = self.__class__.saw_failure or any(
                    "compile error" in item.get("content", "") for item in messages if item.get("role") == "tool"
                )
                sequence = [
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "30", "new": "BROKEN"}},
                    {"name": "finish_changes", "arguments": {"summary": "첫 시도"}},
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "BROKEN", "new": "60"}},
                    {"name": "finish_changes", "arguments": {"summary": "오류를 수정했습니다."}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        baseline_ok = {"supported": True, "ok": True, "command": "check", "output": ""}
        proposed_bad = {"supported": True, "ok": False, "command": "check", "output": "compile error"}
        proposed_ok = {"supported": True, "ok": True, "command": "check", "output": ""}
        validations = AsyncMock(side_effect=[baseline_ok, proposed_bad, proposed_ok])
        with patch("agent.tool_agent.run_workspace_validation", validations):
            result = asyncio.run(run_change_agent(
                message="문구를 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=RepairingClient(),
            ))

        self.assertTrue(RepairingClient.saw_failure)
        self.assertEqual(pending["src/app.py"]["validation_status"], "verified")
        self.assertIn("검증을 통과", result["message"])

    def test_failed_final_diff_is_staged_and_can_be_confirmed(self) -> None:
        class FailingClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                sequence = [
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "30", "new": "BROKEN"}},
                    {"name": "finish_changes", "arguments": {"summary": "후보 변경"}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        baseline_ok = {"supported": True, "ok": True, "output": ""}
        proposed_bad = {"supported": True, "ok": False, "output": "compile error"}
        with patch.dict(os.environ, {"AURA_VALIDATION_REPAIR_ATTEMPTS": "0"}), patch(
            "agent.tool_agent.run_workspace_validation", AsyncMock(side_effect=[baseline_ok, proposed_bad])
        ):
            result = asyncio.run(run_change_agent(
                message="문구를 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=FailingClient(),
            ))

        self.assertIn("실패했지만 최종 Diff", result["message"])
        self.assertEqual(pending["src/app.py"]["validation_status"], "failed")
        with self.assertRaisesRegex(ValueError, "사용자 확인"):
            apply(["src/app.py"])
        apply(["src/app.py"], confirm_unverified=True)
        self.assertIn("BROKEN", (self.root / "src" / "app.py").read_text(encoding="utf-8"))

    def test_repeated_identical_failed_edit_stops_without_looping(self) -> None:
        class RepeatingFailureClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                sequence = [
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "missing", "new": "60"}},
                    {"name": "replace_text", "arguments": {"path": "src/app.py", "old": "missing", "new": "60"}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        result = asyncio.run(run_change_agent(
            message="설정값을 변경해줘", model="fake", project_map=self.project_map,
            conversation_context=[], client=RepeatingFailureClient(),
        ))

        self.assertEqual(RepeatingFailureClient.calls, 2)
        self.assertIn("동일한 실패 도구 호출", result["message"])
        self.assertFalse(pending)

    def test_reading_file_allows_retry_and_normalizes_invalid_count(self) -> None:
        class RetryAfterReadClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                edit = {
                    "name": "replace_text",
                    "arguments": {
                        "path": "src/app.py", "old": "30", "new": "60", "expected_count": 0,
                    },
                }
                sequence = [
                    edit,
                    {"name": "read_file", "arguments": {"path": "src/app.py"}},
                    edit,
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls - 1]
                return {"role": "assistant", "content": "", "tool_calls": [{"function": item}]}

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="설정값을 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=RetryAfterReadClient(),
            ))

        self.assertEqual(RetryAfterReadClient.calls, 4)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")

    def test_repeated_successful_search_stops_without_looping(self) -> None:
        class RepeatingSearchClient:
            calls = 0

            async def chat(self, model, messages, tools):
                self.__class__.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {
                        "name": "search_code", "arguments": {"query": "TIMEOUT"},
                    }}],
                }

        result = asyncio.run(run_change_agent(
            message="설정값을 변경해줘", model="fake", project_map=self.project_map,
            conversation_context=[], client=RepeatingSearchClient(),
        ))

        self.assertEqual(RepeatingSearchClient.calls, 3)
        self.assertIn("동일한 조회 도구 호출", result["message"])
        self.assertFalse(pending)

    def test_three_searches_are_redirected_to_read_before_edit(self) -> None:
        class SearchOnlyClient:
            calls = 0

            async def chat(self, model, messages, tools):
                sequence = [
                    {"name": "search_code", "arguments": {"query": "TIMEOUT"}},
                    {"name": "search_code", "arguments": {"query": "LIMIT"}},
                    {"name": "search_code", "arguments": {"query": "CONFIG"}},
                    {"name": "replace_text", "arguments": {
                        "path": "src/app.py", "old": "30", "new": "60",
                    }},
                    {"name": "finish_changes", "arguments": {"summary": "설정값 변경"}},
                ]
                item = sequence[self.__class__.calls]
                self.__class__.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": item}],
                }

        successful = {"supported": True, "ok": True, "command": "check", "output": ""}
        with patch("agent.tool_agent.run_workspace_validation", AsyncMock(return_value=successful)):
            result = asyncio.run(run_change_agent(
                message="TIMEOUT 설정값을 변경해줘", model="fake", project_map=self.project_map,
                conversation_context=[], client=SearchOnlyClient(),
            ))

        self.assertEqual(SearchOnlyClient.calls, 5)
        self.assertIn("검증을 통과", result["message"])
        self.assertEqual(pending["src/app.py"]["modified"], "TIMEOUT = 60\n")

    def test_validation_classifies_existing_failure_separately(self) -> None:
        baseline = {"supported": True, "ok": False, "output": "same error"}
        proposed = {"supported": True, "ok": False, "output": "same error"}
        self.assertEqual(classify_validation(baseline, proposed)["status"], "baseline_failed")


if __name__ == "__main__":
    unittest.main()
