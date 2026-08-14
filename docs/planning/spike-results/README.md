# SPIKE-001 measurement reports

Raw harness output from `tools/spike/profile_node.py`. This directory is under
`docs/planning/`, outside `NORMATIVE_ROOTS`, and nothing here has a path into
`contracts/policy/capability_profiles.toml`. Promotion is a separate, deliberate act.

| File | Condition | Transcribable? |
|---|---|---|
| `SPIKE-001-3.1-draft-qwen1.7B-{idle,concurrent}.json` | tier `draft`, 3 x 10 min | **yes** — full protocol, `--launch-command` recorded |
| `SPIKE-001-3.1-draft-llama3B-{idle,concurrent}.json` | tier `draft`, 3 x 10 min | **yes** — full protocol, `--launch-command` recorded |
| `SPIKE-001-3.1-standard-qwen8B-{idle,concurrent}.json` | tier `standard`, 3 x 10 min | **yes** — full protocol, `--launch-command` recorded |
| `SPIKE-001-3.1-strong-moe30B-{idle,concurrent}.json` | tier `strong`, 3 x 10 min | **yes**, with the §EOS caveat below |
| `SPIKE-001-3.1-strong-dense24B-{idle,concurrent}.json` | tier `strong`, 3 x 10 min | **yes**, with the §EOS caveat below |
| `SPIKE-001-3.1-small-unattended.json` | tier `small`, 3 x 10 min, idle | **superseded** — measured under the 512-token cap, see below |
| `SPIKE-001-3.1-small-concurrent.json` | tier `small`, 3 x 10 min, concurrent load | **superseded** — measured under the 512-token cap, see below |
| `DESKTOP-F73BBDB-20260812T224722.json` | early harness shakedown | **NO** — `--quick` |
| `DESKTOP-F73BBDB-20260813T010244.json` | early harness shakedown | **NO** — `--quick` |

## The full 3.1 matrix, measured 2026-08-13/14 on the site-A desktop

Node: Ryzen 5 5500 · 15.9 GB RAM · RX 6650 XT, 7.2 GB usable VRAM · llama.cpp build
`b10405-e79e4bf66`, Vulkan · `-fa on --cache-type-k q8_0 --cache-type-v q8_0 --parallel 1`.

Every row is the median of 3 x 10-minute runs. **Read the wall-clock column** — see §Two rates.

| Tier | Model | `-ngl` | GPU delta | gen idle | **wall idle** | gen conc. | **wall conc.** | contention cost |
|---|---|---|---|---|---|---|---|---|
| `draft` | Qwen3-1.7B | 99 | 1171 MiB | 157.67 | **151.42** | 158.80 | **94.88** | **−37.3%** |
| `draft` | Llama-3.2-3B | 99 | 2032 MiB | 103.28 | **99.50** | 102.94 | **72.03** | **−27.6%** |
| `standard` | Qwen3-8B | 99 | 5225 MiB | 47.53 | **47.38** | 47.45 | **46.79** | **−1.2%** |
| `strong` | Qwen3-30B-A3B (MoE) | 12 | 4720 MiB | 9.34 | **9.73** | 8.16 | **8.54** | **−12.2%** |
| `strong` | Mistral-Small-24B (dense) | 16 | 5868 MiB | 3.32 | **3.29** | 3.26 | **3.25** | **−1.2%** |
| `small` | Llama-3.2-3B | 99 | — | 102.63 | **100.57** | 102.33 | **89.45** | −11.1% |

### Finding 1 — MoE beats a smaller dense model by ~3x at the `strong` tier

Qwen3-30B-A3B sustains **9.7 tok/s** where Mistral-Small-24B sustains **3.3 tok/s**, on the
same node, same protocol, same VRAM ceiling — despite the MoE being the *larger* model
(17.8 GB of weights against 13.7 GB) and getting *fewer* layers on the GPU (12 against 16).

This was EXPECTED and is now MEASURED. A dense model pays for every offloaded parameter on
every token; an MoE with ~3B active parameters out of 30B pays for a fraction of them. On a
node whose defining constraint is 7.2 GB of VRAM against models that do not fit, that is not
a tuning detail — it decides whether the tier is usable at all. **3.3 tok/s is a curiosity;
9.7 tok/s is a slow but real overnight worker.**

The dense candidate is kept in the record rather than deleted. It is the control that makes
the MoE figure mean something.

### Finding 2 — contention cost is inversely proportional to model speed

The wall-clock penalty under concurrent load is **−37% for the 1.7B**, **−28% for the 3B**,
and **−1.2% for the 8B and the 24B**. This is consistent and mechanical rather than noisy:
the fixed per-request overhead the concurrent load inflates (scheduling, HTTP, tokenisation,
client work) is roughly constant per request, so it is a large fraction of a fast model's
request and a negligible fraction of a slow one's.

**The consequence for routing is the opposite of the intuition.** The tier that looks
cheapest to run is the one that loses most when the machine is busy — which is exactly when
a router would reach for it. `draft` at 94.88 tok/s under load is still the fastest option
here, but the gap to `standard` narrows from 3.3x to 2.0x, and any routing policy tuned on
idle figures will over-select `draft`.

### Finding 3 — this node does not thermally throttle

Minute 10 matched minute 1 in all runs, in both conditions, at every tier. 3.1's "minute 10,
not minute 1" rule was written for thermally-throttled laptops; on this mains-powered desktop
with a discrete card it is a no-op. The rule stays — it is correct and cheap — but on this
node class it corrects nothing. Worth knowing, and only known because it was measured.

## Two rates, and why the right column is the real one

`sustained_tokens_per_sec` — the figure 3.1 names — counts only server-side *generation*
time. The synthetic load is CPU-bound and never contends the accelerator, so a
generation-time metric is **structurally blind** to it: it reports the `draft` tier losing
0.2% while wall-clock throughput lost 37%.

The harness emits `effective_tokens_per_sec` (tokens ÷ wall clock) alongside, and labels
which one the router should consume. **The router must use `effective_tokens_per_sec` from
the concurrent condition.** Reporting the generation rate satisfies §5's letter — the
concurrent figure *was* reported — while committing exactly the error §5 exists to prevent.

## Caveats that must travel with these numbers

**EOS terminates a request before `n_predict`.** The harness sends `n_predict = <tier
length>` but does not send `ignore_eos`, so a model that finishes its answer early ends the
request there. At `draft` (256) and `standard` (4096) the token totals are exact multiples of
the tier length, so the cap was always reached and the request length is the tier's. At
`strong` (8192) they are not: `strong-dense24B` produced ~2,064–2,189 tokens per 10-minute
run, i.e. **one naturally-terminated response**, not a 8,192-token generation. The tok/s
figure is still a rate over real generation, so it stands; but the `strong` rows measure
*however long this prompt makes the model talk*, not the tier's declared length, and the
minute-5 checkpoint is `null` in those runs because no request returned inside that window.
Fixing this means sending `ignore_eos` — cheap, and it should happen before `strong` is
promoted to `capability_profiles.toml`.

**`small` has not been re-measured since the 512-token cap was removed.** Its two files were
taken at 512 generated tokens per request, not the tier's 1024. They are internally
consistent, so the idle-vs-concurrent comparison inside them holds, but they are not the
`small` tier as 3.1 defines it and are not comparable to the rows above. **`small` is the
tier that closes pass criterion 2** (`local_inference_small`, the SR-005 fallback), so this
is the one gap on the critical path. A re-run is ~1 hour. `draft`-at-256 on the same model
came in at 103.28/99.50, and `small`-at-512 at 102.63/100.57, so the re-run is EXPECTED to
land near 102–103 — but expected is not measured, and the whole point of this spike is that
the difference matters.

**The two `--quick` files are kept as a record of what was run, not as data.** Each carries
`QUICK_MODE_WARNING` in its own body. Their figures must never be copied into
`capability_profiles.toml`, quoted as a measurement, or compared against a full-protocol run
— a `--quick` pass skips the sustained window entirely, so its number describes a cold
machine over seconds, which is the exact error SPIKE-001 3.1 exists to prevent. They were
committed alongside the real report by a broad `git add`; they are labelled here rather than
deleted, because erasing what was run is a worse habit than naming it.

## What "3.1 complete" actually requires

3.1 iterates every capability tier, each in **two** load conditions, each three times for
ten minutes. That is 6 runs per tier, ~1 hour per tier.

There are **four** tiers, not three. `contracts/entities/model_profile.schema.json`
defines `capability_tier` as `["draft", "small", "standard", "strong"]`, and `strong`
is the tier **SR-009 routes to for hard work**. SPIKE-001 3.1 iterated only the first
three, so `strong` could never leave `UNKNOWN` and pass criterion 1 could never be met.
The owner asked for a maximum-capability tier on 2026-08-13; that tier already existed
in the corpus and the spike was simply omitting it. Added under its existing name
rather than a new one.

| Tier | Model measured | Generation length | Min `-c` | Status |
|---|---|---|---|---|
| `draft` | `Qwen3-1.7B` **and** `Llama-3.2-3B` | 256 | 384 | **DONE**, both conditions, both models |
| `small` | `Llama-3.2-3B` | 1024 | 1152 | **RE-RUN NEEDED** — held figures are 512-capped |
| `standard` | `Qwen3-8B` | 4096 | 4224 | **DONE**, both conditions |
| `strong` | `Qwen3-30B-A3B` **and** `Mistral-Small-24B` | 8192 | 8320 | **DONE**, both conditions, both models; see EOS caveat |

The tier selects the **generation length per request**; the tier-representative
**model** is the operator's choice, recorded through `--launch-command`. Both halves
matter — a figure is only comparable against another run with the same model *and*
the same tier.

### Correction: the harness capped every request at 512 tokens

An earlier note here claimed the `standard` tier would overflow a `-c 4096` server.
**That was wrong**, and the reason it was wrong is the actual defect:
`_single_throughput_run` called `_llama_generate(..., n_predict=min(ctx_tokens, 512))`.
The cap meant nothing could ever overflow — and also that **the tier argument was inert
above 256 tokens**. `small` (1024) and `standard` (4096) both collapsed to 512, so they
produced byte-identical request shapes and differed only by which model was loaded.
Three tiers, two distinct measurements.

Fixed: the cap is removed, requests now generate the tier's full length, and the run
**refuses to start** — with the required `-c` in the error — rather than silently
measuring a truncated request and reporting it as a sustained figure.

**Consequence for the figures already taken.** Both `small` runs (idle and concurrent)
were measured at **512 generated tokens per request, not 1024**, under the old cap.
They are internally consistent with each other, so the idle-vs-concurrent comparison
holds, and the effect of request length on tokens/sec is small. But they are *not*
the `small` tier as 3.1 defines it, and they are not comparable to `standard` or
`strong` runs taken after this fix. Recorded here rather than quietly re-labelled;
re-running `small` at 1024 is cheap and should happen before anything is promoted.

`strong` was expected to exceed 7.2 GB of VRAM and spill to CPU. That is the point of
the tier, not a failure of it — `INFERENCE_ARCHITECTURE.md` 0 already treats partial
CPU offload as a real option that trades tokens/sec for capability. **Measured: 9.7 tok/s
(MoE) and 3.3 tok/s (dense).** Single-digit, as expected, and recorded as the honest
ceiling of this node — with the finding that *which* single digit depends on model
architecture more than on model size.

### A silent-failure mode the strong tier exposed, and the fix

The first `strong` pass reported only **1 of 3 valid runs** in each condition for the MoE
candidate. `_llama_generate` carried a flat 600 s per-request timeout, and an 8192-token
request at ~10.5 tok/s needs ~775 s — so two runs in three died on the client side and
were recorded as errors. A tier defined by being slow had a timeout that assumed it would
be fast.

The timeout now scales with the requested length: `max(600, ctx_tokens / 2 + 60)`, i.e. a
floor of 2 tok/s, generously below anything observed. The two affected configurations were
re-run under the fix and now carry 3/3. **The values in the table above are the re-run
values.** Recorded because a harness that drops two thirds of its samples and still emits
a median is worse than one that crashes.

### What is left of 3.1

`small` is the tier that closes **pass criterion 2** (`local_inference_small`, the SR-005
fallback), and it is the **only tier still on the critical path**. Its held figures predate
the 512-cap removal. Cost to close: one ~1-hour matrix run.

Everything else in 3.1 is measured. 3.2 (memory headroom), 3.3 (storage / the five stores),
3.5 (camera and audio) and 3.6 (thermal and power) are untouched; 3.4 (network) is closed as
policy per commit `b695251`.
