---
name: overnight-autonomous-sessions
description: "How the owner runs overnight sessions — work unblocked items to done, then a fixed wrap-up, then power off"
metadata: 
  node_type: memory
  type: user
  originSessionId: c1e3b554-00df-4078-b85d-b38ba177f6fb
  modified: 2026-08-18T00:59:32.512Z
---

The owner hands over the machine overnight and expects **genuine advancement,
not busywork**. Their instruction on 2026-08-18: work an unblocked item to done,
prove it with *"tests, stress tests, studies, analysis, data"*, then **move to
the next thing held by nothing and repeat until genuinely blocked** — and they
push back if the chosen work looks small. When I opened with a batch of CI
checks they asked *"is the ci checks the only thing you can do? don't be lazy"*,
and they were right: F6 was the real next item in the build order.

**The wrap-up is part of the job, not an afterthought.** In their words: memory
files, plans, updates, GitHub, repo and folder health, laptop verification, then
shut down — with *"no missing, problems or mistakes"*.

**Why:** they wake up to the result and cannot ask a follow-up question in the
night. Anything unrecorded is lost, and anything half-finished reads as broken.

**How to apply:**
- Pick from `IMPLEMENTATION_SEQUENCE.md`'s build order, not from whatever is
  easiest to verify. Check what is genuinely blocked before assuming.
- Commit each increment green — full sweep between groups — so a late failure
  never leaves the tree red at shutdown.
- Wrap-up order that works: repo hygiene → `VESPER_ENGINEERING_STATUS.md` →
  repo `MEMORY.md` → an `OVERNIGHT_REPORT_<date>.md` (the repo's own convention)
  → these memory files → push → re-verify anything time-critical → power off.
- **Check what the machine is holding before powering it off.** Node 1 is free
  when no endurance run is in flight; the alarm lives on node 2 and is
  unaffected by node 1 shutting down. Verify rather than assume — see
  [[a029-endurance-run-in-flight]].
- Pushing goes to the feature branch only. Never `main`, never `--force`, no PR
  unless asked.
