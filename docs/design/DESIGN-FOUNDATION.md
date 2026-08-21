# VESPER — Design Foundation

**v0.1 · 2026-08-21 · owner-specified, recorded here so no session has to rediscover it.**

Interactive version, with live previews of every primitive below:
<https://claude.ai/code/artifact/aec78c48-24ad-4e69-a2a2-e27b9a67308c>

Status of this document: the primitives are **decided**. The composition — how a
screen is actually laid out — is **not**, and waits on the owner's UI reference
set. The eleven images supplied on 2026-08-21 are *feel sources, the mark, and
the face*. They are explicitly **not** UI references, and nothing here should be
read as one.

---

## 1. Palette — ten colours

| Name | Hex | OKLCH C / H | on `pitch` | on `paper` | Role |
|---|---|---|---|---|---|
| cream | `#f0e0c0` | .046 / 85° | 14.35:1 | 1.12:1 | Lit surfaces, warm ground |
| ember | `#B96645` | .117 / 42° | 4.49:1 | 3.59:1 | Warning; **light theme accent** |
| solar | `#D99A52` | .116 / 68° | 7.74:1 | 2.09:1 | Speaking, sustained warmth |
| blush | `#e8829d` | .128 / 4° | 7.22:1 | 2.24:1 | Thinking, milestone |
| purple | `#59348a` | .138 / 300° | 2.03:1 | 7.94:1 | Watching, listening |
| gold | `#C5A35A` | .100 / 85° | 7.80:1 | 2.07:1 | Work that is holding |
| botanical | `#64745B` | .043 / 134° | 3.73:1 | 4.33:1 | Rest, quiet hours |
| orange | `#ffaf95` | .101 / 39° | 10.52:1 | 1.53:1 | **Dark theme accent** |
| paper | `#ffeae3` | .025 / 39° | 16.13:1 | — | **Ground, light.** Never an accent |
| pitch | `#03141f` | .033 / 238° | — | 16.13:1 | **Ground, dark.** Never an accent |

Two facts that constrain everything downstream:

- **Cream and orange cannot carry body text on the light ground** (1.12:1,
  1.53:1). They are light sources, not ink.
- **Ember is the only colour legible on both grounds.** That is why it is the
  light theme's accent and why `Alert` uses it regardless of what its source
  image measured.

## 2. Themes

Light, dark, and auto-following the system. VESPER is **dark-first**: ten of the
eleven feel images are night, and the mark is lit matter on black. So the base
token set is dark and light is the redefinition — the inverse of the usual CSS
pattern, applied consistently across all three states (bare `:root`, the
`prefers-color-scheme` media query, and the explicit `data-theme` stamp).

## 3. The adaptive colour rule

> *"Colours should be curated well depending on what's surrounding them, and
> actively changing on their own to end looking well no matter the space they're
> in nor what's behind them."* — owner, 2026-08-21

Per glass surface, five steps:

1. **Sample** the backdrop at 8×8, convert to OKLab, take mean `L`, mean chroma,
   dominant hue and its variance.
2. **Score** the eight chromatic colours only — the two grounds never compete.
   Hue distance from the backdrop (want ≥ 40°), predicted contrast once
   lightness is solved, and a penalty if a sibling within 240 px already holds
   the colour.
3. **Solve lightness, hold hue.** Keep `H` and `C` from the palette entry, move
   `L` only, until APCA `Lc ≥ 60` for text and `≥ 45` for borders, measured
   against the *composited* glass rather than the raw backdrop. Gamut-map chroma
   back into sRGB.
4. **Hysteresis.** Re-evaluate only when backdrop mean `L` shifts > `0.08` or
   hue > `25°`, at most once per `400 ms`, cross-fading on `--smooth`. Without
   damping the interface shimmers as you scroll, because every frame re-picks a
   marginally better colour. *Adaptive without damping reads as broken, not
   alive* — this is the step that is easy to leave out.
5. **Fail closed.** If the backdrop cannot be sampled, take the theme's static
   accent and mark the surface unadapted. Do not guess. Same rule as `INV-HW-2`:
   an unmeasured value is `UNKNOWN`, and `UNKNOWN` is never treated as a good one.

## 4. Glass — iOS 26

This machine runs macOS 26.5 (25F71), so the host already speaks the iOS 26
glass language; matching it is native, not pastiche.

| Tier | Blur | Saturate | Fill α | Radius | Used for |
|---|---|---|---|---|---|
| Chip | 13px | 160% | .055 | 11px | Buttons, pills, tags |
| Sheet | 24px | 180% | .055 | 22px | Cards, panels, the 70% expandable card |
| Dock | 42px | 200% | .085 | 34px | Main menu, island dock, floating dialogs |
| Scrim | 8px | 100% | .50 | 0 | Behind a modal |

Every tier carries a specular top edge (`inset 0 1px 0`), a 1px border, and a
cast shadow.

**Two host settings VESPER must obey**, both exposed to the webview as media
queries: `prefers-reduced-transparency` collapses every tier to an opaque
surface, and `prefers-reduced-motion` turns every spring into a cut. A system
that claims to collaborate with its host does not override the host's
accessibility choices.

## 5. Type

| Role | Face | Foundry | Status |
|---|---|---|---|
| Body, plain text | **Aeonik** | CoType Foundry | Commercial licence required — **not yet bought** |
| Headlines, expressive | **Canela** | Commercial Type (Miguel Reyes) | Commercial licence required — **not yet bought** |
| VESPER's handwriting | **Learning Curve** | Blue Vinyl Fonts | Free — installable today |

None of the three are installed on this machine as of 2026-08-21. They get
bundled into the Tauri app as local `@font-face` files. Web previews use
substitutes (`Outfit`, `Instrument Serif`, `Dancing Script`) because an artifact
may only load fonts from Google Fonts — that constraint does not apply to Tauri.

**The rule for the hand.** A third typeface with no rule is decoration. Learning
Curve is VESPER writing in the first person, unprompted — a margin note, an
aside, a line on a milestone. Never a system message, never a number, never
anything the owner asked for directly, never more than ~two lines. If it appears
in an error dialog, the rule has been broken.

## 6. Motion — this machine's springs

> *"Exactly this macbook's animations, if a new animation is required, I'll tell
> you about it."* — owner. **New animations require owner approval.**

Sampled from the real SwiftUI `Spring(duration:bounce:)` step responses and
emitted as CSS `linear()` easings, so these curves *are* the system's rather
than an approximation.

| Name | Duration | Bounce | ζ | Settles | Overshoot | Used for |
|---|---|---|---|---|---|---|
| `smooth` | 0.50 s | 0.00 | 1.000 | 735 ms | none | Theme change, ambience cross-fade, dock reveal, gaze return |
| `snappy` | 0.50 s | 0.15 | 0.850 | 697 ms | 0.6% | **Default.** Island expand, card open, button press |
| `bouncy` | 0.50 s | 0.30 | 0.700 | 819 ms | 4.6% | Rare and earned: milestone, task completed |
| `legacy` | 0.55 s | 0.175 | 0.825 | 758 ms | 1.0% | Old `.spring()` default; parity with system controls only |

**Dock magnification is not a spring.** It is a distance falloff —
`scale = 1 + 0.8·cos²(π·d / 2W)` for cursor distance `d`, out to `W ≈ 2.5` icon
widths, recomputed per mouse-move with no easing. VESPER's main menu uses the
same curve; occupying the Dock's position while magnifying differently is the
kind of near-miss that reads as cheap.

## 7. Ambience — eleven modes, eleven images

Each supplied image became exactly one mode. Grounds are the darkest (or
lightest) k-means cluster in OKLab, pulled toward the theme ground. Accents come
from the **light source** in each frame — the top 4% of pixels by brightness ×
chroma — because the mean of a night photograph is just the night.

| Mode | Source | Ground | Accent | Contrast | Provenance |
|---|---|---|---|---|---|
| Home | classical hall | `#ebd7c2` light | gold | 3.08:1 | measured 84° |
| Idle | hills + one ember | `#020b11` | solar | 8.21:1 | **curated** |
| Watch | lighthouse | `#151b25` | purple | 3.38:1 | measured 283° |
| Listening | bioluminescence | `#020b11` | purple | 4.25:1 | measured 260° |
| Thinking | violet starfield | `#040e19` | blush | 7.50:1 | measured 18° |
| Working | Milky Way / Alps | `#0a151f` | gold | 7.69:1 | measured 78° |
| Flow | Mavericks wave | `#f6decd` light | solar | 3.36:1 | measured 66° |
| Speaking | sepia windsurfer | `#161c1f` | solar | 7.13:1 | measured 77° |
| Alert | GT3 RS / B-2 | `#061016` | ember | 4.62:1 | **curated** |
| Rest | leaves on cream | `#d2c0b5` light | botanical | 3.11:1 | **curated** |
| Milestone | magenta arch | `#0a0e15` | blush | 7.46:1 | measured 330° |

Eight measured, three curated — each curation recorded with its reason:

- **Idle** — the brightest thing in frame is the galaxy, but the frame is about
  the single ember on the horizon. Took the ember.
- **Alert** — chroma 0.006, no hue signal at all. Ember chosen because it is the
  one colour legible on both grounds, and the frame's only colour is an orange
  reflector.
- **Rest** — the light source is the cream wall, but the subject is the foliage.
  Took the subject. Also forced to a light theme: the leaf mass drags mean `L`
  to 0.43, but the frame is plainly daylight.

**What the images agree on.** Mean chroma across all eleven is `0.04` — almost
neutral. What gives them character is one small saturated thing against a large
desaturated field. So an ambience ground is always muted and the accent is
always the rare bright point. *A mode that colours the whole screen has misread
its own source.*

## 8. The face

Point-cloud head at the centre of the home, form taken from the owner's
reference. **Not blue** — the colour is whatever the adaptive rule picked for
the space, and the hologram panels take the same colour.

| | |
|---|---|
| Eyes lead | 80 ms before the head starts |
| Head yaw | ±18° max, on `--smooth` |
| Head pitch | ±12° max |
| Eye range | ±25° beyond the head |
| Return | to centre after 1.2 s idle |
| Blink | every 3–7 s, 120 ms, never mid-sentence |

Eyes arriving before the head is the whole trick. Move them together and it
reads as a turret.

Eight panel anchors around the head, clockwise from twelve. A panel fades in on
`--snappy`, the face turns to it, and it holds until the thing it describes is
done.

**The fiction is refused.** The reference image carries invented telemetry —
`REASONING 110%`, `MEMORY ARCHIVE 241-F8-J-1000 PB`, lorem-filled panels.
`INV-HW-2` says a number is measured or it is `UNKNOWN`, and `UNKNOWN` means
unavailable. The form is taken; every panel is backed by a live reasoning
stream, the real task graph, a real plan, or a measured number. There is no
filler panel and no decorative readout.

## 9. The mark

Owner: *"should show up everywhere … for the stuff i mentioned along with it, i
don't know if it's better to add them in those spaces if so, don't add them."*
Taken as a decision, not a menu.

**Yes — four places.** Island cap (24 pt, left of the collapsed pill — the
stated primary and the only mark on screen most of the time); island head
(44 pt, top of the expanded dock); app icon (Dock, ⌘-Tab, Finder, About); wake
(alone on the ground while VESPER comes up).

**No — two places.** Main menu: it would sit ~40 pt from the island's copy and
add nothing; a tool rail is not signed. Menu-bar extra: the island already owns
top-centre, and a second mark competes with the notch for the only scarce space
on this display.

A mark in six places stops being a mark.

## 10. Structure

### The dock swap

Inside VESPER's workspace the system Dock goes under the screen and VESPER's
main menu takes its position — a long glass bar, bottom-centre. Cursor to the
bottom edge summons the system Dock, which rises **in front of** the main menu,
exactly as inside any fullscreen app.

**How it is done:** not by fighting the Dock. VESPER sets
`NSApplicationPresentationAutoHideDock` while its window is frontmost — the same
API a fullscreen app uses. macOS reverts it the moment VESPER stops being
frontmost, and the cursor-to-edge reveal is the system's own behaviour, free.

**Permissions consequence:** this is VESPER changing *its own* presentation, so
it belongs in the `self` tier of `contracts/policy/host_actions.toml`, alongside
`set_own_execution_class`. It is not a host mutation and does not require
per-instance owner approval.

**Occlusion, not evacuation.** When the system Dock rises, the main menu stays
exactly where it is and is covered — it does not slide, shrink or re-flow. It
dims to 30% while occluded so it is visibly still there rather than apparently
gone. Two bars trading places is a fight; one bar passing in front of another is
a stack.

### The island, and the notch

Measured on this display rather than assumed: logical **1728 × 1117 pt**
(3456 × 2234 @2x), safe-area top inset **32 pt**, notch **x 771 → 956** —
185 pt wide, dead centre. The island is glued top-centre, so it and the notch
want the same 185 pt.

| State | Where | Size | Shows |
|---|---|---|---|
| **Collapsed** (outside home) | centre x = 864, top y = 38 — six points clear of the inset, never entering the notch band | ≤ 520 × 30 pt | Mark, then current task / song / action / mission. One line, truncating |
| **Flanked** (when content needs width) | two lozenges in the auxiliary areas, `0–771` and `956–1728` | 2 × ≤ 340 pt | Status left, live activity right; notch untouched between them |
| **Expanded** (on demand, or in home) | grows downward from the collapsed pill on `--snappy` | ≤ 1000 × 580 pt | The island dock menu: blurred cards with coloured borders, the face at centre, hologram panels around it |
| **Alert** | collapsed position, `--bouncy` arrival | ≤ 620 × 44 pt | One approval request, or one thing that needs the owner. Never two |

In fullscreen the menu bar hides and the notch region goes black; the island
still refuses to cross y = 32, so nothing changes.

### Floating dialogs — split, per owner instruction

**Stays a dialog** (addressed to the owner, worthless later): approval — a risky
action waiting, the only kind that blocks; clarify — cannot proceed without one
answer; alert — thermal, battery, a deadline arriving; capture — quick input,
summoned from anywhere.

**Becomes a card** (things you go and look at): surfaces — which messages may
float, where they anchor, how long they hold, what may interrupt; backlog —
everything that floated while away; history — what was approved and refused, and
when.

The floating layer itself stays a mechanism: it has a card that *configures* it,
not a card that *is* it.

### The home

The twelve items previously hidden by a sticky-header defect are now home cards,
taking the home from 78 to **90**. Grouped into rooms rather than listed:
Memory (22), Work (25), Doing (10), Beyond (7), Permissions (6), Presence
(frame, floating surfaces, the face). Settings (35) and History (17) remain
their own spaces. Four cards are front doors into rooms rather than rooms
themselves: Tunables, Conversation history, Presence indicator, Floating
surfaces.

## 11. Open — not yet specified

**Blocking the visual language:** the owner's UI reference set; and density
(compact or comfortable by default).

**Not specified anywhere yet:** icon style (line or filled, and at what weight);
whether the interface makes any sound beyond VESPER's voice; corner radii
(11 / 22 / 28 / 34 pt assumed); language and RTL (Arabic or French would change
the island and the rail); external-display behaviour (no notch, different size);
empty and error states.

None of these block the build. Palette, type, motion, glass, themes, the
adaptive rule, the dock swap, the island states and the face are decided and
buildable now.
