"""Named pairings of a STAGE and an AMBIENCE, and nothing else.

THE OWNER'S DECISION, 2026-09-08: a mode is a named `(stage, ambience)` pair --
"research mode" is *stage: research, ambience: Working* -- and the button
selects the pair.

THE TWO AXES STAY INDEPENDENT UNDERNEATH, which is the whole reason
HOME-ARCHITECTURE §6 exists: conflating them "produces an interface that
rearranges itself while you are reading, which is the single most common way an
ambient interface becomes unusable". So a pairing SETS both and does not weld
them. VESPER still moves along the ambience axis on its own -- Thinking,
Speaking, Alert -- without the stage moving, because the owner's layout must not
rearrange because VESPER started thinking. The pairing is an ENTRY POINT.

A STAGE GRANTS NO AUTHORITY. It names the kinds of window its work legitimately
needs, so opening one is an ordinary step of a task rather than a new liberty.
Every window is still `window.open` under the ownership rule and the level
ladder; what the stage supplies is the REASON a step has -- which `INV-TRIG-1`
already requires and the window log already records as the task a window belongs
to.
"""
from __future__ import annotations

import pathlib
import tomllib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
PAIRINGS = REPO / "contracts" / "policy" / "mode_pairings.toml"
AMBIENCES = REPO / "docs" / "design" / "source" / "modes.json"


class UnknownMode(ValueError):
    """A pairing, stage or ambience that is not declared.

    RAISED RATHER THAN APPROXIMATED. The nearest match to "reserach" is
    "research", and acting on that guess is how a typo becomes a mode switch
    the owner did not ask for. `host_actions.toml` is fail-closed for the same
    reason and this follows it.
    """


def _load() -> dict:
    try:
        return tomllib.loads(PAIRINGS.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UnknownMode(f"the pairings contract is unreadable: {exc}") from exc


def ambience_names() -> list:
    """The eleven, read from the file the design owns.

    NOT RESTATED HERE. `docs/design/source/modes.json` is where the eleven live
    and where their images come from; a second list in this file would be a
    second place to update and the two would diverge silently.
    """
    import json
    try:
        rows = json.loads(AMBIENCES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(r.get("mode")) for r in rows if isinstance(r, dict) and r.get("mode")]


def stages() -> dict:
    return _load().get("stages") or {}


def pairings() -> dict:
    return _load().get("pairings") or {}


def resolve(name: str) -> dict:
    """One pairing, with both halves verified to exist.

    A PAIRING THAT NAMES SOMETHING ABSENT IS REFUSED, not repaired. An ambience
    that is not one of the eleven has no wallpaper and no accent, so applying it
    would leave the room half-changed; a stage that is not declared has no list
    of windows its work may open, and defaulting that to "anything" is the
    opposite of what a stage is for.
    """
    key = str(name or "").strip().lower()
    ps = pairings()
    if key not in ps:
        raise UnknownMode(
            f"there is no mode called {name!r}. The ones that exist are: "
            + ", ".join(sorted(ps)))
    row = dict(ps[key])
    stage, amb = str(row.get("stage") or ""), str(row.get("ambience") or "")
    st = stages()
    if stage not in st:
        raise UnknownMode(
            f"mode {key!r} names stage {stage!r}, which is not declared")
    names = ambience_names()
    if names and amb not in names:
        raise UnknownMode(
            f"mode {key!r} names ambience {amb!r}, which is not one of the "
            f"eleven: {', '.join(names)}")
    out = {"mode": key, "stage": stage, "ambience": amb}
    out.update({k: v for k, v in st[stage].items()})
    return out


def may_open(stage: str) -> list:
    """The kinds of window this stage's work may open. Unknown stage: nothing.

    THE EMPTY LIST IS THE SAFE ANSWER and it is what an unknown stage gets --
    not "anything", which is what a permissive default would mean here.
    """
    st = stages().get(str(stage or "").lower())
    return list(st.get("may_open") or []) if isinstance(st, dict) else []


STATE_HOME = (pathlib.Path.home() / "Library" / "Application Support"
              / "VESPER" / "home.json")


def select(name: str, *, path: pathlib.Path | None = None) -> dict:
    """Resolve a pairing and publish it where the running home will see it.

    MERGED, NEVER REWRITTEN. `home.json` has several writers -- the face, the
    transcript, the cards, the flags -- and `HomeState.write()` says so in as
    many words. Building a fresh `HomeState` here to use its writer would carry
    that object's EMPTY transcript and workbench into the file and delete the
    runtime's, which is the whole failure its own header warns about. So this
    touches three keys and leaves every other one alone.

    ATOMIC, because the home reads this file twice a second and a half-written
    object parses as nothing at all -- which would read as "no mode" and leave
    the room unpainted.
    """
    import json
    import os
    import tempfile

    resolved = resolve(name)
    target = path or STATE_HOME
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (OSError, json.JSONDecodeError):
        existing = {}
    existing["mode"] = resolved["mode"]
    existing["stage"] = resolved["stage"]
    existing["ambience"] = resolved["ambience"]
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=1)
    os.replace(tmp, target)
    return resolved
