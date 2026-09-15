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
# HOW MANY FLAGS THE BAR HOLDS.
#
# Owner, 2026-09-11: "make sure it can show all live flags there." It was capped
# at 8, which silently dropped the oldest -- and a surface whose job is to keep
# calling for action, quietly forgetting the earliest call, is worse than one that
# scrolls. The cap is now a bound on unbounded growth rather than a display
# choice: at 64 the bar is a wall of text and something is wrong with the machine,
# not with the bar.
HISTORY_BAR_CAP = 64

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
        # HAS THIS INSTANCE EVER SUPPLIED ONE? See `write`.
        self._workbench_set = False
        # LOADED FROM THE FILE, NOT STARTED EMPTY, AND THE OWNER FOUND THIS.
        # Every flag lived in memory only, so a restart -- and `build.sh`
        # restarts the runtime on every build -- wiped the bar clean whether or
        # not the problems were over. A flag whose condition nothing re-checks
        # on a timer simply vanished: raised at 19:09, gone at 19:30, never
        # re-raised, with the grant it was complaining about still missing.
        # Owner, 2026-09-11: "the rebuild or rerun should not stop it or lose
        # them if they're still live".
        #
        # AND A LOADED FLAG IS NOT TRUSTED TO STILL BE TRUE. It is carried
        # forward UNVERIFIED and each one names how to re-prove it; the runtime
        # re-checks them at startup and drops the ones that are resolved. The
        # two failure directions are not symmetric, which is why loading alone
        # is not the whole fix: forgetting a live problem loses the only notice
        # the owner gets, while keeping a dead one wastes a glance at the bar.
        self._flags: list = self._load_flags()
        self._settings: list = []
        self._projects: list = []
        self._dashboard: dict = {}
        self._research_room: dict = {}
        self._research: list = []
        # A FLAG ON THE BAR WITH NO HISTORY ROW IS A HOLE IN "THE FULL HISTORY".
        #
        # Measured 2026-09-11: three flags on the bar, ONE row in the history --
        # because the two carried ones were raised by a process that predates the
        # history file, so nothing ever appended them. The owner asked to click the
        # bar and see the full history; a bar row the panel cannot account for is
        # the surface disagreeing with itself.
        #
        # BACKFILLED WITHOUT INVENTING A TIME. The row is written with no `at_s`,
        # so the panel shows `--:--` rather than a plausible clock reading -- when
        # it was first raised is genuinely unknown, and guessing it would be the
        # same false-measurement defect as a zero from a missing table.
        self._backfill_history()
        self._mode = ""
        self._stage = ""
        self._ambience = ""
        self._changes: dict = {}
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

    def mode_now(self) -> dict:
        """The mode vesper is actually in, for anyone about to say so out loud.

        THE OWNER ASKED "what mode are you on?" AND WAS TOLD `idle -- present and
        awaiting commands`. That sentence is in no file in this repository: the
        answerer invented it. It had been given the list of modes that EXIST --
        added 2026-09-10 so it could stop inventing mode names -- and nothing
        that says which one is current, so it picked a valid name and wrote a
        plausible description under it. A list of legal answers with no actual
        answer is an invitation to guess, and the guess arrives in the owner's
        own words with no marking that it was one.

        READ FROM THE FILE FIRST, NOT FROM MEMORY, and the difference is not
        academic. `_mode` is empty at construction, so after a runtime restart
        memory says "no mode" while `home.json` still holds the last one -- and
        the SWIFT side paints from that file, so the picture on screen is the
        file's answer. Memory would have vesper deny the mode the owner is
        looking at. Memory is the fallback for an unreadable file, not the
        source.
        """
        row = {}
        try:
            import json as _json

            row = _json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            row = {}
        with self._lock:
            return {"mode": str(row.get("mode") or self._mode or ""),
                    "stage": str(row.get("stage") or self._stage or ""),
                    "ambience": str(row.get("ambience") or self._ambience or "")}

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
            self._workbench_set = True
        self.write()

    def set_changes(self, state: dict) -> None:
        """The changed-files board, for the third pane.

        A FOURTH KEY AND STILL ONE MERGE, for the same reason `set_workbench`
        is written the way it is: this object owns the merge into `home.json`
        and a second writer is how the face state and the metrics rows came to
        delete each other.
        """
        with self._lock:
            self._changes = dict(state or {})
        self.write()

    # THE HISTORY, WHICH IS THE NEW SUBSYSTEM AND NOT THE WIDTH.
    #
    # Owner, 2026-09-11: "when i click the bar, i can see the full history with
    # timestamps, and whether it's fixed or not, and to ask vesper to fix it if
    # it's a real issue that needs fixing."
    #
    # §20 gave flags a life beyond one process. It did not give them a PAST: a
    # flag that was raised and cleared left nothing behind, so "whether it's
    # fixed" had no record to answer from.
    #
    # ORDERED BY SEQUENCE, DISPLAYED BY CLOCK. `INV-COORD-4` refuses a sort keyed
    # on wall time and `CI-005` enforces it. The row carries `at_s` because the
    # owner wants to read a time, and that is PRESENTATION -- the order is the
    # order rows were appended, which is the only thing that orders them.
    HISTORY_CAP = 200

    def _history_path(self) -> Path:
        return self._path.with_name("flag_history.json")

    def _backfill_history(self) -> None:
        """Give every carried flag a history row, if it has none."""
        try:
            rows = self._load_history()
            have = {r.get("id") for r in rows
                    if not r.get("resolved_at_s")}
            added = 0
            for f in self._flags:
                fid = f.get("id")
                if fid and fid not in have:
                    rows.append({"id": fid, "event": "raised",
                                 "text": str(f.get("text") or ""),
                                 "seen": 1, "carried_in": True})
                    added += 1
            if added:
                self._write_history(rows)
        except Exception:                                 # noqa: BLE001
            pass

    def _load_history(self) -> list:
        try:
            rows = json.loads(self._history_path().read_text(encoding="utf-8"))
            return [r for r in rows if isinstance(r, dict) and r.get("id")]
        except Exception:                                 # noqa: BLE001
            return []

    def _append_history(self, row: dict) -> None:
        """Add one event, collapsing a repeat of the same open condition.

        WHY COLLAPSED: a condition that fails every ten seconds would otherwise
        fill the history it is trying to be visible in -- the same argument the
        bar's own dedup makes, one layer down. A RAISE that repeats an id already
        open updates its text and its count rather than appending; a RESOLVE
        always appends, because when something stopped being wrong is the fact
        the owner is looking for.
        """
        rows = self._load_history()
        if row.get("event") == "raised":
            for r in reversed(rows):
                if r.get("id") == row.get("id"):
                    if r.get("event") == "raised" and not r.get("resolved_at_s"):
                        r["text"] = row.get("text") or r.get("text")
                        r["seen"] = int(r.get("seen") or 1) + 1
                        r["last_at_s"] = row.get("at_s")
                        self._write_history(rows)
                        return
                    break
        rows.append(row)
        self._write_history(rows)

    def _write_history(self, rows: list) -> None:
        try:
            self._history_path().parent.mkdir(parents=True, exist_ok=True)
            self._history_path().write_text(
                json.dumps(rows[-self.HISTORY_CAP:], indent=1), encoding="utf-8")
        except Exception:                                 # noqa: BLE001
            pass

    def refresh_settings(self) -> int:
        """Read the settings surface's values and put them on the surface.

        CALLED RARELY AND DELIBERATELY SO. These are contracts on disk, not live
        counters: they change when somebody edits a reviewed file, which is not
        something that happens between two ticks of a poll. Re-reading ten TOML
        files every second to watch them not change is the kind of work a machine
        the owner is trying to keep alive for ten years should not be doing.
        """
        n = 0
        try:
            from core import settings_surface as S
            with self._lock:
                self._settings = S.rows()
            # THE MAIN MENU'S CARDS, on the same cadence and from the same
            # producer pass: each destination's readings, borrowed settings rows
            # and actions (`core/menu_cards.py`). A card that fails to build
            # leaves the previous one standing rather than emptying the menu.
            try:
                from core import menu_cards as MC
                with self._lock:
                    self._menu_cards = MC.cards(self)
                n += len(self._menu_cards)
            except Exception:                             # noqa: BLE001
                pass
            # THE PROJECTS AND RESEARCH BOARDS (`core/boards.py`): the windows and
            # cards the owner chose, each with its live status and its acts, and
            # what the picker may add. Same cadence, same pass.
            try:
                from core import boards as BD
                with self._lock:
                    self._boards = BD.boards()
                n += len(self._boards)
            except Exception:                             # noqa: BLE001
                pass
            n += len(self._settings)
        except Exception:                                 # noqa: BLE001
            pass
        # THE RAIL'S OWN TWO DESTINATIONS (§11.7), read from the same files that
        # are the authority for them: the build order for `projects`, the spike
        # index for `research`. Read here rather than in the page, because the
        # page must never parse a repository document -- what a surface shows has
        # to come through a producer that can say UNAVAILABLE with a reason.
        try:
            from core import rail_surfaces as RS
            with self._lock:
                self._projects = RS.project_rows()
                self._research = RS.research_rows()
            n += len(self._projects) + len(self._research)
        except Exception:                                 # noqa: BLE001
            pass
        # THE DASHBOARD (§28). Its phases come from a contract and its panels
        # read the PROJECT -- which is told, never derived, because a runtime
        # running from the bundle resolves its own location to the shipped copy
        # and answers questions about that instead. `core/places.py` is the one
        # thing that knows which directory the owner means.
        try:
            from core import project_dashboard as PD
            from core import places as PL
            root = ""
            for row in PL.places():
                if row.get("name") == "the project" and row.get("path"):
                    root = row["path"]
                    break
            with self._lock:
                self._dashboard = {
                    "phases": PD.phases(),
                    "modes": PD.modes(),
                    "panels": PD.panels(root or None),
                    "project_root": root,
                }
            n += len(self._dashboard.get("panels") or [])
            # §29's room reaches the surface through the same producer. Without
            # this the module is built and called by nothing, which
            # `gated-subsystems-are-reachable` refuses -- and it refused this one
            # the same day it was written.
            from core import research_room as RR
            with self._lock:
                self._research_room = {
                    "sessions": RR.sessions(),
                    "default": RR.default_layout(),
                    "control_card": RR.control_card(),
                }
            n += len(self._research_room.get("control_card") or [])
        except Exception:                                 # noqa: BLE001
            pass
        self.write()
        return n

    def flag_history(self) -> list:
        """Every flag event, newest last, with what became of it.

        THREE STATES AND NOT A BOOLEAN. `open` is live. `resolved` stopped being
        true and the row says when. `carried` was inherited across a restart and
        has NOT been re-proved -- neither fixed nor confirmed broken. Collapsing
        that third one into either answer would assert something no measurement
        supports, which is `INV-HW-2`'s rule applied to a surface.
        """
        with self._lock:
            live = {f.get("id"): f for f in self._flags}
        out = []
        for row in self._load_history():
            fid = row.get("id")
            if row.get("resolved_at_s"):
                state = "resolved"
            elif fid in live:
                state = "carried" if live[fid].get("carried") else "open"
            else:
                # RAISED, NOT RESOLVED, AND NOT ON THE BAR. The process that
                # raised it is gone and nothing re-raised it, so whether it is
                # over is unknown -- said rather than guessed either way.
                state = "unproven"
            out.append({**row, "state": state})
        return out

    def _load_flags(self) -> list:
        """The previous process's flags, shape-checked rather than trusted.

        A file this cannot parse yields no flags, which is the one case where
        losing them is correct: an unreadable bar is not evidence of anything.
        """
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:                                 # noqa: BLE001
            return []
        out = []
        for f in (raw.get("flags") or []):
            if not isinstance(f, dict):
                continue
            fid, text = str(f.get("id") or ""), str(f.get("text") or "")
            if not fid or not text:
                continue
            row = {"id": fid, "text": text[:400], "carried": True}
            rc = f.get("recheck")
            if isinstance(rc, dict) and rc.get("capability_id"):
                row["recheck"] = {"capability_id": str(rc["capability_id"]),
                                 "args": dict(rc.get("args") or {})}
            out.append(row)
        return out[-HISTORY_BAR_CAP:]

    def open_flags(self) -> list:
        """Everything currently on the bar, for VESPER to read on its next turn.

        THE OWNER, 2026-09-13: *"i want it to put everything like that in the
        flag bar, and vesper should look at the flag bar right on the next
        working request."* Until this existed, nothing in a turn ever read the
        bar -- `carried_flags` was called once at startup and never again, so
        the surface whose job is to carry what went wrong was written to and
        never consulted by the thing that could act on it.

        NEWEST FIRST, because a turn reading this spends a small budget on it
        and the newest flag is the one least likely to have been seen already.
        """
        with self._lock:
            return [dict(f) for f in reversed(self._flags)]

    def carried_flags(self) -> list:
        """Flags inherited from the last process and not yet re-proved."""
        with self._lock:
            return [dict(f) for f in self._flags if f.get("carried")]

    def mark_verified(self, flag_id: str) -> None:
        """This flag has been re-proved against the world; it is not a leftover."""
        with self._lock:
            for f in self._flags:
                if f.get("id") == flag_id:
                    f.pop("carried", None)
        self.write()

    def raise_flag(self, flag_id: str, text: str,
                   recheck: dict | None = None) -> None:
        """Record a flag for the bar above the main menu.

        NEWEST LAST, DEDUPED BY ID, AND BOUNDED. The same flag raised twice --
        a rebuild that fails on every attempt, say -- is one condition, not a
        row per attempt, so it replaces its earlier self and keeps its place at
        the end. The cap is what stops a repeating failure from filling the bar
        it is trying to be visible in.
        """
        text = str(text or "").strip()
        if not text:
            return                    # a flag with no words reveals nothing
        with self._lock:
            self._flags = [f for f in self._flags if f.get("id") != flag_id]
            row: dict = {"id": str(flag_id), "text": text[:400]}
            # HOW TO PROVE THIS IS OVER, carried with the flag itself. Without
            # it a flag that survives a restart has no way to be retired except
            # by whatever happened to raise it running again -- so the owner
            # grants the permission, the condition is gone, and the bar keeps
            # saying it is not.
            if isinstance(recheck, dict) and recheck.get("capability_id"):
                row["recheck"] = {
                    "capability_id": str(recheck["capability_id"]),
                    "args": dict(recheck.get("args") or {})}
            self._flags.append(row)
            del self._flags[:-HISTORY_BAR_CAP]
        self._append_history({"id": str(flag_id), "event": "raised",
                              "text": text[:400], "at_s": int(time.time()),
                              "seen": 1})
        self.write()

    def clear_flag(self, flag_id: str) -> None:
        """Drop one flag, for when the condition it names is resolved."""
        with self._lock:
            before = len(self._flags)
            self._flags = [f for f in self._flags if f.get("id") != flag_id]
            changed = len(self._flags) != before
        if changed:
            # STAMPED ON THE ROW IT RESOLVES, not appended as a second event,
            # because the owner's question is "is this fixed" about ONE thing --
            # two rows for one condition is the shape the bar's dedup already
            # refuses.
            rows = self._load_history()
            for row in reversed(rows):
                if row.get("id") == flag_id and not row.get("resolved_at_s"):
                    row["resolved_at_s"] = int(time.time())
                    break
            self._write_history(rows)
            self.write()

    def set_mode(self, mode: str, stage: str, ambience: str) -> None:
        """The mode the owner chose, for the surface and for the running home.

        WRITTEN AS THREE FIELDS, not one. `mode` is the name they used,
        `ambience` is what the home paints, and `stage` is what the work is --
        and they are separate because HOME-ARCHITECTURE §6 insists the two axes
        stay independent underneath. Collapsing them into one string here would
        be exactly the welding a pairing is meant not to do.
        """
        with self._lock:
            self._mode = str(mode or "")
            self._stage = str(stage or "")
            self._ambience = str(ambience or "")
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
            # A THIRD KEY, AND STILL ONE MERGE. Written whenever this instance
            # has SUPPLIED one, so the card still empties when the workbench
            # does -- a board that keeps its last contents when the source goes
            # quiet reports work that is not happening, which is the same defect
            # as a face stuck on `thinking`.
            #
            # BUT NOT WHEN THIS INSTANCE NEVER HAD ONE, and that distinction was
            # missing and cost the owner their board twice. This file is shared
            # state: ANY process that builds a HomeState and calls write() --
            # including a read-only diagnostic asking what the dashboard holds --
            # had an empty `_workbench`, and an unconditional write published
            # that emptiness over the running runtime's live board. The owner
            # watched a card disappear and reported it, and the cause was a
            # tool looking at it. Measured 2026-09-13.
            #
            # `set_workbench` is what the pump calls every pass, so the runtime
            # still empties the card the moment its own board is empty. A
            # process that never set one now leaves the field alone instead of
            # asserting that nothing is happening.
            if self._workbench_set:
                existing["workbench"] = self._workbench
            # Written unconditionally, like the workbench above: a board
            # that keeps its last contents when the source goes quiet
            # reports work that is not happening.
            existing["changes"] = self._changes
            if self._rows:
                existing["rows"] = self._rows
            # WRITTEN UNCONDITIONALLY, like the workbench and changes above. A
            # bar that keeps its last flags after they are cleared reports a
            # problem that is over, which is the same defect as a face stuck on
            # `thinking` -- and worse here, because a flag is a call to act.
            existing["flags"] = self._flags
            # THE HISTORY RIDES THE SAME FILE, because the surface polls one file
            # and a second one would be a second thing to keep in step. Bounded
            # to what a panel can show: the record on disk keeps more.
            existing["flag_history"] = self.flag_history()[-60:]
            # WRITTEN ONLY ONCE IT HAS BEEN READ, so a tick before the first
            # refresh does not overwrite yesterday's values with an empty list --
            # which would make the surface read UNAVAILABLE for a reason that is
            # not true of any setting.
            if self._settings:
                existing["settings"] = self._settings
            if getattr(self, "_menu_cards", None):
                existing["menu_cards"] = self._menu_cards
            if getattr(self, "_boards", None):
                existing["boards"] = self._boards
            if self._projects:
                existing["projects"] = self._projects
            if self._dashboard:
                existing["project_dashboard"] = self._dashboard
            if self._research_room:
                existing["research_room"] = self._research_room
            if self._research:
                existing["research"] = self._research
            # ONLY WHEN A MODE HAS BEEN CHOSEN. Writing an empty ambience every
            # tick would tell the home to paint nothing, which is not the same
            # as leaving it alone.
            if self._ambience:
                existing["mode"] = self._mode
                existing["stage"] = self._stage
                existing["ambience"] = self._ambience
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
            # AND THE THREAD, which the counter only covers while every writer
            # shares this instance's lock. Two HomeState objects in one process
            # -- a test beside the runtime, a second pump -- each count from
            # zero, and their temp names then collide exactly as the fixed name
            # did. Written the same way as every other atomic write in the
            # corpus so the rule is one rule (`an-atomic-write-never-shares-its-
            # temp-name`).
            tmp = self._path.with_name(
                f"{self._path.stem}.{os.getpid()}.{threading.get_ident()}"
                f".{self._writes}.tmp")
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
