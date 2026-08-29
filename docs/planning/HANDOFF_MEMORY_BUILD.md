# Handoff — VESPER to completion

**Deadline: 2026-09-12. Fourteen days from 2026-08-29, for ALL of VESPER,
running on the MacBook.** Other nodes come after, by owner decision 2026-08-29.

**Single-node DEPLOY, never single-node DESIGN.** `INV-PLACE-3` stands: VESPER
is not pinned to a machine, and a new node joins the fabric and wins placement
on merit. Nothing here may be simplified on the assumption that one node is all
there will ever be — the multi-node modules stay built, gated and green; they
simply do not need wiring into the running Supervisor before the deadline.

Read `MEMORY_ARCHITECTURE.md` for reasoning, `OPEN_QUESTIONS.md` for what is
unproven, `DATA_PLAN.md` for what the evidence can and cannot support. This file
is the state and the order, nothing else.

---

## The scope, measured rather than estimated

**The largest lever is wiring, not building.** Measured 2026-08-29: the
`Supervisor` — which is what a running VESPER actually *is* — wires twelve
modules (bus, completion, config, cost, gateway, hlc, lease, policy, router,
store, tasks, telemetry). Nine more are built, gated and green under their
acceptance runs while being reached by **nothing in the running process**:

| Module | On the 14-day path? |
|---|---|
| `placement` · `fabric` · `enrollment` · `reconcile` | **No** — multi-node. Stay built and gated; wire them when a second node joins |
| `taint` | **Yes, and it shortens the memory build** — see below |
| `projection` | **Yes, and it shortens the memory build** — see below |
| `interlock` | **Yes** — the emergency stop. A daily-use VESPER without a working dead-man's switch is not finished |
| `devices` | Yes — the sensor layer needs a device registry, and this one already stores classes rather than product names |
| `repair` | Yes — graded, tiered failure repair, already honest about what it cannot fix |

### Two of them are memory work that is already done

**`core/taint.py` already implements monotonic sensitivity.** The memory design
requires that a compacted node inherit the strictest sensitivity of its inputs,
and that a check may raise a classification but never lower it. That module
exists, is gated, and states the rule the implementation would otherwise omit:
*a summary of tainted content is tainted*. `summarise()` returns a `Tainted`
rather than a plain string, `ceiling()` takes the most restrictive class across
fragments, and `TaintedCache` preserves taint through cache reuse — which is
exactly what block A's cached prefix needs. **Do not write a second sensitivity
system. Use this one.**

**`core/projection.py` already implements provenance-bound readings.** A
`Reading` cannot hold a value without provenance or provenance without a value,
and it carries `expired()`, `age_ms()` and `unavailable()`. That is the
freshness machinery the verifier registry and block B selection both need, and
the projection pattern L1 and L2 are specified to follow.

`core/autonomy.py` is the same story: a full trigger loop with a predicate
evaluator that structurally cannot call a model, and `trigger_registry.toml`
holds eight triggers of which **one** is wired. `interruption_budget.toml` holds
the complete wake budget and is read by two files.

This is the corpus's own recurring finding turned into a schedule: *almost all
built, almost all reachable by nothing*. Hours spent connecting existing,
already-verified components buy far more capability than hours spent writing new
ones — and they carry far less risk, because the components already have gates.

### What cannot be done in fourteen days, at any speed

**Hardware-blocked**, and no amount of engineering moves them: the iPhone app,
cameras, and the flat clear sheet. Node-1 and fabric work is now **out of scope
by owner decision** rather than merely blocked — other nodes come after the
deadline.

**Empirical validation of memory.** Does carrying memory improve answers, does
re-summarising converge, does selection find the right facts, how large the
resident block gets — every one needs a corpus of real use, and that accumulates
at the speed the owner talks to VESPER rather than the speed anything is built.
Two weeks cannot observe drift or erosion, which are the slow failures.

**So the deliverable is a working system with known-unvalidated properties.**
That is what a prototype is and it is fine. What is not fine is the distinction
quietly disappearing: every claim about memory quality on 2026-09-12 rests on
design argument, not measurement, and must be written that way. The
instrumentation stays in the build precisely so those questions become
answerable later — which is also why the corpus generators come early, since
every day they run before the deadline is a day of evidence.

## Suggested fourteen-day shape

Owner may re-cut this; it is a proposal, not a decision already taken.

| Days | Work |
|---|---|
| 1–4 | **Memory core.** L2 graph store → updater + miss recorder → redactor → block A/B rendering. Ends with memory flowing and the corpus accumulating |
| 5–7 | **Wire what exists.** Autonomy loop into the Supervisor, the seven unwired triggers, the interruption budget, and the five node-local modules above. Highest capability per hour of anything here |
| 8–10 | Chooser · compactor · sensors populating the world model the predicates already read |
| 11–13 | Voice I/O if it fits; integration; hardening. **Voice is the largest single unknown** — deferred four times, `Intake.spoken()` still unused, and Darija voice quality is untested |
| 14 | Full gates, documents, and an honest statement of what is proven versus assumed |

**The one ordering rule that is not negotiable** is in the build table below: the
redactor lands before anything renders memory into a request.

## Validation, and what the deadline cannot buy

**The design cannot be empirically validated inside fourteen days, and no amount
of speed fixes that.**

Four questions — does carrying memory improve answers, does re-summarising
converge, does selection surface the right facts, how big does the resident
block actually get — all need a corpus of real use. The corpus does not exist,
and it accumulates at the speed the owner talks to VESPER, not at the speed
anything is built. Two weeks of use is not enough to observe drift or erosion,
which are the slow failures.

**So the honest deliverable is a working system with known-unvalidated
properties, not a validated one.** That is fine, and it is what a prototype is.
What is NOT fine is letting the distinction quietly disappear: every claim about
memory quality on 2026-09-12 will rest on design argument, not on measurement,
and must be written that way. The instrumentation to answer them later is part
of the build (items 2 and 4 below) — that is the correct response to the
deadline, not skipping them.

---

## Built, gated, committed

| Component | Where | Gate |
|---|---|---|
| Turn record without memory (the baseline) | `core/baseline.py` | `CI-073`, 3 red-run cases |
| Mid-hold interruption classifier | `core/barge_in.py` | `CI-072`, 3 red-run cases |
| Language mirroring, Darija + script | `contracts/policy/voice.toml` `[language]`, rendered by `core/persona.py` | `persona-is-a-contract` |
| Conversation history to all five wires | `core/gateway.py`, `routing/supply.py` | committed, **not yet wired into a live turn** |

Probes in `tools/spike/`: `cache_discount_probe`, `cache_ttl_probe`,
`cache_hitrate_probe`, `cache_truncation_probe`, `latency_sweep`,
`l1_encoding_probe`, `l2_query_probe`, `darija_probe`, `supply_ledger`.
Their raw output is in `docs/spikes/data/`.

**Gates as of 2026-08-29: 47 checks, 160 self-tests, both lints green.**

---

## Build order, and why it is this order

| # | Build | Depends on |
|---|---|---|
| 1 | **L2 graph store** — `entity` / `edge` / `fact` in SQLite, FTS5 + bounded recursive CTE | nothing. Schema already measured at ~18 ms over 100k facts |
| 2 | **Updater + miss recorder** | L2 and `core/store.py`. Writes only, no egress |
| 3 | **Redactor** | must exist before step 4 |
| 4 | **Block A + Block B rendering** | L2, redactor |
| 5 | **Chooser** | deterministic first, model only on ambiguity |
| 6 | Compactor · arbiter · forgetter | memory must exist to compact or contradict |
| 7 | Sensors | populate the world model the trigger predicates already read |

**Step 3 is not negotiable and is easy to get wrong.** Step 4 is the first moment
memory leaves the machine. A credential inside that request is sent and logged
the instant it goes, and nothing recalls it. The guard goes in **before** the
pipe, inside `ModelGateway.complete` where no subsystem can bypass it — including
subsystems written later by someone who never read this.

**Steps 2 and 4 are also what start the corpus.** Every blocked question waits on
them, so building them early buys days of accumulation before the deadline. That
is the only lever the deadline actually has.

---

## Decided. Do not re-open.

| Question | Answer |
|---|---|
| Expiry | Nothing expires by deletion. Staleness is a ranking input; supersession is the only removal. The constant case needs no model |
| Credential vault | Every node, same copy, same unlock credential — which itself never rests on a node |
| Record version | Integer per record. **Not** a one-way door: the owner may authorise a migration |
| The unit | Short searchable form in L2, pointer to the full exchange in L3. Both stored |
| Chooser budget | Deterministic 10 ms → model 250 ms → announce the hold past 600 ms |
| What capture refuses | **Credentials only.** Medical, financial and third-party content are all recorded, by owner decision |
| Off the record | Fixed phrase list, owner-driven, no inference |
| Said once isn't a trait | Ranking rule. Repetition promotes an observation toward a trait; mood is never detected |
| Language | Mirror the owner. Darija in Latin script. Tamazight is demo scope only |
| Background work | Never blocks the turn, never fails it, sheds oldest first |

---

## Traps, all of them found the hard way in this session

**A patch script that asserts and aborts does not stop `git commit`.** Two
commits carry messages describing findings that were in no file, because the
patch was chained with `&&`. Verify the write landed, then commit separately.

**`git add -A <dir>` sweeps unrelated work.** It committed the history plumbing
under a caching message, landing `gateway.py` without its `supply.py` half.
Stage explicit paths.

**Match on the bytes that are actually in the file.** Two failures came from an
en-dash where the patch said hyphen, and a bold marker that was never written.

**A probe needs a positive control, not only a negative one.** The truncation
test reported "truncation misses" on a run where the cache had never populated.
Those two produce byte-identical output.

**Instruments fail in the direction that flatters the result.** The Darija
scorer marked plainly-Darija replies as containing none, because the model wrote
`bghiti` where the list said `bghit`. A 21-minute run looked identical to a hang
because stdout was buffered, results were written only at the end, and a 120 s
timeout was inherited from an unrelated probe.

**A check that has only ever been green is not evidence, and neither is an
unrepeatable red run.** The registry refused both new checks until their red runs
lived in `self_test.py`.

**A false trace is worse than an honest lint error.** No requirement covers
"holding the floor and classifying interruptions"; forcing it onto SR-020 would
have claimed coverage of a perception requirement it does not provide.

---

## Open, needing the owner

- **Provider accounts.** Six, if each subsystem gets its own. Rows are ready and
  empty; nothing blocks until subsystems run concurrently.
- Nothing else. Every design decision is closed.

## Open, needing measurement that cannot happen yet

Everything in `OPEN_QUESTIONS.md`. Eight unverified claims, seven blocked
questions, six blind spots that no planned instrument can see. **K1 is the one to
keep in view:** a confident wrong answer the owner simply accepts produces no
event, and every failure detector in the design requires the owner to react.
