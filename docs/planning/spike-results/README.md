# SPIKE-001 measurement reports

Raw harness output from `tools/spike/profile_node.py`. This directory is under
`docs/planning/`, outside `NORMATIVE_ROOTS`, and nothing here has a path into
`contracts/policy/capability_profiles.toml`. Promotion is a separate, deliberate act.

| File | Condition | Transcribable? |
|---|---|---|
| `SPIKE-001-3.1-small-unattended.json` | tier `small`, 3 x 10 min, idle/unattended | **yes** — full protocol, `--launch-command` recorded |
| `DESKTOP-F73BBDB-20260812T224722.json` | early harness shakedown | **NO** — `--quick` |
| `DESKTOP-F73BBDB-20260813T010244.json` | early harness shakedown | **NO** — `--quick` |

**The two `--quick` files are kept as a record of what was run, not as data.** Each
carries `QUICK_MODE_WARNING` in its own body. Their figures must never be copied
into `capability_profiles.toml`, quoted as a measurement, or compared against the
full-protocol run — a `--quick` pass skips the sustained window entirely, so its
number describes a cold machine over seconds, which is the exact error SPIKE-001
3.1 exists to prevent. They were committed alongside the real report by a broad
`git add`; they are labelled here rather than deleted, because erasing what was run
is a worse habit than naming it.

## What "3.1 complete" actually requires

3.1 iterates **three** capability tiers, each in **two** load conditions, each three
times for ten minutes. That is 6 runs per tier, ~1 hour per tier, ~3 hours total.

There are **four** tiers, not three. `contracts/entities/model_profile.schema.json`
defines `capability_tier` as `["draft", "small", "standard", "strong"]`, and `strong`
is the tier **SR-009 routes to for hard work**. SPIKE-001 3.1 iterated only the first
three, so `strong` could never leave `UNKNOWN` and pass criterion 1 could never be met.
The owner asked for a maximum-capability tier on 2026-08-13; that tier already existed
in the corpus and the spike was simply omitting it. Added under its existing name
rather than a new one.

| Tier | Model needed | Generation length | Min `-c` | Status |
|---|---|---|---|---|
| `draft` | ~1B | 256 | 384 | model not downloaded |
| `small` | ~3B (`Llama-3.2-3B-Instruct-Q4_K_M`) | 1024 | 1152 | idle DONE, concurrent RUNNING |
| `standard` | ~7-8B | 4096 | 4224 | model not downloaded |
| `strong` | biggest that runs at all, CPU offload expected | 8192 | 8320 | model not chosen |

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

`strong` is expected to exceed 7.2 GB of VRAM and spill to CPU. That is the point of
the tier, not a failure of it — `INFERENCE_ARCHITECTURE.md` 0 already treats partial
CPU offload as a real option that trades tokens/sec for capability. Expect single-digit
tokens/sec and record it as the honest ceiling of this node.

### Priority, given the one-month deadline

`small` is the tier that closes **pass criterion 2** (`local_inference_small`, the
SR-005 fallback). It is therefore the only tier on the critical path. `standard` is
the most valuable of the remaining two, because whether a ~8B model fits in the
measured 7.2 GB budget and at what speed is what decides `LEAD_SCOUT` viability in
`INFERENCE_ARCHITECTURE.md` 3. `draft` is cheapest and least decisive.
