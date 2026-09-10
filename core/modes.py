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


def window_kinds() -> dict:
    """kind -> the strings that identify an application as being of that kind.

    POLICY, NOT CODE, for the same reason the pairings are: which application
    counts as a browser is a decision the owner may change, and changing it
    must not need a rebuild.
    """
    return _load().get("window_kinds") or {}


def kind_of(label: str = "", bundle: str = "") -> str:
    """What kind of window this application opens, or "" if nothing claims it.

    MATCHED ON BOTH THE LABEL AND THE BUNDLE ID because the two fail in
    opposite directions. A label is what the owner said and may be anything
    ("safari", "Safari.app", "SAFARI"); a bundle id is durable but is only
    known after `_bundle_for` has resolved it, and a path has none at all.

    THE EMPTY STRING IS A REAL ANSWER AND IT IS NOT "ALLOWED". `stage_may_open`
    is what decides, and it refuses an unclassifiable application under a stage
    that names a list -- the same fail-closed posture `may_open` takes for an
    unknown stage. Returning a permissive default here would put the decision
    in the wrong place and make it invisible.
    """
    hay = f"{label} {bundle}".lower()
    if not hay.strip():
        return ""
    for kind, needles in window_kinds().items():
        if not isinstance(needles, list):
            continue
        for n in needles:
            if str(n).lower() in hay:
                return str(kind)
    return ""


def current_stage(path: pathlib.Path | None = None) -> str:
    """The stage the owner's chosen mode put us in, or "" if none has been set.

    READ FROM `home.json`, WHICH IS WHERE `select()` PUBLISHES IT. Not from a
    module global: `mode.set` and `window.open` may be executed by the same
    process, but the mode also survives a restart in that file and a global
    would not.

    "" IS THE STATE BEFORE ANY MODE IS CHOSEN, and it must not gate anything.
    Until the owner enters a mode there is no stage, and a stage nobody chose
    cannot be the reason a window is refused.
    """
    # IMPORTED HERE, like `select()` does. This module is imported by the
    # capability path on every window action and `json` is not needed by most
    # of it; the local import is the shape the rest of the file already uses.
    import json

    target = path or STATE_HOME
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("stage") or "").strip() if isinstance(data, dict) else ""


def stage_may_open(stage: str, *, label: str = "", bundle: str = "") -> tuple:
    """May this stage open this application unprompted? Returns (ok, reason).

    THE THREE ANSWERS, AND THE ORDER MATTERS.

    1. NO STAGE IS NOT A REFUSAL. Before the owner has entered a mode there is
       no stage, so there is nothing to enforce and everything behaves as it
       did. Gating on an unchosen stage would break every window action the
       moment this landed, which is not what §11.2a asks for.
    2. A DECLARED STAGE WITH AN EMPTY LIST OPENS NOTHING. `idle` is exactly
       that -- "nothing asked" -- and it is the case the empty list was written
       for.
    3. AN UNCLASSIFIABLE APPLICATION IS REFUSED, NOT WAVED THROUGH. It is named
       in the refusal along with the table that would fix it, because the
       alternative -- allowing what nothing claims -- makes `may_open` advisory
       and that is how a reservation becomes a suggestion.
    """
    st = str(stage or "").strip().lower()
    if not st:
        return True, ""
    declared = stages()
    if st not in declared:
        return False, (f"the stage {st!r} is not declared, so what its work may "
                       f"open is unknown -- and defaulting that to 'anything' "
                       f"is the opposite of what a stage is for")
    allowed = may_open(st)
    if not allowed:
        return False, (f"{st} mode opens no windows -- it is the mode for "
                       f"nothing being asked. Ask me directly and I will open it")
    kind = kind_of(label=label, bundle=bundle)
    if not kind:
        return False, (f"I do not know what kind of window {label or bundle!r} "
                       f"is, and {st} mode may only open {', '.join(allowed)}. "
                       f"Naming it in [window_kinds] would fix that")
    if kind not in allowed:
        return False, (f"{st} mode may open {', '.join(allowed)}, and that is a "
                       f"{kind}. Ask me directly and I will open it anyway")
    return True, ""


def stage_limits(stage: str) -> dict:
    """`max_windows` and `owner_keeps` for a stage. Absent means unbounded/no.

    ABSENT IS NOT ZERO. A stage that declares no `max_windows` is not a stage
    that may open none -- `may_open` already carries that -- so the absence
    reads as "no cap", and only a declared number bounds anything.
    """
    st = stages().get(str(stage or "").strip().lower())
    if not isinstance(st, dict):
        return {"max_windows": None, "owner_keeps": False}
    cap = st.get("max_windows")
    try:
        cap = int(cap) if cap is not None else None
    except (TypeError, ValueError):
        cap = None
    return {"max_windows": cap, "owner_keeps": bool(st.get("owner_keeps"))}


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
