import os
import signal
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.coding_harness.execution import ExecutionEnvironment


class ExecutionEnvironmentTests(unittest.TestCase):
    def test_explicit_empty_check_configuration_does_not_run_default_check(self):
        runner = ExecutionEnvironment(checks={})

        self.assertEqual(runner.check_names, ())

    def test_configured_check_is_confined_to_its_workspace(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            protected_file = outside / "host-marker.txt"
            protected_file.write_text("host data", encoding="utf-8")
            (workspace / "sandbox_probe.py").write_text(
                """
import socket
import sys
import hashlib
from pathlib import Path

protected_file = Path(sys.argv[1])
if len(hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 1)) != 32:
    raise RuntimeError("Python cryptographic runtime is unavailable")
try:
    protected_file.read_text(encoding="utf-8")
except OSError:
    print("host-read-blocked")
else:
    print("host-read-allowed")
    raise SystemExit(1)

try:
    protected_file.write_text("changed", encoding="utf-8")
except OSError:
    print("host-write-blocked")
else:
    print("host-write-allowed")
    raise SystemExit(1)

try:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
except OSError:
    print("network-blocked")
else:
    print("network-allowed")
    raise SystemExit(1)

Path("workspace-result.txt").write_text("contained", encoding="utf-8")
print("workspace-write-allowed")
""".lstrip(),
                encoding="utf-8",
            )

            result = ExecutionEnvironment(
                checks={"core": (sys.executable, "sandbox_probe.py", str(protected_file))}
            ).run_check("core", workspace)

            self.assertTrue(result.passed, result)
            self.assertIn("host-read-blocked", result.stdout)
            self.assertIn("host-write-blocked", result.stdout)
            self.assertIn("network-blocked", result.stdout)
            self.assertIn("workspace-write-allowed", result.stdout)
            self.assertEqual(
                (workspace / "workspace-result.txt").read_text(encoding="utf-8"),
                "contained",
            )
            self.assertEqual(protected_file.read_text(encoding="utf-8"), "host data")

    def test_check_is_not_run_when_sandbox_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            marker = workspace / "should-not-exist"
            runner = ExecutionEnvironment(
                checks={"core": (sys.executable, "-c", f"open({str(marker)!r}, 'w').close()")},
                sandbox_executable="/missing/sandbox-exec",
            )

            result = runner.run_check("core", workspace)

            self.assertTrue(result.blocked)
            self.assertFalse(result.passed)
            self.assertIsNone(result.exit_code)
            self.assertFalse(marker.exists())

    def test_timed_out_check_stops_its_child_process(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            child_pid_file = workspace / "child.pid"
            child_group_file = workspace / "child-group.txt"
            child_script = f"""
import os
import pathlib
import time

group = pathlib.Path({str(child_group_file)!r})
escaped = False
for change_group in (os.setsid, lambda: os.setpgid(0, 0)):
    try:
        change_group()
    except OSError:
        pass
    else:
        escaped = True
group.write_text("escaped" if escaped else "blocked")
time.sleep(5)
"""
            script = (
                "import pathlib, subprocess, sys, time; "
                f"child = subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
                f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid)); "
                "time.sleep(30)"
            )
            runner = ExecutionEnvironment(
                checks={"core": (sys.executable, "-c", script)},
                timeout_seconds=0.7,
            )

            result = runner.run_check("core", workspace)

            child_pid = child_pid_file.read_text(encoding="utf-8")
            try:
                self.assertTrue(result.timed_out)
                self.assertFalse(result.passed)
                self.assertEqual(child_group_file.read_text(encoding="utf-8"), "blocked")
                process_state = subprocess.run(
                    ["/bin/ps", "-o", "stat=", "-p", child_pid],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                self.assertTrue(not process_state or process_state.startswith("Z"), process_state)
            finally:
                try:
                    os.kill(int(child_pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_completed_check_does_not_leave_background_children_running(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            child_pid_file = workspace / "child.pid"
            heartbeat_file = workspace / "child-heartbeat.txt"
            child_script = f"""
import pathlib
import time

heartbeat = pathlib.Path({str(heartbeat_file)!r})
while True:
    heartbeat.write_text(str(time.monotonic()))
    time.sleep(0.02)
"""
            script = f"""
import pathlib
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", {child_script!r}])
pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid))
deadline = time.monotonic() + 2
while not pathlib.Path({str(heartbeat_file)!r}).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
"""
            result = ExecutionEnvironment(
                checks={"core": (sys.executable, "-c", script)}
            ).run_check("core", workspace)

            self.assertTrue(result.passed, result)
            child_pid = child_pid_file.read_text(encoding="utf-8")
            try:
                heartbeat = heartbeat_file.read_text(encoding="utf-8")
                time.sleep(0.1)
                self.assertEqual(heartbeat_file.read_text(encoding="utf-8"), heartbeat)
                process_state = subprocess.run(
                    ["/bin/ps", "-o", "stat=", "-p", child_pid],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                self.assertTrue(not process_state or process_state.startswith("Z"), process_state)
            finally:
                try:
                    os.kill(int(child_pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_failed_check_keeps_exit_code_and_bounded_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            script = "import sys; print('x' * 200); print('failure', file=sys.stderr); raise SystemExit(7)"
            result = ExecutionEnvironment(
                checks={"core": (sys.executable, "-c", script)},
                output_limit_bytes=32,
            ).run_check("core", workspace)

            self.assertFalse(result.passed)
            self.assertEqual(result.exit_code, 7)
            self.assertTrue(result.stdout_truncated)
            self.assertLessEqual(len(result.stdout.encode("utf-8")), 32)
            self.assertIn("failure", result.stderr)
            self.assertFalse(result.stderr_truncated)


if __name__ == "__main__":
    unittest.main()
