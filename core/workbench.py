"""What VESPER is thinking and what it has done, derived from events.

TWO COLUMNS, TWO DIFFERENT KINDS OF CLAIM, AND THEY MUST NOT BE MIXED.

  THOUGHTS are VESPER in the first person, in the hand (DESIGN-FOUNDATION SS5).
      Templated from `voice.toml [hand]`, never generated. SS5's rule is
      enforced here rather than trusted: no numbers, no system messages, at most
      two lines.

  ACTIONS are the instrument. A row per thing done, with the provider, the
      profile, the outcome and the time -- everything the hand is forbidden to
      carry, in the face that is meant to carry it.

WHY THE THOUGHTS ARE NOT A MODEL'S REASONING TRACE. Asking a model what it was
thinking produces a SECOND generation, after the fact, about the first -- text
shaped like an explanation and causally downstream of nothing. The decisions
rendered here are real and were already recorded before this file existed: which
difficulty the request classified as and on which signal, which profile the
router selected and why, which rung answered, which register the persona chose.
Putting those in the first person is VESPER saying what it is doing. The
alternative is fiction with a citation.

LIVE AND DONE ARE THE SAME ROW. An action opens when the work starts and closes
when it finishes, in place, keyed by task. A separate "in flight" list would let
the two disagree -- and the moment they disagree the owner is reading a board
that says a thing is running and a thing is finished about one event.

IT IS A SUBSCRIBER, NOT A CALLER. Nothing calls `note()` from the request path;
this attaches to the bus and reads what the system already publishes. A method
somebody has to remember to call is a board that is accurate until the first
time somebody forgets, and `core/home_state.py`'s header records what that costs.
"""

from __future__ import annotations

import re
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "contracts" / "policy" / "voice.toml"

# SS5, mechanically. A digit in the hand is the rule broken -- the number
# belongs in the actions column where the owner can act on it.
DIGIT = re.compile(r"\d")

# How many rows the board holds. Enough to see a failover through; short enough
# that the card is a glance and not a log.
MAX_ACTIONS = 12

# HOW MANY THOUGHTS ARE KEPT, WHICH IS NOT HOW MANY ARE SHOWN.
#
# This was one number and conflated two things. SS5's rule is about LINES on
# screen -- "never more than ~two lines" -- and it was implemented as a cap of
# two THOUGHTS, which is wrong in both directions: one long thought is already
# several lines and passed, while two short ones are one line each and were
# treated as the ceiling.
#
# Worse, the cap did the discarding here, so the renderer got exactly two
# strings and no way to prefer the new one. Whichever thought was newest had to
# share the budget with a stale one even when it needed all of it.
#
# So the record keeps a few and `hand.max_lines` becomes what it always said it
# was: a budget of RENDERED LINES, spent newest-first, by the only layer that
# can measure a line.
MAX_THOUGHTS_KEPT = 4


class HandRuleViolation(Exception):
    """A line in the hand breaks SS5. Refused at load, not at 3 a.m."""


@dataclass(slots=True)
class Action:
    """One thing VESPER did. Opens live, closes in place."""
    verb: str
    detail: str
    state: str = "live"          # live | done | failed
    seconds: float | None = None
    key: str = ""

    def to_dict(self) -> dict:
        return {"verb": self.verb, "detail": self.detail, "state": self.state,
                "seconds": self.seconds}


class Workbench:
    """Subscribes to the bus; publishes two lists for the home to render."""

    def __init__(self, *, voice_path: Path | None = None) -> None:
        with (voice_path or VOICE).open("rb") as fh:
            self._hand = (tomllib.load(fh).get("hand") or {})
        self._max_lines = int(self._hand.get("max_lines", 2))
        for name, line in self._hand.items():
            if name == "max_lines":
                continue
            if DIGIT.search(str(line)):
                raise HandRuleViolation(
                    f"hand line {name!r} contains a number: {line!r}. "
                    "DESIGN-FOUNDATION SS5 forbids it -- the hand is the aside, "
                    "and a figure the owner might act on belongs in the actions "
                    "column, in a face meant to carry one.")
        self._lock = threading.RLock()
        self._thoughts: list[str] = []
        self._actions: list[Action] = []

    # ------------------------------------------------------------ thoughts

    def observe(self, line: str) -> str | None:
        """A thought in VESPER's OWN words, not one from the phrasebook.

        `think` renders a canned line by key, which is right for the moods it
        was built for -- "Straightforward enough." says something true about an
        easy request and says it well. It is the WHOLE column that was the
        problem: every thought on screen came from a fixed list, so the surface
        showed a mood and never a reason. The owner asked for real thoughts
        rather than templates, and this is the door for them: what the proposer
        actually decided, what a step actually observed, in the words that
        decision was actually made in.

        SAME DEDUPE AND SAME BOUND as `think`, because a real thought repeated
        is still one thought, and an unbounded column is a memory leak with a
        typeface.
        """
        line = " ".join(str(line or "").split())
        if not line:
            return None
        with self._lock:
            if self._thoughts and self._thoughts[-1] == line:
                return line
            self._thoughts.append(line)
            del self._thoughts[:-MAX_THOUGHTS_KEPT]
        return line

    def think(self, key: str) -> str | None:
        """Render one hand line by name. Unknown keys are silent, not invented."""
        line = self._hand.get(key)
        if not line:
            return None
        with self._lock:
            if self._thoughts and self._thoughts[-1] == line:
                # The same thought twice running is not two thoughts. Repeats
                # arrive naturally -- two easy requests in a row -- and a column
                # that stutters reads as a loop rather than as a mind.
                return line
            self._thoughts.append(line)
            del self._thoughts[:-MAX_THOUGHTS_KEPT]
        return line

    # ------------------------------------------------------------- actions

    def open(self, key: str, verb: str, detail: str) -> None:
        with self._lock:
            for a in self._actions:
                if a.key == key and a.state == "live":
                    a.verb, a.detail = verb, detail
                    return
            self._actions.append(Action(verb, detail, "live", None, key))
            del self._actions[:-MAX_ACTIONS]

    def close(self, key: str, *, state: str = "done", verb: str | None = None,
              detail: str | None = None, seconds: float | None = None) -> None:
        """Close the newest LIVE row with this key. Silent if there is none.

        SILENT ON PURPOSE. A close with no open is a real ordering -- a provider
        answering after the row scrolled off, a runtime restarted mid-request --
        and inventing a row to close would put a completed action on the board
        that nothing ever started.
        """
        with self._lock:
            for a in reversed(self._actions):
                if a.key == key and a.state == "live":
                    a.state = state
                    if verb is not None:
                        a.verb = verb
                    if detail is not None:
                        a.detail = detail
                    a.seconds = seconds
                    return

    # ------------------------------------------------------------ the bus

    def attach(self, bus: Any) -> None:
        """Read what the system already publishes. Nothing calls in here."""

        def on_route(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            task = str(p.get("task_id") or "task")
            prof = p.get("profile_id") or "a profile"
            self.open(f"route:{task}", "routing", str(prof))
            # The difficulty is the request's own classification and is the one
            # thing here VESPER genuinely decided about the question itself.
            d = p.get("difficulty")
            if d:
                self.think(str(d))
            if p.get("degraded_from"):
                self.think("degraded")

        def on_attempt(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            pid = str(p.get("provider_id") or "a rung")
            outcome = p.get("outcome")
            ms = p.get("elapsed_ms")
            secs = (float(ms) / 1000.0) if isinstance(ms, (int, float)) and ms else None
            key = f"call:{pid}"
            if outcome == "ok":
                self.close(key, state="done", detail=pid, seconds=secs)
                # THE VERB CHANGES WHEN THE ROW CLOSES. It opened as `routing`
                # naming a PROFILE, and closing it named a PROVIDER while still
                # saying `routing` -- a row reading "routing / ollama-strong",
                # which is neither what happened nor a thing VESPER does.
                self.close("route:" + str(p.get("task_id") or "task"),
                           state="done", verb="answered", detail=pid,
                           seconds=secs)
            elif outcome == "error":
                cls = str(p.get("classification") or "failed")
                self.open(key, "asking", pid)
                self.close(key, state="failed", detail=f"{pid} — {cls}", seconds=secs)
                self.think("failing_over")
            elif outcome == "skipped":
                pass          # a rung never called is not an action taken
            else:
                self.open(key, "asking", pid)

        def on_no_route(ev: Any) -> None:
            self.think("unknown")

        for topic, fn, name in (
            ("route.selected", on_route, "workbench-route"),
            ("gateway.attempt", on_attempt, "workbench-attempt"),
            ("route.no_route", on_no_route, "workbench-noroute"),
        ):
            # `name` IS KEYWORD-ONLY on EventBus, and the try/except that used
            # to paper over that would have swallowed a real signature change
            # just as quietly. Called the one correct way instead.
            #
            # INV-COORD-5: delivery is at-least-once, so a consumer that cannot
            # recognise a repeat will double-apply, and the bus refuses to
            # register one that has not said how it recognises them. The event
            # id is the right key here and it is worth saying WHY rather than
            # passing it because the bus asked: a redelivered `route.selected`
            # is the same routing decision, not a second one, and a board that
            # counted it twice would show VESPER doing a thing it did once.
            #
            # The operations happen to be idempotent as well -- `open` updates
            # a live row with the same key rather than adding one, `close`
            # finds no live row the second time, and `think` collapses a
            # repeated line. That is a second line of defence and not the
            # reason: relying on it would make the board's correctness depend
            # on an accident of how it stores things.
            bus.subscribe(topic, fn, name=name,
                          idempotency_key=lambda e: e.event_id)

    # -------------------------------------------------------------- render

    def state(self) -> dict:
        """NEWEST THOUGHT FIRST, because the renderer spends its line budget in
        order and the newest is the one that must never be the casualty.

        The list stays chronological in `self._thoughts` -- that is the record,
        and a record that reorders itself for a view is not a record. The
        reversal happens here, at the boundary, where it is a presentation
        decision and says so.
        """
        with self._lock:
            return {"thoughts": list(reversed(self._thoughts)),
                    "max_lines": self._max_lines,
                    "actions": [a.to_dict() for a in self._actions]}
