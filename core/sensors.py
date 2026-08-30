"""The sensor layer — what makes the trigger predicates evaluable at all.

THE GAP THIS CLOSES, and it is an input gap rather than a design gap.
`contracts/policy/trigger_registry.toml` holds eight triggers whose predicates
read `world.owner.attention_state`, `world.current_host.health`,
`world.current_host.power_source`, `world.system.operating_period` and
`nodes.reachable_set` -- and NOTHING POPULATES ANY OF THEM. The predicates are
correct, gated, and evaluate over an empty world, where `INV-TRIG-4` makes them
all UNKNOWN and none of them fire. A sensor is not a new subsystem; it is the
thing that makes the existing ones able to be true.

A SENSOR AND THE VERIFIER ARE THE SAME SHAPE, which is why this is one registry
and not two. The verifier is `fact -> probe -> cost -> freshness`, consulted on
demand before trusting a fact; a sensor is `source -> probe -> cost -> period`,
run on a schedule. Same probe, two callers. Two registries would drift, and the
drift would be invisible: the scheduled reading and the on-demand reading of the
same fact would disagree and both would look right.

THE ALWAYS-ON LAYER NEVER CALLS A MODEL, AND THAT IS ENFORCED RATHER THAN
DOCUMENTED. Every probe runs inside `decision_path.entered`, so a probe that
reaches `ModelGateway.complete` is REFUSED at the gateway and the attempt is
published. This is not only cost discipline: A REGEX CANNOT BE PROMPT-INJECTED.
A sensor reads SMS, screens, calendar invites and pages found during research --
text an outsider can put in front of VESPER. The moment a model sits in the
filter, the filter becomes the vulnerability it exists to prevent, and "let us
just have a small model watch for interesting things" is the most natural next
suggestion anyone will make.

THE FILTER LOGS WHAT IT DISCARDED. A filter deciding what reaches VESPER is
deciding what VESPER KNOWS, and a filter bug produces SILENCE -- undetectable,
exactly like a memory miss. The discard log is the miss log's shape at a
different layer, and it is the only thing that makes the thresholds tunable.

A FAILED PROBE YIELDS UNKNOWN AND NEVER A STALE VALUE. `INV-EVID-3` and the
world model already treat UNKNOWN and "probably still true" as different
actions, and only one of them is safe. A sensor that returned its last reading
when the probe failed would turn every predicate over it into a statement about
the past that reads as a statement about now.

GATED SOURCES ARE NEVER PUT ON A TIMER. Camera, screen, microphone and feeds are
expensive and intrusive; `MEMORY_ARCHITECTURE.md` says a cheap sensor must gate
them and that power is the constraint. `poll()` therefore refuses to run them,
structurally, rather than relying on nobody configuring a period.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import decision_path
from .world import UNKNOWN, Observation

# The five source classes, which differ by WHAT MAKES THEM HAPPEN -- and that is
# what decides the mechanism, not how the data looks when it arrives.
INTERRUPT = "interrupt"      # pushes, time-critical: a call, an SMS
QUEUE = "queue"              # pushes, not urgent: a file changed, mail
TIMER = "timer"              # cheap to check, polled: calendar, disk, reachability
GATED = "gated"              # expensive, needs a REASON: camera, screen, microphone
SWEEP = "sweep"              # nothing happens; time alone makes it true
SOURCE_CLASSES = (INTERRUPT, QUEUE, TIMER, GATED, SWEEP)

# Which classes may be polled on a schedule. GATED is absent ON PURPOSE and its
# absence is the enforcement: a camera or a microphone needs a REASON, and an
# interval is not a reason.
#
# SWEEP WAS ABSENT BY MISTAKE, and the mistake was lumping it in with GATED
# because both are "not TIMER". `MEMORY_ARCHITECTURE.md` is explicit that a
# sweep IS scheduled -- "no sensor exists; scheduled L2 query", "a scheduled
# query over VESPER's own memory ... seeded by time instead of by an utterance."
# The sweep row has no SENSOR because there is nothing to sense; it still has a
# PERIOD. Excluding it made `trg_fact_expiry_sweep` unreachable, which is the
# trigger whose whole class this is.
#
# INTERRUPT and QUEUE stay out because they are PUSHED. Polling for something
# that pushes is a second, slower path to the same event, and the two would
# disagree about when it happened.
POLLABLE = (TIMER, SWEEP)


class SensorRefused(Exception):
    """A sensor that cannot be registered, or a poll that must not happen."""


@dataclass(frozen=True, slots=True)
class Sensor:
    """`source -> probe -> cost -> period`. The verifier's row, plus a period."""

    name: str
    subject: str
    attribute: str
    probe: Callable[[], Any]
    source_class: str
    period_ms: int = 60_000
    # MEASURED, NOT DECLARED (`INV-HW-2`). Left None until something has timed
    # it; `poll()` records what each probe actually cost.
    cost_ms: float | None = None
    # How long a reading stays true. Absent means "until the next poll", which
    # is a different claim from "forever" and must not be confused with it.
    ttl_ms: int | None = None
    trust_class: str = "verified_local"

    def __post_init__(self) -> None:
        if self.source_class not in SOURCE_CLASSES:
            raise SensorRefused(
                f"{self.name}: unknown source class {self.source_class!r}. The "
                f"class decides the MECHANISM -- {SOURCE_CLASSES} -- and a "
                "sensor whose class is unknown would be scheduled by guesswork.")


@dataclass
class Discard:
    """What the filter dropped, and why. The miss log at a different layer."""

    sensor: str
    reason: str
    at_ms: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {"sensor": self.sensor, "reason": self.reason,
                "at_ms": round(self.at_ms, 1), "detail": self.detail}


class SensorRegistry:
    """One registry, two callers: the scheduler and the verifier."""

    def __init__(self, world: Any, clock: Any, *, bus: Any = None) -> None:
        self._world = world
        self._clock = clock
        self._bus = bus
        self._lock = threading.RLock()
        self._sensors: dict = {}
        self._last_run_ms: dict = {}
        self.discards: list = []

    def register(self, sensor: Sensor) -> None:
        with self._lock:
            if sensor.name in self._sensors:
                raise SensorRefused(f"{sensor.name} is already registered")
            self._sensors[sensor.name] = sensor

    def names(self) -> list:
        with self._lock:
            return sorted(self._sensors)

    # ------------------------------------------------------------- the probe

    def _run(self, sensor: Sensor) -> tuple:
        """Run one probe under the decision-path guard. Returns (value, ms).

        THE GUARD IS THE POINT OF THIS METHOD EXISTING. Every path into a probe
        goes through here, so there is one place the ban is applied rather than
        one per caller -- and a caller added later inherits it without knowing
        it exists.
        """
        started = time.perf_counter()
        try:
            with decision_path.entered(self._bus, f"sensor:{sensor.name}"):
                value = sensor.probe()
        except Exception as exc:                   # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000.0
            # UNKNOWN, NOT THE LAST READING. A stale value renders identically
            # to a fresh one and no predicate over it can tell the difference.
            self._discard(sensor.name, "probe_failed", repr(exc))
            return UNKNOWN, elapsed
        return value, (time.perf_counter() - started) * 1000.0

    def read(self, name: str) -> dict:
        """The VERIFIER's caller: probe now, on demand, before trusting a fact."""
        with self._lock:
            sensor = self._sensors.get(name)
        if sensor is None:
            raise SensorRefused(f"no sensor {name!r}")
        value, ms = self._run(sensor)
        return {"sensor": name, "subject": sensor.subject,
                "attribute": sensor.attribute, "value": value,
                "measured_ms": round(ms, 2), "known": value is not UNKNOWN}

    def poll(self, *, force: bool = False) -> dict:
        """The SCHEDULER's caller: run every due timer sensor, apply the results.

        GATED SOURCES ARE SKIPPED HERE STRUCTURALLY. A camera or a microphone on
        a timer is the design this layer exists to avoid, and refusing it in
        code is stronger than trusting that nobody sets a period.
        """
        now_ms = time.monotonic() * 1000.0
        applied, skipped = [], []
        with self._lock:
            sensors = list(self._sensors.values())
        for s in sensors:
            if s.source_class not in POLLABLE:
                skipped.append({"sensor": s.name, "class": s.source_class,
                                "why": ("only timer sources are polled; a gated "
                                        "source needs a reason, never an "
                                        "interval")})
                continue
            last = self._last_run_ms.get(s.name)
            if not force and last is not None and (now_ms - last) < s.period_ms:
                continue
            value, ms = self._run(s)
            self._last_run_ms[s.name] = now_ms
            if value is UNKNOWN:
                # NOT APPLIED. The world model's UNKNOWN comes from a fact
                # EXPIRING, and writing UNKNOWN as a value would make a failed
                # probe indistinguishable from a fact that timed out.
                applied.append({"sensor": s.name, "outcome": "unknown",
                                "measured_ms": round(ms, 2)})
                continue
            # ABSOLUTE, AND ON THE WORLD'S OWN CLOCK. `valid_until_ms` is a
            # STAMP, not a duration -- the first version of this line passed
            # `s.ttl_ms` straight through, so a sensor with a five-minute TTL
            # produced a fact stamped as expiring five minutes after the epoch.
            # Whether that read as "always expired" or "never expired" depended
            # on what clock the world model happened to be given, and both look
            # identical from outside.
            deadline = (self._world.now_ms() + s.ttl_ms
                        if s.ttl_ms is not None else None)
            obs = Observation(subject=s.subject, attribute=s.attribute,
                              value=value, observed_at_hlc=self._clock.now(),
                              source=f"sensor:{s.name}",
                              valid_until_ms=deadline,
                              trust_class=s.trust_class)
            res = self._world.apply(obs)
            applied.append({"sensor": s.name, "outcome": res.get("outcome", "applied"),
                            "value": value, "measured_ms": round(ms, 2)})
        out = {"applied": applied, "skipped": skipped,
               "discards": len(self.discards)}
        self._emit("sensors.polled", out)
        return out

    def _discard(self, sensor: str, reason: str, detail: str = "") -> None:
        d = Discard(sensor=sensor, reason=reason,
                    at_ms=time.monotonic() * 1000.0, detail=detail)
        self.discards.append(d)
        self._emit("sensors.discarded", d.to_dict())

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject="sensors", payload=payload,
                              component="sensors")
