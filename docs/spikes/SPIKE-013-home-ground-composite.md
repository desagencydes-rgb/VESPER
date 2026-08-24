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

### 0.5 And once it *is* transparent, the glass reaches the ground

This was measured on the same instrument, in the same runs, because it decides
what the transparency is *worth*. A card carrying
`backdrop-filter: blur(26px)` is placed to straddle a hard blue/red edge in the
ground. Two columns are read out of one capture: one inside the card, one
outside it. The outside column is the sharp reference — same capture, same
machine state, no second run to argue with.

| | Route to transparency | Ground | Edge inside the card | Edge outside |
|---|---|---|---|---|
| `F1` | private `_setDrawsBackground:` | `CALayer` | **41 pt** | 0 pt |
| `F2` | legacy `WebView` (public) | `CALayer` | **41 pt** | 0 pt |
| `F3` | private `_setDrawsBackground:` | **`CAMetalLayer`** | **42 pt** | 0 pt |
| `F4` | legacy `WebView` (public) | **`CAMetalLayer`** | **42 pt** | 0 pt |

It could easily have gone the other way, which is why it was measured: a
backdrop filter samples the page's own backdrop, and the Metal field is not in
the page. It reaches anyway, and it reaches a `CAMetalLayer` as readily as a
`CALayer`.

**So §1.1's look is achievable.** The glass really does blur the live field.
What is missing is only the transparency, and only on `WKWebView`. That changes
what the options are worth:

- **Option 1 loses more than it looked.** With an opaque webview there is no
  backdrop to blur — a card's backdrop filter would sample the page's own
  opaque background. The glass becomes a flat panel and the design's central
  material is gone, not merely reduced.
- **Option 2 still delivers the look** — a WebGL field is *inside* the page, so
  the blur reaches it trivially — but it is now one route among several rather
  than the only one, and it still costs a second face implementation and an
  unmeasured second power profile.
- **Option 4 buys the whole look** on either route, at exactly the cost
  `ISLAND-ARCHITECTURE.md` §2 named.

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

**DECIDED 2026-08-23: option 4, and the cards are unblocked.** The owner took
the private route on the condition that its failure stops being silent, which is
the condition `ISLAND-ARCHITECTURE.md` §2's own reasoning asks for — §2 bans
private API *because* "the failure mode is silent", so a route whose failure is
detected at runtime is not the thing §2 was written against.

What landed with it (`bdc70ac`): `app/home-macos/GlassGuard.swift` as the single
place the selector may appear, carrying the reader and three controls it runs
every time; `VESPER --glass-verify` answering `TRANSPARENT`/`OPAQUE`/
`UNREADABLE` at exit `0`/`1`/`2`, where **`UNREADABLE` is not a pass**;
`--glass-verify --no-hatch` as a permanent negative control, measured red at
`#FFFFFF` without the hatch and green with it; `CI-058` refusing the selector
anywhere unmarked and refusing it in `GlassGuard.swift` if the reader or the
negative control is removed; and `INV-HOME-5` promoted from candidate with the
exception written into it, traced to `SR-002`.

**§1 is now measurable.** The composite's cost can be read against a
configuration that ships, which is what this precondition existed to secure.

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

## 1a. What §1 delivered, 2026-08-24 — the sudo-free half

Run on **battery at 22–27%**, never on mains. §3 forbids reporting one as the
other, so the power source is read from `pmset` and printed in every run's own
header. Phase length **6 s**, three interleaved runs per tier — *not* the
protocol's 10 min, which is a duration for **power**, not for CPU.

The reading is **our process tree**: this pid plus the WebKit helpers that
appeared after we started. `proc_pid_rusage(getpid())` reports the webview as
nearly free, because WebKit renders out of process — wrong in exactly the
direction that flatters the architecture. `host_processor_info` is dominated by
whatever else runs on the machine; the first SPIKE-013 run read 132% at
"wallpaper only" and then measured the face as *cheaper* than the wallpaper.

| phase | CPU %, mean [lo … hi] | fps | frames |
|---|---|---|---|
| baseline | `0.002` | 0.0 | **0** |
| centre | `0.222 [0.193 … 0.263]` | 111.2 | — |
| attendant | `0.230 [0.225 … 0.240]` | 116.0 | — |
| dispersed | `0.244 [0.223 … 0.275]` | 115.0 | — |
| absent | `0.002` | 0.0 | **0** |
| composite | `0.275` | 119.1 | — |

**The composite's cost: `+0.053%` of one core.** One axis. GPU and package power
are not in it.

| # | Criterion | Result |
|---|---|---|
| 1 | the composite sustains its cadence, with CPU, GPU and power | **CPU only** — 119 fps held, `+0.053%` |
| 2 | `DISPERSED ≤ CENTRE` on every axis | **INCONCLUSIVE** — see below |
| 3 | `ABSENT` draws zero, proven by counter | **PASS** — 0 frames, every run |
| 4 | occluded draws zero, proven by counter | **PASS on the mechanism**, not yet at full scale |
| 5 | a stated idle cadence and its power difference | not measured |
| 6 | battery drain as hours of runtime | not measured |

### Criterion 2 is inconclusive, and that is the result

The first attempt printed `CPU 0.3 vs 0.2  ok` — a verdict computed at full
precision beside a display rounded to one decimal, so the numbers shown
contradicted the answer given. That is this repo's own recorded defect (*"the
stall record rounded the number it is judged by"*) wearing new clothes, and the
fix was not more decimals. It was to measure the **spread**:

```
centre     0.222  [0.193 … 0.263]
dispersed  0.244  [0.223 … 0.275]
```

**The ranges overlap.** This axis cannot separate the two tiers. §3's *"the
requirement is not relaxed to 'about the same'"* cuts both ways — it is equally
not **met** by "about the same". GPU and package power are the axes that would
settle it.

### Criterion 4 found the defect the spike was not looking for

The ground held **116.8 fps while fully covered**. `Home.swift`'s entire premise
is that macOS will not throttle a covered Metal layer, so the ground stops
*deliberately* — and it never had. The window server said `covered`, the
renderer said `running`, and a delivery counter said
`didChangeOcclusionStateNotification` had arrived **zero times**.

The notification is not broken in general: at `.floating`, covered by one of our
own windows, it fires in **0.02 s** in both directions. It does not arrive for
the *ground specifically* — full-screen, level `normal − 1`, transparent,
`.managed`. `OcclusionWatch` now keeps it and adds a 0.5 s poll of
`occlusionState`, proven alone with the notification disconnected: covered in
`0.50 s`, uncovered in `0.29 s`.

**Full-scale criterion 4 is still owed**, because forcing occlusion at full size
means covering the whole display in black. The phase now refuses to run on a
Desktop that has any of the owner's windows on it.

### `ABSENT` is not zero CPU, and says so

`0.002%` against Centre's `0.222%`. The residue is the 0.5 s occlusion poll and
the 0.4 s dock poll — the machinery that makes the stop possible at all. §8's
claim is about the cloud, and the cloud draws nothing.

---

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
