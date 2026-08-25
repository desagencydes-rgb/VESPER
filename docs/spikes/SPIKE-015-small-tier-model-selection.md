# SPIKE-015 — The small tier's model, decided by measurement on this host

**Status authority is `docs/spikes/INDEX.toml`.** This header follows it (`RF-047`).

**Raised** 2026-08-24 by the owner, re-deciding the small tier.
**Pre-registered** 2026-08-25, before any candidate result was seen.

---

## The question

Can **one** small local model carry VESPER's front-end work — conversation,
perception, tool calling — on this host, fast enough to talk to, and quietly
enough that the owner does not notice it is running?

## Why the obvious evidence does not answer it

Published benchmarks rank candidates against each other on tasks nobody here
will run. Three things they do not report, each of which can decide this alone:

1. **Tokens per second on this silicon.** No published figure exists for any
   candidate on this host's chip. That was checked, not assumed.
2. **Time to the first token a person actually sees.** On a thinking model this
   is not the throughput figure and not the wall clock. Reasoning tokens are
   generated before the answer starts and are never shown or spoken. Measured
   on the incumbent 1.7B at 16k context: a science question ran **56.2 s wall
   with the first visible token at 51.2 s**. Fifty-one seconds of silence, at
   59 tok/s. Every published measure calls that fast.
3. **What it costs the machine.** The owner's requirement is a model that stays
   invisible until you go looking for it. That is a thermal, memory and battery
   property, and no leaderboard carries it.

## The constraint that shapes the candidate set

**No model at or above 7B runs on this host** — owner's decision, 2026-08-24.
The measured cost of that ban is small and specific: on the published tables
`Qwen3-VL-4B-Thinking` scores **67.3 BFCL-v3** against `Qwen3-VL-8B-Instruct`'s
66.3, and **51.3 LiveCodeBench v6** against 39.3. The 4B thinking variant beats
the 8B instruct variant on both axes the ban was feared to cost.

## Pass criteria — fixed before the first candidate ran

A candidate passes only if **all** of these hold. Partial results are reported
as partial; no criterion is relaxed after a result is seen.

| # | Criterion | Threshold | Source of the number |
|---|---|---|---|
| 1 | **Sustained generation** | ≥ 7 tok/s | `capability_profiles.toml` voice floor — 2× the 3.25 tok/s speech break-even |
| 2 | **Conversational first-token latency** | ≤ 2.0 s to first *visible* token | Model's share of the 800 ms `wake_to_first_audio` chain plus turn overhead; the incumbent sets the bar it must not lose to (1.91 s) |
| 3 | **Vision actually works** | endpoint reports `vision: true` **and** every image test returns an answer | A projector that fails to load makes a blind model look like a bad one |
| 4 | **Reads the owner's own handwriting** | recognisable transcription of a real notebook page | `docs/source/handwritten-pages/`, ground truth in `HANDWRITTEN_TRANSCRIPTION.txt` |
| 5 | **Reads a UI** | names the real labels and values in a screenshot of VESPER's own surface | VESPER must read its own interface |
| 6 | **Tool calling, single turn** | correct function, correct arguments, structured | `A-042`-class self-action |
| 7 | **Tool calling, multi-turn** | correct second call using the first call's result | BFCL multi-turn is where small models collapse: 4B **35.25%**, 1.7B **16.88%**, 0.6B **1.38%** |
| 8 | **Long context retrieval** | finds a verifiable fact in same-register prose | `large dataset work` |
| 9 | **Code that runs** | generated function passes asserts in a subprocess | judged by execution, never by reading it |
| 10 | **Host stays comfortable** | battery temp rise < 12 °C and peak < 42 °C; memory band never ≤ 25; no OS thermal warning | Owner's requirement, 2026-08-24: no heat, no fast drain |

**Criterion 10 is a hard abort, not a report line.** The harness stops the run
when it trips, because discovering the cost after an hour of cooking the
laptop is not a measurement anyone asked for.

## What is deliberately not scored

Prose quality. The harness records every answer in full for a human to read and
issues automatic verdicts only where a check is objective — did the call parse
and name the right function, did the arithmetic come out right, did the needle
come back, did the code pass its asserts. **A harness that scores taste is one
that can be tuned until it likes the answer.**

## Two traps this spike is written around

**Budget exhaustion is not a wrong answer.** A reasoning model spends its
budget thinking first; when the cap lands mid-thought the server returns
`finish_reason: "length"` with an *empty* answer. Scored naively that is a
capability failure that never happened. `MEMORY.md` 4h recorded this against a
live endpoint, and the first run of this harness walked into it anyway and
called two tests failures. Budget exhaustion is now its own outcome.

**The context window binds before the token budget does.** The first baseline
ran at `n_ctx = 1024` — node 1's draft-tier configuration, correct for
cross-node comparability and far too small for this work. Every reasoning test
hit the context ceiling, not the model's limit, and the long-context test
returned HTTP 400. A candidate measured in a window too small to hold the task
has not been measured.

## On_fail

If no candidate meets all ten, the **thinking budget is the first thing tuned,
not the criteria** — `--reasoning-budget` and `--reasoning on|off|auto` are
server-side controls, so conversational latency and reasoning depth can be
different deployments of one model rather than different models. If bounding
the budget cannot buy criterion 2 without losing 6–9, the candidate is reported
as failing and the next is tested.

**Not permitted:** a figure from the idle condition reported as the working
one; a rate measured client-side reported as the model's; a vision result from
a run whose projector did not load; relaxing criterion 10 because a candidate
was otherwise good.

## Candidates, in order

1. **Qwen3-VL-4B-Thinking** (Q4_K_M, 2.5 GB) — owner's choice, tested first.
2. Qwen3-VL-4B-Instruct — the latency comparison, same family.
3. Qwen3-VL-2B-Instruct — what "lighter" actually costs.
4. Gemma 3 4B — a negative control from a different family; on published
   document scores it should lose, and if it does not, the sourcing was wrong.
5. **Qwen3-1.7B** — the incumbent baseline, and the draft model for
   speculative decoding regardless of which candidate wins.
