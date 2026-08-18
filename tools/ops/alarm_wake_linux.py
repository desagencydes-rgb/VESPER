#!/usr/bin/env python3
"""Keep the RTC wake alarm armed to the next alarm's wake time. Node 2, root.

WHY THIS EXISTS
---------------
`alarm_night.py arm` is Windows-only. It shells out to PowerShell and calls
`Register-ScheduledTask ... -WakeToRun`, and node 2 has neither `powershell`
nor `pwsh`. So on the machine the alarm actually lives on there has never been
a wake path at all -- only `fire` launched detached, which sleeps in a single
`time.sleep()` and dies with the machine.

`alarm_node_linux.py`'s header says *"THIS NODE NEEDS NO WAKE STEP. It is
already awake, with the lid closed or open."* That is a premise about three
stay-awake layers, not a guarantee, and nothing was checking it. Measured
2026-08-18: `sleep.target` is `static`, not masked, so a manual suspend still
works, and `/sys/class/rtc/rtc0/wakealarm` was empty. A suspended or powered-off
laptop had no way back.

THE DESIGN, AND WHY IT IS A POLLER RATHER THAN A HOOK
-----------------------------------------------------
The obvious build is a `systemd-sleep` hook that arms the RTC on the way down.
That covers suspend and misses power-off, so it wants a shutdown unit too, and
then there are two mechanisms that must agree about the same register.

The RTC alarm lives in the **hardware clock**, not in the kernel. It survives
suspend, power-off, and losing mains power. So the simplest correct thing is to
keep it armed at all times while the machine is up: if the machine then goes
down for any reason -- suspend, shutdown, a pulled plug -- the alarm is already
in the chip and nobody had to notice it was happening.

One mechanism, one register, no hooks that have to fire in the right order.

WHAT IT WILL NOT DO
-------------------
Waking from a full power-off (S5) additionally needs the firmware's "RTC alarm
resume" to be enabled. That is a BIOS setting, not something software can read
back reliably, so this program does not claim it. It reports what it armed and
what the register reads back; whether the machine actually rises is a
measurement, and it is recorded in ALARM-SPOF-OWNER-ACTIONS.md when it is taken.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

WAKEALARM = Path("/sys/class/rtc/rtc0/wakealarm")
INTENT = Path("/home/csf/VESPER/.alarm-state/intent.json")
# How early to wake. The primary preflights 300 s before due; waking earlier
# than that gives PipeWire, the watchdog timer and the session time to settle.
MARGIN_MIN = 15


def read_intent() -> dict | None:
    try:
        return json.loads(INTENT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def rtc_now() -> datetime | None:
    """The RTC's own idea of the time, which is what the register is in."""
    try:
        r = subprocess.run(["hwclock", "--show"], capture_output=True,
                           text=True, timeout=20)
        if r.returncode == 0:
            return datetime.fromisoformat(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def current_alarm() -> int | None:
    try:
        raw = WAKEALARM.read_text().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def arm(epoch: int) -> tuple[bool, str]:
    """Clear then set. Writing a new value over a live alarm is rejected."""
    try:
        WAKEALARM.write_text("0\n")
        WAKEALARM.write_text(f"{epoch}\n")
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"
    back = current_alarm()
    if back != epoch:
        return False, f"read-back mismatch: wrote {epoch}, register holds {back}"
    return True, "armed and read back"


def wake_epoch_for(due: str) -> int | None:
    try:
        due_dt = datetime.strptime(due, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return int((due_dt - timedelta(minutes=MARGIN_MIN)).timestamp())


def cmd_sync(args) -> int:
    out: dict = {"at": datetime.now().isoformat(timespec="seconds"),
                 "margin_min": MARGIN_MIN}
    if os.geteuid() != 0:
        out["error"] = "must run as root; the wakealarm register is root-owned"
        print(json.dumps(out)); return 1
    if not WAKEALARM.exists():
        out["error"] = f"{WAKEALARM} does not exist -- no RTC wake on this node"
        print(json.dumps(out)); return 1

    intent = read_intent()
    if intent is None:
        out["action"] = "none"
        out["reason"] = "no intent recorded -- nothing to wake for"
        # An intent that has gone away should not leave a stale alarm behind.
        if current_alarm():
            try:
                WAKEALARM.write_text("0\n")
                out["cleared_stale_alarm"] = True
            except OSError as e:
                out["clear_failed"] = str(e)
        print(json.dumps(out)); return 0

    due = intent.get("due", "")
    out["due"] = due
    epoch = wake_epoch_for(due)
    if epoch is None:
        out["error"] = f"unparseable due {due!r}"
        print(json.dumps(out)); return 1

    now = datetime.now()
    if datetime.fromtimestamp(epoch) <= now:
        out["action"] = "none"
        out["reason"] = "wake time is already past; the machine is up anyway"
        print(json.dumps(out)); return 0

    have = current_alarm()
    if have == epoch:
        out["action"] = "none"
        out["reason"] = "already armed for this due"
        out["wake_epoch"] = epoch
        out["wake_local"] = datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
        print(json.dumps(out)); return 0

    ok, note = arm(epoch)
    out["action"] = "armed" if ok else "failed"
    out["previous_register"] = have
    out["wake_epoch"] = epoch
    out["wake_local"] = datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
    out["note"] = note
    rn = rtc_now()
    if rn:
        out["rtc_now"] = rn.isoformat(timespec="seconds")
    print(json.dumps(out))
    return 0 if ok else 1


def cmd_status(args) -> int:
    have = current_alarm()
    rn = rtc_now()
    intent = read_intent()
    print(json.dumps({
        "wakealarm_register": have,
        "wakealarm_local": (datetime.fromtimestamp(have).isoformat(timespec="seconds")
                            if have else None),
        "rtc_now": rn.isoformat(timespec="seconds") if rn else None,
        "system_now": datetime.now().isoformat(timespec="seconds"),
        "intent": intent,
        "margin_min": MARGIN_MIN,
        "caveat": ("waking from a full power-off also needs the firmware's RTC "
                   "alarm resume enabled. That is a BIOS setting and is not "
                   "readable here, so it is not claimed -- only measured."),
    }, indent=2))
    return 0


def cmd_clear(args) -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "must run as root"})); return 1
    try:
        WAKEALARM.write_text("0\n")
    except OSError as e:
        print(json.dumps({"error": str(e)})); return 1
    print(json.dumps({"cleared": True, "register": current_alarm()}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(required=True)
    sub.add_parser("sync", help="arm the RTC to the current intent").set_defaults(fn=cmd_sync)
    sub.add_parser("status", help="what the register holds").set_defaults(fn=cmd_status)
    sub.add_parser("clear", help="disarm").set_defaults(fn=cmd_clear)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
