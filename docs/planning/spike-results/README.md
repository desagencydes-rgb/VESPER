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

| Tier | Model needed | Generation length | Status |
|---|---|---|---|
| `draft` | ~1B | 256 tok/request | model not downloaded |
| `small` | ~3B (`Llama-3.2-3B-Instruct-Q4_K_M`) | 1024 tok/request | idle DONE, concurrent RUNNING |
| `standard` | ~7-8B | 4096 tok/request | model not downloaded |

The tier selects the **generation length per request** in the harness
(`TIER_CONTEXT_TOKENS`); the tier-representative **model** is the operator's choice
and is recorded through `--launch-command`. Both halves matter — a figure is only
comparable against another run with the same model *and* the same tier.

### A trap in the `standard` tier, recorded before it is hit

`standard` asks for **4096 generated tokens per request**, and the server has so far
been launched with `-c 4096`. Prompt plus generation would exceed the context window,
so the run would truncate or error rather than measure. **The `standard` tier must be
launched with a larger `-c` (8192).** That changes KV cache size, so its figure is not
directly comparable to the `small` runs — which is expected and fine, since they are
different tiers, but it must be recorded rather than discovered.

### Priority, given the one-month deadline

`small` is the tier that closes **pass criterion 2** (`local_inference_small`, the
SR-005 fallback). It is therefore the only tier on the critical path. `standard` is
the most valuable of the remaining two, because whether a ~8B model fits in the
measured 7.2 GB budget and at what speed is what decides `LEAD_SCOUT` viability in
`INFERENCE_ARCHITECTURE.md` 3. `draft` is cheapest and least decisive.
