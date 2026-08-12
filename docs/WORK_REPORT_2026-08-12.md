# VESPER — Final Pre-Implementation Work Report

**Pass:** second engineering pass · **Date:** 2026-08-12
**Scope:** advance the pre-implementation engineering work as far as it can go without the owner’s readiness decision, and stop immediately before that verification.
**Verdict recorded:** **none.** The readiness gate is the project owner's act. This report is input to it.

---

## 1. Work completed

The first pass produced a corpus that declared itself **READY TO BUILD**. This pass audited that claim against the artifacts it rested on and found **eight defects, none of which any gate could detect**. They share one shape:

> **A claim about an artifact, where the artifact did not exist — and no check compared the two.**

| # | Defect | Consequence had it shipped | Status |
|---|---|---|---|
| 1 | `ADR-002` (persistence) was cited as a decision record by REM-002 and **had never been written** | `INV-ADR-1` forbids any merge under `core/`, `tasks/`, `memory/` while ADR-002 is not ACCEPTED. **F0 is exactly those three.** The corpus declared its next step cleared while an invariant in the same repository blocked it. | Written, filed `PROPOSED` |
| 2 | **13 contracts named by REM specifications did not exist** | `lease.schema.json` and `task.schema.json` are F0 dependencies; `capability`, `grant`, `context_fragment` are the entire authorization chain. The linter validated only paths in `registry.toml`. | All 13 written |
| 3 | **11 dangling ADR citations**, 4 naming ids outside the Foundation namespace | A decision record with no referent is the precise defect ADR-012 was written to fix | Register created; citations corrected |
| 4 | **No shipped trigger registry existed** | `CI-026` — the anti-cron release gate — had nothing to scan, while two documents described it as satisfied by `trg_improvement_backlog`, which lived only as a YAML block inside a markdown file | 8 triggers shipped; `CI-026` implemented |
| 5 | **`CI-016`'s coverage test ran in the wrong direction** | Surface 5's single file `verification/traceability/registry.toml` satisfied the requirement for `verification/`, so **governed surface 6 — the tests themselves — could be deleted with the check still green.** Found by *executing* the declared self-test. | Corrected; red-verified |
| 6 | **`CI-045` was declared by REM-014 and never registered** | A check a specification relied on that no gate would ever have run | Registered as `PENDING` |
| 7 | **36 of 50 acceptance tests named no negative control** | The index header asserted every entry declared one | 47 name a wrong build; 3 record why one cannot exist |
| 8 | **`INVARIANTS.toml` named an enforcing tool that was never written** | A registry citing a non-existent enforcer is the same defect class as an invariant with an empty `enforced_by` | Corrected |

Two new linters close the whole class: **`CI-050`** fails any normative document naming an artifact that does not exist, and **`tools/ci/self_test.py`** *executes* the self-tests that `CHECKS.toml` previously only required checks to *declare*.

---

## 2. Artifacts created or modified

### Created — 34 files

| Class | Artifacts |
|---|---|
| **Decision records (3)** | `ADR-002-persistence.md` (PROPOSED) · `ADR-007-device-identity-and-trust.md` (PROPOSED, owner-reserved) · `ADR-REGISTER.md` |
| **Contracts — schemas (14)** | `lease` · `task` · `verification_strategy` · `claim` · `capability` · `grant` · `context_fragment` · `change_proposal` · `model_profile` · `observation_ingress` · `endpoint_capability` · `context_budget` · `knowledge_map` · `telemetry_record` |
| **Contracts — policy (5)** | `trigger_registry.toml` · `latency_budgets.toml` · `degradation_ladder.toml` · `tunables.toml` · `capability_profiles.toml` |
| **Spikes (9)** | `INDEX.toml` + protocols `SPIKE-001`…`SPIKE-008` |
| **Tools (2)** | `tools/reference_lint.py` (CI-050) · `tools/ci/self_test.py` (red-run harness) |
| **Runbooks (2)** | `RUNBOOK-INTEGRITY-LOSS.md` · `RUNBOOK-PROPOSAL-REVIEW.md` |
| **Reports (1)** | this file |

### Modified — 22 files

`tools/ci/checks.py` (6 new checks + the CI-016 direction fix) · `tools/traceability_lint.py` (TR-028/029/064/065/066/067) · `CHECKS.toml` (CI-045 registered, CI-034b/046b/050/051 added, 14 evidence lines) · `registry.toml` (8 SRs raised, 7 dispositions, orphan mechanisms mapped) · `acceptance/INDEX.toml` (36 negative controls) · `DECISION_FUNCTIONS.md` + `INDEX.toml` (4 new) · `INVARIANTS.toml` · 11 REM headers · `IMPLEMENTATION_READINESS_REPORT.md` · `VESPER_ENGINEERING_STATUS.md` · `IMPLEMENTATION_SEQUENCE.md` · `OWNER_DECISIONS.md` · `DECISION_LOG.md` · `AUTHORITY_AND_PRECEDENCE.md` · `README.md` · `.github/workflows/ci.yml`

---

## 3. Requirements completed

**8 SRs raised to `SPECIFIED`.** Total: **48 of 60**, up from 40.

| SR | Subject | Mechanism added | Why it qualified |
|---|---|---|---|
| SR-006 | Local model architecture | `model_profile` + `capability_profiles` + `DF-SURVIVAL-PROFILE` | `CI-007`/`CI-034`, `INV-HW-1/2` already named it |
| SR-007 | Mapping instead of token dumping | `knowledge_map` + `DF-BAG-RETRIEVE` | `A-006` and `INV-EVID-2` already asserted it |
| SR-008 | Context management by intent | `context_budget` + `DF-CONTEXT-ASSEMBLE` | `A-032` already asserted both modes |
| SR-010 | Context Budget Manager | `context_budget` + `DF-CONTEXT-ASSEMBLE` | `A-032` |
| SR-011 | Performance monitor, model-visible | `telemetry_record` + `DF-GOVERNOR-LEVEL` | `CI-039` already existed and named the damping |
| SR-047 | Fast, realtime interaction | `latency_budgets` + `SM-SCENE` + `DF-DEGRADE` | `INV-PERF-1`, `CI-031`, `A-020`, `SPIKE-002` |
| SR-051 | The COC as the project's bible | `governed_surfaces` + `DF-GOVERNED-WRITE` | `CI-002`/`CI-003` implemented and running |
| SR-054 | Cache tiers | `context_fragment` + `DF-CACHE-ADMIT` | `INV-AUTH-3` required taint inheritance; `CI-012` existed |

**The discriminator applied:** an SR was raised **only** where the missing mechanism was already named load-bearing by a CI check, an invariant's `enforced_by`, or an acceptance-test assertion. Nothing was raised to move a linter.

---

## 4. Requirements still incomplete

**7 SRs below `SPECIFIED`.** `--profile release` **still fails on all seven** — verified deliberately, because a disposition mechanism that converts a FAIL into a PASS is a mechanism for optimising the verdict.

| SR | Status | Artifact required to reach SPECIFIED | Phase |
|---|---|---|---|
| SR-016 | DESIGNED | Network fabric contract: segments, trust zone per segment, the non-interference constraint | F6 |
| SR-017 | DESIGNED | Remote desktop access contract bound to `DF-AUTHORIZE`; depends on SR-016 | F6 |
| SR-023 | CONTRACTED | `Artifact` type with provenance + local/remote generation routing | F5 |
| SR-033 | CONTRACTED | Shares SR-023, plus the rule that a generated presentation is a `SemanticScene` rather than an HTML blob | F5 |
| SR-034 | CONTRACTED | Shares SR-023's `Artifact` type | F5 |
| SR-035 | CONTRACTED | Persona contract bounding humor and impressions against RB-001 and **RB-012 (never impersonate)** — the second is the load-bearing half | F5 |
| SR-038 | CONTRACTED | `SecuritySignal` type + triage decision function. **Highest value of the seven.** | F6 |

> **SR-034 is the worked counter-example.** *"MD/TXT/PDF reports with clean hierarchy, formatting, design, vocabulary"* has no decision content two engineers would implement differently. A `DF-ARTIFACT-RENDER` here would be a document written to move a linter — the exact failure `TR-026` exists to prevent. It stays `CONTRACTED`, and the release profile stays red.

---

## 5. Spikes

**Completed: none.** All eight require hardware that does not exist.

**Registered with executable protocols: 8.** Each declares a measurable pass criterion, a time box, and — **decided in advance** — what happens on failure, so the disposition is not chosen under schedule pressure by whoever holds the failing number.

| Spike | Question | Blocks |
|---|---|---|
| SPIKE-001 | Measured node capability profiles; the minimum viable profile for SR-005 | Hardware purchase · SPIKE-002/007/008 |
| SPIKE-002 | Does the voice chain close on the minimum profile, offline, in `FREE_TIME`? | SR-047 verification · `A-020` · R2 |
| SPIKE-003 | Kernel/OS access envelope per platform | SR-026 disposition |
| SPIKE-004 | Optical envelope of the volumetric output | The `volumetric` ladder rung **only** — contracts are not blocked |
| SPIKE-005 | Delegated call origination without deceptive impersonation | SR-031 disposition |
| SPIKE-006 | RF sensing feasibility, accuracy, legality | SR-037 (R&D only) |
| **SPIKE-007** | Foreground-only survival envelope | SR-060 depth on that node class · `A-048` |
| **SPIKE-008** | Does ADR-002's storage design deliver atomic fencing and crash-safe checkpoints? | **`ADR-002` acceptance confidence · F0 increment 1** |

SPIKE-007 was raised by REM-014 and had no protocol. **SPIKE-008 is new**: the other seven measure hardware; this one measures whether a *decision* survives contact with it, before durable data exists to migrate.

---

## 6. Validation results

Every command below was run at the close of this pass.

```
tools/traceability_lint.py                    PASS   0 errors, 0 warnings, 0 info
tools/traceability_lint.py --profile release  FAIL   7 errors — DEPTH ONLY, and correctly so
tools/reference_lint.py                       PASS   0 errors — 98 normative files
tools/reference_lint.py --self-test           PASS   2/2 red then green
tools/ci/checks.py all                        PASS   10/10 runnable checks
tools/ci/self_test.py                         PASS   25/25 red under violation, green after restore
tools/ci/checks.py status                            14/53 implemented, 39 PENDING
```

**Enforcement: 8/48 → 14/53 implemented.** Six new checks, each with a recorded red run:

| Check | Enforces | The violation it was shown to catch |
|---|---|---|
| `CI-026` | INV-AUTO-5, INV-IDEA-5 | The C1 cron build; a filler trigger with no `source`; the backlog trigger removed |
| `CI-030` | INV-SCENE-2 | The diagram voice-only rung dropped; an action outside the scene schema's enum |
| `CI-034` | INV-HW-2, INV-PLACE-3 | A throughput figure from a datasheet; unmeasured treated as available |
| `CI-046` | INV-TUNE-1 | Runtime state in governed config; cost policy removed from `not_tunable` |
| `CI-050` | INV-TRACE-1, INV-ADR-1 | A REM naming a contract that does not exist; an out-of-namespace ADR id |
| `CI-051` | INV-PERF-1 | Stage budgets exceeding the end-to-end budget; first-audio no longer asserted independently |

**All 14 implemented checks now carry an executed red run**, including the five that previously had none (`CI-003`, `CI-007`, `CI-021`, `CI-038`, `CI-041`/`CI-043`).

---

## 7. Remaining risks

| # | Risk | Disposition |
|---|---|---|
| 1 | **SPIKE-002 may find the voice chain does not close** on minimum hardware, offline, in `FREE_TIME` | Genuinely unknown. Budgets are written **before** measurement and `CI-031`/`CI-051` reject relaxing one alongside the code that failed it. The deliverable on failure is a Part XIV.3 limitation record. |
| 2 | **Every hardware figure is `UNKNOWN`** — 31 fields in `capability_profiles.toml` | Enforced fail-closed: `CI-034` fails the file if a figure is filled in while `measured = false`, and unmeasured capabilities are treated as **unavailable**. |
| 3 | **39 of 53 CI checks unimplemented** | Most are structural checks over source code that does not exist. `CI-022`, `CI-034b`, `CI-046b` were deliberately held or split rather than let a partial implementation be reported as full coverage. |
| 4 | **18 invariants have no CI or mechanism binding** — acceptance tests only | Visible as a note in every `ci-registry` run. Most require runtime state to check at all. |
| 5 | **No runbook has been executed** | Four exist, none validated. The alarm runbook must be validated **at night, with the owner genuinely asleep beforehand**. |
| 6 | **`A-029` and `A-031` have never run** | The two decisive gates. `CI-027` blocks the autonomy release without the C1 negative-control evidence. |
| 7 | **Single-model-family review** | `OWNER-DECISION-004` recommended cross-family for REM-004 and REM-005. **This pass was also single-family**, and it found eight defects the first pass missed — which is evidence for the recommendation, not against it. |
| 8 | **ADR-002 is a paper decision** | SPIKE-008 exists to validate it before durable data exists. Migration retrofitted onto durable data is the classic unrecoverable cost. |

---

## 8. Owner decisions outstanding

**`OWNER-DECISION-006`** — one packet, three linked questions:

- **(a)** Ratify **`ADR-007`** (node identity, enrollment, revocation, recovery). A security boundary, owner-reserved by `AUTHORITY_AND_PRECEDENCE §5`.
- **(b)** Accept **`ADR-002`**, or delegate acceptance to the Chief Architect role. **This is the F0 blocker.** Recommended after SPIKE-008 reports.
- **(c)** Whether the four decision records carried by REM-003…006 should receive numbered ADR ids, requiring an additive extension of the Foundation's ADR-001…016 namespace.

Decisions 001–005 remain resolved and propagated.

---

## 9. Exact state, immediately before the final readiness verification

- **60 source requirements.** 48 `SPECIFIED`, 5 `CONTRACTED`, 2 `DESIGNED`, 3 `R_AND_D`, 1 `PARTIAL_R_AND_D`, 1 `EXCLUDED_BY_SAFETY_POLICY`.
- **26 JSON schemas · 8 policy contracts · 11 state machines · 30 decision functions · 111 invariants · 50 acceptance tests · 53 CI checks · 8 spike protocols · 4 runbooks.**
- **Engineering-profile linters pass with zero findings.** Release profile fails on depth only, on the seven SRs listed in §4, each carrying a recorded disposition.
- **25 red runs executed and passing.** No implemented check is trusted on a declaration alone.
- **One F0 blocker:** `INV-ADR-1`, pending ADR-002 acceptance. **This is correct behaviour, not a defect to work around.**
- **One open owner decision:** `OWNER-DECISION-006`.
- **No production source code exists.** No implementation directory has been created. `git init` has not been run.
- **No readiness verdict has been recorded** by this pass, in either direction. The previous `READY TO BUILD` was withdrawn as **factually falsified** by `INV-ADR-1`, not merely as procedurally premature.

---

## 10. Recommended first implementation step, after the owner approves the gate

**Not F0.** In this order:

1. **Answer `OWNER-DECISION-006`.** (b) is what unblocks F0.
2. **`git init`, push, branch protection, `CODEOWNERS`** (`SETUP.md`). Then self-test **`CI-002`** and **`CI-044`** red — both are `PENDING` precisely because they cannot be trusted without git history, and both guard the source-immutability boundary.
3. **`SPIKE-001`** — measured node capability profiles. It informs the hardware purchase and unblocks the other three hardware spikes. It is the only spike with no prerequisite.
4. **`SPIKE-008`** — persistence validation. Its result is the evidence for accepting ADR-002, and it is far cheaper to revise a storage design on paper than after `state.db` has data in it.
5. **Then, and only then, F0 increment 1:** persistent runtime supervisor, event bus with HLC envelopes, durable task state, checkpoints, `SM-TASK`, `SM-LEASE` — gated by **`A-033` and `A-034` passing with their negative-control runs recorded**, not by the code compiling.

> **The single most valuable habit this pass would carry forward:** run the self-tests rather than trusting them. Executing `CI-016`'s declared self-test — a check that had been green since it was written — is what revealed that governed surface 6 could be deleted with the check still passing. Every other defect in §1 was found the same way: by comparing a claim against the artifact it named.
