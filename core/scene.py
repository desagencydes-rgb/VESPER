"""Semantic scenes — one scene, many endpoints, degradation always reported.

THE ARCHITECTURAL CLAIM THIS FILE EXISTS TO MAKE TRUE: a scene carries what an
element MEANS, never how it looks. A `diagram` is a typed graph, not a PNG. That
single decision is what lets the same scene reach a screen, a voice-only
endpoint and a glass surface — because **a rendered image cannot be narrated,
and a typed graph can**. If `content` ever carried markup, coordinates, fonts or
colours, the scene would be a screen layout in disguise and the voice rung would
have nothing to work with but an apology.

INV-SCENE-2: DEGRADATION IS ALWAYS REPORTED, NEVER SILENT. `degradations` is
required on every render result **even when empty**, because an absent array is
indistinguishable from an unreported drop. That is the difference between "this
endpoint showed everything" and "this endpoint quietly showed less and nobody
recorded it".

THE VOICE ROW IS THE POINT (the ladder's own words). `spatial_class = none` must
produce something INTELLIGIBLE rather than a refusal. A-009's negative control
is a `{markdown, speech}` implementation, which cannot produce a degradation
report at all — it has no typed elements to degrade, so it either renders or
does not, and it can never say what was lost.

`action` IS DRAWN FROM A CLOSED ENUM, not free text. A ladder that invents its
own vocabulary produces degradation records no renderer can emit and no consumer
can branch on.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bus import EventBus

REPO = Path(__file__).resolve().parents[1]

ELEMENT_TYPES = ("text", "metric", "table", "code", "diagram", "image",
                 "timeline", "entity_ref", "state_indicator", "live_binding")

SPATIAL_CLASSES = ("volumetric", "pseudo_3d_glass", "2d", "linear", "none")

# semantic_scene.schema.json#/$defs/renderResult -- closed by design.
DEGRADATION_ACTIONS = ("depth_flattened", "visual_to_narrative", "truncated",
                       "summarised", "omitted", "deferred")

UPDATE_MODES = ("replace", "patch", "append", "stream")


class SceneContractViolation(Exception):
    """A scene or render result that breaks the semantic-scene contract."""


@dataclass(slots=True)
class SceneElement:
    element_id: str
    type: str
    content: Any
    priority: int = 50
    persistence: str = "session"
    privacy_class: str = "personal"
    attention_cost: str = "low"
    spatial_intent: str = "inline"

    def __post_init__(self) -> None:
        if self.type not in ELEMENT_TYPES:
            raise SceneContractViolation(
                f"element type {self.type!r} not in {ELEMENT_TYPES}")
        # A scene carrying styling would be a screen layout in disguise, and
        # the voice endpoint would have nothing to narrate.
        if isinstance(self.content, str):
            for marker in ("<div", "<span", "style=", "#RRGGBB", "font-size"):
                if marker in self.content:
                    raise SceneContractViolation(
                        f"element {self.element_id!r} carries presentation markup "
                        f"({marker!r}). A scene carries what an element MEANS, "
                        "never how it looks -- a rendered image cannot be "
                        "narrated, and a typed graph can.")

    def to_dict(self) -> dict:
        return {"element_id": self.element_id, "type": self.type,
                "content": self.content,
                "presentation_intent": {
                    "priority": self.priority, "persistence": self.persistence,
                    "privacy_class": self.privacy_class,
                    "attention_cost": self.attention_cost},
                "spatial_intent": self.spatial_intent}


@dataclass(slots=True)
class SemanticScene:
    scene_id: str
    intent: dict
    elements: list
    update_mode: str = "replace"
    lifetime: dict = field(default_factory=lambda: {"kind": "session"})

    def __post_init__(self) -> None:
        if self.update_mode not in UPDATE_MODES:
            raise SceneContractViolation(
                f"update_mode {self.update_mode!r} not in {UPDATE_MODES}")


@dataclass(slots=True)
class EndpointCapability:
    endpoint_id: str
    spatial_class: str
    modalities: tuple
    max_elements: int = 16

    def __post_init__(self) -> None:
        if self.spatial_class not in SPATIAL_CLASSES:
            raise SceneContractViolation(
                f"spatial_class {self.spatial_class!r} not in {SPATIAL_CLASSES}")


@dataclass(slots=True)
class RenderResult:
    rendered: bool
    endpoint_id: str | None
    # REQUIRED even when empty. An absent array is indistinguishable from an
    # unreported drop (INV-SCENE-2).
    degradations: list = field(default_factory=list)
    withheld_reason: str | None = None
    output: Any = None

    def to_dict(self) -> dict:
        return {"rendered": self.rendered, "endpoint_id": self.endpoint_id,
                "degradations": list(self.degradations),
                "withheld_reason": self.withheld_reason}


class SceneRenderer:
    """Renders one semantic scene against any endpoint capability descriptor.

    The ladder is READ FROM THE CONTRACT, not hardcoded. Same reasoning as the
    governed-path list in `core/selfmod.py`: a hardcoded copy drifts, and the
    drift is invisible until an element type silently renders differently from
    what the contract says it should.
    """

    def __init__(self, bus: EventBus, *, ladder_path: Path | None = None) -> None:
        self._bus = bus
        self._ladder = self._load_ladder(
            ladder_path or (REPO / "contracts" / "policy" / "degradation_ladder.toml"))

    @staticmethod
    def _load_ladder(path: Path) -> dict:
        """Read the ladder in the shape the artifact actually uses.

        `[[element]]` array-of-tables, each with a `rung` array keyed by
        `spatial_class`. A first version assumed nested `[type.spatial_class]`
        tables and silently loaded ZERO rungs -- parsing succeeded, the dict was
        empty, and every `rung()` lookup returned None. Reading a contract is
        not the same as reading it correctly, so `rung_count()` exists to let a
        test assert the ladder was actually loaded.
        """
        if not path.exists():
            return {}
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        out: dict = {}
        for entry in doc.get("element", ()):
            etype = entry.get("type")
            for rung in entry.get("rung", ()):
                sclass = rung.get("spatial_class")
                if etype and sclass:
                    out[(etype, sclass)] = rung
        return out

    def rung_count(self) -> int:
        """How many rungs were loaded. An empty ladder is a parsing failure."""
        return len(self._ladder)

    def rung(self, element_type: str, spatial_class: str) -> dict | None:
        return self._ladder.get((element_type, spatial_class))

    def render(self, scene: SemanticScene, endpoint: EndpointCapability, *,
               withhold_reason: str | None = None) -> RenderResult:
        if withhold_reason:
            # Withholding is REPORTED, never silent (privacy fail-safe).
            r = RenderResult(False, endpoint.endpoint_id, [],
                             withheld_reason=withhold_reason)
            self._bus.publish("presence.withheld", subject=scene.scene_id,
                              payload=r.to_dict(), component="scene")
            return r

        degradations: list = []
        pieces: list = []
        # Highest priority first, so a max_elements cut drops the least
        # important rather than whatever happened to be last in the list.
        for el in sorted(scene.elements, key=lambda e: -e.priority):
            if len(pieces) >= endpoint.max_elements:
                degradations.append({
                    "element_id": el.element_id,
                    "reason": (f"endpoint holds {endpoint.max_elements} elements; "
                               "lowest-priority elements dropped first"),
                    "action": "omitted"})
                continue
            rendered, deg = self._render_element(el, endpoint)
            if deg is not None:
                degradations.append(deg)
            if rendered is not None:
                pieces.append(rendered)

        for d in degradations:
            if d["action"] not in DEGRADATION_ACTIONS:
                raise SceneContractViolation(
                    f"degradation action {d['action']!r} is outside the closed "
                    f"enum {DEGRADATION_ACTIONS}. A ladder that invents its own "
                    "vocabulary produces records no renderer can emit.")

        r = RenderResult(True, endpoint.endpoint_id, degradations, output=pieces)
        self._bus.publish("presence.rendered", subject=scene.scene_id,
                          payload={**r.to_dict(),
                                   "spatial_class": endpoint.spatial_class,
                                   "element_count": len(pieces)},
                          component="scene")
        return r

    def _render_element(self, el: SceneElement,
                        ep: EndpointCapability) -> tuple:
        """Return (rendered_piece_or_None, degradation_or_None)."""
        sc = ep.spatial_class

        # Voice-only. THE ROW THAT MATTERS: produce something intelligible.
        if sc == "none":
            narration = self._narrate(el)
            if el.type in ("diagram", "image", "table", "timeline"):
                return narration, {
                    "element_id": el.element_id,
                    "reason": (f"{el.type} has no visual surface on a "
                               "voice-only endpoint; narrated from its typed "
                               "structure"),
                    "action": "visual_to_narrative"}
            return narration, None

        # Flat surfaces lose depth but keep everything else.
        if sc in ("2d", "linear") and el.spatial_intent in ("depth", "layered"):
            return self._flatten(el), {
                "element_id": el.element_id,
                "reason": f"endpoint spatial_class {sc} has no depth axis",
                "action": "depth_flattened"}

        # An image cannot be shown on a linear surface at all.
        if sc == "linear" and el.type == "image":
            return None, {"element_id": el.element_id,
                          "reason": "linear endpoint cannot present an image",
                          "action": "omitted"}

        return {"element_id": el.element_id, "type": el.type,
                "content": el.content}, None

    @staticmethod
    def _narrate(el: SceneElement) -> dict:
        """Derive speech from TYPED content. Only possible because it is typed.

        This is the payoff of refusing markup in `content`. A diagram stored as
        a PNG has nothing to say; a diagram stored as nodes and edges narrates
        itself.
        """
        c = el.content
        if el.type == "diagram" and isinstance(c, dict):
            nodes = c.get("nodes", [])
            edges = c.get("edges", [])
            text = (f"A diagram of {len(nodes)} parts. "
                    + "; ".join(f"{a} leads to {b}" for a, b in edges[:6]))
        elif el.type == "table" and isinstance(c, dict):
            rows = c.get("rows", [])
            cols = c.get("columns", [])
            text = (f"A table of {len(rows)} rows by {len(cols)} columns. "
                    f"Columns: {', '.join(map(str, cols))}.")
        elif el.type == "metric":
            text = f"{c}" if not isinstance(c, dict) else \
                f"{c.get('label', 'value')} is {c.get('value')}"
        elif el.type == "state_indicator":
            text = f"Status: {c}"
        elif el.type == "timeline" and isinstance(c, dict):
            text = f"A timeline with {len(c.get('events', []))} events."
        elif el.type == "image":
            text = f"An image: {c.get('alt', 'no description available')}" \
                if isinstance(c, dict) else "An image."
        else:
            text = str(c)
        return {"element_id": el.element_id, "type": el.type, "speech": text}

    @staticmethod
    def _flatten(el: SceneElement) -> dict:
        return {"element_id": el.element_id, "type": el.type,
                "content": el.content, "depth": "flattened"}
