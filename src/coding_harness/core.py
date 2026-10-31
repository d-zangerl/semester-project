from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .agent import AgentController, RunCounters, RunLimits, TaskResult
from .execution import CheckResult, ExecutionEnvironment
from .projects import Project, path_matches
from .repository import RepositoryTools
from .store import TaskStore
from .verification import Verification
from .workspace import WorkspaceRepository, create_project_workspace, create_task_workspace


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
        self._action_id = None

    def counters(self, counters: RunCounters) -> None:
        self.store.save_progress(self.task_id, dataclasses.asdict(counters))

    def checks(self, verification) -> None:
        self.store.add_event(self.task_id, self.run_id, "verification",
                             {"checks": [dataclasses.asdict(check) for check in verification.checks]})


class TaskCore:
    """The single entry point every user interface uses to run tasks."""

    def __init__(self, *, model_client=None, projects: Mapping[str, Project] | None = None,
                 state_directory: str | Path | None = None, runner=None, environment_factory=ExecutionEnvironment,
                 workspace_factory=create_task_workspace, task_log_directory: str | Path | None = None,
                 limits: RunLimits | None = None):
        self.model_client = model_client
        self.projects = dict(projects or {})
        self.state_directory = Path(state_directory).resolve() if state_directory else Path(".harness").resolve()
        self.runner = runner
        self.environment_factory = environment_factory
        self.workspace_factory = workspace_factory
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
        task_id = uuid.uuid4().hex[:8]
        workspace, commit, repository, first_commit = create_project_workspace(
            project, self.state_directory / "workspaces" / task_id, self.state_directory / "git" / task_id)
        self.store.create_task(task_id, project.name, request, commit, first_commit, workspace,
                               repository.git_directory, project.settings(), dataclasses.asdict(self.limits))
        emit(f"Task {task_id} workspace: {workspace}")
        return self._run(task_id, project, repository, emit)

    def _run(self, task_id: str, project: Project, repository: WorkspaceRepository, emit,
             counters: RunCounters | None = None, history: list[dict] | None = None) -> StartedTask:
        saved = self.store.task(task_id)
        workspace = repository.workspace
        limits = RunLimits(**json.loads(saved["limits"]))
        run_id = self.store.begin_run(task_id, os.getpid())
        environment = ExecutionEnvironment(checks=project.checks, runner=self.runner, run_id=f"{task_id}-{run_id}")
        recorder = _StoreRecorder(self.store, repository, task_id, run_id)
        recorder._hash = hash_workspace(workspace)
        controller = AgentController(
            self.model_client,
            RepositoryTools(workspace, allowed_changes=project.allowed_changes),
            self._verification(environment, project.allowed_changes),
            limits=limits,
            progress=emit,
            task_log_directory=self.task_log_directory,
            recorder=recorder,
        )
        result = controller.run_task(saved["request"], workspace, baseline=repository.files_at(saved["first_commit"]),
                                     counters=counters, history=history)
        self._save_result(task_id, run_id, result)
        return StartedTask(result, workspace, environment, task_id, saved["start_commit"], repository)

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
        row = self.store.task(task_id)
        if row is None:
            raise UnknownTaskError(f"No task with ID {task_id!r}.")
        settings = json.loads(row["settings"])
        steps = tuple(Step(action["tool"], json.loads(action["arguments"]), action["status"], action["result"],
                           bool(action["denied"])) for action in self.store.actions(task_id))
        errors = tuple(step.result for step in steps if step.denied and step.result)
        if row["reason"] and row["state"] in {"failed", "paused"}:
            errors += (row["reason"],)
        history = tuple({"role": event["role"], "content": event["content"]}
                        for event in self.store.events(task_id, "message"))
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
                         tuple(settings["allowed_changes"]), tuple(settings["checks"]), row["state"], row["reason"],
                         row["final_response"], row["review_decision"], Path(row["workspace"]),
                         self.store.run_count(task_id), RunLimits(**json.loads(row["limits"])),
                         RunCounters(**json.loads(row["counters"])), steps, errors, history, checks, changed, diff)

    def start_in_copy(self, repository: str | Path, request: str,
                      progress: Callable[[str], None] | None = None) -> StartedTask:
        """Stage 1 flow on any directory; removed once the interfaces move to allowed projects."""
        emit = progress or (lambda message: None)
        workspace = Path(self.workspace_factory(repository))
        emit(f"Task workspace: {workspace}")
        environment = self.environment_factory()
        controller = AgentController(
            self.model_client,
            RepositoryTools(workspace),
            Verification(environment),
            limits=dataclasses.replace(self.limits, fix_attempts=0),
            progress=emit,
            task_log_directory=self.task_log_directory,
        )
        return StartedTask(controller.run_task(request, workspace), workspace, environment)
