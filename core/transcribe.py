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

THE REDACTOR CANNOT READ AUDIO, and pretending otherwise would be the worse
error. A credential spoken aloud is in the waveform and no deterministic pass
over bytes will find it. What can be done is done: the TRANSCRIPT is redacted
before it becomes memory, on the ordinary path every utterance takes. What
cannot be done is stated here rather than glossed -- the audio itself reaches
the provider unredacted, and that is the cost of speech input on a machine with
no local Darija recogniser.

WHAT COMES BACK IS ARABIC SCRIPT, which is what the transcriber produces for
Darija and is the right thing to hand the rest of the system: the memory,
selection and speech paths all handle it, and `core/arabizi.py` converts in the
other direction only at the speech boundary.
"""

from __future__ import annotations

import base64
import json
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

    def to_dict(self) -> dict:
        # THE TEXT IS NOT IN THE RECORD. What was said is memory's business, and
        # this record is about the routing decision -- the same split the speech
        # planner makes in the other direction.
        return {"provider": self.provider, "egress_class": self.egress_class,
                "chars": len(self.text), "seconds": self.seconds,
                "ok": self.ok, "reason": self.reason}


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
        body = json.dumps({"audio": base64.b64encode(data).decode()}).encode()
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

        text = ((out or {}).get("result") or {}).get("text", "") or ""
        t = Transcript(text.strip(), rid, cls, ok=bool(text.strip()),
                       reason="" if text.strip() else "the transcriber returned nothing")
        self._emit("transcribe.done", t.to_dict())
        return t

    def _emit(self, kind: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(kind, subject="transcribe", payload=payload,
                              component="transcribe")


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
