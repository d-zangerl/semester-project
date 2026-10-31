# 04: Start a task on an allowed project in a credential-free workspace

**What to build:** `harness start <project> "<request>"` runs a task only on an allowed project, in a task workspace that holds no credentials, has private Git history, and accepts edits only within the allowed changes.

**Blocked by:** 01 — Prefactor: put the task core behind the interface

**Status:** ready-for-agent

- [ ] A TOML allowlist defines each allowed project's path, checks, allowed changes, and excluded paths.
- [ ] A project not listed is refused with a clear message, and no workspace is created.
- [ ] Task workspaces live in a git-ignored harness directory and survive a reboot.
- [ ] Credentials and configured excluded paths are absent from the workspace, so neither file tools nor executed code can read them, proven by a test.
- [ ] Required fixtures are added explicitly and checks use a generated configuration, and the OpenStock core check still runs.
- [ ] The workspace has its own Git repository at the recorded starting commit, with no remotes.
- [ ] Edits outside the allowed changes are denied in application code, return an error to the model, and write nothing.
- [ ] Progress prints live during `harness start`.
- [ ] Tests run through the task core with a scripted model.
