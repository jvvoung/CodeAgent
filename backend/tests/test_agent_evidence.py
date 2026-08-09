import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.agent_loop import _contains_tool_markup, _required_change_paths, _requires_repository_evidence, _requires_source_read, _ungrounded_identifiers, run_agent
from security.path_guard import guard
from services.conversation_store import ConversationStore
from tools.patch_tools import clear, pending


class AgentEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.memory_temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "CMakeLists.txt").write_text("add_executable(app src/config_writer.cpp)\n", encoding="utf-8")
        (self.root / "src" / "config_writer.cpp").write_text(
            '#include <fstream>\nvoid saveConfig() { std::ofstream out("settings.json"); }\n',
            encoding="utf-8",
        )
        guard.open(str(self.root))
        self.store = ConversationStore(Path(self.memory_temporary.name) / "conversations.json")

    def tearDown(self) -> None:
        clear()
        guard.root = None
        self.temporary.cleanup()
        self.memory_temporary.cleanup()

    def test_detects_general_repository_questions_without_ui_specific_rules(self) -> None:
        self.assertTrue(_requires_repository_evidence("설정 파일이 생성되는 경로가 어디야?"))
        self.assertTrue(_requires_repository_evidence("ConfigWriter::save는 어디서 호출돼?"))
        self.assertTrue(_requires_source_read("이 함수가 왜 실패하는지 원인을 알려줘"))
        self.assertFalse(_requires_repository_evidence("내가 좋아하는 색을 기억해?"))
        self.assertTrue(_contains_tool_markup('```json\n{"name":"read_file","arguments":{}}\n```'))
        evidence = {"files": [{"path": "MainWindow.xaml.cs", "content": "void BtnSave_Click() {}"}]}
        self.assertEqual(_ungrounded_identifiers("`BtnConvert_Click`가 호출됩니다.", {}, evidence), ["BtnConvert_Click"])

    def test_only_requires_files_explicitly_named_by_user(self) -> None:
        evidence = {"files": [
            {"path": "MainWindow.xaml.cs"},
            {"path": "MainWindow.xaml"},
            {"path": "Services/FileSaveService.cs"},
        ]}
        required = _required_change_paths("삭제 버튼을 추가하고 Output 파일을 삭제해줘", evidence)
        self.assertEqual(required, [])
        required = _required_change_paths("MainWindow.xaml과 FileSaveService.cs를 수정해줘", evidence)
        self.assertEqual(required, ["MainWindow.xaml", "Services/FileSaveService.cs"])

    def test_change_requests_route_to_persistent_workspace_agent(self) -> None:
        class ToolClient:
            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

        persistent_result = {
            "message": "지속형 작업공간에서 변경안을 만들었습니다.",
            "events": [],
            "relevant_files": ["src/config_writer.cpp"],
        }
        runner = AsyncMock(return_value=persistent_result)
        with patch("agent.agent_loop.conversations", self.store), patch(
            "agent.agent_loop.OllamaClient", ToolClient
        ), patch("agent.agent_loop.run_change_agent", runner):
            result = asyncio.run(run_agent("saveConfig 이름을 바꿔줘", "test-model"))

        self.assertEqual(result["message"], persistent_result["message"])
        self.assertEqual(runner.await_count, 1)
        self.assertEqual(runner.await_args.kwargs["project_map"]["absolute_root"], self.root)

    def test_automatic_evidence_uses_separate_final_answer_stage(self) -> None:
        class EvidenceAnsweringClient:
            chat_called = False

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def answer_from_evidence(self, model, question, project_map, evidence, history=None):
                self.assert_evidence = evidence
                return "설정은 settings.json에 저장됩니다. 근거 파일은 src/config_writer.cpp입니다."

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.chat_called = True
                raise AssertionError("근거가 확보된 정보 질문은 도구 루프로 되돌아가면 안 됩니다.")

        events = []

        async def on_event(event):
            events.append(event)

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", EvidenceAnsweringClient):
            result = asyncio.run(run_agent("saveConfig 함수가 저장하는 경로가 어디야?", "test-model", on_event))

        self.assertFalse(EvidenceAnsweringClient.chat_called)
        self.assertIn("settings.json", result["message"])
        self.assertEqual([event["tool"] for event in events], ["search_code", "read_file_range"])

    def test_grounded_answer_without_a_citation_gets_real_source_paths(self) -> None:
        class MissingCitationClient:
            chat_called = False

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def answer_from_evidence(self, model, question, project_map, evidence, history=None):
                return "설정은 실행 폴더의 settings.json에 저장됩니다."

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.chat_called = True
                raise AssertionError("인용만 누락된 답변은 일반 도구 루프로 보내면 안 됩니다.")

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", MissingCitationClient):
            result = asyncio.run(run_agent("saveConfig 함수가 저장하는 경로가 어디야?", "test-model"))

        self.assertFalse(MissingCitationClient.chat_called)
        self.assertIn("근거 파일:", result["message"])
        self.assertIn("src/config_writer.cpp", result["message"])

    @unittest.skip("파일별 생성기 대신 지속형 작업공간 도구 루프로 교체됨")
    def test_automatic_evidence_uses_structured_change_generation(self) -> None:
        class StructuredProposalClient:
            chat_called = False
            review_called = False

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def propose_from_evidence(self, model, request, project_map, evidence, history=None):
                return {
                    "acceptance_criteria": ["saveConfig is renamed to saveSettings"],
                    "file_plan": {"src/config_writer.cpp": "Rename the function"},
                    "files": [{
                        "path": "src/config_writer.cpp",
                        "changes": [{
                            "old": 'void saveConfig() { std::ofstream out("settings.json"); }',
                            "new": 'void saveSettings() { std::ofstream out("settings.json"); }',
                        }],
                    }]
                }

            async def review_proposal(self, model, request, project_map, evidence, proposal, previewed_files):
                self.__class__.review_called = True
                return {
                    "complete": True,
                    "missing_requirements": [],
                    "unsafe_or_inconsistent_changes": [],
                    "files_needing_changes": [],
                }

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.chat_called = True
                raise AssertionError("근거가 확보된 변경 요청은 일반 도구 루프로 보내면 안 됩니다.")

        events = []

        async def on_event(event):
            events.append(event)

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", StructuredProposalClient), patch(
            "agent.agent_loop.validate_proposal", AsyncMock(return_value={"supported": True, "ok": True})
        ):
            result = asyncio.run(run_agent("saveConfig 함수 이름을 saveSettings로 변경해줘", "test-model", on_event))

        self.assertFalse(StructuredProposalClient.chat_called)
        self.assertTrue(StructuredProposalClient.review_called)
        self.assertIn("변경안을 만들었습니다", result["message"])
        self.assertEqual([event["tool"] for event in events], ["search_code", "read_file_range", "validate_changes", "propose_changes"])

    @unittest.skip("별도 reviewer 호출이 지속형 동일 대화 검증 루프로 교체됨")
    def test_incomplete_review_restarts_planning_with_feedback(self) -> None:
        class ReviewingProposalClient:
            proposal_calls = 0
            review_calls = 0
            feedback_received = ""

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def propose_from_evidence(self, model, request, project_map, evidence, history=None, feedback=""):
                self.__class__.proposal_calls += 1
                self.__class__.feedback_received = feedback
                return {
                    "acceptance_criteria": ["The requested rename is complete at definitions and uses"],
                    "file_plan": {"src/config_writer.cpp": "Rename the definition and affected uses"},
                    "files": [{
                        "path": "src/config_writer.cpp",
                        "changes": [{
                            "old": 'void saveConfig() { std::ofstream out("settings.json"); }',
                            "new": 'void saveSettings() { std::ofstream out("settings.json"); }',
                        }],
                    }],
                }

            async def review_proposal(self, model, request, project_map, evidence, proposal, previewed_files):
                self.__class__.review_calls += 1
                if self.__class__.review_calls == 1:
                    return {
                        "complete": False,
                        "missing_requirements": ["호출부 이름도 함께 변경해야 합니다."],
                        "unsafe_or_inconsistent_changes": [],
                        "files_needing_changes": ["src/config_writer.cpp"],
                    }
                return {
                    "complete": True,
                    "missing_requirements": [],
                    "unsafe_or_inconsistent_changes": [],
                    "files_needing_changes": [],
                }

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", ReviewingProposalClient), patch(
            "agent.agent_loop.validate_proposal", AsyncMock(return_value={"supported": True, "ok": True})
        ):
            result = asyncio.run(run_agent("saveConfig 함수 이름을 saveSettings로 변경해줘", "test-model"))

        self.assertIn("변경안을 만들었습니다", result["message"])
        self.assertEqual(ReviewingProposalClient.proposal_calls, 2)
        self.assertEqual(ReviewingProposalClient.review_calls, 2)
        self.assertIn("호출부 이름도 함께 변경", ReviewingProposalClient.feedback_received)

    @unittest.skip("별도 reviewer/repair 호출이 제거됨")
    def test_unsubstantiated_review_does_not_discard_a_repaired_build(self) -> None:
        class RepairingProposalClient:
            review_calls = 0

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def propose_from_evidence(self, model, request, project_map, evidence, history=None, feedback=""):
                return {
                    "acceptance_criteria": ["saveConfig is renamed"],
                    "file_plan": {"src/config_writer.cpp": "Rename the function"},
                    "files": [{
                        "path": "src/config_writer.cpp",
                        "changes": [{
                            "old": "void saveConfig()",
                            "new": "void saveSettings()",
                        }],
                    }],
                }

            async def review_proposal(self, model, request, project_map, evidence, proposal, previewed_files):
                self.__class__.review_calls += 1
                if self.__class__.review_calls == 1:
                    return {
                        "complete": True,
                        "missing_requirements": [],
                        "unsafe_or_inconsistent_changes": [],
                        "files_needing_changes": [],
                    }
                return {
                    "complete": False,
                    "missing_requirements": [],
                    "unsafe_or_inconsistent_changes": [],
                    "files_needing_changes": [],
                }

            async def repair_from_validation(self, model, request, proposal, previewed_files, validation_feedback):
                return proposal

        validations = AsyncMock(side_effect=[
            {"supported": True, "ok": False, "message": "compiler error"},
            {"supported": True, "ok": True, "message": "build passed"},
        ])
        with patch("agent.agent_loop.conversations", self.store), patch(
            "agent.agent_loop.OllamaClient", RepairingProposalClient
        ), patch("agent.agent_loop.validate_proposal", validations):
            result = asyncio.run(run_agent("saveConfig 함수 이름을 saveSettings로 변경해줘", "test-model"))

        self.assertIn("변경안을 만들었습니다", result["message"])
        self.assertEqual(RepairingProposalClient.review_calls, 2)
        self.assertEqual(validations.await_count, 2)

    @unittest.skip("검증 실패 Diff도 사용자 확인 후 적용할 수 있는 정책으로 변경됨")
    def test_validation_failure_keeps_non_applicable_diff_visible(self) -> None:
        class FailingProposalClient:
            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def propose_from_evidence(self, model, request, project_map, evidence, history=None, feedback=""):
                return {
                    "acceptance_criteria": ["saveConfig is renamed"],
                    "file_plan": {"src/config_writer.cpp": "Rename the function"},
                    "files": [{
                        "path": "src/config_writer.cpp",
                        "changes": [{"old": "saveConfig", "new": "saveSettings"}],
                    }],
                }

            async def review_proposal(self, model, request, project_map, evidence, proposal, previewed_files):
                return {
                    "complete": True,
                    "missing_requirements": [],
                    "unsafe_or_inconsistent_changes": [],
                    "files_needing_changes": [],
                }

            async def repair_from_validation(self, model, request, proposal, previewed_files, validation_feedback):
                return proposal

        validations = AsyncMock(side_effect=[
            {"supported": True, "ok": False, "message": "duplicate definition"},
            {"supported": True, "ok": False, "message": "duplicate definition"},
        ])
        with patch.dict(os.environ, {"AURA_PROPOSAL_ATTEMPTS": "1"}), patch(
            "agent.agent_loop.conversations", self.store
        ), patch("agent.agent_loop.OllamaClient", FailingProposalClient), patch(
            "agent.agent_loop.validate_proposal", validations
        ):
            result = asyncio.run(run_agent("saveConfig 함수 이름을 saveSettings로 변경해줘", "test-model"))

        self.assertIn("검증에 실패", result["message"])
        failed = pending["src/config_writer.cpp"]
        self.assertEqual(failed["validation_status"], "failed")
        self.assertEqual(failed["validation_error"], "격리된 프로젝트 검증 실패: duplicate definition")
        self.assertEqual(failed["retry_request"], "saveConfig 함수 이름을 saveSettings로 변경해줘")

    def test_retries_ungrounded_answer_then_requires_search_and_source_read(self) -> None:
        class FakeOllamaClient:
            calls = 0
            captured_messages: list[list[dict]] = []
            captured_tools: list[list[dict]] = []

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.calls += 1
                self.__class__.captured_messages.append([dict(item) for item in messages])
                self.__class__.captured_tools.append(tools)
                if self.__class__.calls == 1:
                    return {"role": "assistant", "content": "정보를 더 알려주세요."}
                if self.__class__.calls == 2:
                    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_code", "arguments": {"query": "saveConfig"}}}]}
                if self.__class__.calls == 3:
                    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "src/config_writer.cpp"}}}]}
                return {"role": "assistant", "content": "설정은 실행 경로의 settings.json에 저장됩니다. 근거: src/config_writer.cpp"}

        events = []

        async def on_event(event):
            events.append(event)

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", FakeOllamaClient):
            result = asyncio.run(run_agent("설정 파일이 생성되는 경로가 어디야?", "test-model", on_event))

        self.assertIn("settings.json", result["message"])
        self.assertEqual([event["tool"] for event in events], ["search_code", "read_file"])
        self.assertEqual(result["relevant_files"], ["src/config_writer.cpp"])
        self.assertTrue(any("코드 근거" in item.get("content", "") for item in FakeOllamaClient.captured_messages[1]))
        first_system = FakeOllamaClient.captured_messages[0][0]["content"]
        self.assertIn("CMake", first_system)
        offered_names = {item["function"]["name"] for item in FakeOllamaClient.captured_tools[0]}
        self.assertIn("search_regex", offered_names)
        self.assertNotIn("propose_changes", offered_names)
        self.assertNotIn("git_commit", offered_names)

    def test_blocks_answer_when_model_repeatedly_refuses_to_investigate(self) -> None:
        class RefusingOllamaClient:
            calls = 0

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.calls += 1
                return {"role": "assistant", "content": "정보를 더 알려주세요."}

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", RefusingOllamaClient):
            result = asyncio.run(run_agent("설정 파일 저장 경로가 어디야?", "test-model"))

        self.assertEqual(RefusingOllamaClient.calls, 4)
        self.assertIn("근거 없는 답변은 표시하지 않았습니다", result["message"])

    def test_does_not_execute_the_same_successful_tool_call_repeatedly(self) -> None:
        class RepeatingOllamaClient:
            calls = 0

            async def model_capabilities(self, model: str) -> list[str]:
                return ["tools"]

            async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
                self.__class__.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {"name": "read_file", "arguments": {"path": "src/config_writer.cpp"}}
                    }],
                }

        with patch("agent.agent_loop.conversations", self.store), patch("agent.agent_loop.OllamaClient", RepeatingOllamaClient):
            result = asyncio.run(run_agent("MissingSymbol 함수가 어디서 호출되는지 알려줘", "test-model"))

        read_events = [event for event in result["events"] if event["tool"] == "read_file"]
        self.assertEqual(RepeatingOllamaClient.calls, 3)
        self.assertEqual([event["status"] for event in read_events], ["completed", "failed", "failed"])
        self.assertIn("이미 성공했습니다", read_events[1]["detail"])
        self.assertIn("같은 도구 호출", result["message"])


if __name__ == "__main__":
    unittest.main()
