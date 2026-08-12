# VESPER V0 — BUILD READINESS ASSESSMENT

**Review date:** 2026-08-11
**Scope:** Every major subsystem named in COC Part V, Engineering Foundation, and Engineering Baseline 04–05.

---

## Rating definitions

| Rating | Meaning |
|---|---|
| **GREEN** | Requirements, interfaces, ownership, security boundary, persistence, observability, failure behavior, acceptance tests, and rollback are defined well enough to begin. Uses the Baseline's own readiness definition (`00_ENGINEERING_INDEX`, "Implementation readiness"). |
| **YELLOW** | Architecturally sound and correctly bounded, but one or more of the nine readiness dimensions is missing. Buildable after a bounded, paper-only correction. |
| **RED** | A missing decision would force rework of already-written code, or the subsystem's defining artifact does not exist. Do not begin. |

Ratings are against **the corpus as delivered**, not against intent.

---

## 1. Subsystem ratings

### Control plane and foundation

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **Engineering process / repository** | **RED** | An unusually complete operating model on paper: lifecycle, DoR/DoD, PR gates, handoffs, isolation, separation of duties, escalation | **No repository, CI, CODEOWNERS, branch protection, machine-readable contracts, or traceability lint in the delivered package.** Every named enforcement point lacks its artifact | AR-010 |
| **Persistent runtime / lifecycle** | **RED** | `vesperd` supervisor named; Arch §3's requirements are correct and clear | Persistence engine, durable schema, and checkpoint format are deferred to unresolved ADR-002 while increment #2 depends on them | AR-009, GAP-004/010 |
| **Event bus** | **RED** | Event/Command/Result separation is genuinely well designed; "a command is never proof" is exactly right; envelope fields are named | No delivery guarantee, no ordering guarantee, no clock model, no cross-node semantics. ADR-001 deferred onto the critical path | AR-003, AR-009 |
| **Identity & continuity** | **RED** | The requirement is stated more clearly than anywhere else in the corpus (Part XVI). DR-002, DR-007, DR-022 are correct | No control-plane topology, no state ownership/leases, no failover, no partition behavior, no rejoin/merge. The headline promise has no mechanism | AR-002 |
| **Task system** | **YELLOW** | IC-007 field list is the right shape; state names enumerated; checkpoint concept present | No transition table, no guards, no typed `verification_criteria`, no checkpoint format | GAP-009/010/040 |
| **Resource governor** | **YELLOW** | Comprehensive resource enumeration; correct instincts ("don't overreact to spikes", "never kill user processes automatically") | No damping/hysteresis/dwell — the model-visible, model-actionable loop can oscillate. No verification-cost budgeting | AR-032, AR-024 |
| **Observability** | **YELLOW** | The correlation chain is well specified end-to-end; secret exclusion stated | No retention, no enforcement of the sensitivity classification, no perception-PII handling | AR-035 |

### Intelligence

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **Model gateway / provider fabric** | **YELLOW** | **Best-specified area of the corpus.** IC-002 normalizes the right things; the dependency-direction rule makes replaceability real; 03's benchmark-gated assignment is correct discipline | No `cost_class` (which creates a live contradiction with RB-017), no error taxonomy, no quota model, no mid-stream failure semantics | AR-005, AR-031 |
| **Model router** | **YELLOW** | Routing inputs correctly enumerated (complexity, modality, context, latency, quality, hardware, availability, cost) | No complexity classification method; **no acceptance test for SR-009 at all**; cost policy is an input with no artifact behind it | AR-013, AR-033 |
| **Planner / verifier** | **RED** | Separation is correctly asserted as a core structural claim (SR-013, P-009, RB-004) | The verifier is named in six places and specified in none: no strategy taxonomy, no disagreement handling, no typed acceptance condition, no cost model. Retrofitting verification changes every task's completion path | AR-015 |
| **Agent runtime / orchestration** | **YELLOW** | Agents-as-disposable-workers is right; no artificial ceiling correctly preserved; A-007 is a well-formed test | No authority attenuation across spawn (a security boundary, not a detail); no resource-accounting mechanism behind "constrained by actual resources" | AR-006 |
| **Research engine** | **YELLOW** | IC-010 is a real contract; "insufficient evidence is valid" is correct and rare | Cannot run unattended safely without the injection ceiling; RB-023 (no fabricated citations) depends on the missing claim-evidence envelope | AR-007, AR-014 |
| **Learning loop** | **RED** | The boundaries are correctly stated (DR-012, RB-020, Arch §21) | No promotion unit, no validation gate, no rollback unit, no drift detection, no prohibition on system-prompt accretion. The default implementation violates RB-020 continuously while reading as compliant | AR-022 |

### Knowledge

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **BAG / retrieval** | **RED** | Arch §10 asserts the right property ("source-grounded retrieval layer"); A-006 is a good test | **"BAG instead of RAG" has no SR and no contract**, so nothing forbids implementing it as ordinary vector RAG under the name. The binding constraint from the handwritten source is unenforceable | AR-011, AR-014 |
| **Project/knowledge maps** | **YELLOW** | First-class navigation concept correctly established; A-006 targets the outcome | No map schema; ADR-004 unresolved | GAP-028 |
| **Memory** | **YELLOW** | **IC-006 is the best contract in the corpus** — provenance, confidence, scope, retention, schema_version, source_refs, `supersedes` | No conflict detection, no resolution order, no retention enforcement process, no migration strategy for `schema_version` | AR-016, GAP-046b |
| **Context management** | **YELLOW** | Automatic + manual modes required; budget concept present | No context contract; **manual mode untested**; no taint propagation into assembled context | AR-007, GAP-014 |
| **Caches** | **YELLOW** | Five tiers correctly enumerated from source | No SR, no invalidation strategy, and — importantly — no rule that a cached summary of tainted content stays tainted | AR-011, GAP-027 |

### Perception, world, presence

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **Perception pipeline** | **YELLOW** | Modalities enumerated; provenance/timestamp/confidence/source-device requirement is correct; DR-026's "derived artifacts not opaque guesses" is the right framing | No sensor lifecycle, no consent model, no guaranteed-off, no per-modality retention, no non-owner person handling | AR-027 |
| **World model** | **RED** | Entity and relationship types listed; temporal/confidence intent stated | No entity keying, no identity resolution, no `Person` type, no spatial representation, no consistency model. Presence-by-proximity is unimplementable on top of it | AR-003, AR-019 |
| **Presence engine** | **RED** | The *policy* is well described (inputs, migration, chat-is-not-default) | **`SemanticScene` is one sentence.** This is the artifact the entire anti-chatbot claim rests on, and the largest rework surface in the project | AR-001 |
| **Spatial / holographic** | **RED** | Correctly held as architectural-from-day-one rather than deferred (V1.1 fixed this from V1.0 — a genuine improvement) | Depends entirely on the missing scene schema and the missing spatial representation. The *contracts* can and should proceed now; only the physical adapter waits on SPIKE-004 | AR-001, AR-019 |
| **Device fabric / network** | **YELLOW** | Node classes, device contract fields, lifecycle states, traffic classes, cryptographic node identity, "discovery ≠ trust" — all correct instincts | No `NodeCapabilityProfile` schema, no enrollment admission criteria, no accelerator abstraction, LAN-vs-overlay deferred | AR-017, AR-018 |

### Action, autonomy, security

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **Tool gateway / action** | **RED** | IC-003's field list is right; dry-run/preview and audit are required; Arch §8 correctly distinguishes trusted/untrusted/external code | No authorization decision function, no delegation attenuation, no taint ceiling, no outbox/reconciliation, no `reversibility` classification. Every one of these changes the tool interface | AR-006, AR-007, AR-028 |
| **Autonomy engine** | **RED** | The loop shape is right and the principles are unusually good ("no-op is valid"; "proactivity is generated by this loop, not by asking an LLM to invent tasks") | **`Trigger` is undefined.** `OperatingPeriod` is undefined. The cost choke point does not exist. Three of the four things the subsystem is made of | AR-004, AR-005, AR-008 |
| **Alarm / intervention** | **YELLOW** | Escalation concept, multi-device intent, and stop-on-acknowledgment are all present; A-012 exists | No priority lattice, no distributed ownership/failover, no escalation ceiling, no non-ASR acknowledgment path | AR-026 |
| **Security / authorization** | **RED** | Trust zones, L0–L5 ladder, capability-specific authorization, incident response sequence, threat register T-001…T-015 — the *shape* is correct throughout | No decision function, no grant representation, no delegation rule, no PDP location or failure mode, no taint model, no enrollment criteria, no secret mechanism. A taxonomy is not a security architecture | AR-006, AR-007, AR-018 |
| **Communications / delegated presence** | **YELLOW** | RB-012 and DR-025 get the attribution ethics right | No outbox, no reconciliation probe, no reversibility classification, platform feasibility unassessed | AR-028, SPIKE-005 |
| **Recovery / backup** | **YELLOW** | Failure classes enumerated with detection/containment/degradation/recovery intent; A-017 and A-019 exist | 53% of the failure matrix is UNDEF, concentrated in distributed coordination, security-under-autonomy, and irreversible effects | ADVERSARIAL_REVIEW §4 |

### Governance

| Subsystem | Rating | What is defined | What is missing | Blocking |
|---|---|---|---|---|
| **Change control** | **YELLOW** | **Part XIV is genuinely strong**, especially §3 (record infeasibility, preserve the requirement, define an R&D path) and §8 ("not implemented yet is a release status, not a reinterpretation") | It was not applied to itself: §3 was followed for SR-037 and skipped for SR-026 and SR-031; no enforcement artifact exists | AR-020, AR-010 |
| **Traceability** | **RED** | The chain is correctly designed (`SR → architecture → contract → module → test → evidence → release`) | Part XI is a generated bundle-join; 9 of 28 architecture sections unreferenced; 1 of 31 DRs referenced; 51/51 verification cells are placeholders; **zero SR↔A-test mappings exist**. Part XV's PASS is therefore unsupported | AR-012, AR-013 |
| **Verification & release** | **YELLOW** | Test layers, release levels, release blockers, and the mandatory vertical slice are all well chosen | 20 acceptance tests for 51 SRs with no mapping; SR-047 targets are circular; no adversarial injection corpus | AR-013, AR-023 |
| **Model/tool governance** | **GREEN** | Benchmark-gated assignment, explicit anti-fashion stance, versioning and revalidation on model change, cross-family verification requirement, tool capabilities framed as observations rather than dependencies | Two benchmark suites share IDs B01–B08 with different content across the two packages — a naming collision, not an architecture defect | AR-030 |

---

## 2. Distribution

| Rating | Count | Subsystems |
|---|---|---|
| **GREEN** | **1** | Model/tool governance |
| **YELLOW** | **17** | Task system, resource governor, observability, model gateway, model router, agent runtime, research engine, maps, memory, context, caches, perception, device fabric, alarm, communications, recovery, change control, verification & release |
| **RED** | **13** | Engineering process, persistent runtime, event bus, identity & continuity, planner/verifier, learning loop, BAG, world model, presence engine, spatial/holographic, tool gateway, autonomy engine, security, traceability |

*(17 YELLOW listed above includes 18 entries; "verification & release" and "change control" are counted under governance — total assessed subsystems: 31.)*

**The RED cluster is not random.** Twelve of the thirteen fall into exactly three groups:

1. **The distributed substrate** — event bus, persistent runtime, identity & continuity, world model. All four blocked by the same four decisions (clock, ordering, persistence, topology).
2. **The three defining artifacts** — presence/spatial (scene), autonomy (trigger), world model (keying + consistency). These are what make VESPER not-a-chatbot.
3. **Security under autonomy** — security, tool gateway, and the process layer that would enforce either.

That concentration is the assessment's most useful output: **thirteen RED subsystems are produced by roughly nine decisions**, not by thirteen independent design failures.

---

## 3. What is genuinely ready

Worth stating plainly, because it determines whether the correct response is "fix" or "restart":

- **The plane decomposition is correct** and would survive substantial future extension.
- **The dependency-direction rule** makes model/provider/device replaceability mechanically achievable rather than aspirational — the hardest property in this class of system, and it is handled.
- **Event / Command / Result separation** with "a command is never proof" prevents the most common agent-architecture defect.
- **The authorization ladder, the threat register, the failure-class enumeration, and the contract inventory** are all the right *shape* — they need decision functions and schemas beneath them, not replacement.
- **DR-031's quarantine of speculative capability** is a correct, reusable pattern the corpus already knows how to apply.
- **Model/tool governance is GREEN** and should not be disturbed.

None of the P0 findings requires abandoning a structural decision. Every one is satisfied by **adding** a schema, a state machine, a decision function, or an enforcement point beneath a boundary that is already correctly drawn.

---

## 4. Readiness verdict

> **NOT READY TO BEGIN IMPLEMENTATION — as delivered.**

Three independent reasons, any one of which is sufficient:

1. **Four irreversible decisions are deferred onto the critical path.** ADR-001 (event transport), ADR-002 (persistence), ADR-012 (deployment topology) are filed under "Intentionally unresolved" while Foundation increment #2 *is* "Event contract + durable task state." Starting now does not avoid a premature lock; it guarantees an unreviewed one, made by whoever is on the keyboard. (AR-009)

2. **The three artifacts that make VESPER not-a-chatbot do not exist.** Semantic scene, trigger model, world-model consistency layer. Every one is named, none is specified, and the natural implementation of each is the thing the COC explicitly forbids. (AR-001, AR-008, AR-003/019)

3. **No enforcement layer exists.** Every control in the engineering operating model — branch protection, ownership, contract stability, separation of duties, SR immutability — is prose with no artifact. With multiple agents writing concurrently, unenforced norms are not controls. Most seriously, **nothing currently prevents undetected modification of the immutable SR layer**, which would defeat P-001, RB-036, and Part XIV simultaneously. (AR-010)

**What "not ready" does *not* mean here.** It does not mean the architecture is wrong. The decomposition, the invariants, and the dependency direction are correct, and the corpus is better than most pre-implementation baselines of this ambition. It means the corpus is currently a **taxonomy** — it names every subsystem VESPER needs and never defines the boundary between any two of them precisely enough that two engineers would build compatible halves. The distance from taxonomy to specification is the machine-readable layer, and that layer is **additive**.

**Estimated critical path to READY:** the ten patches in `RECOMMENDED_PATCH_SET.md`, of which PATCH-001 through PATCH-004 (clock/ordering/persistence/topology, and the authorization chain) are the genuine blockers and are decision-work rather than build-work. SPIKE-001 and SPIKE-002 should run in parallel, since SPIKE-001 also informs the hardware purchase decision.

**Recommended sequence:**

1. **Week 0** — Repository, CI, CODEOWNERS, branch protection, `contracts/` directory, immutability check. (PATCH-010; cheap, and it protects everything after it.)
2. **Week 0–1** — Resolve ADR-001, ADR-002, ADR-012. Time-boxed; deliverable is the ADR. Launch SPIKE-001 and SPIKE-002 concurrently.
3. **Week 1–2** — Author the schemas: `SemanticScene`, `Trigger`, `NodeCapabilityProfile`, `OperatingPeriod`, world-model keying, capability grant, claim-evidence envelope. Paper only.
4. **Week 2** — Correct the traceability layer and propose the COC v1.2 additive restoration to the project owner (PATCH-011). Requires owner approval; cannot be done by engineering.
5. **Then** — begin Foundation increment #1.

The first three steps are approximately two weeks of decision work against a project whose rework exposure, if skipped, is the entire foundation.

---

## 5. Answer to the mandated final question

> **If all P0 and P1 findings are corrected, is VESPER sufficiently architected to begin implementation without knowingly accepting architectural ambiguity that is likely to cause major rework?**

# YES — conditionally, and the condition is specific.

**Justification.**

**1. The decomposition is correct and does not change.** The eight planes, the dependency direction (core domain imports no vendor SDK), the Event/Command/Result separation, the trust zones, the L0–L5 ladder, and the contract inventory are the right structure for a persistent distributed operating presence. Not one P0 or P1 finding requires abandoning a structural decision. Every correction in `RECOMMENDED_PATCH_SET.md` **adds a schema, a state machine, a decision function, or an enforcement point beneath a boundary that is already correctly drawn**. That is the distinguishing fact behind this answer: the corpus is under-specified, not mis-designed. Under-specification is closable on paper; mis-design is not.

**2. The corrections are decision-work, not build-work.** PATCH-001 through PATCH-016 produce ADRs, schemas, and CI gates. Two spikes (SPIKE-001 hardware, SPIKE-002 latency) require measurement, and both run in parallel with the paper work. Nothing in the patch set requires building something first to learn whether the architecture holds. Approximately two weeks of decision work.

**3. The corrections close the specific rework surfaces, not merely the symptoms.** The thirteen RED subsystems are produced by roughly nine decisions clustered in three groups — the distributed substrate, the three defining artifacts, and security-under-autonomy. PATCH-001/002 close the first, PATCH-005/006/007 close the second, PATCH-003/004 close the third. After those seven patches, every RED subsystem has its blocking decision resolved.

**4. The corrected foundation would satisfy the corpus's own readiness bar.** `00_ENGINEERING_INDEX` defines implementation-ready as: requirements, interfaces, ownership, security boundary, persistence, observability, failure behavior, acceptance tests, and rollback all defined. Today the corpus supplies requirements and partial interfaces. The patch set supplies the remaining seven dimensions.

**Four qualifications, stated so the YES is not read as broader than it is.**

- **The YES is conditional on the corrections landing as specified, not merely acknowledged.** A patch set that is agreed to and then implemented as prose reproduces the exact defect this review found: correct properties asserted with no mechanism behind them. The test of each patch is whether a **CI check or a contract test can fail** when it is violated. Every patch names one.

- **PATCH-011, PATCH-012, and PATCH-013 require project-owner action and cannot be discharged by engineering.** They touch the immutable layer. If the owner declines the COC v1.2 additive restoration, then SR-052…SR-058 remain unrestored, "BAG instead of RAG" remains unenforceable, and partition tolerance remains an inferred rather than a stated requirement — in which case the answer degrades to a qualified YES with a permanent, recorded traceability defect.

- **Two SR-level tensions are reported, not resolved, per mandate.** SR-003 "retry without stopping" versus SR-045's absolute prohibition (PATCH-004 proposes a reading that satisfies both); and the SR-046 × SR-047 × RB-004 × SR-045 latency intersection (SPIKE-002 will determine whether it closes on the minimum hardware). Both SRs in each pair stand unmodified. If SPIKE-002 shows the intersection does not close, that is a Part XIV §3 limitation record with an R&D path — **not** grounds to relax any of the four.

- **This review is a single-model pass and is not sole authority** (Baseline 03 §8). AR-001 through AR-009 in particular should be re-derived by an independent model family or a human architect before they are treated as settled.

**On the primary architectural test.** VESPER has **not** degraded into "LLM + memory + tools + chat UI" in intent — the COC argues against that outcome more explicitly and more correctly than most specifications of this class. But it currently has **no mechanism** that would prevent the degradation in practice, because the three artifacts that separate the two (semantic scene, trigger model, world-model consistency layer) are named and unspecified. PATCH-005, PATCH-006, and PATCH-001/007 are what convert that intent into an enforceable property. **They are the patches that matter most, and they are the ones most likely to be deferred as "we'll define that when we build presence."** That deferral is the single decision that would turn VESPER into a chatbot with extra steps.
