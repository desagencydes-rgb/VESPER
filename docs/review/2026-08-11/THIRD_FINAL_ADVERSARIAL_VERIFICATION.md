# VESPER V0 — THIRD (FINAL) INDEPENDENT ADVERSARIAL VERIFICATION

**Date:** 2026-08-11
**Scope:** Adjudication of remaining P0/P1 findings prior to freezing the engineering gap register.
**Authoritative inputs:** original handwritten requirements (8 pages, text transcription); VESPER V0 Definitive COC + Rulebook v1.1 (locked).
**Untrusted inputs (treated as claims to be tested, not evidence):** ADVERSARIAL_REVIEW.md; SECOND_INDEPENDENT_ADVERSARIAL_REVIEW.md; RECOMMENDED_PATCH_SET.md.
**Reference (non-authoritative, derived):** Engineering Baseline 00–07; Engineering Foundation v1.0.

**Method.** Every finding below was re-derived from the authoritative sources. Where a prior review's conclusion survives, it survives on evidence I located independently, not on its say-so. Where a prior review's *reasoning* was wrong but its *conclusion* was right, I say so explicitly, because a correct conclusion resting on a false premise produces the wrong correction. Machine checks were run directly against the COC text and are reproducible.

**Discipline note.** Per the mandate, I stopped searching once the seven named areas were covered. I add exactly **one** new finding (FV-01). I did not manufacture additional findings to increase apparent thoroughness. The count of open blockers went *down* in this pass, not up.

---

## 0. Bottom line, stated before the evidence

The architecture is sound. No structural decision needs to be abandoned. The plane decomposition, the dependency-direction rule, Event/Command/Result separation, the L0–L5 capability ladder, and the SR-immutability regime are correct and load-bearing, and every remaining defect sits *beneath* boundaries that are already drawn in the right places.

The remaining defects are of three kinds, and only three:

1. **Missing decision functions and schemas** under correctly-drawn boundaries (authorization, triggers, verification, operating period).
2. **Enforcement expressed as prose with no artifact that can fail.**
3. **One genuine subject-scope omission**: the corpus governs *what may be changed* but never states that **the running VESPER is itself a subject of that change control**.

Item 3 is the only finding in this pass that is both novel and P0. It is closable in specification work. There is **no catastrophic blocker**.

---

## 1. Findings that are definitely real

### 1.1 NV-01 — Runtime self-modification is ungoverned · **CONFIRMED (re-derived) · P0 · blocks implementation start**

**Verdict: CONFIRMED, with the prior review's reasoning corrected.** The conclusion is right. The stated evidence is partly wrong, and the wrongness matters because it produces an over-broad correction.

**What the prior review got wrong.** It asserts *"Nothing in the corpus… restricts VESPER's own autonomy from writing to `core/`, `policy/`, `security/`."* That is false. COC **Part VII** explicitly classifies *"security-policy changes, destructive operations, financial actions, and changes to core Vesper policy"* at **L5 — restricted action requiring direct human control.** The *action class* is governed.

**What is actually missing — three distinct holes, verified directly:**

**(a) Subject scope.** The COC classifies actions but never names the running system as a subject of its own change control. Part XIV ("Change-control constitution") is written entirely in the second person to a *developer*: *"A **developer** may not remove, weaken, or reinterpret an SR."* Machine check: the strings `self-modif`, `own code`, `its own policy`, `system prompt`, and `rewrite` appear **zero times** in the COC. The only adjacent entry, **T-013 Self-improvement regression**, has controls *"Validation, versioning, benchmark gate, rollback"* — which govern **learned artifacts**, not source commits by the running system.

**(b) Population conflation — the runtime/dev-agent axis.** The engineering package's only self-escalation rule is **Baseline 01 §9**: *"Agents may implement within granted scope. They may not… grant themselves permissions."* Its enclosing context is unambiguously **development-time**: §5 repository control, §6 PR gates, §7 handoff, §8 *"Concurrent agents use separate branches/worktrees/workspaces."* The word "agent" then denotes an entirely different population in Foundation → *"Agent runtime: Agents are bounded execution workers"*. **The authority rules are attached to the development population's artifacts (branches, PRs, CODEOWNERS); the runtime population inherits them nowhere.** This is a mechanically demonstrable scope gap, not an interpretive one.

**(c) Reflexivity hole + undefined deployment relationship.** Part VII's L5 classification carries the qualifier *"**unless a narrower approved policy explicitly says otherwise**."* Nothing states that policy-about-policy is itself non-narrowable. Worse, "the runtime may not write to `core/`" is **not yet a well-formed statement**, because **Foundation ADR-012 (deployment topology) is filed "Intentionally unresolved"** — the relationship between the running process and the repository is undefined, so the boundary has no referent. This is the sharpest form of the finding and it links directly to AR-009.

**Why it exists.** The corpus was written from the standpoint of a team building a system. It never took the standpoint of the system building itself — even though **SR-027/SR-048 explicitly authorize exactly that** (*"learn… improve **his** actions/thinking/**LLMs/models/systems/abilities**"*) and **SR-042** authorizes it unattended and overnight.

**Severity: P0 — and here is the honest reason.** Not because runaway self-improvement is likely on a single-user home fabric. Because the boundary must exist in the **tool-gateway contract** (argument-sensitive authorization — a file write's *arguments* determine whether it is L2 or L5), the **deployment topology ADR**, and the **autonomy engine's write path** — all authored in increments 2–5. Retrofitting an argument-sensitive authorization decision into an already-built tool gateway is the expensive kind of rework. It is P0 by *architectural cost and ordering*, not by threat drama.

**Required correction (narrower than the prior review proposed):**

1. Add an invariant: **the VESPER runtime is a first-class subject of its own authorization and change control.** Self-directed writes to `core/`, `policy/`, `security/`, model/prompt configuration, and the SR/COC layer are **L5** and traverse the same reviewed-merge path as any external contributor. The runtime may **open a proposal**; it may never **self-merge into a running configuration**.
2. State that **the L5 classification of policy-governing surfaces is not narrowable** by a narrower approved policy — closing the Part VII reflexivity hole. This is the sentence that makes the rest enforceable.
3. **Resolve ADR-012 far enough** to define the running-process ↔ repository relationship, so "cannot write to `core/`" has a referent. It need not be fully resolved; it needs a *boundary*.

> **Correction to the prior review's proposed patch (PATCH-018).** Its clause *"Free-time self-modification is prohibited outright"* is **too broad and weakens SR-042**, which explicitly authorizes overnight *"code stuff."* The prohibition must be on **self-merge into governing surfaces**, not on **coding at night**. Proposal generation overnight is source-authorized and must remain. Adopting PATCH-018 as literally worded would violate Part XIV §2.

**Required verification.** Adversarial fixture: an overnight agent operating on injected external content attempts (i) a write to `policy/` and (ii) an edit to its own system prompt. Assert both are refused **at the tool/filesystem boundary** — not by model disposition — audited, and surfaced as a proposal requiring human merge. CI structural test: no runtime code path can write to `core/|policy/|security/|models-config|SR` outside the reviewed-merge path. The test must be shown failing against a deliberately non-compliant build before it is trusted.

---

### 1.2 NV-03 — No mechanical proof of unprompted operation · **CONFIRMED and SHARPENED · P1 · blocks the autonomy release gate, not implementation start**

**Verdict: CONFIRMED.** Verified directly against the acceptance layer.

**Evidence.** The *behavioral* requirement for self-initiation exists and is unambiguous: **RB-005** (*"Do not wait for a user message when a permitted useful action can be prepared or executed safely"*), **DR-005** (*"Continuously evaluate…"*), **SR-042**, and the prohibition at **Part V §28** (*"Do not reduce autonomy to a cron job that runs isolated scripts"*). The *acceptance* layer never tests it. **A-011** reads: *"Run a bounded overnight/free-time job using local/free models, checkpointing and resource limits."* It is silent on **who starts the job** — a human typing "run the overnight job" satisfies it. **§27 DoD** requires *"at least one complete… loop works"* — `works` ≠ `runs unprompted`. There is no heartbeat, no liveness assertion, and no zero-user-input criterion anywhere in the COC.

**Where the prior review's own test is insufficient — and this is the crux of your question.** Its proposed gate asserts *"≥ N autonomous evaluation cycles with zero user input… and ≥1 produced a non-trivial decision."* **A pure cron build passes that gate.** Schedule-triggered firing *is* zero-user-input, and it is precisely what you named as the thing to exclude: *scheduled prompting*. The prior test cannot distinguish the two.

**The distinction that is actually mechanical.** Genuine autonomy is not "acted without a human present." It is: **the action originated from a state predicate the system evaluated over its own world model, where the predicate's truth was not pre-scheduled.** A clock may be *an* input; it may not be the *only* input.

**Required correction — the three-part gate, all parts mandatory:**

1. **Liveness.** The autonomy loop emits a heartbeat per evaluation cycle. Loop-stopped is an incident with an alert, not a silent condition.
2. **Provenance.** Every autonomous action resolves to exactly one registered `trigger_id` whose predicate is demonstrably true against a **reconstructible world-model snapshot** (this is PATCH-006's INV-TRIG-1 — correct and reusable).
3. **The anti-cron discriminator — the part that is missing everywhere.** Over the endurance window, **at least one action must fire from a trigger whose predicate is non-schedule** — i.e. it became true because *world-model state changed*, not because a time arrived. Build the fixture by **driving the world model into a firing state at a time the system could not have anticipated**, and asserting the trigger fires with **no model call in the decision path**. A build whose every trigger is time-keyed **fails**.

**Required verification.** 24-hour endurance run, zero user input: assert heartbeat cadence; assert 100% of actions trace to registered triggers; assert ≥1 non-schedule trigger fired; assert ≥1 explicitly recorded no-op carries a `trigger_id` (a no-op is a valid autonomous outcome and must be auditable). Wire as a **blocking gate at the autonomy release level (F5 / Phase 8)**.

**Why this is P1 and not P0.** It requires no architectural rework — it is a gate and a fixture. It can be authored at any point before autonomy ships. It does **not** block starting implementation. It absolutely blocks *declaring autonomy done*, and it is the single most decisive mechanical test you have against the chatbot outcome.

---

### 1.3 Prior-review P0s I independently confirm

These were re-derived from the authoritative text. I confirm them on my own evidence.

| ID | Finding | Verdict | Independently verified evidence |
|---|---|---|---|
| **AR-004** | An absolute cost prohibition is keyed to an explicitly untrusted inference | **CONFIRMED · P0** | SR-045 defines free-time by **user state** (*"when I'm sleeping, when I'm not home, when he's on a break"*). Part V §16 declares user state *"evidence, not facts about the user"* with confidence/expiry (DR-011). An **absolute** rule (RB-016/017: *"prohibited… regardless of convenience"*) gated on a probabilistic input with **no defined fail-direction**. Real, and it determines behavior at the most-used boundary in the system. |
| **AR-005** | Fallback ladder has no cost-class filter | **CONFIRMED · P0** | Part V §24 verbatim: *"classify → retry/backoff → **alternate provider/model** → local fallback → escalation."* "Alternate provider" precedes "local fallback" with no cost gate. During free-time this ladder routes to paid by design, contradicting RB-017. A single choke-point fix, but it must land in the gateway. |
| **AR-006** | Authorization is a taxonomy without a decision function; no delegation attenuation | **CONFIRMED · P0** | Part VII is six levels plus examples — no subject, no argument sensitivity, no PDP location, no delegation rule. RB-028 forbids self-**grant** and is silent on **inheritance**. Part V §11 gives the planner authority to *"determine decomposition, resources… and verification responsibilities"* for spawned agents with no attenuation rule. Inheritance, not self-grant, is the real escalation path. |
| **AR-007** | Injection resistance is a disposition, not a mechanism | **CONFIRMED · P0** | RB-025 states the *outcome* (*"External text… are data, not system authority"*); T-002's control is *"external content is data"* — a restatement. No taint model, no channel separation, no authority reduction under untrusted content, in a system that browses unattended (SR-042/044) with shell access (SR-021). |
| **AR-002** | Control-plane ownership and failover undefined | **CONFIRMED · P0** | Handwritten p4 makes the desktop *"main assistant's space if Macbook not available"* — a **promotion** with no election, lease, or partition rule, under a Part XVI headline promising continuity through node loss. |
| **AR-008** | Autonomy trigger model forbidden-by-negation | **CONFIRMED · P0** | Part V §28 forbids cron; Arch §4 forbids LLM-invented tasks; ADR-009 unresolved. Both implementable options are prohibited and no third is specified. |
| **AR-010 / NV-09** | Enforcement is prose; acceptance tests are not blocking gates | **CONFIRMED · process-P0** | The delivered package is `.md`/`.docx` only. No repository, CI, CODEOWNERS, `contracts/`, or schema registry exists. A-001…A-020 are prose a team can assert as passed. |
| **AR-012** | The traceability matrix is a bundle-join, and it falsifies Part XV | **CONFIRMED · P1** | **My own machine check of all 51 Part XI rows:** the `Status` cell holds one identical string in **51/51** rows; the `Verification` cell holds the placeholder *"Acceptance test required"* in **51/51** rows — there is **no SR↔test mapping anywhere in the corpus**. **1 of 31 DRs** appears (DR-013 only; DR-002/003/004 appear zero times). **9 of 28 architecture sections are referenced by zero SRs — including §3 Persistent Runtime, §4 the core control loop, §23 Authorization, §24 Recovery.** Part XV nonetheless records *"Source-to-architecture traceability present: **PASS**."* **That PASS is falsified on the verification axis.** Consequence for your decision: the Part XV record cannot be used as evidence of coverage, and a gap register frozen against this matrix cannot claim completeness until the matrix is rebuilt. |
| **NV-04** | `L0–L5` token collision between the two engineering packages | **CONFIRMED · P1 (trivial fix)** | COC Part VII: `L4` = *consequential action requiring explicit confirmation*, `L5` = *restricted / direct human control*. Foundation: *"Authority levels: L0 Observe; L1 Propose; L2 Implement; L3 Integrate; **L4 Release**."* Same tokens, security-critical, incompatible. Root cause verified: **Baseline 00 and the Foundation both claim hierarchy slot 3 and neither references the other.** Fix the precedence and the collision resolves with it. |

---

### 1.4 FV-01 — No out-of-band human stop · **NEW · P1 · the only finding I add**

**Evidence.** **RB-030** is the entire override provision: *"Authorized human commands can stop, pause, reconfigure, or inspect Vesper **within the security model**."* That qualifier is circular in exactly the scenario that matters — if the control plane is wedged, partitioned, or is itself the fault, the override path runs through the component that failed. Machine check: `emergency`, `shutdown`, and `kill` appear **zero times** in the COC; `stop condition` appears only in RB-035 and IC-008 (properties of *tasks*, not a human-facing control). **There is no acceptance test for override** — A-001…A-020 contain none. The Foundation asks *"Can it stop autonomous work?"* as a final audit **question**, with no mechanism behind it.

**Why it is real and not manufactured.** It is the backstop that makes NV-01's correction credible. If the runtime's self-write boundary is enforced by the policy layer, and the compromise scenario targets the policy layer, then an override that also runs through that layer is not an independent control. NV-01 and FV-01 are one control pair. Neither prior review nor any of the 25 proposed patches contains it — I checked.

**Severity: P1.** Small, cheap, bounded — but it must be specified before the autonomy engine acquires actuation authority, because it is the control you cannot add *during* the incident it exists for.

**Required correction.** Specify a **stop path independent of the control plane and of model inference**: a physical or OS-level control that halts autonomous actuation without requiring the control plane to be healthy, cooperative, or uncompromised; fail-safe (loss of the path halts autonomy rather than continuing it); audited. Scope it to *autonomous actuation*, not to observation or user-invoked work.

**Required verification.** New acceptance test: wedge the control plane, then invoke the stop path — assert all autonomous actuation ceases within a stated bound, in-flight tasks checkpoint rather than corrupt, and the event is audited. Second case: sever the stop path itself — assert autonomy halts (fail-safe), rather than continuing unsupervised.

---

## 2. Findings that are false or overstated

### 2.1 NV-02 (Verifier collapse) — **REJECTED as stated · MISCLASSIFIED severity · a narrower real gap survives**

The prior review rates this **P0** on the claim that SR-045 + Arch §13 + SR-042 make planner and verifier *structurally, necessarily* the same weak model during unattended operation. **The authoritative text refutes the premise on three independent grounds.**

**(1) The single-model constraint is MacBook-scoped, not system-wide.** The authoritative Part I transcription reads: *"— **Macbook specific** → Metal acceleration → prefer models that fit comfortably in unified memory → avoid swapping… → use smaller models for background tasks, **not keeping many models loaded at once.**"* The clause the finding rests on sits **inside the "Macbook specific" bullet**. It is a per-node constraint on one node. It does not constrain the fabric.

**(2) The fabric provides a second node precisely when the finding assumes it does not.** Handwritten p4: the desktop is *"always connected (either main or additive space)"*; Baseline 05 §12 designates it *"Primary heavy-compute node for larger models, training, GPU inference."* Overnight — user home, asleep — is when the desktop is **most** available. Two free/local models across two nodes is the nominal overnight configuration, not the exceptional one.

**(3) The source's own definition of verification does not require a second model.** Handwritten p2: *"Task planner + verifier: One step plans, another **checks output against files/rules**."* SR-013's engineering interpretation: *"Planning and verification are separate **control stages**."* **Stages, not model instances.** Part V §11's *"verification remains separate"* is a separation of **responsibility**, which a deterministic check against files, tests, and schemas satisfies completely — and satisfies *better* than a second model would. The finding treats model-instance independence as the requirement; the source never asked for it.

**Verdict: the causal claim is REJECTED and the P0 rating is MISCLASSIFIED.**

**What survives, and it is worth keeping — folded into AR-015 at P1.** The degraded case (desktop offline, Neo-only) is real, and the corpus **does not define what verification does when independence is unavailable**. Specifically: nothing forbids a task self-verified by the same model in the same context from being recorded `SUCCEEDED`. That is a genuine specification gap. It is a **P1 specification gap**, not a P0 structural impossibility, and **PATCH-008 already closes most of it** (`VerificationStrategy` strength order, `INV-VERIF-1` verifier-failure ⇒ `BLOCKED`, prohibition on retry-until-agreement).

**Precise residual — two clauses, that is all:**
- **Unattended eligibility:** a free-time task whose acceptance condition is not machine-checkable is **ineligible for autonomous completion**; it queues for a pass when an independent verifier or the user is available.
- **Telemetry:** record `verified_by: {deterministic | retrieval_grounded | model_critic | self_model | deferred}`. `self_model` may never be silently reported as accepted.

The prior review's *correction* was right. Its *diagnosis* was not — and the difference matters, because the false diagnosis ("structurally impossible") invites a costly architectural response to a problem that needs two clauses in a policy.

### 2.2 NV-05 (SR-031 impersonation) — **MISCLASSIFIED · not a contradiction · P2 feasibility item**

The claim is that SR-031 (*"appear on my behalf"*) contradicts RB-012 (*"never deceptively impersonate"*) as an **unrecorded immutable-layer contradiction**. **The COC records the resolution explicitly, in the same rule:** RB-012 reads *"Never deceptively impersonate the user. **When acting on the user's behalf, use appropriate delegated identity/attribution.**"* DR-025 and Part V §18 repeat it. The handwritten *"show up on my behalf"* most naturally reads as **acting as representative**, and the COC has already chosen that reading and written it down. That is a resolved tension, not an unrecorded contradiction — and Part XIV §3 is therefore not triggered.

The **platform-feasibility** half is legitimate and worth keeping: stock iOS/macOS do not expose programmatic call origination without private entitlements. That is a **spike**, at **P2**, resolved under Part XIV §3 (record the limitation, preserve the requirement, define an R&D path) if it proves infeasible. It is not a blocker and does not need owner adjudication now.

### 2.3 NV-01's supporting assertion — **overstated**

*"Nothing in the corpus restricts VESPER's own autonomy from writing to `core/`, `policy/`, `security/`"* is false; Part VII classifies those changes at L5. The finding survives on **subject scope, reflexivity, and mechanism** (§1.1), not on absence of the rule. Stated correctly, the correction is narrower and cheaper.

### 2.4 NV-10 (unbounded daytime spend) — **correctly rated P2, and partially self-mitigating**

Worth noting for register hygiene: AR-033 observes that **no cost policy artifact exists**, and RB-017 permits paid usage *"only when an explicit cost policy authorizes it."* With no artifact, the default is **deny** — the fail-direction is already safe. A `CostPolicy` with ceilings is still needed, but the exposure is smaller than "unbounded burn" implies.

### 2.5 On the "schema-conformance is not behavior-conformance" thesis — **CONFIRMED as the correct organizing principle**

The second review's central methodological claim is right and I adopt it: a contract test checks shape; the anti-chatbot property is a runtime property. It is the reason NV-03 (sharpened per §1.2) and NV-09 matter more than their P1 ratings suggest. It is also the standard I applied to the patch set in §4.

---

## 3. Remaining P0/P1 blockers

Split by what they actually block — the distinction that governs your decision.

### 3.1 Blocks implementation start (must be specified before increment 1)

| # | ID | Why it must land first |
|---|---|---|
| 1 | **NV-01** (+ **FV-01** as its control pair) | Argument-sensitive tool authorization, the deployment-topology boundary, and the runtime write path are authored in increments 2–5. Not retrofittable at acceptable cost. |
| 2 | **AR-006** | The authorization decision function is the contract every tool call resolves against. Everything downstream encodes its absence. |
| 3 | **AR-007** | Taint must be present in the context assembler and the cache from the first BAG implementation. Retrofitting taint through a summarization/cache pipeline is a rewrite. |
| 4 | **AR-002** | Control-plane ownership determines the persistence and task-state design. Wrong here means re-doing increments 1–2. |
| 5 | **AR-004 + AR-005** | `OperatingPeriod` and the cost-class gate live at the model-gateway choke point — increment 4. Both are single-point fixes if done then, diffuse if done later. |
| 6 | **AR-008** | The trigger registry is the autonomy engine's core data structure, and it is the thing that makes RB-019 explainability and A-018 auditability possible at all. |
| 7 | **AR-010** | Week 0. Until the gates exist and have been **shown to fail**, every other correction is unverifiable. This is the gate on all other gates. |
| 8 | **AR-009** | Enough of ADR-001/002/012 to unblock the above — notably ADR-012, on which NV-01's boundary depends for its referent. |

### 3.2 Blocks the release gate, not the start

| ID | Gate |
|---|---|
| **NV-03** (sharpened) | Autonomy release gate (F5 / Phase 8) — including the **non-schedule trigger** discriminator. |
| **NV-09** | Every A-0xx becomes an executable blocking fixture at its release level. |
| **AR-012** | Rebuild Part XI before any coverage claim is made; retract the Part XV verification PASS. |
| **AR-015 + NV-02 residual** | Verification-independence degradation policy and `verified_by` telemetry. |
| **NV-04** | Rename one axis; state package precedence. Hours of work. |
| Remaining P1s | AR-011, AR-013, AR-014, AR-016–AR-028, NV-06, NV-07 — real, bounded, none architecture-invalidating. |

### 3.3 Catastrophic blockers

**None.** No finding in this pass requires abandoning a structural decision, reopening the COC's architecture, or restarting the design. The two candidates for "catastrophic" were NV-01 and NV-02. NV-01 is real but is a specification omission with a known, cheap correction. NV-02's catastrophic framing was refuted by the authoritative text.

---

## 4. Do the proposed patches close them?

Patches assessed as untrusted proposals against the standard the corpus itself sets: *does the correction produce an artifact that can fail?*

| Patch | Target | Closes? | Residual |
|---|---|---|---|
| **PATCH-003** | AR-006, AR-007 | **Yes — the strongest patch in the set.** `effective_level = min(grant, capability.declared_level(args), context_ceiling)` is the right shape; argument-sensitivity, non-delegable L4/L5, taint through summarization and cache, fail-closed PDP, two-context research pattern are all correct. | Does **not** cover the runtime writing to its own governing surfaces — that path is not a "tool call against an external target" in most designs. **NV-01 must be bound to it explicitly.** |
| **PATCH-004** | AR-004, AR-005 | **Yes**, if `OperatingPeriod` has an explicit fail-direction and a ground-truth override. | Fail-direction must be stated as a **hard default** (ambiguous state ⇒ treat as free-time ⇒ no paid calls), not left to configuration. |
| **PATCH-006** | AR-008, AR-025 | **Yes** for the trigger registry; INV-TRIG-1/2 are correct and reusable. | **Does not close NV-03.** A registry proves actions *have* triggers; it does not prove triggers *fire unprompted*, and it does not exclude an all-schedule trigger set. §1.2's discriminator must be added. |
| **PATCH-008** | AR-014, AR-015, AR-016, AR-024 | **Mostly** — `VerificationStrategy`, `INV-VERIF-1`, and the retry-until-agreement prohibition are correct and close most of NV-02's *legitimate* residual. | Add the two clauses in §2.1: unattended eligibility, and `verified_by` telemetry. |
| **PATCH-010** | AR-010, AR-036 | **Yes for process gates.** Its self-test instruction (*"submit a deliberate SR edit… all three must fail CI"*) is exactly right and should be applied to every gate in the program. | Mechanizes **process** only. Does not wire capability acceptance tests (NV-09), and does not cover the runtime as committer (NV-01). |
| **PATCH-011/012/013** | Source restoration, traceability, SR-026 | **Yes**, and they correctly route through owner approval as an additive COC v1.2. | Requires your decision. PATCH-012 must also **retract the Part XV verification PASS**, not merely rebuild the matrix beneath it. |
| **PATCH-014** | AR-022 | **Yes.** The non-learnable boundary (policy, authorization, cost, Rulebook, SR layer) is correct and is a partial pre-image of NV-01's invariant. | Governs *learned artifacts*, not *code commits*. NV-01 remains distinct — say so explicitly so the two are not conflated during remediation. |
| **PATCH-016** | AR-026, AR-028 | **Yes** for alarm ownership, duration cap, independent ack channels, and the external-action outbox. | Does not address FV-01 (out-of-band stop). Different control, different failure mode. |
| **PATCH-018** | NV-01 | **Directionally right, wrongly worded.** | *"Free-time self-modification prohibited outright"* weakens SR-042. Re-scope to **no self-merge into governing surfaces**; overnight proposal generation stays. Add the Part VII non-narrowability clause and the ADR-012 dependency. |
| **PATCH-019** | NV-02 | **Yes** — and it is the *correct* response to the *incorrect* diagnosis. Adopt it; fold into PATCH-008; drop the P0 rating. | None material. |
| **PATCH-020** | NV-03 | **Partially — and its gate is passable by a cron build.** | Add the non-schedule trigger discriminator (§1.2 part 3). Without it the gate does not test the property it exists for. |
| **PATCH-021** | NV-04 | **Yes.** | Also state package precedence between Baseline 00–07 and the Foundation — the collision's root cause, not just its symptom. |
| **PATCH-022** | NV-05 | **Over-scoped.** | Reduce to a platform-feasibility spike at P2. No owner adjudication and no Part XIV §3 record are needed; RB-012 already resolves the semantics. |
| **PATCH-023/024/025, 017** | NV-06/07/08, P2s | **Adequate** for their scope. | None blocking. |

**Net:** 3 of 25 patches need rewording (018, 020, 022), 2 need extension (010, 006), 1 needs de-scoping (022), 1 should be downgraded and merged (019 into 008). **The patch set's architecture is sound; its precision is uneven.** No patch needs to be discarded.

---

## 5. Exact conditions required before implementation

Ordered. Each condition is met only when an **artifact that can fail** exists — not when a document says it exists.

**Week 0 — the gate on all other gates**

1. Execute **PATCH-010**: repository at the Part XIII layout plus `contracts/`; `main` protected; CODEOWNERS with `docs/COC/` and `contracts/` owned by you alone; the six CI checks.
2. **Self-test every gate before use.** Submit a deliberate SR edit, a schema change with no ADR, and a PR writing outside its declared scope. All three must **fail red**. Until they do, the operating model is documentation.

**Before the first implementation task**

3. **Resolve package precedence** (Baseline 00–07 vs Foundation) and execute **PATCH-021** (rename one `L0–L5` axis). One page. It is the cheapest correction in the program and it prevents a security-vocabulary error.
4. Ratify **PATCH-003** (authorization decision function + taint) and **bind NV-01 to it** with the three corrections in §1.1 — including the Part VII **non-narrowability** clause.
5. Resolve **ADR-012** far enough to define the running-process ↔ repository boundary. NV-01 has no referent without it.
6. Specify **FV-01** (out-of-band stop) as a contract. Implementation may follow; the contract may not.
7. Ratify **PATCH-004** with an explicit **fail-direction default**: ambiguous operating period ⇒ free-time ⇒ no paid calls.
8. Ratify **PATCH-002** (control-plane ownership/lease) and **PATCH-006** (trigger registry).

**Before autonomy ships (F5 / Phase 8) — not before the start**

9. **NV-03 three-part gate**, including the non-schedule trigger discriminator. This is your anti-chatbot proof and nothing else in the program substitutes for it.
10. **NV-09**: every A-0xx an executable blocking fixture, mapped 1:1 to its SR set.
11. **PATCH-008 + PATCH-019** merged: verification strategy, unattended-completion eligibility, `verified_by` telemetry.

**Owner decisions required from you (nobody else can make these)**

12. **PATCH-011/012/013** as an additive **COC v1.2**. PATCH-012 must **retract the Part XV verification PASS** — the audit record currently asserts a traceability pass that the matrix beneath it does not support, and leaving that in place means every future coverage claim inherits a known-false premise.
13. The **L5 self-modification policy** (NV-01) — this is a security boundary and, by Baseline 02 §16 and Foundation, no agent may approve its own security boundary.
14. Whether to accept **single-model-family review**. Baseline 03 §8 requires cross-family verification for security-boundary work. This document is a **third pass but not a third family** — treat AR-001…AR-010, NV-01 and FV-01 as pending cross-family confirmation, since they are precisely the security-boundary findings that rule names.

**Freezing the gap register**

The register may be frozen once §5.1–§5.8 are ratified and §2's corrections are applied to it: **NV-02 downgraded P0→P1 and merged into AR-015; NV-05 downgraded to a P2 spike; FV-01 added at P1; NV-01 re-derived per §1.1; NV-03 re-scoped to a release gate with the sharpened test.** Register the Part XI rebuild as a **precondition of any coverage claim**, since no completeness assertion can be made against a matrix whose verification column is 51 identical placeholders.

---

## 6. FINAL VERDICT

**Have you found the blockers that must be corrected before implementation? Yes.**

Three independent passes have now converged. The third pass **removed** one P0 (NV-02, refuted on the authoritative text), **downgraded** one P1 (NV-05), **re-derived** one P0 on corrected reasoning (NV-01), **sharpened** one P1 into a test that actually discriminates (NV-03), and **added exactly one** small finding (FV-01). Convergence at that rate, with the count falling, is the signal that the search is complete. Further adversarial passes will produce P2s and taxonomy — not blockers. **Stop reviewing and start correcting.**

The architecture is **fundamentally sound**, and I want to be unambiguous about that, because three consecutive adversarial reviews create an impression of a system in trouble, and that impression is wrong. Every remaining defect is a **missing decision function, a missing schema, or a missing enforcement artifact beneath a boundary that is already correctly drawn**. That is the good failure mode. The corpus's real weakness is that it is a **taxonomy that names every subsystem without defining the boundary between any two precisely enough that two engineers build compatible halves** — and the corrective work for that is specification, not redesign.

One structural observation worth carrying into remediation: the single most consequential omission in the entire corpus — NV-01 — exists because the documents were written from the standpoint of a **team building a system**, and never from the standpoint of the **system building itself**, even though the handwritten source explicitly asks for exactly that (SR-027, SR-042, SR-048). When you correct it, correct it at that level: *VESPER is a subject of its own rules.* One sentence in the right place closes more of this than any patch in the set.

The conditions in §5 are bounded, ordered, and mostly cheap. Item 3 costs an hour. Items 1–2 cost days. The expensive items (4, 5, 8) are expensive precisely because they must be done **before** code exists — which is the position you are in right now, and which is the best possible position to be in.

**Do not begin implementation until §5.1–§5.8 are ratified as artifacts that can fail.** Then build.

---

# BUILD_AFTER_CORRECTIONS
