"""Build the island's projection from things that are actually true, and write it out.

This is the file-based form of the transport in ISLAND-ARCHITECTURE.md §7.4 -- a
socket comes later; the shape of what crosses it does not change.

WHAT THIS TOOL IS FOR IS REFUSING TO FILL COLUMNS. The owner's reference draws six
status columns and every one of them has a plausible value. Three of the six have
no producer on this machine today: the autonomy loop is not running, there is no
policy decision point to hold pending approvals, and nothing schedules ambience.
So this writes THREE columns, not six, and the island renders three. An empty
shoulder is the honest render and `core/projection.py` makes the alternative
unconstructible.

Stdlib only, per the convention for tools/.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.hlc import HLC                                    # noqa: E402
from core.projection import ISLAND_COLUMNS, Projection, Reading   # noqa: E402

CACHE = REPO / ".island-stress-cache.json"


def now_hlc() -> HLC:
    return HLC(physical_ms=int(time.time() * 1000), logical=0, node_id="macbook")


def fabric_summary() -> Reading:
    """Segment count from the contract. NOT a node count: nothing on this machine
    enumerates enrolled nodes yet, and '3 nodes' would be a number I made up."""
    path = REPO / "contracts" / "policy" / "network_fabric.toml"
    if not path.exists():
        return Reading.unavailable("fabric.summary", "fabric", "no network_fabric.toml")
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    n = len(doc.get("segment", {}) or {})
    if n == 0:
        return Reading.unavailable("fabric.summary", "fabric", "contract declares no segments")
    return Reading(key="fabric.summary", source="contracts/policy/network_fabric.toml",
                   value=f"{n} segments", observed_at=now_hlc())
    # Temperature is deliberately absent. MEMORY.md records that this platform's
    # metrics need translation and are not the ones a Linux node reports; the
    # reference's "41 C" is a number the host does not expose.


def placement_stress(measure: bool) -> Reading:
    """The real assertion count, with its age. `320k` in the reference came from a
    stale line in CLAUDE.md; the runner says 160,000. A measurement is what the
    instrument reported, when it reported it."""
    if measure:
        try:
            out = subprocess.run([sys.executable, str(REPO / "verification" / "stress_placement.py")],
                                 capture_output=True, text=True, cwd=REPO, timeout=300).stdout
        except Exception as exc:                             # noqa: BLE001
            return Reading.unavailable("verification.placement_stress", "verification",
                                       f"runner failed: {exc!r}")
        m = re.search(r"=\s*([\d,]+)\s+assertions", out)
        if not m or "PASS" not in out:
            return Reading.unavailable("verification.placement_stress", "verification",
                                       "runner produced no assertion count, or did not pass")
        CACHE.write_text(json.dumps({"assertions": m.group(1), "at_ms": int(time.time() * 1000)}))
    if not CACHE.exists():
        return Reading.unavailable("verification.placement_stress", "verification",
                                   "not run on this machine -- pass --measure")
    c = json.loads(CACHE.read_text())
    return Reading(key="verification.placement_stress", source="verification/stress_placement.py",
                   value=f"{c['assertions']} assertions",
                   observed_at=HLC(physical_ms=c["at_ms"], logical=0, node_id="macbook"),
                   # A stress result older than a day is not current truth about
                   # this tree; it expires rather than going quietly stale.
                   ttl_ms=24 * 60 * 60 * 1000)


def today() -> Reading:
    d = datetime.now()
    return Reading(key="day.agenda", source="host clock",
                   value=d.strftime("%a %-d"), observed_at=now_hlc())


def build(measure: bool) -> Projection:
    v = now_hlc()
    readings = {r.key: r for r in (
        fabric_summary(),
        placement_stress(measure),
        today(),
        # The three the reference draws that have no producer here. Written as
        # explicit unavailables rather than omitted from the dict, so `--explain`
        # can say WHY a column is missing instead of leaving a silent gap.
        Reading.unavailable("autonomy.state", "core/autonomy.py",
                            "autonomy loop is not running"),
        Reading.unavailable("authorize.pending", "core/authorize.py",
                            "no policy decision point running to hold pending approvals"),
        Reading.unavailable("scene.next_ambience", "core/scene.py",
                            "nothing schedules ambience transitions yet"),
    )}
    return Projection(version=v, readings=readings)


LABELS = {
    "fabric.summary": "Fabric", "verification.placement_stress": "Verified",
    "day.agenda": "Today", "autonomy.state": "Thinking",
    "authorize.pending": "Approvals", "scene.next_ambience": "Ambience",
}


def main() -> int:
    measure = "--measure" in sys.argv
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else Path("/tmp/vesper-island.json")
    proj = build(measure)

    scene = proj.to_scene("island", columns=ISLAND_COLUMNS)
    cols = [{"label": LABELS.get(e.element_id, e.element_id),
             "value": str(e.content["value"])} for e in scene.elements]
    out.write_text(json.dumps({"version": proj.version.to_dict(), "columns": cols}, indent=1))

    print(f"{len(cols)} of {len(ISLAND_COLUMNS)} columns have a producer -> {out}")
    for c in cols:
        print(f"  {c['label']:<10} {c['value']}")
    if "--explain" in sys.argv:
        print("\nabsent, and why:")
        for k in ISLAND_COLUMNS:
            r = proj.readings.get(k)
            if r is not None and not r.at(proj.version).known:
                print(f"  {LABELS.get(k, k):<10} {r.at(proj.version).unavailable_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
