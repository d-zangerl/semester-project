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
DEMOS = {
    "quote": {
        "acceptance": "accept_quote.py",
        "task": "In quotes.py, make create_quote raise ValueError(\"Quote line quantity must be positive.\") when a line has a quantity of zero or less.",
        "expected": ("A quote line with qty <= 0 raises ValueError and nothing is stored; "
                     "positive quotes keep working; existing core tests still pass."),
        "scope": "quotes.py (required); files under tests/ (optional). No other files, no database or config changes.",
        "allowed": ("quotes.py",),
    },
    "delete-quote": {
        "acceptance": "accept_delete_quote.py",
        "tasks": (
            ("Edit only quotes.py. Use the edit old/new mode to replace the exact existing "
             "`delete_quote(no)` function with this behavior: filter out quotes whose `no` matches; "
             "return True and save only if the list became shorter; otherwise return False without saving. "
             "Copy the old function exactly from the read result. Do not rewrite any other part of the file."),
            ("Edit only app.py, inside the existing api_quote_delete(no) function for DELETE "
             "`/api/quote/<path:no>`. Use function edit mode to replace only `api_quote_delete` with "
             "exactly this function content, preserving its permission and error handling:\n"
             "def api_quote_delete(no):\n"
             "    _, err = _check(\"quotes\")\n"
             "    if err:\n"
             "        return err\n"
             "    try:\n"
             "        if not quotes.delete_quote(no):\n"
             "            return jsonify({\"ok\": False, \"error\": \"Quote not found.\"}), 404\n"
             "        return jsonify({\"ok\": True})\n"
             "    except Exception as e:\n"
             "        return jsonify({\"ok\": False, \"error\": str(e)}), 500\n"
             "Do not include the route decorator in function_content; the tool preserves it."),
        ),
        "expected": ("Deleting an existing quote returns success and removes it; deleting a missing quote "
                     "returns false from quotes.delete_quote() and the API returns HTTP 404 with ok=false."),
        "scope": "quotes.py and app.py (required); files under tests/ (optional). No other files.",
        "allowed": ("quotes.py", "app.py"),
    },
    "transfer": {
        "acceptance": "accept_transfer.py",
        "task": ("In operations.py, inside _transfer, raise OperationError(\"Quantity must be positive.\") "
                 "right after the line qty = float(e[\"qty\"]) when qty is zero or less."),
        "expected": ("A transfer line with qty <= 0 raises OperationError and changes nothing; "
                     "positive transfers keep working; existing core tests still pass."),
        "scope": ("operations.py (required); app.py and files under tests/ (optional). "
                  "No other files, no database or config changes."),
        "allowed": ("operations.py", "app.py"),
    },
}
DEMO = DEMOS[sys.argv[1] if len(sys.argv) > 1 else "quote"]
ACCEPTANCE = Path(__file__).resolve().parent / DEMO["acceptance"]
TASKS = DEMO["tasks"] if "tasks" in DEMO else (DEMO["task"],)
TASK, EXPECTED, SCOPE, ALLOWED = "\nTHEN\n".join(TASKS), DEMO["expected"], DEMO["scope"], DEMO["allowed"]
ALLOWED_PREFIX = ("tests/",)
ACCEPTANCE_DEST = ".harness-acceptance/" + DEMO["acceptance"]


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
    print("Task(s) to enter and approve in order:")
    for index, task in enumerate(TASKS, 1):
        print(f"{index}. {task}")
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
        "- Acceptance check: `demo/" + DEMO["acceptance"] + "` (outside the workspace; copied in only for each run)",
        "- Baseline acceptance (before model): " + status(baseline),
        "- Final acceptance (after model): " + status(final_acceptance),
        "- Configured regression check (core): " + status(final_core),
        "- Changed files: " + (", ".join(changed) or "(none)") + ("" if in_scope else " [OUT OF SCOPE]"),
        "- Manual setup/help: none by the harness; the existing local OpenStock database was used.",
        "- Demonstration verdict: " + ("SUCCESS" if success else "NOT SUCCESSFUL"),
    ]
    details = [
        "", "## Final acceptance output", "```", final_acceptance.stdout.rstrip(), "```",
        "## Final acceptance errors", "```", final_acceptance.stderr.rstrip(), "```",
        "## Core check output", "```", final_core.stdout.rstrip(), "```",
        "## Core check errors", "```", final_core.stderr.rstrip(), "```",
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
