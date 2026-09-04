"""Does this turn ask VESPER to DO something, and what exactly — with what arguments.

THE MODEL PROPOSES AND THE AUTHORIZATION STACK DISPOSES, and getting that order
right is what makes it safe to let a language model name a shell command at all.
Nothing here decides whether an action may happen. This produces a PROPOSAL;
`DF-AUTHORIZE` resolves its level from its arguments and either permits it or
sends it to the stop-and-ask ladder. A proposal for `rm -rf ~` is not dangerous
in this module -- it is an L5 request that no standing grant satisfies, and the
owner is asked by voice. That is exactly the arrangement the corpus already
committed to; this is the first thing that uses it.

WHY A JSON CONTRACT RATHER THAN PROVIDER TOOL-CALLING. The ladder in
`router.toml` spans suppliers with different and changing tool-call dialects,
and a rung that cannot express tools would silently lose the ability to act.
`core/extract.py` already answers this the same way for the same reason, and
sharing the shape means one parser to be careful about instead of two.

REFUSAL IS THE DEFAULT AND SAYING SO IS PART OF THE JOB. `none` is the correct
answer for almost every turn -- questions, chat, recall -- and a proposer biased
toward finding work turns every conversation into an attempted action. The
prompt says so explicitly and `parse` treats anything it cannot read as `none`,
because an unparseable proposal and an absent one should have the same effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

SYSTEM = """You decide whether a request asks a personal assistant to DO
something on its owner's computer, and if so, exactly what.

Return ONLY a JSON object, no prose.

POLITE REQUESTS ARE REQUESTS, NOT QUESTIONS. "Can you run it", "could you
write a file", "would you check", "are you able to open" all ASK YOU TO DO THE
THING. The question mark is manners, not a request for information. Judge what
the owner wants to HAPPEN, never the grammar of the sentence.

Return {"action": "none"} ONLY for: a greeting; small talk; a request to
REMEMBER something; or a question whose answer is knowledge you already have
and that needs nothing on this computer looked at or changed.

If it asks you to run, read, write, check, open, list, create or change
something -- however politely it is phrased -- return:
  {"action": "<capability>", "args": {...}, "why": "<short reason>"}

Examples that are ACTIONS, not questions:
  "can you write a python file that prints hey there and run it"
      -> {"action": "fs.write", "args": {"path": "workspace/hey.py",
          "content": "print(\"hey there\")"}, "why": "create the script"}
  "could you run it and show me the output"
      -> {"action": "shell.run", "args": {"cmd": "python3 workspace/hey.py"},
          "why": "run it and report what it printed"}
  "are you able to check the disk space"
      -> {"action": "shell.run", "args": {"cmd": "df -h"}, "why": "look"}

A MULTI-STEP REQUEST STARTS WITH ITS FIRST STEP. "Write a file and run it" is
`fs.write` now; you will be asked again with the result and can run it then.
Never answer "none" because a request needs more than one action.

NEVER CLAIM YOU CANNOT DO SOMETHING THESE CAPABILITIES COVER. Returning "none"
for a request you can act on makes the assistant tell its owner it is unable to
run a file, which is false and is the worst answer available.

The only capabilities that exist are:

  shell.run   args: {"cmd": "<a single command, no pipes or semicolons>"}
              For looking at the machine: listing files, checking status,
              disk space, running processes.
              Also for the CURRENT TIME OR DATE -- use {"cmd": "date"}.
              "what time is it", "chhal men sa3a", "quelle heure" are all
              questions the machine can answer by looking, not by knowing.

  fs.read     args: {"path": "<path>"}
              For reading a file's contents.

  fs.write    args: {"path": "<path>", "content": "<full new contents>"}
              For CREATING a file. Give the WHOLE content.
              To change part of a file that already exists, prefer fs.edit.

  fs.edit     args: {"path": "<path>", "old": "<exact text to replace>",
                     "new": "<what to put there>"}
              For changing part of a file that already exists. `old` must
              appear EXACTLY ONCE in the file -- include enough surrounding
              lines to make it unique. Copy `old` from what you have read;
              do not retype it from memory.

Rules:
- If unsure, return {"action": "none"}. A wrong action costs more than a
  missed one.
- Never invent a capability that is not in the list above.
- Give the command or path exactly as the owner meant it. Do not add flags
  they did not ask for.
- The request may be in Arabic, Darija, French or English. The args are
  still literal paths and commands.
"""

# The capabilities a proposal may name. A proposal for anything else is dropped
# rather than passed on: `CapabilityRegistry.get` would raise `UnknownCapability`
# anyway, but a proposal that cannot possibly be executed should not reach the
# authorization path and appear in its records as a refusal.
KNOWN = ("shell.run", "fs.read", "fs.write", "fs.edit", "agent.ask", "agent.run")


@dataclass(slots=True)
class Proposal:
    capability_id: str
    args: dict
    why: str = ""

    def to_dict(self) -> dict:
        return {"capability_id": self.capability_id, "args": self.args,
                "why": self.why}


def parse(raw: str) -> Proposal | None:
    """The model's text into a proposal, or None. Anything doubtful is None.

    LOCATED RATHER THAN ASSUMED, for the reason `extract.parse` gives: models
    wrap JSON in prose and in code fences reliably enough that not handling it
    is choosing to fail. Only an OBJECT is accepted -- an array here would mean
    the model answered a different question than the one asked.
    """
    if not raw:
        return None
    t = raw.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                t = p
                break
    # AN ARRAY IS REFUSED, and it takes an explicit test to refuse it: scanning
    # for the first `{` finds the first ELEMENT of a list and returns it as if
    # it were the whole answer. A model that replies with three actions has
    # answered a different question, and quietly executing the first one is the
    # worst available reading of that.
    if t.lstrip().startswith("["):
        return None
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(t[i:j + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action") or "").strip()
    if action in ("", "none", "None"):
        return None
    if action not in KNOWN:
        return None
    args = obj.get("args")
    if not isinstance(args, dict) or not args:
        # An action with no arguments cannot be levelled: `declared_level(args)`
        # is the whole basis of the decision, so an argument-free proposal has
        # no level and must not be given the benefit of a default one.
        return None
    return Proposal(capability_id=action,
                    args={str(k): v for k, v in args.items()},
                    why=str(obj.get("why") or "")[:200])


class IntentProposer:
    """Asks a cheap rung whether this turn is an action, and which one."""

    def __init__(self, gateway: Any, *, profile_id: str = "",
                 bus: Any = None, max_tokens: int = 200) -> None:
        self._gw = gateway
        self._profile = profile_id
        self._bus = bus
        self._max_tokens = max_tokens

    def _emit(self, topic: str, payload: dict) -> None:
        if self._bus is not None:
            try:
                self._bus.publish(topic, subject="intent", payload=payload,
                                  component="intent")
            except Exception:                          # noqa: BLE001
                pass

    def propose(self, text: str, observations: list | None = None,
                recent: list | None = None) -> Proposal | None:
        """None means "this turn is not an action", which is the common case.

        `observations` is what the turn has ALREADY done -- the typed, bounded
        views produced by `capabilities.observe`, never raw output. It is what
        turns a single proposal into a loop: the next step is chosen knowing
        what the last one found.

        NONE IS ALSO HOW THE LOOP ENDS, and that is deliberate. Aider's loop
        continues only while machine evidence says something is unfinished --
        lint errors, a failing test, an exception -- and never because the model
        would like to keep going. Here the equivalent is that the proposer must
        produce a well-formed action that the ladder then permits: "nothing more
        to do" is the default, `parse` returns None for anything doubtful, and a
        turn that is finished simply stops proposing.
        """
        text = (text or "").strip()
        if not text:
            return None
        # WHAT "IT" MEANS. Without the turns either side of it, "run it" names
        # nothing, and the proposer answered "none" to every follow-up -- so
        # the owner rephrased, and got refused again, and was told VESPER
        # could not run a file. Measured 2026-09-04 from the log: five
        # consecutive `{"action": "none"}` against a request to run a script
        # that had just been written one turn earlier.
        #
        # RECENT, NOT ALL OF IT. Enough to resolve a pronoun, not enough to
        # turn a classifier prompt into a transcript: the last few utterances
        # and the last thing actually done.
        if recent:
            text = _render_recent(recent) + "\n\n" + text
        if observations:
            text = text + "\n\n" + _render_observations(observations)
        try:
            out = self._gw.complete(
                text, task_id="intent", system=SYSTEM,
                profile_id=self._profile or None, prefer="latency",
                expected_output_tokens=self._max_tokens, difficulty="easy")
        except Exception as exc:                       # noqa: BLE001
            # A PROPOSER THAT CANNOT BE REACHED PROPOSES NOTHING. It must not
            # fall back to a keyword guess: the fallback would be least reliable
            # exactly when the ladder is degraded, and it would be acting.
            self._emit("intent.failed", {"error": repr(exc)})
            return None
        raw = ((out.get("result") or {}).get("text") or "")
        p = parse(raw)
        self._emit("intent.proposed",
                   {"proposal": p.to_dict() if p else None,
                    "raw": raw[:300] if p is None else ""})
        return p


def _render_recent(recent: list) -> str:
    """The last few turns, as context for a pronoun.

    OWNER LINES AND WHAT WAS DONE, nothing else. A proposal needs to resolve
    "it" and "that file"; it does not need the assistant's prose, which is the
    part most likely to talk it into re-proposing something already finished.
    """
    lines = []
    for item in recent[-6:]:
        if isinstance(item, dict):
            who = item.get("who") or "owner"
            what = str(item.get("text") or "").strip()
        else:
            who, what = "owner", str(item).strip()
        if what:
            lines.append(f"  {who}: {what[:220]}")
    if not lines:
        return ""
    return "Earlier in this conversation (for resolving what 'it' refers to):\n" \
        + "\n".join(lines)


def _render_observations(observations: list) -> str:
    """What already happened this turn, as text the proposer can read.

    Rendered from the TYPED observation, not from the result -- so no raw
    command output or file text is assembled here. Everything in these lines
    came through `capabilities.observe`, which is the crossing INV-AUTH-6
    allows, and the fragment carrying it is tainted `retrieved_external` so
    whatever the proposer decides next is capped at L1 by the context ceiling.
    """
    out = ["ALREADY DONE THIS TURN (most recent last):"]
    for i, o in enumerate(observations, 1):
        o = o if isinstance(o, dict) else {}
        cap = o.get("capability", "?")
        bits = [f"{i}. {cap}"]
        for key in ("cmd", "path", "exit_code", "bytes", "truncated",
                    "replaced_existing", "outcome", "refused_because"):
            if o.get(key) is not None:
                bits.append(f"{key}={o[key]!r}")
        out.append("   " + "  ".join(bits))
        for key in ("stdout_lines", "stderr_lines", "lines"):
            got = o.get(key) or []
            if got:
                out.append(f"     {key}:")
                out.extend("       " + ln for ln in got)
    out.append("")
    out.append("If the request is now satisfied, return {\"action\": \"none\"}. "
               "Do not repeat an action you have already taken.")
    return "\n".join(out)
