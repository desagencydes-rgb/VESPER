# VESPER — Engineering Status

**Updated:** 2026-08-12, after the second engineering pass · **Maintained continuously.** If another engineer or agent takes over tomorrow, this file plus `docs/DECISION_LOG.md` is the handoff.

---

## Current position

| | |
|---|---|
| **Phase** | Second engineering pass closed. Implementation **not** authorised. |
| **Position** | Seven SRs carry recorded depth dispositions naming artifacts not yet written; `--profile release` fails on depth. **No completeness judgement is recorded here** — that is part of the gate. |
| **Verdict** | **None recorded.** The readiness gate is the project owner's act. `docs/architecture/IMPLEMENTATION_READINESS_REPORT.md` is *evidence for* that gate and reaches no verdict. |
| **Next action** | Owner performs the readiness gate and answers `OWNER-DECISION-006`. |
| **Known blocker on F0** | `INV-ADR-1` — no merge under `core/`, `tasks/`, `memory/` while `ADR-002` is not ACCEPTED. It is filed `PROPOSED`. |

**Live verification state** — every number below is produced by a command, and the command is the source of truth:

```
tools/traceability_lint.py                    PASS   0 errors, 0 warnings, 0 info
tools/traceability_lint.py --profile release  FAIL   7 errors, DEPTH only (7 SRs below SPECIFIED)
tools/reference_lint.py                       PASS   0 errors — 99 normative files scanned
tools/reference_lint.py --self-test           PASS   2/2 red-then-green
tools/ci/checks.py all                        PASS   10/10 runnable checks
tools/ci/self_test.py                         PASS   25/25 red under violation, green after restore
tools/ci/checks.py status                            14/53 check IDs implemented, 39 PENDING
```

> **`--profile release` failing is the correct state**, not a defect. It fails on depth: seven SRs are not yet `SPECIFIED`. Each records the artifact that would raise it. The dispositions do **not** excuse the depth — that was checked deliberately, because a disposition mechanism that turns a FAIL into a PASS is a mechanism for optimising the verdict.

---

## What the second pass found

The first pass declared **READY TO BUILD**. That declaration was **withdrawn**, because it was falsified by the corpus's own registry — not merely because the verdict was the owner's to make.

| # | Finding | Why it mattered | Status |
|---|---|---|---|
| 1 | **`ADR-002` (persistence) had never been written** | `INV-ADR-1` makes it a hard merge gate for `core/`, `tasks/`, `memory/` — which *is* F0. The declared next step was blocked by an invariant in the same repository. | Written, filed `PROPOSED` |
| 2 | **13 contracts named by REM specs did not exist** | Including `lease.schema.json` and `task.schema.json`, both F0 dependencies. The traceability linter validated only paths in `registry.toml`, so a specification could name a missing artifact and no gate noticed. | All 13 written; `CI-050` added |
| 3 | **11 dangling ADR citations**, 4 of them naming ids (017–020) outside the Foundation's ADR-001…016 namespace | A decision record with no referent is the exact defect ADR-012 was written to fix | Register created; citations corrected |
| 4 | **No shipped trigger registry existed** | `CI-026` — the anti-cron gate — had nothing to scan. Two documents described it as satisfied. | 8 triggers shipped, 0 `SCHEDULE`-class; `CI-026` implemented and red-verified |
| 5 | **`CI-016`'s coverage test ran in the wrong direction** | Governed **surface 6 — the tests themselves** — could be deleted with the check still green. Found by *executing* the declared self-test rather than trusting it. | Corrected; red-verified |
| 6 | **`CI-045` was declared by REM-014 and never registered** | A check a specification relied on that no gate would ever have run | Registered as `PENDING` |
| 7 | **36 of 50 acceptance tests named no negative control** | The index header claimed every entry declared one | 47 now name a wrong build; 3 record why one cannot exist; `TR-064` enforces it |
| 8 | **`INVARIANTS.toml` cited an enforcer that was never written** | A registry naming a non-existent tool is the same defect class as an invariant with an empty `enforced_by` | Corrected |

The common shape: **eight defects, none visible to any gate.** Every one is now covered by a check that has been shown red.

---

## Completed

| Work | Artifacts |
|---|---|
| **Repository structure + migration** | Part XIII layout honoured; every old→new path in the decision log |
| **Authority axes separated** (NV-04, AR-030) | `docs/AUTHORITY_AND_PRECEDENCE.md` — `L0–L5` / `E0–E4` / `Z0–Z3` |
| **Phase 1 — remediation** | REM-001…REM-016, each with the full 15-field treatment |
| **Phase 2 — system specification** | 29 subsystems, `SPEC-00`…`SPEC-D`, each with a Jarvis-divergence field |
| **Phase 3 — contracts & verification** | **26 JSON Schemas + 8 policy contracts** · 11 state machines with normative transition tables · **30 decision functions** · 111 invariants · 50 acceptance tests · 53 CI checks |
| **Phase 3b — reference integrity** | `ADR-002`, `ADR-007`, `ADR-REGISTER.md`; `tools/reference_lint.py` (`CI-050`) |
| **Phase 3c — enforcement made real** | 6 new checks implemented; `tools/ci/self_test.py` executes **25 red runs**, covering every implemented check |
| **Phase 4 — spikes** | 8 protocols with measurable pass criteria and pre-declared failure dispositions |
| **Runbooks** | Emergency stop · Alarm · **Integrity loss** (new) · **Proposal review** (new) |

### The three named remediations

| Item | Status | The mechanism, in one line |
|---|---|---|
| **NV-01** self-modification | Specified; `INV-SELF-2` RATIFIED | Runtime executes from a **pinned artifact ≠ the working repository**; it may open a proposal, never self-merge. **Overnight coding stays unrestricted** — `A-030.6` must *pass*. `change_proposal.schema.json` makes `MERGED` unwritable by a runtime author. |
| **NV-03** zero-input autonomy | Specified; blocking at F5 | A deterministic predicate decides *whether*; a model decides only *how*. Now backed by a **shipped registry of 8 non-`SCHEDULE` triggers** rather than a described one. |
| **FV-01** emergency stop | Specified | **Dead-man's switch**: actuation requires a fresh externally-signed token. Severing the stop path *halts* autonomy. |
| **Traceability** | Rebuilt, enforced, and extended | `registry.toml` + two linters. `CI-050` closes the class of defect the first pass could not see. |

---

## Owner decisions

| ID | Status | Subject |
|---|---|---|
| 001–005 | **RESOLVED** 2026-08-12 | Self-modification `L5`, COC v1.2 additive, Part XV retraction, review family, scanning scope |
| **006** | **OPEN** | (a) ratify `ADR-007` (security boundary) · (b) accept `ADR-002`, or delegate · (c) whether four REM-carried decisions should receive numbered ADR ids |

`OWNER-DECISION-006(b)` is the one that unblocks F0.

---

## Depth not yet reached — stated plainly

| Gap | Detail | Why it is acceptable now |
|---|---|---|
| **39 of 53 CI checks unimplemented** | `tools/ci/checks.py status` for the live figure | Most are structural checks over source code that does not exist. Each declares its self-test and lands **with** its subsystem. `CI-022`, `CI-034b`, `CI-046b` were deliberately split or held at `PENDING` rather than let a partial implementation be reported as full coverage. |
| **7 SRs below `SPECIFIED`** | SR-016, 017 (`DESIGNED`); SR-023, 033, 034, 035, 038 (`CONTRACTED`) | Each names the artifact required and why it is absent. **SR-034 is the worked example of the discriminator**: a decision function for *"clean hierarchy, formatting, vocabulary"* would be a document written to move a linter. |
| **18 invariants enforced only by acceptance tests** | No CI or mechanism binding | Visible in every `ci-registry` run as a note. Most require runtime state to check at all. |
| **Acceptance tests are specifications** | 50 tests with procedures and assertions | Executable fixtures require the runtime. 47 now name the wrong build that must fail. |
| **`A-029` and `A-031` never run** | The two decisive gates | Cannot run before the autonomy engine and interlock exist. `CI-027` blocks the autonomy release without their evidence. |
| **8 spikes unrun; every hardware figure `UNKNOWN`** | `capability_profiles.toml` carries 31 unmeasured fields | Deliberate and enforced: `CI-034` fails the file if any figure is filled in from a datasheet while `measured = false`. Unmeasured is treated as **unavailable**, not as available. |
| **Runbooks written, none validated** | Four runbooks exist | None executed on real hardware. The alarm one must be validated **at night, with the owner genuinely asleep beforehand** — a wake-up procedure validated while awake has not been validated. Phase 8. |
| **`git init` not run** | Deliberate | Branch protection needs a host (`SETUP.md`). `CI-002` and `CI-044` are `PENDING` because they cannot be trusted without history. Both linters run standalone. |

---

## Unresolved contradictions

**None outstanding at the engineering level.** Every contradiction found was resolved with a mechanism or escalated as an owner decision. Previously recorded and still resolved: SR-003 × SR-045 (queue within the free subset); RB-005 × RB-006 (preparation unbudgeted, interruption budgeted); SR-031 × RB-012 (feasibility, not contradiction — `SPIKE-005`); SR-042 × SR-049 (the boundary is on **merge**, not on work); immutable log × privacy deletion (payload/reference separation).

One naming drift was found and corrected this pass: `tunables.toml` initially invented field names where REM-015 §3.5 had already declared them. REM-015's names and ranges are authoritative and are now used verbatim, and `DF-TUNABLE` reads its field set **from the contract** rather than an inlined list — a list in a specification and a list in a contract will drift.

---

## Next actions, in order

1. **Owner:** perform the readiness gate. Answer `OWNER-DECISION-006` (a), (b), (c).
2. **Human:** `git init`, push, branch protection, replace `@owner` in `CODEOWNERS` (`SETUP.md`). Then self-test `CI-002` and `CI-044` red.
3. **Engineering, no dependency on any owner decision:** `SPIKE-001` → `SPIKE-002`, `SPIKE-007`, `SPIKE-008`.
4. **Then, and only then:** F0 — but not before `INV-ADR-1` is discharged by `ADR-002` acceptance. First increment is the persistent runtime, event bus, durable task state and checkpoints, gated by `A-033` and `A-034` **with their negative-control runs recorded**.
