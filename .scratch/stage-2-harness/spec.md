Status: ready-for-agent

# Stage 2: Capable coding harness

## Problem Statement

As the user of the Stage 1 harness, I can only give it small, single-module changes and watch one process from start to finish. When its checks fail, the task simply ends, because failed checks cannot guide further edits. If the process stops, the work and its history are lost. I cannot cancel a task from elsewhere, or reopen and safely continue it. The model starts with only a file listing, so it struggles to find code across modules, and multi-module demos needed tasks split by hand. The harness accepts any repository path, its task workspaces include files that can hold credentials, and it can overwrite newer work in the target repository on approval.

## Solution

I select an allowed project and submit one feature request. The harness saves the task, gives the model bounded context and navigation tools, and runs an edit-test-fix loop in which failed checks guide further edits within clear limits. Every step is saved, so I can watch progress, cancel, close the application, reopen the task, and resume only from a state the harness has rechecked. At the end I see the changed files, the diff, every check result, and any unfinished work, and I decide whether to apply the result. Repository code only ever runs in a locked-down container. The harness proves this on quote expiry for OpenStock, finding and changing the relevant modules itself from one request with a real model.

## User Stories

### Projects and starting a task

1. As a user, I want to choose from a list of allowed projects, so that tasks cannot run against an arbitrary directory.
2. As a user, I want a project that is not listed to be refused with a clear message, so that a typo or wrong path cannot start work.
3. As a maintainer, I want each allowed project to define its checks, allowed changes, and excluded paths, so that safety rules live in configuration rather than in model behaviour.
4. As a user, I want to submit a feature request in one message, so that I do not have to split it across modules by hand.
5. As a user, I want the request, starting commit, allowed changes, and checks saved before any model request, so that the task's terms are fixed and inspectable.
6. As a user, I want each task to start with a fresh model conversation, so that earlier tasks do not influence it.
7. As a user, I want each task to have its own task workspace, so that unapproved changes cannot leak into another task.

### Credentials and containment

8. As a user, I want credential files left out of the task workspace, so that neither the model nor executed code can read them.
9. As a user, I want required fixtures and a generated configuration supplied to checks, so that checks work without real credentials.
10. As a user, I want my API key kept only in the harness process, so that it never reaches logs, saved state, the workspace, or containers.
11. As a user, I want repository code to run only in a locked-down container, so that it cannot reach my files or the network.
12. As a user, I want a new container for each check, so that one check cannot affect another through leftover state.
13. As a user, I want checks reported as unavailable when Docker is not running, so that no repository code runs without containment.
14. As a user, I want the containment boundary probed before it is relied on, so that a misconfigured container is not trusted.
15. As a user, I want containers left by a crashed run removed at startup, so that nothing keeps running unnoticed.
16. As a user, I want push, merge, and deployment to be unavailable, so that the harness cannot publish anything.

### Model service

17. As a user, I want to configure the model service with a base URL, API key, and model name, so that I can use the LION gateway.
18. As a user, I want the same client to work with local Ollama, so that I have a fallback when the gateway is unavailable.
19. As a user, I want plain HTTP refused for non-local endpoints, so that my key and code are not sent unencrypted.
20. As a user, I want temporary gateway failures retried with increasing waits, so that brief outages do not interrupt my work.
21. As a user, I want a task paused with the reason `model unavailable` after retries run out, so that I can resume it once the service returns.
22. As a user, I want a rejected key to pause the task immediately, so that the harness does not keep sending doomed requests.
23. As a user, I want outages to use no fix attempts or retries, so that service problems do not reduce the budget for real work.
24. As a fellow user of the shared service, I want one model request at a time per harness and a token limit per task, so that usage stays fair.
25. As a user, I want model replies validated whether or not the service constrains their format, so that a malformed reply never executes anything.

### Navigation

26. As a user, I want the model to find where Python symbols are defined and used, so that it can locate the code a feature touches.
27. As a user, I want the model to see a file's imports and the files that import it, so that it can find interacting modules and existing callers.
28. As a user, I want the model to inspect the task workspace's Git status and diff, so that it can see what it has changed.
29. As a user, I want plain text search to keep working, so that templates and other non-Python files can still be found.
30. As a user, I want an unparsable file reported rather than crashing the tool, so that one bad file does not stop the task.
31. As a user, I want navigation tools to be read-only and bounded, so that they cannot change code or flood the context.

### Context

32. As a user, I want each model request kept within a documented size limit, so that long tasks keep working and use the service fairly.
33. As a user, I want a compact repository map in the context, so that the model can orient itself without reading everything.
34. As a user, I want relevant files selected from task terms and dependencies, so that the model sees the code most likely to matter.
35. As a user, I want older history summarised, so that long tasks stay within the limit.
36. As a user, I want summaries written by the harness from saved events, so that repository text cannot manipulate compression through a model.
37. As a user, I want trusted instructions, scope, and acceptance criteria never compressed, so that the task's rules survive a long run.
38. As a user, I want repository text and tool output labelled as untrusted and kept out of the system message, so that text imitating instructions has no authority.

### Edit-test-fix loop and limits

39. As a user, I want the model able to run configured checks mid-task, so that it can test partial work across modules.
40. As a user, I want the model limited to configured check names, so that it can never choose a command.
41. As a user, I want checks to run whenever the model claims completion, so that its claim is never taken on trust.
42. As a user, I want failed check output returned to the model, bounded and labelled untrusted, so that failures guide the next edit safely.
43. As a user, I want a separate limit on fix attempts, so that the loop cannot continue indefinitely.
44. As a user, I want limits on tool actions, model responses, consecutive invalid replies, and tokens, so that a stuck task always stops.
45. As a user, I want edits outside the allowed changes denied with an error, so that the model can correct course without writing anything.
46. As a user, I want a task to end only as completed, failed, cancelled, or paused, so that its state is never ambiguous.
47. As a user, I want completed to require every check to pass, so that the word means something.

### Saved work and progress

48. As a user, I want to see live progress during a run, so that tool actions and checks are not opaque.
49. As a user, I want to list all tasks and their states, so that I can find work to reopen.
50. As a user, I want to inspect a task's details, steps, history, errors, and check results after a restart, so that nothing is lost.
51. As a user, I want to inspect a running task from a second terminal, so that I can check on it without disturbing it.
52. As a user, I want the diff to remain available after a restart, so that I can review the task later.

### Cancellation

53. As a user, I want to cancel from the interface or a second terminal, so that I can always stop a run.
54. As a user, I want a cancel to take effect during a slow model request, so that I do not wait for a reply I no longer want.
55. As a user, I want a late model reply discarded after a cancel, so that it cannot cause further actions.
56. As a user, I want a stuck check stopped by a cancel, so that no container, child process, or further write remains.

### Safe resume

57. As a user, I want resume to recheck the task's permissions and settings, so that revoked access is respected.
58. As a user, I want resume to compare the task workspace with its saved state, including the harness's own edits, so that outside changes are noticed.
59. As a user, I want any mismatch to pause the task with a clear reason, so that it never continues on a state it cannot trust.
60. As a user, I want consumed limits preserved across runs, so that resuming cannot grant extra budget.
61. As a user, I want an interrupted action marked as an uncertain action and shown with the current diff, so that I can see what may have happened.
62. As a user, I want uncertain actions never replayed automatically, so that an edit or check is not repeated without my decision.
63. As a user, I want to choose explicitly between returning to the last checkpoint and accepting the current state, so that the decision is mine and is recorded.

### Review and approval

64. As a user, I want the changed files, final diff, and test and lint results shown together, so that I can judge the result.
65. As a user, I want failed and unavailable checks to stay visible, so that nothing appears to have passed when it did not.
66. As a user, I want unfinished work listed, so that I know what a stopped task did not do.
67. As a user, I want nothing applied to the target repository without my approval, so that I stay in control.
68. As a user, I want approval blocked when the target or its commit has changed since the task started, so that newer work is not overwritten by accident.
69. As a user, I want an explicit force option, so that I can still apply the change after reading what differs.
70. As a user, I want checks rerun on a fresh copy after applying, so that I can see the applied result works.

### Interface

71. As a user, I want plain commands to start, list, show, cancel, resume, and review tasks, so that everything is usable from any terminal.
72. As a user, I want a Claude-style inline interface with compact action lines and a status line, so that working with the harness feels natural.
73. As a user, I want the status line to show actions and tokens used and how to cancel, so that limits and controls are always visible.
74. As a user, I want Esc to cancel a running task, so that stopping is immediate.
75. As a user, I want slash commands for tasks, resume, show, cancel, diff, approve, and reject, so that I can stay in the interface.
76. As a user, I want plain text to start a new task and warn me about an unreviewed one, so that I do not forget earlier work.
77. As a user, I want `/continue` to refine an unapproved task, so that I can give follow-up instructions without losing its workspace and history.
78. As a user, I want `/continue` to keep consumed limits, so that a follow-up cannot bypass them.

### Feature and acceptance

79. As an OpenStock user, I want invalid or past quote expiry dates rejected with a clear error, so that bad dates are not stored.
80. As an OpenStock user, I want expired quotes marked, so that I can tell them apart from active ones.
81. As an OpenStock user, I want to list only active quotes, so that expired ones do not get in the way.
82. As an OpenStock API caller, I want a 400 response for an invalid date, so that the error is handled as a client mistake.
83. As an existing OpenStock caller, I want quotes without an expiry to behave as they do today, so that nothing I rely on breaks.
84. As the author, I want the feature check proven to fail on the starting commit for the expected reason, so that passing it later means something.
85. As the author, I want acceptance checks kept outside the agent's writable area, so that the model cannot weaken them.
86. As the author, I want the real-model run to use a disposable clone, so that the original repository stays usable for repeat runs.
87. As the author, I want any manual help recorded, so that the demonstration is honest.

### Delivery

88. As a reviewer, I want core tests to run without an account, API key, or Docker, so that I can verify core behaviour anywhere.
89. As a reviewer, I want tests needing real Docker reported as skipped when it is down, so that a skip is never mistaken for a pass.
90. As a reviewer, I want Stage 1 tool, error, limit, output, and bug-fix behaviour still working, so that Stage 2 did not regress it.
91. As a reviewer, I want a README covering setup, model settings, design decisions, known limits, and credits, with diagrams matching the implementation, so that I can run and assess the work.

## Implementation Decisions

**Modules**

- **Task core (new):** the single interface behind every user interface, with operations to start, list, show, cancel, resume, continue, and review a task. It owns task lifecycle and outcomes.
- **Agent controller (changed):** advances one run step by step, enforcing limits, the fix-attempt rule, and cancellation checks.
- **Task store (new):** durable tasks, runs, events, checkpoints, consumed limits, and check results.
- **Context manager (new):** builds each model request within the limit, including the repository map, file selection, and history summaries.
- **Repository tools (changed):** gain symbol, dependency, and read-only Git tools, and enforce allowed changes.
- **Execution environment (rewritten):** runs configured checks through a container runner. The `sandbox-exec` implementation is removed, per the Docker ADR.
- **Model client (rewritten):** one OpenAI-compatible client.
- **Verification (changed):** reads its starting state from durable storage rather than memory, and runs acceptance checks mounted from outside the workspace.
- **Interfaces:** plain commands and the inline interface hold no core logic.

**Tasks**

- A task is durable and has one or more runs. The brief's "session" means a durable task; no separate session concept exists.
- Plain input starts a new task. Continue starts a new run under the same unapproved task, keeping its workspace, history, and consumed limits.
- Outcomes are completed, failed, cancelled, or paused.

**Model service**

- Configuration comes from `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `CODING_HARNESS_MODEL`, loaded from a git-ignored environment file with `python-dotenv`. HTTP calls use the standard library rather than an SDK.
- The default service is the LION gateway at `https://lion.aida.cs.technikum-wien.at/v1` with model `Qwen/Qwen3.6-35B-A3B`. The model name stays configurable because it can change. Ollama's OpenAI-compatible endpoint is the fallback.
- Non-loopback endpoints require HTTPS.
- The model returns one JSON action as text, schema-constrained where supported. Native tool calling is not used, and the harness validator always applies.
- Each request has a 300-second timeout, with one request at a time. Timeouts, rate limits, and server errors retry after 5, 15, and 45 seconds, then the task pauses as `model unavailable`. A 401 or 403 pauses immediately. Outages consume no fix attempts or retries.

**Loop and limits**

- A check tool action accepts configured names only. Checks also always run on a completion claim. A failed check returns bounded, untrusted-labelled output and consumes one fix attempt.
- Per-task limits, preserved across runs: 60 tool actions, 80 model responses, 3 consecutive invalid-reply retries, 3 fix attempts, 200,000 tokens. Tokens use API usage figures, and a missing figure is an estimate labelled as one. Denied tool actions count only toward consecutive retries.
- The guard against a final reply before any tool use stays. The regex that denies "no change needed" replies is removed, because failing checks now catch false claims.

**Storage and checkpoints**

- State is one SQLite database with an append-only event table, in a git-ignored harness directory that also holds task workspaces, so both survive a reboot.
- For each tool action: save a `started` record with arguments, run the action, save a `finished` record with the result and a workspace hash, then commit to the workspace's private Git repository, which has no remotes.

**Resume and cancellation**

- Resume rechecks the allowed project's entry and settings, compares the workspace hash, and carries consumed limits over. Any mismatch pauses the task.
- A `started` record with no `finished` record is an uncertain action. The task pauses, shows it with the current diff, and requires an explicit choice: discard to the last checkpoint, or accept the current state.
- Model requests may be re-sent because they do not change the workspace, and their tokens still count.
- Cancel sets a flag in the store and signals the process through its saved process ID. The controller checks the flag before every model request, tool action, and check. Model requests run on a worker thread, so a cancel returns immediately and a late reply is discarded.

**Containment**

- Each check runs in a new Docker container with no network, a non-root user, all capabilities dropped, a read-only root filesystem, and memory, CPU, and process limits. Only the task workspace is mounted, with no secrets in the environment. Acceptance checks are mounted read-only.
- The image is pinned and built ahead of time, including the target's dependencies, because checks have no network.
- Containers carry a run ID label, so cancel can kill and remove them, and startup can remove those left by a crash.
- A startup probe confirms that workspace writes work and that outside writes and network access are blocked. If the daemon or probe fails, checks are `UNAVAILABLE`, no repository code runs, and there is no fallback.

**Projects and workspaces**

- An allowlist configuration file in TOML lists each allowed project's path, checks, allowed changes, and excluded paths.
- Task workspaces are explicit copies with their own Git repository at the starting commit, excluding credentials and adding only required fixtures. Checks use a generated configuration. Harness Git commands are read-only or limited to private snapshots.
- Allowed changes are enforced in application code on every edit and rechecked on resume.
- Approval is blocked when the target or its commit differs from the task's starting state, unless explicitly forced.

**Navigation**

- Symbol and dependency tools use Python's `ast`, and are Python-only. Git status and diff use fixed commands. Text search covers everything else.

**Context**

- The limit is 32,000 estimated tokens per request: up to 4,000 for trusted instructions, scope, and acceptance criteria, which are never compressed and always first; 4,000 for the repository map; 12,000 for selected files; 12,000 for recent history.
- Files are selected by matching task terms and following dependencies. Older steps become a harness-written summary built from saved events, with no model call. Untrusted text sits in labelled blocks and never in the system message.

**Interface**

- Plain commands: start, list, show, cancel, resume, review.
- The inline interface uses `prompt_toolkit` and `rich`, and runs tasks on a background thread. Slash commands: tasks, resume, show, cancel, diff, approve, reject, continue. It is built after the core, so a late or cut interface does not affect required functionality.

**Feature**

- Quote expiry changes OpenStock's quotes module and web application module. The quotes module rejects invalid or past dates and marks expired quotes. The web application returns a 400 for invalid dates and adds an active-only list filter. No expiry behaves as today.
- The run uses a disposable clone at the recorded starting commit, listed as its own allowed project. The original repository stays untouched.

## Testing Decisions

**What makes a good test.** A test asserts external behaviour: task outcomes, what the model was sent, what the user can see, and what changed on disk. It should survive restructuring of internal modules. Direct tests of internal modules are added only for cases the task core cannot reasonably reach, such as unusual parsing inputs, and accept less precise failure location as the trade-off.

**Main seam: the task core,** using a scripted model and a fake container runner, with no account, key, or Docker.

- **Checks and loop, and Stage 1 behaviour:** scripted replies drive tasks, and tests assert outcomes, counters, and visible check results, including that failed or unavailable checks never appear as passed.
- **Navigation:** the scripted model requests a tool action, and the test reads the result it receives. Expected Git state is shown the same way.
- **Context:** tests inspect the messages the scripted model receives, covering the size limit, relevant file selection, trusted content staying first and intact after compression, and untrusted labelling, including text imitating instructions.
- **Session storage:** a new core over the same store simulates a restart, then reopens task details, steps, history, errors, and check results.
- **Cancellation and safe resume:** cancel during a blocked scripted model or fake check, or change the workspace or allowlist between runs, then assert the task pauses or stops, nothing more is written, and consumed limits are unchanged. A simulated crash between `started` and `finished` produces an uncertain action.

**Smaller seams**

- **Container runner:** real-Docker tests cover network and filesystem blocking, resource limits, and no containers or child processes left after a cancel. They are reported as skipped when the daemon is down, and must be run before submission.
- **Model HTTP:** the model client runs against a local stub server, covering retries, immediate pause on 401 or 403, usage figures, and the key staying out of output.
- **Interfaces:** plain commands and the inline interface are tested for routing only, against a fake core.

**Outside the test suite.** The quote expiry acceptance and regression checks run against the harness's result from outside the workspace, in contained execution, with a real model. A runner first proves the feature check fails on the starting commit for the expected reason.

**Prior art.** The existing model task loop tests use scripted models to drive the controller, and this approach moves up to the task core. The existing execution environment tests are the starting point for containment cases, rewritten against the new boundary rather than dropped. The existing CLI and review tests are replaced so that the behaviour they cover stays tested.

## Out of Scope

- Hosted sandboxes, full virtual machines, and a `sandbox-exec` fallback
- Symbol and dependency support for languages other than Python
- Three-way merges on approval
- Concurrent model requests or a shared conversation between tasks
- Native API tool calling
- Push, merge, deployment, and package installation during a task
- A full-screen interface
- Changing the original target repository as part of the demonstration

## Further Notes

- The brief is the Stage 2 assignment PDF in the project's docs, and the service terms are in the LION one-pager beside it. Vocabulary follows the glossary, and the containment decision is in the Docker ADR.
- The one-pager states no context window or schema-output support, so the first issue's model trial must establish both. The context and token numbers may be adjusted from its results, with final values documented.
- The LION service is best-effort, a shared single GPU, and can be limited or revoked at any time, so the local fallback must remain usable for development.
- Part 2 receives formative feedback rather than a separate grade, and gaps can be addressed in Part 3.
