import tempfile
import unittest
from pathlib import Path

from agent.retrieval import collect_repository_evidence, extract_search_terms
from security.path_guard import guard


class RetrievalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        guard.open(str(self.root))

    def tearDown(self) -> None:
        guard.root = None
        self.temporary.cleanup()

    def test_extracts_ui_text_and_code_identifiers_without_framework_rules(self) -> None:
        terms = extract_search_terms("저장이라는 버튼을 누르면 ConfigWriter::save에서 파일이 생성되는 경로가 어디야?")

        self.assertIn("저장", terms)
        self.assertIn("버튼", terms)
        self.assertIn("ConfigWriter::save", terms)

    def test_collects_real_code_excerpts_from_korean_question(self) -> None:
        (self.root / "src" / "MainWindow.xaml").write_text('<Button Content="저장" Click="BtnSave_Click"/>\n', encoding="utf-8")
        (self.root / "src" / "MainWindow.xaml.cs").write_text(
            "// 저장 버튼\nvoid BtnSave_Click() { saver.Save(); }\n",
            encoding="utf-8",
        )

        evidence = collect_repository_evidence("저장이라는 버튼을 누르면 어떤 코드가 실행돼?")

        paths = {item["path"] for item in evidence["files"]}
        self.assertGreater(evidence["match_count"], 0)
        self.assertIn("src/MainWindow.xaml", paths)
        self.assertTrue(any("BtnSave_Click" in item["content"] for item in evidence["files"]))

    def test_planner_terms_bridge_korean_question_to_cpp_implementation(self) -> None:
        (self.root / "src" / "config_writer.cpp").write_text(
            '#include <fstream>\nvoid saveConfig() { std::ofstream out("settings.json"); }\n',
            encoding="utf-8",
        )

        evidence = collect_repository_evidence(
            "설정은 어느 위치에 기록돼?",
            extra_terms=["saveConfig", "ofstream", "settings.json"],
        )

        self.assertEqual(evidence["files"][0]["path"], "src/config_writer.cpp")
        self.assertIn("settings.json", evidence["files"][0]["content"])

    def test_late_excerpt_also_includes_file_header_for_imports(self) -> None:
        source = "#include <filesystem>\n" + "\n".join(f"int filler_{line};" for line in range(1, 130))
        source += "\nvoid removeOutputFiles() {}\n"
        (self.root / "src" / "storage.cpp").write_text(source, encoding="utf-8")

        evidence = collect_repository_evidence("removeOutputFiles 함수를 변경해줘")

        target = next(item for item in evidence["files"] if item["path"] == "src/storage.cpp")
        self.assertGreater(target["start_line"], 1)
        self.assertIn("#include <filesystem>", target["header"])


if __name__ == "__main__":
    unittest.main()
