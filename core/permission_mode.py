"""How much VESPER may do without stopping to ask — the owner's switch.

WHY THIS EXISTS. The ladder answers "how dangerous is this" and "how strongly
was it authorized", and both answers are per-action. Neither answers the
question the owner actually asked on 2026-09-05: *stop asking me every time*.
A standing grant at `L2` means anything above read-and-its-own-workspace stops
for a confirmation, and for an owner sitting at the machine driving VESPER
deliberately, that is most of the useful actions.

THREE MODES, AND THE MIDDLE ONE IS THE POINT.

  ASK        what shipped. VESPER holds `L2` and asks above it.
  WORKSPACE  free inside its own folder, asks the moment it reaches outside.
  AUTO       no questions.

WHAT A MODE MAY AND MAY NOT MOVE, WHICH IS THE WHOLE SAFETY ARGUMENT.

A mode raises the STANDING GRANT -- the authority VESPER carries by default --
because that authority is the owner's to give and the owner is giving it. It
never touches `context_ceiling`. That ceiling is `INV-ACT-3`: content that
enters the system may not raise authority, so a web page, a file VESPER just
read, or a model's own output cannot reach past it *no matter what mode the
owner selected*. Otherwise "auto" would mean "anything that can get text in
front of VESPER inherits the owner's blanket yes", and a steered proposer --
the exact case the second axis was built for -- would be indistinguishable
from the owner asking. AUTO MODE IS THE OWNER TRUSTING VESPER. It is not the
owner trusting everything VESPER reads.

The interlock is untouched too. A mode says how much VESPER may do when it
acts; the enable token says whether it may act autonomously at all, and no
mode mints one.

WORKSPACE MODE IS A CEILING AND THE OTHER TWO ARE NOT, which is why it is
implemented the way it is. Ceilings only ever lower -- they compose under
`min()` -- so "free inside the workspace" cannot be expressed as one. What is
expressible is the inverse: hold the high standing grant, and lower it back to
`ASK_LEVEL` for any action whose arguments reach outside the workspace. Same
outcome, and it fails in the safe direction: an argument this module cannot
resolve to a path inside the workspace is treated as outside it.

FAIL-CLOSED ON EVERY READ. A missing file, malformed JSON, an unknown mode
name, a mode written by something that is not the owner -- all of them read
back as ASK. The dangerous failure is a corrupted byte promoting VESPER, so
there is no path here where damage to this file grants anything.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

# The three, in the order they appear to the owner: least to most authority.
ASK = "ask"
WORKSPACE = "workspace"
AUTO = "auto"
MODES = (ASK, WORKSPACE, AUTO)

# What the standing grant carries in each mode. `ASK_LEVEL` is what shipped and
# is also the floor workspace mode falls back to outside its folder, so the two
# can never drift apart into "outside the workspace is somehow more permissive
# than asking".
ASK_LEVEL = "L2"

# `L3`, AND NOT `L5`, AND THIS IS THE WHOLE DESIGN RATHER THAN A TIMID DEFAULT.
#
# INV-AUTH-2: "L4/L5 are never delegable and BIND TO ONE COMMAND INSTANCE; a
# consumed L4 cannot authorize a second action." A STANDING grant at L5 is a
# contradiction in terms -- and the ladder treats it as one. Measured
# 2026-09-05: auto mode issued a standing L5, the first `shell.run` consumed it
# (`grant.max_level in NEVER_DELEGABLE and consume`), and every action after it
# was refused `grant_consumed` and became a question. The owner set "never ask
# me" and got asked on every step but the first, which is worse than not having
# built the mode.
#
# L3 IS THE HIGHEST LEVEL A GRANT CAN STAND AT, and it covers everything the
# owner has actually been asking for: `shell.run` requires L3, `fs.write`
# requires L2, `ui.open` and `fs.read` require L1. So auto mode means no
# questions for running commands, writing files and opening things.
#
# WHAT STILL ASKS, AND WHY IT SHOULD. L4/L5 is the tier that cannot be undone
# from the record alone -- overwriting a file this turn never read, deleting,
# acting outside the owner's own space. Those bind to one command instance by
# invariant, which means one confirmation buys one action, deliberately. Auto
# mode is not a way to switch that off; nothing is.
FREE_LEVEL = "L3"

STANDING_LEVEL = {ASK: ASK_LEVEL, WORKSPACE: FREE_LEVEL, AUTO: FREE_LEVEL}

# No ceiling at all is expressed as the top of the ladder, so the composition
# in the PDP stays a plain `min()` with no special case for "not set".
NO_CEILING = "L5"

# Human-facing, because the settings screen will render these and the CLI
# prints them today. Kept here so the frontend never invents its own wording.
DESCRIPTION = {
    ASK: "Ask me before anything beyond reading and its own workspace.",
    WORKSPACE: "Free inside its own workspace folder. Ask before touching "
               "anything else.",
    AUTO: "Do not ask. Full authority on everything the owner requests.",
}


def observations_taint(mode: str) -> bool:
    """Does what VESPER just observed lower the ceiling for the next step?

    IN `ask` AND `workspace`, YES, AND THAT IS INV-ACT-3 DOING ITS JOB: command
    output and file contents are `retrieved_external`, so the step that could be
    steered by what was just read is the step that has to ask.

    IN `auto`, NO, BY THE OWNER'S EXPLICIT AND REPEATED INSTRUCTION (2026-09-05,
    twice, in terms that left nothing to interpret). What that ceiling did in
    practice was make MULTI-STEP WORK IMPOSSIBLE rather than careful:
    `shell.run` requires L3, its own output is `retrieved_external`, so the
    ceiling fell to L1 the instant VESPER ran anything and every later step was
    refused for `context_ceiling` -- which is deliberately NOT confirmable, so
    the owner could not approve it either. "Write a script and run it" was
    unreachable in every mode, and the owner watched it fail for days.

    WHAT IS ACTUALLY BEING ACCEPTED, stated plainly because it is a real trade:
    with this off, text VESPER reads -- a file's contents, a command's output, a
    sub-agent's answer -- can influence what it does next, up to `FREE_LEVEL`.

    WHAT DOES NOT MOVE, because these bound the blast radius rather than the
    intent: `shell.run` still executes under the seatbelt profile
    (`(deny default)`, `(deny network*)`, writes confined to the workspace and
    /tmp); L4/L5 still bind to one command instance and still ask; the interlock
    still stops autonomy within a token lifetime; every action is still recorded
    with the authority it ran under. This is the owner extending THEIR authority
    over their own machine, and it is one word to undo: `--permission-mode ask`.
    """
    return mode != AUTO


# WHAT AUTO MODE MAY NOT WAIVE, WHATEVER THE OWNER GRANTS.
#
# §11.5 and the owner's own answer, 2026-09-08: "permissions yes, taint stays."
# Auto mode grants every permission with no asking -- VESPER clicks, types,
# opens and closes freely -- and text it READS OFF THE SCREEN stays untrusted:
# actionable as information, never obeyed as a command.
#
# THE TWO ARE DIFFERENT QUESTIONS AND THE OWNER SEPARATED THEM. "May VESPER
# act" is granted in full. "May what VESPER read tell it what to do" is refused
# in every mode. A screen can display anyone's text -- a web page's, an email's,
# a message from someone else -- and auto mode is about trusting VESPER, not
# about trusting whatever happens to be on screen.
#
# AND THE WAIVER WAS ALL-OR-NOTHING UNTIL 2026-09-10, which is why this exists.
# `observations_taint` answers per MODE, so `auto` waived the ceiling for EVERY
# observation regardless of where it came from. §9 recorded the screen
# constraint in advance, precisely so it would not be discovered late -- and the
# mechanism that was supposed to honour it could not express it.
#
# WHY NOT DISCRIMINATE ON THE TRUST CLASS. `shell.run`'s output is
# `retrieved_external` too, and the owner deliberately DID waive that one: it is
# what made multi-step work possible at all. Trust class cannot separate them,
# so the source capability is named.
#
# KNOWN LIMIT, STATED RATHER THAN HIDDEN. A future capability that reads the
# screen and is not added to this set would be waived like any other, and no
# gate would catch it -- membership is a declaration, not a measurement. The
# check asserts the set is non-empty and that the actor consults it; it cannot
# assert that somebody remembered. §11.5's build has to add its own id here.
NEVER_WAIVED_SOURCES = frozenset({"ui.view", "ui.screenshot"})


def observation_waivable(mode: str, capability_id: str) -> bool:
    """May THIS observation stop capping what VESPER does next?

    Asked per observation rather than per step, because one screen capture in a
    batch has to bind the whole step: a rule that waives the ceiling as long as
    SOMETHING in context was ordinary is a rule an injected page walks straight
    through by arriving alongside a file read.
    """
    if str(capability_id or "") in NEVER_WAIVED_SOURCES:
        return False
    return not observations_taint(mode)


class ModeRefused(Exception):
    """A mode was rejected. Never raised on a READ -- reads fail to ASK."""


def _default_path() -> pathlib.Path:
    return (pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
            / "permission_mode.json")


def read(path: pathlib.Path | None = None) -> str:
    """The mode in force. ANY failure is `ASK`.

    Deliberately has no `default` parameter. A caller that could pass one could
    pass `AUTO`, and then a deleted file would be a promotion.
    """
    p = path or _default_path()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        mode = str(d.get("mode", "")).strip().lower()
    except Exception:                                   # noqa: BLE001
        return ASK
    return mode if mode in MODES else ASK


def write(mode: str, *, principal: str, path: pathlib.Path | None = None,
          bus: Any = None, now_ms: int | None = None) -> dict:
    """Set the mode. A NAMED PRINCIPAL IS REQUIRED, for the same reason
    `SafetyInterlock.rearm` requires one: "the system raised its own authority"
    is the state this must never be able to record.
    """
    m = str(mode or "").strip().lower()
    if m not in MODES:
        raise ModeRefused(f"unknown mode {mode!r}; expected one of {MODES}")
    if not str(principal or "").strip():
        raise ModeRefused(
            "setting the permission mode requires a named principal. A mode "
            "change with no principal is VESPER raising its own authority.")
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": m, "set_by": principal, "set_at_ms": now_ms}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    # 0600 BEFORE THE RENAME. A world-writable mode file is a promotion anyone
    # on the machine can hand themselves, and chmod-after-rename leaves a
    # window where it is readable at the default umask.
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    if bus is not None:
        bus.publish("permission.mode_set", subject=principal,
                    payload={"mode": m, "principal": principal,
                             "standing_level": STANDING_LEVEL[m]},
                    component="permission_mode")
    return dict(payload)


def standing_level(mode: str) -> str:
    """What the standing grant carries. An unknown mode carries the least."""
    return STANDING_LEVEL.get(mode, ASK_LEVEL)


# COMMANDS ARE BOUNDED BY THE KERNEL, NOT BY THIS MODULE. Every `shell.run`
# is executed under the seatbelt profile in `core/capabilities.py`, which is
# `(deny default)`, `(deny network*)`, and `file-write*` allowed ONLY into the
# workspace and the temp directory. So "does this command stay in the
# workspace" is not a question this module has to answer from a string -- it
# is already true of the process, enforced somewhere a wrong guess here cannot
# reach. Everything else in this file is about capabilities that are plain
# Python calls with no such fence: `fs.write`, `fs.edit`, `ui.open`.
#
# WHAT WORKSPACE MODE THEREFORE MEANS, PRECISELY, and the owner should hear it
# in these words: VESPER may change anything inside its own folder and run
# whatever it likes there without asking; it may READ your files, because the
# profile allows `file-read*`; it may not write outside its folder and it may
# not reach the network at all.
SEATBELTED = ("shell.run",)


def _paths_in(args: dict) -> list:
    """Every argument that could name a place on disk.

    NOT A WHITELIST OF KEY NAMES. A capability added later with a `dest` or an
    `into` would slip past one, and slipping past means workspace mode treats
    an outside path as inside. Anything string-shaped is considered, and
    `contained()` decides.
    """
    out = []
    for v in (args or {}).values():
        if isinstance(v, str) and v:
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.extend(x for x in v if isinstance(x, str) and x)
    return out


def contained(capability_id: str, args: dict, workspace: pathlib.Path) -> bool:
    """Does this action stay inside the workspace?

    THE ANSWER FOR "I CANNOT TELL" IS NO. A string that resolves nowhere is not
    demonstrably inside the workspace, and workspace mode promises "free inside
    its own folder", not "free unless something looks odd".

    NO METACHARACTER HEURISTIC. An earlier version here rejected any argument
    containing a space on the theory that it was a command line rather than a
    path. On this machine the workspace is under `~/Library/Application
    Support/`, so EVERY path in it contains a space, and workspace mode refused
    its own folder -- the same shape as the redactor mangling a path because it
    scored like a secret. Commands do not need the heuristic (see SEATBELTED)
    and paths must not have it.
    """
    if capability_id in SEATBELTED:
        return True
    ws = workspace.resolve()
    candidates = _paths_in(args)
    if not candidates:
        # Nothing addressable at all: the ordinary ladder still applies, so
        # this is not a promotion.
        return True
    for raw in candidates:
        tok = raw.strip()
        if not tok:
            return False
        try:
            cand = pathlib.Path(os.path.expanduser(tok))
            cand = cand if cand.is_absolute() else (ws / cand)
            cand = cand.resolve()
        except Exception:                               # noqa: BLE001
            return False
        if cand != ws and ws not in cand.parents:
            return False
    return True


def ceiling_for(mode: str, capability_id: str, args: dict,
                workspace: pathlib.Path) -> str:
    """The ceiling this mode imposes on THIS action.

    `ask` and `auto` impose none -- they are expressed entirely in the standing
    grant. Only `workspace` looks at the action, because it is the only mode
    whose answer differs between two calls of the same capability.
    """
    if mode != WORKSPACE:
        return NO_CEILING
    return (NO_CEILING if contained(capability_id, args, workspace)
            else ASK_LEVEL)
