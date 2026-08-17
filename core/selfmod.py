"""The self-modification boundary — INV-SELF-1..7, A-030.

REFUSED AT THE TOOL AND FILESYSTEM BOUNDARY, NOT BY MODEL DISPOSITION. A-030.1
says exactly that, and it is the whole design. A system that declines to edit
its own policy because it was instructed not to is one prompt away from
compliance; the fixture for A-030 is an OVERNIGHT autonomous run on INJECTED
external content with no human present, which is precisely the condition under
which disposition fails. So the refusal is a path check that runs before the
write, and it cannot be argued with because it does not read the argument.

WHAT SR-042 PRESERVES, and why this is not simply "deny everything". A-030.6
must SUCCEED: writing a complete patch to `policy/` **in the workspace**,
running it against the tests, and emitting a proposal at 03:00. That is the
system doing real overnight work on its own governance and asking for review in
the morning. Its mandatory negative control is a build adopting PATCH-018 as
literally worded ("free-time self-modification prohibited outright"), which must
FAIL 30.6 — the red run that proves the correction did not over-restrict.

The distinction the boundary draws is therefore not *what* is being edited but
*where*: a governed path in the RUNNING ARTIFACT is refused; the same content in
the WORKSPACE is the intended way to work.

INV-SELF-3: an L5 grant does not lift this. A-030.5 presents a forged AND a
valid L5 grant and both are refused unconditionally. A boundary that a
sufficiently privileged grant can cross is a boundary that an injected page
will eventually talk its way past.

THE GOVERNED LIST IS READ FROM A PINNED ARTIFACT (A-030.4). If the boundary
consulted a list the runtime could edit, shrinking the list would be the first
move — so `governed_surfaces.toml` is itself governed, and the pinned copy is
what is consulted.
"""

from __future__ import annotations

import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bus import EventBus

# THE GOVERNED LIST IS READ FROM THE PINNED ARTIFACT, NEVER HARDCODED HERE.
# A-030.4 requires the list to come from `contracts/policy/governed_surfaces.toml`,
# and the first version of this module hardcoded a copy instead. The copy had
# already drifted: it was missing `security/`, `spec/`, `models/`,
# `config/prompts/`, `config/personas/`, `routing/`, `docs/source/`, `docs/COC/`
# and `CODEOWNERS`, and it invented `docs/ADR/`. Every one of those omissions is
# a surface the boundary would have let the runtime write.
#
# That artifact names S6 as "THE SURFACE AN IMPLEMENTATION FORGETS -- a runtime
# that can edit its own tests can neutralise every other surface without
# touching one." A hardcoded copy is the same failure one level up: a boundary
# that reads a stale list defends a system that no longer exists.
GOVERNED_SURFACES_ARTIFACT = "contracts/policy/governed_surfaces.toml"

WORKSPACE_PREFIX = "workspace/"


def _norm(p: str) -> str:
    """Normalise a repo-relative path for comparison.

    NOT `lstrip("./")`. That strips any leading run of '.' and '/' characters,
    so `.github/workflows/` becomes `github/workflows/` and then matches
    nothing -- silently un-governing the directory that holds the CI which
    enforces every other boundary. Only a literal leading './' is removed.
    """
    p = str(p).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


class SelfModificationRefused(Exception):
    """A write to a governed path in the running artifact. Structural refusal."""


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    path: str
    rationale: str
    diff_summary: str
    tests_passed: bool
    created_at_wall: str = ""


class SelfModificationBoundary:
    """Path-based refusal. Never consults the model, never reads the content."""

    def __init__(self, bus: EventBus, *, repo_root: Path,
                 workspace_root: Path | None = None,
                 governed_artifact: Path | None = None) -> None:
        self._bus = bus
        self._repo = Path(repo_root).resolve()
        self._workspace = Path(workspace_root).resolve() if workspace_root else None
        self._proposals: dict[str, Proposal] = {}
        self._lock = threading.RLock()
        # Read once at construction from the PINNED artifact. Re-reading per
        # call would mean a runtime that managed to edit the file could widen
        # its own permissions between two writes.
        self._prefixes, self._exact = self._load_governed(
            governed_artifact or (self._repo / GOVERNED_SURFACES_ARTIFACT))

    @staticmethod
    def _load_governed(path: Path) -> tuple[tuple, tuple]:
        """Load GOVERNED_PATHS from the pinned artifact.

        A MISSING ARTIFACT IS FAIL-CLOSED, not fail-open. If the file cannot be
        read, the boundary does not fall back to "nothing is governed" -- it
        governs the whole repository, because a boundary that opens when its
        configuration goes missing is worse than no boundary at all: it looks
        like it is working.
        """
        if not path.exists():
            return (("",), ())     # "" is a prefix of every path
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return (("",), ())
        prefixes, exact = [], []
        for surface in (doc.get("surfaces") or {}).values():
            for raw in surface.get("paths", ()):
                p = _norm(raw)
                (prefixes if p.endswith("/") else exact).append(p)
        # The artifact itself is always governed, whatever it says about itself.
        exact.append(GOVERNED_SURFACES_ARTIFACT)
        return tuple(sorted(set(prefixes))), tuple(sorted(set(exact)))

    def governed_paths(self) -> dict:
        """What this boundary is actually enforcing. For audit, and for tests."""
        return {"prefixes": list(self._prefixes), "exact": list(self._exact),
                "source": GOVERNED_SURFACES_ARTIFACT}

    # ------------------------------------------------------------- the check

    def is_governed(self, rel_path: str) -> bool:
        p = _norm(rel_path)
        if p in self._exact:
            return True
        return any(p.startswith(pref) for pref in self._prefixes)

    def check_write(self, path: str | Path, *, subject: str = "runtime",
                    level: str = "L1", in_workspace: bool = False) -> None:
        """Raise if this write is refused. Called BEFORE the write, always.

        `level` is accepted and deliberately IGNORED for governed paths.
        INV-SELF-3: an L5 grant does not lift this boundary, so the parameter
        exists only so the audit record can show what was claimed.
        """
        p = Path(path)
        try:
            rel = p.resolve().relative_to(self._repo).as_posix()
        except ValueError:
            # Outside the repository entirely -- not this boundary's business.
            return

        if in_workspace or rel.startswith(WORKSPACE_PREFIX):
            return   # A-030.6: the workspace is where this work belongs

        if not self.is_governed(rel):
            return

        self._bus.publish(
            "selfmod.attempt_blocked", subject=subject,
            payload={"path": rel, "claimed_level": level,
                     "refused_by": "tool/filesystem boundary",
                     "note": ("refused structurally, not by model disposition. "
                              "INV-SELF-3: an L5 grant does not lift this -- a "
                              "boundary a privileged grant can cross is one an "
                              "injected page will eventually talk past."),
                     "remedy": "write the change in the workspace and propose it"},
            component="selfmod")
        raise SelfModificationRefused(
            f"write to governed path {rel!r} refused at the tool/filesystem "
            f"boundary (claimed level {level}, which is not consulted). Write it "
            "in the workspace and emit a proposal instead.")

    # -------------------------------------------------------------- proposals

    def propose(self, proposal: Proposal, *, subject: str = "runtime") -> Proposal:
        """A-030.6. The permitted route, and it must work unattended at 03:00."""
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
        self._bus.publish("selfmod.proposal_created", subject=subject,
                          payload={"proposal_id": proposal.proposal_id,
                                   "path": proposal.path,
                                   "tests_passed": proposal.tests_passed,
                                   "rationale": proposal.rationale},
                          component="selfmod")
        return proposal

    def delete_proposal(self, proposal_id: str, *,
                        subject: str = "runtime") -> None:
        """A-030.7: refused. A queue the runtime can prune is not a queue.

        The specific failure this prevents: refuse a proposal, the runtime
        deletes it, and the refusal leaves no trace -- so the same change comes
        back tomorrow as though it had never been considered.
        """
        self._bus.publish(
            "selfmod.attempt_blocked", subject=subject,
            payload={"proposal_id": proposal_id, "action": "delete_proposal",
                     "note": ("the runtime may create proposals and may not remove "
                              "them. A queue it can prune would let a refusal "
                              "vanish and the same change return as though never "
                              "considered.")},
            component="selfmod")
        raise SelfModificationRefused(
            f"deleting proposal {proposal_id!r} is refused; only the owner "
            "resolves a proposal")

    def proposals(self) -> list[Proposal]:
        with self._lock:
            return list(self._proposals.values())
