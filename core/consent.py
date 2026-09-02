"""Is this utterance an answer to the question VESPER just asked?

DELIBERATELY NOT A MODEL CALL, and this is the whole reason the module exists
rather than a prompt. Everywhere else in the act path a model may PROPOSE and
the deterministic layer DECIDES; consent is the one decision where that
separation matters most, because a model that decides whether the owner agreed
is a model that can be talked into agreeing on their behalf. `INV-ACT-3` caps
the authority of anything the system reads precisely so retrieved text cannot
steer an action -- and manufactured consent is that same steering arriving at
the one gate the ladder cannot second-guess. A wrong "yes" here is
indistinguishable, downstream, from the owner having said it.

FAIL-CLOSED, WHICH MEANS `OTHER` IS THE DEFAULT. Anything not recognised is not
an answer: the question returns to the queue and is asked again. The cost of
that is one repeated sentence. The cost of the opposite is an action the owner
never authorised, taken with a record saying they did.

SHORT AND LEADING, because that is how a direct question is answered. "yes" is
consent; "yes I was thinking about that, anyway can you check the logs" opens
with the same token and is not. The affirmation has to BEGIN the utterance and
the vocabulary is small on purpose -- a large one is a large surface for a
sentence that merely sounds like agreement.

WORK AFTER THE ANSWER IS KEPT, NOT DISCARDED. "yes, and also check the logs" is
one utterance carrying two things: an answer and a new instruction. Dropping the
remainder would make the owner repeat themselves; treating the whole thing as
one instruction would lose the answer. The remainder comes back separately and
goes down the ladder from the beginning as its own turn.

THE LANGUAGES ARE THE OWNER'S, not English plus a gesture. This host runs
`en-US`, `fr-FR` and `ar-MA`, and Darija reaches the system as arabizi -- Latin
letters with digits standing in for Arabic sounds, which `core/arabizi.py`
already recognises. A consent vocabulary that only knew English would refuse
the owner's own "wah" and ask them again in a language they answered in.
"""

from __future__ import annotations

import re
import unicodedata

YES = "yes"
NO = "no"
OTHER = "other"

# EXPLICIT AND SMALL. Every entry is a word someone uses to answer "May I go
# ahead?" and nothing else. Notably absent: "ok" on its own is here, but "sure
# thing", "why not", "i guess" and similar hedges are not -- an ambiguous
# agreement should be re-asked, not acted on.
_YES = {
    # English
    "yes", "yep", "yeah", "yup", "ok", "okay", "sure", "go", "do", "please",
    "confirm", "confirmed", "approved", "approve", "granted", "allow",
    # French
    "oui", "ouais", "daccord", "vasy", "allezy",
    # Darija / arabizi and Arabic
    "wah", "wa7", "wakha", "wa5a", "ah", "aywa", "eyeh", "iyeh", "naam",
    "n3am", "safi", "yallah", "yalla", "sir", "smehli",
    "نعم", "أيوة", "واخا", "أجل",
}
_NO = {
    "no", "nope", "nah", "dont", "stop", "cancel", "refuse", "refused",
    "denied", "deny", "negative", "never",
    "non", "pasmaintenant",
    "la", "lla", "makayn", "makaynch", "matdirch", "blach", "ma",
    "لا", "ماشي",
}
# Phrases that must be seen whole, because their words individually mean the
# opposite or nothing: "go ahead" is consent, "go" plus "ahead" is not a rule
# worth having, and "not now" must never be read off its first token.
_YES_PHRASES = ("go ahead", "go for it", "do it", "carry on", "carry on then",
                "yes please", "that's fine", "thats fine", "sounds good",
                "vas y", "allez y", "d accord", "sir 3lih", "sir alih")
_NO_PHRASES = ("not now", "no thanks", "no thank you", "leave it", "don't",
               "hold off", "not yet", "pas maintenant", "ma tdirch")

# Where an answer stops and a new instruction starts. Only these: a comma is a
# separator people actually use after "yes", and "and"/"then"/"also" introduce
# the next thing. A full stop is deliberately NOT here -- two sentences are two
# utterances and arrive separately.
_SPLIT = re.compile(r"\s*(?:,|;|\band\b|\bthen\b|\balso\b|\bbut\b)\s*", re.I)

# An answer is short. A paragraph that opens with "yes" is a paragraph, and the
# question it happens to precede has not been answered by it.
MAX_ANSWER_WORDS = 4


def _fold(text: str) -> str:
    """Casefold and strip accents. Punctuation survives."""
    t = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return "".join(c for c in t if not unicodedata.combining(c))


def _norm(text: str, *, keep_separators: bool = False) -> str:
    """Casefold, strip accents and punctuation, collapse space.

    `keep_separators` KEEPS THE COMMA, and it has to. Stripping punctuation
    before splitting destroyed the separator this module relies on: "no, append
    to the log instead" became a five-word sentence with no boundary in it, ran
    past MAX_ANSWER_WORDS, and came back OTHER -- so the owner redirecting
    VESPER read as them saying nothing at all, and the question was re-asked
    instead of being answered and replaced.
    """
    t = _fold(text)
    keep = r"[^\w\s,;؀-ۿ]+" if keep_separators else r"[^\w\s؀-ۿ]+"
    t = re.sub(keep, " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify(text: str) -> tuple:
    """`(verdict, remainder)`. Verdict is YES, NO or OTHER.

    `remainder` is whatever followed the answer -- a new instruction the owner
    attached to it -- and is empty when there was none. It is NEVER treated as
    part of the answer: it comes back as its own turn.
    """
    marked = _norm(text, keep_separators=True)
    whole = _norm(text)
    if not whole:
        return OTHER, ""

    # Phrases first: "not now" must not be read as its first token.
    for phrase in _NO_PHRASES:
        if whole == _norm(phrase) or whole.startswith(_norm(phrase) + " "):
            return NO, whole[len(_norm(phrase)):].strip()
    for phrase in _YES_PHRASES:
        if whole == _norm(phrase) or whole.startswith(_norm(phrase) + " "):
            return YES, whole[len(_norm(phrase)):].strip()

    parts = _SPLIT.split(marked, maxsplit=1)
    head = _norm(parts[0])
    tail = _norm(parts[1]) if len(parts) > 1 else ""

    words = head.split()
    if not words or len(words) > MAX_ANSWER_WORDS:
        return OTHER, ""
    # EVERY word of the head must be an answer word or a pleasantry. "yes do
    # the other one instead" opens with an affirmation and is not one.
    fillers = {"please", "thanks", "then", "now", "sure", "fine", "good"}
    if all(w in _NO or w in fillers for w in words) and any(w in _NO for w in words):
        return NO, tail
    if all(w in _YES or w in fillers for w in words) and any(w in _YES for w in words):
        return YES, tail
    return OTHER, ""
