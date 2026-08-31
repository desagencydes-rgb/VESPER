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
import os
import pathlib
import shlex
import subprocess
from typing import Any

from core.capability import CapabilityRegistry, LevelRule

# THE ROOT THE LEVEL RULES ARE TALKING ABOUT, stated rather than inherited.
# `fs_write_level("workspace/x")` returns L2 and `("contracts/policy/y")`
# returns L5 -- both readings of a RELATIVE path, which mean nothing without a
# root. Until this was written the root was whatever working directory the
# process happened to have: `$REPO` under the LaunchAgent, and something else
# for anyone running the runtime by hand. So the same argument could be levelled
# as a harmless workspace file and then executed against a different tree.
# The classifier and the implementation now resolve against the same constant.
REPO = pathlib.Path(__file__).resolve().parents[1]


def resolve(path: str) -> pathlib.Path:
    """`~` expanded, relative paths taken against the repository root."""
    p = pathlib.Path(os.path.expanduser(str(path or "")))
    return p if p.is_absolute() else (REPO / p)

# ---------------------------------------------------------------- shell.run

# Verbs that cannot alter the machine no matter what they are pointed at. Kept
# SHORT on purpose: every addition is a new way to be wrong, and the cost of
# omitting one is a question to the owner rather than a destroyed file.
READ_ONLY_VERBS = frozenset({
    "ls", "pwd", "whoami", "date", "uname", "hostname", "id",
    "cat", "head", "tail", "wc", "file", "stat", "du", "df",
    "echo", "which", "type", "env", "uptime", "ps",
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
    if parts and parts[0] in READ_ONLY_VERBS:
        return "L1"
    return "L3"


def shell_run(args: dict) -> dict:
    """Run it, and report what was OBSERVED rather than whether it 'worked'.

    No shell. `shell=True` would re-introduce every chaining form the level
    rules just spent their effort excluding -- the classifier would be reasoning
    about one language and the execution happening in another.

    `cwd` IS STATED for the same reason: a relative path means nothing without a
    root, and inheriting one makes the level a function of who started the
    process.
    """
    cmd = str(args.get("cmd") or "")
    timeout = float(args.get("timeout") or 20.0)
    p = subprocess.run(shlex.split(cmd), capture_output=True, text=True,
                       timeout=timeout, check=False, cwd=str(REPO))
    return {"exit_code": p.returncode,
            "stdout": p.stdout[:4000],
            "stderr": p.stderr[:2000]}


# ------------------------------------------------------------ fs.read/write

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


def fs_read_level(args: dict) -> str:
    p = _norm(args.get("path")).lower()
    if not p:
        return "L5"
    if any(m in p for m in SECRET_MARKERS):
        # READING a credential is not a lesser act than writing one. It is the
        # step that puts it in a context window, which is where it leaves.
        return "L5"
    if p.startswith(("/etc", "/private/etc", "/var/db", "/library/keychains")):
        return "L3"
    return "L1"


def fs_write_level(args: dict) -> str:
    p = _norm(args.get("path")).lower()
    if not p:
        return "L5"
    if any(m in p for m in SECRET_MARKERS):
        return "L5"
    if any(p.startswith(g) or f"/{g}" in p for g in GOVERNED_PREFIXES):
        return "L5"
    if p.startswith("workspace/") or "/workspace/" in p:
        return "L2"
    return "L3"


def fs_read(args: dict) -> dict:
    path = resolve(args.get("path"))
    limit = int(args.get("limit") or 20000)
    text = path.read_text(encoding="utf-8", errors="replace")[:limit]
    return {"path": str(path), "text": text, "bytes": path.stat().st_size}


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


# ---------------------------------------------------------------- assembly

def build_registry() -> CapabilityRegistry:
    """The capabilities the running system holds.

    Each `LevelRule` carries an example that the registry CALLS. A capability
    whose rules all resolve to one level is refused here, at the only moment the
    mistake is cheap.
    """
    reg = CapabilityRegistry()
    reg.register("shell.run", shell_level, [
        LevelRule("read_only", "L1", {"cmd": "ls"}),
        LevelRule("destructive", "L5", {"cmd": "rm -rf ~"}),
        LevelRule("other", "L3", {"cmd": "git status"}),
    ], external_effect=True, reversibility="irreversible")

    reg.register("fs.read", fs_read_level, [
        LevelRule("ordinary", "L1", {"path": "README.md"}),
        LevelRule("credential", "L5", {"path": "~/.config/vesper/secrets.env"}),
        LevelRule("system", "L3", {"path": "/etc/hosts"}),
    ], reversibility="reversible")

    reg.register("fs.write", fs_write_level, [
        LevelRule("workspace", "L2", {"path": "workspace/note.txt"}),
        LevelRule("governed", "L5", {"path": "contracts/policy/cost_policy.toml"}),
        LevelRule("ordinary", "L3", {"path": "documents/note.txt"}),
    ], reversibility="compensatable")
    return reg


def bind_all(executor) -> None:
    """Attach implementations. `fs.write` cannot bind without its compensator."""
    executor.bind("shell.run", shell_run)
    executor.bind("fs.read", fs_read)
    executor.bind("fs.write", fs_write, compensator=fs_write_compensator)


# The capabilities whose results are checked by reading the world back, and the
# function that does it. Absence from this table is not "verification passed";
# `shell.run` is absent because a command's effect is not generically
# observable, and that is recorded rather than papered over.
INDEPENDENT_VERIFIERS = {
    "fs.write": verify_fs_write,
}
