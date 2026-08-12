# SPIKE-001 — Node capability profiles, measured

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | What can each candidate node actually sustain, and what is the minimum viable profile for SR-005 local fallback? |
| **Time box** | 5 working days per candidate node |
| **Owner** | Core Systems Engineer · Device/Network Engineer |
| **Blocks** | ADR-015 · the hardware purchase decision · SR-005 / SR-006 depth · SPIKE-002 · SPIKE-007 · SPIKE-008 |
| **Fills** | Every `UNKNOWN` in `contracts/policy/capability_profiles.toml` |

> **This spike informs the hardware purchase. It is not written to justify one.** If the measurements say no candidate sustains local inference, that is the finding, and the deliverable is a limitation record plus a hardware recommendation — not a smaller definition of "local fallback".

---

## 1. Why this must be measured, not read

`INV-HW-2`: *`sustained_tokens_per_sec` is measured at enrollment, never declared.* Three documents in this corpus asserted hardware agnosticism and none implemented it; `capability_profiles.toml` currently carries **31 fields honestly marked `UNKNOWN`**, and `CI-034` fails the file if any of them is filled in from a datasheet while `measured = false`.

Vendor figures are measured on idle machines running one benchmark. VESPER runs a resource governor, a world model, a perception pipeline and a persistence layer at the same time, on a laptop that is also the owner's working machine. **Sustained-under-load is a different number from peak**, and it is the only number the router can use.

## 2. Candidate nodes

Identified by **profile**, never by product name (`INV-HW-1`, `CI-007`). The inventory mapping lives in the device registry, not here.

| Ref | Profile shape | Expected role |
|---|---|---|
| N1 | unified memory, accelerator present, `always_on = false`, hardware-backed key storage | primary compute + control candidate |
| N2 | discrete accelerator, mains powered, `usually_on`, OS keystore | secondary / fallback control candidate |
| N3 | `foreground_only`, hardware-backed key storage, push-wake | presence endpoint; SPIKE-007 subject |
| N4 | low memory, file-based key storage → `Z2` | presence endpoint only; may hold no state |

## 3. Measurement protocol

Each measurement runs **three times**; the recorded value is the **median**, and the **spread** is recorded alongside it. A single run is an anecdote.

### 3.1 Sustained inference throughput

```
FOR each candidate node N, FOR each capability_tier T in {draft, small, standard}:
    1. Load the tier-representative model.
    2. Warm up: 200 tokens, discarded.
    3. Run a 10-minute continuous generation at the tier's expected context length.
    4. Record: tokens/sec at minute 1, minute 5, minute 10.
    5. Record: thermal state and clock throttling at each interval.
    6. sustained_tokens_per_sec := the MINUTE-10 value, not the minute-1 value.
```

> **Minute 10, not minute 1.** A thermally-throttled laptop delivers a different number after ten minutes than after ten seconds, and VESPER's overnight work runs for hours. Recording the peak would be measuring a machine that does not exist during the workload that matters.

**Concurrent-load variant, mandatory.** Repeat step 3 with a synthetic background load representing the resource governor, world model and persistence layer. Record both figures. **The router uses the concurrent figure.**

### 3.2 Memory headroom (SR-057)

```
FOR each candidate node N:
    1. Record total memory and memory available with the owner's ordinary
       working set loaded (browser, editor, whatever they actually run).
    2. Load the largest tier that fits in the REMAINING headroom.
    3. Assert: zero swap activity during a 10-minute run.
    4. Record the largest tier that satisfies the zero-swap assertion.
```

SR-057 says *fit in memory headroom, avoid swap*. Headroom is measured against the **owner's real working set**, not against an idle machine — the machine is theirs first.

### 3.3 Storage, and the five stores (ADR-002 D2)

Record for each node: available storage; whether all five stores open; sequential and random write throughput; and **whether a `synchronous = FULL` commit completes within the 200 ms checkpoint budget**. Hand the last figure to SPIKE-008.

### 3.4 Network and reachability

Record: LAN round-trip p50/p95; behaviour across sleep/wake; time from wake to reachable; and observed availability over a **7-day passive window**. The last one produces `availability_class`, and it must be observed rather than assumed — `availability_class` is the field that separates *trust* from *availability*, the distinction `OWNER-DECISION-002` turned on.

### 3.5 Camera and audio

Record per node: capture resolution and frame rate under load; microphone quality with the owner at conversational distance; whether wake-word detection runs continuously without material battery cost; whether a hardware capture indicator exists and **whether it can be driven by software** (`INV-PRIV-4` requires a guaranteed-off path software cannot override — a node without one cannot host a sensor in `ACTIVE`).

### 3.6 Thermal and power

Record: sustained load before throttling; noise at sustained load; battery drain per hour at the sustained figure; and whether the node stays usable **for the owner** during it. A node that must become unusable to be useful is not a compute node — SR-057 requires asking before closing the owner's applications, and the same principle applies to making the machine too hot to work on.

## 4. Pass criteria

| # | Criterion |
|---|---|
| 1 | Every `UNKNOWN` in `capability_profiles.toml` carries a measured value for **at least one** candidate node |
| 2 | **At least one node meets the declared minimum for `local_inference_small`** — the SR-005 fallback |
| 3 | At least one node meets `control_plane_host`, including `always_on` |
| 4 | Every node has an observed `availability_class` from the 7-day window, not a declared one |
| 5 | The declared **minimum viable profile** is derived from the measurements and written back into `capability_profiles.toml` with `measured = true` |
| 6 | Every measured figure records median **and spread** across three runs |

## 5. On fail

**If criterion 2 fails** — no candidate sustains `local_inference_small` — SR-005's local fallback does not close on available hardware.

Deliverable: a **COC Part XIV.3 limitation record** naming the shortfall in measured units, plus a hardware recommendation stating the profile that would close it.

**Not permitted:** redefining "local fallback" to mean a smaller model than the one the requirement needs; reporting the peak figure instead of the sustained one; reporting the idle figure instead of the concurrent one; or measuring on a machine that is not a candidate.

**If criterion 3 fails** — no node can host the control plane always-on — that is a finding about the fabric, not about the requirement. `INV-TRUST-2` already forbids designing continuity-critical capability onto a `foreground_only` node, so the honest outcome is that the fabric needs an always-on member.

## 6. Deliverables

1. `capability_profiles.toml` with measured values and `measured = true`.
2. A per-node measurement record with median, spread and conditions for every figure.
3. The declared **minimum viable profile**, derived not chosen.
4. A hardware recommendation, if any criterion fails.
5. Limitation records for anything that does not close.

## 7. Verification that this spike was done honestly

- `CI-034` fails if any figure is present while `measured = false` — so the file cannot be filled in ahead of the measurement.
- Every figure is reproducible from the recorded protocol and conditions.
- `A-042` consumes the profile matrix, so a fabricated profile fails a later test rather than passing quietly.
- **The concurrent-load figure and the idle figure are both recorded.** Recording only the favourable one is the failure mode this section exists to make visible.
