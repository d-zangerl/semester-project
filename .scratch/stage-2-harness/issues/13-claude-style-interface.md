# 13: Work in a Claude-style interface

**What to build:** A user can run tasks in an inline terminal interface with compact action lines, a status line, slash commands, and follow-up instructions, as a thin layer over the task core.

**Blocked by:** 09 — Cancel a running task; 10 — Resume only from a trusted state; 11 — Review and approve a result

**Status:** ready-for-agent

- [ ] The interface uses `prompt_toolkit` and `rich`, and the plain commands keep working.
- [ ] Tool actions and checks appear as compact lines, and the status line shows the task, actions, tokens, and how to cancel.
- [ ] The prompt stays usable while a task runs on a background thread, and Esc cancels.
- [ ] `/tasks`, `/resume`, `/show`, `/cancel`, `/diff`, `/approve`, and `/reject` behave like their plain-command equivalents.
- [ ] Plain text starts a new task, with a warning if an unreviewed task exists.
- [ ] `/continue <instruction>` starts a new run under the same unapproved task, keeping its workspace, history, and consumed limits.
- [ ] Failed and unavailable checks stay as visible as in the plain commands.
- [ ] The interface holds no core logic, and tests cover routing against a fake core, plus `/continue` limits through the real core.
