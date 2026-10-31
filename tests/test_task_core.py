import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.coding_harness.agent import RunLimits
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


def tool(tool_name, /, **arguments):
    return json.dumps({"type": "tool", "tool": tool_name, "arguments": arguments})


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


class FailingThenPassingCheck:
    """A check script that passes only once the note says 'fixed'."""
    SOURCE = ("from pathlib import Path\n"
              "import sys\n"
              "print('note is', Path('note.txt').read_text().strip())\n"
              "sys.exit(0 if 'fixed' in Path('note.txt').read_text() else 3)\n")


class SavedTaskTests(CoreTestCase):
    def test_a_restarted_core_reopens_details_steps_history_errors_and_check_results(self):
        model = ScriptedModel(edit("other.py", "denied"), edit("note.txt", "new\n"), final("All done."))
        task = self.core(model).start("demo", "Update the note")

        saved = self.core().show(task.task_id)

        self.assertEqual(saved.request, "Update the note")
        self.assertEqual(saved.project, "demo")
        self.assertEqual(saved.start_commit, self.start_commit)
        self.assertEqual(saved.allowed_changes, ("note.txt", "tests/**"))
        self.assertEqual(saved.check_names, ("core",))
        self.assertEqual(saved.state, "completed")
        self.assertEqual(saved.final_response, "All done.")
        self.assertEqual([step.tool for step in saved.steps], ["edit", "edit"])
        self.assertIn("allowed changes", saved.steps[0].result)
        self.assertTrue(saved.steps[0].denied)
        self.assertIn("allowed changes", " ".join(saved.errors))
        self.assertTrue(any("Update the note" in message["content"] for message in saved.history))
        self.assertEqual([(check.check_name, check.passed) for check in saved.checks], [("core", True)])
        self.assertEqual(saved.counters.actions, 1)
        self.assertEqual(saved.changed_files, ("note.txt",))
        self.assertIn("+new", saved.diff)

    def test_tasks_are_listed_with_their_states(self):
        first = self.core(ScriptedModel(tool("list"), final())).start("demo", "First")
        second = self.core(ScriptedModel(StopIteration())).start("demo", "Second")

        listed = {task.task_id: task.state for task in self.core().list_tasks()}

        self.assertEqual(listed[first.task_id], "completed")
        self.assertEqual(listed[second.task_id], "failed")

    def test_saved_state_is_visible_while_a_run_is_active(self):
        seen = []
        observer = self.core()

        def observe(message):
            if message.startswith("Tool action"):
                seen.append(observer.list_tasks()[0])

        self.core(ScriptedModel(tool("list"), final())).start("demo", "Watch me", progress=observe)

        self.assertEqual(seen[0].state, "running")
        self.assertEqual(len(observer.show(seen[0].task_id).steps), 1)

    def test_the_starting_state_for_diffs_survives_a_restart(self):
        task = self.core(ScriptedModel(edit("note.txt", "new\n"), StopIteration())).start("demo", "Edit")

        saved = self.core().show(task.task_id)

        self.assertEqual(saved.changed_files, ("note.txt",))
        self.assertIn("-old", saved.diff)

    def test_saved_state_contains_no_api_key(self):
        class KeyedModel(ScriptedModel):
            _api_key = "sk-do-not-store"

        self.core(KeyedModel(tool("list"), final())).start("demo", "Inspect")

        for path in (self.root / "state").rglob("*"):
            if path.is_file():
                self.assertNotIn(b"sk-do-not-store", path.read_bytes(), path)


class FixLoopTests(CoreTestCase):
    def fixable_project(self):
        (self.repository / "tests" / "check.py").write_text(FailingThenPassingCheck.SOURCE, encoding="utf-8")
        git(self.repository, "add", ".")
        git(self.repository, "commit", "-qm", "check")
        return {"demo": self.project()}

    def test_a_failed_check_after_a_completion_claim_guides_a_fix(self):
        model = ScriptedModel(edit("note.txt", "wrong\n"), final("Finished."), edit("note.txt", "fixed\n"), final("Now fixed."))

        task = self.core(model, self.fixable_project()).start("demo", "Fix the note")

        self.assertEqual(task.result.outcome, "completed")
        self.assertEqual(task.result.counters.fix_attempts, 1)
        feedback = model.requests[2][-1]["content"]
        self.assertIn("note is wrong", feedback)
        self.assertIn("untrusted", feedback.lower())
        self.assertEqual(task.result.final_response, "Now fixed.")

    def test_the_model_can_run_a_configured_check_mid_task(self):
        model = ScriptedModel(tool("check", name="core"), edit("note.txt", "fixed\n"), final())

        task = self.core(model, self.fixable_project()).start("demo", "Fix the note")

        self.assertIn("note is old", model.requests[1][-1]["content"])
        self.assertEqual(task.result.outcome, "completed")
        self.assertEqual(task.result.counters.fix_attempts, 0)

    def test_the_model_cannot_name_an_unconfigured_check(self):
        model = ScriptedModel(tool("check", name="rm -rf /"), tool("list"), final())

        task = self.core(model).start("demo", "Try it")

        self.assertEqual(task.result.counters.denied_actions, 1)
        self.assertFalse(any("rm -rf" in " ".join(spec.command) for spec in self.runner.specs))

    def test_running_out_of_fix_attempts_fails_the_task_with_the_failure_visible(self):
        replies = [edit("note.txt", "wrong\n")] + [final("Claimed.")] * 4
        task = self.core(ScriptedModel(*replies), self.fixable_project()).start("demo", "Fix the note")

        self.assertEqual(task.result.outcome, "failed")
        self.assertEqual(task.result.counters.fix_attempts, 3)
        self.assertIn("Fix attempt limit", task.result.stopped_reason)
        self.assertFalse(task.result.verification.checks[0].passed)
        self.assertEqual([c.passed for c in self.core().show(task.task_id).checks], [False])

    def test_unavailable_checks_fail_the_task_and_never_appear_as_passed(self):
        self.runner.unavailable = "Docker daemon is not running."

        task = self.core(ScriptedModel(tool("list"), final())).start("demo", "Inspect")

        self.assertEqual(task.result.outcome, "failed")
        check = self.core().show(task.task_id).checks[0]
        self.assertFalse(check.passed)
        self.assertTrue(check.blocked)
        self.assertEqual(task.result.counters.fix_attempts, 0)

    def test_a_claim_of_no_change_needed_is_settled_by_the_checks(self):
        task = self.core(ScriptedModel(tool("list"), final("No change is needed."))).start("demo", "Inspect")

        self.assertEqual(task.result.outcome, "completed")

    def test_a_final_reply_before_any_tool_use_is_denied_once(self):
        model = ScriptedModel(final("Immediately done."), tool("list"), final())

        task = self.core(model).start("demo", "Inspect")

        self.assertEqual(task.result.counters.denied_actions, 1)
        self.assertEqual(task.result.outcome, "completed")

    def test_each_limit_stops_the_task_visibly(self):
        cases = [
            ("actions", RunLimits(actions=1), [tool("list"), tool("list"), final()], "Tool action limit"),
            ("responses", RunLimits(responses=1), [tool("list"), final()], "response limit"),
            ("retries", RunLimits(retries=2), ["junk", "junk", final()], "Retry limit"),
            ("tokens", RunLimits(tokens=1), [tool("list"), final()], "Token limit"),
        ]
        for name, limits, replies, message in cases:
            with self.subTest(name):
                task = self.core(ScriptedModel(*replies), limits=limits).start("demo", "Inspect")

                self.assertEqual(task.result.outcome, "failed")
                self.assertIn(message, task.result.stopped_reason)

    def test_valid_replies_reset_consecutive_retries_while_denied_actions_count_toward_them(self):
        replies = ["junk", tool("list"), "junk", tool("list"), final()]
        task = self.core(ScriptedModel(*replies), limits=RunLimits(retries=2)).start("demo", "Inspect")
        self.assertEqual(task.result.outcome, "completed")

        denied = [edit("nope.py", "x"), edit("nope.py", "x"), final()]
        task = self.core(ScriptedModel(*denied), limits=RunLimits(retries=2)).start("demo", "Inspect")
        self.assertIn("Retry limit", task.result.stopped_reason)
        self.assertEqual(task.result.counters.actions, 0)

    def test_default_limits_match_the_documented_values(self):
        limits = RunLimits()

        self.assertEqual((limits.actions, limits.responses, limits.retries, limits.fix_attempts, limits.tokens),
                         (60, 80, 3, 3, 200_000))


if __name__ == "__main__":
    unittest.main()
