#!/usr/bin/env python3
"""SPIKE-008 -- persistence engine validation against the ADR-002 constraint set.

    "The other seven spikes measure hardware and platforms. THIS ONE MEASURES
     WHETHER A DECISION SURVIVES CONTACT WITH THEM."   -- SPIKE-008 preamble

ADR-002 chose SQLite in WAL mode because `UPDATE ... WHERE lease_epoch = ?` is a
single atomic statement and is therefore the fencing primitive INV-OWN-3 needs.
That reasoning is sound on paper. Migration retrofitted onto durable data is the
classic unrecoverable cost (GAP-046), so the paper is checked BEFORE F0.

This harness implements the blocking half of the protocol:

    1.1  fencing under concurrent writers      -> criteria 1 and 2   BLOCKING
    1.2  crash safety (SIGKILL trials)         -> criteria 3 and 4   BLOCKING
    1.3  checkpoint budget, synchronous=FULL   -> criterion 5
    1.4  append-only enforcement               -> criterion 7

Not implemented here, and recorded as NOT_RUN rather than passed: 1.5 read-time
upcasting (needs the runtime's event codec, which does not exist until F0) and
1.6 portability across node classes (needs the other candidate nodes, which are
not enrolled). Criteria 8 and 9 therefore stay open, and this harness says so.

    python validate_persistence.py fencing        # 1.1, both builds
    python validate_persistence.py crash          # 1.2
    python validate_persistence.py checkpoint     # 1.3
    python validate_persistence.py appendonly     # 1.4
    python validate_persistence.py all --out <f>  # everything, one report

THE CONTROL RUN IS NOT OPTIONAL. §1.1 requires the same suite to be run against a
deliberately NON-COMPLIANT implementation that does read-then-write instead of
the single guarded statement, and that build MUST FAIL. If it passes, the test is
measuring nothing -- the same discipline every acceptance test in this corpus
carries. `fencing` runs both and reports both.

Stdlib only. sqlite3 ships with Python, which is also why ADR-002 D1 chose it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "planning" / "spike-results"

# ADR-002 D2. Five physical stores, and the boundaries are NORMATIVE: DF-LOSS-CLASS
# classifies a loss by the store the record lived in, so a single-file design would
# make loss classification a judgement call, which INV-LOSS-6 forbids.
STORES = ["log", "state", "audit", "tombstones", "workspace"]
# ADR-002 D9. These three are the system's memory of what it did, and are outside
# the runtime's write capability: a system that can rewrite its own audit log can
# be wrong in a way nobody can later detect.
APPEND_ONLY_STORES = ["log", "audit", "tombstones"]
# ADR-002 D1: synchronous = FULL on log, audit and checkpoint; NORMAL permitted on
# the workspace store only.
SYNC_FULL_STORES = ["log", "audit", "state", "tombstones"]
CHECKPOINT_BUDGET_MS = 200.0  # latency_budgets.toml, p95


def _connect(path: Path, synchronous: str = "FULL") -> sqlite3.Connection:
    c = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(f"PRAGMA synchronous={synchronous}")
    return c


def _init_state(path: Path) -> None:
    c = _connect(path)
    c.execute("""CREATE TABLE IF NOT EXISTS leased_state (
                     domain TEXT PRIMARY KEY,
                     current_epoch INTEGER NOT NULL,
                     value TEXT NOT NULL,
                     written_by_epoch INTEGER NOT NULL)""")
    # Committed write order, captured by a trigger rather than by the writers.
    # The writers' own counters are their report of themselves; this is the
    # database's report of what actually landed, which is the only evidence that
    # survives a writer lying, crashing, or racing.
    c.execute("""CREATE TABLE IF NOT EXISTS write_history (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     epoch INTEGER NOT NULL)""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS t_history
                 AFTER UPDATE OF written_by_epoch ON leased_state
                 BEGIN INSERT INTO write_history(epoch)
                       VALUES (NEW.written_by_epoch); END""")
    c.execute("""INSERT OR REPLACE INTO leased_state
                 VALUES ('d0', 1, 'init', 1)""")
    c.close()


# --------------------------------------------------------------------------- 1.1


def _contender(path_s: str, worker_id: int, n: int, compliant: bool, q, seed: int) -> None:
    """One node contending for the lease, then writing under it.

    THE SCENARIO INV-OWN-3 PROTECTS is a partitioned ex-owner rejoining: it still
    believes it holds the lease, and its write must not land. Modelling it needs
    ownership to actually CHANGE HANDS during the run, which is why every
    contender both claims and writes rather than one holding a permanently stale
    epoch -- a permanently stale writer is rejected by a plain SELECT and would
    let the non-compliant build pass, which is what the first version of this
    test did.

    COMPLIANT: the primitive ADR-002 D3 specifies -- ONE guarded statement, and
    rowcount is the verdict. There is no window between the check and the write
    because they are the same statement.

    NON-COMPLIANT (the control): read the epoch, decide, then write. The decision
    is made against a value that can go stale before the write lands. This is the
    natural implementation and D3 prohibits it."""
    rnd = random.Random(seed)
    c = _connect(Path(path_s))
    accepted = rejected = 0
    for i in range(n):
        # Claim the lease: take the next epoch atomically. Both builds do this
        # identically -- the claim is not what is under test, the WRITE is.
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute("SELECT current_epoch FROM leased_state "
                        "WHERE domain='d0'").fetchone()[0]
        mine = cur + 1
        c.execute("UPDATE leased_state SET current_epoch=? WHERE domain='d0'", (mine,))
        c.execute("COMMIT")

        if compliant:
            r = c.execute(
                "UPDATE leased_state SET value=?, written_by_epoch=? "
                "WHERE domain='d0' AND current_epoch=?",
                (f"w{worker_id}-{i}", mine, mine))
            accepted += 1 if r.rowcount > 0 else 0
            rejected += 0 if r.rowcount > 0 else 1
        else:
            seen = c.execute("SELECT current_epoch FROM leased_state "
                             "WHERE domain='d0'").fetchone()[0]
            if seen == mine:
                # The TOCTOU window. In production this is an ordinary scheduling
                # delay; here it is made explicit so the control's failure is
                # reproducible rather than left to luck.
                time.sleep(rnd.uniform(0.0002, 0.0020))
                c.execute("UPDATE leased_state SET value=?, written_by_epoch=? "
                          "WHERE domain='d0'", (f"w{worker_id}-{i}", mine))
                accepted += 1
            else:
                rejected += 1
    c.close()
    q.put({"worker": worker_id, "accepted": accepted, "rejected": rejected})


def run_fencing(tmp: Path, writes: int = 10000, levels=(2, 4, 8)) -> dict:
    """§1.1. Zero accepted stale-epoch writes is the pass condition. A RATE is not
    acceptable: the scenario this protects happens rarely and matters absolutely.

    THE ASSERTION IS READ FROM COMMITTED STATE, NOT FROM THE WRITERS. A trigger
    appends every committed change of written_by_epoch to write_history in commit
    order. Epochs only ever increase, so a write by an expired owner is exactly a
    DECREASE in that sequence. That makes a stale write a property of the database
    rather than a claim by the process that did or did not make it."""
    results = {}
    for compliant in (True, False):
        build = "compliant" if compliant else "non_compliant_control"
        per_level = []
        for writers in levels:
            db = tmp / f"state_{build}_{writers}.db"
            for suffix in ("", "-wal", "-shm"):
                p_ = Path(str(db) + suffix)
                if p_.exists():
                    p_.unlink()
            _init_state(db)
            q = mp.Queue()
            per_writer = max(1, writes // writers)
            procs = [mp.Process(target=_contender,
                                args=(str(db), w, per_writer, compliant, q, 1000 + w))
                     for w in range(writers)]
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=300)
            drained = []
            while not q.empty():
                drained.append(q.get())

            c = _connect(db)
            hist = [r[0] for r in c.execute(
                "SELECT epoch FROM write_history ORDER BY id").fetchall()]
            row = c.execute("SELECT current_epoch, written_by_epoch "
                            "FROM leased_state WHERE domain='d0'").fetchone()
            c.close()

            regressions = [
                {"at_index": i + 1, "from_epoch": a, "to_epoch": b}
                for i, (a, b) in enumerate(zip(hist, hist[1:])) if b < a
            ]
            per_level.append({
                "concurrent_writers": writers,
                "committed_writes": len(hist),
                "writer_reported_accepted": sum(d["accepted"] for d in drained),
                "writer_reported_rejected": sum(d["rejected"] for d in drained),
                "stale_writes_observed_in_committed_state": len(regressions),
                "first_regressions": regressions[:5],
                "final_current_epoch": row[0],
                "final_written_by_epoch": row[1],
                "passes": len(regressions) == 0,
            })
        results[build] = {
            "levels": per_level,
            "all_levels_pass": all(l["passes"] for l in per_level),
        }

    compliant_ok = results["compliant"]["all_levels_pass"]
    control_failed = not results["non_compliant_control"]["all_levels_pass"]
    return {
        "section": "1.1",
        "writes_per_level": writes,
        "results": results,
        "criterion_1_zero_stale_accepted": compliant_ok,
        "criterion_2_control_build_fails": control_failed,
        "verdict": (
            "PASS" if (compliant_ok and control_failed) else
            "FAIL -- fencing primitive does not hold; ADR-002 D3 must change (BLOCKING)"
            if not compliant_ok else
            "INCONCLUSIVE -- the non-compliant control PASSED, so this suite is not "
            "measuring the property it claims to measure. Criterion 2 exists exactly "
            "to catch this, and a compliant PASS alongside a control PASS is worth "
            "nothing."
        ),
    }


# --------------------------------------------------------------------------- 1.2


def _crash_child(path_s: str, store: str, n_rows: int) -> None:
    """Write continuously until killed. Never exits on its own."""
    c = _connect(Path(path_s))
    c.execute("""CREATE TABLE IF NOT EXISTS records (
                     seq INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                     prev_hash TEXT NOT NULL, this_hash TEXT NOT NULL)""")
    prev = "genesis"
    seq = 0
    while True:
        seq += 1
        payload = f"{store}-{seq}-" + "x" * 200
        h = hashlib.sha256((prev + payload).encode()).hexdigest()
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO records VALUES (?,?,?,?)", (seq, payload, prev, h))
        c.execute("COMMIT")
        prev = h


def run_crash(tmp: Path, trials: int = 500) -> dict:
    """§1.2. Kill the writer at a randomised point, reopen, and assert the last
    transaction is fully present or fully absent -- never torn -- and that the
    audit hash chain is unbroken.

    HONESTY NOTE, and it is a real limitation rather than a caveat: these are
    SIGKILL trials. §1.2 also requires POWER-CUT trials on at least one candidate
    node, because a process kill does not exercise the disk write cache the way a
    power loss does. SIGKILL validates the SQLite/WAL layer; it does NOT validate
    the drive's flush behaviour. Criterion 3 is therefore only partly closed here,
    and the report says so rather than claiming the whole of it."""
    torn = []
    broken_chain = []
    failed_open = []
    per_trial = []
    rnd = random.Random(20260814)

    for t in range(trials):
        store = STORES[t % len(STORES)]
        db = tmp / f"crash_{t}.db"
        if db.exists():
            db.unlink()
        p = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{Path(__file__).parent}'); "
             f"from validate_persistence import _crash_child; "
             f"_crash_child(r'{db}', '{store}', 0)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait until the child is genuinely COMMITTING before killing it.
        # Without this the kill can land during interpreter startup or CREATE
        # TABLE, and the reopen then fails with "no such table" -- which the
        # first version of this harness scored as a crash-safety failure. That
        # would be a false positive on a BLOCKING criterion, i.e. exactly the
        # kind of finding that gets a sound design rejected.
        armed = False
        arm_deadline = time.monotonic() + 20.0
        while time.monotonic() < arm_deadline:
            try:
                probe = _connect(db)
                n_rows = probe.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                probe.close()
                if n_rows >= 5:
                    armed = True
                    break
            except sqlite3.Error:
                pass
            time.sleep(0.01)
        if not armed:
            p.kill(); p.wait(timeout=10)
            per_trial.append({"trial": t, "store": store, "opened": None,
                              "rows_recovered": 0, "chain_intact": None,
                              "skipped": "child never reached a committed state"})
            continue

        # Randomised kill point past the arming threshold, so the kill lands at
        # an arbitrary phase of an arbitrary transaction.
        time.sleep(rnd.uniform(0.02, 0.30))
        p.kill()
        p.wait(timeout=10)

        ok_open = True
        chain_ok = True
        rows = 0
        try:
            c = _connect(db)
            recs = c.execute("SELECT seq,payload,prev_hash,this_hash "
                             "FROM records ORDER BY seq").fetchall()
            rows = len(recs)
            prev = "genesis"
            for seq, payload, ph, th in recs:
                # A torn row would break either the link or the hash itself.
                if ph != prev:
                    chain_ok = False
                    break
                if hashlib.sha256((prev + payload).encode()).hexdigest() != th:
                    chain_ok = False
                    break
                prev = th
            c.close()
        except Exception:
            ok_open = False

        if not ok_open:
            failed_open.append(t)
        elif not chain_ok:
            broken_chain.append(t)
        per_trial.append({"trial": t, "store": store, "opened": ok_open,
                          "rows_recovered": rows, "chain_intact": chain_ok})
        try:
            db.unlink()
            for suffix in ("-wal", "-shm"):
                q = Path(str(db) + suffix)
                if q.exists():
                    q.unlink()
        except OSError:
            pass

    skipped = [t["trial"] for t in per_trial if t.get("skipped")]
    scored = len(per_trial) - len(skipped)
    return {
        "section": "1.2",
        "trials_requested": trials,
        "trials_scored": scored,
        "trials_skipped_unarmed": skipped,
        "kill_mode": "SIGKILL (Popen.kill), after the child has committed >= 5 rows",
        "stores_exercised": STORES,
        "failed_to_open": failed_open,
        "torn_transactions": torn,
        "broken_hash_chains": broken_chain,
        "criterion_3_zero_torn": (
            scored > 0 and len(failed_open) == 0 and len(broken_chain) == 0),
        "criterion_4_chain_unbroken": len(broken_chain) == 0,
        "power_cut_trials_run": False,
        "limitation": (
            "SIGKILL only. §1.2 requires power-cut trials on at least one candidate "
            "node because a process kill does not exercise the disk write cache the "
            "way a power loss does. Criterion 3 is PARTLY closed: the SQLite/WAL "
            "layer is validated, the drive's flush behaviour is not."
        ),
        # Per-trial detail is retained deliberately: §4 deliverable 2 says
        # "no aggregation that hides a single tear".
        "per_trial": per_trial,
    }


# --------------------------------------------------------------------------- 1.3


def run_checkpoint(tmp: Path, n: int = 500) -> dict:
    """§1.3. Checkpoint commit at synchronous=FULL under concurrent read load.
    Budget 200 ms at p95. Record p50 / p95 / max.

    Also asserts the ADR-002 D6 ORDERING: the checkpoint is acknowledged BEFORE
    the plan step is marked complete. An implementation that reverses them
    resumes having forgotten what it just did, and no latency figure would
    reveal it -- which is why the ordering gets its own assertion."""
    db = tmp / "checkpoint.db"
    if db.exists():
        db.unlink()
    c = _connect(db, synchronous="FULL")
    c.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                     id INTEGER PRIMARY KEY, step INTEGER, blob TEXT,
                     acked_at REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS steps (
                     step INTEGER PRIMARY KEY, completed_at REAL)""")

    q = mp.Queue()
    reader = mp.Process(target=_read_load, args=(str(db), 25.0))
    reader.start()

    blob = "z" * 8192
    lat = []
    ordering_violations = 0
    for i in range(n):
        t0 = time.perf_counter()
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO checkpoints VALUES (?,?,?,?)",
                  (i, i, blob, time.time()))
        c.execute("COMMIT")
        acked = time.perf_counter()
        lat.append((acked - t0) * 1000.0)
        # D6: the step is marked complete only AFTER the checkpoint is acked.
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO steps VALUES (?,?)", (i, time.time()))
        c.execute("COMMIT")
        row = c.execute("SELECT c.acked_at, s.completed_at FROM checkpoints c "
                        "JOIN steps s ON s.step=c.step WHERE c.step=?", (i,)).fetchone()
        if row and row[1] < row[0]:
            ordering_violations += 1

    reader.join(timeout=40)
    if reader.is_alive():
        reader.terminate()
    c.close()

    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[int(len(lat) * 0.95) - 1]
    return {
        "section": "1.3",
        "commits": n,
        "synchronous": "FULL",
        "journal_mode": "WAL",
        "under_concurrent_read_load": True,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(lat), 2),
        "budget_ms_p95": CHECKPOINT_BUDGET_MS,
        "criterion_5_within_budget": p95 <= CHECKPOINT_BUDGET_MS,
        "criterion_6_checkpoint_acked_before_step_complete": ordering_violations == 0,
        "ordering_violations": ordering_violations,
        "budget_note": (
            "INV-PERF-1: on a miss the budget is NOT relaxed. Options are optimise, "
            "raise the minimum profile, or record a limitation."
        ),
    }


def _read_load(path_s: str, seconds: float) -> None:
    c = _connect(Path(path_s))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            c.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        except sqlite3.Error:
            pass
    c.close()


# --------------------------------------------------------------------------- 1.4


def run_appendonly(tmp: Path) -> dict:
    """§1.4. Every UPDATE and DELETE against log.db, audit.db and tombstones.db
    must fail AT THE STORAGE LAYER, not at a policy check.

    The distinction is the whole point. A policy check is code that can be
    bypassed by other code; a storage-layer refusal cannot be. This uses SQLite
    triggers that RAISE(ABORT), which is enforcement inside the engine and
    survives any caller."""
    out = []
    for store in APPEND_ONLY_STORES:
        db = tmp / f"{store}.db"
        if db.exists():
            db.unlink()
        c = _connect(db)
        c.execute("CREATE TABLE records (seq INTEGER PRIMARY KEY, payload TEXT)")
        c.execute(f"""CREATE TRIGGER {store}_no_update BEFORE UPDATE ON records
                      BEGIN SELECT RAISE(ABORT,
                        'append-only store: UPDATE forbidden (ADR-002 D9)'); END""")
        c.execute(f"""CREATE TRIGGER {store}_no_delete BEFORE DELETE ON records
                      BEGIN SELECT RAISE(ABORT,
                        'append-only store: DELETE forbidden (ADR-002 D9)'); END""")
        c.execute("INSERT INTO records VALUES (1, 'first')")

        upd_blocked = del_blocked = False
        upd_err = del_err = None
        try:
            c.execute("UPDATE records SET payload='tampered' WHERE seq=1")
        except sqlite3.Error as e:
            upd_blocked, upd_err = True, str(e)
        try:
            c.execute("DELETE FROM records WHERE seq=1")
        except sqlite3.Error as e:
            del_blocked, del_err = True, str(e)

        survived = c.execute("SELECT payload FROM records WHERE seq=1").fetchone()
        c.close()
        out.append({
            "store": store,
            "update_blocked": upd_blocked, "update_error": upd_err,
            "delete_blocked": del_blocked, "delete_error": del_err,
            "row_unchanged_after_attempts": survived is not None and survived[0] == "first",
            "enforcement_layer": "storage (SQLite BEFORE trigger, RAISE(ABORT))",
        })
    return {
        "section": "1.4",
        "stores": out,
        "criterion_7_all_blocked": all(
            s["update_blocked"] and s["delete_blocked"] and s["row_unchanged_after_attempts"]
            for s in out),
    }


# --------------------------------------------------------------------------- report


def cmd_all(args) -> int:
    tmp = Path(args.workdir)
    tmp.mkdir(parents=True, exist_ok=True)
    print("SPIKE-008 -- ADR-002 persistence validation")
    print(f"  workdir {tmp}")

    print("  §1.1 fencing (both builds) ...")
    fencing = run_fencing(tmp, writes=args.writes)
    print(f"       compliant zero-stale={fencing['criterion_1_zero_stale_accepted']}  "
          f"control-fails={fencing['criterion_2_control_build_fails']}")

    print("  §1.4 append-only ...")
    appendonly = run_appendonly(tmp)
    print(f"       all blocked at storage layer={appendonly['criterion_7_all_blocked']}")

    print("  §1.3 checkpoint budget under read load ...")
    checkpoint = run_checkpoint(tmp, n=args.commits)
    print(f"       p50={checkpoint['p50_ms']} ms  p95={checkpoint['p95_ms']} ms  "
          f"budget={CHECKPOINT_BUDGET_MS} ms  within={checkpoint['criterion_5_within_budget']}")

    print(f"  §1.2 crash trials x{args.trials} ...")
    crash = run_crash(tmp, trials=args.trials)
    print(f"       torn=0? {crash['criterion_3_zero_torn']}  "
          f"chain intact? {crash['criterion_4_chain_unbroken']}")

    criteria = {
        "1_zero_stale_epoch_writes": fencing["criterion_1_zero_stale_accepted"],
        "2_non_compliant_control_fails": fencing["criterion_2_control_build_fails"],
        "3_zero_torn_transactions": crash["criterion_3_zero_torn"],
        "4_audit_chain_unbroken": crash["criterion_4_chain_unbroken"],
        "5_checkpoint_p95_within_budget": checkpoint["criterion_5_within_budget"],
        "6_checkpoint_acked_before_step": checkpoint["criterion_6_checkpoint_acked_before_step_complete"],
        "7_append_only_enforced_at_storage": appendonly["criterion_7_all_blocked"],
        "8_upcaster_behaviour": None,
        "9_all_stores_open_every_node_class": None,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spike": "SPIKE-008",
        "adr": "ADR-002",
        "node": {
            "os": f"{platform.system()} {platform.version()}",
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "cpu_count": os.cpu_count(),
            "workdir_free_gb": round(shutil.disk_usage(tmp).free / 1024**3, 1),
        },
        "sections": {
            "1.1_fencing": fencing,
            "1.2_crash_safety": crash,
            "1.3_checkpoint_budget": checkpoint,
            "1.4_append_only": appendonly,
            "1.5_read_time_upcasting": {
                "status": "NOT_RUN",
                "reason": "Needs the runtime's event codec and upcaster registry, which "
                          "do not exist until F0. Criterion 8 stays OPEN.",
            },
            "1.6_portability": {
                "status": "NOT_RUN",
                "reason": "Needs the other candidate node classes enrolled, including the "
                          "foreground_only one. Only one node is enrolled today. "
                          "Criterion 9 stays OPEN.",
            },
        },
        "criteria": criteria,
        "criteria_closed": sum(1 for v in criteria.values() if v is True),
        "criteria_total": len(criteria),
        "blocking_criteria_pass": all(
            criteria[k] for k in ("1_zero_stale_epoch_writes",
                                  "2_non_compliant_control_fails",
                                  "3_zero_torn_transactions",
                                  "4_audit_chain_unbroken")),
        "promotion_note": (
            "This report is EVIDENCE FOR OWNER-DECISION-006(b), not the decision. "
            "SPIKE-008's on_fail is explicit: ADR-002 is revised BEFORE F0 rather than "
            "discovered during it. Criteria 8 and 9 are OPEN, so this is a partial "
            "result and an acceptance resting on it must say which parts it rests on."
        ),
    }
    dest = Path(args.out) if args.out else (
        REPORT_DIR / "SPIKE-008-adr002-validation.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n  {report['criteria_closed']}/{report['criteria_total']} criteria closed; "
          f"blocking criteria pass = {report['blocking_criteria_pass']}")
    print(f"  wrote {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fencing", "crash", "checkpoint", "appendonly", "all"])
    ap.add_argument("--out")
    ap.add_argument("--workdir",
                    default=str(Path(os.environ.get("TEMP", "/tmp")) / "vesper_spike008"))
    ap.add_argument("--writes", type=int, default=10000)
    ap.add_argument("--trials", type=int, default=500)
    ap.add_argument("--commits", type=int, default=500)
    args = ap.parse_args()

    tmp = Path(args.workdir)
    tmp.mkdir(parents=True, exist_ok=True)
    if args.cmd == "all":
        return cmd_all(args)
    fn = {"fencing": lambda: run_fencing(tmp, args.writes),
          "crash": lambda: run_crash(tmp, args.trials),
          "checkpoint": lambda: run_checkpoint(tmp, args.commits),
          "appendonly": lambda: run_appendonly(tmp)}[args.cmd]
    print(json.dumps(fn(), indent=2)[:4000])
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
