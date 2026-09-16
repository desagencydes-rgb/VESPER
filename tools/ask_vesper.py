"""Say something to the RUNNING VESPER and read back what it actually did.

WHY THIS EXISTS. `tools/ops/vesper_runtime.py --say` writes one line into the
utterance file -- and it cannot be run while VESPER is running, because
`_only_one_runtime()` fires first and refuses the second process. So the one
gesture a session needs most often, "ask it something and see what happened", was
reachable only by stopping the thing being asked.

WHAT IT PROVES THAT A DIRECT CALL DOES NOT. A capability called from Python skips
intent, authorisation, the level ladder, the executor and `observe()`. A sentence
does not. The owner, 2026-09-15: *"run some big multi steps checks to verify it
works end to end, ask vesper stuff that makes it go through multiple questions in
one go."* That is this file's whole job -- and it reads the world back afterwards
rather than reporting that the line was written, which is the difference between
an instrument and a receipt.

    python3.13 tools/ask_vesper.py "show me core/showcase.py at line 120"
    python3.13 tools/ask_vesper.py --wait 90 "..."      # a longer turn
    python3.13 tools/ask_vesper.py --watch              # just read the state
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
OUTBOX = STATE / "say.jsonl"
HOME = STATE / "home.json"


def _home() -> dict:
    try:
        return json.loads(HOME.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def transcript() -> list:
    return [r for r in (_home().get("transcript") or []) if isinstance(r, dict)]


def say(text: str) -> None:
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    with OUTBOX.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"text": text, "source": "typed", "final": True}) + "\n")


def surfaces() -> dict:
    """What the showcase and the demonstration say about themselves, right now."""
    from core import demonstration as D
    from core import showcase as SC

    s = SC.said()
    return {"open": bool(s.get("open")), "visible": bool(s.get("visible")),
            "on_vespers_desktop": bool(s.get("on_vespers_desktop")),
            "revision": s.get("revision"), "panes": list(s.get("panes_drawn") or []),
            "marks": s.get("marks_drawn"), "errors": list(s.get("errors") or []),
            "scene": SC.describe(), "demonstration": D.state().get("line")}


def ask(text: str, *, wait_s: float = 60.0, quiet: bool = False) -> dict:
    """Say it, then wait for VESPER to answer, then read the world back.

    THE WAIT IS FOR A NEW ROW IN THE TRANSCRIPT, not for a fixed number of
    seconds. A sleep long enough for the slowest turn is a test that takes that
    long every time, and one long enough for the fastest is a test that reports
    silence as a failure.
    """
    before = len(transcript())
    say(text)
    deadline = time.monotonic() + wait_s
    said: list = []
    while time.monotonic() < deadline:
        rows = transcript()
        if len(rows) > before:
            said = rows[before:]
            # A turn can produce several rows. Wait a moment past the first for
            # the rest rather than reporting half an answer.
            time.sleep(2.5)
            said = transcript()[before:]
            break
        time.sleep(0.4)
    out = {"asked": text, "said": said, "answered": bool(said), **surfaces()}
    if not quiet:
        print(f"\n> {text}")
        if not said:
            print(f"  (nothing came back within {wait_s:g}s)")
        for row in said:
            who = str(row.get("who") or "?")
            body = str(row.get("text") or "").replace("\n", " ")
            print(f"  {who:6} {body[:300]}")
        print(f"  showcase: open={out['open']} visible={out['visible']} "
              f"on-vespers-desktop={out['on_vespers_desktop']} "
              f"rev={out['revision']} panes={out['panes']} marks={out['marks']}")
        if out["errors"]:
            print(f"  page errors: {out['errors']}")
        print(f"  scene: {out['scene']}")
        if out["demonstration"] and "nothing" not in str(out["demonstration"]):
            print(f"  demonstration: {out['demonstration']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="what to say to VESPER")
    ap.add_argument("--wait", type=float, default=60.0, help="seconds to wait for an answer")
    ap.add_argument("--watch", action="store_true", help="read the surfaces and exit")
    args = ap.parse_args()
    if args.watch or not args.text:
        for k, v in surfaces().items():
            print(f"  {k:20} {v}")
        return 0
    got = ask(" ".join(args.text), wait_s=args.wait)
    return 0 if got["answered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
