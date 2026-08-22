# docs/design/ui-refs — the owner's UI reference set

Received **2026-08-21**. These are the references `DESIGN-FOUNDATION.md` §11 was
blocked on, and they lift the first of the two standing corrections in
`docs/design/README.md`: *"the composition of an actual screen is not [decided],
and waits on a reference set that had not arrived as of 2026-08-21."* It has now
arrived, for the island. **A second reference arrived 2026-08-22, for the home** —
`home-reference-1.jpg`, read in `HOME-ARCHITECTURE.md` §14. Everything else is
still unreferenced; see *Still not decided* below.

Keep the distinction that `source/refs/` exists for: those eleven images are
**feel sources**, the mark and the face. These are **UI references** — they say
what a screen is actually composed of. Different job, different directory.

| File | What it is |
|---|---|
| `island-shoulders.png` | The island at rest: mark on the left shoulder, three micro-gauges on the right |
| `island-expanded-instruments.png` | Expanded, at rest — status row over an instrument panel |
| `island-expanded-presence.png` | Expanded, speaking — status row, the face at centre, a spoken caption |
| `face-and-hologram-panels.jpg` | The face, and the hologram panel language around it |
| `island-in-situ.jpg` | One full composite, kept for scale against the menu bar, widgets and Dock |
| `home-reference-1.jpg` | **The home, 2026-08-22.** One full composition: the face as a bust at the centre, work VESPER made scattered around it each with a caption in its own voice, a four-button rail at the right edge, the transcript line, and the main menu at the Dock's position. Confirms the menu bar is present, there is no black band and there is no island. Read in `HOME-ARCHITECTURE.md` §14 |
| `manifest.toml` | Provenance: original filename, sha256, authored size, crop origin, scale |

The committed island files are **lossless crops at native resolution**, not
resamples. The full composites are not committed: the wallpaper behind them does
not compress, and three of them cost more than this entire repository (`.git`
was 9.1 MB). `manifest.toml` carries each original's sha256, so what was measured
stays identifiable even though the frame around it was thrown away.

## The measurement is runnable

```sh
python3 docs/design/source/island_geom.py
```

Nothing below is eyeballed. The island is the near-black region welded to the
bezel; the script flood fills it and takes the per-row extents of the fill.

**Why a flood fill and not the obvious thing.** The first version took the
maximal *contiguous run* of dark pixels through the panel's centre. Bright text
splits that run, so a line of type was reported as a 645 → 57 px geometry step.
The fill routes around glyphs and keeps the outer edge. A profile full of
"steps" that are really words is worse than no measurement, because it looks
like data.

Two things the script has to know and cannot see: these composites were authored
~1915 px wide standing in for a 1728 pt logical screen, and the committed files
are crops. Both live in `manifest.toml` as `scale` and `crop_x`, so x is still
reported in screen coordinates. `island-shoulders.png` additionally carries a
6 px white band above the island in its original — an export artifact, not a
gap above the weld — which is why the script finds the bezel row rather than
trusting y = 0.

## How precisely to read any of this

Owner, 2026-08-21: *"the reference photos are not that accurate and precise, they
are just made in canva … not that precise on details, styles, colors, nor sizes,
just references so you have the same view as mine, and eventually build accurate,
and more beautiful result."*

So the measurements below are **evidence of proportion and intent, not build
targets**. `627.1` is not a number to type into a layout; it is how we know the
two expanded bodies share one width, and roughly what that width is against the
notch. What survives from a Canva composite is *relationships* — this is twice
the notch, these two are the same width, the ground one step in is our black,
the content sits in six columns. What does not survive is the third decimal, and
neither do exact colours or type.

`ANNEX-island-geometry.md` takes these and lands them on a clean system anchored
to the two hardware facts (185 pt notch, 32 pt inset). Build from that annex.
Build from this table only to check the annex still resembles what the owner drew.

## What was measured

All in logical points, on this display (1728 × 1117 pt, notch x 771 → 956).

| | Shoulders | Expanded / instruments | Expanded / presence |
|---|---|---|---|
| Height | **49.6** | **191.3** | **278.8** |
| Width at the bezel | **370.5** | **627.1** | **627.1** |
| Width of the body | 346.1 | 582.0 | 581.1 |
| Bezel fillet, per side | 12.2 | 22.6 | 23.0 |
| Bottom corner rx / ry | 14.4 / 11.7 | 20.8 / 18.9 | 55.9 / 52.3 |
| Width ÷ notch (185 pt) | 2.003 | 3.390 | 3.390 |
| First ink below the bezel | 8.1 | 23.5 | 23.5 |
| Clears the camera? | **yes** | **no — 267 px** | **no — 267 px** |

## Findings

**1. The two expanded states are one width and two heights.** 627.1 pt at the
bezel and 582 pt in the body, identical in both, over the same x span. Only the
height changes with content — 191 pt for instruments, 279 pt for presence. The
island does not resize horizontally to fit what it is saying, and a build that
animates width between expanded contents would be inventing a behaviour the
references do not show.

**2. The interior is `#03141f` — VESPER's own black — measured, not assumed.**
16 129 px of it in the instruments reference. §10 predicted exactly this: *"The
shell is `#000000`, not our black … our black is used one step in, as the ground
the contents sit on."* The owner's reference does it independently. The weld
correction is confirmed from the other direction. (The presence reference's
strongest interior tone is `#212121` at only 93 px — that is the small card
behind the thumbnails, not a panel ground. Recorded because it is in the JSON,
not because it means anything.)

**3. Shoulders is exactly twice the notch.** 370.5 pt against a 185 pt notch is
2.003×. At this precision that is a decision, not a coincidence, and it is worth
building as `2 × notch` rather than as the number 370.

**4. The spec's island sizes are wrong, and not by a little.** The references
correct the §10 table — as proportions, then rationalised in the annex, never by
transcribing these decimals:

| State | §10 said | Measured | |
|---|---|---|---|
| Shoulders | 560 × 32 | 370.5 × 49.6 | narrower, and half again as tall |
| Hanging | 720 × 190 | 627.1 × 191.3 | **height was right**, width was not |
| Expanded | 1000 × 580 | 627.1 × 278.8 | far smaller than specified |
| Bottom radii | 22 / 28 / 34 | 14 / 21 / 56 | wrong spread, wrong values |

The height 190 → 191.3 landing that close is a good sign the rest of §10's
thinking is sound and only the numbers were guesses.

**5. "An inverted fillet of half the bottom radius" does not survive contact.**
Measured, the fillet is 12.2 pt against a 14.4 pt radius (0.85×), 22.6 against
20.8 (1.09×), and 23.0 against 55.9 (0.41×). It is not a ratio of the corner. It
is ~22–23 pt for both expanded states regardless of how round their bottoms are,
and ~12 pt for the smaller state — a constant of the size class. Build it as
its own value.

**6. The expanded references are drawn on a notchless canvas, and collide with
the camera.** This is the one finding that blocks building them as drawn. Both
expanded states put their first ink at y = 23.5 pt, and 267 px of that ink falls
inside x ∈ [771, 956] above the 32 pt safe-area inset — three of the six status
columns are underneath the physical camera housing. In the mockup tool there is
no camera. On this display that text is simply not visible.

The Shoulders reference does **not** have this problem: 0 px in the band. It
keeps its content on the two shoulders and leaves the middle alone, which is
what §10's "the camera is a hole in the layout, not an obstacle to dodge" asks
for. So the reference set is internally inconsistent, and the state that got it
right shows what the fix is.

The correction is forced and cheap: the expanded status row starts at y = 32,
not 23.5, costing ~9 pt of height. It is not a licence to redesign the row.

## The face

`face-and-hologram-panels.jpg` **supersedes the blue face reference.** The owner,
2026-08-21: *"the old face reference (the blue one) is not the real reference."*
§8 already said **"Not blue"** — so the spec was right and the asset was wrong.
Both in-repo copies have been replaced (`assets/face-reference.jpg`, and
`source/refs/face.jpg`, which `build_artifact.py` inlines into the interactive
version — that artifact had been rendering the wrong face).

**The face is not an image.** Owner, 2026-08-21: *"of course the face should not
be at all a simple image, but a whole interactive fast 3d design, actively moving
all the time non stop, so this is very big."* Treat the JPEG as the target it has
to look like, never as an asset to composite. Nothing here is decided about how
it is built — that is a plan, and it is the largest single piece of work the
island implies.

§8's refusal of the fiction still stands and applies harder now that the panel
language is confirmed: the reference carries `REASONING 110%`, `MEMORY ARCHIVE
241-F8-J-1000 PB` and lorem-filled readouts. `INV-HW-2` — measured or `UNKNOWN`,
and `UNKNOWN` means unavailable. Take the form, refuse the numbers.

## Still not decided

These references cover **the island, and one composition of the home**. Everything §11 lists as blocking the
visual language stays blocked for every other surface: the main menu, the home
and its 90 cards, the rooms, floating dialogs, Settings and History have no
reference set. Density (compact or comfortable) is not answered here either.

The owner is preparing home references separately as of 2026-08-21. Nothing in
this directory should be generalised into them.
