# ADR-012 — Deployment topology and the runtime ↔ repository boundary

| | |
|---|---|
| **Status** | **ACCEPTED (bounded)** — resolved exactly far enough to give REM-004 a referent; concrete packaging remains open |
| **Date** | 2026-08-11 |
| **Owner** | Chief Architect / System Integrator |
| **Supersedes** | Foundation ADR-012 — previously *Intentionally unresolved* |
| **Source requirements** | SR-015, SR-019, SR-042, SR-048, SR-049 |
| **Remediation** | `docs/remediation/REM-002`, `docs/remediation/REM-004` |
| **Closes** | AR-009 (P0, in part) · the referent half of NV-01 (P0) |

## Context

The third adversarial verification identified that *"the runtime may not write to `core/`"* is **not yet a well-formed statement**, because the relationship between the running VESPER process and the VESPER repository is undefined. A prohibition needs a referent. ADR-012 was filed *"Intentionally unresolved"* while the entire NV-01 correction depends on it.

Separately, the corpus's headline continuity claim — identity and state survive device loss — has no mechanism, and the handwritten source makes the desktop *"main assistant's space if Macbook not available"*, which is a **promotion** with no election, lease or partition rule.

## Problem

Two questions must be answered, and only two, for the blocked work to proceed:

1. **What is the relationship between the running process and the repository?** (NV-01's referent.)
2. **How many writable control planes exist, and how does authority move between nodes?** (AR-002.)

Anything beyond those two — container runtime, packaging format, process supervisor — is genuinely deferrable and is deliberately left open.

## Constraints

- SR-042 authorizes VESPER to *"code stuff"* overnight, unattended. Any topology that makes overnight coding impossible violates a source requirement.
- SR-049 makes the system's own code and rules "sacred". Any topology that lets the runtime silently rewrite them violates it in the other direction.
- The fabric is partition-prone by design (`SRC-GAP-007`).
- A single-user home network. Multi-region consensus machinery is not proportionate.

## Options — question 1 (runtime ↔ repository)

| # | Option | Verdict |
|---|---|---|
| 1 | Runtime executes **directly from the working repository** | **Rejected.** A self-directed file write and a governed source change become the same operation. NV-01 becomes unenforceable at the filesystem, leaving only model disposition — which is exactly the failure the review names. |
| 2 | Runtime executes from a **pinned deployed artifact** distinct from the working repository; promotion is a human-gated build | **ACCEPTED.** Makes the boundary physical rather than behavioural, and mechanically checkable. |
| 3 | Runtime executes from the repository but governed paths are protected by OS permissions | **Rejected as primary**, retained as defence-in-depth. Permissions are re-grantable by a process that can escalate; the boundary must not depend on the thing it is protecting against. |

## Options — question 2 (control plane)

| # | Option | Verdict |
|---|---|---|
| 1 | Single fixed control plane on one node | **Rejected.** Contradicts the source: the desktop must be able to become the main space when the MacBook is absent. |
| 2 | **Single writable control plane with per-domain ownership leases and one designated standby** | **ACCEPTED.** Matches the source's stated promotion behaviour, bounds divergence, and keeps writes single-writer per domain. |
| 3 | Leaderless multi-writer replication with CRDT merge | **Rejected.** Unjustified complexity at ≤ 8 nodes, and it makes policy and alarm state — where "one authoritative answer" is a safety property — hardest to reason about. |

## Decision

### D1 — Deployment boundary (the NV-01 referent)

```
WORKING REPOSITORY            DEPLOYED RUNTIME ARTIFACT
docs/ contracts/ spec/        immutable, content-addressed,
verification/ tools/ src/     version-pinned
        │                              │
        │   ┌──────────────────┐       │
        └──►│ PROMOTION        │──────►│
            │ human-gated build │       │
            │ E3 merge + E4 cut │       │
            └──────────────────┘       │
                                       ▼
                              running VESPER process
                              (holds E1 at most)
```

1. The running VESPER process executes from a **deployed artifact**: immutable, content-addressed, version-pinned, and **not** the working repository.
2. The deployed artifact is produced only by the **promotion step**, which is a human-gated build (`E3` merge into `main` under CODEOWNERS, then `E4` release cut). No runtime code path performs promotion.
3. The runtime's filesystem capability set **never includes** the working repository's governed paths. The prohibition is enforced by capability, not by policy text or model disposition. Governed paths are enumerated in REM-004 §4.2.
4. The runtime holds a **workspace** — a writable area, separate from both the repository and the artifact — in which it may create, edit, run, test and version code freely. This is where SR-042's overnight "code stuff" happens. It is unrestricted.
5. The only path from workspace to running configuration is a **proposal**: the runtime emits a `change.proposal` with a diff and evidence; a human reviews and merges; a promotion builds a new artifact. **The runtime may open a proposal; it may never self-merge.**
6. Configuration read by the runtime is split into `policy/` (governed, artifact-pinned, read-only to the runtime) and `state/` (runtime-owned, writable). No file is both.

**This is the whole of ADR-012 that NV-01 needs.** Packaging format, process supervisor, and update transport remain open and are recorded as such.

### D2 — Control plane

1. **Single writable control plane** with **per-domain ownership leases** and **one designated standby**.
2. **State domains** (exactly one lease holder each, at any instant): `tasks`, `world`, `memory`, `devices`, `policy`, `autonomy_queue`, `alarms`.
3. **Lease TTL and renewal interval are configuration.** Expiry demotes the holder and emits `control.lease_lost`.
4. **Non-owner behaviour is declared per domain**: `READ_CACHED` (marked stale), `QUEUE_WRITES`, or `REFUSE`. Default **`REFUSE`** for `policy` and `alarms`.
5. **Promotion** is automatic on clean lease expiry **with a quorum of reachable enrolled nodes**; **MANUAL** where quorum is unavailable. **Never automatic on partition alone.**
6. **Partition behaviour.** A disconnected node MAY execute already-authorized local work; MUST queue `world`/`memory` writes; MUST NOT issue external actions (`L4`+); MUST NOT self-promote.
7. **Rejoin.** Queued writes apply under ADR-001 supersession. **Owner-wins** for `policy` and `devices`; **supersession-wins** for `world` and `memory`; task state reconciles through the outbox (REM-011).
8. **`alarms` is the deliberate exception** to "single firer": on partition the failure direction is **FIRE**, resolved by lease-based single-firer election where connectivity permits and by duplicate-tolerant acknowledgement where it does not. A duplicate alarm is far safer than a missed one (REM-011).

## Consequences

**Positive.** NV-01's boundary acquires a referent and becomes checkable by a static CI test rather than by inspection. The desktop can legitimately become the main space, with a stated rule. Partition stops being undefined behaviour.

**Negative / accepted costs.** A promotion step means VESPER cannot deploy its own improvements without a human — which is precisely the intent, and is the cost the owner is asked to accept in `OWNER-DECISION-001`. Leases add a renewal path and a demotion path to the control plane. The `alarms` exception is a genuine asymmetry in the model and must be tested separately (`A-041`).

**Explicitly preserved.** Overnight autonomous research, experimentation, code generation, testing and proposal are **unrestricted** in the workspace. This ADR restricts *merging into governing surfaces*, not *working*.

## Still open (recorded, not deferred silently)

| # | Open item | Why it is safe to defer |
|---|---|---|
| 1 | Artifact packaging format and process supervisor | Adapter-isolated by the dependency-direction rule; no contract depends on it. |
| 2 | Update transport between nodes | Constrained by D1 (must preserve pinning + human gate) but not determined by it. |
| 3 | Lease TTL / renewal numeric values | Configuration; the *existence* of the lease is architectural. |
| 4 | Quorum size for promotion | Configuration, bounded by "never automatic on partition alone". |

## Acceptance tests

`A-034` (control-plane lease, failover, partition, rejoin) · `A-030` (runtime self-modification boundary) · `A-017` extended.
