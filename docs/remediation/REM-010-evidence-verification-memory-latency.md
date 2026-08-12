# REM-010 — Evidence envelope, verification strategy, memory conflict, latency budgets

| | |
|---|---|
| **Closes** | AR-014 (P1) · AR-015 (P1) · AR-016 (P1) · AR-023 (P1) · AR-024 (P1) · NV-02 residual (P1, downgraded from P0) · NV-07 (P1) · GAP-036, GAP-040 |
| **Decision record** | **This specification** discharges Foundation **ADR-010** (memory retention) and the BAG half of **ADR-004**; no separate filing. See `docs/ADR/ADR-REGISTER.md`. |
| **Owner** | Intelligence Systems Engineer · Knowledge & Memory Engineer |
| **Blocked by** | REM-001 (supersession, `UNKNOWN`), REM-003 (`trust_class`) |
| **Blocks** | REM-002 §4.6 (`VERIFYING` guard), REM-008 (a run whose tasks self-certify proves nothing) |

---

## 1. Problem

**Four defects that share one root: the most-repeated behavioural requirement in the corpus has no mechanism.**

**(a) "No guessing" is asserted, never implemented.** RB-002, P-004, SR-041 and SR-048 all state it. `T-001`'s controls are *"Evidence labels, BAG, verifier, no-guessing tests, explicit UNKNOWN state"* — four nouns and a test. There is no claim-level evidence structure, so grounding is at best tracked per *response*, which means a response that is 95 % grounded with one fabricated specific reads as grounded.

**(b) The verifier is named six times and specified zero times.** IC-007's `verification_criteria` has no type. RB-004 says *"A task is complete only when its acceptance condition passes"* — with no statement of what an acceptance condition **is**. And the natural implementation of a disagreeing verifier — re-run until it agrees — **silently destroys the control** while appearing to strengthen it.

**(c) Memory conflict has no resolution order.** RB-003 gives a partial ordering (*"Authoritative source files, system rules, approved project state, and current observations outrank stale memory or model intuition"*) that does not resolve the common case: the calendar, a direct observation, and something the user said all disagree.

**(d) SR-046 × SR-047 × RB-004 × SR-045 has never been costed.** Voice-first interaction, realtime latency, mandatory verification, and free/local models only — simultaneously, on the weakest hardware. The Foundation instructs converting *"measured baselines into targets"*, which defines a target as whatever was measured; such a target can never fail.

**On NV-02 (verifier collapse) — the P0 framing is rejected, and the reason matters.** The claim was that SR-045 + ARCH-13 + SR-042 make planner and verifier *structurally* the same weak model overnight. Three independent grounds refute it: the single-model constraint sits inside the handwritten *"MacBook specific"* bullet and is a per-node constraint; the desktop is *"always connected"* and is most available exactly overnight; and the source's own definition — *"One step plans, another **checks output against files/rules**"* — asks for separate **control stages**, not separate model instances. A deterministic check against files, tests and schemas satisfies it completely, and better than a second model would. **What survives is a P1 specification gap**, closed by §4.3 and §4.4 below: nothing currently forbids a task self-verified by the same model in the same context from being recorded `SUCCEEDED`.

## 2. Authoritative requirement

| Source | Text |
|---|---|
| **RB-002** | *"When evidence is insufficient, retrieve, observe, calculate, ask, or explicitly report uncertainty."* |
| **RB-004** | *"A task is complete only when its acceptance condition passes or Vesper explicitly records failure/blockage."* |
| **RB-023** | *"Never fabricate citations, measurements, experiments, source claims, or novelty."* |
| **RB-003 / DR-020** | Source-of-truth hierarchy |
| **P-004 / P-009** | Evidence beats guessing; verification is part of execution — *"A plausible response is not completion."* |
| **SR-013** | *"Task planner + verifier: One step plans, another checks output against files/rules."* |
| **SR-041 / SR-048** | Absolute honesty, no guessing, no lies |
| **SR-047** | *"All interactions should be fast, realtime, realistic, fun, impressive."* |
| **DR-018** | *"Define measured latency/throughput targets… per hardware profile."* |
| **Handwritten p3** *(`SRC-GAP-001`)* | *"BAG: instead of RAG… NO GUESSING"* |

## 3. Affected subsystems

`SPEC-08 BAG/context retrieval` · `SPEC-07 Memory` · `SPEC-06 World model` · `SPEC-12 Autonomy` · `SPEC-02 Core control loop` · `SPEC-16 Presence` (post-hoc correction) · `SPEC-11 Model routing`.

## 4. Required behaviour

### 4.1 Claim-level evidence

**Grounding is tracked per claim, not per response.**

```
Claim {
  text,
  support: [ source_ref | computation_ref | observation_ref ],
  support_type: retrieved | computed | observed | model_prior,
  confidence,
  trust_class          # inherited from the weakest supporting fragment (REM-003)
}
```

**Output gate by policy class:**

| Policy class | Rule for `support_type = model_prior` |
|---|---|
| `research`, `memory_write`, `world_fact`, `input_to_consequential_action` | **Not emittable as an assertion.** It must be marked, converted into an explicit question, or dropped. |
| `conversational`, `personality` | Gate relaxes; **marking is still required** |

> `UNKNOWN` is a **first-class return value** across BAG, world model and memory. An empty result is **never** coerced into a plausible answer. This is the same `UNKNOWN` REM-001 §4.5 introduces, used at the retrieval boundary.

**BAG, not RAG (`SRC-GAP-001` / proposed SR-052).** Retrieval is **source-grounded and exact**, not similarity-guessing:

> **INV-EVID-2.** No answer may cite a source it did not retrieve. A similarity score is never sufficient grounding. Every `source_ref` resolves to a retrieved span, and the span is reproducible from the cited source.

This is what makes "BAG instead of RAG" an enforceable engineering property rather than a class name.

### 4.2 `VerificationStrategy`

A typed union bound to task class, in **strength order**:

| Strategy | Definition | Independence |
|---|---|---|
| `deterministic` | Tests, schema validation, diff, exit code, recomputation | **Full** — no model involved |
| `retrieval_grounded` | Claims checked against cited sources | Full — the source is the arbiter |
| `model_critic` | Independent **context**; different model **where available** | Partial |
| `self_model` | Same model, same context | **None** |
| `human` | Escalate to the user | Full |
| `none_declared` | Permitted **only** for explicitly non-consequential output, and **recorded as such** — never silently skipped |

`IC-007.verification_criteria` becomes this typed union. A task whose criteria are untyped cannot be created.

> **The independence question is answered by strategy strength, not by model count.** `deterministic` — a passing test suite — is *more* independent than a second LLM, and it runs on the weakest node offline. That is why NV-02's "structural impossibility" framing was wrong, and why the correction is two clauses rather than an architecture.

### 4.3 Disagreement

```
Verifier fails  ⇒  task is NOT complete (RB-004).
Task enters BLOCKED with the disagreement preserved as evidence.
PROHIBITED: re-running until the verifier agrees.
```

> This is the natural implementation and it silently destroys the control. `INV-VERIF-1` names it explicitly so that an implementer cannot arrive at it innocently, and `A-023` tests for convergence-by-retry directly.

### 4.4 Unattended eligibility and `verified_by` telemetry — the NV-02 residual

```
A free-time task whose acceptance condition is NOT machine-checkable is
INELIGIBLE for autonomous completion. It queues for a pass when an
independent verifier or the user is available.

Every task records:
    verified_by ∈ { deterministic | retrieval_grounded | model_critic
                  | self_model | deferred }

`self_model` may NEVER be silently reported as accepted.
```

These two clauses are the whole of what survives NV-02, and they are sufficient. Overnight work that can be checked by tests proceeds; overnight work that can only be checked by opinion queues until morning. That is the correct behaviour and it costs nothing architecturally.

### 4.5 Latency-aware verification — resolving the AR-024 intersection

The four-way intersection is resolved by making verification **asynchronous where it can be**, not by weakening it:

```
Conversational: inline retrieval_grounded verification (cheap, local).
model_critic runs ASYNCHRONOUSLY, with post-hoc correction:
    "Correction — I checked that: it is 60 minutes, not 15."
Streaming / progressive presence is ARCHITECTURAL: first audio begins
before generation completes (REM-009 §4.3).
```

> **Honest post-hoc correction satisfies RB-004 and is more consistent with RB-001 (Truth) than delayed perfection.** A system that says the right thing four seconds late has failed SR-047; a system that corrects itself has satisfied both.

### 4.6 Memory conflict resolution — a stated total order

| Rank | Authority |
|---|---|
| 1 | System rules / policy |
| 2 | Authoritative source-of-record for that attribute *(declared per attribute — e.g. the calendar owns meeting times)* |
| 3 | Direct current observation within TTL |
| 4 | Explicit user statement |
| 5 | Derived / inferred |
| 6 | Model prior — **never authoritative** |

> **When ranks 2, 3 and 4 disagree, VESPER MUST surface the conflict and ASK.** This is the RB-002-compliant outcome and it is the **specified default**, not an implementation choice.

Every correction writes `supersedes`; provenance survives (IC-006). Retention and expiry are an actual background process **with a test**, not a documented intention.

### 4.7 Latency budgets — requirements, set before measurement

> **A target defined as whatever was measured can never fail.** Budgets are derived from interaction-design constraints and set **before** measurement. Measurement then produces a **gap analysis**, never a retarget.

| Path | Budget |
|---|---|
| wake word → first audible response | ≤ 800 ms |
| end of speech → response onset (routine) | ≤ 1200 ms |
| scene update → visible | ≤ 300 ms |
| barge-in interrupt honoured | ≤ 200 ms |
| tool invocation → result acknowledged | ≤ 500 ms |
| checkpoint write | ≤ 200 ms |
| node failover → task resumed | ≤ 30 s |

Where a budget is unmeetable on the minimum hardware profile, record a **COC Part XIV.3 limitation with an R&D path — do not relax the budget.**

## 5. Ownership and authority

| Concern | Owner | Authority |
|---|---|---|
| Evidence envelope, output gate | Knowledge & Memory Engineer | `E2`/`E3` |
| `VerificationStrategy`, disagreement handling | Intelligence Systems Engineer | `E2`/`E3` |
| Memory authority order | Knowledge & Memory Engineer | `E2`; **source-of-record per attribute is owner-configured** |
| Latency budget values | **Project Owner** sets numbers; the **rule** that they precede measurement is architectural | Owner |

## 6. Interfaces

| Interface | Change |
|---|---|
| `IC-006` Memory | `Claim`, `support_type`, `trust_class`, mandatory `supersedes` on correction, declared `source_of_record` per attribute |
| `IC-007` Task | `verification_criteria` becomes the typed union; adds `verified_by` |
| `IC-010` Research | Evidence envelope per claim; *"insufficient evidence"* is a valid terminal conclusion |
| `IC-005` Presence | Post-hoc correction is a `patch` scene update, not a new turn |

Contracts: `contracts/entities/claim.schema.json`, `contracts/entities/verification_strategy.schema.json`, `contracts/policy/latency_budgets.toml`.

## 7. Invariants

| ID | Statement |
|---|---|
| **INV-EVID-1** | No `model_prior` claim is emitted as an assertion in research, memory writes, world facts, or inputs to consequential actions. |
| **INV-EVID-2** | No answer cites a source it did not retrieve; a similarity score is never sufficient grounding. |
| **INV-EVID-3** | `UNKNOWN` is a first-class return value; an empty retrieval is never coerced into an answer. |
| **INV-VERIF-1** | Verifier failure ⇒ `BLOCKED`, never `SUCCEEDED`. Retry-until-agreement is prohibited. |
| **INV-VERIF-2** | A free-time task with a non-machine-checkable acceptance condition is ineligible for autonomous completion. |
| **INV-VERIF-3** | `verified_by: self_model` is never silently reported as accepted. |
| **INV-MEM-1** | Three-way disagreement across authority ranks 2–4 produces a user-facing question, never a silent pick. |
| **INV-PERF-1** | Latency budgets are requirements set before measurement. **A budget may not be modified in the same change as the code that failed it.** |

## 8. Failure behaviour

| Failure | Behaviour |
|---|---|
| Retrieval returns nothing | `UNKNOWN` returned; the caller retrieves differently, asks, or reports uncertainty. Never a plausible substitute. |
| Verifier disagrees | `BLOCKED`; disagreement preserved as evidence; no silent retry |
| No independent verifier available overnight | Task queues (`INV-VERIF-2`); `verified_by: deferred` |
| Async `model_critic` finds an error post-emission | Post-hoc correction scene patch; original claim marked superseded |
| Memory ranks 2–4 disagree | Conflict surfaced; user asked; nothing written until resolved |
| Budget missed on the minimum profile | Gap analysis + Part XIV.3 limitation record. **The budget does not move.** |

## 9. Recovery

Blocked tasks retain their disagreement evidence, so resolution is inspection rather than re-execution. Superseded claims retain provenance, so a post-hoc correction is auditable back to the moment the wrong claim was emitted — which is what makes RB-001 (Truth) verifiable after the fact rather than only in the moment.

## 10. Contract / state machine / decision function

| Artifact | ID / path |
|---|---|
| Claim + evidence | `contracts/entities/claim.schema.json` |
| Verification strategy | `contracts/entities/verification_strategy.schema.json` |
| Latency budgets | `contracts/policy/latency_budgets.toml` |
| Output gate | `DF-OUTPUT-GATE` |
| Verification selection | `DF-VERIFY-SELECT` |
| Memory conflict resolution | `DF-MEMORY-AUTHORITY` |

## 11. Verification

**`A-003` replaced with a graded corpus.** 0 % / partial / full evidence, **including the adversarial "mostly grounded with one unsupported specific"** case — the case a per-response grounding check passes and a per-claim check fails. Unsupported-claim rate is tracked as a **release metric**, not a pass/fail alone.

**`A-023` — Verifier disagreement.** Produce subtly wrong output → verifier fails it → task `BLOCKED` → disagreement recorded → **assert no silent retry convergence** (run 20 iterations; assert the task never reaches `SUCCEEDED` by repetition).

**`A-032` — Context budget and manual mode.** Retrieval stays within budget; manual context override works; `UNKNOWN` propagates.

**`A-020` extended — latency.** Measured against **declared** budgets, wired as a CI performance gate failing on regression past budget. Plus the `INV-PERF-1` test: a change that modifies a budget **and** the code that failed it, in the same commit, fails CI.

**Memory fixture set:** one fixture per pairwise conflict class across ranks 2–6, asserting the specified outcome — including the three-way case asserting a **question**, not a pick.

**SPIKE-002** — timed end-to-end test on the **minimum** profile, offline, in `FREE_TIME`, asserting per-stage budgets **and first-audio latency independently of total completion**. If the chain does not close, the deliverable is a Part XIV.3 limitation record with an R&D path — not a relaxed budget.

## 12. CI enforcement

| Check | Enforces |
|---|---|
| `CI-031` `budget-not-relaxed-with-code` | `INV-PERF-1` — a diff touching `latency_budgets.toml` and the failing implementation together fails |
| `CI-032` `verification-criteria-typed` | Every task fixture's `verification_criteria` resolves to a declared strategy |
| `CI-033` `claim-support-required` | Static: no emission path constructs an assertion in a gated policy class without a `support` array |

## 13. Dependencies

**Requires:** REM-001 (`UNKNOWN`, supersession), REM-003 (`trust_class` on fragments), REM-006 (`FREE_TIME` gates unattended eligibility). **Required by:** REM-002 §4.6 (`VERIFYING → SUCCEEDED` guard), REM-008 (an endurance run whose tasks self-certify proves nothing).

## 14. Unresolved decisions

| # | Item | Disposition |
|---|---|---|
| 1 | Latency budget numbers | **Project Owner.** The rule that they precede measurement is not negotiable. |
| 2 | Source-of-record declaration per memory attribute | Owner configuration; the *requirement* that each attribute has one is architectural |
| 3 | Whether SPIKE-002's chain closes on the minimum profile | **Unknown until measured.** Recorded as an open risk, not assumed either way. |

## 15. Jarvis-divergence check

> *Could an implementation agent satisfy REM-010 while building an ordinary chatbot?*

**Partly — and the residue is the point.** A chatbot can cite sources. The clauses that do not fit: **`INV-VERIF-2`** (a task that cannot be machine-checked *waits until morning* — a request-scoped system has no "later" to wait for) and **`INV-MEM-1`** (a three-way conflict across calendar, observation and user statement presupposes a world model and a memory with declared sources-of-record, neither of which a retrieval-over-documents system has).
