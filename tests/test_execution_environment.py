import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from src.coding_harness.execution import (
    DEFAULT_IMAGE, ContainerSpec, DockerRunner, ExecutionEnvironment, docker_arguments,
)
from src.coding_harness.projects import load_projects
from tests.fakes import LocalRunner


class ContainerCheckTests(unittest.TestCase):
    """Check behaviour at the container runner seam, with no Docker needed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)

    def environment(self, runner, source="print('fine')", **options):
        (self.workspace / "check.py").write_text(source, encoding="utf-8")
        return ExecutionEnvironment(checks={"core": ("python", "check.py")}, runner=runner, **options)

    def test_explicit_empty_check_configuration_does_not_run_default_check(self):
        self.assertEqual(ExecutionEnvironment(checks={}, runner=LocalRunner()).check_names, ())

    def test_a_passing_check_reports_its_output(self):
        result = self.environment(LocalRunner()).run_check("core", self.workspace)

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "core")
        self.assertEqual(result.stdout.strip(), "fine")

    def test_failed_check_keeps_exit_code_and_bounded_output(self):
        result = self.environment(LocalRunner(), "print('x' * 500); raise SystemExit(7)",
                                  output_limit_bytes=100).run_check("core", self.workspace)

        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(len(result.stdout), 100)
        self.assertTrue(result.stdout_truncated)

    def test_timed_out_check_never_appears_as_passed(self):
        result = self.environment(LocalRunner(), "import time; time.sleep(30)",
                                  timeout_seconds=0.2).run_check("core", self.workspace)

        self.assertTrue(result.timed_out)
        self.assertFalse(result.passed)

    def test_unconfigured_check_is_blocked_without_running_anything(self):
        runner = LocalRunner()
        result = self.environment(runner).run_check("other", self.workspace)

        self.assertTrue(result.blocked)
        self.assertEqual(runner.specs, [])

    def test_unavailable_docker_runs_no_repository_code(self):
        runner = LocalRunner(unavailable="Docker daemon is not running.")
        result = self.environment(runner).run_check("core", self.workspace)

        self.assertTrue(result.blocked)
        self.assertFalse(result.passed)
        self.assertIn("Docker daemon is not running.", result.error)
        self.assertEqual(runner.specs, [])

    def test_a_failed_boundary_probe_runs_no_repository_code(self):
        runner = LocalRunner(probe_exit_code=1)
        result = self.environment(runner).run_check("core", self.workspace)

        self.assertTrue(result.blocked)
        self.assertEqual([spec.purpose for spec in runner.specs], ["probe"])

    def test_stopping_removes_the_runs_containers_and_blocks_further_checks(self):
        runner = LocalRunner()
        environment = self.environment(runner)

        environment.stop()
        result = environment.run_check("core", self.workspace)

        self.assertEqual(runner.removed_runs, [environment.run_id])
        self.assertTrue(result.blocked)
        self.assertEqual(runner.specs, [])

    def test_acceptance_checks_receive_a_read_only_mount(self):
        runner = LocalRunner()
        self.environment(runner, read_only_mounts={"/host/acceptance": "/acceptance"}).run_check("core", self.workspace)

        self.assertEqual(runner.specs[-1].read_only_mounts, {"/host/acceptance": "/acceptance"})

    def test_containers_are_locked_down(self):
        spec = ContainerSpec(("python", "check.py"), self.workspace, "image:1", "run-1",
                             read_only_mounts={"/host/acceptance": "/acceptance"})

        arguments = docker_arguments(spec, "name")

        text = " ".join(arguments)
        for expected in ("--network none", "--cap-drop ALL", "--read-only", "--user 1000:1000", "--memory",
                         "--cpus", "--pids-limit", "--label coding-harness.run=run-1",
                         "/host/acceptance:/acceptance:ro", f"{self.workspace}:/workspace"):
            self.assertIn(expected, text)
        self.assertEqual(arguments[-3:], ["image:1", "python", "check.py"])

    def test_container_environment_holds_no_host_secrets(self):
        spec = ContainerSpec(("python", "check.py"), self.workspace, "image:1", "run-1")

        with unittest.mock.patch.dict("os.environ", {"OPENAI_API_KEY": "secret-value"}):
            text = " ".join(docker_arguments(spec, "name"))

        self.assertNotIn("OPENAI_API_KEY", text)
        self.assertNotIn("secret-value", text)

    def test_missing_docker_client_is_reported_as_unavailable(self):
        self.assertIn("not found", DockerRunner(docker="no-such-docker").unavailable_reason("image"))


REAL_DOCKER_UNAVAILABLE = DockerRunner().unavailable_reason(DEFAULT_IMAGE)


@unittest.skipIf(REAL_DOCKER_UNAVAILABLE, f"Real Docker tests skipped: {REAL_DOCKER_UNAVAILABLE}")
class RealDockerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=Path.home() / ".cache" if (Path.home() / ".cache").is_dir() else None)
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name).resolve()
        self.workspace.chmod(0o777)

    def run_source(self, source, **options):
        (self.workspace / "check.py").write_text(source, encoding="utf-8")
        environment = ExecutionEnvironment(checks={"core": ("python", "check.py")}, **options)
        return environment, environment.run_check("core", self.workspace)

    def containers(self, run_id):
        return subprocess.run(["docker", "ps", "-aq", "--filter", f"label=coding-harness.run={run_id}"],
                              capture_output=True, text=True).stdout.strip()

    def test_check_is_confined_to_its_workspace(self):
        outside = self.workspace.parent / "host-marker-should-not-be-visible"
        _, result = self.run_source(f"""
import socket, os
from pathlib import Path
Path("written.txt").write_text("workspace")
assert not Path({str(outside)!r}).exists()
assert os.geteuid() != 0
for target in ("/etc/written", "/usr/written"):
    try:
        Path(target).write_text("x")
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
print("confined")
""")
        self.assertTrue(result.passed, result.stdout + result.stderr + str(result.error))
        self.assertTrue((self.workspace / "written.txt").exists())

    def test_failed_check_keeps_its_exit_code(self):
        _, result = self.run_source("print('failing'); raise SystemExit(7)")

        self.assertEqual(result.exit_code, 7)
        self.assertIn("failing", result.stdout)

    def test_timed_out_check_leaves_no_container(self):
        environment, result = self.run_source("import time; time.sleep(60)", timeout_seconds=3)

        self.assertTrue(result.timed_out)
        self.assertEqual(self.containers(environment.run_id), "")

    def test_stopping_a_stuck_check_leaves_no_container(self):
        (self.workspace / "check.py").write_text("import time; time.sleep(60)", encoding="utf-8")
        environment = ExecutionEnvironment(checks={"core": ("python", "check.py")})
        results = []
        worker = threading.Thread(target=lambda: results.append(environment.run_check("core", self.workspace)))
        worker.start()
        for _ in range(200):
            if subprocess.run(["docker", "ps", "-q", "--filter", f"label=coding-harness.run={environment.run_id}",
                               "--filter", "status=running"], capture_output=True, text=True).stdout.strip():
                time.sleep(2)  # past the boundary probe's short-lived container
                if self.containers(environment.run_id):
                    break
            time.sleep(0.1)

        environment.stop()
        worker.join(30)

        self.assertFalse(worker.is_alive())
        self.assertFalse(results[0].passed)
        self.assertEqual(self.containers(environment.run_id), "")

    def syntax_check(self):
        checks = load_projects(Path(__file__).resolve().parents[1] / "projects.toml")["openstock"].checks
        return ExecutionEnvironment(checks={"syntax": checks["syntax"]}).run_check("syntax", self.workspace)

    def test_the_syntax_check_catches_a_file_that_does_not_parse(self):
        (self.workspace / "tests").mkdir()
        (self.workspace / "tests" / "broken.py").write_text("def broken():\nreturn 1\n", encoding="utf-8")

        result = self.syntax_check()

        self.assertFalse(result.passed)
        self.assertIn("broken.py", result.stdout + result.stderr)

    def test_the_syntax_check_passes_valid_code_and_leaves_no_files_behind(self):
        (self.workspace / "tests").mkdir()
        (self.workspace / "tests" / "fine.py").write_text("x = 1\n", encoding="utf-8")

        result = self.syntax_check()

        self.assertTrue(result.passed, result.stdout + result.stderr + str(result.error))
        self.assertEqual([path.name for path in self.workspace.rglob("*.pyc")], [])

    def test_completed_check_leaves_no_container(self):
        environment, _ = self.run_source("print('done')")

        self.assertEqual(self.containers(environment.run_id), "")


if __name__ == "__main__":
    unittest.main()
