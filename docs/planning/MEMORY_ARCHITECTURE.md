# VESPER — resident memory architecture

**PROPOSAL. Nothing built.** Owner's design + engineering critique, 2026-08-27.
Artifact: `claude.ai/code/artifact/152e81ce-9b2d-49c9-9df2-8cce5074704f`.
**This file wins if they disagree.**

## The idea

Every surveyed system recalls *in response to a turn*. VESPER often has no turn.
So: **memory is resident in every request — recall never happens.** No retrieval
event, no trigger, no latency. Spends prompt tokens, which are the cheap half
(measured 2026-08-26: `max_tokens` is reserved against the rate limit whether
generated or not).

## Measured 2026-08-27, from provider headers

| | |
|---|---|
| Context window | 131,072 |
| **Rate limit** | **8,000 tok/min** ← binding |
| Requests | 1,000/window |
| Refill | ~133 tok/sec, continuous bucket |

**The cap is rate, not size.** The graph fits trivially; it struggles to be
re-sent. Today's turn = 430 preamble + ~20 question + 2,560 reservation ≈ 3,010.

| Graph | Per turn | Turns/min |
|---|---|---|
| 0 | 3,010 | 2.7 |
| 1,000 | 4,010 | 2.0 |
| 2,000 | 5,010 | 1.6 |
| 4,000 | 7,010 | 1.1 |

Reservation dominates the graph — cutting reservations buys more headroom than
shrinking it.

**The one question that decides the design: does prompt caching discount a
stable prefix against the rate limit?** The graph is a stable prefix. Yes →
near-free after the first request. No → full freight every turn, forever.

## Three layers, one truth

| Layer | Where | Size | Access | Holds |
|---|---|---|---|---|
| **L1** | in every request | ~1–2k tok | always present | compressed nodes + shape of what was omitted + pointers |
| **L2** | disk, FTS5 index | 10⁴–10⁵ | `SELECT`, no model call | entities, relations, facts with rank |
| **L3** | `store.py` `log` | unbounded | rare, route-planned | everything; L1/L2 recomputable from it |

**Not dual-write — PROJECT.** L3 takes the append; L1 and L2 are derived views.
Graph-first-then-archive, interrupted, leaves memory with no provenance →
breaks `INV-EVID-2`.

**L1 must carry the shape of the omitted**, ~15 tok/node: *"47 facts under
'work'; 3 resident; pointer."* Buys: VESPER knows what it doesn't know (a silent
drop otherwise leaves it *confidently* ignorant — undetectable, unlike a miss),
and grounding survives (`INV-EVID-2` needs a resolvable span; a pointer is one).

### L3 already exists

```
STORES      = ("log", "state", "audit", "tombstones", "workspace")
APPEND_ONLY = ("log", "audit", "tombstones")
```

`core/store.py` is SQLite — stdlib, append-only at the storage layer,
HLC-ordered, lease epochs, tombstones. **FTS5 and JSON1 both available**: no
dependency, no vector DB.

**So ×2 costs nothing extra.** One model call → one record carrying both
renderings → one `append()` returns a `seq` → L1 carries the compressed
rendering *plus that seq as pointer*. A reference, not a copy that can drift.

## Two writers

- **VESPER, deliberate** — its own files, nothing else touches them. Judgement →
  **rank 5**. Writes to L3 only.
- **Updater, automatic** — after every act, background. Captures whether or not
  it looks important. The net under everything VESPER failed to notice.

**`INV-EVID-1` forbids a model prior asserted into memory, so a model extractor
cannot produce rank 4.** Verbatim owner utterance = rank 4; the extractor's
reading of it = rank 5. Store both, separately, or the system permanently and
invisibly promotes its guesses to the owner's word.

## Authority ranks — `DF-MEMORY-AUTHORITY`, specified, unimplemented

```
1 system_rule · 2 source_of_record · 3 current_observation
4 user_statement · 5 derived · 6 model_prior (never authoritative)
```

Rank 1 live → wins alone. Three-way disagreement across 2–4 → **ask**
(`INV-MEM-1`).

## Nine subsystems

| # | Subsystem | When | Model | Gateway | If absent |
|---|---|---|---|---|---|
| 1 | VESPER | owner-facing | yes | via chooser | — |
| 2 | Chooser | before each turn | yes | own | falls back to today's deterministic path |
| 3 | Updater | after each act, bg | yes | own | memory holds only what VESPER noticed |
| 4 | Compactor | scheduled + pressure | yes | own | L1 grows until it stops fitting |
| 5 | Forgetter | sweep · command · prune | partly | own | L3 grows forever; stale facts stay authoritative |
| 6 | Arbiter | on contradiction | yes | own | silent picks — `INV-MEM-1` forbids |
| 7 | Miss recorder | on correction/repeat | partly | own | **no corpus; design can never be judged** |
| 8 | Verifier | before trusting rank 3 | registry | borrows | acting on a stale reading of a moved world |
| 9 | Redactor | every outbound request | **never** | **at choke point** | **credential reaches a provider, logged there** |

**5 · Forgetter** — three jobs, don't share a path. *Expiry sweep*:
deterministic, no model (`world.sweep_expired()` exists, called by nothing).
*Owner-commanded*: interprets "that". *Judgement pruning*: highest stakes.
Append-only makes a wrong forget recoverable — but only if someone notices, and
nobody notices an absence.

**6 · Arbiter** — separate from the updater because **the updater cannot ask a
question**. Example: owner says flight is Tuesday (rank 4); calendar says
Wednesday (rank 2). Three outcomes: write a winner (rank settles it), ask, or
**hold both and act on neither** — a state VESPER sits in, which is why it's a
subsystem. Ladder rung 1 is code; rungs 2–4 need a model.

**7 · Miss recorder** — **misses are invisible here.** No query returns empty;
VESPER just doesn't know and answers anyway. Catchable only retrospectively:

| Detector | Signal | Model? |
|---|---|---|
| Repetition | owner states something already held at ≥ rank | no |
| Correction | rank-4 statement supersedes what VESPER acted on | **yes** — fuzzy |
| Explicit absence | VESPER said "I don't have that" | no |

Writes to `audit`: situation, layer consulted, what was found, what VESPER did,
**and the correction that followed.** That pairing is the corpus. It exists no
other way.

**8 · Verifier** — registry, appended per build stage.
`fact → probe → cost → freshness`. Freshness decides check-vs-recall per fact.

| Fact | Probe | Cost | Fresh |
|---|---|---|---|
| alarm armed | read LaunchAgent | ~5 ms | 60 s |
| node 1 up | TCP/22 | ~300 ms | 5 min |
| Tuesday's calendar | calendar | ~50 ms | 1 hr |

**9 · Redactor** — **"make the model forget it" is impossible.** Text in a
request has been sent and logged. Detection must be deterministic and run
before any model sees the text (pattern + entropy, like gitleaks). A model may
be a *second* pass; never the first, **because running it is the leak.**

**Inside `ModelGateway.complete`, not per-caller.** The gateway is already the
single choke point (`INV-COST-3`). There, no subsystem can leak — including ones
written later by someone who never read this. Nine callers now.

## Credentials

| Layer | Holds |
|---|---|
| L1 / L2 | opaque handle only — `secret:7f3a` |
| L3 vault | value, encrypted, own protected store |

1. **Opaque handle.** `API-KEY,table=creds,row=17` ships a map of the vault to
   every provider every turn. `secret:7f3a` means nothing off-machine.
2. **Key in macOS Keychain, not a file.** Secure Enclave-backed here. A key read
   off disk protects against a stolen laptop and nothing running as VESPER.
   Owner can still rotate from settings.
3. **Used by CODE, never in a prompt.** VESPER says "use the stored key for X";
   the code resolves the handle. The model sees a handle, never a value.
   **Without this the vault is decorative.**
4. **Compaction may not touch a handle.** Paraphrase it and the credential is
   unreachable. Opaque token, forbidden to alter.

Same intake pass resolves relative time — "next Tuesday" → absolute, original
phrasing kept beside it.

## Sensitivity is monotonic

Owner's question: how to stop VESPER labelling sensitive material insensitive,
given unenumerable cases. **By never classifying downward.**

- Everything the owner says starts `private`.
- Relaxing requires **positive evidence**; absence of a red flag is not evidence.
- A compacted node inherits the **maximum** sensitivity of its inputs.
- A check on the result may **raise**, never lower.

You don't need to catch every sensitive thing — only to never lower a
classification. One assertion, and it subsumes aggregation: three innocuous
facts compacting into a security profile is just "the result was raised."
Hence: **privacy class is recomputed on projection, never inherited.**

## Time is a dimension, not a partition

Compaction **recognises** timelines; it does not split across them.
Partitioning walls off the cross-period patterns that produce good conclusions.
`Fact.observed_at_hlc` already makes time an attribute of every record.

## Compaction re-derives; never rewrites

```
WRONG   L1(n+1) = compact( L1(n) )
RIGHT   L1(n+1) = project( L3 )
```

Kills four permanent failure modes at once: **generation drift** (each pass is a
translation; meaning degrades with no hallucination), **poisoning** (one
hallucination enters wearing an old memory's clothes and survives every later
pass), **uncorrectable corrections** (Y baked into a summary can't be un-baked
by compressing further; re-deriving from a log containing the correction just
works), **unrecoverable bugs** (fix the compactor, re-project).

Cost: projection reads more of L3 each time. That's what the compactor's own
gateway and off-peak schedule are for.

## Routing profile — 11 fields

Owner's 5 plus 6 missing.

| Field | Why |
|---|---|
| key provider · models · benchmark | owner's |
| context window · size | owner's |
| effort levels | owner's |
| **egress class** | the updater handles raw owner speech — E1-private only |
| **rate limits (TPM/RPM)** | the binding constraint |
| **cost class** | `INV-COST-5`: metered-free is paid unless a hard cap is provable |
| **measured latency** | `INV-HW-2`: measured at enrolment, never declared |
| **supported parameters** | "OpenAI-compatible" ≠ one parameter set; a 400 on `reasoning_effort` cost a rung once |
| **retirement policy** | a class terminal for the updater may be fine for the verifier |
| **concurrency limit** | background subsystems can burst |
| **preemption** | **owner waiting → background yields.** Separate keys stop quota competition, not machine competition |

### Self-repair — propose, report, ask, then apply

`provider_supply.toml` is in `contracts/policy/`; `INV-SELF-*` permits proposing
into `workspace/`, forbids self-applying. Owner's resolution, accepted:

1. VESPER investigates the dead end and **lays out the finding and the actions**.
2. **Reports and asks permission immediately.**
3. On approval, **applies it.**

Split underneath: **measured availability written freely** (this rung 404s, this
model is gone — observation, which `INV-HW-2` wants recorded); **contract
changes proposed.** Matches `selfmod.Proposal`.

## Ten ways it breaks

1. **Cold start** — L1 grows fastest when compaction has least to work with;
   early facts over-weight themselves and stay.
2. **Aggregation** — innocuous facts compact into a security profile. Answered
   by monotonic sensitivity above.
3. **Continuous exposure** — resident memory reaches whichever provider answers,
   every turn, and sits in its logs. Forecloses public rungs permanently.
4. **Throughput cliff** — bigger requests hit the rate limit sooner, so long
   conversations fail over to slower rungs precisely when going well.
5. **Convergence** — lossy, repeated, forever: either it stops shrinking (L1
   outgrows budget) or asymptotically holds nothing. A useful equilibrium is an
   assumption, and it is the one the design rests on.
6. **Metadata vs compression** — rank, source, time, privacy, pointer are all
   mandatory and all overhead against the pressure to be small.
7. **Secrets** — answered by the redactor, but only if it is deterministic and
   at the choke point.
8. **Another person** — `DF-IDENTITY-RESOLVE` returns `unknown_person` as a
   distinct role. VESPER must not disclose owner memory in their presence, nor
   learn from them as the owner. Nothing implements either.
9. **Divergence** — two nodes append and project; if projection is not a pure
   function of the log they disagree while the log agrees.
10. **Time** — relative time stored relatively is wrong the next day.

### Two more, raised 2026-08-27

11. **L3 is one SQLite file on one machine.** Disk dies → all memory gone.
    `INV-PLACE-3` says VESPER is not pinned to a machine; its memory currently
    would be. Needs replication or a stated backup policy, decided now.
12. **Append-only makes the record format permanent.** Old rows stay in the old
    shape forever. **Every record needs a schema version from the first write**
    or the shape can never change.

## Spikes, gating order

| # | Question | Falsified if |
|---|---|---|
| S1 | Is a stable prefix discounted against TPM? | cached tokens charged in full — the graph permanently divides throughput |
| S2 | Does compaction converge? | size grows monotonically, or recall falls below the bar |
| S3 | Can the metadata be afforded? | overhead exceeds compression gain — L1 has no reason to exist |
| S4 | Is resident cheaper than retrieving? | resident loses on tokens or latency |

**There is no corpus.** The 91 MB of transcripts and 1,060-line `MEMORY.md` are
the *builder's* notes — `docs/design/HOME-CONTENT.md:117` says so explicitly.
S2 and S4 need a corpus that does not exist, which is why the miss recorder is
not optional.

## Undecided

- **The unit** — fact triples are rankable and decayable but lose nuance;
  episodes are faithful and unqueryable. L3 holds both; L1 probably cannot.
- **Who sets expiry** — a model guessing a TTL decides what the owner keeps.
- **The chooser's latency budget** — a number to set before building.
- **What the updater refuses** beyond credentials.
- **How L2 is navigated** — "cheap traversal" is a requirement, not a mechanism.
- **L3 replication** — see 11.

## Governing artefacts

`DF-MEMORY-AUTHORITY` · `INV-MEM-1` · `INV-EVID-1/2/3` · `INV-LEARN-1/2/3` ·
`INV-LOSS-1/2/3` · `INV-PERF-1` · `INV-PLACE-3` · `INV-COORD-4` · `INV-SELF-*` ·
`INV-COST-3/5` · `core/privacy.py` · `core/world.py` (`Fact` carries subject,
attribute, value, HLC, source, confidence, `valid_until_ms`, `conflicting`) ·
`core/evidence.py` (`resolve_memory_conflict`, `SpanIndex`) · `core/store.py` ·
`core/context.py` (`ContextBudgetManager`, `recent_dialogue`).

**Almost all built. Almost all reachable by nothing.**
