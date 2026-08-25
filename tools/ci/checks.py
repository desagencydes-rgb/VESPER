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
import ast
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
FABRIC = REPO / "contracts" / "policy" / "network_fabric.toml"
HOST_ACTIONS = REPO / "contracts" / "policy" / "host_actions.toml"
FABRIC_IMPL = REPO / "core" / "fabric.py"
PLACEMENT = REPO / "core" / "placement.py"
MODEL_PROFILE = REPO / "contracts" / "entities" / "model_profile.schema.json"
IDEA = REPO / "contracts" / "entities" / "improvement_idea.schema.json"
TASK = REPO / "contracts" / "entities" / "task.schema.json"
VERIF_STRATEGY = (REPO / "contracts" / "entities"
                  / "verification_strategy.schema.json")
AUTONOMY = REPO / "core" / "autonomy.py"
INTERLOCK = REPO / "core" / "interlock.py"
CORE = REPO / "core"

# Directories whose code must never name a product. Scanned once they exist;
# absence is not a pass, it is reported as "not yet applicable".
PRODUCT_NAME_SCOPES = ["routing", "resources", "policy", "world", "models",
                        # core/ added 2026-08-15 when F0/F1 landed. The router,
                        # the cost choke point and the policy skeleton all live
                        # here, and INV-HW-1 is precisely about routing, resource
                        # and policy paths. Scanning only the aspirational
                        # directories would have left the real ones uncovered.
                        "core",
                        # contracts/ and spec/ added 2026-08-19, and the reason
                        # is the same defect one directory over. FIVE of the six
                        # scopes above have NEVER EXISTED -- there is no
                        # routing/, resources/, policy/, world/ or models/ in
                        # this tree and there never has been. So CI-007 was
                        # scanning core/ alone while INV-HW-1's own subject --
                        # "routing, resource or POLICY paths" -- lives at
                        # contracts/policy/, where the shipped policy contracts
                        # actually are. _vacuous_checks() did not catch this: it
                        # excludes CI-007 only when NO scope exists, and core/
                        # kept it looking healthy while 5/6 scopes were fiction.
                        # Widening it found a real violation on the first run,
                        # in contracts/entities/node_capability_profile.schema.json.
                        # This is the CI-016 prefix bug in a new place: a scope
                        # list is not coverage until something confirms the
                        # scopes resolve.
                        "contracts", "spec"]
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
def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nullable(spec: dict) -> bool:
    """Does this property schema admit null in any of its spellings?"""
    t = spec.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return True
    return any(_nullable(sub) for key in ("anyOf", "oneOf", "allOf")
               for sub in spec.get(key, []) if isinstance(sub, dict))


def _returns_dict_with_key(tree, func_name: str, key: str) -> bool:
    """Does the module-level `func_name` return a dict literal carrying `key`?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Return)
                        and isinstance(sub.value, ast.Dict)
                        and any(isinstance(k, ast.Constant) and k.value == key
                                for k in sub.value.keys)):
                    return True
    return False


def _name_dict_has_key(scope, module, name: str, key: str) -> bool | None:
    """Does `name` hold a dict carrying `key`? None when it cannot be resolved.

    ONE HOP, AND THE THIRD ANSWER MATTERS. `name = {...}` is resolved directly;
    `name = helper(...)` is resolved by reading `helper`'s returned dict
    literal. That second case is not hypothetical -- `autonomy.py` publishes
    `payload=probe` where `probe = anti_cron_probe(trigger)`, and the returned
    dict does carry `trigger_id`. A resolver that stopped at literals reported
    that line as an INV-TRIG-1 violation when the code was correct.

    Anything deeper returns None rather than True or False, and the caller
    reports it as unresolved. Guessing True would let a real omission through
    on any indirection; guessing False would cry wolf until someone disabled
    the check. "I could not tell" is the honest third answer and it is the one
    that gets acted on.

    IT RESOLVES INSIDE A SCOPE, and that is not a detail. Searching the whole
    module for an assignment to `probe` found the one inside `anti_cron_probe`
    -- a dict COMPREHENSION, not a dict literal -- and reported the caller's
    perfectly correct `probe = anti_cron_probe(trigger)` as unresolvable. Two
    functions may both use a name like `probe` or `payload`, and a resolver
    that ignores scope answers a question about the wrong variable.
    """
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name
                   for t in node.targets):
            continue
        val = node.value
        if isinstance(val, ast.Dict):
            return any(isinstance(k, ast.Constant) and k.value == key
                       for k in val.keys)
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
            return _returns_dict_with_key(module, val.func.id, key)
        return None
    return None


# --------------------------------------------------------------------------
# CI-022 -- INV-COST-4: a model profile's cost class is NON-NULLABLE.
# The failure mode is specific, and it is not "the field is missing": it is
# that a profile nobody classified gets READ as free, and a paid call is then
# made under a budget that was never asked about it. So a default is refused,
# null is refused, and dropping the field from `required` is refused -- three
# spellings of the same silence.
# --------------------------------------------------------------------------
def check_cost_class_nonnull() -> Result:
    r = Result("cost-class-nonnull")
    if not MODEL_PROFILE.is_file():
        r.err("contracts/entities/model_profile.schema.json is missing -- "
              "INV-COST-4 has no subject")
        return r
    doc = _json(MODEL_PROFILE)
    cc = doc.get("properties", {}).get("cost_class")
    if cc is None:
        r.err("model_profile declares no `cost_class` property (INV-COST-4)")
        return r
    if "cost_class" not in doc.get("required", []):
        r.err("`cost_class` is not in `required` -- an unclassified profile "
              "would validate, and INV-COST-4 exists because it would then be "
              "treated as free")
    if "default" in cc:
        r.err(f"`cost_class` declares a default ({cc['default']!r}). A default "
              "IS the silent classification this invariant forbids")
    if _nullable(cc):
        r.err("`cost_class` admits null -- 'we forgot to classify it' becomes "
              "'it was treated as free'")
    enum = cc.get("enum")
    if not enum:
        r.err("`cost_class` is not an enum, so any string would validate and "
              "the budget could not branch on it")
    else:
        missing = {"free", "paid"} - set(enum)
        if missing:
            r.err(f"`cost_class` enum omits {sorted(missing)} -- the cost "
                  "policy distinguishes them")
        r.note(f"cost_class enum: {enum}")
    if doc.get("additionalProperties") is not False:
        r.err("model_profile permits additional properties, so a misspelled "
              "`cost_clas` would validate beside a missing real one")
    return r


# --------------------------------------------------------------------------
# CI-047 -- INV-IDEA-4: nothing leaves the backlog silently.
# A RETIRED idea with no disposition_reason is indistinguishable from one the
# system quietly gave up on. The rule has to be STRUCTURAL: the property
# description already says MANDATORY, and a description does not reject a
# document.
# --------------------------------------------------------------------------
def check_idea_retirement_reason() -> Result:
    r = Result("idea-retirement-reason")
    if not IDEA.is_file():
        r.err("contracts/entities/improvement_idea.schema.json is missing")
        return r
    doc = _json(IDEA)
    status = doc.get("properties", {}).get("status", {})
    if "RETIRED" not in (status.get("enum") or []):
        r.err("`status` has no RETIRED state -- INV-IDEA-4 has no subject")
        return r

    conditional = None
    for clause in doc.get("allOf", []):
        cond = clause.get("if", {}).get("properties", {}).get("status", {})
        if cond.get("const") == "RETIRED" or "RETIRED" in (cond.get("enum") or []):
            conditional = clause
            break
    if conditional is None:
        r.err("no allOf if/then binds RETIRED to a disposition_reason. The "
              "property description says MANDATORY; a description does not "
              "reject a document (INV-IDEA-4)")
        return r

    then = conditional.get("then", {})
    if "disposition_reason" not in then.get("required", []):
        r.err("the RETIRED clause does not `require` disposition_reason")
    sub = then.get("properties", {}).get("disposition_reason", {})
    if _nullable(sub) or sub.get("minLength", 0) < 1:
        r.err("a RETIRED idea may carry an empty or null disposition_reason -- "
              "an empty reason is silence with extra steps")
    r.note("RETIRED is structurally bound to a non-empty disposition_reason")
    return r


# --------------------------------------------------------------------------
# CI-032 -- INV-VERIF-3: verification criteria are TYPED, never free text.
# RB-004 asks for a "machine-checkable acceptance condition". Free text is
# checkable only by a model, which makes the thing verified and the thing
# verifying the same kind of judgement -- and a task can then be declared done
# by writing a sentence about it.
# --------------------------------------------------------------------------
def check_verification_criteria_typed() -> Result:
    r = Result("verification-criteria-typed")
    if not TASK.is_file():
        r.err("contracts/entities/task.schema.json is missing")
        return r
    doc = _json(TASK)
    if "verification_criteria" not in doc.get("required", []):
        r.err("`verification_criteria` is not required -- a task with no "
              "acceptance condition could be created (INV-VERIF-3)")
    vc = doc.get("properties", {}).get("verification_criteria")
    if vc is None:
        r.err("task declares no `verification_criteria`")
        return r
    ref = vc.get("$ref")
    if not ref:
        r.err(f"`verification_criteria` is inline (type={vc.get('type')!r}) "
              "rather than a $ref to a typed strategy. Free text here is the "
              "failure INV-VERIF-3 names")
    elif "verification_strategy" not in ref:
        r.err(f"`verification_criteria` refs {ref!r}, not the verification "
              "strategy contract")
    elif not VERIF_STRATEGY.is_file():
        r.err("verification_strategy.schema.json is missing, so the $ref "
              "resolves to nothing and the typing is nominal")
    else:
        strat = _json(VERIF_STRATEGY)
        if strat.get("type") == "string":
            r.err("verification_strategy is itself a bare string -- a $ref "
                  "that makes free text look typed is worse than free text")
        r.note(f"typed via {ref.rsplit('/', 1)[-1]}; strategy requires "
               f"{strat.get('required')}")
    return r


# --------------------------------------------------------------------------
# CI-025 -- INV-TRIG-1: every autonomous action resolves to exactly one
# registered trigger_id, INCLUDING NO-OPS. The no-op clause is the one that
# matters: a system recording only what it did cannot be audited for what it
# decided not to do, and "nothing happened" is indistinguishable from "the loop
# was dead".
#
# WHAT COUNTS AS AN ACTION, and why the discriminator is not a hand-picked
# list. The first version of this check flagged every `autonomy.*` publication
# and immediately went red on `autonomy.model_call_in_decision_path` -- which
# is a VIOLATION DIAGNOSTIC emitted from `model_call_attempted(where)`, a
# function that has no trigger in scope and could not name one if it wanted to.
# INV-TRIG-1 is about actions, not about every event in the namespace.
#
# The rule used instead comes from the code's own structure: an event whose
# SUBJECT is a trigger is a per-trigger decision, and a per-trigger decision
# whose payload drops the trigger_id cannot be joined back to its trigger in
# the durable log. Machinery diagnostics are subject-scoped to something else
# and are listed explicitly below -- and the check FAILS if a listed exemption
# is no longer emitted, so the list cannot quietly outlive its reason.
# --------------------------------------------------------------------------

# Named exemptions: autonomy events that are NOT per-trigger actions. Each must
# still be emitted somewhere, or the entry is stale and is reported as such.
NON_ACTION_AUTONOMY_EVENTS = {
    "autonomy.model_call_in_decision_path":
        "a refused model call inside the evaluator (A-011.4). Emitted from a "
        "path that has no trigger in scope by construction",
}


def check_action_has_trigger() -> Result:
    r = Result("action-has-trigger")
    if not AUTONOMY.is_file():
        r.err("core/autonomy.py is missing -- INV-TRIG-1 has no subject")
        return r
    tree = ast.parse(AUTONOMY.read_text(encoding="utf-8"))

    # Walk per function, so a payload name resolves against the scope it was
    # written in rather than against a same-named variable in some other
    # function. The module itself is included last for any module-level call.
    scopes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    scopes.append(tree)

    published = []
    seen_calls = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call) or id(node) in seen_calls:
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "publish"):
                continue
            topic = node.args[0] if node.args else None
            if not (isinstance(topic, ast.Constant)
                    and isinstance(topic.value, str)
                    and topic.value.startswith("autonomy.")):
                continue
            seen_calls.add(id(node))

            payload = subject = None
            for kw in node.keywords:
                if kw.arg == "payload":
                    payload = kw.value
                elif kw.arg == "subject":
                    subject = kw.value
            if payload is None and len(node.args) >= 3:
                payload = node.args[2]
            if subject is None and len(node.args) >= 2:
                subject = node.args[1]

            # Subject is a trigger => this is a per-trigger decision.
            trigger_scoped = (isinstance(subject, ast.Attribute)
                              and subject.attr == "trigger_id")

            carries = False
            if isinstance(payload, ast.Dict):
                carries = any(isinstance(k, ast.Constant)
                              and k.value == "trigger_id"
                              for k in payload.keys)
            elif isinstance(payload, ast.Name):
                carries = _name_dict_has_key(scope, tree, payload.id,
                                             "trigger_id")
            published.append((topic.value, node.lineno, carries, trigger_scoped))

    if not published:
        r.err("no autonomy.* events are published from core/autonomy.py -- the "
              "check has no subject and would otherwise pass vacuously")
        return r

    actions = [(t, ln, c) for t, ln, c, scoped in published if scoped]
    if not actions:
        r.err("no autonomy event is scoped to a trigger, so INV-TRIG-1 has "
              "nothing to bind -- either the loop records no decisions or the "
              "subject convention changed and this check went blind")
    for topic, line, carries in actions:
        if carries is None:
            r.err(f"core/autonomy.py:{line} publishes {topic!r} with a payload "
                  "this check cannot resolve to a dict. Not assumed either "
                  "way: extend the resolver or pass a literal, but an "
                  "unreadable payload is not evidence of a trigger_id "
                  "(INV-TRIG-1)")
        elif not carries:
            r.err(f"core/autonomy.py:{line} publishes {topic!r} about a "
                  "trigger but drops trigger_id from the payload, so the "
                  "durable record cannot be joined back to it (INV-TRIG-1)")

    seen = {t for t, _, _, _ in published}
    for topic, why in sorted(NON_ACTION_AUTONOMY_EVENTS.items()):
        if topic not in seen:
            r.err(f"{topic!r} is listed as a non-action exemption but is no "
                  f"longer emitted. Remove the exemption rather than leaving a "
                  f"standing hole ({why})")

    noops = [t for t, _, _ in actions if "noop" in t]
    if not noops:
        r.err("no trigger-scoped no-op event is published. INV-TRIG-6 makes "
              "the recorded no-op the evidence that the loop ran at all; "
              "without one, a dead loop and an idle one look identical")

    exempt = sorted(seen & set(NON_ACTION_AUTONOMY_EVENTS))
    r.note(f"{len(actions)} trigger-scoped decisions, all carrying trigger_id; "
           f"no-op events {sorted(set(noops))}; exempt diagnostics {exempt}")
    return r


def _local_imports(path: Path) -> set[str]:
    """Sibling modules this file imports, by bare module name.

    `from .lease import X` -> {"lease"}; `from core.lease import X` -> same;
    `import core.lease` -> same. Three spellings of one dependency, and a
    boundary check that understood only one of them would be trivially evaded
    by writing another.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and not mod:
                # `from . import lease`
                found.update(a.name for a in node.names)
            elif node.level:
                found.add(mod.split(".")[0])
            elif mod.startswith("core."):
                found.add(mod.split(".")[1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("core."):
                    found.add(a.name.split(".")[1])
    return found


def _boundary(result: Result, subject: Path, forbidden: dict[str, str],
              why: str) -> None:
    """Assert `subject` imports none of `forbidden`, and that the ban is real.

    THE SECOND HALF IS THE POINT. A ban list naming modules that do not exist
    passes on every tree and enforces nothing -- the exact vacuity this repo
    keeps finding in its own checks. So every forbidden module must be present
    in core/, or the entry is reported as stale rather than quietly satisfied.
    """
    if not subject.is_file():
        result.err(f"{subject.relative_to(REPO).as_posix()} is missing -- the "
                   "boundary has no subject")
        return
    missing = [m for m in forbidden if not (CORE / f"{m}.py").is_file()]
    if missing:
        result.err(f"ban list names modules that do not exist in core/: "
                   f"{sorted(missing)}. A ban on nothing passes everywhere; "
                   "remove the entry or fix the name")
    imported = _local_imports(subject)
    for mod in sorted(forbidden):
        if mod in imported:
            result.err(f"{subject.name} imports core.{mod} -- {forbidden[mod]} "
                       f"({why})")
    result.note(f"{subject.name} imports {sorted(imported) or ['nothing local']}; "
                f"banned: {sorted(forbidden)}")


# --------------------------------------------------------------------------
# CI-019 -- INV-STOP-2: the stop path does not traverse the control plane, the
# PDP, any lease, or any model inference.
#
# The interlock is a dead-man's switch: autonomy runs only while a fresh enable
# token is present, so stopping is the ABSENCE of a renewal and every failure
# of the stop path fails toward stopped. That property is destroyed by any
# dependency that can itself fail, block or refuse -- a stop that needs a lease
# is a stop that cannot happen during the partition you most want to stop in.
# --------------------------------------------------------------------------
def check_interlock_independence() -> Result:
    r = Result("interlock-independence")
    _boundary(r, INTERLOCK, {
        "lease": "the stop path would depend on ownership it may not hold "
                 "during a partition",
        "authorize": "the PDP is the control plane's decision point; a stop "
                     "that can be refused is not a stop",
        "gateway": "model inference in the stop path makes stopping depend on "
                   "the thing being stopped",
        "router": "routing is a model-selection path and can block",
        "policy": "policy is evaluated by the control plane the stop must "
                  "outlive",
        "selfmod": "the self-modification boundary is governed by the runtime "
                   "the interlock exists to halt",
    }, "INV-STOP-2")
    return r


# --------------------------------------------------------------------------
# CI-023 -- INV-TRIG-2: the evaluator holds no model capability.
#
# "Is there anything worth doing?" asked of a model is a chatbot talking to
# itself, and it is also non-reproducible: the same world state would produce
# different actions on different days. The evaluator decides by predicate over
# world state or it does not decide. The attempt path must EMIT AND RAISE --
# emitting alone leaves a build that logs its own violation and carries on.
# --------------------------------------------------------------------------
def check_evaluator_no_model_capability() -> Result:
    r = Result("evaluator-no-model-capability")
    _boundary(r, AUTONOMY, {
        "gateway": "the model gateway is a model capability by definition",
        "router": "the router exists to choose a model",
        "context": "context assembly is a model-call preparation path",
    }, "INV-TRIG-2")
    if not AUTONOMY.is_file():
        return r

    tree = ast.parse(AUTONOMY.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "model_call_attempted"), None)
    if fn is None:
        r.err("no `model_call_attempted` path exists. INV-TRIG-2 requires an "
              "attempt to be emitted AND raised; with no such function the "
              "attempt would simply succeed")
        return r
    raises = any(isinstance(n, ast.Raise) for n in ast.walk(fn))
    emits = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "publish" for n in ast.walk(fn))
    if not emits:
        r.err("`model_call_attempted` does not publish -- the violation would "
              "be refused but invisible in the audit trail (A-011.4)")
    if not raises:
        r.err("`model_call_attempted` does not raise -- a build that logs its "
              "own violation and carries on is the failure A-011.4 names")
    r.note("model_call_attempted both emits and raises")
    return r


# --------------------------------------------------------------------------
# CI-005 -- INV-COORD-4: wall clock never participates in ordering or
# supersession. Only HLC does.
#
# The failure this refuses is SILENT. Two nodes whose clocks differ by a second
# will agree on every test in the suite and disagree only about which of two
# concurrent writes happened last -- and the loser is discarded without anyone
# being told. That is why ADR-001 puts node_id inside the HLC tuple in the
# first place: ordering must come from a clock that cannot go backwards
# relative to another node's.
#
# WHAT IT DOES NOT FLAG, deliberately. Comparing "is it 09:00 yet" against the
# wall clock is not ordering and not supersession -- the alarm does exactly
# that and is correct to. A check that fired there would need an annotation on
# every legitimate use, and a check that cries wolf gets disabled, which is the
# lesson CI-025 already paid for. So only two shapes are refused:
#
#   1. a sort/min/max/heapq keyed on a wall-clock timestamp, and
#   2. a comparison whose BOTH sides are wall-clock timestamps -- the shape of
#      "which record wins", as opposed to "has this moment arrived".
#
# ESCAPE HATCH. `WALL-CLOCK-OK` on the statement's lines allows it, and every
# use is reported as a note rather than passing silently, so an annotation is
# something a reviewer sees rather than something that hides.
# --------------------------------------------------------------------------

# Timestamp names only. `swallowed` contains "wall" and `wall_tokens_per_sec`
# is a throughput, so a substring test would flag both -- the check has to know
# the difference between a clock reading and a word that happens to contain one.
_WALL_NAME = re.compile(r"(^|_)at_wall$|^wall(_iso|_ms)?$|_wall_ms$")
_CLOCK_CALLS = {("time", "time"), ("datetime", "now"), ("datetime", "utcnow"),
                ("datetime", "today"), ("time", "time_ns")}
_ORDERING_FNS = {"sorted", "min", "max"}
_ANNOTATION = "WALL-CLOCK-OK"


def _names_in(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
    return out


def _is_wall(node: ast.AST) -> bool:
    """True when this expression reads a wall clock."""
    if any(_WALL_NAME.search(nm) for nm in _names_in(node)):
        return True
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            base = n.func.value
            if isinstance(base, ast.Name) and (base.id, n.func.attr) in _CLOCK_CALLS:
                return True
    return False


def _annotated(lines: list[str], node: ast.AST) -> bool:
    lo = getattr(node, "lineno", None)
    hi = getattr(node, "end_lineno", lo)
    if lo is None:
        return False
    # One line of slack each way: the annotation is often on the line above.
    for k in range(max(1, lo - 1), min(len(lines), (hi or lo) + 1) + 1):
        if _ANNOTATION in lines[k - 1]:
            return True
    return False


def check_no_wall_clock_ordering() -> Result:
    r = Result("no-wall-clock-ordering")
    if not CORE.is_dir():
        r.note("core/ does not exist yet -- not applicable")
        return r
    files = sorted(CORE.glob("*.py"))
    if not files:
        r.err("core/ contains no modules -- INV-COORD-4 cannot be evaluated, "
              "and a check with nothing to scan must not report PASS")
        return r

    scanned = allowed = 0
    for path in files:
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            r.err(f"{path.name}: does not parse ({e.msg}) -- cannot be scanned")
            continue
        scanned += 1
        rel = path.relative_to(REPO).as_posix()

        for n in ast.walk(tree):
            # ---- shape 1: ordering keyed on a wall clock
            key = None
            if isinstance(n, ast.Call):
                fname = None
                if isinstance(n.func, ast.Name):
                    fname = n.func.id
                elif isinstance(n.func, ast.Attribute):
                    fname = n.func.attr
                if fname in _ORDERING_FNS or fname == "sort" or (
                        isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "heapq"):
                    key = next((kw.value for kw in n.keywords
                                if kw.arg == "key"), None)
                    subject = key if key is not None else n
                    if _is_wall(subject):
                        if _annotated(lines, n):
                            allowed += 1
                            r.note(f"{rel}:{n.lineno} wall-clock ordering "
                                   f"allowed by {_ANNOTATION}")
                        else:
                            r.err(f"{rel}:{n.lineno} orders by a wall-clock "
                                  f"timestamp. INV-COORD-4: only HLC orders. "
                                  f"Two nodes a second apart silently disagree "
                                  f"about which write won")

            # ---- shape 2: supersession by comparing two wall clocks
            if isinstance(n, ast.Compare) and n.ops and isinstance(
                    n.ops[0], (ast.Lt, ast.Gt, ast.LtE, ast.GtE)):
                sides = [n.left, *n.comparators]
                if len(sides) >= 2 and all(_is_wall(s) for s in sides):
                    if _annotated(lines, n):
                        allowed += 1
                        r.note(f"{rel}:{n.lineno} wall-clock comparison "
                               f"allowed by {_ANNOTATION}")
                    else:
                        r.err(f"{rel}:{n.lineno} decides precedence by "
                              f"comparing two wall-clock timestamps. "
                              f"INV-COORD-4: supersession is HLC's, and the "
                              f"loser here is discarded without anyone being "
                              f"told")

    r.note(f"scanned {scanned} modules in core/; {allowed} annotated "
           f"exception(s)")
    return r


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
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    tail = lines[-6:]
    if proc.returncode != 0:
        r.err(f"{stage} acceptance gate FAILED (exit {proc.returncode})")

        # SURFACE THE CASE THAT FAILED, not just the closing notes.
        #
        # This used to print the last six lines only. Every acceptance runner
        # ends with the same block -- the standing "owed" notes and the gate
        # verdict -- so a CI failure showed the items that are ALWAYS owed and
        # never the assertion that actually broke. On 2026-08-18 that made a red
        # `gates` job unreadable: it listed the 24 h endurance run and the alarm
        # hardware cases, which are owed on every run including the green ones.
        #
        # The failing case is identified by the harness's own markers, so this
        # does not need to know what any particular gate asserts.
        # `expected-fail` lines are negative controls behaving CORRECTLY -- a
        # control that passes is the defect, not one that fails. Including them
        # listed eight healthy controls as failures and buried the one real
        # MISS, which is the same illegibility this block exists to remove.
        failed = [ln for ln in lines
                  if ln.startswith("[FAIL]")
                  or " MISS:" in ln
                  or " ERROR:" in ln]
        if failed:
            r.err("  the assertions that actually failed:")
            for ln in failed[:20]:
                r.err(f"    {ln.strip()}")
            if len(failed) > 20:
                r.err(f"    ... and {len(failed) - 20} more")
        else:
            r.err("  no [FAIL]/MISS/ERROR line was produced -- the runner exited "
                  "non-zero without naming a case, which is itself the defect")
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
                           "F2")


def check_f4_acceptance() -> Result:
    return _run_acceptance("f4-acceptance", "verification/run_f4_acceptance.py",
                           "F4 world/privacy/enrollment")


def check_f3_acceptance() -> Result:
    return _run_acceptance("f3-acceptance", "verification/run_f3_acceptance.py",
                           "F3 scene/presence/outbox")


def check_f5_acceptance() -> Result:
    """THE DECISIVE GATE. C1 (pure cron) is the run the corpus calls the single
    most important in the verification programme."""
    return _run_acceptance("f5-acceptance", "verification/run_f5_acceptance.py",
                           "F5 autonomy")


def check_f6_acceptance() -> Result:
    """F6 placement and survival -- A-048 in full, plus A-017.

    A-048's negative controls are BUILDS, not inputs: a node-pinned placement
    and an undamped one. A build that pins VESPER to one machine passes every
    other acceptance test in the suite and fails the owner's actual
    requirement, which is why the control has to be a whole placement policy
    rather than a bad fixture.
    """
    return _run_acceptance("f6-acceptance", "verification/run_f6_acceptance.py",
                           "F6 placement/survival/recovery")


def check_placement_stress() -> Result:
    """Properties over randomised fabrics, not outcomes over chosen ones.

    Separate from the F6 gate so a failure is attributable: the gate says a
    named case broke, this says a property broke on an input nobody chose. The
    scoring defect that made a 20x throughput gain read as 9% passed four of
    A-048's nine cases before a fifth caught it, which is the argument for
    having both.
    """
    return _run_acceptance("placement-stress",
                           "verification/stress_placement.py",
                           "placement property/stress")


def check_fabric_stress() -> Result:
    """DF-FABRIC-ADMIT over randomised fabrics, not just the shipped one.

    CI-055 reads the contract in the tree -- one input, and the one least
    likely to be wrong. This exercises the decision function over the space of
    contracts it will meet as nodes enrol, and its load-bearing property is
    non-elevation: a `max` that quietly becomes a `min` grants the strongest
    trust over the least controlled path, passes any test that only checks a
    ceiling was applied, and looks identical in a diff.
    """
    return _run_acceptance("fabric-stress",
                           "verification/stress_fabric.py",
                           "fabric property/stress")


def check_host_stress() -> Result:
    """The host action boundary over randomised vocabularies, not just the one.

    CI-056 reads the single reviewed vocabulary in the tree. This exercises the
    enforcement code over the space of vocabularies it meets as rows are added
    and enabled -- which is where a boundary erodes: not in the file that was
    reviewed, but in the tenth edit nobody read as carefully as the first.

    Its load-bearing property is the read line's DIRECTION. Inverting one
    comparison makes `changes_host` ask permission for reads and grant host
    mutations freely. Authorisation is still consulted on every call, so any
    test asserting "authorisation is checked" stays green while the owner
    policy is exactly reversed. The harness ships with that inversion as a
    negative control and fails if the control passes.
    """
    return _run_acceptance("host-stress",
                           "verification/stress_host.py",
                           "host action boundary property/stress")



# --------------------------------------------------------------------------
# CI-055 -- INV-NET-1/2/3: the network fabric contract cannot be made to lie.
#
# WHY THIS CHECK EXISTS AT ALL, given SR-016 sat at DESIGNED for a reason.
# Its depth_note said building the contract first would be "ceremony written to
# move a linter", and that was right. So the mechanism came first: three
# invariants, a decision function, and core/fabric.py. This check is what makes
# the contract load-bearing rather than decorative -- without it the file is a
# set of values nothing reads under a name nothing enforces.
#
# THE CASE WORTH NAMING is elevation. INV-NET-2 makes a segment's zone a
# CEILING. A check that merely confirmed a ceiling was PRESENT would pass a
# contract in which the least controlled path granted the strongest zone, which
# is not a weaker policy -- it is the inverse of the intended one, and it looks
# identical in a diff.
# --------------------------------------------------------------------------
def check_fabric_segments() -> Result:
    r = Result("fabric-segment-declared")
    if not FABRIC.is_file():
        r.err("contracts/policy/network_fabric.toml is missing -- DF-FABRIC-ADMIT has no segment declarations and INV-NET-1 defaults to refusing everything")
        return r
    doc = _load(FABRIC)

    # INV-NET-1. Fail-closed is the invariant, not a setting on it.
    disp = doc.get("unlisted_segment_disposition")
    if disp != "UNREACHABLE":
        r.err(f"unlisted_segment_disposition is {disp!r}, not 'UNREACHABLE' -- INV-NET-1 is fail-closed; an unknown network path is what a hostile one looks like")

    if "attested" not in doc:
        r.err("the contract does not declare `attested` -- absence would be read as 'yes', which is the INV-HW-2 failure mode on the network axis")

    ni = doc.get("non_interference", {})
    if ni.get("required") is not True:
        r.err("non_interference.required must be true -- SR-016's second clause is 'devices remain usable normally by the user'")
    if ni.get("administrative_control_scope") != "vesper_owned_only":
        r.err(f"administrative_control_scope is {ni.get('administrative_control_scope')!r}, not 'vesper_owned_only' -- INV-NET-3: being attached to VESPER's network is not consent to be managed by it")
    if ni.get("control_traffic_reserved") is not True:
        r.err("control_traffic_reserved must be true -- A-045 asserts media traffic does not starve control traffic, and without a reservation that assertion has no mechanism")
    if ni.get("user_owned_preemptible") is not False:
        r.err("user_owned_preemptible must be false -- 'usable normally' is not 'usable when VESPER is idle'")

    segs = doc.get("segment", {})
    if not segs:
        r.err("no segments declared")
    ranks = {"Z0": 0, "Z1": 1, "Z2": 2, "Z3": 3}
    controlled = 0
    for name, s in sorted(segs.items()):
        ceiling = s.get("trust_zone_ceiling")
        if ceiling not in ranks:
            r.err(f"segment {name!r}: trust_zone_ceiling {ceiling!r} is not one of {tuple(ranks)}")
            continue
        vc = bool(s.get("vesper_controlled", False))
        controlled += 1 if vc else 0
        # THE ELEVATION GUARD. A path VESPER does not control may not carry a
        # host-capable ceiling. HOST_ZONES is (Z0, Z1) in core/placement.py, so
        # a Z0/Z1 ceiling on an uncontrolled segment silently restores exactly
        # the full-host eligibility INV-NET-2 exists to remove.
        if not vc and ranks[ceiling] < ranks["Z2"]:
            r.err(f"segment {name!r} is not vesper_controlled yet declares ceiling {ceiling}, which is host-capable (HOST_ZONES = Z0, Z1). A segment may only WEAKEN trust (INV-NET-2)")
        if s.get("carries_control_plane") and not vc:
            r.err(f"segment {name!r} carries the control plane on a path VESPER does not control (INV-NET-1)")
        for own in s.get("admits_ownership", []):
            if own not in ("vesper_owned", "user_owned"):
                r.err(f"segment {name!r}: unknown ownership class {own!r}")

    if doc.get("attested") is True and controlled == 0:
        r.err("attested = true with no vesper_controlled segment -- attestation of a fabric that does not exist")

    tc = doc.get("traffic", {}).get("control", {})
    if tc.get("starvable") is not False:
        r.err("traffic.control.starvable must be false -- INV-NET-3")
    if not isinstance(tc.get("reserved_share"), (int, float)) or tc.get("reserved_share", 0) <= 0:
        r.err("traffic.control.reserved_share must be a positive share -- a reservation of zero is not a reservation")

    # The duplication guard core/fabric.py's own comment promises. It copies
    # TRUST_ZONE_RANK rather than importing it so that a placement refactor
    # cannot make admission fail open; that is only safe while something
    # confirms the two have not drifted. This is that something.
    if FABRIC_IMPL.is_file() and PLACEMENT.is_file():
        import re as _re
        def _ranks(path):
            m = _re.search(r"TRUST_ZONE_RANK\s*=\s*\{([^}]*)\}", path.read_text(encoding="utf-8"))
            return m.group(1).strip() if m else None
        a, b = _ranks(FABRIC_IMPL), _ranks(PLACEMENT)
        if a is None or b is None:
            r.err("TRUST_ZONE_RANK not found in core/fabric.py or core/placement.py -- the drift guard cannot run and an unrunnable guard is a failed assertion, not a skip")
        elif a != b:
            r.err(f"TRUST_ZONE_RANK differs between core/fabric.py and core/placement.py -- admission and placement would disagree about which zone is stronger. fabric: {a} placement: {b}")

    if not r.errors:
        r.note(f"{len(segs)} segments, {controlled} vesper_controlled, attested={doc.get('attested')}; fail-closed disposition {disp}")
        if doc.get("attested") is not True:
            r.note("fabric is NOT attested: every vesper_controlled segment refuses admission today, so no node is a full host. Fail-closed and correct -- promotion of `attested` is a separate reviewed act, as `measured` is for capability_profiles.toml")
    return r




# --------------------------------------------------------------------------
# CI-056 -- INV-HW-1 / INV-SELF-1: the host action vocabulary is closed,
# tiered, reversible where it claims to be, and cannot quietly cross the line
# between reading the machine and changing it.
#
# WHAT THIS CHECK IS ACTUALLY DEFENDING.
#
# The host exposes no negotiation interface, so VESPER's only way to influence
# its own running conditions is to act and then re-read the world. That makes
# the action set the entire safety boundary -- there is no second gate behind
# it. And because the boundary is a list, the failure mode is not a dramatic
# one: it is a row quietly flipping `enabled` from false to true, which looks
# like configuration and reads like nothing in a diff.
#
# The owner's policy (2026-08-20) is that VESPER reads freely and changes
# nothing on its own; where a change is warranted it reports it and the owner
# applies it. Everything above `read_line` therefore ships disabled. THAT is
# the property with teeth here, and it is asserted directly rather than
# inferred from the tiers being present.
#
# THREE ASSERTIONS THAT LOOK REDUNDANT AND ARE NOT.
#
# 1. `reversible = true` with an inverse that does not exist. The row claims
#    undoability, the vocabulary cannot deliver it, and nothing notices until
#    an incident is under way and the undo is missing.
# 2. An undo capped BELOW the action it undoes. Both rows have caps, both look
#    responsibly bounded, and the system can enter a state it lacks the budget
#    to leave. A bounded action whose undo is more tightly bounded is not
#    reversible in any sense that helps.
# 3. `reversible = false` outside the destructive tier. Irreversibility is the
#    definition of destructive; a row that is irreversible and filed lower has
#    been misfiled, and misfiling is how a destructive action inherits a
#    permissive consent rule.
# --------------------------------------------------------------------------
def check_host_actions() -> Result:
    r = Result("host-action-vocabulary")
    if not HOST_ACTIONS.is_file():
        r.err("contracts/policy/host_actions.toml is missing -- the action "
              "vocabulary is the whole safety boundary and its absence is not "
              "an empty vocabulary, it is an unbounded one")
        return r
    doc = _load(HOST_ACTIONS)
    pol = doc.get("policy", {})
    actions = doc.get("action", {})

    if pol.get("fail_closed") is not True:
        r.err("policy.fail_closed must be true -- permit-unless-forbidden "
              "leaves the permitted set unbounded and unauditable")
    if pol.get("action_provenance_required") != "verified_local":
        r.err("policy.action_provenance_required must be 'verified_local': an "
              "action driven by model-generated or retrieved belief is the "
              "failure that actually causes harm on a live machine")

    tiers = pol.get("tiers") or []
    read_line = pol.get("read_line")
    if not tiers:
        r.err("policy.tiers is empty -- no ordering means no read line")
        return r
    if read_line not in tiers:
        r.err(f"policy.read_line {read_line!r} is not one of the declared tiers {tiers}")
        return r
    line = tiers.index(read_line)

    if not actions:
        r.err("no actions declared. An empty vocabulary under fail_closed is "
              "vacuously safe, so this is reported rather than passed: the "
              "check would be green while enforcing nothing")
        return r

    non_mutating = set(pol.get("non_mutating_tiers") or [])
    if not non_mutating:
        r.err("policy.non_mutating_tiers is empty -- without it every row is "
              "treated as mutating and a read is asked for an undo it cannot have")
    for t in non_mutating:
        if t not in tiers:
            r.err(f"non_mutating_tiers names {t!r}, which is not a declared tier")

    CONSENT_LEVELS = ("never", "per_rule", "per_instance")
    REQUIRED = ("tier", "enabled", "description", "reversible", "inverse",
                "requires_owner_consent", "provenance_required", "source")
    above = []
    for name, a in sorted(actions.items()):
        missing = [f for f in REQUIRED if f not in a]
        if missing:
            r.err(f"action {name!r} is missing {', '.join(missing)}")
            continue
        if a["tier"] not in tiers:
            r.err(f"action {name!r} has tier {a['tier']!r}, not in {tiers}")
            continue
        if not str(a.get("source", "")).strip():
            r.err(f"action {name!r} names no source -- a row invented to keep "
                  f"this check green is visible as a row nothing asked for")
        if a["provenance_required"] != "verified_local":
            r.err(f"action {name!r} accepts provenance {a['provenance_required']!r}; "
                  f"only 'verified_local' may drive a host action")

        # CONSENT. Added after the self-test caught its absence: downgrading
        # the only irreversible row from per-instance to per-rule consent left
        # every check green. One approval would then have covered every future
        # firing of an action that destroys unsaved work, which is precisely
        # the difference the two words exist to express.
        consent = a["requires_owner_consent"]
        if consent not in CONSENT_LEVELS:
            r.err(f"action {name!r} declares consent {consent!r}, not one of "
                  f"{CONSENT_LEVELS}")
        elif a["tier"] == "destructive" and consent != "per_instance":
            r.err(f"action {name!r} is destructive but asks only for {consent!r} "
                  f"consent. A destructive action approved once is approved "
                  f"forever, which is not what the owner agreed to")
        elif not a["reversible"] and consent != "per_instance":
            r.err(f"action {name!r} is irreversible but asks only for {consent!r} "
                  f"consent -- nothing can undo it, so nothing may pre-authorise it")

        mutating = a["tier"] not in non_mutating
        if not mutating:
            for f in ("inverse", "max_targets_per_window", "window_seconds"):
                if a.get(f):
                    r.err(f"action {name!r} is in non-mutating tier {a['tier']!r} "
                          f"but declares {f} -- a row that changes nothing needs "
                          f"no undo and no blast radius, and carrying them hides "
                          f"a mutating row filed in the wrong tier")

        idx = tiers.index(a["tier"])
        # THE OWNER-POLICY ASSERTION. Everything that changes the machine ships
        # disabled until an owner authorisation is recorded against it.
        if idx > line and a["enabled"]:
            r.err(f"action {name!r} is above the read line ({a['tier']!r} > "
                  f"{read_line!r}) and enabled. Owner policy 2026-08-20: VESPER "
                  f"reports a change and the owner applies it. Enabling this is "
                  f"a governed act, not a config edit")
        if idx > line:
            above.append(name)
            if consent == "never":
                r.err(f"action {name!r} changes the machine and asks for no "
                      f"consent at all")
            for f in ("max_targets_per_window", "window_seconds"):
                if f not in a:
                    r.err(f"action {name!r} is above the read line and declares "
                          f"no {f} -- individually safe actions are collectively "
                          f"unsafe without a blast radius")

        inv = a.get("inverse", "")
        if mutating and a["reversible"]:
            if not inv:
                r.err(f"action {name!r} mutates, claims reversible = true, and names no inverse")
            elif inv not in actions:
                r.err(f"action {name!r} names inverse {inv!r}, which is not in "
                      f"the vocabulary. A claimed undo that does not exist is "
                      f"worse than an admitted one-way action")
        elif mutating:
            if inv:
                r.err(f"action {name!r} is irreversible but names inverse {inv!r}")
            if a["tier"] != "destructive":
                r.err(f"action {name!r} is irreversible but filed under "
                      f"{a['tier']!r}. Irreversibility IS the destructive tier; "
                      f"filing it lower lets it inherit a weaker consent rule")

    # An undo must never be scarcer than the thing it undoes.
    for name, a in sorted(actions.items()):
        inv = a.get("inverse", "")
        if not inv or inv == name or inv not in actions:
            continue
        if a.get("restores_baseline"):
            continue          # this row IS the undo; the rule applies to its partner
        cap, icap = a.get("max_targets_per_window"), actions[inv].get("max_targets_per_window")
        if isinstance(cap, int) and isinstance(icap, int) and icap < cap:
            r.err(f"action {name!r} allows {cap} per window but its inverse "
                  f"{inv!r} allows only {icap}. The system can enter a state it "
                  f"has no budget to leave")

    enabled = sorted(n for n, a in actions.items()
                     if a.get("enabled") and a.get("tier") in tiers)
    r.note(f"{len(actions)} actions declared, {len(enabled)} enabled, "
           f"{len(above)} above the read line ({read_line!r})")
    r.note("above-the-line rows disabled pending owner authorisation: "
           + (", ".join(above) if above else "none declared"))
    return r


# --------------------------------------------------------------------------
# CI-057 -- a surface may not render a number nobody measured
#
# CI-034 covers the POLICY half of INV-HW-2 and its note is explicit that the
# runtime half "needs source code". This is the first runtime surface to exist,
# so this is the first place that half can be enforced rather than deferred.
#
# A RUNTIME FIXTURE, not a grep. Checking that the guards are *present* in the
# text would pass on a guard that had been inverted, and inverting one
# comparison is precisely how this codebase has been bitten before. So the
# contract is exercised: the bad readings are constructed and must raise.
# --------------------------------------------------------------------------
def check_projection_unknown_absent() -> Result:
    r = Result("projection-unknown-is-absent")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.hlc import HLC
        from core.projection import (ISLAND_COLUMNS, Projection,
                                     ProjectionContractViolation, Reading)
    except Exception as exc:                       # noqa: BLE001 -- any import failure is a red
        r.err(f"core.projection did not import: {exc!r}")
        return r

    now = HLC(physical_ms=1_000_000, logical=0, node_id="ci")
    older = HLC(physical_ms=900_000, logical=0, node_id="ci")

    def refuses(desc: str, **kw) -> None:
        try:
            Reading(**kw)
        except ProjectionContractViolation:
            return
        except Exception as exc:                   # noqa: BLE001
            r.err(f"{desc}: raised {exc!r} rather than ProjectionContractViolation")
            return
        r.err(f"{desc}: was ACCEPTED. INV-HW-2 -- a value nobody measured must not "
              "be constructible.")

    refuses("a value with no observation time (the '41 degrees C' failure)",
            key="host.temp", source="host", value=41, unit="C")
    refuses("neither a value nor a reason",
            key="host.temp", source="host")
    refuses("a value AND an unavailable reason",
            key="host.temp", source="host", value=41, observed_at=now,
            unavailable_reason="not exposed")
    refuses("an unavailable reading carrying an observation time",
            key="host.temp", source="host", unavailable_reason="not exposed",
            observed_at=now)
    refuses("a TTL that expires on arrival",
            key="host.temp", source="host", value=41, observed_at=now, ttl_ms=0)

    # Zero is a value. This is the assertion that catches a truthiness test
    # replacing an `is None` test -- MEMORY.md records that zeros compress to
    # nothing on this platform, so a genuine zero and an unmeasured field must
    # stay structurally apart.
    try:
        if not Reading(key="authorize.pending", source="authorize",
                       value=0, observed_at=now).known:
            r.err("a reading of 0 reported itself UNKNOWN. Zero is a real answer; "
                  "only None is absent.")
    except Exception as exc:                       # noqa: BLE001
        r.err(f"a reading of 0 was refused: {exc!r}")

    # An expired reading goes unavailable rather than continuing to render.
    stale = Reading(key="verification.placement_stress", source="verification",
                    value=320_000, observed_at=older, ttl_ms=1_000)
    if stale.at(now).known:
        r.err("an expired reading still reported a value. A measurement without a "
              "usable age renders identically to a fresh one.")

    # The render boundary: unavailable readings are OMITTED, never placeheld.
    proj = Projection(version=now, readings={
        "authorize.pending": Reading(key="authorize.pending", source="authorize",
                                     value=0, observed_at=now),
        "host.temp": Reading.unavailable("host.temp", "host", "not exposed on this platform"),
        "verification.placement_stress": stale,
    })
    scene = proj.to_scene("ci-fixture")
    ids = {e.element_id for e in scene.elements}
    if "host.temp" in ids:
        r.err("to_scene rendered an UNAVAILABLE reading. INV-HW-2: an absent column "
              "must not be styled into looking like a present one.")
    if "verification.placement_stress" in ids:
        r.err("to_scene rendered an EXPIRED reading.")
    if "authorize.pending" not in ids:
        r.err("to_scene dropped a known reading whose value is 0.")

    # INV-COORD-4: ordering is the HLC's job.
    if Projection(version=older, readings={}).supersedes(Projection(version=now, readings={})):
        r.err("an older projection superseded a newer one. INV-COORD-4: only the "
              "HLC orders.")

    if r.ok:
        r.note(f"{len(ISLAND_COLUMNS)} island columns declared; "
               "5 refusals, expiry, omission and HLC ordering all exercised")
    return r


# --------------------------------------------------------------------------
# CI-058 -- INV-HOME-5: the glass hatch ships in one place, with its alarm.
#
# SPIKE-013 SS0 measured, on macOS 26.5, that a WKWebView cannot be made
# transparent with public API: every public configuration paints #FFFFFF over
# the ground, and `underPageBackgroundColor = .clear` is set, held, reads back
# at alpha 0.00 and changes nothing. The owner took the private selector on one
# condition.
#
# THE CONDITION IS NOT "use it carefully". ISLAND-ARCHITECTURE SS2 forbids
# private API and says why: "the failure mode is SILENT". So the exception is
# granted against the SILENCE. The hatch may exist in exactly one shipped file,
# and only while that file also contains the runtime reader that turns the
# silent failure into a loud one.
#
# Two things are therefore checked, and the second is the one that matters:
#   1. the selector appears only in files that carry the `glass-hatch-ok`
#      marker, so no second copy can drift in unreviewed;
#   2. the shipped file still contains its reader AND its negative control. A
#      hatch whose alarm has been deleted is worse than no hatch, because the
#      architecture now records a risk that is being managed and it is not.
# --------------------------------------------------------------------------
GLASS_HATCH_MARK = "glass-hatch-ok"
GLASS_HATCH_PATTERNS = ("_setDrawsBackground", 'forKey: "drawsBackground"')
GLASS_HATCH_HOME = "app/home-macos/GlassGuard.swift"


def check_glass_hatch() -> Result:
    r = Result("glass-hatch-contained")
    app_dir = REPO / "app"
    if not app_dir.is_dir():
        r.note("not yet applicable: no app/ directory on this tree")
        return r

    scanned = 0
    carriers: list[str] = []
    for f in sorted(app_dir.rglob("*.swift")):
        if not f.is_file():
            continue
        scanned += 1
        text = f.read_text(encoding="utf-8", errors="replace")
        if not any(pat in text for pat in GLASS_HATCH_PATTERNS):
            continue
        rel = f.relative_to(REPO).as_posix()
        carriers.append(rel)
        if GLASS_HATCH_MARK not in text:
            r.err(
                f"{rel} reaches for the private WKWebView background selector without the "
                f"{GLASS_HATCH_MARK!r} marker. SPIKE-013 SS0 bought this hatch on one condition: "
                f"it lives in one reviewed place, with the alarm that makes its failure loud. "
                f"A second copy is a second silent failure."
            )

    shipped = REPO / GLASS_HATCH_HOME
    if shipped.is_file():
        t = shipped.read_text(encoding="utf-8", errors="replace")
        has_hatch = any(pat in t for pat in GLASS_HATCH_PATTERNS)
        if has_hatch and "CGWindowListCreateImage" not in t:
            r.err(
                f"{GLASS_HATCH_HOME} ships the hatch but no longer contains the reader "
                f"(CGWindowListCreateImage). In-process readers cannot answer this question -- "
                f"takeSnapshot flattens onto an opaque bitmap and cacheDisplay cannot see "
                f"out-of-process WebKit content -- so removing this one leaves the hatch with "
                f"no alarm at all."
            )
        if has_hatch and "applyHatch" not in t:
            r.err(
                f"{GLASS_HATCH_HOME} ships the hatch but no longer offers the negative control "
                f"(applyHatch: false). An alarm that has only ever been green has not been shown "
                f"to key on the thing it claims to key on."
            )
    elif carriers:
        r.err(
            f"the hatch appears in {carriers} but {GLASS_HATCH_HOME} is gone -- the one place it "
            f"is allowed to live, and the only file the alarm is checked in."
        )

    if not carriers:
        r.note("no Swift file under app/ reaches for the private background selector")
    else:
        r.note(f"scanned {scanned} Swift files under app/; hatch carried by {len(carriers)}: "
               + ", ".join(carriers))
    return r


# --------------------------------------------------------------------------
# CI-059 / CI-060 -- the gateway wired to the quota ledger and the effort floor.
#
# BOTH CHECKS ARE RUNTIME-FIXTURE AND BOTH DRIVE THE REAL `ModelGateway`, for
# the reason `core/gateway.py`'s own docstring records about `profile_id`: that
# field existed on `Provider` from F1 and the gateway never read it, so the
# router produced a decision, the gateway called providers in registration
# order, and every test passed. A-022 asserted on `RouteDecision`, A-004 on
# `attempts_by_class`, and NO TEST HELD THE TWO ENDS OF THE SAME CALL. A
# structural check that `core/quota.py` and `core/effort.py` are imported would
# reproduce that defect exactly: an import is not a call site.
#
# So these construct a gateway, register providers, and read what came back.
#
# THE FIXTURES ARE THE POINT OF THE LIMIT-0 AND EMPTY-CONTENT CASES. Both are
# verbatim captures from live endpoints on 2026-08-25 (see the README beside
# them). A cloud session has no credentials by design and must not invent a
# provider shape it has not observed -- INV-HW-2 applies to a response shape
# exactly as it applies to a throughput figure. The quota limit below is PARSED
# OUT OF THE CAPTURED BYTES by the same function the live path uses, never
# typed in as a literal 0.
# --------------------------------------------------------------------------
PROVIDER_FIXTURES = REPO / "tests" / "fixtures" / "provider-responses"
LIMIT_ZERO_FIXTURE = PROVIDER_FIXTURES / "google-429-limit-zero.json"
EMPTY_CONTENT_FIXTURE = PROVIDER_FIXTURES / "groq-200-empty-content.json"


class _StubBus:
    """Enough bus for this: `CostPolicy` and `ModelGateway` only ever publish.

    A real `EventBus` needs a clock and a `StoreSet` on disk, which would make
    a fast check slow and would couple it to persistence it is not testing.
    Recording the events keeps them assertable if a later case needs them.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, type_: str, *, subject: str | None = None,
                payload: dict | None = None, component: str | None = None) -> None:
        self.events.append((type_, payload or {}))


def _gateway(quota=None, sleep_free: bool = True):
    """A gateway on a stub bus, with sleeping disabled.

    `sleep=lambda s: None` because the retry PACING is not what these check --
    A-004 already asserts the delays -- and sleeping the real backoff would put
    30 s of wall clock into a gate that is meant to fail fast.
    """
    from core.cost import CostPolicy
    from core.gateway import ModelGateway
    from core.hlc import HybridLogicalClock

    bus = _StubBus()
    cost = CostPolicy(bus, HybridLogicalClock("ci"))
    gw = ModelGateway(bus, cost, sleep=(lambda s: None) if sleep_free else None,
                      quota=quota)
    return bus, cost, gw


def _raiser(classification: str, calls: list, tag: str, **attrs):
    """A provider that always fails, recording that it was reached.

    Counting invocations rather than reading `attempts_by_class` in every case
    is deliberate: the counter is what the gateway BELIEVES it spent, and the
    list is what actually left. A-004.3's lesson is that those are different
    measurements, and a budget bug could easily move one without the other.
    """
    def call(prompt, options):
        calls.append(tag)
        e = RuntimeError(f"{tag}: {classification}")
        e.classification = classification
        for k, v in attrs.items():
            setattr(e, k, v)
        raise e
    return call


def check_narration_complete() -> Result:
    """SR-004 has a line for every way a request can fail, and no device names.

    RUNTIME FIXTURE, NOT A GREP. A structural check ("does narration.toml have
    N rows") passes for a file whose rows cannot render -- and a template that
    raises at format time is silence at the one moment the owner is waiting to
    be told something, which is the failure this whole surface exists to
    prevent. So the announcer is built and the lines are actually rendered.
    """
    r = Result("narration-complete")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.gateway import TERMINAL, TRANSIENT
        from core.narration import EXTRA, Announcer, NarrationRefused
    except Exception as exc:                       # noqa: BLE001
        r.err(f"narration did not import: {exc!r}")
        return r

    try:
        a = Announcer()
    except NarrationRefused as exc:
        r.err(f"the announcer refused to load: {exc}")
        return r

    # 1. COVERAGE. Every classification the gateway can produce.
    for cls in (*TRANSIENT, *TERMINAL, *EXTRA):
        try:
            a.render(cls, provider_class="a provider", attempt=1, max_attempts=10,
                     retry_in_seconds=5, next_rung="a local model")
        except NarrationRefused as exc:
            r.err(f"classification {cls!r} could not be rendered: {exc}")

    # 2. NO DEVICE NAMES SPOKEN. CI-007 scans the file; this scans what the
    # owner actually HEARS, which is the rendered string rather than the source.
    # A template could name a device only in a substituted field, and the file
    # scan would not see it.
    for cls in (*TRANSIENT, *TERMINAL, *EXTRA):
        said = a.render(cls, provider_class="a provider", attempt=1,
                        max_attempts=10, retry_in_seconds=5,
                        next_rung="a local model").lower()
        for name in PRODUCT_NAMES:
            if name.strip() and name.strip() in said:
                r.err(f"the line for {cls!r} says {name.strip()!r}. INV-HW-1: the "
                      "owner hears a capability, never an inventory.")

    # 3. A HALF-RENDERED SENTENCE IS REFUSED. "Retrying in  seconds" reads as a
    # bug to a listener and costs trust in every other line.
    try:
        a.render("rate_limited", attempt=1, max_attempts=10)
        r.err("a line missing a required field rendered anyway. A sentence with "
              "a hole in it is worse than silence.")
    except NarrationRefused:
        pass

    # 4. THE BUDGET GATES SPEECH. Narrating ten retries of an unattended 3 a.m.
    # run satisfies the letter of SR-004 and violates RB-006. Asserted in BOTH
    # directions, or this passes for an announcer that never speaks at all.
    spoken: list = []
    a2 = Announcer(speaker=lambda text: spoken.append(text))
    u_quiet = a2.announce("rate_limited", interruption_class="proactive",
                          attempt=1, max_attempts=10, retry_in_seconds=5)
    u_loud = a2.announce("rate_limited", interruption_class="active_user_task",
                         attempt=1, max_attempts=10, retry_in_seconds=5)
    if u_quiet.spoken:
        r.err("an unattended (proactive) failure was SPOKEN. RB-006: every "
              "retry of a background run narrated aloud is noise, not status.")
    if not u_loud.spoken:
        r.err("a failure the owner is waiting on was NOT spoken. That is the "
              "whole of SR-004 -- the difference between a system that is "
              "working and one that has hung is whether it says so.")

    if r.ok:
        r.note(f"{len(TRANSIENT) + len(TERMINAL) + len(EXTRA)} classifications "
               "rendered; speech gated in both directions; no device name in "
               "any rendered line")
    return r


def check_chain_budget() -> Result:
    r = Result("chain-budget-bounded")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.gateway import AllProvidersExhausted, ModelGateway, Provider
        from core.quota import QuotaLedger, UNAVAILABLE_ON_TIER, EXHAUSTED
        from routing.http_completion import _quota_limit_from
    except Exception as exc:                       # noqa: BLE001
        r.err(f"the gateway did not import: {exc!r}")
        return r

    # ---------------------------------------------------------------- budget
    # SIX RUNGS, TWO ATTEMPTS EACH. Without a chain-wide bound this request
    # costs TWELVE provider calls, and the real cost of a request is then a
    # property of how many providers happened to be registered rather than
    # anything anybody decided. MULTI_ROUTE.md §2: ten per REQUEST.
    bus, cost, gw = _gateway()
    calls: list[str] = []
    for i in range(6):
        cost.register_credential(f"rung{i}", "free")
        gw.register(Provider(f"rung{i}", "prof",
                             _raiser("rate_limited", calls, f"rung{i}"),
                             model=f"m{i}"))
    try:
        gw.complete("q", task_id="budget", profile_id="prof")
    except AllProvidersExhausted:
        pass
    except Exception as exc:                       # noqa: BLE001
        r.err(f"a fully-failing chain raised {exc!r} rather than AllProvidersExhausted")
    if len(calls) != ModelGateway.MAX_ATTEMPTS_PER_REQUEST:
        r.err(f"a six-rung chain at 2 attempts each made {len(calls)} provider calls; "
              f"the chain-wide budget is {ModelGateway.MAX_ATTEMPTS_PER_REQUEST}. An "
              "unbounded chain spends per-provider attempts times ladder length, which "
              "is a number nobody chose.")
    if gw.attempts_by_class.get("free") != len(calls):
        r.err(f"the boundary counter says {gw.attempts_by_class.get('free')} attempts "
              f"while {len(calls)} calls actually left. A-004.3 asserts on the counter, "
              "so the two disagreeing means the assertion measures the wrong thing.")

    # DISCRIMINATION: the budget is READ, not a constant that happens to be 10.
    # Without this the case above would also pass a build that stopped after ten
    # for some unrelated reason.
    bus, cost, gw = _gateway()
    calls3: list[str] = []
    for i in range(6):
        cost.register_credential(f"rung{i}", "free")
        gw.register(Provider(f"rung{i}", "prof",
                             _raiser("rate_limited", calls3, f"rung{i}"),
                             model=f"m{i}"))
    try:
        gw.complete("q", task_id="budget3", profile_id="prof",
                    max_attempts_per_request=3)
    except AllProvidersExhausted:
        pass
    if len(calls3) != 3:
        r.err(f"an explicit budget of 3 permitted {len(calls3)} calls. The budget is "
              "not being read.")

    # A TERMINAL COSTS ITS ONE ATTEMPT AND NOTHING MORE. Six terminal rungs then
    # a working one: at one attempt each that is 6 spent and the seventh answers.
    # At two each the budget is gone before it is reached, and the request fails
    # while a healthy provider sat untouched.
    bus, cost, gw = _gateway()
    tcalls: list[str] = []
    for i in range(6):
        cost.register_credential(f"dead{i}", "free")
        gw.register(Provider(f"dead{i}", "prof",
                             _raiser("auth_failed", tcalls, f"dead{i}"),
                             model=f"d{i}"))
    cost.register_credential("healthy", "free")
    gw.register(Provider("healthy", "prof", lambda p, o: {"text": "answered"},
                         model="h"))
    try:
        out = gw.complete("q", task_id="terminal", profile_id="prof")
        if out["provider_id"] != "healthy":
            r.err(f"after six terminal rungs the answer came from {out['provider_id']!r}")
        if out.get("attempts_remaining") != ModelGateway.MAX_ATTEMPTS_PER_REQUEST - 7:
            r.err(f"six terminal refusals plus one success left "
                  f"{out.get('attempts_remaining')} of "
                  f"{ModelGateway.MAX_ATTEMPTS_PER_REQUEST}. A TERMINAL must consume "
                  "its single attempt and none of the retries it would have bought.")
    except Exception as exc:                       # noqa: BLE001
        r.err(f"six TERMINAL rungs exhausted the chain before a healthy provider was "
              f"reached: {exc!r}")

    # ------------------------------------------------------- quota ordering
    # BOTH DIRECTIONS, and the second is what makes this evidence. A check that
    # only ever registers the rich provider second cannot tell "ordered by
    # headroom" apart from "reversed the registration list".
    for rich, poor in (("second-registered", "first-registered"),
                       ("first-registered", "second-registered")):
        ledger = QuotaLedger()
        bus, cost, gw = _gateway(ledger)
        for pid in ("first-registered", "second-registered"):
            cost.register_credential(pid, "free")
            gw.register(Provider(pid, "prof",
                                 (lambda n: lambda p, o: {"text": n})(pid),
                                 model="shared-model"))
        # MEASURED ceilings on both sides. An unmeasured entry deliberately
        # sorts in the MIDDLE (see QuotaLedger.rank), so a case built on two
        # unmeasured entries would be asserting against a tie-break.
        ledger.entry(rich, "shared-model").limit = 100
        ledger.entry(rich, "shared-model").limit_is_measured = True
        ledger.entry(rich, "shared-model").used = 5.0
        ledger.entry(poor, "shared-model").limit = 100
        ledger.entry(poor, "shared-model").limit_is_measured = True
        ledger.entry(poor, "shared-model").used = 95.0
        out = gw.complete("q", task_id="order", profile_id="prof")
        if out["provider_id"] != rich:
            r.err(f"with {rich!r} holding 95% headroom and {poor!r} holding 5%, the "
                  f"call went to {out['provider_id']!r}. Registration order is still "
                  "deciding routing.")

    # --------------------------------------------------- limit == 0 refusals
    if not LIMIT_ZERO_FIXTURE.is_file():
        r.err(f"{LIMIT_ZERO_FIXTURE.relative_to(REPO).as_posix()} is missing: the "
              "limit-0 cases have no captured bytes to run against and would be "
              "asserting against a shape nobody observed")
        return r
    body = json.loads(LIMIT_ZERO_FIXTURE.read_text(encoding="utf-8"))
    message = (body.get("error") or {}).get("message") or ""
    limit = _quota_limit_from(message)
    if limit != 0:
        r.err(f"the captured refusal parsed to limit={limit!r}, not 0. Either the "
              "fixture changed or the message parser stopped reading it -- and the "
              "parser reads PROSE, so a vendor rewording removes the only signal "
              "separating a permanent refusal from a temporary one.")
        return r

    ledger = QuotaLedger()
    bus, cost, gw = _gateway(ledger)
    zero_calls: list[str] = []
    cost.register_credential("no-allowance", "free")
    cost.register_credential("working", "free")
    gw.register(Provider("no-allowance", "prof",
                         _raiser("rate_limited", zero_calls, "no-allowance",
                                 quota_limit=limit, retry_after_ms=7_065),
                         model="excluded-model"))
    gw.register(Provider("working", "prof", lambda p, o: {"text": "answered"},
                         model="included-model"))
    out = gw.complete("q", task_id="zero1", profile_id="prof")
    if len(zero_calls) != 1:
        r.err(f"a limit-0 refusal was attempted {len(zero_calls)} times. "
              "`rate_limited` is TRANSIENT and always will be; the permanence is in "
              "the `limit` field, and retrying it spends the budget every day forever "
              "on a call that cannot succeed.")
    if out.get("attempts_remaining") != ModelGateway.MAX_ATTEMPTS_PER_REQUEST - 1:
        r.err(f"a limit-0 refusal plus one success left "
              f"{out.get('attempts_remaining')} of "
              f"{ModelGateway.MAX_ATTEMPTS_PER_REQUEST}. Discovering that a rung is "
              "permanently outside the tier is ledger maintenance that happens once "
              "ever and benefits every later request; it must not be billed to the "
              "one request that found out.")
    state = ledger.entry("no-allowance", "excluded-model").state
    if state != UNAVAILABLE_ON_TIER:
        r.err(f"the ledger recorded the limit-0 refusal as {state!r}, not "
              f"{UNAVAILABLE_ON_TIER!r}. An exhausted window returns tomorrow; a zero "
              "limit never returns.")
    gw.complete("q", task_id="zero2", profile_id="prof")
    gw.complete("q", task_id="zero3", profile_id="prof")
    if len(zero_calls) != 1:
        r.err(f"the excluded rung was called {len(zero_calls)} times across three "
              "requests. UNAVAILABLE_ON_TIER is permanent and must never be offered "
              "again -- `_roll_if_window_elapsed` refuses to roll it for the same "
              "reason.")

    # DISCRIMINATION, and the case that makes the three above evidence. The SAME
    # classification, the SAME status, a NON-ZERO limit: this one is temporary,
    # and a build that keyed on `rate_limited` instead of on `limit` would
    # retire a working model on its first ordinary rate limit.
    ledger2 = QuotaLedger()
    bus, cost, gw = _gateway(ledger2)
    cost.register_credential("busy", "free")
    cost.register_credential("working", "free")
    gw.register(Provider("busy", "prof",
                         _raiser("rate_limited", [], "busy", quota_limit=20,
                                 retry_after_ms=33_000),
                         model="metered-model"))
    gw.register(Provider("working", "prof", lambda p, o: {"text": "answered"},
                         model="included-model"))
    gw.complete("q", task_id="nonzero", profile_id="prof")
    busy_state = ledger2.entry("busy", "metered-model").state
    if busy_state != EXHAUSTED:
        r.err(f"a refusal carrying limit=20 was recorded as {busy_state!r}, not "
              f"{EXHAUSTED!r}. Permanence must key on the limit being ZERO, not on "
              "the status being 429 -- a spent window refills.")

    # ------------------------------------ spend is read from the provider
    # WHY THIS IS ASSERTED AND NOT ASSUMED. `_book_spend` read one field name,
    # `tokens_predicted`, which is the LOCAL runner's spelling. Every remote
    # provider reports under `usage` and the three wire shapes spell it three
    # ways, so the ledger booked 1.0 UNMEASURED for providers that had just
    # handed it an exact count. Nothing failed and no gate went red -- the
    # numbers were simply worthless, which is the failure mode a quota ledger
    # can least afford. Found by the live acceptance run, not by a check.
    #
    # Asserted across all three remote spellings AND the local one, because a
    # fix that reads only the shape that happened to be debugged reintroduces
    # the same defect for the other two.
    from core.gateway import _completion_tokens
    for shape, payload, want in [
        ("openai", {"usage": {"completion_tokens": 24}}, 24),
        ("cf", {"usage": {"output_tokens": 31}}, 31),
        ("google", {"usage": {"candidatesTokenCount": 17}}, 17),
        ("local", {"tokens_predicted": 12}, 12),
    ]:
        got = _completion_tokens(payload)
        if got != want:
            r.err(f"a {shape}-shaped response reporting {want} completion tokens "
                  f"booked {got!r}. An adapter's vocabulary is not the system's: "
                  "reading one spelling books every other provider as an "
                  "unmeasured guess while it reports exact numbers.")
    # A REPORTED ZERO MUST NOT BOOK AS ZERO. One provider returns zeros on calls
    # that worked; booking that as spend concludes the free tier is infinite.
    if _completion_tokens({"usage": {"completion_tokens": 0, "output_tokens": 0}}) is not None:
        r.err("a response reporting zero completion tokens booked a measured "
              "zero. Zero here is a missing field wearing a number -- it must "
              "fall through to None so the ledger books it UNMEASURED.")

    # ------------------------------------------- the parser's own drift alarm
    # WHY THIS BELONGS IN A CHECK AND NOT A COMMENT. The limit that separates
    # "permanently outside the tier" from "back tomorrow" is carried ONLY in
    # the vendor's prose -- verified against the captured bytes: the structured
    # QuotaFailure block holds metrics, quota ids and a retry delay, and no
    # limit. So one regex over one sentence stands between a dead rung being
    # retired and being retried every day forever.
    #
    # A frozen fixture cannot notice a rewording. The fixture still parses, the
    # check above still passes, and the ladder quietly starts paying for a rung
    # that can never answer. So the DETECTOR is asserted here, in both
    # directions -- it must fire on a limit named in a shape the parser missed,
    # and must stay silent on an ordinary refusal that publishes no limit at
    # all. Without the second half this passes for a detector that simply
    # always fires, which would be an alarm nobody could act on.
    try:
        from routing.http_completion import quota_limit_parse_suspect
    except Exception as exc:                       # noqa: BLE001
        r.err(f"the drift detector did not import: {exc!r}")
        return r

    reworded = ("You exceeded your current quota. Quota exceeded for metric: "
                "generate_content_free_tier_requests, the limit is 0 for this model.")
    if _quota_limit_from(reworded) is not None:
        r.err("a reworded refusal parsed after all -- this case no longer "
              "exercises the drift path and must be replaced with one the "
              "parser genuinely misses, or the alarm below is untested")
    elif not quota_limit_parse_suspect(reworded):
        r.err("a refusal naming `the limit is 0` in prose the parser could not "
              "read raised NO suspicion. That is the silent degradation: it "
              "books as EXHAUSTED, looks temporary, and the ladder retries a "
              "permanently dead rung every day while every check stays green.")

    ordinary = "Rate limit exceeded. Please try again later."
    if quota_limit_parse_suspect(ordinary):
        r.err("an ordinary refusal that publishes no limit raised suspicion. "
              "Most providers never publish one, so this would fire constantly "
              "and an alarm that always fires is one nobody reads.")

    if r.ok:
        r.note(f"chain budget {ModelGateway.MAX_ATTEMPTS_PER_REQUEST}/request; "
               "ordering exercised in both directions; limit-0 parsed from "
               f"{LIMIT_ZERO_FIXTURE.relative_to(REPO).as_posix()} and discriminated "
               "against a non-zero limit; parser-drift alarm asserted in both "
               "directions")
    return r


def check_effort_floor() -> Result:
    r = Result("effort-floor-and-null-answer")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.effort import (EFFORT_RANK, EffortFloorViolation, FLOOR,
                                 REASONING_HEADROOM)
        from core.gateway import Provider
    except Exception as exc:                       # noqa: BLE001
        r.err(f"the effort policy did not import: {exc!r}")
        return r

    # ------------------------------------------------- the null answer (§13.3)
    if not EMPTY_CONTENT_FIXTURE.is_file():
        r.err(f"{EMPTY_CONTENT_FIXTURE.relative_to(REPO).as_posix()} is missing: the "
              "empty-content case would be asserting against a hand-written double "
              "of a shape that was measured")
        return r
    captured = json.loads(EMPTY_CONTENT_FIXTURE.read_text(encoding="utf-8"))
    choice = (captured.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    finish = choice.get("finish_reason")
    if content != "" or finish != "length":
        r.err(f"the captured 200 no longer reads content={content!r} "
              f"finish_reason={finish!r}. The fixture is evidence, not a double: if it "
              "changed, that is a finding to record rather than a test to adjust.")
        return r

    bus, cost, gw = _gateway()
    offered_budgets: list[int | None] = []
    cost.register_credential("null-answer", "free")
    cost.register_credential("real-answer", "free")

    def null_answer(prompt, options):
        offered_budgets.append(options.get("max_tokens"))
        return {"text": content, "stop_reason": finish}

    gw.register(Provider("null-answer", "prof", null_answer, model="reasoning"))
    gw.register(Provider("real-answer", "prof",
                         lambda p, o: {"text": "a real answer"}, model="plain"))
    out = gw.complete("q", task_id="null", profile_id="prof", difficulty="moderate")
    if out["provider_id"] != "real-answer":
        r.err(f"a 200 carrying empty content was returned as an answer (from "
              f"{out['provider_id']!r}). Nothing in the transport failed and nothing "
              "in the response says anything went wrong, which is exactly why it "
              "needs a guard at the one boundary every call crosses.")
    if len(offered_budgets) < 2:
        r.err(f"the empty answer was attempted {len(offered_budgets)} time(s). It is a "
              "failed attempt and must be RETRIED, not merely rejected.")
    elif not (offered_budgets[1] and offered_budgets[0]
              and offered_budgets[1] > offered_budgets[0]):
        r.err(f"the retry offered budgets {offered_budgets[:2]}. The failure is "
              "deterministic in the budget -- reasoning consumed the whole allowance "
              "before a content token was emitted -- so an identical retry is the same "
              "call made twice.")

    # DISCRIMINATION: the guard keys on EMPTINESS, not on `finish_reason`. A
    # truncated answer that still said something is an answer, and refusing it
    # would throw away work that was paid for.
    bus, cost, gw = _gateway()
    cost.register_credential("truncated", "free")
    gw.register(Provider("truncated", "prof",
                         lambda p, o: {"text": "a partial but real ans",
                                       "stop_reason": finish},
                         model="reasoning"))
    out = gw.complete("q", task_id="trunc", profile_id="prof", difficulty="moderate")
    if out["result"]["text"] != "a partial but real ans":
        r.err("a TRUNCATED but non-empty answer was refused. The guard must key on "
              "empty content, not on finish_reason=length.")

    # ----------------------------------------------------- the floor (§14)
    bus, cost, gw = _gateway()
    seen: list[dict] = []
    cost.register_credential("wire", "free")
    gw.register(Provider("wire", "prof",
                         lambda p, o: (seen.append(dict(o)), {"text": "ok"})[1],
                         model="m"))
    out = gw.complete("q", task_id="hard", profile_id="prof", difficulty="hard",
                      expected_output_tokens=1_024)
    want_effort = FLOOR["hard"]
    want_budget = REASONING_HEADROOM[want_effort] + 1_024
    if out["effort"]["reasoning_effort"] != want_effort:
        r.err(f"difficulty=hard derived reasoning_effort="
              f"{out['effort']['reasoning_effort']!r}, not the floor {want_effort!r}")
    if out["effort"]["max_tokens"] != want_budget:
        r.err(f"difficulty=hard derived max_tokens={out['effort']['max_tokens']}, not "
              f"{want_budget} (reasoning headroom PLUS output, never output alone)")
    # THE DECISION MUST REACH THE CALL. `profile_id` was carried on `Provider`
    # for months without the gateway reading it, and everything looked correct.
    # An effort derived and not sent is that defect again.
    if not seen or seen[0].get("reasoning_effort") != want_effort:
        r.err(f"the derived effort did not reach the provider: options carried "
              f"{seen[0].get('reasoning_effort') if seen else None!r}")
    if not seen or seen[0].get("max_tokens") != want_budget \
            or seen[0].get("n_predict") != want_budget:
        r.err(f"the derived budget did not reach the provider under both spellings: "
              f"max_tokens={seen[0].get('max_tokens') if seen else None}, "
              f"n_predict={seen[0].get('n_predict') if seen else None}. An adapter "
              "reads one of the two, and a budget written only to the other is a "
              "decision that never reaches the call.")

    # LOWERING IS REFUSED, LOUDLY. A silent clamp is how a cost optimisation
    # becomes a capability regression that no test sees -- and this gateway is
    # the one component that feels budget pressure, which is precisely why it
    # must not be the one that gets to relax the standard.
    lowered = None
    try:
        gw.complete("q", task_id="lower", profile_id="prof", difficulty="hard",
                    options={"reasoning_effort": "low"})
        lowered = "accepted"
    except EffortFloorViolation:
        lowered = "refused"
    except Exception as exc:                       # noqa: BLE001
        lowered = f"raised {exc!r}"
    if lowered != "refused":
        r.err(f"a caller lowering effort below the difficulty's floor was {lowered}. "
              "Effort may be raised and never lowered, and a caller-supplied effort "
              "must be read as a request to RAISE rather than merged over the derived "
              "value -- a merge is a bypass wearing the shape of an override.")

    # RAISING IS HONOURED, which is the half that keeps the floor a floor rather
    # than a fixed setting.
    out = gw.complete("q", task_id="raise", profile_id="prof", difficulty="trivial",
                      options={"reasoning_effort": "high"})
    if out["effort"]["reasoning_effort"] != "high":
        r.err(f"a caller raising effort above the floor got "
              f"{out['effort']['reasoning_effort']!r}. A floor that cannot be exceeded "
              "is a ceiling.")

    if r.ok:
        r.note(f"null answer from "
               f"{EMPTY_CONTENT_FIXTURE.relative_to(REPO).as_posix()} retried with a "
               f"grown budget and discriminated against a truncated real answer; "
               f"floor table {dict(FLOOR)} over efforts {sorted(EFFORT_RANK, key=EFFORT_RANK.get)}")
    return r


CHECK_FNS = {
    "ci-registry": check_ci_registry,
    "f0-acceptance": check_f0_acceptance,
    "f1-acceptance": check_f1_acceptance,
    "f2-acceptance": check_f2_acceptance,
    "f4-acceptance": check_f4_acceptance,
    "f3-acceptance": check_f3_acceptance,
    "f5-acceptance": check_f5_acceptance,
    "f6-acceptance": check_f6_acceptance,
    "placement-stress": check_placement_stress,
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
    "cost-class-nonnull": check_cost_class_nonnull,
    "idea-retirement-reason": check_idea_retirement_reason,
    "verification-criteria-typed": check_verification_criteria_typed,
    "action-has-trigger": check_action_has_trigger,
    "interlock-independence": check_interlock_independence,
    "evaluator-no-model-capability": check_evaluator_no_model_capability,
    "no-wall-clock-ordering": check_no_wall_clock_ordering,
    "fabric-segment-declared": check_fabric_segments,
    "host-action-vocabulary": check_host_actions,
    "fabric-stress": check_fabric_stress,
    "host-stress": check_host_stress,
    "projection-unknown-absent": check_projection_unknown_absent,
    "glass-hatch-contained": check_glass_hatch,
    "chain-budget-bounded": check_chain_budget,
    "narration-complete": check_narration_complete,
    "effort-floor-and-null-answer": check_effort_floor,
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
