import asyncio
import tempfile
import unittest
from pathlib import Path

from security.path_guard import guard
from tools.terminal_tools import run_terminal


class TerminalToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "terminal-marker.txt").write_text("AURA\n", encoding="utf-8")
        (self.root / "nested").mkdir()
        guard.open(str(self.root))

    def tearDown(self) -> None:
        guard.root = None
        self.temporary.cleanup()

    def test_cmd_runs_from_open_project(self) -> None:
        result = asyncio.run(run_terminal("cmd", "if exist terminal-marker.txt (echo CMD_OK) else (exit /b 1)"))

        self.assertEqual(result["return_code"], 0)
        self.assertIn("CMD_OK", result["stdout"])
        self.assertEqual(Path(result["cwd"]), self.root)

    def test_powershell_runs_from_open_project(self) -> None:
        command = "if (Test-Path -LiteralPath 'terminal-marker.txt') { 'POWERSHELL_OK' } else { exit 1 }"
        result = asyncio.run(run_terminal("powershell", command))

        self.assertEqual(result["return_code"], 0)
        self.assertIn("POWERSHELL_OK", result["stdout"])
        self.assertEqual(Path(result["cwd"]), self.root)

    def test_git_bash_runs_from_open_project(self) -> None:
        result = asyncio.run(run_terminal("git-bash", "test -f terminal-marker.txt && echo GIT_BASH_OK"))

        self.assertEqual(result["return_code"], 0)
        self.assertIn("GIT_BASH_OK", result["stdout"])
        self.assertEqual(Path(result["cwd"]), self.root)

    def test_cd_changes_the_next_command_directory_for_every_shell(self) -> None:
        cases = [
            ("cmd", "cd nested", "if exist ..\\terminal-marker.txt (echo CMD_NESTED) else (exit /b 1)"),
            ("powershell", "Set-Location -LiteralPath 'nested'", "if (Test-Path -LiteralPath '..\\terminal-marker.txt') { 'POWERSHELL_NESTED' } else { exit 1 }"),
            ("git-bash", "cd nested", "test -f ../terminal-marker.txt && echo GIT_BASH_NESTED"),
        ]
        for shell, change_directory, verify_command in cases:
            with self.subTest(shell=shell):
                changed = asyncio.run(run_terminal(shell, change_directory))
                self.assertEqual(changed["return_code"], 0)
                self.assertEqual(Path(changed["cwd"]), self.root / "nested")

                verified = asyncio.run(run_terminal(shell, verify_command, cwd=changed["cwd"]))
                self.assertEqual(verified["return_code"], 0)
                self.assertIn("NESTED", verified["stdout"])

    def test_cd_can_move_outside_the_initial_project(self) -> None:
        changed = asyncio.run(run_terminal("cmd", "cd .."))

        self.assertEqual(changed["return_code"], 0)
        self.assertEqual(Path(changed["cwd"]), self.root.parent)


if __name__ == "__main__":
    unittest.main()
