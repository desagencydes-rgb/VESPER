#!/usr/bin/env python3.13
"""Is L2 fast enough to sit on every turn's critical path?

WHAT IS AT STAKE. The revised L1 puts block B -- the few facts this turn needs
-- in front of the question, selected by an L2 query rather than by a model.
That query therefore runs on EVERY turn, before the model call, and its cost is
added to a conversational latency budget of 1,200 ms whose fast rung already
answers in ~420 ms. A 200 ms selector would cost more than the difference
between the fastest and slowest provider on the ladder.

WHAT IS ACTUALLY AT RISK, which is not the part people assume. The full-text
match is not the danger; FTS5 is an inverted index and answers in microseconds.
The danger is the two stages after it:

  * TRAVERSAL -- a recursive CTE whose cost is depth x fanout. Personal memory
    has hubs (the owner, the current project) with degree in the hundreds, and
    a depth-3 walk through a hub visits a large fraction of the graph.
  * RANKING -- ordering thousands of candidates to take five.

Both are measured separately below, because a single end-to-end number would
hide which one to fix.

THE NEGATIVE CONTROL IS THE UNINDEXED RUN. A benchmark that is fast can be fast
because the index works or because the dataset is small enough that a table
scan is also fast -- and at 10^4 rows a scan IS fast. Dropping the indexes and
re-running is what distinguishes them. If the unindexed timing matches the
indexed one, this probe is measuring nothing and its headline is meaningless.

Stdlib only.
"""
from __future__ import annotations

import random
import sqlite3
import statistics
import sys
import time

SCALES = [10_000, 100_000]
TOP_N = 5              # block B holds 3-5 facts
DEPTHS = [1, 2, 3]
REPEATS = 60

SCHEMA = """
CREATE TABLE entity(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE fact(
  id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, attribute TEXT NOT NULL,
  value TEXT NOT NULL, rank INTEGER NOT NULL, observed_at_hlc TEXT NOT NULL,
  privacy TEXT NOT NULL, log_seq INTEGER NOT NULL);
CREATE TABLE edge(
  src_id INTEGER NOT NULL, dst_id INTEGER NOT NULL, relation TEXT NOT NULL,
  weight REAL NOT NULL);
CREATE VIRTUAL TABLE fact_fts USING fts5(
  value, attribute, content='fact', content_rowid='id', tokenize='porter');
"""

INDEXES = """
CREATE INDEX idx_fact_subject ON fact(subject_id);
CREATE INDEX idx_edge_src ON edge(src_id);
CREATE INDEX idx_edge_dst ON edge(dst_id);
CREATE INDEX idx_fact_rank ON fact(rank, log_seq DESC);
"""

# VOCABULARY SIZE IS THE VARIABLE THIS BENCHMARK IS MOST SENSITIVE TO, and the
# first version of this file got it wrong. With a 34-word vocabulary every query
# term matched ~30% of rows, an OR of four terms matched almost everything, and
# the "full-text match" timing was really the cost of ranking most of the table.
# That is a property of the generator, not of FTS5 or of memory.
#
# Real personal memory has a long tail: a few very common terms (the owner's
# name, "meeting", today's project) and thousands of rare ones. Zipf gives that
# shape, and it is what decides whether a term selects 0.5% of rows or 30%.
CORE = ("router latency memory alarm calendar node battery quota provider "
        "budget spike contract invariant transcript compaction owner project "
        "meeting flight laptop schedule proposal review deadline gateway "
        "credential vault sensor trigger persona voice ledger placement").split()


def make_vocab(rng, size=6000):
    """CORE terms stay common; the rest are the rare tail."""
    tail = [f"{rng.choice('bcdfghjklmnpqrstvw')}{rng.choice('aeiou')}"
            f"{rng.choice('bcdfglmnprstv')}{rng.choice('aeiou')}{i}"
            for i in range(size)]
    return CORE, tail


def zipf_pick(rng, core, tail):
    """~25% of tokens from the small common set, 75% from the long tail."""
    return rng.choice(core) if rng.random() < 0.25 else rng.choice(tail)


WORDS = CORE     # kept for the attribute column, which IS low-cardinality


def build(conn: sqlite3.Connection, n_facts: int, rng: random.Random) -> dict:
    """A graph with HUBS, because a uniform-degree graph is the easy case.

    Real personal memory is not uniform: the owner, the current project and
    today's machine attract most edges. Traversal cost is dominated by whether
    a walk passes through one of those, so a benchmark built on uniform degree
    measures a graph nobody has and reports a traversal cost nobody will pay.
    5% of entities are hubs here and take ~60% of the edges.
    """
    n_ent = max(200, n_facts // 12)
    core, tail = make_vocab(rng)
    conn.executescript(SCHEMA)
    kinds = ("person", "project", "place", "device", "topic", "event")
    conn.executemany("INSERT INTO entity(id,name,kind) VALUES(?,?,?)",
                     [(i, f"{rng.choice(kinds)}_{i}", rng.choice(kinds))
                      for i in range(1, n_ent + 1)])

    hubs = list(range(1, max(2, n_ent // 20) + 1))
    facts = []
    for i in range(1, n_facts + 1):
        subj = rng.choice(hubs) if rng.random() < 0.45 else rng.randint(1, n_ent)
        text = " ".join(zipf_pick(rng, core, tail)
                        for _ in range(rng.randint(8, 22)))
        facts.append((i, subj, rng.choice(WORDS), text,
                      rng.choice((2, 3, 4, 4, 5)), f"hlc:{i}:{rng.randint(0,9)}",
                      rng.choice(("private", "private", "private", "shareable")), i))
    conn.executemany(
        "INSERT INTO fact(id,subject_id,attribute,value,rank,observed_at_hlc,"
        "privacy,log_seq) VALUES(?,?,?,?,?,?,?,?)", facts)

    n_edges = n_facts // 2
    edges = []
    for _ in range(n_edges):
        src = rng.choice(hubs) if rng.random() < 0.6 else rng.randint(1, n_ent)
        edges.append((src, rng.randint(1, n_ent),
                      rng.choice(("knows", "part_of", "at", "about", "owns")),
                      round(rng.random(), 3)))
    conn.executemany("INSERT INTO edge(src_id,dst_id,relation,weight) "
                     "VALUES(?,?,?,?)", edges)
    conn.execute("INSERT INTO fact_fts(fact_fts) VALUES('rebuild')")
    conn.commit()
    return {"entities": n_ent, "facts": n_facts, "edges": n_edges,
            "hubs": len(hubs), "core": core, "tail": tail}


def timed(fn, repeats: int = REPEATS) -> tuple[float, float, int]:
    """Median and p95 in ms. THE MEDIAN IS NOT THE INTERESTING NUMBER -- a
    selector on every turn is felt at its tail, so p95 is what the budget must
    survive."""
    xs, rows = [], 0
    for _ in range(repeats):
        t = time.perf_counter()
        rows = fn()
        xs.append((time.perf_counter() - t) * 1000)
    xs.sort()
    return statistics.median(xs), xs[int(len(xs) * 0.95)], rows


def stage_fts(conn, seed_terms):
    def run():
        q = " OR ".join(seed_terms)
        return len(conn.execute(
            "SELECT rowid FROM fact_fts WHERE fact_fts MATCH ? "
            "ORDER BY bm25(fact_fts) LIMIT 200", (q,)).fetchall())
    return run


def stage_traverse(conn, start_ids, depth):
    def run():
        # Bounded recursive CTE. The depth bound is not politeness: without it
        # a walk from a hub enumerates most of the graph.
        return len(conn.execute(f"""
            WITH RECURSIVE reach(id, d) AS (
              SELECT value, 0 FROM json_each(?)
              UNION
              SELECT e.dst_id, reach.d + 1 FROM edge e
                JOIN reach ON e.src_id = reach.id
               WHERE reach.d < {depth}
            )
            SELECT DISTINCT id FROM reach""",
            (__import__("json").dumps(start_ids),)).fetchall())
    return run


def stage_full(conn, seed_terms, depth):
    def run():
        q = " OR ".join(seed_terms)
        return len(conn.execute(f"""
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
               WHERE reach.d < {depth}
            )
            SELECT f.id, f.value, f.rank
              FROM fact f
              JOIN reach r ON f.subject_id = r.id
             WHERE f.privacy = 'private'
             ORDER BY f.rank ASC, f.log_seq DESC
             LIMIT {TOP_N}""", (q,)).fetchall())
    return run


def main() -> int:
    rng = random.Random(7)
    print(f"{'scale':>8} {'stage':<26} {'median':>9} {'p95':>9}  rows")
    print("-" * 66)
    for n in SCALES:
        conn = sqlite3.connect(":memory:")
        meta = build(conn, n, rng)
        conn.executescript(INDEXES)
        conn.commit()
        seeds = [zipf_pick(rng, meta["core"], meta["tail"]) for _ in range(4)]
        seeds_worst = rng.sample(meta["core"], 4)   # all-common: the worst case
        starts = list(range(1, 6))

        m, p, r = timed(stage_fts(conn, seeds))
        print(f"{n:>8} {'1 full-text match':<26} {m:>7.2f}ms {p:>7.2f}ms  {r}")
        m, p, r = timed(stage_fts(conn, seeds_worst))
        print(f"{n:>8} {'1w  same, all-common terms':<26} {m:>7.2f}ms {p:>7.2f}ms  {r}")
        for d in DEPTHS:
            m, p, r = timed(stage_traverse(conn, starts, d))
            print(f"{n:>8} {f'2 traverse depth {d}':<26} {m:>7.2f}ms {p:>7.2f}ms  {r}")
        for d in DEPTHS:
            m, p, r = timed(stage_full(conn, seeds, d))
            flag = "" if p < 10 else "   <-- OVER BUDGET"
            _ = flag
            print(f"{n:>8} {f'3 FULL select depth {d}':<26} {m:>7.2f}ms {p:>7.2f}ms  {r}{flag}")

        # NEGATIVE CONTROL: without the indexes, is it still this fast? If yes,
        # the indexes are not what is being measured and the numbers above mean
        # nothing.
        for stmt in ("DROP INDEX idx_fact_subject", "DROP INDEX idx_edge_src",
                     "DROP INDEX idx_edge_dst", "DROP INDEX idx_fact_rank"):
            conn.execute(stmt)
        conn.commit()
        m2, p2, _ = timed(stage_full(conn, seeds, 2), repeats=20)
        print(f"{n:>8} {'* control: NO indexes d2':<26} {m2:>7.2f}ms {p2:>7.2f}ms"
              f"   (indexed d2 above)")
        print(f"{'':>8} {'  entities/edges/hubs':<26} "
              f"{meta['entities']}/{meta['edges']}/{meta['hubs']}")
        print("-" * 66)
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
