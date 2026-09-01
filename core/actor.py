"""The path from "do this" to it being done — or to the owner being asked.

WHAT THIS CLOSES. Every part of acting existed and none of it was joined up:
`core/intent.py` proposes, `core/capabilities.py` levels and implements,
`core/authorize.py` decides, `core/executor.py` invokes and compensates,
`core/confirm.py` asks the owner when the answer is no. This is the wire, and
it is deliberately thin -- it makes no policy of its own, and every refusal in
it comes from somewhere that already existed.

THE STANDING GRANT IS L2 AND THAT IS THE WHOLE SAFETY ARGUMENT. VESPER holds
authority to look at the machine and to write inside its own workspace. It holds
NO standing authority to touch the owner's documents, the contracts, the
credentials, or to run anything that is not provably read-only. Those are not
forbidden -- they are refused *pending an answer*, and the refusal becomes a
spoken question. So the interesting cases do not depend on the proposer being
right; they depend on the owner being asked, which is the arrangement the owner
chose on 2026-08-31: stop, explain, ask by voice, and wait if nobody is there.

WHY THE GRANT IS PER-CAPABILITY AND NOT PER-SESSION. `Grant` is keyed to a
capability id, so there is no such thing here as "VESPER is in L2 mode". Each
capability is granted separately and an L4/L5 answer is consumed by the single
action it was given for (INV-AUTH-2). A session-wide level would make one
confirmation stand for every later action, which is the failure the whole ladder
is built to prevent.

VERIFICATION IS NOT OPTIONAL AND ITS ABSENCE IS NOT SILENCE. Where a capability
has an independent verifier, it runs and its verdict is what gets reported.
Where none exists -- `shell.run`, whose effects are not generically observable --
the outcome says so in words rather than implying the result was checked. A-013
asks for a result verified independently of the actor's claim; saying "nothing
independently verified this" is an honest answer to that, and pretending
otherwise is not.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.authorize import Grant, PolicyDecisionPoint
from core.capabilities import INDEPENDENT_VERIFIERS, bind_all, build_registry
from core.executor import Executor
from core.intent import IntentProposer
from core.taint import ContextCeiling, Tainted

# What VESPER may do without asking. Read-only inspection and its own workspace.
STANDING_LEVEL = "L2"

# How long a standing grant lives before it must be re-issued. Long enough not
# to be a nuisance, short enough that a runtime left running for days is not
# still acting on authority issued in a state nobody remembers.
STANDING_TTL_MS = 12 * 60 * 60 * 1000


@dataclass(slots=True)
class Outcome:
    """What happened, in a form both the log and the owner can be told."""

    kind: str                 # acted | asked | refused | failed
    capability_id: str
    level: str = ""
    said: str = ""            # the sentence for the owner
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "capability_id": self.capability_id,
                "level": self.level, "said": self.said, "detail": self.detail}


class Actor:
    """Proposes, authorizes, acts, verifies — or stops and asks."""

    def __init__(self, bus: Any, gateway: Any, *, subject: str = "vesper",
                 target: str = "host", broker: Any = None,
                 now_ms: Any = None, profile_id: str = "") -> None:
        self._bus = bus
        self._registry = build_registry()
        self._pdp = PolicyDecisionPoint(bus, self._registry,
                                        **({"now_ms": now_ms} if now_ms else {}))
        self._executor = Executor(bus, self._registry, self._pdp)
        bind_all(self._executor)
        self._proposer = IntentProposer(gateway, bus=bus, profile_id=profile_id)
        self._ceiling = ContextCeiling(bus)
        self._subject = subject
        self._target = target
        self._broker = broker
        self._issue_standing()

    # ------------------------------------------------------------- grants

    def _issue_standing(self) -> None:
        """One grant per capability, all at L2, none delegable."""
        expiry = STANDING_TTL_MS
        for cid in self._registry.ids():
            self._pdp.issue(Grant(
                grant_id=f"standing:{cid}", subject=self._subject,
                capability_id=cid, target_scope=(self._target,),
                max_level=STANDING_LEVEL, expiry_ms=expiry, lease_epoch=0,
                delegable=False, issued_by="owner"))

    # --------------------------------------------------------------- act

    def maybe_act(self, text: str, *, attention_state: str = "UNKNOWN",
                  period: str = "active",
                  fragments: list | None = None) -> Outcome | None:
        """None means this turn was not a request to do anything.

        `fragments` carries the PROVENANCE of everything that reached the
        proposer, and it is what makes `core/taint.py` binding here. Before
        2026-09-01 the ceiling was computed nowhere on this path:
        `authorize()` and `execute()` both defaulted `context_ceiling` to
        "L5" and no caller passed one, so `ALLOWED_LEVEL` could not lower any
        decision the running system made. `ContextCeiling` was instantiated
        exactly twice in the whole repository -- once by its check and once by
        its acceptance test, both of which supply their own subject. A check
        that constructs the thing it checks is testing a library, not a system.
        """
        p = self._proposer.propose(text)
        if p is None:
            return None

        try:
            cap = self._registry.get(p.capability_id)
        except Exception as exc:                       # noqa: BLE001
            return Outcome("refused", p.capability_id,
                           said="that is not something I can do",
                           detail={"error": repr(exc)})
        level = cap.required(p.args)

        # THE CEILING IS COMPUTED BEFORE THE LADDER IS CONSULTED, and it is
        # `check` rather than `ceiling` deliberately: above-ceiling is not a
        # silent drop (RB-022). `check` queues the proposal and publishes
        # `security.above_ceiling_proposal`, plus `security.injection_suspected`
        # when externally-retrieved content is in context -- which is the whole
        # point of the subsystem and was previously emitted by nothing that runs.
        frags = self._fragments_for(text, fragments)
        ceil = self._ceiling.check(level, frags, capability_id=p.capability_id,
                                   subject=self._subject)["ceiling"]

        # ASKED BEFORE ACTING, so that the refusal carries the DECISION and not
        # just a string. `Executor.execute` authorizes again immediately before
        # invoking -- that second check is the binding one and this one does not
        # replace it. This one exists because the broker needs the Decision
        # object to explain WHY, and a refusal message parsed back out of an
        # execution record would be a worse version of the same thing.
        #
        # THE CEILING GOES TO BOTH CALLS. Passing it only here would re-open the
        # hole one layer down: `execute` re-authorizes immediately before
        # invoking, and that second check is the binding one.
        d = self._pdp.authorize(subject=self._subject,
                                capability_id=p.capability_id, args=p.args,
                                target=self._target, context_ceiling=ceil,
                                current_lease_epoch=0)
        if not d.authorized:
            return self._ask(d, p, level, attention_state, period)

        try:
            ex = self._executor.execute(subject=self._subject,
                                        capability_id=p.capability_id,
                                        args=p.args, target=self._target,
                                        context_ceiling=ceil,
                                        current_lease_epoch=0)
        except Exception as exc:                       # noqa: BLE001
            return Outcome("failed", p.capability_id, level,
                           said="I tried and it failed",
                           detail={"error": repr(exc)})

        # `Execution.outcome == "VERIFIED"` MEANS THE INVOCATION COMPLETED, and
        # it is not the independent verification A-013 asks for -- the executor
        # is reporting on the call it made, which is still the actor's own view
        # of itself. The world gets read back below.
        if ex.outcome != "VERIFIED":
            return Outcome("failed", p.capability_id, level,
                           said="I tried and it did not go through",
                           detail={"outcome": ex.outcome, "error": ex.error})

        return self._verify(p, level, ex)

    # ------------------------------------------------------------- pieces

    @staticmethod
    def _fragments_for(text: str, fragments: list | None) -> list:
        """The provenance of what reached the proposer, defaulted honestly.

        A caller that has retrieved anything -- a file, a page, a memory, a
        message from someone who is not the owner -- passes it here with its
        real class, and the ceiling binds. `ContextCeiling.ceiling` takes the
        MINIMUM over fragments, because taint is contagious rather than
        averaged: one external fragment lowers the ceiling for the whole turn.

        THE DEFAULT IS THE ASSUMPTION THIS SYSTEM ALREADY MAKES EVERYWHERE
        ELSE, written down where it can be found. A live utterance is classed
        `owner` because the standing grant is issued `issued_by="owner"` on
        exactly the same premise. That premise is NOT verified: the wake word
        opens a six-second capture of a room, and a room can contain someone
        else. When speaker verification lands, this is the line it changes, and
        the ceiling is already threaded through everything downstream of it.
        """
        if fragments is not None:
            return list(fragments)
        return [Tainted(text, "owner", origin="utterance:live")]


    def _ask(self, decision: Any, proposal: Any, level: str,
             attention_state: str, period: str) -> Outcome:
        """A refusal becomes a question, or stays a refusal and says why."""
        if self._broker is None:
            return Outcome("refused", proposal.capability_id, level,
                           said=(f"that needs your say-so ({level}) and I have "
                                 "no way to ask you right now"),
                           detail={"reason": decision.reason})
        try:
            asked = self._broker.request(decision, target=self._target,
                                         period=period,
                                         attention_state=attention_state)
        except Exception as exc:                       # noqa: BLE001
            return Outcome("refused", proposal.capability_id, level,
                           said="that needs your say-so and I could not ask",
                           detail={"error": repr(exc)})
        return Outcome("asked", proposal.capability_id, level,
                       said=(f"I stopped before doing that -- it needs your "
                             f"permission ({level}). {proposal.why}".strip()),
                       detail={"reason": decision.reason, "asked": asked})

    @staticmethod
    def _reportable(result: dict) -> dict:
        """What goes into the RECORD, which is not everything the call returned.

        `fs.write` hands back `previous` -- the entire prior contents of the
        file -- because `fs_write_compensator` needs those bytes to undo the
        write. The executor is careful about this: `Execution.to_dict` leaves
        `result` out of every event it publishes. The actor then put it back,
        so `act.outcome` carried the full previous text of anything overwritten
        into the durable event store, for every write.

        Compensation is unaffected: the executor holds the real result and
        passes THAT to the compensator. Only the reported copy is narrowed, and
        it keeps the hash, because "record what was compared" needs the value
        that was compared and not the document it came from.
        """
        if "previous" not in result:
            return result
        out = dict(result)
        prev = out.pop("previous")
        out["previous_sha256"] = (
            hashlib.sha256(prev.encode("utf-8")).hexdigest()
            if isinstance(prev, str) else None)
        out["previous_bytes"] = len(prev) if isinstance(prev, str) else 0
        return out

    def _verify(self, proposal: Any, level: str, ex: Any) -> Outcome:
        """Read the world back where that is possible, and say so where it is not."""
        result = ex.result if isinstance(getattr(ex, "result", None), dict) else {}
        verifier = INDEPENDENT_VERIFIERS.get(proposal.capability_id)
        if verifier is None:
            return Outcome("acted", proposal.capability_id, level,
                           said=_describe(proposal, result),
                           detail={"result": self._reportable(result),
                                   "verified": None,
                                   "why_not": ("this capability's effect is not "
                                               "generically observable, so "
                                               "nothing independent checked it")})
        try:
            v = verifier(result)
        except Exception as exc:                       # noqa: BLE001
            v = {"verified": False, "why": f"the verifier itself failed: {exc!r}"}
        if not v.get("verified"):
            # THE ACTOR SAID IT WORKED AND THE WORLD DISAGREES. The world wins.
            return Outcome("failed", proposal.capability_id, level,
                           said="I thought I did that, but checking says otherwise",
                           detail={"result": self._reportable(result), "verification": v})
        return Outcome("acted", proposal.capability_id, level,
                       said=_describe(proposal, result),
                       detail={"result": self._reportable(result), "verification": v})


def _describe(proposal: Any, result: dict) -> str:
    """One sentence about what actually happened, carrying real values."""
    cid = proposal.capability_id
    if cid == "shell.run":
        out = (result.get("stdout") or "").strip()
        code = result.get("exit_code")
        if code not in (0, None):
            return f"it ran and came back with error code {code}"
        return out[:600] if out else "it ran and printed nothing"
    if cid == "fs.read":
        n = result.get("bytes")
        return f"{result.get('path')} — {n} bytes:\n{(result.get('text') or '')[:600]}"
    if cid == "fs.write":
        return f"written: {result.get('path')}"
    return "done"
