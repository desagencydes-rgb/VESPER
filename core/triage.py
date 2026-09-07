"""What happens to a failure after the request has already been answered.

THE BRIEF'S RULE, AND IT IS THE RIGHT ONE. Quota failures are classified,
routed around, and forgotten. Everything else is held for investigation, and
the investigation runs LATER -- when a model is available again, never during
the outage.

That ordering is structural rather than tidy. Triage needs a working model to
reason about a failure, and during the outage there is not one; a system that
tried to investigate at the moment of failure would be asking the broken thing
to explain itself.

WHY QUOTA IS EXCLUDED, stated precisely because it is the one exclusion here.
A rate limit or a spent window is a working provider doing its job. There is
nothing to find, nothing to fix, and no action a person could take -- so
queueing it produces a backlog of items whose only possible resolution is
"yes, we used what we had". A queue that fills with non-findings is a queue
nobody reads, and the real finding underneath goes with it.

    limit == 0 IS ALSO NOT INVESTIGATED, and that is not obvious. It is
    permanent, so it looks like the kind of thing a person should know. But
    the ledger has already recorded it and the ladder has already stopped
    offering that rung -- the system has fully absorbed the fact. What would
    an investigation add? It is a CONFIGURATION truth, surfaced in the daily
    summary, not an incident.

ORDERED BY HLC, NEVER BY WALL CLOCK (INV-COORD-4). Failures arrive from
several providers, potentially across nodes, and a queue sorted on timestamps
would reorder itself whenever a clock drifted. The wall clock appears here only
as a displayed field.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# core/gateway.py's vocabulary, imported by value so the two cannot drift.
from .gateway import TERMINAL, TRANSIENT

# Classifications that are ROUTED AROUND and never investigated.
NOT_INVESTIGATED = frozenset({
    "rate_limited",                 # a working provider doing its job
    "quota_exhausted",              # the window refills; nothing to find
    "quota_unavailable_on_tier",    # permanent, but already fully absorbed
    "cost_policy",                  # a rule was applied; nothing went wrong
    "provider_unavailable",         # deliberately revoked, e.g. by A-004.3
    # THE LEDGER'S OWN REFUSAL, AND IT WAS THE ONE GETTING THROUGH.
    #
    # `rate_limited` is excluded above, correctly -- but the gateway BOOKS that
    # refusal, and every call afterwards is declined by the ledger with a
    # DIFFERENT classification. Measured 2026-09-07: the advisor hit a real
    # session limit, was correctly read as `rate_limited` and correctly
    # declined by triage, and then produced six `quota_ledger_exhausted` items
    # that WERE admitted -- each one graded, repaired, and answered "no tier-1
    # handler exists for this classification".
    #
    # That is the same defect as the one this exclusion was written for,
    # arriving one step downstream under a name the exclusion had not been
    # taught. A quota that has already been absorbed is not a defect the second
    # time it is reported either.
    "quota_ledger_exhausted",
})

# The four grades. Only the first is ever acted on without the owner.
CRITICAL_NOW = "CRITICAL_NOW"
CRITICAL_DEFERRED = "CRITICAL_DEFERRED"
CAN_WAIT = "CAN_WAIT"
NO_FIX_NEEDED = "NO_FIX_NEEDED"
GRADES = (CRITICAL_NOW, CRITICAL_DEFERRED, CAN_WAIT, NO_FIX_NEEDED)

# A single transient blip is noise; a pattern across a window is a change in
# the world. Below this count, `server_error` and `connection_error` close as
# NO_FIX_NEEDED rather than opening an investigation.
REPEAT_THRESHOLD = 3


@dataclass
class TriageItem:
    """One failure held for investigation, with the evidence that produced it.

    `attempts` HOLDS RECORDS, NOT A SUMMARY. "Recurring server_error" is not a
    finding; "9 of 11 attempts to that rung in 40 minutes, all 503, while two
    other rungs succeeded" is. A grade computed from a summary cannot be
    re-derived later, and a grade nobody can re-derive is an opinion.
    """

    item_id: str
    provider_id: str
    model: str
    classification: str
    hlc: str
    first_seen_wall: str = ""
    attempts: list = field(default_factory=list)
    grade: str | None = None
    grade_reason: str = ""
    graded_hlc: str | None = None
    resolution: str | None = None

    def count(self) -> int:
        return len(self.attempts)


class TriageQueue:
    """Durable, HLC-ordered, and deliberately empty of quota failures."""

    def __init__(self, path: Path | None = None, *, bus: Any = None,
                 clock: Any = None) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, TriageItem] = {}
        self._path = Path(path) if path else None
        self._bus = bus
        self._clock = clock
        if self._path and self._path.exists():
            self._load()

    def attach(self, bus: Any) -> None:
        """Collect investigable failures off `gateway.attempt` as they happen.

        SUBSCRIBED, NOT CALLED, for the same reason narration is: the gateway
        publishes what happened and must not know who cares. A call path that
        holds a reference to a triage queue is one that cannot run without one.

        RECORDING IS NOT INVESTIGATING. This runs during the outage and only
        writes the failure down; grading needs a working model and happens when
        a rung reports healthy again (`grade_all`).
        """
        def on_attempt(ev: Any) -> None:
            payload = getattr(ev, "payload", {}) or {}
            if payload.get("outcome") == "ok":
                return
            self.record(payload.get("provider_id", "unknown"),
                        payload.get("model", "unknown"),
                        payload.get("classification"),
                        detail={k: payload.get(k) for k in
                                ("elapsed_ms", "retry_after_ms",
                                 "server_retry_after_ms", "attempt",
                                 "max_attempts", "cost_class")})

        bus.subscribe("gateway.attempt", on_attempt, name="triage-attempt",
                      idempotency_key=lambda e: e.event_id)

        # A WARNING NOBODY READS IS NOT A CONTROL.
        #
        # `quota.limit_parse_suspect` fires when a refusal names a limit in a
        # shape the parser could not read -- the signal that the one regex
        # standing between "permanently dead rung" and "back tomorrow" has
        # drifted. It was published and NOTHING CONSUMED IT, which made it a
        # log line dressed as a safeguard: the detector would fire correctly,
        # forever, into a bus with no subscriber.
        #
        # Routed here it becomes a graded item with an owner-facing escalation,
        # which is the difference between detecting drift and doing something
        # about it.
        def on_drift(ev: Any) -> None:
            payload = getattr(ev, "payload", {}) or {}
            self.record(payload.get("provider_id", "unknown"),
                        payload.get("model", "unknown"),
                        "quota_limit_unparseable",
                        detail={"message_excerpt": payload.get("message_excerpt"),
                                "booked_as": payload.get("booked_as")})

        bus.subscribe("quota.limit_parse_suspect", on_drift,
                      name="triage-quota-drift",
                      idempotency_key=lambda e: e.event_id)

    # ------------------------------------------------------------- admission

    @staticmethod
    def investigable(classification: str | None) -> bool:
        """Does this failure warrant investigation at all?

        UNKNOWN CLASSIFICATIONS ARE INVESTIGATED, not ignored. A classification
        this module has never heard of is exactly the thing worth a person's
        attention -- fail-open here is the safe direction, because the cost is
        one queue entry and the cost of the alternative is a new failure mode
        that is silently discarded forever.
        """
        if not classification:
            return False
        return classification not in NOT_INVESTIGATED

    def record(self, provider_id: str, model: str, classification: str,
               *, detail: dict | None = None) -> TriageItem | None:
        """Admit a failure, or decline it. Returns None when declined."""
        if not self.investigable(classification):
            return None
        with self._lock:
            key = f"{provider_id}::{model}::{classification}"
            hlc = self._tick()
            item = self._items.get(key)
            if item is None:
                item = TriageItem(item_id=key, provider_id=provider_id,
                                  model=model, classification=classification,
                                  hlc=hlc)
                self._items[key] = item
            # RE-OPENED, NOT DUPLICATED. The same failure recurring is stronger
            # evidence about one problem, not a second problem -- and a grade
            # already given is cleared, because the thing it was given about
            # has changed.
            item.attempts.append(dict(detail or {}))
            if item.grade is not None:
                item.grade = None
                item.grade_reason = ("re-opened: the failure recurred after "
                                     "being graded, so the grade no longer "
                                     "describes what is happening")
            self._persist()
            self._publish("triage.recorded", key, {
                "provider_id": provider_id, "model": model,
                "classification": classification, "occurrences": item.count()})
            return item

    # -------------------------------------------------------------- grading

    def grade(self, item: TriageItem) -> TriageItem:
        """Assign one of four grades, from the evidence and nothing else.

        NOT A MODEL CALL. The grading rule is written down here so it can be
        argued with, tested, and re-derived from the same attempts six months
        later. A model asked to grade its own provider failures would produce a
        plausible answer that no one could check, and the one thing this queue
        is for is producing findings that survive review.
        """
        n = item.count()
        c = item.classification

        if c == "auth_failed":
            g, why = CRITICAL_NOW, (
                f"credentials refused {n}x on {item.provider_id}. This does not "
                "heal on its own and removes an entire rung until someone acts "
                "-- an expired or revoked key stays expired.")
        elif c == "bad_request":
            g, why = CRITICAL_NOW, (
                f"the provider rejected our request {n}x as malformed. Almost "
                "always our defect, and it will recur identically on every "
                "future call until the request changes.")
        elif c == "quota_limit_unparseable":
            g, why = CRITICAL_NOW, (
                f"a refusal from {item.provider_id} named a limit the parser "
                "could not read. That parser is the ONLY signal separating a "
                "tier with no allowance (permanent) from a spent window (back "
                "tomorrow) -- the structured quota block carries metrics and "
                "ids and no limit at all. While it is drifted, a dead rung is "
                "retried every day forever and every check stays green, "
                "because the fixture is frozen and still parses. Needs a live "
                "refusal to re-measure against; the fixture cannot tell you.")
        elif c == "no_provider_for_profile":
            g, why = CRITICAL_NOW, (
                "a routed capability has no provider. The router decided and "
                "the gateway could not honour it -- a configuration gap, not a "
                "transient fault.")
        elif c in ("server_error", "connection_error"):
            if n >= REPEAT_THRESHOLD:
                g, why = CRITICAL_DEFERRED, (
                    f"{n} occurrences, at or above the repeat threshold of "
                    f"{REPEAT_THRESHOLD}. A pattern is a change in the world "
                    "rather than a blip -- but the ladder routed around it, so "
                    "the workaround holds and this is not an emergency.")
            else:
                g, why = NO_FIX_NEEDED, (
                    f"{n} occurrence(s), below the repeat threshold of "
                    f"{REPEAT_THRESHOLD}. A single transient fault that the "
                    "ladder already absorbed. Closed with its evidence rather "
                    "than left open to accumulate.")
        elif c == "timeout":
            g, why = (CRITICAL_DEFERRED if n >= REPEAT_THRESHOLD else CAN_WAIT), (
                f"{n} timeout(s) on {item.provider_id}. The request may have "
                "been served and lost on the way back, so this is not "
                "evidence the provider is down.")
        else:
            # THE UNKNOWN PATH, and it is deliberately not NO_FIX_NEEDED. A
            # classification this rule has never seen is precisely what a
            # person should look at; grading it away would make every future
            # unknown failure invisible.
            g, why = CAN_WAIT, (
                f"classification {c!r} has no grading rule. Surfaced rather "
                "than closed: an unrecognised failure is the one most worth a "
                "person's attention, and a default of NO_FIX_NEEDED would hide "
                "every future unknown.")

        with self._lock:
            item.grade, item.grade_reason = g, why
            item.graded_hlc = self._tick()
            self._persist()
        self._publish("triage.graded", item.item_id, {
            "provider_id": item.provider_id, "classification": c,
            "grade": g, "reason": why, "occurrences": n})
        return item

    def grade_all(self) -> list:
        """Drain the ungraded backlog. Called when a rung reports healthy."""
        with self._lock:
            pending = [i for i in self._items.values() if i.grade is None]
        return [self.grade(i) for i in pending]

    # --------------------------------------------------------------- reading

    def open_items(self, grade: str | None = None) -> list:
        with self._lock:
            # HLC ORDER, NEVER WALL CLOCK (INV-COORD-4).
            items = sorted(self._items.values(), key=lambda i: i.hlc)
        if grade is None:
            return [i for i in items if i.resolution is None]
        return [i for i in items if i.grade == grade and i.resolution is None]

    def resolve(self, item_id: str, resolution: str) -> None:
        with self._lock:
            it = self._items.get(item_id)
            if it is not None:
                it.resolution = resolution
                self._persist()

    def report(self) -> list:
        with self._lock:
            return [asdict(i) for i in
                    sorted(self._items.values(), key=lambda i: i.hlc)]

    # ----------------------------------------------------------- internals

    def _tick(self) -> str:
        if self._clock is None:
            # A MONOTONIC COUNTER, NOT A TIMESTAMP. Without a clock the queue
            # still must not order on wall time; a sequence preserves admission
            # order without pretending to be a time.
            return f"seq-{len(self._items):08d}-{sum(i.count() for i in self._items.values()):08d}"
        # `now()`, NOT `tick()`. This read `self._clock.tick()` from the day it
        # was written and HybridLogicalClock has no such method, so every
        # `record` with a clock attached raised AttributeError -- and the bus
        # SWALLOWS handler exceptions into a failure counter, so the drift
        # subscription fired correctly, failed silently, and looked wired.
        #
        # Found because the queue was finally constructed WITH a clock. The
        # check exercised the no-clock path only, so a whole branch of this
        # class had never run. A test that constructs its subject one way
        # covers one way.
        return str(self._clock.now())

    def _publish(self, type_: str, subject: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=subject, payload=payload,
                              component="triage")

    def _persist(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in self._items.items()},
                                  indent=2), encoding="utf-8")
        tmp.replace(self._path)     # atomic; a torn queue is worse than none

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for k, v in raw.items():
            self._items[k] = TriageItem(**v)
