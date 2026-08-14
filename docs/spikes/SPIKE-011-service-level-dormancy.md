# SPIKE-011 — Service-level on-demand dormancy

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Can individual heavy services on an already-awake node (starting with local LLM inference) sit fully dormant — near-zero CPU/GPU/power draw — until a request actually needs them, activate within an acceptable latency budget, and return to dormant afterward, with **no person present**? |
| **Time box** | 2 working days |
| **Owner** | Core Systems Engineer |
| **Depends on** | SPIKE-001 (measures the same node's power/capability profile) |
| **Requires hardware** | Yes |
| **Raised by** | Owner, 2026-08-13 |
| **Blocks** | The VESPER-owned llama.cpp/llama-server hosting decision · `capability_profiles` power/idle fields for the site-A desktop |

> **Relationship to SPIKE-010.** SPIKE-010 asks whether the *whole machine* can sleep and be woken on demand. This spike asks the question one level down: while the machine is up and running VESPER, can *individual services* on it — starting with local LLM inference — stay dormant by default and activate only when actually called? This covers the common case: the site-A desktop is awake (because VESPER needs it reachable) but idle most of the time, with no one at the keyboard.

> **Candidate tooling is not being invented here.** [`llama-swap`](https://github.com/mostlygeek/llama-swap) — a small, zero-dependency reverse proxy that sits in front of `llama-server` (or other OpenAI-compatible backends), loads a model on first request, and unloads it after a configurable idle TTL — already does the shape of thing this spike measures. The work is verifying it actually delivers the claimed behavior on this hardware, not building a bespoke gatekeeper.

---

## 1. What gets measured

```
1. Baseline: system idle power/CPU/GPU draw with no inference service running at all.
2. Start the gatekeeper (llama-swap or equivalent) with zero models loaded.
   Measure its own idle CPU/RAM/power footprint against the baseline in step 1.
3. Send a single request to the stable endpoint. Measure:
   - cold-start latency (gatekeeper spawns llama-server, model loads into VRAM, first token)
   - GPU/VRAM/power draw once the model is loaded and serving
4. Let the service sit idle past its configured TTL. Measure:
   - time to unload
   - GPU/VRAM/power draw after unload, compared against step 1's baseline
5. Repeat the load -> idle -> unload cycle several times in a row.
   Watch for VRAM leaks, crashed reloads, or growing latency across cycles.
6. Send a request WHILE a previous request is still in flight (or immediately after),
   to confirm the gatekeeper never unloads a service that has work outstanding.
```

## 2. Pass criteria

| # | Criterion |
|---|---|
| 1 | A request to the stable endpoint with nothing loaded activates the service and is served within a stated cold-start budget |
| 2 | After the idle TTL elapses, the service unloads and GPU/VRAM/power draw returns to within a small, stated margin of true system idle |
| 3 | The always-on gatekeeper process itself shows negligible idle CPU/RAM — it must not become its own "thing that's never really off" |
| 4 | Repeated load/unload cycles do not leak VRAM or require restarting the gatekeeper |
| 5 | A service with a request in flight is never unloaded mid-request |

## 3. On fail

If cold-start latency is unacceptable for a given caller (e.g. an interactive path that can't tolerate a multi-second model load), that specific service is named as an exception and kept warm — with the power/heat/wear cost of doing so recorded explicitly, not silently eaten. Dormancy is adopted **per service**, not assumed universal across every future VESPER capability.

**Not permitted:** reporting a warm-cache benchmark as the cold-start number; claiming an idle-draw improvement without a measured before/after on this hardware; unloading a service that has a request in flight; or treating a working demo as proof without the repeated-cycle stability check in step 5.

## 4. Deliverables

1. Baseline idle draw, gatekeeper-idle draw, loaded draw, and post-unload draw — four numbers, not estimates.
2. Cold-start latency, measured, with the model/quant used stated alongside it.
3. Stability result across repeated cycles (how many, any failures).
4. A recommendation on which VESPER services (starting with local LLM inference) adopt this pattern by default, and which — if any — are named exceptions kept warm.
