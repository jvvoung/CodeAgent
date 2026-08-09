import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from models.schemas import Change, ProposedFile
from security.path_guard import guard
from tools.build_tools import detect_command
from tools.file_tools import MAX_FILE_SIZE, read_file, read_file_range, repository_map, search_code, search_regex, tree
from tools.patch_tools import apply, clear, pending, propose, propose_failed, preview, reject, stage_preview
from services.command_runner import run_command


class CoreToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "settings.py").write_text("TIMEOUT = 5000\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Example project\n", encoding="utf-8")
        guard.open(str(self.root))
        clear()

    def tearDown(self) -> None:
        clear()
        guard.root = None
        self.temporary.cleanup()

    def test_tree_read_and_search(self) -> None:
        (self.root / "bin").mkdir()
        (self.root / "bin" / "generated.dll").write_bytes(b"binary")
        (self.root / "model.gguf").write_bytes(b"model")
        nodes = tree()
        self.assertEqual([node["name"] for node in nodes], ["src", "README.md"])
        self.assertEqual(read_file("src/settings.py"), "TIMEOUT = 5000\n")
        self.assertEqual(search_code("TIMEOUT")[0]["path"], "src/settings.py")

    def test_repository_map_detects_cpp_and_build_system(self) -> None:
        (self.root / "CMakeLists.txt").write_text("add_executable(example src/main.cpp)\n", encoding="utf-8")
        (self.root / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")

        result = repository_map()

        self.assertIn("CMake", result["build_systems"])
        self.assertIn("CMakeLists.txt", result["manifests"])
        self.assertIn("src/main.cpp", result["entry_points"])
        self.assertIn({"name": "C++", "files": 1}, result["languages"])

    def test_regex_search_and_bounded_file_read(self) -> None:
        source = self.root / "src" / "writer.cpp"
        source.write_text("void saveConfig() {\n  std::ofstream out(\"settings.json\");\n}\n", encoding="utf-8")

        hits = search_regex(r"ofstream|fopen")
        excerpt = read_file_range("src/writer.cpp", 1, 2)

        self.assertEqual(hits[0]["path"], "src/writer.cpp")
        self.assertEqual(hits[0]["line"], 2)
        self.assertEqual(excerpt["end_line"], 2)
        self.assertIn("ofstream", excerpt["content"])

    def test_path_escape_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "루트 밖"):
            read_file("../outside.txt")

    def test_unique_filename_is_resolved_in_nested_folder(self) -> None:
        self.assertEqual(read_file("settings.py"), "TIMEOUT = 5000\n")

    def test_missing_file_reports_path_instead_of_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "파일을 찾을 수 없습니다: missing.py"):
            read_file("missing.py")

    def test_ambiguous_filename_requires_relative_path(self) -> None:
        (self.root / "other").mkdir()
        (self.root / "other" / "settings.py").write_text("OTHER = True\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "같은 이름의 파일이 여러 개"):
            read_file("settings.py")

    def test_large_file_reports_actual_size(self) -> None:
        large = self.root / "large.txt"
        large.write_bytes(b"x" * (MAX_FILE_SIZE + 1))
        with self.assertRaisesRegex(ValueError, "파일 용량이 제한을 초과했습니다"):
            read_file("large.txt")

    def test_patch_requires_unchanged_original(self) -> None:
        proposal = ProposedFile(path="src/settings.py", changes=[Change(old="5000", new="10000")])
        proposed = propose([proposal])
        self.assertEqual(proposed[0]["modified"], "TIMEOUT = 10000\n")
        (self.root / "src" / "settings.py").write_text("TIMEOUT = 7000\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "파일 내용이 달라졌습니다"):
            apply(None)

    def test_patch_accepts_unique_anchor_with_whitespace_only_differences(self) -> None:
        target = self.root / "sample.txt"
        target.write_text("before\n    save(  value );\nafter\n", encoding="utf-8")
        result = propose([ProposedFile(path="sample.txt", changes=[Change(
            old="before\nsave( value );",
            new="before\nsave( value );\ninserted",
        )])])
        self.assertIn("    save(  value );\ninserted", result[0]["modified"])

    def test_patch_apply_and_reject(self) -> None:
        proposal = ProposedFile(path="src/settings.py", changes=[Change(old="5000", new="10000")])
        propose([proposal])
        apply(["src/settings.py"])
        self.assertEqual(read_file("src/settings.py"), "TIMEOUT = 10000\n")
        propose([ProposedFile(path="src/settings.py", changes=[Change(old="10000", new="12000")])])
        reject(None)
        self.assertFalse(pending)

    def test_patch_apply_supports_added_and_deleted_files(self) -> None:
        stage_preview([
            {
                "path": "src/new.py", "original": "", "modified": "VALUE = 1\n",
                "original_exists": False, "modified_exists": True, "change_type": "added",
                "additions": 1, "deletions": 0,
            },
            {
                "path": "README.md", "original": "# Example project\n", "modified": "",
                "original_exists": True, "modified_exists": False, "change_type": "deleted",
                "additions": 0, "deletions": 1,
            },
        ], validation_status="verified")

        apply(None)

        self.assertEqual((self.root / "src" / "new.py").read_text(encoding="utf-8"), "VALUE = 1\n")
        self.assertFalse((self.root / "README.md").exists())

    def test_failed_patch_is_visible_and_requires_confirmation_to_apply(self) -> None:
        proposal = ProposedFile(path="src/settings.py", changes=[Change(old="5000", new="10000")])
        proposed = preview([proposal])
        propose_failed(proposed, "구문 검사 실패", "제한 시간을 변경해줘")

        item = pending["src/settings.py"]
        self.assertEqual(item["validation_status"], "failed")
        self.assertEqual(item["validation_error"], "구문 검사 실패")
        self.assertEqual(item["retry_request"], "제한 시간을 변경해줘")
        with self.assertRaisesRegex(ValueError, "사용자 확인"):
            apply(["src/settings.py"])
        apply(["src/settings.py"], confirm_unverified=True)
        self.assertEqual(read_file("src/settings.py"), "TIMEOUT = 10000\n")

    def test_patch_resolves_unique_filename(self) -> None:
        proposed = propose([ProposedFile(path="settings.py", changes=[Change(old="5000", new="9000")])])
        self.assertEqual(proposed[0]["path"], "src/settings.py")

    def test_build_detection(self) -> None:
        (self.root / "package.json").write_text("{}", encoding="utf-8")
        self.assertEqual(detect_command(self.root), ["npm.cmd", "run", "build"])
        self.assertEqual(detect_command(self.root, test=True), ["npm.cmd", "test"])

    def test_python_build_uses_current_interpreter(self) -> None:
        (self.root / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
        self.assertEqual(detect_command(self.root)[0], sys.executable)

    def test_command_timeout_on_python_310(self) -> None:
        result = asyncio.run(
            run_command([sys.executable, "-c", "import time; time.sleep(1)"], str(self.root), timeout=0.01)
        )
        self.assertEqual(result["return_code"], -1)
        self.assertIn("초과했습니다", result["stderr"])


if __name__ == "__main__":
    unittest.main()
