# VESPER — Final Pre-F0 Correction and Verification Report

**Date:** 2026-08-12 · **Scope:** the whole engineering corpus at the F0 gate · **Author:** engineering pass 3 (verification audit)
**Status of this document:** VERIFIED — every figure in it was re-derived by running the tool named beside it, in this pass, against this tree.

---

## 1. Executive verdict

> ## `BUILD_AFTER_CORRECTIONS`

The corpus is **structurally ready** to be built against and is **not cleared to build today**. The blocker is not a defect and is not new: `INV-ADR-1` forbids any change under `core/`, `tasks/` or `memory/` while `ADR-001`, `ADR-002` or `ADR-012` is not `ACCEPTED`, and `ADR-002` is filed `PROPOSED`. That rule was previously held by discipline. As of this pass it is held by `CI-008`, which runs on every commit and **fires on the first file an F0 engineer writes**.

Three things separate this verdict from the one this repository could have been given a day ago.

1. **The verification system was audited as an artifact, not trusted as a control.** Eleven defects were found. Nine independent probes — each a deliberate violation of a check that was green — account for most of them; the remainder surfaced from a harness restore failure and from tracing a requirement to its mechanism. The recurring class is *a check that reads a label, a name, or a declaration instead of the property it claims to enforce* — including the anti-cron gate, which is the check that holds the anti-chatbot property.
2. **The published coverage figure went down.** The tree previously counted checks that exist. It now counts only invariants named by a check that is implemented, bidirectionally consistent, red-run **and** non-vacuous: **`ENFORCED TODAY: 15/118`**. Each of those four conditions was individually false somewhere in this tree before this pass.
3. **No requirement was narrowed to make a gate pass.** Where the honest reading was that `SR-020` had no acting mechanism, the mechanism was specified (§8). Where an invariant was missing, it was written rather than substituted (`INV-GOV-1`). Where a decision was owner-reserved, it was left open and recorded as `BLOCKED` (§12).

`BUILD` is not available: an ADR that gates F0 is unaccepted, and the decision is not this auditor's to take. `DO_NOT_BUILD` is not warranted: nothing found in this pass is an architectural or authority defect requiring redesign, the blockers are enumerable, and each has a named discharge path.

---

## 2. Corrections performed

Full rationale for each is recorded in `docs/DECISION_LOG.md` under *"Final pre-F0 correction and verification pass — 2026-08-12"*. Summary, in the order the brief numbered them:

| # | Finding | Correction | Evidence it now holds |
|---|---|---|---|
| 1 | **`ADR-002` lifecycle** — cited as a decision record and gating F0 | Left `PROPOSED`. `CI-008` implemented and proven in **both** directions: red against a planted `core/` file, green against the same file once `ADR-002` is genuinely `ACCEPTED` | `self_test.py` scenario cases; §5 |
| 2 | **`CI-026` validated labels, not semantics** | Rewritten to parse each predicate **body**, classify every namespace root against a closed vocabulary, and evaluate the predicate with **all clock terms TRUE and all world-state terms FALSE**. If it still fires, the clock alone suffices and the row is cron whatever it is labelled | `8/8 enabled AND proven to require world state to fire`; 5 red runs |
| 3 | **Registry was one-directional; negative controls were weak** | `CI-041/043` now compares `INVARIANTS.toml` and `CHECKS.toml` **in both directions** and fails on any asymmetry. Each asymmetry was resolved by deciding **which side was wrong**, not by making the files agree | `ci-registry` PASS with the lint live |
| 4 | **Declarations are not enforcement** | A check marked `implemented` with no executed red run in `tools/ci/self_test.py` now **fails** `ci-registry`. Caught `CI-050` on its first run. Vacuity (a check whose scan set is empty) is now reported separately and excluded from the coverage figure | `vacuous on this tree: CI-007, CI-008` |
| 5 | **`SR-020` computer agency had no acting mechanism** | **Specified, not downgraded.** `SPEC-30`, two contracts, `SM-ENDPOINT-EPISODE`, three decision functions, `INV-ACT-1…6`, `A-051`/`A-052`, and `CI-052/053/054` filed **`PENDING`** because they need a runtime | §8 |
| 6 | **`CI-016` deletion/prefix bypass** | String prefix → **path-component** prefix (`core-notes/` no longer satisfies `core/`); `spec/` and `CODEOWNERS` added to governed surface 6; surface 7's dead `autonomy/triggers/`-only path corrected to cover the shipped registry; CODEOWNERS coverage of every governed path now checked | 4 red runs; `governed-surfaces-integrity` PASS |
| 7 | **`A-029` could be repointed** | `TR-068` added: an acceptance test's target specification must **mention** the test id. Existence is not aboutness | traceability PASS with `TR-068` live |
| 8 | **Artifact existence** | `CI-050` scope extended to the **live COC baselines**, `.github/workflows/` and `CODEOWNERS`; the linter's self-exemption removed; probe tokens assembled from fragments so it can scan itself | 107 normative files, PASS |
| 9 | **Repository never proven to execute** | `git init`; full suite executed from a clean tree; `CI-008` demonstrated blocking a planted `core/probe.py` | §4 |

Two findings were raised by this pass rather than by the brief:

- **`CI-039` named an invariant that did not describe damping.** The missing invariant (`INV-GOV-1`) was **written**, rather than repointing the check at whichever nearby invariant made the registry consistent — which is the `A-029` defect in a different file.
- **Both mutation harnesses were rewriting line endings.** `write_text` converts `\n` to `\r\n` on Windows, so the harness that proves the checks silently modified an LF baseline document while reporting success. Both harnesses are now byte-exact, with SHA-256 assertions around every case. *A verification tool that alters the artifact it verifies invalidates every result taken after it.*

---

## 3. Remaining blockers

| # | Blocker | Class | Blocks | Discharge |
|---|---------|-------|--------|-----------|
| 1 | **`ADR-002` is `PROPOSED`** | `BLOCKED` — owner-reserved | **F0 increment 1**, via `INV-ADR-1`/`CI-008` | Owner or Chief Architect acceptance. `OWNER-DECISION-006(b)` |
| 2 | **`ADR-007` awaits owner ratification** | `BLOCKED` — owner-reserved | Not F0 by `INV-ADR-1`, but `hlc.node_id` provenance stays undefined, so event-envelope work rests on an open decision | `OWNER-DECISION-006(a)` |
| 3 | **`OWNER-DECISION-001`…`006` — one open** | `BLOCKED` | `INV-SELF-2` stays `AWAITING_OWNER_RATIFICATION` | §12 |
| 4 | **Branch protection not enabled; `@owner` is a placeholder** | `PENDING` — host-side | `CI-002`, `CI-044`. **Every governed surface is advisory until this is done** | `SETUP.md`; one GitHub configuration step |
| 5 | **`SPIKE-008` `NOT_STARTED`, and it depends on `SPIKE-001` (`NOT_STARTED`)** | `PENDING` | `docs/spikes/INDEX.toml` records `SPIKE-008` as blocking **`F0 increment 1`** and as the confidence basis for `ADR-002` acceptance | Run `SPIKE-001` then `SPIKE-008` |
| 6 | **41 of 56 checks are `PENDING`** | `PENDING` | Not F0 entry; they are the F1+ gates | They need runtime source to scan |
| 7 | **No acceptance test is executable** | `PENDING` | Nothing | There is no runtime. Stated so that `52 known tests` is never read as `52 passing tests` |

Blockers 1, 2 and 3 are the same owner decision viewed from three files. Blocker 4 is the one most easily mistaken for done: `CODEOWNERS` is complete and correct, and **has no force until branch protection is on**.

---

## 4. Verification evidence

Every command below was run in this pass, against this tree. Nothing in this section is quoted from a prior report.

| Command | Result |
|---|---|
| `python tools/ci/checks.py all` | **11/11 checks passed** |
| `python tools/ci/self_test.py` | **47/47 self-tests behaved correctly** (red under violation, green after restore) |
| `python tools/reference_lint.py` | **PASS**, errors=0 warnings=0, **107 normative files scanned** |
| `python tools/reference_lint.py --self-test` | **5/5 self-tests behaved correctly** |
| `python tools/traceability_lint.py --profile engineering` | **PASS**, errors=0 warnings=0 info=0 |
| `python tools/traceability_lint.py --profile release` | **FAIL**, errors=7 — *correct*, see §6 |
| `python tools/ci/checks.py ci-registry` | **PASS** |

**Recalculated corpus figures** (from `traceability_lint` and `ci-registry` output, not from any document):

| Quantity | Count | Source |
|---|---|---|
| Source requirements (`SR`) | **60** | COC index |
| Design requirements (`DR`) | **31** | COC index |
| Architecture sections / rulebook / IC / A / T / P | 28 / 36 / 10 / 20 / 15 / 10 | COC index |
| Registry rows | **60 SR, 31 DR, 52 known tests, 8 recorded source gaps** | `registry.toml` |
| Invariants | **118** | `spec/invariants/INVARIANTS.toml` |
| CI checks | **56** — 15 implemented, **41 `PENDING`** | `verification/ci/CHECKS.toml` |
| State machines | **12** | `spec/state-machines/INDEX.toml` |
| Decision functions | **33** | `spec/decision-functions/INDEX.toml` |
| Spikes | **9, all `NOT_STARTED`** | `docs/spikes/INDEX.toml` |

**The honest enforcement figure:**

```
ENFORCED TODAY: 15/118 invariants are named by an implemented, bidirectionally
consistent, red-run, non-vacuous check; vacuous on this tree: CI-007, CI-008
18/118 invariants have no CI or mechanism binding at all (acceptance-test prose only)
```

`CI-007` (no product names) and `CI-008` (ADR gate) are **vacuous today** — they scan directory sets that do not yet exist — and are named as such rather than counted. Both stop being vacuous on F0's first commit; see §13.

---

## 5. Negative-control results

A check that has only ever been green is not evidence. Every implemented check is mutated to its declared violation, run, required to exit 1, restored **byte-exactly**, and required to exit 0.

**`tools/ci/self_test.py` — 47/47.** Composition, counted from the harness output:

| Family | Cases | What is proven |
|---|---|---|
| `CI-026` anti-cron | **8** | A predicate **body** replaced with pure cron while the label stays `COMPOSITE` **fails**; a clock term promoted from AND-guard to OR-disjunct **fails**; the backlog trigger **disabled rather than deleted** — the quieter attack — **fails**; an invented clock namespace the vocabulary does not know **fails** |
| `CI-016` governed surfaces | **5** | Surface 6 removed **fails**; surface 6 degraded to string-prefix stubs **fails**; `spec/` dropped — the invariants left editable by the runtime — **fails**; the shipped trigger registry left governed by nothing (S7 path drift plus S1 narrowed) **fails** |
| `CI-008` ADR gate | **4** | F0 code under `core/` while `ADR-002` is `PROPOSED` **fails**; the ADR record flipped while the register disagrees **fails**; a status outside the vocabulary **fails**; and the **discrimination case** — the same F0 code **passes** once `ADR-002` is genuinely `ACCEPTED`, which is what proves the gate keys on the decision rather than on the presence of code |
| `CI-041/043` registry (`checks`) | **5** | An invariant with an empty `enforced_by` **fails**; a check claiming an invariant that does not name it back **fails**; an invariant claiming a check that does not perform it **fails**; an implemented check with no executed red run **fails** |
| `CI-003`/`CI-038`/`TR-*` traceability | **5** | Includes `TR-068`: `A-029`'s spec pointer repointed at an unrelated acceptance file **fails** |
| `CI-050` reference integrity | **5** | Run from both harnesses; see below |
| `CI-034` measured-not-declared | **4** | |
| `CI-046` tunable ranges / `CI-051` latency budgets | **3** each | |
| `CI-030` degradation ladder | **2** | |
| `CI-028` / `CI-007` / `CI-021` | **1** each | one declared-violation case |

**`tools/reference_lint.py --self-test` — 5/5**, including a dangling tool path planted in the **live COC v1.2 additive baseline** and a dangling contract path planted in **`CODEOWNERS`** — the two files most recently added to scope, and both previously unscanned.

**Harness integrity.** Both harnesses read bytes, normalise only for the *match*, restore the original bytes, and assert SHA-256 equality before and after every case. This was added because the previous harness was found silently rewriting `\n` to `\r\n` in a baseline document.

**Controls that do not exist and are not claimed.** No acceptance test has been executed, because there is no runtime. `A-051`'s negative control (*the self-report build* — a system that closes an episode on the actor's own claim of success) is **specified and not run**. `A-029` — externally injected observation at unpredictable timing, the behavioural gate on the anti-cron property — is likewise specified and not run. `CI-026` reports this residual itself: *a state term's relevance is not verifiable without an evaluator.*

---

## 6. Traceability status

- **Engineering profile: PASS**, 0 errors, 0 warnings, 0 info.
- **Release profile: FAIL**, 7 errors, all `TR-027` — `SR-016`, `SR-017` (`DESIGNED`), `SR-023`, `SR-033`, `SR-034`, `SR-035`, `SR-038` (`CONTRACTED`), all below `SPECIFIED`.

**The release FAIL is correct and is deliberately not fixed.** Each of the seven has a recorded depth disposition. A disposition mechanism that converted a FAIL into a PASS would be a mechanism for optimising the verdict; the dispositions record *why* the depth is right, and the profile still fails.

**None of the seven is in F0 scope.** `IMPLEMENTATION_SEQUENCE.md` gates F0 on `A-002`, `A-019`, `A-033`, `A-034`. The SRs whose tests include any of those four are `SR-011`, `SR-019`, `SR-028`, `SR-049`, `SR-058` — **all five are `SPECIFIED`**. The seven release-profile failures test through `A-013`, `A-015`, `A-027`, `A-036`, `A-044`, `A-045`, none of which is an F0 gate. Determined by cross-referencing `registry.toml` against the F0 row of the sequence document, not by inspection.

**New this pass:** `TR-068` closes the direction traceability never checked — a test's target specification must *mention* the test. Previously `A-029` could have been repointed at any existing file and the lint stayed green.

---

## 7. Autonomy and JARVIS-divergence status

**The property:** VESPER acts because the world changed, not because the clock advanced. A system that only wakes on a schedule is a cron job with a language model attached, and must fail.

**Status: ENFORCED, with one named residual.**

`CI-026` reads `contracts/policy/trigger_registry.toml` — a shipped product artifact, not a fixture — and for each of 8 triggers parses the predicate body, classifies every namespace root against a closed vocabulary, and evaluates the predicate with **all clock terms TRUE and all world-state terms FALSE**:

```
8/8 enabled AND proven to require world state to fire
declared/effective: trg_alarm_fire=COMPOSITE/COMPOSITE, trg_fact_expiry_sweep=STATE/STATE,
trg_improvement_backlog=COMPOSITE/COMPOSITE, trg_map_stale=STATE/STATE,
trg_placement_reevaluate=STATE/STATE, trg_proposal_awaiting_review=COMPOSITE/STATE,
trg_reattestation_due=COMPOSITE/COMPOSITE, trg_record_loss_detected=EVENT/EVENT
```

`trg_proposal_awaiting_review` declares `COMPOSITE` and is **effectively `STATE`** — the check reports the declared and derived classes separately rather than accepting the label.

**Both disguises now fail.** A cron-only registry fails. A scheduled prompt wearing a `COMPOSITE` label fails, because the label is not read. Turning the state triggers off and leaving the schedule on fails.

**Residual, stated by the check itself:** whether a state term is *relevant* — whether `map_stale` really tracks the map going stale — is not verifiable without an evaluator. `A-029` is the behavioural gate and is not executable before the runtime exists. This is the honest limit of static analysis on this property.

**Revisit mechanism:** state-driven. `trg_fact_expiry_sweep`, `trg_map_stale` and `trg_placement_reevaluate` fire on world-model conditions, not on a timer.

---

## 8. Computer-agency status

**The requirement (`SR-020`):** VESPER sees screens and **acts on machines**. The loop is perceive → interpret → reason → decide → **act** → observe result → verify → continue or recover.

**What was found:** `SR-020` was `SPECIFIED`, and its trace ran entirely to `semantic_scene.schema.json`, `SM-SENSOR` and `INV-PRIV-4` — capture, sensor indicators and output rendering. **None of them concerns acting.** The perception clause was specified; the agency clause had no subsystem, no decision function, and no contract. The cheap correction — narrow `SR-020` until the existing artifacts covered it — would have converted VESPER into a system that answers questions *about* computers. It was rejected explicitly.

**Status: SPECIFIED (design complete, enforcement `PENDING` on the runtime).**

| Artifact | Content |
|---|---|
| `SPEC-30` in `docs/architecture/SPEC-C-autonomy-and-presence.md` | Computer and device agency, with the Jarvis-divergence clause |
| `contracts/commands/endpoint_interaction.schema.json` | Every action carries `expected_post_condition`, `observation_plan`, `verification_strategy`. `observation_plan.independent_of_actuator` is `"const": true` — structurally, not by convention |
| `contracts/entities/endpoint_surface_state.schema.json` | The perceive half: typed element tree, closed `role` enum, required `valid_until`, `trust_class` fixed to `retrieved_external` |
| `SM-ENDPOINT-EPISODE` (11 states) | Prohibited edges include **`ACTUATED → VERIFIED`** and `OUTCOME_UNKNOWN → CLOSED` |
| `DF-ENDPOINT-ACT` / `DF-ENDPOINT-OBSERVE` / `DF-ENDPOINT-RECOVER` | Act, verify independently, recover |
| `INV-ACT-1…6` | The six invariants of acting on a machine |
| `A-051`, `A-052` in `verification/acceptance/AT-05-intelligence-and-evidence.md` | 10 cases; negative control is **the self-report build**. `A-052` covers injection-and-stop |
| `CI-052`, `CI-053`, `CI-054` | Filed **`PENDING`** — they need runtime source |
| `REM-012` §8a | Required behaviour, invariants, verification, and model/node agnosticism |

**The load-bearing prohibitions:**

1. **`ACTUATED → VERIFIED` is a prohibited transition.** *The actor's report is not the outcome.* A system that treats "I clicked the button" as "the button was clicked" has no closed loop.
2. **An observation captured through the acting path does not close an episode.** `capture_path.actuator_path` is compared against `sensor_id`; `DF-ENDPOINT-OBSERVE` refuses a plan where they are equal.
3. **Screen content is `retrieved_external` by construction.** There is no schema value that lets text read off a machine raise authority. The endpoint is where an injection is most convincing (`INV-ACT-3`, `INV-AUTH-6`).
4. **`OUTCOME_UNKNOWN` is not falsy** and has no edge to `CLOSED`. Retry of a non-idempotent action after an unknown outcome is prohibited.
5. **The target is `node_id` + `surface_class` + `required_capability`** — no model names, no product names.

**Not claimed:** no adapter exists, no episode has been run, `CI-052/053/054` are `PENDING`, and `A-051`/`A-052` are not executable. This is a specification, honestly labelled.

---

## 9. Self-improvement status

**The property:** VESPER may research, experiment, benchmark, write code and propose changes — autonomously and unattended — and may never merge a governed change into a running configuration, and may never rewrite its own authority rules and then use them to approve itself.

**Status: ENFORCED in content, `PENDING` on identity.**

| Path | Status | Held by |
|---|---|---|
| **May work** — research, code, test, benchmark, patch governed surfaces, overnight | ENFORCED | `workspace/` is `L2` unrestricted; `CI-016` fails any build where it is not (`A-030.6`, `SR-042`, `INV-SELF-7`) |
| **May not merge** — no self-merge into a running configuration | **Split** | `CI-016` enforces surface **content**; `CI-044` enforces **reviewer identity** and is `PENDING` on branch protection |
| **May not rewrite the rules and then use them** | ENFORCED this pass | `spec/` was governed by **no surface at all** while `verification/` and `tools/` were inside. Every invariant, state machine and decision function in this system lives under `spec/`. **A runtime that may not edit the test may not edit the property the test checks either.** `CODEOWNERS` added for the same reason |

**Correction of a false record.** `INV-SELF-2` — the self-modification boundary — recorded `CI-016` as its enforcer. `CI-016` is implemented, runs, passes, and **cannot see the property**: content coverage cannot observe a reviewer. That is a green run against a false record, which is worse than an empty one. Corrected to `CI-044`, which is `PENDING`, and the header of `governed_surfaces.toml` was corrected in the same way — it credited `CI-016` with "CODEOWNERS integrity", which has been `CI-044`'s job since the two were split.

**Honest residual:** until branch protection is enabled and `@owner` is a real account, the merge boundary is **documentation**. `CI-016` guarantees the *set of protected paths* is complete and correctly shaped; it cannot guarantee a human approved the change.

---

## 10. Model-agnostic multi-hardware status

**The requirement:** no hard-coded model→hardware binding. Nodes expose dynamic capability profiles; models are resources, not hardware identities. The architecture must remain valid if every current model is replaced.

**Status: ENFORCED at the boundary; vacuous in the code layer, and reported as vacuous.**

- **`INV-HW-1` / `CI-007` (no product names in routing, resource or policy logic).** PASS, with the note: *not yet applicable: no implementation directories exist*. This is **vacuity, not coverage**, and `ci-registry` names it as such. It becomes real on F0's first routing file.
- **Structural agnosticism holds in the artifacts that do exist.** `node_capability_profile.schema.json` is the routing input; targets are `node_id` + `surface_class` + `required_capability`. `endpoint_interaction.schema.json` names no model and no product. `node_id` is a cryptographic identity (`ADR-007`), not a device nickname.
- **`CI-034` (measured, not declared)** reports **13 capabilities, 6 in the survival core, 31 fields honestly `UNKNOWN`** pending `SPIKE-001`/`002`/`007`. The profile is a measurement slot, not a hardware roster.
- **The replacement test.** Substituting every model in the system changes `model_profile` records and routing weights. It changes no invariant, no state machine, no decision function and no contract, because none of them names a model.

---

## 11. Hardware and survival status

**Status: HONEST — specified, unmeasured, and not claimed as measured.**

- **`SPIKE-001`, `SPIKE-002`, `SPIKE-007` are `NOT_STARTED`**, as are all nine spikes. No capability has been invented to fill the gap: `CI-034` reports **31 fields `UNKNOWN`** and would fail a build that declared a value it had not measured.
- **Availability and trust remain separate concepts.** `SM-DEVICE` tracks reachability; `ADR-007` and the trust zones `Z0–Z3` govern authority. A node being reachable does not make it trusted, and this is the property that keeps the survival core from being pinned to whichever machine happens to be on.
- **Placement is not pinned.** `INV-PLACE-1/2/3` and `trg_placement_reevaluate` (a `STATE` trigger) keep placement a continuous decision. `CI-045` (`placement-not-pinned`) is `PENDING` on runtime source.
- **The survival core is bounded and checked.** `CI-034` enforces that it stays small enough to be a survival core: **6 of 13 capabilities**.
- **Latency budgets exist and were set before measurement.** `CI-051` reports the voice chain closing on paper — stages sum to **1000 ms against a 1200 ms end-to-end budget, 200 ms headroom** — across **7 declared paths, `measured = False`**. The arithmetic closing on paper is what makes a later measurement falsifiable.

---

## 12. Owner decisions

`docs/decisions/OWNER_DECISIONS.md`: five resolved, **`OWNER-DECISION-006` OPEN and blocking F0**, re-confirmed OPEN by this pass.

**No owner approval was invented, and no owner-reserved decision was self-accepted.** The gate this pass built (`CI-008`) blocks the work this pass would otherwise proceed to. Accepting `ADR-002` would have discharged it in a single edit. `AUTHORITY_AND_PRECEDENCE §5` reserves the decision, Baseline 02 §16 forbids an agent approving its own security boundary, and **a gate discharged by its own author is not a gate**.

**Decision packet — `OWNER-DECISION-006`:**

| Part | Question | Consequence of the decision |
|---|---|---|
| **(a)** | Ratify `ADR-007` (device identity and trust)? | Security boundary, owner-reserved. Until settled, `hlc.node_id` provenance is undefined and event-envelope work rests on an open decision |
| **(b)** | Accept `ADR-002` (persistence)? | **This is the F0 gate.** `CI-008` blocks every file under `core/`, `tasks/`, `memory/` until it is `ACCEPTED`. `docs/spikes/SPIKE-008-persistence-validation.md` is the recorded confidence basis and is `NOT_STARTED` |
| **(c)** | Extend the ADR namespace beyond `ADR-001…016`, or keep the corrected citations? | Bookkeeping only; recorded because extending a baseline namespace to satisfy a citation would be reinterpretation dressed as bookkeeping |
| *(within (b))* | Re-confirm `ADR-001` and `ADR-012`, stamped `ACCEPTED` in an earlier pass under the same authority question? | Raised inside (b) by both `OWNER_DECISIONS.md` and `ADR-002` §Acceptance authority — **not a separate sub-part id.** Either all three are confirmed together, or the earlier two are re-confirmed on the same basis. One question, answered once |

`OWNER-DECISION-001` remains the ratification of the `INV-SELF-2` non-narrowability clause; `governed_surfaces.toml` carries `ratification_pending` accordingly.

---

## 13. Exact F0 prerequisites

In order. Each is a discrete act with a named owner; none is a judgement call left to the implementer.

| # | Prerequisite | Owner | Why it is before F0, not during |
|---|---|---|---|
| **1** | **Enable branch protection and replace `@owner` with the real account** | Repository owner (host-side) | Until this is done every governed surface is advisory, `CI-002` and `CI-044` cannot leave `PENDING`, and the self-modification merge boundary is documentation. `SETUP.md` has the steps |
| **2** | **Run `SPIKE-001`** (node capability profiles) | Engineering | `docs/spikes/INDEX.toml` records `SPIKE-008` as depending on it, and 31 capability fields are `UNKNOWN` until it reports |
| **3** | **Run `SPIKE-008`** (persistence validation) | Engineering | Recorded as blocking **`F0 increment 1`** and as the confidence basis for `ADR-002`. Atomic epoch fencing and crash-safe checkpoints, **including the non-compliant read-then-write control run** |
| **4** | **Decide `OWNER-DECISION-006`, at minimum part (b): accept or reject `ADR-002`** | Project owner / Chief Architect | **`CI-008` fails the very first commit under `core/`, `tasks/` or `memory/` while `ADR-002` is `PROPOSED`.** This is not a gate discovered later — it is the first thing an F0 engineer trips. Acceptance must precede the first file, not follow it |
| **5** | **Decide `OWNER-DECISION-006(a)`: ratify `ADR-007`** | Project owner | Not blocked by `INV-ADR-1`, but F0 builds the event bus, and `hlc.node_id` provenance is undefined until this is settled. Deciding it after the envelope is written means rewriting the envelope |
| **6** | **Re-run the full suite on the post-acceptance tree** | Engineering | `CI-008` and `CI-007` are **vacuous today**. On F0's first commit both stop being vacuous simultaneously — `CI-008` because `core/` becomes non-empty, `CI-007` because routing logic starts to exist. Neither has ever run against a populated tree, only against planted-file scenarios |

**F0 scope, for the avoidance of drift** (`docs/architecture/IMPLEMENTATION_SEQUENCE.md`, row F0/R0): runtime supervisor, config, telemetry, event bus, durable task state, checkpoints, persistence abstraction, policy skeleton. **Exit criterion:** `A-002`, `A-019`, `A-033`, `A-034` pass **with their negative controls recorded**. All five SRs gated by those four tests are `SPECIFIED`.

**What F0 must not do:** write to any of the nine governed surfaces from runtime code; treat `Result.status = "unknown"` as a failure or a success; emit an effect before the outbox record; or add a `SCHEDULE`-only row to the trigger registry.

---

## 14. Final independent reasoning pass

> *Could an engineer start F0 tomorrow and reasonably discover a hidden architectural, authority, verification, model/hardware, autonomy, or requirement blocker that this repository currently claims does not exist?*

Answered by category, against the tree rather than against its documentation.

| Category | Could a hidden blocker surface? | Basis |
|---|---|---|
| **Architectural** | **No.** F0's subsystems have contracts, state machines and decision functions; the persistence design has an ADR. The *risk* — that the storage design fails under fencing or crash — is named, sized and owned as `SPIKE-008`, and is a prerequisite in §13, not a discovery |
| **Authority** | **No, and it is unmissable.** `CI-008` fails the first F0 commit. An engineer cannot get three days in before finding it; they cannot get one file in |
| **Verification** | **Reduced, not eliminated.** Nine label-only or scope-hole defects were found and closed with permanent red runs, and the lint that would have caught most of them now exists. But **41 of 56 checks are `PENDING` and no acceptance test is executable** — that is stated everywhere, including in the coverage figure, so it is a known absence rather than a hidden one |
| **Model / hardware** | **No, with a stated unknown.** No model→hardware binding exists to discover. 31 capability fields are `UNKNOWN` and labelled `UNKNOWN`; `SPIKE-001` is prerequisite 2 |
| **Autonomy** | **No for the static property; yes for the behavioural one, and it is declared.** The clock-alone test is enforced against the shipped registry. Whether a state term tracks the thing it names needs `A-029` and an evaluator. `CI-026` says this in its own output |
| **Requirement** | **No.** The one requirement found without a mechanism (`SR-020` agency) was specified rather than narrowed. The release profile still fails on seven SRs by design, and none of the seven is in F0 scope |

**The residual risks, stated plainly, because a report that lists none is not honest:**

1. **The branch-protection gap is the largest one and it is not a code problem.** `CODEOWNERS` is complete; it has no force until a human enables protection. Anyone reading the corpus can mistake a correct `CODEOWNERS` for an enforced one.
2. **`CI-008` and `CI-007` have never run against a populated tree.** They are proven against planted-file scenarios in both directions, which is the strongest evidence available before code exists — and it is not the same as having run.
3. **The anti-chatbot property is enforced structurally and unproven behaviourally.** No triggered episode has ever executed.

4. **`.github/workflows/ci.yml` has never run.** There is no remote and no CI host, so every result in this report was produced by invoking the tools directly. The workflow's interpreter pin was `3.12` while all evidence was gathered on **3.14**; the pin has been corrected to name the version the evidence was actually produced on, but that is a correction, not a verification. The first push to a host will be the first execution of this file, and it should be treated as such.
5. **`SPIKE-008` is the one place where an F0 engineer could still be genuinely surprised** — not by a missing artifact, but by the ADR-002 design failing its own validation. That is a design risk with a named, sized, owned experiment in front of it. Which is what a spike is for.

None of these is a claim this repository makes and cannot support. Each is recorded, in the tree, in the artifact that owns it.

---

## 15. Verdict

> # `BUILD_AFTER_CORRECTIONS`

**Why not `BUILD`.** `ADR-002` is `PROPOSED` and `CI-008` — a check this pass implemented and proved in both directions — blocks F0's first commit. `OWNER-DECISION-006` is OPEN. Branch protection is not enabled, so `CI-002` and `CI-044` are `PENDING` and every governed surface is advisory. `SPIKE-001` and `SPIKE-008` are `NOT_STARTED`, and `SPIKE-008` is recorded as blocking F0 increment 1. Each of these is an act reserved to someone other than this auditor, and discharging any of them here would be the exact defect this pass spent its time finding: **a gate satisfied by the party it constrains.**

**Why not `DO_NOT_BUILD`.** Nothing found requires redesign, and all eleven defects are closed. They close in four different ways, and the difference matters:

| Defect | Count | How it is closed | Red run today? |
|---|---|---|---|
| Verification defects — `CI-026` semantics, `CI-016` bypass, `CI-008` unimplemented, one-directional registry, no red-run coverage, `TR-068` aboutness, `CI-050` scope | **7** | Check corrected or written | **Yes**, permanent, in `self_test.py` |
| Registry-correctness defect — `CI-039` naming an invariant that did not describe damping | **1** | `INV-GOV-1` written | **No** — `CI-039` is `PENDING`. Held by the bidirectional lint, which does have one |
| Requirement gap — `SR-020` computer agency | **1** | **Specified**, not narrowed | **No** — `CI-052/053/054` are `PENDING` on the runtime |
| Harness-integrity defect — both harnesses rewriting line endings | **1** | Byte-exact read/restore, SHA-256 asserted around all 47 cases | n/a — it is what makes the other red runs trustworthy |
| Repository-executability gap — the suite had never been proven to run anywhere | **1** | `git init`; full suite executed from a clean tree | n/a |

Two of the eleven therefore have **no red run of their own and are not claimed to**. The blockers are six enumerable acts, ordered, each with a named owner. The architecture survives model replacement, is not pinned to one machine, keeps availability and trust separate, and keeps autonomy state-driven and self-improvement human-gated at merge.

**What this verdict means operationally.** Do the six prerequisites in §13, in order. Then re-run the full suite on the post-acceptance tree and read `ENFORCED TODAY` again. If it has not moved, F0 has added code without adding enforcement, and that is the next thing to fix.

The corpus is not green because it was made to look green. `ENFORCED TODAY` fell from a figure that counted checks to **15/118**, which counts only checks that are implemented, consistent, red-run and non-vacuous. That number is the one worth defending.

---

*Preserved unchanged by this pass: `docs/WORK_REPORT_2026-08-12.md` above its dated addendum, `docs/FINAL_VERIFICATION_REPORT.md`, and every prior section of `docs/DECISION_LOG.md`. Historical reports record what was believed at the time; overwriting them would destroy the only evidence of how these defects survived two passes.*
