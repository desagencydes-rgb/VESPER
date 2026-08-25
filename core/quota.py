"""Quota accounting per (provider, model) — what is left, and what was spent.

WHY THIS EXISTS, AND WHY IT IS NOT A COUNTER.

`ModelGateway` tries providers in the order they were registered. Registration
order was therefore the real routing rule, and nothing in the system knew which
provider had the most headroom left. SR-003 asks for "automatic API switching
when quota/error occurs"; switching *well* means switching to whichever
provider can actually still answer, and that is a fact nobody was holding.

FOUR MEASURED FINDINGS SHAPE THIS FILE. All were taken on 2026-08-25 against
live providers, and each one breaks a design that reads as obviously correct.

  1. A `429` DOES NOT MEAN "EXHAUSTED". Google's image model answered
     RESOURCE_EXHAUSTED carrying `limit: 0` -- the free tier has no allowance
     for that model at all. Same status, opposite meaning: an exhausted quota
     returns tomorrow, a zero quota never returns. Treating them alike spends
     the whole retry budget, every day, forever, on a call that cannot succeed.
     So `limit == 0` is recorded as UNAVAILABLE_ON_TIER and is PERMANENT.

  2. THE PROVIDER'S OWN USAGE FIELD MAY BE ZERO ON A CALL THAT WORKED.
     Cloudflare returned `{'input_tokens': 0, 'output_tokens': 0, 'neurons': 0}`
     for a request that plainly produced output. A ledger that trusts that
     field records zero spend forever and concludes the free tier is infinite.
     So every entry carries `spend_is_measured`, and an unmeasured spend is
     ESTIMATED and SAID to be, never silently treated as fact (INV-HW-2).

  3. COMPLETION TOKENS INCLUDE REASONING TOKENS, and on short answers reasoning
     dominates. Measured on gpt-oss-120b: the reply `GROQ_OK` -- seven
     characters -- cost 64 completion tokens, ~57 of them reasoning. A ledger
     counting "output length" undercounts real spend by roughly 8x on small
     calls. It counts the provider's `completion_tokens`, never the text.

  4. THE SAME MODEL COSTS 4.6x DEPENDING ON ONE PARAMETER. Same prompt, same
     answer `OK`, on gpt-oss-120b: reasoning_effort=low cost 26 completion
     tokens, medium 34, default 64, high 119. This is why `EffortPolicy` lives
     here rather than in the caller -- spend is a quota question, and the
     cheapest correct setting is the ledger's business.

WALL CLOCK IS USED HERE, DELIBERATELY, AND INV-COORD-4 IS NOT VIOLATED.
Quota windows are defined BY the provider in wall-clock terms -- "per day",
"per 5 hours". Asking "has this window ended" is a threshold test against an
external boundary, not an ordering of events, and CLAUDE.md names exactly this
case as permitted. Nothing here sorts by time or decides precedence by it;
event ordering remains HLC's job everywhere else in the system.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Quota window units a provider may meter in. A provider metering in something
# not on this list is a provider we cannot plan against, and `UNKNOWN` is the
# honest answer rather than a guess dressed as a unit.
UNITS = ("requests", "tokens", "neurons", "UNKNOWN")

# State of one (provider, model) pair.
AVAILABLE = "available"
EXHAUSTED = "exhausted"                  # spent; returns when the window rolls
UNAVAILABLE_ON_TIER = "unavailable_on_tier"   # limit==0; NEVER returns


class QuotaExceeded(Exception):
    """No headroom. Carries whether this is temporary or permanent."""

    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


@dataclass
class Entry:
    """One (provider, model) quota line.

    `limit` is None when the provider never told us. That is NOT zero and must
    never be defaulted to zero: zero is a MEASURED statement that the tier has
    no allowance, and inventing it would permanently disable a working model.
    It is also not infinity -- an unknown ceiling is planned against
    conservatively and marked `limit_is_measured = False`.
    """

    provider_id: str
    model: str
    unit: str = "UNKNOWN"
    limit: int | None = None
    limit_is_measured: bool = False
    used: float = 0.0
    # Vacuously true at zero spend; falsified forever by the first
    # unmeasured booking. See record_success.
    spend_is_measured: bool = True
    state: str = AVAILABLE
    window_seconds: int = 86_400
    window_started_at: float = field(default_factory=time.time)
    # What the server said about when to come back, when it said anything.
    server_retry_after_ms: int | None = None
    # Provenance. A number whose origin is not recorded cannot be audited, and
    # this file's whole purpose is deciding what to trust.
    source: str = ""

    def remaining(self) -> float | None:
        """Headroom, or None when the ceiling was never measured."""
        if self.limit is None:
            return None
        return max(0.0, float(self.limit) - self.used)

    def fraction_left(self) -> float | None:
        if self.limit is None or self.limit <= 0:
            return None
        return self.remaining() / float(self.limit)


class QuotaLedger:
    """What each (provider, model) has left. One ledger per account.

    ONE LEDGER PER ACCOUNT, NOT PER MODALITY, and that is load-bearing.
    Cloudflare meters text AND image generation from a single pool of 10,000
    neurons/day. Four modality routers each holding their own ledger would each
    believe they had the whole pool and together authorise four times the real
    budget -- with the overspend landing as 429s on whichever modality asked
    last, most likely the interactive one.
    """

    def __init__(self, path: Path | None = None, *, bus: Any = None) -> None:
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], Entry] = {}
        self._path = Path(path) if path else None
        self._bus = bus
        if self._path and self._path.exists():
            self._load()

    # ------------------------------------------------------------- accounting

    def entry(self, provider_id: str, model: str) -> Entry:
        with self._lock:
            k = (provider_id, model)
            if k not in self._entries:
                self._entries[k] = Entry(provider_id=provider_id, model=model)
            e = self._entries[k]
            self._roll_if_window_elapsed(e)
            return e

    def _roll_if_window_elapsed(self, e: Entry) -> None:
        """Reset a spent window when its period has passed.

        A THRESHOLD TEST, NOT AN ORDERING. See the module docstring: this asks
        whether an externally-defined window has ended, which is the same shape
        as "has 09:00 arrived". It does not order events and does not decide
        precedence.

        UNAVAILABLE_ON_TIER IS NOT ROLLED. A limit of zero is not a window that
        refills -- it is the tier saying this model is not included. Rolling it
        would resurrect a dead route every midnight and spend the retry budget
        rediscovering that it is dead.
        """
        if e.state == UNAVAILABLE_ON_TIER:
            return
        if time.time() - e.window_started_at >= e.window_seconds:
            e.used = 0.0
            e.window_started_at = time.time()
            e.state = AVAILABLE
            e.server_retry_after_ms = None

    def record_success(self, provider_id: str, model: str, *,
                       amount: float | None, unit: str = "UNKNOWN",
                       measured: bool, source: str = "") -> None:
        """Book spend against a pair.

        `amount=None` means the provider did not tell us what the call cost.
        That is recorded as an UNMEASURED estimate of 1 unit rather than as
        zero: Cloudflare returns literal zeros on calls that worked, and a
        ledger that books zero concludes the tier is infinite. One unit is
        wrong, but it is wrong in the safe direction and it is FLAGGED.
        """
        with self._lock:
            e = self.entry(provider_id, model)
            if amount is None:
                e.used += 1.0
                measured = False
            else:
                e.used += float(amount)
            # STICKY, AND ONE-WAY. `spend_is_measured` is vacuously True while
            # nothing has been booked, and ANY unmeasured booking falsifies it
            # permanently. A later measured call must not relabel a total that
            # already contains a guess -- the running figure is only as good as
            # its worst input, and a mixed total that reports itself as
            # measured is exactly the laundering INV-HW-2 refuses.
            if not measured:
                e.spend_is_measured = False
            if unit != "UNKNOWN":
                e.unit = unit
            if source:
                e.source = source
            self._persist()

    def record_refusal(self, provider_id: str, model: str, *,
                       limit: int | None, retry_after_ms: int | None = None,
                       source: str = "") -> Entry:
        """Book a quota refusal. Returns the entry so the caller can see WHICH.

        THE `limit == 0` BRANCH IS THE WHOLE POINT OF THIS METHOD. Google's
        quota detail on an image model read `limit: 0` -- the free tier has no
        allowance, so the very first request is refused and so is every one
        after it. Classified as EXHAUSTED it would be retried tomorrow, and the
        day after, spending the retry budget forever on an impossibility.
        """
        with self._lock:
            e = self.entry(provider_id, model)
            e.server_retry_after_ms = retry_after_ms
            if source:
                e.source = source
            if limit is not None:
                e.limit = int(limit)
                e.limit_is_measured = True
            if limit == 0:
                e.state = UNAVAILABLE_ON_TIER
                self._publish("quota.unavailable_on_tier", provider_id, {
                    "provider_id": provider_id, "model": model, "limit": 0,
                    "permanent": True,
                    "note": ("limit is ZERO, not exhausted: this tier has no "
                             "allowance for this model. Never retried -- a "
                             "window that refills and a tier that excludes "
                             "look identical in the status code and are "
                             "opposite facts.")})
            else:
                e.state = EXHAUSTED
                if e.limit is not None:
                    # The refusal itself measures the ceiling: we were refused
                    # at this point, so this is what the ceiling is. That is a
                    # measurement, which is why `limit_is_measured` is set.
                    e.used = float(e.limit)
                self._publish("quota.exhausted", provider_id, {
                    "provider_id": provider_id, "model": model,
                    "limit": e.limit, "permanent": False,
                    "retry_after_ms": retry_after_ms})
            self._persist()
            return e

    # -------------------------------------------------------------- selection

    def usable(self, provider_id: str, model: str) -> bool:
        e = self.entry(provider_id, model)
        return e.state == AVAILABLE

    def rank(self, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Order (provider, model) pairs by headroom, most first.

        THE BRIEF SAYS "BIGGEST QUOTA TO SMALLEST" AND THAT CANNOT BE A STATIC
        LIST. Which provider is biggest changes through the day as each is
        spent: Cloudflare leads in the morning on 10,000 neurons and can be
        behind Groq by evening. So the order is computed per request.

        AN UNMEASURED CEILING SORTS BEHIND A MEASURED ONE WITH HEADROOM, and
        ahead of a measured one that is nearly spent. Fail-closed would put it
        last always, which would make every unmetered provider useless; treating
        it as infinite would put it first always, which is the declared-capacity
        error INV-HW-2 exists to refuse. Ranking it in the middle is the honest
        reading of "we do not know", and the decision records that it did not
        know.
        """
        with self._lock:
            scored = []
            for i, (pid, model) in enumerate(candidates):
                e = self.entry(pid, model)
                if e.state != AVAILABLE:
                    continue
                frac = e.fraction_left()
                # -1.0 sorts unmeasured between "plenty left" and "nearly out".
                key = frac if frac is not None else 0.5
                scored.append((-key, i, pid, model))
            scored.sort()
            return [(pid, model) for _, _, pid, model in scored]

    def report(self) -> list[dict]:
        with self._lock:
            out = []
            for e in self._entries.values():
                self._roll_if_window_elapsed(e)
                d = asdict(e)
                d["remaining"] = e.remaining()
                d["fraction_left"] = e.fraction_left()
                out.append(d)
            return out

    # ------------------------------------------------------------ persistence

    def _publish(self, type_: str, subject: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=subject, payload=payload,
                              component="quota")

    def _persist(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {f"{k[0]}||{k[1]}": asdict(v) for k, v in self._entries.items()},
            indent=2), encoding="utf-8")
        tmp.replace(self._path)      # atomic; a torn ledger is worse than none

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A CORRUPT LEDGER IS NOT AN EMPTY ONE, but it is the safe default:
            # starting from zero over-estimates headroom for one window and
            # self-corrects on the first refusal, whereas refusing to start
            # leaves the system with no route at all.
            return
        for k, v in raw.items():
            pid, _, model = k.partition("||")
            self._entries[(pid, model)] = Entry(**v)
