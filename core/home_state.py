"""What the home shows, and what VESPER's face is doing, from real activity.

THE FACE WAS BUILT AND NEVER CONNECTED. `Behaviour.swift` carries fourteen
behaviours with distinct gaze, blink, breath and dispersal -- and the only
thing that has ever set one is `--demo`, cycling them on a timer so they could
be SEEN. Nothing in the running system chose a behaviour, so a face that can
express thinking, listening and talking has been resting through every call
VESPER has made.

That is the same defect shape this tree keeps finding: a capability that
exists, is correct, and has no seam to the thing it is about. `Provider.
profile_id` sat unread for months; the egress class was applied at
registration and never at the choke point. Built-and-unreached is the failure
mode of a system assembled in layers.

THE BRIDGE ALREADY EXISTED AND IS NOT NEW HERE. `~/Library/Application
Support/VESPER/home.json` is written by Python and read by the chrome. This
adds two keys to it rather than inventing a channel: a second mechanism between
the same two processes would be two things that must agree about the same
state, and `tools/ops/alarm_wake_linux.py` records what that costs.

BEHAVIOUR IS DERIVED FROM EVENTS, NEVER SET BY A CALLER. A method like
`set_thinking()` would put the face's honesty in the hands of whoever
remembered to call it, and the first forgotten call is a face that says it is
working while nothing is running. Subscribing means the face cannot lie about
activity it did not have -- and cannot fail to show activity it did.

THE FACE IS AN INSTRUMENT AND ITS READING IS ABOUT VESPER. `resting` while a
request is in flight is a false reading in exactly the way a stale metric is,
so the behaviour falls back to `resting` on a TIMEOUT rather than staying
wherever the last event left it. A face stuck on `thinking` after a crash is
worse than one at rest: it reports work that is not happening.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / "Library" / "Application Support" / "VESPER"
HOME_JSON = STATE_DIR / "home.json"

# The subset of Behaviour.swift's fourteen that real activity can justify.
# The others -- laughing, joking, angry, happy, aura -- are expressive states
# nothing currently measures, and picking one from a heuristic would be the
# face inventing a mood. They stay unused until something can honestly produce
# them.
# WRITTEN OUT ONE PER LINE AFTER A TRANSPOSITION. The tuple form
# `RESTING, THINKING, WORKING = "resting", "working", "thinking"` bound THINKING
# to "working" and WORKING to "thinking", and it reads as correct at a glance --
# three names, three strings, all present. The face then showed the wrong state
# for every event and nothing could have caught it but running it, because both
# values are valid behaviours and neither side raised.
RESTING = "resting"
THINKING = "thinking"
WORKING = "working"
TALKING = "talking"
LISTENING = "listening"
WONDERING = "wondering"

DERIVABLE = (RESTING, THINKING, WORKING, TALKING, LISTENING, WONDERING)

# How long a behaviour survives without a further event before falling back to
# rest. Longer than a slow provider call (measured: the slowest supplier
# answered in 70 s) so an honest long think is not cut short, short enough that
# a crashed run does not leave the face working forever.
STALE_AFTER_S = 90.0


class HomeState:
    """Derives the face's behaviour and the transcript from the event bus."""

    def __init__(self, *, path: Path | None = None, bus: Any = None,
                 clock: Any = None) -> None:
        self._path = Path(path) if path else HOME_JSON
        self._bus = bus
        self._clock = clock
        self._lock = threading.RLock()
        self._behaviour = RESTING
        self._since = time.time()
        self._reason = "no activity yet"
        self._workbench: dict = {}
        self._transcript: list = []
        self._rows: list = []
        self._writes = 0

    # ------------------------------------------------------------ behaviour

    def _set(self, behaviour: str, reason: str) -> None:
        if behaviour not in DERIVABLE:
            # REFUSED, NOT COERCED. A behaviour outside the derivable set means
            # a caller is inventing an expression, and silently substituting
            # `resting` would hide that while looking calm.
            raise ValueError(
                f"{behaviour!r} is not derivable from activity; expected "
                f"{DERIVABLE}. The expressive states nothing measures stay "
                "unused rather than being guessed at.")
        with self._lock:
            if self._behaviour != behaviour:
                self._behaviour = behaviour
                self._since = time.time()
                self._reason = reason
                self._publish()
        self.write()

    def behaviour(self) -> str:
        """The current behaviour, with staleness applied.

        READ THROUGH THE TIMEOUT RATHER THAN STORED THROUGH IT. A background
        timer that reset the field would be a second writer racing the event
        handlers; deriving it on read means there is one source of truth and no
        ordering to get wrong.
        """
        with self._lock:
            if (self._behaviour != RESTING
                    and time.time() - self._since > STALE_AFTER_S):
                return RESTING
            return self._behaviour

    def state(self) -> dict:
        with self._lock:
            stale = (self._behaviour != RESTING
                     and time.time() - self._since > STALE_AFTER_S)
            return {"behaviour": self.behaviour(),
                    "since_s": round(time.time() - self._since, 1),
                    "reason": ("fell back to rest: no event for "
                               f"{STALE_AFTER_S:.0f}s, and a face reporting "
                               "work that is not happening is worse than one "
                               "at rest") if stale else self._reason}

    # ---------------------------------------------------------------- wiring

    def attach(self, bus: Any) -> None:
        """Derive the face from what VESPER is actually doing."""

        def on_dispatch(ev: Any) -> None:
            self._set(THINKING, "an utterance was accepted and dispatched")

        def on_partial(ev: Any) -> None:
            # A recogniser mid-sentence is the one moment `listening` is a
            # true reading rather than a pose.
            self._set(LISTENING, "a spoken utterance is still being revised")

        def on_attempt(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            if p.get("outcome") == "ok":
                self._set(THINKING, "a provider answered; composing")
            elif p.get("classification"):
                # NOT `angry`, and not `working`. A failover is VESPER trying
                # something else, and `wondering` is the honest reading of that
                # -- the alternative would be a face that performs frustration
                # it does not have.
                self._set(WONDERING,
                          f"attempt failed ({p.get('classification')}); "
                          "trying another provider")

        def on_narration(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            if p.get("spoken"):
                self._set(TALKING, "speaking a status line aloud")

        def on_route(ev: Any) -> None:
            self._set(WORKING, "a route was selected; the call is in flight")

        for event, handler, name in [
            ("intake.dispatched", on_dispatch, "face-dispatch"),
            ("intake.partial", on_partial, "face-partial"),
            ("gateway.attempt", on_attempt, "face-attempt"),
            ("narration.emitted", on_narration, "face-narration"),
            ("route.selected", on_route, "face-route"),
        ]:
            bus.subscribe(event, handler, name=name,
                          idempotency_key=lambda e: e.event_id)

    def set_transcript(self, entries: list) -> None:
        """The conversation, and -- derived from it -- whether VESPER is talking.

        DERIVED HERE RATHER THAN SET BY THE CALLER, which is INV-HOME-7's whole
        argument: a `set_talking()` would put the face's honesty in the hands of
        whoever remembered to call it, and the first forgotten call is a face
        that answered in silence.

        WHY THE TRANSCRIPT AND NOT AN EVENT. `TALKING` was reachable only from
        `narration.spoken`, so it fired when VESPER SAID a status line aloud and
        never when it answered the owner -- the one moment it is unambiguously
        talking. Every reply landed on the stage with the face still `thinking`,
        which is a false reading in exactly the way a stale metric is.

        A NEW VESPER LINE, not merely a last line that is VESPER's: this is
        called on every pump pass, and re-deriving `talking` from an unchanged
        transcript would hold the face open indefinitely after one reply.
        """
        with self._lock:
            previous = self._transcript
            self._transcript = list(entries)
            newest = entries[-1] if entries else None
            is_new_reply = (
                newest is not None
                and newest.get("who") == "vesper"
                and len(entries) > len(previous))
        if is_new_reply:
            self._set(TALKING, "a reply reached the stage")
        self.write()

    def set_workbench(self, state: dict) -> None:
        """VESPER's thoughts and actions, for the top-left card.

        WRITTEN THROUGH HERE RATHER THAN BY `Workbench` ITSELF, because this
        object owns the merge into `home.json` and a second writer is how the
        face state and the metrics rows came to delete each other. `Workbench`
        derives; this publishes. One file, one writer per key, one merge.
        """
        with self._lock:
            self._workbench = dict(state or {})
        self.write()

    def set_rows(self, rows: list) -> None:
        """The metrics card's rows. Owned by whoever measured them."""
        with self._lock:
            self._rows = list(rows)
        self.write()

    # ------------------------------------------------------------- the file

    def write(self) -> Path:
        """Publish the state the chrome reads. Atomic, and it MERGES.

        `tools/home_snapshot.py` owns `rows` and this owns `behaviour` and
        `transcript`. A whole-file rewrite from either would silently delete
        the other's work, and the loser would be whichever ran last -- a race
        with no error, which is the kind that survives review.
        """
        with self._lock:
            existing: dict = {}
            if self._path.exists():
                try:
                    existing = json.loads(self._path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = {}
            existing["face"] = self.state()
            existing["transcript"] = self._transcript
            # A THIRD KEY, AND STILL ONE MERGE. Written unconditionally so the
            # card empties when the workbench does -- a board that keeps its
            # last contents when the source goes quiet reports work that is not
            # happening, which is the same defect as a face stuck on `thinking`.
            existing["workbench"] = self._workbench
            if self._rows:
                existing["rows"] = self._rows
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # A UNIQUE TEMP PER WRITE, NOT A FIXED NAME.
            #
            # `with_suffix(".tmp")` gives every writer the SAME path. Five bus
            # handlers call this, and two overlapping writes race: the first
            # creates home.tmp, the second overwrites and renames it, and the
            # first's rename then fails with FileNotFoundError -- which
            # propagated out of the pump loop and KILLED THE RUNTIME. The
            # symptom was not a corrupt file; it was VESPER going silent, with
            # the crash only visible in a log nobody was watching.
            #
            # The pid and a counter make collision impossible between processes
            # and within one, and the rename stays atomic per POSIX.
            self._writes += 1
            tmp = self._path.with_name(
                f"{self._path.stem}.{os.getpid()}.{self._writes}.tmp")
            try:
                tmp.write_text(json.dumps(existing, indent=1), encoding="utf-8")
                tmp.replace(self._path)
            finally:
                # WHATEVER HAPPENS, DO NOT LEAVE THE TEMP BEHIND. A failed write
                # that litters the state directory turns one bad moment into a
                # directory nobody can read at a glance.
                tmp.unlink(missing_ok=True)
            return self._path

    def _publish(self) -> None:
        if self._bus is not None:
            self._bus.publish("home.behaviour_changed", subject=self._behaviour,
                              payload=self.state(), component="home_state")
