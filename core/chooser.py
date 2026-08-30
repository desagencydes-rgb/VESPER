"""The chooser — deterministic first, a model only when the answer is ambiguous.

WHAT IT CHOOSES. `MEMORY_ARCHITECTURE.md`'s subsystem table has VESPER reaching
the gateway "via chooser": before each turn, something decides how hard this
request is and therefore which rung serves it. Today that is `classify()` alone,
and the table's own fallback column says so -- "falls back to today's
deterministic path".

THE SIGNAL IT NEEDS ALREADY EXISTS AND NOTHING READS IT. `Classification`
carries `confident: bool`, has since the classifier was written, and exactly one
thing in this repository branches on it: the CI check that asserts it is there.
The chooser is what makes it mean something.

A MODEL ON EVERY TURN IS THE THING BEING AVOIDED. "Ask a model how hard this is"
is one line, works, and puts a network call in front of every single utterance
including "hello" -- inside the latency path, on the owner's critical path,
paid for per token. The deterministic classifier answers confidently for
greetings, acknowledgements, long structured requests and anything carrying code
or a path. What reaches the model path is the honest middle, and only that.

THE ESCALATION MAY RAISE AND MAY NEVER LOWER, which is the same asymmetry
`core/effort.py` refuses to clamp and `CI-042` already gates in the classifier.
A request classified too HIGH costs a stronger rung. One classified too LOW gets
`low` reasoning effort and comes back confidently wrong -- and confidently wrong
is the failure mode this entire corpus is organised against. So a model that
answers "trivial" to something the deterministic floor called "moderate" is
overruled, and the overrule is recorded rather than silently applied.

THREE BUDGETS, AND THE THIRD IS NOT A TIMEOUT. Deterministic 10 ms, model
250 ms, and 600 ms is when VESPER SAYS something about the wait. They are
separate on purpose: announcing at 250 ms would make VESPER apologise constantly
for delays nobody perceives, and 600 ms is roughly where a pause stops reading
as thinking and starts reading as broken.

NOTHING HERE MAY FAIL A TURN. No escalator, a slow escalator, a raising
escalator, an escalator that returns nonsense -- every one of them falls back to
the deterministic answer, which was already computed and is already good enough
to route with. The chooser is an improvement on the floor, never a dependency of
it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .difficulty import DIFFICULTY, classify

# `MEMORY_ARCHITECTURE.md`'s budget table, and these are the numbers from it.
DETERMINISTIC_BUDGET_MS = 10
MODEL_BUDGET_MS = 250
ANNOUNCE_MS = 600

DETERMINISTIC = "deterministic"
ESCALATED = "escalated"
FELL_BACK = "fell_back"


@dataclass(frozen=True, slots=True)
class Choice:
    """One routing decision, and everything needed to audit it afterwards."""

    difficulty: str
    path: str
    signal: str
    elapsed_ms: float
    announce: bool = False
    floor: str = ""
    overruled: bool = False

    def to_dict(self) -> dict:
        return {"difficulty": self.difficulty, "path": self.path,
                "signal": self.signal, "elapsed_ms": round(self.elapsed_ms, 2),
                "announce": self.announce, "deterministic_floor": self.floor,
                "overruled_the_model": self.overruled,
                "budgets_ms": {"deterministic": DETERMINISTIC_BUDGET_MS,
                               "model": MODEL_BUDGET_MS,
                               "announce": ANNOUNCE_MS}}


class Chooser:
    """Routes a turn. Calls a model only when the deterministic path is unsure."""

    def __init__(self, *, escalate: Callable | None = None,
                 bus: Any = None) -> None:
        # INJECTED, NOT IMPORTED, for the same reason the updater's extractor
        # is: this is the only part that needs a model, and the module has to
        # be exercisable without a network to be gateable at all.
        self._escalate = escalate
        self._bus = bus

    def choose(self, text: str) -> Choice:
        started = time.perf_counter()
        c = classify(text)
        det_ms = (time.perf_counter() - started) * 1000.0

        # THE COMMON PATH ENDS HERE, WITH NO MODEL CALL. Greetings,
        # acknowledgements, anything carrying code or a path, anything long
        # enough to imply structure: all answered confidently and for free.
        if c.confident:
            return self._done(c.difficulty, DETERMINISTIC, c.signal, started,
                              floor=c.difficulty)

        if self._escalate is None:
            return self._done(c.difficulty, DETERMINISTIC,
                              f"{c.signal}; no escalator configured", started,
                              floor=c.difficulty)

        try:
            answer = self._escalate(text)
        except Exception as exc:                   # noqa: BLE001
            # A DEAD ESCALATOR IS NOT A DEAD TURN. The deterministic answer is
            # already computed and already routable; the escalation was an
            # improvement on it, never a dependency of it.
            self._emit("chooser.escalation_failed", {"error": repr(exc)})
            return self._done(c.difficulty, FELL_BACK,
                              f"{c.signal}; escalation failed: "
                              f"{type(exc).__name__}", started,
                              floor=c.difficulty)

        if answer not in DIFFICULTY:
            self._emit("chooser.escalation_unusable", {"answer": repr(answer)})
            return self._done(c.difficulty, FELL_BACK,
                              f"{c.signal}; escalator returned "
                              f"{answer!r}, which is not a difficulty", started,
                              floor=c.difficulty)

        # RAISE ONLY. A model answering "trivial" where the deterministic floor
        # said "moderate" is refused, not applied: too high costs a stronger
        # rung, too low gets `low` effort and a confidently wrong answer.
        if DIFFICULTY.index(answer) < DIFFICULTY.index(c.difficulty):
            self._emit("chooser.overruled", {"model_said": answer,
                                             "floor": c.difficulty})
            return self._done(c.difficulty, ESCALATED,
                              f"escalator said {answer!r}; refused as a "
                              f"downgrade below the deterministic floor "
                              f"{c.difficulty!r}", started,
                              floor=c.difficulty, overruled=True)

        return self._done(answer, ESCALATED,
                          f"{c.signal}; escalated to {answer!r}", started,
                          floor=c.difficulty)

    def _done(self, difficulty: str, path: str, signal: str, started: float, *,
              floor: str, overruled: bool = False) -> Choice:
        elapsed = (time.perf_counter() - started) * 1000.0
        choice = Choice(difficulty=difficulty, path=path, signal=signal,
                        elapsed_ms=elapsed, announce=elapsed >= ANNOUNCE_MS,
                        floor=floor, overruled=overruled)
        if choice.announce:
            # NOT A TIMEOUT AND NOT A CANCELLATION. The work continues; this
            # says the owner should be told it is still happening.
            self._emit("chooser.hold", choice.to_dict())
        self._emit("chooser.chose", choice.to_dict())
        return choice

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=payload.get("difficulty", "chooser"),
                              payload=payload, component="chooser")
