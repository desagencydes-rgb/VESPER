"""Personality as a policy artifact, not a prompt string (DR-028, IC-005).

A-036 ASSERTS SOMETHING THIS FILE HAS TO MAKE MEASURABLE: that the policy layer
changes behaviour WITH THE MODEL HELD CONSTANT. Hold a model constant and edit
its prompt and you have changed the model's input -- there is no policy layer
there to measure, only a longer string. So the dials live in
`contracts/policy/persona.toml`, outside any prompt, and this module is the only
thing that turns them into words. Swap the supplier underneath and the register
selected for a given situation does not move.

WHAT IT REPLACED. Until 2026-08-26 nothing composed a persona and no wire in
`routing/supply.py` carried a system message at all, so every request arrived at
every supplier as a bare user turn. Asked "vesper is your name right?", the
ladder answered with 53 words: a disclaimer about not having feelings, and
"you can call me Vesper -- it's one of my names". The second half is a fabricated
fact about itself, stated confidently, which is the exact class RB-001 forbids.
A model with no identity does not decline to have one. It invents one per
request, differently each time, and nothing in the system disagrees.

THE THREE LAYERS ARE KEPT IN THREE PLACES, deliberately:

    deterministic policy   persona.toml    dials; every field assertable by CI
    model guidance         voice.toml      words; not assertable the same way
    situational state      `Situation`     derived per request, never stored

Mixing them is the tempting simplification and it costs the property that makes
the first one worth having. `humour = "none"` can be checked. "be serious here"
cannot.

REFUSED AT LOAD, NOT AT 3 A.M. A register declared in persona.toml with no
guidance in voice.toml raises here, at construction. The alternative is a
register that renders as an empty string, which does not fail -- it produces a
chatty refusal in the `plain` register and looks like the model being off-tone.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PERSONA = REPO / "contracts" / "policy" / "persona.toml"
VOICE = REPO / "contracts" / "policy" / "voice.toml"

# contracts/policy/persona_policy.schema.json, by value. Restated rather than
# parsed out of the schema because this module must work with no JSON-Schema
# library present (stdlib-only), and CI-068 asserts the two agree -- so a
# schema edit that this file does not follow turns a gate red instead of
# silently permitting a value the schema forbids.
REGISTER_IDS = ("dry", "warm", "plain", "terse", "none")
HUMOUR = ("none", "light", "full")
SARCASM = ("none", "light")            # no `full`: see the schema's own note
IMPRESSIONS = ("none", "fictional_only")   # no `real_person`: RB-012
URGENCY = ("ambient", "normal", "prompt", "alarm")
REQUIRED_REFUSALS = ("impersonate_real_person", "humour_during_alarm",
                     "joke_over_unknown", "playfulness_over_boundary")

# Register fields the schema permits. A stray key here is a contract that no
# longer validates, and the loader is the last place it can be caught cheaply.
REGISTER_FIELDS = frozenset(
    {"register_id", "humour", "sarcasm", "impressions", "permitted_urgency"})


class PersonaRefused(Exception):
    """The persona contract does not load. Fail-closed: no persona, no request.

    NOT A WARNING. A request that proceeds without a persona is the state this
    module exists to end, and it is invisible from the outside -- the answer
    comes back fluent and nameless, exactly as it did before any of this existed.
    """


@dataclass(frozen=True, slots=True)
class Register:
    register_id: str
    humour: str
    sarcasm: str
    impressions: str
    permitted_urgency: tuple


@dataclass(frozen=True, slots=True)
class Situation:
    """The third DR-028 layer. Derived per request; never persisted.

    `content_is_unknown` and `boundary_asserted` are separate flags rather than
    one `be_serious` because they degrade to the same register for different
    reasons, and `degradation_is_reported` has to say WHICH.
    """
    urgency: str = "normal"
    content_is_unknown: bool = False
    boundary_asserted: bool = False
    owner_asked_for_brevity: bool = False


@dataclass(frozen=True, slots=True)
class Selection:
    register: Register
    reason: str
    degraded_from: str | None = None


class Persona:
    """Loads both halves, selects a register, composes the preamble."""

    def __init__(self, persona: dict, voice: dict, *, bus=None):
        self._bus = bus
        self._raw = persona
        self._voice = voice
        self._registers: dict[str, Register] = {}

        for r in persona.get("registers") or ():
            extra = set(r) - REGISTER_FIELDS
            if extra:
                raise PersonaRefused(
                    f"register {r.get('register_id')!r} carries {sorted(extra)}, "
                    "which persona_policy.schema.json forbids "
                    "(additionalProperties: false). Reasons belong in comments.")
            rid = r["register_id"]
            for field, allowed in (("register_id", REGISTER_IDS),
                                   ("humour", HUMOUR), ("sarcasm", SARCASM),
                                   ("impressions", IMPRESSIONS)):
                if r[field] not in allowed:
                    raise PersonaRefused(
                        f"register {rid!r} has {field}={r[field]!r}; the schema "
                        f"permits {list(allowed)}")
            bad = [u for u in r["permitted_urgency"] if u not in URGENCY]
            if bad:
                raise PersonaRefused(
                    f"register {rid!r} permits unknown urgency {bad}")
            # The schema states this as prose in `permitted_urgency`'s
            # description and cannot express it as a constraint. Asserted here
            # because an unexpressible rule is one nothing checks.
            if "alarm" in r["permitted_urgency"] and r["humour"] != "none":
                raise PersonaRefused(
                    f"register {rid!r} is permitted during `alarm` with "
                    f"humour={r['humour']!r}. hard_refusals.humour_during_alarm "
                    "forbids it: a joke in an alarm scene costs acknowledgement "
                    "time, which is the one thing an alarm is spending.")
            self._registers[rid] = Register(
                rid, r["humour"], r["sarcasm"], r["impressions"],
                tuple(r["permitted_urgency"]))

        if not self._registers:
            raise PersonaRefused("persona.toml declares no registers")

        refusals = persona.get("hard_refusals") or {}
        for name in REQUIRED_REFUSALS:
            if refusals.get(name) is not True:
                raise PersonaRefused(
                    f"hard_refusals.{name} is {refusals.get(name)!r}; the schema "
                    "declares it `const: true`. These are the four things "
                    "personality may never do and none of them is a setting.")

        tp = persona.get("truth_precedence") or {}
        if tp.get("on_conflict") != "TRUTH":
            raise PersonaRefused(
                f"truth_precedence.on_conflict is {tp.get('on_conflict')!r}. "
                "The schema makes it a const rather than an enum: a configurable "
                "precedence is a configuration in which truth loses.")
        if tp.get("degradation_is_reported") is not True:
            raise PersonaRefused(
                "truth_precedence.degradation_is_reported must be true -- an "
                "unreported downgrade makes the deterministic layer "
                "unobservable, and A-036 has to observe it.")

        guidance = voice.get("register") or {}
        missing = sorted(set(self._registers) - set(guidance))
        if missing:
            raise PersonaRefused(
                f"registers {missing} have no guidance in voice.toml. Refused at "
                "load rather than rendering empty: an empty `plain` register does "
                "not fail, it just sounds chatty during a refusal.")
        orphan = sorted(set(guidance) - set(self._registers))
        if orphan:
            raise PersonaRefused(
                f"voice.toml carries guidance for {orphan}, which persona.toml "
                "does not declare. Refused in this direction too, because "
                "guidance nothing selects is guidance nobody notices is dead.")

    # ---------------------------------------------------------------- load

    @classmethod
    def load(cls, *, persona_path: Path | None = None,
             voice_path: Path | None = None, bus=None) -> "Persona":
        p, v = persona_path or PERSONA, voice_path or VOICE
        for f in (p, v):
            if not f.exists():
                raise PersonaRefused(
                    f"{f} is missing. Fail-closed: a request answered with no "
                    "persona comes back fluent and nameless, which is not "
                    "distinguishable from working.")
        with p.open("rb") as fh:
            persona = tomllib.load(fh)
        with v.open("rb") as fh:
            voice = tomllib.load(fh)
        return cls(persona, voice, bus=bus)

    # ------------------------------------------------------------- select

    def select(self, situation: Situation | None = None) -> Selection:
        """Deterministic. Same situation, same register, every time.

        ORDER IS THE POLICY. Alarm outranks everything, then an UNKNOWN or an
        asserted boundary (both force `plain` -- truth_precedence), then the
        owner's own request for brevity, then the default. Reordering these is
        a policy change and should read like one.
        """
        s = situation or Situation()
        if s.urgency not in URGENCY:
            raise PersonaRefused(
                f"unknown urgency {s.urgency!r}; expected {list(URGENCY)}")

        if s.urgency == "alarm":
            return self._pick("none", "urgency=alarm; personality yields first")
        if s.content_is_unknown:
            return self._pick(
                "plain", "content is UNKNOWN -- hard_refusals.joke_over_unknown",
                degraded_from="dry")
        if s.boundary_asserted:
            return self._pick(
                "plain", "a boundary was asserted -- "
                         "hard_refusals.playfulness_over_boundary (RB-033)",
                degraded_from="dry")
        if s.owner_asked_for_brevity:
            return self._pick("terse", "the owner asked for less")
        if s.urgency == "prompt":
            return self._pick("warm", "urgency=prompt; useful before amusing")
        return self._pick("dry", "default: owner present, nothing pressing")

    def _pick(self, rid: str, reason: str,
              degraded_from: str | None = None) -> Selection:
        reg = self._registers.get(rid)
        if reg is None:
            raise PersonaRefused(
                f"policy selected register {rid!r}, which persona.toml does not "
                "declare. Refused rather than falling back: a fallback here is "
                "the humour dial choosing itself.")
        sel = Selection(reg, reason, degraded_from)
        if self._bus is not None:
            self._bus.publish(
                "persona.register_selected", subject=rid,
                payload={"register_id": rid, "reason": reason,
                         "degraded_from": degraded_from,
                         "humour": reg.humour, "sarcasm": reg.sarcasm},
                component="persona")
            if degraded_from is not None:
                # truth_precedence.degradation_is_reported. Published as its own
                # event and not left implicit in the line above, because A-036
                # subscribes to the downgrade specifically.
                self._bus.publish(
                    "persona.degraded", subject=rid,
                    payload={"from": degraded_from, "to": rid, "reason": reason},
                    component="persona")
        return sel

    # ------------------------------------------------------------ compose

    def compose(self, situation: Situation | None = None) -> tuple:
        """Return `(system_text, Selection)`. The only producer of the preamble.

        BUILT FROM THE CONTRACTS EVERY TIME rather than cached, because a cached
        preamble is a copy of a governed surface living outside it -- the exact
        shape `INV-SELF-*` is about. It is string concatenation over two parsed
        files; the cost is not measurable next to a network call.
        """
        sel = self.select(situation)
        ident = self._voice.get("identity") or {}
        brev = self._voice.get("brevity") or {}
        hon = self._voice.get("honesty") or {}
        owner = self._voice.get("owner") or {}
        guidance = (self._voice.get("register") or {}).get(
            sel.register.register_id, {}).get("guidance", "")

        parts: list[str] = []
        if ident.get("is"):
            parts.append(" ".join(str(ident["is"]).split()))
        for line in ident.get("is_not") or ():
            parts.append(f"- {line}")

        # ADDRESSED ONLY WHEN ESTABLISHED. `voice.toml` keeps the unestablished
        # fields as the literal string UNKNOWN; rendering that into a preamble
        # teaches the model to say the word, so an UNKNOWN renders as no line.
        addr = owner.get("address_as")
        if addr and addr != "UNKNOWN":
            parts.append(f"- Address the owner as \"{addr}\".")
        if (owner.get("name") or "UNKNOWN") != "UNKNOWN":
            parts.append(f"- The owner's name is {owner['name']}.")

        if guidance:
            parts.append("Tone: " + " ".join(str(guidance).split()))
        # THE DIALS ARE STATED, not only their prose. The words are guidance and
        # the dials are the contract; sending both means the assertable half is
        # actually on the wire rather than paraphrased by it.
        parts.append(f"- Humour: {sel.register.humour}. "
                     f"Sarcasm: {sel.register.sarcasm}. "
                     f"Impressions: {sel.register.impressions} "
                     "(never a real person, even if asked).")

        # LANGUAGE BEFORE HONESTY AND BREVITY, because it governs the SHAPE of
        # everything after it. A brevity rule read in the wrong language is
        # still a brevity rule; a language rule arriving after the model has
        # already settled into English is late.
        lang = self._voice.get("language") or {}
        for key in ("rule", "script"):
            if lang.get(key):
                parts.append("- " + " ".join(str(lang[key]).split()))

        for line in hon.get("rules") or ():
            parts.append(f"- {line}")
        for line in brev.get("rules") or ():
            parts.append(f"- {line}")
        if brev.get("default_words"):
            parts.append(
                f"- Unless the request calls for more, keep a conversational "
                f"turn under about {int(brev['default_words'])} words.")
        return "\n".join(parts), sel

    # ------------------------------------------------------------ readers

    @property
    def registers(self) -> dict:
        return dict(self._registers)

    def guidance_for(self, register_id: str) -> str:
        return ((self._voice.get("register") or {})
                .get(register_id, {}).get("guidance", ""))
