# VESPER V0 — ARCHITECTURE GAP REGISTER

**Review date:** 2026-08-11
**Purpose:** Every architectural decision that an engineer or coding agent would have to **invent** because the current documents do not specify it.

---

## Classification

| Class | Meaning | Count |
|---|---|---|
| **MUST DEFINE BEFORE BUILD** | Missing decision likely to cause architectural rework. Blocks the first line of code in the affected area. | **32** (§A: 21, §E: 11) |
| **DEFINE DURING SUBSYSTEM** | Local implementation detail; does not threaten a system boundary. | **14** (§B) |
| **RESEARCH SPIKE** | Unknown technology requiring empirical investigation before the decision can be made. | **6** (§C) |
| **OPTIONAL** | Useful but not required for VESPER V0. | **4** (§D) |

**56 entries total.** The register is deliberately not exhaustive of every unspecified detail — per mandate, the specification is not inflated for theoretical completeness. Entries qualify only where a *system boundary, persistence, identity, security, autonomy, contract, or recovery* consequence is demonstrable, or where the decision is genuinely deferrable and worth recording as such.

The mission's own standard is applied throughout:
> *"Do not accept 'we can figure that out later' when the missing decision affects system boundaries, persistence, identity, security, autonomy, contracts, or recovery."*

---

## A. MUST DEFINE BEFORE BUILD

### A1 — Persistence, eventing, and coordination

| ID | Missing decision | Category | Why it cannot wait | Rework if deferred | Ref |
|---|---|---|---|---|---|
| **GAP-001** | **Event delivery guarantee** — at-most-once / at-least-once / effectively-once | Concurrency, error semantics | Determines whether every consumer needs idempotency, and whether a world-model write can be applied twice | Every event producer and consumer; all world-model write paths | AR-003, AR-009 |
| **GAP-002** | **Event ordering guarantee** — global / per-source / per-subject / none | Concurrency | Determines whether observation supersession is possible at all | World model, task state machine, autonomy triggers | AR-003 |
| **GAP-003** | **Clock model** — wall clock vs. monotonic vs. logical/hybrid | Concurrency, invariants | The corpus's freshness rule ("timestamps + confidence") is only sound if clocks agree; they will not, across a roaming laptop and a legacy handset | Every timestamped record; the entire freshness/expiry mechanism | AR-003 |
| **GAP-004** | **Persistence engine and durable schema** for task state, memory, world model, checkpoints | Persistence, migration | Foundation increment #2 *is* "event contract + durable task state" — unbuildable without this | Increments #2–#7; Phases 1–5 | AR-009, ADR-002 |
| **GAP-005** | **Control-plane topology** — singleton, singleton+standby, or replicated | Ownership, identity, deployment | Determines whether VESPER survives the MacBook leaving the house, which is the COC's headline claim | Control plane, persistence, device trust, deployment | AR-002, ADR-012 |
| **GAP-006** | **State-domain ownership + lease model** — who authoritatively owns tasks / world / memory / devices / policy / autonomy queue, and what a non-owner may do | Ownership, concurrency | Without leases, two nodes write the same task and diverge silently | Control plane and every state consumer | AR-002 |
| **GAP-007** | **Partition behavior and rejoin/merge procedure** | Concurrency, recovery | The source *designs in* intermittency ("desktop may be disconnected", "J3 may be offline") — this is a normal operating mode, not an exception | Recovery paths, queueing, world model | AR-002, AR-003 |
| **GAP-008** | **Observation supersession and TTL/expiry rule** — when does a fact become UNKNOWN rather than "last known value" | Invariants, error semantics | RB-002 forbids guessing; a stale fact presented as current *is* a guess | World model, presence routing, autonomy eligibility | AR-003 |
| **GAP-009** | **Task state machine transition table** — legal transitions, triggers, guards, terminal states | State machines | 04 §5 names states (`CREATED → READY → RUNNING → WAITING → VERIFYING → SUCCEEDED`, plus `RETRYING/BLOCKED/FAILED/CANCELLED/RESUMABLE`) but defines no transitions, so no two implementations will agree | Task system, agent runtime, recovery, checkpointing | AR-015, IC-007 |
| **GAP-010** | **Checkpoint format and resumption semantics** — what is captured, at what granularity, and what "resume" means for a partially-executed plan | Persistence, recovery | RB-035 requires checkpointing for all autonomous work; A-002/A-011/A-017 all depend on it | Autonomy, tasks, agents, migration | AR-002 |

### A2 — Security and authorization

| ID | Missing decision | Category | Why it cannot wait | Rework if deferred | Ref |
|---|---|---|---|---|---|
| **GAP-011** | **Authorization decision function** — subject, resource, argument-sensitivity, and the mapping from request to L0–L5 | Authorization | Part VII is a taxonomy with no evaluator. `shell.run("ls")` and `shell.run("rm -rf ~")` are the same tool | Every tool, the policy layer, the audit chain | AR-006 |
| **GAP-012** | **Capability grant representation and delegation/attenuation rule** — what a spawned agent inherits | Authorization, security boundary | SR-014 permits unbounded agent fan-out; without attenuation a sub-agent processing a web page holds its parent's L4 authority | Agent runtime, tool gateway, task schema | AR-006 |
| **GAP-013** | **Policy decision point location + unavailability behavior** (fail-open vs. fail-closed) | Security boundary, error semantics | An unstated default becomes fail-open, because that is what makes the demo work | Policy layer, every call site | AR-006 |
| **GAP-014** | **Context taint model and authority ceiling** — trust classes, propagation through summarization/caching, and the level cap for externally-derived content | Security boundary | The highest-consequence unspecified control: unattended overnight web research with shell and comms access | Context assembler, router, tool gateway, cache | AR-007 |
| **GAP-015** | **L4 confirmation binding** — what a confirmation authorizes (one action instance vs. a task vs. a session), how it is obtained when no authenticated surface is present, and its expiry | Authorization, lifecycle | Determines whether one "yes" can authorize six agents' worth of external action | Tool gateway, presence, audit | AR-006, AR-028 |
| **GAP-016** | **Node enrollment admission criteria** — the gate between `ENROLLED` and `TRUSTED` | Security boundary, lifecycle | 05 §4 correctly says "visibility on a LAN does not imply trust" and never says what does | Device fabric, network, trust zones | AR-018 |
| **GAP-017** | **Secret storage mechanism and model-context exclusion enforcement** | Security boundary | Stated as a rule ("never ordinary telemetry", "minimized model exposure") with no mechanism; provider credentials are the highest-value target on the network | Model gateway, telemetry, config | AR-035 |

### A3 — The three artifacts that define VESPER

| ID | Missing decision | Category | Why it cannot wait | Rework if deferred | Ref |
|---|---|---|---|---|---|
| **GAP-018** | **`SemanticScene` schema** — element taxonomy, presentation intent, spatial anchoring, update/streaming semantics, interaction affordances, endpoint capability descriptor, declared degradation ladder | Interface, schema | This is the artifact that makes "VESPER is not a chat UI" true rather than asserted. Without it the first renderer defines it as `{markdown, speech}` and the projector/glass adapters cannot be built on it | **Entire Presence plane plus every producer of user-visible output** — the largest rework surface in the project | AR-001 |
| **GAP-019** | **`Trigger` definition and registry** — predicate language over world-model/task/schedule state, debounce, priority, budget, stop conditions | Interface, schema, autonomy | Part V §28 forbids "a cron job that runs isolated scripts" without specifying the alternative. The only two implementable options in the absence of a spec are both forbidden | Autonomy plane; RB-019 explainability; A-018 auditability | AR-008 |
| **GAP-020** | **World-model entity keying, identity resolution, and `Person` typing** — including a hard `owner` vs. `unknown_person` distinction | Schema, invariants, privacy | SR-029 inference and SR-040 OCR both need to know *whose* state and *which* person; guests are currently unmodelled | World model, perception, presence routing, privacy controls | AR-019, AR-027 |
| **GAP-021** | **Spatial representation** — topological room graph vs. metric coordinates vs. pure relational | Schema | SR-028 ("define their place from network and cameras") and 05 §10 (presence "by proximity") are both unimplementable without one | World model, presence routing, device fabric | AR-019 |

---

## B. DEFINE DURING SUBSYSTEM IMPLEMENTATION

These are genuinely local. Recording them prevents them being mistaken for architecture later.

| ID | Missing decision | Subsystem | Note | Ref |
|---|---|---|---|---|
| **GAP-022** | Provider error taxonomy (retry-worthy / switch-worthy / fatal / content-policy) | Model gateway | Local to IC-002 provided the enum is versioned in `contracts/` | AR-031 |
| **GAP-023** | Per-credential quota tracking with rolling windows | Model gateway | Free tiers rarely expose introspection; quota must be inferred locally | AR-031 |
| **GAP-024** | Mid-stream provider failure handling per modality | Model gateway + presence | Voice continuation must be semantically resumable; needs GAP-018 first | AR-031 |
| **GAP-025** | Task complexity classification method for SR-009 routing | Router | Heuristic vs. classifier vs. declared-by-planner — all viable, none boundary-affecting | AR-013 |
| **GAP-026** | Resource governor damping constants (dwell time, hysteresis band, transition cap) | Resource governor | Tunable; the *requirement* that damping exist is architectural, the values are not | AR-032 |
| **GAP-027** | Cache invalidation strategy per tier (file-hash / chunk / embedding / summary / prefix) | Knowledge | Local, provided cache entries inherit taint (GAP-014) | AR-011 |
| **GAP-028** | Map representation and update strategy for project/knowledge maps | Knowledge | Local, provided retrieval returns exact source spans (GAP-036) | AR-011 |
| **GAP-029** | ASR / TTS / wake-word engine selection | Presence | Adapter-isolated by the dependency-direction rule | — |
| **GAP-030** | OCR engine selection and preprocessing pipeline | Perception | Adapter-isolated | — |
| **GAP-031** | Video frame-sampling and motion-comparison strategy | Perception | Local to the media evidence pipeline | AR-024 |
| **GAP-032** | Sandbox mechanism for code execution (container / VM / OS sandbox) | Tools | Local **provided** the trust-zone boundary (GAP-014) is already fixed | ADR-006 |
| **GAP-033** | Report/artifact rendering stack (MD/PDF/HTML) | Artifacts | Local, provided artifacts carry provenance | AR-013 |
| **GAP-034** | Alarm escalation ladder specifics (volumes, intervals, device order) | Alarm | Local; the *ceiling*, *ownership*, and *ack channels* are architectural (GAP-041) | AR-026 |
| **GAP-035** | Telemetry storage backend | Observability | Local, provided retention and sensitivity enforcement are specified (GAP-042) | AR-035 |

---

## C. RESEARCH SPIKE

Empirical investigation required before the decision can responsibly be made. Each should be time-boxed and **deliver an ADR, not a prototype**.

| ID | Question | Deliverable | Blocks | Ref |
|---|---|---|---|---|
| **SPIKE-001** | What local model quality and sustained throughput is achievable on each candidate machine, and what is the **minimum viable profile** for SR-005 local fallback? | Measured `NodeCapabilityProfile` values per candidate; a declared minimum profile | Hardware purchase decision; SR-005, SR-006; GAP-037 | AR-017 |
| **SPIKE-002** | Can the SR-046 × SR-047 × RB-004 × SR-045 latency chain close on the minimum profile? (voice-in → retrieval → route → plan → verify → voice-out, local models, offline) | Per-stage latency budget with measured feasibility; if it does not close, a Part XIV §3 limitation record with an R&D path | SR-047 quantification; verification strategy design | AR-023, AR-024 |
| **SPIKE-003** | What kernel/OS-level access is actually available per platform (macOS, Windows, Android, iOS), at what privilege, under what entitlement, with what user consent? | Per-platform feasibility matrix | SR-026; **Part XIV §3 record is currently missing and required** | AR-020 |
| **SPIKE-004** | What is the real optical feasibility envelope of the glass/holographic output, and what scene properties does it constrain? | Feasibility report + the constraints it imposes on GAP-018's schema | SR-002, SR-018 physical adapter (contracts are **not** blocked — they proceed now) | AR-001, AR-018 |
| **SPIKE-005** | Is programmatic call/FaceTime-style delegated presence achievable on the target platform without deceptive impersonation? | Feasibility report; if infeasible, a Part XIV §3 limitation record following the DR-031 pattern | SR-031 | AR-021, AR-020 |
| **SPIKE-006** | Wi-Fi / RF through-wall sensing feasibility, accuracy, and legality | Already correctly scoped by DR-031 as an isolated, default-disabled research adapter — **the model the other five spikes should follow** | SR-037 (R&D track only) | — |

---

## D. OPTIONAL

| ID | Item | Why optional |
|---|---|---|
| **GAP-047** | Speculative decoding | Handwritten source says "if available"; a throughput optimization with no boundary consequence. Should nonetheless receive an SR for traceability (AR-011) |
| **GAP-048** | Interactive desk / spatial input surface | Source says "possibly". Covered by GAP-018's endpoint abstraction if that is done correctly — which is the test of whether GAP-018 was done correctly |
| **GAP-049** | Ambience/lighting control beyond displays | SR-030 is core, but the physical lighting integration specifically can follow the actuator contract without new architecture |
| **GAP-050** | Additional weak laptop node | Source says "possibly". Absorbed by the `NodeCapabilityProfile` abstraction (GAP-037) |

---

## E. Remaining MUST-DEFINE entries (cross-cutting)

| ID | Missing decision | Category | Why it cannot wait | Ref |
|---|---|---|---|---|
| **GAP-036** | **Claim-level evidence envelope + output gate** — `{claim, support[], support_type, confidence}` and the policy-class rule for what may be emitted unsupported | Invariants | "No guessing" is the most-repeated behavioral requirement in the corpus and currently has no mechanism. Retrofitting evidence tracking into a generation pipeline is a rewrite, not an addition | AR-014 |
| **GAP-037** | **`NodeCapabilityProfile` schema + per-subsystem minimum profiles**, with throughput **measured at enrollment** rather than declared | Schema, hardware assumptions | Hardware agnosticism is asserted in three documents and implemented in none. Without this, "MacBook Neo" ends up in config and hardware substitution becomes a migration | AR-017, AR-034 |
| **GAP-038** | **`OperatingPeriod` state machine** with the fail-closed asymmetry (inference may enter FREE_TIME, never exit it) | State machine, invariants | An absolute cost prohibition is currently gated on an explicitly-untrusted inference. Both error directions violate a stated absolute | AR-004 |
| **GAP-039** | **`cost_class` on every credential and model profile + a single gateway choke point** that no caller can bypass | Invariants, provider assumptions | Arch §24's fallback ladder currently routes free-tier exhaustion onto paid providers **by design**, contradicting RB-017 | AR-005, AR-033 |
| **GAP-040** | **`VerificationStrategy` taxonomy bound to task class**, plus disagreement handling and typed `verification_criteria` | Interface, error semantics | RB-004 requires a machine-checkable acceptance condition on every task; IC-007's field has no type. Also the natural implementation (retry until the verifier agrees) silently destroys the control | AR-015, AR-024 |
| **GAP-041** | **Priority lattice** (alarm/safety > task > ambience > proactive) + alarm ownership/failover + escalation ceiling + non-ASR acknowledgment | Invariants, ownership | Without a lattice, a quiet-hours policy silently suppresses the alarm; without an ack ceiling, maximum-volume escalation at 03:00 has no guaranteed stop | AR-026 |
| **GAP-042** | **Sensor lifecycle state machine + per-modality retention + guaranteed-off path** | Lifecycle, privacy | Always-on mics and cameras in a home with no consent model, no indicator obligation, and no retention rule | AR-027 |
| **GAP-043** | **Transactional outbox + per-tool reconciliation probe + `reversibility` classification** | Persistence, error semantics | "A command is never proof that an action happened" is correctly stated and never discharged. Checkpoint-replay recovery makes duplicate external actions *more* likely, not less | AR-028 |
| **GAP-044** | **`LearnedArtifact` type, promotion gate, rollback unit, and the non-learnable boundary** (policy/authorization/cost/Rulebook/SRs) | Versioning, rollback | Without this, learning is implemented as system-prompt accretion, which violates RB-020 continuously while appearing compliant | AR-022 |
| **GAP-045** | **`InterruptionBudget` and the prepare-vs-interrupt distinction** | Invariants | RB-005 and RB-006 point in opposite directions with no arbitration metric. Preparation is free; interruption must be budgeted | AR-025 |
| **GAP-046** | **Schema versioning and migration strategy** across events, memory, tasks, world model | Versioning, migration | Every contract carries `schema_version` and **nothing states what happens when it changes**. Migration retrofitted onto durable data is the classic unrecoverable cost | Foundation "Event backbone", IC-006 |

---

## F. Hidden assumptions the corpus does not acknowledge

Not gaps in the sense of missing decisions — assumptions currently baked in that no document flags.

| # | Assumption | Where it hides | Risk |
|---|---|---|---|
| 1 | **The portable modem is always available** | SR-016; 05 §5 | It is a single point of failure for the entire control plane. If the network is LAN-bound rather than an overlay, VESPER ceases to exist away from home — and the LAN-vs-overlay choice is deferred to unresolved ADR-012 |
| 2 | **"Free API" is a stable, well-defined category** | SR-001, SR-045, RB-016/017 | A free tier on an account with a payment method attached can bill on overage. Without a `metered_free_tier` distinction and a provable hard cap, the absolute rule leaks (GAP-039) |
| 3 | **Apple Silicon / Metal / unified memory** | Handwritten p3 → Arch §13 | Normative text names the product. If the machine becomes non-Apple, the acceleration path changes entirely and no accelerator adapter exists (GAP-037) |
| 4 | **The J3 can be both a trusted node and a 3D renderer** | SR-018 | Two incompatible architectures; the corpus never chooses, and enrollment has no admission criteria (GAP-016, AR-018) |
| 5 | **The iPhone can act as an "additive node"** | SR-015, SR-019 | iOS constrains background execution and local-network discovery in ways that narrow this to a foreground-only presence endpoint; no continuity path may depend on it (AR-034) |
| 6 | **Verification is affordable** | RB-004, P-009 | Roughly doubles inference per task; during FREE_TIME both roles are filled by weak local models. Never costed (SPIKE-002) |
| 7 | **The user is the only person in the environment** | SR-029, SR-040; world model | No `Person` type, no guest handling, no consent model (GAP-020, GAP-042) |
| 8 | **A single model family can review its own architecture** | 02 §16, 03 §8 | 03 §8 correctly requires cross-family verification — **including for this review** (see ADVERSARIAL_REVIEW §0.5) |

---

## G. Ordering constraint

The MUST-DEFINE entries are not independent. Enforced order:

```
GAP-003 (clock)  →  GAP-001, GAP-002 (delivery, ordering)  →  GAP-008 (supersession)
                                  ↓
                    GAP-004 (persistence)  →  GAP-009, GAP-010 (task FSM, checkpoints)
                                  ↓
                    GAP-005, GAP-006, GAP-007 (topology, ownership, partition)
                                  ↓
        GAP-011 → GAP-012 → GAP-014 → GAP-015 (authz chain; taint ceiling folds into the decision function)
                                  ↓
        GAP-020, GAP-021 (world model keying + space)  →  GAP-018 (scene)  →  GAP-019 (triggers)
```

**GAP-003 first.** It is one paragraph of decision and every freshness, ordering, and supersession rule depends on it. **GAP-018 and GAP-019 last among the blockers**, because both consume the world model — but both must still land **before Phase 3/F3 and Phase 8/F5 respectively**, not during them.

The three currently-deferred ADRs that must be reclassified as blocking are **ADR-001** (GAP-001/002), **ADR-002** (GAP-004), and **ADR-012** (GAP-005). **ADR-003** (model runtime abstraction) correctly stays deferred — the dependency-direction rule already protects it, and it is the one item on the Foundation's "Intentionally unresolved" list that genuinely belongs there.
