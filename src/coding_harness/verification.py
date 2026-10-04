from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .execution import CheckResult


@dataclass(frozen=True)
class VerificationResult:
    checks: tuple[CheckResult, ...]
    changed_files: tuple[str, ...]
    diff: str
    diff_truncated: bool

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


class Verification:
    def __init__(self, execution_environment, *, diff_limit_bytes: int = 64 * 1024):
        self.execution_environment = execution_environment
        self.diff_limit_bytes = diff_limit_bytes

    def capture_baseline(self, workspace: str | Path) -> dict[str, bytes]:
        root = Path(workspace).resolve()
        baseline = {}
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or ".git" in path.parts:
                continue
            if any(part.startswith(".harness-") for part in path.relative_to(root).parts):
                continue
            baseline[path.relative_to(root).as_posix()] = path.read_bytes()
        return baseline

    def verify(self, workspace: str | Path, baseline: dict[str, bytes]) -> VerificationResult:
        workspace_path = Path(workspace).resolve()
        changes, diff, truncated = self._diff(baseline, workspace_path, self.diff_limit_bytes)
        names = self._check_names()
        if not names:
            checks = (CheckResult("configured checks", None, "", "", False, False,
                                  blocked=True, error="No configured repository checks are available."),)
        else:
            outcomes = []
            for name in names:
                try:
                    outcomes.append(self.execution_environment.run_check(name, workspace_path))
                except Exception as error:
                    outcomes.append(CheckResult(name, None, "", "", False, False,
                                                blocked=True, error=f"Configured check unavailable: {error}"))
            checks = tuple(outcomes)
        return VerificationResult(checks, tuple(changes), diff, truncated)

    def _check_names(self) -> tuple[str, ...]:
        names = getattr(self.execution_environment, "check_names", ("core",))
        return tuple(names)

    @staticmethod
    def _diff(baseline: dict[str, bytes], workspace: Path, byte_limit: int) -> tuple[list[str], str, bool]:
        changes = []
        chunks = []
        size = 0
        truncated = False
        workspace_files = {p.relative_to(workspace).as_posix(): p for p in workspace.rglob("*")
                           if p.is_file() and not p.is_symlink() and ".git" not in p.parts
                           and not any(part.startswith(".harness-") for part in p.relative_to(workspace).parts)}
        for name in sorted(baseline.keys() | workspace_files.keys()):
            after = workspace_files.get(name)
            old = baseline.get(name, b"")
            new = after.read_bytes() if after else b""
            if hashlib.sha256(old).digest() == hashlib.sha256(new).digest():
                continue
            changes.append(name)
            try:
                old_text, new_text = old.decode("utf-8").splitlines(True), new.decode("utf-8").splitlines(True)
            except UnicodeDecodeError:
                lines = [f"Binary file changed: {name}\n"]
            else:
                lines = difflib.unified_diff(old_text, new_text, fromfile=f"a/{name}", tofile=f"b/{name}")
            for line in lines:
                if size >= byte_limit:
                    truncated = True
                    break
                encoded = line.encode("utf-8")
                if size + len(encoded) > byte_limit:
                    encoded = encoded[:byte_limit - size]
                    truncated = True
                text = encoded.decode("utf-8", errors="ignore")
                chunks.append(text)
                size += len(encoded)
                if truncated:
                    break
            if truncated:
                continue
        diff = "".join(chunks)
        if truncated:
            marker = "\n[diff truncated]\n".encode("utf-8")
            prefix_limit = max(0, byte_limit - len(marker))
            prefix = diff.encode("utf-8")[:prefix_limit].decode("utf-8", errors="ignore")
            remaining = byte_limit - len(prefix.encode("utf-8"))
            diff = prefix + marker[:remaining].decode("utf-8", errors="ignore")
        return changes, diff, truncated
