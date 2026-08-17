"""Taint and the context ceiling — INV-AUTH-3, INV-AUTH-6, INV-AUTH-7.

THE SENTENCE THE WHOLE DEFENCE RESTS ON, quoted from REM-003 4.4:

    "Taint propagates through summarisation, embedding, and cache reuse. A
    summary of tainted content is tainted. This single sentence is the whole
    defence, and it is the one an implementation will omit, because
    summarisation naturally produces a clean-looking new string."

That is why `summarise` and `cache_get` live in THIS module rather than in a
text-processing one. A summariser that returns a plain string has already lost
the taint — not through malice but through the ordinary shape of the operation,
which takes tainted input and produces new text with no obvious owner. Here the
return type is `Tainted`, so losing the taint requires deliberately unwrapping
it, and A-025's mandatory control is a summariser that does exactly that.

SECOND-ORDER PROPAGATION IS THE CASE THAT ACTUALLY BITES (A-025.8). A cache
holding "the summary of page X" looks like clean local data on the second read.
The cache stores the `Tainted` wrapper, not the string.

ABOVE-CEILING IS NOT A SILENT DROP. An action above the ceiling becomes a
QUEUED PROPOSAL requiring owner confirmation, and emits
`security.injection_suspected`. Dropping it silently would violate RB-022 (no
silent capability loss) and would hide the control in precisely the case where
the owner needs to see it.

INV-AUTH-6: THE PLANNER CONTEXT NEVER INGESTS RAW EXTERNAL TEXT. External
content goes to an EXTRACTION context capped at L1 with no state-changing
tools, whose output must validate against a schema. The planner receives typed,
schema-validated data — still tainted, but structured. `assert_planner_clean`
makes that assertion checkable rather than aspirational.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus
from .capability import LEVEL_RANK, LEVELS

# REM-003 4.4. Ceiling per trust class for STATE-CHANGING capabilities.
ALLOWED_LEVEL = {
    "system": "L5",
    "owner": "L5",
    "verified_local": "L4",
    "retrieved_local": "L3",
    "model_generated": "L2",
    "retrieved_external": "L1",
}
# The class that must never reach the planner context (INV-AUTH-6).
EXTERNAL = "retrieved_external"


@dataclass(frozen=True, slots=True)
class Tainted:
    """A value that carries its trust class with it.

    Deliberately not a `str` subclass. A `str` subclass survives `str(x)` and
    `x + y` and f-strings by silently degrading to a plain `str`, which is the
    exact leak this type exists to prevent. Getting the text out requires
    `.value`, which is a visible act.
    """

    value: Any
    trust_class: str
    origin: str = ""
    derived_from: tuple = ()

    def ceiling(self) -> str:
        return ALLOWED_LEVEL.get(self.trust_class, "L0")

    def to_dict(self) -> dict:
        return {"trust_class": self.trust_class, "origin": self.origin,
                "derived_from": list(self.derived_from),
                "ceiling": self.ceiling()}


def _weakest(classes: list) -> str:
    """The lowest-trust class present. Taint is contagious, not averaged."""
    if not classes:
        return "system"
    return min(classes, key=lambda c: LEVEL_RANK.get(ALLOWED_LEVEL.get(c, "L0"), 0))


def summarise(inputs: list, summariser: Callable[[list], Any], *,
              origin: str = "summary") -> Tainted:
    """Summarise, PRESERVING taint (A-025.7).

    The summariser sees plain values and returns a plain value; this wrapper is
    what keeps the result honest. A summary of tainted content is tainted, and
    the trust class of the result is the WEAKEST of its inputs -- not the
    average and not the majority, because one hostile input is enough.
    """
    texts = [i.value if isinstance(i, Tainted) else i for i in inputs]
    classes = [i.trust_class for i in inputs if isinstance(i, Tainted)]
    out = summariser(texts)
    return Tainted(value=out, trust_class=_weakest(classes), origin=origin,
                   derived_from=tuple(
                       i.origin for i in inputs if isinstance(i, Tainted)))


class TaintedCache:
    """A cache that stores the wrapper, not the string (A-025.8).

    Second-order propagation is the case an ordinary cache loses: the value
    goes in tainted and comes out looking like clean local data because the
    cache's own return type is `str`.
    """

    def __init__(self) -> None:
        self._d: dict[str, Tainted] = {}
        self._lock = threading.RLock()

    def put(self, key: str, value: Tainted) -> None:
        if not isinstance(value, Tainted):
            raise TypeError(
                "TaintedCache stores Tainted values only. Storing a bare value "
                "would launder its trust class on the next read, which is "
                "A-025.8 exactly.")
        with self._lock:
            self._d[key] = value

    def get(self, key: str) -> Tainted | None:
        with self._lock:
            return self._d.get(key)


class ContextCeiling:
    """Computes the ceiling and handles the above-ceiling path."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.proposals: list[dict] = []

    def ceiling(self, fragments: list) -> str:
        """min over all fragments of allowed_level(trust_class)."""
        if not fragments:
            return "L5"
        return min((f.ceiling() for f in fragments),
                   key=lambda l: LEVEL_RANK[l])

    def check(self, requested_level: str, fragments: list, *,
              capability_id: str, subject: str = "action") -> dict:
        """Returns a decision. Above the ceiling becomes a PROPOSAL, not a drop."""
        ceil = self.ceiling(fragments)
        if LEVEL_RANK[requested_level] <= LEVEL_RANK[ceil]:
            return {"allowed": True, "ceiling": ceil,
                    "effective_level": requested_level}

        has_external = any(f.trust_class == EXTERNAL for f in fragments)
        proposal = {
            "capability_id": capability_id,
            "requested_level": requested_level,
            "context_ceiling": ceil,
            "requires_owner_confirmation": True,
            "reason": (f"requested {requested_level} exceeds the context ceiling "
                       f"{ceil} set by the weakest fragment in context"),
        }
        self.proposals.append(proposal)
        # RB-022: not silently dropped. Queued as a proposal AND reported.
        self._bus.publish("security.above_ceiling_proposal", subject=subject,
                          payload=proposal, component="taint")
        if has_external:
            self._bus.publish(
                "security.injection_suspected", subject=subject,
                payload={"capability_id": capability_id,
                         "requested_level": requested_level,
                         "context_ceiling": ceil,
                         "external_fragments": [f.origin for f in fragments
                                                if f.trust_class == EXTERNAL],
                         "note": ("an action above the ceiling was requested while "
                                  "externally-retrieved content is in context. "
                                  "Asking for a SMALL action does not bypass the "
                                  "ceiling -- see A-025.9.")},
                component="taint")
        return {"allowed": False, "ceiling": ceil, "proposal": proposal,
                "effective_level": ceil}

    def assert_planner_clean(self, planner_fragments: list, *,
                             subject: str = "planner") -> bool:
        """INV-AUTH-6: zero `retrieved_external` fragments in planner context.

        The two-context pattern is architectural rather than optional: external
        content is read in an EXTRACTION context capped at L1, and only
        schema-validated structured data crosses into the planner. This makes
        the crossing checkable.
        """
        bad = [f for f in planner_fragments if f.trust_class == EXTERNAL]
        if bad:
            self._bus.publish(
                "security.planner_context_contaminated", subject=subject,
                payload={"fragments": [f.origin for f in bad],
                         "note": ("INV-AUTH-6: the planner context never ingests "
                                  "raw external text. External content belongs in "
                                  "the extraction context, whose output must "
                                  "validate against a schema before crossing.")},
                component="taint")
            return False
        return True
