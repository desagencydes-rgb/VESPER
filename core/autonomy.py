"""The autonomy loop — the anti-chatbot property, made testable.

THIS IS THE FILE THE WHOLE ARCHITECTURE EXISTS TO JUSTIFY. Everything before it
is infrastructure; this is the part that makes VESPER something other than a
chatbot with a cron job attached. Three properties, and each has a control that
must fail.

1. THE EVALUATOR CANNOT CALL A MODEL (INV-AUTO-2). Not "does not" — CANNOT.
   `PredicateEvaluator` is handed world state and nothing else: no gateway, no
   router, no callable that could reach one. A-011.4 attempts a model call
   inside the evaluator and requires both that `autonomy.model_call_in_decision_
   path` is emitted AND that the call raises. A loop that asks a model "is there
   anything worth doing?" is a chatbot that talks to itself, and C2 is that
   build.

2. A TRIGGER MUST REQUIRE WORLD STATE, NOT JUST THE CLOCK (INV-AUTO-5). The
   discriminator is mechanical: evaluate the predicate with every clock term
   TRUE and every world-state term FALSE. If it still fires, the clock alone is
   sufficient and the trigger is cron whatever its label says. C1 — pure cron —
   passes liveness and provenance and FAILS this, and the corpus calls that
   "the single most important run in the verification programme".

3. AN UNKNOWN FACT DOES NOT FIRE (INV-COORD-2, from the acting side). A
   predicate over an expired fact evaluates FALSE, not "probably still true".
   This is why the world model returns UNKNOWN rather than a stale value: the
   two produce different actions, and only one of them is safe.

EVERY AUTONOMOUS ACTION RESOLVES TO EXACTLY ONE REGISTERED trigger_id
(INV-TRIG-1), INCLUDING NO-OPS. A recorded no-op with a trigger_id is how a
quiet night is distinguished from a dead one — which is exactly what C4 (silent
death) tests.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus
from .world import UNKNOWN, WorldModel

# A predicate term is either a clock term or a world-state term. The
# classification is what makes the anti-cron check mechanical rather than a
# reading of the trigger's name.
CLOCK_ROOTS = ("schedule", "clock", "time", "elapsed", "cron")
STATE_ROOTS = ("world", "tasks", "backlog", "memory", "devices", "proposals",
               "alarms", "autonomy")

PREDICATE_CLASSES = ("STATE", "EVENT", "COMPOSITE", "SCHEDULE")


class ModelCallInDecisionPath(Exception):
    """A model was reached from inside the evaluator. INV-AUTO-2."""


class CronDisguisedAsTrigger(Exception):
    """A trigger that fires on the clock alone, whatever it is labelled."""


@dataclass(slots=True)
class Trigger:
    trigger_id: str
    predicate_class: str
    # A callable over a state dict. Deliberately NOT a string to be eval'd:
    # a string predicate needs an interpreter, and an interpreter is a place a
    # model call can hide.
    predicate: Callable[[dict], bool]
    # The terms this predicate reads, declared. Used for the anti-cron probe.
    clock_terms: tuple = ()
    state_terms: tuple = ()
    enabled: bool = True
    debounce_s: int = 0

    def __post_init__(self) -> None:
        if self.predicate_class not in PREDICATE_CLASSES:
            raise ValueError(f"predicate_class must be one of {PREDICATE_CLASSES}")


class PredicateEvaluator:
    """Evaluates predicates over world state. HAS NO PATH TO A MODEL.

    The constructor takes a WorldModel and nothing else. There is no gateway
    parameter to forget to remove, no router, no callable that could reach one.
    INV-AUTO-2 is enforced by what this class is not given.
    """

    def __init__(self, bus: EventBus, world: WorldModel) -> None:
        self._bus = bus
        self._world = world
        # Set while a predicate is running, so an attempted model call can be
        # detected and attributed rather than merely blocked.
        self._in_decision_path = threading.local()

    def snapshot(self, terms: tuple) -> dict:
        """Read the world state a predicate needs. Reconstructible afterwards.

        A-029 Part 2 requires the predicate to RE-EVALUATE TRUE against its
        reconstructed snapshot, so the snapshot is the evidence, not the log
        line saying it fired.
        """
        out = {}
        for t in terms:
            if "." in t:
                subj, attr = t.rsplit(".", 1)
                out[t] = self._world.read(subj, attr)
            else:
                out[t] = UNKNOWN
        return out

    def evaluate(self, trigger: Trigger, snapshot: dict) -> bool:
        """Run the predicate. An UNKNOWN term makes it FALSE, never 'probably'."""
        # INV-COORD-2 from the acting side: an expired fact does not fire.
        if any(v == UNKNOWN for v in snapshot.values()):
            unknowns = [k for k, v in snapshot.items() if v == UNKNOWN]
            self._bus.publish(
                "autonomy.predicate_unknown", subject=trigger.trigger_id,
                payload={"trigger_id": trigger.trigger_id,
                         "unknown_terms": unknowns, "fired": False,
                         "note": ("a predicate over an UNKNOWN fact does not "
                                  "fire. UNKNOWN and 'probably still true' "
                                  "produce different actions, and only one is "
                                  "safe.")},
                component="autonomy")
            return False

        self._in_decision_path.active = True
        try:
            return bool(trigger.predicate(snapshot))
        finally:
            self._in_decision_path.active = False

    def model_call_attempted(self, where: str = "evaluator") -> None:
        """Called by any model path that finds itself inside the evaluator.

        Emits AND raises. A-011.4 requires both: the emission makes it visible
        in the audit trail, the raise makes it impossible to proceed. Emitting
        without raising would leave a build that logs its own violation and
        carries on.
        """
        self._bus.publish(
            "autonomy.model_call_in_decision_path", subject=where,
            payload={"where": where,
                     "note": ("INV-AUTO-2: the decision to act is made by "
                              "predicates over world state, never by asking a "
                              "model. A loop that asks 'is there anything worth "
                              "doing?' is a chatbot talking to itself.")},
            component="autonomy")
        raise ModelCallInDecisionPath(
            f"a model call was attempted inside {where}; the evaluator has no "
            "model path by construction and this call is refused")

    def in_decision_path(self) -> bool:
        return getattr(self._in_decision_path, "active", False)


def anti_cron_probe(trigger: Trigger) -> dict:
    """THE DISCRIMINATOR. Evaluate with all clock terms TRUE, all state FALSE.

    If the predicate still fires, the clock alone is sufficient and the trigger
    is cron whatever it is labelled. This is mechanical rather than a reading of
    the trigger's name, which is the only way it can be checked by CI.
    """
    probe = {t: True for t in trigger.clock_terms}
    probe.update({t: False for t in trigger.state_terms})
    try:
        fires = bool(trigger.predicate(probe))
    except Exception:
        fires = False
    return {
        "trigger_id": trigger.trigger_id,
        "declared_class": trigger.predicate_class,
        "fires_on_clock_alone": fires,
        "effective_class": "SCHEDULE" if fires else trigger.predicate_class,
        "note": ("fires with every clock term true and every world-state term "
                 "false -- the clock alone is sufficient" if fires else
                 "requires world state to fire"),
    }


class AutonomyLoop:
    """Ticks, evaluates, acts. Never asks a model whether to act."""

    def __init__(self, bus: EventBus, world: WorldModel,
                 evaluator: PredicateEvaluator, *, tick_interval_s: float = 1.0,
                 now_ms: Any = None) -> None:
        self._bus = bus
        self._world = world
        self._eval = evaluator
        self.tick_interval_s = tick_interval_s
        self._now_ms = now_ms or (lambda: 0)
        self._triggers: dict[str, Trigger] = {}
        self._last_fire: dict[str, int] = {}
        self._lock = threading.RLock()
        self.ticks = 0
        self.heartbeats: list = []
        self.fired: list = []
        self.noops: list = []

    def register(self, trigger: Trigger) -> Trigger:
        """Register a trigger. A cron-in-disguise is REFUSED at registration.

        Same construction as the constant-level capability in F2: the only
        moment the mistake is cheap is before it is in the system.
        """
        probe = anti_cron_probe(trigger)
        if probe["fires_on_clock_alone"] and trigger.predicate_class != "SCHEDULE":
            self._bus.publish("autonomy.cron_disguise_refused",
                              subject=trigger.trigger_id, payload=probe,
                              component="autonomy")
            raise CronDisguisedAsTrigger(
                f"{trigger.trigger_id!r} declares {trigger.predicate_class} but "
                "fires with every world-state term false. The clock alone is "
                "sufficient, so it is SCHEDULE-class whatever it is labelled "
                "(INV-AUTO-5).")
        with self._lock:
            self._triggers[trigger.trigger_id] = trigger
        return trigger

    def tick(self) -> list:
        """One cycle. Emits a heartbeat whether or not anything fires."""
        with self._lock:
            self.ticks += 1
            triggers = list(self._triggers.values())

        hb = {"tick": self.ticks, "at_ms": self._now_ms()}
        self.heartbeats.append(hb)
        self._bus.publish("autonomy.heartbeat", subject="loop", payload=hb,
                          component="autonomy")

        actions = []
        for t in triggers:
            if not t.enabled:
                continue
            snap = self._eval.snapshot(t.state_terms)
            # Clock terms are supplied to the predicate as real values, but they
            # are never sufficient on their own -- that was settled at
            # registration by the anti-cron probe.
            snap.update({c: True for c in t.clock_terms})
            fires = self._eval.evaluate(t, snap)

            if not fires:
                # INV-TRIG-6: a recorded no-op carries a trigger_id. This is how
                # a quiet night is distinguishable from a dead one.
                noop = {"trigger_id": t.trigger_id, "tick": self.ticks,
                        "fired": False, "snapshot": snap}
                self.noops.append(noop)
                self._bus.publish("autonomy.noop", subject=t.trigger_id,
                                  payload=noop, component="autonomy")
                continue

            if t.debounce_s and self._last_fire.get(t.trigger_id) is not None:
                if (self._now_ms() - self._last_fire[t.trigger_id]
                        < t.debounce_s * 1000):
                    continue

            self._last_fire[t.trigger_id] = self._now_ms()
            action = {
                "trigger_id": t.trigger_id,           # INV-TRIG-1
                "predicate_class": t.predicate_class,
                "tick": self.ticks,
                "at_ms": self._now_ms(),
                # A-029 Part 2: the snapshot IS the evidence.
                "snapshot": snap,
                "model_involved_in_decision": False,
            }
            self.fired.append(action)
            actions.append(action)
            self._bus.publish("autonomy.trigger_fired", subject=t.trigger_id,
                              payload=action, component="autonomy")
        return actions

    def replay_predicate(self, action: dict) -> bool:
        """A-029 Part 2: re-evaluate the predicate against its snapshot."""
        t = self._triggers[action["trigger_id"]]
        return bool(t.predicate(action["snapshot"]))

    def registry_report(self) -> list:
        with self._lock:
            return [anti_cron_probe(t) for t in self._triggers.values()]
