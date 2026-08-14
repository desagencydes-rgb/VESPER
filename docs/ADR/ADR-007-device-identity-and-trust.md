# ADR-007 — Node cryptographic identity, enrollment, attestation, revocation and recovery

| | |
|---|---|
| **Status** | **ACCEPTED** — ratified by the project owner 2026-08-14, as written, under `OWNER-DECISION-006(a)`, option A. Previously `PROPOSED`. This is a security boundary; `AUTHORITY_AND_PRECEDENCE §5` reserves those for the project owner, and Baseline 02 §16 forbids an agent approving its own security boundary — so this line was not writable by engineering on its own authority. |
| **Ratification record** | The owner's stated condition was that each device hold its own keys with separate keys used for verification. That is D1 (per-node Ed25519 keypair; `node_id` is the fingerprint of the public key) and D7 (a separate owner enrollment key, held off every node). The four practical consequences were put to the owner before ratification and accepted: no trust-on-first-use at enrollment (D3), non-overridable automatic demotion on storage degradation (D4), the file-based-key handset admitted at `Z2` rather than excluded (D2), and loss of the enrollment key halting new enrollments while the fabric continues (D7). One clarification was made and is recorded because a ratification should not rest on a conflation: **this record is IDENTITY, not transport encryption.** It establishes which node is which. The encrypted channel between sites is `SPIKE-009`'s fabric, a different layer, and ADR-007's §D4 session binding runs over it rather than replacing it. |
| **Date** | 2026-08-12 |
| **Owner** | Device/Network Engineer · Security Engineer |
| **Supersedes** | Foundation ADR-007 *"Device identity/trust: enrollment, authentication, revocation, recovery"* — previously *Intentionally unresolved* |
| **Source requirements** | SR-015, SR-018, SR-019, SR-038, SR-049, SR-050, SR-058, SR-060 |
| **Derived** | DR-002, DR-008, DR-024, DR-027 |
| **Remediation** | `docs/remediation/REM-011 §3.6–3.7` (capability profile, enrollment gate) · `REM-002` (quorum membership) |
| **Closes** | GAP-016 · AR-018 (the identity half) |
| **Blocks** | The event envelope: ADR-001 §Security requires `hlc.node_id` to be *"the node's cryptographic identity from ADR-007, not a self-asserted name"*. Until this is settled, `node_id` has no defined provenance and supersession is forgeable. |

## Context

Three specifications consume a node identity that no record defines.

- **ADR-001** puts `node_id` inside the HLC tuple and states that a self-asserted name lets a compromised node forge supersession by claiming another node's identity.
- **REM-002 §4.3** promotes a lease on *"a quorum of reachable **enrolled** nodes"* — a membership set with no definition of membership.
- **REM-011 §3.7** specifies the *admission gate* between `ENROLLED` and `TRUSTED` (minimum security baseline, key storage, capability floor, re-attestation interval) but not the **identity** that gate is applied to, nor how it is proven on each subsequent connection.

REM-011 answered *"what must a node satisfy to be trusted?"*. This record answers *"how does the fabric know which node it is talking to, and what happens when that answer changes?"*

## Problem

1. **Identity material.** What is a `node_id`, where does its private key live, and what happens on a node class where key storage is weak (the J3) or where the OS may evict the process (the iPhone)?
2. **Enrollment.** How does a node get an identity in the first place without a trust-on-first-use hole on a home LAN that `REM-011` already says *"visibility on a LAN does not imply trust"*?
3. **Ongoing proof.** An identity proven once at enrollment and never again is a bearer token with a long life.
4. **Revocation.** A revoked node must stop being able to write, and must stop counting toward quorum, and must do so on nodes that were **partitioned during the revocation** — the hard case.
5. **Recovery.** The owner's laptop is stolen or wiped. It held a `Z0` identity. What restores the fabric without the theft becoming a permanent trusted foothold?

## Constraints

- ≤ 8 nodes, one human owner, no PKI operations staff, no certificate authority to run.
- Node classes differ by an order of magnitude in key-storage quality. The design must degrade by **assigning a lower trust zone**, never by weakening the protocol.
- A node may be offline for days by design (SR-058) and must be able to rejoin without a fresh enrollment ceremony.
- Revocation must not require quorum, because the case that matters most is *"a node is compromised while the fabric is partitioned"*.
- `INV-TRUST-1`: a `Z2` node may not hold state, issue commands, or receive secrets — so its identity must be usable for *rendering and observing* while being structurally unable to do the rest.

## Options

| # | Option | Verdict |
|---|---|---|
| 1 | Self-asserted node names + shared LAN secret | **Rejected.** This is the status quo the ADR-001 security note falsifies. One leaked secret is total compromise, and supersession becomes forgeable. |
| 2 | Full internal PKI (CA, intermediate, CRL/OCSP) | **Rejected.** Correct but disproportionate for eight nodes and one human. An unmaintained CA is worse than no CA: expiry becomes an outage nobody can diagnose. |
| 3 | **Per-node Ed25519 keypair; `node_id` = the public key fingerprint; owner-signed enrollment certificate; short-lived session proof; owner-signed revocation list replicated as ordinary events** | **ACCEPTED.** Proportionate, offline-friendly, and revocation propagates through the machinery that already exists. |
| 4 | Platform attestation only (Secure Enclave / StrongBox / TPM) as the sole identity | **Rejected as sole mechanism, adopted as a trust-zone input.** Not available on all target node classes; making it mandatory would exclude the J3 entirely rather than placing it in `Z2`, which is the outcome REM-011 deliberately chose. |

## Decision

### D1 — Identity material

Every node generates an **Ed25519** keypair at first start. `node_id = "nd_" + base32(sha256(public_key))[:26]`, stable for the life of the key. The private key never leaves the node and is never included in any checkpoint, backup, telemetry record, or model context.

`node_id` is the value that appears in `hlc.node_id`, in `lease.holder`, and in every audit record. It is a **fingerprint of a key**, so claiming another node's identity requires that node's private key.

### D2 — Key storage determines the trust-zone ceiling

Key storage quality is an **input to zone assignment**, not a pass/fail on enrollment. This is the mechanism that lets the J3 participate without granting it control-plane trust.

| Key storage | Zone ceiling | Rationale |
|---|---|---|
| Hardware-backed, non-exportable (Secure Enclave, StrongBox, TPM) | `Z0` | Key extraction requires physical attack |
| OS keychain / keystore, non-exportable, device-locked | `Z0` | Acceptable for the owner's primary nodes |
| OS keychain, exportable, or software keystore | `Z1` | May execute bounded work; holds no policy authority |
| File-based key with filesystem permissions only | **`Z2`** | May render and observe; may not hold state, issue commands, or receive secrets (`INV-TRUST-1`) |
| No usable key storage | Not enrollable | A node that cannot keep a secret cannot have an identity |

A node **cannot raise its own ceiling**: `security_baseline` and `key_storage_class` are fields of `NodeCapabilityProfile`, measured at enrollment (`INV-HW-2`), and the zone is derived from them by rule, not declared.

### D3 — Enrollment requires an out-of-band owner act

There is **no trust-on-first-use**. Enrollment is:

1. The candidate node generates its keypair and displays/emits its `node_id` fingerprint.
2. The owner confirms that fingerprint **on an already-`Z0` node**, through an authenticated surface — the fingerprint is compared out of band, not accepted from the network.
3. The control plane issues an **enrollment certificate**: `{node_id, roles[], zone, key_storage_class, issued_at_hlc, reattest_interval, owner_signature}`, signed by the owner enrollment key (D7).
4. The node transitions `DISCOVERED → ENROLLED`. `ENROLLED → TRUSTED` remains REM-011 §3.7's admission gate, unchanged. `SM-DEVICE` already prohibits `DISCOVERED → TRUSTED`.

The `A-029` synthetic observer is enrolled by this same path as a `Z2 sensor_node`, which is what makes `INV-AUTO-4`'s external ingress a production mechanism rather than test scaffolding.

### D4 — Ongoing proof: session binding, not a bearer token

Every connection between nodes performs a mutual challenge–response over the node keys, establishing a session bound to `(node_id, lease_epoch_at_bind)`. Session lifetime ≤ `reattest_interval`. Writes carry the session identifier; a write whose session predates the current epoch is rejected by the same fencing statement as a stale-epoch write (ADR-002 D3).

**Re-attestation interval** by zone: `Z0` 7 days · `Z1` 24 h · `Z2` 24 h. Re-attestation re-measures `NodeCapabilityProfile` security fields; a node whose storage class has degraded (e.g. keychain unlocked to exportable) is **demoted automatically** and the demotion is emitted, never silent.

### D5 — Revocation propagates as an ordinary event, and does not need quorum

The owner signs a **revocation entry** `{node_id, revoked_at_hlc, reason, owner_signature}`. It is written to `audit.db` and published on the event bus as a normal HLC-ordered event, so it flows through at-least-once delivery and supersession exactly like every other fact.

Three properties make this hold in the case that matters:

- **No quorum needed.** A single owner signature is sufficient. A compromise during partition is exactly when quorum is unavailable.
- **Revocation is monotone.** Un-revocation is not an event type. Restoring a node requires a **new keypair and a new enrollment**, so a replayed old certificate can never resurrect it.
- **A partitioned node learns on rejoin, and is fenced meanwhile.** Its lease expires at TTL (REM-002), it cannot self-promote (`INV-OWN-2`), and its queued writes are applied as ordinary non-owner writes subject to supersession — never with owner authority.

### D6 — Compromise response

On revocation the control plane: drops all sessions bound to that `node_id`; removes it from quorum membership; marks facts it sourced as **`CONFLICTED` rather than deleting them** (deletion would destroy the evidence of what it wrote); requires re-verification of any `L4`+ external action it originated since its last clean re-attestation; and emits a class C `RecordLoss` if any `audit.db` or `tombstones.db` content it held is unrecoverable (`INV-LOSS-2` — incident, no affect).

### D7 — The owner enrollment key, and the recovery case

The owner holds a **separate enrollment key**, not stored on any single node and not in the runtime's secret store — the same separation principle as the emergency-stop signing key (REM-005), and for the same reason: a key the runtime can reach is a key a compromised runtime can use.

Recovery when a `Z0` node is lost or stolen:

1. Revoke from any surviving node using the owner enrollment key (D5). No quorum required.
2. Leases held by the lost node expire at TTL; promotion follows REM-002 §4.3 — **automatic only with quorum, operator-confirmed otherwise**.
3. Restore state from backup (ADR-002 D10) onto a replacement node, which enrolls as a **new identity**. The old `node_id` is never reissued.
4. If the enrollment key itself is lost, the fabric continues operating but **can enroll nothing new**. Re-establishing it is an owner ceremony on a `Z0` node and is a class C audit event. Recorded as open item 2.

## Consequences

**Positive.** `hlc.node_id` becomes unforgeable, so ADR-001's supersession rule is sound against a compromised node rather than only against a buggy one. Quorum membership becomes a defined set. The J3 gains a principled place in the fabric — the design *degrades the zone*, not the protocol, which is the exact resolution REM-011 chose for SR-018.

**Negative / accepted costs.** Enrollment now requires a deliberate owner act with an out-of-band fingerprint comparison; adding a node is minutes, not seconds. Re-attestation can demote a node the owner considers fine, and that demotion is intentionally not overridable at runtime. Losing the enrollment key is an unpleasant state — bounded, but real.

**Rejected shortcut.** "Trust anything already on the home LAN" is the natural implementation and is prohibited by D3, because REM-011 already recorded that visibility on a LAN does not imply trust, and because SR-038 requires VESPER to treat its own network as a place intruders can appear.

## Interfaces

`IC-004` (device), `IC-009` (security). Contracts: `contracts/entities/node_capability_profile.schema.json` (adds `key_storage_class`, `enrollment_certificate_ref`), `contracts/events/event_envelope.schema.json` (`hlc.node_id` provenance).

## Security

This record *is* a security boundary; that is why it is filed PROPOSED. The two decisions most consequential for the owner to review are **D2** (key storage sets the zone ceiling, so a weak node is admitted rather than excluded) and **D7** (a separate enrollment key that VESPER itself cannot reach, at the cost of a recovery ceremony).

## Failure modes

Key loss on a node; storage-class degradation between attestations; revocation issued during partition; enrollment key loss; replayed enrollment certificate; two nodes claiming one `node_id`. Each is covered by `A-042`, with the revocation-during-partition case extending `A-034`.

## Rollback

Certificates and revocations are schema-versioned events under ADR-002 D4/D5, so an identity-format change is a read-time upcast, not a re-enrollment of the fabric.

## Acceptance tests

`A-042` (node enrollment admission, `Z2` bounds, re-attestation) — extended by this record with the revocation, demotion and recovery cases; `A-034` (revocation during partition); `A-044` (compromise indicators).

## Open items

| # | Item | Disposition |
|---|---|---|
| 1 | Whether the owner enrollment key is a hardware token or an offline file | Owner preference; both satisfy D7. Raised inside `OWNER-DECISION-006`. |
| 2 | Enrollment-key loss ceremony (rotation with no surviving signer) | Genuinely open. Bounded consequence — the fabric keeps running and cannot add nodes. Must be closed before R2, not before F0. |
| 3 | Whether re-attestation intervals are owner-tunable | Default **no**: an interval VESPER can extend is an interval it can extend to infinity. If tunable, the range belongs in `contracts/policy/tunables.toml` under `INV-TUNE-1`. |
