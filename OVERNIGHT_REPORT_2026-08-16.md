# VESPER — overnight session report, night of 2026-08-16

> ## ⚠ DO NOT POWER OFF THIS MACHINE
>
> **The 24-hour `A-029` endurance run is in flight on it.** It started at
> **00:42 on 2026-08-16** and finishes at **~00:42 on 2026-08-17**. Powering
> down, sleeping or restarting kills it and the 24 hours start again from zero.
> This is the "needs the machine left alone for a day" item from yesterday's
> report, and it is now the day.
>
> Sleep and hibernate are already `Never` on the active High performance scheme
> and no reboot is pending — I checked rather than assumed. The remaining risk
> is a manual shutdown.
>
> ```
> python verification/run_a029_endurance.py --status
> ```

---

## 1. The headline

**The 24-hour endurance run — yesterday's "single most significant gap between
*passes* and *proven*" — is running**, on a harness that was shown to fail
against three deliberately broken builds before it was trusted with a day of
elapsed time.

And **yesterday's report was wrong about one thing, in your favour**: engineering
had *not* run out of unblocked work. `SPIKE-008` criterion 8 was deferred with
the recorded reason *"needs the runtime's event codec and upcaster registry,
which do not exist until F0"*. F0 shipped in the very session that wrote the
handover, so the block lifted the moment it landed and the deferral text went on
reading as a block. **Criterion 8 is now closed**, with its own non-compliant
control.

| | |
|---|---|
| Commits tonight | 5, on `feat/f0-f1-endurance`, **nothing pushed** |
| PR #5 | **untouched and frozen** — your review is the review the last report describes |
| New runtime code | 163 lines (`core/codec.py`) + the real-time driver and watchdog |
| New harness code | ~1,290 lines across four files |
| Acceptance gates | 6, all still green |
| `checks.py` · `self_test.py` | 17 / 17 · 47 / 47 |
| Endurance harness self-test | **6/6 healthy pass · 3/3 broken fail as required** |
| `SPIKE-008` | 7 criteria → **8**; criterion 9 still needs the second node |

---

## 2. What the night produced

### 2.1 `A-029` on a real clock — and the fifth vacuous check

The 24-hour run could not simply be *started*, because nothing could run it.
`AutonomyLoop.tick()` had no real-time caller: the only thing that had ever
driven it was a `for` loop advancing a simulated clock. Part 1 — liveness across
a window — had nothing to be true of.

`AutonomyRunner` (in `core/autonomy.py`) is that driver. Two properties worth
your attention:

- **It schedules by absolute deadline**, not by sleeping for the interval. Over
  1,440 cycles, `sleep(60)` accumulates every cycle's own work as drift, which
  is the difference between a cadence and an approximation.
- **Its watchdog is a separate thread**, because a stall detector living inside
  the loop it watches cannot report the one failure that matters. A dead thread
  emits nothing.

That second point uncovered **a fifth instance of yesterday's §5 pattern, in the
decisive gate itself**: A-029 Part 1 asserts `autonomy.loop_stalled` never
fires, and **nothing in the runtime could emit that event**. There was no
watchdog. The assertion was an absence that could not become a presence — it
would have read green forever, against any build, including a dead one. It is
now emitted by the watchdog, and the `B1` control below is the run that proves
it fires.

### 2.2 One definition of the gate, two drivers

The obvious way to build a real-time A-029 is to copy the compressed one and
change the clock — after which the gate has two definitions that agree today,
drift apart at the first amendment, and **both keep printing PASS**.

So A-029's three parts now live in `verification/a029_protocol.py` and are
asserted identically by the compressed driver and the real-time one. The
compressed gate still passes, unchanged in verdict, with strictly stronger
assertions.

That refactor immediately exposed something: **C1's cron model was
under-built.** It fired unconditionally on every tick and therefore recorded no
no-ops at all — so it passed the old Part 2 check by having nothing to check.
AT-03 requires C1 to *pass* parts 1 and 2 and fail only part 3. Cron now has a
due job and a not-due one, which is what cron actually is.

### 2.3 The controls, and the two the self-test caught

Three deliberately broken builds, each at real cadence, each required to fail —
run **before** launching anything:

| Build | Result |
|---|---|
| **B1** the loop wedges at 40% of the window (a hang, not an exception) | part 1 fails **and the watchdog fires** |
| **B2** every trigger `SCHEDULE`-class | parts 1 and 2 pass, part 3 fails — the asymmetry AT-03 requires |
| **B3** a *correct* build that retains 1 MB per tick | every A-029 part passes, `E1` fails at **+76.9 MB** against an 8.4 MB budget |

**B3 is the only control that tests the reason for running 24 hours at all**,
and it is where the self-test earned its place twice:

1. **My first B3 passed — so it measured nothing.** It leaked inside a trigger's
   predicate, and `PredicateEvaluator.evaluate()` short-circuits on an `UNKNOWN`
   term *before* calling the predicate. Across a window where the fact is
   usually `UNKNOWN` the leak barely ran: 3 MB instead of 96 MB, comfortably
   inside budget. That is yesterday's pattern #3 exactly — a control written from
   the same mental model as the code it checks — written by the pass that had
   just read that short-circuit. It is recorded in the file rather than quietly
   corrected.
2. **`E3` thread stability failed a *healthy* build**, by comparing `min` to
   `max` across a run whose first samples are taken while five threads are still
   coming up. It read a correct startup as instability.

### 2.4 Two instruments, cross-checked

The harness judges Part 1 from the loop's own in-memory list and Part 3 from the
injection times its own controller recorded — i.e. from its account of itself.
That is yesterday's failure #4 in a different costume.

`verification/verify_a029_from_log.py` re-derives all three parts from the
durable event log alone: heartbeats from `autonomy.heartbeat` records, and **the
moment `T` arrived from the `world.fact_updated` write the system recorded**
rather than the one the controller claims to have made. A trigger it cannot
rebuild is `UNVERIFIABLE` and **fails** — "I could not check it" must never read
the same as "it passed". It opens the store read-only rather than copying it,
because SPIKE-008's own portability control established that copying a SQLite
store under a live writer is the unsafe path.

The self-test now requires the two instruments to **agree on all four builds**.
The leak build is the stated exception: RSS never reaches the event log, so a
log-only verdict cannot see a leak and is right to say PASS. That is a real limit
of log-derived evidence, recorded rather than smoothed over.

### 2.5 VOID vs FAILED

AT-03 already carries this distinction and the harness lacked it: *"if the
external ingress is unavailable during the run, the run is **void** (harness
defect), not failed (product defect)... a void run is re-run, never counted."*

The environmental failure a desktop run is actually exposed to is the machine
sleeping or restarting — and all three symptoms are identical to a dead loop.
The discriminator is mechanical, in the spirit of the anti-cron probe: **a
suspended machine stops the monotonic clock and does not stop wall time.** A
genuinely stalled loop diverges by neither — both clocks run while nothing ticks
— which is why this cannot launder a real stall into a void. Asserted in both
directions.

### 2.6 `SPIKE-008` criterion 8 — the expired deferral

`core/codec.py` is the upcaster registry ADR-002 D4 specified: upcasters keyed
by `(event_type, from_version)`, applied on read until the reader's version is
reached.

**The registry holds no store handle, and that is the enforcement.** The way an
implementation fails "stored bytes never mutate on read" is by fixing up the
record it just read while it happens to have both forms in hand. This class has
nowhere to write one back to — the same construction as `PredicateEvaluator`,
which cannot call a model because it was never handed anything that could. The
probe's upcaster deliberately mutates its argument in place, which is how one is
ordinarily written, and the stored dict is still unchanged afterwards.

A missing upcaster **raises and names the exact step**. The silent version — hand
back the old form, drop the unknown field — surfaces as a `None` three frames
away with nothing tying it to a schema change. A body *newer* than the reader is
refused rather than guessed at.

Its non-compliant control (the naive codec that upcasts in place and returns the
old form) fails as required, and criterion 8 is not claimed unless it does.

---

## 3. Recorded, not fixed — deliberately

Both are real, both are small, and both were left alone because a 24-hour run was
in flight and changing what it is judged against mid-run is worse than either
defect.

1. **Part 1 is judged from an in-memory list, not the durable log.** If the two
   ever disagree the harness believes the weaker one, and it is not the one
   A-029 names. `verify_a029_from_log.py` is the answer; making it the *primary*
   judge is owed before the R4 gate.
2. **`AutonomyLoop` retains every heartbeat, firing and no-op for the life of the
   process.** ~1,440 of each per day at the declared cadence — harmless across
   this window, unbounded across a month. Recorded at the code and in the
   harness's `NOT_CLAIMED` so it is not mistaken for a discovery later.

**A declared cadence of 60 s is a choice this harness made, not one it
inherited.** Nothing in `contracts/` or `spec/` declares a production tick
cadence. `INV-AUTO-1` fixes the tolerance at 3× that interval, so the number
matters; it is recorded in the artifact rather than left in a default argument.
Worth ratifying as a real contract value at some point.

---

## 4. Tomorrow morning, in order

### 4.1 Read the run — and know how to read a FAIL

```bash
python verification/run_a029_endurance.py --status
```

It will be ~8 hours in. What you want to see: `stalls 0`, `late ticks 0`, and an
`rss` figure that has not climbed. At 00:52 it read 32.0 MB, 0 stalls, 0 late
ticks, with heartbeats and no-ops accumulating one per minute.

**If it reports FAIL with stalls or late ticks, check whether the machine
napped before believing it.** The run in flight is pinned to a commit that
predates §2.5, so it cannot label itself VOID. Compare the artifact's wall-clock
span (`started_iso` → `finished_iso`) against its monotonic `elapsed_s`: if wall
time ran materially longer, the machine was suspended and the run is **void, not
failed** — re-run it, never count it.

### 4.2 Two five-minute things, unchanged from yesterday's plan

The **bare-panel baseline** needs no glass (SPIKE-004 §8), and a **flat clear
sheet** closes the other half. Not a jar or tumbler — §6.1 records why vertical
walls cannot work.

### 4.3 Review PR #5, then decide what to do with tonight's branch

PR #5 is exactly as you left it. Tonight's work is five commits on
`feat/f0-f1-endurance`, stacked on it, **unpushed** — I did not push because you
had not asked me to and the branch changes what a reviewer of #5 would see. Say
the word and it goes up as its own PR stacked on #5.

### 4.4 The two decisions

Unchanged and still yours, laid out in full in `PLAN_2026-08-16.md` §3:
`OWNER-DECISION-006(c)` (the ADR namespace — 2 minutes, blocks nothing) and the
`ADR-001`/`ADR-012` authority question (~10 minutes, and the more interesting of
the two).

`OWNER-DECISION-006(b)`'s stale "still BLOCKS F0" header is fixed; the ruling has
been in `ADR-002` since 08-14.

---

## 5. Housekeeping you should know about

- **A git worktree exists at `C:/Projects/VESPER-endurance-2026-08-16`**, pinned
  at commit `94b84fb`, so nothing I edited afterwards could perturb a run in
  flight. It has its own store directory.
- **The completed run's artifact lands inside that worktree**, at
  `docs/planning/spike-results/A-029-endurance-live.json`. **Copy it into the
  main tree before running `git worktree remove`**, or the night's headline
  deliverable goes with it.
- Nothing touched `main`. Nothing touched `feat/f0-f1-runtime`. No owner decision
  was inferred, discharged or implied.

---

## 6. What is still blocked, and by what

Unchanged from yesterday except where noted:

| Item | Blocker |
|---|---|
| `SPIKE-008` criterion 9 | a `foreground_only` node — hardware |
| F6 discovery, placement, migration | a second **always-on** node (the Kali laptop is enrolled but `on_demand`) — the desktop repair |
| iPhone app → `SPIKE-002` → `A-020` | the MacBook |
| `A-008`, `A-028`, `A-039`, `A-012`, `A-041` | cameras, alarm devices, a physical ASR-independent channel |
| `SPIKE-004` ghost reading | a flat clear sheet — five minutes of looking |
| ~~`SPIKE-008` criterion 8~~ | ~~the F0 codec~~ — **closed tonight** |

F6 was deliberately not started. It needs the second always-on node, and the
software-only half would have left a **fourth** part-built stage in a tree that
already carries three — which makes tomorrow's review worse, not better.
