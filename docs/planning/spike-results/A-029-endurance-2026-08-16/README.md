# A-029 endurance, 2026-08-16 — the 23-hour run, and why it is a partial

**Status: RECORDED PARTIAL. Not a pass, not a failure, not VOID.**
`A-029` remains **owed**. `F5-AUTONOMY-ACCEPTANCE-node1.json` keeps
`endurance_run_owed: true`, and nothing in this directory changes that.

The run was launched 2026-08-16 00:42:32 for a 24 h window at a 60 s cadence and
was **externally terminated at 23:42:30**, after **23.00 h — 95.85 %** of the
window. It did not crash and it did not wind down: the log carries
`runtime.started` and **no** `runtime.stopped`, and the final heartbeat is a
normal on-cadence tick. Every Python process was gone afterwards.

## What is in this directory

| File | What it is |
|---|---|
| `log.db` | The durable event log, **4 139 records**, WAL-consolidated snapshot. `PRAGMA integrity_check` = `ok` |
| `A-029-FROM-LOG-declared-24h.json` | The verdict judged against the window the run was **launched for**. **FAIL** |
| `A-029-FROM-LOG-observed-23h.json` | The verdict judged against the window actually **observed**. **PASS** |
| `A-029-endurance-live-at-kill.json` | The live status file as it stood at the moment of the kill — carries the last 120 resource samples |
| `MANIFEST.json` | Sizes, checksums and provenance |

**The two verdict files disagree on purpose, and the disagreement is the
finding.** They are the same evidence read against two different windows.

## Why the 24 h reading is the binding one

`verification/acceptance/AT-03-autonomy-and-cost.md` fixes the window as a
number, not as a purpose:

> **Run configuration.** 24-hour endurance run · zero user input for the entire
> window · `OperatingPeriod = FREE_TIME` throughout · free/local models only ·
> enable token present · full event log retained.

Part 3 then draws each firing time `T` "uniformly at random from the **24 h
window**." A 23 h run cannot honour a draw from hour 23–24. All three draws
happened to land earlier and all three fired — **that is luck, not coverage.**

`verify_a029_from_log.py` anticipated this exact situation in its own docstring
and refuses to let the inferred window clear a short run:

> Without it the window is inferred from the log's own span, which cannot see a
> loop that died before the end — so an inferred window is reported and never
> used to clear a run that stopped early.

Judged against the declared 24 h window, two Part 1 assertions miss:

```
MISS  Part 1 heartbeats span the whole window, both ends
      last heartbeat 3 600 000 ms before the window end, against a 180 000 ms limit
MISS  Part 1 the heartbeat count matches the declared cadence
      1381 heartbeats, expected ~1440 (+/-28)
```

**And it is not VOID.** AT-03's void clause is specific — *"if the external
ingress is unavailable during the run"*. The ingress was available; all three
injections landed. An external process kill is not the environment defect that
clause names, so the run may not be laundered into a void and re-run for free.

## What the run nevertheless established

Everything except window length passed, and one pre-registered prediction was
falsified in the product's favour.

| Part | Evidence | Reading |
|---|---|---|
| **1 — liveness** | 1 381 heartbeats, no gap > 3 × tick, 0 `loop_stalled`, 0 late ticks, worst lateness 0.00 s | Holds for 23.00 h |
| **2 — provenance** | 9 firings all resolving to one registered `trigger_id`, each predicate re-evaluated true against its reconstructed snapshot; 1 372 recorded no-ops carrying a `trigger_id` | Holds |
| **3 — anti-cron** | **3 of 3** injections via the production ingress as an enrolled `synthetic_observer`; 0 `model_call_in_decision_path` | Holds — complete |

### E1: the pre-registered leak did not happen

`A-029-E1-PREREGISTRATION.md` was written at hour 12.4, **before the answer was
knowable**, and predicted from a linear fit that RSS would reach a last-quarter
mean near **29 MB** — a **+9.3 MB** growth against an **8.0 MB** budget, i.e. a
healthy build failing its own leak check.

Measured at hours 21.02–23.00:

```
first quarter of the retained tail   19.91 MB
last  quarter of the retained tail   20.20 MB
growth                               +0.29 MB   against a 8.4 MB budget
peak                                 20.34 MB
projected                            ~29 MB     — wrong by 8.9 MB
```

RSS rose to 24.17 MB by hour 12 and **came back down to ~19.8 MB by hour 23**.
The accelerated reproduction's conclusion — *"unbounded leaks do not flatten;
allocator arenas and page caches do"* — is confirmed at real timescale. Handles
(176) and threads (5) are exactly flat. The store grows 0.184 MB/h, append-only
by design, projecting 0.14 GB per 30 days.

**The escape hatch was not needed.** The pre-registration's
`INCONCLUSIVE-BY-CRITERION` disposition existed in case E1 failed. E1 passes on
its merits, so the disposition is not invoked — but the sharper criterion it
specifies is still the right one to build, because *this* run passed E1 by
accident of allocator behaviour rather than by measuring the program.

### The hole that must be stated

**Hours 12 → 21 of the resource series are gone.** The live status file retains
only the last 120 samples, and the run never reached the end-of-run write that
would have persisted the full series. So E1 above is a **reconstruction from two
endpoints** — the pre-registration's hourly table for hours 1–12, and the
surviving tail for hours 21–23 — not a continuous measurement.

The pre-registration's own overturn clause is *"tracked Python heap growing
without deceleration across the window"*. **That clause is unverifiable for
hours 12–21.** The endpoints are sound and the projection is genuinely
falsified; the middle is not evidence, and is not claimed as any.

## The stronger reason to re-run: the build

The run executed `94b84fb`. **391 lines of harness change landed after it
started**, and they are not cosmetic:

| Commit | What it added |
|---|---|
| `fa7d24d` | `verify_a029_from_log.py` — **234 lines that did not exist when the run launched** |
| `5ae6996` | `detect_void` and the `wall_s` sample field — VOID vs FAILED |
| `fafe39d` | Closed two findings and covered the watchdog in CI |

Two consequences, both material:

1. **The run could never have been judged the way the harness now judges runs.**
   Its samples carry no `wall_s`, so `detect_void` is inert against them and a
   machine suspension could not have been told from a stall — retroactively or
   at the time.
2. **The cross-check could not have run.** The current driver asserts *"the
   log-derived verdict and the in-memory verdict AGREE"*, treating a
   disagreement as a failure of the run. That assertion did not exist yet.

So even a full 24 h under `94b84fb` would have been judged by the weaker
instrument. **The missing hour is the smaller defect; the build is the larger
one.** A re-run on `HEAD` is not repetition — it exercises the corrected
criteria for the first time.

## Disposition

1. This run is recorded as a **partial**, cited for what it observed and for the
   falsified E1 projection, and **never cited as an `A-029` pass**.
2. `A-029` stays **owed** before gate R4. `INV-AUTO-3` additionally requires the
   **C1 pure-cron negative control** recorded as failing Part 3 before `A-029`
   may be cited at all — independent of this run.
3. A **fresh 24 h run on `HEAD`** is the closure. Nothing memory-heavy may share
   its window: `SPIKE-001` §3.2 drives free RAM to 0.27 GB at 660 pages/s, which
   would perturb the run it is measured beside.
