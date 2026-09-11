"""Tool execution and compensation — the path every action actually takes.

WHAT THIS ADDS OVER THE AUTHORIZATION CORE. `DF-AUTHORIZE` answers "may this
happen"; this answers "what happened, and what do we do when it half-happened".
Those are different problems and the second is the one that produces
unrecoverable states.

AUTHORIZATION IS RE-CHECKED IMMEDIATELY BEFORE INVOCATION, never once at the
top of a task. A grant can expire between planning and acting, and a check done
at plan time authorises an action taken under a rule that has since changed.
A-024.4 is exactly this case: a grant expiring mid-task sends the task to
**WAITING** — not a silent proceed (which acts without authority) and not
FAILED (which throws away work that is merely paused).

COMPENSATION IS NOT ROLLBACK, and the distinction decides the design.
`reversible` means the effect can be undone. `compensatable` means it cannot be
undone but a *counter-action* exists — you cannot unsend an email, you can send
a correction. `irreversible` means neither. So:

  * a `compensatable` capability MUST have a registered compensator before it
    can execute. Discovering at failure time that no compensator exists is
    discovering it too late.
  * an `irreversible` capability is NEVER retried on an unknown outcome. SPEC-C
    is explicit: "non-idempotent action with unknown outcome -> compensate or
    escalate, **never retry**". Retrying is how one payment becomes two.

THE OUTBOX ORDER IS INTENT -> ACT -> RECORD, and the middle step is the one
that can be interrupted. If the process dies after acting but before recording,
the intent looks unsent. That is why external effects carry an idempotency key
the far side honours: exactly-once delivery does not exist, exactly-once
*effect* does, and only with a key.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .authorize import Decision, PolicyDecisionPoint
from .bus import EventBus
from .capabilities import touched_paths
from .capability import CapabilityRegistry
from .checkpoint import CheckpointUnavailable

OUTCOMES = ("VERIFIED", "FAILED", "OUTCOME_UNKNOWN", "COMPENSATED", "REFUSED")


# WAITING FOR AN ANSWER IS NOT BEING BLOCKED, and this is the only
# distinction the bar needs to get right. A refusal that PAUSES for the owner's
# approval is already visible -- they are being asked. A refusal that ENDS the
# attempt is the owner's word for blocked, and until 2026-09-11 it reached
# nothing: `flag.raised` was published from exactly ONE place, the branch where
# a capability SUCCEEDED but degraded. Three `tool.refused` sites and two
# `tool.failed` sites published events the bar does not subscribe to, so the
# surface whose stated job is "one destination for every flag VESPER raises"
# showed a narrow slice of them and looked complete.
#
# Owner, 2026-09-11: "flags contain everything that should be flagged, even
# stuff vesper got blocked on or couldn't achieve".
PAUSED_NOT_BLOCKED = ("grant_expired", "pdp_unavailable")


def blocked_flag_id(capability_id: str) -> str:
    """The condition "vesper is not allowed to do this", once per capability.

    THE REASON IS IN THE TEXT AND NOT IN THE ID, and that is the whole point.
    Keyed on the reason as well, this flag could never be retracted: a later
    SUCCESS knows the capability and the target but cannot know which refusal
    reason it has just contradicted, so `_resolved_ids` could not name the row
    to clear and every refusal would have been permanent. `CI-137`'s check
    caught it by refusing a raise site that builds its own id -- two copies of
    an id expression drift, and the drift shows up as a flag nothing can clear.
    """
    return f"refused:{capability_id}"


def unimplemented_flag_id(capability_id: str) -> str:
    """The condition "vesper can name this and has nothing bound to do it"."""
    return f"unimplemented:{capability_id}"


def flag_id_for(capability_id: str, result: dict, args: dict, target: Any) -> str:
    """The name of the CONDITION a flag is about. One derivation, two callers.

    THE ID NAMES THE CONDITION, NOT THE EXECUTION. It keyed on the idempotency
    key once, which carries a per-execution uuid -- so every retry of the same
    failure produced a NEW flag and the dedupe in `HomeState.raise_flag` could
    never fire. Driven 2026-09-09: asking twice for the same impossible
    relocation put two identical flags in the bar, which is exactly the "a
    repeating failure fills the bar it is trying to be visible in" case the
    dedupe was written for.

    AND THE RUNG IS NOT PART OF IT, which was the second half of the same
    mistake. `window.relocate` fails at four named rungs -- `cannot_degrade`,
    `refused_unsaved`, `rebuild_failed`, and after a retry -- and putting the
    rung in the id made each attempt at ONE unresolvable situation its own row.
    Worse, it made retraction impossible: a relocation that fails at
    `cannot_degrade` and later succeeds derives two different ids, so the
    success could never cancel the failure. A rung is which ATTEMPT failed,
    which is exactly the execution detail the first sentence rules out. The
    owner sees one row per capability per window, carrying the latest reason.

    A capability may still name its own condition, and the ones that do are the
    ones whose condition is not "this capability on this target": `_act` names
    `host.accessibility`, which is about the machine.

    THIS FUNCTION IS THE ONLY DERIVATION so that raise and retract cannot drift
    apart. Two copies of this expression is a bar that raises under one name and
    clears under another, and the symptom would be a flag that will not go away
    -- indistinguishable from the defect this replaced.
    """
    named = str((result or {}).get("flag_id") or "").strip()
    if named:
        return named
    return ":".join(str(x) for x in
                    (capability_id, (args or {}).get("window_id") or target) if x)


def _resolved_ids(capability_id: str, result: dict, args: dict,
                  target: Any) -> list:
    """Which flag conditions this clean result has just contradicted.

    TWO SOURCES, AND THE SECOND IS WHY THIS IS NOT ONE LINE.

    The derived id covers the ordinary case: the same capability on the same
    target, which failed before and did not fail now. That is sound without any
    inference -- it is the same condition, re-measured.

    `resolved` covers what a result knows and the derivation cannot: a window
    act that SUCCEEDS is direct evidence that accessibility is granted to this
    build, and `host.accessibility` is not keyed on any window. A capability
    that has read the world names what the world no longer supports, in the same
    result, rather than leaving a stale row to be noticed. Unknown ids are
    harmless: `clear_flag` for a flag that is not raised does nothing.

    NOTHING HERE INFERS FROM ABSENCE. A capability that says nothing resolves
    nothing but its own condition, which is the fail-closed direction for a
    surface whose job is to keep calling for action until someone acts.
    """
    # A SUCCESS CONTRADICTS "NOT ALLOWED" AND "NOTHING BOUND" DIRECTLY, and
    # these were missing until 2026-09-11 -- the two conditions were newly
    # raisable and nothing could retract them, so a capability refused once
    # carried a permanent row on the bar even after the owner granted it.
    out = [flag_id_for(capability_id, {}, args, target),
           blocked_flag_id(capability_id),
           unimplemented_flag_id(capability_id)]
    named = (result or {}).get("resolved")
    if isinstance(named, str):
        named = [named]
    if isinstance(named, (list, tuple, set)):
        out.extend(str(n).strip() for n in named if str(n).strip())
    seen, uniq = set(), []
    for fid in out:
        if fid and fid not in seen:
            seen.add(fid)
            uniq.append(fid)
    return uniq


class NotAuthorized(Exception):
    """Execution refused. Carries the DF-AUTHORIZE decision."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(f"{decision.reason}: {decision.detail}")
        self.decision = decision


class CompensatorMissing(Exception):
    """A `compensatable` capability was registered without a compensator."""


@dataclass(slots=True)
class Execution:
    execution_id: str
    capability_id: str
    subject: str
    outcome: str
    result: Any = None
    error: str | None = None
    compensated: bool = False
    idempotency_key: str = ""
    checkpoint: str | None = None

    def to_dict(self) -> dict:
        return {"execution_id": self.execution_id,
                "capability_id": self.capability_id, "subject": self.subject,
                "outcome": self.outcome, "error": self.error,
                "compensated": self.compensated,
                "idempotency_key": self.idempotency_key,
                "checkpoint": self.checkpoint}


class Executor:
    """Invokes capabilities. Every invocation passes DF-AUTHORIZE first."""

    def __init__(self, bus: EventBus, registry: CapabilityRegistry,
                 pdp: PolicyDecisionPoint, shadow: Any = None,
                 reconciler: Any = None, selfmod: Any = None) -> None:
        self._bus = bus
        self._registry = registry
        self._pdp = pdp
        self._shadow = shadow
        self._reconciler = reconciler
        self._selfmod = selfmod
        self._impls: dict[str, Callable[[dict], Any]] = {}
        self._compensators: dict[str, Callable[[dict, Any], Any]] = {}
        self._seen_keys: set = set()
        self._lock = threading.RLock()

    def bind(self, capability_id: str, impl: Callable[[dict], Any], *,
             compensator: Callable[[dict, Any], Any] | None = None) -> None:
        """Attach an implementation. Refuses `compensatable` without a compensator.

        Checked HERE rather than at failure time. A capability that declares it
        can be compensated and cannot is worse than one that admits it is
        irreversible: the first produces a plan that assumes recovery exists.
        """
        cap = self._registry.get(capability_id)
        if cap.reversibility == "compensatable" and compensator is None:
            raise CompensatorMissing(
                f"{capability_id!r} declares reversibility='compensatable' but no "
                "compensator was supplied. Refused at bind time -- discovering at "
                "failure time that no counter-action exists is discovering it too "
                "late, and the plan will already have assumed recovery.")
        with self._lock:
            self._impls[capability_id] = impl
            if compensator is not None:
                self._compensators[capability_id] = compensator

    def execute(self, *, subject: str, capability_id: str, args: dict,
                target: str, context_ceiling: str = "L5",
                authorization: str = "owner_explicit",
                current_lease_epoch: int = 0, command_id: str | None = None,
                idempotency_key: str | None = None,
                task_id: str | None = None) -> Execution:
        cap = self._registry.get(capability_id)
        eid = str(uuid.uuid4())
        key = idempotency_key or f"{capability_id}:{target}:{eid}"

        # Re-checked HERE, immediately before invocation. A check at plan time
        # authorises an action taken under a rule that may since have changed.
        d = self._pdp.authorize(subject=subject, capability_id=capability_id,
                                args=args, target=target,
                                context_ceiling=context_ceiling,
                                authorization=authorization,
                                current_lease_epoch=current_lease_epoch,
                                command_id=command_id)
        if not d.authorized:
            ex = Execution(eid, capability_id, subject, "REFUSED",
                           error=f"{d.reason}: {d.detail}", idempotency_key=key)
            self._bus.publish("tool.refused", subject=task_id or subject,
                              payload={**ex.to_dict(), "decision": d.to_dict()},
                              component="executor")
            # A-024.4: an expired grant pauses the task rather than failing it.
            if d.reason in ("grant_expired", "pdp_unavailable") and task_id:
                self._bus.publish(
                    "task.waiting_on_authorization", subject=task_id,
                    payload={"task_id": task_id, "capability_id": capability_id,
                             "reason": d.reason,
                             "task_state": "WAITING",
                             "note": ("not a silent proceed, which would act "
                                      "without authority, and not FAILED, which "
                                      "would discard work that is merely paused")},
                    component="executor")
            elif d.reason not in PAUSED_NOT_BLOCKED:
                # BLOCKED, AND THE OWNER HEARS ABOUT IT. Keyed on the
                # capability and the reason rather than on the execution, so a
                # capability refused forty times is one row: the condition is
                # "this is not permitted", not "it was attempted again".
                self._bus.publish(
                    "flag.raised", subject=task_id or subject,
                    payload={"id": flag_id_for(
                                 capability_id,
                                 {"flag_id": blocked_flag_id(capability_id)},
                                 args, target)[:160],
                             "capability_id": capability_id,
                             "text": (f"vesper was not allowed to "
                                      f"{capability_id}: {d.detail}"
                                      or d.reason)[:400],
                             "recheck": {"capability_id": capability_id,
                                         "args": dict(args or {})}},
                    component="executor")
            raise NotAuthorized(d)

        # Idempotency at the executor, not only at the outbox: a replayed plan
        # must not invoke twice even when the outbox cursor was lost.
        with self._lock:
            if key in self._seen_keys:
                ex = Execution(eid, capability_id, subject, "VERIFIED",
                               result=None, idempotency_key=key)
                self._bus.publish("tool.suppressed_duplicate",
                                  subject=task_id or subject,
                                  payload=ex.to_dict(), component="executor")
                return ex
            impl = self._impls.get(capability_id)

        if impl is None:
            ex = Execution(eid, capability_id, subject, "FAILED",
                           error="no implementation bound", idempotency_key=key)
            self._bus.publish("tool.failed", subject=task_id or subject,
                              payload=ex.to_dict(), component="executor")
            self._bus.publish(
                "flag.raised", subject=task_id or subject,
                payload={"id": flag_id_for(
                             capability_id,
                             {"flag_id": unimplemented_flag_id(capability_id)},
                             args, target)[:160],
                         "capability_id": capability_id,
                         "text": (f"vesper can name {capability_id} and has "
                                  f"nothing bound to carry it out")[:400]},
                component="executor")
            return ex

        # THE OUTBOX RECORD IS WRITTEN BEFORE THE EFFECT, and "before" is the
        # entire invariant (INV-ACT-6). Recording an external send afterwards is
        # trivially easy and completely useless: the case that matters is a
        # crash between the send and the record, and after-the-fact bookkeeping
        # is exactly blind to it. A resumed task then re-sends, and a duplicated
        # external send has no undo.
        #
        # ONLY FOR CAPABILITIES THAT DECLARE AN EXTERNAL EFFECT. `fs.write` and
        # `fs.edit` change this machine and are covered by the checkpoint below;
        # `shell.run` can reach anything, which is what `external_effect` marks.
        # THE SELF-MODIFICATION BOUNDARY, ASKED BEFORE THE WRITE AND NOT BY
        # THE LADDER. `fs_write_level` already returns L5 for governed trees,
        # and INV-SELF-3 says that is not enough: an L5 grant does not lift
        # this. A boundary a sufficiently privileged grant can cross is one an
        # injected page will eventually talk its way past, and A-030's fixture
        # is an overnight autonomous run on injected content with nobody
        # present -- precisely the condition under which disposition fails.
        #
        # REFUSED ON THE PATH, NOT ON THE ARGUMENT. It does not read the reason
        # for the write, so there is nothing to argue with.
        #
        # AND THE WORKSPACE IS THE INTENDED WAY TO WORK (A-030.6). The
        # distinction is not WHAT is edited but WHERE: a governed path in the
        # running artifact is refused; the same content in the workspace is the
        # thing VESPER is supposed to do overnight and propose in the morning.
        if self._selfmod is not None:
            for target in touched_paths(capability_id, args):
                self._selfmod.check_write(target, subject=subject,
                                          level=d.effective_level)

        outbox_id = None
        if self._reconciler is not None and getattr(cap, "external_effect", False):
            from .reconcile import OutboxEntry
            outbox_id = f"ob-{eid}"
            self._reconciler.record_intent(OutboxEntry(
                outbox_id=outbox_id, task_id=task_id or subject,
                capability_id=capability_id, args=dict(args),
                idempotency_key=key,
                # A COMMAND'S EFFECT IS NOT GENERICALLY PROBEABLE, which is why
                # `shell.run` has no independent verifier either. Declaring it
                # reconcilable would promise a recovery path that does not
                # exist, and `recover()` escalates to the owner instead of
                # retrying -- the honest move, and the one that stops one
                # payment becoming two.
                reconcilable=False))

        # THE SNAPSHOT IS TAKEN HERE, at the one place every execution passes,
        # and BEFORE the implementation runs. Hooking it in the actor instead
        # would leave any other caller of `execute` writing with no undo -- the
        # same shape as a subsystem that is built, gated, and reachable from
        # one path out of two.
        #
        # FAIL CLOSED. A capability that declares it touches files does not run
        # when its pre-state cannot be recorded. Writing over the owner's data
        # with the undo quietly unavailable is the one moment the undo exists
        # for.
        checkpoint_id = None
        targets = touched_paths(capability_id, args)
        if targets:
            if self._shadow is None:
                ex = Execution(eid, capability_id, subject, "REFUSED",
                               error="no_checkpoint_store", idempotency_key=key)
                self._bus.publish("tool.refused", subject=task_id or subject,
                                  payload={**ex.to_dict(),
                                           "why": "this capability changes files "
                                                  "and no checkpoint store is "
                                                  "attached, so the change could "
                                                  "not be undone"},
                                  component="executor")
                # CARRIES A DECISION, like every other refusal out of this
                # method. Raising with a bare string made `e.decision` a str,
                # and A-024.4 reads `e.decision.reason` -- so the acceptance
                # test failed on an AttributeError rather than on the property
                # it was asserting.
                raise NotAuthorized(Decision(
                    False, "L0", "no_checkpoint_store", capability_id, subject,
                    f"{capability_id} changes files and no checkpoint store is "
                    "attached, so the change could not be undone"))
            try:
                checkpoint_id = self._shadow.checkpoint(
                    targets, f"before {capability_id} [{eid}]")
            except CheckpointUnavailable as exc:
                ex = Execution(eid, capability_id, subject, "REFUSED",
                               error=f"checkpoint_failed: {exc}",
                               idempotency_key=key)
                self._bus.publish("tool.refused", subject=task_id or subject,
                                  payload={**ex.to_dict()}, component="executor")
                raise
            self._bus.publish("tool.checkpointed", subject=task_id or subject,
                              payload={"execution_id": eid,
                                       "capability_id": capability_id,
                                       "checkpoint": checkpoint_id,
                                       "paths": [str(t) for t in targets]},
                              component="executor")

        self._bus.publish("tool.invoked", subject=task_id or subject,
                          payload={"execution_id": eid,
                                   "capability_id": capability_id,
                                   "effective_level": d.effective_level,
                                   "checkpoint": checkpoint_id,
                                   "idempotency_key": key},
                          component="executor")
        try:
            result = impl(args)
        except Exception as e:  # noqa: BLE001
            if outbox_id is not None:
                # UNKNOWN, NOT FAILED. The implementation raised, and from in
                # here a raise after the effect landed is indistinguishable
                # from one before it. Calling that FAILED would licence a
                # retry of something that may already have happened.
                self._reconciler.mark(outbox_id, "UNKNOWN")
            return self._handle_failure(eid, cap, subject, args, key, e, task_id)
        if outbox_id is not None:
            self._reconciler.mark(outbox_id, "CONFIRMED", result)

        with self._lock:
            self._seen_keys.add(key)
        ex = Execution(eid, capability_id, subject, "VERIFIED", result=result,
                       idempotency_key=key, checkpoint=checkpoint_id)
        self._bus.publish("tool.completed", subject=task_id or subject,
                          payload=ex.to_dict(), component="executor")
        # A FLAG IS PART OF A RESULT AND MUST REACH A SURFACE.
        #
        # Published HERE because this is the one place every capability's
        # result passes through, and because `Execution.to_dict()` deliberately
        # does not carry the result -- so a subscriber to `tool.completed`
        # cannot see a flag at all. Without this the flags already being
        # produced go nowhere: `window.relocate` returns `degraded: true` with
        # its `notes`, and `window.open` reports a window the system placed on a
        # Desktop VESPER cannot reach, and both were read by nothing.
        #
        # A DEGRADED RESULT WITH NO TEXT IS STILL A FLAG. `degraded` without a
        # `flag` string means something was raised and never given words, which
        # is worth surfacing as itself rather than dropping silently.
        if isinstance(result, dict) and (result.get("flag") or result.get("degraded")):
            text = str(result.get("flag") or "").strip()
            if not text:
                notes = result.get("notes")
                if isinstance(notes, list) and notes:
                    text = "; ".join(str(n) for n in notes)[:400]
            # `reason` IS READ HERE BECAUSE THE ACTOR READS IT THERE. This
            # consumer took `flag`/`notes` and the actor took `reason`/`flag`,
            # so a capability that explained itself in `reason` -- the key the
            # owner-facing sentence uses -- reached the flag bar as "said
            # nothing about how". Two readers of the same result disagreeing
            # about which key holds the explanation is a defect in the pair,
            # not in whichever capability picked the other one.
            if not text:
                text = str(result.get("reason") or "").strip()
            if not text:
                text = (f"{capability_id} completed in a degraded way and said "
                        "nothing about how")
            self._bus.publish("flag.raised", subject=task_id or subject,
                              payload={"id": flag_id_for(capability_id, result,
                                                         args, target)[:160],
                                       "capability_id": capability_id,
                                       "text": text[:400]},
                              component="executor")
        # AND A CLEAN RESULT RETRACTS WHAT ITS OWN FAILURE RAISED.
        #
        # THE BAR WAS RAISE-ONLY IN PRODUCTION. `HomeState.clear_flag` existed,
        # worked, and had exactly ONE caller in the whole tree: the check for
        # this feature, which called it itself and then asserted the flag was
        # gone. So `CI-137` proved the mechanism while nothing reached it --
        # the built-and-reached-by-nothing shape, with the check's own comment
        # ("or the bar reports a problem that is over") describing the live
        # defect rather than guarding against it.
        #
        # WHAT THAT COSTS THE OWNER IS A FALSE ALARM THAT NEVER GOES AWAY. A
        # rebuild revokes accessibility, `_act` flags `host.accessibility`, the
        # owner grants it in System Settings, vesper starts working -- and the
        # bar keeps telling them it is not granted until the process restarts.
        # The mode watcher makes it worse: it retries, so the sequence
        # fail -> flag -> retry -> succeed is the NORMAL one, and a bar that
        # cannot retract turns every recovered failure into a permanent row.
        #
        # `degraded` IS THE DISCRIMINATOR, NOT `ok`. `window.relocate` returns
        # `ok: True` with `degraded: True` when it rebuilt a window instead of
        # moving it -- a success that is still worth flagging -- so retracting
        # on `ok` alone would clear a flag the same result just raised.
        # `ok is not False` RATHER THAN `ok`, because a clean result is not
        # obliged to say so. `window.list` is a read: it returns the inventory
        # and no `ok` key at all, and it is the one capability whose whole job is
        # re-reading the world -- exactly the result that should be allowed to
        # retract. What must NOT retract is a refusal, and a refusal says
        # `ok: False` explicitly. The branch above has already taken everything
        # carrying a flag or `degraded`, so what reaches here reported no problem.
        elif isinstance(result, dict) and result.get("ok") is not False:
            for fid in _resolved_ids(capability_id, result, args, target):
                self._bus.publish("flag.cleared", subject=task_id or subject,
                                  payload={"id": fid[:160],
                                           "capability_id": capability_id},
                                  component="executor")
        return ex

    def _handle_failure(self, eid: str, cap, subject: str, args: dict,
                        key: str, exc: Exception, task_id: str | None) -> Execution:
        """A failure whose outcome cannot be observed is OUTCOME_UNKNOWN.

        Not FAILED. "It threw" and "it did not happen" are different claims,
        and treating the first as the second is how a system retries something
        that already took effect.
        """
        unknown = getattr(exc, "outcome_unknown", False)
        outcome = "OUTCOME_UNKNOWN" if unknown else "FAILED"
        ex = Execution(eid, cap.capability_id, subject, outcome,
                       error=f"{type(exc).__name__}: {exc}", idempotency_key=key)

        if outcome == "OUTCOME_UNKNOWN":
            self._bus.publish(
                "tool.outcome_unknown", subject=task_id or subject,
                payload={**ex.to_dict(), "reversibility": cap.reversibility,
                         "retry_permitted": False,
                         "note": ("SPEC-C: a non-idempotent action with an unknown "
                                  "outcome is compensated or escalated, NEVER "
                                  "retried -- retrying is how one payment becomes "
                                  "two")},
                component="executor")

        comp = self._compensators.get(cap.capability_id)
        if comp is not None and cap.reversibility == "compensatable":
            try:
                comp(args, ex.result)
                ex.compensated = True
                ex.outcome = "COMPENSATED"
                self._bus.publish("tool.compensated", subject=task_id or subject,
                                  payload=ex.to_dict(), component="executor")
            except Exception as ce:  # noqa: BLE001
                self._bus.publish(
                    "tool.compensation_failed", subject=task_id or subject,
                    payload={**ex.to_dict(),
                             "compensation_error": f"{type(ce).__name__}: {ce}",
                             "note": ("escalate: the effect stands and the "
                                      "counter-action did not")},
                    component="executor")
        elif cap.reversibility == "irreversible":
            self._bus.publish(
                "tool.irreversible_failure", subject=task_id or subject,
                payload={**ex.to_dict(),
                         "note": ("irreversible and uncompensatable: escalated, "
                                  "never retried")},
                component="executor")
        else:
            self._bus.publish("tool.failed", subject=task_id or subject,
                              payload=ex.to_dict(), component="executor")
        return ex
