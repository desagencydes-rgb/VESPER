"""Control-plane ownership — leases, fencing, and the refusal to self-promote.

SEVEN INDEPENDENTLY LEASED DOMAINS, not one global lock. `tasks`, `world`,
`memory`, `devices`, `policy`, `autonomy_queue`, `alarms`. Independence is the
point: a node that can run tasks but has lost the `devices` lease degrades on
one axis instead of stopping, and REM-002's failure table is written per
domain because that is how failure actually arrives.

THE THREE RULES THAT ARE EASY TO GET WRONG, and each is a named invariant:

  INV-OWN-2  A partitioned node MAY NOT SELF-PROMOTE. The instinct is to keep
             working -- the node is up, the work is queued, the user is
             waiting. But both sides of a partition feel exactly like "the
             other node died", and if both promote there are two owners
             issuing external actions. `DF-PROMOTE` returns NO_PROMOTION on
             every side when partition is suspected, and A-034.4 asserts the
             system degrades read-only and asks for an operator rather than
             guessing.

  INV-OWN-3  Every write carries its epoch; stale ones are refused AT THE
             STORAGE LAYER. Not here. This module hands the epoch down; the
             single-statement conditional UPDATE in store.py is what actually
             fences. Enforcement in the caller would be advisory.

  INV-OWN-4  `policy`, `autonomy_queue` and `alarms` REFUSE non-owner writes
             rather than queueing them. A queued write is a write that will
             happen later without authority -- worse than a rejection, because
             the rejection is visible now and the queue fires silently.

A HOLDER THAT CANNOT RENEW SELF-DEMOTES AT TTL. It does not keep writing
hopefully. The failure direction is chosen deliberately: stop, flush,
checkpoint, emit `control.lease_lost`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .bus import EventBus
from .hlc import HLC, HybridLogicalClock
from .store import DOMAINS, StoreSet

# INV-OWN-4. These three refuse rather than queue.
REFUSE_NON_OWNER = ("policy", "autonomy_queue", "alarms")

DEFAULT_TTL_MS = 15_000


class NotOwner(Exception):
    """A write was attempted against a domain this node does not hold."""


class PromotionRefused(Exception):
    """Promotion was refused. INV-OWN-2 — this is correct behaviour, not a bug."""


@dataclass(slots=True)
class Held:
    domain: str
    epoch: int
    acquired_at: HLC
    ttl_ms: int
    renewed_monotonic: float


class LeaseManager:
    """Per-node view of which domains this node owns, and under which epoch.

    TTL is measured on the MONOTONIC clock, not the wall clock and not the HLC.
    Wall clock can jump; HLC is an ordering device with no duration semantics --
    the gap between two HLC stamps is not a number of seconds. Expiry is a
    local duration question, which is exactly what monotonic time answers.
    """

    def __init__(self, store: StoreSet, clock: HybridLogicalClock, bus: EventBus,
                 *, node_id: str, ttl_ms: int = DEFAULT_TTL_MS,
                 monotonic: Callable[[], float] | None = None) -> None:
        self._store = store
        self._clock = clock
        self._bus = bus
        self._node_id = node_id
        self._ttl_ms = ttl_ms
        self._monotonic = monotonic or time.monotonic
        self._held: dict[str, Held] = {}
        self._partition_suspected = False
        self._lock = threading.RLock()

    # --------------------------------------------------------------- acquire

    def acquire(self, domain: str) -> int:
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}")
        with self._lock:
            epoch = self._store.claim_domain(domain, self._node_id, self._clock.now())
            at = self._clock.now()
            self._held[domain] = Held(domain, epoch, at, self._ttl_ms,
                                      self._monotonic())
            self._bus.publish("control.lease_acquired", subject=domain,
                              payload={"domain": domain, "epoch": epoch,
                                       "holder": self._node_id, "ttl_ms": self._ttl_ms},
                              component="lease", at=at)
            return epoch

    def promote(self, domain: str, *, quorum: bool) -> int:
        """Promote to owner after the previous holder is believed gone.

        `quorum` is the caller's evidence that this node can see enough of the
        fabric to distinguish "the other node died" from "I am the one cut
        off". Without it, promotion is refused -- A-034.4.
        """
        with self._lock:
            if self._partition_suspected or not quorum:
                self._bus.publish(
                    "control.promotion_requires_operator", subject=domain,
                    payload={"domain": domain,
                             "partition_suspected": self._partition_suspected,
                             "quorum": quorum,
                             "reason": ("INV-OWN-2: a partitioned node cannot tell "
                                        "'the peer died' from 'I am isolated'. Both "
                                        "sides would promote and issue external "
                                        "actions. Degrading read-only.")},
                    component="lease")
                raise PromotionRefused(
                    f"promotion to '{domain}' refused: "
                    f"partition_suspected={self._partition_suspected}, quorum={quorum}")
            return self.acquire(domain)

    # ---------------------------------------------------------------- status

    def owns(self, domain: str) -> bool:
        with self._lock:
            h = self._held.get(domain)
            if h is None:
                return False
            if self._expired(h):
                self._demote(domain, "ttl_expired")
                return False
            # The store is the authority, not this node's memory of it. If
            # another node has claimed the domain the epoch has moved on, and
            # believing our own cached copy is how a fenced node keeps writing.
            return self._store.domain_epoch(domain) == h.epoch

    def epoch(self, domain: str) -> int:
        """The epoch to write under. Raises if this node is not the owner."""
        with self._lock:
            if not self.owns(domain):
                raise NotOwner(
                    f"node {self._node_id} does not hold the '{domain}' lease"
                    + (" -- and this domain REFUSES non-owner writes rather than "
                       "queueing them (INV-OWN-4)" if domain in REFUSE_NON_OWNER else ""))
            return self._held[domain].epoch

    def _expired(self, h: Held) -> bool:
        return (self._monotonic() - h.renewed_monotonic) * 1000.0 > h.ttl_ms

    def renew(self, domain: str) -> bool:
        with self._lock:
            h = self._held.get(domain)
            if h is None:
                return False
            if self._store.domain_epoch(domain) != h.epoch:
                self._demote(domain, "fenced_by_newer_epoch")
                return False
            h.renewed_monotonic = self._monotonic()
            return True

    def tick(self) -> None:
        """Expire anything past TTL. Called by the supervisor's heartbeat."""
        with self._lock:
            for domain, h in list(self._held.items()):
                if self._expired(h):
                    self._demote(domain, "ttl_expired")

    def _demote(self, domain: str, reason: str) -> None:
        h = self._held.pop(domain, None)
        if h is None:
            return
        self._bus.publish("control.lease_lost", subject=domain,
                          payload={"domain": domain, "epoch": h.epoch,
                                   "reason": reason,
                                   "note": ("holder self-demoted rather than "
                                            "continuing to write hopefully")},
                          component="lease")

    def release(self, domain: str) -> None:
        with self._lock:
            h = self._held.pop(domain, None)
            if h is not None:
                self._store.release_domain(domain, self._clock.now())
                self._bus.publish("control.lease_released", subject=domain,
                                  payload={"domain": domain, "epoch": h.epoch},
                                  component="lease")

    # ------------------------------------------------------------- partition

    def set_partition_suspected(self, suspected: bool) -> None:
        with self._lock:
            if suspected == self._partition_suspected:
                return
            self._partition_suspected = suspected
            self._bus.publish("control.partition_suspected", subject="fabric",
                              payload={"suspected": suspected}, component="lease")

    @property
    def partition_suspected(self) -> bool:
        return self._partition_suspected

    def external_action_permitted(self, level: str) -> bool:
        """INV-OWN-2: a partitioned node may not issue L4+ external actions.

        The failure direction is asymmetric on purpose. Suppressing an external
        action during a partition costs a delay; issuing it twice, once from
        each side, sends the message twice, and there is no undo for that.
        """
        if not self._partition_suspected:
            return True
        try:
            return int(level.lstrip("Ll")) < 4
        except ValueError:
            return False

    def fence(self, domain: str, reason: str) -> None:
        with self._lock:
            at = self._clock.now()
            self._store.fence_domain(domain, reason, at)
            self._held.pop(domain, None)
            self._bus.publish("control.fenced", subject=domain,
                              payload={"domain": domain, "reason": reason},
                              component="lease", at=at)

    def held_domains(self) -> dict[str, int]:
        with self._lock:
            return {d: h.epoch for d, h in self._held.items()}
