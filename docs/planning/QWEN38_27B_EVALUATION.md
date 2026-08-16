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

The tempting calculation — 8 GB VRAM plus 9.33 GB free system RAM (15.9 total minus the 6.57 GB
measured working set) equals 17.33 GB addressable — **is wrong, and this repo already has the
evidence that falsifies it.** With `-ngl N`, N layers sit in VRAM and the remainder in system
RAM, but the KV cache, llama.cpp's compute buffers and mmap page-cache pressure all draw on the
same 15.9 GB. `SPIKE-001` §3.2 measured where that actually lands:

> Mistral-Small-24B Q4_K_M — **~14.3 GB of weights**, `-ngl 16` — left **0.27 GB free of 15.9**
> and drove the machine to **660 pages/s** with 4 GB of pagefile peak.
> Recorded verdict: *DOES NOT COEXIST*.

A 14.3 GB model failed on a machine the naive sum said could hold 17.33 GB. **The operative
ceiling on node 1 is therefore ~14.3 GB of weights — a measured failure, not a calculated
limit.** Anything at or above that size fails the same way.

| Qwen3.8-27B | Size | Against the measured 14.3 GB boundary |
|---|---|---|
| **4-bit** | 17–19 GB | **3–5 GB past it.** Will not load usefully |
| **3-bit** | 13–16 GB | **Straddles it.** Best case sits within a hair of the boundary; worst case is past it |

Neither configuration clears a boundary that a **smaller** model already failed.

---

## 3. Why 3-bit is not a way around it

3-bit is the only configuration that even approaches node 1, and it fails on memory before any
other argument is needed: at 13–16 GB it straddles the 14.3 GB boundary that a smaller model
already failed at. Three further reasons make it a non-starter even at the bottom of that range:

**Speed.** Node 1 measured Mistral-Small-24B Q4 at **3.15 tok/s** with `-ngl 16`. A 27B at
3-bit with an 8 GB card lands in the same single-digit band; independent reports put a *20 GB*
VRAM card at 7–10 tok/s and note that 8 GB with heavy CPU offload falls to single digits.
Against the `standard` tier's measured **45.8 tok/s**, that is roughly **15× slower**.

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

1. **Do not add it to node 1, at any quantization.** At Q4 it sits 3–5 GB past the measured
   14.3 GB failure boundary; at Q3 it straddles that same boundary, and even at the bottom of
   its range it is ~15× slower than the tier it would displace, unmeasured in quality, and
   barred from the latency path. Node 1's usable ceiling remains the `standard` tier — which
   §3.2 established and this evaluation does not disturb.

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
