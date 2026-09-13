"""The places VESPER can work in, named, so it never has to guess where "here" is.

THE OWNER'S INSTRUCTION, 2026-09-13: *"there are so many situations where i can
say here, so i would suggest to put everything in front of vesper, and let it
choose by context."* This is that list.

WHY GUESSING WAS THE BUG. `core/capabilities.REPO` is
`Path(__file__).resolve().parents[1]` -- correct in the repo, and in the SHIPPED
COPY it resolves to `…/VESPER.app/Contents/Resources/runtime`. The owner runs the
bundle, so "the project root" silently meant the copy: asked to list it, VESPER
answered with the five directories `build.sh` ships and nothing in the reply said
which directory it had actually read.

SO THE PROJECT ROOT IS TOLD, NEVER DERIVED. A copy cannot work out that it is a
copy by looking at itself -- that is the whole shape of the defect. `build.sh`
records the path it built FROM, and this reads it back and **checks that the
place still looks like the thing it claims to be** before offering it.

AND AN UNVERIFIABLE PLACE IS ABSENT, NOT ASSUMED. `INV-HW-2` applied to paths:
UNKNOWN means UNAVAILABLE. A recorded root that no longer exists, or that no
longer carries the markers of the project, is dropped WITH ITS REASON rather than
offered and found wrong later -- because a wrong path that looks right is the
defect this module exists to end.

WHAT THIS MODULE DOES NOT DO. It does not decide what VESPER may touch. Naming a
place is not authorising an act in it: `shell.run` still runs under its
deny-default seatbelt, `contracts/policy/host_actions.toml` still says which
effects exist, and the capability ladder still prices them. This widens what
VESPER KNOWS, never what it may do -- and keeping those two separate is how
Claude Code does it too.
"""

from __future__ import annotations

import pathlib

# Where the runtime's own code lives. This one IS derivable, because it is the
# only place a module can honestly speak about by looking at itself.
_HERE = pathlib.Path(__file__).resolve().parents[1]

# THE MARKERS THAT SAY "THIS IS THE PROJECT". Two, and both must be present: a
# single marker is satisfied by any directory that happens to have a `core/`.
_PROJECT_MARKERS = ("core", "CLAUDE.md")

# Written by `build.sh` beside the shipped runtime. One line, `key = "value"`,
# read without a TOML parser so this module stays importable anywhere.
_RECORD = _HERE / "place.toml"


def _recorded_project_root() -> tuple[pathlib.Path | None, str]:
    """What the build recorded, or nothing and the reason why."""
    try:
        text = _RECORD.read_text(encoding="utf-8")
    except OSError:
        # NO RECORD. There is one honest fallback and it is NOT the derivation
        # that caused the defect: if the directory the code is running from
        # CARRIES THE PROJECT'S MARKERS, it is the project, and it is the
        # project for the same reason any other candidate would be -- it was
        # checked, not assumed.
        #
        # THE DIFFERENCE FROM THE BUG IS THE WHOLE POINT. `REPO =
        # Path(__file__).parents[1]` took the module's location AS the answer
        # with nothing verified, so the shipped copy called itself the project.
        # That copy fails this test: it carries `core/` and no `CLAUDE.md`. The
        # markers are what tell a real tree from a packaged one, so running from
        # the repo resolves and running from the bundle correctly does not.
        if all((_HERE / m).exists() for m in _PROJECT_MARKERS):
            return _HERE, ""
        return None, ("no build record of where the project is, and this "
                      "directory does not carry the project's markers -- a copy "
                      "cannot work out where the original is by looking at "
                      "itself")
    root = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("project_root"):
            _, _, val = line.partition("=")
            root = val.strip().strip('"').strip("'")
            break
    if not root:
        return None, "the build record names no project_root"
    p = pathlib.Path(root)
    if not p.is_dir():
        return None, (f"the build recorded {root!r} and nothing is there now -- "
                      f"reported as absent rather than used and found wrong")
    missing = [m for m in _PROJECT_MARKERS if not (p / m).exists()]
    if missing:
        return None, (f"{root!r} exists but does not carry {missing} -- it is "
                      f"not the project, whatever the record says")
    return p, ""


def places() -> list:
    """Every place VESPER can name, with what it is and whether it is the project.

    ORDERED MOST-SPECIFIC FIRST, because the list is read by a model choosing
    between them and the project is the answer to "the project" far more often
    than the runtime copy is.
    """
    out: list = []
    root, why = _recorded_project_root()
    if root is not None:
        out.append({
            "name": "the project",
            "path": str(root),
            "what": ("the owner's working tree -- what they mean by 'the "
                     "project', 'the repo', or 'here' when talking about the "
                     "work"),
        })
    else:
        out.append({
            "name": "the project",
            "path": "",
            "what": f"UNAVAILABLE: {why}",
        })
    # WHEN THE RUNNING CODE *IS* THE PROJECT, SAY SO ONCE. Listing the same
    # directory twice under two names invites the planner to believe there are
    # two places and pick the wrong one -- which is the confusion this module
    # exists to remove, reintroduced by the module itself.
    if root is not None and str(root) == str(_HERE):
        out[0]["what"] += " -- and this process is running from it, not a copy"
        return out
    out.append({
        "name": "the running copy",
        "path": str(_HERE),
        "what": ("the code this process is executing, shipped inside the "
                 "application. It is a COPY: editing it changes nothing the "
                 "owner keeps, and listing it is not listing the project"),
    })
    return out


def render(rows: list | None = None) -> str:
    """The places as text for the planner, or empty when there is nothing to say."""
    rows = places() if rows is None else rows
    if not rows:
        return ""
    out = ["WHERE THINGS ARE. Name the one you mean; do not assume the command "
           "runs in the project."]
    for r in rows:
        r = r if isinstance(r, dict) else {}
        path = str(r.get("path") or "")
        out.append(f"  {r.get('name')}: {path or '(unavailable)'}")
        out.append(f"      {r.get('what')}")
    return "\n".join(out)
