"""What the `projects` and `research` rail buttons show (§11.7).

WHY THESE TWO AND NOT SOMETHING INVENTED. §11.7 recorded the gap honestly:
`research` has a written specification as a STAGE (§7.1 — the subject on the
right, a freeform canvas on the left, the face dispersed) and `projects` had
none at all, with `spec_raw.txt` routing seventeen items to `history` and zero
here. A night was spent refusing to invent seventeen features nobody asked for.

`HOME-ARCHITECTURE` §14.2 is what resolves it: `history` and `settings` are whole
SPACES, while `projects` and `research` are **Work-room cards**. So the rail
buttons are not the stage and not a space -- they are the way IN, and what a way
in should show is what is already there.

SO BOTH READ SOMETHING REAL THAT ALREADY EXISTS:

  projects  -> the build order in the plan doc. The steps, their state, and what
               each is waiting on. That IS the project, it is written down, and
               the owner recognises it on sight.
  research  -> the spike index, which `CLAUDE.md` calls "the status authority for
               every spike". A spike is a question settled by measurement, which
               is what research means here rather than a reading list nobody has
               filled.

NEITHER INVENTS A ROW. If the file cannot be read, the surface says so with the
reason -- the same rule `settings_surface.py` follows, and for the same reason:
a false zero looks measured and is not.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "docs" / "design" / "HOME-WORKBENCH.md"
SPIKES = REPO / "docs" / "spikes" / "INDEX.toml"

# THE MARKERS THE PLAN DOC ACTUALLY USES, read rather than assumed. The build
# order writes state as an emoji plus a word, and these are the four that appear.
_STATE = (
    ("✅", "done"),        # white heavy check mark
    ("\U0001f7e1", "partial"),  # large yellow circle
    ("\U0001f51c", "queued"),   # SOON arrow
    ("⏸", "discuss"),      # pause -- the owner's own stop
)


def _state_of(cell: str) -> str:
    """The state the doc GIVES a row, or `unmarked` -- never a guess.

    AN UNMARKED ROW IS NOT A ROW THAT IS NOT STARTED, and the first version of
    this said it was. Steps 1-9 carry no marker because the convention began at
    step 10; every one of them is built and gated -- the commands card, the
    explanations card, the changes card all have checks that pass. Reporting them
    as "not started" is a false reading of exactly the kind two settings rows
    produced from a wrong TOML key on the same day: it looks measured and is not.

    `INV-HW-2`'s rule applied to a document: what it does not say is unknown, and
    unknown is its own answer.
    """
    for mark, name in _STATE:
        if mark in cell:
            return name
    return "unmarked"


def project_rows() -> list:
    """Every step of the build order, with its state and what it is waiting on.

    PARSED FROM THE DOC RATHER THAN DUPLICATED. A second list of the steps would
    be a second thing to keep in step with the first, and `CI-089` exists because
    exactly that pair drifted eight times. The doc is the authority; this reads
    it.
    """
    try:
        text = PLAN.read_text(encoding="utf-8")
    except Exception:                                     # noqa: BLE001
        return [{"id": "plan", "name": "Build order", "status": "unavailable",
                 "reason": "the plan document could not be read"}]

    # The build order is the one table whose rows start with a step number or a
    # dash, inside the section that declares it.
    try:
        body = text[text.index("## 10. BUILD ORDER"):]
    except ValueError:
        return [{"id": "plan", "name": "Build order", "status": "unavailable",
                 "reason": "the plan document has no build order section"}]
    body = body[:body.index("\n---", 1)] if "\n---" in body[1:] else body

    out: list = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("#", "---") or set(cells[0]) <= {"-"}:
            continue
        num, name, ships = cells[0], cells[1], cells[2]
        if not num or num == "—":
            num = ""
        # THE NAME IS THE BOLD PART; the rest of the cell is its section
        # reference, which belongs in the detail rather than the title.
        m = re.match(r"\*\*(.+?)\*\*\s*(.*)", name)
        title = m.group(1) if m else name
        where = (m.group(2) if m else "").strip()
        state = _state_of(ships)
        # WHAT IT IS WAITING ON, taken from the step's own words rather than
        # guessed: the doc says "awaiting", "needs", "owed" where it applies.
        waiting = ""
        for cue in ("AWAITING", "awaiting", "needs ", "**Owed:**", "owed"):
            if cue in ships:
                seg = ships[ships.index(cue):]
                waiting = re.sub(r"[*`]", "", seg)[:160]
                break
        out.append({
            "id": f"step-{num or title[:18]}",
            "name": (f"{num}. {title}" if num else title),
            "status": "available",
            "state": state,
            "where": where[:60],
            "detail": re.sub(r"[*`]", "", ships)[:400],
            "waiting": waiting,
        })
    if not out:
        return [{"id": "plan", "name": "Build order", "status": "unavailable",
                 "reason": "the build order table could not be parsed"}]
    return out


def research_rows() -> list:
    """Every spike, with the status the index gives it.

    THE INDEX IS THE AUTHORITY AND `CLAUDE.md` SAYS SO: *"the status authority
    for every spike. The protocol documents' headers follow it, never the
    reverse."* So this reads the index and never a document's own header, which
    is the thing that has been wrong before.
    """
    try:
        doc = tomllib.loads(SPIKES.read_text(encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return [{"id": "spikes", "name": "Spikes", "status": "unavailable",
                 "reason": "the spike index could not be read"}]
    table = doc.get("spikes") or doc.get("spike") or {}
    if not isinstance(table, dict) or not table:
        return [{"id": "spikes", "name": "Spikes", "status": "unavailable",
                 "reason": "the index declares no spikes, so there is nothing to "
                           "count rather than zero of it"}]
    out = []
    for key, row in sorted(table.items()):
        row = row if isinstance(row, dict) else {}
        out.append({
            "id": str(key),
            "name": f"{key} — {row.get('title') or row.get('name') or 'untitled'}"[:110],
            "status": "available",
            "state": str(row.get("status") or "unknown").lower(),
            "where": str(row.get("path") or row.get("doc") or "")[:60],
            "detail": str(row.get("question") or row.get("note")
                          or row.get("summary") or "")[:400],
            "waiting": "",
        })
    return out
