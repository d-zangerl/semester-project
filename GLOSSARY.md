# Coding Harness

This context defines the language of the local coding harness: an interactive tool that uses a language model to modify a configured repository under explicit safety and verification rules.

## Language

**Task**:
One independent coding request, saved durably so it can be inspected, cancelled, and reopened. Each task starts with a fresh model conversation and a disposable task workspace, and carries nothing over from other tasks.
_Avoid_: Session, job, conversation

**Run**:
One process attempt at advancing a task. A task has one or more runs; a resume starts a new run under the same task and consumed limits.
_Avoid_: Execution, attempt

**Checkpoint**:
A saved point in a task from which a later run may safely continue.
_Avoid_: Snapshot, savepoint

**Uncertain action**:
A tool action that began before an interruption and whose outcome is unknown. It is never replayed automatically.
_Avoid_: Failed action, pending action

**Task outcome**:
How a run ends: completed (all checks pass), failed (a limit reached or checks still failing), cancelled, or paused. A model's completion claim alone is never completed.
_Avoid_: Status when referring to the end of a run

**Paused task**:
A task stopped until a person decides or a condition clears, such as a state mismatch, an uncertain action, or an unavailable model. Pausing consumes no fix attempts.
_Avoid_: Failed task, stuck task

**Fix attempt**:
A return to the model after the model claimed completion and a configured check did not pass. Fix attempts have their own limit, separate from retries after invalid model replies.
_Avoid_: Retry

**Task workspace**:
A disposable filesystem copy of the configured repository used for one task before approval.
_Avoid_: Sandbox, target repository

**Target repository**:
The configured local repository to which an explicitly approved diff may be applied.
_Avoid_: Workspace, source repository

**Warehouse**:
A business storage location in OpenStock's inventory domain.
_Avoid_: Location when referring to the business concept

**Transfer**:
The movement of a positive quantity of stock between two distinct warehouses.
_Avoid_: Move, relocation

**Tool action**:
One validated request from the model to navigate or read the task workspace, edit it, or run a configured check.
_Avoid_: Command, operation

**Allowed project**:
A target repository that the harness configuration explicitly permits tasks to run against.
_Avoid_: Any repository path, workspace

**Allowed changes**:
The paths a task may edit, saved with the task and enforced by the harness on every edit and on resume.
_Avoid_: Scope when referring to enforced paths only

**Configured check**:
A repository command selected by configuration and run by the harness regardless of the model's completion claim.
_Avoid_: Acceptance test when it is not task-specific

**Task-specific acceptance evidence**:
A check tied to the user's task, such as a regression test that fails against the task starting state and passes after the change.
_Avoid_: Verification when referring to one test only

**Declared baseline**:
The repository URL and commit identifier recorded as the intended starting provenance, whether or not local Git metadata can verify it.
_Avoid_: Verified commit unless verification actually occurred
