import asyncio
import shutil
import unittest
from pathlib import Path

from security.path_guard import guard
from services.proposal_validator import _commands, _compact_failure_output, _diagnostic_lines, _ignore, _infrastructure_failure, validate_proposal


class ProposalValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("cmake"):
            self.skipTest("cmake is not installed")
        self.root = Path(__file__).parent / "fixtures" / "cpp_grounding"
        guard.open(str(self.root))

    def tearDown(self) -> None:
        guard.root = None

    def test_accepts_buildable_generic_cpp_change(self) -> None:
        path = "src/config_store.cpp"
        original = (self.root / path).read_text(encoding="utf-8")
        result = asyncio.run(validate_proposal([{
            "path": path,
            "original": original,
            "modified": original.replace("return 0;", "return EXIT_SUCCESS;").replace(
                "#include <fstream>", "#include <fstream>\n#include <cstdlib>"
            ),
        }]))
        self.assertTrue(result["supported"])
        self.assertTrue(result["ok"])

    def test_rejects_new_compile_error_without_framework_rules(self) -> None:
        path = "src/config_store.cpp"
        original = (self.root / path).read_text(encoding="utf-8")
        result = asyncio.run(validate_proposal([{
            "path": path,
            "original": original,
            "modified": original + "\nint main() { return missing_symbol; }\n",
        }]))
        self.assertTrue(result["supported"])
        self.assertFalse(result["ok"])
        self.assertRegex(result["message"], "실패|빌드 오류")

    def test_dotnet_validation_does_not_restore_from_network(self) -> None:
        with self.subTest("solution"):
            temporary = self.root.parent / "dotnet-command-fixture"
            temporary.mkdir(exist_ok=True)
            try:
                (temporary / "App.sln").write_text("", encoding="utf-8")
                self.assertIn("--no-restore", _commands(temporary)[0])
            finally:
                (temporary / "App.sln").unlink(missing_ok=True)
                temporary.rmdir()

    def test_normalizes_validation_workspace_paths(self) -> None:
        baseline = _diagnostic_lines(r"D:\repo\.aura-validation\proposal-one\baseline\src\a.cpp:4: error")
        proposed = _diagnostic_lines(r"D:\repo\.aura-validation\proposal-two\proposed\src\a.cpp:4: error")
        self.assertEqual(baseline, proposed)

        baseline = _diagnostic_lines(r"D:\repo\.aura-workspaces\task-one\baseline\src\a.cpp:4: error")
        proposed = _diagnostic_lines(r"D:\repo\.aura-workspaces\task-one\worktree\src\a.cpp:4: error")
        self.assertEqual(baseline, proposed)

    def test_recognizes_package_network_failure_as_infrastructure(self) -> None:
        self.assertTrue(_infrastructure_failure("error NU1301: https://api.nuget.org/v3/index.json"))

    def test_validation_copy_skips_local_model_weights(self) -> None:
        temporary = self.root.parent / "copy-ignore-fixture"
        temporary.mkdir(exist_ok=True)
        try:
            (temporary / "model.gguf").write_bytes(b"model")
            (temporary / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
            ignored = _ignore(str(temporary), ["model.gguf", "main.cpp"])
            self.assertIn("model.gguf", ignored)
            self.assertNotIn("main.cpp", ignored)
        finally:
            (temporary / "model.gguf").unlink(missing_ok=True)
            (temporary / "main.cpp").unlink(missing_ok=True)
            temporary.rmdir()

    def test_compacts_build_output_to_relative_actionable_diagnostics(self) -> None:
        output = "\n".join([
            r"D:\repo\.aura-validation\proposal-one\proposed\App\View.cs(12,4): error CS0103: 'Path' is missing [D:\repo\App.csproj]",
            "빌드하지 못했습니다.",
            "워크로드 업데이트를 사용할 수 있습니다.",
        ])

        compact = _compact_failure_output(output)

        self.assertIn("App\\View.cs(12,4): error CS0103", compact)
        self.assertNotIn(".aura-validation", compact)
        self.assertNotIn("워크로드", compact)


if __name__ == "__main__":
    unittest.main()
