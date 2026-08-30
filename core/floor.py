"""Holding the floor, and what the owner can do to work that is in flight.

THE THING THAT WAS MISSING BETWEEN TWO THINGS THAT EXISTED. `core/chooser.py`
sets `announce` when a choice passes 600 ms -- the point where a pause stops
reading as thinking and starts reading as broken. `core/barge_in.py` classifies
what the owner says during such a hold, has 242 phrases and a gate, and was
called by NOTHING. Neither is useful alone: an announcement with no way to
respond to it is a status line, and a classifier nothing feeds is a table.

THE FOUR OUTCOMES ARE NOT FOUR SHADES OF ONE THING. `barge_in` returns them and
this module is what makes them differ in behaviour rather than in name:

    BREAK    abandon the work now. The owner took the floor.
    SWALLOW  cooperative -- "no rush", "mhm". Discard it and STAY SILENT.
    STATUS   a liveness check. Answer it and DO NOT cancel.
    QUEUE    a new request. Hold it and deliver when the work lands.

SWALLOW MUST NOT ANSWER, and that is the outcome most likely to be implemented
wrongly, because answering is polite. "Take your time" met with "certainly, I'll
continue" is VESPER interrupting the owner's permission to not be interrupted.
Cooperative interruptions support the current speaker; responding to one takes
the floor the owner just declined to take.

QUEUE MUST ACTUALLY DELIVER. A queued utterance that is dropped when the work
lands is indistinguishable from one that was swallowed, and the owner learns
that speaking during a hold loses what they said. `release()` returns the queue
and empties it in the same call, so a caller cannot read it and forget it.

A HALT IS NEVER LOST. `INV-STOP-*` is the family this belongs to and the
asymmetry is the corpus's usual one: a wrong break costs one preparation cycle,
and a wrong swallow means "stop" was ignored -- which is the failure that makes
a system nobody will leave running.

NO MODEL, AND NOT FOR COST. This runs while the owner is mid-sentence and the
work is in flight; a model call here would add its own latency to the hold it is
supposed to be managing, and `barge_in` is a phrase table precisely so the
answer arrives before the next word does.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .barge_in import Floor, classify


@dataclass(frozen=True, slots=True)
class Verdict:
    """One mid-hold utterance and what it did. Every field is a different fact."""

    floor: str
    text: str
    acted: bool          # did this change what the work is doing?
    answer: bool         # does the owner get a reply right now?
    queued: bool         # will this be delivered when the work lands?

    def to_dict(self) -> dict:
        return {"floor": self.floor, "acted": self.acted,
                "answer": self.answer, "queued": self.queued}


class Held(Exception):
    """An operation that only makes sense while the floor is held, or is not."""


class FloorHolder:
    """Holds the floor for work in flight and routes what arrives during it."""

    def __init__(self, *, bus: Any = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._held = False
        self._reason = ""
        self._queue: list = []
        self.broken = False

    # ------------------------------------------------------------------ hold

    def hold(self, reason: str) -> None:
        """Take the floor. `reason` is what VESPER would say if asked."""
        with self._lock:
            self._held = True
            self._reason = reason
            self._queue.clear()
            self.broken = False
        self._emit("floor.held", {"reason": reason})

    @property
    def holding(self) -> bool:
        with self._lock:
            return self._held

    def offer(self, text: str) -> Verdict:
        """Something the owner said. Classify it and say what happens.

        REFUSES WHEN THE FLOOR IS NOT HELD, rather than classifying anyway. An
        utterance outside a hold is an ordinary request and must go through
        `Intake`; treating it as a barge-in would silently route normal speech
        into a table that only knows how to stop things.
        """
        with self._lock:
            if not self._held:
                raise Held(
                    "the floor is not held, so this is an ordinary utterance "
                    "and belongs in Intake. Classifying it here would route "
                    "normal speech through a table that only knows how to stop "
                    "work.")

        verdict = classify(text)

        if verdict is Floor.BREAK:
            with self._lock:
                self.broken = True
                self._held = False
            v = Verdict(floor=verdict.value, text=text, acted=True,
                        answer=False, queued=False)
        elif verdict is Floor.SWALLOW:
            # SILENCE IS THE BEHAVIOUR, not an omission. Answering "take your
            # time" takes the floor the owner just declined to take.
            v = Verdict(floor=verdict.value, text=text, acted=False,
                        answer=False, queued=False)
        elif verdict is Floor.STATUS:
            # ANSWERED AND NOT CANCELLED. A liveness check is the owner asking
            # whether the silence is work or a hang, and the answer to that
            # question must not be to stop working.
            v = Verdict(floor=verdict.value, text=text, acted=False,
                        answer=True, queued=False)
        else:
            with self._lock:
                self._queue.append(text)
            v = Verdict(floor=verdict.value, text=text, acted=False,
                        answer=False, queued=True)

        self._emit("floor.offered", {**v.to_dict(), "reason": self._reason})
        return v

    def status_line(self) -> str:
        """What a liveness check gets. The reason, not a reassurance."""
        with self._lock:
            return self._reason or "still working"

    def release(self) -> list:
        """Give the floor back and return what was queued, emptying it.

        RETURNS AND CLEARS IN ONE CALL so a caller cannot read the queue and
        then forget to deliver it -- which would be indistinguishable, from the
        owner's side, from having been swallowed.
        """
        with self._lock:
            self._held = False
            queued, self._queue = list(self._queue), []
        self._emit("floor.released", {"delivered": len(queued)})
        return queued

    def _emit(self, type_: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(type_, subject="floor", payload=payload,
                              component="floor")
