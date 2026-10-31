# 07: Let the model navigate by symbols, dependencies, and Git

**What to build:** During a task, the model can find where a symbol is defined and used, see which modules depend on each other, and inspect the Git state of the task workspace, all through read-only tools.

**Blocked by:** 04 — Start a task on an allowed project in a credential-free workspace

**Status:** ready-for-agent

- [ ] A symbol tool action returns Python definitions and references, using `ast`.
- [ ] A dependency tool action returns a file's imports and the files that import it, using `ast`.
- [ ] Git status and diff tool actions read the workspace's private repository using fixed commands only.
- [ ] All new tool actions validate arguments, stay inside the workspace, respect exclusions, and bound their output.
- [ ] A file that cannot be parsed is reported rather than crashing the tool, and text search still covers non-Python files.
- [ ] Scripted tests through the task core find the modules, symbols, and dependencies needed for a quote expiry task on an OpenStock-shaped fixture, and show the expected Git state.
