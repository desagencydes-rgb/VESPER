# REM-014 — Opportunistic placement and last-resort survival

| | |
|---|---|
| **Implements** | **SR-060** (COC v1.2 additive) · SR-058 · SR-019 |
| **Origin** | Project-owner requirement, 2026-08-12, recorded during `OWNER-DECISION-002` |
| **Owner** | Device/Network Engineer · Core Systems Engineer |
| **Blocked by** | REM-002 (leases, checkpoints), REM-011 (`NodeCapabilityProfile`) |
| **Blocks** | Nothing. It sharpens placement rather than gating any other correction. |

---

## 1. Problem

The corpus assigned VESPER a **home**. Baseline 05 §11 makes the MacBook *"a first-class VESPER node"*, §12 makes the desktop the *"primary heavy-compute candidate"*, and SR-019 makes the MacBook *"main space"*. Migration was specified as a **failure response** — something that happens when a node is lost.

The owner's requirement is the opposite posture:

> *"nothing is sitting anywhere, Vesper eventually gets moved automatically where it feels comfortable, and when hardware is genuinely unavailable — say only the iPhone is online — it should end up there with just whatever it needs so it stays alive, and with the most resources it can get, not everything obviously, but at least the maximum it can get."*

Three defects follow from the home-node posture:

**(a) Placement was static.** Nothing continuously asks *"is this still the best place to be?"* A build that pins VESPER to one machine passes every other test in the suite.

**(b) The last-resort case was specified as an exclusion, not a mode.** REM-011 correctly forbade assigning continuity-critical capability *solely* to a foreground-only node — and, read carelessly, that reads as *"the iPhone can never keep VESPER alive"*. When the iPhone is the only thing online, the correct behaviour is not to be absent. **Ceasing to exist because the preferred hardware is missing is a failure, not a degradation.**

**(c) Degraded operation had no capability rule.** "Degraded mode" was named repeatedly and never quantified. A fixed minimal profile wastes a capable node; running everything overloads a weak one.

## 2. The distinction that resolves (b)

Two properties were conflated into one:

| Axis | Question | Example |
|---|---|---|
| `trust_zone` | *May this node be relied on?* | The J3 fails the security baseline → `Z2`, may render and observe only |
| `availability_class` | *How reliably is it awake?* | The iPhone has Secure Enclave key storage and is fully trustworthy → `Z0`, but iOS restricts background execution → `foreground_only` |

> **These are different problems with different answers.** The iPhone is *trustworthy but intermittently awake*. Conflating the axes produced a rule that excluded it from continuity entirely, when the correct rule excludes it only from being the **planned sole home** of a continuity-critical capability — not from **hosting survival** when it is all that remains.

`INV-TRUST-2` is restated accordingly: it constrains **designed assignment**, not **runtime survival**. `A-048.8` asserts the planning half; `A-048.4` asserts the survival half. Both must pass.

## 3. Required behaviour

### 3.1 Opportunistic placement — `DF-PLACE`

VESPER is **not pinned**. Placement is re-evaluated continuously — on every node-availability change and on a slow tick — and relocation is **automatic and unprompted**.

```
hosts = nodes with trust_zone in {Z0, Z1}
best  = best_by(hosts, [availability_class_rank, sustained_throughput,
                        accelerator_memory, network_class])
```

**Damped, exactly like the resource governor** (REM-012 §5), and for the same reason:

| Rule | Value | Why |
|---|---|---|
| `RELOCATE_GAIN` | 1.25 | A marginally better node does not justify a migration; migration is not free |
| `MIN_DWELL` | 10 min | Prevents flapping between comparable nodes |
| Degradation or loss of the current host | **bypasses both** | Getting off a dying node is urgent; getting onto a slightly nicer one is not |

> This is the placement analogue of REM-007: the decision is a **deterministic predicate over measured node state** — never a model call, never a schedule. A "nightly re-placement job" would be the same anti-pattern as cron autonomy.

### 3.2 Survival mode

When **no** `Z0`/`Z1` host is reachable, VESPER enters `SURVIVAL` on the best `survival_capable` node rather than ceasing to exist.

**Core set — always present, non-negotiable:**

```
identity · task state · memory references · queued work
· event-log tail · one usable interaction surface
```

That last item matters: a VESPER that is alive but unreachable has not survived in any sense the owner cares about.

**`survival_capable` requires `Z0` or `Z1` trust and durable local storage.** A `Z2` node may **not** host survival — `INV-TRUST-1` holds without exception, because a node that fails the security baseline holding VESPER's identity and task state is a worse outcome than a temporary absence. In that case VESPER emits `placement.survival_impossible` and waits. **This is the one case where absence is correct**, and it is reported rather than silent.

### 3.3 Maximum sustainable capability — `DF-SURVIVAL-PROFILE`

> *"Not everything obviously, but at least the maximum it can get."*

```
set = core
for cap in ordered_by_value(all_capabilities):
    if fits(set + cap, node, pressure) and meets_minimum_profile(cap, node):
        set += cap
```

`fits` uses **measured** values (`INV-HW-2`), so two nodes with identical spec sheets and different thermal behaviour get different answers — which is the entire reason enrollment measures rather than declares. **Every excluded capability is reported as a degradation** (RB-022, DR-021); the owner is never left to infer what is missing.

### 3.4 Authority does not expand under survival

Survival is a **capability** state, not an **authority** state. On a survival node:

- autonomous `L4`+ external actions remain **refused** (`INV-OWN-2` — a lone node cannot deduplicate against what the others did);
- the enable token is still required (`INV-STOP-1`);
- self-modification remains impossible (`INV-SELF-1`).

Scarcity is never an argument for more authority. It is the situation in which a compromised or confused system is least observable, so the bar does not drop.

## 4. Ownership and authority

| Concern | Owner | Authority |
|---|---|---|
| `DF-PLACE`, damping constants | Device/Network Engineer | `E2`; constants are owner-tunable configuration |
| `DF-SURVIVAL-PROFILE`, core-set definition | Core Systems Engineer | `E2`; **the core set is architectural**, not tunable |
| `survival_capable` per node | Enrollment (measured + baseline) | Not self-declarable by the node |
| Relocation execution | Automatic, no human in the loop | Deliberate — `INV-PLACE-1` |

## 5. Interfaces

| Interface | Change |
|---|---|
| `IC-004` Device | `NodeCapabilityProfile` gains `availability_class`, `survival_capable`, and `trust_zone` as a **separate** field |
| `IC-007` Task | `Checkpoint` gains `survival_carry` — task state is core; large derived artifacts are not |
| New events | `placement.relocated` · `placement.survival_entered` · `placement.survival_impossible` · `placement.degraded_capability_set` |

Contracts: `contracts/entities/node_capability_profile.schema.json`, `contracts/entities/checkpoint.schema.json`.

## 6. Invariants

| ID | Statement |
|---|---|
| **INV-PLACE-1** | VESPER is not pinned to any node. Placement is re-evaluated continuously and relocation to a better available host is automatic and unprompted. |
| **INV-PLACE-2** | Relocation is damped by a minimum dwell and a relocation-gain threshold. Degradation or loss of the current host bypasses both. |
| **INV-PLACE-3** | With no full host reachable, VESPER enters `SURVIVAL` on the best `survival_capable` node carrying the core set plus the maximum additional capability that node measurably sustains. Every excluded capability is reported. |
| **INV-TRUST-2** *(restated)* | No continuity-critical capability is **designed** to depend solely on a `foreground_only` or `on_demand` node. This constrains planned assignment, **not** runtime survival. |
| **INV-TRUST-1** *(unchanged)* | A `Z2` node may not hold state — including under survival. |

## 7. Failure behaviour

| Failure | Behaviour |
|---|---|
| Every host lost, one survival node remains | `SURVIVAL` entered; core set carried; degradation reported |
| Every host lost, only a `Z2` node remains | `placement.survival_impossible`; VESPER does **not** run there; state stays where it was last durable |
| Core set does not fit the survival node | Attempt anyway, report the shortfall; do not silently run partial |
| Relocation fails mid-migration | Roll back to source; if the source is gone, the task is `RESUMABLE` and restores on the next viable host |
| Two nodes flap in score | Damping holds; `placement.flap_suppressed` if the cap is reached |
| Survival node goes to background (iOS) | Work suspends, state is durable; resumes on foreground or on a better host appearing — **this is expected, not an incident** |

## 8. Recovery

Recovery is a relocation. When a full host returns, `DF-PLACE` moves VESPER back and resumes from checkpoint, with the outbox cursor preventing repeated external effects (`INV-TASK-2`). No separate "exit survival" procedure exists, deliberately — a path exercised only in incidents is a path that does not work.

## 9. Verification

**`A-048`**, nine cases (see `verification/acceptance/AT-01`). The two that carry the requirement:

- **48.4** — with only a `foreground_only` node reachable, VESPER **stays alive** with the core set and a usable interaction surface.
- **48.5** — the running capability set is the **maximum the node measurably sustains**, not a fixed minimum, with every exclusion reported.

**Negative controls (mandatory).** A **node-pinned** build must FAIL 48.1 and 48.4. An **undamped** build must FAIL 48.3 by flapping.

## 10. CI enforcement

`CI-034` (`measured-not-declared`) and `CI-035` (`z2-capability-bound`) already cover the profile and trust halves. A new `CI-045 placement-not-pinned` — structural: no code path selects a host by node identity rather than through `DF-PLACE` — is registered as `PENDING` until the placement module exists.

## 11. Unresolved decisions

| # | Item | Disposition |
|---|---|---|
| 1 | `RELOCATE_GAIN` and `MIN_DWELL` values | Owner-tunable. The *requirement that damping exist* is architectural. |
| 2 | Whether the J3 can ever be `survival_capable` | **No** while it fails the security baseline (`Z2`). Revisit only if its baseline changes. |
| 3 | iOS background-execution envelope for survival duration | **SPIKE-007** (new): how long can a foreground-only node sustain the core set, and what is the durable-state guarantee across suspension? |

## 12. Jarvis-divergence check

> *Could an implementation agent satisfy REM-014 while building an ordinary chatbot?*

**No.** Clause: **`INV-PLACE-1` — VESPER relocates itself between physical machines, unprompted, while retaining identity, task state and active goal.** A chatbot runs where it is deployed; "where it feels comfortable" is not a question its architecture can ask. And **`INV-PLACE-3`** — surviving on the last device standing with a measured maximum capability set — presupposes a system that continues to *exist* between requests. There is nothing for a request-scoped system to keep alive.
