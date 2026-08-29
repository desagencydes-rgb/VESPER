"""The record of what VESPER answered, written before memory exists.

WHY THIS IS THE FIRST THING BUILT AND NOT THE LAST. Every question worth asking
about the memory system is comparative -- does memory make the answers better,
does it cost more than it returns, does carrying more of it help or hurt. None
of those is answerable without a record of VESPER answering WITHOUT memory, on
real turns, from the same owner.

That record can only be collected before memory is switched on. Afterwards
there is no way back to a clean before, and the comparison is gone permanently.
It costs an append to a store that already exists. So it lands first.

WHAT IS RECORDED AT WRITE TIME, AND WHY EACH FIELD CANNOT BE RECONSTRUCTED
LATER:

  * `declined` vs `could_not` -- whether VESPER CHOSE not to answer or was
    UNABLE to. In a log these are the same event, and afterwards nothing can
    tell them apart. It has to be decided at the moment it happens or the
    distinction is lost, which is why it is a required argument with no
    default rather than something inferred downstream.
  * `gap_ms` -- time since the previous turn. Decides, later, whether a cache
    entry would still have been alive. Reconstructible only if every turn is
    present, which it will not be.
  * `answer` verbatim -- the thing being judged. A summary of it is not.

WHAT IS DELIBERATELY NOT RECORDED HERE. Whether the owner corrected, repeated
or rephrased. Those are properties of what happens NEXT, unknowable while this
turn is being written, and inventing a field for them now would produce a
column that is null on every row and read later as "no corrections happened".
They are annotated by a separate pass over the log.

NO MODEL, AND NO JUDGEMENT. This transcribes. The moment it starts deciding
which turns are worth keeping, the corpus becomes a product of that decision
and every later measurement inherits it -- which is exactly the contamination
the data plan names as the foundation's biggest risk. Capture is total here;
selection happens at projection, where it is auditable because the unselected
material still exists.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = 1
STORE = "log"
KIND = "turn"

# The answer is kept whole. A cap exists only to stop one pathological reply
# consuming the store, and when it bites it is RECORDED as truncation rather
# than silently applied -- a truncated answer that does not say so would be
# read later as a short answer, which is a different measurement.
MAX_TEXT = 32_000


@dataclass(slots=True)
class Turn:
    """One owner-facing exchange, as it happened."""
    question: str
    answer: str
    # REQUIRED, NO DEFAULT. See the module docstring: a default here would let
    # every caller skip the one decision that cannot be made afterwards.
    outcome: str                      # "answered" | "declined" | "could_not"
    provider_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_ms: float | None = None
    gap_ms: float | None = None
    difficulty: str | None = None
    language: str | None = None       # what the OWNER wrote in, not the reply
    truncated: bool = False
    schema_version: int = SCHEMA_VERSION

    OUTCOMES = ("answered", "declined", "could_not")

    def __post_init__(self) -> None:
        if self.outcome not in self.OUTCOMES:
            raise ValueError(
                f"outcome must be one of {self.OUTCOMES}, got {self.outcome!r}. "
                "'declined' and 'could_not' are not interchangeable: one is a "
                "choice and the other is a failure, and nothing downstream can "
                "tell them apart once this row is written.")
        for name in ("question", "answer"):
            v = getattr(self, name)
            if len(v) > MAX_TEXT:
                setattr(self, name, v[:MAX_TEXT])
                self.truncated = True


class BaselineRecorder:
    """Appends one record per owner-facing turn. Never blocks the turn.

    The recorder holds no opinion about what it writes. It is given a `Turn`
    and appends it; a failure to append is reported and swallowed, because the
    contract is that background bookkeeping never turns a good answer into an
    error.
    """

    def __init__(self, stores: Any, clock: Any, *, on_error: Any = None) -> None:
        self._stores = stores
        self._clock = clock
        self._on_error = on_error
        self._last_turn_ms: float | None = None
        self.written = 0
        self.failed = 0

    def gap_ms(self, now_ms: float | None = None) -> float | None:
        """Milliseconds since the previous recorded turn, or None for the first.

        None on the first turn is deliberate and is not the same as 0. A zero
        would say "no time passed", which is a claim about the world; None says
        "there was no previous turn", which is a fact about the record.
        """
        now = time.monotonic() * 1000.0 if now_ms is None else now_ms
        prev = self._last_turn_ms
        return None if prev is None else round(now - prev, 1)

    def record(self, turn: Turn, *, now_ms: float | None = None) -> dict | None:
        now = time.monotonic() * 1000.0 if now_ms is None else now_ms
        if turn.gap_ms is None:
            turn.gap_ms = self.gap_ms(now)
        self._last_turn_ms = now
        body = asdict(turn)
        try:
            rec = self._stores.append(STORE, KIND, body, self._clock.now())
            self.written += 1
            return {"seq": getattr(rec, "seq", None), "kind": KIND}
        except Exception as exc:                       # noqa: BLE001
            # SWALLOWED ON PURPOSE, AND COUNTED. A recorder that raises turns a
            # working answer into a failed turn, which is a worse outcome than
            # a missing row. `failed` is what makes the loss visible rather
            # than silent -- an unexplained gap in the log with no counter is
            # indistinguishable from a quiet period.
            self.failed += 1
            if self._on_error is not None:
                self._on_error(exc)
            return None

    def stats(self) -> dict:
        return {"written": self.written, "failed": self.failed,
                "schema_version": SCHEMA_VERSION}
