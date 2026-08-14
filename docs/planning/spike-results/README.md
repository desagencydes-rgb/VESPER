# SPIKE-001 measurement reports

Raw harness output from `tools/spike/profile_node.py`. This directory is under
`docs/planning/`, outside `NORMATIVE_ROOTS`, and nothing here has a path into
`contracts/policy/capability_profiles.toml`. Promotion is a separate, deliberate act.

| File | Condition | Transcribable? |
|---|---|---|
| `SPIKE-001-3.1-v3-draft-qwen1.7B-{idle,concurrent}.json` | tier `draft`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.1-v3-draft-llama3B-{idle,concurrent}.json` | tier `draft`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.1-v3-small-llama3B-{idle,concurrent}.json` | tier `small`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.1-v3-standard-qwen8B-{idle,concurrent}.json` | tier `standard`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.1-v3-strong-moe30B-{idle,concurrent}.json` | tier `strong`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.1-v3-strong-dense24B-{idle,concurrent}.json` | tier `strong`, 3 x 10 min | **yes** — authoritative |
| `SPIKE-001-3.2-memory-baseline.json` | memory headroom, no model resident | **partial** — see §3.2 |
| `SPIKE-001-3.3-storage.json` | sequential + random write on `C:` | **yes** |
| `SPIKE-001-3.6-thermal-power.json` | thermal / power readback | **yes**, with explicit nulls-and-reasons |
| `SPIKE-001-3.1-*` **without** `-v3-` | the 2026-08-13/14 first pass | **NO** — superseded, see §The v2 pass |
| `DESKTOP-F73BBDB-2026081*.json` | early harness shakedown | **NO** — `--quick` |

---

## 3.1 — the settled matrix, measured 2026-08-14 on the site-A desktop

Node: Ryzen 5 5500 · 12 logical cores · 15.9 GB RAM · RX 6650 XT, 7.2 GB usable VRAM ·
llama.cpp build `b10405-e79e4bf66`, Vulkan · `-fa on --cache-type-k q8_0 --cache-type-v q8_0
--parallel 1`. Harness method `schema_version 3` (streamed, wall-clock checkpoints,
`ignore_eos`); aggregates at `schema_version 4` (see Finding 6).

Every figure is the **median of 3 x 10-minute runs**, sampled at **minute 10**, with the
min–max spread. Pass criterion 6 requires both, and below the spread is what decides which
findings survive. **The wall-clock column is the one a router consumes** — see §Two rates.

| Tier | Model | `-c` | `-ngl` | GPU delta | gen idle | **wall idle** (spread) | **wall conc.** (spread) | contention |
|---|---|---|---|---|---|---|---|---|
| `draft` | Qwen3-1.7B | 1024 | 99 | 1389 MiB | 148.20 | **142.01** (140.53–142.24) | **82.00** (81.38–82.48) | **−42.3%** |
| `draft` | Llama-3.2-3B | 1024 | 99 | 2631 MiB | 96.93 | **93.55** (92.55–94.99) | **64.39** (61.01–67.13) | **−31.2%** |
| `small` | Llama-3.2-3B | 2048 | 99 | 2119 MiB | 98.73 | **97.64** (95.07–97.68) | **85.32** (85.16–86.01) | **−12.6%** |
| `standard` | Qwen3-8B | 8448 | 99 | 5737 MiB | 45.81 | **45.67** (45.53–45.97) | **46.56** (45.95–46.66) | *not resolvable* |
| `strong` | Qwen3-30B-A3B (MoE) | 8448 | 12 | 4750 MiB | 6.79 | **6.79** (6.78–7.36) | **7.33** (7.32–7.34) | *not resolvable* |
| `strong` | Mistral-Small-24B (dense) | 8448 | 16 | 6045 MiB | 3.15 | **3.15** (3.06–3.16) | **3.04** (3.03–3.09) | *not resolvable* |

*Not resolvable* means the idle and concurrent spreads overlap, so the sign of the difference
is not established at n = 3. It is recorded that way rather than quoted to three significant
figures. The three rows where the cost **is** resolvable have no overlap at all.

All twelve configurations reported `sustained_is_final_checkpoint = true` at
`sustained_from_checkpoint_minute = 10.0` in all 3 runs. Finding 4 of the previous pass is
closed by construction.

### Finding 1 — the MoE beats a smaller dense model by 2.2x at `strong`

Qwen3-30B-A3B sustains **6.79 tok/s** where Mistral-Small-24B sustains **3.15 tok/s**, on the
same node, same protocol, same VRAM ceiling — despite the MoE being the *larger* model
(17.8 GB of weights against 13.7 GB) and getting *fewer* layers on the GPU (12 against 16).

This was EXPECTED and is now MEASURED. A dense model pays for every offloaded parameter on
every token; an MoE with ~3B active parameters out of 30B pays for a fraction of them. On a
node whose defining constraint is 7.2 GB of VRAM against models that do not fit, this decides
whether the tier is usable at all.

The gap survives its spread by a wide margin — the MoE's worst run (6.78) is 2.15x the dense
candidate's best (3.16).

> **Correction to the v2 record.** This finding was previously published as **"~3x", 9.7
> against 3.3**. Both halves of that were inflated: the MoE figure was an aliased mid-run
> sample (Finding 4) and then a whole-run average (Finding 6). The ratio is **2.2x**, and the
> absolute numbers are ~30% lower. The finding's direction and its consequence are unchanged;
> its magnitude was overstated twice, by two different defects, both in the MoE's favour.

The dense candidate is kept in the record rather than deleted. It is the control that makes
the MoE figure mean something.

### Finding 2 — contention cost is inversely proportional to model speed, and the mechanism is per-request overhead

The wall-clock penalty under concurrent load, in order:

| Config | contention cost | resolvable? |
|---|---|---|
| `draft` Qwen3-1.7B | −42.3% | yes, no overlap |
| `draft` Llama-3.2-3B | −31.2% | yes, no overlap |
| `small` Llama-3.2-3B | −12.6% | yes, no overlap |
| `standard` Qwen3-8B | +1.9% | no — overlapping spreads |
| `strong` MoE | +8.0% | no — overlapping spreads |
| `strong` dense | −3.5% | no — overlapping spreads |

**The mechanism is visible directly.** Wall rate as a fraction of generation rate is the share
of the clock *not* spent generating — prompt eval, HTTP, scheduling, client work — and that is
exactly what the CPU-bound synthetic load contends for:

| Config | tokens/request | overhead, idle | overhead, under load |
|---|---|---|---|
| `draft` Qwen3-1.7B | 256 | 4.2% | **46.4%** |
| `draft` Llama-3.2-3B | 256 | 3.5% | **35.7%** |
| `small` Llama-3.2-3B | 1024 | 1.1% | **11.0%** |
| `standard` Qwen3-8B | 4096 | 0.3% | 0.9% |
| `strong` (both) | 8192, deadline-bounded | 0.0% | 0.0% |

Monotone across all six, in both conditions. The per-request overhead is roughly constant, so
it is a large fraction of a fast short request and a negligible fraction of a slow long one.
At `strong` a single request spans the entire 10-minute window, so there is no inter-request
gap left to contend and the wall rate equals the generation rate exactly.

**An independent corroboration falls out of it.** `draft`-Llama-3B and `small`-Llama-3B are
the *same weights*, differing only in request length (256 vs 1024). The longer-request tier is
**faster in wall-clock terms** — 97.64 against 93.55 — despite a slightly lower generation
rate. Amortising one prompt eval over four times as many tokens more than pays for it. Two
tiers of the ladder are the same model, and the ladder rung that looks "smaller" is the
cheaper one to actually run.

**The consequence for routing is the opposite of the intuition.** The tier that looks cheapest
is the one that loses most when the machine is busy — which is precisely when a router reaches
for it. `draft` at 82.00 tok/s under load is still the fastest option here, but its lead over
`small` collapses from 1.45x to 0.96x: **under load, `draft` is slower than `small`.** Any
routing policy tuned on idle figures will select the wrong tier under exactly the conditions
that motivated the choice.

### Finding 3 — no thermal throttle at `draft`, `small` or `standard`

Minute 10 held minute 1 within ±3% in all 3 runs and both conditions at those tiers. 3.1's
"minute 10, not minute 1" rule was written for thermally-throttled laptops; on this
mains-powered desktop with a discrete card it corrects nothing at those tiers. The rule stays —
it is correct and cheap — and Finding 5 is the reason it earns its keep anyway.

### Finding 4 — checkpoint aliasing at `strong`: found in v2, fixed in v3

The v2 harness could only fire a checkpoint **when a request returned**, because that was the
only moment token counts advanced. At `strong` a single request ran 625–1,137 s — longer than
the whole 10-minute window — so each published `strong` figure came from whichever checkpoint
its return happened to cross. One of the three MoE concurrent runs published **the minute-1
value**, the single figure §3.1 names explicitly and forbids.

**Fixed.** v3 streams tokens and fires checkpoints on the wall clock, and sends `ignore_eos`
so a request lasts the tier's declared length rather than however long the model chooses to
talk. All 12 v3 configurations now report their sustained figure from minute 10, flagged as
the final checkpoint, in 3 runs of 3.

The defect class — *a metric whose boundary is drawn somewhere other than where its name
implies* — has now been found three times in this spike: the `sustained`/`effective` split
(2026-08-13), this one, and Finding 6 below.

### Finding 5 — the `strong` tier decays within a single run, and the MoE decays hard

Interval generation rate at minute 10 against minute 1 of the same run:

| Config | idle | concurrent |
|---|---|---|
| `draft` Qwen3-1.7B | −0.1 / −0.3 / −2.9% | −7.1 / −2.2 / −2.8% |
| `draft` Llama-3.2-3B | +0.4 / +1.4 / +0.2% | +1.5 / 0.0 / +1.3% |
| `small` Llama-3.2-3B | −0.3 / −0.1 / −2.5% | +0.5 / +2.3 / +0.2% |
| `standard` Qwen3-8B | −1.4 / −2.1 / −2.3% | −0.3 / −1.9 / −1.7% |
| **`strong` MoE** | **−39.4 / −46.8 / −45.3%** | **−40.3 / −42.0 / −40.6%** |
| `strong` dense | −6.5 / −6.2 / +5.5% | −7.3 / −5.5 / −7.6% |

The MoE loses **39–47% of its rate across ten minutes, in 6 of 6 runs**, sign-consistent and
tightly clustered, in both conditions. The same harness shows ±3% at every other tier, so this
is not a sampling artefact.

**The cause is not established, and two candidates fit.** (a) KV-cache growth: attention cost
rises as the 8448-token context fills during a long `ignore_eos` generation. (b) An MoE
expert-working-set effect: early tokens are served from a small hot set of experts and the
working set expands toward all of them as generation continues, degrading a partially
offloaded model toward its full streaming speed. Only (b) explains why the MoE decays ~6x
harder than the dense model *at the same context size*. Recorded as an open question.

Thermal is not ruled out but is unlikely to be the whole story — a thermal or power limit
should hit the dense 24B and the 8B similarly, and it does not. No die temperature is readable
on this board, so this cannot be settled here.

**Consequence.** Strong-tier figures must be taken at the END of a sustained run. A minute-1
sample of the MoE reads ~12.4 tok/s against a settled 6.79. A router calibrated on the early
number would over-commit to `strong` by roughly 1.8x.

### Finding 6 — the two headline columns were aggregated over different windows

`median_sustained_tokens_per_sec` was the **minute-10** generation rate.
`median_effective_tokens_per_sec` was the **whole-run average** wall rate. The per-run
minute-10 wall rate existed in every report as `sustained_effective_tokens_per_sec` and was
simply never aggregated.

On a config that holds flat the two windows agree within ~1% and the defect is invisible. On
a config that decays, the whole-run average sits above the settled rate by however much it
decayed:

| Config | published (whole-run) | settled (minute 10) | error |
|---|---|---|---|
| `strong` MoE idle | 8.63 | **6.79** | +27% |
| `strong` MoE concurrent | 8.79 | **7.33** | +20% |
| `strong` dense idle | 3.21 | **3.15** | +1.9% |
| everything else | — | — | under 1% |

The one row where it mattered is the one row whose promotion decision it would have driven.

**Fixed and re-derived, not re-measured.** The samples were never wrong — only the summary
was. `tools/spike/reaggregate.py` recomputes the aggregates from each report's own
`run_results`, stamps `schema_version 4`, and records the superseded value in the file. A
re-run would have cost ~6 hours and produced identical `run_results`. **v3 and v4 reports are
comparable**, unlike v2 and v3: the measurement method is unchanged.

---

## Two rates, and why the wall-clock one is the real one

`sustained_tokens_per_sec` — the figure 3.1 names — counts only server-side *generation* time.
The synthetic load is CPU-bound and never contends the accelerator, so a generation-time metric
is **structurally blind** to it. This pass makes the point better than the last one did:

| Config | generation rate, idle → concurrent | wall rate, idle → concurrent |
|---|---|---|
| `draft` Qwen3-1.7B | 148.20 → 153.03 (**+3.3%**) | 142.01 → 82.00 (**−42.3%**) |
| `draft` Llama-3.2-3B | 96.93 → 100.14 (**+3.3%**) | 93.55 → 64.39 (**−31.2%**) |
| `standard` Qwen3-8B | 45.81 → 46.97 (+2.5%) | 45.67 → 46.56 (+1.9%) |

In four of six configurations the generation rate reports that concurrent load made the node
**faster**. Reporting it satisfies §5's letter — the concurrent figure *was* reported — while
committing exactly the error §5 exists to prevent.

**The router must use `median_effective_tokens_per_sec` from the concurrent condition**, which
as of `schema_version 4` is the minute-10 wall rate.

---

## 3.2 memory · 3.3 storage · 3.6 thermal — closed 2026-08-14

**3.2 memory — PARTIAL.** 15.9 GB total, 9.79 GB available with no model resident. The
protocol asks for headroom measured **with the owner's real working set loaded** (browser,
editor, whatever actually runs). This figure is a point-in-time OS reading on an idle machine
and is not that. **One re-run needed, while the machine is in normal use.**

**3.3 storage — DONE.** Sequential write **1271.7 MB/s**, random 4K write **75,787 IOPS**, on
`C:\Projects\VESPER-runtime`. 123.5 GB free of 475.9 GB. Swap inactive before and after,
sampled point-in-time — a positive reading would be meaningful, a negative one is
inconclusive, not proof.

**3.3 checkpoint commit — DONE, and it hands SPIKE-008 its figure.** At `synchronous=FULL`,
`journal_mode=WAL`, under concurrent read load, 1000 commits: **p50 0.93 ms, p95 1.08 ms, max
9.25 ms** against a **200 ms p95 budget**. 185x headroom. Ordering violations: 0. SPIKE-008
criteria 5 and 6 both satisfied. Measured by the SPIKE-008 harness rather than duplicated here,
so there is one implementation of the five-store schema and not two that can drift.

**3.6 thermal and power — DONE, with honest nulls.** No throttle at `draft`/`small`/`standard`
(Finding 3); `strong` decays and is recorded separately (Finding 5). Battery drain is
structurally N/A on a mains desktop. Wall power and noise are **null with reasons** — no meter,
and a phone-app reading is not a measurement. ACPI thermal zones unreadable on this board.
Owner-usable-during-load is DECLARED per the 3.4 policy lock, not measured.

**3.4 network** — closed as policy per commit `b695251`. **3.5 camera/audio** — skipped for
this node by owner direction. Neither is pending.

---

## The v2 pass (files without `-v3-`)

Kept as a record of what was run, not as data. They were measured before the streaming fix,
so at `strong` their checkpoints alias (Finding 4) and at every tier their aggregates use the
wrong window (Finding 6). Streaming also costs ~4% of throughput, so a v2 figure and a v3
figure are not comparable even where v2 sampled correctly — and mixing them *across tiers* is
the worst case, because comparing tiers is exactly what the router does.

Their headline figures must not be copied into `capability_profiles.toml` or quoted as
measurements. They are labelled here rather than deleted, because erasing what was run is a
worse habit than naming it.

**The two `--quick` files** likewise. Each carries `QUICK_MODE_WARNING` in its own body. A
`--quick` pass skips the sustained window entirely, so its number describes a cold machine over
seconds — the exact error 3.1 exists to prevent.

---

## What is left of SPIKE-001 on this node

| Item | State | Cost to close |
|---|---|---|
| 3.1 full tier matrix, both conditions | **DONE** — 6 configs x 2 conditions x 3 runs | — |
| 3.2 memory headroom under real working set | **OPEN** | one run, ~1 min, while the machine is in use |
| 3.3 storage + checkpoint commit | **DONE** | — |
| 3.4 network | closed as policy | — |
| 3.5 camera / audio | skipped for this node | — |
| 3.6 thermal / throttle | **DONE** | — |
| 3.6 wall power | **BLOCKED** on an instrument | a wall meter; SPIKE-011 names one |
| Finding 5 attribution (KV growth vs MoE working set) | **OPEN QUESTION** | a context-length sweep at `strong` |

Nothing here is on the F0 critical path. F0 was unblocked by ADR-002 and ADR-007 on
2026-08-14, and promotion of any figure above into `capability_profiles.toml` remains a
separate, deliberate act.
