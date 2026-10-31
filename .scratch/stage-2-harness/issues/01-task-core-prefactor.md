# 01: Prefactor: put the task core behind the interface

**What to build:** The current task flow runs through a new task core that any interface can call, with no change in what the user sees. This creates the main test seam for Stage 2.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The interface starts a task and receives its result only through the task core.
- [ ] The interface holds no task logic, and a test drives the core without it.
- [ ] A scripted model and an injected check runner can be supplied to the core, so tests need no account, key, or sandbox.
- [ ] Existing scripted-model loop tests that exercise behaviour through the controller move up to the core.
- [ ] All existing behaviour and tests still pass, apart from tests moved as described.
