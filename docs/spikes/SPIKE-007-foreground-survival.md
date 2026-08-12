# SPIKE-007 — Foreground-only survival envelope

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | How long can a `foreground_only` node sustain the `INV-PLACE-3` survival core, and what is the durable-state guarantee across OS suspension? |
| **Time box** | 5 working days |
| **Owner** | Device/Network Engineer |
| **Depends on** | SPIKE-001 |
| **Raised by** | `REM-014` §Unresolved decisions, item 3 |
| **Blocks** | SR-060 depth on foreground-only nodes · `A-048` survival cases · `capability_profiles.background_continuous_operation` |

> **The distinction this spike protects.** `OWNER-DECISION-002` separated **trust** from **availability**: a node can be fully trusted (`Z0`) and only intermittently awake. Fusing the two is what previously excluded the phone from the fabric entirely. This spike measures the *availability* half — and it is measured, because a survival guarantee resting on an assumption about an OS scheduler is not a guarantee.

---

## 1. What is actually being asked

`INV-PLACE-3`:

> When no full host is reachable, VESPER enters `SURVIVAL` on the best `survival_capable` node **rather than ceasing to exist**, carrying identity, task state, memory references, queued work and one interaction surface, plus the maximum additional capability that node can measurably sustain.

On a `foreground_only` node the OS may suspend or terminate the process at its discretion. Three things must therefore be measured, and none can be read from documentation:

1. **How long** the survival core keeps running before the OS intervenes.
2. **What survives** the intervention — specifically, whether a durable write in flight completes or tears.
3. **How fast** it comes back when woken.

## 2. Why documentation is not sufficient

Platform documentation describes *policy*, not *behaviour under this workload*. Background execution allowances depend on battery level, thermal state, user habits, recent foreground time, and heuristics that change between OS releases. A stated allowance of *N* seconds is an upper bound under favourable conditions, and survival is not a favourable condition — **VESPER reaches this node precisely when everything else has failed**, which usually means the owner is asleep and has not touched the device for hours.

## 3. Protocol

### 3.1 Background execution envelope

```
FOR each foreground_only candidate, FOR each condition C in
    { battery 100% plugged, battery 50%, battery 15%,
      device idle 8h, device active in last 5 min,
      thermally warm }:

    1. Bring VESPER to SURVIVAL on the node with the survival core loaded.
    2. Send the device to background (screen off, no user interaction).
    3. Emit a heartbeat every 10 s to a witness node.
    4. Record: time from backgrounding to the LAST heartbeat received.
    5. Record: whether the process was suspended (resumable) or terminated.
    6. Repeat 5 times per condition. Report median AND minimum.
```

> **Report the minimum, not only the median.** A survival guarantee is a floor. The median is what usually happens; the minimum is what the guarantee can honestly promise.

### 3.2 Durable-write guarantee across suspension

This is the measurement that matters most, because a torn write is worse than a stopped process.

```
FOR 200 trials:
    1. Begin a checkpoint transaction (ADR-002 D6, synchronous = FULL).
    2. Force suspension at a randomised point within the transaction window.
    3. On restore, assert: the checkpoint is EITHER fully committed OR
       fully absent. NEVER partial.
    4. Assert: the audit chain in audit.db is unbroken (ADR-002 D8).
    5. Assert: tombstones.db is consistent with state.db.
```

**Zero torn writes is the pass condition, not a low rate.** A torn checkpoint on the last device standing is exactly the situation `INV-LOSS-4` addresses — *forgetting is permitted; pretending the work happened is not* — and a class C integrity loss on a survival node is the worst reachable outcome in the system.

### 3.3 Wake and restore

```
FOR each wake mechanism available on the platform (push, timer, connectivity,
                                                   user interaction):
    1. Suspend as in 3.1.
    2. Trigger the wake mechanism.
    3. Record: wake to process running; running to survival core loaded;
       loaded to first heartbeat; loaded to interaction surface responsive.
    4. Compare against the node_failover_task_resumed budget (30 000 ms).
```

### 3.4 Sustainable capability set

With the node in `SURVIVAL` under background constraints, determine which entries in `capability_profiles.toml` remain sustainable, and feed the answer to `DF-SURVIVAL-PROFILE`. Record each **excluded** capability explicitly — `INV-PLACE-3` requires every exclusion to be reported as a degradation, so the list is a product output, not a test artifact.

### 3.5 Battery honesty

Record battery drain per hour while sustaining the survival core. **A survival mode that flattens the owner's phone overnight has failed differently, not succeeded.** If drain exceeds a rate that would leave the device unusable by morning, the sustainable set must shrink and the shrink must be reported.

## 4. Pass criteria

| # | Criterion |
|---|---|
| 1 | A measured **minimum** background-execution duration for every condition in 3.1 |
| 2 | **Zero torn durable writes** across 200 suspension trials |
| 3 | Audit chain and tombstone consistency intact in every trial |
| 4 | At least one wake mechanism restoring the survival core within the 30 s failover budget |
| 5 | A measured sustainable capability set, with every exclusion enumerated |
| 6 | Battery drain leaving the device usable after an 8-hour survival window |

## 5. On fail

| Failing criterion | Disposition |
|---|---|
| **2 or 3** (torn writes / broken integrity) | **The node class is not `survival_capable`.** No amount of capability tuning fixes a storage layer that tears. Record it, remove the class from `survival_capable`, and re-run after an ADR-002 revision. This finding would also feed straight back into SPIKE-008. |
| 1 (short duration) | Not a failure of SR-060. Record the measured envelope; `DF-SURVIVAL-PROFILE` shrinks the set accordingly. SR-060 asks for the **maximum the device can sustain** — a measured smaller set satisfies it; a silent smaller set does not. |
| 4 (slow wake) | Record as a degradation against the failover budget. Do **not** relax the budget (`INV-PERF-1`). |
| 6 (battery) | Shrink the sustainable set until drain is acceptable, and report the shrink. |

**Not permitted:** claiming a survival guarantee that the measurements do not support; reporting the plugged-in figure as the envelope; or treating a suspension as equivalent to a graceful shutdown.

## 6. Deliverables

1. Background-execution envelope table: median and **minimum** per condition.
2. Torn-write trial results — 200 trials, pass/fail per trial, no aggregation that hides a single failure.
3. Wake-and-restore timings per mechanism.
4. The sustainable capability set, and the enumerated exclusions.
5. `capability_profiles.background_continuous_operation.max_suspension_tolerance_s`, measured.
6. Limitation records for anything unmet.

## 7. Relationship to `A-048`

`A-048` asserts that VESPER enters `SURVIVAL` rather than ceasing to exist, carries the core set, and reports every excluded capability. Its negative controls are a **node-pinned build** and an **undamped build that flaps**. This spike supplies the *ground truth* that makes `A-048`'s survival cases runnable: without a measured envelope, `A-048` can only assert that the code path exists — and a code path that has never met a real OS suspension is not evidence of survival.
