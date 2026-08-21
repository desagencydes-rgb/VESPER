# docs/design

Everything about how VESPER looks, moves and feels. Written down because it was
specified across several long conversations that a context compaction would
otherwise lose.

| Path | What it holds |
|---|---|
| `DESIGN-FOUNDATION.md` | **The spec.** Palette, themes, adaptive-colour rule, glass tiers, type, motion, the eleven ambience modes, the face, the mark, the dock swap, island geometry. Read this first |
| `routing/` | The owner's own placement decisions for 237 catalogue items — `spec_raw.txt` is the export as pasted, `routed.json` the parse, `data.json` the full catalogue including unrouted suggestions |
| `source/` | The generator for the interactive version. `build_artifact.py` reassembles it from the HTML fragments and inlines `refs/` as data URIs |
| `source/*.py` | The derivations, so no number here is a claim without a method — see below |
| `assets/` | The mark and the face reference at working resolution |

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

## Two standing corrections

- **The eleven images are feel sources, the mark, and the face. They are not UI
  references.** The owner was explicit about this. The primitives are decided;
  the composition of an actual screen is not, and waits on a reference set that
  had not arrived as of 2026-08-21.
- **New animations require owner approval.** The four springs plus the Dock
  magnification falloff are the entire motion vocabulary until the owner adds to
  it.

## Rebuilding the interactive version

```sh
cd docs/design/source && python3 build_artifact.py
```

Writes `vesper-design-foundation.html`, self-contained, ~3.6 MB. Note the paths
in `build_artifact.py` assume it runs from its own directory.
