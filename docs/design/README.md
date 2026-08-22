# docs/design

Everything about how VESPER looks, moves and feels. Written down because it was
specified across several long conversations that a context compaction would
otherwise lose.

| Path | What it holds |
|---|---|
| `DESIGN-FOUNDATION.md` | **The spec.** Palette, themes, adaptive-colour rule, glass tiers, type, motion, the eleven ambience modes, the face, the mark, the dock swap, island geometry. Read this first |
| `ISLAND-ARCHITECTURE.md` | The island's behaviour and wiring: its seat as an endpoint, the state machine, what backs each column, how it behaves everywhere on the Mac, and the build order |
| `ANNEX-island-geometry.md` | **Build from this.** The measured proportions landed on a clean system anchored to the two hardware facts |
| `ISLAND-CONTENT.md` | Everything each island state can carry, each marked LIVE / READY / BLOCKED, so designing and wiring do not wait on each other |
| `HOME-ARCHITECTURE.md` | **VESPER's home.** What a workspace is on this OS and what it provably is not, the five surface classes, stages, the face's presence law, and the build order that puts the frontend first |
| `HOME-CONTENT.md` | All 90 home cards, the widgets, the windows and the twelve stages, each marked FRONTEND / READY / BLOCKED. **56 of 90 are buildable before a producer runs** |
| `ui-refs/` | **The owner's UI reference set** — what a screen is actually composed of, with the geometry measured out of it. The island only; every other surface is still unreferenced. Has its own README |
| `routing/` | The owner's own placement decisions for 237 catalogue items — `spec_raw.txt` is the export as pasted, `routed.json` the parse, `data.json` the full catalogue including unrouted suggestions |
| `source/` | The generator for the interactive version. `build_artifact.py` reassembles it from the HTML fragments and inlines `refs/` as data URIs |
| `source/*.py` | The derivations, so no number here is a claim without a method — see below |
| `source/artifacts/` | The two published pages and their sources. The architecture page is **built from the markdown**; the previews page is hand-authored and carries a DOM-stub test with executed negative controls. Has its own README |
| `assets/` | The mark and the face reference at working resolution |
| `assets/wallpapers/` | **The owner's eleven mode wallpapers and four videos.** Authored, irreplaceable, and committed for that reason — they existed only in one Downloads folder on one laptop |

Interactive version:
<https://claude.ai/code/artifact/aec78c48-24ad-4e69-a2a2-e27b9a67308c>

## The derivations are runnable

Nothing in the spec is asserted from taste where it could be computed. Each
script is stdlib-only and prints what it found:

```sh
python3 docs/design/source/oklch.py     # palette -> OKLCH + contrast on both grounds
python3 docs/design/source/springs.py   # SwiftUI Spring(duration:bounce:) -> CSS linear()
python3 docs/design/source/extract.py   # k-means over each source image, in OKLab
python3 docs/design/source/modes2.py    # the LIGHT SOURCE in each image, not its mean
python3 docs/design/source/final.py     # -> modes.json, the eleven ambience themes
python3 docs/design/source/island_geom.py  # the island, measured out of ui-refs/
python3 docs/design/source/home_rooms.py   # the home's nine rooms, out of the owner's own routing
python3 docs/design/source/tiny.py         # regenerate refs/tiny/ -- extract.py and modes2.py need it
python3 docs/design/source/home_wallpapers.py  # do the wallpapers agree with the ambience they carry?
```

`extract.py` decodes PNG with `zlib` + manual defiltering rather than pulling a
dependency, so these run on a bare interpreter like `profile_node.py` does.

**Why `modes2.py` exists at all.** `extract.py` alone produced nonsense: five of
the eleven modes collapsed onto pink and Alert came out green. Clustering
averages away the only thing that gives a night frame its character — one small
saturated light in a large dark field. Taking the accent from the top 4% of
pixels by brightness x chroma fixed eight of eleven outright. The remaining
three are marked `curated` in `modes.json` with the reason recorded, because a
judgement call that looks like a measurement is worse than either one.

## Four standing corrections

- **The eleven images in `source/refs/` are feel sources, the mark, and the face.
  They are not UI references.** The owner was explicit about this. The UI
  reference set is a separate thing and lives in `ui-refs/`: the island arrived
  2026-08-21, **the home arrived 2026-08-22**. The rooms, Settings and History
  are still undecided and still waiting.
  **Amended 2026-08-22:** the eleven are now also the **wallpapers**, one per
  ambience mode, in `assets/wallpapers/`. That does not make them UI references —
  they still say nothing about composition — but it does mean each mode's accent
  was derived from the very picture that sits behind it. `source/home_wallpapers.py`
  measures the agreement: **all 8 measured modes within 30°, none diverging.**
- **The blue face was never the reference.** Replaced 2026-08-21 on the owner's
  correction; §8 had said "Not blue" all along, so the spec was right and the
  asset was wrong. `build_artifact.py` inlines `source/refs/face.jpg`, so the
  interactive version had been rendering the wrong face until then.
- **New animations require owner approval.** The four springs plus the Dock
  magnification falloff were the entire motion vocabulary until the owner added
  to it. **Two additions so far:** the mark's four state motions (2026-08-21) and
  the face's **dissolve** (2026-08-22) — the point cloud's attractor released, not
  a fade. Nothing else is in the vocabulary.
- **The home is not a window.** `HOME-ARCHITECTURE.md` §2 checked the SDK
  directly: there is no public API to create, name or enumerate a Space, and
  Accessibility cannot move a foreign window between Desktops. The home is a
  ground window at `normal − 1` on a Desktop the owner creates once, and the
  owner's "move it to his workspace and put it back" is implemented as re-open
  from a ledger, never as teleport.

## Rebuilding the interactive version

```sh
cd docs/design/source && python3 build_artifact.py
```

Writes `vesper-design-foundation.html`, self-contained, ~3.6 MB. Note the paths
in `build_artifact.py` assume it runs from its own directory.
