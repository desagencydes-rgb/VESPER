# VESPER inference architecture — residency modes over a VRAM budget

**Status: DESIGN. Not measured, not locked.** Written 2026-08-13. Numbers marked EXPECTED are arithmetic, not measurements — SPIKE-011 and SPIKE-012 replace them with real ones. Lives in `docs/planning/` so it is outside `NORMATIVE_ROOTS` and CI-free until it earns promotion.

**Target node:** the site-A desktop — Ryzen 5 5500 (12 threads), 16 GB RAM, RX 6650 XT **8 GB VRAM**, Windows 11 Pro.

---

## 0. The one constraint everything bends around

**Not 8 GB — 7.2 GB.** MEASURED 2026-08-13 via `llama-server --list-devices` on the real card:

```
Vulkan0: AMD Radeon RX 6650 XT (8176 MiB, 7378 MiB free)
```

The card reports 8176 MiB total but only **7378 MiB free** — the desktop compositor and display take the rest, and they do not give it back while Windows is running a desktop. Every budget below is against **~7.2 GB usable**, not the 8 GB on the box. Planning against the nameplate figure would have overcommitted every mode by roughly 800 MiB.

| Model class | Quant | EXPECTED weights | Fits alongside? |
|---|---|---|---|
| ~1B | Q4 | ~0.7 GB | many |
| ~3B | Q4 | ~2.0 GB | a few |
| ~7-8B | Q4_K_M | ~4.5 GB | one, plus a tiny |
| ~13-14B | Q4 | ~8.5 GB | **does not fit** — needs partial CPU offload |

Against 7.2 GB rather than 8, the modes that were already tight get tighter: `COUNCIL` (3 × ~3B) and `SWARM` were sized with roughly 800 MiB that does not exist. Treat their viability as genuinely open until SPIKE-012 measures them.

Add KV cache and runtime overhead on top of weights. Quantized KV (q8_0 symmetric) roughly halves the cache cost — that is what buys the headroom to run two models at once.

**Partial CPU offload is a real option, not a failure mode.** 12 threads and 16 GB of system RAM can hold layers the GPU cannot. It trades tokens/sec for capability — the right trade when the task needs a bigger brain and can wait.

---

## 1. The layers

```
  agent / swarm layer        many concurrent agents          cheap, scales wide
         |
      router                 request -> which model          policy, not hardware
         |
  residency manager          what is loaded, right now       THE control point
         |
   model servers             llama-server, N parallel slots  VRAM-bound
         |
     baseline                native Windows, Vulkan, no Docker
```

**The correction that produced this design:** an earlier draft fixed the shape as "many agents → router → few servers." That is only one of several shapes the owner actually needs. The shape is **configurable**, and the residency manager is what configures it.

### Baseline (layer 0) — settled

- **Native Windows processes.** No Docker, no WSL2. Container/VM layers cost a measured 15–40% on GPU work and buy nothing on a single-tenant node.
- **Vulkan backend.** On RDNA2 this outperforms ROCm/HIP in published 2026 benchmarks, because llama.cpp's ROCm path is a lightly-ported CUDA backend while its Vulkan backend was originally written on an RDNA2 card. **Correction (2026-08-13):** an earlier draft said ROCm was Linux-only. It is not — release `b10405` ships `llama-b10405-bin-win-rocm-7.14-x64.zip`. The performance argument stands; the availability argument was wrong, and a head-to-head bench on this card is worth doing rather than assuming.
- **VESPER owns its own build.** No borrowing from AEGIS / NUMEN / ARCHONEC — those stay untouched.
- **Flash Attention on, symmetric quantized KV cache** (q8_0/q8_0; q4_0/q4_0 when stretching). Asymmetric pairs fall back to a slower unfused path.
- **OS choice stays open.** Linux idles lighter, but this machine is not VESPER-dedicated. Deliberately not decided here.

**Security note, observed at first launch (2026-08-13).** `llama-server` warns at startup that it defaults to **CORS allowing all origins with no API key set**. Bound to `127.0.0.1` on a single machine that is a local-only concern. It stops being local-only the moment this node is reachable through the SPIKE-009 cross-site fabric: an unauthenticated inference endpoint on the fabric is exactly the shape of thing SPIKE-010 §5 already forbids for the wake path. **Do not expose this port beyond loopback without an API key and an origin policy.** Recorded here so the default is a decision rather than an accident.

---

## 2. Residency states

A model is always in exactly one state. "Loaded but not working" is a first-class state, not an accident.

| State | In VRAM? | Serving? | Cost |
|---|---|---|---|
| `ACTIVE` | yes | yes | full |
| `WARM` | yes | no — ready instantly | VRAM held, near-zero compute |
| `DORMANT` | no | no — config known, reloadable | none |
| `COLD` | no | not configured | none |

`WARM` is the state that answers "multiple loaded, but only some working on need." `DORMANT` is what SPIKE-011 measures.

---

## 3. Residency modes

A mode is a VRAM budget allocation. The residency manager switches between them.

| Mode | Shape | For |
|---|---|---|
| `SOLO_MAX` | one model, all 8 GB, CPU offload allowed | hardest single task; max capability, slowest |
| `LEAD_SCOUT` | one ~7B `ACTIVE` + one ~1B `ACTIVE` | the default. Tiny handles routing/classification/tool-picking so trivial calls never touch the big model or trigger a swap |
| `COUNCIL` | 3-ish ~3B models `ACTIVE` | genuine parallel specialization — different models, different jobs, at once |
| `SWARM` | many ~1B models `ACTIVE` | maximum breadth, minimum depth |
| `ELASTIC` | some `ACTIVE`, others `WARM`/`DORMANT` | mixed load — the general case, and the one that risks thrash |
| `DORMANT_ALL` | nothing loaded | machine on, VESPER idle. GPU truly at rest |

**Modes are selected, not hardcoded.** The residency manager may switch modes on workload — that switch is itself an expensive operation and is governed by anti-thrash policy (§5).

---

## 4. Concurrency ≠ swapping

The single most important distinction in this design.

- **Concurrency** — one `llama-server`, `--parallel N` slots, continuous batching. N agents share **one loaded copy** of the weights. Cost is roughly one model's VRAM plus per-slot KV, **not** N × model. This is how the swarm scales.
- **Swapping** — unload, load different weights from disk. Costs **seconds**. This is for changing gears, not for serving requests.

**Corollary:** a swarm of agents on the *same* model is cheap. A swarm of agents each demanding a *different* model is the expensive case, and `ELASTIC` mode has to defend against it.

---

## 5. Policy the manager needs

Not tooling — decisions. `llama-swap` supplies idle-TTL unloading and nothing else on this list.

| Policy | Question it answers |
|---|---|
| Admission | request arrives, model not loaded — load it, queue it, or route to a resident substitute? |
| Anti-thrash | minimum residency time before a model may be evicted; swap-rate ceiling |
| Priority | interactive agent beats background batch job for a slot |
| Headroom | reserve VRAM/RAM so the machine stays responsive; never allocate to the last byte |
| Thermal / power | back off under sustained heat; power-cap when latency is not critical |
| Idle descent | `ACTIVE` → `WARM` → `DORMANT` → `DORMANT_ALL` on a timer ladder |
| In-flight safety | never unload a model with a request outstanding |

---

## 6. Power and longevity

The big lever is **dormancy**, not tuning: unloaded-and-idle beats any power-limit slider. Tuning is the icing.

- GPU power cap ~70–80%: EXPECTED ~25–30% less draw, several °C cooler, <7% throughput loss — inference is memory-bandwidth-bound, so the top of the power curve buys little.
- Light undervolt (50–150 mV): EXPECTED 10–30% watts at equal speed.
- Lower sustained temperature is the honest longevity argument. Both figures are EXPECTED and get measured, not assumed.

---

## 7. What is settled vs. what the spikes decide

**Settled (build against these):** native Windows, no Docker/WSL2 · Vulkan · VESPER-owned build · Flash Attention + symmetric quantized KV · the four residency states · concurrency-via-slots as the swarm mechanism.

**SPIKE-011 decides:** whether dormancy actually returns the GPU to idle draw, and the real cold-start cost of leaving `DORMANT`.

**SPIKE-012 decides:** whether the residency manager holds up — mode switching, anti-thrash, priority, headroom, and which modes are viable at all on 8 GB.

**Deliberately left open:** base OS · exact model picks per mode · final power-cap and undervolt values.

---

## 8. The node is a household machine, and it is about to change

Two facts that reshape what SPIKE-001 can honestly measure **today** (owner, 2026-08-13):

1. **The owner is present now and will not be later.** The desktop stays in site A; the owner moves to site B. Today it is a daily-driver with Opera and a full working set. Afterwards it is unattended, used occasionally by a household member at most.
2. **The household includes a child.** Another person may start a game or other GPU-heavy application at any time, without warning or coordination.

### What this does to SPIKE-001

Its sections split four ways. Measuring a presence-dependent figure now would describe a machine that stops existing after the move — the exact error §3.1 of that spike warns about.

| Bucket | Sections | Disposition |
|---|---|---|
| Presence-independent | 3.1 throughput · 3.3 storage | Measure now; stable across the move |
| Two figures required | 3.2 headroom · 3.6 thermal/power | Record **both** `owner_present` and `unattended`. `unattended` is the **binding** figure — see the §3.4 lock below — and `owner_present` is observed context |
| Locked by policy, still unmeasured | 3.4 availability / reachability | See below |
| Skipped by owner direction | 3.5 camera/audio | See below |

#### 3.4 — locked as policy, NOT as a measurement (owner, 2026-08-13)

The owner's decision: **this node is treated as always-unused.** When a household member does use it, a protocol confines VESPER to light work and monitoring; when the machine goes unused or off again, VESPER resumes full operation.

That decision settles the *design*. It does **not** produce a measured `availability_class`, and it must not be transcribed as one:

- The statement is an **intent** about the future, not an observation of the past. `INV-HW-2` and `CI-034` exist for exactly this shape of claim.
- `capability_profiles.toml` keeps `availability_class` unmeasured with `unmeasured_disposition = "UNAVAILABLE"`. No field changes.
- **It does not retire the pass-criterion-3 failure.** Criterion 3 needs an `always_on` `control_plane_host`; this node is `on_demand` with wake BLOCKED (SPIKE-010). The fabric still needs an always-on member. Stated here so it is not later discovered as a regression.

The protocol the lock implies has two halves, and both are new build work, not measurement:

1. **Degradation on human presence** — detect an interactive session, drop VESPER to light work, restore on logoff/idle/shutdown. Shares its trigger machinery with SPIKE-012 §4's foreign-GPU-contention yield.
2. **Activity monitoring, scoped.** The owner's stated reason is sound — it is their machine and their data. The boundary belongs in writing rather than in the implementer's head: **VESPER-relevant events only** — session start/stop, GPU/VRAM contention, disk pressure, and access attempts against VESPER's directories. Not general-purpose activity capture.

#### 3.5 — skipped for this node (owner, 2026-08-13)

Owner-**declared**, not measured: audio capture is available; camera is available via phone; neither is needed, because the owner will not be at this machine. Recorded as *declared and unmeasured* — **not** as measured-absent. A different node re-opens the question.

**Stated in advance, not discovered late:** scoping SPIKE-001 to this node alone *guarantees* its pass criterion 3 fails — that criterion needs an `always_on` `control_plane_host`, and this node is `on_demand` with wake BLOCKED (SPIKE-010). Its §5 on-fail already covers the outcome: a finding about the fabric, not about the requirement. The fabric needs an always-on member.

### Household protection — configuration, not a spike

Windows 11 **Pro** already provides this. It is ordinary administration and is deliberately not spiked:

- A **standard, non-admin** account for household use.
- **ACLs** denying that account VESPER's directories and model store.
- **`fsutil` disk quota** on it, so the shared disk cannot be filled out from under VESPER.

**Correction (2026-08-13).** An earlier revision said "a second local account already exists." It does not, in the sense meant. `Get-LocalUser` shows the enabled accounts are `ULTRA PC` (owner) and `CodexSandboxOnline` / `CodexSandboxOffline` — tooling accounts, not a household account. The household account has to be **created**, and the two sandbox accounts are themselves extra logon surface on a machine about to be left unattended. Flagged to the owner; not removed.

`fsutil quota` is **verified, not assumed** — it requires quotas enabled on the volume and fails quietly when they are not. The hardening script queries the state and reports it rather than setting a cap blind.

The one genuinely measurable part — whether VESPER **yields** to a foreign GPU workload instead of thrashing, and how fast it recovers — is folded into SPIKE-012 §4 rather than opened as a new spike.

### Disk was on the critical path — it is not any more

**Superseded 2026-08-13.** An earlier revision of this section read: *"C: has 35.1 GB free … the `Downloads` cleanup is therefore a prerequisite to the inference build."* The owner has since cleaned up, and C: now has **167.73 GB free** (MEASURED). A `COUNCIL` or `ELASTIC` mode implies roughly 15–20 GB of model files; that fits several times over. **Storage no longer gates the inference build.**

Left as a finding rather than an action, because neither was in scope of what the owner asked for:

- `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx` — **63.03 GB**, and genuinely allocated, not sparse (`fsutil file queryvaliddata` reports a valid-data length matching the logical size). It holds Docker images and volumes; reclaiming it destroys them. The owner's Docker instruction was about *runtime behaviour* — "doesn't use the computer until called" — and that was already true and is now verified: service `Manual`/`Stopped`, autostart removed.
- `Ubuntu-22.04` WSL distro — 5.2 GB. Untouched.
