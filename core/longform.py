"""Split one reply into the sentence VESPER says and the text it shows.

THE OWNER'S REQUEST, IN THEIR WORDS: the explanations and the big text "will
not say them, they just show up there, what it says stays on the dialog that
was made for it, they should be connected."

TWO DESTINATIONS, ONE REPLY, AND THE SPLIT IS NOT COSMETIC. Reading four
hundred words aloud is the failure this exists to prevent -- a spoken channel
has no skimming, no scrollback and no way to stop politely. A code block read
aloud is worse than useless: `mv -f "$a" "$b"` spoken is not a command anyone
can act on. So the stage and the speech get a sentence, and the board gets the
whole thing.

CONNECTED BY THE TURN, NEVER BY POSITION. Both halves carry the utterance's
HLC, so clicking either finds the other. Pairing them by "the newest of each"
would be right until the first turn that produces one and not the other, and
then silently wrong for every turn after it.

NOTHING HERE IS GENERATED. The spoken line is VESPER'S OWN FIRST SENTENCE, cut
at a boundary it already wrote. Asking a model to summarise its own answer
produces a SECOND generation about the first -- text shaped like a summary and
causally downstream of nothing, which `core/workbench.py`'s header rejects for
the thinking column and which is no more true here. When there is no prose to
take, this says so in a fixed line rather than inventing one.

TYPED BLOCKS, NOT MARKDOWN. The page renders each kind with a fixed template
and `textContent`. Handing it a markdown string would put a parser in the page,
and a parser in the page is the place a model's output becomes markup.

Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# What may be spoken in one go. Not a style preference: `speech.plan` sends this
# to a synthesiser and then to the room, and there is no way to skip ahead.
SPOKEN_MAX_CHARS = 240

# Below this, with no code and few lines, a reply is simply a reply -- it is
# said, it appears on the stage, and NO board entry is made. An explanations
# card that filled up with one-line answers would bury the explanations.
LONGFORM_MIN_CHARS = 320
LONGFORM_MIN_LINES = 5

# The board's depth. Explanations are long; keeping thirty is already a lot of
# text to carry through home.json on every tick.
EXPLANATIONS_MAX = 30

FENCE = re.compile(r"^```[ \t]*([A-Za-z0-9_+-]*)[ \t]*$")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
# A sentence ends at ., ! or ? followed by space or end. Kept deliberately dumb:
# a cleverer rule mis-splits `3.13` and `e.g.` in both directions, and the cost
# of stopping a little early is a shorter spoken line, which is not a defect.
SENTENCE_END = re.compile(r"(?<=[.!?])\s")

# WHEN THERE IS NO PROSE TO TAKE. A reply that opens with a code fence has no
# first sentence, and the alternative to a fixed line is inventing one about
# text VESPER has not been asked to describe.
NO_PROSE = "That one is written out on the board."


@dataclass(slots=True)
class Block:
    kind: str                       # text | code | list
    text: str = ""
    lang: str = ""
    items: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind}
        if self.kind == "list":
            d["items"] = list(self.items)
        else:
            d["text"] = self.text
        if self.lang:
            d["lang"] = self.lang
        return d


@dataclass(slots=True)
class Split:
    spoken: str
    blocks: tuple[Block, ...] = ()
    title: str = ""

    @property
    def is_longform(self) -> bool:
        return bool(self.blocks)


def _blocks(text: str) -> list[Block]:
    """Typed blocks from a reply, in order.

    AN UNCLOSED FENCE IS STILL A CODE BLOCK. Models truncate; a reply whose
    final fence never closes is the ordinary shape of a reply that hit a token
    limit. Treating the remainder as prose would put a wall of code through the
    text renderer and, worse, through the SPOKEN half on some future call site.
    """
    out: list[Block] = []
    lines = text.split("\n")
    i = 0
    prose: list[str] = []

    def flush_prose() -> None:
        if not prose:
            return
        chunk = "\n".join(prose).strip("\n")
        prose.clear()
        for para in re.split(r"\n\s*\n", chunk):
            para = para.strip()
            if not para:
                continue
            rows = para.split("\n")
            if all(BULLET.match(r) for r in rows):
                out.append(Block("list",
                                 items=tuple(BULLET.sub("", r).strip() for r in rows)))
            else:
                out.append(Block("text", text=para))

    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            lang, i = m.group(1), i + 1
            body: list[str] = []
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1                                   # step over the closing fence
            flush_prose()
            code = "\n".join(body).strip("\n")
            if code:
                out.append(Block("code", text=code, lang=lang))
            continue
        prose.append(lines[i])
        i += 1
    flush_prose()
    return out


def _first_sentence(text: str) -> str:
    """VESPER's own opening, cut at a boundary VESPER already wrote."""
    para = text.strip().split("\n\n")[0].strip()
    para = " ".join(para.split())
    if not para:
        return ""
    if len(para) <= SPOKEN_MAX_CHARS:
        return para
    # The last full sentence that fits.
    cut = para[:SPOKEN_MAX_CHARS]
    ends = list(SENTENCE_END.finditer(cut))
    if ends:
        return cut[:ends[-1].start() + 1].strip()
    # No sentence boundary at all -- one very long sentence. A word boundary and
    # an ellipsis, which says a cut happened rather than implying VESPER stopped
    # there.
    return cut[:cut.rfind(" ")].strip() + "…" if " " in cut else cut.strip() + "…"


def split(reply: str, *, question: str = "") -> Split:
    """One reply, divided into what is said and what is shown.

    A SHORT REPLY IS NOT DIVIDED AT ALL. `spoken` is the whole thing and
    `blocks` is empty, so the board stays empty and the stage carries the
    answer -- which is what it has always done and is right for most turns.
    """
    reply = (reply or "").strip()
    if not reply:
        return Split(spoken="")

    blocks = _blocks(reply)
    has_code = any(b.kind == "code" for b in blocks)
    long_enough = (len(reply) >= LONGFORM_MIN_CHARS
                   or reply.count("\n") + 1 >= LONGFORM_MIN_LINES)
    if not (has_code or long_enough):
        return Split(spoken=reply)

    # The opening PROSE, which is not necessarily the first block: a reply may
    # begin with the code and explain it after.
    lead = next((b.text for b in blocks if b.kind == "text"), "")
    spoken = _first_sentence(lead) or NO_PROSE

    # THE TITLE COMES FROM THE QUESTION, NOT FROM THE ANSWER. The board is read
    # by someone looking for the thing they asked about, and the answer's own
    # first words are already the line beneath it.
    # CUT AT A WORD, NOT AT A CHARACTER. A title ending "...short bash exam"
    # reads as a different question from the one that was asked.
    title = " ".join((question or "").split())
    if len(title) > 70:
        title = title[:70]
        if " " in title:
            title = title[:title.rfind(" ")]
        title += "…"
    title = title or "explanation"
    return Split(spoken=spoken, blocks=tuple(blocks), title=title)
