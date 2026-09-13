"""Research mode (§29): a room that remembers, and the card that controls it.

THE OWNER'S SPECIFICATION, 2026-09-12: *"the research mode is a little different,
connected to the side button but doesn't pop up a new window or dashboard, it just
puts there all the cards and windows necessary, has more than the windows and
cards the show up when just active on a new session that can be used on demand,
when i come back to an old research session the same open windows and cards from
last session should show up on that session, on a new session, default step shows
up, vesper and i can control all of those windows and cards just from a pop up
card right above the history card that is at the bottom left, here, the other
cards that exist on vesper's normal state should remain in the control card and
can be pulled up by me or vesper."*

IT OPENS NOTHING. Projects opens a surface; research POPULATES THE ONE ALREADY
THERE. Building it as a second dashboard is the single most likely way to get this
wrong, and the specification says so in its first clause.

TWO TIERS, AND THE SECOND IS WHY THE CONTROL CARD EXISTS. What appears on a new
session is the DEFAULT STEP. What is AVAILABLE is everything else -- including
every card from vesper's ordinary state, which is parked rather than lost. The
control card is the inventory, not a research-only widget.

A SESSION'S LAYOUT IS DURABLE, AND A RESTORED CARD IS CORROBORATED. Step 15b
solved this shape for windows across a restart and its rule holds here: a
restored thing is checked against the live world and **fail-closed on every
unreadable state**. A room that claims to be last week's room and is not is a
false reading, which is the thing this corpus refuses everywhere else.

BOTH PARTIES DRIVE IT. The owner said "vesper and i can control all of those
windows and cards" -- so arranging the room is an ordinary act for VESPER through
the same surface, not a human-only control.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STATE = Path.home() / "Library" / "Application Support" / "VESPER"
SESSIONS = STATE / "research"

# WHAT A NEW SESSION OPENS WITH. The owner called it "the default step", so it is
# a STEP rather than a layout: the thing a piece of research starts by doing.
DEFAULT_STEP = "question"

# THE CARDS THIS ROOM CAN HOLD. Vesper's ordinary cards are here too, deliberately
# -- "the other cards that exist on vesper's normal state should remain in the
# control card and can be pulled up". Nothing is lost by entering research.
ORDINARY_CARDS = ("commands", "explanations", "changes", "terminal", "history",
                  "metrics", "flags")
RESEARCH_CARDS = ("question", "sources", "notes", "findings", "canvas")
ALL_CARDS = RESEARCH_CARDS + ORDINARY_CARDS


def _path(session_id: str) -> Path:
    # ONE FILE PER SESSION, named by the id, so a torn write loses one session
    # rather than the index of all of them.
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:64]
    return SESSIONS / f"{safe or 'unnamed'}.json"


def default_layout() -> dict:
    """What a NEW session shows. Named, so nobody has to infer it."""
    return {"step": DEFAULT_STEP,
            "shown": [DEFAULT_STEP],
            "available": list(ALL_CARDS),
            "windows": []}


def save(session_id: str, layout: dict) -> tuple[bool, str]:
    """Record the room as it stands. Called by the owner AND by VESPER."""
    try:
        SESSIONS.mkdir(parents=True, exist_ok=True)
        shown = [c for c in (layout or {}).get("shown") or [] if c in ALL_CARDS]
        body = {
            "session_id": str(session_id),
            "step": str((layout or {}).get("step") or DEFAULT_STEP),
            "shown": shown,
            "windows": [w for w in (layout or {}).get("windows") or []
                        if isinstance(w, dict) and w.get("window_id")],
            "at_ms": int(time.time() * 1000),
        }
        p = _path(session_id)
        # A UNIQUE TEMP AND A RENAME. A half-written layout read back as a room
        # is worse than no layout: the owner would be told this IS last session.
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=1), encoding="utf-8")
        tmp.replace(p)
        return True, ""
    except OSError as e:
        return False, f"the session layout could not be written: {type(e).__name__}"


def restore(session_id: str, *, live_windows: list | None = None) -> dict:
    """The room a session left behind, corroborated, or the default with a reason.

    CORROBORATED AGAINST THE LIVE WORLD, like `CI-138`'s restored window stamp.
    A remembered window that is no longer open is DROPPED and counted, never
    offered -- and the count is reported so the owner is told the room came back
    smaller rather than discovering it.
    """
    p = _path(session_id)
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out = default_layout()
        out["why"] = "a new session, so the default step is what opens"
        out["restored"] = False
        return out
    except (OSError, json.JSONDecodeError) as e:
        # FAIL-CLOSED AND SAY SO. An unreadable layout is not an empty one.
        out = default_layout()
        out["why"] = (f"the saved layout could not be read "
                      f"({type(e).__name__}), so this opens as a new session "
                      f"rather than as a room that may not be the right one")
        out["restored"] = False
        return out

    live = {str(w.get("window_id")) for w in (live_windows or [])
            if isinstance(w, dict) and w.get("window_id")}
    kept, gone = [], 0
    for w in body.get("windows") or []:
        if not isinstance(w, dict):
            continue
        if live_windows is None or str(w.get("window_id")) in live:
            kept.append(w)
        else:
            gone += 1

    shown = [c for c in body.get("shown") or [] if c in ALL_CARDS]
    out = {
        "step": str(body.get("step") or DEFAULT_STEP),
        "shown": shown or [DEFAULT_STEP],
        "available": list(ALL_CARDS),
        "windows": kept,
        "restored": True,
        "why": "",
    }
    if gone:
        out["why"] = (f"{gone} window(s) from that session are no longer open "
                      f"and were dropped rather than shown as present")
    return out


def control_card(layout: dict | None = None) -> list:
    """The inventory the control card renders: every card, shown or parked.

    EVERY CARD, NOT THE RESEARCH ONES. The owner's last clause is the whole
    point: vesper's ordinary cards stay reachable from inside research, so
    entering the room costs nothing.
    """
    layout = layout or default_layout()
    shown = set(layout.get("shown") or [])
    rows = []
    for cid in ALL_CARDS:
        rows.append({
            "id": cid,
            "shown": cid in shown,
            "kind": "research" if cid in RESEARCH_CARDS else "ordinary",
            # WHO MAY PULL IT UP. Both, by the owner's own sentence -- recorded
            # as data so the surface cannot quietly make it a human-only control.
            "pullable_by": ["owner", "vesper"],
        })
    return rows


def sessions() -> list:
    """Every recorded research session, newest first, or an empty list."""
    try:
        files = sorted(SESSIONS.glob("*.json"))
    except OSError:
        return []
    out = []
    for f in files:
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A TORN SESSION IS NAMED, NOT SKIPPED. Silently dropping it would
            # make a damaged room look like one that never existed.
            out.append({"session_id": f.stem, "step": "", "at_ms": 0,
                        "unreadable": True})
            continue
        out.append({"session_id": str(b.get("session_id") or f.stem),
                    "step": str(b.get("step") or ""),
                    "shown": len(b.get("shown") or []),
                    "at_ms": int(b.get("at_ms") or 0),
                    "unreadable": False})
    out.sort(key=lambda r: r.get("at_ms") or 0, reverse=True)
    return out
