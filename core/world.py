"""World model — facts that expire to UNKNOWN, conflicts that are never resolved silently.

FOUR INVARIANTS, and each of them is a place where the obvious implementation is
wrong in a way that only shows up months later.

INV-COORD-1: NO FACT MAY BE APPLIED OUT OF HLC ORDER. A write whose
`observed_at_hlc <= current` is REJECTED and the rejection is emitted. The
obvious implementation is last-write-wins on arrival, which silently applies a
stale observation over a fresh one whenever the network reorders two packets --
and nothing throws, the world model is simply wrong afterwards.

INV-COORD-2: NO EXPIRED FACT MAY BE READ AS CURRENT. Past `valid_until` the only
readable value is UNKNOWN. Not "the last known value with a staleness warning" --
UNKNOWN. A-033.3 partitions a node for two hours and asserts that every fact past
its TTL reads UNKNOWN and *none reads its last value*. The distinction matters
because a trigger evaluating "is the owner home" gets a definite wrong answer
from a stale fact and a correct "I don't know" from an expired one, and only the
second is safe to act on.

INV-COORD-3: NO CONFLICT MAY BE RESOLVED WITHOUT AN EMITTED `world.conflict`.
Two sources disagreeing is information, not noise. A-033.4 asserts that on a
contradiction **no attribute value changes** and the reader receives CONFLICTED.
Picking a winner -- by recency, by confidence, by source rank -- destroys the
one signal that says the model does not know.

INV-WORLD-1: AN UNKNOWN PERSON IS NEVER RESOLVED TO THE OWNER. The nearest-match
identification that every face-recognition pipeline does by default is exactly
this failure, and its consequence is routing private content to a stranger.

INV-WORLD-2: SPATIAL PLACEMENT IS TOPOLOGICAL. `kitchen adjacent_to hallway`,
never `(3.2m, 1.4m)`. No subsystem may require metric coordinates, because the
moment one does, every room needs surveying and the model stops working in a
house nobody measured.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus
from .hlc import HLC, HybridLogicalClock

UNKNOWN = "UNKNOWN"
CONFLICTED = "CONFLICTED"

# INV-WORLD-2. Topological relations only -- no distances, no coordinates.
SPATIAL_RELATIONS = ("adjacent_to", "contains", "connects_to", "same_as")

# A person the system has not identified. NEVER collapses to the owner.
UNKNOWN_PERSON = "unknown_person"


@dataclass(frozen=True, slots=True)
class Observation:
    """One source's claim about one attribute of one subject."""

    subject: str
    attribute: str
    value: Any
    observed_at_hlc: HLC
    source: str
    confidence: float = 1.0
    # Wall-clock milliseconds after which this reads UNKNOWN. TTL is a duration
    # question, so it is answered on a duration clock, not on the HLC -- the gap
    # between two HLC stamps is not a number of seconds.
    valid_until_ms: int | None = None
    trust_class: str = "verified_local"

    def to_dict(self) -> dict:
        return {"subject": self.subject, "attribute": self.attribute,
                "value": self.value, "source": self.source,
                "confidence": self.confidence,
                "observed_at_hlc": self.observed_at_hlc.to_dict(),
                "valid_until_ms": self.valid_until_ms,
                "trust_class": self.trust_class}


@dataclass(slots=True)
class Fact:
    subject: str
    attribute: str
    value: Any
    observed_at_hlc: HLC
    source: str
    confidence: float
    valid_until_ms: int | None
    conflicting: tuple = ()

    def to_dict(self) -> dict:
        return {"subject": self.subject, "attribute": self.attribute,
                "value": self.value, "source": self.source,
                "confidence": self.confidence,
                "observed_at_hlc": self.observed_at_hlc.to_dict(),
                "valid_until_ms": self.valid_until_ms,
                "conflicting_sources": list(self.conflicting)}


class WorldModel:
    """Current beliefs, with expiry and conflict as first-class outcomes."""

    def __init__(self, bus: EventBus, clock: HybridLogicalClock, *,
                 now_ms: Any = None) -> None:
        self._bus = bus
        self._clock = clock
        self._now_ms = now_ms or (lambda: 0)
        self._facts: dict[tuple, Fact] = {}
        self._topology: dict[str, set] = {}
        self._lock = threading.RLock()
        self.rejected_writes = 0
        self.duplicate_writes = 0

    # ------------------------------------------------------------------ write

    def apply(self, obs: Observation) -> dict:
        """Apply an observation, or reject it. Never silently overwrites."""
        key = (obs.subject, obs.attribute)
        with self._lock:
            cur = self._facts.get(key)

            # INV-COORD-1. Ordering is HLC-only; arrival order is not consulted.
            if cur is not None and obs.observed_at_hlc <= cur.observed_at_hlc:
                self.rejected_writes += 1
                self._bus.publish(
                    "world.write_rejected", subject=obs.subject,
                    payload={"attribute": obs.attribute, "source": obs.source,
                             "offered_hlc": obs.observed_at_hlc.to_dict(),
                             "current_hlc": cur.observed_at_hlc.to_dict(),
                             "reason": ("INV-COORD-1: observed_at_hlc <= current. "
                                        "State is unchanged. Arrival order is not "
                                        "consulted -- only HLC.")},
                    component="world")
                return {"applied": False, "reason": "stale_hlc",
                        "value": self._read_value(cur)}

            # INV-COORD-3. A live disagreement is not resolved here.
            if (cur is not None and not self._expired(cur)
                    and cur.source != obs.source and cur.value != obs.value):
                conflicting = tuple(sorted({cur.source, obs.source}))
                cur.conflicting = conflicting
                self._bus.publish(
                    "world.conflict", subject=obs.subject,
                    payload={"attribute": obs.attribute,
                             "sources": list(conflicting),
                             "values": [cur.value, obs.value],
                             "resolution": "NONE -- no attribute value changed",
                             "reader_receives": CONFLICTED,
                             "note": ("picking a winner by recency, confidence or "
                                      "source rank destroys the one signal that "
                                      "says the model does not know")},
                    component="world")
                return {"applied": False, "reason": "conflict",
                        "value": CONFLICTED}

            self._facts[key] = Fact(
                subject=obs.subject, attribute=obs.attribute, value=obs.value,
                observed_at_hlc=obs.observed_at_hlc, source=obs.source,
                confidence=obs.confidence, valid_until_ms=obs.valid_until_ms)

        self._bus.publish("world.fact_updated", subject=obs.subject,
                          payload=obs.to_dict(), component="world")
        return {"applied": True, "value": obs.value}

    # ------------------------------------------------------------------- read

    def _expired(self, f: Fact) -> bool:
        return f.valid_until_ms is not None and self._now_ms() >= f.valid_until_ms

    def _read_value(self, f: Fact) -> Any:
        if f.conflicting:
            return CONFLICTED
        # INV-COORD-2. The last known value is NOT offered as a fallback.
        if self._expired(f):
            return UNKNOWN
        return f.value

    def read(self, subject: str, attribute: str) -> Any:
        with self._lock:
            f = self._facts.get((subject, attribute))
        if f is None:
            return UNKNOWN
        return self._read_value(f)

    def read_detail(self, subject: str, attribute: str) -> dict:
        with self._lock:
            f = self._facts.get((subject, attribute))
        if f is None:
            return {"value": UNKNOWN, "reason": "no observation"}
        v = self._read_value(f)
        d = {"value": v, **f.to_dict()}
        if v == UNKNOWN and f.valid_until_ms is not None:
            d["reason"] = (f"expired at {f.valid_until_ms}; INV-COORD-2 forbids "
                           "reading the last known value")
        elif v == CONFLICTED:
            d["reason"] = "sources disagree; no value was picked"
        return d

    def sweep_expired(self) -> list:
        """Report which facts have expired. Does NOT delete them.

        The record of what was believed and when it lapsed is evidence; deleting
        it would make "why did the system stop knowing this" unanswerable.
        """
        out = []
        with self._lock:
            for (subj, attr), f in self._facts.items():
                if self._expired(f):
                    out.append({"subject": subj, "attribute": attr,
                                "reads_as": UNKNOWN,
                                "last_value_not_offered": True})
        if out:
            self._bus.publish("world.facts_expired", subject="world",
                              payload={"count": len(out), "facts": out},
                              component="world")
        return out

    # ------------------------------------------------------------- identity

    def identify_person(self, candidates: list) -> str:
        """INV-WORLD-1: an unknown person is NEVER resolved to the owner.

        `candidates` is a list of (person_id, confidence). The nearest-match
        behaviour every recognition pipeline does by default is exactly the
        failure this prevents, and its consequence is routing private content
        to a stranger. A weak match is not a match.
        """
        MATCH_FLOOR = 0.95
        strong = [(p, c) for p, c in candidates if c >= MATCH_FLOOR]
        if len(strong) == 1:
            return strong[0][0]
        if candidates:
            self._bus.publish(
                "world.person_unresolved", subject="identity",
                payload={"candidates": [{"person": p, "confidence": c}
                                        for p, c in candidates],
                         "resolved_to": UNKNOWN_PERSON,
                         "match_floor": MATCH_FLOOR,
                         "note": ("INV-WORLD-1: a weak or ambiguous match resolves "
                                  "to unknown_person, never to the owner. Nearest "
                                  "match is how private content reaches a stranger.")},
                component="world")
        return UNKNOWN_PERSON

    # ------------------------------------------------------------- topology

    def relate(self, a: str, relation: str, b: str) -> None:
        """INV-WORLD-2: topological only. No coordinates, no distances."""
        if relation not in SPATIAL_RELATIONS:
            raise ValueError(
                f"relation {relation!r} not in {SPATIAL_RELATIONS}. Spatial "
                "placement is TOPOLOGICAL -- the moment a subsystem needs metric "
                "coordinates, every room needs surveying and the model stops "
                "working in a house nobody measured.")
        with self._lock:
            self._topology.setdefault(a, set()).add((relation, b))
            if relation in ("adjacent_to", "connects_to", "same_as"):
                self._topology.setdefault(b, set()).add((relation, a))

    def related(self, a: str) -> list:
        with self._lock:
            return sorted(self._topology.get(a, set()))
