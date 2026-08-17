"""VESPER F0 — the persistent runtime.

Increment 1 of the Foundation sequence: runtime supervisor, config, telemetry,
event bus, durable task state, checkpoints, persistence abstraction and policy
skeleton. Gated by A-002, A-019, A-033 and A-034 passing WITH their negative
controls recorded — not by the code running.

Module order below is dependency order, and it is also reading order:

    hlc         the total order. Nothing else may compare timestamps.
    store       five physical stores, epoch fencing, append-only guards.
    bus         typed envelopes, mandatory consumer idempotency.
    lease       ownership, fencing tokens, the refusal to self-promote.
    tasks       durable task state, checkpoints, the outbox.
    telemetry   write-time redaction, budget accounting.
    policy      named decision points with a deny default.
    config      measured-vs-declared provenance.
    supervisor  assembles and owns the lifecycle.
"""

from .bus import ContractViolation, Event, EventBus
from .config import NotMeasured, RuntimeConfig
from .hlc import HLC, ClockRegression, HybridLogicalClock
from .lease import LeaseManager, NotOwner, PromotionRefused
from .policy import Decision, PolicySkeleton
from .store import AppendOnlyViolation, StaleEpochWrite, StoreSet
from .supervisor import Supervisor
from .tasks import IllegalTransition, Outbox, Task, TaskStore, VerificationRequired
from .telemetry import Telemetry

__all__ = [
    "HLC", "HybridLogicalClock", "ClockRegression",
    "StoreSet", "StaleEpochWrite", "AppendOnlyViolation",
    "EventBus", "Event", "ContractViolation",
    "LeaseManager", "NotOwner", "PromotionRefused",
    "TaskStore", "Task", "Outbox", "IllegalTransition", "VerificationRequired",
    "Telemetry", "PolicySkeleton", "Decision",
    "RuntimeConfig", "NotMeasured", "Supervisor",
]
