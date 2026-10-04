import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.coding_harness.cli import UserInterface
from src.coding_harness.execution import ExecutionEnvironment


class ScriptedModelClient:
    def __init__(self, response):
        self.response = json.dumps({"type": "final", "response": "Fixture task completed."})

    def request(self, messages):
        return self.response


class CommandLineTests(unittest.TestCase):
    def test_model_request_timeout_is_configurable_and_allows_slow_local_models(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CODING_HARNESS_OLLAMA_TIMEOUT", None)
            self.assertEqual(UserInterface._model_client().timeout_seconds, 300)
            os.environ["CODING_HARNESS_OLLAMA_TIMEOUT"] = "12"
            self.assertEqual(UserInterface._model_client().timeout_seconds, 12)

    def run_fixture(self, check_source):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        repository = root / "repository"
        (repository / "tests").mkdir(parents=True)
        (repository / "tests" / "test_core.py").write_text(check_source, encoding="utf-8")
        output = io.StringIO()
        interface = UserInterface(
            model_client_factory=lambda: ScriptedModelClient("unused"),
            execution_environment_factory=lambda: ExecutionEnvironment(
                checks={"core": (sys.executable, "tests/test_core.py")}
            ),
        )
        with patch("builtins.input", side_effect=["Check the fixture repository", "/quit"]), redirect_stdout(output):
            status = interface.run(["--repository", str(repository)])
        text = output.getvalue()
        workspace_line = next(line for line in text.splitlines() if line.startswith("Task workspace: "))
        workspace = Path(workspace_line.removeprefix("Task workspace: "))
        self.addCleanup(lambda: shutil.rmtree(workspace, ignore_errors=True))
        return status, text, repository, workspace

    def test_task_runs_fixed_check_in_workspace_without_touching_repository(self):
        status, output, repository, workspace = self.run_fixture(
            "from pathlib import Path\n"
            "Path('test-check-artifact.txt').write_text('sandboxed')\n"
            "print('fixture core check passed')\n"
        )
        self.assertEqual(status, 0, output)
        self.assertIn("Final response: Fixture task completed.", output)
        self.assertIn("fixture core check passed", output)
        self.assertIn("core: PASS (exit code 0)", output)
        self.assertTrue((workspace / "test-check-artifact.txt").exists())
        self.assertFalse((repository / "test-check-artifact.txt").exists())

    def test_failed_fixed_check_is_visible_and_workspace_is_retained(self):
        status, output, repository, workspace = self.run_fixture(
            "import sys\nprint('fixture failure output')\nraise SystemExit(7)\n"
        )
        self.assertEqual(status, 1, output)
        self.assertIn("core: FAIL (exit code 7)", output)
        self.assertIn("fixture failure output", output)
        self.assertTrue(workspace.is_dir())
        self.assertFalse((repository / "test-check-artifact.txt").exists())


if __name__ == "__main__":
    unittest.main()
