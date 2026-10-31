# 09: Cancel a running task

**What to build:** A user can press Ctrl-C or run `harness cancel <id>` from a second terminal to stop a task, even during a slow model request or stuck check, leaving no container, child process, or further write.

**Blocked by:** 03 — Run checks in locked-down containers; 05 — Reopen a saved task after a restart; 06 — Let failed checks guide fixes within limits

**Status:** ready-for-agent

- [ ] Cancel sets a flag in the store and signals the process using its saved process ID.
- [ ] The controller checks the flag before every model request, tool action, and check.
- [ ] Model requests run on a worker thread, so a cancel returns immediately and a late reply is discarded.
- [ ] A cancelled task has the outcome cancelled, shown by `harness show`.
- [ ] A core test cancels during a blocked scripted model and a fake stuck check, and asserts no further actions or writes.
- [ ] A real-Docker test cancels a stuck check, and asserts no container or child process remains.
