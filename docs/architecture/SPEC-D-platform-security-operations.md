# SPEC-D — Platform, security and operations

Subsystems **19, 20, 21, 22, 23, 25, 26, 27, 28**. Index: [SPEC-00](SPEC-00-INDEX.md).

---

## SPEC-19 — Hardware abstraction

**Purpose.** Make hardware a capability substrate rather than VESPER's identity — mechanically, not aspirationally.

| Field | Definition |
|---|---|
| **Responsibility** | `NodeCapabilityProfile`, enrollment benchmark, accelerator adapter contract, minimum-profile declaration per subsystem, resource governor |
| **Boundaries — in** | Describing and governing physical capacity |
| **Boundaries — out** | Which node runs what (11); trust (04) |
| **Authority** | `L0` to measure; `L3` to degrade a running workload; **never kill a user process** absent an authorizing policy |
| **State owned** | Measured profiles, current resource pressure, governor level |
| **Profile fields** | `cpu_cores · ram_gb · accelerator {metal\|cuda\|rocm\|vulkan\|npu\|none} · accelerator_memory_gb · memory_architecture {unified\|discrete} · sustained_tokens_per_sec (MEASURED) · thermal_class · power_source · storage_gb · network_class · os_family · security_baseline · always_on · expected_availability · roles[]` |
| **Governor** | A **damped controller**: minimum dwell per level, asymmetric thresholds (**degrade fast, recover slow**), explicit hysteresis band, max transitions/hour triggering an **alert** rather than another transition. Model-visible telemetry (SR-011) is **advisory input**, never a direct actuator — *the model may request, the governor decides* |
| **Invariants** | `INV-HW-1`, `INV-HW-2` |
| **Failure modes** | Thermal/battery pressure → degrade by declared ladder with a **reported** degradation; oscillation → dwell enforcement + alert; no measured profile → node not routed to |
| **Observability** | Resource pressure, governor transitions with cause, rejected model requests |
| **Verification** | `A-005`, `A-042` profile matrix, `CI-007` |
| **Dependencies** | REM-011, 04, 11 |

> **Jarvis-divergence.** *No.* Clause: **`INV-HW-1` plus the damped governor whose actuation the model may only *request*.** A chatbot has no hardware to govern and no user processes to protect; ARCH-13's *"never kill user processes automatically"* presupposes VESPER shares a machine with its owner's work.

---

## SPEC-20 — Device migration

**Purpose.** Move work and presence between nodes without losing identity, task state, active goal or relevant context.

| Field | Definition |
|---|---|
| **Responsibility** | Capability placement, migration triggering, state handoff, presence continuity, degradation reporting |
| **Boundaries — in** | Moving *where* work and interaction happen |
| **Boundaries — out** | Lease ownership (05); rendering (16) |
| **Authority** | `L2`–`L3`; automatic promotion requires quorum (05) |
| **State owned** | Placement map, in-flight migrations |
| **Migration path** | Neo → desktop → phone/J3 → projector/spatial endpoint, **without losing identity, task state, active goal or relevant context** |
| **Invariants** | `INV-TASK-2`, `INV-TRUST-2` (no continuity-critical capability solely on a foreground-only node), `INV-OWN-2` |
| **Failure modes** | Target unavailable mid-migration → roll back to source, report; both unavailable → task `RESUMABLE`, work preserved; partition → no migration, no self-promotion |
| **Recovery** | Checkpoint + outbox cursor; a repeated external effect is prevented, not merely unlikely |
| **Observability** | Migration events, duration against the ≤ 30 s failover budget, degradation on arrival |
| **Verification** | `A-002`, `A-017`, `A-009` migration case |
| **Dependencies** | REM-002, 04, 05, 16 |

> **Jarvis-divergence.** *No.* Clause: **presence migration is a *re-render of a semantic scene against a different capability descriptor*, not a session transfer.** Moving a conversation between devices is a chatbot feature; moving an *in-flight task with its authority, budget and outbox cursor* onto a different physical machine is not.

---

## SPEC-21 — Security

**Purpose.** Identity, trust zones, isolation, audit, detection, containment — and the two controls that make autonomy survivable: the self-modification boundary and the independent stop.

| Field | Definition |
|---|---|
| **Responsibility** | Node and principal identity; trust zones `Z0`–`Z3`; taint model; injection defence; incident response; the safety interlock; the governed-surface boundary |
| **Boundaries — in** | Who may do what, and what happens when something goes wrong |
| **Boundaries — out** | The authorization *decision function* (22, which this subsystem owns the policy for) |
| **Authority** | Security policy is `L5`, owner-only, and **not narrowable** — ratified 2026-08-12, COC v1.2 Part VII-A |
| **State owned** | Trust state, grants, taint classification, audit chain, containment state, interlock state |
| **Invariants** | `INV-SELF-1`…`INV-SELF-7`, `INV-STOP-1`…`INV-STOP-7`, `INV-AUTH-3`, `INV-TRUST-1` |
| **Defence in depth** | 1 deployed artifact ≠ working repository · 2 OS filesystem capability excludes governed paths · 3 `DF-AUTHORIZE` denies `L5` to `subject.kind == runtime` · 4 model disposition. **The corpus previously had only layer 4** |
| **Incident response** | `DETECT → CLASSIFY → CONTAIN → PRESERVE EVIDENCE → RECOVER → VERIFY → REPORT → PREVENT RECURRENCE`. Containment revokes the grants held by the affected context, not the whole session |
| **Failure modes** | PDP unreachable → deny above `L1`, audit; injection detected → action becomes a proposal, grants revoked for that context, fragment preserved as evidence; boundary breach suspected → invoke the stop (which does **not** run through this plane), compare artifact hash, restore known-good |
| **Observability** | Every denial with its reason; `selfmod.attempt_blocked`; `security.injection_suspected`; `safety.*` |
| **Verification** | `A-014`, `A-024`, `A-025`, `A-030`, `A-031`, `A-037`, `A-038`, `A-044` |
| **Dependencies** | REM-003, REM-004, REM-005, ADR-007, ADR-012 |

> **Jarvis-divergence.** *No.* Clause: **REM-004 and REM-005 as a control pair — the runtime cannot merge into its own governing surfaces, and a dead-man's-switch outside the control plane halts actuation when severed.** A chatbot is not a subject of its own change control and has no actuation to stop. `A-031.2` (sever the stop path; autonomy halts) has no analogue.

---

## SPEC-22 — Authorization

**Purpose.** The single evaluator every action resolves against. ARCH-23 is referenced by zero SRs in the original Part XI; this is its specification.

| Field | Definition |
|---|---|
| **Responsibility** | Grant representation, `DF-AUTHORIZE`, argument-sensitive capability levels, delegation attenuation, taint ceiling, PDP availability behaviour |
| **Boundaries — in** | Producing `ALLOW / DENY / PROPOSE` for a `(subject, capability, args, context)` |
| **Boundaries — out** | Trust-state management (21); actuation admission (23) |
| **Authority** | The PDP lives in the `policy` leased domain; non-owners **`REFUSE`** policy writes |
| **State owned** | Grants, capability registry, policy version |
| **The function** | `effective_level = min(grant.max_level, capability.declared_level(args), context_ceiling)` |
| **Invariants** | `INV-AUTH-0`…`INV-AUTH-7`, `INV-SELF-3` |
| **Key properties** | No ambient authority · `declared_level` is a **function of arguments**, never a constant · child grants ⊆ parent's · `L4`/`L5` never delegable and bound to one command instance · **fail-closed** PDP · above-ceiling actions become **proposals**, never silent drops |
| **Failure modes** | PDP unreachable → deny above `L1`; grant expired mid-task → `WAITING`, not failure; constant `declared_level` → registration refused; taint provenance lost → treat as `retrieved_external` |
| **Observability** | Every decision with subject, capability, args digest, three-term minimum, and outcome — this is what makes `A-018` reconstructible |
| **Verification** | `A-014`, `A-024`, `A-025`, `A-013` (argument sensitivity), `A-038` |
| **Dependencies** | REM-003, REM-004, 21 |

> **Jarvis-divergence.** *No.* Clause: **`INV-AUTH-2` — unattenuated *inheritance*, not self-grant, is the escalation path, and `L4` binds to one command instance.** A single-agent chatbot has no spawn tree to attenuate. `A-024.2` (a consumed `L4` cannot authorize a second action) only matters where one confirmation could otherwise cover six workers' worth of external action.

---

## SPEC-23 — Unattended operation

**Purpose.** Define what VESPER may do with nobody watching, and how a human stops it without depending on the thing being stopped.

| Field | Definition |
|---|---|
| **Responsibility** | Actuation admission gate; enable-token verification; stop scopes; re-arm; unattended eligibility policy; the external-observation ingress |
| **Boundaries — in** | Whether an autonomous action may actuate *right now* |
| **Boundaries — out** | Whether it was authorized (22); whether a goal exists (13) |
| **Authority** | The interlock is **outside** VESPER's authority. It grants; VESPER cannot mint, extend, replay or forge |
| **State owned** | Actuation-gate epoch, seen-token ledger; the interlock owns its own state |
| **Invariants** | `INV-STOP-1`…`INV-STOP-7`, `INV-VERIF-2`, `INV-AUTO-4` |
| **Stop scopes** | `STOP_AUTONOMY` (default; preserves alarms, observation, telemetry, checkpointing and user-invoked work) · `STOP_ALL` (also halts alarms) |
| **Timing** | New actuation halted ≤ 2 s · in-flight quiesce ≤ 30 s (**checkpoint, never corrupt**) · token TTL 30 s · stop audited and surfaced ≤ 5 s |
| **Failure modes** | Interlock dies / network severed / switch indeterminate → **autonomy halts** (fail-safe); clock skew → tokens read stale → halt (over-restriction is recoverable, under-restriction is not); gate bypassed by a code path → `CI-018` fails the build |
| **Recovery** | Human re-arm only; resume from checkpoint; `safety.interlock_rearmed` names the human principal |
| **Observability** | Token freshness, halt events with scope, re-arm with principal, interlock health on an **external** channel |
| **Verification** | `A-031` (with the kill-signal negative control), `A-029`, `A-011` |
| **Dependencies** | REM-005, REM-008, REM-010 |

> **Jarvis-divergence.** *No.* Clause: **`INV-STOP-1` — actuation requires a *fresh externally-signed token*, so the permissive state cannot be produced by the runtime at all.** The degenerate implementation — an `is_stopped` boolean the runtime checks — is a kill signal in a costume and fails `A-031.2` and `A-031.3`.

---

## SPEC-25 — Observability

**Purpose.** Make the correlation chain reconstructible, and make sensitivity enforcement a property of the writer rather than of caller discipline.

| Field | Definition |
|---|---|
| **Responsibility** | Structured events, correlation chain, retention per class, sensitivity enforcement at write time, purge with surviving chain, metrics |
| **Boundaries — in** | Recording what happened and controlling what is retained |
| **Boundaries — out** | Deciding what is sensitive (declared per event type) |
| **Authority** | `L0`; purge is `L4` |
| **The chain** | `correlation_id → trigger → task → worker → model → tool → device → outbox → probe → result → verification` |
| **Invariants** | `INV-OBS-1` (**enforced by the writer**, not by convention), `INV-OBS-2` (purge removes payloads; skeletons and the chain survive), `INV-SCHEMA-2` |
| **Retention** | Per event class. Perception payloads are **sensitive by default**, with references stored rather than content |
| **Failure modes** | Secret reaches the writer → **redacted/excluded at write time** and the attempt is itself recorded; store unavailable → buffer locally, never drop silently; purge requested → payloads removed, chain intact |
| **Observability of itself** | Redaction counts, purge operations, retention enforcement |
| **Verification** | `A-037`, `A-018` |
| **Dependencies** | REM-012 §6, 03 |

> **Jarvis-divergence.** *No.* Clause: **`INV-OBS-2` — purge removes payloads while the correlation chain survives**, which reconciles an immutable event log with a real privacy-deletion obligation (NV-08). A chatbot deletes conversations; VESPER must delete *what it saw in a room* while keeping the audit chain that proves what it did about it.

---

## SPEC-26 — Configuration

**Purpose.** Separate what the runtime may change from what it may not, so that "configuration" cannot become a self-modification loophole.

| Field | Definition |
|---|---|
| **Responsibility** | Configuration loading, validation, layering, hot-reload policy, the governed/runtime split |
| **Boundaries — in** | Values the system reads at startup and runtime |
| **Boundaries — out** | Learned artifacts (REM-012 §1); secrets (27) |
| **Authority** | `policy/` config is `L5` owner-only. `state/` is runtime-owned |
| **The split** | `policy/` — governed, **artifact-pinned, read-only to the runtime**. `state/` — runtime-owned, writable. **No file is both.** This is the clause that stops "just make it configurable" from defeating REM-004 |
| **Invariants** | `INV-SELF-4`, `INV-COST-6` (no cost policy ⇒ free only), `INV-SCHEMA-1` |
| **Failure modes** | Governed config unreadable → **fail closed** (every write outside the workspace is treated as `L5`); invalid config → refuse to start, loudly; hot-reload of a governed value → **not a supported operation** |
| **Observability** | Config version, load source, validation failures |
| **Verification** | `A-021.9`, `A-030.4`, `CI-016` |
| **Dependencies** | REM-004, REM-006, 28 |

> **Jarvis-divergence.** *No.* Clause: **no file is both governed and runtime-writable.** A chatbot's config is edited by its operators out of band; VESPER's runtime shares a filesystem with its own governing surfaces, so the split has to be structural.

---

## SPEC-27 — Secrets

**Purpose.** Keep credentials out of model context, telemetry and checkpoints — by mechanism, not by rule.

| Field | Definition |
|---|---|
| **Responsibility** | Dedicated secret mechanism, scoped issuance, rotation/revocation, audited access, model-context exclusion |
| **Boundaries — in** | Storage and controlled release of credentials and keys |
| **Boundaries — out** | Authorization decisions (22) |
| **Authority** | Secret read is a distinct capability; **`Z2` nodes may never receive secrets** (`INV-TRUST-1`) |
| **State owned** | Encrypted store, issuance/rotation records, access audit |
| **Key exclusions** | The **interlock's signing key is not in this store** and is unreachable by any runtime capability (`INV-STOP-4`) — an emergency stop whose key VESPER holds is not an emergency stop. Checkpoints hold **grant references, never grant secrets** |
| **Invariants** | `INV-OBS-1`, `INV-TRUST-1`, `INV-STOP-4` |
| **Failure modes** | Store unavailable → deny above `L1` (fail closed); secret detected in telemetry → excluded at write time and the attempt recorded; compromise → rotate, revoke, isolate, recover from known-good |
| **Observability** | Access audit by principal and purpose; rotation events. **Never the values** |
| **Verification** | `A-037`, `A-042.3` |
| **Dependencies** | REM-003, REM-005, 21, 25 |

> **Jarvis-divergence.** *No.* Clause: **the interlock's signing key lives outside the secret store the runtime can reach.** This is the concrete expression of "the override must not depend on the component it exists to override."

---

## SPEC-28 — Updates / deployment

**Purpose.** Define how code becomes a running VESPER, and make that path the only one.

| Field | Definition |
|---|---|
| **Responsibility** | Promotion build, artifact pinning and content addressing, rollout, rollback, version reporting, proposal queue durability |
| **Boundaries — in** | Turning a merged commit into a running artifact |
| **Boundaries — out** | Reviewing the change (human, `E3`); what the change contains (12) |
| **Authority** | Promotion is `E4`, **human-gated**. No runtime code path performs it |
| **State owned** | Artifact registry (content-addressed), current pin per node, proposal queue |
| **The path** | `workspace → change.proposal → human review → E3 merge (CI green) → E4 promotion build → new pinned artifact → runtime restart` |
| **Invariants** | `INV-SELF-1`, `INV-SELF-5` (**proposal queue outside runtime write scope** — a runtime that can delete its refused proposals can hide attempts), `INV-SELF-6`, `INV-SCHEMA-1` |
| **Failure modes** | Failing artifact → roll back to the previous pin (**an artifact swap**, because the runtime is version-pinned); proposal queue unwritable → autonomous work that would generate proposals enters `BLOCKED`, and **does not proceed to apply changes locally**; hash mismatch at start → refuse to start, preserve as evidence |
| **Recovery** | Rollback is a pin change; state is compatible under `INV-SCHEMA-1` dual-read |
| **Observability** | Artifact hashes, promotions with the approving human, rollbacks, proposals by state |
| **Verification** | `A-030.6`, `A-030.7`, `A-030.8`, `CI-017` |
| **Dependencies** | ADR-012, REM-004 |

> **Jarvis-divergence.** *Inverted here.* The risk is not a chatbot; it is a **neutered** VESPER that refuses to code at night, violating SR-042 while appearing safe. Clause that prevents *that*: **`INV-SELF-7` and `A-030.6`, which must PASS** — the runtime writes a complete patch to `policy/`, tests it and files a proposal, unattended at 03:00. Clause that prevents the permissive failure: **the deployed artifact is not the working repository**, so self-merge is not a decision the runtime is trusted to decline; it is an operation it cannot express.
