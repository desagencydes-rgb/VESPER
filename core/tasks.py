"""Durable task state, checkpoints, and the outbox that stops double-sending.

TWO INVARIANTS SHAPE THIS WHOLE FILE.

INV-TASK-1: THERE IS NO `RUNNING -> SUCCEEDED` TRANSITION. Success is reachable
only through `VERIFYING` with a passing strategy. This is the anti-chatbot
property in its smallest form: a system that can mark its own work done because
it finished executing has only proved that it stopped, not that it worked. The
transition table below simply does not contain the edge, so the shortcut is
unavailable rather than discouraged.

INV-TASK-2: RESUME REPLAYS FROM THE OUTBOX CURSOR, NEVER FROM PLAN START. A
task that sent an email at step 3 and died at step 4 must not send it again on
resume. Replaying from the plan start is the obvious implementation and it is
wrong in the one way that cannot be undone -- external effects have no rollback.
The cursor is the single field that makes resumption safe, which is why it is
`required` on the checkpoint schema.

THE OUTBOX PATTERN, stated plainly because it is the load-bearing piece:
an external action is (1) recorded as an intent, (2) performed, (3) marked
sent -- each step durable. A crash between 1 and 2 replays it, which is
correct. A crash between 2 and 3 leaves an intent that LOOKS unsent; that is
the genuinely hard case, and it is why `send()` takes an idempotency key that
the external side honours. Exactly-once delivery does not exist; exactly-once
EFFECT does, and only with a key.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus
from .hlc import HLC, HybridLogicalClock
from .lease import LeaseManager
from .store import StoreSet

# contracts/entities/task.schema.json
STATES = ("CREATED", "READY", "RUNNING", "WAITING", "VERIFYING", "RETRYING",
          "BLOCKED", "RESUMABLE", "SUCCEEDED", "FAILED", "CANCELLED")

# The transition table IS the invariant. Note what is absent: RUNNING has no
# edge to SUCCEEDED. INV-TASK-1 is enforced by the shape of this dict, not by a
# check that could be forgotten at one call site.
ALLOWED: dict[str, tuple[str, ...]] = {
    "CREATED":   ("READY", "CANCELLED"),
    "READY":     ("RUNNING", "BLOCKED", "CANCELLED"),
    "RUNNING":   ("WAITING", "VERIFYING", "RESUMABLE", "BLOCKED",
                  "RETRYING", "FAILED", "CANCELLED"),
    "WAITING":   ("RUNNING", "RESUMABLE", "BLOCKED", "FAILED", "CANCELLED"),
    "VERIFYING": ("SUCCEEDED", "RETRYING", "FAILED", "BLOCKED", "RESUMABLE"),
    "RETRYING":  ("RUNNING", "FAILED", "CANCELLED", "RESUMABLE"),
    "BLOCKED":   ("READY", "RUNNING", "FAILED", "CANCELLED", "RESUMABLE"),
    "RESUMABLE": ("RUNNING", "READY", "FAILED", "CANCELLED"),
    "SUCCEEDED": (),
    "FAILED":    (),
    "CANCELLED": (),
}

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")

VERIFICATION_KINDS = ("deterministic", "retrieval_grounded", "model_critic",
                      "self_model", "human", "deferred", "none_declared")


class IllegalTransition(Exception):
    """A state transition not present in the table. Includes RUNNING→SUCCEEDED."""


class VerificationRequired(Exception):
    """Success was claimed without a passing verification strategy."""


@dataclass(slots=True)
class Task:
    task_id: str
    goal: str
    state: str
    verification_criteria: dict
    created_at_hlc: HLC
    lease_epoch: int
    schema_version: int = 1
    plan: list | None = None
    checkpoint_ref: str | None = None
    outbox_cursor: str | None = None
    completed_steps: list = field(default_factory=list)
    evidence_refs: list = field(default_factory=list)
    priority_class: str = "active_user_task"
    verified_by: str | None = None
    updated_at_hlc: HLC | None = None
    resource_consumed: dict = field(default_factory=dict)
    blocked_reason: dict | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "schema_version": self.schema_version,
            "goal": self.goal,
            "state": self.state,
            "verification_criteria": self.verification_criteria,
            "verified_by": self.verified_by,
            "priority_class": self.priority_class,
            "plan": self.plan,
            "checkpoint_ref": self.checkpoint_ref,
            "outbox_cursor": self.outbox_cursor,
            "completed_steps": self.completed_steps,
            "evidence_refs": self.evidence_refs,
            "lease_epoch": self.lease_epoch,
            "resource_consumed": self.resource_consumed,
            "blocked_reason": self.blocked_reason,
            "created_at_hlc": self.created_at_hlc.to_dict(),
            "updated_at_hlc": self.updated_at_hlc.to_dict() if self.updated_at_hlc else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            task_id=d["task_id"], goal=d["goal"], state=d["state"],
            verification_criteria=d["verification_criteria"],
            created_at_hlc=HLC.from_dict(d["created_at_hlc"]),
            lease_epoch=d["lease_epoch"],
            schema_version=d.get("schema_version", 1),
            plan=d.get("plan"), checkpoint_ref=d.get("checkpoint_ref"),
            outbox_cursor=d.get("outbox_cursor"),
            completed_steps=d.get("completed_steps") or [],
            evidence_refs=d.get("evidence_refs") or [],
            priority_class=d.get("priority_class", "active_user_task"),
            verified_by=d.get("verified_by"),
            updated_at_hlc=(HLC.from_dict(d["updated_at_hlc"])
                            if d.get("updated_at_hlc") else None),
            resource_consumed=d.get("resource_consumed") or {},
            blocked_reason=d.get("blocked_reason"),
        )


class TaskStore:
    """Durable tasks, checkpoints and the outbox. All writes fenced by epoch."""

    DOMAIN = "tasks"
    # Tasks are namespaced inside the domain. The `tasks` domain is a LEASED
    # DOMAIN, not a private table -- other components legitimately keep keyed
    # state there. Without a prefix, `all()` parses every row in the domain as
    # a Task and dies on the first one that is not, which is exactly what
    # happened on the first run of A-034.3. Selecting by prefix makes "which
    # rows are tasks" structural instead of a guess.
    KEY_PREFIX = "task:"

    @classmethod
    def _key(cls, task_id: str) -> str:
        return f"{cls.KEY_PREFIX}{task_id}"

    def __init__(self, store: StoreSet, clock: HybridLogicalClock, bus: EventBus,
                 leases: LeaseManager) -> None:
        self._store = store
        self._clock = clock
        self._bus = bus
        self._leases = leases
        self._lock = threading.RLock()

    def _epoch(self) -> int:
        return self._leases.epoch(self.DOMAIN)

    # ----------------------------------------------------------------- write

    def create(self, goal: str, verification_criteria: dict, *,
               priority_class: str = "active_user_task",
               plan: list | None = None) -> Task:
        kind = verification_criteria.get("kind")
        if kind not in VERIFICATION_KINDS:
            raise VerificationRequired(
                f"verification_criteria.kind must be one of {VERIFICATION_KINDS}, "
                f"got {kind!r}. REM-010 4.2: criteria are TYPED, never free text -- "
                "a task whose criteria are untyped cannot be verified, only asserted."
            )
        at = self._clock.now()
        t = Task(task_id=str(uuid.uuid4()), goal=goal, state="CREATED",
                 verification_criteria=verification_criteria,
                 created_at_hlc=at, lease_epoch=self._epoch(),
                 priority_class=priority_class, plan=plan, updated_at_hlc=at)
        self._persist(t, at)
        self._bus.publish("task.created", subject=t.task_id,
                          payload={"task_id": t.task_id, "goal": goal,
                                   "priority_class": priority_class},
                          component="tasks", at=at)
        return t

    def transition(self, task: Task, to: str, *, evidence: dict | None = None) -> Task:
        if to not in STATES:
            raise IllegalTransition(f"unknown state {to!r}")
        allowed = ALLOWED[task.state]
        if to not in allowed:
            extra = ""
            if task.state == "RUNNING" and to == "SUCCEEDED":
                extra = (" -- INV-TASK-1: there is NO RUNNING->SUCCEEDED edge. "
                         "Success is reachable only through VERIFYING with a "
                         "passing strategy. Finishing execution is not evidence "
                         "the work was done.")
            raise IllegalTransition(
                f"{task.state} -> {to} is not permitted (allowed: {allowed or 'none, terminal'}){extra}")

        if to == "SUCCEEDED":
            # Belt and braces: the table already makes SUCCEEDED reachable only
            # from VERIFYING, but the verdict must also be present and passing.
            if not (evidence or {}).get("passed"):
                raise VerificationRequired(
                    "SUCCEEDED requires evidence={'passed': True, ...} from the "
                    "declared verification strategy. A task cannot mark itself done.")
            task.verified_by = (evidence or {}).get("verified_by") or task.verified_by
            if task.verified_by in (None, "none_declared"):
                raise VerificationRequired(
                    "SUCCEEDED requires a named verifier. 'none_declared' is not a "
                    "verification strategy.")

        at = self._clock.now()
        prev, task.state, task.updated_at_hlc = task.state, to, at
        task.lease_epoch = self._epoch()
        if evidence:
            task.evidence_refs.append(evidence)
        self._persist(task, at)
        self._bus.publish("task.state_changed", subject=task.task_id,
                          payload={"task_id": task.task_id, "from": prev, "to": to,
                                   "verified_by": task.verified_by},
                          component="tasks", at=at)
        return task

    def _persist(self, task: Task, at: HLC) -> None:
        self._store.put_state(self.DOMAIN, self._key(task.task_id), task.to_dict(),
                              lease_epoch=self._epoch(), at=at)

    def get(self, task_id: str) -> Task | None:
        d = self._store.get_state(self.DOMAIN, self._key(task_id))
        return Task.from_dict(d) if d else None

    def all(self) -> list[Task]:
        """Every task in the domain.

        A row under the task prefix that will not parse is CORRUPTION and is
        raised, not skipped. Skipping it would turn a damaged task into a
        silently missing one -- and a task that vanishes is worse than a task
        that fails loudly, because nothing downstream knows to look for it.
        """
        out = []
        for k, b in self._store.list_state(self.DOMAIN):
            if not k.startswith(self.KEY_PREFIX):
                continue
            try:
                out.append(Task.from_dict(b))
            except (KeyError, ValueError) as e:
                raise ValueError(
                    f"corrupt task row at key {k!r}: {e}. Not skipped -- a task "
                    "that silently vanishes is worse than one that fails loudly."
                ) from e
        return out

    # ------------------------------------------------------------ checkpoint

    def checkpoint(self, task: Task, *, survival_carry: bool = False) -> str:
        """Write a restorable checkpoint. Returns its id.

        `outbox_cursor` is copied in deliberately: it is what resume replays
        from, and a checkpoint without it would restore a task that re-sends
        everything it already sent.
        """
        at = self._clock.now()
        cp_id = str(uuid.uuid4())
        body = {
            "checkpoint_id": cp_id,
            "schema_version": 1,
            "task_id": task.task_id,
            "written_at_hlc": at.to_dict(),
            "lease_epoch": self._epoch(),
            "goal": task.goal,
            "plan": task.plan,
            "completed_steps": list(task.completed_steps),
            "evidence_refs": list(task.evidence_refs),
            "grant_refs": [],  # references only; never secrets (schema note)
            "outbox_cursor": task.outbox_cursor or "",
            "resource_consumed": dict(task.resource_consumed),
            "survival_carry": survival_carry,
        }
        with self._lock:
            self._store.append("log", "task.checkpoint_written", body, at,
                               lease_epoch=self._epoch())
            task.checkpoint_ref = cp_id
            self._persist(task, at)
        self._bus.publish("task.checkpoint_written", subject=task.task_id,
                          payload={"task_id": task.task_id, "checkpoint_id": cp_id,
                                   "outbox_cursor": body["outbox_cursor"],
                                   "survival_carry": survival_carry},
                          component="tasks", at=at)
        return cp_id

    def latest_checkpoint(self, task_id: str) -> dict | None:
        best = None
        for rec in self._store.read("log", kind="task.checkpoint_written"):
            if rec.body.get("task_id") == task_id:
                best = rec.body  # HLC order, so the last match is the newest
        return best

    def restore(self, task_id: str) -> Task:
        """Restore from the newest checkpoint. The task re-enters RESUMABLE.

        NEVER into SUCCEEDED. REM-002's failure table is explicit: a restored
        task re-enters RESUMABLE, because a checkpoint records where the work
        got to, not that it was verified.
        """
        cp = self.latest_checkpoint(task_id)
        if cp is None:
            raise LookupError(f"no checkpoint for task {task_id}")
        cur = self.get(task_id)
        at = self._clock.now()
        t = Task(
            task_id=task_id, goal=cp["goal"], state="RESUMABLE",
            verification_criteria=(cur.verification_criteria if cur
                                   else {"kind": "none_declared"}),
            created_at_hlc=cur.created_at_hlc if cur else at,
            lease_epoch=self._epoch(),
            plan=cp.get("plan"), checkpoint_ref=cp["checkpoint_id"],
            outbox_cursor=cp.get("outbox_cursor") or None,
            completed_steps=list(cp.get("completed_steps") or []),
            evidence_refs=list(cp.get("evidence_refs") or []),
            priority_class=cur.priority_class if cur else "active_user_task",
            updated_at_hlc=at,
            resource_consumed=dict(cp.get("resource_consumed") or {}),
        )
        self._persist(t, at)
        self._bus.publish("task.restored", subject=task_id,
                          payload={"task_id": task_id,
                                   "checkpoint_id": cp["checkpoint_id"],
                                   "resumes_from_outbox_cursor": t.outbox_cursor,
                                   "state": "RESUMABLE"},
                          component="tasks", at=at)
        return t


class Outbox:
    """Durable record of external actions, so resume cannot re-send them.

    The cursor is a monotonic sequence over this node's intents. A resumed task
    replays from its cursor: anything at or before it has already been sent and
    is skipped, anything after it has not.
    """

    def __init__(self, store: StoreSet, clock: HybridLogicalClock, bus: EventBus,
                 leases: LeaseManager) -> None:
        self._store = store
        self._clock = clock
        self._bus = bus
        self._leases = leases
        self._lock = threading.RLock()

    def intent(self, task_id: str, action: str, args: dict, *,
               idempotency_key: str, level: str = "L1") -> str:
        """Record the intent to act BEFORE acting. Returns the cursor value."""
        at = self._clock.now()
        oid = str(uuid.uuid4())
        with self._lock:
            seq = self._store.append("log", "outbox.intent", {
                "outbox_id": oid, "task_id": task_id, "action": action,
                "args": args, "idempotency_key": idempotency_key,
                "level": level, "sent": False,
            }, at, lease_epoch=self._leases.epoch("tasks"))
        return f"{seq}:{oid}"

    def mark_sent(self, cursor: str, result: dict | None = None) -> None:
        at = self._clock.now()
        self._store.append("log", "outbox.sent", {
            "cursor": cursor, "result": result or {},
        }, at, lease_epoch=self._leases.epoch("tasks"))

    def already_sent(self, cursor: str) -> bool:
        for rec in self._store.read("log", kind="outbox.sent"):
            if rec.body.get("cursor") == cursor:
                return True
        return False

    def pending_after(self, task_id: str, cursor: str | None) -> list[dict]:
        """Intents strictly after the cursor. What a resume should replay."""
        floor = int(cursor.split(":", 1)[0]) if cursor else 0
        out = []
        for rec in self._store.read("log", kind="outbox.intent"):
            if rec.body.get("task_id") != task_id:
                continue
            if rec.seq <= floor:
                continue
            out.append({**rec.body, "cursor": f"{rec.seq}:{rec.body['outbox_id']}"})
        return out

    def send(self, task: Task, action: str, args: dict, *,
             idempotency_key: str, perform: Callable[[dict], dict],
             level: str = "L1") -> dict:
        """Intent -> perform -> mark sent, each step durable.

        Refuses outright if the node is partitioned and the action is L4+
        (INV-OWN-2). The refusal is the feature: a duplicated external send has
        no undo.
        """
        if not self._leases.external_action_permitted(level):
            raise PermissionError(
                f"external action {action!r} at {level} refused: partition suspected. "
                "INV-OWN-2 -- both sides of a partition would send it.")
        cursor = self.intent(task.task_id, action, args,
                             idempotency_key=idempotency_key, level=level)
        if self.already_sent(cursor):
            return {"skipped": True, "reason": "already sent", "cursor": cursor}
        result = perform(args)
        self.mark_sent(cursor, result)
        task.outbox_cursor = cursor
        return {"skipped": False, "result": result, "cursor": cursor}
