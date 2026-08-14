# SPIKE-001 measurement reports

Raw harness output from `tools/spike/profile_node.py`. This directory is under
`docs/planning/`, outside `NORMATIVE_ROOTS`, and nothing here has a path into
`contracts/policy/capability_profiles.toml`. Promotion is a separate, deliberate act.

> **Two nodes are now measured.** Everything below the "The full 3.1 matrix" heading is
> **node 1**, the site-A desktop (Windows, RX 6650 XT). **Node 2** — the Kali laptop
> (`CSF`, ASUS VivoBook, i3-8130U, 3.7 GB RAM, **CPU-only**) — was onboarded 2026-08-14; its
> results and the reasoning around them are in **`NODE-2-KALI-LAPTOP-FINDINGS.md`**, with the
> machine-preparation log in `MACHINE-PREP-KALI.md`. Node-2 raw harness files:
>
> | File | Section |
> |---|---|
> | `SPIKE-008-adr002-validation-kali.json` | SPIKE-008 blocking suite (2nd node class; control fails; 500/500 crash trials) |
> | `SPIKE-001-3.x-kali-system.json` | §system identity |
> | `SPIKE-001-3.2-kali-memory.json` | §3.2 memory headroom |
> | `SPIKE-001-3.3-kali-storage.json` | §3.3 storage |
> | `SPIKE-001-3.1-kali-draft-qwen1.7B-idle.json` | §3.1 draft tier, CPU-only, idle |
> | `SPIKE-001-3.1-kali-draft-qwen1.7B-concurrent.json` | §3.1 draft tier, CPU-only, concurrent |
>
> The single most consequential node-2 finding for the fabric: **this laptop is a viable
> _interim_ always-on control-plane host** (the gap no enrolled node fills) *conditional on*
> the owner's availability commitment and an `ADR-007`/disk-encryption path to Z0 — but its
> measured availability class is `on_demand`, not `always_on`, and its RAM makes it the bridge,
> not the destination. Full reasoning in `NODE-2-KALI-LAPTOP-FINDINGS.md`.

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

Every row is the **median of 3 x 10-minute runs, with the min–max spread** — pass criterion 6
requires both, and in one row below the spread is what decides whether the finding survives.
**Read the wall-clock column** — see §Two rates.

| Tier | Model | `-ngl` | GPU delta | wall idle (spread) | wall conc. (spread) | contention cost |
|---|---|---|---|---|---|---|
| `draft` | Qwen3-1.7B | 99 | 1171 MiB | **151.42** (151.07–151.58) | **94.88** (93.05–97.47) | **−37.3%** |
| `draft` | Llama-3.2-3B | 99 | 2032 MiB | **99.50** (99.07–99.69) | **72.03** (71.37–72.80) | **−27.6%** |
| `standard` | Qwen3-8B | 99 | 5225 MiB | **47.38** (47.28–47.42) | **46.79** (46.63–46.80) | **−1.2%** |
| `strong` | Qwen3-30B-A3B (MoE) | 12 | 4720 MiB | **9.73** (9.19–10.36) | **8.54** (7.90–9.19) | *not resolvable* |
| `strong` | Mistral-Small-24B (dense) | 16 | 5868 MiB | **3.29** (3.28–3.31) | **3.25** (3.24–3.26) | **−1.2%** |
| `small` | Llama-3.2-3B | 99 | — | **100.57** | **89.45** | −11.1% |

Generation-rate medians, for completeness: draft-1.7B 157.67 / 158.80 · draft-3B 103.28 /
102.94 · standard 47.53 / 47.45 · MoE 9.34 / 8.16 · dense 3.32 / 3.26 · small 102.63 / 102.33.

**The MoE row's spread is 12–15% and its two ranges overlap at 9.19.** Every other row holds
under 5%. So the MoE's apparent −12.2% contention cost is **not resolvable at n = 3** and is
recorded as such rather than quoted to three significant figures. §Sampling below explains
why that one row is noisy, and it is not because the machine is.

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

The 3x gap survives its spread by a wide margin — the MoE's worst run (9.19) is 2.8x the
dense candidate's best (3.31) — so this finding stands where the contention one below does not.

### Finding 2 — contention cost is inversely proportional to model speed

The wall-clock penalty under concurrent load is **−37% for the 1.7B**, **−28% for the 3B**,
and **−1.2% for the 8B and the 24B**, each measured on rows whose spread is under 5%. This is
consistent and mechanical rather than noisy: the fixed per-request overhead the concurrent
load inflates (scheduling, HTTP, tokenisation, client work) is roughly constant per request,
so it is a large fraction of a fast model's request and a negligible fraction of a slow one's.

The MoE row is excluded from this finding, not folded into it. Its ranges overlap.

**The consequence for routing is the opposite of the intuition.** The tier that looks
cheapest to run is the one that loses most when the machine is busy — which is exactly when
a router would reach for it. `draft` at 94.88 tok/s under load is still the fastest option
here, but the gap to `standard` narrows from 3.3x to 2.0x, and any routing policy tuned on
idle figures will over-select `draft`.

### Finding 3 — this node does not thermally throttle

Minute 10 matched minute 1 at `draft`, `small` and `standard`, in both conditions. 3.1's
"minute 10, not minute 1" rule was written for thermally-throttled laptops; on this
mains-powered desktop with a discrete card it is a no-op. The rule stays — it is correct and
cheap — but on this node class it corrects nothing. Worth knowing, and only known because it
was measured. **This finding does not extend to `strong`,** whose checkpoints do not measure
what their labels say — see §Sampling.

### Finding 4 — at `strong`, the harness samples the wrong thing, and the spread proves it

This is the defect the MoE's 12–15% spread was pointing at, and it is not a property of the
machine.

`_single_throughput_run` can only fire a checkpoint **when a request returns**, because that
is the only moment token counts advance. At `draft` (256 tokens) and `standard` (4096) a
request returns every few seconds, so the minute-1 / minute-5 / minute-10 checkpoints land
where their labels say. At `strong` a single request runs for **625–1,137 seconds** — longer
than the entire 10-minute window — so one request spans two or three checkpoint boundaries,
and every interval collapses into whichever checkpoint its return happens to cross.

Reconstructed from the committed reports, per run — `sustained_tokens_per_sec` is defined as
the *last non-null interval*, so the column on the right is the checkpoint each published
figure actually came from:

| Run | requests | checkpoint pattern (min 1 / 5 / 10) | published "sustained" is from |
|---|---|---|---|
| `moe30B-idle` run 0 | 2 | 10.69 / 9.34 / — | **minute 5** |
| `moe30B-idle` run 1 | 1–2 | 10.24 / — / 10.73 | minute 10 |
| `moe30B-idle` run 2 | 2 | 10.57 / — / 8.66 | minute 10 |
| `moe30B-conc` run 0 | 2 | 9.40 / — / 8.16 | minute 10 |
| `moe30B-conc` run 1 | 1–2 | 10.33 / 8.78 / — | **minute 5** |
| `moe30B-conc` run 2 | 1 | 7.93 / — / — | **minute 1** |
| `dense24B` all 6 | 2 | 3.3 / — / 3.3 | minute 10 |

So the three MoE "sustained" values that produced a median and a 12% spread were each taken
from a **different checkpoint over a different number of requests**. They are not one
measurement repeated three times, and their spread is sampling geometry, not machine
variance. One of them — `moe30B-conc` run 2 — is **the minute-1 value**, which is the single
figure §3.1 names explicitly and forbids: *"sustained_tokens_per_sec := the MINUTE-10 value,
not the minute-1 value."* The harness obeyed the rule's letter (take the last interval) and
broke it in fact.

This is the same defect class as the `sustained` / `effective` split found on 2026-08-13, one
level down: **a metric whose boundary is drawn somewhere other than where its name implies.**
It was invisible in the aggregate and only appeared by asking why one row's spread was three
times every other row's.

**What stands and what does not.** The order-of-magnitude comparison stands — 9.7 against 3.3
is far too large to be sampling geometry, and Finding 1 is safe. What does not stand is any
`strong` figure quoted to three significant figures, any `strong` idle-vs-concurrent delta,
and any claim that `strong` was measured at minute 10.

**Fix, before `strong` is re-run or promoted:** sample on a wall-clock timer (or stream
tokens) rather than only at request boundaries, and send `ignore_eos` so a request lasts the
tier's declared length instead of however long the model chooses to talk. Both are small; the
second alone is not enough, because a 8,192-token request at 9.7 tok/s still spans 845 s and
would still alias.

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
`strong` (8192) **no run ever reached the cap in a single request**: totals are 2,064–2,520
for the dense candidate and 6,314–9,996 for the MoE, across one or two EOS-terminated
requests. The tok/s figure is still a rate over real generation, so it stands; but the
`strong` rows measure *however long this prompt makes the model talk*, not the tier's
declared length. Fixing this means sending `ignore_eos` — cheap, and it should happen before
`strong` is promoted to `capability_profiles.toml`. It is necessary but **not sufficient**;
see Finding 4 for the sampling half of the same problem.

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
