"""Event bus — typed envelopes, HLC ordering, mandatory consumer idempotency.

THREE THINGS THIS ENFORCES THAT A NORMAL PUB/SUB DOES NOT:

1. EVERY CONSUMER DECLARES AN IDEMPOTENCY KEY (INV-COORD-5), and registration
   without one is refused. Not warned about -- refused, at registration time,
   which is the only moment the mistake is cheap. At-least-once delivery is the
   only delivery guarantee a partition-tolerant system can offer, so duplicate
   delivery is not an anomaly to be handled later; it is the contract. A
   consumer that has not said how to recognise a repeat WILL double-apply, and
   A-033.2 replays 500 events twice to prove it does not.

2. SENSITIVITY IS ENFORCED AT WRITE TIME, NEVER BY CALLER DISCIPLINE
   (INV-OBS-1). An event marked `sensitive` or `secret` MUST carry an empty
   payload and use `payload_ref` instead. The check lives here because "every
   caller remembers to do the right thing" is not a security property -- it is
   a hope, and it fails the first time someone adds a caller in a hurry.

3. ORDERING IS HLC-ONLY (INV-COORD-4). `observed_at_wall` rides along for
   display and policy windows and is structurally excluded from every ordering
   path in this file.

DELIVERY MODEL. Synchronous, in-process, ordered. F0 is a single-node runtime;
cross-node transport is F2's problem. Handlers run inline so that "the event
was published" and "every consumer has seen it" are the same instant -- which
makes the durable-state assertions in A-002 and A-034 checkable without
sleeping in a test.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .codec import UpcasterRegistry
from .hlc import HLC, HybridLogicalClock, wall_iso
from .store import StoreSet

SENSITIVITY = ("public", "internal", "personal", "sensitive", "secret")
TRUST_CLASS = ("system", "owner", "verified_local", "retrieved_local",
               "retrieved_external", "model_generated")
# INV-OBS-1: at these levels the payload must be empty and the content must
# live behind a payload_ref in the separately-retained store.
PAYLOAD_FORBIDDEN = ("sensitive", "secret")

ENVELOPE_SCHEMA_VERSION = 1


class ContractViolation(Exception):
    """An envelope or a registration broke a contract. Never caught internally."""


@dataclass(frozen=True, slots=True)
class Event:
    """One event envelope. Mirrors contracts/events/event_envelope.schema.json."""

    event_id: str
    type: str
    source: dict
    subject: str
    observed_at_hlc: HLC
    observed_at_wall: str
    sensitivity: str
    trust_class: str
    payload: dict
    schema_version: int = ENVELOPE_SCHEMA_VERSION
    correlation_id: str | None = None
    caused_by: str | None = None
    trigger_id: str | None = None
    confidence: float | None = None
    provenance: tuple = ()
    payload_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "type": self.type,
            "source": self.source,
            "subject": self.subject,
            "observed_at_hlc": self.observed_at_hlc.to_dict(),
            "observed_at_wall": self.observed_at_wall,
            "correlation_id": self.correlation_id,
            "caused_by": self.caused_by,
            "trigger_id": self.trigger_id,
            "sensitivity": self.sensitivity,
            "trust_class": self.trust_class,
            "confidence": self.confidence,
            "provenance": list(self.provenance),
            "payload_ref": self.payload_ref,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            event_id=d["event_id"],
            type=d["type"],
            source=d["source"],
            subject=d["subject"],
            observed_at_hlc=HLC.from_dict(d["observed_at_hlc"]),
            observed_at_wall=d["observed_at_wall"],
            sensitivity=d["sensitivity"],
            trust_class=d["trust_class"],
            payload=d.get("payload") or {},
            schema_version=d.get("schema_version", ENVELOPE_SCHEMA_VERSION),
            correlation_id=d.get("correlation_id"),
            caused_by=d.get("caused_by"),
            trigger_id=d.get("trigger_id"),
            confidence=d.get("confidence"),
            provenance=tuple(d.get("provenance") or ()),
            payload_ref=d.get("payload_ref"),
        )


@dataclass
class Subscription:
    name: str
    event_type: str
    handler: Callable[[Event], None]
    # INV-COORD-5. Maps an event to the key that identifies "the same work".
    # Usually event_id; a consumer that dedupes on a business key (one action
    # per task per step, say) says so here.
    idempotency_key: Callable[[Event], str]
    seen: set = field(default_factory=set)
    applied: int = 0
    suppressed_duplicates: int = 0
    failures: int = 0


class EventBus:
    """In-process, ordered, at-least-once with enforced consumer idempotency."""

    def __init__(self, clock: HybridLogicalClock, store: StoreSet,
                 *, component: str = "bus",
                 codec: UpcasterRegistry | None = None) -> None:
        self._clock = clock
        self._store = store
        self._component = component
        # ADR-002 D4: migration is read-time upcasting, so the codec belongs on
        # the READ path and nowhere else. A default empty registry is correct
        # rather than lax -- with no upcasters registered, a body at the current
        # version passes through and a body at any other version RAISES, which
        # is the behaviour criterion 8 asks for.
        self.codec = codec if codec is not None else UpcasterRegistry()
        self._subs: dict[str, list[Subscription]] = {}
        self._lock = threading.RLock()
        self._published = 0

    # ------------------------------------------------------------ subscribe

    def subscribe(self, event_type: str, handler: Callable[[Event], None], *,
                  name: str,
                  idempotency_key: Callable[[Event], str] | None = None) -> Subscription:
        """Register a consumer. REFUSES registration without an idempotency key.

        INV-COORD-5 calls a registration without one "a build failure". This is
        the build-failure moment: raising here is the whole enforcement.
        """
        if idempotency_key is None:
            raise ContractViolation(
                f"consumer {name!r} registered for {event_type!r} without an "
                "idempotency key. INV-COORD-5: delivery is at-least-once, so a "
                "consumer that cannot recognise a repeat will double-apply. "
                "Pass idempotency_key=lambda e: e.event_id if that is genuinely "
                "the right key -- but say so explicitly."
            )
        sub = Subscription(name=name, event_type=event_type, handler=handler,
                           idempotency_key=idempotency_key)
        with self._lock:
            self._subs.setdefault(event_type, []).append(sub)
        return sub

    # -------------------------------------------------------------- publish

    def publish(self, type: str, subject: str, payload: dict, *,
                sensitivity: str = "internal",
                trust_class: str = "system",
                component: str | None = None,
                subject_kind: str = "runtime",
                correlation_id: str | None = None,
                caused_by: str | None = None,
                trigger_id: str | None = None,
                confidence: float | None = None,
                provenance: tuple = (),
                payload_ref: str | None = None,
                at: HLC | None = None) -> Event:
        if sensitivity not in SENSITIVITY:
            raise ContractViolation(
                f"sensitivity {sensitivity!r} not in {SENSITIVITY}")
        if trust_class not in TRUST_CLASS:
            raise ContractViolation(
                f"trust_class {trust_class!r} not in {TRUST_CLASS}")
        # INV-OBS-1, enforced by the writer rather than by the caller.
        if sensitivity in PAYLOAD_FORBIDDEN and payload:
            raise ContractViolation(
                f"event {type!r} is {sensitivity!r} and carries an inline payload. "
                "INV-OBS-1: content/reference separation is what makes retention "
                "and purge enforceable. Put the content in the separately-retained "
                "store and pass payload_ref."
            )

        stamp = at or self._clock.now()
        ev = Event(
            event_id=str(uuid.uuid4()),
            type=type,
            source={"node_id": self._clock.node_id,
                    "component": component or self._component,
                    "subject_kind": subject_kind},
            subject=subject,
            observed_at_hlc=stamp,
            # Display and policy windows only. Never read by any ordering path.
            observed_at_wall=wall_iso(),
            sensitivity=sensitivity,
            trust_class=trust_class,
            payload=dict(payload),
            correlation_id=correlation_id,
            caused_by=caused_by,
            trigger_id=trigger_id,
            confidence=confidence,
            provenance=tuple(provenance),
            payload_ref=payload_ref,
        )
        return self.emit(ev)

    def emit(self, ev: Event) -> Event:
        """Durably append, then deliver. Order matters: append FIRST.

        If delivery crashes the machine, the event is already in the log and
        replay will re-deliver it. The reverse order loses events whose
        handlers ran but whose record never landed -- and those are invisible
        afterwards, because nothing recorded that they existed.
        """
        with self._lock:
            self._store.append("log", ev.type, ev.to_dict(), ev.observed_at_hlc)
            self._published += 1
            subs = list(self._subs.get(ev.type, ()))
        for sub in subs:
            self._deliver(sub, ev)
        return ev

    def _deliver(self, sub: Subscription, ev: Event) -> None:
        key = sub.idempotency_key(ev)
        if key in sub.seen:
            sub.suppressed_duplicates += 1
            return
        try:
            sub.handler(ev)
        except Exception:
            # A failing consumer must not take down the publisher or the other
            # consumers, and must not be silently swallowed either. The key is
            # NOT marked seen, so a replay retries it.
            sub.failures += 1
            self._store.append("audit", "system.consumer_failed", {
                "consumer": sub.name,
                "event_id": ev.event_id,
                "event_type": ev.type,
                "traceback": traceback.format_exc(limit=8),
            }, ev.observed_at_hlc)
            return
        sub.seen.add(key)
        sub.applied += 1

    # ---------------------------------------------------------------- replay

    def replay(self, *, after_seq: int = 0) -> int:
        """Re-deliver the durable log in HLC order.

        This is recovery, and it is also A-033.2: replaying a stream twice must
        leave state byte-identical, with the second pass counted as duplicates
        rather than applied. Consumer idempotency is what makes that true, and
        this method is how it gets exercised.
        """
        n = 0
        for rec in self._store.read("log", after_seq=after_seq):
            # Upcast on read, never on write, and never back into the store.
            # `rec.body` is left exactly as it was read: the codec returns a new
            # dict and holds no store handle to write one back through.
            ev = Event.from_dict(
                self.codec.upcast(rec.body, to_version=ENVELOPE_SCHEMA_VERSION,
                                  event_type=rec.kind))
            with self._lock:
                subs = list(self._subs.get(ev.type, ()))
            for sub in subs:
                self._deliver(sub, ev)
            n += 1
        return n

    # ------------------------------------------------------------ inspection

    def stats(self) -> dict:
        with self._lock:
            return {
                "published": self._published,
                "consumers": {
                    s.name: {
                        "event_type": s.event_type,
                        "applied": s.applied,
                        "suppressed_duplicates": s.suppressed_duplicates,
                        "failures": s.failures,
                    }
                    for subs in self._subs.values() for s in subs
                },
            }
