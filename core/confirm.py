"""Owner confirmation for an action VESPER may not take on its own.

THE OWNER'S DESIGN, 2026-08-31, in their own terms: a single-use action stops,
VESPER explains the situation, and it asks for permission by voice at that
moment. If the owner is not there it either waits and asks the moment they are
back, or -- if it is a little critical and cannot wait -- it calls them.

WHAT THIS MODULE IS AND IS NOT. It does not decide whether an action is
permitted; `core/authorize.py` does that and its refusal is the input here. This
turns a refusal into a QUESTION and routes that question through the
interruption budget, which already knows what may reach the owner and what
waits. The refusal is not softened: until the owner answers, the action has not
happened.

A CONFIRMATION REQUEST DOES NOT DECAY, and that single flag is what implements
the owner's second branch. `core/interruption.py` drops a decaying candidate
that will not fit the budget and QUEUES a non-decaying one -- "worth the same
tomorrow, so it waits". A question about an action the owner asked for is worth
the same when they get back, so it queues, and `surface_queued()` puts it in
front of them at the next natural boundary. Nothing extra had to be built for
that branch; marking it correctly was the whole of it.

THE THIRD BRANCH IS NOT BUILT AND MUST NOT BE FAKED. Calling the owner needs a
node with a TELEPHONY capability, and no enrolled node declares one. (Written as
a capability and not as a handset: `INV-HW-1` -- the profile, never the device.
A named product here would be wrong the moment the hardware changed, and this
file would then describe a fabric that no longer exists.) The modality is
declared in
`contracts/policy/interruption_budget.toml` with `available = false` so the
policy slot exists and is visible; `urgent()` refuses rather than silently
degrading to a queued question, because an urgent confirmation that quietly
waits is the failure the third branch exists to prevent.

AND THE FIRST BRANCH IS GATED ON SOMETHING NOTHING WRITES. `world.owner.
attention_state` has no producer -- the trigger registry reads it, the
interruption budget takes it as a parameter, and no sensor populates it. So
VESPER cannot currently tell whether the owner is there to be asked. That is
recorded rather than worked around: an unknown attention state falls to
`DEFAULT_BUDGET = 0` and the question QUEUES. Defaulting it to `available` would
make the voice branch testable and would turn "I do not know if you are there"
into "speak now", which is the declared-versus-measured error this corpus keeps
finding (`INV-HW-2`).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus
from .interruption import Candidate, InterruptionBudget

# `world.owner.attention_state` when nothing has written it. Deliberately not a
# member of ATTENTION_STATES: it is the absence of one, and it must not be
# comparable to a real state or a budget row could accidentally serve it.
ATTENTION_UNKNOWN = "UNKNOWN"

# How a confirmation reached, or would reach, the owner. Costs mirror
# `interruption_budget.toml`'s modality_cost, normalised to the 0..1 the
# interruption candidate uses.
ASK_BY_VOICE = "speech"
ASK_BY_PHONE = "phone_call"

# The reasons an authorization refusal becomes a QUESTION rather than an ending.
# A refusal for any other reason is not a confirmation problem: an expired lease
# or a stale epoch is not something the owner can answer in the moment.
CONFIRMABLE_REASONS = ("grant_consumed", "owner_confirmation_required",
                       "no_grant", "below_required_level",
                       "weak_authorization", "outside_workspace")

# `outside_workspace` IS THE POINT OF WORKSPACE MODE, NOT A FAILURE OF IT. The
# owner chose "free in your folder, ask before anything else", so an action
# reaching outside is precisely the case a question exists for -- and one they
# can settle with a yes without leaving the mode. Excluding it would have made
# workspace mode a dead end: VESPER would refuse and the owner's only recourse
# would be to switch the whole machine to `auto`.

# `weak_authorization` MEANS "NOBODY ASKED FOR THIS STRONGLY ENOUGH", WHICH IS
# THE ONE REFUSAL A QUESTION EXISTS TO RESOLVE. The authorization ceiling is
# L3 for a later step of a turn and L2 for autonomous work, so any step above
# those refused with this reason -- and because it was excluded here, VESPER
# could not ask about it. Measured 2026-09-04: the owner asked for a script to
# be run, the second step needed more than the ceiling carried, and they were
# told "it needs your permission" by a system that had already decided it
# could not request that permission.
#
# `context_ceiling` STAYS OUT, and the distinction is the whole point. That one
# means a web page or a model's own output is in context, and INV-ACT-3 says
# content entering the system may never raise authority -- so an owner saying
# yes must NOT lift it, or steered content would have found a way to ask the
# owner for its own promotion. "Nobody asked" is answerable by the owner
# asking; "something untrusted is in the room" is not.

# `below_required_level` WAS MISSING AND IT IS THE COMMON CASE. Measured
# 2026-09-02: `fs.write` on a new file and on an existing one both refuse with
# `below_required_level` against the standing L2 grant -- so the single most
# frequent refusal in the act path could not become a question, and VESPER's
# only reachable ask was the rarer `no_grant`. The exclusion was reasoned as "an
# expired lease or a stale epoch is not something the owner can answer in the
# moment", which is true of those and is NOT true of this one: "this needs more
# permission than I hold" is precisely the situation the owner described when
# they specified this ladder -- a single-use action stops, VESPER explains, and
# it asks. A confirmation path that cannot be reached by the ordinary refusal is
# a confirmation path for exceptions only.


class NotTheQuestionInFront(Exception):
    """An answer arrived for a question that was not being asked.

    RAISED RATHER THAN IGNORED, because the two readings of "the owner said
    yes while this was queued" are opposite: they meant this question, or they
    meant something else entirely and this one happened to be open. Guessing
    the first is how a confirmation becomes a formality; guessing the second
    loses a real answer. Asking again costs one sentence and settles it.
    """


def requeue(broker: "ConfirmationBroker") -> int:
    """Anything the owner did not answer goes back to queued.

    CALLED WHEN THE OWNER DOES SOMETHING ELSE -- adds a task, changes the
    subject, asks what the action would actually do. None of those is an
    answer, and all of them mean the question is no longer the thing in front
    of them. It returns to the queue and must be surfaced again before a bare
    "yes" can settle it.

    THE QUESTION ITSELF SURVIVES. `core/interruption.py` marks a confirmation
    non-decaying because it is "worth the same tomorrow", which is the owner's
    own design for being away. This does not drop anything; it only stops an
    unrelated utterance from settling it.
    """
    n = 0
    with broker._lock:                                   # noqa: SLF001
        moved = [r for r in broker._pending.values()     # noqa: SLF001
                 if r.asked and not r.answered]
        for req in moved:
            req.asked = False
            n += 1
    # BACK INTO THE INTERRUPTION QUEUE, not merely marked. Clearing the flag
    # alone made the question unanswerable AND unaskable: `surface()` returns
    # what the budget releases, and a question that was spoken at request time
    # never entered the queue, so nothing would ever put it back in front of
    # the owner. It would have waited forever for a boundary it was not
    # standing at -- a question that cannot be answered and cannot be re-asked
    # is a question that was silently dropped, which is exactly what
    # `decays=False` exists to prevent.
    #
    # `decays=False` AGAIN, for the same reason as the first time: it is worth
    # the same when they come back, so it waits rather than being dropped for
    # not fitting the budget.
    for req in moved:
        broker._budget.allocate(                         # noqa: SLF001
            [Candidate(candidate_id=req.request_id, expected_value=1.0,
                       decays=False, interruption_cost=0.8, is_alarm=False)],
            period="FREE_TIME", attention_state=ATTENTION_UNKNOWN)
    if n:
        broker._bus.publish(                             # noqa: SLF001
            "confirm.requeued", subject="owner",
            payload={"count": n, "note": ("the owner did something else; the "
                                          "question waits to be asked again")},
            component="confirm")
    return n


class PhoneUnavailable(Exception):
    """The urgent branch was taken and no phone is enrolled to take it."""


@dataclass(slots=True)
class ConfirmationRequest:
    """One question, with everything the owner needs to answer it."""

    request_id: str
    capability_id: str
    target: str
    level: str
    reason: str
    explanation: str
    subject: str = "owner"
    answered: bool = False
    granted: bool = False
    # IS THIS QUESTION IN FRONT OF THE OWNER RIGHT NOW?
    #
    # A BARE "YES" IS NOT AN ANSWER TO WHATEVER HAPPENS TO BE PENDING. The
    # owner may hear a question, say nothing about it, add three unrelated
    # tasks, and then say "yes" to something else entirely -- and a matcher
    # that took any affirmative utterance would attribute that to the oldest
    # open question and act on it. So an answer only settles a question that is
    # ASKED: surfaced, and nothing else said since.
    #
    # ANYTHING ELSE RE-QUEUES IT rather than settling it, which is also how
    # "they discussed it and never actually answered" stays distinguishable
    # from "they agreed". Silence is not consent, and neither is having been
    # nearby while VESPER was talking.
    asked: bool = False

    def to_dict(self) -> dict:
        return {"request_id": self.request_id, "asked": self.asked,
                "capability_id": self.capability_id, "target": self.target,
                "level": self.level, "reason": self.reason,
                "explanation": self.explanation, "answered": self.answered,
                "granted": self.granted}


def explain(capability_id: str, target: str, level: str, reason: str) -> str:
    """The sentence the owner hears. Says what stopped and why, then asks.

    WRITTEN HERE, NOT BY A MODEL. `INV-NARRATE-1` already requires every gateway
    failure classification to have a line rendered from a governed template and
    never produced by a model, and the reasoning carries: a model asked to
    explain why an action was blocked is a model that can be talked into
    explaining it away.

    NO LEVEL IN THE SPOKEN LINE. `level` is recorded on the request and stays
    out of the sentence: "it needs L4" tells the owner nothing they can act on,
    and an authorization tier read aloud is jargon standing where a reason
    should be. The first version of this line also read the level off the
    REFUSAL, which is L0 on every denial -- so it said "it needs L0" about an
    action that needs L4, which is worse than saying nothing.
    """
    why = {
        "grant_consumed": ("the confirmation you gave for this has already been "
                           "used, and it covers one action"),
        "owner_confirmation_required": "this needs your confirmation first",
        "no_grant": "I have no permission for this",
        # NO LEVEL IN THE SENTENCE, per the rule above: "it needs L4" is jargon
        # standing where a reason should be, and the owner cannot act on it.
        "below_required_level": ("this needs more permission than I hold for "
                                 "it right now"),
    }.get(reason, f"I was refused for {reason}")
    return (f"I stopped before {capability_id} on {target}: {why}. "
            f"May I go ahead?")


class ConfirmationBroker:
    """Turns an authorization refusal into a question the owner can answer."""

    def __init__(self, bus: EventBus, budget: InterruptionBudget) -> None:
        self._bus = bus
        self._budget = budget
        self._pending: dict = {}
        self._lock = threading.RLock()

    # ----------------------------------------------------------------- ask

    def request(self, decision: Any, *, target: str, period: str,
                attention_state: str = ATTENTION_UNKNOWN,
                urgent: bool = False) -> dict:
        """Stop, explain, and ask -- now if the owner is there, later if not.

        `decision` is a refusal from `core/authorize.py`. Passing an AUTHORIZED
        decision is a caller error and raises: manufacturing a question about an
        action that was already permitted would train the owner to approve
        things reflexively, which is how a confirmation becomes a formality.
        """
        if getattr(decision, "authorized", False):
            raise ValueError(
                "a confirmation was requested for an AUTHORIZED action. The "
                "question exists because the action was refused; asking about "
                "permitted ones teaches the owner to say yes without reading.")
        if decision.reason not in CONFIRMABLE_REASONS:
            # Not every refusal is a question. A stale lease epoch or an
            # out-of-scope target is not something the owner can answer by
            # saying yes, and asking would offer an approval that changes
            # nothing.
            self._bus.publish(
                "confirm.not_confirmable", subject=decision.capability_id,
                payload={"reason": decision.reason,
                         "confirmable": list(CONFIRMABLE_REASONS),
                         "note": ("this refusal is not something owner "
                                  "confirmation can resolve")},
                component="confirm")
            return {"asked": False, "reason": "not_confirmable"}

        req = ConfirmationRequest(
            request_id=str(uuid.uuid4()),
            capability_id=decision.capability_id, target=target,
            level=getattr(decision, "effective_level", "L0"),
            reason=decision.reason,
            explanation=explain(decision.capability_id, target,
                                getattr(decision, "effective_level", "L0"),
                                decision.reason))
        with self._lock:
            self._pending[req.request_id] = req

        if urgent:
            return self._urgent(req, period, attention_state)

        cand = Candidate(
            candidate_id=req.request_id,
            expected_value=1.0,
            # THE FLAG THAT IMPLEMENTS "WAIT AND ASK ME WHEN I'M BACK". A
            # question about an action the owner set in motion is worth exactly
            # as much when they return, so it must never be dropped for not
            # fitting the budget.
            decays=False,
            interruption_cost=0.8,      # speech, the expensive modality
            is_alarm=False)
        outcome = self._budget.allocate([cand], period=period,
                                        attention_state=attention_state)
        asked_now = req.request_id in outcome.surfaced
        self._bus.publish(
            "confirm.requested", subject=req.capability_id,
            payload={**req.to_dict(), "period": period,
                     "attention_state": attention_state,
                     "asked_now": asked_now,
                     "modality": ASK_BY_VOICE if asked_now else "queued",
                     "note": ("an unknown attention state falls to budget 0 and "
                              "the question waits, which is the correct "
                              "fail-closed answer: nothing writes "
                              "world.owner.attention_state yet")},
            component="confirm")
        req.asked = asked_now
        return {"asked": asked_now, "queued": not asked_now,
                "request_id": req.request_id,
                "modality": ASK_BY_VOICE if asked_now else None,
                "explanation": req.explanation}

    def _urgent(self, req: ConfirmationRequest, period: str,
                attention: str) -> dict:
        """The owner's third branch: cannot wait, so call them.

        REFUSES RATHER THAN DEGRADING. No phone is enrolled, so this cannot
        happen -- and quietly falling back to a queued question would be the
        exact failure the branch exists to prevent: something urgent waiting
        silently while the owner assumes it would have reached them.
        """
        self._bus.publish(
            "confirm.urgent_unreachable", subject=req.capability_id,
            payload={**req.to_dict(), "period": period,
                     "attention_state": attention, "modality": ASK_BY_PHONE,
                     "note": ("the phone_call modality is declared in "
                              "interruption_budget.toml and is unavailable: no "
                              "node with a SIM is enrolled. Refused rather than "
                              "degraded to a queued question.")},
            component="confirm")
        raise PhoneUnavailable(
            f"{req.capability_id} needs urgent confirmation and no enrolled "
            "node can place a call. Enrol a telephony-capable node, or answer "
            "the queued question when you return -- this action has NOT "
            "happened.")

    # -------------------------------------------------------------- answer

    def surface(self, *, boundary: str = "natural_interaction") -> list:
        """Put the waiting questions in front of the owner, once they are back."""
        ids = self._budget.surface_queued(boundary=boundary)
        with self._lock:
            for i in ids:
                if i in self._pending:
                    self._pending[i].asked = True
            out = [self._pending[i].to_dict() for i in ids if i in self._pending]
        if out:
            self._bus.publish(
                "confirm.surfaced", subject=boundary,
                payload={"boundary": boundary, "requests": out},
                component="confirm")
        return out

    def answer(self, request_id: str, *, granted: bool) -> ConfirmationRequest:
        """Record the owner's answer. Does NOT itself authorize anything.

        The caller re-runs authorization with a fresh grant. Keeping those
        separate is deliberate: a broker that could authorize would be a second
        path to a level, and `INV-AUTH-1` says there is no such path.
        """
        with self._lock:
            req = self._pending.get(request_id)
            if req is None:
                raise KeyError(f"no pending confirmation {request_id!r}")
            if req.answered:
                raise ValueError(
                    f"confirmation {request_id!r} was already answered "
                    f"{'yes' if req.granted else 'no'}. One question, one "
                    "answer -- re-asking a question the owner has settled is "
                    "how a confirmation becomes a formality.")
            if not req.asked:
                raise NotTheQuestionInFront(
                    f"confirmation {request_id!r} is queued, not in front of "
                    "the owner. It has to be asked again before an answer "
                    "means anything: a 'yes' said while this question was not "
                    "on screen is a yes to something else.")
            req.answered, req.granted = True, granted
            req.asked = False
        self._bus.publish("confirm.answered", subject=req.capability_id,
                          payload=req.to_dict(), component="confirm")
        return req

    def pending(self) -> list:
        with self._lock:
            return [r.to_dict() for r in self._pending.values()
                    if not r.answered]
