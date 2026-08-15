"""Telemetry — sensitivity enforced at the writer, plus checkpoint budget timing.

INV-OBS-1 SAYS SENSITIVITY IS ENFORCED BY THE TELEMETRY WRITER AT WRITE TIME,
NEVER BY CALLER DISCIPLINE. That phrasing is doing real work. The natural
design puts a `redact()` helper in a utility module and trusts every call site
to use it; the first caller added under time pressure forgets, and the leak is
permanent because telemetry is retained. So redaction happens HERE, on the way
to disk, and a caller cannot opt out.

INV-OBS-2: `correlation_id` survives purge. Purging the content of an
observation must not destroy the ability to say that an observation existed and
what it led to -- otherwise a purge erases the audit trail along with the data,
and the system loses the ability to explain itself.

INV-PERF-1: ON A BUDGET MISS THE BUDGET IS NOT RELAXED. `record_duration`
reports a breach; it has no path to widening the budget. The options named in
the corpus are optimise, raise the minimum profile, or record a limitation --
all of which are decisions, not code changes made under a failing test.
"""

from __future__ import annotations

import statistics
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .hlc import HybridLogicalClock, wall_iso
from .store import StoreSet

# Field names whose VALUES never reach the telemetry store in the clear.
# Matched case-insensitively on substrings, because the failure mode is a field
# called `user_password_hint`, not one called exactly `password`.
REDACT_SUBSTRINGS = ("password", "secret", "token", "api_key", "apikey",
                     "credential", "private_key", "passphrase", "session_key",
                     "authorization", "cookie")

REDACTED = "[REDACTED-BY-WRITER]"


def _redact(obj: Any, depth: int = 0) -> Any:
    """Structural redaction. Applied on the write path, unconditionally."""
    if depth > 12:
        return "[REDACTION-DEPTH-LIMIT]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(s in str(k).lower() for s in REDACT_SUBSTRINGS):
                out[k] = REDACTED
            else:
                out[k] = _redact(v, depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v, depth + 1) for v in obj]
    return obj


@dataclass(slots=True)
class BudgetStat:
    name: str
    budget_ms: float
    samples: list = field(default_factory=list)

    def p95(self) -> float | None:
        if not self.samples:
            return None
        s = sorted(self.samples)
        # Nearest-rank p95. With n < 20 this is the max, which is the honest
        # answer at that sample size rather than an interpolated number that
        # implies more data than exists.
        idx = max(0, min(len(s) - 1, int(round(0.95 * len(s))) - 1))
        return s[idx]

    def breached(self) -> bool:
        p = self.p95()
        return p is not None and p > self.budget_ms


class Telemetry:
    """Writes to the `audit` store. Append-only at the storage layer."""

    def __init__(self, store: StoreSet, clock: HybridLogicalClock) -> None:
        self._store = store
        self._clock = clock
        self._budgets: dict[str, BudgetStat] = {}
        self._lock = threading.RLock()

    def record(self, kind: str, fields: dict, *, sensitivity: str = "internal",
               correlation_id: str | None = None) -> None:
        body = {
            # INV-OBS-2: survives purge of the content, so the fact that
            # something happened outlives the details of what.
            "correlation_id": correlation_id,
            "sensitivity": sensitivity,
            "wall": wall_iso(),
            "fields": _redact(fields),
        }
        self._store.append("audit", kind, body, self._clock.now())

    def declare_budget(self, name: str, budget_ms: float) -> None:
        with self._lock:
            self._budgets.setdefault(name, BudgetStat(name, budget_ms))

    def record_duration(self, name: str, ms: float) -> bool:
        """Record a sample. Returns True if the p95 budget is now breached.

        INV-PERF-1: there is deliberately no `relax_budget`. A breach is
        reported and recorded; what to do about it is a decision made by a
        human with the number in hand.
        """
        with self._lock:
            b = self._budgets.get(name)
            if b is None:
                raise KeyError(
                    f"budget {name!r} was never declared. Declare it before "
                    "measuring against it, so an undeclared budget cannot be "
                    "invented to fit a measurement.")
            b.samples.append(ms)
            breached = b.breached()
        if breached:
            self.record("perf.budget_breached", {
                "budget": name, "budget_ms": b.budget_ms, "p95_ms": b.p95(),
                "samples": len(b.samples),
                "note": "INV-PERF-1: the budget is NOT relaxed. Optimise, raise "
                        "the minimum profile, or record a limitation.",
            })
        return breached

    @contextmanager
    def time(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record_duration(name, (time.perf_counter() - t0) * 1000.0)

    def budgets(self) -> dict:
        with self._lock:
            return {
                n: {"budget_ms": b.budget_ms, "p95_ms": b.p95(),
                    "samples": len(b.samples), "breached": b.breached()}
                for n, b in self._budgets.items()
            }
