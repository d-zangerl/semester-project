from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .agent import AgentController, RunCounters, RunLimits, TaskResult
from .context import ContextLimits, ContextManager
from .execution import CheckResult, DockerRunner, ExecutionEnvironment, process_exists
from .projects import Project, path_matches
from .repository import RepositoryTools
from .review import apply_changes, target_differences
from .model import estimate_tokens
from .store import TaskStore
from .verification import Verification
from .workspace import WorkspaceRepository, create_project_workspace, populate_workspace


class UnknownProjectError(ValueError):
    """The requested project is not in the allowlist."""


class UnknownTaskError(ValueError):
    """No saved task has this ID."""


@dataclass(frozen=True)
class StartedTask:
    result: TaskResult
    workspace: Path
    environment: object
    task_id: str | None = None
    start_commit: str | None = None
    repository: WorkspaceRepository | None = None


@dataclass(frozen=True)
class Step:
    tool: str
    arguments: dict
    status: str
    result: str | None
    denied: bool


@dataclass(frozen=True)
class SavedTask:
    task_id: str
    project: str
    request: str
    start_commit: str | None
    allowed_changes: tuple[str, ...]
    check_names: tuple[str, ...]
    state: str
    reason: str | None
    final_response: str
    review_decision: str | None
    workspace: Path
    runs: int
    limits: RunLimits
    counters: RunCounters
    steps: tuple[Step, ...]
    errors: tuple[str, ...]
    history: tuple[dict, ...]
    checks: tuple[CheckResult, ...]
    changed_files: tuple[str, ...]
    diff: str

    @property
    def unfinished(self) -> str:
        """What this task did not finish, in words; empty when it completed."""
        if self.state == "completed":
            return ""
        return self.reason or f"The task is {self.state} and did not complete."


@dataclass(frozen=True)
class ApprovalOutcome:
    applied: tuple[str, ...]
    blocked_by: tuple[str, ...]
    post_checks: tuple[CheckResult, ...]
    post_workspace: Path | None

    @property
    def passed(self) -> bool:
        return bool(self.applied) and bool(self.post_checks) and all(check.passed for check in self.post_checks)


def hash_workspace(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in workspace.rglob("*") if path.is_file() and not path.is_symlink()):
        digest.update(path.relative_to(workspace).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class _StoreRecorder:
    """Saves a run as it happens, so a restarted harness can reopen it."""

    def __init__(self, store: TaskStore, repository: WorkspaceRepository, task_id: str, run_id: int):
        self.store, self.repository, self.task_id, self.run_id = store, repository, task_id, run_id
        self._action_id: int | None = None
        self._hash: str | None = None

    def message(self, role: str, content: str) -> None:
        self.store.add_event(self.task_id, self.run_id, "message", {"role": role, "content": content})

    def action_started(self, tool: str, arguments: dict) -> None:
        self._action_id = self.store.action_started(self.task_id, self.run_id, tool, arguments)

    def action_finished(self, result: str, denied: bool) -> None:
        workspace_hash = hash_workspace(self.repository.workspace)
        checkpoint = self.repository.head()
        if workspace_hash != self._hash:
            checkpoint = self.repository.commit(f"Checkpoint after action {self._action_id}")
            self._hash = workspace_hash
        self.store.action_finished(self._action_id, result, denied, workspace_hash, checkpoint)
        self.store.add_event(self.task_id, self.run_id, "workspace_state", {"hash": workspace_hash})
        self._action_id = None

    def counters(self, counters: RunCounters) -> None:
        self.store.save_progress(self.task_id, dataclasses.asdict(counters))

    def checks(self, verification) -> None:
        self.store.add_event(self.task_id, self.run_id, "verification",
                             {"checks": [dataclasses.asdict(check) for check in verification.checks]})
        # Checks can leave files behind; the saved working-copy state includes them.
        workspace_hash = hash_workspace(self.repository.workspace)
        if workspace_hash != self._hash:
            self.repository.commit("Checkpoint after checks")
            self._hash = workspace_hash
        self.store.add_event(self.task_id, self.run_id, "workspace_state", {"hash": workspace_hash})


class TaskCore:
    """The single entry point every user interface uses to run tasks."""

    def __init__(self, *, model_client=None, projects: Mapping[str, Project] | None = None,
                 state_directory: str | Path | None = None, runner=None, task_log_directory: str | Path | None = None,
                 limits: RunLimits | None = None, context_limits: ContextLimits | None = None,
                 question_empty_completion: bool = True):
        self.question_empty_completion = question_empty_completion
        self.context_limits = context_limits
        self.model_client = model_client
        self.projects = dict(projects or {})
        self.state_directory = Path(state_directory).resolve() if state_directory else Path(".harness").resolve()
        self.runner = runner or DockerRunner()
        self.task_log_directory = task_log_directory or self.state_directory / "logs"
        self.limits = limits or RunLimits()
        self._store: TaskStore | None = None

    @property
    def store(self) -> TaskStore:
        if self._store is None:
            self._store = TaskStore(self.state_directory / "harness.db")
        return self._store

    def _project(self, name: str) -> Project:
        project = self.projects.get(name)
        if project is None:
            raise UnknownProjectError(f"{name!r} is not an allowed project. "
                                      f"Allowed: {', '.join(sorted(self.projects)) or '(none)'}.")
        return project

    def start(self, project_name: str, request: str,
              progress: Callable[[str], None] | None = None) -> StartedTask:
        project = self._project(project_name)
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Task description is required.")
        emit = progress or (lambda message: None)
        trusted = self._trusted_messages(project, request)
        limit = (self.context_limits or ContextLimits()).trusted
        if sum(estimate_tokens(message["content"]) for message in trusted) > limit:
            raise ValueError(f"The request is too long: trusted terms must fit within {limit} estimated tokens.")
        task_id = uuid.uuid4().hex[:8]
        workspace, commit, repository, first_commit = create_project_workspace(
            project, self.state_directory / "workspaces" / task_id, self.state_directory / "git" / task_id)
        self.store.create_task(task_id, project.name, request, commit, first_commit, workspace,
                               repository.git_directory, project.settings(), dataclasses.asdict(self.limits))
        self.store.add_event(task_id, None, "workspace_state", {"hash": hash_workspace(workspace)})
        emit(f"Task {task_id} workspace: {workspace}")
        return self._run(task_id, project, repository, emit, initial_messages=trusted)

    def _run(self, task_id: str, project: Project, repository: WorkspaceRepository, emit,
             counters: RunCounters | None = None, history: list[dict] | None = None,
             initial_messages: list[dict] | None = None) -> StartedTask:
        saved = self.store.task(task_id)
        workspace = repository.workspace
        limits = RunLimits(**json.loads(saved["limits"]))
        self._remove_stale_containers()
        run_id = self.store.begin_run(task_id, os.getpid())
        environment = ExecutionEnvironment(checks=project.checks, runner=self.runner, run_id=f"{task_id}-{run_id}")
        recorder = _StoreRecorder(self.store, repository, task_id, run_id)
        recorder._hash = hash_workspace(workspace)
        tools = RepositoryTools(workspace, allowed_changes=project.allowed_changes, history=repository)
        context = ContextManager(tools, saved["request"], lambda: self.store.actions(task_id), self.context_limits)
        controller = AgentController(
            self.model_client,
            tools,
            self._verification(environment, project.allowed_changes),
            limits=limits,
            progress=emit,
            task_log_directory=self.task_log_directory,
            recorder=recorder,
            cancel_requested=lambda: self.store.cancel_requested(task_id),
            context_builder=context.build,
            question_empty_completion=self.question_empty_completion,
        )
        finished = threading.Event()

        def stop_containers_on_cancel():
            while not finished.wait(0.1):
                if self.store.cancel_requested(task_id):
                    environment.stop()
                    return

        watcher = threading.Thread(target=stop_containers_on_cancel, daemon=True)
        watcher.start()
        restore_signal = self._cancel_on_terminate(task_id)
        try:
            result = controller.run_task(saved["request"], workspace,
                                         baseline=repository.files_at(saved["first_commit"]),
                                         counters=counters, history=history, initial_messages=initial_messages)
        except Exception as error:
            self.store.save_outcome(task_id, "failed", str(error), "", None)
            self.store.end_run(run_id, "failed")
            raise
        finally:
            finished.set()
            watcher.join(timeout=5)
            restore_signal()
        self._save_result(task_id, run_id, result)
        return StartedTask(result, workspace, environment, task_id, saved["start_commit"], repository)

    def _remove_stale_containers(self) -> None:
        remove_stale = getattr(self.runner, "remove_stale", None)
        if remove_stale:
            try:
                remove_stale()
            except (OSError, subprocess.SubprocessError):
                pass

    def _cancel_on_terminate(self, task_id: str) -> Callable[[], None]:
        """A signal from `cancel` in another terminal, or a plain kill, stops the run cleanly."""
        if threading.current_thread() is not threading.main_thread():
            return lambda: None
        previous = signal.signal(signal.SIGTERM, lambda number, frame: self.store.request_cancel(task_id))
        return lambda: signal.signal(signal.SIGTERM, previous)

    def cancel(self, task_id: str) -> bool:
        """Ask an active run to stop. Returns False when the task has no active run."""
        row = self._row(task_id)
        if row["state"] != "running":
            return False
        self.store.request_cancel(task_id)
        pid = row["pid"]
        if pid and pid != os.getpid() and process_exists(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return True

    def _row(self, task_id: str):
        row = self.store.task(task_id)
        if row is None:
            raise UnknownTaskError(f"No task with ID {task_id!r}.")
        return row

    def _paused(self, task_id: str, row, repository: WorkspaceRepository, reason: str, emit) -> StartedTask:
        self.store.save_outcome(task_id, "paused", reason, row["final_response"], None)
        emit(f"Paused: {reason}")
        counters = RunCounters(**json.loads(row["counters"]))
        return StartedTask(TaskResult("", None, counters, reason, None, "paused"), repository.workspace, None,
                           task_id, row["start_commit"], repository)

    def _expected_hash(self, task_id: str) -> str:
        return self.store.events(task_id, "workspace_state")[-1]["hash"]

    def _last_checkpoint(self, row) -> str:
        finished = [action for action in self.store.actions(row["id"]) if action["checkpoint"]]
        return finished[-1]["checkpoint"] if finished else row["first_commit"]

    def resume(self, task_id: str, *, discard_to_checkpoint: bool = False, accept_current_state: bool = False,
               progress: Callable[[str], None] | None = None) -> StartedTask:
        """Continue only from a trusted state. Anything else pauses until the user chooses."""
        return self._continue_run(task_id, discard_to_checkpoint, accept_current_state, progress, None)

    def continue_task(self, task_id: str, instruction: str,
                      progress: Callable[[str], None] | None = None) -> StartedTask:
        """A follow-up on an unapproved task: a new run with the same workspace, history, and consumed limits."""
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("A follow-up instruction is required.")
        return self._continue_run(task_id, False, False, progress, instruction.strip())

    def _continue_run(self, task_id: str, discard: bool, accept: bool, progress, instruction: str | None) -> StartedTask:
        if discard and accept:
            raise ValueError("Choose either discarding to the last checkpoint or accepting the current state.")
        emit = progress or (lambda message: None)
        row = self._row(task_id)
        if row["review_decision"]:
            raise ValueError(f"Task {task_id} was already reviewed: {row['review_decision']}.")
        if instruction is None and row["state"] == "completed":
            raise ValueError(f"Task {task_id} already completed; review it or send a follow-up.")
        if row["state"] == "running" and row["pid"] and row["pid"] != os.getpid() and process_exists(row["pid"]):
            raise ValueError(f"Task {task_id} still has an active run in process {row['pid']}.")
        repository = WorkspaceRepository(row["git_directory"], row["workspace"])
        project = self.projects.get(row["project"])
        if project is None:
            return self._paused(task_id, row, repository, f"The allowed project {row['project']!r} is no longer listed.", emit)
        if project.settings() != json.loads(row["settings"]):
            return self._paused(task_id, row, repository, f"The allowed project {row['project']!r} changed its settings.", emit)
        if not repository.workspace.is_dir():
            return self._paused(task_id, row, repository, "The task workspace no longer exists.", emit)
        uncertain = [action for action in self.store.actions(task_id) if action["status"] == "started"]
        mismatch = hash_workspace(repository.workspace) != self._expected_hash(task_id)
        if (uncertain or mismatch) and not (discard or accept):
            if uncertain:
                action = uncertain[-1]
                reason = (f"uncertain action: {action['tool']} {action['arguments']} began before an interruption and "
                          "its outcome is unknown.")
            else:
                reason = "The task workspace differs from its saved state."
            return self._paused(task_id, row, repository, reason + " Resume with an explicit choice: discard to the "
                                "last checkpoint, or accept the current state.", emit)
        if uncertain or mismatch:
            choice = "discard_to_checkpoint" if discard else "accept_current_state"
            if discard:
                repository.restore(self._last_checkpoint(row))
            else:
                repository.commit("Accepted current state on resume")
            self.store.add_event(task_id, None, "resume_choice", {"choice": choice})
            self.store.add_event(task_id, None, "workspace_state", {"hash": hash_workspace(repository.workspace)})
            status = "discarded" if discard else "accepted"
            for action in uncertain:
                self.store.resolve_action(action["id"], status)
            note = ("The interrupted action's effects were discarded; the files are back at the last checkpoint."
                    if discard else "The user accepted the current files, including any effects of the interrupted action.")
            self.store.add_event(task_id, None, "message", {"role": "user", "content": note})
        if instruction is not None:
            self.store.add_event(task_id, None, "instruction", {"text": instruction})
        return self._run(task_id, project, repository, emit, counters=RunCounters(**json.loads(row["counters"])),
                         history=self._history(task_id))

    def _history(self, task_id: str) -> list[dict]:
        history = [{"role": event["role"], "content": event["content"]}
                   for event in self.store.events(task_id, "message")]
        instructions = [event["text"] for event in self.store.events(task_id, "instruction")]
        if instructions:
            follow_ups = "\n".join(f"Follow-up instruction: {text}" for text in instructions)
            history[1] = {**history[1], "content": f"{history[1]['content']}\n{follow_ups}"}
        return history

    def review(self, task_id: str) -> SavedTask:
        return self.show(task_id)

    def _reviewable(self, task_id: str):
        row = self._row(task_id)
        if row["review_decision"]:
            raise ValueError(f"Task {task_id} was already reviewed: {row['review_decision']}.")
        if row["state"] == "running" and row["pid"] and process_exists(row["pid"]) and row["pid"] != os.getpid():
            raise ValueError(f"Task {task_id} still has an active run.")
        return row

    def reject(self, task_id: str) -> None:
        self._reviewable(task_id)
        self.store.save_review_decision(task_id, "rejected")

    def approve(self, task_id: str, *, force: bool = False) -> ApprovalOutcome:
        row = self._reviewable(task_id)
        project = self._project(row["project"])
        saved = self.show(task_id)
        if not saved.changed_files:
            raise ValueError(f"Task {task_id} has no changes to approve.")
        originals = WorkspaceRepository(row["git_directory"], row["workspace"]).files_at(row["first_commit"])
        differences = target_differences(project.path, row["start_commit"], originals, saved.changed_files)
        if differences and not force:
            return ApprovalOutcome((), tuple(differences), (), None)
        apply_changes(project.path, row["workspace"], saved.changed_files)
        self.store.save_review_decision(task_id, "approved (forced)" if differences else "approved")
        fresh = self.state_directory / "post-apply" / f"{task_id}-{uuid.uuid4().hex[:6]}"
        populate_workspace(project, fresh, commit=None)
        environment = ExecutionEnvironment(checks=project.checks, runner=self.runner)
        verification = Verification(environment)
        checks = verification.verify(fresh, verification.capture_baseline(fresh)).checks
        outcome = ApprovalOutcome(tuple(saved.changed_files), (), tuple(checks), fresh)
        self.store.add_event(task_id, None, "post_apply", {"passed": outcome.passed,
                                                           "checks": [dataclasses.asdict(check) for check in checks]})
        if outcome.passed:
            shutil.rmtree(fresh, ignore_errors=True)
        return outcome

    @staticmethod
    def _trusted_messages(project: Project, request: str) -> list[dict]:
        terms = (f"Task: {request.strip()}\n"
                 f"Scope: you may only change these paths: {', '.join(project.allowed_changes)}.\n"
                 f"Acceptance: the task is complete only when these configured checks pass: "
                 f"{', '.join(project.checks) or '(none)'}.")
        return [{"role": "system", "content": AgentController._system_prompt()}, {"role": "user", "content": terms}]

    @staticmethod
    def _verification(environment, allowed_changes) -> Verification:
        return Verification(environment, relevant=lambda name: path_matches(name, tuple(allowed_changes)))

    def _save_result(self, task_id: str, run_id: int, result: TaskResult) -> None:
        checks = None
        if result.verification is not None:
            checks = [dataclasses.asdict(check) for check in result.verification.checks]
        self.store.save_outcome(task_id, result.outcome, result.stopped_reason, result.final_response, checks)
        self.store.end_run(run_id, result.outcome)

    def list_tasks(self) -> list[SavedTask]:
        return [self.show(row["id"], include_diff=False) for row in self.store.tasks()]

    def show(self, task_id: str, include_diff: bool = True) -> SavedTask:
        row = self._row(task_id)
        settings = json.loads(row["settings"])
        steps = tuple(Step(action["tool"], json.loads(action["arguments"]), action["status"], action["result"],
                           bool(action["denied"])) for action in self.store.actions(task_id))
        errors = tuple(step.result for step in steps if step.denied and step.result)
        if row["reason"] and row["state"] in {"failed", "paused"}:
            errors += (row["reason"],)
        history = tuple(self._history(task_id))
        state = row["state"]
        if state == "running" and row["pid"] and not process_exists(row["pid"]):
            state = "interrupted"
        checks = tuple(CheckResult(**check) for check in json.loads(row["checks"]))
        if not checks:
            verifications = self.store.events(task_id, "verification")
            if verifications:
                checks = tuple(CheckResult(**check) for check in verifications[-1]["checks"])
        changed: tuple[str, ...] = ()
        diff = ""
        if include_diff and Path(row["workspace"]).is_dir():
            repository = WorkspaceRepository(row["git_directory"], row["workspace"])
            checker = self._verification(None, settings["allowed_changes"])
            changed, diff, _ = checker.diff(row["workspace"], repository.files_at(row["first_commit"]))
        return SavedTask(row["id"], row["project"], row["request"], row["start_commit"],
                         tuple(settings["allowed_changes"]), tuple(settings["checks"]), state, row["reason"],
                         row["final_response"], row["review_decision"], Path(row["workspace"]),
                         self.store.run_count(task_id), RunLimits(**json.loads(row["limits"])),
                         RunCounters(**json.loads(row["counters"])), steps, errors, history, checks, changed, diff)
