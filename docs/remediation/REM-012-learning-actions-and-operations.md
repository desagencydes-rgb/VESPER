# REM-012 — Learning boundary, external-action outbox, alarms, gateway, governor, observability

| | |
|---|---|
| **Closes** | AR-020 (P1) · AR-021 (P1) · AR-022 (P1) · AR-026 (P1) · AR-028 (P1) · AR-030–AR-035 (P2) · NV-06 (P1) · NV-08 (P2) · GAP-041, GAP-043, GAP-044, GAP-046 |
| **Decision records** | **This specification** discharges Foundation **ADR-011** (learning boundary), **ADR-013** (observability retention) and **ADR-014** (research promotion). The observability *store* is decided in `docs/ADR/ADR-002-persistence.md` D2. See `docs/ADR/ADR-REGISTER.md`. |
| **Owner** | Multiple — one section per owning role |
| **Blocked by** | REM-002, REM-003, REM-004, REM-005, REM-006 |

This REM closes the remaining P1/P2 corrections. Each section is self-contained: problem, correction, invariants, verification, CI.

---

## 1. Learning promotion and the non-learnable boundary *(AR-022 · Intelligence Systems Engineer)*

**Problem.** SR-027 and SR-048 authorize learning; RB-020 forbids one interaction permanently altering core policy. No promotion unit, validation gate, or rollback unit exists — so the default implementation is **system-prompt accretion**, which violates RB-020 continuously while appearing compliant, and which defeats versioning, rollback and attribution simultaneously.

**Correction.**

```
LearnedArtifact {
  artifact_id,
  type: routing_hint | procedure | retrieval_strategy | context_policy
      | tool_preference | trigger_proposal,
  content, provenance (which outcomes produced it), scope, expiry,
  version, status: proposed | active | retired
}

PROMOTION GATE
  Nothing enters the active set without passing a held-out regression suite
  scoring the candidate against the current baseline.
  Net-negative candidates are rejected AUTOMATICALLY.

NON-LEARNABLE BOUNDARY (hard)
  Security policy, authorization levels, cost policy, the Rulebook, and the
  SR layer are NOT learnable under any score. They change only through
  owner-approved change control (COC Part XIV).
  Learnable artifacts live in a SEPARATE, bounded store, enforced on the
  WRITE PATH -- not by inspection.

ROLLBACK   unit = the individual artifact, plus a kill switch reverting the
           entire active set to a known-good version.
DRIFT      the regression suite runs on a SCHEDULE, not only at promotion,
           so degradation accumulated across many individually-accepted
           changes surfaces.

PROHIBITED PATTERN (added to the Foundation's "Prohibited" list, alongside
"hidden global state"): system-prompt accretion as a learning mechanism.
```

> **Relationship to REM-004, stated so the two are never conflated.** `INV-LEARN-1` governs what the *learning store* may contain. `INV-SELF-1` governs what the *runtime* may commit. A system could satisfy `INV-LEARN-1` perfectly and still rewrite `policy/` with a shell command. Two controls, two failure modes, two tests.

| ID | Invariant |
|---|---|
| **INV-LEARN-1** | No learned artifact may modify policy, authorization, cost rules, or the Rulebook — enforced **structurally on the store's write path**. |
| **INV-LEARN-2** | A single outcome cannot alter the active set. |
| **INV-LEARN-3** | Every active artifact is individually rollback-able and the whole set is revertible. |

**`A-016` extended / `A-040`:** a single bad outcome does not alter the active set; a candidate failing the gate is rejected **and recorded**; the kill switch restores prior behaviour **measurably**; structural write-path test for `INV-LEARN-1`. **CI-036** `learning-store-boundary`.

---

## 2. Transactional outbox and reconciliation *(AR-028 · Core Systems Engineer)*

**Problem.** COC ARCH-04 states the correct principle — *"A command is never proof that an action happened"* — and never discharges it. IC-003's `rollback/compensation` field cannot compensate an email that was already sent. Worse, checkpoint-replay recovery (REM-002) makes duplicate external actions **more** likely, not less.

**Correction.**

```
TRANSACTIONAL OUTBOX
  Intent is durably recorded with an idempotency_key BEFORE the call.
  Result is recorded after. Recovery reads the OUTBOX, never replays the task.

RECONCILIATION PROBE
  Every external tool declares a READ-ONLY probe answering "did this happen?"
  (search sent items by key, query call history, look up the created event).
  Reconciliation runs BEFORE any retry.
  Where no probe is possible the tool declares `reconcilable: false` and MUST
  escalate to the user rather than retry.

IC-003 FIELD CHANGE (proposal)
  Replace the single `rollback/compensation` field with
      reversibility: reversible | compensable | irreversible
  `irreversible` implies L4+ and pre-commit confirmation binding (INV-AUTH-2).

Bind SR-031/DR-025 delegated-identity attribution to the outbox record so
A-018 auditability is satisfiable.
```

`reconcilable: false` is the case that silently produces duplicates, and it is handled **by declaration** rather than by hope.

| ID | Invariant |
|---|---|
| **INV-EXT-1** | No external side effect occurs without a prior durable outbox record. |
| **INV-EXT-2** | No retry of an external action occurs without a successful reconciliation probe; `reconcilable: false` escalates instead. |

**`A-035`:** crash-injection during external tool execution; assert exactly-once **effective** delivery via reconciliation; assert `reconcilable: false` escalates; assert the audit chain reconstructs `trigger → authority → command → outbox → probe → result`. **CI-037** `outbox-before-effect`.

---

## 3. Alarms: priority lattice, ownership, escalation ceiling *(AR-026, NV-06 · Autonomy & Task Engineer)*

**Problem.** No priority lattice, so a quiet-hours policy silently suppresses the alarm. No distributed ownership, so on partition it is undefined whether the J3 fires. No escalation ceiling, so maximum-volume escalation at 03:00 has no guaranteed stop. No trusted time source, so the alarm's own schedule is only as good as an unauthenticated clock.

**Correction.**

```
PRIORITY LATTICE  (a rule, not left to implementers)
  alarm/safety  >  active user task  >  ambience  >  proactive
  Alarm class overrides RB-034 ambience policy, RB-015 resource yielding,
  RB-006 proportionality, and device-level quiet hours.

OWNERSHIP    Replicated to every capable node with lease-based single-firer
             election. ON PARTITION: FIRE. Never fire-never. (REM-002 §4.5)

TRUSTED TIME Alarm scheduling uses an authenticated time source. Under
             `clock_suspect` (REM-001 §4.1) alarms fire on the LAST KNOWN
             GOOD schedule and the uncertainty is announced -- they are not
             skipped. Missed-window is reported, never silent.

ACK          Multi-channel. At least one channel MUST be physical and require
             no ASR (hardware button, phone unlock, specific device action).

CEILING      Maximum escalation level, duration cap with auto-stop, and a
             documented physical kill (which device, which action), tested at
             Phase 8 and written into a runbook. Every escalation step logged.
```

| ID | Invariant |
|---|---|
| **INV-ALARM-1** | Exactly one firer per instant where connectivity permits; on partition the failure direction is **fire**. |
| **INV-ALARM-2** | At least one acknowledgment channel is physical and ASR-independent; escalation has a hard duration cap. |
| **INV-ALARM-3** | Alarm class is exempt from the interruption budget, ambience policy, resource yielding and quiet hours. |

**`A-012` extended / `A-041`:** fire with the owning node removed; each ack channel independently **including with ASR fully disabled**; duration cap terminates escalation; override of an active quiet-hours policy; `clock_suspect` fires on last-known-good with announced uncertainty. Runbook `docs/runbooks/RUNBOOK-ALARM.md` is a deliverable.

---

## 4. `owner_administrative` capability class and SR-026 *(AR-020, AR-021 · Security Engineer)*

**Problem (a).** SR-039 (*"bypass/whatever workarounds to reach goals in all hardwares — should always explain and ask first"*) was narrowed by RB-013 **without a recorded deviation**, and no capability class exists for legitimate owner-directed privileged action — making SR-039 unimplementable rather than merely constrained.

**Problem (b).** SR-026's *"read kernel"* was dropped from its own interpretation, and COC Part XIV.3's procedure for infeasible requirements — which the corpus correctly applied to SR-037 — was not applied.

**Correction (a).**

```
L5 owner_administrative
  Privileged operations on ENROLLED, OWNER-ATTESTED assets.
  Requires explicit PER-INSTANCE owner confirmation with risk and
  reversibility explained FIRST -- which is the source's own
  "should always explain and ask first".
  Fully audited. Checkpointed where reversible.
  NOT delegable to a sub-agent (INV-AUTH-2).
  NOT invocable during FREE_TIME.
```

**RB-013 scoping clarification (proposal, changes no requirement):** RB-013 prohibits defeating authentication, authorization, encryption or access controls on **third-party or non-owned systems**, and prohibits circumventing VESPER's own security model. It does **not** prohibit owner-authorized administrative operations on the owner's own enrolled hardware, which are governed by `owner_administrative`. *The distinction that resolves it cleanly: **whose** control is being bypassed, and **who** authorized it.*

**Correction (b).** SR-026 splits: the **telemetry half** is core and buildable now; the **kernel-access half** becomes a recorded Part XIV.3 limitation with an R&D path and a per-platform feasibility matrix (**SPIKE-003**), following the DR-031 pattern the corpus already knows how to apply. **The SR is not narrowed.** Status is `PARTIAL_R_AND_D`, published in release notes per Part XIV.7 — **never `IMPLEMENTED`**.

| ID | Invariant |
|---|---|
| **INV-ADMIN-1** | `owner_administrative` requires per-instance owner confirmation, is never delegable, and is never invocable during `FREE_TIME`. |
| **INV-LIMIT-1** | Any SR judged infeasible carries a limitation record and an R&D path per Part XIV.3, and may never be marked `IMPLEMENTED`. |

**`A-038`:** per-instance confirmation; non-delegability; `FREE_TIME` denial; targeted **negative** tests asserting RB-013 still blocks non-owned and self-directed cases. **`A-043`:** hardware telemetry present; kernel half reports its limitation record rather than a value. **CI-038** `limitation-record-required`.

---

## 5. Provider gateway, resource governor, cost policy *(AR-031, AR-032, AR-033 · Intelligence Systems Engineer)*

| Item | Correction |
|---|---|
| **Error taxonomy** | Versioned enum in IC-002 (`retry_worthy \| switch_worthy \| fatal \| content_policy \| quota`) with a declared policy per class |
| **Quota model** | Local per-credential tracking with rolling windows and pessimistic 429 backoff — free tiers rarely expose introspection |
| **Mid-stream failure** | Specified **per modality**. For voice, the spoken prefix is **committed** and continuation is **semantically resumable** — the replacement model receives the prefix as context — never silently restarted. Partially-rendered scenes have a defined merge rule (REM-009 `update_mode: patch`). |
| **Governor damping** | The governor is a **damped controller**: minimum dwell per level, asymmetric thresholds (**degrade fast, recover slow**), explicit hysteresis band, max transitions/hour triggering an **alert** rather than another transition. Model-visible telemetry (SR-011) is **advisory input to a deterministic governor**, not a direct actuator: *the model may request, the governor decides.* |
| **Cost policy** | `contracts/policy/cost_policy.toml` per REM-006 §4.6; owner-only change control; explicitly **not learnable** (`INV-LEARN-1`); gateway **fails closed** with no policy loaded |

**`A-004` extended:** mid-stream provider kill during streamed voice — assert **no audible repetition** and semantic continuity. **Governor:** drive synthetic oscillation; assert transitions stay under cap and that dwell-violating model requests are **rejected**. **CI-039** `governor-damping-present`.

---

## 6. Observability: retention, sensitivity, purge *(AR-035, NV-08 · Verification Engineer)*

**Problem.** A correlation chain is defined; retention, sensitivity enforcement and purge are not. ARCH-25 says *"Secrets must never enter ordinary telemetry"* with no mechanism.

**Correction.**

- Retention **per event class**.
- The `sensitivity` field is **enforced by the telemetry writer** — redaction/exclusion **at write time**, not by convention.
- Perception payloads are **classified sensitive by default**, with **references stored rather than content**.
- A purge path satisfying REM-011's deletion requirement, **with the correlation chain surviving purge** (the content/reference separation in REM-011 §3.5).

| ID | Invariant |
|---|---|
| **INV-OBS-1** | Sensitivity is enforced at write time by the telemetry writer, never by caller discipline. |
| **INV-OBS-2** | Purge removes payloads; event skeletons and the correlation chain survive. |

**`A-037`:** inject a secret and a synthetic PII payload into a traced flow; assert **neither appears in the store**; assert purge removes derived records **while the correlation chain survives**. **CI-040** `telemetry-sensitivity-enforced`.

---

## 7. Schema versioning and migration *(GAP-046 · Chief Architect)*

**Problem.** Every contract carries `schema_version` and **nothing states what happens when it changes**. Migration retrofitted onto durable data is the classic unrecoverable cost.

**Correction.**

```
Every durable record and every event carries schema_version.
Readers MUST accept N and N-1. Writers emit N only.
A breaking change requires: an ADR, a migration script, a dual-read window,
and a recorded cutover. `schema_version` may never be reused for different
semantics.
Events are IMMUTABLE: migration is read-time upcasting, never log rewriting.
```

| ID | Invariant |
|---|---|
| **INV-SCHEMA-1** | Readers accept `N` and `N-1`; writers emit `N`. Breaking changes require an ADR and a dual-read window. |
| **INV-SCHEMA-2** | The event log is never rewritten. Migration is read-time upcasting. |

**CI-001** `schema-change-requires-adr` — any diff under `contracts/` without a referenced ACCEPTED ADR fails.

---

## 8. Roadmap consolidation *(AR-030 · Chief Architect)*

Precedence is declared in `docs/AUTHORITY_AND_PRECEDENCE.md §3`. The single consolidated sequence is published in `docs/architecture/IMPLEMENTATION_SEQUENCE.md`, merging Foundation `F0–F8` with Baseline `Phase 0–10` and resolving the ordering deliberately: **perception before presence**, because presence routing consumes world-model facts that only perception produces. Benchmark ID collision resolved by renaming (`FB01–FB08` / `BB01–BB10`).

---

## 8a. Computer and device agency *(added 2026-08-12 · Autonomy & Task Engineer)*

**Why this section exists.** `ARCH-08` (*Computer and Device Interaction*) is a locked architecture section. `SR-020` requires VESPER to *"self-interact across available hardware"*, `SR-021` to *"run/execute code, scripts, commands"*, and `SR-030` names *"computer action"* explicitly. The handwritten source is unambiguous: *"self interact everywhere in all available hardwares"*, *"researching & taking action on computer"*.

Until this pass, **none of the 29 subsystems covered acting on a computer and none of the 30 decision functions governed endpoint interaction.** `SR-020` was `SPECIFIED`, but its agency clause traced only to `semantic_scene.schema.json` (output rendering), `SM-SENSOR` (capture) and `INV-PRIV-4` (sensor indicators). The one artifact that touched agency, `A-013`, asserts argument-sensitive **authorization** — permission to act, which is not the act.

That is precisely the condition under which a competent implementer reduces computer agency to *"answer questions about the computer"* while every written rule still reads as satisfied. The requirement was **not downgraded** to make the registry honest; the mechanism was written.

### 8a.1 Required behaviour

The unit is an **episode**, not a call:

```
read the surface -> assert the precondition -> decide -> actuate
                 -> observe THROUGH A DIFFERENT PATH -> verify against a
                    declared post-condition -> recover or close
```

| Property | Mechanism |
|---|---|
| Perception of a machine | `contracts/entities/endpoint_surface_state.schema.json` — a typed element tree with roles, labels, per-element confidence, `observed_at_hlc` and a required `valid_until`. `trust_class` is structurally fixed to `retrieved_external`. |
| A checkable action | `contracts/commands/endpoint_interaction.schema.json` — `expected_post_condition`, `observation_plan` and `verification_strategy` are all REQUIRED, so an unverifiable action is unrepresentable. |
| Admission | `DF-ENDPOINT-ACT` — typed action, fresh and known precondition, `DF-AUTHORIZE` with `declared_level(args)`, taint ceiling, trust zone, measured capability, actuation gate, outbox record. |
| Independent observation | `DF-ENDPOINT-OBSERVE` — the observing path may not be the actuating path. Where no independent path exists the outcome is `UNKNOWN`, never `VERIFIED`. |
| Recovery | `DF-ENDPOINT-RECOVER` — `RETRY \| COMPENSATE \| ESCALATE \| HALT`. **No branch returns success.** |
| Lifecycle | `SM-ENDPOINT-EPISODE`, whose prohibited edges are the load-bearing half: no `ACTUATED → VERIFIED`, no `OUTCOME_UNKNOWN → CLOSED`, no retry of a non-idempotent action after an unknown outcome. |

### 8a.2 Invariants

| ID | Invariant |
|---|---|
| **INV-ACT-1** | A typed `EndpointInteraction` or no action. A free-text instruction to an endpoint is a prompt, not an action. |
| **INV-ACT-2** | The actuator's report is never the observation. |
| **INV-ACT-3** | Screen content, OCR, UI labels and command output are `retrieved_external` and may never raise authority. |
| **INV-ACT-4** | Every endpoint action traverses `DF-AUTHORIZE` and, for a runtime subject, `DF-ACTUATION-GATE`. No direct adapter path. |
| **INV-ACT-5** | An `UNKNOWN` outcome is never closed as success or failure. |
| **INV-ACT-6** | Outbox record and idempotency key before an irreversible effect; no retry of a non-idempotent action on `UNKNOWN`. |

### 8a.3 Verification and CI

`A-051` (the closed loop, ten cases, with **the self-report build as the negative control**) and `A-052` (injection and mid-episode stop). **CI-052** `endpoint-action-typed`, **CI-053** `endpoint-observation-independent`, **CI-054** `endpoint-episode-transitions` — all three `PENDING`, because all three need the endpoint adapter layer that F0 has not authorised. The **contract half is enforceable today**: the required-field set in `endpoint_interaction.schema.json` makes an unverifiable action structurally unrepresentable, and the `const` on `observation_plan.independent_of_actuator` makes a self-grading actuator unrepresentable.

### 8a.4 Model and node agnosticism

Nothing in this section names a model, a vendor or a product. The target of an interaction is a **node identity plus a surface class plus a measured capability requirement**. Which node satisfies that is `DF-PLACE`'s answer at the moment of acting and may differ on the next episode; an unmeasured endpoint capability is treated as unavailable (`INV-HW-2`). `A-051.10` re-runs the whole suite with a different planner model and a different host node and requires every assertion to hold.

---

## 9. Jarvis-divergence check

> *Could an implementation agent satisfy REM-012 while building an ordinary chatbot?*

**No, at two points.** **§2** — the transactional outbox with a per-tool reconciliation probe presupposes that VESPER acts on the world and must later determine *whether it did*; a chatbot's tool calls return synchronously and are never reconciled after a crash, because it has no crash to survive. **§3** — alarm ownership with a partition failure-direction presupposes multiple nodes competing to wake a human. Neither has any meaning in a request-scoped system, and `A-035`'s crash-injection case cannot be passed by one.
