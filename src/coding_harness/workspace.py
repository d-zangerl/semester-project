from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .projects import Project, path_matches

# Always left out, whatever a project configures.
ALWAYS_EXCLUDED = (".env", ".env.*", ".git", "venv", ".venv", "*.pem", "*.key", "__pycache__")


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


def _run_git(source: Path, *arguments: str, text: bool = True):
    return subprocess.run(["git", "-C", str(source), *arguments], check=True, capture_output=True, text=text,
                          stdin=subprocess.DEVNULL)


def source_commit(project: Project) -> str | None:
    """The source's current commit, or None when it is not a Git repository."""
    try:
        return _run_git(Path(project.path), "rev-parse", "HEAD").stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _excluded(relative: str, project: Project) -> bool:
    parts = Path(relative).parts
    return path_matches(relative, project.excluded_paths) or any(
        path_matches(part, ALWAYS_EXCLUDED) for part in parts)


def _copy_source_files(project: Project, destination: Path, *, commit: str | None) -> None:
    source = Path(project.path)
    if commit:
        archive = _run_git(source, "archive", "--format=tar", commit, text=False).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            members = [member for member in tar.getmembers()
                       if member.isfile() and not _excluded(member.name, project)]
            tar.extractall(destination, members=members, filter="data")
        return
    for path in source.rglob("*"):
        relative = path.relative_to(source).as_posix()
        if path.is_file() and not path.is_symlink() and not _excluded(relative, project):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def _add_declared_files(project: Project, destination: Path) -> None:
    source = Path(project.path)
    for fixture in project.fixtures:
        target = destination / fixture
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / fixture, target)
    for name, template in project.generated_files.items():
        shutil.copyfile(source / template, destination / name)


def populate_workspace(project: Project, destination: Path, *, commit: str | None) -> None:
    """Fill a workspace from a commit, or the working tree when commit is None: credentials out, fixtures in."""
    destination.mkdir(parents=True)
    _copy_source_files(project, destination, commit=commit)
    _add_declared_files(project, destination)
    # Containers run as an unprivileged user and must be able to write here.
    destination.chmod(0o777)
    for path in destination.rglob("*"):
        path.chmod(0o777 if path.is_dir() else 0o666)


class WorkspaceRepository:
    """The workspace's private Git history. Its Git directory lives outside the workspace, out of reach of
    executed code, so repository code cannot plant hooks or configuration that the harness would then run."""

    _IDENTITY = ("-c", "user.name=coding-harness", "-c", "user.email=harness@localhost", "-c", "commit.gpgsign=false",
                 "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false",
                 "-c", "core.attributesFile=/dev/null", "-c", "core.excludesFile=/dev/null")

    def __init__(self, git_directory: str | Path, workspace: str | Path):
        self.git_directory = Path(git_directory)
        self.workspace = Path(workspace)

    def _git(self, *arguments: str, text: bool = True):
        return subprocess.run(
            ["git", *self._IDENTITY, f"--git-dir={self.git_directory}", f"--work-tree={self.workspace}", *arguments],
            check=True, capture_output=True, text=text, stdin=subprocess.DEVNULL, cwd=self.workspace)

    def initialise(self) -> str:
        self.git_directory.parent.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        return self.commit("Starting state")

    def commit(self, message: str) -> str:
        self._git("add", "--all", "--force", ".")
        self._git("commit", "-q", "--allow-empty", "-m", message)
        return self.head()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def remotes(self) -> list[str]:
        return self._git("remote").stdout.split()

    def restore(self, commit: str) -> None:
        self._git("reset", "-q", "--hard", commit)
        self._git("clean", "-q", "-f", "-d", "-x")

    def status(self) -> str:
        return self._git("status", "--porcelain").stdout

    def diff(self, commit: str | None = None) -> str:
        return self._git("diff", commit or "HEAD", "--", ".").stdout

    def files_at(self, commit: str) -> dict[str, bytes]:
        archive = self._git("archive", "--format=tar", commit, text=False).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            return {member.name: tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()}


def create_project_workspace(project: Project, workspace: Path, git_directory: Path) -> tuple[Path, str | None, WorkspaceRepository, str]:
    """Create a task workspace and its private history. Returns workspace, source commit, repository, first commit."""
    commit = source_commit(project)
    populate_workspace(project, workspace, commit=commit)
    repository = WorkspaceRepository(git_directory, workspace)
    first_commit = repository.initialise()
    return workspace, commit, repository, first_commit
