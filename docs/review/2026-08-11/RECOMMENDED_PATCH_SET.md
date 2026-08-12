# VESPER V0 — RECOMMENDED PATCH SET

**Review date:** 2026-08-11
**Scope:** Every P0 and P1 finding in `ADVERSARIAL_REVIEW.md`.

> **The COC is not modified by this document.** Patches touching COC v1.1 are **proposals requiring project-owner approval and a new source baseline version** per Part XIV §6. Patches touching the Engineering Foundation, the Engineering Baseline package, or new artifacts are normal engineering governance and may proceed under existing authority.
>
> No patch weakens, postpones, or reinterprets any SR. **PATCH-011 restores dropped source content and is therefore additive**, which is the only Part XIV-compliant treatment for an omission.

---

## Coverage map

| Patch | Findings closed | Severity | Authority required |
|---|---|---|---|
| PATCH-001 | AR-003 | P0 | Engineering (new ADR-001) |
| PATCH-002 | AR-002, AR-009 | P0 | Engineering (ADR-002, ADR-012) |
| PATCH-003 | AR-006, AR-007 | P0 | Engineering + owner sign-off on the ceiling policy |
| PATCH-004 | AR-004, AR-005 | P0 | Engineering; **COC clarification proposal** for Arch §24 |
| PATCH-005 | AR-001 | P0 | Engineering (new contract) |
| PATCH-006 | AR-008, AR-025 | P0 / P1 | Engineering |
| PATCH-007 | AR-019, AR-027 | P1 | Engineering + owner sign-off on privacy defaults |
| PATCH-008 | AR-014, AR-015, AR-016, AR-024 | P1 | Engineering |
| PATCH-009 | AR-017, AR-018, AR-034 | P1 | Engineering |
| PATCH-010 | AR-010, AR-036 | process-P0 / P3 | Engineering |
| PATCH-011 | AR-011, AR-029 | P1 | **Project owner — COC v1.2 additive baseline** |
| PATCH-012 | AR-012, AR-013 | P1 | **Project owner — COC v1.2 (Part XI, XV)** |
| PATCH-013 | AR-020, AR-021 | P1 | **Project owner** (deviation record); Engineering (capability class) |
| PATCH-014 | AR-022 | P1 | Engineering |
| PATCH-015 | AR-023 | P1 | Engineering + owner sets the numbers |
| PATCH-016 | AR-026, AR-028 | P1 | Engineering |
| PATCH-017 | AR-030, AR-031, AR-032, AR-033, AR-035 | P2 | Engineering |

All 29 P0/P1 findings are covered. P2/P3 findings are grouped into PATCH-017 and PATCH-010 for convenience.

---

## PATCH-001 — Coordination substrate: clock, ordering, delivery, supersession

| | |
|---|---|
| **Closes** | AR-003 (P0) |
| **Affected document** | New **ADR-001** (currently "Intentionally unresolved"); Engineering Foundation "Event backbone"; Baseline 04 §4, §6; COC IC-001 *(clarifying only — adds implementation obligation, changes no requirement)* |

**Problem.** VESPER is multi-node with designed intermittency and has no delivery guarantee, no ordering guarantee, no clock model, no supersession rule, and no conflict semantics. "Timestamps and confidence prevent stale observations becoming truth" is only sound if clocks agree.

**Exact proposed correction.** Insert into ADR-001 as the accepted decision:

```
DECISION
1. Clock. Every event carries a hybrid logical clock stamp
   hlc = (physical_ms, logical_counter, node_id).
   Wall-clock time is retained as `observed_at_wall` for user display
   and policy windows ONLY. It is never used for ordering or supersession.
2. Delivery. At-least-once. Every consumer MUST be idempotent on
   (event_id) or on a declared natural key.
3. Ordering. Total order per (source, subject). No cross-subject ordering
   guarantee is provided or may be assumed.
4. Supersession. A world-model fact is
   (subject, attribute, value, observed_at_hlc, valid_until,
    confidence, source, provenance).
   A write is REJECTED if observed_at_hlc <= the current fact's,
   regardless of arrival order.
5. Expiry. Every observation type declares a TTL. On expiry the fact
   becomes UNKNOWN. It never degrades to "last known value".
6. Conflict. Two non-superseded facts for the same (subject, attribute)
   from different sources within their validity windows constitute a
   conflict. The world model MUST emit `world.conflict` and MUST NOT
   select a winner silently.
```

**Architectural impact.** Fixes the shape of every event envelope, every world-model write path, and every consumer's idempotency obligation. Enables AR-002's partition handling and AR-004's period evaluation. Adds no distributed-systems machinery beyond HLC stamps and per-subject ordering — deliberately the cheapest model that satisfies the requirements.

**New invariant.**
> **INV-COORD-1:** No world-model fact may be applied out of HLC order. No expired fact may be read as current. No conflict may be resolved without an emitted `world.conflict` event.

**Verification.** Fault-injection suite: (a) skew a node ±120 s, assert world-model order unchanged; (b) replay a duplicated stream, assert idempotent state; (c) partition a node 2 h simulated, flush, assert no expired observation becomes current; (d) inject contradictory simultaneous observations, assert `world.conflict` with no silent winner.

---

## PATCH-002 — Control-plane topology, state ownership, and failover

| | |
|---|---|
| **Closes** | AR-002 (P0), AR-009 (P0) |
| **Affected document** | New **ADR-002** and **ADR-012**; Engineering Foundation "Intentionally unresolved" *(reclassification)*; Baseline 04 §14, §17; 05 §13 |

**Problem.** The COC's headline claim — identity and state survive device loss — has no mechanism. Four irreversible decisions sit on the critical path of Foundation increment #2 while being filed as deliberately deferred.

**Exact proposed correction.**

*(a) Amend the Foundation's "Intentionally unresolved" paragraph to read:*

```
Intentionally unresolved (DEFERRED-REVERSIBLE): model runtime abstraction,
concrete serialization library, and similar adapter-isolated choices. These
are protected by the dependency-direction rule and may be decided later on
evidence.

BLOCKING-IRREVERSIBLE (must be accepted before increment #2):
ADR-001 event transport, ADR-002 persistence engine, ADR-012 deployment
topology. These encode assumptions that every later increment inherits;
deferring them does not avoid a premature lock, it delegates the lock to
whoever implements first. Where evidence is required, run a time-boxed
spike (<= 1 week) whose deliverable is the ADR, not a prototype.
```

*(b) ADR-012 accepted decision:*

```
Single writable control plane with per-domain ownership leases and one
designated standby.

- State domains: tasks, world, memory, devices, policy, autonomy_queue,
  alarms. Each has exactly one lease holder at any instant.
- Lease TTL and renewal interval are configuration; expiry demotes the
  holder and emits `control.lease_lost`.
- Non-owner behavior per domain is declared: READ_CACHED (marked stale),
  QUEUE_WRITES, or REFUSE. Default REFUSE for policy and alarms.
- Promotion: automatic on clean lease expiry with quorum of reachable
  enrolled nodes; MANUAL where quorum is unavailable. Never automatic
  on partition alone.
- Partition: a disconnected node may execute already-authorized local
  work, MUST queue world/memory writes, MUST NOT issue external actions
  (L4+), MUST NOT self-promote.
- Rejoin: queued writes are applied under PATCH-001 supersession.
  Owner-wins for policy and devices; supersession-wins for world and
  memory; task state reconciles via the outbox (PATCH-016).

A leaderless replicated design is explicitly rejected as unjustified
complexity at this scale.
```

**Architectural impact.** Determines the persistence engine, the deployment shape, the device-trust model, and whether a modular monolith is viable (it is, per node, with the control plane as the leased layer). Unblocks Phases 1–5.

**New invariants.**
> **INV-OWN-1:** Every state domain has exactly one lease holder at any instant. A node without the lease may not write.
> **INV-OWN-2:** A partitioned node may not self-promote and may not issue L4+ external actions.
> **INV-ADR-1:** No PR touching `core/`, `tasks/`, or `memory/` may merge while ADR-001, ADR-002, or ADR-012 is not Accepted.

**Verification.** Extend A-017 to three parts: (i) clean departure → standby promotes, task resumes from checkpoint, alarm ownership transfers **exactly once**; (ii) partition with both sides live → assert no double external action, no divergent task state on rejoin; (iii) stale rejoin → assert lease rejection plus emitted degradation and reconciliation events. Add the INV-ADR-1 CI gate.

---

## PATCH-003 — Authorization decision function, delegation attenuation, and the injection ceiling

| | |
|---|---|
| **Closes** | AR-006 (P0), AR-007 (P0) |
| **Affected document** | Baseline 04 §10, §13; Engineering Foundation "Capability security"; new `contracts/authorization.schema.json`; COC Part VII *(clarification proposal — adds the evaluator, changes no level)* |

**Problem.** L0–L5 is a taxonomy with no evaluator, no grant representation, and no rule for what a spawned agent inherits. Separately, prompt-injection defense is asserted as a model disposition rather than an architectural control, in a system that browses the web unattended with shell access.

**Exact proposed correction.**

```
GRANT
  grant_id, subject (agent|task|node|user_session), capability_id,
  target_scope, max_level (L0..L5), expiry, delegable (default false),
  issued_by, issued_for_command_id (nullable)

DECISION FUNCTION
  effective_level = min(
      grant.max_level,
      capability.declared_level(args),   # argument-sensitive, per tool
      context_ceiling                    # from taint, below
  )
  Ambient authority does not exist. An agent that holds no grant may act
  at L0 only.

DELEGATION
  A spawned agent's grant set MUST be a subset of its parent's.
  `delegable` defaults to false.
  L4 and L5 grants are NEVER delegable and bind to exactly one
  command_id, one target, and one expiry.

TAINT
  Every context fragment carries
  trust_class in {system, owner, verified_local, retrieved_local,
                  retrieved_external, model_generated}
  Taint propagates through summarization, embedding, and cache reuse:
  a summary of tainted content is tainted.
  context_ceiling = min over fragments of allowed_level(trust_class)
  Binding: a context containing `retrieved_external` caps
  context_ceiling at L1 for state-changing capabilities.

ABOVE-CEILING BEHAVIOR
  An action above the ceiling is NOT silently dropped. It is converted to
  a queued proposal requiring owner confirmation, preserving SR-048/RB-014.

TWO-CONTEXT RESEARCH PATTERN (architectural, not optional)
  High-authority planner context never ingests raw external content.
  Low-authority extraction context ingests it and returns only
  schema-validated structured data.

AVAILABILITY
  The policy decision point is FAIL-CLOSED. If unreachable, every request
  above L1 is denied and audited. Break-glass is L5, time-boxed, audited.
```

**Architectural impact.** Changes the tool interface, the agent spawn path, the context assembler, and the cache. This is precisely why it is P0 — all four are written early.

**New invariants.**
> **INV-AUTH-1:** No ambient authority. Every action above L0 resolves to a grant.
> **INV-AUTH-2:** A child's grant set ⊆ parent's. L4/L5 never delegable and bind to one command instance.
> **INV-AUTH-3:** Taint propagates through summarization and caching. `retrieved_external` in context ⇒ ceiling L1 for state-changing capabilities.
> **INV-AUTH-4:** PDP unavailable ⇒ deny above L1.

**Verification.** Extend A-014; add **A-025 injection corpus** as a CI gate with fixtures covering webpage, PDF, OCR'd image text, filename, code comment, sub-agent output, and **a summary of an injected page** (the taint-propagation case). Assert per fixture: zero ≥L2 executions, correct ceiling, taint preserved through summarization and cache reuse, `security.injection_suspected` emitted. Add **A-024**: sub-agent cannot exceed parent grants; a consumed L4 grant cannot authorize a second action; PDP-down denies ≥L2.

---

## PATCH-004 — `OperatingPeriod` state machine and cost-class enforcement

| | |
|---|---|
| **Closes** | AR-004 (P0), AR-005 (P0) |
| **Affected document** | Baseline 04 §9, §12; Engineering Foundation "Model gateway"; new `policy/cost_policy.yaml`; **COC Arch §24 clarification proposal** |

**Problem.** An absolute prohibition (SR-045/RB-016/RB-017) is gated on an explicitly-untrusted inference and never defined as a predicate. Separately, Arch §24's fallback ladder has no cost-class filter and therefore routes free-tier exhaustion onto paid providers **by design**.

**Exact proposed correction.**

```
OperatingPeriod = {ACTIVE_SESSION, IDLE, FREE_TIME, DO_NOT_DISTURB}

TRANSITIONS
  Driven ONLY by: (1) user-configured schedule, (2) explicit user command,
  (3) ground-truth session activity = an authenticated interaction within
      the last N minutes.
  Mood/physiology/presence inference is NOT a transition driver.

FAIL-CLOSED ASYMMETRY (the invariant)
  Inference MAY cause ENTRY into FREE_TIME.
  Inference MAY NEVER cause EXIT from FREE_TIME.
  Only a schedule boundary or an authenticated user interaction exits it.

  Rationale: over-restriction is recoverable (the user speaks);
  under-restriction is not (money is already spent).

COST CLASS
  cost_class in {free, metered_free_tier, paid} is a MANDATORY,
  non-nullable field on every credential and every model profile,
  resolved at registration.
  `metered_free_tier` is treated as `paid` unless a hard spend cap
  is provable.

FILTERED FALLBACK LADDER (replaces the unfiltered Arch §24 ladder)
  classify -> retry/backoff
           -> alternate provider/model  [SKIP if cost_class not permitted]
           -> local fallback
           -> queue / pause / degrade / stop   (NOT escalate-to-paid)
  Enforcement lives at a SINGLE choke point inside the model gateway.
  No caller may reach an adapter without traversing it.

ON EXHAUSTION under a restrictive policy
  Emit `autonomy.blocked_on_cost_policy`; checkpoint; queue.
  Do NOT wake the user for ordinary work (SR-042).
```

*COC clarification proposal (owner approval required), to be recorded as an ADR resolving the SR-003 / SR-045 tension:*
> *During FREE_TIME, SR-003's "retry without stopping" is satisfied by continuing within the free/local subset and by queueing rather than terminating when that subset is exhausted. Both SRs stand unmodified.*

**Architectural impact.** Adds a period evaluator to the control plane and a mandatory field plus choke point to the model gateway. Small surface, but it must exist before the router and autonomy engine are written.

**New invariants.**
> **INV-COST-1:** Zero paid-provider requests may leave the gateway while `OperatingPeriod = FREE_TIME`, under any inference input.
> **INV-COST-2:** Inference may enter FREE_TIME; it may never exit it.
> **INV-COST-3:** No code path reaches a provider adapter without traversing the cost-class choke point.

**Verification.** **A-021**: adversarial inference in both directions — assert no paid call in FREE_TIME; authenticated interaction exits within one cycle; inference alone never exits; current period and cause always retrievable. Extend **A-004**: revoke all free providers mid-task in FREE_TIME → assert gateway-level zero paid attempts (assertion, not log inspection), checkpointed pause, `autonomy.blocked_on_cost_policy` emitted, user not woken. Static test for INV-COST-3.

---

## PATCH-005 — `SemanticScene` contract

| | |
|---|---|
| **Closes** | AR-001 (P0) |
| **Affected document** | COC IC-005 *(implementation obligation — proposal)*; Baseline 04 §11; new `contracts/semantic_scene.schema.json`; Baseline 07 (add a Scene template) |

**Problem.** The artifact on which the entire "VESPER is not a chat UI" claim rests is one sentence. Without it, the first renderer defines a scene as `{markdown, speech}` and A-009 is satisfiable by rendering the same markdown twice.

**Exact proposed correction.** Author `contracts/semantic_scene.schema.json` with, at minimum:

```
SemanticScene {
  scene_id, schema_version, correlation_id, created_at_hlc,
  intent: {purpose, urgency, privacy_class, expected_dwell},
  elements: [ SceneElement ],
  update_mode: replace | patch | append | stream,
  lifetime: {ttl, persist_until_acked}
}

SceneElement {
  element_id,
  type: text | metric | table | code | diagram | image | timeline
      | entity_ref | state_indicator | live_binding,
  content,                       # typed per element type
  presentation_intent: {         # intent, NOT styling
    priority, persistence, ephemerality, privacy_class, attention_cost
  },
  spatial_intent: user_relative | space_anchored(SpaceRef)
                | surface_relative | unanchored,
  affordances: [declared capability, not an event handler]
}

EndpointCapability {
  endpoint_id, modalities, resolution_class, spatial_class,
  text_capacity, color, audio, interaction_classes, latency_class,
  privacy_class
}

RENDERER CONTRACT
  render(scene, endpoint_capability) ->
      { rendered: bool, degradations: [ {element_id, reason, action} ] }

  Every element type declares a degradation ladder per capability class.
  Degradation is ALWAYS reported, never silent (RB-022).
  The schema contains NO free-form markdown escape hatch.
```

**Architectural impact.** Defines the boundary between everything that produces user-visible output and everything that renders it. Also supplies the streaming update semantics required by PATCH-008's progressive-presence requirement.

**New invariants.**
> **INV-SCENE-1:** No output reaches a user except as a `SemanticScene`. No renderer may require a field outside the schema.
> **INV-SCENE-2:** Every dropped or degraded element is reported in `degradations`.

**Verification.** Contract test: one scene fixture → three renderers with **materially different capability descriptors** (2D, voice-only, spatial simulator) → all three produce output and an explicit degradation report. Strengthen **A-009** to require differing capability descriptors. Add **A-026**: assert every core capability is reachable without any text/chat surface enabled (this is the SR-046 test that currently does not exist). Negative test: assert no markdown-string escape hatch in the schema.

---

## PATCH-006 — `Trigger` registry and `InterruptionBudget`

| | |
|---|---|
| **Closes** | AR-008 (P0), AR-025 (P1) |
| **Affected document** | New **ADR-009**; Baseline 04 §12; Engineering Foundation "Agent runtime"; new `contracts/trigger.schema.json`; COC Arch §12 *(implementation obligation — proposal)* |

**Problem.** Part V §28 forbids "a cron job that runs isolated scripts" and Arch §4 forbids "asking an LLM to invent tasks" — the only two implementable options in the absence of a spec. Separately, RB-005 and RB-006 point in opposite directions with no arbitration metric.

**Exact proposed correction.**

```
Trigger {
  trigger_id, name, owner, enabled,
  predicate,                 # declarative expression over world-model facts,
                             # task-graph state, schedule, event patterns
  debounce, cooldown, priority,
  required_authority,        # max effective level actions may reach
  resource_budget, cost_policy, stop_conditions, reporting_policy,
  provenance                 # authored | promoted-from-proposal (PATCH-014)
}

EVALUATION
  Deterministic predicate evaluation over the world model.
  NOT a model call. The LLM enters AFTER a trigger fires, to plan HOW to
  satisfy an already-justified goal — never to decide WHETHER one exists.

STANDING GOALS
  Represented as long-lived triggers with re-evaluation conditions,
  not as recurring prompts.

PROPOSED TRIGGERS
  A model may PROPOSE a trigger. It may not BE one. Proposals enter the
  registry only through the PATCH-014 promotion gate.

InterruptionBudget {
  per OperatingPeriod and user-attention state:
    max_proactive_contacts_per_hour,
    modality_cost: {ambient_visual: low, visual_notice: med,
                    speech: high, alarm: exempt}
}

PROACTIVE DECISION
  Every proactive action declares
    (expected_value, decays: bool, interruption_cost, reversibility).
  Act now IFF value > cost AND decays.
  Otherwise QUEUE for the next natural interaction boundary.

PREPARE vs INTERRUPT
  RB-005's "prepared or executed safely" licenses UNLIMITED preparation.
  Preparation is free and is the default. Interruption is strictly
  budgeted. This distinction resolves most of the RB-005/RB-006 tension.
```

**Architectural impact.** Makes autonomy an engineered control system rather than a prompt. Required for RB-019 explainability and A-018 auditability, both of which need the trigger named.

**New invariants.**
> **INV-TRIG-1:** Every autonomous action traces to exactly one registered `trigger_id` whose predicate demonstrably evaluated true against a reconstructible world-model snapshot.
> **INV-TRIG-2:** No autonomous action originates from a model call not preceded by a trigger.
> **INV-TRIG-3:** Preparation is unbudgeted; interruption is budgeted; alarm class is exempt.

**Verification.** Extend **A-011** for INV-TRIG-1/2, including driving the world model into a firing state and asserting the trigger fires with **no model involvement in the decision**. New budget test: N proactive candidates → assert budget adherence, boundary queueing, high-value non-decaying items not dropped, alarm class bypasses.

---

## PATCH-007 — World-model keying, spatial representation, and perception privacy

| | |
|---|---|
| **Closes** | AR-019 (P1), AR-027 (P1) |
| **Affected document** | New **ADR-005**; Baseline 04 §6; 05 §9, §10; COC Arch §16 *(hardening proposal)*; new `contracts/world_model.schema.json` |

**Exact proposed correction.**

```
ENTITY KEYING
  Stable entity IDs. Evidence -> identity resolution is an explicit policy
  producing (entity_id, confidence, evidence_refs).

Person { person_id, role: owner | known | unknown_person, confidence }

  HARD INVARIANT: an unknown person is NEVER silently resolved to owner.

SPATIAL MODEL
  Topological room graph: Space nodes, adjacency edges, per-space
  privacy_class. Devices, displays, sensors are located in spaces.
  Metric coordinates are OPTIONAL future refinement and are not required
  by any V0 requirement.

PRESENCE ROUTING
  select_endpoint(scene.privacy_class, space.privacy_class,
                  observed_persons, user_location_confidence)
  FAIL-SAFE: if user_location_confidence < threshold OR an unknown person
  is present in the target space, route to the most private available
  surface or WITHHOLD. Never default to the most public surface.

SENSOR LIFECYCLE
  states: DISABLED -> ARMED -> ACTIVE -> PAUSED -> DISABLED
  A physical or OS-level guaranteed-off path MUST exist that software
  cannot override. An active-capture indicator is always visible.

RETENTION (defaults; owner-configurable)
  raw audio/video : NOT persisted beyond the processing window
  derived observations : persisted with TTL
  transcripts : persisted only on explicit user action
  OCR output : TTL; never persisted for unknown_person frames

INFERENCE SCOPE
  SR-029 physiological/mood inference runs for role=owner ONLY, is
  LOCAL-ONLY and non-exportable (replaces "local where practical"),
  and carries confidence + expiry per DR-011.

USER CONTROL
  A "what did you see/hear, and what is retained" inspection and deletion
  path is required (DR-023, RB-030).
```

**Architectural impact.** Makes presence routing, proximity selection, and SR-029/SR-040 implementable and socially usable. The topological choice deliberately avoids importing a localization stack no requirement demands.

**New invariants.**
> **INV-WORLD-1:** An unknown person is never resolved to the owner.
> **INV-PRIV-1:** Unknown person in the target space ⇒ private content is withheld or routed to the most private surface.
> **INV-PRIV-2:** Physiological/mood inference is owner-only, local-only, non-exportable.
> **INV-PRIV-3:** Raw media is not persisted beyond the processing window.

**Verification.** Extend **A-010** with a fixture matrix (privacy class × persons present × location confidence) asserting correct endpoint selection and the fail-safe direction. Extend **A-008**: unknown person in frame suppresses inference and OCR retention; physical off stops capture at source; deletion path removes derived artifacts, not just raw media.

---

## PATCH-008 — Evidence envelope, verification strategy, memory conflict, and latency budget

| | |
|---|---|
| **Closes** | AR-014 (P1), AR-015 (P1), AR-016 (P1), AR-024 (P1) |
| **Affected document** | Baseline 04 §7, §12; COC IC-006, IC-007 *(implementation obligations — proposal)*; new **ADR-010**; new `contracts/evidence.schema.json` |

**Problem.** "No guessing" is the most-repeated behavioral requirement and has no mechanism. The verifier is named six times and specified zero times. Memory conflict has no resolution order. And the SR-046 × SR-047 × RB-004 × SR-045 intersection has never been costed.

**Exact proposed correction.**

```
CLAIM-LEVEL EVIDENCE (grounding is tracked per claim, not per response)
  Claim { text, support: [source_ref | computation_ref | observation_ref],
          support_type: retrieved | computed | observed | model_prior,
          confidence }

OUTPUT GATE BY POLICY CLASS
  research | memory_write | world_fact | input_to_consequential_action:
      support_type = model_prior is NOT emittable as assertion.
      It must be marked, converted to an explicit question, or dropped.
  conversational | personality:
      gate relaxes; marking is still required.
  UNKNOWN is a first-class return value across BAG, world model, and
  memory. An empty result is NEVER coerced to a plausible answer.

VerificationStrategy (strength order; bound to task class)
  deterministic      (tests, schema validation, diff, exit code)
  retrieval_grounded (claims checked against cited sources)
  model_critic       (independent context; different model where available)
  human              (escalate)
  none_declared      (permitted ONLY for explicitly non-consequential
                      output, and RECORDED as such — never silently skipped)

  IC-007.verification_criteria becomes a typed union over these.

DISAGREEMENT
  Verifier failure => task is NOT complete (RB-004). Task enters BLOCKED
  with the disagreement preserved as evidence.
  PROHIBITED: re-running until the verifier agrees. This is the natural
  implementation and it silently destroys the control.

LATENCY-AWARE VERIFICATION (resolves the AR-024 intersection)
  Conversational: inline retrieval_grounded verification (cheap).
  model_critic runs ASYNCHRONOUSLY with post-hoc correction
    ("Correction — I checked that: it is 60 minutes, not 15").
  Honest post-hoc correction satisfies RB-004 and is MORE consistent
  with RB-001 than delayed perfection.
  Streaming/progressive presence is an ARCHITECTURAL requirement: first
  audio begins before generation completes.

MEMORY CONFLICT RESOLUTION (total order)
  1 system rules / policy
  2 authoritative source-of-record for that attribute (declared per
    attribute; e.g. the calendar owns meeting times)
  3 direct current observation within TTL
  4 explicit user statement
  5 derived / inferred
  6 model prior (never authoritative)

  When (2), (3) and (4) disagree, VESPER MUST surface the conflict and
  ASK. This is the RB-002-compliant outcome and is the specified default,
  not an implementation choice.
  Every correction writes `supersedes`; provenance survives.
  Retention/expiry is an actual background process with a test.
```

**Architectural impact.** Evidence tracking cannot be retrofitted into a generation pipeline — it is a rewrite, which is why this is filed at P1 rather than P2 despite being paper-resolvable. The async-verification decision is what allows SR-047 and RB-004 to coexist.

**New invariants.**
> **INV-EVID-1:** No `model_prior` claim is emitted as assertion in research, memory writes, world facts, or inputs to consequential actions.
> **INV-VERIF-1:** Verifier failure ⇒ `BLOCKED`, never `SUCCEEDED`. Retry-until-agreement is prohibited.
> **INV-MEM-1:** Three-way disagreement across authority tiers 2–4 produces a user-facing question, never a silent pick.

**Verification.** Replace **A-003**'s single case with a graded corpus (0% / partial / full evidence), including the adversarial "mostly grounded with one unsupported specific" case. Track unsupported-claim rate as a release metric. New **A-023**: subtly wrong output → verifier fails it → `BLOCKED` → disagreement recorded → no silent retry convergence. Memory fixture set per pairwise conflict class. **SPIKE-002** timed end-to-end test on the minimum profile, offline, in FREE_TIME, asserting per-stage budgets and first-audio latency independently of total completion.

---

## PATCH-009 — `NodeCapabilityProfile`, enrollment admission, and role separation

| | |
|---|---|
| **Closes** | AR-017 (P1), AR-018 (P1), AR-034 (P2) |
| **Affected document** | Baseline 05 §2, §3, §4; COC IC-004 *(implementation obligation)*; **COC Arch §13 editorial proposal**; new `contracts/node_profile.schema.json` |

**Exact proposed correction.**

```
NodeCapabilityProfile {
  node_id, schema_version,
  cpu_cores, ram_gb,
  accelerator: metal | cuda | rocm | vulkan | npu | none,
  accelerator_memory_gb,
  memory_architecture: unified | discrete,
  sustained_tokens_per_sec,      # MEASURED at enrollment, per model class
  thermal_class, power_source, storage_gb, network_class,
  os_family, security_baseline,
  always_on: bool, expected_availability,
  roles: [presence_endpoint | compute_node | sensor_node | control_candidate]
}

Every subsystem with a hardware dependency declares a MINIMUM PROFILE.
The router and resource governor select against MEASURED profiles,
never against node names.

An accelerator adapter contract makes the local-inference path
substitutable across metal/cuda/rocm/vulkan/cpu.

ENROLLMENT ADMISSION (the missing gate between ENROLLED and TRUSTED)
  Required: minimum security_baseline, required key storage,
  capability floor per granted role, re-attestation interval.

  New zone: `limited_trust` — for devices passing capability but failing
  the security baseline. They MAY render and observe. They MAY NOT hold
  state, issue commands, or receive secrets.

ROLE SEPARATION (resolves SR-018 without deferring it)
  J3    := presence_endpoint + a narrow, explicitly enumerated
           compute_node capability set, in `limited_trust`.
           This satisfies "its own assistant space and display stack"
           without granting control-plane trust.
  iPhone := presence_endpoint, FOREGROUND-ONLY, push-wake.
           No continuity-critical capability may be assigned solely to a
           foreground-only node.
```

*COC Arch §13 editorial proposal (owner approval; changes no requirement, removes a product name):*
> Replace *"On MacBook Neo, prefer models that fit comfortably in unified memory and avoid swap-heavy operation"* with *"On any node whose `memory_architecture = unified`, prefer models that fit within `accelerator_memory_gb` headroom and avoid swap-heavy operation."*

**Architectural impact.** Makes hardware agnosticism mechanical rather than aspirational, and makes the pending hardware purchase decidable against SR-005 via SPIKE-001.

**New invariants.**
> **INV-HW-1:** No routing or resource-policy code path references a product name.
> **INV-HW-2:** `sustained_tokens_per_sec` is measured at enrollment, never declared.
> **INV-TRUST-1:** A node in `limited_trust` may not hold state, issue commands, or receive secrets.

**Verification.** Enrollment benchmark populating measured fields. Boot the stack against three synthetic profiles (high/medium/minimum) asserting correct model selection and correct degradation reporting on minimum. Static check for INV-HW-1. Enrollment suite: baseline failure ⇒ `limited_trust`; role-scoped grants; re-attestation expiry demotes and emits degradation.

---

## PATCH-010 — Make the engineering operating model enforceable

| | |
|---|---|
| **Closes** | AR-010 (process-P0), AR-036 (P3) |
| **Affected document** | New repository artifacts; COC Part XIII *(add `contracts/` — proposal)*; Baseline 01, 02 |

**Problem.** Every enforcement point named in 01 §5/§6/§8/§9/§10 and 02 §16/§18 lacks its artifact. With multiple agents writing concurrently, unenforced norms are not controls — and nothing currently prevents undetected modification of the immutable SR layer.

**Exact proposed correction. Do this in week 0, before the first implementation task.**

1. Initialize the repository with the Part XIII layout **plus `contracts/`** (JSON Schema per IC-001…IC-010 and per event type) and `docs/ADR/`.
2. Protect `main`: required review, required status checks, no force-push, no direct pushes.
3. `CODEOWNERS` mapping each subsystem to its single accountable owner from Baseline 02 §2–§14. **`docs/COC/` and `contracts/` are owned by the project owner alone.**
4. CI checks that mechanize the prose:
   - `schema-change-requires-adr` — any diff under `contracts/` without a referenced Accepted ADR fails.
   - `pr-declares-source-ids` — every PR names ≥1 SR that resolves to a real ID.
   - `traceability-lint` — fails when an SR loses its architecture / contract / test mapping; fails on unreferenced architecture sections or DRs (PATCH-012).
   - `source-immutability` — **fails any diff touching the SR registry without an owner-approved baseline-version bump.**
   - `adr-gate` — INV-ADR-1 from PATCH-002.
   - `declared-write-scope` — a PR's changed paths must be a subset of its task envelope's declared scope.
5. Machine-readable agent task envelopes (Foundation's `TASK_ID … STOP_CONDITIONS`) with declared write scopes.
6. Record in Baseline 02 §16: *a model reviewing another instance of the same model family does not satisfy separation of duties. Security-boundary and contract changes require cross-family or human review (consistent with 03 §8).*

**Architectural impact.** None on the runtime. Total on the project's ability to detect drift.

**New invariants.**
> **INV-PROC-1:** The SR registry cannot change without an owner-approved baseline bump — enforced in CI, not by convention.
> **INV-PROC-2:** A contract change without an Accepted ADR cannot merge.
> **INV-PROC-3:** No agent's merged diff falls outside its declared write scope.

**Verification.** **Self-test the gates before use.** Submit (a) a deliberate SR edit, (b) a schema change without an ADR, (c) a PR writing outside its declared scope. All three must fail CI. Until they do, the operating model is documentation.

---

## PATCH-011 — Restore dropped handwritten source content *(COC v1.2 — owner approval required)*

| | |
|---|---|
| **Closes** | AR-011 (P1), AR-029 (P1) |
| **Affected document** | **COC Part II** — additive only |

**Problem.** At least eight handwritten requirement clauses in Part I have no SR ID in Part II. Under P-001 and RB-036 this is prohibited, and because Part XIV makes SRs immutable, the omission is permanent until an owner-approved baseline change. The omissions are concentrated in the engineering-load-bearing material.

**Exact proposed correction.** Issue **COC v1.2** as an **additive restoration**. Adding a dropped source requirement restores rather than weakens the source, and is the only Part XIV-compliant treatment for an omission. Proposed new SRs:

| New SR | Restores (Part I) | Binding content |
|---|---|---|
| **SR-052** | p3 "BAG: instead of RAG … NO GUESSING" | Retrieval must be **source-grounded and exact, not similarity-guessing**. Invariant: *no answer may cite a source it did not retrieve verbatim; a similarity score is never sufficient grounding.* This is what makes "BAG not RAG" enforceable rather than a class name |
| **SR-053** | p3 prompt compression / memory summaries | Summary memory of facts, decisions, rules, open tasks, next actions, plans; **items the user says to remember are recorded immediately** |
| **SR-054** | p3 cache tiers | File-hash, chunk, embedding, summary, and prompt-prefix caches where the runtime supports them |
| **SR-055** | p3 multi-step reasoning | classify → retrieve → plan → generate → self-check → output, as a named pipeline distinct from SR-013 |
| **SR-056** | p3 speculative decoding | Draft-model proposal + verification where runtime support justifies it. Status may be `R&D` |
| **SR-057** | p3 MacBook-specific constraints | Accelerated local inference; models fit within memory headroom; avoid swap; smaller models for background work; not many models loaded at once; **forced closure of user apps requires asking**. Expressed as a capability profile constraint per PATCH-009, not as a product name |
| **SR-058** | p4 node availability | J3 always at home, occasionally offline; desktop usually connected, occasionally disconnected; iPhone last-resort. **These are the partition-tolerance requirements** whose loss is why AR-003 was never confronted |

Additionally, extend the SR status vocabulary with **`EXCLUDED_BY_SAFETY_POLICY`** and **`NARROWED_BY_OWNER_APPROVAL`**, and register the p6 excluded item (AR-029) and the SR-039 narrowing (PATCH-013) with rationale, approver, and date. This strengthens immutability discipline: every handwritten clause gets exactly one ID and one recorded disposition, so no future reader can mistake an omission for a decision or a decision for an oversight.

**Architectural impact.** SR-052 constrains the knowledge plane. SR-057 constrains the resource governor. **SR-058 is the one with real teeth** — it makes partition tolerance a source requirement rather than an inferred one, which is what forces PATCH-001 and PATCH-002 to be taken seriously.

**New invariant.**
> **INV-SRC-1:** Every bulleted requirement clause in Part I maps to exactly one SR ID or one recorded exclusion/narrowing.

**Verification.** Completeness lint (CI): parse Part I, extract clauses, assert each maps to an SR or a recorded disposition.

---

## PATCH-012 — Rebuild traceability and correct the release-gate record *(COC v1.2 — owner approval required)*

| | |
|---|---|
| **Closes** | AR-012 (P1), AR-013 (P1) |
| **Affected document** | **COC Part XI, Part X, Part XV** |

**Problem.** Part XI is a generated bundle-join: 9 of 28 architecture sections unreferenced (including §3 Persistent Runtime and §4 the core control loop), 1 of 31 DRs referenced, 51/51 verification cells identical placeholders, §1 used as a fallback bucket. Part XV then records "Source-to-architecture traceability present: **PASS**" and "Release decision: **CLOSED**". The lock was granted on evidence that does not hold.

**Exact proposed correction.**
1. Replace Part XI with a hand-verified matrix — one row per SR, columns: architecture section(s), DR(s), contract (IC-xxx), owning module, **named acceptance test ID**, status, evidence. The independent audit in `COC_TRACEABILITY_MATRIX.md` is offered as the starting point.
2. Add an explicit `SR → A-ID` mapping to Part X. Add the missing tests identified across this review: **A-021** free-time predicate, **A-022** difficulty-based routing (SR-009), **A-023** verifier disagreement (SR-013), **A-024** delegation attenuation, **A-025** injection corpus, **A-026** no-chat-required (SR-046), **A-027** artifact generation with provenance (SR-023/033/034), **A-028** media evidence pipeline (SR-024). Mark SR-037 explicitly `R&D`.
3. Amend Part XV to record the corrected audit result in place of the original PASS lines, retaining the original text with a dated correction note. Part XV asserts a completed audit, so its correction is an owner-level action.

**Architectural impact.** None on the runtime. Restores the ability of the release gate to mean anything.

**New invariant.**
> **INV-TRACE-1:** Every SR names ≥1 architecture section, ≥1 contract, and ≥1 acceptance test ID, or carries status `R&D` / `EXCLUDED`. Every A-ID names ≥1 SR. Every architecture section and every DR is referenced by ≥1 SR or explicitly marked non-requirement-bearing.

**Verification.** `traceability-lint` in CI (PATCH-010), failing on either orphan direction. Publish SR coverage counts per release per Part XIV §7.

---

## PATCH-013 — Apply Part XIV §3 to SR-026, and add the owner-administrative capability class

| | |
|---|---|
| **Closes** | AR-020 (P1), AR-021 (P1) |
| **Affected document** | New limitation records; COC Part VII *(new capability class — proposal)*; Baseline 04 §13; RB-013 *(scoping clarification — proposal)* |

**Problem.** (a) SR-026's "read kernel" was silently dropped from its own interpretation, and Part XIV §3's procedure — which the corpus correctly applied to SR-037 — was not applied. (b) SR-039 was narrowed by RB-013 without a recorded deviation, and no capability class exists for legitimate owner-directed privileged action, making SR-039 unimplementable.

**Exact proposed correction.**

*(a) SR-026.* Split the treatment. The telemetry half is core and buildable now. The kernel-access half becomes a **recorded limitation with an R&D path and a per-platform feasibility matrix** (SPIKE-003), following the DR-031 pattern the corpus already knows how to apply. **The SR is not narrowed.** Status becomes `PARTIAL + R&D`, published in release notes per Part XIV §7 — never `IMPLEMENTED`. Confirm with the project owner what "read kernel" is *for*: deep resource telemetry and security/intrusion monitoring (SR-038) have very different feasible implementations, and the answer determines whether a supported non-privileged path exists.

*(b) SR-039.* Two actions:

1. Record the narrowing as an explicit, owner-approved deviation in the same register as the safety exclusion (PATCH-011). This restores traceability without changing the safety posture.
2. Add an **L5 `owner_administrative`** capability class:

```
L5 owner_administrative
  Privileged operations on ENROLLED, OWNER-ATTESTED assets.
  Requires explicit per-instance owner confirmation with the risk and
  reversibility explained FIRST — which is precisely the source's own
  "should always explain and ask first".
  Fully audited. Checkpointed where reversible.
  NOT delegable to a sub-agent (INV-AUTH-2).
  NOT invocable during FREE_TIME.
```

3. Scope RB-013 explicitly (proposal): *RB-013 prohibits defeating authentication, authorization, encryption, or access controls on **third-party or non-owned systems**, and prohibits circumventing VESPER's own security model. It does not prohibit owner-authorized administrative operations on the owner's own enrolled hardware, which are governed by the `owner_administrative` class.* The distinction that resolves this cleanly: **whose** control is being bypassed, and **who** authorized it.

**Architectural impact.** Makes SR-039 implementable and keeps RB-013's actual protective intent intact. Puts SR-026 on an honest footing so it cannot be marked done on the strength of a CPU monitor.

**New invariants.**
> **INV-ADMIN-1:** `owner_administrative` requires per-instance owner confirmation, is never delegable, and is never invocable during FREE_TIME.
> **INV-LIMIT-1:** Any SR judged infeasible carries a limitation record and an R&D path per Part XIV §3, and may never be marked IMPLEMENTED.

**Verification.** Assert `owner_administrative` per-instance confirmation, non-delegability, and FREE_TIME denial. Targeted negative tests asserting RB-013 still blocks non-owned and self-directed cases. SPIKE-003 feasibility matrix reviewed at the Phase 6 gate.

---

## PATCH-014 — Learning promotion pipeline and the non-learnable boundary

| | |
|---|---|
| **Closes** | AR-022 (P1) |
| **Affected document** | New **ADR-011**, **ADR-014**; Baseline 04; Engineering Foundation "Prohibited" list; COC Arch §21 *(implementation obligation — proposal)* |

**Exact proposed correction.**

```
LearnedArtifact {
  artifact_id, type: routing_hint | procedure | retrieval_strategy
                   | context_policy | tool_preference | trigger_proposal,
  content, provenance (which outcomes produced it), scope, expiry,
  version, status: proposed | active | retired
}

PROMOTION GATE
  Nothing enters the active set without passing a held-out regression
  suite scoring the candidate against the current baseline.
  Net-negative candidates are rejected AUTOMATICALLY.

NON-LEARNABLE BOUNDARY (hard)
  Security policy, authorization levels, cost policy, the Rulebook, and
  the SR layer are NOT learnable under any score. They change only through
  owner-approved change control (Part XIV).
  Learnable artifacts live in a SEPARATE, clearly-bounded store, enforced
  on the write path.

ROLLBACK
  Unit = the individual artifact. Plus a kill switch reverting the entire
  active set to a known-good version.

DRIFT DETECTION
  The regression suite runs on a SCHEDULE, not only at promotion, so
  accumulated degradation across many individually-accepted changes
  surfaces.

PROHIBITED PATTERN (add to the Foundation's Prohibited list, alongside
"hidden global state")
  System-prompt accretion as a learning mechanism. It defeats versioning,
  rollback, and attribution simultaneously.
```

**Architectural impact.** Makes SR-027/SR-048 satisfiable without violating RB-020, and supplies the promotion path that PATCH-006's proposed triggers require.

**New invariants.**
> **INV-LEARN-1:** No learned artifact may modify policy, authorization, cost rules, or the Rulebook — enforced structurally on the store's write path, not by inspection.
> **INV-LEARN-2:** A single outcome cannot alter the active set.
> **INV-LEARN-3:** Every active artifact is individually rollback-able and the whole set is revertible.

**Verification.** Extend **A-016** materially: single bad outcome does not alter the active set; a candidate failing the gate is rejected and recorded; the kill switch restores prior behavior **measurably**; the structural write-path test for INV-LEARN-1.

---

## PATCH-015 — Requirement-derived latency budgets

| | |
|---|---|
| **Closes** | AR-023 (P1) |
| **Affected document** | Baseline "Performance" sections; DR-018 *(implementation obligation)*; new `policy/latency_budgets.yaml` |

**Problem.** The Foundation instructs converting **measured baselines into targets**. A target defined as whatever was measured can never fail, and SR-047 has no quantification anywhere.

**Exact proposed correction.** Set budgets **before** measurement, derived from interaction-design constraints. The specific numbers are the owner's call; the **rule** is that they are requirements and the implementation is judged against them:

```
wake_word -> first audible response        <= 800 ms
end_of_speech -> response onset            <= 1200 ms (routine requests)
scene update -> visible                    <= 300 ms
barge-in interrupt honored                 <= 200 ms
tool invocation -> result acknowledged     <= 500 ms
checkpoint write                           <= 200 ms
node failover -> task resumed              <= 30 s
```

Measurement then produces a **gap analysis**, never a retarget. Where a budget is unmeetable on the minimum hardware profile, record a Part XIV §3 limitation with an R&D path — **do not relax the budget**.

**Architectural impact.** Converts SR-047 from `UNVERIFIABLE` to verifiable, and gives SPIKE-002 a pass/fail criterion.

**New invariant.**
> **INV-PERF-1:** Latency budgets are requirements set before measurement. A budget may not be modified in the same change as the code that failed it.

**Verification.** **A-020** asserts measured latency against declared budgets, wired as a CI performance gate failing on regression past budget. Add the same-change-modification test for INV-PERF-1.

---

## PATCH-016 — Alarm priority/ownership and the external-action outbox

| | |
|---|---|
| **Closes** | AR-026 (P1), AR-028 (P1) |
| **Affected document** | Baseline 04 §4, §10; COC IC-003 *(field change — proposal)*; Arch §15 *(hardening proposal)*; new runbook |

**Exact proposed correction.**

```
PRIORITY LATTICE (stated as a rule, not left to implementers)
  alarm/safety  >  active user task  >  ambience  >  proactive
  Alarm class overrides RB-034 ambience policy, RB-015 resource yielding,
  RB-006 proportionality, and device-level quiet-hours.

ALARM OWNERSHIP
  Alarms are replicated to every capable node with lease-based
  single-firer election.
  FAILURE DIRECTION IS SPECIFIED: on partition, FIRE. A duplicate alarm is
  far safer than a missed one. Never fire-never.

ACKNOWLEDGMENT
  Multi-channel. At least one channel MUST be physical and require no ASR
  (hardware button, phone unlock, specific device interaction).

CEILING
  Maximum escalation level, duration cap with auto-stop, and a documented
  physical kill (which device, which action) tested at Phase 8 and written
  into a runbook. Every escalation step is logged for user review.

TRANSACTIONAL OUTBOX (external side effects)
  Intent is durably recorded with an idempotency_key BEFORE the call.
  Result is recorded after. Recovery reads the OUTBOX, never replays the
  task.

RECONCILIATION PROBE
  Every external tool declares a read-only probe answering "did this
  happen?" (search sent items by key, query call history, look up the
  created event). Reconciliation runs BEFORE any retry.
  Where no probe is possible the tool declares `reconcilable: false` and
  MUST escalate to the user rather than retry. This is the case that
  silently produces duplicates and must be handled by declaration.

IC-003 FIELD CHANGE (proposal)
  Replace the single `rollback/compensation` field with
    reversibility: reversible | compensable | irreversible
  `irreversible` implies L4+ and pre-commit confirmation binding
  (INV-AUTH-2).

  Bind SR-031/DR-025 delegated-identity attribution to the outbox record
  so A-018 auditability is satisfiable.
```

**Architectural impact.** Discharges the obligation created by the corpus's own excellent principle that "a command is never proof that an action happened," and makes checkpoint-replay recovery safe for external effects — currently it makes duplicates *more* likely, not less.

**New invariants.**
> **INV-ALARM-1:** An alarm has exactly one firer per instant; on partition the failure direction is fire, not skip.
> **INV-ALARM-2:** At least one acknowledgment channel is physical and ASR-independent; escalation has a hard duration cap.
> **INV-EXT-1:** No external side effect occurs without a prior durable outbox record.
> **INV-EXT-2:** No retry of an external action occurs without a successful reconciliation probe; `reconcilable: false` escalates instead.

**Verification.** Extend **A-012**: fire with the owning node removed; assert each acknowledgment channel independently including with ASR fully disabled; assert the duration cap terminates escalation; assert override of an active quiet-hours policy. Crash-injection during external tool execution: assert exactly-once effective delivery via reconciliation, assert `reconcilable: false` escalates, assert the audit chain reconstructs trigger → authority → command → outbox → probe → result.

---

## PATCH-017 — P2 consolidation

| | |
|---|---|
| **Closes** | AR-030, AR-031, AR-032, AR-033, AR-035 (all P2) |
| **Affected document** | Baseline 00, 06; Foundation roadmap; IC-002; Arch §13, §25; new `policy/cost_policy.yaml` |

| Item | Correction |
|---|---|
| **AR-030** Conflicting roadmaps | Declare precedence in `00_ENGINEERING_INDEX`: Foundation governs architecture, Baseline governs process. Merge F0–F8 and Phase 0–10 into one sequence. Resolve the ordering deliberately: **perception before presence**, since presence routing consumes world-model facts only perception produces. Resolve the B01–B08 benchmark ID collision between the two packages |
| **AR-031** Provider gateway | Error taxonomy as a versioned enum in IC-002 with a declared policy per class; local per-credential quota tracking with rolling windows and pessimistic 429 backoff; mid-stream failure specified per modality — for voice, the spoken prefix is committed and continuation is **semantically resumable** (the replacement model receives the prefix as context), never silently restarted; a defined merge rule for partially-rendered scenes across a model switch |
| **AR-032** Governor oscillation | Specify the governor as a **damped controller**: minimum dwell per level, asymmetric thresholds (degrade fast, recover slow), explicit hysteresis band, max transitions/hour triggering an alert rather than another transition. Model-visible telemetry is **advisory input to a deterministic governor**, not a direct actuator — the model may request, the governor decides |
| **AR-033** No cost policy artifact | Author `policy/cost_policy.yaml`: permitted cost classes per `OperatingPeriod`, per-task and per-day ceilings, alert threshold, hard stop, mid-task ceiling escalation path. Version it under owner-only change control alongside security policy — it is explicitly **not learnable** (INV-LEARN-1). Gateway **fails closed** when no cost policy is loaded |
| **AR-035** Observability | Retention per event class; the `sensitivity` field **enforced by the telemetry writer** (redaction/exclusion at write time, not by convention); perception payloads classified sensitive by default with references stored rather than content; a purge path satisfying PATCH-007's deletion requirement, with the correlation chain surviving purge |

**Verification.** Roadmap: single document referenced by the index plus a precedence statement. Gateway: extend **A-004** with mid-stream provider kill during streamed voice — assert no audible repetition and continuity. Governor: drive synthetic oscillation, assert transitions stay under cap and dwell-violating model requests are rejected. Cost: assert fail-closed with no policy loaded; assert ceilings halt and report. Telemetry: inject a secret and a synthetic PII payload into a traced flow, assert neither appears in the store; assert purge removes derived records while the correlation chain survives.

---

## Execution order

```
Week 0    PATCH-010  repository + CI + immutability gate   (protects everything after)
Week 0-1  PATCH-001  clock / ordering / delivery / supersession   [ADR-001]
          PATCH-002  topology / ownership / failover             [ADR-002, ADR-012]
          launch SPIKE-001 (hardware, informs the purchase) and SPIKE-002 (latency)
Week 1-2  PATCH-003  authorization + injection ceiling
          PATCH-004  OperatingPeriod + cost class
          PATCH-009  NodeCapabilityProfile + enrollment
Week 2    PATCH-007  world keying + spatial + privacy
          PATCH-005  SemanticScene            (consumes the world model)
          PATCH-006  Trigger + InterruptionBudget  (consumes the world model)
          PATCH-008  evidence / verification / memory conflict / latency
Week 2    PATCH-011, PATCH-012, PATCH-013   -> project owner, COC v1.2
Then      PATCH-014, PATCH-015, PATCH-016, PATCH-017 land with their subsystems
          Begin Foundation increment #1
```

**PATCH-001 first.** It is one paragraph of decision and every freshness, ordering, and supersession rule depends on it. **PATCH-005 and PATCH-006 last among the blockers**, because both consume the world model — but both must land before Phase 3/F3 and Phase 8/F5 respectively, not during them.

Approximately two weeks of decision work, against a project whose rework exposure if skipped is the entire foundation.
