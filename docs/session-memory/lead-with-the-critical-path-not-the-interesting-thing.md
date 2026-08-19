---
name: lead-with-the-critical-path-not-the-interesting-thing
description: "Spend the session on what the plan says is urgent; a deferred gate gets one line, however interesting the discrepancy is"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 56298fb4-5855-49be-82e3-1793e25bde6f
  modified: 2026-08-17T12:28:27.501Z
---

When asked "what's the plan," answer with the **critical path** and then work it. A gate
scheduled for week 2 or 3 gets **one line**, no matter how interesting a discrepancy about it
turns out to be.

On 2026-08-17 the owner asked what was on for Monday. Two full turns went to the A-029
endurance run — a stale "in flight" claim, a killed relaunch, a durable-log reconstruction — all
correct, all about the **7th of 9** gate, due week 3. Meanwhile the actual Monday items sat
untouched with half the day gone. The owner's reaction: *"you left everything that is important
and went talking about the least important one."*

**Why:** this is mistake #3 in the repo's `MEMORY.md` — treating A-029 as urgent — recurring in a
new form. The first time it cost a day of machine time. This time it cost the owner's attention,
which is scarcer. Being *right* about a low-priority discrepancy is not the same as it being
worth a turn, and a correct finding delivered instead of the day's work is still a failure to
deliver.

**How to apply:** lay out the plan's own ordering first and work top-down from it. When an
inconsistency surfaces in something deferred, record it in one line and keep going — offer the
fix, don't perform it. Verify with a command instead of narrating a hypothesis: `git worktree
list` and the run's own log settled in two calls what two turns of prose did not. Delivery is
the unit of progress, not analysis.

Related: [[lay-out-records-before-working-on-them]], [[a029-endurance-run-in-flight]],
[[vesper-repo-memory-file]].
