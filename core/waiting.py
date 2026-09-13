"""Conditions VESPER waits FOR, rather than answers it waits for.

THE OWNER, 2026-09-13: *"i want vesper whenever it asks for something, anything,
the time i do it, it should keep going, not wait for me to respond or tell it i
did it, that way vesper is more autonomous, and i should never tell it i did
it, only i do it, and it keeps going."*

WHY THIS IS NOT `Actor.resume`. That path exists for the owner ANSWERING -- a
yes or a no to a confirmation -- and re-runs authorisation with a fresh grant.
This is the other shape entirely: VESPER asked the owner to CHANGE THE WORLD
(switch Desktop, give a grant, bring a window over), and the world changing is
the answer. Nothing needs to be said, and requiring the owner to say it is the
thing they asked to remove.

A CONDITION IS READ FROM THE WORLD, NEVER REMEMBERED AS A PROMISE. Every check
below re-reads the machine at the moment it is asked. A parked turn that trusted
a flag set when the refusal happened would resume on a world that had moved --
which is the whole defect `CI-138`'s corroboration exists to refuse for windows.

AND IT GIVES UP. `TTL_MS` bounds every wait, because a turn parked on a condition
the owner never satisfies is a turn that never ends and a promise never kept. On
expiry it says what it was waiting for and stops, rather than sitting silent.
"""

from __future__ import annotations

import time
from typing import Any

# HOW LONG A TURN WAITS FOR THE WORLD TO CHANGE. Long enough for the owner to
# switch a Desktop or open System Settings and click a checkbox; short enough
# that a forgotten request does not outlive the session it belongs to.
TTL_MS = 10 * 60 * 1000

# MOST PARKED WAITS AT ONCE. A bounded dict, for `Actor._parked`'s reason: an
# unbounded one is a leak that only shows up on a long-running day.
MAX_WAITING = 16

UNKNOWN = "unknown"


class ConditionUnknown(Exception):
    """A condition was named that this module cannot check.

    RAISED RATHER THAN DEFAULTED TO FALSE. A condition nobody can check is not
    a condition that is merely unmet -- it is a request to wait forever, and
    the caller has to hear about it rather than discover it as silence.
    """


def _window_on_showing_desktop(args: dict) -> tuple[bool, str]:
    """Is the named window now on the Desktop that is showing?"""
    wid = str((args or {}).get("window_id") or "").strip()
    if not wid:
        return False, "no window was named, so nothing can be watched for"
    try:
        from core.capabilities import _window_bridge
        raw = _window_bridge("--windows-list")
    except Exception as exc:                           # noqa: BLE001
        return False, f"the window list could not be read: {type(exc).__name__}"
    for w in (raw.get("windows") or []):
        if str(w.get("window_id")) == wid:
            if w.get("on_active_desktop"):
                return True, ""
            return False, "that window is still on another Desktop"
    return False, "that window is no longer open at all"


def _vespers_desktop_showing(args: dict) -> tuple[bool, str]:
    """Is VESPER's own Desktop the one on screen?"""
    try:
        from core.capabilities import _window_bridge
        raw = _window_bridge("--windows-list")
    except Exception as exc:                           # noqa: BLE001
        return False, f"the window list could not be read: {type(exc).__name__}"
    # `vespers_desktop` is null unless vesper's ground is on the showing Space;
    # that is exactly the question, so its presence IS the answer.
    return bool(raw.get("vespers_desktop")), "vesper's desktop is not showing yet"


def _grant_present(args: dict) -> tuple[bool, str]:
    """Has the owner given the named permission since we asked?

    READ WITHOUT PROMPTING. `Grants.swift` reads every permission with
    non-prompting probes, so asking this repeatedly cannot put a dialog on the
    owner's screen -- which would be the opposite of leaving them alone.
    """
    which = str((args or {}).get("which") or "").strip().lower()
    if not which:
        return False, "no permission was named, so nothing can be watched for"
    # THE READER PRINTS TEXT, NOT JSON, SO THIS PARSES TEXT. `_window_bridge`
    # looks for a JSON object and would find none -- the first version of this
    # asked for a `--grants-json` flag that does not exist, which is a condition
    # that could never once have been true. Checked against the binary's own
    # flags rather than assumed.
    import subprocess as _sp
    try:
        from core.capabilities import VESPER_BIN
        out = _sp.run([str(VESPER_BIN), "--grants"], capture_output=True,
                      text=True, timeout=30, check=False)
    except Exception as exc:                           # noqa: BLE001
        return False, f"the permissions could not be read: {type(exc).__name__}"
    # Lines read "[ok]      Accessibility" / "[ask]     Screen Recording".
    seen = {}
    for ln in (out.stdout or "").splitlines():
        ln = ln.strip()
        if ln.startswith("[") and "]" in ln:
            mark, _, rest = ln.partition("]")
            name = rest.strip().lower()
            if name:
                seen[name] = mark.strip("[").strip()
    for name, mark in seen.items():
        if which in name:
            return mark == "ok", f"{name} is still '{mark}'"
    return False, (f"{which!r} is not a permission this reader lists "
                   f"({', '.join(sorted(seen)[:6])})")


CONDITIONS = {
    "window_on_showing_desktop": _window_on_showing_desktop,
    "vespers_desktop_showing": _vespers_desktop_showing,
    "grant_present": _grant_present,
}


def check(name: str, args: dict | None = None) -> tuple[bool, str]:
    """Is the condition true RIGHT NOW? Never cached, never remembered."""
    fn = CONDITIONS.get(str(name or ""))
    if fn is None:
        raise ConditionUnknown(
            f"{name!r} is not a condition this node can check. The set is "
            f"closed: {sorted(CONDITIONS)}. A condition nobody can read is a "
            f"request to wait forever.")
    return fn(args or {})


class Waiting:
    """Turns parked on the world changing, and the ones now ready to go on."""

    def __init__(self, *, now_ms=None, ttl_ms: int = TTL_MS) -> None:
        self._now = now_ms or (lambda: int(time.time() * 1000))
        self._ttl = int(ttl_ms)
        self._items: dict = {}

    def park(self, key: str, condition: str, args: dict, payload: Any) -> None:
        """Wait for `condition`. Raises if nothing can check it."""
        check(condition, args)          # fail loudly now, not silently later
        if len(self._items) >= MAX_WAITING:
            oldest = min(self._items.values(), key=lambda v: v["at_ms"])
            self._items.pop(oldest["key"], None)
        self._items[key] = {"key": key, "condition": condition, "args": dict(args or {}),
                            "payload": payload, "at_ms": self._now()}

    def ready(self) -> list:
        """Everything whose condition is now true. Removed as it is returned."""
        out = []
        for key, item in list(self._items.items()):
            try:
                ok, _why = check(item["condition"], item["args"])
            except ConditionUnknown:
                self._items.pop(key, None)
                continue
            if ok:
                out.append(self._items.pop(key))
        return out

    def expired(self) -> list:
        """Waits that outlived their window. Removed as they are returned."""
        now = self._now()
        out = []
        for key, item in list(self._items.items()):
            if now - item["at_ms"] >= self._ttl:
                out.append(self._items.pop(key))
        return out

    def pending(self) -> list:
        return [dict(v) for v in self._items.values()]
