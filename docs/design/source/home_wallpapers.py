"""The owner's wallpapers, measured against the ambience they are supposed to carry.

WHY THIS EXISTS. `modes.json` derives each mode's accent from the LIGHT SOURCE in
a reference image -- the top 4% of pixels by brightness x chroma, because the
mean of a night photograph is just the night. The owner has now supplied eleven
wallpapers, one per mode, and they will sit BEHIND the interface those accents
are drawn on.

If a wallpaper's light source disagrees with its mode's recorded accent, the
adaptive-colour rule (`DESIGN-FOUNDATION.md` SS3) spends every frame fighting the
picture behind it. That is not a thing to notice in month two.

So this measures the wallpapers with the same method `modes2.py` used on the
references, and prints the disagreement in degrees. It does not fix anything and
it does not write `modes.json` -- promotion is a separate reviewed act, as it is
for every other contract here.

    python3 docs/design/source/home_wallpapers.py [<dir>]

Default dir is `WALLPAPER_DIR` below. Stdlib only: `sips` does the decode to a
small PNG (it ships with macOS), and `extract.py`'s hand-written PNG reader does
the rest, so nothing is installed to run this.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract import read_png, to_oklab, to_rgb          # noqa: E402

WALLPAPER_DIR = HERE.parents[1] / "design" / "assets" / "wallpapers"

# The eleven, in the order modes.json holds them.
MODES = ["Home", "Idle", "Watch", "Listening", "Thinking", "Working",
         "Flow", "Speaking", "Alert", "Rest", "Milestone"]

# The accent hue each mode's own entry in modes.json was derived at. Read from
# the file rather than restated, so this cannot drift from it.
def recorded() -> dict[str, dict]:
    data = json.loads((HERE / "modes.json").read_text(encoding="utf-8"))
    return {m["mode"]: m for m in data}


def hue_of(lab: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(lab[2], lab[1])) % 360


def dh(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def light_source(path: Path, tmp: Path) -> tuple[float, float, float, str]:
    """The same reading modes2.py takes: the top 4% by brightness x chroma."""
    small = tmp / (path.stem + ".png")
    subprocess.run(["sips", "-s", "format", "png", "-Z", "96",
                    str(path), "--out", str(small)],
                   check=True, capture_output=True)
    labs = [to_oklab(p) for p in read_png(str(small))]
    labs.sort(key=lambda l: -(l[0] * (1 + 3 * math.hypot(l[1], l[2]))))
    top = labs[:max(6, len(labs) * 4 // 100)]
    a = sum(l[1] for l in top) / len(top)
    b = sum(l[2] for l in top) / len(top)
    L = sum(l[0] for l in top) / len(top)
    return (hue_of((L, a, b)), math.hypot(a, b), L, to_rgb(L, a, b))


def ground(path: Path, tmp: Path) -> float:
    """Mean lightness of the whole frame -- decides whether a mode is light."""
    small = tmp / (path.stem + "_g.png")
    subprocess.run(["sips", "-s", "format", "png", "-Z", "64",
                    str(path), "--out", str(small)],
                   check=True, capture_output=True)
    labs = [to_oklab(p) for p in read_png(str(small))]
    return sum(l[0] for l in labs) / len(labs)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else WALLPAPER_DIR
    if not src.exists():
        raise SystemExit(f"no wallpaper directory at {src}")
    rec = recorded()

    print(f"wallpapers: {src}\n")
    print(f"{'mode':<11}{'recorded':>10}{'measured':>10}{'delta':>8}"
          f"{'C':>7}{'mean L':>8}  {'accent':<9} verdict")

    worst = 0.0
    rows = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for mode in MODES:
            hits = [p for p in src.iterdir()
                    if p.stem.lower() == mode.lower() and p.suffix.lower()
                    in (".png", ".jpg", ".jpeg", ".avif", ".heic", ".webp")]
            if not hits:
                print(f"{mode:<11}{'':>10}{'MISSING':>10}")
                rows.append((mode, None))
                continue
            p = hits[0]
            H, C, L, hexv = light_source(p, tmp)
            meanL = ground(p, tmp)
            r = rec[mode]
            d = dh(H, r["hue"])
            worst = max(worst, d)
            # TWO REASONS A GAP IS NOT A DEFECT, both already in the record.
            #
            # 1. A hue needs chroma to carry it. Alert measures 0.006 -- no hue
            #    signal at all -- which is precisely why modes.json marks it
            #    curated and takes ember for being legible on both grounds.
            # 2. A CURATED mode's accent deliberately does NOT follow the light
            #    source. Idle's brightest thing is the galaxy at ~295 degrees;
            #    the frame is about the one ember on the horizon, and solar was
            #    taken instead. Measuring that gap and calling it divergence
            #    reads the curation as an error, which inverts what happened.
            #
            # So only a MEASURED mode can diverge. This is the check refusing to
            # produce a false positive against its own record.
            weak = C < 0.02
            if weak:
                verdict = "no hue signal — curated, as recorded"
            elif r["prov"] == "curated":
                verdict = f"curated — accent is not the light source, by decision"
            elif d <= 30:
                verdict = "agrees"
            else:
                verdict = "DIVERGES"
            print(f"{mode:<11}{r['hue']:>9.0f}°{H:>9.0f}°{d:>7.0f}°"
                  f"{C:>7.3f}{meanL:>8.2f}  {r['accentName']:<9} {verdict}")
            rows.append((mode, {"H": H, "C": C, "meanL": meanL, "hex": hexv,
                                "recorded_hue": r["hue"], "delta": d,
                                "prov": r["prov"], "light": r["light"],
                                "file": p.name}))

    print()
    judged = [r for _, r in rows if r and r["C"] >= 0.02 and r["prov"] == "measured"]
    bad = [r for r in judged if r["delta"] > 30]
    total = len([r for _, r in rows if r])
    print(f"{total} wallpapers; {len(judged)} are MEASURED modes with a hue signal and "
          f"can be judged. {len(bad)} of those diverge by more than 30 degrees.")
    print("The rest are curated: modes.json records the accent as a decision rather "
          "than a reading, so there is nothing to reproduce.")

    # The other half of the check: a mode declared light must actually be light.
    print()
    for mode, r in rows:
        if not r:
            continue
        looks_light = r["meanL"] > 0.50
        if looks_light != r["light"]:
            print(f"  NOTE  {mode}: modes.json says light={r['light']}, "
                  f"the wallpaper's mean L is {r['meanL']:.2f}. "
                  f"{'Rest is already recorded as forced light against its mean.' if mode=='Rest' else 'Worth a look.'}")

    json.dump({m: r for m, r in rows if r},
              open(HERE / "wallpaper_check.json", "w"), indent=1)
    print(f"\nwrote {HERE.name}/wallpaper_check.json")


if __name__ == "__main__":
    main()
