# Annex — island geometry, as built

**Build from this file.** `ui-refs/README.md` records what the owner's
composites measure; this one lands those measurements on a system that can
actually be typed into a layout. The composites are Canva, and the owner has
said so plainly: *"not that precise on details, styles, colors, nor sizes, just
references so you have the same view as mine."* What is taken from them is
proportion and intent. What is taken from the hardware is everything else.

## Two anchors, and why only two

Everything below is derived from facts about this display, not from the
composites:

| Anchor | Value | Source |
|---|---|---|
| Notch width | **185 pt** (x 771 → 956) | measured, DESIGN-FOUNDATION §10 |
| Safe-area top inset | **32 pt** | measured, same |
| Logical screen | 1728 × 1117 pt | measured, same |

The notch is 185 pt, which is odd. Anything anchored to it is therefore also
odd, and that is correct rather than sloppy: the island is pretending to be the
camera housing, so it inherits the housing's arithmetic. Interior content is on
an 8 pt grid *within* the body, and the odd half-point is absorbed at the edges
where no one can see it.

## The states

| State | Width at bezel | Body width | Height | Derivation |
|---|---|---|---|---|
| **Dormant** | 185 | — | 32 | *is* the notch; forced by hardware |
| **Shoulders** | **370** | 346 | **48** | `2 × notch`; `inset + 16` |
| **Expanded, at rest** | **624** | 576 | **192** | `78 × 8`; `6 × 32` |
| **Expanded, speaking** | **624** | 576 | **280** | same width; `35 × 8` |
| **Alert** | 624 | 576 | 96 | *unreferenced* — width borrowed from Expanded so it is not a third guess |

Against the composites: 370 vs 370.5, 48 vs 49.6, 624 vs 627.1, 192 vs 191.3,
280 vs 278.8. Every state within 0.5% except Shoulders' height, which was 3%
and is rounded to a clean 48 deliberately.

**Two relationships to build as relationships, never as numbers.** Shoulders is
`2 × notch` — if a future display has a different notch, Shoulders follows it and
370 becomes wrong. And **Expanded is one width across both bodies**: it grows
downward only. Width must never animate between expanded contents; the
references show no such behaviour and the weld reads as a fixed object.

## The vertical bands

```
y = 0    ┌──────────── the bezel. The island's top edge IS y = 0 ────────────┐
         │  SHOULDER BAND    must clear x ∈ [771, 956] — the camera is here  │
y = 32   ├─────────────────── safe-area inset ─────────────────────────────  ┤
         │  STATUS ROW       six columns, full width, label over value       │
y = 68   ├──────────────────────────────────────────────────────────────────┤
y = 72   │  BODY             instrument panel, or the face                   │
H − 16   └──────────────────────────────────────────────────────────────────┘
```

**The status row starts at y = 32, not at 23.5 where the composites put it.**
This is the one correction that is not negotiable: 267 px of the composites' ink
sits inside the notch's x-range above the inset, which on this display is
underneath the physical camera. Canva has no camera. The `island-shoulders`
composite gets this right on its own — 0 px in the band — so the reference set
already contains its own fix.

Nothing is lost by the correction. Measured, the composites leave ~47 pt between
first ink and the body, and a two-line status column needs ~28. The row moves
down into slack that was already there; **no state gets taller**.

## Corners

**Continuous, not circular, and not the ellipse the composites measure.** The
measured rx/ry pairs (14.4/11.7, 20.8/18.9, 55.9/52.3) are consistently wider
than tall by about the same ratio, which is what a rasteriser does, not what a
designer decides.

More to the point, continuous corners are *required by the fiction*. This
display's own corners are continuous curves; a panel pretending to be an
extension of the bezel and drawn with circular corners reads as a sticker on the
screen rather than part of it. The illusion is the whole component.

| State | Bottom radius | Top radius | Bezel fillet, per side |
|---|---|---|---|
| Shoulders | 16 | **0** | 12 |
| Expanded, at rest | 24 | **0** | 24 |
| Expanded, speaking | 48 | **0** | 24 |
| Alert | 24 | **0** | 24 |

Top radius is **0 in every state, always** — a rounded top edge would put a
visible seam where the panel meets the bezel, and one point of air there is the
whole error.

The fillet is **not** "half the bottom radius", which the composites disprove:
12.2 pt against a 14.4 radius, 22.6 against 20.8, 23.0 against 55.9 — 0.85×,
1.09×, 0.41×. It is a constant per size class, ~12 small and ~24 expanded, and is
built as its own value.

## Colour, one step in

| Layer | Value | Why |
|---|---|---|
| Shell | `#000000` | welded to a true-black housing; `#03141f` beside it reads as a lighter patch |
| Ground, one step in | `#03141f` | VESPER's black — **measured in the composite**, 16 129 px |
| Glass | opaque for the first 120 pt below the bezel; Dock-tier below | nothing to refract where the panel is opaque |

The ground being exactly our own black was predicted by §10 and then found
independently in the owner's composite. It is the one colour in this annex the
references are trusted on, because it agrees with a decision made before they
arrived — everything else about their colour is Canva's and is ignored.

## What this annex does not decide

Type sizes and weights, icon style, the instrument panel's internal layout, and
every surface that is not the island. Density (compact or comfortable) is still
open and will move the 8 pt interior grid when it is answered.
