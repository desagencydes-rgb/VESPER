"""A-029's three parts, defined once, asserted identically by both drivers.

WHY THIS MODULE EXISTS. A-029 now has two drivers: the compressed one in
`run_f5_acceptance.py` (simulated clock, fast, runs in CI) and the real-time one
in `run_a029_endurance.py` (24 h of wall clock, run by hand). The obvious way to
build the second is to copy the first and change the clock -- and then the gate
has two definitions that agree today and drift apart at the first amendment.
Worse, the drift would be invisible: both would keep printing PASS.

So the assertions live here and the drivers supply evidence. A driver decides
HOW the window is produced; this module decides WHAT makes it a pass. An
amendment lands in one place or it lands wrong.

The evidence a driver must produce is deliberately primitive -- lists of
heartbeats, fired actions and no-ops, plus counted events -- because anything
richer would let a driver hand in its own conclusions. A checker that reads a
driver's summary is checking the driver, which is failure mode #4 from the
2026-08-15 report: a comparison against the artifact it just produced.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Protocol

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.autonomy import Trigger  # noqa: E402
from core.world import UNKNOWN  # noqa: E402

# The A-029 Part 3 fixture, fixed by the protocol text itself:
# `world.workshop_space.temperature = 31.4 C` against a `> 30` predicate.
SUBJECT = "world.workshop_space"
ATTRIBUTE = "temperature"
TERM = f"{SUBJECT}.{ATTRIBUTE}"
INJECTED_VALUE = 31.4
TRIGGER_ID = "trg_workshop_overheat"

# Part 3.4: "fires within <= 2 x tick_interval of T".
FIRE_TOLERANCE_TICKS = 2
# INV-AUTO-1: "absence beyond 3x tick_interval is an incident".
GAP_FACTOR = 3
# Part 1 counts heartbeats against an expected cadence. Real time jitters and
# simulated time does not, so the tolerance is a parameter with a strict
# default rather than a constant generous enough to cover both.
DEFAULT_COUNT_TOLERANCE = 0.0


class Checker(Protocol):
    def check(self, name: str, passed: bool, detail: str = "") -> bool: ...


def temperature_trigger() -> Trigger:
    """The A-029 Part 3 trigger, registered BEFORE the run.

    STATE-class: `temperature > 30 AND NOT is_unknown(temperature)`. With the
    fact absent or expired it is false at every instant of every day, which is
    what makes it a state trigger rather than a schedule.
    """
    def predicate(s: dict) -> bool:
        t = s.get(TERM)
        if t is UNKNOWN or t is None or t is False:
            return False
        try:
            return float(t) > 30.0
        except (TypeError, ValueError):
            return False

    return Trigger(TRIGGER_ID, "STATE", predicate, state_terms=(TERM,))


# ===========================================================================
# Part 1 — liveness
# ===========================================================================

def check_part1(c: Checker, *, heartbeats: list, tick_interval_ms: float,
                window_ms: float, stalled_events: int,
                count_tolerance: float = DEFAULT_COUNT_TOLERANCE,
                window_start_ms: float = 0.0) -> None:
    """`autonomy.heartbeat` at the declared cadence for the WHOLE window.

    Four assertions, and the reason there are four rather than one: a count
    alone passes for a loop that ticked twice as fast for half the window; a
    gap check alone passes for a loop that stopped one tick in; a span check
    alone passes for a loop that ticked at each end and slept in the middle.
    Each covers the others' blind spot.
    """
    ats = [h["at_ms"] for h in heartbeats]
    expected = int(round(window_ms / tick_interval_ms)) if tick_interval_ms else 0
    limit = GAP_FACTOR * tick_interval_ms
    end_ms = window_start_ms + window_ms

    c.check("Part 1 heartbeats are present at all",
            bool(ats), f"{len(ats)} heartbeats")

    gaps = [ats[i + 1] - ats[i] for i in range(len(ats) - 1)]
    c.check("Part 1 no gap exceeds 3 x tick_interval",
            bool(gaps) and all(g <= limit for g in gaps),
            f"max gap {max(gaps) if gaps else 'n/a'} ms against a {limit} ms limit")

    # The window is covered at BOTH ends. This is what C4 (silent death at the
    # midpoint) fails and a gap check alone would not catch until the very last
    # gap -- which a driver that simply stops recording never produces.
    covered = (bool(ats) and (ats[0] - window_start_ms) <= limit
               and (end_ms - ats[-1]) <= limit)
    c.check("Part 1 heartbeats span the whole window, both ends",
            covered,
            f"first at {ats[0] if ats else 'n/a'}, last at {ats[-1] if ats else 'n/a'}, "
            f"window {window_start_ms}..{end_ms} ms")

    slack = max(1, int(expected * count_tolerance))
    c.check("Part 1 the heartbeat count matches the declared cadence",
            expected and abs(len(ats) - expected) <= slack,
            f"{len(ats)} heartbeats, expected ~{expected} (+/-{slack})")

    c.check("Part 1 autonomy.loop_stalled never fires",
            stalled_events == 0, f"{stalled_events} stall episodes")


# ===========================================================================
# Part 2 — provenance
# ===========================================================================

def check_part2(c: Checker, *, actions: list, registered_ids: set,
                replay: Callable[[dict], bool], noops: list) -> None:
    """100% of actions resolve to exactly one registered trigger_id.

    `replay` re-evaluates a fired action's predicate against its own
    reconstructed snapshot. It is passed in rather than read off the action,
    because an action that carried its own verdict would be attesting to
    itself.
    """
    c.check("Part 2 at least one action was taken to have provenance for",
            bool(actions), f"{len(actions)} actions")
    c.check("Part 2 100% of actions resolve to exactly one registered trigger_id",
            bool(actions) and all(a.get("trigger_id") in registered_ids
                                  for a in actions),
            str(sorted({a.get("trigger_id") for a in actions})))
    c.check("Part 2 each predicate re-evaluates true against its snapshot",
            bool(actions) and all(replay(a) for a in actions))
    c.check("Part 2 at least one recorded no-op carries a trigger_id",
            bool(noops) and all(n.get("trigger_id") for n in noops),
            f"{len(noops)} recorded no-ops")


# ===========================================================================
# Part 3 — the anti-cron discriminator
# ===========================================================================

def check_part3(c: Checker, *, runs: list, model_call_events: int) -> None:
    """THE DISCRIMINATOR. `runs` is one record per independent draw of T.

    Each record: `{"T": <tick>, "delta_ticks": int|None, "action": dict|None}`.
    `delta_ticks` is measured from the injection, not claimed by the driver.

    A build can be perfectly live and perfectly provenanced and still be cron
    wearing autonomy's vocabulary. Only this part tells them apart, which is
    why C1 must fail HERE and pass parts 1 and 2.
    """
    deltas = [r["delta_ticks"] for r in runs]
    acts = [r["action"] for r in runs]

    c.check("Part 3.4 every independent draw of T produced a firing",
            bool(runs) and all(d is not None for d in deltas), str(deltas))
    c.check(f"Part 3.4 each fired within {FIRE_TOLERANCE_TICKS} x tick_interval of T",
            bool(runs) and all(d is not None and d <= FIRE_TOLERANCE_TICKS
                               for d in deltas), str(deltas))
    c.check("Part 3.5 the fired trigger_id resolves to the STATE-class trigger",
            bool(acts) and all(a and a.get("trigger_id") == TRIGGER_ID
                               for a in acts),
            str([a.get("trigger_id") if a else None for a in acts]))
    c.check("Part 3.5 and its predicate_class is STATE",
            bool(acts) and all(a and a.get("predicate_class") == "STATE"
                               for a in acts),
            str([a.get("predicate_class") if a else None for a in acts]))
    c.check("Part 3.6 the reconstructed snapshot contains the injected fact",
            bool(acts) and all(a and a.get("snapshot", {}).get(TERM)
                               == INJECTED_VALUE for a in acts))
    c.check("Part 3.7 autonomy.model_call_in_decision_path did NOT fire",
            model_call_events == 0, f"{model_call_events} events")
    c.check("Part 3 NOT every fired trigger is SCHEDULE-class",
            bool(acts) and not all(a and a.get("predicate_class") == "SCHEDULE"
                                   for a in acts),
            "every firing was SCHEDULE-class -- this build is cron wearing "
            "autonomy's vocabulary")


def part3_run_record(T: Any, injected_at: Any, action: dict | None) -> dict:
    """Build one Part 3 record. `delta_ticks` is derived here, once."""
    delta = None
    if action is not None and injected_at is not None:
        delta = action["tick"] - injected_at
    return {"T": T, "injected_at": injected_at, "delta_ticks": delta,
            "action": action}
