"""A sub-agent thinks. It does not act, and its answer is an observation.

WHY DELEGATION IS THIS SHAPE AND NOT ANOTHER. `PolicyDecisionPoint.attenuate`
returns None -- not a weaker grant, NONE -- when the parent grant is
non-delegable, and every standing grant `Actor._issue_standing` hands out is
`delegable=False`. `INV-AUTH-2` closes the L4/L5 tiers on top of that. So a
sub-agent cannot inherit a capability by construction; there is no path that
gives it one. That is not a limitation to work around, it is the answer: a
sub-agent reads and reasons, and anything that follows is done by the parent,
under the parent's own authority, down the same ladder as everything else.

ITS ANSWER IS AN OBSERVATION, AND THAT IS THE WHOLE SAFETY ARGUMENT. Delegation
is otherwise the cleanest laundering path in the system: hand a sub-agent a page
of untrusted text, and receive back a confident, well-formed proposal with no
trace of where it came from. `INV-ACT-3` says content entering the system is
`retrieved_external` and MAY NEVER RAISE the authority of any action -- so a
sub-agent's reply is classed exactly as a shell command's output is, and asking
one lowers the ceiling for the rest of the turn like any other look at the world.

NO NESTING. A sub-agent that can start a sub-agent is an unbounded tree, and the
budget that bounds one call does not bound a tree. This class is never given the
means to make another, in the same way `PredicateEvaluator` cannot call a model
because it was never handed anything that could.

BOUNDED IN BOTH DIRECTIONS. What goes in is capped because a sub-agent is a way
to spend the parent's context somewhere it cannot be seen; what comes back is
capped because an answer is an observation and observations are already bounded
for exactly this reason -- `OBS_MAX_LINES` exists so a runaway command cannot
fill a context window, and a runaway sub-agent is the same failure with a nicer
name.

ONE ROUND. A conversation would need a place to keep it, a budget over the whole
exchange, and a way for the owner to see what was said in their name. A single
question and a single answer needs none of that, and is what delegation is
actually wanted for: read this, tell me what matters.
"""

from __future__ import annotations

from typing import Any

# What a sub-agent may be handed, and what it may hand back. Characters rather
# than tokens because this is a guard rather than an accountant -- the gateway
# does the token accounting, and a guard that needs a tokenizer to run is a
# guard that fails when the tokenizer does.
MAX_QUESTION_CHARS = 4000
MAX_CONTEXT_CHARS = 24000
MAX_ANSWER_CHARS = 4000

# The system prompt is a contract, not a suggestion. It says what the sub-agent
# is FOR, and the two things it says it cannot do are things it structurally
# cannot do -- the sentence is there so a model does not spend its answer
# proposing actions nobody can execute, not because the sentence is the defence.
SYSTEM = (
    "You are a reader. You are given some material and one question about it. "
    "Answer the question from the material only. You cannot run commands, read "
    "files, or change anything -- if the answer requires doing something, say "
    "what would need doing and stop. Be brief and concrete. If the material "
    "does not answer the question, say so plainly rather than guessing.")


class SubAgentUnavailable(Exception):
    """No gateway was supplied, so nothing could be asked."""


class SubAgent:
    """One question, one answer, no capabilities."""

    def __init__(self, gateway: Any, *, bus: Any = None,
                 profile_id: str = "") -> None:
        self._gw = gateway
        self._bus = bus
        self._profile_id = profile_id
        # DELIBERATELY ABSENT: an executor, a registry, a policy decision point,
        # a job registry, a shell session. Listed here because their absence is
        # the design -- a later maintainer adding one would be removing the
        # reason this class is safe to reach from a proposal.

    def ask(self, question: str, *, material: str = "",
            task_id: str = "subagent") -> dict:
        """Ask, and return what came back with its provenance attached."""
        if self._gw is None:
            raise SubAgentUnavailable(
                "no model gateway, so a sub-agent could not be asked. Refused "
                "rather than answered from nothing.")
        q = str(question or "").strip()[:MAX_QUESTION_CHARS]
        if not q:
            raise ValueError("a sub-agent needs a question")
        mat = str(material or "")[:MAX_CONTEXT_CHARS]

        prompt = f"Material:\n{mat}\n\nQuestion: {q}" if mat else q
        out = self._gw.complete(prompt, task_id=task_id, system=SYSTEM,
                                expected_output_tokens=512,
                                difficulty="moderate",
                                **({"profile_id": self._profile_id}
                                   if self._profile_id else {}))
        text = ((out.get("result") or {}).get("text") or "").strip()
        truncated = len(text) > MAX_ANSWER_CHARS
        text = text[:MAX_ANSWER_CHARS]
        record = {
            "question": q,
            "answer": text,
            "truncated": truncated,
            "material_chars": len(mat),
            # STATED IN THE RECORD, not left to the caller to remember. Whoever
            # reads this back -- the actor, an audit, the owner -- is told what
            # it is: a model's words about material this system did not verify.
            "trust_class": "retrieved_external",
            "note": ("a sub-agent's answer is an observation, not an "
                     "instruction: it may never raise the authority of any "
                     "action (INV-ACT-3)"),
        }
        if self._bus is not None:
            try:
                self._bus.publish("subagent.answered", subject=task_id,
                                  payload={k: v for k, v in record.items()
                                           if k != "answer"},
                                  component="subagent")
            except Exception:                          # noqa: BLE001
                pass
        return record
