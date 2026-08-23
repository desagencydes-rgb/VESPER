# Home — steps 1 and 2 (2026-08-23)

Written for the session that picks this up. Step 1 landed as `b2122bc`; step 2
is the `SPIKE-013` precondition below, and it ends on a decision the owner owns.

## Owner's standing facts

- **Desktop 1 has Notes open. Desktop 2 is the empty one — that is VESPER's.**
  Do not confuse them; the owner said so explicitly.
- The owner asked to be stopped and told whenever a run needs them.

## Step 1 — DONE

The home is folded into `VESPER.app`. One process, one binary, one identity.

| File | What it is |
|---|---|
| `app/home-macos/Home.swift` | `HomeController` — the ground at `normal − 1` `.managed`, transparent, the face on it, the **deliberate occlusion stop** |
| `app/home-macos/HomeAmbience.swift` | the eleven modes out of `modes.json`, and the wallpaper as the **real desktop picture** (reversible: original recorded in Application Support) |
| `app/home-macos/SpaceWatch.swift` | foreign-window fingerprint + Jaccard, promoted out of `residency_probe.swift` |
| `app/home-macos/HomeVerify.swift` | identity readout + the §2.6 measurement + the sibling guard |
| `app/island-macos/main.swift` | `--home`, `--home-verify`, and `Controller.retreat(_:)` for §2.6 |

**Named `HomeAmbience.swift`, not `Ambience.swift`** — macOS is case-insensitive
and `Ambience.swift` silently overwrote the F2 probe `ambience.swift`. Recovered
from git. Do not reintroduce the collision.

## What was measured, and what was not

- **Identity**: launched as the app, `codesign` reports `Identifier=ai.vesper.island`,
  `Signature=adhoc`. As a loose binary it reports no bundle and says so.
  **NOT proven:** that a permission dialog says VESPER. That is observed in a
  dialog or not at all, and the first one is the Accessibility grant this build
  deliberately has not asked for.
- **Occlusion answers a stronger question than residency.** Dry run, nobody
  switching: ground on the active Desktop 24/24, reported covered 24/24, because
  a full-screen terminal was over it. That is what §2.6 and §10 both want.
- **§2.6's signal is UNMEASURED.** It needs the owner to switch Desktops.

## THE ONE RUN THE OWNER STILL HAS TO DO

The LaunchAgent keeps an island alive, and a second VESPER invalidates the
control — so the agent must be stopped first. The guard refuses and says so if
it is not.

```sh
launchctl bootout gui/$(id -u)/ai.vesper.island
./app/VESPER.app/Contents/MacOS/VESPER --home-verify --after 12 --seconds 45
#   1. within 12 s, Ctrl+2 to VESPER's empty Desktop — the ground is created THERE
#   2. wait ~10 s, Ctrl+1 back to Notes, wait ~10 s, Ctrl+2 again
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.vesper.island.plist
```

Log lands at `app/home-macos/home_verify_last_run.log`.

**The criterion is an implication, not an agreement.** `lit while ABSENT` must be
0. `dark while present` is legitimate and reported, not judged. `control (island)`
must be 0 — it is the island's own panel, on every Desktop and above every
ordinary window, so it can be neither left behind nor covered.

If `leaving-the-desktop-darkens-the-ground` FAILS, §2.6 cannot use occlusion and
must move to `NSWorkspace.activeSpaceDidChangeNotification`.

## Step 2 — ANSWERED 2026-08-23, and the answer is NO

**Can a `WKWebView` be transparent over the face, with public API only? No.**

Full readings, controls and disposition: `SPIKE-013` §0 (status `RUNNING` in
`docs/spikes/INDEX.toml`). Instrument: `app/home-macos/glass_probe.swift`, run
twice at two window levels with identical readings.

- Every public configuration paints `#FFFFFF` over the ground — including
  `underPageBackgroundColor = .clear`, which is **set, held, and reads back at
  α 0.00** while changing nothing. It is the scroll-bounce colour, and it is the
  whole public surface: no macOS 26 addition touches background.
- The private `_setDrawsBackground:` **and** the legacy WebKit1
  `WebView.drawsBackground` (which is public, and deprecated since 10.14) both
  let the ground through — on the same instrument, in the same run. That is what
  makes this a finding rather than a blind spot.
- So it is not "no public route exists". It is **"no public route exists on
  `WKWebView`"** — and the one that does forecloses Tauri, whose macOS backend
  *is* a `WKWebView`.

**The instrument is the other half of the deliverable.** Two earlier ones failed
silently in opposite directions: `takeSnapshot` composites onto an opaque bitmap
(reports opaque for a transparent page), `cacheDisplay` only draws this
process's views (reports opaque for anything WebKit renders). This one asks the
window server for the composite of our own window, and does not trust that
either — `CGWindow.h:264` returns *transparent black* when a window can't be
read, which is indistinguishable from success. Three controls run first, and
`B1` (a page painted edge to edge in `#FF00FF` must read back `#FF00FF`) is the
one both earlier instruments would have failed.

**And the glass reaches the ground once it is transparent** (`SPIKE-013` §0.5).
A card blurring across a hard edge in the ground smears it over **41–42 pt**
inside the card and leaves it **0 pt** outside — on both routes, and over a real
`CAMetalLayer` as readily as a `CALayer`. It could have gone the other way: a
backdrop filter samples the page's own backdrop, and the field is not in the
page. So the §1.1 look is achievable; only the transparency is missing.

### DECIDED 2026-08-23 — the hatch, with an alarm

Owner chose: **take the private route, and make its failure loud.** Landed in
`bdc70ac`.

| | |
|---|---|
| `app/home-macos/GlassGuard.swift` | the ONLY file that may name `_setDrawsBackground:`. Carries the hatch, the reader, and three controls it runs every time |
| `VESPER --glass-verify` | `TRANSPARENT` / `OPAQUE` / `UNREADABLE`, exit `0` / `1` / `2`. **`UNREADABLE` is not a pass** |
| `VESPER --glass-verify --no-hatch` | the standing negative control. Measured: `#FFFFFF` red without the hatch, green with it |
| `CI-058` `glass-hatch-contained` | refuses the selector in any unmarked file, and refuses it in `GlassGuard.swift` if the reader or the negative control is removed. Found two files on its first run |
| `INV-HOME-5` | promoted from candidate **with the exception written into it**, traced to `SR-002` |

**Why the exception is coherent rather than a climbdown.** `ISLAND-ARCHITECTURE`
§2's own reason for banning private API is that *"the failure mode is silent"*.
The ban is against the silence. `SPIKE-013` produced a reader that sees the real
composite, so the silence is gone and the risk is one VESPER can see.

**The alarm's own first run reported `UNREADABLE`,** and the fault was the
alarm's: `navigationDelegate` is weak and nothing held the delegate between
steps. It refused to answer rather than guessing — which is what the three steps
are for, and why `UNREADABLE` is a separate verdict from `OPAQUE`.

### What is unblocked, and what is still not

**The 90 cards are unblocked.** Nothing about them is throwaway now: the chrome
can be transparent, and the glass blurs the live field behind it.

Still not done, and not blocked on the owner:

- **`SPIKE-013`'s actual question — the composite's COST — has no numbers.**
  That is the six-configuration table in §1, and it can now be measured against
  a configuration that ships. Its `on_fail` fallbacks stand unchanged.
- **`wry` is still unread.** If Tauri's macOS backend uses the same selector,
  the chrome inherits this hatch whether or not VESPER writes it — and
  `GlassGuard.verify` is the right alarm for that too, but `CI-058` cannot see
  inside a dependency. Read it the day it lands.

## Still open, carried forward

- **GPU/energy for the face is unmeasured** — `powermetrics` needs sudo. 117.9 fps
  at 0.2 % CPU is the CPU half only.
- `adopt_probe` built, never run. It is the *repair* path now, not placement.
- `intro.mp4` — proposed as the first-run cold open. Owner has not confirmed.
- The reference "cool ideas" primitives are identified, not yet engineered.
  Standing rule: adopt the primitives, refuse the habit of filling them.
