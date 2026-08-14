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

> **The two `strong` rows are the last observed rate, not a plateau.** At that tier one
> request spans the entire window (0 of 1 completed, aborted at the deadline), and the rate
> was still falling with context when the clock stopped — see Finding 5. Read 6.79 as *the
> rate at ~4.2k tokens of context*, not as a floor. Every other row is a genuine steady state
> across dozens to hundreds of completed requests.

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
for it.

Stated on identical weights, so that model speed cannot be doing the work: Llama-3.2-3B at
the `small` request length beats **the same file** at the `draft` request length under load,
**85.32 against 64.39** — a 32% advantage for the tier that generates four times as much per
request. Idle, the two are within 4.4% of each other. The entire gap is contention landing on
per-request overhead.

Across models the picture is milder and should not be overstated: `draft`-Qwen3-1.7B holds
82.00 under load against `small`'s 85.32, so the fastest draft model roughly *draws* with
`small` rather than losing to it — a 3.9% gap that is close to spread distance. What is solid
is the direction and the size of the collapse: `draft`-Qwen's lead over `small` falls from
1.45x idle to 0.96x under load. Any routing policy tuned on idle figures will over-select
`draft` under exactly the conditions that motivated choosing it.

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

**The cause is KV-cache growth, not an MoE effect.** Two candidates were considered: (a)
attention cost rising as the 8448-token context fills during a long `ignore_eos` generation,
and (b) an MoE expert-working-set effect, where early tokens are served from a small hot set
of experts and the working set expands toward all of them, degrading a partially offloaded
model toward its full streaming speed. The percentage figures look like (b). Converting them
to **cost per token of context** separates the two, and the existing data is enough.

At `strong` a single request spans the entire window (0 of 1 requests completed, aborted at
the deadline), so context grows monotonically and each interval's midpoint context is
computable from the cumulative token count:

| Model | ms/token, minute 1 → minute 10 | context grew by | **slowdown per token of context** |
|---|---|---|---|
| Qwen3-30B-A3B (MoE) | 82.3 → 135.9 | +3,863 | **17.6 µs** (runs: 13.9 / 18.2 / 17.6) |
| Mistral-Small-24B (dense) | 295.9 → 316.5 | +1,361 | **14.6 µs** (runs: 15.1 / 14.6 / −14.2) |

The two are within ~20% of each other despite a **3.6x difference in baseline per-token cost**.
That is what (a) predicts — an additive per-context-token attention cost, roughly
model-independent for similar layer counts sharing the same `q8_0` KV cache — and it is not
what (b) predicts, which would be an MoE-only effect.

The percentage gap is then fully accounted for by two multipliers, with no third mechanism
needed: the MoE reaches 2.8x more context (it generates faster) *and* its baseline per-token
cost is 3.6x lower, so the same absolute penalty is a far larger fraction of it. Checking the
model against the observation: MoE 17.6 µs x 3,863 = +68 ms on a base of 82.3 → −45% rate
(observed −45%); dense 14.6 µs x 1,361 = +20 ms on 295.9 → −6.3% (observed −6.5%).

**`standard` is not evidence either way**, despite being flat at the same `-c 8448`. It
completes 6 requests per run and **resets context every 4,096 tokens**, so it never tests
monotonic growth — its flatness is a steady state across resets.

**Residual uncertainty, and why this stays open.** The two µs figures differ by 20%, n = 3,
and one dense run has the opposite sign. This is *consistent with* KV growth rather than
proof of it. The decisive test is a context sweep at `strong` — the same model at `-c 2048`,
`4096`, `8448` — which would show the slope directly. Thermal is not formally ruled out but
does not fit: a thermal limit should hit the dense 24B and the 8B similarly, and it does not.
No die temperature is readable on this board.

### Consequence: `strong` does not have a single throughput number

If the decay is context-driven, then **a tok/s figure for `strong` is only meaningful with the
context length it was measured at.** 6.79 is the rate at roughly 4.2k tokens of context, which
is where the 10-minute clock happened to stop — it is the **last observed rate, not a
plateau**. Nothing had settled; the run ended mid-generation with context still growing.

Extrapolating the fitted line to a full 8,448-token context gives **~4.4 tok/s** for the MoE.
That figure is **EXPECTED, not MEASURED** — it is a two-point linear extrapolation and is
recorded as such. It matters because a router calibrating on 6.79 for a job longer than ten
minutes, or one that starts with a large prompt, would still be optimistic. In the other
direction, a minute-1 sample reads ~12.4 tok/s and would over-commit to `strong` by 1.8x.

**What the router actually needs from this tier is a rate as a function of context, not a
scalar.** That is a finding about the shape of `capability_profiles.toml`, not just its
values, and it should be settled by the context sweep before `strong` is promoted.

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

**3.2 memory — DONE, and it produced the hardest constraint in the spike.** Measured
2026-08-15 with the owner's real working set open (Opera, Chrome, Terminal), sampled every 5 s
across a 180 s window per condition. **The reported figure is the worst sample, not the mean** —
headroom that exists only on average is not headroom. Summary:
`SPIKE-001-3.2-headroom-summary.json`.

| Condition | worst-case free | in use | paging (pages/s) | verdict |
|---|---|---|---|---|
| working set, no model | 6.57 GB | 9.33 GB | — | baseline |
| working set + `standard` (Qwen3-8B, `-ngl 99`) | 2.85 GB | 13.05 GB | 10.8 avg | **coexists** |
| working set + `strong` (MoE, `-ngl 12`) | **0.27 GB** | 15.63 GB | **660.8 avg**, 1176 peak | **does not coexist** |

**The strong tier and the owner's working set cannot share this node.** Only 12 of the MoE's
layers fit in 7.2 GB of VRAM, so ~13 GB of its 17.8 GB of weights sit in system RAM; add a
9.3 GB working set and the demand exceeds 15.9 GB. The machine does not fail — it **pages**,
at 660 pages/sec against 10.8 for `standard`, with 4 GB of pagefile peak. That is measured, not
projected, and it is invisible to any check that only asks whether the model loaded.

Two consequences, both structural rather than cosmetic:

1. **The 3.4 human-present degradation mode must UNLOAD the strong model, not deprioritise
   it.** A scheduler that keeps it resident and merely lowers its priority will page the
   owner's browser — precisely the failure that mode exists to prevent.
2. **Residency cost is not a function of VRAM alone.** A fully GPU-offloaded model still costs
   ~3.7 GB of *system* RAM here (page cache for the weights plus process overhead), and the
   MoE costs ~13 GB. `capability_profiles.toml` needs a host-RAM cost per resident model or
   SPIKE-012's residency manager will decide on a number that omits 13 GB.

**And it makes 3.1's strong-tier figure conditional.** The matrix ran on an otherwise idle
machine, so 6.79 tok/s describes a state this node cannot be in while the owner is using it.
What `strong` sustains *while paging* is **not measured** and is expected to be materially
worse. Recorded as unmeasured rather than estimated.

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
| 3.2 memory headroom under real working set | **DONE** — 3 conditions, and the strong tier does not coexist | — |
| `strong` throughput WHILE paging | **OPEN** | 3.1's strong figures assume an idle machine |
| 3.3 storage + checkpoint commit | **DONE** | — |
| 3.4 network | closed as policy | — |
| 3.5 camera / audio | skipped for this node | — |
| 3.6 thermal / throttle | **DONE** | — |
| 3.6 wall power | **BLOCKED** on an instrument | a wall meter; SPIKE-011 names one |
| Finding 5 attribution | attributed to KV growth from existing data; **confirmation open** | a context sweep at `strong` (`-c 2048/4096/8448`), ~1 h |
| `strong` rate as a function of context, for the router | **OPEN** — blocks promoting `strong` | same context sweep |

Nothing here is on the F0 critical path. F0 was unblocked by ADR-002 and ADR-007 on
2026-08-14, and promotion of any figure above into `capability_profiles.toml` remains a
separate, deliberate act.
