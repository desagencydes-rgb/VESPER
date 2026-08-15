"""Privacy routing — the ambiguous cell always resolves the private way.

A-010 PART B IS A FULL CROSS-PRODUCT, and the assertion that matters is not
"most cells are right" but this: **in EVERY ambiguous cell the outcome is the
most private available surface or WITHHOLD, never the most public.**

    privacy_class      x  persons present            x  location confidence
    {public, personal,    {none, owner, owner+known,    {high, low, UNKNOWN}
     private}             owner+unknown, unknown_only}

THE DEFAULT THAT MAKES THIS FAIL is routing by capability -- "use the largest
available display", "use the nearest endpoint". It reads as helpful and it is
the exact behaviour that shows a private message on the living-room screen while
a guest is standing there. A-010's mandatory negative control is precisely that
build, and it must fail every `owner+unknown` and low-confidence cell.

THE ASYMMETRY IS DELIBERATE, and it is the same shape as the cost rule in
`core/cost.py`: the two error directions do not cost the same. Withholding
something the owner wanted costs a re-ask. Displaying something private to a
stranger cannot be undone. So ambiguity resolves toward the cheap failure, every
time, and `UNKNOWN` confidence is treated exactly as `low` rather than as a
missing input to be guessed at (INV-EVID-3).

INV-PRIV-2: physiological and mood inference is owner-only, local-only and
NON-EXPORTABLE. `export_inference` refuses rather than filtering, because a
filter is a thing that can be misconfigured and a refusal is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bus import EventBus
from .world import UNKNOWN, UNKNOWN_PERSON

PRIVACY_CLASSES = ("public", "personal", "private")
CONFIDENCE = ("high", "low", UNKNOWN)

# Ordered MOST PRIVATE first. "Most private available" means the first entry in
# this list that the target space actually offers.
SURFACE_PRIVACY_ORDER = ("private_earpiece", "personal_handheld",
                         "shared_display", "public_display")
WITHHOLD = "WITHHOLD"

# Which surfaces are acceptable for each privacy class when the space is CLEAN
# (owner alone, high confidence). Anything less clean narrows this further.
MAX_EXPOSURE = {
    "public": "public_display",
    "personal": "personal_handheld",
    "private": "private_earpiece",
}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    surface: str
    privacy_class: str
    persons: tuple
    location_confidence: str
    ambiguous: bool
    reason: str

    def to_dict(self) -> dict:
        return {"surface": self.surface, "privacy_class": self.privacy_class,
                "persons": list(self.persons),
                "location_confidence": self.location_confidence,
                "ambiguous": self.ambiguous, "reason": self.reason}


class PrivacyRouter:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    @staticmethod
    def _is_ambiguous(persons: tuple, confidence: str) -> bool:
        """Ambiguity is any of: a stranger present, or unsure where the owner is.

        `UNKNOWN` confidence counts as ambiguous rather than as a missing input
        to be filled in -- INV-EVID-3, one layer up.
        """
        return (UNKNOWN_PERSON in persons
                or confidence in ("low", UNKNOWN))

    def route(self, *, privacy_class: str, persons: tuple,
              location_confidence: str, available: tuple,
              subject: str = "scene") -> RoutingDecision:
        if privacy_class not in PRIVACY_CLASSES:
            raise ValueError(f"privacy_class must be one of {PRIVACY_CLASSES}")
        if location_confidence not in CONFIDENCE:
            raise ValueError(f"location_confidence must be one of {CONFIDENCE}")

        ambiguous = self._is_ambiguous(persons, location_confidence)

        # The ceiling: how public may this content ever be, before ambiguity.
        ceiling = MAX_EXPOSURE[privacy_class]
        ceiling_rank = SURFACE_PRIVACY_ORDER.index(ceiling)

        if ambiguous:
            # Every ambiguous cell collapses to the MOST PRIVATE available
            # surface, or WITHHOLD when none is private enough. Never the most
            # public, never "the largest display".
            reason_bits = []
            if UNKNOWN_PERSON in persons:
                reason_bits.append("an unidentified person is in the target space")
            if location_confidence in ("low", UNKNOWN):
                reason_bits.append(f"location confidence is {location_confidence}")
            # Under ambiguity, private content will not go to a shared surface
            # at all; personal content is pulled down to handheld-or-better.
            allowed_rank = 0 if privacy_class == "private" else min(
                ceiling_rank, SURFACE_PRIVACY_ORDER.index("personal_handheld"))
            candidates = [s for s in SURFACE_PRIVACY_ORDER[:allowed_rank + 1]
                          if s in available]
            surface = candidates[0] if candidates else WITHHOLD
            reason = ("ambiguous cell: " + " and ".join(reason_bits)
                      + f" -> most private available ({surface}). Withholding "
                        "costs a re-ask; showing private content to a stranger "
                        "cannot be undone.")
            d = RoutingDecision(surface, privacy_class, tuple(persons),
                                location_confidence, True, reason)
            self._bus.publish("presence.routed_private", subject=subject,
                              payload=d.to_dict(), component="privacy")
            return d

        # Unambiguous: owner alone (or with known persons) and confident.
        candidates = [s for s in SURFACE_PRIVACY_ORDER[:ceiling_rank + 1]
                      if s in available]
        surface = candidates[-1] if candidates else WITHHOLD
        d = RoutingDecision(surface, privacy_class, tuple(persons),
                            location_confidence, False,
                            f"unambiguous: exposure ceiling for {privacy_class!r} "
                            f"is {ceiling}")
        self._bus.publish("presence.routed", subject=subject, payload=d.to_dict(),
                          component="privacy")
        return d

    def export_inference(self, kind: str, person_role: str, *,
                         destination: str) -> None:
        """INV-PRIV-2. Physiological/mood inference is NON-EXPORTABLE.

        Refuses rather than filtering. A filter is a thing that can be
        misconfigured; a refusal is not. A-039.4 asserts this by attempting an
        export and observing the refusal, which is why this raises rather than
        returning a redacted payload.
        """
        SENSITIVE = ("physiological", "mood", "affect", "biometric")
        if kind in SENSITIVE:
            self._bus.publish(
                "privacy.export_refused", subject=kind,
                payload={"kind": kind, "person_role": person_role,
                         "destination": destination,
                         "reason": ("INV-PRIV-2: owner-only, local-only, "
                                    "non-exportable. Refused rather than "
                                    "filtered -- a filter can be misconfigured.")},
                component="privacy")
            raise PermissionError(
                f"{kind!r} inference is non-exportable (INV-PRIV-2); refused "
                f"export to {destination!r}")
        if kind in SENSITIVE and person_role != "owner":
            raise PermissionError(f"{kind!r} inference runs for the owner only")
