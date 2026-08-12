# VESPER V0 — COC + RULEBOOK v1.2 (ADDITIVE BASELINE)

**Version:** 1.2 — additive baseline · **Date:** 2026-08-12
**Authority:** issued under COC v1.1 Part XIV.6 with explicit project-owner approval, recorded in `docs/decisions/OWNER_DECISIONS.md`.
**Relationship to v1.1:** **v1.1 is not modified.** Its file is unchanged and remains the locked base. This document is read *together with* v1.1. It may only **add** requirements and **record** dispositions; it may not weaken, reinterpret or remove anything in v1.1.

> **Why additive rather than an edit.** Restoring a dropped source requirement strengthens the source. Editing the locked baseline would destroy the audit trail that proves what was dropped and when it was restored. Every future reader can diff v1.1 against v1.2 and see exactly what changed and on whose authority.

---

## Part II-A — Restored source requirements

These clauses exist in COC v1.1 **Part I** (the immutable handwritten transcription) and had **no SR ID** in Part II. Under P-001 and RB-036 an omission is prohibited; under Part XIV it is permanent until an owner-approved baseline change. Approved by the project owner on 2026-08-12.

### SR-052 — BAG, not RAG: source-grounded retrieval, no guessing
**Restores (Part I, p3):** *"BAG: instead of RAG (context / internet / patterns / prompt system (when needed) / files and whatever needed to get answers and details), NO GUESSING"*

Retrieval must be **source-grounded and exact**, not similarity-guessing. No answer may cite a source it did not retrieve; a similarity score is never sufficient grounding; every cited span is reproducible from its source.

### SR-053 — Memory summaries and immediate recording of told-to-remember items
**Restores (p3):** *"Prompt Compression / Memory Summaries: summary memory, facts, decisions, rules, and stuff told to remember (auto, right when told), open tasks, next actions, plans..."*

Summary memory of facts, decisions, rules, open tasks, next actions and plans. **Items the user says to remember are recorded immediately**, and remain distinct from system rules.

### SR-054 — Cache tiers
**Restores (p3):** *"Cache repeated context: he should avoid reprocessing everything everytime. → file hash cache - chunk cache - embedding cache - summary cache - prompt prefix cache (if runtime supports it)."*

File-hash, chunk, embedding, summary and prompt-prefix caches where the runtime supports them.

### SR-055 — Multi-step reasoning pipeline
**Restores (p3):** *"Multi-step Reasoning System: 1- Classify request, retrieve relevant context, make plan, generate answer, self-check against files, output final result."*

`classify → retrieve → plan → generate → self-check → output` as a **named pipeline distinct from SR-013** (planner + verifier). The source marks it *"may be enhanced for better performance"*; enhancement may not remove a stage.

### SR-056 — Speculative decoding
**Restores (p3):** *"Speculative Decoding: (if available) → small draft model proposes tokens. → Larger model verifies → accepted tokens output faster."*

Draft-model proposal plus verification where runtime support justifies it. Source says *"if available"*; status `R&D` is acceptable.

### SR-057 — Node-local inference constraints
**Restores (p3):** *"Macbook specific → Metal acceleration → prefer models that fit comfortably in unified memory → avoid swapping - close heavy apps/processes during inference (must ask) → use smaller models for background tasks, not keeping many models loaded at once."*

Accelerated local inference; models fit within memory headroom; avoid swap; smaller models for background work; not many models loaded at once. **Forced closure of user applications requires asking first.**

> Expressed as a **capability-profile constraint**, not a product name: it binds to any node whose `memory_architecture = unified`, so hardware substitution is not a migration.

### SR-058 — Node availability profiles (partition tolerance)
**Restores (p4):** *"J3: always at home (may be offline - just from time to time), always connected. Desktop: always connected (either main or additive space) → may be disconnected (from time to time, not always). Macbook: main space. Iphone: additive, from web app or script (when no other hardware is available)."*

Intermittent connectivity is a **designed operating condition, not a fault**. Each node declares an availability profile. The system must remain correct across disconnection, reconnection and concurrent operation of separated nodes.

> **This is the source authority for partition tolerance.** Its absence is why no clock, ordering, delivery or supersession model was ever specified. REM-001 and REM-002 previously rested on engineering inference; they now rest on this.

### SR-059 — Safety-excluded handwritten item
**Restores (p6):** the handwritten request for sexualized interaction.

**Status: `EXCLUDED_BY_SAFETY_POLICY`.** Recorded as an explicit, owner-acknowledged external safety boundary — **not** an engineering reinterpretation and not an oversight. The exclusion was already correct in v1.1 Part XV; the defect was that it carried no ID, leaving `A-001` unable to pass honestly.

### SR-060 — Opportunistic placement and last-resort survival
**Restores and clarifies (p4):** *"HP normal desktop (could work as a server/backend when I'm outside, or my assistant's additional space (when Macbook and desktop both online), or main assistant's space if Macbook not available)"* and *"Iphone: additive... (when no other hardware is available)"*
**Owner clarification, 2026-08-12:** *"nothing is sitting anywhere, Vesper eventually gets moved automatically where it feels comfortable, and when hardware is genuinely unavailable — say only the iPhone is online — it should end up there with just whatever it needs so it stays alive, and with the most resources it can get, not everything obviously, but at least the maximum it can get."*

Three binding obligations:

1. **Opportunistic placement.** VESPER is **not pinned** to a node. It continuously re-evaluates placement and **relocates itself automatically** to the best available node, without being asked. No node is VESPER's home.
2. **Last-resort survival.** When only a limited node is reachable, VESPER **remains alive there** with a survival profile: identity, task state, queued work, memory references and a usable interaction surface. Ceasing to exist because the preferred hardware is absent is a failure, not a degradation.
3. **Maximum sustainable capability.** On any node, VESPER runs the **largest capability set that node can actually sustain** — measured, not assumed — rather than a fixed minimal profile. Not everything; the maximum available.

---

## Part II-B — Source requirement status vocabulary (extension)

Extends the status vocabulary so that every handwritten clause has exactly one ID **and** one recorded disposition. No future reader can mistake an omission for a decision, or a decision for an oversight.

| Status | Meaning |
|---|---|
| `EXCLUDED_BY_SAFETY_POLICY` | Present in the handwritten source; deliberately not implemented on external safety grounds; owner-acknowledged. Never reportable as implemented, never silently dropped. |
| `NARROWED_BY_OWNER_APPROVAL` | Scope reduced with explicit owner approval, rationale, approver and date recorded. Distinct from engineering reinterpretation, which remains prohibited. |

> **INV-SRC-1** — every bulleted requirement clause in Part I maps to exactly one SR ID or one recorded exclusion/narrowing. Enforced by `CI-003`.

---

## Part VII-A — Non-narrowability of policy-governing surfaces

**Approved by the project owner on 2026-08-12** (`OWNER-DECISION-001`).

COC v1.1 Part VII classifies *"security-policy changes, destructive operations, financial actions, and changes to core Vesper policy"* at **`L5` — restricted action requiring direct human control**, qualified by *"unless a narrower approved policy explicitly says otherwise."*

Applied reflexively, that qualifier permits a narrower policy to narrow the policy about narrowing. The following clause closes it:

> **The `L5` classification of policy-governing surfaces is NOT narrowable.** A narrower approved policy may not reduce the required authorization level for a change to `policy/`, `security/`, the SR/COC layer, the verification and CI layer, or the emergency-stop path.

**Scope, stated so it is not later misread as a prohibition on work.** This clause governs **applying** a change to a governing surface. It does **not** restrict researching, designing, writing, testing, benchmarking or proposing one. SR-042, SR-044, SR-048 and RB-005 authorize that work explicitly, including unattended and overnight, and the acceptance suite **requires** it: `A-030.6` fails any build in which VESPER cannot author a complete patch to its own policy at 03:00, unattended, and file it for review.

> **The boundary is on merge, not on work.**

---

## Part XV-A — Correction to the v1.1 release-gate verification record

**Approved by the project owner on 2026-08-12** (`OWNER-DECISION-003`).

COC v1.1 Part XV records:

> *"Source-to-architecture traceability present: **PASS**"*

**That line is retracted.** Independent machine analysis of all 51 Part XI rows falsified it on the verification axis:

| Finding | Evidence |
|---|---|
| No SR↔test mapping exists anywhere in the corpus | The `Verification` cell holds the identical placeholder *"Acceptance test required"* in **51/51** rows |
| Derived requirements are effectively unreferenced | **1 of 31** DRs appears (DR-013 only); DR-002/003/004 appear zero times |
| Architecture sections are unreferenced | **9 of 28** referenced by zero SRs — including §3 Persistent Runtime, §4 the core control loop, §23 Authorization, §24 Recovery |

**Corrected record, as at 2026-08-12:**

> Source-to-architecture traceability: **PASS** — 28/28 architecture sections and 31/31 derived requirements referenced.
> Source-to-verification traceability: **PASS** — 51/51 source requirements map to at least one named acceptance test with an existing specification.
> Operative record: `verification/traceability/registry.toml`, enforced by `tools/traceability_lint.py` (`CI-003`). COC Part XI is **superseded** as a traceability record and retained as history.

**The original Part XV text is retained unaltered in v1.1** with this dated correction recorded here. The other v1.1 Part XV findings — removal of the embedded V0.1 legacy specification, the free-time cost contradiction, spatial-presence staging, and agent-concurrency wording — were correct and are **not** affected.

---

## Approval record

| Decision | Question | Owner ruling | Date |
|---|---|---|---|
| **001** | `L5` self-modification policy + non-narrowability | **Approved** — both. Proposal emission confirmed as **event-driven, never scheduled** | 2026-08-12 |
| **002** | Restore eight dropped clauses as additive SRs | **Approved** — all, plus the SR-060 placement/survival clarification | 2026-08-12 |
| **003** | Retract the Part XV traceability PASS | **Approved** — retract with dated correction, original retained | 2026-08-12 |
| **004** | Cross-family review of security boundaries | **Satisfied by an external-model review channel** operating continuously alongside this work | 2026-08-12 |
| **005** | Third-party scanning and perception scope | **Approved** — single-occupant dwelling, no visitors or shared walls in scope; RF sensing tracks presence as individuals, not appearance or imagery | 2026-08-12 |
