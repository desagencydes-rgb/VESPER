"""Regenerate `refs/tiny/` so `extract.py` and `modes2.py` can run at all.

THE DEFECT THIS FIXES. `docs/design/README.md` says the six derivations are
runnable and "print what they found". Two of them could not run: both read
`refs/tiny/{key}.png`, that directory was never committed, and nothing in the
tree generated it. A derivation nobody can re-run is an assertion with a
footnote, which is the thing this corpus exists to refuse.

WHY -Z 64, AND WHY THE SIZE TURNS OUT NOT TO MATTER MUCH. The original size was
not recorded. Sweeping 48..512 px and comparing modes2.py's light-source hue
against the hue `modes.json` already records: SEVEN of the eight measured modes
reproduce within 0-5 degrees AT EVERY SIZE. The reading is stable under
resampling, which is a better property than any one size being correct.

THE EIGHTH IS `arch` / Milestone, AND IT DOES NOT CLOSE. Recorded 330 degrees;
measured 347-353 at every size, a ~20 degree gap. The palette pick is unaffected
-- 330 and 350 both land on blush, which is what modes.json carries -- so
nothing downstream moves. But the recorded number cannot be reproduced from the
committed reference, and the honest disposition is to say so here rather than
quietly overwrite it. Either the original tiny was cropped differently or it came
from a different frame. Recorded, not resolved.

WHAT RUNNING THE DERIVATIONS AFTERWARDS WILL DO, AND WHY THAT DIFF IS NOT A
CORRECTION. `extract.py` writes `palettes.json` and `modes2.py` writes
`lightsrc.json`, both committed. Re-running them against tiny references this
script RECONSTRUCTED produces a diff -- 304 changed lines when it was tried on
2026-08-22. That diff is the REPRODUCTION GAP between the original run and a
reconstruction, not a finding about the palette, and it was reverted rather than
committed. `modes.json`, which the whole design reads, is untouched by either.

AND `final.py` REWRITES `modes.json`, WHICH IS THE ONE THAT MATTERS. It is the
file every surface reads for its ambience. Running the derivation chain end to
end on reconstructed tiny references moved its grounds by a few units and its
chroma by 0.001 -- small, invisible in a preview, and a silent redefinition of
the design system. It was reverted.

So: `python3 final.py` is not a safe thing to run casually. The chain
tiny -> extract -> modes2 -> final regenerates four committed files from inputs
that are a reconstruction, and only a decision should let any of them land.

Commit a regenerated `palettes.json`, `lightsrc.json` or `modes.json` only as a
deliberate act with the gap stated, never as a side effect of having run a
script. An invariant candidate is sitting here: the derivation outputs are
unchanged unless the commit says why.

    python3 docs/design/source/tiny.py

Idempotent. Uses `sips`, which ships with macOS, so nothing is installed.
`refs/tiny/` is git-ignored for the same reason `face.bin` is: derived, not
authored.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFS = HERE / "refs"
TINY = REFS / "tiny"
SIZE = 64

KEYS = ["hall", "ember", "light", "vein", "violet", "gold", "wave",
        "sepia", "matte", "leaf", "arch", "face"]


def main() -> None:
    if not REFS.is_dir():
        raise SystemExit(f"no reference images at {REFS}")
    TINY.mkdir(exist_ok=True)
    made = 0
    for key in KEYS:
        src = next((REFS / f"{key}{ext}" for ext in (".jpg", ".jpeg", ".png")
                    if (REFS / f"{key}{ext}").exists()), None)
        if src is None:
            print(f"  MISSING  {key}")
            continue
        dst = TINY / f"{key}.png"
        subprocess.run(["sips", "-s", "format", "png", "-Z", str(SIZE),
                        str(src), "--out", str(dst)],
                       check=True, capture_output=True)
        made += 1
    print(f"wrote {made} tiny references at -Z {SIZE} into {TINY.relative_to(HERE.parents[2])}")
    print("extract.py and modes2.py can now run. Both must be run from this directory.")


if __name__ == "__main__":
    main()
