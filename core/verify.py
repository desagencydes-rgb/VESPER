"""Verification — and the refusal to let repetition become success (A-023).

THE FAILURE THIS PREVENTS HAS A NAME: retry-until-agreement. Run a flaky
verifier enough times and one run will pass; accept that run and the system has
learned to keep rolling until it likes the answer. It looks like persistence
and it is actually a system that cannot fail. A-023 runs the same task 20 times
and asserts it NEVER reaches SUCCEEDED, because the output is genuinely wrong
every time and a verifier that eventually agrees is broken.

The defence is structural, not statistical. A verdict is bound to the OUTPUT it
judged, by hash. Re-running against unchanged output returns the CACHED
verdict, so repetition cannot produce a new opinion. To get a different verdict
you have to produce different work -- which is the whole point.

INV-VERIF-3 / A-023.4: `self_model` is never reported as accepted. A model
judging its own output is the single least reliable verifier available, and
allowing it as an acceptance route would make every other verifier optional.
It may be RECORDED -- its opinion is evidence -- but it cannot close a task.

A-023.5: in FREE_TIME a task whose acceptance condition is not machine-checkable
is DEFERRED, not completed. The alternative is a system that marks unverifiable
work done while nobody is watching, which is precisely when nobody would notice.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus

# contracts/entities/task.schema.json verified_by
STRATEGIES = ("deterministic", "retrieval_grounded", "model_critic",
              "self_model", "human", "deferred", "none_declared")

# INV-VERIF-3. These may produce a verdict that is RECORDED as evidence, but
# they can never close a task.
NEVER_ACCEPTS = ("self_model", "none_declared", "deferred")

# Machine-checkable strategies. Anything else needs a human, and in FREE_TIME
# that means deferral rather than completion.
MACHINE_CHECKABLE = ("deterministic", "retrieval_grounded")


class VerifierDisagreement(Exception):
    """Verifiers disagreed. Preserved as evidence, never averaged away."""


@dataclass(frozen=True, slots=True)
class Verdict:
    strategy: str
    passed: bool
    detail: str
    output_hash: str
    can_accept: bool

    def to_dict(self) -> dict:
        return {"strategy": self.strategy, "passed": self.passed,
                "detail": self.detail, "output_hash": self.output_hash,
                "can_accept": self.can_accept}


def output_hash(output: Any) -> str:
    return hashlib.sha256(
        json.dumps(output, sort_keys=True, default=str).encode()).hexdigest()[:32]


class Verifier:
    """Runs verification strategies and remembers what it already judged."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._strategies: dict[str, Callable[[Any, dict], tuple[bool, str]]] = {}
        # (task_id, strategy, output_hash) -> Verdict. THE anti-repetition
        # mechanism: a verdict is bound to the output it judged.
        self._cache: dict[tuple, Verdict] = {}
        self._attempts: dict[str, int] = {}
        self._lock = threading.RLock()

    def register(self, strategy: str,
                 fn: Callable[[Any, dict], tuple[bool, str]]) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}, expected {STRATEGIES}")
        self._strategies[strategy] = fn

    def verify(self, task_id: str, output: Any, criteria: dict) -> Verdict:
        strategy = criteria.get("kind")
        if strategy not in STRATEGIES:
            raise ValueError(
                f"verification_criteria.kind must be one of {STRATEGIES}, got "
                f"{strategy!r}. Criteria are TYPED, never free text.")
        h = output_hash(output)
        key = (task_id, strategy, h)

        with self._lock:
            self._attempts[task_id] = self._attempts.get(task_id, 0) + 1
            attempt = self._attempts[task_id]
            cached = self._cache.get(key)

        if cached is not None:
            # Repetition against unchanged output returns the SAME verdict.
            self._bus.publish("verify.repeat_suppressed", subject=task_id,
                              payload={"task_id": task_id, "attempt": attempt,
                                       "output_hash": h,
                                       "verdict": cached.to_dict(),
                                       "reason": ("a verdict is bound to the output "
                                                  "it judged. Re-running unchanged "
                                                  "work cannot buy a new opinion -- "
                                                  "that is retry-until-agreement.")},
                              component="verify")
            return cached

        fn = self._strategies.get(strategy)
        if fn is None:
            passed, detail = False, f"no verifier registered for {strategy!r}"
        else:
            try:
                passed, detail = fn(output, criteria)
            except Exception as e:  # noqa: BLE001
                passed, detail = False, f"verifier raised {type(e).__name__}: {e}"

        # INV-VERIF-3: some strategies can never close a task, whatever they say.
        can_accept = passed and strategy not in NEVER_ACCEPTS
        v = Verdict(strategy, passed, detail, h, can_accept)
        with self._lock:
            self._cache[key] = v

        self._bus.publish("verify.verdict", subject=task_id,
                          payload={"task_id": task_id, "attempt": attempt,
                                   **v.to_dict()},
                          component="verify")
        if passed and not can_accept:
            self._bus.publish(
                "verify.accept_refused", subject=task_id,
                payload={"task_id": task_id, "strategy": strategy,
                         "reason": (f"{strategy!r} may be recorded as evidence but "
                                    "can never close a task (INV-VERIF-3). A model "
                                    "judging its own output would make every other "
                                    "verifier optional.")},
                component="verify")
        return v

    def cross_check(self, task_id: str, output: Any,
                    criteria_list: list[dict]) -> list[Verdict]:
        """Run several strategies. Disagreement is PRESERVED, never averaged.

        A majority vote across verifiers would turn a real disagreement into a
        number, and the disagreement is the finding: it says the acceptance
        condition is ambiguous, which is information no average carries.
        """
        verdicts = [self.verify(task_id, output, c) for c in criteria_list]
        if len({v.passed for v in verdicts}) > 1:
            self._bus.publish(
                "verify.disagreement", subject=task_id,
                payload={"task_id": task_id,
                         "verdicts": [v.to_dict() for v in verdicts],
                         "resolution": "PRESERVED as evidence; task is BLOCKED",
                         "note": ("not averaged and not majority-voted -- the "
                                  "disagreement itself is the finding")},
                component="verify")
        return verdicts

    def attempts(self, task_id: str) -> int:
        return self._attempts.get(task_id, 0)

    def should_defer(self, criteria: dict, period: str) -> bool:
        """A-023.5: unverifiable work in FREE_TIME is deferred, not completed."""
        return (period == "FREE_TIME"
                and criteria.get("kind") not in MACHINE_CHECKABLE)
