# Coding Harness

The harness runs a configured repository check against a disposable copy of a
local repository. Ticket 01 provides the contained check runner; model-backed
editing and review controls are added by later implementation tickets.

## Run

From the project root, use Python 3 and launch:

```bash
python3 src/main.py
```

The default target is `./target-repository`. Select another repository with
`--repository /path/to/repository` or set `CODING_HARNESS_REPOSITORY`.
The CLI asks for a task description and runs the configured core check,
`python3 tests/test_core.py`, in a fresh task workspace. The check's output and
exit status are shown. A successful workspace is removed; a failed, timed-out,
or blocked workspace is retained and its path is printed.

OpenStock's core test requires the local, git-ignored
`target-repository/data/openstock.db`; that database is not included in the
source checkout. If it is missing, the harness reports the test's nonzero exit
status rather than treating the check as successful. The legacy
`import_access.py` importer is Windows-only and is not run automatically.

## Containment prerequisite

Repository code and tests run only under the macOS OS-enforced
`sandbox-exec` sandbox. The harness verifies that the task workspace is
writable, a file outside it is inaccessible, and network socket access is
blocked before it launches a repository check. The policy permits the task
workspace as writable and the Python/system runtime paths needed to execute
the check. Check execution is denied if the sandbox runtime is missing or
the boundary probe fails; there is no unrestricted subprocess fallback.

The check has a 60-second timeout and captures at most 64 KiB from each output
stream. On timeout, the process group is terminated; the sandbox also denies
process-group changes so children cannot escape that cleanup. The target
repository is never used as the check's working directory.
