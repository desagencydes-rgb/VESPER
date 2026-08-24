"""Is this thread currently deciding whether to act? INV-AUTO-2's enforcement.

WHAT WAS WRONG, MEASURED 2026-08-24. `PredicateEvaluator`'s docstring says
INV-AUTO-2 is "enforced by what this class is not given" -- no gateway, no
router, no callable that could reach one. That is true of the EVALUATOR and not
true of the PREDICATE it runs, because a predicate is arbitrary caller-supplied
code and can close over anything in scope.

Demonstrated with a predicate that closed over a `ModelGateway` and asked it
"is there anything worth doing?":

    predicate fired             : True
    model calls that got through: 1
    violation events emitted    : 0

The trigger fired on a model's answer and nothing recorded that it happened.
`model_call_attempted` existed the whole time and was called by NOTHING outside
the acceptance tests; `in_decision_path()` was called by nothing at all. So
A-011.4's control proved the REPORTING MECHANISM works and proved nothing about
whether a real model call would reach it -- the same shape as A-022 asserting a
route decision the gateway then ignored.

WHY A THREAD-LOCAL AND NOT A PARAMETER. The gateway cannot take an evaluator
reference: `CI-023` forbids `core/autonomy.py` from importing the gateway, the
router or the context assembler, and the ban is the point -- the decision path
must have no way to reach a model capability. An argument threaded through every
call site would also be a thing to forget at exactly one of them. A leaf module
both sides import couples neither to the other.

WHY IT IS THREAD-LOCAL AND NOT GLOBAL. A background thread legitimately calling
a model while a predicate happens to be evaluating on another thread is not a
violation, and blocking it would be a deadlock dressed as a safety property.
The question is whether THIS thread is inside a decision.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any

_state = threading.local()


class ModelCallInDecisionPath(Exception):
    """A model capability was reached from inside a predicate evaluation."""


def active() -> bool:
    return bool(getattr(_state, "depth", 0))


def where() -> str:
    return getattr(_state, "where", "unknown")


@contextmanager
def entered(bus: Any, site: str):
    """Mark this thread as deciding. Re-entrant, and always restores.

    Depth-counted rather than a boolean: a predicate that evaluates another
    predicate would otherwise clear the flag on the inner exit and leave the
    outer decision unprotected for the rest of its run.
    """
    depth = getattr(_state, "depth", 0)
    prev_bus = getattr(_state, "bus", None)
    prev_where = getattr(_state, "where", None)
    _state.depth = depth + 1
    _state.bus = bus
    _state.where = site
    try:
        yield
    finally:
        _state.depth = depth
        _state.bus = prev_bus
        _state.where = prev_where


def refuse(attempted_from: str) -> None:
    """Emit AND raise. A-011.4 requires both.

    Emitting without raising leaves a build that logs its own violation and
    carries on, which is the failure that requirement names. Raising without
    emitting leaves a violation nobody can audit afterwards.
    """
    bus = getattr(_state, "bus", None)
    if bus is not None:
        bus.publish(
            "autonomy.model_call_in_decision_path", subject=attempted_from,
            payload={"where": attempted_from, "decision_site": where(),
                     "note": ("INV-AUTO-2: the decision to act is made by "
                              "predicates over world state, never by asking a "
                              "model. A loop that asks 'is there anything "
                              "worth doing?' is a chatbot talking to itself.")},
            component="autonomy")
    raise ModelCallInDecisionPath(
        f"a model call was attempted from {attempted_from!r} while this thread "
        f"was inside {where()!r}. The decision to act may not be made by asking "
        "a model (INV-AUTO-2), and this call is refused rather than counted.")
