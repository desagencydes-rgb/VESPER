"""Runtime supervisor — the process that stays alive and owns the lifecycle.

WHAT F0 IS FOR. Everything above this layer assumes a runtime that is already
running, already holds its leases, and already knows what it was doing before
it was last killed. This assembles that: clock, stores, bus, leases, tasks,
telemetry, policy — wired in dependency order, started, heartbeated, and shut
down in a way that leaves the stores restorable.

SHUTDOWN IS THE PART THAT MATTERS. A supervisor that starts cleanly and exits
by dying is only half a supervisor, because the state left behind is what the
next start has to work from. On `stop()`: demote leases, checkpoint the WAL so
every store is a self-contained portable artifact (ADR-002 D10), and record
that the shutdown was clean. An unclean shutdown is then detectable on the next
start rather than inferred.

THE HEARTBEAT DOES NOT PRETEND TO BE A SCHEDULER. It expires leases past TTL
and nothing else. Autonomy, triggers and the anti-chatbot property are F5's
concern, and building a scheduler here would quietly create the thing the
architecture spends its effort avoiding: a system whose only reason to act is
that time passed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .bus import EventBus
from .config import RuntimeConfig
from .hlc import HybridLogicalClock
from .lease import LeaseManager
from .policy import PolicySkeleton
from .store import StoreSet
from .tasks import Outbox, TaskStore
from .telemetry import Telemetry

CLEAN_SHUTDOWN_KEY = "runtime.clean_shutdown"


class Supervisor:
    """Owns every long-lived object in the runtime."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at_wall: float | None = None

        # Dependency order. The clock is first because everything else stamps
        # with it; the store is second because the bus's first act is a durable
        # append. The regression callback is wired after the bus exists, since
        # the clock must not depend on the bus (that would be a cycle).
        self.clock = HybridLogicalClock(
            config.node_id, max_regression_ms=config.max_clock_regression_ms)
        self.store = StoreSet(config.data_dir, node_id=config.node_id)
        self.bus = EventBus(self.clock, self.store, component="supervisor")
        self.telemetry = Telemetry(self.store, self.clock)
        self.leases = LeaseManager(self.store, self.clock, self.bus,
                                   node_id=config.node_id,
                                   ttl_ms=config.lease_ttl_ms)
        self.tasks = TaskStore(self.store, self.clock, self.bus, self.leases)
        self.outbox = Outbox(self.store, self.clock, self.bus, self.leases)
        self.policy = PolicySkeleton(self.bus, self.leases)

        self.clock._on_regression = self._on_clock_regression  # noqa: SLF001
        self.telemetry.declare_budget("checkpoint_commit",
                                      config.checkpoint_budget_ms)

    # ----------------------------------------------------------------- start

    def start(self, *, domains: tuple[str, ...] = ("tasks",)) -> "Supervisor":
        unclean = self._detect_unclean_shutdown()
        self.started_at_wall = time.time()

        self.bus.publish("runtime.started", subject=self.config.node_id,
                         payload={"node_id": self.config.node_id,
                                  "trust_zone": self.config.trust_zone,
                                  "data_dir": str(self.config.data_dir),
                                  "previous_shutdown_was_clean": not unclean},
                         component="supervisor")
        if unclean:
            # Stated as an event, not a log line. A-002 and A-034 assert on
            # observable state and emitted events; "the log said so" is not
            # evidence that anything happened.
            self.bus.publish("runtime.unclean_shutdown_detected",
                             subject=self.config.node_id,
                             payload={"note": ("previous run did not record a clean "
                                               "shutdown; tasks left RUNNING are "
                                               "candidates for RESUMABLE")},
                             component="supervisor")
            self._mark_running_tasks_resumable(domains)

        self._store_clean_flag(False)
        for d in domains:
            self.leases.acquire(d)

        self._thread = threading.Thread(target=self._heartbeat, daemon=True,
                                        name="vesper-heartbeat")
        self._thread.start()
        return self

    def _detect_unclean_shutdown(self) -> bool:
        flag = self.store.get_meta(CLEAN_SHUTDOWN_KEY)
        if flag is None:
            return False  # first ever start; not unclean, just new
        return not flag.get("clean", False)

    def _store_clean_flag(self, clean: bool) -> None:
        # runtime_meta, NOT domain state: this flag is not a task, is not
        # fenced by a task epoch, and has to stay writable during shutdown
        # while leases are being released.
        self.store.put_meta(CLEAN_SHUTDOWN_KEY, {"clean": clean})

    def _mark_running_tasks_resumable(self, domains: tuple[str, ...]) -> None:
        if "tasks" not in domains:
            return
        epoch = self.store.claim_domain("tasks", self.config.node_id, self.clock.now())
        for t in self.tasks.all():
            if t.state in ("RUNNING", "WAITING"):
                at = self.clock.now()
                t.state = "RESUMABLE"
                t.updated_at_hlc = at
                t.lease_epoch = epoch
                self.store.put_state("tasks", TaskStore._key(t.task_id),
                                     t.to_dict(), lease_epoch=epoch, at=at)
                self.bus.publish("task.state_changed", subject=t.task_id,
                                 payload={"task_id": t.task_id, "from": "RUNNING",
                                          "to": "RESUMABLE",
                                          "reason": "unclean shutdown detected"},
                                 component="supervisor", at=at)
        self.store.release_domain("tasks", self.clock.now())

    # ------------------------------------------------------------- heartbeat

    def _heartbeat(self) -> None:
        interval = self.config.heartbeat_ms / 1000.0
        while not self._stopping.wait(interval):
            try:
                self.leases.tick()
                for d in list(self.leases.held_domains()):
                    self.leases.renew(d)
            except Exception as e:  # noqa: BLE001
                self.telemetry.record("runtime.heartbeat_error",
                                      {"error": f"{type(e).__name__}: {e}"})

    def _on_clock_regression(self, observed_ms: int, last_ms: int) -> None:
        self.bus.publish("system.clock_regression", subject=self.config.node_id,
                         payload={"observed_ms": observed_ms, "last_ms": last_ms,
                                  "delta_ms": last_ms - observed_ms,
                                  "hlc_ordering_affected": False,
                                  "wall_clock_policy": "clock_suspect"},
                         component="clock")

    # ------------------------------------------------------------------ stop

    def stop(self, *, clean: bool = True) -> dict:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

        summary: dict[str, Any] = {"clean": clean}
        try:
            if clean:
                for d in list(self.leases.held_domains()):
                    self.leases.release(d)
                self._store_clean_flag(True)
                self.bus.publish("runtime.stopped", subject=self.config.node_id,
                                 payload={"clean": True}, component="supervisor")
            # Always checkpoint, clean or not: a store left with an
            # uncheckpointed WAL is one whose tail a naive copy would lose.
            summary["wal_checkpoint"] = self.store.checkpoint_wal()
            summary["integrity"] = self.store.integrity()
        finally:
            self.store.close()
        return summary

    def __enter__(self) -> "Supervisor":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop(clean=not any(exc))

    # ------------------------------------------------------------------ view

    def status(self) -> dict:
        return {
            "node_id": self.config.node_id,
            "held_domains": self.leases.held_domains(),
            "partition_suspected": self.leases.partition_suspected,
            "bus": self.bus.stats(),
            "budgets": self.telemetry.budgets(),
            "hlc": str(self.clock.peek()),
            "clock_regression_episodes": self.clock.regression_episodes,
        }
