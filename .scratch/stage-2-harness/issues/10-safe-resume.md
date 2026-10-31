# 10: Resume only from a trusted state

**What to build:** A user can run `harness resume <id>` after a crash, cancel, or outage. The task continues only after permissions and the saved working-copy state are rechecked, and otherwise pauses with a clear reason for the user to decide.

**Blocked by:** 05 — Reopen a saved task after a restart; 06 — Let failed checks guide fixes within limits

**Status:** ready-for-agent

- [ ] Each tool action saves a `started` record with arguments, then a `finished` record with the result and a workspace hash, and each checkpoint commits to the workspace's private Git repository.
- [ ] A resume starts a new run under the same task, with consumed limits carried over unchanged.
- [ ] Resume rechecks the allowed project's entry and settings, and compares the workspace hash, including the harness's own edits.
- [ ] Any mismatch makes the task a paused task with a clear reason.
- [ ] A `started` record with no `finished` record is an uncertain action. The task pauses, shows it with the current diff, and never replays it automatically.
- [ ] `--discard-to-checkpoint` restores the last checkpoint, and `--accept-current-state` continues from the current files. Both choices are recorded.
- [ ] A task whose model stays unavailable, or whose key is rejected, pauses with the reason shown and consumes no fix attempts or retries. It can be resumed later.
- [ ] Re-sent model requests are allowed, and their tokens still count.
- [ ] Scripted tests through the task core cover a clean resume, a changed workspace, a changed allowlist, a simulated crash producing an uncertain action, both choices, an outage pause, and preserved limits.
