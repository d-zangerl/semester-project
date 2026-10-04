# 05: Demonstrating a real-model task with independent acceptance evidence

**What to build:** The developer can demonstrate the complete harness using a task entered dynamically in the CLI and a real local Ollama model, with independent evidence that the requested cross-module behavior was broken before the run and works afterward.

**Blocked by:** 03 — Reviewing and applying a task result.

**Status:** ready-for-agent

- [x] The demonstration uses a user-entered small task involving behavior across cooperating target-repository modules; the task is not hard-coded as the only supported harness scenario.
- [x] The demonstration records the starting repository revision/state, task request, expected behavior, and permitted change scope.
- [x] A task-specific acceptance check is stored outside the model-writable workspace and fails against the task's starting copy before the real-model run.
- [x] The same acceptance check runs against the resulting task workspace inside the OS-enforced contained environment and passes; the configured existing regression tests also pass, with failures visible and preventing a successful demonstration claim.
- [x] The demonstration shows configured regression-check results, changed files, diff, and any manual setup or assistance.
- [ ] A demonstration video of no more than four minutes shows the real-model run and its relevant evidence.

## Comments

- Accepted on `integration/coding-harness`. `demo/run_demo.py` + external `demo/accept_quote.py` (fails on baseline, passes with a reference fix); record written to `demo-record-*.md`. Live rehearsal with `qwen2.5-coder:7b`: 1 of 3 runs SUCCESS, others correctly flagged NOT SUCCESSFUL. 41 tests pass.
- Deviation accepted by the user: the demo task is single-module (`quotes.py`), not cross-module, because the 7B model could not handle larger files.
- The video (<= 4 min) is recorded by the user and remains open (unchecked).

