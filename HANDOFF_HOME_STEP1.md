# Home — state of play (2026-08-24)

Written for the session that picks this up. Steps 1 and 2 are done; the home
runs from the login item and does not stop.

## Owner's standing facts

- **Desktop 1 is the owner's. Desktop 2 is the empty one — that is VESPER's.**
- The owner asked to be stopped and told whenever a run needs them.
- **Do not black out a Desktop that has their windows on it.** The occlusion
  phase did this once, unannounced, and it is now guarded.

## What runs, right now, with nothing to start by hand

`~/Library/LaunchAgents/ai.vesper.island.plist`, `RunAtLoad`, `KeepAlive`:

```
VESPER --home --on-empty-desktop --mode Home --chrome
```

One process. Island, ground, face, glass plate, chrome and main menu. It waits
**indefinitely** for a Desktop with none of the owner's windows on it and takes
nothing until it finds one — no `--wait`, because a timeout exit under
`KeepAlive` is a restart loop. The wait does not block, so the island is up the
moment the process is.

Its log is `~/Library/Application Support/VESPER/island.out`, live rather than
buffered.

## What is built and measured

| | Verified by |
|---|---|
| **The two-layer home** — Metal field below, transparent `WKWebView` above | `--face-check`: the card paints where the ground paints nothing; face contrast unchanged with the chrome over it |
| **The glass hatch** — the one private call, with an alarm | `--glass-verify` → `TRANSPARENT`; `--glass-verify --no-hatch` → `OPAQUE #FFFFFF`. `CI-058` |
| **The plate behind the face** — Dock tier, fill solved from the wallpaper | backdrop `0.494` → fill `0.757` → ground `0.120` predicted, `0.125` measured |
| **The falloff** — glass at the rim, contrast at the centre | rim reads `2.8x` the centre |
| **The face** — density derived from the layer, not inherited | `10.3%` of its region above its ground, up from `0.61%` |
| **§8's four tiers** — Centre, Attendant, Dispersed, Absent | `--cost-check`: Absent draws **0 frames**, every run |
| **The occlusion stop** | `--occlusion-check` → `0.02 s` by notification; `--poll-only` → `0.50 s` by poll |
| **Icons and widgets hidden on VESPER's Desktop only** | **486/486** tiles of the ground read alpha >= 0.99 |
| **The main menu** — §14.2's bar, avatar, separate expandable tile | `--face-check`: paints at the Dock's position |
| **The dock swap** — §10 | mechanism wired; **not yet observed on Desktop 2** — watch the log for `system dock down` |

`SPIKE-013` §1a carries the cost table. The composite costs **+0.053%** of one
core.

## GENUINELY BLOCKED — and on what

| # | What | Blocked on |
|---|---|---|
| 1 | **`SPIKE-013` criteria 1, 5, 6** — GPU, package power, battery drain, idle cadence | **`sudo powermetrics`.** Owner action. Everything on screen runs at an unmeasured power budget |
| 2 | **Criterion 2** — `DISPERSED <= CENTRE` | Same. CPU came back **inconclusive**: `centre 0.222 [0.193 … 0.263]` against `dispersed 0.244 [0.223 … 0.275]`, ranges overlap, so the axis cannot separate them. §3 refuses "about the same" in **both** directions |
| 3 | **Criterion 4 at full scale** | A run on VESPER's own Desktop — forcing occlusion means covering the whole display in black. The mechanism is verified; only the full-size figure is owed |
| 4 | **The eight main-menu icons** | Owner: *"we'll have to define them, then get them or build them."* Eight meanings, then eight icons. Placeholders ship until then, and they look like placeholders on purpose |
| 5 | **The face is a floating head** | §14.1 says a **bust** — head, neck and shoulders — at roughly the middle fifth of the width, from under the menu bar to two-thirds down. Needs `face_cloud.py` work **and** an owner decision, because it moves where every card goes |
| 6 | **§10's 30% dim under the Dock** | No public API for the **autohide reveal** — it reserves no space, so `visibleFrame` cannot see it, and the Dock's own window bounds are the whole display. The persistent Dock is handled. The alternative is watching the cursor, which is watching the cause and calling it the effect |
| 7 | **APCA** | §3 names `Lc >= 60`. The card solves a **WCAG-style luminance ratio** instead, labelled as a proxy in the code and in its own readout. Needs APCA's constants from source |
| 8 | **Whether Tauri already uses the private hatch** | `wry` is not installed. If it does, choosing Tauri accepts the hatch inside a dependency, where `CI-058` cannot see it |
| 9 | **Switching Spaces programmatically** | §2.3a — no public API names a Space. An Accessibility grant would do it, and this build deliberately has not asked for one |

## Not blocked, not started

The rail (§14.2's four glass buttons), the transcript line, the remaining cards.
The composition question (#5) should be settled first: moving 90 cards later
costs more than moving one now.

## Verification, all of it

```sh
python3.13 tools/ci/checks.py all          # 32
python3.13 tools/ci/self_test.py           # 80, red then green
python3.13 tools/reference_lint.py
python3.13 tools/traceability_lint.py

VESPER --glass-verify              # 0 transparent · 1 opaque · 2 unreadable
VESPER --glass-verify --no-hatch   # must go RED
VESPER --occlusion-check           # both directions
VESPER --occlusion-check --poll-only
VESPER --home --mode Home --chrome --face-check --seconds 14
VESPER --home --mode Home --cost-check --cost-seconds 6 --cost-repeats 3
```

**`python3.13`, not `python3`** — the system 3.9 dies on `tomllib`, and
`checks.py` still exits 0 while doing it.

## Things that bit, worth not repeating

- **A patch script is an instrument.** A multi-part replacement reporting one
  boolean hid the one anchor that missed; the scrim did not exist for three
  measurements while the reader took the blame. Assert every replacement.
- **`framesDrawn` counts attempts.** It reported 367 frames for a face nobody
  could see, and 116.8 fps for a ground that was fully covered.
- **A mean hides the run that did nothing.** Print every run before any average.
- **`String(format:)` with `%@` and a C string is a SIGTRAP with no message**,
  and it will happen after the measurement has completed.
- **Two definitions of the same plist drift.** `launchctl` will happily report
  "reloaded" for a file that did not change.
