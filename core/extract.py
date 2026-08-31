"""Turning what the owner SAID into what VESPER KNOWS.

WITHOUT THIS, MEMORY IS A TRANSCRIPT. `core/updater.py` stores every utterance
verbatim at rank 4 and has always had an `extractor` slot for the second half --
the reading that turns "sami ghadi lmdrasa nhar sebt m3a 3 dial l3chia" into a
fact ABOUT SAMI. Nothing ever filled that slot, so on 2026-08-31 the owner told
VESPER a fact, asked it to remember, and was answered UNKNOWN: the sentence was
in memory and the fact was not. Sixteen rows, every one of them `owner/said`.

RETRIEVAL IS WHY THIS MATTERS, not tidiness. Block B selects on the question's
own words. A sentence filed under `owner/said` is found only by someone who
already remembers the sentence; a fact filed under `sami/school_day` is found by
asking about Sami. Storing without extracting produces a memory that can only
answer questions whose answer you already knew.

IT IS A MODEL AND IS TREATED AS ONE. The updater stores every reading at rank 5
with `trust_class = model_generated`, whatever this returns, so a wrong reading
can never outrank the owner's own words sitting beside it at rank 4. That is
also why this module does not need to be careful in the way a parser would: the
verbatim row is the truth, and the reading is a convenience laid next to it.

AN EMPTY LIST IS THE RIGHT ANSWER MOST OF THE TIME. Greetings, questions,
acknowledgements and commands carry no fact. An extractor that invents one for
every utterance fills memory with noise that outranks nothing but crowds
selection -- and block B's slots are few.
"""

from __future__ import annotations

import json
import re
from typing import Any

# What the model is asked for, and the shape the updater expects back.
SCHEMA_HINT = '[{"subject": "...", "attribute": "...", "value": "..."}]'

SYSTEM = """You extract facts from one sentence for a personal assistant's memory.

Return ONLY a JSON array. Each element: {"subject","attribute","value"}.

- subject: WHO or WHAT the fact is about. A person's name, a place, a thing.
  Use "owner" only when the fact is genuinely about the person speaking.
- attribute: a short snake_case key naming the KIND of fact (school_day,
  flight_time, phone_number, preference, deadline).
- value: the fact itself, short and self-contained. Keep the owner's own
  wording where it carries meaning.

Return [] when the sentence carries no fact worth remembering -- greetings,
questions, commands, acknowledgements, small talk. [] is a common and correct
answer; do not invent a fact to avoid it.

The sentence may be Moroccan Darija written in Latin script, where 3, 7 and 9
are letters. Extract in whatever language the sentence uses. Do not translate.

Examples
"sami ghadi lmdrasa nhar sebt m3a 3 dial l3chia"
[{"subject":"sami","attribute":"school_day","value":"lmdrasa nhar sebt m3a 3 dial l3chia"}]
"kidayr?"
[]
"""

# An explicit instruction to remember. When one of these is present the
# utterance is a MEMORY WRITE and not conversation, and an empty extraction is
# a failure rather than the usual correct answer.
REMEMBER_PHRASES = (
    # Darija, Latin script -- how the owner actually types
    "sjl", "sejjel", "sjjl", "39l", "3qel", "3gel", "tfekker", "tfekkr",
    "khelli f memory", "f memory", "fmemory", "hdi m3loma", "hadi m3loma",
    # English / French
    "remember this", "remember that", "note this", "save this", "keep this",
    "don't forget", "dont forget", "retiens", "souviens",
)


def is_remember_instruction(text: str) -> bool:
    """Did the owner explicitly ask for this to be kept?

    SUBSTRING MATCHING, DELIBERATELY. The owner types Darija in Latin script
    with no fixed spelling -- `sjl`, `sejjel`, `sjjl` are the same word -- so an
    exact-token match would miss most of the ways they actually write it. A
    false positive costs one extra extraction; a false negative loses the fact
    the owner explicitly asked to keep, which is the whole failure this exists
    to prevent.
    """
    low = (text or "").lower()
    return any(p in low for p in REMEMBER_PHRASES)


def parse(raw: str) -> list:
    """The model's text into readings. Anything malformed is dropped.

    MODELS WRAP JSON IN PROSE and in code fences, reliably enough that not
    handling it is choosing to fail. The array is located rather than assumed
    to be the whole response -- but only an ARRAY: accepting a bare object
    would let a single malformed reading through as if it were a list.
    """
    if not raw:
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        out = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(out, list):
        # REDUNDANT GIVEN THE BRACKET SEARCH ABOVE, and kept deliberately: the
        # slice is `[`..`]`, so json.loads can only return a list here. If the
        # locating is ever relaxed to accept a bare object, this is what stops
        # one malformed reading arriving as if it were a list of them. Noted as
        # unreachable so nobody writes a self-test case for it and finds it
        # green -- which is exactly what happened on 2026-08-31.
        return []
    readings = []
    for item in out:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        subject = str(item.get("subject", "")).strip()
        attribute = str(item.get("attribute", "")).strip()
        if not value or not subject:
            continue
        readings.append({
            "subject": subject.lower().replace(" ", "_")[:64],
            # A missing attribute is `derived`, which the updater already uses
            # as its default -- named here so the row says what it is.
            "attribute": (re.sub(r"[^a-z0-9_]+", "_", attribute.lower()).strip("_")
                          or "derived")[:48],
            "value": value[:500],
        })
    return readings


class FactExtractor:
    """Reads one utterance into facts, using the ordinary provider ladder."""

    def __init__(self, gateway: Any, *, profile_id: str = "",
                 bus: Any = None, max_tokens: int = 256) -> None:
        self._gw = gateway
        self._profile = profile_id
        self._bus = bus
        self._max_tokens = max_tokens

    def __call__(self, text: str) -> list:
        """Never raises. The updater already treats a failure as no readings.

        AND IT ASKS FOR LITTLE. `expected_output_tokens` is declared rather than
        defaulted because a free tier runs out of TOKENS PER MINUTE, not
        billing, and this call happens on every turn -- an over-declaration here
        is withheld from the next real request.
        """
        if not (text or "").strip():
            return []
        try:
            out = self._gw.complete(
                text, task_id="extract", system=SYSTEM,
                profile_id=self._profile or None, prefer="latency",
                expected_output_tokens=self._max_tokens, difficulty="easy")
        except Exception as exc:                    # noqa: BLE001
            self._emit("extract.failed", {"error": repr(exc)})
            return []
        raw = ((out or {}).get("result") or {}).get("text") or ""
        readings = parse(raw)
        self._emit("extract.read", {
            "readings": len(readings),
            "subjects": [r["subject"] for r in readings][:6],
            "explicit": is_remember_instruction(text),
            "note": ("stored at rank 5 as model_generated; the owner's verbatim "
                     "words sit beside them at rank 4 and outrank them"),
        })
        return readings

    def _emit(self, kind: str, payload: dict) -> None:
        if self._bus is not None:
            self._bus.publish(kind, subject="updater", payload=payload,
                              component="extract")
