"""Reassemble the home architecture artifact from the two markdown files.

Same job as `build_artifact.py` one directory up, for a different surface: the
artifact is a RENDERING of the documents, never a second copy of them. Edit the
markdown; run this; republish. Nothing here holds content of its own.

    python3 docs/design/source/artifacts/build_home_doc.py out.html

Stdlib only.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parents[3]

from md2html import convert          # noqa: E402
from doc_css import CSS              # noqa: E402
from doc_body import BODY            # noqa: E402

HEAD = """<title>VESPER's Home</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Outfit:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Dancing+Script:wght@500&display=swap">
"""

def strip_h1(md: str) -> str:
    lines = md.split("\n")
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    return "\n".join(lines[i + 1:])

def nav_of(html_str: str, label: str) -> str:
    items = re.findall(
        r'<h2 id="([^"]+)">(?:<span class="num">([^<]*)</span>)?<span>(.*?)</span></h2>',
        html_str)
    out = []
    for sid, num, txt in items:
        clean = re.sub(r'<[^>]+>', '', txt)
        clean = re.sub(r'\s+—.*$', '', clean)
        out.append(f'<a href="#{sid}"><b>{num or "·"}</b><span>{clean}</span></a>')
    return f'<div class="navgroup"><h6>{label}</h6>' + "".join(out) + "</div>"

def main() -> None:
    dst = Path(sys.argv[1] if len(sys.argv) > 1 else "vesper-home.html")
    design = REPO / "docs" / "design"
    arch = convert(strip_h1((design / "HOME-ARCHITECTURE.md").read_text(encoding="utf-8")))
    cont = convert(strip_h1((design / "HOME-CONTENT.md").read_text(encoding="utf-8")))
    nav = nav_of(arch, "Architecture") + nav_of(cont, "What it carries")
    dst.write_text(
        HEAD + CSS + BODY.replace("@@NAV@@", nav)
                         .replace("@@ARCH@@", arch)
                         .replace("@@CONT@@", cont),
        encoding="utf-8")
    print(f"wrote {dst} ({dst.stat().st_size:,} bytes) "
          f"— {arch.count('<table>') + cont.count('<table>')} tables, "
          f"{nav.count('<a href')} sections")

if __name__ == "__main__":
    main()
