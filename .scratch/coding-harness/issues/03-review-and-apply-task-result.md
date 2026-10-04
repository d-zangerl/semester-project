# 03: Reviewing and applying a task result

**What to build:** After a task completes, the user can inspect its complete diff and explicitly approve applying it to the configured repository or reject it. The harness reports source changes, follows the agreed approval behavior, verifies the applied result, and cleans up or retains the task workspace according to the outcome.

**Blocked by:** 02 — Completing a coding task through validated model tools.

**Status:** ready-for-agent

- [ ] The complete bounded diff and check results remain available for review until the user chooses approval or rejection.
- [ ] Rejection leaves the configured target unchanged and removes the successful task workspace.
- [ ] Approval applies the complete diff to the configured target only after an explicit user decision.
- [ ] If the target changed since task creation, the harness reports the mismatch; explicit approval still authorizes the agreed force-apply behavior and the warning is visible before application.
- [ ] After application, the configured core check runs against a fresh copy of the updated target inside the OS-enforced sandbox; repository code is never executed directly from the configured target.
- [ ] The post-application check's captured output and exit code are reported, and a failure is not reported as success.
- [ ] Failed, blocked, or unavailable runs retain their task workspace and report its location for diagnosis.
- [ ] Automated tests cover review-state retention, rejection, approval, mismatch reporting, post-application verification, and cleanup/retention outcomes.
