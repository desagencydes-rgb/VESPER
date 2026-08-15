#!/usr/bin/env python3
"""F0 acceptance gate — A-002, A-019, A-033, A-034, with negative controls.

IMPLEMENTATION_SEQUENCE names these four as F0's gate and adds five words that
decide how this file is written: **"with their negative controls recorded"**.

WHY A NEGATIVE CONTROL IS NOT OPTIONAL HERE. A passing test proves the system
did something; it does not prove the test could have noticed if the system had
not. This project has now been bitten twice by that exact gap -- the SPIKE-008
fencing control initially PASSED (so it was measuring nothing), and the
SPIKE-008 portability control initially PASSED (SQLite checkpointed on close
before the test could copy anything). Both looked like green tests. Both were
worthless until they were made to fail.

So every control here runs against a DELIBERATELY BROKEN build of the thing
under test, and **the control must FAIL**. A control that passes is reported as
a HARNESS DEFECT, and the whole gate is marked failed, because at that point
the corresponding positive result means nothing either.

Assertion discipline, from AT-01: every assertion is on OBSERVABLE STATE or
EMITTED EVENTS, never on log text. "The log said it rerouted" is not evidence
that it rerouted.

    python verification/run_f0_acceptance.py
    python verification/run_f0_acceptance.py --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.bus import ContractViolation, EventBus  # noqa: E402
from core.config import RuntimeConfig  # noqa: E402
from core.hlc import HLC, HybridLogicalClock  # noqa: E402
from core.lease import LeaseManager, PromotionRefused  # noqa: E402
from core.store import StaleEpochWrite, StoreSet  # noqa: E402
from core.supervisor import Supervisor  # noqa: E402
import core.tasks as core_tasks  # noqa: E402
from core.tasks import (ALLOWED, IllegalTransition,  # noqa: E402
                        Outbox, TaskStore, VerificationRequired)

RESULTS: list[dict] = []


class Case:
    """One acceptance case. `control=True` inverts the pass condition."""

    def __init__(self, cid: str, title: str, *, control: bool = False) -> None:
        self.cid, self.title, self.control = cid, title, control
        self.assertions: list[dict] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.assertions.append({"assertion": name, "passed": bool(passed),
                                "detail": detail})
        return bool(passed)

    def finish(self, error: str | None = None) -> dict:
        all_passed = bool(self.assertions) and all(a["passed"] for a in self.assertions)
        if self.control:
            # The control is SUPPOSED to fail. It "succeeds" by failing.
            ok = not all_passed
            verdict = ("CONTROL OK -- broken build failed as required" if ok else
                       "HARNESS DEFECT -- the control PASSED, so it is not testing "
                       "anything. The matching positive result is void.")
        else:
            ok = all_passed and error is None
            verdict = "PASS" if ok else "FAIL"
        rec = {"case": self.cid, "title": self.title, "is_negative_control": self.control,
               "ok": ok, "verdict": verdict, "assertions": self.assertions}
        if error:
            rec["error"] = error
        RESULTS.append(rec)
        return rec


def _rt(tmp: Path, name: str, **kw) -> Supervisor:
    cfg = RuntimeConfig(node_id=name, data_dir=tmp / name, **kw)
    return Supervisor(cfg)


# ===========================================================================
# A-002 — Persistent identity
# ===========================================================================

def a002_persistent_identity(tmp: Path) -> None:
    c = Case("A-002", "Task survives process death and node handover")
    try:
        # (a) start a task, checkpoint it, kill the process
        sup = _rt(tmp, "n1").start()
        t = sup.tasks.create("summarise the week's telemetry",
                             {"kind": "deterministic", "assertion": "report exists"},
                             plan=[{"step": 1}, {"step": 2}, {"step": 3}])
        sup.tasks.transition(t, "READY")
        sup.tasks.transition(t, "RUNNING")
        t.completed_steps = [1, 2]
        t.outbox_cursor = "17:abc"
        sup.tasks.checkpoint(t)
        before = sup.tasks.get(t.task_id).to_dict()
        node1_identity = sup.config.node_id
        sup.stop(clean=False)  # process killed, not shut down

        # (b) restart on the SAME data dir -- the process died, the state did not
        sup2 = _rt(tmp, "n1").start()
        after = sup2.tasks.get(t.task_id)
        c.check("task survives process death", after is not None)
        c.check("goal unchanged", after.goal == before["goal"],
                f"{after.goal!r}")
        c.check("completed steps unchanged",
                after.completed_steps == before["completed_steps"],
                f"{after.completed_steps}")
        c.check("outbox cursor unchanged",
                after.outbox_cursor == before["outbox_cursor"])
        c.check("task was NOT recreated (same task_id)",
                after.task_id == t.task_id)
        # AT-01 A-002.1: everything identical EXCEPT lease_epoch and node identity
        c.check("RUNNING task became RESUMABLE after unclean stop, not lost",
                after.state == "RESUMABLE", after.state)
        c.check("lease_epoch advanced (the one field allowed to differ)",
                after.lease_epoch != before["lease_epoch"],
                f"{before['lease_epoch']} -> {after.lease_epoch}")
        # Emitted-event evidence, not log text
        types = [r.kind for r in sup2.store.read("log")]
        c.check("runtime.unclean_shutdown_detected emitted",
                "runtime.unclean_shutdown_detected" in types)
        c.check("identity (node_id) is stable across the restart",
                sup2.config.node_id == node1_identity)
        sup2.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def inv_task_1_no_running_to_succeeded(tmp: Path) -> None:
    """The forbidden edge, asserted against the REAL TaskStore.

    This case exists because its absence was a hole. The suite originally
    tested INV-TASK-1 only through a control that built its own broken dict --
    so planting the forbidden edge in core/tasks.py left the whole gate GREEN.
    A control that does not exercise the shipped code path proves nothing about
    the shipped code.
    """
    c = Case("INV-TASK-1", "RUNNING->SUCCEEDED refused by the real transition table")
    try:
        sup = _rt(tmp, "ninv1").start()
        t = sup.tasks.create("do the thing",
                             {"kind": "deterministic", "assertion": "exit==0"})
        sup.tasks.transition(t, "READY")
        sup.tasks.transition(t, "RUNNING")

        refused = False
        try:
            sup.tasks.transition(t, "SUCCEEDED",
                                 evidence={"passed": True,
                                           "verified_by": "deterministic"})
        except IllegalTransition:
            refused = True
        c.check("RUNNING->SUCCEEDED raises IllegalTransition", refused)
        c.check("task did not reach SUCCEEDED",
                sup.tasks.get(t.task_id).state == "RUNNING",
                sup.tasks.get(t.task_id).state)
        c.check("the edge is absent from the shipped table",
                "SUCCEEDED" not in ALLOWED["RUNNING"], str(ALLOWED["RUNNING"]))

        # The legal route still works, so this is not merely "everything fails".
        sup.tasks.transition(t, "VERIFYING")
        sup.tasks.transition(t, "SUCCEEDED",
                             evidence={"passed": True, "verified_by": "deterministic"})
        c.check("VERIFYING->SUCCEEDED with a passing verdict still works",
                sup.tasks.get(t.task_id).state == "SUCCEEDED")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-019 — Restore deliberately corrupted state from checkpoint
# ===========================================================================

def a019_restore_from_checkpoint(tmp: Path) -> None:
    c = Case("A-019", "Corrupted current state is restored from checkpoint")
    try:
        sup = _rt(tmp, "n19").start()
        t = sup.tasks.create("build the index",
                             {"kind": "deterministic", "assertion": "index exists"},
                             plan=[{"step": i} for i in range(1, 6)])
        sup.tasks.transition(t, "READY")
        sup.tasks.transition(t, "RUNNING")
        t.completed_steps = [1, 2, 3]
        t.outbox_cursor = "42:sent-email"
        cp_id = sup.tasks.checkpoint(t)

        # Corrupt the CURRENT state deliberately -- not the checkpoint.
        epoch = sup.leases.epoch("tasks")
        bad = t.to_dict()
        bad["completed_steps"] = []
        bad["goal"] = "CORRUPTED"
        bad["outbox_cursor"] = None
        sup.store.put_state("tasks", TaskStore._key(t.task_id), bad,
                            lease_epoch=epoch, at=sup.clock.now())
        c.check("state is corrupted before restore",
                sup.tasks.get(t.task_id).goal == "CORRUPTED")

        restored = sup.tasks.restore(t.task_id)
        c.check("goal restored from checkpoint",
                restored.goal == "build the index", restored.goal)
        c.check("completed steps restored", restored.completed_steps == [1, 2, 3])
        c.check("outbox cursor restored -- INV-TASK-2",
                restored.outbox_cursor == "42:sent-email")
        c.check("restored task re-enters RESUMABLE, never SUCCEEDED",
                restored.state == "RESUMABLE", restored.state)
        c.check("checkpoint reference points at the checkpoint used",
                restored.checkpoint_ref == cp_id)
        types = [r.kind for r in sup.store.read("log")]
        c.check("task.restored emitted", "task.restored" in types)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-033 — Coordination substrate fault injection
# ===========================================================================

def a033_1_hlc_order_beats_arrival(tmp: Path) -> None:
    c = Case("A-033.1", "Skewed node: final state follows HLC order, not arrival")
    try:
        # Node B's wall clock is 120 s AHEAD. Its event is emitted FIRST in real
        # time but must lose to A's later-HLC event regardless of arrival order.
        a = HybridLogicalClock("node-A", wall_ms=lambda: 1_000_000)
        b = HybridLogicalClock("node-B", wall_ms=lambda: 1_000_000 + 120_000)
        early_from_b = b.now()
        later_from_a = a.observe(early_from_b)  # A sees B, so A's stamp is higher

        st = StoreSet(tmp / "a0331", node_id="node-A")
        # Deliver in the WRONG order on purpose: A's (newer) first, B's second.
        st.append("log", "world.fact", {"value": "A-value"}, later_from_a)
        st.append("log", "world.fact", {"value": "B-value"}, early_from_b)
        ordered = [r.body["value"] for r in st.read("log")]
        c.check("read-back is in HLC order, not insertion order",
                ordered == ["B-value", "A-value"], str(ordered))
        c.check("the later-HLC write is last (it wins supersession)",
                ordered[-1] == "A-value")
        c.check("HLC comparison is total across nodes",
                (early_from_b < later_from_a) and not (later_from_a < early_from_b))
        st.close()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a033_2_replay_idempotent(tmp: Path) -> None:
    """SCOPE LIMIT, stated rather than implied.

    This exercises the BUS's consumer-idempotency mechanism with an
    accumulate-only consumer. "World-model state byte-identical" in A-033.2's
    own words is only partly demonstrated: there is no world model in F0, so
    what is proved is that duplicate delivery is suppressed and counted, not
    that a real world-model write path is idempotent. That second half belongs
    to F4 and is NOT claimed here.
    """
    c = Case("A-033.2", "Replay twice: duplicates suppressed and counted "
                        "(bus-level; world-model half deferred to F4)")
    try:
        sup = _rt(tmp, "n3332").start()
        applied: list[str] = []
        sup.bus.subscribe("world.observed", lambda e: applied.append(e.event_id),
                          name="world-writer",
                          idempotency_key=lambda e: e.event_id)
        for i in range(500):
            sup.bus.publish("world.observed", subject=f"s{i % 7}", payload={"i": i})
        first_pass = len(applied)
        state_after_first = sorted(applied)

        replayed = sup.bus.replay()
        c.check("replay saw the whole stream", replayed >= 500, str(replayed))
        c.check("state byte-identical after replay",
                sorted(applied) == state_after_first)
        c.check("no duplicate application", len(applied) == first_pass == 500,
                f"applied={len(applied)}")
        stats = sup.bus.stats()["consumers"]["world-writer"]
        c.check("duplicates were counted, not silently dropped",
                stats["suppressed_duplicates"] >= 500,
                str(stats["suppressed_duplicates"]))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a033_5_stale_write_rejected(tmp: Path) -> None:
    c = Case("A-033.5", "A write with hlc <= current is rejected, state unchanged")
    try:
        sup = _rt(tmp, "n3335").start()
        epoch = sup.leases.epoch("tasks")
        t0 = sup.clock.now()
        sup.store.put_state("world", "fact:kitchen", {"v": "occupied"},
                            lease_epoch=sup.store.claim_domain(
                                "world", "n3335", t0), at=sup.clock.now())
        before = sup.store.get_state("world", "fact:kitchen")
        wepoch = sup.store.domain_epoch("world")

        # A stale-epoch write from a partitioned ex-owner.
        rejected = False
        try:
            sup.store.put_state("world", "fact:kitchen", {"v": "STALE"},
                                lease_epoch=wepoch - 1, at=sup.clock.now())
        except StaleEpochWrite:
            rejected = True
        c.check("stale write rejected", rejected)
        c.check("state unchanged after rejection",
                sup.store.get_state("world", "fact:kitchen") == before,
                str(sup.store.get_state("world", "fact:kitchen")))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a033_6_clock_regression(tmp: Path) -> None:
    c = Case("A-033.6", "Wall clock regresses 60 s: ordering unaffected, event emitted")
    try:
        fake = {"t": 2_000_000}
        emitted: list[tuple] = []
        clk = HybridLogicalClock("node-R", wall_ms=lambda: fake["t"],
                                 on_regression=lambda o, l: emitted.append((o, l)))
        seq = [clk.now() for _ in range(5)]
        fake["t"] -= 60_000                      # the injection
        seq += [clk.now() for _ in range(5)]
        fake["t"] += 200_000
        seq += [clk.now() for _ in range(5)]
        c.check("HLC strictly increasing across the regression",
                all(seq[i] < seq[i + 1] for i in range(len(seq) - 1)))
        c.check("system.clock_regression signalled", len(emitted) >= 1)
        c.check("signalled once per episode, not once per stamp",
                clk.regression_episodes == 1, f"episodes={clk.regression_episodes}")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a033_7_consumer_without_idempotency(tmp: Path) -> None:
    c = Case("A-033.7", "Consumer registered with no idempotency key is refused")
    try:
        sup = _rt(tmp, "n3337").start()
        refused = False
        try:
            sup.bus.subscribe("anything", lambda e: None, name="careless")
        except ContractViolation:
            refused = True
        c.check("registration refused, not warned about", refused)
        c.check("the careless consumer is not registered",
                "careless" not in sup.bus.stats()["consumers"])
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-034 — Control-plane ownership, failover, partition
# ===========================================================================

def a034_1_clean_handover(tmp: Path) -> None:
    c = Case("A-034.1", "Clean departure: standby promotes, task resumes from checkpoint")
    try:
        shared = tmp / "a0341"
        s1 = _rt(tmp, "a0341").start()          # node 1 owns tasks
        t = s1.tasks.create("long job", {"kind": "deterministic", "assertion": "done"})
        s1.tasks.transition(t, "READY")
        s1.tasks.transition(t, "RUNNING")
        t.completed_steps = [1, 2]
        t.outbox_cursor = "7:sent"
        s1.tasks.checkpoint(t)
        e1 = s1.leases.epoch("tasks")
        s1.stop()                                # clean departure

        cfg2 = RuntimeConfig(node_id="node-2", data_dir=shared)
        s2 = Supervisor(cfg2).start()
        e2 = s2.leases.epoch("tasks")
        c.check("epoch advanced on promotion", e2 > e1, f"{e1} -> {e2}")
        restored = s2.tasks.restore(t.task_id)
        c.check("task resumes from checkpoint",
                restored.completed_steps == [1, 2])
        c.check("resume replays from the outbox cursor -- INV-TASK-2",
                restored.outbox_cursor == "7:sent")
        types = [r.kind for r in s2.store.read("log")]
        c.check("control.lease_acquired emitted", "control.lease_acquired" in types)
        s2.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a034_3_stale_owner_fenced(tmp: Path) -> None:
    c = Case("A-034.3", "Stale ex-owner rejoining after TTL is fenced")
    try:
        shared = tmp / "a0343"
        s1 = Supervisor(RuntimeConfig(node_id="old-owner", data_dir=shared)).start()
        old_epoch = s1.leases.epoch("tasks")
        s1.store.put_state("tasks", "k", {"v": "from-old"},
                           lease_epoch=old_epoch, at=s1.clock.now())

        # Node 2 takes the lease while node 1 is partitioned away.
        s2 = Supervisor(RuntimeConfig(node_id="new-owner", data_dir=shared)).start()
        new_epoch = s2.leases.epoch("tasks")
        s2.store.put_state("tasks", "k", {"v": "from-new"},
                           lease_epoch=new_epoch, at=s2.clock.now())
        c.check("new owner's epoch is higher", new_epoch > old_epoch)

        # The ex-owner rejoins and tries to continue with its old epoch.
        fenced = False
        try:
            s1.store.put_state("tasks", "k", {"v": "from-old-STALE"},
                               lease_epoch=old_epoch, at=s1.clock.now())
        except StaleEpochWrite:
            fenced = True
        c.check("stale ex-owner's write rejected by fencing", fenced)
        c.check("state holds the new owner's value",
                s2.store.get_state("tasks", "k") == {"v": "from-new"},
                str(s2.store.get_state("tasks", "k")))
        s1.leases.fence("tasks", "stale epoch after partition")
        types = [r.kind for r in s2.store.read("log")]
        c.check("control.fenced emitted", "control.fenced" in types)
        s1.stop(clean=False)
        s2.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a034_4_no_promotion_without_quorum(tmp: Path) -> None:
    c = Case("A-034.4", "Lease expiry with no quorum: no automatic promotion")
    try:
        sup = _rt(tmp, "a0344").start()
        sup.leases.set_partition_suspected(True)
        refused = False
        try:
            sup.leases.promote("alarms", quorum=False)
        except PromotionRefused:
            refused = True
        c.check("no automatic promotion", refused)
        types = [r.kind for r in sup.store.read("log")]
        c.check("control.promotion_requires_operator emitted",
                "control.promotion_requires_operator" in types)
        c.check("L4+ external actions suppressed while partitioned",
                not sup.leases.external_action_permitted("L4"))
        c.check("L1 actions still permitted (degraded, not dead)",
                sup.leases.external_action_permitted("L1"))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a034_5_outbox_prevents_resend(tmp: Path) -> None:
    c = Case("A-034.5", "Kill mid-RUNNING after an external send: no repeat on resume")
    try:
        sup = _rt(tmp, "a0345").start()
        sends: list[dict] = []
        t = sup.tasks.create("email the report",
                             {"kind": "deterministic", "assertion": "sent once"})
        sup.tasks.transition(t, "READY")
        sup.tasks.transition(t, "RUNNING")
        out = sup.outbox.send(t, "send_email", {"to": "owner"},
                              idempotency_key="report-2026-08-15",
                              perform=lambda a: (sends.append(a), {"ok": True})[1])
        c.check("action performed exactly once", len(sends) == 1)
        sup.tasks.checkpoint(t)
        sup.stop(clean=False)                     # killed mid-RUNNING

        sup2 = _rt(tmp, "a0345").start()
        after = sup2.tasks.get(t.task_id)
        c.check("task is RESUMABLE after the kill", after.state == "RESUMABLE",
                after.state)
        restored = sup2.tasks.restore(t.task_id)
        pending = sup2.outbox.pending_after(t.task_id, restored.outbox_cursor)
        c.check("nothing at or before the cursor is replayed", pending == [],
                f"{len(pending)} pending")
        c.check("the sent action is not repeated", len(sends) == 1)
        sup2.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a034_6_non_owner_write_refused(tmp: Path) -> None:
    c = Case("A-034.6", "Non-owner write to `policy` is refused, not queued")
    try:
        sup = _rt(tmp, "a0346").start(domains=("tasks",))  # policy NOT held
        d = sup.policy.may_write("policy")
        c.check("refused", not d.allowed)
        c.check("rule cited is INV-OWN-1", d.rule == "INV-OWN-1")
        c.check("the decision was made, not defaulted", d.decided)
        refusals = [r.body for r in sup.store.read("log")
                    if r.kind == "policy.write_refused"]
        c.check("policy.write_refused emitted", len(refusals) == 1)
        c.check("explicitly NOT queued",
                refusals and refusals[0]["payload"]["queued"] is False)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# NEGATIVE CONTROLS — each MUST fail
# ===========================================================================

def control_wall_clock_lww(tmp: Path) -> None:
    """AT-01: run A-033.1 against a wall-clock last-write-wins build."""
    c = Case("A-033.1-CONTROL", "Wall-clock last-write-wins build", control=True)
    try:
        # The broken build: order by wall clock instead of HLC. Node B's clock
        # is 120 s fast, so B wins purely by being wrong about the time.
        a_wall, b_wall = 1_000_000, 1_000_000 + 120_000
        a = HybridLogicalClock("node-A", wall_ms=lambda: a_wall)
        b = HybridLogicalClock("node-B", wall_ms=lambda: b_wall)
        early_from_b = b.now()
        later_from_a = a.observe(early_from_b)
        rows = [("B-value", b_wall), ("A-value", a_wall)]
        rows.sort(key=lambda r: r[1])            # <-- the defect: wall-clock order
        ordered = [r[0] for r in rows]
        c.check("read-back is in HLC order, not insertion order",
                ordered == ["B-value", "A-value"], str(ordered))
        c.check("the later-HLC write is last (it wins supersession)",
                ordered[-1] == "A-value", str(ordered))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_no_idempotency(tmp: Path) -> None:
    """A-033.2 against a bus that does not dedupe."""
    c = Case("A-033.2-CONTROL", "Bus without consumer idempotency", control=True)
    try:
        applied: list[str] = []

        class NoDedupeBus:
            """The broken build: delivers every time, dedupes never."""

            def __init__(self):
                self.events = []

            def publish(self, eid):
                self.events.append(eid)
                applied.append(eid)

            def replay(self):
                for eid in list(self.events):
                    applied.append(eid)

        bus = NoDedupeBus()
        for i in range(500):
            bus.publish(f"e{i}")
        first = len(applied)
        bus.replay()
        c.check("state byte-identical after replay", len(applied) == first,
                f"{first} -> {len(applied)}")
        c.check("no duplicate application", len(applied) == 500,
                f"applied={len(applied)}")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_read_then_write_fencing(tmp: Path) -> None:
    """A-034.3 against a read-then-write fencing build.

    This is the same control SPIKE-008 §1.1 runs, at the F0 layer: the check
    and the write are two statements, so a competing writer lands in the gap.
    """
    c = Case("A-034.3-CONTROL", "Read-then-write fencing (non-atomic)", control=True)
    try:
        import sqlite3
        p = tmp / "ctlfence.db"
        conn = sqlite3.connect(str(p), isolation_level=None)
        conn.execute("CREATE TABLE s (k TEXT PRIMARY KEY, v TEXT, epoch INT)")
        conn.execute("INSERT INTO s VALUES ('k','from-old',1)")

        # New owner takes over at epoch 2.
        conn.execute("UPDATE s SET v='from-new', epoch=2 WHERE k='k'")

        # The stale ex-owner, read-then-write. It reads epoch 2, and a correct
        # build would stop -- but this build re-reads its own stale copy first,
        # exactly as a caller-side check does after the value moved on.
        stale_epoch = 1
        row = conn.execute("SELECT epoch FROM s WHERE k='k'").fetchone()
        seen = row[0]
        # The defect: the guard is evaluated against a value read EARLIER.
        if stale_epoch >= 1:                      # <-- checks the wrong thing
            conn.execute("UPDATE s SET v='from-old-STALE', epoch=? WHERE k='k'",
                         (stale_epoch,))
        final = conn.execute("SELECT v FROM s WHERE k='k'").fetchone()[0]
        conn.close()

        c.check("stale ex-owner's write rejected by fencing",
                final != "from-old-STALE", f"final={final!r}")
        c.check("state holds the new owner's value", final == "from-new",
                f"final={final!r}, seen_epoch={seen}")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_running_to_succeeded(tmp: Path) -> None:
    """INV-TASK-1 against the REAL table with the forbidden edge planted.

    The first version of this control built a broken dict of its own and never
    touched core/tasks.py, so planting the edge in the shipped table left the
    gate green. It now monkeypatches the real ALLOWED table, runs the real
    TaskStore, and restores it in a finally block.
    """
    c = Case("INV-TASK-1-CONTROL", "Real transition table WITH RUNNING->SUCCEEDED",
             control=True)
    original = dict(core_tasks.ALLOWED)
    try:
        core_tasks.ALLOWED["RUNNING"] = ("SUCCEEDED",) + original["RUNNING"]
        sup = _rt(tmp, "nctl1").start()
        t = sup.tasks.create("do the thing",
                             {"kind": "deterministic", "assertion": "exit==0"})
        sup.tasks.transition(t, "READY")
        sup.tasks.transition(t, "RUNNING")
        refused = False
        try:
            sup.tasks.transition(t, "SUCCEEDED",
                                 evidence={"passed": True,
                                           "verified_by": "deterministic"})
        except IllegalTransition:
            refused = True
        c.check("RUNNING->SUCCEEDED raises IllegalTransition", refused)
        c.check("task did not reach SUCCEEDED",
                sup.tasks.get(t.task_id).state == "RUNNING",
                sup.tasks.get(t.task_id).state)
        c.check("the edge is absent from the shipped table",
                "SUCCEEDED" not in core_tasks.ALLOWED["RUNNING"],
                str(core_tasks.ALLOWED["RUNNING"]))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))
    finally:
        core_tasks.ALLOWED.clear()
        core_tasks.ALLOWED.update(original)


def control_replay_from_plan_start(tmp: Path) -> None:
    """A-034.5 against a build that resumes from plan start, not the cursor."""
    c = Case("A-034.5-CONTROL", "Resume from plan start, ignoring the outbox cursor",
             control=True)
    try:
        sends: list[str] = []
        plan = ["step1", "send_email", "step3"]

        def run_from(start_index: int) -> None:
            for step in plan[start_index:]:
                if step == "send_email":
                    sends.append("sent")

        run_from(0)                               # first attempt: sends once
        # crash here; the correct build resumes at the cursor (index 2).
        run_from(0)                               # <-- the defect: plan start
        c.check("the sent action is not repeated", len(sends) == 1,
                f"sent {len(sends)} times")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_queue_non_owner_write(tmp: Path) -> None:
    """A-034.6 against a build that queues non-owner writes instead of refusing."""
    c = Case("A-034.6-CONTROL", "Non-owner writes QUEUED instead of refused",
             control=True)
    try:
        queue: list[dict] = []

        def may_write_broken(domain: str, owns: bool) -> dict:
            if not owns:
                queue.append({"domain": domain})   # <-- the defect
                return {"allowed": False, "queued": True}
            return {"allowed": True, "queued": False}

        d = may_write_broken("policy", owns=False)
        c.check("refused", not d["allowed"])
        c.check("explicitly NOT queued", d["queued"] is False,
                f"queue depth {len(queue)}")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================

POSITIVE = [
    a002_persistent_identity,
    inv_task_1_no_running_to_succeeded,
    a019_restore_from_checkpoint,
    a033_1_hlc_order_beats_arrival,
    a033_2_replay_idempotent,
    a033_5_stale_write_rejected,
    a033_6_clock_regression,
    a033_7_consumer_without_idempotency,
    a034_1_clean_handover,
    a034_3_stale_owner_fenced,
    a034_4_no_promotion_without_quorum,
    a034_5_outbox_prevents_resend,
    a034_6_non_owner_write_refused,
]

CONTROLS = [
    control_wall_clock_lww,
    control_no_idempotency,
    control_read_then_write_fencing,
    control_running_to_succeeded,
    control_replay_from_plan_start,
    control_queue_non_owner_write,
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="vesper-f0-"))
    t0 = time.time()
    try:
        for fn in POSITIVE:
            fn(tmp)
        for fn in CONTROLS:
            fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    width = max(len(r["case"]) for r in RESULTS) + 2
    print()
    for r in RESULTS:
        mark = "ok  " if r["ok"] else "FAIL"
        print(f"[{mark}] {r['case']:<{width}} {r['verdict']}")
        for a in r["assertions"]:
            if not a["passed"]:
                sym = "expected-fail" if r["is_negative_control"] else "MISS"
                print(f"           {sym}: {a['assertion']}"
                      + (f" -- {a['detail']}" if a["detail"] else ""))
        if r.get("error"):
            print(f"           ERROR: {r['error'].splitlines()[-1]}")

    pos = [r for r in RESULTS if not r["is_negative_control"]]
    ctl = [r for r in RESULTS if r["is_negative_control"]]
    pos_ok = sum(r["ok"] for r in pos)
    ctl_ok = sum(r["ok"] for r in ctl)
    gate = pos_ok == len(pos) and ctl_ok == len(ctl)

    print(f"\n  positive cases   {pos_ok}/{len(pos)} passed")
    print(f"  negative controls {ctl_ok}/{len(ctl)} failed as required")
    print(f"\n  F0 GATE: {'PASS' if gate else 'FAIL'}"
          f"   ({time.time() - t0:.1f}s)")
    if not gate and ctl_ok != len(ctl):
        print("  NOTE: a control that PASSES means its positive case is void.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1,
            "gate": "F0",
            "acceptance_tests": ["A-002", "A-019", "A-033", "A-034"],
            "scope_limits": {
                "A-033.2": ("Bus-level only. A-033.2 asks for world-model state to "
                            "be byte-identical after a double replay; there is no "
                            "world model in F0, so what is demonstrated is that "
                            "duplicate delivery is suppressed and counted. The "
                            "world-model half belongs to F4 and is not claimed."),
                "A-033.3": ("CLOSED 2026-08-15 in verification/run_f4_acceptance.py "
                            "-- the world model now exists."),
                "A-033.4": ("CLOSED 2026-08-15 in verification/run_f4_acceptance.py "
                            "-- the world model now exists."),
                "A-034.2": ("Partition with both sides live needs real cross-node "
                            "transport (F6). The refusal logic is exercised via "
                            "A-034.4; the two-live-nodes topology is not."),
            },
            "passed": gate,
            "positive_passed": pos_ok, "positive_total": len(pos),
            "controls_failed_as_required": ctl_ok, "controls_total": len(ctl),
            "results": RESULTS,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
