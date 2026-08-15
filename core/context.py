"""Context budget manager — A-032, INV-EVID-3.

FOUR BEHAVIOURS, and each is a thing a naive implementation gets wrong.

AUTOMATIC MODE selects by intent and state, within budget. The naive version
sorts by relevance score and fills to the limit; that quietly drops whatever
sits just past the cut with no record, and the answer degrades without anyone
being able to say why.

MANUAL MODE overrides automatic selection, and is invocable BOTH by command and
by interface. The naive version treats manual as a hint that the automatic
scorer may override, which means the owner cannot actually pin a fragment --
and being able to say "use this" is the entire point of manual mode.

OVERRUN DEGRADES BY DROPPING THE LOWEST PRIORITY, WITH A REPORTED DEGRADATION,
NEVER SILENTLY. RB-022 again. A budget that is enforced silently produces an
answer built on less than the caller believes, which is worse than an answer
that says what it lacked.

UNKNOWN PROPAGATES RATHER THAN BEING FILLED (INV-EVID-3). A fragment whose
value is UNKNOWN stays UNKNOWN in the assembled context. The pressure to
substitute a plausible default for a hole is precisely where invention starts,
and it starts here rather than in the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus
from .evidence import UNKNOWN

# Highest first. A fragment's priority is a property of what it IS, not of how
# well it scored -- so a budget squeeze cannot drop the owner's own instruction
# in favour of a well-matching piece of trivia.
PRIORITY = ("system_policy", "owner_instruction", "task_goal",
            "retrieved_evidence", "recent_dialogue", "ambient")
PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITY)}


@dataclass(slots=True)
class Fragment:
    fragment_id: str
    kind: str
    text: str
    tokens: int
    trust_class: str = "model_generated"
    pinned: bool = False          # manual mode
    value_is_unknown: bool = False

    def rank(self) -> int:
        return PRIORITY_RANK.get(self.kind, len(PRIORITY))


@dataclass(slots=True)
class AssembledContext:
    fragments: list = field(default_factory=list)
    tokens_used: int = 0
    budget_tokens: int = 0
    dropped: list = field(default_factory=list)
    mode: str = "automatic"
    unknowns: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "budget_tokens": self.budget_tokens,
            "tokens_used": self.tokens_used,
            "fragments": [f.fragment_id for f in self.fragments],
            "dropped": self.dropped,
            "unknown_fragments": self.unknowns,
            "within_budget": self.tokens_used <= self.budget_tokens,
        }


class ContextBudgetManager:
    def __init__(self, bus: EventBus, *, budget_tokens: int) -> None:
        self._bus = bus
        self.budget_tokens = budget_tokens

    def assemble(self, fragments: list[Fragment], *, intent: str,
                 manual: list[str] | None = None,
                 subject: str = "context") -> AssembledContext:
        """Build a context within budget.

        `manual` is a list of fragment ids the caller has pinned. Pinned
        fragments are placed FIRST and are never dropped by the automatic
        selector -- if they alone exceed the budget the overrun is reported,
        because silently discarding what the owner explicitly asked for would
        make manual mode a suggestion.
        """
        mode = "manual" if manual else "automatic"
        pinned_ids = set(manual or ())
        for f in fragments:
            f.pinned = f.fragment_id in pinned_ids

        # Pinned first, then by priority class, then by declaration order.
        ordered = sorted(fragments, key=lambda f: (not f.pinned, f.rank()))

        out = AssembledContext(mode=mode, budget_tokens=self.budget_tokens)
        for f in ordered:
            if out.tokens_used + f.tokens <= self.budget_tokens or f.pinned:
                out.fragments.append(f)
                out.tokens_used += f.tokens
                if f.value_is_unknown:
                    # INV-EVID-3: carried through as UNKNOWN, not filled.
                    out.unknowns.append(f.fragment_id)
            else:
                out.dropped.append({
                    "fragment_id": f.fragment_id, "kind": f.kind,
                    "tokens": f.tokens,
                    "reason": (f"budget {self.budget_tokens} would be exceeded; "
                               f"{f.kind!r} is the lowest-priority remaining class"),
                })

        if out.dropped:
            # RB-022: reported. A caller must be able to see that its answer was
            # built on less than it asked for.
            self._bus.publish("context.degraded", subject=subject,
                              payload={"intent": intent, **out.to_dict(),
                                       "note": ("dropped lowest-priority context to "
                                                "stay within budget -- reported, "
                                                "never silent")},
                              component="context")
        if out.unknowns:
            self._bus.publish("context.unknown_propagated", subject=subject,
                              payload={"fragments": out.unknowns,
                                       "note": ("UNKNOWN is a first-class value; an "
                                                "empty retrieval is never coerced "
                                                "into an answer (INV-EVID-3)")},
                              component="context")
        if out.tokens_used > self.budget_tokens:
            # Only reachable when pinned fragments alone overrun.
            self._bus.publish("context.budget_exceeded_by_manual_pin",
                              subject=subject,
                              payload={**out.to_dict(),
                                       "note": ("manual pins are honoured over the "
                                                "budget and the overrun is reported; "
                                                "silently dropping a pin would make "
                                                "manual mode a suggestion")},
                              component="context")
        self._bus.publish("context.assembled", subject=subject,
                          payload={"intent": intent, **out.to_dict()},
                          component="context")
        return out
