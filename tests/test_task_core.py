import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.coding_harness.core import TaskCore, UnknownProjectError
from src.coding_harness.projects import Project
from tests.fakes import LocalRunner


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.requests = []

    def request(self, messages):
        self.requests.append([dict(message) for message in messages])
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def tool(name, **arguments):
    return json.dumps({"type": "tool", "tool": name, "arguments": arguments})


def edit(path, content):
    return tool("edit", path=path, content=content)


def final(text="Done."):
    return json.dumps({"type": "final", "response": text})


def git(directory, *arguments):
    return subprocess.run(["git", "-C", str(directory), "-c", "user.name=t", "-c", "user.email=t@example.com",
                           *arguments], check=True, capture_output=True, text=True).stdout.strip()


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.repository = self.root / "repository"
        (self.repository / "tests").mkdir(parents=True)
        (self.repository / "data").mkdir()
        (self.repository / "note.txt").write_text("old\n", encoding="utf-8")
        (self.repository / "secret.txt").write_text("secret\n", encoding="utf-8")
        (self.repository / "config.example.json").write_text('{"example": true}', encoding="utf-8")
        (self.repository / "config.json").write_text('{"api_key": "real-secret"}', encoding="utf-8")
        (self.repository / "tests" / "check.py").write_text("print('ok')\n", encoding="utf-8")
        (self.repository / ".gitignore").write_text("data/\n", encoding="utf-8")
        (self.repository / "data" / "fixture.db").write_text("fixture", encoding="utf-8")
        git(self.repository, "init", "-q")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-qm", "start")
        self.start_commit = git(self.repository, "rev-parse", "HEAD")
        self.runner = LocalRunner()

    def project(self, **changes):
        settings = dict(
            name="demo", path=self.repository, checks={"core": ("python", "tests/check.py")},
            allowed_changes=("note.txt", "tests/**"), excluded_paths=("secret.txt", "config.json"),
            fixtures=("data/fixture.db",), generated_files={"config.json": "config.example.json"},
        )
        settings.update(changes)
        return Project(**settings)

    def core(self, model=None, projects=None, **options):
        return TaskCore(model_client=model or ScriptedModel(), projects=projects or {"demo": self.project()},
                        state_directory=self.root / "state", runner=self.runner, **options)


class AllowedProjectTests(CoreTestCase):
    def test_a_project_not_listed_is_refused_and_no_workspace_is_created(self):
        with self.assertRaises(UnknownProjectError):
            self.core().start("other", "Do something")

        self.assertFalse((self.root / "state" / "workspaces").exists())

    def test_a_task_edits_its_workspace_and_leaves_the_repository_untouched(self):
        task = self.core(ScriptedModel(edit("note.txt", "new\n"), final())).start("demo", "Update the note")

        self.assertEqual(task.result.verification.changed_files, ("note.txt",))
        self.assertTrue(task.result.verification_passed)
        self.assertEqual((task.workspace / "note.txt").read_text(encoding="utf-8"), "new\n")
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "old\n")

    def test_the_workspace_excludes_credentials_and_adds_only_declared_fixtures(self):
        model = ScriptedModel(tool("read", path="secret.txt"), tool("list"), final())

        task = self.core(model).start("demo", "Inspect")

        self.assertFalse((task.workspace / "secret.txt").exists())
        self.assertEqual((task.workspace / "config.json").read_text(encoding="utf-8"), '{"example": true}')
        self.assertEqual((task.workspace / "data" / "fixture.db").read_text(encoding="utf-8"), "fixture")
        everything = json.dumps(model.requests)
        self.assertNotIn("real-secret", everything)
        self.assertNotIn("secret.txt", json.dumps(model.requests[0]))

    def test_checks_see_only_the_workspace_copy(self):
        task = self.core(ScriptedModel(tool("list"), final())).start("demo", "Inspect")

        self.assertEqual(self.runner.specs[-1].workspace, task.workspace)

    def test_the_task_records_its_starting_commit_and_the_workspace_has_private_history(self):
        task = self.core(ScriptedModel(tool("list"), final())).start("demo", "Inspect")

        self.assertEqual(task.start_commit, self.start_commit)
        self.assertFalse((task.workspace / ".git").exists())
        self.assertEqual(task.repository.remotes(), [])
        self.assertTrue(task.repository.head())

    def test_uncommitted_source_changes_do_not_enter_the_workspace(self):
        (self.repository / "note.txt").write_text("uncommitted\n", encoding="utf-8")

        task = self.core(ScriptedModel(tool("list"), final())).start("demo", "Inspect")

        self.assertEqual((task.workspace / "note.txt").read_text(encoding="utf-8"), "old\n")

    def test_edits_outside_the_allowed_changes_are_denied_and_write_nothing(self):
        model = ScriptedModel(edit("other.py", "x = 1\n"), edit("tests/new.py", "y = 2\n"), final())

        task = self.core(model).start("demo", "Add things")

        self.assertFalse((task.workspace / "other.py").exists())
        self.assertTrue((task.workspace / "tests" / "new.py").exists())
        self.assertIn("allowed changes", model.requests[1][-1]["content"])
        self.assertEqual(task.result.counters.denied_actions, 1)

    def test_progress_is_reported_as_the_task_runs(self):
        seen = []

        self.core(ScriptedModel(tool("list"), final())).start("demo", "Inspect", progress=seen.append)

        self.assertTrue(any("Tool action" in message for message in seen))


if __name__ == "__main__":
    unittest.main()
