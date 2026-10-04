"""Real-model demonstration runner.

1. Copies the target repository to a demo copy (the real target is never touched).
2. Proves the external acceptance check FAILS on a fresh sandboxed copy (abort otherwise).
3. Starts the normal harness on the demo copy; you type the task and use /approve or /reject.
4. Re-runs the acceptance check and the configured core check, each in the sandbox on a fresh copy
   of the result, and prints/writes a record (revision, task, scope, results, changed files, diff).

Run from the project root: python3 demo/run_demo.py
"""
from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coding_harness.cli import UserInterface  # noqa: E402
from coding_harness.execution import ExecutionEnvironment  # noqa: E402
from coding_harness.verification import Verification  # noqa: E402
from coding_harness.workspace import create_task_workspace  # noqa: E402

TARGET = ROOT / "target-repository"
ACCEPTANCE = Path(__file__).resolve().parent / "accept_quote.py"
TASK = "In quotes.py, make create_quote raise ValueError(\"Quote line quantity must be positive.\") when a line has a quantity of zero or less."
EXPECTED = ("A quote line with qty <= 0 raises ValueError and nothing is stored; "
            "positive quotes keep working; existing core tests still pass.")
SCOPE = ("quotes.py (required); files under tests/ (optional). "
         "No other files, no database or config changes.")
ALLOWED = ("quotes.py",)
ALLOWED_PREFIX = ("tests/",)
ACCEPTANCE_DEST = ".harness-acceptance/accept_quote.py"


def run_in_fresh_copy(environment: ExecutionEnvironment, repository: Path, check_name: str, with_acceptance: bool):
    workspace = create_task_workspace(repository)
    try:
        if with_acceptance:
            (workspace / ".harness-acceptance").mkdir()
            shutil.copyfile(ACCEPTANCE, workspace / ACCEPTANCE_DEST)
        return environment.run_check(check_name, workspace)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def status(check) -> str:
    if check.blocked:
        return "UNAVAILABLE (" + str(check.error) + ")"
    if check.timed_out:
        return "TIMED OUT"
    return ("PASS" if check.passed else "FAIL") + " (exit code " + str(check.exit_code) + ")"


def main() -> int:
    revision = subprocess.run(["git", "-C", str(TARGET), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip() or "(unknown)"
    environment = ExecutionEnvironment(checks={
        "core": (sys.executable, "tests/test_core.py"),
        "acceptance": (sys.executable, ACCEPTANCE_DEST),
    })
    demo_root = Path(tempfile.mkdtemp(prefix="coding-harness-demo-"))
    repository = demo_root / "openstock-demo"
    shutil.copytree(TARGET, repository, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "venv", "__pycache__", "_test.db*", "_accept.db*"))
    print("Demo copy of the target (real target untouched): " + str(repository))
    print("Starting revision: " + revision)
    print("Task to enter: " + TASK)
    print("Expected behavior: " + EXPECTED)
    print("Permitted scope: " + SCOPE + "\n")

    baseline = run_in_fresh_copy(environment, repository, "acceptance", True)
    print("Baseline acceptance check: " + status(baseline))
    print(baseline.stdout)
    if baseline.blocked or baseline.passed:
        print("ABORT: the acceptance check must run and FAIL before the model runs.")
        shutil.rmtree(demo_root, ignore_errors=True)
        return 2

    verifier = Verification(environment)
    snapshot = verifier.capture_baseline(repository)
    print("Starting the harness. Enter the task above, review the diff, then /approve (or /reject) and /quit.\n")
    UserInterface().run(["--repository", str(repository)])

    final_acceptance = run_in_fresh_copy(environment, repository, "acceptance", True)
    final_core = run_in_fresh_copy(environment, repository, "core", False)
    changed, diff, truncated = verifier.diff(repository, snapshot)
    in_scope = all(name in ALLOWED or name.startswith(ALLOWED_PREFIX) for name in changed)
    success = bool(changed) and final_acceptance.passed and final_core.passed and in_scope

    summary = [
        "# Demonstration record",
        "- Date: " + datetime.datetime.now().isoformat(timespec="seconds"),
        "- Target and starting revision: OpenStock `" + revision + "`",
        "- Task: " + TASK,
        "- Expected behavior: " + EXPECTED,
        "- Permitted scope: " + SCOPE,
        "- Acceptance check: `demo/accept_quote.py` (outside the workspace; copied in only for each run)",
        "- Baseline acceptance (before model): " + status(baseline),
        "- Final acceptance (after model): " + status(final_acceptance),
        "- Configured regression check (core): " + status(final_core),
        "- Changed files: " + (", ".join(changed) or "(none)") + ("" if in_scope else " [OUT OF SCOPE]"),
        "- Manual setup/help: none by the harness; the existing local OpenStock database was used.",
        "- Demonstration verdict: " + ("SUCCESS" if success else "NOT SUCCESSFUL"),
    ]
    details = [
        "", "## Final acceptance output", "```", final_acceptance.stdout.rstrip(), "```",
        "## Core check output", "```", final_core.stdout.rstrip(), "```",
        "## Diff" + (" (truncated)" if truncated else ""), "```diff", diff.rstrip(), "```",
    ]
    record = ROOT / ("demo-record-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md")
    record.write_text("\n".join(summary + details) + "\n", encoding="utf-8")
    print("\n".join(summary))
    print("\nFull record written to " + str(record))
    shutil.rmtree(demo_root, ignore_errors=True)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
