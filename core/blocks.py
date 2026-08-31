"""L1 — two blocks, in different places, for different reasons.

    [ BLOCK A ]  cached, stable      persona + rules + an INDEX of what exists
    [   ...    ]  deliberately empty
    [ BLOCK B ]  fresh, uncached     the 3-5 facts THIS turn needs
    [ question ]

WHY TWO AND NOT ONE, because one block cannot satisfy both constraints at once
and the conflict is not a matter of taste:

    CACHING WANTS STABILITY FIRST. The discount is prefix-keyed, so stable
    content has to lead and volatile content has to trail. Any byte that
    changes early invalidates everything after it.

    ATTENTION WANTS IMPORTANCE AT THE EDGES. Long-context accuracy follows a
    U-curve and the middle degrades by more than 30%. Ordering purely for the
    cache puts the facts in the middle -- the worst position available.

Two blocks resolve it. A leads, which is both cache-optimal and a
high-attention position; B sits last, against the question, which is the other
high-attention position; and the weak middle is left EMPTY ON PURPOSE. An
implementation that "helpfully" fills the middle with anything at all has
undone the only reason this file is shaped like this.

BLOCK A HOLDS THE INDEX, NOT THE KNOWLEDGE, and this is the correction to the
original design rather than a size optimisation. Context-rot measurements across
18 models find degradation driven by length AND by distractors, and specifically
that TOPICALLY RELATED BUT IRRELEVANT content harms more than unrelated filler.
Resident personal memory is exactly that: related, and mostly irrelevant to any
one turn. Carrying every fact resident maximises the most harmful kind of
context there is. So A carries what memory CONTAINS -- `47 facts under "work";
3 resident; ->log:1183` -- at roughly 15 tokens a node instead of the facts
themselves.

THAT IS ALSO WHAT KEEPS ABSENCE NON-SILENT. Without the index, a fact that was
not selected leaves VESPER *confidently* ignorant, which produces no event and
cannot be noticed by anyone. With it, VESPER knows the shape of what it did not
bring, and `INV-EVID-2`'s resolvable span survives as a pointer.

MERGING PERSONA INTO A IS NOT TIDINESS -- IT IS WHAT MAKES PERSONA CACHEABLE.
Measured 2026-08-28: `persona.toml` plus `voice.toml` are ~1,590 tokens shipped
as their own system prompt every turn, and that is below every published cache
minimum. Alone they can never be discounted. As stratum 0 of block A they cross
the threshold and both halves go nearly free.

THE MERGE IS IN RENDERING, NEVER IN AUTHORITY, and this is the line that must
not blur. Persona lives in `contracts/policy/`, changed only by reviewed act
(`INV-SELF-*`). Memory is derived. Block A RENDERS from the contract and the
memory system may never write into it -- without that rule a compaction pass
could rewrite VESPER's own rules and no gate would notice, because the output
would still look like a persona.

BLOCK B IS SELECTED DETERMINISTICALLY. FTS5 plus bounded graph traversal over
L2, no model call, single-digit milliseconds. THIS IS WHAT PRESERVES THE OWNER'S
FOUNDING INSIGHT: there is still no recall EVENT, nothing waits on a retrieval
hop, and a self-initiated act with no user turn still gets a block B -- seeded
by the sweep's finding instead of by an utterance. What was rejected was
recall-as-a-round-trip, not selection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .memory import TOP_N, MemoryGraph

# `MEMORY_ARCHITECTURE.md`'s budget table. On breach: ship what was found and
# NOTE THE TRUNCATION -- never silently return less, because a short block B and
# a block B that ran out of time are indistinguishable downstream.
SELECTION_BUDGET_MS = 25

# Roughly what one index line costs. Used to report block A's size, never to
# decide anything: `INV-HW-2` -- this is an estimate and is labelled as one.
APPROX_TOKENS_PER_NODE = 15

BLOCK_A_HEADER = "What is in memory (an index, not the contents):"
BLOCK_B_HEADER = "Relevant to this turn:"


@dataclass(frozen=True, slots=True)
class Rendered:
    """One turn's L1. Carries how it was built, so a bad turn is diagnosable."""

    block_a: str
    block_b: str
    question: str
    selected: tuple = ()
    truncated: bool = False
    selection_ms: float = 0.0
    index_nodes: int = 0
    # Facts selected and then REFUSED because their L3 pointer did not resolve.
    # Reported rather than merely dropped: A-032 requires degradation to be
    # visible, and a turn quietly missing the one fact that answered it looks
    # exactly like a turn where memory had nothing.
    ungrounded: tuple = ()

    def system(self) -> str:
        """Block A. Goes in the system position and is the cached prefix."""
        return self.block_a

    def prompt(self) -> str:
        """Block B then the question, in that order and nothing between them."""
        return f"{self.block_b}\n\n{self.question}" if self.block_b else self.question

    def to_dict(self) -> dict:
        return {"block_a_chars": len(self.block_a),
                "block_b_chars": len(self.block_b),
                "selected": [f.to_dict() for f in self.selected],
                "truncated": self.truncated,
                "selection_ms": round(self.selection_ms, 2),
                "budget_ms": SELECTION_BUDGET_MS,
                "index_nodes": self.index_nodes,
                "approx_index_tokens": self.index_nodes * APPROX_TOKENS_PER_NODE,
                "approx_is_an_estimate": True,
                "ungrounded": [f.to_dict() for f in self.ungrounded],
                "ungrounded_count": len(self.ungrounded)}


class L1Renderer:
    """Builds block A and block B. Never calls a model; never writes."""

    def __init__(self, persona: Any, memory: MemoryGraph) -> None:
        self._persona = persona
        self._memory = memory

    # ---------------------------------------------------------------- block A

    def block_a(self, situation: Any = None, *, index_limit: int = 40) -> tuple:
        """Persona, rules, and the index of what memory holds.

        RENDERED FROM THE CONTRACT EVERY TIME, exactly as `Persona.compose`
        already does and for the same reason: a cached preamble is a copy of a
        governed surface living outside it. The cache being discussed here is
        the PROVIDER's prefix cache, which is keyed on bytes -- so identical
        bytes are what buys the discount, not a local copy.

        NO PER-TURN VALUE MAY ENTER THIS STRING. Not a timestamp, not a turn
        number, not the question. One changing byte at the front invalidates the
        whole prefix and silently costs full freight on every turn afterwards --
        and nothing about the output looks any different when that happens,
        which is why `CI-077` compares two renders byte for byte instead of
        trusting this comment.
        """
        preamble, _sel = self._persona.compose(situation)
        nodes = self._memory.index(limit=index_limit)

        lines = [preamble.rstrip(), "", BLOCK_A_HEADER]
        if not nodes:
            lines.append("- nothing recorded yet")
        for n in nodes:
            # THE SHAPE OF THE OMITTED, not the omitted. A count and a pointer:
            # enough for VESPER to know what it did not bring, and to fetch it
            # deliberately if the turn needs it.
            noun = "fact" if n["facts"] == 1 else "facts"
            lines.append(f"- {n['facts']} {noun} under \"{n['node']}\" "
                         f"({n['kind']}) ->log:{n['pointer']}")
        lines += ["",
                  "These counts say what EXISTS, not what you were given. If a "
                  "turn needs something counted here that is not quoted below, "
                  "say so rather than answering around it."]
        return "\n".join(lines), len(nodes)

    # ---------------------------------------------------------------- block B

    def block_b(self, terms: list, *, ceiling: str = "private",
                depth: int = 2, limit: int = TOP_N, control: Any = None) -> tuple:
        """The few facts this turn needs, deterministically selected.

        Returns `(text, facts, truncated, elapsed_ms)`. The budget is reported
        rather than enforced by cancellation: a half-run query returns nothing
        useful, so the honest behaviour is to ship what was found and SAY that
        it went long.
        """
        started = time.perf_counter()
        # OVER-SELECT WHEN THE OWNER HAS A HAND ON IT. A drop removes facts
        # AFTER selection, so selecting exactly `limit` and then dropping two
        # would hand the turn three facts where five were available. The
        # automatic path is untouched: with no control, this is the same call
        # it always was.
        want = limit if control is None else limit * 3
        facts = list(self._memory.select(terms, ceiling=ceiling, depth=depth,
                                         limit=want))
        if control is not None:
            # DROPPED FIRST, THEN PINNED. An excluded fact must not be able to
            # come back by being pinned -- the owner said to drop it, and a
            # later pin matching the same words is the looser instruction.
            facts = control.excluded(facts)
            pinned = set(control.manual_ids(facts))
            if pinned:
                facts.sort(key=lambda f: (f.id not in pinned,))
        facts = facts[:limit]

        # GROUNDED BEFORE QUOTED. The line below prints `->log:42` as the
        # fact's provenance, and until now it printed it whether or not record
        # 42 existed -- which `core/memory.py`'s header says in as many words is
        # the trap: a `0`, a seq from another store, and a seq for a record
        # never written are all well-formed integers, and every wrong pointer
        # here is PLAUSIBLE. A pointer that is only printed is not a citation.
        #
        # AN UNGROUNDED FACT IS DROPPED, NOT ANNOTATED. Quoting it with a note
        # would put the content in the context anyway, where the model uses it;
        # the caveat travels in the prompt and the content travels into the
        # answer.
        facts, ungrounded = self._ground(facts)

        elapsed = (time.perf_counter() - started) * 1000.0
        truncated = elapsed > SELECTION_BUDGET_MS

        if not facts:
            return "", (), truncated, elapsed, tuple(ungrounded)
        lines = [BLOCK_B_HEADER]
        for f in facts:
            # EVERY LINE CARRIES ITS POINTER. `INV-EVID-2` needs a resolvable
            # span, and a fact quoted without one cannot be cited -- it can only
            # be asserted, which is the thing the whole authority ladder exists
            # to prevent.
            lines.append(f"- {f.subject}/{f.attribute}: {f.value} "
                         f"[rank {f.rank} ->log:{f.log_seq}]")
        if truncated:
            lines.append(f"- (selection took {elapsed:.1f} ms against a "
                         f"{SELECTION_BUDGET_MS} ms budget; this may be fewer "
                         "facts than the question deserved)")
        if ungrounded:
            # SAID IN THE PROMPT, not only on the bus. The model is the one
            # about to answer, and it is the party that needs to know memory
            # came back thinner than it looks -- an event nobody reads mid-turn
            # is a record of the degradation, not a report of it.
            lines.append(f"- ({len(ungrounded)} further fact(s) were withheld: "
                         "their record in the log could not be re-read, so they "
                         "cannot be cited)")
        return "\n".join(lines), tuple(facts), truncated, elapsed, tuple(ungrounded)

    def _ground(self, facts: list) -> tuple:
        """Split into (citable, ungrounded) by re-reading each L3 pointer.

        FAIL-CLOSED ON A MISSING STORE. With no L3 handle nothing can be
        re-read, and the tempting behaviour -- pass everything through, since
        checking is impossible -- would make the guard vanish in exactly the
        configuration that cannot check. Memory with no reachable log is memory
        that cannot cite, so it does not get quoted.
        """
        store = getattr(self._memory, "_store", None)
        if store is None:
            return [], list(facts)
        good, bad = [], []
        for f in facts:
            rec = store.record("log", f.log_seq)
            if rec is None or not _quoted_in(rec.body, f.value):
                # TWO DIFFERENT FAULTS, ONE ANSWER. A pointer to nothing is a
                # fabricated citation; a record that does not contain the value
                # is L2 having drifted from the log it was projected from. Both
                # mean this fact cannot be shown to come from anywhere.
                bad.append(f)
            else:
                good.append(f)
        return good, bad

    # ----------------------------------------------------------------- render

    def render(self, question: str, *, situation: Any = None,
               terms: list | None = None, ceiling: str = "private",
               depth: int = 2, limit: int = TOP_N, control: Any = None) -> Rendered:
        """One turn's L1.

        `terms` defaults to the question's own words, which is the utterance-led
        path. A self-initiated turn passes the SWEEP's finding instead -- one
        mechanism, not two, and it is why this argument exists at all.
        """
        a, nodes = self.block_a(situation)
        b, facts, truncated, ms, ungrounded = self.block_b(
            terms if terms is not None else _terms(question),
            ceiling=ceiling, depth=depth, limit=limit, control=control)
        return Rendered(block_a=a, block_b=b, question=question,
                        selected=facts, truncated=truncated,
                        selection_ms=ms, index_nodes=nodes,
                        ungrounded=ungrounded)


def _quoted_in(body: Any, needle: str) -> bool:
    """Is the fact's value actually present in the record it points at?

    Walks leaves rather than matching rendered JSON, so a value can never be
    satisfied by a KEY NAME -- `{"value": ...}` must not ground the fact whose
    value is the word "value".
    """
    if needle == "":
        return False
    if isinstance(body, dict):
        return any(_quoted_in(v, needle) for v in body.values())
    if isinstance(body, (list, tuple)):
        return any(_quoted_in(v, needle) for v in body)
    return needle in str(body)


def _terms(text: str) -> list:
    """Words worth searching on. Deterministic, and deliberately not clever.

    A stopword list is enough here. Anything smarter is a model in the selection
    path, and selection is on the critical path of every single turn.
    """
    stop = {"the", "and", "for", "with", "what", "when", "where", "which",
            "that", "this", "have", "has", "was", "were", "are", "you", "your",
            "did", "does", "do", "is", "it", "of", "to", "in", "on", "a", "an",
            "my", "me", "i", "we", "us", "about", "how", "why", "who"}
    out = []
    for w in text.split():
        w = w.strip(".,!?;:'\"()[]").lower()
        if len(w) > 2 and w not in stop and w.isascii() and w.isalnum():
            out.append(w)
    return out
