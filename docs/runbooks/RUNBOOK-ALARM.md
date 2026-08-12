# RUNBOOK — Alarm and wake escalation

**RUNBOOK-ID:** RB-ALARM-001 · **Severity:** high · **Owner:** Project Owner
**Required deliverable of** REM-012 §3. Referenced by `A-041.7`.

> The source is explicit: *"I'm a sleeper so he must not stop, even if he should play loud noises and music and speak at the same time from all devices."* This runbook exists because a system built to that instruction needs a **documented way to stop it** that works at 03:00, half-awake, in the dark.

---

## Stopping an alarm right now

**Any one of these ends it.** They are ordered by how easy they are while barely conscious.

| # | Action | Works when |
|---|---|---|
| 1 | **Press the physical acknowledgement control** | Always. Requires no speech, no screen, no unlock. |
| 2 | **Unlock your phone** | Phone reachable and charged |
| 3 | Say the acknowledgement phrase | ASR is up and can hear you over the alarm |
| 4 | Interact with any enrolled display | That surface is alive |
| 5 | **Wait for the duration cap** | Always — escalation self-terminates. It does not run forever. |

**At least one channel is always physical and ASR-independent** (`INV-ALARM-2`). That is deliberate: an alarm loud enough to wake a heavy sleeper is loud enough to defeat its own microphone, and an acknowledgement path that requires speaking over it is not a path.

## It is firing on more than one device

**Expected, and correct.** Alarms replicate to every capable node. Where connectivity permits, lease-based election picks a single firer. **On a network partition, every capable node fires.**

> This is the one place in VESPER where availability is deliberately chosen over consistency. A duplicate alarm is an annoyance; a missed one violates SR-043. **Never fire-never.**

Acknowledging on **any** device stops **all** of them once they can talk to each other again. Until then, acknowledge on each — the acknowledgement path is duplicate-tolerant by design.

## It fired at the wrong time

Check what VESPER says about its own clock before assuming the schedule is wrong.

Under `clock_suspect` (REM-001 §4.1 — clock regression, or no authenticated time source), alarms fire on the **last known good schedule** and VESPER **announces the uncertainty**. It does not skip. A wrong-but-announced alarm is recoverable; a silently skipped one is the failure the requirement exists to prevent.

If the time source is genuinely wrong, fix the time source — not the alarm.

## It did not fire

1. **Check for a missed-window report.** An elapsed schedule window is reported (`autonomy.window_missed`), never silently skipped. If the report is there, the alarm knew and could not act — check node availability at that time.
2. **Check the interlock.** `STOP_ALL` halts alarm actuation; `STOP_AUTONOMY` does **not**. If someone press-and-held ≥ 5 s, alarms are off until a human re-arms. See `RUNBOOK-EMERGENCY-STOP.md`.
3. **Check that a capable node was reachable.** With no `survival_capable` node online, there is nothing to fire from — VESPER reports `placement.survival_impossible` rather than failing silently.
4. **If none of the above,** this is a defect against `A-041` and the event log will reconstruct it: `trigger → authority → command → outbox → result`.

## The escalation ceiling

Escalation has a **hard duration cap with automatic stop**, a maximum escalation level, and every step is logged for your review. It will not escalate forever, and it will not exceed the configured ceiling even if unacknowledged.

**Physical kill, if everything else fails:** power down the loudest node. Recorded here rather than left as folklore, because the alternative is inventing it at 03:00.

> Note the asymmetry with the emergency stop: the interlock's default (`STOP_AUTONOMY`, a single press) **preserves alarms** precisely so that stopping VESPER's autonomy does not silently disable your wake-up. Halting alarms requires the deliberate press-and-hold. That was a design decision, not an oversight.

## What overrides what

Alarm and safety sit at the top of the priority lattice (REM-012 §3):

```
alarm/safety  >  active user task  >  ambience  >  proactive
```

An alarm **overrides** device quiet hours, the ambience policy, resource yielding, and the interruption budget. If a quiet-hours setting is suppressing your alarm, that is a bug, not a configuration choice — `A-041.5` tests exactly this.

## After an alarm

Every escalation step is logged and reviewable: which devices fired, at what level, how long, and how it was acknowledged. If the escalation felt disproportionate, that log is what you tune against — the ladder specifics (volumes, intervals, device order) are configuration; the ceiling, the ownership rule and the ack channels are architectural.

## Verification

`A-041`, seven cases — including firing with the owning node removed, partition behaviour on both sides, **each acknowledgement channel exercised independently with ASR fully disabled**, the duration cap terminating escalation, override of an active quiet-hours policy, and `clock_suspect` firing on last-known-good with announced uncertainty.

**Test this runbook at Phase 8**, on the real hardware, at night, with the owner performing the steps unaided and genuinely asleep beforehand. A wake-up procedure validated while awake has not been validated.
