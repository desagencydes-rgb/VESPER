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

**Rate limits are not one shape.** Groq binds on 8,000 tokens/min. Mistral binds
on **4 requests/min** with 250,000 tokens/min — 62,500 tokens per request before
volume binds at all. On a request-capped rung a resident graph is free, and the
throughput cliff below (4) does not exist. The binding constraint is per rung,
never a property of "the provider ladder".

**Latency at size, measured 2026-08-28:** Mistral served 8,250 resident tokens
in 0.84–1.17 s against Groq's 0.42–0.67 s at 2,768. One 6.7 s outlier in four
calls, so the tail is uncharacterised. A large resident block does not cost
conversational speed.

**Tokenizers disagree by 31% on identical bytes** — 8,800 characters measured as
2,768 tokens on Groq and 3,631 on Mistral. L1's budget is per-provider; a single
number would be wrong on every rung but one.

### Caching — MEASURED 2026-08-28, and the experiment was confounded

| Run | Prefix | Gap between calls | Cached | Charged to the rate limit |
|---|---|---|---|---|
| small | 3,631 | **0.67 s** | 0 | 3,636 — full freight |
| large | 8,249 | **17 s** | 8,224 | **30** |

A repeated prefix CAN cost 0.4% of freight. That is the result the design
needed and it is real.

**But the two runs differ in prefix size AND in the gap between calls**, because
`--spacing` was added for Mistral's 4-requests-per-minute limit and its effect
on the thing being measured went unnoticed. Either variable explains both rows.
So **it is not known whether the discount is bought by SIZE or by WAITING**, and
every economic claim resting on a size threshold is provisional until one
variable moves at a time.

Published minimums make the size story the less likely one: OpenAI is 1,024
tokens, Anthropic 1,024 for Opus/Sonnet. A ~4,000-token threshold would be far
above the industry norm.

**The remaining question is cache TTL and it may be the one that decides the
design.** A discount that expires in five minutes is worth nothing to an
assistant whose owner speaks to it every twenty.

## Three layers, one truth

| Layer | Where | Size | Access | Holds |
|---|---|---|---|---|
| **L1** | in every request | two blocks, see below | always present | block A: rules + index of what exists · block B: the facts this turn needs |
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

## L1 — two blocks, in different places, for different reasons

```
[ BLOCK A ]  cached, stable        persona + rules + voice
                                   index: "47 work facts, 12 people, 8 rules"
[ BLOCK B ]  fresh, uncached       the 3-5 facts THIS turn needs
[ question ]
```

**Why two and not one.** A single block cannot satisfy both constraints at once:

- **Caching wants stability first.** The discount is prefix-keyed, so stable
  content must lead and volatile content must trail.
- **Attention wants importance at the EDGES.** Long-context accuracy follows a
  U-curve; the middle degrades by >30%. Ordering purely for the cache puts the
  facts in the middle — the worst position available.

Two blocks resolve it. A leads (cache-optimal AND high-attention), B sits last
against the question (the other high-attention position), and the weak middle is
left deliberately empty.

**Block A holds the INDEX, not the knowledge.** This is the correction to the
original design. Context-rot measurements across 18 models find degradation is
driven by length *and* by distractors, and specifically that **topically related
but irrelevant content harms more than unrelated filler**. Resident personal
memory is exactly that: related, and mostly irrelevant to any one turn. Carrying
every fact resident maximises the most harmful kind of context there is.

So A carries what memory CONTAINS — `47 facts under "work"; 3 resident;
→log:1183` — which is what keeps absence non-silent, at ~15 tokens per node
instead of the facts themselves.

**Block B is selected deterministically.** FTS5 plus bounded graph traversal
over L2, no model call, single-digit milliseconds. **This is what preserves the
owner's founding insight**: there is still no recall EVENT, nothing waits on a
retrieval hop, and a self-initiated act with no user turn still gets a block B.
What was rejected was recall-as-a-round-trip, not selection.

**Merging persona into A is not tidiness — it is what makes persona cacheable.**
Measured 2026-08-28: `persona.toml` + `voice.toml` are ~1,590 tokens of content,
shipped as their own system prompt every turn and below every published cache
minimum. Alone they can never be discounted. As stratum 0 of block A they cross
the threshold and both halves go nearly free.

**The merge is in RENDERING, never in AUTHORITY.** Persona lives in
`contracts/policy/`, governed, reviewed changes only (`INV-SELF-*`). Memory is
derived. Block A renders from the contract and **the memory system may never
write into it** — without that line a compaction pass could rewrite VESPER's own
rules and no gate would notice.

**A better structure exists and is out of reach.** Position-independent caching
(EPIC, CacheBlend) caches chunks modularly and composes them in any order,
dissolving the cache-versus-attention conflict entirely. It requires controlling
the serving stack (vLLM + LMCache). Hosted APIs do not expose it and local
inference is ruled out on this host. Revisit only if node 1 ever serves.

## L2 — a graph schema inside SQLite

The owner asked whether L2 should be a graph, a network, a model, a database, a
JSON file or a graphify snapshot. **"Graph versus database" is a false choice:**
the graph is the logical model, SQLite is the physical store. `entity`, `edge`
and `fact` are tables; traversal is a bounded recursive CTE.

Ruled out, with reasons:

| Candidate | Why not |
|---|---|
| A model / neural net | no citable span (`INV-EVID-2`), unauditable, cannot be updated incrementally |
| Vector DB | similarity is never sufficient for a citation; a dependency in a stdlib-only corpus |
| JSON file | no index, load-everything-to-query, no safe concurrent write |
| graphify snapshot | wrong lifecycle — a builder's snapshot on the owner's keys; L2 is live and incrementally written |

FTS5 and JSON1 are both already available and `core/store.py` is already SQLite.
This closes the open item *"how L2 is navigated"*: bounded-depth recursive CTE,
no model call.

**The query is on the critical path of every turn**, so it is a latency budget
item, not an implementation detail. The risk is not the full-text lookup — it is
the traversal depth × fanout and the ranking that picks 3–5 rows out of
thousands. Both are measurable now against synthetic data, because what is being
tested is the index, not the content.

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

## What the updater refuses, and where refusals go

The updater captures indiscriminately by design. That makes its refusal list
the only thing standing between "a safety net" and "a file that quietly
accumulates everything the owner ever said near a microphone".

**Refusing is not deleting.** Owner's decision, 2026-08-28: refused material
goes to a **quarantine**, not to nothing. VESPER may read it for a deliberate
check; the projections never do. Two properties follow, and both are the point:

- **A wrong refusal is recoverable.** Without quarantine, over-refusal is a
  silent permanent loss and nobody notices an absence.
- **A wrong RULE becomes visible.** One refusal is an event; five hundred of
  the same shape is a pattern, and the pattern is only visible if the refusals
  are kept somewhere countable.

**This inverts the default.** The obvious instinct is to refuse as little as
possible so nothing is lost. With a quarantine the asymmetry reverses: an
over-refusal is a retrievable inconvenience, an under-refusal is a permanent
record of something that should never have been written. **Refuse generously.**

### Three classes, and the first one may not be quarantined either

| Class | Written to memory? | Quarantined? |
|---|---|---|
| **Credentials · keys · tokens · passwords** | Never | **The FACT only** — time, source, why. Never the value |
| **Owner-designated sensitive** | No | In full, owner-reviewable, releasable |
| **Low-confidence extraction** | Yes, at rank 5 | n/a — a rank, not a refusal |

**Class 1 must not be quarantined in full, and this is the trap.** A quarantine
holding every credential VESPER has ever seen is a more attractive target than
the vault, because it is the one place they are all gathered and it was built
to be the low-security bin. What is kept is the tombstone: *a credential-shaped
string was refused here, at this time, from this source* — enough to audit the
detector, useless to a thief.

### The rules, split by who decided them

**Settled — no owner input needed:**

1. **Credential-shaped strings.** Deterministic detection, pattern plus
   entropy, before any model sees the text.
2. **Speech from an unidentified person** is never stored as the owner's
   memory. `DF-IDENTITY-RESOLVE` already returns `unknown_person` as a distinct
   role; nothing implements the consequence.
3. **The updater's own reading of an utterance is rank 5, never rank 4.** Not a
   refusal — a rank. Store the verbatim utterance at rank 4 *and* the reading at
   rank 5, separately, or the system permanently promotes its guesses to the
   owner's word.

**Proposed, needs the owner's call — these are policy, not engineering:**

4. Medical detail
5. Financial account detail, as distinct from credentials
6. Substantive content about identifiable third parties
7. Anything said while the owner has marked the moment private

**Deliberately NOT on this list**, because a plausible-sounding rule that fires
wrongly is worse than a missing one: no refusal on "emotional content", none on
"negative statements", none on profanity, none on anything requiring judgement
about *tone*. Every one of those needs a model to evaluate, and a model in the
refusal path is the same defect as a model in the redactor — running it on the
text is the thing being avoided.

## Background work never blocks the owner

Owner's requirement, 2026-08-28: everything running before and after the
owner-facing turn runs in the background, and VESPER continues regardless.

| Rule | Why |
|---|---|
| **The turn never awaits a background subsystem** | Capture, miss recording and verification are dispatched and forgotten. A turn that waits on its own bookkeeping is slower than one with no memory at all |
| **A background failure never fails the turn** | The updater dying must not turn a good answer into an error. Failures are recorded and triaged later, when a model is available again |
| **Background work is idempotent, keyed** | Delivery is at-least-once, so the same capture arriving twice must not produce two facts. Keys on the event id |
| **Ordering is by logical clock, never arrival** | Two background jobs finishing out of order must not reorder memory. Wall-clock ordering is already forbidden |
| **The owner waiting preempts background work** | Separate keys stop quota competition, not competition for the machine |
| **Backpressure sheds oldest-first, and records the shed** | If capture falls behind, it drops the oldest and says so. Silently dropping the newest loses what just happened, which is the material most likely to matter |

### Thresholds and budgets

| Path | Budget | On breach |
|---|---|---|
| Difficulty judgement (no model) | 5 ms | Fall through to `moderate` |
| Memory selection for a turn | **25 ms** | Ship what was found; note the truncation |
| Chooser, deterministic | 10 ms | Escalate to the model path |
| Chooser, model path | **250 ms** | Hold the floor and say so |
| Hold announcement threshold | **600 ms** total elapsed | Below this, say nothing at all |
| Turn, end to end | 1,200 ms | Existing budget, unchanged |
| Capture, per act | 30 s, background | Retry once, then quarantine the input |
| Compaction pass | unbudgeted, off-peak | Yields to any owner-facing work |

**The hold announcement threshold is separate from the chooser budget on
purpose.** Announcing at 250 ms would make VESPER apologise constantly for
delays nobody perceives; 600 ms is roughly where a pause stops reading as
thinking and starts reading as broken.

**While the floor is held, inbound is classified and not obeyed** —
`core/barge_in.py`. Cooperative interruptions are swallowed, liveness checks
get a status line without cancelling, competitive ones stop the work, and
anything else is queued and delivered afterwards. Ambiguity breaks through,
because a wrong break costs one preparation cycle and a wrong swallow means
"stop" was ignored.

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

13. **Distractors, not just size.** Degradation is driven by irrelevant content
    as much as by length, and **topically related but irrelevant content harms
    more than unrelated filler** — which is precisely what resident personal
    memory is. This is the strongest argument against the original design and it
    is why block A now carries the index rather than the facts. Unresolved:
    the residual distractor cost of block A itself (S5).

### Two more, raised 2026-08-27 — both now answered

11. **L3 was one SQLite file on one machine.** Answered by the backup policy
    below.
12. **Record format permanence — DOWNGRADED 2026-08-28.** The original claim
    was that append-only makes the shape permanent and a version field cannot
    be added later. **That is wrong**: the system appends but the OWNER may
    edit, so an owner-authorised migration can rewrite old records. A version
    integer per record is still worth having — it makes a migration a lookup
    rather than a guess — but it is routine, not a one-way door, and it blocks
    nothing.

## Write modes — "append-only" is about the SYSTEM, not the owner

Owner's clarification: the system may only append; the owner may change
anything. Reconciled without losing provenance:

| Mode | Who | Effect |
|---|---|---|
| **Append** | system | normal path. New record, HLC-ordered. |
| **Supersede** | **owner only** | an "edit". A NEW record at rank 4 superseding the old; both remain. |
| **Erase** | **owner only** | content destroyed. Tombstone records *that* an erasure happened, when, by the owner — never what. |

**An edit must not be an in-place mutation.** Mutating a row leaves
`observed_at_hlc` claiming a time that belongs to different content — the audit
trail becomes false, and `INV-LOSS-3` loses the evidence base it depends on.
Supersession gives the owner total control while every projection re-derives
correctly.

**Erase exists because supersession is not enough.** Some content should never
have existed — a leaked key, something recorded in error. The tombstone keeps
"something was removed here" auditable without keeping the content.

## Backup — everything, in two places by class

| Class | Destination | Mechanism |
|---|---|---|
| Ordinary memory | **private GitHub repo**, branch per type | export on write |
| Credentials · highest sensitivity | **each node**, secure local store | auto-sync when node is on network |
| Large files | **each node** | same path as credentials |

### Five constraints on that

1. **The redactor guards this path too.** Git history is effectively permanent:
   a force-push does not remove a secret from clones, forks, or GitHub's
   unreachable objects. So the redactor is an **egress** component, not a
   provider component — one implementation, called at every boundary off this
   machine: providers, GitHub, node sync.
2. **Never commit the SQLite file.** Binary blob, no meaningful diff, whole file
   rewritten per commit; the repo bloats and history is unreadable. Export
   **JSONL or a SQL dump** — diffs, compresses, greps, restores.
3. **Name files `(node, epoch)` and merges never conflict.** Two nodes pushing
   one branch will fight; two nodes writing their own append-only files merge by
   union. HLC still orders the contents.
4. **A private repo is access control, not encryption.** GitHub staff, a
   compromised token, one mis-click to public. Acceptable for ordinary memory;
   name it rather than assume it.
5. **The vault is as strong as the weakest node holding it.** Replicating
   credentials to every node multiplies the attack surface across machines with
   different protections (node 1 Windows, node 2 Kali). The alternative —
   credentials on one node, others requesting on demand — costs offline use.
   Owner's call; it should be a decision.

## The sensor layer, and the "unconscious"

**The gap this closes.** Everything above assumed a turn exists. VESPER's whole
premise is that it acts without one — camera checks, calendar, code, stale
plans, unfinished tasks, self-research, unresolved questions, incoming
calls/SMS/WhatsApp/Telegram, socials. Nothing in the memory design says what
GENERATES those.

**Most of it is already built and reachable by nothing.** As with the rest of
this corpus, the finding is not a missing design:

| Artefact | State |
|---|---|
| `contracts/policy/interruption_budget.toml` | complete wake budget. Read only by `core/narration.py`, `core/alarm.py` |
| `contracts/policy/trigger_registry.toml` | 8 triggers, `STATE`/`EVENT`/`COMPOSITE` predicates, debounce, cooldown, resource budget | 
| `INV-TRIG-7` | *a model may propose a trigger, never BE one* — already the rule the always-on layer needs |
| `trg_fact_expiry_sweep` | the sweep class already exists |

**What is genuinely missing is the INPUT side.** Predicates reference
`world.owner.attention_state`, `nodes.reachable_set`, `world.current_host.health`
— and nothing populates them. **That is what a sensor is:** not a new subsystem,
but the thing that makes the existing predicates evaluable.

### Five source classes

They differ by WHAT MAKES THEM HAPPEN, and that decides the mechanism.

| Class | Nature | Sources |
|---|---|---|
| **Interrupt** | pushes, time-critical | incoming call, SMS, WhatsApp, Telegram |
| **Queue** | pushes, not urgent | file changed, mail, a flag set |
| **Timer** | cheap to check, polled | calendar, task state, disk, network reachability |
| **Gated** | expensive — needs a REASON, never a timer | camera, screen, microphone, feeds |
| **Sweep** | **nothing happens** — time alone makes it true | unfinished tasks, stale plans, unresolved questions, deferred work, self-research |

**The sweep row has no sensor because there is nothing to sense.** Nothing emits
an event when an idea has been unresolved for three weeks. It is a scheduled
query over VESPER's own memory — the same engine as block B's selector, seeded
by time instead of by an utterance.

**That answers the open question of what seeds block B on a self-initiated
turn: the sweep's finding is the seed.** One mechanism, not two.

**A sensor and the verifier are the same shape.** The verifier registry is
`fact → probe → cost → freshness`; a sensor is `source → probe → cost → period`.
Same probe, two callers — one on demand before trusting a fact, one scheduled.
One registry, not two.

### What "unconscious" decomposes into

The metaphor is load-bearing in one specific way: **the unconscious is cheap
BECAUSE it is dumb and specific.** The cocktail-party effect does not run on
general intelligence monitoring the room; it runs on a cheap always-on detector
for one's own name. Twenty specific detectors cost nothing. One general "is this
important?" detector costs a model call, always, forever.

| Function | Meaning | Model? | Status |
|---|---|---|---|
| Filtering | most of what is sensed never reaches VESPER | **never** | new |
| Salience | some things break through regardless | **never** | new |
| Priming | recent/frequent memory is cheaper to reach | **never** | = block B ranking |
| Consolidation | sorting and compressing while idle | yes, own routing | = the compactor |
| Incubation | a new fact closes an open question | rarely | a join, not magic |
| Automaticity | approved often enough → no deliberation | **never** | new, gated by `INV-SELF-*` |

Four of six are code. The answer to *"does it get its own routing and API
keys?"* is **no, for the always-on parts** — only consolidation does, and it
already has one.

### Two rules that stop it collapsing

**1. The always-on layer never calls a model.** `INV-TRIG-7` already states the
half about triggers; the sensor half needs writing. This is not cost discipline
alone: **a regex cannot be prompt-injected.** The moment a model is put in the
filter, the filter becomes the vulnerability it exists to prevent. "Let us just
have a small model watch for interesting things" is the most natural next
suggestion anyone will make, and it silently ends the design.

**2. The filter logs what it discarded.** A filter deciding what reaches VESPER
is deciding what VESPER knows, and a filter bug produces SILENCE — undetectable,
exactly like a memory miss. The discard log is the miss log's shape at a
different layer, and it is the only thing that makes the thresholds tunable.

### The untrusted-input gap

`INVARIANTS.toml:873` already holds the right principle — screen content, OCR
output and command output are `retrieved_external`, may never raise authority,
and *"an instruction read off a screen is an untrusted input, not a directive."*

**Its scope is too narrow.** It covers screens. It does not cover an incoming
SMS, a WhatsApp message, a calendar invite, or a page read during self-research
— every one of which is text an outsider can put in front of VESPER. With
sensors feeding triggers, anyone able to message VESPER can attempt to steer it.

**Extend the existing invariant's scope rather than adding a rival to it.** A
sensor's output is data, never a command, whatever the channel.

The outbound direction needs a gate for the same reason: VESPER holding a phone
number can initiate contact, and that is rate-limited and governed, not free.

### Wake budget — already defined, and it is better than a new one

No new numbers are needed. `interruption_budget.toml` holds:

- **Lattice** `alarm_safety > active_user_task > ambience > proactive`, strict,
  not reorderable by configuration.
- **Modality cost** ambient_visual 1 · visual_notice 3 · speech 8 · alarm
  `EXEMPT` (deliberately not a number — an exempt class must not be comparable).
- **Per-state ceilings** ACTIVE_SESSION.focused 8/hr, 2 contacts · .available
  24/hr, 6 · IDLE.present 16/hr, 4 · IDLE.absent 3/hr, 1 · FREE_TIME **0** ·
  DND **0**.
- **Rule** `act_now ⟺ expected_value > interruption_cost AND decays`, otherwise
  `QUEUE_TO_BOUNDARY`; `drop_permitted = false`.

And it already answers *"how often may VESPER act WITHOUT interrupting me"*:
`[preparation] budgeted = false` — research, indexing, drafting, benchmarking and
proposal filing are bounded by resource and cost policy, never by the
interruption budget. `INV-IDEA-6`: **idle time expands available time, never
authority.**

### Sources — designed now, connected later

Not needed for data gathering, spikes or testing. Listed so that the day a
channel is enabled it is a registry row and not a redesign.

| Source | Class | Notes |
|---|---|---|
| calendar · task state · disk · reachability · host health | Timer | cheapest, already partly in `host_actions.toml` |
| filesystem / repo change · mail · flags | Queue | |
| SMS · WhatsApp · Telegram · voice call | Interrupt | **untrusted text; needs the extended invariant before enabling** |
| camera · screen · microphone · feeds | Gated | never on a timer — a cheap sensor must gate them; power is the constraint |
| unfinished tasks · stale plans · unresolved questions · deferred work · self-research · low-priority projects | Sweep | no sensor exists; scheduled L2 query |
| social accounts | Timer or Queue | outbound is governed, not free |

## Which providers serve which subsystem

Owner memory is private, so **rule R6 puts every memory-touching subsystem on
E1_PRIVATE rungs only** — Cloudflare, Groq, Ollama, Mistral, Claude CLI. The
public rungs (four Gemini keys, NVIDIA, OpenRouter) can never see memory however
generous their quota.

| Subsystem | Rung | On what basis |
|---|---|---|
| Chooser | Groq | 0.42–0.67 s measured; it is inside the latency path |
| VESPER main | Groq → Mistral | fast first, quality on failover |
| Compactor | Mistral | 250k tok/min, caches, latency irrelevant |
| Arbiter | Claude CLI | judgement, rare, no metered quota |
| Updater | Cloudflare | high volume, background |
| Miss recorder | Cloudflare / Ollama | cheap, background |
| Forgetter | Claude CLI | highest stakes, rarest |
| Verifier | mostly no model | probes, not inference |
| Redactor | **never a model** | running one IS the leak |
| Sensors + filter | **never a model** | always-on; and a regex cannot be injected |

**Nine subsystems, five private rungs.** Per-subsystem isolation is therefore
**per-ACCOUNT, not per-provider** — separate Groq/Mistral/Cloudflare accounts, as
already done with four Gemini keys. The owner has confirmed additional accounts
are available. Quota isolation is the goal; the provider need not know the
accounts are related.

**Two rungs cannot be measured at all.** Cloudflare reported `prompt=0,
completion=0` on three working calls (consistent with its known-unreliable
usage reporting) and Ollama returns no rate-limit headers. Under fail-closed
doctrine unmeasurable spend is unusable, so both need another accounting route
before they carry a subsystem.

**Mistral reports cost directly** — `x-ratelimit-tokens-query-cost` — which is
better evidence than a delta between two observations. Worth reading in
production.

## Spikes, gating order

**S1 is answered in part.** A repeated prefix costs 0.4% of freight on Mistral.
What remains is which variable buys it.

Runnable now, no corpus needed:

| # | Question | Why it decides something |
|---|---|---|
| M1 | **Cache TTL** — how long the discount survives | possibly decisive: a discount expiring in 5 min is worth nothing to an assistant spoken to every 20 |
| M2 | **Size vs waiting**, one variable at a time | resolves the confound above; every economic claim rests on it |
| M3 | **Does Groq cache at all** | decides whether the 0.4 s rung gets the discount or only the 1 s one |
| M4 | **SQLite: FTS5 + traversal + ranking** at 10⁴ and 10⁵ facts | block B is on every turn's critical path; must be single-digit ms |
| M5 | **Cloudflare and Ollama measurability** | unmeasurable spend is unusable, fail-closed |
| M6 | **Token density per rung** | 31% spread already seen; L1's budget is per-provider |

Blocked on a corpus that does not exist:

| # | Question | Falsified if |
|---|---|---|
| S2 | Does compaction converge? | size grows monotonically, or recall falls below the bar |
| S3 | Can the metadata be afforded? | overhead exceeds compression gain |
| S4 | Is resident cheaper than retrieving? | resident loses on tokens or latency |
| S5 | **Does a large block A measurably degrade answers?** | it does — block A shrinks to the index alone, permanently |

**There is no corpus.** The 91 MB of transcripts and 1,060-line `MEMORY.md` are
the *builder's* notes — `docs/design/HOME-CONTENT.md:117` says so explicitly.
S2 and S4 need a corpus that does not exist, which is why the miss recorder is
not optional.

## Undecided

- **What the updater refuses** beyond credentials — items 4-7 above are
  policy, awaiting the owner.
- **Filter thresholds** — how loud a thing must be to wake VESPER. The mechanism
  is cheap and the dials need the corpus; sane defaults, tuned from the discard
  log.

**Closed 2026-08-28.** *Credential replication* — every node, same copy, same
unlock credential; the unlock credential itself never rests on a node, or
replicating the vault replicates its key. *Expiry* — nothing expires by
deletion; staleness is a ranking input and supersession the only removal, so
the constant case needs no model and the two rare cases share the arbiter's
rung. *The unit* — short searchable form in L2 with a pointer to the full
exchange in L3; the short form is what can be wrong, and only the failure
record catches that. *Chooser budget* — deterministic first at 10 ms, model
path at 250 ms, announce past 600 ms. *Schema version* — an integer per record,
routine.

**Closed since 2026-08-27:** *how L2 is navigated* (bounded recursive CTE over a
graph schema in SQLite) · *what seeds block B on a self-initiated turn* (the
sweep's finding) · *the wake budget* (already specified in
`interruption_budget.toml`; no new numbers needed).

## Governing artefacts

`DF-MEMORY-AUTHORITY` · `INV-MEM-1` · `INV-EVID-1/2/3` · `INV-LEARN-1/2/3` ·
`INV-LOSS-1/2/3` · `INV-PERF-1` · `INV-PLACE-3` · `INV-COORD-4` · `INV-SELF-*` ·
`INV-COST-3/5` · `core/privacy.py` · `core/world.py` (`Fact` carries subject,
attribute, value, HLC, source, confidence, `valid_until_ms`, `conflicting`) ·
`core/evidence.py` (`resolve_memory_conflict`, `SpanIndex`) · `core/store.py` ·
`core/context.py` (`ContextBudgetManager`, `recent_dialogue`).

**Almost all built. Almost all reachable by nothing.**
