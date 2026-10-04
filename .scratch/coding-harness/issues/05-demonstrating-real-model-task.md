# 05: Demonstrating a real-model task with independent acceptance evidence

**What to build:** The developer can demonstrate the complete harness using a task entered dynamically in the CLI and a real local Ollama model, with independent evidence that the requested cross-module behavior was broken before the run and works afterward.

**Blocked by:** 03 — Reviewing and applying a task result.

**Status:** ready-for-agent

- [ ] The demonstration uses a user-entered small task involving behavior across cooperating target-repository modules; the task is not hard-coded as the only supported harness scenario.
- [ ] The demonstration records the starting repository revision/state, task request, expected behavior, and permitted change scope.
- [ ] A task-specific acceptance check is stored outside the model-writable workspace and fails against the task's starting copy before the real-model run.
- [ ] The same acceptance check runs against the resulting task workspace inside the OS-enforced contained environment and passes; the configured existing regression tests also pass, with failures visible and preventing a successful demonstration claim.
- [ ] The demonstration shows configured regression-check results, changed files, diff, and any manual setup or assistance.
- [ ] A demonstration video of no more than four minutes shows the real-model run and its relevant evidence.
