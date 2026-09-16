"""One request, many capabilities, end to end -- and then read the world back.

THE OWNER, 2026-09-15: *"run some big multi steps checks to verify it works end to
end, ask vesper stuff that makes it go through multiple questions in one go, and
keep doing that until no questions are left."*

WHY THIS IS NOT A UNIT TEST AND MUST NOT BECOME ONE. Every gate in `tools/ci/`
drives one module against a fixture. This drives the WHOLE path on the REAL
running window: a sentence's worth of work at a time, through the parser that
turns a proposal into an action, the authorisation ladder that prices it, the
executor that runs it, the observation that crosses back, and the window that
either drew it or did not. Each of the three passes below answers one of the
owner's questions and refuses to answer it from anything but the surface's own
report.

  A. THE PARSER    -- can what the owner says even become one of these actions?
                      A capability the proposer cannot NAME is one VESPER can
                      never choose, which is how a whole subsystem has been
                      "built and reached by nothing" three times in this corpus.
  B. THE ACT PATH  -- authorised, levelled, executed, observed, compensated,
                      through the real registry rather than by calling the
                      function.
  C. THE SURFACE   -- the live window: panes, marks, the cursor, its own browser
                      driven end to end, the Desktop it is on, a demonstration
                      walked step by step, and the undo.

    python3.13 tools/showcase_endtoend.py            # all three, once
    python3.13 tools/showcase_endtoend.py --rounds 3 # and again, and again
    python3.13 tools/showcase_endtoend.py --pass C   # one pass
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAILED: list[str] = []
STEPS = 0


def check(ok: bool, what: str, detail: str = "") -> bool:
    global STEPS
    STEPS += 1
    mark = "  ok " if ok else "  ** "
    print(f"{mark}{what}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(f"{what}: {detail}")
    return ok


# --------------------------------------------------------------- A. the parser

# WHAT A PROPOSER WOULD RETURN for each of these sentences. Written by hand ON
# PURPOSE: the question this pass answers is whether the PARSER and the REGISTRY
# accept the shape, and a model in the loop would make a failure ambiguous
# between "the model phrased it oddly" and "the system cannot take it".
SENTENCES = [
    ("show me core/showcase.py at line 120",
     {"action": "showcase.scene", "why": "the owner asked to see that file at that line",
      "args": {"why": "core/showcase.py, at line 120",
               "panes": [{"id": "code", "kind": "code", "path": "core/showcase.py",
                          "focus": {"line": 120}}]}}),
    ("put that picture and the clip side by side",
     {"action": "showcase.scene", "why": "two things to look at together",
      "args": {"why": "the picture and the clip",
               "panes": [{"id": "pic", "kind": "image", "path": "~/Desktop/a.png"},
                         {"id": "vid", "kind": "video", "path": "~/Desktop/b.mp4",
                          "focus": {"at_s": 12}}]}}),
    ("point at the bit you changed",
     {"action": "showcase.point", "why": "the owner asked where",
      "args": {"pane": "code", "x": 0.5, "y": 0.4, "gesture": "tap",
               "mark": "ring", "at": [0.5, 0.4]}}),
    ("let me see it",
     {"action": "showcase.reveal", "why": "the owner asked to see it",
      "args": {"visible": True, "desktop": "vesper", "why": "here it is"}}),
    ("put that away",
     {"action": "showcase.reveal", "why": "the owner is done looking",
      "args": {"visible": False}}),
    ("look that up",
     {"action": "showcase.web", "why": "the owner asked for a page",
      "args": {"verb": "navigate", "url": "https://example.com"}}),
    ("what am i looking at",
     {"action": "showcase.follow", "why": "the owner asked what is in front of them",
      "args": {"what": "windows"}}),
    ("watch my screen",
     {"action": "showcase.follow", "why": "the owner asked to be followed",
      "args": {"what": "screen"}}),
]


def pass_a() -> None:
    print("\nA. can what the owner says become one of these actions?")
    from core import capabilities as C
    from core import intent as I

    reg = C.build_registry()
    for verb in ("showcase.scene", "showcase.point", "showcase.reveal", "showcase.web", "showcase.follow"):
        check(verb in I.KNOWN, f"{verb} is proposable at all")
        check(verb in I.CAN_DO, f"{verb} is something vesper can say about itself")
        check(verb in I.SYSTEM, f"{verb} is in the prompt the proposer reads")
        try:
            reg.get(verb)
            check(True, f"{verb} is in the live registry")
        except Exception as exc:                          # noqa: BLE001
            check(False, f"{verb} is in the live registry", repr(exc))

    for sentence, reply in SENTENCES:
        # THE PROPOSAL SAYS `action` AND THE RECORD SAYS `capability_id`. The
        # prompt asks the model for "action"; `intent.parse` maps it onto
        # `Proposal.capability_id`. This instrument asserted `.action` and died
        # on its first run -- the tool's bug, not the system's, and exactly what
        # `verify-instruments-before-asking-the-owner` is about.
        got = I.parse(json.dumps(reply))
        ok = got is not None and got.capability_id == reply["action"]
        check(ok, f"{sentence!r} parses to {reply['action']}",
              "dropped" if got is None else f"got {got.capability_id}")

    # AND AN INVENTED VERB IS STILL DROPPED. A parser that accepts everything is
    # not evidence that it accepts the right things.
    check(I.parse(json.dumps({"action": "show.explode", "args": {}, "why": "x"})) is None,
          "a show verb nobody registered is dropped before authorisation")


# ------------------------------------------------------------- B. the act path

def pass_b() -> None:
    print("\nB. authorised, levelled, executed, observed -- through the real path")
    import os
    import tempfile

    from core import capabilities as C

    prev = os.environ.get("VESPER_SHOWCASE_DIR")
    td = tempfile.mkdtemp(prefix="vesper-e2e-")
    os.environ["VESPER_SHOWCASE_DIR"] = td
    try:
        from core import showcase as SC
        # A stand-in window that reports drawing everything, so this pass is
        # about the LADDER rather than about the display. Pass C uses the real one.
        pathlib.Path(td, "showcase-said.json").write_text(json.dumps(
            {"open": True, "revision": 10 ** 9, "panes_drawn": ["code", "note", "site"],
             "marks_drawn": 3, "errors": []}), encoding="utf-8")

        reg = C.build_registry()
        ladder = [
            ("showcase.scene", {"why": "a file at a line", "panes": [
                {"id": "code", "kind": "code", "path": "README.md",
                 "focus": {"line": 3}}]}, "L1"),
            ("showcase.scene", {"why": "in front of the owner", "visible": True,
                            "desktop": "here", "panes": [
                                {"id": "note", "kind": "text", "text": "hi"}]}, "L3"),
            ("showcase.scene", {"why": "a secret", "panes": [
                {"id": "code", "kind": "code",
                 "path": "~/.config/vesper/secrets.env"}]}, "L5"),
            ("showcase.point", {"pane": "code", "x": 0.5, "y": 0.5}, None),
            ("showcase.reveal", {"visible": False}, "L1"),
            ("showcase.reveal", {"visible": True, "desktop": "vesper"}, "L1"),
            ("showcase.reveal", {"visible": True, "desktop": "here"}, "L3"),
            ("showcase.web", {"verb": "navigate", "url": "https://example.com"}, "L2"),
            ("showcase.web", {"verb": "click", "selector": "a"}, "L3"),
            ("showcase.web", {"verb": "type", "selector": "input",
                          "text": "OPENAI_API_KEY=sk-live-abc"}, "L5"),
            ("showcase.follow", {"what": "windows"}, "L2"),
            ("showcase.follow", {"what": "screen"}, "L4"),
        ]
        for verb, args, want in ladder:
            if want is None:
                continue
            # `declared_level`, NOT `.level`: the record's field is the function
            # itself. Second wrong guess this instrument made about an API it
            # never read -- both caught by running it, which is the argument for
            # running instruments before quoting them.
            got = reg.get(verb).declared_level(args)
            check(got == want, f"{verb} {json.dumps(args)[:52]}… is {want}", f"got {got}")

        # THE POINT VERB'S LEVEL DEPENDS ON WHERE THE SCENE IS, NOT ONLY ON ITS
        # ARGUMENT. This is the hole the advisor found: revealed onto the owner's
        # Desktop once, every later arrow was priced as if it were on VESPER's.
        SC.publish({"why": "on vesper's", "visible": True, "desktop": "vesper",
                    "panes": [{"id": "code", "kind": "text", "text": "x"}]})
        cheap = reg.get("showcase.point").declared_level({"pane": "code", "x": 0.5, "y": 0.5})
        SC.publish({"why": "on the owner's", "visible": True, "desktop": "here",
                    "panes": [{"id": "code", "kind": "text", "text": "x"}]})
        dear = reg.get("showcase.point").declared_level({"pane": "code", "x": 0.5, "y": 0.5})
        check(cheap == "L1" and dear == "L3",
              "pointing costs what the SCREEN costs, not what the argument says",
              f"on vesper's {cheap}, on the owner's {dear}")

        # EXTERNAL EFFECT AND REVERSIBILITY, declared rather than assumed.
        web = reg.get("showcase.web")
        check(bool(getattr(web, "external_effect", False)),
              "driving a page is declared an external effect, so the outbox covers it")
        scene = reg.get("showcase.scene")
        check(str(getattr(scene, "reversibility", "")) == "reversible",
              "putting something on the showcase is reversible")

        # WHAT CROSSES BACK IS THE RECEIPT, BOUNDED -- never the file's contents.
        obs = C.observe("showcase.scene", {}, {"ok": True, "revision": 4,
                                           "panes_drawn": ["code"], "marks_drawn": 2})
        check(obs.get("panes_drawn") == ["code"] and obs.get("revision") == 4,
              "the observation carries which panes drew")
        body = json.dumps(obs)
        check("kind" not in body and "path" not in body,
              "the observation does not carry the scene's own content back")
        webobs = C.observe("showcase.web", {}, {"ok": True, "url": "https://x", "title": "T",
                                            "text": "y" * 9000})
        check(len(json.dumps(webobs)) < 9000,
              "a page's text is bounded before it reaches the planner",
              f"{len(json.dumps(webobs))} chars")
        check(C.observation_trust("showcase.web") == C.EXTERNAL,
              "a page vesper drove is external content")
        check(C.observation_trust("showcase.scene") == "verified_local",
              "the surface's own receipt is not external content")
    finally:
        if prev is None:
            os.environ.pop("VESPER_SHOWCASE_DIR", None)
        else:
            os.environ["VESPER_SHOWCASE_DIR"] = prev


# --------------------------------------------------------------- C. the surface

def pass_c() -> None:
    print("\nC. the live window -- panes, marks, its own browser, its own Desktop")
    from core import capabilities as C
    from core import demonstration as D
    from core import showcase as SC

    if not SC.said().get("open"):
        check(False, "the showcase window is open", "VESPER is not running")
        return

    # 1. A FILE AT A LINE, A NOTE, AND A BROWSER -- built hidden, on its Desktop.
    one = C.showcase_scene({
        "why": "an end-to-end run: a file at a line, a note, and vesper's browser",
        "visible": False, "desktop": "vesper",
        "panes": [
            {"id": "code", "kind": "code", "path": "core/showcase.py",
             "title": "core/showcase.py", "focus": {"line": 120, "before": 10, "after": 30}},
            {"id": "note", "kind": "text", "title": "what this is",
             "text": "built while you were working, on vesper's desktop, hidden."},
            {"id": "site", "kind": "web", "url": "https://example.com", "span": 2},
        ],
        "marks": [{"kind": "arrow", "pane": "code", "from": [0.05, 0.08],
                   "anchor": {"pane": "code", "line": 120}}],
    })
    check(one.get("ok"), "a three-pane scene drew", str(one.get("reason"))[:90])
    check(sorted(one.get("panes_drawn") or []) == ["code", "note", "site"],
          "every pane appeared", str(one.get("panes_drawn")))
    said = SC.said()
    check(not said.get("visible"), "and it is HIDDEN while the owner works")
    # WHICHEVER IS TRUE, ASSERTED. The home only creates its ground on a Desktop with
    # none of the owner's windows on it, so "on VESPER's Desktop" is a state the
    # machine may not be in -- and a test that demanded it would be demanding the
    # owner rearrange their session.
    awaiting = bool(said.get("awaiting_desktop"))
    if awaiting:
        check(True, "vesper has no Desktop of its own yet -- the ground waits for an empty one",
              "the scene is built and held")
    else:
        check(bool(said.get("on_vespers_desktop")),
              "on VESPER's Desktop, not the owner's", f"window {said.get('window_id')}")

    # 2. ITS OWN CURSOR AND AN ARROW, placed on a pane that is there.
    pt = C.showcase_point({"pane": "code", "x": 0.4, "y": 0.35, "gesture": "tap",
                       "mark": "ring", "at": [0.4, 0.35]})
    check(pt.get("ok"), "vesper's own cursor moved and left a ring", str(pt.get("reason"))[:80])
    check(not C.showcase_point({"pane": "not-there"}).get("ok"),
          "pointing at a pane that is not on the showcase is refused")
    check(not C.showcase_point({"pane": "code", "on": "here"}).get("ok"),
          "vesper refuses to draw on the screen the owner is working on")

    # 3. DRIVING ITS OWN BROWSER, END TO END, READ BACK AT EVERY STEP.
    time.sleep(1.2)
    steps = [
        ({"verb": "navigate", "url": "https://example.com"}, True),
        ({"verb": "wait_for", "contains": "Example Domain", "timeout_ms": 8000}, True),
        ({"verb": "read", "selector": "h1"}, True),
        ({"verb": "wait_for", "contains": "zzz-not-on-this-page", "timeout_ms": 1500}, False),
        ({"verb": "click", "selector": "a"}, True),
        ({"verb": "click", "selector": "#nothing-matches-this"}, False),
        ({"verb": "explode"}, False),
    ]
    for args, want in steps:
        got = C.showcase_web(args)
        check(bool(got.get("ok")) == want,
              f"browser: {args['verb']} {'succeeds' if want else 'is refused'}",
              str(got.get("reason") or got.get("title"))[:70])
    h1 = C.showcase_web({"verb": "read", "selector": "h1"})
    check("Example Domain" in str(h1.get("text") or ""),
          "and it read the page's own heading back", str(h1.get("text"))[:50])

    # 4. FOLLOWING THE OWNER -- and saying WHICH of the two things it means.
    win = C.showcase_follow({"what": "windows"})
    check(win.get("ok"), "following the owner's windows")
    check("screen recording grant" in str(win.get("not_seen") or ""),
          "and saying plainly what that does NOT include")
    scr = C.showcase_follow({"what": "screen"})
    grant = (SC.said().get("grants") or {}).get("screen_recording")
    if grant == "granted":
        check(scr.get("ok"), "following the owner's screen", str(scr.get("reason"))[:80])
        check(bool(scr.get("shot")), "and it took a real frame", str(scr.get("size")))
    else:
        check(not scr.get("ok"),
              "the screen is refused honestly while the grant is missing",
              f"grant={grant}")
        check(scr.get("fallback", {}).get("args", {}).get("what") == "windows",
              "and it names the thing it CAN do instead")

    # 5. A DEMONSTRATION, WALKED, AND ITS TRANSCRIPT.
    script = [
        {"say": "this is the file that decides what a scene is", "dwell_s": 2,
         "scene": {"panes": [{"id": "code", "kind": "code", "path": "core/showcase.py",
                              "title": "core/showcase.py", "focus": {"line": 60}}]}},
        {"say": "and this is the bound that refuses instead of truncating", "dwell_s": 2,
         "scene": {"marks": [{"kind": "arrow", "pane": "code", "from": [0.05, 0.1],
                              "anchor": {"pane": "code", "line": 64}}]}},
        {"say": "the whiteboard comes up beside it", "dwell_s": 2,
         "scene": {"panes": [{"id": "code", "kind": "code", "path": "core/showcase.py",
                              "title": "core/showcase.py", "focus": {"line": 60}},
                             {"id": "board", "kind": "board", "title": "whiteboard"}],
                   "marks": []}},
    ]
    check(D.load("an end-to-end demonstration", script).get("ok"), "a demonstration loads")
    for i in range(1, len(script) + 1):
        out = D.advance(reveal=True)
        check(out.get("ok"), f"step {i} showed and the window confirmed it",
              str(out.get("reason") or out.get("say"))[:70])
    check(D.advance(reveal=True).get("state") == D.DONE, "the demonstration finished")
    rows = D.transcript()
    check(len(rows) == len(script) and all(r.get("revision") for r in rows),
          "and every step it showed is recorded with the revision that proves it",
          f"{len(rows)} rows")

    # 6. REVEALED, THEN PUT BACK THE WAY IT WAS.
    rev = C.showcase_reveal({"visible": True, "desktop": "vesper",
                         "why": "here is what it did"})
    if bool(SC.said().get("awaiting_desktop")):
        check(not rev.get("ok") and rev.get("flag_id") == "showcase.no_desktop_yet",
              "a reveal with no Desktop of its own refuses instead of claiming a screen",
              str(rev.get("reason"))[:70])
        check((rev.get("repair") or {}).get("args", {}).get("desktop") == "here",
              "and it names what would work instead")
        here = C.showcase_reveal({"visible": True, "desktop": "here", "why": "on yours then"})
        check(here.get("ok") and here.get("visible"),
              "and it CAN come to the owner's desktop when asked", str(here.get("reason"))[:60])
    else:
        check(rev.get("ok") and rev.get("visible"), "revealed on vesper's desktop")
        check(bool(rev.get("on_vespers_desktop")),
              "and the window itself confirms which Desktop it is on")
    before = [p.get("id") for p in (SC.current().get("panes") or [])]
    last = C.showcase_scene({"why": "something else entirely",
                         "panes": [{"id": "other", "kind": "text", "text": "different"}]})
    undo = C.showcase_scene_compensate({}, last)
    after = [p.get("id") for p in (SC.current().get("panes") or [])]
    check(undo.get("compensated") and after == before,
          "and the undo puts back exactly what the owner was looking at",
          f"{before} -> {after}")

    # 7. AND IT GOES AWAY WHEN TOLD.
    away = C.showcase_reveal({"visible": False, "why": "done"})
    check(away.get("ok") and not away.get("visible"), "put away on request")
    check(not SC.said().get("visible"), "and the window agrees it is hidden")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--pass", dest="which", choices=["A", "B", "C"], action="append")
    args = ap.parse_args()
    which = args.which or ["A", "B", "C"]
    for n in range(1, args.rounds + 1):
        if args.rounds > 1:
            print(f"\n{'=' * 72}\nROUND {n} of {args.rounds}\n{'=' * 72}")
        if "A" in which:
            pass_a()
        if "B" in which:
            pass_b()
        if "C" in which:
            pass_c()
    print(f"\n{'-' * 72}")
    if FAILED:
        print(f"{len(FAILED)} of {STEPS} checks failed:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print(f"all {STEPS} checks passed, end to end, on the running window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
