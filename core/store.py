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
        for row in self._conns[store].execute(q, args):
            yield Record(row[0], row[1], json.loads(row[2]),
                         HLC(row[3], row[4], row[5]), row[6])

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
