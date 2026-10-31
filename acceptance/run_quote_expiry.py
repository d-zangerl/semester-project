"""Delivers quote expiry with a real model, on a disposable clone, against the protected check.

1. Clones the target at its recorded commit; the original target repository is never touched.
2. Proves the feature check fails on the starting code for the expected reason, or stops.
3. Runs the harness from one unsplit request.
4. Runs the acceptance and core checks on a copy of the result, and writes a record.

Run from the project root: .venv/bin/python acceptance/run_quote_expiry.py
Use --prove-only to stop after step 2, needing no model.
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.coding_harness.core import TaskCore  # noqa: E402
from src.coding_harness.execution import ExecutionEnvironment  # noqa: E402
from src.coding_harness.model import client_from_environment  # noqa: E402
from src.coding_harness.projects import Project, load_projects  # noqa: E402

CHECK_DIRECTORY = ROOT / "acceptance" / "quote_expiry"
REQUEST = (
    "Add optional expiry to customer quotes in OpenStock. The valid_until value of a quote is an optional ISO date "
    "(YYYY-MM-DD). Creating a quote with a valid_until that is not a real ISO date, or that is before today, must "
    "raise ValueError with a clear message and store nothing; today and later are accepted, and no valid_until "
    "behaves as it does today. Every quote returned by get_quote and get_quotes must have a boolean 'expired' field: "
    "true only when its valid_until is before today. The quote creation API must answer an invalid date with HTTP "
    "400 and ok=false. GET /api/quotes must keep returning all quotes by default, and with the query parameter "
    "active=1 must leave out expired quotes. Find the relevant modules yourself, and keep existing callers working."
)
ACCEPTANCE = {"acceptance": ("python", "/acceptance/accept.py")}


def run_acceptance(workspace: Path, directory: Path, core_checks) -> tuple:
    """Run on a copy, so check artifacts cannot enter the result."""
    copy = directory / f"check-{datetime.datetime.now().strftime('%H%M%S%f')}"
    shutil.copytree(workspace, copy)
    copy.chmod(0o777)
    environment = ExecutionEnvironment(checks={**ACCEPTANCE, **core_checks},
                                       read_only_mounts={str(CHECK_DIRECTORY): "/acceptance"})
    return tuple(environment.run_check(name, copy) for name in environment.check_names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prove-only", action="store_true")
    options = parser.parse_args()
    target = load_projects(ROOT / "projects.toml")["openstock"]
    state = ROOT / ".harness"
    state.mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="quote-expiry-", dir=state))
    clone = base / "clone"
    subprocess.run(["git", "clone", "-q", str(target.path), str(clone)], check=True)
    commit = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], check=True, capture_output=True,
                            text=True).stdout.strip()
    for fixture in target.fixtures:
        (clone / fixture).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target.path / fixture, clone / fixture)
    project = Project(name="openstock-quote-expiry", path=clone, checks=target.checks,
                      allowed_changes=target.allowed_changes, excluded_paths=target.excluded_paths,
                      fixtures=target.fixtures, generated_files=target.generated_files)
    core = TaskCore(model_client=None if options.prove_only else client_from_environment(),
                    projects={project.name: project}, state_directory=base / "state")

    print(f"Target {target.path} at {commit}\nDisposable clone: {clone}")
    from src.coding_harness.workspace import populate_workspace
    untouched = base / "untouched"
    populate_workspace(project, untouched, commit=commit)
    proof = run_acceptance(untouched, base, {})[0]
    print(proof.stdout, proof.stderr)
    if proof.blocked or proof.passed or "FEATURE FAILED" not in proof.stdout or "REGRESSION PASSED" not in proof.stdout:
        print("STOP: the feature check must fail on the starting code, with regression checks passing.")
        return 1
    print("Proven: the feature check fails on the starting code for the expected reason.")
    if options.prove_only:
        return 0

    started = core.start(project.name, REQUEST, progress=lambda message: print(f"[progress] {message}", flush=True))
    saved = core.show(started.task_id)
    results = run_acceptance(started.workspace, base, target.checks)
    passed = all(check.passed for check in results)
    record = base / "record.md"
    lines = [f"# Quote expiry run: {'PASSED' if passed else 'NOT PASSED'}", "", f"- Target commit: {commit}",
             f"- Model: {core.model_client.model}", f"- Task: {saved.task_id}, outcome {saved.state}",
             f"- Request: {REQUEST}", f"- Allowed changes: {', '.join(project.allowed_changes)}",
             f"- Commands: {ACCEPTANCE}, {dict(target.checks)}",
             f"- Reason, if stopped: {saved.reason or '(none)'}", f"- Changed files: {', '.join(saved.changed_files)}",
             "- Manual help: none during this run; record any here.", "", "## Results", ""]
    for check in results:
        lines += [f"### {check.check_name}: {'PASS' if check.passed else 'NOT PASSED'} "
                  f"(exit {check.exit_code}) {check.error or ''}", "", "```", check.stdout, check.stderr, "```", ""]
    lines += ["## Diff", "", "```diff", saved.diff, "```"]
    record.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Record: {record}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
