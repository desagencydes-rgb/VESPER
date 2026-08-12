# SPIKE-010 — Remote wake feasibility

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Can VESPER bring an off or sleeping compute node to a usable state on demand — over LAN, then over WAN — and return it to sleep, with **no person present**? |
| **Time box** | 3 working days |
| **Owner** | Device/Network Engineer |
| **Depends on** | SPIKE-009 (supplies the cross-site path for the WAN half) |
| **Requires hardware** | Yes |
| **Raised by** | Owner, 2026-08-12 |
| **Blocks** | The "VESPER turns it on" capability · the `wakeable` attribute on the site-A desktop profile |

> **Partial evidence is already in hand, and it points both ways.** Read on the strong site-A desktop (2026-08-12, read-only): its onboard `Realtek PCIe GbE Family Controller` supports Wake-on-LAN and is already ARMED (`powercfg /devicequery wake_armed`), and S3 sleep plus hibernate are available. Those are the hard parts, and they exist. The blockers are mundane and real: the Ethernet is **unplugged** (the machine is on a USB Wi-Fi dongle that cannot do wake-on-wireless), WoL-from-full-shutdown (S5) is a **BIOS setting not yet verified**, and — the one that does not go away — after the owner relocates, the site-A LAN has **no always-on device** to deliver a wake initiated from another city.

> **Scope note.** The SEPARATE broken desktop (fans twitch for under a second, no POST — a pre-POST power fault, most likely PSU or motherboard) is **out of scope**. A machine that cannot POST cannot be woken; it is a repair task, not a node, and remote wake does not apply to it until it is fixed.

---

## 1. The LAN half

```
1. Connect the target desktop to the router by ETHERNET (WoL does not ride the USB Wi-Fi dongle).
2. Confirm/enable, at the OS: WakeOnMagicPacket on the wired NIC. Optionally DISARM keyboard and
   mouse as wake sources, so only the NIC wakes it (a headless node should not wake on a bump).
3. From a SECOND node on the same LAN (the laptop), with the target in S3:
   send the magic packet -> assert the target wakes and becomes reachable within a stated budget.
4. Repeat from FULL SHUTDOWN (S5). If it fails, the BIOS lacks wake-from-S5 (or ErP is on):
   record it as a BIOS-configuration dependency, not a capability failure.
5. Assert VESPER can then return the target to sleep on command.
```

The test must be driven from a **second** machine: the node cannot both be asleep and be the thing that sends its own wake packet, and the controller cannot be the machine it is putting to sleep.

## 2. The WAN half (depends on SPIKE-009)

```
Through the SPIKE-009 fabric, initiate the same wake from a node in a DIFFERENT city.
Delivery requires ONE of:
  (a) the site-A router forwards the magic packet from the fabric to the LAN broadcast, OR
  (b) an always-on site-A-side agent, reachable over the fabric, emits the packet locally.
Record which path exists on the owner's real router, and its cost.
```

## 3. Pass criteria

| # | Criterion |
|---|---|
| 1 | The target wakes from S3 via a LAN magic packet and is reachable within budget |
| 2 | Wake-from-S5 either works, or its BIOS dependency is recorded precisely |
| 3 | VESPER returns the target to sleep on command |
| 4 | A WAN wake succeeds through the SPIKE-009 fabric via (a) or (b) |
| 5 | The wake source is authenticated — an unauthenticated broadcast cannot boot the node from outside |

## 4. On fail

If there is no always-on presence on the site-A network **and** the router cannot forward a wake packet, remote wake over WAN is **infeasible** and is recorded as such. The node's `availability_class` stays `on_demand` with wake dependent on a **human** — a family member powers it on, and VESPER takes over afterward. Nothing continuity-critical is designed onto it regardless (`INV-TRUST-2`).

**Not permitted:** reporting a LAN-only success as remote wake; marking the node `always_on`; assuming a person will be present to press the button; or leaving the wake path unauthenticated so anything on the fabric can boot the machine.

## 5. Deliverables

1. LAN wake result from S3 and from S5, with the budget met or the BIOS dependency named.
2. The sleep-on-command result.
3. The WAN wake result, naming which delivery path the owner's router actually supports and its cost.
4. The wake-source authentication finding.
5. A recommendation on whether `wakeable` can be set true for the site-A desktop, or whether it stays human-gated — and, if a small always-on site-A device is the answer, what the cheapest honest option is.
