# Handoff — pick up here

Written 2026-09-01, ~23:00, at the end of the session that gave VESPER
capabilities and surveyed the agent landscape. Read this first, then
`CLAUDE.md`, then `docs/AGENT_LANDSCAPE_NOTES.md`.

## You do not need the previous chat transcript

Everything decided is already written down and pushed:

| What | Where |
|---|---|
| The investigation, in full detail | `docs/AGENT_LANDSCAPE_NOTES.md` (4 parts) |
| Last night's work + what needs the owner | `docs/WORK_REPORT_2026-08-31_EVENING.md` |
| Doctrine, gate commands, machine facts | `CLAUDE.md` |
| Measured numbers with provenance | `MEMORY.md` |
| Per-node setup | `HANDOFF_TO_MACBOOK.md` |

The auto-memory (29 files) lives at
`~/.claude/projects/-Users-macbook-Projects-VESPER/memory/` and is keyed to the
**project path, not the account** — so on this same Mac a different account
picks it up unchanged. `MEMORY.md` there is its index.

## State as of this handoff

- Working tree clean, everything pushed to `feat/macos-host-profile`.
- **87 checks pass. 405/405 self-test cases** red-under-violation,
  green-after-restore. Both lints, F0–F6 acceptance, placement and fabric
  stress all pass.
- VESPER is **stopped** — the owner asked for it off to watch a film. The
  globe-key watcher (`ai.vesper.island.fnwatch`) is still loaded so Fn ×3 starts
  it again. Full restart:
  `launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.vesper.island.plist`
- Speech recognition **is granted** and the wake word was confirmed working
  acoustically. Accessibility for the globe key is granted-in-effect (the
  watcher fires) though `--fn-status` reports the flag false.
- One Swift change is **committed but not built**: the wake-listener retry
  (`scheduleWakeRetry`). It type-checks clean. It was deliberately not built
  because `build.sh` re-signs and would revoke the owner's TCC grants. **The
  next build must be followed by re-granting** — see
  `[[tcc-grants-die-on-every-rebuild]]` in memory.

## What the owner asked for next, verbatim in intent

1. **One more sweep of the landscape investigation — miss nothing** — then ADD
   to the artifact (`https://claude.ai/code/artifact/2c2ec20a-ad18-4dc2-9760-8d0df4e3c6b8`).
   **Do not remove anything already in it.** They have twice corrected me for
   compressing rather than adding.
2. **Then work autonomously, all night, without stopping.** Decide the next
   thing yourself when one finishes. Keep a backup so nothing is ruined. No
   problems, no bugs, no issues left behind. Efficiency matters more than
   feature count.
3. **`caffeinate -i`** (idle only — the screen must still be able to sleep).
   Watch heat and battery.
4. Deadline pressure: "code red". Do not defer work. Do not break anything.
5. If something needs the owner, **set it aside and move on** — do not block.

## The build order they approved

From `docs/AGENT_LANDSCAPE_NOTES.md`, tier one first. Containment ships
**with** the loop, not after it, because a loop multiplies whatever safety
posture exists.

1. The agentic loop — propose → execute → **observe** → propose again.
2. Seatbelt containment for `shell.run` (`sandbox-exec`, verified present).
3. Read-before-write, enforced.
4. `fs.edit` — surgical, unique-match-or-fail.
5. Shadow-git checkpoint and undo.

Then tiers two (make the loop useful), three (memory), four (reach).

## Rules that will bite you if you skip them

- `python3.13`, never `python3` — the system one is 3.9 and every gate dies on
  `tomllib` **while still exiting 0**.
- **Never let `tools/ci/self_test.py` be killed.** It mutates a file, runs the
  check, restores. A tool timeout is a kill: the run takes ~14 minutes, longer
  than the 10-minute Bash ceiling, so run it with `nohup … &` and poll. Check
  `git status` afterwards for a file you did not edit.
- **Do not edit repo files while it runs** — the restore writes back
  pre-edit bytes and silently reverts your work.
- A check lands with an **executed red run** or it does not land. Add the case
  to `self_test.py` and watch it go red, then green.
- Five times this session a check passed when it should have failed. The cause
  was always the same: the check tested for a NAME rather than a BEHAVIOUR, or
  probed through a door that returns early. Assert the property, then prove the
  mutation goes red.
- `INV-HW-1`: no product names in routing/resource/policy paths.
- Documented counts drift constantly. `CI-089` now gates them; sync
  `CLAUDE.md` and `VESPER_ENGINEERING_STATUS.md` after any check/case change.

## Known open items (none block the build order)

- `fs.write` can destroy a file it never read, and the verifier confirms it.
  **This is item 3 in the build order and the most urgent open defect.**
- Credentials sit plaintext in `~/.config/vesper/secrets.env`. macOS Keychain
  unused. Same failure that compromised OpenClaw.
- Capability policy is hard-coded in Python rather than a contract.
- The memory/action isolation (the proposer never sees memory) is real,
  accidental, and ungated.
