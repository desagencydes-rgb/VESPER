"""The updater and the miss recorder — the net under everything VESPER missed.

TWO WRITERS, AND THIS IS THE SECOND. `MEMORY_ARCHITECTURE.md`: VESPER writing
deliberately is judgement, rank 5, its own files. The updater runs after every
act, in the background, and captures WHETHER OR NOT IT LOOKS IMPORTANT. That
indiscriminateness is the design, not a shortcut -- a capture path that only
records what seemed significant is a capture path with VESPER's blind spots
built into it, and blind spots are precisely what a net is for.

WHICH MAKES THE REFUSAL LIST THE WHOLE SAFETY ARGUMENT. It is the only thing
between "a safety net" and "a file that quietly accumulates everything the owner
ever said near a microphone."

REFUSING IS NOT DELETING (owner, 2026-08-28). Refused material goes to a
quarantine that the projections never read. Two properties follow and both are
the point: a wrong refusal is RECOVERABLE, because over-refusal without a
quarantine is a silent permanent loss and nobody notices an absence; and a wrong
RULE becomes VISIBLE, because one refusal is an event and five hundred of the
same shape is a pattern -- and a pattern is only visible if the refusals are
kept somewhere countable.

THIS INVERTS THE OBVIOUS INSTINCT, which is to refuse as little as possible so
nothing is lost. With a quarantine the asymmetry reverses: an over-refusal is a
retrievable inconvenience, an under-refusal is a permanent record of something
that should never have been written. So: REFUSE GENEROUSLY. `redact.scan()` is
called here with `generous=True` for exactly that reason, and with the default
at the egress boundary where over-redaction corrupts the owner's own request.

CLASS 1 IS NOT QUARANTINED IN FULL, AND THAT IS THE TRAP IN THIS FILE. A
quarantine holding every credential VESPER has ever seen is a more attractive
target than the vault -- it is the one place they are all gathered, and it was
built to be the low-security bin. What is kept is a TOMBSTONE: a
credential-shaped string was refused here, at this time, from this source.
Enough to audit the detector, useless to a thief. `redact.Finding` has no field
the value could travel in, which is what makes that safe rather than merely
intended.

RANK 4 AND RANK 5 ARE STORED SEPARATELY AND BOTH ARE STORED. `INV-EVID-1`
forbids a model prior asserted into memory, so a model extractor cannot produce
rank 4. The owner's verbatim utterance is rank 4; the extractor's READING of it
is rank 5. Storing only the reading permanently and invisibly promotes the
system's guesses to the owner's word, and nothing downstream can separate them
afterwards because the distinction was never written down.

THE EXTRACTOR IS INJECTED, NEVER IMPORTED. It is the only part of this file that
needs a model, and it is optional: with no extractor the verbatim rank-4 capture
still happens, which is the half that cannot be reconstructed later. That also
keeps this module stdlib-only and testable without a network.

SAID ONCE ISN'T A TRAIT, AND IT IS A RANKING RULE RATHER THAN A REFUSAL. "I hate
this project", said in frustration, must not become a durable fact that the
owner hates that project. It stays one observation with a timestamp; only
repetition promotes it toward a trait. THIS NEEDS NO DETECTION OF MOOD AT ALL,
which is the entire point -- the system never judges how something was said, it
only declines to generalise from a single utterance. Every design that tried to
read tone needed a model in the capture path, and a model in the capture path is
the same defect as one in the redactor.

THE TURN NEVER WAITS AND NEVER FAILS ON THIS. Capture is dispatched and
forgotten. `capture()` catches its own exceptions and records them rather than
raising, because the updater dying must not turn a good answer into an error --
a turn that waits on its own bookkeeping is slower than one with no memory at
all.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .memory import MemoryContractViolation, MemoryGraph
from .redact import scan

# Owner-driven, fixed, and deliberately not inferred. Same mechanism as
# `core/barge_in.py`: a phrase list, no model, no judgement about what the
# moment contained. A rule that has to GUESS whether the owner meant it is a
# rule that will be wrong in the direction of recording.
OFF_THE_RECORD = (
    "off the record", "forget this", "forget that", "don't remember that",
    "do not remember that", "dont remember that", "don't record this",
    "do not record this", "keep this between us",
)

# Why refused, for the quarantine. The first may never be quarantined in full.
REFUSED_CREDENTIAL = "credential_shaped"
REFUSED_OFF_RECORD = "off_the_record"
REFUSED_OWNER_SENSITIVE = "owner_designated_sensitive"

# `DF-MEMORY-AUTHORITY`. The owner's own words; the extractor's reading of them.
RANK_USER_STATEMENT = 4
RANK_DERIVED = 5

# Repetition promotes an observation toward a trait. Unmeasured, and marked as
# such so it cannot be quoted as a finding: nothing has yet watched this owner
# repeat anything, and a threshold chosen from taste is a declared number.
TRAIT_REPETITIONS = 3
TRAIT_REPETITIONS_MEASURED = False

# Backpressure. Sheds OLDEST first, because silently dropping the newest loses
# what just happened -- the material most likely to matter.
DEFAULT_BACKLOG = 256


@dataclass(frozen=True, slots=True)
class Capture:
    """What one capture attempt did. Every outcome is a different fact."""

    outcome: str                     # stored | refused | duplicate | shed | failed
    event_id: str
    reason: str = ""
    fact_ids: tuple = ()
    quarantine_seq: int | None = None
    tombstone_seq: int | None = None

    def to_dict(self) -> dict:
        d = {"outcome": self.outcome, "event_id": self.event_id,
             "reason": self.reason, "fact_ids": list(self.fact_ids)}
        if self.quarantine_seq is not None:
            d["quarantine_seq"] = self.quarantine_seq
        if self.tombstone_seq is not None:
            d["tombstone_seq"] = self.tombstone_seq
        return d


class Updater:
    """Captures after every act. Never blocks the turn, never fails it."""

    def __init__(self, memory: MemoryGraph, store: Any, clock: Any, *,
                 bus: Any = None, extractor: Callable | None = None,
                 backlog: int = DEFAULT_BACKLOG) -> None:
        self._memory = memory
        self._store = store
        self._clock = clock
        self._bus = bus
        self._extractor = extractor
        self._lock = threading.RLock()
        # Delivery is at-least-once, so the same capture arriving twice must not
        # produce two facts. Keyed on the event id, which is the only identifier
        # that survives a redelivery.
        self._seen: dict = {}
        self._order: deque = deque(maxlen=backlog)
        self._backlog = backlog
        self.shed_count = 0

    # ---------------------------------------------------------------- capture

    def capture(self, text: str, *, event_id: str, subject: str = "owner",
                attribute: str = "said", source: str = "typed",
                privacy: str = "private", trust_class: str = "owner",
                owner_sensitive: bool = False) -> Capture:
        """Take one utterance. Returns what was decided and why; never raises.

        THE RETURN VALUE IS THE RECORD. A caller that ignores it loses nothing
        the system needs -- every outcome is also published and, where it
        matters, written -- but a caller that RAISES out of here would turn a
        good answer into an error, which is the one thing background work may
        never do.
        """
        try:
            return self._capture(text, event_id=event_id, subject=subject,
                                 attribute=attribute, source=source,
                                 privacy=privacy, trust_class=trust_class,
                                 owner_sensitive=owner_sensitive)
        except Exception as exc:                   # noqa: BLE001
            # A background failure is recorded and triaged later, when a model
            # is available again. It is not raised into the turn.
            self._emit("updater.failed", {"event_id": event_id,
                                          "error": repr(exc)})
            return Capture(outcome="failed", event_id=event_id,
                           reason=f"{type(exc).__name__}: {exc}")

    def _capture(self, text: str, *, event_id: str, subject: str,
                 attribute: str, source: str, privacy: str, trust_class: str,
                 owner_sensitive: bool) -> Capture:
        with self._lock:
            if event_id in self._seen:
                return Capture(outcome="duplicate", event_id=event_id,
                               reason="at-least-once delivery; already captured",
                               fact_ids=self._seen[event_id])
            if len(self._order) == self._backlog and self._order:
                oldest = self._order[0]
                self.shed_count += 1
                # RECORDED, never silent. A capture path that drops quietly is
                # indistinguishable from one that is keeping up.
                self._emit("updater.shed", {"event_id": oldest,
                                            "shed_total": self.shed_count,
                                            "note": "oldest first; the newest "
                                                    "is what just happened"})
                self._seen.pop(oldest, None)

        # 1. OFF THE RECORD. Checked FIRST, before anything is written
        #    anywhere, because a phrase that marks a moment unrecorded must not
        #    have its own content land in a quarantine on the way past.
        low = text.lower()
        if any(p in low for p in OFF_THE_RECORD):
            self._emit("updater.refused", {"event_id": event_id,
                                           "reason": REFUSED_OFF_RECORD})
            return Capture(outcome="refused", event_id=event_id,
                           reason=REFUSED_OFF_RECORD)

        # 2. CREDENTIALS. Generous, because an over-refusal here is retrievable
        #    from the quarantine and an under-refusal is permanent. The
        #    TOMBSTONE is the whole record -- never the value.
        findings = scan(text, generous=True, source=source)
        if findings:
            seq = self._store.append(
                "tombstones", "updater.credential_refused",
                {"event_id": event_id, "source": source,
                 "at": str(self._clock.now()),
                 "findings": [f.to_dict() for f in findings],
                 "note": ("a credential-shaped string was refused here. The "
                          "value is deliberately absent: a store holding every "
                          "credential VESPER has seen is a better target than "
                          "the vault.")},
                self._clock.now())
            self._emit("updater.refused", {"event_id": event_id,
                                           "reason": REFUSED_CREDENTIAL,
                                           "count": len(findings)})
            with self._lock:
                self._seen[event_id] = ()
                self._order.append(event_id)
            return Capture(outcome="refused", event_id=event_id,
                           reason=REFUSED_CREDENTIAL, tombstone_seq=int(seq))

        # 3. OWNER-DESIGNATED SENSITIVE. Quarantined IN FULL -- reviewable and
        #    releasable, because the owner marked it and the owner can unmark it.
        if owner_sensitive:
            seq = self._store.append(
                "workspace", "updater.quarantined",
                {"event_id": event_id, "source": source, "text": text,
                 "reason": REFUSED_OWNER_SENSITIVE,
                 "note": "owner-reviewable and releasable; projections never "
                         "read this store"},
                self._clock.now())
            self._emit("updater.refused", {"event_id": event_id,
                                           "reason": REFUSED_OWNER_SENSITIVE})
            with self._lock:
                self._seen[event_id] = ()
                self._order.append(event_id)
            return Capture(outcome="refused", event_id=event_id,
                           reason=REFUSED_OWNER_SENSITIVE,
                           quarantine_seq=int(seq))

        # 4. THE WRITE. Verbatim at rank 4 ALWAYS; the extractor's reading at
        #    rank 5 only if there is an extractor, and never instead.
        ids = []
        verbatim = self._memory.remember(
            subject=subject, attribute=attribute, value=text,
            rank=RANK_USER_STATEMENT, privacy=privacy,
            trust_class=trust_class, at=self._clock.now())
        ids.append(verbatim.id)

        if self._extractor is not None:
            for reading in self._readings(text):
                try:
                    derived = self._memory.remember(
                        subject=reading.get("subject", subject),
                        attribute=reading.get("attribute", "derived"),
                        value=reading["value"],
                        # RANK 5, ALWAYS, whatever the extractor claims. An
                        # extractor that could set its own rank could promote
                        # itself to the owner's word, and nothing downstream
                        # would be able to tell.
                        rank=RANK_DERIVED, privacy=privacy,
                        # `model_generated`, from core/taint.py. An extractor IS
                        # a model, and calling its output anything else hides
                        # that from every trust computation downstream.
                        trust_class="model_generated",
                        at=self._clock.now())
                    ids.append(derived.id)
                except (MemoryContractViolation, KeyError) as exc:
                    self._emit("updater.extraction_refused",
                               {"event_id": event_id, "error": repr(exc)})

        with self._lock:
            self._seen[event_id] = tuple(ids)
            self._order.append(event_id)
        self._emit("updater.stored", {"event_id": event_id,
                                      "fact_ids": ids,
                                      "verbatim_rank": RANK_USER_STATEMENT,
                                      "derived": len(ids) - 1})
        return Capture(outcome="stored", event_id=event_id,
                       fact_ids=tuple(ids))

    def _readings(self, text: str) -> list:
        """The extractor's output, defensively normalised.

        An extractor is a model and its output is `model_prior` until it is
        stored as `derived` against the owner's own verbatim words. Anything
        malformed is dropped rather than guessed at.
        """
        try:
            out = self._extractor(text) or []
        except Exception as exc:                   # noqa: BLE001
            self._emit("updater.extractor_failed", {"error": repr(exc)})
            return []
        return [r for r in out
                if isinstance(r, dict) and str(r.get("value", "")).strip()]

    # ------------------------------------------------------ said once ≠ trait

    def trait_candidates(self, *, threshold: int = TRAIT_REPETITIONS) -> list:
        """Observations repeated often enough to be treated as traits.

        COMPUTED, NEVER STORED AS A FLAG. Promotion is a RANKING rule, so it
        has to be re-derivable: a stored `is_trait` bit taken once could never
        be un-taken by the owner simply not saying the thing again, and a mood
        recorded in frustration would outlive the mood. Counting at read time
        means a trait stops being one when the repetitions stop mattering.
        """
        rows = self._memory._conn.execute(          # noqa: SLF001
            """SELECT en.name, f.attribute, f.value, COUNT(*) AS n
                 FROM fact f JOIN entity en ON en.id = f.subject_id
                WHERE f.rank = ?
             GROUP BY f.subject_id, f.attribute, f.value
               HAVING n >= ?
             ORDER BY n DESC""",
            (RANK_USER_STATEMENT, threshold)).fetchall()
        return [{"subject": r[0], "attribute": r[1], "value": r[2],
                 "repetitions": r[3], "threshold": threshold,
                 "threshold_measured": TRAIT_REPETITIONS_MEASURED}
                for r in rows]

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=payload.get("event_id", "updater"),
                              payload=payload, component="updater")


class MissRecorder:
    """The only reason the memory design can ever be judged.

    MISSES ARE INVISIBLE HERE, and that is the problem this class exists for. No
    query returns empty and no error is raised -- VESPER simply does not know
    something and answers anyway, fluently. There is no event. So a miss is
    catchable only RETROSPECTIVELY, by pairing what VESPER did with the
    correction that followed, and that pairing exists no other way.

    `MEMORY_ARCHITECTURE.md` is blunt about the consequence of not having this:
    "no corpus; design can never be judged". Every blocked question -- does
    carrying memory improve answers, does selection surface the right facts --
    waits on records written here.

    TWO OF THE THREE DETECTORS NEED NO MODEL. Repetition (the owner states
    something memory already holds at or above the rank it would be written at)
    and explicit absence (VESPER said it did not have something) are both
    deterministic. Only correction is fuzzy, and it is injected for the same
    reason the extractor is.
    """

    REPETITION = "repetition"
    CORRECTION = "correction"
    EXPLICIT_ABSENCE = "explicit_absence"

    def __init__(self, memory: MemoryGraph, store: Any, clock: Any, *,
                 bus: Any = None) -> None:
        self._memory = memory
        self._store = store
        self._clock = clock
        self._bus = bus

    def record(self, *, detector: str, situation: str, layer_consulted: str,
               what_was_found: Any, what_vesper_did: str,
               correction: str | None = None) -> int:
        """One miss, in the `audit` store. Append-only at the storage layer.

        `correction` MAY BE NONE AND THE RECORD IS STILL WRITTEN. The correction
        often arrives in a later turn, and a design that waited for it would
        record only the misses that happened to be corrected promptly -- which
        is a biased corpus, and biased in the direction of looking better than
        the truth.
        """
        if detector not in (self.REPETITION, self.CORRECTION,
                            self.EXPLICIT_ABSENCE):
            raise ValueError(
                f"unknown detector {detector!r}. A miss whose detector is not "
                "named cannot be counted against that detector's false-positive "
                "rate, which is the only way the thresholds get tuned.")
        seq = self._store.append(
            "audit", "memory.miss",
            {"detector": detector, "situation": situation,
             "layer_consulted": layer_consulted,
             "what_was_found": what_was_found,
             "what_vesper_did": what_vesper_did,
             "correction": correction,
             "at": str(self._clock.now())},
            self._clock.now())
        if self._bus is not None:
            self._bus.publish("memory.miss", subject=detector,
                              payload={"seq": int(seq), "detector": detector,
                                       "corrected": correction is not None},
                              component="miss-recorder")
        return int(seq)

    def repetition(self, text: str, *, subject: str = "owner",
                   ceiling: str = "private") -> dict | None:
        """Did the owner just tell VESPER something memory already holds?

        Deterministic: the check is whether selection ALREADY returns the fact,
        which is exactly the question "would carrying memory have helped here".
        A hit means memory held it and VESPER did not use it -- which is a
        SELECTION miss, and a different defect from never having stored it.
        """
        terms = [t for t in _terms(text) if len(t) > 3]
        if not terms:
            return None
        for f in self._memory.select(terms, ceiling=ceiling):
            if _overlap(f.value, text) >= 0.6:
                return {"detector": self.REPETITION, "held_fact_id": f.id,
                        "held_value": f.value, "rank": f.rank,
                        "note": ("memory held this and the answer did not use "
                                 "it: a selection miss, not a capture miss")}
        return None

    def explicit_absence(self, vesper_said: str) -> dict | None:
        """VESPER stated it did not know. The one miss that announces itself."""
        low = vesper_said.lower()
        for phrase in ("i don't have", "i do not have", "i don't know",
                       "i do not know", "you haven't told me",
                       "i have no record", "nothing in memory"):
            if phrase in low:
                return {"detector": self.EXPLICIT_ABSENCE, "phrase": phrase}
        return None


def _terms(text: str) -> list:
    return [w.strip(".,!?;:'\"").lower() for w in text.split() if w.strip()]


def _overlap(a: str, b: str) -> float:
    """Jaccard over word sets. Deterministic, and no model in the miss path."""
    sa, sb = set(_terms(a)), set(_terms(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
