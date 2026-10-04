from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agent import AgentController
from .execution import ExecutionEnvironment
from .model import ModelClient
from .repository import RepositoryTools
from .verification import Verification
from .workspace import create_task_workspace


class UserInterface:
    def __init__(self, *, model_client_factory=None, execution_environment_factory=None,
                 workspace_factory=create_task_workspace):
        self.model_client_factory = model_client_factory or self._model_client
        self.execution_environment_factory = execution_environment_factory or ExecutionEnvironment
        self.workspace_factory = workspace_factory

    def run(self, arguments: list[str] | None = None) -> int:
        project_root = Path(__file__).resolve().parents[2]
        default_repository = os.environ.get("CODING_HARNESS_REPOSITORY", str(project_root / "target-repository"))
        parser = argparse.ArgumentParser(description="Run independent coding tasks in disposable repository copies.")
        parser.add_argument("--repository", default=default_repository,
                            help="Target repository path (default: CODING_HARNESS_REPOSITORY or ./target-repository).")
        options = parser.parse_args(arguments)
        repository = Path(options.repository).expanduser()
        if not repository.is_dir():
            print(f"Configured repository is not a directory: {repository}", file=sys.stderr)
            return 1
        try:
            model = self.model_client_factory()
        except (OSError, ValueError) as error:
            print(f"Cannot configure model client: {error}", file=sys.stderr)
            return 1

        print(f"Coding harness ready for {repository.resolve()}.")
        print("Enter a task, /help for controls, or /quit to exit.")
        failed = False
        while True:
            try:
                task = input("Task> ").strip()
            except EOFError:
                print("\nEnd of input; exiting.")
                return 1 if failed else 0
            except KeyboardInterrupt:
                print("\nTask entry cancelled.")
                return 130
            if task == "/quit":
                return 1 if failed else 0
            if task == "/help":
                self._show_help()
                continue
            if not task:
                continue
            try:
                workspace = self.workspace_factory(repository)
                print(f"Task workspace: {workspace}")
                environment = self.execution_environment_factory()
                controller = AgentController(
                    model,
                    RepositoryTools(workspace),
                    Verification(environment),
                    progress=lambda message: print(f"[progress] {message}"),
                    task_log_directory=project_root,
                )
                result = controller.run_task(task, workspace)
            except KeyboardInterrupt:
                print("\nTask interrupted; workspace retained for diagnosis.")
                return 130
            except (OSError, ValueError, RuntimeError) as error:
                failed = True
                print(f"Task could not complete: {error}")
                continue
            self._show_result(result, workspace)
            if result.stopped_reason or not result.verification_passed:
                failed = True

    @staticmethod
    def _model_client() -> ModelClient:
        endpoint = os.environ.get("CODING_HARNESS_OLLAMA_ENDPOINT", "http://localhost:11434")
        model = os.environ.get("CODING_HARNESS_OLLAMA_MODEL", "qwen2.5-coder:7b")
        return ModelClient(endpoint, model)

    @staticmethod
    def _show_help() -> None:
        print("Enter a coding task to start a fresh run. /help shows this text; /quit exits.")
        print("Review the proposed diff manually. This delivery never applies changes to the configured repository.")

    @staticmethod
    def _show_result(result, workspace: Path) -> None:
        print(f"Final response: {result.final_response or '(no final response)'}")
        if result.stopped_reason:
            print(f"STOPPED: {result.stopped_reason}")
        counts = result.counters
        print(f"Counters: actions={counts.actions}, denied={counts.denied_actions}, "
              f"retries={counts.retries}, responses={counts.responses}")
        if result.verification is None:
            print("Verification: unavailable (the model did not complete the task).")
        else:
            verification = result.verification
            print("Changed files:")
            if verification.changed_files:
                for path in verification.changed_files:
                    print(f"  {path}")
            else:
                print("  (none)")
            print("Diff:")
            print(verification.diff or "(no textual diff)")
            print("Configured checks:")
            for check in verification.checks:
                if check.blocked:
                    status = f"UNAVAILABLE: {check.error or 'check could not run'}"
                elif check.timed_out:
                    status = "TIMED OUT"
                else:
                    status = f"{'PASS' if check.passed else 'FAIL'} (exit code {check.exit_code})"
                print(f"  {check.check_name}: {status}")
                if check.stdout:
                    print("  stdout:")
                    print("    " + check.stdout.rstrip().replace("\n", "\n    "))
                if check.stdout_truncated:
                    print("  [stdout truncated]")
                if check.stderr:
                    print("  stderr:")
                    print("    " + check.stderr.rstrip().replace("\n", "\n    "))
                if check.stderr_truncated:
                    print("  [stderr truncated]")
            if not verification.passed:
                print("Verification did not pass; the model's completion claim is not authoritative.")
        print(f"Review workspace retained at: {workspace}")


def main(arguments: list[str] | None = None) -> int:
    return UserInterface().run(arguments)
