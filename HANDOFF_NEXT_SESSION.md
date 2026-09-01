# Handoff — pick up here

Rewritten 2026-09-01 07:15, at the end of the overnight session that completed
tier one of the build order. Read this, then
`docs/WORK_REPORT_2026-09-01_OVERNIGHT.md`, then `CLAUDE.md`.

## State

- **99 checks pass. 470/470 self-test cases** red under violation, green after
  restore. Both lints, F0–F6 acceptance, placement and fabric stress all pass.
- Working tree clean, everything pushed to `feat/macos-host-profile`.
- Backup branch `backup/pre-overnight-2026-09-01` at `831a177` — the state
  before the overnight run.
- `build.sh` has **not** been run since the last TCC grant. Speech and
  Accessibility are intact. `scheduleWakeRetry` is still committed and unbuilt;
  **the next build must be followed by re-granting** —
  `[[tcc-grants-die-on-every-rebuild]]`.

## What needs the owner, in order

1. **The emergency stop.** `core/interlock.py` is a dead-man's switch that runs
   on tokens minted outside the runtime. Wiring it means deciding **who presents
   tokens and from where**. The easy way — letting the runtime mint its own —
   is exactly the kill-signal build A-031.2 names as the control that must
   fail. Until this is decided, VESPER can act and there is no stop to press.
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
