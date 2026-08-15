"""
tools/ci/checks.py -- runnable CI checks.

Each subcommand implements a check declared in verification/ci/CHECKS.toml.
Checks that are specified but not yet implemented are marked impl = "PENDING"
in that registry and are reported by `python tools/ci/checks.py status`, so the
gap between "specified" and "enforced" is always visible rather than implied.

Every check here has been run against its declared self_test. A check that has
only ever been green is not evidence.

Usage:
    python tools/ci/checks.py all
    python tools/ci/checks.py <name> [--self-test]
    python tools/ci/checks.py status

Stdlib only. Python >= 3.11.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKS = REPO / "verification" / "ci" / "CHECKS.toml"
INVARIANTS = REPO / "spec" / "invariants" / "INVARIANTS.toml"
SM_INDEX = REPO / "spec" / "state-machines" / "INDEX.toml"
DF_INDEX = REPO / "spec" / "decision-functions" / "INDEX.toml"
ACCEPTANCE = REPO / "verification" / "acceptance" / "INDEX.toml"
SCENE = REPO / "contracts" / "entities" / "semantic_scene.schema.json"
COST = REPO / "contracts" / "policy" / "cost_policy.toml"
GOVERNED = REPO / "contracts" / "policy" / "governed_surfaces.toml"
TRIGGERS = REPO / "contracts" / "policy" / "trigger_registry.toml"
LADDER = REPO / "contracts" / "policy" / "degradation_ladder.toml"
TUNABLES = REPO / "contracts" / "policy" / "tunables.toml"
CAPPROFILES = REPO / "contracts" / "policy" / "capability_profiles.toml"
LATENCY = REPO / "contracts" / "policy" / "latency_budgets.toml"

# Directories whose code must never name a product. Scanned once they exist;
# absence is not a pass, it is reported as "not yet applicable".
PRODUCT_NAME_SCOPES = ["routing", "resources", "policy", "world", "models",
                        # core/ added 2026-08-15 when F0/F1 landed. The router,
                        # the cost choke point and the policy skeleton all live
                        # here, and INV-HW-1 is precisely about routing, resource
                        # and policy paths. Scanning only the aspirational
                        # directories would have left the real ones uncovered.
                        "core"]
PRODUCT_NAMES = ["macbook neo", "macbook", "galaxy j3", " j3 ", "iphone"]


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


class Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.errors: list[str] = []
        self.notes: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------
# CI-041 / CI-043 -- the registries that make every other check auditable
# --------------------------------------------------------------------------
def check_ci_registry() -> Result:
    r = Result("ci-registry")
    checks = _load(CHECKS).get("checks", {})
    invs = _load(INVARIANTS).get("invariants", {})
    sms = _load(SM_INDEX).get("state_machines", {})
    dfs = _load(DF_INDEX).get("decision_functions", {})
    known_tests = set(_load(ACCEPTANCE).get("tests", {})) if ACCEPTANCE.is_file() else set()

    for cid, c in sorted(checks.items()):
        if not c.get("self_test"):
            r.err(f"{cid} declares no self_test -- a check that has never been red is not evidence")
        if not c.get("enforces"):
            r.err(f"{cid} enforces no invariant")
        for inv in c.get("enforces", []):
            if inv not in invs:
                r.err(f"{cid} enforces undeclared invariant {inv}")
        if not c.get("blocking"):
            r.err(f"{cid} declares no blocking level")

    # An invariant with no enforcement is a wish, not an invariant.
    for iid, inv in sorted(invs.items()):
        if not inv.get("enforced_by"):
            r.err(f"{iid} has an empty enforced_by -- it is a wish, not an invariant")
        if not inv.get("owner_rem"):
            r.err(f"{iid} declares no owning remediation spec")
        for ref in inv.get("enforced_by", []):
            if ref.startswith("CI-") and ref not in checks:
                r.err(f"{iid} is enforced_by undeclared check {ref}")

    # Every declared mechanism must have its spec file on disk.
    for label, doc, path in (("state machine", _load(SM_INDEX), SM_INDEX), ("decision function", _load(DF_INDEX), DF_INDEX)):
        spec = doc.get("spec")
        if not spec:
            r.err(f"{path.name} declares no spec file")
        elif not (REPO / spec).is_file():
            r.err(f"{path.name} references missing spec {spec}")

    # A declared ID is not an artifact. The same rule the traceability linter
    # applies to acceptance tests (TR-062) applied to mechanisms: every declared
    # SM-*/DF-* must actually appear in its specification file.
    for label, doc in (("state machine", _load(SM_INDEX)), ("decision function", _load(DF_INDEX))):
        spec = doc.get("spec")
        if not spec or not (REPO / spec).is_file():
            continue
        body = (REPO / spec).read_text(encoding="utf-8")
        key = "state_machines" if label == "state machine" else "decision_functions"
        for mid in sorted(doc.get(key, {})):
            if mid not in body:
                r.err(f"{label} {mid} is declared in the registry but does not appear in {spec}")

    # ----------------------------------------------------------------------
    # BIDIRECTIONAL CONSISTENCY. Until 2026-08-12 this registry was linted in
    # ONE DIRECTION ONLY: an invariant had to name SOME check, and a check had
    # to name SOME declared invariant. Neither side had to agree with the
    # other. Four false enforcement records survived that -- including
    # INV-SELF-2, a ratified COC v1.2 Part VII-A security clause, recording
    # enforcement by CI-016, an IMPLEMENTED AND PASSING check that contains no
    # non-narrowability logic at all. The registry read as though the clause
    # was defended today. It was not.
    #
    # An enforcement claim is a two-sided fact. If a check enforces an
    # invariant, the invariant is enforced by that check, and the registries
    # must both say so.
    #
    # SYMMETRY IS NOT TRUTH. Resolving a mismatch by ADDING the missing side
    # manufactures the very claim this rule exists to catch. Each of the 22
    # mismatches found on 2026-08-12 was resolved by deciding WHICH SIDE WAS
    # WRONG, and the four that were resolved by REMOVING a claim carry an
    # `enforcement_correction` field recording why.
    # ----------------------------------------------------------------------
    for cid, c in sorted(checks.items()):
        for inv in c.get("enforces", []):
            if inv in invs and cid not in invs[inv].get("enforced_by", []):
                r.err(
                    f"ASYMMETRIC ENFORCEMENT CLAIM: {cid} declares it enforces {inv}, but "
                    f"{inv}.enforced_by does not list {cid}. One of the two is false. Decide which "
                    f"-- do not close the gap by adding the missing side, which manufactures the "
                    f"claim this rule exists to catch."
                )
    for iid, inv in sorted(invs.items()):
        for ref in inv.get("enforced_by", []):
            if ref.startswith("CI-") and ref in checks and iid not in checks[ref].get("enforces", []):
                r.err(
                    f"ASYMMETRIC ENFORCEMENT CLAIM: {iid} declares it is enforced by {ref}, but "
                    f"{ref}.enforces does not list {iid}. An invariant may not claim enforcement "
                    f"from a check that does not perform it."
                )
        for ref in inv.get("enforced_by", []):
            if ref.startswith("A-") and ref not in known_tests:
                r.err(f"{iid} is enforced_by acceptance test {ref}, which is not declared in verification/acceptance/INDEX.toml")

    # ----------------------------------------------------------------------
    # RED-RUN COVERAGE. A check marked implemented whose declared self_test has
    # never been EXECUTED is a check that has only ever been green, which
    # CHECKS.toml's own header says is not evidence. Nothing verified that the
    # `impl` field and the red-run harness agreed: mark a check implemented,
    # forget the harness case, and this registry stayed green.
    # ----------------------------------------------------------------------
    harness = _harness_commands()
    for cid, c in sorted(checks.items()):
        impl = c.get("impl")
        if not impl or impl == "PENDING":
            continue
        if impl not in harness:
            r.err(
                f"{cid} is marked implemented as {impl!r}, but tools/ci/self_test.py runs no "
                f"red-then-green cycle against that command. A check that has only ever been "
                f"green is not evidence -- CHECKS.toml's own header says so."
            )
        if not c.get("self_test_evidence"):
            r.err(
                f"{cid} is implemented but records no `self_test_evidence` -- the executed red run, "
                f"not the intention to write one"
            )

    # Every invariant must be reachable from at least one mechanism or check.
    covered = {i for c in checks.values() for i in c.get("enforces", [])}
    covered |= {i for d in list(sms.values()) + list(dfs.values()) for i in d.get("enforces", [])}
    test_only = [i for i in sorted(invs) if i not in covered]
    for iid in test_only:
        r.note(f"{iid} is enforced only by acceptance tests, with no CI or mechanism binding")

    # ----------------------------------------------------------------------
    # THE HONEST ENFORCEMENT FIGURE. "14 of 53 checks implemented" is true and
    # flattering. It is not the number a reader wants, which is: how many
    # invariants does a machine defend TODAY? An invariant counts only if a
    # check that is implemented, symmetric in both registries, red-run by the
    # harness, and NOT SELF-REPORTED AS VACUOUS names it.
    # ----------------------------------------------------------------------
    vacuous = _vacuous_checks()
    defended = sorted(
        iid for iid, inv in invs.items()
        if any(
            ref in checks
            and checks[ref].get("impl") not in (None, "PENDING")
            and checks[ref]["impl"] in harness
            and iid in checks[ref].get("enforces", [])
            and ref not in vacuous
            for ref in inv.get("enforced_by", [])
        )
    )
    r.note(f"{len(checks)} checks, {len(invs)} invariants, {len(sms)} state machines, {len(dfs)} decision functions")
    pending = [c for c in checks.values() if c.get("impl") == "PENDING"]
    r.note(f"{len(pending)}/{len(checks)} checks are specified but not yet implemented (impl = PENDING)")
    r.note(f"{len(test_only)}/{len(invs)} invariants have no CI or mechanism binding at all (acceptance-test prose only)")
    r.note(
        f"ENFORCED TODAY: {len(defended)}/{len(invs)} invariants are named by an implemented, "
        f"bidirectionally consistent, red-run, non-vacuous check"
        + (f"; vacuous on this tree: {', '.join(sorted(vacuous))}" if vacuous else "")
    )
    return r


def _harness_commands() -> set[str]:
    """The commands tools/ci/self_test.py actually runs a red-then-green cycle against.

    Derived from the harness's own case lists, never from a hand-kept list --
    a coverage claim maintained by hand is the thing this is checking for.
    """
    sys.path.insert(0, str(REPO / "tools" / "ci"))
    try:
        import self_test  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - reported, not raised
        return {f"<self_test.py unimportable: {exc}>"}
    cmds = {f"tools/ci/checks.py {c[0]}" for c in self_test.CASES}
    cmds |= {f"tools/ci/checks.py {c[0]}" for c in self_test.CREATE_CASES}
    cmds |= {f"tools/ci/checks.py {c[0]}" for c in self_test.SCENARIO_CASES}
    cmds |= {" ".join(c[0]) for c in self_test.LINT_CASES}
    return cmds


def _vacuous_checks() -> set[str]:
    """Checks that run but currently have no subject on this tree.

    A check whose scan set is empty passes for the wrong reason. Counting it as
    enforcement inflates the figure, so it is named instead of hidden.
    """
    vac = set()
    if not any((REPO / s).is_dir() for s in PRODUCT_NAME_SCOPES):
        vac.add("CI-007")
    if not any((REPO / p).is_dir() and any(f.is_file() for f in (REPO / p).rglob("*")) for p in F0_GATED_PATHS):
        vac.add("CI-008")
    return vac


# --------------------------------------------------------------------------
# CI-028 -- INV-SCENE-3: no free-form markup escape hatch in the scene schema
# --------------------------------------------------------------------------
def check_scene_schema(self_test: bool = False) -> Result:
    r = Result("scene-no-escape-hatch")
    if not SCENE.is_file():
        r.err("semantic_scene.schema.json missing")
        return r
    raw = SCENE.read_text(encoding="utf-8")
    doc = json.loads(raw)

    banned = re.compile(r'"(markdown|md|html|rich_text|raw_html|innerHTML|body_md)"\s*:', re.I)
    for m in banned.finditer(raw):
        r.err(f"scene schema exposes a free-form markup field: {m.group(1)}")

    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    for pname in v:
                        if re.fullmatch(r"(markdown|html|rich_text|raw.*)", pname, re.I):
                            r.err(f"{path}.properties.{pname} is a markup escape hatch")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc)

    if self_test:
        probe = json.loads(raw)
        probe["properties"]["markdown"] = {"type": "string"}
        found = "markdown" in probe["properties"]
        r.note(f"self-test: injected markdown field would be detected = {found}")
        if not found:
            r.err("self-test failed: the check cannot detect an injected markup field")
    return r


# --------------------------------------------------------------------------
# CI-021 / CI-022 -- INV-COST-1, INV-COST-4
# --------------------------------------------------------------------------
def check_cost_policy() -> Result:
    r = Result("cost-policy")
    if not COST.is_file():
        r.note("no cost policy loaded -- gateway permits cost_class 'free' only (INV-COST-6). Safe by default.")
        return r
    doc = _load(COST)
    permitted = doc.get("permitted_cost_classes", {})
    for restricted in ("FREE_TIME", "DO_NOT_DISTURB", "IDLE"):
        classes = permitted.get(restricted)
        if classes is None:
            r.err(f"permitted_cost_classes.{restricted} is undeclared -- absence must not be inferred as permissive")
        elif classes != ["free"]:
            r.err(
                f"INV-COST-1 violated: permitted_cost_classes.{restricted} = {classes}. "
                f"Only 'free' is permissible during a restricted period, under any inference input."
            )
    mft = doc.get("metered_free_tier", {})
    if mft.get("treat_as") != "paid":
        r.err("INV-COST-5 violated: metered_free_tier must be treated as 'paid' absent a provable hard cap")
    ex = doc.get("exhaustion", {})
    if ex.get("escalate_to_paid") is not False:
        r.err("INV-COST-1 violated: exhaustion must not escalate to paid")
    if ex.get("wake_user") is not False:
        r.err("SR-042 violated: ordinary work must not wake the user")
    return r


# --------------------------------------------------------------------------
# CI-016 -- governed surfaces integrity (REM-004)
# --------------------------------------------------------------------------
def check_governed_surfaces() -> Result:
    r = Result("governed-surfaces-integrity")
    if not GOVERNED.is_file():
        r.err("governed_surfaces.toml missing -- DF-GOVERNED-WRITE fails closed, but the boundary is undefined")
        return r
    doc = _load(GOVERNED)
    surfaces = doc.get("surfaces", {})
    all_paths = {p for s in surfaces.values() for p in s.get("paths", [])}

    for sid, s in sorted(surfaces.items()):
        if not s.get("paths"):
            r.err(f"surface {sid} declares no paths -- a surface that protects nothing is a heading")
        if not s.get("contents"):
            r.err(f"surface {sid} declares no `contents` -- an unexplained boundary is unreviewable")

    # Surface 6 is the one an implementation forgets: a runtime that can edit
    # its own tests can neutralise every other surface without touching one.
    required = {
        "policy/": "authorization and cost policy",
        "security/": "identity, secrets, audit",
        "core/": "runtime, lifecycle, event bus",
        "verification/": "the tests that check the boundary",
        "tools/": "the linters that check the boundary",
        "docs/COC/": "the SR/COC layer",
    }
    # DIRECTION MATTERS, AND SO DOES THE COMPONENT BOUNDARY.
    #
    # A declared path protects a required subtree only if the DECLARED path is a
    # prefix of the REQUIRED one AT A PATH-COMPONENT BOUNDARY. Two defects have
    # been found here, both by executing a probe rather than reading the code:
    #
    #  2026-08-12 (a): the test ran in the WRONG DIRECTION -- it asked whether
    #  any declared path started with the required path, so surface 5's single
    #  file `verification/traceability/registry.toml` satisfied the requirement
    #  for `verification/`, and surface 6 could be deleted with this check green.
    #
    #  2026-08-12 (b): the corrected form used a STRING prefix, so declaring
    #  paths = ["v", "t"] satisfied `verification/` and `tools/` while protecting
    #  two directories that do not exist. Corrected to a component-boundary test.
    def covers(declared: str, req: str) -> bool:
        d, q = declared.rstrip("/"), req.rstrip("/")
        return bool(d) and (q == d or q.startswith(d + "/"))

    for path, why in required.items():
        if not any(covers(p, path) for p in all_paths):
            r.err(f"GOVERNED_PATHS omits {path} ({why})")

    # SPECIFIC FILES whose loss would be silent. A surface may name a directory
    # that does not exist yet -- core/ and security/ are future runtime paths and
    # that is correct. But a surface pointing at a directory that will NEVER
    # exist because the artifact it means to protect lives elsewhere is dead
    # configuration, and dead configuration reads as protection. Surface 7
    # declared `autonomy/triggers/` while the shipped registry has always been
    # contracts/policy/trigger_registry.toml.
    must_be_governed = {
        "contracts/policy/trigger_registry.toml": "the SHIPPED trigger registry (INV-TRIG-7: a model may propose a trigger, never be one)",
        "contracts/policy/governed_surfaces.toml": "this file -- a boundary whose definition the runtime can edit is not a boundary",
        "contracts/policy/cost_policy.toml": "the cost policy (INV-COST-1)",
        "verification/ci/CHECKS.toml": "the CI enforcement registry",
        "spec/invariants/INVARIANTS.toml": "the invariant registry",
        "tools/ci/checks.py": "the checks themselves",
        ".github/workflows/ci.yml": "the workflow that runs them",
    }
    for f, why in sorted(must_be_governed.items()):
        if not any(covers(p, f) for p in all_paths):
            r.err(f"GOVERNED_PATHS does not cover {f} ({why})")
        if not (REPO / f).exists():
            r.err(f"{f} is required to be governed but does not exist on disk")

    # CODEOWNERS COVERAGE. CI-044 (was this change reviewed by the owner?) needs
    # git history and branch protection and stays PENDING. The STATIC half needs
    # neither: a governed path with no CODEOWNERS line will never be routed to a
    # reviewer even once branch protection exists, so the gate would be open on
    # that path and nothing would say so.
    codeowners = REPO / "CODEOWNERS"
    if not codeowners.is_file():
        r.err("CODEOWNERS is missing -- every governed path would merge unreviewed once branch protection exists")
    else:
        owned = [
            line.split()[0].strip("/")
            for line in codeowners.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and not line.strip().startswith("*")
        ]
        for p in sorted(all_paths):
            if not any(covers(o, p.rstrip("/")) for o in owned):
                r.err(
                    f"governed path {p} has no CODEOWNERS entry -- CI-044 will never route it to a "
                    f"reviewer, so the boundary is declared but unrouted"
                )

    if "workspace" not in doc:
        r.err(
            "no workspace declared -- INV-SELF-7 requires an unrestricted L2 workspace, "
            "or the boundary over-restricts and violates SR-042"
        )
    elif doc["workspace"].get("level") != "L2":
        r.err("workspace must be L2; a higher level would gate overnight coding that SR-042 authorizes")
    return r


# --------------------------------------------------------------------------
# CI-008 -- INV-ADR-1: the F0 merge gate.
#
#   "No change under core/, tasks/ or memory/ may merge while ADR-001, ADR-002
#    or ADR-012 is not ACCEPTED."
#
# This was PENDING until 2026-08-12, on the stated ground that it needs git
# history. It does not. The invariant is a property of the TREE, not of the
# diff: if a file exists under a gated path while a required ADR is not
# ACCEPTED, that file merged under an open gate. Checking the tree catches the
# same violation one step later and needs no history at all.
#
# The ADR status is read from THE ADR FILE, never from docs/ADR/ADR-REGISTER.md.
# Reading the register would be metadata-only verification: an index can be
# edited to say ACCEPTED without anyone accepting anything. The register is then
# cross-checked AGAINST the files, so a divergence between the two is itself a
# failure -- in either direction.
# --------------------------------------------------------------------------
ADR_DIR = REPO / "docs" / "ADR"
ADR_REGISTER = ADR_DIR / "ADR-REGISTER.md"

# INV-ADR-1 names these three. The list lives here, in a governed surface, so
# that shortening it is a human-merged edit rather than a config tweak.
F0_REQUIRED_ADRS = {
    "ADR-001": "coordination substrate -- clock, delivery, ordering, supersession",
    "ADR-002": "persistence -- durable stores, fencing, checkpoints, migration, recovery",
    "ADR-012": "deployment topology -- the runtime/repository boundary",
}
F0_GATED_PATHS = ["core", "tasks", "memory"]
ADR_STATUS_VOCAB = {"ACCEPTED", "PROPOSED", "SUPERSEDED", "REJECTED", "DEFERRED"}

_ADR_STATUS_RE = re.compile(r"\*\*Status\*\*\s*\|\s*\*{0,2}([A-Z_]+)")
_REGISTER_ROW_RE = re.compile(r"^\|\s*\*\*(ADR-\d{3})\*\*\s*\|[^|]*\|\s*\*{0,2}([A-Z_]+)", re.M)


def _adr_file_status(adr_id: str) -> tuple[str | None, str | None]:
    """(status, path) read from the ADR record itself. (None, None) if unfiled."""
    for f in sorted(ADR_DIR.glob(f"{adr_id}-*.md")):
        m = _ADR_STATUS_RE.search(f.read_text(encoding="utf-8")[:2000])
        return (m.group(1) if m else "UNPARSEABLE"), f.relative_to(REPO).as_posix()
    return None, None


def check_adr_gate() -> Result:
    r = Result("adr-gate")

    statuses: dict[str, str] = {}
    for adr, subject in sorted(F0_REQUIRED_ADRS.items()):
        status, path = _adr_file_status(adr)
        if status is None:
            r.err(
                f"{adr} ({subject}) has no decision record on disk. INV-ADR-1 gates F0 on its "
                f"acceptance; an unfiled ADR can never be ACCEPTED, so the gate would be "
                f"permanently and silently open."
            )
            statuses[adr] = "MISSING"
            continue
        if status == "UNPARSEABLE":
            r.err(f"{adr} record {path} declares no parseable **Status** -- an unstatused decision record is a draft")
        elif status not in ADR_STATUS_VOCAB:
            r.err(
                f"{adr} record {path} carries Status {status!r}, which is not one of "
                f"{sorted(ADR_STATUS_VOCAB)}. A status outside the vocabulary is unreadable by "
                f"this gate, and an unreadable gate is not a gate."
            )
        statuses[adr] = status

    # Register/file divergence, both directions.
    if not ADR_REGISTER.is_file():
        r.err("docs/ADR/ADR-REGISTER.md is missing -- ADR statuses have no index to cross-check against")
    else:
        rows = dict(_REGISTER_ROW_RE.findall(ADR_REGISTER.read_text(encoding="utf-8")))
        for adr in sorted(F0_REQUIRED_ADRS):
            filed, reg = statuses.get(adr), rows.get(adr)
            if reg is None:
                r.err(f"{adr} has no row in ADR-REGISTER.md")
            elif filed not in (None, "MISSING", "UNPARSEABLE") and reg != filed:
                r.err(
                    f"{adr}: the register says {reg} and the record says {filed}. A decision has one "
                    f"status. Whichever is wrong, the gate cannot be trusted while they disagree."
                )

    not_accepted = sorted(a for a, s in statuses.items() if s != "ACCEPTED")

    # Which gated paths actually contain code?
    populated = []
    for p in F0_GATED_PATHS:
        d = REPO / p
        if d.is_dir() and any(f.is_file() for f in d.rglob("*")):
            populated.append(p)

    if populated and not_accepted:
        for p in populated:
            files = sorted(
                f.relative_to(REPO).as_posix() for f in (REPO / p).rglob("*") if f.is_file()
            )[:5]
            r.err(
                f"INV-ADR-1 violated: {p}/ contains {len(files)} or more files "
                f"({', '.join(files)}) while {', '.join(f'{a} is {statuses[a]}' for a in not_accepted)}. "
                f"No change under core/, tasks/ or memory/ may merge until all of "
                f"{', '.join(sorted(F0_REQUIRED_ADRS))} are ACCEPTED."
            )
    elif populated:
        r.note(f"gated paths populated ({', '.join(populated)}); all required ADRs ACCEPTED -- F0 may proceed")
    else:
        r.note(
            "gate ARMED and not yet applicable: no files exist under "
            + ", ".join(f"{p}/" for p in F0_GATED_PATHS)
            + ". This is a pass because there is nothing to block, not because the gate is satisfied."
        )

    r.note("ADR status read from the records: " + ", ".join(f"{a}={statuses.get(a)}" for a in sorted(F0_REQUIRED_ADRS)))
    if not_accepted:
        r.note(
            f"F0 IS BLOCKED: {', '.join(not_accepted)} not ACCEPTED. Resolution is owner-reserved "
            f"(OWNER-DECISION-006(b)); this check does not and may not discharge it."
        )
    return r


# --------------------------------------------------------------------------
# CI-007 -- INV-HW-1: no product names in routing/resource/policy logic
# --------------------------------------------------------------------------
def check_product_names() -> Result:
    r = Result("no-product-names")
    scanned = 0
    for scope in PRODUCT_NAME_SCOPES:
        d = REPO / scope
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if not f.is_file() or f.suffix not in {".py", ".ts", ".js", ".rs", ".go", ".toml", ".json", ".yaml"}:
                continue
            scanned += 1
            text = f.read_text(encoding="utf-8", errors="replace").lower()
            for name in PRODUCT_NAMES:
                if name.strip() in text and "product-name-ok" not in text:
                    r.err(f"{f.relative_to(REPO).as_posix()} references product name {name.strip()!r} (INV-HW-1)")
    if scanned == 0:
        r.note("not yet applicable: no implementation directories exist (production code is not yet authorised)")
    else:
        r.note(f"scanned {scanned} files across {PRODUCT_NAME_SCOPES}")
    return r


# --------------------------------------------------------------------------
# CI-026 -- INV-AUTO-5 / INV-IDEA-5: the shipped trigger registry may not
# consist exclusively of SCHEDULE-class predicates.
#
# WHAT THIS CHECK USED TO BE, AND WHY THAT WAS NOT ENOUGH
#
# Until 2026-08-12 this check read the `predicate_class` LABEL and nothing
# else. An independent probe replaced the improvement-backlog predicate body
# with `schedule.cron("0 3 * * *")`, left the label at "COMPOSITE", and the
# check printed "8/8 enabled and non-SCHEDULE" and exited 0. That build IS the
# C1 pure-cron negative control. The declared self-test only ever mutated the
# label, so the defect was invisible to the harness as well: label-only
# validation, verified by a label-only red run.
#
# WHAT IT IS NOW
#
# The predicate BODY is parsed into a boolean expression over atoms, every
# dotted namespace root is classified against a closed vocabulary, and three
# semantic properties are asserted:
#
#   1. UNCLASSIFIABLE IS A FAILURE. Every dotted root must appear in
#      SCHEDULE_ROOTS or STATE_ROOTS below. A predicate that invents
#      `tick.every("3h")` does not get classified as state by default -- it
#      fails. Extending the vocabulary is an edit to tools/ (governed surface
#      S6) and therefore requires a human merge, which is the point.
#   2. A NON-SCHEDULE TRIGGER MUST HAVE A NON-SCHEDULE TERM. Not a label: an
#      atom whose namespace roots are world/task/node/event state.
#   3. THE CLOCK ALONE MUST NOT FIRE IT. Every schedule-only atom is set TRUE,
#      every other atom FALSE, and the expression is evaluated. If it comes out
#      TRUE, the predicate can fire with the world model saying nothing, which
#      is cron regardless of what the row is called. `NOT <state>` evaluates
#      TRUE under this substitution deliberately: the adversarial direction is
#      the one that makes firing EASIER.
#
# KNOWN LIMIT, STATED RATHER THAN HIDDEN. A predicate of the form
# `world.<dummy> AND schedule.cron(...)` passes this check, because deciding
# whether a state term is load-bearing requires evaluating it against a world
# model, and no evaluator exists before F0. That residue is A-029's job: an
# externally injected observation, at a time drawn OUTSIDE the system, must
# cause a trigger to fire. CI-026 proves the registry is state-shaped;
# A-029 proves the running system is not anticipating the clock. Both are
# required and they fail for different reasons.
#
# This check is only meaningful because contracts/policy/trigger_registry.toml
# is a SHIPPED PRODUCT ARTIFACT. It additionally requires every row to name the
# requirement that wanted the behaviour, so a trigger invented to keep this
# check green is visible as a row with no `source`.
# --------------------------------------------------------------------------

# Namespaces that denote A CLOCK. A predicate over these alone is a schedule.
SCHEDULE_ROOTS = {
    "schedule", "clock", "timer", "cron", "time", "calendar", "cadence",
    "interval", "tick", "period", "wallclock", "elapsed", "every", "at",
}

# Namespaces that denote WORLD, TASK, NODE or EVENT STATE. This vocabulary is
# closed on purpose: a predicate naming a root outside both sets FAILS rather
# than being classified as state by default. Adding a root is a governed-surface
# edit and must name the trigger that needed it.
STATE_ROOTS = {
    "world",              # world model facts, owner attention, host health, fabric
    "tasks",              # running/queued task state
    "backlog",            # improvement backlog (REM-015)
    "nodes", "node",      # fabric membership, reachability, per-node posture
    "events",             # event bus (EVENT-class predicates)
    "proposals",          # change-proposal queue (REM-004)
    "maps",               # knowledge maps (REM-010)
    "alarm",              # alarm record state: lease, acknowledgement, window
    "storage",            # tombstones, integrity chain (REM-016)
    "security_baseline",  # node posture terms used by ADR-007 D4 re-attestation
    "key_storage_class",
    "locator",            # knowledge-map source locator
    "freshness",          # knowledge-map freshness record
}
EVENT_ROOTS = {"events"}

# A cron expression is the canonical schedule primitive. It may appear only in a
# predicate that ADMITS to being SCHEDULE-class.
CRON_LITERAL = re.compile(r"\bcron\s*\(|(?<![\w*/-])[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+\s+[\d*/,-]+(?![\w*/-])")
DOTTED_ROOT = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\s*\.")

# The shipped rows whose disappearance would silently remove a specified
# behaviour. Each names the clause it carries. Retiring one is an edit to THIS
# FILE -- a governed surface (S6) -- and therefore requires a human merge. That
# friction is deliberate: the registry's own header warns that quiet removal
# "is how the anti-cron property would be lost quietly", and disabling is
# quieter than removing.
REQUIRED_TRIGGERS = {
    "trg_improvement_backlog": "INV-IDEA-5 / REM-015 -- idle capacity does autonomous improvement work",
    "trg_placement_reevaluate": "INV-PLACE-1/2 / SR-060 -- 'where should I be running right now?'",
    "trg_fact_expiry_sweep": "INV-COORD-2 -- an expired fact becomes UNKNOWN rather than staying current",
    "trg_record_loss_detected": "INV-LOSS-2/3 / REM-016 -- a vanished record is surfaced, not forgotten",
    "trg_alarm_fire": "INV-ALARM-1/2/3 / SR-043 -- a due alarm fires under partition",
    "trg_proposal_awaiting_review": "INV-SELF-1 / OWNER-DECISION-001 -- proposals reach the owner event-driven",
    "trg_map_stale": "SR-007 / REM-007 §4.5 -- the worked example of a standing goal",
    "trg_reattestation_due": "INV-TRUST-1 / ADR-007 D4 -- posture change re-attests immediately",
}


def _balanced(s: str) -> bool:
    depth = 0
    for c in s:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _split_top(expr: str, op: str) -> list[str]:
    """Split on `op` at bracket depth 0."""
    parts, depth, last, i, n = [], 0, 0, 0, len(expr)
    while i < n:
        c = expr[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            parts.append(expr[last:i])
            i += len(op)
            last = i
            continue
        i += 1
    parts.append(expr[last:])
    return parts


def parse_predicate(expr: str):
    """Boolean expression tree over opaque atoms: ('and'|'or', [..]) | ('not', n) | ('atom', s)."""
    expr = re.sub(r"\s+", " ", expr).strip()
    while expr.startswith("(") and expr.endswith(")") and _balanced(expr[1:-1]):
        expr = expr[1:-1].strip()
    for op, tag in ((" OR ", "or"), (" AND ", "and")):
        parts = _split_top(expr, op)
        if len(parts) > 1:
            return (tag, [parse_predicate(p) for p in parts])
    if expr.startswith("NOT "):
        return ("not", parse_predicate(expr[4:]))
    return ("atom", expr)


def _atoms(node) -> list[str]:
    k = node[0]
    if k == "atom":
        return [node[1]]
    if k == "not":
        return _atoms(node[1])
    return [a for c in node[1] for a in _atoms(c)]


def _evaluate(node, truth) -> bool:
    k = node[0]
    if k == "atom":
        return truth(node[1])
    if k == "not":
        return not _evaluate(node[1], truth)
    if k == "and":
        return all(_evaluate(c, truth) for c in node[1])
    return any(_evaluate(c, truth) for c in node[1])


def classify_atom(atom: str) -> tuple[set[str], set[str]]:
    """Return (namespace roots found, tags in {SCHEDULE, STATE, EVENT, UNKNOWN})."""
    roots = {m.group(1) for m in DOTTED_ROOT.finditer(atom)}
    tags: set[str] = set()
    for root in roots:
        if root in SCHEDULE_ROOTS:
            tags.add("SCHEDULE")
        elif root in EVENT_ROOTS:
            tags.add("EVENT")
        elif root in STATE_ROOTS:
            tags.add("STATE")
        else:
            tags.add("UNKNOWN")
    return roots, tags


def check_trigger_registry() -> Result:
    r = Result("non-schedule-trigger-present")
    if not TRIGGERS.is_file():
        r.err(
            "contracts/policy/trigger_registry.toml is missing -- INV-AUTO-5 cannot be "
            "evaluated, and an unevaluable invariant is not an invariant"
        )
        return r
    doc = _load(TRIGGERS)
    triggers = doc.get("triggers", {})
    if not triggers:
        r.err("trigger registry declares no triggers")
        return r

    classes: dict[str, str | None] = {}
    effective: dict[str, str] = {}
    state_driven_enabled: list[str] = []

    for tid, t in sorted(triggers.items()):
        pc = t.get("predicate_class")
        classes[tid] = pc
        if pc not in {"SCHEDULE", "STATE", "EVENT", "COMPOSITE"}:
            r.err(f"{tid} has invalid predicate_class {pc!r}")
        if not t.get("source"):
            r.err(
                f"{tid} declares no `source` -- a trigger that names no requirement is a "
                f"filler row added to satisfy this check, which is what the anti-cron "
                f"clause forbids"
            )
        if t.get("actuation_scope") not in {"NONE", "AUTONOMOUS_ACTUATION", "ALARM_ACTUATION"}:
            r.err(f"{tid} declares no valid actuation_scope (REM-005 binding)")
        if not t.get("resource_budget"):
            r.err(f"{tid} declares no resource_budget")
        if t.get("enabled") not in (True, False):
            r.err(f"{tid} declares no boolean `enabled` -- an unstated enablement is not a shipped decision")

        predicate = t.get("predicate")
        if not predicate:
            r.err(f"{tid} declares no predicate")
            effective[tid] = "NONE"
            continue

        # ------------------------------------------------ SEMANTIC ANALYSIS
        tree = parse_predicate(predicate)
        atoms = _atoms(tree)
        sched_only: set[str] = set()
        has_state = has_event = has_sched = False
        for atom in atoms:
            roots, tags = classify_atom(atom)
            if not roots:
                r.err(
                    f"{tid}: predicate term {atom!r} names no namespace. Every term must be a "
                    f"comparison over a declared world-model, task, node or event namespace, or "
                    f"the anti-cron analyser cannot classify it."
                )
                continue
            unknown = sorted(roots - SCHEDULE_ROOTS - STATE_ROOTS)
            if unknown:
                r.err(
                    f"{tid}: predicate term {atom!r} references unclassifiable namespace(s) "
                    f"{unknown}. The classification vocabulary in tools/ci/checks.py is closed on "
                    f"purpose -- a new root is a governed-surface edit requiring a human merge, "
                    f"not a way to make a clock look like world state."
                )
                continue
            if "SCHEDULE" in tags:
                has_sched = True
            if "STATE" in tags:
                has_state = True
            if "EVENT" in tags:
                has_event = True
            if tags == {"SCHEDULE"}:
                sched_only.add(atom)

        if has_sched and not (has_state or has_event):
            eff = "SCHEDULE"
        elif has_sched:
            eff = "COMPOSITE"
        elif has_event:
            # An `events.` reference is definitive: the predicate observes the
            # bus. A co-occurring state term qualifies WHICH event, it does not
            # make the row state-polled.
            eff = "EVENT"
        elif has_state:
            eff = "STATE"
        else:
            eff = "UNCLASSIFIED"
        effective[tid] = eff

        if CRON_LITERAL.search(predicate) and pc != "SCHEDULE":
            r.err(
                f"{tid}: the predicate contains a cron expression but is declared {pc}. A cron "
                f"expression is the canonical schedule primitive; a row that uses one and calls "
                f"itself STATE/EVENT/COMPOSITE is the C1 build wearing autonomy's vocabulary."
            )

        if pc != "SCHEDULE":
            if eff == "SCHEDULE":
                r.err(
                    f"INV-AUTO-5 violated: {tid} is declared {pc} but its EFFECTIVE PREDICATE is "
                    f"purely schedule-driven -- every term is a clock term. The label is not the "
                    f"trigger; the predicate is."
                )
            elif eff == "UNCLASSIFIED":
                r.err(f"{tid}: predicate could not be classified; see the term errors above")
            else:
                # THE DECISIVE TEST. Grant every clock term; deny every world-state
                # term. If the predicate still fires, the clock alone is sufficient.
                fires_on_clock_alone = _evaluate(tree, lambda a: a in sched_only)
                if fires_on_clock_alone:
                    r.err(
                        f"INV-AUTO-5 violated: {tid} FIRES ON THE CLOCK ALONE. With every "
                        f"world-state term false and every schedule term true, the predicate "
                        f"evaluates TRUE. A clock may be an input; it may never be sufficient."
                    )
                elif t.get("enabled") is True:
                    state_driven_enabled.append(tid)

        if pc in ("STATE", "EVENT") and has_sched:
            r.err(
                f"{tid} is declared {pc} but its predicate contains a schedule term. A row with a "
                f"clock term is COMPOSITE at best; calling it {pc} understates the clock's role."
            )
        if pc == "EVENT" and not has_event:
            r.err(f"{tid} is declared EVENT but its predicate observes no `events.` namespace")
        if pc == "STATE" and not has_state:
            r.err(f"{tid} is declared STATE but its predicate reads no world/task/node state")
        if pc == "SCHEDULE" and not has_sched:
            r.err(f"{tid} is declared SCHEDULE but its predicate contains no clock term")

    # ------------------------------------------------------- INV-AUTO-5 global
    if not state_driven_enabled:
        r.err(
            "INV-AUTO-5 violated: the shipped trigger registry contains no ENABLED trigger whose "
            "predicate genuinely requires world state to fire. This build is cron wearing "
            "autonomy's vocabulary (the C1 negative control)."
        )

    # ------------------------------------------ deletion / disablement bypass
    for tid, why in sorted(REQUIRED_TRIGGERS.items()):
        t = triggers.get(tid)
        if t is None:
            r.err(
                f"{tid} is absent from the shipped registry. It carries {why}. A load-bearing "
                f"product row is not a fixture, and removing one during cleanup is how the "
                f"property it carries would be lost quietly."
            )
        elif t.get("enabled") is not True:
            r.err(
                f"{tid} is present but NOT ENABLED. It carries {why}. Disabling is quieter than "
                f"removing and has the same effect on the shipped build."
            )
        elif effective.get(tid) == "SCHEDULE":
            r.err(f"{tid}'s effective predicate is schedule-only. It carries {why}.")

    backlog = triggers.get("trg_improvement_backlog")
    if backlog is not None and backlog.get("predicate_class") == "SCHEDULE":
        r.err(
            "INV-IDEA-5 violated: trg_improvement_backlog is SCHEDULE-class. A clock alone may "
            "never cause backlog work to begin."
        )

    r.note(
        f"{len(triggers)} triggers, declared/effective: "
        + ", ".join(f"{t}={classes[t]}/{effective.get(t)}" for t in sorted(triggers))
    )
    r.note(
        f"{len(state_driven_enabled)}/{len(triggers)} enabled AND proven to require world state "
        f"to fire (predicate evaluated with all clock terms true and all state terms false)"
    )
    r.note(
        "residual: a state term's RELEVANCE is not verifiable without an evaluator. "
        "A-029 (externally injected observation, unpredictable timing) is the behavioural gate."
    )
    return r


# --------------------------------------------------------------------------
# CI-030 -- INV-SCENE-2: every element type declares a degradation ladder for
# every endpoint spatial class, and every declared action is a member of the
# scene schema's closed enum.
# --------------------------------------------------------------------------
def check_degradation_ladder() -> Result:
    r = Result("degradation-ladder-complete")
    if not LADDER.is_file():
        r.err("contracts/policy/degradation_ladder.toml is missing")
        return r
    if not SCENE.is_file():
        r.err("semantic_scene.schema.json missing")
        return r

    doc = _load(LADDER)
    scene = json.loads(SCENE.read_text(encoding="utf-8"))

    element_types = set(scene["$defs"]["sceneElement"]["properties"]["type"]["enum"])
    permitted_actions = set(
        scene["$defs"]["renderResult"]["properties"]["degradations"]["items"]["properties"]["action"]["enum"]
    )
    spatial_classes = set(doc.get("spatial_classes", []))
    if not spatial_classes:
        r.err("degradation ladder declares no spatial_classes")
        return r

    declared = {}
    for el in doc.get("element", []):
        etype = el.get("type")
        declared[etype] = el
        if etype not in element_types:
            r.err(f"ladder declares element type {etype!r}, which the scene schema does not define")
            continue
        rungs = {rung.get("spatial_class"): rung for rung in el.get("rung", [])}
        for sc in sorted(spatial_classes):
            if sc not in rungs:
                r.err(f"element {etype!r} has no rung for spatial_class {sc!r} (INV-SCENE-2)")
        for sc, rung in sorted(rungs.items()):
            if not rung.get("degraded"):
                continue
            action = rung.get("action")
            if action not in permitted_actions:
                r.err(
                    f"element {etype!r} rung {sc!r} declares action {action!r}, which is not in the "
                    f"scene schema's closed enum -- a renderer cannot emit this degradation record"
                )
            fb = rung.get("fallback_action")
            if fb is not None and fb not in permitted_actions:
                r.err(f"element {etype!r} rung {sc!r} declares fallback_action {fb!r}, not in the scene enum")
            if not rung.get("reason"):
                r.err(f"element {etype!r} rung {sc!r} is degraded with no reason (silent degradation)")

    for etype in sorted(element_types - set(declared)):
        r.err(f"scene element type {etype!r} has NO degradation ladder (INV-SCENE-2)")

    missing_voice = [
        e for e, el in declared.items()
        if "none" not in {rung.get("spatial_class") for rung in el.get("rung", [])}
    ]
    if missing_voice:
        r.err(f"element types with no voice-only rung: {sorted(missing_voice)} -- this is the rung that is always the one omitted")

    r.note(f"{len(declared)} element types x {len(spatial_classes)} spatial classes = {len(declared) * len(spatial_classes)} required rungs")
    return r


# --------------------------------------------------------------------------
# CI-046 -- INV-TUNE-1: a tunable's declared range is not itself tunable.
# --------------------------------------------------------------------------
def check_tunables() -> Result:
    r = Result("tunable-range-immutable")
    if not TUNABLES.is_file():
        r.err("contracts/policy/tunables.toml is missing -- INV-TUNE-1 has no subject")
        return r
    doc = _load(TUNABLES)
    tunables = doc.get("tunable", {})
    if not tunables:
        r.err("tunables.toml declares no tunables")

    for name, t in sorted(tunables.items()):
        for field in ("min", "max", "default", "unit", "affects", "owner_rationale"):
            if field not in t:
                r.err(f"tunable {name!r} declares no {field}")
        lo, hi, dflt = t.get("min"), t.get("max"), t.get("default")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            if lo >= hi:
                r.err(f"tunable {name!r} has min >= max ({lo} >= {hi}) -- an empty range is not a range")
            if isinstance(dflt, (int, float)) and not (lo <= dflt <= hi):
                r.err(f"tunable {name!r} default {dflt} lies outside [{lo}, {hi}]")
        if "current" in t:
            r.err(
                f"tunable {name!r} carries a `current` value. This file is GOVERNED CONFIGURATION; "
                f"runtime state belongs in state.db (SPEC-26, ADR-002 D2). No file is both."
            )

    if doc.get("governed_surface") is not True:
        r.err("tunables.toml does not declare itself a governed surface -- a range the runtime can write is not a range")

    nt = doc.get("not_tunable", {})
    if not nt.get("fields"):
        r.err("no `not_tunable` list -- the boundary between pace and authority is unstated")
    else:
        required_members = ["cost_policy", "GOVERNED_PATHS", "enable-token TTL"]
        joined = " | ".join(nt["fields"])
        for m in required_members:
            if m not in joined:
                r.err(f"`not_tunable.fields` omits {m!r} -- INV-TUNE-1 names authority, budget and cost policy explicitly")

    if doc.get("on_out_of_range", {}).get("behaviour") != "CLAMP_AND_REPORT":
        r.err("on_out_of_range.behaviour must be CLAMP_AND_REPORT -- INV-TUNE-1 forbids silent acceptance")
    if doc.get("on_out_of_range", {}).get("silent_accept") is not False:
        r.err("on_out_of_range.silent_accept must be false")

    r.note(f"{len(tunables)} tunables declared; {len(nt.get('fields', []))} fields explicitly not tunable")
    return r


# --------------------------------------------------------------------------
# CI-034 -- INV-HW-2: measured, not declared. A capability whose minimum
# profile has not been MEASURED must be treated as unavailable, and this check
# fails a file that has quietly filled the numbers in from a datasheet.
# --------------------------------------------------------------------------
def check_measured_not_declared() -> Result:
    r = Result("measured-not-declared")
    if not CAPPROFILES.is_file():
        r.err("contracts/policy/capability_profiles.toml is missing -- DF-SURVIVAL-PROFILE has no second argument")
        return r
    doc = _load(CAPPROFILES)

    measured = doc.get("measured")
    if measured is None:
        r.err("capability_profiles.toml does not declare `measured` -- absence would be read as 'yes'")
    if doc.get("unmeasured_disposition") != "UNAVAILABLE":
        r.err("unmeasured_disposition must be UNAVAILABLE -- an unmeasured capability treated as available is a hardware assumption presented as a fact")

    caps = doc.get("capability", {})
    if not caps:
        r.err("no capabilities declared")

    unknown_fields = 0
    for name, c in sorted(caps.items()):
        if "survival_core" not in c:
            r.err(f"capability {name!r} does not declare survival_core")
        if "min_trust_zone" not in c:
            r.err(f"capability {name!r} declares no min_trust_zone -- survival must never lower a trust floor")
        stps = c.get("sustained_tokens_per_sec_min")
        if stps is not None and stps != "UNKNOWN":
            if measured is not True:
                r.err(
                    f"capability {name!r} declares sustained_tokens_per_sec_min = {stps!r} while "
                    f"measured = false. INV-HW-2: this value is MEASURED at enrollment, never declared."
                )
        for k, v in c.items():
            if v == "UNKNOWN":
                unknown_fields += 1

    core = [n for n, c in caps.items() if c.get("survival_core") is True]
    if not core:
        r.err("no survival_core capabilities -- INV-PLACE-3 requires a defined core set")
    for n in core:
        c = caps[n]
        if c.get("requires_accelerator") is True:
            r.err(f"survival_core capability {n!r} requires an accelerator -- a core set that needs good hardware is not a survival core")
        if c.get("requires_always_on") is True:
            r.err(f"survival_core capability {n!r} requires an always-on node, which contradicts INV-PLACE-3")

    if doc.get("degradation_reporting", {}).get("required") is not True:
        r.err("degradation_reporting.required must be true -- INV-PLACE-3: every excluded capability is reported")

    r.note(f"{len(caps)} capabilities, {len(core)} in the survival core, {unknown_fields} fields honestly UNKNOWN pending SPIKE-001/002/007")
    return r


# --------------------------------------------------------------------------
# CI-031 -- INV-PERF-1: budgets are requirements set BEFORE measurement.
# The commit-level half (a budget changed in the same diff as the code that
# failed it) needs git history and stays PENDING; this half checks that the
# budget file is well-formed, complete, and has not quietly become a report of
# what was measured.
# --------------------------------------------------------------------------
def check_latency_budgets() -> Result:
    r = Result("latency-budgets-declared")
    if not LATENCY.is_file():
        r.err("contracts/policy/latency_budgets.toml is missing -- SPIKE-002 would have no pass/fail criterion")
        return r
    doc = _load(LATENCY)

    if doc.get("set_before_measurement") is not True:
        r.err("set_before_measurement must be true -- a target defined as whatever was measured can never fail")

    paths = doc.get("path", [])
    if not paths:
        r.err("no latency paths declared")
    required_paths = {"wake_to_first_audio", "speech_end_to_response_onset", "barge_in_honoured", "checkpoint_write"}
    declared_ids = {p.get("id") for p in paths}
    for rp in sorted(required_paths - declared_ids):
        r.err(f"required latency path {rp!r} is not declared (REM-010 §4.7)")

    for p in paths:
        pid = p.get("id")
        if not isinstance(p.get("budget_ms"), int):
            r.err(f"path {pid!r} declares no integer budget_ms")
        if "measured_ms" not in p:
            r.err(f"path {pid!r} declares no measured_ms slot -- the gap analysis has nowhere to land")

    for pid in ("wake_to_first_audio", "speech_end_to_response_onset"):
        p = next((x for x in paths if x.get("id") == pid), None)
        if p is not None and p.get("independent_of_total") is not True:
            r.err(
                f"path {pid!r} must assert independent_of_total -- REM-010 requires first-audio latency "
                f"to be asserted independently of total completion, or a system that is silent for four "
                f"seconds and then perfect passes"
            )

    chain = doc.get("chain", {}).get("voice_round_trip")
    if chain:
        stages = chain.get("stages", [])
        total = sum(s.get("budget_ms", 0) for s in stages)
        declared_sum = chain.get("sum_of_stage_budgets_ms")
        if declared_sum is not None and declared_sum != total:
            r.err(f"voice chain sum_of_stage_budgets_ms = {declared_sum} but the stages sum to {total}")
        e2e = chain.get("end_to_end_budget_ms")
        if e2e is not None and total > e2e:
            r.err(
                f"AR-024 unclosed at the specification level: stage budgets sum to {total} ms against an "
                f"end-to-end budget of {e2e} ms. The arithmetic does not close before measurement even begins."
            )
        else:
            r.note(f"voice chain: stages sum to {total} ms against {e2e} ms end-to-end (headroom {chain.get('headroom_ms')} ms)")
    else:
        r.err("no voice_round_trip chain declared -- the SR-046 x SR-047 x RB-004 x SR-045 intersection has no arithmetic")

    on_miss = doc.get("on_miss", {})
    if "relax budget_ms" not in " | ".join(on_miss.get("prohibited", [])):
        r.err("on_miss.prohibited does not forbid relaxing budget_ms -- which is the one response INV-PERF-1 exists to prevent")

    r.note(f"{len(paths)} paths declared; measured = {doc.get('measured')}")
    return r


# --------------------------------------------------------------------------
# F-stage acceptance gates -- run the real harnesses, do not re-implement them
# --------------------------------------------------------------------------
def _run_acceptance(name: str, script: str, stage: str) -> Result:
    """Run an acceptance harness as a subprocess and surface its verdict.

    Shelling out rather than importing keeps ONE definition of each gate. A
    check that re-implemented the assertions could drift from the harness and
    then disagree with it, and the disagreement would be discovered by whoever
    trusted the wrong one.
    """
    r = Result(name)
    path = REPO / script
    if not path.exists():
        r.err(f"{script} is missing -- the {stage} gate cannot be evaluated")
        return r
    proc = subprocess.run([sys.executable, str(path)], capture_output=True,
                          text=True, cwd=str(REPO), timeout=900)
    tail = [ln for ln in proc.stdout.splitlines() if ln.strip()][-6:]
    if proc.returncode != 0:
        r.err(f"{stage} acceptance gate FAILED (exit {proc.returncode})")
        for ln in tail:
            r.err(f"  {ln}")
        return r
    for ln in tail:
        if "passed" in ln or "required" in ln or "GATE" in ln or "INCREMENT" in ln:
            r.note(ln.strip())
    return r


def check_f0_acceptance() -> Result:
    return _run_acceptance("f0-acceptance", "verification/run_f0_acceptance.py", "F0")


def check_f1_acceptance() -> Result:
    return _run_acceptance("f1-acceptance", "verification/run_f1_acceptance.py",
                           "F1")


def check_f2_acceptance() -> Result:
    return _run_acceptance("f2-acceptance", "verification/run_f2_acceptance.py",
                           "F2 authorization core")


CHECK_FNS = {
    "ci-registry": check_ci_registry,
    "f0-acceptance": check_f0_acceptance,
    "f1-acceptance": check_f1_acceptance,
    "f2-acceptance": check_f2_acceptance,
    "adr-gate": check_adr_gate,
    "scene-no-escape-hatch": check_scene_schema,
    "cost-policy": check_cost_policy,
    "governed-surfaces-integrity": check_governed_surfaces,
    "no-product-names": check_product_names,
    "non-schedule-trigger-present": check_trigger_registry,
    "degradation-ladder-complete": check_degradation_ladder,
    "tunable-range-immutable": check_tunables,
    "measured-not-declared": check_measured_not_declared,
    "latency-budgets-declared": check_latency_budgets,
}


def report(results: list[Result]) -> int:
    failed = 0
    for res in results:
        status = "PASS" if res.ok else "FAIL"
        print(f"[{status}] {res.name}")
        for n in res.notes:
            print(f"         note: {n}")
        for e in res.errors:
            print(f"         ERROR: {e}")
        failed += 0 if res.ok else 1
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="VESPER CI checks")
    ap.add_argument("check", nargs="?", default="all", choices=["all", "status", *CHECK_FNS])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.check == "status":
        checks = _load(CHECKS).get("checks", {})
        impl = [c for c in checks.values() if c.get("impl") != "PENDING"]
        print(f"CI enforcement: {len(impl)}/{len(checks)} checks implemented, {len(checks) - len(impl)} specified-but-PENDING")
        for cid, c in sorted(checks.items()):
            mark = "impl" if c.get("impl") != "PENDING" else "PENDING"
            print(f"  {cid:8} {mark:8} {c['name']:34} blocks@{c.get('blocking')}")
        return 0

    names = list(CHECK_FNS) if args.check == "all" else [args.check]
    results = []
    for n in names:
        fn = CHECK_FNS[n]
        results.append(fn(self_test=args.self_test) if n == "scene-no-escape-hatch" else fn())
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
