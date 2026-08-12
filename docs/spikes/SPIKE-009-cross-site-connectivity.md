# SPIKE-009 — Cross-site connectivity fabric

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Can nodes on **different physical networks** reach each other securely, at zero recurring cost, low-maintenance, through home-grade NAT on both ends — and does the existing design silently assume they share a LAN? |
| **Time box** | 5 working days |
| **Owner** | Device/Network Engineer · Security Engineer |
| **Requires hardware** | Yes — two nodes on two genuinely separate internet connections |
| **Raised by** | Owner, 2026-08-12 |
| **Blocks** | The site-A desktop's use as a remote node · any cross-site placement · SPIKE-010's WAN wake path |

> **This spike surfaced a hidden assumption, which is its real value.** Every existing artifact quietly assumes the nodes share a network: SPIKE-001 §3.4 measures *LAN* round-trip, and REM-002 promotes leases on *"reachable enrolled nodes"* without ever defining reach across the internet. A roaming laptop in site B and a compute desktop in site A are not on the same LAN. Nothing in the corpus claims cross-site works — so this is not a defect, it is a **missing requirement**, and it is cheaper to confront now than during F0.

---

## 1. The constraint the owner set

- **Primary: self-run WireGuard.** No third party, minimal update surface, no account. The owner explicitly declined a solution that "updates constantly."
- **Optional fallback: a mesh provider** (Tailscale-style), selected only when the primary path is down, via **a live endpoint resolver** that discovers the currently-working link and uses it.
- **Zero recurring cost.** Not "cheap" — zero.

The honest tension, stated before measuring: when **both** ends sit behind home-grade NAT, a pure peer-to-peer WireGuard tunnel needs *one* reachable endpoint to rendezvous. You can have any two of {zero cost, zero third-party, zero manual NAT work} — rarely all three. This spike measures which two are actually achievable on the owner's real connections.

## 2. Protocol

### 2.1 Reachability across NAT

```
Node A on network 1, Node B on network 2 (genuinely separate ISPs, not two SSIDs on one router).
1. Stand up a self-run WireGuard tunnel A<->B.
2. Record: does it connect at all without a public relay? (NAT type on each side: full-cone,
   restricted, symmetric — symmetric on either side usually defeats hole-punching.)
3. If it needs a rendezvous, record the MINIMUM: a DDNS name + one forwarded port on one side,
   or a relay endpoint, and that endpoint's real recurring cost.
```

### 2.2 Survival of address change

```
Force each side's public address to change (reconnect the ISP link, toggle mobile data).
Assert: the tunnel re-establishes automatically within a stated budget, with NO manual step.
A fabric that needs a human to repair the link every time the ISP renews a lease is not a fabric.
```

### 2.3 Identity binding (ADR-007)

```
Assert: the channel authenticates to the peer's CRYPTOGRAPHIC NODE IDENTITY, not to its IP.
An IP is a location, not an identity. If the link trusts whoever answers at an address, a
hijacked address is a hijacked node.
```

### 2.4 The fallback resolver

```
Kill the primary path. Assert: the resolver detects the loss, selects the fallback mesh,
publishes the new reachable endpoint, and traffic resumes — without the primary's failure
being mistaken for the node being offline.
```

### 2.5 Trust does not ride in on reachability

```
Assert, on paper and in the link's authorization: the transport is UNTRUSTED PLUMBING.
Making a node reachable does not raise its trust zone. ADR-007 identity and the Z0-Z3 zones
still gate what a reached node may do. A reached Z2 node is still Z2.
```

## 3. Pass criteria

| # | Criterion |
|---|---|
| 1 | A→B channel established across two separate ISPs, authenticated to node identity |
| 2 | It survives an address change on either side automatically, within budget |
| 3 | The link binds to ADR-007 identity, never to an IP |
| 4 | Zero recurring cost on the primary path, or the exact minimum cost named if not |
| 5 | The fallback resolver switches paths without reporting the node as offline |
| 6 | Reachability provably grants no authority the node did not already hold |

## 4. On fail

If self-run WireGuard cannot traverse both home NATs without a public relay, the deliverable is a **limitation record** naming the minimum infrastructure the fabric actually needs and its real cost, plus the fallback-mesh option evaluated on the same six criteria. **Cross-site operation stays R&D, and the LAN-only assumption is made EXPLICIT** in the affected specs (REM-002's reachability clause, SPIKE-001 §3.4) rather than left implicit.

**Not permitted:** hardcoding a node's IP anywhere; assuming a static public address the owner does not have; treating the mesh provider as trusted rather than as transport; or depending on a third party while still claiming "zero maintenance."

## 5. Deliverables

1. The NAT-type finding for each of the owner's real connections.
2. Connection result for pure self-run WireGuard, with the minimum rendezvous named if one is required.
3. Reconnect-after-address-change measurement.
4. The resolver's path-switch behaviour, including the false-offline test.
5. A one-page recommendation: primary transport, fallback transport, and whether a new owner-authored SR is needed for cross-site operation (flagged for the owner — **not** created here).
