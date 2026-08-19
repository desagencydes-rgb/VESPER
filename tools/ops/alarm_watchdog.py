#!/usr/bin/env python3
"""Watchdog for the prototype alarm — restores the primary, never fires itself.

WHY THIS IS NOT A SECOND FIRING PATH
------------------------------------
The obvious backup is a systemd timer that sounds the alarm at 09:00 if the
primary did not. That trades one failure for a worse one: two independent
things that can each make noise, and no way for either to know the other
already did. A double alarm at 09:00 is not a smaller bug than a silent one --
it is the same bug with the owner awake to see it.

So this process never actuates. It answers exactly one question --

    is the primary still there, and should it be? --

and its only action is to put the primary back. There is one firing path in the
system at all times, which is what makes double-firing structurally impossible
rather than merely unlikely.

WHAT IT COVERS, AND WHAT IT DOES NOT
------------------------------------
Covers: the primary crashing, being OOM-killed, being killed by accident, or
exiting for any reason before its due time while the user session is alive.

Does NOT cover: reboot or power-off. On node 2 as configured on 2026-08-18,
`loginctl show-user csf -p Linger` reads `Linger=no` and lightdm has no
autologin, so after a reboot there is no user session, no PipeWire, and nothing
starts a systemd --user timer. Closing that hole needs root and is recorded in
docs/planning/spike-results/ALARM-SPOF-OWNER-ACTIONS.md. This file does not
pretend otherwise: `status` reports the reboot hole as OPEN.

THE THREE REFUSALS
------------------
A watchdog that relaunches too eagerly is worse than none, because it can sound
an alarm nobody asked for. This one declines to act in three cases:

  1. The due time has passed by more than GRACE_S. A stale intent must never
     resurrect yesterday's alarm at noon.
  2. The evidence file shows this exact due time already ran to completion.
     Keyed on `alarm.waiting.payload.due`, so a completed 09:00 is never
     confused with a pending one.
  3. A primary for this due time is already alive. Matched precisely enough not
     to match this watchdog, or a shell wrapper that happens to carry the same
     words on its command line -- a stray launcher wrapper matching a loose
     pattern is exactly how a watchdog concludes "all is well" over a dead
     alarm.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / ".alarm-state"
INTENT = STATE / "intent.json"
FIRE_RESULT = STATE / "fire-result.json"
LOG_DIR = Path.home() / ".vesper-alarm-logs"
PRIMARY = REPO / "tools" / "ops" / "alarm_night.py"

# How long after the due time an intent stays actionable. Past this the intent
# is stale and the correct action is to do nothing and say so.
GRACE_S = 1800


# ---------------------------------------------------------------- intent
def read_intent() -> dict | None:
    if not INTENT.exists():
        return None
    try:
        return json.loads(INTENT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_intent(due: str, cap_s: int) -> dict:
    STATE.mkdir(parents=True, exist_ok=True)
    obj = {
        "due": due,
        "cap_s": cap_s,
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "note": ("What the watchdog guards. Its presence does not mean an "
                 "alarm is running -- run `status` for that."),
    }
    INTENT.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return obj


# ---------------------------------------------------------------- refusals
def already_completed(due: str) -> bool:
    """Refusal 2. True when the evidence file shows THIS due time finished.

    Keyed on the `alarm.waiting` record's due rather than on the file's mtime,
    because the file is rewritten by every run and a mtime says when something
    was written, not which alarm it was about.
    """
    if not FIRE_RESULT.exists():
        return False
    try:
        recs = json.loads(FIRE_RESULT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    recs = recs.get("records", recs) if isinstance(recs, dict) else recs
    if not isinstance(recs, list):
        return False
    file_due = None
    completed = False
    for r in recs:
        if not isinstance(r, dict):
            continue
        payload = r.get("payload") or {}
        if r.get("kind") == "alarm.waiting" and isinstance(payload, dict):
            file_due = payload.get("due")
        if r.get("kind") == "alarm.completed":
            completed = True
    return completed and file_due == due


def primary_pids(due: str) -> list[int]:
    """Refusal 3. PIDs of live primaries for exactly this due time.

    Reads /proc directly rather than shelling out to pgrep, so the match is
    against the real argv rather than a rendered command line a wrapper could
    also satisfy. The test is: a python process whose argv contains
    alarm_night.py, the literal token `fire`, and this due string.
    """
    me = os.getpid()
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        args = [a.decode("utf-8", "replace") for a in argv if a]
        if not args:
            continue
        if not any(a.endswith("alarm_night.py") for a in args):
            continue
        if "fire" not in args:
            continue
        if due not in args:
            continue
        found.append(pid)
    return found


# ---------------------------------------------------------------- action
def relaunch(due: str, cap_s: int) -> dict:
    """The only thing this program is allowed to do to the world.

    THE RESTORED PROCESS MUST NOT LIVE IN THIS PROCESS'S CGROUP.

    The first version of this function used Popen(start_new_session=True),
    which detaches the process from the terminal but NOT from the systemd
    cgroup. The watchdog runs as a `Type=oneshot` unit whose KillMode defaults
    to `control-group`, so the instant the watchdog finished, systemd killed
    everything still in its cgroup -- including the alarm it had just restored,
    2 ms earlier.

    That failure is worth naming precisely because of how it presented: the
    journal recorded `{"action": "relaunch", "relaunched_pid": 518375}` and
    the unit reported `Result=success`. Both were true statements about what
    the watchdog *did*, and the alarm was dead anyway. A restore that reports
    its own return value has not established that anything is running -- the
    same lesson the rung readiness check learned when `spd-say` exiting 0 was
    mistaken for a sound in the room.

    So the restore goes through `systemd-run --user`, which places the primary
    in a transient unit of its own. It survives this process exiting, it is
    visible as a named unit, and `verify_alive` below re-reads /proc afterwards
    rather than trusting the launch.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", due)
    unit = f"vesper-alarm-primary-{stamp}"
    cmd = [sys.executable, str(PRIMARY), "fire", "--at", due, "--cap-s", str(cap_s)]

    if shutil.which("systemd-run"):
        # A previous transient unit that failed would block the name.
        subprocess.run(["systemctl", "--user", "reset-failed", unit],
                       capture_output=True)
        r = subprocess.run(
            ["systemd-run", "--user", "--collect", "--quiet",
             f"--unit={unit}", f"--working-directory={REPO}",
             "--property=KillMode=process", *cmd],
            capture_output=True, text=True)
        out = {"method": "systemd-run", "unit": unit,
               "launch_rc": r.returncode,
               "launch_stderr": (r.stderr or "").strip()[:300]}
    else:
        log = LOG_DIR / f"restored-{stamp}.log"
        with open(log, "ab") as fh:
            proc = subprocess.Popen(
                cmd, cwd=str(REPO), stdout=fh, stderr=fh,
                stdin=subprocess.DEVNULL, start_new_session=True)
        out = {"method": "popen", "spawned_pid": proc.pid, "log": str(log)}

    out.update(verify_alive(due))
    return out


def verify_alive(due: str, settle_s: float = 1.5) -> dict:
    """Re-read /proc after a restore. The launch is a claim; this is the check."""
    time.sleep(settle_s)
    pids = primary_pids(due)
    return {"verified_running": bool(pids), "verified_pids": pids,
            "verify_note": ("re-read from /proc after the launch, because a "
                            "launch that returns 0 has not established that "
                            "anything survived it")}


# ---------------------------------------------------------------- commands
def evaluate(intent: dict) -> dict:
    due = intent["due"]
    cap_s = int(intent.get("cap_s", 900))
    now = datetime.now()
    try:
        due_dt = datetime.strptime(due, "%Y-%m-%d %H:%M")
    except ValueError:
        return {"action": "none", "reason": "unparseable_due", "due": due}

    if now > due_dt + timedelta(seconds=GRACE_S):
        return {"action": "none", "reason": "intent_stale", "due": due,
                "note": ("past due by more than the grace window; a watchdog "
                         "that relaunches here sounds yesterday's alarm today")}
    if already_completed(due):
        return {"action": "none", "reason": "already_completed", "due": due}
    pids = primary_pids(due)
    if pids:
        return {"action": "none", "reason": "primary_alive", "due": due,
                "pids": pids}
    return {"action": "relaunch", "reason": "primary_absent", "due": due,
            "cap_s": cap_s}


def cmd_check(args) -> int:
    intent = read_intent()
    if intent is None:
        out = {"action": "none", "reason": "no_intent",
               "note": "nothing is being guarded"}
        print(json.dumps(out))
        return 0
    out = evaluate(intent)
    if out["action"] == "relaunch" and not args.dry_run:
        out.update(relaunch(out["due"], out["cap_s"]))
        out["at"] = datetime.now().isoformat(timespec="seconds")
    elif out["action"] == "relaunch":
        out["dry_run"] = True
    print(json.dumps(out))
    return 0


def cmd_status(args) -> int:
    intent = read_intent()
    linger = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""),
                             "-p", "Linger"], capture_output=True, text=True)
    reboot_covered = "Linger=yes" in (linger.stdout or "")
    out = {
        "intent": intent,
        "evaluation": evaluate(intent) if intent else None,
        "coverage": {
            "process_death": True,
            "reboot_or_poweroff": reboot_covered,
            "note": ("reboot coverage needs `loginctl enable-linger` AND a "
                     "session that starts audio at boot; without both there "
                     "is no PipeWire after a reboot and nothing to sound"),
        },
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_set(args) -> int:
    print(json.dumps(write_intent(args.at, args.cap_s), indent=2))
    return 0


def cmd_clear(args) -> int:
    existed = INTENT.exists()
    INTENT.unlink(missing_ok=True)
    print(json.dumps({"cleared": existed}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(required=True)
    c = sub.add_parser("check", help="evaluate and restore if needed")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_check)
    sub.add_parser("status", help="what is guarded and what is covered").set_defaults(fn=cmd_status)
    s = sub.add_parser("set", help="record what to guard")
    s.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM"')
    s.add_argument("--cap-s", type=int, default=900)
    s.set_defaults(fn=cmd_set)
    sub.add_parser("clear").set_defaults(fn=cmd_clear)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
