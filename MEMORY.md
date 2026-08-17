# VESPER — memory

**What this file is.** The things worth remembering that are not derivable from the code,
the git history or the specification. Measured numbers with their provenance, mistakes
already made so they are not made twice, the doctrine that keeps getting rediscovered, and
the standing constraints of this particular setup.

**Not required reading.** It is a place to stand on. If a fact here contradicts a command's
output, **the command wins** and this file is stale — fix it.

**Maintained by appending.** Nothing here is deleted when it turns out to be wrong; it is
struck through and corrected, because the correction is usually the useful part.

---

## 1. The hardware, and what it actually does

### Node 1 — the site-A desktop (`DESKTOP-F73BBDB`)
Ryzen 5 5500 · 12 logical cores · **15.9 GB DDR4** · RX 6650 XT with **7.2 GB usable
VRAM, measured** · 475.9 GB disk · Windows 11 · llama.cpp `b10405-e79e4bf66`, Vulkan.

**Measured sustained throughput** (`SPIKE-001` §3.1, median of 3 × 10-min runs, GGUF sizes
read from the files themselves on 2026-08-17):

| Model | On disk | Fits in 7.2 GB VRAM | tok/s | size × tok/s |
|---|---|---|---|---|
| Qwen3-1.7B Q4_K_M | 1.19 GB | yes | 148.2 | 176 GB/s |
| Llama-3.2-3B Q4_K_M | 1.88 GB | yes | 98.7 | 186 GB/s |
| Qwen3-8B Q4_K_M | 4.68 GB | yes | 45.8 | 214 GB/s |
| Mistral-Small-24B Q4_K_M | 13.35 GB | **no** | 3.15 | 42 GB/s |
| Qwen3-30B-A3B Q4_K_M (MoE) | 17.35 GB | **no** | 6.79 | — |

### **The bandwidth law — the single most useful fact about this machine**

Generating one token requires reading **every weight the model activates**, once. So:

> **tokens/second ≈ effective memory bandwidth ÷ bytes read per token**

The three models that fit in VRAM all land at **176–214 GB/s** — the card's memory
bandwidth. The one that does not fit lands at **42 GB/s** — dual-channel DDR4.
**There is a ~5× cliff at the moment a model stops fitting in VRAM**, and after that
nothing but model size and RAM speed matters.

**This law predicts, it does not merely describe.** Use it before downloading anything:
a dense model of size *S* GB that does not fit in VRAM will run at roughly `42 / S` tok/s.

**What it rules out, permanently, on this node:**

| Idea | Why it fails |
|---|---|
| SSD / pagefile as RAM | Already in use — 27.6 GB allocated. It is what `§3.2` measured **failing** at 660 pages/s. NVMe is ~10× slower than RAM, so it makes the divisor worse |
| More GPU offload (`-ngl`) | The card physically holds 7.2 GB. Already maximised |
| Bigger pagefile / more virtual memory | Adds capacity. Capacity was not the binding constraint — speed is |
| Move work CPU → GPU | Token generation is **bandwidth-bound, not compute-bound**. Both processors already wait on memory |

**What does work: Mixture-of-Experts.** `Qwen3-30B-A3B` is larger on disk than the dense
24B, sits on fewer GPU layers, thrashes the pagefile — and is still **more than twice as
fast** (6.79 vs 3.15), because only ~3B of its 30B parameters activate per token.
**When shopping for a stronger local model, shop for MoE with a small active-parameter
count, not for a better dense model.**

### Memory coexistence (`SPIKE-001` §3.2, worst-sample not mean)

| Condition | Free at worst moment | Paging | Verdict |
|---|---|---|---|
| Owner working set, no model | 6.57 GB | — | Baseline. The owner's apps cost ~3.2 GB |
| \+ Qwen3-8B, all layers on GPU | 2.85 GB | 10.8 /s | **COEXISTS** |
| \+ Qwen3-30B-A3B, `-ngl 12` | **0.27 GB** | **660 /s** | **DOES NOT COEXIST** |

**A fully GPU-offloaded model still costs ~3.7 GB of system RAM** (page cache for the model
file plus process overhead). `-ngl 99` does not mean zero host memory, and a capacity plan
that assumes it will be wrong by 3.7 GB.

The coexistence boundary is **between 13.35 GB and 17.35 GB** — bounded on both sides by
measurement and not pinned more precisely by any run on record.

### Node 2 — the Kali laptop (`CSF`)
ASUS VivoBook · i3-8130U · 4 logical cores · **3.71 GB RAM** · Intel UHD 620 · **CPU-only**
· 112 GB disk. Availability class `on_demand`, **declared not measured**.

Its value is not compute. It is a **second real node** for distributed work, and a host for
long-clock tests that need wall time rather than power — the endurance harness is ~30 MB
and 5 threads, so this laptop runs it comfortably while the desktop does real work.

**Reaching it** (established 2026-08-17): `ssh -i ~/.ssh/vesper_node2 csf@192.168.100.102`,
key `vesper_node2` authorised in `~/.ssh/authorized_keys`. `sshd` had to be enabled once with
`systemctl enable --now ssh`. **ICMP is blocked in both directions — ping proves nothing here;
test TCP/22 instead.** Desktop↔laptop TCP works, so there is no AP isolation and `SPIKE-009`'s
premise is not blocked.

**It never sleeps, and that is why the alarm lives here.** Three layers, all verified live on
2026-08-17: a `logind` drop-in `10-vesper-nosleep.conf` (`HandleLidSwitch`/`ExternalPower`/
`Docked` = ignore, and `IdleAction=ignore` read back over D-Bus), xfce
`presentation-mode=true` with `inactivity-on-ac=0` / `lid-action-on-ac=0` / `dpms-enabled=false`,
and a `systemd-inhibit` lock. **The inhibitor does NOT survive a reboot** — it was gone when
checked; the other two layers did survive and are the load-bearing ones.

Audio: built-in **analog** HDA Intel PCH, PipeWire + `pipewire-pulse` + wireplumber.
`spd-say` ships; `alsa-utils` and `pulseaudio-utils` were installed 2026-08-17.
`csf` is in `audio` and (since 2026-08-17) `input`.

### Why the alarm is on node 2 and not node 1

Node 1's only audible outputs are the two monitors' **HDMI** speakers — the rear analog jack
and the headset are both inaudible in the room. Windows resumes from a timer wake with the
**panels dark**, and a dark panel has no audio endpoint, so the alarm plays into nothing.
`ES_DISPLAY_REQUIRED` prevents a panel sleeping but does **not wake one already asleep**, and
`SC_MONITORPOWER` from a locked session did not override it. Five rehearsals, five silences.

`CONSOLELOCK` is **not** what governs sign-in-on-wake on this machine: Windows Hello is
enabled, so Hello's policy wins and the legacy value is ignored — which is also why the
setting is absent from Settings. Setting it to 0 changed nothing.

Node 2 has none of these: analog speakers, no display in the path, and a session lock that
gates neither audio nor input.

### Other devices
Owner's phone (always on) · iPhone · Samsung Galaxy J3 (2016, 360×640 @ dpr 2, Android 5.1.1)
· MacBook (expected 2026-08-20) · several old tablets, camera usability to be audited.

---

## 2. Mistakes already made — do not remake them

| # | The mistake | The correction |
|---|---|---|
| 1 | Claimed node 1 could address **17.33 GB** by adding 8 GB VRAM to 9.33 GB free RAM | Falsified by measurement. KV cache, compute buffers and page-cache pressure all draw on the same 15.9 GB. Never sum VRAM and free RAM |
| 2 | Attributed the `§3.2` failure to **Mistral-Small-24B at ~14.3 GB** | Both halves wrong. It was **Qwen3-30B-A3B at 17.35 GB**. Sizes had been estimated and presented as measured, in documents whose whole argument is that estimates must not be. **Read the file sizes off disk** |
| 3 | Treated the 24-hour endurance test as urgent | It gates F5, which is **7th of 9** in the build order. It blocked nothing for weeks. Check the dependency chain before declaring an emergency |
| 4 | Said heavy work would perturb the endurance run, protecting the machine for a day | A tick counts late only when **more than a full 60 s** late. Generous, not a hair trigger. And **load can only make the test harder to pass**, so a pass under load is a *stronger* result |
| 5 | Said the alarm gate needed a hardware purchase | It needs a **platform check**, not hardware. `RUNBOOK-ALARM` requires acknowledgement with "no speech, no screen, no unlock" — a phone's **volume or power button** qualifies, and the runbook's own physical kill is "power down the loudest node" |
| 6 | Listed the owner decisions as pending work | Five resolved 2026-08-12; `006(a)` and `(b)` resolved 2026-08-14. Only `006(c)` is open and the file itself says it **blocks nothing** |
| 7 | Copied a live SQLite store to preserve evidence | `SPIKE-008` lost **300 committed rows** doing exactly this — a copy passed `integrity_check` and was still short. Use `con.backup()`, or open `mode=ro`. **Always verify the copy's record count against the original** |
| 8 | Eyeballed a colour palette instead of running the validator | Three rounds of failures. Run the checker |

---

## 3. Doctrine that keeps getting rediscovered

- **Measured or absent.** `capability_profiles.toml` takes measured values only; `CI-034`
  fails a build that fills it from a datasheet. **Unmeasured is treated as unavailable, not
  as available.** Measured-but-unpromoted is a correct and deliberate state.
- **Pre-register the reading before the result exists.** `A-029-E1-PREREGISTRATION.md` fixed
  how a leak check would be read at hour 12.4, before hour 24 arrived. It worked: the
  projection was falsified and the escape hatch was never needed. A rule written after the
  number is a rule fitted to the number.
- **VOID vs FAILED.** An environment defect must never be laundered into a product defect —
  or the reverse. `AT-03` voids a run **only** if the external ingress was unavailable. An
  externally killed process is neither void nor failed; it is a **recorded partial**.
- **A negative control is the point.** A test nobody has seen fail proves nothing. Every
  gate here carries a deliberately broken build that must fail — and the most important run
  in the programme is `C1`, the fake cron build that must fail the anti-cron check.
- **A control should differ from the real run in exactly one variable.** This is why a
  24-second `C1` against a 24-hour `A-029` is questionable: it differs in two.
- **"I could not check it" must never read the same as "it passed."** Unverifiable is a
  failed assertion, not a skip.
- **Judge from the durable log, not from the component's own account of itself.** The
  harness's in-memory list and the event log are two instruments; a disagreement between
  them is a failure of the run, not a detail to reconcile afterwards.
- **A criterion the window cannot exercise is not a criterion.** A bound of 10,000 that a
  24-hour window can only reach 1,440 of will pass without ever being tested.
- **State the hole.** A reconstruction from two endpoints with a 9-hour gap in the middle is
  worth more when the gap is named than when it is smoothed over.

---

## 4. Standing constraints

- **Product names are forbidden** in `routing/`, `resources/`, `policy/`, `world/`,
  `models/`, `core/` — enforced by `CI-007`. They are **legal in `docs/planning/`**, which
  is not in the scanned scopes. Verified, not assumed.
- **`--profile release` failing is correct**, not a defect. It fails on depth: seven SRs
  below `SPECIFIED`, each naming the artifact that would raise it.
- **The runtime executes from a pinned artifact ≠ the working repository.** It may open a
  proposal, never self-merge. Overnight coding is deliberately **unrestricted**; only
  *merge* is gated.
- **SQLite sidecars (`*.db-shm`, `*.db-wal`) are git-ignored.** Evidence stores committed
  under `docs/planning/spike-results/` must be **WAL-consolidated snapshots**.
- **The alarm overrides everything** — quiet hours, ambience policy, resource yielding, the
  interruption budget. A quiet-hours setting suppressing an alarm is a bug, not a
  configuration choice.

---

## 5. Open questions, recorded rather than resolved

1. **What window must `C1` run for?** `AT-03` calls it the most important run in the
   programme and specifies no window. `CI-027`, the check that would settle it, is
   `impl = "PENDING"`. Current evidence is 24 seconds at a 0.25 s cadence.
2. **The `ADR-001` / `ADR-012` authority question.** Both carry `ACCEPTED` stamped by an
   engineering pass rather than by the owner. Recorded, not resolved.
3. **`OWNER-DECISION-006(c)`** — whether four decision records carried inside REM specs get
   their own numbers. Blocks nothing.
4. **Which of the owner's cameras expose a driveable capture indicator and a physical off.**
   The Monday audit answers it; a whole stage depends on the answer.
5. **Can an app capture a hardware-button press while the device is locked**, per platform?
   `SPIKE-003`. The alarm's acknowledgement channel depends on it.

---

## 6. Where things live

| | |
|---|---|
| Handoff / live verification figures | `VESPER_ENGINEERING_STATUS.md` |
| Current plan | `PLAN_2026-08-17.md` |
| Build order and gate placement | `docs/architecture/IMPLEMENTATION_SEQUENCE.md` |
| Acceptance tests (the normative ones) | `verification/acceptance/AT-0*.md` |
| Measurements | `docs/planning/spike-results/`, with `README.md` as the record |
| Owner decisions | `docs/decisions/OWNER_DECISIONS.md` |
| Endurance evidence, 23 h partial | `docs/planning/spike-results/A-029-endurance-2026-08-16/` |
| Procurement and model evaluations | `docs/planning/MACBOOK_PROCUREMENT_BENCHMARK.md`, `QWEN38_27B_EVALUATION.md` |
