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
unchanged, so ~~**nothing is mirrored**~~.

> **CORRECTED 2026-08-17, by looking at it.** The second half is wrong. The ghost
> renders text **right-to-left** — the field run photographed `VESPER 01:53` and
> the page title both reversed.
>
> The error is instructive, so it is kept rather than quietly fixed. The table
> above is right that the *world* `x` coordinate is preserved; the mistake was
> concluding from that that the image is not mirrored. **Handedness is not a
> coordinate.** A single reflection is orientation-reversing — the full map here
> is `(x,y,z) -> (x,-z,-y)`, whose determinant is `-1` — and the viewer stands on
> the far side of the fold, so their left-right axis is inverted relative to
> someone looking down at the panel. Preserved coordinate, reversed image.
>
> It also explains why the `flip` control could never have fixed it:
> `rotate(180deg)` is `scale(-1,-1)` with determinant **+1**. No rotation undoes a
> reflection. The instrument now applies `scaleX(-1)` — a separate `mirror`
> control, **on by default** — and every mark records `mirrored` alongside
> `flipped` so a reading can never be read back without knowing which geometry
> produced it.
>
> The general lesson is the one this file already argues for elsewhere: a
> derivation checked only against the coordinate it happens to track is not
> checked. **Five minutes of looking through the glass falsified it.**

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
| Glyph height | Smallest ~~cap height~~ **font-size** still legible, CSS px (dpr 2). The instrument varies `font-size`; cap height is ~0.7 of it, and the two were being used interchangeably |
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
rather than by reasoning, a `mirror` toggle (§6, on by default), and `D` / `w`
steppers. The operator marks each reading and presses SEND; the page POSTs the
record and it lands in `docs/planning/spike-results/` with no transcription
step, because six numbers read aloud is six numbers that can be mistyped.

**The instrument runs in a 2016 browser, and this is a design constraint, not a
footnote.** Every result file records the same user agent: Chrome 55 on Android
5.1.1 (`SM-J320F`). The page was written on a desktop in CSS that browser cannot
parse, and **an unsupported declaration is dropped silently** — nothing throws
and nothing logs, so the instrument looked correct everywhere except on the only
device it is for. On load the page now POSTs a **capability probe**:
`CSS.supports()` for each feature it depends on, plus the measured
`getBoundingClientRect()` of the tap zones and a face. It lands as
`SPIKE-004-capability-probe-<browser>.json`, overwritten per load, because it
records a property of the browser rather than an event in the field. Nothing in
the page may use a feature newer than Chrome 55, and the probe is what makes
that checkable rather than asserted.

### 8.2 Correction — why the first two runs returned six defaults

**2026-08-18.** The commit of 2026-08-17 (`b2c257a`) recorded that two field runs
had produced six marks each with every value at `levels[0]`, and concluded:

> ~~Not measurements — defaults, recorded because MARK never checked whether the
> operator had moved the scale.~~

~~The instrument was manufacturing numbers because the operator never stepped the
scale.~~ **That was one cause and it was not the main one.** The operator
reported the next day that tapping the sides of the screen did nothing — only the
buttons and the swipes worked — and the cause generalised: `#tapzones` was
positioned with `inset: 0`, which is Chrome 87. Dropped, the element took auto
offsets, wrapped no content, and measured **0 × 0**. The level control had no hit
target at all.

It did not stop there. The collapse ran through the test content itself:

| Test | Rendered with | Available | What the operator saw when they stepped it |
|---|---|---|---|
| glyph height | flex ladder, `gap` | `gap` is Cr 84 | text at the right size, unspaced — **readable** |
| colour survival | grid + `aspect-ratio` | Cr 57 / Cr 88 | swatches zero px tall — **nothing** |
| viewing arc | `aspect-ratio` box, spokes sized in % of it | Cr 88 | no ring, no spokes — **nothing to mark against** |
| element density | `display:grid` + `aspect-ratio` cells | Cr 57 / Cr 88 | 1 cell and 16 cells looked identical — **nothing** |
| ambient ceiling | `.solid` square via `aspect-ratio` | Cr 88 | the caption only — **no white field to wash out** |
| motion legibility | flex ladder + `@keyframes` | animations OK | drift visible — **readable** |

So for four of the six tests, **stepping the scale changed nothing on screen.**
"The operator never stepped it" and "stepping it did nothing" are different
facts, and the record asserted the first. An operator who moved a control, saw no
change, and left the value where it was behaved correctly; the instrument did
not.

**What stands from `b2c257a`, unchanged.** The `stepped` flag is still right and
stays: the floor can be the true answer, and "measured the floor" must survive as
a different fact from "never touched it". The `viewing arc` and `ambient ceiling`
scales really were single-valued (`levels: [1]`) and really did make those two
tests unanswerable — that defect was independent of the CSS and is fixed. The
`stepped` set is now keyed by `test|layout` rather than by test name, because
marks are, and no `baseline` pass has ever been run — §7 makes the baseline the
thing that gives every ghost number its meaning, so a guard that stayed silent
through the first baseline pass would have failed on the run that matters most.

### 8.3 The first baseline pass does not count, and the reason is geometry

**2026-08-17 23:45.** The first `baseline` pass ever taken produced six marks,
all `stepped: true`, correctly labelled and named — the instrument worked. The
readings do not.

Every mark carries `flipped: true, mirrored: true`. **Neither transform has any
meaning in `baseline`**: that layout is the bare panel viewed head-on, with no
fold and no reflection to undo. `mirror` defaults on because the ghost needs it
(§6), and that default is precisely what carried it into the one layout that
must not have it. What the pass actually measured is how small the operator can
read text that is upside down and backwards.

That shows up in the numbers. `glyph height` came back as **40 px — the largest
value on the scale**, marked as the *smallest legible* size, on a bare phone
screen at ~53 cm. Reversed text is the explanation. And because §7 makes the
baseline the datum every ghost reading is compared against, a baseline degraded
by two transforms does not lose one row: it biases the entire spike toward
*"the fold costs nothing"*.

Two further readings are not yet trustworthy for reasons the instrument cannot
fix:

- `ambient ceiling: 4` (*daylight / bright*) was marked 11 s after the previous
  mark. That step asks the operator to **change the room light** until the image
  washes out — the only measurement here that alters the room rather than the
  phone.
- `viewing arc: 90°` says the image never breaks at any angle. On a bare LCD at
  90° off-axis the panel is edge-on; real panels wash out well before that.

**The files are kept, not deleted.** They carry `flipped` and `mirrored` on
every mark, which is exactly why the defect was visible at all — the geometry
fields added in §6's correction did their job on the first run that needed them.
A reading whose geometry is recorded can be disqualified; one whose geometry is
unknown cannot.

**Fixed in the instrument:** selecting `baseline` now forces both transforms off
and the `flip` / `mirror` buttons refuse while it is selected, saying why. The
protocol card says it too, along with the note that the ambient step needs the
room light genuinely varied.

**The lesson worth keeping is not the one that commit drew.** It read six
suspicious numbers and reached for operator discipline. The numbers were
suspicious because the instrument was broken in a way that reports nothing — no
error, no log, no visual clue on the machine it was authored on. **Before
concluding that a reading is the operator's fault, establish that the instrument
was capable of showing them anything.** That is what the load probe in §8.1 now
does automatically, on the device, every session.
