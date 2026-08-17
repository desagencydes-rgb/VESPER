# SPIKE-004 — Optical feasibility envelope of the volumetric output

| | |
|---|---|
| **Status** | NOT_STARTED · **Time box** 10 working days · **Owner** Presence & Interaction Engineer |
| **Question** | What is the real optical feasibility envelope of the glass/holographic output, and which scene properties does it constrain? |
| **Blocks** | **The `volumetric` ladder rung only.** Contracts are *not* blocked and proceed now. |
| **Requires hardware** | Yes |

> **§2's protocol is amended by §6–§8 (2026-08-14).** The assembly is a Pepper's
> ghost on an ordinary phone screen, not an exotic display. Several properties
> §2 asks for are panel spec-sheet facts and measure nothing about the optics.
> §6 states the geometry, §7 states what is actually measured and why the
> baseline needs a matched viewing distance, §8 states what hardware is needed.

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

## 6. The assembly, and the geometry that decides what can be used

The output is a **Pepper's ghost**: an ordinary screen (the Galaxy J3) showing a
curated layout, with a partial reflector standing on it. The reflector passes
most of the light through and reflects what is bright, so the lit content
appears to float and the unlit ground is invisible. There is no exotic display
and nothing to buy from an optics supplier.

**The reflector must be flat and tilted at ~45°.** Put the screen in the plane
`z=0`, a lit pixel at `(x, -d, 0)`, and the viewer out along `+y`, with the
reflector folded along the line `y=0`:

| Reflector | Normal | Image of that pixel | Result |
|---|---|---|---|
| Vertical wall | `(0,1,0)` | `(x, +d, 0)` | Still `z=0`. The image lies **in the screen plane**, displaced sideways. Nothing floats. |
| 45° pane | `(0,1,1)/√2` | `(x, 0, d)` | Height `d` above the fold. The horizontal source plane maps to a **vertical** image plane. |

Two consequences the screen layout depends on, and both are derived above rather
than assumed: content **farther from the fold line appears higher**, and `x` is
unchanged, so **nothing is mirrored**.

### 6.1 What this rules in and out

| Candidate | Verdict | Why |
|---|---|---|
| Flat clear sheet propped at 45° — sheet protector, clear document folder, CD jewel-case lid, acetate | **Works.** Recommended. | Flat, thin, partially reflective. Already in the house; nothing to buy. |
| Four-face frustum (the "hologram pyramid") | Works, but costs 4× the light | Each face gets a quarter of the panel to make an image nobody is standing in front of. |
| Cone / flared bowl with ~45° walls | Works | The rotationally symmetric case. Needs an annular layout, not four copies. |
| **Straight-sided jar, bottle, tumbler or glass box** | **Does not work** | Walls are vertical, so by the table above the image never leaves the screen plane. The shoulder passes through 45° along a narrow doubly-curved band, which smears an arc rather than forming an image. 3–4 mm glass also reflects at both surfaces, doubling whatever does appear. |

The straight-sided-jar case was tested against the geometry on 2026-08-14 after
one was proposed; recorded here so it is not proposed again.

### 6.2 One pane beats four on this panel

The J3 is 720×1280 at 5". A four-face layout gives each face a 360 px square and
throws away three quarters of the light. A single pane feeds the whole panel
into one image, at one viewing position — which is what a desk endpoint is.
**Both layouts are measured**; the recommendation is single, and the pyramid
figure exists so the ladder records what the four-face cost actually is rather
than asserting it.

## 7. What is measured, and the baseline that makes it mean something

§2 asks for usable volume, refresh rate and element density. On this assembly
those are **panel** properties already on the spec sheet; measuring them here
would produce numbers that say nothing about the optics. What the fold actually
costs is:

| Measured | Datum |
|---|---|
| Glyph height | Smallest cap height still legible, px |
| Colour survival | Last swatch set where every patch stays distinguishable |
| Viewing arc | Degrees off-axis at which the image breaks |
| Element density | Highest count where **every** element stays readable |
| Ambient ceiling | Room-light level at which the ghost washes out |
| Motion legibility | Fastest drift still readable, px/s |

**The baseline is only comparable if the distance matches.** The folded path is
`eye → pane → down to screen`, which is longer than looking at the phone
directly. Comparing "smallest legible size on the bare screen at arm's length"
against "smallest legible size through the glass" would mix distance with light
loss and then attribute all of it to the optics — a clean-looking number that is
wrong, which under INV-HW-2 and CI-034 is worse than no number.

So the baseline is taken **head-on** — the folded path meets the screen along
its normal, so a normal-incidence view is the matching one — at eye distance
`D + w/2`, where `D` is eye-to-pane and `w` is the depth of the screen strip the
pane covers. Both are recorded with every mark.

## 8. Hardware, and what each stage needs

| Stage | Needs glass? | Needs the owner? |
|---|---|---|
| Instrument + capture path | No | No — built and served |
| Baseline (bare panel, matched distance) | **No** | Yes, ~5 min of their eyes |
| Ghost reading, single pane | A flat clear sheet | Yes |
| Ghost reading, pyramid | A four-face frustum | Yes |

Every datum in §7 is perceptual by construction — legible or not, the angle it
breaks at, the light level it washes out at. No amount of shell access on the
handset reads any of them, so `adb` is **not** on the critical path for this
spike and is deliberately not being chased. (It does not currently enumerate
this handset; the Samsung OEM driver holds the interface. Fixing it means a
Device Manager or `pnputil` driver swap under admin, which is owner
intervention, to gain a shell the spike has no use for.)

### 8.1 Instrument

`tools/spike/spike004_ghost.html`, served by `tools/spike/serve_ghost.py` on
port 8899. Three layouts (`pyramid` / `single` / `baseline`), a `flip` toggle
that settles small-end-down vs large-end-down frustum orientation by looking
rather than by reasoning, and `D` / `w` steppers. The operator marks each
reading and presses SEND; the page POSTs the record and it lands in
`docs/planning/spike-results/` with no transcription step, because six numbers
read aloud is six numbers that can be mistyped.
