# VESPER — resident memory architecture

**Status: PROPOSAL. Nothing here is built.** Owner's architecture, 2026-08-27,
with engineering critique and the constraints measured that day. Artifact copy:
`claude.ai/code/artifact/152e81ce-9b2d-49c9-9df2-8cce5074704f` — this file is the
durable one and wins if the two disagree.

## The idea, and why it is not a workaround

Every memory system surveyed — Claude Code's read-time search, ChatGPT's
write-time extraction, Kimi's long context — recalls **in response to a turn**.
VESPER will frequently have no turn; it acts on its own. That makes "what
triggers recall" the hardest open question in the space.

The owner's answer removes the question rather than answering it: **memory is
resident in every request, so recall never happens.** No retrieval event, no
trigger, no latency. It also spends the correct currency — measured 2026-08-26,
`max_tokens` is *reserved* against the rate limit whether generated or not, so
prompt tokens are the cheap half.

## What was measured, 2026-08-27

From the provider's own response headers (`x-ratelimit-*`), one small call:

| Constraint | Value | Binds what |
|---|---|---|
| Context window | 131,072 | Request size. The graph is nowhere near it. |
| **Tokens per minute** | **8,000** | **The real constraint.** 1/16th of the window. |
| Requests per window | 1,000 | Not binding at conversational rates. |
| Refill | ~133 tok/sec | Continuous bucket, so bursts recover. |

**The cap is rate, not size.** The graph will never struggle to fit; it will
struggle to be re-sent. Per turn today: 430 preamble + ~20 question + 2,560
reservation ≈ 3,010 → **2.7 turns/min before any memory at all.**

| Graph size | Per turn | Turns/min |
|---|---|---|
| 0 (today) | 3,010 | 2.7 |
| 1,000 | 4,010 | 2.0 |
| 2,000 | 5,010 | 1.6 |
| 4,000 | 7,010 | 1.1 |

The reservation dominates the graph — cutting reservations buys more headroom
than shrinking the graph. **The single measurement that decides the design:
does prompt caching discount a stable prefix against TPM?** The graph is a
stable prefix, which is exactly what caching is for. If yes, near-free after the
first request. If no, every turn pays full freight forever.

## Three layers, one source of truth

**Correction to the owner's "×2 write": do not dual-write, PROJECT.** One append
to L3; L1 and L2 are derived views. Dual-writing invites drift and needs reserved
slots kept in step. Projection makes disagreement structurally impossible — and
ordering matters: graph-first-then-archive, interrupted, leaves a memory with no
provenance, which breaks `INV-EVID-2` outright.

| Layer | Lives | Size | Access | Job |
|---|---|---|---|---|
| **L1 resident** | in every request | ~1–2k tok | always present, never retrieved | removes recall; VESPER is never blank |
| **L2 navigable** | on disk, structured | 10⁴–10⁵ | on demand, cheap traversal, no model call to enter | the backstop L1 points into |
| **L3 archive** | append-only log | unbounded | rare, route-planned | the truth; L1 and L2 recomputable from it |

**L1 must carry the SHAPE of what was omitted**, not just survivors. ~15 tokens
a node: *"47 facts under 'work'; 3 resident; pointer."* Buys two things:
VESPER knows what it does not know (a silent drop otherwise leaves it
*confidently* ignorant — undetectable, unlike a miss), and grounding survives
(`INV-EVID-2` needs a resolvable span; a summary is not one, a pointer is).

## Two writers

Owner's design, and better than a single writer.

- **VESPER, deliberate.** Its own files, nothing else touches them. Judgement, so
  **rank 5 · derived**. Writes only to L3; projections pick it up.
- **Updater, automatic.** After every act, background, captures whether or not it
  looks important — the net under everything VESPER failed to notice mattered.

**The load-bearing detail:** `INV-EVID-1` forbids a model prior emitted as an
assertion into memory. A model-run extractor therefore **cannot produce rank 4**.
A verbatim owner utterance is rank 4; the extractor's reading of it is rank 5.
Store both, separately, or the system silently promotes its own guesses to the
owner's word — permanently and invisibly.

## Eight subsystems

Owner named four. Four more are required. Four of the eight need no model, which
is the natural line for where a gateway is warranted.

| Subsystem | When | Model | Gateway | If absent |
|---|---|---|---|---|
| VESPER | owner-facing | yes | own | — |
| Chooser | before each turn | yes | own | falls back to today's deterministic path |
| Updater | after each act, bg | yes | own | memory holds only what VESPER noticed |
| Compactor | scheduled + pressure | yes | own | L1 grows until it stops fitting |
| **Forgetter** | sweep + command | no | code | L3 grows forever; stale facts stay authoritative |
| **Arbiter** | on contradiction | borrows | ladder | silent picks — what `INV-MEM-1` forbids |
| **Verifier** | before trusting rank 3 | no | code | acting on a stale reading of a moved world |
| **Miss recorder** | on failed recall | no | code | **no corpus accumulates; design cannot be judged** |

Owner chose **four separate gateways and key sets** for blast-radius isolation.
Honest cost, recorded now rather than discovered: four credential sets, four
failover ladders each needing to stay measured and correct, four places a rung
can silently retire. `QuotaLedger.declare_pool` + reserved floors would give the
same non-drain guarantee on one ladder; isolation is the thing being bought.

## The resolution ladder (owner's design)

`INV-MEM-1` mandates a question on three-way disagreement across ranks 2–4.
Asking is the **last** resort, not the first — and it mirrors the provider ladder.

1. Rank it (`DF-MEMORY-AUTHORITY`) → resolved? write the winner.
2. Look in memory — L2, then L3.
3. Look at the world — files, processes, sensors.
4. Look outside — research, code, sources.
5. Only the owner can know? **Ask, at a good moment.**
   Otherwise **hold both, act on neither, and say so if asked** — a legitimate
   terminal state; `INV-EVID-3` doing its job.

Every rung before the last is cheaper than an interruption, which is what makes
the invariant affordable in a voice interface.

## The rule that defends everything

```
WRONG   L1(n+1) = compact( L1(n) )    # a copy of a copy of a copy
RIGHT   L1(n+1) = project( L3 )       # always from the source
```

Kills four failure modes at once:

- **Generation drift** — each pass is a translation; meaning degrades with no
  hallucination at all.
- **Compaction poisoning** — the compactor is a model; hallucinate once and a
  false fact enters wearing the clothes of an old established memory, and
  survives every later pass because each trusts the last.
- **Uncorrectable corrections** — "my name is X, not Y" cannot un-bake Y from a
  summary by compressing further. Re-deriving from a log containing the
  correction simply produces the right answer.
- **Unrecoverable bugs** — a bad compactor release corrupts memory permanently
  under iteration; under projection you fix it and re-project.

Cost: projection reads more of L3 each time. That is what the compactor's own
gateway and off-peak schedule are for — background work, nobody waiting.

## Ten ways it breaks

1. **Cold start** — L1 grows fastest when compaction has least to work with;
   early facts over-weight themselves and stay.
2. **Aggregation** — "works late Tuesdays" + "lives alone" + "travels monthly"
   compress into a security profile. **Compaction can create sensitivity that was
   in none of its inputs**, so privacy class must be recomputed on projection,
   never inherited.
3. **Continuous exposure** — resident memory reaches whichever provider answers,
   every turn, and sits in their logs. Forecloses public rungs permanently.
4. **Throughput cliff** — bigger requests hit the rate limit sooner, so long
   conversations fail over to slower rungs precisely when going well.
5. **Convergence** — lossy, repeated, forever: either it stops shrinking (L1
   outgrows budget) or it asymptotically holds nothing. A useful equilibrium
   between the two is an assumption, and it is the one the design rests on.
6. **Metadata vs compression** — rank, source, time, privacy, pointer are all
   mandatory and all pure overhead against the pressure to be small.
7. **Secrets** — the owner reads an API key aloud; the updater captures
   indiscriminately by design; it lands in L1 and is transmitted every turn
   forever. **No rule against this exists anywhere in the system today.**
8. **Another person** — `DF-IDENTITY-RESOLVE` returns `unknown_person` as a
   distinct role. VESPER must not disclose owner memory in their presence, and
   must not learn from them as the owner. Nothing implements either.
9. **Divergence** — two nodes append and project; if projection is not a pure
   function of the log they disagree about what they know while the log agrees.
10. **Time** — "next Tuesday" stored relatively is wrong when read. Resolve at
    capture, keep the original phrasing beside it.

## Spikes, in gating order

| # | Question | Falsified if |
|---|---|---|
| S1 | Is a stable prefix discounted against TPM? | cached tokens charged in full — the graph permanently divides throughput |
| S2 | Does compaction converge? | size grows monotonically, or recall falls below the stated bar |
| S3 | Can the metadata be afforded? | overhead exceeds compression gain — L1 has no reason to exist |
| S4 | Is resident cheaper than retrieving? | resident loses on tokens or latency |

**There is no corpus.** The 91 MB of session transcripts and the 1,060-line
`MEMORY.md` are the *builder's* notes — `docs/design/HOME-CONTENT.md:117` says so
in as many words. They record engineering this system, not VESPER assisting
anyone. S2 and S4 need a corpus that does not exist, which is why the miss
recorder is not optional: it is what turns the first weeks of real use into the
dataset that finally judges this.

## Still undecided

- **The unit** — fact triples are rankable and decayable but lose nuance;
  episodes are faithful and unqueryable. L3 can hold both; L1 probably cannot.
- **Who sets expiry** — a model guessing a TTL is a model deciding what the
  owner gets to keep.
- **The chooser's latency budget** — accepted as a model call engineered to stay
  fast; *how fast* is a number to set before building, not after.
- **What the updater must refuse** — credentials at minimum. The list is empty
  and the updater's whole design is to capture indiscriminately.
- **How L2 is navigated** — "cheap traversal, no model call" is a requirement,
  not yet a mechanism.

## Governing artefacts

`DF-MEMORY-AUTHORITY` (six ranks) · `INV-MEM-1` · `INV-EVID-1/2/3` ·
`INV-LEARN-1/2/3` · `INV-LOSS-1/2/3` · `INV-PERF-1` · `INV-PLACE-3` ·
`INV-COORD-4` · `core/privacy.py` · `core/world.py` (`Fact` already carries
subject, attribute, value, HLC, source, confidence, `valid_until_ms`,
`conflicting`) · `core/evidence.py` (`resolve_memory_conflict`, `SpanIndex`) ·
`core/store.py` (append-only, tombstones, epochs) · `core/context.py`
(`ContextBudgetManager`, `recent_dialogue` priority class).

**Almost all of it is built and reachable by nothing.**
