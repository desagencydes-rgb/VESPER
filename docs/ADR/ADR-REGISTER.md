# VESPER — ADR Register

**Purpose.** The authoritative index of which architecture decision records exist, what status each carries, and — for decisions that were made but not filed as a numbered ADR — **where the decision actually lives**.

**Authority.** The Engineering Foundation v1.0 *"Initial ADR Register"* defines the ADR namespace as **ADR-001 … ADR-016**. That register stands to ADR IDs as the COC stands to SR IDs: it is the authority for *which identifiers exist*. This file supplies status and location only. It may not invent an ID.

**Enforced by** `tools/reference_lint.py` (`CI-050`): every `ADR-xxx` referenced anywhere in the corpus must appear here; every ADR file path cited by any document must exist.

---

## 1. Register

| ID | Subject (Foundation wording) | Status | Where the decision lives |
|---|---|---|---|
| **ADR-001** | Event transport: transport, persistence and delivery guarantees | **ACCEPTED** *(see §3)* | `docs/ADR/ADR-001-coordination-substrate.md` |
| **ADR-002** | Persistence engine: task state, memory, provenance, migration and recovery | **PROPOSED** | `docs/ADR/ADR-002-persistence.md` — **blocks F0** via `INV-ADR-1` |
| **ADR-003** | Model runtime abstraction: local/remote normalization without vendor coupling | **DEFERRED — correctly** | Not required before F1. The dependency-direction rule protects it; confirmed by all three adversarial reviews. |
| **ADR-004** | BAG/index architecture: maps + exact + semantic + summaries + caches | **CARRIED BY REM-010 + contracts** | `REM-010 §4`, `contracts/entities/knowledge_map.schema.json`, `contracts/entities/context_budget.schema.json`. Engine selection deferred to F1. |
| **ADR-005** | World model representation: entities, spaces, devices, observations, time, confidence | **CARRIED BY REM-011** | `REM-011 §3.1–3.2`, `contracts/entities/world_fact.schema.json`, `SM-WORLD-FACT`. Superseded as a separate filing. |
| **ADR-006** | Tool sandbox: isolation for code/tool execution | **DEFERRED — bounded** | Local decision, permitted only because the trust-zone boundary is fixed (REM-003). Required before R1. |
| **ADR-007** | Device identity/trust: enrollment, authentication, revocation, recovery | **PROPOSED — owner ratification required** | `docs/ADR/ADR-007-device-identity-and-trust.md` · `OWNER-DECISION-006` |
| **ADR-008** | Presence transport: semantic scenes and interaction events | **CARRIED BY REM-009** | `REM-009 §4`, `contracts/entities/semantic_scene.schema.json`, `contracts/entities/endpoint_capability.schema.json`, `SM-SCENE`, `DF-SELECT-ENDPOINT`, `DF-DEGRADE` |
| **ADR-009** | Autonomous scheduler: triggers, budgets, checkpoints, stop/reporting | **CARRIED BY REM-007 + REM-008** | `REM-007 §4`, `REM-008 §4`, `contracts/entities/trigger.schema.json`, `contracts/policy/trigger_registry.toml`, `contracts/policy/interruption_budget.toml`, `SM-TRIGGER`, `DF-TRIGGER-EVAL` |
| **ADR-010** | Memory retention: automatic/user-approved/expiring/session memory | **CARRIED BY REM-010** | `REM-010 §4`, `DF-MEMORY-AUTHORITY`, `INV-MEM-1` |
| **ADR-011** | Learning boundary: what may change automatically versus reviewed | **CARRIED BY REM-012 + REM-015** | `REM-012 §1`, `REM-015 §4`, `INV-LEARN-1..3`, `INV-TUNE-1`, `contracts/policy/tunables.toml` |
| **ADR-012** | Deployment topology: centralized/edge/replicated/opportunistic services | **ACCEPTED (bounded)** *(see §3)* | `docs/ADR/ADR-012-deployment-topology.md`; extended for opportunistic placement by `REM-014` / `DF-PLACE` |
| **ADR-013** | Observability store: retention and sensitive-data minimization | **CARRIED BY REM-012 + ADR-002** | `REM-012 §6`, `INV-OBS-1/2`; physical store decided in `ADR-002 D2` |
| **ADR-014** | Research promotion: evidence threshold for production | **CARRIED BY REM-012 + REM-015** | `REM-012 §5`, `REM-015 §4`, `SM-IDEA`, `INV-IDEA-3` |
| **ADR-015** | Model assignment: run B01–B08 on actual candidate tools | **PENDING SPIKE-001** | Cannot be decided before measurement. `docs/spikes/SPIKE-001-node-capability-profiles.md` |
| **ADR-016** | First production vertical slice | **PENDING the readiness gate** | Sequencing is fixed by `docs/architecture/IMPLEMENTATION_SEQUENCE.md`; the ADR closes when F0 is authorised. |

---

## 2. The ADR-017…ADR-020 citation defect — resolved

`REM-003`, `REM-004`, `REM-005` and `REM-006` each cited a *"Decision record"* at `ADR-017`…`ADR-020`. **Those IDs do not exist.** The Foundation register defines 001–016 and is the authority for the namespace, exactly as the COC is for SR IDs.

Two resolutions were available:

| Option | Verdict |
|---|---|
| Extend the Foundation register with four new IDs | **Not taken.** The Foundation is a baseline document; extending its namespace is a baseline change, and doing that to satisfy a citation would be a reinterpretation dressed as bookkeeping. |
| **Correct the citations: the REM specification *is* the decision record** | **Taken.** Each of these four REMs already contains the full ADR content — context, options with rejections, decision, consequences, invariants and verification. The ADR pointer was a habit, not a missing artifact. |

| REM | Was cited as | Now records |
|---|---|---|
| REM-003 | `ADR-017-authorization-decision-function.md` | *This specification is the decision record.* `DF-AUTHORIZE`, `INV-AUTH-0..7` |
| REM-004 | `ADR-018-self-modification-boundary.md` | *This specification is the decision record*, with `ADR-012` as the referent. `INV-SELF-1..7` |
| REM-005 | `ADR-019-safety-interlock.md` | *This specification is the decision record.* `SM-INTERLOCK`, `INV-STOP-1..7` |
| REM-006 | `ADR-020-operating-period-and-cost.md` | *This specification is the decision record.* `SM-OPERATING-PERIOD`, `INV-COST-1..7` |

No decision content changed. Four dangling file references were removed and four decision records that already existed were correctly located.

### Retired identifiers

These ids **never existed** and never will. They are recorded here so that the corrective sentences in REM-003…006 may keep naming them — the record of a defect is worth more than a clean grep — while `tools/reference_lint.py` continues to reject any *new* reference that is not one of these.

```toml
retired_ids = ["ADR-017", "ADR-018", "ADR-019", "ADR-020"]
retired_reason = "NEVER_EXISTED — cited by REM-003..006 as decision records; outside the Foundation ADR-001..016 namespace. Corrected 2026-08-12."
```

**If the owner prefers numbered ADRs for these four**, extending the register is a clean baseline addition — raised as an option inside `OWNER-DECISION-006`, not decided here.

---

## 3. The acceptance-authority question

`AUTHORITY_AND_PRECEDENCE §5` assigns ADRs to *"Engineering; owner for security boundaries"*. Baseline 02 §3 assigns ADR approval to the **Chief Architect**; Baseline 02 §16 forbids any agent approving its own security boundary.

- **ADR-001** and **ADR-012** carry `Status: ACCEPTED`, stamped by an engineering pass.
- **ADR-002** is filed `PROPOSED` because accepting it would discharge `INV-ADR-1` — the F0 gate — by the hand that wrote it.
- **ADR-007** is filed `PROPOSED` because it is a security boundary and therefore owner-reserved.

This asymmetry is **recorded, not resolved**. Either the three coordination/persistence/topology ADRs are confirmed together at the readiness gate, or ADR-001 and ADR-012's acceptance should be re-confirmed on the same basis. See `OWNER-DECISION-006`.

---

## 4. What "CARRIED BY REM-xxx" means, precisely

It means the decision is **made and enforceable**, not that it is pending. Each such row satisfies all four ADR obligations:

| Obligation | Where it is discharged in a REM |
|---|---|
| Context and problem | §1 Problem, §2 Authoritative requirement |
| Options with recorded rejections | §4 Required behaviour, and §14 Unresolved decisions for what was deliberately left open |
| Decision | §4, §7 Invariants, §10 Contract / state machine / decision function |
| Consequences and verification | §8 Failure behaviour, §11 Verification, §12 CI enforcement |

A row is `CARRIED BY` only where all four are present. Rows where they are not — ADR-003, ADR-006, ADR-015, ADR-016 — are marked `DEFERRED` or `PENDING` with the gate at which they close.
