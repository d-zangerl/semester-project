# 08: Keep every model request within the context limit

**What to build:** A long task keeps working because every model request stays within a documented size limit, while trusted terms stay intact and untrusted text stays labelled.

**Blocked by:** 05 — Reopen a saved task after a restart; 07 — Let the model navigate by symbols, dependencies, and Git

**Status:** ready-for-agent

- [ ] Each request stays within 32,000 estimated tokens: up to 4,000 trusted, 4,000 repository map, 12,000 selected files, and 12,000 recent history.
- [ ] Limits change only if the model trial shows they must, and the final values are documented.
- [ ] The repository map lists files and top-level symbols within its budget.
- [ ] Files are selected by matching task terms and following dependencies.
- [ ] Older steps become a summary written by the harness from saved events, with no model call.
- [ ] Trusted instructions, scope, and acceptance criteria are never compressed and always come first.
- [ ] Repository text and tool output sit in labelled untrusted blocks and never in the system message.
- [ ] Scripted tests inspect the messages the model receives, covering file selection, the size limit, and compression keeping task constraints and untrusted text separate, including text imitating instructions.
