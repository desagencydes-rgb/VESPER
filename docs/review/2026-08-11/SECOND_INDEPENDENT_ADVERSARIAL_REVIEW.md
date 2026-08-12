# VESPER V0 — SECOND INDEPENDENT ADVERSARIAL REVIEW

**Reviewer role:** Independent senior systems architect (second pass, adversarial).
**Date:** 2026-08-11
**Sources of authority (as mandated):**

- **Immutable:** the eight handwritten pages + `VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.1` (SR-001..SR-051, DR-001..DR-031, RB-001..RB-036, IC-001..IC-010, A-001..A-020).
- **Current design (under test):** `VESPER_ENGINEERING_BASELINE_v1.0/` (00–07) **and** `VESPER_ENGINEERING_FOUNDATION_v1.0.docx`.
- **Untrusted hypotheses:** everything in `REVIEW_2026-08-11/` (the prior Claude review: ADVERSARIAL_REVIEW, ARCHITECTURE_GAP_REGISTER, BUILD_READINESS_ASSESSMENT, COC_TRACEABILITY_MATRIX, RECOMMENDED_PATCH_SET) and `claude's-return.txt`.

I read the full corpus directly. I did not take any prior finding as true until I re-derived it against the source text. This document reports what the documents **enforce**, not what they intend.

---

## 1. Executive Verdict

**The corpus cannot, as delivered, prevent a competent, literal, optimization-driven engineer from building a conventional "LLM + memory + tools + UI" and passing every written check.** The intent is the opposite of a chatbot and is argued more explicitly and correctly than most specifications of this class. But intent is carried almost entirely in **prose principles and prohibitions**, and prohibitions do not compile. The three artifacts that actually separate VESPER from a chatbot — the **semantic scene**, the **autonomy trigger**, and the **world-model consistency/keying layer** — are each named in one sentence and specified nowhere. The natural, ship-it implementation of each is exactly the thing the COC forbids.

**On the prior Claude review:** it is unusually strong. I independently **CONFIRM all ten P0 findings** (AR-001…AR-010) against the source text, with two refinements (AR-004/AR-005 are one leak with two enforcement points; the gateway choke point AR-005 is the load-bearing backstop, so it outranks AR-004). The prior review's structural read — *"the corpus is under-specified, not mis-designed; the fixes are additive"* — is correct and I concur with it.

**Where the prior review is itself incomplete — and this is the reason a second pass was warranted:** its own success test is insufficient for the degradation it most fears. Claude's condition is *"corrections must land as CI checks and contract tests that can fail."* A **contract test checks shape, not behavior.** A `SemanticScene` schema with a `text` element type is satisfied by one giant text element containing the entire chatbot reply; a `Trigger` registry is satisfied by one cron-like entry; a "one loop works" acceptance test is satisfied by a loop that only ever runs when prompted. **Schema-conformance is not behavior-conformance.** The anti-chatbot property is a *runtime* property and requires *runtime* assertions — liveness of the unprompted loop, real modality migration on materially different hardware, and negative tests that fail a degenerate scene. Neither the corpus nor the prior patch set contains these. I add them (NV-03, NV-09, and the patch critiques in §5).

I also add **nine new findings** the prior review missed, three of which I rate P0/P1 and which are not covered by any existing patch: **recursive self-modification of VESPER's own code by the overnight autonomy engine** (NV-01), **verifier collapse under the single-local-model free-time constraint** (NV-02), and **an authorization-vocabulary collision (`L0–L5`) between the two engineering packages** (NV-04).

**Readiness:** **NOT READY as delivered.** The architecture is sound and worth building; the specification is not yet a specification. After a bounded, additive correction program (the prior 17 patches, *strengthened* per §5, plus the new items), it becomes ready. This is decision-work, not a redesign.

**Final token (also in §8): `BUILD_AFTER_CORRECTIONS`.**

---

## 2. Claude Finding Audit

Legend: **CONFIRMED** (re-derived from source, severity correct, fix sound) · **PARTIAL** (real but fix/scope incomplete) · **MISCLASSIFIED** (severity or category wrong) · **INCOMPLETE** (correct but misses a deeper/adjacent issue) · **REJECTED** (not supported by source).

### P0 findings

| ID | My verdict | Severity | Evidence I verified | Does the proposed fix solve it? | Deeper/adjacent issue I add |
|---|---|---|---|---|---|
| **AR-001** SemanticScene is one sentence | **CONFIRMED** | P0 | IC-005 = *"Semantic scene + modality requirements → selected rendering endpoint → interaction events."* (COC Part XII; Foundation "IC-005"). No taxonomy anywhere. Part V §28 bullet 2 forbids reduction to decoration but supplies no schema. | **Partially.** The `SemanticScene` schema is necessary but **bypassable**: a `text`/`code` element with unbounded content is a legal markdown escape hatch. See NV/patch critique PC-1. | The fix needs a **behavioral** negative test (a scene that is 95% one text element must FAIL A-009), not only a shape test. |
| **AR-002** Control-plane ownership / failover undefined | **CONFIRMED** | P0 | COC Arch §3, §24; Part XVI headline claim; Foundation "State ownership" + ADR-012 *Intentionally unresolved*. Handwritten p4 "desktop… main assistant's space if Macbook not available" = **promotion** with no election/lease. | Yes — single writable control plane + leases + standby + partition rules is the right call at this scale. | Must be stated as a **joint invariant with the alarm** (NV-06): the wake-alarm owner must survive the exact partition (MacBook leaves) that AR-002 describes. |
| **AR-003** No clock/ordering/consistency model | **CONFIRMED** | P0 | COC Arch §5,§7; DR-006 "available", not "ordered". Handwritten p4 intermittency profiles = designed partitions. ADR-001 unresolved. | Yes — HLC + at-least-once + per-(source,subject) order + supersession + TTL→UNKNOWN is correct and cheap. | Confidence/UNKNOWN handling in the *trigger evaluator* inherits this and is unaddressed (PC-2). |
| **AR-004** Absolute cost rule gated on untrusted inference | **CONFIRMED** but **re-prioritized** | P0 | SR-045/RB-016/RB-017 absolute; SR-029/DR-011/Arch §16 declare user-state "evidence, not facts". "Free-time" used ~14× as trigger, 0× as definition. | Yes (fail-closed `OperatingPeriod`). | **This and AR-005 are the same leak.** If AR-005's gateway choke point is correct and fail-closed, AR-004 errors reduce to *over*-restriction (recoverable). So **AR-005 is the true backstop and should be treated as the higher-priority of the pair.** |
| **AR-005** Fallback ladder has no cost-class filter | **CONFIRMED** | P0 | Arch §24 ladder: *classify → retry → alternate provider/model → local → escalate* — no cost predicate. Direct contradiction with RB-017. | Yes — `cost_class` mandatory on every credential/profile + single gateway choke point + filtered ladder. | Minor accuracy note: Claude quotes SR-001's pool as *"free APIs… plus separately authorized paid providers"*; that exact phrasing is an **interpretation gloss**, not SR-001 text (SR-001 = weak-hardware + API switching). The **mechanism** claim is nonetheless correct and directly verifiable. |
| **AR-006** Authorization is a taxonomy w/o a decision function; no spawn attenuation | **CONFIRMED** | P0 | Part VII = 6 levels + examples; no subject, no arg-sensitivity, no PDP location, no delegation rule. RB-028 forbids self-grant, is silent on **inheritance** (the real attack path). | Yes — explicit capability grant tuple + `effective_level = min(...)` + strict attenuation + fail-closed PDP. | Does **not** cover VESPER modifying its **own** code/policy outside the tool-authorization path — see NV-01. |
| **AR-007** Injection resistance is a disposition, not a mechanism | **CONFIRMED** | P0 | RB-025/T-002/DR-020 all describe outcome; no taint, no channel separation, no authority reduction under untrusted content. System browses unattended (SR-042/044) with shell (SR-021). | Yes — context tainting + authority ceiling by taint + channel separation + two-context research pattern. | Taint must survive **cache and summary** reuse (Claude says this) **and** the offline weak model is least able to resist injection (NV-07). |
| **AR-008** Autonomy trigger forbidden-by-negation, undefined-by-omission | **CONFIRMED** | P0 | Arch §4 "not by repeatedly asking an LLM to invent tasks"; §28 "not a cron job"; both prohibitions; ADR-009 unresolved. | Mostly — first-class `Trigger` registry with deterministic predicate is right. | "Deterministic predicate" over a **probabilistic/UNKNOWN** world model still hides fail-direction decisions (PC-2). And nothing proves triggers actually **fire unprompted in production** (NV-03). |
| **AR-009** Four "unresolved" ADRs on the critical path | **CONFIRMED** | P0 | Foundation *Intentionally unresolved* lists event transport, persistence, serialization, deployment topology; increment **#2 = "Event contract + durable task state"** depends on ADR-001/002. Verbatim contradiction. | Yes — reclassify blocking-irreversible vs deferred-reversible; time-boxed spikes whose deliverable is the ADR. | Correct and important. |
| **AR-010** Every enforcement point is prose; no artifact | **CONFIRMED** | process-P0 | Delivered package contains only `.md`/`.docx`. No repo, CI, CODEOWNERS, `contracts/`, schema registry. Immutability of SR layer is unprotected. | Yes, as far as it goes — but PATCH-010 mechanizes **process** gates (schema/ADR/traceability/immutability) and does **not** wire the **capability acceptance tests** (A-002/009/011…) as blocking gates (NV-09), nor cover VESPER-as-committer (NV-01). |

### P1 findings (audited; abbreviated where I concur)

| ID | My verdict | Note |
|---|---|---|
| **AR-011** SR registry drops load-bearing handwritten clauses (BAG-not-RAG, cache tiers, node availability profiles) | **CONFIRMED** | Verified: no SR carries "BAG instead of RAG," the five cache tiers, or the J3/desktop **intermittency** profiles. The dropped availability profiles ARE the partition-tolerance requirement, so AR-003 currently rests on an *inferred* requirement. Restoration (PATCH-011, owner action) is the only Part XIV-compliant treatment. |
| **AR-012** Part XI matrix is a bundle-join; falsifies Part XV "PASS" | **CONFIRMED** | Verified by inspection: all 51 verification cells contain the identical string "Acceptance test required"; DR coverage is dominated by DR-013 bolted onto ~15 SRs; DR-002/003/004 appear zero times; multiple Part V sections are referenced by no SR. Part XV's "traceability present: PASS" is therefore unsupported by its own matrix. |
| **AR-013** No SR↔acceptance-test map; 20 tests for 51 SRs | **CONFIRMED** | A-001..A-020 exist as prose; no SR names its acceptance test and vice-versa. |
| **AR-014** "No guessing" has no mechanism | **CONFIRMED / INCOMPLETE** | Correct. Misses that no-guessing fails *hardest* precisely on the offline weak local model (NV-07), where calibration/abstention is least available and most required. |
| **AR-015** Verifier named in six places, specified in none | **CONFIRMED / INCOMPLETE** | Correct. Misses the structural impossibility: under SR-045 (free-only) + Arch §13 (one model in memory on Neo) + SR-042 (overnight), planner and verifier **must be the same weak model** — verification collapses to self-check exactly when unattended (NV-02). This raises the effective severity toward **P0 for the autonomy safety case.** |
| **AR-016** Memory conflict detection/resolution undefined | **CONFIRMED** | IC-006 has `supersedes` but no conflict rule/order. |
| **AR-017** Hardware agnosticism stated 3×, implemented 0× | **CONFIRMED** | No `NodeCapabilityProfile` schema, no accelerator abstraction, product names in normative text (Arch §13 "MacBook Neo… unified memory"). |
| **AR-018** J3 admits two incompatible architectures; no enrollment admission | **CONFIRMED** | SR-018 "own OS/space" vs thin display endpoint. |
| **AR-019** World model has no keying/identity-resolution/spatial rep | **CONFIRMED** | Presence-by-proximity is unimplementable without it. Pairs with AR-003. |
| **AR-020** SR-026 "read kernel" unaddressed; Part XIV §3 not followed | **CONFIRMED** | |
| **AR-021** SR-039 narrowed without a recorded deviation | **CONFIRMED** | Needs owner deviation record + owner-administrative capability class. |
| **AR-022** Learning loop has no promotion/validation/rollback unit | **CONFIRMED** | Default impl violates RB-020 continuously while reading as compliant. |
| **AR-023** SR-047 unverifiable by construction (targets = whatever is measured) | **CONFIRMED** | |
| **AR-024** Four reqs jointly infeasible on min hardware; no latency arithmetic | **CONFIRMED** | Reported, not resolved, per mandate. SPIKE-002 measures it. |
| **AR-025** RB-005 vs RB-006 initiative conflict; no interruption budget | **CONFIRMED** | |
| **AR-026** Alarm: no priority lattice, no distributed ownership, no ceiling | **CONFIRMED / INCOMPLETE** | Misses the trusted-time dependency and the AR-002/AR-004 co-ownership invariant (NV-06). |
| **AR-027** Perception: no sensor lifecycle/consent/non-owner-person model | **CONFIRMED** | Extend to third-party legal scope (guests, through-wall, shared-network scanning) — NV-08 context. |
| **AR-028** Irreversible external actions: no outbox/reconciliation | **CONFIRMED** | The "rollback/compensation" field is undefined exactly where it matters most. |
| **AR-029** Excluded handwritten item carries no SR ID | **CONFIRMED** | Exclusions need an ID + recorded disposition. |

### P2/P3 findings

| ID | My verdict | Note |
|---|---|---|
| **AR-030** Two conflicting roadmaps / package relationship undefined | **CONFIRMED / INCOMPLETE** | Correct on roadmaps (Phase 0–10 vs F0–F8 vs "first 10 increments") and the B01–B10 vs B01–B08 benchmark-ID collision. **Misses the more dangerous collision: the `L0–L5` token is overloaded** — Foundation "Authority levels: L0 Observe; L1 Propose; L2 Implement; L3 Integrate; L4 Release" vs COC Part VII "L0 Observe … L4 Consequential action requiring confirmation; L5 Restricted." Same tokens, security-critical, incompatible meanings (NV-04). I raise this pair to **P1.** |
| **AR-031** Provider gateway lacks error taxonomy/quota/mid-stream semantics | **CONFIRMED** | |
| **AR-032** Resource-governor telemetry is a feedback loop with no damping | **CONFIRMED** | Model-visible, model-actionable loop can oscillate. |
| **AR-033** No cost-policy artifact → all paid usage unauthorized by default | **CONFIRMED / INCOMPLETE** | Correct. Misses that **daytime** paid usage has no spend ceiling, and SR-014's no-agent-count-limit + paid providers = unbounded daytime burn (NV-10). |
| **AR-034** iPhone capability envelope unmodeled | **CONFIRMED** | Compounds with platform-feasibility of SR-031 (NV-05). |
| **AR-035** Observability: no retention/sensitivity enforcement/PII handling | **CONFIRMED / INCOMPLETE** | Misses the immutable-event-log vs privacy-deletion contradiction (NV-08). |
| **AR-036** Repo layout has no home for contracts/schemas | **CONFIRMED** | Folded into PATCH-010. |

**Audit summary:** 0 REJECTED, 0 MISCLASSIFIED-as-too-high. All 36 findings are real. Refinements: **AR-004↓/AR-005↑** (one leak, gateway is the backstop); **AR-015 and the AR-030 L0–L5 pair should be raised** (P0-for-autonomy and P1 respectively); **AR-014/026/033/035 are INCOMPLETE** in the ways noted. The prior review's central claim (under-specified, not mis-designed; additive fix) **survives independent scrutiny.**

---

## 3. New Findings (independent search)

These are not in the prior review or its patch set. IDs prefixed **NV** (new-vulnerability).

### NV-01 — The overnight autonomy engine can recursively modify VESPER's own code, and the enforcement layer is designed only for human dev-agents · **P0**

- **Exact failure.** SR-042 authorizes unattended overnight work that may "make stuff, **read stuff, code stuff**." SR-048/SR-027 authorize VESPER to "learn… improve **his** actions/thinking/**LLMs/models/systems/abilities**." SR-049 declares its own code/system "sacred." These compose into **recursive self-modification**: the running autonomy engine has shell + filesystem (SR-021/022) and a mandate to improve its own systems, at night, unattended, on free models (the weakest, least-aligned, most injection-prone — AR-007/NV-07). Nothing in the corpus or in PATCH-010 restricts VESPER's *own* autonomy from writing to `core/`, `policy/`, `security/`, or the model/prompt configuration that governs it.
- **Evidence.** PATCH-010's immutability check protects **only the SR registry**. CODEOWNERS + branch protection are specified for **human** contributors pushing PRs (Baseline 01 §5 "no direct pushes to main"; Foundation "No direct agent writes to main" — but "agent" here means dev tooling agents, not the VESPER runtime). No document states that the VESPER *runtime* is itself bound by branch protection / CI / CODEOWNERS when it exercises its SR-042/SR-048 authority. AR-022's learning-promotion gate governs *learned parameters/procedures*, not *source-code commits by the running system.*
- **Why it builds the wrong thing / why it is dangerous.** The single most consequential actor with respect to "build the wrong VESPER" is VESPER modifying itself. An overnight agent that ingests an injected web page (AR-007) while holding self-improvement authority can alter its own policy or security code, and the change reads as "self-improvement," which is *authorized*. This is privilege escalation with a mandate.
- **Correction.** Declare an explicit invariant: **the VESPER runtime is a first-class subject of its own authorization and change-control.** Self-directed changes to `core/`, `policy/`, `security/`, `models/` config, system prompts, and the SR/COC layer are **L5** (direct human control) and must traverse the **same** CI/CODEOWNERS/immutability gates as any external contributor — i.e., the autonomy engine may open a proposal branch but may never self-merge to a running configuration. Free-time self-modification is prohibited outright (free models are the injection-weakest). Bind this to NV-02 and AR-007's authority ceiling.
- **Verification.** Adversarial test: an overnight agent under injection attempts to write `policy/` and to alter its own system prompt → assert both are blocked at the filesystem/tool boundary (not by prose), audited, and surfaced as a proposal requiring L5 human merge. CI test: no runtime code path can write to `core/|policy/|security/|models/config` outside the reviewed-merge path.

### NV-02 — Verifier collapse: SR-045 + Arch §13 + SR-042 make planner and verifier the same weak model exactly when unattended · **P0 (autonomy safety)**

- **Exact failure.** P-009/RB-004/SR-013 require verification to be a **separate** responsibility from planning ("a plausible response is not completion"). Arch §13 (Metal / "avoid keeping many models loaded at once," "smaller models for background tasks") plus SR-045 (free/local only in free-time) plus the MacBook-Neo unified-memory constraint mean that during overnight autonomy **only one small local model is resident.** Therefore planner, executor, and verifier are the **same** weak model. Self-verification by a single weak model is the **least** reliable verification configuration, and it is the one that governs **unattended, high-consequence overnight work** (SR-042/044).
- **Evidence.** COC Arch §13 bullets; SR-045/RB-016; Arch §11 "agent outputs are not trusted merely because another model produced them; verification remains separate" — a rule the free-time single-model configuration **cannot satisfy.** AR-015 correctly says the verifier is unspecified but does not surface this *structural* impossibility.
- **Correction.** Define a **verification-independence policy that degrades explicitly**: (1) where two distinct local models cannot co-reside, verification must use an *independent method* — deterministic checks against files/tests/tools/schemas (not model self-judgment) — and the task's `verification_criteria` (IC-007) must be **machine-checkable** for any task eligible to run unattended; (2) any free-time task whose acceptance condition is **not** machine-checkable is **ineligible for autonomous completion** and must be queued for a review pass when a stronger/independent model or the user is available; (3) record "verified-by: {independent-check | self-model | deferred}" in telemetry so a self-verified overnight result is never silently treated as accepted.
- **Verification.** A-011 extension: run an overnight job whose only available verifier is the planning model; assert the system either (a) verifies via deterministic checks, or (b) marks the result `unverified/deferred` and does **not** report success. Assert no free-time task with a non-machine-checkable acceptance condition is auto-completed.

### NV-03 — No liveness proof that the observe→decide→act loop runs unprompted; "one loop works" is satisfiable by a prompt-driven loop · **P1 (the direct anti-chatbot test)**

- **Exact failure.** The entire not-a-chatbot claim is that proactivity comes from a **continuous** loop (Part V §4, Part VI, §27 DoD "at least one complete… loop works"). But the acceptance criteria test that a loop **can** run, not that it **does** run without a user. A chatbot-with-extra-steps satisfies "one loop works" by running the loop once, in a demo, triggered by a human. There is **no liveness/heartbeat requirement, no dead-man's-switch, and no "zero-user-input" assertion** anywhere in the corpus or the patch set.
- **Evidence.** COC A-011/§27; Foundation "Mandatory vertical slice" — all describe a loop that executes, none require it to execute *unprompted on a cadence in production.* The prior review's own success criterion ("contract tests that can fail") checks shape, not liveness.
- **Correction.** Add a **production liveness invariant**: the autonomy loop emits a heartbeat event per evaluation cycle; a monitor asserts ≥ N autonomous evaluation cycles occurred with **zero user input** over a rolling 24h window, and that ≥1 of them produced a non-trivial decision (act *or* an explicitly recorded no-op with a trigger_id). Wire as a release gate and a runtime alert (loop-stopped is an incident).
- **Verification.** Endurance test: run VESPER 24h with no user interaction; assert heartbeat cadence, assert every action traces to a registered trigger (AR-008), assert at least one real autonomous action or recorded no-op occurred. A build where the loop only advances on user input **fails** this gate. **This is the single most decisive mechanical test against the chatbot outcome.**

### NV-04 — `L0–L5` authorization-vocabulary collision between the two engineering packages · **P1**

- **Exact failure.** The COC's Part VII / Arch §23 define `L0–L5` as the **capability-authorization ladder for actions** (L4 = "Consequential action requiring explicit confirmation," L5 = "Restricted / direct human control"). The Foundation doc **reuses the same tokens** for **agent authority levels**: "L0 Observe; L1 Propose; L2 Implement; L3 Integrate; L4 Release." An implementer reading "requires L4" cannot tell whether it means *a consequential action needing user confirmation* or *an agent permitted to cut a release.* This is a semantic collision on the **most security-critical vocabulary in the system.**
- **Evidence.** COC Part VII table; Foundation "Agent Organization & Governance → Authority levels." Both normative, both delivered as "current design," neither cross-references the other. (AR-030 caught the B01–B10/B01–B08 benchmark-ID collision but not this one.)
- **Correction.** Rename one axis. Recommended: keep `L0–L5` for **capability authorization** (it is anchored in the immutable COC) and rename the Foundation agent axis to `AG0–AG4` (or "review gates A–E," which the Foundation already uses elsewhere). Add a glossary with exactly one meaning per token, enforced by a docs-lint.
- **Verification.** Traceability-lint rule: the token `L4`/`L5` in any contract or task envelope must resolve to the capability ladder; agent-authority references must use the renamed axis. A collision is a CI failure.

### NV-05 — SR-031 "appear on my behalf" vs RB-012 "never deceptively impersonate" is an unrecorded immutable-layer contradiction · **P1**

- **Exact failure.** SR-031 requires VESPER to "call/FaceTime on the user's behalf and **appear on the user's behalf** on MacBook." Handwritten p5: "he should **show up on my behalf**." RB-012/DR-025 require: "Never deceptively impersonate the user… use appropriate delegated identity/attribution." Literally *appearing as the user* on a video/voice call is impersonation; RB-012 forbids it. This is the same class of internal contradiction as AR-005 (two immutable-layer artifacts in tension), and it is **not recorded** as such.
- **Evidence.** SR-031, RB-012, DR-025 (COC). Also compounds with **platform feasibility** (NV, below): stock iOS/macOS do not expose programmatic FaceTime call origination or "appear as user" video injection without private entitlements.
- **Correction.** Record the tension per Part XIV §3 (both stand). Resolve the *meaning*: "on the user's behalf" = **attributed delegated presence** ("This is VESPER calling for <User>"), never identity spoofing. Where a platform cannot express delegated attribution, the action is **narrowed** with an owner-approved deviation (like AR-021). Add a platform-feasibility spike for call/message origination on each target OS **before** committing SR-031 to a release.
- **Verification.** Every delegated communication carries explicit attribution metadata; a negative test asserts VESPER never originates a channel that presents the raw user identity without the delegated marker. Spike output: a per-platform feasibility record with a Part XIV §3 limitation entry where infeasible.

### NV-06 — The wake-alarm has no trusted-time source and no co-ownership invariant with the control plane and OperatingPeriod · **P1**

- **Exact failure.** The alarm (SR-043) is the one safety-critical, must-fire, may-be-loud function. It depends on (a) a **correct wall-clock time** and (b) a **guaranteed single owner** that survives partition. AR-003 correctly bans wall-clock for *ordering* but keeps it for "policy windows" — the free-time schedule and the alarm both run on wall clock. On a fabric containing a **drifting J3** and machines that sleep/roam, "06:30" is not a trusted instant, and the alarm owner may be the very node (MacBook) that left in AR-002's scenario. Nothing ties AR-002 (ownership), AR-004 (`OperatingPeriod`), and AR-026 (alarm) into one invariant. DST/timezone transitions are unmodeled.
- **Evidence.** SR-043; AR-003 "wall-clock retained for… policy windows"; AR-002 partition scenario; AR-026 (alarm ownership) does not mention time-source trust or DST.
- **Correction.** (1) Designate a **trusted time source** (NTP-disciplined, with a max-skew alarm) for policy windows and alarms; nodes exceeding a skew bound are ineligible to own an alarm. (2) State the invariant: **an authoritative alarm has exactly one owner at any instant, co-located with or failed-over alongside the control-plane lease, and fires on true scheduled time regardless of partition or user-presence inference.** (3) Model timezone/DST explicitly for schedule boundaries.
- **Verification.** Skew a node ±120s → assert it cannot own the alarm and the alarm still fires within tolerance from a disciplined owner; partition the alarm owner at 06:29 → assert failover fires the 06:30 alarm exactly once; run across a DST boundary → assert correct local fire time.

### NV-07 — "No guessing" is structurally weakest exactly where it is required most: offline, on the weak local model · **P1**

- **Exact failure.** RB-002/P-004/SR-041 make abstention-over-fabrication a defining, near-absolute behavior. Its enforcement depends on retrieval, tools, calculation, or calibrated uncertainty. In the **offline / free-time / weak-local-model** state (SR-001/SR-005/SR-045) — the state the whole project is *centered on* — web retrieval is gone, the BAG is limited to local sources, and the small model is the **most** prone to confident fabrication and the **least** capable of calibrated abstention. So the no-guessing guarantee degrades precisely in the operating mode where it is hardest to satisfy and where a human is least able to catch a fabrication (unattended overnight).
- **Evidence.** SR-005, SR-025, RB-002, Arch §13; AR-014 flags the missing mechanism generally but not this operating-mode asymmetry.
- **Correction.** Make no-guessing an **operating-mode-aware** requirement: in offline/weak-model mode, (1) require *evidence-backed* answers or explicit `UNKNOWN` — the model may not assert unretrievable facts; (2) raise the abstention threshold and prefer "queue until online / until stronger model" over answering; (3) tag every offline answer with its evidence basis so an online pass can re-verify. Tie to NV-02's deterministic-verification requirement.
- **Verification.** A-003 extension in offline mode: remove a required fact and remove network; assert the weak model returns `UNKNOWN`/deferral, not a fabrication; assert offline answers are tagged for later re-verification.

### NV-08 — Immutable event log / provenance vs privacy-deletion is an unresolved contradiction · **P2**

- **Exact failure.** IC-001 mandates **immutable past events**; IC-006 uses `supersedes` (append-only) and durable provenance. RB-024/DR-011/AR-027 require minimized retention and (implied) deletion of wrongly-captured sensitive perception, including images of **non-owner persons** (guests, through-wall RF, shared-network scans). An immutable, append-only log **cannot delete** a wrongly captured face or a third party's data while preserving the correlation chain. PATCH-017's "purge path" is asserted but collides head-on with IC-001 immutability and is not reconciled.
- **Evidence.** IC-001 "past events immutable"; IC-006 append-only; RB-024; AR-027/AR-035.
- **Correction.** Separate **event immutability** (integrity of the ledger) from **payload retention** (the sensitive content). Store sensitive perception **by reference**, keep the ledger entry immutable but make the referenced payload **purgeable**, and record purge as a new immutable event ("payload_purged", reason, authority) so the chain survives deletion. Define non-owner-person handling: default-sensitive, shortest retention, purge-on-review.
- **Verification.** Capture a guest's face → owner issues purge → assert payload is unrecoverable, ledger integrity intact, correlation chain still reconstructs, and a `payload_purged` event exists.

### NV-09 — Capability acceptance tests (A-001..A-020, +new) are never wired as blocking gates · **P1**

- **Exact failure.** Even after PATCH-010, the CI gates are *process* gates (schema-change-without-ADR, SR-referenced-in-PR, traceability-lint, immutability). The **capability** acceptance tests — A-002 persistence, A-009 presence migration, A-011 autonomy, A-014 security/injection, A-017 recovery — are not defined as executable, blocking release gates by any patch. They remain prose a team can hand-wave as "passed." This reproduces the exact defect the whole review is about, one level up.
- **Evidence.** PATCH-010 gate list; Foundation "Release blockers" (a prose list); no patch makes A-0xx executable/blocking.
- **Correction.** Every A-0xx (and NV-added A-021+) is a named, executable test fixture in `tests/acceptance/`, mapped 1:1 to its SR set (closing AR-013), and **blocking** at its release level. "Not implemented yet" is a release status (Part XIV §8), but a *claimed* pass with no executable fixture is a release blocker.
- **Verification.** Release-gate CI enumerates SR→A-test coverage and fails on any SR whose claimed status ≥ VERIFIED lacks a green executable fixture.

### NV-10 — No daytime spend ceiling; SR-014 no-agent-limit × paid providers = unbounded daytime burn · **P2**

- **Exact failure.** All cost discipline (RB-016/017, DR-013, AR-004/005) targets **free-time.** Outside free-time, paid usage is "allowed when a cost policy authorizes it," but there is **no budget/ceiling/alert artifact** and SR-014 imposes **no agent-count limit**. A daytime multi-agent fan-out on paid providers has no upper bound. T-014 (cost leakage) names the threat; nothing caps it.
- **Correction.** A `CostPolicy` artifact with hard daily/however-scoped ceilings, per-task and per-fan-out budgets, and a fail-closed stop at the same gateway choke point as AR-005. Alerts before ceiling.
- **Verification.** Drive a daytime fan-out toward the ceiling → assert the gateway halts new paid calls at the cap and reports, without corrupting in-flight tasks.

### NV-11 — Third-party / legal scope of surveillance and security-scanning is undefined · **P2**

- **Exact failure.** SR-037 (see through walls), SR-038 (find intruders/vulnerabilities on "network/connected hardware"), and camera perception can capture or probe **third parties and neighbors' devices** on shared infrastructure. "Authorized assets and scopes" (Arch §19) is prose with no scope object. On an apartment/shared network, vulnerability scanning (SR-038) can reach devices the owner has no authority over — a legal exposure, not just a privacy one.
- **Correction.** A machine-readable **authorized-scope object** (owned devices, owned network ranges, owned spaces) that bounds all scanning and RF sensing; anything outside scope is refused and logged; non-owner persons default to sensitive-minimal per NV-08. DR-031 already models the RF adapter as quarantined — extend its scope object to SR-038.
- **Verification.** Point SR-038 scanning at an out-of-scope host → assert refusal + audit; RF sensing outside authorized space → assert disabled.

---

## 4. Traceability Audit

I re-ran the audit against the source text; I concur with the prior review's machine analysis and add structural notes.

- **SR → architecture:** Part XI maps each SR to "Architecture N" (COC Part V sections) but the mapping is a **coarse bundle-join**: DR-013 is bolted onto ~15 SRs; DR-002/003/004 (the identity/world/presence requirements that define the system) appear **zero** times; several Part V sections are referenced by no SR. **CONFIRMED (AR-012).**
- **SR → verification:** All 51 rows carry the identical placeholder "Acceptance test required." **There is no SR↔A-test mapping in either direction.** 20 acceptance tests are implicitly claimed to cover 51 SRs with no stated correspondence. **CONFIRMED (AR-013).** Part XV's "Source-to-architecture traceability present: PASS" is therefore **not supported by its own matrix** — a self-falsifying release-gate record.
- **Handwritten → SR (lossless projection):** Several load-bearing handwritten clauses have **no SR**: "BAG instead of RAG," the five cache tiers, and — most importantly — the **node availability/intermittency profiles** ("J3… may be offline"; "Desktop… may be disconnected"), which *are* the partition-tolerance requirement. Because they were dropped, AR-003's partition requirement is inferred, not stated. **CONFIRMED (AR-011).** One excluded handwritten item has no ID/disposition (**AR-029**).
- **Engineering package → source:** **Two** engineering specifications (Baseline 00–07 and the Foundation doc) both claim to derive from COC v1.1, with **no stated precedence** and **divergent** role taxonomies, phase schemes (Phase 0–10 / F0–F8 / "first 10 increments"), release ladders (DEV…V0-STABLE / R0–R5), benchmark IDs (B01–B10 vs B01–B08), **and the `L0–L5` authorization tokens (NV-04).** An implementer cannot determine which governs. **CONFIRMED + EXTENDED (AR-030 → NV-04).**
- **New traceability requirement:** the chain must extend to **executable** artifacts: `SR → arch → contract(schema) → module/owner → executable A-test → release evidence`, enforced by `traceability-lint`, with **no cell allowed to hold a placeholder string** (NV-09 + PATCH-012).

**Net:** applying the mandate's own PASS rule (an SR passes only with both an implementation path and a verification path), the corpus today has **near-zero** SRs that fully pass — not because the requirements are absent, but because the verification side of every row is a placeholder. Traceability is **RED**.

---

## 5. Exact Remediation Plan

I adopt the prior review's PATCH-001…017 (they are well-formed and I re-verified their coverage), with the **strengthenings** and **additions** below. Where I add, I note whether it is engineering-only or requires **owner** action (immutable layer).

### Patch-effectiveness critiques (must be applied or the patch under-delivers)

- **PC-1 (strengthen PATCH-005 / AR-001).** A `SemanticScene` shape test does not stop the degenerate "one giant `text` element" chatbot. Add a **behavioral** gate: A-009 must render the same scene on two endpoints with **materially different capability descriptors**, assert **explicit degradation reports**, and **fail** any scene where a single unstructured text/markdown element carries the substantive payload. Ban a markdown escape hatch by test, not by convention.
- **PC-2 (strengthen PATCH-006 / AR-008).** "Deterministic trigger predicate over the world model" still hides fail-direction decisions because world-model facts are probabilistic/UNKNOWN/conflicting (AR-003). Require every trigger predicate to declare its **confidence threshold** and its **UNKNOWN-handling** (fire / don't-fire / defer), and apply AR-004's **fail-closed asymmetry** to any trigger that authorizes cost or external action.
- **PC-3 (strengthen PATCH-010 / AR-010 → NV-09).** PATCH-010 mechanizes *process* gates only. Add: every A-0xx acceptance test is an **executable, blocking** fixture mapped 1:1 to its SRs; a claimed status ≥ VERIFIED with no green fixture fails the release gate.
- **PC-4 (extend PATCH-010 / NV-01).** The VESPER **runtime** is a subject of its own change-control. No runtime code path may write to `core/|policy/|security/|models-config|SR/COC` outside the reviewed-merge path; free-time self-modification is prohibited. This is a CI test *and* a filesystem/tool-boundary enforcement, not prose.
- **PC-5 (extend PATCH-008 / NV-02).** Verification independence must **degrade explicitly**: unattended tasks require machine-checkable `verification_criteria`; non-checkable free-time tasks are ineligible for autonomous completion and are deferred; telemetry records `verified-by`.

### New patches

| New patch | Closes | Owner? | One-line deliverable |
|---|---|---|---|
| **PATCH-018** | NV-01, PC-4 | Eng (+owner sign-off on L5 self-mod policy) | Runtime-as-subject-of-change-control invariant + boundary enforcement + no free-time self-mod. |
| **PATCH-019** | NV-02, PC-5 | Eng | Verification-independence degradation policy; machine-checkable acceptance gate for unattended tasks. |
| **PATCH-020** | NV-03 | Eng | Autonomy **liveness/heartbeat** + zero-user-input 24h endurance gate (the direct anti-chatbot test). |
| **PATCH-021** | NV-04 | Eng | Rename Foundation agent axis (`AG0–AG4`); reserve `L0–L5` for capability authorization; glossary + docs-lint. |
| **PATCH-022** | NV-05 | **Owner** (Part XIV §3 record) + Eng | Delegated-attribution semantics for SR-031; per-platform feasibility spike; narrowing where infeasible. |
| **PATCH-023** | NV-06 | Eng | Trusted time source + alarm/control-plane/OperatingPeriod co-ownership invariant + DST/timezone model. |
| **PATCH-024** | NV-07 | Eng | Operating-mode-aware no-guessing (offline abstention + evidence-tagging + defer-to-online). |
| **PATCH-025** | NV-08 | Eng (+owner privacy defaults) | Split event-immutability from payload-retention; purgeable referenced payloads + `payload_purged` event. |
| **PATCH-026** | NV-09, PC-3 | Eng | Executable, blocking A-0xx gates with 1:1 SR mapping. |
| **PATCH-027** | NV-10 | Eng (+owner sets numbers) | `CostPolicy` daytime ceilings/budgets/alerts at the gateway choke point. |
| **PATCH-028** | NV-11 | Eng (+owner scope) | Machine-readable authorized-scope object bounding SR-037/SR-038 sensing/scanning. |

### Corrected execution order (supersedes/extends the prior "Execution order")

1. **Week 0 — enforcement first.** PATCH-010 **+ PC-3/PC-4** (repo, CI, CODEOWNERS, `contracts/`, immutability gate, **executable acceptance-gate harness**, **runtime-as-subject** boundary). Nothing else starts until an SR edit, a schema-change-without-ADR, an out-of-scope write, **a claimed-but-unbacked acceptance pass**, and **a runtime write to `policy/`** all fail CI.
2. **Week 0–1 — the irreversible ADRs (blocking).** PATCH-001 (clock/order/delivery/supersession → ADR-001), PATCH-002 (topology/ownership/failover → ADR-002/012). Launch SPIKE-001 (hardware) and SPIKE-002 (latency) in parallel; **add a per-platform telephony/presence spike (PATCH-022).**
3. **Week 1–2 — the security backstops.** PATCH-003 (authorization + injection ceiling), PATCH-004 (`OperatingPeriod` + cost class; **gateway choke point is the load-bearing backstop — AR-005 > AR-004**), PATCH-018 (runtime self-mod), PATCH-027 (daytime cost), PATCH-009 (node profiles/enrollment).
4. **Week 2 — the three defining artifacts + their behavioral tests.** PATCH-005 **+ PC-1** (`SemanticScene` + degenerate-scene negative test), PATCH-006 **+ PC-2** (`Trigger` + confidence/UNKNOWN handling), PATCH-007 (world keying + spatial + privacy), PATCH-020 (liveness gate), PATCH-023 (trusted time/alarm).
5. **Week 2–3 — verification & continuity.** PATCH-008/019 (evidence envelope, verifier degradation), PATCH-014 (learning promotion), PATCH-016 (alarm/outbox), PATCH-025 (purge), PATCH-024 (offline no-guessing).
6. **Owner track (parallel, cannot be done by engineering).** PATCH-011 (restore dropped SRs incl. the **partition-tolerance SR**), PATCH-012 (rebuild Part XI/XV), PATCH-013 (SR-026/SR-039 deviations), PATCH-021 glossary sign-off, PATCH-022/025/028 owner policies.
7. **Then** begin Foundation increment #1.

**Discipline that makes the plan real (both the prior review and I insist on this):** every correction lands as **a schema, a state machine, a decision function, or an executable test that can fail** — and, per PC-1/PC-3/NV-03, **at least one of those tests must be behavioral/runtime, not merely shape-checking.** A patch acknowledged and then implemented as prose reproduces the original defect exactly.

---

## 6. Build Readiness Matrix

Ratings are against the corpus **as delivered** (GREEN = meets the Baseline's own nine-dimension readiness bar; YELLOW = sound, additive paper fix; RED = missing decision forces rework or the defining artifact is absent). I concur with the prior distribution and adjust three cells (↑ = I rate more severe than prior).

| Subsystem | Rating | Blocking finding(s) |
|---|---|---|
| Engineering process / repository / enforcement | **RED** | AR-010, NV-01, NV-09 |
| Persistent runtime / lifecycle | **RED** | AR-002, AR-009 |
| Event bus / coordination substrate | **RED** | AR-003, AR-009 |
| Identity & continuity (control-plane) | **RED** | AR-002 |
| World model | **RED** | AR-003, AR-019 |
| Presence engine (semantic scene) | **RED** | AR-001 (+PC-1) |
| Spatial / holographic contracts | **RED** | AR-001, AR-019 |
| Autonomy engine (trigger + liveness) | **RED** | AR-008, AR-004, NV-03 |
| Planner / **verifier** | **RED** ↑ | AR-015 **+ NV-02** (raised toward P0-for-autonomy) |
| Learning loop | **RED** | AR-022, NV-01 |
| BAG / retrieval | **RED** | AR-011, AR-014, NV-07 |
| Tool gateway / action | **RED** | AR-006, AR-007, AR-028 |
| Security / authorization | **RED** | AR-006, AR-007, AR-018, NV-01 |
| Traceability | **RED** | AR-011, AR-012, AR-013, NV-09 |
| Model gateway / provider fabric | **YELLOW** | AR-005, AR-031, NV-10 |
| Model router | **YELLOW** | AR-013, AR-033 |
| Task system | **YELLOW** | (IC-007 transition table/guards) |
| Resource governor | **YELLOW** | AR-032, AR-024 |
| Observability | **YELLOW** | AR-035, NV-08 |
| Agent runtime / orchestration | **YELLOW** | AR-006 (attenuation) |
| Research engine | **YELLOW** | AR-007, AR-014, NV-02 |
| Memory | **YELLOW** | AR-016, NV-08 |
| Context management | **YELLOW** | AR-007 (taint), manual-mode untested |
| Caches | **YELLOW** | AR-011, AR-007 (tainted-summary) |
| Perception pipeline | **YELLOW** | AR-027, NV-11 |
| Device fabric / network | **YELLOW** | AR-017, AR-018 |
| Alarm / intervention | **YELLOW** ↑-risk | AR-026, **NV-06** (trusted time + co-ownership) |
| Communications / delegated presence | **YELLOW** | AR-028, **NV-05** (impersonation contradiction) |
| Recovery / backup | **YELLOW** | failure matrix ~53% UNDEF |
| Change control | **YELLOW** | AR-020, AR-010, NV-04 |
| Verification & release | **YELLOW** ↑ | AR-013, AR-023, **NV-09** (no executable blocking gates) |
| Model/tool governance | **GREEN** | (only the B01–B10/B01–B08 + NV-04 vocabulary collisions to clean up) |

**Distribution:** **1 GREEN, ~17 YELLOW, 14 RED.** The RED cluster is still produced by a small number of decisions — the four coordination/topology ADRs, the three defining artifacts, and security-under-autonomy — **plus two I add: runtime-self-modification governance (NV-01) and executable acceptance gates (NV-09).** Every RED is closable additively.

---

## 7. JARVIS Divergence Report

For each subsystem: *could a literal, optimization-driven engineer satisfy the documents while shipping ordinary chatbot behavior?* **Yes** everywhere the enforcement is prose. The exact bypass and the artifact that closes it:

| Subsystem | Chatbot-compatible implementation that passes the docs | Artifact that forecloses it |
|---|---|---|
| **Presence** | `scene = {markdown, speech}`; A-009 "two surfaces" = same markdown at two font sizes | `SemanticScene` schema **+ behavioral negative test that fails a single-text-element scene** (AR-001 + PC-1) |
| **Autonomy trigger** | periodic LLM prompt "anything to do?" wrapped to look structured | deterministic `Trigger` registry; every action traces to one `trigger_id`; **no action from a model call not preceded by a trigger** (AR-008 + PC-2) |
| **Autonomy liveness** | run the loop only when the user prompts; demo "one loop works" | **heartbeat + zero-user-input 24h endurance gate** (NV-03) — *the* decisive test |
| **World model** | a JSON blob overwritten last-write-wins | HLC + supersession + keying + `world.conflict` events (AR-003/019) |
| **Continuity** | singleton on the MacBook; "survives restart" = process restart on one box | control-plane leases + failover + partition rules; A-002/A-017 fault-injection (AR-002) |
| **Verification** | the same model rsubjectively "checks" its own output | machine-checkable `verification_criteria`; unattended non-checkable → deferred (NV-02) |
| **No-guessing** | weak offline model answers confidently | operating-mode-aware abstention + evidence tags (NV-07) |
| **Injection defense** | "the model treats content as data" | context taint + authority ceiling + channel separation + CI injection corpus (AR-007) |
| **Free-time cost** | walk the fallback ladder onto a paid key at 2am | `cost_class` + gateway choke point + fail-closed `OperatingPeriod` (AR-005/004) |
| **Self-improvement** | overnight agent edits its own `policy/` and calls it "learning" | runtime-as-subject-of-change-control (NV-01); promotion gate (AR-022) |
| **Authorization** | ambient authority; L4 grant inherited by six spawned agents | explicit grants + `min()` decision fn + strict attenuation + fail-closed PDP (AR-006) |
| **Interface identity** | ship the chat box as the primary surface | RB-007/§28 + **the presence + liveness tests above**; chat-is-not-default must be a *tested* property, not an assertion (AR-013 → NV-09) |

**Divergence conclusion:** VESPER has **not** degraded in intent — the COC argues against the chatbot outcome more explicitly and correctly than most specifications of this ambition. It currently has **no mechanism** that would prevent the degradation in practice. The prior review located this precisely at three artifacts; my independent pass confirms those three and adds that even specifying them as **schemas** is insufficient — the property is a **runtime behavioral** one, and the corpus/patch-set lack the runtime assertions (liveness, real migration, degenerate-scene rejection, unattended verification) that actually make "not a chatbot" *checkable*. Those runtime gates (NV-03, PC-1, NV-02, PC-3) are the ones most likely to be quietly dropped as "we'll test that when we build presence/autonomy," and that deferral is the single decision that turns VESPER into a chatbot with extra steps.

---

## 8. Final Verdict

The architecture is **correct and worth building**: the plane decomposition, the dependency-direction rule (which makes model/provider/device replaceability real rather than aspirational), Event/Command/Result separation with "a command is never proof," the trust zones, the L0–L5 capability ladder, the threat register, and the contract inventory are the right *shape*. **Not one P0 or P1 finding — prior or new — requires abandoning a structural decision.** Every correction adds a schema, a state machine, a decision function, or an executable test beneath a boundary already correctly drawn.

But **as delivered the corpus is a taxonomy, not a specification.** It names every subsystem VESPER needs and defines the boundary between almost none of them precisely enough that two engineers build compatible halves. Its verification layer is a wall of placeholders; its enforcement layer does not exist; the three artifacts that make it not-a-chatbot are one sentence each; and — beyond the prior review — its overnight self-improvement authority is ungoverned (NV-01), its unattended verification is structurally self-referential (NV-02), and nothing proves its defining loop ever runs unprompted (NV-03). Two immutable-layer contradictions (AR-005 cost, NV-05 impersonation) and one security-vocabulary collision (NV-04) remain unrecorded.

**Do not begin implementation against the corpus as delivered.** Execute the corrected, additive program in §5 — the ten prior patches **strengthened by PC-1…PC-5** and the eleven new patches (PATCH-018…028), with the **owner-track** items (restore the partition-tolerance SR and the other dropped source; rebuild traceability; record the SR-026/031/039 deviations) handled as an additive **COC v1.2**, since I did not and may not modify the immutable layer. The blocking core is roughly two to three weeks of **decision work** (four coordination/topology ADRs, three defining-artifact schemas, the authorization/injection/cost backstops, the runtime-self-mod boundary, and the executable+liveness test harness), plus three parallel spikes (hardware, latency, per-platform telephony/presence).

Two standing caveats, per the corpus's own discipline (Baseline 03 §8, and honesty about scope): I audited against the transcription embedded in v1.1 Part I, not the original photographed pages; and this remains a single-model pass — AR-001…AR-010 and NV-01…NV-03 in particular should be re-derived by an independent model family or a human architect before they are treated as settled. That is not a hedge on the verdict; it is the verification requirement the mandate itself imposes.

If, and only if, every P0 and P1 above (prior + new) lands as an artifact that **can fail** — including at least the four **runtime/behavioral** gates (liveness NV-03, degenerate-scene rejection PC-1, unattended-verification NV-02, executable acceptance gates NV-09), not merely shape-checking contract tests — then VESPER is sufficiently architected to begin implementation without knowingly accepting ambiguity likely to cause major rework.

**Decision:**

```
BUILD_AFTER_CORRECTIONS
```
