# VESPER inference architecture — residency modes over a VRAM budget

**Status: DESIGN. Not measured, not locked.** Written 2026-08-13. Numbers marked EXPECTED are arithmetic, not measurements — SPIKE-011 and SPIKE-012 replace them with real ones. Lives in `docs/planning/` so it is outside `NORMATIVE_ROOTS` and CI-free until it earns promotion.

**Target node:** the site-A desktop — Ryzen 5 5500 (12 threads), 16 GB RAM, RX 6650 XT **8 GB VRAM**, Windows 11 Pro.

---

## 0. The one constraint everything bends around

**8 GB of VRAM.** Every design choice below is downstream of it.

| Model class | Quant | EXPECTED weights | Fits alongside? |
|---|---|---|---|
| ~1B | Q4 | ~0.7 GB | many |
| ~3B | Q4 | ~2.0 GB | a few |
| ~7-8B | Q4_K_M | ~4.5 GB | one, plus a tiny |
| ~13-14B | Q4 | ~8.5 GB | **does not fit** — needs partial CPU offload |

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
- **Vulkan backend.** On Windows + RDNA2 this outperforms ROCm/HIP; ROCm is Linux-first and lightly tuned for RDNA.
- **VESPER owns its own build.** No borrowing from AEGIS / NUMEN / ARCHONEC — those stay untouched.
- **Flash Attention on, symmetric quantized KV cache** (q8_0/q8_0; q4_0/q4_0 when stretching). Asymmetric pairs fall back to a slower unfused path.
- **OS choice stays open.** Linux idles lighter, but this machine is not VESPER-dedicated. Deliberately not decided here.

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
