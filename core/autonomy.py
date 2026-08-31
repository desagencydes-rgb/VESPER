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
                 history_limit: int = DEFAULT_HISTORY) -> None:
        self._bus = bus
        self._world = world
        self._eval = evaluator
        self.tick_interval_s = tick_interval_s
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

    def tick(self) -> list:
        """One cycle. Emits a heartbeat whether or not anything fires."""
        with self._lock:
            self.ticks += 1
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
                noop = {"trigger_id": t.trigger_id, "tick": self.ticks,
                        "fired": False, "snapshot": snap}
                self._remember(self.noops, noop)
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
            self._remember(self.fired, action)
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
