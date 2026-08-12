"""
vesper_ids.py -- Authoritative identifier extraction from the locked COC.

The COC (docs/COC/VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.1.md) is the single
source of truth for WHICH identifiers exist. No other artifact may invent an
SR/DR/RB/IC/A/T/P identifier, and no artifact may silently drop one.

This module is deliberately dependency-free (stdlib only) so that CI can run it
on any node without an install step.

Authority: COC v1.1 Part II (SR), Part III (DR), Part V (Architecture sections),
Part VIII (RB), Part IX (T), Part X (A), Part XII (IC), Part IV (P).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COC_PATH = REPO_ROOT / "docs" / "COC" / "VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.1.md"
# v1.2 is ADDITIVE: v1.1 is never edited, so the authoritative identifier set is
# the union. Issued under Part XIV.6 with recorded owner approval.
COC_ADDITIVE = REPO_ROOT / "docs" / "COC" / "VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md"

# `### SR-001 --- Some title {#anchor}`
_ITEM_RE = re.compile(
    r"^#{2,4}\s+(?P<id>(?:SR|DR|RB|IC|A|T|P)-\d{3})\s*[-–—]{1,3}\s*(?P<title>.*?)\s*(?:\{#.*\})?\s*$"
)
# `## Part V --- 3. Persistent Vesper Runtime {#anchor}`
_ARCH_RE = re.compile(
    r"^##\s+Part\s+V\s*-{1,3}\s*(?P<num>\d{1,2})\.\s*(?P<title>.*?)\s*(?:\{#.*\})?\s*$"
)
# `## Part XI --- Source traceability matrix`
_PART_RE = re.compile(r"^##\s+Part\s+(?P<num>[IVX]+)\s*-{1,3}\s*(?P<title>.*?)\s*(?:\{#.*\})?\s*$")


@dataclass
class CocIndex:
    """Every identifier the locked COC defines, with its declared title."""

    sr: dict[str, str] = field(default_factory=dict)
    dr: dict[str, str] = field(default_factory=dict)
    rb: dict[str, str] = field(default_factory=dict)
    ic: dict[str, str] = field(default_factory=dict)
    a: dict[str, str] = field(default_factory=dict)
    t: dict[str, str] = field(default_factory=dict)
    p: dict[str, str] = field(default_factory=dict)
    arch: dict[str, str] = field(default_factory=dict)  # "ARCH-03" -> title

    def bucket(self, prefix: str) -> dict[str, str]:
        return {
            "SR": self.sr,
            "DR": self.dr,
            "RB": self.rb,
            "IC": self.ic,
            "A": self.a,
            "T": self.t,
            "P": self.p,
            "ARCH": self.arch,
        }[prefix]

    def all_ids(self) -> set[str]:
        out: set[str] = set()
        for prefix in ("SR", "DR", "RB", "IC", "A", "T", "P", "ARCH"):
            out |= set(self.bucket(prefix))
        return out

    def summary(self) -> str:
        return (
            f"SR={len(self.sr)} DR={len(self.dr)} ARCH={len(self.arch)} "
            f"RB={len(self.rb)} IC={len(self.ic)} A={len(self.a)} "
            f"T={len(self.t)} P={len(self.p)}"
        )


def parse_coc(path: Path = COC_PATH, additive: Path | None = COC_ADDITIVE) -> CocIndex:
    if not path.is_file():
        raise FileNotFoundError(f"Locked COC not found at {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if additive is not None and additive.is_file():
        text += "\n" + additive.read_text(encoding="utf-8", errors="replace")
    idx = CocIndex()
    for raw in text.splitlines():
        line = raw.rstrip()

        m = _ARCH_RE.match(line)
        if m:
            arch_id = f"ARCH-{int(m.group('num')):02d}"
            idx.arch[arch_id] = m.group("title").strip()
            continue

        m = _ITEM_RE.match(line)
        if m:
            ident = m.group("id")
            prefix = ident.split("-")[0]
            title = m.group("title").strip().rstrip(".")
            # Do not let a later duplicate heading silently overwrite the first.
            bucket = idx.bucket(prefix)
            bucket.setdefault(ident, title)
    return idx


def parse_parts(path: Path = COC_PATH) -> dict[str, str]:
    """Roman-numeral COC parts, used by the source-immutability check."""
    parts: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _PART_RE.match(raw.rstrip())
        if m:
            parts[m.group("num")] = m.group("title").strip()
    return parts


def main() -> int:
    idx = parse_coc()
    print(f"COC index: {idx.summary()}")
    for prefix in ("SR", "DR", "ARCH", "RB", "IC", "A", "T", "P"):
        bucket = idx.bucket(prefix)
        print(f"\n[{prefix}] {len(bucket)}")
        for k, v in bucket.items():
            print(f"  {k}  {v[:96]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
