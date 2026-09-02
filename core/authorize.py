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
    "weak_authorization",       # nobody asked for this strongly enough
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


# ------------------------------------------------- how strongly was this asked

# THE SECOND AXIS, AND THE ONE THIS LADDER DID NOT HAVE. Every level rule here
# answers "how dangerous is this". Codex's guardian answers that AND "how
# strongly did the user actually authorize it", with `Unknown` first-class --
# and the two come apart in exactly the case this whole design exists for.
#
# A POISONED proposer emits something dangerous, and the danger axis catches
# it. A STEERED proposer emits something entirely reasonable that the owner
# never asked for: `rm` on the right file, a message to the wrong person, a
# write nobody requested. On the danger axis that is unremarkable. Only the
# authorization axis sees it.
#
# We wrote "safety does not depend on the proposer being right" as the central
# sentence of this system. One ladder cannot carry it.
AUTHORIZATION = ("owner_explicit", "owner_task", "unknown")

# The ceiling each strength permits for a state-changing capability. Same shape
# as `taint.ALLOWED_LEVEL` and deliberately independent of it: taint is about
# the provenance of the CONTENT, this is about the provenance of the REQUEST,
# and an action can be weak on either axis while impeccable on the other.
AUTHORIZATION_CEILING = {
    # The owner asked for this, in this turn, in words.
    "owner_explicit": "L5",
    # A later step of a task the owner asked for. They authorised the errand
    # and not each move inside it, so a step that reaches further than the
    # errand plausibly meant is a question rather than a continuation.
    "owner_task": "L3",
    # Nobody asked. Autonomous work, and `unknown` rather than `none` because
    # the honest statement is that this system cannot tell the difference
    # between "the owner would want this" and "the proposer decided to".
    "unknown": "L2",
}


def authorization_ceiling(strength: str) -> str:
    """The ceiling for this strength. An unrecognised one is the lowest there is.

    FAIL CLOSED ON THE NAME TOO. A typo in a caller's string must not read as
    full authority, which is what `.get(strength, "L5")` would have done.
    """
    return AUTHORIZATION_CEILING.get(strength, "L0")


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
        """The strongest grant this subject can actually use for this.

        IT RETURNED THE FIRST MATCH IN INSERTION ORDER, AND THAT MADE THE
        CONFIRMATION LADDER UNREACHABLE. `Actor._issue_standing` issues one L2
        grant per capability at construction, so it is always first -- and a
        stronger grant issued later, which is exactly what answering a
        confirmation produces, was never found. Measured 2026-09-02: an
        answered question issued an L5 single-use grant, `find` returned the
        standing L2, and the approved action was refused `below_required_level`
        a second time. The owner could say yes and nothing would happen.

        A CONSUMED OR EXPIRED GRANT NO LONGER MASKS A USABLE ONE either, which
        was the same bug wearing different clothes: the consumed/expired checks
        run on whatever `find` returned, so a spent single-use grant sitting
        ahead of a live standing grant denied everything with `grant_consumed`.

        AND WHEN NOTHING IS USABLE IT STILL RETURNS ONE, deliberately. The
        caller distinguishes `no_grant` from `grant_consumed` from
        `grant_expired`, and collapsing all three into "no grant" would tell
        the owner they never had permission when in fact they spent it.

        THIS IS NOT AMBIENT AUTHORITY. Every grant returned here was issued to
        this subject for this capability; picking the strongest of them is not
        a path to a level nobody granted, which is what INV-AUTH-1 forbids. The
        bound on a lingering strong grant is its own expiry -- an answered
        grant lives five minutes and is single-use.
        """
        with self._lock:
            cands = [g for g in self._grants.values()
                     if g.subject == subject and g.capability_id == capability_id]
        if not cands:
            return None
        now = self._now_ms()
        usable = [g for g in cands if not g.consumed and now < g.expiry_ms]
        if not usable:
            # WHICH REFUSAL THE OWNER HEARS DEPENDS ON WHICH GRANT WE RETURN,
            # so it is chosen rather than left to insertion order. "You already
            # spent this" is something they can act on -- ask again -- and "it
            # expired" is not. A subject holding one spent and one stale grant
            # should hear the actionable one.
            return next((g for g in cands
                         if g.consumed and now < g.expiry_ms), cands[0])
        return max(usable, key=lambda g: LEVEL_RANK[g.max_level])

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
                  authorization: str = "owner_explicit",
                  current_lease_epoch: int = 0,
                  command_id: str | None = None,
                  consume: bool = True) -> Decision:
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

        auth_ceiling = authorization_ceiling(authorization)
        effective = _min_level(grant.max_level, declared, context_ceiling,
                               auth_ceiling)
        if LEVEL_RANK[effective] < LEVEL_RANK[required]:
            # THE REASON NAMES THE AXIS THAT BOUND. "Refused" is not useful to
            # the owner; "refused because nobody asked for this" and "refused
            # because a web page is in context" are different answers to
            # different questions, and only one of them is something they can
            # resolve by saying yes.
            if LEVEL_RANK[auth_ceiling] < LEVEL_RANK[required]:
                reason = "weak_authorization"
            elif LEVEL_RANK[context_ceiling] < LEVEL_RANK[required]:
                reason = "context_ceiling"
            else:
                reason = "below_required_level"
            return self._deny(subject, cap, reason, effective,
                              f"effective {effective} < required {required} "
                              f"(grant {grant.max_level}, declared {declared}, "
                              f"ceiling {context_ceiling}, "
                              f"authorization {authorization}/{auth_ceiling})")

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
        # SPENT BY THE CHECK THAT IS ABOUT TO ACT, AND ONLY BY IT. One
        # authorize call is one use -- the contract is explicit, and a grant
        # bound to `cmd-2` is refused a SECOND authorize for `cmd-2`. But a
        # command is checked twice by design: the actor asks first, purely to
        # decide whether a refusal should become a QUESTION, and the executor
        # re-checks immediately before invoking, which is the binding one.
        #
        # With both consuming, an L4/L5 grant was spent by the question-routing
        # check and gone by the time anything could act on it. Measured
        # 2026-09-02: the owner approved an fs.write, an L5 grant was issued,
        # the actor's pre-check consumed it, and the executor then refused
        # `below_required_level` against the standing L2 left behind. The owner
        # said yes and nothing happened. It had never fired because no action
        # above L1 had ever reached this path -- `no-ambient-authority` says so
        # in its own REACH note.
        #
        # `consume=False` DOES NOT AUTHORISE ANYTHING. It answers "would this be
        # permitted", which is what a caller deciding whether to ask needs, and
        # it is not a second path to a level: nothing executes on its verdict.
        if grant.max_level in NEVER_DELEGABLE and consume:
            with self._lock:
                grant.consumed = True   # INV-AUTH-2: single use

        d = Decision(True, effective, "authorized", capability_id, subject,
                     f"grant {grant.max_level}, declared {declared}, "
                     f"ceiling {context_ceiling}, "
                     f"authorization {authorization}/{auth_ceiling}, "
                     f"required {required}")
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
