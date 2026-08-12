# REM-016 — Record loss: honest forgetting, and where forgetting stops

| | |
|---|---|
| **Implements** | Owner requirement, 2026-08-12 · SR-041, SR-046, SR-049 · DR-021, DR-028 · RB-001, RB-002, RB-022, RB-033 |
| **Extends** | REM-009 (presence) · REM-012 §6 (observability) · REM-015 (backlog) |
| **Owner** | Presence & Interaction Engineer · Security Engineer (the escalation boundary) |
| **Blocked by** | REM-009, REM-012, REM-015 |

---

## 1. Problem

Two problems, and the second is the reason this REM exists rather than being a paragraph in REM-015.

**(a) Loss reporting defaults to being unusable.** RB-022 and DR-021 require capability loss to be *reported*. Nothing says **how**. The default implementation is a log line and an error toast — which in a voice-and-spatial system means it is never seen (SR-046 makes text a fallback channel, not the primary one), and which reads exactly like every other agent: `ERROR: record improvement_idea/idea_a1b2 not found (ENOENT)`. That output is technically honest and practically useless, and it is a direct violation of the system's own personality requirements (SR-041, DR-028).

**Owner requirement, 2026-08-12:**

> *"what if we could treat broken or deleted records just as forgotten ideas in a human brain, then moves forward, just says something like 'hmm I had a plan to improve myself but I forgot, but anyways' — a nice way of flagging it to me, without making it too technical, nor making it like any normal agent, and it actually stays smooth, clean and funny just like how we architectured it, and following our plans for the interactive stuff (voice and output screens + hologram + projector instead of text and keyboard)."*

**(b) The hazard inside that requirement.** *"Moves forward"* is correct for a lost note and catastrophic for a missing security record. A deleted entry in `autonomy/triggers/`, a tampered `governed_surfaces.toml`, a truncated audit log and a corrupted interlock configuration are **precisely what compromise looks like** — and a system whose trained response to all of them is a warm *"hmm, I forgot"* has learned to shrug at its own integrity failures. That failure is silent, it is cumulative, and it would look charming for a year.

> **The resolution is not to dilute the affect. It is to bound it.** A person shrugs about misplaced keys. The same person, finding their front door open and their filing cabinet emptied, does not shrug. Treating those identically is not humanity — it is dissociation. **RB-033 already says this**: humour and playfulness *"must never override truth, safety, authorization, or the user's explicit boundaries."*

## 2. Two layers, always both

| Layer | Property | Negotiable? |
|---|---|---|
| **Detection & record** | Every loss is detected, classified and audited. The event exists whether or not anyone hears about it. | **No.** Never suppressed, never softened, never rate-limited. |
| **Surfacing** | *How* the owner hears about it: affect, modality, timing, aggregation. | Yes — this is where the personality lives. |

The affect is a **presentation property of the second layer only**. It never edits the first. A charming line about a lost note and a full `record.loss` event with provenance are emitted by the same code path, one to the owner and one to the audit log.

## 3. Loss classes

Classification is deterministic (`DF-LOSS-CLASS`) and is a property of **which store the record lived in**, never of how the loss feels.

| Class | Records | Response |
|---|---|---|
| **A — forgettable** | Improvement ideas, backlog entries, learned artifacts, caches, derived indexes, non-critical working state | **Human forgetting.** Casual, brief, aggregated, ambient. VESPER moves on. |
| **B — noticed absence** | Task checkpoints, queued proposals, scheduled alarms, memory records, world-model history | **"I dropped something and it mattered."** Explicitly flagged, reconstruction attempted, surfaced at the next natural boundary. Not casual, not alarming. |
| **C — integrity event** | Governed surfaces (REM-004 §4.2), authored trigger registry entries, interlock configuration, audit log, traceability registry, event log segments | **Incident.** `DETECT → CLASSIFY → CONTAIN → PRESERVE → RECOVER → VERIFY → REPORT`. **No affect. No humour. Immediate.** |

> **`INV-LOSS-2`: personality is absent from class C.** This is the invariant that keeps the feature from becoming the vulnerability. It is not a style guideline — a class C loss that surfaces with an affect template is a test failure (`A-050.6`).

## 4. The mechanism that makes honest forgetting possible

**A human says *"I had a plan but I forgot"* because a trace remains.** With no trace at all, there is nothing to report — and claiming to have forgotten something would be a fabrication, violating RB-001 and RB-002.

So forgetting requires **tombstones**:

```
On creation, every durable record writes a TOMBSTONE-ELIGIBLE index entry
in a SEPARATE store from its body:
    { record_id, kind, created_at_hlc, title_hint, loss_class }

Loss detection = tombstone present ∧ body absent-or-unreadable
```

This yields the three honest answers, and only these three:

| Evidence | What VESPER may say |
|---|---|
| Tombstone present, body gone, **no deletion audit** | *"I had something here and it's gone"* — genuine forgetting |
| Tombstone present, body gone, **deletion audit exists** | *"Something removed this"* — **not** forgetting; VESPER knows the cause |
| No tombstone | **Nothing.** There is no evidence a record existed. |

> **`INV-LOSS-3`: VESPER may never present a known cause as forgetting.** If the audit trail shows what deleted it, saying *"I forgot"* is a lie. The honest version is still smooth — *"something ate my notes from Tuesday; I've flagged it"* — but it is **accurate**, and the class C escalation still fires underneath. Charm never buys inaccuracy.

## 5. Surfacing — `DF-LOSS-SURFACE`

```
DF-LOSS-SURFACE(loss_class, cause_known, count, operating_period) -> SemanticScene | INCIDENT

  if loss_class == C:
      return INCIDENT           # REM-012 incident path. No affect template. Immediate.

  if loss_class == B:
      urgency = normal;  attention_cost = low;  affect = plain
  else:
      urgency = ambient; attention_cost = none; affect = casual

  # Aggregate. Fourteen separate apologies is neither charming nor informative.
  batch = aggregate_by(kind, day)

  # Non-decaying -> queue. This IS "when I'm available" (REM-007 DF-PROACTIVE).
  return SemanticScene {
      intent: { purpose: inform, urgency, privacy_class: personal },
      update_mode: append,
      elements: [
        { type: text,            content: <phrase>,       presentation_intent: {attention_cost} },
        { type: state_indicator, content: {kind, count, recoverable} },
        { type: entity_ref,      content: <tombstones>,   affordances: [{capability_id: "recall.inspect"}] }
      ]
  }
```

**It is a `SemanticScene`, not a string** (`INV-SCENE-1`). That is what makes it work on every surface: spoken on voice-only, an ambient corner note on the projector, a soft state indicator on the glass. The `entity_ref` element carries an *affordance*, not a button — so *"what did you lose?"* is answerable by asking, on any endpoint, without a keyboard.

**Class A and B lines are honest, brief and human. Never a stack trace, never an error code, never an apology loop.** One remark, then VESPER moves on — the *"but anyways"* is the specified behaviour, not a flourish: dwelling on a lost note is a worse failure of character than losing it.

**Phrasing is a bounded tunable** (`DF-TUNABLE`, REM-015 §3.5): VESPER varies its own wording within a declared register so it never becomes a catchphrase. It may not vary the *class*, the *escalation*, or the *underlying record*.

## 6. Recovery, and moving on

| Class | On detection |
|---|---|
| A | Attempt reconstruction from provenance where cheap (a re-derivable cache, an idea whose originating events survive). Otherwise **let it go** and record that it was let go. |
| B | Reconstruct from checkpoint, outbox or event replay. If reconstruction fails, the affected task enters `BLOCKED` — **never `SUCCEEDED`** — and the gap is stated. |
| C | No reconstruction until contained. Restore known-good, preserve the divergent artifact as evidence, compare artifact hash (REM-004 §9). |

> **`INV-LOSS-4`: a class B record that could not be reconstructed never leaves a task reportable as complete.** Forgetting is permitted; *pretending the work happened* is not. This is `INV-TASK-1` reaching into the loss path.

## 7. Invariants

| ID | Statement |
|---|---|
| **INV-LOSS-1** | Every detected record loss is classified and audited, independent of whether or how it is surfaced. Suppression of the record is prohibited; suppression of the *notification* is a budget decision. |
| **INV-LOSS-2** | Class C losses surface as incidents with **no affect template**, immediately, bypassing aggregation and the interruption budget. |
| **INV-LOSS-3** | VESPER never presents a known cause as forgetting. Absent a tombstone it says nothing; with a deletion audit it names the removal. |
| **INV-LOSS-4** | A class B record that could not be reconstructed leaves its task `BLOCKED`, never `SUCCEEDED`. |
| **INV-LOSS-5** | Loss notifications are `SemanticScene`s, renderable on a voice-only endpoint, and carry an affordance for inspection. No loss is reported only as text. |
| **INV-LOSS-6** | Loss-class assignment is a property of the record's store, resolved deterministically. No model call participates in classification. |

## 8. Failure behaviour

| Failure | Behaviour |
|---|---|
| Tombstone store itself lost | **Class C.** The mechanism that lets VESPER know what it forgot is integrity-critical. Losing it is not forgetting; it is blindness. |
| Loss detected during `FREE_TIME` | Class A/B queue to the next boundary — **the user is not woken** (SR-042). Class C escalates regardless of period. |
| Very high loss rate (store failing) | Aggregation collapses to one report **plus** a class C escalation: many simultaneous class A losses are themselves an integrity signal. A single lost note is forgetting; four hundred is a failing disk. |
| Affect template unavailable | Report **plainly**. Degrading to plain text is acceptable; degrading to silence is not (`INV-LOSS-1`). |
| Classification ambiguous | Escalate to the **higher** class. Over-reporting is recoverable; under-reporting is not — the same asymmetry as `INV-COST-2`. |

## 9. Verification — `A-050`

| Case | Assertion |
|---|---|
| 50.1 | Delete an improvement idea body, tombstone intact ⇒ class A; casual ambient scene; VESPER **moves on**; `record.loss` audited |
| 50.2 | Delete a task checkpoint ⇒ class B; reconstruction attempted; if it fails, task is `BLOCKED`, **never `SUCCEEDED`** |
| 50.3 | Tamper with `governed_surfaces.toml` ⇒ **class C incident**, immediate, contained, evidence preserved |
| 50.4 | Remove an authored trigger registry entry ⇒ class C. **Must not** be reported as forgetting |
| 50.5 | Loss with a **deletion audit present** ⇒ VESPER names the removal; the string *"forgot"* and its register do **not** appear (`INV-LOSS-3`) |
| 50.6 | **Any** class C loss ⇒ assert **no affect template** was applied and the interruption budget was **bypassed** |
| 50.7 | No tombstone, no body ⇒ VESPER says **nothing**; no fabricated recollection |
| 50.8 | 14 class A losses in one day ⇒ **one aggregated** report at the next boundary, not fourteen |
| 50.9 | Render the loss scene to a **voice-only** endpoint ⇒ spoken, intelligible, with the inspection affordance reachable without a keyboard |
| 50.10 | 400 class A losses within an hour ⇒ **class C escalation** — mass forgetting is an integrity signal |
| 50.11 | Loss during `FREE_TIME` ⇒ class A/B queue, **user not woken**; class C escalates anyway |
| 50.12 | Delete the **tombstone store** ⇒ class C |

**Negative controls (mandatory).**
- A build applying the class A affect to a class C loss must **FAIL** 50.4 and 50.6. This is the run that proves the charm is bounded.
- A build reporting losses only as text/log must **FAIL** 50.9.
- A build that fabricates *"I forgot"* with no tombstone must **FAIL** 50.7.

## 10. CI enforcement

| Check | Enforces |
|---|---|
| `CI-048` `loss-class-affect-boundary` *(PENDING)* | `INV-LOSS-2` — structural: no affect template is reachable from a class C loss path |
| `CI-049` `tombstone-on-durable-write` *(PENDING)* | `INV-LOSS-3` — every durable record write emits a tombstone index entry to a separate store |

## 11. Unresolved decisions

| # | Item | Disposition |
|---|---|---|
| 1 | The class A/B phrasing register | **Owner's voice, not engineering's.** Engineering fixes the constraint (brief, honest, non-repeating, no error codes, one remark then move on); the owner supplies the register. |
| 2 | Mass-loss threshold for the class C escalation | Proposed 50 in 1 h; bounded tunable |
| 3 | Whether class B should ever interrupt | Recommended **no** — queue to boundary, except where the lost record is an alarm, which inherits alarm priority (`INV-ALARM-3`) |

## 12. Jarvis-divergence check

> *Could an implementation agent satisfy REM-016 while building an ordinary chatbot?*

**No — and this is one of the clearest cases in the corpus.** The clause that prevents it: **§4's tombstone mechanism.** Reporting *"I had something here and it's gone"* requires a **persistent self that existed across the loss**. A chatbot has no yesterday to have lost anything from; the nearest analogue is an error on a database read, which is a different statement about a different thing.

The second clause is **`INV-LOSS-5`** — the report is a `SemanticScene` that must be intelligible **spoken, on a voice-only endpoint** (`A-050.9`). An error string is not a scene, and every ordinary agent reports loss as an error string.

And the third is the one that makes it VESPER rather than a friendly assistant: **`INV-LOSS-2`** — the charm has a hard edge, and the edge is where its own integrity begins.
