# Home — where step 1 stands (2026-08-23)

Written for the session that picks this up. Commit `b2122bc`.

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

## Step 2 — next, and it is the last structural unknown

**Can a `WKWebView` be transparent over the face, with public API only?**
`underPageBackgroundColor` is the only public knob and looked insufficient; no
in-process instrument could confirm it (`takeSnapshot` composites onto an opaque
bitmap; `cacheDisplay` cannot reach out-of-process WebKit content). SPIKE-013
restarts here — and its question changed when the wallpaper became the real
desktop picture, because no opaque full-screen layer of ours is in the
compositing path any more.

This decides whether card work is throwaway. **Do not start the 90 cards before
it is settled.** A `--look` mode (owner looks at the screen for 20 s) was drafted
and never applied; that may be the only honest instrument left.

## Still open, carried forward

- **GPU/energy for the face is unmeasured** — `powermetrics` needs sudo. 117.9 fps
  at 0.2 % CPU is the CPU half only.
- `adopt_probe` built, never run. It is the *repair* path now, not placement.
- `intro.mp4` — proposed as the first-run cold open. Owner has not confirmed.
- The reference "cool ideas" primitives are identified, not yet engineered.
  Standing rule: adopt the primitives, refuse the habit of filling them.
