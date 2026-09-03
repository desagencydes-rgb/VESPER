"""Darija speech IN -- our own route, because Apple's would bypass the redactor.

THE DECISION THIS IMPLEMENTS, from `docs/DECISION_LOG.md` 2026-08-31:

    Speech-IN, English  The machine's own recogniser, on-device. Already built.
    Speech-IN, Darija   Our own route, through the gateway. Apple has no
                        on-device Darija and its own path bypasses the redactor.

`app/island-macos/Listener.swift` already REFUSES to open the microphone for a
locale with no on-device recogniser, and refuses before opening it -- capturing
audio it would have to send away is worse than not capturing. Measured
2026-08-30: `en-US` has on-device recognition on this machine and `ar-MA`,
`ar-SA` and `fr-FR` do not. That refusal is why Darija speech has to come
through here instead.

AUDIO IS EGRESS, AND MORE OF IT THAN TEXT. A recording carries whatever was
said in the room, including things the owner did not mean to send, and unlike a
typed message nobody reviewed it first. So this obeys the same rule as every
other provider: `MAY_CARRY` decides which egress class may receive it, and the
supply row carries that class. It is not a separate routing system.

THE REDACTOR IS A TEXT TOOL AND THE TRANSCRIPT IS WHERE IT BELONGS. It runs on
the way into memory, on the ordinary path every utterance takes -- `core/updater.py`
calls `redact.scan()` before anything is written -- so a credential that reaches
here as speech is redacted exactly where a typed one is. That is the design, not
a compromise.

The one thing worth stating plainly: the AUDIO reaches the provider before any
of that, and no deterministic pass over a waveform can find a spoken secret.
That is a property of sending audio anywhere at all, not a gap in the redactor,
and it is the reason this route is confined to the same E1_PRIVATE suppliers
every other private content already goes to rather than the cheapest one
available.

WHAT COMES BACK IS ARABIC SCRIPT, which is what the transcriber produces for
Darija and is the right thing to hand the rest of the system: the memory,
selection and speech paths all handle it, and `core/arabizi.py` converts in the
other direction only at the speech boundary.
"""

from __future__ import annotations

import base64
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The purpose a supply row must declare to be considered a transcriber.
TRANSCRIBE_PURPOSE = "transcribe"

# Locales the machine's own recogniser handles on-device, measured 2026-08-30.
# Anything else must come through here or not at all.
ON_DEVICE_LOCALES = ("en-US", "en_US")


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    provider: str
    egress_class: str | None
    seconds: float = 0.0
    ok: bool = True
    reason: str = ""
    # MEASURED, NOT ASSUMED. `Intake` gates action on confidence and treats a
    # missing one as 0.0, which reflects every utterance back. Inventing a
    # number to get past that gate would be the declared-versus-measured error
    # on the one signal that decides whether VESPER ACTS on what it misheard.
    confidence: float = 0.0
    language: str = ""
    language_probability: float = 0.0

    def to_dict(self) -> dict:
        # THE TEXT IS NOT IN THE RECORD. What was said is memory's business, and
        # this record is about the routing decision -- the same split the speech
        # planner makes in the other direction.
        return {"provider": self.provider, "egress_class": self.egress_class,
                "chars": len(self.text), "seconds": self.seconds,
                "ok": self.ok, "reason": self.reason,
                "confidence": round(self.confidence, 3),
                "language": self.language,
                "language_probability": round(self.language_probability, 3)}


def needs_our_route(locale: str) -> bool:
    """Is this a locale the machine cannot transcribe by itself?

    ASKED AS A PROPERTY OF THE HOST, not of the language. An on-device Darija
    recogniser could ship in a macOS update, and the honest answer would change
    without this file changing -- the Swift side probes `supportsOnDeviceRecognition`
    for exactly that reason. This list is the measurement's record, and it is
    small enough to be re-measured rather than trusted.
    """
    return locale not in ON_DEVICE_LOCALES


class Transcriber:
    """Audio to text, through the ordinary supply rules."""

    def __init__(self, bus: Any = None, *, supply: list | None = None) -> None:
        self._bus = bus
        self._supply = list(supply or ())

    def choose(self, privacy_class: str = "private") -> tuple:
        """The permitted transcriber, and every one refused on the way.

        REUSES `MAY_CARRY`, like the speech planner. There is no local fallback
        here and that asymmetry is real: a synthesiser that may not speak can
        fall back to the machine's own voice, and a transcriber that may not
        transcribe has nothing to fall back to -- this locale is here precisely
        because the machine cannot do it.
        """
        from .gateway import MAY_CARRY
        permitted = MAY_CARRY.get(privacy_class, frozenset())
        refused = []
        for row in self._supply:
            if _field(row, "purpose") != TRANSCRIBE_PURPOSE:
                continue
            cls = _field(row, "egress_class")
            rid = _field(row, "id") or _field(row, "provider_id") or "?"
            if cls in permitted:
                return row, cls, tuple(refused)
            refused.append(f"{rid}({cls})")
        return None, None, tuple(refused)

    def transcribe(self, audio: bytes | Path, *,
                   privacy_class: str = "private") -> Transcript:
        """Returns what was heard, or why it could not be.

        NEVER RAISES INTO THE TURN. A failed transcription is silence, which is
        recoverable; an exception out of the listening path would take down the
        loop that is also how the owner types.
        """
        data = Path(audio).read_bytes() if isinstance(audio, (str, Path)) else audio
        row, cls, refused = self.choose(privacy_class)
        if row is None:
            reason = (f"no transcriber may carry {privacy_class!r} content"
                      + (f"; refused {list(refused)}" if refused else
                         "; none is declared"))
            self._emit("transcribe.refused", {"privacy_class": privacy_class,
                                              "refused": list(refused),
                                              "reason": reason})
            return Transcript("", "none", None, ok=False, reason=reason)

        rid = _field(row, "id") or "?"
        key = _secret(_field(row, "credential_env") or "")
        account = _secret(_field(row, "account_env") or "")
        if not key:
            return Transcript("", rid, cls, ok=False,
                              reason="no credential for the transcriber")
        endpoint = (_field(row, "endpoint") or "").replace("{account}", account) \
                                                  .replace("{model}", _field(row, "model") or "")
        # THE LANGUAGE IS DETECTED, NOT DECLARED -- REVERSED 2026-09-03, and the
        # reversal is why the mechanism stays. It was declared `ar` because
        # Darija auto-detected as FRENCH on 2026-08-31. That no longer
        # reproduces on `whisper-large-v3-turbo`, and the override had become
        # the defect it was written to prevent: English and French audio came
        # back as "ترجمة نانسي قنقر", a Whisper hallucination, while Darija was
        # byte-identical with and without it across four samples.
        #
        # "SAYING SO COSTS NOTHING" WAS THE WRONG PART. Declaring a language
        # costs every OTHER language the owner speaks, and this owner speaks
        # three. Forcing the wrong one does not degrade -- it INVENTS: forcing
        # `en` on Darija returns "What can you do for today's work?", fluent,
        # plausible, and not what was said. A mistranscription that looks like a
        # request is worse than one that looks like noise, because only the
        # second is obviously wrong.
        #
        # The row may still declare `language` and it is honoured when present.
        # What changed is that nothing declares it, so detection runs and the
        # detected language reaches `Transcript.language` with its probability
        # instead of being overwritten by a guess made in a contract file.
        payload = {"audio": base64.b64encode(data).decode()}
        lang = _field(row, "language") or ""
        if lang:
            payload["language"] = lang
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            self._emit("transcribe.failed", {"provider": rid, "error": repr(exc)})
            return Transcript("", rid, cls, ok=False, reason=repr(exc))

        res = (out or {}).get("result") or {}
        text = res.get("text", "") or ""
        info = res.get("transcription_info") or {}
        conf = _confidence(res)
        t = Transcript(
            text.strip(), rid, cls,
            seconds=float(info.get("duration") or 0.0),
            ok=bool(text.strip()),
            reason="" if text.strip() else "the transcriber returned nothing",
            confidence=conf,
            language=str(info.get("language") or ""),
            language_probability=float(info.get("language_probability") or 0.0))
        self._emit("transcribe.done", t.to_dict())
        return t

    def _emit(self, kind: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(kind, subject="transcribe", payload=payload,
                              component="transcribe")


def _confidence(result: dict) -> float:
    """A confidence from what the transcriber actually reported.

    `avg_logprob` is the mean log probability of the tokens in a segment, so
    `exp` of it is the geometric mean probability -- a real measure of how sure
    the model was, in the 0..1 range `Intake` compares against its floor.
    Duration-weighted, because a half-second segment and a ten-second one are
    not equal evidence.

    NO SEGMENTS MEANS 0.0, and that is the honest answer rather than a
    conservative-looking default: `Intake` reflects an utterance it cannot
    trust, which is exactly right when nothing measured the confidence. A
    fabricated 0.9 here would let VESPER act on a mishearing.

    `no_speech_prob` DISCOUNTS IT. A segment the model thinks is probably not
    speech should not contribute its token confidence as though it were.
    """
    segs = result.get("segments") or []
    total = weighted = 0.0
    for sg in segs:
        lp = sg.get("avg_logprob")
        if lp is None:
            continue
        dur = max(float(sg.get("end", 0)) - float(sg.get("start", 0)), 0.01)
        p = math.exp(max(float(lp), -20.0))
        p *= (1.0 - min(max(float(sg.get("no_speech_prob") or 0.0), 0.0), 1.0))
        weighted += p * dur
        total += dur
    return round(weighted / total, 4) if total else 0.0


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _secret(name: str) -> str:
    if not name:
        return ""
    try:
        from routing.supply import read_secrets
        return read_secrets().get(name, "") or ""
    except Exception:                              # noqa: BLE001
        return ""


def transcribe_rows(path: Path | None = None) -> list:
    """Declared transcribers, read from the contract.

    Not through `routing.supply.load_rows`, for the same reason the speech rows
    are not: that loader enforces INV-HW-2's measured-throughput rule, and a
    transcriber is not routed by tokens per second.
    """
    import tomllib
    p = path or (Path(__file__).resolve().parents[1]
                 / "contracts" / "policy" / "provider_supply.toml")
    try:
        doc = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for row in doc.get("provider", []):
        if row.get("purpose") != TRANSCRIBE_PURPOSE:
            continue
        env = row.get("credential_env", "")
        if env and not _secret(env):
            continue
        out.append(row)
    return out
