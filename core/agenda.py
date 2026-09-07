"""What VESPER should do next, and when — the loop's other half.

THE LOOP THE OWNER DESCRIBED, AND THE HALF THAT WAS MISSING. VESPER takes a
request, does it, answers, and then asks what to do next "depending on
calendar, notes, plans, and their importance and time" -- stopping when nothing
is required. The asking-what-next half exists: `core/autonomy.py` ticks,
evaluates triggers and goes quiet. What it evaluated was four internal
housekeeping triggers -- token expiry, memory drift, contradictions, a stale
knowledge map. Nothing connected it to the owner's day, and `core/tasks.py`,
which has carried a `priority_class` since it was written, was referenced by
the runtime at NOT ONE LINE.

"NOTHING IS DUE" AND "I COULD NOT LOOK" ARE DIFFERENT ANSWERS, and keeping them
apart is most of this file. A calendar VESPER cannot read must never present as
a clear day: that is `INV-HW-2` -- UNKNOWN means UNAVAILABLE, and the honest
report is "I do not know what is on your calendar", not silence. Every source
therefore reports its own reachability, `Agenda.unavailable` names the ones
that failed, and the runtime says so rather than acting as though the day were
empty.

RANKED ON A SCORE, NOT SORTED ON A CLOCK. `INV-COORD-4` says wall clock never
orders, and `CI-005` refuses a sort keyed on a timestamp -- correctly, because
that rule exists to stop two nodes disagreeing about which record came first.
A DEADLINE is a different object from a record time: asking "has this become
due" is the permitted comparison, the same shape as "has 09:00 arrived". So
urgency here is a derived 0..1 quantity, importance is a declared weight, and
what orders the list is their combination. Two items due at the same minute
are separated by importance rather than by whichever timestamp sorted lower.

THE SOURCES ARE DELIBERATELY UNEVEN. `plan` is a file VESPER can also WRITE,
so "remind me to call the bank Tuesday" becomes an item it schedules itself
rather than a sentence it forgets. `calendar` and `reminders` are read-only and
arrive through the app's EventKit bridge, because the raw stores are behind
Full Disk Access and asking the owner for the whole disk to read their agenda
is the wrong trade.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
AGENDA_DIR = STATE / "agenda"
PLAN_PATH = AGENDA_DIR / "plan.json"
# Written by the app's EventKit bridge. A separate file from the plan because
# one is VESPER's and one is the owner's, and a bug in the bridge must not be
# able to eat what VESPER wrote down.
EVENTKIT_PATH = AGENDA_DIR / "eventkit.json"
# Written by the app's Notes bridge, which reaches Notes over Apple Events --
# a different permission class from EventKit and a different trust class for
# what comes back, which is why it is a separate file and a separate reader.
NOTES_PATH = AGENDA_DIR / "notes.json"

# How old the EventKit dump may be before it stops counting as knowledge. The
# bridge refreshes on a timer; past this the answer is "I do not know", never
# "nothing is scheduled".
EVENTKIT_FRESH_S = 15 * 60

# Declared weights. Not measured, and not pretending to be: these are the
# owner's ranking of their own priorities, which is the one thing in this
# system that IS a declaration.
IMPORTANCE = {"low": 0.25, "normal": 0.5, "high": 1.0}
DEFAULT_IMPORTANCE = "normal"

# How far ahead an item starts to count as "now". Below this it is not the
# loop's business yet, which is what makes the loop go quiet.
LEAD_S = 15 * 60

# Urgency saturates a day out. Something due next week and something due next
# month are equally not-now, and letting the difference between them move the
# ranking would let a distant deadline outrank a near one on importance alone.
HORIZON_S = 24 * 60 * 60

SOURCES = ("plan", "calendar", "reminders", "notes")


@dataclass
class Item:
    item_id: str
    title: str
    source: str
    due_ms: int | None = None
    importance: str = DEFAULT_IMPORTANCE
    done: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "title": self.title,
                "source": self.source, "due_ms": self.due_ms,
                "importance": self.importance, "done": self.done,
                "note": self.note}

    def urgency(self, now_ms: int) -> float:
        """0 when far off, 1 once due. An item with no due time is not urgent.

        NO DUE TIME IS NOT "DUE NOW". A note with no deadline should sit
        patiently below anything with one, however important it is, or every
        undated idea would outrank a meeting that starts in ten minutes.
        """
        if self.due_ms is None:
            return 0.0
        remaining_s = (self.due_ms - now_ms) / 1000.0
        if remaining_s <= 0:
            return 1.0
        if remaining_s >= HORIZON_S:
            return 0.0
        return 1.0 - (remaining_s / HORIZON_S)

    def score(self, now_ms: int) -> float:
        """Importance and time, together. The owner's two words, in one number.

        MULTIPLIED RATHER THAN ADDED, and the difference is visible at the
        edges: added, a `high` item with no deadline outranks a `normal` one
        that is due right now. Multiplied, importance scales urgency -- it
        decides between things whose time has come, and cannot manufacture a
        time that has not.
        """
        w = IMPORTANCE.get(self.importance, IMPORTANCE[DEFAULT_IMPORTANCE])
        return w * self.urgency(now_ms)

    def due(self, now_ms: int) -> bool:
        """Has this become the loop's business yet?"""
        if self.done or self.due_ms is None:
            return False
        return (self.due_ms - now_ms) / 1000.0 <= LEAD_S


@dataclass
class Agenda:
    items: list = field(default_factory=list)
    # Sources that could not be read. NOT the same as sources with nothing in
    # them, and the runtime is expected to say which it is.
    unavailable: dict = field(default_factory=dict)

    def due_now(self, now_ms: int) -> list:
        """Everything whose time has come, most pressing first.

        Ordered by `score`, then by importance weight, then by title -- a total
        order with no clock in it, so two runs over the same agenda produce the
        same list.
        """
        ready = [i for i in self.items if i.due(now_ms)]
        return sorted(
            ready,
            key=lambda i: (-i.score(now_ms),
                           -IMPORTANCE.get(i.importance,
                                           IMPORTANCE[DEFAULT_IMPORTANCE]),
                           i.title),
        )

    def quiet(self, now_ms: int) -> bool:
        """Is there genuinely nothing to do?

        FALSE WHILE ANY SOURCE IS UNREADABLE. "I have nothing for you" and "I
        could not see your calendar" must not produce the same silence.
        """
        return not self.unavailable and not self.due_now(now_ms)

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self.items],
                "unavailable": dict(self.unavailable)}


def _item_from(d: dict, source: str) -> Item | None:
    title = str(d.get("title") or "").strip()
    if not title:
        return None
    due = d.get("due_ms")
    try:
        due = int(due) if due is not None else None
    except (TypeError, ValueError):
        due = None
    imp = str(d.get("importance") or DEFAULT_IMPORTANCE).strip().lower()
    return Item(item_id=str(d.get("item_id") or f"{source}:{title}"),
                title=title, source=source, due_ms=due,
                importance=imp if imp in IMPORTANCE else DEFAULT_IMPORTANCE,
                done=bool(d.get("done")), note=str(d.get("note") or ""))


def read_plan(path: pathlib.Path | None = None) -> tuple:
    """VESPER's own list. Returns (items, unavailable_reason_or_None).

    A MISSING FILE IS AN EMPTY PLAN, NOT AN OUTAGE. Nobody has written anything
    down yet, which is a fact rather than a failure -- unlike a calendar, where
    "no file" means the bridge did not run.
    """
    p = path or PLAN_PATH
    if not p.exists():
        return [], None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                            # noqa: BLE001
        return [], f"the plan file could not be read ({type(exc).__name__})"
    out = [it for it in (_item_from(x, "plan")
                         for x in d.get("items", []) if isinstance(x, dict))
           if it is not None]
    return out, None


def write_plan(items: list, path: pathlib.Path | None = None) -> None:
    """Replace the plan. Written whole and renamed, so a crash mid-write leaves
    the previous list rather than half of the new one."""
    p = path or PLAN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"items": [i.to_dict() for i in items]}, indent=1), encoding="utf-8")
    tmp.replace(p)


def add_to_plan(title: str, *, due_ms: int | None = None,
                importance: str = DEFAULT_IMPORTANCE, note: str = "",
                path: pathlib.Path | None = None) -> Item:
    """One more thing to do. This is the write path that makes `plan` the
    source VESPER can actually keep, rather than one more thing to read."""
    items, _ = read_plan(path)
    item = Item(item_id=f"plan:{int(time.time() * 1000)}", title=title.strip(),
                source="plan", due_ms=due_ms,
                importance=(importance if importance in IMPORTANCE
                            else DEFAULT_IMPORTANCE),
                note=note)
    items.append(item)
    write_plan(items, path)
    return item


def read_notes(path: pathlib.Path | None = None,
               now_s: float | None = None) -> tuple:
    """Note TITLES, as the app's bridge last saw them.

    SEPARATE FROM `read_eventkit` BECAUSE THE SOURCE IS SEPARATE. Calendar and
    reminders come from EventKit under one grant and fail together; Notes comes
    over Apple Events under its own Automation grant and fails on its own. One
    reader over both would report a denied Notes grant as a calendar outage.

    TITLES ONLY -- see `NotesBridge.swift` for why. A note's BODY may hold
    anything the owner ever pasted, and this is the path VESPER uses to decide
    what to do next. Every row carries `trust` so nothing downstream can forget
    that even the title is retrieved rather than authored here.

    NO `due_ms` EVER, even if a future bridge sent one. A note has a
    modification date, not a deadline, and `score()` ranks an undated item
    below anything dated -- which is where "sometime" belongs. Inventing
    urgency from a modification date would put whatever the owner touched this
    morning at the top of their agenda every single day.
    """
    p = path or NOTES_PATH
    now = now_s if now_s is not None else time.time()
    if not p.exists():
        return [], {"notes": ("the notes bridge has not run; VESPER has no "
                              "reading of your notes")}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                            # noqa: BLE001
        return [], {"notes": f"the notes dump could not be read ({type(exc).__name__})"}
    try:
        age = now - float(d.get("written_at_s") or 0)
    except (TypeError, ValueError):
        age = float("inf")
    if age > EVENTKIT_FRESH_S:
        return [], {"notes": (f"the notes reading is {int(age // 60)} minutes "
                              f"old, past the {EVENTKIT_FRESH_S // 60} minute "
                              f"freshness window")}
    block = d.get("notes")
    if not isinstance(block, dict):
        return [], {"notes": "the bridge reported nothing for this source"}
    if not block.get("authorized", False):
        return [], {"notes": str(block.get("why")
                                 or "VESPER has not been granted access to notes")}
    items = []
    for raw in block.get("items", []):
        if not isinstance(raw, dict):
            continue
        # THE DUE TIME IS STRIPPED HERE, not trusted to be absent. The reader
        # enforces the rule; the writer merely happens to follow it today.
        it = _item_from({**raw, "due_ms": None}, "notes")
        if it is not None:
            items.append(it)
    return items, {}


def read_eventkit(path: pathlib.Path | None = None,
                  now_s: float | None = None) -> tuple:
    """Calendar and reminders, as the app's bridge last saw them.

    Returns (items, {source: reason}) -- and a stale or missing dump makes BOTH
    calendar and reminders unavailable rather than empty. `INV-HW-2`: a reading
    nobody took is not a reading of zero.
    """
    p = path or EVENTKIT_PATH
    now = now_s if now_s is not None else time.time()
    if not p.exists():
        why = ("the calendar bridge has not run; VESPER has no reading of "
               "your calendar or reminders")
        return [], {"calendar": why, "reminders": why}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                            # noqa: BLE001
        why = f"the calendar dump could not be read ({type(exc).__name__})"
        return [], {"calendar": why, "reminders": why}
    try:
        age = now - float(d.get("written_at_s") or 0)
    except (TypeError, ValueError):
        age = float("inf")
    if age > EVENTKIT_FRESH_S:
        why = (f"the calendar reading is {int(age // 60)} minutes old, past "
               f"the {EVENTKIT_FRESH_S // 60} minute freshness window")
        return [], {"calendar": why, "reminders": why}

    items, unavailable = [], {}
    for source in ("calendar", "reminders"):
        block = d.get(source)
        if not isinstance(block, dict):
            unavailable[source] = "the bridge reported nothing for this source"
            continue
        if not block.get("authorized", False):
            unavailable[source] = (
                f"VESPER has not been granted access to {source}")
            continue
        for raw in block.get("items", []):
            if isinstance(raw, dict):
                it = _item_from(raw, source)
                if it is not None:
                    items.append(it)
    return items, unavailable


def build(*, plan_path: pathlib.Path | None = None,
          eventkit_path: pathlib.Path | None = None,
          notes_path: pathlib.Path | None = None,
          now_s: float | None = None) -> Agenda:
    """Every source, with its own reachability recorded.

    EACH SOURCE FAILS ON ITS OWN. Notes reaches VESPER over Apple Events under
    a separate Automation grant; folding it into the EventKit reader would
    report a denied Notes grant as a calendar outage, and `quiet()` would then
    stay False for a reason it names wrongly.
    """
    items, unavailable = [], {}
    plan_items, plan_bad = read_plan(plan_path)
    items.extend(plan_items)
    if plan_bad:
        unavailable["plan"] = plan_bad
    ek_items, ek_bad = read_eventkit(eventkit_path, now_s=now_s)
    items.extend(ek_items)
    unavailable.update(ek_bad)
    nt_items, nt_bad = read_notes(notes_path, now_s=now_s)
    items.extend(nt_items)
    unavailable.update(nt_bad)
    return Agenda(items=[i for i in items if not i.done], unavailable=unavailable)


def sentence(agenda: Agenda, now_ms: int) -> str:
    """What VESPER would say about the state of the day. One line, no ids."""
    due = agenda.due_now(now_ms)
    parts = []
    if due:
        head = due[0]
        parts.append(f"{head.title} is next" if len(due) == 1
                     else f"{head.title} is next, and {len(due) - 1} more are due")
    if agenda.unavailable:
        # "BUT" ONLY WHEN THERE IS SOMETHING TO CONTRAST WITH. This was
        # unconditional, so with nothing due VESPER opened with "But VESPER has
        # not been granted access to calendar" -- a sentence that answers a
        # question nobody asked. Heard on the first live run, 2026-09-05.
        why = "; ".join(sorted(agenda.unavailable.values()))
        parts.append(("but " + why) if parts else why)
    if not parts:
        return "Nothing is due."
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


# --------------------------------------------------------------- the trigger

# The world term the sweep writes and the trigger reads. Dotted, because a
# predicate snapshot resolves `subject.attribute` through `world.read()`.
DUE_TERM = "world.agenda.item_due"


def item_due(now_s: float | None = None) -> bool:
    """Is anything on the owner's agenda the loop's business right now?

    A SWEEP, FOR THE SAME REASON `fact-expiry` IS ONE. Nothing emits an event
    when a meeting becomes imminent -- time alone makes it true -- so the only
    way to see it is to ask.

    AN UNREADABLE SOURCE DOES NOT FIRE THIS. `Agenda.quiet` distinguishes the
    two cases and the runtime reports the difference in words, but a trigger
    that fired because VESPER could not see the calendar would act on an
    absence of information, which is the opposite of what `INV-HW-2` asks for.
    """
    now = now_s if now_s is not None else time.time()
    ag = build(now_s=now)
    return bool(ag.due_now(int(now * 1000)))


def agenda_trigger(handler=None):
    """`trg_agenda_item_due`, as a callable predicate.

    `handler` IS NOT OPTIONAL IN PRACTICE, WHATEVER THE SIGNATURE SAYS. A
    Trigger carrying neither a handler nor an `intent` is skipped outright by
    `AutonomyLoop.dispatch` -- `if not intent: continue` -- so it fires,
    dispatches, and does nothing.

    THE RUNTIME PASSES ONE (`vesper_runtime.py`, `_agenda_due_handler`), and
    `CI-121` fails if it ever stops. This paragraph used to describe the day
    the trigger shipped WITHOUT a handler as though that were the current
    state, and on 2026-09-05 a later session read it, believed the agenda was
    inert, and reported it to the owner as an open defect that had been fixed
    hours earlier. A docstring that narrates a past bug in the present tense
    is a bug report with no expiry date -- so the history lives in the commit
    message and this says what is true now.

    The default stays `None` because the predicate is worth testing on its
    own, and because a handler built in `core/` could not reach the speech
    path anyway; it is the runtime that holds the voice.

    A HANDLER RATHER THAN AN `intent`. An intent is free text handed to
    `Actor.maybe_act`, which proposes CAPABILITY actions -- shell, files,
    sub-agents. Speaking is not one of them, so an intent would be routed to a
    proposer that has no way to satisfy it and would answer "none". The owner
    asked to be TOLD what is due; telling is the runtime's job, so the runtime
    supplies the callable.

    NO CLOCK TERM, so it survives `CI-026`'s anti-cron probe: the probe
    evaluates with every clock term TRUE and every state term FALSE, and this
    predicate reads only the state term, so the clock alone can never be
    sufficient. Something has to have actually come due.

    THIS IS THE HALF OF THE OWNER'S LOOP THAT WAS MISSING. The other four
    triggers registered here watch VESPER's own housekeeping -- token expiry,
    memory drift, contradictions, a stale knowledge map. This one is the first
    that watches the owner's day.
    """
    from .autonomy import Trigger

    def predicate(s: dict) -> bool:
        return bool(s.get(DUE_TERM))

    return Trigger(
        trigger_id="trg_agenda_item_due",
        predicate_class="STATE",
        predicate=predicate,
        clock_terms=(),
        state_terms=(DUE_TERM,),
        enabled=True,
        # Once a minute at most. An item stays due until it is done, so without
        # this the trigger would fire on every tick for the whole window.
        debounce_s=60,
        handler=handler,
    )
