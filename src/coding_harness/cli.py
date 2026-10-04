from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .execution import CheckResult, ExecutionEnvironment
from .workspace import create_task_workspace


class UserInterface:
    def run(self, arguments: list[str] | None = None) -> int:
        project_root = Path(__file__).resolve().parents[2]
        default_repository = os.environ.get(
            "CODING_HARNESS_REPOSITORY",
            str(project_root / "target-repository"),
        )
        parser = argparse.ArgumentParser(description="Run a configured repository check in a contained task copy.")
        parser.add_argument(
            "--repository",
            default=default_repository,
            help="Target repository path (default: CODING_HARNESS_REPOSITORY or ./target-repository).",
        )
        options = parser.parse_args(arguments)

        try:
            task = input("Task: ").strip()
        except EOFError:
            print("No task was entered.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nTask entry cancelled.", file=sys.stderr)
            return 130
        if not task:
            print("A task description is required.", file=sys.stderr)
            return 1

        try:
            workspace = create_task_workspace(options.repository)
        except (OSError, ValueError) as error:
            print(f"Cannot create task workspace: {error}", file=sys.stderr)
            return 1

        print(f"Task captured: {task}")
        print(f"Task workspace: {workspace}")
        print("Running configured core check in the OS-enforced sandbox...")
        try:
            result = ExecutionEnvironment().run_check("core", workspace)
        except KeyboardInterrupt:
            print("\nCheck stopped; task workspace retained for diagnosis.")
            print(f"Task workspace: {workspace}")
            return 130

        self._show_result(result)
        if result.passed:
            shutil.rmtree(workspace)
            print("Configured core check passed; task workspace removed.")
            return 0

        print("Configured core check did not pass; task workspace retained for diagnosis.")
        print(f"Task workspace: {workspace}")
        return 1

    @staticmethod
    def _show_result(result: CheckResult) -> None:
        if result.blocked:
            print(f"BLOCKED: {result.error}")
        elif result.timed_out:
            print(f"TIMED OUT after {result.duration_seconds:.1f}s")
        else:
            state = "PASS" if result.passed else "FAIL"
            print(f"{state}: configured check {result.check_name!r}, exit code {result.exit_code}")
        if result.stdout:
            print("stdout:")
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stdout_truncated:
            print("[stdout truncated]")
        if result.stderr:
            print("stderr:")
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.stderr_truncated:
            print("[stderr truncated]")


def main(arguments: list[str] | None = None) -> int:
    return UserInterface().run(arguments)
