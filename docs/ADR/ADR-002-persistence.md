# ADR-002 — Persistence: durable stores, fencing primitive, checkpoint format, migration and recovery

| | |
|---|---|
| **Status** | **ACCEPTED** — by the project owner, 2026-08-14, under `OWNER-DECISION-006(b)`, on the seven `SPIKE-008` criteria tested. Previously `PROPOSED`. **`INV-ADR-1` is discharged and F0 is unblocked.** See §Acceptance authority for the condition it was given under and the two criteria still open. |
| **Date** | 2026-08-12 |
| **Owner** | Core Systems Engineer |
| **Supersedes** | Foundation ADR-002 *"Persistence engine: task state, memory, provenance, migration and recovery"* — previously *Intentionally unresolved* |
| **Source requirements** | SR-011, SR-019, SR-041, SR-049, SR-053, SR-058, SR-060 |
| **Derived** | DR-002, DR-007, DR-017, DR-021, DR-022 |
| **Remediation** | `docs/remediation/REM-002` (leases, tasks, checkpoints) · `REM-001` (log semantics) · `REM-016` (tombstones, loss classes) |
| **Closes** | GAP-004, GAP-010, GAP-046 · AR-009 (the persistence half) |
| **Blocks** | **F0 in its entirety.** `INV-ADR-1` forbids any merge under `core/`, `tasks/` or `memory/` while this ADR is not ACCEPTED. |

## Context

REM-002 specifies leases, epoch fencing, a task transition table and a checkpoint content list, and then defers the engine: *"Persistence engine (concrete) — ADR-002. Constrained here: must support atomic epoch-fenced writes and durable append-only log."* REM-001 specifies an append-only, HLC-ordered event log. REM-016 requires tombstones in a store **separate** from the records they describe. Three specifications converge on a persistence layer that does not exist, and F0's first increment is exactly that layer.

The Foundation filed this *"Intentionally unresolved"*. Deferring it does not avoid a premature lock — it delegates the lock to whoever writes the first `open()` call, which is the failure ADR-001 and ADR-012 were written to stop repeating.

## Problem

Five decisions must be made together or not at all, because each constrains the others:

1. **Which engine**, given that the same code must run on a laptop, a desktop, and a foreground-only handset that is sometimes the only reachable node (SR-060).
2. **How many physical stores**, given that REM-016 assigns different loss classes to different record kinds and `DF-LOSS-CLASS` takes `store` as a *deterministic input* — so store boundaries are load-bearing, not an implementation preference.
3. **What makes fencing atomic.** `INV-OWN-3` says stale-epoch writes are *"rejected at the storage layer"*. If that check is a read-then-write in application code, it is a race, and the invariant is false in exactly the partition-rejoin case it exists to cover.
4. **What migration means**, given `INV-SCHEMA-2` (*the event log is never rewritten*) and `INV-SCHEMA-1` (*readers accept N and N-1*).
5. **What recovery restores**, given that `RESUMABLE` must be reachable and `SUCCEEDED` must not be (`INV-TASK-1`, `INV-LOSS-4`).

## Constraints

- Every node class in the fabric must be able to host the store, including `Z2 limited_trust` nodes that may **not** hold state — so the store must be omissible per node, not assumed.
- No server process, no operator, no scheduled maintenance. A persistence layer requiring a DBA is a persistence layer that stops working the first week.
- Crash-safe under power loss on a laptop lid-close and a phone process kill.
- Checkpoint write budget ≤ 200 ms (REM-002 §4.7; carried into `contracts/policy/latency_budgets.toml`).
- Must support a single-statement conditional write, so fencing is one atomic operation.
- Must survive being carried, whole, to the weakest reachable node (`INV-PLACE-3`).
- Governed-surface configuration and runtime state are **never the same file** (SPEC-26).

## Options

| # | Option | Verdict |
|---|---|---|
| 1 | Flat files + JSON Lines, hand-rolled | **Rejected.** No atomic conditional write, so fencing degrades to advisory and `INV-OWN-3` becomes unenforceable. Crash-safety would be re-invented badly. |
| 2 | Embedded KV store (RocksDB / LevelDB) | **Rejected.** Compaction pressure and background threads on a battery-powered, foreground-only node are the wrong failure mode for the survival case. No conditional-update primitive without a read-modify-write dance. |
| 3 | LMDB | **Rejected.** Good crash-safety, but no query surface for the audit reconstruction `A-018` requires, and its mobile story is weak on the exact node class SR-060 makes decisive. |
| 4 | **SQLite, WAL journal mode, one file per store** | **ACCEPTED.** Present on every target OS including iOS and Android; single-file so a store *is* a portable artifact; ACID; `UPDATE … WHERE lease_epoch = ?` is one atomic statement, which is precisely the fencing primitive `INV-OWN-3` needs; SQL satisfies the audit reconstruction requirement without a second engine. |
| 5 | Client/server RDBMS (PostgreSQL) | **Rejected.** Requires an always-on server, which contradicts SR-060 (survival on the last device standing) and reintroduces the single point of failure ADR-012 removed. |
| 6 | An event-sourcing framework | **Rejected.** Couples the durable format to a runtime library. The log semantics are already fixed by ADR-001; a framework would add a second, competing definition. |

## Decision

### D1 — Engine

**SQLite in WAL mode**, `synchronous = FULL` on the log, audit and checkpoint stores; `synchronous = NORMAL` permitted on the workspace store only. One SQLite file per store. No ORM in `core/`: the storage layer is written against the fencing and append-only primitives directly, because an ORM's default `UPDATE` is the exact statement D3 prohibits.

### D2 — Five physical stores, and why the boundaries are normative

Store separation is derived from `DF-LOSS-CLASS`, which classifies a loss **by the store the record lived in**. A single-file design would make loss classification a judgement call, and `INV-LOSS-6` forbids that.

| Store | Contents | Loss class (REM-016) | Write mode |
|---|---|---|---|
| `log.db` | Append-only event log, HLC-ordered per `(source, subject)` | **B** | Append only. No `UPDATE`, no `DELETE` — enforced by capability (D9), not by convention. |
| `state.db` | The seven leased domains: `tasks`, `world`, `memory`, `devices`, `policy` *(cached projection only)*, `autonomy_queue`, `alarms` | **B** | Fenced writes only (D3) |
| `audit.db` | Authorization decisions, `selfmod.attempt_blocked`, stop/re-arm events, deletion audit, integrity chain | **C** | Append only, hash-chained (D8) |
| `tombstones.db` | One index entry per durable record ever written, and per record deleted | **C** | Append only |
| `workspace.db` | Improvement backlog, caches (all five tiers), learned artifacts, derived indexes | **A** | Unrestricted to the runtime (`INV-IDEA-2`) |

> **`tombstones.db` is separate on purpose.** `INV-LOSS-3` says VESPER never presents a known cause as forgetting, and with no tombstone it says nothing. A tombstone stored beside the record it describes is destroyed by the same event that destroys the record — which would convert every mass loss into silence, the one outcome REM-016 exists to prevent.

> **`policy` in `state.db` is a cached projection, never the authority.** The authority is the governed surface on disk, read from the pinned deployed artifact (ADR-012 D1). SPEC-26's *"no file is both governed configuration and runtime state"* is preserved because the projection is rebuilt from the artifact at start and is never written back.

### D3 — Fencing is a storage-layer primitive

Every write to a leased domain executes as a **single statement** carrying the epoch guard:

```sql
UPDATE <domain_table>
   SET ..., lease_epoch = :epoch
 WHERE <key> = :key
   AND lease_epoch <= :epoch;
-- rowcount == 0  =>  REJECTED (stale epoch). Never a retry, never a fallback path.
```

Inserts carry the same guard through a `WHERE NOT EXISTS (… lease_epoch > :epoch)` clause. A zero-row result is a **rejection that is emitted** (`control.fenced`), not an error to be swallowed. Any read-then-write implementation of the same check is non-compliant and is what `CI-009` scans for.

### D4 — The event log is never rewritten

Append-only, in the physical sense: the runtime's handle on `log.db` holds no `UPDATE`/`DELETE` capability. Migration is **read-time upcasting**: a registered chain of upcaster functions keyed by `(event_type, from_version)`, applied on read until the reader's current version is reached.

Upcasters are **governed code** (they live under `core/` and are therefore inside `GOVERNED_PATHS`). This is deliberate: an upcaster is the one place where a runtime that could edit it could rewrite history without touching the log.

### D5 — Schema version policy

Readers accept `N` and `N-1`; writers emit `N` (`INV-SCHEMA-1`). A breaking change requires an ACCEPTED ADR **and** a dual-read window at least as long as the longest expected node absence, because a node offline across a version bump must still be readable on rejoin — the J3 and the desktop are explicitly allowed to be offline for days (SR-058).

The migration unit is the upcaster, not a batch job. There is no offline migration step, because there is no moment at which every node is present.

### D6 — Checkpoint durability

A checkpoint is one transaction against `state.db`, committed with `synchronous = FULL`, and **acknowledged before the plan step is marked complete**. Content and exclusions are already normative in `contracts/entities/checkpoint.schema.json`; this ADR adds only the durability ordering, which is the part an implementation gets wrong: marking the step complete first and checkpointing after produces a task that resumes having forgotten what it just did.

### D7 — Recovery is ordinary operation running backwards

| Situation | Restore path |
|---|---|
| Node loss mid-task | Load the latest checkpoint whose `lease_epoch` is not stale; replay `log.db` forward from `checkpoint.written_at_hlc`; task enters `RESUMABLE → READY`. |
| Checkpoint fails integrity check | Fall back to the previous checkpoint; the corrupted one is **preserved as incident evidence**, never deleted; the task re-enters `RESUMABLE`. It may never enter `SUCCEEDED` (`INV-LOSS-4`). |
| Store-level corruption | Isolate the store, emit a class-appropriate `RecordLoss` (`DF-LOSS-CLASS` reads the store name), restore the last verified backup, replay the log forward. Corruption of `audit.db` or `tombstones.db` is **class C** and is an incident with no affect (`INV-LOSS-2`). |
| Rejoin after partition | Queued writes are replayed as ordinary writes subject to supersession (ADR-001 D4); nothing is applied with owner authority (`FENCED`). |

### D8 — Audit integrity chain

Each `audit.db` row carries `prev_hash` over the canonical serialization of the previous row. A break in the chain is detectable without a second system and is, by `DF-LOSS-CLASS`, a class C loss. This is what makes *"deletion of an audit record is distinguishable from ordinary forgetting"* a mechanical property rather than a hope.

### D9 — Capability boundary at the storage layer

The runtime process opens `log.db`, `audit.db` and `tombstones.db` through handles that hold **no** `UPDATE` or `DELETE` authority. Enforced by the storage layer's own API surface (no such method is exposed) and by the OS filesystem capability set (ADR-012 layer 2). A policy statement alone would be layer 4 — the layer prompt injection defeats.

### D10 — Backup and the survival subset

Online backup via SQLite's backup API to a second enrolled node, at least daily and before any promotion. Restore is the same code path as node failover; a recovery path exercised only during incidents does not work.

On entering `SURVIVAL` (`DF-PLACE`), the carried set is: `tombstones.db`, the `audit.db` tail, `state.db` restricted to `tasks`/`memory` references/`autonomy_queue`, and the `log.db` tail from the last checkpoint. **`workspace.db` is class A and may be left behind** — and its absence is reported as a degradation (`INV-PLACE-3`), never silently.

## Consequences

**Positive.** F0 becomes buildable: durable task state, checkpoints and the event bus all have a defined substrate. `INV-OWN-3` becomes a single SQL statement rather than a protocol. Store separation gives `DF-LOSS-CLASS` a deterministic input, so loss classification needs no model and no judgement.

**Negative / accepted costs.** Five files instead of one, and cross-store consistency is therefore **not** transactional: a task write and its audit row are two transactions. This is accepted deliberately — the alternative couples the integrity store's availability to the state store's, and a system that cannot write state must still be able to write audit. Ordering is fixed: **audit first, then effect** (the same rule as `INV-EXT-1`'s outbox).

SQLite's single-writer-per-file constraint is a real limit; it is acceptable because leases already establish a single writer per domain, so the database constraint and the architectural constraint coincide.

**Rejected shortcut.** "One database file, a `kind` column, and application-level checks" is the natural implementation. It is prohibited: it makes fencing a race (D3), makes loss classification a judgement (D2), and makes append-only a convention (D9).

## Interfaces

`IC-001` (event bus), `IC-006` (memory), `IC-007` (task), `IC-009` (security/audit).

Contracts: `contracts/entities/lease.schema.json`, `contracts/entities/task.schema.json`, `contracts/entities/checkpoint.schema.json`, `contracts/events/event_envelope.schema.json`.

## Security

The three append-only stores are the system's memory of what it did. D9 places them outside the runtime's write capability for the same reason `GOVERNED_PATHS` is outside it: a system that can rewrite its own audit log can be wrong in a way nobody can later detect. Backups inherit the classification of their source store; a backup of `audit.db` on a `Z2` node is a `Z2` node holding class C data, which `INV-TRUST-1` forbids — so **`Z2` nodes host no store at all**.

## Failure modes

Power loss mid-transaction (WAL recovery); disk full; corrupted page; clock jump during checkpoint; simultaneous open by a stale ex-owner; upcaster absent for an old event version. Each is covered by `A-019`, `A-033`, `A-034` or `A-050`.

## Rollback

Every store is a single file; rollback is a file swap plus a forward log replay. Because the log is never rewritten (D4), rolling the *code* back does not require rolling the *data* back, provided the N/N-1 window in D5 is honoured.

## Acceptance tests

`A-019` (restore deliberately corrupted state from checkpoint), `A-033` (coordination fault injection), `A-034` (lease, failover, partition, fencing), `A-035` (outbox / exactly-once effective delivery), `A-050` (record loss and class boundaries).

## Acceptance authority

`AUTHORITY_AND_PRECEDENCE §5` assigns ADRs to *"Engineering; owner for security boundaries"*, and Baseline 02 §3 assigns ADR approval to the Chief Architect. This record was filed **PROPOSED**, not ACCEPTED, for one reason: the same pass that wrote it would otherwise be the pass that discharged `INV-ADR-1`, which is the F0 gate. A gate discharged by its own author is not a gate.

**ACCEPTED 2026-08-14 by the project owner** under `OWNER-DECISION-006(b)`, on evidence rather than on the record's own argument. `INV-ADR-1` is discharged and F0 is unblocked.

### The condition the acceptance was given under, and whether this record meets it

The owner's stated condition: *"as long as it ensures data isn't lost, even if one device got cut off from the network, and the other one came afterwards."* That is the partition-rejoin case, and it is the exact case `INV-OWN-3` and D3 exist for. Recorded here in full, because an acceptance is only as good as the shared understanding of what was accepted.

**What this design guarantees, precisely:**

- The cut-off device's queued work is **not discarded**. D7 replays it as ordinary writes subject to ADR-001 D4 supersession, and the writes enter `log.db`, which is append-only and never rewritten (`INV-SCHEMA-2`).
- Its writes are **not applied with owner authority** — that is the fencing (D3), and it is deliberate. A returning ex-owner must not be able to overwrite decisions taken in its absence.
- Where both devices changed the same key, the supersession rule decides and the older change is **superseded, not deleted**. `tombstones.db` (D2) carries an index entry for every durable record ever written, held in a *separate* store so that whatever destroys a record cannot also destroy the evidence it existed. `INV-LOSS-3` forbids presenting a known cause as forgetting.

**So the condition is met in the sense that matters — nothing vanishes, and nothing vanishes silently — with one refinement the owner should hold onto: a conflicting change made during the partition can be overruled. It is overruled visibly and on the record, never quietly.**

### Evidence the acceptance rests on

`SPIKE-008`, run 2026-08-14 on the first candidate node against this design. Seven of nine criteria closed:

| Criterion | Result |
|---|---|
| 1 — zero stale-epoch writes accepted, at 2, 4 and 8 concurrent writers | **PASS** |
| 2 — the mandatory non-compliant read-then-write control **fails** | **PASS** (it accepted 119 / 167 / 186 stale writes; the compliant build accepted 0) |
| 3 — zero torn transactions, 500 crash trials, all five stores | **PASS** |
| 4 — audit hash chain unbroken in every trial | **PASS** |
| 5 — checkpoint at `synchronous = FULL` under read load ≤ 200 ms p95 | **PASS** — 1.17 ms |
| 6 — checkpoint acknowledged before step completion (D6 ordering) | **PASS** |
| 7 — `UPDATE`/`DELETE` on append-only stores refused at the storage layer | **PASS** |
| 8 — read-time upcasting behaviour | **PASS 2026-08-16** — `core/codec.py`; non-compliant control fails as required |
| 9 — all five stores open on every candidate node class | **NOT RUN** — one node enrolled |

**The acceptance was explicitly on the seven criteria tested.** Criterion 8 has since been verified during F0 exactly as this clause anticipated: the codec is `core/codec.py`, the missing-upcaster path raises rather than dropping a field, stored bytes are unchanged after a read, and a body newer than the reader is refused rather than guessed at. Evidence: `docs/planning/spike-results/SPIKE-008-criterion8-upcasting.json`. **Criterion 9 remains open** and is verified on the second enrolled node; if it fails, this record is revised then, which is the same disposition §3 already carries. Report: `docs/planning/spike-results/SPIKE-008-adr002-validation.json`.

> **Note for the readiness gate.** ADR-001 and ADR-012 carry `Status: ACCEPTED` stamped in an earlier engineering pass under the same authority question. Either all three are confirmed together at the gate, or the acceptance of ADR-001/ADR-012 should be re-confirmed on the same basis. Recorded here rather than resolved, because it is the same authority question and should be answered once. See `OWNER-DECISION-006`.

## Open items

| # | Item | Disposition |
|---|---|---|
| 1 | Lease TTL, renewal interval, quorum size | Owner configuration (REM-002 §14). Bounded by *"never automatic on partition alone"*. |
| 2 | Backup retention depth and off-fabric copy | Operations decision; does not affect any interface. Raised at Phase 8. |
| 3 | Whether `workspace.db` caches are also backed up | Class A; default **no**. Cheaper to rebuild than to carry. Revisit if SPIKE-001 shows index rebuild cost exceeds the survival budget. |
