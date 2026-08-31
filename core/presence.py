"""Who is in the room, declared by the owner until a camera can see it.

WHY A PHRASE AND NOT A SENSOR. The layered identity check -- camera, then voice,
then a fingerprint prompt, on every interaction -- was designed, costed and
dropped by the owner on 2026-08-31: too much time per run and too much load on
the system. This is what replaces it until vision exists, and it is the same
mechanism `core/updater.py` already uses for "off the record": a fixed,
owner-driven phrase list, deterministic, no model, no inference about what the
moment contained.

IT COSTS NOTHING PER TURN, which is the entire argument for it. A phrase match
against a short list is free; a model deciding who is in the room is a network
call on the critical path, forever, and a filter that can be talked into
misbehaving by whatever it is listening to.

WHAT IT FEEDS. `core/privacy.py` already routes by
`privacy_class x persons x location_confidence`, and already resolves EVERY
ambiguous cell toward the most private surface or WITHHOLD. It has always been
correct and has never had anything to tell it who was present -- `persons` was
supplied by callers who did not know either. This is that input.

THE ASYMMETRY IS INHERITED, NOT INVENTED HERE. Withholding something the owner
wanted costs a re-ask; showing something private to a stranger cannot be undone.
So `clear()` is an explicit act and time never clears it: a declaration that
expired on a timer would silently return VESPER to speaking freely in a room the
owner never said had emptied.

ITS CHECK RUNS UNREGISTERED, AND IT IS THE THIRD. `INV-PRIV-1` is the rule this
implements -- "unknown person in the target space ... implies private content is
withheld or routed to the most private surface" -- and it is enforced only by
acceptance tests A-009 and A-010, with no SR naming it. So there is no honest
requirement for a CI check to trace to.

That makes three checks now running and claiming nothing: the redactor before
INV-PRIV-7 was ratified, the Arabizi transliterator, and this. The pattern is
worth the owner's attention rather than three separate footnotes -- the corpus
has capabilities whose rules were never written into the invariant set, and each
one costs a gate that cannot be reported as coverage.

THIS IS NOT IDENTITY. It answers "is anyone else here", which is the half of
failure mode 8 that speaker verification structurally cannot reach -- a verified
owner can have someone standing beside them. `docs/design/VISION-IDENTITY.md`
carries the design that answers both halves once cameras exist; the flag written
here is the same flag that design sets, so the consumers do not change when the
source does.
"""

from __future__ import annotations

import threading
from typing import Any

from .world import UNKNOWN_PERSON, Observation

# Owner-driven, fixed, matched on the whole utterance or as a contained phrase.
# Deliberately NOT inferred: a rule that guesses whether the owner meant it will
# be wrong in the direction of disclosing.
SOMEONE_PRESENT = (
    "someone is with me", "someone's with me", "someone here with me",
    "i'm not alone", "i am not alone", "there's someone here",
    "there is someone here", "we have company", "not alone right now",
    "someone else is here",
)
ALONE_AGAIN = (
    "i'm alone", "i am alone", "we're alone", "they left", "they've left",
    "they have left", "alone again", "just me now", "nobody else here",
)

# The world fact both this and the future vision layer write.
SUBJECT = "world.owner"
ATTRIBUTE = "presence"

ALONE = "alone"
WITH_OTHERS = "with_unknown_people"


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").split())


class Presence:
    """The owner's declaration of who is in the room with them."""

    def __init__(self, world: Any, clock: Any, *, bus: Any = None) -> None:
        self._world = world
        self._clock = clock
        self._bus = bus
        self._lock = threading.RLock()
        self._state = ALONE

    def offer(self, text: str) -> dict | None:
        """Read an utterance for a declaration. Returns what changed, or None.

        RETURNS None FOR ORDINARY SPEECH so a caller can pass every utterance
        through without branching. The declaration is a side channel, not a
        command -- the owner saying "someone is with me" is also a sentence
        VESPER should hear and answer.
        """
        flat = _norm(text)
        if not flat:
            return None
        if any(p in flat for p in SOMEONE_PRESENT):
            return self.set(WITH_OTHERS, said=text)
        if any(p in flat for p in ALONE_AGAIN):
            return self.set(ALONE, said=text)
        return None

    def set(self, state: str, *, said: str = "") -> dict:
        if state not in (ALONE, WITH_OTHERS):
            raise ValueError(f"presence must be {ALONE!r} or {WITH_OTHERS!r}")
        with self._lock:
            previous, self._state = self._state, state
        # NO TTL. A presence declaration that expired on a timer would return
        # VESPER to speaking freely in a room the owner never said had emptied,
        # and the owner would have no way to know it had happened.
        self._world.apply(Observation(
            subject=SUBJECT, attribute=ATTRIBUTE, value=state,
            observed_at_hlc=self._clock.now(), source="owner_declaration",
            trust_class="owner"))
        out = {"presence": state, "previous": previous, "said": said[:120],
               "source": "owner_declaration"}
        if self._bus is not None:
            self._bus.publish("presence.declared", subject=SUBJECT,
                              payload=out, component="presence")
        return out

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def persons(self) -> tuple:
        """The `persons` tuple `core/privacy.py` routes on.

        `UNKNOWN_PERSON` IS THE POINT. `PrivacyRouter._is_ambiguous` treats its
        presence as ambiguity, and every ambiguous cell resolves to the most
        private surface available or to WITHHOLD. So declaring company does not
        need a new rule anywhere -- it feeds the rule that already exists, and
        the routing that was already correct starts being correct about a room
        it can finally hear about.
        """
        return ("owner",) if self.state == ALONE else ("owner", UNKNOWN_PERSON)
