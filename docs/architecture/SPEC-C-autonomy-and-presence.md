# SPEC-C — Autonomy and presence

Subsystems **12, 13, 14, 15, 16, 17, 18**. Index: [SPEC-00](SPEC-00-INDEX.md).

---

## SPEC-12 — Autonomy

**Purpose.** Turn a fired trigger into bounded, checkpointed, verifiable work. Autonomy is a **control system**, not a prompt loop.

| Field | Definition |
|---|---|
| **Responsibility** | Eligibility, planning dispatch, resource/tool/time budgets, checkpointing, stop conditions, reporting policy, proposal emission |
| **Boundaries — in** | *How* to satisfy an already-justified goal |
| **Boundaries — out** | *Whether* a goal exists (13 — and this boundary is the whole design). Actuation admission (23) |
| **Authority** | Bounded by `trigger.required_authority`, which **cannot be `L5`** — `L5` is the level at which the subject must be a human (`INV-SELF-3`) |
| **State owned** | `autonomy_queue` (leased), active autonomous tasks, budgets consumed |
| **Inputs** | Fired triggers, `OperatingPeriod`, cost policy, enable token, verification strategy availability |
| **Outputs** | Tasks into `SM-TASK`; `autonomy.blocked_on_cost_policy`; `change.proposal`; reports at the configured boundary |
| **Persistence** | Every autonomous unit checkpoints (RB-035). Work survives node change |
| **Lifecycle** | `DF-AUTONOMY-ELIGIBLE → plan → authorize → actuation gate → execute → verify → checkpoint → report` |
| **Invariants** | `INV-TRIG-1`, `INV-VERIF-2` (a `FREE_TIME` task with a non-machine-checkable acceptance condition is **ineligible** and queues), `INV-SELF-1`, `INV-SELF-7`, `INV-COST-1` |
| **Failure modes** | No free provider in `FREE_TIME` → checkpoint + queue, **user not woken**; no independent verifier → defer, `verified_by: deferred`; stop condition hit → `CANCELLED` with reason; governed write attempted → refused, converted to a **proposal**, work preserved |
| **Recovery** | Resume from checkpoint via `RESUMABLE`; the outbox cursor prevents repeated external effects |
| **Observability** | Trigger→action chain, budgets consumed, blocked reasons, proposals emitted |
| **Security** | Runs under the taint ceiling; overnight web work caps state-changing capabilities at `L1` |
| **Verification** | `A-011`, `A-029`, `A-030.6`, `A-021` |
| **Dependencies** | REM-004, REM-005, REM-006, REM-007, REM-008 |

> **Jarvis-divergence.** *No.* Clause: **`INV-SELF-7` combined with `INV-VERIF-2`** — the runtime may write a complete patch to `policy/`, test it and file a proposal at 03:00 with nobody present (`A-030.6` must **pass**), yet may not complete a task it cannot machine-check while unattended. Both behaviours require a system that exists, decides and defers between conversations.

---

## SPEC-13 — Trigger evaluation

**Purpose.** The deterministic layer that decides **whether** a goal exists. One of the four artifacts that separate VESPER from a chatbot.

| Field | Definition |
|---|---|
| **Responsibility** | Registry, predicate evaluation, debounce/cooldown, priority ordering, provenance, no-op recording |
| **Boundaries — in** | Predicate truth over world/task/schedule/event domains |
| **Boundaries — out** | Planning (12). **A model never enters this subsystem** |
| **Authority** | `L0`. The evaluation sandbox holds **no model capability at all** |
| **State owned** | Trigger registry (in `autonomy_queue`), cooldown state, last-evaluation snapshots |
| **Predicate language** | Total, side-effect-free, provably terminating, over four typed domains. `UNKNOWN` and `CONFLICTED` are **not falsy** — a predicate evaluating to either does not fire |
| **Evaluation** | Deterministic pass per tick **and** on change to any referenced subject. Change-driven evaluation is what makes `STATE` triggers responsive rather than polled |
| **Invariants** | `INV-TRIG-1`…`INV-TRIG-7`, `INV-AUTO-5` (the registry may not be exclusively `SCHEDULE`-class) |
| **Failure modes** | Predicate raises → **that trigger** disabled, incident recorded, others unaffected (isolation is mandatory); unknown subject → `UNKNOWN`, no fire; evaluator lag → degrade by priority; storm → priority order + per-tick fire cap with `autonomy.fire_cap_reached`, never silent truncation |
| **Recovery** | After failover the new owner **re-evaluates from current state and does not replay missed firings** — a predicate over current state is self-correcting. Elapsed `SCHEDULE` windows are reported as missed, never silently skipped |
| **Observability** | Per-trigger fire/no-fire counts with reasons; `autonomy.model_call_in_decision_path` if ever raised |
| **Security** | `autonomy/triggers/` is `GOVERNED_PATHS` surface 7 — a model may propose a trigger, never be one |
| **Verification** | `A-011.3`, `A-011.4`, `A-029` part 3 (with the C1 cron and C2 model-decides negative controls) |
| **Dependencies** | REM-007, 06 |

> **Jarvis-divergence.** *No — this is the decisive one.* Clause: **the evaluator runs in a sandbox with no model capability, and the violation is observable (`INV-TRIG-2`).** A chatbot-with-a-scheduler decides to act by calling a model; `A-011.4` detects that directly at runtime rather than by code review. The second clause is `INV-TRIG-4`: firing requires a *known* world fact, which presupposes a world model that can be `UNKNOWN`.

---

## SPEC-14 — Attention and interruption

**Purpose.** Arbitrate RB-005 (*don't wait for me*) against RB-006 (*don't act merely because you can*) with a metric rather than a judgement call.

| Field | Definition |
|---|---|
| **Responsibility** | Interruption budget, modality cost, act-vs-queue decisions, natural interaction boundaries, priority lattice enforcement |
| **Boundaries — in** | Whether to *surface* something now |
| **Boundaries — out** | Whether to *do* it (13) — **preparation is unbudgeted and never routed through here** |
| **Authority** | `L1`–`L2` |
| **State owned** | Budget consumption per `(OperatingPeriod, attention_state)`; the queued-for-boundary list |
| **The rule** | `act_now ⇔ expected_value > interruption_cost ∧ decays`. Otherwise **queue**. There is no `DROP` outcome — dropping a high-value item would violate RB-005 |
| **Priority lattice** | `alarm/safety > active user task > ambience > proactive`. Alarm class is exempt from the budget, ambience policy, resource yielding, proportionality and device quiet-hours |
| **Modality cost** | `ambient_visual: low · visual_notice: medium · speech: high · alarm: exempt` |
| **Invariants** | `INV-TRIG-3`, `INV-ALARM-3` |
| **Failure modes** | Budget exhausted with a high-value decaying item → escalate one modality step **only if** value exceeds escalation cost, else queue and record; boundary never arrives → item persists, it is not aged out |
| **Observability** | Contacts per hour by modality, queue depth, items surfaced at boundaries, escalations |
| **Verification** | `A-047`, `A-041.5` |
| **Dependencies** | REM-007, 16 |

> **Jarvis-divergence.** *No.* Clause: **preparation is unbudgeted and interruption is budgeted — `A-047` asserts an unbounded number of prepared-but-not-surfaced actions is permitted.** A chatbot has no concept of work done for the user that the user has not yet been told about. The `decays` term only makes sense for a system that persists between conversations.

---

## SPEC-15 — Semantic scene

**Purpose.** The typed representation of everything user-visible. The artifact on which the *"not a chat UI"* claim rests.

| Field | Definition |
|---|---|
| **Responsibility** | Scene and element schema, presentation intent, spatial intent, affordances, update/streaming semantics, degradation ladders |
| **Boundaries — in** | *What the content means* |
| **Boundaries — out** | *How it looks* (16 renderers) and *where it goes* (17). **Producers never name an endpoint** |
| **Authority** | `L0` to construct; delivery is gated by 16/17 |
| **State owned** | Active scenes and their lifecycle |
| **Invariants** | `INV-SCENE-1`…`INV-SCENE-4`. Critically: **no free-form markdown or HTML field anywhere in the schema** |
| **Element types** | `text · metric · table · code · diagram · image · timeline · entity_ref · state_indicator · live_binding`, each with a declared degradation ladder per capability class |
| **Streaming** | `update_mode: stream` is architectural — first audio must begin before generation completes, or REM-010's latency budget is unmeetable by construction. Patches carry HLC, so out-of-order arrival resolves by the same supersession rule as world facts |
| **Failure modes** | Undeclared element type → rejected at the contract boundary; missing ladder entry → renderer registration fails |
| **Observability** | Scenes emitted, degradations by type and endpoint, withheld count |
| **Verification** | `A-009` (with the `{markdown, speech}` negative control), `A-026` |
| **Dependencies** | REM-009, 06 (space graph) |

> **Jarvis-divergence.** *No.* Clause: **`INV-SCENE-3` — no markup escape hatch — combined with `A-009`'s requirement that a `diagram` render as a *structural narration* on a voice-only endpoint.** A chat UI's output *is* markdown; it carries no typed structure from which a narration could be derived. `A-026` closes the remaining route by removing the text surface entirely.

---

## SPEC-16 — Presence / interaction

**Purpose.** Choose how VESPER exists in the current environment, and migrate when a surface disappears.

| Field | Definition |
|---|---|
| **Responsibility** | Endpoint selection, rendering dispatch, migration, interaction event capture, speech in/out, ambience coordination |
| **Boundaries — in** | Delivering a scene and observing the response |
| **Boundaries — out** | Scene content (15); capability description (17); privacy facts (06) |
| **Authority** | `L2` for ordinary output; ambience is `L2`–`L3`; alarm escalation is its own class |
| **State owned** | Active renderings per endpoint, migration state, interaction history for the current exchange |
| **Inputs** | Scene, endpoint capabilities, world facts (user location, persons present, space privacy), `OperatingPeriod`, interruption budget |
| **Outputs** | Rendered output; `presence.scene_emitted / degraded / endpoint_migrated / withheld`; interaction events |
| **Invariants** | `INV-PRIV-1` (**fail-safe routing** — withhold or route most-private; never default to the most public surface), `INV-SCENE-2` |
| **Failure modes** | No endpoint satisfies the minimum modality → `withheld` + queue, **never downgraded past its privacy class**; endpoint lost mid-stream → re-select and re-render, spoken prefix **semantically resumed**; space graph unavailable → withhold rather than guess |
| **Recovery** | Scenes are re-renderable from semantic form; `persist_until_acked` ensures a scene that mattered survives its surface |
| **Observability** | Selected modality **and reason**, latency, migrations, acknowledgements, withholds |
| **Security** | Privacy class per scene and per space; unknown person present suppresses private content |
| **Verification** | `A-009`, `A-010` part B, `A-026`, `A-046` |
| **Dependencies** | REM-009, REM-011, 15, 17, 06 |

> **Jarvis-divergence.** *No.* Clause: **`DF-SELECT-ENDPOINT`'s fail-safe — low location confidence or an unknown person in the space withholds.** A chatbot renders to the surface that made the request. `A-010`'s unknown-person cells have no meaning in a request-scoped system, and the natural wrong implementation (route to the largest display) is exactly what the negative control catches.

---

## SPEC-17 — Endpoint capability negotiation

**Purpose.** Describe what a surface can actually do, so degradation is a computed ladder rather than an improvisation.

| Field | Definition |
|---|---|
| **Responsibility** | `EndpointCapability` declaration and measurement, capability matching, degradation resolution, renderer registration |
| **Boundaries — in** | What an endpoint can render and at what fidelity |
| **Boundaries — out** | Selection policy (16); node trust (04) |
| **Authority** | `L0` |
| **State owned** | Capability descriptors per endpoint; declared degradation ladders per `(element type × capability class)` |
| **Fields** | `modalities · resolution_class · spatial_class {none, 2d, 2d_projected, pseudo_3d_glass, volumetric} · text_capacity · color · audio · interaction_classes · latency_class · privacy_class` |
| **Invariants** | `INV-SCENE-2`, `INV-SCENE-4`, `INV-HW-1` |
| **Failure modes** | Renderer with no ladder entry for a type → **registration refused**; capability under-declared → degradation reported and the scene still delivered |
| **Observability** | Registered endpoints and their descriptors; degradation frequency per pair |
| **Verification** | `A-009` (three materially different descriptors), `CI-030` |
| **Dependencies** | REM-009, REM-011, 04 |

> **Jarvis-divergence.** *No.* Clause: **`spatial_class` as a first-class capability dimension with a declared ladder down to `none`.** A chat UI has one rendering target and no ladder; the projector and glass-cube targets exist in the type system from day one, which is what ARCH-28 means by *"spatial contracts are architectural from the beginning."*

---

## SPEC-18 — Multimodal perception

**Purpose.** Turn the physical environment into provenance-carrying observations. Perception is what makes the world model *world*-shaped rather than document-shaped.

| Field | Definition |
|---|---|
| **Responsibility** | Audio/ASR, camera, screen capture, OCR/handwriting, image understanding, video (frames, motion comparison, duration, audio, captions, metadata), system/network telemetry as non-visual perception |
| **Boundaries — in** | Producing observations with provenance, timestamp, confidence and source device |
| **Boundaries — out** | Interpreting them into decisions (06, 13); identity *policy* (`DF-IDENTITY-RESOLVE`) |
| **Authority** | `L0` to observe; sensor arming is `L3`; sensitive inference is owner-only |
| **State owned** | Sensor lifecycle state, capture buffers (transient), derived artifacts |
| **Lifecycle** | `SM-SENSOR`: `DISABLED → ARMED → ACTIVE → PAUSED → DISABLED`, with the **physical-off edge reachable from every state** |
| **Invariants** | `INV-PRIV-2` (owner-only, local-only, non-exportable inference), `INV-PRIV-3` (raw media not persisted beyond the processing window), `INV-PRIV-4` (**guaranteed-off path software cannot override; no capture without a working indicator**), `INV-WORLD-1`, `INV-EVID-2` |
| **Retention** | Raw A/V: not persisted · derived observations: TTL · transcripts: **only on explicit user action** · OCR: TTL, **never for `unknown_person` frames** |
| **Failure modes** | Indicator undrivable → **refuse `ACTIVE`**; unknown person detected → `PAUSED` + inference suppressed; sensor loss → capability degradation reported |
| **Recovery** | Re-arm requires policy authorization; a physically-off sensor is never re-armed by software alone |
| **Observability** | Capture sessions, indicator state, suppression events, retention purges |
| **Security** | Everything here is `retrieved_external`-adjacent: OCR'd text is a documented injection vector (`A-025.3`) |
| **Verification** | `A-008`, `A-028`, `A-039` |
| **Dependencies** | REM-011, 06 |

> **Jarvis-divergence.** *No.* Clause: **`INV-PRIV-4` — a sensor refuses to capture when its indicator cannot be driven, and the guaranteed-off path is physical.** A chatbot receives uploads; it has no standing sensors, no consent surface, and no unknown-person case. `A-008.4` asserts capture stops *at source*, which is a statement about hardware, not software.

---

## SPEC-30 — Computer and device agency

**Purpose.** Operate a computer the way a person operates one: read the machine, decide, act on it, read it again, and be honest about what happened. This subsystem was **missing until 2026-08-12**. `ARCH-08` (*Computer and Device Interaction*) is a locked architecture section and `SR-020`/`SR-021` are locked source requirements, but of 29 subsystems none covered acting on a computer and of 30 decision functions none governed endpoint interaction. Computer agency was **permitted by the architecture and specified by nothing**, which is the precise condition under which an implementation quietly reduces it to *"answer questions about the computer."*

| Field | Definition |
|---|---|
| **Responsibility** | Reading a machine's surfaces (`EndpointSurfaceState`), planning a typed action (`EndpointInteraction`), actuating it, observing the result through an independent path, verifying against a declared post-condition, and recovering from a refuted or unknown outcome |
| **Boundaries — in** | The whole episode: `precondition → actuate → observe → verify → recover` (`SM-ENDPOINT-EPISODE`) |
| **Boundaries — out** | *Whether* an action is wanted (12, 13 — the autonomy and trigger layer); *whether* the subject may perform it (22, `DF-AUTHORIZE`); *whether* actuation is permitted at all right now (`DF-ACTUATION-GATE`); physical-world perception (18); presenting anything to the owner (15, 16) |
| **Authority** | `L0` to read a surface · the action's own `declared_level(args)` to act · runtime subjects additionally require a `trigger_id` and a per-action enable token |
| **State owned** | Episode state, surface observations (TTL-bounded), idempotency keys, attempt counters |
| **Lifecycle** | `SM-ENDPOINT-EPISODE`: `PLANNED → PRECONDITION_MET → ACTUATING → ACTUATED → OBSERVED → VERIFIED \| REFUTED \| OUTCOME_UNKNOWN → RECOVERING → CLOSED` |
| **Decisions** | `DF-ENDPOINT-ACT` (admission), `DF-ENDPOINT-OBSERVE` (evidence plan), `DF-ENDPOINT-RECOVER` (disposition of a bad outcome) |
| **Contracts** | `contracts/commands/endpoint_interaction.schema.json`, `contracts/entities/endpoint_surface_state.schema.json`, plus `Command`/`Result` for transport |
| **Invariants** | `INV-ACT-1` (typed action or no action), `INV-ACT-2` (**the actor's report is never the observation**), `INV-ACT-3` (screen content is `retrieved_external`), `INV-ACT-4` (no direct adapter path), `INV-ACT-5` (`UNKNOWN` is never closed as success or failure), `INV-ACT-6` (outbox and idempotency before an irreversible effect), and `INV-VERIF-1`, `INV-EXT-1`, `INV-AUTH-5/6/7`, `INV-STOP-1`, `INV-HW-1/2` |
| **Retention** | Surface observations: TTL, short · raw captures: not persisted beyond the processing window (`INV-PRIV-3`) · episode records: durable, they are the audit trail of everything VESPER did to a machine |
| **Failure modes** | Surface `UNKNOWN` or stale → refuse, do not act hopefully · no independent observation path → `OUTCOME_UNKNOWN`, never `VERIFIED` · stop engaged mid-episode → `OUTCOME_UNKNOWN` then recovery · non-idempotent action with unknown outcome → compensate or escalate, **never retry** |
| **Recovery** | `DF-ENDPOINT-RECOVER` returns `RETRY \| COMPENSATE \| ESCALATE \| HALT`. It has no branch returning success: recovery decides what to **do** about an outcome, never relabels it |
| **Observability** | Every episode with its interaction, observation source, verification strategy, outcome and disposition. Arguments are sensitivity-classified at write time (`INV-OBS-1`) |
| **Security** | This is the highest-consequence surface in the system and the most convincing injection vector in it. Text read off a screen is written by whoever wrote the screen: `trust_class` is structurally fixed to `retrieved_external` in the surface contract, so an instruction found on a machine is ceiling-bound to `L1` and an above-ceiling attempt becomes a queued proposal with `security.injection_suspected` (`A-052`) |
| **Model and node agnosticism** | Nothing here names a model or a product. The target is a **node identity plus a surface class plus a measured capability requirement**; which node satisfies it is `DF-PLACE`'s answer at the moment of acting and may differ next time. An unmeasured endpoint capability is treated as unavailable (`INV-HW-2`) |
| **Verification** | `A-013` (capability-controlled interaction), `A-051` (**the closed loop, with the self-report build as the negative control**), `A-052` (injection and mid-episode stop), `A-008` (perception provenance) |
| **Dependencies** | REM-012, REM-003, REM-005, REM-011; subsystems 06, 12, 13, 18, 22, 24 |

> **Jarvis-divergence.** *No.* Clause: **`INV-ACT-2` — the actuator's report is never the observation, and `SM-ENDPOINT-EPISODE` has no edge from `ACTUATED` to `VERIFIED`.** A conventional assistant calls a tool, receives the tool's own reply, and reports success; the loop closes inside the model's context and nothing external ever confirms anything. Here the loop closes on the **machine**: the post-state is read back through a path that is not the acting path, `OUTCOME_UNKNOWN` is a first-class terminal reading, and an episode that cannot be observed is not a successful one. `A-051`'s negative control is a build that closes the episode on the actor's own success report — it must **FAIL**, and a chatbot-with-tools **is** that build.
