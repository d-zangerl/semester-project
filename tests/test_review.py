import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.coding_harness.cli import UserInterface
from src.coding_harness.execution import CheckResult


class EditThenFinish:
    def __init__(self, edits=(("note.txt", "new text\n"),)):
        self.responses = [
            json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": path, "content": content}})
            for path, content in edits
        ] + [json.dumps({"type": "final", "response": "Edited."})]
        self.index = 0

    def request(self, messages):
        response = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return response


class FakeChecks:
    check_names = ("core",)

    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.workspaces = []
        self.seen_notes = []

    def run_check(self, name, workspace):
        workspace = Path(workspace)
        self.workspaces.append(workspace)
        self.seen_notes.append((workspace / "note.txt").read_text(encoding="utf-8"))
        exit_code, blocked = self.outcomes.pop(0) if self.outcomes else (0, False)
        return CheckResult(name, None if blocked else exit_code, f"check output {len(self.workspaces)}\n", "",
                           False, False, blocked=blocked, error="sandbox unavailable" if blocked else None)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        (self.repository / "note.txt").write_text("original\n", encoding="utf-8")
        (self.repository / "keep.txt").write_text("keep\n", encoding="utf-8")

    def run_session(self, inputs, checks=None, model=None, between=None):
        checks = checks or FakeChecks()
        interface = UserInterface(
            model_client_factory=lambda: model or EditThenFinish(),
            execution_environment_factory=lambda: checks,
        )
        output = io.StringIO()
        feed = iter(inputs)

        def fake_input(prompt=""):
            try:
                value = next(feed)
            except StopIteration:
                raise EOFError
            if between and value == "<MUTATE>":
                between()
                return next(feed)
            return value

        with patch("builtins.input", side_effect=fake_input), redirect_stdout(output):
            status = interface.run(["--repository", str(self.repository)])
        text = output.getvalue()
        workspaces = [Path(line.removeprefix("Task workspace: "))
                      for line in text.splitlines() if line.startswith("Task workspace: ")]
        self.addCleanup(lambda: [__import__("shutil").rmtree(w, ignore_errors=True) for w in workspaces])
        return status, text, workspaces, checks

    def test_review_keeps_diff_available_and_target_unchanged_until_decision(self):
        status, text, workspaces, _ = self.run_session(["Edit the note", "/diff", "/quit"])
        self.assertEqual(text.count("+new text"), 2)
        self.assertIn("/approve", text)
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "original\n")
        self.assertTrue(workspaces[0].exists())

    def test_reject_leaves_target_unchanged_and_removes_passing_workspace(self):
        status, text, workspaces, _ = self.run_session(["Edit the note", "/reject", "/quit"])
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "original\n")
        self.assertFalse(workspaces[0].exists())
        self.assertIn("Rejected", text)

    def test_approve_applies_complete_change_set_and_verifies_fresh_copy_then_cleans_up(self):
        model = EditThenFinish([("note.txt", "new text\n"), ("added/new.txt", "created\n")])
        status, text, workspaces, checks = self.run_session(["Edit things", "/approve", "/quit"], model=model)
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "new text\n")
        self.assertEqual((self.repository / "added" / "new.txt").read_text(encoding="utf-8"), "created\n")
        self.assertEqual((self.repository / "keep.txt").read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(len(checks.workspaces), 2)
        post_apply_workspace = checks.workspaces[1]
        self.assertNotEqual(post_apply_workspace, workspaces[0])
        self.assertNotEqual(post_apply_workspace, self.repository)
        self.assertEqual(checks.seen_notes[1], "new text\n")
        self.assertIn("Applied 2 file(s)", text)
        self.assertIn("Post-apply check core: PASS (exit code 0)", text)
        self.assertIn("check output 2", text)
        self.assertFalse(workspaces[0].exists())
        self.assertFalse(post_apply_workspace.exists())

    def test_target_mismatch_is_warned_before_apply_and_explicit_approval_force_applies(self):
        def mutate():
            (self.repository / "note.txt").write_text("changed elsewhere\n", encoding="utf-8")

        status, text, workspaces, _ = self.run_session(
            ["Edit the note", "<MUTATE>", "/approve", "/quit"], between=mutate)
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "new text\n")
        warning = text.index("WARNING: the configured repository changed")
        self.assertLess(warning, text.index("Applied 1 file(s)"))
        self.assertIn("note.txt", text[warning:])

    def test_failed_post_apply_check_is_reported_and_workspaces_are_retained(self):
        checks = FakeChecks([(0, False), (1, False)])
        status, text, workspaces, checks = self.run_session(["Edit the note", "/approve", "/quit"], checks=checks)
        self.assertIn("Post-apply check core: FAIL (exit code 1)", text)
        self.assertNotIn("Post-apply verification passed", text)
        self.assertEqual(status, 1)
        self.assertTrue(checks.workspaces[1].exists())
        self.addCleanup(lambda: __import__("shutil").rmtree(checks.workspaces[1], ignore_errors=True))
        self.assertIn(checks.workspaces[1].name, text)

    def test_blocked_post_apply_check_is_unavailable_not_success(self):
        checks = FakeChecks([(0, False), (0, True)])
        status, text, workspaces, checks = self.run_session(["Edit the note", "/approve", "/quit"], checks=checks)
        self.assertIn("Post-apply check core: UNAVAILABLE", text)
        self.assertEqual(status, 1)
        self.addCleanup(lambda: __import__("shutil").rmtree(checks.workspaces[1], ignore_errors=True))

    def test_failed_task_check_retains_workspace_even_when_rejected(self):
        checks = FakeChecks([(1, False)])
        status, text, workspaces, _ = self.run_session(["Edit the note", "/reject", "/quit"], checks=checks)
        self.assertTrue(workspaces[0].exists())
        self.assertIn(str(workspaces[0]), text)
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "original\n")

    def test_end_of_input_during_review_does_not_apply_and_retains_workspace(self):
        status, text, workspaces, _ = self.run_session(["Edit the note"])
        self.assertEqual((self.repository / "note.txt").read_text(encoding="utf-8"), "original\n")
        self.assertTrue(workspaces[0].exists())


if __name__ == "__main__":
    unittest.main()
