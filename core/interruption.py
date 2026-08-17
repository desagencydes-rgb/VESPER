"""Interruption budget — what may reach the owner, and what waits.

THE TWO RULES THAT ARE EASY TO GET BACKWARDS.

HIGH-VALUE NON-DECAYING ITEMS ARE QUEUED, NEVER DROPPED. The obvious budget
implementation drops whatever does not fit, which silently discards exactly the
things worth saying. If an item is valuable and does not go stale, running out
of budget is a reason to say it LATER, not a reason to never say it.

PREPARATION IS UNBUDGETED. The budget governs INTERRUPTIONS, not work. An
unbounded number of prepared-but-not-surfaced actions is permitted, and A-047
asserts that explicitly -- because a system that throttles its own preparation
to save interruption budget has confused thinking with talking.

ALARM CLASS BYPASSES THE BUDGET ENTIRELY. Not "gets a large allowance" --
bypasses. A budget that can suppress an alarm is a budget that will, on the
night it matters.

DECAY IS THE DISCRIMINATOR for what gets dropped. An item that decays is worth
less later, so when it does not fit and cannot wait, it is dropped and the drop
is RECORDED. An item that does not decay is worth the same tomorrow, so it
waits.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus

ATTENTION_STATES = ("available", "focused", "asleep", "away")
PERIODS = ("FREE_TIME", "DO_NOT_DISTURB", "IDLE", "ACTIVE_SESSION")

# Interruptions permitted per (period, attention_state). Alarm class ignores
# this table entirely.
BUDGET = {
    ("ACTIVE_SESSION", "available"): 6,
    ("ACTIVE_SESSION", "focused"): 1,
    ("IDLE", "available"): 3,
    ("IDLE", "focused"): 1,
    ("FREE_TIME", "available"): 1,
    ("FREE_TIME", "asleep"): 0,
    ("FREE_TIME", "away"): 0,
    ("DO_NOT_DISTURB", "available"): 0,
    ("DO_NOT_DISTURB", "focused"): 0,
    ("DO_NOT_DISTURB", "asleep"): 0,
}
DEFAULT_BUDGET = 0          # unlisted combinations are silent, not generous


@dataclass(slots=True)
class Candidate:
    candidate_id: str
    expected_value: float          # 0..1
    decays: bool
    interruption_cost: float       # 0..1
    is_alarm: bool = False
    prepared: bool = False

    def priority(self) -> float:
        return self.expected_value - self.interruption_cost


@dataclass(slots=True)
class BudgetOutcome:
    surfaced: list = field(default_factory=list)
    queued: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    prepared: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"surfaced": list(self.surfaced), "queued": list(self.queued),
                "dropped": list(self.dropped), "prepared": len(self.prepared)}


class InterruptionBudget:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: list = []
        self._lock = threading.RLock()

    def budget_for(self, period: str, attention: str) -> int:
        return BUDGET.get((period, attention), DEFAULT_BUDGET)

    def allocate(self, candidates: list, *, period: str,
                 attention_state: str) -> BudgetOutcome:
        budget = self.budget_for(period, attention_state)
        out = BudgetOutcome()

        # Alarms first and unconditionally -- they do not consume budget.
        for cand in candidates:
            if cand.is_alarm:
                out.surfaced.append(cand.candidate_id)
        remaining = budget

        ordered = sorted([c for c in candidates if not c.is_alarm],
                         key=lambda c: -c.priority())
        for cand in ordered:
            if cand.prepared:
                # Preparation is UNBUDGETED. Recorded so the count can be
                # asserted, never charged against the allowance.
                out.prepared.append(cand.candidate_id)
                continue
            if remaining > 0:
                out.surfaced.append(cand.candidate_id)
                remaining -= 1
            elif not cand.decays:
                # Worth the same tomorrow -> it waits.
                out.queued.append(cand.candidate_id)
                with self._lock:
                    self._queue.append(cand)
            else:
                # Worth less later and no room now -> dropped, and RECORDED.
                out.dropped.append(cand.candidate_id)

        self._bus.publish(
            "interruption.allocated", subject=f"{period}/{attention_state}",
            payload={"period": period, "attention_state": attention_state,
                     "budget": budget, **out.to_dict(),
                     "note": ("alarms bypass the budget entirely; preparation is "
                              "unbudgeted; high-value non-decaying items queue "
                              "rather than drop")},
            component="interruption")
        if out.dropped:
            self._bus.publish("interruption.dropped", subject="candidates",
                              payload={"dropped": out.dropped,
                                       "reason": "decaying and over budget"},
                              component="interruption")
        return out

    def surface_queued(self, *, boundary: str = "natural_interaction") -> list:
        """Queued items surface at the next natural interaction boundary."""
        with self._lock:
            items = [c.candidate_id for c in self._queue]
            self._queue.clear()
        if items:
            self._bus.publish("interruption.queue_surfaced", subject=boundary,
                              payload={"boundary": boundary, "items": items},
                              component="interruption")
        return items

    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)
