#!/usr/bin/env python3
"""Re-derive A-029's verdict from the durable log, independently of the harness.

WHY A SECOND VERIFIER. `run_a029_endurance.py` judges Part 1 from
`AutonomyLoop.heartbeats` -- the loop's own in-memory list -- and Part 3 from
the injection times its own controller recorded. Both are the harness's account
of what it did. A-029 says the run retains a full event log, and the 2026-08-15
report's failure #4 was a check that compared a component's list against the
artifact that component had just produced. This reads the log instead.

WHAT MAKES IT INDEPENDENT, precisely:

  * Heartbeats come from `autonomy.heartbeat` records, not from a Python list.
  * The injections are found by looking for the world write itself
    (`world.fact_updated` at the A-029 subject and value), so the moment T
    arrived is reconstructed from what the SYSTEM recorded, not from what the
    controller says it did.
  * The tick a firing followed is derived by counting heartbeat records that
    precede it in the log, so `delta_ticks` is measured here rather than
    carried over.
  * The predicate is rebuilt from `a029_protocol` and re-run against the
    snapshot as stored. A trigger this verifier cannot rebuild is reported as
    UNVERIFIABLE and fails, because "I could not check it" must never read the
    same as "it passed".

THE STORE IS OPENED READ-ONLY, NOT COPIED. SPIKE-008's own portability control
established that copying a SQLite store while a writer connection is open is
the unsafe path -- it lost 300 committed rows while still passing
`integrity_check`. A `mode=ro` URI connection is safe against a live WAL
writer, so this can be run against a run that is still in flight.

    python verification/verify_a029_from_log.py --data-dir <run>/.a029-data/a029
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a029_protocol import (ATTRIBUTE, INJECTED_VALUE, SUBJECT,  # noqa: E402
                           TERM, TRIGGER_ID, check_part1, check_part2,
                           check_part3, part3_run_record, temperature_trigger)
from harness import Case, print_results  # noqa: E402

HEARTBEAT = "autonomy.heartbeat"
FIRED = "autonomy.trigger_fired"
NOOP = "autonomy.noop"
STALLED = "autonomy.loop_stalled"
MODEL_CALL = "autonomy.model_call_in_decision_path"
FACT = "world.fact_updated"


def read_log(db: Path) -> list[tuple[int, str, dict]]:
    """Every record in HLC order, across every segment, read-only.

    SEGMENTS, NOT ONE FILE. `StoreSet.rotate` archives a full log by renaming it
    to `log-seg<stamp>-to<high>.db` and opening a fresh one; the sequence
    continues and nothing is deleted. This function opens a PATH rather than
    going through the store, and it is the PRIMARY EVIDENCE for A-029 -- so
    reading only the live file after a rotation would under-report every
    heartbeat, firing and no-op before it.

    That failure would not have looked like a missing file. A-029 part 1
    asserts the window is covered at BOTH ENDS, so a truncated read fails the
    gate for a reason having nothing to do with the loop being alive, and the
    natural response to that is to go looking at the loop. Rotation is built and
    deliberately not wired yet; this is one of the two things it waits on.

    ORDERED ACROSS SEGMENTS RATHER THAN WITHIN THEM. Each file is already in
    HLC order and segments do not overlap in time, but sorting the union is what
    makes that a property of the data instead of an assumption about how
    rotation happened to be called.
    """
    files = sorted(db.parent.glob(f"{db.stem}-seg*.db")) + [db]
    rows: list = []
    for path in files:
        if not path.exists():
            continue
        uri = f"file:{path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=30.0)
        try:
            rows.extend(con.execute(
                "SELECT seq, kind, body, hlc_physical_ms, hlc_logical, "
                "hlc_node_id FROM records").fetchall())
        finally:
            con.close()
    rows.sort(key=lambda r: (r[3], r[4], r[5]))
    return [(r[0], r[1], json.loads(r[2])) for r in rows]


def derive(records: list[tuple[int, str, dict]]) -> dict:
    """Rebuild the run's evidence from the log alone."""
    heartbeats: list = []
    fired: list = []
    noops: list = []
    injections: list = []
    counts = {STALLED: 0, MODEL_CALL: 0}
    last_tick = 0

    for _seq, kind, body in records:
        payload = body.get("payload", body)
        if kind == HEARTBEAT:
            last_tick = payload.get("tick", last_tick)
            heartbeats.append({"tick": payload.get("tick"),
                               "at_ms": payload.get("at_ms")})
        elif kind == FIRED:
            fired.append(payload)
        elif kind == NOOP:
            noops.append(payload)
        elif kind in counts:
            counts[kind] += 1
        elif kind == FACT:
            # The injection, as the SYSTEM recorded it -- not as the controller
            # claims to have made it.
            if (payload.get("subject") == SUBJECT
                    and payload.get("attribute") == ATTRIBUTE
                    and payload.get("value") == INJECTED_VALUE):
                injections.append({"after_tick": last_tick,
                                   "source": payload.get("source")})

    return {"heartbeats": heartbeats, "fired": fired, "noops": noops,
            "injections": injections,
            "stalled": counts[STALLED], "model_calls": counts[MODEL_CALL]}


def _replayer(case: Case):
    """Rebuild predicates by trigger_id. An unknown id is a FAILURE, not a skip."""
    known = {TRIGGER_ID: temperature_trigger().predicate}
    unverifiable: set = set()

    def replay(action: dict) -> bool:
        tid = action.get("trigger_id")
        fn = known.get(tid)
        if fn is None:
            unverifiable.add(tid)
            return False
        return bool(fn(action.get("snapshot", {})))

    return replay, unverifiable


def judge_from_log(data_dir: Path, tick_s: float, *,
                   window_s: float | None = None,
                   case_id: str = "A-029-FROM-LOG") -> tuple[dict, dict]:
    """Judge one run from its log. Returns (case record, derived evidence).

    `window_s` is passed when the caller knows the window the run was LAUNCHED
    for. Without it the window is inferred from the log's own span, which
    cannot see a loop that died before the end -- so an inferred window is
    reported and never used to clear a run that stopped early.
    """
    ev = derive(read_log(Path(data_dir) / "log.db"))
    hb = ev["heartbeats"]
    c = Case(case_id, "A-029 re-derived from the durable event log")
    if not hb:
        c.check("the log contains autonomy.heartbeat records", False,
                "no heartbeat records at all")
        return c.finish(), ev

    span_ms = hb[-1]["at_ms"] - hb[0]["at_ms"]
    window_ms = (window_s * 1000) if window_s else (span_ms + tick_s * 1000)
    ev["span_ms"] = span_ms
    ev["window_ms"] = window_ms
    ev["window_inferred"] = window_s is None

    replay, unverifiable = _replayer(c)
    check_part1(c, heartbeats=hb, tick_interval_ms=tick_s * 1000,
                window_ms=window_ms, window_start_ms=hb[0]["at_ms"],
                stalled_events=ev["stalled"], count_tolerance=0.02)
    check_part2(c, actions=ev["fired"],
                registered_ids={a.get("trigger_id") for a in ev["fired"]} or {TRIGGER_ID},
                replay=replay, noops=ev["noops"])
    runs = []
    for inj in ev["injections"]:
        after = [a for a in ev["fired"] if a.get("tick", 0) > inj["after_tick"]]
        runs.append(part3_run_record(inj["after_tick"], inj["after_tick"],
                                     after[0] if after else None))
    check_part3(c, runs=runs, model_call_events=ev["model_calls"])
    c.check("every fired trigger_id could be rebuilt and re-evaluated",
            not unverifiable,
            f"unverifiable trigger ids: {sorted(unverifiable)}" if unverifiable
            else "")
    c.check("the injected observation came from an enrolled synthetic_observer",
            bool(ev["injections"])
            and all(i["source"] == "synthetic_observer" for i in ev["injections"]),
            str({i["source"] for i in ev["injections"]}))
    return c.finish(), ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True,
                    help="the run's store directory (contains log.db)")
    ap.add_argument("--tick", type=float, default=60.0,
                    help="the declared tick_interval the run was launched with")
    ap.add_argument("--hours", type=float,
                    help="the window the run was LAUNCHED for. Without it the "
                         "window is inferred from the log's own span, which "
                         "cannot detect a loop that died before the end.")
    ap.add_argument("--out")
    args = ap.parse_args()

    db = Path(args.data_dir) / "log.db"
    if not db.exists():
        print(f"  no log.db at {db}")
        return 2

    rec, ev = judge_from_log(Path(args.data_dir), args.tick,
                             window_s=args.hours * 3600 if args.hours else None)
    hb = ev["heartbeats"]
    if not hb:
        print("  the log contains no autonomy.heartbeat records at all.")
        print_results([rec])
        return 1

    span_ms = ev["span_ms"]
    print(f"  log      : {db}")
    print(f"  records  : {len(hb)} heartbeats, {len(ev['fired'])} firings, "
          f"{len(ev['noops'])} no-ops, {len(ev['injections'])} injections")
    print(f"  observed : {span_ms / 3_600_000:.2f} h at a declared {args.tick}s cadence")
    if ev["window_inferred"]:
        print("  window   : INFERRED from the log's own span. Pass --hours for a "
              "completed run;\n             an inferred window cannot see a loop "
              "that stopped early.")
    if len(ev["injections"]) < 3:
        print(f"  note     : only {len(ev['injections'])} of 3 injections have "
              "happened. If the run is still\n             in flight, Part 3 is "
              "expected to be incomplete and this is not a failure.")

    print_results([rec])
    print(f"\n  A-029 FROM LOG: {'PASS' if rec['ok'] else 'FAIL'}")
    print("  This verdict is derived from the durable log only. It does not "
          "read the harness's\n  own summary, and it is not evidence about "
          "resource stability -- that needs the\n  sampler, which does not "
          "write to the log.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"schema_version": 1, "gate": "A-029-from-log",
             "source": str(db), "declared_tick_interval_s": args.tick,
             "observed_span_h": round(span_ms / 3_600_000, 3),
             "heartbeats": len(hb), "firings": len(ev["fired"]),
             "noops": len(ev["noops"]), "injections": ev["injections"],
             "stalled_events": ev["stalled"], "result": rec},
            indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
