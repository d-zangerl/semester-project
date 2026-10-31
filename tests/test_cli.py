import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.coding_harness.agent import RunCounters, RunLimits
from src.coding_harness.cli import main
from src.coding_harness.core import ApprovalOutcome, SavedTask, UnknownProjectError
from src.coding_harness.execution import CheckResult
from src.coding_harness.model import client_from_environment


def saved_task(**changes):
    values = dict(task_id="abc", project="demo", request="Do it", start_commit="c1", allowed_changes=("a.py",),
                  check_names=("core",), state="completed", reason=None, final_response="Done", review_decision=None,
                  workspace=Path("/w"), runs=1, limits=RunLimits(), counters=RunCounters(), steps=(), errors=(),
                  history=(), checks=(CheckResult("core", 0, "", "", False, False),), changed_files=("a.py",),
                  diff="+new")
    values.update(changes)
    return SavedTask(**values)


class CommandRoutingTests(unittest.TestCase):
    """The commands hold no task logic; they route to the core and show what it returns."""

    def run_command(self, *arguments):
        self.core = MagicMock()
        self.core.projects = {"demo": SimpleNamespace(path="/repo")}
        self.core.show.return_value = saved_task()
        self.core.review.return_value = saved_task()
        self.core.list_tasks.return_value = [saved_task()]
        self.core.start.return_value = SimpleNamespace(task_id="abc", result=SimpleNamespace(outcome=self.outcome))
        self.core.resume.return_value = self.core.start.return_value
        self.core.continue_task.return_value = self.core.start.return_value
        self.core.approve.return_value = self.approval
        self.core_options = {}

        def factory(**options):
            self.core_options = options
            return self.core

        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(list(arguments), core_factory=factory)
        return status, output.getvalue(), errors.getvalue()

    outcome = "completed"
    approval = ApprovalOutcome(("a.py",), (), (CheckResult("core", 0, "", "", False, False),), None)

    def test_start_routes_to_the_core_and_shows_the_result(self):
        status, output, _ = self.run_command("start", "demo", "Do it")

        self.assertEqual(status, 0)
        self.assertEqual(self.core.start.call_args.args, ("demo", "Do it"))
        self.assertTrue(self.core_options["with_model"])
        self.assertIn("core: PASS", output)
        self.assertIn("+new", output)

    def test_the_exit_code_reflects_the_task_outcome(self):
        for outcome, expected in (("failed", 1), ("paused", 2), ("cancelled", 130)):
            with self.subTest(outcome), patch.object(type(self), "outcome", outcome):
                self.assertEqual(self.run_command("start", "demo", "Do it")[0], expected)

    def test_list_show_and_cancel_need_no_model(self):
        for arguments in (("list",), ("show", "abc"), ("cancel", "abc"), ("review", "abc")):
            with self.subTest(arguments):
                self.run_command(*arguments)
                self.assertFalse(self.core_options["with_model"])

    def test_list_shows_state(self):
        _, output, _ = self.run_command("list")

        self.assertIn("abc", output)
        self.assertIn("completed", output)

    def test_projects_lists_allowed_projects(self):
        _, output, _ = self.run_command("projects")

        self.assertIn("demo: /repo", output)

    def test_cancel_routes_to_the_core(self):
        status, _, _ = self.run_command("cancel", "abc")

        self.assertEqual(status, 0)
        self.core.cancel.assert_called_once_with("abc")

    def test_resume_passes_the_explicit_choice(self):
        self.run_command("resume", "abc", "--discard-to-checkpoint")

        self.assertTrue(self.core.resume.call_args.kwargs["discard_to_checkpoint"])
        self.assertFalse(self.core.resume.call_args.kwargs["accept_current_state"])

    def test_resume_refuses_both_choices(self):
        with self.assertRaises(SystemExit):
            self.run_command("resume", "abc", "--discard-to-checkpoint", "--accept-current-state")

    def test_review_shows_without_deciding(self):
        self.run_command("review", "abc")

        self.core.approve.assert_not_called()
        self.core.reject.assert_not_called()

    def test_review_approve_passes_force(self):
        status, output, _ = self.run_command("review", "abc", "--approve", "--force")

        self.assertEqual(status, 0)
        self.core.approve.assert_called_once_with("abc", force=True)
        self.assertIn("Applied: a.py", output)

    def test_a_blocked_approval_lists_the_differences_and_fails(self):
        blocked = ApprovalOutcome((), ("a.py differs",), (), None)
        with patch.object(type(self), "approval", blocked):
            status, output, _ = self.run_command("review", "abc", "--approve")

        self.assertEqual(status, 1)
        self.assertIn("a.py differs", output)

    def test_core_errors_are_reported_without_a_traceback(self):
        def factory(**options):
            core = MagicMock()
            core.start.side_effect = UnknownProjectError("'x' is not an allowed project.")
            return core

        errors = io.StringIO()
        with redirect_stderr(errors):
            status = main(["start", "x", "Do it"], core_factory=factory)

        self.assertEqual(status, 1)
        self.assertIn("not an allowed project", errors.getvalue())

    def test_unavailable_and_failed_checks_stay_visible(self):
        checks = (CheckResult("core", None, "", "", False, False, blocked=True, error="Docker is down"),
                  CheckResult("lint", 4, "bad", "", False, False))
        core = MagicMock()
        core.show.return_value = saved_task(checks=checks, state="failed", final_response="All passed!")
        stream = io.StringIO()
        with redirect_stdout(stream):
            main(["show", "abc"], core_factory=lambda **options: core)
        output = stream.getvalue()

        self.assertIn("UNAVAILABLE: Docker is down", output)
        self.assertIn("lint: FAIL (exit code 4)", output)
        self.assertIn("not verified as complete", output)


class ModelSettingsTests(unittest.TestCase):
    def test_model_request_timeout_is_configurable_and_allows_slow_models(self):
        with patch.dict("os.environ", {"OPENAI_BASE_URL": "http://localhost:1/v1"}, clear=False):
            os.environ.pop("CODING_HARNESS_MODEL_TIMEOUT", None)
            self.assertEqual(client_from_environment("/nonexistent/.env").timeout_seconds, 300)
            os.environ["CODING_HARNESS_MODEL_TIMEOUT"] = "12"
            self.assertEqual(client_from_environment("/nonexistent/.env").timeout_seconds, 12)


class EntryPointTests(unittest.TestCase):
    def test_the_entry_point_shows_help(self):
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run([sys.executable, str(root / "src" / "main.py"), "--help"], capture_output=True, text=True)

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("resume", done.stdout)


if __name__ == "__main__":
    unittest.main()
