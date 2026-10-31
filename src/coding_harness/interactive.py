from __future__ import annotations

import signal
import threading
from typing import Callable

from .cli import format_approval, format_checks, format_task
from .core import UnknownProjectError, UnknownTaskError

HELP = """Type a request to start a new task on the current project.
/project <name>        choose the allowed project
/tasks                 list tasks
/show <id>             show a task
/diff [id]             show changed files, checks, and the diff
/resume <id> [--discard-to-checkpoint|--accept-current-state]
/continue <instruction>   follow up on the current unapproved task
/cancel [id]           cancel a run (Esc also cancels)
/approve [--force]     apply the current task's result to the target
/reject                discard the current task's result
/quit                  leave"""


class InteractiveSession:
    """Routes typed lines to the task core. Holds what is on screen, and no task logic."""

    def __init__(self, core, write: Callable[[str], None] = print):
        self.core = core
        self.write = write
        self.project = sorted(core.projects)[0] if core.projects else None
        self.current_task: str | None = None
        self._worker: threading.Thread | None = None
        self.finished = False

    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def wait(self) -> None:
        if self._worker:
            self._worker.join()

    def handle_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        try:
            if text.startswith("/"):
                command, _, argument = text.partition(" ")
                handler = self._commands().get(command)
                if handler is None:
                    self.write(f"Unknown command {command}. Type /help.")
                else:
                    handler(argument.strip())
            else:
                self._start(text)
        except (UnknownProjectError, UnknownTaskError, ValueError, OSError) as error:
            self.write(f"Error: {error}")

    def _commands(self) -> dict[str, Callable[[str], None]]:
        return {"/help": lambda _: self.write(HELP), "/quit": self._quit, "/project": self._choose_project,
                "/tasks": self._tasks, "/show": self._show, "/diff": self._diff, "/resume": self._resume,
                "/continue": self._continue, "/cancel": self._cancel, "/approve": self._approve,
                "/reject": self._reject}

    def _quit(self, _: str) -> None:
        if self.running:
            self.write("A task is running; cancel it first with /cancel or Esc.")
            return
        self.finished = True

    def _choose_project(self, name: str) -> None:
        if name not in self.core.projects:
            raise UnknownProjectError(f"{name!r} is not an allowed project. "
                                      f"Allowed: {', '.join(sorted(self.core.projects))}.")
        self.project = name
        self.write(f"Project: {name}")

    def _tasks(self, _: str) -> None:
        tasks = self.core.list_tasks()
        for task in tasks:
            self.write(f"{task.task_id}  {task.state:<12} {task.project:<12} {task.request[:60]}")
        if not tasks:
            self.write("No tasks yet.")

    def _task_id(self, argument: str) -> str:
        task_id = argument or self.current_task
        if not task_id:
            raise ValueError("No current task; give a task ID.")
        return task_id

    def _show(self, argument: str) -> None:
        self.write(format_task(self.core.show(self._task_id(argument))))

    def _diff(self, argument: str) -> None:
        task = self.core.review(self._task_id(argument))
        self.write("\n".join(["Changed files: " + (", ".join(task.changed_files) or "(none)"), "Checks:",
                              *format_checks(task.checks), task.diff or "(no textual diff)"]))

    def _in_background(self, work: Callable[[], object]) -> None:
        if self.running:
            self.write("A task is already running; one task runs at a time.")
            return

        def run():
            try:
                started = work()
            except (UnknownProjectError, UnknownTaskError, ValueError, OSError) as error:
                self.write(f"Error: {error}")
                return
            self.current_task = started.task_id
            self._report(started.task_id)

        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _report(self, task_id: str) -> None:
        task = self.core.show(task_id)
        self.write(f"Task {task_id}: {task.state}")
        if task.unfinished:
            self.write(f"Unfinished: {task.unfinished}")
        self.write("\n".join(["Changed files: " + (", ".join(task.changed_files) or "(none)"), "Checks:",
                              *format_checks(task.checks)]))
        self.write("Use /diff, then /approve or /reject.")

    def _progress(self, message: str) -> None:
        if message.startswith("Task ") and " workspace: " in message:
            self.current_task = message.split()[1]
        if not message.startswith(("Requesting model response", "Task log:", "Task started:")):
            self.write(f"● {message}")

    def _start(self, request: str) -> None:
        if self.project is None:
            raise ValueError("No allowed projects are configured.")
        if self.running:
            self.write("A task is already running; one task runs at a time.")
            return
        unreviewed = [task.task_id for task in self.core.list_tasks() if self._awaits_review(task)]
        if unreviewed:
            self.write(f"Warning: unreviewed task(s) remain: {', '.join(unreviewed)}. This request starts a new "
                       "task from the target, without their changes.")
        self._in_background(lambda: self.core.start(self.project, request, progress=self._progress))

    @staticmethod
    def _awaits_review(task) -> bool:
        edited = any(step.tool == "edit" and not step.denied for step in task.steps)
        return edited and not task.review_decision and task.state in {"completed", "failed", "paused"}

    def _resume(self, argument: str) -> None:
        parts = argument.split()
        options = {"--discard-to-checkpoint": "discard_to_checkpoint", "--accept-current-state": "accept_current_state"}
        choices = {options[part]: True for part in parts if part in options}
        task_ids = [part for part in parts if part not in options]
        task_id = self._task_id(task_ids[0] if task_ids else "")
        self.core.show(task_id, include_diff=False)
        self.current_task = task_id
        self._in_background(lambda: self.core.resume(task_id, progress=self._progress, **choices))

    def _continue(self, instruction: str) -> None:
        if not instruction:
            raise ValueError("Usage: /continue <instruction>")
        task_id = self._task_id("")
        self._in_background(lambda: self.core.continue_task(task_id, instruction, progress=self._progress))

    def cancel_current(self) -> bool:
        return bool(self.current_task) and self.running and self.core.cancel(self.current_task)

    def _cancel(self, argument: str) -> None:
        cancelled = self.core.cancel(self._task_id(argument))
        self.write("Cancelling." if cancelled else "That task has no active run.")

    def _approve(self, argument: str) -> None:
        self.write(format_approval(self.core.approve(self._task_id(""), force=argument == "--force")))

    def _reject(self, _: str) -> None:
        self.core.reject(self._task_id(""))
        self.write("Rejected; the target was not changed.")

    def status_line(self) -> str:
        project = self.project or "(no project)"
        if not self.current_task:
            return f"{project} · /help for commands"
        try:
            counters = self.core.show(self.current_task, include_diff=False)
        except (UnknownTaskError, OSError, ValueError):
            return f"{project} · /help for commands"
        hint = "esc to cancel" if self.running else counters.state
        return (f"{project} · task {self.current_task} · {counters.counters.actions}/{counters.limits.actions} actions · "
                f"{counters.counters.tokens}/{counters.limits.tokens} tokens · {hint}")


def _colour(text: str) -> str:
    """Rich markup for a compact output line; everything else is shown literally."""
    from rich.markup import escape

    safe = escape(text)
    if text.startswith("● "):
        return f"[cyan]●[/cyan]{safe[1:]}"
    if text.startswith(("Error", "Warning", "Unfinished")) or ": FAIL" in text or ": UNAVAILABLE" in text:
        return f"[yellow]{safe}[/yellow]"
    return safe


def run_interactive(core_factory) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout
    from rich.console import Console

    session = InteractiveSession(core_factory(with_model=True))
    console = Console()
    session.write = lambda text: console.print(_colour(text), highlight=False, soft_wrap=True)
    bindings = KeyBindings()

    @bindings.add("escape", eager=True)
    def cancel(event):
        if session.cancel_current():
            session.write("Cancelling.")

    # `harness cancel` from another terminal signals this process; the core's watcher does the stopping.
    signal.signal(signal.SIGTERM, lambda number, frame: session.cancel_current())
    prompt: PromptSession = PromptSession(key_bindings=bindings, bottom_toolbar=session.status_line, refresh_interval=0.5)
    session.write("Coding harness. Type a request, or /help.")
    with patch_stdout(raw=True):
        while not session.finished:
            try:
                session.handle_line(prompt.prompt("> "))
            except KeyboardInterrupt:
                if not session.cancel_current():
                    session.write("Type /quit to leave.")
            except EOFError:
                if session.running:
                    session.cancel_current()
                    session.wait()
                return 0
    return 0
