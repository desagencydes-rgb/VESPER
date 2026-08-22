# SPIKE-013 — The home's ground: composite cost, and whether dispersal is affordable

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | What does VESPER's home ground actually cost — a Metal ambience/face layer beneath a full-screen transparent webview — and is the **dispersed** face tier cheaper than **centre**, as the presence law requires? |
| **Time box** | 2 working days |
| **Owner** | Platform Engineer |
| **Depends on** | The island's face measurement (39,805 points, 5–7% CPU, 59 MB, 60 fps — `DESIGN-FOUNDATION.md` §8) |
| **Requires hardware** | Yes — this MacBook, **on battery**, not on mains |
| **Raised by** | `HOME-ARCHITECTURE.md` §8 and §11, 2026-08-22 |
| **Blocks** | Build steps F1–F3: the ground, the ambience field, and the four face presence tiers |

> **Why this is a spike and not a build decision.** `ISLAND-ARCHITECTURE.md` §6
> already set the rule for the island's face: *"its power draw is measured
> before its point count is chosen."* The home makes that rule bigger. It is
> full-screen rather than 627 pt wide, it composites a webview over the same
> renderer, and it adds a fourth tier — dispersal — that is *assumed* to be
> cheaper than the head it replaces and could easily be more expensive: more
> points visible, no head to cull against, and no attractor to keep the work
> bounded.

> **The pre-registration is the point.** The reading below is fixed before the
> result exists, for the reason `A-029-E1` records: a rule written after the
> number is a rule fitted to the number.

---

## 1. What gets measured

```
0. Baseline: this machine idle, on battery, home not running, island Dormant.
   CPU %, GPU %, package power, and battery drain rate over 10 minutes.

1. Metal layer alone, full screen: the ambience field with the face at CENTRE.
   Same four figures. Compare against the island's already-measured
   5-7% CPU / 59 MB at 627 pt.

2. Add the transparent WKWebView over it, full screen, rendering the Home
   stage's real chrome (widgets, main menu, one open card).
   Same four figures. THE DELTA BETWEEN 1 AND 2 IS THE COMPOSITE'S COST and is
   the number this spike exists to produce.

3. Face at ATTENDANT. Same four figures.
4. Face DISPERSED.  Same four figures.
5. Face ABSENT.     Same four figures, PLUS a frame counter proving zero frames
   and zero timer, per the presence law.

6. Occlusion: switch to the owner's Desktop, leave the home mounted for
   10 minutes. Same four figures, plus the frame counter.

7. Idle cadence: repeat step 2 with the ground rendering at a reduced cadence
   (candidate: 30 fps, then 10 fps while nothing moves). Record the power
   difference and whether the ambience still reads as alive.
```

Every figure is read from the world after acting — `powermetrics` and the
battery's own drain, never the renderer's own frame-time counter alone. An
instrument's self-report is not evidence.

## 2. Pass criteria

| # | Criterion |
|---|---|
| 1 | The composite (step 2) sustains its target cadence with CPU, GPU and package power recorded against both the step-0 baseline and the island's measured 5–7% |
| 2 | **DISPERSED ≤ CENTRE on every axis.** Pre-registered here, before the reading exists |
| 3 | **ABSENT draws zero** — zero frames and no timer, proven by counter, not by inspection |
| 4 | **Occluded draws zero** (step 6). `INV-HOME-4`'s candidate statement is exactly this |
| 5 | A stated idle cadence for the ground, with its measured power difference from 60 fps |
| 6 | Battery drain rate at the chosen configuration, stated as hours of home-open runtime |

## 3. On fail

**If the composite cannot hold its budget**, the fallback is not "fewer points"
chosen by taste. The finding is recorded and exactly one of three named options
is taken, with its cost stated:

1. the webview loses transparency — opaque panels over the ground, and the field
   shows only where nothing is mounted;
2. the field moves into the webview and Metal is dropped, accepting a worse
   field for one less layer;
3. the ground renders at a lower cadence, with the power saved and the liveness
   lost both recorded.

**If DISPERSED costs more than CENTRE**, the dissolve is not shipped as
specified. It becomes a cut to a still field, and the owner is told the particle
dispersal is not affordable on this host. **The requirement is not relaxed to
"about the same".**

**Not permitted:** reporting a figure measured on mains as the battery figure;
reporting step 1 (Metal alone) as the composite's cost; choosing a point count
before the power is measured; reporting a mean where the worst sample is what
governs — `SPIKE-001` §3.2 already established that the mean of a coexistence
test hides the moment it fails.

## 4. Deliverables

1. Six configurations × four figures, in one table, with the baseline first.
2. The composite delta — a single number, and the sentence that says what it
   buys.
3. A decided idle cadence, and the frame counter output for ABSENT and for
   occluded.
4. Hours of home-open battery runtime, which is the figure the lifetime goal is
   actually judged on.
5. A yes/no on dispersal, with the arithmetic.
