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

import ast
import inspect
import json
import textwrap
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus
from .decision_path import ModelCallInDecisionPath as _ModelCallInDecisionPath
from . import decision_path
from .world import UNKNOWN, WorldModel

# A predicate term is either a clock term or a world-state term. The
# classification is what makes the anti-cron check mechanical rather than a
# reading of the trigger's name.
CLOCK_ROOTS = ("schedule", "clock", "time", "elapsed", "cron")
STATE_ROOTS = ("world", "tasks", "backlog", "memory", "devices", "proposals",
               "alarms", "autonomy")

PREDICATE_CLASSES = ("STATE", "EVENT", "COMPOSITE", "SCHEDULE")


# ONE CLASS, NOT A SUBCLASS. Defined in `decision_path` because the GATEWAY
# raises it -- and an `except` clause here that named a subclass would silently
# fail to catch the refusal the gateway actually raises. Re-exported so callers
# keep importing it from where the rule lives.
ModelCallInDecisionPath = _ModelCallInDecisionPath


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
    # WHAT TO DO once the predicate has already decided that something should
    # happen. A sentence, handed to the actor exactly as a spoken request would
    # be, so a fired trigger goes down the same ladder an owner utterance does
    # -- levelled, authorized, contained, checkpointed and verified.
    #
    # IT IS NOT PART OF THE DECISION. `tick` never reads it; `dispatch` does,
    # after the predicate has returned True. That separation is the design and
    # not an implementation detail: WHETHER to wake is deterministic state,
    # WHAT to do once awake may be a model call, and mixing them would put a
    # model back in the decision path this module exists to keep it out of.
    intent: str = ""
    # SYSTEM WORK, for triggers whose answer is not a proposed action. The
    # compactor re-deriving L2 from L3 is not something to ask a model to
    # propose -- it is deterministic maintenance with one right answer, and
    # routing it through the proposer would put a model in front of a decision
    # that has already been made.
    #
    # LIKE `intent`, IT IS NEVER READ WHILE DECIDING. `tick` does not touch it;
    # `dispatch` calls it after the predicate has returned True.
    handler: Any = None

    def __post_init__(self) -> None:
        if self.predicate_class not in PREDICATE_CLASSES:
            raise ValueError(f"predicate_class must be one of {PREDICATE_CLASSES}")


class NonTerminatingPredicate(Exception):
    """A predicate that cannot be shown to terminate. Refused at registration."""


# The value shapes a predicate must survive. Not exhaustive -- a predicate is
# TOTAL over its declared terms, and these are the shapes those terms actually
# take in this system: a fact, a missing fact, a boolean and a number.
_PROBE_SHAPES = (True, False, None, 0, "", UNKNOWN)
_PROBE_DEADLINE_S = 2.0

# A no-op is published when the trigger's snapshot CHANGES, and at least this
# often regardless. Re-stating an unchanged snapshot every tick is not evidence,
# it is repetition: 41.8 hours of one quiet trigger wrote 619,063 identical
# records, and five triggers project to 1.78 million a day. INV-TRIG-6 asks for
# silence to carry provenance, and a record that says "this snapshot has held
# since tick N" carries strictly more of it than a record that says only
# "tick N" -- it states the DURATION of the silence, which the per-tick form
# leaves the reader to infer from absence.
#
# The keepalive is what stops the inference from being unbounded: after this
# many quiet ticks the trigger re-states itself, so "last heard from" is never
# older than NOOP_KEEPALIVE_TICKS even for a term that never moves.
NOOP_KEEPALIVE_TICKS = 60


def assert_terminating(predicate: Callable[[dict], bool],
                       terms: tuple = ()) -> dict:
    """INV-TRIG-5, at the only moment it is cheap: registration.

    A SUFFICIENT CONDITION, NOT A DECISION PROCEDURE, and saying so is part of
    the contract. The halting problem forbids deciding termination in general,
    so this accepts only predicates whose termination is STRUCTURALLY EVIDENT --
    no `while`, no self-recursion -- and then corroborates with a bounded probe.
    A predicate that needs a `while` loop is refused and must be rewritten,
    which is the right trade for a callable that runs unattended in a decision
    path at 03:00.

    SOURCE THAT CANNOT BE READ IS A REFUSAL, not a pass. A predicate built by
    `exec`, or a C callable, cannot be shown to terminate by any means available
    here, and `UNKNOWN` means `UNAVAILABLE` in this corpus as everywhere else.

    TOTALITY IS PROBED OVER THE DECLARED TERMS, because that is the contract:
    `PredicateEvaluator.evaluate` always passes every declared term, so probing
    with an empty dict would refuse correct predicates for a call that cannot
    happen.

    THE PROBE THREAD CANNOT BE KILLED. Python offers no way, so a predicate that
    hangs leaves a daemon thread behind for the life of the process. That is
    itself the argument for refusing at REGISTRATION rather than at tick time:
    one leaked thread at startup is a bounded cost, and one per tick is not.
    """
    findings = {"structural": "ok", "probe": "ok"}

    try:
        src = textwrap.dedent(inspect.getsource(predicate))
    except (OSError, TypeError) as exc:
        raise NonTerminatingPredicate(
            f"the predicate's source cannot be read ({exc!r}), so its "
            "termination cannot be shown by any means available here. UNKNOWN "
            "is UNAVAILABLE: a predicate that cannot be inspected is refused "
            "rather than trusted.") from exc

    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A nested def often dedents to something unparseable on its own.
        # Wrapping is not a workaround -- it restores the context the source
        # was written in.
        try:
            tree = ast.parse("if True:\n" + textwrap.indent(src, "    "))
        except SyntaxError as exc:
            raise NonTerminatingPredicate(
                f"the predicate's source does not parse ({exc}), so nothing "
                "can be established about it") from exc

    own_names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            raise NonTerminatingPredicate(
                "the predicate contains a `while` loop. Termination is not "
                "decidable in general, so registration accepts only predicates "
                "whose termination is structurally evident -- rewrite it as a "
                "bounded `for` or a direct expression (INV-TRIG-5).")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in own_names:
            raise NonTerminatingPredicate(
                f"the predicate calls itself ({node.func.id!r}). Recursion "
                "depth here is a function of world state, which is exactly the "
                "input a predicate must not be able to diverge on.")

    # THE BOUNDED PROBE IS CORROBORATION, NOT PROOF. It catches the shapes the
    # structural rules cannot see -- a `for` over an unbounded generator, a
    # blocking call -- and it cannot catch a predicate that diverges only on a
    # world state this probe did not construct.
    for shape in _PROBE_SHAPES:
        snapshot = {t: shape for t in (terms or ("probe.term",))}
        done: list = []

        def _run(snap: dict = snapshot) -> None:
            try:
                done.append(bool(predicate(snap)))
            except Exception as exc:                  # noqa: BLE001
                done.append(exc)

        # RETRIED ONCE BEFORE REFUSING. A wall-clock deadline inside a
        # REGISTRATION path makes registration non-deterministic: a scheduling
        # hiccup on a loaded machine refuses a predicate that terminates fine,
        # and the symptom is an intermittently red gate -- which reads as flaky
        # rather than broken and is the worse failure. A genuinely
        # non-terminating predicate misses both deadlines; a hiccup misses one.
        # The cost is one extra deadline on a true positive, paid once at
        # registration and never on the hot path.
        #
        # Added after F5 failed exactly once on 2026-08-31 and could not be
        # reproduced in eight runs, four of them under deliberate CPU load. The
        # cause was not established, so this hardens the mechanism rather than
        # claiming to fix that run.
        timed_out = 0
        for _ in range(2):
            done.clear()
            th = threading.Thread(target=_run, daemon=True)
            th.start()
            th.join(_PROBE_DEADLINE_S)
            if not th.is_alive():
                break
            timed_out += 1
        if timed_out >= 2:
            raise NonTerminatingPredicate(
                f"the predicate did not return within {_PROBE_DEADLINE_S}s on "
                f"a snapshot of {shape!r}, twice.")
        if done and isinstance(done[0], Exception):
            raise NonTerminatingPredicate(
                f"the predicate raised {done[0]!r} on a snapshot of {shape!r}. "
                "A predicate is TOTAL over its declared terms: one that raises "
                "on a legitimate value does not evaluate to False, it takes the "
                "tick down with it.")
    return findings


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

        # THE PREDICATE IS ARBITRARY CALLER CODE. This class has no model path,
        # but the callable it runs can close over one -- measured 2026-08-24, a
        # predicate that asked a gateway "is there anything worth doing?" fired
        # on the answer with nothing recorded. The flag is process-visible so
        # the MODEL CAPABILITY can refuse, rather than relying on the decision
        # path to police itself.
        self._in_decision_path.active = True
        try:
            with decision_path.entered(self._bus, "evaluator"):
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

    # ~7 days at a 60 s cadence. Large enough that no acceptance window is
    # truncated, small enough that a month-long process is bounded.
    DEFAULT_HISTORY = 10_000

    def __init__(self, bus: EventBus, world: WorldModel,
                 evaluator: PredicateEvaluator, *, tick_interval_s: float = 1.0,
                 now_ms: Any = None,
                 history_limit: int = DEFAULT_HISTORY, actor: Any = None,
                 interlock: Any = None) -> None:
        self._bus = bus
        self._actor = actor
        self._interlock = interlock
        self._world = world
        self._eval = evaluator
        self.tick_interval_s = tick_interval_s
        # When the last tick ran, for `due()`. None means never, so
        # the first pass always ticks rather than waiting one interval
        # for a loop that has only just started.
        self._last_tick_ms: float | None = None
        self._now_ms = now_ms or (lambda: 0)
        self._triggers: dict[str, Trigger] = {}
        self._last_fire: dict[str, int] = {}
        self._lock = threading.RLock()
        self.ticks = 0
        # BOUNDED, and the bound is the point. Every entry here is also
        # published to the durable log, so these are a convenience for callers
        # -- never the record of what happened. Unbounded, they made a process
        # that stays up for a month accumulate a month of history in memory,
        # which the endurance run exists to catch.
        #
        # `dropped_history` is not decoration: a caller that reads these lists
        # must be able to tell "nothing was dropped" from "I am looking at a
        # tail". Silently handing back a truncated history is how a long run
        # gets judged against the part of itself it happens to remember.
        self.history_limit = history_limit
        self.dropped_history = 0
        # trigger_id -> (snapshot fingerprint, tick it became
        # current, tick it was last published). Not history --
        # three scalars per trigger, so it does not grow with
        # uptime the way the thing it replaces did.
        self._noop_state: dict[str, tuple[str, int, int]] = {}
        self.heartbeats: deque = deque(maxlen=history_limit)
        self.fired: deque = deque(maxlen=history_limit)
        self.noops: deque = deque(maxlen=history_limit)

    def _remember(self, dq: deque, item: dict) -> None:
        """Append to a bounded history, counting what falls off the end.

        A `deque(maxlen=...)` drops silently, which is exactly the behaviour a
        caller must not inherit unknowingly. Counting the drop is what lets
        `dropped_history` distinguish a complete record from a tail.
        """
        if dq.maxlen is not None and len(dq) == dq.maxlen:
            self.dropped_history += 1
        dq.append(item)

    def register(self, trigger: Trigger) -> Trigger:
        """Register a trigger. A cron-in-disguise is REFUSED at registration.

        Same construction as the constant-level capability in F2: the only
        moment the mistake is cheap is before it is in the system.
        """
        # INV-TRIG-5 FIRST. A predicate that may not terminate must not be run,
        # and `anti_cron_probe` RUNS it -- so checking cron-disguise first would
        # hang the registration on exactly the predicate this refuses.
        assert_terminating(trigger.predicate,
                           tuple(trigger.clock_terms) + tuple(trigger.state_terms))

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

    def due(self, *, now_ms: float | None = None) -> bool:
        """Has `tick_interval_s` elapsed since the last tick?

        THE LOOP DECLARED A CADENCE AND NOTHING CONSULTED IT. `tick_interval_s`
        has defaulted to 1.0 since this class was written, and the pump called
        `tick()` on every pass -- so the loop ran at POLL_SECONDS (0.15 s),
        which is the interval the SPEECH path needs, not this one. Measured on
        the live log: a median gap of 163 ms between heartbeats, 6.7x the rate
        the loop says it runs at. The declared value was not a target, it was
        decoration.

        WHY THIS IS THE SENSOR PATTERN AND NOT A NEW ONE. `SensorRegistry`
        already solves exactly this: sensors declare `period_ms` (60 s, 120 s,
        300 s) and are polled only when due, inside the same 0.15 s pump. The
        autonomy loop is the one subsystem that was never given the same
        treatment, and the sensor module's own comment is the argument -- "a
        heartbeat nobody asked for buries the events that matter under a
        hundred to one".

        PACED ON A DURATION CLOCK, WHICH IS NOT AN ORDERING. INV-COORD-4 says
        the wall clock never orders or supersedes; "has 1 second elapsed" is a
        duration question, is answered the same way sensors answer theirs, and
        orders nothing.
        """
        now = self._now_ms() if now_ms is None else now_ms
        if self._last_tick_ms is None:
            return True
        return (now - self._last_tick_ms) >= self.tick_interval_s * 1000.0

    def tick(self) -> list:
        """One cycle. Emits a heartbeat whether or not anything fires."""
        with self._lock:
            self.ticks += 1
            self._last_tick_ms = self._now_ms()
            triggers = list(self._triggers.values())

        hb = {"tick": self.ticks, "at_ms": self._now_ms()}
        self._remember(self.heartbeats, hb)
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
                #
                # Published on CHANGE, not on tick. `since_tick` is what keeps
                # this auditable: the record does not merely say the trigger was
                # quiet at this instant, it says the snapshot it was quiet under
                # has held unchanged since that tick. A reader reconstructs any
                # intervening tick from the record that covers it.
                fp = json.dumps(snap, sort_keys=True, default=str)
                prev = self._noop_state.get(t.trigger_id)
                if prev is None or prev[0] != fp:
                    since, changed, last_pub = self.ticks, True, None
                else:
                    _, since, last_pub = prev
                    changed = False
                # The staleness clock runs from the last PUBLISHED record, not
                # from the last tick. Advancing it every tick was the first
                # version of this and it silently disabled the keepalive
                # entirely: `self.ticks - last_tick` is 1 forever, so the
                # threshold is never reached and a trigger that never changes
                # is heard from exactly once. It measured 1 record where it
                # should have measured 10.
                stale = (not changed
                         and self.ticks - last_pub >= NOOP_KEEPALIVE_TICKS)
                self._noop_state[t.trigger_id] = (
                    fp, since, self.ticks if (changed or stale) else last_pub)

                if changed or stale:
                    noop = {"trigger_id": t.trigger_id, "tick": self.ticks,
                            "fired": False, "snapshot": snap,
                            "since_tick": since,
                            "ticks_covered": self.ticks - since + 1,
                            # Why this record exists, so a reader never has to
                            # guess whether a gap is a quiet trigger or a dead
                            # one: "changed" means the world moved, "keepalive"
                            # means it did not and the trigger said so anyway.
                            "reason": "changed" if changed else "keepalive"}
                    self._remember(self.noops, noop)
                    self._bus.publish("autonomy.noop", subject=t.trigger_id,
                                      payload=noop, component="autonomy")
                continue

            # THE RUN OF SILENCE ENDS WHERE THE PREDICATE STOPS BEING FALSE,
            # not where the action dispatches. Dropping this state below the
            # debounce check instead was wrong and it was wrong LIVE, not in
            # theory: every trigger in `core/self_directed.py` sets debounce_s
            # between 300 and 3600 seconds, so a trigger that fires and stays
            # true is debounced for up to an hour of ticks during which nothing
            # publishes -- and the surviving run would then let a later record
            # claim, via `since_tick`, that the trigger was quiet straight
            # through the tick it fired on.
            self._noop_state.pop(t.trigger_id, None)

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
            self._remember(self.fired, action)
            actions.append(action)
            self._bus.publish("autonomy.trigger_fired", subject=t.trigger_id,
                              payload=action, component="autonomy")
        return actions

    def attach_interlock(self, interlock: Any) -> "AutonomyLoop":
        """Give the loop its stop, after construction. See `attach_actor`."""
        self._interlock = interlock
        return self

    def attach_actor(self, actor: Any) -> "AutonomyLoop":
        """Give the loop hands, after construction.

        The runtime builds this loop before it builds the actor, and the actor
        needs a gateway the loop does not. A setter is honest about that
        ordering; reaching into `_actor` from the runtime would work and would
        hide it.
        """
        self._actor = actor
        return self

    def dispatch(self, actions: list, *, period: str = "free_time",
                 attention_state: str = "ABSENT") -> list:
        """Act on triggers that have ALREADY fired. Never part of the decision.

        THE LAYER THAT WAS MISSING. `core/autonomy.py` had `Trigger`,
        `PredicateEvaluator`, `AutonomyLoop` and `AutonomyRunner`, it ran on
        every pass of the runtime, and `grep actor core/autonomy.py` returned
        nothing but an unrelated comment. So a fired trigger could publish an
        event and could not do anything -- a working engine with one
        instruction and no hands.

        WHY IT IS A SEPARATE METHOD FROM `tick`. `tick` decides and returns;
        this acts on what it decided. Keeping them apart means `tick` holds no
        reference to the actor at all, so the property "no model call in the
        decision path" is structural rather than a rule someone has to
        remember. A check can read `tick` and see it.

        FREE_TIME AND ABSENT ARE THE DEFAULTS, and they are not decoration. A
        refusal here reaches `ConfirmationBroker.request`, which allocates
        against the interruption budget for that period -- and the refusals
        VESPER's own work produces most often (`below_required_level`,
        `context_ceiling`) are not in CONFIRMABLE_REASONS at all, so they
        return "not confirmable" rather than becoming a voice at three in the
        morning. Autonomous work is bounded to what the standing grant already
        allows, and everything else waits for a person.
        """
        # THE DEAD-MAN'S SWITCH, ASKED ONCE PER DISPATCH. `autonomy_permitted`
        # is false when a stop is engaged AND when no fresh token is present --
        # and the second is the one that matters, because it is what makes
        # every failure of the arming path fail toward stopped rather than
        # toward running.
        #
        # ASKED HERE AND NOT IN `tick`. Deciding whether a trigger's condition
        # holds is not acting on it; a stopped VESPER should still observe,
        # still record, and still be able to say what it would have done.
        # A-031.4 lists observation and telemetry as surviving STOP_AUTONOMY
        # for exactly that reason.
        if self._interlock is not None and not self._interlock.autonomy_permitted():
            if actions:
                self._bus.publish(
                    "autonomy.stopped", subject="interlock",
                    payload={"reason": self._interlock.stop_reason(),
                             "would_have_acted": [a.get("trigger_id")
                                                  for a in actions],
                             "note": ("autonomy is not permitted: no fresh "
                                      "enable token, or a stop is engaged. The "
                                      "triggers still fired and are recorded.")},
                    component="autonomy")
            return []

        done = []
        for action in actions or []:
            tid = action.get("trigger_id")
            trigger = self._triggers.get(tid)
            intent = getattr(trigger, "intent", "") if trigger else ""
            handler = getattr(trigger, "handler", None) if trigger else None

            if handler is not None:
                try:
                    got = handler()
                except Exception as exc:            # noqa: BLE001
                    self._bus.publish(
                        "autonomy.handler_failed", subject=tid,
                        payload={"trigger_id": tid,
                                 "error": f"{type(exc).__name__}: {exc}"},
                        component="autonomy")
                else:
                    rec = {"trigger_id": tid, "handled": True, "result": got}
                    done.append(rec)
                    self._bus.publish("autonomy.handled", subject=tid,
                                      payload=rec, component="autonomy")

            if not intent:
                continue
            if self._actor is None:
                self._bus.publish(
                    "autonomy.no_actor", subject=tid,
                    payload={"trigger_id": tid,
                             "note": ("a trigger fired with something to do and "
                                      "the loop holds no actor, so nothing can "
                                      "happen")},
                    component="autonomy")
                continue
            try:
                outcome = self._actor.maybe_act(
                    intent, attention_state=attention_state, period=period,
                    # THE STOP FOLLOWS THE WORK IN, and until 2026-09-01 it did
                    # not. The interlock was consulted once above, before the
                    # actor was ever called, so a stop pressed during a turn was
                    # not seen until the turn had finished by itself -- up to
                    # six steps, each a shell command or a file write, after the
                    # owner said stop. `dispatch` passes it because `dispatch`
                    # is what knows this work is autonomous; an owner-typed turn
                    # passes nothing and is untouched.
                    permitted=(self._interlock.autonomy_permitted
                               if self._interlock is not None else None))
            except Exception as exc:                   # noqa: BLE001
                # A FIRED TRIGGER MUST NOT TAKE THE LOOP DOWN, for the same
                # reason a bad predicate must not: a dead loop is the failure
                # this whole module exists to make visible.
                self._bus.publish("autonomy.dispatch_failed", subject=tid,
                                  payload={"trigger_id": tid,
                                           "error": f"{type(exc).__name__}: {exc}"},
                                  component="autonomy")
                continue
            record = {"trigger_id": tid,
                      "intent": intent,
                      "outcome": outcome.to_dict() if outcome is not None else None}
            done.append(record)
            self._bus.publish("autonomy.acted", subject=tid, payload=record,
                              component="autonomy")
        return done

    def replay_predicate(self, action: dict) -> bool:
        """A-029 Part 2: re-evaluate the predicate against its snapshot."""
        t = self._triggers[action["trigger_id"]]
        return bool(t.predicate(action["snapshot"]))

    def registry_report(self) -> list:
        with self._lock:
            return [anti_cron_probe(t) for t in self._triggers.values()]


class AutonomyRunner:
    """Drives the loop in real time, and watches it FROM OUTSIDE.

    WHY THIS EXISTS AT ALL. `AutonomyLoop.tick()` is a single cycle; something
    has to call it. Until now the only caller was a test loop advancing a
    simulated clock, which means A-029 Part 1 -- liveness across a real window
    -- had nothing to be true of. `Supervisor` deliberately refuses the job
    ("THE HEARTBEAT DOES NOT PRETEND TO BE A SCHEDULER"), and it is right to:
    driving autonomy from the lease heartbeat would make elapsed time a reason
    to act. This is the driver, kept separate for that reason.

    THE WATCHDOG IS A SEPARATE THREAD, AND THAT IS THE WHOLE POINT. A stall
    detector living inside the loop it watches cannot report the one failure
    that matters -- the loop being dead -- because a dead thread emits nothing.
    `AT-03` requires `autonomy.loop_stalled` to FIRE against C4, the
    silent-death build. Before this class, NOTHING in the runtime could emit
    that event, which made A-029 Part 1's "`autonomy.loop_stalled` never fires"
    an assertion about an event no code path could produce. An absence that
    cannot become a presence measures nothing.

    SCHEDULING IS BY ABSOLUTE DEADLINE, not by sleeping for the interval. A
    24-hour run of `sleep(60)` accumulates every cycle's work as drift; over
    1,440 cycles that is the difference between a cadence and an approximation.
    Lateness is recorded per cycle rather than smoothed away.
    """

    STALL_FACTOR = 3          # INV-AUTO-1: absence beyond 3x tick_interval

    def __init__(self, bus: EventBus, loop: AutonomyLoop, *,
                 tick_interval_s: float | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._bus = bus
        self._loop = loop
        self.tick_interval_s = (tick_interval_s if tick_interval_s is not None
                                else loop.tick_interval_s)
        self._mono = monotonic
        self._stopping = threading.Event()
        self._tick_thread: threading.Thread | None = None
        self._watch_thread: threading.Thread | None = None

        self._last_tick_mono: float = 0.0
        self._lock = threading.RLock()
        self.late_ticks = 0
        self.max_lateness_s = 0.0
        self.stall_episodes = 0
        self.cycle_errors = 0
        self.started_mono: float = 0.0

    # ----------------------------------------------------------------- drive

    def start(self) -> "AutonomyRunner":
        self.started_mono = self._mono()
        with self._lock:
            self._last_tick_mono = self.started_mono
        self._tick_thread = threading.Thread(target=self._drive, daemon=True,
                                             name="vesper-autonomy")
        self._watch_thread = threading.Thread(target=self._watch, daemon=True,
                                              name="vesper-autonomy-watchdog")
        self._tick_thread.start()
        self._watch_thread.start()
        return self

    def _drive(self) -> None:
        deadline = self.started_mono
        while not self._stopping.is_set():
            began = self._mono()
            lateness = began - deadline
            if lateness > self.tick_interval_s:
                self.late_ticks += 1
                self.max_lateness_s = max(self.max_lateness_s, lateness)
            try:
                self._loop.tick()
            except Exception as e:  # noqa: BLE001
                # A cycle that raises must not take the loop down: a dead loop
                # is the failure this whole class exists to make visible, and
                # dying quietly on one bad predicate is how it happens.
                self.cycle_errors += 1
                self._bus.publish("autonomy.cycle_error", subject="loop",
                                  payload={"error": f"{type(e).__name__}: {e}"},
                                  component="autonomy")
            with self._lock:
                self._last_tick_mono = self._mono()
            deadline += self.tick_interval_s
            # If we are more than a whole interval behind, resynchronise rather
            # than firing a burst of catch-up ticks. A burst would forge the
            # cadence the gate is measuring.
            now = self._mono()
            if deadline < now:
                deadline = now + self.tick_interval_s
            self._stopping.wait(max(0.0, deadline - now))

    # -------------------------------------------------------------- watchdog

    def _watch(self) -> None:
        interval = max(0.05, self.tick_interval_s / 2.0)
        stalled = False
        while not self._stopping.wait(interval):
            with self._lock:
                since = self._mono() - self._last_tick_mono
            limit = self.STALL_FACTOR * self.tick_interval_s
            if since > limit and not stalled:
                # Edge-triggered: one event per episode, not one per poll. A
                # dead loop would otherwise emit thousands of identical events
                # and bury the moment it died.
                stalled = True
                self.stall_episodes += 1
                self._bus.publish(
                    "autonomy.loop_stalled", subject="loop",
                    # NOT ROUNDED, and the reason is not fussiness.
                    #
                    # The decision above is `since > limit` on the raw floats.
                    # This payload is the AUDIT RECORD for INV-AUTO-1 -- it is
                    # what a reader has to judge the incident by after the fact.
                    # Rounding `since` to 3 places while leaving `limit` raw
                    # made the record contradict the decision that produced it:
                    # 3 * 0.2 is 0.6000000000000001 in binary floating point, so
                    # any gap in (0.6, 0.6005) was recorded as exactly 0.6 and
                    # a reader checking the arithmetic would find a stall whose
                    # own numbers say the limit was never exceeded.
                    #
                    # It went red in CI on 2026-08-18 and passed on this
                    # developer's machine, because the band is about half a
                    # millisecond wide and only a differently-scheduled watchdog
                    # poll lands inside it. An intermittently self-refuting
                    # audit record is worse than a consistently wrong one: it
                    # invites re-running until the evidence looks tidy.
                    #
                    # Record what was compared. Rounding is presentation, and
                    # presentation belongs to whoever renders it.
                    payload={"since_last_tick_s": since,
                             "limit_s": limit,
                             "tick_interval_s": self.tick_interval_s,
                             "episode": self.stall_episodes,
                             "note": ("INV-AUTO-1: absence beyond 3x "
                                      "tick_interval is an incident, not a "
                                      "quiet period. Detected from outside the "
                                      "loop thread, because a dead thread "
                                      "cannot report its own death.")},
                    component="autonomy")
            elif since <= limit and stalled:
                stalled = False
                self._bus.publish("autonomy.loop_resumed", subject="loop",
                                  payload={"episode": self.stall_episodes},
                                  component="autonomy")

    # ------------------------------------------------------------------ stop

    def stop(self) -> dict:
        self._stopping.set()
        for t in (self._tick_thread, self._watch_thread):
            if t is not None:
                t.join(timeout=self.tick_interval_s * 2 + 5.0)
        return self.status()

    def alive(self) -> bool:
        return bool(self._tick_thread and self._tick_thread.is_alive())

    def status(self) -> dict:
        with self._lock:
            since = self._mono() - self._last_tick_mono
        return {
            "ticks": self._loop.ticks,
            "tick_interval_s": self.tick_interval_s,
            "since_last_tick_s": round(since, 3),
            "late_ticks": self.late_ticks,
            "max_lateness_s": round(self.max_lateness_s, 3),
            "stall_episodes": self.stall_episodes,
            "cycle_errors": self.cycle_errors,
            "elapsed_s": round(self._mono() - self.started_mono, 1),
        }
