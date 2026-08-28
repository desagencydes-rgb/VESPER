"""What the owner says while VESPER is preparing, and whether it stops the work.

THE PROBLEM. The chooser sometimes needs longer than its budget. When it does,
VESPER says so and holds the floor. During that hold the owner may say
something -- and the naive implementations are both wrong:

  * Treat everything as an interruption, and "take your time" cancels the work
    it was granting time for. The owner is punished for being polite.
  * Treat nothing as an interruption, and "stop" is ignored. That is worse: a
    system that cannot be stopped is one nobody will leave running.

CONVERSATION ANALYSIS ALREADY HAS THE DISTINCTION, so it is not invented here.
The literature separates COOPERATIVE interruptions -- which support the current
speaker and do not seek the floor ("mhm", "go on", "no rush") -- from
COMPETITIVE ones, which take the floor ("stop", "wait", "actually"). That maps
exactly onto the decision this module makes.

A THIRD CLASS, WHICH THE OBVIOUS DESIGN MISSES. "You still there?" is neither.
It seeks neither the floor nor to encourage; it is checking the system is
alive. Swallowing it silently is the exact behaviour that makes the owner think
VESPER has hung -- and then say something that IS competitive. Answering it
with a status line, without cancelling, defuses the interruption that would
otherwise follow.

THE DEFAULT UNDER AMBIGUITY IS TO BREAK THROUGH, AND THE ASYMMETRY IS THE WHOLE
ARGUMENT. A wrong break-through costs one wasted preparation cycle, measured in
hundreds of milliseconds. A wrong swallow means the owner said "stop" and was
ignored. Those are not comparable costs, so they must not share a default.

NO MODEL, EVER. This runs while the owner is waiting, on every inbound token,
and a model call here would add latency to the exact moment the system is
already apologising for latency. It is also the reason the classifier cannot be
talked out of stopping: a fixed list has no instructions to follow.
"""
from __future__ import annotations

import re
from enum import Enum

__all__ = ("Floor", "classify", "PHRASES")


class Floor(Enum):
    """What to do with an utterance that arrives during a hold."""
    BREAK = "break"        # competitive -- abandon the work now
    SWALLOW = "swallow"    # cooperative -- discard, keep working, stay silent
    STATUS = "status"      # liveness check -- answer, do not cancel
    QUEUE = "queue"        # anything else -- hold, deliver when the work lands


# ---------------------------------------------------------------------------
# COMPETITIVE -- take the floor. Grouped by what the speaker actually wants,
# because the groups have different failure modes and reviewing a flat list of
# 90 strings is how a group goes missing.
# ---------------------------------------------------------------------------
_HALT = (
    "stop", "stop it", "stop that", "stop now", "halt", "abort", "cancel",
    "cancel that", "cancel it", "quit", "exit", "terminate", "kill it",
    "kill that", "drop it", "drop that", "forget it", "forget that",
    "never mind", "nevermind", "nvm", "scrap that", "scrap it", "leave it",
    "skip it", "skip that", "dont bother", "don't bother", "belay that",
    "abandon", "give up", "end it",
)
_REVERSE = (
    "wait", "wait wait", "hold on", "hold up", "hang on", "hold it",
    "actually", "scratch that", "undo", "revert", "go back", "back up",
    "my mistake", "i misspoke", "one sec", "one second", "just a sec",
)
_RECORRECT = (
    "wrong", "thats wrong", "that's wrong", "wrong question", "wrong one",
    "not that", "not this", "not what i meant", "not what i said", "i meant",
    "i mean", "thats not", "that's not", "different question", "new question",
    "change of plan", "instead", "rather", "correction",
)
_PROHIBIT = (
    "no", "nope", "nah", "dont", "don't", "do not", "not now", "no dont",
    "no don't", "negative",
)
_SILENCE = (
    "quiet", "be quiet", "shut up", "shush", "hush", "mute", "stop talking",
    "silence", "enough", "thats enough", "that's enough",
)
_URGENT = (
    "emergency", "urgent", "help", "now", "right now", "immediately", "asap",
    "hurry", "quick", "quickly", "priority",
)
# ATTENTION GRABS ARE COMPETITIVE ONLY IN THIS CONTEXT. "hey" opening a
# conversation is a greeting; "hey" arriving while the system is already
# working is the owner trying to get in. The hold is what changes the reading,
# which is why this list lives here and not in the greeting set.
_ATTENTION = (
    "hey", "hey wait", "oi", "listen", "look", "excuse me", "yo",
)

# ---------------------------------------------------------------------------
# COOPERATIVE -- grant the floor. Swallowed silently.
# ---------------------------------------------------------------------------
_TIME_GRANT = (
    "take your time", "take ur time", "take all the time you need",
    "take as long as you need", "no rush", "no hurry", "whenever",
    "whenever youre ready", "whenever you're ready", "no pressure",
    "at your own pace", "in your own time", "theres no rush", "there's no rush",
)
_ACK = (
    "ok", "okay", "k", "kk", "okey", "alright", "all right", "right", "sure",
    "yeah", "yea", "ye", "yep", "yup", "yes", "mhm", "mm", "mmhm", "mmm",
    "uh huh", "uhhuh", "aha", "ah", "i see", "isee", "got it", "gotcha",
    "understood", "makes sense", "fair", "fair enough", "cool", "nice",
    "great", "good", "perfect", "sweet", "noted", "roger", "copy",
)
_ENCOURAGE = (
    "go ahead", "go on", "carry on", "keep going", "continue", "proceed",
    "please do", "do it", "sounds good", "good idea", "go for it", "yes please",
)
_POLITE = (
    "please", "thanks", "thank you", "ty", "thx", "cheers", "appreciate it",
    "appreciated",
)
_FILLER = (
    "um", "uh", "er", "erm", "hmm", "hm", "hmmm", "well", "so", "huh",
)
_REASSURE = (
    "no problem", "np", "no worries", "thats fine", "that's fine", "all good",
    "its fine", "it's fine", "dont worry", "don't worry", "take it easy",
    "its ok", "it's ok", "thats ok", "that's ok", "fine",
)
# NEGATED HALTS. "don't stop" contains "stop" and means the opposite of it.
# These are listed as cooperative phrases and matched BEFORE the halt list by
# the longest-match rule below; without them the most natural way to say
# "carry on" would cancel the work.
_NEGATED_HALT = (
    "dont stop", "don't stop", "do not stop", "dont cancel", "don't cancel",
    "dont quit", "don't quit", "keep at it", "stay on it",
)

# ---------------------------------------------------------------------------
# STATUS -- checking VESPER is alive. Answered, never cancelled.
# ---------------------------------------------------------------------------
_STATUS = (
    "still there", "you still there", "are you there", "you there", "hello",
    "hello?", "you ok", "are you ok", "you alive", "still working",
    "still going", "whats happening", "what's happening", "whats going on",
    "what's going on", "how long", "how much longer", "are you stuck",
    "did it crash", "did you crash", "is it working", "any progress",
    "you good", "?", "??", "???",
)

PHRASES: dict[str, Floor] = {}
for _group, _verdict in (
    (_NEGATED_HALT, Floor.SWALLOW),      # before _HALT; longest-match anyway
    (_TIME_GRANT, Floor.SWALLOW), (_ACK, Floor.SWALLOW),
    (_ENCOURAGE, Floor.SWALLOW), (_POLITE, Floor.SWALLOW),
    (_FILLER, Floor.SWALLOW), (_REASSURE, Floor.SWALLOW),
    (_STATUS, Floor.STATUS),
    (_HALT, Floor.BREAK), (_REVERSE, Floor.BREAK), (_RECORRECT, Floor.BREAK),
    (_PROHIBIT, Floor.BREAK), (_SILENCE, Floor.BREAK), (_URGENT, Floor.BREAK),
    (_ATTENTION, Floor.BREAK),
):
    for _p in _group:
        # First writer wins, so a phrase appearing in two groups keeps the
        # SWALLOW/STATUS reading it was given above. Only `_NEGATED_HALT`
        # relies on this today; the assertion in the self-test pins it.
        PHRASES.setdefault(_p, _verdict)

# Longest first. "no rush" must be tested before "no", and "dont stop" before
# both "stop" and "dont" -- otherwise the shortest token decides and every
# polite phrase containing a negation cancels the work.
_ORDERED = sorted(PHRASES, key=len, reverse=True)

# APOSTROPHES ARE DELETED, NOT SPACED. Replacing them with a space turns
# "don't stop" into "don t stop", which matches no phrase and therefore falls
# through to the ambiguity default -- cancelling the work on the most natural
# way of saying "carry on". Every other punctuation mark becomes a space so
# "ok,stop" still splits into two words.
_APOS = re.compile(r"[\u2019']")
_PUNCT = re.compile(r"[^\w\s?]+")
_WS = re.compile(r"\s+")

# NEGATION IN FRONT OF A HALT REVERSES IT, and the long-utterance path needs
# this as much as the phrase table does: "let's not stop until this is done" is
# seven words, reaches the contained-word scan, and reads as a halt without it.
_NEGATED = re.compile(
    r"\b(?:not|dont|never|no need to|rather than|instead of|without)\s+"
    r"(?:to\s+|you\s+|ing\s+)?"
    r"(?:stop|cancel|quit|halt|abort|give up|drop it)\b")
# Utterances longer than this are not backchannels whatever they contain. A
# person granting time says four words; a person issuing a new instruction
# writes a sentence, and a sentence during a hold is a new request.
_MAX_CONTROL_WORDS = 6


def _normalise(text: str) -> str:
    t = _APOS.sub("", (text or "").lower().strip())
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def classify(text: str) -> Floor:
    """Decide what a mid-hold utterance does to the work in flight.

    Whole-utterance match first, then a contained-phrase match limited to short
    utterances. The length limit is what stops "I need to stop by the shop"
    reading as a halt while still catching "ok stop".
    """
    flat = _normalise(text)
    if not flat:
        return Floor.SWALLOW
    verdict = PHRASES.get(flat)
    if verdict is not None:
        return verdict

    words = flat.split()
    if len(words) <= _MAX_CONTROL_WORDS:
        for phrase in _ORDERED:
            if " " in phrase:
                if phrase in flat:
                    return PHRASES[phrase]
            elif phrase in words:      # word-boundary match for single tokens
                return PHRASES[phrase]
        # A short utterance that matched nothing is still more likely to be an
        # attempt to intervene than a stray thought. Ambiguity breaks through.
        return Floor.BREAK

    # A long utterance is a new request: it is neither encouragement nor a
    # simple halt, and discarding it would lose real content. But a halt word
    # inside one still stops the work -- the sentence can be re-read afterwards
    # from the queue, whereas work that should have stopped cannot be un-run.
    if not _NEGATED.search(flat):
        for phrase in _HALT + _SILENCE + _URGENT:
            if re.search(rf"\b{re.escape(phrase)}\b", flat):
                return Floor.BREAK
    return Floor.QUEUE
