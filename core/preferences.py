"""The owner's preferences: the settings that are theirs to set from a button.

WHY A SEPARATE FILE AND NOT A CONTRACT. `contracts/policy/*.toml` are governed
surfaces: the runtime may propose a change and may never apply one, and a
toggle on the settings screen that wrote one of them would route around the
review from a button. A PREFERENCE is different in kind -- the owner's voice
speed, whether the island is showing, whether the wake word is armed -- and the
owner said, 2026-09-13: *"i want a toggle to toggle on or off the island in the
settings"*. So preferences live beside VESPER's state, are written by the owner's
own gesture through the home, and nothing here can reach a governed file.

DECLARED, TYPED, BOUNDED. Every key this module accepts is listed with its type,
its range or its options and its default. An undeclared key is refused; a value
outside its declared range is refused. That is `INV-TUNE-1`'s shape applied to
the owner's own settings: a screen can move a value inside its range and never
widen the range.

ATOMIC, WITH A UNIQUE TEMP NAME. `heard.offset` taught this tree (2026-09-13,
16 `FileNotFoundError`s in `island.err`) that two writers sharing one `.tmp`
name race each other into a missing file. Every writer here has its own.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from typing import Any

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
PATH = STATE / "preferences.json"

# key -> (kind, default, constraint, what it is)
#   kind: "bool" | "choice" | "range" | "text"
#   constraint: options tuple for choice; (lo, hi, step) for range; None else
SCHEMA: dict[str, tuple[str, Any, Any, str]] = {
    "island.enabled": ("bool", True, None,
                       "Whether the island shows at all. Off keeps it out of "
                       "sight; the home still runs."),
    "wake_word.enabled": ("bool", True, None,
                          "Whether the wake word is armed."),
    "voice.rate": ("range", 1.0, (0.5, 2.0, 0.05),
                   "How fast VESPER speaks, as a multiple of the voice's own rate."),
    "language": ("choice", "en-US", ("en-US", "ar-MA", "fr-FR"),
                 "The language VESPER answers in. On-device recognition exists "
                 "for en-US only; the others go to Apple's servers."),
    "quiet_hours.start": ("text", "23:00", "HH:MM",
                          "When quiet hours begin."),
    "quiet_hours.end": ("text", "08:00", "HH:MM",
                        "When quiet hours end."),
    "do_not_disturb": ("bool", False, None,
                       "Silence now, without changing the standing schedule."),
    "notification_rules": ("choice", "important", ("all", "important", "none"),
                           "What is worth telling the owner about."),
    "endpoint_selection": ("choice", "auto", ("auto", "home", "island", "speech"),
                           "Which surface VESPER reaches the owner through."),
    "microphone.gain_db": ("range", 0.0, (-20.0, 20.0, 1.0),
                           "Gain applied to what the microphone hears before "
                           "recognition. Set from a measured level, not a guess."),
    "windows.manage_others_on_demand": ("bool", True, None,
                                        "Owner's rule 31 (2026-09-13): windows "
                                        "that are not VESPER's are managed only "
                                        "when asked; VESPER's own, always."),
}

_LOCK = threading.RLock()


class PreferenceRefused(ValueError):
    """An undeclared key, or a value outside its declared range."""


def read(path: pathlib.Path | None = None) -> dict:
    """Every declared key with the owner's value or its default."""
    p = path or PATH
    stored: dict = {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            stored = raw.get("values") if isinstance(raw.get("values"), dict) else raw
    except (OSError, json.JSONDecodeError):
        stored = {}
    out = {}
    for key, (kind, default, constraint, _what) in SCHEMA.items():
        v = stored.get(key, default)
        try:
            out[key] = _coerce(key, v)
        except PreferenceRefused:
            # A CORRUPT VALUE ON DISK IS THE DEFAULT, NOT A CRASH. And it is not
            # silently the default either: `is_set` below says which keys the
            # owner actually set, so a screen can tell the two apart.
            out[key] = default
    return out


def is_set(path: pathlib.Path | None = None) -> set:
    p = path or PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        vals = raw.get("values") if isinstance(raw, dict) else None
        return set(vals or {}) & set(SCHEMA)
    except (OSError, json.JSONDecodeError):
        return set()


def _coerce(key: str, value: Any) -> Any:
    if key not in SCHEMA:
        raise PreferenceRefused(f"{key!r} is not a declared preference")
    kind, _default, constraint, _what = SCHEMA[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "on", "1", "yes"):
            return True
        if str(value).lower() in ("false", "off", "0", "no"):
            return False
        raise PreferenceRefused(f"{key} takes on or off, not {value!r}")
    if kind == "choice":
        if value in constraint:
            return value
        raise PreferenceRefused(f"{key} takes one of {list(constraint)}, not {value!r}")
    if kind == "range":
        lo, hi, _step = constraint
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise PreferenceRefused(f"{key} takes a number, not {value!r}") from None
        if not (lo <= f <= hi):
            raise PreferenceRefused(f"{key} takes {lo}..{hi}, not {f}")
        return f
    if kind == "text":
        s = str(value)
        if constraint == "HH:MM":
            parts = s.split(":")
            ok = (len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
                  and 0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60)
            if not ok:
                raise PreferenceRefused(f"{key} takes HH:MM, not {s!r}")
        return s
    raise PreferenceRefused(f"{key} has an unknown kind {kind!r}")


def write(key: str, value: Any, *, principal: str = "owner",
          source: str = "settings", path: pathlib.Path | None = None,
          bus: Any = None) -> Any:
    """Set one preference. Returns the coerced value. Refuses rather than guesses."""
    p = path or PATH
    coerced = _coerce(key, value)
    with _LOCK:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("values"), dict):
                raw = {"values": {}}
        except (OSError, json.JSONDecodeError):
            raw = {"values": {}}
        before = raw["values"].get(key)
        raw["values"][key] = coerced
        raw.setdefault("history", [])
        raw["history"] = (raw["history"] + [{
            "key": key, "from": before, "to": coerced, "by": principal,
            "source": source, "at_ms": int(time.time() * 1000)}])[-200:]
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(raw, indent=1), encoding="utf-8")
        tmp.replace(p)
    if bus is not None:
        bus.publish("preference.changed", subject=key,
                    payload={"key": key, "from": before, "to": coerced,
                             "by": principal, "source": source},
                    component="preferences")
    return coerced


def describe(key: str) -> dict:
    """What a screen needs to render a control for this key."""
    kind, default, constraint, what = SCHEMA[key]
    d: dict = {"key": key, "kind": kind, "default": default, "what": what}
    if kind == "choice":
        d["options"] = list(constraint)
    elif kind == "range":
        d["min"], d["max"], d["step"] = constraint
    elif kind == "text":
        d["format"] = constraint
    return d
