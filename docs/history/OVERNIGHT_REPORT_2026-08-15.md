# VESPER — overnight session report, 2026-08-15

**Read this first tomorrow.** It is the handover: where we are, what changed,
what is verified, what is owed, and what needs you rather than me.

---

## 1. The headline

**VESPER now runs.** When this session began the corpus was ~37,800 lines of
specification and **zero lines of anything that executes**. It is now
**6,509 lines of runtime** under `core/` and **4,274 lines of acceptance
harness** under `verification/`.

**Three of nine build stages are complete. Three more are part-built with every
software-only case passing.** Engineering has run out of unblocked work —
everything remaining needs hardware, your decision, or real elapsed time.

| | |
|---|---|
| Commits this session | 23, all pushed |
| Pull request | **#5**, open, CI green |
| Acceptance gates | **6**, all running in CI |
| Positive cases passing | **40 / 40** |
| Negative controls failing as required | **20 / 20** |
| `tools/ci/checks.py` | 17 / 17 |
| `tools/ci/self_test.py` | 47 / 47 |
| `reference_lint` · `traceability_lint` | clean · clean |

---

## 2. Where we are on the roadmap

The sequence is `W0 → F0 → F1 → F2 → F4 → F3 → F6 → F5 → F7/F8`.

| Stage | What it is | State |
|---|---|---|
| **W0** | repo, CI, contracts, ADRs | **DONE** (before this session) |
| **F0** | persistent runtime, event bus, durable tasks, checkpoints | **COMPLETE + gated** |
| **F1** | model gateway, cost choke point, router, evidence, context | **COMPLETE + gated** |
| **F2** | tool contract, authorization, taint, execution, devices | **COMPLETE + gated** |
| **F4** | perception + world model | **part-built** — world/privacy/enrollment done; perception needs cameras |
| **F3** | presence — scenes, endpoints, voice | **part-built** — scenes/outbox done; latency needs the voice chain |
| **F6** | distributed — discovery, placement, migration | **not started** — needs a second always-on node |
| **F5** | autonomy — triggers, evaluator, safety interlock | **part-built + gated** — compressed run passes; 24 h run owed |
| **F7/F8** | environment, research engine | **not started** |

**F5 is the decisive stage and it passes in compressed form.** That is the
anti-chatbot property — the thing that separates VESPER from a chatbot with a
cron job attached — and it is now *tested* rather than asserted.

---

## 3. What got built, stage by stage

### F0 — the persistent runtime *(13 positive, 6 controls)*

| Module | What it owns |
|---|---|
| `core/hlc.py` | the total order. Nothing else may compare timestamps. |
| `core/store.py` | five physical stores, epoch fencing, append-only guards |
| `core/bus.py` | typed envelopes, mandatory consumer idempotency |
| `core/lease.py` | ownership, fencing tokens, refusal to self-promote |
| `core/tasks.py` | durable task state, checkpoints, the outbox |
| `core/telemetry.py` | write-time redaction, budget accounting |
| `core/policy.py` | named decision points with a deny default |
| `core/config.py` | measured-vs-declared provenance |
| `core/supervisor.py` | assembles and owns the lifecycle |

Invariants are enforced **structurally**. `INV-TASK-1` is the *absence of an
edge* in the transition table — there is no `RUNNING → SUCCEEDED`, so the
shortcut is unavailable rather than discouraged. A task can only reach success
through `VERIFYING` with a passing verdict.

### F1 — cost, routing, evidence *(7 positive, 4 controls)*

The cost rule is unconditional and deliberately asymmetric: *"user is asleep"*
during `ACTIVE_SESSION` may enter `FREE_TIME`; *"user is awake"* during
`FREE_TIME` may **not** leave it. Same inference, same confidence, opposite
treatment — because wrongly entering `FREE_TIME` delays work and wrongly leaving
it spends money that cannot be unspent.

**The router is where last night's measurements stopped being a document.** It
uses wall-clock throughput (the generation figure said this machine got *faster*
under load while wall clock fell 42%), treats a tier's rate as a function of
context (the measured 17.6 µs/token KV slope), and checks **host RAM** — which
is why it refuses to put the strong tier beside your working set.

Evidence is grounded **per claim**, not per response, because the adversarial
case is a mostly-correct answer with one invented specific. A citation is a byte
range that re-reads to its hash, never a similarity score.

### F2 — authorization and tools *(8 positive, 3 controls)*

A capability's level is a function of its **arguments**: `shell.run("ls")` is L1
and `shell.run("rm -rf ~")` is L5. A constant level is refused *at registration*,
and the check is adversarial — the registry calls the real function and demands
two distinct answers.

Taint survives summarisation and cache reuse, which is the failure an
implementation always omits because summarising produces a clean-looking new
string. The self-modification boundary refuses at the **filesystem**, not by
disposition, and an L5 grant does not lift it.

### F4 — world model, privacy, enrollment *(5 positive, 1 control)*

An expired fact reads `UNKNOWN`, never its last value. A conflict changes
nothing and emits. An unknown person is never resolved to you.

**The privacy matrix is all 45 cells**, and in every one of the 36 ambiguous
cells the outcome is the most private surface or `WITHHOLD` — never the largest
display.

### F3 — semantic scenes and the outbox *(3 positive, 1 control)*

One scene renders to a screen, a voice-only endpoint and a glass surface,
because content carries **what an element means** rather than how it looks. A
diagram is a typed graph, so it can narrate itself; a PNG cannot.

Reconciliation gives exactly-once **effect** across three crash points —
including the dangerous one where the action landed and the outbox does not know.

### F5 — autonomy and the interlock *(4 positive, 5 controls)*

The evaluator **cannot** call a model — its constructor takes a world model and
nothing else. The anti-cron probe is mechanical: evaluate with every clock term
true and every world term false, and if it still fires it is cron whatever it is
labelled.

The interlock is a **dead-man's switch**. Autonomy runs only while a fresh,
externally minted token is present, so severing the stop path *halts* autonomy
instead of stranding it running. Alarms survive `STOP_AUTONOMY` — an interlock
that silenced them would be one you'd hesitate to use.

---

## 4. The measurements that changed decisions

**The strong tier and your working set cannot share this machine.** Measured
with your apps open, sampling the worst moment across 180 s:

| Condition | worst-case free RAM | paging |
|---|---|---|
| your apps, no model | 6.57 GB | — |
| \+ `standard` tier (Qwen3-8B) | 2.85 GB | 10.8 pages/s |
| \+ `strong` tier (MoE 30B) | **0.27 GB** | **660 pages/s** |

The machine doesn't fail — it **pages**, invisibly to any check that only asks
whether the model loaded. Two consequences now enforced in code: the
human-present mode must *unload* the strong model rather than deprioritise it,
and residency costs **system RAM**, not just VRAM.

**`strong` has no single speed number.** It decays 39–47% across ten minutes,
which I traced to KV-cache growth (17.6 µs per token of context for the MoE,
14.6 for the dense model — nearly identical despite a 3.6× baseline difference).
So 6.79 tok/s is *the rate at ~4.2k tokens of context*, not a floor.

---

## 5. Four tests that passed while measuring nothing

This is the pattern worth carrying forward, and it bit us **four times**:

1. **SPIKE-008 fencing control** — the stale writer held a permanently expired
   epoch, so a plain `SELECT` rejected it before the race could happen.
2. **SPIKE-008 portability control** — SQLite checkpoints on last-connection
   close, so the WAL was folded back before anything was copied.
3. **F0 `INV-TASK-1` control** — built a broken dict of its own and never
   touched `core/tasks.py`. **Planting the forbidden edge in the shipped table
   left the entire F0 gate green.**
4. **F2 `30.4` artifact check** — compared the boundary's list against the
   artifact it had just read. Tautological; adding a surface left it green.

Each was written from the same mental model as the code it checked, so it
inherited the same blind spot. The only defence that worked: **run the control
against a deliberately broken build and require it to fail.** Every gate here
was verified that way — the full table is in `verification/RED-TEST-EVIDENCE.md`.

**C1 deserves special mention.** The pure-cron control fails *only part 3* — it
passes liveness and provenance perfectly with all 240 firings. That asymmetry is
the proof that the anti-cron discriminator has teeth.

---

## 6. What is owed, and by whom

### Needs you

| # | Item | Cost |
|---|---|---|
| 1 | **A flat clear sheet** — plastic sheet protector, CD case lid, acetate. Closes `SPIKE-004`. Instrument is built and served. | ~5 min of your eyes |
| 2 | **`OWNER-DECISION-006(c)`** — whether four REM-carried decisions get numbered ADR ids | a decision |
| 3 | **The ADR-001/ADR-012 authority question** — both carry `ACCEPTED` stamped by an engineering pass, not by you. The corpus says either all three are confirmed together at the readiness gate, or those two are re-confirmed. F0 proceeded on the mechanical gate. **Recorded, not resolved by the hand that wrote it.** | a decision |
| 4 | **The MacBook** — unblocks the iPhone app → `SPIKE-002` → `A-020` | acquisition |
| 5 | **The broken desktop** — the intended always-on server | repair |

### Needs hardware

`A-008`, `A-028`, `A-039` (cameras, video, capture indicators) · `A-012`,
`A-041` (alarm devices, a physical ASR-independent channel) · `SPIKE-008`
criterion 9 on a `foreground_only` node.

### Needs elapsed time

**The 24-hour `A-029` endurance run.** The compressed run passes with identical
protocol and assertions, but it cannot surface a slow leak or an hour-19
resource exhaustion. **Owed before the R4 gate.** This is the single most
significant gap between "passes" and "proven".

---

## 7. Tomorrow, in order

1. **Review and merge PR #5.** 23 commits, CI green.
2. **Answer the two owner decisions** in §6.
3. **Grab a clear plastic sheet** — five minutes closes SPIKE-004.
4. **Decide what to prioritise:** the 24 h endurance run (needs the machine left
   alone for a day), or F6 distributed work (needs the second always-on node).

---

## 8. How to verify any of this yourself

```bash
python tools/ci/checks.py          # 17/17 — includes all six gates
python tools/ci/self_test.py       # 47/47 — every check shown red then green
python tools/reference_lint.py     # clean
python verification/run_f5_acceptance.py   # the decisive gate, C1 included
```

Every claim in this report is produced by one of those commands. Nothing here is
asserted from memory.
