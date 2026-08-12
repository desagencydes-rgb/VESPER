# SPEC-A — Control plane and distribution

Subsystems **01, 02, 03, 04, 05, 24, 29**. Index: [SPEC-00](SPEC-00-INDEX.md).

---

## SPEC-01 — Persistent VESPER runtime

**Purpose.** Hold VESPER's identity, lifecycle and durable state so that neither a model process exiting nor a device disconnecting destroys the system. Closes the referent for COC ARCH-03, which is referenced by zero SRs in the original Part XI.

| Field | Definition |
|---|---|
| **Responsibility** | Supervise component lifecycles; own the durable identity record; hold the process supervision tree; expose health; coordinate startup ordering and shutdown draining |
| **Boundaries — in** | Identity, supervision, startup/shutdown, health, degraded-mode entry |
| **Boundaries — out** | Task scheduling (05), model execution (10), authorization decisions (22). The runtime **supervises**; it does not decide |
| **Authority** | Holds **`E1` at most, permanently** (`INV-AUTH-0`, REM-004). No `L`-level converts to an `E`-level |
| **State owned** | `identity` (persistent id, policy version pin, artifact content hash), supervision tree, health |
| **Inputs** | Deployed artifact (pinned, content-addressed); `config/` read-only; node identity from ADR-007 |
| **Outputs** | `runtime.started` / `runtime.degraded` / `runtime.stopping`; health to the interlock's external channel |
| **Persistence** | Identity survives every restart. **Artifact content hash is recorded at every start**, so "has the running system changed?" is a hash comparison rather than an investigation (REM-004 §9) |
| **Concurrency** | Single supervisor per node. Components restart independently under supervision |
| **Lifecycle** | `COLD → STARTING → RUNNING → DEGRADED → DRAINING → STOPPED`. `DEGRADED` is a first-class operating state, never a prelude to exit — ARCH-03 requires entering degraded modes *rather than terminating* |
| **Invariants** | `INV-SELF-4` (filesystem capability excludes `GOVERNED_PATHS`), `INV-SELF-6` (no path from commit to running process except a human-gated promotion) |
| **Failure modes** | Component crash → supervised restart; repeated crash → `DEGRADED` + capability degradation reported (RB-022); artifact hash mismatch → **refuse to start**, preserve as evidence; config unreadable → fail closed |
| **Recovery** | Restart from the pinned artifact; restore state from ADR-002 persistence; tasks re-enter via `RESUMABLE` |
| **Observability** | Startup ordering, restart counts per component, artifact hash, degraded-mode entries/exits with cause |
| **Security** | Executes from the deployed artifact, **not** the working repository (ADR-012 D1). Workspace is writable; `GOVERNED_PATHS` is not |
| **Verification** | `A-002`, `A-019`, `A-030` |
| **Dependencies** | ADR-002 (persistence), ADR-012 (topology), ADR-007 (node identity) |

> **Jarvis-divergence.** *No.* Clause: **the artifact content hash recorded at every start, combined with a filesystem capability set that excludes `GOVERNED_PATHS`.** A chatbot backend has no notion of a pinned self, so `A-030.8` (no path from commit to running process) is meaningless for it and unimplementable in it.

---

## SPEC-02 — Core control loop

**Purpose.** Run the continuous `observe → normalize → world model → evaluate → decide → authorize → execute → verify → update → learn` cycle that generates proactivity. ARCH-04 is referenced by zero SRs in the original Part XI; this is its specification.

| Field | Definition |
|---|---|
| **Responsibility** | Drive the cycle at a fixed tick **and** on world-model change; emit a heartbeat per cycle; record no-ops |
| **Boundaries — in** | Cycle orchestration, heartbeat, no-op recording, evaluator scheduling |
| **Boundaries — out** | Predicate semantics (13), planning (12), rendering (16). The loop **sequences**; it does not judge |
| **Authority** | `L0` intrinsically. Every action it dispatches is separately authorized (22) and gated (23) |
| **State owned** | `cycle_id`, evaluator lag, heartbeat cadence |
| **Inputs** | World-model change notifications; tick; task-graph state |
| **Outputs** | `autonomy.heartbeat` per cycle; `autonomy.noop_recorded`; dispatch to 12 |
| **Persistence** | None beyond cycle counters — the loop is **stateless by design** so a restart cannot resurrect a stale decision |
| **Concurrency** | Single loop per control-plane owner. Evaluation is a deterministic pass; execution is dispatched asynchronously |
| **Invariants** | `INV-AUTO-1` (heartbeat every cycle; absence beyond `3 × tick` is an incident), `INV-TRIG-6` (a no-op carries a `trigger_id`) |
| **Failure modes** | Loop stall → `autonomy.loop_stalled` **surfaced through the interlock's external channel**, not through VESPER's presence layer (a wedged VESPER cannot report its own wedging); evaluator lag → degrade by priority, never silent drop |
| **Recovery** | Supervisor restart; the loop resumes from current world state and **does not replay missed cycles** — a predicate over current state is self-correcting |
| **Observability** | Heartbeat cadence, triggers evaluated/fired, no-ops, lag |
| **Verification** | `A-029` parts 1 and 2, `A-011` |
| **Dependencies** | 06, 13, 12, 25 |

> **Jarvis-divergence.** *No.* Clause: **`INV-AUTO-1` — a heartbeat every cycle, whose absence is an incident.** A request-scoped system emits nothing between requests, so `A-029` C3 (prompt-driven) and C4 (silent death) both fail part 1. The heartbeat is what makes "quiet" distinguishable from "dead".

---

## SPEC-03 — Event / Command / Result architecture

**Purpose.** The coordination substrate. Three distinct types with three distinct meanings, and the rule that keeps them distinct: **a Command is never proof that an action happened.**

| Field | Definition |
|---|---|
| **Responsibility** | Typed, versioned, HLC-stamped envelopes; at-least-once delivery; total order per `(source, subject)`; consumer idempotency registration |
| **Boundaries — in** | Envelope shape, delivery, ordering, idempotency, schema versioning |
| **Boundaries — out** | Transport choice (ADR-001), payload semantics (per type) |
| **Authority** | `L0`. The bus carries; it does not authorize |
| **State owned** | Append-only event log; consumer offsets; idempotency ledger |
| **Inputs** | Producers across every plane |
| **Outputs** | Ordered per-subject streams to registered consumers |
| **Persistence** | **Append-only and immutable.** Migration is read-time upcasting; the log is never rewritten (`INV-SCHEMA-2`). Payload/reference separation lets purge remove content while skeletons and the correlation chain survive |
| **Concurrency** | Per-subject serialisation; cross-subject concurrency unrestricted and **explicitly unordered** |
| **Invariants** | `INV-COORD-1`…`INV-COORD-5`, `INV-SCHEMA-1`, `INV-SCHEMA-2`, `INV-OBS-1` |
| **Contracts** | `event_envelope.schema.json`, `command.schema.json`, `result.schema.json` |
| **Failure modes** | Duplicate delivery → consumer idempotency absorbs; out-of-order arrival → `DF-SUPERSEDE` rejects; clock regression → HLC unaffected, `system.clock_regression`; log corruption → quarantine segment as evidence, restore from checkpoint, **never partially trust** |
| **Recovery** | Replay is order-insensitive and repetition-insensitive by construction — which is why this had to land before the persistence design, not after |
| **Observability** | Delivery counts, duplicate counts, consumer lag, rejected writes |
| **Security** | `trust_class` on the envelope; `sensitivity` enforced by the writer at write time; `secret` payloads never inline |
| **Verification** | `A-033` (with the wall-clock negative control) |
| **Dependencies** | ADR-001, ADR-007 |

> **Jarvis-divergence.** *No.* Clause: **`Result.status = "unknown"` as a first-class outcome.** A chatbot's tool call returns or throws. VESPER must represent *"the command was issued and I cannot determine whether the effect occurred"* without coercing it to success or failure — that coercion is precisely the guess RB-002 forbids, and it is the state a crash mid-external-call actually produces.

---

## SPEC-04 — Distributed node fabric

**Purpose.** Make nodes participants in one system rather than separate assistants, with trust as a gate rather than a consequence of connectivity.

| Field | Definition |
|---|---|
| **Responsibility** | Discovery, enrollment, admission, trust zones, capability advertisement, reachability, revocation |
| **Boundaries — in** | Node identity, `SM-DEVICE` lifecycle, `NodeCapabilityProfile`, trust zone assignment |
| **Boundaries — out** | Lease ownership (05), placement decisions (11, 20) |
| **Authority** | Enrollment is `L5` **owner-gated**. *Visibility on a LAN does not imply trust* — and admission is what does |
| **State owned** | Device registry (leased domain `devices`), trust state, measured capability profiles |
| **Inputs** | Discovery beacons, enrollment requests, heartbeats, enrollment benchmark results |
| **Outputs** | `device.enrolled` / `device.trusted` / `device.degraded` / `device.revoked`; capability graph to 11 and 17 |
| **Persistence** | Registry is durable; **`sustained_tokens_per_sec` is measured at enrollment, never declared** (`INV-HW-2`) |
| **Concurrency** | Single writer (`devices` lease); non-owners `READ_CACHED` |
| **Lifecycle** | `SM-DEVICE`: `DISCOVERED → ENROLLED → {TRUSTED \| LIMITED_TRUST} → ONLINE → DEGRADED → OFFLINE → REVOKED` |
| **Invariants** | `INV-TRUST-1` (`Z2` may not hold state, issue commands, or receive secrets), `INV-TRUST-2` (no continuity-critical capability solely on a foreground-only node), `INV-HW-2` |
| **Failure modes** | Baseline failure → `LIMITED_TRUST` (`Z2`), not rejection — the J3 is useful as a display without being trusted with state; re-attestation expiry → demote + report; benchmark cannot run → stays `ENROLLED`, never routed to |
| **Recovery** | Re-enrollment; credential rotation on compromise (`isolate → preserve evidence → revoke/rotate → recover`) |
| **Observability** | Enrollment events, trust transitions, re-attestation, reachability |
| **Security** | Cryptographic node identity (ADR-007); `Z0`–`Z3` zones per `docs/AUTHORITY_AND_PRECEDENCE.md §4.3` |
| **Verification** | `A-042`, `A-045`, `A-010` |
| **Dependencies** | ADR-007, REM-011 |

> **Jarvis-divergence.** *No.* Clause: **`Z2 limited_trust` — a node that may render and observe but may not hold state, issue commands, or receive secrets.** A chatbot has clients, not nodes; there is no state for a client to hold and therefore no admission question. `A-042.3` has no analogue.

---

## SPEC-05 — State ownership

**Purpose.** Guarantee exactly one writer per state domain at any instant, so that two nodes cannot silently diverge. This is the mechanism behind COC Part XVI's headline continuity claim.

| Field | Definition |
|---|---|
| **Responsibility** | Lease acquisition/renewal/demotion, epoch fencing, promotion decisions, partition behaviour, rejoin merge |
| **Boundaries — in** | The seven domains: `tasks`, `world`, `memory`, `devices`, `policy`, `autonomy_queue`, `alarms` |
| **Boundaries — out** | The *content* of each domain (owned by its subsystem) |
| **Authority** | Lease grant is control-plane authority. **Manual promotion in a no-quorum partition is human-only, by decision** |
| **State owned** | Lease table, `lease_epoch` per domain |
| **Inputs** | Reachability, quorum, heartbeats, operator promotion |
| **Outputs** | `control.lease_acquired` / `lease_lost` / `fenced` / `promotion_requires_operator` |
| **Persistence** | Leases durable with epochs; **every write to a leased domain carries its epoch, and the storage layer rejects stale ones** |
| **Concurrency** | One holder per domain; domains leased **independently** — the MacBook may own `tasks` while the desktop owns `world` |
| **Lifecycle** | `SM-LEASE` |
| **Invariants** | `INV-OWN-1`…`INV-OWN-4` |
| **Failure modes** | Renewal failure → self-demote at TTL, flush, checkpoint — **never keep writing hopefully**; partition → neither side promotes, both queue, `L4`+ suppressed on both; stale rejoin → `FENCED` |
| **Recovery** | Rejoin applies queued writes under HLC supersession. **Owner-wins** for `policy`/`devices` (authoritative configuration); **supersession-wins** for `world`/`memory` (observation); outbox reconciliation for `tasks` |
| **Observability** | Lease transitions, epoch, fencing events, promotion decisions and their inputs |
| **Security** | A `Z2` node may never hold a lease |
| **Verification** | `A-034` (with the no-fencing negative control), `A-017` |
| **Dependencies** | REM-001 (supersession is the merge rule), ADR-002, ADR-012 |

> **Jarvis-divergence.** *No.* Clause: **partition behaviour — a node that cannot see its peers may not resolve that ambiguity in its own favour.** A chatbot has one writer and no partition. `A-034.4` (lease expiry with no quorum → refuse to promote, degrade read-only) is a decision only a distributed system can get wrong.

---

## SPEC-24 — Recovery

**Purpose.** Make recovery *ordinary operation running backwards* rather than a separate subsystem. ARCH-24 is referenced by zero SRs in the original Part XI.

| Field | Definition |
|---|---|
| **Responsibility** | Checkpointing, restore, resumption, incident evidence preservation, rollback of the deployed artifact |
| **Boundaries — in** | Checkpoint format, resume semantics, restore ordering, evidence preservation |
| **Boundaries — out** | Fault *detection* (29), external-effect reconciliation (REM-012 §2) |
| **Authority** | Restore is `L3`; artifact rollback is `L5` human |
| **State owned** | Checkpoints, restore points, incident evidence store |
| **Inputs** | Task state, outbox cursor, lease epoch, artifact hashes |
| **Outputs** | `recovery.checkpoint_written` / `restored` / `incident_preserved` |
| **Persistence** | Checkpoint = goal, plan, completed steps + results, evidence refs, **grant references (never grant secrets)**, outbox cursor, resource consumption, epoch. **Excluded:** model context windows, raw media, secrets — a checkpoint is a resumption record, not a memory dump |
| **Concurrency** | Checkpoint write ≤ 200 ms, acknowledged **before** a step is marked complete |
| **Invariants** | `INV-TASK-2` (resume replays from the outbox cursor, never plan start), `INV-EXT-2` |
| **Failure modes** | Checkpoint corruption → previous checkpoint, corrupted one preserved as evidence, task re-enters `RESUMABLE` and **never `SUCCEEDED`**; store corruption → isolate, preserve, restore known-good, replay log |
| **Recovery** | Promotion is a lease acquisition; resume is a checkpoint restore; rejoin is a supersession-ordered replay — **a recovery path exercised only during incidents is one that does not work** |
| **Observability** | Checkpoint latency, restore counts, resumption sources |
| **Verification** | `A-019`, `A-017`, `A-034.5`, `A-035` |
| **Dependencies** | 03, 05, REM-012 §2 |

> **Jarvis-divergence.** *No.* Clause: **resume replays from the outbox cursor, so an already-sent external action is not repeated.** A chatbot that restarts loses the conversation and calls that acceptable; `A-034.5` requires a task to survive the death of its machine *and* not re-send the email it already sent.

---

## SPEC-29 — Failure isolation

**Purpose.** Ensure one failing component degrades capability rather than the system, and that degradation is always visible.

| Field | Definition |
|---|---|
| **Responsibility** | Failure-domain boundaries, detection, containment, degraded-mode declaration, capability-loss reporting |
| **Boundaries — in** | Domain definition, circuit breaking, containment, degradation reporting |
| **Boundaries — out** | Recovery execution (24), security containment (21) |
| **Authority** | Containment is `L3`; node isolation is `L4` |
| **State owned** | Per-domain health, breaker state, active degradations |
| **Failure domains** | Model/provider · runtime-worker · process · node · network · storage · device · external service · configuration · security incident. **Each declares detection, containment, degraded mode, recovery and reporting** — a domain missing any of the five is not a domain |
| **Invariants** | `INV-TRIG-*` trigger failure isolation (one disabled trigger never affects another); RB-022 / DR-021 no silent capability loss |
| **Failure modes** | Cascading failure → breakers open per domain; repeated open/close → **damped** per REM-012 §5, alert rather than another transition |
| **Recovery** | Half-open probing with asymmetric thresholds: **degrade fast, recover slow** |
| **Observability** | Breaker state, degradation entries/exits with cause, capability availability |
| **Verification** | `A-004`, `A-005`, `A-017`, `A-034` |
| **Dependencies** | 25, 24 |

> **Jarvis-divergence.** *No.* Clause: **DR-021 / RB-022 — when a capability disappears, VESPER reports the degradation and reroutes.** A chatbot that loses a tool returns an error for that request and is otherwise unchanged; VESPER must maintain a *standing* capability inventory whose reduction is an event the user is told about. `A-042.5` (re-attestation expiry demotes and emits degradation) has no request to attach to.
