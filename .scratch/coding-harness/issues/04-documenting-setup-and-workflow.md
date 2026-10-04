# 04: Documenting setup and the implemented workflow

**What to build:** A new user can understand the harness's prerequisites, configure it without committing secrets, launch the working application, and follow diagrams that accurately explain its implemented components and task flow.

**Blocked by:** 03 — Reviewing and applying a task result.

**Status:** ready-for-agent

- [ ] The README lists required dependencies and sandbox/model prerequisites, provides secret-free example settings, and gives the exact tested launch command.
- [ ] The README explains repository selection, interactive task entry, available chat controls, configured checks, approval/rejection, and result/workspace lifecycle.
- [ ] Safety documentation explains the actual containment boundary, the fail-closed behavior, the configured action/retry/time/output limits, and disabled capabilities; it does not imply that a disposable copy or Git worktree is itself a sandbox.
- [ ] Verification documentation distinguishes configured repository checks from task-specific acceptance evidence and explains how failed/unavailable checks are shown.
- [ ] Mermaid diagrams show the component/data flow, collaborator responsibilities, and model-tool loop through final verification, matching the implemented behavior.
- [ ] Documentation instructions and launch examples are checked against the runnable application.
