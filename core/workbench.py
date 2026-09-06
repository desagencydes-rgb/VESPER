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
import shlex
import threading
import time
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
# THE OWNER ASKED FOR MORE HERE, in these words: "add more to the place showing
# activity so they show up with more details". Twelve rows was a glance at the
# last failover; a turn that runs a command, reads a file and writes another
# spends three of them, so a session's worth of work scrolled off within
# minutes. The card scrolls, so depth costs nothing but the list itself.
MAX_ACTIONS = 40

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


# ------------------------------------------------------------------ commands
#
# THE COMMAND RECORD IS NOT THE ACTION ROW, AND CONFLATING THEM WAS THE THING
# THE OWNER KEPT HITTING. An action row is a status line -- eighty characters,
# one verb, gone in twelve rows. A command is something the owner needs to READ:
# what ran, where, what it printed, and, when it failed, why. Compressing the
# second into the first is how "it ran and came back with error code 1" became
# the whole of what VESPER could say about a rename that failed for a reason
# `mv` had already written down.
#
# Enough to see a session's work; short enough that it stays a card.
COMMANDS_MAX = 50

# What one command may contribute. Two bounds because they fail differently: a
# single enormous line blows the byte budget without ever reaching the line
# count, and a million short lines blow the line count while each is tiny.
COMMAND_OUT_MAX_BYTES = 16_384
COMMAND_OUT_MAX_LINES = 400

# The board's depth, owned by the module that decides what goes on it.
# Imported rather than restated so the two cannot drift.
from .longform import EXPLANATIONS_MAX          # noqa: E402


@dataclass(slots=True)
class Command:
    """One command VESPER ran, with everything needed to judge the result.

    ARGV IS THE RECORD; `display` IS THE RENDERING. `shell_run` refuses
    `shell=True`, so the argv list is what the kernel actually received. A
    single string is a RECONSTRUCTION of it, and the gap between the two is
    where a reader believes one thing ran while another did -- the same class
    of mistake as a classifier reading a command the shell never saw. So the
    list is stored, `display` is derived from it for the owner's eye and for
    the copy button, and nothing ever parses `display` back.
    """
    id: str
    argv: tuple[str, ...]
    cwd: str = ""
    state: str = "ok"                     # ok | failed | running
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: int | None = None
    truncated: bool = False

    @property
    def display(self) -> str:
        return shlex.join(self.argv)

    def to_dict(self) -> dict:
        return {"id": self.id, "argv": list(self.argv), "display": self.display,
                "cwd": self.cwd, "state": self.state,
                "exit_code": self.exit_code, "stdout": self.stdout,
                "stderr": self.stderr, "elapsed_ms": self.elapsed_ms,
                "truncated": self.truncated}


def _clip(text: str) -> tuple[str, bool]:
    """Trim one output stream to the card's budget, keeping the FIRST lines.

    THE FIRST LINES, NOT THE LAST. A traceback names its cause at the top and a
    failing build names the first error first; keeping the tail keeps the
    summary and throws away the diagnosis. The owner reads this to find out
    what went wrong, and what went wrong is at the beginning.

    AND THE CUT IS VISIBLE. Silent truncation reads as "the command printed
    nothing more", which is a false statement the owner would act on.
    """
    text = str(text or "")
    lines = text.split("\n")
    cut = len(lines) > COMMAND_OUT_MAX_LINES
    if cut:
        lines = lines[:COMMAND_OUT_MAX_LINES]
    out = "\n".join(lines)
    # Measured in BYTES, because the budget is about what crosses into a JSON
    # file and a webview, and a character count is not that at any non-ASCII
    # input -- which VESPER's own output regularly is.
    raw = out.encode("utf-8")
    if len(raw) > COMMAND_OUT_MAX_BYTES:
        out = raw[:COMMAND_OUT_MAX_BYTES].decode("utf-8", "ignore")
        cut = True
    return out, cut


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
    # WHAT KIND OF THING THIS WAS, in the system's own vocabulary: a capability
    # id, a provider id, a profile. Kept beside the human sentence rather than
    # folded into it, because the two answer different questions -- `detail`
    # says what happened and this says which machinery it happened in, and a
    # row that concatenates them is unreadable at eleven pixels.
    meta: str = ""
    # WHEN, so a board read after the fact is a record and not just a state.
    # Wall clock, and INV-COORD-4 has nothing to say about it: this orders
    # nothing and supersedes nothing, it is rendered next to the row.
    at_ms: int = 0

    def to_dict(self) -> dict:
        return {"verb": self.verb, "detail": self.detail, "state": self.state,
                "seconds": self.seconds, "meta": self.meta, "at_ms": self.at_ms}


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
        self._commands: list[Command] = []
        self._explanations: list[dict] = []
        self._seq = 0

    # -------------------------------------------------------------- restore

    def seed(self, state: Any) -> int:
        """Take back the board that was on screen before the last restart.

        THE OWNER WATCHED A CARD DISAPPEAR AND SAID SO. Every rebuild restarts
        the runtime, the lists live in memory, and `home.json` is overwritten
        with an empty workbench on the first pump -- so a restart blanked the
        commands and the explanations while everything was working correctly.
        A surface that empties for reasons the owner cannot see is exactly the
        failure this whole chunk was asked for.

        SEEDED FROM `home.json` ITSELF, NOT FROM A SECOND FILE. That file is
        already the contract between the runtime and the chrome, it already
        survives a restart, and it is already bounded by these same caps.
        Adding a store beside it would be a second answer to a question that
        has one, and the two would eventually disagree.

        FINISHED ACTIONS AND THOUGHTS ARE RESTORED; LIVE ROWS ARE NOT.
        The first version restored neither, on the reasoning that an action row
        can be `live` and putting a spinner on the board for work that stopped
        existing with the process would be a lie. The `live` half of that is
        right and still holds. The rest was wrong, and the owner reported it in
        as many words -- "the card where vesper's thoughts, actions, and
        providers is gone, where the fuck did it go" -- because `.work.idle`
        hides the card when it has nothing, so a restart made it VANISH rather
        than empty.

        A finished action is a record of something that happened and stays true
        across a restart, exactly like a command. A thought is VESPER's own
        sentence about a decision it really made. Both are restorable; a `live`
        row is the only thing that is not, and it is dropped rather than
        coerced -- guessing that an interrupted action completed would put a
        false outcome on the board, which is worse than a shorter list.
        """
        state = state if isinstance(state, dict) else {}
        n = 0
        with self._lock:
            if not self._commands:
                for c in (state.get("commands") or [])[-COMMANDS_MAX:]:
                    if not isinstance(c, dict) or not c.get("argv"):
                        continue
                    self._commands.append(Command(
                        id=str(c.get("id") or f"cmd{len(self._commands)}"),
                        argv=tuple(str(a) for a in c["argv"]),
                        cwd=str(c.get("cwd") or ""),
                        state=str(c.get("state") or "ok"),
                        exit_code=(c.get("exit_code")
                                   if isinstance(c.get("exit_code"), int) else None),
                        stdout=str(c.get("stdout") or ""),
                        stderr=str(c.get("stderr") or ""),
                        elapsed_ms=(c.get("elapsed_ms")
                                    if isinstance(c.get("elapsed_ms"), int) else None),
                        truncated=bool(c.get("truncated"))))
                    n += 1
                # THE COUNTER RESUMES PAST WHAT WAS RESTORED. Starting from
                # zero would mint `cmd1` a second time, and the page keys its
                # open rows on that id -- so a restored row and a new one would
                # be the same row as far as the surface is concerned.
                self._seq = max(self._seq, len(self._commands))
            if not self._explanations:
                for e in (state.get("explanations") or [])[-EXPLANATIONS_MAX:]:
                    if isinstance(e, dict) and e.get("blocks"):
                        self._explanations.append(e)
                        n += 1
            if not self._actions:
                for a in (state.get("actions") or [])[-MAX_ACTIONS:]:
                    if not isinstance(a, dict):
                        continue
                    # A `live` ROW IS DROPPED, NOT COERCED. Whatever it was
                    # doing stopped when the process did, and neither "done"
                    # nor "failed" is a thing anyone knows.
                    if a.get("state") not in ("done", "failed"):
                        continue
                    self._actions.append(Action(
                        verb=str(a.get("verb") or ""),
                        detail=str(a.get("detail") or ""),
                        state=str(a["state"]),
                        seconds=(a.get("seconds")
                                 if isinstance(a.get("seconds"), (int, float)) else None),
                        key=f"restored:{len(self._actions)}",
                        meta=str(a.get("meta") or ""),
                        at_ms=int(a.get("at_ms") or 0)))
                    n += 1
            if not self._thoughts:
                # STORED CHRONOLOGICALLY, PUBLISHED NEWEST-FIRST. `state()`
                # reverses on the way out, so what comes back has to be
                # reversed on the way in or the card comes up backwards.
                for t in list(reversed(state.get("thoughts") or []))[-MAX_THOUGHTS_KEPT:]:
                    if isinstance(t, str) and t.strip():
                        self._thoughts.append(t)
                        n += 1
        return n

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

    # What each capability is called while it is happening, in the words a
    # person would use. The owner asked for the surface to say what VESPER is
    # DOING -- "running command X", "reading", "opening" -- the way a coding
    # agent narrates its tools, rather than only naming the provider that
    # answered afterwards.
    ACT_VERBS = {
        "shell.run": ("running", "ran"),
        "ui.open": ("opening", "opened"),
        "fs.read": ("reading", "read"),
        "fs.write": ("writing", "wrote"),
        "fs.edit": ("editing", "edited"),
        "agent.ask": ("asking", "asked"),
        "agent.run": ("delegating", "delegated"),
    }

    @staticmethod
    def _act_detail(capability_id: str, args: dict) -> str:
        """The one thing worth showing about this action, and nothing else."""
        a = args or {}
        if capability_id == "shell.run":
            return str(a.get("cmd") or "")[:120]
        for k in ("path", "target", "agent", "question"):
            if a.get(k):
                return str(a[k])[:120]
        return capability_id

    def acted(self, capability_id: str, args: dict, *, state: str = "done",
              seconds: float | None = None, output: str = "",
              meta: str = "") -> None:
        """Record one capability step, finished, with what it produced.

        OUTPUT IS PART OF THE ACTION. "ran python3 hey.py" and "ran python3
        hey.py -> hey there" are different amounts of use to someone watching:
        the first says a thing happened, the second says what it did. Trimmed
        hard, because this is a status line and not a terminal.
        """
        live, past = self.ACT_VERBS.get(capability_id, ("doing", "did"))
        detail = self._act_detail(capability_id, args)
        out = " ".join(str(output or "").split())[:80]
        if out and state == "done":
            detail = f"{detail} -> {out}"
        key = f"act:{capability_id}:{detail[:40]}"
        self.open(key, live, detail, meta=(meta or capability_id))
        self.close(key, state=state, verb=past, detail=detail, seconds=seconds)

    # ----------------------------------------------------------- commands

    def command(self, argv: Any, *, cwd: str = "",
                exit_code: int | None = None, stdout: str = "",
                stderr: str = "", elapsed_ms: int | None = None) -> str | None:
        """Record one command exactly as it ran. Returns its id, or None.

        NOTHING IS INFERRED HERE. The state comes from the exit code, the
        output comes from the streams, and a command with no argv is refused
        rather than recorded as an empty one -- a row saying VESPER ran
        something and declining to say what is worse than no row.
        """
        if isinstance(argv, str):
            # A STRING IS ACCEPTED AND SPLIT ONCE, HERE, so callers that only
            # have the `cmd` field are not silently dropped. `shell_run` splits
            # the same way, so this reproduces its argv rather than inventing a
            # different one.
            try:
                argv = shlex.split(argv)
            except ValueError:
                return None
        argv = tuple(str(a) for a in (argv or ()))
        if not argv:
            return None
        out, cut_o = _clip(stdout)
        err, cut_e = _clip(stderr)
        with self._lock:
            self._seq += 1
            cmd = Command(
                id=f"cmd{self._seq}",
                argv=argv,
                cwd=str(cwd or ""),
                state=("ok" if exit_code in (0, None) else "failed"),
                exit_code=(int(exit_code) if isinstance(exit_code, int) else None),
                stdout=out, stderr=err,
                elapsed_ms=(int(elapsed_ms)
                            if isinstance(elapsed_ms, (int, float)) else None),
                truncated=(cut_o or cut_e))
            self._commands.append(cmd)
            del self._commands[:-COMMANDS_MAX]
            return cmd.id

    # ------------------------------------------------------- explanations

    def explain(self, turn_id: str, title: str, blocks: Any) -> str | None:
        """The long half of a reply, for the board. Never spoken.

        THE SPLIT IS MADE IN `core/longform.py` AND NOT HERE. This stores what
        it decided. Putting the rule in the store would mean the only way to
        find out what VESPER will say aloud is to write a record and read it
        back -- and the speech path does not go through this object at all.

        KEYED ON THE TURN, so the reply on the stage and the explanation on the
        board can find each other. `turn_id` is the utterance's HLC: an
        identity, not an ordering, so `INV-COORD-4` has nothing to say about it.

        SAME TURN REPLACES, DOES NOT STACK. A turn produces one explanation; a
        second arriving for the same id means the turn was re-run, and two
        entries would show the owner one answer twice.
        """
        rows = [b.to_dict() if hasattr(b, "to_dict") else dict(b)
                for b in (blocks or ())]
        rows = [b for b in rows if b.get("kind") in ("text", "code", "list")]
        if not rows:
            return None
        turn_id = str(turn_id or "")
        entry = {"id": f"exp:{turn_id}" if turn_id else f"exp{len(self._explanations)}",
                 "turn_id": turn_id,
                 "title": " ".join(str(title or "").split())[:70],
                 "blocks": rows}
        with self._lock:
            self._explanations = [e for e in self._explanations
                                  if e["id"] != entry["id"]]
            self._explanations.append(entry)
            del self._explanations[:-EXPLANATIONS_MAX]
        return entry["id"]

    def open(self, key: str, verb: str, detail: str, *, meta: str = "") -> None:
        with self._lock:
            for a in self._actions:
                if a.key == key and a.state == "live":
                    a.verb, a.detail = verb, detail
                    if meta:
                        a.meta = meta
                    return
            self._actions.append(Action(verb, detail, "live", None, key,
                                        meta, int(time.time() * 1000)))
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
            self.open(f"route:{task}", "routing", str(prof),
                      meta=f"difficulty {p.get('difficulty') or '?'}")
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
                self.open(key, "asking", pid, meta=cls)
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
                    "actions": [a.to_dict() for a in self._actions],
                    # CHRONOLOGICAL HERE, NEWEST-FIRST IN THE CARD. Same
                    # decision as the thoughts above and for the same reason:
                    # the record does not reorder itself for a view, and the
                    # renderer is the layer allowed to make that choice.
                    "commands": [c.to_dict() for c in self._commands],
                    "explanations": list(self._explanations)}
