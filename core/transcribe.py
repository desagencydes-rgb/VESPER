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

from core.rung_credentials import expand_rows

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

    def _candidates(self, privacy_class: str = "private") -> tuple:
        """Every permitted transcriber, in rung order, and every one refused.

        REUSES `MAY_CARRY`, like the speech planner. There is no local
        fallback here and that asymmetry is real: a synthesiser that may not
        speak can fall back to the machine's own voice, and a transcriber that
        may not transcribe has nothing to fall back to -- this locale is here
        precisely because the machine cannot do it.
        """
        from .gateway import MAY_CARRY
        permitted = MAY_CARRY.get(privacy_class, frozenset())
        rows, refused = [], []
        for row in self._supply:
            if _field(row, "purpose") != TRANSCRIBE_PURPOSE:
                continue
            cls = _field(row, "egress_class")
            rid = _field(row, "id") or _field(row, "provider_id") or "?"
            if cls in permitted:
                rows.append(row)
            else:
                refused.append(f"{rid}({cls})")
        return tuple(rows), tuple(refused)

    def choose(self, privacy_class: str = "private") -> tuple:
        """The FIRST permitted transcriber, kept for callers that want one row."""
        rows, refused = self._candidates(privacy_class)
        if rows:
            row = rows[0]
            return row, _field(row, "egress_class"), refused
        return None, None, refused

    def _transcribe_one(self, row: Any, data: bytes) -> dict:
        """One rung, one attempt. Returns a raw result dict, never raises.

        TWO WIRES, ONE SHAPE OUT. `cf_whisper` posts JSON with the audio
        base64-encoded and reads `result.text` / `result.transcription_info`;
        `groq_whisper` posts multipart/form-data -- Groq's audio endpoint is
        OpenAI-shaped, not JSON-body-shaped, and does not accept a base64
        string -- and reads `text` / `segments` / `language` at the top level.
        Both return through the same dict keys so the caller does not need to
        know which one answered.
        """
        rid = _field(row, "id") or "?"
        wire = _field(row, "wire") or "cf_whisper"
        key = _secret(_field(row, "credential_env") or "")
        if not key:
            return {"ok": False, "id": rid,
                    "reason": "no credential for the transcriber"}

        # THE LANGUAGE IS DETECTED, NOT DECLARED -- REVERSED 2026-09-03, and the
        # reversal is why the mechanism stays. It was declared `ar` because
        # Darija auto-detected as FRENCH on 2026-08-31. That no longer
        # reproduces on `whisper-large-v3-turbo`, and the override had become
        # the defect it was written to prevent: English and French audio came
        # back as "ترجمة نانسي قنقر", a Whisper hallucination, while Darija was
        # byte-identical with and without it across four samples. The row may
        # still declare `language` and it is honoured when present; nothing
        # does, by default, so detection decides.
        lang = _field(row, "language") or ""

        try:
            if wire == "groq_whisper":
                boundary = "----vesperTranscribeBoundary"
                parts = [
                    "--{b}\r\nContent-Disposition: form-data; "
                    "name=\"model\"\r\n\r\n{m}\r\n".format(
                        b=boundary, m=_field(row, "model") or ""),
                    "--{b}\r\nContent-Disposition: form-data; "
                    "name=\"response_format\"\r\n\r\nverbose_json\r\n".format(b=boundary),
                ]
                if lang:
                    parts.append(
                        "--{b}\r\nContent-Disposition: form-data; "
                        "name=\"language\"\r\n\r\n{l}\r\n".format(b=boundary, l=lang))
                parts.append(
                    "--{b}\r\nContent-Disposition: form-data; "
                    "name=\"file\"; filename=\"a.wav\"\r\n"
                    "Content-Type: audio/wav\r\n\r\n".format(b=boundary))
                body = "".join(parts).encode() + data + "\r\n--{b}--\r\n".format(b=boundary).encode()
                endpoint = _field(row, "endpoint") or ""
                req = urllib.request.Request(
                    endpoint, data=body, method="POST",
                    headers={"Authorization": f"Bearer {key}",
                             "User-Agent": "vesper/1.0",
                             "Content-Type": f"multipart/form-data; boundary={boundary}"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    out = json.loads(resp.read())
                text = out.get("text", "") or ""
                # GROQ NAMES A LANGUAGE ("English"); CLOUDFLARE NAMES A CODE
                # ("en"). `Transcript.language` means one thing regardless of
                # which rung answered, so this is where the two are
                # reconciled -- the owner speaks three languages and this maps
                # exactly those, rather than importing a general-purpose table
                # for languages nothing here will ever produce.
                lang_out = {"english": "en", "french": "fr", "arabic": "ar"}.get(
                    str(out.get("language") or "").strip().lower(),
                    str(out.get("language") or ""))
                return {"ok": bool(text.strip()), "id": rid, "text": text,
                        "seconds": float(out.get("duration") or 0.0),
                        "confidence": _confidence(out),
                        "language": lang_out, "language_probability": 0.0}

            account = _secret(_field(row, "account_env") or "")
            endpoint = (_field(row, "endpoint") or "").replace("{account}", account) \
                                                      .replace("{model}", _field(row, "model") or "")
            payload = {"audio": base64.b64encode(data).decode()}
            if lang:
                payload["language"] = lang
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                endpoint, data=body, method="POST",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.loads(resp.read())
            res = (out or {}).get("result") or {}
            text = res.get("text", "") or ""
            info = res.get("transcription_info") or {}
            return {"ok": bool(text.strip()), "id": rid, "text": text,
                    "seconds": float(info.get("duration") or 0.0),
                    "confidence": _confidence(res),
                    "language": str(info.get("language") or ""),
                    "language_probability": float(info.get("language_probability") or 0.0)}
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "id": rid, "reason": repr(exc)}

    def transcribe(self, audio: bytes | Path, *,
                   privacy_class: str = "private") -> Transcript:
        """Returns what was heard, or why it could not be.

        TRIES EVERY PERMITTED RUNG IN ORDER. The first one out of quota is not
        the last one available -- `transcribe.rung_failed` fires per rung that
        did not work, so a key nearing its limit is visible in the log even on
        a turn a later rung saved.

        NEVER RAISES INTO THE TURN. A failed transcription is silence, which is
        recoverable; an exception out of the listening path would take down the
        loop that is also how the owner types.
        """
        data = Path(audio).read_bytes() if isinstance(audio, (str, Path)) else audio
        rows, refused = self._candidates(privacy_class)
        if not rows:
            reason = (f"no transcriber may carry {privacy_class!r} content"
                      + (f"; refused {list(refused)}" if refused else
                         "; none is declared"))
            self._emit("transcribe.refused", {"privacy_class": privacy_class,
                                              "refused": list(refused),
                                              "reason": reason})
            return Transcript("", "none", None, ok=False, reason=reason)

        tried = []
        for i, row in enumerate(rows):
            cls = _field(row, "egress_class")
            result = self._transcribe_one(row, data)
            if result["ok"]:
                if i > 0:
                    self._emit("transcribe.rung_advanced",
                              {"tried_first": [_field(r, "id") for r in rows[:i]],
                               "heard_on": result["id"]})
                t = Transcript(
                    result["text"].strip(), result["id"], cls,
                    seconds=result.get("seconds", 0.0), ok=True, reason="",
                    confidence=result.get("confidence", 0.0),
                    language=result.get("language", ""),
                    language_probability=result.get("language_probability", 0.0))
                self._emit("transcribe.done", t.to_dict())
                return t
            tried.append(result)
            self._emit("transcribe.rung_failed",
                      {"id": result.get("id"), "reason": result.get("reason"),
                       "rungs_remaining": len(rows) - i - 1})

        self._emit("transcribe.exhausted",
                  {"rungs_tried": len(tried),
                   "reasons": [r.get("reason") for r in tried]})
        last = tried[-1] if tried else {}
        reason = last.get("reason") or "the transcriber returned nothing"
        return Transcript("", last.get("id", "none"),
                          _field(rows[-1], "egress_class") if rows else None,
                          ok=False, reason=reason)
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
        pass
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
    declared = [row for row in doc.get("provider", [])
                if row.get("purpose") == TRANSCRIBE_PURPOSE]

    # EVERY NUMBERED SIBLING OF A DECLARED ROW IS A RUNG, exactly as in
    # `core/speech.py`. `CLOUDFLARE_API_TOKEN_TRANSCRIBE`, `_2`, `_3`... and a
    # different provider entirely (`groq-transcribe`, its own `rung`) both
    # arrive through this same expansion.
    return expand_rows(declared, present=lambda env: bool(_secret(env)))
