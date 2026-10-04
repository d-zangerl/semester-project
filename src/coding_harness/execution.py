from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


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


class ExecutionEnvironment:
    """Runs fixed, configured checks under the macOS App Sandbox profile."""

    def __init__(
        self,
        checks: Mapping[str, Sequence[str]] | None = None,
        *,
        timeout_seconds: float = 60,
        output_limit_bytes: int = 64 * 1024,
        sandbox_executable: str | None = None,
    ):
        configured_checks = checks or {"core": (sys.executable, "tests/test_core.py")}
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
        self._sandbox_executable = sandbox_executable

    def run_check(self, check_name: str, workspace: str | Path) -> CheckResult:
        started = time.monotonic()
        command = self._checks.get(check_name)
        if command is None:
            return self._blocked(check_name, f"Check is not configured: {check_name!r}.", started)
        if sys.platform != "darwin":
            return self._blocked(check_name, "OS-enforced sandbox is unavailable on this platform.", started)

        sandbox = self._resolve_sandbox()
        if sandbox is None:
            return self._blocked(
                check_name,
                "macOS sandbox-exec was not found; repository code was not run.",
                started,
            )

        try:
            task_workspace = Path(workspace).resolve(strict=True)
            if not task_workspace.is_dir():
                raise ValueError("Task workspace is not a directory.")
            environment = self._runtime_environment(task_workspace)
            profile = self._profile(task_workspace)
            with tempfile.TemporaryDirectory(prefix="coding-harness-sandbox-probe-") as probe_directory:
                protected_file = Path(probe_directory) / "protected-marker"
                protected_file.write_text("protected", encoding="utf-8")
                probe = self._run_process(
                    (
                        sandbox,
                        "-p",
                        profile,
                        str(Path(sys.executable).resolve()),
                        "-c",
                        self._probe_code(),
                        str(protected_file),
                    ),
                    task_workspace,
                    environment,
                    min(self._timeout_seconds, 10),
                )
                if probe.error or probe.timed_out or probe.exit_code != 0:
                    return self._blocked(
                        check_name,
                        "Sandbox boundary verification failed; repository code was not run. "
                        + self._process_error(probe),
                        started,
                        stdout=probe.stdout,
                        stderr=probe.stderr,
                    )
                if probe.stdout_truncated or probe.stderr_truncated:
                    return self._blocked(
                        check_name,
                        "Sandbox boundary verification output was truncated; repository code was not run.",
                        started,
                        stdout=probe.stdout,
                        stderr=probe.stderr,
                    )

            result = self._run_process(
                (sandbox, "-p", profile, *self._resolve_command(command)),
                task_workspace,
                environment,
                self._timeout_seconds,
            )
            return CheckResult(
                check_name=check_name,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                timed_out=result.timed_out,
                blocked=result.error is not None,
                error=result.error,
                duration_seconds=time.monotonic() - started,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return self._blocked(
                check_name,
                f"Sandbox setup failed; repository code was not run: {error}",
                started,
            )

    def _resolve_sandbox(self) -> str | None:
        executable = self._sandbox_executable or shutil.which("sandbox-exec")
        if executable is None:
            return None
        resolved = shutil.which(executable)
        if resolved is None or not os.access(resolved, os.X_OK):
            return None
        return str(Path(resolved).resolve())

    @staticmethod
    def _runtime_environment(workspace: Path) -> dict[str, str]:
        home = workspace / ".harness-home"
        temporary = workspace / ".harness-tmp"
        home.mkdir(exist_ok=True)
        temporary.mkdir(exist_ok=True)
        return {
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "PATH": str(Path(sys.executable).resolve().parent),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C",
            "LC_ALL": "C",
        }

    @staticmethod
    def _profile(workspace: Path) -> str:
        python_executable = str(Path(sys.executable).resolve())
        runtime_executables = {Path(python_executable)}
        framework_executable = Path(sys.prefix) / "Resources/Python.app/Contents/MacOS/Python"
        if framework_executable.is_file():
            runtime_executables.add(framework_executable.resolve())
        read_roots = {
            "/System",
            "/usr/bin",
            "/usr/lib",
            "/usr/share",
            "/private/var/db/dyld",
            str(Path(python_executable).parent),
        }
        runtime_library_roots = {
            path.resolve()
            for path in (Path(sys.prefix) / "lib", Path(sys.base_prefix) / "lib")
            if path.is_dir()
        }
        library_directory = sysconfig.get_config_var("LIBDIR")
        if library_directory and Path(library_directory).is_dir():
            runtime_library_roots.add(Path(library_directory).resolve())
        read_roots.update(str(path) for path in runtime_library_roots)
        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            value = sysconfig.get_paths().get(key)
            if value:
                read_roots.add(str(Path(value).resolve()))

        runtime_libraries = {Path(sys.prefix) / "Python"}
        library_name = sysconfig.get_config_var("LDLIBRARY")
        if library_directory and library_name:
            runtime_libraries.add(Path(library_directory) / library_name)
        runtime_libraries = {
            path.resolve()
            for path in runtime_libraries
            if path.is_file()
        }

        rules = [
            "(version 1)",
            '(import "system.sb")',
            "(deny default)",
            "(allow process-fork)",
            "(allow sysctl-read)",
            "(deny network*)",
            "(deny syscall-unix (syscall-number SYS_setsid))",
            "(deny syscall-unix (syscall-number SYS_setpgid))",
            "(allow file-read* (subpath \"/System\") (subpath \"/usr/bin\") "
            "(subpath \"/usr/lib\") (subpath \"/usr/share\") "
            "(subpath \"/private/var/db/dyld\") "
            "(literal \"/dev/null\") (literal \"/dev/urandom\"))",
        ]
        rules.extend(
            f"(allow process-exec (literal {_sbpl_quote(str(executable))}))"
            for executable in sorted(runtime_executables)
        )
        rules.extend(f"(allow file-read* (subpath {_sbpl_quote(root)}))" for root in sorted(read_roots))
        rules.extend(
            f"(allow file-read* file-map-executable (literal {_sbpl_quote(str(executable))}))"
            for executable in sorted(runtime_executables)
        )
        rules.extend(
            f"(allow file-map-executable (subpath {_sbpl_quote(str(root))}))"
            for root in sorted(runtime_library_roots)
        )
        rules.extend(
            f"(allow file-read* file-map-executable (literal {_sbpl_quote(str(library))}))"
            for library in sorted(runtime_libraries)
        )
        rules.extend(
            f"(allow file-read-metadata (path-ancestors {_sbpl_quote(root)}))"
            for root in sorted(read_roots | {str(workspace)} | {str(path) for path in runtime_libraries})
        )
        rules.extend(
            [
                f"(allow file-read* (subpath {_sbpl_quote(str(workspace))}))",
                f"(allow file-write* (subpath {_sbpl_quote(str(workspace))}))",
                "(allow file-write* (literal \"/dev/null\"))",
            ]
        )
        return "\n".join(rules)

    @staticmethod
    def _probe_code() -> str:
        return """
import socket
import sys
from pathlib import Path

if len(__import__("hashlib").pbkdf2_hmac("sha256", b"probe", b"salt", 1)) != 32:
    raise RuntimeError("Python cryptographic runtime is unavailable")

protected = Path(sys.argv[1])
workspace_probe = Path(".harness-sandbox-probe-" + str(__import__("uuid").uuid4()))
try:
    workspace_probe.write_text("workspace", encoding="utf-8")
    if workspace_probe.read_text(encoding="utf-8") != "workspace":
        raise RuntimeError("workspace read/write probe failed")
finally:
    workspace_probe.unlink(missing_ok=True)

try:
    protected.read_text(encoding="utf-8")
except OSError:
    pass
else:
    raise RuntimeError("sandbox can read outside the task workspace")

try:
    protected.write_text("changed", encoding="utf-8")
except OSError:
    pass
else:
    raise RuntimeError("sandbox can write outside the task workspace")

try:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
except OSError:
    pass
else:
    raise RuntimeError("sandbox network access is not blocked")
"""

    def _run_process(
        self,
        command: Sequence[str],
        workspace: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
    ) -> CheckResult:
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            return CheckResult(
                check_name="",
                exit_code=None,
                stdout="",
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
                error=str(error),
                duration_seconds=time.monotonic() - started,
            )

        stdout = _BoundedStream(process.stdout, self._output_limit_bytes)
        stderr = _BoundedStream(process.stderr, self._output_limit_bytes)
        readers = [
            threading.Thread(target=stdout.drain, daemon=True),
            threading.Thread(target=stderr.drain, daemon=True),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
            except KeyboardInterrupt:
                self._stop_process_group(process)
                raise
            self._stop_process_group(process)
        finally:
            for reader in readers:
                reader.join()
            process.stdout.close()
            process.stderr.close()

        return CheckResult(
            check_name="",
            exit_code=process.returncode,
            stdout=stdout.text,
            stderr=stderr.text,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            timed_out=timed_out,
            duration_seconds=time.monotonic() - started,
        )

    @staticmethod
    def _stop_process_group(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.wait()
            return
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        else:
            time.sleep(0.1)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _resolve_command(command: Sequence[str]) -> tuple[str, ...]:
        executable = command[0]
        resolved = shutil.which(executable)
        if resolved is None:
            raise ValueError(f"Configured check executable was not found: {executable}")
        return (str(Path(resolved).resolve()), *command[1:])

    @staticmethod
    def _process_error(result: CheckResult) -> str:
        details = result.error or result.stderr.strip() or result.stdout.strip()
        if result.timed_out:
            details = f"Sandbox verification timed out. {details}"
        if result.exit_code is not None:
            details = f"Sandbox verification exited with code {result.exit_code}. {details}"
        return details

    @staticmethod
    def _blocked(
        check_name: str,
        error: str,
        started: float,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> CheckResult:
        return CheckResult(
            check_name=check_name,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=False,
            stderr_truncated=False,
            blocked=True,
            error=error,
            duration_seconds=time.monotonic() - started,
        )


def _sbpl_quote(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Sandbox paths cannot contain NUL bytes.")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'
