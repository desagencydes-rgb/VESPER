# SPIKE-004 — Optical feasibility envelope of the volumetric output

| | |
|---|---|
| **Status** | NOT_STARTED · **Time box** 10 working days · **Owner** Presence & Interaction Engineer |
| **Question** | What is the real optical feasibility envelope of the glass/holographic output, and which scene properties does it constrain? |
| **Blocks** | **The `volumetric` ladder rung only.** Contracts are *not* blocked and proceed now. |
| **Requires hardware** | Yes |

## 1. What is and is not blocked

This is the spike most likely to be misread as blocking the presence architecture. It is not.

The semantic-scene design is **endpoint-independent by construction**: `spatial_intent` is relational, `presentation_intent` carries intent rather than styling, and every element type declares a rung for every `spatial_class` including `none`. An unavailable `volumetric` rung is therefore a **degradation**, not a redesign — which is exactly the property the architecture was built to have, and this spike is the first real test of whether it holds.

If the glass output proves infeasible, VESPER loses one rung on a ladder and reports it. Nothing else changes. If the architecture had been built around a screen, this finding would instead be a rewrite.

## 2. Protocol

Measure, on the candidate optical assembly:

| Property | Method |
|---|---|
| Usable volume | Physical bounds within which an element is legible, in cm³ |
| Viewing angle | Angular range retaining legibility, horizontal and vertical |
| Ambient-light tolerance | Legibility at 100 / 300 / 500 / 1000 lux, measured with a meter |
| Refresh rate under load | Sustained fps rendering a representative scene, not a test pattern |
| Element density | Maximum simultaneous elements at legible size |
| Depth separation | Minimum discriminable depth between two layers |
| Text capacity | Characters legible at the owner's ordinary viewing distance |
| Colour fidelity | Whether `state_indicator` colour semantics survive |
| Latency | Scene update → visible, against the 300 ms budget |

Each figure measured under **the room's real lighting**, at the owner's real viewing distance, with the owner's real eyesight — not on an optical bench. A display legible only in a darkened room at 40 cm is not a presence endpoint in a home.

## 3. Pass criteria

1. Every property above has a measured value with stated conditions.
2. `scene_update_visible` p95 ≤ 300 ms on the assembly.
3. Legibility holds at the **measured ambient light of the intended room**, not a favourable one.
4. The measured constraints are written into `contracts/policy/degradation_ladder.toml` as bounds on the `volumetric` rung and into `endpoint_capability.schema.json` field values.
5. `diagram` and `table` elements are legible in the volume — the two element types whose value is highest and whose density demands are largest.

## 4. On fail

The `volumetric` rung is recorded as **R&D**. `endpoint_capability.spatial_class` retains the value; no endpoint claims it. `DF-DEGRADE` resolves volumetric scenes to the next available rung and reports the degradation, which is already its specified behaviour.

**Not permitted:** removing `volumetric` from the schema. The rung's presence is what keeps the architecture endpoint-independent, and deleting an unavailable rung is how a system quietly becomes a 2D UI toolkit with spatial vocabulary.

## 5. Deliverables

1. The measured optical envelope.
2. Constraints written back into the degradation ladder and endpoint capability schema.
3. A legibility judgement for each element type in the volume.
4. Either a viable `volumetric` rung or a recorded R&D disposition.
