"""Showing something WHILE explaining it -- an ordered walk across the showcase.

THE OWNER'S ASK, 2026-09-15: *"can vesper actively show me stuff while explaning
something? [...] how can i keep going with it live [...] can it do these
capabilities whenever it thinks it's a good time to?"*

A DEMONSTRATION IS A SCRIPT, NOT A RECORDING. Each step carries one sentence and
one scene, and the two are published TOGETHER. That coupling is the whole point:
the failure this module exists to prevent is the one every screen-share has,
where the words are two slides ahead of the picture. `core/showcase.py` owns what
is on screen; this owns which step is current, and a step is not current until its
scene is published and its revision read back.

WHY A STEP IS WRITTEN AS A PATCH AND PUBLISHED AS A WHOLE SCENE. A demonstration
that rebuilt the scene from nothing each step would tear down the pane the owner
is reading in order to add an arrow to it, so a step DECLARES only what changes
and panes persist across steps. But the thing published is the fold of every step
so far -- `carried()` -- never a patch onto whatever happened to be on the screen.
Publishing patches live was the first version and it was wrong: what `check()`
verified and what `advance()` ran were two different scenes, and the check was
therefore worthless in exactly the case it existed for.

"WHENEVER IT THINKS IT'S A GOOD TIME TO" IS NOT A NEW RULE AND MUST NOT BECOME
ONE. `contracts/policy/interruption_budget.toml` already decides when VESPER may
take the owner's attention, and it already carries the exact distinction this
needs:

    [preparation]
    budgeted = false

Building a demonstration on VESPER's OWN Desktop, while the owner works on
theirs, is preparation -- it takes no attention and is charged nothing. REVEALING
it is an interruption and is charged like any other. So this module never decides
whether to interrupt; it asks `InterruptionBudget.allocate` with `prepared=True`
while hidden and `prepared=False` at the reveal, and does what it is told. A
second policy here would be a second answer to a question that already has one,
and the two would disagree within a month.

WHAT WAS SHOWN IS RECORDED, NOT REMEMBERED. Every advance appends the published
revision and the sentence to `shown`. "Show me exactly what you did" is then
answered from a ledger rather than from a claim -- which is this corpus's whole
posture about instruments reporting on themselves, applied to a surface that is
unusually easy to be confidently wrong about, because it LOOKS like it worked.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

from core import showcase

STATE = showcase.STATE
LEDGER = "demonstration.json"

# A demonstration that cannot be sat through is not one. Sixty steps at the
# default dwell is ten minutes of the owner's attention, which is past anything
# they asked for and well past what the budget would fund.
MAX_STEPS = 60
DEFAULT_DWELL_S = 6.0
MAX_DWELL_S = 120.0

RUNNING, HELD, DONE, IDLE = "running", "held", "done", "idle"
STATES = (RUNNING, HELD, DONE, IDLE)

_LOCK = threading.Lock()


def ledger_path(state_dir: pathlib.Path | None = None) -> pathlib.Path:
    # THROUGH THE SHOWCASE'S RESOLVER, so the gates' override moves this ledger
    # with the scene it describes. Two files that must agree and only one of them
    # obeying `VESPER_SHOWCASE_DIR` would have a check reading the owner's real
    # demonstration while publishing into a temp directory.
    return showcase.state_dir(state_dir) / LEDGER


def _read(state_dir: pathlib.Path | None = None) -> dict:
    try:
        got = json.loads(ledger_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = None
    if not isinstance(got, dict):
        return {"state": IDLE, "title": "", "steps": [], "at": 0, "shown": []}
    return got


def _write(rec: dict, state_dir: pathlib.Path | None = None) -> None:
    p = ledger_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def base() -> dict:
    """The empty showcase a demonstration starts from.

    A DEMONSTRATION DOES NOT INHERIT WHATEVER WAS ON SCREEN, and the first version
    did. Step 1 patched onto the live scene, so a demonstration that had been
    checked against an empty start ran against a screen holding somebody else's
    panes -- and refused, correctly, with a message about a mark pointing at a
    pane it had never heard of. The bug was not the refusal. It was that what was
    CHECKED and what was RUN were two different scenes, which makes the check
    worthless exactly when it matters.
    """
    return {"panes": [], "marks": [], "cursor": None, "why": "",
            "visible": False, "desktop": "vesper"}


def carried(steps, upto: int) -> dict:
    """The full scene after `upto` steps -- what step `upto` leaves on the screen.

    BUILT FROM THE SCRIPT, NEVER FROM THE SCREEN. This is the same fold `check`
    walks, so the scene a step publishes is the one its check passed on.
    """
    scene = base()
    for step in list(steps)[:max(0, int(upto))]:
        if isinstance(step, dict) and isinstance(step.get("scene"), dict):
            scene = {**scene, **step["scene"]}
    return scene


def check(steps) -> tuple[bool, str]:
    """Is this script demonstrable, and if not, why.

    EVERY STEP'S SCENE IS VALIDATED AT LOAD, not at the moment it is reached. A
    demonstration that dies on step nine in front of the owner has already cost
    them the eight steps they sat through; the bad news belongs before the first
    word is spoken.
    """
    if not isinstance(steps, (list, tuple)) or not steps:
        return False, "a demonstration has at least one step"
    if len(steps) > MAX_STEPS:
        return False, (f"{len(steps)} steps were asked for and the bound is "
                       f"{MAX_STEPS}; past that it is a session, not a "
                       f"demonstration")
    # NAMED `so_far` AND NOT `carried`: the module function of that name does
    # the same fold for the RUN, and one of them shadowing the other in the file
    # that must keep them identical is how they stop being identical.
    so_far = base()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"step {i + 1} is not a record"
        if not str(step.get("say") or "").strip():
            return False, (f"step {i + 1} shows something and says nothing; the "
                           f"owner asked to be shown things WHILE they are "
                           f"explained")
        dwell = step.get("dwell_s", DEFAULT_DWELL_S)
        try:
            dwell = float(dwell)
        except (TypeError, ValueError):
            return False, f"step {i + 1} dwells for {dwell!r}, which is not seconds"
        if not 0 < dwell <= MAX_DWELL_S:
            return False, (f"step {i + 1} dwells {dwell}s; a step lasts more than "
                           f"nothing and at most {MAX_DWELL_S}s")
        patch = step.get("scene") or {}
        if not isinstance(patch, dict):
            return False, f"step {i + 1}'s scene is not a record"
        # THE MERGE IS CHECKED, NOT THE PATCH. Step 4 may drop the pane step 2's
        # arrow points at, and each half is legal alone.
        #
        # AND THE SENTENCE IS SUPPLIED HERE THE WAY `advance` SUPPLIES IT. A check
        # that validated a scene with no `why` while the run publishes one with
        # the step's own sentence is a check of a scene that never runs -- which
        # is the fault `base()` was written about, one level up.
        so_far = {**so_far, **patch}
        so_far["why"] = str(step.get("why") or step.get("say") or "")
        ok, why = showcase.validate(so_far)
        if not ok:
            return False, f"step {i + 1} would leave the showcase wrong: {why}"
    return True, ""


def load(title: str, steps, *, why: str = "", state_dir=None) -> dict:
    """Hold a checked demonstration, ready and showing nothing yet."""
    ok, bad = check(steps)
    if not ok:
        return {"ok": False, "reason": bad}
    with _LOCK:
        rec = {"state": HELD, "title": str(title or "a demonstration"),
               "why": str(why or ""), "steps": list(steps), "at": 0, "shown": [],
               "interrupted": False}
        _write(rec, state_dir)
    return {"ok": True, "state": HELD, "steps": len(steps),
            "title": rec["title"],
            "line": f"{rec['title']}: {len(steps)} steps, ready and not yet shown"}


def state(state_dir=None) -> dict:
    """Where the demonstration is, in terms the owner can act on."""
    rec = _read(state_dir)
    steps = rec.get("steps") or []
    at = int(rec.get("at") or 0)
    st = str(rec.get("state") or IDLE)
    if st not in STATES:
        st = IDLE
    nxt = steps[at] if 0 <= at < len(steps) else None
    return {"state": st, "title": rec.get("title") or "", "at": at,
            "total": len(steps), "shown": list(rec.get("shown") or []),
            "interrupted": bool(rec.get("interrupted")),
            "next": (str(nxt.get("say")) if isinstance(nxt, dict) else None),
            "line": _line(st, rec.get("title") or "", at, len(steps))}


def _line(st: str, title: str, at: int, total: int) -> str:
    if st == IDLE:
        return "nothing is being demonstrated"
    if st == HELD:
        return f"{title} is ready: {total} steps, none shown yet"
    if st == DONE:
        return f"{title} finished: all {total} steps shown"
    return f"{title}: step {at} of {total}"


def advance(*, budget=None, period: str = "ACTIVE_SESSION",
            attention: str = "available", reveal: bool = True,
            verify: bool = True, state_dir=None) -> dict:
    """Show the next step, or say why it was not shown.

    THE BUDGET IS ASKED EVERY STEP AND NOT ONLY AT THE START. The owner's
    attention state changes mid-demonstration -- they take a call, they start
    typing -- and a demonstration that got permission once and then owned the
    screen for ten minutes is the exact behaviour `interruption_budget.toml`
    exists to prevent. A refused step does not end the demonstration: it HOLDS,
    and `resume()` picks it up where their attention comes back.
    """
    with _LOCK:
        rec = _read(state_dir)
        steps = rec.get("steps") or []
        at = int(rec.get("at") or 0)
        if not steps:
            return {"ok": False, "reason": "no demonstration is loaded"}
        if at >= len(steps):
            rec["state"] = DONE
            _write(rec, state_dir)
            return {"ok": True, "state": DONE, "at": at, "total": len(steps),
                    "line": f"{rec.get('title')} is finished"}
        step = steps[at]
        say = str(step.get("say") or "")

        # PREPARED WHILE HIDDEN, CHARGED AT THE REVEAL. This is the whole of
        # "whenever it thinks it's a good time to", and it is one line because
        # the policy already existed.
        if budget is not None:
            from core.interruption import Candidate
            cand = Candidate(candidate_id=f"demonstration.{at + 1}",
                             expected_value=0.8, decays=False,
                             interruption_cost=(0.3 if reveal else 0.0),
                             prepared=not reveal)
            out = budget.allocate([cand], period=period,
                                  attention_state=attention)
            if cand.candidate_id not in out.surfaced and cand.candidate_id not in out.prepared:
                rec["state"] = HELD
                rec["interrupted"] = True
                _write(rec, state_dir)
                return {"ok": False, "held": True, "state": HELD, "at": at,
                        "reason": ("your attention is spoken for, so vesper is "
                                   "holding the next step rather than taking it"),
                        "line": f"holding at step {at + 1} of {len(steps)}"}

        # THE WHOLE SCENE, FOLDED FROM THE SCRIPT. Not a patch onto the live
        # screen -- see `base()` for the day that difference cost.
        scene = carried(steps, at + 1)
        scene["why"] = str(step.get("why") or say)
        scene["visible"] = bool(reveal)
        scene.setdefault("desktop", "vesper")
        pub = showcase.publish(scene, state_dir)
        if not pub.get("ok"):
            # A STEP THAT DID NOT PUBLISH IS NOT A STEP THAT RAN. `at` does not
            # move, so a retry shows the step that was missed rather than the
            # one after it.
            why = f"step {at + 1} would not go on screen: {pub.get('reason')}"
            return {"ok": False, "state": str(rec.get("state") or HELD), "at": at,
                    "reason": why, "line": why}

        # A STEP IS NOT SHOWN UNTIL THE WINDOW SAYS IT DREW IT.
        #
        # `showcase.scene` verified and this did not, which meant the one path that
        # narrates to the owner was the one path that could claim a step it never
        # put on the screen. `at` does not move on a failure, so the next advance
        # retries the step the owner missed rather than the one after it -- a
        # demonstration that skips silently is worse than one that stops.
        drew = {"ok": True}
        if verify:
            drew = showcase.rendered(int(pub["revision"]), timeout_s=4.0,
                                     state_dir=state_dir)
            if not drew.get("ok"):
                rec["state"] = HELD
                _write(rec, state_dir)
                why = (f"step {at + 1} was published and the showcase did not "
                       f"report drawing it: {drew.get('reason')}")
                return {"ok": False, "published": True, "state": HELD, "at": at,
                        "revision": pub["revision"], "reason": why, "line": why}
        rec["at"] = at + 1
        rec["state"] = RUNNING if rec["at"] < len(steps) else DONE
        rec["interrupted"] = False
        shown = list(rec.get("shown") or [])
        shown.append({"step": at + 1, "say": say, "revision": pub.get("revision"),
                      "panes": pub.get("panes"), "marks": pub.get("marks"),
                      "revealed": bool(reveal)})
        rec["shown"] = shown[-MAX_STEPS:]
        _write(rec, state_dir)
    return {"ok": True, "state": rec["state"], "at": rec["at"],
            "total": len(steps), "say": say, "revision": pub.get("revision"),
            "dwell_s": float(step.get("dwell_s", DEFAULT_DWELL_S)),
            "line": f"step {rec['at']} of {len(steps)}: {say}"}


def interrupt(state_dir=None) -> dict:
    """Stop where it is, keeping the place.

    NOT A STOP AND NOT A RESET. The owner said something mid-demonstration; the
    right response is to fall silent with the screen intact, so that what they
    are looking at is still what was being discussed when they spoke.
    """
    with _LOCK:
        rec = _read(state_dir)
        if not (rec.get("steps") or []):
            return {"ok": False, "reason": "nothing is being demonstrated"}
        rec["state"] = HELD
        rec["interrupted"] = True
        _write(rec, state_dir)
    return {"ok": True, "state": HELD, "at": int(rec.get("at") or 0),
            "line": (f"held at step {rec.get('at')} of {len(rec.get('steps') or [])}"
                     f" -- the screen is left as it was")}


def resume(state_dir=None) -> dict:
    """Pick it up where their attention came back."""
    with _LOCK:
        rec = _read(state_dir)
        steps = rec.get("steps") or []
        if not steps:
            return {"ok": False, "reason": "nothing is being demonstrated"}
        if int(rec.get("at") or 0) >= len(steps):
            return {"ok": False, "reason": "that demonstration is finished"}
        rec["state"] = RUNNING
        rec["interrupted"] = False
        _write(rec, state_dir)
    return {"ok": True, "state": RUNNING, "at": int(rec.get("at") or 0),
            "line": f"carrying on from step {int(rec.get('at') or 0) + 1}"}


def stop(*, clear_screen: bool = True, state_dir=None) -> dict:
    """End it. The screen is cleared unless the owner is still reading it."""
    with _LOCK:
        rec = _read(state_dir)
        rec["state"] = IDLE
        rec["at"] = 0
        rec["steps"] = []
        rec["interrupted"] = False
        _write(rec, state_dir)
    if clear_screen:
        showcase.clear(state_dir, why="the demonstration ended")
    return {"ok": True, "state": IDLE, "line": "the demonstration is over"}


def transcript(state_dir=None) -> list:
    """Exactly what was shown, step by step, with the revision that proves it.

    THE ANSWER TO *"can vesper show me exactly what it did"*. Every row pairs a
    sentence with the published revision that carried it, so the claim and the
    artefact are the same record rather than two that have to be trusted to
    agree.
    """
    return list(_read(state_dir).get("shown") or [])
