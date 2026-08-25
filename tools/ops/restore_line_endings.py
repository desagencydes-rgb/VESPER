#!/usr/bin/env python3
"""Restore any file whose line endings a patch script silently rewrote.

WHY THIS EXISTS RATHER THAN A NOTE IN CLAUDE.md. The note is already there and
it has not been enough: several files in this repo are CRLF, Python's
`read_text`/`write_text` round-trip converts them to LF, and the result is a
diff where a 40-line change arrives as 5,900 lines of churn. It has happened
three times in one session, each time to the same three files, each time caught
only because `git diff --stat` was read before committing.

A REMINDER THAT HAS TO BE OBEYED EVERY TIME IS A CONTROL THAT WILL EVENTUALLY
BE MISSED. This compares the working tree against HEAD and puts back whatever
the editing tool took away -- content untouched, endings restored.

Run it before staging. Exits non-zero if it changed anything, so a hook or a
careless commit notices.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=False).stdout


def main() -> int:
    changed = [f for f in git("diff", "--name-only").splitlines() if f.strip()]
    fixed = []
    for f in changed:
        p = Path(f)
        if not p.is_file():
            continue
        head = subprocess.run(["git", "show", f"HEAD:{f}"],
                              capture_output=True, check=False).stdout
        if not head:
            continue
        head_crlf = b"\r\n" in head
        wt = p.read_bytes()
        wt_crlf = b"\r\n" in wt
        if head_crlf and not wt_crlf:
            # Normalise first so a partially-converted file cannot end up with
            # doubled carriage returns.
            p.write_bytes(wt.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            fixed.append(f)
        elif wt_crlf and not head_crlf:
            p.write_bytes(wt.replace(b"\r\n", b"\n"))
            fixed.append(f)

    if fixed:
        print("restored line endings (content untouched):")
        for f in fixed:
            print(f"  {f}")
        return 1
    print("line endings match HEAD on every changed file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
