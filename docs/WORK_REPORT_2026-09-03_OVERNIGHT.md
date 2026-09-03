# Overnight, 2026-09-03

Nine commits, `467a469` → `be56b9b`, pushed. 127 checks and 558 self-test cases
green at every commit. Bundles in `~/VESPER-backups/` at each step.

## The measurement, and why it was hard to take

**Every agent rung was outside the ladder.** `measured_profiles` skips a
provider with no measured rate — `INV-HW-2`, unmeasured is UNAVAILABLE — and the
agent rungs had never appeared in a promoted measurement. Read through the
consumer rather than the file, `load_rows()` returned 27 rows with every
`claude-*` and `codex-*` agent among the 21 skipped. Nine sub-agents that
answered when probed and that the router could not reach.

It now returns 45.

**What made a clean sweep impossible is itself the finding.** Nine rungs share
one Claude subscription, so a sweep spends that account's allowance measuring it
and the rungs called last report a usage limit rather than a rate. Cumulative
across sweeps, not per-sweep: 03:16 reached all seven tried, 03:59 reached two.
Promoting that would have retired five working rungs — the probe killing what it
was measuring, with `INV-HW-2` unable to tell "unmeasured because unavailable"
from "unmeasured because my own probe burned the quota".

`--merge` carries a rung's last real measurement forward with `carried_from`,
`carried_reason` and `carried_age_hours` on the row. It refuses to carry over a
terminal status, so a withdrawn model still retires, and refuses anything older
than 24 h, so a carried number stays a measurement rather than a memory. Three
rows in the promoted file are carried, all Google 503s, each saying so.

## Four provider defects, three of which looked like outages

| Rung | Presented as | Actually |
|---|---|---|
| `nvidia-strong` | provider failure | model reached end of life 2026-08-26 |
| `cf-image` | malformed request | NSFW classifier false-positive on "a single grey square on a white background", then 137 KB of image on the next call |
| `codex-*` ×3 | rung failing | argv inherited `-p` from the claude row; `-p` is `--profile` to codex |
| `ollama-strong` | dead | 200 with 2048 reasoning tokens and zero characters of content |

The probe had been discarding every Cloudflare error body: it read OpenAI's
`error.message` and Cloudflare answers with `errors: [{code, message}]`. A
refusal whose reason is discarded is indistinguishable from a refusal with no
reason, and the two call for opposite responses.

**One recorded retry**, split by whether a refusal is terminal or transient. A
withdrawn model (410/405/501) descends and is never retried; 408/429/5xx, a
timeout, a 200-with-empty-body, an unexplained 400 and a stochastic content
refusal each get one more attempt. `attempts` is written into the row so a
second-attempt measurement is legible as one.

## Ratification, and the number that did not move

Fifteen checks that ran green while belonging to no registry entry are now
CI-104…CI-118. **Coverage moved 88 → 89, not 88 → 103**: fourteen of them name
invariants other checks already defend. Only `wake-word-listens-locally-and-
starts-once` reached an undefended one, `INV-PRIV-3` — raw media not kept past
its processing window, the one privacy rule with a continuously-open microphone
behind it, held until now by an acceptance test and nothing mechanical.

Testing that expectation before writing the batch is what kept it honest.

The registry then refused all fifteen for recording no `self_test_evidence` —
the executed red run rather than the intention to write one. Running them
properly surfaced the night's worst defect.

## The two readings that disagreed

`if __name__ == "__main__"` sits at line 4854 of `self_test.py`. Cases appended
below it **run on import and do not run as a script**. `CI-089` counts by
importing; the harness runs as a script. Two cases added earlier that night were
counted as evidence and never executed, and the evidence line recorded for
CI-104 named a case that had not run.

The disagreement is invisible in the one direction that matters: the count is
higher than what executes, and the surplus is exactly the new cases a session is
relying on. `CI-089` now parses the file and refuses any top-level statement
below the guard.

## Citations into the archive resolved to nothing

`read()` walks every segment and inflates each record against the archive's own
dictionary. `record()` — the point lookup a citation uses — queried the live file
alone and called `json.loads` on the body. Measured on the real store: 1,896,415
records had rotated into a 607 MiB compressed segment, and `record("log", 1)`,
`record("log", 500000)` and `record("log", 1896415)` all returned None.

**It failed in the worst direction.** `memory-citations-resolve-or-are-withheld`
withholds a claim whose support cannot be fetched, so this produced no wrong
answers — it silently retired the evidence for everything older than the last
rotation. A claim that goes unsupported reads as caution, not as a broken read
path. The check could not see it because it exercised the scan, and the scan was
correct throughout: two access paths to the same records, one tested.

Fixed and verified against the real archive: four point lookups in 2 ms at
27 MiB RSS, resolving from the compressed segment and the live log alike.

## Agents, end to end

`AgentRunner` built claude's flag set for every binary, so every codex agent
exited 2 before reading its prompt. Verified through the real runner after the
fix — researcher, briefer and auditor all answer. Containment is the sandbox
rather than the prompt: a thinking agent runs `read-only` at the process level
and only the one agent that may act gets `workspace-write`.

**A rung reporting it is out of quota was going to be quoted back as its
answer.** "You've hit your session limit" is 65 characters, past every length
bound in the runner. `_exhaustion` reads it as UNAVAILABLE, which descends. The
window is 200 characters because a written false-positive case caught an agent
*discussing* rate limits at ~370 and classifying it as a refusal.

## The bundle

`VESPER --arm` is a mode now. The minter is the process whose absence stops
autonomy and it ran as a bare `python3` outside the bundle. The token logic is
deliberately not ported. It resolves its repo from the binary rather than the
cwd — `currentDirectoryPath` is "/" under launchd, which works by hand and fails
as a login item.

**The app was rebuilt: cdhash `2069a84a…` → `1f015fc0…`, measured before and
after.** TCC grants are gone and `scheduleWakeRetry` is finally built. Nothing
further is pending a build.

## What is waiting on the owner

1. **Re-grant TCC** — `open -n app/VESPER.app --args --speech-consent`, then
   Accessibility for the globe key. The next grant is the one that lasts.
2. **Log in the advisor account** —
   `CLAUDE_CONFIG_DIR=~/.config/vesper/claude-advisor claude`. The only rung
   failing for a reason a session cannot fix.
3. **Ratify some of the 23** — `docs/planning/UNRATIFIED_CHECKS_2026-09-03.md`
   proposes the invariant text for each. Three are worth writing on their own
   merits; four look like extensions of existing invariants rather than new ones.

## The shape that keeps recurring

Seven times tonight a check was alive and useless: an assertion matching its own
definition, a negative probe containing no signature, a mutation landing where
nothing read it, a count taken by a path the runner does not use. Every one was
found by writing the failing case first and watching it stay green.
