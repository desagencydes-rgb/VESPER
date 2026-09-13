"""The projects dashboard (§28): phases, engineering modes, and what is in them.

THE OWNER'S SPECIFICATION, 2026-09-12: *"when i click the projects side button,
its dashboard pops up, has at the top places where i can switch between phases if
they were not chosen well, or switch between engineering modes (engineering
practices and engineering), or switch between engineering phases, i can control
the plans, code, designs, roadmap, practices, documents, terminal, commands,
history and anything helpful there."*

THREE SWITCHES, AND THEY ARE NOT THREE NAMES FOR ONE THING. Writing them as one
control is the first way this gets built wrong. The project's own phase is
CORRECTIVE -- the owner said "if they were not chosen well", so a phase can be set
wrongly and must be re-settable without losing what is filed under it. The
engineering MODE is a different axis entirely: practice versus work, two bodies of
material about the same project.

THE PANELS THAT ALREADY EXIST ARE COMPOSED, NEVER REBUILT. `terminal`, `commands`
and `history` are live cards with their own checks -- `CI-126` guards exactly one
terminal. A second implementation inside the dashboard would be a second thing to
keep correct and the older one would rot. Those panels carry `composes` naming the
surface that owns them, and no content of their own.

AND EVERY OTHER PANEL READS SOMETHING REAL OR SAYS WHY NOT. `core/settings_surface`
established the rule and two false zeros on the same day proved it necessary: a
panel that cannot read its source reports UNAVAILABLE **with the reason**, because
a zero that looks measured and is not is worse than an absence.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "policy" / "project_phases.toml"

# THE PANELS THE OWNER NAMED, in the order they were named. `anything helpful
# there` is deliberately NOT invented into a panel: §11.7 spent a night refusing
# to invent seventeen features nobody asked for, and the same restraint applies.
COMPOSED = {
    "terminal": "the terminal card (§6) -- one implementation, guarded by CI-126",
    "commands": "the commands card (§3) -- what actually ran, with its output",
    "history": "the conversation history surface",
}


def _contract() -> tuple[dict, str]:
    try:
        return tomllib.loads(CONTRACT.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return {}, "the phase contract is not on this node"
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {}, f"the phase contract could not be read: {type(e).__name__}"


def phases() -> list:
    """The declared phases, in order, or one row saying why there are none."""
    doc, why = _contract()
    rows = doc.get("phases") or []
    if not rows:
        return [{"id": "unavailable", "name": "UNAVAILABLE",
                 "what": why or "the contract declares no phases, so there is "
                                "nothing to count rather than zero of it"}]
    return [{"id": str(p.get("id") or ""), "name": str(p.get("name") or ""),
             "what": str(p.get("what") or "")} for p in rows if isinstance(p, dict)]


def modes() -> list:
    """Engineering, and engineering practices. Two, by the owner's own words."""
    doc, why = _contract()
    rows = doc.get("modes") or []
    if not rows:
        return [{"id": "unavailable", "name": "UNAVAILABLE",
                 "what": why or "the contract declares no modes"}]
    return [{"id": str(m.get("id") or ""), "name": str(m.get("name") or ""),
             "what": str(m.get("what") or "")} for m in rows if isinstance(m, dict)]


def _count(root: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in root.glob(pattern))
    except OSError:
        return -1


def panels(project_root: Path | None = None, mode: str = "work") -> list:
    """One row per panel, each reading its real source or saying why it cannot.

    `project_root` IS PASSED IN, NEVER DERIVED. `core/places.py` exists because
    `Path(__file__).parents[1]` resolves to the shipped copy when the runtime
    runs from the bundle, and vesper answered "list the project root" with the
    five directories `build.sh` ships. A surface about the project must be told
    which directory that is, like everything else now is.
    """
    out: list = []

    def panel(pid, name, what, **kw):
        row = {"id": pid, "name": name, "what": what, "mode": kw.pop("mode", "work")}
        row.update(kw)
        out.append(row)

    if project_root is None or not Path(project_root).is_dir():
        why = ("no project directory was supplied, so nothing here can be read. "
               "The dashboard refuses to guess which directory it is about")
        for pid, name in (("plans", "Plans"), ("code", "Code"),
                          ("designs", "Designs"), ("roadmap", "Roadmap"),
                          ("practices", "Practices"), ("documents", "Documents")):
            panel(pid, name, why, status="unavailable")
        for pid, what in COMPOSED.items():
            panel(pid, pid.capitalize(), what, status="composed", composes=what)
        return out

    root = Path(project_root)
    docs = root / "docs"
    design = docs / "design"

    n = _count(design, "*.md")
    panel("plans", "Plans",
          "the documents the work is planned in -- the authority every surface "
          "reads rather than a second copy of it",
          status="available" if n > 0 else "unavailable",
          value=(f"{n} planning document(s)" if n > 0 else
                 "docs/design carries no planning document on this node"),
          source="docs/design/*.md")

    mods = _count(root / "core", "*.py")
    panel("code", "Code",
          "the source itself, counted where it lives rather than estimated",
          status="available" if mods > 0 else "unavailable",
          value=(f"{mods} core module(s)" if mods > 0 else
                 "no core/ directory here -- this may not be the project"),
          source="core/*.py")

    refs = _count(docs, "**/*REFERENCE*") + _count(design, "*.png") + _count(design, "*.svg")
    panel("designs", "Designs",
          "the visual references the interface is built against",
          status="available" if refs > 0 else "unavailable",
          value=(f"{refs} reference(s)" if refs > 0 else
                 "no design reference found under docs/ on this node"),
          source="docs/**")

    # THE ROADMAP IS THE BUILD ORDER AND IS ALREADY PARSED. Reading it a second
    # way here would be a second thing to keep in step with the first, which is
    # the pair CI-089 exists because of.
    try:
        from core.rail_surfaces import project_rows
        steps = [r for r in project_rows() if r.get("status") == "available"]
        done = sum(1 for r in steps if r.get("state") == "done")
        panel("roadmap", "Roadmap",
              "the build order, read from the plan document that is its authority",
              status="available" if steps else "unavailable",
              value=(f"{len(steps)} step(s), {done} done" if steps else
                     "the build order could not be parsed"),
              source="the plan document's build order table")
    except Exception as e:                                 # noqa: BLE001
        panel("roadmap", "Roadmap", "the build order",
              status="unavailable",
              value=f"the build order reader failed: {type(e).__name__}")

    inv = root / "spec" / "invariants" / "INVARIANTS.toml"
    try:
        n_inv = len(tomllib.loads(inv.read_text(encoding="utf-8")).get("invariants") or {})
    except Exception:                                      # noqa: BLE001
        n_inv = -1
    panel("practices", "Practices",
          "how the work is done here -- the rules that are enforced rather than "
          "the ones that are hoped for",
          mode="practice",
          status="available" if n_inv > 0 else "unavailable",
          value=(f"{n_inv} declared invariant(s)" if n_inv > 0 else
                 "the invariant registry could not be read on this node"),
          source="spec/invariants/INVARIANTS.toml")

    # CONTRACTS ARE THEIR OWN PANEL, not a kind of document. The owner named
    # them beside engineering and designing, and they are different in a way
    # that matters here: a contract is GOVERNED -- `profile_node.py` has no
    # write path into `capability_profiles.toml`, deliberately, and promotion
    # into one is a separate reviewed act. A surface that filed them under
    # "documents" would invite editing them like prose.
    n_con = _count(root / "contracts", "**/*.toml")
    panel("contracts", "Contracts",
          "the governed files -- the rules the build is held to. Changing one is "
          "a reviewed act, never an edit, which is why they are not documents",
          status="available" if n_con > 0 else "unavailable",
          value=(f"{n_con} contract(s)" if n_con > 0 else
                 "no contracts/ directory here -- this may not be the project"),
          source="contracts/**/*.toml")

    n_docs = _count(docs, "**/*.md")
    panel("documents", "Documents",
          "everything written down about this project",
          status="available" if n_docs > 0 else "unavailable",
          value=(f"{n_docs} document(s)" if n_docs > 0 else
                 "no documents found under docs/ on this node"),
          source="docs/**/*.md")

    for pid, what in COMPOSED.items():
        panel(pid, pid.capitalize(), what, status="composed", composes=what)

    if mode:
        # THE MODE FILTERS, IT DOES NOT DELETE. A panel belonging to the other
        # mode is still returned, marked, so the surface can show what switching
        # would reveal rather than pretending it does not exist.
        for row in out:
            row["in_mode"] = (row.get("mode") == mode)
    return out
