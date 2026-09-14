"""Who may move a window, and why.

THE OWNER'S RULE, 2026-09-08, VERBATIM: *"windows opened by me are mine, and can
be managed only from a request from me; windows opened by vesper can be totally
managed by vesper"* -- and, asked what happens when the owner's own window sits
on VESPER's Desktop: *"VESPER's Desktop, VESPER's rules."*

THEN RULE 31, 2026-09-13, AND IT REPLACED THAT ANSWER: *"vesper can manage any
window, but only the windows that aren't his are managed only on demand,
everything else is vesper, all grants given by default there for both."* So
authority has ONE source now -- WHO opened the window -- and where it sits
decides nothing. The Desktop clause is gone: an owner's window on VESPER's
Desktop is still the owner's. VESPER's Desktop is still where what VESPER opens
goes (`window_open`); it is no longer a place that makes someone else's window
VESPER's.

WHY THIS IS A MODULE AND NOT A BRANCH INSIDE THE ADAPTER. Everything here is
decidable from a record: a window id, where it is, and who opened it. None of it
needs the Accessibility grant, a running window server, or a Mac. Putting the
rule where it can be driven by a test means the rule can be shown to refuse
things, which is the only way anyone can believe it. The platform adapter is
then a translation layer with no policy in it at all -- the same split
`contracts/policy/host_actions.toml` makes when it says rows name an abstract
effect and the adapter owns the mechanism.

INV-HW-1 APPLIES IN FULL AND IT IS EASY TO BREAK HERE. Not "the Finder window",
not "Safari" -- a window is a record with a provenance and a location. An
application's NAME may travel as an opaque label for the owner to read; it may
never be the thing a rule branches on. A rule that special-cases one program is
a rule the next node cannot honour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The three provenances. `UNKNOWN` is not a fourth state to be resolved later --
# it is the answer whenever VESPER cannot show it opened the window, and it is
# treated exactly as the owner's. INV-HW-2's shape applied to authority: UNKNOWN
# means the restrictive answer, fail-closed, because the alternative is that
# anything VESPER has forgotten about becomes something VESPER may close.
OWNER_OPENED = "owner_opened"
VESPER_OPENED = "vesper_opened"
UNKNOWN = "unknown"
PROVENANCES = (OWNER_OPENED, VESPER_OPENED, UNKNOWN)

# What may happen to a window, as abstract effects. No platform verbs here.
MOVE = "move"
RESIZE = "resize"
CLOSE = "close"
RAISE = "raise"
RELOCATE_OFF = "relocate_off_vespers_desktop"
EFFECTS = (MOVE, RESIZE, CLOSE, RAISE, RELOCATE_OFF)

# The three answers. `FREE` means VESPER may do it unprompted; `ON_REQUEST`
# means the owner must have asked for this, in this turn; `REFUSED` means no
# request makes it permissible.
FREE = "free"
ON_REQUEST = "on_request"
REFUSED = "refused"


class WindowRuleViolation(Exception):
    """A record that cannot be judged. Raised rather than defaulted."""


@dataclass(frozen=True)
class Window:
    """One window, as much as authority needs to know about it.

    Frozen for the reason `Reading` is: a record whose provenance can be
    reassigned after the fact is not a provenance, it is a variable that
    happens to hold one. A window that changes hands does so by being
    re-observed, not by being edited.

    `title` is carried for the OWNER to read and is never branched on. It can
    contain anything on the machine -- a document name, a subject line -- so it
    is content, and content does not decide policy.
    """

    window_id: str
    pid: int
    app_label: str
    desktop_id: str
    provenance: str = UNKNOWN
    title: str | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCES:
            raise WindowRuleViolation(
                f"window {self.window_id!r} carries provenance "
                f"{self.provenance!r}, which is not one of {PROVENANCES}. A "
                "provenance invented at the boundary is how an owner's window "
                "becomes VESPER's by spelling.")
        if not str(self.window_id).strip():
            raise WindowRuleViolation(
                "a window with no id cannot be authorised, because nothing can "
                "later confirm the effect landed on the window that was judged")
        if not str(self.desktop_id).strip():
            raise WindowRuleViolation(
                f"window {self.window_id!r} has no desktop. Location is the "
                "FIRST clause of the owner's rule, so a record that cannot say "
                "where it is cannot be judged at all -- and defaulting it to "
                "'not VESPER's' would quietly grant the safer answer to a "
                "window that might be sitting on VESPER's own Desktop.")


def authority(window: Window, effect: str, *, vespers_desktop: str | None) -> str:
    """May VESPER do `effect` to `window` unprompted, on request, or never?

    ONE QUESTION, RULE 31's (owner, 2026-09-13): who opened it. `vesper_opened`
    is free, everywhere. `owner_opened` and `unknown` are the owner's,
    everywhere, and need the owner to have asked.

    WHAT WENT, AND WHY IT HAD TO. This used to ask WHERE first: "on VESPER's
    Desktop, every window is VESPER's to arrange, whoever opened it" (the owner,
    2026-09-08). Rule 31 has no Desktop exception, and INV-HOST-5 was filed with
    rule 31's sentence while this function still answered the old way -- a gate
    green under a rule it did not enforce. That clause also needed a guard of
    its own: carrying an owner's window onto the Desktop GAVE authority and
    carrying it off SPENT authority held only there. With authority carried by
    the window rather than the place, moving it changes nothing about whose it
    is, and relocation needs no branch.

    `vespers_desktop` IS STILL TAKEN AND DELIBERATELY NOT CONSULTED. `may_act`
    and `describe` tell the owner where the window is, and callers hand the
    same record to all three. `a-window-belongs-to-someone` asserts every
    effect answers the same on every Desktop and with no Desktop at all.
    """
    if effect not in EFFECTS:
        raise WindowRuleViolation(
            f"{effect!r} is not one of {EFFECTS}. `contracts/policy/"
            "host_actions.toml` is fail-closed and so is this: an effect that "
            "is not named is refused rather than approximated to the nearest "
            "one that is.")

    if window.provenance == VESPER_OPENED:
        return FREE                                   # VESPER's own, anywhere
    return ON_REQUEST                                 # the owner's or unrecorded, anywhere


def may_act(window: Window, effect: str, *, vespers_desktop: str | None,
            owner_requested: bool) -> tuple[bool, str]:
    """The same question with the request in hand. Returns (allowed, reason).

    THE REASON IS RETURNED, NOT LOGGED HERE, because the caller knows what it
    was trying to do and this does not. A refusal the owner cannot read is a
    refusal they will report as a bug -- which is the same argument
    `INV-HW-2` makes for carrying the reason on an unavailable reading.
    """
    verdict = authority(window, effect, vespers_desktop=vespers_desktop)
    if verdict == FREE:
        return True, "vesper may arrange this window unprompted"
    if verdict == REFUSED:
        return False, "this effect is refused on this window in every mode"
    if owner_requested:
        return True, "the owner asked for this"
    where = ("on vesper's desktop" if vespers_desktop
             and window.desktop_id == vespers_desktop else "elsewhere")
    if effect == RELOCATE_OFF:
        return False, ("moving a window the owner opened to another desktop "
                       "needs the owner to ask")
    return False, (f"this window is the owner's ({window.provenance}, {where}) "
                   "and was not asked about")


def classify_opened(*, by_vesper: bool) -> str:
    """Stamp provenance at the moment a window appears, never afterwards.

    WHY THERE IS NO INFERENCE HERE AND NEVER WILL BE. The tempting version of
    this function guesses from what the window looks like -- its application,
    its title, whether it resembles something VESPER just asked for. Every one
    of those is a property the owner can produce by accident, and a wrong guess
    in the permissive direction hands VESPER a window it may not touch. The
    only thing that actually knows is the code that did the opening, so that is
    the only thing allowed to say.
    """
    return VESPER_OPENED if by_vesper else OWNER_OPENED


def partition(windows: list, *, vespers_desktop: str | None,
              effect: str = MOVE) -> dict:
    """Split an inventory into what VESPER may arrange and what it may not.

    For the surface: the menu's window row shows a count, and a count that
    silently included windows VESPER cannot touch would promise the owner
    something the executor then refuses.
    """
    free, needs, refused = [], [], []
    for w in windows:
        v = authority(w, effect, vespers_desktop=vespers_desktop)
        (free if v == FREE else needs if v == ON_REQUEST else refused).append(w)
    return {"free": free, "on_request": needs, "refused": refused}


def describe(window: Window, *, vespers_desktop: str | None) -> str:
    """One line the owner can read. Names the app as a LABEL, never as a rule."""
    where = ("vesper's desktop"
             if vespers_desktop and window.desktop_id == vespers_desktop
             else f"desktop {window.desktop_id}")
    who = {OWNER_OPENED: "you opened it", VESPER_OPENED: "vesper opened it",
           UNKNOWN: "opener not recorded"}[window.provenance]
    return f"{window.app_label} on {where} — {who}"
