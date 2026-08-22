"""The home's rooms, derived from the owner's own routing rather than asserted.

WHY THIS EXISTS. `DESIGN-FOUNDATION.md` §10 states the home holds 90 cards
"grouped into rooms rather than listed", and names six rooms with their counts.
Six rooms plus the four named front doors account for 81 of the 90. Nine cards
had no room, and a number that is quoted rather than recomputed is the failure
`CLAUDE.md` corrected on itself on 2026-08-21 -- the island reference drew "320k
assertions" because a stale line in `CLAUDE.md` said so.

So the rooms are computed here from the two files the owner actually produced:
`routing/data.json` (the catalogue) and `routing/routed.json` (where the owner
sent each item). Change either and this output changes with it.

THE ROOM RULE, stated before the counts so it cannot be fitted to them:
a card's room is its catalogue section. The owner routed by item, not by
section, but every item the owner sent to `home` came out of exactly one
section, and the sections are already the owner's own grouping of the corpus.
Inventing a second grouping on top would be a taxonomy nobody asked for.

THE TWELVE. Twelve catalogue rows appear in `data.json` and in no routing
decision -- the first row of each of the twelve sections, lost to a sticky
header in the tool the owner routed with. They are not "unrouted" in the sense
of undecided; they were never shown. They are home cards, and four of them are
front doors into surfaces that are their own space rather than rooms.

Stdlib only, per the convention for tools/ and docs/design/source/.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTING = HERE.parent / "routing"

# Section -> the room it becomes. FRONT DOORS are cards in the home that open a
# surface which is not a room: Settings and History are their own spaces
# (35 and 17 items), and Machine and Fabric keep their detail in the main menu
# (27 and 21 items) with one card in the home standing in front of it.
ROOMS = {
    "01": ("Frame",         "shell"),
    "02": ("Machine",       "front door -> main menu, 27 items"),
    "03": ("Fabric",        "front door -> main menu, 21 items"),
    "04": ("Doing",         "room"),
    "05": ("Permissions",   "room"),
    "06": ("Memory",        "room"),
    "07": ("Work",          "room"),
    "08": ("Tunables",      "front door -> Settings, 35 items"),
    "09": ("History",       "front door -> History, 17 items"),
    "10": ("Presence",      "room"),
    "11": ("Introspection", "room"),
    "12": ("Beyond",        "room"),
}

# What `st` means in the catalogue, and the build phase it implies. The phase is
# a FIRST CUT and is not authoritative -- `HOME-CONTENT.md` carries the decided
# one per card. It is printed because the shape of the distribution is the
# useful part: it says how much of the home can be built before a backend runs.
PHASE_OF_ST = {
    "live": "P",   # a producer exists in core/ today -- projection work only
    "spec": "B",   # specified in a contract, nothing produces it yet
    "you":  "B",   # owner-specified behaviour, no producer
    "new":  "B",   # new capability
    "sug":  "B",   # suggested, undesigned
}


def load() -> tuple[list, dict]:
    data = json.loads((ROUTING / "data.json").read_text(encoding="utf-8"))
    routed = json.loads((ROUTING / "routed.json").read_text(encoding="utf-8"))
    return data["sections"], {(r["sec"], r["name"]): r for r in routed}


def home_cards(sections: list, routes: dict) -> list[dict]:
    """Every card that lands in the home: routed there, or never shown at all."""
    out = []
    for sec in sections:
        for row in sec["rows"]:
            route = routes.get((sec["num"], row["name"]))
            if route is None:
                origin = "never-shown"          # the twelve
            elif route["dest"] == "home":
                origin = "routed"
            else:
                continue
            out.append({
                "sec": sec["num"],
                "room": ROOMS[sec["num"]][0],
                "name": row["name"],
                "st": row["st"],
                "origin": origin,
                "note": (route or {}).get("note", ""),
            })
    return out


def main() -> None:
    sections, routes = load()
    cards = home_cards(sections, routes)

    total_rows = sum(len(s["rows"]) for s in sections)
    never_shown = [c for c in cards if c["origin"] == "never-shown"]

    print(f"catalogue rows        {total_rows}")
    print(f"routing decisions     {len(routes)}")
    print(f"never shown (the 12)  {len(never_shown)}")
    print(f"routed to home        {len(cards) - len(never_shown)}")
    print(f"HOME CARDS            {len(cards)}")
    print()

    by_room: dict[str, list] = {}
    for c in cards:
        by_room.setdefault(c["sec"], []).append(c)

    print(f"{'room':<15}{'n':>4}  {'live':>5}{'spec':>5}{'new':>5}{'sug':>5}{'you':>5}   kind")
    for sec in sorted(by_room):
        room, kind = ROOMS[sec]
        rows = by_room[sec]
        st = Counter(c["st"] for c in rows)
        print(f"{room:<15}{len(rows):>4}  "
              f"{st['live']:>5}{st['spec']:>5}{st['new']:>5}{st['sug']:>5}{st['you']:>5}   {kind}")
    print(f"{'TOTAL':<15}{len(cards):>4}")
    print()

    phases = Counter(PHASE_OF_ST[c["st"]] for c in cards)
    print("first-cut phase, from the catalogue's own status field:")
    print(f"  P  producer exists in core/, needs the projection only   {phases['P']:>3}")
    print(f"  B  needs a producer that does not run yet                {phases['B']:>3}")
    print()

    # The correction this file exists to make, shown as arithmetic rather than
    # claimed. DESIGN-FOUNDATION §10 groups the home into six rooms plus the
    # frame, and separately names four cards as front doors. Between them they
    # leave seven cards with no home at all.
    grouped = {"Memory", "Work", "Doing", "Beyond", "Permissions", "Presence",
               "Frame"}
    front_doors_named = {"Tunables", "History"}     # "Tunables", "Conversation history"
    in_room = sum(1 for c in cards if c["room"] in grouped)
    named_only = sum(1 for c in cards if c["room"] in front_doors_named)
    orphan = Counter(c["room"] for c in cards
                     if c["room"] not in grouped | front_doors_named)

    print(f"DESIGN-FOUNDATION §10 puts {in_room} of {len(cards)} into a room,")
    print(f"and names {named_only} more as front doors without giving them one.")
    print(f"{sum(orphan.values())} cards are not mentioned at all: "
          + ", ".join(f"{k} {v}" for k, v in sorted(orphan.items())))
    print()
    print("So the home has NINE rooms, not six: the six named, plus Machine and")
    print("Fabric as front doors, plus Introspection as a room of its own.")


if __name__ == "__main__":
    main()
