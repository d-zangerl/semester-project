import json
import tempfile
import unittest
from pathlib import Path

from src.coding_harness.core import TaskCore
from src.coding_harness.execution import CheckResult


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.requests = []

    def request(self, messages):
        self.requests.append(messages)
        return next(self.replies)


class FakeChecks:
    check_names = ("core",)

    def __init__(self, exit_code=0):
        self.exit_code = exit_code

    def run_check(self, name, workspace):
        return CheckResult(name, self.exit_code, "output\n", "", False, False)


def edit(path, content):
    return json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": path, "content": content}})


def final(text="Done."):
    return json.dumps({"type": "final", "response": text})


class TaskCoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        (self.repository / "note.txt").write_text("old\n", encoding="utf-8")

    def core(self, model, checks=None):
        return TaskCore(model_client=model, environment_factory=lambda: checks or FakeChecks(),
                        task_log_directory=self.root / "logs")

    def test_starting_a_task_edits_a_workspace_and_reports_the_result_without_touching_the_repository(self):
        task = self.core(ScriptedModel(edit("note.txt", "new\n"), final())).start(self.repository, "Update the note")

        self.assertEqual(task.result.verification.changed_files, ("note.txt",))
        self.assertTrue(task.result.verification_passed)
        self.assertEqual((task.workspace / "note.txt").read_text(encoding="utf-8"), "new\n")
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "old\n")


if __name__ == "__main__":
    unittest.main()
