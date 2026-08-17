"""Alarm actuation: the ladder, the cap, and the rule that an unactuable rung is not a rung.

The alarm is the one place in VESPER where availability is chosen over
consistency (`trg_alarm_fire`'s predicate_note), where the interlock deliberately
does NOT halt (`interlock.py`), and where the interruption budget is bypassed
rather than merely widened (`interruption.py`). All three of those already ship.
What did not exist until now is the thing that makes a noise.

THE RULE THIS MODULE EXISTS FOR, stated first because it is the one that is easy
to get wrong and expensive to get wrong:

    A DEVICE THAT IS REACHABLE IS NOT A RUNG.

A rung counts only when VESPER can (a) reach the device, (b) actually change the
settings that decide whether a sound is audible -- silent mode, volume, do-not-
disturb, airplane, low-power sleep -- and (c) OBSERVE that the sound happened.
An owner's phone sitting on the nightstand in silent mode with the volume at zero
is a device the naive implementation counts, escalates to, and hears nothing
from. It reports a four-rung ladder and delivers none.

This is `capability_profiles.toml`'s doctrine applied to the alarm: UNMEASURED IS
TREATED AS UNAVAILABLE, NOT AS AVAILABLE. And condition (c) is `SPEC-30`'s
prohibition applied here -- `SM-ENDPOINT-EPISODE` has no edge from `ACTUATED` to
`VERIFIED`, because the actuator's report is never the observation. A driver
returning "I set the volume to maximum" is a self-report; something has to hear
it.

NOT GATE EVIDENCE. A-012 requires escalation ACROSS A DEVICE LADDER. A single
node is a one-rung ladder and cannot satisfy it, whatever this module does
correctly. Runs produced here are prototype evidence and are recorded as
`gate_evidence = false`. A-041's seven cases -- partition, duplicate-tolerant
acknowledgement, clock_suspect, the documented physical kill -- are untouched by
anything in this file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

# INV-ALARM-2: "escalation has a hard duration cap". trg_alarm_fire fixes it at
# 900 s and names it in stop_conditions. It is imported from that decision, not
# re-chosen here -- a second copy of a number is a second thing to drift.
HARD_CAP_S = 900

# The three-state readiness result. Deliberately not a boolean: "we could not
# check" and "we checked and it is silent" must not collapse into one value,
# because the corpus's own doctrine is that "I could not check it" must never
# read the same as "it passed".
READY = "READY"                  # reachable, settings actuated, sound observed
NOT_ACTUABLE = "NOT_ACTUABLE"    # reachable, but the settings could not be changed
UNVERIFIABLE = "UNVERIFIABLE"    # actuated, but nothing could observe the result
UNREACHABLE = "UNREACHABLE"      # not present at all

COUNTED_AS_RUNG = (READY,)


@dataclass(slots=True)
class ReadinessReport:
    """What a rung's own pre-flight found. `state` decides whether it counts."""
    rung_id: str
    state: str
    reachable: bool = False
    settings_actuated: bool = False
    actuation_observed: bool = False
    blocking_settings: tuple = ()
    note: str = ""

    @property
    def counts(self) -> bool:
        return self.state in COUNTED_AS_RUNG


class RungDriver(Protocol):
    """A platform driver. Kept behind a Protocol so `core/` names no product.

    Three methods, and the split between them is the whole point. `prepare`
    changes the device's settings. `actuate` makes the noise. `observe` reports
    whether a noise happened -- and MUST NOT do so by asking `actuate` how it
    went, which is the prohibited ACTUATED -> VERIFIED edge.
    """

    rung_id: str
    modality: str

    def prepare(self) -> ReadinessReport: ...
    def actuate(self, level: int, message: str) -> dict: ...
    def observe(self) -> bool: ...
    def silence(self) -> None: ...


@dataclass(slots=True)
class Rung:
    driver: RungDriver
    level: int
    readiness: ReadinessReport | None = None

    @property
    def rung_id(self) -> str:
        return self.driver.rung_id


@dataclass(slots=True)
class AlarmInstance:
    """One scheduled alarm. Lives in the `alarms` store domain, which
    `lease.py` already declares REFUSE_NON_OWNER and `devices.py` already
    declares CONTINUITY_CRITICAL."""
    alarm_id: str
    due_epoch_s: float
    window_s: int
    label: str
    acknowledged: bool = False
    acknowledged_via: str | None = None
    fired_at_s: float | None = None
    steps: list = field(default_factory=list)

    def now_in_window(self, now_s: float) -> bool:
        return self.due_epoch_s <= now_s < (self.due_epoch_s + self.window_s)


def build_alarm_trigger(alarm: AlarmInstance, *, holds_lease: Callable[[], bool],
                        partition_suspected: Callable[[], bool]):
    """Construct the runtime Trigger matching the SHIPPED `trg_alarm_fire` row.

    The predicate is transcribed from `contracts/policy/trigger_registry.toml`,
    not invented here:

        schedule.now_in(alarm.window)
        AND ( alarm.holds_fire_lease OR world.fabric.partition_suspected )
        AND NOT alarm.acknowledged

    Declaring the terms is what makes `anti_cron_probe` mechanical. With every
    clock term TRUE and every state term FALSE this returns:
        True AND (False OR False) AND True  ->  False
    so the clock alone is NOT sufficient and the trigger is COMPOSITE in fact and
    not merely by label. That check is the one CI-026 exists to run, and a
    hand-rolled "if it is 9am, speak" bypasses it entirely -- which is the reason
    this actuator is wired to the predicate instead of to a timer.
    """
    from .autonomy import Trigger

    def predicate(s: dict) -> bool:
        return bool(
            s.get("schedule.now_in_alarm_window")
            and (s.get("alarms.holds_fire_lease") or s.get("world.fabric.partition_suspected"))
            and not s.get("alarms.acknowledged")
        )

    return Trigger(
        trigger_id="trg_alarm_fire",
        predicate_class="COMPOSITE",
        predicate=predicate,
        clock_terms=("schedule.now_in_alarm_window",),
        state_terms=("alarms.holds_fire_lease", "world.fabric.partition_suspected",
                     "alarms.acknowledged"),
        enabled=True,
        debounce_s=0,
    )


class AlarmActuator:
    """Runs the escalation ladder under the cap, and counts only real rungs."""

    def __init__(self, drivers: list[RungDriver], *, emit: Callable[[str, dict], None],
                 cap_s: int = HARD_CAP_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._drivers = drivers
        self._emit = emit
        self._cap_s = cap_s
        self._clock = clock
        self.rungs: list[Rung] = []
        self.rejected: list[ReadinessReport] = []

    # ---------------------------------------------------------------- pre-flight
    def preflight(self) -> dict:
        """Establish the ladder BEFORE the alarm is due, not while it is firing.

        Running this at fire time would mean discovering that the only device is
        in silent mode at the moment the owner needed to already be awake. It is
        a scheduled act with its own outcome, and a ladder that comes back empty
        is a finding to surface the evening before -- not a surprise at 09:00.
        """
        self.rungs, self.rejected = [], []
        for i, drv in enumerate(self._drivers):
            try:
                rep = drv.prepare()
            except Exception as exc:                       # a driver that raises
                rep = ReadinessReport(                     # is not a usable rung
                    rung_id=getattr(drv, "rung_id", f"rung_{i}"),
                    state=UNREACHABLE, note=f"prepare() raised: {exc!r}")
            if rep.counts:
                self.rungs.append(Rung(driver=drv, level=len(self.rungs) + 1,
                                       readiness=rep))
            else:
                self.rejected.append(rep)
            self._emit("alarm.rung_readiness", {
                "rung_id": rep.rung_id, "state": rep.state,
                "reachable": rep.reachable,
                "settings_actuated": rep.settings_actuated,
                "actuation_observed": rep.actuation_observed,
                "blocking_settings": list(rep.blocking_settings),
                "counted": rep.counts, "note": rep.note,
            })

        report = {
            "counted_rungs": [r.rung_id for r in self.rungs],
            "rejected": [{"rung_id": r.rung_id, "state": r.state,
                          "blocking_settings": list(r.blocking_settings)}
                         for r in self.rejected],
            "ladder_depth": len(self.rungs),
            "gate_evidence": False,
            "note": ("A-012 requires escalation across a device ladder; a "
                     "one-rung ladder is a prototype. Rungs rejected above were "
                     "reachable-but-not-actuable or actuated-but-unobservable, "
                     "and an unactuable rung is not a rung."),
        }
        self._emit("alarm.preflight", report)
        return report

    # -------------------------------------------------------------------- firing
    def fire(self, alarm: AlarmInstance, *, acknowledged: Callable[[], str | None],
             poll_s: float = 0.5) -> dict:
        """Escalate until acknowledged or the cap terminates it.

        FAIL-SAFE DIRECTION. The natural implementation stops when it runs out of
        rungs, which is silence while the owner is still asleep. This one holds
        at the loudest available rung until the cap, because the failure being
        guarded against is a missed wake-up (SR-043), not an excess of noise.
        """
        if not self.rungs:
            out = {"fired": False, "reason": "NO_ACTUABLE_RUNG",
                   "rejected": [r.rung_id for r in self.rejected],
                   "note": ("every candidate device was reachable-but-silent or "
                            "unobservable. Firing into a device that cannot be "
                            "heard would report success and wake nobody.")}
            self._emit("alarm.not_fired", out)
            return out

        started = self._clock()
        alarm.fired_at_s = started
        self._emit("alarm.fired", {"alarm_id": alarm.alarm_id, "label": alarm.label,
                                   "ladder_depth": len(self.rungs)})
        idx, ack_via, capped = 0, None, False

        while True:
            elapsed = self._clock() - started
            if elapsed >= self._cap_s:                     # INV-ALARM-2 / 41.4
                capped = True
                break

            rung = self.rungs[min(idx, len(self.rungs) - 1)]
            step = {"rung_id": rung.rung_id, "level": rung.level,
                    "elapsed_s": round(elapsed, 1)}
            try:
                step["actuation"] = rung.driver.actuate(rung.level, alarm.label)
                # The observation is a SEPARATE call. It does not read the return
                # value above, and this is the ACTUATED -> VERIFIED prohibition
                # in code rather than in a comment.
                step["observed"] = bool(rung.driver.observe())
            except Exception as exc:
                step["actuation"] = {"error": repr(exc)}
                step["observed"] = False

            alarm.steps.append(step)
            self._emit("alarm.escalation_step", step)      # A-012: every step logged

            deadline = self._clock() + max(poll_s, 1.0) * 8
            while self._clock() < deadline:
                via = acknowledged()
                if via:
                    ack_via = via
                    break
                if self._clock() - started >= self._cap_s:
                    capped = True
                    break
                time.sleep(poll_s)
            if ack_via or capped:
                break
            idx += 1

        for r in self.rungs:                               # stop the noise either way
            try:
                r.driver.silence()
            except Exception:
                pass

        alarm.acknowledged = bool(ack_via)
        alarm.acknowledged_via = ack_via
        out = {
            "fired": True,
            "alarm_id": alarm.alarm_id,
            "acknowledged": bool(ack_via),
            "acknowledged_via": ack_via,
            "terminated_by_cap": capped,
            "elapsed_s": round(self._clock() - started, 1),
            "steps": alarm.steps,
            "gate_evidence": False,
            "note": ("prototype run: a one-rung ladder cannot satisfy A-012's "
                     "across-the-ladder assertion, and a firing time known to "
                     "the owner in advance is not the RUNBOOK-ALARM validation "
                     "night."),
        }
        self._emit("alarm.completed", out)
        return out
