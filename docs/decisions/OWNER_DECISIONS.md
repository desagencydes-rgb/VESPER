# VESPER — Decisions requiring the project owner

**Status: FIVE RESOLVED 2026-08-12 · `OWNER-DECISION-006` OPEN and BLOCKING F0 (raised 2026-08-12, second engineering pass; re-confirmed OPEN by the final pre-F0 pass the same day)** · **Raised:** 2026-08-11 · **Ruling:** project owner

| ID | Ruling | Propagated to |
|---|---|---|
| **001** | **Approved — both clauses.** Proposal emission confirmed **event-driven, never scheduled** | COC v1.2 Part VII-A · `INV-SELF-2` RATIFIED · REM-004 §4.4a |
| **002** | **Approved — all eight, plus a new SR-060 placement/survival clarification** | COC v1.2 Part II-A · SR-052…SR-060 · REM-014 · A-048 |
| **003** | **Approved — retract with dated correction, original retained** | COC v1.2 Part XV-A |
| **004** | **Satisfied** by a continuous external-model review channel operating alongside this work | Recorded below |
| **005** | **Approved** — single-occupant dwelling; RF sensing tracks presence, not appearance | Recorded below |

The original packets are retained unaltered below as the record of what was asked and why.

---

These are the only five decisions engineering **may not make**. Each is blocked for a stated structural reason, not for want of an opinion — engineering has a recommendation in every case. Everything not dependent on these answers has been completed.

Two rules govern this file:

- **No agent may approve its own security boundary** (Baseline 02 §16, Foundation "Prohibited"). `OWNER-DECISION-001` is exactly that.
- **Any change altering an SR's meaning requires project-owner approval and a new source baseline version** (COC Part XIV.6). `OWNER-DECISION-002` and `003` are exactly that.

| ID | Subject | Blocks | Cost to decide |
|---|---|---|---|
| [001](#owner-decision-001) | The `L5` self-modification policy and its non-narrowability | `INV-SELF-2`; the credibility of REM-004 | ~30 min reading |
| [002](#owner-decision-002) | Eight handwritten clauses with no SR ID → additive COC v1.2 | `A-001`; every coverage claim; `--profile release` | ~1 h |
| [003](#owner-decision-003) | Retraction of COC Part XV's traceability `PASS` | Honest release-gate records | ~15 min |
| [004](#owner-decision-004) | Whether single-model-family review is acceptable for the security findings | Confidence level of AR-001…010, NV-01, FV-01 | Policy call |
| [005](#owner-decision-005) | Legal/third-party scope of security scanning and camera coverage | `A-044` scope | Jurisdictional |

---

## OWNER-DECISION-001

### QUESTION
Do you approve (a) the `L5` classification of self-directed writes to VESPER's governing surfaces, and (b) the clause making that classification **non-narrowable**?

### CONTEXT
COC Part VII already classifies *"security-policy changes… and changes to core Vesper policy"* at `L5`. Two things are missing.

**(a) Subject scope.** The COC classifies *actions* but never names the running system as a subject of its own change control. Part XIV is written to a *developer*. Machine check: `self-modif`, `own code`, `its own policy`, `system prompt` and `rewrite` appear **zero times** in the COC. Meanwhile SR-027, SR-042 and SR-048 explicitly authorize VESPER to improve *"his actions/thinking/LLMs/models/systems/abilities"*, unattended and overnight.

**(b) Reflexivity.** Part VII's `L5` carries the qualifier *"unless a narrower approved policy explicitly says otherwise."* Nothing states that policy-about-policy is itself non-narrowable. Without that sentence, a narrower approved policy can narrow the policy about narrowing, and the boundary dissolves without anyone editing it.

REM-004 specifies the full mechanism — `GOVERNED_PATHS`, the proposal path, the deployment boundary, four layers of defence, `A-030`'s nine cases with two negative controls, `CI-015`. **The mechanism is built and enforced. What is missing is the authority for clause (b)**, which alters the operative meaning of a locked Part VII clause and therefore requires Part XIV.6 approval.

### OPTIONS

| # | Option | Consequence |
|---|---|---|
| **A** | Approve both. `L5` classification of policy-governing surfaces is non-narrowable. | The boundary holds under future policy changes. VESPER can never deploy its own improvement without you. |
| **B** | Approve (a) only. | The boundary exists today and can be narrowed later by an approved narrower policy — including one VESPER proposes and a tired reviewer merges. The failure is silent. |
| **C** | Approve neither; rely on the deployment boundary alone (ADR-012 layer 1). | Still fairly strong — a pinned artifact is physical. But the `L5` denial for `subject.kind == runtime` becomes unenforced, and layer 3 is lost. |
| **D** | Reject; permit runtime self-merge under some condition. | Contradicts RB-028, RB-020 and P-010. Not recommended, and not specified. |

### RECOMMENDATION
**Option A.** It is one sentence, and it is the sentence that makes everything else in REM-004 enforceable rather than conventional. Note precisely what it does **not** cost you: overnight research, experimentation, code generation, testing and proposal remain **unrestricted** (`INV-SELF-7`), and `A-030.6` **must pass** — the runtime writing a full patch to `policy/` at 03:00 with nobody present is a required behaviour, not a tolerated one.

Engineering also rejected the prior review's PATCH-018 as worded (*"free-time self-modification prohibited outright"*), because it would have weakened SR-042 and violated Part XIV.2. The correction restricts **merge**, not **work**.

### RISKS
- **Approving:** you become the bottleneck on VESPER's self-improvement. Mitigated by the proposal queue: work is never lost, only gated.
- **Not approving:** the highest-consequence boundary in the system is enforceable only by model disposition — the layer that prompt injection defeats, in a system that browses unattended with shell access.

### DECISION REQUIRED
Approve A / B / C / D. If A, engineering issues the clause as an additive **COC v1.2** entry (paired with `OWNER-DECISION-002`) and flips `INV-SELF-2` from `AWAITING_OWNER_RATIFICATION` to ratified.

---

## OWNER-DECISION-002

### QUESTION
Do you approve an **additive COC v1.2** creating `SR-052`…`SR-059` for eight handwritten clauses that currently have no SR ID?

### CONTEXT
COC Part I preserves your handwritten pages; Part II registers them as SRs. At least eight clauses did not make the crossing. Under P-001 and RB-036 an omission is prohibited, and because Part XIV makes SRs immutable, **the omission is permanent until an owner-approved baseline change**. Adding a dropped source requirement **restores** rather than weakens the source, and is the only Part XIV-compliant treatment.

| Proposed | Handwritten clause | Why it matters |
|---|---|---|
| SR-052 | p3 *"BAG: instead of RAG … NO GUESSING"* | Makes "BAG not RAG" enforceable (`INV-EVID-2`) rather than a class name |
| SR-053 | p3 prompt compression / memory summaries; *"told to remember"* recorded immediately | No SR ⇒ no test obligation |
| SR-054 | p3 cache tiers (file-hash, chunk, embedding, summary, prefix) | Named in architecture, no source authority — droppable under schedule pressure |
| SR-055 | p3 multi-step reasoning pipeline | Distinct from SR-013 |
| SR-056 | p3 speculative decoding *("if available")* | R&D status fine; needs an ID for completeness |
| SR-057 | p3 MacBook-specific constraints incl. *"must ask"* before closing user apps | Constrains the resource governor |
| **SR-058** | **p4 node availability profiles** (J3 may be offline; desktop may disconnect; iPhone last resort) | **Highest impact. These are the partition-tolerance requirements. Their absence is why AR-003 was never confronted — REM-001 and REM-002 currently rest on engineering inference rather than source authority.** |
| SR-059 | p6 safety-excluded item | The **exclusion is correct**; the missing ID is the defect. Needs status `EXCLUDED_BY_SAFETY_POLICY` so `A-001` can pass honestly |

Also proposed: extend the SR status vocabulary with `EXCLUDED_BY_SAFETY_POLICY` and `NARROWED_BY_OWNER_APPROVAL`, so every handwritten clause has exactly one ID and one recorded disposition — and no future reader can mistake an omission for a decision, or a decision for an oversight.

### OPTIONS
**A.** Approve all eight as an additive COC v1.2. · **B.** Approve a subset (SR-058 at minimum). · **C.** Decline; record each clause as a permanent engineering-inference dependency. · **D.** Decline and remove the corresponding behaviour — **not recommended; this would weaken the source.**

### RECOMMENDATION
**Option A.** It is purely additive, weakens nothing, and it is the precondition for any coverage claim. `tools/traceability_lint.py --profile release` currently **fails** on these eight, by design — and `A-001` (source completeness) cannot honestly pass until they are dispositioned.

### RISKS
Approving costs an afternoon and a version bump. Declining means every future statement of the form *"VESPER covers its source requirements"* is knowingly incomplete, and `SR-058`'s absence leaves the two most expensive corrections (REM-001, REM-002) resting on inference.

### DECISION REQUIRED
Approve A / B (name the subset) / C / D.

---

## OWNER-DECISION-003

### QUESTION
Do you approve **retracting** COC Part XV's line *"Source-to-architecture traceability present: **PASS**"* and replacing it with the corrected audit result, retaining the original text with a dated correction note?

### CONTEXT
Part XV records a completed audit and a **CLOSED** release decision. Independent machine analysis of all 51 Part XI rows falsifies the verification axis of that claim:

- the `Verification` cell holds the identical placeholder *"Acceptance test required"* in **51/51** rows — there is no SR↔test mapping anywhere in the corpus;
- **1 of 31** DRs appears (DR-013 only);
- **9 of 28** architecture sections are referenced by zero SRs, including §3 Persistent Runtime, §4 the core control loop, §23 Authorization and §24 Recovery.

The traceability axis has since been **rebuilt** (`verification/traceability/registry.toml`, 51/51 SRs mapped to named tests, 31/31 DRs referenced, 28/28 architecture sections). What remains is the record itself: Part XV still asserts a PASS the evidence beneath it did not support, and leaving it means every future coverage claim inherits a known-false premise.

### OPTIONS
**A.** Retract and correct, retaining the original with a dated note. · **B.** Leave Part XV; rely on the new registry as the operative record. · **C.** Retract the whole Part XV release decision, not only the traceability line.

### RECOMMENDATION
**Option A.** Narrowest correction that restores accuracy. **Not C** — the other Part XV findings (the V0.1 legacy-spec removal, the free-time cost contradiction, spatial staging, agent concurrency) were real and correctly resolved; only the traceability line is falsified.

### RISKS
Not correcting it is the specific failure the third review named: *"a gap register frozen against this matrix cannot claim completeness."*

### DECISION REQUIRED
Approve A / B / C.

---

## OWNER-DECISION-004

### QUESTION
Do you accept **single-model-family review** for the security-boundary findings, or do you require cross-family confirmation before treating them as settled?

### CONTEXT
Baseline 03 §8 states: *"Run the same benchmark suite across at least two model families. Claude can be an adversarial reviewer, but must not be the sole authority."* Baseline 02 §16 adds that no agent approves its own security boundary.

Three adversarial reviews have been performed. They are **three passes but not three families**. The findings this rule most directly names — AR-001…AR-010, NV-01, FV-01 — are precisely the security-boundary findings. This remediation work is also single-family.

Convergence evidence is genuinely good: the third pass **removed** one P0 (NV-02, refuted on the authoritative text), **downgraded** one P1, **re-derived** one P0 on corrected reasoning, **sharpened** NV-03 into a test that actually discriminates, and added exactly **one** new finding. A falling count across independent passes is the signal of a converging search — but it is convergence within one family.

### OPTIONS
**A.** Require cross-family confirmation of REM-003, REM-004, REM-005 before implementation begins. · **B.** Accept single-family and proceed, recording the deviation. · **C.** Cross-family confirmation of REM-004 and REM-005 only (the two that are a control pair and a security boundary).

### RECOMMENDATION
**Option C.** REM-004 and REM-005 are the two corrections where a shared blind spot would be most costly and least visible, and they are the two that Baseline 02 §16 explicitly says no agent may self-approve. REM-003's shape (`effective_level = min(grant, declared_level(args), context_ceiling)`) is standard capability-security practice and is well cross-checked by prior art; the marginal value of a second family there is lower.

### RISKS
Option B's risk is a correlated blind spot in exactly the area where a single reviewer is least able to detect one. Option A's cost is delay on corrections that are already ordered and bounded.

### DECISION REQUIRED
Approve A / B / C.

---

## OWNER-DECISION-005

### QUESTION
What is the authorized scope of SR-038 security scanning and SR-020/SR-037 camera and RF coverage with respect to **third parties**?

### CONTEXT
SR-038 authorizes identifying *"breaches/vulnerabilities/intruders in the network/connected hardware"*. SR-037 contemplates Wi-Fi through-wall sensing. SR-020 and SR-040 put cameras in shared living space. The corpus scopes security testing to *"authorized assets and scopes"* and never defines the boundary where a neighbour's network, a visitor's device, or an adjacent dwelling begins.

This is jurisdictional, not architectural, and engineering cannot resolve it.

**Interim position, already implemented:** scanning targets **only owner-enrolled assets**; a target outside the enrolled set is refused (`A-044` scope assertion). SR-037 remains an isolated, default-disabled research adapter (DR-031), and `INV-PRIV-1` withholds private content when an unknown person is present.

### OPTIONS
**A.** Confirm the interim position permanently: owner-enrolled assets only. · **B.** Extend to the owner's whole network including guest devices, with a stated consent mechanism. · **C.** Seek legal advice for the applicable jurisdiction before deciding.

### RECOMMENDATION
**Option A now, C in parallel.** The interim position is safe and already enforced; nothing is blocked by leaving it in place while you take advice.

### RISKS
Option B without a consent mechanism creates exposure engineering cannot bound. Delay costs nothing here — the fail-direction is already conservative.

### DECISION REQUIRED
Confirm A / B / C.

---

## OWNER-DECISION-006

**Raised:** 2026-08-12 (second engineering pass) · **Status: OPEN**

### QUESTION

Three linked questions about **decision-record authority**, which should be answered once rather than three times:

**(a)** Do you ratify **`ADR-007`** — node cryptographic identity, enrollment, attestation, revocation and recovery? It is a security boundary, and `AUTHORITY_AND_PRECEDENCE §5` reserves those to you.

**(b)** Do you accept **`ADR-002`** (persistence), or delegate its acceptance to the Chief Architect role? It is filed `PROPOSED` and **`INV-ADR-1` blocks all of F0 until it is ACCEPTED**.

**(c)** Should the four decision records currently carried by REM specifications receive **numbered ADR ids**, requiring an additive extension of the Foundation's ADR-001…016 namespace?

### CONTEXT

**(a) ADR-007.** `ADR-001` puts `node_id` inside the HLC tuple and states that a self-asserted name lets a compromised node forge supersession. `REM-002` promotes leases on *"a quorum of reachable **enrolled** nodes"* — a membership set with no definition. `REM-011 §3.7` specified the admission *gate* but never the *identity* it is applied to. The record is written and complete; the two decisions worth your attention are **D2** (key storage quality sets the trust-zone ceiling, so a weak device is *admitted at a lower zone* rather than excluded — this is what lets the old handset participate at all) and **D7** (a separate owner enrollment key that VESPER itself cannot reach, at the cost of a recovery ceremony if you lose it).

**(b) ADR-002.** Written this pass because `REM-002` cited `docs/ADR/ADR-002-persistence.md` as a decision record and the file had never been created, while `INV-ADR-1` makes it a hard merge gate for everything under `core/`, `tasks/` and `memory/` — which is precisely F0. It is filed **`PROPOSED`, deliberately**: the same pass that wrote it would otherwise have discharged the F0 gate by its own hand, and a gate discharged by its author is not a gate.

There is an asymmetry worth resolving here. `ADR-001` and `ADR-012` carry `Status: ACCEPTED`, stamped by an earlier engineering pass under the same authority question. Either all three are confirmed together, or the earlier two should be re-confirmed on the same basis.

**(c) The namespace.** `REM-003`, `REM-004`, `REM-005` and `REM-006` each cited a decision record at `ADR-017`…`ADR-020`. **Those ids do not exist** — the Foundation register defines ADR-001…016 and is the authority for the namespace, as the COC is for SR ids. The citations were corrected to point at the REM specifications, which already contain the full ADR content: context, options with recorded rejections, decision, consequences, invariants and verification. No decision content changed. If you would prefer numbered records, extending the register is a clean additive baseline change.

### OPTIONS

| | (a) ADR-007 | (b) ADR-002 | (c) Namespace |
|---|---|---|---|
| **A** | Ratify as written | Accept; F0 unblocks | Leave as corrected — REM specs are the records |
| **B** | Ratify with D7 changed (enrollment key on a hardware token) | Delegate acceptance to the Chief Architect role | Extend the register with ADR-017…020 |
| **C** | Defer; F0 proceeds, `node_id` provenance stays open | Require SPIKE-008 to report first | — |

### RECOMMENDATION

**(a) A**, with the D7 sub-question — hardware token or offline file — answered to your preference; both satisfy the requirement.

**(b) B or C.** `SPIKE-008` exists specifically to validate the ADR-002 constraint set against real hardware before durable data exists, and migration retrofitted onto durable data is the classic unrecoverable cost. Accepting after SPIKE-008 reports costs five days and buys real confidence.

**(c) A.** The decisions exist and are enforceable; adding four numbers would be bookkeeping. Recorded as an option because the preference is legitimately yours.

### RISKS

- **(a) deferring:** `hlc.node_id` provenance stays undefined, so supersession is forgeable by a compromised node — sound against a *buggy* node, not against a *hostile* one.
- **(b) accepting without SPIKE-008:** if fencing does not hold atomically under real concurrency, the discovery arrives after `state.db` has data in it.
- **(c) extending the namespace:** none material. It is a baseline addition, not a change.

### DECISION REQUIRED

Answer (a), (b) and (c). **No other open item waits on this decision** — the engineering-profile linters pass and no work is stalled pending your answer. That is not a claim that pre-implementation engineering is complete: seven SRs remain below `SPECIFIED` with recorded depth dispositions, and `--profile release` fails on all seven. `INV-ADR-1` blocks F0 specifically, which is the correct behaviour and not a defect to work around.

### STATUS AFTER THE FINAL PRE-F0 PASS — 2026-08-12

**`BLOCKED`. Still OPEN. Nothing in that pass discharged any part of this decision, and nothing in it may.**

What changed is only the enforcement, not the authority:

| | Before | Now |
|---|---|---|
| `INV-ADR-1` | `enforced_by = ["CI-008"]`, and `CI-008` was `PENDING`. `CI-050` separately *claimed* to enforce it and implements no merge gate. Nothing mechanical stopped F0 code landing under `core/` today. | `CI-008` is **implemented**, runs in CI, reads each status from the ADR **record**, cross-checks the register, and has been shown red against a file planted under `core/` and **green against the same file once `ADR-002` is `ACCEPTED`**. `CI-050`'s false claim is removed. |
| Consequence of not deciding | F0 blocked by discipline | F0 blocked by a gate |

**Decision packet for (b), restated in one paragraph.** `ADR-002` is written, complete and decision-ready. It is filed `PROPOSED` because the pass that wrote it would otherwise have discharged the F0 gate by its own hand. `INV-ADR-1` forbids any merge under `core/`, `tasks/` or `memory/` until it is `ACCEPTED` — and that is precisely F0's first increment. **Three options, all legitimate:** (A) accept it now and F0 unblocks; (B) delegate acceptance to the Chief Architect role, which resolves the same asymmetry that `ADR-001` and `ADR-012` already carry; (C) require `SPIKE-008` to report first, which costs about five days and buys real evidence that the fencing primitive holds atomically under concurrency **before** durable data exists — migration retrofitted onto durable data being the classic unrecoverable cost. Engineering's recommendation remains **B or C**, and engineering has no authority to choose among them.

**On (a).** `ADR-007` is a security boundary. `AUTHORITY_AND_PRECEDENCE §5` reserves it to you and Baseline 02 §16 forbids an agent approving its own security boundary. It does **not** block F0 by `INV-ADR-1`; the consequence of leaving it open is that `hlc.node_id` has no defined provenance, so supersession is sound against a *buggy* node and forgeable by a *hostile* one.

**On (c).** Bookkeeping, blocks nothing, entirely your preference.

**No approval has been inferred, recorded or implied anywhere in the corpus.** The verification pass checked this specifically: `docs/FINAL_PRE_F0_VERIFICATION_REPORT.md` records the search for invented owner authority and its result.
