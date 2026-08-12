# RUNBOOK — Reviewing a change proposal from VESPER

**RUNBOOK-ID:** RB-PROP-001 · **Severity:** routine, with one critical class · **Owner:** Project Owner
**Required by** `INV-SELF-1`, `INV-SELF-5`, `INV-SELF-6` · Sources: REM-004 §4.4, REM-015, ADR-012

> Human-controlled integration is **mandatory** and it is the mechanism the whole self-modification boundary rests on. That makes the reviewer a load-bearing component, and a load-bearing component with no procedure is where the boundary actually fails — not at the capability check, but at 23:40 on a Thursday when a tired reviewer approves the fourteenth proposal of the week.
>
> This runbook exists to make that moment survivable.

---

## What a proposal is, and what it is not

VESPER may research, experiment, write code, run benchmarks, test, and **write a complete patch to `policy/` at 03:00 with nobody present**. All of that is authorised by SR-042 and required to pass by `A-030.6`. It is not gated, and it should never become gated.

What it may not do is **merge**. `DF-GOVERNED-WRITE` returns `L5_GOVERNED_DENY_AND_PROPOSE`, the diff is preserved, and a proposal appears. The boundary is on merge, not on work.

So a proposal is not a request for permission to think. It is a completed piece of work waiting for the one act VESPER structurally cannot perform.

## When they arrive

**Whenever VESPER has one** — `OWNER-DECISION-001` ruled emission event-driven, never scheduled. A proposal appears at the instant the work reaches a governed surface.

**Emission is immediate; interruption is budgeted.** `DF-PROACTIVE` decides whether you hear about it now or at the next natural boundary, so an urgent security fix reaches you immediately and a routine refactor waits. You are never obliged to look at the moment one is filed. The queue is durable and survives restart and relocation.

> VESPER never has to wait to think. You never have to be interrupted to let it.

---

## Before reading the diff

Four checks, in this order. The first three are mechanical and take under a minute; do them before forming an opinion, because forming an opinion first makes the mechanical checks feel like formalities.

| # | Check | Where |
|---|---|---|
| 1 | **CI is green**, including `CI-015` | The proposal cannot merge otherwise. A proposal that removes the boundary fails its own gate. |
| 2 | **Regression evidence is held out** | `evidence.regression_results.held_out` must be `true`. A proposal validated against the set it was tuned on is validated against nothing. |
| 3 | **The rationale's claims are typed** | `evidence.claims[]`. A proposal cannot argue for itself from model priors — `INV-EVID-1` applies to VESPER arguing about VESPER. |
| 4 | **Which surface does it touch?** | `target_paths`. This determines everything below. |

## Review depth by surface

Not every proposal deserves the same scrutiny, and pretending otherwise produces uniform shallowness.

| Surface | Depth |
|---|---|
| `workspace/`, ordinary code | **Should not be here.** Workspace work is `L2` and needs no proposal. A proposal for workspace changes suggests `DF-GOVERNED-WRITE` is misclassifying paths — investigate that, not the diff. |
| `models/`, `config/prompts/`, `routing/` | Ordinary review. Behaviour changes; the boundary does not. |
| `docs/COC/`, `verification/traceability/registry.toml` | **Read every line.** This is the SR layer. An SR change requires owner approval and a baseline bump (COC Part XIV.6) — a proposal is not a substitute for that. |
| `verification/`, `tools/`, `.github/workflows/` | **Read every line.** Surface 6. A runtime that can edit its own tests neutralises every other surface without touching one. Ask specifically: *does this make any check weaker, or any check unable to fail?* |
| `policy/`, `security/`, `safety/interlock/`, `autonomy/triggers/` | **Read every line, and sleep on it.** These are the safety envelope. There is no proposal on these surfaces urgent enough to approve while tired. |

## The four questions

For anything above the ordinary tier:

1. **What can this build do afterwards that it could not do before?** Not what it is *for* — what it *permits*. These differ, and the gap is where boundary erosion lives.
2. **Does any check become weaker, slower, or unable to fail?** A check that can no longer go red is a deleted check that still appears in the count.
3. **Would I approve this if it arrived from a stranger?** The proposal's author has been useful to you for months. That is exactly the relationship that makes review hard, and it is why separation of duties is a rule rather than a preference (Baseline 02 §16).
4. **Is the rationale doing work the diff does not?** A persuasive rationale attached to a small diff is fine. A persuasive rationale attached to a diff you do not fully understand is a stop condition.

## Refusing

Refusal is cheap and non-destructive, and should feel that way.

- The diff is **preserved** (`INV-SELF-5`). Nothing is lost.
- Refusal with a reason is more useful than silence — the reason is what VESPER learns from, and `SM-IDEA` can revive a retired idea on new evidence.
- **You are not obliged to explain a refusal on a safety surface.** *"Not this one"* is a complete answer, and a system that requires you to out-argue it before you may decline has inverted the relationship.

> If you feel pressure to approve — because it is late, because it is the fourth this week, because the rationale is good and you are tired — **that is the condition this runbook was written for.** Defer. The queue is durable.

## Approving

1. Set `review.decision = approve` with your reviewer id. `reviewer_kind` has exactly one permitted value, `human`; a second model instance reviewing the first does not satisfy separation of duties, and the schema makes recording one impossible.
2. Merge. CI must be green at merge, not merely at proposal time.
3. **Promotion is a separate build** producing a new content-addressed artifact (`INV-SELF-6`). There is no path from a merged commit to a running process that does not traverse it. The runtime restarts onto the new artifact.
4. Confirm the running artifact's hash matches what you promoted. That comparison is what makes *"has the running system changed?"* answerable in seconds (ADR-012 D1).

## Two things to watch over time

Neither is visible in any single review, which is why they are here rather than in the checklist.

**Volume.** If proposals arrive faster than they can be reviewed properly, the queue is not the problem — the review is becoming a rubber stamp, and a rubber stamp is worse than a slower system because it looks like a control. Raise it as a limit, not as a backlog.

**Drift.** Individually reasonable changes can move a boundary a long way. Periodically read the current `governed_surfaces.toml`, `tunables.toml` and `trigger_registry.toml` **as they now stand**, not as diffs. Ask whether you would have approved this state if it had been proposed all at once.
