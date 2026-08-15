# Red-test evidence — the gates can fail

**Why this file exists.** Every gate in this repository reports PASS. That is
worth nothing on its own: a gate that cannot fail reports PASS forever. This
project has now shipped **four** checks that passed while measuring nothing —
the SPIKE-008 fencing control, the SPIKE-008 portability control, the F0
`INV-TASK-1` control, and the F2 `30.4` artifact check. Each looked green and
each was worthless until it was made to go red.

So each F-stage gate was run against a **deliberately broken build** and
observed failing. This is the record of those runs. Reproduce any of them by
applying the mutation and running the named check.

| Gate | Mutation applied to shipped code | Result |
|---|---|---|
| `f0-acceptance` | Plant `RUNNING → SUCCEEDED` in `core/tasks.py`'s `ALLOWED` table | **RED** |
| `f0-acceptance` | Break fencing to read-then-write in `core/store.py` (`put_state`) | **RED** |
| `f1-acceptance` | Disable the claim-level support check in `core/evidence.py` | **RED** |
| `f2-acceptance` | Make `summarise()` return `verified_local` instead of the weakest input class | **RED** |
| `f2-acceptance` | Let an `L5` grant bypass `SelfModificationBoundary.check_write` | **RED** |
| `f2-acceptance` | Reintroduce `lstrip("./")` in the governed-path parser | **RED** — `NOT governed: ['.github/workflows/ci.yml']` |
| `f2-acceptance` | Let an expired grant proceed instead of going `WAITING` | **RED** |
| `f2-acceptance` | Drop the `INV-TRUST-2` placement check | **RED** |
| `f4-acceptance` | Let expired facts return their last known value | **RED** |
| `f4-acceptance` | Make the privacy router ignore ambiguity | **RED** |
| `f4-acceptance` | Add the `DISCOVERED → TRUSTED` edge | **RED** |
| `f3-acceptance` | Drop the `degradations` array when empty | **RED** |
| `f3-acceptance` | Make recovery replay instead of probe | **RED** |
| `f5-acceptance` | Remove the `UNKNOWN` guard from the evaluator | **RED** |
| `f5-acceptance` | Make the interlock fail **open** when the token expires | **RED** |
| all | restore | **GREEN** |

## The C1 asymmetry, recorded because it is the point

`A-029-C1-CONTROL` is the pure-cron build, and the corpus calls its red run
*"the single most important run in the verification programme"*. It does not
fail everything — that would prove nothing. It fails **only part 3**:

```
PART 1+2 pass on this build (recorded, not asserted as failure)
   -> liveness and provenance both hold
Part 3 NOT every fired trigger is SCHEDULE-class
   -> 240 fired, all SCHEDULE-class: cron wearing autonomy's vocabulary
```

A build can be flawlessly live and flawlessly provenanced and still be a cron
job. Part 3 is the only thing that tells them apart, and this run is the proof
that part 3 has teeth.

## The four controls that passed and shouldn't have

Recorded because the pattern repeats and is worth recognising early.

1. **SPIKE-008 fencing control.** The stale writer held a permanently expired
   epoch, so a plain `SELECT` rejected it before the race could occur. Fixed by
   making ownership genuinely change hands and reading the verdict from
   committed state via a trigger. Now accepts 119–3,175 stale writes as it must.

2. **SPIKE-008 portability control.** Skipped the WAL checkpoint expecting the
   tail to strand in a sidecar — but SQLite checkpoints on last-connection-close,
   so the WAL was always folded back before anything was copied. Fixed by
   copying while a writer connection is still open with `wal_autocheckpoint=0`.
   Now loses 300 committed rows while the copy still passes `integrity_check`.

3. **F0 `INV-TASK-1` control.** Built a broken dict of its own and never touched
   `core/tasks.py`, so planting the forbidden edge in the shipped table left the
   whole gate green. Fixed by monkeypatching the real `ALLOWED` table, plus a
   positive case that exercises the real `TaskStore`.

4. **F2 `30.4` artifact check.** Compared the boundary's governed list against
   the artifact the boundary had just read — tautological, agreeing with itself
   by construction. Adding a surface to the artifact left it green. Fixed by
   naming the critical surfaces by hand, independently of the parser, plus a
   converse check that the boundary does not simply govern everything.

**The shared shape:** each control was written from the same mental model as
the code it was meant to check, so it inherited the same blind spot. The only
reliable defence found so far is to *run the control against a deliberately
broken build and require it to fail* — which is what the table above records.
