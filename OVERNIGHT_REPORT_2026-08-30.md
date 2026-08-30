# Overnight report — 2026-08-30

**The memory build order is complete. Steps 1 through 7, all gated, all wired
into the running process.** What follows is what landed, what was found, and
what is waiting on the owner.

**Read this first if you read nothing else:**

1. This machine was on **battery, 53%, discharging, no charger attached** at
   01:5x while running unattended with idle sleep disabled.
   `core/host_probes.py` found it — the first real reading the new sensor layer
   took was about its own host. Plug it in before the next long run.
2. **Mic and speech consent need granting again**, and earlier in this report I
   said otherwise. TCC keys an ad-hoc-signed app's grants to its cdhash and
   every rebuild resets them. One command, once, and it holds until the next
   build:
   ```
   open -n ~/Projects/VESPER/app/VESPER.app --args --speech-consent
   ```

---

## Where the build stands

| # | Build-order item | State | Gate |
|---|---|---|---|
| 1 | L2 graph store | done, wired | `CI-074` |
| 2 | Updater + miss recorder | done, wired | `CI-076` |
| 3 | Redactor | done, wired at the choke point | runs, **unregistered** — see below |
| 4 | Block A + Block B rendering | done, wired | `CI-077` |
| 5 | Chooser | done, wired | `CI-081` |
| 6 | Compactor · arbiter · forgetter | done | `CI-080` · `CI-078` · `CI-079` |
| 7 | Sensors | done, wired | `CI-082` |

**Gates: 57 checks, 223 self-tests, both lints green.** Every check landed with
an executed red run in `self_test.py`; nothing was declared.

Memory runs in the live app. `~/Library/Application Support/VESPER/l2.db` was
created by the supervised runtime, carries the full schema, and no
`memory.unavailable` event was published.

## Voice, and autonomy

**Speech-in is built.** `app/island-macos/Listener.swift`, `--listen --locale
en-US`. `requiresOnDeviceRecognition = true` is set explicitly — the API default
is false, transcription is equally good either way, and omitting it silently
sends every word spoken in the room to Apple. It **refuses** a locale with no
on-device support rather than degrading. Spoken input routes through
`Intake.spoken()`, so a 61%-confident "delete the archive" is reflected back
rather than executed.

**`core/floor.py`** closes the gap between the chooser's 600 ms announcement and
`core/barge_in.py`, which had 242 phrases, a gate, and no caller. `INV-HOLD-1`
has four clauses and CI-072 could only reach one — "discarded", "answered
without cancelling" and "queued and delivered afterwards" are behaviours a
classifier cannot perform.

**VESPER made its first autonomous decision.** A probe stops answering → the
reading lapses → the world reads `UNKNOWN` → a sweep sees it → the trigger
fires, with a snapshot that replays TRUE and `model_involved_in_decision:
False`. One trigger of eight is wired; the other seven read terms nothing
populates yet, and registering them would produce triggers that evaluate UNKNOWN
forever and look identical to working ones.

`tick()` **decides and publishes; it does not act.** Actuation is a separate
concern and the interlock is what will stand in front of it.

## Invariants that gained a CI enforcer tonight

| Invariant | Was enforced by | Now also |
|---|---|---|
| `INV-MEM-1` | `A-003` only | `CI-078` |
| `INV-EVID-3` | `A-003` only | `CI-082` |
| `INV-DIFF-1` | `CI-069` | `CI-081` |
| `INV-PRIV-5` | `A-037`, `A-039` | `CI-080` |
| `INV-LOSS-3` | `CI-049`, `A-050` | `CI-079` |
| `INV-HOLD-1` | `CI-072` (one clause of four) | `CI-083` |

## Findings — the useful half

**The ~18 ms in `HANDOFF_MEMORY_BUILD.md` is the wrong row.** It is the
full-text stage in isolation. The actual block-B query measures **31.55 / 50.36 /
87.35 ms at 100k facts** — over the 25 ms budget at every depth, including depth
1. L2 is specified to hold 10⁴–10⁵, so the design is comfortable at the bottom
of its own range and breaks at the top. **Consequence not previously written
down: the compactor is load-bearing for latency, not only for context size.**
Raw output now in `docs/spikes/data/l2_query_probe.txt` — it was the only probe
storing none.

**The measuring instrument's own query carried two defects into the design.**
`reach` unions on `(id, d)`, so an entity reached at two depths returns each of
its facts twice — block B holds 3–5 facts and would have spent slots on repeats.
And `WHERE f.privacy = 'private'` would have made a `personal` fact permanently
unreachable. Neither was visible to the probe: `stage_full` counted rows, and a
duplicate count reads as a hit.

**Erase does not destroy content, and the architecture currently forbids it
doing so.** `UPDATE` and `DELETE` on the `log` store are refused at the storage
layer (ADR-002 D9), so an erased value stays in L3. Two consequences: a
reprojection resurrects it unless it reads the tombstones (it now does, gated by
`CI-080`), and **a credential that reached L2 must be rotated, not merely
erased.** A real erasure needs an owner-authorised path through the append-only
guard.

**Three ways of testing that erasure turned out to be untestable.** A rowid
lookup on `fact_fts` is vacuous (external-content tables resolve through the
base table). A raw `MATCH` and a scan of the shadow blocks are both
non-deterministic — identical erasures disagreed depending only on what else had
been written first, because FTS5 segment merging decides when a term leaves
index storage. The gate asserts `select()`, the only deterministic path; the
residue limit is recorded in `core/forgetter.py` rather than gated.

**TCC CONSENT DOES NOT SURVIVE A REBUILD, AND THIS CORRECTS SOMETHING I
REPORTED EARLIER TONIGHT.** I obtained microphone and speech-recognition consent
at ~01:0x and reported voice as unblocked. It is not. TCC keys an
**ad-hoc-signed** app's grants to its **cdhash**, `build.sh` re-signs on every
build, and I rebuilt five more times after that (memory wiring, chooser,
sensors, listener ×2). Measured: granted at cdhash `6bd67687...`; at cdhash
`59b04339...` the same app reads `notDetermined` and `NOT authorized`. **The
consent is gone and needs granting again** — `open -n .../VESPER.app --args
--speech-consent`, and it will hold until the next build.

`build.sh`'s header already argues for a Developer ID certificate on
launch-item grounds. This is a second, sharper reason: without a stable
identity, **every voice change costs the owner two dialogs**. Use
`--speech-status` to read the grants without requesting anything.

**The TCC responsible-process trap**, walked into immediately after writing the
warning about it. Running the bundle's executable from a shell prints the
correct bundle identifier and TCC still attributes to the shell: the microphone
returned "granted" with no dialog (inherited from Terminal) and the speech
request died with SIGABRT complaining about a usage string that was present.
**Both readings failed in the direction that looks like success.** `open -n` is
the fix; now in `CLAUDE.md`.

**Two of my own checks were wrong and the harness said so.** `CI-077` matched
the literal `"facts under"`, which renders `"1 fact under"` for a single-fact
node — a check whose result depended on how much the owner happened to say about
one topic. And its middle-is-empty assertion tested that block B led and the
question trailed, both of which stay true while arbitrary content sits between
them. A negative control that passes is a defect, not a relief.

**`FAILING` is a dead clause in `trg_placement_reevaluate`.** Its predicate
reads `world.current_host.health in { DEGRADED, FAILING }`. `DEGRADED` is an
`SM-DEVICE` state; **`FAILING` appears in exactly one place in the whole corpus
— that line.** No state machine defines it, no code produces it, nothing else
mentions it. The clause is unreachable by construction, which does not break the
trigger (the `OR` simply never fires on that branch) but makes it narrower than
it reads: anyone reading the predicate would believe VESPER reacts to a failing
host. Either `SM-DEVICE` gains the state or the clause goes — both are changes
to governed surfaces, so neither is mine.

**And my own probe made the same class of mistake in the other direction.**
`host_health()` shipped returning `nominal`/`constrained`, invented in the probe,
while the predicate reads `DEGRADED`. The trigger could never have fired however
degraded the host got, and nothing would have reported it because both halves
were internally consistent — the same defect as `l2_query_probe.py` inventing
`private`/`shareable` for a column `core/privacy.py` already owned. Fixed to
`SM-DEVICE`'s vocabulary, and `CI-082` now asserts the returned value is an
`SM-DEVICE` state so the class of error is caught rather than remembered.

**An event on every pump pass filled 86% of the log before anything failed.**
`sensors.poll()` published whether or not a probe ran: 9,152 of 10,609 records
in twenty minutes, ~8/second, into a store that is append-only and cannot be
cleaned. The cost is not disk — the log is what every miss record and every
replayed snapshot reads back, and 86% noise makes it a log nobody will read.
Fixed and gated. **The ~9k junk records are permanent**, for the same reason the
erased credential is: `DELETE` on the `log` store is refused at the storage
layer. They are harmless and they are there.

**I used neither `taint.py` nor `projection.py`, which the handoff named
specifically**, and checking that at the end found the worst defect of the
night. Every trust class my code wrote was invented — `owner_utterance`,
`extractor_reading`, `compaction`, `calendar` — because `remember()` validated
privacy against its contract and checked trust only for non-emptiness.
`_weakest()` maps an unknown class to rank 0, so **the owner's own words ranked
below `retrieved_external`**, and nothing in memory ever carried the one class
`INV-AUTH-6` is about. The compactor also set `trust_class="compaction"`,
destroying the inputs' classes at the exact moment content merges. Both fixed:
memory refuses anything outside `taint`'s vocabulary, and compaction inherits
through `taint.summarise()` — verified, `owner` + `retrieved_external` now
yields `retrieved_external`. `SensorRegistry.read()` returns a `projection.Reading`,
which structurally cannot hold a value without provenance.

**That was the third invented vocabulary in one night** — after the L2 probe's
`private`/`shareable` and `host_health`'s `nominal`/`constrained`. Each looked
reasonable read on its own, and none of them failed anything.

## Three more modules wired after the first wrap-up

**`devices`** — this node had never described itself, so `INV-TRUST-2` (no
continuity-critical capability on a foreground-only node) had nothing to check.
With one node that question is never asked, which is exactly when the answer
stops being checked. Registered from **measurement**: audio inputs and outputs
counted from the system inventory rather than assumed from the form factor,
`sustained_tokens_per_sec` recorded as **unmeasured** so `capability()` returns
None for it, and `key_storage_class = os_keychain` **not** `hardware_backed` —
the two differ by a trust zone, a keychain existing evidences the first and
nothing has shown a key in a secure element. Raising it is your promotion to
make.

**`repair` + the grading step between it and triage.** Three real provider
failures were sitting in the queue ungraded, and `RepairAgent` declines an
ungraded item on purpose. `grade_all()` was called by **nothing** — its
docstring says "called when a rung reports healthy" and no rung ever reported.
So the chain was collect → gap → decline, and the decline looked like the
repairer working. Now: `claude-sub/server_error` grades `NO_FIX_NEEDED`,
`groq-strong/server_error` grades `CRITICAL_DEFERRED`, `groq-strong/budget_too_large`
grades `CAN_WAIT`, and all three are declined **because none is CRITICAL_NOW** —
a stated conclusion instead of an unexamined queue.

## Waiting on the owner

1. **The scoping decision, and it is the big one.** The source requirement set
   does not fit in fourteen days on top of memory. Cut explicitly, extend, or
   defer — but cutting by silence is the one option the handoff forbids.
2. **`INV-PRIV-7`, proposed.** No invariant in the corpus says a credential may
   not reach a provider; the handwritten source never mentions credentials at
   all. The redactor's check therefore RUNS and is deliberately **not**
   registered in `CHECKS.toml`, because registering it means declaring an
   invariant it enforces and inventing one is the manufactured claim
   `ci-registry` exists to refuse. Ratify it and the check registers.
3. **Darija voice quality** — needs your ears, and it is **rendered and waiting**:
   run `~/VESPER-darija-ab/play.sh`. Four voices (`Majed` ar_001 MSA, `Thomas`
   fr_FR, `Amelie` fr_CA, `Samantha` en_US as the floor) across four lines,
   grouped by line so you hear the same sentence four ways. All 16 files
   verified as real audio with `afinfo`, not with an exit code. The `recall`
   line matters most — it is VESPER reading a memory back to you, which is what
   it will say most often once the corpus fills.
4. **STT route.** Recommended and unconfirmed: Groq for Darija, Apple on-device
   for `en-US`. `ar-MA` is not available on-device here, so Apple's own path
   egresses outside `ModelGateway` and outside the redactor. **The English half
   is built**: `app/island-macos/Listener.swift`, `--listen --locale en-US`,
   with `requiresOnDeviceRecognition = true` set explicitly — the API default is
   false, transcription is equally good either way, and omitting it silently
   sends every word spoken in the room to Apple. It **refuses** a locale with no
   on-device support rather than degrading to servers, because that would be a
   change in where your voice goes decided by a library at runtime with no
   event. Spoken input now routes through `Intake.spoken()` — which has existed
   since the intake layer was written and was called by nothing — so a
   61%-confident "delete the archive" is reflected back rather than executed.
5. **A log-backed span type.** `Claim.support` wants a `SourceSpan` — a byte
   range in a file with a `verify()` that re-reads it. An L2 fact's provenance
   is a log sequence. They do not compose, so memory-derived claims carry no
   support and `ClaimChecker` will refuse them under a gated policy class.
   Arbitration is unaffected.
6. **Provider accounts** — six, if each subsystem gets its own.
7. **Ambient recording of other people.** Half-settled: "speech from an
   unidentified person is never stored as the owner's memory" is decided, and
   failure mode #8 says "nothing implements either".

## What is deliberately not claimed

Every memory-quality property here rests on design argument, not measurement.
The corpus that would settle S2 and S4 started accumulating tonight — the
updater captures and the miss recorder pairs what VESPER did with what memory
held — and it accumulates at the speed the owner talks to VESPER.

Nothing was pushed. Local `git bundle` backups are in `~/VESPER-backups/`.
