# SPIKE-002 — Voice interaction latency chain on the minimum profile

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Does the SR-046 × SR-047 × RB-004 × SR-045 chain close on the **minimum** profile, offline, in `FREE_TIME`, with local models only? |
| **Time box** | 10 working days |
| **Owner** | Presence & Interaction Engineer · Intelligence Systems Engineer |
| **Depends on** | SPIKE-001 (supplies the minimum profile) |
| **Measures against** | `contracts/policy/latency_budgets.toml` — written **before** this spike, deliberately |
| **Closes** | AR-024 · GAP-006 (verification affordability) |

> **This is the spike most likely to fail, and the corpus has said so from the first review.** It is written so that a failure produces a usable engineering result rather than a negotiation.

---

## 1. The intersection being measured

Four requirements meet at one point and the arithmetic was never done:

| | |
|---|---|
| **SR-046 / SR-047** | interactions are fast, realtime, realistic |
| **RB-004** | every task carries a machine-checkable acceptance condition — verification is not optional |
| **SR-045** | **no paid providers during `FREE_TIME`** — so both generation and verification run on local models |
| **SR-005** | local fallback must work at all |

Verification roughly **doubles** inference per interaction. During `FREE_TIME` both roles are filled by weak local models on the weakest node. Nobody has ever costed this. `latency_budgets.toml` currently asserts stage budgets summing to **1000 ms** against an end-to-end budget of **1200 ms**, with 200 ms of headroom — on paper. This spike finds out whether that paper survives.

## 2. Conditions — all four simultaneously

The measurement is only meaningful under the hardest declared conditions, because those are the conditions SR-045 guarantees will occur:

1. **The minimum viable profile** from SPIKE-001 — not the best node.
2. **Offline.** Network physically disconnected, not merely unused.
3. **`OperatingPeriod = FREE_TIME`**, evaluated by `DF-OPERATING-PERIOD`, not asserted by the harness.
4. **Local models only**, at the tiers SPIKE-001 measured as sustainable.

Any measurement taken with a network cable attached is not a measurement of this chain.

## 3. Instrumentation

Every stage boundary emits an event carrying its HLC (`ADR-001`). Latency is computed from **the event log**, never from harness-side wall-clock reads — the harness cannot see where the time went, and the whole value of this spike is knowing which stage is the problem.

```
mic_open ─▶ asr_final ─▶ perception_fused ─▶ retrieval_complete
        ─▶ route_selected ─▶ plan_ready ─▶ verify_inline_complete
        ─▶ scene_built ─▶ tts_first_sample ─▶ tts_complete
```

Two clocks are recorded for every run and they answer different questions:

| Clock | Starts | Stops | Budget |
|---|---|---|---|
| **first-output** | wake word detected | `tts_first_sample` | **800 ms** |
| **completion** | end of user speech | `tts_complete` | 1200 ms |

> **These are asserted independently, and that is not a formality.** A build that is silent for four seconds and then answers perfectly has *failed* SR-047 while passing any total-completion budget. REM-010 §4.5 makes streaming architectural precisely so first-output can be met while completion continues. A report that gives only a total is not a result for this spike.

## 4. Protocol

### 4.1 Corpus

**60 utterances**, fixed and version-controlled, in four classes of 15:

| Class | Shape | Why it is in the set |
|---|---|---|
| A | trivial, no retrieval (*"what time is it"*) | isolates the ASR + TTS floor. If this misses, nothing else can pass. |
| B | single-fact retrieval | exercises BAG at its cheapest |
| C | multi-source retrieval + reasoning | the realistic case |
| D | retrieval returning **nothing** | the `UNKNOWN` path — must be **fast**, because "I don't know" arriving late is the worst of both outcomes |

Class D exists because the natural implementation spends the most time on the query it cannot answer.

### 4.2 Runs

30 runs per utterance class, cold and warm cache alternating. Report **p50, p95 and max** per stage and per clock. **p95 is the pass criterion**; p50 alone hides the case the owner will remember.

### 4.3 The verification-cost measurement (the AR-024 core)

Run each class **twice**:

- **V0** — generation only, verification disabled. Not a permitted shipping configuration; a diagnostic baseline.
- **V1** — with `retrieval_grounded` inline verification, as `DF-VERIFY-SELECT` would select for conversational output.

`verification_overhead := V1 − V0`, per stage and end to end.

Then, separately: with `model_critic` verification running **asynchronously** per REM-010 §4.5, measure (a) that first-output is unaffected, and (b) the post-hoc correction latency — how long until *"Correction — I checked that"* arrives. A correction that arrives after the owner has left is not a correction.

### 4.4 Barge-in

50 interruptions at randomised points during output. Measure interrupt → audio actually stops. Budget **200 ms**. Record whether the pipeline cancels end to end or merely stops the speaker — a stopped speaker with a running pipeline still holds the resources the next turn needs.

## 5. Pass criteria

| # | Criterion | Budget |
|---|---|---|
| 1 | `wake_to_first_audio` p95, classes A–D | ≤ 800 ms |
| 2 | `speech_end_to_response_onset` p95, classes A–C | ≤ 1200 ms |
| 3 | Class D (`UNKNOWN`) p95 **no worse than class B** | — |
| 4 | `barge_in_honoured` p95 | ≤ 200 ms |
| 5 | `scene_update_visible` p95 | ≤ 300 ms |
| 6 | Every stage within its declared stage budget at p95 | per `latency_budgets.toml` |
| 7 | V1 (verification enabled) meets criteria 1 and 2 | — |
| 8 | Async `model_critic` correction arrives within the same interaction session | — |

**Criterion 7 is the one this spike exists for.** Passing with verification disabled is not passing: SR-045 makes local verification mandatory in exactly the period being measured.

## 6. On fail — decided now, in advance

> **The deliverable is a COC Part XIV.3 limitation record with an R&D path. Not a relaxed budget.** `INV-PERF-1` and `CI-031` make this mechanical: a commit that changes a `budget_ms` and an implementation file together is rejected.

Permitted responses, in order of preference:

1. **Optimise the identified stage.** The per-stage instrumentation exists so this is targeted rather than speculative.
2. **Move a stage to async** where REM-010 §4.5 already permits it. Only `model_critic` is currently permitted; moving anything else is a REM-010 change with its own review.
3. **Raise the minimum node profile** and re-run SPIKE-001. This changes the hardware recommendation, honestly and visibly.
4. **Record the limitation.** Name the stage, the measured figure, the budget, and the gap in milliseconds.

Explicitly **not** permitted, and named because each is what a team under deadline actually does:

- relaxing `budget_ms`;
- redefining a path so the slow stage falls outside it;
- reporting a measurement from a stronger profile;
- reporting completion latency in place of first-output latency;
- reporting the V0 (verification-disabled) figure as the result;
- reporting p50 as though it were p95.

## 7. Deliverables

1. Per-stage latency table: p50 / p95 / max, per utterance class, V0 and V1.
2. `measured_ms` populated in `latency_budgets.toml`, with `measured = true`. **No `budget_ms` value changes in the same commit** (`CI-031`).
3. A **gap analysis**: budget minus measured, per path. Positive gaps are findings, not embarrassments.
4. `verification_overhead`, isolated — the number AR-024 has been asking for since the first review.
5. Limitation records for any unmet criterion.
6. A recommendation on whether the minimum profile is viable for voice interaction at all.

## 8. What a *negative* result buys

If the chain does not close, this spike has still produced the most valuable artifact in the programme: **the specific stage, the specific gap, on the specific hardware**. That is a purchasing decision and an optimisation target. What it must never become is a quiet edit to a budget file, which is why the budgets were written before the measurement and are enforced by a check that runs without any of this hardware existing.
