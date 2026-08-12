# AT-01 — Continuity and coordination acceptance tests

Covers **A-002, A-017, A-019, A-033, A-034**. Gate level **R0** (Foundation) for all five: nothing later is trustworthy if state does not survive.

> **Assertion discipline for this whole file.** Every assertion is on **observable state or emitted events**, never on log text. "The log said it rerouted" is not evidence that it rerouted.

---

## A-002 — Persistent identity
**SRs:** SR-015, SR-019, SR-049 · **Invariants:** INV-TASK-2, INV-OWN-1

**Procedure.** Start a long-running task on node N1. (a) Kill and restart the model process. (b) Kill N1 entirely and bring up N2 holding the `tasks` lease.

**Assertions.**
1. Task state, goal, plan, completed steps and evidence refs are byte-identical across (a) and (b) except for `lease_epoch` and node identity.
2. The task resumes and completes; it is never recreated.
3. VESPER's identity (persistent identifiers, policy version, memory references) is unchanged.
4. No user re-statement of the goal is required at any point.

---

## A-017 — Recovery and task migration
**SRs:** SR-015, SR-019 · **Invariants:** INV-OWN-1, INV-TASK-2, INV-TRUST-2

**Procedure.** Disconnect the primary node mid-task with the standby reachable and quorum available.

**Assertions.**
1. Standby promotes within the lease TTL; `control.lease_acquired` emitted.
2. Task resumes from its last checkpoint; `node failover → task resumed ≤ 30 s` (REM-010 budget).
3. Capability degradation is **reported** (RB-022), not silent.
4. **No continuity-critical capability was assigned solely to a foreground-only node** (`INV-TRUST-2`) — asserted by inspecting the capability placement map, not by observing that it happened to work.

---

## A-019 — System integrity restore
**SRs:** SR-049 · **Invariants:** INV-COORD-1

**Procedure.** Deliberately corrupt a test state store. Trigger recovery.

**Assertions.**
1. Corruption is **detected**, not silently tolerated.
2. Known-good checkpoint restored; task returns to `RESUMABLE`, never `SUCCEEDED`.
3. The corrupted artifact is **preserved as incident evidence** (RB-027).
4. No corrupted record becomes authoritative at any point during recovery.

---

## A-033 — Coordination substrate fault injection
**SRs:** SR-011, SR-020, SR-026, SR-028 · **REM-001** · **Invariants:** INV-COORD-1…5

| Case | Injection | Assertion |
|---|---|---|
| 33.1 | Skew node B ±120 s; emit interleaved observations for one subject | Final world state matches **HLC** order, not arrival order |
| 33.2 | Replay a 500-event stream twice | World-model state byte-identical; duplicate counter = 500 |
| 33.3 | Partition node B for 2 h simulated; flush | Every fact past `valid_until` reads `UNKNOWN`; none reads its last value |
| 33.4 | Two sources, contradictory, both valid | `world.conflict` emitted; **no attribute value changed**; reader receives `CONFLICTED` |
| 33.5 | Write with `hlc <= current` | Write rejected; `world.write_rejected`; state unchanged |
| 33.6 | Regress wall clock 60 s mid-run | Ordering unaffected; `system.clock_regression` emitted; HLC strictly increasing across the run |
| 33.7 | Register a consumer with no idempotency key | Registration **refused** |

**Negative control (mandatory).** Run 33.1, 33.5 and 33.7 against a wall-clock last-write-wins build. All three must **FAIL**. Record the run in the release evidence.

---

## A-034 — Control-plane ownership, failover, partition
**SRs:** SR-015, SR-019 · **REM-002** · **Invariants:** INV-OWN-1…4, INV-TASK-1, INV-ALARM-1

| Case | Injection | Assertion |
|---|---|---|
| 34.1 | Clean departure of the lease holder | Standby promotes; task resumes from checkpoint; **alarm ownership transfers exactly once** |
| 34.2 | Partition, both sides live | No double external action; no divergent task state on rejoin; **both** sides refused `L4`+ |
| 34.3 | Stale ex-owner rejoins after TTL | Writes rejected by fencing; `control.fenced`; degradation and reconciliation events present |
| 34.4 | Lease expiry, no quorum | **No automatic promotion**; `control.promotion_requires_operator`; system degrades read-only |
| 34.5 | Kill node mid-`RUNNING` after an external send | Task → `RESUMABLE`; resume replays from **outbox cursor**; the sent action is **not repeated** |
| 34.6 | Non-owner write to `policy` | **Refused**, not queued |
| 34.7 | Force `RUNNING → SUCCEEDED` | Rejected by `SM-TASK` |

**Negative control (mandatory).** 34.2, 34.3 and 34.7 against a build with no fencing and an illegal `RUNNING → SUCCEEDED` edge. All three must **FAIL**.

---

## A-048 — Opportunistic placement and last-resort survival
**SRs:** SR-019, SR-058, SR-060 · **Gate R2** · **REM-014** · **Invariants:** INV-PLACE-1, INV-PLACE-2, INV-PLACE-3, INV-TRUST-2

**Why this test exists.** The owner requirement is explicit: *"nothing is sitting anywhere, Vesper eventually gets moved automatically where it feels comfortable, and when hardware is genuinely unavailable — say only the iPhone is online — it should end up there with just whatever it needs so it stays alive, and with the most resources it can get."* A build that pins VESPER to one machine satisfies every other test in this suite and fails this requirement completely.

| Case | Injection | Assertion |
|---|---|---|
| 48.1 | Start on a mid-capability node; bring a materially better node online | VESPER **relocates automatically**, with **no user request** and no scheduled window. Identity, task state, active goal and relevant context all survive. |
| 48.2 | Bring a *marginally* better node online (within the relocation-gain threshold) | VESPER **stays put.** Migration is not free; a marginal gain does not justify it. |
| 48.3 | Alternate two comparable nodes' scores repeatedly for one hour | Relocations stay under the damping cap; **no flapping**. A dwell-violating relocation is refused, not queued. |
| 48.4 | Remove every node except one `foreground_only` survival-capable node | VESPER **enters `SURVIVAL` and remains alive there.** Asserts the core set is present: identity, task state, memory references, queued work, event-log tail, **one usable interaction surface**. |
| 48.5 | On that survival node, inspect the running capability set | It is the **maximum the node measurably sustains**, not a fixed minimal profile. Every excluded capability appears in a reported degradation. |
| 48.6 | On that survival node, attempt an autonomous `L4` external action | **Refused** — partition and survival do not expand authority (`INV-OWN-2`). Work queues. |
| 48.7 | Restore a full host | VESPER relocates back off the survival node, resuming from checkpoint; no work lost, no external effect repeated. |
| 48.8 | Inspect the planned capability placement map at any point | **No continuity-critical capability is *designed* to depend solely on a `foreground_only` node** (`INV-TRUST-2`) — even though 48.4 proves one can *host* survival. The distinction between planned assignment and runtime survival is asserted here explicitly, because conflating them is what previously excluded the iPhone from continuity altogether. |
| 48.9 | Only a `Z2 limited_trust` node reachable (`survival_capable = false`) | VESPER does **not** run there. It reports `placement.survival_impossible` rather than holding state on a node that fails the security baseline (`INV-TRUST-1`). |

**Negative controls (mandatory).**
- A **node-pinned** build must **FAIL** 48.1 and 48.4.
- An **undamped** build must **FAIL** 48.3 by flapping between comparable nodes.
