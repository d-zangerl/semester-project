from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .agent import AgentController, TaskResult
from .execution import ExecutionEnvironment
from .projects import Project
from .repository import RepositoryTools
from .verification import Verification
from .workspace import WorkspaceRepository, create_project_workspace, create_task_workspace


class UnknownProjectError(ValueError):
    """The requested project is not in the allowlist."""


@dataclass(frozen=True)
class StartedTask:
    result: TaskResult
    workspace: Path
    environment: object
    task_id: str | None = None
    start_commit: str | None = None
    repository: WorkspaceRepository | None = None


class TaskCore:
    """The single entry point every user interface uses to run tasks."""

    def __init__(self, *, model_client, projects: Mapping[str, Project] | None = None,
                 state_directory: str | Path | None = None, runner=None, environment_factory=ExecutionEnvironment,
                 workspace_factory=create_task_workspace, task_log_directory: str | Path | None = None):
        self.model_client = model_client
        self.projects = dict(projects or {})
        self.state_directory = Path(state_directory) if state_directory else Path(".harness")
        self.runner = runner
        self.environment_factory = environment_factory
        self.workspace_factory = workspace_factory
        self.task_log_directory = task_log_directory or self.state_directory / "logs"

    def start(self, project_name: str, request: str,
              progress: Callable[[str], None] | None = None) -> StartedTask:
        project = self.projects.get(project_name)
        if project is None:
            raise UnknownProjectError(f"{project_name!r} is not an allowed project. "
                                      f"Allowed: {', '.join(sorted(self.projects)) or '(none)'}.")
        emit = progress or (lambda message: None)
        task_id = uuid.uuid4().hex[:8]
        workspace, commit, repository, _ = create_project_workspace(
            project, self.state_directory / "workspaces" / task_id, self.state_directory / "git" / task_id)
        emit(f"Task workspace: {workspace}")
        environment = ExecutionEnvironment(checks=project.checks, runner=self.runner)
        controller = AgentController(
            self.model_client,
            RepositoryTools(workspace, allowed_changes=project.allowed_changes),
            Verification(environment),
            progress=emit,
            task_log_directory=self.task_log_directory,
        )
        result = controller.run_task(request, workspace)
        return StartedTask(result, workspace, environment, task_id, commit, repository)

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
            progress=emit,
            task_log_directory=self.task_log_directory,
        )
        return StartedTask(controller.run_task(request, workspace), workspace, environment)
