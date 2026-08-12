# ADR-001 — Coordination substrate: clock, delivery, ordering, supersession

| | |
|---|---|
| **Status** | **ACCEPTED** (engineering authority; no SR semantics affected) |
| **Date** | 2026-08-11 |
| **Owner** | Core Systems Engineer |
| **Supersedes** | Foundation ADR-001 "Event transport" — previously *Intentionally unresolved* |
| **Source requirements** | SR-011, SR-015, SR-019, SR-020, SR-026, SR-028, SR-036, SR-042, SR-049 |
| **Derived** | DR-003, DR-006, DR-007, DR-017, DR-020, DR-021 |
| **Remediation** | `docs/remediation/REM-001` |
| **Closes** | AR-003 (P0), GAP-001, GAP-002, GAP-003, GAP-008 |

## Context

VESPER is multi-node with **designed** intermittency: the handwritten source states the desktop "may be disconnected (from time to time)" and the J3 "may be offline — just from time to time". Partition is a normal operating mode, not an exception.

COC ARCH-05 states the entire freshness mechanism as: *"Use timestamps and confidence/health status so stale observations do not become current truth."* That sentence is only sound if clocks agree. Across a roaming laptop, a legacy Android handset and a desktop that sleeps, they do not.

The Foundation filed event transport as *"Intentionally unresolved"* while simultaneously making increment #2 *"Event contract + durable task state"*. Deferring this does not avoid a premature lock; it delegates the lock to whoever implements first.

## Problem

No delivery guarantee, no ordering guarantee, no clock model, no supersession rule, no expiry rule, and no conflict semantics. Without them, "stale observations do not become current truth" is unimplementable, and RB-002 (*no guessing*) is violated by construction every time a stale fact is read as current.

## Constraints

- Single-user home fabric, ≤ 8 nodes. Distributed-systems machinery must be proportionate.
- Nodes are heterogeneous down to a Samsung Galaxy J3; the model must be implementable there.
- COC ARCH-04's *"A command is never proof that an action happened"* must survive.
- No requirement in the corpus needs cross-subject total order.

## Options

| # | Option | Verdict |
|---|---|---|
| 1 | Wall-clock timestamps only | **Rejected.** This is the status quo and is precisely what AR-003 falsifies. Clock skew silently reorders facts. |
| 2 | NTP-disciplined wall clock + "close enough" | **Rejected.** Reduces skew, does not bound it, and fails entirely for a node offline for hours. Produces a system that is correct in testing and wrong in the field. |
| 3 | Vector clocks per subject | **Rejected.** Correct, but the metadata grows with node count and it provides causality VESPER never queries. Unjustified complexity at this scale. |
| 4 | **Hybrid Logical Clock (HLC) + at-least-once delivery + per-subject total order + explicit supersession/TTL/conflict rules** | **ACCEPTED.** Bounded metadata (three fields), implementable on every node class, and it makes freshness and supersession decidable without inventing consensus. |
| 5 | Full consensus (Raft) over the event log | **Rejected for the event log.** A partition-prone fabric where the source *requires* disconnected operation cannot make progress under a quorum-writes rule. (Leases in ADR-002 use quorum only for *promotion*, which is the correct narrow use.) |

## Decision

Accepted as stated in `docs/remediation/REM-001 §7`, normatively:

1. **Clock.** Every event carries `hlc = (physical_ms, logical_counter, node_id)`. Wall-clock time is retained as `observed_at_wall` for **user display and policy windows only**, and is never used for ordering or supersession.
2. **Delivery.** At-least-once. Every consumer is idempotent on `event_id` or on a declared natural key.
3. **Ordering.** Total order per `(source, subject)`. No cross-subject ordering guarantee is provided or may be assumed.
4. **Supersession.** A world-model fact is `(subject, attribute, value, observed_at_hlc, valid_until, confidence, source, provenance)`. A write is REJECTED if `observed_at_hlc <= current.observed_at_hlc`, regardless of arrival order.
5. **Expiry.** Every observation type declares a TTL. On expiry the fact becomes `UNKNOWN` — never "last known value".
6. **Conflict.** Two non-superseded facts for the same `(subject, attribute)` from different sources within their validity windows are a conflict. The world model emits `world.conflict` and does not select a winner silently.

## Consequences

**Positive.** Fixes the shape of every event envelope and every world-model write path exactly once, before any of them exist. Makes ADR-002's partition handling and REM-006's operating-period evaluation expressible. Turns RB-002 from a disposition into a data-structure property: `UNKNOWN` is a representable value, so "no guessing" has somewhere to go.

**Negative / accepted costs.** Every consumer carries an idempotency obligation. HLC adds ~16 bytes per event. A conflict is a first-class outcome that the presence layer must be able to render, which is a real obligation on REM-009's `SemanticScene`.

**Rejected shortcut.** "Last write wins by arrival order" is the natural implementation and is prohibited by `INV-COORD-1`, because arrival order on a partition-prone fabric is uncorrelated with observation order.

## Interfaces

`IC-001` (event bus). Contract: `contracts/events/event_envelope.schema.json`, `contracts/entities/world_fact.schema.json`.

## Security

HLC `node_id` is the node's cryptographic identity from ADR-007, not a self-asserted name; otherwise a compromised node can forge supersession by claiming another node's identity. A node may not advance another node's logical counter.

## Persistence

The event log is append-only and immutable (Foundation: *"past events immutable"*). World-model facts are mutable-by-supersession with `supersedes` retained, so provenance survives correction (IC-006).

## Failure modes

Clock jump backwards; node offline beyond TTL; duplicate delivery; conflicting simultaneous observation; log corruption. Each is covered by `A-033`.

## Rollback

Schema-versioned envelopes (`schema_version` mandatory) with the migration rule in REM-011. HLC is additive to a wall-clock envelope, so a v1→v2 migration is forward-only and does not require a log rewrite.

## Acceptance tests

`A-033` (coordination substrate fault-injection suite), extending `A-010` and `A-017`.
