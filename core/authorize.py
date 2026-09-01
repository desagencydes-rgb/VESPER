"""DF-AUTHORIZE — the single evaluator every action resolves against.

    effective_level = min(grant.max_level,
                          capability.declared_level(args),
                          context_ceiling)

    authorized  <=>  effective_level >= capability.required_level(args)
                     AND now < grant.expiry
                     AND target IN grant.target_scope
                     AND grant.lease_epoch is current

THERE IS NO AMBIENT AUTHORITY. REM-003 puts it precisely: *"Default deny is not
a configuration setting; it is the absence of any code path that produces a
level without a grant."* So `authorize()` has no branch that yields anything
above `L0` without a matching grant — not a default, not a fallback, not an
admin override. A subject holding no grant acts at `L0`, full stop.

DELEGATION ATTENUATION IS THE REAL ESCALATION PATH. RB-028's prohibition on
self-grant was never the exposure; UNATTENUATED INHERITANCE was. A sub-agent
that inherits its parent's grants unchanged turns one owner confirmation into
six agents' worth of external action. So `attenuate()` returns a SUBSET, always:
`delegable` defaults false, and L4/L5 are never delegable at all.

A CONSUMED L4 GRANT CANNOT AUTHORIZE A SECOND ACTION (INV-AUTH-2). One
confirmation authorises one action instance — not a task, not a session. The
grant carries `issued_for_command_id` and is marked consumed on use.

PDP UNREACHABLE MEANS DENY ABOVE L1, AND AUDIT IT (INV-AUTH-4). Not "fall back
to cached policy", not "allow and reconcile later". The audit matters as much
as the denial: a denial nobody recorded is indistinguishable from an action
that never happened.

EVERY DENIAL NAMES ITS REASON from a closed output domain (A-014). A denial
reading "not authorized" tells the owner nothing about what to fix, and a
system that cannot explain its refusals trains people to route around them.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Any

from .bus import EventBus
from .capabilities import prohibited
from .capability import LEVEL_RANK, LEVELS, Capability, CapabilityRegistry

# A-014: "each denial names its reason from DF-AUTHORIZE's output domain".
# Closed vocabulary; a new reason is a deliberate addition, not a free string.
DENY_REASONS = (
    "no_grant",                 # no grant at all -> capped at L0
    "grant_expired",
    "target_out_of_scope",
    "stale_lease_epoch",
    "grant_consumed",
    "below_required_level",
    "context_ceiling",
    "pdp_unavailable",
    "not_delegable",
    "self_modification_boundary",
    "owner_confirmation_required",
    "prohibited",               # no grant satisfies this, including L5
)

NEVER_DELEGABLE = ("L4", "L5")


@dataclass(slots=True)
class Grant:
    grant_id: str
    subject: str
    capability_id: str
    target_scope: tuple
    max_level: str
    expiry_ms: int
    lease_epoch: int
    delegable: bool = False
    issued_by: str = "owner"
    issued_for_command_id: str | None = None
    consumed: bool = False
    parent_grant_id: str | None = None

    def to_dict(self) -> dict:
        return {"grant_id": self.grant_id, "subject": self.subject,
                "capability_id": self.capability_id,
                "target_scope": list(self.target_scope),
                "max_level": self.max_level, "delegable": self.delegable,
                "consumed": self.consumed,
                "parent_grant_id": self.parent_grant_id}


@dataclass(frozen=True, slots=True)
class Decision:
    authorized: bool
    effective_level: str
    reason: str
    capability_id: str
    subject: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"authorized": self.authorized,
                "effective_level": self.effective_level, "reason": self.reason,
                "capability_id": self.capability_id, "subject": self.subject,
                "detail": self.detail}


def _min_level(*levels: str) -> str:
    return min(levels, key=lambda l: LEVEL_RANK[l])


class PolicyDecisionPoint:
    """Holds grants and answers DF-AUTHORIZE. Lives in the `policy` domain."""

    def __init__(self, bus: EventBus, registry: CapabilityRegistry, *,
                 now_ms: Any = None) -> None:
        self._bus = bus
        self._registry = registry
        self._grants: dict[str, Grant] = {}
        self._lock = threading.RLock()
        self.available = True          # A-024.3 injects False
        self._now_ms = now_ms or (lambda: 0)

    # ----------------------------------------------------------------- grants

    def issue(self, grant: Grant) -> Grant:
        if grant.max_level in NEVER_DELEGABLE and grant.delegable:
            raise ValueError(
                f"{grant.max_level} grants are NEVER delegable (INV-AUTH-2). One "
                "confirmation authorises one action instance, not a session and "
                "not six agents' worth of external action.")
        with self._lock:
            self._grants[grant.grant_id] = grant
        return grant

    def find(self, subject: str, capability_id: str) -> Grant | None:
        with self._lock:
            for g in self._grants.values():
                if g.subject == subject and g.capability_id == capability_id:
                    return g
        return None

    def attenuate(self, parent: Grant, child_subject: str,
                  child_grant_id: str) -> Grant | None:
        """DF-ATTENUATE. Returns a SUBSET grant, or None.

        A-024.6: a grant marked `delegable=false` (the default) produces an
        EMPTY child set for that capability -- not a weaker grant, none at all.
        """
        if not parent.delegable or parent.max_level in NEVER_DELEGABLE:
            self._bus.publish(
                "authz.delegation_refused", subject=child_subject,
                payload={"parent_grant_id": parent.grant_id,
                         "capability_id": parent.capability_id,
                         "reason": ("not_delegable" if not parent.delegable
                                    else "L4/L5 are never delegable"),
                         "child_set": []},
                component="authz")
            return None
        child = replace(parent, grant_id=child_grant_id, subject=child_subject,
                        parent_grant_id=parent.grant_id, delegable=False,
                        consumed=False)
        self.issue(child)
        return child

    # ------------------------------------------------------------- the answer

    def authorize(self, *, subject: str, capability_id: str, args: dict,
                  target: str, context_ceiling: str = "L5",
                  current_lease_epoch: int = 0,
                  command_id: str | None = None) -> Decision:
        cap = self._registry.get(capability_id)
        declared = cap.declared_level(args)
        required = cap.required(args)

        # ASKED BEFORE EVERYTHING, INCLUDING BEFORE THE GRANT. A tier that a
        # grant could open is not this tier, so the check cannot sit anywhere a
        # grant is consulted first. The ladder handles "how dangerous"; this
        # handles "and what if the owner says yes anyway", for the small set of
        # acts whose only effect is to remove the machinery that would have
        # caught a mistake.
        why = prohibited(capability_id, args)
        if why is not None:
            return self._deny(subject, cap, "prohibited", "L0", why)

        # INV-AUTH-4. Checked before anything else that could accidentally
        # produce a level: a PDP that cannot be consulted has not said yes.
        if not self.available:
            if LEVEL_RANK[required] > LEVEL_RANK["L1"]:
                return self._deny(subject, cap, "pdp_unavailable", "L0",
                                  f"PDP unreachable and {capability_id} requires "
                                  f"{required}; deny above L1 and audit")

        grant = self.find(subject, capability_id)
        if grant is None:
            # THE no-ambient-authority path. There is no branch below that can
            # raise this above L0.
            return self._deny(subject, cap, "no_grant", "L0",
                              "subject holds no grant for this capability and is "
                              "therefore capped at L0")
        if grant.consumed:
            return self._deny(subject, cap, "grant_consumed", "L0",
                              f"grant {grant.grant_id} was already spent; one "
                              "confirmation authorises one action instance")
        if self._now_ms() >= grant.expiry_ms:
            return self._deny(subject, cap, "grant_expired", "L0",
                              f"expired at {grant.expiry_ms}")
        if target not in grant.target_scope:
            return self._deny(subject, cap, "target_out_of_scope", "L0",
                              f"target {target!r} not in {list(grant.target_scope)}")
        if grant.lease_epoch != current_lease_epoch:
            return self._deny(subject, cap, "stale_lease_epoch", "L0",
                              f"grant epoch {grant.lease_epoch} != current "
                              f"{current_lease_epoch}")
        if (cap.requires_owner_confirmation
                and grant.issued_for_command_id
                and grant.issued_for_command_id != command_id):
            return self._deny(subject, cap, "owner_confirmation_required", "L0",
                              f"grant is bound to command "
                              f"{grant.issued_for_command_id!r}, not {command_id!r}")

        effective = _min_level(grant.max_level, declared, context_ceiling)
        if LEVEL_RANK[effective] < LEVEL_RANK[required]:
            reason = ("context_ceiling"
                      if LEVEL_RANK[context_ceiling] < LEVEL_RANK[required]
                      else "below_required_level")
            return self._deny(subject, cap, reason, effective,
                              f"effective {effective} < required {required} "
                              f"(grant {grant.max_level}, declared {declared}, "
                              f"ceiling {context_ceiling})")

        # THE LEVEL ALONE DECIDES, owner decision 2026-08-31. This read
        # `cap.requires_owner_confirmation and grant.max_level in
        # NEVER_DELEGABLE`, so an L4 grant on a capability that did not declare
        # owner confirmation was NEVER SPENT BY USE -- one confirmation
        # authorised action after action. Verified before the change: the same
        # grant authorized twice in a row.
        #
        # Two things made it survive. A-024.2's fixture declares
        # `requires_owner_confirmation=True`, so the acceptance test only ever
        # exercised the covered branch; and CI-013 was PENDING until 2026-08-31
        # and gated nothing. INV-AUTH-2's own text mentions only the level --
        # "L4/L5 are never delegable and bind to one command instance" -- and
        # `issue()` twelve lines up already refuses an L4-delegable grant on the
        # level alone. Two triggers for one class of grant; this is now one.
        if grant.max_level in NEVER_DELEGABLE:
            with self._lock:
                grant.consumed = True   # INV-AUTH-2: single use

        d = Decision(True, effective, "authorized", capability_id, subject,
                     f"grant {grant.max_level}, declared {declared}, "
                     f"ceiling {context_ceiling}, required {required}")
        self._bus.publish("authz.decision", subject=subject, payload=d.to_dict(),
                          component="authz")
        return d

    def _deny(self, subject: str, cap: Capability, reason: str,
              level: str, detail: str) -> Decision:
        if reason not in DENY_REASONS:
            # NOT an assert: `python -O` strips asserts, and this is the check
            # that keeps A-014's "each denial names its reason from
            # DF-AUTHORIZE's output domain" true at runtime rather than only
            # under test.
            raise ValueError(
                f"denial reason {reason!r} is outside DF-AUTHORIZE's output "
                f"domain {DENY_REASONS}. A denial the owner cannot look up is "
                "one that trains people to route around the system.")
        d = Decision(False, level, reason, cap.capability_id, subject, detail)
        # Every denial is audited. A denial nobody recorded is
        # indistinguishable from an action that never happened.
        self._bus.publish("authz.denied", subject=subject, payload=d.to_dict(),
                          component="authz")
        return d
