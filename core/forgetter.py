"""The forgetter — three jobs that must not share a path.

`MEMORY_ARCHITECTURE.md` is explicit that these are different problems wearing
one word:

    EXPIRY SWEEP        deterministic, no model. A fact's validity ran out.
    OWNER-COMMANDED     the owner said to forget something, and "that" has to
                        be resolved to a fact.
    JUDGEMENT PRUNING   the highest-stakes of the three, and the only one where
                        a wrong answer destroys something nobody asked to lose.

"APPEND-ONLY" IS ABOUT THE SYSTEM, NOT THE OWNER. The owner's clarification:
the system may only append; the OWNER may change anything. Three modes, and who
may use each is the whole design:

    APPEND      system    normal path, new record, HLC-ordered
    SUPERSEDE   owner     an "edit" -- a NEW record superseding the old.
                          Both remain.
    ERASE       owner     content destroyed. A tombstone records THAT an
                          erasure happened, when, and by the owner. Never what.

AN EDIT MUST NOT BE AN IN-PLACE MUTATION, and this is the rule the obvious
implementation breaks. `UPDATE fact SET value = ?` is one line, reads as
correct, and leaves `observed_at_hlc` claiming a time that belongs to different
content. The audit trail is then FALSE rather than missing -- every record still
present, every timestamp still plausible, and the history it describes never
happened. `INV-LOSS-3` depends on that trail being real.

ERASE DOES NOT REACH L3, AND THE ARCHITECTURE CURRENTLY FORBIDS IT DOING SO.
Measured 2026-08-30: `UPDATE` and `DELETE` on the `log` store are both refused
at the STORAGE layer by ADR-002 D9, not by convention. So `erase()` removes the
L2 projection and the value remains readable in the append-only log, which means
two things that must not be discovered later:

    "content destroyed" IS TRUE OF THE PROJECTION AND NOT OF THE SOURCE. For the
    case erase exists for -- a leaked credential -- the credential is still in
    L3. It must be ROTATED. Erasing it is housekeeping, not containment.

    A REPROJECTION WOULD RESURRECT IT unless it consults the tombstones, which
    is why `core/compactor.py` reads them and why that is gated rather than
    remembered.

The fix is an owner-authorised path through the append-only guard -- the same
shape as the 2026-08-28 downgrade of "record format permanence", which concluded
that the system appends while the OWNER may rewrite. That path does not exist,
building it means changing a storage-layer invariant, and it is not a decision
this file gets to make.

ERASE EXISTS BECAUSE SUPERSESSION IS NOT ENOUGH. Some content should never have
existed: a leaked key, something recorded in error. Superseding it leaves it
readable in L3 forever. The tombstone keeps "something was removed here"
auditable without keeping the content -- the same shape as the updater's
credential refusal, and for the same reason.

NOTHING EXPIRES BY DELETION. Decided 2026-08-28 and not re-openable here:
staleness is a RANKING input and supersession is the only removal. So the expiry
sweep in this file does not delete -- it reports what has gone stale so ranking
can weigh it, which is why the method is called `stale()` and returns rows
rather than removing them. A forgetter that deleted on expiry would make the
constant case (a fact that is simply old and still true) need a model to save it.

NOBODY NOTICES AN ABSENCE. That sentence governs every method here. Append-only
makes a wrong forget RECOVERABLE, but only if someone realises it happened, and
a fact that quietly stopped being there produces no event at all. Every removal
in this file therefore writes a record of itself before it removes anything.
"""

from __future__ import annotations

from typing import Any

from .memory import MemoryGraph

# Who may invoke a mode. Not an enum for its own sake: `SYSTEM` appears here
# precisely so that the one mode it is allowed is visible beside the two it is
# not.
SYSTEM = "system"
OWNER = "owner"

APPEND = "append"
SUPERSEDE = "supersede"
ERASE = "erase"

MODE_ACTOR = {APPEND: (SYSTEM, OWNER), SUPERSEDE: (OWNER,), ERASE: (OWNER,)}


class ForgetRefused(Exception):
    """A removal the caller is not entitled to make, or cannot describe."""


class Forgetter:
    """Supersession, erasure and staleness. Never an in-place edit."""

    def __init__(self, memory: MemoryGraph, store: Any, clock: Any, *,
                 bus: Any = None) -> None:
        self._memory = memory
        self._store = store
        self._clock = clock
        self._bus = bus

    # -------------------------------------------------------------- supersede

    def supersede(self, *, subject: str, attribute: str, new_value: str,
                  actor: str, rank: int = 4, privacy: str = "private",
                  trust_class: str = "owner_utterance",
                  reason: str = "") -> dict:
        """The owner's edit. A NEW record; the old one remains readable.

        THE OLD FACT IS NOT TOUCHED. Not updated, not flagged, not deleted --
        the supersession is expressed by the NEW record's existence and its
        later position in HLC order, which is the only ordering this system
        recognises. Anything that reached back and modified the old row would
        make its `observed_at_hlc` a lie.
        """
        if actor not in MODE_ACTOR[SUPERSEDE]:
            raise ForgetRefused(
                f"{actor!r} may not supersede. The system appends; only the "
                "owner edits. A system that could rewrite the owner's stated "
                "facts would be correcting them, which is a different product.")
        prior = self._memory._conn.execute(         # noqa: SLF001
            """SELECT f.id, f.value, f.log_seq FROM fact f
                 JOIN entity en ON en.id = f.subject_id
                WHERE en.name = ? AND f.attribute = ?
             ORDER BY f.log_seq DESC LIMIT 1""",
            (subject, attribute)).fetchone()

        fact = self._memory.remember(
            subject=subject, attribute=attribute, value=new_value, rank=rank,
            privacy=privacy, trust_class=trust_class, at=self._clock.now())

        record = {"mode": SUPERSEDE, "actor": actor, "subject": subject,
                  "attribute": attribute, "new_fact_id": fact.id,
                  "new_log_seq": fact.log_seq,
                  "superseded_fact_id": prior[0] if prior else None,
                  "superseded_log_seq": prior[2] if prior else None,
                  "reason": reason, "at": str(self._clock.now()),
                  "note": ("both records remain readable; supersession is "
                           "expressed by HLC order, never by mutating the "
                           "earlier row")}
        self._store.append("audit", "memory.superseded", record,
                           self._clock.now())
        self._emit("memory.superseded", record)
        return record

    # ------------------------------------------------------------------ erase

    def erase(self, *, fact_id: int, actor: str, reason: str) -> dict:
        """Destroy content. Keep that it happened; never keep what it was.

        THE TOMBSTONE IS WRITTEN BEFORE THE ROW GOES. If the delete succeeded
        and the tombstone did not, the fact would be gone with no record that
        anything was ever there -- which is the silent absence this whole file
        is written against, and it would be indistinguishable from a bug.

        THE REASON IS MANDATORY AND THE CONTENT IS NOT KEPT. `INV-LOSS-3`:
        VESPER never presents a known cause as forgetting. With a deletion audit
        it NAMES the removal; with nothing it says nothing. A tombstone carrying
        the erased text would defeat the point of erasing it -- the same trap as
        quarantining a credential in full.
        """
        if actor not in MODE_ACTOR[ERASE]:
            raise ForgetRefused(
                f"{actor!r} may not erase. Erasure is the owner's alone: it is "
                "the one operation this system cannot undo, and a wrong one "
                "produces no evidence that it was wrong.")
        if not reason.strip():
            raise ForgetRefused(
                "erasure requires a reason. It is the only record that will "
                "survive, and 'something was removed here, cause unknown' is "
                "indistinguishable from data loss when it is read back.")

        row = self._memory._conn.execute(           # noqa: SLF001
            """SELECT f.id, en.name, f.attribute, f.log_seq, f.rank
                 FROM fact f JOIN entity en ON en.id = f.subject_id
                WHERE f.id = ?""", (fact_id,)).fetchone()
        if row is None:
            raise ForgetRefused(f"no fact {fact_id}")

        # THE SHAPE, NEVER THE CONTENT. Subject and attribute say what KIND of
        # thing was removed, which is what makes the tombstone auditable; the
        # value is what makes it dangerous, and it is not here.
        tomb = {"mode": ERASE, "actor": actor, "fact_id": row[0],
                "subject": row[1], "attribute": row[2],
                "log_seq": row[3], "rank": row[4], "reason": reason,
                "at": str(self._clock.now()),
                "note": ("the erased VALUE is deliberately absent. A tombstone "
                         "holding what it erased has not erased it.")}
        seq = self._store.append("tombstones", "memory.erased", tomb,
                                 self._clock.now())

        # THREE STEPS, AND DELETING THE ROW IS ONLY THE FIRST. Measured
        # 2026-08-30, because the obvious two-line version leaves the content
        # recoverable and looks completely finished:
        #
        #   DELETE FROM fact alone   -- `select()` stops returning it, because
        #     the join drops an orphan. But a raw `fact_fts MATCH` still counts
        #     it: any reader of the index other than `select()` sees the term.
        #
        #   + DELETE FROM fact_fts   -- the match count goes to zero. This is
        #     the step that actually removes it from the index.
        #
        #   + rebuild and VACUUM     -- belt and braces on the index's own
        #     STORAGE, and the honest description is that they help rather than
        #     guarantee.
        #
        # WHAT THIS CANNOT PROMISE, measured rather than assumed. The erased
        # term sometimes survives in the `fact_fts_data` shadow blocks after
        # every logical trace of it is gone, and whether it does depends on
        # FTS5's internal segment merging -- which depends on what else has been
        # written since. Two runs of the same erasure, differing only in whether
        # another fact had been stored, gave different answers. So this is NOT a
        # property to assert and NOT one to state as a guarantee: `erase()`
        # removes the content from every logical path into it, and cannot
        # promise the bytes are unrecoverable from the file.
        #
        # THE THREE LAYERS ARE REDUNDANT ON PURPOSE. Measured: VACUUM alone
        # takes the match count to zero, because it rebuilds the shadow tables
        # as a side effect. The explicit index delete and rebuild are kept
        # anyway -- VACUUM is a MAINTENANCE operation, not a semantic one, and
        # the first person who removes it for being slow would silently take
        # the erasure guarantee with it. The intent should be stated by the
        # code that means it.
        #
        # THAT LIMIT MATTERS MOST FOR THE CASE ERASE EXISTS FOR -- a leaked
        # credential. The vault, the updater's refusal and the redactor are what
        # keep a secret out of memory in the first place; erase is the remedy
        # for one that got in, and it is the weakest of the four. A credential
        # that reached L2 should be rotated, not merely erased.
        with self._memory._lock:                    # noqa: SLF001
            self._memory._conn.execute(             # noqa: SLF001
                "DELETE FROM fact_fts WHERE rowid = ?", (fact_id,))
            self._memory._conn.execute(             # noqa: SLF001
                "DELETE FROM fact WHERE id = ?", (fact_id,))
            self._memory._conn.execute(             # noqa: SLF001
                "INSERT INTO fact_fts(fact_fts) VALUES('rebuild')")
            self._memory._conn.commit()             # noqa: SLF001
            self._memory._conn.execute("VACUUM")    # noqa: SLF001

        tomb["tombstone_seq"] = int(seq)
        self._emit("memory.erased", tomb)
        return tomb

    # ------------------------------------------------------------- staleness

    def stale(self, *, older_than_seq: int) -> list:
        """Facts whose position in the log makes them candidates for demotion.

        RETURNS ROWS; REMOVES NOTHING. Nothing expires by deletion in this
        design -- staleness is a ranking input and supersession is the only
        removal. A sweep that deleted here would need a model to rescue the
        constant case, which is the most common case there is: a fact that is
        simply old and still perfectly true.

        ORDERED BY LOG SEQUENCE, NOT BY WALL CLOCK (`INV-COORD-4`). The seq is
        derived from HLC order, and it is the only ordering that survives two
        nodes appending independently.
        """
        rows = self._memory._conn.execute(          # noqa: SLF001
            """SELECT f.id, en.name, f.attribute, f.rank, f.log_seq
                 FROM fact f JOIN entity en ON en.id = f.subject_id
                WHERE f.log_seq < ?
             ORDER BY f.log_seq ASC""", (older_than_seq,)).fetchall()
        return [{"fact_id": r[0], "subject": r[1], "attribute": r[2],
                 "rank": r[3], "log_seq": r[4],
                 "note": "a ranking input, not a deletion candidate"}
                for r in rows]

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=str(payload.get("subject", "memory")),
                              payload=payload, component="forgetter")
