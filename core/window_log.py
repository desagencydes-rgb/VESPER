"""What VESPER did with windows, kept so it can answer "what was I working on".

THE OWNER'S DESIGN, 2026-09-09, and its most important property is what it does
NOT do: *"no windows open after reboot, vesper can look at the logs and define
the windows it was working on, and then opens what it needs at that time, it's a
fresh start for it anyways."*

So this is a RECORD AND NEVER A TRIGGER. Nothing here reopens anything. That is
not a simplification, it is what makes the design correct:

  - A "reopen this at startup" flag would have to be written at shutdown, and a
    crash, a panic or a flat battery skips that -- the feature would be absent
    exactly when it was wanted.
  - A bulk restore at startup is an autonomous action with no trigger, which
    `INV-TRIG-1` refuses. A window opened because a task needs it inherits that
    task's trigger.
  - It is the compactor's own doctrine: `L1(n+1) = project(L3)`, never
    `compact(L1(n))`. Restoring a saved set replays a previous answer; reading
    the log and deciding fresh projects from the record.
  - And after a reboot the world may have moved -- files renamed, applications
    updated, the work abandoned. Restoring blindly asserts that yesterday's
    context is today's.

SCOPED TO WINDOWS VESPER TOUCHED. Not the owner's whole session. That bounds the
size and keeps this from becoming a record of someone's week that VESPER had no
business keeping.

AN ABSENT TITLE SAYS WHY, AND THE REASON IS A CODE. The corpus's rule is that an
absence carries its reason and no stamp. Codes rather than sentences because the
owner asked that VESPER be able to look these up and understand them without
getting confused -- a closed set can be queried; prose can only be re-read and
guessed at, which is the compact-your-own-answer trap in another costume.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import threading
import time
from typing import Any, Iterator

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
LOG_DIR = STATE / "window-log"

# WHY A TITLE IS ABSENT. Closed set, extended only deliberately.
NO_FILE = "no_file"                  # never saved to a folder
NO_FILE_MODEL = "no_file_model"      # the application does not open documents
UNREADABLE = "unreadable"            # accessibility not granted; nothing to read
REASONS = (NO_FILE, NO_FILE_MODEL, UNREADABLE)

_LOCK = threading.RLock()


def _week_of(at_ms: int) -> str:
    """The ISO week a moment belongs to. Segments rotate weekly, per the owner."""
    t = time.gmtime(at_ms / 1000.0)
    iso = time.strftime("%G-W%V", t)
    return iso


def _segment(week: str, *, compressed: bool = False) -> pathlib.Path:
    return LOG_DIR / (f"{week}.jsonl.gz" if compressed else f"{week}.jsonl")


def record(*, window_id: str, action: str, app_label: str = "",
           bundle_id: str = "", pid: Any = "", desktop_id: str = "",
           provenance: str = "", geometry: dict | None = None,
           title: str | None = None, title_absent: str | None = None,
           task: str = "", at_ms: int | None = None) -> dict:
    """Append one interaction. Never raises: losing a memory is not losing safety.

    `title` and `title_absent` are exclusive and one is required. A row with
    neither would be an absence with no reason, which is the thing this corpus
    refuses -- and a row with both would be claiming two contradictory facts.
    """
    at = int(at_ms if at_ms is not None else time.time() * 1000)
    if title is None and title_absent not in REASONS:
        title_absent = UNREADABLE
    if title is not None:
        title_absent = None
    row = {"at_ms": at, "window_id": str(window_id), "action": str(action),
           "app_label": str(app_label), "bundle_id": str(bundle_id),
           "pid": str(pid), "desktop_id": str(desktop_id),
           "provenance": str(provenance), "geometry": dict(geometry or {}),
           "task": str(task)}
    if title is not None:
        row["title"] = str(title)
    else:
        row["title_absent"] = str(title_absent)
    try:
        with _LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            seg = _segment(_week_of(at))
            with seg.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass
    return row


def _read_segment(path: pathlib.Path) -> Iterator[dict]:
    """One segment's rows, compressed or not, WITHOUT a decompression step.

    The owner's requirement is that VESPER can come back to any of it and read
    it whenever, without decompressing anything first. `gzip.open` in text mode
    is exactly that: the caller does not know or care which form a segment is
    in, which is what makes the weekly compression invisible rather than a
    thing to remember.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:      # type: ignore[operator]
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue          # one bad line never hides the rest
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def segments() -> list:
    """Every segment, oldest first, whichever form each is in."""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("*.jsonl*"), key=lambda p: p.name)


def read(*, since_ms: int = 0, app: str = "", action: str = "",
         limit: int = 500) -> list:
    """Rows matching a filter, newest last. Reads compressed segments directly."""
    out: list = []
    for seg in segments():
        for row in _read_segment(seg):
            if row.get("at_ms", 0) < since_ms:
                continue
            if app and row.get("app_label") != app:
                continue
            if action and row.get("action") != action:
                continue
            out.append(row)
    return out[-limit:]


def compress_old_weeks(*, now_ms: int | None = None) -> list:
    """Compress every segment except the current week's.

    THE CURRENT WEEK STAYS UNCOMPRESSED AND NEAR, per the owner. Older weeks are
    gzipped in place and remain readable through `read()` with no extra step.
    Returns the segments compressed, so a caller can say what it did.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    keep = _week_of(now)
    done = []
    with _LOCK:
        for seg in segments():
            if seg.suffix == ".gz" or seg.name.startswith(keep):
                continue
            try:
                raw = seg.read_bytes()
                gz = seg.with_name(seg.name + ".gz")
                with gzip.open(gz, "wb") as fh:
                    fh.write(raw)
                # THE ORIGINAL GOES ONLY AFTER THE COPY IS READABLE. A crash
                # between writing and deleting must not be able to lose a week.
                if any(_read_segment(gz)):
                    seg.unlink()
                    done.append(gz.name)
                else:
                    gz.unlink()
            except OSError:
                continue
    return done
