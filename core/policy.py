"""Policy skeleton — the decision points F0 must not leave undefined.

DELIBERATELY A SKELETON. F0's job is to make sure every policy question has a
NAMED place to be answered and a safe default, so that later stages fill in
decisions rather than discovering that the question was never asked. The
temptation is to implement authorization properly here; that belongs to F4 and
guessing at it now would produce a security boundary nobody reviewed.

WHAT IS REAL HERE, and not deferred:

  * The refusal path. `policy`, `autonomy_queue` and `alarms` refuse non-owner
    writes rather than queueing them (INV-OWN-4). That is enforced now, because
    a queue added today would fire tomorrow without authority.

  * The default. Every undecided policy question answers DENY, and answering it
    emits a record saying it was undecided. An undecided question that defaults
    to allow is indistinguishable from a decision to allow, and it silently
    becomes one the moment anybody relies on it.

  * Autonomy levels L0-L5, with the L4+ partition rule wired to the lease
    manager, because that is a continuity property rather than an authorization
    one and it has to hold before F4 exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bus import EventBus
from .lease import REFUSE_NON_OWNER, LeaseManager, NotOwner

# L0 observe · L1 local reversible · L2 local durable · L3 external read
# L4 external write (irreversible outside the system) · L5 owner-impersonating
AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str
    rule: str
    decided: bool  # False => no rule existed and the default denied it


class PolicySkeleton:
    def __init__(self, bus: EventBus, leases: LeaseManager) -> None:
        self._bus = bus
        self._leases = leases

    def may_write(self, domain: str) -> Decision:
        """INV-OWN-1 / INV-OWN-4. Refuses; never queues."""
        try:
            self._leases.epoch(domain)
        except NotOwner as e:
            d = Decision(False, str(e), "INV-OWN-1", True)
            self._bus.publish("policy.write_refused", subject=domain,
                              payload={"domain": domain, "reason": d.reason,
                                       "queued": False,
                                       "note": ("INV-OWN-4: refused, not queued -- a "
                                                "queued write is one that happens "
                                                "later without authority")
                                       if domain in REFUSE_NON_OWNER else None},
                              component="policy")
            return d
        return Decision(True, "node holds the lease", "INV-OWN-1", True)

    def may_act(self, level: str, *, capability: str) -> Decision:
        if level not in AUTONOMY_LEVELS:
            return self._undecided(f"unknown autonomy level {level!r}", capability)
        if not self._leases.external_action_permitted(level):
            d = Decision(False, ("partition suspected: L4+ external actions are "
                                 "suppressed on every side"), "INV-OWN-2", True)
            self._bus.publish("policy.action_suppressed", subject=capability,
                              payload={"capability": capability, "level": level,
                                       "reason": d.reason}, component="policy")
            return d
        if level in ("L4", "L5"):
            # Not implemented here on purpose. F4 owns authorization, and a
            # placeholder that allowed L4 would be a real grant made by
            # accident.
            return self._undecided(
                f"{level} requires an authorization grant; F4 owns that decision",
                capability)
        return Decision(True, f"{level} is within the F0 skeleton's remit",
                        "F0-skeleton", True)

    def _undecided(self, reason: str, subject: str) -> Decision:
        d = Decision(False, reason, "default-deny", False)
        self._bus.publish("policy.undecided", subject=subject,
                          payload={"reason": reason, "defaulted_to": "DENY",
                                   "note": ("an undecided question that defaults to "
                                            "allow becomes a decision to allow the "
                                            "moment anything relies on it")},
                          component="policy")
        return d
