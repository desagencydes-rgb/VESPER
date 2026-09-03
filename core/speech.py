"""Saying it out loud -- the half of the turn VESPER could not do.

UNTIL NOW VESPER COULD NOT SPEAK. `say.jsonl` is the INBOUND channel: the
island and the home surface append what the owner said, and the runtime reads
it. The reply went to the transcript and was RENDERED. Nothing in the process
ever produced audio, so every voice decision in this corpus -- the persona's
brevity rules, the Darija script conversion, the interruption budget's `speech`
modality costing 8 -- governed a modality that did not exist.

A SYNTHESISER IS A PROVIDER, AND SPEAKING IS EGRESS. That is the constraint
that shapes this module. Sending a reply to an external voice service puts it on
that service's machines, and the corpus already has the rule: `MAY_CARRY` in
`core/gateway.py` says private and personal content may reach only an
`E1_PRIVATE` supplier. This module REUSES that rule rather than inventing an
allowlist beside it -- a second path to a provider is the shape `INV-COST-3`
refuses at the cost choke point, and the same reasoning applies to privacy.

LOCAL SYNTHESIS IS NOT A PROVIDER AT ALL. `/usr/bin/say` runs on this machine,
reaches no network and has no egress class, so it is always permitted. It is
also, measured 2026-08-31, WRONG FOR DARIJA: the system voices read 3, 7 and 9
as English numerals, which is the entire reason the script conversion exists.

SO THE FALLBACK IS REPORTED, NEVER SILENT. When privacy forces local synthesis
on content the local voice will mangle, the owner hears a degraded reply and has
no way to know why. `A-032` requires degradation to be visible; the plan carries
what was lost and why, exactly as block B reports a withheld fact.

THE SCRIPT IS CONVERTED HERE AND NOWHERE ELSE. `INV-NARRATE-2`, ratified
2026-08-31: the transliterated string goes to the synthesiser and stops there.
It never reaches the transcript, memory, or any surface the owner reads. What
is on screen stays what was written.

AND SPEAKING ALOUD IS AN EXPOSURE DECISION, not merely an output one. A reply
read into a room is heard by whoever is in it, so the plan runs through
`PrivacyRouter` first -- which is what `core/presence.py` was built to feed.
WITHHOLD means show it, do not say it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import tempfile
import tomllib

from core.rung_credentials import expand_rows
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .arabizi import looks_arabizi, transliterate
from .bus import EventBus
from .gateway import MAY_CARRY
from .privacy import WITHHOLD, PrivacyRouter

# Local synthesis. Not a provider: no network, no credential, no egress class,
# so no MAY_CARRY row can exclude it and none needs to.
LOCAL = "local"
LOCAL_BINARY = "/usr/bin/say"

# The purpose a supply row must declare to be considered a synthesiser. The
# supply table already keys rows by purpose for exactly this reason.
SPEECH_PURPOSE = "speech"

# What the local voice cannot say correctly. Measured 2026-08-31 by ear: the
# system voices read Arabizi digits as English numerals, so "3ndi" becomes
# "three-ndi". Arabic script is read as Arabic and is fine; Latin Darija is not.
LOCAL_MANGLES = "latin_darija_digits"

# The worse failure, found by ear on 2026-08-31 the moment this reached the
# live turn: converting to Arabic and handing it to a voice with no Arabic
# reads NOTHING. The owner heard the word "comma" in an English voice -- the
# synthesiser skipped every character it could not pronounce and vocalised the
# punctuation. Converting into a script the synthesiser cannot read turns a
# MISPRONUNCIATION into SILENCE, which is strictly worse.
NO_ARABIC_VOICE = "synthesiser_has_no_arabic_voice"

# Arabic locales as `say -v '?'` reports them.
_ARABIC_LOCALES = ("ar_", "ar-")

# THE OWNER'S CHOICES, READ FROM THE CONTRACT RATHER THAN GUESSED. They were
# decided by ear in the ~/VESPER-darija-ab A/B and lived only in that README,
# so the first version of this module defaulted to the system voice -- female,
# en_US, and it reads 3/7/9 as English numerals. That is the exact failure the
# comparison existed to avoid, reintroduced by not reading its outcome.
VOICE_CONTRACT = (Path(__file__).resolve().parents[1]
                  / "contracts" / "policy" / "voice.toml")


SUPPLY_CONTRACT = (Path(__file__).resolve().parents[1]
                   / "contracts" / "policy" / "provider_supply.toml")


def speech_rows(path: Path | None = None) -> list:
    """Declared synthesisers, read from the contract directly.

    NOT THROUGH `routing.supply.load_rows`, and the reason matters. That loader
    enforces INV-HW-2 for the TEXT ladder: a provider with no measured
    throughput is UNAVAILABLE, because routing by an unmeasured tokens/sec is
    routing on a guess. A synthesiser is not routed by throughput -- it is
    chosen by whether its egress class may carry the content -- so that gate
    drops every speech row for failing a test that does not apply to it.

    What DOES apply is still enforced here: a row with no credential present is
    not offered, because a synthesiser that cannot authenticate is one that
    will fail after the egress decision has already been made.
    """
    try:
        doc = tomllib.loads((path or SUPPLY_CONTRACT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    declared = [row for row in doc.get("provider", [])
                if row.get("purpose") == SPEECH_PURPOSE]

    def present(env: str) -> bool:
        return bool(os.environ.get(env) or _secret(env))

    # EVERY NUMBERED SIBLING OF A DECLARED ROW IS A RUNG. `ELEVENLABS_API_KEY`
    # is rung one; `ELEVENLABS_API_KEY_2`, `_3`, ... are additional free
    # accounts of the SAME provider, added by dropping a line into
    # `secrets.env` -- no row is written for them, `expand_rows` synthesises
    # one per credential it finds. See `core/rung_credentials.py`.
    return expand_rows(declared, present=present)


def _secret(name: str) -> str:
    """Read a credential from the owner's secrets file if it is not exported.

    The runtime loads these already; this exists so `Speech` works when it is
    constructed outside the runtime -- a check, a one-off script -- without
    each caller having to export the environment first.
    """
    if not name:
        return ""
    try:
        from routing.supply import read_secrets
        return read_secrets().get(name, "") or ""
    except Exception:                              # noqa: BLE001
        return ""


def synthesis_policy(path: Path | None = None) -> dict:
    """The `[synthesis]` block. Absent means no chosen voice, never a default.

    An empty dict makes `_voice_for` return "" and the host default speaks --
    which is the state that produced the bug. So the check asserts the block
    EXISTS rather than only that it is honoured.
    """
    try:
        return tomllib.loads((path or VOICE_CONTRACT)
                             .read_text(encoding="utf-8")).get("synthesis", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


@dataclass(frozen=True, slots=True)
class SpeechPlan:
    """What will be said, by what, in what script, and what was lost."""

    spoken: bool
    text: str                       # what the synthesiser receives
    display_text: str               # what the owner reads. Never the converted form.
    script_converted: bool
    synthesiser: str
    egress_class: str | None
    privacy_class: str
    surface: str
    voice: str = ""                 # the synthesiser's voice. "" = its default.
    rate: int = 0                   # words per minute. 0 = the voice's default.
    degraded: bool = False
    degradation: str = ""
    reason: str = ""
    candidates_refused: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"spoken": self.spoken, "synthesiser": self.synthesiser,
                "voice": self.voice, "rate": self.rate,
                "egress_class": self.egress_class,
                "privacy_class": self.privacy_class, "surface": self.surface,
                "script_converted": self.script_converted,
                "degraded": self.degraded, "degradation": self.degradation,
                "reason": self.reason,
                "candidates_refused": list(self.candidates_refused),
                # THE CONVERTED TEXT IS NOT IN THIS RECORD. It exists between
                # here and the synthesiser and nowhere else (INV-NARRATE-2).
                "chars": len(self.text)}


class Speech:
    """Decides whether to speak, in what script, and through what."""

    def __init__(self, bus: EventBus, router: PrivacyRouter | None = None,
                 *, supply: list | None = None) -> None:
        self._bus = bus
        self._router = router or PrivacyRouter(bus)
        # Rows from `contracts/policy/provider_supply.toml`. Absent means there
        # is no external synthesiser, which is the current state and is not an
        # error -- local synthesis still works.
        self._supply = list(supply or ())
        # Probed once per process. Installing a voice is a restart, not a turn.
        self._local_arabic: bool | None = None
        self._policy = synthesis_policy()

    # ------------------------------------------------------------------ plan

    def plan(self, reply: str, *, privacy_class: str = "private",
             persons: tuple = ("owner",), location_confidence: str = "high",
             available: tuple = ("private_earpiece",)) -> SpeechPlan:
        """Decide. Does not speak; `speak()` executes a plan.

        SEPARATED SO THE DECISION IS INSPECTABLE. A method that decided and
        spoke in one step could only be tested by listening, and every property
        worth asserting here -- the egress refusal, the script conversion, the
        reported degradation -- is a property of the decision.
        """
        route = self._router.route(privacy_class=privacy_class,
                                   persons=persons,
                                   location_confidence=location_confidence,
                                   available=available, subject="speech")
        if route.surface == WITHHOLD:
            plan = SpeechPlan(
                spoken=False, text="", display_text=reply,
                script_converted=False, synthesiser=LOCAL, egress_class=None,
                privacy_class=privacy_class, surface=WITHHOLD,
                reason=("the privacy router withheld this content from every "
                        "available surface, so it is shown and not said"))
            self._publish(plan)
            return plan

        # THE SYNTHESISER IS CHOSEN FIRST, AND THE SCRIPT SECOND. The first
        # version converted unconditionally and then picked a voice, which put
        # Arabic script into an English synthesiser and produced silence. The
        # script a text should be in is a property of WHO IS SAYING IT.
        synth, egress, refused = self._choose(privacy_class)
        arabic_ok = self._speaks_arabic(synth)

        # SCRIPT, AT THIS BOUNDARY ONLY. `display_text` keeps the owner's own
        # words; only `text` -- what the synthesiser hears -- is ever converted.
        is_darija = looks_arabizi(reply)
        converted = is_darija and arabic_ok
        spoken_text = transliterate(reply) if converted else reply

        degraded, degradation = False, ""
        if is_darija and not arabic_ok:
            # NOT CONVERTED, ON PURPOSE. The Latin is mispronounced -- the
            # digits are read as English numerals, which is the problem the
            # converter exists to solve -- but it is AUDIBLE. Converting here
            # would hand Arabic to a voice that has none and produce nothing.
            degraded, degradation = True, NO_ARABIC_VOICE
        elif synth == LOCAL and converted:
            degraded, degradation = True, LOCAL_MANGLES

        plan = SpeechPlan(
            spoken=True, text=spoken_text, display_text=reply,
            script_converted=converted, synthesiser=synth, egress_class=egress,
            voice=self._voice_for(synth, converted),
            rate=self._rate_for(synth, converted),
            privacy_class=privacy_class, surface=route.surface,
            degraded=degraded, degradation=degradation,
            candidates_refused=tuple(refused),
            reason=("local synthesis: no external synthesiser may carry "
                    f"{privacy_class!r} content" if synth == LOCAL and refused
                    else "" if synth == LOCAL else
                    f"external synthesiser {synth!r} may carry "
                    f"{privacy_class!r} content"))
        self._publish(plan)
        return plan

    def _speaks_arabic(self, synth: str) -> bool:
        """Can this synthesiser actually pronounce Arabic script?

        MEASURED FOR LOCAL, DECLARED FOR EXTERNAL, and never assumed for
        either. `say -v '?'` lists what is installed on THIS machine, so the
        answer is a property of the host and not of macOS -- an Arabic voice
        can be added, and then the conversion becomes correct here without any
        code change. An external row must declare `speaks_arabic = true`; the
        default is False, because the failure of a wrong guess is silence.
        """
        if synth == LOCAL:
            if self._local_arabic is None:
                self._local_arabic = self._probe_local_arabic()
            return self._local_arabic
        for row in self._supply:
            rid = self._field(row, "id") or self._field(row, "provider_id")
            if rid == synth:
                return bool(self._field(row, "speaks_arabic", False))
        return False

    def _rate_for(self, synth: str, arabic: bool) -> int:
        """Speaking rate, from the contract. 0 leaves the voice's own default.

        A SEPARATE VALUE PER SCRIPT, because they are separate voices with
        separate defaults -- and the English one was chosen at near-default
        pace in the jarvis A/B while the Arabic default measured too slow.
        """
        if synth != LOCAL:
            return 0
        key = "darija_local_rate" if arabic else "english_rate"
        try:
            return int(self._policy.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _voice_for(self, synth: str, arabic: bool) -> str:
        """The voice to speak this script in. Empty means the default.

        FOUND BY EAR, 2026-08-31, the first time this reached the live turn:
        the owner heard the single word "comma" in a woman's voice. The text
        was correct Arabic script and `say` used its DEFAULT voice, which is
        English -- so the synthesiser skipped every character it could not
        pronounce and vocalised the punctuation.
        
        Having an Arabic voice installed is not the same as USING it. The
        capability probe answers "can this host say Arabic"; this answers "which
        voice will actually be asked to", and only the second one makes a sound.
        """
        if synth != LOCAL:
            # The external voice is named in the contract, not discovered: the
            # owner picked it by ear and the id is the record of that choice.
            key = "darija_voice_id" if arabic else "english_voice_id"
            return self._policy.get(key, "") or self._policy.get("voice_id", "")
        installed = {n for n, _ in self._local_voices()}
        if arabic:
            # The recorded Arabic fallback, if it is actually installed.
            chosen = self._policy.get("darija_local_voice", "")
            if chosen and chosen in installed:
                return chosen
            for name, locale in self._local_voices():
                if any(locale.startswith(loc.rstrip("_-"))
                       for loc in _ARABIC_LOCALES):
                    return name
            return ""
        # ENGLISH IS A CHOICE TOO, and leaving it to the host default is what
        # gave the owner a voice they had already rejected in a written A/B.
        chosen = self._policy.get("english_voice", "")
        return chosen if chosen in installed else ""

    @staticmethod
    def _local_voices() -> list:
        """(name, locale) for every installed voice. Read, never assumed."""
        binary = shutil.which(LOCAL_BINARY) or shutil.which("say")
        if not binary:
            return []
        try:
            out = subprocess.run([binary, "-v", "?"], capture_output=True,
                                 timeout=10, text=True).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        rows = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "_" in parts[1]:
                rows.append((parts[0], parts[1]))
        return rows

    @staticmethod
    def _probe_local_arabic() -> bool:
        """Read the installed voices. An instrument's list, not a belief."""
        binary = shutil.which(LOCAL_BINARY) or shutil.which("say")
        if not binary:
            return False
        try:
            out = subprocess.run([binary, "-v", "?"], capture_output=True,
                                 timeout=10, text=True).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return any(loc in out for loc in _ARABIC_LOCALES)


    @staticmethod
    def _field(row: Any, name: str, default: Any = None) -> Any:
        """Read a field from a supply row, however the caller carries it.

        `routing/supply.py` builds `SupplyRow` dataclasses and the contract
        itself parses to dicts. Both are legitimate inputs -- the runtime passes
        the loaded rows, a test passes literals -- and requiring one shape would
        mean either the runtime converts or the tests build dataclasses. Neither
        earns anything.
        """
        if isinstance(row, dict):
            return row.get(name, default)
        return getattr(row, name, default)

    def _candidates(self, privacy_class: str) -> list:
        """Every PERMITTED row for this content, in the order to try them.

        `self._supply` already carries every rung of every declared provider
        -- `speech_rows()` expanded `ELEVENLABS_API_KEY`, `_2`, `_3`... into
        one row apiece -- so this is a filter, not a search: egress-permitted
        rows, in the order they were declared, which is rung order.
        """
        permitted = MAY_CARRY.get(privacy_class, frozenset())
        return [row for row in self._supply
                if self._field(row, "purpose") == SPEECH_PURPOSE
                and self._field(row, "egress_class") in permitted]

    def _choose(self, privacy_class: str) -> tuple:
        """The FIRST permitted synthesiser, and every one refused on the way.

        THIS PICKS FOR THE PLAN, NOT FOR THE CALL. `plan()` needs one id to
        decide the script and narrate the reason; `speak()` needs the whole
        ordered list, because the first rung may be out of characters this
        month and the second one is not. `_candidates` is that list;
        `_speak_external` walks it, this method reports only its head.

        REUSES `MAY_CARRY` RATHER THAN A LOCAL ALLOWLIST. An unknown privacy
        class yields an empty permitted set, so it falls to local -- absence is
        never permissive here, exactly as it is not in the cost policy.
        """
        cands = self._candidates(privacy_class)
        if cands:
            row = cands[0]
            return (self._field(row, "id") or self._field(row, "provider_id"),
                    self._field(row, "egress_class"), ())
        refused = [f"{self._field(row, 'id') or self._field(row, 'provider_id')}"
                  f"({self._field(row, 'egress_class')})"
                  for row in self._supply
                  if self._field(row, "purpose") == SPEECH_PURPOSE]
        return LOCAL, None, tuple(refused)

    def _publish(self, plan: SpeechPlan) -> None:
        self._bus.publish(
            "speech.planned", subject=plan.synthesiser,
            payload={**plan.to_dict(),
                     "note": ("a synthesiser is a provider and speaking is "
                              "egress, so the choice runs through the same "
                              "MAY_CARRY rule as any other model call")},
            component="speech")
        if plan.degraded:
            self._bus.publish(
                "speech.degraded", subject=plan.synthesiser,
                payload={"degradation": plan.degradation,
                         "privacy_class": plan.privacy_class,
                         "refused": list(plan.candidates_refused),
                         "note": ("the local voice reads Arabizi digits as "
                                  "English numerals. The owner hears a worse "
                                  "reply and this is why -- A-032: degradation "
                                  "is reported, never silent.")},
                component="speech")

    # ----------------------------------------------------------------- speak

    def _speak_one(self, row: dict, plan: SpeechPlan) -> dict:
        """One rung, one attempt. Never raises; the caller decides what a
        failure here means -- try the next rung, or report the turn spoken
        nowhere.
        """
        rid = self._field(row, "id") or self._field(row, "provider_id")
        key = os.environ.get(self._field(row, "credential_env") or "", "")
        if not key:
            key = _secret(self._field(row, "credential_env") or "")
        if not key:
            return {"spoke": False, "attempted": rid,
                    "reason": "no credential in the environment or secrets file"}
        endpoint = (self._field(row, "endpoint") or "").replace(
            "{voice}", plan.voice or self._policy.get("darija_voice_id", ""))
        body = json.dumps({"text": plan.text,
                           "model_id": self._field(row, "model") or ""}).encode()
        req = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"xi-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                audio = resp.read()
                code = resp.status
        except (urllib.error.URLError, OSError) as exc:
            return {"spoke": False, "attempted": rid, "reason": repr(exc)}
        out = Path(tempfile.gettempdir()) / f"vesper-speech-{os.getpid()}.mp3"
        out.write_bytes(audio)
        player = shutil.which("afplay")
        played = False
        if player:
            try:
                played = subprocess.run([player, str(out)],
                                        capture_output=True,
                                        timeout=120).returncode == 0
            except (OSError, subprocess.SubprocessError):
                played = False
        self._bus.publish(
            "speech.attempted", subject=rid,
            payload={"http_status": code, "bytes": len(audio),
                     "played": played, "chars": len(plan.text),
                     "voice": plan.voice,
                     "note": ("bytes returned is not a sound in the room; "
                              "`played` is the player's exit, which is also "
                              "not one")},
            component="speech")
        return {"spoke": played, "attempted": rid,
                "bytes": len(audio), "http_status": code}

    def _speak_external(self, plan: SpeechPlan) -> dict:
        """Try every permitted rung, in order, until one speaks.

        THE FIRST RUNG BEING OUT OF CHARACTERS IS NOT THE SAME EVENT AS EVERY
        RUNG BEING OUT. `speech.rung_failed` fires once per rung that did not
        work, so a key nearing its monthly cap is visible in the log even on a
        turn that a later rung saved -- otherwise "it always works" would keep
        being true right up until the turn nothing saves.

        THE CREDENTIAL NEVER TOUCHES THE TEXT PATH. It goes in a header; the
        body carries the reply and the model id and nothing else.

        AND EVERY RUNG FAILING IS A FAILURE, NOT SILENCE. Falling back to the
        local voice here would be a second routing decision taken at the worst
        moment -- after the egress check has already passed -- so the caller is
        told and the turn keeps its answer on screen.
        """
        candidates = self._candidates(plan.privacy_class)
        if not candidates:
            return {"spoke": False, "reason": f"no row for {plan.synthesiser!r}"}
        tried = []
        for i, row in enumerate(candidates):
            result = self._speak_one(row, plan)
            if result["spoke"]:
                if i > 0:
                    self._bus.publish(
                        "speech.rung_advanced", subject=result["attempted"],
                        payload={"tried_first": [self._field(r, "id")
                                                  or self._field(r, "provider_id")
                                                  for r in candidates[:i]],
                                 "spoke_on": result["attempted"]},
                        component="speech")
                return result
            tried.append(result)
            self._bus.publish(
                "speech.rung_failed", subject=result.get("attempted"),
                payload={"reason": result.get("reason"),
                         "rungs_remaining": len(candidates) - i - 1},
                component="speech")
        self._bus.publish(
            "speech.exhausted", subject=plan.synthesiser,
            payload={"rungs_tried": len(tried),
                     "reasons": [t.get("reason") for t in tried]},
            component="speech")
        return {"spoke": False, "attempted": plan.synthesiser,
                "rungs_tried": len(tried),
                "reason": tried[-1].get("reason") if tried else "no rung tried"}

    def speak(self, plan: SpeechPlan, *, voice: str | None = None) -> dict:
        """Execute a plan. Only local synthesis is implemented.

        AN EXTERNAL SYNTHESISER IS REFUSED RATHER THAN STUBBED. No supply row
        declares `purpose = "speech"` yet, so `plan()` cannot select one; if one
        is added and this method silently did nothing, the owner would hear
        nothing and the record would say it spoke.

        AND `say` EXITING 0 IS NOT A SOUND IN THE ROOM. The corpus already
        records that about `spd-say`. The return here reports what was ATTEMPTED
        and its exit status; it does not claim audio was produced.
        """
        if not plan.spoken:
            return {"spoke": False, "reason": plan.reason}
        if plan.synthesiser != LOCAL:
            return self._speak_external(plan)
        if not shutil.which(LOCAL_BINARY) and not shutil.which("say"):
            return {"spoke": False, "attempted": LOCAL,
                    "reason": "no local speech binary on this host"}
        cmd = [LOCAL_BINARY if shutil.which(LOCAL_BINARY) else "say"]
        # THE PLAN'S VOICE, not the host's default. An explicit override wins,
        # but the default of the default is what produced "comma".
        chosen = voice or plan.voice
        if chosen:
            cmd += ["-v", chosen]
        if plan.rate:
            cmd += ["-r", str(plan.rate)]
        cmd.append(plan.text)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            code = proc.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            return {"spoke": False, "attempted": LOCAL, "reason": repr(exc)}
        self._bus.publish("speech.attempted", subject=LOCAL,
                          payload={"exit_code": code, "chars": len(plan.text),
                                   "degraded": plan.degraded,
                                   "note": ("exit 0 means the command returned, "
                                            "not that a sound reached the room")},
                          component="speech")
        return {"spoke": code == 0, "attempted": LOCAL, "exit_code": code}
