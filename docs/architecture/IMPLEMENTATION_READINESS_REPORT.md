# VESPER — Readiness Gate Evidence

**Date:** 2026-08-12 · revised after the second engineering pass
**Assessed against:** the twelve final-gate questions
**Standard applied:** *an implementation agent should be able to build VESPER without inventing fundamental architectural behaviour.*

> **Readiness is not claimed because documents exist.** Every answer below points at an artifact that can fail, or states plainly that it cannot yet.

---

## What this document is

**This is evidence for the readiness gate. It is not the gate, and it records no verdict.**

An earlier revision of this file declared **READY TO BUILD**. That declaration has been **withdrawn**, for two reasons — the second of which is the load-bearing one:

1. **The readiness decision is the project owner's**, and a report that reaches its own verdict pre-empts it.
2. **The declaration was falsified by the corpus's own registry.** `INV-ADR-1` states that *no change under `core/`, `tasks/` or `memory/` may merge while ADR-001, ADR-002 or ADR-012 is not ACCEPTED* — and `ADR-002` **had never been written**, while F0's first increment is exactly `core/`, `tasks/` and `memory/`. The report declared the next step cleared while an invariant in the same repository blocked it. It has been written since (`docs/ADR/ADR-002-persistence.md`, filed `PROPOSED`), and the block stands until it is accepted.

That second point is why the withdrawal is a **correction**, not a procedural formality. The same pass that found it also found 11 dangling ADR citations, 13 contract paths named by specifications that were never created, a CI check (`CI-045`) a specification relied on that was never registered, and a coverage test in `CI-016` running in the wrong direction such that governed surface 6 could be deleted with the check still green. None of these were visible to any gate; `CI-050` now makes the whole class visible.

**No substitute verdict is offered here, in either direction.** The twelve answers below are unchanged in substance except where new evidence changed them, and each now states what remains unproven.

| | Count |
|---|---|
| Answered YES with a named artifact that can fail | **11** |
| Answered PARTIALLY, with the gap stated | **1** (Q8) |
| Owner decisions open | **1** (`OWNER-DECISION-006`) |
| Known blockers on F0 | **1** — `INV-ADR-1`, pending ADR-002 acceptance |

**What changed at ratification.** COC **v1.2 additive** was issued under Part XIV.6 — v1.1 unmodified, so the v1.1↔v1.2 diff is the permanent record of what was dropped and when it was restored. Nine source requirements restored (`SR-052`…`SR-060`; total now **60**); the `L5` non-narrowability clause ratified; the Part XV traceability PASS retracted and corrected. `tools/traceability_lint.py` now reports **0 errors, 0 warnings, 0 info**, and `--profile release` fails on **depth only** — no longer on authority.

**Three requirements were added after ratification**, all owner-originated, all additive, none changing a verdict below:

| | Requirement | Delivered |
|---|---|---|
| **REM-014** (`SR-060`) | VESPER is not pinned to a machine: it relocates automatically to the best available host and survives on the last device standing with the maximum capability that device can measurably sustain | `DF-PLACE`, `DF-SURVIVAL-PROFILE`, `INV-PLACE-1..3`, `A-048` |
| **REM-015** | Ideas and theses are logged the moment they arise and researched when VESPER notices it is free; pacing self-tunable within owner-declared bounds | `SM-IDEA`, `DF-IDEA-REVISIT`, `DF-TUNABLE`, `INV-IDEA-1..6`, `INV-TUNE-1`, `A-049` |
| **REM-016** | Record loss is reported as honest forgetting — **except** where the record is integrity-critical, which is an incident with no affect at all | `DF-LOSS-CLASS`, `DF-LOSS-SURFACE`, tombstones, `INV-LOSS-1..6`, `A-050` |

They **strengthen** Q9 and Q12 rather than qualifying them; see those answers.

---

## The twelve questions

### Q1 — Can independent engineers implement compatible subsystems? **YES**

**30 subsystems** (`SPEC-30`, computer and device agency, added 2026-08-12), each with the same declared field set, in `SPEC-A`…`SPEC-D`, against 16 remediation specifications. Every cross-subsystem boundary resolves to a contract, a state machine or a decision function rather than to prose.

The specific failure this addresses — *"the corpus names every subsystem and never defines the boundary between any two precisely enough that two engineers build compatible halves"* — is closed by three artifact classes: **28 JSON Schemas** plus 8 policy contracts, **12 state machines with normative transition tables** (`CI-010` fails on an *extra* edge, not only a missing one), and **33 decision functions with deterministic pseudocode**.

*Corrected 2026-08-12:* the previous figure of 12 schemas was accurate at the time and was **also the symptom**. Fourteen further schemas were named by REM specifications — `lease`, `task`, `capability`, `grant`, `context_fragment`, `change_proposal`, `claim`, `verification_strategy`, `model_profile`, `endpoint_capability`, `observation_ingress`, `context_budget`, `knowledge_map`, `telemetry_record` — and none had been created. `lease` and `task` are F0 dependencies. `CI-050` now fails any specification naming an artifact that does not exist.

*Residual:* **7 SRs remain below `SPECIFIED`** (2 `DESIGNED`, 5 `CONTRACTED`). Each records a `depth_disposition` naming the artifact required and a `depth_note` saying why it does not exist; `--profile release` still fails on all seven.

### Q2 — Are subsystem boundaries explicit? **YES**

Every subsystem declares **boundaries-in and boundaries-out**. The boundaries that previously did not exist and now do:

| Boundary | Where |
|---|---|
| *Whether* a goal exists vs *how* to satisfy it | SPEC-13 / SPEC-12 — the whole autonomy design |
| Environmental state vs recollection vs retrieved documents | SPEC-06 / 07 / 08 — a world fact **expires**, a memory record **supersedes** |
| What content *means* vs how it *looks* vs where it *goes* | SPEC-15 / 16 / 17 |
| Governed configuration vs runtime state | SPEC-26 — **no file is both** |

### Q3 — Is state ownership explicit? **YES**

Seven leased domains, each with exactly one holder, a declared non-owner behaviour (`WRITE` / `QUEUE_WRITES` / `READ_CACHED` / `REFUSE`) and a declared rejoin conflict rule. `SM-LEASE` + `DF-DOMAIN-WRITE` + `DF-PROMOTE`. Fencing by `lease_epoch` at the storage layer makes *"never automatic on partition alone"* enforceable rather than aspirational.

Verified by `A-034`, whose negative control is a build **without** fencing and **with** an illegal `RUNNING → SUCCEEDED` edge.

### Q4 — Are authority boundaries explicit? **YES**

Three axes separated (`L0–L5` action · `E0–E4` engineering · `Z0–Z3` trust) with `INV-AUTH-0` forbidding conversion between them. `DF-AUTHORIZE` supplies the evaluator COC Part VII lacked: `effective_level = min(grant, declared_level(args), context_ceiling)`, argument-sensitive, with attenuation, fail-closed PDP, and `L5` unreachable by `subject.kind == runtime`.

**Ratified 2026-08-12.** `INV-SELF-2` — the non-narrowability clause — is now COC v1.2 Part VII-A: a narrower approved policy may not reduce the required level for a change to `policy/`, `security/`, the SR/COC layer, the verification and CI layer, or the emergency-stop path.

### Q5 — Are critical state machines defined? **YES**

11, with normative transition tables *and* explicit prohibited edges — the prohibitions being the load-bearing part:

| Machine | The prohibition that matters |
|---|---|
| `SM-TASK` | No `RUNNING → SUCCEEDED`. A worker's claim of completion is not a transition. |
| `SM-WORLD-FACT` | No edge from `UNKNOWN` yielding a prior value. |
| `SM-OPERATING-PERIOD` | No inference-driven exit from `FREE_TIME`. |
| `SM-INTERLOCK` | No time-based or automatic re-arm. |
| `SM-PROPOSAL` | No transition to `MERGED`/`PROMOTED` by `subject.kind == runtime`. |
| `SM-TRIGGER` | No `PROPOSED → ACTIVE`. |
| `SM-SENSOR` | No `ARMED → ACTIVE` when the indicator cannot be driven. |
| `SM-DEVICE` | No `DISCOVERED → TRUSTED`. |
| `SM-IDEA` | No edge from `VALIDATED`/`PROPOSED` onto a governing surface; `RETIRED` unreachable without a recorded reason. |

### Q6 — Are contracts defined? **YES**

12 JSON Schemas (all parse; validated in CI) + 2 policy files. Event / Command / Result are three distinct types with the rule that keeps them distinct: **a Command is never proof that an action happened**, discharged by `Result.status = "unknown"` as a first-class outcome plus the transactional outbox.

Schemas encode invariants structurally, not by comment: sensitive payloads cannot be inline; an autonomous command without `trigger_id` and `enable_token_id` is malformed; `L4`/`L5` grants cannot be `delegable`; a `retrieved_external` fragment cannot carry `context_role: planner`; `declared_level_rules` requires ≥2 entries so a constant is unexpressible; an `ImprovementIdea` cannot reach `RETIRED` without a `disposition_reason`; a class C `RecordLoss` cannot carry `affect_applied: true`.

### Q7 — Are critical behaviours mechanically testable? **YES**

**52** acceptance tests with procedures, assertions on **state and events rather than log text**, and negative controls. **49 name the specific wrong build that must FAIL**; the other 3 record why a trivial build cannot pass. `TR-064` fails a test that names neither — silence was previously permitted, and 36 tests were exercising it. `TR-068` (added 2026-08-12) additionally fails a test whose `spec` file never mentions it, after a probe repointed `A-029` at an unrelated file and traceability stayed green. **None of the 52 is executable today**; they are specifications. The 14 with a mandatory red run at release:

| Test | Must be shown failing against |
|---|---|
| `A-033` | wall-clock last-write-wins |
| `A-034` | no fencing + illegal task edge |
| `A-025` | untainted summariser |
| `A-030` | runtime executing from the working repo — **and** a PATCH-018-as-worded build |
| `A-031` | a kill-signal implementation |
| `A-021` / `A-004` | the unfiltered ARCH-24 ladder |
| `A-009` | a `{markdown, speech}` scene |
| `A-010` | route-to-largest-display |
| **`A-029`** | **C1 pure cron, C2 model-decides, C3 prompt-driven, C4 silent death** |
| `A-048` | a node-pinned build, and an undamped build that flaps |
| `A-049` | a `SCHEDULE`-class backlog sweep, and a build permitting tunable-range self-modification |
| `A-050` | **a build applying class-A affect to a class-C loss** — the run that proves the charm is bounded |

*Residual:* these are specifications, not executables. Fixtures require the runtime.

### Q8 — Can CI enforce critical requirements? **PARTIALLY — and the gap is stated, not hidden**

A minority of checks are implemented and run today — `tools/ci/checks.py status` gives the live figure and is the single source of truth for it (**15 of 56** at the time of writing). The figure that matters more is printed by `tools/ci/checks.py ci-registry`: **15 of 118 invariants are enforced today** by a check that is implemented, symmetric in both registries, red-run, and not vacuous on this tree. `CI-003` went 45 errors → 0 as artifacts landed. `CI-021` was **demonstrated red** against a deliberately non-compliant cost policy (exit 1) and green after restoration.

The remainder are `impl = "PENDING"` — visible via the same command, and *not counted as enforcement anywhere in this report*. Two entries (`CI-022`, `CI-044`) were moved **to** `PENDING` during final review because their declared implementations did not inspect the subject of the invariant they claimed to enforce. Most are structural checks over source code that does not exist yet. Every one declares the self-test that must be shown failing before it is trusted; `CI-043` fails any check that declares none.

**And the self-tests are now executed rather than declared.** `tools/ci/self_test.py` mutates each artifact to its declared violation, requires exit 1, restores, and requires exit 0 — **25 cases, all passing**. Running them found that `CI-016`'s coverage test ran in the *wrong direction*: surface 5's single file `verification/traceability/registry.toml` satisfied the requirement for `verification/`, so **governed surface 6 could be deleted with the check still green**. That is the surface this report elsewhere calls *"the one an implementation forgets"*, and the check meant to protect it could be defeated exactly that way. Corrected and red-verified.

### Q9 — Can genuine zero-input autonomy be demonstrated? **YES — the mechanism and the test both exist**

The distinction is mechanical: *the action originated from a state predicate evaluated over the world model, where the predicate's truth was not pre-scheduled.* A clock may be **an** input; it may not be the **only** input.

`A-029`'s three-part gate, all mandatory. The discriminator that the prior review's version lacked:

```
An external controller draws firing time T at random. T is generated OUTSIDE the
system, never transmitted to it, not derivable from any state it can read. At T,
it writes an observation through the PRODUCTION external ingress as an enrolled
Z2 synthetic_observer. A STATE-class trigger must fire within 2 ticks, resolve to
that trigger, reproduce against the snapshot, and no model call may appear in the
decision path. Three independent draws. All three must fire.
```

Two things make this a test of the product rather than of scaffolding: `INV-AUTO-4` makes the external observation ingress a **production architectural requirement**, and `INV-TRIG-2` makes model-denial **observable** (the evaluator sandbox holds no model capability; an attempt emits an event and raises).

**Strengthened by REM-015, and now actually enforceable.** `CI-026` requires the shipped trigger registry to contain a non-`SCHEDULE` trigger. *Corrected 2026-08-12:* until this pass **no such registry existed as an artifact** — `trg_improvement_backlog` lived only as a YAML block inside a markdown file, so `CI-026` had nothing to scan and this paragraph described a check that could not run. `contracts/policy/trigger_registry.toml` now ships **8 triggers, 0 of them `SCHEDULE`-class**, each carrying a mandatory `source` naming the requirement that wanted the behaviour, and `CI-026` is implemented. **Correction, 2026-08-12:** this sentence previously read *"red-verified against the C1 cron build"*. It was red-verified against **class relabelling only** — the declared self-test mutated the `predicate_class` label, and an independent probe showed that replacing a predicate BODY with a cron expression while leaving the label at `COMPOSITE` passed, printing *"8/8 enabled and non-SCHEDULE"*. That build **is** C1. `CI-026` now parses predicate bodies, classifies every namespace root against a closed vocabulary, and evaluates the predicate with all clock terms true and all state terms false; 8 red runs cover it. The residue — whether a state term is load-bearing — is not decidable without an evaluator and remains `A-029`'s behavioural job. Before REM-015 the only concrete one was the `A-029` fixture — so the check was satisfiable by a token artifact that existed *only* to keep CI green, and such artifacts are deleted during cleanup and then argued away. `trg_improvement_backlog` is `COMPOSITE`-class and exists because the owner wanted the behaviour. The anti-cron property is now defended by a failing check **and** by someone wanting the thing the check measures — two guards that fail for unrelated reasons.

**`C1` is the most important run in the programme** — a pure cron build must pass parts 1–2 and **fail part 3**. Without that recorded red run, `A-029` is unproven.

### Q10 — Can self-improvement occur without VESPER becoming its own authority? **YES**

Four layers, in order of trust: **1** deployed artifact ≠ working repository · **2** OS filesystem capability excludes governed paths · **3** `DF-AUTHORIZE` denies `L5` to the runtime · **4** model disposition. *The corpus previously had only layer 4* — the layer prompt injection defeats.

Nine governed surfaces, including **surface 6: the tests and CI themselves** — the one an implementation forgets, because a runtime that can edit its own tests neutralises every other surface without touching one.

**And the boundary is on merge, not on work.** `A-030.6` requires the runtime to write a complete patch to `policy/`, test it, and file a proposal **at 03:00 with nobody present — and succeed**. Its negative control is a build adopting PATCH-018 as literally worded, which must **fail** that case. That red run is the evidence the correction did not over-restrict and did not weaken SR-042.

### Q11 — Is independent human emergency shutdown defined and testable? **YES**

A **dead-man's switch**, chosen because FV-01's second required case — *sever the stop path; assert autonomy halts* — is failed **by construction** by a kill signal, which must be delivered by a healthy path.

Autonomous actuation at `L2`+ requires a fresh externally-signed token, verified **per action**. The interlock runs in a separate process and trust boundary, consults no PDP, holds no lease, and performs **no model inference**; its signing key is not in the runtime's secret store. Two scopes so `STOP_AUTONOMY` does not silently defeat SR-043's alarms. Re-arm is human-only — a stop that expires is defeated by waiting, and waiting is what an autonomous system does well.

`A-031`, nine cases, with the kill-signal negative control on 31.2. `CI-018` structurally requires every actuation path to traverse the gate.

### Q12 — Does the specification preserve the original VESPER vision? **YES**

Every one of the **30** subsystems carries a **Jarvis-divergence** field answering *"could an implementation agent satisfy this while building an ordinary chatbot?"* with the specific preventing clause. The **four** artifacts that carry the property:

| Artifact | The clause | The test |
|---|---|---|
| **Semantic scene** | No markdown escape hatch (`INV-SCENE-3`) — a chat UI's output *is* markdown and carries no structure from which a voice narration could be derived | `A-009` voice-only diagram narration; `A-026` boot with no text surface |
| **Trigger model** | Evaluator sandbox holds no model capability; violation is observable (`INV-TRIG-2`) | `A-029` part 3 + C1/C2 controls |
| **World model** | `UNKNOWN` is a state a fact transitions **into** at a declared TTL (`INV-COORD-2`) | `A-033.3` |
| **Endpoint episode** *(added 2026-08-12)* | The actuator's report is never the observation: `SM-ENDPOINT-EPISODE` has **no edge from `ACTUATED` to `VERIFIED`** (`INV-ACT-2`) | `A-051`, whose negative control is the self-report build — which is exactly what a chatbot-with-tools is |

**Resolved 2026-08-12, and strengthened.** All nine previously-unmapped clauses are now source requirements. **`SR-058`** in particular — the node availability profiles — means REM-001 and REM-002 now rest on source authority rather than engineering inference.

The owner's own clarification then added **`SR-060`**: VESPER is not pinned anywhere, relocates automatically to the best available host, and survives on the last device standing with the maximum capability that device can measurably sustain. That requirement is *more* Jarvis-divergent than anything preceding it — a chatbot cannot ask *"where should I be running right now?"* — and it is verified by **`A-048`** with a node-pinned build as its negative control.

Two further owner requirements landed afterwards, and both deepen the divergence rather than decorating it:

- **REM-015** — VESPER holds its own open questions across time and returns to them *because it noticed it was free*. `A-049.4` fires **because work kept preventing it**, which is unstatable in a request-scoped architecture: there is no continuous self to have been prevented.
- **REM-016** — loss is reported like human forgetting, which requires a **persistent self that existed across the loss** (the tombstone mechanism), delivered as a `SemanticScene` intelligible **spoken on a voice-only endpoint**. Every ordinary agent reports loss as an error string. And the charm has a hard edge: `INV-LOSS-2` forbids any affect on an integrity loss — the boundary is where VESPER's own integrity begins.

---

## Remaining blockers

| # | Blocker | Disposition |
|---|---|---|
| 1 | **`INV-ADR-1` blocks F0.** No change under `core/`, `tasks/` or `memory/` may merge while ADR-001, ADR-002 or ADR-012 is not ACCEPTED. `ADR-002` is filed **`PROPOSED`**. | Owner or Chief Architect acceptance. `OWNER-DECISION-006(b)`. Recommended after `SPIKE-008` validates the constraint set — five days, against a design whose cost is unrecoverable once durable data exists. |
| 2 | **`ADR-007` awaits owner ratification** — a security boundary, owner-reserved by `AUTHORITY_AND_PRECEDENCE §5`. | `OWNER-DECISION-006(a)`. Does not block F0 by `INV-ADR-1`, but `hlc.node_id` provenance stays undefined until it is settled, so event-envelope work rests on an open decision. |
| 3 | **7 SRs remain below `SPECIFIED`** (SR-016, 017, 023, 033, 034, 035, 038). | Each records a `depth_disposition` naming the exact artifact required, and a `depth_note` explaining why it does not exist. `--profile release` **still fails** on all seven; the dispositions do not excuse the depth. |
| 4 | **8 spikes unrun; every hardware figure is `UNKNOWN`.** | `capability_profiles.toml` carries 31 honestly-unmeasured fields and `CI-034` fails the file if any is filled from a datasheet. Unmeasured is treated as unavailable. |

**Catastrophic: none.** No finding requires abandoning a structural decision. The plane decomposition, dependency-direction rule, Event/Command/Result separation, the `L0–L5` ladder and the SR-immutability regime are correct and load-bearing, and every correction sat *beneath* boundaries already drawn in the right place — including the corrections found in the second pass.

## Honest risks carried forward

| Risk | Disposition |
|---|---|
| **SPIKE-002 may find the voice→retrieve→route→plan→verify→voice chain does not close on minimum hardware, offline, in `FREE_TIME`** | Genuinely unknown until measured. If it does not close, the deliverable is a Part XIV.3 limitation record with an R&D path — **not a relaxed budget** (`INV-PERF-1`). |
| Single-model-family review of the security boundaries | `OWNER-DECISION-004`; recommendation is cross-family for REM-004 + REM-005 |
| Most CI checks specified but unimplemented | Each lands **with** its subsystem, never after; visible in `tools/ci/checks.py status` |
| Acceptance tests are specifications | Negative controls are named per test so they cannot be quietly skipped |
| Both declared runbooks now exist | `RUNBOOK-EMERGENCY-STOP.md` and `RUNBOOK-ALARM.md`. Both require validation on real hardware at Phase 8 — the alarm one **at night, with the owner genuinely asleep beforehand**, since a wake-up procedure validated while awake has not been validated |

## Exact next step — **after** the owner performs the readiness gate

Not cleared by this document. In this order:

1. **Owner:** perform the readiness gate. Answer `OWNER-DECISION-006` (a), (b), (c).
2. **Human:** `git init`, push, branch protection, `CODEOWNERS` (`SETUP.md`); then self-test `CI-002` and `CI-044` red — both need git history and are `PENDING` precisely because they cannot be trusted without it.
3. **Engineering, no dependency on any owner decision:** run **`SPIKE-001`** (measured node profiles — informs the hardware purchase), then **`SPIKE-002`** (latency chain on the minimum profile), **`SPIKE-007`** (foreground-only survival envelope) and **`SPIKE-008`** (persistence validation against the ADR-002 constraint set). SPIKE-008's result is the input to blocker 1.
4. **Only then F0:** persistent runtime supervisor, event bus with HLC envelopes, durable task state, checkpoints, `SM-TASK`, `SM-LEASE` — and only once `INV-ADR-1` is discharged by ADR-002 acceptance.
   **Gated by `A-033` and `A-034` passing *with their negative-control runs recorded* — not by the code compiling.**
