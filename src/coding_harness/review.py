from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def target_differences(repository: str | Path, start_commit: str | None, originals: dict[str, bytes],
                       changed_files) -> list[str]:
    """How the target differs from the task's starting state, in ways that approving would overwrite or ignore."""
    root = Path(repository)
    differences = []
    if start_commit:
        current = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL).stdout.strip()
        if current != start_commit:
            differences.append(f"target commit is {current or 'unknown'}, the task started from {start_commit}")
    for name in changed_files:
        path = root / name
        current_bytes = path.read_bytes() if path.is_file() else None
        if current_bytes != originals.get(name):
            differences.append(f"{name} differs from the task's starting state")
    return differences


def apply_changes(repository: str | Path, workspace: str | Path, changed_files) -> int:
    """Copy every changed file from the task workspace into the configured repository."""
    root = Path(repository).resolve(strict=True)
    source_root = Path(workspace).resolve(strict=True)
    applied = 0
    for name in changed_files:
        destination = (root / name).resolve()
        source = source_root / name
        if root not in destination.parents:
            raise ValueError(f"Refusing to apply a path outside the configured repository: {name}")
        if source.is_file() and not source.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if root not in destination.parent.resolve().parents and destination.parent.resolve() != root:
                raise ValueError(f"Refusing to apply a path outside the configured repository: {name}")
            shutil.copyfile(source, destination)
        elif not source.exists() and destination.is_file():
            destination.unlink()
        applied += 1
    return applied
