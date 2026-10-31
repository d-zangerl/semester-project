from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping


def path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    """True when a workspace-relative path equals a pattern, sits under it, or matches its glob."""
    posix = PurePosixPath(path).as_posix()
    for pattern in patterns:
        prefix = pattern[:-3] if pattern.endswith("/**") else pattern.rstrip("/")
        if posix == prefix or posix.startswith(prefix + "/") or fnmatch.fnmatchcase(posix, pattern):
            return True
    return False


@dataclass(frozen=True)
class Project:
    """An allowed project: what tasks may run against, and under which rules."""

    name: str
    path: Path
    checks: Mapping[str, tuple[str, ...]]
    allowed_changes: tuple[str, ...]
    excluded_paths: tuple[str, ...] = ()
    fixtures: tuple[str, ...] = ()
    generated_files: Mapping[str, str] = field(default_factory=dict)

    def settings(self) -> dict:
        """The settings a saved task is compared against on resume."""
        return {"path": str(Path(self.path).resolve()), "checks": {name: list(command) for name, command in self.checks.items()},
                "allowed_changes": list(self.allowed_changes), "excluded_paths": list(self.excluded_paths)}


def load_projects(config_path: str | Path) -> dict[str, Project]:
    config_file = Path(config_path)
    with config_file.open("rb") as handle:
        entries = tomllib.load(handle).get("projects", {})
    projects = {}
    for name, entry in entries.items():
        path = Path(entry["path"]).expanduser()
        if not path.is_absolute():
            path = config_file.resolve().parent / path
        projects[name] = Project(
            name=name, path=path,
            checks={check: tuple(command) for check, command in entry["checks"].items()},
            allowed_changes=tuple(entry["allowed_changes"]),
            excluded_paths=tuple(entry.get("excluded_paths", ())),
            fixtures=tuple(entry.get("fixtures", ())),
            generated_files=dict(entry.get("generated_files", {})),
        )
    return projects
