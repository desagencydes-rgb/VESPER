# VESPER — Qwen3.8-27B evaluation (planning, ESTIMATED not measured)

**Status: PLANNING.** Outside the normative set, like the rest of `docs/planning/`. It records
a model-adoption question and the evidence behind it. **Nothing here may enter
`contracts/policy/capability_profiles.toml`** — every performance figure below is either a
third-party benchmark or a projection, and `CI-034` fails a build that fills a capability
profile from either. This model enrols by measurement or not at all.

Evaluated: 2026-08-16. Node in question: **node 1**, the strong desktop
(Ryzen 5 5500 · 15.9 GB DDR4 · RX 6650 XT 8 GB VRAM).

---

## 1. The claim, checked

**It is real, and the claim is accurate.** Released **2026-08-05** under **Apache 2.0**;
community GGUFs appeared 08-13/14. Hugging Face: `Qwen/Qwen3.8-27B`.

| Property | Value |
|---|---|
| Parameters | 27B, **dense** (not MoE) |
| Layers | 64 |
| Architecture | `16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))` — hybrid linear attention, 3:1 |
| Context | 262 144 native, extensible to ~1M via YaRN |
| Modality | **Native vision-language** — images and video, not a bolted-on adapter |
| License | Apache 2.0 |
| Family | Only 27B, 2.4T-A95B and Max. **No small variants.** |

The Instagram claim — "very strong even though it's just 27B" — holds up. It beats
**Qwen3.7-Plus, Alibaba's own larger flagship**, on 10 of 12 published benchmark rows,
losing only GPQA Diamond and HLE.

| Benchmark | Qwen3.8-27B | Qwen3.7-Plus |
|---|---|---|
| SWE-bench Pro | **61.7** | 53.4 |
| QwenSWEBench | **79.0** | 63.8 |
| IFBench (instruction following) | **79.5** | 62.5 |
| LiveCodeBench v6 | **90.3** | 88.8 |
| NL2Repo-Bench (repo-level codegen) | **42.3** | 36.2 |
| CoWorkBench (long-horizon office work) | **70.7** | 65.1 |
| Terminal Bench 2.1 | **73.0** | — (Muse Glimmer 30B: 51.7) |
| GPQA Diamond | 89.2 | **wins** |
| HLE | — | **wins** |

For scale, its CoWorkBench score of 70.7 sits *above* the quoted Opus 4.6 Max figure of 68.2.
The architecture is the interesting part: three of every four blocks use Gated DeltaNet linear
attention, which is how a dense 27B carries 262K context without a KV cache that explodes.

**Caveat that matters below:** these are the full-precision numbers. They do not transfer to a
heavily quantized copy, and quantization is the only way this model comes near node 1.

---

## 2. The number that decides it

Vendor guidance for Qwen3.8-27B, by quantization:

| Quant | RAM/VRAM needed |
|---|---|
| 2-bit | 11–13 GB |
| 3-bit | 13–16 GB |
| **4-bit** | **17–19 GB** |
| 6-bit | 24 GB |
| 8-bit | 31 GB |

**Node 1's ceiling is not a matter of arithmetic. It was measured.**

> **CORRECTION, 2026-08-17.** An earlier revision of this section attributed the §3.2 failure to
> *"Mistral-Small-24B, ~14.3 GB"*. **Both halves were wrong.** The model that failed §3.2 was
> **Qwen3-30B-A3B**, and the on-disk sizes, read from the files themselves, are
> **Mistral-Small-24B = 13.35 GB** and **Qwen3-30B-A3B = 17.35 GB**. The corrected boundary is
> higher than the one first recorded, which makes the 3-bit case *better* than this document
> originally claimed. The conclusion does not change, but it now rests on the right number and
> for the right reason — which is speed, not capacity.

The tempting calculation — 8 GB VRAM plus 9.33 GB free system RAM equals ~17.3 GB addressable —
is wrong, because the KV cache, llama.cpp's compute buffers and mmap page-cache pressure all draw
on the same 15.9 GB. `SPIKE-001` §3.2 measured where it actually lands:

> **Qwen3-30B-A3B Q4_K_M — 17.35 GB on disk**, `-ngl 12` — left **0.27 GB free of 15.9** and drove
> the machine to **660 pages/s average** with 4 GB of pagefile peak.
> Recorded verdict: *DOES NOT COEXIST*.

Against the 13.35 GB dense model, which §3.1 ran to completion, that puts the coexistence boundary
**somewhere between 13.35 GB and 17.35 GB** — bounded on both sides by measurement, and not
pinned more precisely than that by any run on record.

| Qwen3.8-27B | Size | Against the measured band |
|---|---|---|
| **4-bit** | 17–19 GB | **At or past 17.35 GB, which is measured to fail.** Will not load usefully |
| **3-bit** | 13–16 GB | **Inside the unpinned band.** At the bottom of its range it is comparable to a model that did run, so it probably *loads* |

**So 3-bit is not excluded on memory, and this document previously implied it was.** It is
excluded on speed, which the next section derives from the same measurements.

---

## 3. The bandwidth law, and why no configuration escapes it

3-bit probably loads. It is still excluded, and the reason is arithmetic that this node's own
measurements pin down almost exactly.

Generating one token requires reading **every weight the model activates**, once. So the ceiling is
not compute — it is
**tokens/second ≈ effective memory bandwidth ÷ bytes read per token**. Node 1's four dense
measurements, with the GGUF sizes read from the files themselves:

| Model | On disk | Fits in 7.2 GB VRAM? | Measured tok/s | size × tok/s |
|---|---|---|---|---|
| Qwen3-1.7B | 1.19 GB | yes | 148.2 | **176 GB/s** |
| Llama-3.2-3B | 1.88 GB | yes | 98.7 | **186 GB/s** |
| Qwen3-8B | 4.68 GB | yes | 45.8 | **214 GB/s** |
| Mistral-Small-24B | 13.35 GB | **no** | 3.15 | **42 GB/s** |

The product is not a coincidence. The three that fit in VRAM all land at **~180–215 GB/s** — the
RX 6650 XT's memory bandwidth. The one that does not fit lands at **42 GB/s** — dual-channel DDR4.
**The moment a model stops fitting in VRAM, throughput falls off a ~5× cliff**, and after that it
is governed by system RAM speed no matter what else is tuned.

Qwen3.8-27B is **dense**, so every one of its 27B parameters is read for every token. At 3-bit it
is ~14 GB, which does not fit in 7.2 GB of VRAM. The law then predicts:

    42 GB/s ÷ ~14 GB  ≈  3 tokens/second

which is the same single-digit band the 13.35 GB dense model was actually measured in. Against the
`standard` tier's measured **45.8 tok/s**, that is roughly **15× slower**.

**Why the proposed workarounds do not move this number.** Each was checked against the same
measurements rather than dismissed:

| Idea | What it does | Why it does not help |
|---|---|---|
| **Use the SSD as RAM** (swap / pagefile) | Already in use — 27.6 GB allocated on this machine | This is what §3.2 measured *failing*: **660 pages/s**, 0.27 GB free. NVMe runs ~3–7 GB/s against RAM's 42, so it makes the divisor **worse by another ~10×**, not better. It is the failure mode, not the fix |
| **Push more onto the GPU** (`-ngl`) | Puts more layers in VRAM | The card physically holds **7.2 GB, measured**. It is already the thing being maximised; a 14 GB model cannot have more than half of it resident, and VRAM is not expandable |
| **Add virtual memory / a bigger pagefile** | Grows addressable space | Capacity was never the binding constraint at 3-bit — **speed is**. More slow space does not make weights arrive faster |
| **Shift work from CPU to GPU** | Better parallelism | Token generation is **bandwidth-bound, not compute-bound**. Both processors already spend most of their time waiting on memory |

**The one lever that genuinely works on this hardware is architecture, and this node already
measured it.** `Qwen3-30B-A3B` is a **Mixture-of-Experts** model: 30B parameters total but only
~3B activate per token, so it reads a fraction of itself per token. It is **larger on disk than
the dense 24B (17.35 GB vs 13.35 GB), sits on fewer GPU layers, thrashes the pagefile — and is
still more than twice as fast** (6.79 vs 3.15 tok/s). That is the bandwidth law working in the
other direction.

**Qwen3.8-27B is dense, so it gets none of that benefit.** If the goal is a stronger local model on
node 1, the property to shop for is **MoE with a small active-parameter count**, not a better dense
27B — and that is a search this evaluation recommends over adopting this model.

**The latency budget forbids it.** `A-020` declares a 1200 ms voice chain. At ~3 tok/s a single
short reply takes tens of seconds. This model cannot sit anywhere near that path.

**The benchmarks would no longer apply.** The table in §1 describes the full-precision model.
How much a 27B loses at 3-bit is **not something this evaluation has a source for** — treat it
as an open question, not a known penalty. That uncertainty is itself the problem: adopting it
at 3-bit means adopting a model whose quality nobody here has measured, on the strength of
numbers that describe a different one. That is the substitution `CI-034` exists to prevent.

**Cost.** The repo's own power work found the strong tier already costs **~34× more electricity
per token** than the draft tier. A slower, larger model makes that worse.

---

## 4. Add, or replace? — tier by tier

| Tier | Current | Replace with Qwen3.8-27B? | Why |
|---|---|---|---|
| `draft` | Qwen3-1.7B · 148.2 tok/s | **No** | Different job — speculative drafting needs to be tiny and fast |
| `small` | Llama-3.2-3B · 98.7 tok/s | **No** | Background tasks; 27B is three orders of magnitude off the point |
| `standard` | Qwen3-8B · 45.8 tok/s | **No** | 3.4× the parameters, ~15× slower, breaks the latency budget. **And there is no Qwen3.8 small variant to upgrade this tier with** — the family stops at 27B |
| `strong` | Mistral-Small-24B · 3.15 tok/s<br>Qwen3-30B-A3B · 6.79 tok/s | **Yes on merit — but see below** | Better benchmarks, Apache 2.0, native vision, 262K context |

The `strong` row needs care. Qwen3.8-27B is genuinely a better strong-tier model than
Mistral-Small-24B on every axis that matters. But **the strong tier already does not run on
node 1** — that is the measured §3.2 verdict. Swapping a non-running 24B for a larger
non-running 27B changes nothing operationally on this machine.

---

## 5. Decision

1. **Do not add it to node 1, at any quantization — but for the right reason.** At Q4 it is at or
   past the 17.35 GB that §3.2 measured failing. At Q3 it probably **loads**, and is then
   **~3 tok/s** by the bandwidth law in §3 — ~15× slower than the tier it would displace,
   unmeasured in quality, and barred from the latency path. **The binding constraint is speed,
   not capacity**, and no swap, pagefile or offload setting changes it, because all of them act
   on the wrong side of the division. Node 1's usable ceiling remains the `standard` tier.

2. **Record it as the candidate `strong`-tier reference**, superseding Mistral-Small-24B in
   *planning only*. It enrols by measurement on a node that can hold it, exactly as every other
   device does. Nothing about this may reach `capability_profiles.toml` until then.

3. **Do nothing tonight.** See §6.

4. **It does not change the MacBook decision — but it does put a price on the capability.**
   See §7.

---

## 6. Operational hold — A-029 is in flight

The 24-hour endurance run is live (dedicated worktree `VESPER-endurance-2026-08-16`, driver
`verification/run_a029_endurance.py`, several Python processes resident), running until
approximately **00:42 on 2026-08-17**.

Downloading and loading a 17 GB model during that window is actively harmful:

- The download alone is ~16 GB of network and disk I/O.
- Loading it drives free RAM toward zero. The measured behaviour at that memory pressure is
  **0.27 GB free and 660 pages/s** — enough to perturb or stall the run.
- It would **contaminate the run's own power and thermal series**, which are the artifacts the
  run exists to produce.

Any hands-on evaluation waits until A-029 completes and its artifacts are written.

---

## 7. Cross-check against the MacBook procurement decision

This evaluation **independently confirms Finding 2** of `MACBOOK_PROCUREMENT_BENCHMARK.md`:
17–19 GB at Q4 is out of reach for a 16 GB Mac, and out of reach for the 18 GB M3 Pro too. **No
machine on that reseller's list can run Qwen3.8-27B.** That is not an argument for spending
more on that list — it is confirmation that the list's price premium buys nothing here either.

It does, however, put a number on the capability for the first time: **running Qwen3.8-27B at Q4
needs ~24 GB of unified memory as an entry point, and 32 GB to be comfortable** — a 24 GB Mac's
default GPU wired limit is ~18 GB against a 17–19 GB requirement, so 24 GB is marginal rather
than sufficient.

That is recorded as a fact about the capability, **not as a purchase recommendation.** Nothing
here argues for exceeding the stated 12 000 dh ceiling: the machine being bought is for Xcode,
the control plane and the `standard` tier, and it does that job at 10 500 dh. If running a 27B
locally ever becomes a requirement rather than an interest, it is a separate purchase against a
separate budget — and on current evidence the `strong` tier belongs on the API or a future
always-on node, not on a laptop.

---

## 8. If and when it is measured

The protocol is the existing one, unchanged:

1. Run it through `SPIKE-001` §3.1 and §3.2 on whatever node is proposed to host it —
   sustained throughput per tier and memory headroom under the real working set.
2. Record whether `llama.cpp` vision actually works for this architecture. The text path has
   community GGUF support; **the multimodal path is unconfirmed** and is the single most
   valuable untested property, since no current VESPER tier has vision at all.
3. Only measured readings may reach `capability_profiles.toml`. The benchmark table in §1 may
   not, and neither may anything else in this file.
