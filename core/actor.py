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
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.authorize import Grant, PolicyDecisionPoint
from core.capabilities import (INDEPENDENT_VERIFIERS, bind_all,
                               build_registry, observation_trust,
                               observe)
from core.executor import Executor
from core.intent import IntentProposer
from core.taint import EXTERNAL, ContextCeiling, Tainted

# What VESPER may do without asking. Read-only inspection and its own workspace.
STANDING_LEVEL = "L2"

# How long a standing grant lives before it must be re-issued. Long enough not
# to be a nuisance, short enough that a runtime left running for days is not
# still acting on authority issued in a state nobody remembers.
STANDING_TTL_MS = 12 * 60 * 60 * 1000

# How many actions one turn may take. The loop exists so a task can be
# finished, not so work can go on indefinitely; six is enough for read ->
# decide -> write -> verify with room to recover from one mistake.
MAX_STEPS = 6

# Consecutive refused or failed steps before the turn is stopped. Codex bounds
# the same thing at three denials per turn, and the reason is the same: with a
# loop, a proposer that keeps re-proposing something the ladder refuses grinds
# until the budget runs out. Without a loop this could not happen, which is why
# it lands in the same commit rather than a later one.
MAX_CONSECUTIVE_REFUSALS = 3


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
                  period: str = "active", fragments: list | None = None,
                  max_steps: int = MAX_STEPS) -> Outcome | None:
        """Act, observe, and act again until the turn is finished. None means
        this turn was not a request to do anything at all.

        UNTIL 2026-09-01 THIS WAS ONE PROPOSAL AND ONE ACTION. It could not run
        a command, look at the output, and open the file it found; it could not
        try something, watch it fail, and fix it; it could not do anything that
        takes two moves. A better tool set with no loop is still one action per
        sentence.

        WHAT MAY CONTINUE THE LOOP IS THE NARROW PART. Aider's inner loop
        advances only on machine evidence that something is unfinished -- lint
        errors, a failing test, an exception, a file that was not shared -- and
        never because the model would like to keep going. Here the equivalent
        is that the proposer must emit a well-formed action that the ladder
        then permits. "Nothing more to do" is the default: `parse` returns None
        for anything doubtful, so a finished turn simply stops proposing.

        AND FOUR THINGS END IT REGARDLESS. The step budget; a repeat of the
        previous action, which is progress having stopped; a refusal that needs
        the owner, because waiting for an answer is not a step; and the
        consecutive-refusal breaker below.

        THE OBSERVATIONS ARE TAINTED AND THAT CHANGES WHAT COMES NEXT.
        INV-ACT-3 makes command output `retrieved_external`, so from the second
        step onwards the context ceiling is L1 and anything above it becomes a
        question for the owner. That is a real and deliberate narrowing: it is
        exactly the case where a file or a directory listing could otherwise
        talk VESPER into something, and it is the reason the ceiling was wired
        into this path first.
        """
        observations: list = []
        outcomes: list = []
        last: Outcome | None = None
        signatures: list = []
        consecutive_refusals = 0

        for step in range(max(1, int(max_steps))):
            p = self._proposer.propose(
                text, observations=observations if observations else None)
            if p is None:
                break

            # NO PROGRESS IS A STOP CONDITION. A proposer handed its own last
            # action back can repeat it indefinitely, and every repeat is a
            # fresh authorization and a fresh execution of something already
            # done. Compared against the PREVIOUS signature rather than all of
            # them, because revisiting a path legitimately happens -- read,
            # write, read back -- and only an immediate repeat is stuck.
            sig = (p.capability_id,
                   json.dumps(p.args, sort_keys=True, default=str))
            if signatures and sig == signatures[-1]:
                self._bus.publish(
                    "act.no_progress", subject=self._subject,
                    payload={"capability_id": p.capability_id, "step": step},
                    component="actor")
                break
            signatures.append(sig)

            out = self._one_step(p, text, attention_state, period,
                                 fragments, observations)
            last = out
            outcomes.append(out.to_dict())

            if out.kind == "asked":
                break                      # waiting on the owner ends the turn

            if out.kind in ("refused", "failed"):
                consecutive_refusals += 1
                if consecutive_refusals >= MAX_CONSECUTIVE_REFUSALS:
                    # THE CIRCUIT BREAKER, AND IT SHIPS WITH THE LOOP RATHER
                    # THAN AFTER IT. One action per utterance made a refusal a
                    # dead end; a loop lets a wrong or steered proposer grind
                    # against the ladder for as long as the budget allows,
                    # burning battery and -- once refusals reach the voice ask
                    # -- the owner's sleep. Codex bounds the same thing at
                    # three consecutive denials per turn.
                    self._bus.publish(
                        "act.refusal_breaker", subject=self._subject,
                        payload={"consecutive": consecutive_refusals,
                                 "step": step,
                                 "capability_id": p.capability_id},
                        component="actor")
                    break
            else:
                consecutive_refusals = 0
                observations.append(
                    observe(p.capability_id, p.args,
                            (out.detail or {}).get("result") or {}))

        if last is None:
            return None
        if len(outcomes) > 1:
            last.detail = dict(last.detail or {})
            last.detail["steps"] = outcomes
        return last

    def _one_step(self, p: Any, text: str, attention_state: str, period: str,
                  fragments: list | None, observations: list) -> Outcome:
        """One proposal, levelled, authorized, executed and verified."""
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
        frags = self._fragments_for(text, fragments, observations)
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
    def _fragments_for(text: str, fragments: list | None,
                       observations: list | None = None) -> list:
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
        base = (list(fragments) if fragments is not None
                else [Tainted(text, "owner", origin="utterance:live")])

        # EVERY OBSERVATION LOWERS THE CEILING FOR THE REST OF THE TURN.
        # INV-ACT-3: "command output entering the system are trust_class
        # retrieved_external ... and may never raise the authority of any
        # action." So once VESPER has looked at anything, the next step is
        # capped at L1 and anything above it becomes a question. This is the
        # loop's cost and it is the loop's whole safety argument: the step that
        # could be steered by what was just read is the step that has to ask.
        base += [Tainted(o, observation_trust(str(o.get("capability") or "")),
                         origin=f"observation:{o.get('capability')}")
                 for o in (observations or []) if isinstance(o, dict)]
        return base


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
