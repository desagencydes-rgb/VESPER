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

## Nine subsystems

Owner named four. Five more are required. Six carry their own gateway, key set,
model roster, benchmark and rules; three are deterministic and carry none.

| # | Subsystem | When | Model | Own gateway | If absent |
|---|---|---|---|---|---|
| 1 | **VESPER** | owner-facing | yes | served by the chooser | — |
| 2 | **Chooser** | before each turn | yes | yes | falls back to today's deterministic path |
| 3 | **Updater** | after each act, bg | yes | yes | memory holds only what VESPER noticed |
| 4 | **Compactor** | scheduled + pressure | yes | yes | L1 grows until it stops fitting |
| 5 | **Forgetter** | sweep, command, prune | partly | yes | L3 grows forever; stale facts stay authoritative |
| 6 | **Arbiter** | on contradiction | yes | yes | silent picks — what `INV-MEM-1` forbids |
| 7 | **Miss recorder** | on correction / repeat | partly | yes | **no corpus accumulates; the design can never be judged** |
| 8 | **Verifier** | before trusting rank 3 | registry | borrows | acting on a stale reading of a moved world |
| 9 | **Redactor** | every outbound request | **never** | **at the choke point** | **a credential reaches a provider and is logged there** |

### 5 · Forgetter — three jobs, three risk levels

Split deliberately; they must not share a path.

- **Expiry sweep** — driven by `Fact.valid_until_ms`. Deterministic, no model.
  Running one here is paying for arithmetic. `world.sweep_expired()` exists and
  is called by nothing.
- **Owner-commanded** — *"forget that."* Needs interpretation of what "that" is.
  Model, high stakes.
- **Judgement pruning** — deciding a fact stopped mattering. Highest stakes; the
  place a model could quietly erase things nobody notices are gone.

Append-only lowers the stakes without removing them: a tombstone marks a record
dead, the row survives, so a wrong forget is *recoverable* — but only if someone
notices, and nobody notices an absence.

### 6 · Arbiter — why it cannot live inside the updater

It runs when two memories disagree and something must decide. It is separate for
one reason: **the updater cannot ask a question.** It runs in the background,
the owner is not there, and it has to finish.

> March: the owner says "my flight is Tuesday."
> April: the calendar says Wednesday.
> Both live, both in memory, disagreeing.

The updater only captured them; the compactor only shrinks. Three possible
outputs, and the third is why this is a subsystem and not a function:

1. **Write a winner** — rank settles it. Calendar is `source_of_record` (2) and
   beats `user_statement` (4).
2. **Ask the owner** — only they can know.
3. **Hold both, act on neither, say so if asked** — a state VESPER can *sit in*.

Rung 1 of the ladder is pure code; rungs 2–4 (look in memory, at the world,
outside) need a model to formulate and interpret, which is why it has a gateway.

### 7 · Miss recorder — and the hard problem in it

**In a resident-memory architecture misses are invisible.** No query returns
empty; VESPER simply does not know something and answers anyway, confidently. It
cannot be caught at retrieval time. It has to be caught **retrospectively, from
the owner's corrections.**

Three detectors:

| Detector | Signal | Needs a model? |
|---|---|---|
| **Repetition** | the owner states something already held at equal-or-higher rank | no — exact match |
| **Correction** | a rank-4 statement supersedes what VESPER just acted on | **yes** — "no, it's X" vs "also X" is genuinely fuzzy |
| **Explicit absence** | VESPER said "I do not have that" | no — self-reported |

Writes to the existing `audit` store: the situation, which layer was consulted,
what was found, what VESPER did — and **the correction that followed.** That
pairing is a labelled example: what it should have known, beside what it did.
**This is the corpus. It does not exist any other way.**

### 8 · Verifier — a registry, appended to as each part lands

Each entry: **fact pattern → how to check → what it costs → how long the answer
stays fresh.**

| Fact | Probe | Cost | Fresh for |
|---|---|---|---|
| is the alarm armed | read the LaunchAgent | ~5 ms | 60 s |
| is node 1 up | TCP/22 | ~300 ms | 5 min |
| what is on Tuesday | calendar | ~50 ms | 1 hr |

The freshness column is load-bearing: it decides *check* versus *recall* per
fact, rather than as a blanket policy. Scope is everything better checked than
remembered — files, graphs, memory status, alarms, processes, plans, calendar,
research state. Built in stages, appended each time.

### 9 · Redactor — deterministic, at the choke point, never a model

**"Make the model forget it" is not possible.** Once text is in a request it has
been sent; the provider has it and has logged it. So detection must be
deterministic and must run **before any model sees the text** — pattern and
entropy scanning in code, the way `gitleaks` and `trufflehog` work. A model may
be a *second* pass for what patterns miss; it can never be the first line,
because **running it is the leak.**

**It belongs inside `ModelGateway.complete`, not at each caller.** The gateway is
already the single choke point for everything leaving this machine
(`INV-COST-3`). Placed there it is structurally impossible for any subsystem to
send a credential — including subsystems written later by someone who never read
this document. Placed per-caller, one forgetful caller is a permanent leak.

## Credentials — the vault

Owner's design, with three adjustments.

| Layer | Holds |
|---|---|
| L1 / L2 | **an opaque handle only** — `secret:7f3a` |
| L3 vault | the value, encrypted, in its own protected store |

1. **The handle is opaque.** `API-KEY,table=creds,row=17` transmits a map of the
   vault to every provider on every turn. `secret:7f3a` means nothing off this
   machine and resolves by local lookup. Same convenience, no structure leaked.
2. **The vault key lives in the macOS Keychain, not in a file.** Hardware-backed
   by the Secure Enclave on this machine. A key VESPER reads off disk protects
   against a stolen laptop and against nothing running as VESPER. Keychain makes
   the OS the gate, and the owner can still rotate it from settings.
3. **A credential is used by CODE and never enters a prompt.** If VESPER
   retrieves a key to *use* it and using it means a model call, it is back at the
   provider. VESPER says "use the stored key for X"; the **code** resolves the
   handle and makes the call. The model sees a handle, never a value.

**Handles must survive compaction verbatim.** The compactor rewrites nodes; if it
paraphrases `secret:7f3a` the credential becomes unreachable. It is an opaque
token the compactor is forbidden to touch.

The same intake pass resolves relative time — "next Tuesday" to an absolute date,
with the original phrasing kept beside it. Relative time stored relatively is
simply wrong the next day, and this is the boundary where it enters.

## Sensitivity is monotonic — the design that needs no enumeration

The owner's question: how do we stop VESPER classifying sensitive material as
insensitive, given how many hidden cases exist?

**By never classifying downward.**

- Everything the owner says starts `private`. Relaxation requires **positive
  evidence**; the absence of a red flag is not evidence.
- A compacted node inherits the **maximum** sensitivity of its inputs.
- The check on the result may **raise** it further. It may never lower it.

You do not need to catch every sensitive thing. You need to never *lower* a
classification. That is one assertion, and it subsumes the aggregation case —
three innocuous facts compacting into a security profile is simply "the result
was raised."

This is the repo's existing fail-closed doctrine applied to a new axis:
unlabelled defaults to private, UNKNOWN is UNAVAILABLE.

## Time is a dimension, not a partition

Compaction must **recognise** timelines, not split across them. Partitioning
would wall off exactly the cross-period patterns that produce good conclusions —
the world does not keep its causes inside one month. `Fact.observed_at_hlc`
already makes time an attribute of every record; that is the right shape.

## Self-updating the routing profiles — the split that keeps it legal

The owner wants VESPER to repair its own routing when a provider drops or adds a
model, triggered by investigating a real dead end. `provider_supply.toml` lives
in `contracts/policy/` and is a **governed surface**: `INV-SELF-*` permits the
runtime to PROPOSE into `workspace/` and never to self-apply. `profile_node.py`
deliberately has no write path to its own contract for this reason.

The split that preserves the intent:

- **Measured availability is written freely.** This rung 404s, this model is
  gone, this key was revoked. That is observation, and `INV-HW-2` wants it
  recorded rather than declared.
- **Contract changes are proposed.** Which providers are permitted, which egress
  class, which cost class. Otherwise VESPER can silently rewrite which providers
  it is allowed to use, which is a security capability rather than a maintenance
  one.

## Routing profile — the full field list

Owner's five, plus eight that were missing.

| Field | Why |
|---|---|
| key provider · available models · benchmark | owner's |
| context window · size | owner's |
| effort levels | owner's |
| **egress class** | which rungs may see *this subsystem's* data. The updater handles raw owner speech: E1-private only |
| **rate limits (TPM/RPM)** | the binding constraint — 131k window against 8k/min |
| **cost class** | `INV-COST-5` treats metered-free as paid unless a hard cap is provable |
| **measured latency** | `INV-HW-2`: measured at enrolment, never declared |
| **supported parameters** | "OpenAI-compatible" is not one parameter set — a 400 on `reasoning_effort` cost a rung once |
| **retirement policy** | a class terminal for the updater may be fine for the verifier |
| **concurrency limit** | background subsystems can burst |
| **preemption** | **when the owner is waiting, background yields.** Separate keys stop them competing for quota; nothing stops them competing for the machine |

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
