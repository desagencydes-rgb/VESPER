"""The state projection — one read-only answer to "what is true now", for every surface.

THE ARCHITECTURAL CLAIM THIS FILE EXISTS TO MAKE TRUE: a surface never reaches
into a runtime module. It reads a projection. The island has six status columns;
the home has ninety cards. Six ad-hoc couplings would be survivable and ninety
would not, and the ninety would each have their own idea of what "unknown" looks
like.

INV-HW-2 IS ENFORCED HERE STRUCTURALLY, NOT DOCUMENTED HERE. A `Reading` cannot
hold a value without provenance, and cannot hold provenance without a value. The
failure this prevents is specific and was drawn in the owner's own reference: a
status column reading `41 °C` on a host that does not expose a temperature,
because the column looked empty without one. `to_scene()` OMITS an unavailable
reading rather than rendering a placeholder for it, so the absent case cannot be
styled into looking like the present case.

ZERO IS A VALUE. `None` IS NOT. Every test here is `is None`, never truthiness:
"0 approvals waiting" is a real and useful answer, and `MEMORY.md` already
records the shape of this mistake on this platform -- zeros compress to nothing,
and a metric that reads zero because nobody measured it is indistinguishable
from one that is genuinely zero unless the two are kept structurally apart.

A MEASUREMENT WITHOUT ITS AGE IS NOT A MEASUREMENT. `320k assertions` with no
"when" is exactly the claim INV-HW-2 exists to refuse, so a `Reading` may carry a
`ttl_ms` and goes UNAVAILABLE when it expires. It does not go stale, because a
stale number renders identically to a fresh one and nobody can see the
difference.

INV-COORD-4: projections are ordered by HLC and by nothing else. `supersedes()`
is the only comparison, and it does not look at a wall clock. Asking "is this
reading older than its TTL" is a duration, not an ordering, and is fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from .hlc import HLC
from .scene import SceneElement, SemanticScene


class ProjectionContractViolation(Exception):
    """Raised where a projection would have carried a number nobody measured."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One thing a surface may show, or the recorded reason there is nothing to show.

    Frozen for the same reason `HLC` is: a reading that can be mutated after it
    is stamped is not an observation, it is a variable that happens to hold one.
    """

    key: str
    source: str
    value: Any = None
    unit: str | None = None
    observed_at: HLC | None = None
    ttl_ms: int | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        has_value = self.value is not None
        has_reason = self.unavailable_reason is not None

        if has_value and has_reason:
            raise ProjectionContractViolation(
                f"reading {self.key!r} carries both a value and an unavailable "
                "reason. One or the other -- a value with an excuse attached is "
                "how a placeholder gets rendered as a measurement.")
        if not has_value and not has_reason:
            raise ProjectionContractViolation(
                f"reading {self.key!r} has no value and no reason. INV-HW-2: "
                "UNKNOWN means UNAVAILABLE, and an unavailable reading must say "
                "why or a surface cannot explain itself to the owner.")
        if has_value and self.observed_at is None:
            raise ProjectionContractViolation(
                f"reading {self.key!r} carries a value with no observation time. "
                "A measurement without its age is not a measurement -- it is a "
                "number that will still look fresh an hour from now.")
        if has_reason and self.observed_at is not None:
            raise ProjectionContractViolation(
                f"reading {self.key!r} is unavailable but carries an observation "
                "time. Nothing was observed, so there is no time to record.")
        if self.ttl_ms is not None and self.ttl_ms <= 0:
            raise ProjectionContractViolation(
                f"reading {self.key!r} has ttl_ms={self.ttl_ms}. A non-positive "
                "TTL expires on arrival, which is a way of spelling 'unavailable' "
                "that no reader will notice.")

    @property
    def known(self) -> bool:
        return self.value is not None

    def age_ms(self, now: HLC) -> int | None:
        """How old this reading is. A DURATION, not an ordering -- INV-COORD-4
        governs which of two things came first, and this asks neither."""
        if self.observed_at is None:
            return None
        return max(0, now.physical_ms - self.observed_at.physical_ms)

    def expired(self, now: HLC) -> bool:
        if self.ttl_ms is None or self.observed_at is None:
            return False
        age = self.age_ms(now)
        return age is not None and age > self.ttl_ms

    def at(self, now: HLC) -> "Reading":
        """This reading as of `now`. An expired reading becomes UNAVAILABLE and
        says so, rather than continuing to render its last value."""
        if not self.expired(now):
            return self
        return Reading(
            key=self.key, source=self.source,
            unavailable_reason=f"expired: {self.age_ms(now)} ms old, ttl {self.ttl_ms} ms")

    @staticmethod
    def unavailable(key: str, source: str, reason: str) -> "Reading":
        return Reading(key=key, source=source, unavailable_reason=reason)


@dataclass(frozen=True, slots=True)
class Projection:
    """Everything true at one point in the total order."""

    version: HLC
    readings: Mapping[str, Reading] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Reading:
        return self.readings[key]

    def __contains__(self, key: str) -> bool:
        return key in self.readings

    def __iter__(self) -> Iterator[str]:
        return iter(self.readings)

    def supersedes(self, other: "Projection") -> bool:
        """The ONLY comparison between two projections. INV-COORD-4 -- ordering
        is the HLC's job, and a projection assembled on a node whose wall clock
        drifted must not thereby win."""
        return other.version < self.version

    def known(self, now: HLC | None = None) -> dict[str, Reading]:
        at = now or self.version
        return {k: r for k, r in ((k, r.at(at)) for k, r in self.readings.items()) if r.known}

    def to_scene(self, scene_id: str, *, columns: tuple[str, ...] | None = None) -> SemanticScene:
        """The projection as a scene, for any endpoint.

        UNAVAILABLE READINGS ARE OMITTED, NOT RENDERED EMPTY. This is the line
        INV-HW-2 is enforced on: a column that produces no element cannot be
        styled to look like a column that produced one, and a renderer cannot
        decide to fill it in. An endpoint that wants to explain the gap reads
        `unavailable_reason` deliberately; it never gets it by accident.
        """
        keys = columns if columns is not None else tuple(self.readings)
        elements = []
        for key in keys:
            r = self.readings.get(key)
            if r is None:
                continue
            r = r.at(self.version)
            if not r.known:
                continue
            content: dict[str, Any] = {"label": r.key, "value": r.value,
                                       "observed_at": r.observed_at.to_dict()}
            if r.unit is not None:
                content["unit"] = r.unit
            elements.append(SceneElement(
                element_id=r.key, type="metric", content=content,
                # A status column is glanceable by construction. Anything that
                # needs more attention than that is an Alert, not a column.
                attention_cost="low", spatial_intent="inline"))
        return SemanticScene(
            scene_id=scene_id,
            intent={"purpose": "status", "surface_agnostic": True},
            elements=elements,
            update_mode="replace",
            lifetime={"kind": "session"},
        )


# The island's six status columns, in the order the owner's reference draws them.
# Declared here rather than in the island because the columns are a projection
# concern: a headless node renders the same six to `linear`, and the home reads
# the same keys. See docs/design/ISLAND-ARCHITECTURE.md §4.
ISLAND_COLUMNS: tuple[str, ...] = (
    "fabric.summary",
    "verification.placement_stress",
    "day.agenda",
    "autonomy.state",
    "authorize.pending",
    "scene.next_ambience",
)

# The home's metrics card, §14.2. FIVE keys, and today most of them have no
# producer -- which is the point: `to_scene` omits an unavailable reading
# rather than rendering a placeholder, so the card shows what is true and
# leaves the rest blank. A plausible-looking figure here is the exact defect
# `projection-unknown-is-absent` refuses.
#
# Keyed by what they MEAN rather than by the row label, because the same
# reading feeds a voice endpoint that has no rows at all.
HOME_METRIC_KEYS: tuple = (
    "model.thinking",
    "model.context_tokens",
    "model.cache",
    "model.tokens_per_sec",
    "host.power_source",
)
