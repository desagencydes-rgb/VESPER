"""VESPER's showcase -- the surface it shows things ON, and the only one it owns.

THE OWNER'S ASK, 2026-09-15, VERBATIM: *"can vesper show stuff on screen actively
fast (open windows, open website, open files, codes, in specific locations to show
specific details, open images, videos, from wherever place it could do it best,
pull up whiteboard, draw directly on my screen, show arrows, have it's own cursor?
[...] can it do the work while hiding the screen activity while i am working, and
when it reports then it opens everything needed (not just windows, specific
locations in each window) on it's desktop and not mine to not interrupt my work?"*

TWO MEASURED FACTS DECIDE THIS MODULE'S SHAPE, and neither is a preference.

  1. `core/capabilities.py:window_relocate` records, from 2026-09-08/09: a FOREIGN
     application's window does not move between Spaces for `CGSMoveWindowsToManagedSpace`
     nor for the older add/remove pair. VESPER's OWN windows do move.
  2. The same file records that a NEWLY CREATED window does not reliably land on
     the Space that is showing.

Read together they say the last clause of the ask -- *on its desktop and not mine*
-- is reachable through exactly one route: a surface VESPER OWNS, created once,
kept alive, and relocated as a unit. It is NOT reachable by opening Preview,
QuickTime, a browser and an editor and herding them, because those four windows
are foreign and this macOS will not move them. So the showcase is one window of
VESPER's own with PANES inside it, and "open an image, a video, a website and a
file at line 42" becomes four panes rather than four applications.

That is not a workaround dressed up. It is strictly MORE than the herd of
applications could give, because a pane can be pointed AT: an arrow can end on
line 42 of the code pane and stay there when the window is resized, which no
arrangement of Preview and TextEdit can do.

WHAT A SCENE IS. An ordered list of panes, a list of marks drawn over them, where
VESPER's own cursor is, and one sentence saying WHY this is on screen. It is data,
published atomically to one file; the window reads it and renders. Nothing here
draws anything, and that separation is the reason this module can be tested by a
gate with no window server in front of it.

COORDINATES ARE FRACTIONS OF THEIR PANE, NEVER PIXELS. A mark placed at pixel 300
is wrong the moment the window is resized or the owner's display changes, and this
surface exists to be looked at on a display nobody has measured yet. Fractions
survive both. The one place a raw number is allowed is a CODE LINE, which is not a
coordinate at all -- it is an identity, and the renderer resolves it to pixels
after layout. `anchor` marks exist for exactly that reason: an arrow that ends on
"line 42" still ends on line 42 after a reflow, and an arrow that ends at y=0.31
does not.

ORDER IS `revision`, NOT A TIMESTAMP. `INV-COORD-4` -- wall clock never orders.
A reader that received revision 9 ignores revision 8 arriving late, and no clock
is consulted to know that.

BOUNDS ARE REFUSALS, NOT TRUNCATIONS. A scene that exceeds a bound is REFUSED with
the reason, because a silently truncated demonstration is a demonstration that
lies about what it showed -- the same fault as the stall record that rounded the
number it was judged by.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
SCENE = "showcase.json"

# THE CLOSED SETS. Every one of these is closed for the same reason `ui_act`'s
# action set is closed: an unknown kind reaching the renderer is an unknown kind
# rendering nothing, which looks exactly like a scene that worked.
PANE_KINDS = ("code", "image", "video", "web", "board", "text", "run")
MARK_KINDS = ("arrow", "ring", "ink", "label")
GESTURES = ("none", "move", "tap", "drag")
DESKTOPS = ("vesper", "here")

# WHY THESE NUMBERS. Eight panes is the most a 16-inch display shows at a size
# the owner can read -- past that the showcase is a mosaic, not an explanation.
# The code slice is bounded at 400 lines because the pane scrolls and an
# explanation that needs more than 400 lines needs a second pane with its own
# sentence. The character bounds keep one published file under a megabyte, which
# is what a 0.25 s reader can afford.
MAX_PANES = 8
MAX_MARKS = 64
MAX_CODE_LINES = 400
MAX_TEXT_CHARS = 40_000
MAX_INK_POINTS = 500
MAX_SCENE_BYTES = 1_000_000
MAX_TAIL_LINES = 200

# NEVER INLINED INTO A SCENE, whatever the caller says. The showcase publishes a
# world-readable file and renders it on a surface pointed at a display: a secret
# that reaches it has been disclosed twice over. The capability in front of this
# runs the full path ladder; this list is the second lock, and it is here because
# the first one has been routed around before -- `shell.run`'s `cat` was
# allowlisted while `fs.read` of the same file was L5.
NEVER_SHOWN = ("/.config/vesper/", "/.ssh/", "/.aws/", "/.gnupg/",
               "/Library/Keychains/", "/.netrc")


def state_dir(explicit=None) -> pathlib.Path:
    """Where this surface's files live.

    THE ENVIRONMENT OVERRIDE EXISTS FOR THE GATES AND FOR NOTHING ELSE.
    `a-checks-red-run-must-not-damage-the-repo`: the checks below drive the real
    capability, and without a way to point it somewhere else they would publish
    test scenes onto the surface the owner is looking at and overwrite the
    running window's readback. `Showcase.swift` has the same override for the
    same reason, and the probe sets it.
    """
    if explicit:
        return pathlib.Path(explicit)
    env = os.environ.get("VESPER_SHOWCASE_DIR")
    return pathlib.Path(env) if env else STATE


def scene_path(state_dir_: pathlib.Path | None = None) -> pathlib.Path:
    return state_dir(state_dir_) / SCENE


def _forbidden(raw: str) -> bool:
    """Is this a path the showcase refuses to read, whatever asked?

    MATCHED ON THE RESOLVED PATH WITH A TRAILING SEPARATOR, so `~/.sshfoo` is not
    caught by `/.ssh/` and `~/.ssh/id_rsa` is. Symlinks are resolved first: the
    one route around a prefix check is a link, and `resolve()` closes it.
    """
    try:
        p = str(pathlib.Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        p = str(raw)
    hay = p + "/"
    return any(bad in hay for bad in NEVER_SHOWN)


def read_code(path: str, *, line: int | None = None, before: int = 40,
              after: int = 80) -> dict:
    """A bounded, numbered slice of a file, centred on the line being shown.

    THE SLICE CARRIES ITS OWN FIRST LINE NUMBER, and the renderer numbers from
    there. A pane that renumbered from 1 would put the arrow on the right PIXEL
    and the wrong LINE, which is the failure this whole module is built to avoid.
    """
    p = pathlib.Path(path).expanduser()
    if _forbidden(str(p)):
        return {"ok": False, "reason": "vesper does not put that file on a screen"}
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as e:
        return {"ok": False, "reason": f"{p.name} could not be read: {e}"}
    lines = raw.splitlines()
    total = len(lines)
    if line is None:
        first, last = 1, min(total, MAX_CODE_LINES)
    else:
        line = max(1, min(int(line), max(total, 1)))
        first = max(1, line - max(0, int(before)))
        last = min(total, first + max(1, int(before) + int(after)) - 1)
        if last - first + 1 > MAX_CODE_LINES:
            last = first + MAX_CODE_LINES - 1
    body = "\n".join(lines[first - 1:last])
    if len(body) > MAX_TEXT_CHARS:
        body = body[:MAX_TEXT_CHARS]
        # A CUT SLICE SAYS SO IN THE RECORD, not only in the pixels.
        return {"ok": True, "body": body, "first_line": first, "last_line": last,
                "total_lines": total, "clipped": True, "name": p.name,
                "path": str(p)}
    return {"ok": True, "body": body, "first_line": first, "last_line": last,
            "total_lines": total, "clipped": False, "name": p.name, "path": str(p)}


def tail(path: str, lines: int = 60) -> dict:
    """The end of a growing file -- what a run is saying right now.

    READ WHOLE AND SLICED, not seeked. These records are kilobytes and the
    correctness of a seek into a partially-written UTF-8 line is not worth the
    microseconds: a torn multi-byte character renders as a replacement glyph in
    the middle of the thing the owner is being shown.
    """
    p = pathlib.Path(path).expanduser()
    if _forbidden(str(p)):
        return {"ok": False, "reason": "vesper does not put that file on a screen"}
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as e:
        return {"ok": False, "reason": f"{p.name} could not be read: {e}"}
    got = raw.splitlines()
    n = max(1, min(int(lines), MAX_TAIL_LINES))
    return {"ok": True, "body": "\n".join(got[-n:]), "name": p.name,
            "path": str(p), "total_lines": len(got)}


def _frac(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 1.0 else None


def _check_pane(pane: dict, idx: int) -> str:
    """One pane, or the reason it is refused."""
    if not isinstance(pane, dict):
        return f"pane {idx} is not a record"
    pid = str(pane.get("id") or "").strip()
    if not pid:
        return f"pane {idx} has no id, so nothing can point at it"
    kind = str(pane.get("kind") or "")
    if kind not in PANE_KINDS:
        return (f"pane {pid!r} is a {kind!r}, which is not something vesper "
                f"shows. The set is closed: {', '.join(PANE_KINDS)}")
    for field in ("body", "text"):
        val = pane.get(field)
        if isinstance(val, str) and len(val) > MAX_TEXT_CHARS:
            return (f"pane {pid!r} carries {len(val)} characters and the bound is "
                    f"{MAX_TEXT_CHARS}; split it across panes with a sentence each")
    if kind in ("code", "image", "video", "run") and not str(pane.get("path") or ""):
        return f"pane {pid!r} is a {kind} pane with no path"
    if kind == "web" and not str(pane.get("url") or ""):
        return f"pane {pid!r} is a web pane with no address"
    if str(pane.get("path") or "") and _forbidden(str(pane["path"])):
        return f"pane {pid!r} names a file vesper does not put on a screen"
    span = pane.get("span", 1)
    if span not in (1, 2):
        return f"pane {pid!r} asks to span {span!r}; a pane spans 1 or 2 columns"
    focus = pane.get("focus")
    if focus is not None and not isinstance(focus, dict):
        return f"pane {pid!r} has a focus that is not a record"
    if isinstance(focus, dict):
        region = focus.get("region")
        if region is not None:
            if (not isinstance(region, (list, tuple)) or len(region) != 4
                    or any(_frac(v) is None for v in region)):
                return (f"pane {pid!r} focuses a region that is not four "
                        f"fractions of the pane")
    return ""


def _check_mark(mark: dict, idx: int, pane_ids: set) -> str:
    """One mark, or the reason it is refused.

    A MARK THAT NAMES NO PANE IS REFUSED rather than drawn on the window. An
    arrow floating over the gap between panes points at nothing, and a
    demonstration whose arrows point at nothing is worse than one with no arrows:
    the owner follows it.
    """
    if not isinstance(mark, dict):
        return f"mark {idx} is not a record"
    kind = str(mark.get("kind") or "")
    if kind not in MARK_KINDS:
        return (f"mark {idx} is a {kind!r}; the set is closed: "
                f"{', '.join(MARK_KINDS)}")
    pane = str(mark.get("pane") or "")
    if pane not in pane_ids:
        return (f"mark {idx} is drawn on pane {pane!r}, which is not in this "
                f"scene")
    anchor = mark.get("anchor")
    if anchor is not None and not isinstance(anchor, dict):
        return f"mark {idx} has an anchor that is not a record"
    if kind == "ink":
        pts = mark.get("points")
        if not isinstance(pts, (list, tuple)) or not pts:
            return f"mark {idx} is a stroke with no points"
        if len(pts) > MAX_INK_POINTS:
            return (f"mark {idx} carries {len(pts)} points and the bound is "
                    f"{MAX_INK_POINTS}")
        for pt in pts:
            if (not isinstance(pt, (list, tuple)) or len(pt) != 2
                    or _frac(pt[0]) is None or _frac(pt[1]) is None):
                return f"mark {idx} has a point that is not two fractions of the pane"
        return ""
    if kind == "label" and not str(mark.get("text") or "").strip():
        return f"mark {idx} is a label with nothing written on it"
    # Arrows and rings may be placed either by fraction or by anchor. One of the
    # two is required: a mark with neither has no position at all.
    has_at = _frac((mark.get("at") or [None, None])[0]) is not None \
        if isinstance(mark.get("at"), (list, tuple)) and len(mark.get("at")) == 2 else False
    if not has_at and not isinstance(anchor, dict):
        return (f"mark {idx} has neither a point on its pane nor an anchor to "
                f"something in it")
    if isinstance(mark.get("at"), (list, tuple)) and len(mark["at"]) == 2:
        if any(_frac(v) is None for v in mark["at"]):
            return f"mark {idx} sits outside its pane"
    frm = mark.get("from")
    if frm is not None:
        if (not isinstance(frm, (list, tuple)) or len(frm) != 2
                or any(_frac(v) is None for v in frm)):
            return f"mark {idx} starts outside its pane"
    return ""


def validate(scene: dict) -> tuple[bool, str]:
    """Is this scene renderable, and if not, exactly why.

    CALLED BEFORE PUBLISHING AND AGAIN BY THE GATE. The renderer is not a
    validator: a page that skips what it cannot draw reports success for a scene
    that showed half of itself, which is `INV-HW-2`'s shape applied to pixels --
    UNKNOWN is UNAVAILABLE, and a pane that did not render is not a pane that
    rendered emptily.
    """
    if not isinstance(scene, dict):
        return False, "a scene is a record"
    panes = scene.get("panes") or []
    if not isinstance(panes, (list, tuple)):
        return False, "panes are a list"
    if len(panes) > MAX_PANES:
        return False, (f"{len(panes)} panes were asked for and the bound is "
                       f"{MAX_PANES}; a scene past that is a mosaic, not an "
                       f"explanation")
    ids = []
    for i, pane in enumerate(panes):
        why = _check_pane(pane, i)
        if why:
            return False, why
        ids.append(str(pane.get("id")))
    if len(set(ids)) != len(ids):
        dupe = next(i for i in ids if ids.count(i) > 1)
        return False, f"two panes are both called {dupe!r}; a mark could not say which"
    marks = scene.get("marks") or []
    if not isinstance(marks, (list, tuple)):
        return False, "marks are a list"
    if len(marks) > MAX_MARKS:
        return False, f"{len(marks)} marks were asked for and the bound is {MAX_MARKS}"
    for i, mark in enumerate(marks):
        why = _check_mark(mark, i, set(ids))
        if why:
            return False, why
    cursor = scene.get("cursor")
    if cursor is not None:
        if not isinstance(cursor, dict):
            return False, "the cursor is a record"
        if cursor.get("pane") and str(cursor["pane"]) not in set(ids):
            return False, f"the cursor is on pane {cursor['pane']!r}, which is not in this scene"
        if str(cursor.get("gesture") or "none") not in GESTURES:
            return False, (f"{cursor.get('gesture')!r} is not a gesture; the set "
                           f"is closed: {', '.join(GESTURES)}")
        for axis in ("x", "y"):
            if cursor.get(axis) is not None and _frac(cursor[axis]) is None:
                return False, f"the cursor's {axis} is not a fraction of its pane"
    desktop = str(scene.get("desktop") or "vesper")
    if desktop not in DESKTOPS:
        return False, (f"{desktop!r} is not a desktop this shows on; it is "
                       f"{' or '.join(DESKTOPS)}")
    if not str(scene.get("why") or "").strip():
        return False, ("a scene says why it is on screen; the owner asked to KNOW "
                       "what vesper did, and an unexplained window does not tell him")
    blob = json.dumps(scene)
    if len(blob) > MAX_SCENE_BYTES:
        return False, (f"the scene is {len(blob)} bytes and the bound is "
                       f"{MAX_SCENE_BYTES}; point at a file instead of inlining it")
    return True, ""


def current(state_dir: pathlib.Path | None = None) -> dict:
    """What is published right now, or an empty scene.

    A MISSING OR CORRUPT FILE READS AS EMPTY AND NOT AS AN ERROR. This is read on
    a 0.25 s timer by a window that must not die because a writer was interrupted
    mid-rename -- and it cannot be, because the rename is atomic, which is
    precisely why a corrupt read here means something worse happened and the
    right answer is still to show nothing rather than to stop.
    """
    p = scene_path(state_dir)
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"revision": 0, "panes": [], "marks": [], "visible": False,
                "why": "", "desktop": "vesper"}
    if not isinstance(got, dict):
        return {"revision": 0, "panes": [], "marks": [], "visible": False,
                "why": "", "desktop": "vesper"}
    return got


_LOCK = threading.Lock()


def hydrate(scene: dict) -> tuple[dict, str]:
    """Read in what a pane points at, so nothing publishes a pane with no content.

    WHY THIS IS HERE AND NOT IN THE CAPABILITY. It WAS in the capability, and a
    demonstration -- which publishes its own scenes and never goes through
    `showcase.scene` -- put three code panes on the showcase with a path, a title and
    an empty body. The page rendered them faithfully: three empty boxes. One
    reader, one place, and now there is no second route that can skip it.

    RUN PANES ARE NOT HYDRATED HERE, deliberately. Their content grows after the
    scene is published and the WINDOW re-reads the tail every tick; baking a
    snapshot in would freeze a live run at the moment it was described.
    """
    out = dict(scene or {})
    panes = []
    for pane in (out.get("panes") or []):
        if not isinstance(pane, dict):
            panes.append(pane)
            continue
        pane = dict(pane)
        if pane.get("kind") == "code" and not pane.get("body"):
            focus = pane.get("focus") or {}
            got = read_code(str(pane.get("path") or ""), line=focus.get("line"),
                            before=int(focus.get("before", 40) or 40),
                            after=int(focus.get("after", 80) or 80))
            if not got.get("ok"):
                return out, str(got.get("reason"))
            pane["body"] = got["body"]
            pane["first_line"] = got["first_line"]
            pane["total_lines"] = got["total_lines"]
            pane["clipped"] = got["clipped"]
        panes.append(pane)
    out["panes"] = panes
    return out, ""


def publish(scene: dict, state_dir: pathlib.Path | None = None) -> dict:
    """Put a scene on the showcase, atomically, with the next revision.

    THE TEMP NAME CARRIES PID AND THREAD. Nine writers in this corpus shared one
    temp name and two of them racing produced a file that was neither. The rule
    is now checked by `an-atomic-write-never-shares-its-temp-name`, and this
    writer is inside its scan.
    """
    scene, missing = hydrate(scene)
    if missing:
        return {"ok": False, "reason": missing}
    ok, why = validate(scene)
    if not ok:
        return {"ok": False, "reason": why}
    p = scene_path(state_dir)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        prev = current(state_dir)
        out = dict(scene)
        try:
            out["revision"] = int(prev.get("revision") or 0) + 1
        except (TypeError, ValueError):
            out["revision"] = 1
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        _remember(prev, state_dir)
    return {"ok": True, "revision": out["revision"], "panes": len(out.get("panes") or []),
            "marks": len(out.get("marks") or []), "path": str(p),
            "previous_revision": int(prev.get("revision") or 0)}


# HOW FAR BACK A SHOWCASE CAN BE PUT. Four, and bounded by bytes as well as by
# count: a history that grows with the thing it remembers is a file that is fine
# for a week and then is not.
HISTORY = "showcase-was.json"
HISTORY_DEPTH = 4
HISTORY_MAX_SCENE_BYTES = 200_000


def _remember(scene: dict, state_dir_=None) -> None:
    """Keep the scene that was there, so a step can be taken back.

    A SCENE TOO BIG TO KEEP IS RECORDED AS ABSENT, NOT DROPPED SILENTLY. `restore`
    then refuses with the reason, which is the honest answer -- an undo that
    quietly clears the screen instead of putting it back is worse than one that
    says it cannot.
    """
    p = state_dir(state_dir_) / HISTORY
    try:
        was = json.loads(p.read_text(encoding="utf-8"))
        rows = was.get("scenes") if isinstance(was, dict) else None
    except (OSError, ValueError):
        rows = None
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    rev = int(scene.get("revision") or 0)
    if rev:
        blob = json.dumps(scene)
        rows.append({"revision": rev,
                     "scene": scene if len(blob) <= HISTORY_MAX_SCENE_BYTES else None,
                     "too_big": len(blob) > HISTORY_MAX_SCENE_BYTES})
    rows = rows[-HISTORY_DEPTH:]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"scenes": rows}, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        # A HISTORY THAT CANNOT BE WRITTEN MUST NOT FAIL THE PUBLISH. The owner
        # asked to be shown something; losing the undo is a smaller failure than
        # not showing it, and `restore` reports the gap rather than inventing one.
        return


def restore(revision: int, state_dir_=None) -> dict:
    """Put back the scene that carried this revision."""
    p = state_dir(state_dir_) / HISTORY
    try:
        rows = (json.loads(p.read_text(encoding="utf-8")) or {}).get("scenes") or []
    except (OSError, ValueError):
        rows = []
    for row in reversed([r for r in rows if isinstance(r, dict)]):
        if int(row.get("revision") or 0) == int(revision):
            if row.get("too_big") or not isinstance(row.get("scene"), dict):
                return {"ok": False,
                        "reason": (f"revision {revision} was too large to keep, "
                                   f"so vesper will not pretend to put it back")}
            scene = dict(row["scene"])
            scene.pop("revision", None)
            return publish(scene, state_dir_)
    return {"ok": False, "reason": (f"revision {revision} is further back than the "
                                    f"last {HISTORY_DEPTH} scenes")}


def patch(state_dir: pathlib.Path | None = None, **fields) -> dict:
    """Change part of the scene and leave the rest standing.

    THE WHOLE MERGED SCENE IS VALIDATED, never the patch alone. A patch that is
    legal by itself can produce an illegal scene -- dropping the pane an arrow
    points at is the obvious one -- and validating the fragment would let exactly
    that through.
    """
    merged = dict(current(state_dir))
    merged.update(fields)
    merged.pop("revision", None)
    return publish(merged, state_dir)


def clear(state_dir: pathlib.Path | None = None, why: str = "nothing to show") -> dict:
    """Empty the showcase without destroying its revision line."""
    return publish({"panes": [], "marks": [], "cursor": None, "visible": False,
                    "why": why, "desktop": "vesper"}, state_dir)


# --------------------------------------------------------- the two-way channel
#
# THE SCENE GOES ONE WAY AND IS NOT ENOUGH. A published scene is a request, and
# §9r's whole lesson is that a push which returned without throwing is not a
# surface that rendered: "every instrument used mounted its OWN webview and fired
# ONE push, which is a different question from 'is the surface the owner is
# looking at rendering'". So the window writes back what it actually DREW, and
# `rendered()` below is how an act verifies itself against that rather than
# against its own optimism.
#
# AND SOME THINGS CANNOT BE ASKED FOR IN A SCENE AT ALL. Driving the showcase's
# own browser -- navigate, click, type, read the page back -- is a conversation
# with a live view inside the home process, which no second process can reach:
# `_window_bridge` works for a foreign app because the accessibility interface is
# systemwide, and a `WKWebView` in another process is not. Hence an ASK file with
# a sequence number and a SAID file carrying results, which is the same transport
# the rest of this surface uses and is testable with no window server present.
ASK = "showcase-ask.json"
SAID = "showcase-said.json"

# The verbs the window will act on. Closed, for the reason every other set here
# is closed: an unknown verb is a command that silently does nothing, which is
# indistinguishable from one that worked.
ASK_VERBS = ("navigate", "click", "type", "key", "scroll", "read", "back",
             "reload", "shot", "wait_for",
             # NOT ABOUT A PAGE. `screen` photographs the display, and it goes
             # down this channel for one reason: the answer is only true when the
             # process answering IS vesper. See `run(_:seq:)` in Showcase.swift.
             "screen")
MAX_ASKS = 32


def ask_path(state_dir_=None) -> pathlib.Path:
    return state_dir(state_dir_) / ASK


def said_path(state_dir_=None) -> pathlib.Path:
    return state_dir(state_dir_) / SAID


def said(state_dir=None) -> dict:
    """What the window last reported drawing and doing."""
    try:
        got = json.loads(said_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _ask_file(state_dir=None) -> dict:
    try:
        got = json.loads(ask_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seq": 0, "asks": []}
    if not isinstance(got, dict):
        return {"seq": 0, "asks": []}
    return got


def ask(verb: str, *, timeout_s: float = 8.0, state_dir=None, **fields) -> dict:
    """Ask the showcase's own browser to do one thing, and wait for its answer.

    THE SEQUENCE NUMBER IS THE IDENTITY, not the position in the list. Two acts
    racing would otherwise read each other's answers, and the failure would look
    like a flaky page rather than like the transport it is.

    A TIMEOUT IS A REFUSAL AND NOT A GUESS. If the window did not answer, this
    returns `ok: False` saying so. It does not return the previous answer, and it
    does not assume success: an act whose verification times out is an act whose
    verification failed.
    """
    import time

    if verb not in ASK_VERBS:
        return {"ok": False, "reason": (f"{verb!r} is not something vesper asks a "
                                        f"page to do; the set is closed: "
                                        f"{', '.join(ASK_VERBS)}")}
    p = ask_path(state_dir)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = _ask_file(state_dir)
        seq = int(cur.get("seq") or 0) + 1
        asks = [a for a in (cur.get("asks") or []) if isinstance(a, dict)]
        asks.append({"seq": seq, "verb": verb, **fields})
        out = {"seq": seq, "asks": asks[-MAX_ASKS:]}
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
        os.replace(tmp, p)

    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        done = (said(state_dir).get("answers") or {})
        got = done.get(str(seq))
        if isinstance(got, dict):
            return {"ok": bool(got.get("ok")), "seq": seq, **got}
        time.sleep(0.05)
    return {"ok": False, "seq": seq, "timed_out": True,
            "reason": (f"the showcase did not answer {verb!r} within "
                       f"{timeout_s:g}s -- it may not be open")}


def rendered(revision: int, *, timeout_s: float = 4.0, state_dir=None) -> dict:
    """Wait until the window reports having drawn AT LEAST this revision.

    `>=` AND NOT `==`. A faster revision may overtake this one between publish and
    read -- that is correct behaviour and not a miss, because a later scene
    supersedes this one by definition. Insisting on equality would turn a
    demonstration that advanced quickly into a demonstration that reported
    failures.
    """
    import time

    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        s = said(state_dir)
        try:
            got = int(s.get("revision") or -1)
        except (TypeError, ValueError):
            got = -1
        if got >= int(revision):
            return {"ok": True, "revision": got,
                    "panes_drawn": list(s.get("panes_drawn") or []),
                    "marks_drawn": int(s.get("marks_drawn") or 0),
                    "errors": list(s.get("errors") or [])}
        time.sleep(0.05)
    return {"ok": False, "revision": revision, "timed_out": True,
            "reason": ("the showcase did not report drawing that scene -- it is "
                       "not open, or it is not reading")}


def describe(scene: dict | None = None, state_dir: pathlib.Path | None = None) -> str:
    """One sentence the owner can hear, saying what is on the showcase.

    SPOKEN, SO IT NAMES THINGS AND NOT COUNTS WHERE IT CAN. "three panes" tells
    the owner nothing he could act on; "the run's output, char_lm/main.py at line
    64, and the loss curve" tells him where to look.
    """
    s = scene if scene is not None else current(state_dir)
    panes = s.get("panes") or []
    if not panes:
        return "vesper's showcase is empty"
    named = []
    for pane in panes[:4]:
        kind = str(pane.get("kind") or "")
        title = str(pane.get("title") or "").strip()
        if title:
            named.append(title)
        elif kind == "code":
            name = pathlib.Path(str(pane.get("path") or "")).name
            focus = pane.get("focus") or {}
            line = focus.get("line")
            named.append(f"{name} at line {line}" if line else name)
        elif kind == "web":
            named.append(str(pane.get("url") or "a page"))
        elif kind in ("image", "video", "run"):
            named.append(pathlib.Path(str(pane.get("path") or "")).name or kind)
        else:
            named.append("the whiteboard" if kind == "board" else "a note")
    more = len(panes) - len(named)
    body = ", ".join(named) + (f", and {more} more" if more > 0 else "")
    where = ("on vesper's desktop" if str(s.get("desktop") or "vesper") == "vesper"
             else "here")
    seen = "showing" if s.get("visible") else "held back until you ask"
    return f"{seen} {where}: {body}"
