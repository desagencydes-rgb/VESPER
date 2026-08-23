# SPIKE-013 — The home's ground: composite cost, and whether dispersal is affordable

| | |
|---|---|
| **Status** | RUNNING |
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

## 0. The precondition, answered 2026-08-23 — and it is a NO

Everything in §1 assumes a **transparent** webview over the Metal layer. That
assumption was never tested, and it is false with public API.

**Can a `WKWebView` be transparent over the face, with public API only? No.**

Instrument: `app/home-macos/glass_probe.swift`. macOS 26.5 build 25F71. Run
twice — once at the ground's own level (`normal − 1`, window occluded) and once
floating and visible — with identical readings at both.

### 0.1 Why a third instrument was needed

Two earlier ones failed, in opposite directions, and both failed *silently*:

| Instrument | What it actually does | What it reported |
|---|---|---|
| `takeSnapshot` | composites onto an **opaque** bitmap | alpha 1.00 for a page that may have been perfectly transparent |
| `cacheDisplay(in:)` | draws the view tree **this process** owns | `OPAQUE (Δ 2.992)` — a delta of nearly the maximum possible 3.0, which is the WKWebView placeholder, not the page |

Both are in-process. The content is not: WebKit renders in
`com.apple.WebKit.WebContent`. So this instrument asks the **window server** for
the composite of our own window, which is the only reader that sees every layer
regardless of which process drew it.

That reader is not trusted on its word either. `CGWindow.h:264`: *"if the
windows can't be read, then a transparent black image will be returned"* — and
transparent black is exactly what success looks like. A blocked capture and a
perfect pass are the same pixel. Hence three controls, run first, all passed:

| | Control | Read |
|---|---|---|
| `A1` | ground only, blue over red — does the capture reach our window, and which way up | `#1249CC` over `#CD4412`, α 1.00, 1280×840 |
| `A2` | clear ground, no webview — is alpha preserved | transparent |
| `B1` | a page painted edge to edge `#FF00FF` — **does the capture see WebKit at all** | `#FF00FF` |

`B1` is the one both earlier instruments would have failed.

**`A1` also failed on its first run, and the reason is kept.** It *declared*
that a `CGColor(red: 0.063, …)` ground would read back as `#1030C0`. It read
`#1249CC`. Nothing was wrong with the capture — the window server composites in
the display's space and the reader converts to sRGB, so an authored colour and a
captured one are two different numbers for the same paint. The fix was not a
wider tolerance. `A1` now **measures** the reference and every later case is
compared against that measurement. `INV-HW-2` in a colour space.

### 0.2 The readings

Ground reads `#1249CC`. A reading of `#1249CC` at a point where the page draws
nothing means the webview painted nothing there.

| | Configuration | Empty point | |
|---|---|---|---|
| `C1` | default `WKWebView`, page `background: transparent` | `#FFFFFF` α1.00 | webview painted over it |
| `C2` | `+ underPageBackgroundColor = .clear` | `#FFFFFF` α1.00 | webview painted over it |
| `C3` | `+ layer.isOpaque = false` | `#FFFFFF` α1.00 | webview painted over it |
| `C4` | the same over a **clear** ground — the whole stack | `#FFFFFF` α1.00 | webview painted over it |
| `C5` | the same with the real glass chrome | `#FFFFFF` α1.00 | webview painted over it |
| `C6` | the same over a **`CAMetalLayer`** — the home's own ground | `#FFFFFF` α1.00 | webview painted over it |
| `D1` | **private** `_setDrawsBackground:false` | `#1249CC` α1.00 | **ground shows through** |
| `E1` | **legacy** `WebView.drawsBackground = false` | `#1249CC` α1.00 | **ground shows through** |

`underPageBackgroundColor` is not being ignored. It is set, held, and **reads
back as α 0.00** — and the webview still paints white. It is the scroll-bounce
colour its own header says it is (`WKWebView.h:607`, *"the background color
under the page's content, such as for scroll bouncing areas"*), and it is the
whole public surface on `WKWebView`: grepping this machine's SDK for
`macos(26)` additions across WebKit turns up Screen Time, instant back,
obscured content insets and data restore, and nothing about background.

**`D1` and `E1` are what make this a finding rather than a blind spot.** On the
same instrument, in the same run, two configurations *did* read the ground
through the webview. The reader can tell transparent from opaque. The public
knobs on `WKWebView` cannot produce it.

### 0.3 What the finding does and does not say

`E1` narrows the sentence. `drawsBackground` **is** public — on the legacy
WebKit1 `WebView` (`WebView.h:504`), deprecated since 10.14 and still present
and working on macOS 26.5. So the finding is not *"no public route exists"*. It
is:

> **No public route exists on `WKWebView`.**

and the route that does exist costs a deprecated, in-process, frozen engine and
**forecloses Tauri**, whose macOS backend is a `WKWebView`.

### 0.4 What is now blocked, and on whom

The composite cost in §1 cannot be measured honestly until the fallback is
chosen, because measuring a configuration that cannot ship measures nothing.
§3's three named options are now live, plus a fourth that §3 did not anticipate:

| | Option | What it costs |
|---|---|---|
| 1 | the webview loses transparency — opaque panels over the ground | the field shows only where nothing is mounted. The wallpaper is the real desktop picture now, so this is less severe than when §3 was written |
| 2 | the field moves into the webview, Metal dropped | a second face in WebGL, a second power profile, and `FaceRenderer`'s measured 5–7 % is thrown away |
| 3 | the ground renders at a lower cadence | does not help — cadence is not why the webview is opaque |
| 4 | *(new)* accept a non-public route | `_setDrawsBackground:` is KVC onto a private property, which `ISLAND-ARCHITECTURE.md` §2 rules out because the failure is silent and arrives with an OS update. WebKit1 is public but deprecated and forecloses Tauri |

**This is an owner decision and the 90 home cards are held until it is made** —
which is exactly what running the precondition first was for.

**Unverified, and it decides how much option 4 really costs:** Tauri's macOS
backend must obtain window transparency somehow, and `wry` is not installed on
this machine yet, so which route it takes has not been read. If it uses the
private setter, then choosing Tauri already accepts option 4 inside a
dependency, one step further from where it can be seen. Check it the day `wry`
lands.

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
