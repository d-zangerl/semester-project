# 05: Reopen a saved task after a restart

**What to build:** A user can close the application and later run `harness list` and `harness show <id>` to see a task's details, steps, history, errors, and check results, including from a second terminal while a run is active.

**Blocked by:** 01 — Prefactor: put the task core behind the interface; 04 — Start a task on an allowed project in a credential-free workspace

**Status:** ready-for-agent

- [ ] A task's request, project, starting commit, allowed changes, checks, runs, consumed limits, and outcome are saved in SQLite before and during execution.
- [ ] Steps and results are saved as they happen in an append-only event history.
- [ ] The starting state needed for diffs survives a restart, replacing the in-memory baseline.
- [ ] `harness list` shows all tasks and their states.
- [ ] `harness show <id>` shows saved details, steps, history, errors, check results, and the diff.
- [ ] Both commands work during an active run in another terminal.
- [ ] Saved state contains no API key, proven by a test.
- [ ] A test creates a new task core over the same store to simulate a restart, and reopens everything above.
