from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_IMAGE = "coding-harness-check:1"
BUILD_HINT = "docker build -t coding-harness-check:1 -f docker/check.Dockerfile target-repository"
RUN_LABEL = "coding-harness.run"
OWNER_LABEL = "coding-harness.owner-pid"
_DOCKER_CONTROL_TIMEOUT = 30


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool = False
    blocked: bool = False
    error: str | None = None
    duration_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.blocked and not self.timed_out and self.exit_code == 0


@dataclass(frozen=True)
class ContainerSpec:
    command: tuple[str, ...]
    workspace: Path
    image: str
    run_id: str
    purpose: str = "check"
    read_only_mounts: Mapping[str, str] = field(default_factory=dict)
    memory: str = "1g"
    cpus: str = "2"
    pids: int = 256


def docker_arguments(spec: ContainerSpec, name: str) -> list[str]:
    arguments = [
        "run", "--rm", "--name", name,
        "--label", f"{RUN_LABEL}={spec.run_id}",
        "--label", f"{OWNER_LABEL}={os.getpid()}",
        "--network", "none",
        "--user", "1000:1000",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp",
        "--memory", spec.memory,
        "--cpus", spec.cpus,
        "--pids-limit", str(spec.pids),
        "--env", "HOME=/tmp",
        "--env", "TMPDIR=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "LANG=C.UTF-8",
        "--volume", f"{spec.workspace}:/workspace",
        "--workdir", "/workspace",
    ]
    for source, target in spec.read_only_mounts.items():
        arguments += ["--volume", f"{source}:{target}:ro"]
    return [*arguments, spec.image, *spec.command]


class _BoundedStream:
    def __init__(self, stream, limit: int):
        self.stream = stream
        self.limit = limit
        self.chunks: list[bytes] = []
        self.size = 0
        self.truncated = False

    def drain(self) -> None:
        while True:
            chunk = self.stream.read(8192)
            if not chunk:
                return
            remaining = self.limit - self.size
            if remaining > 0:
                retained = chunk[:remaining]
                self.chunks.append(retained)
                self.size += len(retained)
            if len(chunk) > remaining:
                self.truncated = True

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


class DockerRunner:
    """The only code that talks to Docker."""

    def __init__(self, docker: str = "docker"):
        self.docker = docker

    def _control(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.docker, *arguments], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=_DOCKER_CONTROL_TIMEOUT)

    def unavailable_reason(self, image: str) -> str | None:
        if shutil.which(self.docker) is None:
            return f"Docker client {self.docker!r} was not found."
        try:
            if self._control("version", "--format", "{{.Server.Version}}").returncode != 0:
                return "Docker daemon is not running or not reachable."
            if self._control("image", "inspect", image).returncode != 0:
                return f"Check image {image} is not built. Build it with: {BUILD_HINT}"
        except (OSError, subprocess.SubprocessError) as error:
            return f"Docker could not be reached: {type(error).__name__}."
        return None

    def run(self, spec: ContainerSpec, timeout_seconds: float, output_limit_bytes: int) -> CheckResult:
        started = time.monotonic()
        name = f"coding-harness-{uuid.uuid4().hex}"
        try:
            process = subprocess.Popen([self.docker, *docker_arguments(spec, name)], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as error:
            return CheckResult("", None, "", "", False, False, error=str(error),
                               duration_seconds=time.monotonic() - started)
        stdout = _BoundedStream(process.stdout, output_limit_bytes)
        stderr = _BoundedStream(process.stderr, output_limit_bytes)
        readers = [threading.Thread(target=stream.drain, daemon=True) for stream in (stdout, stderr)]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._remove_container(name, process)
        except BaseException:
            self._remove_container(name, process)
            raise
        finally:
            for reader in readers:
                reader.join(timeout=5)
        return CheckResult("", None if timed_out else process.returncode, stdout.text, stderr.text,
                           stdout.truncated, stderr.truncated, timed_out=timed_out,
                           duration_seconds=time.monotonic() - started)

    def _remove_container(self, name: str, process: subprocess.Popen) -> None:
        try:
            self._control("rm", "-f", name)
        except (OSError, subprocess.SubprocessError):
            pass
        process.kill()
        process.wait()

    def _labelled_containers(self, *filters: str) -> list[str]:
        arguments = ["ps", "-aq"]
        for value in filters:
            arguments += ["--filter", f"label={value}"]
        return self._control(*arguments).stdout.split()

    def remove_run(self, run_id: str) -> None:
        containers = self._labelled_containers(f"{RUN_LABEL}={run_id}")
        if containers:
            self._control("rm", "-f", *containers)

    def remove_stale(self) -> list[str]:
        """Remove containers whose owning harness process no longer exists."""
        removed = []
        listing = self._control("ps", "-a", "--filter", f"label={OWNER_LABEL}",
                                "--format", f'{{{{.ID}}}} {{{{.Label "{OWNER_LABEL}"}}}}').stdout
        for line in listing.splitlines():
            container, _, owner = line.partition(" ")
            if owner.isdigit() and not _process_exists(int(owner)):
                self._control("rm", "-f", container)
                removed.append(container)
        return removed


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ExecutionEnvironment:
    """Runs fixed, configured checks in new, locked-down containers, and fails closed."""

    def __init__(
        self,
        checks: Mapping[str, Sequence[str]] | None = None,
        *,
        timeout_seconds: float = 60,
        output_limit_bytes: int = 64 * 1024,
        image: str = DEFAULT_IMAGE,
        runner=None,
        run_id: str | None = None,
        read_only_mounts: Mapping[str, str] | None = None,
    ):
        configured_checks = {"core": ("python", "tests/test_core.py")} if checks is None else checks
        self._checks = {
            name: tuple(command)
            for name, command in configured_checks.items()
            if name and command and all(isinstance(part, str) and part for part in command)
        }
        if len(self._checks) != len(configured_checks):
            raise ValueError("Each configured check must have a name and non-empty string command.")
        if timeout_seconds <= 0 or output_limit_bytes <= 0:
            raise ValueError("Check timeout and output limit must be positive.")
        self._timeout_seconds = timeout_seconds
        self._output_limit_bytes = output_limit_bytes
        self._image = image
        self._runner = runner or DockerRunner()
        self.run_id = run_id or uuid.uuid4().hex
        self._read_only_mounts = dict(read_only_mounts or {})
        self._stopped = False

    @property
    def check_names(self) -> tuple[str, ...]:
        return tuple(self._checks)

    def stop(self) -> None:
        """Kill this run's containers and refuse further checks."""
        self._stopped = True
        self._runner.remove_run(self.run_id)

    def run_check(self, check_name: str, workspace: str | Path) -> CheckResult:
        started = time.monotonic()
        command = self._checks.get(check_name)
        if command is None:
            return self._blocked(check_name, f"Check is not configured: {check_name!r}.", started)
        if self._stopped:
            return self._blocked(check_name, "The run was stopped; repository code was not run.", started)
        try:
            task_workspace = Path(workspace).resolve(strict=True)
            if not task_workspace.is_dir():
                raise ValueError("Task workspace is not a directory.")
            reason = self._runner.unavailable_reason(self._image)
            if reason:
                return self._blocked(check_name, f"{reason} Repository code was not run.", started)
            probe = self._runner.run(self._spec(("python", "-c", _PROBE_CODE), task_workspace, "probe"),
                                     min(self._timeout_seconds, 30), self._output_limit_bytes)
            if probe.error or probe.timed_out or probe.exit_code != 0:
                details = probe.error or probe.stderr.strip() or probe.stdout.strip() or "probe did not finish"
                return self._blocked(check_name, f"Container boundary verification failed; repository code was "
                                                 f"not run. {details}", started)
            result = self._runner.run(self._spec(command, task_workspace, "check"),
                                      self._timeout_seconds, self._output_limit_bytes)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return self._blocked(check_name, f"Container setup failed; repository code was not run: {error}", started)
        return CheckResult(check_name, result.exit_code, result.stdout, result.stderr, result.stdout_truncated,
                           result.stderr_truncated, timed_out=result.timed_out,
                           blocked=result.error is not None, error=result.error,
                           duration_seconds=time.monotonic() - started)

    def _spec(self, command: tuple[str, ...], workspace: Path, purpose: str) -> ContainerSpec:
        return ContainerSpec(command, workspace, self._image, self.run_id, purpose, self._read_only_mounts)

    @staticmethod
    def _blocked(check_name: str, error: str, started: float) -> CheckResult:
        return CheckResult(check_name, None, "", "", False, False, blocked=True, error=error,
                           duration_seconds=time.monotonic() - started)


_PROBE_CODE = """
import os
import socket
from pathlib import Path

marker = Path(".harness-probe-" + str(os.getpid()))
marker.write_text("workspace")
marker.unlink()
if os.geteuid() == 0:
    raise SystemExit("container runs as root")
try:
    Path("/etc/harness-probe").write_text("x")
except OSError:
    pass
else:
    raise SystemExit("root filesystem is writable")
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
except OSError:
    pass
else:
    raise SystemExit("network is reachable")
"""
