# A network power button for the site-A node — DIY build

**Status: DESIGN, not built.** Written 2026-08-13. Supersedes Option A of `WAKE_OPTIONS.md` as the chosen path.

**Why this and not the cable.** The owner reports the router is too far and there is no network outlet in the room (2026-08-13). Measured signal was 90% at 1.3 ms, which said *close* — but signal strength travels through walls that a cable cannot, so the measurement was consistent with a distance a cable still cannot cross. Cable path closed.

**What the owner asked for:** a small board inside the PC, wired to whatever controls its power, triggering on and off remotely. Safe, ideally free, DIY.

**Short answer: yes.** This is a standard build, it is the most capable of all the options, and it is the only one that can also force-off a hung machine. It is not free — **EXPECTED ~50–80 MAD in parts** — but it is the cheapest thing that actually solves the problem.

---

## 0. Read this first — there is a free path, and it is already switched on

The owner asked for zero cost, DIY from what is already in the house. Measured on this machine 2026-08-13, before designing anything:

```
powercfg /devicequery wake_programmable
    HID-compliant mouse (001)
    HID Keyboard Device
    Realtek PCIe GbE Family Controller          <- armed, but no cable
    HID-compliant system controller
    HID-compliant consumer control device

powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE
    (Allow wake timers)  Current AC Power Setting Index: 0x00000001   <- ENABLED
```

Three facts fall out:

1. **The USB Wi-Fi dongle is absent from the wake-programmable list.** It cannot wake this machine under any configuration. That closes Wake-on-Wireless-LAN as a measured fact rather than an assumption.
2. **The Realtek NIC is already armed to wake.** The wake capability was never missing — only the cable.
3. **`Allow wake timers` is ENABLED right now.** Windows can bring this machine out of **S3** on a schedule, with **no hardware, no BIOS visit, and no purchase.**

### The zero-cost design

```
VESPER idle  ->  machine sleeps to S3 (EXPECTED ~3-5 W)
                      |
      Task Scheduler wake timer fires every N minutes
                      |
              machine wakes (~3 s)
                      |
         is there work?  --- no ---> back to S3
                      |
                     yes
                      |
              stay up and run
```

A scheduled task with **"Wake the computer to run this task"** arms an RTC timer. This is ordinary Windows, available today, and it needs nothing the owner does not already have.

**Latency is the honest trade.** This is *polled*, not on-demand: worst case is one poll interval. But the interval is a dial, not a fixed cost.

| Poll interval | Worst-case wait | EXPECTED average draw |
|---|---|---|
| 5 min | 5 min | ~8 W |
| 15 min | 15 min | ~5 W |
| 30 min | 30 min | ~4 W |

(Assuming ~30 s awake per empty poll at ~65 W, plus S3 baseline. EXPECTED — SPIKE-011's wall meter replaces these.)

Even the aggressive 5-minute setting is roughly **8× cheaper than leaving the machine running**, and costs nothing to build.

**What "is there work?" can be**, all free: a file dropped in a synced folder, an unread message in a queue the node polls, a flag on any endpoint VESPER already talks to. The node reaches *out* on wake, so nothing needs to reach *in* — which also means no inbound port, no exposure, and no new attack surface. That is a real security advantage over every paid option below.

### What this does not do

- **It cannot wake from S5 (full off).** Windows wake timers work from S3 only. Waking from a true power-off needs the BIOS `Resume by Alarm` setting — also free, but a BIOS visit.
- **It cannot recover a hung machine.** If Windows locks up, nothing here helps.
- **It is not true on-demand.** If the owner needs sub-minute response from site B, only §1 delivers that.

**Recommendation: build §0 first, because it is free and available today.** Treat §1 as an upgrade to buy only if polling latency turns out to be a real problem in practice — which it may well not.

### Before anything is built, one test

Sleep the machine, let a wake timer fire, confirm it comes back. Free, ten minutes, and it either validates the whole design or kills it early. **Not run yet** — a SPIKE-001 measurement is in progress and sleeping the machine would destroy it.

---

## 1. The paid option — a network power button

Every ATX motherboard exposes a **front-panel `PWRBTN` header**: two pins that the case's power button momentarily shorts together. The board does not care *what* shorts them. A microcontroller wired in parallel with the physical button is, to the motherboard, indistinguishable from a finger.

```
   [ Wi-Fi microcontroller ]---(optocoupler)---> PWRBTN pins on the motherboard
             |                                        ^
       powered from 5V standby                        |
       (alive while the PC is off)          physical case button stays
                                            wired here too, in parallel
```

Press durations are an ACPI convention, not a custom protocol:

| Assert for | Machine is off | Machine is running |
|---|---|---|
| ~250 ms | powers on | **graceful** shutdown request to Windows |
| ~6 s | nothing | hard power-cut — last resort only |

So one output pin gives on, graceful off, and force-off.

---

## 2. Parts

| Part | Purpose | EXPECTED cost |
|---|---|---|
| ESP32 dev board (or Pi Pico W) | Wi-Fi + GPIO | 30–60 MAD |
| PC817 optocoupler | **isolation** — see §4 | ~5 MAD |
| 220 Ω resistor | limits opto LED current | ~1 MAD |
| 1 kΩ resistor | for the optional state-sense input | ~1 MAD |
| Dupont jumper wires | connections, no soldering to the board needed | ~10 MAD |

**EXPECTED total ~50–80 MAD.** These are estimates, not quotes.

A second optocoupler (~5 MAD) is worth buying for §5.

---

## 3. Wiring

**Trigger path — this is the whole build:**

```
ESP32 GPIO ──[220 Ω]── PC817 pin 1 (anode)
ESP32 GND ───────────── PC817 pin 2 (cathode)

PC817 pin 4 (collector) ── motherboard PWRBTN pin 1  (the +3.3V, pulled-up pin)
PC817 pin 3 (emitter) ──── motherboard PWRBTN pin 2  (ground)
```

The case's own power button stays connected to those same two pins. Both work; neither knows about the other.

**Power for the board.** Use an **internal USB 2.0 header**, not the PSU. Nearly every board has a spare one, it is 5 V and already fused, and it requires no cutting or splicing. In BIOS, **disable ErP / Deep Sleep** so USB keeps its standby rail alive in S5 — without that the board dies when the PC shuts down and cannot wake anything.

> The alternative — tapping the purple 5VSB wire on the 24-pin ATX connector — also works and is what many guides show. **Do not do it.** It means cutting or piercing a live PSU cable for no gain over a USB header that is already there.

---

## 4. Safety — the part that matters

The owner asked for this to be safe. Four rules, in order of importance:

1. **Never wire a GPIO directly to `PWRBTN`.** The optocoupler is not optional. It passes the signal as light, so the two circuits share no electrical connection. If the microcontroller dies, shorts, or is miswired, the motherboard sees nothing. Direct wiring risks the board.
2. **Unplug the PC from the mains before opening the case**, then hold the power button ~5 s to drain residual charge. Touch bare metal on the chassis before touching components.
3. **The output must never latch on.** A GPIO stuck high holds the power button down forever, which force-kills the machine and keeps it dead. Firmware asserts, then de-asserts on a timer, with a watchdog that forces the pin low after 7 s no matter what. An optocoupler also fails *open*, which is the safe direction.
4. **Keep the physical button wired.** Parallel, not replacement. If the whole thing fails, someone in the house can still press the button.

Residual risks, stated plainly: opening the case carries static-discharge risk; a miswired trigger could power-cycle the machine unexpectedly; and this adds a device that must not fail closed. None is large, all are manageable, and the optocoupler removes the one that could damage hardware.

---

## 5. Worth adding: state sense

Without it, a press is fire-and-forget — you cannot tell whether the machine came up. The **`PLED` (power LED) header** already carries exactly that signal.

```
PLED+ ──[1 kΩ]── opto #2 pin 1 (anode)
PLED- ─────────── opto #2 pin 2 (cathode)
opto #2 output ── ESP32 GPIO (with internal pull-up)
```

Now the board reports **on / off** as a fact rather than an assumption, and the firmware can refuse to send a 250 ms press when the machine is already running — which would otherwise *shut it down* instead of waking it. That single guard is why this is worth the extra 5 MAD.

---

## 6. Firmware and security

It is a network-reachable device whose only job is to power-cycle the machine. Treat it as such:

- **LAN only.** No cloud service, no port forwarding, no vendor account.
- **Authenticated.** A shared secret on every command; unauthenticated requests dropped silently. `SPIKE-010` §5 already forbids an unauthenticated wake path on the fabric, and this is that path.
- **Three commands, nothing else:** `status`, `press` (250 ms), `force_off` (6 s, explicitly separate so it cannot be reached by accident).
- **Refuse contradictory commands** using the §5 state sense.
- No firmware auto-update from the internet.

This is the same posture already recorded for `llama-server`: the default is a decision, not an accident.

---

## 7. Free alternative, and why it is not enough on its own

**BIOS `Wake on RTC` / `Resume by Alarm` costs nothing and needs no hardware.** The board powers itself on at a set time daily; VESPER shuts down when idle. That is a working duty cycle for zero dirhams.

Its limit is real: **scheduled, not on-demand.** Between windows the node is unreachable, and it cannot recover a machine that hung rather than shut down.

**Do both.** Turn the RTC alarm on regardless — it is free, it takes two minutes in BIOS, and it is a fallback if the microcontroller ever fails. The network button adds on-demand wake and force-off on top.

---

## 8. Considered and rejected

- **Smart plug + "Restore on AC Power Loss".** Costs more (EXPECTED 80–150 MAD), requires no case opening — genuinely safer to install. Rejected as the primary because it cannot request a *graceful* shutdown, only cut mains, and because it depends on a vendor's cloud app by default. Reasonable fallback if opening the case is unwelcome.
- **Powerline adapters.** EXPECTED 250–400 MAD, more than this build, and they only restore the cable path — still needing WoL configuration on top.
- **Wake-on-Wireless-LAN.** Not achievable. The adapter is a **USB** dongle and the USB bus is unpowered in S3/S5, so it is not alive to receive anything. Hardware fact, not a setting.

---

## 9. Before buying anything — check these

1. Does the motherboard have a **spare internal USB 2.0 header**? (Look for a 9-pin block labelled `USB` / `F_USB`.)
2. Does BIOS have **ErP / Deep Sleep** as a disable-able setting? Needed for USB standby power.
3. Does BIOS have **Resume by Alarm / Wake on RTC**? Free win either way.
4. Are the `PWRBTN` and `PLED` headers reachable with the case assembled?

All four are answerable in one look inside plus one BIOS visit. Nothing should be ordered before that.

---

## 10. What this changes upstream

- `WAKE_OPTIONS.md` recommended Option A (cable). **Superseded** — the owner has ruled the cable out. Option E, previously listed as "not because it beats Option A on cost", is now the recommendation.
- The sequencing constraint from `WAKE_OPTIONS.md` §3 still holds and is unchanged: **automatic shutdown must not be enabled until the wake path is verified end to end.** Until then, an idle shutdown makes the node unreachable until someone physically presses the button, with the owner in site B.
- `SPIKE-010`'s BLOCKED wake finding is not resolved by this document. It is resolved when the thing is built, wired and tested.
