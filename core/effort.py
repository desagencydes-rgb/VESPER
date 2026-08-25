"""How hard a model is told to think, per task — and the floor that protects it.

THE POINT OF THIS FILE IS NOT TO SPEND LESS. It is to stop spending MORE than
a task needs, which is a different thing and the distinction is the whole
design. Measured 2026-08-25 on gpt-oss-120b, same prompt, same answer `OK`:

    reasoning_effort=low       26 completion tokens
    reasoning_effort=medium    34
    (unset, provider default)  64
    reasoning_effort=high     119

4.6x between low and high FOR AN IDENTICAL ANSWER. On a trivial task, high
effort buys nothing and costs everything -- the answer was `OK` either way.

BUT THE INVERSE IS THE MORE EXPENSIVE MISTAKE, AND THIS FILE EXISTS TO PREVENT
IT. Cheap-by-default on a hard task buys a confidently wrong answer, and a
wrong answer is not a saving: it is the whole cost of the call, plus the cost
of acting on it, plus the cost of the call that has to be made again. The
router already states this rule for model choice --

    "routing hard work to a draft model produces a confidently wrong answer,
     which is worse than a late one"                        core/router.py

-- and effort is the same rule applied to the same model. A strong model told
to think cheaply is a weaker model with better provenance.

SO EFFORT IS A FLOOR, NOT A TARGET. `for_difficulty` returns the MINIMUM
effort a difficulty may be answered at. Callers may raise it and may never
lower it, and `EffortFloorViolation` is raised rather than silently clamped,
because a silent clamp is how a cost optimisation quietly becomes a capability
regression that nothing detects. A-011-style negative control: a build that
maps `hard` to `low` must FAIL the floor test.

MAX_TOKENS IS PART OF EFFORT, AND GETTING IT WRONG LOOKS LIKE SUCCESS.
Measured the same day: Groq at `max_tokens=16` returned HTTP 200,
`finish_reason: length`, and `content: ''` -- reasoning consumed the entire
budget before a single content token was emitted. A budget too small does not
produce a short answer; it produces NO answer, with a success status. So the
budget here is always reasoning headroom PLUS output, never output alone.
"""

from __future__ import annotations

from dataclasses import dataclass

# core/router.py DIFFICULTY, imported by value rather than restated so the two
# cannot drift. Kept as a tuple here to avoid a circular import at module load.
DIFFICULTY = ("trivial", "easy", "moderate", "hard")

# Ordered weakest to strongest. Comparison is by INDEX, never by string.
EFFORTS = ("low", "medium", "high")
EFFORT_RANK = {e: i for i, e in enumerate(EFFORTS)}

# Reasoning headroom to reserve, by effort. Anchored on the measurement above
# (low 26 / medium 34 / high 119 total completion tokens on a TRIVIAL prompt)
# and then multiplied, because reasoning scales with the problem and those
# figures are the floor of the range, not its middle.
#
# GENEROUS ON PURPOSE. Unused budget costs nothing -- providers bill what was
# generated, not what was permitted. Insufficient budget costs the entire call
# AND returns a success status while doing it. The asymmetry is total, so the
# only defensible bias is upward.
REASONING_HEADROOM = {"low": 512, "medium": 2_048, "high": 8_192}


class EffortFloorViolation(Exception):
    """A caller asked for less effort than the difficulty permits."""


@dataclass(frozen=True, slots=True)
class Effort:
    reasoning_effort: str
    max_tokens: int
    difficulty: str
    rationale: str

    def to_dict(self) -> dict:
        return {"reasoning_effort": self.reasoning_effort,
                "max_tokens": self.max_tokens,
                "difficulty": self.difficulty,
                "rationale": self.rationale}


# The floor per difficulty. NOT a lookup of "what to use" -- a lookup of
# "the least this may be answered at".
#
# `moderate` sits at medium rather than low deliberately. Low effort measured
# 26 tokens against medium's 34 -- an 8-token difference on a trivial prompt,
# which is nothing -- so buying capability at that price is obviously correct.
# The large jump is medium -> high (34 -> 119), and that is the one worth
# spending only where the difficulty earns it.
FLOOR = {
    "trivial":  "low",
    "easy":     "low",
    "moderate": "medium",
    "hard":     "high",
}


def for_difficulty(difficulty: str, *,
                   expected_output_tokens: int = 1_024,
                   raise_to: str | None = None) -> Effort:
    """The effort floor for a difficulty, optionally raised.

    `raise_to` may only ever RAISE. Passing a weaker effort raises rather than
    clamping: a caller that thinks it lowered effort and did not would go on
    believing it had saved something, and a caller that lowered it successfully
    would have silently downgraded an answer nobody asked to downgrade.
    Neither is acceptable, so the attempt is refused loudly.
    """
    if difficulty not in DIFFICULTY:
        raise ValueError(f"unknown difficulty {difficulty!r}, expected {DIFFICULTY}")
    floor = FLOOR[difficulty]
    effort = floor
    rationale = (f"floor for difficulty={difficulty} is {floor} "
                 "(effort is a FLOOR, never a target: cheap thinking on a hard "
                 "task buys a confidently wrong answer, which costs more than "
                 "the tokens it saves)")
    if raise_to is not None:
        if raise_to not in EFFORT_RANK:
            raise ValueError(f"unknown effort {raise_to!r}, expected {EFFORTS}")
        if EFFORT_RANK[raise_to] < EFFORT_RANK[floor]:
            raise EffortFloorViolation(
                f"difficulty={difficulty!r} has an effort floor of {floor!r}; "
                f"{raise_to!r} is below it. Effort may be raised, never "
                "lowered -- silently granting this would turn a cost "
                "optimisation into a capability regression that no test sees.")
        if EFFORT_RANK[raise_to] > EFFORT_RANK[floor]:
            effort = raise_to
            rationale += f"; RAISED to {raise_to} by the caller"
    budget = REASONING_HEADROOM[effort] + int(expected_output_tokens)
    return Effort(effort, budget, difficulty, rationale)


def guard_response(content: str | None, finish_reason: str | None,
                   effort: Effort) -> None:
    """Refuse a 200 that carried no answer.

    MEASURED 2026-08-25: Groq returned HTTP 200 with `finish_reason: length`
    and `content: ''` because reasoning consumed the whole token budget. The
    gateway recorded that as `ok` and would have handed an empty string to the
    caller as though it were an answer.

    A SUCCESS STATUS IS NOT A SUCCESSFUL ANSWER, and this is the cheapest
    possible place to say so. Raised with the gateway's TRANSIENT vocabulary so
    it is retried -- with a bigger budget -- rather than treated as terminal.
    """
    if content is not None and content.strip():
        return
    e = RuntimeError(
        f"provider returned success with empty content "
        f"(finish_reason={finish_reason!r}, max_tokens={effort.max_tokens}, "
        f"reasoning_effort={effort.reasoning_effort}). Reasoning tokens are "
        "billed as completion tokens and can consume the entire budget before "
        "any content is emitted -- measured at 57 of 64 tokens on a "
        "seven-character answer. Retry with a larger budget.")
    # core/gateway.py reads these two attributes off any exception.
    e.classification = "server_error"      # TRANSIENT -> retried
    e.retry_after_ms = None
    raise e
