"""A LONG, CROWDED, CONCURRENT run at the showcase -- the workout the gates are not.

THE OWNER, 2026-09-16: *"the tests you ran aren't enough, they maybe good to check
baseline and code syntax, but i don't think they are enough to ensure it's ready
... it's not tuned for an actual run end to end, a long one, and a complicated
one."*

That is correct, and the distinction is worth stating precisely. `tools/ci/`
drives one module against a fixture. `tools/showcase_endtoend.py` drives the real
window through a SHORT, TIDY sequence: one thing at a time, nothing else writing,
nothing under load, finished in a minute. Both answer "does this work once, alone,
on a good day". Neither answers:

  * does it still answer after thousands of operations
  * does it hold up with eight panes, two live browsers and a growing run at once
  * what happens when a demonstration, an act and the owner's own buttons all
    write in the same second
  * does it leak -- memory, temp files, unbounded state, revisions
  * does a bad pane (missing file, dead host, a megabyte of text) take it down
  * does it come back when the owner closes the window, or when VESPER restarts
  * and how FAST is it, measured rather than felt

EVERY PHASE ASSERTS AND MEASURES. A soak that only watches for a crash is a soak
that reports success for a surface which quietly stopped drawing an hour ago -- so
a watchdog samples the window's own heartbeat, its CPU and its memory throughout,
and any stall is a failure with the second it happened.

    python3.13 tools/showcase_soak.py              # the full workout, ~6-9 min
    python3.13 tools/showcase_soak.py --quick      # a third of the load
    python3.13 tools/showcase_soak.py --phase C    # one phase, repeatable
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import capabilities as C            # noqa: E402
from core import demonstration as D           # noqa: E402
from core import showcase as SC               # noqa: E402

FAILED: list[str] = []
NOTES: list[str] = []
CHECKS = 0
LATENCIES: list[float] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILED.append(f"{what}" + (f" [{detail}]" if detail else ""))
        print(f"  ** {what}" + (f"  [{detail}]" if detail else ""))
    return ok


def note(line: str) -> None:
    NOTES.append(line)
    print(f"     {line}")


def home_pid() -> int | None:
    out = subprocess.run(["pgrep", "-f", "VESPER --home"],
                         capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def sample(pid: int) -> tuple[float, float]:
    """(cpu SECONDS used so far, resident MB) for the home process, or (-1, -1).

    CPU TIME, NOT `ps %cpu` -- AND THE FIRST VERSION OF THIS HARNESS GOT IT WRONG.
    On macOS `%cpu` is a decaying average over roughly the last minute, so the
    soak's own load bled into the sample it took at the START and this reported
    "idle: 31% cpu" for a process that was sitting at 3.5%. An instrument's
    self-report is not evidence: the honest measure is CPU time consumed between
    two readings, divided by the wall time between them, which is what the caller
    does with this.
    """
    try:
        out = subprocess.run(["ps", "-o", "cputime=,rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5).stdout.split()
        clock, rss = out[0], out[1]
        parts = [float(x) for x in clock.replace("-", ":").split(":")]
        secs = 0.0
        for part in parts:
            secs = secs * 60 + part
        return secs, float(rss) / 1024.0
    except (ValueError, IndexError, subprocess.SubprocessError):
        return -1.0, -1.0


class Watchdog(threading.Thread):
    """Is the window still alive, and what is it costing, THROUGHOUT.

    A SOAK THAT ONLY CHECKS AT THE END CANNOT SAY WHEN SOMETHING DIED. This samples
    the readback's own modification time -- the window rewrites it every tick -- so
    a stall is caught within seconds and reported with the phase it happened in.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.halt = threading.Event()
        self.stalls: list[str] = []
        self.cpu: list[float] = []
        self.rss: list[float] = []
        self.rss_at: list[float] = []
        self.rss_phase: list[str] = []
        self.last_cpu: float | None = None
        self.last_at = 0.0
        self.revisions: list[int] = []
        self.phase = "start"
        self.pid = home_pid()

    def run(self):
        # MTIME IS A WEAK HEARTBEAT AND THE THRESHOLD SAYS SO. `replaceItemAt`
        # preserves the original file's modification date, so an idle window that is
        # perfectly alive can leave mtime still for seconds at a time. Twelve seconds
        # is loose enough not to invent a stall and tight enough to catch a real one.
        # The stronger liveness signal is the process sampling below, which
        # re-resolves the pid when it disappears -- so a restart is measured rather
        # than mistaken for a death.
        said = SC.said_path()
        last_seen = 0.0
        last_change = time.monotonic()
        while not self.halt.is_set():
            try:
                mtime = said.stat().st_mtime
            except OSError:
                mtime = 0.0
            if mtime != last_seen:
                last_seen = mtime
                last_change = time.monotonic()
            elif time.monotonic() - last_change > 12.0:
                self.stalls.append(f"{self.phase}: the window stopped writing its "
                                   f"readback for {time.monotonic() - last_change:.0f}s")
                last_change = time.monotonic()
            if self.pid:
                c, m = sample(self.pid)
                now = time.monotonic()
                if c < 0:
                    # THE PROCESS RESTARTED UNDER US, and a watchdog holding the old
                    # pid stops measuring without saying so. Phase H restarts VESPER
                    # deliberately, and it runs BEFORE the sustained phase -- so the
                    # one phase written to catch a leak ran with no samples at all,
                    # while the report still printed a slope as if it had. Measured
                    # 2026-09-16: "over 99s" for a twelve-minute run.
                    self.pid = home_pid()
                    self.last_cpu = None
                if c >= 0:
                    if self.last_cpu is not None and now > self.last_at:
                        used = (c - self.last_cpu) / (now - self.last_at) * 100.0
                        self.cpu.append(max(0.0, used))
                    self.last_cpu, self.last_at = c, now
                    self.rss.append(m)
                    self.rss_at.append(now)
                    self.rss_phase.append(self.phase)
            try:
                self.revisions.append(int(SC.said().get("revision") or -1))
            except Exception:                               # noqa: BLE001
                pass
            self.halt.wait(2.0)


def drew(scene: dict, why: str) -> dict:
    """Publish through the real act and time it."""
    t0 = time.monotonic()
    out = C.showcase_scene(scene)
    LATENCIES.append(time.monotonic() - t0)
    if not out.get("ok") and not out.get("superseded"):
        check(False, why, str(out.get("reason"))[:110])
    return out


# ------------------------------------------------------------------ the phases

def phase_a(_):
    """Idle. The baseline everything else is compared against."""
    print("\nA. idle -- is it alive when nothing is asking?")
    pid = home_pid()
    check(pid is not None, "the home is running")
    if not pid:
        return
    before = SC.said_path().stat().st_mtime if SC.said_path().exists() else 0
    time.sleep(6)
    after = SC.said_path().stat().st_mtime
    check(after > before, "the window writes its own heartbeat while idle",
          f"{after - before:.1f}s of movement")
    c, m = sample(pid)
    note(f"idle: {c:.1f}% cpu, {m:.0f} MB resident")


def phase_b(quick):
    """Crowded: every pane kind at once, marks on each, a cursor."""
    print("\nB. crowded -- eight panes of every kind, marks on each")
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "run.log").write_text("the run is going\n" * 20, encoding="utf-8")
    img = REPO / "docs" / "design"
    picture = next((p for p in img.rglob("*.png")), None) if img.is_dir() else None
    panes = [
        {"id": "codeA", "kind": "code", "path": "core/showcase.py",
         "focus": {"line": 120}, "title": "showcase.py"},
        {"id": "codeB", "kind": "code", "path": "core/demonstration.py",
         "focus": {"line": 60}, "title": "demonstration.py"},
        {"id": "note", "kind": "text", "text": "a note " * 400, "focus": {"find": "note"}},
        {"id": "run", "kind": "run", "path": str(tmp / "run.log")},
        {"id": "board", "kind": "board"},
        {"id": "siteA", "kind": "web", "url": "https://example.com"},
        {"id": "siteB", "kind": "web", "url": "https://example.org"},
    ]
    if picture:
        panes.append({"id": "pic", "kind": "image", "path": str(picture)})
    marks = [{"kind": "arrow", "pane": "codeA", "from": [0.05, 0.1],
              "anchor": {"pane": "codeA", "line": 120}},
             {"kind": "ring", "pane": "note", "at": [0.4, 0.4]},
             {"kind": "ink", "pane": "board",
              "points": [[i / 40, (i % 7) / 7] for i in range(40)]},
             {"kind": "label", "pane": "run", "at": [0.2, 0.2], "text": "here"}]
    out = drew({"why": "everything at once", "visible": False, "desktop": "vesper",
                "panes": panes, "marks": marks,
                "cursor": {"pane": "codeA", "x": 0.5, "y": 0.4, "visible": True}},
               "a crowded scene drew")
    asked = {p["id"] for p in panes}
    got = set(out.get("panes_drawn") or [])
    check(asked <= got, "every one of the panes appeared", f"missing {sorted(asked - got)}")
    check(int(out.get("marks_drawn") or 0) >= len(marks),
          "and every mark with it", f"{out.get('marks_drawn')} of {len(marks)} + cursor")
    note(f"{len(panes)} panes and {len(marks)} marks drew in {LATENCIES[-1] * 1000:.0f} ms")
    # TWO LIVE BROWSERS, DRIVEN INDEPENDENTLY.
    for pane, word in (("siteA", "Example Domain"), ("siteB", "Example Domain")):
        got = C.showcase_web({"verb": "wait_for", "pane": pane, "contains": word,
                              "timeout_ms": 12000})
        check(got.get("ok"), f"the {pane} browser loaded on its own",
              str(got.get("reason"))[:70])
    a = C.showcase_web({"verb": "read", "pane": "siteA", "selector": "h1"})
    b = C.showcase_web({"verb": "read", "pane": "siteB", "selector": "h1"})
    check(a.get("ok") and b.get("ok"), "and both read back independently")


def phase_c(quick):
    """Churn: hundreds of scenes as fast as the act will take them."""
    n = 40 if quick else 120
    print(f"\nC. churn -- {n} scenes back to back")
    bad = 0
    superseded = 0
    t0 = time.monotonic()
    for i in range(n):
        t1 = time.monotonic()
        out = C.showcase_scene({
            "why": f"churn {i}", "visible": False, "desktop": "vesper",
            "panes": [{"id": "a", "kind": "text", "text": f"scene {i}"},
                      {"id": "b", "kind": "code", "path": "core/showcase.py",
                       "focus": {"line": 40 + (i % 200)}}],
            "marks": [{"kind": "ring", "pane": "a", "at": [(i % 10) / 10, 0.5]}]})
        # EVERY ACT IS TIMED, not just the tidy ones: a latency figure drawn from
        # four hand-picked calls describes nothing.
        LATENCIES.append(time.monotonic() - t1)
        if out.get("superseded"):
            superseded += 1
        elif not out.get("ok"):
            bad += 1
            if bad <= 3:
                check(False, f"churn scene {i} failed", str(out.get("reason"))[:90])
    took = time.monotonic() - t0
    check(bad == 0, "every scene in the churn drew or was superseded", f"{bad} failed")
    note(f"{n} scenes in {took:.1f}s ({took / n * 1000:.0f} ms each, "
         f"{superseded} superseded by a faster one)")
    s = SC.said()
    check(not s.get("errors"), "and the page raised no errors through all of it",
          str(s.get("errors"))[:100])


def phase_d(quick):
    """A run growing while everything else changes around it."""
    print("\nD. a live run, with the scene changing around it")
    tmp = pathlib.Path(tempfile.mkdtemp()) / "run.log"
    tmp.write_text("start\n", encoding="utf-8")
    drew({"why": "a run and a file", "visible": False, "desktop": "vesper",
          "panes": [{"id": "live", "kind": "run", "path": str(tmp)},
                    {"id": "code", "kind": "code", "path": "core/showcase.py",
                     "focus": {"line": 200}}]}, "a run pane drew")
    time.sleep(0.8)
    first = (SC.said().get("run_tails") or {}).get("live")
    rounds = 6 if quick else 20
    for i in range(rounds):
        with tmp.open("a", encoding="utf-8") as f:
            f.write(f"line {i}\n")
        if i % 4 == 3:                      # and the scene changes underneath it
            C.showcase_point({"pane": "code", "x": (i % 9) / 10, "y": 0.5,
                              "mark": "ring", "at": [(i % 9) / 10, 0.5]})
        time.sleep(0.3)
    time.sleep(0.8)
    last = (SC.said().get("run_tails") or {}).get("live")
    check(bool(first) and bool(last) and last >= first + rounds,
          "the tail kept up with every line while the scene changed around it",
          f"{first} -> {last} for {rounds} appended")


def phase_e(quick):
    """A long demonstration, walked end to end."""
    steps = 8 if quick else 30
    print(f"\nE. a {steps}-step demonstration, walked")
    script = []
    for i in range(steps):
        script.append({
            "say": f"step {i + 1}: what this line does", "dwell_s": 1,
            "scene": {"panes": [{"id": "code", "kind": "code", "path": "core/showcase.py",
                                 "focus": {"line": 30 + i * 7}},
                                {"id": "n", "kind": "text", "text": f"note {i}"}],
                      "marks": [{"kind": "arrow", "pane": "code", "from": [0.05, 0.1],
                                 "anchor": {"pane": "code", "line": 30 + i * 7}}]}})
    loaded = D.load("a long demonstration", script)
    check(loaded.get("ok"), "a long script loads", str(loaded.get("reason"))[:90])
    shown = 0
    for i in range(steps):
        out = D.advance(reveal=False)
        if out.get("ok"):
            shown += 1
        else:
            check(False, f"step {i + 1} did not show", str(out.get("reason"))[:90])
            break
    check(shown == steps, "every step showed and the window confirmed each",
          f"{shown}/{steps}")
    rows = D.transcript()
    check(len(rows) == steps and all(r.get("revision") for r in rows),
          "and the transcript records each with its revision", f"{len(rows)} rows")
    D.stop()


def phase_f(quick):
    """Three writers at once: a demonstration, acts, and the owner's buttons."""
    seconds = 20 if quick else 45
    print(f"\nF. {seconds}s of a demonstration, acts and buttons writing at once")
    from core import controls as CTL
    script = [{"say": f"step {i}", "dwell_s": 1,
               "scene": {"panes": [{"id": "code", "kind": "code",
                                    "path": "core/showcase.py",
                                    "focus": {"line": 40 + i * 3}}]}}
              for i in range(1, 25)]
    D.load("concurrent", script)
    errors: list[str] = []
    halt = threading.Event()

    def demo():
        while not halt.is_set():
            out = D.advance(reveal=False)
            if not out.get("ok") and out.get("state") != D.DONE:
                if "did not report drawing" in str(out.get("reason")):
                    errors.append(f"demonstration: {out.get('reason')}")
            if out.get("state") == D.DONE:
                D.load("concurrent", script)
            halt.wait(0.4)

    def acts():
        i = 0
        while not halt.is_set():
            i += 1
            out = C.showcase_scene({"why": f"act {i}", "visible": False,
                                    "desktop": "vesper",
                                    "panes": [{"id": "t", "kind": "text",
                                               "text": f"act {i}"}]})
            # A SUPERSEDED SCENE IS EXPECTED HERE AND IS NOT A FAULT; a pane that
            # was asked for and did not draw IS.
            if out.get("flag_id") == "showcase.pane_missing":
                errors.append(f"false pane_missing under concurrency: {out.get('reason')}")
            halt.wait(0.3)

    def buttons():
        while not halt.is_set():
            for action in ("showcase.hide", "showcase.reveal"):
                got = CTL.apply({"action": action, "args": {}}, ctx={})
                if not got.get("ok") and "no Desktop" not in str(got.get("reason")):
                    errors.append(f"control {action}: {got.get('reason')}")
                halt.wait(0.7)

    threads = [threading.Thread(target=f, daemon=True) for f in (demo, acts, buttons)]
    for t in threads:
        t.start()
    time.sleep(seconds)
    halt.set()
    for t in threads:
        t.join(5)
    D.stop()
    check(not errors, "three writers for the whole stretch and nothing lied",
          "; ".join(errors[:2])[:160])
    s = SC.said()
    check(bool(s.get("open")), "the window is still there afterwards")
    check(not s.get("errors"), "and the page still has no errors", str(s.get("errors"))[:90])


def phase_g(quick):
    """Bad input: what a real session hands it on a bad day."""
    print("\nG. bad panes -- missing files, dead hosts, oversized text")
    cases = [
        ({"why": "a file that is not there", "panes": [
            {"id": "x", "kind": "code", "path": "/nope/not/here.py"}]}, "refuse"),
        ({"why": "a picture that is not there", "panes": [
            {"id": "x", "kind": "image", "path": "/nope/none.png"}]}, "draw"),
        ({"why": "too much text", "panes": [
            {"id": "x", "kind": "text", "text": "z" * (SC.MAX_TEXT_CHARS + 10)}]}, "refuse"),
        ({"why": "too many marks", "panes": [{"id": "x", "kind": "text", "text": "t"}],
          "marks": [{"kind": "ring", "pane": "x", "at": [0.5, 0.5]}
                    for _ in range(SC.MAX_MARKS + 5)]}, "refuse"),
    ]
    for scene, expect in cases:
        scene.update({"visible": False, "desktop": "vesper"})
        out = C.showcase_scene(dict(scene))
        if expect == "refuse":
            check(not out.get("ok"), f"refused: {scene['why']}", str(out)[:80])
        else:
            check(out.get("ok"), f"drew anyway: {scene['why']}", str(out.get("reason"))[:80])
    # A DEAD HOST MUST NOT HANG THE SURFACE.
    drew({"why": "a host that does not answer", "visible": False, "desktop": "vesper",
          "panes": [{"id": "dead", "kind": "web",
                     "url": "https://this-host-does-not-exist.vesper.invalid"}]},
         "a web pane for a dead host drew")
    t0 = time.monotonic()
    got = C.showcase_web({"verb": "navigate", "pane": "dead",
                          "url": "https://this-host-does-not-exist.vesper.invalid",
                          "wait_s": 20})
    took = time.monotonic() - t0
    check(not got.get("ok"), "a dead host is refused rather than hung",
          str(got.get("reason"))[:70])
    check(took < 20, "and it answers rather than timing out", f"{took:.1f}s")
    check(bool(SC.said().get("open")), "the window survived all of that")


def phase_h(quick):
    """The owner closes the window, and VESPER restarts under it."""
    print("\nH. the owner closes it, and VESPER restarts under it")
    # THE TITLE SAID THIS AND THE CODE DID NOT DO IT. The first version only
    # restarted VESPER, so "the owner closes it" was a claim the phase never
    # tested -- an instrument lying about its own coverage, which is worse than
    # not having the phase at all.
    wid = str(SC.said().get("window_id") or "")
    if wid and wid != "0":
        shut = C.window_close({"window_id": wid, "effect": "close",
                               "owner_requested": True})
        # macOS ONLY LETS VESPER ACT ON THE DESKTOP THAT IS SHOWING, and the
        # showcase is usually not on it. That refusal is the documented rule
        # working, not a defect -- so this asserts whichever is true, and the
        # recovery assertions below run either way, because the question that
        # matters is "can it still draw afterwards".
        elsewhere = "another desktop" in str(shut.get("reason") or "")
        check(shut.get("ok") or elsewhere or "unsaved" in str(shut.get("reason")),
              "closing vesper's showcase either works or says why it cannot",
              str(shut.get("reason"))[:80])
        time.sleep(1.0)
        check(bool(SC.said().get("open")),
              "and the surface is still reading after it is closed")
        out = C.showcase_scene({"why": "after the owner closed it", "visible": False,
                                "desktop": "vesper",
                                "panes": [{"id": "back", "kind": "text",
                                           "text": "still here"}]})
        check(out.get("ok"), "and it still draws, so a reveal can bring it back",
              str(out.get("reason"))[:90])
    drew({"why": "before the restart", "visible": False, "desktop": "vesper",
          "panes": [{"id": "keep", "kind": "text", "text": "still here?"}]},
         "a scene before the restart")
    before = int(SC.said().get("revision") or -1)
    label = f"gui/{os.getuid()}/ai.vesper.island"
    subprocess.run(["launchctl", "kickstart", "-k", label],
                   capture_output=True, text=True, timeout=30)
    back = False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(1.0)
        s = SC.said()
        if s.get("open") and SC.said_path().stat().st_mtime > time.time() - 5:
            back = True
            break
    check(back, "the showcase comes back by itself after a restart")
    if back:
        out = C.showcase_scene({"why": "after the restart", "visible": False,
                                "desktop": "vesper",
                                "panes": [{"id": "after", "kind": "text",
                                           "text": "back"}]})
        check(out.get("ok"), "and draws again without being told anything",
              str(out.get("reason"))[:90])
        note(f"revision continued from {before} to {out.get('revision')}")


def phase_i(quick):
    """What it leaves behind."""
    print("\nI. what it leaves behind")
    d = SC.state_dir()
    leftovers = [p.name for p in d.glob("showcase*.tmp")]
    check(not leftovers, "no temp files left in the state directory",
          ", ".join(leftovers[:4]))
    for name, cap in (("showcase.json", 1_200_000), ("showcase-was.json", 1_000_000),
                      ("showcase-said.json", 400_000)):
        f = d / name
        if f.exists():
            size = f.stat().st_size
            check(size < cap, f"{name} stays bounded", f"{size / 1024:.0f} KB")
    s = SC.said()
    answers = s.get("answers") or {}
    check(len(answers) <= 64, "the answer ring stays bounded", f"{len(answers)} kept")
    shots = list(d.glob("showcase-*.png"))
    if shots:
        note(f"{len(shots)} page snapshots on disk ({sum(p.stat().st_size for p in shots) // 1024} KB)")


def phase_z(quick):
    """Sustained load for as long as the owner asked for, watching the slope.

    A HUNDRED SECONDS IS NOT A LONG RUN, and a leak is invisible in one. This
    holds a steady mixed load and lets the watchdog sample memory throughout, so
    the report can say whether the resident set CLIMBS or settles -- the only
    question that distinguishes a working set from a leak.
    """
    minutes = float(os.environ.get("VESPER_SOAK_MINUTES") or (1 if quick else 8))
    print(f"\nZ. sustained -- {minutes:g} minutes of mixed load, watching the slope")
    tmp = pathlib.Path(tempfile.mkdtemp()) / "run.log"
    tmp.write_text("start\n", encoding="utf-8")
    deadline = time.monotonic() + minutes * 60
    i = 0
    bad = 0
    while time.monotonic() < deadline:
        i += 1
        with tmp.open("a", encoding="utf-8") as f:
            f.write(f"line {i}\n")
        t0 = time.monotonic()
        out = C.showcase_scene({
            "why": f"sustained {i}", "visible": False, "desktop": "vesper",
            # A WEB PANE IS HELD FOR THE WHOLE RUN, never re-navigated: a
            # WKWebView is the heaviest thing on this surface, so a retention
            # problem would show here and nowhere else in the mix.
            "panes": [{"id": "code", "kind": "code", "path": "core/showcase.py",
                       "focus": {"line": 20 + (i % 300)}},
                      {"id": "live", "kind": "run", "path": str(tmp)},
                      {"id": "site", "kind": "web", "url": "https://example.com"},
                      {"id": "n", "kind": "text", "text": f"round {i}"}],
            "marks": [{"kind": "arrow", "pane": "code", "from": [0.05, 0.1],
                       "anchor": {"pane": "code", "line": 20 + (i % 300)}},
                      {"kind": "ring", "pane": "n", "at": [0.5, 0.5]}]})
        LATENCIES.append(time.monotonic() - t0)
        if not out.get("ok") and not out.get("superseded"):
            bad += 1
            if bad <= 3:
                check(False, f"sustained round {i}", str(out.get("reason"))[:90])
        if i % 25 == 0:
            C.showcase_point({"pane": "n", "x": 0.5, "y": 0.5, "mark": "label",
                              "at": [0.5, 0.6], "text": f"{i}"})
    check(bad == 0, f"every one of {i} scenes held up over {minutes:g} minutes",
          f"{bad} failed")
    tail = (SC.said().get("run_tails") or {}).get("live")
    check(bool(tail), "and the live run was still being tailed at the end", f"{tail} lines")


PHASES = {"A": phase_a, "B": phase_b, "C": phase_c, "D": phase_d, "E": phase_e,
          "F": phase_f, "G": phase_g, "H": phase_h, "I": phase_i, "Z": phase_z}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--phase", action="append", choices=sorted(PHASES))
    args = ap.parse_args()
    if not SC.said().get("open"):
        print("the showcase is not open: is VESPER running?")
        return 1

    dog = Watchdog()
    dog.start()
    t0 = time.monotonic()
    rss0 = dog.rss[0] if dog.rss else None
    try:
        for name in (args.phase or sorted(PHASES)):
            dog.phase = name
            PHASES[name](args.quick)
    finally:
        dog.halt.set()
        dog.join(4)

    print("\n" + "-" * 72)
    for s in dog.stalls:
        check(False, f"the window stalled: {s}")
    if dog.cpu:
        note(f"home process cpu (time used per wall second): median "
             f"{statistics.median(dog.cpu):.1f}%, peak {max(dog.cpu):.1f}%")
    if len(dog.rss) > 4:
        rss_lo, rss_hi = min(dog.rss), max(dog.rss)
        span = max(1e-6, dog.rss_at[-1] - dog.rss_at[0])
        # THE SLOPE IS WHAT TELLS A WORKING SET FROM A LEAK. A range says the
        # process got bigger while it was busy, which is what a process does.
        # THE SLOPE IS TAKEN INSIDE THE SUSTAINED PHASE, because phase H restarts
        # VESPER: a first-half/second-half comparison that straddles a restart
        # measures the restart, not the process. The first version reported
        # -103 MB/hour, which was a fresh process, not a shrinking one.
        window = [(t, m) for t, m, ph in zip(dog.rss_at, dog.rss, dog.rss_phase)
                  if ph == "Z"] or list(zip(dog.rss_at, dog.rss))
        half = len(window) // 2 or 1
        early = statistics.median([m for _, m in window[:half]])
        late = statistics.median([m for _, m in window[half:]] or [early])
        inner = max(1e-6, window[-1][0] - window[0][0])
        per_hour = (late - early) / inner * 3600
        note(f"under {inner:.0f}s of sustained load: {early:.0f} MB -> {late:.0f} MB")
        ran = time.monotonic() - t0
        if span < ran * 0.8:
            check(False, "the watchdog measured the whole run",
                  f"sampled {span:.0f}s of {ran:.0f}s")
        note(f"resident {rss_lo:.0f} -> {rss_hi:.0f} MB over {span:.0f}s "
             f"of a {ran:.0f}s run; "
             f"first half median {early:.0f} MB, second half {late:.0f} MB "
             f"({per_hour:+.0f} MB/hour at that slope)")
        check(per_hour < 120, "memory is a working set and not a leak",
              f"{per_hour:+.0f} MB/hour")
        time.sleep(8)
        settled = sample(dog.pid)[1] if dog.pid else -1
        if settled > 0:
            note(f"and it settles back to {settled:.0f} MB once the load stops")
    if LATENCIES:
        ordered = sorted(LATENCIES)
        p50 = ordered[len(ordered) // 2] * 1000
        p95 = ordered[int(len(ordered) * 0.95)] * 1000
        note(f"scene latency: median {p50:.0f} ms, p95 {p95:.0f} ms, "
             f"worst {ordered[-1] * 1000:.0f} ms, {len(ordered)} acts")
        check(p95 < 2500, "and it stayed responsive throughout", f"p95 {p95:.0f} ms")
    revs = [r for r in dog.revisions if r >= 0]
    if revs:
        check(all(b >= a for a, b in zip(revs, revs[1:])),
              "the drawn revision never went backwards")

    print("-" * 72)
    if FAILED:
        print(f"{len(FAILED)} of {CHECKS} checks failed:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print(f"all {CHECKS} checks passed under load, on the running window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
