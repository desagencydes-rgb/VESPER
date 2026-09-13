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
import math
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
    # THE POOL THIS ENTRY DRAWS FROM, when several (provider, model) pairs
    # share one budget. Cloudflare meters text AND image generation from a
    # single 10,000 neurons/day; without this, a text consumer and an image
    # consumer each see a full ceiling and together authorise twice the real
    # budget. Empty means the entry has a budget of its own.
    account: str = ""
    # What this entry is FOR. Entries sharing a pool compete, and a batch job
    # will happily spend the whole day's budget before the owner asks their
    # first question. The purpose is what a reservation floor is declared
    # against.
    purpose: str = "text"
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
    # VESPER'S OWN CEILING, AS A SHARE OF THE PROVIDER'S. Owner, 2026-09-13: the
    # account the agents share may use 70% of its window and the advisor's 40%,
    # so that VESPER's own calls never spend what the owner needs. IT BINDS ONLY
    # ON A MEASURED LIMIT: a share of an unknown number is an unknown number
    # (INV-HW-2), so until the first refusal measures the window the cap is
    # declared and does not bind, and says so.
    soft_cap_ratio: float | None = None

    def effective_limit(self) -> int | None:
        """The ceiling this entry is actually allowed to reach, or None.

        None when nothing measured the provider's ceiling, or no cap is
        declared. Never below 1: a cap that rounds to zero would retire a rung
        VESPER is permitted to use, which is the fail-closed reading applied to
        the wrong quantity.
        """
        if (self.limit is None or not self.limit_is_measured
                or self.soft_cap_ratio is None):
            return None
        return max(1, int(float(self.limit) * self.soft_cap_ratio))

    def soft_capped(self) -> bool:
        """VESPER has stopped itself here; the provider has not refused."""
        eff = self.effective_limit()
        return eff is not None and self.used >= eff

    def remaining(self) -> float | None:
        """Headroom, or None when the ceiling was never measured.

        Against VESPER's own ceiling where one binds: headroom the cap forbids
        spending is not headroom, and ranking on it would send the ladder
        straight at the line the cap exists to hold.
        """
        if self.limit is None:
            return None
        ceiling = self.effective_limit()
        return max(0.0, float(ceiling if ceiling is not None else self.limit) - self.used)

    def fraction_left(self) -> float | None:
        if self.limit is None or self.limit <= 0:
            return None
        ceiling = self.effective_limit()
        return self.remaining() / float(ceiling if ceiling is not None else self.limit)


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
        # account -> published ceiling for the whole pool.
        self._pools: dict[str, float] = {}
        # (account, purpose) -> fraction of the pool reserved for it.
        self._floors: dict[tuple, float] = {}
        if self._path and self._path.exists():
            self._load()

    def declare_pool(self, account: str, limit: float) -> None:
        """One shared ceiling for every entry naming this account."""
        with self._lock:
            self._pools[account] = float(limit)

    def reserve(self, account: str, purpose: str, fraction: float) -> None:
        """Hold a share of a pool for one purpose.

        THE FLOOR IS HARD, AND THE FIRST VERSION OF THIS DOCSTRING SAID IT WAS
        SOFT -- "an unused floor is lent out". The code never did that, and it
        could not: lending only works if the lender can call the loan back, and
        SPENT QUOTA CANNOT BE RECLAIMED. Once a batch of images has spent the
        day's neurons there is no mechanism, at any layer, that returns them to
        conversation. A floor that yields to whoever asks first is not a floor.

        So a purpose may spend the pool MINUS what every other purpose holds,
        whether or not those others have spent anything yet. That idles capacity
        on a quiet day, and it is the correct trade: the cost of the reservation
        is a batch job finishing later, and the cost of not having one is the
        owner asking a question at 6 p.m. and being told the day is gone.

        Fractions are not checked against a total of 1.0 on purpose -- floors
        summing over 1.0 make every purpose unspendable, which is a fail-closed
        outcome that surfaces immediately rather than a silent overcommit.
        """
        with self._lock:
            self._floors[(account, purpose)] = float(fraction)

    def reserved_for_others(self, account: str, purpose: str) -> float:
        """Pool units held for purposes OTHER than this one."""
        with self._lock:
            cap = self._pools.get(account)
            if cap is None:
                return 0.0
            return sum(cap * f for (a, p), f in self._floors.items()
                       if a == account and p != purpose)

    def spendable(self, account: str, purpose: str) -> float | None:
        """What this purpose may still spend, after others' floors.

        Never negative: once a purpose has eaten into what others reserved,
        the answer is zero rather than a debt. A negative here would flow into
        a ranking comparison and quietly reorder the ladder.
        """
        rem = self.pool_remaining(account)
        if rem is None:
            return None
        return max(0.0, rem - self.reserved_for_others(account, purpose))

    def pool_used(self, account: str) -> float:
        """Total spend across every entry drawing on this pool."""
        with self._lock:
            return sum(e.used for e in self._entries.values()
                       if e.account == account)

    def pool_remaining(self, account: str) -> float | None:
        with self._lock:
            cap = self._pools.get(account)
        if cap is None:
            return None
        return max(0.0, cap - self.pool_used(account))

    def pool_report(self) -> list:
        with self._lock:
            accounts = sorted({e.account for e in self._entries.values() if e.account})
        return [{"account": a, "limit": self._pools.get(a),
                 "used": round(self.pool_used(a), 1),
                 "remaining": self.pool_remaining(a),
                 "drawn_by": sorted(f"{e.provider_id}/{e.model}"
                                    for e in self._entries.values() if e.account == a)}
                for a in accounts]

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
            was_capped = e.soft_capped()
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
            if e.soft_capped() and not was_capped:
                # SAID ONCE, AT THE LINE. The state stays AVAILABLE because the
                # provider refused nothing; `rank` and `usable` stop offering the
                # entry, and this record is how the owner can tell "VESPER held
                # back" from "the provider ran out" -- opposite facts under the
                # same silence.
                self._publish("quota.soft_capped", provider_id, {
                    "provider_id": provider_id, "model": model,
                    "used": e.used, "effective_limit": e.effective_limit(),
                    "limit": e.limit, "soft_cap_ratio": e.soft_cap_ratio,
                    "unit": e.unit,
                    "note": ("VESPER's own ceiling, a declared share of a "
                             "measured window; the provider has not refused")})
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
            elif e.limit is None and e.used > 0:
                # THE REFUSAL MEASURES THE CEILING IN THIS LEDGER'S OWN UNITS.
                # A subscription CLI says "limit reached" and never a number, so
                # `limit` stayed None forever and no share of it could ever be
                # taken. What IS known at this moment is how much this window
                # spent before the door closed -- and that is a measurement of
                # the door, in requests, taken by hitting it. A refusal on a
                # window's FIRST call measures nothing (zero would read as a tier
                # with no allowance) and is left unmeasured.
                e.limit = int(math.ceil(e.used))
                e.limit_is_measured = True
                e.source = ((e.source + " | ") if e.source else "") + (
                    f"ceiling measured at refusal: {e.used:g} {e.unit} spent "
                    "in this window when the provider closed the door")
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
        """AVAILABLE, and the shared pool must not already be spent.

        An entry can be perfectly healthy on its own books while the account it
        draws from has nothing left. Checking only the entry is how two
        consumers of one budget both conclude they may proceed.
        """
        e = self.entry(provider_id, model)
        if e.state != AVAILABLE or e.soft_capped():
            return False
        if not e.account:
            return True
        rem = self.spendable(e.account, e.purpose)
        return rem is None or rem > 0

    def offered_state(self, e: Entry) -> str:
        """What `rank` will say about this entry, for the record a skip carries.

        `soft_capped` is not a state the window rolls -- the provider is
        AVAILABLE and VESPER is the one holding back -- so it is reported here
        rather than written into `state`, and a skip recorded from it reads
        `quota_ledger_soft_capped` instead of an exhaustion that never happened.
        """
        return "soft_capped" if (e.state == AVAILABLE and e.soft_capped()) else e.state

    def headroom_fraction(self, e: Entry) -> float | None:
        """Headroom as a fraction, THE BINDING ONE when a pool applies.

        An entry in a pool has two ceilings and the smaller decides. Reporting
        only the entry's own would let an image consumer see plenty of room in
        a pool that conversation had already spent -- which is the failure the
        pool exists to prevent, arriving one level down.
        """
        own = e.fraction_left()
        if not e.account:
            return own
        cap = self._pools.get(e.account)
        if cap is None or cap <= 0:
            return own
        # The pool fraction this purpose may actually reach, not the raw
        # remainder: capacity another purpose is holding is not headroom.
        spendable = self.spendable(e.account, e.purpose)
        pool = (spendable / cap) if spendable is not None else 1.0
        return pool if own is None else min(own, pool)

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
                if e.state != AVAILABLE or e.soft_capped():
                    continue
                frac = self.headroom_fraction(e)
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
                d["effective_limit"] = e.effective_limit()
                d["soft_capped"] = e.soft_capped()
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
