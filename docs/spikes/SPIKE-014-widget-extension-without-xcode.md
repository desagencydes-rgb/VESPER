# SPIKE-014 — A WidgetKit extension without Xcode, and its real refresh budget

| | |
|---|---|
| **Status** | NOT_STARTED |
| **Question** | Can a WidgetKit extension be built and registered by hand — `swiftc` plus an assembled `.appex`, the way `app/island-macos/build.sh` already assembles `VESPER.app` — and what reload cadence does macOS actually grant it? |
| **Time box** | 2 working days |
| **Owner** | Platform Engineer |
| **Depends on** | `VESPER.app` bundling and the local signing identity (`tools/make_signing_cert.sh`) |
| **Requires hardware** | Yes — this machine |
| **Raised by** | `HOME-ARCHITECTURE.md` §4, 2026-08-22 |
| **Blocks** | The system-widget half of the owner's requirement that VESPER's widgets *"can be added in other workspaces via the add widget feature"* |

> **What is already known, and how.** Verified 2026-08-22 by `swiftc -parse`
> against the macOS 26.5 SDK: `WidgetKit`, `SwiftUI`, `AppIntents` and `WebKit`
> all resolve under Command Line Tools with **no Xcode on this machine**. That
> settles the compiler and settles nothing else. Whether a hand-assembled
> `.appex` *registers* with the widget system is a different question, and the
> island already produced the cautionary case: `SMAppService` compiled,
> registered without throwing, reported "enabled", and launchd refused to spawn
> the app every time.

> **A registration that returns without error is not a widget on the desktop.**
> The reading is the gallery, and then the desktop.

---

## 1. What gets measured

```
1. Assemble a minimal .appex by hand: swiftc against WidgetKit, an Info.plist
   with NSExtensionPointIdentifier = com.apple.widgetkit-extension, placed in
   VESPER.app/Contents/PlugIns/. Sign with the local identity.
   READ BACK: does it appear in the widget gallery?

2. Place it on the desktop. Read back that it renders.

3. LSUIElement question: VESPER.app is currently an accessory app
   (no Dock tile). Determine whether a widget from an accessory app is offered
   in the gallery at all, and record the answer either way -- it decides
   whether the home ships as a second bundle or the island stops being
   LSUIElement.

4. Rebuild, re-sign, re-place. Does the widget survive a rebuild?
   Does it survive a reboot? Do the TCC grants survive with it?

5. THE CADENCE. Leave the widget in place for >= 12 hours with a timeline that
   requests the most aggressive reload policy available. Log every reload with
   its wall time from inside the provider. Report the DISTRIBUTION -- count,
   median gap, worst gap -- not the nominal policy.

6. Staleness: let a reading pass its ttl_ms while the widget is on screen.
   Read the screen. It must render the absent state.
```

## 2. Pass criteria

| # | Criterion |
|---|---|
| 1 | A hand-assembled `.appex` appears in the gallery and renders on the desktop |
| 2 | It survives a rebuild, a re-sign and a reboot |
| 3 | The observed reload cadence is reported as a **distribution over ≥ 12 hours**, with its worst gap |
| 4 | An expired reading renders the absent state **on screen**, verified by looking, with freshness evaluated at render time rather than at timeline-build time |
| 5 | The accessory-app question (step 3) is answered either way |

## 3. On fail

**If a hand-assembled extension cannot register**, that is recorded as a
limitation with its cause, and the system widget is deferred until Xcode or a
Developer ID makes it buildable. **The in-home widget is not redefined as "the
widget" to make the requirement met** — the owner asked for widgets that leave
the home, and a widget that stays home is a different object (§4).

**If the granted cadence is too slow for a candidate reading**, that reading
does not become a system widget. This is not a failure to route around: a number
the OS will hold on screen for hours is a number that must carry its age or not
appear, which is `INV-HOME-2`'s candidate statement and the same rule that
refused `41 °C` on the island.

**Not permitted:** reporting a reload triggered by hand, by a debugger, or by
`WidgetCenter.reloadAllTimelines()` as the system's own cadence; reporting the
policy requested instead of the cadence observed; shipping a widget whose
freshness is decided when the timeline is built.

## 4. Deliverables

1. Yes/no on hand-assembled registration, with the plist and layout that worked
   or the error that stopped it.
2. The accessory-app answer, and what it costs if it is "no".
3. The cadence distribution over ≥ 12 hours: count, median, worst.
4. A screenshot of the expired-reading render, because that one is judged by
   looking.
5. A list of which candidate readings are affordable as system widgets at the
   measured cadence, and which are not.
