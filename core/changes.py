"""What changed on disk, with a real diff, from two sources the owner can tell apart.

THE OWNER'S REQUEST: "anything it does to any file (addings+deletes)" shown "in
a comprehensive clean way, totally manageable, user friendly", each file
collapsed in a list and expandable on demand, with additions and deletions
compared, and buttons to push, pull and create.

WHERE THE "BEFORE" COMES FROM, AND WHY IT IS NOT INVENTED HERE.
`core/checkpoint.py`'s `ShadowGit` already mirrors, by absolute path, every file
VESPER is about to touch -- it has to, because the executor FAILS CLOSED on a
capability that changes files it cannot snapshot first. So the prior contents of
every write VESPER makes are already committed to a real git repository, keyed
by the execution that made them. This reads that. Building a second store of
"previous" bytes beside it would be a second answer to a question that already
has one, and the two would eventually disagree about the same file.

AND IT IS NOT THE EVENT LOG. `Actor._reportable` deliberately strips `previous`
from the durable record and keeps `previous_sha256`, so the audit store never
carries file contents. That decision stands and this does not reverse it: what
follows is a VIEW CACHE. It is bounded, it is rebuilt from the shadow, nothing
may cite it as evidence, and it is not append-only. A future session finding
this file must not mistake it for an audit trail -- the audit trail is the bus
log and does not contain a single line of anyone's file.

TWO SOURCES, LABELLED, NEVER MERGED INTO A FAKE GIT VIEW. VESPER writes to
paths in no repository at all -- the workspace, `~/Downloads` -- and the owner
also edits repository files VESPER never saw. Both belong in the list; only one
of them can be pushed. So every row carries `source`, and the git buttons are
disabled on rows git has never heard of.

A SUBSCRIBER, NOT A CALLER, like `core/workbench.py`. Nothing in the request
path calls in here; this attaches to the bus and reads what the executor
already publishes. A method somebody has to remember to call is a board that is
accurate until the first time somebody forgets.

Stdlib only.
"""

from __future__ import annotations

import difflib
import pathlib
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

# How many changed files the card holds. A working tree mid-rebase can have
# hundreds; the card is a place to read a diff, not a place to page through one.
CHANGES_MAX = 60

# What one file may contribute. Both bounds exist because they fail differently:
# a minified bundle is one line and megabytes, a generated file is a hundred
# thousand short ones.
DIFF_MAX_LINES = 300
DIFF_MAX_BYTES = 32_000

# AND A BUDGET ACROSS ALL OF THEM, WHICH IS THE BOUND THAT ACTUALLY MATTERED.
# The per-file caps were satisfied and the board still carried 36 KB for one
# Swift file; twelve of those is a megabyte, rewritten into `home.json` and
# pushed through a webview on every tick. The owner has asked twice not to heat
# this machine up. Rows past the budget keep their COUNTS -- which come from
# `--numstat` and cost nothing -- and say plainly that the diff was not loaded.
DIFF_TOTAL_MAX_BYTES = 140_000

# How many files get a full textual diff. The rest are listed with their counts.
DIFF_FILES_MAX = 8

# A file bigger than this is not diffed at all. Reading both sides of a 200 MB
# binary to render a card is a way to make the surface hang, and "binary file
# changed" is the whole of what a diff of it would say anyway.
FILE_MAX_BYTES = 2_000_000

# How often the working tree is re-read. `git status` on a large repository is
# not free and the answer changes at human speed.
GIT_REFRESH_S = 6.0

STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed",
          "C": "copied", "?": "untracked", "T": "typechange"}


@dataclass(slots=True)
class Change:
    path: str
    source: str                     # vesper | git
    status: str                     # added | modified | deleted | untracked ...
    added: int = 0
    removed: int = 0
    hunks: str = ""
    by_vesper: bool = False
    in_repo: str = ""               # the repo root, or "" when there is none
    truncated: bool = False
    binary: bool = False

    @property
    def name(self) -> str:
        return pathlib.PurePath(self.path).name

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name, "source": self.source,
                "status": self.status, "added": self.added,
                "removed": self.removed, "hunks": self.hunks,
                "by_vesper": self.by_vesper, "in_repo": self.in_repo,
                "truncated": self.truncated, "binary": self.binary}


def _read(path: pathlib.Path) -> tuple[str, bool]:
    """The file as text, and whether it is one. Never raises."""
    try:
        if not path.is_file():
            return "", False
        if path.stat().st_size > FILE_MAX_BYTES:
            return "", True
        raw = path.read_bytes()
    except OSError:
        return "", False
    if b"\x00" in raw[:8000]:
        return "", True
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return "", True


def _redact(text: str) -> str:
    """Whatever the redactor takes out, taken out of BOTH sides of the diff.

    A file VESPER wrote may contain a key it was asked to write, and this card
    renders file contents into a webview and through `home.json`. The redactor
    is the same one that stands in front of every model call; there is no
    argument for it guarding egress and not guarding the screen.
    """
    if not text:
        return text
    try:
        from . import redact as _r
        out = _r.redact(text, source="changes")
        return out[0] if isinstance(out, tuple) else str(out)
    except Exception:                                   # noqa: BLE001
        # A REDACTOR FAILURE HIDES THE DIFF RATHER THAN SHOWING IT RAW. The
        # opposite default -- show it and hope -- is how a key reaches a
        # surface, and the cost of this one is a card that says less.
        return "(redactor unavailable — diff withheld)"


def diff(before: str, after: str, path: str) -> tuple[str, int, int, bool]:
    """A unified diff, its counts, and whether it was cut.

    COUNTED OFF THE DIFF THAT IS SHOWN, not off the whole one. A card reading
    "+900 −4" above four visible lines is a card lying about what it is
    displaying, which is worse than saying the view is partial.
    """
    a = before.splitlines(keepends=True)
    b = after.splitlines(keepends=True)
    rows = list(difflib.unified_diff(a, b, fromfile=path, tofile=path, n=3))
    cut = False
    if len(rows) > DIFF_MAX_LINES:
        rows = rows[:DIFF_MAX_LINES]
        cut = True
    text = "".join(rows)
    if len(text.encode("utf-8")) > DIFF_MAX_BYTES:
        text = text.encode("utf-8")[:DIFF_MAX_BYTES].decode("utf-8", "ignore")
        cut = True
        rows = text.splitlines(keepends=True)
    added = sum(1 for r in rows if r.startswith("+") and not r.startswith("+++"))
    removed = sum(1 for r in rows if r.startswith("-") and not r.startswith("---"))
    return text, added, removed, cut


def repo_of(path: Any) -> str:
    """The git repository containing this path, or "" -- never a guess."""
    p = pathlib.Path(path)
    d = p if p.is_dir() else p.parent
    try:
        r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


class Changes:
    """The changed-files board. Subscribes to the executor; reads the shadow."""

    def __init__(self, shadow: Any = None) -> None:
        self._lock = threading.RLock()
        self._shadow = shadow
        # execution_id -> (checkpoint commit, paths). Held only between the
        # checkpoint and the completion, then dropped -- this is not a log.
        self._pending: dict[str, tuple[str, list[str]]] = {}
        self._vesper: list[Change] = []
        self._git: list[Change] = []
        self._git_at = 0.0
        self._git_root = ""

    # ------------------------------------------------------------ the shadow

    def _before(self, commit: str, path: str) -> tuple[str, bool]:
        """The file as the shadow recorded it just before VESPER touched it.

        ABSENT IS A REAL ANSWER, and it is how a CREATION is represented: there
        was no file, so the diff is all additions. Returning "" for both "empty
        file" and "no file" is the same conflation the shadow's own `restore`
        refuses to make, so the second value says which.
        """
        if self._shadow is None or not commit:
            return "", False
        mirror = "tree/" + str(pathlib.Path(path).resolve()).lstrip("/")
        try:
            r = subprocess.run(
                ["git", "-C", str(self._shadow.root), "show", f"{commit}:{mirror}"],
                capture_output=True, text=True, check=False, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return "", False
        if r.returncode != 0:
            return "", False           # not in that commit: the file is new
        return r.stdout, True

    def _record(self, capability_id: str, commit: str, paths: list) -> None:
        for raw in paths[:8]:
            path = str(pathlib.Path(raw).resolve())
            before, existed = self._before(commit, path)
            after, binary = _read(pathlib.Path(path))
            now_exists = pathlib.Path(path).is_file()
            if not existed and not now_exists:
                continue                     # nothing was there and nothing is
            status = ("added" if not existed else
                      "deleted" if not now_exists else "modified")
            if binary:
                ch = Change(path=path, source="vesper", status=status,
                            by_vesper=True, binary=True,
                            in_repo=repo_of(path))
            else:
                text, add, rem, cut = diff(_redact(before), _redact(after), path)
                if status == "modified" and not text:
                    continue                 # touched and unchanged is not a change
                ch = Change(path=path, source="vesper", status=status,
                            added=add, removed=rem, hunks=text,
                            by_vesper=True, truncated=cut,
                            in_repo=repo_of(path))
            with self._lock:
                # ONE ROW PER PATH. A file written six times in a turn is one
                # changed file, and six rows would bury the other five files.
                self._vesper = [c for c in self._vesper if c.path != ch.path]
                self._vesper.append(ch)
                del self._vesper[:-CHANGES_MAX]

    # -------------------------------------------------------------- the tree

    def refresh_git(self, root: str = "", *, now: float = 0.0) -> None:
        """Re-read the working tree, at most every `GIT_REFRESH_S`.

        THROTTLED, BECAUSE THE PUMP RUNS FOUR TIMES A SECOND. `git status` plus
        a diff per changed file, eight times a second, on a repository this
        size, is a measurable load on a laptop the owner has asked twice not to
        heat up.
        """
        import time as _t
        now = now or _t.time()
        with self._lock:
            if now - self._git_at < GIT_REFRESH_S:
                return
            self._git_at = now
        # THE ROOT IS RESOLVED, NEVER TRUSTED AS PASSED.
        #
        # MEASURED 2026-09-06: the runtime executes from inside the app bundle,
        # so its `REPO` constant is `.../VESPER.app/Contents/Resources/runtime`
        # -- a directory that IS inside the owner's repository but is not its
        # top level. `git status` there still worked, so the card filled with
        # rows and looked right, while every path was made relative to the
        # wrong root and every single `git diff` came back empty: eighteen
        # changed files, all reading "+0 −0". A card that is confidently wrong
        # is worse than one that is missing.
        root = repo_of(root or self._git_root or pathlib.Path.cwd()) or ""
        if not root:
            return
        self._git_root = root
        try:
            st = subprocess.run(["git", "-C", root, "status", "--porcelain",
                                 "--untracked-files=normal"],
                                capture_output=True, text=True, check=False,
                                timeout=25)
        except (OSError, subprocess.SubprocessError):
            return
        if st.returncode != 0:
            return
        rows: list[Change] = []
        for line in st.stdout.splitlines()[:CHANGES_MAX]:
            if len(line) < 4:
                continue
            code, rel = line[:2], line[3:].strip()
            if " -> " in rel:                       # a rename: show the target
                rel = rel.split(" -> ", 1)[1]
            rel = rel.strip('"')
            status = STATUS.get(code.strip()[:1] or "M", "modified")
            full = str(pathlib.Path(root) / rel)
            rows.append(Change(path=full, source="git", status=status,
                               in_repo=root))
        # EVERY ROW GETS ITS COUNTS, from `--numstat`, in ONE command. A row
        # reading "modified" with no numbers tells the owner less than the file
        # listing they already have, and this costs one process for the whole
        # tree rather than one per file.
        try:
            ns = subprocess.run(["git", "-C", root, "diff", "--numstat", "HEAD"],
                                capture_output=True, text=True, check=False,
                                timeout=25)
            counts: dict[str, tuple[int, int]] = {}
            if ns.returncode == 0:
                for ln in ns.stdout.splitlines():
                    bits = ln.split("\t")
                    if len(bits) == 3:
                        a, d, name = bits
                        counts[name] = ((int(a) if a.isdigit() else 0),
                                        (int(d) if d.isdigit() else 0))
            for ch in rows:
                rel = str(pathlib.PurePath(ch.path).relative_to(ch.in_repo))
                if rel in counts:
                    ch.added, ch.removed = counts[rel]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        # THE DIFF TEXT IS FETCHED FOR A BOUNDED PREFIX, WITHIN A BOUNDED
        # TOTAL. `git diff` per file is the expensive half, and a working tree
        # with two hundred changed files would spend the pump's whole budget
        # rendering rows nobody scrolled to.
        spent = 0
        for ch in rows[:DIFF_FILES_MAX]:
            if spent >= DIFF_TOTAL_MAX_BYTES:
                ch.truncated = True
                break
            rel = str(pathlib.PurePath(ch.path).relative_to(ch.in_repo))
            if ch.status == "untracked":
                after, binary = _read(pathlib.Path(ch.path))
                if binary:
                    ch.binary = True
                    continue
                ch.hunks, ch.added, ch.removed, ch.truncated = diff(
                    "", _redact(after), ch.path)
                spent += len(ch.hunks)
                continue
            try:
                d = subprocess.run(["git", "-C", ch.in_repo, "diff", "HEAD", "--", rel],
                                   capture_output=True, text=True, check=False,
                                   timeout=20)
            except (OSError, subprocess.SubprocessError):
                continue
            if d.returncode != 0:
                continue
            body = _redact(d.stdout)
            lines = body.splitlines(keepends=True)
            if len(lines) > DIFF_MAX_LINES:
                lines = lines[:DIFF_MAX_LINES]
                ch.truncated = True
            ch.hunks = "".join(lines)
            spent += len(ch.hunks)
            # THE COUNTS STAY THE ONES `--numstat` GAVE. Recomputing them from
            # a diff that may have been cut would put "+12" above a file that
            # really changed in nine hundred places -- a card confidently
            # describing something other than what happened.
        with self._lock:
            self._git = rows

    # ---------------------------------------------------------------- the bus

    def attach(self, bus: Any) -> None:
        def on_checkpoint(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            eid = str(p.get("execution_id") or "")
            if not eid:
                return
            with self._lock:
                # BOUNDED. An execution that is checkpointed and never completes
                # -- refused after the snapshot, or the runtime restarted --
                # would otherwise sit here forever.
                if len(self._pending) > 64:
                    self._pending.pop(next(iter(self._pending)))
                self._pending[eid] = (str(p.get("checkpoint") or ""),
                                      [str(x) for x in (p.get("paths") or [])])

        def on_completed(ev: Any) -> None:
            p = getattr(ev, "payload", {}) or {}
            eid = str(p.get("execution_id") or "")
            with self._lock:
                held = self._pending.pop(eid, None)
            if not held:
                return
            commit, paths = held
            # READ THE WORLD BACK AFTER ACTING. The diff is computed HERE, not
            # from what the capability said it wrote -- a result claiming a file
            # was written is the instrument's self-report, and this tree's rule
            # is that it is not evidence.
            self._record(str(p.get("capability_id") or ""), commit, paths)

        for topic, fn, name in (("tool.checkpointed", on_checkpoint, "changes-checkpoint"),
                                ("tool.completed", on_completed, "changes-completed")):
            bus.subscribe(topic, fn, name=name,
                          idempotency_key=lambda e: e.event_id)

    # --------------------------------------------------------------- render

    def state(self) -> dict:
        with self._lock:
            vesper = [c.to_dict() for c in self._vesper]
            git = [c.to_dict() for c in self._git]
        # A PATH VESPER WROTE THAT GIT ALSO TRACKS IS ONE ROW, NOT TWO -- and it
        # is the GIT row, because that is the more useful of the two views, with
        # `by_vesper` kept so the authorship is not lost.
        by_path = {c["path"]: c for c in git}
        for c in vesper:
            if c["path"] in by_path:
                by_path[c["path"]]["by_vesper"] = True
            else:
                by_path[c["path"]] = c
        rows = list(by_path.values())[:CHANGES_MAX]
        return {"changes": rows, "repo": self._git_root}
