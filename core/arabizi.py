"""Latin-script Darija to Arabic script, for the speech engine only.

WHY THIS EXISTS. `voice.toml` decides that VESPER writes Darija in Latin letters
and numbers, the way Moroccans text. That decision is about what the OWNER
READS, and it stands. What reaches a speech engine is a different question, and
the owner raised it: a text-to-speech model handed `3awd` has no way to know the
`3` is a letter, so it says "three-awd". Apple's voices do exactly that, which
is why they cannot speak Darija at all.

SO THE SCRIPT ON SCREEN AND THE SCRIPT IN THE SPEAKER NEED NOT MATCH. This
converts one to the other at the boundary. Nothing else in the system changes,
and the owner never sees Arabic script unless they ask for it.

THE DIGITS ARE THE WHOLE POINT AND THE REST IS BEST-EFFORT. Arabizi has no
standard: vowels are written or omitted by feel, the same sound has several
spellings, and `ch` is French-influenced Moroccan for what Levantine writers
spell `sh`. What IS stable is the digit convention -- 3, 7, 9, 2, 5, 6 stand for
letters Latin has no glyph for -- and those are the characters that break a
speech engine. So this is not a general transliterator and does not pretend to
be one.

IT IS A HEURISTIC AND IS MARKED AS ONE. `MEASURED = False` until somebody who
speaks Darija has listened to its output and said whether it is right. That is
not a formality: `INV-HW-2`'s habit applies to language as much as to
throughput, and a transliterator that looks plausible in a diff is exactly the
kind of thing that ships wrong. The owner is the only person who can grade it.

ITS CHECK RUNS AND IS DELIBERATELY UNREGISTERED, the same position the redactor
held before `INV-PRIV-7` was ratified. No invariant in the corpus covers
transliteration, and `INV-HW-2` -- the nearest habit, "measured at enrolment,
never declared" -- is specifically about sustained throughput. Claiming it here
would be a false trace, which this corpus holds to be worse than an honest gap.
`tools/ci/checks.py arabizi-preserves-and-marks-itself` therefore guards this
module and reports covering nothing.

ORDER MATTERS AND IS THE COMMON BUG. Digraphs must be consumed before single
letters, or `ch` becomes `c`+`h` and the word is wrong; longest-match-first is
what prevents that, not the order they happen to sit in a dict.
"""

from __future__ import annotations

# Set to True only when a Darija speaker has graded the output.
MEASURED = False

# Longest first. The list is ordered by length at import, so the order written
# here is for reading, not for matching.
_MAP: dict[str, str] = {
    # The digit convention -- the part that actually breaks a speech engine.
    "2": "ء", "3": "ع", "5": "خ", "6": "ط", "7": "ح", "8": "غ", "9": "ق",
    # Digraphs, before their single letters.
    "ch": "ش", "sh": "ش", "kh": "خ", "gh": "غ", "th": "ث", "dh": "ذ",
    "ou": "و", "ai": "اي", "aa": "ا", "ee": "ي", "ii": "ي", "oo": "و",
    # Consonants.
    "b": "ب", "t": "ت", "j": "ج", "7": "ح", "d": "د", "r": "ر", "z": "ز",
    "s": "س", "f": "ف", "k": "ك", "l": "ل", "m": "م", "n": "ن", "h": "ه",
    "w": "و", "y": "ي", "q": "ق", "g": "ك", "p": "ب", "v": "ف", "c": "ك",
    "x": "كس",
    # Vowels. Arabic writes short vowels rarely; these are the long forms, which
    # is the safer default for a speech engine -- an over-written vowel is read
    # slightly long, an omitted one can change the word.
    "a": "ا", "i": "ي", "e": "ي", "o": "و", "u": "و",
}

# Punctuation a speech engine reads as prosody. Comma and question mark have
# Arabic forms; a Latin `?` after Arabic text renders on the wrong side.
_PUNCT = {",": "،", ";": "؛", "?": "؟"}

_ORDERED = sorted(_MAP, key=len, reverse=True)


def transliterate(text: str) -> str:
    """Arabizi to Arabic script. Longest-match-first, left to right.

    PASSES THROUGH ANYTHING IT DOES NOT RECOGNISE -- Latin punctuation, digits
    that are genuinely numbers, and any Arabic already present. A transliterator
    that dropped what it could not map would silently delete content, which is a
    worse failure than leaving a character alone.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _PUNCT:
            out.append(_PUNCT[ch]); i += 1; continue
        if ch.isspace() or "؀" <= ch <= "ۿ":
            out.append(ch); i += 1; continue
        low = text[i:].lower()
        for k in _ORDERED:
            if low.startswith(k):
                out.append(_MAP[k]); i += len(k); break
        else:
            out.append(ch); i += 1
    return "".join(out)


# English tokens that legitimately mix a digit with letters. A closed set,
# because that is what makes the test decidable: everything else that mixes a
# digit with letters in Latin script is the Arabizi convention.
_EN_UNITS = frozenset((
    "am", "pm", "h", "hr", "hrs", "min", "mins", "s", "sec", "secs",
    "st", "nd", "rd", "th", "k", "m", "b", "kg", "g", "mb", "gb", "tb",
    "px", "pt", "x", "d", "w", "y", "yr", "yrs", "c", "f", "kb",
))


def looks_arabizi(text: str) -> bool:
    """Is this Latin-script Darija rather than English?

    THE FIRST VERSION OF THIS WAS WRONG IN TWO WAYS AND ITS OWN CHECK CAUGHT
    BOTH. It stripped spaces before looking for a digit beside a letter, so
    "at 9am" became "...at9am..." and every digit in every sentence looked
    embedded. And the rule it claimed -- letters on BOTH sides -- fails on
    "3awd" and "7it", where the digit leads.

    THE REAL DISTINCTION IS THE LETTERS, NOT THE POSITION. English mixes digits
    with a small closed set of units and ordinals: 9am, 3pm, 24h, 1st, 5kg.
    Arabizi mixes them with words. So a token carrying one of the convention's
    digits is Arabizi unless what surrounds the digit is one of those units.

    IT ONLY SEES DARIJA THAT HAPPENS TO USE A DIGIT. "Golti liya lbareh" is
    Darija and contains none, so this returns False for it -- correctly, since
    the caller's question is "will a speech engine mispronounce a digit here",
    and there is no digit to mispronounce. Detecting Darija as a LANGUAGE is a
    different problem and this is not it.
    """
    import re
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if not re.search(r"[235679]", tok):
            continue
        letters = re.sub(r"[0-9]", "", tok)
        if letters and letters not in _EN_UNITS:
            return True
    return False
