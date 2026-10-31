# Docker replaces sandbox-exec for repository code

Stage 1 contained repository code with macOS `sandbox-exec`, which is tested but macOS-only and deprecated by Apple. We replace it with one new, locked-down Docker container per check, using a pinned image built ahead of time because checks run with no network. Moving the model to a hosted service freed the local memory that made a container VM unattractive.

If the Docker daemon is unavailable, checks report `UNAVAILABLE` and no repository code runs. We deliberately keep no `sandbox-exec` fallback, so there is only one containment boundary to reason about and test. Running checks now requires Docker, and core tests use a fake container runner so they still pass without it; tests against real Docker are reported as skipped when the daemon is down.
