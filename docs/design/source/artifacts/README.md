# The home artifacts

Two published pages, and the sources that produce them. The design system they
render is `../../DESIGN-FOUNDATION.md` — every colour, glass tier, typeface and
spring here comes from it, and none is invented locally.

| | |
|---|---|
| `build_home_doc.py` | Builds the architecture page **from the markdown**, so the artifact is a rendering of `HOME-ARCHITECTURE.md` and `HOME-CONTENT.md` rather than a second copy of them. Edit the markdown, rebuild, republish |
| `md2html.py` · `doc_css.py` · `doc_body.py` | Its converter, stylesheet and shell |
| `home-previews.html` | The previews page. Hand-authored — it is the source, not an output |
| `test_previews.js` · `dom_stub.js` | Drives the previews page against a DOM stub |

```sh
python3 docs/design/source/artifacts/build_home_doc.py out.html
~/.local/node/bin/node docs/design/source/artifacts/test_previews.js
~/.local/node/bin/node docs/design/source/artifacts/test_previews.js --controls
```

## Why there is a test for a mockup

There is no browser automation on this machine and `node --check` only proves
the file parses. `test_previews.js` renders every stage × desk × ambience mode
and asserts the output — and **carries its own negative controls**, because a
harness nobody has seen fail proves nothing. `--controls` mutates the page three
ways and requires each mutation to go red.

## What these pages may and may not claim

**The composition is a proposal.** `../../ui-refs/` covers the island only; the
home has never had a reference set, and the previews say so on the page in the
first screen of copy. What is honoured rather than invented: the ten palette
colours, the four glass tiers at their measured blur / saturate / fill / radius,
the three typefaces through their agreed web substitutes, the four springs as
`linear()` emitted by `../springs.py`, the eleven ambience grounds and accents
from `../modes.json`, and the island geometry from `../island_geom.json`.

**The face here is not the face.** These canvases run ~900 points; the native
renderer runs 39,805 in Metal at a measured 5–7% CPU. Nothing on these pages is
evidence about the real renderer's cost — that is `SPIKE-013`, and its pass
condition is pre-registered.
