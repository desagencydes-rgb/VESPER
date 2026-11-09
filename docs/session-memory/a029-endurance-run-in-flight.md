---
name: a029-endurance-run-in-flight
description: "A-029 24h run — not currently in flight; owner shut the machine down 2026-08-17, rescheduled to week 3"
metadata: 
  node_type: memory
  type: project
  originSessionId: 752ebc2c-4e42-45fd-9e8f-08e69c2177af
  modified: 2026-08-17T00:34:37.609Z
---

**No endurance run is in flight.** The machine may be powered off, restarted, or used for
anything at any time. **Do not ask the owner to keep it on for A-029.**

A run was launched 2026-08-17 00:09:58 and **the owner shut the machine down the same night
at ~5% progress, deliberately and correctly** — the machine had been up 36 hours and the gate
is not due until week 3. Nothing of value was lost: ~80 heartbeats is not evidence, and the
valuable **23.00 h partial is committed** under
`docs/planning/spike-results/A-029-endurance-2026-08-16/`.

**A-029 is scheduled for week 3** of `docs/history/PLAN_2026-08-17.md`, run alongside the C1 pure-cron
control on the Kali laptop the same night. It gates F5, which is **7th of 9** in the build
order (`F0→F1→F2→F4→F3→F6→F5→F7→F8`), so it blocks nothing before then.

**The standing lesson, which cost a day already:** check the dependency chain before treating
anything as urgent, and never constrain the owner's hardware for a test that gates work three
weeks out. See [[lay-out-records-before-working-on-them]].

When it is re-run: launch detached, verify `wall_s` is present in the samples so the VOID
detector is armed, and judge with both instruments — the log-derived verdict is primary.
