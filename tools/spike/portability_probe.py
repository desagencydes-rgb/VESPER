#!/usr/bin/env python3
"""SPIKE-008 §1.6 / criterion 9 — the five stores as a PORTABLE ARTIFACT.

WHY THIS IS A SEPARATE INSTRUMENT. Criterion 9 asks whether all five stores open
on every candidate node class, and §1.6 adds "byte-identical checksums after
transfer". No single machine can answer that: it is a statement about a file
that has moved. `validate_persistence.py all` correctly records §1.6 as NOT_RUN
on each node it runs on, and would keep doing so forever, because the test is
not a measurement one node takes -- it is an emit on node A and a verify on
node B.

So this splits into two halves that run on different machines:

    node A:  python tools/spike/portability_probe.py emit   --dir <d>
             (commit <d> -- the repository IS the transfer medium)
    node B:  python tools/spike/portability_probe.py verify --dir <d>

WHAT IT SEPARATES, and this distinction is not in the protocol. §1.6 says
"byte-identical checksums", but byte-identity and portability are different
claims and only one of them is load-bearing:

  * FILE DIGEST -- sha256 of the file. Answers "did the bytes survive the
    transfer". A real property, but a store that fails it is corrupt, not
    merely non-portable.
  * LOGICAL DIGEST -- a hash over the rows as SQLite reads them back, ordered
    deterministically. Answers "did the DATA survive, on this node's SQLite
    build". This is what ADR-002 D10's survival carry actually needs. Two nodes
    can legitimately disagree on file bytes -- page layout, freelist state and
    version headers all differ -- while agreeing perfectly on content.

Reporting only the first would fail a store that is perfectly portable. Reporting
only the second would miss a truncated transfer. Both are recorded.

THE NEGATIVE CONTROL, and the first version of it was worthless. `emit
--leave-wal` was supposed to leave the tail in a `-wal` sidecar so that copying
the `.db` alone would lose it. It passed -- because SQLite CHECKPOINTS ON LAST
CONNECTION CLOSE. By the time anything was copied the WAL had already been
folded back in, the sidecars were empty, and the control demonstrated nothing.
That is the same failure as the SPIKE-008 fencing control that initially passed:
a test that has never been red is not evidence.

The control now reproduces the scenario that actually loses data -- copying the
stores WHILE THE RUNTIME IS RUNNING, with a writer connection still open and
`wal_autocheckpoint` disabled, which is exactly how a live ADR-002 D10 survival
carry would be taken. `portability_probe.py control` does that and FAILS if no
rows are lost, because a control that cannot show the loss cannot certify its
absence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_persistence import STORES, APPEND_ONLY_STORES  # noqa: E402

MANIFEST = "MANIFEST.json"
# Fixed, so two nodes emit comparable content and nothing depends on a clock or
# an RNG. Date.now()-style inputs would make every cross-node comparison fail
# for a reason that has nothing to do with portability.
ROWS_PER_STORE = 200
SEED_TEXT = "vesper-spike008-portability"


def _connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=FULL")
    return c


def _payload(store: str, i: int) -> tuple[str, str]:
    body = f"{SEED_TEXT}:{store}:{i:06d}"
    return body, hashlib.sha256(body.encode()).hexdigest()


def _create(path: Path, store: str) -> None:
    c = _connect(path)
    c.execute("""CREATE TABLE IF NOT EXISTS records (
                     seq INTEGER PRIMARY KEY,
                     body TEXT NOT NULL,
                     body_sha256 TEXT NOT NULL)""")
    if store in APPEND_ONLY_STORES:
        # ADR-002 D9. The guard is part of the artifact, not of the runtime that
        # wrote it -- so it must survive the transfer too. A store that arrives
        # on another node with its append-only guard missing is not the same
        # store, even if every row matches.
        for op in ("UPDATE", "DELETE"):
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS no_{op.lower()}_records
                          BEFORE {op} ON records
                          BEGIN SELECT RAISE(ABORT,
                              'append-only store: {op} refused at the storage layer');
                          END""")
    c.execute("BEGIN")
    for i in range(ROWS_PER_STORE):
        body, digest = _payload(store, i)
        c.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (i, body, digest))
    c.execute("COMMIT")
    c.close()


def _checkpoint(path: Path) -> str:
    """Fold the WAL back into the .db so the file is self-contained.

    TRUNCATE rather than PASSIVE: PASSIVE may decline to run if a reader holds
    the WAL, and would then report success having done nothing -- leaving a
    store that looks checkpointed and is not."""
    c = sqlite3.connect(str(path), isolation_level=None)
    row = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    c.execute("PRAGMA journal_mode=DELETE")  # drop the -wal/-shm sidecars entirely
    c.close()
    return f"wal_checkpoint(TRUNCATE) -> busy={row[0]}, log_frames={row[1]}, checkpointed={row[2]}"


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _logical_digest(path: Path) -> tuple[str, int]:
    """Hash the rows as SQLite reads them, in a deterministic order.

    This is the digest that should match across nodes. It is deliberately blind
    to page layout, freelist state and file-format version bytes, all of which
    can differ between SQLite builds without a single row being different."""
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    h = hashlib.sha256()
    n = 0
    for seq, body, digest in c.execute(
            "SELECT seq, body, body_sha256 FROM records ORDER BY seq"):
        h.update(f"{seq}\x1f{body}\x1f{digest}\x1e".encode())
        n += 1
    c.close()
    return h.hexdigest(), n


def _node_identity() -> dict:
    return {
        "hostname_hint": platform.node(),
        "os_family": platform.system(),
        "os_version": platform.version(),
        "python_version": platform.python_version(),
        # sqlite3.version (the pysqlite wrapper version) was REMOVED in Python
        # 3.14 and is not read here. The library version is the one that matters
        # for portability anyway -- it is what decides whether a file opens.
        "sqlite_version": sqlite3.sqlite_version,
    }


def cmd_emit(args) -> int:
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    for stale in d.glob("*.db*"):
        stale.unlink()

    files = {}
    for store in STORES:
        p = d / f"{store}.db"
        _create(p, store)
        note = _checkpoint(p)
        logical, rows = _logical_digest(p)
        files[f"{store}.db"] = {
            "store": store,
            "append_only": store in APPEND_ONLY_STORES,
            "bytes": p.stat().st_size,
            "file_sha256": _file_digest(p),
            "logical_sha256": logical,
            "rows": rows,
            "checkpoint": note,
            "sidecars_present": sorted(
                q.name for q in d.glob(f"{store}.db-*")),
        }

    manifest = {
        "schema_version": 1,
        "spike": "SPIKE-008",
        "section": "1.6 portability / criterion 9",
        "role": "emit",
        "negative_control": False,
        "emitted_by": _node_identity(),
        "rows_per_store": ROWS_PER_STORE,
        "seed_text": SEED_TEXT,
        "files": files,
        "how_to_verify": (
            "On a DIFFERENT node class, from a checkout of this repository: "
            "python tools/spike/portability_probe.py verify --dir <this dir>"
        ),
        "what_a_pass_means": (
            "logical_sha256 matching on both nodes means the DATA is portable, "
            "which is what ADR-002 D10 survival carry requires. file_sha256 "
            "matching additionally means the bytes were transferred intact. A "
            "logical match with a file mismatch is still a pass for criterion 9 "
            "and must be reported as such, not as a failure."
        ),
    }
    (d / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name, meta in files.items():
        print(f"  {name:16} {meta['bytes']:>8} B  rows={meta['rows']:<4} "
              f"sidecars={meta['sidecars_present'] or 'none'}")
    print(f"\nwrote {d / MANIFEST}")
    return 0


def cmd_control(args) -> int:
    """NEGATIVE CONTROL: copy the stores while the runtime still holds them open.

    This is the scenario that actually loses data, and it is the realistic one --
    an ADR-002 D10 survival carry taken from a LIVE node, not a stopped one. The
    writer connection stays open and `wal_autocheckpoint` is off, so recent
    commits live only in the `-wal` sidecar. Copying the `.db` alone silently
    yields a store that opens cleanly, passes `integrity_check`, and is missing
    its most recent writes -- the worst possible failure mode, because nothing
    about it looks like a failure.

    An earlier control skipped the checkpoint and then closed the connection.
    That proved nothing: SQLite checkpoints on last-connection-close, so the WAL
    was always folded back in before anything was copied, and the control passed.
    A control that passes has measured nothing. This one FAILS (exit 2) if the
    rows do not go missing, because a control that cannot demonstrate the loss
    cannot certify its absence.
    """
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    for stale in d.glob("*.db*"):
        stale.unlink()

    live = d / "live"
    copied = d / "copied"
    live.mkdir(exist_ok=True)
    copied.mkdir(exist_ok=True)
    for old in list(live.glob("*")) + list(copied.glob("*")):
        old.unlink()

    p = live / "log.db"
    _create(p, "log")

    # Hold the connection open, disable autocheckpoint, and commit a tail that
    # therefore stays in the WAL.
    c = _connect(p)
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("BEGIN")
    for i in range(ROWS_PER_STORE, ROWS_PER_STORE + 300):
        body, digest = _payload("log", i)
        c.execute("INSERT INTO records VALUES (?,?,?)", (i, body, digest))
    c.execute("COMMIT")

    total_live = c.execute("SELECT count(*) FROM records").fetchone()[0]
    wal = p.with_name(p.name + "-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0

    # The naive carry: copy the .db, leave the sidecars behind.
    dst = copied / "log.db"
    dst.write_bytes(p.read_bytes())
    c.close()

    ro = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    integrity = ro.execute("PRAGMA integrity_check").fetchone()[0]
    total_copied = ro.execute("SELECT count(*) FROM records").fetchone()[0]
    ro.close()

    lost = total_live - total_copied
    demonstrated = lost > 0
    out = {
        "schema_version": 1,
        "spike": "SPIKE-008",
        "section": "1.6 portability -- NEGATIVE CONTROL",
        "scenario": "stores copied while the runtime holds them open, wal_autocheckpoint=0",
        "node": _node_identity(),
        "rows_in_live_store": total_live,
        "rows_in_copied_store": total_copied,
        "rows_lost": lost,
        "wal_bytes_left_behind": wal_bytes,
        "copied_store_opens": True,
        "copied_store_integrity_check": integrity,
        "control_demonstrated_the_loss": demonstrated,
        "why_this_is_the_dangerous_case": (
            "The copied store OPENS and passes integrity_check while missing "
            f"{lost} committed rows. A carry that checks only 'does it open' "
            "would certify this store as good."
        ),
        "verdict": "CONTROL OK -- loss demonstrated" if demonstrated else
                   "CONTROL USELESS -- no loss occurred, so it proves nothing",
    }
    print(json.dumps(out, indent=2))
    if args.out:
        o = Path(args.out)
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nwrote {o}", file=sys.stderr)
    return 0 if demonstrated else 2


def cmd_verify(args) -> int:
    d = Path(args.dir)
    mpath = d / MANIFEST
    if not mpath.exists():
        print(f"no {MANIFEST} in {d} -- run `emit` on the source node first", file=sys.stderr)
        return 1
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    results = {}
    all_open = True
    all_logical = True
    for name, expect in manifest["files"].items():
        p = d / name
        r: dict = {"store": expect["store"]}
        if not p.exists():
            r.update(opens=False, error="file missing after transfer")
            results[name] = r
            all_open = False
            all_logical = False
            continue
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            r["integrity_check"] = c.execute("PRAGMA integrity_check").fetchone()[0]
            c.close()
            r["opens"] = True
        except sqlite3.Error as e:
            r.update(opens=False, error=f"{type(e).__name__}: {e}")
            results[name] = r
            all_open = False
            all_logical = False
            continue

        logical, rows = _logical_digest(p)
        fdig = _file_digest(p)
        r.update(
            rows_read=rows,
            rows_expected=expect["rows"],
            file_sha256_match=(fdig == expect["file_sha256"]),
            logical_sha256_match=(logical == expect["logical_sha256"]),
            bytes_now=p.stat().st_size,
            bytes_at_emit=expect["bytes"],
        )
        # The append-only guard has to survive the transfer too. A store whose
        # rows all match but whose triggers are gone is not the same store.
        if expect["append_only"]:
            try:
                c = sqlite3.connect(str(p), isolation_level=None)
                c.execute("UPDATE records SET body='tamper' WHERE seq=0")
                c.close()
                r["append_only_guard_survived"] = False
            except sqlite3.Error:
                r["append_only_guard_survived"] = True
        if not r["logical_sha256_match"]:
            all_logical = False
        if not r["opens"]:
            all_open = False
        results[name] = r

    verdict = {
        "schema_version": 1,
        "spike": "SPIKE-008",
        "section": "1.6 portability / criterion 9",
        "role": "verify",
        "negative_control": manifest.get("negative_control", False),
        "emitted_by": manifest["emitted_by"],
        "verified_by": _node_identity(),
        "cross_node": manifest["emitted_by"]["hostname_hint"] != platform.node(),
        "all_stores_open": all_open,
        "all_logical_digests_match": all_logical,
        "per_store": results,
    }
    if verdict["negative_control"]:
        verdict["criterion_9_contribution"] = (
            "NONE -- this is the negative control. It is EXPECTED to lose the "
            "uncheckpointed tail. A control that passes has measured nothing."
        )
    elif not verdict["cross_node"]:
        verdict["criterion_9_contribution"] = (
            "NONE -- emitted and verified on the SAME host. Criterion 9 is a "
            "cross-node-class claim; a same-host verify only proves the probe "
            "runs. Recorded so it is never mistaken for the real result."
        )
    else:
        verdict["criterion_9_contribution"] = (
            "One node class closed. Criterion 9 needs every candidate class from "
            "SPIKE-001, including the foreground_only one."
        )

    out = Path(args.out) if args.out else None
    print(json.dumps(verdict, indent=2))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0 if (all_open and all_logical) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit", help="create the five stores as a portable artifact")
    e.add_argument("--dir", required=True)
    e.set_defaults(func=cmd_emit)
    ctl = sub.add_parser(
        "control", help="NEGATIVE CONTROL: copy stores from a LIVE runtime and lose the tail")
    ctl.add_argument("--dir", required=True)
    ctl.add_argument("--out")
    ctl.set_defaults(func=cmd_control)
    v = sub.add_parser("verify", help="open and verify an emitted artifact on this node")
    v.add_argument("--dir", required=True)
    v.add_argument("--out")
    v.set_defaults(func=cmd_verify)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
