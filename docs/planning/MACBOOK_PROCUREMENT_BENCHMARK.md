# VESPER — MacBook procurement benchmark (planning, ESTIMATED not measured)

**Status: PLANNING.** Like `HARDWARE_INVENTORY.md`, this file is deliberately kept OUT of
the normative set. It records a purchase decision and the evidence behind it. It is **not**
an input to any decision function.

Two rules carried over from the inventory, because they apply here with more force:

1. **Nothing here may be copied into `contracts/policy/capability_profiles.toml`.** Every
   throughput figure below for a machine we do not own is **ESTIMATED** — derived from
   published third-party benchmarks, not measured on the device. `CI-034` fails a build that
   fills a capability profile from a figure like these. When a MacBook is bought it enrols by
   the same path as every other node: it joins by measurement, and `SPIKE-001` is what
   measures it.
2. **Product names are allowed here** because this is planning prose. `docs/planning/` is not
   in `PRODUCT_NAME_SCOPES` (`tools/ci/checks.py`), which covers `routing`, `resources`,
   `policy`, `world`, `models` and `core`. The same devices appear in the specifications only
   by profile shape, and `CI-007` enforces that.

Last updated: 2026-08-16. Budget ceiling: **12 000 dh**. Rate used: **1 USD = 9.26 dh**.

Rendered version, with the price/performance chart:
`https://claude.ai/code/artifact/8a83f6e7-9cbf-4f64-9c13-662ca251e4cf`

---

## The decision

**Buy the MacBook Pro 14″ 2021, M1 Pro, 16 GB / 512 GB — asking 10 500 dh, target 9 500 dh.**

It is the only offer that stays under 12 000 dh once a charger is counted, and it sits in the
200 GB/s memory class, which is the spec that decides local generation speed. The two most
expensive machines offered — 15 000 and 16 000 dh — are **slower at local inference than this
one**, because Apple narrowed the memory bus on M3 Pro and the base M4 never had a wide one.

---

## The six offers, resolved

The reseller's descriptions are ambiguous in three places. Resolved specs:

| Rank | Machine | Chip | Bandwidth | Est. tok/s | Weight | Asking | With charger | Verdict |
|---|---|---|---|---|---|---|---|---|
| **1** | **MBP 14″ 2021 (A2442)** | **M1 Pro 8C/14C** | **200 GB/s** | **27.6** | **1.6 kg** | **10 500** | **11 200** | **Buy** |
| 2 | MBP 14″ 2023 (A2779) | M2 Pro 10C/16C **?** | 200 GB/s **?** | 29.5 | 1.6 kg | 12 000 | 12 700 | Verify chip |
| 3 | MBP 16″ 2021 (A2485) | M1 Pro 10C/16C | 200 GB/s | 28.4 | 2.15 kg | 11 500 | 12 400 | Fallback |
| 4 | MBP 16″ 2023 (A2780) | M2 Pro 12C/19C | 200 GB/s | 30.4 | 2.15 kg | 14 000 | 14 000 | Over budget |
| 5 | MBP 14″ 2023 (Mac15,6) | M3 Pro 11C/14C | 150 GB/s | 24.0 | 1.6 kg | 15 000 | 15 700 | Decline |
| 6 | MBP 14″ 2024 (A3112) | M4 base 10C/10C | 120 GB/s | 18.8 | 1.55 kg | 16 000 | 16 700 | Decline |

**All tok/s figures are ESTIMATED**, scaled from published llama.cpp Metal results for
LLaMA-7B Q4_0 by 0.78× to reach Qwen3-8B Q4_K_M (8.19B vs 6.74B parameters, plus the K-quant
penalty on Metal). None is a reading. For contrast, the existing desktop **measures 45.8 tok/s**
on that model — every machine above is a step down on raw inference. The MacBook is bought for
Xcode, portability and the primary-node role, not for inference speed.

**How the ambiguities were resolved.** The 16″ 2023 must be M2 Pro, not M3 Pro: the M3 Pro 16″
started at 18 GB, so a 16 GB unit dates it to the January 2023 machine. The 2024 M4 must be the
14″: the 16″ never shipped with a base M4. The 14″ 2023 is the one that stays open — see below.

---

## The gates

Binary, applied in order; machines ordered by gates passed, then by price. A rejection is
traceable to a named criterion, never to a preference for newer silicon.

| Gate | Criterion | Why | Failed by |
|---|---|---|---|
| 1 | Apple Silicon, runs current Xcode | The reason for the purchase: the iPhone app blocks `SPIKE-002`, which blocks `A-020` | none |
| 2 | ≥16 GB unified / ≥512 GB SSD | Xcode plus simulators needs the storage; 16 GB is the floor to hold the `standard` tier resident | none |
| 3 | ≤12 000 dh asking | The stated budget ceiling | 4, 5, 6 |
| 4 | 200 GB/s memory class | Token generation on Metal is bandwidth-bound, not compute-bound. Invisible on a price list | 5, 6 |
| 5 | Portable — travels site A↔site B | `HARDWARE_INVENTORY.md` records that everything portable travels. 1.6 kg vs 2.15 kg | 3, 4 |

Ranks 1 and 2 pass all five. Rank 1 wins on price alone — **rank 2 is a paid upgrade over
rank 1, not a better default.**

**Gate 5 is the softest of the five.** Gates 1–4 are binary facts about the hardware; gate 5 is
a weighting, and it is the one a different set of priorities could legitimately overturn. See
*Screen and cooling* below for what happens if it is weighted the other way.

---

## The two findings that invert the price list

### 1. Apple narrowed the memory bus twice, and the price list did not notice

M1 Pro and M2 Pro run a 256-bit bus at **200 GB/s**. M3 Pro narrowed it to 192-bit —
**150 GB/s**. The base M4 has never had a wide bus: **120 GB/s**. Because generation speed
tracks bandwidth almost linearly, the 16 000 dh M4 is estimated **32% slower** at the
`standard` tier than the 10 500 dh M1 Pro. The M4 wins single-core CPU and carries the longest
macOS runway — but it loses at the job it would be bought for.

### 2. Not one of the six reaches the `strong` tier

macOS caps GPU-wired memory near 75% of unified RAM: about **12 GB on a 16 GB machine**,
13.5 GB on the 18 GB M3 Pro. Read from the GGUF files themselves on 2026-08-17:
**Mistral-Small-24B Q4_K_M is 13.35 GB** and **Qwen3-30B-A3B Q4_K_M is 17.35 GB** — an earlier
revision of this line said 14.3 and 18.6, both estimated rather than measured. The 13.35 GB dense
model clears a 16 GB Mac's ~12 GB wired cap by less than nothing; the MoE does not come close.

This restates, on new hardware, what `SPIKE-001 3.2` already **measured** on the desktop: with
the owner working set resident, the strong tier left 0.27 GB free of 15.9 GB and the machine
paged at 660 pages/s — *DOES NOT COEXIST*. A 16 GB Mac does not escape that; unified memory
means the model competes with the working set in the same pool.

So the `strong` tier stays on the desktop or the API **whichever of these six is bought**, and
5 500 dh of extra spend buys no additional capability class. **RAM is soldered** — this is the
one irreversible spec on the page, and it is recorded here as a conscious accept, not an
oversight. It is also exactly the constraint the source anticipated: *"prefer models that fit
comfortably in unified memory / avoid swapping"* (`SRC-GAP-006`, ratified as part of COC v1.2).

---

## Screen and cooling — the 14″/16″ trade

Two criteria the gates under-weighted. Both are real and both favour the 16″.

| Attribute | 14″ | 16″ | Who wins |
|---|---|---|---|
| Display | 14.2″ · 3024×1964 | 16.2″ · 3456×2234 | 16″, **+31% screen area**. Same panel otherwise (XDR, 254 ppi, 120 Hz, 1000 nits) — bigger, not better |
| Fans, sustained CPU load | 5 500–5 900 rpm, ~48 dB | under 2 500 rpm | 16″, decisively. Same chip, larger heatsink and fans |
| Battery / charger | 70 Wh · 67 W | 100 Wh · 140 W | 16″, though the 140 W adapter costs more to replace |
| Weight | 1.6 kg | 2.15 kg | 14″, **550 g / 34% lighter** — the only line here that cannot be bought back later |

**Where the cooling cashes in, and where it does not.** The 16″'s thermal headroom pays off on
*compute-bound* work — long Xcode builds, prompt prefill, many agents at once. That is real and
it is part of this job. But the workload the gates were built around, **token generation, is
memory-bound**: the GPU waits on memory rather than burning watts, and never reaches the thermal
ceiling that separates the two chassis. The 16″ advantage lands on builds, not on the `standard`
tier.

**Why screen loses anyway.** Screen size matters only at a desk, and at a desk an external
display solves it. M1 Pro drives two external monitors; a 27″ panel is ~1 000–1 500 dh, well
under the price gap plus charger, and yields more usable area than a 16″ ever does. Weight has
no such escape — it is paid on every trip between the two sites.

**The condition that would flip the ranking.** The 16″ 2021 M1 Pro loses on one number:
11 500 + ~900 dh for a 140 W charger = **12 400**, past the ceiling. If that stretch is
acceptable *and* the machine will mostly live on a desk rather than in a bag, it becomes a
defensible first choice — and on sustained-work grounds it would then rank **above** the
12 000 dh 14″ M2 Pro, having the faster 10C/16C chip and the better cooling for the same money.
That is a change of weighting, not of fact: gates 1–4 are unaffected.

---

## Open question — blocks rank 2 only

**The 14″ 2023 at 12 000 dh has an unconfirmed chip.** That description fits two machines:

| If it is | Cores | Bandwidth | Est. tok/s | Worth |
|---|---|---|---|---|
| **M2 Pro** (Jan 2023, A2779) — 16/512 is its stock config | 10C CPU / 16C GPU | 200 GB/s | 29.5 | 10 500–12 000 dh |
| **M3 base** (Nov 2023, Mac15,3) — 16 GB is a BTO on an 8 GB base | 8C CPU / 10C GPU | 100 GB/s | ~16 | 9 000–9 500 dh max |

There is **no base-M2 14″ MacBook Pro** — the base M2 machine is the 13″ Touch Bar (2022) — so
"M2" without "Pro" is not one of the possibilities. M3 Pro is ruled out because it started at
18 GB.

Resolved by asking the seller for the **serial number** and checking it at
`checkcoverage.apple.com`. If it is an M3, the machine is not rank 2; it is last on value.

---

## Negotiation sheet

Derived from US resale comparables converted at 9.26 dh/USD, then lifted 15–25% for the
Moroccan market, where import duty and VAT raise the whole used price floor. A bargaining
range, not a valuation.

| Unit | US comp | Converted | Fair local | Asking | Target | Walk away above |
|---|---|---|---|---|---|---|
| 14″ M1 Pro 16/512 | $900–1 200 | 8 300–11 100 | 9 500–11 000 | 10 500 | **9 500** | 10 500 |
| 14″ M2 Pro 16/512 | $1 000–1 250 | 9 300–11 600 | 10 500–12 000 | 12 000 | 10 800 | 11 800 |
| 16″ M1 Pro 16/512 | $700–1 000 | 6 500–9 300 | 8 500–10 000 | 11 500 | 9 800 | 10 800 |
| 16″ M2 Pro 16/512 | $1 200–1 400 | 11 100–13 000 | 12 500–14 000 | 14 000 | 12 300 | 13 000 |
| 14″ M3 Pro 18/512 | $1 150–1 350 | 10 600–12 500 | 12 000–13 500 | 15 000 | 12 500 | 13 500 |
| 14″ M4 16/512 | $1 250–1 400 | 11 600–13 000 | 13 000–14 500 | 16 000 | 13 500 | 14 500 |

**One local comparable worth quoting back:** an M4 *Pro* 16″ with 24 GB / 512 GB was listed on
Avito at **15 500 dh** — more RAM, 273 GB/s, a genuinely faster machine for less than this
reseller wants for a base M4 at 16 000. Avito blocks automated fetching, so that is one
observed listing rather than a sampled market.

**Only the 16″ 2023 was described as including its box.** Every other row therefore carries
~700–900 dh for a charger, which is why "with charger" is the column that decides gate 3.

---

## Pre-payment checklist

1. **Serial number for every unit**, run at `checkcoverage.apple.com` — returns true model,
   manufacture window, warranty state. Resolves the M2 Pro / M3 question by itself.
2. **A photo of "About This Mac"** — it names chip and core counts exactly. "2023, 16/512" is
   not the same claim as "M2 Pro, 10-core CPU, 16-core GPU".
3. **System Report → Power → cycle count and condition.** Under 200 excellent, 200–500 good,
   over 500 price in a battery. "Service Recommended" means budget 1 500–2 500 dh. On a 2021
   unit this is the largest hidden cost.
4. **Confirm charger included and its wattage.** ~700–900 dh for a genuine adapter — enough to
   push a 12 000 dh machine past the ceiling.
5. **Activation Lock off and Find My signed out** *before* payment. A locked Mac is a brick.
6. **Run Apple Diagnostics** (hold D at boot); check the screen at full white and full black
   for the 14″/16″ display-cable and backlight faults; test every port, keyboard, speakers.
7. **Match the on-screen serial to the one printed underneath.** A mismatch means a replaced
   logic board or a stolen machine.

---

## What happens after purchase

The MacBook remains **excluded from the fabric until measured** — `HARDWARE_INVENTORY.md` is
explicit that it joins by measurement with no placeholder profile. On arrival:

1. Run `SPIKE-001` §3.1 and §3.2 on it — throughput per tier and memory headroom, the same
   protocol the desktop and the Kali laptop went through. **Those readings, not the estimates
   in this file, are what may reach `capability_profiles.toml`.**
2. Expect the `standard` tier to be the ceiling and the `strong` tier to fail the headroom
   check. If it does, that is the prediction above confirmed, and it belongs in the spike
   artifact as a measured result.
3. Only then does the iPhone app work start, which unblocks `SPIKE-002` and then `A-020`.
