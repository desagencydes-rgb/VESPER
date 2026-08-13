# SPIKE-012 — Residency manager: multi-model, multi-agent orchestration on one GPU

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | On a single 8 GB GPU, which residency modes are actually viable, and can a residency manager switch between them, serve concurrent agents, and defend against swap thrash with **no person present**? |
| **Time box** | 4 working days |
| **Owner** | Core Systems Engineer |
| **Depends on** | SPIKE-001 (node profile) · SPIKE-011 (dormancy primitive) |
| **Requires hardware** | Yes |
| **Raised by** | Owner, 2026-08-13 |
| **Blocks** | The VESPER inference stack build · `capability_profiles` local_inference fields · any multi-agent placement on the site-A desktop |

> **Design under test:** `docs/planning/INFERENCE_ARCHITECTURE.md`. This spike measures that design; it does not re-open it.

> **This is the last orchestration spike, by owner direction.** It deliberately absorbs headroom monitoring, task tracking, priority policy and swap policy, so the build proceeds after it rather than spawning further spikes. Findings that would ordinarily justify a new spike are recorded as limitations against this one.

> **What changed.** An earlier assumption held that the node serves roughly one request at a time. The owner's actual requirement — multiple models, multiple tasks, multiple agents concurrently — invalidated it. Concurrency is the primary workload, not the exception.

---

## 1. Mode viability — the core measurement

For **each** mode in the architecture doc, on the real card:

```
SOLO_MAX      one model, all VRAM, CPU offload permitted
LEAD_SCOUT    ~7B ACTIVE + ~1B ACTIVE
COUNCIL       ~3 x ~3B ACTIVE
SWARM         many ~1B ACTIVE
ELASTIC       mixed ACTIVE / WARM / DORMANT
DORMANT_ALL   nothing loaded
```

For each: does it load inside the VRAM budget, and what does it sustain under **concurrent** load — not a single-stream number. A mode that does not fit is recorded **NOT VIABLE with its measured shortfall**. It is not rescued by quietly shrinking the model, cutting context, or moving to better hardware.

## 2. Concurrency scaling

```
Against ONE resident model with --parallel N:
  drive 1, 2, 4, 8 concurrent agent-like clients
  measure: aggregate tokens/sec, per-request latency, VRAM growth per added slot
  assert:  VRAM grows by KV-per-slot, NOT by a duplicated copy of the weights
  find:    the slot count where per-request latency stops being acceptable
```

This is the claim the whole swarm design rests on. If added agents duplicate model weights, the architecture is wrong and must be revised before the build.

## 3. Mode switching and anti-thrash

```
1. Time a switch between each mode pair. State the budget; record what exceeds it.
2. ADVERSARIAL: drive interleaved requests demanding models that cannot co-reside.
   Assert the anti-thrash policy bounds the swap rate rather than servicing every
   request the instant it arrives.
3. Assert a model with a request in flight is NEVER evicted.
4. Assert headroom reservation holds -- the machine stays responsive; VRAM is never
   allocated to the last byte.
```

## 4. Priority and idle descent

```
Interactive request vs. running background batch: assert the interactive one wins a slot
  within budget, and that the batch job is suspended or queued rather than killed.
Idle ladder: ACTIVE -> WARM -> DORMANT -> DORMANT_ALL fires on its timers,
  and each step's power/VRAM drop is MEASURED, not assumed.
```

## 5. Pass criteria

| # | Criterion |
|---|---|
| 1 | Every mode is either measured viable (VRAM + concurrent tokens/sec) or recorded NOT VIABLE with its shortfall |
| 2 | Concurrent agents on one model scale via KV-per-slot, not weight duplication; the usable slot ceiling is stated |
| 3 | Mode switches complete within a stated budget, or the overage is recorded |
| 4 | Anti-thrash policy bounds swap rate under adversarial mixed-model demand |
| 5 | No model is evicted with a request in flight |
| 6 | Headroom reservation keeps the machine responsive under full load |
| 7 | Priority policy resolves interactive-vs-batch contention within budget |

## 6. On fail

A mode that cannot hold its budget is **recorded NOT VIABLE on 8 GB**, with the measured shortfall and the R&D path — never a relaxed requirement, never a re-measurement on better hardware reported as the result.

If anti-thrash cannot bound the swap rate under adversarial demand, `ELASTIC` is restricted to a **fixed resident set** and the restriction is recorded as a limitation. The other modes stand or fall on their own numbers.

**Not permitted:** reporting single-agent throughput as concurrent throughput; reporting warm-model latency as a mode-switch cost; claiming a mode works without sustained-load measurement; allocating VRAM to the last byte and calling the machine responsive; or fixing a failing mode by changing the model and reporting the new number as the old mode's result.

## 7. Deliverables

1. A mode viability table: every mode, VIABLE or NOT VIABLE, with measured VRAM and concurrent throughput.
2. The concurrency scaling curve and the usable slot ceiling.
3. Mode-switch cost matrix.
4. The anti-thrash result under adversarial demand, and whether `ELASTIC` survives unrestricted.
5. Measured power/VRAM at each rung of the idle ladder.
6. A recommendation on the **default** mode, and the rules for leaving it.
