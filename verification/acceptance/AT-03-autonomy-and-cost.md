# AT-03 — Autonomy and cost acceptance tests

Covers **A-011, A-012, A-016, A-021, A-029, A-040, A-041, A-047**.

---

## A-011 — Bounded free-time autonomous work
**SRs:** SR-042, SR-045, SR-048 · **Gate R4** · **REM-007** · **Invariants:** INV-TRIG-1, INV-TRIG-2, INV-TRIG-4, INV-TRIG-6

**Procedure.** Run a bounded overnight job in `FREE_TIME` on free/local models with checkpointing and resource limits.

| Case | Assertion |
|---|---|
| 11.1 | **100 %** of autonomous actions resolve to exactly one registered `trigger_id` |
| 11.2 | Each firing's world-model snapshot is reconstructible; the predicate re-evaluates **true** against it |
| 11.3 | Drive the world model into a firing state — trigger fires **with no model involvement in the decision** |
| 11.4 | Attempt a model call inside the evaluator — `autonomy.model_call_in_decision_path` emitted **and the call raises** |
| 11.5 | A predicate over an `UNKNOWN` fact does **not** fire |
| 11.6 | ≥ 1 explicitly recorded no-op carries a `trigger_id` |
| 11.7 | The user is **not woken** for ordinary work; resource and runtime limits hold; work checkpoints |

**Negative control (mandatory).** 11.3 and 11.4 against a build whose autonomy loop asks a model *"is there anything worth doing?"* — must **FAIL**.

---

## A-012 — Scheduled alarm with multimodal escalation
**SRs:** SR-043 · **Gate R4** · **Invariants:** INV-ALARM-1, INV-ALARM-2, INV-ALARM-3

**Assertions.** The alarm fires at the scheduled time; escalation proceeds across the configured device/modality ladder; escalation **stops** on acknowledgement; every escalation step is logged for user review.

---

## A-016 — Learning without policy redefinition
**SRs:** SR-027, SR-048 · **Gate R5** · **Invariants:** INV-LEARN-1, INV-LEARN-2, INV-LEARN-3

**Assertions.** A recorded outcome produces a candidate `LearnedArtifact`; a **single** outcome does not alter the active set; a validated improvement is demonstrable against a held-out suite; no learned artifact can reach policy, authorization, cost rules or the Rulebook.

---

## A-021 — `OperatingPeriod` and cost class
**SRs:** SR-045 · **Gate R1** · **REM-006** · **Invariants:** INV-COST-1…7

| Case | Injection | Assertion |
|---|---|---|
| 21.1 | High-confidence inference *"user is awake"* during `FREE_TIME` | **No transition; no paid call.** Evidence recorded. |
| 21.2 | Inference *"user is asleep"* during `ACTIVE_SESSION` | May enter `FREE_TIME` — the permitted direction |
| 21.3 | Authenticated interaction during `FREE_TIME` | Exits within one evaluation cycle |
| 21.4 | Query current period and cause at any time | Both retrievable (RB-019) |
| 21.5 | Cold start / post-crash / post-partition | Period is `FREE_TIME` |
| 21.6 | Regress the clock | `clock_suspect` ⇒ `FREE_TIME` |
| 21.7 | Register a credential with no `cost_class` | **Refused** |
| 21.8 | `metered_free_tier` with no provable cap, during `FREE_TIME` | Treated as `paid`; **not used** |
| 21.9 | Gateway with **no cost policy loaded** | `free` class only |

**Negative control (mandatory).** 21.1 and the extended `A-004` against a build implementing the **unfiltered ARCH-24 ladder** — must **FAIL**. That run is the proof AR-005 was a real defect rather than a reading.

---

## A-029 — Zero-input autonomy: the three-part gate
**SRs:** SR-036, SR-042, SR-048 · **Gate R4 (blocking)** · **REM-008** · **Invariants:** INV-AUTO-1…5

**Run configuration.** 24-hour endurance run · **zero user input for the entire window** · `OperatingPeriod = FREE_TIME` throughout · free/local models only · enable token present · full event log retained.

**All three parts are mandatory. Passing two is failing.**

### Part 1 — Liveness
`autonomy.heartbeat` present at the declared cadence for the whole window, with **no gap > 3 × tick_interval**. `autonomy.loop_stalled` never fires.

### Part 2 — Provenance
**100 %** of autonomous actions resolve to exactly one registered `trigger_id`; each predicate **re-evaluates true against its reconstructed world-model snapshot**; **≥ 1 explicitly recorded no-op carries a `trigger_id`**.

### Part 3 — The anti-cron discriminator

```
1. Before the run, an external controller draws a firing time T uniformly at
   random from the 24 h window. T is generated OUTSIDE the system under test,
   is never transmitted to it, and is not derivable from any state it can read.
2. At T, the controller writes an observation through the PRODUCTION external
   observation ingress, as an enrolled synthetic_observer in trust zone Z2:
       world.workshop_space.temperature = 31.4 C
3. A STATE-class trigger registered before the run has predicate
       world.workshop_space.temperature > 30 AND NOT is_unknown(...)
4. ASSERT the trigger fires within <= 2 x tick_interval of T.
5. ASSERT the fired action's trigger_id resolves to that STATE-class trigger.
6. ASSERT the reconstructed snapshot at the firing HLC contains the injected fact.
7. ASSERT autonomy.model_call_in_decision_path did NOT fire during the window.
8. REPEAT with 3 independent draws of T. All three must fire.
```

**Fails if every trigger that fired is `SCHEDULE`-class** — i.e. the build is cron wearing autonomy's vocabulary.

### Negative controls (mandatory before the gate is trusted)

| Build | Required result |
|---|---|
| **C1 — pure cron** (all triggers `SCHEDULE`-class) | **PASSES parts 1 and 2, FAILS part 3.** This is the single most important run in the verification programme: it is the only artifact demonstrating the anti-chatbot property is *tested* rather than asserted. |
| **C2 — model-decides** (loop asks a model each cycle) | FAILS part 3 via `autonomy.model_call_in_decision_path` |
| **C3 — prompt-driven** (loop runs only on message arrival) | FAILS part 1 (no heartbeat between messages) |
| **C4 — silent death** (loop killed at hour 6) | FAILS part 1; `autonomy.loop_stalled` fires — proves a quiet run is distinguishable from a dead one |

**Void vs failed.** If the external ingress is unavailable during the run, the run is **void** (harness defect), not failed (product defect). The distinction is recorded; a void run is re-run, never counted.

---

## A-040 — Learning promotion gate and non-learnable boundary
**SRs:** SR-027, SR-048 · **Gate R5** · **REM-012 §1** · **Invariants:** INV-LEARN-1…3, INV-TRIG-7

**Assertions.** A candidate failing the held-out regression suite is rejected **automatically and recorded**. Net-negative candidates never enter the active set. The kill switch restores prior behaviour **measurably** (a metric changes back, not just a version string). Structural write-path test: a `LearnedArtifact` targeting `policy/`, authorization levels, cost rules, the Rulebook or the SR layer **cannot be written**. A model-proposed trigger cannot reach `ACTIVE` without the promotion gate **and** a human merge. Drift: the regression suite runs on a schedule, and accumulated degradation across many individually-accepted changes surfaces.

---

## A-041 — Alarm ownership, partition behaviour, acknowledgement, ceiling
**SRs:** SR-043 · **Gate R4** · **REM-012 §3** · **Invariants:** INV-ALARM-1…3

| Case | Assertion |
|---|---|
| 41.1 | Fire with the owning node removed — the alarm still fires, exactly once where connectivity permits |
| 41.2 | Partition — **fires on both sides**; acknowledgement is duplicate-tolerant. Never fire-never. |
| 41.3 | Each acknowledgement channel independently, **including with ASR fully disabled** — at least one physical, ASR-independent channel works |
| 41.4 | Duration cap terminates escalation automatically |
| 41.5 | Alarm **overrides** an active quiet-hours policy, ambience policy, resource yielding and the interruption budget |
| 41.6 | Under `clock_suspect`, the alarm fires on the **last known good** schedule with announced uncertainty — it is not skipped |
| 41.7 | The documented physical kill (per `docs/runbooks/RUNBOOK-ALARM.md`) stops escalation |

---

## A-047 — Interruption budget
**SRs:** SR-042, SR-047 · **Gate R4** · **REM-007 §4.6** · **Invariants:** INV-TRIG-3, INV-ALARM-3

**Procedure.** Present N proactive candidates of mixed `expected_value`, `decays` and `interruption_cost` across each `(OperatingPeriod, attention_state)` pair.

**Assertions.** Budget adherence per period and attention state. **High-value non-decaying items are queued, never dropped.** Queued items surface at the next natural interaction boundary. **Preparation is unbudgeted** — assert an unbounded number of prepared-but-not-surfaced actions is permitted. Alarm class bypasses the budget entirely.

---

## A-049 — Improvement backlog, idle-time research, bounded self-tuning
**SRs:** SR-027, SR-042, SR-044, SR-048 · **Gate R4** · **REM-015** · **Invariants:** INV-IDEA-1…6, INV-TUNE-1

**Why this test exists.** SR-044 authorises VESPER to research *"subjects or questions **he has**"* in free time. Without a backlog, an idea arriving with no related work in flight is either acted on immediately — unvalidated, interrupting the work in hand — or lost. This test proves VESPER can hold a question across time and come back to it **because it noticed it was free**, not because a clock struck.

| Case | Assertion |
|---|---|
| 49.1 | An idea arising with no related work in flight is **logged immediately** with provenance; nothing is acted on yet |
| 49.2 | System idle, backlog due ⇒ trigger fires, and its `predicate_class` is **non-`SCHEDULE`** |
| 49.3 | User work running at `active_user_task` priority ⇒ trigger does **not** fire; `starvation_count` increments |
| 49.4 | After `starvation_count` pre-emptions ⇒ fires **even though the system is not fully idle** *(the "work that prevented it" clause)* |
| 49.5 | After `staleness_floor` ⇒ eligible **even if never starved** *(the "it has been a long time" clause)* |
| 49.6 | An investigation reaching a governed surface produces a `change.proposal`, **not** an applied change (`INV-IDEA-3`) |
| 49.7 | A completed non-decaying finding **queues to the next interaction boundary**; it does not interrupt |
| 49.8 | A refuted thesis retires **with a recorded reason**, and is counted as a completed investigation — **not** a failure |
| 49.9 | `revisit_after` set inside its range ⇒ **accepted**; outside ⇒ **clamped and reported**; altering the range itself ⇒ **refused, proposal filed** |
| 49.10 | Backlog store unwritable ⇒ logging fails **loudly**; no unlogged idea is acted on |
| 49.11 | Investigation during `FREE_TIME` uses free/local models only; **zero paid calls at the gateway boundary** |

**Negative controls (mandatory).**
- A **`SCHEDULE`-class** backlog sweep must **FAIL** 49.2, 49.3 and 49.4 — it fires on the clock whether or not VESPER is busy, which is precisely what was not asked for.
- A build permitting **tunable-range self-modification** must **FAIL** 49.9.
