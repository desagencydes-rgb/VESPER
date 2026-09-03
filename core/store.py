"""Persistence abstraction — the five physical stores of ADR-002.

WHY FIVE FILES AND NOT ONE. DF-LOSS-CLASS classifies a data loss by the store
the record lived in, and INV-LOSS-6 forbids that classification from being a
judgement call. One file with five tables would make "which class of data did
we lose" an argument after the fact; five files make it a property of the
filesystem. The boundaries are NORMATIVE, not organisational.

  log         append-only    the event log
  audit       append-only    what the system did, and under whose authority
  tombstones  append-only    what was deleted, so deletion is itself evidence
  state       mutable        current task/lease/world state
  workspace   mutable        scratch; the only store where loss is tolerable

THE THREE APPEND-ONLY STORES ARE ENFORCED AT THE STORAGE LAYER, not by caller
discipline. ADR-002 D9: a system that *can* rewrite its own audit log can be
wrong in a way nobody can later detect. SQLite BEFORE triggers raise on UPDATE
and DELETE, so the guarantee survives a bug in the runtime, a future
maintainer, and the runtime being compromised.

FENCING (INV-OWN-3) IS A SINGLE-STATEMENT CONDITIONAL UPDATE. Every write to a
leased domain carries the epoch it was authorised under, and the guard is
`WHERE lease_epoch <= :epoch` inside the same statement that writes. It is not
a read-then-check-then-write: SPIKE-008's negative control measured that the
read-then-write form accepts 119-3175 stale writes depending on the machine,
because the check and the write are not atomic and a partitioned ex-owner
lands in the gap. The single-statement form accepted zero across 10,000 writes
at 2, 4 and 8 concurrent writers on two node classes.

WAL + synchronous=FULL on the four durable stores; NORMAL is permitted on
workspace only (ADR-002 D1). Measured checkpoint cost: p95 1.08 ms on node 1
and 0.07 ms on node 2, against a 200 ms budget.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .hlc import HLC

STORES = ("log", "state", "audit", "tombstones", "workspace")
APPEND_ONLY = ("log", "audit", "tombstones")
# ADR-002 D1. workspace is the one store where a lost tail is acceptable, so it
# is the one store that may run at synchronous=NORMAL.
SYNC_FULL = ("log", "state", "audit", "tombstones")

# The seven independently leased domains (contracts/entities/lease.schema.json).
DOMAINS = ("tasks", "world", "memory", "devices", "policy", "autonomy_queue", "alarms")


class StaleEpochWrite(Exception):
    """A write was refused because its lease epoch is behind the store's.

    This is the fencing rejection of INV-OWN-3 and it is a NORMAL event, not a
    bug: it is exactly what happens when a partitioned ex-owner rejoins and
    tries to continue. A-034.3 asserts it happens.
    """

    def __init__(self, domain: str, offered: int, current: int) -> None:
        super().__init__(
            f"write to '{domain}' refused: offered lease_epoch {offered} is stale "
            f"(store is at {current}). INV-OWN-3 fencing."
        )
        self.domain = domain
        self.offered = offered
        self.current = current


class AppendOnlyViolation(Exception):
    """An UPDATE or DELETE was attempted against an append-only store."""


@dataclass(frozen=True, slots=True)
class Record:
    seq: int
    kind: str
    body: dict
    written_at_hlc: HLC
    lease_epoch: int


class StoreSet:
    """The five stores, opened together and closed together.

    Deliberately NOT a general-purpose ORM. Every method here exists because a
    named invariant or acceptance case requires it, and the narrowness is the
    point: a persistence layer that can express any query can also express a
    query that bypasses fencing.
    """

    def __init__(self, root: Path | str, *, node_id: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.node_id = node_id
        self._conns: dict[str, sqlite3.Connection] = {}
        self._lock = threading.RLock()
        for name in STORES:
            self._conns[name] = self._open(name)
        self._migrate()

    # ----------------------------------------------------------------- open

    # ---------------------------------------------------------- rotation

    # Which stores may be rotated into segments. The append-only three, because
    # they are the ones that grow without bound by design -- `state` and
    # `workspace` are mutable and stay one file each.
    #
    # WHY ROTATION IS THE ONLY ARCHIVAL FORM THIS LAYER PERMITS. The append-only
    # stores are enforced by SQLite BEFORE triggers that raise on UPDATE and
    # DELETE (ADR-002 D9: "a system that CAN rewrite its own audit log can be
    # wrong in a way nobody can later detect"). So compressing records in place
    # and moving old records out are not trade-offs to weigh -- they are
    # impossible. Starting a NEW FILE is neither an UPDATE nor a DELETE, and the
    # old segment stays exactly as it was written.
    #
    # AND NOTHING IS DELETED, which is the owner's own rule for the bin: comment
    # out and append, never remove. A rotated segment is renamed, indexed and
    # kept.

    # ------------------------------------------------- compressed segments

    # A COMPRESSED ARCHIVE IS STILL A DATABASE, and that is the requirement
    # rather than a preference: the owner asked for archives that sit compressed
    # on disk and stay readable WITHOUT being unpacked first. Compressing the
    # whole file reaches 15.7x measured on this corpus and fails that -- reading
    # one record would mean unpacking 1.6 GB.
    #
    # SO EACH RECORD IS COMPRESSED SEPARATELY, WITH A SHARED DICTIONARY. Measured
    # on 20,000 real records: 1.8x per-record alone, because a 600-byte event has
    # too little internal repetition for deflate to find; 4.5x with a dictionary
    # trained on the corpus, which is where the repetition actually lives -- the
    # same field names, node ids and component strings in every record. The
    # dictionary is the difference between "not worth doing" and "worth doing".
    #
    # AND THE DICTIONARY LIVES INSIDE THE ARCHIVE. A segment that needed a
    # dictionary kept somewhere else would be a file that stops being readable
    # when that somewhere else is lost or moved -- which is exactly the failure
    # an archive exists to prevent. Each file carries what it needs.
    ZDICT_KEY = "body_zdict"
    ZDICT_SAMPLE_RECORDS = 400
    ZDICT_MAX_BYTES = 32768

    @staticmethod
    def _is_compressed(conn: sqlite3.Connection) -> bytes | None:
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                (StoreSet.ZDICT_KEY,)).fetchone()
        except sqlite3.OperationalError:
            return None            # no meta table: an ordinary segment
        return bytes(row[0]) if row else None

    @staticmethod
    def _inflate(blob: bytes, zdict: bytes) -> str:
        """Decompress one record against the archive's own dictionary.

        `zlib.decompress(data, wbits, bufsize)` takes a BUFFER SIZE as its third
        argument, not a dictionary -- passing one there raises TypeError, which
        is how the first version of this failed. A dictionary is only reachable
        through `decompressobj`.
        """
        do = zlib.decompressobj(15, zdict)
        return (do.decompress(blob) + do.flush()).decode()

    def compress_segment(self, path: Path) -> dict:
        """Rewrite one archived segment with its bodies compressed.

        ONLY AN ARCHIVE, NEVER THE LIVE FILE. A rotated segment never changes
        again, which is what makes re-encoding it safe: there is no writer to
        race and no record that can arrive mid-rewrite.

        AND IT IS VERIFIED BEFORE THE ORIGINAL GOES. Every record is read back
        out of the new file and compared to the old one -- count, seq, kind and
        body -- because "the compressor returned 0" is the instrument reporting
        on itself, and this is the one operation in the system that could lose
        history silently. The original is replaced only after the copy has been
        shown to hold the same records.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            if self._is_compressed(src) is not None:
                return {"segment": path.name, "compressed": False,
                        "reason": "already compressed"}
            rows = src.execute(
                "SELECT seq, kind, body, hlc_physical_ms, hlc_logical, "
                "hlc_node_id, lease_epoch FROM records ORDER BY seq").fetchall()
        finally:
            src.close()
        if not rows:
            return {"segment": path.name, "compressed": False,
                    "reason": "empty"}

        sample = "\n".join(r[2] for r in rows[:self.ZDICT_SAMPLE_RECORDS])
        zdict = sample.encode()[:self.ZDICT_MAX_BYTES]
        tmp = path.with_name(path.name + ".compressing")
        tmp.unlink(missing_ok=True)
        dst = sqlite3.connect(str(tmp))
        try:
            dst.execute("""CREATE TABLE records (
                               seq INTEGER PRIMARY KEY,
                               kind TEXT NOT NULL,
                               body BLOB NOT NULL,
                               hlc_physical_ms INTEGER NOT NULL,
                               hlc_logical INTEGER NOT NULL,
                               hlc_node_id TEXT NOT NULL,
                               lease_epoch INTEGER NOT NULL)""")
            dst.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB)")
            dst.execute("CREATE INDEX ix_records_kind ON records(kind)")
            dst.execute("""CREATE INDEX ix_records_hlc
                           ON records(hlc_physical_ms, hlc_logical, hlc_node_id)""")
            dst.execute("INSERT INTO meta(key, value) VALUES(?, ?)",
                        (self.ZDICT_KEY, zdict))
            for seq, kind, body, pms, lg, node, epoch in rows:
                co = zlib.compressobj(9, zlib.DEFLATED, 15, 8, 0, zdict)
                blob = co.compress(body.encode()) + co.flush()
                dst.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)",
                            (seq, kind, blob, pms, lg, node, epoch))
            dst.commit()
        except Exception:
            dst.close()
            tmp.unlink(missing_ok=True)
            raise
        dst.close()

        # READ IT BACK AND COMPARE, before anything is replaced.
        check = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
        try:
            zd = self._is_compressed(check)
            back = check.execute(
                "SELECT seq, kind, body FROM records ORDER BY seq").fetchall()
            same = len(back) == len(rows) and all(
                b[0] == o[0] and b[1] == o[1]
                and self._inflate(bytes(b[2]), zd) == o[2]
                for b, o in zip(back, rows))
        finally:
            check.close()
        if not same:
            tmp.unlink(missing_ok=True)
            raise ValueError(
                f"the compressed copy of {path.name} does not hold the same "
                "records as the original; the original is untouched")

        was, now = path.stat().st_size, tmp.stat().st_size
        path.unlink()
        tmp.rename(path)
        self._emit_rotation({"segment": path.name, "compressed": True,
                             "records": len(rows), "was_bytes": was,
                             "now_bytes": now,
                             "ratio": round(was / max(now, 1), 2)})
        return {"segment": path.name, "compressed": True, "records": len(rows),
                "was_bytes": was, "now_bytes": now,
                "ratio": round(was / max(now, 1), 2)}

    def _emit_rotation(self, payload: dict) -> None:
        """Best effort: the store has no bus, so this is a hook for one."""
        hook = getattr(self, "on_segment_compressed", None)
        if hook is not None:
            try:
                hook(payload)
            except Exception:                          # noqa: BLE001
                pass

    def segments(self, store: str) -> list:
        """Every segment of a store, oldest first, live one last."""
        pat = f"{store}-seg*.db"
        old = sorted(self.root.glob(pat))
        return [*old, self.root / f"{store}.db"]

    def rotate(self, store: str) -> dict:
        """Close the live file, name it a segment, and open a fresh one.

        THE SEQUENCE MUST NOT RESTART, and this is the whole hazard. `seq` is
        `INTEGER PRIMARY KEY AUTOINCREMENT`, so a new file begins at 1 -- and
        `core/compactor.py` stores `log_seq` on every L2 fact and uses it three
        ways: `erased_seqs()` compares tombstoned seqs to decide what the owner
        removed, `verify()` keys the L2-vs-L3 comparison on it, and `project()`
        carries it. With numbering restarted, a tombstone for seq 42 in segment
        one would silently erase a DIFFERENT record at seq 42 in segment two:
        not data loss, which is visible, but the wrong deletion succeeding
        quietly.

        So the new segment's `sqlite_sequence` is seeded past the old maximum.
        SQLite exposes exactly that table for exactly this.
        """
        if store not in APPEND_ONLY:
            raise ValueError(
                f"{store!r} is not append-only, so it does not grow without "
                "bound and rotating it would only scatter it")
        with self._lock:
            conn = self._conns[store]
            high = int(conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM records").fetchone()[0])
            if high == 0:
                return {"store": store, "rotated": False,
                        "reason": "empty; nothing to rotate"}
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            live = self.root / f"{store}.db"
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            seg = self.root / f"{store}-seg{stamp}-to{high}.db"
            live.rename(seg)
            # The WAL and shm files belong to the segment, not to the new live
            # store. Leaving them behind hands a fresh database someone else's
            # journal.
            for suffix in ("-wal", "-shm"):
                stray = live.with_name(live.name + suffix)
                if stray.exists():
                    stray.rename(seg.with_name(seg.name + suffix))
            self._conns[store] = self._open(store)
            self._migrate_one(store)
            # SEEDED PAST THE OLD MAXIMUM, so `seq` keeps meaning one thing
            # across the whole history rather than one thing per file.
            # `sqlite_sequence` carries no UNIQUE constraint, so there is no
            # upsert to bind to; it is also empty until the first insert, which
            # is exactly the state a fresh segment is in.
            seeded = self._conns[store]
            seeded.execute("DELETE FROM sqlite_sequence WHERE name='records'")
            seeded.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES('records', ?)",
                (high,))
        return {"store": store, "rotated": True, "segment": seg.name,
                "seq_high_water": high,
                "note": ("the previous file is kept whole and unmodified; the "
                         "new one continues the sequence rather than "
                         "restarting it")}

    def _open(self, name: str) -> sqlite3.Connection:
        path = self.root / f"{name}.db"
        c = sqlite3.connect(str(path), timeout=30.0, isolation_level=None,
                            check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(f"PRAGMA synchronous={'FULL' if name in SYNC_FULL else 'NORMAL'}")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _migrate(self) -> None:
        for name in STORES:
            self._migrate_one(name)

    def _migrate_one(self, name: str) -> None:
        """The schema for one store. Split out of `_migrate` so a rotated
        segment's replacement gets the same tables, indexes and append-only
        triggers as the file it replaces -- a fresh log without the BEFORE
        triggers would be an append-only store that is not."""
        if True:
            c = self._conns[name]
            c.execute("""CREATE TABLE IF NOT EXISTS records (
                             seq INTEGER PRIMARY KEY AUTOINCREMENT,
                             kind TEXT NOT NULL,
                             body TEXT NOT NULL,
                             hlc_physical_ms INTEGER NOT NULL,
                             hlc_logical INTEGER NOT NULL,
                             hlc_node_id TEXT NOT NULL,
                             lease_epoch INTEGER NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_records_kind ON records(kind)")
            # The total order, materialised as an index. Reading the log in HLC
            # order must not require sorting in Python -- a replay that sorts in
            # memory cannot replay a log larger than memory.
            c.execute("""CREATE INDEX IF NOT EXISTS ix_records_hlc
                         ON records(hlc_physical_ms, hlc_logical, hlc_node_id)""")
            if name in APPEND_ONLY:
                for op in ("UPDATE", "DELETE"):
                    c.execute(f"""CREATE TRIGGER IF NOT EXISTS no_{op.lower()}_records
                                  BEFORE {op} ON records
                                  BEGIN SELECT RAISE(ABORT,
                                      'append-only store: {op} refused at the storage layer (ADR-002 D9)');
                                  END""")

        # Leased domains live in `state`. One row per domain, and the epoch on
        # that row is the fence every write to the domain is checked against.
        s = self._conns["state"]
        s.execute("""CREATE TABLE IF NOT EXISTS leased_domain (
                         domain TEXT PRIMARY KEY,
                         epoch INTEGER NOT NULL,
                         holder TEXT,
                         state TEXT NOT NULL,
                         updated_hlc_physical_ms INTEGER NOT NULL,
                         updated_hlc_logical INTEGER NOT NULL,
                         updated_hlc_node_id TEXT NOT NULL)""")
        # Keyed current-value store, fenced by domain epoch.
        s.execute("""CREATE TABLE IF NOT EXISTS domain_state (
                         domain TEXT NOT NULL,
                         key TEXT NOT NULL,
                         body TEXT NOT NULL,
                         written_by_epoch INTEGER NOT NULL,
                         hlc_physical_ms INTEGER NOT NULL,
                         hlc_logical INTEGER NOT NULL,
                         hlc_node_id TEXT NOT NULL,
                         PRIMARY KEY (domain, key))""")
        for d in DOMAINS:
            s.execute("""INSERT OR IGNORE INTO leased_domain
                         VALUES (?, 0, NULL, 'UNOWNED', 0, 0, ?)""", (d, self.node_id))

        # Runtime lifecycle metadata -- the clean-shutdown flag and similar.
        # SEPARATE FROM domain_state ON PURPOSE. It first lived under the
        # `tasks` domain, which meant `TaskStore.all()` handed a non-task row to
        # Task.from_dict and every restart crashed on KeyError: 'task_id'. The
        # deeper problem was conceptual: runtime metadata is not a leased-domain
        # entity, it is not fenced by a task epoch, and it must stay writable
        # during shutdown while leases are being released.
        s.execute("""CREATE TABLE IF NOT EXISTS runtime_meta (
                         key TEXT PRIMARY KEY,
                         body TEXT NOT NULL)""")

    # ---------------------------------------------------------------- append

    def append(self, store: str, kind: str, body: dict, at: HLC,
               lease_epoch: int = 0) -> int:
        """Append one record. Returns its sequence number."""
        if store not in STORES:
            raise ValueError(f"unknown store {store!r}")
        with self._lock:
            cur = self._conns[store].execute(
                """INSERT INTO records
                   (kind, body, hlc_physical_ms, hlc_logical, hlc_node_id, lease_epoch)
                   VALUES (?,?,?,?,?,?)""",
                (kind, json.dumps(body, sort_keys=True), at.physical_ms, at.logical,
                 at.node_id, lease_epoch),
            )
            return int(cur.lastrowid)

    def _rows(self, store: str, q: str, args: list):
        """Rows from every segment of a store, oldest segment first.

        A SEGMENT IS OPENED READ-ONLY AND CLOSED AGAIN. Holding a handle on
        every archive would make a long-running VESPER keep the whole history
        open; opening on demand costs a file open per read of a rotated store,
        which is the trade this makes deliberately.
        """
        for path in self.segments(store)[:-1]:
            if not path.exists():
                continue
            c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                                timeout=30.0, check_same_thread=False)
            try:
                zdict = self._is_compressed(c)
                if zdict is None:
                    yield from c.execute(q, args)
                else:
                    # ONE RECORD AT A TIME, which is the whole point of
                    # compressing per record: the caller reads what it asked
                    # for and nothing is unpacked that nobody wanted.
                    for row in c.execute(q, args):
                        row = list(row)
                        row[2] = self._inflate(bytes(row[2]), zdict)
                        yield tuple(row)
            finally:
                c.close()
        yield from self._conns[store].execute(q, args)

    def read(self, store: str, *, kind: str | None = None,
             after_seq: int = 0, limit: int | None = None) -> Iterator[Record]:
        """Read in HLC order — the total order, not insertion order.

        These differ whenever a record arrives from another node out of order,
        which is precisely the case the world model has to get right.
        """
        q = ("SELECT seq, kind, body, hlc_physical_ms, hlc_logical, hlc_node_id, lease_epoch "
             "FROM records WHERE seq > ?")
        args: list[Any] = [after_seq]
        if kind is not None:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY hlc_physical_ms, hlc_logical, hlc_node_id"
        if limit is not None:
            q += " LIMIT ?"
            args.append(limit)
        # ACROSS EVERY SEGMENT, oldest first. A read that saw only the live
        # file would report the log as beginning at the last rotation -- and
        # `verify_a029_from_log.py`, `Compactor.project` and every replay would
        # quietly agree with it, because none of them has any other source of
        # truth to notice the difference against.
        for row in self._rows(store, q, args):
            yield Record(row[0], row[1], json.loads(row[2]),
                         HLC(row[3], row[4], row[5]), row[6])

    def record(self, store: str, seq: int) -> "Record | None":
        """One record by sequence number. None if there is no such record.

        A POINT LOOKUP, NOT A SCAN. `read()` is the only other way in and it
        walks the log in HLC order to find one row -- fine for a replay, and
        O(log size) per citation when the caller is resolving evidence, which is
        the one place it gets called once per claim.

        CITED BY `seq`, WHICH IS THE PRIMARY KEY AND NEVER MOVES. A later reader
        will be tempted to make this an HLC lookup because HLC is the total
        order everywhere else. It must not be: `INV-COORD-4` says the clock
        orders, and a citation does not want an order -- it wants the one
        immutable identity of the record it names. Two records can share an HLC
        physical millisecond; none can share a seq.
        """
        # THROUGH `_rows`, LIKE `read()`, AND FOR THE SAME REASON. This used to
        # query `self._conns[store]` -- the LIVE file only -- so the moment a
        # segment rotated out, every citation into it resolved to None. Measured
        # 2026-09-03 against the real archive: 1,896,415 records had rotated and
        # `record("log", 1)` returned None, as did seq 500,000 and the segment's
        # own last record.
        #
        # A CITATION THAT RESOLVES TO NOTHING IS WORSE THAN ONE THAT ERRORS.
        # `memory-citations-resolve-or-are-withheld` withholds a claim whose
        # support cannot be fetched, so this did not produce a wrong answer --
        # it silently retired the evidence for everything older than the last
        # rotation, which is most of the history and all of the part worth
        # citing.
        #
        # It was also the read path that could not see a COMPRESSED body:
        # `json.loads` on a zlib blob raises, where `_rows` inflates per record
        # against the archive's own dictionary. So compression made archived
        # citations fail twice over, and the sequential path -- the one the
        # check exercises -- was fine throughout.
        q = ("SELECT seq, kind, body, hlc_physical_ms, hlc_logical, "
             "hlc_node_id, lease_epoch FROM records WHERE seq = ?")
        for row in self._rows(store, q, [int(seq)]):
            return Record(row[0], row[1], json.loads(row[2]),
                          HLC(row[3], row[4], row[5]), row[6])
        return None

    def count(self, store: str, kind: str | None = None) -> int:
        if kind is None:
            return int(self._conns[store].execute(
                "SELECT count(*) FROM records").fetchone()[0])
        return int(self._conns[store].execute(
            "SELECT count(*) FROM records WHERE kind=?", (kind,)).fetchone()[0])

    def try_mutate_append_only(self, store: str) -> None:
        """Deliberately attempt an UPDATE against an append-only store.

        Exists so the guard can be ASSERTED rather than assumed. A protection
        nobody ever tries to breach is a protection nobody has verified.
        """
        if store not in APPEND_ONLY:
            raise ValueError(f"{store!r} is not an append-only store")
        try:
            self._conns[store].execute("UPDATE records SET kind='tamper' WHERE seq=1")
        except sqlite3.Error as e:
            raise AppendOnlyViolation(str(e)) from e
        raise AssertionError(
            f"append-only guard on '{store}' DID NOT FIRE -- ADR-002 D9 is not enforced")

    # ---------------------------------------------------------------- leases

    def domain_epoch(self, domain: str) -> int:
        row = self._conns["state"].execute(
            "SELECT epoch FROM leased_domain WHERE domain=?", (domain,)).fetchone()
        if row is None:
            raise ValueError(f"unknown domain {domain!r}")
        return int(row[0])

    def domain_holder(self, domain: str) -> tuple[str | None, str, int]:
        row = self._conns["state"].execute(
            "SELECT holder, state, epoch FROM leased_domain WHERE domain=?",
            (domain,)).fetchone()
        if row is None:
            raise ValueError(f"unknown domain {domain!r}")
        return row[0], row[1], int(row[2])

    def claim_domain(self, domain: str, holder: str, at: HLC) -> int:
        """Take the lease by bumping the epoch. Returns the NEW epoch.

        Monotonic and never reused: the epoch is the fencing token, and a reused
        token would let a returning ex-owner's writes pass the fence.
        """
        with self._lock:
            c = self._conns["state"]
            c.execute("BEGIN IMMEDIATE")
            try:
                row = c.execute("SELECT epoch FROM leased_domain WHERE domain=?",
                                (domain,)).fetchone()
                if row is None:
                    raise ValueError(f"unknown domain {domain!r}")
                new_epoch = int(row[0]) + 1
                c.execute("""UPDATE leased_domain
                             SET epoch=?, holder=?, state='OWNED',
                                 updated_hlc_physical_ms=?, updated_hlc_logical=?,
                                 updated_hlc_node_id=?
                             WHERE domain=?""",
                          (new_epoch, holder, at.physical_ms, at.logical,
                           at.node_id, domain))
                c.execute("COMMIT")
                return new_epoch
            except Exception:
                c.execute("ROLLBACK")
                raise

    def release_domain(self, domain: str, at: HLC) -> None:
        with self._lock:
            self._conns["state"].execute(
                """UPDATE leased_domain SET holder=NULL, state='UNOWNED',
                       updated_hlc_physical_ms=?, updated_hlc_logical=?,
                       updated_hlc_node_id=?
                   WHERE domain=?""",
                (at.physical_ms, at.logical, at.node_id, domain))

    def fence_domain(self, domain: str, reason: str, at: HLC) -> None:
        with self._lock:
            self._conns["state"].execute(
                """UPDATE leased_domain SET state='FENCED',
                       updated_hlc_physical_ms=?, updated_hlc_logical=?,
                       updated_hlc_node_id=?
                   WHERE domain=?""",
                (at.physical_ms, at.logical, at.node_id, domain))
            del reason  # carried on the emitted control.fenced event, not here

    # ----------------------------------------------------------- fenced write

    def put_state(self, domain: str, key: str, body: dict, *,
                  lease_epoch: int, at: HLC) -> None:
        """Write to a leased domain under an epoch. THE fencing primitive.

        The guard and the write are ONE statement. Everything about
        INV-OWN-3 rests on that: a read-then-write leaves a window between the
        check and the write in which a competing writer can take the lease, and
        SPIKE-008's control build measured 119-3175 stale writes slipping
        through that window depending on the machine's speed. Here the
        `WHERE ... <= :epoch` and the `SET` commit or fail together.
        """
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}")
        payload = json.dumps(body, sort_keys=True)
        with self._lock:
            c = self._conns["state"]
            cur = c.execute(
                """INSERT INTO domain_state
                       (domain, key, body, written_by_epoch,
                        hlc_physical_ms, hlc_logical, hlc_node_id)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(domain, key) DO UPDATE SET
                       body=excluded.body,
                       written_by_epoch=excluded.written_by_epoch,
                       hlc_physical_ms=excluded.hlc_physical_ms,
                       hlc_logical=excluded.hlc_logical,
                       hlc_node_id=excluded.hlc_node_id
                   WHERE domain_state.written_by_epoch <= excluded.written_by_epoch""",
                (domain, key, payload, lease_epoch,
                 at.physical_ms, at.logical, at.node_id),
            )
            if cur.rowcount == 0:
                row = c.execute(
                    "SELECT written_by_epoch FROM domain_state WHERE domain=? AND key=?",
                    (domain, key)).fetchone()
                raise StaleEpochWrite(domain, lease_epoch, int(row[0]) if row else -1)

    def get_state(self, domain: str, key: str) -> dict | None:
        row = self._conns["state"].execute(
            "SELECT body FROM domain_state WHERE domain=? AND key=?",
            (domain, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put_meta(self, key: str, body: dict) -> None:
        """Runtime lifecycle metadata. NOT leased, NOT fenced, NOT domain state."""
        with self._lock:
            self._conns["state"].execute(
                "INSERT INTO runtime_meta VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET body=excluded.body",
                (key, json.dumps(body, sort_keys=True)))

    def get_meta(self, key: str) -> dict | None:
        row = self._conns["state"].execute(
            "SELECT body FROM runtime_meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_state(self, domain: str) -> list[tuple[str, dict]]:
        return [(k, json.loads(b)) for k, b in self._conns["state"].execute(
            "SELECT key, body FROM domain_state WHERE domain=? ORDER BY key", (domain,))]

    # --------------------------------------------------------------- lifecycle

    def checkpoint_wal(self) -> dict[str, int]:
        """Fold each WAL back into its .db so every store is self-contained.

        This is what makes the store set a PORTABLE ARTIFACT (ADR-002 D10). The
        SPIKE-008 portability control measured what happens without it: copying
        a live store loses its uncheckpointed tail -- 300 committed rows gone --
        while still opening cleanly and passing integrity_check.
        """
        out = {}
        with self._lock:
            for name in STORES:
                row = self._conns[name].execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                out[name] = int(row[1]) if row else -1
        return out

    def integrity(self) -> dict[str, str]:
        return {n: self._conns[n].execute(
            "PRAGMA integrity_check").fetchone()[0] for n in STORES}

    def close(self) -> None:
        with self._lock:
            for c in self._conns.values():
                c.close()
            self._conns.clear()

    def __enter__(self) -> "StoreSet":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
