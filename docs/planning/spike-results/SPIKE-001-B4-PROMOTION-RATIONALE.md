# B4 — the first promotion into `capability_profiles.toml`, and why it is one line

**Recorded 2026-08-19 01:20, after the `v3` tier matrix completed on node 1.**

## What was available to promote

Twelve `SPIKE-001` §3.1 reports, all on **one checkpoint**, verified from the
server's own `build_info` rather than from the string passed to the harness:

| Tier | idle | concurrent |
|---|---|---|
| `draft` Qwen3-1.7B | 148.2 | 153.0 |
| `draft` Llama-3.2-3B | 96.9 | 100.1 |
| `small` Llama-3.2-3B | 100.2 | 101.0 |
| `standard` Qwen3-8B | 45.8 | 47.0 |
| `strong` Qwen3-30B-A3B MoE | 7.45 | 7.12 |
| `strong` Mistral-24B dense | 3.07 | 3.05 |

```
distinct builds across all v3 reports: {'b10405-e79e4bf66'}   SINGLE CHECKPOINT
```

That was `B2`'s entire purpose — three previously published MoE figures came
from three different checkpoints, which §3.1 forbids.

## The mistake this document exists to avoid

**`sustained_tokens_per_sec_min` is not a measurement. It is a requirement.**

The field asks what a node must sustain *to host a capability*. The table above
says what one node achieved. Copying the second into the first would produce a
file that looks measured, passes `CI-034`, and encodes nothing but "whatever
this desktop did in August" — with the added defect that the minimum would rise
or fall with the hardware, which is backwards. A capability's needs do not
change when you buy a better machine.

So a figure is promoted only where a **stated requirement** exists to derive it
from. Exactly one does today.

## The one promotion: `voice_interaction` = 7 tok/s

Derived from `contracts/policy/latency_budgets.toml`, which asserts its budgets
on the **minimum viable node, offline, FREE_TIME, local models only** — not on
the best machine while a paid API is reachable.

The binding constraint is not time-to-first-token. It is that **generation must
outpace speech delivery**, or the voice stalls mid-sentence:

```
natural speech            ~150 words/min  =  ~2.5 words/s
tokens per word (BPE)     ~1.3
break-even                ~3.25 tok/s        the voice keeps up with ZERO margin
2x headroom               ~6.5 tok/s      -> 7 tok/s
```

A generator running exactly at speech rate stalls on any hiccup — a longer
token, a scheduling pause, a cache miss. Two times is the smallest headroom
that survives ordinary jitter, and it is stated here so a later reader can
disagree with the multiplier rather than guess at it.

**The threshold discriminates, which is how you know it is doing work:**

| Measured tier | tok/s | Can host voice? |
|---|---|---|
| Mistral-24B dense | 3.05 | **No** — below break-even; the voice would stutter |
| Qwen3-30B-A3B MoE | 7.12 | Barely — above the floor, no comfort |
| Qwen3-8B | 45.8 | Yes, comfortably |
| Llama-3.2-3B | 100.2 | Yes |

That the 24B dense model cannot host voice on this node is a real, checkable
consequence, and it agrees with the bandwidth law: a model that does not fit in
7.2 GB of VRAM falls to DDR4 speed and cannot be talked to.

## What stays `UNKNOWN`, and why that is not laziness

| Capability | Why no number |
|---|---|
| `local_inference_small`, `local_inference_standard` | Their minimum would be the tier's own throughput, which is circular. SR-005 names the tiers; nothing states what a tier must sustain to count as delivered |
| `perception_vision` | `SPIKE-007`. Frame rate and model size are the constraints, and neither is measured |
| `control_plane_host`, `autonomous_actuation` | Bounded by lease and interlock timing, not by token throughput. `SPIKE-002` |
| The six survival-core capabilities | None is an inference capability. A token rate is not what they need, and inventing one would make the core harder to satisfy on the last device standing — the exact failure `INV-PLACE-3` exists to prevent |

`INV-HW-2` keeps every one of these `UNAVAILABLE` until measured. That is the
fail-closed behaviour and it stays.

## What `measured = true` now means in that file

It is a file-level flag and `CI-034` requires it before **any** capability may
carry a number. It does **not** claim every field is measured — 32 fields are
still honestly `UNKNOWN`. It claims that the values which are present are
backed by evidence and traceable to it.

## Owner review requested on one judgement

The **2× speech-rate headroom** is engineering's call and it is the only
invented number in this change. Everything else is either measured, derived
from a budget the owner already approved, or left `UNKNOWN`.

If the multiplier should be 1.5× (≈5 tok/s) or 3× (≈10 tok/s), that is a
one-line change with a real consequence: at 10 tok/s the MoE model stops
qualifying for voice on this node, and node 1 would host no voice-capable
strong-tier model at all.
