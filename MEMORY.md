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

> **THERE ARE TWO `llama-server.exe` ON THIS MACHINE AND ONLY ONE IS COMPARABLE.**
> Use `C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe` — that is
> `b10405-e79e4bf66`, and every figure in the table below was measured with it.
> `C:\Tools\llama-cpp\llama-server.exe` is build **8631**, a different
> checkpoint. It starts, loads, and emits tokens perfectly well; the figures
> simply are not comparable to these, and nothing says so. The comparable one
> is the **9 KB** file, not the 14 MB one — it is a launcher against 52 DLLs.
> `PLAN_2026-08-18` named the wrong path; `run_tier_matrix.ps1` names the right
> one. See `docs/planning/spike-results/SPIKE-001-RUNNER-BINARY-TRAP.md`.

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

## 4b. What the night of 2026-08-17/18 established, and what it cost to learn

### The instrument, not the operator (SPIKE-004)

`spike004_ghost.html` was written on a desktop in CSS that the target handset's
**Chrome 55** cannot parse — `display:grid` (Cr 57), `place-items` (59), `min()`
(79), flex `gap` (84), `inset` (87), `aspect-ratio` (88). **An unsupported
declaration is dropped silently**, so it looked correct everywhere except on the
one device it is for. Four of the six tests rendered *nothing*, and a commit had
already blamed the operator for recording defaults.

**Three field runs were lost to this, in three different ways**, and the general
lesson is worth more than any of them: *before concluding a reading is the
operator's fault, establish that the instrument could show them anything.*

- The tap zones measured **0 × 0**, so the level control had no hit target.
- The first `baseline` pass ran with `flip` and `mirror` **on** — meaningless on
  a bare panel with no fold — so it measured how small reversed text can be
  read. `glyph height` came back 40 px, the *largest* value on the scale.
- The next two ran on a page loaded **before** the fix, from a tab nobody
  reloaded, and nothing in the record said so.

**Fixed, and the fixes are the reusable part.** The page POSTs a capability
probe on load (`CSS.supports()` plus measured rects), the server substitutes the
served file's own sha256 for `__BUILD__` so a stale page cannot hide, `baseline`
forces the transforms off, and the wrapping `layout` button became three
non-wrapping ones. **SPIKE-004 still has zero valid readings.** It is parked and
it blocks nothing — its own §1 says so.

### `DF-PLACE` had two gaps that only show up when you implement it

1. **`hosts` filters on trust zone alone**, which makes `A-048.4` unsatisfiable:
   a `Z0 foreground_only` node would be a top-ranked *full* host and survival
   would never be entered on any topology. `INV-PLACE-3` says survival begins
   when no **full host** is reachable, and `INV-TRUST-2` permits runtime
   survival exactly there — those cohere only if such a node is never a full
   host. `core/placement.py::is_full_host` encodes that, with the alternative
   reading named in case the corpus meant the literal one.
2. **The degradation bypass is listed after two gates that have already
   returned**, so it is dead code as written. `INV-PLACE-2`'s prose governs and
   the bypass goes first.

**The survival core is ALL-OR-NOTHING.** Filling it greedily makes it partially
satisfiable, and the property harness found what that produces: at pressure 0.75
a core member fell out for want of storage, and at 0.95 three others stopped
fitting, released their budget, and **it came back**. A core that reappears as
conditions worsen is not a core.

**A ratio test needs a magnitude whose ratios mean something.** The first scalar
score was additive with availability weighted +1000, so a node with **twenty
times** the throughput scored 9% better and placement returned KEEP.

### Reaching node 2, and what is armed on it

`ssh -i ~/.ssh/vesper_node2 csf@192.168.100.102` — the username is **`csf`**,
recorded here because probing six plausible names found none of them and this
file already had the answer.

**The 09:00 alarm is a detached process, not a timer.** `pid 32626`,
`alarm_night.py fire --at 2026-08-18 09:00`, reparented to init, one long
`time.sleep()` to five minutes before due. **There is no systemd timer and no
cron behind it**: if the process dies or the machine reboots, there is no alarm
and nothing will say so. That is the single largest fragility in the alarm
setup and it is recorded rather than fixed, because changing it at 01:40 on the
night it has to work is the wrong time to test a change.

`A-034.2` (partition, both sides live) is **no longer blocked on capability** —
two real nodes and key-based SSH both exist. It was deliberately not run on the
night of 08-17/18 because it requires partitioning the network on the machine
holding that alarm.

---

## 4c. The alarm on node 2 — what the day of 2026-08-18 established

### The `arm` subcommand cannot run on the node the alarm lives on

`tools/ops/alarm_night.py arm` is **Windows-only**. It shells out to
`powershell -Command Register-ScheduledTask ... -WakeToRun`, and node 2 has
neither `powershell` nor `pwsh`. It is a leftover from when the alarm lived on
node 1.

**So the only usable path on node 2 is `fire` launched detached** — which is
precisely the single point of failure, and it is not an oversight in the
operator's habits, it is the absence of an implementation.

### "This node needs no wake step" is a premise, not a guarantee

`alarm_node_linux.py`'s header states *"THIS NODE NEEDS NO WAKE STEP … there is
no rtcwake, no wake timer, and none of the class of failure that comes with
them."* That is true **only while the three stay-awake layers hold**, and
nothing was checking that they do. Measured 2026-08-18:

| | |
|---|---|
| `HandleLidSwitch/ExternalPower/Docked` | `ignore` — present in the drop-in |
| `IdleAction` | `ignore`, read live over D-Bus |
| xfce `presentation-mode` / `inactivity-on-ac` | `true` / `0`, read live |
| `sleep.target`, `suspend.target`, `hibernate.target` | **`static` — NOT masked** |
| `/sys/class/rtc/rtc0/wakealarm` | **empty — no RTC wake armed** |

Lid close and idle are covered. **A manual suspend or a power-off is not**, and
a suspended laptop will not ring, because there is no wake path to ring it.

### The watchdog restores the primary; it never fires

`tools/ops/alarm_watchdog.py` + a `systemd --user` timer every 2 min. One
firing path exists at all times, so a double alarm is structurally impossible
rather than merely unlikely. Three refusals: stale intent, already-completed
due, live primary. Live primary is matched by reading argv out of `/proc` —
`pgrep -f` matches the launcher wrapper *and the shell running the pgrep*, and
a watchdog that matches its own command line concludes "all is well" over a
dead alarm.

**`Linger=yes` is set. Autologin is deliberately NOT.** Autologin removes the
laptop's login password; that is a security trade the owner makes, not one
engineering makes with a sudo password handed over for a different purpose.
Audio was measured reachable from a `systemd-run --user` unit with no
graphical session, so autologin looks unnecessary — **expected, not verified.
The only thing that verifies it is an attended reboot.**

### The failure worth remembering, because of how it presented

The watchdog's first version passed every refusal test and did not work.
`Popen(start_new_session=True)` detaches from the terminal but **not from the
systemd cgroup**, and the watchdog is a `Type=oneshot` unit whose `KillMode`
defaults to `control-group`. Systemd killed the restored alarm the instant the
watchdog finished — 2 ms after launching it.

The journal recorded `{"action": "relaunch", "relaunched_pid": 518375}` and the
unit recorded `Result=success`. **Both were true statements about what the
watchdog did, and the alarm was dead anyway.** It is the `spd-say` lesson in a
new place: exiting 0 is a self-report, and the fact is whether anything is
running. The fix goes through `systemd-run --user` into its own transient unit
and then re-reads `/proc`.

### `A-034.2` is blocked on transport, not on the alarm

The note written on 2026-08-17 said `A-034.2` was ready and held back only
because node 2 carried the alarm. **That was wrong.** `A-034.2` partitions two
live control-plane sides, and a repo-wide search for sockets, HTTP servers,
asyncio servers or RPC finds exactly one network binding in the tree — the
SPIKE-004 ghost instrument. Key-based SSH is the *operator's* access channel,
not VESPER's control plane. F0's original note was the accurate one. The real
blocker is `SR-016`/`SR-017`, both still `DESIGNED`.

### The iPhone alarm rung is a system behaviour, not something to build

**AlarmKit** (iOS/iPadOS 26+) rings on the Lock Screen, StandBy and Dynamic
Island through silent mode, and **a volume-button press dismisses it** — an
Apple DTS engineer states this directly. That is `41.3`'s no-speech/no-screen/
no-unlock acknowledgement, delivered as a system behaviour.

The cost is an **entitlement Apple reviews**, which is exactly the risk
`SPIKE-003` §2 names in advance: *"entitlements are frequently documented and
unobtainable."* It counts when it is held, not when it is cited. **Android is
the cheaper second rung** — `MediaSession` + a foreground service, no
entitlement, and what every alarm app on the platform already does.

Full record: `docs/planning/spike-results/SPIKE-003-ACK-CHANNEL-PARTIAL.md`
and `ALARM-SPOF-OWNER-ACTIONS.md`.

## 4d. The night of 2026-08-18/19 — CI, and what a minimum means

### `capability_profiles.toml` is no longer entirely UNKNOWN, and it gained ONE number

**`voice_interaction.sustained_tokens_per_sec_min = 7`.** Everything else is
still `UNKNOWN`, deliberately.

**The rule this established, and it is the useful part:**
`sustained_tokens_per_sec_min` is **what a capability needs**, not what a
machine achieved. Copying `SPIKE-001` throughput into it would pass `CI-034`,
look measured, and encode nothing but "whatever this desktop did in August" —
with the minimum *rising when you buy better hardware*, which is backwards.

The 7 comes from a requirement: generation must outpace speech delivery or the
voice stalls mid-sentence. ~150 wpm × ~1.3 tokens/word ≈ **3.25 tok/s
break-even**, doubled for jitter. It discriminates against the measured tiers —
the 24B dense at 3.05 **cannot** host voice, the 30B MoE at 7.12 barely can, the
8B at 45.8 does comfortably — and that agrees with the bandwidth law.

Full rationale, including what was deliberately not promoted:
`docs/planning/spike-results/SPIKE-001-B4-PROMOTION-RATIONALE.md`.

### All twelve v3 throughput reports are on ONE checkpoint

`b10405-e79e4bf66`, read from the **server's own `build_info`**, not from the
string passed to the harness. `SPIKE-001` §3.1 forbids comparing across
checkpoints and three published MoE figures had come from three. Fixed.

| Tier | idle | concurrent |
|---|---|---|
| `draft` Qwen3-1.7B | 148.2 | 153.0 |
| `small` Llama-3.2-3B | 100.2 | 101.0 |
| `standard` Qwen3-8B | 45.8 | 47.0 |
| `strong` MoE 30B-A3B | 7.45 | 7.12 |
| `strong` dense 24B | 3.07 | 3.05 |

The corrected sampler did **not** move the numbers — it made them comparable.

### The audit record rounded the number it is judged by

`autonomy.loop_stalled` is `INV-AUTO-1`'s evidence. The watchdog decided
`since > limit` on raw floats and published `round(since, 3)` beside a raw
`limit`. **`3 * 0.2 = 0.6000000000000001`**, so any gap in (0.6, 0.6005) was
recorded as `0.6` — not greater than the limit. The record contradicted the
decision that produced it, and anyone checking the arithmetic on a real stall
would have found a report saying the limit was never exceeded.

Half a millisecond wide, so it passed here and went red on a differently
scheduled runner. **Rounding is presentation; a payload is evidence. Record what
was compared.**

### A red gate that lists what is always owed has not said what broke

`checks.py` printed the last six lines of an acceptance runner's stdout. Every
runner ends with the same closing block, so a failure showed the standing "owed"
notes — the 24 h endurance run, the alarm hardware cases — and never the
assertion that broke. Three separate CI failures were unreadable because of it.

It now surfaces `[FAIL]` case lines and `MISS` assertions first. `expected-fail`
lines are excluded: those are negative controls behaving correctly, and a
control that **passes** is the defect.

### One case, three failures, one cause

`A-029-RT` failed in CI three times on three *different* assertions. Patching
them individually was treating symptoms. The cause was a **0.2 s tick interval**,
putting `INV-AUTO-1`'s stall threshold at 0.6 s — inside the range a shared
runner deschedules a Python thread. Now 0.5 s / 1.5 s.

Its healthy-phase assertion also could not discriminate: a stall reported while
the loop ticks normally is a defect, but when the scheduler genuinely withholds
the thread past the limit, reporting it is **correct**. It is now judged against
observed lateness, so it keeps full force on a machine that schedules on time
and says so explicitly when it cannot tell.

> **The standing lesson:** a required check that fails one run in three is worse
> than one that fails every time. It teaches whoever is waiting to press the
> button again, and the day it goes red for a real reason that habit throws the
> finding away.

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
| Placement / survival | `core/placement.py`, `verification/run_f6_acceptance.py`, `verification/stress_placement.py` |
| Alarm armed-state evidence | `docs/planning/spike-results/ALARM-0900-armed-verification-20260818.json` |
| J3 browser capability probes | `docs/planning/spike-results/SPIKE-004-capability-probe-*.json` |
