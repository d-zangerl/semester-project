# 02: Run a task through the LION gateway, and trial the model

**What to build:** A user can configure the LION gateway or local Ollama and run a task through either. A recorded trial shows whether the real model can complete an unsplit two-module task before later work depends on it.

**Blocked by:** None (can start immediately). The trial needs the user's API key in the git-ignored environment file.

**Status:** ready-for-agent

- [ ] The client uses any OpenAI-compatible endpoint, configured by `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `CODING_HARNESS_MODEL`, loaded with `python-dotenv`.
- [ ] The environment file is git-ignored before it is needed, and a secret-free example is committed.
- [ ] Non-loopback endpoints require HTTPS, and Ollama's OpenAI-compatible endpoint works.
- [ ] Timeouts, rate limits, and server errors retry after 5, 15, and 45 seconds, then raise a distinct `model unavailable` error. A 401 or 403 raises immediately without retrying.
- [ ] Each request has a 300-second timeout, and only one request runs at a time.
- [ ] Token usage is returned for each request, and a missing figure is reported as an estimate.
- [ ] Schema-constrained output is requested where supported, and the validator applies to every reply either way.
- [ ] The key never appears in logs or output, proven by a test.
- [ ] Tests against a local stub server cover the above with no external network.
- [ ] A recorded trial with one unsplit two-module task reports whether the model completes it, plus observed latency, schema-output support, and any context-size errors.
- [ ] If the trial fails repeatedly, the result is reported to the user before dependent tickets start.
