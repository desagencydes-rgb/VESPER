"""The compactor — re-derives from the log, and never from its own last answer.

    WRONG   L1(n+1) = compact( L1(n) )
    RIGHT   L1(n+1) = project( L3 )

ONE CHARACTER OF DIFFERENCE IN THE FORMULA, AND IT KILLS FOUR PERMANENT FAILURE
MODES. Compacting the previous compaction is the natural implementation, it is
cheaper, and every one of these is silent:

    GENERATION DRIFT -- each pass is a translation of a translation. Meaning
    degrades with no hallucination anywhere and no step that looks wrong.

    POISONING -- one hallucination enters wearing an old memory's clothes and
    survives every later pass, because every later pass takes it as input.

    UNCORRECTABLE CORRECTIONS -- the owner says "no, it was Wednesday". If Y is
    baked into a summary, compressing further cannot un-bake it. Re-deriving
    from a log that CONTAINS the correction just works, with no special case.

    UNRECOVERABLE BUGS -- fix the compactor, re-project, done. Against a
    compact-the-compaction design the damage is in the only copy.

The cost is that projection reads more of L3 each time, which is what the
compactor's own gateway and its off-peak schedule are for.

REPROJECTION MUST NOT RESURRECT AN ERASURE, and a naive `project(L3)` does
exactly that. L3 is append-only -- verified at the storage layer, not by
convention -- so an erased fact's value is still in the log after `erase()` has
removed it from L2. Reading the log alone therefore brings it back, silently,
and the owner's erasure is undone by a maintenance pass. The projection is a
function of the log AND THE TOMBSTONES, and that is why `reproject()` reads both.

PRIVACY IS RECOMPUTED ON PROJECTION, NEVER INHERITED. `MEMORY_ARCHITECTURE.md`:
a compacted node inherits the MAXIMUM sensitivity of its inputs, and a check may
raise a classification but never lower it. This subsumes the aggregation failure
without needing to detect it -- three innocuous facts compacting into a security
profile is simply "the result was raised". You do not have to catch every
sensitive thing; you have to never classify downward.

THE SUMMARISER IS INJECTED AND OPTIONAL. It is the only part that needs a model.
Reprojection is fully deterministic, which is what makes the divergence property
(`verify()`) checkable without a network -- and divergence is failure mode 9:
"if projection is not a pure function of the log they disagree while the log
agrees."
"""

from __future__ import annotations

from typing import Any, Callable

from .memory import MODEL_PRIOR, MemoryGraph
from .privacy import PRIVACY_CLASSES

FACT_KIND = "memory.fact"
ERASED_KIND = "memory.erased"


def strictest(classes: list) -> str:
    """The most private class present. Monotonic: this only ever goes up.

    `PRIVACY_CLASSES` is ordered least-private first, so "maximum sensitivity"
    is the highest index. Written against that contract rather than as a string
    comparison, because a string comparison would keep working on a vocabulary
    `core/privacy.py` does not define and would order it alphabetically.
    """
    known = [c for c in classes if c in PRIVACY_CLASSES]
    if not known:
        # NOT AN ERROR AND NOT public. Unlabelled content is private -- the same
        # default the egress choke point takes, and for the same reason: the
        # permissive reading is the one that cannot be undone.
        return "private"
    return max(known, key=PRIVACY_CLASSES.index)


class Compactor:
    """Rebuilds L2 from L3, and compacts nodes by re-deriving them."""

    def __init__(self, memory: MemoryGraph, store: Any, clock: Any, *,
                 bus: Any = None, summariser: Callable | None = None) -> None:
        self._memory = memory
        self._store = store
        self._clock = clock
        self._bus = bus
        self._summariser = summariser

    # ------------------------------------------------------------ projection

    def erased_seqs(self) -> set:
        """Log sequences the owner has erased. Read from the tombstones."""
        return {int(r.body["log_seq"])
                for r in self._store.read("tombstones", kind=ERASED_KIND)
                if r.body.get("log_seq") is not None}

    def project(self) -> list:
        """What L2 SHOULD contain, derived from L3. Pure; writes nothing.

        Separated from `reproject()` on purpose: a function that computes the
        answer and a function that installs it are different things to test, and
        `verify()` needs the first without the second.
        """
        erased = self.erased_seqs()
        out = []
        for rec in self._store.read("log", kind=FACT_KIND):
            if rec.seq in erased:
                continue                 # the owner removed this; it stays gone
            b = rec.body
            if int(b.get("rank", MODEL_PRIOR)) == MODEL_PRIOR:
                continue                 # INV-EVID-1, applied at projection too
            out.append({"subject": b["subject"], "attribute": b["attribute"],
                        "value": b["value"], "rank": int(b["rank"]),
                        "privacy": b["privacy"],
                        "trust_class": b["trust_class"],
                        "log_seq": rec.seq})
        return out

    def verify(self) -> dict:
        """Is L2 exactly what the log projects? Failure mode 9, made checkable.

        `INV-PLACE-3` has VESPER joining and leaving nodes, and two nodes both
        append and both project. If projection is not a pure function of the
        log, they diverge while the log agrees -- and nothing anywhere would
        report it, because each node's L2 is internally consistent.
        """
        expected = {(f["subject"], f["attribute"], f["value"], f["log_seq"])
                    for f in self.project()}
        rows = self._memory._conn.execute(          # noqa: SLF001
            """SELECT en.name, f.attribute, f.value, f.log_seq
                 FROM fact f JOIN entity en ON en.id = f.subject_id""").fetchall()
        actual = {(r[0], r[1], r[2], r[3]) for r in rows}
        return {"converged": expected == actual,
                "missing_from_l2": sorted(expected - actual)[:20],
                "extra_in_l2": sorted(actual - expected)[:20],
                "expected": len(expected), "actual": len(actual)}

    def reproject(self) -> dict:
        """Rebuild L2 from L3. The recovery path, and the bug-fix path.

        DROPS AND REBUILDS rather than reconciling row by row. A reconciliation
        has to be correct about what to leave alone, and being wrong there is
        exactly the divergence this method exists to remove -- so it does not
        get the chance.
        """
        facts = self.project()
        # THE INDEX IS REBUILT FROM CONTENT, NEVER DELETED FROM ROW BY ROW, and
        # this is a repair function so it may not assume the thing it is
        # repairing is sane. `DELETE FROM fact_fts` on an external-content table
        # raises "database disk image is malformed" the moment the base table
        # and the index disagree -- which is one of the states this method
        # exists to recover FROM. Found by exactly that: a stray row inserted
        # into `fact` without its index entry, and the recovery path was the
        # thing that crashed.
        #
        # `rebuild` derives the whole index from the content table, so it cannot
        # be left inconsistent and cannot fail on finding an inconsistency.
        with self._memory._lock:                    # noqa: SLF001
            c = self._memory._conn                  # noqa: SLF001
            c.execute("DELETE FROM fact")
            c.execute("DELETE FROM edge")
            c.execute("DELETE FROM entity")
            c.execute("INSERT INTO fact_fts(fact_fts) VALUES('rebuild')")
            c.commit()
        for f in facts:
            sid = self._memory.entity(f["subject"], "topic")
            with self._memory._lock:                # noqa: SLF001
                self._memory._conn.execute(         # noqa: SLF001
                    """INSERT INTO fact(subject_id, attribute, value, rank,
                                        observed_at_hlc, privacy, trust_class,
                                        log_seq)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (sid, f["attribute"], f["value"], f["rank"],
                     f".{f['log_seq']}", f["privacy"], f["trust_class"],
                     f["log_seq"]))
        with self._memory._lock:                    # noqa: SLF001
            # ONE BULK REBUILD rather than a per-row insert. Same reason, plus
            # it is what the measuring probe did for 100k rows.
            self._memory._conn.execute(             # noqa: SLF001
                "INSERT INTO fact_fts(fact_fts) VALUES('rebuild')")
            self._memory._conn.commit()             # noqa: SLF001
        result = {"projected": len(facts), "erased_skipped": len(self.erased_seqs())}
        self._emit("memory.reprojected", result)
        return result

    # ------------------------------------------------------------ compaction

    def compact(self, subject: str, attribute: str) -> dict:
        """Re-derive one node from L3 and replace its facts with a summary.

        DERIVED IS RANK 5 AND THE INPUTS ARE NOT DELETED. A summary is the
        system's reading of the owner's words, which is rank 5 by
        `DF-MEMORY-AUTHORITY` however many rank-4 statements went into it --
        and the rank-4 originals stay in L3, which is what makes the next
        re-derivation possible and what makes this reversible.
        """
        inputs = [f for f in self.project()
                  if f["subject"] == subject and f["attribute"] == attribute]
        if not inputs:
            return {"outcome": "nothing to compact", "subject": subject}
        if self._summariser is None:
            return {"outcome": "no summariser", "subject": subject,
                    "inputs": len(inputs),
                    "note": ("compaction needs a model and reprojection does "
                             "not; the deterministic half works without one")}

        ceiling = strictest([f["privacy"] for f in inputs])
        text = self._summariser([f["value"] for f in inputs])
        fact = self._memory.remember(
            subject=subject, attribute=attribute, value=str(text),
            rank=5, privacy=ceiling, trust_class="compaction",
            at=self._clock.now())
        out = {"outcome": "compacted", "subject": subject, "attribute": attribute,
               "inputs": len(inputs), "privacy": ceiling,
               "input_classes": sorted({f["privacy"] for f in inputs}),
               "fact_id": fact.id,
               "note": ("privacy is the MAXIMUM of the inputs, recomputed and "
                        "never inherited: three innocuous facts compacting into "
                        "a security profile is just 'the result was raised'")}
        self._emit("memory.compacted", out)
        return out

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=str(payload.get("subject", "memory")),
                              payload=payload, component="compactor")
