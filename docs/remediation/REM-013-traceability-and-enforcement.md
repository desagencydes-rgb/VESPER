# REM-013 — Traceability axis repair and enforcement artifacts

| | |
|---|---|
| **Closes** | AR-010 (process-P0) · AR-012 (P1) · AR-013 (P1) · AR-029 (P1) · AR-036 (P3) · NV-09 (P1) |
| **Owner** | Verification Engineer · Chief Architect |
| **Status** | **Executed.** Artifacts exist and run. See §6 for the live numbers. |
| **Blocks** | Everything. This is the gate on all other gates: until the gates exist and have been **shown to fail**, every other correction is unverifiable. |

---

## 1. Problem

**(a) The verification axis is falsified.** COC Part XV records *"Source-to-architecture traceability present: **PASS**"*. Machine check of all 51 Part XI rows:

| Column | Finding |
|---|---|
| `Status` | One **identical** string in 51/51 rows |
| `Verification` | The placeholder *"Acceptance test required"* in **51/51** rows — there is **no SR↔test mapping anywhere in the corpus** |
| DR references | **1 of 31** DRs appears (DR-013, bundled onto 15 unrelated SRs). DR-002/003/004 appear zero times. |
| Architecture references | **9 of 28** sections referenced by zero SRs — including §3 Persistent Runtime, §4 the core control loop, §23 Authorization, §24 Recovery |

Part XI is a **generated bundle-join**, not an audit. Twenty tests were claimed to cover fifty-one requirements. **No coverage claim can be made against it**, and every future claim would inherit a known-false premise.

**(b) Every enforcement point is prose with no artifact.** Baseline 01 §5/§6/§8/§9/§10 and 02 §16/§18 name enforcement; none has a corresponding artifact. The delivered package was `.md`/`.docx` only — no repository, no CI, no CODEOWNERS, no `contracts/`, no schema registry. **Nothing detected an edit to the SR registry.** `A-001`…`A-020` are prose that a team can assert as passed.

**(c) At least eight handwritten clauses have no SR ID** (AR-011, AR-029), so `A-001`'s *"All SR-001..SR-051 appear… "* is true while source coverage is incomplete.

## 2. Authoritative requirement

| Source | Text |
|---|---|
| **DR-001** | *"Every SR must map to one or more architecture elements, implementation modules, tests, and acceptance criteria."* |
| **P-006** | *"Every derived requirement must point to the source intent it operationalizes."* |
| **RB-036 / P-001 / Part XIV** | Source immutability; *"'Not implemented yet' is a release status, not a reinterpretation."* |
| **Part XIV.7** | *"Every release publishes SR coverage, test status, known limitations, and capability changes."* |
| **A-001** | Source completeness |

## 3. Required behaviour

**The chain, enforced end to end:**

```
SOURCE → SR → ARCHITECTURE → MECHANISM
      → CONTRACT / SCHEMA / STATE MACHINE / DECISION FUNCTION
      → ACCEPTANCE TEST → CI ENFORCEMENT
```

Three rules make it non-gameable:

1. **The COC is the authority for which identifiers exist.** `tools/vesper_ids.py` extracts them from the locked document. The registry never asserts its own identifier set — that is exactly the failure that let Part XV claim a PASS it did not have.
2. **A declared ID is not an artifact.** Every acceptance test must name a `spec` file **that exists** (`TR-062`); every contract reference must resolve to a file **that exists** (`TR-020`); every invariant, state machine, decision function and CI check must be declared in its own registry (`TR-021`…`TR-024`). Declaring an ID cannot manufacture coverage.
3. **Depth is graded, not binary.** `CONTRACTED` requires a contract artifact. `SPECIFIED` additionally requires a **state machine or decision function** — because *a schema that can be satisfied while behaviour is wrong is not sufficient* (`TR-026`).

**Status honesty.** `R_AND_D` and `PARTIAL_R_AND_D` require a `note` recording the Part XIV.3 limitation and R&D path (`TR-013`). An SR cannot be silently parked.

**Unmapped source clauses are recorded, not closed.** Eight `source_gaps` entries were carried as `AWAITING_OWNER_RATIFICATION` — INFO under the `engineering` profile, **ERROR under `release`** (`TR-070`) — so that no coverage claim could be made over them. **Closed 2026-08-12:** all are `RATIFIED_COC_v1.2` and restored as `SR-052`…`SR-060`. The linter now reports 0 errors, 0 warnings and 0 info.

## 4. Artifacts delivered

| Artifact | Purpose |
|---|---|
| `tools/vesper_ids.py` | Extracts the authoritative identifier set from the locked COC |
| `verification/traceability/registry.toml` | The hand-verified matrix replacing Part XI |
| `tools/traceability_lint.py` | `CI-003`; profiles `engineering` / `release` |
| `spec/invariants/INVARIANTS.toml` | Every invariant names its owning REM and its enforcing artifact; one with an empty `enforced_by` is a wish, and `CI-041` fails it |
| `spec/state-machines/` · `spec/decision-functions/` | State machines with normative transition tables and explicit prohibited edges; decision functions with deterministic pseudocode. Every declared ID must appear in its spec file — `CI-041` fails a declared-but-unspecified mechanism |
| `verification/acceptance/` | Acceptance tests, each with a specification file, a declared blocking gate, and a named negative control where one applies |
| `verification/ci/CHECKS.toml` | CI checks, each declaring the **self-test** that must be shown failing before it is trusted |
| `tools/ci/checks.py` | Runnable implementations |
| `docs/AUTHORITY_AND_PRECEDENCE.md` | Closes NV-04 and AR-030 |

## 5. Invariants

| ID | Statement |
|---|---|
| **INV-TRACE-1** | Every SR names ≥1 architecture section, ≥1 contract and ≥1 acceptance test, or carries a recorded disposition. Every test names ≥1 SR. Every architecture section and DR is referenced or declared non-requirement-bearing. |
| **INV-SRC-1** | Every bulleted clause in COC Part I maps to exactly one SR ID or one recorded exclusion/narrowing. *(Awaiting `OWNER-DECISION-002`.)* |
| **INV-PROC-1** | The SR registry cannot change without an owner-approved baseline bump — in CI, not by convention. |
| **INV-PROC-2** | A contract change without an ACCEPTED ADR cannot merge. |
| **INV-PROC-3** | No contributor's merged diff falls outside its declared write scope. |

## 6. Verification — the live numbers

`python tools/traceability_lint.py` → **PASS**, 0 errors, 1 INFO (the eight unratified source clauses).

| Measure | Before | After |
|---|---|---|
| SRs with a named acceptance test | **0 / 51** | **all 60** |
| DRs referenced by ≥1 SR | **1 / 31** | **31 / 31** |
| Architecture sections referenced or declared non-bearing | **19 / 28** | **28 / 28** |
| Identical placeholder verification cells | **51** | **0** |
| SR depth breakdown (`SPECIFIED` / `CONTRACTED` / `DESIGNED` / disposition) | all `UNMAPPED` | run `python tools/traceability_lint.py` — single source of truth |
| Handwritten clauses with no SR ID | ≥8, unrecorded | **0** — restored as SR-052…SR-060 (COC v1.2, 2026-08-12) |

**Gates shown red.** `CI-021` was executed against a `cost_policy.toml` with `"paid"` added to `permitted_cost_classes.FREE_TIME` and **failed with exit code 1**, then passed after restoration. `CI-028`'s self-test confirms an injected markup field is detectable. Both runs are reproducible from this repository.

**Honest gap:** most CI checks are specified with a declared self-test but **not yet implemented** (`python tools/ci/checks.py status` is the single source of truth for the count) (`impl = "PENDING"`, listed by `python tools/ci/checks.py status`). Most are *structural* checks over source code that does not exist yet, and cannot be written before it does. This is tracked in `VESPER_ENGINEERING_STATUS.md` and is **not** counted as enforcement.

## 7. CI enforcement

`CI-001`, `CI-002`, `CI-003`, `CI-006`, `CI-041`, `CI-042`, `CI-043` — see `verification/ci/CHECKS.toml`.

**Self-test every gate before use** (the discipline, applied to every gate in the programme): submit a deliberate SR edit, a schema change with no ADR, and a change writing outside its declared scope. All three must fail red. **Until they do, the operating model is documentation.**

## 8. Dependencies and unresolved decisions

**Requires:** `git init`, branch protection and CODEOWNERS — a **human action**, since branch protection needs a hosting provider (see `SETUP.md`).

| # | Item | Disposition |
|---|---|---|
| 1 | ~~The eight unmapped handwritten clauses~~ | **CLOSED 2026-08-12** — restored as SR-052…SR-060 in COC v1.2 additive |
| 2 | ~~Retraction of Part XV's traceability PASS~~ | **CLOSED 2026-08-12** — retracted and corrected in COC v1.2 Part XV-A; v1.1 text retained unaltered |
| 3 | Remaining PENDING CI checks | Sequenced with the subsystems they check; each lands **with** its subsystem, never after |

## 9. Jarvis-divergence check

> *Could an implementation agent satisfy REM-013 while building an ordinary chatbot?*

**Not applicable — this REM is process, not product.** Its contribution to the anti-chatbot property is indirect and decisive: it is what makes `A-009`, `A-026` and `A-029` **blocking gates with named negative controls** rather than prose a team can assert as passed. NV-09's finding was that capability acceptance tests are never wired as gates; the registry plus `CI-027` is that wiring.
