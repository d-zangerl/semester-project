# 11: Review and approve a result

**What to build:** A user can run `harness review <id>` at any later time to see the full result and reject or approve it. Approval cannot overwrite newer work by accident.

**Blocked by:** 04 — Start a task on an allowed project in a credential-free workspace; 05 — Reopen a saved task after a restart

**Status:** ready-for-agent

- [ ] Review shows changed files, the final diff, check results, and unfinished work, with failed or unavailable checks kept visible.
- [ ] Nothing reaches the target repository without an explicit approval.
- [ ] Approval is blocked when the target or its commit differs from the task's starting state, and the differences are listed.
- [ ] An explicit force option applies the change anyway.
- [ ] After applying, checks run on a fresh copy of the target, as in Stage 1, and the result is saved.
- [ ] Rejecting leaves the target unchanged and records the decision.
- [ ] Review decisions survive a restart and appear in `harness show`.
- [ ] Tests replace the Stage 1 review tests so the behaviour they cover stays tested, and also cover blocked approval and force.
