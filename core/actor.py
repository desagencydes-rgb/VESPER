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
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.advisor import STOP as ADVISOR_STOP
from core.advisor import worth_reviewing
from core.authorize import Decision, Grant, PolicyDecisionPoint
from core.capabilities import (INDEPENDENT_VERIFIERS, bind_all,
                               WORKSPACE, build_registry,
                               observation_trust, observe)
from core.executor import Executor
from core.intent import IntentProposer, Proposal
from core.reconcile import Reconciler
from core.selfmod import SelfModificationBoundary
from core.checkpoint import ShadowGit
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

# Where the shadow history lives. Beside VESPER's state, for the reason given
# in `__init__` -- the workspace's own parent, so a rebuild cannot take it.
SHADOW_ROOT = WORKSPACE.parent / "shadow"
# HOW LONG A PARKED *PLAN* STAYS GOOD. Deliberately NOT how long the QUESTION
# stays good: `core/confirm.py` marks a confirmation non-decaying because "a
# question about an action the owner asked for is worth the same when they get
# back", and that is the owner's own design for being away. What goes stale is
# not the question, it is everything the turn had LOOKED AT before asking. An
# observation is a claim about the world at a moment; resuming a six-step plan
# on top of eight-hour-old observations is acting on a world that has moved.
#
# So the two are separated: an answer always authorises the action it was asked
# about, and only a FRESH park also resumes the rest of the plan.
PARK_TTL_MS = 60 * 60 * 1000
# The single-use grant an answered question buys. Short, because it exists to
# cover one execution that is about to happen, not to leave authority lying
# around: `core/authorize.py` already refuses a consumed grant with "one
# confirmation authorises one action instance", and this is the time bound on
# the same idea.
ANSWER_GRANT_TTL_MS = 5 * 60 * 1000
# HOW MANY TURNS MAY BE WAITING ON AN ANSWER AT ONCE. Unbounded, this is a map
# a steered proposer grows for free: every refused high-level action parks a
# whole turn -- its text, its observations, its outcomes -- and nothing ever
# removes one the owner does not answer. The owner's design says a question
# waits indefinitely, and that is about the QUESTION, which is one small record
# in the broker. The PLAN behind it is not small and does not need to wait
# forever: its observations are stale after PARK_TTL_MS anyway.
#
# Oldest out first, and the eviction is PUBLISHED. A turn that quietly vanished
# would leave the owner answering a question whose plan no longer exists.
MAX_PARKED_TURNS = 8

# The tree the self-modification boundary governs: this repository.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def _ask_sentence(why: str) -> str:
    """The permission question, in words the owner can answer.

    THE OLD ONE DID NOT ASK ANYTHING. It read: "I stopped before doing that --
    it needs your permission (L5). run the script to output "hey there!"" --
    four separate faults in one line, heard aloud by the owner on 2026-09-04.
    It named a LEVEL, which is this system's vocabulary and not theirs. It
    appended `proposal.why`, which is a log fragment written for the record,
    as though it were a sentence. It used a double dash, which a synthesiser
    reads as a stumble. And it never posed a QUESTION, so nothing in it told
    the owner that saying yes was available -- which is the entire point of
    stopping to ask.

    THE LEVEL STAYS IN `detail`. It belongs in the record, where a reader is
    debugging the ladder, and not in a sentence spoken to the person who only
    wants to know what VESPER is about to do.
    """
    w = (why or "").strip().rstrip(".!?").strip()
    if not w:
        return "I need your go-ahead before I do that. Say yes and I will."
    return f"I need your go-ahead before I {w}. Say yes and I will."


class Actor:
    """Proposes, authorizes, acts, verifies — or stops and asks."""

    def __init__(self, bus: Any, gateway: Any, *, subject: str = "vesper",
                 target: str = "host", broker: Any = None,
                 now_ms: Any = None, profile_id: str = "",
                 shadow: Any = None, reconciler: Any = None,
                 selfmod: Any = None, jobs: Any = None,
                 agent: Any = None, advisor: Any = None,
                 runner: Any = None) -> None:
        self._bus = bus
        self._registry = build_registry()
        # Turns waiting on an answer, keyed by the broker's own
        # request_id. In memory rather than on disk deliberately:
        # a plan is only resumable inside the process that built
        # it -- the observations it rests on are that process's
        # reading of the world -- and a restart should re-ask
        # rather than resume something it cannot vouch for.
        self._parked: dict = {}
        # THE SAME CLOCK THE LADDER USES. The actor needs one for the park
        # window and the answered-grant expiry, and taking a second source
        # would let a grant issued "now" be already expired by the PDP's
        # reckoning. Injected in tests for the same reason it is injected into
        # the PDP: a window that can only be tested by waiting is not tested.
        #
        # A DURATION CLOCK, WHICH IS NOT AN ORDERING. INV-COORD-4 governs what
        # orders and supersedes; "has an hour passed" orders nothing.
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        # ALWAYS HANDED TO THE PDP, not only when a caller injected one. It was
        # forwarded conditionally, so the runtime -- which constructs
        # `Actor(bus, gw, broker=...)` with no clock -- left the PDP on its
        # `lambda: 0` default. Every grant then had an expiry in the far future
        # of a clock that never advanced, so `grant_expired` could not fire and
        # the five-minute bound on an answered confirmation was decorative.
        # Two clocks disagreeing is worse than one wrong clock: the expiry was
        # WRITTEN from real time and READ from zero.
        self._pdp = PolicyDecisionPoint(bus, self._registry,
                                        now_ms=self._now_ms)
        # BESIDE STATE, NEVER BESIDE CODE. `build.sh` deletes the runtime
        # directory inside VESPER.app on every build, and a note written there
        # was created, hash-verified, reported successful and then removed by
        # the next build. A checkpoint store under the bundle would lose its
        # history at exactly the moment a rebuild made it most useful.
        self._shadow = shadow if shadow is not None else ShadowGit(SHADOW_ROOT)
        # EXACTLY-ONCE EFFECT, NOT EXACTLY-ONCE DELIVERY. `shell.run` declares
        # an external effect and can reach anything; a crash between the call
        # and the record leaves nothing able to tell "not sent" from "sent,
        # result lost". The outbox is what makes that difference recoverable,
        # and it mattered less when VESPER took one action per utterance than
        # it does now that a turn can take six.
        self._reconciler = reconciler if reconciler is not None else Reconciler(bus)
        # THE SELF-MODIFICATION BOUNDARY. Built, gated by CI-015 against the
        # REAL repository and the real pinned artifact, and consulted by
        # nothing -- so the refusal existed and was never asked for.
        self._selfmod = selfmod if selfmod is not None else SelfModificationBoundary(
            bus, repo_root=REPO_ROOT)
        self._executor = Executor(bus, self._registry, self._pdp,
                                  shadow=self._shadow,
                                  reconciler=self._reconciler,
                                  selfmod=self._selfmod)
        # THE STOP TRAVELS WITH THE CAPABILITY. Without a registry
        # `shell_run` refuses `background`, so an actor built without
        # one cannot start work that outlives its turn at all.
        self._jobs = jobs
        # THE SUB-AGENT, BUILT FROM THE ACTOR'S OWN GATEWAY IF NONE WAS GIVEN.
        # It shares the gateway so delegation goes through the same choke point
        # every other model call does -- the redactor, the cost policy and the
        # quota ledger are not optional for a question asked on VESPER's behalf
        # just because a sub-agent asked it.
        if agent is None and gateway is not None:
            from core.subagent import SubAgent
            agent = SubAgent(gateway, bus=bus)
        self._agent = agent
        # ABSENT BY DEFAULT, AND ABSENCE IS NOT PERMISSION. With no advisor the
        # act path is exactly what it was; a missing reviewer never becomes a
        # reason to be more permissive than a system that never had one.
        self._advisor = advisor
        self._runner = runner
        bind_all(self._executor, jobs=jobs, agent=agent, runner=runner)
        self._proposer = IntentProposer(gateway, bus=bus, profile_id=profile_id)
        self._ceiling = ContextCeiling(bus)
        self._subject = subject
        self._target = target
        self._broker = broker
        self._issue_standing()

    # ------------------------------------------------------------- grants

    def _issue_standing(self) -> None:
        """One grant per capability, all at L2, none delegable."""
        # RELATIVE TO NOW, and it was absolute. `expiry = STANDING_TTL_MS` is
        # the instant 12 hours after the epoch: unreachable under the PDP's old
        # zero clock, and already twelve hours past under any real one. It read
        # as "never expires" only because nothing ever advanced the clock it
        # was compared against.
        expiry = self._now_ms() + STANDING_TTL_MS
        for cid in self._registry.ids():
            self._pdp.issue(Grant(
                grant_id=f"standing:{cid}", subject=self._subject,
                capability_id=cid, target_scope=(self._target,),
                max_level=STANDING_LEVEL, expiry_ms=expiry, lease_epoch=0,
                delegable=False, issued_by="owner"))

    # --------------------------------------------------------------- act

    def maybe_act(self, text: str, *, attention_state: str = "UNKNOWN",
                  period: str = "active", fragments: list | None = None,
                  max_steps: int = MAX_STEPS,
                  permitted: Any = None,
                  recent: list | None = None,
                  resume_state: dict | None = None) -> Outcome | None:
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
        # RESUMED STATE, OR A FRESH TURN. One loop rather than two: a
        # second implementation for "continuing" is a second place for the
        # step budget, the no-progress rule and the refusal breaker to be
        # subtly different, and the resumed path is the one nobody exercises
        # by hand.
        #
        # `signatures` CARRIES ACROSS THE PAUSE and that matters: the
        # no-progress rule compares against the previous signature, so a
        # resumed turn that dropped them would let the proposer immediately
        # repeat the action the owner just approved -- a second execution of
        # a single-use approval, which the ladder would then refuse as
        # `grant_consumed`, but only after proposing it.
        st = resume_state or {}
        observations: list = list(st.get("observations") or [])
        outcomes: list = list(st.get("outcomes") or [])
        last: Outcome | None = st.get("last")
        signatures: list = list(st.get("signatures") or [])
        consecutive_refusals = int(st.get("consecutive_refusals") or 0)

        for step in range(int(st.get("start_step") or 0), max(1, int(max_steps))):
            # THE STOP, ASKED EVERY STEP -- AND IT WAS ASKED NOWHERE.
            #
            # The interlock was consulted in `AutonomyLoop.dispatch`, once,
            # BEFORE this loop began, and nothing asked again. Driven on
            # 2026-09-01: an autonomous turn ran six steps and six model calls
            # with the stop reachable at none of them. Pressing the emergency
            # stop after step 1 prevented the NEXT dispatch and let steps 2..6
            # run -- each one a shell command or a file write the owner had
            # already said to stop. The docstring above lists four things that
            # end this loop and the stop is not among them, which was accurate.
            #
            # ASKED BEFORE PROPOSING, not after. A stop noticed after the
            # proposal has already spent a model call on work it will discard,
            # and on the rungs this runs on a call is a piece of a free-tier
            # quota that does not come back until its window resets.
            #
            # PASSED IN BY THE CALLER, NEVER HELD BY THE ACTOR. `dispatch`
            # supplies it because `dispatch` is what knows the work is
            # autonomous; an owner-typed turn supplies nothing and is
            # unaffected. STOP_AUTONOMY stops autonomous work -- an actor that
            # consulted `autonomy_permitted()` on its own would also refuse the
            # owner the moment the enable token went stale, which is every
            # ninety seconds by design.
            if permitted is not None and not permitted():
                self._bus.publish(
                    "act.stopped", subject=self._subject,
                    payload={"step": step, "steps_taken": len(signatures),
                             "note": ("autonomy stopped mid-turn: the interlock "
                                      "refused before this step was proposed")},
                    component="actor")
                break

            p = self._proposer.propose(
                text, observations=observations if observations else None, recent=recent)
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
                # PARKED, NOT DROPPED. This was `break  # waiting on the owner
                # ends the turn`, and it was the single largest ceiling in the
                # act path: VESPER stopped to ask, the turn died, and the
                # owner's "yes" arrived to a proposer that had forgotten
                # everything -- no observations, no plan, no step budget spent,
                # nothing to resume. The question survived and the WORK did not.
                #
                # KEYED ON THE BROKER'S OWN request_id, so there is exactly one
                # identifier for "the thing that was asked" and no second
                # correlation scheme to disagree with it.
                rid = ((out.detail or {}).get("asked") or {}).get("request_id")
                if rid:
                    self._park(rid, text=text, proposal=p, step=step,
                               observations=observations,
                               signatures=signatures, outcomes=outcomes,
                               attention_state=attention_state, period=period,
                               fragments=fragments, max_steps=max_steps,
                               consecutive_refusals=consecutive_refusals)
                break                      # the turn pauses here; it resumes

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

    # ------------------------------------------------------- park / resume

    @staticmethod
    def _proposal_fingerprint(capability_id: str, args: dict) -> str:
        """What the owner was actually asked about.

        THE BINDING, AND IT IS THE WHOLE SAFETY ARGUMENT OF RESUME. Without it
        the sequence is: VESPER asks "may I delete the cache?", the owner says
        yes, and resume asks the model what to do next -- which may be a
        different action entirely, now carrying an approval that was given for
        something else. An answer authorises ONE action, and this is how resume
        knows which one.
        """
        return hashlib.sha256(
            json.dumps([capability_id, args], sort_keys=True,
                       default=str).encode()).hexdigest()

    def _park(self, request_id: str, **state) -> None:
        p = state.pop("proposal")
        parked = {
            "request_id": request_id,
            "capability_id": p.capability_id,
            "args": p.args,
            "why": getattr(p, "why", ""),
            "fingerprint": self._proposal_fingerprint(p.capability_id, p.args),
            "parked_at_ms": self._now_ms(),
            **state,
        }
        # `fragments` may hold Tainted objects, which do not belong in a
        # published payload; the turn keeps them in memory and the record
        # carries only what a reader needs.
        if len(self._parked) >= MAX_PARKED_TURNS:
            oldest = min(self._parked.values(), key=lambda v: v["parked_at_ms"])
            self._parked.pop(oldest["request_id"], None)
            self._bus.publish(
                "act.park_evicted", subject=self._subject,
                payload={"request_id": oldest["request_id"],
                         "capability_id": oldest["capability_id"],
                         "note": ("too many turns waiting on an answer; the "
                                  "oldest plan was dropped. Its QUESTION is "
                                  "still open, and answering it now does "
                                  "NOTHING: the plan that would have carried "
                                  "the action out is gone, so VESPER asks "
                                  "again rather than acting on a request it "
                                  "can no longer describe.")},
                component="actor")
        self._parked[request_id] = parked
        self._bus.publish(
            "act.parked", subject=self._subject,
            payload={"request_id": request_id, "step": parked["step"],
                     "capability_id": p.capability_id,
                     "observations": len(parked["observations"]),
                     "note": ("the turn is waiting on the owner and will "
                              "continue from here, not start over")},
            component="actor")

    @property
    def broker(self) -> Any:
        """The thing that asks. Exposed so a caller routing the owner's reply
        can settle the question this actor parked, without a second broker
        being constructed somewhere else and disagreeing about what is open."""
        return self._broker

    def parked(self) -> list:
        """What is waiting on an answer. Read-only."""
        return [{"request_id": k, "capability_id": v["capability_id"],
                 "step": v["step"], "parked_at_ms": v["parked_at_ms"],
                 "period": v.get("period", "active")}
                for k, v in self._parked.items()]

    def answerable(self) -> str:
        """The parked turn whose question is IN FRONT OF THE OWNER, or "".

        A CALLER ROUTING A BARE "YES" MUST NOT GUESS. The runtime took
        `parked()[0]`, which is insertion order -- the OLDEST waiting turn.
        With two questions open, answering the one VESPER just asked would have
        settled a different one and run its action instead: the owner approves
        a file write and a shell command executes, with a record saying they
        agreed to it. The broker already knows which question is being asked;
        this is the only correct way to pick.

        RETURNS "" RATHER THAN A GUESS when nothing is being asked. An answer
        with no question in front of it is not an answer -- see
        `NotTheQuestionInFront` -- and the caller re-queues instead.
        """
        if self._broker is None:
            return ""
        try:
            asked = {r["request_id"] for r in self._broker.pending()
                     if r.get("asked")}
        except Exception:                              # noqa: BLE001
            return ""
        for rid in self._parked:
            if rid in asked:
                return rid
        return ""

    def resume(self, request_id: str, *, granted: bool,
               instead: str = "", permitted: Any = None) -> Outcome | None:
        """The owner answered. Continue the turn that was waiting.

        RE-AUTHORISES; IT DOES NOT SKIP THE LADDER. `ConfirmationBroker.answer`
        says it in its own words -- "Does NOT itself authorize anything. The
        caller re-runs authorization with a fresh grant" -- because a broker
        that could authorise would be a second path to a level and INV-AUTH-1
        says there is no such path. This is that caller. It issues a
        single-use, target-scoped, five-minute grant and then runs the SAME
        ladder every other action runs.

        A DECLINE IS NOT A FAILURE. The owner saying no is the system working;
        it is recorded as a decision with the request it answers, never as an
        error, for the same reason `core/baseline.py` separates `declined` from
        `could_not`.

        AN EXPIRED PARK STILL HONOURS THE ANSWER, AND STOPS THERE. The action
        the owner approved is the action they approved, whenever they get to
        it. What does not survive is the REST of the plan, because the
        observations it was built on are old -- see PARK_TTL_MS.
        """
        parked = self._parked.pop(request_id, None)
        if parked is None:
            return Outcome("refused", "", "L0",
                           said="I do not have a question waiting under that.",
                           detail={"reason": "no_parked_turn",
                                   "request_id": request_id})
        if not granted:
            # REDIRECTED IS NOT THE SAME AS REFUSED, and the difference is what
            # happens to the plan. "No" ends the turn. "No, do it this other
            # way" ends the turn AND supersedes it -- the owner has said what
            # they want instead, so resuming anything from the old plan would
            # be doing the thing they just replaced. Both discard the park;
            # only one of them is a rejection of the idea.
            kind = "redirected" if instead else "declined"
            self._bus.publish(
                f"act.{kind}", subject=self._subject,
                payload={"request_id": request_id,
                         "capability_id": parked["capability_id"],
                         "step": parked["step"],
                         "instead": instead or None}, component="actor")
            if instead:
                return Outcome("redirected", parked["capability_id"], "L0",
                               said="Understood -- I will do that instead.",
                               detail={"request_id": request_id,
                                       "instead": instead,
                                       "note": ("the parked plan is discarded; "
                                                "the replacement is a new turn "
                                                "and goes down the ladder from "
                                                "the beginning")})
            return Outcome("declined", parked["capability_id"], "L0",
                           said="Understood -- I have not done it.",
                           detail={"request_id": request_id})

        # THE BINDING, CHECKED. A parked plan whose proposal no longer hashes
        # to what was asked about is not resumable under this answer.
        if self._proposal_fingerprint(parked["capability_id"],
                                      parked["args"]) != parked["fingerprint"]:
            self._bus.publish(
                "act.resume_refused", subject=self._subject,
                payload={"request_id": request_id, "reason": "fingerprint"},
                component="actor")
            return Outcome("refused", parked["capability_id"], "L0",
                           said="what I asked about is not what I would do now",
                           detail={"reason": "proposal_changed"})

        stale = (self._now_ms() - parked["parked_at_ms"]) > PARK_TTL_MS
        self._pdp.issue(Grant(
            grant_id=f"answered:{request_id}", subject=self._subject,
            capability_id=parked["capability_id"],
            target_scope=(self._target,), max_level="L5",
            expiry_ms=self._now_ms() + ANSWER_GRANT_TTL_MS, lease_epoch=0,
            delegable=False, issued_by="owner"))
        self._bus.publish(
            "act.resumed", subject=self._subject,
            payload={"request_id": request_id, "step": parked["step"],
                     "stale": stale,
                     "observations": len(parked["observations"]),
                     "note": ("the approved action runs; the rest of the plan "
                              "continues only if the observations are fresh")},
            component="actor")
        return self._resume_from(parked, stale=stale, permitted=permitted)

    def _resume_from(self, parked: dict, *, stale: bool,
                     permitted: Any = None) -> Outcome | None:
        """Run the action the owner approved, then continue if the plan is fresh.

        THE APPROVED ACTION IS EXECUTED, NOT RE-PROPOSED. Asking the model what
        to do next would spend the owner's answer on whatever it says now; the
        proposal is rebuilt from what was parked so the thing that runs is the
        thing that was described in the question.

        IT STILL GOES THROUGH `_one_step`, which means the full ladder: the
        fresh grant raises the ceiling, it does not bypass it. Containment,
        the self-modification boundary, the outbox record and the checkpoint
        all happen exactly as they would have without a pause.
        """
        # THE STOP REACHES A RESUMED TURN TOO, and it did not. `maybe_act` asks
        # before every step; resume walked straight into `_one_step` with no
        # such check, so an autonomous turn parked on a question would run its
        # approved action even if the emergency stop had been engaged while it
        # waited. The gap was widest exactly where it matters: a turn that is
        # WAITING is a turn that has been sitting there long enough for the
        # owner to have changed their mind and pressed the stop.
        if permitted is not None and not permitted():
            self._bus.publish(
                "act.stopped", subject=self._subject,
                payload={"request_id": parked["request_id"],
                         "step": parked["step"],
                         "note": ("autonomy was stopped while this turn waited "
                                  "for an answer; the approved action was not "
                                  "run")},
                component="actor")
            return Outcome("declined", parked["capability_id"], "L0",
                           said="autonomy was stopped while I waited, so I "
                                "have not done it",
                           detail={"request_id": parked["request_id"],
                                   "reason": "stopped_while_parked"})

        p = Proposal(parked["capability_id"], parked["args"],
                     parked.get("why", ""))
        observations = list(parked["observations"])
        out = self._one_step(p, parked["text"], parked["attention_state"],
                             parked["period"], parked.get("fragments"),
                             observations)
        outcomes = list(parked["outcomes"]) + [out.to_dict()]
        if out.kind not in ("refused", "failed", "asked"):
            observations.append(
                observe(p.capability_id, p.args,
                        (out.detail or {}).get("result") or {}))

        if stale or out.kind in ("refused", "failed", "asked"):
            if len(outcomes) > 1:
                out.detail = dict(out.detail or {})
                out.detail["steps"] = outcomes
                out.detail["resumed"] = True
                out.detail["plan_continued"] = False
                if stale:
                    out.detail["note"] = (
                        "the action you approved ran; the rest of the plan did "
                        "not continue because it was built on observations "
                        "older than the park window")
            return out

        return self.maybe_act(
            parked["text"], attention_state=parked["attention_state"],
            period=parked["period"], fragments=parked.get("fragments"),
            max_steps=parked["max_steps"], permitted=permitted,
            resume_state={"observations": observations, "outcomes": outcomes,
                          "signatures": list(parked["signatures"]),
                          "last": out,
                          "consecutive_refusals": parked["consecutive_refusals"],
                          "start_step": int(parked["step"]) + 1})

    @staticmethod
    def _authorization_for(period: str, observations: list) -> str:
        """How strongly the owner asked for THIS action, as opposed to a task.

        THE AXIS THE LADDER DID NOT HAVE. Every level rule answers "how
        dangerous is this". This answers "who wanted it", and the two come
        apart in the case the whole design exists for: a STEERED proposer emits
        something entirely reasonable that the owner never asked for, which is
        unremarkable on the danger axis and visible only here.

        Three cases, and the boundaries are the honest ones this system can
        actually tell apart:

        FREE_TIME is `unknown`. An autonomous trigger fired; nobody asked for
        anything. `unknown` rather than `none`, because the truthful statement
        is that nothing here can distinguish "the owner would have wanted this"
        from "the proposer decided to".

        A LATER STEP OF A TURN is `owner_task`. The owner asked for the errand
        and not for each move inside it, and by the second step the proposal is
        being shaped by what the first step observed -- which is exactly where
        a steered proposer gets its opening.

        THE FIRST STEP OF A SPOKEN TURN is `owner_explicit`. They said it, in
        this turn, in words.
        """
        if period == "free_time":
            return "unknown"
        return "owner_task" if observations else "owner_explicit"

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
        strength = self._authorization_for(period, observations)
        # ONE ID FOR THE WHOLE COMMAND, so the pre-check below and the
        # executor's re-check are recognisably the same instance. Without it a
        # single-use L4/L5 grant is spent by the first and gone by the second,
        # and the whole confirmation ladder ends in `grant_consumed` on the very
        # action the owner just approved -- which is what it did.
        command_id = str(uuid.uuid4())
        # NON-CONSUMING, BECAUSE THIS CHECK DOES NOT ACT. It exists to decide
        # whether a refusal should become a QUESTION; the executor re-checks
        # immediately before invoking and that is the binding, consuming one.
        # Spending the grant here left nothing for the check that actually
        # runs, so an approved L4/L5 action was refused against whatever weaker
        # grant remained -- the owner said yes and nothing happened.
        d = self._pdp.authorize(subject=self._subject,
                                capability_id=p.capability_id, args=p.args,
                                target=self._target, context_ceiling=ceil,
                                authorization=strength,
                                current_lease_epoch=0,
                                command_id=command_id,
                                consume=False)
        if not d.authorized:
            return self._ask(d, p, level, attention_state, period)

        # A SECOND OPINION ON WHAT CANNOT BE UNDONE, and only on that. The
        # ladder has already decided this is ALLOWED; the advisor is asked
        # whether it looks like a MISTAKE -- an irreversible action aimed at the
        # wrong target, a misreading of what was asked. Reviewing every read
        # would tax the ordinary path and teach everyone to skim the warnings.
        #
        # AND ITS VERDICT IS ONE-DIRECTIONAL. `PROCEED` does nothing: the action
        # faces the identical ladder it faced a line ago. Only `STOP` has an
        # effect, and the effect is to ASK THE OWNER rather than to refuse --
        # which is what makes an advisor safe to consult at all. An advisor that
        # could authorise would be a way to manufacture consent: feed it a
        # document arguing for the action and receive approval. `INV-ACT-3` says
        # content entering the system may never raise authority, and advice is
        # content entering the system.
        if self._advisor is not None:
            try:
                cap = self._registry.get(p.capability_id)
            except Exception:                          # noqa: BLE001
                cap = None
            if cap is not None and worth_reviewing(cap, level):
                seen = self._advisor.review(
                    capability_id=p.capability_id, args=p.args,
                    why=getattr(p, "why", ""), asked_for=text, level=level)
                if seen.get("verdict") == ADVISOR_STOP:
                    # Routed through the ordinary confirmation ladder rather
                    # than refused, so the turn PARKS and the owner's answer
                    # resumes it with the plan intact.
                    return self._ask(
                        Decision(False, "L0", "owner_confirmation_required",
                                 p.capability_id, self._subject,
                                 detail=str(seen.get("because") or "")[:300]),
                        p, level, attention_state, period)

        try:
            ex = self._executor.execute(subject=self._subject,
                                        capability_id=p.capability_id,
                                        args=p.args, target=self._target,
                                        command_id=command_id,
                                        context_ceiling=ceil,
                                        authorization=strength,
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
                           said=("I need your go-ahead for that, and I have no "
                                 "way to ask you right now"),
                           detail={"reason": decision.reason, "level": level})
        try:
            asked = self._broker.request(decision, target=self._target,
                                         period=period,
                                         attention_state=attention_state)
        except Exception as exc:                       # noqa: BLE001
            return Outcome("refused", proposal.capability_id, level,
                           said="that needs your say-so and I could not ask",
                           detail={"error": repr(exc)})
        return Outcome("asked", proposal.capability_id, level,
                       said=_ask_sentence(proposal.why),
                       detail={"reason": decision.reason, "asked": asked,
                               "level": level})

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
