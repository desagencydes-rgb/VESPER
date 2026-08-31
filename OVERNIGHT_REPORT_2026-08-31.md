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
