# 12: Deliver quote expiry with a real model

**What to build:** From one unsplit request, the harness finds and changes the relevant OpenStock modules with a real model, and protected acceptance and regression checks pass on the result.

**Blocked by:** 02 — Run a task through the LION gateway, and trial the model; 06 — Let failed checks guide fixes within limits; 07 — Let the model navigate by symbols, dependencies, and Git; 08 — Keep every model request within the context limit; 10 — Resume only from a trusted state; 11 — Review and approve a result

**Status:** ready-for-agent

- [ ] The target repository, exact starting commit, feature request, allowed changes, and acceptance commands are saved with the task.
- [ ] Acceptance and regression checks are kept outside the agent's writable area, and run against the result in contained execution.
- [ ] Checks cover invalid and past expiry dates rejected with a clear error, expired quotes marked, no expiry behaving as today, a 400 from the web application, an active-only list filter, and existing callers still working.
- [ ] A runner proves the feature check fails on the starting commit for the expected reason, before the model runs.
- [ ] The run uses a disposable clone listed as its own allowed project, and the original target repository stays untouched.
- [ ] The final diff is reviewed, acceptance and regression checks pass, and any manual help is recorded.
- [ ] The Stage 1 demo runners are removed.
- [ ] A failed run is reported honestly, with what would need to change.
