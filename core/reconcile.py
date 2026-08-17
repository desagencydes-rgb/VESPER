"""External-action reconciliation — exactly-once EFFECT, not exactly-once delivery.

THE DISTINCTION THE WHOLE FILE RESTS ON: exactly-once *delivery* does not exist
over an unreliable channel. Exactly-once *effect* does, and it costs two things —
an idempotency key the far side honours, and a **probe** that can ask "did my
action actually land?" Without the probe, a crash at the wrong moment leaves the
system unable to distinguish "not sent" from "sent, result lost", and both of the
available guesses are wrong some of the time.

THE THREE CRASH POINTS A-035 INJECTS, and why the middle one is the hard one:

    before the call   -> nothing happened. Replay is correct and safe.
    MID-CALL          -> UNKNOWN. The far side may or may not have acted.
    after the call,
    before recording  -> it happened, and the outbox does not know.

Only the first is safe to retry blindly. For the other two the recovery path
**probes** rather than replays, and that is the entire content of INV-EXT-1.

RECOVERY READS THE OUTBOX, NEVER REPLAYS THE TASK (INV-TASK-2 again, from the
other side). Replaying the task re-derives the plan and re-executes steps whose
effects already landed. The outbox is the record of what was *attempted*, which
is the only thing that can be reconciled against the far side.

A TOOL DECLARING `reconcilable: false` ESCALATES TO THE USER INSTEAD OF
RETRYING. If the effect cannot be checked and cannot be undone, the honest move
is to stop and ask. Retrying is the dishonest one, and it is how one payment
becomes two.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus

CRASH_POINTS = ("before_call", "mid_call", "after_call_before_record")

OUTBOX_STATES = ("INTENT", "SENT", "CONFIRMED", "UNKNOWN", "ESCALATED")


class ReconciliationRequired(Exception):
    """An outbox entry whose outcome is unknown and cannot be probed."""


@dataclass(slots=True)
class OutboxEntry:
    outbox_id: str
    task_id: str
    capability_id: str
    args: dict
    idempotency_key: str
    state: str = "INTENT"
    result: Any = None
    reconcilable: bool = True
    # SR-031 / DR-025: who the action was taken ON BEHALF OF, recorded on the
    # outbox record itself so the audit chain can attribute it.
    delegated_identity: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict:
        return {"outbox_id": self.outbox_id, "task_id": self.task_id,
                "capability_id": self.capability_id,
                "idempotency_key": self.idempotency_key, "state": self.state,
                "reconcilable": self.reconcilable,
                "delegated_identity": self.delegated_identity,
                "attempts": self.attempts}


class Reconciler:
    """Owns the outbox and the recovery path that reads it."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._entries: dict[str, OutboxEntry] = {}
        self._probes: dict[str, Callable[[OutboxEntry], Any]] = {}
        self._lock = threading.RLock()

    def register_probe(self, capability_id: str,
                       probe: Callable[[OutboxEntry], Any]) -> None:
        """A probe answers 'did this action land?' against the far side."""
        with self._lock:
            self._probes[capability_id] = probe

    def record_intent(self, entry: OutboxEntry) -> OutboxEntry:
        with self._lock:
            self._entries[entry.outbox_id] = entry
        self._bus.publish("outbox.intent", subject=entry.task_id,
                          payload=entry.to_dict(), component="reconcile")
        return entry

    def mark(self, outbox_id: str, state: str, result: Any = None) -> None:
        if state not in OUTBOX_STATES:
            raise ValueError(f"state {state!r} not in {OUTBOX_STATES}")
        with self._lock:
            e = self._entries[outbox_id]
            e.state, e.result = state, result
        self._bus.publish(f"outbox.{state.lower()}", subject=e.task_id,
                          payload=e.to_dict(), component="reconcile")

    def attempt(self, outbox_id: str, perform: Callable[[dict], Any], *,
                crash_at: str | None = None) -> dict:
        """Perform the external action, optionally crashing at an injected point.

        `crash_at` exists so A-035's three injections are expressible without a
        real process kill: the states left behind are identical, and a test that
        needs a real crash is a test that runs rarely.
        """
        with self._lock:
            e = self._entries[outbox_id]
            e.attempts += 1

        if crash_at == "before_call":
            # Nothing happened. The entry stays INTENT.
            return {"crashed_at": "before_call", "state": e.state}

        if crash_at == "mid_call":
            # The far side MAY have acted. This is the honest unknown.
            self.mark(outbox_id, "UNKNOWN")
            return {"crashed_at": "mid_call", "state": "UNKNOWN"}

        result = perform(e.args)

        if crash_at == "after_call_before_record":
            # It happened and the outbox does not know. Indistinguishable from
            # mid-call from the inside, which is why both go to the probe.
            self.mark(outbox_id, "UNKNOWN")
            return {"crashed_at": "after_call_before_record", "state": "UNKNOWN"}

        self.mark(outbox_id, "CONFIRMED", result)
        return {"crashed_at": None, "state": "CONFIRMED", "result": result}

    def recover(self, task_id: str) -> list:
        """THE RECOVERY PATH. Reads the outbox; never replays the task."""
        with self._lock:
            pending = [e for e in self._entries.values()
                       if e.task_id == task_id
                       and e.state in ("INTENT", "SENT", "UNKNOWN")]
        out = []
        for e in pending:
            if e.state == "INTENT":
                # Safe: nothing left the machine.
                out.append({"outbox_id": e.outbox_id, "action": "replay_safe",
                            "reason": "intent recorded, call never made"})
                continue

            if not e.reconcilable:
                # Cannot be checked, cannot be undone -> stop and ask.
                self.mark(e.outbox_id, "ESCALATED")
                self._bus.publish(
                    "outbox.escalated_to_user", subject=task_id,
                    payload={**e.to_dict(),
                             "reason": ("tool declares reconcilable=false: the "
                                        "effect cannot be checked and cannot be "
                                        "undone, so the honest move is to stop "
                                        "and ask. Retrying is how one payment "
                                        "becomes two.")},
                    component="reconcile")
                out.append({"outbox_id": e.outbox_id, "action": "escalated",
                            "reason": "not reconcilable"})
                continue

            probe = self._probes.get(e.capability_id)
            if probe is None:
                self.mark(e.outbox_id, "ESCALATED")
                out.append({"outbox_id": e.outbox_id, "action": "escalated",
                            "reason": "no probe registered for this capability"})
                continue

            landed = probe(e)
            if landed:
                self.mark(e.outbox_id, "CONFIRMED", landed)
                out.append({"outbox_id": e.outbox_id, "action": "confirmed",
                            "reason": "probe found the effect; NOT resent"})
            else:
                out.append({"outbox_id": e.outbox_id, "action": "replay_safe",
                            "reason": "probe found no effect; safe to resend "
                                      "under the same idempotency key"})

        self._bus.publish("outbox.recovered", subject=task_id,
                          payload={"task_id": task_id, "entries": out,
                                   "note": ("recovery read the OUTBOX, not the "
                                            "task -- replaying the task would "
                                            "re-execute steps whose effects "
                                            "already landed")},
                          component="reconcile")
        return out

    def audit_chain(self, outbox_id: str) -> dict:
        """A-035.4: trigger -> authority -> command -> outbox -> probe -> result."""
        e = self._entries[outbox_id]
        return {
            "outbox": e.to_dict(),
            "chain": ["trigger", "authority", "command", "outbox", "probe",
                      "result"],
            "delegated_identity": e.delegated_identity,
            "reconstructible": e.delegated_identity is not None,
        }

    def get(self, outbox_id: str) -> OutboxEntry | None:
        return self._entries.get(outbox_id)
