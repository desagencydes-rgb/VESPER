"""The arbiter — what VESPER does when memory contradicts itself.

SEPARATE FROM THE UPDATER BECAUSE THE UPDATER CANNOT ASK A QUESTION. That is
the whole reason this is its own subsystem rather than a branch inside capture.
The updater runs in the background, after the act, and must never block or fail
a turn -- so it has no way to surface anything to the owner and no business
deciding what happens when two things it wrote disagree.

THE WORKED EXAMPLE, from `MEMORY_ARCHITECTURE.md`: the owner says the flight is
Tuesday (rank 4, user_statement); the calendar says Wednesday (rank 2,
source_of_record). Three outcomes are available and the third is the one people
forget exists:

    RESOLVED     rank settles it, and no 2/3/4 disagreement exists
    ASK          the ranks disagree -- surface it, never pick
    HOLD BOTH    keep the contradiction and act on NEITHER

THE THIRD IS A STATE VESPER SITS IN, which is exactly why this is a subsystem
and not a function. A system that must always produce an answer will produce a
wrong one here, confidently, and the owner has no way to see that it happened.

THE DECISION IS NOT MADE IN THIS FILE. `core/evidence.resolve_memory_conflict`
already implements `DF-MEMORY-AUTHORITY` and `INV-MEM-1`, was verified by A-003
and F1, and has been reachable from NOTHING in the runtime -- called only by an
acceptance runner. This module finds the contradictions in L2 and hands them to
it. Reimplementing the ladder here would give this corpus two rank tables that
would drift, and the one that drifted would be the one nobody was watching.

WHY A SILENT PICK IS A SPEC VIOLATION AND NOT A PREFERENCE. REM-010 4.6 calls
asking "the RB-002-compliant outcome and the specified default". The asymmetry
is the familiar one: a question costs the owner a moment, and a silent pick
costs whatever acting on the wrong flight time costs -- and produces no event, so
nobody learns it happened.

RANK 6 IS NOT A TIEBREAKER, and the resolver refuses it even when it is the only
candidate present -- which is precisely the moment it would otherwise get used.
"""

from __future__ import annotations

from typing import Any

from .evidence import Claim, LogReceipt, resolve_memory_conflict
from .memory import MemoryGraph

# The ranks whose disagreement must be surfaced rather than settled. Imported
# rather than restated: `core/evidence.py` owns this set.
from .evidence import MUST_ASK_RANKS


class Arbiter:
    """Finds contradictions in L2 and refuses to settle them quietly."""

    def __init__(self, memory: MemoryGraph, bus: Any = None) -> None:
        self._memory = memory
        self._bus = bus

    def contradictions(self, *, ceiling: str = "private") -> list:
        """Every (subject, attribute) holding more than one distinct value.

        GROUPED BY WHAT THE FACT IS ABOUT, not by when it arrived. Two values
        for `flight/departs` is a contradiction; two values for `owner/said` is
        a conversation. The attribute is what carries that distinction, which is
        why the updater's default attribute is `said` rather than something that
        would make every utterance contradict the last.

        SUPERSESSION IS NOT CONTRADICTION and this deliberately does not try to
        tell them apart. Nothing expires by deletion in this design -- staleness
        is a ranking input -- so an older value sitting beside a newer one is the
        normal state, and calling that a conflict would make every updated fact
        an interruption. What is returned here is a candidate set; the resolver
        decides, and rank plus HLC order is how it decides.
        """
        rows = self._memory._conn.execute(          # noqa: SLF001
            """SELECT en.name, f.attribute, COUNT(DISTINCT f.value) AS vals
                 FROM fact f JOIN entity en ON en.id = f.subject_id
             GROUP BY f.subject_id, f.attribute
               HAVING vals > 1
             ORDER BY vals DESC""").fetchall()
        return [{"subject": r[0], "attribute": r[1], "distinct_values": r[2]}
                for r in rows]

    def claims_for(self, subject: str, attribute: str) -> list:
        """The competing values, as `Claim`s the resolver understands.

        `memory_rank` CARRIES ACROSS UNCHANGED. The whole authority ladder is
        that number, and a translation layer that recomputed it -- however
        reasonably -- would be a second opinion about authority sitting between
        the store and the rule.
        """
        rows = self._memory._conn.execute(          # noqa: SLF001
            """SELECT f.value, f.rank, f.trust_class, f.log_seq
                 FROM fact f JOIN entity en ON en.id = f.subject_id
                WHERE en.name = ? AND f.attribute = ?
             ORDER BY f.rank ASC, f.log_seq DESC""",
            (subject, attribute)).fetchall()
        # SUPPORT IS A LOG RECEIPT, closing the gap this comment used to
        # record. The old note stood correctly for as long as `SourceSpan` was
        # the only span type: it is a byte range in a FILE, an L2 fact's
        # provenance is an L3 log SEQUENCE, and manufacturing a path from a seq
        # would have produced a citation that looks resolvable and is not --
        # worse than none, and what `INV-EVID-2` exists to refuse. The cost was
        # stated rather than discovered: `Claim.supported()` was False for every
        # memory-derived claim, so the arbiter could pick a winner and not cite
        # it. `LogReceipt` is the log-backed span the note asked for.
        #
        # THE RECEIPT QUOTES THE L2 VALUE AND RESOLVES AGAINST THE L3 RECORD,
        # which is the whole point and not a formality: those two are written by
        # different code paths, and a receipt whose quoted value is absent from
        # the record it names is memory that has drifted from its own log. A
        # receipt built only from the record would agree with itself and detect
        # nothing.
        #
        # A POINTER THAT DOES NOT RESOLVE YIELDS NO SUPPORT, not a receipt that
        # fails later. `memory.py`'s header is explicit that `NOT NULL` cannot
        # tell a real seq from a plausible one, so the arbiter reads it back
        # here and an unresolvable pointer leaves the claim unsupported -- which
        # `ClaimChecker` then refuses in a gated policy class. That is the
        # fail-closed direction: silence about the origin, never a citation that
        # cannot be produced.
        store = self._memory._store                 # noqa: SLF001
        claims = []
        for value, rank, trust_class, log_seq in rows:
            rec = store.record("log", log_seq)
            support = ()
            if rec is not None:
                support = (LogReceipt.of("log", rec, value),)
            claims.append(Claim(text=value, memory_rank=rank,
                                trust_class=trust_class, support=support))
        return claims

    def resolve(self, subject: str, attribute: str) -> dict:
        """Resolve one contradiction, or produce the question. Never a pick."""
        claims = self.claims_for(subject, attribute)
        return resolve_memory_conflict(
            self._bus or _NullBus(), claims, subject=f"{subject}/{attribute}")

    def sweep(self, *, ceiling: str = "private") -> list:
        """Every contradiction, with what the resolver did about it.

        RETURNS THE ASKS AS ASKS. The caller decides when to put a question in
        front of the owner -- `interruption_budget.toml` governs that and this
        module does not get to overrule it. What this guarantees is that the
        question EXISTS rather than having been silently resolved away.
        """
        out = []
        for c in self.contradictions(ceiling=ceiling):
            res = self.resolve(c["subject"], c["attribute"])
            out.append({**c, "outcome": res.get("outcome"),
                        "reason": res.get("reason"),
                        "value": res.get("value")})
        return out

    def open_questions(self, *, ceiling: str = "private") -> list:
        """Only the contradictions that must reach the owner."""
        return [r for r in self.sweep(ceiling=ceiling) if r["outcome"] == "ASK"]


class _NullBus:
    """A bus that discards. The resolver publishes; a caller may not care.

    Deliberately not `None`-checking inside `resolve_memory_conflict`: that
    function's publish is part of how a conflict becomes visible, and making it
    optional there would let a caller silence the very event the invariant
    exists to produce.
    """

    def publish(self, *a: Any, **k: Any) -> None:
        return None
