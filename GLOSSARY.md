# Coding Harness

This context defines the language of the local coding harness: an interactive tool that uses a language model to modify a configured repository under explicit safety and verification rules.

## Language

**Task**:
One independent coding request and execution. Each task starts with a fresh model conversation and a disposable task workspace.
_Avoid_: Session, job, conversation

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
One validated request from the model to list, read, search, edit, or run a configured check.
_Avoid_: Command, operation

**Configured check**:
A repository command selected by configuration and run by the harness regardless of the model's completion claim.
_Avoid_: Acceptance test when it is not task-specific

**Task-specific acceptance evidence**:
A check tied to the user's task, such as a regression test that fails against the task starting state and passes after the change.
_Avoid_: Verification when referring to one test only

**Declared baseline**:
The repository URL and commit identifier recorded as the intended starting provenance, whether or not local Git metadata can verify it.
_Avoid_: Verified commit unless verification actually occurred
