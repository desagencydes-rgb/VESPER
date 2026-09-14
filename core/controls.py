"""What a button on the home may ask VESPER to do, and what happens when it does.

THE OWNER, 2026-09-13: *"where the fuck is management???"* Every surface showed
readings and none of them could change anything. This is the seam that turns a
gesture on the home into an act: the chrome posts `{action, args}` through the
Swift host into `control.jsonl`, the runtime drains it here, and each action is
applied by a function that is registered by NAME with the kind of thing it is.

THREE KINDS, AND THE KIND DECIDES WHO APPLIES IT.

  preference  -- the owner's own settings (`core/preferences.py`). Applied here,
                 directly: the gesture is the owner's and the value is bounded
                 by the schema.
  governed    -- a value in a governed contract. NEVER applied here. The runtime
                 is a subject of its own authorisation (INV-SELF-1) and may not
                 write a governed file; it records the proposal and the host
                 puts a confirmation in front of the owner naming the exact
                 file, key and value, and the HOST -- the owner's own process,
                 on the owner's own click -- makes the edit. The record here is
                 what makes that a reviewed act rather than a shortcut.
  act         -- something VESPER does to the machine: open, move, close, run.
                 Routed through the SAME path a typed request takes, so it
                 traverses intent, authorisation, the ladder and the flag bar
                 like any other (INV-AUTH-1: no second door into acting).

EVERY OUTCOME IS RECORDED, applied or refused, with the reason. A button that
does nothing and says nothing is the failure the owner reported.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from core import preferences as P

PREFERENCE, GOVERNED, ACT = "preference", "governed", "act"


class ControlRefused(ValueError):
    pass


def _set_preference(args: dict, ctx: dict) -> dict:
    key = str(args.get("key") or "")
    if "value" not in args:
        raise ControlRefused("preference.set needs a value")
    v = P.write(key, args["value"], principal="owner", source="home",
                bus=ctx.get("bus"), path=ctx.get("preferences_path"))
    return {"key": key, "value": v}


def _propose_governed(args: dict, ctx: dict) -> dict:
    """Record what the owner asked for. The host applies it after confirming."""
    for k in ("file", "key", "value"):
        if k not in args:
            raise ControlRefused(f"governed.propose needs {k}")
    f = str(args["file"])
    if not f.startswith("contracts/policy/") or "/../" in f or f.endswith("/"):
        raise ControlRefused(f"{f!r} is not a governed policy file")
    return {"file": f, "key": str(args["key"]), "value": args["value"],
            "applied_by": "the host, after the owner confirms the exact edit",
            "note": ("the runtime does not write governed files (INV-SELF-1); "
                     "this records the owner's request")}


def _act(args: dict, ctx: dict) -> dict:
    """Queue the request as if the owner had typed it."""
    text = str(args.get("text") or "").strip()
    if not text:
        raise ControlRefused("act needs the sentence to run")
    outbox = ctx.get("outbox")
    if outbox is None:
        raise ControlRefused("no outbox to queue into")
    with open(outbox, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"text": text, "source": "typed", "final": True,
                             "via": "home-control",
                             "at_ms": int(time.time() * 1000)}) + "\n")
    return {"queued": text}


PERMISSION, EXPORT, HOST = "permission", "export", "host"


def _set_permission(args: dict, ctx: dict) -> dict:
    """The standing permission mode. A NAMED principal, and the click is one."""
    from core import permission_mode as PM
    mode = str(args.get("mode") or "")
    try:
        PM.write(mode, principal="owner", bus=ctx.get("bus"),
                 now_ms=int(time.time() * 1000), path=ctx.get("permission_path"))
    except PM.ModeRefused as exc:
        raise ControlRefused(str(exc)) from None
    return {"mode": mode}


def _export_memory(args: dict, ctx: dict) -> dict:
    """Facts and entities out of the L2 store, as JSON on the owner's Desktop.
    Ids and facts, never the transcript (`map-navigates-and-never-carries-content`)."""
    import pathlib
    import sqlite3
    src = pathlib.Path(ctx.get("l2_path") or (pathlib.Path.home() / "Library" / "Application Support" / "VESPER" / "l2.db"))
    if not src.exists():
        raise ControlRefused("there is no memory store to export yet")
    dest_dir = pathlib.Path(ctx.get("export_dir") or (pathlib.Path.home() / "Desktop"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = {"exported_at_ms": int(time.time() * 1000), "tables": {}}
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        for t in ("entity", "fact", "edge"):
            try:
                cur = con.execute(f"SELECT * FROM {t}")
                cols = [c[0] for c in cur.description]
                out["tables"][t] = [dict(zip(cols, r)) for r in cur.fetchall()]
            except sqlite3.Error as exc:
                out["tables"][t] = {"error": str(exc)}
    finally:
        con.close()
    dest = dest_dir / time.strftime("VESPER-memory-%Y%m%d-%H%M%S.json")
    dest.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return {"path": str(dest),
            "counts": {t: (len(v) if isinstance(v, list) else 0) for t, v in out["tables"].items()}}


def _host_done(args: dict, ctx: dict) -> dict:
    """The host did something itself (a stop, a pane, a revoke) and says so here
    so the record is on the bus with everything else. Nothing is applied."""
    return {"what": str(args.get("what") or ""), "ok": bool(args.get("ok", True)),
            "detail": str(args.get("detail") or "")[:300]}


BOARD = "board"


def _board(fn_name: str):
    """The owner's own record of what is on a board: written directly, like a
    preference, and refused rather than guessed when the argument is not one
    the board can hold."""
    def run(args: dict, ctx: dict) -> dict:
        from core import boards as B
        path = ctx.get("boards_path")
        try:
            if fn_name == "add_window":
                return B.add_window(args.get("kind"), args.get("window") or args, path=path)
            if fn_name == "remove_window":
                return B.remove_window(args.get("kind"), str(args.get("window_id") or ""), path=path)
            if fn_name == "add_card":
                return B.add_card(args.get("kind"), str(args.get("card_id") or ""), path=path)
            if fn_name == "remove_card":
                return B.remove_card(args.get("kind"), str(args.get("card_id") or ""), path=path)
            if fn_name == "research_session":
                return B.set_research_session(str(args.get("session") or ""), path=path)
        except B.BoardRefused as exc:
            raise ControlRefused(str(exc)) from None
        raise ControlRefused(f"no board operation {fn_name!r}")
    return run


WORKFLOW = "workflow"


def _workflow(kind: str):
    """Start a research or project run. The actor and the runner come from the
    runtime through `ctx`; a workflow never has a command or an account of its
    own. Runs in the background: the pump must not wait minutes for an agent."""
    def run(args: dict, ctx: dict) -> dict:
        from core import workflows as W
        title = str(args.get("question") or args.get("goal") or args.get("title") or "")
        actor = ctx.get("actor")
        runner = ctx.get("runner") or getattr(actor, "_runner", None)
        act = (lambda text: actor.maybe_act(text)) if actor is not None else ctx.get("act")
        try:
            return W.start(kind, title, runner=runner, act=act, bus=ctx.get("bus"),
                           workdir=ctx.get("workdir"), status_path=ctx.get("workflows_path"),
                           background=ctx.get("background", True),
                           config_dir=ctx.get("config_dir"), binary=ctx.get("binary"))
        except W.WorkflowRefused as exc:
            raise ControlRefused(str(exc)) from None
    return run


REGISTRY: dict[str, tuple[str, Callable[[dict, dict], dict]]] = {
    "workflow.research": (WORKFLOW, _workflow("research")),
    "workflow.project": (WORKFLOW, _workflow("project")),
    "board.add_window": (BOARD, _board("add_window")),
    "board.remove_window": (BOARD, _board("remove_window")),
    "board.add_card": (BOARD, _board("add_card")),
    "board.remove_card": (BOARD, _board("remove_card")),
    "board.research_session": (BOARD, _board("research_session")),
    "preference.set": (PREFERENCE, _set_preference),
    "permission.set": (PERMISSION, _set_permission),
    "governed.propose": (GOVERNED, _propose_governed),
    "memory.export": (EXPORT, _export_memory),
    "act": (ACT, _act),
    "host.done": (HOST, _host_done),
}


def apply(control: dict, *, ctx: dict | None = None) -> dict:
    """Apply one control record. Never raises: the outcome is the return value."""
    ctx = ctx or {}
    action = str(control.get("action") or "")
    args = control.get("args") if isinstance(control.get("args"), dict) else {}
    entry = REGISTRY.get(action)
    if entry is None:
        return {"ok": False, "action": action, "kind": None,
                "reason": f"{action!r} is not a registered control"}
    kind, fn = entry
    try:
        result = fn(args, ctx)
    except (ControlRefused, P.PreferenceRefused) as exc:
        return {"ok": False, "action": action, "kind": kind, "reason": str(exc)}
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "action": action, "kind": kind,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "action": action, "kind": kind, "result": result}
