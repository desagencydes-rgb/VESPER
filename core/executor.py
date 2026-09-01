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
                 reconciler: Any = None) -> None:
        self._bus = bus
        self._registry = registry
        self._pdp = pdp
        self._shadow = shadow
        self._reconciler = reconciler
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
