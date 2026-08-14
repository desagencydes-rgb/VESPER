# Waking the site-A node without a human — options, measured constraints first

**Status: DESIGN.** Written 2026-08-13. Figures marked MEASURED come from this machine today. Figures marked EXPECTED are arithmetic from vendor draw figures and are **not** measured — SPIKE-011 replaces them.

**The owner's requirement (2026-08-13):** *not* always-on — that is electricity spent for nothing. The machine should be **off, or as close to off as makes no difference, and come up when needed, with no human intervention.** Free or near-free. A hardware workaround is acceptable.

---

## 0. Why SPIKE-010 said BLOCKED — the precise reason

SPIKE-010 recorded that remote wake "needs a wired path the owner doesn't have yet." Measured today, that sentence resolves to something much more actionable than it sounded.

```
MEASURED 2026-08-13

Get-NetAdapter -Physical
  Ethernet 3   Realtek PCIe GbE Family Controller   Disconnected   0 bps
  Wi-Fi 8      802.11n USB Wireless LAN Card        Up             150 Mbps

powercfg /availablesleepstates
  Available    : Standby (S3), Hibernate, Fast Startup
  Not available: S0 Low Power Idle, S1, S2, Hybrid Sleep
```

Three consequences:

1. **The network is a USB Wi-Fi dongle.** Wake-on-Wireless-LAN is not achievable here in any practical sense: the USB bus is unpowered in S3 and S5, so the adapter is simply not alive to receive anything. This is a property of the hardware, not a setting.
2. **But the board has an onboard Realtek PCIe gigabit NIC, and it is merely unplugged.** PCIe NICs are powered from standby rails and Realtek GbE controllers support Wake-on-LAN from S3, and usually from S5. **The wake hardware already exists in this machine.** What is missing is a cable.
3. **S3 standby is available.** That matters more than it looks — see §2.

So "BLOCKED" was accurate but overstated the difficulty. The blocker is an Ethernet cable, not a capability gap.

---

## 1. The idea that dissolves the problem: S3 is not "on"

The owner's objection to always-on is electricity, and it is a correct objection about a machine that is *running*. It is not a correct objection about S3.

| State | EXPECTED draw | Wakeable remotely? |
|---|---|---|
| Running, idle desktop | ~60–70 W | n/a |
| **S3 standby** | **~3–5 W** | **yes — WoL over the PCIe NIC** |
| S5 soft-off | ~1–2 W | yes, if Fast Startup is off and the BIOS permits S5 WoL |
| Unplugged | 0 W | no |

EXPECTED monthly energy, at ~1.2 MAD/kWh:

| Regime | EXPECTED kWh/month | EXPECTED cost |
|---|---|---|
| Always running | ~47 | ~56 MAD |
| S3 most of the day, ~4 h/day active | ~11 | ~13 MAD |
| S5 most of the day, ~4 h/day active | ~9 | ~11 MAD |

**S3 costs roughly 2 MAD/month more than being fully off, and wakes in about three seconds.** The difference between S3 and S5 is not worth engineering around; the difference between either of them and always-running is real and is the owner's point.

> These are EXPECTED, from published idle figures for this class of part. They are the first thing SPIKE-011 should replace with a wall-meter reading, because the whole duty-cycle argument rests on them.

---

## 2. Options, cheapest first

### Option A — Ethernet cable + S3 + Wake-on-LAN  ·  cost: one cable  ·  **recommended**

Plug `Ethernet 3` into the router. Then:

- BIOS: enable **Wake on LAN / Power On by PCIe**, and disable **ErP / Deep Sleep** (ErP cuts the standby rail the NIC needs).
- Windows: NIC properties → **Wake on Magic Packet** enabled, and *uncheck* "Allow the computer to turn off this device to save power".
- Disable **Fast Startup** (`powercfg /hibernate off` does this — it is already in the hardening script).
- VESPER sleeps the machine to S3 on idle; any fabric member sends a magic packet to wake it.

Free apart from the cable, no moving parts, no extra device to fail, wake latency ~3 s.

**The one thing to verify before relying on it:** that this board actually holds the NIC powered in S3. Some consumer boards do not. That is a ten-minute test, not a spike — sleep the machine, send a magic packet from a phone, see if it comes up.

### Option B — the router is too far for a cable

Same as A, but bridge the gap. In rough order of preference:

- **Powerline adapter pair** (Ethernet over house mains). Works well when both ends share a circuit; degrades across phases.
- **An old router in client/bridge mode**, feeding the PC's Ethernet port. Often free if one is lying around.
- **A dedicated Wi-Fi-to-Ethernet bridge**, cheapest new option.

All three give the PCIe NIC a real link, which is the only thing Option A is missing.

### Option C — BIOS RTC alarm  ·  cost: nothing  ·  no cable needed

Most BIOSes offer **Wake on RTC / Resume by Alarm**: power on at a fixed time daily. Combined with VESPER shutting down when idle, this produces a duty cycle with **zero hardware and zero human intervention**.

The limitation is honest and load-bearing: **it is scheduled, not on-demand.** Between windows the node is unreachable. That is fine for batch and overnight work, and useless for "answer me now." It composes well with Option A rather than competing with it — RTC as the floor, WoL for on-demand.

### Option D — smart plug + "Restore on AC Power Loss = Power On"  ·  cost: ~80–150 MAD

Set the BIOS to power on when mains returns, then use a Wi-Fi smart plug to cut and restore power remotely. The machine boots. This works from a genuinely dead S5, needs no Ethernet, and is controllable from a phone anywhere.

Caveats, stated plainly: **it cannot shut down gracefully** — software must do that, and the plug is only for powering *on*. Pulling the plug on a running machine risks the filesystem, so the plug must never be toggled off while VESPER is up. It also adds a cheap network-connected device to the house, which is its own small attack surface.

### Option E — ESP32 / Pico W wired to the front-panel power header  ·  cost: ~50 MAD

A microcontroller across the `PWRBTN` pins, acting as a network-controlled power button. It is what Options A–D are all approximating, it works from S5, it needs no Ethernet, and it can also do a *forced* power-off if the machine hangs — which nothing else here can.

It requires opening the case and one soldered or dupont connection, and it is a device the owner then maintains. Listed because the owner explicitly invited a hardware workaround, not because it beats Option A on cost or simplicity.

---

## 3. Recommendation — SUPERSEDED 2026-08-13

> **Option A is closed.** The owner reports the router is too far and there is no network outlet in the room. The measured 90% signal at 1.3 ms said *close*, but signal passes through walls a cable cannot, so the reading was consistent with a distance that still defeats cabling. **Option E is now the recommendation** — see `REMOTE_POWER_BUILD.md` for the full design, parts list, wiring, and safety rules. Option C stays as the free backstop and should be enabled regardless.
>
> The original recommendation is kept below rather than deleted, because the reasoning for it was sound and only the premise changed.

**Option A, with Option C as a backstop.** The cable is the cheapest fix available, uses hardware already in the machine, and turns the SPIKE-010 blocker into a solved problem. Add the RTC alarm because it costs nothing and covers the case where the network itself is down.

Order of work:

1. Plug the Ethernet cable in. Confirm `Ethernet 3` goes `Up`.
2. Verify the S3 + magic-packet path end to end before anything depends on it.
3. Only then let VESPER shut down or sleep on idle. **Until step 2 passes, do not enable automatic shutdown** — the node would become unreachable until someone physically presses the button, and the owner will be in site B.
4. Measure real draw in S3 and running with a wall meter, and replace every EXPECTED figure above.

---

## 4. What this changes upstream

- `INFERENCE_ARCHITECTURE.md` §6 says the big power lever is dormancy rather than tuning. That still holds, but it was scoped to **GPU** dormancy while the machine runs. **Machine-level dormancy is a much bigger lever** — roughly 60 W against the few watts a power cap saves.
- SPIKE-011 was scoped to service-level dormancy on a running machine. It should also carry the wall-meter readings for running / S3 / S5, because the duty-cycle decision depends on them and nothing else measures them.
- The `always_on` question in `capability_profiles.toml` is unaffected. This node is `on_demand` either way; a working wake path changes how *quickly* it can be summoned, not its class. The fabric still needs an always-on member to send the magic packet — and that member can be trivial (a phone, a router script, a small VPS), which is the part the earlier phrasing failed to make clear.
