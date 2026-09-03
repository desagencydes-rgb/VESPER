# The 23 checks that run and are not ratified

Written 2026-09-03. `python3.13 tools/ci/checks.py ci-registry` prints this
count on every run; this file is what it would take to act on it.

## Why they are held out

A check earns a registry entry by naming the invariant it enforces. These 23
each assert a property that **no invariant in `INVARIANTS.toml` states**, so
ratifying one means WRITING that invariant — a durable normative claim about
VESPER. `tools/ci/checks.py` says so where it reports the number:

> ratifying one means writing the invariant it enforces, which is the owner's
> act rather than a session's. Turning it into a failure would push a session
> toward registering things quickly instead of correctly.

So this file proposes the text and stops. Each entry is one decision.

**They are not unguarded.** All 23 run in every `checks.py all` sweep and all
have red-then-green cases. What they lack is a NAME, which is why they count
toward no coverage figure — 89/144 is the honest number precisely because it
excludes them.

## The 15 that were ratified instead

On 2026-09-03, 15 checks whose invariant ALREADY existed were registered
(CI-104…CI-118). Coverage moved **88 → 89**, not 88 → 103: fourteen of them
name invariants other checks already defend. Only `wake-word-listens-locally-
and-starts-once` reached an undefended one (`INV-PRIV-3`). Expect the same
shape here — most of these would add a name, not a defence.

---

## Storage and the log

**`a-rotated-log-keeps-one-sequence-and-loses-nothing`**
Asserts: a segmented log keeps one monotonic sequence across a rotation and
loses no record.
*Proposed:* `INV-LOG-n` — Rotation is not a schema change: sequence numbers
continue across segments and no record is dropped, rewritten or reordered by
it. Sits beside `INV-SCHEMA-2` (the log is never rewritten).

**`a-compressed-archive-is-still-a-readable-log`**
Asserts: an archived segment is read a record at a time while compressed, never
decompressed-then-read.
*Proposed:* `INV-LOG-n` — Compression is a storage decision, never an
availability one: an archived segment answers reads without being unpacked.
This is the owner's stated requirement in their own words.

**`memory-repairs-its-own-drift`**
Asserts: when L2 stops being what L3 projects, something notices and repairs it.
*Proposed:* `INV-MEM-n` — L2 is a projection of L3 and drift between them is
detected and repaired, never tolerated. Distinct from `INV-EVID-1`, which is
about support for a claim, not about the projection staying true.

**`memory-stores-facts-not-only-transcript`**
Asserts: memory records what is KNOWN and not only what was SAID.
*Proposed:* `INV-MEM-n` — A turn is not a fact. What the system knows is
extracted and stored as facts; the transcript alone does not constitute memory.

**`l1-spends-a-token-budget`**
Asserts: block B fits a budget in tokens, not a count of facts.
*Proposed:* `INV-MEM-n` — Context is spent in tokens. A block bounded by an
item count is unbounded in the unit the provider charges.

**`a-read-window-moves-and-proves-only-what-it-saw`**
Asserts: a paged read is not a whole-file read, and only a complete read yields
the token that stands for having read it.
*Proposed:* `INV-AUTH-n` — Evidence of reading covers exactly the bytes read.
Closely related to `INV-AUTH-5` (write never destroys what was not read) and
arguably an extension of it rather than a new invariant — worth deciding which.

## Authority and containment

**`authorization-strength-is-its-own-axis`**
Asserts: how dangerous an act is and how strongly it was authorised are
separate questions.
*Proposed:* `INV-AUTH-n` — Danger and authorisation strength are independent
axes; neither substitutes for the other. This one is load-bearing doctrine and
probably the most valuable in this file.

**`a-level-rule-means-what-it-says-and-names-what-it-refuses`**
Asserts: a level rule's declaration is checked against its function AND against
a counter-example it must refuse.
*Proposed:* `INV-AUTH-n` — A rule that cannot state what it refuses has not
stated what it permits.

**`shell-runs-contained`**
Asserts: `shell.run` is contained by the kernel, not merely classified by a
string match on the command.
*Proposed:* `INV-ACT-n` — Containment is enforced by the platform, never by
recognising a command. A string classifier is a heuristic; a sandbox is a
boundary.

**`a-shell-session-carries-context-not-a-shell`**
Asserts: `cd`, environment and a venv survive between commands without a live
shell process.
*Proposed:* `INV-ACT-n` — Session continuity is carried as state, not as a
long-lived process. (Also the reason 13 environment names are refused.)

**`every-change-is-undoable`**
Asserts: nothing that changes a file runs without its pre-state recorded first.
*Proposed:* `INV-ACT-n` — The pre-state is recorded before the change, not
after. Ordering is the whole content, as with `INV-ACT-6`.

**`edit-names-one-place`**
Asserts: a surgical edit changes one place or nothing, and never reindents.
*Proposed:* `INV-ACT-n` — An edit that matches more than one place has not
identified its target.

**`autonomy-can-act-and-still-cannot-decide`**
Asserts: the outer loop has capabilities and still no model in the decision
path.
*Proposed:* `INV-AUTO-n` — Autonomy may act; it may not decide. No model output
reaches the authorisation decision. Overlaps `INV-AUTH-6` — check whether that
already says it before adding a second.

**`credentials-can-leave-the-plaintext-file`**
Asserts: a Keychain credential is used and the plaintext file remains a
fallback.
*Proposed:* `INV-PRIV-n` — A credential store is added without becoming a
single point of failure.

## Providers and the ladder

**`a-withdrawn-model-descends-instead-of-being-retried`**
Asserts: a withdrawn model (410/405/501) is not retried; a busy one (429/5xx)
still is.
*Proposed:* `INV-COST-n` — A terminal refusal descends the ladder; a transient
one is retried. Retrying a terminal refusal spends a call confirming what the
first already settled. **Strongest candidate in this file** — it was written
against a measured defect (`meta/llama-3.3-70b-instruct`, end of life
2026-08-26) and the classification is now load-bearing in three places.

**`a-decline-is-not-an-attempt`**
Asserts: a refusal that cannot change is not re-taken on every pass.
*Proposed:* `INV-AUTO-n` — A decision that cannot change is not re-decided.

## Interaction

**`floor-held-and-offered-to`**
Asserts: four mid-hold outcomes that differ in behaviour, not only in name.
*Proposed:* `INV-FLOOR-n` — A hold has outcomes that differ in what happens,
not in what they are called.

**`speech-in-declares-language-and-measures-confidence`**
Asserts: speech input declares its language and carries a measured confidence.
*Proposed:* `INV-SPEECH-n` — A transcript without its language and its
instrument's confidence is not evidence. This is `INV-HW-2`'s measured-not-
declared rule applied to recognition, and may belong there rather than as a new
invariant.

**`every-turn-recorded-with-its-outcome`**
Asserts: what VESPER answered is written down, and choosing not to act is an
outcome rather than a failure.
*Proposed:* `INV-OBS-n` — Every turn is recorded with its outcome, and a
deliberate non-action is an outcome.

## The corpus itself

**`the-runtime-resolves-every-name-it-uses`**
Asserts: no function in the runtime reads a name that does not exist.
*Proposed:* `INV-PROC-n` — A name the runtime cannot resolve is a defect the
sweep finds, not one a user finds. This caught a real `NameError` in `pump()`
that a broad exception handler had been swallowing — autonomy never ticked.

**`gated-subsystems-are-reachable`**
Asserts: a subsystem only its own check can reach is not enforced by it.
*Proposed:* `INV-PROC-n` — A check whose only caller is itself is not
enforcement. Generalises the vacuity rule `ci-registry` already applies.

**`map-built-and-kept-true`**
Asserts: the corpus is mapped in submaps and a moved file does not stay mapped.
*Proposed:* `INV-PROC-n` — A map that outlives the thing it maps is worse than
no map.

**`host-pressure-read-through-the-adapter`**
Asserts: platform signals reach VESPER translated, never raw.
*Proposed:* `INV-HW-n` — A platform reading is translated at the adapter, never
interpreted upstream. `macOS memorystatus_level` is a band, not a size, and
reading it as a size is the defect this prevents.

---

## Recommendation

Three are worth writing on their own merits, because each states doctrine the
corpus already relies on and would lose if it were forgotten:

1. `a-withdrawn-model-descends-instead-of-being-retried` — terminal descends,
   transient retries.
2. `authorization-strength-is-its-own-axis` — danger and authorisation are
   independent.
3. `shell-runs-contained` — containment is a boundary, not a classifier.

Four look like EXTENSIONS of existing invariants rather than new ones, and
folding them in would be better than adding: `a-read-window-moves…` into
`INV-AUTH-5`, `speech-in-declares…` into `INV-HW-2`, `autonomy-can-act…` into
`INV-AUTH-6`, `gated-subsystems-are-reachable` into the vacuity rule.

The rest are real properties with no home yet. None is urgent: they run and
they are red-tested. What they are missing is a name.
