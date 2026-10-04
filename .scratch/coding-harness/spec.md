Status: ready-for-agent

## Problem Statement

The project needs a small, understandable coding harness that behaves like a lightweight coding agent. A user should be able to start the application, enter coding tasks in an interactive chat, and watch the harness inspect and modify a configured Python repository through a language model.

The harness must make the model useful without treating model output as trusted. It must validate every requested action, restrict file and command access to a disposable copy of the configured repository, enforce action and output limits, run configured checks, and show the user the changed files, diff, and verification results. It must preserve failed or unavailable checks instead of claiming success.

The first configured target is the local OpenStock checkout at `./target-repository`, with upstream repository `https://github.com/TMBeaver/openstock` and baseline commit `abc87dccab96c78917b35add542284e61adc5f37`. This commit has been fetched and checked out locally in detached-HEAD state. Future runs must record the actual source revision/state used and must not present the declared commit as the run's actual baseline if the checkout has since changed.

## Solution

Build a simple Python CLI chat application in the project `src` directory. The user starts it with the exact working Python command documented in the README, selects or accepts a configured repository path, and enters a task in the interactive chat. The controller creates a disposable filesystem copy of the repository for that task, sends filtered repository context and the task to a local Ollama model, validates model actions, and returns tool results until the model emits a final response or a safety limit is reached. Document the harness and sandbox prerequisites, dependencies, a secret-free example settings file, and the launch command. Avoid requiring package installation to launch; use Python's standard library for harness functionality where practical, and document any unavoidable runtime prerequisite.

All target-repository code and tests must execute inside an actual OS-enforced contained environment. The specific sandbox runtime is an implementation/configuration choice. A disposable copy, Git worktree, sanitized environment, or subprocess timeout alone is not a sandbox. The sandbox must not expose unrelated host files or credentials, must have network access disabled, and must be restricted to the task workspace and required runtime resources. If the sandbox cannot be created or its restrictions cannot be established, do not run repository code; report the run as blocked rather than falling back to an unrestricted subprocess.

After model completion, the harness runs the configured repository checks in the sandbox, collects changed files and a bounded diff, and reports configured-check results separately from task-specific acceptance evidence. For the real-model demonstration, choose a small cross-module behavior change from the task entered by the user and prepare an immutable acceptance check outside the model-writable workspace. Confirm that check fails on the run's starting copy before model execution, then run it against the result. Keep the task workspace available while the user reviews the complete diff. Approval applies the diff to the configured repository; rejection discards the task workspace. Clean up a successful task workspace only after the user has made that decision; retain failed or blocked workspaces for diagnosis. Each subsequent task starts with a fresh model conversation and task workspace, while the configured repository may contain changes approved by earlier tasks.

The six primary collaborators are `UserInterface`, `AgentController`, `ModelClient`, `RepositoryTools`, `ExecutionEnvironment`, and `Verification`. The implementation should remain understandable and use simple dependency injection rather than introducing a framework or unnecessary abstraction.

## User Stories

1. As a developer, I want to start the harness with a simple Python command, so that I can use it without a build system or complicated installation.
2. As a developer, I want to configure a default repository path, so that the harness knows which local checkout to modify.
3. As a developer, I want to override the repository path at startup, so that I can use the same harness with another local Python repository.
4. As a developer, I want to configure the repository URL and declared baseline identifier, so that each run records its intended target provenance.
5. As a user, I want to start an interactive chat, so that I can enter a coding task after the application has started.
6. As a user, I want to submit several tasks in one application session, so that I do not need to restart the process for every task.
7. As a user, I want each task to run one at a time, so that progress, changes, and approval state are unambiguous.
8. As a user, I want each task to start with a fresh model conversation, so that earlier tasks do not bias later tasks.
9. As a user, I want each task to start with a fresh disposable workspace, so that unapproved changes cannot leak into the next task.
10. As a user, I want to enter `/help`, so that I can discover the available chat controls.
11. As a user, I want to enter `/approve` after reviewing a completed result, so that I explicitly authorize applying the complete diff.
12. As a user, I want to enter `/reject`, so that I can discard the proposed changes and return to a fresh task prompt.
13. As a user, I want to enter `/quit`, so that I can leave the chat cleanly.
14. As a user, I want normal chat input to be interpreted as a new task, so that I can describe the requested coding work naturally.
15. As a user, I want the harness to show progress while a task is running, so that tool calls and verification are not opaque.
16. As a user, I want the model to inspect files through explicit tools, so that it can understand the repository without receiving unrelated host data.
17. As a user, I want the model to list repository files, so that it can discover the repository structure.
18. As a user, I want the model to read repository files, so that it can understand relevant implementation and tests.
19. As a user, I want the model to search repository text, so that it can find symbols, rules, and existing tests efficiently.
20. As a user, I want the model to edit files in the task workspace, so that it can implement the requested change.
21. As a user, I want file paths outside the task workspace to be rejected, so that model input cannot access unrelated files.
22. As a user, I want unknown tools to be rejected, so that an invalid model response cannot execute an unintended action.
23. As a user, I want invalid tool arguments to produce a visible error without execution, so that malformed requests fail safely.
24. As a user, I want repository commands to come from a fixed allowlist, so that the model cannot run arbitrary shell commands.
25. As a user, I want repository commands to run with a timeout and bounded output, so that a stuck or noisy command cannot take over the process.
26. As a user, I want repository commands to run without network access, so that repository code cannot reach unrelated services during execution.
27. As a user, I want preparation and repository execution boundaries to remain separate, so that any future setup operation cannot silently expand runtime permissions.
28. As a user, I want the model protocol to use one strict JSON object per response, so that the controller can validate actions deterministically.
29. As a user, I want malformed model responses to be visible and non-executable, so that the harness never treats arbitrary text as an action.
30. As a user, I want the model to be able to report completion with a final response, so that the action loop has a clear termination signal.
31. As a user, I want a final model response to trigger controller verification rather than automatic success, so that model claims cannot replace actual checks.
32. As a user, I want the configured OpenStock core test to run for every task, so that existing regression behavior remains visible.
33. As a user, I want optional smoke checks to run only when their prerequisites are available, so that unavailable infrastructure is reported rather than misrepresented as a pass.
34. As a user, I want task-specific regression tests added by the model to be checked against the starting workspace, so that a test demonstrates the requested behavior was initially broken.
35. As a user, I want task-specific regression tests to pass after the model change, so that the requested behavior has direct acceptance evidence when such a test exists.
36. As a user, I want configured repository checks and task-specific acceptance evidence reported separately, so that I can distinguish general health from proof of the requested change.
37. As a user, I want failed checks and unavailable checks to remain visible, so that the harness never reports a misleading success.
38. As a user, I want the harness to show changed files, so that I know the scope of the proposed modification.
39. As a user, I want the harness to show a bounded diff, so that I can review the exact proposed changes.
40. As a user, I want output truncation to be marked explicitly, so that I know when the displayed evidence is incomplete.
41. As a user, I want the harness to count actions, denied actions, retries, and responses, so that safety limits are observable.
42. As a user, I want the harness to stop when an action or response limit is reached, so that a repeating model cannot run indefinitely.
43. As a user, I want model, tool, and verification failures to leave diagnostics available, so that I can understand why a task did not complete.
44. As a user, I want successful task workspaces kept until I approve or reject the diff and then cleaned up, so that I can review the result without accumulating temporary files.
45. As a user, I want failed task workspaces retained with their location reported, so that I can diagnose failures.
46. As a user, I want the target repository's current filesystem state copied without an automatic reset, so that approved prior work is preserved.
47. As a user, I want dirty target state copied as-is, so that the harness does not destroy work I made outside the harness.
48. As a user, I want the source state fingerprint recorded before a task, so that the harness can detect target changes before approval.
49. As a user, I want approval to apply the complete diff rather than an implicit subset, so that the approval boundary is explicit.
50. As a user, I want an approved diff applied to the configured repository path, so that the result becomes available to the project I selected.
51. As a user, I want target changes detected before application, so that I can see when the source changed during the task.
52. As a user, I want an approved diff to be force-applied even after a target mismatch, according to the selected Delivery 1 policy, so that the implementation remains simple and the approval decision remains authoritative.
53. As a user, I want the mismatch and force-application behavior reported clearly, so that I understand when concurrent changes may be overwritten.
54. As a user, I want the configured core test run after application, so that the target repository's resulting state is checked.
55. As a developer, I want the Ollama endpoint and model to be configurable, so that local model settings do not require source changes.
56. As a developer, I want example settings without secrets, so that setup is reproducible without exposing credentials.
57. As a developer, I want the harness organized around six narrow collaborators, so that each responsibility is understandable and testable.
58. As a developer, I want scripted model responses for automated controller tests, so that core tests do not require a live Ollama service.
59. As a developer, I want file-tool, invalid-request, failed-command, action-limit, and output-limit tests, so that safety behavior is regression-tested.
60. As a developer, I want a README with setup, configuration, launch instructions, limitations, and diagrams, so that another person can run and understand the harness.
61. As a developer, I want the implementation vocabulary to distinguish a business warehouse from a transport-level location selector, so that domain language remains precise.
62. As a developer, I want the harness to launch with an exact, documented Python command without requiring a separate package installation for the harness itself, so that setup is straightforward.
63. As a user, I want repository code and tests to run only inside an OS-enforced sandbox, so that untrusted code cannot access unrelated host files or credentials.
64. As a user, I want execution to stop safely when the sandbox is unavailable or misconfigured, so that the harness never silently falls back to unsafe execution.
65. As a user, I want the demonstration's acceptance check to be separate from the task workspace and model edits, so that the model cannot make its own verification pass by changing the check.
66. As a user, I want the real-model demonstration to use a task I enter and a small behavior spanning cooperating repository modules, so that it proves an end-to-end dynamic coding workflow.
67. As a developer, I want the demonstration record to state the exact starting revision, task request, expected behavior, and permitted change scope, so that its result can be reproduced and reviewed.

## Implementation Decisions

- The harness is a Python CLI implemented in the project source package and launched with a simple `python3` command.
- The interface is an interactive chat supporting multiple sequential tasks in one process, with exactly one active task at a time.
- A normal task is entered inside the chat. The repository is selected through configuration with an optional startup path override.
- Each task is a new execution: no prior task messages, tool results, diffs, or model conversation are sent to the model.
- The configured repository's current filesystem state is copied into a task workspace. The harness does not automatically reclone, reset, or discard the configured repository.
- The initial configuration points to the local OpenStock checkout, with its upstream URL and declared baseline identifier recorded in settings and run metadata.
- The current checkout has the declared baseline commit available in Git and checked out detached. Each task records the actual starting revision when Git metadata is available, along with source-state information for local modifications; the configured commit remains provenance, not an assertion that later task worktrees are unchanged.
- The user interface supports `/help`, `/approve`, `/reject`, and `/quit`. Ordinary input starts a new task; there is no follow-up clarification conversation within an active task.
- `UserInterface` owns prompts, progress rendering, control commands, result presentation, and approval/rejection input.
- `AgentController` owns task orchestration, model-loop state, action validation, limits, error transitions, and coordination between collaborators.
- `ModelClient` owns Ollama communication and exposes a small provider seam that can be replaced by a scripted model in tests.
- `RepositoryTools` owns list, read, search, and edit operations. Every path is resolved beneath the task workspace and rejected if it escapes that boundary.
- `ExecutionEnvironment` owns the fixed command allowlist and runs every target-repository command inside an OS-enforced contained environment. The runtime is selected through implementation/configuration rather than fixed by this spec. The sandbox exposes only the disposable task workspace and required runtime resources, denies network access, withholds credentials and unrelated host files, applies configured resource/time/output limits, and can be stopped without leaving child processes or writes outside the workspace.
- `Verification` owns baseline evidence, configured checks, task-specific test evidence, changed-file discovery, diff collection, and post-application checks.
- Model responses contain exactly one JSON object with either a tool name and arguments or a final text response. Extra keys, surrounding prose, malformed JSON, unknown tools, and invalid arguments are rejected without execution.
- The controller enforces 30 tool actions, 3 retries, a 60-second command timeout, 64 KiB per output stream, and a separate 40-response ceiling. The user-visible run summary reports the action, denied-action, retry, and response counts.
- Repository commands are fixed by configuration. The OpenStock core test command always runs inside the sandbox; optional smoke checks run only when explicitly configured and their prerequisites are available. No repository command is run if sandbox setup or enforcement fails.
- The model may add or edit regression tests in the task workspace as supporting regression coverage. They do not replace the immutable demonstration acceptance check, which is prepared outside the model-writable workspace, run against the task starting copy before model execution, and run again against the completed copy.
- The end-to-end demonstration uses a user-entered, small cross-module task and a corresponding acceptance check prepared outside the task workspace. Record the task, target starting revision, expected behavior and permitted change scope, exact check, baseline result, final result, configured test results, diff, and any manual setup/help.
- The controller never treats the model's final response as proof of success. Verification results, unavailable checks, and failures remain authoritative and visible.
- Task workspaces remain available while the user reviews the diff and until approval or rejection. After that decision, successful workspaces are removed; failed, blocked, or unavailable runs retain their workspace and diagnostics.
- Approval applies the complete diff to the configured repository. A source fingerprint is recorded at task start; a mismatch is reported, but the Delivery 1 policy automatically force-applies the approved diff.
- The configured repository is never modified before explicit approval. Push, merge, commit, branch mutation, deployment, package installation, arbitrary shell commands, and repository-command network access are disabled.
- The model receives filtered relevant text context, excluding secrets, credentials, binaries, generated files, ignored files, and unrelated host data. It can request additional context through repository tools. The sandbox must independently prevent access to host credentials and paths even if sensitive material is mistakenly present in the task copy.
- Configuration includes the repository path, upstream URL, declared baseline identifier, Ollama endpoint, model name, limits, command allowlist, and workspace policy. Environment overrides may replace machine-specific settings without placing secrets in source.
- Mermaid diagrams in the README show collaborator relationships and the task lifecycle, consistent with the component/data-flow, class-responsibility, and model-tool loop diagrams in the requirements.
- Setup documentation provides dependencies and prerequisites, an example settings file without secrets, and the exact working Python launch command (for example, `python3 src/<entry-point>.py` after the entry point is established).
- The harness is implemented as the project's own application rather than copied from an existing coding harness. The inspected sample-agent scaffold may inform simple interfaces and testing patterns, but is not a runnable base implementation.
- The domain language uses `Warehouse` for the business storage concept, `location` for an input or transport-level selector, `Transfer` for moving positive stock between distinct warehouses, `Task` for one independent coding execution, and `Task workspace` for its disposable copy.

## Testing Decisions

- Tests assert externally observable behavior at the highest practical seam: the controller loop with fake collaborators is the primary integration seam, while focused tests cover path validation, command execution, JSON validation, limits, and verification outcomes.
- File-tool tests cover listing, reading, searching, editing, successful in-scope operations, and rejection of paths outside the task workspace.
- Controller tests use scripted model responses to prove that a valid tool request is executed, its result is returned to the model, and a final response transitions to verification.
- Invalid-request tests cover unknown tools, malformed JSON, extra keys, invalid arguments, denied actions, and retries without accidental execution.
- Execution tests cover successful commands, captured output and exit codes, nonzero exits, output truncation, timeouts, and stop behavior.
- Limit tests cover action exhaustion, response exhaustion, denied-action and retry counting, and clear stopped-run results.
- Verification tests cover baseline-failing task checks, final-passing task checks, configured repository checks, unavailable checks, changed-file reporting, bounded diffs, and post-application checks.
- Approval tests cover workspace retention while awaiting a decision, rejection cleanup, successful application, source mismatch reporting, and the configured automatic force-apply policy.
- Sandbox tests prove that repository commands run with only the task workspace exposed, cannot access host credentials or unrelated paths, have no network access, stop within configured limits, and are not launched when sandbox setup fails.
- The demonstration acceptance check is stored outside the model-writable task workspace. The same check must fail before model execution and pass after the real-model run.
- Core tests must run without Ollama credentials or a live model by using scripted model clients.
- The real-model demonstration uses local Ollama and a user-entered task spanning cooperating target modules; it records the exact external acceptance check, baseline and final results, diff, existing regression results, and any manual setup/help. Automated harness tests remain deterministic.
- Existing OpenStock tests are prior art for repository-level regression behavior; the harness should invoke the configured core test command rather than reimplement OpenStock business rules.
- Tests focus on observable behavior and contracts, not private helper structure or implementation-specific call ordering.

## Out of Scope

- A graphical user interface.
- Multiple concurrent tasks.
- Follow-up clarification messages or conversational history within an active task.
- Long-term persistence of chat history, task history, model messages, or tool results.
- Automatic derivation of a trustworthy acceptance check for every arbitrary user task.
- Treating model-authored repository tests as sufficient proof without baseline and final execution evidence.
- Running repository code or tests directly on the host, or falling back to an unrestricted subprocess when a sandbox is unavailable.
- Arbitrary shell execution, arbitrary network access, package installation, Git mutation, push, merge, deployment, or credential access.
- Automatic repository recloning, resetting, or cleanup of the configured target.
- Hunk-level or file-level selective approval.
- Complex three-way merge logic before applying an approved diff.
- A provider marketplace or broad multi-model abstraction.
- Production-grade authentication, multi-user operation, remote execution, or hosted deployment.
- Changes to OpenStock business behavior as part of building the harness; OpenStock is the target repository for demonstration and verification.
- Creating an ADR unless a later implementation decision is hard to reverse, surprising without context, and based on a genuine trade-off.

## Further Notes

- The local target checkout is currently checked out at the declared OpenStock commit `abc87dccab96c78917b35add542284e61adc5f37` in detached-HEAD state. Normal application execution uses the configured local checkout as-is and does not reclone or reset it.
- The target repository may be dirty. The harness copies its current state and reports that the task started from that state; it does not silently discard unrelated work.
- The task workspace is a disposable copy, not itself a security boundary. Only the sandbox provides execution isolation; file tools still enforce path containment, and repository text/model replies remain untrusted.
- Sandbox runtime and prerequisites must be documented. This spec intentionally does not mandate Docker, `sandbox-exec`, or another particular engine; implementation must choose a genuinely OS-enforced contained environment and demonstrate that its policy restricts execution. The sandbox should expose only the task workspace as writable, avoid exposing the target repository and host home directory to repository processes, disable networking, and avoid passing environment secrets. If these restrictions cannot be verified, execution is blocked. The harness itself should not require installing Python packages just to launch.
- The implementation should remain small enough to understand in one sitting. New collaborators beyond the six named classes require an explicit reason and should normally be simple data structures or test doubles.
- The README should document the local Ollama prerequisite, example configuration, launch command, chat commands, safety limitations, verification semantics, and the force-application trade-off.
- The README should explain that the requirements' first diagram shows the overall components and data flow, the second shows suggested class responsibilities and collaborators, and the third shows the action/observation loop and final verification. The implementation diagrams must reflect the actual system.
- The local issue tracker uses `Status: ready-for-agent` for this specification.
