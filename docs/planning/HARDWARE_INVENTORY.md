# VESPER — Hardware inventory (planning, EXPECTED not measured)

**Status: PLANNING.** This file is a working note, deliberately kept OUT of the normative set. It records the real devices as they are *declared and observed*, so there is somewhere to put facts as they arrive. It is **not** an input to any decision function.

Two hard rules keep it honest:

1. **Nothing here may be copied into `contracts/policy/capability_profiles.toml`.** That file's fields are `UNKNOWN` until `SPIKE-001` *measures* them under load, and `CI-034` fails a build that fills them from a spec sheet. Spec-sheet numbers and measured-sustained numbers are different numbers; this file holds the first kind, the contract holds the second, and they never cross.
2. **Product names are allowed here** because this is planning prose, not routing, resource or policy logic. In the specifications the same devices appear only by *profile shape* (`availability_class`, `trust_zone`, `key_storage_class`) — never by brand — and `CI-007` enforces that. Substituting hardware must be a profile change there, never a migration.

Last updated: 2026-08-12.

---

## The fabric today

| Device | Profile shape | Availability | Role | State |
|---|---|---|---|---|
| **Strong desktop** (site A) | high compute, discrete GPU, mains-powered | `on_demand` after the owner relocates (available now) | `compute_candidate`; `wakeable` **pending** SPIKE-010; **never** continuity-critical | **Live.** Specs below |
| **Asus laptop** (Kali Linux) | portable compute + control candidate | `usually_on` while in use; travels to site B | primary `compute_candidate` + `control_candidate` | Live; specs TBD when powered |
| **iPhone 14 Pro** | foreground-only endpoint, hardware capture indicator | `foreground_only` | presence endpoint; **survival floor** | Live; travels |
| **Samsung J3** | low-memory endpoint, file-based key storage | `on_demand` / `foreground_only` | weak endpoint, holds no state → likely `Z2` | Live; travels |
| **Broken desktop** | — | **UNAVAILABLE** | none | **Repair project.** Pre-POST power fault |
| **MacBook** | — | not acquired | — | **Excluded.** Joins by measurement when purchased — no placeholder |

**The owner relocates to site B; everything portable travels; the strong desktop stays in site A.** That single fact is why the strong desktop is `on_demand`, not `always_on`: it is a powerful machine that will be mostly off and occasionally run, not a 24/7 host. Marking it `always_on` would let the system design continuity-critical work onto a machine that is asleep in another city.

---

## Strong desktop — observed 2026-08-12 (read-only, from the machine itself)

| Component | Value | Note |
|---|---|---|
| CPU | AMD Ryzen 5 5500 | 6 cores / 12 threads, 3.6 GHz base |
| RAM | 16 GB | 2 × 8 GB DDR4-2133 (running at 2133; faster is possible with XMP) |
| GPU | AMD Radeon RX 6650 XT | **8 GB VRAM** — Windows reports "4 GB", the classic 32-bit `AdapterRAM` cap; the card ships with 8 |
| Storage | 512 GB SSD (~477 GB usable) | TEAM TM8FPD512G |
| Board | MSI B550 (MS-7C96) | PCIe 4.0, Ryzen 5000 support |
| OS | Windows 11 Pro (10.0.26200) | |
| Sleep states | S3 + Hibernate available; S0/S1/S2 not | WoL-from-S3 is the reliable path |
| Wake-on-LAN | **Onboard Realtek GbE supports it and is ARMED** | but Ethernet is **unplugged** — currently on a weak USB Wi-Fi dongle (802.11n, 72 Mbps) that cannot WoL |

**Expected role:** the muscle VESPER borrows. Strongest node by a wide margin; the 8 GB GPU runs small quantized models locally, the 12 threads carry background work. Borrowed when awake, never leaned on.

**Remote wake is BLOCKED on a wired path (2026-08-12).** Wake-on-LAN cannot ride the current USB Wi-Fi dongle — cheap dongles do not support wake-on-wireless, and no OS setting adds a capability the hardware lacks. The NIC that *is* WoL-capable (onboard Realtek GbE) is unplugged. Until a wired path exists, `wakeable = BLOCKED` and **the desktop is usable as a node only while it is already powered on** (owner present, or a family member turned it on). The two physical options, cheapest first:
1. **An Ethernet cable** if the desktop is near the router — the single cheapest fix in the project.
2. **Powerline adapters** if a cable cannot reach — a wired-equivalent link over house wiring, one-time cost.
Then, if wake-from-full-shutdown is wanted, **check the BIOS wake-from-S5 setting** (S3-sleep wake already looks feasible). None of this blocks using the desktop while it is on.

**Measured performance (sustained tokens/sec under concurrent load, memory headroom against the real working set, etc.) is NOT here** — that is `SPIKE-001`, and it needs a model runner installed. The table above is what the machine *is*, not what it *sustains*.

---

## The broken desktop

Symptom (owner-reported): press power → fans and lights kick for **under one second** → dead; no video; power-cycling and reseating power do not help. This is a **pre-POST power failure** — the machine never reaches boot. Most likely, in order: **PSU protection tripping** (cheapest, most common — test with a known-good PSU), then a **motherboard short/fault**, then a dead component pulling a rail down.

**Consequence for VESPER:** none yet. Wake-on-LAN cannot wake a machine that cannot POST, so this is a **repair task, not a node**, and it is excluded from the fabric until it boots and its WoL path is verified.

---

## New scope this inventory surfaced

The owner's setup (compute in one city, everything else in another) needs two things the corpus does **not** currently have, now tracked as spikes:

- **`SPIKE-009` — cross-site connectivity.** The whole design so far assumes nodes share a LAN. Reaching site A from site B needs a secure, zero-cost, low-maintenance fabric across two home networks.
- **`SPIKE-010` — remote wake.** Whether VESPER can power the desktop on across the internet — gated by the "nothing always-on stays in site A" problem and the router's WoL support.

**Both may require a new owner-authored SR for cross-site operation.** Adding an SR is COC-locked and owner-reserved — **flagged here for the owner, not invented.**
