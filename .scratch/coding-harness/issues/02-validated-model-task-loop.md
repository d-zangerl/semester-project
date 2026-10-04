# 02: Completing a coding task through validated model tools

**What to build:** A user can submit an independent coding task in the interactive CLI and have local Ollama inspect and edit the disposable task workspace through bounded repository tools. The harness validates every model action, runs configured checks, and presents progress, changed files, a diff, and truthful check results without applying changes to the configured target.

**Blocked by:** 01 — Running configured checks in a contained task workspace.

**Status:** ready-for-agent

- [ ] The implementation uses the six named collaborators `UserInterface`, `AgentController`, `ModelClient`, `RepositoryTools`, `ExecutionEnvironment`, and `Verification`; any additional architectural collaborator has a documented reason.
- [ ] The harness is the project's own implementation and is not built by starting from an existing coding harness.
- [ ] The interactive CLI accepts multiple sequential tasks in one process, one active task at a time; each task starts with a fresh model context and workspace, without carrying over prior conversation or tool results.
- [ ] The model uses the configured local Ollama endpoint/model and returns exactly one strict JSON tool-action or final-response object; malformed, ambiguous, unknown, or invalid requests never execute.
- [ ] The controller sends the task and permitted repository context to the model, executes only validated allowed requests, and returns each tool result or a clear error; invalid requests produce a visible error without executing an action.
- [ ] The user can observe progress as the model uses list, read, search, and edit tools that enforce task-workspace path containment.
- [ ] Automated file-tool tests prove intended in-scope list/read/search/edit behavior and reject paths outside the task workspace without accessing or changing those paths.
- [ ] Only fixed, configured repository checks can execute; arbitrary shell commands, network access, Git mutation, package installation, push, merge, and deployment are unavailable.
- [ ] The controller enforces the configured action, retry, response, command-time, and output limits, stops further actions when a limit is reached, and visibly reports action, denied-action, retry, and response counts.
- [ ] On model completion, configured checks run in the contained environment and the user sees progress, changed files, a bounded diff, captured check output and exit codes, and failures or unavailable checks.
- [ ] The model's final response cannot override failed or unavailable verification, and this task flow does not modify the configured repository.
- [ ] A nonzero command exit and its output remain visible and cannot be reported as a passing check.
- [ ] Scripted-model tests prove a valid tool request receives the tool result and cover invalid requests, limits, failed checks, and visible verification results without requiring Ollama.
