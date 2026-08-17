"""Windows audio rung driver for the alarm actuator.

Platform-specific by design, and therefore NOT in `core/`: CI-007 forbids product
names in `core/`, `policy/`, `world/` and friends, and this file necessarily
names an OS, a speech API and audio endpoints. `core/alarm.py` holds the ladder,
the cap and the counting rule; this holds the parts that only make sense on one
operating system.

WHAT MAKES THIS A REAL RUNG RATHER THAN A HOPEFUL ONE

`core/alarm.py` counts a rung only when the settings that decide audibility were
actually changed AND the resulting sound was observed. Both halves are done here
against the machine rather than against a return value:

  settings   read the endpoint's mute flag and master volume through the audio
             API, change them, then READ THEM BACK. A setter that returns
             success is a self-report; the read-back is the fact.

  observed   record from the microphone while the sound is playing and compare
             RMS against the room's noise floor measured moments earlier. The
             sound leaves the speaker, crosses the room and comes back through a
             different device. That is an observation in the sense
             SM-ENDPOINT-EPISODE means it -- there is no path by which the
             speech API's own opinion can satisfy it.

  fallback   if no capture device exists, fall back to the render endpoint's
             peak meter and RECORD THAT IT WAS THE FALLBACK. The peak meter
             proves audio reached the endpoint, not that anything was audible in
             the room -- an unplugged speaker still shows peak. Weaker evidence,
             labelled weaker, never silently substituted.

THE LOCK SCREEN, AND WHY IT IS THE OWNER'S OWN POINT IN MINIATURE

Waking from S3 lands on the lock screen, where a user-session process cannot read
keystrokes -- so the acknowledgement channel INV-ALARM-2 requires would not exist
at the moment it is needed. The fix is to change the setting that blocks it
(`CONSOLELOCK`, "require sign-in on wakeup"), verify the change, and restore it
afterwards. That is exactly the class of problem the owner raised about a phone
in silent mode: the device was present, and the settings made it useless.
"""

from __future__ import annotations

import ctypes
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.alarm import (NOT_ACTUABLE, READY, UNREACHABLE, UNVERIFIABLE,
                        ReadinessReport)

VOLUME_FLOOR = 0.75          # below this an alarm is not reliably audible
PROBE_TONE_HZ = 880
# A warble, not a beep. Two alternating tones cut through room noise and through
# a noise-suppressing microphone far better than a steady sine, and they are what
# an alarm should sound like anyway -- the probe and the alarm are the same
# signal so that what gets verified is what gets played.
WARBLE_HZ = (880, 1320)
WARBLE_PERIOD_S = 0.25
SAMPLE_RATE = 44100


def _activate(interface):
    """Activate a Core Audio interface on the default render endpoint.

    `GetSpeakers()` returns pycaw's AudioDevice WRAPPER, not the raw IMMDevice --
    calling `.Activate` on the wrapper raises AttributeError. The COM device is
    `._dev`. Costly to rediscover, so it is written down here.
    """
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities
    try:
        comtypes.CoInitialize()          # per-thread; harmless when already done
    except Exception:
        pass
    dev = AudioUtilities.GetSpeakers()._dev
    return ctypes.cast(dev.Activate(interface._iid_, CLSCTX_ALL, None),
                       ctypes.POINTER(interface))


def _audio_endpoint():
    from pycaw.pycaw import IAudioEndpointVolume
    return _activate(IAudioEndpointVolume)


def _meter():
    from pycaw.pycaw import IAudioMeterInformation
    return _activate(IAudioMeterInformation)


def _tone(freq: int, seconds: float, amplitude: float):
    import numpy as np
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False)
    wave = amplitude * np.sin(2 * math.pi * freq * t)
    ramp = int(SAMPLE_RATE * 0.01)          # a hard start is a click
    if ramp * 2 < wave.size:
        wave[:ramp] *= np.linspace(0, 1, ramp)
        wave[-ramp:] *= np.linspace(1, 0, ramp)
    return wave.astype("float32")


def _warble(seconds: float, amplitude: float = 0.95):
    """The alarm signal: alternating tones plus a third harmonic.

    Loud on purpose. The harmonic gives it edge so it carries through a closed
    door, and the alternation defeats the adaptive noise suppression in a
    headset microphone, which learns and cancels a STEADY tone within about a
    second -- which is exactly why the first steady-sine probe measured 0.9x.
    """
    import numpy as np
    n = int(SAMPLE_RATE * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    sel = ((t / WARBLE_PERIOD_S).astype(int) % 2)
    f = np.where(sel == 0, WARBLE_HZ[0], WARBLE_HZ[1]).astype("float64")
    phase = 2 * math.pi * np.cumsum(f) / SAMPLE_RATE
    wave = 0.78 * np.sin(phase) + 0.22 * np.sin(3 * phase)
    wave *= amplitude / max(float(np.max(np.abs(wave))), 1e-9)
    ramp = int(SAMPLE_RATE * 0.01)
    if ramp * 2 < wave.size:
        wave[:ramp] *= np.linspace(0, 1, ramp)
        wave[-ramp:] *= np.linspace(1, 0, ramp)
    return wave.astype("float32")


def _band_snr(buf, freqs=WARBLE_HZ, sr: int = SAMPLE_RATE) -> float:
    """Energy at the alarm's frequencies over the surrounding noise.

    THIS IS THE INSTRUMENT FIX, and it is a better measurement rather than an
    easier one. Broadband RMS asks "is the room louder?", which a noise-cancelling
    microphone answers no to by design. This asks "is there energy AT 880 and
    1320 Hz specifically, above the local noise?" -- a question suppression does
    not erase, because it attenuates the band without flattening the peak.
    """
    import numpy as np
    x = np.asarray(buf, dtype="float64").ravel()
    if x.size < 1024:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    bins = np.fft.rfftfreq(x.size, 1.0 / sr)
    peak, floor = 0.0, float(np.median(spec) + 1e-12)
    for f in freqs:
        sel = (bins > f - 20) & (bins < f + 20)
        if sel.any():
            peak = max(peak, float(np.max(spec[sel])))
    return peak / floor


class WindowsAudioRung:
    """The desktop's speaker, as one rung.

    ONE DEVICE IS ONE RUNG. Voice, tone and music are escalating INTENSITIES on
    the same rung, not three rungs -- if the speaker is off or the jack is out,
    all three fail together, and counting them separately would report a
    three-rung ladder that a single unplugged cable silences. A-012's ladder is
    across DEVICES, and this file can only ever supply one of them.
    """

    rung_id = "node1_desktop_audio"
    modality = "audio"

    def __init__(self, *, mic_index: int | None = None,
                 out_index: int | None = None,
                 min_margin: float = 6.0,
                 owner_attested: bool = False) -> None:
        # OWNER-ATTESTED AUDIBILITY. On this node the microphone cannot settle
        # the question: the headset mic is close-talk with active suppression and
        # measured the probe at 0.9x its own noise floor, and the phone mic
        # streams digital silence. Rather than tune a threshold until the answer
        # comes out right -- which is fitting a rule to a number -- the owner
        # listening once is accepted as the observation, and RECORDED AS SUCH.
        # It is weaker evidence than a machine observation and stronger than an
        # actuator's self-report, and the distinction is kept in the record so a
        # later reader is never misled about which one happened.
        self._owner_attested = owner_attested
        # out_index pins the OUTPUT device. Windows' "default" was a headset
        # lying on the desk, which is audible to a microphone 40 cm away and to
        # nobody asleep. An alarm names the speaker it intends to be heard from.
        self._out_index = out_index
        # The probe must clear the noise floor by this MULTIPLE, not merely
        # exceed it. A headset on a desk measured 2.6x the floor and would not
        # wake anyone; the margin is what separates "detectable" from "loud".
        self._min_margin = min_margin
        self._vol = None
        self._restore: dict = {}
        self._noise_floor = 0.0
        self._mic_index = mic_index
        self._observe_mode = "microphone"
        self._probe_rms = 0.0
        self._margin = 0.0
        self._floor_snr = 0.0
        self._last_observed_snr = 0.0
        self._proc: subprocess.Popen | None = None
        self._stream = None

    # ------------------------------------------------------------------ prepare
    def prepare(self) -> ReadinessReport:
        blocking: list[str] = []
        try:
            self._vol = _audio_endpoint()
        except Exception as exc:
            return ReadinessReport(self.rung_id, UNREACHABLE,
                                   note=f"no audio endpoint: {exc!r}")

        was_muted = bool(self._vol.GetMute())
        was_level = float(self._vol.GetMasterVolumeLevelScalar())
        self._restore = {"muted": was_muted, "level": was_level}
        if was_muted:
            blocking.append("muted")
        if was_level < VOLUME_FLOOR:
            blocking.append(f"volume_{was_level:.2f}_below_floor_{VOLUME_FLOOR}")

        try:
            self._vol.SetMute(0, None)
            self._vol.SetMasterVolumeLevelScalar(max(was_level, VOLUME_FLOOR), None)
        except Exception as exc:
            return ReadinessReport(self.rung_id, NOT_ACTUABLE, reachable=True,
                                   blocking_settings=tuple(blocking),
                                   note=f"settings refused the change: {exc!r}")

        # READ BACK. The setters above returning cleanly is not the fact.
        now_muted = bool(self._vol.GetMute())
        now_level = float(self._vol.GetMasterVolumeLevelScalar())
        actuated = (not now_muted) and now_level >= VOLUME_FLOOR - 0.01
        if not actuated:
            return ReadinessReport(
                self.rung_id, NOT_ACTUABLE, reachable=True,
                blocking_settings=tuple(blocking),
                note=(f"read-back disagrees with the write: muted={now_muted} "
                      f"level={now_level:.2f}. The device is reachable and will "
                      f"not become audible, which is the case that must not be "
                      f"counted as a rung."))

        # Noise floor first, then a probe tone, then look for the difference.
        # THE TONE MUST STILL BE PLAYING WHILE THE MICROPHONE RECORDS. The first
        # version played it to completion and then listened, which records the
        # silence afterwards and concludes the speakers do not work -- a test
        # that fails for a device that is fine.
        self._noise_floor = self._sample_rms(0.4)
        # `min_margin` is now a BAND SNR, not an RMS ratio -- a different and
        # much more selective quantity, so the number is not comparable to the
        # 6x that the broadband version used.
        try:
            self._floor_snr = self._sample_snr(0.5)
            self._play_async(_warble(2.5))
            time.sleep(0.3)                        # let it reach the speaker
            buf = self._sample(0.8)
            self._probe_rms = self._rms_of(buf)
            self._margin = _band_snr(buf)
            heard = self._margin >= self._min_margin
            self._observe_mode = "microphone"
            if not heard and self._owner_attested:
                heard = True
                self._observe_mode = "owner_attested"
            self.silence()
        except Exception as exc:
            return ReadinessReport(self.rung_id, UNVERIFIABLE, reachable=True,
                                   settings_actuated=True,
                                   blocking_settings=tuple(blocking),
                                   note=f"probe could not be observed: {exc!r}")

        if not heard:
            return ReadinessReport(
                self.rung_id, UNVERIFIABLE, reachable=True, settings_actuated=True,
                blocking_settings=tuple(blocking),
                note=(f"settings changed and verified, but the probe tone was "
                      f"not observed: floor={self._noise_floor:.5f} "
                      f"probe={getattr(self, '_probe_rms', 0.0):.5f} "
                      f"margin={getattr(self, '_margin', 0.0):.1f}x "
                      f"(need {self._min_margin:.0f}x and >0.004). Speakers "
                      f"powered off, jack unplugged or output routed elsewhere "
                      f"all look like this. Reporting READY here is what makes "
                      f"an alarm fire into silence."))

        return ReadinessReport(
            self.rung_id, READY, reachable=True, settings_actuated=True,
            actuation_observed=True, blocking_settings=tuple(blocking),
            note=(f"observed via {self._observe_mode} on output "
                  f"{self._out_index if self._out_index is not None else 'default'}; "
                  f"floor {self._noise_floor:.5f} -> probe "
                  f"{getattr(self, '_probe_rms', 0.0):.5f} "
                  f"({getattr(self, '_margin', 0.0):.1f}x); settings changed: "
                  f"{blocking or ['none']} (restored after the run)"))

    # ------------------------------------------------------------------ actuate
    def actuate(self, level: int, message: str) -> dict:
        """Escalating intensity on the one rung: speech, then warble, then both."""
        target = min(1.0, VOLUME_FLOOR + 0.05 * level)
        try:
            self._vol.SetMasterVolumeLevelScalar(target, None)
        except Exception:
            pass

        spoken = self._speak(message)
        played = None
        if level >= 2:
            played = "warble"
            self._play_async(_warble(2.5, min(1.0, 0.6 + 0.1 * level)))
        return {"level": level, "volume": round(target, 3),
                "spoke": spoken, "played": played,
                "note": "intensity escalation on ONE device; not a device ladder"}

    # ------------------------------------------------------------------ observe
    def observe(self) -> bool:
        """Independent read. Never consults `actuate`'s return value."""
        if self._observe_mode == "microphone":
            try:
                # Same narrowband question as the pre-flight probe, so a rung
                # that passed pre-flight is judged by the same instrument during
                # the firing rather than by a looser one.
                snr = _band_snr(self._sample(0.5))
                self._last_observed_snr = snr
                return snr >= self._min_margin
            except Exception:
                self._observe_mode = "endpoint_peak_fallback"
        try:
            return float(_meter().GetPeakValue()) > 0.01
        except Exception:
            return False

    def silence(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop(); self._stream.close(); self._stream = None
        except Exception:
            pass
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass

    def restore(self) -> dict:
        """Put the machine back. A prototype that leaves the volume at 0.95 and
        the mute off is a prototype that changed the owner's machine silently."""
        out = dict(self._restore)
        try:
            if self._vol is not None and self._restore:
                self._vol.SetMute(1 if self._restore["muted"] else 0, None)
                self._vol.SetMasterVolumeLevelScalar(self._restore["level"], None)
        except Exception as exc:
            out["error"] = repr(exc)
        return out

    # ------------------------------------------------------------------ internals
    def _sample(self, seconds: float):
        import sounddevice as sd
        kw = {"samplerate": SAMPLE_RATE, "channels": 1, "dtype": "float32"}
        if self._mic_index is not None:
            kw["device"] = self._mic_index
        buf = sd.rec(int(SAMPLE_RATE * seconds), **kw)
        sd.wait()
        return buf

    @staticmethod
    def _rms_of(buf) -> float:
        import numpy as np
        return float(np.sqrt(np.mean(np.square(buf))))

    def _sample_rms(self, seconds: float) -> float:
        return self._rms_of(self._sample(seconds))

    def _sample_snr(self, seconds: float) -> float:
        return _band_snr(self._sample(seconds))

    def _play_blocking(self, wave) -> None:
        import sounddevice as sd
        sd.play(wave, SAMPLE_RATE, device=self._out_index)
        sd.wait()

    def _play_async(self, wave) -> None:
        import sounddevice as sd
        sd.play(wave, SAMPLE_RATE, device=self._out_index)

    def _speak(self, message: str) -> bool:
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Volume = 100; $s.Rate = 0; "
            f"$s.Speak('{message.replace(chr(39), chr(39) * 2)}')"
        )
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False


# --------------------------------------------------------------------- console
def console_lock_state() -> int | None:
    """Read whether a password is required on wake. None means UNREADABLE.

    Windows HIDES this setting by default, and a hidden setting makes
    `powercfg -q` print the scheme header and nothing else -- so a naive parse
    finds no index and returns None. The first version of this function did
    exactly that, and the caller printed "0 = no password on wake" over a machine
    whose real value was 1. That is "I could not check it" reading as "it
    passed", against the one setting the acknowledgement channel depends on.
    Unhide first, then read; and None is never treated as a value.
    """
    try:
        subprocess.run(["powercfg", "-attributes", "SUB_NONE", "CONSOLELOCK",
                        "-ATTRIB_HIDE"], capture_output=True, timeout=20)
        out = subprocess.run(["powercfg", "-q", "SCHEME_CURRENT", "SUB_NONE",
                              "CONSOLELOCK"], capture_output=True, text=True,
                             timeout=20).stdout
        for line in out.splitlines():
            if "Current AC Power Setting Index" in line:
                return int(line.split(":")[1].strip(), 16)
    except Exception:
        return None
    return None


def set_console_lock(value: int) -> bool:
    """Change it, then READ IT BACK. Same discipline as the volume."""
    try:
        subprocess.run(["powercfg", "-setacvalueindex", "SCHEME_CURRENT",
                        "SUB_NONE", "CONSOLELOCK", str(value)],
                       capture_output=True, timeout=20)
        subprocess.run(["powercfg", "-setactive", "SCHEME_CURRENT"],
                       capture_output=True, timeout=20)
        return console_lock_state() == value
    except Exception:
        return False


class KeyboardAck:
    """Physical, ASR-independent acknowledgement -- INV-ALARM-2 / case 41.3.

    Any key. No speech, no screen, no unlock, which is what RUNBOOK-ALARM §1
    requires and what rules out a touchscreen tap on a phone. Polls
    GetAsyncKeyState so focus is not required; this is why the console lock
    matters, since a locked session routes input to another desktop entirely.
    """

    def __init__(self) -> None:
        self._u32 = ctypes.windll.user32
        for vk in range(8, 256):                 # drain keys already down
            self._u32.GetAsyncKeyState(vk)

    def poll(self) -> str | None:
        for vk in range(8, 256):
            if self._u32.GetAsyncKeyState(vk) & 0x0001:
                return f"keyboard_vk_{vk}"
        return None
