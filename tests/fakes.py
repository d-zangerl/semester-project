"""Shared test doubles for the container boundary."""
from __future__ import annotations

import subprocess
import sys

from src.coding_harness.execution import CheckResult


class LocalRunner:
    """Runs check commands as plain local processes, so core tests need no Docker. Test use only."""

    def __init__(self, unavailable=None, probe_exit_code=0):
        self.unavailable = unavailable
        self.probe_exit_code = probe_exit_code
        self.specs = []
        self.removed_runs = []

    def unavailable_reason(self, image):
        return self.unavailable

    def run(self, spec, timeout_seconds, output_limit_bytes):
        self.specs.append(spec)
        if spec.purpose == "probe":
            return CheckResult("", self.probe_exit_code, "", "probe failed" if self.probe_exit_code else "", False, False)
        command = [sys.executable if spec.command[0] == "python" else spec.command[0], *spec.command[1:]]
        try:
            done = subprocess.run(command, cwd=spec.workspace, capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return CheckResult("", None, "", "", False, False, timed_out=True)
        stdout, stderr = done.stdout[:output_limit_bytes], done.stderr[:output_limit_bytes]
        return CheckResult("", done.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace"),
                           len(done.stdout) > output_limit_bytes, len(done.stderr) > output_limit_bytes)

    def remove_run(self, run_id):
        self.removed_runs.append(run_id)
