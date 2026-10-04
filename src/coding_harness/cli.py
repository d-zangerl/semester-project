from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .agent import AgentController
from .execution import ExecutionEnvironment
from .model import ModelClient
from .repository import RepositoryTools
from .review import apply_changes, target_mismatches
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
            if result.verification is not None and result.verification.changed_files:
                try:
                    outcome = self._review(result, workspace, repository, environment)
                except EOFError:
                    print("\nEnd of input during review; nothing was applied.")
                    print(f"Task workspace retained at: {workspace}")
                    return 1
                except KeyboardInterrupt:
                    print("\nReview cancelled; nothing was applied.")
                    print(f"Task workspace retained at: {workspace}")
                    return 130
                except (OSError, ValueError) as error:
                    print(f"Applying the change failed: {error}")
                    print(f"Task workspace retained at: {workspace}")
                    outcome = False
                if not outcome:
                    failed = True
            else:
                print(f"No changes to review. Task workspace retained at: {workspace}")

    def _review(self, result, workspace: Path, repository: Path, environment) -> bool:
        """Returns True when the review ended without a failed or unavailable check."""
        verification = result.verification
        print("Review: /approve applies the changes to the configured repository, /reject discards them, "
              "/diff shows the result again.")
        while True:
            decision = input("Review> ").strip()
            if decision == "/diff":
                self._show_result(result, workspace, announce_workspace=False)
            elif decision == "/reject":
                print("Rejected: the configured repository was not changed.")
                if verification.passed:
                    shutil.rmtree(workspace, ignore_errors=True)
                    print("Task workspace removed.")
                    return True
                print(f"Task workspace retained for diagnosis at: {workspace}")
                return False
            elif decision == "/approve":
                return self._approve(result, workspace, repository, environment)
            else:
                print("Enter /approve, /reject, or /diff.")

    def _approve(self, result, workspace: Path, repository: Path, environment) -> bool:
        verification = result.verification
        checker = Verification(environment)
        mismatched = target_mismatches(checker, repository, result.baseline or {})
        if mismatched:
            print("WARNING: the configured repository changed since this task started. "
                  "Approval force-applies the task's files over the current content. Differing files:")
            for name in mismatched:
                print(f"  {name}")
        if not verification.passed:
            print("WARNING: the task's configured checks did not pass.")
        applied = apply_changes(repository, workspace, verification.changed_files)
        print(f"Applied {applied} file(s) to {repository.resolve()}.")
        fresh = self.workspace_factory(repository)
        print(f"Post-apply check workspace: {fresh}")
        post = checker.verify(fresh, checker.capture_baseline(fresh))
        for check in post.checks:
            print(f"Post-apply check {check.check_name}: {self._check_status(check)}")
            self._print_check_output(check)
        if post.passed and verification.passed:
            shutil.rmtree(fresh, ignore_errors=True)
            shutil.rmtree(workspace, ignore_errors=True)
            print("Post-apply verification passed; task workspaces removed.")
            return True
        if post.passed:
            shutil.rmtree(fresh, ignore_errors=True)
            print("Post-apply verification passed.")
        else:
            print("Post-apply verification did not pass or was unavailable.")
            print(f"Post-apply workspace retained at: {fresh}")
        print(f"Task workspace retained at: {workspace}")
        return post.passed and verification.passed

    @staticmethod
    def _check_status(check) -> str:
        if check.blocked:
            return f"UNAVAILABLE: {check.error or 'check could not run'}"
        if check.timed_out:
            return "TIMED OUT"
        return f"{'PASS' if check.passed else 'FAIL'} (exit code {check.exit_code})"

    @staticmethod
    def _print_check_output(check) -> None:
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

    @staticmethod
    def _model_client() -> ModelClient:
        endpoint = os.environ.get("CODING_HARNESS_OLLAMA_ENDPOINT", "http://localhost:11434")
        model = os.environ.get("CODING_HARNESS_OLLAMA_MODEL", "qwen2.5-coder:7b")
        return ModelClient(endpoint, model)

    @staticmethod
    def _show_help() -> None:
        print("Enter a coding task to start a fresh run. /help shows this text; /quit exits.")
        print("After a task with changes: /approve applies them to the configured repository, /reject discards them, /diff repeats the result.")

    @staticmethod
    def _show_result(result, workspace: Path, announce_workspace: bool = True) -> None:
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
                print(f"  {check.check_name}: {UserInterface._check_status(check)}")
                UserInterface._print_check_output(check)
            if not verification.passed:
                print("Verification did not pass; the model's completion claim is not authoritative.")
        if announce_workspace:
            print(f"Task workspace: {workspace}")


def main(arguments: list[str] | None = None) -> int:
    return UserInterface().run(arguments)
