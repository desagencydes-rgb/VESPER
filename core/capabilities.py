"""The capabilities VESPER actually holds — levels, implementations, verifiers.

WHAT WAS MISSING, AND IT WAS NOT THE MACHINERY. `core/capability.py` refuses a
constant level at registration; `core/authorize.py` decides; `core/executor.py`
re-checks and compensates. All of it was built, gated, and reachable by nothing:
the only `shell.run` in this corpus lived inside `run_f2_acceptance.py`'s
`_registry()` fixture. The verification report says so in its own words --
"No subsystem, no decision function, no contract covers endpoint interaction."
So VESPER could decide perfectly about actions it had no way to take.

This module is the promotion of that fixture into the running system, which is a
different act from copying it: a fixture may assume its caller is a test, and
these implementations run against the owner's real machine.

THE LEVEL RULES FAIL CLOSED, and the asymmetry is deliberate. Every classifier
here answers "is this provably harmless" and never "does this look dangerous".
A denylist of dangerous forms is wrong in the direction that destroys data: the
first command nobody thought of is admitted at L1. An allowlist is wrong in the
direction that asks a question the owner can answer. `INV-HW-2` makes the same
move for throughput -- UNKNOWN means UNAVAILABLE -- and it is the same argument.

WHY `ls; rm -rf ~` IS NOT READ-ONLY, which is the whole trap in `shell.run`.
The command *begins* with an allowlisted verb, so any classifier that checks the
first word admits it, and A-013's assertion still passes because `ls` and
`rm -rf ~` do resolve differently. The chaining form is the one that gets past
both. Anything that can introduce a second command -- `;` `&&` `||` `|` backtick
`$(` `>` `<` newline -- disqualifies the whole string from being read-only
before the verb is ever looked at.

VERIFICATION IS INDEPENDENT OF THE ACTOR'S CLAIM (A-013, INV-VERIF-1). An
implementation returning `{"ok": True}` is the actor's story about itself. Each
capability that changes something is paired with a verifier that goes and READS
THE WORLD: `fs.write` re-reads the file off disk and compares its hash to the
hash of what was supposed to be written. This is the corpus's standing rule --
"an instrument's self-report is not evidence" -- applied at the point where it
costs something to honour.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import tempfile
import time
from typing import Any

from core.capability import CapabilityRegistry, LevelRule
from core.taint import EXTERNAL

# THE ROOT THE LEVEL RULES ARE TALKING ABOUT, stated rather than inherited.
# `fs_write_level("workspace/x")` returns L2 and `("contracts/policy/y")`
# returns L5 -- both readings of a RELATIVE path, which mean nothing without a
# root. Until this was written the root was whatever working directory the
# process happened to have: `$REPO` under the LaunchAgent, and something else
# for anyone running the runtime by hand. So the same argument could be levelled
# as a harmless workspace file and then executed against a different tree.
# The classifier and the implementation now resolve against the same constant.
REPO = pathlib.Path(__file__).resolve().parents[1]

# AND `workspace/` IS NOT UNDER IT, which testing through the shipped bundle is
# the only way to find. The app bundle carries a COPY of the runtime, so
# `parents[1]` there is `VESPER.app/Contents/Resources/runtime` -- and
# `build.sh` rewrites that directory on every build. Asked in Darija to write a
# note "f workspace/test.txt", VESPER wrote it, reported success truthfully, and
# put it somewhere the next build deletes. Nothing was wrong with the level, the
# write, or the verification: the file was real, the hash matched, and it was
# doomed.
#
# VESPER's own writable space therefore lives beside its state, not beside its
# code, because state survives a rebuild and code is replaced by one.
WORKSPACE = (pathlib.Path.home() / "Library" / "Application Support" /
             "VESPER" / "workspace")


def resolve(path: str) -> pathlib.Path:
    """`~` expanded; `workspace/` to the durable one; anything else to the repo.

    FULLY NORMALISED, and that is not cosmetic. `..` and symlinks are collapsed
    here so that the path the level rules judge is the path the implementation
    opens. Without it the two reason about different filesystems -- the exact
    split `shell_run` refuses `shell=True` to avoid.
    """
    raw = str(path or "")
    p = pathlib.Path(os.path.expanduser(raw))
    if not p.is_absolute():
        parts = pathlib.PurePosixPath(raw.replace("\\", "/")).parts
        if parts and parts[0] == "workspace":
            p = WORKSPACE.joinpath(*parts[1:])
        else:
            # A BARE RELATIVE PATH MEANS THE OWNER'S HOME, NOT THE CODE'S ROOT.
            # `REPO` is `__file__`'s parent, which inside the shipped bundle is
            # `VESPER.app/Contents/Resources/runtime` -- so "Downloads/x.png"
            # resolved to a Downloads folder inside the app. Measured
            # 2026-09-04: the owner asked for a file that was sitting in
            # ~/Downloads and got `FileNotFoundError` naming a path inside the
            # bundle, then the sentence "I tried and it did not go through".
            #
            # WHEN A PERSON SAYS "Downloads" THEY MEAN THEIRS. Home is tried
            # first and the repo second, so a relative path that names a real
            # project file still resolves for work inside the checkout; when
            # neither exists the HOME form is returned, because that is the one
            # the owner meant and the error should name the place they looked.
            # HOME ONLY WHEN THE FILE IS ACTUALLY THERE. The first version of
            # this also sent NON-EXISTENT relative paths home, which is a
            # different and worse thing: `fs.write "notes.txt"` became a write
            # into the home ROOT and levelled L5, and the registry caught it --
            # `fs.write` rule 'ordinary' declares L3 and its own example
            # resolved L5. Naming an existing file is the case the owner meant
            # ("the png in Downloads"); inventing a new one is not, and it
            # belongs where it always went. `~/...` still reaches home for
            # creating something there, which is what the proposer is told to
            # write.
            home_p = pathlib.Path.home() / p
            p = home_p if home_p.exists() else (REPO / p)
    return pathlib.Path(os.path.normpath(str(p))).resolve()


def _under(child: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        child.relative_to(pathlib.Path(os.path.normpath(str(parent))).resolve())
        return True
    except ValueError:
        return False


def _escapes(raw: str, resolved: pathlib.Path) -> bool:
    """Did a relative path end up outside the root its own prefix claimed?

    `workspace/../../../../etc/passwd` STARTS WITH `workspace/`, so a classifier
    reading the string levels it as VESPER's own scratch space -- L2 to write,
    L1 to read -- while the filesystem opens `/etc/passwd`. Measured
    2026-08-31: both of those levels came back exactly that way.

    This is the defect the whole module is written against, arriving through the
    one door that was still classifying a STRING instead of a TARGET. It also
    defeats the sentence this design rests on -- that safety does not depend on
    the proposer being right -- because a traversal argument is precisely what a
    wrong or steered proposer would produce.
    """
    if pathlib.PurePosixPath(raw.replace("\\", "/")).is_absolute():
        return False
    if raw.startswith("~"):
        return False
    parts = pathlib.PurePosixPath(raw.replace("\\", "/")).parts
    claimed = WORKSPACE if (parts and parts[0] == "workspace") else REPO
    return not _under(resolved, claimed)

# ---------------------------------------------------------------- shell.run

# Verbs that cannot alter the machine no matter what they are pointed at. Kept
# SHORT on purpose: every addition is a new way to be wrong, and the cost of
# omitting one is a question to the owner rather than a destroyed file.
READ_ONLY_VERBS = frozenset({
    "ls", "pwd", "whoami", "date", "uname", "hostname", "id",
    "cat", "head", "tail", "wc", "file", "stat", "du", "df",
    "echo", "which", "type", "uptime", "ps",
})

# Anything that could introduce a SECOND command. Checked before the verb, so a
# chained destructive tail cannot ride in behind an allowlisted head.
CHAINING = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "&")

# Forms whose damage is not recoverable and which must never resolve below the
# top level even when they are the whole command.
DESTRUCTIVE_MARKERS = (
    "rm ", "rmdir", "mkfs", "dd ", "shutdown", "reboot", "killall",
    "chmod", "chown", "diskutil", "launchctl", "defaults write", "pkill",
    ":(){", "sudo", "curl", "wget", "nc ", "ssh ",
)


LEVEL_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


def _looks_like_path(tok: str) -> bool:
    """A token naming a file, as opposed to a flag or a bare word."""
    if not tok or tok.startswith("-"):
        return False
    return "/" in tok or tok.startswith("~") or tok.startswith(".")


def _worst(a: str, b: str) -> str:
    return a if LEVEL_RANK.get(a, 5) >= LEVEL_RANK.get(b, 5) else b


def _session_cwd(args: dict) -> str:
    """The directory a command will run in, given its session. Never raises.

    ONE ANSWER, USED BY BOTH THE CLASSIFIER AND THE EXECUTION. A second
    computation of "where does this run" is a second thing to disagree with,
    and the disagreement is invisible: the level rules would be judging a tree
    the command never touches.
    """
    sid = args.get("session")
    carried = _SHELL_SESSIONS.get(str(sid)) if sid else None
    base = (carried or {}).get("cwd") or str(REPO)
    try:
        return _resolve_cwd(args.get("cwd"), base)
    except Exception:                                  # noqa: BLE001
        # An out-of-scope cwd is refused at execution with a reason; here it
        # must not change the LEVEL, so the strictest root stands in.
        return base


def shell_level(args: dict) -> str:
    """`ls` -> L1, `rm -rf ~` -> L5, everything else -> L3. A-013's own case.

    THE ORDER MATTERS AND IT IS NOT THE OBVIOUS ONE. Destructive markers are
    tested BEFORE the read-only allowlist, because `cat /etc/passwd | sudo tee`
    starts with an allowlisted verb. And chaining disqualifies before either,
    because the whole point of `ls; rm -rf ~` is that both halves are honest.
    """
    cmd = str(args.get("cmd") or "").strip()
    if not cmd:
        return "L5"                      # an empty command is not a safe one
    low = cmd.lower()
    if any(m in low for m in DESTRUCTIVE_MARKERS):
        return "L5"
    if any(c in cmd for c in CHAINING):
        return "L3"                      # composable, so not provably read-only
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return "L5"                      # unbalanced quoting: not analysable
    base = "L1" if (parts and parts[0] in READ_ONLY_VERBS) else "L3"

    # THE SAME FILE MUST NOT BE CHEAPER THROUGH THIS DOOR. `fs.read` refuses a
    # credential at L5, and `shell.run("cat ~/.ssh/id_rsa")` was returning L1 --
    # `cat` is allowlisted and nothing looked at what it was pointed AT. The
    # protection was real and there were two ways in, which is the defect this
    # module has now hit three times: a level about a VERB while the effect is
    # about a TARGET.
    #
    # So every path-shaped argument is levelled by the rules that already govern
    # reading it, and the command inherits the worst answer. One classifier for
    # "what does this touch", used by both doors.
    # RESOLVED AGAINST THE ROOT THE COMMAND WILL ACTUALLY RUN IN. The level
    # rules are relative prefixes -- `workspace/` is L2, `contracts/` is L5 --
    # so a relative argument means nothing without a root, and the root the
    # CLASSIFIER assumes must be the root the EXECUTION uses. It was not: the
    # classifier resolved against the process's own working directory while
    # `shell.run` pinned execution to the repo, and a session that carries a
    # `cwd` widens that gap into "levelled against one tree, executed against
    # another". Same root, both doors.
    root = _session_cwd(args)
    for tok in parts[1:]:
        if _looks_like_path(tok):
            probe = tok
            if not tok.startswith(("/", "~")):
                probe = str(pathlib.Path(root) / tok)
            base = _worst(base, fs_read_level({"path": probe}))
    return base


# The kernel-level containment for `shell.run`. Present on every macOS this
# runs on; its absence is a refusal rather than a fallback.
SEATBELT = "/usr/bin/sandbox-exec"


class ContainmentUnavailable(Exception):
    """The sandbox could not be applied, so the command does not run.

    FAIL CLOSED, AND THE ALTERNATIVE IS THE WHOLE POINT. Running unsandboxed
    "just this once" because the sandbox is missing is running unsandboxed
    exactly when the machine is in a state nobody predicted.
    """


def _seatbelt_profile(level: str) -> str:
    """The profile a command of this level runs under.

    WHY CONTAINMENT AT ALL, GIVEN THE LEVEL RULES. Because classification is a
    judgement about a STRING and the sandbox is a rule about a PROCESS. Every
    defect this module has had was the gap between those two: a path that
    levelled as the workspace and opened /etc/passwd, a verb allowlist that
    admitted a command whose redirection nobody looked at. The classifier is
    allowed to be wrong here, because the kernel is not consulting it.

    NETWORK IS DENIED AT EVERY LEVEL. `ModelGateway` is the only sanctioned
    egress and the redactor sits in front of it; a shell command that can open
    a socket is a second exit with nothing in front of it, whatever the owner
    approved the command for.

    WRITES DEPEND ON WHAT THE LEVEL CLAIMED. L1 means "provably read-only", so
    the profile makes that true rather than trusting it -- a command that
    levelled L1 and tries to write is refused by the kernel, and the refusal is
    evidence the classifier was wrong. Above L1 the owner has approved an
    action that changes something, so writes are allowed into VESPER's own
    space and the temp directory, and nowhere else.
    """
    parts = ['(version 1)', '(deny default)',
             '(allow process-exec process-fork)',
             '(allow sysctl-read)', '(allow mach-lookup)',
             '(allow file-read*)',
             '(deny network*)']
    if level == "L1":
        parts.append("(deny file-write*)")
        return "".join(parts)

    writable = [str(WORKSPACE), tempfile.gettempdir()]

    # AUTO MODE REACHES THE OWNER'S OWN FILES, AND THE INCONSISTENCY THAT
    # FORCED THIS IS WORTH RECORDING. `fs.write` is a Python call and is not
    # seatbelted; `shell.run` is. So VESPER could CREATE ~/Downloads/hey.txt
    # and then could not RENAME it -- measured 2026-09-05, `mv: Operation not
    # permitted`, reported to the owner as "error code 1" with no reason. Two
    # capabilities disagreeing about where the owner's files are is not a
    # containment boundary, it is a bug that looks like one.
    #
    # HOME, NOT `/`. The system stays read-only: no writes to /System,
    # /Library, /usr, /bin, another user's home, or the VESPER repo's own
    # governed paths (INV-SELF-1..7 keeps the runtime out of its own source,
    # and that rule is upstream of this one). And `(deny network*)` does NOT
    # move in any mode -- `ModelGateway` is the only sanctioned egress and the
    # redactor sits in front of it, so a shell that could open a socket would
    # be a second exit with nothing in front of it whatever the owner approved.
    #
    # READ FRESH, NOT CACHED AT IMPORT. The owner switches modes to change what
    # VESPER may do NOW; a profile fixed at process start would need a restart
    # to take effect, and a restart is what the mode exists to avoid.
    try:
        from . import permission_mode as _pm
        if _pm.read() == _pm.AUTO:
            writable.append(str(pathlib.Path.home()))
    except Exception:                                   # noqa: BLE001
        # A mode that cannot be read is `ask`, here as everywhere else: the
        # narrow profile is the safe one, so a broken read costs reach and
        # never grants it.
        pass

    for d in writable:
        parts.append(f'(allow file-write* (subpath "{d}"))')
    return "".join(parts)


def shell_run(args: dict) -> dict:
    """Run it CONTAINED, and report what was OBSERVED rather than whether it
    'worked'.

    No shell. `shell=True` would re-introduce every chaining form the level
    rules just spent their effort excluding -- the classifier would be reasoning
    about one language and the execution happening in another.

    `cwd` IS STATED for the same reason: a relative path means nothing without a
    root, and inheriting one makes the level a function of who started the
    process.
    """
    cmd = str(args.get("cmd") or "")
    timeout = float(args.get("timeout") or 20.0)
    argv = shlex.split(cmd)
    if not argv:
        raise ValueError("no command to run")

    # `~` IS EXPANDED HERE BECAUSE NO SHELL WILL DO IT. `shell=True` is refused
    # on purpose, so a `~` reaching the kernel is a literal directory named
    # "~", and `open ~/Downloads/x.png` fails with "No such file or directory"
    # while the same path spelled out works. Measured 2026-09-04.
    #
    # ONLY A LEADING `~`, and only where a shell would expand one -- this is
    # not a general rewrite of relative paths. A bare `Downloads/x.png` still
    # means "relative to the working directory", which is what every other
    # command-line tool on this machine would also do with it; the proposer is
    # told to write the owner's folders as `~/...` for exactly that reason.
    argv = [(os.path.expanduser(a) if a.startswith("~") else a) for a in argv]

    # THE SESSION'S CARRIED CONTEXT. Absent a session id this behaves exactly as
    # it did: one command, in the repo, with the ambient environment.
    sid = args.get("session")
    carried = _SHELL_SESSIONS.get(str(sid)) if sid else None
    env_over = dict((carried or {}).get("env") or {})
    for k, v in (args.get("env") or {}).items():
        if str(k).upper() in ENV_NEVER_SETTABLE:
            raise ValueError(
                f"{k} may not be set for a contained command: it changes which "
                "binary runs or what it loads, so the argv the level rules "
                "classified would not be the program that executes.")
        env_over[str(k)] = str(v)
    # THE SAME ANSWER THE CLASSIFIER USED, from the same function -- but
    # re-resolved rather than reused, so an out-of-scope cwd still RAISES here
    # instead of silently falling back the way the level computation must.
    base_cwd = ((carried or {}).get("cwd") or str(REPO))
    run_cwd = _resolve_cwd(args.get("cwd"), base_cwd)

    if not os.path.exists(SEATBELT):
        raise ContainmentUnavailable(
            f"{SEATBELT} is not on this machine, so shell.run has no "
            "containment. The command was not run.")

    level = shell_level(args)
    env = {**os.environ, **env_over} if env_over else None
    argv_contained = [SEATBELT, "-p", _seatbelt_profile(level), *argv]

    # BACKGROUND IS THE SAME COMMAND, CONTAINED THE SAME WAY. It is levelled by
    # the same rules, wrapped in the same seatbelt profile and run in the same
    # resolved directory -- the only difference is that nobody waits for it.
    # Running a command in the background must never be a way to run a
    # DIFFERENT command, which is what a separate path here would eventually
    # become.
    if args.get("background"):
        jobs = args.get("_jobs")
        if jobs is None:
            raise ValueError(
                "background was requested and no job registry was supplied, so "
                "nothing could stop this command once it started. Refused: an "
                "unstoppable process is exactly what the emergency stop exists "
                "to prevent.")
        started = jobs.start(argv_contained, cmd=cmd,
                             period=str(args.get("period") or "active"),
                             cwd=run_cwd, env=env)
        if sid:
            key = str(sid)
            if key not in _SHELL_SESSIONS and len(_SHELL_SESSIONS) >= MAX_SHELL_SESSIONS:
                _SHELL_SESSIONS.pop(next(iter(_SHELL_SESSIONS)))
            _SHELL_SESSIONS[key] = {"cwd": run_cwd, "env": env_over}
        return {**started, "contained": True, "containment_level": level,
                "cwd": run_cwd, "session": str(sid) if sid else None,
                "background": True}

    # WALL CLOCK, AND THIS IS ONE OF THE TWO THINGS IT IS FOR. `INV-COORD-4`
    # forbids a timestamp to ORDER or SUPERSEDE anything; "how long did this
    # take" is a duration, orders nothing, and is measured the only way a
    # duration can be.
    _t0 = time.monotonic()
    p = subprocess.run(argv_contained,
                       capture_output=True, text=True,
                       timeout=timeout, check=False, cwd=run_cwd, env=env)
    _elapsed_ms = int((time.monotonic() - _t0) * 1000)

    # PERSISTED ONLY ON A SESSION THAT WAS ASKED FOR, and only after the command
    # actually ran. Recording the cwd before the run would leave a session
    # pointing somewhere a failed command never reached.
    if sid:
        key = str(sid)
        if key not in _SHELL_SESSIONS and len(_SHELL_SESSIONS) >= MAX_SHELL_SESSIONS:
            _SHELL_SESSIONS.pop(next(iter(_SHELL_SESSIONS)))
        _SHELL_SESSIONS[key] = {"cwd": run_cwd, "env": env_over}

    # ARGV IS RETURNED BECAUSE ARGV IS WHAT RAN. Everything downstream that
    # wants to show the owner this command had only the `cmd` STRING, and
    # rebuilding a command line from a string it was already split from is a
    # reconstruction that can differ from the thing the kernel received. The
    # commands card shows what ran, so it is given what ran.
    #
    # UNCONTAINED, DELIBERATELY: `argv` without the seatbelt wrapper. The
    # wrapper is how the command was confined, not what the owner asked for,
    # and `containment_level` beside it already says the confinement happened.
    return {"exit_code": p.returncode,
            "argv": list(argv),
            "elapsed_ms": _elapsed_ms,
            "stdout": p.stdout[:4000],
            "stderr": p.stderr[:2000],
            "contained": True,
            "containment_level": level,
            "cwd": run_cwd,
            "session": str(sid) if sid else None}


def agent_run_level(args: dict) -> str:
    """Consulting a named agent, levelled on what leaves AND what it may do.

    TWO THINGS DECIDE THIS, not one. `agent.ask` is levelled on the material
    because that is all that happens: text goes to a provider. A named agent
    can also hold TOOLS, and one of them -- the tester -- runs commands. So the
    level is the worse of "what is being sent" and "what this agent is allowed
    to do", because either can be the dangerous half.

    AN AGENT THAT ACTS IS L3 AT BEST. It runs gate commands on the owner's
    machine outside VESPER's own containment, which is exactly the trade the
    roster contract writes down. It is never cheaper than a command VESPER
    would run itself.
    """
    material = str(args.get("material") or "")
    low = material.lower()
    if any(m in low for m in SECRET_MARKERS):
        return "L5"
    name = str(args.get("agent") or "")
    spec = _agent_spec(name)
    if spec is None:
        # AN AGENT NOBODY DECLARED IS NOT A CHEAP ONE. Unknown means unknown,
        # and INV-HW-2's rule about unmeasured values applies to authority the
        # same way it applies to throughput.
        return "L5"
    if spec.get("acts"):
        return "L3"
    if len(material) > SUBAGENT_MATERIAL_L3:
        return "L3"
    return "L2"


def _agent_spec(name: str):
    """The declared agent, or None. Never raises, never invents one."""
    try:
        from core.agents import load_roster
        return load_roster().get(str(name))
    except Exception:                                  # noqa: BLE001
        return None


def agent_run(args: dict) -> dict:
    """Run a named agent. Bound with a runner; refuses without one."""
    runner = args.get("_runner")
    if runner is None:
        raise ValueError(
            "a named agent was asked for and no runner was supplied, so the "
            "question would have gone nowhere. Refused rather than answered "
            "from nothing.")
    res = runner.run(str(args.get("agent") or ""),
                     str(args.get("question") or ""))
    return dict(res)


def agent_ask_level(args: dict) -> str:
    """Asking a sub-agent is EGRESS, and it is levelled on what leaves.

    A LEVEL ABOUT THE VERB WHILE THE EFFECT IS ABOUT THE TARGET is the defect
    this module has already hit three times -- `shell.run("cat ~/.ssh/id_rsa")`
    returning L1 because `cat` is allowlisted. Delegation is the same shape with
    a friendlier name: "ask a sub-agent" sounds like thinking, and what it
    actually does is send material to a provider. So the material is what is
    levelled, by the rules that already govern reading it.
    """
    material = str(args.get("material") or "")
    low = material.lower()
    if any(m in low for m in SECRET_MARKERS):
        # The same reasoning `fs_read_level` gives: putting a credential in a
        # context window IS the step where it leaves.
        return "L5"
    if len(material) > SUBAGENT_MATERIAL_L3:
        # Sending a lot of the owner's material to a provider is a bigger act
        # than asking a question about a paragraph, and the size is the only
        # thing about it this can see without reading it.
        return "L3"
    return "L2"


def agent_ask(args: dict) -> dict:
    """Ask a sub-agent. Bound with a gateway; refuses without one."""
    agent = args.get("_agent")
    if agent is None:
        raise ValueError(
            "a sub-agent was asked for and no agent was supplied, so the "
            "question would have gone nowhere. Refused rather than answered "
            "from nothing.")
    return agent.ask(str(args.get("question") or ""),
                     material=str(args.get("material") or ""))


# How much material makes delegation an L3 act rather than an L2 one.
SUBAGENT_MATERIAL_L3 = 4000


# ------------------------------------------------------------ shell sessions

# WHAT SURVIVES BETWEEN TWO `shell.run` CALLS. Codex keeps a real shell process
# alive so `cd`, exports and an activated venv persist; a straight line of
# independent commands cannot install a dependency and then use it.
#
# THIS IS SESSION STATE, NOT A SESSION PROCESS, and the difference is the whole
# reason it is safe here. A live shell would re-introduce exactly what
# `shell.run` refuses on purpose -- the module says it in its own words: no
# `shell=True`, because "the classifier would be reasoning about one language
# and the execution happening in another". Chaining, redirection and
# substitution would all become invisible again, and the level rules would be
# classifying a string that is no longer what runs. So each command is still one
# contained argv the classifier sees whole; only the CONTEXT it runs in carries
# over.
_SHELL_SESSIONS: dict = {}
# Bounded, because a session dict keyed by whatever the proposer invents is a
# map a steered model can grow without limit. Oldest out first.
MAX_SHELL_SESSIONS = 16

# ENVIRONMENT NAMES A SESSION MAY NEVER SET. Not a style rule -- each of these
# changes WHICH BINARY RUNS or what it loads, which means the argv the level
# classifier read is no longer the program that executes. `PATH` is the obvious
# one: `npm test` classified as a test run becomes whatever `npm` a prepended
# directory supplies. The loader variables are the same attack one layer down,
# and they are how a contained process is made to load code nobody classified.
#
# REFUSED RATHER THAN LEVELLED UP. A higher level would make it the owner's
# question, and the owner cannot see the difference between a PATH that is fine
# and a PATH that is an attack -- that is the whole point of the substitution.
ENV_NEVER_SETTABLE = ("PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
                      "DYLD_FRAMEWORK_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
                      "PYTHONPATH", "PYTHONSTARTUP", "NODE_OPTIONS",
                      "BASH_ENV", "ENV", "SHELL", "IFS")


class ShellCwdOutsideRoots(Exception):
    """A session tried to run somewhere no capability level covers."""


def _session_roots() -> tuple:
    """Where a session may set its working directory.

    The same two roots the seatbelt profile already carves out for writes. A
    session that could `cd` anywhere would run reads from the owner's whole
    home with a level rule that never considered it.
    """
    return (REPO, WORKSPACE)


def _resolve_cwd(raw: str | None, base: str) -> str:
    if not raw:
        return base
    cand = pathlib.Path(raw)
    if not cand.is_absolute():
        cand = pathlib.Path(base) / cand
    cand = cand.resolve()
    for root in _session_roots():
        try:
            cand.relative_to(pathlib.Path(root).resolve())
        except ValueError:
            continue
        if cand.is_dir():
            return str(cand)
        raise ShellCwdOutsideRoots(f"{cand} is not a directory")
    raise ShellCwdOutsideRoots(
        f"{cand} is outside every root a session may run in "
        f"({', '.join(str(r) for r in _session_roots())})")


def ui_open_level(args: dict) -> str:
    """Opening something FOR the owner, levelled on what it opens.

    A SEPARATE CAPABILITY BECAUSE `shell.run` CANNOT DO IT. Commands run under
    seatbelt, and the sandbox refuses to hand a file to LaunchServices --
    `open ~/Downloads/x.png` returns `_LSOpenURLsWithCompletionHandler()
    failed with error -54`. Measured 2026-09-04, when the owner asked VESPER to
    open an image and got "I tried and it did not go through".
    WIDENING THE SANDBOX FOR EVERY COMMAND WOULD HAVE BEEN THE WRONG FIX: this
    is one narrow door -- hand a path to the system's default handler -- rather
    than a general loosening of containment that every future command inherits.

    IT SHOWS, IT DOES NOT READ. Opening a file puts it on the owner's screen
    for the owner to look at; the contents never enter VESPER's context, so
    this cannot be a way to read a credential that `fs.read` would refuse. It
    is still levelled on the target, because putting a private file on screen
    in a room with other people in it is a disclosure even when VESPER is blind
    to it.
    """
    raw = str(args.get("path") or args.get("target") or "")
    if not raw:
        return "L5"
    low = raw.lower()
    if low.startswith(("http://", "https://")):
        return "L2"                       # a link the owner asked to see
    target = resolve(raw)
    # The same targets `fs.read` guards, judged the same way.
    return fs_read_level({"path": str(target)})


def ui_open(args: dict) -> dict:
    """Hand a path or URL to the system's default handler. Never reads it."""
    raw = str(args.get("path") or args.get("target") or "").strip()
    if not raw:
        raise ValueError("nothing to open")
    low = raw.lower()
    if low.startswith(("http://", "https://")):
        target = raw
    else:
        t = resolve(raw)
        if not t.exists():
            raise FileNotFoundError(str(t))
        target = str(t)
    # NOT UNDER SEATBELT, which is the entire reason this exists -- and the
    # argument is a single resolved path passed as one argv element, never a
    # shell string, so there is nothing here for a quoted command to escape.
    proc = subprocess.run(["/usr/bin/open", target], capture_output=True,
                          text=True, timeout=20, check=False)
    return {"opened": target, "exit_code": proc.returncode,
            "stderr": (proc.stderr or "").strip()[:300]}


# ---------------------------------------------------------------- windows
#
# THREE GATES, AND ALL THREE MUST SAY YES. `contracts/policy/host_actions.toml`
# says whether VESPER may move A window at all; `core/windows.py` says whether
# it may move THIS one; the capability level below says how much approval that
# costs. They are deliberately separate: the first is a vocabulary the checks
# read, the second is the owner's ownership rule, the third is the authorisation
# ladder every other capability already climbs. Merging any two of them would
# put policy somewhere no check looks.

VESPER_BIN = REPO / "app" / "VESPER.app" / "Contents" / "MacOS" / "VESPER"


def _window_bridge(*argv: str) -> dict:
    """Ask the app binary. A helper is a MODE of VESPER, never a loose script.

    WHY NOT A PYTHON LIBRARY. The accessibility interface answers for the
    process that asks, and TCC attributes a grant to the RESPONSIBLE process --
    which for anything the runtime spawns itself would be the runtime, or worse
    the shell that started it. `MEMORY.md` records this costing a whole grant
    trip once already: a microphone request from a terminal came back "granted"
    because it inherited the terminal's answer. Going through the bundle means
    the thing asking is the thing the owner granted.
    """
    if not VESPER_BIN.exists():
        raise FileNotFoundError(
            f"{VESPER_BIN} is not built -- window actions run as VESPER from "
            "the bundle, so there is nothing to ask")
    out = subprocess.run([str(VESPER_BIN), *argv], capture_output=True,
                         text=True, timeout=30, check=False)
    lines = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"the window bridge returned nothing readable: "
                     f"{(out.stderr or out.stdout or '')[:200]}")


def _inventory() -> tuple[list, str | None]:
    """Live windows as `core.windows.Window` records, and VESPER's Desktop.

    PROVENANCE IS READ FROM VESPER'S OWN RECORD, NEVER INFERRED FROM THE WINDOW.
    `core/windows.classify_opened` says why at length: every property a guess
    could use is one the owner can produce by accident, and a wrong guess in the
    permissive direction hands VESPER a window it may not touch. A window this
    process did not open is `unknown`, and `unknown` is treated as the owner's.
    """
    from core import windows as W

    raw = _window_bridge("--windows-list")
    desktop = raw.get("desktop_id")
    # VESPER'S DESKTOP, WHICH IS NOT THE ACTIVE ONE. The bridge answers `null`
    # unless VESPER's own ground is on the Space that is showing. Reading
    # `desktop_id` here instead -- as the first draft did -- makes every window
    # on screen "on vesper's desktop" and hands VESPER the owner's whole
    # session under clause 1 of the ownership rule.
    vespers = raw.get("vespers_desktop")
    # The bridge's `accessible` field is deliberately NOT consulted: it answers
    # yes while unable to enumerate a window. See `_act`, which diagnoses the
    # same condition from a failure instead.
    # CORROBORATED HERE, because this is the one place the live window list and
    # the recorded claims are both in hand. A claim is only ever turned into a
    # stamp against a window the bridge just reported.
    mine = set(_VESPER_OPENED_WINDOWS) | _corroborate(_load_opened(),
                                                      raw.get("windows", []))
    return ([W.Window(window_id=str(w["window_id"]), pid=int(w["pid"]),
                      app_label=str(w.get("app_label") or "?"),
                      desktop_id=str(w.get("desktop_id") or desktop or "?"),
                      provenance=(W.VESPER_OPENED if str(w["window_id"]) in mine
                                  else W.UNKNOWN),
                      meta={"x": w.get("x"), "y": w.get("y"),
                            "width": w.get("width"), "height": w.get("height")})
             for w in raw.get("windows", [])],
            vespers)


# Windows VESPER opened, in this process. NOT PERSISTED, for the reason
# `core/latency.py` refuses a persisted estimate: a provenance read off disk at
# startup is a claim about a previous run's windows, and window ids are reused.
# Forgetting means falling back to `unknown`, which is the owner's -- the safe
# direction, and the only one worth defaulting to.
_VESPER_OPENED_WINDOWS: set = set()


# THE SAME SET, SURVIVING A RESTART OF VESPER -- AND ONLY THAT.
#
# The comment above says a provenance read off disk is a claim about a previous
# run's windows and that window ids are reused. Half of that is right, and the
# half that is wrong is the half that matters: ids reset on a MACHINE boot, not
# on a VESPER restart. VESPER restarted a dozen times on 2026-09-08 with every
# window still open and every id still valid, and forgot them all each time.
#
# MEASURED on this host 2026-09-09, and re-measurable through the app's
# `--window-id-reuse-check`: window numbers are allocated monotonically and are
# NOT reused within a boot. 41 windows created and destroyed gave 41 distinct
# strictly increasing numbers, including 25 sequential open-close cycles. So if
# VESPER opened window 500, exited, the owner closed it and opened their own,
# theirs gets 501 or higher. A stale stamp can only ever match the window it was
# made for.
#
# WHICH IS WHY THE FILE IS A HINT AND NEVER A SOURCE OF TRUTH. Four conditions,
# all required, or the stamp resolves to `unknown` -- the owner's, the safe
# direction: the boot matches, the window is still live, the pid matches, and
# the application matches. Anything else -- a parse error, a missing field, a
# changed field -- resolves the same way. This restores authority over a window
# that demonstrably still exists; it can never invent any.
_OPENED_PATH = (pathlib.Path.home() / "Library" / "Application Support"
                / "VESPER" / "windows_opened.json")


def _boot_id() -> str:
    """This boot, as the key that invalidates everything across a reboot.

    ANCHORED ON THE FIELD, because `kern.boottime` reads
    `{ sec = 1788295195, usec = 476017 }` and a greedy match for `sec = ` finds
    `usec` -- which would still vary per boot and so would still *work*, while
    being the wrong number. It was written that way first.
    """
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"],
                             capture_output=True, text=True, timeout=5,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    import re as _re
    m = _re.search(r"\{\s*sec\s*=\s*(\d+)", out)
    return m.group(1) if m else ""


def _load_opened() -> list:
    """The recorded claims, or nothing. Never raises, never guesses."""
    try:
        doc = json.loads(_OPENED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    # A DIFFERENT BOOT DISCARDS THE WHOLE FILE, not entry by entry. Numbers
    # restart low at boot, so a stale entry for window 100 could match a window
    # the owner opened seconds into the new session -- the one case where the
    # monotonic guarantee does not hold, and the reason this key exists.
    if str(doc.get("boot_id") or "") != _boot_id() or not _boot_id():
        return []
    rows = doc.get("windows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save_opened(rows: list) -> None:
    """Write the claims atomically. A failure here loses memory, never safety."""
    try:
        _OPENED_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OPENED_PATH.with_name(f"windows_opened.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"boot_id": _boot_id(), "windows": rows},
                                  indent=1), encoding="utf-8")
        tmp.replace(_OPENED_PATH)
    except OSError:
        pass


def _corroborate(rows: list, live: list) -> set:
    """Which recorded claims does the world still support?

    `live` is what the bridge just reported. A claim survives only if the window
    is still there, under the same process, in the same application. Anything
    else is dropped rather than resolved generously.
    """
    by_id = {str(w.get("window_id")): w for w in live}
    out = set()
    for r in rows:
        wid = str(r.get("window_id") or "")
        w = by_id.get(wid)
        if w is None:
            continue                       # gone; a stamp for it claims nothing
        if str(w.get("pid")) != str(r.get("pid")):
            continue                       # same number, different process
        if str(w.get("app_label")) != str(r.get("app_label")):
            continue                       # same number, different application
        out.add(wid)
    return out


def _remember_opened(window_id: str, pid: Any, app_label: str) -> None:
    rows = [r for r in _load_opened()
            if str(r.get("window_id")) != str(window_id)]
    rows.append({"window_id": str(window_id), "pid": str(pid),
                 "app_label": str(app_label), "at_ms": int(time.time() * 1000)})
    _save_opened(rows[-64:])


def _forget_opened(window_id: str) -> None:
    _save_opened([r for r in _load_opened()
                  if str(r.get("window_id")) != str(window_id)])


def window_list(args: dict) -> dict:
    """Inventory. Reads no titles -- that is content and a separate decision."""
    from core import windows as W

    wins, desktop = _inventory()
    parts = W.partition(wins, vespers_desktop=desktop)
    return {"desktop_id": desktop,
            "count": len(wins),
            "may_arrange": len(parts["free"]),
            "needs_a_request": len(parts["on_request"]),
            "windows": [{"window_id": w.window_id, "pid": w.pid,
                         "app_label": w.app_label,
                         "provenance": w.provenance,
                         "line": W.describe(w, vespers_desktop=desktop),
                         **w.meta} for w in wins]}


def _log_touch(effect: str, w, out: dict, args: dict) -> None:
    """Record one interaction, scoped to windows VESPER actually touched.

    NOT THE OWNER'S WHOLE SESSION. The owner's scoping, and it is what keeps
    this from becoming a record of someone's week that VESPER had no business
    keeping -- as well as what bounds its size.

    A TITLE IS NOT READ HERE. `window_list` levels titles at L5 because a title
    is a document name or a subject line, and this runs under whatever level
    the ACT was authorised at. So the row carries the reason a title is absent
    rather than quietly reading one at the wrong level; a caller that has
    legitimately read a title can pass it.
    """
    from core import window_log as WL

    WL.record(window_id=str(getattr(w, "window_id", args.get("window_id", ""))),
              action=effect,
              app_label=str(getattr(w, "app_label", "")),
              pid=str(getattr(w, "pid", "")),
              desktop_id=str(getattr(w, "desktop_id", "")),
              provenance=str(getattr(w, "provenance", "")),
              geometry=dict(getattr(w, "meta", {}) or {}),
              title_absent=WL.UNREADABLE,
              task=str(args.get("task") or ""))


def _act(effect: str, args: dict, *argv: str) -> dict:
    """One place where the ownership rule is consulted, so it cannot be skipped.

    `owner_requested` IS PASSED IN BY THE CALLER AND IS NOT INFERRED HERE. The
    executor knows whether this step came from something the owner said; this
    function does not, and a function that decided for itself whether it had
    been asked would always be able to decide yes.
    """
    from core import windows as W

    wid = str(args.get("window_id") or "").strip()
    if not wid:
        raise ValueError("no window_id")
    wins, desktop = _inventory()
    target = next((w for w in wins if w.window_id == wid), None)
    if target is None:
        raise ValueError(f"window {wid} does not exist on any desktop, so it "
                         "cannot be judged or acted on")
    allowed, why = W.may_act(target, effect, vespers_desktop=desktop,
                             owner_requested=bool(args.get("owner_requested")))
    if not allowed:
        return {"ok": False, "refused_by": "ownership", "reason": why,
                "window": W.describe(target, vespers_desktop=desktop)}
    out = _window_bridge(*argv, "--window-id", wid, "--window-pid", str(target.pid))
    out.setdefault("window", W.describe(target, vespers_desktop=desktop))
    # RECORDED AFTER THE ACT, WITH WHAT WAS TRUE BEFORE IT.
    #
    # After, because an act that was refused by the ownership rule returns
    # above and is not an interaction with a window -- it is an interaction
    # with a rule. With the geometry from BEFORE, because that is the state the
    # owner would recognise if they later asked what vesper did to this window;
    # the state after is readable from the world at any time.
    _log_touch(effect, target, out, args)
    # ACCESSIBILITY IS DIAGNOSED FROM A FAILURE, NOT FROM ITS OWN REPORT.
    #
    # The first version of this flag asked the bridge whether accessibility was
    # granted. It answers YES while being unable to enumerate a single window:
    # `AXIsProcessTrusted()` reports the RESPONSIBLE process, which for a
    # helper launched from a terminal is the terminal, and `CLAUDE.md` records
    # that exact trap for the microphone. So the instrument's self-report is
    # worthless here and the discriminator is what actually happened -- an act
    # that failed with an empty accessibility tree for a window the window
    # server can see. That is a permission problem stated as a measurement.
    if not out.get("ok") and "ax=[]" in str(out.get("reason") or ""):
        out.setdefault("degraded", True)
        out.setdefault("flag_id", "host.accessibility")
        out.setdefault("flag",
                       "vesper cannot act on windows: the accessibility tree "
                       "came back empty for a window that is on screen, which "
                       "means macos accessibility is not granted to this build. "
                       "grant it in system settings > privacy & security > "
                       "accessibility. every rebuild of vesper revokes it.")
    return out


def window_move(args: dict) -> dict:
    return _act("move", args, "--window-act", "move",
                "--x", str(int(args["x"])), "--y", str(int(args["y"])))


def window_resize(args: dict) -> dict:
    return _act("resize", args, "--window-act", "resize",
                "--w", str(int(args["width"])), "--h", str(int(args["height"])))


def window_close(args: dict) -> dict:
    out = _act("close", args, "--window-act", "close")
    if out.get("ok"):
        _VESPER_OPENED_WINDOWS.discard(str(args.get("window_id")))
        # AND FROM THE FILE, or a closed window's number stays claimed until the
        # next reboot -- harmless while the number is unused, and wrong the
        # moment anything reads the record as history.
        _forget_opened(str(args.get("window_id")))
    return out


def window_open_level(args: dict) -> str:
    """Opening an application is L2; opening a FILE is levelled on the file.

    A window VESPER opens becomes a window VESPER may then rearrange and close
    without asking, so what goes into it matters. Launching an application
    shows nothing private. Putting one of the owner's files on screen is a
    disclosure whether or not VESPER reads it -- `ui_open_level` makes the same
    argument -- so the file's own sensitivity decides, and a credential is
    refused at L5 exactly as it would be there.
    """
    raw = str(args.get("path") or args.get("target") or "")
    if not raw:
        return "L2"
    return ui_open_level({"path": raw})


def window_list_level(args: dict) -> str:
    """Inventory is L1; asking for window TITLES is content, and refused there.

    A window title is a document name, a subject line, a message. The bridge
    does not read them and `host_actions.toml`'s observe tier is explicit that
    content is a new row and a new decision -- so the request levels at L5
    rather than being silently downgraded to the inventory it is not.
    """
    return "L5" if args.get("titles") else "L1"


def window_close_level(args: dict) -> str:
    """Closing VESPER's own window is L4; closing the owner's is L5.

    Nothing can undo either, which is why neither is below L4. What separates
    them is whose unsaved work is at stake.
    """
    from core import windows as W

    return "L4" if args.get("provenance") == W.VESPER_OPENED else "L5"


def window_open(args: dict) -> dict:
    """Open something as a window VESPER OWNS.

    THIS IS WHAT MAKES PROVENANCE REAL, and without it the owner's second
    sentence -- "windows opened by vesper can be totally managed by vesper" --
    was dead code. `_VESPER_OPENED_WINDOWS` had exactly one writer, on the
    rebuild path, which had never run. So every window in the inventory read
    `unknown`, every `unknown` resolves to the owner's, and clause 2 of the
    ownership rule was unreachable in production while passing every test.

    DIFFERENT FROM `ui.open`, AND THE DIFFERENCE IS THE POINT. `ui.open` hands
    a path to the system's default handler so the OWNER can look at it, and the
    window that appears is theirs. This one records that VESPER caused the
    window, which is what later authorises VESPER to move, resize or close it
    without asking. Same mechanism underneath, different consequence -- so they
    are separate capabilities rather than a flag, because a flag on a
    capability the owner has already approved is a way to acquire authority
    quietly.

    THE STAMP IS TAKEN FROM WHAT ACTUALLY APPEARED, never from what was asked
    for. `core/windows.classify_opened` insists on this: the only thing that
    knows VESPER opened a window is the code that did the opening, and it knows
    it by watching a window that was not there before appear.
    """
    from core import windows as W

    app = str(args.get("app") or "").strip()
    path = str(args.get("path") or args.get("target") or "").strip()
    if not app and not path:
        raise ValueError("nothing to open")

    # VESPER DOES NOT CREATE WINDOWS ON A DESKTOP IT DOES NOT OWN.
    #
    # A new window appears WHERE THE SYSTEM DECIDES, and this guard used to say
    # "on whichever Desktop is showing". That is false: on 2026-09-09 a window
    # this function created never appeared on the active Desktop, and the owner
    # found it on another one. What decides placement is NOT established -- a
    # later run put a fresh window on the active Desktop -- and the fix does not
    # depend on knowing. The guard is kept because it removes the common case
    # and costs nothing, but it does NOT guarantee placement; only the readback
    # after opening does, and this function now performs one. If it lands on the
    # owner's Desktop, VESPER has just
    # put something into their workspace uninvited --
    # and then, because the ownership rule's clause 1 does not apply there, it
    # cannot tidy it away again either. The owner's whole framing is that their
    # Desktop is theirs; adding to it unasked is the same trespass as
    # rearranging it unasked, and it is easier to do by accident.
    #
    # An explicit request lifts this, because then it is not uninvited.
    wins, vespers = _inventory()
    if not vespers and not args.get("owner_requested"):
        return {"ok": False, "refused_by": "ownership",
                "reason": "vesper's desktop is not the one showing, so a new "
                          "window would land in your workspace. Ask for it and "
                          "it will open here."}

    before = {w.window_id for w in wins}
    if app:
        bundle = _bundle_for(app)
        if not bundle:
            raise ValueError(f"no application matching {app!r} on this machine")
        out = _window_bridge("--window-act", "reopen", "--window-id", "0",
                             "--window-pid", "0", "--bundle", bundle)
        if not out.get("ok"):
            return {"ok": False, "reason": out.get("reason") or "it did not open"}
        new_id = str(out.get("window_id"))
    else:
        ui_open({"path": path})
        # RE-READ, because `open` exiting 0 is not a window. The handler may
        # hand the file to an application that was already showing it, in which
        # case nothing new appeared and nothing may be claimed.
        new_id = ""
        for _ in range(20):
            time.sleep(0.15)
            fresh = [w for w in _inventory()[0] if w.window_id not in before]
            if fresh:
                new_id = fresh[0].window_id
                break
        if not new_id:
            return {"ok": False, "reason": "the system opened no new window -- it "
                    "was likely already showing, and a window VESPER did not "
                    "create is not VESPER's to claim"}

    _VESPER_OPENED_WINDOWS.add(new_id)
    # WAIT FOR THE WINDOW TO BE LISTED, DO NOT READ ONCE AND CONCLUDE.
    #
    # The bridge returning a window id means the window server accepted the
    # creation, not that `CGWindowListCopyWindowInfo` already reports it.
    # Measured 2026-09-09: at 0.0 s the window is absent from the listing and at
    # 0.3 s it is there. Reading once therefore found nothing and reported
    # `landed: off_vespers_desktop, degraded: true` -- a flag raised about a
    # window that was sitting exactly where it should be. That is the same
    # too-early read that made the ground retraction control report a failure
    # earlier the same night, and the same answer applies: poll for the fact
    # rather than assume how long it takes to become one.
    wins, vespers, made = [], None, None
    for _ in range(20):
        wins, vespers = _inventory()
        made = next((w for w in wins if w.window_id == new_id), None)
        if made is not None:
            break
        time.sleep(0.1)
    # RECORDED WITH WHAT THE WORLD SAYS, not with what was asked for. The pid
    # and application come from the window that actually appeared, because those
    # are the two fields a later run corroborates against -- recording the
    # requested application would make the check compare a claim to itself.
    if made is not None:
        _remember_opened(new_id, made.pid, made.app_label)
    if made is None:
        # THE WINDOW OPENED AND IT IS NOT HERE, AND THAT IS NOT A SUCCESS.
        #
        # This returned `ok: True` with an empty line whenever the window could
        # not be found, which reads as "opened, nothing to report" and is the
        # opposite of what happened. The owner found it on 2026-09-09: "they
        # opened in desktop 1 not 2 (the empty one)".
        #
        # THE ASSUMPTION THIS FUNCTION WAS BUILT ON IS FALSE. Its own comment
        # says a new window appears on whichever Desktop is showing. Measured
        # the same night: TextEdit with ZERO windows open, launched while a
        # different Desktop was active, put its window on Desktop 1 where it had
        # last been used. So the guard above -- refuse unless VESPER's Desktop is
        # showing -- does not achieve what it claims, and the trespass it exists
        # to prevent is reachable straight through it.
        #
        # The honest report is that VESPER opened something into the owner's
        # workspace and cannot even tidy it away: every act in the bridge matches
        # its target through `SpaceWatch.onScreen()`, which sees only the active
        # Desktop, so a window that landed elsewhere cannot be moved, resized or
        # closed. Rebuilding it in place is the owner's instruction and is owed
        # (HOME-WORKBENCH §11.1c); it needs a bridge that can reach a window on
        # another Desktop, and it must attempt ONCE and then flag rather than
        # retry, because placement may be sticky.
        return {"ok": True, "degraded": True, "window_id": new_id,
                "provenance": W.classify_opened(by_vesper=True),
                "landed": "off_vespers_desktop",
                "flag": "vesper opened a window and the system placed it on "
                        "another desktop, where vesper cannot reach it to move "
                        "or close it. it is yours to close.",
                "line": ""}
    return {"ok": True, "window_id": new_id,
            "provenance": W.classify_opened(by_vesper=True),
            "landed": "vespers_desktop" if vespers else "active_desktop",
            "line": W.describe(made, vespers_desktop=vespers),
            **made.meta}


def _bundle_for(name: str) -> str:
    """An application's bundle id from the name the owner used.

    A LABEL IN, AN IDENTIFIER OUT, and the label never travels further.
    INV-HW-1 forbids a product name in a routing, resource or policy path;
    resolving one the owner typed into an identifier at the boundary is exactly
    how that rule is kept while still letting them say "open the notes app".
    """
    out = subprocess.run(["/usr/bin/osascript", "-e", f'id of application "{name}"'],
                         capture_output=True, text=True, timeout=15, check=False)
    return (out.stdout or "").strip()


def window_relocate(args: dict) -> dict:
    """Move a window to another Desktop, degrading rather than failing.

    THE OWNER'S LADDER, 2026-09-08, verbatim: *"if it breaks, we'll have a
    backup, vesper flags it, if it's redoable, it should retry, if not it should
    do it manually, screenshot, identify window/app/place, then close that
    window and opens another one in it's desktop, same app, same place."*

    So four rungs, and the point of writing them here rather than in the Swift
    is that retry-then-degrade is a POLICY decision. The bridge is mechanism: it
    moves, it reads back, it reports. What to do about a failure is this side's
    business, and keeping it here means the ladder is testable without a Mac.

      1. **Move.** The private call reports nothing, so the bridge reads the
         window's Space back and compares. That readback IS the rung.
      2. **Retry once, and only for a failure that could differ.** A missing
         symbol will still be missing a second later; retrying it burns the
         owner's time to produce the same sentence. A move that simply did not
         land can differ, so that one is retried.
      3. **Reconstruct.** Identify the application and the geometry, close the
         window, open a fresh one in the same place. The owner's own fallback,
         and it is PUBLIC API only -- which is the whole reason it survives the
         private symbol disappearing.
      4. **Flag, on every path including success-after-retry.** A degradation
         nobody is told about is a system quietly getting worse.

    TWO THINGS THE FALLBACK REFUSES, AND BOTH MATTER.

    It will not close a window with unsaved work, and it treats "the
    application would not say" as unsaved. `host_actions.toml` keeps
    `close_window` outside the owner's authorisation precisely because nothing
    recovers what was in it.

    And it cannot choose the Desktop a rebuilt window lands on. This said "a new
    window opens on the CURRENT Space"; observed 2026-09-09, that is false -- a
    window created here never appeared on the active Desktop. What DOES decide
    placement is not established, so nothing may be inferred from it either way.
    So requiring VESPER's Desktop to be showing is necessary and NOT
    sufficient, the rebuild must READ BACK where the replacement landed, and it
    must attempt once and then flag rather than retry: if placement is sticky, a
    retry loop reopens onto the wrong Desktop forever.
    """
    from core import windows as W

    wid = str(args.get("window_id") or "").strip()
    space = str(args.get("space") or "").strip()
    notes: list = []
    wins, vespers = _inventory()
    target = next((w for w in wins if w.window_id == wid), None)
    if target is None:
        raise ValueError(f"window {wid} is not on the active desktop")

    # THE OWNERSHIP RULE FIRST, and relocation has its own effect for a reason
    # `core/windows.py` sets out at length: moving a window off VESPER's Desktop
    # spends authority it only holds while the window is there.
    effect = (W.RELOCATE_OFF
              if vespers and target.desktop_id == vespers else W.MOVE)
    allowed, why = W.may_act(target, effect, vespers_desktop=vespers,
                             owner_requested=bool(args.get("owner_requested")))
    if not allowed:
        return {"ok": False, "refused_by": "ownership", "reason": why}

    # --------------------------------------------------------------- rung 1
    out = _window_bridge("--window-act", "relocate", "--window-id", wid,
                         "--window-pid", str(target.pid), "--space", space)
    if out.get("ok"):
        return {**out, "rung": "moved", "notes": notes}

    # --------------------------------------------------------------- rung 2
    # RETRIED ONLY WHERE A SECOND ATTEMPT COULD DIFFER. A resolved-symbol
    # failure is a property of this macOS and will hold for the next call too.
    #
    # AND MEASURED 2026-09-08, THE BOUNDARY IS OWNERSHIP OF THE CONNECTION, NOT
    # THE SYMBOL. VESPER's own probe window relocates correctly -- "was unknown,
    # asked for 3, is 3" -- while a foreign application's window does not move
    # for `CGSMoveWindowsToManagedSpace` OR for the older add/remove pair. So
    # the private route serves VESPER's own surfaces and the owner's rebuild
    # ladder is not a degraded path for foreign windows, it is the ONLY path.
    reason = str(out.get("reason") or "")
    retryable = "MISSING" not in reason and "UNAVAILABLE" not in reason
    notes.append(f"the move did not land: {reason[:160]}")
    if retryable:
        again = _window_bridge("--window-act", "relocate", "--window-id", wid,
                               "--window-pid", str(target.pid), "--space", space)
        if again.get("ok"):
            notes.append("it landed on the second attempt")
            return {**again, "rung": "moved_after_retry", "notes": notes}
        notes.append("the retry did not land either")
    else:
        notes.append("not retried: the private call is unavailable on this "
                     "macOS, so a second attempt produces the same answer")

    # --------------------------------------------------------------- rung 3
    if not vespers:
        notes.append("the fallback needs VESPER's Desktop to be the one showing "
                     "-- a new window opens on the current Space, and switching "
                     "Space is the same capability that just failed")
        return {"ok": False, "rung": "cannot_degrade", "notes": notes,
                "degraded": True,
                "flag": "vesper could not move a window to another desktop: the "
                        "system refuses the move for windows it does not own, "
                        "and the rebuild needs vesper's desktop to be showing.",
                "reason": "cross-Desktop relocation is unavailable and the "
                          "rebuild fallback cannot reach VESPER's Desktop from here"}

    ident = _window_bridge("--window-act", "identity", "--window-id", wid,
                           "--window-pid", str(target.pid))
    if ident.get("edited") != "no":
        notes.append(f"the rebuild was refused: unsaved work is "
                     f"{ident.get('edited')!r}")
        return {"ok": False, "rung": "refused_unsaved", "notes": notes,
                "degraded": True,
                "flag": "vesper stopped short of rebuilding a window because it "
                        "holds unsaved work, or the application would not say. "
                        "nothing recovers what is inside a window it closes.",
                "reason": "this window has unsaved work, or the application "
                          "would not say -- rebuilding it means closing it, and "
                          "nothing recovers what was inside"}

    closed = _window_bridge("--window-act", "close", "--window-id", wid,
                            "--window-pid", str(target.pid))
    if not closed.get("ok"):
        notes.append(f"the window would not close: {str(closed.get('reason'))[:120]}")
        return {"ok": False, "rung": "rebuild_failed", "notes": notes,
                "degraded": True,
                "flag": "vesper could not close a window it was rebuilding, so "
                        "the window is where it was and the move did not happen.",
                "reason": "the rebuild could not close the original window"}

    fresh = _window_bridge("--window-act", "reopen", "--window-id", wid,
                           "--window-pid", str(target.pid),
                           "--bundle", str(ident.get("bundle_id") or ""))
    if not fresh.get("ok"):
        notes.append(f"the application did not reopen: {str(fresh.get('reason'))[:140]}")
        return {"ok": False, "rung": "rebuild_failed", "notes": notes,
                "degraded": True,
                "flag": "vesper closed a window to rebuild it and the "
                        "application opened no replacement. the window is gone "
                        "and nothing took its place.",
                "reason": "the original window was closed and the application "
                          "opened no replacement -- say so plainly rather than "
                          "leaving the owner to notice"}

    new_id = str(fresh.get("window_id"))
    _VESPER_OPENED_WINDOWS.add(new_id)
    _window_bridge("--window-act", "move", "--window-id", new_id,
                   "--window-pid", str(fresh.get("pid")),
                   "--x", str(ident.get("x", 0)), "--y", str(ident.get("y", 0)))
    placed = _window_bridge("--window-act", "resize", "--window-id", new_id,
                            "--window-pid", str(fresh.get("pid")),
                            "--w", str(ident.get("width", 0)),
                            "--h", str(ident.get("height", 0)))
    notes.append("rebuilt: same application, same place, on vesper's desktop")
    return {"ok": True, "rung": "rebuilt", "window_id": new_id,
            "app_label": ident.get("app_label"), "geometry": placed.get("after"),
            "notes": notes,
            # THE DEGRADATION IS PART OF THE RESULT, not a log line. The owner
            # asked to be flagged, and a caller that only reads `ok` would
            # otherwise report a rebuild as an ordinary move.
            "degraded": True}


def window_level(args: dict) -> str:
    """How much approval moving this window costs.

    LEVELLED ON WHOSE WINDOW IT IS, which is the only thing that changes the
    stakes. Rearranging what VESPER put on its own Desktop is housekeeping;
    reaching into the owner's working window is not, even when the ownership
    rule permits it. CLOSING IS L4 IN EVERY CASE because it cannot be undone --
    the same reasoning `host_actions.toml` applies when it refuses to let
    anything irreversible be pre-authorised.
    """
    from core import windows as W

    effect = str(args.get("effect") or "move")
    if effect == W.CLOSE:
        return "L4"
    return "L2" if args.get("provenance") == W.VESPER_OPENED else "L3"


def shell_session(session_id: str) -> dict:
    """Read one session's carried context. Read-only; for callers and checks."""
    st = _SHELL_SESSIONS.get(session_id)
    return {"cwd": st["cwd"], "env": dict(st["env"])} if st else {}


# --------------------------------------------------------------- prohibited

# Directory names that hold VESPER's own account of what it did, the undo
# behind it, and the token that says it may act at all. Matched as PATH
# SEGMENTS rather than substrings, so a document called "shadow puppets.txt" is
# not caught by a rule about the shadow store.
#
# `interlock` IS THE ENFORCEABLE HALF OF THE DEAD-MAN'S SWITCH. The design says
# the minting key is unreachable from the runtime, and on one machine under one
# uid that is not something the OS enforces. What IS enforced is this: a
# steered proposer cannot write itself an enable token, because `fs.write` and
# `fs.edit` refuse this path at every level including under an L5 grant.
SELF_DEFEATING_DIRS = ("shadow", "events", "audit", "interlock")


def prohibited(capability_id: str, args: dict) -> str | None:
    """The reason this act is refused outright, or None.

    THE TIER OUR LADDER DID NOT HAVE. L5 was the top, and an L5 grant plus an
    L5 declaration authorised an L5 action -- so every safety property in this
    system was contingent on one spoken "yes", from someone who may be half
    asleep, to a request produced by a proposer we have already agreed we
    cannot trust. Claude Code's own operating rules carry the sentence ours was
    missing: these stay prohibited when the user explicitly asks for them,
    supplies all the details, or says they authorize it.

    THE SET IS TINY ON PURPOSE, and the test for membership is not "dangerous"
    -- it is SELF-DEFEATING. Deleting the owner's holiday photos is a
    catastrophe and it belongs on the ladder, where the owner can consent to
    it. Erasing the record of what VESPER did, or the undo behind it, or
    reading the credential store into a model's context, are different: they do
    not need the owner's judgement to be wrong, they remove the machinery that
    would have caught it. A grant that can turn off the thing that records
    grants is not a grant.

    NOT A REPLACEMENT FOR THE LADDER. Everything here is already L5. This is
    the answer to "and what if the owner says yes anyway".
    """
    args = args or {}
    if capability_id in ("fs.write", "fs.edit"):
        raw = _norm(args.get("path"))
        if not raw:
            return None
        target = resolve(raw)
        parts = {q.lower() for q in target.parts}
        if _under(target, WORKSPACE.parent) and parts & set(SELF_DEFEATING_DIRS):
            return ("this would write inside VESPER's own record of what it "
                    "did, or the undo behind it")
    if capability_id == "fs.read":
        raw = _norm(args.get("path"))
        if raw and any(m in str(resolve(raw)).lower() for m in SECRET_MARKERS):
            # READING IS THE STEP THAT PUTS IT IN A CONTEXT WINDOW, which is
            # where it leaves. The ladder already says L5; this says that no
            # answer to that question is yes.
            return "this would read a credential into a model's context"
    return None


# ------------------------------------------------------------ fs.read/write


class StaleWrite(Exception):
    """The file changed between being read and being written.

    Deliberately an exception rather than a level: a refusal that the ladder
    could raise past would be no refusal at all, and there is no confirmation
    that makes a write against vanished content correct.
    """


# Paths whose contents are credentials. Named as a CLASS, not as a list of
# products (INV-HW-1): what makes these special is that they hold secrets, not
# which tool wrote them.
SECRET_MARKERS = ("secrets", "credential", "token", ".env", "id_rsa",
                  ".ssh", "keychain", "password", "api_key", "apikey")

# Contract and specification trees. Editing these is editing the rules the
# system is judged against, which is an owner-administrative act by definition.
GOVERNED_PREFIXES = ("contracts/", "spec/", "verification/", "docs/COC/",
                     "tools/ci/")


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


# HOW MANY FILES ONE READ MAY NAME. Bounded because the proposer chooses the
# list: an unbounded batch is a way to pull the whole repo into a context window
# in one step, which is the opposite of what a step budget is for.
MAX_READ_BATCH = 8


def _read_paths(args: dict) -> list:
    """The paths a read names, whether it named one or several."""
    many = args.get("paths")
    if isinstance(many, (list, tuple)):
        return [p for p in many if _norm(p)]
    one = _norm(args.get("path"))
    return [one] if one else []


def fs_read_level(args: dict) -> str:
    """Levelled on the RESOLVED target, never on the string that named it.

    A BATCH IS LEVELLED AT ITS WORST MEMBER. Reading four files in one action
    must not be a way to read the expensive one cheaply: one credential path
    among seven innocuous ones makes the whole batch L5, exactly as
    `shell_level` already does for the path arguments of a command. Averaging,
    or levelling on the first, would make burying the target the technique.
    """
    batch = _read_paths(args)
    if len(batch) > 1:
        if len(batch) > MAX_READ_BATCH:
            return "L5"
        worst = "L1"
        for one in batch:
            worst = _worst(worst, fs_read_level({"path": one}))
        return worst

    raw = _norm(args.get("path")) or (batch[0] if batch else "")
    if not raw:
        return "L5"
    target = resolve(raw)
    if _escapes(raw, target):
        return "L5"
    p = str(target).lower()
    if any(m in p for m in SECRET_MARKERS):
        # READING a credential is not a lesser act than writing one. It is the
        # step that puts it in a context window, which is where it leaves.
        return "L5"
    if p.startswith(("/etc", "/private/etc", "/var/db", "/library/keychains")):
        return "L3"
    if _under(target, WORKSPACE) or _under(target, REPO):
        return "L1"
    # Anywhere else on the machine is somebody's private business. Reading it is
    # a question, not a default.
    return "L3"


def fs_write_level(args: dict) -> str:
    """Levelled on the RESOLVED target, never on the string that named it."""
    raw = _norm(args.get("path"))
    if not raw:
        return "L5"
    target = resolve(raw)
    if _escapes(raw, target):
        return "L5"
    p = str(target).lower()
    if any(m in p for m in SECRET_MARKERS):
        return "L5"
    # GOVERNED IS ASKED OF THE ABSOLUTE PATH, so it still fires once the prefix
    # has been resolved away: `contracts/` becomes `<repo>/contracts/`.
    if any(f"/{g}" in p for g in GOVERNED_PREFIXES):
        return "L5"
    if _under(target, WORKSPACE):
        # VESPER'S OWN SCRATCH SPACE, AND THE ONE PLACE A BLIND OVERWRITE IS
        # NOT ESCALATED BELOW. Overwriting its own notes is not destroying the
        # owner's data, and making it ask would put a confirmation in front of
        # the most ordinary thing it does. This carve-out is the weaker half of
        # the argument and it is written down as such: it holds because the
        # shadow-git checkpoint makes workspace writes recoverable. If that is
        # not built, this line should be revisited rather than inherited.
        return "L2"

    # A BLIND OVERWRITE OF THE OWNER'S DATA IS NOT THE SAME ACT AS CREATING A
    # FILE. `fs.write` would open an existing path, keep the previous bytes for
    # the compensator, and replace them -- and `verify_fs_write` would then
    # confirm, correctly, that the new content is on disk. Every instrument
    # pointed at it reported success. Nothing anywhere established that the
    # thing being destroyed had ever been looked at.
    #
    # The mechanism is the structural one rather than a "has this been read"
    # flag, because INV-AUTH-5 requires the declared level to be a function of
    # the ARGUMENTS: a turn-scoped read set is state, and state in a level rule
    # breaks the invariant. `expect_sha256` is an argument. Codex reaches the
    # same property from the other side -- its patch format carries the context
    # lines it replaces, so a blind write is unrepresentable rather than
    # refused.
    #
    # L4 AND NOT L3: L4 is never delegable and is consumed by the single action
    # it was granted for, which is the right weight for replacing something the
    # owner has and VESPER has not read.
    if target.exists() and not str(args.get("expect_sha256") or "").strip():
        return "L4"
    return "L3"


def fs_read(args: dict) -> dict:
    """Read one file, or several in one action.

    SEVERAL PATHS, ONE ACTION -- NOT SEVERAL ACTIONS IN PARALLEL. The value
    wanted from "parallel independent calls" is not concurrency, it is not
    spending four of six steps looking at four files. Doing it as one action
    keeps every property the loop rests on: ONE observation, so `INV-ACT-3`'s
    ceiling drops once and after all of it rather than racing; ONE step against
    the budget, so reading widely does not quietly buy a bigger one; and no
    concurrent writes, so `ShadowGit` still has a meaningful "previous" to
    restore. `core/intent.py` also stays object-only, which it chose
    deliberately -- "an array here would mean the model answered a different
    question than the one asked".

    EACH FILE VOUCHES ONLY FOR ITSELF. A batch of four where one was truncated
    returns three tokens and one refusal to vouch, never a blanket claim over
    all four.
    """
    if isinstance(args.get("paths"), (list, tuple)):
        batch = _read_paths(args)
        if len(batch) > MAX_READ_BATCH:
            raise ValueError(
                f"{len(batch)} paths in one read; the limit is "
                f"{MAX_READ_BATCH}. A read that can name any number of files is "
                "a way to pull a whole tree into one context window.")
        files = [fs_read({**args, "paths": None, "path": one}) for one in batch]
        return {"files": files, "count": len(files),
                "paths": [f["path"] for f in files],
                # THE BATCH IS COMPLETE ONLY IF EVERY MEMBER WAS. A caller
                # reading this to decide whether it has "seen" the set gets one
                # honest answer rather than having to check each.
                "complete": all(f.get("complete") for f in files),
                "bytes": sum(f.get("bytes") or 0 for f in files)}
    """Read, and hand back the hash of the WHOLE file.

    `sha256` is over the bytes on disk, NOT over the truncated text returned --
    it is the token `fs.write` demands back as `expect_sha256`, so hashing the
    excerpt would let a 20 KB limit silently authorise an overwrite of a 2 MB
    file that was never seen past its first page.
    """
    path = resolve(args.get("path"))
    limit = int(args.get("limit") or 20000)
    raw = path.read_bytes()
    whole = raw.decode("utf-8", errors="replace")

    # AN OFFSET, BECAUSE THE SECOND PAGE WAS UNREACHABLE. Without one, a file
    # longer than the limit could only ever be read from the top: VESPER saw
    # `truncated: true` and had no way to ask for the rest, so a long log or a
    # large source file was permanently a first page. Codex and Claude Code
    # both offer this and the reason is the same -- a bounded window is only
    # useful if it can move.
    #
    # LINES, NOT BYTES. A byte offset can land mid-character and mid-line, and
    # an excerpt starting halfway through a line is a fragment the reader has
    # to guess the shape of. Lines are what the owner and the model both talk
    # about, and what `fs.edit` matches on.
    offset = max(0, int(args.get("offset") or 0))
    if offset:
        lines = whole.splitlines(keepends=True)
        whole = "".join(lines[offset:])
    text = whole[:limit]

    # A PARTIAL READ HANDS BACK NO TOKEN, and this closes a hole rather than
    # adding a rule. `expect_sha256` drops a whole-file overwrite from L4 to L3,
    # and `fs_write_level` says exactly what that buys: "Nothing anywhere
    # established that the thing being destroyed had ever been looked at." The
    # hash was over the WHOLE file even when the read was truncated -- so
    # reading the first page of a 2 MB file returned the token meaning "I have
    # seen this", and the owner's confirmation was skipped for a file VESPER had
    # seen a hundredth of. The `limit` made that reachable already; an offset
    # would have made it easy.
    #
    # SO THE TOKEN IS ISSUED ONLY FOR A COMPLETE READ. Wanting to replace a
    # whole file at the lower level now requires having read the whole file,
    # which is what the invariant meant in the first place. A partial read
    # still reports the size and the line count -- enough to ask for the rest --
    # and `sha256` is None, so a proposer copying it into `expect_sha256`
    # produces no token and the write asks the owner instead.
    complete = offset == 0 and len(whole) <= limit
    out = {"path": str(path), "text": text, "bytes": path.stat().st_size,
           "offset": offset,
           "lines_total": len(raw.decode("utf-8", "replace").splitlines()),
           "truncated": len(whole) > limit,
           "complete": complete}
    if complete:
        out["sha256"] = hashlib.sha256(raw).hexdigest()
    else:
        out["sha256"] = None
        out["sha256_withheld"] = (
            "this read did not cover the whole file, so it carries no proof "
            "the file was seen. Read it whole to overwrite it without asking.")
    return out


def fs_write(args: dict) -> dict:
    """Write, and report the hash of what was INTENDED.

    The verifier below re-reads the file and computes the hash of what is
    actually on disk. Returning the intended hash here is what makes the
    comparison meaningful: if this returned the hash of what it read back, the
    actor would be grading its own homework and the two values could never
    disagree.
    """
    path = resolve(args.get("path"))
    content = str(args.get("content") or "")
    expect = str(args.get("expect_sha256") or "").strip().lower()

    # THE STALE CASE IS REFUSED HERE AND NOT ON THE LADDER, because it is not
    # the owner's to wave through. A missing `expect_sha256` is a question --
    # "replace a file you have not read?" -- and L4 asks it. A WRONG one is not
    # a question: the proposal was formed against content that is no longer
    # there, so confirming it would be confirming an intent that has stopped
    # describing the world. An L5 grant does not make a stale write correct.
    if path.exists() and expect:
        on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
        if on_disk != expect:
            raise StaleWrite(
                f"{path} has changed since it was read: expected {expect[:12]}..., "
                f"found {on_disk[:12]}.... The write was planned against content "
                "that is no longer on disk. Read it again and decide again.")

    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(content, encoding="utf-8")
    return {"path": str(path),
            "intended_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "had_previous": previous is not None,
            "previous": previous}


def fs_write_compensator(args: dict, result: Any) -> dict:
    """The counter-action, required at bind time because writes are compensatable.

    Restoring the previous bytes is not the same as never having written -- an
    fsevent fired, a watcher may have run -- which is exactly why the
    reversibility is `compensatable` and not `reversible`.
    """
    path = resolve(args.get("path"))
    prev = (result or {}).get("previous")
    if prev is None:
        path.unlink(missing_ok=True)
        return {"restored": "absent"}
    path.write_text(prev, encoding="utf-8")
    return {"restored": "previous_contents"}


def verify_fs_write(result: dict) -> dict:
    """READ THE WORLD BACK. The actor's claim is not consulted.

    A-013 asks for a result verified independently of the actor's claim, and
    this is the cheapest honest form of it: the bytes are on a disk, so go and
    look at the disk.
    """
    path = pathlib.Path(str((result or {}).get("path") or ""))
    if not path.exists():
        return {"verified": False,
                "why": "the file the write claims to have created is not there"}
    on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
    intended = (result or {}).get("intended_sha256")
    return {"verified": on_disk == intended,
            "on_disk_sha256": on_disk,
            "intended_sha256": intended,
            "why": "" if on_disk == intended else
                   "what is on disk is not what the write says it wrote"}


# ---------------------------------------------------------------- fs.edit


class EditNotUnique(Exception):
    """The text to replace matched zero times, or more than once."""


# How a match is looked for, in decreasing strictness. Taken from Codex's
# `seek_sequence`, which tries exact, then ignoring trailing whitespace, then
# ignoring both ends -- because a model reproducing a block of code reliably
# gets the content right and the indentation wrong.
#
# THE LADDER WIDENS HOW A MATCH IS FOUND AND NEVER HOW MANY IT MAY HIT. Aider's
# `search_and_replace` has its uniqueness check commented out and calls
# `str.replace`, which replaces EVERY occurrence. For an interactive tool with
# a git undo one keystroke away that is a reasonable trade; for an assistant
# acting unattended at three in the morning it is not. Each rung here still
# demands exactly one match and refuses otherwise.
# `replace_all` IS SPECIFIED BY THE TOOLS THIS BORROWED FROM AND IS DELIBERATELY
# NOT BUILT. Named here so the gap is visible in the code rather than only in a
# decision nobody re-reads.
#
# THE REASON IS THE LADDER, NOT TASTE. `fs.write` escalates to L4 when it would
# replace a file the turn cannot show it has read, and `fs.edit` is exempt for a
# specific reason: an edit cannot be authored without knowing the content,
# because `old` has to match what is on disk -- so producing one IS the
# evidence. Matching exactly one place is what makes that argument hold.
#
# `replace_all` breaks it in the middle. Matching six places proves the author
# knew ONE context and guessed that the other five are like it; the edit then
# changes all six at the cheaper level that unique-match paid for. That is the
# escalation exemption being spent on places nobody looked at -- which is the
# same shape as `fs.write` on an unread file, arriving through the door that was
# opened because it could not happen here.
#
# WHAT TO DO INSTEAD, when it is genuinely wanted: read the file, then write it
# whole with `expect_sha256`. That costs L3 and it costs having actually read
# the thing being changed, which is the price the ladder is asking for.
REPLACE_ALL_NOT_BUILT = "replace_all"

EDIT_STRATEGIES = (
    ("exact", lambda ln: ln),
    ("ignoring trailing whitespace", lambda ln: ln.rstrip()),
    ("ignoring indentation", lambda ln: ln.strip()),
)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _shift(line: str, delta: int) -> str:
    """Move one line by `delta` columns, never past its own indentation."""
    if not line.strip():
        return line
    if delta > 0:
        return " " * delta + line
    return line[min(-delta, _indent_of(line)):]


def fs_edit_level(args: dict) -> str:
    """An edit levels like a write, MINUS the blind-overwrite escalation.

    `fs.write` escalates to L4 when it would replace a file the turn cannot
    show it has read. An edit cannot be authored without knowing the content:
    `old` has to match what is on disk, so producing one is itself the evidence
    that `expect_sha256` exists to demand. That is the whole reason to have a
    surgical edit rather than a whole-file replacement -- it makes the safe
    thing the easy thing, instead of the thing you have to remember.

    Everything else about a write still applies: credentials and governed trees
    are L5 whether the change is surgical or not.
    """
    raw = _norm(args.get("path"))
    if not raw:
        return "L5"
    if not str(args.get("old") or ""):
        # An edit with nothing to match is a whole-file write wearing the level
        # of a surgical one, and it is the obvious way around this rule.
        return "L5"
    target = resolve(raw)
    if _escapes(raw, target):
        return "L5"
    p = str(target).lower()
    if any(m in p for m in SECRET_MARKERS):
        return "L5"
    if any(f"/{g}" in p for g in GOVERNED_PREFIXES):
        return "L5"
    if _under(target, WORKSPACE):
        return "L2"
    return "L3"


def _locate(text: str, old: str) -> tuple:
    """(start, end, how) for the ONE place `old` occurs, or raise."""
    for how, norm in EDIT_STRATEGIES:
        hay = [norm(ln) for ln in text.splitlines()]
        needle = [norm(ln) for ln in old.splitlines()]
        if not needle:
            raise EditNotUnique("there is no text to replace")
        if len(needle) > len(hay):
            continue
        hits = [i for i in range(len(hay) - len(needle) + 1)
                if hay[i:i + len(needle)] == needle]
        if len(hits) == 1:
            return hits[0], hits[0] + len(needle), how
        if len(hits) > 1:
            # AMBIGUOUS IS REFUSED HERE RATHER THAN LOOSENED FURTHER. A later,
            # more forgiving rung can only ever match more places, so carrying
            # on would trade a refusal for a guess.
            raise EditNotUnique(
                f"the text to replace occurs {len(hits)} times ({how}). An edit "
                "must name one place; give more surrounding lines.")
    raise EditNotUnique(
        "the text to replace was not found, even ignoring indentation. The file "
        "is not what the edit was written against.")


def fs_edit(args: dict) -> dict:
    """Replace one known block with another, or change nothing at all."""
    path = resolve(args.get("path"))
    old = str(args.get("old") or "")
    new = str(args.get("new") or "")
    if not path.exists():
        raise EditNotUnique(f"{path} does not exist; an edit is not a creation")

    before = path.read_text(encoding="utf-8")
    expect = str(args.get("expect_sha256") or "").strip().lower()
    if expect:
        on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
        if on_disk != expect:
            raise StaleWrite(
                f"{path} has changed since it was read: expected {expect[:12]}..., "
                f"found {on_disk[:12]}...")

    # THE MOST PRECISE MATCH FIRST: an exact substring that occurs exactly
    # once. The line-based ladder below is Codex's, and it is right for
    # replacing blocks, but it cannot express "change this word on this line"
    # -- and refusing that would push the proposer back to `fs.write`, which is
    # the whole-file replacement this capability exists to avoid.
    n = before.count(old) if old else 0
    if n > 1:
        raise EditNotUnique(
            f"the text to replace occurs {n} times exactly. An edit must name "
            "one place; give more surrounding lines.")
    if n == 1:
        after = before.replace(old, new, 1)
        path.write_text(after, encoding="utf-8")
        return {"path": str(path), "matched_by": "exact substring",
                "replacements": 1,
                "sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
                "previous": before}

    lines = before.splitlines(keepends=True)
    start, end, how = _locate(before, old)

    # A LOOSE MATCH MUST NOT REINDENT THE FILE. Matching "ignoring indentation"
    # and then writing the replacement flush left is how a surgical edit
    # silently breaks Python -- measured on the first run of this function,
    # where `        return 1` came back as `return 1` and the enclosing
    # function lost its body. The rung that widened the match owes the file the
    # indentation it matched past, so the delta between what was found and what
    # the caller wrote is applied to every line of the replacement.
    body = new
    if how != "exact":
        # PER LINE, NOT ONE DELTA FOR THE BLOCK. A single delta taken from the
        # first line flattens everything under it: matching
        #     def a(self):
        #         return 1
        # against a block the caller wrote flush left put `return 2` at the
        # same indentation as its own `def`, which is a syntax error the edit
        # reports as a success. Each line of the replacement takes the delta
        # between the file line it matched and the line the caller wrote at the
        # same position, so the structure the file already had is preserved.
        found = [_indent_of(ln) for ln in lines[start:end]]
        wrote = [_indent_of(ln) for ln in old.splitlines()]
        deltas = [f - w for f, w in zip(found, wrote)] or [0]
        out = []
        for i, ln in enumerate(new.splitlines()):
            out.append(_shift(ln, deltas[i] if i < len(deltas) else deltas[-1]))
        body = "\n".join(out)

    after = "".join(lines[:start]) + body + ("" if body.endswith("\n") else "\n") \
        + "".join(lines[end:])
    path.write_text(after, encoding="utf-8")
    return {"path": str(path),
            "matched_by": how,
            "replacements": 1,
            "sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
            "previous": before}


def fs_edit_compensator(args: dict, result: Any) -> dict:
    path = resolve(args.get("path"))
    prev = (result or {}).get("previous")
    if prev is None:
        return {"restored": "nothing_to_restore"}
    path.write_text(prev, encoding="utf-8")
    return {"restored": "previous_contents"}


def verify_fs_edit(result: dict) -> dict:
    """READ THE WORLD BACK, and check the hash of what is there now."""
    path = pathlib.Path(str((result or {}).get("path") or ""))
    if not path.exists():
        return {"verified": False, "why": "the edited file is not there"}
    on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
    claimed = (result or {}).get("sha256")
    return {"verified": on_disk == claimed,
            "on_disk_sha256": on_disk, "claimed_sha256": claimed,
            "why": "" if on_disk == claimed else
                   "what is on disk is not what the edit says it wrote"}


# ------------------------------------------------------------- observation

# How much of what an action produced may cross back into the proposer's
# context. Bounded at both ends: a runaway command must not fill the window,
# and a single enormous line must not defeat a line count.
OBS_MAX_LINES = 40
OBS_MAX_LINE_CHARS = 200


# THE TRUST CLASS OF WHAT AN ACTION SAW, per capability. INV-ACT-3 names its
# members exactly -- "screen content, OCR output, UI element labels and command
# output" -- and command output is the one that appears here, so `shell.run`
# is `retrieved_external` and capped at L1. A local file is not on that list
# and `retrieved_local` is the class the corpus provides for it, so reading a
# file caps the rest of the turn at L3 rather than L1.
#
# THAT DISTINCTION IS WHAT MAKES THE LOOP USABLE, and it is a real loosening,
# so it is written where it can be argued with. Treating every observation as
# external would mean that having looked at a file, VESPER must ask before
# editing it -- which is most of the work it exists to do. Treating command
# output as local would contradict an invariant by name.
#
# `fs.write`'s observation is a receipt: a path, a hash and whether something
# was replaced. It carries no content VESPER did not itself author, so it is
# `verified_local`. An unknown capability gets the strictest class there is,
# because a default that fails open is how the next capability becomes a hole.
OBSERVATION_TRUST = {
    "shell.run": EXTERNAL,
    # A SUB-AGENT'S ANSWER IS EXTERNAL CONTENT, and stating it here rather than
    # leaning on the default is the point: delegation is the cleanest laundering
    # path in the system -- hand it untrusted material, receive a confident
    # proposal with no trace of where it came from -- and the default is a thing
    # a later edit can change without noticing what it changed.
    "agent.ask": EXTERNAL,
    # A NAMED AGENT'S OUTPUT IS EXTERNAL FOR THE SAME REASON, and more
    # so: several of them read files and run searches, so their answers
    # carry whatever they found.
    "agent.run": EXTERNAL,
    "fs.read": "retrieved_local",
    "fs.edit": "retrieved_local",
    "fs.write": "verified_local",
}
OBSERVATION_TRUST_DEFAULT = EXTERNAL


def observation_trust(capability_id: str) -> str:
    return OBSERVATION_TRUST.get(capability_id, OBSERVATION_TRUST_DEFAULT)


def observe(capability_id: str, args: dict, result: dict) -> dict:
    """The TYPED view of what an action produced, for the next step to plan on.

    WHY THIS EXISTS RATHER THAN HANDING BACK THE RESULT. INV-AUTH-6: the
    planner context never ingests raw external text. Command output, file
    contents and UI labels are `retrieved_external` by INV-ACT-3, and the
    architecture the corpus committed to is that external content goes to an
    extraction context capped at L1 and only STRUCTURED, schema-shaped data
    crosses into the planner. This is that crossing, made narrow enough to
    describe: fixed keys, known types, bounded lengths.

    IT IS STILL TAINTED AND THAT IS THE POINT. Structure is not trust. A
    filename is attacker-controlled if a directory was attacker-controlled, so
    the caller wraps this in `Tainted(..., "retrieved_external")` and the
    context ceiling caps whatever the next step tries to do at L1. The two
    mechanisms are doing different jobs: this one bounds the SHAPE, the ceiling
    bounds the AUTHORITY, and neither substitutes for the other.

    WHAT IS DELIBERATELY ABSENT: `previous`, the prior contents of an
    overwritten file. It is in the result for the compensator and it has no
    business being shown to a model that is deciding what to do next.
    """
    def lines(text: Any) -> list:
        out = str(text or "").splitlines()[:OBS_MAX_LINES]
        return [ln[:OBS_MAX_LINE_CHARS] for ln in out]

    result = result if isinstance(result, dict) else {}
    if capability_id == "shell.run":
        return {"capability": capability_id,
                "cmd": str(args.get("cmd") or "")[:OBS_MAX_LINE_CHARS],
                "exit_code": result.get("exit_code"),
                "stdout_lines": lines(result.get("stdout")),
                "stderr_lines": lines(result.get("stderr"))}
    if capability_id == "fs.read":
        return {"capability": capability_id,
                "path": str(result.get("path") or args.get("path") or ""),
                "bytes": result.get("bytes"),
                "sha256": result.get("sha256"),
                "truncated": bool(result.get("truncated")),
                "lines": lines(result.get("text"))}
    if capability_id == "fs.edit":
        return {"capability": capability_id,
                "path": str(result.get("path") or args.get("path") or ""),
                "matched_by": result.get("matched_by"),
                "replacements": result.get("replacements"),
                "sha256": result.get("sha256")}
    if capability_id == "fs.write":
        return {"capability": capability_id,
                "path": str(result.get("path") or args.get("path") or ""),
                "wrote_sha256": result.get("intended_sha256"),
                "replaced_existing": bool(result.get("had_previous"))}
    # AN UNKNOWN CAPABILITY REPORTS THAT IT RAN AND NOTHING ELSE. Falling back
    # to the raw result would make every new capability a hole in INV-AUTH-6 by
    # default, which is the wrong direction for a default to fail in.
    return {"capability": capability_id, "observed": False}


# WHICH FILES AN ACTION WILL TOUCH, so the shadow store can snapshot them
# BEFORE it happens. Declared per capability rather than guessed from the
# arguments, because a guess that misses is an undo that silently is not there.
#
# `shell.run` is deliberately absent and that is a stated limit, not an
# oversight: a command's writes are not knowable from its text, which is the
# same reason it has no independent verifier. The seatbelt is what bounds it --
# an L1 command cannot write at all, and above L1 it can only write inside the
# workspace and temp. Undo for shell.run needs the sandbox to report what it
# touched, and that is not built.
TOUCHED_PATHS = {
    "fs.write": lambda args: [resolve(args.get("path"))],
    "fs.edit": lambda args: [resolve(args.get("path"))],
}


def touched_paths(capability_id: str, args: dict) -> list:
    fn = TOUCHED_PATHS.get(capability_id)
    if fn is None:
        return []
    try:
        return [pathlib.Path(p) for p in fn(args or {})]
    except Exception:                                  # noqa: BLE001
        # A CAPABILITY THAT DECLARES IT TOUCHES FILES AND CANNOT SAY WHICH IS
        # NOT CHECKPOINTABLE, and the executor refuses rather than running it
        # with no snapshot. Returning [] here would report "touches nothing",
        # which is the failure that looks like success.
        raise


# ---------------------------------------------------------------- assembly

def build_registry() -> CapabilityRegistry:
    """The capabilities the running system holds.

    Each `LevelRule` carries an example that the registry CALLS. A capability
    whose rules all resolve to one level is refused here, at the only moment the
    mistake is cheap.
    """
    reg = CapabilityRegistry()
    # THE REFUTATIONS BELOW ARE THE BUGS THIS MODULE ACTUALLY HAD. Each one is
    # an argument that WAS returning the cheap level and should not have been;
    # carrying them as counter-examples means the same mistake fails at
    # registration rather than in front of the owner.
    reg.register("shell.run", shell_level, [
        LevelRule("read_only", "L1", {"cmd": "ls"},
                  refutes=(
                      # `cat` is allowlisted and nothing looked at what it
                      # pointed AT. This returned L1 while `fs.read` of the
                      # same file returned L5 -- one protection, two doors.
                      {"cmd": "cat ~/.ssh/id_rsa"},
                      {"cmd": "cat ~/.config/vesper/secrets.env"},
                      # An allowlisted verb followed by anything else. Both
                      # halves are honest, which is the whole point of `;`.
                      {"cmd": "ls; rm -rf ~"},
                      {"cmd": "cat /etc/passwd | sudo tee /tmp/x"},
                  )),
        LevelRule("destructive", "L5", {"cmd": "rm -rf ~"}),
        LevelRule("other", "L3", {"cmd": "git status"}),
    ], external_effect=True, reversibility="irreversible")

    reg.register("agent.run", agent_run_level, [
        LevelRule("reader", "L2", {"agent": "navigator",
                                   "question": "where is the actor?"},
                  refutes=(
                      # An agent that runs commands is not a reader.
                      {"agent": "tester", "question": "run the gates"},
                      # And one nobody declared is not cheap.
                      {"agent": "not-in-the-roster", "question": "do a thing"},
                  )),
        LevelRule("acts", "L3", {"agent": "tester",
                                 "question": "run the gates"}),
        LevelRule("credential", "L5",
                  {"agent": "navigator", "question": "what is this?",
                   "material": "OPENAI_API_KEY=sk-live-abc"}),
    ], reversibility="reversible")

    reg.register("agent.ask", agent_ask_level, [
        LevelRule("brief", "L2", {"question": "what does this do?",
                                  "material": "class A: pass"},
                  refutes=(
                      # "Ask a sub-agent" sounds like thinking; what it does is
                      # send this to a provider.
                      {"question": "what is this?",
                       "material": "OPENAI_API_KEY=sk-live-abc"},
                      {"question": "summarise", "material": "x" * 9000},
                  )),
        LevelRule("credential", "L5",
                  {"question": "what is this?",
                   "material": "OPENAI_API_KEY=sk-live-abc"}),
    ], reversibility="reversible")

    reg.register("ui.open", ui_open_level, [
        LevelRule("owner file", "L3", {"path": "~/Downloads/a.png"},
                  refutes=(
                      {"path": "~/.config/vesper/secrets.env"},
                      {"path": "~/.ssh/id_rsa"},
                  )),
        LevelRule("link", "L2", {"path": "https://example.com"}),
        LevelRule("credential", "L5", {"path": "~/.config/vesper/secrets.env"}),
    ], reversibility="reversible")

    # WINDOWS. The ownership rule lives in `core/windows.py` and is consulted by
    # the implementation; these rules are the approval ladder, which is a
    # different question -- "may VESPER touch this window" versus "how much
    # confirmation does touching it cost".
    # INV-AUTH-5 REFUSED THE FIRST VERSION OF THIS AND IMPROVED IT. A constant
    # level was rejected -- "a capability whose level does not depend on its
    # arguments cannot distinguish `ls` from `rm -rf ~`" -- and the honest
    # second distinction was already sitting in the design: inventory is L1,
    # and asking for TITLES is content. `host_actions.toml`'s observe tier says
    # plainly that "anything that reads CONTENT is a new row and a new
    # decision", and the bridge refuses titles outright. Levelling the request
    # at L5 puts that boundary in the ladder rather than only in a comment, so a
    # future caller that asks for titles is refused by the authorisation path
    # instead of quietly getting inventory.
    reg.register("window.list", window_list_level, [
        LevelRule("inventory", "L1", {},
                  refutes=({"titles": True},)),
        LevelRule("titles", "L5", {"titles": True}),
    ], reversibility="reversible")

    reg.register("window.move", window_level, [
        LevelRule("vesper's own", "L2",
                  {"window_id": "1", "x": 0, "y": 0, "provenance": "vesper_opened"}),
        LevelRule("the owner's", "L3",
                  {"window_id": "1", "x": 0, "y": 0, "provenance": "unknown"}),
    ], reversibility="reversible")

    reg.register("window.resize", window_level, [
        LevelRule("vesper's own", "L2",
                  {"window_id": "1", "width": 10, "height": 10,
                   "provenance": "vesper_opened"}),
        LevelRule("the owner's", "L3",
                  {"window_id": "1", "width": 10, "height": 10,
                   "provenance": "unknown"}),
    ], reversibility="reversible")

    # NOT `compensatable`, and the distinction is the honest one: a compensator
    # would have to reopen the window, and nothing can reopen a document with
    # the owner's unsaved edits in it. `host_actions.toml` says the same thing
    # about `terminate_process` -- the only irreversible row in the vocabulary
    # exists to be governed, not to be undone.
    reg.register("window.close", window_close_level, [
        LevelRule("vesper's own", "L4",
                  {"window_id": "1", "effect": "close",
                   "provenance": "vesper_opened"},
                  refutes=({"window_id": "1", "effect": "close",
                            "provenance": "unknown"},)),
        # THE OWNER'S WINDOW IS A LEVEL HIGHER, and `host_actions.toml` agrees
        # from the other side: `close_window` is the one row the owner's
        # 2026-09-08 authorisation deliberately does NOT cover. Unsaved work in
        # the target is destroyed and no inverse recovers it.
        LevelRule("the owner's", "L5",
                  {"window_id": "1", "effect": "close", "provenance": "unknown"}),
    ], reversibility="irreversible")

    # RELOCATION IS ITS OWN CAPABILITY, matching `core/windows.py`'s own split:
    # crossing the Desktop boundary changes which clause of the ownership rule
    # applies, so a position change must never be able to carry an authority
    # change with it.
    # SEPARATE FROM `ui.open` DELIBERATELY. Both put something on screen; only
    # this one records that VESPER caused it, and that record is what later
    # authorises VESPER to move or close it unasked. A flag on `ui.open` would
    # have let a capability the owner already approved acquire new authority
    # without a new approval.
    reg.register("window.open", window_open_level, [
        LevelRule("an application", "L2", {"app": "TextEdit"},
                  refutes=({"path": "~/.config/vesper/secrets.env"},)),
        LevelRule("owner file", "L3", {"path": "~/Downloads/a.png"}),
        LevelRule("credential", "L5", {"path": "~/.config/vesper/secrets.env"}),
    ], reversibility="reversible")

    reg.register("window.relocate", window_level, [
        LevelRule("vesper's own", "L2",
                  {"window_id": "1", "space": "3", "provenance": "vesper_opened"}),
        LevelRule("the owner's", "L3",
                  {"window_id": "1", "space": "3", "provenance": "unknown"}),
    ], reversibility="reversible")

    reg.register("fs.read", fs_read_level, [
        LevelRule("ordinary", "L1", {"path": "README.md"},
                  refutes=(
                      {"path": "~/.config/vesper/secrets.env"},
                      {"path": "~/.ssh/id_rsa"},
                      # Levelled on the string it was NAMED by rather than the
                      # target it resolves to: this begins with `workspace/`
                      # and opens /etc/passwd.
                      {"path": "workspace/../../../../etc/passwd"},
                  )),
        LevelRule("credential", "L5", {"path": "~/.config/vesper/secrets.env"}),
        LevelRule("system", "L3", {"path": "/etc/hosts"}),
    ], reversibility="reversible")

    reg.register("fs.write", fs_write_level, [
        LevelRule("workspace", "L2", {"path": "workspace/note.txt"},
                  refutes=(
                      {"path": "contracts/policy/cost_policy.toml"},
                      # GOVERNED is asked of the ABSOLUTE path, so it must
                      # still fire once a relative prefix has resolved away.
                      {"path": "workspace/../contracts/policy/cost_policy.toml"},
                      {"path": "~/.config/vesper/secrets.env"},
                  )),
        LevelRule("governed", "L5", {"path": "contracts/policy/cost_policy.toml"}),
        LevelRule("ordinary", "L3", {"path": "documents/note.txt"}),
    ], reversibility="compensatable")

    reg.register("fs.edit", fs_edit_level, [
        LevelRule("workspace", "L2",
                  {"path": "workspace/note.txt", "old": "a", "new": "b"}),
        LevelRule("governed", "L5",
                  {"path": "contracts/policy/cost_policy.toml",
                   "old": "a", "new": "b"}),
        LevelRule("ordinary", "L3",
                  {"path": "documents/note.txt", "old": "a", "new": "b"}),
    ], reversibility="compensatable")
    return reg


def bind_all(executor, *, jobs=None, agent=None, runner=None) -> None:
    """Attach implementations. `fs.write` cannot bind without its compensator.

    THE JOB REGISTRY IS BOUND, NOT PASSED IN ARGS. `background` is a flag the
    proposer may set; the thing that can STOP a background command is not, and
    must never be something a model supplies or omits. Binding it here means a
    proposer can ask for background and cannot ask for background-without-a-way-
    to-stop-it -- `shell_run` refuses that combination outright, and this is
    what makes the refusal unreachable in practice rather than merely correct.
    """
    if jobs is not None:
        def _shell_with_jobs(args: dict) -> dict:
            return shell_run({**args, "_jobs": jobs})
        executor.bind("shell.run", _shell_with_jobs)
    else:
        executor.bind("shell.run", shell_run)

    executor.bind("ui.open", ui_open)

    executor.bind("window.list", window_list)
    executor.bind("window.move", window_move)
    executor.bind("window.resize", window_resize)
    executor.bind("window.close", window_close)
    executor.bind("window.relocate", window_relocate)
    executor.bind("window.open", window_open)

    # THE SUB-AGENT IS BOUND, NOT PASSED IN ARGS, for the reason the job
    # registry is: what a proposal may ASK for and what carries the request are
    # different things, and the second must never be something a model supplies.
    if agent is not None:
        def _ask_with_agent(args: dict) -> dict:
            return agent_ask({**args, "_agent": agent})
        executor.bind("agent.ask", _ask_with_agent)
    else:
        executor.bind("agent.ask", agent_ask)

    # THE RUNNER IS BOUND, NOT PASSED IN ARGS, for the same reason the job
    # registry and the sub-agent are: a proposal may name WHICH agent, and must
    # never supply the thing that runs it.
    if runner is not None:
        def _run_with_runner(args: dict) -> dict:
            return agent_run({**args, "_runner": runner})
        executor.bind("agent.run", _run_with_runner)
    else:
        executor.bind("agent.run", agent_run)
    executor.bind("fs.read", fs_read)
    executor.bind("fs.write", fs_write, compensator=fs_write_compensator)
    executor.bind("fs.edit", fs_edit, compensator=fs_edit_compensator)


# The capabilities whose results are checked by reading the world back, and the
# function that does it. Absence from this table is not "verification passed";
# `shell.run` is absent because a command's effect is not generically
# observable, and that is recorded rather than papered over.
INDEPENDENT_VERIFIERS = {
    "fs.write": verify_fs_write,
    "fs.edit": verify_fs_edit,
}
