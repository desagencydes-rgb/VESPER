# Overnight report — 2026-08-31

**Gates: 60 checks, 238 self-tests, both lints green.** Tree clean, everything
committed, local bundles in `~/VESPER-backups/`. Nothing pushed.

**Waiting on your ears, and only that:** `~/VESPER-darija-ab/voice.sh` plays the
whole comparison in the order that decides things. I cannot hear audio, so this
is the one thing I could not settle myself.

---

## The night's headline: your credentials work, and four things stopped them

All seventeen chat credentials answer, plus ElevenLabs. Every one is a **distinct**
account — I checked by hashing, because seventeen slots holding one key would
have looked identical in the file and bought no isolation at all.

Getting there turned up four defects, **three of them mine**:

**`read_secrets` matched only lines beginning `export`.** A credential written
`MISTRAL_API_KEY_CHOOSER=...` was skipped in silence — so every key you pasted
was invisible to the runtime and every row naming one was dropped as "no
credential". A credential file gets edited by hand under time pressure; the
parser was the wrong place to be strict about shell syntax.

**The probe had its own copy of that same parser**, with the same defect. Two
readers of one file is one too many; they drifted the moment the file grew. The
probe now calls the one implementation.

**My generated supply rows silently dropped two fields.** The Cloudflare rows
lost `account_env`, whose value substitutes into `{account}` in the endpoint, and
the Claude rows lost `argv`, without which the CLI wire runs with no prompt.
Generating rows from a fixed field list discards anything not on the list.

**And the rung was pointed at a model your tier cannot call.** All seven Mistral
accounts return HTTP 403 on `mistral-large-latest`. It would have failed on its
first real request. `mistral-medium-latest` works; 54 models are available, so
the tier was never the constraint.

## Two recorded findings are now wrong, and I corrected them

**Cloudflare and Ollama are measurable.** `MEMORY.md` and `MEMORY_ARCHITECTURE.md`
both record them as unmeterable and therefore unusable. Both now return real
non-zero counts, and **Cloudflare returns `neurons` directly** — the exact unit
its 10,000/day quota is denominated in, which is better evidence than a token
delta and is precisely the accounting route the corpus said was missing. **The
five accounts I told you to hold are usable.**

I kept the original reasoning rather than deleting it, because it was right:
unmeasurable spend *is* unusable, and the answer was to re-measure, not to relax
the rule.

**Manual context mode was never missing.** The handoff records SR-008 as "manual
mode missing entirely". `ContextBudgetManager.assemble(manual=[...])` has pinned
fragments and refused to drop them since it was written — it is constructed in
exactly one place in the repository, an acceptance runner. Nothing had reached it.

## What is now live

| | |
|---|---|
| **Per-subsystem routing** | Six ladders, 27 of 28 rows measured and routable. Only `nvidia-strong` is out, on a pre-existing HTTP 410. |
| **`INV-PRIV-7`** | Ratified. The redactor's check registers as `CI-084` and stops claiming nothing. |
| **`FAILING` · `battery_critical`** | Both defined and produced. `trg_placement_reevaluate` can fire for the first time. |
| **Presence** | You tell VESPER someone is with you; public content moves off the shared display. Costs one phrase match per turn. |
| **Context commands** | "focus on the flight", "drop the calendar", "never mind" — reaching selection, verified across turns. |
| **Arabizi transliteration** | Latin Darija → Arabic script at the speech boundary only. What you read never changes. |

## The bug that was hiding behind the dead states

Every host sensor I wired on the 30th used subject `current_host`. A predicate's
snapshot resolves `world.current_host.health` by splitting on the **last** dot —
subject `world.current_host`. So the probes ran, the facts landed, the world was
correct, and **no predicate could read a single one of them.** An unreadable
subject and a genuinely quiet trigger look identical from outside.

Found by driving the trigger end to end rather than trusting the facts were
arriving. `CI-082` now cross-checks every registered sensor's subject against
the subjects predicates actually resolve.

## A pattern worth your attention

**Four checks now run and report covering nothing** — the redactor before you
ratified `INV-PRIV-7`, the Arabizi transliterator, the presence flag, and the
context commands. Each guards a real rule that is **absent from the invariant
set**, and registering one against an invariant it does not enforce is the
manufactured claim `ci-registry` exists to refuse.

`INV-PRIV-1` is the sharpest example: *"unknown person in the target space
implies private content is withheld"* is exactly what presence implements, and it
is enforced only by acceptance tests with **no SR naming it**.

That is four rules the system genuinely follows and cannot report following.
Ratifying them is the same one-line act `INV-PRIV-7` took.

## Still yours

1. **The voice comparison** — `~/VESPER-darija-ab/voice.sh`
2. **Four invariants to ratify**, or a decision to leave those gates unregistered
3. **ElevenLabs is on the free tier** — 10,000 characters/month, roughly 125 spoken
   replies. If the Arabizi test passes, the next question is a paid tier.
4. **The remaining scope items** are mine, not yours: self-check, cache tiers,
   multiple agents, the mapping system.

---

## Second half of the night — the five remaining capabilities, then the registry

### Built and wired

| What | Where | Gate |
|---|---|---|
| Cache tiers + `DF-CACHE-ADMIT` | `core/cache.py` | `CI-085`, 8 red-run cases |
| Log receipts for `Claim.support` | `core/evidence.py`, `core/arbiter.py`, `core/blocks.py`, `core/store.py` | `CI-086`, 6 cases |
| The two machine-checkable verifiers | `core/verifiers.py`, `core/verify.py`, runtime `build()` | `CI-087`, 6 cases |
| SR-007 knowledge map | `core/knowledge_map.py` | `CI-088`, 6 cases |

Every one is reached by the running system. That was the explicit bar, because
the pattern this corpus keeps finding is a subsystem that is correct, gated, and
called by nothing.

### Six checks that had been declared since the registry was first written

`CI-004`, `CI-011`, `CI-012`, `CI-013`, `CI-020`, `CI-033`. No new subsystem
code — every one guards something already complete and correct, and every one
was `impl = "PENDING"`, which looks like enforcement in any listing that does
not read the `impl` field.

**52 → 63 of 140 invariants enforced, in one session, without building a
subsystem.** That is the sharpest evidence yet that wiring and gating is where
the ground is lost, not building.

### Findings

**Five times, two guards turned out not to be one.** Each was found by a
self-test case staying green under a mutation that should have broken it, and
each time the fix was to test the guard through the door it actually defends:

1. `retrieve`'s stale-node filter is redundant with `span_for`'s read-time hash
   for *correctness*; its real job is not READING a file already known to have
   moved. Asserted by counting reads.
2. `attenuate`'s L4 clause is unreachable through an issued grant, because
   `issue()` already refuses to create one. What it defends is a `Grant`
   constructed directly. Asserted through that door.
3. The cost policy's `_policy_loaded` branch is redundant with the lookup's
   free-only default on an empty map. What it guarantees is free-only
   *regardless of the map's contents* — a policy that parsed halfway.
4. The rule-count and adversarial-probe refusals coincide on a single-rule
   declaration. What the count adds is the **diagnosis**: it says too few rules,
   where the probe sends the author to inspect a function that is correct.
5. A proposal RETURNED is not a proposal QUEUED, and only the queue survives the
   call.

**Two of my own assertions were vacuous.** The concatenation-collision test
compared summary keys, which hash content to a fixed 64 characters before
joining, so removing the separator left it green — the reachable collision is
`chunk_key`, whose parts are variable-width integers. And CI-020's structural
scan looked for `.invoke(`, which appears nowhere in this codebase.

**One mistake, caught and repaired.** A registry edit sliced from CI-033 to
CI-034 and deleted `CI-007` in between; the file is grouped by topic, not sorted
numerically. Restored verbatim from HEAD and confirmed by a parsed diff of the
whole registry. A later edit dropped CI-020's original note recording the
2026-08-12 reassignment from CI-021 — restored and quoted verbatim. Every
subsequent registry edit used a bounded replacement of the exact entry text.

### Open, and for the owner

Grant consumption keys on `requires_owner_confirmation AND L4/L5` while
`issue()` refuses an L4-delegable grant on the level alone. An L4 grant on a
capability that does not declare owner confirmation is therefore **not spent by
use** — verified empirically. `INV-AUTH-2`'s text mentions only the level.
`CI-013` asserts neither reading, deliberately. A task chip was raised for the
decision.

### Verification at the end of the night

```
70 checks · 295 self-tests · both lints · F0–F6 · both stress runners — all green
61/89 checks implemented, 28 PENDING · 63/140 invariants enforced
```

---

## Third stretch — the PENDING registry, and giving the counts a consumer

After the five source capabilities landed, the highest-value work left was not
building. **34 of 89 registered checks were `impl = "PENDING"`** — declared
enforcement that did not exist, in front of subsystems that were complete and
correct. A PENDING entry looks exactly like enforcement in any listing that does
not read the `impl` field.

### Implemented this stretch

| Check | Guards | Subject |
|---|---|---|
| `CI-004` | `INV-COORD-5` bus consumer idempotency | `core/bus.py` |
| `CI-009` | `INV-OWN-3` lease fencing | `core/store.py` |
| `CI-010` | `INV-TASK-1`, `INV-VERIF-1` task transitions | `core/tasks.py` |
| `CI-011` | `INV-AUTH-5` argument-sensitive levels | `core/capability.py` |
| `CI-012` | `INV-AUTH-3`, `INV-ACT-3` taint propagation | `core/taint.py` |
| `CI-013` | `INV-AUTH-1`, `INV-ACT-4` no ambient authority | `core/authorize.py` |
| `CI-015` | `INV-SELF-1/4`, `INV-IDEA-3`, `INV-TRIG-7` | `core/selfmod.py` |
| `CI-020` | `INV-COST-3/6` gateway choke point | `core/gateway.py` |
| `CI-024` | `INV-TRIG-5` predicate totality | `core/autonomy.py` |
| `CI-033` | `INV-EVID-1` claim support | `core/evidence.py` |
| `CI-035` | `INV-TRUST-1` Z2 bound | `core/enrollment.py` |
| `CI-040` | `INV-OBS-1` telemetry sensitivity | `core/telemetry.py` |
| `CI-045` | `INV-PLACE-1/2` placement not pinned | `core/placement.py` |
| `CI-046b` | `INV-TUNE-1` runtime half | `core/placement.py` |
| `CI-049` | `INV-LOSS-3` tombstones | `core/forgetter.py` |

**52 → 73 of 140 invariants enforced.** Nineteen checks remain PENDING; eight of
those are `kind = "process"` and gate human steps whose infrastructure does not
exist yet.

`CI-024` is the exception worth naming: `INV-TRIG-5` had **no enforcement of any
kind**, so `assert_terminating` was written as part of landing the check. Every
other one gated code that was already there.

`CI-045` had been held on a stated precondition — *"Remains PENDING until the
placement module exists"* — and the placement module exists, with 160k stress
assertions against it. A sweep found no other check held that way.

### The pattern that kept recurring

**Seven times, two guards turned out not to be one.** Each was found by a
self-test case staying green under a mutation that should have broken it, and
each time the fix was to test the guard through the door it actually defends:

| Redundant-looking pair | What the "extra" guard actually does |
|---|---|
| `retrieve`'s stale filter vs `span_for`'s hash | avoids READING a file already known to have moved |
| `attenuate`'s L4 clause vs `issue`'s refusal | defends a `Grant` that never went through `issue` |
| cost policy's `_policy_loaded` vs the lookup default | holds regardless of what the map contains |
| rule count vs adversarial probe | gives the right DIAGNOSIS, not just the right refusal |
| proposal returned vs proposal queued | only the queue survives the call |
| artifact self-append vs `contracts/policy/` prefix | governs an artifact that removed its own directory |
| structural `while` rule vs bounded probe | refuses WITHOUT EXECUTING the predicate |

### Giving the counts a consumer

CLAUDE.md's check and self-test counts have drifted **seven times**. Every
correction was made by a human noticing. So the eighth is not a correction:
`documented-counts-match-commands` reads every figure both documents quote from
a command and compares it to what that command produces.

It earned itself immediately — four stale figures on the first run, then two
more the patterns had not covered: *"41 of 56 CI checks unimplemented"* and
*"18 of 118 invariants enforced"*, both live claims in a table headed **"every
number below is produced by a command"**.

Three designs failed before one held, each caught by the self-test. The
requirement is now derived from the **documents**, not the pattern list: delete
a pattern and the line it covered becomes uncovered. *A guard that can be
removed by removing what it guards is not a guard.*

It is **deliberately unregistered** — there is no ratified invariant for
documentation integrity, and registering it against an invented `INV-PROC-4`
would be the false trace `ci-registry` refuses.

### Two things I broke and repaired

**`core/autonomy.py`** — one of the 209 CRLF files. My patch script read and
wrote text, converting all 494 line endings; then a self-test I stopped with
`pkill` never ran its restore, leaving the file LF-converted *and* missing the
guard I had just added. Restored from HEAD, re-applied through bytes.

**`contracts/policy/tunables.toml`** — a red-run mutation whose code RAN
overwrote it, 8577 bytes to 9. The harness restores the path it mutated and
nothing else. Restored from HEAD and verified; the mutation is now inert.

Both are recorded in memory. A line-ending diff against HEAD is now part of the
end-of-work sweep.

### Waiting on the owner

Two decisions were raised as task chips rather than taken unattended:

1. **The L4 grant single-use trigger.** Consumption keys on
   `requires_owner_confirmation AND L4/L5` while `issue()` refuses an
   L4-delegable grant on the level alone. `INV-AUTH-2`'s text mentions only the
   level, so an L4 grant on a capability without owner confirmation is not spent
   by use — verified empirically. `CI-013` asserts neither reading.
2. **Ratifying invariants for the four unregistered checks** — arabizi,
   presence, context control, documented-counts.
