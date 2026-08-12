# REM-009 — `SemanticScene` contract and endpoint capability negotiation

| | |
|---|---|
| **Closes** | AR-001 (P0) · GAP-018 · GAP-048 |
| **Decision record** | **This specification** discharges Foundation **ADR-008** (presence transport); no separate filing. See `docs/ADR/ADR-REGISTER.md`. |
| **Owner** | Presence & Interaction Engineer |
| **Blocked by** | REM-001 (streaming updates carry HLC), REM-011 §world-model (spatial anchoring needs the space graph) |
| **Blocks** | every producer of user-visible output |

---

## 1. Problem

**The artifact on which the entire "VESPER is not a chat UI" claim rests is one sentence.**

> COC IC-005 — Presence Contract, in full: *"Semantic scene + modality requirements → selected rendering endpoint → interaction events."*

That is a name and an arrow. Without a schema, the first renderer defines a scene as `{markdown, speech}`, and `A-009` — *"Deliver the same semantic scene through at least two different output surfaces"* — is satisfied by rendering the same markdown string twice, once to a screen and once to a TTS engine. Every stated rule still reads as satisfied. The projector, glass and holographic adapters then cannot be built on it, because there is nothing in the payload that describes *what the content is* rather than *how it was written*.

This is the largest rework surface in the project: retrofitting a semantic scene means rewriting **every producer of user-visible output**, not just the renderers.

## 2. Authoritative requirement

| Source | Text |
|---|---|
| **ARCH-20** | *"Visual output is represented as a **semantic scene** rather than a device-specific screen dump."* |
| **ARCH-06** | *"Vesper must not require a chat box as its default interface. Text/keyboard remains an explicit fallback/manual control channel."* · *"Presence must support graceful migration."* |
| **DR-010** | *"Visual content is represented semantically so it can be rendered across 2D, projector, glass, holographic, and future spatial surfaces."* |
| **DR-004** | Presence engine selects surfaces by context, capability and policy |
| **DR-021 / RB-022** | No silent capability loss — degradation must be reported |
| **SR-046** | *"No text only or keyboard only (those are active only when I activate them…)"* |
| **SR-002 / SR-018 / SR-028** | Projector, glass, 3D hologram, per-display placement |
| **ARCH-28** | *"Do not reduce holographic/spatial output to a decorative animation requirement."* |
| **P-003** | Presence is a first-class capability, not a cosmetic UI layer |

## 3. Affected subsystems

`SPEC-15 Semantic scene` · `SPEC-16 Presence / interaction` · `SPEC-17 Endpoint capability negotiation` · every subsystem that produces user-visible output · `SPEC-06 World model` (spatial anchoring).

## 4. Required behaviour

### 4.1 `SemanticScene`

```
SemanticScene {
  scene_id, schema_version, correlation_id, created_at_hlc,
  intent: { purpose, urgency, privacy_class, expected_dwell },
  elements: [ SceneElement ],
  update_mode: replace | patch | append | stream,
  lifetime: { ttl, persist_until_acked }
}

SceneElement {
  element_id,
  type: text | metric | table | code | diagram | image | timeline
      | entity_ref | state_indicator | live_binding,
  content,                          # typed per element type
  presentation_intent: {            # INTENT, never styling
    priority, persistence, ephemerality, privacy_class, attention_cost
  },
  spatial_intent: user_relative | space_anchored(SpaceRef)
                | surface_relative | unanchored,
  affordances: [ declared capability ]   # a capability, NOT an event handler
}
```

**Four properties are load-bearing, and each excludes a specific wrong implementation:**

| Property | Excludes |
|---|---|
| `presentation_intent` carries **intent, not styling** (`priority`, `persistence`, `attention_cost`) — never fonts, colours, coordinates | A scene that is a screen layout in disguise |
| `spatial_intent` is **relational** (`user_relative`, `space_anchored`), resolved against the world-model space graph at render time | A scene that hard-codes a display |
| `affordances` declare a **capability** ("this entity can be opened"), not a handler | A scene that is a serialised DOM |
| **There is no free-form markdown escape hatch anywhere in the schema** | The `{markdown, speech}` degenerate scene |

The last one is the single most important line in this REM. A markdown field is a hole through which the whole contract drains, because every producer will use it and no spatial renderer can consume it.

### 4.2 `EndpointCapability` and negotiation

```
EndpointCapability {
  endpoint_id, modalities, resolution_class, spatial_class,
  text_capacity, color, audio, interaction_classes,
  latency_class, privacy_class
}
```

`spatial_class ∈ { none, 2d, 2d_projected, pseudo_3d_glass, volumetric }` — this is the field that makes the glass-cube and projector targets first-class rather than special cases.

**Renderer contract:**

```
render(scene, endpoint_capability) ->
    { rendered: bool, degradations: [ {element_id, reason, action} ] }
```

> **Every element type declares a degradation ladder per capability class, and degradation is ALWAYS reported, never silent** (RB-022, DR-021).

Example ladder for `diagram`:

| Endpoint `spatial_class` | Rendering | Degradation reported |
|---|---|---|
| `volumetric` / `pseudo_3d_glass` | Spatial diagram with depth-separated layers | none |
| `2d_projected` / `2d` | Flat diagram | `depth_flattened` |
| `none` (voice only) | Spoken structural summary: nodes, edges, the one relationship that matters | `visual_to_narrative` |

The voice row is why the schema must carry *what the diagram means*, not an image. A rendered PNG cannot be narrated; a typed graph can.

### 4.3 Streaming and progressive presence

`update_mode: stream` is an **architectural** requirement, not an optimisation: SR-047 demands realtime interaction, and REM-010's latency budget requires **first audio to begin before generation completes**. A scene that can only be delivered complete makes the budget unmeetable by construction.

Streamed scene patches carry HLC (REM-001), so out-of-order patch arrival is resolved by the same supersession rule as world facts rather than by a second mechanism.

### 4.4 Migration

When an endpoint disappears mid-scene, the presence engine re-runs endpoint selection for the *scene*, not for the *pixels*, and re-renders against the new capability descriptor with a fresh degradation report. Because the scene is semantic, migration from a projector to voice is a re-render, not a translation.

### 4.5 Privacy routing (binds to REM-011)

`select_endpoint(scene.intent.privacy_class, space.privacy_class, observed_persons, user_location_confidence)`

> **FAIL-SAFE:** if `user_location_confidence < threshold` **or** an unknown person is present in the target space, route to the most private available surface or **WITHHOLD**. Never default to the most public surface.

The default matters: the natural implementation routes to the biggest available display, which is the projector, which is the one a guest can read.

## 5. Ownership and authority

| Concern | Owner | Authority |
|---|---|---|
| `SemanticScene` schema | Presence & Interaction Engineer | `E2`/`E3`; schema change requires an ADR (`CI-001`) |
| Degradation ladders per element type | Presence & Interaction Engineer | `E2` |
| Endpoint capability declarations | Device/Network Engineer | `E2`; measured at enrollment, not declared (REM-011) |
| Privacy routing thresholds | **Project Owner** | Configuration |

## 6. Interfaces

| Interface | Change |
|---|---|
| `IC-005` Presence | Becomes the full schema above; `render()` returns a degradation report |
| `IC-004` Device | Adds `EndpointCapability` |
| `IC-001` Event | `presence.scene_emitted`, `presence.degraded`, `presence.endpoint_migrated`, `presence.withheld` |

Contracts: `contracts/entities/semantic_scene.schema.json`, `contracts/entities/endpoint_capability.schema.json`.

## 7. Invariants

| ID | Statement |
|---|---|
| **INV-SCENE-1** | No output reaches a user except as a `SemanticScene`. No renderer may require a field outside the schema. |
| **INV-SCENE-2** | Every dropped or degraded element is reported in `degradations`. Silent degradation is prohibited. |
| **INV-SCENE-3** | The schema contains no free-form markdown or HTML escape hatch. A string field is typed `text` with `presentation_intent`, or it does not exist. |
| **INV-SCENE-4** | `spatial_intent` is relational and resolved at render time against the world-model space graph. No producer names an endpoint. |
| **INV-PRIV-1** | Unknown person in the target space, or low location confidence ⇒ private content is withheld or routed to the most private surface. |

## 8. Failure behaviour

| Failure | Behaviour |
|---|---|
| No endpoint satisfies the scene's minimum modality | `presence.withheld` + queued for the next capable surface. Never downgraded past its privacy class. |
| Endpoint disappears mid-stream | Re-select and re-render (§4.4); the spoken prefix already committed is **semantically resumed**, never silently restarted (REM-011) |
| Renderer cannot handle an element type | Degrade per the declared ladder and report; a renderer with no ladder entry for a type fails registration |
| Producer emits a scene with an undeclared element type | Rejected at the contract boundary; `CI-028` catches it earlier |
| Space graph unavailable | `spatial_intent` resolves to `unanchored`; privacy routing **fails safe** (withhold) rather than guessing a space |

## 9. Recovery

Scenes are re-renderable from their semantic form, so recovery after an endpoint or renderer failure is re-selection plus re-render. `lifetime.persist_until_acked` ensures a scene that mattered is not lost when its surface dies — which is the presence-layer analogue of REM-002's checkpointing.

## 10. Contract / state machine / decision function

| Artifact | ID / path |
|---|---|
| Scene schema | `contracts/entities/semantic_scene.schema.json` |
| Endpoint capability | `contracts/entities/endpoint_capability.schema.json` |
| Scene lifecycle | `SM-SCENE` (`CREATED → RENDERED → UPDATED → MIGRATED → EXPIRED / ACKED / WITHHELD`) |
| Endpoint selection | `DF-SELECT-ENDPOINT` |
| Degradation resolution | `DF-DEGRADE` |

## 11. Verification

**`A-009` strengthened.** One scene fixture → **three renderers with materially different capability descriptors**: a 2D screen, a **voice-only** endpoint, and a **spatial simulator** (`pseudo_3d_glass`).
- All three produce output.
- All three produce an **explicit degradation report**.
- The voice-only render of a `diagram` element is a **structural narration**, not a filename or an apology.

**`A-026` — no chat required (the SR-046 test that does not currently exist).** Boot with **every text/chat surface disabled**. Assert every core capability is reachable and every scene renders. A build whose control path requires a text box **fails**.

**Negative tests, both mandatory:**
- Assert **no markdown/HTML string escape hatch exists** in the schema — a structural assertion over the JSON Schema, not a review.
- Assert a renderer that drops an element **without** reporting it fails the contract test.

**Negative control.** `A-009` must be shown **FAILING** against a `{markdown, speech}` scene implementation — which passes the *current* `A-009` wording. That red run is the evidence that AR-001 was real.

## 12. CI enforcement

| Check | Enforces |
|---|---|
| `CI-028` `scene-no-escape-hatch` | `INV-SCENE-3` — structural scan of the scene schema for free-form markup fields |
| `CI-029` `no-endpoint-in-producer` | `INV-SCENE-4` — no producer module references an endpoint ID or a device product name |
| `CI-030` `degradation-ladder-complete` | Every (element type × capability class) pair has a declared ladder entry |

## 13. Dependencies

**Requires:** REM-001 (HLC on streamed patches), REM-011 (space graph, `Person` typing for privacy routing, measured endpoint capability). **Required by:** every output-producing subsystem; `SPEC-17`.

## 14. Unresolved decisions

| # | Item | Disposition |
|---|---|---|
| 1 | Optical feasibility envelope of the glass/holographic output | **SPIKE-004.** Contracts are **not** blocked by it and proceed now; the spike constrains the `volumetric` ladder rung only. |
| 2 | ASR/TTS/wake-word engine selection | Adapter-isolated; local to `SPEC-16`. |
| 3 | Concrete diagram element sub-schema (graph vs. layered vs. timeline) | Local to the element type, provided narration is derivable from it. |

## 15. Jarvis-divergence check

> *Could an implementation agent satisfy REM-009 while building an ordinary chatbot?*

**No — this is the artifact that carries the property most directly.** The clause that prevents it: **`INV-SCENE-3`, no free-form markdown escape hatch**, combined with **`A-009`'s voice-only structural narration of a diagram**. A chat UI's output *is* markdown; it has no typed structure from which a narration could be derived, so it cannot satisfy the voice row of the degradation ladder without inventing one. `A-026` closes the remaining route by removing the text surface entirely.
