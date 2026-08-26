"""What KIND of request this is, so the ladder stops answering all of them alike.

THE HARDCODED CONSTANT THIS REPLACES. `tools/ops/vesper_runtime.py` passed
`difficulty="moderate"` on every request, with a comment that was honest about
it: "difficulty is not inferred ... `moderate` is the honest middle until
something can classify." This is that something. Until it existed, "hello" and
"design me a schema" were routed identically, which cost twice:

  TIER. `moderate` floors at `standard`, so a greeting could not be answered by
  anything cheaper, and on 2026-08-26 it was routed to a rung that took 25.9 s
  to say hello back.

  EFFORT. `moderate` floors at `medium`, which reserves 2048 tokens of
  reasoning headroom (core/effort.py). A greeting does not need 2048 tokens of
  reasoning and the free tiers underneath are finite.

IT IS ASYMMETRIC ON PURPOSE, and this is the whole design. Classifying UP is
cheap and classifying DOWN is dangerous: a hard question answered at `low`
effort comes back confidently wrong, which is the exact failure `core/effort.py`
raises rather than clamps to avoid. So:

  - going DOWN requires a positive, narrow signal (a greeting, an
    acknowledgement, a short closed question). Silence from every rule means
    `moderate`, never `trivial`.
  - going UP needs only one marker, and several are single words.
  - anything it cannot read confidently stays `moderate` -- the same honest
    middle as before, so the worst case of this module is the status quo.

IT IS A HEURISTIC AND IS LABELLED ONE. `RouteDecision` carries the reason, and
`classify` returns the signal it fired on, so a bad route can be traced to the
rule that made it rather than to "the classifier". INV-HW-2 is not in play here:
difficulty is a property of a request, not a throughput, and nothing downstream
treats this as a measurement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# core/router.py DIFFICULTY, by value. Restated rather than imported to keep
# this module free of a circular import at load; CI-069 asserts they agree.
DIFFICULTY = ("trivial", "easy", "moderate", "hard")

# Whole-utterance matches, after casefolding and stripping punctuation. A
# SUBSTRING MATCH WOULD BE WRONG HERE: "thanks, now explain the placement
# stress runner" contains "thanks" and is not an acknowledgement.
GREETINGS = frozenset({
    "hi", "hey", "hello", "yo", "hiya", "morning", "good morning",
    "good afternoon", "good evening", "good night", "goodnight",
    "hi there", "hey there", "hello there", "are you there", "you there",
    "you awake", "vesper", "hey vesper", "hi vesper", "hello vesper",
})
ACKS = frozenset({
    "thanks", "thank you", "thanks a lot", "thank you very much", "ta",
    "ok", "okay", "k", "cool", "nice", "great", "perfect", "got it",
    "understood", "sure", "yes", "yeah", "yep", "no", "nope", "right",
    "sounds good", "will do", "never mind", "nevermind", "forget it",
    "stop", "cancel", "wait", "bye", "goodbye", "see you", "good work",
    "well done", "lol", "haha",
})

# One marker is enough to raise. Word-boundary anchored so "designer" does not
# fire "design" and "whyever" does not fire "why".
HARD_MARKERS = (
    r"\bwhy\b", r"\bexplain\b", r"\bdesign\b", r"\bprove\b", r"\banalys[ei]\b",
    r"\banalyz[ei]\b", r"\bcompare\b", r"\btrade-?offs?\b", r"\bderive\b",
    r"\bdebug\b", r"\brefactor\b", r"\barchitect\w*\b", r"\bimplement\b",
    r"\balgorithm\b", r"\boptimi[sz]e\b", r"\bstrategy\b", r"\bplan\b",
    r"\bwrite\s+(?:me\s+)?(?:a|the|some)?\s*(?:code|script|program|function)\b",
    r"\bstep[- ]by[- ]step\b", r"\bpros and cons\b", r"\breview\b",
)
_HARD = re.compile("|".join(HARD_MARKERS), re.I)

# Closed questions with one short factual answer. `easy`, never `trivial`:
# they still need a model, and `trivial` is reserved for turns that need
# almost nothing of one.
_EASY = re.compile(
    r"^\s*(?:what|who|when|where|which|how many|how much|how long|is|are|was|"
    r"were|do|does|did|can|could|will|would|should)\b", re.I)

# A code fence, a stack trace or a URL means there is material to work over,
# whatever the words around it say.
_MATERIAL = re.compile(r"```|\bTraceback\b|https?://|\b\w+\.(?:py|swift|toml|json|ts|js|rs|go)\b")

TRIVIAL_MAX_WORDS = 6
EASY_MAX_WORDS = 25
HARD_MIN_WORDS = 60


@dataclass(frozen=True, slots=True)
class Classification:
    difficulty: str
    signal: str
    confident: bool

    def to_dict(self) -> dict:
        return {"difficulty": self.difficulty, "signal": self.signal,
                "confident": self.confident}


def _normalise(text: str) -> str:
    return re.sub(r"[^\w\s']", " ", (text or "").casefold()).strip()


def classify(text: str) -> Classification:
    """Return the difficulty this request should be routed at.

    ORDER MATTERS AND READS AS POLICY. Material and hard markers are checked
    BEFORE the short-utterance rules, because "why?" is three characters and is
    not trivial -- a length rule that ran first would demote it.
    """
    raw = (text or "").strip()
    words = raw.split()
    n = len(words)
    if not n:
        # An empty request is not trivial, it is a defect upstream. `moderate`
        # rather than a raise: the intake layer already refuses empties, and
        # this module should not be a second place a keystroke can be lost.
        return Classification("moderate", "empty request; no signal to read", False)

    if _MATERIAL.search(raw):
        return Classification("hard", "carries code, a trace, a path or a URL", True)
    if _HARD.search(raw):
        m = _HARD.search(raw)
        return Classification("hard", f"marker {m.group(0)!r}", True)
    if n >= HARD_MIN_WORDS:
        return Classification(
            "hard", f"{n} words -- length alone implies structure to hold", True)

    flat = _normalise(raw)
    if flat in GREETINGS:
        return Classification("trivial", "whole utterance is a greeting", True)
    if flat in ACKS:
        return Classification("trivial", "whole utterance is an acknowledgement", True)

    # A QUESTION MARK IS NOT A DOWNGRADE SIGNAL, and it looked like one. Short
    # questions are usually easy and "why not?" is not -- but `_HARD` has
    # already claimed that case above, so what reaches here is a short closed
    # question with no hard marker in it.
    if n <= TRIVIAL_MAX_WORDS and not raw.endswith("?"):
        return Classification(
            "easy", f"{n} words, no question and no hard marker", False)
    if n <= EASY_MAX_WORDS and _EASY.match(raw):
        return Classification("easy", "short closed question", False)

    return Classification(
        "moderate", "no confident signal either way -- the honest middle", False)
