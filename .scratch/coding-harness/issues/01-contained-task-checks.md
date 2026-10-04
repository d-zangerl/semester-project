# 01: Running configured checks in a contained task workspace

**What to build:** A user can start the harness, select the configured repository, and run its configured core check against a fresh disposable copy inside a verified OS-enforced contained environment. The harness reports captured output and exit status and refuses to execute repository code if it cannot establish containment.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] The user can launch the Python CLI using the documented command, enter a task, and use the configured default repository or a startup repository-path override.
- [x] The harness implementation is runnable from the project source directory with the documented Python launch command.
- [x] Each task gets a disposable copy of the configured repository; the configured target is not modified by task execution.
- [x] The configured core check runs only inside an OS-enforced contained environment restricted to the task workspace and required runtime resources, with network access disabled and unrelated host files and credentials unavailable.
- [x] A missing or unverifiable sandbox blocks repository execution; the harness does not fall back to a plain subprocess or rely on the copy itself as isolation.
- [x] The user sees the command's bounded output, exit code, timeout or blocked state, and any output truncation.
- [x] A stuck command can be stopped, including its child processes, without leaving child processes running or allowing later writes outside the task workspace.
- [x] Automated tests demonstrate successful execution in the configured sandbox, fail-closed behavior when the sandbox cannot be established, and safe stopping of a command and its child processes.

## Comments

- Implemented and accepted on `integration/coding-harness`. The harness suite passed (7 tests), and the configured OpenStock core check passed (23 checks, 0 failures) against the existing local database copy.
- The legacy `py -3 import_access.py` prerequisite could not run on this macOS host (`py` and `pyodbc` are unavailable); an existing local database was subsequently found and left unchanged.
