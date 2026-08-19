# SPIKE-003 (partial) — the alarm acknowledgement channel, per platform

**Recorded 2026-08-18. Desk research plus one hardware measurement.**

## What this is, and what it is not

`SPIKE-003`'s own question is the kernel/OS access envelope across nine
capabilities and four platforms, and its status stays **`NOT_STARTED`**. This
record answers only the **promoted sub-question** that `PLAN_2026-08-17`
pulled into week 1 because a gate came to depend on it:

> Can an application capture a **hardware button press** while the device is
> **locked** — no speech, no screen, no unlock — so it can serve as `41.3`'s
> acknowledgement channel?

Nothing here advances `SPIKE-003` toward its own pass criteria. The nine-cell
matrix is untouched.

## The honesty rule this record is written under

`SPIKE-003` §2: *"Validate each available cell with a minimal probe that
actually reads the value. **A documentation citation is not a measurement** —
entitlements are frequently documented and unobtainable."*

So every row below carries how it is known. **One row is measured. The rest are
read.** A read row is a lead, and it is not evidence.

| Platform | Answer | Mechanism | How known |
|---|---|---|---|
| **Linux** (node 2, Kali) | **YES** | `EV_KEY` and `EV_SW` read straight off `/dev/input/event*`. Kernel level — the session lock is not in the path at all. Needs the `input` group | **MEASURED.** `tools/ops/alarm_node_linux.py` acknowledged the 2026-08-18 09:00 firing via `evdev_event1_lid_opened` at 09:00:10 |
| **iOS 26+** | **YES — but not by reading the button** | **AlarmKit.** Alarms ring on the Lock Screen, StandBy and Dynamic Island even when the device is silenced or the screen is off, and **a volume-button press dismisses the alarm** | **READ.** Apple DTS engineer, developer forum 810865: *"the buttons turn off the alarm and the swipe snoozes"* |
| **iOS, without AlarmKit** | **NO, not reliably** | KVO on `AVAudioSession.outputVolume` detects volume changes in the foreground. Backgrounded, it needs a background execution mode and must fit one of the prescribed use cases | **READ** |
| **Android** | **YES, in practice** | `MediaSession` plus a foreground service receives media/volume key events with the screen off; on API 26+ the system routes the event to the last session that played audio locally. Every stock alarm app does this — Google Clock ships a *Volume buttons → snooze/dismiss* setting | **READ** |
| **Windows, macOS** | not investigated | — | neither is a candidate alarm rung today |

## The finding that changes the design

**Do not build a hardware-button reader on iOS.** `SPIKE-003` §1 already states
the doctrine — *"a supported API that delivers the purpose is a better outcome
than a privileged hack that delivers the literal words"* — and AlarmKit is
exactly that API. It delivers `41.3`'s requirement as a **system behaviour**:
no speech, no screen, no unlock, and it survives silent mode.

## The cost, and it is the risk §2 names

AlarmKit needs:

1. `NSAlarmKitUsageDescription` in `Info.plist`, and
2. **an entitlement that must be requested from Apple and is reviewed by Apple.**

That second item is precisely the failure mode `SPIKE-003` §2 warns about — a
documented entitlement that may be unobtainable. **It is validated by holding
it, not by citing it.** Until an entitlement is actually granted against a real
Apple developer account, the iPhone rung is `UNKNOWN`, and `INV-HW-2` makes
`UNKNOWN` mean `UNAVAILABLE`.

There is a second, independent gate: an iOS build has to reach the handset at
all. A free account sideloads with a 7-day expiry; a paid account extends that
to a year. Neither is decided.

## Consequence for the alarm ladder

`A-012` needs escalation **across** a device ladder, and node 2 is one device.
Today's ladder is depth 1 and every firing is `gate_evidence = false`.

- **Android is the cheapest second rung.** No entitlement, no review, and the
  mechanism is what every alarm app on the platform already uses.
- **The iPhone is the strongest rung and the slowest** — the acknowledgement is
  a system behaviour rather than something to build, but it is gated behind an
  Apple review with no committed timeline.

Neither is measured. Both are leads.

## What would turn a read row into a measured one

A minimal probe per platform, run on the actual handset: schedule an alarm,
lock the device, let it ring, press the hardware button, and record whether the
process observed the event — the same shape as the Linux rung, which is
measured precisely because it did that.
