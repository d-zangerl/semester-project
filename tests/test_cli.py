import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "src" / "main.py"


class CommandLineTests(unittest.TestCase):
    def test_user_task_uses_repository_override_and_runs_its_core_check(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            (repository / "tests").mkdir(parents=True)
            (repository / "tests" / "test_core.py").write_text(
                "from pathlib import Path\n"
                "Path('test-check-artifact.txt').write_text('sandboxed')\n"
                "print('fixture core check passed')\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(ENTRY_POINT), "--repository", str(repository)],
                input="Check the fixture repository\n",
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                check=False,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Task captured: Check the fixture repository", completed.stdout)
            self.assertIn("fixture core check passed", completed.stdout)
            self.assertIn("exit code 0", completed.stdout)
            self.assertIn("task workspace removed", completed.stdout)
            self.assertFalse((repository / "test-check-artifact.txt").exists())

    def test_failed_core_check_is_visible_and_workspace_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            (repository / "tests").mkdir(parents=True)
            (repository / "tests" / "test_core.py").write_text(
                "import sys\nprint('fixture failure output')\nraise SystemExit(7)\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(ENTRY_POINT), "--repository", str(repository)],
                input="Check a failing fixture\n",
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                check=False,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("FAIL:", completed.stdout)
            self.assertIn("exit code 7", completed.stdout)
            self.assertIn("fixture failure output", completed.stdout)
            workspace_line = next(
                line for line in completed.stdout.splitlines() if line.startswith("Task workspace: ")
            )
            workspace = Path(workspace_line.removeprefix("Task workspace: "))
            self.assertTrue(workspace.is_dir())
            shutil.rmtree(workspace)


if __name__ == "__main__":
    unittest.main()
