"""Arm, fire and stand down the prototype alarm.

    python tools/ops/alarm_night.py preflight
    python tools/ops/alarm_night.py arm   --at "2026-08-18 09:00" --wake-margin-min 10
    python tools/ops/alarm_night.py fire  --at "2026-08-18 09:00"
    python tools/ops/alarm_night.py stand-down

`arm` schedules the machine to WAKE ITSELF from S3 and then runs `fire`, which
evaluates the shipped `trg_alarm_fire` predicate and hands off to the actuator.

THE WAKE TIMER SUPPLIES POWER. THE PREDICATE SUPPLIES THE DECISION.

That split is the whole design. A scheduled task that speaks at 09:00 would be a
SCHEDULE-class actuation with no lease, no acknowledgement channel and no logged
escalation -- exactly the shape CI-026 exists to catch, and a second alarm path
that no gate in the tree scans. So the task's only job is to make the machine
running and awake; whether the alarm fires is then decided by the same COMPOSITE
predicate the trigger registry ships, evaluated by the same PredicateEvaluator
the autonomy loop uses, which returns FALSE on any UNKNOWN term.

STATUS OF ANY RUN PRODUCED HERE: prototype, `gate_evidence = false`.
A-012 needs escalation across a DEVICE ladder and this node supplies one device.
The RUNBOOK-ALARM validation night additionally needs the owner genuinely asleep
and NOT knowing the firing time; an alarm set for a time the owner chose is a
smoke test of the actuator, which is worth having and is not the same thing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.alarm import AlarmActuator, AlarmInstance, build_alarm_trigger
from tools.ops.alarm_node_win import (KeyboardAck, WindowsAudioRung,
                                      console_lock_state, set_console_lock)

TASK_NAME = "VESPER-Alarm-Prototype"
STATE_DIR = REPO / ".alarm-state"
WINDOW_S = 1800          # the alarm remains due for 30 minutes


def _emitter(records: list):
    def emit(kind: str, payload: dict) -> None:
        rec = {"kind": kind, "at_wall": datetime.now().isoformat(timespec="seconds"),
               "payload": payload}
        records.append(rec)
        print(f"[{rec['at_wall']}] {kind}: "
              f"{json.dumps(payload, default=str)[:220]}", flush=True)
    return emit


def _out_list(spec) -> list:
    """"6,5" -> [6, 5]. Order matters only for logging; both sound together."""
    if spec in (None, ""):
        return []
    if isinstance(spec, int):
        return [spec]
    return [int(x) for x in str(spec).replace(" ", "").split(",") if x != ""]


def _dev_args(args) -> str:
    out = ""
    if getattr(args, "output_device", None) is not None:
        out += f" --output-device {args.output_device}"
    if getattr(args, "mic_device", None) is not None:
        out += f" --mic-device {args.mic_device}"
    if getattr(args, "attest_audible", False):
        out += " --attest-audible"
    if getattr(args, "min_margin", 6.0) != 6.0:
        out += f" --min-margin {args.min_margin}"
    return out


def _save(name: str, body: dict) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / name
    p.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    return p


# --------------------------------------------------------------------- preflight
def cmd_devices(args) -> int:
    import sounddevice as sd
    seen = set()
    print("OUTPUTS (pin one with --output-device N):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and d["name"] not in seen:
            seen.add(d["name"])
            print(f"  {i:>3} | {d['name']} | {d['max_output_channels']}ch")
    print("INPUTS (--mic-device N):")
    seen.clear()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["name"] not in seen:
            seen.add(d["name"])
            print(f"  {i:>3} | {d['name']}")
    return 0


def cmd_preflight(args) -> int:
    records: list = []
    emit = _emitter(records)
    rung = WindowsAudioRung(out_indices=_out_list(args.output_device),
                            mic_index=args.mic_device,
                            min_margin=args.min_margin,
                            owner_attested=args.attest_audible)
    act = AlarmActuator([rung], emit=emit)
    report = act.preflight()
    report["observation_channel"] = rung._observe_mode
    lock = console_lock_state()
    report["console_lock_on_wake"] = lock
    report["console_lock_note"] = {
        1: ("1 = a password is required on wake, so the session is locked and a "
            "user-process cannot read the acknowledgement keypress. `arm` clears "
            "it for the night and `stand-down` restores it."),
        0: "0 = no password on wake; the acknowledgement keypress is readable.",
    }.get(lock, ("UNREADABLE. This is NOT 'fine' -- it is an unverified "
                 "acknowledgement channel, which INV-ALARM-2 makes load-bearing. "
                 "Arming on an unreadable value would be asserting a channel "
                 "nobody checked."))
    report["ack_channel_verified"] = lock == 0
    restored = rung.restore()
    report["volume_restored_to"] = restored
    _save("preflight.json", {"records": records, "report": report})
    print("\n" + json.dumps(report, indent=2, default=str))
    return 0 if report["ladder_depth"] else 1


# --------------------------------------------------------------------------- arm
def cmd_arm(args) -> int:
    due = datetime.strptime(args.at, "%Y-%m-%d %H:%M")
    wake = due - timedelta(minutes=args.wake_margin_min)
    prior_lock = console_lock_state()
    cleared = set_console_lock(0) if prior_lock == 1 else (prior_lock == 0)

    ps = f"""
$act = New-ScheduledTaskAction -Execute '{sys.executable}' `
  -Argument '"{REPO / 'tools' / 'ops' / 'alarm_night.py'}" fire --at "{args.at}"{_dev_args(args)}' `
  -WorkingDirectory '{REPO}'
$trg = New-ScheduledTaskTrigger -Once -At '{wake.strftime('%Y-%m-%dT%H:%M:%S')}'
$set = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -StartWhenAvailable
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $act -Trigger $trg `
  -Settings $set -Force | Out-Null
(Get-ScheduledTask -TaskName '{TASK_NAME}').Settings.WakeToRun
"""
    r = subprocess.run(["powershell", "-NonInteractive", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=120)
    wake_to_run = "true" in (r.stdout or "").lower()

    out = {
        "due": args.at, "wake_at": wake.strftime("%Y-%m-%d %H:%M"),
        "task": TASK_NAME,
        "wake_to_run_confirmed": wake_to_run,
        "console_lock_prior": prior_lock, "console_lock_cleared": cleared,
        "stderr": (r.stderr or "").strip()[:400],
        "note": ("The task supplies power only. `fire` re-evaluates "
                 "trg_alarm_fire's predicate on wake and will NOT sound if the "
                 "predicate is false or any term is UNKNOWN."),
        "owner_action": "Leave speakers on and volume up, then let the machine sleep.",
    }
    _save("armed.json", out)
    print(json.dumps(out, indent=2))
    if not wake_to_run:
        print("\nWAKE NOT CONFIRMED -- the task exists but WakeToRun did not read "
              "back true. Do not rely on this to wake you.", file=sys.stderr)
        return 1
    return 0


# -------------------------------------------------------------------------- fire
def cmd_fire(args) -> int:
    from core.autonomy import PredicateEvaluator, anti_cron_probe
    from core.bus import EventBus
    from core.hlc import HybridLogicalClock
    from core.world import Observation, WorldModel

    records: list = []
    emit = _emitter(records)
    due = datetime.strptime(args.at, "%Y-%m-%d %H:%M").timestamp()
    alarm = AlarmInstance(alarm_id="alarm_prototype_1", due_epoch_s=due,
                          window_s=WINDOW_S,
                          label=args.message)

    rung = WindowsAudioRung(out_indices=_out_list(args.output_device),
                            mic_index=args.mic_device,
                            min_margin=args.min_margin,
                            owner_attested=args.attest_audible)
    act = AlarmActuator([rung], emit=emit)
    pre = act.preflight()
    pre["observation_channel"] = rung._observe_mode
    if not pre["ladder_depth"]:
        _save("fire-result.json", {"records": records, "result": pre})
        print("NO ACTUABLE RUNG -- refusing to report a fire that nobody hears.",
              file=sys.stderr)
        return 2

    bus = EventBus.__new__(EventBus)          # bus only for the evaluator's emits
    try:
        bus.__init__()                        # type: ignore[misc]
    except Exception:
        pass
    clock = HybridLogicalClock("alarm_node")
    world = WorldModel(bus, clock, now_ms=lambda: int(time.time() * 1000))
    ev = PredicateEvaluator(bus, world)
    trigger = build_alarm_trigger(alarm, holds_lease=lambda: True,
                                  partition_suspected=lambda: False)

    probe = anti_cron_probe(trigger)
    emit("alarm.anti_cron_probe", probe)
    if probe["fires_on_clock_alone"]:
        print("REFUSED: the alarm trigger fires on the clock alone; that is cron.",
              file=sys.stderr)
        return 3

    ack = KeyboardAck()
    deadline = due + WINDOW_S
    result = {"fired": False, "reason": "window elapsed without the predicate firing"}

    while time.time() < deadline:
        now_ms = int(time.time() * 1000)
        ttl = now_ms + 120_000
        for subj, attr, val in (
            ("alarms", "holds_fire_lease", True),
            ("alarms", "acknowledged", bool(alarm.acknowledged)),
            ("world.fabric", "partition_suspected", False),
        ):
            world.apply(Observation(subj, attr, val, clock.now(),
                                    source="alarm_node", trust_class="verified_local",
                                    valid_until_ms=ttl))
        snap = ev.snapshot(trigger.state_terms)
        snap["schedule.now_in_alarm_window"] = alarm.now_in_window(time.time())
        emit("alarm.predicate_snapshot", snap)

        if ev.evaluate(trigger, snap):
            result = act.fire(alarm, acknowledged=ack.poll)
            break
        time.sleep(5)

    result["preflight"] = pre
    result["console_lock_at_fire"] = console_lock_state()
    result["volume_restored_to"] = rung.restore()
    result["gate_evidence"] = False
    _save("fire-result.json", {"records": records, "result": result})
    print("\n" + json.dumps(result, indent=2, default=str)[:2000])
    return 0


# ------------------------------------------------------------------- stand-down
def cmd_stand_down(args) -> int:
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                   capture_output=True, timeout=60)
    restored = set_console_lock(1)
    out = {"task_deleted": True, "console_lock_restored_to_1": restored,
           "console_lock_now": console_lock_state()}
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)

    def audio_opts(sp):
        sp.add_argument("--output-device", default=None,
                        help="output device index, or several comma-separated "
                             "to sound them together (e.g. 6,5)")
        sp.add_argument("--mic-device", type=int, default=None)
        sp.add_argument("--attest-audible", action="store_true",
                        help="the owner confirmed BY EAR that this output is "
                             "loud enough. Recorded as observation_channel="
                             "owner_attested, never as a machine observation.")
        sp.add_argument("--min-margin", type=float, default=6.0,
                        help="probe RMS must exceed the noise floor by this "
                             "multiple to count as audible")
        return sp

    audio_opts(sub.add_parser("preflight")).set_defaults(fn=cmd_preflight)
    a = audio_opts(sub.add_parser("arm")); a.set_defaults(fn=cmd_arm)
    a.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM"')
    a.add_argument("--wake-margin-min", type=int, default=10)
    f = audio_opts(sub.add_parser("fire")); f.set_defaults(fn=cmd_fire)
    f.add_argument("--at", required=True)
    f.add_argument("--message", default="Good morning. It is nine o'clock, "
                                        "Tuesday the eighteenth of August. "
                                        "Press any key to acknowledge.")
    sub.add_parser("stand-down").set_defaults(fn=cmd_stand_down)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
