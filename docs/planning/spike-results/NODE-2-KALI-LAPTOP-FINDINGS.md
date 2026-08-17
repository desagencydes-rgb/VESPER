# Node 2 — the Kali laptop: onboarding findings

**Written 2026-08-14 from the machine itself, following `docs/planning/NODE_ONBOARDING_KALI_LAPTOP.md`.**
This is the second candidate node. Node 1 is the site-A desktop. Everything below is
measured on this machine unless it says otherwise; where a thing is declared rather than
measured, it says so, because that distinction is the whole point of this corpus.

The §0 gate ran clean on a fresh checkout before any of this:
`traceability_lint` PASS, `reference_lint` PASS, `ci/checks.py all` 11/11. So every
measurement below was taken against the same tree node 1 measured on.

---

## What this machine is

Measured read-only from the running system (`hostnamectl`, `lscpu`, `free`, `lspci`,
`lsblk`, `profile_node.py system`).

| Component | Value | Note |
|---|---|---|
| Model | ASUS VivoBook S14 **X430UA** | firmware X430UA.304, dated 2019-05-22 |
| CPU | Intel **Core i3-8130U** | 2 cores / 4 threads, 2.2 GHz base, 3.4 GHz max; AVX2/FMA/F16C |
| RAM | **3.71 GB** | single channel; 3.9 GB swap partition on the SSD |
| GPU | Intel **UHD Graphics 620** (integrated) | **no discrete GPU**; shares system RAM |
| Storage | 128 GB **SanDisk SD9SN8W** SATA SSD | 112 GB usable, 68 GB free before cleanup |
| OS | **Kali GNU/Linux Rolling 2025.3** | kernel 6.16.8+kali-amd64 |
| Firmware security | **TPM 2.0 present** (`/dev/tpm0`), root filesystem **not** LUKS-encrypted | bears on trust-zone Z0 — see below |

**The headline is the RAM and the absence of a discrete GPU.** This is a low-end 2018
ultrabook. It is not a compute node in the sense the site-A desktop is, and nothing below
should be read as if it competes there. Its candidate role is the one the fabric actually
lacks — the always-on control-plane host — and that role is about *availability and trust*,
not tokens per second. The two questions are kept separate throughout.

---

## SPIKE-008 criterion 9 — the cheapest, highest-value deliverable

Ran the full blocking suite, stdlib only, exactly as the onboarding doc specified:

```
python3 tools/spike/validate_persistence.py all --writes 10000 --trials 500 --commits 500 \
  --out docs/planning/spike-results/SPIKE-008-adr002-validation-kali.json
```

Node: Linux, Python 3.13.11, **SQLite 3.46.1** (node 1 was Windows). This matters —
criterion 9 asks whether the five stores open *on every candidate node class*, and a Linux
result on a different SQLite build is exactly the second data point it needs.

| Section | Criterion | Result on this node | Node 1 (for contrast) |
|---|---|---|---|
| 1.1 fencing, compliant | 1 — zero stale-epoch writes | **0 stale** at 2/4/8 writers | 0 stale |
| 1.1 fencing, control | 2 — non-compliant build **must fail** | **FAILS**: accepted **1 839 / 3 175** stale writes at 2/4 writers | fails: 119 / 167 / 186 |
| 1.2 crash safety | 3 — zero torn transactions | **0 torn** across **500/500** armed trials | 0 torn |
| 1.2 crash safety | 4 — audit chain unbroken | **0 broken chains**, all 5 stores recovered every trial | intact |
| 1.3 checkpoint | 5 — p95 within 200 ms | **p95 = 0.07 ms** (p50 0.03, max 1.74), synchronous=FULL | p95 1.17 ms |
| 1.3 checkpoint | 6 — checkpoint acked before step | 0 ordering violations | ok |
| 1.4 append-only | 7 — UPDATE/DELETE blocked at storage | **all blocked** (SQLite BEFORE trigger, RAISE(ABORT)) | blocked |
| 1.5 upcasting | 8 | **PASS 2026-08-16** on node 1 — `core/codec.py` exists now that F0 has shipped | PASS |
| 1.6 portability | 9 | see below | NOT_RUN |

**Two findings worth carrying, neither of which is "it passed":**

1. **The negative control fails *harder* on this node than on node 1** — the read-then-write
   build accepted 1 839 and 3 175 stale writes (2 and 4 writers) where node 1 saw 119–186.
   Same defect, far wider exposure. The read-modify-write race window is a function of CPU
   speed and scheduler: a slower 2-core CPU under the Linux CFS scheduler leaves the window
   open much longer than node 1's machine did. This does not change the verdict — both
   controls fail, which is all criterion 2 requires — but it is a concrete demonstration that
   *the control is measuring something real*, and that the amount of corruption an unguarded
   write path produces is hardware-dependent and can be large.

2. **The checkpoint budget has ~2 800× headroom here** (0.07 ms against 200 ms), even more
   than node 1's ~170×, on strictly weaker hardware. Linux `fsync` on this SATA SSD is simply
   very cheap for a WAL checkpoint of this size. The 200 ms budget is in no danger on either
   node class measured so far.

**On criterion 9 specifically — stated precisely, because the onboarding doc slightly
over-promised it.** The doc said "you are the second node class … [criterion 9] was left open
for exactly one reason: only one node was enrolled." That is the right instinct, but the
harness itself still records criterion 9 as **OPEN**, and it is right to. §1.6 portability is
`NOT_RUN` because a single-node harness cannot test "every candidate node class" from one
machine — closing 9 formally needs the results *collated across* nodes, and in particular
needs the **foreground-only** class (the iPhone/J3), which this laptop is not. What this run
delivers is the substantive thing: a **second, independent node class** — different OS,
different SQLite, different filesystem — on which all five stores open and every blocking
criterion passes. That is real evidence toward 9; it is not the closure of 9. The closure is
a collation act plus the foreground-only node, and it stays owner/reviewer work.

**One limit the harness records about itself, and I am repeating rather than burying:** the
crash trials are **SIGKILL, not power-cut**. A process kill does not exercise the drive's
write cache the way pulling power does. So criterion 3 is *partly* closed on this node — the
SQLite/WAL layer is validated, the SSD's flush-on-power-loss behaviour is not. A real
power-cut trial on at least one node is still outstanding, on either node class.

---

## SPIKE-001 §3.1 throughput — CPU-only, because that is what this machine is

The onboarding doc said: *check the accelerator first, do not assume; if it is CPU-only, that
is the finding and a CPU-only figure is still a real profile.* It is CPU-only. The UHD 620
iGPU exists but (a) shares the 3.71 GB system RAM so it buys no VRAM, (b) is a very weak part,
and (c) Vulkan/OpenCL are not even installed. The reproducible profile of this machine is its
CPU, and that is what was measured — with the prebuilt `llama.cpp b10431 ubuntu-x64` (CPU)
build, no `-ngl`.

Model: **Qwen3-1.7B Q4_K_M** — deliberately the *draft* tier and one of node 1's two draft
models, so the numbers are directly comparable. Loading it leaves ~1.9 GB free; a 3B model
(node 1's other draft model) would sit on the edge of swap on 3.7 GB and was not used, so this
node's draft figure is Qwen3-1.7B only.

Launch command recorded verbatim (the flags *are* the configuration under test):
`llama-server -m Qwen3-1.7B-Q4_K_M.gguf -c 1024 --parallel 2 -t 4 --host 127.0.0.1 --port 8080`
(CPU-only, no `-ngl`).

Full protocol: 3 × 10-min runs per condition. Median, with min–max spread (criterion 6 wants
both). **Read the wall-clock column** — it is the one the router consumes.

| Condition | gen rate (sustained) | **wall-clock (effective)** | wall spread | contention |
|---|---|---|---|---|
| draft, idle | 11.02 | **10.26** | 9.18–10.42 | — |
| draft, concurrent | 7.70 | **7.19** | 7.12–7.23 | **−29.9%** |

**A node-class finding, not just a number: on a CPU-only node the two-rate distinction
collapses.** Node 1's sharpest throughput lesson was that `sustained` (generation-time) is
*structurally blind* to CPU contention — on its GPU the generation rate moved −0.2% under load
while wall-clock moved −37%, because the synthetic load is CPU-bound and never touches the
accelerator. On this machine there is no accelerator: generation happens on the same CPU the
load contends, so **both** metrics fall together (−30.1% generation, −29.9% wall-clock). The
gap node 1 had to warn about does not open here. This does not retire node 1's rule — the
router must still consume `effective_tokens_per_sec` — it explains *why* the rule mattered
there (a GPU node) and why the two columns happen to agree here (a CPU node). Recorded so a
future reader does not "discover" the agreement and mistake it for the metrics being
interchangeable in general; they are not.

The idle spread has one low run (9.18 against 10.26/10.42); the concurrent spread is very tight
(7.12–7.23). No thermal collapse was seen across the 30-min windows, but this is a passively
cooled ultrabook and a longer or hotter run could differ — not claimed beyond what was
measured.

**The comparison that matters for design:** node 1 sustained ~151 tok/s on this exact model
on its GPU. This node does ~10–11 tok/s on CPU — roughly **14× slower**. That is the honest
ceiling. It means this machine can run a 1.7B model for light background classification or
routing work, but it is not a voice-latency or interactive-inference node, and it must never
be routed hard work. As a *fallback* local inferer for the control plane when the desktop is
asleep in another city, ~10 tok/s at 1.7B is a real, if slow, capability rather than nothing.

§3.2 (memory headroom) and §3.3 (storage) were run:
- **§3.2 memory:** total 3.71 GB, 2.18 GB available at rest. The protocol's real figure —
  headroom *with the owner's working set loaded* — must be taken with their actual apps open;
  recorded as a point-in-time reading, not the protocol figure. On a 3.7 GB machine this is
  the binding constraint, not compute.
- **§3.3 storage:** sequential write **112 MB/s**, random-4k write **~10 100 IOPS**, no swap
  during the run. Healthy SATA SSD; not the bottleneck for a control plane.

---

## Availability — the honest answer, and the one node 1 got wrong

Node 1's mistake #4 was a 7-day sampler that ran *on the machine it was measuring*, so it
could not observe the machine while off. I did not repeat it. Instead I read what the machine
has already recorded about itself: the **persistent** systemd journal (`/var/log/journal`
exists), which holds boot and suspend history back to **2025-11-11** — 277 days.

**What the machine has actually done (measured):**

| Metric | Value |
|---|---|
| Observation span | 277 days (2025-11-11 → 2026-08-14), persistent journal |
| Distinct boot sessions | **87** |
| Median session length | **~44 minutes** (0.74 h); 77 of 87 sessions are under a day |
| Calendar days with *any* activity | 168 of 277 — **61%** |
| Calendar days completely dark | **109** (39%) |
| Longest continuous-off gaps | **21.6 days**, 15.9 days, 15.3 days, 12.3 days |
| Lid behaviour | **suspends on lid close** (systemd default; xfce4-power-manager owned the event) |

This is the profile of a personal working laptop that is switched on for an hour, used, and
switched off — 87 times over nine months, dark on two days in five, and once powered off
completely for **three weeks**. **As measured, this machine is not `always_on` and not
`usually_on`. Its measured class is `on_demand`,** the same as the desktop, arrived at from
the opposite direction (the desktop is a powerful machine left off; this is a portable one
carried around).

**What is intended is a different statement, and it is not a measurement.** The owner's plan
is to leave this machine powered and dedicated to VESPER. If honoured, that makes it
`always_on` by *declaration* — exactly the structure node 1's desktop got, and exactly as
load-bearing: `INV-TRUST-2` forbids continuity-critical capability on a node that can be off
with no way back, so the declaration is safe only as long as the machine is in fact left on.

**Two things make this laptop a *better* declared-always_on candidate than the desktop:**

1. **It travels with the owner.** The desktop's disqualifying property (SPIKE-010: it will be
   in site A, unwakeable, while the owner is in site B) does not apply here. This machine is
   wherever the owner is, so "off with no way back" degrades to "off, and a human who is
   present can turn it on" — which is a far weaker failure mode.
2. **A human is always near it**, so the wake path is trivial and needs no WoL, no relay, no
   always-on site-A-side agent.

**Two things make it a *worse* one:**

1. **3.71 GB RAM.** Hosting VESPER's control plane *and* being the owner's daily-driver Kali
   box at the same time competes for a very small memory budget. The control plane is light,
   but "dedicated to VESPER" and "my working laptop" are in tension on 3.7 GB in a way they
   would not be on 16 GB.
2. **It is the owner's personal machine**, so the operating commitment ("leave it on, don't
   close the lid to sleep, don't repurpose it") is a commitment about their own daily tool,
   which is harder to keep than the same commitment about a dedicated desktop.

---

## The verdict on the control-plane-host gap

`SPIKE-001` pass criterion 3 needs at least one node meeting `control_plane_host`:
`trust_zone = Z0` **and** `availability_class ∈ {always_on, usually_on}`. No enrolled node
meets it. Can this laptop?

**On availability:** not as measured (`on_demand`), but plausibly as *declared* `always_on`
under the owner's operating commitment — and with a materially safer failure mode than the
desktop because it travels with the owner and is human-wakeable. This is a real candidate, not
a disqualified one.

**On trust zone Z0:** unresolved, and not mine to resolve. Z0 is the top trust zone and its
`key_storage_class` requirement is governed by `ADR-007` (node cryptographic identity), which
is **not yet ratified**. What is measurable: this machine has a **TPM 2.0**, which is the
hardware a strong `key_storage_class` would bind to — a point in its favour — but its root
filesystem is **not encrypted**, which is a point against holding Z0 secrets on it as it
stands. Whether this node can be Z0 is an `ADR-007` question with a disk-encryption
precondition, flagged here for the owner, not decided here.

**Net:** this laptop is a **viable interim control-plane host** — the only enrolled device
that plausibly fills the fabric's one structural hole today — *conditional on* (a) the owner's
availability commitment being real and honoured, and (b) the `ADR-007` / disk-encryption path
to Z0 being walked. It should be treated as the bridge, not the destination: the structurally
right answer remains a mains-powered machine that stays put — **the repaired site-A desktop**
(the standing candidate) or the **forthcoming MacBook** — because neither puts the fabric's
continuity core on someone's daily-driver ultrabook with 3.7 GB of RAM. Per `INV-TRUST-2`, a
clear "interim yes, with conditions" is more useful than an unconditional yes that a later
reboot or a closed lid would falsify.

---

## Machine preparation (owner authorised, 2026-08-14)

See `MACHINE-PREP-KALI.md` for the itemised cleanup log and the keep-awake configuration.
Summary: **~14 GB reclaimed** (regenerable caches, emptied trash, and a round of owner-selected
app/tool/model removals — Eclipse, Antigravity, mtkclient, Evil-Droid/FuzzyAI, Ollama and
InsightFace models, an old kernel); Code-OSS and the active `.pyenv` Python were kept by owner
choice. **All sleep/blank paths disabled** at the owner's explicit request ("I won't be here to
wake it") across three independent layers (live `systemd-inhibit` lock, xfce settings, and a
logind drop-in that makes it reboot-proof). **Timezone corrected** to Africa/Casablanca. No
credentials, keys, network config, Wi-Fi driver trees, or unidentified files were touched.

---

## Mistakes and caveats to carry forward

- **The duty-cycle figure is easy to overstate.** A naive "sum of session spans ÷ observation
  span" gives 45%, but that counts suspend/hibernate time as "on" — 10 of the 87 sessions span
  more than a day and are mostly suspend. The honest metrics are the ones above: 61% of
  calendar days had any activity, median session ~44 min. I nearly published the 45%.
- **The clock is set to a US Eastern (EDT) timezone** on a machine that lives in Morocco. Not
  acted on, but noted: any scheduling or time-of-day logic that assumes local wall-clock will
  be wrong by ~5–6 hours until this is corrected.
- **The throughput "idle" condition was run while the owner was away**, which is the *cleanest*
  possible idle (no contention) — but on a 3.7 GB machine the more decision-relevant number is
  headroom *with the owner's working set loaded*, and that has not been taken. The CPU tok/s
  figure is the ceiling, not the in-use figure.
- **Criterion 9 is advanced, not closed** (see SPIKE-008 above). Do not let this report be
  cited as closing it.
</content>
</invoke>
