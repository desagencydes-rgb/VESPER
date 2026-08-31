"""L2 — the graph projection of memory, inside SQLite.

WHAT THIS IS A PROJECTION *OF*, and why that word carries the design. L3
(`core/store.py`, store `log`) is the truth: append-only, HLC-ordered,
unbounded. L2 is a DERIVED VIEW of it and L1 is derived in turn.
`MEMORY_ARCHITECTURE.md` states the rule as "not dual-write — PROJECT", and the
failure it prevents is specific: a graph-first write interrupted between the two
stores leaves a fact with no provenance. That is `INV-EVID-2` broken, and broken
undetectably, because the surviving row looks exactly like a correct one.

So there is ONE write path. `remember()` appends to L3, takes the `seq` that
`append()` returns, and only then projects the row into L2 carrying that seq as
its pointer. There is deliberately no public method that writes a fact without a
seq. Making the ordering structural rather than documented is what stops a
subsystem written later — by someone who never read this — from getting it
backwards and having it work anyway.

`log_seq INTEGER NOT NULL` IS NOT THE GUARD, and mistaking it for one is the
easy error here. A `0`, a seq belonging to a different store, or a seq for a
record that was never written all satisfy NOT NULL. The guard is
`unresolved_pointers()`, which reads each pointer back out of L3 and returns the
rows that do not resolve. A constraint that checks only the SHAPE of a pointer
cannot tell a real one from a plausible one, and every wrong pointer here is
plausible.

TWO CLASSIFICATIONS, TWO COLUMNS, AND THEY ARE NOT THE SAME AXIS. This looked
like one field and is not:

    `privacy`     — may this LEAVE?      (`core/privacy.py`: public/personal/private)
    `trust_class` — may this be ACTED ON? (`core/taint.py`)

A sentence the owner spoke is maximally trusted and may be maximally private. A
retrieved web page is the reverse. Collapsing them silently loses whichever axis
the collapse did not keep — silently, because either column alone still renders
a plausible-looking row.

THE MEASURED SCHEMA IS COPIED. THE PROBE'S SELECT PREDICATE IS NOT.
`tools/spike/l2_query_probe.py` measured this schema, and the tables, the FTS5
configuration and the bounded recursive CTE are taken from it verbatim. Its
`WHERE f.privacy = 'private'` is not, and copying it would have been a live bug:
it admits only private facts, so a `personal` fact could never reach block B at
all. The probe needed a filter of stable cardinality to time and any constant
served — which is also why it used a privacy vocabulary (`private`/`shareable`)
that `core/privacy.py` does not define. A benchmark's predicate is part of the
benchmark, not part of the design, and this is the second time in this corpus
that an instrument's own convenience nearly became a contract.

`trust_class` IS A COLUMN THE PROBE DID NOT MEASURE. The ~18 ms over 100k facts
quoted in `MEMORY_ARCHITECTURE.md` describes the schema WITHOUT it. That figure
therefore does not describe what this file builds, and it is deliberately not
restated here as though it did (`INV-HW-2`). Re-run the probe against this
schema to get a number that describes the thing that actually exists.

SELECTION MAKES NO MODEL CALL. FTS5 plus a depth-bounded traversal, ordered by
authority rank and recency. That is what preserves the owner's founding
constraint: there is no recall EVENT, nothing waits on a retrieval hop, and a
self-initiated act with no user turn still gets a block B. What was rejected was
recall-as-a-round-trip, not selection.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from .hlc import HybridLogicalClock  # noqa: F401  (type reference only)
from .privacy import PRIVACY_CLASSES
from .taint import ALLOWED_LEVEL

# DF-MEMORY-AUTHORITY. Ordered: 1 wins. Rank 6 is in the vocabulary so that a
# model prior can be NAMED, never so that it can be stored — see MODEL_PRIOR.
AUTHORITY_RANKS = {
    1: "system_rule", 2: "source_of_record", 3: "current_observation",
    4: "user_statement", 5: "derived", 6: "model_prior",
}
MODEL_PRIOR = 6

# Block B holds 3-5 facts. The probe measured at 5 and this is that number, not
# a new one chosen here.
TOP_N = 5

# The depth bound is not politeness. Without it a walk from a hub — the owner,
# the current project — enumerates most of the graph, and personal memory is
# hub-shaped by nature rather than by accident.
MAX_DEPTH = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS entity(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact(
  id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, attribute TEXT NOT NULL,
  value TEXT NOT NULL, rank INTEGER NOT NULL, observed_at_hlc TEXT NOT NULL,
  privacy TEXT NOT NULL, trust_class TEXT NOT NULL, log_seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edge(
  src_id INTEGER NOT NULL, dst_id INTEGER NOT NULL, relation TEXT NOT NULL,
  weight REAL NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(
  value, attribute, content='fact', content_rowid='id', tokenize='porter');
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_name ON entity(name);
CREATE INDEX IF NOT EXISTS idx_fact_subject ON fact(subject_id);
CREATE INDEX IF NOT EXISTS idx_edge_src ON edge(src_id);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst_id);
CREATE INDEX IF NOT EXISTS idx_fact_rank ON fact(rank, log_seq DESC);
"""


class MemoryContractViolation(Exception):
    """A write that would leave memory unprovenanced, unranked or unclassified."""


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """One selected fact, carrying everything needed to cite it.

    `log_seq` is not decoration. `INV-EVID-2` needs a resolvable span, and this
    is it: the pointer back into L3 where the full exchange this was derived
    from still lives.
    """

    id: int
    subject: str
    attribute: str
    value: str
    rank: int
    privacy: str
    trust_class: str
    log_seq: int
    observed_at_hlc: str

    def to_dict(self) -> dict:
        return {"id": self.id, "subject": self.subject,
                "attribute": self.attribute, "value": self.value,
                "rank": self.rank, "authority": AUTHORITY_RANKS[self.rank],
                "privacy": self.privacy, "trust_class": self.trust_class,
                "log_seq": self.log_seq, "observed_at_hlc": self.observed_at_hlc}


def _classes_at_or_below(ceiling: str) -> tuple:
    """Every privacy class no more private than `ceiling`.

    `privacy.py` orders its classes least-private first, so this is a prefix of
    that tuple. Written as a lookup against the contract rather than as a
    comparison on strings, because a string comparison would silently start
    working on a vocabulary `privacy.py` does not define.
    """
    if ceiling not in PRIVACY_CLASSES:
        raise MemoryContractViolation(
            f"unknown privacy ceiling {ceiling!r}, expected {PRIVACY_CLASSES}. "
            "An unrecognised ceiling must refuse rather than default: the "
            "defaulting direction that looks natural is the permissive one.")
    return PRIVACY_CLASSES[:PRIVACY_CLASSES.index(ceiling) + 1]


class MemoryGraph:
    """L2. Written only by projection from L3, read without a model call."""

    def __init__(self, store: Any, path: str = ":memory:") -> None:
        self._store = store
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------------------------------------------------------------- writing

    def entity(self, name: str, kind: str) -> int:
        """Get or create an entity. Idempotent by name."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM entity WHERE name = ?", (name,)).fetchone()
            if row:
                return int(row[0])
            cur = self._conn.execute(
                "INSERT INTO entity(name, kind) VALUES(?,?)", (name, kind))
            self._conn.commit()
            return int(cur.lastrowid)

    def remember(self, *, subject: str, attribute: str, value: str, rank: int,
                 privacy: str, trust_class: str, at: Any,
                 subject_kind: str = "topic") -> MemoryFact:
        """The only way a fact enters L2. L3 first, always.

        THE ORDER IS THE POINT. `append()` returns the seq; the L2 row cannot be
        built before that call has happened, because the seq is one of its
        columns. An implementation that wrote L2 first and "filled the seq in
        after" would pass every test that checks the final state and would leave
        an unprovenanced row behind on any interruption.
        """
        if rank not in AUTHORITY_RANKS:
            raise MemoryContractViolation(
                f"rank {rank!r} not in DF-MEMORY-AUTHORITY {sorted(AUTHORITY_RANKS)}")
        if rank == MODEL_PRIOR:
            raise MemoryContractViolation(
                "INV-EVID-1: a model prior may not be asserted into memory. The "
                "extractor's READING of an utterance is rank 5 (derived); the "
                "utterance itself is rank 4. Storing a prior as though it were "
                "either is how a system promotes its own guesses to the owner's "
                "word — permanently, and with nothing to see afterwards.")
        if privacy not in PRIVACY_CLASSES:
            raise MemoryContractViolation(
                f"privacy {privacy!r} not in {PRIVACY_CLASSES} (core/privacy.py "
                "owns this vocabulary; L2 does not define its own)")
        # VALIDATED AGAINST `core/taint.py`, WHICH OWNS THIS VOCABULARY, and it
        # was not until 2026-08-30. Before that this only checked the string was
        # non-empty, and every caller in this repository duly invented one:
        # `owner_utterance`, `extractor_reading`, `compaction`, `calendar`.
        #
        # THE CONSEQUENCE WAS THE OPPOSITE OF THE INTENT. `taint._weakest()`
        # maps an unknown class to rank 0 -- fail-closed, and correct -- so
        # `owner_utterance` ranked as LESS trusted than `retrieved_external`,
        # and the owner's own words were the least trusted thing in any set
        # containing them. Meanwhile nothing in memory ever carried
        # `retrieved_external`, so `INV-AUTH-6` -- that class must never reach
        # the planner context -- had nothing to act on.
        #
        # This is the same defect as `l2_query_probe.py` inventing
        # `private`/`shareable`, and as `host_health()` inventing
        # `nominal`/`constrained`. Three times in one night, each time because
        # the invented value looked reasonable on its own.
        if trust_class not in ALLOWED_LEVEL:
            raise MemoryContractViolation(
                f"trust_class {trust_class!r} is not in core/taint.py's "
                f"vocabulary {sorted(ALLOWED_LEVEL)}. An invented class ranks "
                "BELOW retrieved_external under `_weakest`, so it makes the "
                "content it labels the least trusted thing present -- and it "
                "makes INV-AUTH-6 unenforceable, because the class it names "
                "never appears.")

        body = {"subject": subject, "attribute": attribute, "value": value,
                "rank": rank, "privacy": privacy, "trust_class": trust_class}
        seq = int(self._store.append("log", "memory.fact", body, at))

        subject_id = self.entity(subject, subject_kind)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO fact(subject_id, attribute, value, rank,
                                    observed_at_hlc, privacy, trust_class, log_seq)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (subject_id, attribute, value, rank, str(at), privacy,
                 trust_class, seq))
            fact_id = int(cur.lastrowid)
            # External-content FTS5: the index does not follow the base table on
            # its own. The probe rebuilt in bulk, which is right for a benchmark
            # and wrong for incremental writes — a missed row here is invisible
            # until a search silently fails to find something that is present.
            self._conn.execute(
                "INSERT INTO fact_fts(rowid, value, attribute) VALUES(?,?,?)",
                (fact_id, value, attribute))
            self._conn.commit()

        return MemoryFact(id=fact_id, subject=subject, attribute=attribute,
                          value=value, rank=rank, privacy=privacy,
                          trust_class=trust_class, log_seq=seq,
                          observed_at_hlc=str(at))

    def relate(self, src: str, relation: str, dst: str, *, weight: float = 1.0,
               kind: str = "topic") -> None:
        """An edge between two entities. Traversal reads these, never facts."""
        src_id, dst_id = self.entity(src, kind), self.entity(dst, kind)
        with self._lock:
            self._conn.execute(
                "INSERT INTO edge(src_id, dst_id, relation, weight) VALUES(?,?,?,?)",
                (src_id, dst_id, relation, weight))
            self._conn.commit()

    # ---------------------------------------------------------------- reading

    def select(self, terms: list, *, ceiling: str = "private",
               depth: int = 2, limit: int = TOP_N) -> list:
        """Block B. FTS5, then bounded traversal, then authority order.

        No model call and no round trip. The privacy filter is a ceiling rather
        than an equality — see this module's header for why the probe's
        `privacy = 'private'` was not carried over.
        """
        if depth < 0 or depth > MAX_DEPTH:
            raise MemoryContractViolation(
                f"depth {depth} outside 0..{MAX_DEPTH}; an unbounded walk from a "
                "hub enumerates the graph")
        allowed = _classes_at_or_below(ceiling)
        if not terms:
            return []
        match = " OR ".join(t for t in terms if t.strip())
        if not match:
            return []
        holes = ",".join("?" * len(allowed))
        with self._lock:
            rows = self._conn.execute(f"""
                WITH hit AS (
                  SELECT f.id, f.subject_id, bm25(fact_fts) AS score
                    FROM fact_fts JOIN fact f ON f.id = fact_fts.rowid
                   WHERE fact_fts MATCH ?
                   ORDER BY score LIMIT 100
                ),
                reach(id, d) AS (
                  SELECT subject_id, 0 FROM hit
                  UNION
                  SELECT e.dst_id, reach.d + 1 FROM edge e
                    JOIN reach ON e.src_id = reach.id
                   WHERE reach.d < ?
                )
                SELECT f.id, en.name, f.attribute, f.value, f.rank, f.privacy,
                       f.trust_class, f.log_seq, f.observed_at_hlc
                  FROM fact f
                  -- DISTINCT, and it is not tidiness. `reach` is UNION-ed on
                  -- (id, d), so an entity reached at depth 0 AND at depth 1 is
                  -- two rows, and this join then returns each of its facts
                  -- twice. Block B holds 3-5 facts; filling two of those slots
                  -- with the same fact is worse than returning four. The probe
                  -- this query came from could not see it -- `stage_full`
                  -- counted rows, and the duplicate count looked like a hit.
                  JOIN (SELECT DISTINCT id FROM reach) r ON f.subject_id = r.id
                  JOIN entity en ON en.id = f.subject_id
                  -- THE SCORE WAS COMPUTED AND THROWN AWAY. `hit` ranks by
                  -- bm25 and the old ORDER BY used authority alone, so a fact
                  -- that ANSWERED the question lost every slot to facts that
                  -- merely outranked it. Measured 2026-08-31: asked when Sami
                  -- goes to school, block B returned five `owner/said` rows at
                  -- rank 4 and left `sami/school_day` at rank 5 out entirely --
                  -- the fact was in memory and could not be retrieved.
                  --
                  -- AUTHORITY AND RELEVANCE ANSWER DIFFERENT QUESTIONS, and
                  -- conflating them is the defect. Authority decides which of
                  -- two CONFLICTING facts to believe, and `core/arbiter.py`
                  -- still does that untouched. Relevance decides which few
                  -- facts are worth the block's slots. Ordering the second by
                  -- the first means the most authoritative facts crowd out the
                  -- ones that were actually asked about -- and `owner` is a hub,
                  -- so every `said` row is reachable from any owner fact.
                  LEFT JOIN hit ON hit.id = f.id
                 WHERE f.privacy IN ({holes})
                 ORDER BY (hit.id IS NULL) ASC,   -- direct matches before hub siblings
                          hit.score ASC,          -- then how well they matched
                          f.rank ASC,             -- then authority
                          f.log_seq DESC          -- then recency
                 LIMIT ?""",
                (match, depth, *allowed, limit)).fetchall()
        return [MemoryFact(id=r[0], subject=r[1], attribute=r[2], value=r[3],
                           rank=r[4], privacy=r[5], trust_class=r[6],
                           log_seq=r[7], observed_at_hlc=r[8]) for r in rows]

    def index(self, *, limit: int = 40) -> list:
        """Block A. What memory CONTAINS, never what it says.

        ~15 tokens a node instead of the facts themselves. This is what keeps
        absence non-silent: without it a dropped fact leaves VESPER CONFIDENTLY
        ignorant, which produces no event and cannot be noticed. A miss can be.
        """
        with self._lock:
            rows = self._conn.execute("""
                SELECT en.name, en.kind, COUNT(*), MAX(f.log_seq)
                  FROM fact f JOIN entity en ON en.id = f.subject_id
              GROUP BY f.subject_id
              ORDER BY COUNT(*) DESC
                 LIMIT ?""", (limit,)).fetchall()
        return [{"node": r[0], "kind": r[1], "facts": r[2], "pointer": r[3]}
                for r in rows]

    # ------------------------------------------------------------ the guard

    def unresolved_pointers(self) -> list:
        """Every L2 fact whose `log_seq` does not resolve to an L3 record.

        THE CHECK THAT NOT NULL CANNOT MAKE. This reads the pointer back out of
        L3 rather than inspecting its shape, because every wrong pointer in this
        schema is a well-formed integer. An empty list is the only acceptable
        result, and a non-empty one means memory is asserting things it cannot
        show the origin of.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, log_seq FROM fact").fetchall()
        live = {r.seq for r in self._store.read("log", kind="memory.fact")}
        return [{"fact_id": i, "log_seq": s} for i, s in rows if s not in live]

    def counts(self) -> dict:
        with self._lock:
            return {t: int(self._conn.execute(
                f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                for t in ("entity", "fact", "edge")}
