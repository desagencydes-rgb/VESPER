---
name: code-review-ultra-unavailable
description: The owner cannot run /code-review ultra on VESPER — repo and files are too big; use a path-scoped local review instead
metadata:
  type: project
---

The owner reported on 2026-08-18 that **`/code-review ultra` cannot be run on
VESPER — the repo and files are too big for it.** Do not plan a session around
it, and do not put "wait for the ultra review" in front of other work.

**Why:** ultra bundles the branch for a cloud multi-agent pass, and that is what
the size limit hits. The local `/code-review` skill is a different mechanism and
runs fine when given a path target, so reviews are still available — just
narrower.

**How to apply:** when a fresh module wants an adversarial pass, run the local
review scoped to the file (`/code-review high core/<module>.py`), and report it
as *a* review rather than as the gate clearing. Never serialize a day behind it.
See [[lead-with-the-critical-path-not-the-interesting-thing]].
