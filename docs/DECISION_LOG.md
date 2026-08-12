# VESPER — Decision and change log

Append-only. Every entry records what changed, on whose authority, and why. Owner decisions live in [`decisions/OWNER_DECISIONS.md`](decisions/OWNER_DECISIONS.md); this log records everything engineering decided under its own authority, plus every conflict raised.

**Nothing in this log modifies an SR, the Rulebook, or any locked COC part.**

---

## 2026-08-11 — Repository migration

The root contained authoritative artifacts scattered alongside working files. Moved into an intentional structure honouring COC Part XIII (`docs/COC/`, `docs/ADR/`, `docs/runbooks/`, `docs/changelog/`) with named siblings added, plus the PATCH-010 additive `contracts/`, `spec/`, `verification/`, `tools/`.

| Old path | New path |
|---|---|
| `ORINGINAL_HANDWRITTEN_REQUIREMENTS/` | `docs/source/handwritten-pages/` *(spelling corrected in the directory name only; file contents untouched)* |
| `original-handwritten-requirements-text-version.txt` | `docs/source/HANDWRITTEN_TRANSCRIPTION.txt` |
| `VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.1.{md,docx}` | `docs/COC/` |
| `VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.0.docx` | `docs/COC/superseded/` |
| `VESPER_V0_COC_and_RULEBOOK_v0.1.docx` | `docs/COC/superseded/` |
| `VESPER_ENGINEERING_FOUNDATION_v1.0.docx` | `docs/baseline/` (+ extracted `.txt` for machine reading) |
| `VESPER_ENGINEERING_BASELINE_v1.0/` | `docs/baseline/ENGINEERING_BASELINE_v1.0/` |
| `REVIEW_2026-08-11/` | `docs/review/2026-08-11/` |
| `claude's-return.txt` | `docs/review/2026-08-11/REVIEW_CLOSING_NOTE.txt` |

**Nothing was deleted.** Superseded COC versions are retained in `docs/COC/superseded/` with their obsolescence recorded here rather than by removal. No file content was modified during migration.

**Authority:** engineering (repository organisation). **Reversible:** yes, from this table.

---

## 2026-08-11 — Authority axes separated (NV-04, AR-030)

`docs/AUTHORITY_AND_PRECEDENCE.md`. Three authority axes were colliding on the token `L4`, one meaning *may cut a release* and the other *may send messages on the user's behalf*.

- **`L0–L5` action authorization** — locked in COC Part VII, **keeps the token**.
- **`E0–E4` engineering change authority** — the Foundation's axis, **renamed**; semantics preserved exactly.
- **`Z0–Z3` node trust zones** — named here; previously unnamed prose.

Package precedence declared: **Foundation governs architecture, Baseline governs process**, COC governs any residual conflict. Benchmark IDs renamed `FB01–FB08` / `BB01–BB10`.

This was done **before** the remediation specifications, because every authorization document written after it uses these tokens.

**Authority:** engineering (resolving ambiguity between derived packages; no SR affected).

---

## 2026-08-11 — ADRs accepted

| ADR | Decision | Previously |
|---|---|---|
| **ADR-001** | HLC + at-least-once + per-subject total order + supersession/TTL/conflict rules | *Intentionally unresolved* |
| **ADR-012** | Runtime executes from a **pinned deployed artifact ≠ working repository**; single writable control plane with per-domain leases and one standby | *Intentionally unresolved* |

ADR-012 was resolved **only as far as REM-004 needs a referent**. Packaging format, process supervisor, update transport, lease TTL values and quorum size remain open and are recorded as such — deferring them is safe; deferring the boundary was not.

**Authority:** engineering. Foundation's *"Intentionally unresolved"* list reclassified: these two were **BLOCKING-IRREVERSIBLE**, not deferrable. Deferring them does not avoid a premature lock; it delegates the lock to whoever implements first.

---

## 2026-08-11 — Prior-review corrections applied

Engineering did **not** adopt the recommended patch set verbatim. Corrections, each with its reason:

| Item | Correction | Reason |
|---|---|---|
| **PATCH-018** (NV-01) | Rejected as worded. *"Free-time self-modification prohibited outright"* **weakens SR-042**, which explicitly authorizes overnight *"code stuff"*. Re-scoped to **no self-merge into governing surfaces**. | Adopting it literally would violate COC Part XIV.2. `A-030.6` now requires the runtime to write a patch to `policy/` at 03:00 and **succeed** in filing a proposal. |
| **PATCH-020** (NV-03) | Extended with the **non-schedule discriminator**. | The proposed gate is **passed by a pure cron build**: schedule-triggered firing *is* zero-user-input. `A-029` part 3 + the C1 control fixes it. |
| **PATCH-022** (NV-05) | De-scoped to a P2 feasibility spike. | RB-012 **already records the resolution** (*"use appropriate delegated identity/attribution"*). Not an unrecorded contradiction; Part XIV.3 not triggered. |
| **NV-02** (verifier collapse) | **P0 rating rejected**; folded into REM-010 at P1 as two clauses. | The single-model constraint sits inside the handwritten *"MacBook specific"* bullet — a per-node constraint. The desktop is *"always connected"* and most available overnight. And the source asks for separate **control stages**, not model instances: *"another checks output against files/rules."* A deterministic check satisfies it better than a second model. |
| **PATCH-010, PATCH-006** | Extended. | 010 mechanised process only, not capability tests (NV-09) or the runtime-as-committer (NV-01). 006's registry proves actions *have* triggers, not that triggers *fire unprompted*. |
| **PATCH-019** | Merged into REM-010. | Correct response to an incorrect diagnosis; adopt the response, drop the diagnosis. |

**Authority:** engineering, re-derived against the authoritative text. Where a prior review's conclusion survived, it survived on re-derived evidence, not on its say-so.

---

## 2026-08-11 — Traceability axis rebuilt (AR-012, AR-013, NV-09)

`verification/traceability/registry.toml` + `tools/traceability_lint.py` replace COC Part XI as the operative traceability record.

| Measure | Before | After |
|---|---|---|
| SRs with a named acceptance test | 0/51 | **51/51** |
| DRs referenced by ≥1 SR | 1/31 | **31/31** |
| Architecture sections referenced or declared non-bearing | 19/28 | **28/28** |
| Identical placeholder verification cells | 51 | **0** |

Design rule that makes it non-gameable: **the locked COC is the authority for which identifiers exist** (`tools/vesper_ids.py`), and the registry supplies only mappings. A registry that asserted its own identifier set is exactly the failure that let Part XV claim a PASS it did not have.

COC Part XI and Part XV are **not modified** — retraction is `OWNER-DECISION-003`.

**Authority:** engineering (additive artifact). **Note:** `A-001` cannot honestly pass until `OWNER-DECISION-002` resolves; the linter reports this rather than hiding it.

---

## 2026-08-11 — Gates demonstrated red

Discipline applied: *a check that has only ever been green is not evidence.*

- **CI-021** run against a `cost_policy.toml` with `"paid"` added to `permitted_cost_classes[FREE_TIME]` → **failed, exit 1**; passed after restoration.
- **CI-028** self-test confirms an injected markdown field in the scene schema is detectable.
- **CI-003** shown red at 45 errors before the acceptance and mechanism registries landed, then green at 0.

Both runs are reproducible from this repository.

---

## 2026-08-12 - All five owner decisions resolved; COC v1.2 additive issued

The project owner ruled on all five packets. **COC v1.1 was not modified.** `docs/COC/VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md` was issued under Part XIV.6, so the diff between v1.1 and v1.2 is the permanent record of what was dropped and when it was restored.

| Decision | Ruling | Propagated |
|---|---|---|
| **001** | Approved, both clauses | COC v1.2 Part VII-A (non-narrowability) · `INV-SELF-2` -> RATIFIED · REM-004 §4.4a |
| **002** | Approved, all eight + a new SR-060 | COC v1.2 Part II-A · `SR-052`…`SR-060` · registry rows · REM-014 · `A-048` |
| **003** | Approved: retract with dated correction | COC v1.2 Part XV-A. Original v1.1 text retained unaltered. |
| **004** | Satisfied by a continuous external-model review channel | Baseline 03 §8 met by a second family reviewing each return |
| **005** | Approved: single-occupant dwelling; RF sensing tracks presence, not appearance | Scanning stays scoped to owner-enrolled assets |

**Owner ruling on proposal timing (001).** Proposals are emitted **the instant** the runtime's work reaches a governed surface - **never on a schedule**. Recorded in REM-004 §4.4a with the reason: a scheduled proposal path would make *"I found an improvement"* a function of the clock rather than of the world, which is the same anti-pattern as cron autonomy. Emission is immediate; *surfacing* is arbitrated by the interruption budget, so an urgent fix reaches the owner now and a routine refactor waits for a natural boundary.

**On 005 - the privacy mechanisms are retained despite the ruling.** The *legal scope* question is closed (no visitors, no shared walls, no third-party assets). But `INV-WORLD-1` (an unknown person is never resolved to the owner) and `INV-PRIV-1` (withhold on unknown presence) cost nothing and are **kept**. A fail-safe that only exists once it is needed is one that will not work when it is. The ruling narrows what VESPER may *scan*; it does not remove what VESPER does when the unexpected happens.

---

## 2026-08-12 - SR-060 added: opportunistic placement and last-resort survival

A **new owner requirement**, given while ratifying 002:

> *"nothing is sitting anywhere, Vesper eventually gets moved automatically where it feels comfortable, and when hardware is genuinely unavailable - say only the iPhone is online - it should end up there with just whatever it needs so it stays alive, and with the most resources it can get, not everything obviously, but at least the maximum it can get."*

This **reverses the posture** of the prior specification, which treated migration as a failure response and gave VESPER a home node. It is source-grounded: handwritten p4 already makes the desktop the *"main assistant's space if Macbook not available"* and the iPhone the fallback *"when no other hardware is available"*. The owner clarified the semantics.

**The engineering consequence that mattered.** `INV-TRUST-2` previously read as *"the iPhone can never keep VESPER alive"*. The defect was conflating two axes:

| Axis | Question | iPhone |
|---|---|---|
| `trust_zone` | May this node be relied on? | **`Z0`** - Secure Enclave key storage; fully trustworthy |
| `availability_class` | How reliably is it awake? | **`foreground_only`** - iOS restricts background execution |

Now separate fields on `NodeCapabilityProfile`. `INV-TRUST-2` restated to constrain **designed assignment**, not **runtime survival**: no continuity-critical capability may be *planned* to depend solely on a foreground-only node, but such a node may *host survival* when it is all that remains. `A-048.8` asserts the planning half and `A-048.4` the survival half - both must pass.

Delivered: REM-014 · `SR-060` · `DF-PLACE`, `DF-SURVIVAL-PROFILE` · `INV-PLACE-1/2/3` · `A-048` (nine cases; negative controls: a node-pinned build and an undamped build) · `node_capability_profile.schema.json` · `checkpoint.schema.json`.

**One case where absence is still correct:** if only a `Z2` node is reachable, VESPER does **not** run there. `INV-TRUST-1` holds without exception - a node failing the security baseline holding VESPER's identity is worse than a temporary absence. It emits `placement.survival_impossible` rather than failing silently.

---

## 2026-08-12 - REM-015: improvement backlog and idle-time research

**Owner requirement.** VESPER should log ideas and theses about its own improvement the moment it has them, keep the existing act-while-working proposal path, revisit the backlog when it has nothing to do, actively research those ideas, report results when the owner is available, and be able to adjust its own revisit pacing "because time is relative".

**One deliberate departure from the wording, and why.** The requirement says *"add a schedule"*. Implemented literally as a `SCHEDULE`-class trigger, the backlog sweep would fire on a clock whether or not VESPER was busy - the exact anti-pattern REM-008 exists to exclude, and it would have weakened `A-029`. But the owner's own description is a **state predicate** three times over: *"whenever it has nothing to do"*, *"when it has been a long time"*, *"or work that prevented it from doing it"*. It is therefore built as a **`COMPOSITE`** trigger over idle-state, staleness and starvation. That is not a reinterpretation - it is stronger than a clock and is what was actually described.

**Consequence worth noting:** the shipped trigger registry now contains a real non-`SCHEDULE` trigger by default, so `CI-026` and `A-029` part 3 are satisfied by a **product feature** rather than a test fixture. The anti-cron property became load-bearing in something the owner wanted for its own sake.

**Self-tuning, bounded.** `INV-TUNE-1` separates the tunable from its range: VESPER sets `revisit_after`, `idle_threshold`, `staleness_floor` and `starvation_count` freely **within owner-declared ranges**; it may never alter a range, a predicate, an authority, a budget or a cost policy. Out-of-range values are **clamped and reported** - a silent clamp would leave VESPER holding a false model of itself and acting on it.

**Both paths converge.** An idea that matures into a change to a governed surface traverses the same `change.proposal` and the same human merge (`INV-IDEA-3`). The backlog changes *when VESPER thinks*, never *what it may apply*.

Delivered: REM-015 · `improvement_idea.schema.json` · `SM-IDEA` · `DF-IDEA-REVISIT`, `DF-TUNABLE` · `INV-IDEA-1..6`, `INV-TUNE-1` · `A-049` (eleven cases; negative controls: a `SCHEDULE`-class sweep and a build permitting range self-modification) · `CI-046`, `CI-047`.

---

## 2026-08-12 - REM-016: record loss, honest forgetting, and where forgetting stops

**Owner requirement.** Broken or deleted records should be treated like forgotten ideas in a human brain - VESPER notices, says something brief and human, moves on, and flags it smoothly through voice and visual output rather than as an error string.

**The hazard inside it, and the resolution.** *"Moves forward"* is correct for a lost note and catastrophic for a missing security record: a deleted trigger-registry entry, a tampered `governed_surfaces.toml` or a truncated audit log is exactly what compromise looks like. A system whose trained response to all of them is a warm *"hmm, I forgot"* has learned to shrug at its own integrity failures - silently, cumulatively, and it would look charming for a year.

The resolution is not to dilute the affect but to **bound** it. A person shrugs about misplaced keys; the same person finding their front door open and their filing cabinet emptied does not. Treating those identically is not humanity, it is dissociation - and RB-033 already says so: humour *"must never override truth, safety, authorization."*

**Three loss classes**, assigned deterministically from which store held the body (`DF-LOSS-CLASS`, no model call):

| Class | Records | Response |
|---|---|---|
| **A** | Ideas, backlog, learned artifacts, caches, derived indexes | Human forgetting. Casual, aggregated, ambient. Moves on. |
| **B** | Checkpoints, proposals, alarms, memory, world history | *"I dropped something and it mattered."* Reconstruction attempted; on failure the task is `BLOCKED`, never `SUCCEEDED`. |
| **C** | Governed surfaces, authored triggers, interlock config, audit log, traceability registry, **the tombstone store itself** | **Incident. No affect. Immediate.** Bypasses aggregation and the interruption budget. |

**Two mechanisms that make it honest rather than charming.**

**Tombstones.** A person says *"I had a plan but I forgot"* because a trace remains. With no trace there is nothing to report, and claiming to have forgotten would be a fabrication (RB-002). Every durable record writes an index entry to a **separate store**; loss is tombstone-present AND body-absent. Three honest answers exist and only three: *"I had something here and it's gone"* (no deletion audit), *"something removed this"* (deletion audit exists), and **silence** (no tombstone).

**`INV-LOSS-3`: a known cause is never dressed as forgetting.** If the audit shows what deleted it, saying *"I forgot"* is a lie under RB-001. The honest version is still smooth - *"something ate my notes from Tuesday; I've flagged it"* - but accurate. **Charm never buys inaccuracy.**

**Two further guards not requested but required by the architecture.** Mass loss escalates: one lost note is forgetting, four hundred in an hour is a failing disk and becomes class C. And ambiguous classification escalates **upward** - the same asymmetry as `INV-COST-2`, because over-reporting is recoverable and under-reporting is not.

**Delivery follows SR-046.** The report is a `SemanticScene`, not a string, so it is spoken on a voice-only endpoint, ambient on the projector, and carries an *affordance* for inspection reachable without a keyboard (`A-050.9`).

Delivered: REM-016 · `record_loss.schema.json` (tombstone + loss) · `DF-LOSS-CLASS`, `DF-LOSS-SURFACE` · `INV-LOSS-1..6` · `A-050` (twelve cases; the load-bearing negative control is a build applying class-A affect to a class-C loss, which **must fail** 50.4 and 50.6) · `CI-048`, `CI-049`.

---

## Conflicts raised, not resolved by engineering

| # | Conflict | Disposition |
|---|---|---|
| 1 | `L5` non-narrowability alters a locked Part VII clause | **RESOLVED 2026-08-12** - approved; COC v1.2 Part VII-A |
| 2 | Eight handwritten clauses have no SR ID | **RESOLVED 2026-08-12** - approved; COC v1.2 Part II-A |
| 3 | Part XV asserts a traceability PASS the evidence does not support | **RESOLVED 2026-08-12** - retracted; COC v1.2 Part XV-A |
| 4 | Baseline 03 §8 requires cross-family review for security boundaries | **RESOLVED 2026-08-12** - satisfied by an external-model review channel |
| 5 | Third-party scope of scanning and camera coverage | **RESOLVED 2026-08-12** - owner-enrolled assets only; single-occupant dwelling |

**No engineering-level conflicts remain open.**

## Engineering positions recorded so they are not re-litigated

| Position | Basis |
|---|---|
| The J3 is **not** a `control_candidate`; it is `Z2 limited_trust` | `INV-TRUST-1` — `Z2` may not hold state. Resolves the two-incompatible-architectures reading of SR-018 without deferring it. |
| No continuity-critical capability may be assigned solely to the iPhone | Foreground-only execution; `INV-TRUST-2` |
| The world model is **topological**, not metric | No V0 requirement needs metres; metric coordinates would import a localisation stack nothing demands |
| Verification independence is a property of **strategy strength**, not model count | A passing test suite is more independent than a second LLM and runs offline on the weakest node |
| `metered_free_tier` is treated as `paid` absent a provable hard cap | A free tier on an account with a payment method can bill on overage |

---

## Second engineering pass — 2026-08-12

Eight defects found, none of which any gate could see. Recorded here because the *class* matters more than the individual items: every one was a **claim about an artifact rather than an artifact**, and the corpus had no check that compared the two.

| # | Decision | Rationale |
|---|---|---|
| 1 | **`ADR-002` written and filed `PROPOSED`, not ACCEPTED** | `REM-002` cited it as a decision record; the file did not exist, while `INV-ADR-1` makes it a hard merge gate for `core/`, `tasks/`, `memory/` — precisely F0. Filed `PROPOSED` because the pass that wrote it would otherwise have discharged the F0 gate by its own hand. **A gate discharged by its author is not a gate.** |
| 2 | **`ADR-007` written and filed `PROPOSED — owner ratification required`** | A security boundary; `AUTHORITY_AND_PRECEDENCE §5` reserves those to the owner and Baseline 02 §16 forbids an agent approving its own. Raised as `OWNER-DECISION-006`. |
| 3 | **`ADR-017`…`ADR-020` citations corrected rather than the namespace extended** | The Foundation register defines ADR-001…016 and is the authority for the namespace, as the COC is for SR ids. The four REMs already contained full ADR content; the pointer was a habit, not a missing artifact. Extending a baseline namespace to satisfy a citation would be reinterpretation dressed as bookkeeping. Recorded as `OWNER-DECISION-006(c)` in case the owner prefers numbered records. |
| 4 | **13 missing contracts written** | Named by REM specifications and never created. `lease` and `task` are F0 dependencies; `capability`, `grant` and `context_fragment` are the authorization chain. |
| 5 | **`tools/reference_lint.py` (`CI-050`) added** | The traceability linter validated only paths in `registry.toml`, so a specification could name an artifact that did not exist and no gate noticed. This is the check that would have caught items 1, 3, 4, 6 and 8 on the day they were introduced. |
| 6 | **`tools/ci/self_test.py` added — self-tests are now executed, not declared** | `CHECKS.toml` requires every check to declare its self-test. Declaring is not running. Executing them found `CI-016`'s coverage test running in the **wrong direction**: surface 5's single file satisfied the requirement for `verification/`, so **governed surface 6 could be deleted with the check still green**. Third instance of the CI-022/CI-044 defect class. |
| 7 | **Six checks implemented against shipped artifacts** (`CI-026`, `CI-030`, `CI-034`, `CI-046`, `CI-050`, `CI-051`) | Each required a product artifact that did not exist — most importantly `trigger_registry.toml`, without which `CI-026`, the anti-cron gate, had nothing to scan while two documents described it as satisfied. |
| 8 | **`CI-034b`, `CI-046b` split; `CI-031` left `PENDING` and `CI-051` created** | Where an implementation covers only part of an invariant, the covered half ships as its own check and the uncovered half stays visibly `PENDING`. Reporting a policy-file check as covering a runtime invariant is exactly what put `CI-022` and `CI-044` back to `PENDING` in the first pass. |
| 9 | **8 SRs raised to `SPECIFIED`; 7 given recorded depth dispositions** | Discriminator applied: raise an SR only where the missing mechanism was **already named load-bearing** by a CI check, an invariant's `enforced_by`, or an acceptance-test assertion. **SR-034 is the worked counter-example** — a decision function for *"clean hierarchy, formatting, vocabulary"* would be a document written to move a linter. `--profile release` was verified to still FAIL on all seven: a disposition mechanism that converts a FAIL to a PASS is a mechanism for optimising the verdict. |
| 10 | **`READY TO BUILD` withdrawn from the readiness report** | Two reasons, and the second is the load-bearing one: the readiness decision is the owner's, **and** the declaration was falsified by `INV-ADR-1` in the same repository. No substitute verdict was recorded in either direction. |
| 11 | **`tunables.toml` field names reconciled to REM-015 §3.5** | This pass initially invented names where the REM had already declared them with ranges. REM-015 is authoritative. `DF-TUNABLE` now reads `TUNABLE_FIELDS` **from the contract** instead of an inlined list, because a list in a specification and a list in a contract will drift — and the drift surfaces as the runtime refusing a field the owner believed was tunable. |
| 12 | **Spike namespace moved to `docs/spikes/`** | `AUTHORITY_AND_PRECEDENCE §5` recorded `docs/architecture/`. No spike had ever been written there, or anywhere. Location change only; no semantics affected. |

---

## Final pre-F0 correction and verification pass — 2026-08-12

The second pass audited the corpus. **This pass audited the verification system**, on the premise that a check is an artifact like any other and can be wrong in the same ways. Nine of the eleven defects below were found by deliberately violating a green check and observing that it stayed green. The recurring class is narrower than the second pass's and worse: **a check that reads a label, a name, or a declaration instead of the property it claims to enforce.** Every correction is accompanied by a permanent red run, so the class cannot silently return.

| # | Decision | Rationale |
|---|---|---|
| 1 | **Both mutation harnesses converted to byte-exact read/mutate/restore, with SHA-256 assertions around every case** | Found by a restore failure, not by design: Python's `write_text` rewrites `\n` as `\r\n` on Windows, so the harness that proves the checks silently **modified an LF baseline document** — `VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md` — while reporting success. A verification tool that alters the artifact it verifies is the most expensive possible defect, because every result taken after it is suspect. `read()` now normalises for the *match* and carries the original bytes and the file's newline convention for the *restore*. |
| 2 | **`CI-026` rewritten to parse and evaluate predicate bodies; label reading removed** | The anti-cron gate was **label-only**. A row whose body was a cron expression passed while printing `8/8 enabled and non-SCHEDULE`, provided its `predicate_class` field said `COMPOSITE`. It also could not see disablement: turning every state trigger off left it green. The check now classifies every namespace root against a closed vocabulary and evaluates each predicate with all clock terms TRUE and all world-state terms FALSE. If it still fires, **the clock alone is sufficient and the row is cron whatever it is labelled**. This is the check that holds the anti-chatbot property; it was the weakest one in the tree. |
| 3 | **`INV-ADR-1` re-derived as a tree property and `CI-008` implemented** | The F0 merge gate was `PENDING` while `CI-050` falsely claimed to enforce `INV-ADR-1`. It had been left unimplemented because it was conceived as a diff property needing git history. It is not: *"no file under `core/`, `tasks/` or `memory/` while any of ADR-001/002/012 is not ACCEPTED"* is checkable against a single tree, and is now checked on every run, reading status from the **ADR record** and cross-checking the register in both directions. |
| 4 | **`ADR-002` left `PROPOSED`; `OWNER-DECISION-006` left OPEN** | The gate this pass built blocks the work this pass would need to do next. Accepting the ADR would discharge it in a single edit. `AUTHORITY_AND_PRECEDENCE §5` reserves the decision, and **a gate discharged by its own author is not a gate** — the same reasoning that filed the ADR `PROPOSED` in the first place, applied to the auditor rather than the architect. `CI-008` was instead proven in **both directions**: red against a planted `core/` file, green against the same file once the status is genuinely `ACCEPTED`, which is what proves it keys on the decision rather than on the presence of code. |
| 5 | **Enforcement made bidirectionally consistent, resolving each asymmetry on the merits rather than by symmetrising** | `INVARIANTS.toml` and `CHECKS.toml` each named the other, and nothing compared them. `INV-SELF-2` — the self-modification boundary — recorded `CI-016` as its enforcer, a check that is implemented, runs, and **cannot see the property**: content coverage cannot observe a reviewer. A green run against a false record is worse than no record. Every asymmetry the new lint reported on its first run was resolved by deciding **which side was wrong**; making the two files agree would have been trivial and would have preserved the defect. |
| 6 | **Red-run coverage added to `CI-041/043`: a check marked `implemented` with no executed red run in `self_test.py` now fails** | Caught a real gap on its first run — `CI-050` was marked implemented and had never been shown red by the harness. **A check that has only ever been green is not evidence**, and until this lint existed nothing in the tree could tell the difference between a check that passes and a check that works. Vacuity is reported alongside it: `CI-007` and `CI-008` currently scan empty sets and are named as vacuous rather than counted as coverage. |
| 7 | **`CI-016` moved from string prefix to path-component prefix; `spec/` and `CODEOWNERS` added to surface 6; surface 7's dead path corrected** | Three independent holes in one boundary. String prefixing meant `core-notes/` satisfied `core/`. `spec/` — where every invariant, state machine and decision function in the system lives — was **governed by no surface at all** while `verification/` and `tools/` were inside: a runtime that may not edit the test may not edit the property the test checks either. And surface 7, written specifically to protect the trigger registry, pointed at `autonomy/triggers/`, a directory that has never existed; the shipped registry was governed only incidentally through another surface's prefix. **Dead configuration reads as protection.** |
| 8 | **`TR-068` added: an acceptance test must be *mentioned by* the specification it points at** | `TR-062` checked that the target file exists. Under that rule `A-029` could be repointed at any file in the repository and traceability stayed green — existence is not aboutness. The one-line consequence is that a test can no longer be detached from its subject by editing a path. |
| 9 | **`CI-050` scope holes closed and the linter's self-exemption removed** | The reference linter did not scan the **live COC baselines**, `.github/workflows/`, or `CODEOWNERS`, and excluded itself. The excluded set contained the constitutional documents and the file that decides who reviews changes to everything else. Its probe tokens are now assembled from fragments so that the linter scanning itself does not trip on its own test data. 107 normative files are now in scope. |
| 10 | **`SR-020` computer agency **specified**, not downgraded** | The honest reading of the registry was that `SR-020` had no mechanism. The cheap fix was to narrow the requirement until the existing artifacts covered it — which would have converted VESPER into a system that answers questions *about* computers. Instead: `SPEC-30`, `endpoint_interaction` and `endpoint_surface_state` contracts, `SM-ENDPOINT-EPISODE`, three decision functions, `INV-ACT-1…6`, `A-051`/`A-052`, and `CI-052/053/054` filed **`PENDING`** because they need a runtime. The load-bearing prohibition is `ACTUATED → VERIFIED`: **the actor's report is not the outcome**, and an observation captured through the acting path does not close an episode. |
| 11 | **`INV-GOV-1` written rather than repointing `CI-039` at a convenient invariant** | `CI-039` (governor damping) named an invariant that did not describe damping. The tempting correction — point it at whichever nearby invariant makes the registry consistent — is the `A-029` defect in a different file. The missing invariant was written instead. |
| 12 | **Repository initialised; the whole suite executed from a clean clone** | The corpus had no git history, so nothing had ever proven the tooling ran anywhere except this working directory. It now does, with `CI-008` demonstrably blocking a planted `core/probe.py`. |
| 13 | **Published coverage restated as `ENFORCED TODAY: 15/118`** | The tree previously reported checks that *exist*. The figure now counts only invariants named by a check that is implemented, bidirectionally consistent, red-run and non-vacuous — four conditions, each of which was individually false somewhere in this tree before this pass. The number went **down**, which is the point: *"the objective is not to make the repository look green."* |
