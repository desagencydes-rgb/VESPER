"""The owner's hand on the context — SR-008's missing half.

WHAT WAS ACTUALLY MISSING, because it is not what the handoff says. That
document records "manual mode missing entirely". It is not: `ContextBudgetManager
.assemble(manual=[...])` pins fragments first, never lets the automatic selector
drop them, and reports an overrun rather than silently discarding what the owner
asked for. It has worked since it was written.

What was missing is that **nothing reaches it**. `ContextBudgetManager` is
constructed in exactly one place in this repository -- `run_f1_acceptance.py` --
so manual mode was exercised only by the test that proves it exists. And
SR-008 asks for the mode to be "switchable by command or interface", which needs
a surface the owner can actually speak to. That surface is this file.

DETERMINISTIC, NO MODEL, SAME MECHANISM AS THE OTHERS. A fixed phrase list, like
`core/updater.py`'s off-the-record and `core/presence.py`'s declaration. A model
deciding what the owner meant by "focus on the flight" would put a network call
in front of a command whose whole purpose is to take control away from the
automatic path -- and would fail in the direction of ignoring the instruction.

THE THREE THINGS AN OWNER ACTUALLY WANTS, and they are different operations:

    PIN      "focus on X", "use the X" -- X survives every automatic cut.
    DROP     "forget the last hour", "drop the calendar" -- X is excluded even
             if the selector would have chosen it.
    CLEAR    "never mind", "back to normal" -- return to automatic.

DROP IS NOT PIN'S OPPOSITE AND MUST NOT BE BUILT AS ONE. Un-pinning returns a
fragment to the automatic selector, which may well choose it again -- so an
owner saying "drop the calendar" and getting it back on the next turn would
reasonably conclude the command does nothing. A drop is an exclusion that
outlives the selector's opinion.

IT NEVER SILENTLY EXPIRES, for the reason `core/presence.py` gives about its own
flag: a control the owner set and the system quietly released is worse than one
that was never offered, because they stop trusting the ones that remain.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

PIN_PHRASES = ("focus on", "focus only on", "use only", "just use",
               "stick to", "only look at", "pin ")
DROP_PHRASES = ("forget the", "drop the", "ignore the", "leave out the",
                "without the", "stop using the")
CLEAR_PHRASES = ("never mind", "back to normal", "forget that", "as you were",
                 "unpin", "clear the focus", "normal mode")

AUTOMATIC = "automatic"
MANUAL = "manual"


@dataclass
class ContextControl:
    """What the owner has pinned and dropped. Nothing here expires."""

    pinned: set = field(default_factory=set)
    dropped: set = field(default_factory=set)

    @property
    def mode(self) -> str:
        return MANUAL if (self.pinned or self.dropped) else AUTOMATIC

    def to_dict(self) -> dict:
        return {"mode": self.mode, "pinned": sorted(self.pinned),
                "dropped": sorted(self.dropped)}


def _subject_after(text: str, phrase: str) -> str:
    """The words the owner named after a command phrase.

    Stops at a clause boundary. "focus on the flight and tell me the time" is
    one instruction and one subject, not a subject containing an instruction --
    taking the whole tail would pin a phrase no fragment could ever match.
    """
    i = text.find(phrase)
    tail = text[i + len(phrase):].strip()
    tail = re.split(r"\b(?:and|then|also|but|please)\b|[,.;?]", tail)[0]
    return " ".join(w for w in tail.split() if w not in ("the", "a", "an", "my")).strip()


class ContextCommands:
    """Turns owner phrases into pins and drops. No model, no inference."""

    def __init__(self, *, bus: Any = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self.state = ContextControl()

    def offer(self, text: str) -> dict | None:
        """Read an utterance for a context command. None for ordinary speech.

        CLEAR IS CHECKED FIRST. "never mind, focus on the flight" contains both
        a clear and a pin, and the owner means the later one -- but "forget
        that" alone is a clear, not a drop of a fragment named "that". Ordering
        the checks so an explicit clear cannot be swallowed by the drop list is
        what keeps "never mind" from pinning the word "mind".
        """
        flat = " ".join((text or "").lower().split())
        if not flat:
            return None
        with self._lock:
            for p in CLEAR_PHRASES:
                if p in flat and not any(q in flat for q in PIN_PHRASES):
                    self.state.pinned.clear()
                    self.state.dropped.clear()
                    return self._emit("cleared", "")
            for p in PIN_PHRASES:
                if p in flat:
                    subj = _subject_after(flat, p)
                    if subj:
                        self.state.pinned.add(subj)
                        self.state.dropped.discard(subj)
                        return self._emit("pinned", subj)
            for p in DROP_PHRASES:
                if p in flat:
                    subj = _subject_after(flat, p)
                    if subj:
                        self.state.dropped.add(subj)
                        self.state.pinned.discard(subj)
                        return self._emit("dropped", subj)
        return None

    @staticmethod
    def _haystack(f: Any) -> str:
        """Everything about an item the owner might have named.

        WORKS ON MORE THAN ONE SHAPE ON PURPOSE. `Fragment` carries
        `fragment_id`/`text`; a `MemoryFact` carries `id`/`subject`/`attribute`/
        `value`. The first version read only Fragment's fields, so passing it
        memory facts matched nothing and a drop silently did nothing -- the
        exact failure the owner would report as "the command is ignored".
        Naming the fields explicitly rather than duck-typing one of them keeps
        that from recurring when a third shape arrives.
        """
        parts = [getattr(f, n, "") for n in
                 ("fragment_id", "id", "kind", "subject", "attribute", "text", "value")]
        return " ".join(str(p) for p in parts if p).lower()

    @staticmethod
    def _ident(f: Any) -> Any:
        return getattr(f, "fragment_id", None) or getattr(f, "id", None)

    def manual_ids(self, fragments: list) -> list:
        """Fragment ids to pin, matched against what the owner named.

        SUBSTRING MATCH ON ID AND TEXT, deliberately loose. The owner says "the
        flight", not `frag-l2-0007`, and a control that required the internal
        identifier would be a control only the system could use.
        """
        out = []
        with self._lock:
            pins = set(self.state.pinned)
        for f in fragments:
            if any(p and p in self._haystack(f) for p in pins):
                out.append(self._ident(f))
        return out

    def excluded(self, fragments: list) -> list:
        """Fragments the owner dropped. Removed BEFORE the selector runs.

        A DROP IS NOT AN UNPIN. Returning a dropped fragment to the automatic
        selector would let it be chosen again on the very next turn, and the
        owner would rightly conclude the command does nothing.
        """
        with self._lock:
            drops = set(self.state.dropped)
        return [f for f in fragments
                if not any(d and d in self._haystack(f) for d in drops)]

    def _emit(self, action: str, subject: str) -> dict:
        out = {"action": action, "subject": subject, **self.state.to_dict()}
        if self._bus is not None:
            self._bus.publish("context.commanded", subject=subject or "all",
                              payload=out, component="context")
        return out
