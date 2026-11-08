# Showroom brief — the README that opens the repository

**For:** the agent (Codex) that will write `README.md`, the page GitHub shows
first. **Written:** 2026-11-08, when the repository was prepared for open
source. Everything an agent needs is in this file or linked from it. It does not
need the original author's chat history or memory.

The goal, in the owner's words: *"very impressive, with logos, images, styles,
everything about vesper, status, guides, goals, plans, architecture, and
statuses of what's finished, what needs fixing and what remains."* A website
for VESPER is planned later, so write README sections that could lift straight
onto a landing page.

---

## 1. Ground rules — read before writing a word

1. **Every number comes from a command you ran, with its date.** Do not copy a
   figure out of this file or any other document without re-running its
   command. This corpus has corrected its own check counts eight times. Its
   founding rule is *"if a statement contradicts a command's output, the
   command wins."* §5 gives the commands.
2. **Do not show a passing CI badge you cannot back up.** `.github/workflows/ci.yml`
   runs on `ubuntu-latest`, and some checks need a built macOS bundle. Look at
   the Actions tab after the first public push. Badge only what is actually
   green. A red badge on day one is worse than none; a fake green one is worse
   than red.
3. **Nothing aspirational is described as built.** Use the inventory in §4. If
   it is under *Unfinished* or *Not solved*, the README says so.
4. **Do not move or rename root documents.** `CI-089` reads figures out of
   `CLAUDE.md` and `VESPER_ENGINEERING_STATUS.md`. `tools/reference_lint.py`
   and `tools/traceability_lint.py` resolve paths across the corpus.
5. **After rewriting `README.md`, run** `python3.13 tools/reference_lint.py`
   and `python3.13 tools/traceability_lint.py`. Use `python3.13`: on macOS's
   3.9, both crash on `tomllib` and still exit 0.
6. **Never run `docs/design/source/final.py`.** It regenerates `modes.json`,
   which every surface reads.
7. **GitHub README rendering:** no JavaScript and no custom CSS. Inline HTML
   (`<p align="center">`, `<picture>`, `<img width>`, `<details>`), tables,
   Mermaid diagrams and `> [!NOTE]` alerts all render. **`.mp4` files in the
   repo do not play inline.** To show motion, either convert a short clip to
   GIF/WebP under ~5 MB, or upload the mp4 to a GitHub issue or release and
   embed the resulting `user-attachments` URL.
8. Keep the existing identity quote. It is the thesis:
   > The model is replaceable. The device is replaceable. The UI is replaceable.
   > The network path is replaceable. The provider is replaceable.
   > **VESPER's identity, goals, state, policies, memory, capabilities and
   > continuity are not supposed to disappear merely because one of those
   > components disappears.**

---

## 2. What VESPER is

A **persistent, distributed artificial operating presence**, not an LLM with
tools and a chat UI. Models, devices and providers are interchangeable parts.
What persists is VESPER's identity, memory, policy and continuity.

- **Two goals** (owner, standing): *stretch every host's lifetime* (power,
  heat and battery are first-class inputs, and the build has turned down
  running local models on a laptop) and *maximise joint capability* across
  every machine enrolled.
- **Single-node deploy, never single-node design.** It runs on one Mac today,
  and it is built so a new node joins the fabric and wins placement on merit
  (`INV-PLACE-3`).
- **Measured, never declared.** A node's throughput is measured when it
  enrolls. `UNKNOWN` means `UNAVAILABLE` (`INV-HW-2`).
- **Governed.** It acts on a real machine (windows, screen, commands, calendar,
  notes) under a two-axis authority ladder. Anything from outside (web pages,
  MCP tool descriptions, files) is data, never instruction (`INV-ACT-3`). The
  stop never passes through the runtime (`INV-STOP-2`).
- **Its own presence on macOS:** an **island** welded to the notch, a **face**
  that dissolves and speaks, a **home** that is VESPER's own Desktop, and a
  **showcase** window where it lays out work and follows your screen.
  Summoned with **globe ×3** or the wake word.
- **Speaks the owner's language.** Arabizi/Darija input is a first-class path
  (`core/arabizi.py`).

## 3. Architecture

The authority chain, top to bottom (from the current README; keep it):

```
handwritten source → COC + Rulebook → ADRs → Foundation / Baseline
  → remediation + system specification → contracts + mechanisms → verification + CI
```

The code, by layer:

| Layer | Where | What it holds |
|---|---|---|
| Native surfaces | `app/island-macos/`, `app/home-macos/` | One Swift binary: island, home, showcase, globe watcher, wake listener, every helper as a *mode*. Built with plain `swiftc` |
| Runtime | `tools/ops/vesper_runtime.py` | The pump: hears, decides, acts, answers |
| Core | `core/` (107 modules) | bus, store, tasks, taint, authorize, capability, evidence, placement, enrollment, telemetry, autonomy, the memory system (arbiter, compactor, cache, knowledge map), MCP client, speech |
| Routing | `routing/` + `contracts/policy/provider_supply.toml` | The model ladder: rungs across a dozen providers and two subscription CLIs, gated by **egress class** (`E1-PRIVATE` vs `E2-PUBLIC`) before quota |
| Contracts | `contracts/` | Events, commands, results, entities, policy (TOML + JSON Schema) |
| Spec | `spec/` | 12 state machines, 38 decision functions, invariants |
| Verification | `verification/`, `tools/ci/` | F0–F6 acceptance suites, property stress, 207 registered checks, red-run self-test harness |
| Design | `docs/design/` | Palette, type, motion, glass, eleven ambience modes, the face |

A Mermaid diagram of this flow would serve the page well: surfaces →
runtime → core → routing → providers, with contracts/spec feeding
verification. Deeper reading for the architecture section:
`docs/architecture/SPEC-00-INDEX.md`, `docs/AUTHORITY_AND_PRECEDENCE.md`,
`docs/ADR/`, `docs/design/HOME-ARCHITECTURE.md`.

## 4. Status inventory, 2026-11-08

Source of truth: [`VESPER_OPEN_WORK.md`](../VESPER_OPEN_WORK.md). Re-read it;
it may have moved since this was written.

### Done, with proof

- **Engineering foundation:** spec, contracts, ADRs, 182 invariants, 12 state
  machines, 38 decision functions.
- **F0–F6 acceptance suites** (runtime, endurance, network fabric) were run on a
  Windows desktop and a Linux laptop. Property stress: 160,000 placement and
  180,000 fabric assertions.
- **The memory system**, built and gated.
- **VESPER can act:** four capabilities in a six-step loop, contained,
  checkpointed and two-axis authorised.
- **The showcase:** panes, marks, its own cursor and browser, a whiteboard and a
  live run tail. 396 end-to-end assertions over five rounds. A soak ran 8 min
  under three writers at 7.9% CPU with memory steady at ~75 MB and p95 283 ms.
- **Globe ×3** calls VESPER onto the Desktop you are on.
- **Following the owner's screen** (a real 1728×1117 frame).
- **The app no longer invalidates its own code signature.** That fault had
  blocked reopening it after a permission grant; it is now gated.

### Broken (open bugs)

- The showcase can collapse its panes into a strip (`#grid` sizes rows to
  content). §2.1.
- VESPER speaks in the host's default voice; nothing sets `plan.voice`. This is
  the one known-red check, `speech-is-egress-and-says-so`. §2.2.
- Speaking blocks the runtime for as long as the sentence lasts (6.1 s for 19
  words, measured). §2.3.

### Unfinished

- Non-blocking voice: `core/speech.Voice` is written and reached by nothing.
- Typing through the accessibility bridge is not proven.
- Screenshot verification is not wired into the harnesses.
- Scenes and demonstrations are scripted by hand; VESPER does not yet compose
  them itself. This is blocked on model access.
- 18 of 207 registered checks are still `impl = "PENDING"`, and ~10 runnable
  checks are not yet in the registry.
- **In flight when work stopped:** when no Desktop is empty and VESPER is
  called to a busy one, the showcase should open full screen. Uncommitted
  changes to `app/home-macos/Showcase.swift` and `chrome/showcase.html` exist
  in the original working copy only.

### Not solved (no known answer)

- VESPER has no Desktop of its own until the user switches to an empty one. It
  never *takes* a Desktop with the user's windows on it.
- macOS will not move another application's window between Desktops.
- Accessibility answers only for the Desktop that is showing.
- TCC grants and ad-hoc rebuilds: which grants survive a rebuild is not fully
  derived. A Developer ID certificate would settle it.

### Platforms

- **macOS (Apple Silicon):** furthest ahead. Everything above.
- **Windows / Linux:** the Python core, the routing ladder and every gate run.
  The acceptance suites were run there. **There is no visual shell.** The
  decided frontend for everything except the island is **Tauri**, and nobody
  has built it. This is the biggest open area for contributors.

## 5. Figures — run these, then quote them with today's date

```sh
python3.13 tools/ci/checks.py all          # "N/M checks passed"
python3.13 tools/ci/checks.py ci-registry  # checks, invariants, PENDING, ENFORCED TODAY
python3.13 tools/traceability_lint.py
python3.13 tools/reference_lint.py
git ls-files '*.py'    | xargs wc -l | tail -1
git ls-files '*.swift' | xargs wc -l | tail -1
git rev-list --count HEAD
```

Measured when this brief was written (2026-11-08), so you can tell if
something moved:

| Figure | Value |
|---|---|
| Registered checks | 207 (18 PENDING) |
| Invariants enforced by a real, red-run check | 131 / 182 |
| `checks.py all` | see `VESPER_OPEN_WORK.md` §1; one known red (`speech-is-egress-and-says-so`) |
| Self-test cases (red-then-green) | 1090 |
| Python | ~109,500 lines |
| Swift | ~21,300 lines |
| Commits | 639, first on 2026-08-12 |

## 6. Visual assets

All are owner-supplied and published with the repository under its MIT license.

| Asset | Path | Size | Use |
|---|---|---|---|
| App icon / mark | `docs/design/assets/vesper-icon.png` | 1024² | Logo at the top (render ~120–160 px) |
| Face | `docs/design/assets/face-reference.jpg` | 1200² | Hero, or beside the "what it is" section |
| Face + hologram panels | `docs/design/ui-refs/face-and-hologram-panels.jpg` | 1254² | Design section |
| Home reference | `docs/design/ui-refs/home-reference-1.jpg` | 1317×852 | "The home" |
| Island in situ | `docs/design/ui-refs/island-in-situ.jpg` | 1400×907 | "The island" |
| Island crops | `docs/design/ui-refs/island-*.png` | 742 wide | Small strip under the island section |
| Ambience wallpapers | `docs/design/assets/wallpapers/{home,idle,watch,thinking,working,speaking,flow,alert,rest}.png`, `milestone.jpg` | ~1672×941 | A mode gallery (a 3×3 grid of thumbnails) |
| Animated wallpapers | `docs/design/assets/wallpapers/{intro,rest_animated,milestone_animated,speaking_animated}.mp4` | 4–7 MB | Upload or convert; see rule 7 |
| System blueprint poster | `output/pdf/VESPER_SYSTEM_BLUEPRINT_PREVIEW.png` | 4961×7016 | Architecture section (link the PDF beside it) |

**These are references and mood images, not screenshots of the running app.**
Label them as design references. For real screenshots, build the app
(`docs/INSTALL.md` §5) and capture the island, home and showcase. Check them
for personal content before committing.

### Design language

Palette (from `docs/design/DESIGN-FOUNDATION.md` §1). Use it for badges and
any shields.io colours:

| Name | Hex | Role |
|---|---|---|
| pitch | `#03141f` | Ground, dark |
| paper | `#ffeae3` | Ground, light |
| cream | `#f0e0c0` | Lit surfaces |
| orange | `#ffaf95` | Accent, dark theme |
| ember | `#B96645` | Accent, light theme; warning |
| solar | `#D99A52` | Speaking |
| blush | `#e8829d` | Thinking, milestone |
| purple | `#59348a` | Watching, listening |
| gold | `#C5A35A` | Work that is holding |
| botanical | `#64745B` | Rest |

Typefaces are Aeonik, Canela and Learning Curve. They are commercial, not in
the repo, and not needed for the README.

## 7. Suggested shape

1. Centred logo, name, one-line thesis, a few honest badges (license MIT,
   platform macOS | Windows/Linux core, "status: open for contributors").
2. The identity quote.
3. A hero image (face or home reference), labelled as a design reference.
4. **What it is**, in about five bullets from §2.
5. **Surfaces:** island / home / showcase, each with its image.
6. **Architecture:** a Mermaid diagram and the layer table.
7. **Status:** Done / Broken / Unfinished / Not solved, from §4, with a
   per-platform table.
8. **Get started:** link [`docs/INSTALL.md`](INSTALL.md) with a 5-line quick
   start.
9. **Goals and roadmap:** Tauri shell for Windows/Linux, non-blocking voice,
   model-composed scenes, a Developer ID certificate, multi-node fabric,
   the website.
10. **Contributing / Security / License:** link `CONTRIBUTING.md`,
    `SECURITY.md`, `LICENSE`.
11. **Ambience gallery** inside a collapsible `<details>`.
12. **How this was built**: an engineering corpus where every claim carries a
    measurement and every check has a recorded red run. Link `MEMORY.md` and
    `docs/DECISION_LOG.md`. This discipline is the project's most unusual
    feature; show it.
