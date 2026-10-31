from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import ApprovalOutcome, SavedTask, TaskCore, UnknownProjectError, UnknownTaskError
from .execution import CheckResult
from .model import client_from_environment
from .projects import load_projects

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTCOME_EXIT_CODES = {"completed": 0, "failed": 1, "paused": 2, "cancelled": 130}


def default_core(*, with_model: bool = True) -> TaskCore:
    return TaskCore(model_client=client_from_environment() if with_model else None,
                    projects=load_projects(PROJECT_ROOT / "projects.toml"),
                    state_directory=PROJECT_ROOT / ".harness",
                    task_log_directory=PROJECT_ROOT / "logs")


def check_status(check: CheckResult) -> str:
    if check.blocked:
        return f"UNAVAILABLE: {check.error or 'check could not run'}"
    if check.timed_out:
        return "TIMED OUT"
    return f"{'PASS' if check.passed else 'FAIL'} (exit code {check.exit_code})"


def format_checks(checks) -> list[str]:
    lines = []
    if not checks:
        return ["  (no check results)"]
    for check in checks:
        lines.append(f"  {check.check_name}: {check_status(check)}")
        for name, text, truncated in (("stdout", check.stdout, check.stdout_truncated),
                                      ("stderr", check.stderr, check.stderr_truncated)):
            if text:
                lines.append(f"    {name}:")
                lines.append("      " + text.rstrip().replace("\n", "\n      "))
            if truncated:
                lines.append(f"    [{name} truncated]")
    return lines


def format_counters(task: SavedTask) -> str:
    counters, limits = task.counters, task.limits
    tokens = f"{counters.tokens}{' (estimated)' if counters.tokens_estimated else ''}/{limits.tokens}"
    return (f"actions {counters.actions}/{limits.actions}, responses {counters.responses}/{limits.responses}, "
            f"fix attempts {counters.fix_attempts}/{limits.fix_attempts}, denied {counters.denied_actions}, "
            f"tokens {tokens}")


def format_task(task: SavedTask, *, steps: bool = True) -> str:
    lines = [f"Task {task.task_id} [{task.state}] on {task.project}",
             f"Request: {task.request}",
             f"Starting commit: {task.start_commit or '(not a Git repository)'}",
             f"Allowed changes: {', '.join(task.allowed_changes)}",
             f"Runs: {task.runs}. Used: {format_counters(task)}"]
    if task.review_decision:
        lines.append(f"Review: {task.review_decision}")
    if steps:
        lines.append("Steps:")
        for step in task.steps:
            state = "denied" if step.denied else step.status
            lines.append(f"  {step.tool} {step.arguments if len(str(step.arguments)) < 120 else '...'}: {state}")
        if not task.steps:
            lines.append("  (none)")
        if task.errors:
            lines.append("Errors:")
            lines.extend(f"  {error}" for error in task.errors)
    if task.final_response:
        suffix = "" if task.state == "completed" else " (the model's claim, not verified as complete)"
        lines.append(f"Final response{suffix}: {task.final_response}")
    if task.unfinished:
        lines.append(f"Unfinished: {task.unfinished}")
    lines.append("Changed files:")
    lines.extend(f"  {name}" for name in task.changed_files)
    if not task.changed_files:
        lines.append("  (none)")
    lines.append("Checks:")
    lines.extend(format_checks(task.checks))
    lines.append("Diff:")
    lines.append(task.diff or "(no textual diff)")
    return "\n".join(lines)


def format_approval(outcome: ApprovalOutcome) -> str:
    if outcome.blocked_by:
        return "\n".join(["Approval blocked; nothing was applied. Differences:",
                          *(f"  {difference}" for difference in outcome.blocked_by),
                          "Use --force to apply anyway."])
    lines = [f"Applied: {', '.join(outcome.applied)}", "Post-apply checks:", *format_checks(outcome.post_checks)]
    if not outcome.passed and outcome.post_workspace:
        lines.append(f"Post-apply checks did not pass; workspace kept at {outcome.post_workspace}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Run durable coding tasks on allowed projects. "
                                                                 "With no command, opens the interactive interface.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("projects", help="List allowed projects.")
    start = commands.add_parser("start", help="Start a task; Ctrl-C cancels it.")
    start.add_argument("project")
    start.add_argument("request")
    commands.add_parser("list", help="List tasks and their states.")
    show = commands.add_parser("show", help="Show a task's details, steps, checks, and diff.")
    show.add_argument("task")
    cancel = commands.add_parser("cancel", help="Cancel a task's active run.")
    cancel.add_argument("task")
    resume = commands.add_parser("resume", help="Resume a task from a trusted state.")
    resume.add_argument("task")
    choice = resume.add_mutually_exclusive_group()
    choice.add_argument("--discard-to-checkpoint", action="store_true")
    choice.add_argument("--accept-current-state", action="store_true")
    follow_up = commands.add_parser("continue", help="Give an unapproved task a follow-up instruction.")
    follow_up.add_argument("task")
    follow_up.add_argument("instruction")
    review = commands.add_parser("review", help="Show a result, then optionally approve or reject it.")
    review.add_argument("task")
    decision = review.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--force", action="store_true", help="Approve even if the target has changed.")
    return parser


def _progress(message: str) -> None:
    print(f"[progress] {message}", flush=True)


def _finish(core, started) -> int:
    print(format_task(core.show(started.task_id), steps=False))
    return OUTCOME_EXIT_CODES.get(started.result.outcome, 1)


def main(arguments: list[str] | None = None, *, core_factory=default_core) -> int:
    options = _parser().parse_args(arguments)
    if options.command is None:
        from .interactive import run_interactive
        return run_interactive(core_factory)
    try:
        needs_model = options.command in {"start", "resume", "continue"}
        core = core_factory(with_model=needs_model)
        if options.command == "projects":
            for name, project in sorted(core.projects.items()):
                print(f"{name}: {project.path}")
            return 0
        if options.command == "start":
            return _finish(core, core.start(options.project, options.request, progress=_progress))
        if options.command == "list":
            tasks = core.list_tasks()
            for task in tasks:
                print(f"{task.task_id}  {task.state:<12} {task.project:<12} {task.request[:70]}")
            if not tasks:
                print("No tasks yet.")
            return 0
        if options.command == "show":
            print(format_task(core.show(options.task)))
            return 0
        if options.command == "cancel":
            if core.cancel(options.task):
                print(f"Cancelling task {options.task}.")
                return 0
            print(f"Task {options.task} has no active run.")
            return 1
        if options.command == "resume":
            return _finish(core, core.resume(options.task, discard_to_checkpoint=options.discard_to_checkpoint,
                                             accept_current_state=options.accept_current_state, progress=_progress))
        if options.command == "continue":
            return _finish(core, core.continue_task(options.task, options.instruction, progress=_progress))
        if options.approve:
            outcome = core.approve(options.task, force=options.force)
            print(format_approval(outcome))
            return 0 if outcome.passed else 1
        if options.reject:
            core.reject(options.task)
            print(f"Rejected task {options.task}; the target was not changed.")
            return 0
        print(format_task(core.review(options.task)))
        return 0
    except (UnknownProjectError, UnknownTaskError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
