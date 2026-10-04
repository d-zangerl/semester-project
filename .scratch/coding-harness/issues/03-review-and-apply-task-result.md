# 03: Reviewing and applying a task result

**What to build:** After a task completes, the user can inspect its complete diff and explicitly approve applying it to the configured repository or reject it. The harness reports source changes, follows the agreed approval behavior, verifies the applied result, and cleans up or retains the task workspace according to the outcome.

**Blocked by:** 02 — Completing a coding task through validated model tools.

**Status:** ready-for-agent

- [x] The complete bounded diff and check results remain available for review until the user chooses approval or rejection.
- [x] Rejection leaves the configured target unchanged and removes the successful task workspace.
- [x] Approval applies the complete diff to the configured target only after an explicit user decision.
- [x] If the target changed since task creation, the harness reports the mismatch; explicit approval still authorizes the agreed force-apply behavior and the warning is visible before application.
- [x] After application, the configured core check runs against a fresh copy of the updated target inside the OS-enforced sandbox; repository code is never executed directly from the configured target.
- [x] The post-application check's captured output and exit code are reported, and a failure is not reported as success.
- [x] Failed, blocked, or unavailable runs retain their task workspace and report its location for diagnosis.
- [x] Automated tests cover review-state retention, rejection, approval, mismatch reporting, post-application verification, and cleanup/retention outcomes.

## Comments

- Implemented and accepted on `integration/coding-harness`. The harness suite passes (34 tests), and a live approve run against a scratch repository with local `qwen2.5-coder:7b` applied the change and passed the post-apply sandbox check.
- Limit: the harness has no delete tool, so approved changes are creations and edits.
