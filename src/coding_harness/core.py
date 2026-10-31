from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agent import AgentController, TaskResult
from .execution import ExecutionEnvironment
from .repository import RepositoryTools
from .verification import Verification
from .workspace import create_task_workspace


@dataclass(frozen=True)
class StartedTask:
    result: TaskResult
    workspace: Path
    environment: object


class TaskCore:
    """The single entry point every user interface uses to run tasks."""

    def __init__(self, *, model_client, environment_factory=ExecutionEnvironment,
                 workspace_factory=create_task_workspace, task_log_directory: str | Path | None = None):
        self.model_client = model_client
        self.environment_factory = environment_factory
        self.workspace_factory = workspace_factory
        self.task_log_directory = task_log_directory

    def start(self, repository: str | Path, request: str,
              progress: Callable[[str], None] | None = None) -> StartedTask:
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
