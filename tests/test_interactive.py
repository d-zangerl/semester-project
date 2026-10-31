import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.coding_harness.core import UnknownTaskError
from src.coding_harness.interactive import InteractiveSession
from tests.test_cli import saved_task
from tests.test_task_core import CoreTestCase, ScriptedModel, edit, final


class RoutingTests(unittest.TestCase):
    """The interface holds no task logic: it routes to the core and shows what comes back."""

    def session(self):
        self.core = MagicMock()
        self.core.projects = {"demo": object(), "zeta": object()}
        self.core.list_tasks.return_value = []
        self.core.show.return_value = saved_task()
        self.core.review.return_value = saved_task()
        started = SimpleNamespace(task_id="abc")
        self.core.start.return_value = started
        self.core.resume.return_value = started
        self.core.continue_task.return_value = started
        self.core.approve.return_value = MagicMock(blocked_by=("a.py differs",))
        self.lines = []
        return InteractiveSession(self.core, write=self.lines.append)

    def test_plain_text_starts_a_task_on_the_current_project(self):
        session = self.session()

        session.handle_line("Add expiry")
        session.wait()

        self.assertEqual(self.core.start.call_args.args, ("demo", "Add expiry"))
        self.assertEqual(session.current_task, "abc")

    def test_plain_text_warns_about_an_unreviewed_task(self):
        session = self.session()
        step = SimpleNamespace(tool="edit", denied=False)
        self.core.list_tasks.return_value = [saved_task(steps=(step,), task_id="old")]

        session.handle_line("Add expiry")
        session.wait()

        self.assertTrue(any("unreviewed" in line and "old" in line for line in self.lines))

    def test_project_selection_is_limited_to_allowed_projects(self):
        session = self.session()

        session.handle_line("/project zeta")
        self.assertEqual(session.project, "zeta")
        session.handle_line("/project nope")
        self.assertEqual(session.project, "zeta")
        self.assertIn("not an allowed project", self.lines[-1])

    def test_slash_commands_route_to_the_core(self):
        session = self.session()
        session.current_task = "abc"
        for line, method in (("/show", "show"), ("/diff", "review"), ("/cancel", "cancel"), ("/reject", "reject")):
            with self.subTest(line):
                session.handle_line(line)
                getattr(self.core, method).assert_called_with("abc")
        session.handle_line("/tasks")
        self.core.list_tasks.assert_called()

    def test_approve_passes_force_and_shows_a_block(self):
        session = self.session()
        session.current_task = "abc"

        session.handle_line("/approve")
        self.core.approve.assert_called_with("abc", force=False)
        self.assertIn("a.py differs", self.lines[-1])
        session.handle_line("/approve --force")
        self.core.approve.assert_called_with("abc", force=True)

    def test_resume_passes_the_explicit_choice(self):
        session = self.session()

        session.handle_line("/resume abc --accept-current-state")
        session.wait()

        self.assertEqual(self.core.resume.call_args.args, ("abc",))
        self.assertTrue(self.core.resume.call_args.kwargs["accept_current_state"])

    def test_commands_without_a_current_task_explain_themselves(self):
        session = self.session()

        session.handle_line("/approve")

        self.assertIn("No current task", self.lines[-1])

    def test_unknown_commands_and_quit(self):
        session = self.session()

        session.handle_line("/nope")
        self.assertIn("Unknown command", self.lines[-1])
        session.handle_line("/quit")
        self.assertTrue(session.finished)

    def test_failed_and_unavailable_checks_stay_visible(self):
        from src.coding_harness.execution import CheckResult
        session = self.session()
        session.current_task = "abc"
        self.core.review.return_value = saved_task(checks=(
            CheckResult("core", None, "", "", False, False, blocked=True, error="Docker is down"),))

        session.handle_line("/diff")

        self.assertIn("UNAVAILABLE: Docker is down", self.lines[-1])

    def test_a_mistyped_task_id_does_not_break_the_prompt(self):
        session = self.session()
        self.core.show.side_effect = UnknownTaskError("No task with ID 'nope'.")

        session.handle_line("/resume nope")
        session.wait()

        self.assertIsNone(session.current_task)
        self.assertIn("No task", self.lines[-1])
        self.assertIn("demo", session.status_line())

    def test_the_status_line_never_raises(self):
        session = self.session()
        session.current_task = "gone"
        self.core.show.side_effect = UnknownTaskError("gone")

        self.assertIn("demo", session.status_line())

    def test_the_status_line_shows_limits(self):
        session = self.session()
        session.current_task = "abc"

        line = session.status_line()

        self.assertIn("0/60 actions", line)
        self.assertIn("0/200000 tokens", line)


class ContinueThroughTheCoreTests(CoreTestCase):
    def test_continue_keeps_the_task_and_its_consumed_limits(self):
        lines = []
        first = InteractiveSession(self.core(ScriptedModel(edit("note.txt", "one\n"), final())), write=lines.append)
        first.handle_line("Edit the note")
        first.wait()
        task_id = first.current_task

        second = InteractiveSession(self.core(ScriptedModel(edit("note.txt", "two\n"), final())), write=lines.append)
        second.current_task = task_id
        second.handle_line("/continue Use two instead")
        second.wait()

        saved = self.core().show(task_id)
        self.assertEqual(saved.runs, 2)
        self.assertEqual(saved.counters.actions, 2)
        self.assertIn("+two", saved.diff)


if __name__ == "__main__":
    unittest.main()
