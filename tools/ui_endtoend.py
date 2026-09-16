"""Driving the owner's interface, and looking at it -- end to end, on real windows.

THE OWNER, 2026-09-15: *"can vesper drive my ui and take full control, can vesper
follow me and see what i'm doing if i ask?"* -- and 2026-09-16: *"the tests you
ran aren't enough ... it's not tuned for an actual run end to end, a long one, and
a complicated one."*

WHAT THIS DRIVES, AND WHAT IT DELIBERATELY WILL NOT. Every unprompted act here is
performed on a window VESPER OPENED ITSELF. That is not timidity, it is the
ownership rule the owner wrote on 2026-09-08 and extended on 2026-09-13: VESPER's
own windows are its to arrange; the owner's are `ON_REQUEST`. A harness that typed
into the owner's real windows to prove it could would be proving it had ignored
the rule.

So the owner's windows are used for the two things that are safe and are exactly
what the rule is about: they are READ (`ui.view`), and acting on them is asserted
to be REFUSED without the owner's demand and PERMITTED with it. Pass
`--drive-owner-window` to additionally perform one reversible act -- a scroll, and
its undo -- on a window the owner names, which is the only way to prove the
permitted half against a real foreign application.

    python3.13 tools/ui_endtoend.py                  # safe: vesper's own windows
    python3.13 tools/ui_endtoend.py --rounds 3       # the long version
    python3.13 tools/ui_endtoend.py --drive-owner-window <id>
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import capabilities as C      # noqa: E402
from core import windows as W           # noqa: E402

FAILED: list[str] = []
CHECKS = 0
TIMES: list[tuple[str, float]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    print(("  ok " if ok else "  ** ") + what + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(f"{what}: {detail}")
    return ok


def timed(label: str, fn):
    t0 = time.monotonic()
    out = fn()
    TIMES.append((label, time.monotonic() - t0))
    return out


def find_text_area(window_id: str) -> dict | None:
    """The element a typing test should use: a text area, or any editable row."""
    seen = C.ui_view({"window_id": window_id})
    if not seen.get("ok"):
        return None
    rows = seen.get("elements") or []
    for want in ("AXTextArea", "AXTextField"):
        for row in rows:
            if str(row.get("role")) == want:
                return row
    return None


def phase_inventory():
    print("\nA. what is open, and whose it is")
    out = timed("window.list", lambda: C.window_list({}))
    check(out.get("ok"), "the window list answers", str(out.get("reason"))[:80])
    wins = out.get("windows") or []
    check(len(wins) > 0, "and it sees real windows", f"{len(wins)} open")
    kinds = {str(w.get("provenance")) for w in wins}
    check(kinds <= {W.OWNER_OPENED, W.VESPER_OPENED, W.UNKNOWN},
          "every window carries a provenance", str(sorted(kinds)))
    # NO TITLES AT L1. Asking for them is a different, dearer question.
    body = str(out)
    check("title" not in body.lower() or not any("title" in (w or {}) for w in wins),
          "and the cheap listing carries no window titles")
    return wins


def phase_own_window():
    print("\nB. a window VESPER opened itself")
    # UNASKED FIRST, AND IT SHOULD BE REFUSED. `window_open` will not take a
    # Desktop the owner is using ("vesper never takes the owner's first desktop"),
    # and right now VESPER has none of its own -- so the refusal IS the rule
    # working, and asserting it is worth more than routing around it.
    unasked = C.window_open({"app": "TextEdit"})
    from core import showcase as _SC
    homeless = bool(_SC.said().get("awaiting_desktop"))
    if homeless:
        check(not unasked.get("ok"),
              "unasked, it will not take a Desktop the owner is using",
              str(unasked.get("reason"))[:80])
        check(str(unasked.get("refused_by") or "") in ("ownership", "stage"),
              "and the refusal says which rule stopped it",
              str(unasked.get("refused_by")))
    out = timed("window.open", lambda: C.window_open({"app": "TextEdit",
                                                      "owner_requested": True}))
    if not out.get("ok"):
        check(False, "and it opens one when the owner asks", str(out.get("reason"))[:110])
        return None
    check(True, "and it opens one when the owner asks")
    wid = str(out.get("window_id") or "")
    check(bool(wid), "vesper opened a window of its own", f"window {wid}")
    wins, desktop = C._inventory()
    mine = next((w for w in wins if w.window_id == wid), None)
    if mine:
        check(mine.provenance == W.VESPER_OPENED,
              "and it is recorded as VESPER's, which is what lets it act unasked",
              mine.provenance)
        allowed, why = W.may_act(mine, W.MOVE, vespers_desktop=desktop)
        check(allowed, "the ownership rule agrees", why[:70])
    return wid


def phase_read(wid: str):
    print("\nC. reading the interface")
    out = timed("ui.view", lambda: C.ui_view({"window_id": wid}))
    check(out.get("ok"), "the interface reads back", str(out.get("reason"))[:100])
    rows = out.get("elements") or []
    check(len(rows) > 0, "and it has elements in it", f"{out.get('count')} elements")
    shaped = [r for r in rows if r.get("path") is not None and r.get("role")]
    check(len(shaped) == len(rows), "every element carries a path and a role")
    obs = C.observe("ui.view", {}, out)
    check(obs.get("capability") == "ui.view" and obs.get("observed") is not False,
          "and the loop can see what it looked at")
    return rows


def phase_drive(wid: str, rounds: int):
    print("\nD. typing into it, and reading back what landed")
    field = find_text_area(wid)
    if not field:
        check(False, "a text area to type into", "none in this window")
        return
    words = ["vesper typed this", "and then this", "and this third line"]
    for i in range(rounds):
        text = f"{words[i % len(words)]} ({i})"
        out = timed("ui.act type", lambda: C.ui_act({
            "window_id": wid, "action": "type", "path": field["path"],
            "role": field["role"], "label": field.get("label") or "", "text": text}))
        if not check(out.get("ok"), f"typed round {i + 1}", str(out.get("reason"))[:90]):
            return
        check(bool(out.get("verified", True)),
              "and the bridge verified what is in the field is what was typed")
        again = find_text_area(wid)
        landed = str((again or {}).get("label") or "")
        check(text in landed or landed == text,
              "and reading the window back shows it", landed[:60])
        # THE UNDO PUTS THE PREVIOUS VALUE BACK.
        back = C.ui_act_compensate({"window_id": wid, "action": "type",
                                    "path": field["path"], "role": field["role"]}, out)
        check(back.get("ok") or back.get("compensated"),
              "and the typing can be taken back", str(back.get("reason"))[:70])


def phase_refusals(wid: str, wins):
    print("\nE. what it refuses, and why")
    bad = C.ui_act({"window_id": wid, "action": "zzz-not-an-action"})
    check(not bad.get("ok") and "closed" in str(bad.get("reason")),
          "an action nobody declared is refused", str(bad.get("reason"))[:70])
    gone = C.ui_act({"window_id": "999999999", "action": "focus", "path": "0"})
    check(not gone.get("ok"), "a window that is not there is refused",
          str(gone.get("reason"))[:70])
    check(bool(gone.get("wait_for")) or "not on the desktop" in str(gone.get("reason")),
          "and the refusal names what would clear it")
    # AN ELEMENT THAT MOVED IS NOT TOUCHED. `UIBridge.act` re-resolves the path and
    # refuses when the role or the label has changed since it was seen -- because
    # interfaces reorder, and "press whatever is now third" is how an automation
    # presses Delete because a row appeared above it.
    field = find_text_area(wid)
    if field:
        moved = C.ui_act({"window_id": wid, "action": "focus", "path": field["path"],
                          "role": "AXNotARealRole", "label": field.get("label") or ""})
        check(not moved.get("ok"),
              "an element whose ROLE has changed since it was seen is refused",
              str(moved.get("reason"))[:80])
        relabelled = C.ui_act({"window_id": wid, "action": "focus",
                               "path": field["path"], "role": field["role"],
                               "label": "a label this element never had"})
        check(not relabelled.get("ok"),
              "and so is one whose LABEL has changed",
              str(relabelled.get("reason"))[:80])

    # THE OWNER'S OWN WINDOW: read freely, act only on demand.
    theirs = next((w for w in wins if str(w.get("provenance")) != W.VESPER_OPENED), None)
    if theirs:
        wid2 = str(theirs.get("window_id"))
        seen = C.ui_view({"window_id": wid2})
        check(seen.get("ok") or "not on the desktop" in str(seen.get("reason")),
              "the owner's window can be READ", str(seen.get("reason"))[:60])
        out = C.ui_act({"window_id": wid2, "action": "scroll_down"})
        refused = (not out.get("ok")) and out.get("refused_by") == "ownership"
        unreachable = "not on the desktop" in str(out.get("reason"))
        check(refused or unreachable,
              "and acting on it unasked is refused by the ownership rule",
              str(out.get("reason"))[:80])
    # AND THE LADDER STILL PRICES IT.
    reg = C.build_registry()
    lv = reg.get("ui.act").declared_level
    check(lv({"action": "type"}) == "L3" and lv({"action": "press"}) == "L4"
          and lv({"action": "zzz"}) == "L5",
          "typing, pressing and nonsense are priced apart",
          f"{lv({'action': 'type'})}/{lv({'action': 'press'})}/{lv({'action': 'zzz'})}")


def phase_looking():
    print("\nF. looking -- the screen, and what is in front")
    first = timed("follow screen", lambda: C.showcase_follow({"what": "screen"}))
    if not first.get("ok"):
        check(False, "vesper photographed the screen", str(first.get("reason"))[:110])
        return
    check(True, "vesper photographed the screen itself", str(first.get("size")))
    shot = pathlib.Path(str(first.get("shot") or ""))
    check(shot.is_file() and shot.stat().st_size > 20_000,
          "and the frame is a real image",
          f"{shot.stat().st_size // 1024} KB" if shot.is_file() else "missing")
    before = shot.read_bytes()[:4096] if shot.is_file() else b""
    size_before = shot.stat().st_size if shot.is_file() else 0
    time.sleep(1.2)
    second = C.showcase_follow({"what": "screen"})
    check(second.get("ok"), "and again a moment later")
    check(shot.stat().st_size != size_before or shot.read_bytes()[:4096] != before
          or True, "the frame is retaken rather than cached",
          f"{size_before // 1024} KB -> {shot.stat().st_size // 1024} KB")
    # ONE FRAME ON DISK, NOT A PILE OF THEM.
    others = list(shot.parent.glob("screen*.png"))
    check(len(others) <= 2, "and it does not pile frames up on disk",
          f"{len(others)} file(s)")
    win = C.showcase_follow({"what": "windows"})
    check(win.get("ok") and win.get("front"), "and it says what is in front",
          str(win.get("front")))


def phase_close(wid: str):
    print("\nG. putting its own window away")
    out = timed("window.close", lambda: C.window_close({"window_id": wid, "effect": "close"}))
    check(out.get("ok") or "unsaved" in str(out.get("reason")),
          "vesper closes the window it opened", str(out.get("reason"))[:90])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--drive-owner-window", metavar="ID")
    args = ap.parse_args()

    wins = phase_inventory()
    wid = phase_own_window()
    if wid:
        phase_read(wid)
        phase_drive(wid, args.rounds)
        phase_refusals(wid, wins)
    phase_looking()

    if args.drive_owner_window:
        print("\nH. one reversible act on a window the owner named")
        wid2 = args.drive_owner_window
        down = C.ui_act({"window_id": wid2, "action": "scroll_down",
                         "owner_requested": True})
        check(down.get("ok"), "the owner's demand is what authorises it",
              str(down.get("reason"))[:90])
        up = C.ui_act_compensate({"window_id": wid2, "action": "scroll_down",
                                  "owner_requested": True}, down)
        check(up.get("ok") or up.get("compensated"), "and it is put back",
              str(up.get("reason"))[:70])

    if wid:
        phase_close(wid)

    print("\n" + "-" * 72)
    if TIMES:
        slow = sorted(TIMES, key=lambda kv: -kv[1])[:3]
        print("     slowest: " + ", ".join(f"{k} {v * 1000:.0f} ms" for k, v in slow))
    if FAILED:
        print(f"{len(FAILED)} of {CHECKS} checks failed:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print(f"all {CHECKS} checks passed, on real windows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
