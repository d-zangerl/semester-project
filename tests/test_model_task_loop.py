import json
import copy
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.coding_harness.agent import AgentController
from src.coding_harness.agent import RunLimits
from src.coding_harness.cli import UserInterface
from src.coding_harness.model import ModelClient
from src.coding_harness.repository import RepositoryTools
from src.coding_harness.verification import Verification


class ScriptedModelClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def request(self, messages):
        self.requests.append(copy.deepcopy(messages))
        return next(self.responses)


class PassingChecks:
    def __init__(self):
        self.workspaces = []

    def run_check(self, name, workspace):
        self.workspaces.append(Path(workspace))
        return type("Check", (), {
            "check_name": name, "exit_code": 0, "stdout": "checks passed\n", "stderr": "",
            "stdout_truncated": False, "stderr_truncated": False, "timed_out": False,
            "blocked": False, "error": None, "passed": True,
        })()


class ModelTaskLoopTests(unittest.TestCase):
    def test_task_progress_is_appended_to_unique_root_log_as_events_happen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            log_root = root / "harness"
            model = ScriptedModelClient([
                json.dumps({"type": "tool", "tool": "edit", "arguments": {
                    "path": "note.txt", "content": "updated",
                }}),
                json.dumps({"type": "final", "response": "Updated the note."}),
                json.dumps({"type": "final", "response": "Second task complete."}),
            ])
            visible_during_progress = []

            def observe_progress(message):
                if message.startswith("Tool action"):
                    logs = list(log_root.glob("coding-harness-task-*.log"))
                    self.assertEqual(len(logs), 1)
                    visible_during_progress.append(logs[0].read_text(encoding="utf-8"))
                    self.assertIn(message, visible_during_progress[-1])
                if message == "Requesting model response (2/40)":
                    log_text = next(log_root.glob("coding-harness-task-*.log")).read_text(encoding="utf-8")
                    self.assertIn("Tool result for edit", log_text)

            controller = AgentController(
                model,
                RepositoryTools(workspace),
                Verification(PassingChecks()),
                progress=observe_progress,
                task_log_directory=log_root,
            )
            result = controller.run_task("Update the note", workspace)

            logs = list(log_root.glob("coding-harness-task-*.log"))
            self.assertEqual(len(logs), 1)
            self.assertTrue(visible_during_progress)
            contents = logs[0].read_text(encoding="utf-8")
            self.assertIn("Updated the note", contents)
            self.assertIn("Tool result", contents)
            self.assertIn("core", contents)
            self.assertIn("actions=1", contents)
            self.assertIn("Task diff (changed files: note.txt", contents)
            self.assertIn("+++ b/note.txt", contents)
            self.assertIn("+updated", contents)
            self.assertTrue(result.verification_passed)
            controller.run_task("Second independent task", workspace)
            self.assertEqual(len(list(log_root.glob("coding-harness-task-*.log"))), 2)
            self.assertEqual(logs[0].read_text(encoding="utf-8"), contents)

    def test_single_markdown_fenced_json_response_is_accepted_and_denials_log_raw_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            fenced = "```json\n" + json.dumps({"type": "final", "response": "Done."}) + "\n```"
            controller = AgentController(
                ScriptedModelClient(["I will help you.", fenced]),
                RepositoryTools(directory), Verification(PassingChecks()), task_log_directory=directory,
            )
            result = controller.run_task("Anything", directory)
            self.assertEqual(result.final_response, "Done.")
            self.assertEqual(result.counters.denied_actions, 1)
            self.assertIn("I will help you.", controller.task_log_path.read_text(encoding="utf-8"))

    def test_flat_edit_shape_is_normalized_to_a_validated_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            model = ScriptedModelClient([
                "```json\n" + json.dumps({"type": "edit", "path": "hello.py", "content": "x = 1\n"}) + "\n```",
                json.dumps({"type": "final", "response": "Done."}),
            ])
            controller = AgentController(
                model, RepositoryTools(workspace), Verification(PassingChecks()), task_log_directory=directory,
            )
            result = controller.run_task("Create hello.py", workspace)
            self.assertEqual(result.counters.denied_actions, 0)
            self.assertEqual(result.verification.changed_files, ("hello.py",))
            self.assertIn("+x = 1", result.verification.diff)

    def test_stopped_task_still_logs_diff_and_denial_teaches_tool_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            flat = json.dumps({"type": "edit", "path": "a.txt", "extra": "x"})
            edit = json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": "note.txt", "content": "kept"}})
            model = ScriptedModelClient([edit, flat, flat, flat])
            controller = AgentController(
                model, RepositoryTools(directory), Verification(PassingChecks()), task_log_directory=directory,
            )
            result = controller.run_task("Anything", directory)
            self.assertIsNotNone(result.stopped_reason)
            log = controller.task_log_path.read_text(encoding="utf-8")
            self.assertIn("+++ b/note.txt", log)
            self.assertIn("+kept", log)
            feedback = model.requests[2][-1]["content"]
            self.assertIn('{"type":"tool","tool":"edit","arguments"', feedback)

    def test_model_request_instructs_testing_when_behavior_is_testable(self):
        with tempfile.TemporaryDirectory() as directory:
            model = ScriptedModelClient([
                json.dumps({"type": "final", "response": "No code changes needed."}),
            ])

            AgentController(
                model, RepositoryTools(directory), Verification(PassingChecks()),
                task_log_directory=directory,
            ).run_task("Review this repository", directory)

            system_prompt = model.requests[0][0]["content"]
            self.assertIn("relevant regression tests", system_prompt)
            self.assertIn("requested behavior is testable", system_prompt)
            self.assertIn("testing is not applicable", system_prompt)

    def test_edit_result_returns_to_model_and_final_response_runs_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "note.txt").write_text("before", encoding="utf-8")
            model = ScriptedModelClient([
                json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": "note.txt", "content": "after"}}),
                json.dumps({"type": "final", "response": "Updated the note."}),
            ])
            checks = PassingChecks()
            controller = AgentController(model, RepositoryTools(workspace), Verification(checks))

            result = controller.run_task("Update the note", workspace)

            self.assertEqual((workspace / "note.txt").read_text(encoding="utf-8"), "after")
            self.assertIn("Tool result", json.dumps(model.requests[1]))
            self.assertIn("bytes_written", json.dumps(model.requests[1]))
            self.assertEqual(result.final_response, "Updated the note.")
            self.assertTrue(result.verification_passed)
            self.assertEqual(result.verification.changed_files, ("note.txt",))
            self.assertIn("-before", result.verification.diff)
            self.assertIn("+after", result.verification.diff)
            self.assertEqual(result.counters.actions, 1)
            self.assertEqual(result.counters.responses, 2)

    def test_each_task_starts_with_only_its_own_prompt(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            model = ScriptedModelClient([
                json.dumps({"type": "final", "response": "first"}),
                json.dumps({"type": "final", "response": "second"}),
            ])
            controller = AgentController(model, RepositoryTools(first), Verification(PassingChecks()))

            controller.run_task("first task", first)
            controller.run_task("second task", second)

            self.assertEqual(len(model.requests), 2)
            self.assertIn("first task", model.requests[0][1]["content"])
            self.assertNotIn("first task", json.dumps(model.requests[1]))
            self.assertIn("second task", model.requests[1][1]["content"])

    def test_invalid_and_unknown_actions_are_denied_without_execution_and_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            marker = workspace / "should-not-change.txt"
            marker.write_text("original", encoding="utf-8")
            model = ScriptedModelClient([
                '{"type":"tool","tool":"delete","arguments":{"path":"should-not-change.txt"}}',
                '{"type":"tool","tool":"edit","arguments":{"path":"should-not-change.txt","content":"bad","extra":1}}',
                '{"type":"tool","tool":"read","arguments":{"path":"../outside"}}',
                json.dumps({"type": "final", "response": "I could not make a safe change."}),
            ])
            controller = AgentController(model, RepositoryTools(workspace), Verification(PassingChecks()))

            result = controller.run_task("Keep the marker safe", workspace)

            self.assertEqual(marker.read_text(encoding="utf-8"), "original")
            self.assertEqual(result.counters.denied_actions, 3)
            self.assertEqual(result.counters.retries, 3)
            self.assertEqual(result.counters.responses, 3)
            self.assertFalse(result.verification_passed)
            self.assertIn("Retry limit reached", result.stopped_reason)

    def test_tool_and_response_limits_stop_the_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            model = ScriptedModelClient([
                json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": "file.txt", "content": "1"}}),
                json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": "file.txt", "content": "2"}}),
            ])
            result = AgentController(
                model, RepositoryTools(workspace), Verification(PassingChecks()),
                limits=RunLimits(actions=1, responses=4),
            ).run_task("Edit", workspace)
            self.assertEqual(result.counters.actions, 1)
            self.assertEqual(result.counters.responses, 2)
            self.assertIn("action limit", result.stopped_reason)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            model = ScriptedModelClient([
                json.dumps({"type": "tool", "tool": "edit", "arguments": {"path": "file.txt", "content": "1"}}),
            ])
            result = AgentController(
                model, RepositoryTools(workspace), Verification(PassingChecks()),
                limits=RunLimits(responses=1),
            ).run_task("Edit", workspace)
            self.assertEqual(result.counters.responses, 1)
            self.assertIn("response limit", result.stopped_reason)

    def test_unavailable_check_cannot_be_reported_as_passed(self):
        class UnavailableChecks:
            check_names = ("core",)

            def run_check(self, name, workspace):
                raise OSError("sandbox unavailable")

        with tempfile.TemporaryDirectory() as directory:
            model = ScriptedModelClient([json.dumps({"type": "final", "response": "Done."})])
            result = AgentController(
                model, RepositoryTools(directory), Verification(UnavailableChecks())
            ).run_task("Inspect", directory)
            self.assertFalse(result.verification_passed)
            self.assertTrue(result.verification.checks[0].blocked)
            self.assertIn("sandbox unavailable", result.verification.checks[0].error)

    def test_non_json_ambiguous_and_duplicate_json_responses_never_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "safe.txt"
            marker.write_text("safe", encoding="utf-8")
            model = ScriptedModelClient([
                "Here is a tool call.",
                '{"type":"final","response":"no"} {"type":"final","response":"also no"}',
                '{"type":"tool","tool":"edit","tool":"edit","arguments":{"path":"safe.txt","content":"bad"}}',
            ])
            result = AgentController(
                model, RepositoryTools(directory), Verification(PassingChecks()),
                limits=RunLimits(retries=3),
            ).run_task("Keep the file unchanged", directory)
            self.assertEqual(marker.read_text(encoding="utf-8"), "safe")
            self.assertEqual(result.counters.actions, 0)
            self.assertEqual(result.counters.denied_actions, 3)
            self.assertIn("Retry limit reached", result.stopped_reason)

    def test_failed_configured_check_overrules_model_completion_and_is_reported(self):
        class FailedChecks:
            check_names = ("core",)

            def run_check(self, name, workspace):
                return type("Check", (), {
                    "check_name": name, "exit_code": 7, "stdout": "failure output", "stderr": "",
                    "stdout_truncated": False, "stderr_truncated": False, "timed_out": False,
                    "blocked": False, "error": None, "passed": False,
                })()

        with tempfile.TemporaryDirectory() as directory:
            model = ScriptedModelClient([json.dumps({"type": "final", "response": "Everything passed."})])
            result = AgentController(model, RepositoryTools(directory), Verification(FailedChecks())).run_task(
                "Inspect", directory
            )
            self.assertEqual(result.final_response, "Everything passed.")
            self.assertFalse(result.verification_passed)
            self.assertEqual(result.verification.checks[0].exit_code, 7)
            self.assertIn("failure output", result.verification.checks[0].stdout)

    def test_reported_diff_stays_within_configured_byte_limit_when_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "note.txt").write_text("old\n", encoding="utf-8")
            model = ScriptedModelClient([
                json.dumps({"type": "tool", "tool": "edit", "arguments": {
                    "path": "note.txt", "content": "a substantially longer replacement\n",
                }}),
                json.dumps({"type": "final", "response": "Updated."}),
            ])
            result = AgentController(
                model,
                RepositoryTools(workspace),
                Verification(PassingChecks(), diff_limit_bytes=32),
            ).run_task("Update the note", workspace)

            self.assertTrue(result.verification.diff_truncated)
            self.assertLessEqual(len(result.verification.diff.encode("utf-8")), 32)
            self.assertIn("[diff truncated]", result.verification.diff)


class RepositoryToolTests(unittest.TestCase):
    def test_list_read_search_edit_are_confined_to_task_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside secret", encoding="utf-8")
            (workspace / "source.txt").write_text("needle in workspace", encoding="utf-8")
            tools = RepositoryTools(workspace)

            self.assertEqual(tools.read_file("source.txt")["content"], "needle in workspace")
            self.assertEqual(tools.search("needle")["matches"][0]["path"], "source.txt")
            self.assertEqual(tools.list_files()["entries"][0]["path"], "source.txt")
            tools.edit_file("source.txt", "changed")
            self.assertEqual((workspace / "source.txt").read_text(encoding="utf-8"), "changed")
            for operation in (
                lambda: tools.read_file("../outside.txt"),
                lambda: tools.edit_file("../outside.txt", "changed outside"),
                lambda: tools.read_file(str(outside)),
            ):
                with self.assertRaises(ValueError):
                    operation()
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside secret")

    def test_symlink_outside_workspace_is_not_listed_searched_or_accessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside secret", encoding="utf-8")
            (workspace / "escape.txt").symlink_to(outside)
            tools = RepositoryTools(workspace)
            self.assertEqual(tools.list_files()["entries"], [])
            self.assertEqual(tools.search("outside")["matches"], [])
            with self.assertRaises(ValueError):
                tools.read_file("escape.txt")
            with self.assertRaises(ValueError):
                tools.edit_file("escape.txt", "modified")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside secret")


class OllamaContractTests(unittest.TestCase):
    def test_chat_request_uses_non_streaming_ollama_api_contract(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen["path"] = self.path
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps({"message": {"content": '{"type":"final","response":"ok"}'}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = ModelClient(f"http://127.0.0.1:{server.server_port}", "test-model")
            answer = client.request([{"role": "user", "content": "task"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(answer, '{"type":"final","response":"ok"}')
        self.assertEqual(seen["path"], "/api/chat")
        self.assertEqual(seen["body"]["model"], "test-model")
        self.assertFalse(seen["body"]["stream"])
        self.assertEqual(seen["body"]["messages"], [{"role": "user", "content": "task"}])

    def test_model_client_rejects_nonlocal_endpoints(self):
        with self.assertRaises(ValueError):
            ModelClient("http://example.com:11434", "model")


class InteractiveCliTests(unittest.TestCase):
    def test_sequential_tasks_create_fresh_workspaces_and_model_contexts(self):
        class SuccessfulChecks(PassingChecks):
            check_names = ("core",)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            (repository / "original.txt").write_text("base", encoding="utf-8")
            workspaces = []

            def new_workspace(source):
                workspace = root / f"task-{len(workspaces) + 1}"
                shutil.copytree(source, workspace)
                workspaces.append(workspace)
                return workspace

            model = ScriptedModelClient([
                json.dumps({"type": "final", "response": "first finished"}),
                json.dumps({"type": "final", "response": "second finished"}),
            ])
            interface = UserInterface(
                model_client_factory=lambda: model,
                execution_environment_factory=SuccessfulChecks,
                workspace_factory=new_workspace,
            )
            output = io.StringIO()
            with patch("builtins.input", side_effect=["first task", "second task", "/quit"]), redirect_stdout(output):
                status = interface.run(["--repository", str(repository)])

            self.assertEqual(status, 0)
            self.assertEqual(len(workspaces), 2)
            self.assertNotEqual(workspaces[0], workspaces[1])
            self.assertIn("first task", model.requests[0][1]["content"])
            self.assertNotIn("first task", json.dumps(model.requests[1]))
            self.assertIn("second task", model.requests[1][1]["content"])
            self.assertIn("first finished", output.getvalue())
            self.assertIn("second finished", output.getvalue())
            self.assertEqual((repository / "original.txt").read_text(encoding="utf-8"), "base")


if __name__ == "__main__":
    unittest.main()
