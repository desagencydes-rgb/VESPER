"""The seventeen main-menu destinations as CARDS that manage, not readings.

THE OWNER, 2026-09-13: *"its buttons need to open cards where i can manage
stuff not just look at some json bullshit."* Until tonight every destination on
the main menu rendered the same shape: one catalogue line with a reading or an
absence. This module gives each destination a card with three things: ROWS
that are real readings with their source, SETTINGS rows it may borrow from the
settings producer (so a control on a card is the same control, bound by the
same schema), and ACTIONS -- buttons whose payload is a control the runtime or
the host applies (`core/controls.py` says which, by kind).

WHAT AN ACTION MAY BE. `preference.set` (the owner's own settings),
`permission.set` (the standing permission mode, a named-principal write),
`memory.export`, `act` (a sentence queued through the ordinary typed path, so
it meets intent, authorisation, the ladder and the flag bar), and `host.*`
(things the HOST does itself because they must not traverse the runtime: the
stop and the re-arm, opening a System Settings pane, dropping every grant,
requesting speech consent, running the gates). INV-STOP-2: the stop path does
not traverse the VESPER control plane -- so `host.stop` never reaches this
process; the Swift host unregisters the arm agent on the click.

EVERY ROW HAS A SOURCE. A card that says "armed" without saying what it read
is the island's "320k assertions" column again. Readings that are not on this
node say so plainly ("no remote surface enrolled") rather than UNAVAILABLE:
the owner asked to see that word nowhere, and the honest replacement is the
sentence that says what is true.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import time
import tomllib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
BUNDLE_ID = "ai.vesper.island"

PRIVACY_PANES = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "camera": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "speech": "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition",
    "calendars": "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars",
}


def _row(label: str, value: Any, source: str, detail: str = "") -> dict:
    return {"label": label, "value": value, "source": source, "detail": detail}


def _action(id_: str, label: str, action: str, args: dict | None = None,
            *, danger: bool = False, note: str = "") -> dict:
    return {"id": id_, "label": label, "danger": danger, "note": note,
            "control": {"action": action, "args": args or {}}}


def _toml(rel: str) -> dict:
    try:
        return tomllib.loads((REPO / rel).read_text(encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return {}


def _bus(sql: str, params: tuple = ()) -> list:
    """A read-only question to the event store. Empty on any failure."""
    p = STATE / "bus" / "log.db"
    if not p.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1.0)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []


def _counts(hours: float, kinds: tuple) -> dict:
    since = int((time.time() - hours * 3600) * 1000)
    marks = ",".join("?" for _ in kinds)
    rows = _bus(f"SELECT kind, count(*) FROM records WHERE hlc_physical_ms>? "
                f"AND kind IN ({marks}) GROUP BY kind", (since, *kinds))
    out = {k: 0 for k in kinds}
    out.update({k: n for k, n in rows})
    return out


def _last(kind: str) -> float | None:
    rows = _bus("SELECT max(hlc_physical_ms) FROM records WHERE kind=?", (kind,))
    return (rows[0][0] / 1000.0) if rows and rows[0][0] else None


def _age(ts: float | None) -> str:
    if ts is None:
        return "never"
    s = max(0.0, time.time() - ts)
    if s < 90:
        return f"{int(s)} s ago"
    if s < 5400:
        return f"{int(s // 60)} min ago"
    return f"{s / 3600:.1f} h ago"


def _armed() -> tuple[bool, str]:
    p = STATE / "interlock" / "enable_token.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        issued, ttl = int(d.get("issued_at_ms", 0)), int(d.get("ttl_ms", 0))
        left = (issued + ttl) / 1000.0 - time.time()
        if left > 0:
            return True, f"enable token fresh, {int(left)} s left, issued by {d.get('issued_by')}"
        return False, f"enable token expired {int(-left)} s ago"
    except Exception:                                     # noqa: BLE001
        return False, "no enable token on disk"


def _agent_pid(label: str) -> str | None:
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=3).stdout
    except Exception:                                     # noqa: BLE001
        return None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == label:
            return parts[0].strip()
    return None


def _grants() -> tuple[list, str]:
    """What the app's own `--grants` mode last wrote, newest of the two places."""
    cands = [STATE / "grants.txt", pathlib.Path("/tmp/vesper-grants.txt")]
    cands = [c for c in cands if c.exists()]
    if not cands:
        return [], "not read since the last build -- press Read grants"
    p = max(cands, key=lambda c: c.stat().st_mtime)
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            rows.append(_row(k.strip(), v.strip(), f"{p} ({_age(p.stat().st_mtime)})"))
    return rows, f"{p.name}, read {_age(p.stat().st_mtime)}"


def mic_reading() -> tuple[str, str]:
    """The last `--mic-level` reading and what it means, or why there is none.

    The interpretation is `Listener.swift`'s own: normal speech at a desk peaks
    around -12 to -6 dBFS with mean RMS near -30; a peak below -35 is quiet;
    no buffers at all is no microphone on that input, not a quiet one.
    """
    p = STATE / "mic-level.txt"
    if not p.exists():
        return "not measured yet -- press Measure and speak normally for 8 s", ""
    text = p.read_text(encoding="utf-8", errors="replace")
    import re as _re
    m = _re.search(r"peak (-?[\d.]+) dBFS, mean rms (-?[\d.]+) dBFS, over (\d+) buffers", text)
    when = _age(p.stat().st_mtime)
    if not m:
        if "no audio buffers" in text:
            return f"no audio buffers arrived ({when}): no microphone on the selected input", str(p)
        return f"unreadable reading ({when})", str(p)
    peak, rms, n = float(m.group(1)), float(m.group(2)), int(m.group(3))
    verdict = ("QUIET: check the system input volume and device before adding gain" if peak < -35
               else "usable level" if peak <= -3 else "HOT: near clipping, lower the input")
    return f"peak {peak:g} dBFS, rms {rms:g} dBFS over {n} buffers ({when}) -- {verdict}", str(p)


def camera_reading() -> tuple[str, str]:
    """The last `--camera-probe` reading, or why there is none."""
    p = STATE / "camera-probe.txt"
    if not p.exists():
        return "not measured yet -- press Probe camera (5 s, on-device detection, nothing stored)", ""
    lines = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    return f"{lines[-1][:140] if lines else 'empty'} ({_age(p.stat().st_mtime)})", str(p)


def presence_reading() -> tuple[str, str]:
    p = STATE / "presence.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        age = _age(d.get("at_ms", 0) / 1000.0)
        who = "someone at the machine" if d.get("someone") else "nobody in view"
        return f"{who} ({age}; identity {d.get('identity', 'unknown')})", str(p)
    except Exception:                                     # noqa: BLE001
        return "no presence flag yet -- the camera has not been asked", ""


def _memory_counts() -> dict:
    p = STATE / "l2.db"
    out = {"entity": 0, "fact": 0, "edge": 0}
    if not p.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1.0)
        try:
            for t in out:
                try:
                    out[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                except sqlite3.Error:
                    pass
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


def cards(home: Any = None) -> dict:
    """Every main destination, as a card. Keyed by catalogue id."""
    from core import permission_mode as PM
    from core import preferences as P
    prefs = P.read()
    out: dict = {}
    armed, why_armed = _armed()
    arm_pid = _agent_pid("ai.vesper.island.arm")

    # --- action-outbox -----------------------------------------------------
    c = _counts(24, ("outbox.intent", "outbox.confirmed", "outbox.unknown", "act.outcome"))
    out["action-outbox"] = {
        "title": "Action outbox",
        "summary": "Every outward effect is recorded before it happens (INV-ACT-6). Last 24 h, from the event store.",
        "rows": [_row("intents recorded", c["outbox.intent"], "bus: outbox.intent"),
                 _row("confirmed", c["outbox.confirmed"], "bus: outbox.confirmed"),
                 _row("unresolved", c["outbox.unknown"], "bus: outbox.unknown",
                      "an effect whose result could not be read back; reconciled before any retry (INV-EXT-2)"),
                 _row("acts with an outcome", c["act.outcome"], "bus: act.outcome")],
        "actions": [_action("explain", "Explain the unresolved ones", "act",
                            {"text": "which of your recorded actions are unresolved, and why?"})],
    }

    # --- autonomy-queue / emergency-stop -----------------------------------
    hb = _last("autonomy.heartbeat")
    trg = (_toml("contracts/policy/trigger_registry.toml").get("triggers") or {})
    c = _counts(24, ("autonomy.trigger_fired", "autonomy.handled", "autonomy.noop", "autonomy.blocked_on_cost_policy"))
    stop_actions = [
        _action("stop", "STOP autonomy now", "host.stop", danger=True,
                note="the host unregisters the arm agent; the token expires within 90 s and autonomy halts (INV-STOP-3)"),
        _action("rearm", "Re-arm", "host.rearm",
                note="a human act, on this click (INV-STOP-7)"),
    ]
    out["autonomy-queue"] = {
        "title": "Autonomy queue",
        "summary": "What VESPER may do unprompted, and whether it is armed to do it.",
        "rows": [_row("armed", "yes" if armed else "no", "interlock/enable_token.json", why_armed),
                 _row("arm agent", f"running, pid {arm_pid}" if arm_pid and arm_pid != "-" else "not running",
                      "launchctl list ai.vesper.island.arm"),
                 _row("last heartbeat", _age(hb), "bus: autonomy.heartbeat"),
                 _row("triggers", f"{len(trg)} registered, {sum(1 for v in trg.values() if v.get('enabled'))} enabled",
                      "contracts/policy/trigger_registry.toml"),
                 _row("last 24 h", f"{c['autonomy.trigger_fired']} fired, {c['autonomy.handled']} handled, "
                                   f"{c['autonomy.noop']} no-ops, {c['autonomy.blocked_on_cost_policy']} blocked by cost",
                      "bus")],
        "actions": stop_actions + [_action("list", "What are you planning?", "act",
                                            {"text": "what do you intend to do unprompted, and when?"})],
    }
    out["emergency-stop"] = {
        "title": "Emergency stop",
        "summary": "Independent of the thing it stops: the host, not the runtime, unregisters the arm agent (INV-STOP-2).",
        "rows": [_row("autonomy", "ARMED" if armed else "STOPPED", "interlock/enable_token.json", why_armed),
                 _row("arm agent", f"pid {arm_pid}" if arm_pid and arm_pid != "-" else "not running",
                      "launchctl list")],
        "actions": stop_actions,
    }

    # --- grants / hardware-access / macos-permissions -----------------------
    grows, gsrc = _grants()
    panes = [_action(f"open-{k}", f"Open {k.title()} pane", "host.open_url", {"url": v})
             for k, v in PRIVACY_PANES.items()]
    read_grants = _action("read", "Read grants now", "host.read_grants",
                          note="runs the app's own --grants mode; asks for nothing")
    out["grants"] = {
        "title": "Grants",
        "summary": f"Standing permissions as macOS reports them to VESPER itself ({gsrc}).",
        "rows": grows or [_row("grants", "not read since the last build", "app --grants",
                               "every rebuild re-signs the app and TCC forgets it (MEMORY: TCC grants die on every rebuild)")],
        "actions": [read_grants] + panes[:4],
    }
    mic_val, mic_src = mic_reading()
    cam_val, cam_src = camera_reading()
    pres_val, pres_src = presence_reading()
    out["hardware-access"] = {
        "title": "Hardware access",
        "summary": "Camera, microphone, screen: what is granted, what was measured, and what is in use.",
        "rows": ([r for r in grows if any(w in r["label"].lower() for w in ("camera", "microphone", "screen", "speech"))]
                 or [_row("hardware grants", "not read since the last build", "app --grants")])
                + [_row("microphone level", mic_val, mic_src or "app --mic-level",
                        "measured at the recogniser's input, before any gain"),
                   _row("microphone gain", f"{prefs.get('microphone.gain_db', 0):g} dB", "preferences.json",
                        "applied to a copy of each buffer after the level is measured; ±20 dB"),
                   _row("camera", cam_val, cam_src or "app --camera-probe",
                        "fps, faces and cpu from Apple's on-device face detection; no frame is kept"),
                   _row("presence", pres_val, pres_src or "presence.json",
                        "detection, not identity: the face-auth model of VISION-IDENTITY.md is not built")],
        "settings": ["microphone"],
        "actions": [_action("mic", "Measure microphone (8 s)", "host.mic_level",
                            note="speak normally at your usual distance; the reading lands here"),
                    _action("cam", "Probe camera (5 s)", "host.camera_probe",
                            note="opens the webcam as VESPER, detects faces on-device, writes counts and a presence flag"),
                    read_grants, panes[3], panes[2], panes[1]],
    }
    out["macos-permissions"] = {
        "title": "macOS permissions",
        "summary": "Accessibility, Screen Recording, Automation, Speech: granted or needed, and the pane that grants each.",
        "rows": grows or [_row("permissions", "not read since the last build", "app --grants")],
        "actions": [read_grants,
                    _action("speech", "Request speech consent", "host.speech_consent",
                            note="open -n VESPER --args --speech-consent, so TCC attributes the ask to VESPER")]
                   + panes,
    }

    # --- verification-state ----------------------------------------------
    gates_log = STATE / "gates.log"
    if gates_log.exists():
        tail = gates_log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        gates_val = f"{tail[0][:80] if tail else 'running'} ({_age(gates_log.stat().st_mtime)})"
    else:
        gates_val = "not run from here yet"
    try:
        from core import settings_surface as SS
        gs = next((r for r in SS.rows() if r["id"] == "gate-status"), {})
        se = next((r for r in SS.rows() if r["id"] == "self-test-evidence"), {})
    except Exception:                                     # noqa: BLE001
        gs, se = {}, {}
    out["verification-state"] = {
        "title": "Verification state",
        "summary": "Verified is what a check saw; asserted is what a document says. Repetition never counts as success.",
        "rows": [_row("documented checks", gs.get("value", "unread"), gs.get("source", "CLAUDE.md")),
                 _row("documented red runs", se.get("value", "unread"), se.get("source", "CLAUDE.md")),
                 _row("last gate run from here", gates_val, str(gates_log))],
        "actions": [_action("run", "Run every gate now", "host.run_gates",
                            note="python3.13 tools/ci/checks.py all in the project, output to gates.log; about four minutes")],
    }

    # --- follow-me / remote-surfaces --------------------------------------
    caps = (_toml("contracts/policy/capability_profiles.toml").get("capability") or {})
    out["follow-me"] = {
        "title": "Follow-me",
        "summary": "The interface follows VESPER when it relocates. Relocation needs a second enrolled node.",
        "rows": [_row("enrolled nodes", len(caps), "contracts/policy/capability_profiles.toml"),
                 _row("placement", "single node: nothing to follow yet" if len(caps) <= 1 else "re-evaluated continuously (INV-PLACE-1)",
                      "core/placement.py")],
        "actions": [_action("enroll", "How do I enroll a node?", "act",
                            {"text": "explain how to enroll another machine as a node, step by step"})],
    }
    out["remote-surfaces"] = {
        "title": "Remote surfaces",
        "summary": "Reaching VESPER from a phone or another machine.",
        "rows": [_row("phone app", "not built (build order step 31)", "HOME-WORKBENCH §10"),
                 _row("remote nodes", f"{max(0, len(caps) - 1)} besides this one", "capability_profiles.toml"),
                 _row("endpoint preference", prefs.get("endpoint_selection", "auto"), "preferences.json")],
        "settings": ["endpoint-selection"],
        "actions": [_action("plan", "What would it take?", "act",
                            {"text": "what would it take to reach you from my phone?"})],
    }

    # --- grant-templates (the permission mode) ---------------------------
    mode = PM.read()
    out["grant-templates"] = {
        "title": "Grant templates",
        "summary": "The standing permission mode: how much VESPER may do before asking. Set by you, by name (a mode change with no principal is VESPER raising its own authority).",
        "rows": [_row("mode in force", mode, "permission_mode.json"),
                 _row("ask", "every act above L1 asks first", "core/permission_mode.py"),
                 _row("workspace", "acts freely inside its own place, asks outside", "core/permission_mode.py"),
                 _row("auto", "acts without asking, never above its ceilings", "core/permission_mode.py")],
        "actions": [_action(f"mode-{m}", f"Set {m}", "permission.set", {"mode": m}) for m in PM.MODES],
    }

    # --- import-export (memory) -------------------------------------------
    mc = _memory_counts()
    out["import-export"] = {
        "title": "Import / export",
        "summary": "Your memory, as facts VESPER extracted, never the transcript.",
        "rows": [_row("entities", mc["entity"], "l2.db"), _row("facts", mc["fact"], "l2.db"),
                 _row("relations", mc["edge"], "l2.db", "0 until relate() is called (PLAN F3)")],
        "actions": [_action("export", "Export memory to Desktop", "memory.export",
                            note="writes ~/Desktop/VESPER-memory-<time>.json; ids and facts, no transcript")],
    }

    # --- live-activity-stream ---------------------------------------------
    gran = prefs.get("activity.granularity", "actions")
    kinds = {"all": None,
             "actions": ("act.outcome", "tool.invoked", "tool.completed", "intent.proposed", "flag.raised",
                         "control.applied", "control.refused", "preference.changed"),
             "turns": ("turn", "intent.proposed", "act.outcome")}[gran]
    if kinds:
        marks = ",".join("?" for _ in kinds)
        ev = _bus(f"SELECT kind, hlc_physical_ms FROM records WHERE kind IN ({marks}) ORDER BY seq DESC LIMIT 20", kinds)
    else:
        ev = _bus("SELECT kind, hlc_physical_ms FROM records WHERE kind NOT IN ('autonomy.heartbeat','safety.token_accepted') ORDER BY seq DESC LIMIT 20")
    out["live-activity-stream"] = {
        "title": "Live activity",
        "summary": f"The newest 20 events at granularity '{gran}', from the event store.",
        "rows": [_row(time.strftime("%H:%M:%S", time.localtime(ms / 1000)), k, "bus") for k, ms in ev]
                or [_row("events", "none yet at this granularity", "bus")],
        "controls": [{**P.describe("activity.granularity"), "value": gran, "label": "granularity"}],
        "actions": [],
    }

    # --- modes --------------------------------------------------------------
    pair = _toml("contracts/policy/mode_pairings.toml")
    pairings = pair.get("pairings") or {}
    cur = {"mode": getattr(home, "_mode", None), "stage": getattr(home, "_stage", None),
           "ambience": getattr(home, "_ambience", None)} if home is not None else {}
    out["modes"] = {
        "title": "Modes",
        "summary": "A mode pairs a stage of work with an ambience. Switching changes only VESPER's own Desktop.",
        "rows": [_row("current", f"{cur.get('mode') or 'unknown'} (stage {cur.get('stage') or '?'}, ambience {cur.get('ambience') or '?'})",
                      "home.json")]
                + [_row(name, f"stage {v.get('stage', name)}, ambience {v.get('ambience', '?')}",
                        "contracts/policy/mode_pairings.toml") for name, v in pairings.items()],
        "actions": [_action(f"mode-{name}", f"Switch to {name}", "act", {"text": f"switch to {name} mode"})
                    for name in pairings],
    }

    # --- panic-revoke -------------------------------------------------------
    out["panic-revoke"] = {
        "title": "Panic revoke",
        "summary": "Drop every standing grant at once and stop autonomy, without stopping VESPER. The host confirms once, then runs tccutil reset for this app.",
        "rows": [_row("what it drops", "Accessibility, Screen Recording, Microphone, Camera, Speech, Automation, Calendars for " + BUNDLE_ID,
                      "tccutil reset All " + BUNDLE_ID),
                 _row("what it keeps", "VESPER running, your files, your preferences", "-")],
        "actions": [_action("panic", "REVOKE EVERYTHING", "host.panic_revoke", danger=True,
                            note="the host asks once, then resets TCC for this app and unregisters the arm agent")],
    }

    # --- per-app-rules ------------------------------------------------------
    try:
        from core import apps as A
        classes = list(A.CLASSES)
    except Exception:                                     # noqa: BLE001
        classes = []
    out["per-app-rules"] = {
        "title": "Per-app rules",
        "summary": "Rules branch on an application's CLASS, never its name (INV-HW-1). Rule 31: VESPER manages its own windows always, others on demand.",
        "rows": [_row(cl, "driven only with a grant; refused without one" if cl != "vesper_itself" else "VESPER's own",
                      "core/apps.py, core/windows.py") for cl in classes]
                + [_row("others' windows", "managed on demand" if prefs.get("windows.manage_others_on_demand", True) else "managed like VESPER's own",
                        "preferences.json")],
        "controls": [{**P.describe("windows.manage_others_on_demand"),
                      "value": prefs.get("windows.manage_others_on_demand", True), "label": "others on demand"}],
        "actions": [_action("which", "Which apps may you drive right now?", "act",
                            {"text": "which applications may you drive right now, and which need a grant?"})],
    }

    # --- quiet-hours-restrictions -----------------------------------------
    out["quiet-hours-restrictions"] = {
        "title": "Quiet hours",
        "summary": "Narrower permissions at night. Alarm class stays exempt (INV-ALARM-3).",
        "rows": [_row("quiet hours", f"{prefs.get('quiet_hours.start')}–{prefs.get('quiet_hours.end')}", "preferences.json"),
                 _row("do not disturb", "on" if prefs.get("do_not_disturb") else "off", "preferences.json"),
                 _row("FREE_TIME budget", "0 contacts an hour by contract", "contracts/policy/interruption_budget.toml")],
        "settings": ["quiet-hours", "do-not-disturb", "notification-rules"],
        "actions": [],
    }

    # --- work-rate ----------------------------------------------------------
    hrs = float(prefs.get("work_rate.window_hours", 24) or 24)
    c = _counts(hrs, ("turn", "act.outcome", "model.completed", "tool.completed", "flag.raised"))
    out["work-rate"] = {
        "title": "Work rate",
        "summary": f"What got done in the last {hrs:g} h, counted from the event store.",
        "rows": [_row("turns answered", c["turn"], "bus: turn"),
                 _row("acts with an outcome", c["act.outcome"], "bus: act.outcome"),
                 _row("tools completed", c["tool.completed"], "bus: tool.completed"),
                 _row("model completions", c["model.completed"], "bus: model.completed"),
                 _row("flags raised", c["flag.raised"], "bus: flag.raised")],
        "controls": [{**P.describe("work_rate.window_hours"), "value": hrs, "label": "window (hours)"}],
        "actions": [],
    }
    return out
