# VESPER — Engineering Status

**Updated:** 2026-08-31, after the last five unbuilt source capabilities landed and six checks that had been declared since the registry was written were finally implemented · **Maintained continuously.** If another engineer or agent takes over tomorrow, this file plus `docs/DECISION_LOG.md` is the handoff.

> **Read `MEMORY.md` first.** It carries what is *not* derivable from this file, the code or the
> git history: the measured numbers with their provenance, the **bandwidth law** that governs
> every model decision on node 1, the mistakes already made and corrected, and the doctrine this
> project keeps rediscovering. Not required reading — a place to stand on. The current plan is
> `PLAN_2026-08-24.md`.

---

## Current position

**2026-08-31. EVERY REMAINING UNBUILT SOURCE CAPABILITY IS BUILT AND GATED.**
`core/cache.py` (SR-054's tiers plus DF-CACHE-ADMIT), `LogReceipt` in
`core/evidence.py` (the log-backed span an L2 fact can actually produce),
`core/verifiers.py` (the two machine-checkable strategies `core/verify.py` had
declared and never implemented) and `core/knowledge_map.py` (SR-007, which had
no CI check at all). Each is reached by the running system, not only by a test:
the arbiter cites its winners, block B withholds a fact whose pointer does not
resolve and says so in the prompt, and `build()` registers the verifiers it can
actually run.

**THE NUMBER WORTH WATCHING IS NOW `impl = "PENDING"`, NOT THE CHECK COUNT.**
A PENDING entry looks exactly like enforcement in every listing that does not
read the `impl` field. Fifteen were implemented on 2026-08-31 — `CI-004`,
`CI-009`, `CI-010`, `CI-011`, `CI-012`, `CI-013`, `CI-015`, `CI-020`, `CI-024`,
`CI-033`, `CI-035`, `CI-040`, `CI-045`, `CI-046b`, `CI-049` — and all but one
guard a subsystem that has been complete and correct since it was built.
`core/bus.py`, `core/store.py`, `core/tasks.py`, `core/taint.py`,
`core/authorize.py`, `core/capability.py`, `core/evidence.py`, `core/selfmod.py`,
`core/telemetry.py`, `core/enrollment.py`, `core/placement.py`,
`core/forgetter.py` and the gateway's cost choke point were each protected by
nothing.

`CI-024` is the exception: `INV-TRIG-5` had **no enforcement of any kind**, so
`assert_terminating` in `core/autonomy.py` was written as part of landing it.

**Enforced invariants went 52 → 79 of 144 in one session, with one subsystem's
worth of new code.** That is the clearest measure so far that **wiring and
gating, not building, is where this corpus loses ground.**

**And the two counts that had drifted seven times now have a gate.**
`documented-counts-match-commands` reads every figure this file and `CLAUDE.md`
quote from a command and compares it to what the command produces. It found two
further live claims stale by years on its first run — *"41 of 56 CI checks
unimplemented"* and *"18 of 118 invariants enforced"* — in the table below that
says every number in it is produced by a command.

**One security question is open and deliberately undecided** — see
`CI-013`'s note in `verification/ci/CHECKS.toml`. Grant consumption keys on
`requires_owner_confirmation AND L4/L5` while `issue()` refuses an L4-delegable
grant on the level alone, so an L4 grant on a capability that does not declare
owner confirmation is not spent by use. `INV-AUTH-2`'s text mentions only the
level. The check asserts neither reading: freezing the current behaviour would
lock a possible gap into a gate, and asserting the strict one would change the
security model without owner review.


**MEMORY LANDED 2026-08-29/30, ALL SEVEN BUILD-ORDER STEPS, WIRED.** `core/memory.py`
(L2 graph over SQLite, FTS5 + bounded recursive CTE), `core/redact.py`,
`core/updater.py` (updater + miss recorder), `core/blocks.py` (L1 block A/B),
`core/chooser.py`, `core/arbiter.py`, `core/forgetter.py`, `core/compactor.py`,
`core/sensors.py` and `core/host_probes.py`. All reached from
`tools/ops/vesper_runtime.py`'s live turn; `l2.db` is created by the supervised
runtime. **56 checks, 206 self-tests, both lints.** Five invariants gained a CI
enforcer, two of which previously had only an acceptance test: `INV-MEM-1` and
`INV-EVID-3`. Details and the findings are in `OVERNIGHT_REPORT_2026-08-30.md`.

**Two things that change plans rather than just adding code.** The `~18 ms`
quoted for L2 in `HANDOFF_MEMORY_BUILD.md` is the full-text stage alone; the
actual block-B query is 31.55/50.36/87.35 ms at 100k facts, over the 25 ms
budget at every depth — so **the compactor is load-bearing for latency**, not
only for context size. And **erase does not destroy content**: `UPDATE`/`DELETE`
on the `log` store are refused at the storage layer, so an erased value stays in
L3 and a credential that reached L2 must be **rotated**, not merely erased.

**Voice is unblocked at the front edge.** Microphone and speech-recognition
consent are granted to `ai.vesper.island` as of 2026-08-30. On-device
recognition is available for `en-US` and NOT for `ar-MA`/`ar-SA`/`fr-FR`.

| | |
|---|---|
| **Phase** | **F0, F1, F2 COMPLETE. F3, F4, F5, F6 part-built — every software-only case done, hardware-blocked cases named.** Seven gates run in CI. **F6 placement landed 2026-08-18**: `DF-PLACE` and `DF-SURVIVAL-PROFILE` implemented in `core/placement.py`, `A-048` (nine cases, both mandatory negative controls) and `A-017` green, plus a property harness over randomised fabrics. Implementation authorised and under way — `INV-ADR-1` was discharged 2026-08-14 by owner acceptance of `ADR-002` (with `ADR-001` and `ADR-012` already ACCEPTED). |
| **Position** | **Three** SRs remain below `SPECIFIED` and `--profile release` fails on depth, deliberately: `SR-034` is the corpus's worked example of a requirement correctly held there, and `SR-016`/`SR-017` are F6 network-fabric work whose assertions `A-045` already holds. The other four were raised 2026-08-17 against the assertion that already named their mechanism. **No completeness judgement is recorded here** — that is part of the gate. |
| **Verdict** | **None recorded here.** The readiness gate is the project owner's act. `docs/architecture/IMPLEMENTATION_READINESS_REPORT.md` and `docs/FINAL_PRE_F0_VERIFICATION_REPORT.md` are *evidence for* that gate. |
| **Next action** | **The router was not routing, and that is fixed (2026-08-24).** `SR-009` asks for easy work on smaller models; every difficulty was reaching the strong tier, and `A-022` was green because it asserted the tier floor and monotonicity, both of which a constant `strong` satisfies. Separately, `ModelGateway.complete` had no parameter for a routed profile at all, so **registration order was the routing rule**. Both closed, each with an executed red run. `routing/` now exists, which makes `CI-007` non-vacuous on the first directory `INV-HW-1` names. **VESPER has made a real model call** — `free:1 paid:0`, build `b10405-e79e4bf66`. What remains blocked needs the **iPhone app**, **cameras**, a **flat clear sheet**, and **node 1 powered on** (measured 2026-08-24 15:05: TCP/22 closed across the /24, so every tier above `draft` is unreachable from here). Software-only work continues to land — F6 placement on 2026-08-18. What remains blocked needs the **MacBook** (expected 2026-08-20), the **iPhone app**, **cameras**, and a **flat clear sheet**. **The endurance run is NOT in flight**; this line claimed it was for a day after it stopped being true. `A-029` is F5's gate, seventh of nine in the build order, and is scheduled for week 3 alongside the work it actually gates — the 23 h partial is banked as evidence. Owner still owes `OWNER-DECISION-006(c)` and the ADR-001/012 authority question below. |
| **Known blocker on F0** | **DISCHARGED 2026-08-14.** `ADR-002` was accepted by the owner under `OWNER-DECISION-006(b)`; `ADR-001` and `ADR-012` were already ACCEPTED. `CI-008` enforces this mechanically and is green. **One authority question remains open and is the owner's:** `ADR-001` and `ADR-012` carry `ACCEPTED` stamped by an engineering pass, not by the owner. The corpus records that either all three are confirmed together at the readiness gate or the other two are re-confirmed on the same basis. F0 proceeded on the mechanical gate; this is recorded, not resolved. |
| **Repository** | `git init` **done** 2026-08-12, `core.autocrlf=false`, corpus committed as authored. Branch protection and the `@owner` handle remain host-side owner actions, so `CI-002` and `CI-044` stay `PENDING`. |

**Live verification state** — every number below is produced by a command, and the command is the source of truth:

```
tools/traceability_lint.py                    PASS   0 errors, 0 warnings, 0 info
tools/traceability_lint.py --profile release  FAIL   2 errors, DEPTH only (SR-017, SR-034)
tools/reference_lint.py                       PASS   0 errors — 179 normative files scanned
tools/reference_lint.py --self-test           PASS   6/6 red-then-green
tools/ci/checks.py all                        PASS   106/106 runnable checks
tools/ci/self_test.py                         PASS   503/503 red under violation, green after restore
tools/ci/checks.py status                            76/94 check IDs implemented, 18 PENDING
tools/ci/checks.py ci-registry                       ENFORCED TODAY: 80/144 invariants
verification/run_f0_acceptance.py             PASS
verification/run_f1_acceptance.py             PASS
verification/run_f2_acceptance.py             PASS
verification/run_f3_acceptance.py             PASS   A-009, A-026, A-035
verification/run_f4_acceptance.py             PASS
verification/run_f5_acceptance.py             PASS   A-029 + C1 control
verification/run_f6_acceptance.py             PASS   A-048 (9 cases) + A-017, 3 controls
verification/stress_placement.py              PASS   160k property assertions
verification/stress_fabric.py                 PASS   180k property assertions, DF-FABRIC-ADMIT
verification/run_a029_endurance.py --self-test PASS  6/6 healthy, 3/3 controls fail as required
verification/run_live_provider_acceptance.py  PASS   9/9 -- NOT hermetic, needs a live endpoint
tools/schema_validate.py --self-test          PASS   11/11 red-then-green
tools/home_snapshot.py --probe                       5/5 card rows have a producer
```

**The runtime carries a model path and registers no provider.** `Supervisor` owns one router, gateway, cost policy and completion service, and emits `runtime.model_path` at startup naming its profile count, provider count and declared credentials. Zero providers is fail-closed and still routable: the router selects, the gateway finds nothing serving the profile, the task queues. Registering an endpoint is a deployment act.

**The live provider gate is deliberately outside `checks.py all`.** It needs a model
server; with none it reports `NOT RUN` and **exits 2**, never 0. A gate that goes green
because its subject was absent is the vacuity defect described two paragraphs down, and
the point of naming that defect was to stop repeating it. Start the endpoint with
`~/VESPER-runtime/serve.sh` — llama.cpp **b10405-e79e4bf66**, the same build node 1 runs,
so the two nodes' figures are comparable rather than merely both present.

**The two figures that matter, and the difference between them.** *"21 of 56 checks implemented"* is true and flattering. *"23 of 118 invariants are enforced today"* is the number a reader actually wants. An invariant counts as enforced today only if a check names it that is **implemented**, **symmetric in both registries**, **red-run by the harness**, and **not vacuous on this tree**. `ci-registry` computes it on every run, so it cannot go stale.

**The vacuity exclusion is now empty, and the prose that said otherwise was stale.** Until 2026-08-18 this paragraph named `CI-007` and `CI-008` as excluded for having nothing to scan. `_vacuous_checks()` adds `CI-007` only when *no* scope directory exists and `CI-008` only when `core/`, `tasks/` and `memory/` are all empty — and `core/` has held 65 files since F0 landed. Neither has been excluded for some time; the sentence describing them as excluded outlived the condition it described. Read the command, not this file.

**Six checks landed 2026-08-18**, each with an executed red run and each traced to a requirement: `CI-022` cost-class-nonnull, `CI-025` action-has-trigger, `CI-032` verification-criteria-typed, `CI-047` idea-retirement-reason, `CI-019` interlock-independence, `CI-023` evaluator-no-model-capability. `TR-067` fired on three of them — an implemented check that no SR names — and each was placed by evidence: the SR already listed the invariant's *other* declared enforcer.

> **`--profile release` failing is the correct state**, not a defect. It fails on depth: seven SRs are not yet `SPECIFIED`. Each records the artifact that would raise it. The dispositions do **not** excuse the depth — that was checked deliberately, because a disposition mechanism that turns a FAIL into a PASS is a mechanism for optimising the verdict.

---

## What the second pass found *(historical — retained)*

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

## What the final pre-F0 pass found (2026-08-12)

The third pass audited **the verification system itself**: for each load-bearing check it established a positive control, injected a violation the repository's own self-tests do *not* enumerate, and required the check to go red. Nine went green. All nine are now closed and each closure carries its own red run.

| # | Defect | Class | Closure |
|---|---|---|---|
| 1 | **`CI-026` validated the trigger `predicate_class` LABEL, never the predicate SEMANTICS** | label-only validation | Predicate bodies are now parsed. Every namespace root is classified against a closed vocabulary; the predicate is evaluated with all clock terms TRUE and all world-state terms FALSE, and firing under that substitution fails. 8 red runs. |
| 2 | **`CI-026` did not require `trg_improvement_backlog` to be ENABLED** | disablement bypass | Eight load-bearing rows are named in the check; absent, disabled or schedule-only fails. Retiring one is an edit to a governed surface. |
| 3 | **`CI-008`, the enforcer of the sole F0 blocker, was `PENDING`** | rule with no enforcer | Implemented. `INV-ADR-1` is a property of the TREE, not of a diff, so no git history is needed. Red against a file under `core/`; **green against the same file once `ADR-002` is ACCEPTED** — the discriminating direction. |
| 4 | **`CI-050` declared `enforces = ["INV-TRACE-1", "INV-ADR-1"]` and implemented no merge gate** | false enforcement record | Claim dropped. `INV-ADR-1` is now enforced by `CI-008`. |
| 5 | **`INV-SELF-2` — a RATIFIED COC v1.2 security clause — recorded enforcement by `CI-016`**, an implemented, passing check containing no non-narrowability logic | false enforcement record on a green check | Retargeted to `CI-044` (`PENDING`). **The class is closed**: `ci-registry` now lints the registries in BOTH directions and 22 asymmetries were resolved by deciding which side was wrong, not by adding the missing side. |
| 6 | **`CI-016` used a STRING prefix**, so `paths = ["v", "t"]` satisfied `verification/` and `tools/` | metadata-only verification | Path-component prefix. Extended to require named load-bearing files to be covered by some surface, which caught S7 pointing at `autonomy/triggers/` — a directory that has never existed — and **`spec/` being governed by no surface at all**, while every invariant in the system lives there. |
| 7 | **`TR-062` verified a test's `spec` file EXISTS, not that it mentions the test** | unrelated-artifact substitution | `TR-068` added. Red run: `A-029` — the anti-cron discriminator — repointed to `AT-04`. |
| 8 | **`CI-050` scanned neither the LIVE COC, nor `.github/workflows/`, nor `CODEOWNERS`, and exempted ITSELF** | wrong-file scanning / excluded-file hole | All three added; the self-exemption removed by assembling its probe tokens from fragments. A workflow pointing at a non-existent checks script now fails. |
| 9 | **Nothing verified that an implemented check had ever been RED** | checks that verify only their own existence | `ci-registry` now requires every implemented check's `impl` command to appear in the red-run harness and to record `self_test_evidence`. It found `CI-050` uncovered on its first run. |

Two further findings, neither previously recorded anywhere:

- **`CI-039` declared `enforces = ["INV-PERF-1"]`** — latency-budget immutability — while its self-test is about **governor damping**, an unrelated property that REM-012 §5 specifies in full and that no invariant ID carried. `INV-GOV-1` was written and the claim retargeted. A check pointing at the nearest available ID is how a false record is born innocently.
- **The mutation harnesses restored files with `write_text`**, which on Windows rewrites every `
` as `
`. The corpus is genuinely mixed CRLF/LF — `docs/COC/` and the ADR records are LF — so a text-mode restore silently rewrote governed-surface bytes. Found when a probe converted the live COC v1.2 additive from LF to CRLF; the restore compared equal as text and unequal as bytes. Both harnesses now read and restore bytes, and assert byte-exactness after every restore. **The file was restored to its exact original 11 638 bytes and is byte-identical in the committed tree.**

And one requirement gap:

- **`SR-020`'s computer-agency clause was `SPECIFIED` while tracing only to perception and presentation artifacts.** Of 29 subsystems none covered acting on a computer; of 30 decision functions none governed endpoint interaction. The requirement was **not downgraded**. `SPEC-30`, `SM-ENDPOINT-EPISODE`, `DF-ENDPOINT-ACT/OBSERVE/RECOVER`, two contracts, `INV-ACT-1…6` and `A-051`/`A-052` were written, and `SR-020`, `SR-021` and `SR-030` now trace to them.

---

## Completed

| Work | Artifacts |
|---|---|
| **Repository structure + migration** | Part XIII layout honoured; every old→new path in the decision log |
| **Authority axes separated** (NV-04, AR-030) | `docs/AUTHORITY_AND_PRECEDENCE.md` — `L0–L5` / `E0–E4` / `Z0–Z3` |
| **Phase 1 — remediation** | REM-001…REM-016, each with the full 15-field treatment |
| **Phase 2 — system specification** | **30 subsystems**, `SPEC-00`…`SPEC-D`, each with a Jarvis-divergence field |
| **Phase 3 — contracts & verification** | **28 JSON Schemas + 8 policy contracts** · **12 state machines** with normative transition tables · **33 decision functions** · **118 invariants** · **52 acceptance tests** · **56 CI checks** |
| **Phase 3b — reference integrity** | `ADR-002`, `ADR-007`, `ADR-REGISTER.md`; `tools/reference_lint.py` (`CI-050`) |
| **Phase 3c — enforcement made real** | `tools/ci/self_test.py` executes **47 red runs**; `ci-registry` fails any implemented check with no red run |
| **Phase 3d — computer agency specified** | `SPEC-30`, `SM-ENDPOINT-EPISODE`, `DF-ENDPOINT-ACT/OBSERVE/RECOVER`, `endpoint_interaction.schema.json`, `endpoint_surface_state.schema.json`, `INV-ACT-1…6`, `A-051`, `A-052`, `CI-052…054` |
| **Phase 3e — repository** | `git init` with `core.autocrlf=false`; corpus committed as authored; full suite re-run from a fresh clone |
| **Phase 4 — spikes** | 8 protocols with measurable pass criteria and pre-declared failure dispositions |
| **Runbooks** | Emergency stop · Alarm · **Integrity loss** (new) · **Proposal review** (new) |

### The three named remediations

| Item | Status | The mechanism, in one line |
|---|---|---|
| **NV-01** self-modification | Specified; `INV-SELF-2` RATIFIED | Runtime executes from a **pinned artifact ≠ the working repository**; it may open a proposal, never self-merge. **Overnight coding stays unrestricted** — `A-030.6` must *pass*. `change_proposal.schema.json` makes `MERGED` unwritable by a runtime author. |
| **NV-03** zero-input autonomy | Specified; blocking at F5 | A deterministic predicate decides *whether*; a model decides only *how*. Now backed by a **shipped registry of 8 non-`SCHEDULE` triggers** rather than a described one. |
| **FV-01** emergency stop | Specified | **Dead-man's switch**: actuation requires a fresh externally-signed token. Severing the stop path *halts* autonomy. |
| **Traceability** | Rebuilt, enforced, extended, and made **bidirectional** | `registry.toml` + two linters. `CI-050` closes the dangling-artifact class; `TR-068` closes unrelated-artifact substitution; `ci-registry`'s two-direction lint closes the false-enforcement-record class. |
| **Computer agency** (`SR-020`, `SR-021`, `SR-030`) | Specified this pass | The unit is an **episode**, not a call. `SM-ENDPOINT-EPISODE` has **no edge from `ACTUATED` to `VERIFIED`** — the actuator's report is never the observation. `A-051`'s negative control is the self-report build, which is what a chatbot-with-tools is. |

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
| **18 of 94 CI checks unimplemented** | `tools/ci/checks.py status` for the live figure | Most are structural checks over source code that does not exist. Each declares its self-test and lands **with** its subsystem. `CI-022`, `CI-034b`, `CI-046b` were deliberately split or held at `PENDING` rather than let a partial implementation be reported as full coverage. |
| **7 SRs below `SPECIFIED`** | SR-016, 017 (`DESIGNED`); SR-023, 033, 034, 035, 038 (`CONTRACTED`) | Each names the artifact required and why it is absent. **SR-034 is the worked example of the discriminator**: a decision function for *"clean hierarchy, formatting, vocabulary"* would be a document written to move a linter. |
| **80 of 144 invariants enforced by an implemented, red-run, non-vacuous check** | Computed by `ci-registry` on every run; the remainder are enforced by acceptance tests or by nothing yet. | Visible in every `ci-registry` run as a note. Most require runtime state to check at all. |
| **Acceptance tests are specifications** | 52 tests with procedures and assertions | Executable fixtures require the runtime. **None is executable today.** 49 name the wrong build that must fail; 3 record why a negative control cannot exist. |
| **`A-029` and `A-031` never run** | The two decisive gates | Cannot run before the autonomy engine and interlock exist. `CI-027` blocks the autonomy release without their evidence. |
| **11 of 12 spikes unrun; `capability_profiles.toml` still entirely `UNKNOWN`** | `SPIKE-001` is `RUNNING` — see below. The other 11 are `NOT_STARTED`. The profile file carries 31 unmeasured fields and `measured = false`. | Deliberate and enforced: `CI-034` fails the file if any figure is filled in from a datasheet while `measured = false`. Unmeasured is treated as **unavailable**, not as available. **Measured-but-unpromoted is the correct state**: SPIKE-001 has real numbers on disk and none of them has been written into the contract, because promotion is a separate deliberate act and the spike's own pass criteria are not all met. |
| **Runbooks written, none validated** | Four runbooks exist | None executed on real hardware. The alarm one must be validated **at night, with the owner genuinely asleep beforehand** — a wake-up procedure validated while awake has not been validated. Phase 8. |
| **Branch protection and the `@owner` handle** | `git init` is **done**; hosting is not | The repository exists and the full suite has been re-run from a fresh clone, so verification now executes against version control rather than a directory. `CI-002` and `CI-044` stay `PENDING`: one commit is not review history, and branch protection is a host-side setting. Replacing `@owner` in `CODEOWNERS` is an owner action (`SETUP.md`). |

---

## Unresolved contradictions

**None outstanding at the engineering level.** Every contradiction found was resolved with a mechanism or escalated as an owner decision. Previously recorded and still resolved: SR-003 × SR-045 (queue within the free subset); RB-005 × RB-006 (preparation unbudgeted, interruption budgeted); SR-031 × RB-012 (feasibility, not contradiction — `SPIKE-005`); SR-042 × SR-049 (the boundary is on **merge**, not on work); immutable log × privacy deletion (payload/reference separation).

One naming drift was found and corrected this pass: `tunables.toml` initially invented field names where REM-015 §3.5 had already declared them. REM-015's names and ranges are authoritative and are now used verbatim, and `DF-TUNABLE` reads its field set **from the contract** rather than an inlined list — a list in a specification and a list in a contract will drift.

---

---

## SPIKE-001 — RUNNING since 2026-08-13 *(added 2026-08-14)*

The first candidate node is a mains-powered desktop in site A: Ryzen 5 5500 · 15.9 GB RAM ·
RX 6650 XT with **7.2 GB usable VRAM, measured** · llama.cpp `b10405-e79e4bf66`, Vulkan.
Ten full-protocol reports are committed under `docs/planning/spike-results/`; that
directory's `README.md` is the measurement record and carries every caveat.

**§3.1 measured** — median of 3 × 10-min runs, wall-clock rate, idle → concurrent:

| Tier | Model | idle | concurrent |
|---|---|---|---|
| `draft` | Qwen3-1.7B | 151.42 | 94.88 |
| `draft` | Llama-3.2-3B | 99.50 | 72.03 |
| `standard` | Qwen3-8B | 47.38 | 46.79 |
| `strong` | Qwen3-30B-A3B (MoE) | ~9.7 | ~8.5 |
| `strong` | Mistral-Small-24B (dense) | 3.29 | 3.25 |

Three findings worth carrying into design: **MoE beats a smaller dense model ~3× at `strong`**
on a VRAM-starved node (9.7 vs 3.3 tok/s, while being the larger model on fewer GPU layers);
**contention cost is inversely proportional to model speed** (−37% at 1.7B, −1.2% at 8B), so
a router tuned on idle figures over-selects `draft` precisely when the machine is busy; and
this node **does not thermally throttle**, making §3.1's minute-10 rule a no-op on this node
class.

**Open, and why the spike is `RUNNING` rather than `REPORTED`:**

| Item | Cost | Note |
|---|---|---|
| §3.1 `small` re-run | ~1 h | **Critical path.** The tier that closes pass criterion 2 (`local_inference_small`, SR-005 fallback). Held figures predate the 512-token-cap removal, so they are not the tier as §3.1 defines it. |
| `strong` sampling fix | small | Checkpoints fire only when a request returns; at `strong` one request outlasts the window, so intervals alias and one published figure came from **minute 1** — the value §3.1 names and forbids. Needs `ignore_eos` **and** wall-clock sampling. Do not re-run `strong` before both land. |
| §3.2, §3.3, §3.6 | hours each | Memory headroom, the five stores, thermal/power. §3.3's `synchronous = FULL` figure is SPIKE-008's input. |
| §3.5 | — | Skipped for this node by owner direction; recorded DECLARED-and-unmeasured, not measured-absent. Another node re-opens it. |
| **Criterion 4 — availability** | **closed by decision** | See below. Not a pending measurement. |

**Criteria 3 and 4 are dispositioned by owner decision (2026-08-14), not pending.** A 7-day
passive observation window was started and withdrawn the same day as incoherent: the sampler
runs *on* the node, so it cannot observe the node while the node is off — and the node is off
whenever the owner is not at it. Seven days of that measures the owner's working hours, not
the machine, and not the machine that will exist after relocation.

`availability_class` for this node is therefore **DECLARED by owner policy and recorded as
declared**: the node is treated as *available*, on the operational commitment that it is left
powered on and dedicated to VESPER, with a human-present degradation mode (confine VESPER to
light work while someone is at the machine, restore when they leave).

**The commitment is the load-bearing part, and it is the one thing to keep honest.**
`INV-TRUST-2` forbids placing continuity-critical capability on a node that can be off with no
way back, and SPIKE-010 records that VESPER cannot wake this one. So the declaration is safe
exactly as long as the machine is in fact left on, and unsafe the moment it is not. That is an
operating condition to honour, not a measurement to take — and it is why remote wake
(SPIKE-009/010) stays worth doing even though it is off the F0/F1 path.

---

## Next actions, in order

**Engineering has run out of unblocked work.** Everything below needs hardware,
owner action, or real elapsed time.

1. **Owner — get a flat clear sheet** (plastic sheet protector, CD case lid,
   acetate). ~5 minutes of eyes closes `SPIKE-004`. The instrument is built and
   served; the bare-panel baseline half needs no glass at all.
2. **Owner — `OWNER-DECISION-006(c)`:** whether four REM-carried decisions get
   numbered ADR ids. Still open.
3. **Owner — the ADR-001/ADR-012 authority question** recorded in the position
   table above.
4. **Owner — the MacBook.** It unblocks the iPhone app, which unblocks
   `SPIKE-002`, which unblocks `A-020` (the measured latency chain).
5. **Owner — the broken desktop.** It is the intended always-on server; the
   Kali laptop is the interim control-plane host and its RAM makes it a bridge,
   not a destination.
6. **Engineering, when hardware exists:** `A-008`/`A-028`/`A-039` (cameras,
   video, capture indicators), `A-012`/`A-041` (alarm hardware),
   `SPIKE-008` criterion 9 on a `foreground_only` node.
7. **Engineering, needs elapsed time:** the **24-hour `A-029` endurance run** —
   **IN FLIGHT since 2026-08-17 00:09:58, lands ~2026-08-18 00:10.** Detached
   from any session, pinned to worktree `VESPER-endurance-2026-08-17` at
   `e78256f`. Nothing memory-heavy may share its window: `SPIKE-001` §3.2 drives
   free RAM to 0.27 GB at 660 pages/s and would perturb it.

   The **first attempt was externally killed at 23.00 h of 24** and is a
   **RECORDED PARTIAL** — not a pass, not a failure, and not VOID (`AT-03` voids
   a run only when the external ingress was unavailable; all three injections
   landed). `A-029` **stays owed**. Evidence, both verdict readings and the
   disposition are committed under
   `docs/planning/spike-results/A-029-endurance-2026-08-16/`.

   Two results from it are worth carrying. **The pre-registered leak did not
   happen:** `A-029-E1-PREREGISTRATION.md` projected a last-quarter mean near
   29 MB (+9.3 MB against an 8.0 MB budget); measured at hours 21–23 it was
   20.07 MB, **+0.07 MB**. RSS peaked at 24.17 MB by hour 12 and came back down,
   so the `INCONCLUSIVE-BY-CRITERION` disposition was **not invoked**. Stated
   with its hole: hours 12–21 of the series are gone, so that is a
   reconstruction from two endpoints, not a continuous measurement. **And the
   build was the larger defect:** 391 lines of harness landed *after* the run
   started, including all 234 lines of `verify_a029_from_log.py` and the
   VOID/FAILED discriminator, so that run could not have been judged the way
   runs are now judged — its samples carry no `wall_s` and `detect_void` is
   inert against them. The relaunch exercises the corrected criteria for the
   first time rather than repeating anything.

*Done and no longer listed:* branch protection is live, `CODEOWNERS` points at the real owner account, and the repository is pushed. `CI-002` and `CI-044` remain `PENDING` on review history and the governed-surface check respectively, not on host configuration.

**Scale, stated plainly so no plan is built on a wrong premise.** The corpus is ~37,800 lines
across 161 files. The runtime is now **6509 lines** under `core/`, plus 4274 lines of acceptance
harness under `verification/` and ~3,400 lines of verification tooling under `tools/`.
`IMPLEMENTATION_SEQUENCE.md` runs F0…F8 and names **F5** as the decisive gate.
**Three of nine stages are complete (F0, F1, F2); F3, F4 and F5 are part-built with every software-only acceptance case passing.** Any schedule that puts a finished VESPER inside a month
is a schedule that has not read this file.

See `docs/FINAL_PRE_F0_VERIFICATION_REPORT.md` for the full evidence, the negative-control table and the exact F0 prerequisite list.
