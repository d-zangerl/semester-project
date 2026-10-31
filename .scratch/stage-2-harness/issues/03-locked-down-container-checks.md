# 03: Run checks in locked-down containers

**What to build:** A user running a task sees its configured check run in a new, locked-down Docker container, or sees `UNAVAILABLE` with no repository code run. This replaces `sandbox-exec`, per the Docker ADR.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Each check runs in a new container with no network, a non-root user, all capabilities dropped, a read-only root filesystem, and memory, CPU, and process limits.
- [ ] Only the task workspace is mounted, and the container environment holds no secrets.
- [ ] A pinned image with the target's dependencies is built ahead of time by a documented command.
- [ ] A probe confirms that workspace writes work and that outside writes and network access are blocked. A failed probe gives `UNAVAILABLE`.
- [ ] A missing or stopped daemon gives `UNAVAILABLE` with a clear reason, and there is no fallback.
- [ ] Containers carry a run ID label. Stopping a run kills and removes its container, and startup removes containers left by a crashed run.
- [ ] A read-only mount is available for acceptance checks kept outside the workspace.
- [ ] Timeouts and bounded output behave as in Stage 1, and failed, timed-out, or unavailable checks never appear as passed.
- [ ] The `sandbox-exec` implementation is removed, and its containment tests are rewritten against the new boundary.
- [ ] Core tests use a fake container runner, and real-Docker tests are visibly reported as skipped when the daemon is down.
