"""Hybrid logical clock — the ONLY ordering input in VESPER (INV-COORD-4).

WHY A HYBRID CLOCK AND NOT A TIMESTAMP. Wall clock is unusable for ordering:
it jumps backwards on NTP correction, it drifts between nodes, and two nodes
can genuinely disagree about "now" by minutes. A system that orders on wall
clock silently applies a stale write over a fresh one whenever a clock is
wrong, and that failure is invisible -- nothing throws, the data is simply
wrong afterwards. INV-COORD-4 forbids wall clock in ordering and supersession
for exactly this reason, and A-033.1 and A-033.6 are the tests that prove it.

WHY A LOGICAL CLOCK ALONE IS NOT ENOUGH EITHER. A Lamport clock orders events
correctly but its values mean nothing to a human and cannot answer "did this
happen in the last hour", which policy windows need. The hybrid keeps a
physical component that tracks wall time when wall time behaves, and a logical
component that takes over whenever it does not.

THE ORDER IS TOTAL, NOT PARTIAL. Ordering is lexicographic on
(physical_ms, logical, node_id). The node_id tie-breaker is what makes it
total: without it two nodes can produce identical (physical_ms, logical) pairs
and the system has no defined winner, which turns into "whichever arrived
last" -- arrival order, the thing this module exists to eliminate.

MONOTONICITY IS BY CONSTRUCTION, NOT BY ASSUMPTION. `now()` never returns a
value <= the last one it returned, whatever the operating system says the time
is. A backwards jump is absorbed into the logical counter and REPORTED, never
silently followed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

# contracts/events/event_envelope.schema.json#/$defs/hlc
HLC_FIELDS = ("physical_ms", "logical", "node_id")


@dataclass(frozen=True, order=False, slots=True)
class HLC:
    """One point in the total order.

    Frozen because a timestamp that can be mutated after it is stamped on an
    event is not a timestamp -- it is a variable that happens to hold a time,
    and every ordering guarantee downstream depends on it not changing.
    """

    physical_ms: int
    logical: int
    node_id: str

    # Ordering is defined ONLY through this key. Nothing else in the codebase
    # may compare timestamps by any other means -- see INV-COORD-4.
    def key(self) -> tuple[int, int, str]:
        return (self.physical_ms, self.logical, self.node_id)

    def __lt__(self, other: "HLC") -> bool:
        return self.key() < other.key()

    def __le__(self, other: "HLC") -> bool:
        return self.key() <= other.key()

    def __gt__(self, other: "HLC") -> bool:
        return self.key() > other.key()

    def __ge__(self, other: "HLC") -> bool:
        return self.key() >= other.key()

    def to_dict(self) -> dict:
        return {
            "physical_ms": self.physical_ms,
            "logical": self.logical,
            "node_id": self.node_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HLC":
        missing = [f for f in HLC_FIELDS if f not in d]
        if missing:
            raise ValueError(f"HLC missing required field(s): {missing}")
        if not isinstance(d["physical_ms"], int) or d["physical_ms"] < 0:
            raise ValueError("HLC.physical_ms must be a non-negative integer")
        if not isinstance(d["logical"], int) or d["logical"] < 0:
            raise ValueError("HLC.logical must be a non-negative integer")
        if not isinstance(d["node_id"], str) or not d["node_id"]:
            raise ValueError("HLC.node_id must be a non-empty string")
        return cls(d["physical_ms"], d["logical"], d["node_id"])

    def __str__(self) -> str:
        return f"{self.physical_ms}.{self.logical}@{self.node_id[:12]}"


class ClockRegression(Exception):
    """Raised only when a regression exceeds the tolerated bound.

    A small backwards step is normal (NTP slew) and is absorbed. A large one
    means the machine's clock is not trustworthy, and continuing to stamp
    policy windows from it would be worse than stopping.
    """


class HybridLogicalClock:
    """Thread-safe HLC. One instance per node.

    `on_regression` receives (observed_ms, last_ms) whenever the physical clock
    moves backwards. The runtime wires this to emit `system.clock_regression`
    (A-033.6). It is a callback rather than a direct bus call because this
    module must not depend on the bus -- the bus stamps its events with this
    clock, and the reverse dependency would be a cycle.
    """

    def __init__(
        self,
        node_id: str,
        *,
        wall_ms: Callable[[], int] | None = None,
        max_regression_ms: int = 300_000,
        on_regression: Callable[[int, int], None] | None = None,
    ) -> None:
        if not node_id:
            raise ValueError("HLC requires a node_id: it is the tie-breaker that makes the order total")
        self._node_id = node_id
        # Injectable so the A-033.6 clock-regression case can drive the clock
        # backwards deterministically. A test that has to wait for real NTP to
        # misbehave is a test that never runs.
        self._wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self._max_regression_ms = max_regression_ms
        self._on_regression = on_regression
        self._lock = threading.Lock()
        self._last = HLC(0, 0, node_id)
        # A regression is an EPISODE, not a per-call condition. The naive form
        # reports on every stamp until wall clock catches up, so a 60-second
        # backwards jump emits one `system.clock_regression` per event for 60
        # seconds -- an event storm that buries the one notification that
        # mattered. Reported once on entry; re-armed when the clock recovers.
        self._in_regression = False
        self._regression_episodes = 0

    @property
    def node_id(self) -> str:
        return self._node_id

    def now(self) -> HLC:
        """Stamp a local event. Strictly greater than every previous return."""
        with self._lock:
            phys = self._wall_ms()
            last = self._last

            if phys > last.physical_ms:
                self._clear_regression(phys)
                nxt = HLC(phys, 0, self._node_id)
            else:
                # Either the clock stood still (same millisecond -- common) or
                # it went backwards. Both are handled by advancing the logical
                # counter, which is what keeps `now()` strictly increasing
                # regardless of what the OS reports.
                if phys < last.physical_ms:
                    self._report_regression(phys, last.physical_ms)
                nxt = HLC(last.physical_ms, last.logical + 1, self._node_id)

            self._last = nxt
            return nxt

    def observe(self, remote: HLC) -> HLC:
        """Merge a timestamp received from another node, then stamp locally.

        This is what makes the order total ACROSS nodes rather than merely
        within one. After observing a remote timestamp, this node's clock is at
        least as far along as the sender's, so any event it subsequently emits
        sorts after the one it just received -- which is the causality the
        world model relies on.
        """
        with self._lock:
            phys = self._wall_ms()
            last = self._last
            if phys < last.physical_ms:
                self._report_regression(phys, last.physical_ms)
            else:
                self._clear_regression(phys)

            high = max(phys, last.physical_ms, remote.physical_ms)
            if high == last.physical_ms == remote.physical_ms:
                logical = max(last.logical, remote.logical) + 1
            elif high == last.physical_ms:
                logical = last.logical + 1
            elif high == remote.physical_ms:
                logical = remote.logical + 1
            else:
                logical = 0

            nxt = HLC(high, logical, self._node_id)
            self._last = nxt
            return nxt

    def peek(self) -> HLC:
        """The last stamped value, without advancing. For assertions only."""
        with self._lock:
            return self._last

    def _report_regression(self, observed_ms: int, last_ms: int) -> None:
        delta = last_ms - observed_ms
        if delta > self._max_regression_ms:
            raise ClockRegression(
                f"wall clock regressed {delta} ms (> {self._max_regression_ms} ms bound). "
                "HLC ordering is unaffected, but wall-clock policy windows on this node "
                "cannot be trusted -- refusing to continue silently."
            )
        if self._in_regression:
            return  # same episode; already reported
        self._in_regression = True
        self._regression_episodes += 1
        if self._on_regression is not None:
            self._on_regression(observed_ms, last_ms)

    def _clear_regression(self, observed_ms: int) -> None:
        """Re-arm once wall clock has caught back up past the high-water mark."""
        if self._in_regression and observed_ms >= self._last.physical_ms:
            self._in_regression = False

    @property
    def regression_episodes(self) -> int:
        """Distinct regression episodes seen. Asserted by A-033.6."""
        return self._regression_episodes


def wall_iso(ms: int | None = None) -> str:
    """RFC3339 UTC, for `observed_at_wall`.

    DISPLAY AND POLICY WINDOWS ONLY. INV-COORD-4 forbids this value from
    participating in ordering or supersession; it is carried on the envelope so
    a human can read it and so time-window policies can evaluate, and for
    nothing else.
    """
    import datetime as _dt

    t = time.time() if ms is None else ms / 1000.0
    return (
        _dt.datetime.fromtimestamp(t, _dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
