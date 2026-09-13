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


REGISTRY: dict[str, tuple[str, Callable[[dict, dict], dict]]] = {
    "preference.set": (PREFERENCE, _set_preference),
    "governed.propose": (GOVERNED, _propose_governed),
    "act": (ACT, _act),
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
