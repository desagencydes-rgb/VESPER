# Codex brief — the main menu and the expandable menu

Written 2026-09-07 so a second agent can build these in parallel without
colliding with the session working on the rest of `HOME-WORKBENCH.md`.

## Why this is the right slice to hand over

It is visual and interaction work with a clear contract, it touches no
invariant, and it is currently **placeholders** — `{{slots}}` renders eight
identical rounded-square SVGs and the expandable tile says
`"expandable menu — placeholder"` in its own title attribute.

It also runs on a **different account**. The Claude rungs share two
subscriptions and the owner has already hit a session limit on one of them
today; codex has its own.

## THE THREE CONSTRAINTS. Breaking any of them costs more than the work saves.

### 1. `home.html` is the collision point — stay inside the markers

Everything renders through one file, `app/home-macos/chrome/home.html`, and the
other session edits it too. Work **only** between these markers, which exist
for this purpose and are otherwise untouched:

```
/* ==== MENU: codex owns everything between these markers ==== */
/* ==== /MENU ==== */
```

CSS goes in the first pair, markup in the second, script in the third. Do not
edit outside them. Do not reformat the file.

### 2. Never run `build.sh`

**Every build re-signs the bundle ad-hoc, and macOS keys TCC grants to the code
signature.** A build silently revokes all six of the owner's grants —
microphone, speech recognition, calendar, reminders, accessibility, Apple
Events — and each one costs them a manual trip through System Settings. This
has already happened twice today.

Iterate against the file instead: `HomeChrome.template()` reads
`app/home-macos/chrome/home.html` from the repo first, so the running app picks
up markup changes on its next mount with no build at all. Verify with:

```
app/VESPER.app/Contents/MacOS/VESPER --chrome-probe
```

which loads the page offscreen in a real WKWebView and prints the DOM back.

### 3. Do not touch `HomeChrome.fallbackTemplate()`

It is GENERATED from `home.html` by `tools/sync_chrome_fallback.py`, and
`CI-065` compares them byte for byte. The other session regenerates it. If you
edit it by hand the gate goes red and the two copies fight.

## What to build

**The main menu** (`.dockrow` / `.bar`). Eight slots, currently placeholder
glyphs. Each needs a real icon and a real action posted over the existing
`vesperAct` bridge (see `app/home-macos/ActBridge.swift` for the message shape
and for what it will and will not accept from a page).

**The expandable menu** (`.tile`, right of the separator). §14.2 calls it "a
SEPARATE expandable menu tile at its right end" — separate is the point, it is
not a ninth slot. It should open into a panel listing what the eight cannot
hold.

## The design is already decided — do not invent one

Read `docs/design/DESIGN-FOUNDATION.md` first. The tokens are in the page:

- Dock tier: `blur(42px) saturate(200%)`, fill `.085`, radius `34`
- Ink `--ink: #f4e6dc`; secondary at `.62`, tertiary at `.34`
- Type: `--face-body`; never introduce a face
- Motion: `cubic-bezier(.32,.72,0,1)`, 220–280 ms
- Slot hover is already specified: `translateY(-6px) scale(1.06)`

## Rules that are enforced mechanically

- **`textContent`, never `innerHTML`**, for anything derived from `home.json`.
  `CI-127` parses for it. These strings carry a model's output.
- **Nothing may reach the terminal.** `CI-129` asserts that no renderer can
  post to `vesperTerm`. Do not add one.
- **Theme-aware and bounded**: every list capped, every cap named.

## Definition of done

`app/VESPER.app/Contents/MacOS/VESPER --chrome-probe` shows the menu rendered
with real labels, and clicking a slot posts the intended `vesperAct` message.
Hand back the diff; the other session runs the gates, regenerates the fallback,
and builds once at the end.
