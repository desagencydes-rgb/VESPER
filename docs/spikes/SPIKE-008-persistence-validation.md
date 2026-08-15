# SPIKE-008 — Persistence engine validation against the ADR-002 constraint set

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Does the ADR-002 storage design actually deliver atomic epoch fencing, crash-safe checkpoints within budget, and readable stores on every node class? |
| **Time box** | 5 working days |
| **Owner** | Core Systems Engineer |
| **Depends on** | SPIKE-001 |
| **Raised by** | ADR-002, filed 2026-08-12 |
| **Blocks** | ADR-002 acceptance confidence · F0 increment 1 |

> The other seven spikes measure hardware and platforms. **This one measures whether a decision survives contact with them.** ADR-002 chose SQLite in WAL mode because `UPDATE … WHERE lease_epoch = ?` is a single atomic statement and is therefore the fencing primitive `INV-OWN-3` needs. That reasoning is sound on paper. Migration retrofitted onto durable data is the classic unrecoverable cost (GAP-046), so the paper is checked *before* F0, not during it.

---

## 1. Protocol

### 1.1 Fencing under concurrent writers (`INV-OWN-3`)

```
Two writer processes hold epochs E and E+1 against one state.db.
FOR 10 000 interleaved writes to the same leased domain:
    assert: EVERY write carrying epoch E is rejected (rowcount == 0)
    assert: EVERY rejection emits control.fenced
    assert: NO write carrying E is observable in the committed state
Repeat with 4 and 8 concurrent writers.
```

**Zero accepted stale-epoch writes is the pass condition.** A rate is not acceptable: the scenario this protects is a partitioned ex-owner rejoining, which happens rarely and matters absolutely.

Run the same suite against a **deliberately non-compliant implementation** that performs a read-then-write check instead of the single guarded statement. It must fail. If it passes, the test is measuring nothing — the same discipline every acceptance test in this corpus carries.

### 1.2 Crash safety

```
FOR 500 trials, FOR each store in {log, state, audit, tombstones, workspace}:
    1. Begin a write.
    2. Kill the process (SIGKILL) or cut power at a randomised point.
    3. Reopen.
    assert: the store opens
    assert: the last transaction is fully present or fully absent, never torn
    assert: audit.db prev_hash chain is unbroken
    assert: log.db contains no partial event
```

Power-cut trials on at least one candidate node, not only SIGKILL — a process kill does not exercise the disk cache the way a power loss does.

### 1.3 Checkpoint budget

Measure checkpoint commit at `synchronous = FULL` on the **minimum** profile, under concurrent read load. Budget **200 ms at p95** (`latency_budgets.toml`). Record p50 / p95 / max.

Also assert the **ordering** in ADR-002 D6: the checkpoint is acknowledged *before* the plan step is marked complete. Instrument both events and assert the sequence — an implementation that reverses them resumes having forgotten what it just did, and no latency figure would reveal it.

### 1.4 Append-only enforcement (ADR-002 D9)

Attempt `UPDATE` and `DELETE` against `log.db`, `audit.db` and `tombstones.db` through the runtime's own handle. **Every attempt must fail at the storage layer**, not at a policy check. Verify the handle exposes no such method and that the OS filesystem capability set excludes the write mode.

### 1.5 Read-time upcasting (ADR-002 D4/D5)

Write events at `schema_version = N-1`, register an upcaster, read at `N`. Assert: the stored bytes are **unchanged** after reading; the reader receives the upcast form; and a **missing** upcaster produces an explicit error rather than a silently-dropped field.

### 1.6 Portability

Open all five stores on every candidate node class from SPIKE-001, including the `foreground_only` one. Assert readability and byte-identical checksums after transfer — a store that is a portable artifact is what makes ADR-002 D10's survival carry possible.

## 2. Pass criteria

| # | Criterion |
|---|---|
| 1 | Zero stale-epoch writes accepted across all concurrency levels |
| 2 | The non-compliant read-then-write build **fails** 1.1 |
| 3 | Zero torn transactions across 500 crash trials, all five stores |
| 4 | Audit hash chain unbroken in every trial |
| 5 | Checkpoint commit ≤ 200 ms p95 on the minimum profile under load |
| 6 | Checkpoint acknowledged **before** step completion, verified by event order |
| 7 | Every `UPDATE`/`DELETE` against an append-only store fails at the storage layer |
| 8 | Missing upcaster raises; stored bytes never mutate on read — **PASSED 2026-08-16**, `docs/planning/spike-results/SPIKE-008-criterion8-upcasting.json`. Deferred until F0 existed; `core/codec.py` is the registry. Its non-compliant control (a codec that upcasts in place and returns the old form when no upcaster is registered) **fails as required**. |
| 9 | All five stores open on every candidate node class |

## 3. On fail

**ADR-002 is revised before F0 rather than discovered during it.** That is the entire purpose of running this spike ahead of implementation.

| Failing criterion | Disposition |
|---|---|
| 1 or 2 | The fencing primitive does not hold. `INV-OWN-3` is unenforceable as designed and ADR-002 D3 must change. This is a **blocking** revision. |
| 3 or 4 | Crash safety insufficient. Re-examine journal mode and `synchronous` settings; if unresolvable, D1's engine choice is revisited. Blocking. |
| 5 | Budget miss. Record the gap; do **not** relax the budget (`INV-PERF-1`). Options are the same as SPIKE-002's: optimise, or raise the minimum profile, or record a limitation. |
| 9 | A node class cannot host a store. It is then a presence endpoint only, never a survival host — which is a `capability_profiles` change, not a requirement change. |

## 4. Deliverables

1. Fencing results at every concurrency level, including the non-compliant control run.
2. Crash-trial results: 500 trials, per-trial pass/fail, no aggregation that hides a single tear.
3. Checkpoint latency distribution and the ordering assertion result.
4. Append-only enforcement evidence.
5. Upcaster behaviour on the missing-upcaster path.
6. Portability matrix across node classes.
7. Either a recommendation that ADR-002 be accepted as written, or the specific clauses requiring revision.
