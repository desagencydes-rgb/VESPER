"""The projects and research boards: the windows and cards the owner chose, and
what can be done with each of them.

THE OWNER, 2026-09-13: *"project dashboard in full with windows, i said windows
and cards should appear there right? with full management i choose from a pop
up list or something, not just generic cards that are not working."* So a board
is a CHOSEN SET -- windows picked from the live inventory and cards picked from
the panels VESPER has -- kept in `boards.json` beside VESPER's state, published
with the live status of each choice, and offered with the acts that manage it.

WHAT "MANAGE" IS HERE. Every window action goes through the ordinary typed path
(`act`): "bring the <app> window <id> to your desktop", "close window <id>". It
meets intent, authorisation, the ladder and the flag bar like a sentence the
owner typed, because it IS one. Rule 31 (owner, 2026-09-13): VESPER manages its
own windows always and the owner's on demand -- and a button the owner pressed
is the demand. Choosing what is ON the board is the owner's own record and is
written directly (`board.*` controls), like a preference.

THE INVENTORY IS THE LIVE ONE. The picker lists what the app binary's own
`--windows-list` mode reports right now, with the provenance VESPER recorded for
each; a chosen window that has since closed is shown as gone, never dropped
silently (`core/research_room.restore` applies the same rule to a room).
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from typing import Any

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
PATH = STATE / "boards.json"
KINDS = ("projects", "research")
_LOCK = threading.RLock()


class BoardRefused(ValueError):
    pass


def _read(path: pathlib.Path | None = None) -> dict:
    p = path or PATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (OSError, json.JSONDecodeError):
        d = {}
    for k in KINDS:
        d.setdefault(k, {})
        d[k].setdefault("windows", [])
        d[k].setdefault("cards", [])
    d["research"].setdefault("session", "")
    return d


def _write(d: dict, path: pathlib.Path | None = None) -> None:
    p = path or PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(p)


def _kind(k: Any) -> str:
    if k not in KINDS:
        raise BoardRefused(f"board {k!r} is not one of {KINDS}")
    return str(k)


def add_window(kind: str, window: dict, *, path: pathlib.Path | None = None) -> dict:
    k = _kind(kind)
    wid = str((window or {}).get("window_id") or "").strip()
    if not wid:
        raise BoardRefused("a window needs its window_id")
    with _LOCK:
        d = _read(path)
        rows = [w for w in d[k]["windows"] if str(w.get("window_id")) != wid]
        rows.append({"window_id": wid, "app_label": str(window.get("app_label") or "?"),
                     "pid": str(window.get("pid") or ""), "added_ms": int(time.time() * 1000)})
        d[k]["windows"] = rows[-24:]
        _write(d, path)
    return {"kind": k, "windows": len(rows)}


def remove_window(kind: str, window_id: str, *, path: pathlib.Path | None = None) -> dict:
    k = _kind(kind)
    with _LOCK:
        d = _read(path)
        before = len(d[k]["windows"])
        d[k]["windows"] = [w for w in d[k]["windows"] if str(w.get("window_id")) != str(window_id)]
        _write(d, path)
    return {"kind": k, "removed": before - len(d[k]["windows"])}


def add_card(kind: str, card_id: str, *, path: pathlib.Path | None = None) -> dict:
    k = _kind(kind)
    cid = str(card_id or "").strip()
    if cid not in {c["id"] for c in available_cards(k)}:
        raise BoardRefused(f"{cid!r} is not a card the {k} board can hold")
    with _LOCK:
        d = _read(path)
        if cid not in d[k]["cards"]:
            d[k]["cards"].append(cid)
        _write(d, path)
    return {"kind": k, "cards": len(d[k]["cards"])}


def remove_card(kind: str, card_id: str, *, path: pathlib.Path | None = None) -> dict:
    k = _kind(kind)
    with _LOCK:
        d = _read(path)
        d[k]["cards"] = [c for c in d[k]["cards"] if c != card_id]
        _write(d, path)
    return {"kind": k, "cards": len(d[k]["cards"])}


def set_research_session(session_id: str, *, path: pathlib.Path | None = None) -> dict:
    sid = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_ ")[:64].strip()
    if not sid:
        raise BoardRefused("a research session needs a name")
    from core import research_room as RR
    with _LOCK:
        d = _read(path)
        d["research"]["session"] = sid
        _write(d, path)
    ok, why = RR.save(sid, RR.restore(sid))
    return {"session": sid, "saved": ok, "why": why}


def available_cards(kind: str) -> list:
    k = _kind(kind)
    if k == "projects":
        try:
            from core import project_dashboard as PD
            from core import places as PL
            root = next((r["path"] for r in PL.places() if r.get("name") == "the project" and r.get("path")), None)
            return [{"id": p["id"], "name": p["name"], "what": p.get("what", "")}
                    for p in PD.panels(pathlib.Path(root) if root else None)]
        except Exception:                                 # noqa: BLE001
            return []
    from core import research_room as RR
    return [{"id": c, "name": c.replace("_", " "), "what": "research card" if c in RR.RESEARCH_CARDS else "one of VESPER's ordinary cards"}
            for c in RR.ALL_CARDS]


def _inventory() -> tuple[list, str]:
    """Live windows, through the app's own mode. Empty with a reason on failure."""
    try:
        from core import capabilities as caps
        wins, desktop = caps._inventory()
        return ([{"window_id": w.window_id, "pid": w.pid, "app_label": w.app_label,
                  "provenance": w.provenance, **{k: v for k, v in w.meta.items() if k == "on_active_desktop"}}
                 for w in wins], "")
    except Exception as exc:                              # noqa: BLE001
        return [], f"{type(exc).__name__}: {str(exc)[:120]}"


def board(kind: str, *, path: pathlib.Path | None = None, inventory: list | None = None,
          inventory_why: str = "") -> dict:
    """One board, published: chosen windows with live status, chosen cards,
    what the picker may add, and the acts that manage each choice."""
    k = _kind(kind)
    d = _read(path)[k]
    if inventory is None:
        inventory, inventory_why = _inventory()
    live = {str(w["window_id"]): w for w in inventory}
    chosen_windows = []
    for w in d["windows"]:
        wid = str(w.get("window_id"))
        lw = live.get(wid)
        status = ("open" + (", on the showing Desktop" if lw and lw.get("on_active_desktop") else ", elsewhere")) if lw else "gone (closed since it was chosen)"
        prov = (lw or {}).get("provenance", "unknown")
        acts = []
        if lw:
            label = f"{w.get('app_label', '?')} window {wid}"
            acts.append({"id": f"bring-{wid}", "label": "Bring here",
                         "control": {"action": "act", "args": {"text": f"move the {label} to your desktop"}}})
            if prov == "vesper_opened":
                acts.append({"id": f"close-{wid}", "label": "Close",
                             "control": {"action": "act", "args": {"text": f"close the {label}"}}})
            else:
                acts.append({"id": f"close-{wid}", "label": "Close (yours, on your demand)",
                             "control": {"action": "act", "args": {"text": f"close the {label}; i am asking you to"}}})
        acts.append({"id": f"remove-{wid}", "label": "Remove from board",
                     "control": {"action": "board.remove_window", "args": {"kind": k, "window_id": wid}}})
        chosen_windows.append({**w, "status": status, "provenance": prov, "actions": acts})
    chosen_ids = {str(w.get("window_id")) for w in d["windows"]}
    available = [w for w in inventory if str(w["window_id"]) not in chosen_ids]
    cards_avail = available_cards(k)
    chosen_cards = [{"id": c, "name": next((x["name"] for x in cards_avail if x["id"] == c), c),
                     "actions": [{"id": f"remove-card-{c}", "label": "Remove",
                                  "control": {"action": "board.remove_card", "args": {"kind": k, "card_id": c}}}]}
                    for c in d["cards"]]
    out: dict = {
        "kind": k,
        "chosen_windows": chosen_windows,
        "available_windows": available,
        "inventory_why": inventory_why,
        "chosen_cards": chosen_cards,
        "available_cards": [c for c in cards_avail if c["id"] not in d["cards"]],
        "open_actions": [
            {"id": f"open-{w}", "label": f"Open a {w} here",
             "control": {"action": "act", "args": {"text": f"open a new {w} window here"}}}
            for w in ("browser", "editor", "terminal", "viewer")],
        "add_window_control": {"action": "board.add_window", "args": {"kind": k}},
        "add_card_control": {"action": "board.add_card", "args": {"kind": k}},
    }
    # THE RUNS ON THIS BOARD (core/workflows.py): what was asked, each step's
    # status and where its files are, while it runs and after.
    try:
        from core import workflows as WF
        out["workflows"] = WF.runs("research" if k == "research" else "project")
    except Exception:                                     # noqa: BLE001
        out["workflows"] = []
    out["start_control"] = ({"action": "workflow.research", "label": "Research this question",
                             "placeholder": "a question worth a study"} if k == "research"
                            else {"action": "workflow.project", "label": "Work on this goal",
                                  "placeholder": "what to build, in one sentence"})
    if k == "research":
        from core import research_room as RR
        out["session"] = d.get("session") or ""
        out["sessions"] = RR.sessions()
        out["session_actions"] = ([{"id": "open-room", "label": f"Open the room '{out['session']}'",
                                    "control": {"action": "act", "args": {"text": f"open the research room for {out['session']}"}}}]
                                  if out["session"] else [])
        out["new_session_control"] = {"action": "board.research_session", "args": {}}
    return out


def boards(path: pathlib.Path | None = None) -> dict:
    inv, why = _inventory()
    return {k: board(k, path=path, inventory=inv, inventory_why=why) for k in KINDS}
