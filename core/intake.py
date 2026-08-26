"""How something said to VESPER arrives — typed now, spoken later, same pipe.

WHY THIS EXISTS BEFORE THERE IS A MICROPHONE. The owner's constraint, 2026-08-25:
a text field is necessary now and will matter less once VESPER can hold a spoken
conversation. That is a statement about which modality is PRIMARY, not about
which one to build first -- and the expensive mistake is to build the typed path
as though typing were the only way anything arrives.

THE DIFFERENCE THAT WOULD FORCE A REWRITE, and it is not the input device:

    A TYPED utterance is CERTAIN and COMPLETE. It exists when the owner presses
    return; every character is exactly what they meant.

    A SPOKEN utterance is NEITHER. It arrives in fragments, each revising the
    last, and every word carries a confidence that may be low. "Delete the
    archive" and "delete the archives" are one phoneme apart, and a recogniser
    that is 61% sure is not evidence of anything.

A pipe that assumes certainty and completeness has both assumptions baked into
every caller downstream, and voice then arrives as a rewrite rather than a
source. So `Utterance` carries `final` and `confidence` from the first day, and
the typed path simply fills them in as certain -- which costs nothing now and is
the whole of the migration later.

CONFIDENCE GATES ACTION, IT DOES NOT GATE DELIVERY. A low-confidence utterance
is still recorded and still shown; what it does not do is silently become an
instruction. `SR-042`'s standing rule -- do not wake the owner for ordinary work
-- cuts the other way here: a misheard command executed is worse than a slow
one, so an uncertain utterance is REFLECTED BACK rather than acted on. The owner
correcting a wrong transcription costs seconds; VESPER acting on one can cost
whatever the action cost.

NOTHING DOWNSTREAM BRANCHES ON THE SOURCE. `CompletionService` does not know or
ask whether a request was typed or spoken. If it ever needs to, that is a signal
the abstraction leaked -- the source belongs in the RECORD, for audit and for
the transcript, and not in the control flow.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

# How an utterance reached VESPER. Recorded, never branched on.
TYPED = "typed"
SPOKEN = "spoken"
SCHEDULED = "scheduled"      # a trigger firing, e.g. the Thursday ritual
SOURCES = (TYPED, SPOKEN, SCHEDULED)

# Below this, a spoken utterance is reflected back for confirmation instead of
# acted on. Deliberately NOT tuned yet: nothing has measured this recogniser on
# this owner's voice in this room, and a threshold chosen from a paper is a
# declared number. It is here so the SHAPE is right, and it is marked as
# unmeasured so it cannot be quoted as though it were a finding.
CONFIDENCE_FLOOR = 0.75
CONFIDENCE_FLOOR_MEASURED = False


class IntakeRefused(Exception):
    """An utterance could not be accepted. Never silently dropped."""


@dataclass
class Utterance:
    """One thing said to VESPER, however it arrived.

    `final` and `confidence` exist for every source, including typed, where
    they are trivially true and 1.0. Giving the typed path the same shape as
    the spoken one is what makes voice a SOURCE later rather than a rewrite --
    and it costs one line today.
    """

    text: str
    source: str = TYPED
    # False while a recogniser is still revising. A typed utterance is final
    # the moment it exists.
    final: bool = True
    # None means "certainty is not a question here" -- which is true of typing
    # and of a scheduled trigger, and is NOT the same as 1.0 from a recogniser
    # that happened to be sure. The distinction matters when the record is read
    # back: one is a fact about the channel, the other is a measurement.
    confidence: float | None = None
    hlc: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise IntakeRefused(
                f"unknown source {self.source!r}, expected {SOURCES}. An "
                "utterance whose provenance is unknown cannot be audited, and "
                "the record is the only place the source is allowed to matter.")

    def certain(self) -> bool:
        """Is this safe to act on without reflecting it back first?"""
        if self.confidence is None:
            return True              # the channel does not admit uncertainty
        return self.confidence >= CONFIDENCE_FLOOR

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source, "final": self.final,
                "confidence": self.confidence, "hlc": self.hlc,
                "certain": self.certain(), **({"meta": self.meta} if self.meta else {})}


class Intake:
    """Accepts utterances from any source and dispatches the ones ready to act.

    HOLDS THE PARTIALS, DISPATCHES THE FINALS. A recogniser emits a stream of
    revisions and only the last is what the owner said; dispatching each one
    would run the same request five times and answer four questions nobody
    asked. Typed input produces exactly one final utterance and passes straight
    through, so the buffering costs it nothing.
    """

    def __init__(self, *, bus: Any = None, clock: Any = None,
                 dispatch: Callable[[Utterance], Any] | None = None) -> None:
        self._bus = bus
        self._clock = clock
        self._dispatch = dispatch
        self._lock = threading.RLock()
        self._partial: dict[str, Utterance] = {}
        self.history: list = []

    def offer(self, u: Utterance, *, stream_id: str = "default") -> dict:
        """Take an utterance. Returns what was decided and why.

        THREE OUTCOMES, and each is a different fact:
          `buffered`  -- a revision arrived; nothing acted on yet
          `reflected` -- heard, but not confidently enough to act on
          `dispatched` -- acted on
        """
        with self._lock:
            if self._clock is not None and not u.hlc:
                # `now()`, NOT `tick()`. The identical wrong assumption was
                # made in core/triage.py and fixed there; it was still here,
                # because fixing one call site is not fixing a belief about an
                # API. Both files were written the same day from the same wrong
                # idea, and only one had been exercised with a clock attached.
                u.hlc = str(self._clock.now())
            self.history.append(u)

            if not u.final:
                self._partial[stream_id] = u
                self._emit("intake.partial", u)
                return {"outcome": "buffered", "utterance": u.to_dict(),
                        "note": ("a revision, not an instruction -- dispatching "
                                 "every fragment would answer four questions "
                                 "nobody asked")}

            self._partial.pop(stream_id, None)

            if not u.text.strip():
                self._emit("intake.empty", u)
                return {"outcome": "ignored", "utterance": u.to_dict(),
                        "note": "empty after trimming; nothing was said"}

            if not u.certain():
                self._emit("intake.reflected", u)
                return {"outcome": "reflected", "utterance": u.to_dict(),
                        "note": (f"confidence {u.confidence} is below the floor "
                                 f"{CONFIDENCE_FLOOR}"
                                 + ("" if CONFIDENCE_FLOOR_MEASURED
                                    else " (UNMEASURED -- the floor's shape is "
                                         "right and its value has not been "
                                         "measured on this owner's voice)")
                                 + ". Reflected for confirmation rather than "
                                   "acted on: correcting a wrong transcription "
                                   "costs seconds, acting on one costs whatever "
                                   "the action costs.")}

            self._emit("intake.dispatched", u)
            result = self._dispatch(u) if self._dispatch else None
            return {"outcome": "dispatched", "utterance": u.to_dict(),
                    "result": result}

    def typed(self, text: str) -> dict:
        """The path the input field uses. Certain and complete by construction."""
        return self.offer(Utterance(text=text, source=TYPED))

    def spoken(self, text: str, *, confidence: float, final: bool,
               stream_id: str = "mic") -> dict:
        """The path a recogniser will use. Exists now so it is not a rewrite."""
        return self.offer(Utterance(text=text, source=SPOKEN,
                                    final=final, confidence=confidence),
                          stream_id=stream_id)

    def transcript(self, limit: int = 40) -> list:
        """What has been said, newest last. The surface both modalities share.

        Partials are excluded: a transcript that showed every revision would
        show the owner their own words being rewritten, which is the recogniser
        thinking out loud rather than a record of what was said.
        """
        with self._lock:
            return [u.to_dict() for u in self.history if u.final][-limit:]

    def _emit(self, type_: str, u: Utterance) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject=u.source, payload=u.to_dict(),
                              component="intake")
