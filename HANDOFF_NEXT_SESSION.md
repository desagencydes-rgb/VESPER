# Handoff — pick up here

Rewritten 2026-09-01 22:10, at the end of the overnight session that completed
tier one of the build order. Read this, then
`docs/WORK_REPORT_2026-09-01_OVERNIGHT.md`, then `CLAUDE.md`.

## State

- **127 checks pass. 549/549 self-test cases** red under violation, green after
  restore. Both lints, F0–F6 acceptance, placement and fabric stress all pass.
- Working tree clean, everything pushed to `feat/macos-host-profile`.
- Backup branch `backup/pre-overnight-2026-09-01` at `831a177` — the state
  before the overnight run.
- `build.sh` has **not** been run since the last TCC grant. Speech and
  Accessibility are intact. `scheduleWakeRetry` is still committed and unbuilt;
  **the next build must be followed by re-granting** —
  `[[tcc-grants-die-on-every-rebuild]]`.

## What needs the owner, in order

1. **`cache` waits on a model-spend decision, not on work.** Its only valuable
   tier is SUMMARY and nothing in this system summarises yet:
   `Compactor(summariser=...)` is passed `None`. The dedicated keys already
   exist (`MISTRAL_API_KEY_COMPACTOR` and seven more). Turning on summarising
   compaction is the decision.
2. **Ratify CI-094 … CI-103.** Ten checks run in every pass and are held out of
   the registry because each asserts a new invariant, and promotion into a
   contract is a separate reviewed act. Precedent: arabizi, presence,
   context-control.
3. **`tools/ops/vesper_keychain.py --migrate`** whenever they want credentials
   out of `secrets.env`. Built and verified; not run, because writing to their
   login keychain is a change to their machine.
4. **The event log wants a retention policy.** 1.6 GB, 1.9 M records, nothing
   prunes it. The refusal storm that was two thirds of the growth is fixed, but
   `autonomy.heartbeat` and `autonomy.noop` are one record per trigger per tick
   forever, and two more triggers landed last night.
5. **Decide whether the loop is too cautious.** After a `shell.run`, the next
   step above L1 asks. One table, `OBSERVATION_TRUST` in
   `core/capabilities.py`. The reasoning is in the report.

## The stop exists now

`core/interlock.py` is wired and consulted before every autonomous action. It
is a dead-man's switch: autonomy runs only while a fresh token is present, so
a crashed minter, an unplugged machine or a wedged control plane all stop it.
`tools/ops/vesper_arm.py --install` is the minter and the owner has installed
it. **It runs as `python3` and belongs in the bundle as `VESPER --arm`** — see
the Swift batch.

What is enforced, stated honestly: `SafetyInterlock` has no mint method at all,
the token directory is in the prohibited tier so `fs.write` refuses it under an
L5 grant, and replay is refused by token id. On one machine under one uid the
OS does not enforce "the key is unreachable from the runtime", and claiming it
would be dishonest.

## What is built and NOT yet joined to anything

`CI-094` is the gate for this class, and it prints the current list on every
run. Ten `core/` modules are the subject of a check and imported by no
production module. Two are not-yet-reachable by design (`enrollment`,
`placement` — no second node exists). **Eight are OWED**, and the two that
matter most are `interlock.py` (above) and `selfmod.py`, the self-modification
boundary: it exists, `CI-015` drives it against the real repository, and
nothing in the runtime consults it before a write.

That gate is the most useful thing to work from. Everything on it is a
subsystem someone already built correctly.

## Rules that will bite you if you skip them

- `python3.13`, never `python3` — the system one is 3.9 and every gate dies on
  `tomllib` **while still exiting 0**.
- **Never let `tools/ci/self_test.py` be killed.** It mutates, checks, restores.
  It takes ~14 minutes; run it with `nohup … &` and poll. **`pgrep -f
  self_test.py` matches your own waiter shell** — check for the python process
  specifically, or you will wait forever on a run that finished.
- **Do not edit repo files while it runs.** The restore writes back pre-edit
  bytes and silently reverts your work.
- A check lands with an **executed red run** or it does not land. And a case
  that stays green is telling you something true: four were withdrawn last
  night after measurement showed the property was defended structurally and the
  mutation could not produce the defect.
- **Assert WHICH refusal, not that one happened.** `Executor.execute` raises
  `NotAuthorized` from two places now, and a bare `except NotAuthorized` cannot
  tell them apart — one check reported green while the property it guards was
  gone. Three separate cases hit this shape in one session.
- **Every refusal needs a control that succeeds.** Two containment cases passed
  under their own violation because the probe wrote to a path that was
  unwritable anyway, and because a judgement read `curl`'s exit code instead of
  its HTTP status.
- Documented counts drift on every check added. `CI-089` gates them; sync
  `CLAUDE.md` and `VESPER_ENGINEERING_STATUS.md`.
- Commit messages that contain backticks or `>` need `git commit -F` — the
  shell will otherwise execute them. One tried to redirect into `/etc/hosts`.

## The build order, where it stands

Tier one, all landed last night: the agentic loop, seatbelt containment,
read-before-write, `fs.edit`, shadow-git checkpoint and undo. Plus the taint
ceiling wired to the act path, the reachability gate, the rejection circuit
breaker, a prohibited tier no grant opens, the outer loop joined to the actor,
Keychain credentials, and a second authorization axis.

Next, from `docs/AGENT_LANDSCAPE_NOTES.md`:

- **S6. Process hardening pre-`main`** — `PT_DENY_ATTACH`, no core dumps, scrub
  `DYLD_*`. Swift, so it needs a build and therefore a TCC re-grant.
- **L13. A self-directed work queue** so the outer loop has more to consider
  than two host triggers.
- **M1. Feed memory citations back as usage** — the notes call it the cheapest
  high-value change available.

## Added 22:10 — the log stopped growing a gigabyte a day

`autonomy.noop` was writing one record per trigger per tick: **619,063 records /
420 MB over 41.8 hours from a single trigger**. Four self-directed triggers
landed this morning, which projected the same idle machine to **1.78 million
records and ~1.5 GB a day**. Silence is now run-length encoded — a record states
the snapshot and the tick it has held since, with a 60-tick keepalive bounding
staleness — so the same 42 hours costs about 7 MB. This is more provenance than
the per-tick form, not less: INV-TRIG-6 asks that silence be auditable, and a
duration is more auditable than an instant.

**Still growing and NOT fixed:** `autonomy.heartbeat`, 365 MB of the existing
1.67 GB, roughly 210 MB/day. It cannot get the same treatment — A-029 part 1
asserts per-tick cadence four separate ways, so collapsing heartbeats breaks the
gate that proves the loop is alive. At 584 bytes of body for a two-field
payload the cost is the record ENVELOPE, so the options are a smaller envelope
or a separate telemetry store with retention. **Both are durable-log format
changes and I did not make them unattended — this one needs you.**

The 1.67 GB already on disk is history; this bounds only what is written from
now. `repair.attempted` is 545 MB of it and was fixed at source earlier.

**Three self-test cases had gone dead, all in the good direction.** They named
`core/interlock.py`'s OWED entry (the emergency stop got wired, so the entry was
correctly deleted), the three-element `SELF_DEFEATING_DIRS` (it gained
`"interlock"`), and a two-element `all_triggers` return (it grew a third host
trigger). Nothing was broken in any of them — the code improved and the
mutations stopped matching, which is the direction that is hardest to notice.
Retargeted; 516/516 again.

## Host state at 22:10 — READ THIS FIRST

**The MacBook was on battery at 12% with ~55 minutes remaining, and `caffeinate`
was not running.** The charger came out at some point after the afternoon. I did
NOT restart `caffeinate`: holding a 12% machine awake makes it die rather than
sleep cleanly, and everything was committed and pushed (`9a953e6`, working tree
clean, `origin/feat/macos-host-profile` level with HEAD) before that decision.
If the machine slept, nothing was lost.

## Added 2026-09-02 — the agent-landscape build list is done

Twelve commits overnight. Full account in
`docs/WORK_REPORT_2026-09-02_OVERNIGHT.md`; the parts that change what a next
session should do:

**THE AUTONOMY LOOP HAD NOT BEEN RUNNING.** `pump()` read `interlock` from
another function's scope, so every pass raised NameError, the broad handler
caught it and published `autonomy.loop_failed`, and the loop never ticked. Fixed,
and gated by `the-runtime-resolves-every-name-it-uses`. **The runtime has not
been started since the fix — starting it is the first thing worth doing, and the
first real check of the night's work.**

**BOTH BUILD LISTS ARE COMPLETE EXCEPT AN MCP CLIENT.** L1-L10 and safety 1-9
are done; safety 10 (MCP) is not started. It is the highest-surface-area item on
either list: tool names and descriptions are declared by the SERVER, so tool
metadata is untrusted content and an unlevelled tool has to be L5.

**GRANT EXPIRY HAD NEVER WORKED** and now does. `_issue_standing` wrote an
absolute expiry and the PDP read a clock stuck at zero; each concealed the other.
Anything that assumed grants never expire is now wrong.

**SEGMENT ROTATION IS BUILT AND CALLED BY NOTHING.** `StoreSet.rotate()` archives
a log segment, seeds the new file's sequence past the old high-water mark, and
keeps the old one whole. There is no policy for WHEN to rotate -- that is a
decision about the owner's disk, not a property of the store, and it is the one
piece of this work that changes nothing until someone sets it.

**DO NOT RUN `self_test` CONCURRENTLY WITH ANYTHING.** It mutates live repo
files. Three false failures tonight came from overlapping it with `checks.py
all`, including one that read `CHECKS.toml` while it was deliberately broken.

## The last log item, analysed and deliberately NOT done

**94% of every event record is envelope.** A heartbeat is 579 bytes of which the
useful content -- `{"tick": N, "at_ms": M}` -- is 35. The rest is `event_id`,
the HLC stamp, `observed_at_wall`, a `source` block repeating the same three
constants, and five fields that are `null`.

Shrinking it is the supported move, not a hack: `INV-SCHEMA-2` says the log is
never rewritten and migration is read-time upcasting, and `core/codec.py` exists
for exactly that. New records would be written smaller and old ones upcast on
read, with no migration pass -- which matters because a migration needs a moment
when every node is present, and this system allows a node to be absent for days.

**WHY IT WAS NOT DONE TONIGHT.** The codec is on `EventBus.replay()` and NOWHERE
ELSE. `Compactor.project`, `verify_a029_from_log.py` and every other consumer
calls `store.read("log", ...)` and reads `rec.body` raw. So a narrower record
breaks any reader that indexes a field rather than `.get()`-ing it, and finding
those is an audit rather than a guess. Doing that unattended, on the durable log,
at 28% battery, is the wrong trade -- especially now that rotation bounds the
live file and growth is about 30 MB/day.

**THE ORDER FOR WHOEVER PICKS IT UP:** put the codec on the read path first (or
give `StoreSet.read` an upcasting option), audit the direct consumers, and only
then narrow the envelope. The win is roughly 4x on every record kind, which is
also 4x on each archived segment.

**And the cheaper one first:** archived segments are immutable and compress
**13.7x** (measured: 20,000 heartbeats, 11.7 MB -> 0.85 MB). Rotation bounds the
working file but not the disk -- the 1.68 GB archive is still 1.68 GB. Deciding
what happens to archives is the owner's, since the bin doctrine says VESPER never
deletes.
