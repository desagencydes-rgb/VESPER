# VESPER — Final Pre-Implementation Verification Report

**Date:** 2026-08-12
**Scope:** Independent adversarial verification of the VESPER engineering foundation prior to F0.
**Method:** Every load-bearing claim checked against the artifact it names. Every runnable gate executed. Independent negative controls injected — deliberately chosen as mutations the repository's own self-tests do **not** enumerate — then restored and verified byte-identical by SHA-256, with a full recursive `diff` against a pre-probe backup at the end.
**Authority applied:** handwritten source → COC/Rulebook v1.1 + v1.2 additive → owner decisions → engineering foundation → derived requirements → contracts/state machines/decision functions → acceptance tests/CI → prior reviews (evidence only, never authority).

> This report reaches a verdict on **readiness to begin F0**. It does not authorise F0; that remains the owner's act.

---

## 1. Executive verdict

**`BUILD_AFTER_CORRECTIONS`.**

The architecture is sound. I attempted to find a structural contradiction, an architectural failure, or a requirement gap that could not be closed by writing a missing artifact or implementing a declared check. **I did not find one.** The plane decomposition, the Event/Command/Result separation, the authority-axis separation, the dead-man's-switch stop design, the leased state-ownership model, and the three newest requirement areas (opportunistic placement/survival, improvement backlog, record-loss continuity) are all correctly conceived and correctly bounded. VESPER as specified is **not** a conventional LLM + memory + tools + UI assistant, and an implementation agent following these documents would find the chatbot path blocked at several independent points.

The corpus is also **honest about its own state**, which is the rarest property in a document set this size. Every `READY TO BUILD` string in the repository is part of a *withdrawal*, not a live claim. The readiness report explicitly refuses to record a verdict. `--profile release` fails, deliberately, and the failure is described as correct rather than explained away. I confirmed all of that directly.

What blocks F0 is a specific, closeable set:

1. **`ADR-002` is `PROPOSED`, and `INV-ADR-1` makes it a hard merge gate for `core/`, `tasks/` and `memory/` — which is exactly F0.** Disclosed and correct.
2. **There is no git repository, so no CI check has ever gated anything.** Disclosed — but its consequence is not: the sole named F0 blocker (`INV-ADR-1`) is enforced by `CI-008`, which is `PENDING`. Nothing mechanical prevents F0 code landing under `core/` today.
3. **Three false enforcement records survive in the registries** — including one on a ratified security clause (`INV-SELF-2`) that points at an *implemented, passing* check which does not test it. This is the `CI-022` defect class, and its recurrence inside the registry the second pass rebuilt is the single most important finding in this report.

None of these is structural. All are correctable. The verdict is `BUILD_AFTER_CORRECTIONS`, with the exact minimum list in §14.

---

## 2. Repository and artifact integrity

Every headline count in `VESPER_ENGINEERING_STATUS.md` and the readiness report was recounted from the artifacts. **All are true.**

| Claim | Verified | Method |
|---|---|---|
| 26 JSON Schemas | ✅ 26 | `find contracts -name '*.json'` |
| 8 policy contracts | ✅ 8 | `find contracts/policy -name '*.toml'` |
| 11 state machines | ✅ 11 | `spec/state-machines/INDEX.toml` |
| 30 decision functions | ✅ 30 | `spec/decision-functions/INDEX.toml` |
| 111 invariants | ✅ 111 | `spec/invariants/INVARIANTS.toml` |
| 50 acceptance tests | ✅ 50 | `verification/acceptance/INDEX.toml` |
| 53 CI checks, 14 implemented | ✅ 53 / 14 | `tools/ci/checks.py status` |
| 60 SRs | ✅ 60 | traceability lint COC index |
| 29 subsystems, each with a Jarvis-divergence field | ✅ 29 / 29 | `SPEC-A..D` section count |
| 8 spikes, 31 hardware fields `UNKNOWN` | ✅ | `docs/spikes/INDEX.toml`, `capability_profiles.toml` |
| 8 triggers shipped, 0 `SCHEDULE`-class | ✅ | `CI-026` run output |
| 47 tests name a negative control, 3 record why one cannot exist | ✅ 47 + 3 | `negative_control` / `negative_control_rationale` fields |

**ADR statuses verified in the files themselves**, not in the register alone: `ADR-001` **ACCEPTED**, `ADR-002` **PROPOSED**, `ADR-007` **PROPOSED**, `ADR-012` **ACCEPTED (bounded)**. The register matches all four. `OWNER-DECISION-006` is **OPEN**. The `ADR-017…020` retirement is correctly recorded and `reference_lint` correctly still rejects *new* references to them.

**No dangling references exist today.** `reference_lint` scans 99 normative files and reports 0 errors; all 50 acceptance-test `spec` pointers resolve to files that genuinely contain the test id (I checked all 50 by content, not by path existence). The 13 previously-missing contracts and the missing `ADR-002` are all present.

**Anti-self-deception scan.** I grepped the corpus for `READY`, `PASS`, `COMPLETE`, `VERIFIED`, `IMPLEMENTATION READY`, `BUILD`, `SPECIFIED` and traced each important occurrence to its evidence. `READY TO BUILD` appears in four files (`IMPLEMENTATION_READINESS_REPORT.md`, `DECISION_LOG.md`, `WORK_REPORT_2026-08-12.md`, `VESPER_ENGINEERING_STATUS.md`) and **in every case it is the withdrawal being recorded**, never a live assertion. `VERIFIED` in `registry.toml` is a status-vocabulary definition, not a claim about any SR. No SR carries `VERIFIED` or `IMPLEMENTED`. I found **no false readiness claim** anywhere in the corpus.

---

## 3. Requirement traceability verdict

**Verdict: SOUND AS A MAP, WEAK AS A GATE.**

The chain SOURCE → SR → architecture → mechanism → contract → acceptance test → CI is complete as a *declared* structure and the linters genuinely validate most of it. I ran all of them and reproduced every published figure:

```
tools/traceability_lint.py                    PASS  0 errors, 0 warnings, 0 info   (exit 0)
tools/traceability_lint.py --profile release  FAIL  7 errors, DEPTH only           (exit 1)
tools/reference_lint.py                       PASS  0 errors, 99 files             (exit 0)
tools/reference_lint.py --self-test           PASS  2/2 red-then-green             (exit 0)
tools/ci/checks.py all                        PASS  10/10 runnable                 (exit 0)
tools/ci/self_test.py                         PASS  25/25 red-then-green           (exit 0)
tools/ci/checks.py status                            14/53 implemented, 39 PENDING
```

`--profile release` genuinely exits **1** and fails on depth only (SR-016, 017 `DESIGNED`; SR-023, 033, 034, 035, 038 `CONTRACTED`). The recorded dispositions do **not** convert the FAIL into a PASS — I verified this specifically, because it is the mechanism most likely to have been used to optimise a verdict. It has not been.

**SR status distribution (verified):** 48 `SPECIFIED`, 2 `DESIGNED`, 5 `CONTRACTED`, 1 `PARTIAL_R_AND_D`, 3 `R_AND_D`, 1 `EXCLUDED_BY_SAFETY_POLICY`.

**Where the chain is weaker than it reads:**

- **45 of 60 SRs have no implemented CI check** behind them. 18 SRs carry no `ci` field at all. This is not hidden, but no document states it at SR granularity.
- **The SR → acceptance-test link is validated by file existence, not by content.** `TR-062` checks that the named `spec` file exists. It does not check that the file mentions the test. I proved this by repointing **`A-029`** — the single most important run in the programme — from `AT-03-autonomy-and-cost.md` to `AT-04-presence-and-perception.md`, a file that never mentions `A-029`. **Traceability lint stayed PASS with 0 errors.** This is a latent hole, not a live defect: all 50 pointers are currently correct.

---

## 4. Architecture verdict

**Verdict: PASS.** The runtime genuinely supports `observe → interpret → decide → act → verify → learn` without a user message as the initial trigger.

| Requirement | Mechanism | Status |
|---|---|---|
| Persistent runtime | SPEC-01, pinned artifact + content hash at every start | Specified |
| Event bus | SPEC-03, `event_envelope.schema.json`, HLC ordering (`ADR-001`) | Specified |
| Durable state | `ADR-002` (**PROPOSED**), `task.schema.json`, `checkpoint.schema.json` | Specified, **gate open** |
| Checkpoints / task persistence | `SM-TASK`, `checkpoint.schema.json`, outbox cursor | Specified |
| Recovery | SPEC-24 — resume replays from outbox cursor, no duplicate external effect | Specified |
| Autonomy | SPEC-12, `DF-AUTONOMY-ELIGIBLE`, `autonomy_enable_token.schema.json` | Specified |
| Triggers | SPEC-13, `SM-TRIGGER`, `DF-TRIGGER-EVAL`, shipped registry of 8 | Specified + partly enforced |
| Interruption / attention | SPEC-14, `interruption_budget.toml`, preparation unbudgeted | Specified |
| Verification | `DF-VERIFY-SELECT`, `INV-VERIF-1` (a worker's claim is not a transition) | Specified |
| Failure handling | SPEC-29, `Result.status = "unknown"` as first-class | Specified |

The decisive structural choices are correct and load-bearing:

- **`SM-TASK` prohibits `RUNNING → SUCCEEDED`.** A worker's claim of completion is not a state transition. This single prohibition is what prevents the whole system degrading into "the model said it worked."
- **`Result.status = "unknown"`** is a first-class outcome, so a crash mid-external-call is representable without coercion to success or failure.
- **`SM-WORLD-FACT` has no edge from `UNKNOWN` yielding a prior value**, and `UNKNOWN` is a state a fact *transitions into* at a declared TTL. `UNKNOWN` is not falsy; a predicate over `UNKNOWN` does not fire.
- All **11 state machines carry explicit prohibited edges**, which is the load-bearing half.

---

## 5. JARVIS divergence verdict

**Verdict: PASS at the specification layer. THIN at the enforcement layer.**

All 29 subsystems carry a Jarvis-divergence field, and — this is the part I expected to fail and did not — **the fields name specific clauses and specific tests, not prose reassurance.** Representative, verified verbatim:

- **Semantic scene:** `INV-SCENE-3`, no markdown escape hatch. "A chat UI's output *is* markdown; it carries no typed structure from which a narration could be derived." Backed by `A-009` (voice-only diagram narration) and `A-026` (boot with no text surface).
- **Trigger evaluation:** "the evaluator runs in a sandbox with no model capability, and the violation is observable (`INV-TRIG-2`)." A chatbot-with-a-scheduler decides to act by calling a model; `A-011.4` detects that at runtime.
- **Core control loop:** `INV-AUTO-1`, a heartbeat every cycle whose absence is an incident. "The heartbeat is what makes 'quiet' distinguishable from 'dead'."
- **Multimodal perception:** `INV-PRIV-4`, a sensor refuses to capture when its indicator cannot be driven, and the guaranteed-off path is physical.
- **Recovery:** a task must survive the death of its machine *and* not re-send the email it already sent.

**The enforcement picture is much thinner than the specification picture.** I classified all 111 invariants by what actually enforces them today, reconciling both directions (an invariant's `enforced_by`, and each check's `enforces`):

| Enforcement reality | Count |
|---|---|
| Enforced today by an implemented CI check **that also names the invariant back** | **11** |
| CI check specified but `PENDING` | 39 |
| Design mechanism only (`SM-`/`DF-`), nothing executable | 35 |
| Acceptance-test prose only, no CI and no mechanism binding | 18 |

The 18-figure matches `checks.py ci-registry` exactly, confirming that tool is honest. But **the 11 figure appears nowhere in the corpus.** The published framing is "14 of 53 checks implemented," which is true and much more flattering than "11 of 111 invariants are actually enforced."

Divergence-critical subsystems, by what defends them **today**:

| Property | Clause | Defended today by |
|---|---|---|
| Semantic scene (no markdown) | `INV-SCENE-3` | ✅ `CI-028` implemented + red-verified |
| Degradation ladder completeness | `INV-SCENE-2` | ✅ `CI-030` implemented + red-verified |
| Hardware measured-not-declared | `INV-HW-2`, `INV-PLACE-3` | ✅ `CI-034` implemented, 4 red runs |
| Anti-cron / autonomy | `INV-AUTO-5`, `INV-IDEA-5` | ⚠️ `CI-026` — **label only**, see §12 |
| Trigger evaluator holds no model | `INV-TRIG-2` | ❌ `CI-023` PENDING |
| World model `UNKNOWN` | `INV-COORD-2` | ❌ `A-033` only, cannot run |
| External observation ingress | `INV-AUTO-4` | ❌ `A-029` only, cannot run |
| Memory authority | `INV-MEM-1` | ❌ `DF-MEMORY-AUTHORITY` design only |
| Presence endpoint fail-safe | `DF-SELECT-ENDPOINT` | ❌ `A-010` only |
| Taint / injection | `INV-AUTH-3/6/7` | ❌ `CI-012`, `CI-014` PENDING |
| Learning boundary | `INV-LEARN-1` | ❌ `CI-036` PENDING |
| Distributed ownership | `INV-OWN-3` | ❌ `CI-009` PENDING |
| Migration / placement | `INV-PLACE-1/2` | ❌ `CI-045` PENDING |
| Model routing | `INV-HW-1` | ⚠️ `CI-007` implemented but **vacuous** — no `routing/` dir exists yet |

**This is expected and not a P0.** Most of these need source code that does not exist. The finding is not that they are unenforced; it is that the corpus's own summary figures make enforcement look broader than 11/111.

**Notably, `INV-AUTO-4` — the invariant the readiness report's strongest autonomy claim rests on ("`INV-AUTO-4` makes the external observation ingress a *production architectural requirement*") — is in the acceptance-test-prose-only class.** No CI check and no state machine or decision function names it. It rests entirely on `A-029`, which cannot run, and whose spec pointer I showed is not content-validated.

---

## 6. Autonomous computer-agency verdict

**Verdict: PERMITTED, NOT SPECIFIED. P1.**

The original handwritten source is unambiguous that this is required — *"self interact everywhere in all available hardwares"*, *"run & execute code/scripts/commands"*, *"researching & taking action on computer"*, *"ability to call / facetime on my behalf… send messages, take notes in note app, set up calendar"*. It is carried by **`SR-020`** (*"Speak, listen, see space through cameras, see screens, self-interact across available hardware"*) and **`SR-030`** (*"…research, and computer action"*).

**The architecture does not collapse into `user request → LLM response → tool call`.** Command issuance sits downstream of the trigger/autonomy layer, `DF-ACTUATION-GATE` sits between the autonomy engine and every actuator, `INV-VERIF-1` forbids treating the actor's claim as the outcome, and `INV-EXT-1` requires an outbox record before any external effect. The `see → … → adapt` loop exists in fragments: `A-008` (screen content with provenance/confidence) → world model → autonomy/task planning → `A-013` (capability-controlled execution) → `DF-VERIFY-SELECT` (result verified independently of the actor's claim) → `SM-IDEA`/learning.

**But the substrate is unspecified.** Of 29 subsystems, **none** covers acting on a computer. Of 30 decision functions, **none** governs endpoint interaction. `ADR-006` (tool sandbox) is `DEFERRED` — legitimately, to before R1.

The specific defect: **`SR-020` is marked `SPECIFIED`, yet its agency clause traces only to perception and presentation artifacts** — `semantic_scene.schema.json`, `SM-SENSOR`, `INV-PRIV-4`. `SM-SENSOR` is capture; `INV-PRIV-4` is sensor indicators; `semantic_scene` is output rendering. **Nothing in `SR-020`'s traced set covers "self-interact."** The one artifact that does is `A-013` — *"Capability-controlled computer interaction," gate R1* — whose entire specification is four sentences asserting that `shell.run("ls")` and `shell.run("rm -rf ~")` resolve to different levels through `declared_level(args)`.

That assertion is correct and valuable, but it is authorization, not agency. `SR-020`'s `SPECIFIED` status overstates its depth — it would more honestly sit at `CONTRACTED` with a depth disposition naming an endpoint-interaction contract, exactly as `SR-023` and `SR-035` do. This is **not structural**: `Command`/`Result`, the outbox, the trust zones and `ADR-006` leave a clean, correctly-shaped slot for it.

---

## 7. Distributed-survival verdict

**Verdict: PASS — the strongest recent work in the corpus.**

`REM-014` / `SR-060` genuinely resolves a real architectural error rather than papering over it. The insight is that **trustworthiness and availability are different axes**, and conflating them produced a rule excluding the iPhone from continuity entirely. The correction is precise: the iPhone is `Z0` (Secure Enclave, fully trustworthy) but `foreground_only` (iOS background limits), so it is excluded only from being the **planned sole home** of a continuity-critical capability — **not** from hosting survival when it is all that remains. `REM-014` states the principle exactly right:

> *"Ceasing to exist because the preferred hardware is missing is a failure, not a degradation."*

| Concern | Mechanism | Verified |
|---|---|---|
| State ownership | 7 leased domains, one holder each, `SM-LEASE` | ✅ |
| Leases / fencing | `lease_epoch` fencing at the storage layer | ✅ |
| Ordering | HLC envelopes, `INV-COORD-4` (no wall-clock ordering) | ✅ |
| Partitions | `DF-PROMOTE` — never automatic on partition alone; no quorum → refuse, degrade read-only | ✅ |
| Stale state | `INV-COORD-2` — past `valid_until` the only readable value is `UNKNOWN` | ✅ |
| Conflict resolution | `DF-CONFLICT-DETECT`, `DF-SUPERSEDE`, `DF-DOMAIN-WRITE` | ✅ |
| Migration | `DF-PLACE`, `SPEC-20`, `trg_placement_reevaluate` (STATE-class) | ✅ |
| Node failure / disappearance | `SPEC-29`, re-attestation expiry demotes and emits degradation | ✅ |
| Partial availability | `DF-SURVIVAL-PROFILE`, 13 capabilities, **6 in the survival core** with memory floors | ✅ |
| iPhone constraints | `availability_class = foreground_only`, `SPIKE-007` | ✅ specified, unmeasured |
| Security boundaries | `Z0–Z3` trust zones, `INV-TRUST-1` (`Z2` may not hold state or receive secrets) | ✅ |
| Anti-flap | `INV-PLACE-2` — minimum dwell time + relocation gain threshold | ✅ |

`A-048` carries two negative controls: a node-pinned build **and** an undamped build that flaps. `CI-034` red-verifies that unmeasured capabilities are treated as **unavailable**, not available — I confirmed all 4 of its red runs execute.

**Residual (correctly disclosed):** `CI-045` (`placement-not-pinned`) is `PENDING`; all 31 hardware figures are `UNKNOWN` pending `SPIKE-001/002/007`.

---

## 8. Self-improvement verdict

**Verdict: PASS on design. Both paths exist and are correctly bounded.**

**Path A — working improvement.** Four layers of defence, in trust order: (1) deployed artifact ≠ working repository (`ADR-012` D1, content hash at start); (2) OS filesystem capability set excludes `GOVERNED_PATHS` — *enforced by capability, not policy text* (`INV-SELF-4`); (3) `DF-AUTHORIZE` denies `L5` to `subject.kind == runtime`, always, including under a valid `L5` grant and under break-glass (`INV-SELF-3`); (4) model disposition. The corpus previously had only layer 4 — the layer prompt injection defeats. Nine governed surfaces, including **surface 6: the tests and CI themselves**.

**The boundary is on merge, not on work** — this is the part most implementations get wrong in the other direction, and it is correct here. `INV-SELF-7` makes workspace activity unrestricted; `A-030.6` requires the runtime to write a complete patch to `policy/`, test it, and file a proposal **at 03:00 with nobody present — and succeed**. Its negative control is a build adopting PATCH-018 as literally worded, which must **fail**. That red run is the evidence the correction did not over-restrict `SR-042`. `SM-PROPOSAL` prohibits any transition to `MERGED`/`PROMOTED` by a runtime author, and `change_proposal.schema.json` makes `MERGED` structurally unwritable by one.

**Path B — idea/thesis backlog.** `SM-IDEA`, `DF-IDEA-REVISIT`, `improvement_idea.schema.json`, `INV-IDEA-1..6`, `A-049`. The design is event-driven for proposals and state-driven for the backlog, as required:

- `INV-IDEA-1` — an idea is logged **the moment it arises**, with provenance; never held only in model context.
- `INV-IDEA-2` — the backlog is runtime-owned and freely writable; logging an idea *about* a governed surface is unrestricted.
- `INV-IDEA-3` — an idea maturing into a governed change traverses the **same** proposal path. The backlog is never a shortcut.
- `INV-IDEA-4` — retirement requires a `disposition_reason`; no idea leaves silently.
- `INV-IDEA-6` — **idle time expands available time, never authority.** Resource budget, cost policy, enable token and taint ceiling apply to backlog work unchanged.

`INV-IDEA-6` is the clause that makes overnight autonomy safe rather than merely permitted, and it is correctly stated.

**Enforcement residual:** `CI-047` (`idea-retirement-reason`) is `PENDING`; `CI-015`/`CI-017` are `PENDING`; `A-030` and `A-049` cannot run. See §12 for the `CI-026` backlog-trigger gap and §9 for the `INV-SELF-2` defect, both of which touch this area.

---

## 9. Security verdict

**Verdict: DESIGN SOUND. ENFORCEMENT ABSENT TODAY — expected. One false enforcement record, which is not expected.**

Attack-surface review against the design:

| Attack | Defence | Enforced today |
|---|---|---|
| Prompt injection | `INV-AUTH-3` taint through summarisation/embedding/cache; `DF-CONTEXT-CEILING` | ❌ `CI-012` PENDING |
| Indirect injection | `INV-AUTH-6` — planner context **never** contains a `retrieved_external` fragment; enforced structurally in `context_fragment.schema.json` | ❌ `CI-014` PENDING |
| Malicious file / webpage / tool output | `trust_class` propagation; `DF-CACHE-ADMIT` under taint | ❌ PENDING |
| Compromised device | `Z0–Z3`, `INV-TRUST-1`, re-attestation, `SM-DEVICE` prohibits `DISCOVERED → TRUSTED` | ❌ `CI-035` PENDING |
| Privilege escalation | `INV-AUTH-0` — no conversion between `L`/`E`/`Z` axes by any automated process | ❌ `CI-006` PENDING |
| Confused deputy | `DF-AUTHORIZE` argument-sensitive: `effective_level = min(grant, declared_level(args), context_ceiling)`; `DF-ATTENUATE` on agent spawn | ❌ `CI-011`/`CI-013` PENDING |
| Credential exposure | `INV-OBS-1`, sensitive payloads structurally cannot be inline | ❌ `CI-040` PENDING |
| Autonomous unauthorized action | `INV-TRIG-1` (no action without `trigger_id`), enable token per action | ❌ `CI-025` PENDING |
| Chained low-risk actions | `context_ceiling` + per-action token; `INV-IDEA-6` | ❌ |
| Hallucination causing real action | `INV-VERIF-1` — a worker's claim is not a transition; `DF-VERIFY-SELECT` | ❌ |
| Self-modification | 4 layers (§8); `INV-SELF-1..7` | ⚠️ see below |
| Policy circumvention | `INV-SELF-2` non-narrowability, ratified as COC v1.2 Part VII-A | ❌ **falsely recorded as enforced** |
| Emergency-stop failure | dead-man's switch (§11) | ❌ `CI-018`/`CI-019` PENDING |

**The design does not rely on prose.** `INV-AUTH-7` is a good example of correct thinking: an above-ceiling action becomes a **queued proposal** with `security.injection_suspected` emitted — *never silently dropped*. Schemas encode invariants structurally rather than by comment: an autonomous command without `trigger_id` and `enable_token_id` is malformed; `L4`/`L5` grants cannot be `delegable`; `declared_level_rules` requires ≥2 entries so a constant is unexpressible.

**The one real security finding — `INV-SELF-2`.** See F-P1-1 in §12. The non-narrowability clause, ratified into the COC, records `enforced_by = ["CI-016", "A-030"]`. `CI-016` is **implemented and passing**, so the registry reads as though this clause is defended today. It is not: `CHECKS.toml` assigns `INV-SELF-2` to **`CI-044`**, which is `PENDING` and requires git history that does not exist. `CI-016` tests governed-surface *content* and the `L2` workspace level; it contains no non-narrowability logic. **A ratified security clause carries a false enforcement record pointing at a green check.**

---

## 10. CI and acceptance-test verification results

Every runnable gate was executed. **I did not trust any check because its code exists.** For the load-bearing ones I injected violations the repository's own self-tests do **not** enumerate.

### 10.1 Declared self-tests — all genuinely execute

`tools/ci/self_test.py` mutates each artifact to its declared violation, requires exit 1, restores, requires exit 0: **25/25 correct.** `reference_lint --self-test`: **2/2.** These are real red runs, not declarations. The `CI-016` direction defect the second pass reported is genuinely fixed — I re-verified it (probe G2: deleting surface 6 goes red with the correct error).

### 10.2 Independent negative controls — my own, not theirs

Harness validated first: two positive controls in an in-scope directory both went red correctly (`RF-010`, `RF-022`), so a GREEN below means a genuine blind spot, not a broken probe. Every mutation was restored and the whole tree verified byte-identical by recursive `diff` afterwards.

| # | Independent mutation | Gate | Result |
|---|---|---|---|
| 1 | Dangling tool path planted in the **live COC v1.2 additive** | `CI-050` | 🔴 **GREEN — gap.** `docs/COC/` is excluded from scan scope |
| 2 | `ci.yml` told to run `tools/ci/checks_MISSING.py` | `CI-050` | 🔴 **GREEN — gap.** `.github/` is not scanned at all |
| 3 | `predicate_class = "STATEX"` (outside enum) | `CI-026` | ✅ RED — correct |
| 4 | **All** triggers `enabled = false` | `CI-026` | ✅ RED — correct |
| 5 | **`trg_improvement_backlog` alone disabled** | `CI-026` | 🔴 **GREEN — gap.** `INV-IDEA-5`'s load-bearing row can ship switched off |
| 6 | **Backlog predicate replaced with `schedule.cron("0 3 * * *")`, class left `COMPOSITE`** | `CI-026` | 🔴 **GREEN — gap.** Reported "8/8 enabled and non-SCHEDULE" |
| 7 | Surface 6 paths degraded to `["v", "t"]` | `CI-016` | 🔴 **GREEN — gap.** String-prefix, not path-prefix |
| 8 | Surface 6 deleted outright (the recorded defect) | `CI-016` | ✅ RED — correct, fix holds |
| 9 | **`A-029` spec repointed to an unrelated file** | `CI-003` | 🔴 **GREEN — gap.** Existence checked, content not |

**Probe 6 is the most consequential.** `CI-026` validates the `predicate_class` *label*, never the predicate *semantics*. A registry in which every predicate body is a cron expression, with every row labelled `COMPOSITE`/`STATE`, passes the anti-cron gate and prints `8/8 enabled and non-SCHEDULE`. That build **is** the `C1` pure-cron negative control. The readiness report states `CI-026` is *"implemented and red-verified against the C1 cron build"*; it is red-verified against **class relabelling only**, which is what the declared self-test mutates.

To be fair to the design: `CI-026` arguably cannot do better before a predicate evaluator exists, and the genuine `C1` control properly lives in `A-029`. The defect is the **claim**, not the check's ambition. But it means the anti-cron property has **no mechanical defence today** — only a naming convention.

### 10.3 CI wiring

- `.github/workflows/ci.yml` names only the checks each step actually runs — the discipline it declares, it keeps. The unusual `checks.py scene-no-escape-hatch --self-test` invocation is genuinely supported (verified: prints `injected markdown field would be detected = True`).
- **`ci.yml` never runs `--profile release`.** The depth gate that correctly exits 1 blocks nothing mechanically. Defensible (it is a release gate) but worth stating.
- **The workflow has never executed.** There is no git repository — `git status` returns *"not a repository"*, and `.git` does not exist. Every CI enforcement claim in the corpus is, today, unexercised as a gate.

### 10.4 Acceptance tests

All 50 are **specifications, not executables**, as the corpus states plainly. 47 name a wrong build that must fail; 3 carry a `negative_control_rationale` (verified — the claim is true). The two decisive gates, `A-029` and `A-031`, cannot run before the autonomy engine and interlock exist. `CI-027` correctly blocks the autonomy release without `A-029`'s recorded `C1` failing control.

---

## 11. F0 prerequisite audit

| Prerequisite | State | Blocking? |
|---|---|---|
| **`ADR-002` ACCEPTED** | **`PROPOSED`** | 🔴 **YES** — `INV-ADR-1` |
| `ADR-001`, `ADR-012` ACCEPTED | ✅ both ACCEPTED | No (acceptance-authority asymmetry recorded, unresolved) |
| `ADR-007` ratified | `PROPOSED`, owner-reserved | Not by `INV-ADR-1`, but `hlc.node_id` provenance stays undefined |
| `OWNER-DECISION-006` (a)(b)(c) | **OPEN** | 🔴 **YES** |
| F0 contracts exist (`task`, `lease`, `checkpoint`, `event_envelope`) | ✅ all present and parse | No |
| `SM-TASK`, `SM-LEASE` | ✅ with prohibited edges | No |
| `DF-DOMAIN-WRITE`, `DF-PROMOTE` | ✅ | No |
| Runbooks | ✅ 4 exist, **none validated** | No (Phase 8) |
| Spike protocols | ✅ 8, with pass criteria + `on_fail` | No — but all **unrun** |
| Hardware feasibility | 31 figures `UNKNOWN` | No — correctly treated as unavailable |
| **git repository + branch protection** | **absent** | 🔴 **YES** — no CI gate can operate |
| **`CI-008` (the `INV-ADR-1` gate)** | **`PENDING`** | 🔴 **YES** — the F0 blocker is unenforced |
| Unresolved contradictions | **none found** — I re-checked all five previously recorded; all genuinely resolved | No |

**`INV-ADR-1` is a rule with no enforcer.** It is `kind = "process"`, `enforced_by = ["CI-008"]`, and `CI-008` is `PENDING`. Separately, `CI-050` *claims* `enforces = ["INV-TRACE-1", "INV-ADR-1"]`, but `reference_lint.py` implements no merge gate whatsoever — it validates that ADR files carry a Status from the correct enum. The words `core/`, `tasks/`, `memory/` appear in that file **only in a comment**. So the sole named blocker on F0 is defended by one `PENDING` check and one false claim.

---

## 12. Findings ranked P0–P3

### P0 — implementation must not begin

**F-P0-1 · `ADR-002` is `PROPOSED`; `INV-ADR-1` blocks F0.**
No change under `core/`, `tasks/` or `memory/` may merge while `ADR-001`, `ADR-002` or `ADR-012` is not `ACCEPTED`. F0's first increment is exactly those paths. *Disclosed and correctly characterised by the corpus.* Resolution: `OWNER-DECISION-006(b)`.

**F-P0-2 · No git repository exists, so no CI check has ever gated anything — and the F0 blocker itself is unenforced.**
`git status` → not a repository. The corpus discloses `git init` has not been run and correctly holds `CI-002`/`CI-044` at `PENDING` for that reason. What is **not** disclosed is the consequence: `CI-008`, the enforcer of `INV-ADR-1`, is also `PENDING`, and `CI-050`'s claim to enforce `INV-ADR-1` is false. Nothing mechanical prevents F0 code landing under `core/` today while `ADR-002` is `PROPOSED`. The gate is entirely human discipline.

### P1 — significant pre-implementation correction required

**F-P1-1 · `INV-SELF-2` carries a false enforcement record pointing at an implemented, passing check.**
`INVARIANTS.toml` records `enforced_by = ["CI-016", "A-030"]`. `CHECKS.toml` assigns `INV-SELF-2` to `CI-044` (`PENDING`, needs git). `CI-016` does not implement non-narrowability. This is a **ratified COC v1.2 Part VII-A security clause** — the one preventing a narrower approved policy from lowering the required level for `policy/`, `security/`, the SR/COC layer, the verification and CI layer, and the emergency-stop path. This is the `CI-022` defect class — an enforcement claim the code does not perform — recurring inside the registry the second pass rebuilt to eliminate it. **No gate detects it**, because `ci-registry` only checks the reverse direction (does *some* check name this invariant), which `CI-044` satisfies.

**F-P1-2 · `CI-050` declares `enforces = ["INV-TRACE-1", "INV-ADR-1"]`; it does not enforce `INV-ADR-1`.**
`reference_lint.py` implements no merge gate. Same defect class as F-P1-1, on the F0 blocker itself.

**F-P1-3 · `INV-IDEA-3` → `CI-015` mismatch.** `CI-015` does not list `INV-IDEA-3` in `enforces`. Third instance of the same class. (Plus 20 reverse-direction mismatches where a check claims an invariant that does not name it back — mostly benign, but entirely unlinted.)

**F-P1-4 · The published enforcement figures overstate reality at invariant granularity.**
"14 of 53 checks implemented" is true. So is "18 invariants enforced only by acceptance tests." Neither conveys that **only 11 of 111 invariants are enforced today by an implemented check that also names them back** — and one of those 11, `CI-007`, is currently vacuous because no `routing/` or `resources/` directory exists.

**F-P1-5 · `CI-026` validates the trigger `predicate_class` label, not the predicate semantics.**
Proved: a registry whose predicates are pure cron expressions, labelled `COMPOSITE`, passes and reports `8/8 enabled and non-SCHEDULE`. That is the `C1` build. The readiness report's *"red-verified against the C1 cron build"* holds only for class relabelling. The anti-cron property has no mechanical defence today.

**F-P1-6 · `CI-026` does not require `trg_improvement_backlog` to be enabled.**
Proved: disabling that row alone leaves the check green. The registry's own header warns that quiet removal "is how the anti-cron property would be lost quietly" — disabling is quieter than removing, and the check covers removal but not disabling.

**F-P1-7 · `SR-020`'s computer-agency clause is `SPECIFIED` but traced only to perception and presentation artifacts.**
"Self-interact across available hardware" maps to `semantic_scene.schema.json`, `SM-SENSOR`, `INV-PRIV-4` — none of which concerns acting. No subsystem, no decision function, no contract covers endpoint interaction. `A-013` is four sentences about argument-sensitive authorization. `SR-020` should sit at `CONTRACTED` with a depth disposition naming an endpoint-interaction contract, as `SR-023`/`SR-035` correctly do.

### P2 — non-blocking weakness

**F-P2-1 · `CI-050` excludes `docs/COC/` — the live authoritative rulebook.** The exclusion is justified for *superseded* COC documents, but `VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md` is current, normative, second in the authority hierarchy, and names three real paths. Proved: a dangling path planted there stays green. Latent — no live defect.

**F-P2-2 · `CI-050` does not scan `.github/workflows/` or `CODEOWNERS`.** Proved: `ci.yml` pointed at a nonexistent tool stays green. The file naming every tool CI runs is itself unchecked.

**F-P2-3 · `TR-062` verifies a test's `spec` file exists, not that it contains the test.** Proved with `A-029`. Latent — all 50 currently resolve correctly.

**F-P2-4 · `CI-016` uses string-prefix rather than path-prefix.** `paths = ["v", "t"]` satisfies the `verification/` and `tools/` requirements. The recorded direction defect is genuinely fixed; this is a residual weakness in the corrected form.

**F-P2-5 · `ci.yml` never runs `--profile release`.** The depth gate exits 1 correctly but blocks nothing mechanically.

**F-P2-6 · `CI-007` is implemented but vacuous** on the current tree — correctly self-reported as *"not yet applicable."*

**F-P2-7 · Governed surface S7 declares `autonomy/triggers/`, but the shipped registry is `contracts/policy/trigger_registry.toml`** (governed only incidentally, via S1's `contracts/policy/`). Path drift between the surface definition and the artifact it means to protect.

### P3 — documentation / process

**F-P3-1 · `governed_surfaces.toml` header credits `CI-016` with "CODEOWNERS integrity."** That is `CI-044`'s job; `CI-016` validates content. Stale after the split.

**F-P3-2 · `tools/__pycache__/` is present in the tree.** Covered by `.gitignore`, but the tree is not yet a repository.

---

## 13. Previous-review claims: confirmed / rejected

**Confirmed (independently re-verified):**

- All 8 second-pass defects were real and are genuinely fixed: `ADR-002` written; 13 contracts created and parsing; 11 dangling ADR citations resolved with the register; trigger registry shipped (8 rows, 0 `SCHEDULE`); `CI-016`'s direction defect corrected and red-verified; `CI-045` registered; 47+3 negative controls; `INVARIANTS.toml`'s dangling enforcer corrected.
- Every headline artifact count (§2) — all true.
- All linter results reproduce exactly, including `--profile release` exit 1 on depth only.
- 25/25 and 2/2 self-tests genuinely execute red-then-green.
- `READY TO BUILD` is withdrawn everywhere; no live readiness claim exists.
- The 18 acceptance-test-only invariants figure is accurate.
- The five previously-recorded contradictions are genuinely resolved.
- The readiness report's refusal to record its own verdict is real, and its statement that dispositions do not excuse depth is verified true.

**Rejected or materially qualified:**

| Claim | Verdict |
|---|---|
| `CI-026` *"implemented and red-verified against the C1 cron build"* | **Qualified.** Red-verified against class *relabelling*. A genuine cron build passes (probe 6). |
| `INV-SELF-2` enforced by `CI-016` | **Rejected.** `CI-016` does not test it; the real check is `CI-044`, `PENDING`. |
| `CI-050` enforces `INV-ADR-1` | **Rejected.** No merge gate is implemented. |
| Q8: *"the gap is stated, not hidden"* | **Qualified.** True at check granularity; the invariant-level figure (11/111) is stated nowhere. |
| `SR-020` at `SPECIFIED` | **Rejected as overstated** for its agency clause. |
| *"`CI-050` closes the class of defect the first pass could not see"* | **Qualified.** It closes it inside the normative roots; `docs/COC/` (live) and `.github/` remain blind. |
| Status: *"Known blocker on F0: 1"* | **Qualified.** The blocker is real, but is itself unenforced (`CI-008` `PENDING`), which is not recorded. |

---

## 14. Exact remaining corrections

**Minimum set before F0 begins. Nothing here requires an architectural change.**

1. **Owner: answer `OWNER-DECISION-006` (a), (b), (c).** `(b)` — accept `ADR-002` or delegate — is what discharges `INV-ADR-1`. Recommended after `SPIKE-008` validates the constraint set, per the corpus's own reasoning.
2. **`git init`, push, branch protection, replace `@owner` in `CODEOWNERS`** (`SETUP.md`). Until this exists, no CI check gates anything.
3. **Implement `CI-008` (the ADR gate) and show it red** against a change under `core/` while `ADR-002` is `PROPOSED`. The one named F0 blocker must be mechanically enforced before F0 code can land.
4. **Correct the three false enforcement records**, and close the class:
   - `INV-SELF-2.enforced_by`: `CI-016` → `CI-044`
   - `CI-050.enforces`: drop `INV-ADR-1`
   - `INV-IDEA-3` / `CI-015` mismatch
   - **Add a bidirectional consistency lint to `ci-registry`**: every `CI-x` in an invariant's `enforced_by` must list that invariant in its `enforces`, and vice versa. This defect class has now recurred four times and **no gate detects it**. Show it red.
5. **Extend `CI-050` scan scope** to the live `docs/COC/` (v1.2 additive; keep superseded documents excluded) and to `.github/workflows/`. Show both red.
6. **Add a `TR-` rule** requiring a test's declared `spec` file to contain the test id. Show it red against the `A-029` repoint.
7. **`CI-026`:** require `trg_improvement_backlog.enabled = true`; show red. Record explicitly that predicate *semantics* is `A-029`'s job, not `CI-026`'s, and **correct the readiness report's "red-verified against the C1 cron build" wording** to say what was actually verified.
8. **Record the honest enforcement figure** (11/111 invariants; `CI-007` currently vacuous) in `VESPER_ENGINEERING_STATUS.md`, alongside the existing 14/53.
9. **Re-classify `SR-020`** to `CONTRACTED` with a depth disposition naming an endpoint-interaction contract — or write that contract. Either is acceptable; leaving it at `SPECIFIED` is not.

**Not required before F0, but required before autonomy ships:** `CI-018`, `CI-019`, `CI-023`, `CI-027` implemented; `A-029` with its `C1` red run recorded; `A-030` and `A-031` executed with negative controls.

**Also recommended before F0 (unchanged from the corpus's own plan):** run `SPIKE-001` → `SPIKE-002`, `SPIKE-007`, `SPIKE-008`. None depends on an owner decision.

---

## 15. Final readiness matrix

| Dimension | Verdict | Note |
|---|---|---|
| Repository / artifact integrity | ✅ **PASS** | Every count true; no dangling references; no false readiness claim |
| Requirement traceability | ⚠️ **PASS WITH GAPS** | Sound as a map; content-coupling unverified (F-P2-3) |
| Runtime architecture | ✅ **PASS** | `observe→…→learn` closes without a user message |
| JARVIS divergence (specification) | ✅ **PASS** | 29/29 clauses name a mechanism and a test |
| JARVIS divergence (enforcement) | ⚠️ **THIN** | 11/111 invariants defended today; anti-cron is label-only |
| Autonomous computer agency | ⚠️ **PERMITTED, UNSPECIFIED** | F-P1-7; not structural |
| Distributed survival | ✅ **PASS** | Strongest recent work; trust/availability axes correctly separated |
| Self-improvement | ✅ **PASS** | Both paths; boundary correctly on merge, not on work |
| Security (design) | ✅ **PASS** | Structural, not prose; four layers, not one |
| Security (enforcement) | 🔴 **ABSENT** | Expected pre-code — **except** F-P1-1, which is not |
| Emergency stop | ✅ **DESIGN PASS** | Dead-man's switch; `INV-STOP-2` puts the stop path outside the control plane, PDP, leases and model inference; human-only re-arm |
| CI / acceptance tests | ⚠️ **HONEST BUT INERT** | Self-tests genuinely execute; no repository, so nothing gates |
| F0 prerequisites | 🔴 **NOT MET** | `ADR-002` `PROPOSED`; `OWNER-DECISION-006` open; no git; `CI-008` `PENDING` |
| Unresolved contradictions | ✅ **NONE FOUND** | All five previously recorded genuinely resolved |

**On the question this audit was called to answer** — *can competent engineers or coding agents now implement VESPER from this repository without being able to accidentally turn it into a conventional LLM + memory + tools + UI assistant?*

**Not accidentally, no — the specification blocks that at multiple independent points.** But the blocks are currently held by *documents* rather than by *gates*: 11 of 111 invariants are mechanically defended, the anti-cron property is defended by a naming convention rather than a check, and no CI runs at all. An agent that follows the corpus faithfully will build VESPER. An agent that drifts will not be stopped by machinery today — it will be stopped only by review.

That is a correctable condition, not a structural one. Close the nine items in §14 and this becomes `BUILD`.

---

`BUILD_AFTER_CORRECTIONS`
