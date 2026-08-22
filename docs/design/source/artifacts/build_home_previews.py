"""Inline the owner's wallpapers into the previews page.

WHY THE PAGE DOES NOT CARRY THEM. An Artifact must be self-contained -- the CSP
blocks every external host -- so the eleven wallpapers have to be embedded as
data URIs. Committing them embedded would put ~2 MB of base64 in git ON TOP OF
the 44 MB of originals in `docs/design/assets/wallpapers/`, and a second copy of
an asset is a second thing to keep in step. Same reasoning as `build_artifact.py`
one directory up, which inlines `refs/` rather than committing an inlined page.

    python3 docs/design/source/artifacts/build_home_previews.py [out.html]

Default output is `home-previews.built.html` beside the source, git-ignored.
Stdlib only; `sips` ships with macOS.
"""
from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "home-previews.html"
WALLPAPERS = HERE.parents[1] / "assets" / "wallpapers"
MARKER = "<!--WALLPAPERS-->"

MODES = ["home", "idle", "watch", "listening", "thinking", "working",
         "flow", "speaking", "alert", "rest", "milestone"]

# 1100 px wide at quality 62. The shipped assets are the originals; this size is
# for a web page that must stay well under the 16 MB artifact ceiling.
WIDTH, QUALITY = 1100, 62


def main() -> None:
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "home-previews.built.html"
    page = SRC.read_text(encoding="utf-8")
    if MARKER not in page:
        raise SystemExit(f"{SRC.name} has no {MARKER} marker")

    lines = ["<script>",
             "/* The owner's eleven wallpapers, one per ambience mode, inlined by",
             "   build_home_previews.py. Originals: docs/design/assets/wallpapers/ */",
             "window.WP = {"]
    total = 0
    with tempfile.TemporaryDirectory() as td:
        for mode in MODES:
            src = next((WALLPAPERS / f"{mode}{ext}"
                        for ext in (".png", ".jpg", ".jpeg", ".avif", ".heic")
                        if (WALLPAPERS / f"{mode}{ext}").exists()), None)
            if src is None:
                print(f"  MISSING  {mode}")
                continue
            small = Path(td) / f"{mode}.jpg"
            subprocess.run(["sips", "-s", "format", "jpeg",
                            "-s", "formatOptions", str(QUALITY),
                            "-Z", str(WIDTH), str(src), "--out", str(small)],
                           check=True, capture_output=True)
            blob = small.read_bytes()
            total += len(blob)
            lines.append(f'  "{mode}": "data:image/jpeg;base64,'
                         f'{base64.b64encode(blob).decode()}",')
    lines += ["};", "</script>"]

    dst.write_text(page.replace(MARKER, "\n".join(lines)), encoding="utf-8")
    size = dst.stat().st_size
    print(f"wrote {dst.name}  {size:,} bytes  "
          f"({len(MODES)} wallpapers, {total/1024:.0f} KB before base64)")
    if size > 16 * 1024 * 1024:
        raise SystemExit("OVER THE 16 MB ARTIFACT CEILING")


if __name__ == "__main__":
    main()
