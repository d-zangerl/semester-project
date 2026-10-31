# 06: Let failed checks guide fixes within limits

**What to build:** During a task, the model can run configured checks, and a completion claim with failing checks returns it to work. The task always ends with a clear outcome, either when checks pass or when a limit stops it.

**Blocked by:** 03 — Run checks in locked-down containers; 05 — Reopen a saved task after a restart

**Status:** ready-for-agent

- [ ] A check tool action accepts configured names only. Other names are denied, and no model-chosen command can run.
- [ ] Checks always run on a completion claim, whatever the model says.
- [ ] A failed check returns bounded output labelled untrusted, and a completion claim with failing checks consumes one fix attempt.
- [ ] Defaults are 60 tool actions, 80 model responses, 3 consecutive invalid-reply retries, 3 fix attempts, and 200,000 tokens. Reaching a limit stops the task visibly.
- [ ] Denied tool actions count only toward consecutive retries.
- [ ] Outcomes are exactly completed, failed, cancelled, or paused, and completed requires every check to pass.
- [ ] The guard against a final reply before any tool use stays, and the regex denying "no change needed" replies is removed.
- [ ] The result shows changed files, the diff, test and lint results, and unfinished work, with failed or unavailable checks kept visible.
- [ ] Consumed limits and outcomes are saved and shown by `harness show`.
- [ ] Scripted tests through the task core cover fail-then-fix, running out of fix attempts, each limit, and failed or unavailable checks never appearing as passed.
- [ ] Stage 1 tool, error, action-limit, output-limit, and bug-fix tests still pass.
