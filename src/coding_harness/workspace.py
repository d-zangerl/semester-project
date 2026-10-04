from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def create_task_workspace(repository: str | Path) -> Path:
    source = Path(repository).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"Configured repository is not a directory: {source}")

    workspace = Path(tempfile.mkdtemp(prefix="coding-harness-task-"))
    try:
        shutil.copytree(
            source,
            workspace,
            dirs_exist_ok=True,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git"),
        )
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    return workspace
