# Work report — 2026-09-01, 01:40 to 22:10

Written for the owner. Overnight plus the day that followed. Thirty-two commits, all pushed to `feat/macos-host-profile`.
**Tier one of the approved build order is complete**, plus the two defects this
survey found in our own code and two items from its own build list.

Gates as of the last commit: **122/122 checks pass, 516 self-test cases red
under violation and green after restore, both lints pass.** Up from 87 checks
and 407 cases when the night began.

**Four modules remain built-and-unreached, down from thirteen.** Three are
correct as they are — `enrollment`, `fabric` and `placement` all wait on a
second node joining. The fourth is `cache`, below.

---

## Read this part first — what needs you

**1. `cache` is the only module left that waits on a decision.** Its five tiers
save different things and only one of them saves anything you would notice:
SUMMARY, which avoids re-summarising the same content for the same purpose —
model calls, so money and time. FILE_HASH and CHUNK save disk and CPU
(negligible); PROMPT_PREFIX enables a provider discount that was **measured at
1 hit in 14** and is therefore a bonus, never a premise.

The problem is that SUMMARY has no customer: nothing in this system summarises
yet. `Compactor(summariser=...)` is the slot and it is passed `None`, so
`compact()` honestly returns `{"outcome": "no summariser"}`. Wiring the cache
alone buys ~nothing. What makes it worth having is turning on **summarising
compaction**, which is a model-spend decision: how much, on which rung.

The keys for it already exist — `MISTRAL_API_KEY_COMPACTOR`,
`CLOUDFLARE_API_TOKEN_COMPACTOR` and six more dedicated per-subsystem
credentials, provisioned and unused.

**2. Autonomy is armed by a Python LaunchAgent, and it should be VESPER's own
process.** `tools/ops/vesper_arm.py --install` works and you installed it, but
it shows as `python3`. It belongs in the bundle as `VESPER --arm`, which is
Swift and therefore part of the build batch below.

**3. Ten checks — now more — run and are held out of the registry.** Each
asserts a property that is a new invariant, and promotion into a contract is a
separate reviewed act.

**4. One Swift build, one TCC re-grant, five items:** a stable self-signed
signing identity (so grants survive rebuilds), TCC dialogs raised from inside
the app instead of by a command, your `fn+ctrl+opt+cmd+return` stop, the
already-committed `scheduleWakeRetry`, and `VESPER --arm`.

## What the day added

Twelve subsystems that were **built, gated, and reached by nothing** are now
reached. The reachability gate found them, and it found three more once it was
widened from the 50 modules some check happened to name to all 76.

| | |
|---|---|
| `context.py` | L1 spends a **token** budget, not a fact count |
| `compactor.py` | the consolidation loop: L2 drifting from L3 is detected and repaired |
| `arbiter.py` | memory contradicting itself is a question, never a silent pick |
| `interlock.py` | **the stop** — a dead-man's switch, armed by a minter VESPER cannot be |
| `reconcile.py` | an external action is recorded **before** it happens |
| `knowledge_map.py` | 8,561 nodes over declared roots, kept true by hash |
| `selfmod.py` | a governed path is refused even under an L5 grant |
| `floor.py` | the owner can interrupt work in flight; "take your time" is met with silence |
| `host.py` | the platform's own verdict, translated — it says this machine is under pressure |
| `baseline.py` | every turn recorded with its outcome; a choice is not a failure |

Plus Keychain credentials (30 migrated), a second authorization axis, and a
repair storm fixed that was two thirds of a 1.6 GB log.

## The overnight items, for reference

**1. The emergency stop is still not wired, and that is a decision I would not
make for you.** `core/interlock.py` is a dead-man's switch: autonomy runs only
while a *fresh enable token* is present, and the token is minted OUTSIDE the
runtime by a key the runtime cannot reach. That design is right, and it means
wiring it requires choosing **who presents tokens and from where**. Doing it
the easy way -- letting the runtime mint its own -- builds precisely the
kill-signal version A-031.2 names as the control that must fail. Doing it the
honest way is your safety architecture, at 3am, unattended. So it is recorded
and untouched.

Until that is decided, **VESPER can act and there is no stop to press.** It is
the first thing I would do with you awake.

**2. Ten checks run and are held out of the registry.** CI-094 through CI-103
are implemented, red-run and passing in every `checks.py all`, and deliberately
not registered: each asserts a property that is a *new invariant*, and
promotion into a contract is a separate reviewed act. This follows the
precedent the arabizi, presence and context-control checks set. They need your
ratification to count toward the enforcement figure.

**3. Your keys are still plaintext, by choice.** The Keychain path is built and
verified; I did not migrate them, because writing to your login keychain is a
change to your machine. One command when you want it:

```bash
python3.13 tools/ops/vesper_keychain.py --status
```

then `--migrate`. It never prints a value, and it does not delete the file.

**4. The next build still has to be followed by re-granting TCC.** Unchanged
from the last handoff. `scheduleWakeRetry` remains committed and unbuilt; I did
not run `build.sh` all night, because re-signing would have revoked speech and
Accessibility with you asleep.

---

## The one behaviour change you will notice

**After VESPER runs a command, the next step above L1 asks you.**

`INV-ACT-3` says command output is `retrieved_external` and "may never raise
the authority of any action". The agentic loop landed last night, and the taint
ceiling landed with it, so once the loop has observed something the ceiling is
L1 for the rest of that turn. Measured: *echo, then write to a file* -- step one
acts, step two is refused for `context_ceiling`, `security.injection_suspected`
is published, and the file is not written.

**Reading a file is treated differently, and that is the deliberate loosening.**
The invariant names screen content, OCR, UI labels and *command output* -- not
local file contents, for which `retrieved_local` (L3) is the class the corpus
already provides. So `read -> edit` works without asking; `run -> write` does
not.

Treating everything as external would mean that having looked at a file, VESPER
must ask before editing it, which is most of the work it exists to do. Treating
command output as local would contradict an invariant by name. **If the loop
feels too cautious, this is the line to argue with** -- it is one table,
`OBSERVATION_TRUST` in `core/capabilities.py`.

---

## What landed

| | |
|---|---|
| **The taint ceiling reaches the act path** | The worst thing found. See below. |
| **A reachability gate** | Closes the class rather than the instance. |
| **The agentic loop** | VESPER can take a second step. |
| **The rejection circuit breaker** | Three consecutive refusals end the turn. |
| **Seatbelt containment** | Every `shell.run` under `sandbox-exec`. |
| **Read-before-write** | A blind overwrite is L4; a stale hash is refused at any level. |
| **`fs.edit`** | Surgical, unique-match-or-fail. |
| **Shadow-git checkpoint and undo** | The pre-state of every file-touching action. |
| **A tier no grant opens** | Three acts an L5 grant does not authorise. |
| **The outer loop has hands** | Two real triggers; `dispatch` joins a fired trigger to the actor. |
| **Keychain credentials** | Built, verified, not migrated. |
| **A second authorization axis** | How strongly was this asked, with `unknown` first-class. |
| **Two checks that were not evidence** | Both fixed. |

### The worst thing found, and it was ours

`core/taint.py` -- the anti-prompt-injection ceiling, and on reading the
strongest subsystem in this repository -- **had zero production callers**.
`context_ceiling` defaulted to `"L5"` in both `authorize()` and `execute()` and
no caller passed one, so `_min_level(grant, declared, ceiling)` could never be
lowered by the trust class of anything in context. `ContextCeiling` was
instantiated exactly twice in the whole corpus: once by its own check, once by
the F2 acceptance runner. **Both supply their own subject.**

Every gate was green, because a check that constructs the thing it checks is
testing a library rather than a system.

That was the **third** instance of one shape -- memory reaching the answer path
and not the act path, `fs.write` verified through a door that returns early, and
now taint -- so the fix is not taint-specific. `CI-094` asserts that a `core/`
module named as a check subject has a production call site outside `tools/` and
`verification/`. **Ten do not.** Each is now declared with a reason saying
whether it is not-yet-reachable by design (`enrollment`, `placement` -- no
second node exists) or **OWED**. The two worst OWED entries are
`core/interlock.py` and `core/selfmod.py`.

### Two checks were passing under their own deliberate violation

The last handoff said "405/405". Running the full suite found two cases
reporting `exit0` under mutation. Both were the shape `CLAUDE.md` names: a test
for a **name** rather than a **behaviour**.

- **The chaining rule in `shell_level` was defended by nothing.** Five composed
  commands were probed and each is caught by a *different* rule -- four by the
  destructive-marker test, and `echo hi > /etc/hosts` by the path rule. The
  whole chaining branch could be deleted and the check stayed green. With it
  gone, six ordinary redirecting commands resolve to **L1**.
- **The wake-word retry was asserted by its name.** Two permission guards call
  `scheduleWakeRetry`, so deleting one left the other and the speech branch
  stopped retrying while the check passed.

### The axis the ladder did not have

Every level rule here answers *how dangerous is this*. Codex's guardian answers
that **and** *how strongly did the user actually authorize it*, with `Unknown`
first-class — and the two come apart in the case this design exists for. A
**poisoned** proposer emits something dangerous and the danger axis catches it.
A **steered** proposer emits something entirely reasonable that you never asked
for, which is unremarkable on the danger axis and visible only here.

Three strengths, and the boundaries are the ones this system can actually tell
apart: `owner_explicit` (you said it, this turn, in words), `owner_task` (a
later step of an errand you asked for — you authorised the errand, not each
move inside it), and `unknown` (autonomous; nobody asked). It is independent of
taint on purpose: taint is the provenance of the **content**, this is the
provenance of the **request**, and each binds alone.

Autonomous work caps at L2 — the standing grant it already ran under — so the
outer loop still has hands. The check asserts that specifically, because an
axis that quietly took it away would have undone the previous night's work two
commits later.

### A claim from the sweep, withdrawn

The second sweep proposed building an outbound secret sanitizer, saying "our
redactor is built for personal data". **That was written from the name and not
from the file.** `core/redact.py` opens with *"Credential detection and
redaction -- deterministic, and never a model"*, and measured against every
shape Codex's 87 lines catch it caught all of them, plus GitHub tokens,
private-key blocks and -- through Shannon entropy -- formats nobody has invented
yet, with no false positives on ordinary prose.

Ours is the better instrument. Measuring before building is the only reason a
second, worse copy did not get written.

---

## How the work was done

Every item: implemented, **driven end to end against the real world** rather
than a description of it, given a check, and that check watched go red under a
deliberate violation and green after restore. Several times the driving found
what the reading had not:

- `fs.edit` matched loosely and wrote the replacement flush left, so
  `        return 1` came back as `return 1` and the enclosing function lost its
  body. Fixing that with one indentation delta then flattened multi-line
  matches. Deltas are per line now, and the check **parses** the result rather
  than comparing bytes.
- The containment check's carve-out probe pointed at the filesystem root, where
  an unsandboxed write fails for want of root -- a permissions error wearing
  containment's clothes. And its network assertion required `curl` to exit 0,
  but under an allow-network profile curl returns a real status and still exits
  non-zero on a truncated read, so a request that plainly got through was
  recorded as denied. **Both cases passed under their own violation until the
  controls were fixed.**
- `keychain_secret` bound its service as a default argument, which freezes the
  module constant at definition time. It looks identical to the correct version
  and silently ignores the constant it appears to read.

Four self-test cases were withdrawn rather than shipped, after measurement
showed the property was defended structurally and the mutation could not
produce the defect. Saying that plainly is better than shipping cases that look
like coverage.

**And the full run at the end found four more that had stopped being evidence
during the night's own work** — which is the argument for running the whole
suite before calling a night finished, rather than a per-check run after each
change. Three were anchors I had moved myself. The fourth is an interaction
between two things built hours apart: `Executor.execute` grew a **second**
`NotAuthorized` — the refusal when a file-touching capability has no checkpoint
store — sitting after the authorization refusal. Deleting the authorization
raise let control fall through to the checkpoint raise, so the probe still saw
`NotAuthorized`, the implementation still had not run, and
`no-ambient-authority` reported green while ambient authority was no longer
being refused by `DF-AUTHORIZE` at all.

Two refusals of the same exception type are indistinguishable to a bare
`except`. That is the third time in one session the same lesson arrived: **a
check that asserts a refusal without asserting *which* refusal is satisfied by
any refusal at all.**

---

## State

- Working tree clean. Everything pushed. Backup branch
  `backup/pre-overnight-2026-09-01` at `831a177`.
- `build.sh` was **not** run. TCC grants intact.
- Machine on AC the whole time, no thermal warning recorded at any point,
  `caffeinate -i` held so the screen could still sleep.
- The artifact carries the full survey plus the night's work, additively:
  https://claude.ai/code/artifact/6a07dc94-5ed9-4b45-8940-ba800ad4f775
