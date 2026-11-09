# Plan for 2026-08-25 — every power lever, applied at once

Written the night before, after the owner reported the machine hot and the
battery down ~30% while the harness reported "heat is a non-issue". The harness
was wrong; see §0.

**The owner asked for a verdict, not an attempt.** §6 declares in advance what
this plan can and cannot deliver, and one case where it FAILS outright.

---

## 0. The correction this plan is built on

`AppleSmartBattery.Temperature` moved 30.6 → 30.96 °C across four runs while the
machine became hot to the touch. The battery is a large thermal mass at the base
of the chassis and lags the SoC by many minutes. **That sensor cannot see a
compute burst, and gating on it produced a false all-clear.**

Power is the honest instrument, needs no sudo, and is the *cause* of both
symptoms:

```
idle, nothing loaded         5.1 W
model loaded, doing nothing 14.8 W    <- 3x idle merely to be AVAILABLE
generating                  34-41 W   <- near-identical for a 1.7B and a 4B
```

And the law, from our own two data points:

```
model                  GB   tok/s  watts  GB/s read  J/token
Qwen3-1.7B Q4_K_M    1.00    67.5   34.2       67.5    0.507
Qwen3-VL-4B Q4_K_M   2.30    33.0   38.8       75.9    1.176

energy ratio measured 2.32x   |   model size ratio 2.30x
```

**Energy per token is proportional to bytes read per token.** Decoding is
memory-bandwidth-bound; both models pull ~70 GB/s and therefore draw nearly the
same power. This is why "use a smaller model" is a weak lever and why the strong
levers are all about *not reading those bytes in the first place*.

---

## 0b. The comparison with node 2, and two hypotheses it killed

The owner reported that the Kali laptop ran a small model without heating. It
ran **the same model** — `Qwen3-1.7B-Q4_K_M` — and the reports are in the tree:

```
node 2 (4 cores, 3.71 GB, Intel UHD 620)   11.02 tok/s idle   7.7 concurrent
this Mac (-ngl 99, full GPU offload)       67-69 tok/s
```

**6x faster here.** Node 2 was not cool because it was efficient; it was cool
because it was slow. 11 tok/s x 1.0 GB is ~11 GB/s of memory traffic against
this Mac's ~69 GB/s. Power tracks bandwidth. *(Caveat: those reports are dated
2026-08-14. If node 2 later ran a different model, this comparison does not
describe that run.)*

**HYPOTHESIS 1, KILLED: "run CPU-only like node 2 did."** `gpu_in_use` is null
in every node 2 report, so that box was almost certainly CPU-only, and copying
it looked obvious. Measured on this host, 2500 tokens, power sampled at 0.5 Hz:

```
-ngl 99 (full GPU)   69.0 tok/s   31.1 W med   0.450 J/tok
-ngl 0  (CPU only)   42.8 tok/s   38.6 W med   0.900 J/tok
```

CPU-only is **slower AND hotter** — twice the energy per token. The GPU is
already the efficient path on this silicon. There is no offload setting to tune.

**HYPOTHESIS 2, KILLED: "cap the rate to ~11 tok/s and it will behave like node
2."** llama.cpp has no rate limiter, and the arithmetic says not to want one:
at 69 tok/s a 200-token answer costs 2.9 s x 31 W = **90 J**; node 2 needs 18 s
at an estimated 15-20 W = **270-360 J** for the same answer. **This Mac uses
about a third of the energy per answer.** It merely concentrates it into three
seconds instead of eighteen, and concentrated power is what a hand feels.

So the difference the owner noticed is real and is **burst intensity, not waste**.
Per unit of work this host is the better one. The lever is therefore not to slow
it down — it is to ask it for less work, less often.

## 1. The target, as a number

"Unnoticeable" is defined here so it can be failed:

| | Threshold |
|---|---|
| Average power over a 1-hour realistic session | **≤ 8 W** (idle is 5.1 W) |
| Battery above idle | **≤ 3 %/hour** |
| Sustained draw per answer | **no burst above 35 W lasting > 20 s** |
| The owner's hand | **the machine must not feel warm.** This is a criterion, not a courtesy — it caught what the instrument missed |

---

## 2. Why this is reachable — the arithmetic, before any work is done

Measured power, applied to duty cycles:

```
continuous generation, model resident     duty 101%   avg 39.2 W   33.9 %/h   <- what was benchmarked
20 answers/h, model kept resident         duty 3.4%   avg 15.6 W   10.4 %/h
20 answers/h, unloaded when idle          duty 3.4%   avg  6.2 W    1.1 %/h   <- target met
60 answers/h, unloaded when idle          duty 10.1%  avg  8.5 W    3.4 %/h
```

**The heat came from the benchmark, not from the use case.** The suite generated
back-to-back for 5–10 minutes at 39 W. A real answer is ~200 tokens — six
seconds, 238 J, a blip. The distance between "unnoticeable" and "hell" is duty
cycle, and it is a factor of about 25.

---

## 3. The levers, ranked by measured effect

Every one is applied. They are ordered by how much they actually buy, which is
**not** the order that feels intuitive.

| # | Lever | Effect | Cost / risk |
|---|---|---|---|
| **L1** | **Unload the model after idle** | 10.4 → **1.1 %/h**. Removes the +9.7 W resident cost | Reload measured at **1.3–2.3 s** warm. Cold (page cache evicted) is UNMEASURED — step 1 measures it |
| **L2** | **Cap tokens per answer; bound thinking** | **~3x**. 600-token answers cost the same as 3x as many 200-token ones | Truncated answers if the cap is too tight |
| **L3** | **Never generate locally on battery for background work** | Removes autonomy drain entirely | Autonomy waits for mains. A policy decision, not a technical one |
| **L4** | **Speculative decoding**, small draft + 4B target | Up to **2.3x** fewer bytes/token — *if* the draft is small and acceptance is high | **GO/NO-GO: vocab must match.** A VL model may carry extra image tokens. Verified in step 2 |
| **L5** | **q8_0 KV cache + 8k context** | −1.53 GB resident; already measured | Already proven; keeps the memory guard green |
| **L6** | **q8_0 projector** instead of F16 | −~0.4 GB resident | Vision quality unverified at q8_0 |
| **L7** | **Retrieval before generation** | Largest possible: tokens never generated cost nothing | Architectural; the owner's own "mapping system" from handwritten page 1 |

L1 alone is worth more than L4, L5 and L6 combined. That is the finding.

---

## 4. Execution order

Each step is verified before the next. Any step may end the day early with a
recorded result — that is a result, not a wasted day.

**Step 0 — instrument first (10 min).** `sudo powermetrics` for real SoC
temperature and package power, since the no-sudo path cannot see the die. Run
`tools/spike/spike013_power_run.sh` conditions: unplugged, idle machine.
*Without this step every thermal claim tomorrow is as weak as tonight's was.*

**Step 1 — cold load time (10 min).** Purge the page cache, measure launch →
healthy. **If cold load > 10 s, L1 is not viable as written** and becomes
"unload after 10 minutes" rather than "after 60 seconds".

**Step 2 — speculative decoding GO/NO-GO (20 min).** Download `Qwen3-0.6B`
Q4_K_M (~0.4 GB). Launch with `--model-draft`. If llama.cpp refuses on vocab
mismatch, L4 is dead — record it and move on. If it loads, measure accepted
tokens per verification pass.

**Step 3 — build the lean configuration (30 min).** All of L2, L5, L6 together,
plus L4 if step 2 passed.

**Step 4 — the realistic-duty-cycle run (45 min).** *Not* the back-to-back
suite. 20 answers spread over an hour, with the model unloaded between, power
sampled every 5 s throughout. This is the run that decides §1.

> **THE PACK GAUGE CANNOT SEE A SINGLE ANSWER, and a run designed without
> knowing that would report a false pass.** `InstantAmperage` updates every few
> seconds, so a 3-second generation reads as idle: a sweep run against 300-token
> answers returned 6.4 W median AND 6.4 W peak for both configurations — the
> instrument had simply not moved. The sustained figures elsewhere in this plan
> are valid because they were sampled across minutes. So step 4 must be judged
> on **cumulative charge drop across the whole hour**, with per-answer wattage
> treated as unmeasurable by this instrument. `powermetrics` from step 0 is the
> only thing that can resolve a single burst.

**Step 5 — the owner's hand.** Ask. Record the answer verbatim.

---

## 5. What gets built, not just configured

L1 and L3 are **code**, not flags:

* a supervisor-owned model lifecycle: load on demand, unload after N seconds
  idle, with the unload emitted as an event so it is visible rather than
  assumed;
* a policy gate: background/autonomy generation refuses on battery unless the
  owner explicitly asks. `contracts/policy/` already holds the cost policy; this
  is a power policy beside it.

Both are small. Neither is a config change, and neither should be faked with a
timer that nobody can observe.

---

## 6. THE VERDICT, DECLARED IN ADVANCE

**The plan SUCCEEDS for interactive use.** The arithmetic in §2 is built on
measured power, not estimates: an assistant answering on demand, with the model
unloaded between turns and answers capped, lands at **~1–3 %/hour above idle and
~6–8 W average**. That meets §1 with margin, and it does so mostly on L1 alone.

**The plan FAILS, and I am declaring it now rather than discovering it tomorrow,
for CONTINUOUS LOCAL GENERATION.** If VESPER is to think in the background, hold
a long streaming conversation, or run its autonomy loop against a local model,
no combination of these levers reaches "unnoticeable":

* generation costs 34–41 W against a 5.1 W idle — 6–8x, and that is the
  memory bus, not inefficiency;
* the levers reduce *bytes read* and *time spent*, and the best case here is
  roughly 2–3x;
* 39 W reduced by 3x is 13 W, still **2.5x idle, sustained** — a warm machine
  and roughly 8 %/hour.

**So the boundary is: local inference is affordable in bursts and unaffordable
continuously.** No amount of tuning moves that line, because the line is the
memory bandwidth required to read the weights. Anything continuous belongs on
the API path or on node 1 — which is what SR-003/SR-005 and the owner's own
handwritten page 1 already say.

**If tomorrow's step 4 shows > 10 W average or > 5 %/hour on the interactive
duty cycle, the plan has failed on its own terms** and the next move is not more
tuning — it is accepting that this host does not run a local model at all, and
the offline backup becomes node 1 rather than this machine.

---

## 7. Prepare tonight (no power cost — downloads only)

- [ ] `Qwen3-0.6B-Q4_K_M.gguf` (~0.4 GB) — the draft model for L4
- [ ] `mmproj-Qwen3VL-4B-Thinking-Q8_0.gguf` — for L6
- [ ] optionally `Qwen3.5-4B` Q4_K_M + mmproj — thinking off by default, which
      makes L2 free rather than a tuning exercise

Downloading is network-bound and costs almost nothing on the battery. Generation
is what costs. Nothing else runs tonight.
