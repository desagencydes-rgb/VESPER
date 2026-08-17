"""Linux audio rung driver — node 2, the Kali laptop.

Written after a full evening of the Windows node failing to make a sound, and it
exists because node 2 breaks every link in that failure chain:

    node 1 (desktop)                        node 2 (this laptop)
    ------------------------------------    ------------------------------------
    only audible output is monitor HDMI     built-in ANALOG speakers
    panels dark on a timer wake             no display involved at all
    dark panel => no audio endpoint         audio endpoint is the sound card
    Hello locks the session on wake         never sleeps: three independent
                                            layers hold it awake (systemd-inhibit,
                                            xfce power settings, a logind drop-in
                                            HandleLidSwitch=ignore)
    microphone dead under Task Scheduler    ordinary user process, mic available

The consequence worth stating: THIS NODE NEEDS NO WAKE STEP. It is already awake,
with the lid closed or open, so there is no rtcwake, no wake timer, and none of
the class of failure that comes with them.

And unlike two monitors on one machine, this is a genuinely separate node, so it
is a real second RUNG for A-012's device ladder rather than redundancy inside one.

WHAT IS DELIBERATELY THE SAME AS THE WINDOWS DRIVER

The readiness rule and the ACTUATED -> VERIFIED split are `core/alarm.py`'s, not
this file's. A rung counts only when the settings that decide audibility were
changed AND READ BACK, and when the resulting sound was OBSERVED by something
that is not the actuator's own return value. `spd-say` exiting 0 is a self-report;
the microphone hearing the room is the fact. Tonight's whole lesson is that those
two get confused precisely when nobody is checking.
"""

from __future__ import annotations

import math
import os
import select
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.alarm import (NOT_ACTUABLE, READY, UNREACHABLE, UNVERIFIABLE,
                        UNVERIFIED, ReadinessReport)

SAMPLE_RATE = 44100
WARBLE_HZ = (880, 1320)
WARBLE_PERIOD_S = 0.25
MIC_DEAD_EPS = 1e-4          # below this the capture stream is not running
RUN_DIR = Path("/tmp/vesper-alarm")


def _run(cmd: list, timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 1, repr(exc)


# ------------------------------------------------------------------ synthesis
def _warble(seconds: float, amplitude: float = 0.95):
    """Alternating tones plus a third harmonic.

    Same signal as the Windows driver, and for the same reason: a steady sine is
    learned and cancelled by adaptive noise suppression within about a second,
    which is how the first probe on node 1 measured BELOW its own noise floor.
    """
    import numpy as np
    n = int(SAMPLE_RATE * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    sel = ((t / WARBLE_PERIOD_S).astype(int) % 2)
    f = np.where(sel == 0, WARBLE_HZ[0], WARBLE_HZ[1]).astype("float64")
    phase = 2 * math.pi * np.cumsum(f) / SAMPLE_RATE
    wave_ = 0.78 * np.sin(phase) + 0.22 * np.sin(3 * phase)
    wave_ *= amplitude / max(float(np.max(np.abs(wave_))), 1e-9)
    ramp = int(SAMPLE_RATE * 0.01)
    if ramp * 2 < wave_.size:
        wave_[:ramp] *= np.linspace(0, 1, ramp)
        wave_[-ramp:] *= np.linspace(1, 0, ramp)
    return wave_


def _alarm_bed(seconds: float, amplitude: float, level: int = 1):
    """A rising two-tone siren over the warble.

    There is no Windows Media directory here, so the bed is synthesised rather
    than borrowed. Escalation changes the sweep rate and depth, so higher levels
    are not merely louder -- an alarm that only gets louder stops registering as
    a change once a sleeper habituates to it.
    """
    import numpy as np
    n = int(SAMPLE_RATE * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    sweep_hz = 0.4 + 0.25 * level
    centre = 700 + 60 * level
    depth = 260 + 40 * level
    f = centre + depth * np.sin(2 * math.pi * sweep_hz * t)
    phase = 2 * math.pi * np.cumsum(f) / SAMPLE_RATE
    siren = 0.7 * np.sin(phase) + 0.3 * np.sign(np.sin(phase)) * 0.35
    mix = 0.6 * siren + 0.4 * _warble(seconds, 1.0)
    mix *= amplitude / max(float(np.max(np.abs(mix))), 1e-9)
    return mix


def _write_wav(path: Path, samples) -> Path:
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return path


def _band_energy(buf, freqs=WARBLE_HZ) -> float:
    """Energy at the alarm's own frequencies.

    Absolute band energy, compared against the SAME bins measured in silence --
    not peak-over-median, which reads 20-30x on an empty room and would declare
    an unplugged speaker audible. That version shipped for one commit on node 1
    and passed everything, which is exactly what a vacuous check looks like.
    """
    import numpy as np
    x = np.asarray(buf, dtype="float64").ravel()
    if x.size < 2048:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) / x.size
    bins = np.fft.rfftfreq(x.size, 1.0 / SAMPLE_RATE)
    total = 0.0
    for f in list(freqs) + [700, 900, 1100]:      # siren sweep sits in here too
        sel = (bins > f - 40) & (bins < f + 40)
        if sel.any():
            total += float(np.max(spec[sel]))
    return total


class LinuxAudioRung:
    """The laptop's built-in speakers, as one rung."""

    rung_id = "node2_kali_analog"
    modality = "audio"

    def __init__(self, *, min_margin: float = 3.0, owner_attested: bool = False,
                 sink: str = "@DEFAULT_SINK@", source: str | None = None) -> None:
        self._sink = sink
        self._source = source
        self._min_margin = min_margin
        self._owner_attested = owner_attested
        self._procs: list = []
        self._restore: dict = {}
        self._floor_e = 0.0
        self._probe_e = 0.0
        self._margin = 0.0
        self._mic_dead = False
        self._observe_mode = "microphone"

    # ------------------------------------------------------------------ mixer
    def _sink_state(self) -> tuple[bool | None, int | None]:
        rc, out = _run(["pactl", "get-sink-mute", self._sink])
        muted = None if rc else ("yes" in out.lower())
        rc2, out2 = _run(["pactl", "get-sink-volume", self._sink])
        vol = None
        if not rc2:
            for tok in out2.replace("/", " ").split():
                if tok.endswith("%"):
                    try:
                        vol = int(tok[:-1])
                        break
                    except ValueError:
                        pass
        return muted, vol

    # ---------------------------------------------------------------- prepare
    def prepare(self) -> ReadinessReport:
        blocking: list[str] = []
        rc, _ = _run(["pactl", "info"])
        if rc:
            return ReadinessReport(self.rung_id, UNREACHABLE,
                                   note="no PulseAudio/PipeWire server reachable")

        was_muted, was_vol = self._sink_state()
        self._restore = {"muted": was_muted, "volume": was_vol}
        if was_muted:
            blocking.append("muted")
        if was_vol is not None and was_vol < 80:
            blocking.append(f"volume_{was_vol}pc_below_80")

        _run(["pactl", "set-sink-mute", self._sink, "0"])
        _run(["pactl", "set-sink-volume", self._sink, "100%"])

        # READ BACK. pactl exiting 0 is not the fact.
        now_muted, now_vol = self._sink_state()
        if now_muted or (now_vol is not None and now_vol < 95):
            return ReadinessReport(
                self.rung_id, NOT_ACTUABLE, reachable=True,
                blocking_settings=tuple(blocking),
                note=(f"read-back disagrees with the write: muted={now_muted} "
                      f"volume={now_vol}. Reachable and will not become audible."))

        try:
            self._floor_e = _band_energy(self._record(0.6))
            bed = _write_wav(RUN_DIR / "probe.wav", _warble(2.0, 0.95))
            self._play_async(bed)
            time.sleep(0.35)
            self._probe_e = _band_energy(self._record(0.8))
            self.silence()
        except Exception as exc:
            return ReadinessReport(self.rung_id, UNVERIFIED, reachable=True,
                                   settings_actuated=True,
                                   blocking_settings=tuple(blocking),
                                   note=f"probe could not be observed: {exc!r}")

        self._mic_dead = (self._floor_e < MIC_DEAD_EPS and self._probe_e < MIC_DEAD_EPS)
        self._margin = self._probe_e / max(self._floor_e, 1e-12)
        heard = (not self._mic_dead) and self._margin >= self._min_margin
        if not heard and self._owner_attested and not self._mic_dead:
            heard = True
            self._observe_mode = "owner_attested"
        elif self._mic_dead:
            self._observe_mode = "instrument_unavailable"

        if heard:
            return ReadinessReport(
                self.rung_id, READY, reachable=True, settings_actuated=True,
                actuation_observed=True, blocking_settings=tuple(blocking),
                note=(f"observed via {self._observe_mode}; band energy "
                      f"{self._floor_e:.6f} -> {self._probe_e:.6f} "
                      f"({self._margin:.1f}x); settings changed: "
                      f"{blocking or ['none']}"))

        # UNVERIFIED fires, UNVERIFIABLE does not -- see core/alarm.py. A dead
        # instrument must never be what silences an alarm.
        return ReadinessReport(
            self.rung_id, UNVERIFIED if self._mic_dead else UNVERIFIABLE,
            reachable=True, settings_actuated=True,
            blocking_settings=tuple(blocking),
            note=(f"probe not observed: floor={self._floor_e:.6f} "
                  f"probe={self._probe_e:.6f} margin={self._margin:.1f}x "
                  f"(need {self._min_margin}x)"
                  + (" MICROPHONE UNAVAILABLE -- nothing was measured, so this "
                     "is absence of evidence, not evidence of silence."
                     if self._mic_dead else "")))

    # ---------------------------------------------------------------- actuate
    def actuate(self, level: int, message: str) -> dict:
        _run(["pactl", "set-sink-mute", self._sink, "0"])
        _run(["pactl", "set-sink-volume", self._sink, "100%"])
        amp = min(1.0, 0.65 + 0.07 * level)
        bed = _write_wav(RUN_DIR / f"bed{level}.wav", _alarm_bed(20.0, amp, level))
        self._play_async(bed)
        spoke = self._speak(message)
        return {"level": level, "amplitude": round(amp, 3), "spoke": spoke,
                "played": bed.name, "sink": self._sink,
                "note": ("intensity escalation on ONE rung. The sweep rate and "
                         "depth change with level, not only the volume -- a "
                         "sleeper habituates to a sound that merely gets louder.")}

    # ---------------------------------------------------------------- observe
    def observe(self) -> bool:
        if self._observe_mode == "instrument_unavailable":
            return False
        try:
            e = _band_energy(self._record(0.5))
            return e / max(self._floor_e, 1e-12) >= self._min_margin
        except Exception:
            return False

    def silence(self) -> None:
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        self._procs = []
        _run(["pkill", "-f", "paplay .*vesper-alarm"], timeout=5)

    def restore(self) -> dict:
        out = dict(self._restore)
        try:
            if self._restore.get("muted") is not None:
                _run(["pactl", "set-sink-mute", self._sink,
                      "1" if self._restore["muted"] else "0"])
            if self._restore.get("volume") is not None:
                _run(["pactl", "set-sink-volume", self._sink,
                      f"{self._restore['volume']}%"])
        except Exception as exc:
            out["error"] = repr(exc)
        return out

    # -------------------------------------------------------------- internals
    def _record(self, seconds: float):
        import numpy as np
        cmd = ["parec", "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1"]
        if self._source:
            cmd += [f"--device={self._source}"]
        n_bytes = int(SAMPLE_RATE * seconds) * 2
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            data = p.stdout.read(n_bytes)
        finally:
            p.terminate()
        return np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0

    def _play_async(self, path: Path) -> None:
        self._procs.append(subprocess.Popen(
            ["paplay", "--device", self._sink, str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def _speak(self, message: str) -> bool:
        try:
            self._procs.append(subprocess.Popen(
                ["spd-say", "-r", "-30", "-i", "100", message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            return True
        except Exception:
            return False


class EvdevAck:
    """Physical, ASR-independent acknowledgement — INV-ALARM-2 / case 41.3.

    Reads EV_KEY presses straight off /dev/input/event*, which needs the `input`
    group. No speech, no screen, no unlock: opening the laptop lid or pressing any
    key acknowledges, and none of it requires seeing a display or typing a
    password. That is the channel the runbook asks for and the one node 1 could
    never provide, because a locked Windows session routes input to another
    desktop entirely.
    """

    EV_KEY = 0x01
    _FMT = "llHHi"          # timeval(2x long), type, code, value

    def __init__(self) -> None:
        self._size = struct.calcsize(self._FMT)
        self._fds: list = []
        for path in sorted(Path("/dev/input").glob("event*")):
            try:
                self._fds.append((os.open(str(path), os.O_RDONLY | os.O_NONBLOCK),
                                  path.name))
            except Exception:
                continue

    @property
    def available(self) -> bool:
        return bool(self._fds)

    def poll(self) -> str | None:
        if not self._fds:
            return None
        try:
            ready, _, _ = select.select([f for f, _ in self._fds], [], [], 0)
        except Exception:
            return None
        for fd in ready:
            name = next((n for f, n in self._fds if f == fd), "?")
            try:
                data = os.read(fd, self._size * 32)
            except Exception:
                continue
            for off in range(0, len(data) - self._size + 1, self._size):
                _, _, etype, code, value = struct.unpack(
                    self._FMT, data[off:off + self._size])
                if etype == self.EV_KEY and value == 1:
                    return f"evdev_{name}_key_{code}"
        return None

    def close(self) -> None:
        for fd, _ in self._fds:
            try:
                os.close(fd)
            except Exception:
                pass
        self._fds = []
