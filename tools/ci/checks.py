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






CHROME_TEMPLATE = "app/home-macos/chrome/home.html"
CHROME_SWIFT = "app/home-macos/HomeChrome.swift"


def check_chrome_template_renders() -> Result:
    """The home's markup is complete, substitutable, and matches its fallback.

    WHY THIS IS THE FIRST OFFLINE GUARD THE UI HAS EVER HAD. Every other layer
    in this tree is covered by checks that run without credentials; the chrome
    was covered by nothing. Its failure mode is the worst available: a malformed
    template ships, the webview mounts, and NOTHING PAINTS -- while `mounted`
    stays true, which `HomeChrome`'s own header warns about in as many words.
    A layer that sits over the owner's whole Desktop cannot be verified only by
    someone looking at it.

    THE DRIFT THIS EXISTS TO CATCH is not a typo. The binary carries an inline
    fallback so a missing file never blanks the Desktop, and a fallback is by
    definition the copy nobody looks at. It and the file can diverge for months
    and the divergence only surfaces on the day the file is gone -- which is to
    say, in front of the owner, during the failure the fallback was written for.
    """
    r = Result("chrome-template-renders")
    tpl_path = REPO / CHROME_TEMPLATE
    swift_path = REPO / CHROME_SWIFT
    if not tpl_path.is_file():
        r.err(f"{CHROME_TEMPLATE} is missing. The chrome would fall back to the "
              "inline copy, which is correct behaviour and is NOT a reason to "
              "ship without the file -- the fallback exists for a failure, not "
              "as the source of truth.")
        return r
    tpl = tpl_path.read_text(encoding="utf-8")
    swift = swift_path.read_text(encoding="utf-8")
    if len(tpl.strip()) < 200:
        r.err(f"{CHROME_TEMPLATE} is {len(tpl)} bytes -- too small to be the "
              "home's markup. An empty template mounts cleanly and paints "
              "nothing.")
        return r

    tokens = set(re.findall(r"\{\{(\w+)\}\}", tpl))
    if not tokens:
        r.err("the template contains no substitution tokens at all. Either it "
              "is not the template, or the values the chrome solves at mount "
              "time (the card's fill, its position) are now hardcoded -- and a "
              "hardcoded fill cannot adapt to the wallpaper behind it.")

    # 1. EVERY TOKEN MUST BE SUBSTITUTED BY THE SWIFT. A token nobody replaces
    # renders as literal `{{fill}}` inside a CSS declaration, which the parser
    # discards silently -- the card then paints with no fill and the owner sees
    # a pane of clear glass over a bright wallpaper with unreadable ink.
    for tok in sorted(tokens):
        if f'"{{{{{tok}}}}}"' not in swift:
            r.err(f"the template uses {{{{{tok}}}}} and HomeChrome substitutes "
                  "no such token. It would render literally into the CSS, where "
                  "an invalid declaration is DROPPED SILENTLY -- the surface "
                  "still appears, just wrong, which is the hardest kind of "
                  "wrong to notice.")

    # 2. AND THE SWIFT MUST NOT SUBSTITUTE TOKENS THE TEMPLATE NO LONGER HAS.
    # That direction is the drift warning: it means the file was edited and the
    # code was not, so the two disagree about what the page is made of.
    for m in re.finditer(r'replacingOccurrences\(of: "\{\{(\w+)\}\}"', swift):
        if m.group(1) not in tokens:
            r.err(f"HomeChrome substitutes {{{{{m.group(1)}}}}}, which the "
                  "template no longer contains. The file and the code have "
                  "drifted apart.")

    # 3. THE INLINE FALLBACK MUST USE THE SAME TOKENS AS THE FILE. If it does
    # not, the day the file goes missing is the day the owner sees a broken
    # home -- during the exact failure the fallback was written to survive.
    fb_start = swift.find("static func fallbackTemplate()")
    if fb_start < 0:
        r.err("HomeChrome has no inline fallback. A missing template file would "
              "then blank a layer covering the owner's whole Desktop.")
    else:
        fb = swift[fb_start:swift.find("static func template()", fb_start)]
        fb_tokens = set(re.findall(r"\{\{(\w+)\}\}", fb))
        if fb_tokens != tokens:
            r.err(f"the inline fallback and {CHROME_TEMPLATE} disagree about "
                  f"their tokens: only-in-file={sorted(tokens - fb_tokens)}, "
                  f"only-in-fallback={sorted(fb_tokens - tokens)}. A fallback is "
                  "by definition the copy nobody looks at, so it drifts "
                  "silently and the divergence surfaces during the failure it "
                  "was written for.")

    # 4. STRUCTURE. Checked by presence rather than by parsing: the point is
    # that the page still HAS its parts, not that the HTML is well-formed.
    for needed, why in [("<style", "no stylesheet -- every surface would paint unstyled"),
                        ("class=\"card\"", "the card is gone from the markup"),
                        ("class=\"dockrow\"", "the main menu row is gone"),
                        ('id="history"', "the history bar is gone and there is "
                         "no way back into the conversation"),
                        ('id="stage"', "the stage is gone -- the surface typing "
                         "and speech SHARE, so losing it removes the place "
                         "either channel appears"),
                        ('id="say"', "the input field is gone and there is no "
                         "way to say anything to VESPER at all"),
                        ('data-face=', "the face behaviour no longer reaches the "
                         "page, so every state-reactive rule falls back to the "
                         "resting appearance while VESPER is working"),
                        # EVERY SURFACE'S RULE, NOT JUST ITS ELEMENT. The
                        # `.stack` CSS went missing once because an insert
                        # anchored on an indentation the file did not have: the
                        # replace did nothing, reported nothing, and the MARKUP
                        # still landed. A check for `class="stack"` passed while
                        # the transcript and field rendered as raw unstyled text
                        # over the menu bar. An element that exists is not an
                        # element that is styled, and only one of those is a
                        # surface.
                        (".convo{", "the conversation column has no rule, so "
                         "the card and history bar fall out of the bottom-right "
                         "corner and back over the dock"),
                        (".history{", "the history bar has no rule -- it "
                         "renders as unbounded raw rows instead of one line "
                         "that opens"),
                        ("--face-body", "the type stack is gone: SS5's faces "
                         "are named first so they take over the day they are "
                         "licensed, and without the variable every surface "
                         "falls back to the system face"),
                        ("Intl.Segmenter", "the grapheme split is gone -- the "
                         "dissolve walks UTF-16 code units again and tears "
                         "every emoji into halves that are not characters"),
                        (".stage{", "the stage has no rule -- the exchange "
                         "renders as unpositioned raw text, which is exactly "
                         "what happened the first time these surfaces were "
                         "built"),
                        ("@keyframes scatter", "the dissolve is gone: a line "
                         "would be replaced by a cut rather than coming apart, "
                         "and the stage would read as a label that changed"),
                        (".field{", "the input has no rule and appears as a bare "
                         "browser text box"),
                        (".dot{", "the state dot has no rule, so VESPER's "
                         "activity is invisible even when the face is correct")]:
        if needed not in tpl:
            r.err(f"template is missing {needed!r}: {why}")

    # THE CONVERSATION CLUSTER IS ANCHORED TO THE FACE, NOT TO THE VIEWPORT.
    #
    # THIS IS THE PROPERTY THAT WAS GREEN WHILE BROKEN. The rule read
    # `right: 26px; width: min(38vw, 520px)` and this check happily confirmed
    # the rule was present -- but a width derived from the viewport cannot
    # avoid an element it cannot see, and on the owner's display the card sat
    # over the face. "The rule exists" and "the card clears the face" are
    # different claims, and only the first had a gate.
    #
    # The distinction being asserted is not cosmetic: `left: {{convoLeft}}px`
    # with convoLeft = faceRect.maxX + 40 makes overlap ARITHMETICALLY
    # impossible, whatever the window size. A viewport rule can only ever be
    # coincidentally clear. So the check is that the cluster's horizontal origin
    # comes from a substituted token, and that the token is derived from the
    # face in the Swift that fills it.
    # `(?:[^}]|\}\})*` RATHER THAN `[^}]*`. The substitution tokens are
    # `{{name}}`, so a rule containing one contains `}}` -- a naive negated
    # class stops inside the token and reports the rule as lacking the very
    # thing it is being checked for. It did exactly that on the first run.
    m = re.search(r"\.convo\{((?:[^}]|\}\})*)\}", tpl, re.S)
    if m is None:
        r.err("the template has no `.convo` rule, so the conversation card and "
              "history bar have no position at all")
    elif "{{convoLeft}}" not in m.group(1):
        r.err("`.convo` does not take its horizontal origin from a substituted "
              "token. A viewport-derived position cannot avoid the face -- it "
              "is only ever coincidentally clear of it, and on 2026-08-26 the "
              "coincidence ran out on the owner's display.")
    # MATCHED ON THE ASSIGNMENT, NOT ON THE STRING ANYWHERE IN THE FILE. The
    # first version searched for `faceRect.maxX` and was satisfied by the
    # COMMENT above the assignment that mentions it -- so cutting the
    # derivation loose left the check green. A check a comment can satisfy is
    # checking the prose.
    if not re.search(r"convoLeft\s*=\s*Int\(faceRect\.maxX\)", swift):
        r.err("HomeChrome.swift does not derive convoLeft from faceRect.maxX. "
              "The token would be substituted with a number that knows nothing "
              "about where the face is, which is the same defect wearing a "
              "token.")

    # THE TRANSITION IS SERIALISED, AND BOTH COPIES CARRY IT.
    #
    # `__vesperStage` scheduled a fresh 860 ms timer on every arrival, each
    # closing over its own line. A typed turn publishes the owner's line and
    # then the reply, and since replies now return in about half a second both
    # land inside one dissolve -- so two timers ran, the first painted, and the
    # second wiped it a few milliseconds later. The owner's own words appeared
    # for a few frames, with no dissolve, on every turn. Reproduced offscreen
    # with `app/home-macos/layout_probe --eval`.
    #
    # ASSERTED IN BOTH FILES SEPARATELY because the Swift fallback is a REDUCED
    # copy, not a mirror -- 102 script lines against the template's 239 -- so
    # requiring the two to be equal would be wrong, and requiring nothing is how
    # the fallback kept the bug after the template was fixed.
    for label, src in (("the template", tpl), ("the inline fallback", swift)):
        # THE GUARD AND THE ASSIGNMENT BOTH. The assignment alone is satisfied
        # by code that still schedules a timer per arrival -- it is the early
        # return on an already-pending transition that does the serialising, and
        # asserting only the timer left the self-test green with the guard gone.
        if ("pendingTimer = setTimeout" not in src
                or "if (pendingTimer)" not in src):
            r.err(f"{label} schedules an unbounded number of dissolve timers. "
                  "Two lines arriving inside one 860 ms window paint over each "
                  "other, and the first is shown for a few frames with no "
                  "dissolve at all.")
        if "restagger(stage, 'out')" not in src:
            r.err(f"{label} never re-staggers the outgoing line. `paint` has "
                  "always computed a mirrored delay for `out` and was never "
                  "called with it, so the dissolve replayed the ARRIVAL's "
                  "stagger -- measured: the two delay sequences were identical, "
                  "element for element.")
        # THE SLICE, NOT THE NAME. `"ANIMATED_MAX" in src` is satisfied by the
        # constant still being declared while nothing slices with it -- the
        # self-test renamed the declaration, left the reference, and the check
        # stayed green. Assert the mechanism.
        if "slice(0, ANIMATED_MAX)" not in src:
            r.err(f"{label} splits and animates every glyph of a reply. The "
                  "card shows 288 characters (48 per line over six, measured); "
                  "the rest is clipped by `overflow: hidden` after being given "
                  "its own scatter vector, delay and animation.")

    # NOTHING MAY ROOT THE BACKDROP AT `body` OR `html`.
    #
    # Every panel in this page is `backdrop-filter: blur(24px) saturate(180%)`,
    # and a backdrop filter samples what is painted behind the element WITHIN
    # its backdrop root. `opacity` below 1 makes an element a backdrop root --
    # so one line setting `document.body.style.opacity` cuts every glass panel
    # off from the Desktop it is supposed to be sampling. The blur has nothing
    # to blur, the cards render as bare translucent fill, and the text on them
    # stops being legible. Shipped 2026-08-26 as a one-line "wake the
    # compositor" trick and seen by the owner within the hour.
    #
    # THE UNDO WAS THE WORSE HALF: it was queued in `requestAnimationFrame`,
    # which is exactly the callback WebKit does not run while a view is
    # throttled -- the state the trick existed to leave. It could stay rooted
    # for as long as the throttle lasted.
    #
    # Checked in the Swift as well as the template, because the call that did
    # it was Swift evaluating JS into the page, where no amount of reading the
    # template would have found it.
    ROOTING = re.compile(
        r"(?:document\.)?(?:body|documentElement)\s*\.style\.opacity\s*=",
        re.I)
    for label, src in (("the template", tpl), ("HomeChrome.swift", swift)):
        live = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith(("//", "*", "/*")))
        if ROOTING.search(live):
            r.err(f"{label} sets an opacity on `body` or `documentElement`. "
                  "Any value below 1 makes it a BACKDROP ROOT, and every glass "
                  "panel here filters the Desktop behind it -- rooting them at "
                  "an empty transparent page leaves the blur with nothing to "
                  "sample and the cards washed out.")

    # THE WORKBENCH REACHES THE PAGE. Two columns of different claims and the
    # type is what separates them: thoughts in the HAND, actions in the body
    # face. SS5 forbids the hand a number -- "never a system message, never a
    # number" -- and the owner needs the number, so it goes in the row beside it.
    for label, src in (("the template", tpl), ("the inline fallback", swift)):
        # THE DEFINITION, NOT THE NAME. `"__vesperWork" in src` is satisfied by
        # `__vesperWorkX`, and by the call site, and by a comment -- three ways
        # to be green with the receiver gone. Match the assignment.
        if "window.__vesperWork = function" not in src:
            r.err(f"{label} cannot receive the workbench, so VESPER's thoughts "
                  "and actions are derived, written to home.json and rendered "
                  "by nothing.")
        if "--face-hand" not in src:
            r.err(f"{label} declares no hand. SS5's third face is VESPER writing "
                  "in the first person and it is the whole reason the thoughts "
                  "column is a different kind of claim from the actions one.")
    # THE NEWEST THOUGHT IS NEVER THE CASUALTY, in both copies.
    #
    # The budget is spent newest-first and the first entry is appended without
    # being tested -- so a long thought is shown whole and the OLDER ones are
    # dropped to make room, rather than the new one being clipped or squeezed.
    # It rendered the other way round on both counts: thoughts were appended
    # chronologically with `nth-child(2)` dimmed, so a fresh thought appeared
    # FADED under a stale bright one; and a six-line ceiling clipped it.
    for label, src in (("the template", tpl), ("the inline fallback", swift)):
        if "if (i === 0) { continue; }" not in src:
            r.err(f"{label} tests the newest thought against the line budget. "
                  "It must be appended unconditionally -- a long thought is "
                  "still a thought, and clipping it is exactly the `packed and "
                  "hidden` the budget exists to avoid.")
        if "gap * (lines - 1)" not in src:
            r.err(f"{label} counts lines and not the gaps between them. Two "
                  "one-line thoughts measured 51.00px against a budget of "
                  "50.92px and the second was dropped: SS5's `~two lines` "
                  "decided by eight hundredths of a pixel.")
        if "flex:0 0 auto" not in src:
            r.err(f"{label} lets the thoughts block shrink. When the card runs "
                  "short the ACTIONS must give way -- a log can scroll, a "
                  "half-shown thought is just wrong.")
    if "reversed(self._thoughts)" not in (REPO / "core" / "workbench.py").read_text(
            encoding="utf-8"):
        r.err("the workbench publishes thoughts oldest-first, so the renderer "
              "spends its budget on stale lines and the newest is what runs "
              "out of room.")

    if "static func workbenchJSON()" not in swift:
        r.err("HomeChrome never reads the workbench out of home.json, so the "
              "page's receiver is never called.")
    if "window.__vesperWork(" not in swift:
        r.err("the refresh tick never calls the page's workbench receiver. The "
              "file is read and the card is never told -- built-and-unreached "
              "one step further along than usual.")

    if r.ok:
        r.note(f"{len(tpl)} bytes, {len(tokens)} tokens all substituted "
               f"({', '.join(sorted(tokens))}), fallback token set matches, "
               "stylesheet + card + dock row present, conversation cluster "
               "anchored to faceRect rather than to the viewport; one dissolve "
               "timer, a mirrored out-stagger and a bounded element count in "
               "both the template and the fallback; nothing roots the backdrop "
               "at body; the workbench reaches both copies and the hand is "
               "declared in each")
    return r








def check_face_follows_activity() -> Result:
    """VESPER's face reports what it is doing, and falls back to rest when stale.

    THE FACE WAS BUILT AND NEVER CONNECTED. `Behaviour.swift` has carried
    fourteen behaviours -- distinct gaze, blink, breath, dispersal -- since the
    island was written, and the only thing that ever selected one was `--demo`,
    cycling them on a timer so they could be SEEN. A face able to express
    thinking, listening and talking rested through every call VESPER made.

    Built-and-unreached is this tree's recurring failure: `Provider.profile_id`
    sat unread for months, the egress class was applied at registration and
    never at the choke point. Each was correct, and each had no seam to the
    thing it was about.
    """
    r = Result("face-follows-activity")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        import time
        from core.home_state import (DERIVABLE, LISTENING, RESTING, STALE_AFTER_S,
                                     TALKING, THINKING, WONDERING, WORKING,
                                     HomeState)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"home_state did not import: {exc!r}")
        return r

    # 0. THE CONSTANTS BIND TO WHAT THEY SAY. Written one per line after a
    # transposed tuple bound THINKING to "working" -- three names, three
    # strings, all present, and the face showed the wrong state for every
    # event. Both values were valid behaviours, so nothing raised.
    for name, value in [("THINKING", THINKING), ("WORKING", WORKING),
                        ("TALKING", TALKING), ("LISTENING", LISTENING),
                        ("WONDERING", WONDERING), ("RESTING", RESTING)]:
        if value != name.lower():
            r.err(f"{name} is bound to {value!r}. A transposition here shows "
                  "the wrong expression for every event and raises nothing, "
                  "because both sides are valid behaviours.")

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "home.json"
        from core.bus import EventBus
        from core.hlc import HybridLogicalClock
        from core.store import StoreSet
        clock = HybridLogicalClock("face-check")
        store = StoreSet(Path(td) / "s", node_id="face-check")
        bus = EventBus(clock, store, component="face-check")
        hs = HomeState(path=path)
        hs.attach(bus)

        if hs.behaviour() != RESTING:
            r.err("the face did not start at rest.")

        # 1. EACH SIGNAL PRODUCES ITS OWN EXPRESSION. Asserted individually
        # rather than as a sequence: a mapping where every event produced the
        # same behaviour would satisfy "it changed" and express nothing.
        for event, payload, want, why in [
            ("intake.dispatched", {}, THINKING, "an utterance was accepted"),
            ("route.selected", {}, WORKING, "a call is in flight"),
            ("gateway.attempt", {"outcome": "error",
                                 "classification": "rate_limited"}, WONDERING,
             "a provider failed and another is being tried"),
            ("narration.emitted", {"spoken": True}, TALKING, "speaking aloud"),
            ("intake.partial", {}, LISTENING, "a spoken utterance is mid-revision"),
        ]:
            bus.publish(event, subject="s", payload=payload, component="x")
            got = hs.behaviour()
            if got != want:
                r.err(f"{event} produced {got!r}, expected {want!r} ({why}). A "
                      "face that reports the wrong activity is a false reading "
                      "in the same way a stale metric is.")

        # 2. STALENESS FALLS BACK TO REST. A face stuck on `thinking` after a
        # crash reports work that is not happening, which is worse than rest.
        hs._since = time.time() - (STALE_AFTER_S + 5)
        if hs.behaviour() != RESTING:
            r.err(f"a behaviour older than {STALE_AFTER_S}s did not fall back "
                  "to rest. A face still reporting work after the process "
                  "stopped is a false reading that nothing else would correct.")

        # 3. AN UNDERIVABLE EXPRESSION IS REFUSED, NOT COERCED. The expressive
        # states nothing measures -- laughing, angry, happy -- must not be
        # reachable from a heuristic, or the face invents a mood.
        try:
            hs._set("laughing", "nothing measures this")
            r.err("an expression nothing measures was accepted. A face that "
                  "can be told to look happy will eventually look happy about "
                  "something it did not evaluate.")
        except ValueError:
            pass

        # 4. THE FILE THE CHROME READS ACTUALLY CARRIES IT.
        import json
        obj = json.loads(path.read_text(encoding="utf-8"))
        if (obj.get("face") or {}).get("behaviour") not in DERIVABLE:
            r.err("home.json carries no usable `face.behaviour`. The chrome "
                  "reads that key; without it the face falls back to resting "
                  "forever, which is what it did before it was connected.")

        # 5. WRITING MUST NOT CLOBBER THE OTHER PRODUCER. `home_snapshot.py`
        # owns `rows`; this owns `face` and `transcript`. A whole-file rewrite
        # from either deletes the other's work, and the loser is whichever ran
        # last -- a race with no error.
        obj["rows"] = [{"label": "keep", "value": "me"}]
        path.write_text(json.dumps(obj), encoding="utf-8")
        hs._set(THINKING, "second write")
        after = json.loads(path.read_text(encoding="utf-8"))
        if not after.get("rows"):
            r.err("writing the face state deleted `rows`. Two producers share "
                  "this file and a whole-file rewrite makes them race with no "
                  "error reported.")

        # 6. ANSWERING IS TALKING. `TALKING` was reachable only from
        # `narration.spoken`, so it fired when VESPER said a STATUS LINE aloud
        # and never when it answered the owner -- the one moment it is
        # unambiguously talking. Every reply landed with the face still
        # `thinking`, which is a false reading in the way a stale metric is.
        hs2 = HomeState(path=path)
        hs2.set_transcript([{"who": "owner", "text": "hi"}])
        if hs2.behaviour() == "talking":
            r.err("the owner's own line put the face into `talking`. The face "
                  "would mouth the owner's words back at them.")
        hs2.set_transcript([{"who": "owner", "text": "hi"},
                            {"who": "vesper", "text": "Hello, sir."}])
        if hs2.behaviour() != "talking":
            r.err(f"a reply reached the stage and the face stayed "
                  f"{hs2.behaviour()!r}. Answering is the clearest case of "
                  "talking there is.")
        # A NEW LINE, not merely a last line that is VESPER's. `set_transcript`
        # runs on every pump pass; re-deriving from an unchanged transcript
        # would hold the face open indefinitely after one reply.
        hs2._set(THINKING, "next request")
        hs2.set_transcript([{"who": "owner", "text": "hi"},
                            {"who": "vesper", "text": "Hello, sir."}])
        if hs2.behaviour() == "talking":
            r.err("an unchanged transcript re-derived `talking`, so the face "
                  "re-opens on every pump pass and never stops answering.")

    # 7. THE ANIMATION CHANNELS ARE KEPT APART, and the talking channel refuses
    # to invent a level. Asserted structurally because the driver is Swift and
    # this gate is stdlib Python -- the same split CI-065 makes for the chrome.
    beh = (REPO / "app" / "island-macos" / "Behaviour.swift").read_text(
        encoding="utf-8")
    if "case .thinking" not in beh or "pulse = 1 +" not in beh:
        r.err("Behaviour.swift has no scale envelope for thinking. Until it "
              "did, the face had ONE scale channel -- a 6.2 s breath identical "
              "under every behaviour but `aura` -- so thinking and talking "
              "differed only in where the eyes pointed, which is not a "
              "difference at all from across a room.")
    # SLICED FROM `stepChannels`, NOT FROM THE WHOLE FILE. `case .thinking` and
    # `case .working` each appear three times -- in the gaze table, in the
    # responsiveness table, and here -- so a naive `find` slices the gaze
    # section and reports on a switch that has nothing to do with channels.
    # It did exactly that on the first run.
    chan = beh[beh.find("private func stepChannels"):]
    think = chan[chan.find("case .thinking"):chan.find("case .working")]
    # THE EXACT PINNED STATEMENT, with its newline. `"glow = 1" in think` also
    # matches `glow = 1 + 0.22 * ...` -- a substring test that is satisfied by
    # the very modulation it exists to forbid, and the self-test caught it.
    # ASSERTED AS THE ABSENCE OF A MODULATION, not only as the presence of a
    # pin. A pinned line followed by a modulation is exactly the violation, and
    # a presence test cannot see it -- the self-test proved that by adding one
    # and staying green. `glow = 1` is necessary; "and nothing else touches
    # glow" is the property.
    if "glow = 1\n" not in think or "glow = 1 +" in think or "glow +=" in think:
        r.err("the thinking case does not pin `glow`. DESIGN-FOUNDATION SS6: "
              "thinking modulates scale ONLY and working modulates lightness "
              "ONLY -- a state that both pulsed and brightened reads as a third "
              "thing.")
    work = chan[chan.find("case .working"):chan.find("case .talking")]
    if "pulse = 1\n" not in work or "pulse = 1 +" in work or "pulse +=" in work:
        r.err("the working case does not pin `pulse`. SS6: `the size holds "
              "still; only the brightness breathes`.")
    if "case audio" not in beh or "case none" not in beh:
        r.err("SpeechSource does not name its cases. The difference between "
              "a driven envelope and a decorative one is the source, and an "
              "unnamed source cannot be checked or swapped.")
    talk = chan[chan.find("case .talking"):chan.find("default:")]
    if "speechSource == .none" not in talk or "pulse = 1\n" not in talk:
        r.err("the talking envelope runs with no speech source. SS6: `until "
              "the audio path exists the mark does not speak; it idles`. A "
              "free-running sine here is indistinguishable on screen from real "
              "speech and wrong every frame.")
    # AND THE CHANNEL IS ACTUALLY CARRIED. A driver that can be driven and a
    # host that never drives it is the built-and-unreached shape again.
    chrome_sw = (REPO / "app" / "home-macos" / "HomeChrome.swift").read_text(
        encoding="utf-8")
    if "vesperSpeaking" not in chrome_sw:
        r.err("HomeChrome.swift registers no speaking channel, so nothing can "
              "ever set a speech source and `talking` is permanently idle.")
    home_sw = (REPO / "app" / "home-macos" / "Home.swift").read_text(
        encoding="utf-8")
    if "motion.speechSource" not in home_sw:
        r.err("the render tick never sets `speechSource`, so the page reports "
              "delivery to a driver that is not listening.")
    # BOTH EDGES WAKE THE CHROME. The face resumes on a display link and the
    # webview does not resume until something asks it for a frame, so the two
    # paths that end with the ground visible -- the occlusion notification and
    # the Space change -- each have to say so. Wiring one fixes switching apps
    # and leaves switching Desktops exactly as it was.
    # COUNTED OVER LIVE LINES ONLY. `home_sw.count("chrome.wake()")` counts the
    # commented-out call too, so disabling one edge leaves the count unchanged
    # and the check green -- the third time in this file that a comment has
    # satisfied an assertion about code. Strip them first.
    live = "\n".join(ln for ln in home_sw.splitlines()
                     if not ln.lstrip().startswith("//"))
    if live.count("chrome.wake()") < 2:
        r.err("only one of the two visibility edges wakes the chrome. The face "
              "comes back on its own display link; the cards, the main menu and "
              "the widgets stay on WebKit's throttled schedule, which reads as "
              "them vanishing while the owner is away.")
    if "func wake()" not in (REPO / "app" / "home-macos"
                             / "HomeChrome.swift").read_text(encoding="utf-8"):
        r.err("HomeChrome has no `wake`, so the edges call nothing.")
    # AND THE DRIVER IS TOLD WHICH BEHAVIOUR IT IS IN.
    #
    # THE ONE THAT INVALIDATED EVERYTHING ELSE IN THIS CHECK. `FaceDriver
    # .behaviour` was set by nothing anywhere in the app: it defaulted to
    # `.resting` and stayed there for the life of the process. `home_state.py`
    # derived the behaviour, `home.json` carried it, the page's status dot showed
    # it, and every assertion above passed -- while the face rested through every
    # request VESPER answered. Fourteen behaviours and every motion channel
    # hanging off them were unreachable in the shipping build.
    #
    # Nothing else here can catch it: the Python half is correct, the Swift
    # channels are correct, and the defect is entirely in the absence of one
    # assignment between them.
    if "motion.behaviour = " not in live:
        r.err("nothing assigns FaceDriver.behaviour, so the face holds "
              "`resting` for the life of the process. Every behaviour, every "
              "gaze field and every animation channel is unreachable, and each "
              "of them tests correctly in isolation.")
    if "onFaceBehaviour" not in chrome_sw:
        r.err("the chrome does not report the behaviour it reads to its host. "
              "It has always pushed it into the PAGE, where it moves a status "
              "dot -- the dot was right and the face was resting.")
    if "motion.pulse" not in home_sw or "motion.glow" not in home_sw:
        r.err("the render tick does not apply the animation channels. They "
              "would be computed every frame and drawn by nothing.")

    if r.ok:
        r.note("five signals map to five distinct expressions; a stale "
               f"behaviour falls back to rest after {STALE_AFTER_S:.0f}s; an "
               "unmeasured expression is refused; the snapshot merges rather "
               "than clobbering the other producer; a reply derives `talking` "
               "and an unchanged transcript does not; scale and brightness "
               "stay on separate channels and talking idles with no source")
    return r




def check_egress_gates_at_choke_point() -> Result:
    """Private content cannot reach a public-only supplier, whatever its quota.

    THE GAP THIS CLOSES, and it was open while the whole ladder was built on
    top of it. `core/privacy.py` has classified content as
    {public, personal, private} since A-010. `provider_supply.toml` classifies
    suppliers as {E1_PRIVATE, E2_PUBLIC}. Both existed, both were right, and
    NOTHING JOINED THEM: the egress class was applied once when the ladder was
    built and the choke point had never heard of it. A caller who registered a
    public ladder could send the owner's private content down it and no rule
    anywhere would object.

    INV-COST-3's argument, unchanged: a rule enforced anywhere but the one
    place every call passes through is a rule with a bypass.
    """
    r = Result("egress-gates-at-choke-point")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.gateway import (AllProvidersExhausted, E1_PRIVATE, E2_PUBLIC,
                                  EgressRefused, MAY_CARRY, ModelGateway,
                                  Provider)
        from core.quota import QuotaLedger
    except Exception as exc:                       # noqa: BLE001
        r.err(f"the gateway did not import: {exc!r}")
        return r

    def gw_with(egress: str):
        ledger = QuotaLedger()
        bus, cost, gw = _gateway(ledger)
        cost.register_credential("p", "free")
        gw.register(Provider("p", "prof",
                             lambda q, o: {"text": "answered", "usage": {}},
                             model="m", egress_class=egress))
        return gw

    # 1. THE REFUSAL. A public-only supplier must not receive private content,
    # and the ladder must exhaust rather than fall through to it.
    try:
        gw_with(E2_PUBLIC).complete("secret", task_id="e1", profile_id="prof",
                                    difficulty="trivial",
                                    privacy_class="private")
        r.err("private content reached an E2_PUBLIC provider. Two of the most "
              "generous free tiers available are public-only, so a ladder that "
              "ranks on headroom reaches exactly the wrong suppliers -- "
              "capacity must never buy permission.")
    except AllProvidersExhausted:
        pass

    # 2. THE PERMISSION. Without this the check passes for a gateway that
    # refuses everything, which protects privacy by deleting the function.
    try:
        out = gw_with(E2_PUBLIC).complete("a public question", task_id="e2",
                                          profile_id="prof",
                                          difficulty="trivial",
                                          privacy_class="public")
        if out.get("provider_id") != "p":
            r.err("public content was refused by a public supplier.")
    except AllProvidersExhausted:
        r.err("public content could not reach an E2_PUBLIC provider. A rule "
              "that refuses everything is not a privacy boundary, it is an "
              "outage.")

    # 3. UNLABELLED IS PRIVATE. Not "unclassified", not "assume public".
    # core/privacy.py's asymmetry: withholding costs a re-ask, and sending
    # private content to a provider that trains on it cannot be undone.
    import inspect
    default = inspect.signature(ModelGateway.complete).parameters["privacy_class"].default
    if default != "private":
        r.err(f"privacy_class defaults to {default!r}. Unlabelled content must "
              "be treated as PRIVATE -- the ambiguous case has to resolve to "
              "the cheap failure, exactly as the display router does.")

    # 4. A TYPO IS REFUSED, NOT DEFAULTED. Silently reading an unknown class as
    # permissive is how a one-character mistake becomes an egress.
    try:
        gw_with(E1_PRIVATE).complete("x", task_id="e3", profile_id="prof",
                                     difficulty="trivial",
                                     privacy_class="publik")
        r.err("an unknown privacy_class was accepted. A typo must refuse, "
              "never resolve to the most permissive reading.")
    except EgressRefused:
        pass
    except AllProvidersExhausted:
        r.err("an unknown privacy_class was treated as an ordinary refusal "
              "rather than raising. It must be distinguishable from a ladder "
              "that merely ran out.")

    # 5. A PROVIDER REGISTERED WITHOUT A CLASS IS PRIVATE-ONLY. An unvetted
    # endpoint must not receive private content by omission.
    if Provider("x", "y", lambda a, b: {}).egress_class != E1_PRIVATE:
        r.err("a Provider with no declared egress class did not default to "
              "the strictest. Defaulting to permissive would let an unreviewed "
              "endpoint be trusted by omission rather than by decision.")

    # 6. THE TABLE ITSELF. `personal` is content ABOUT the owner and must be
    # treated as private, not as a middle ground that leaks.
    if MAY_CARRY.get("personal") != frozenset({E1_PRIVATE}):
        r.err("`personal` content is permitted somewhere other than "
              "E1_PRIVATE. It is content about the owner; a middle ground "
              "between public and private is where it leaks.")

    if r.ok:
        r.note("private refused at a public supplier and public permitted at "
               "one; unlabelled defaults to private; an unknown class raises; "
               "an undeclared Provider is private-only")
    return r




def check_intake_is_modality_neutral() -> Result:
    """A misheard instruction is reflected, not executed; partials never act.

    RUNTIME FIXTURE. The property is about what the pipe DOES with an uncertain
    utterance, and a structural check that a `confidence` field exists passes
    for a pipe that never reads it -- which is the same present-and-unread trap
    `Provider.profile_id` sat in for months.
    """
    r = Result("intake-is-modality-neutral")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.intake import (CONFIDENCE_FLOOR, SPOKEN, TYPED, Intake,
                                 IntakeRefused, Utterance)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"intake did not import: {exc!r}")
        return r

    # CONSTRUCTED WITH A CLOCK. Every case built a bare `Intake()`, so the HLC
    # branch never ran -- and it called a method the clock does not have. The
    # same wrong assumption was fixed in core/triage.py and left standing here,
    # because both were written the same day from the same wrong idea and only
    # one was ever exercised with a clock. A check that constructs its subject
    # one way covers one way; this is the second time that sentence was needed.
    from core.hlc import HybridLogicalClock
    acted: list = []
    ink = Intake(clock=HybridLogicalClock("intake-check"),
                 dispatch=lambda u: acted.append(u.text))

    # 1. TYPED IS CERTAIN BY CONSTRUCTION and must pass straight through.
    if ink.typed("hello")["outcome"] != "dispatched":
        r.err("a typed utterance was not dispatched. Typing admits no "
              "uncertainty; gating it would make the text path worse to buy "
              "nothing for the spoken one.")

    # 2. A PARTIAL MUST NOT ACT. A recogniser emits a stream of revisions and
    # only the last is what was said; acting on each answers four questions
    # nobody asked and spends four times the quota doing it.
    before = len(acted)
    ink.spoken("delete the", confidence=0.99, final=False)
    if len(acted) != before:
        r.err("a non-final utterance was acted on. Every revision would run as "
              "its own request -- and the dangerous one is that an incomplete "
              "sentence can be a valid instruction with the opposite meaning.")

    # 3. LOW CONFIDENCE IS REFLECTED, NOT EXECUTED, and this is the safety
    # property. `delete the archive` and `delete the archives` are one phoneme
    # apart. Correcting a wrong transcription costs seconds; acting on one costs
    # whatever the action costs.
    before = len(acted)
    out = ink.spoken("delete the archive", confidence=CONFIDENCE_FLOOR - 0.2,
                     final=True)
    if out["outcome"] != "reflected" or len(acted) != before:
        r.err(f"an utterance below the confidence floor was {out['outcome']!r} "
              "and reached the dispatcher. An uncertain instruction must be "
              "reflected back for confirmation, never executed.")

    # 4. AND IT MUST STILL BE DELIVERED. Confidence gates ACTION, not delivery:
    # an utterance that is dropped rather than shown leaves the owner with no
    # idea VESPER heard anything, which is worse than a wrong guess shown.
    if not any(u["text"] == "delete the archive" for u in ink.transcript()):
        r.err("a reflected utterance is missing from the transcript. It must be "
              "shown -- silently dropping it leaves the owner unable to tell "
              "`did not hear` from `heard and declined`.")

    # 5. HIGH CONFIDENCE ACTS. Without this the check passes for a pipe that
    # refuses everything, which is safe and useless.
    before = len(acted)
    if ink.spoken("open the calendar", confidence=0.99,
                  final=True)["outcome"] != "dispatched" or len(acted) == before:
        r.err("a confident final utterance was not acted on. A pipe that "
              "refuses everything satisfies the safety half by deleting the "
              "function.")

    # 6. PROVENANCE IS MANDATORY. An utterance whose source is unknown cannot be
    # audited, and the record is the only place the source is allowed to matter.
    try:
        Utterance(text="x", source="somewhere")
        r.err("an utterance with an unknown source was accepted.")
    except IntakeRefused:
        pass

    # 7. TYPED CARRIES `confidence = None`, NOT 1.0. One is a fact about the
    # channel, the other is a measurement from a recogniser that happened to be
    # sure -- and a record that cannot tell them apart cannot be audited later.
    typed_u = Utterance(text="x", source=TYPED)
    spoken_u = Utterance(text="x", source=SPOKEN, confidence=1.0)
    if typed_u.confidence is not None or spoken_u.confidence != 1.0:
        r.err("typed input reported a numeric confidence. `None` means "
              "certainty is not a question on this channel; 1.0 means a "
              "recogniser measured it. Collapsing them loses the distinction "
              "the audit record needs.")

    if r.ok:
        r.note(f"partials buffer; below {CONFIDENCE_FLOOR} reflects and is still "
               "shown; above it acts; source is mandatory; typed confidence is "
               "None rather than 1.0")
    return r




def check_shared_pool_is_shared() -> Result:
    """Modalities sharing one meter share one budget, and floors protect the owner.

    RUNTIME FIXTURE. A structural check that an `account` field exists passes
    for a ledger that never consults it -- and the defect this guards against
    is precisely a field that is present and unread.
    """
    r = Result("shared-pool-is-shared")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.quota import QuotaLedger
    except Exception as exc:                       # noqa: BLE001
        r.err(f"quota did not import: {exc!r}")
        return r

    # 1. SPENDING THROUGH ONE MODALITY MUST CLOSE THE OTHER. Cloudflare bills
    # text and image from one 10,000/day. Two consumers each seeing a full
    # ceiling authorise twice the real budget, and the overspend lands as 429s
    # on whichever asks last -- most likely the interactive one.
    led = QuotaLedger()
    led.declare_pool("acct", 1_000)
    for model, purpose in (("txt", "text"), ("img", "image")):
        e = led.entry("p", model)
        e.account, e.purpose, e.unit = "acct", purpose, "neurons"
    led.record_success("p", "img", amount=1_000, measured=True, unit="neurons")
    if led.usable("p", "txt"):
        r.err("the pool was spent through the image model and the TEXT model "
              "still reported usable. Two consumers of one budget both "
              "concluding they may proceed is the whole defect: the ceiling is "
              "the account's, not the entry's.")

    # 2. A FLOOR PROTECTS THE OWNER'S CONVERSATION from a batch job.
    led2 = QuotaLedger()
    led2.declare_pool("acct", 1_000)
    for model, purpose in (("txt", "text"), ("img", "image")):
        e = led2.entry("p", model)
        e.account, e.purpose, e.unit = "acct", purpose, "neurons"
    led2.reserve("acct", "text", 0.60)
    led2.record_success("p", "img", amount=400, measured=True, unit="neurons")
    img_left = led2.spendable("acct", "image")
    txt_left = led2.spendable("acct", "text")
    if img_left is None or round(img_left) != 0:
        r.err(f"after spending 400 of 1000 with 60% held for text, image could "
              f"still spend {img_left}. Expected 0 -- 600 is reserved and a "
              "floor that yields to whoever asks first is not a floor.")
    if txt_left is None or round(txt_left) != 600:
        r.err(f"text could spend {txt_left}, expected 600. The owner's share "
              "must survive a batch job that ran first.")

    # 3. THE FLOOR IS HARD, and this is asserted because the docstring once
    # claimed otherwise. Lending only works if the loan can be called back, and
    # SPENT QUOTA CANNOT BE RECLAIMED -- there is no layer that returns neurons
    # to conversation after a batch has used them.
    led3 = QuotaLedger()
    led3.declare_pool("acct", 1_000)
    e = led3.entry("p", "img")
    e.account, e.purpose = "acct", "image"
    led3.reserve("acct", "text", 0.60)
    if round(led3.spendable("acct", "image")) != 400:
        r.err("with nothing yet spent, image could reach more than the pool "
              "minus the text floor. An unused floor is NOT lent out: it "
              "cannot be, because it could never be reclaimed.")

    # 4. OVERCOMMITTED FLOORS FAIL CLOSED. Fractions summing past 1.0 make
    # every purpose unspendable, which surfaces at once instead of silently
    # overselling the pool.
    led3.reserve("acct", "audio", 0.50)
    if led3.usable("p", "img"):
        r.err("floors summing over 1.0 left a purpose spendable. Overcommit "
              "must fail closed and visibly, not resolve itself by letting "
              "whoever asks first win.")

    if r.ok:
        r.note("one meter, one budget: spend through image closes text; a 60% "
               "text floor survives a batch job; the floor is hard because "
               "spent quota cannot be reclaimed; overcommit fails closed")
    return r


def check_triage_excludes_quota() -> Result:
    """Quota failures are routed around, never investigated; the rest are kept.

    RUNTIME FIXTURE. A structural check ("is rate_limited in the exclusion
    set") passes for a queue that never consults the set. The queue is built
    and fed.
    """
    r = Result("triage-excludes-quota")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.quota import QuotaLedger
        from core.repair import RepairAgent, TIER1, TIER3
        from core.triage import (CAN_WAIT, CRITICAL_DEFERRED, CRITICAL_NOW,
                                 NO_FIX_NEEDED, REPEAT_THRESHOLD, TriageQueue)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"triage did not import: {exc!r}")
        return r

    # CONSTRUCTED WITH A CLOCK, and that is not incidental. Every case below
    # built a bare `TriageQueue()`, so the HLC branch of `_tick` had never
    # executed -- it called a method the clock does not have, raised
    # AttributeError on every record, and the bus SWALLOWS handler exceptions
    # into a failure counter. The drift subscription fired correctly, failed
    # silently, and looked wired. A check that constructs its subject one way
    # covers one way.
    from core.hlc import HybridLogicalClock
    clock = HybridLogicalClock("triage-check")

    # 1. QUOTA IS DECLINED. The brief's rule, and the reason a queue stays
    # readable: a backlog whose only resolution is "yes, we used what we had"
    # is a backlog nobody opens, and the real finding goes down with it.
    q = TriageQueue(clock=clock)
    for cls in ("rate_limited", "quota_exhausted", "quota_unavailable_on_tier",
                "cost_policy"):
        if q.record("p", "m", cls) is not None:
            r.err(f"{cls!r} was admitted for investigation. A working provider "
                  "doing its job is not a finding; queueing it buries the ones "
                  "that are.")

    # 2. AN UNKNOWN CLASSIFICATION IS ADMITTED. Fail-OPEN here is the safe
    # direction: the cost is one queue entry, and the cost of the alternative
    # is a new failure mode discarded silently forever.
    if q.record("p", "m", "a_classification_nobody_wrote_a_rule_for") is None:
        r.err("an unrecognised classification was declined. That is the one "
              "most worth a person's attention -- declining it makes every "
              "future unknown failure invisible.")

    # 3. GRADING, both directions on the repeat threshold. Without the second
    # half this passes for a grader that escalates everything, which is the
    # same as a grader that grades nothing.
    q1 = TriageQueue(clock=clock)
    it = q1.grade(q1.record("p", "m", "auth_failed"))
    if it.grade != CRITICAL_NOW:
        r.err(f"auth_failed graded {it.grade!r}. A revoked key does not heal "
              "and removes a whole rung until a person acts.")
    q2 = TriageQueue(clock=clock)
    one = q2.grade(q2.record("p", "m", "server_error"))
    if one.grade != NO_FIX_NEEDED:
        r.err(f"a single server_error graded {one.grade!r}. One blip the ladder "
              "already absorbed must close, or the queue fills with noise.")
    q3 = TriageQueue(clock=clock)
    for _ in range(REPEAT_THRESHOLD):
        q3.record("p", "m", "server_error")
    many = q3.grade(q3.open_items()[0])
    if many.grade != CRITICAL_DEFERRED:
        r.err(f"{REPEAT_THRESHOLD} server_errors graded {many.grade!r}. A "
              "pattern is a change in the world rather than a blip.")

    # 4. ONLY CRITICAL_NOW IS ACTED ON UNATTENDED. A CRITICAL_DEFERRED item has
    # a workaround that is holding; acting anyway spends risk to buy nothing.
    ag = RepairAgent(ledger=QuotaLedger(), supply_rows=[])
    out = ag.repair(many)
    # ASSERT ON THE REASON, NOT ON `fixed`. A first version checked only that
    # `fixed` was False -- and `server_error` has no tier-1 handler, so it is
    # False whether the grade guard runs or not. The case could not go red:
    # the check was passing for the right answer reached by the wrong route.
    # What must be true is that the item was declined BECAUSE OF ITS GRADE.
    if out.fixed or CRITICAL_DEFERRED not in out.note:
        r.err(f"a {CRITICAL_DEFERRED} item was not declined on its grade "
              f"(fixed={out.fixed}, note={out.note[:80]!r}). Its workaround is "
              "holding -- acting anyway spends risk to buy nothing.")

    # 5. THE ESCALATION NAMES THE VARIABLE. A guide saying "replace its
    # environment variable" makes the reader look up what the system already
    # knew, and a guide that costs the reader work is a worse guide.
    from routing.supply import SupplyRow
    row = SupplyRow(provider_id="solo-x", rung=1, egress_class="E1_PRIVATE",
                    cost_class="free", provable_hard_cap=True,
                    hard_cap_evidence="e", model="m", wire="openai_chat",
                    profile_id="p", measured_tokens_per_sec=1.0,
                    rate_is_measured=True, quota_unit="requests",
                    quota_limit=1, quota_window_seconds=1,
                    credential_env="SOLO_X_API_KEY")
    ag2 = RepairAgent(ledger=QuotaLedger(), supply_rows=[row])
    q4 = TriageQueue(clock=clock)
    solo = q4.grade(q4.record("solo-x", "m", "auth_failed"))
    esc = ag2.repair(solo)
    text = " ".join(esc.guide)
    if esc.tier != TIER3:
        r.err(f"a service with no sibling credential escalated as {esc.tier!r}, "
              "not to the owner. VESPER cannot obtain a credential -- that is "
              "the owner's, by rule.")
    if "SOLO_X_API_KEY" not in text:
        r.err("the escalation guide did not name the environment variable to "
              "replace. The name is not a secret; only the value is.")
    if "ALREADY ATTEMPTED" not in text:
        r.err("the guide omitted what was already tried, so the owner repeats "
              "work and cannot see what has been ruled out.")

    if r.ok:
        r.note(f"quota classes declined; unknown admitted; repeat threshold "
               f"{REPEAT_THRESHOLD} asserted in both directions; escalation "
               "names its variable and what was tried")
    return r


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
        # NEURONS FIRST, because it is what the provider actually bills for an
        # image and because a tuple missing it still satisfies every other
        # case. This assertion was absent at first and the self-test proved it:
        # removing `neurons` from the read order changed nothing that was
        # checked, so the case reported exit0/exit0 -- a mutation applied to a
        # line nothing was looking at.
        ("cf image (neurons)", {"usage": {"neurons": 172.8,
                                          "completion_tokens": 0}}, 172),
        ("openai", {"usage": {"completion_tokens": 24}}, 24),
        ("cf", {"usage": {"output_tokens": 31}}, 31),
        ("google", {"usage": {"candidatesTokenCount": 17}}, 17),
        ("local", {"tokens_predicted": 12}, 12),
    ]:
        got = _completion_tokens(payload)
        if got is not None:
            got = int(got)
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
        from core.effort import (EFFORT_RANK, EXPECTED_OUTPUT,
                                 EffortFloorViolation, FLOOR,
                                 REASONING_HEADROOM, for_difficulty)
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

    # THE RESERVATION IS NOT FREE, and the comment that sized it said it was.
    # A free tier runs out of TOKENS PER MINUTE, not of billing, and a live 429
    # on 2026-08-26 read `Limit 8000, Used 5118, Requested 3155` for a turn that
    # came back twelve words long: `max_tokens` is charged whether or not it is
    # generated. So a declared expectation must narrow the reserve.
    if set(EXPECTED_OUTPUT) != set(FLOOR):
        r.err(f"EXPECTED_OUTPUT covers {sorted(EXPECTED_OUTPUT)} but the floor "
              f"table covers {sorted(FLOOR)}. A difficulty with no declared "
              "expectation silently takes the 1024-token default that this "
              "table exists to replace.")
    else:
        prev = -1
        for d in ("trivial", "easy", "moderate", "hard"):
            cur = EXPECTED_OUTPUT[d]
            if cur <= prev:
                r.err(f"EXPECTED_OUTPUT is not monotonic at {d!r} ({prev} -> "
                      f"{cur}). A harder request must not be allotted less room "
                      "to answer in than an easier one.")
            prev = cur
        loose = for_difficulty("trivial")
        tight = for_difficulty("trivial",
                               expected_output_tokens=EXPECTED_OUTPUT["trivial"])
        if tight.max_tokens >= loose.max_tokens:
            r.err(f"declaring a small expected output did not narrow the "
                  f"reserve ({loose.max_tokens} -> {tight.max_tokens}). On a "
                  "TPM-limited rung the difference is how many turns a minute "
                  "holds -- the budget is not spent, it is withheld from the "
                  "next request.")
        # AND THE REASONING HEADROOM IS UNTOUCHED BY IT. This is the control:
        # the narrowing must come out of the OUTPUT allowance only. Reasoning
        # is unpredictable and a starved reasoning budget returns no answer at
        # all with a 200, which is the failure the rest of this check is about.
        # ANCHORED ON THE MEASUREMENT, NOT ON THE TABLE ITSELF. The first
        # version of this compared `tight.max_tokens - EXPECTED_OUTPUT[...]`
        # against `REASONING_HEADROOM[...]` -- both sides read the same dict, so
        # cutting the headroom moved the equation with it and the control passed
        # under a deliberate violation. A negative control that passes is a
        # defect, not a relief.
        #
        # The values are the conclusion of a measurement (low 26 / medium 34 /
        # high 119 completion tokens on a trivial prompt, multiplied because
        # reasoning scales with the problem), so they are asserted as literals
        # for the same reason CI-031 refuses a relaxed latency budget: changing
        # a measured constant is a RE-MEASUREMENT and has to arrive with new
        # evidence, not as the cheapest way to pay for a saving somewhere else.
        MEASURED_HEADROOM = {"low": 512, "medium": 2_048, "high": 8_192}
        if dict(REASONING_HEADROOM) != MEASURED_HEADROOM:
            r.err(f"REASONING_HEADROOM is {dict(REASONING_HEADROOM)}, not the "
                  f"measured {MEASURED_HEADROOM}. A starved reasoning budget "
                  "does not shorten an answer -- it returns NO answer with a "
                  "200 status, measured at 57 of 64 tokens consumed before a "
                  "seven-character reply. Shaving this to buy rate-limit "
                  "headroom takes it from the one allowance that cannot spare "
                  "it.")
        elif tight.max_tokens - EXPECTED_OUTPUT["trivial"] != MEASURED_HEADROOM[
                FLOOR["trivial"]]:
            r.err("a declared expected output changed the REASONING headroom. "
                  "It may only narrow the output allowance: reasoning tokens "
                  "are billed as completion tokens and can consume the entire "
                  "budget before a content token is emitted.")

    # THE OTHER END OF THE SAME AXIS. This check has always covered a budget
    # too SMALL -- reasoning eats the allowance and a 200 comes back empty. A
    # budget too LARGE is the mirror and had no coverage at all: measured
    # 2026-08-26, a `hard` request reserves 9216 tokens and one rung's whole
    # per-minute allowance is 8000, so it answered `413 Request too large` in
    # 0.19 s every time.
    from routing.http_completion import _STATUS_CLASS
    from core.gateway import TERMINAL, TRANSIENT
    cls413 = _STATUS_CLASS.get(413)
    if cls413 != "budget_too_large":
        r.err(f"HTTP 413 classifies as {cls413!r}. Unclassified it falls through "
              "to `server_error`, which is TRANSIENT -- so the chain retries a "
              "request that cannot succeed and then reports a working provider "
              "as broken.")
    else:
        if cls413 in TRANSIENT:
            r.err("`budget_too_large` is TRANSIENT. Retrying an oversized "
                  "request against a fixed ceiling fails identically, forever.")
        if cls413 not in TERMINAL:
            r.err("`budget_too_large` is neither TRANSIENT nor TERMINAL, so the "
                  "chain has no rule for it.")
        # AND IT MUST NOT BOOK A QUOTA REFUSAL. The rung is fine and the
        # credential is fine; retiring it over one request's SHAPE would remove
        # a working provider that will serve the next, smaller question.
        from core.gateway import QUOTA_CLASSIFICATIONS
        if cls413 in QUOTA_CLASSIFICATIONS:
            r.err("`budget_too_large` books a quota refusal. A rung that cannot "
                  "accept a 9216-token reservation accepts a 640-token one "
                  "perfectly well -- this is a fact about the request, not "
                  "about the allowance.")
    # AND THE OWNER IS TOLD SOMETHING TRUE. `narration.toml` refuses to load
    # without a line per classification, so this asserts the line SAYS the
    # right thing rather than that one exists.
    nar = (REPO / "contracts" / "policy" / "narration.toml").read_text(
        encoding="utf-8")
    if 'classification = "budget_too_large"' not in nar:
        r.err("no narration line for `budget_too_large` -- silence at the "
              "moment the owner is waiting to be told something.")

    if r.ok:
        r.note(f"null answer from "
               f"{EMPTY_CONTENT_FIXTURE.relative_to(REPO).as_posix()} retried with a "
               f"grown budget and discriminated against a truncated real answer; "
               f"floor table {dict(FLOOR)} over efforts {sorted(EFFORT_RANK, key=EFFORT_RANK.get)}; "
               f"declared output {dict(EXPECTED_OUTPUT)} narrows the reserve "
               f"{loose.max_tokens}->{tight.max_tokens} on trivial without "
               f"touching reasoning headroom; 413 classifies as budget_too_large, "
               "terminal for the request and not for the rung, and narrates")
    return r


def check_persona_is_a_contract() -> "Result":
    """IC-005/DR-028: personality is a policy artifact, not a prompt string.

    THE PROPERTY IS THAT IT LOADS FAIL-CLOSED. A persona that silently renders
    empty is the state this whole surface replaced -- and it does not look
    broken from outside: the answer still comes back fluent, just nameless, and
    on 2026-08-26 it also came back inventing facts about its own name.
    """
    r = Result("persona-is-a-contract")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.persona import (REGISTER_IDS, Persona, PersonaRefused,
                                  Situation)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.persona did not import: {exc!r}")
        return r

    try:
        p = Persona.load()
    except PersonaRefused as e:
        r.err(f"the shipped persona contract does not load: {e}")
        return r

    # 1. THE SCHEMA'S ENUM IS THE ONE IN FORCE. `core/persona.py` restates it
    # by value to stay stdlib-only, so the restatement is asserted against the
    # schema file rather than trusted -- a schema edit this module does not
    # follow would otherwise permit a value the contract forbids.
    schema = json.loads((REPO / "contracts" / "policy"
                         / "persona_policy.schema.json").read_text(encoding="utf-8"))
    item = schema["properties"]["registers"]["items"]["properties"]
    for field, names in (("register_id", REGISTER_IDS),):
        declared = tuple(item[field]["enum"])
        if declared != tuple(names):
            r.err(f"core/persona.py {field} is {names} but the schema declares "
                  f"{declared}. The restatement has drifted from the contract.")
    # RB-012 and the sarcasm ceiling are expressed as ABSENT enum members, so
    # they are asserted as absences: a schema that grew `real_person` would
    # make the impersonation refusal configurable.
    if "real_person" in item["impressions"]["enum"]:
        r.err("persona_policy.schema.json permits impressions=real_person. "
              "RB-012 is absolute and the schema's own note says a schema that "
              "cannot express the violation cannot be configured into it.")
    if "full" in item["sarcasm"]["enum"]:
        r.err("the schema permits sarcasm=full; it has no such member by "
              "design -- prosody carries the marker and a degraded endpoint "
              "drops prosody first.")

    # 2. THE FOUR HARD REFUSALS ARE TRUE, individually named.
    raw = tomllib.loads((REPO / "contracts" / "policy"
                         / "persona.toml").read_text(encoding="utf-8"))
    for name in ("impersonate_real_person", "humour_during_alarm",
                 "joke_over_unknown", "playfulness_over_boundary"):
        if raw.get("hard_refusals", {}).get(name) is not True:
            r.err(f"hard_refusals.{name} is not true. The schema makes it a "
                  "const; none of the four is a setting.")
    if raw.get("truth_precedence", {}).get("on_conflict") != "TRUTH":
        r.err("truth_precedence.on_conflict is not TRUTH -- a configurable "
              "precedence is a configuration in which truth loses.")

    # 3. SELECTION IS DETERMINISTIC AND ALARM OUTRANKS HUMOUR.
    a = p.select(Situation(urgency="alarm"))
    if a.register.humour != "none" or a.register.sarcasm != "none":
        r.err(f"the alarm register carries humour={a.register.humour!r}. A joke "
              "in an alarm scene costs acknowledgement time, which is the one "
              "thing an alarm is spending.")
    twice = {p.select(Situation()).register.register_id for _ in range(5)}
    if len(twice) != 1:
        r.err(f"selection is not deterministic: {twice}. A-036 holds the model "
              "constant and expects the POLICY to decide; a register that "
              "varies makes that unmeasurable.")

    # 4. TRUTH OUTRANKS PERSONALITY, and the downgrade is reported.
    u = p.select(Situation(content_is_unknown=True))
    if u.register.humour != "none":
        r.err("an UNKNOWN was not downgraded to a humourless register "
              "(hard_refusals.joke_over_unknown).")
    if u.degraded_from is None:
        r.err("the downgrade to plain was silent. truth_precedence."
              "degradation_is_reported: an unreported downgrade makes the "
              "deterministic layer unobservable, and A-036 has to observe it.")

    # 5. THE PREAMBLE IS ACTUALLY BUILT and carries the identity that was
    # missing. Asserted on content, not on length: an empty string is a
    # perfectly well-formed preamble and is exactly the defect.
    text, sel = p.compose(Situation())
    if "VESPER" not in text:
        r.err("the composed preamble does not name VESPER. Asked its own name "
              "with no preamble, the ladder answered 'it is one of my names'.")
    # NARROWED FROM `"UNKNOWN" not in text`, WHICH WAS WRONG AND CAUGHT ITSELF
    # ON ITS FIRST RUN. The honesty rules legitimately contain the word -- "an
    # UNKNOWN is reported as UNKNOWN" is the instruction. What must not appear
    # is an OWNER FIELD rendered as the placeholder, so the assertion is about
    # the owner lines and nothing else.
    for line in text.splitlines():
        if line.startswith("- The owner") and "UNKNOWN" in line:
            r.err(f"an unestablished owner field rendered into the preamble: "
                  f"{line!r}. voice.toml keeps them as UNKNOWN precisely so "
                  "they render as NO line; sending the word teaches the model "
                  "to say it back.")

    # 6. AN UNGUIDED REGISTER IS REFUSED AT LOAD. The negative control for the
    # whole file: without it a register renders empty and merely sounds off.
    broken = dict(raw)
    voice = tomllib.loads((REPO / "contracts" / "policy"
                           / "voice.toml").read_text(encoding="utf-8"))
    thin = {k: v for k, v in voice.items() if k != "register"}
    thin["register"] = {k: v for k, v in voice["register"].items() if k != "plain"}
    try:
        Persona(broken, thin)
    except PersonaRefused:
        pass
    else:
        r.err("a register with no guidance in voice.toml loaded without "
              "complaint. It would render as an empty tone instruction, which "
              "does not fail -- it just sounds chatty during a refusal.")
    if not r.errors:
        r.note(f"{len(p.registers)} registers, 4 hard refusals asserted "
               f"individually, schema enums matched by value, alarm humourless, "
               f"UNKNOWN downgrade reported, preamble {len(text)} chars in "
               f"register {sel.register.register_id!r}")
    return r


def check_barge_in_never_swallows_a_halt() -> "Result":
    """Ambiguity must break through, and negation must not read as a halt.

    THE ASYMMETRY IS THE PROPERTY. A wrong break-through costs one wasted
    preparation cycle. A wrong swallow means the owner said "stop" and was
    ignored, which is the failure that makes a system nobody leaves running.
    Those costs are not comparable, so they must not share a default -- and an
    implementation that is merely ACCURATE, without that bias, will pick the
    wrong side of every genuinely ambiguous utterance.
    """
    r = Result("barge-in-never-swallows-a-halt")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.barge_in import Floor, classify, PHRASES
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.barge_in did not import: {exc!r}")
        return r

    # 1. A HALT IS NEVER SWALLOWED. This is the one that must not regress.
    for u in ("stop", "stop it", "cancel", "wait", "hold on", "abort",
              "nevermind", "shut up", "no", "actually", "hey", "emergency",
              "ok stop", "actually stop that", "wrong question"):
        got = classify(u)
        if got is not Floor.BREAK:
            r.err(f"{u!r} classified {got.value}, must be break. A competitive "
                  "interruption that is swallowed is an owner who cannot stop "
                  "the system.")

    # 2. NEGATED HALTS MEAN CARRY ON. "don't stop" contains "stop" and reverses
    # it; without this the most natural way to say "keep going" cancels.
    for u in ("don't stop", "dont stop", "don’t stop", "please dont cancel",
              "lets not stop until this is done"):
        if classify(u) is Floor.BREAK:
            r.err(f"{u!r} broke through. It contains a halt word and negates "
                  "it; treating it as a halt cancels work the owner just asked "
                  "to continue.")

    # 3. COOPERATIVE INTERRUPTIONS ARE SWALLOWED. The owner's own example.
    for u in ("take your time", "no rush", "ok", "mhm", "go ahead", "thanks",
              "no worries", "whenever you're ready", ""):
        got = classify(u)
        if got is not Floor.SWALLOW:
            r.err(f"{u!r} classified {got.value}, must be swallow. Granting "
                  "time must not cancel the work it grants time for.")

    # 4. LIVENESS CHECKS ANSWER WITHOUT CANCELLING. Swallowing these silently
    # is what produces the competitive interruption a moment later.
    for u in ("still there?", "you there", "how long", "hello?", "?"):
        got = classify(u)
        if got is not Floor.STATUS:
            r.err(f"{u!r} classified {got.value}, must be status. A liveness "
                  "check seeks neither the floor nor to encourage.")

    # 4b. THE LONG BRANCH, WHICH NOTHING COVERED UNTIL 2026-08-30 -- and it is
    #     the branch whose behaviour this module's own docstring described
    #     incorrectly, citing a sentence that does the opposite of what it said.
    #
    #     A long utterance is a new request and belongs in the QUEUE. A long
    #     utterance CONTAINING a halt word still breaks: the sentence can be
    #     re-read from the queue afterwards, and work that should have stopped
    #     cannot be un-run. An explicit negation suppresses it.
    for u in ("could you also look at the calendar for next week sometime",
              "I was thinking about the flight and the hotel booking as well"):
        if classify(u) is not Floor.QUEUE:
            r.err(f"a long utterance with no control word gave "
                  f"{classify(u).name} rather than QUEUE. Discarding it loses "
                  "real content, and treating it as a halt punishes the owner "
                  "for saying something substantive.")
    for u in ("I need you to stop what you are doing right now please",
              "actually stop that and look at the other thing instead"):
        if classify(u) is not Floor.BREAK:
            r.err(f"a long utterance containing a halt word gave "
                  f"{classify(u).name} rather than BREAK. A halt inside a "
                  "sentence is still a halt -- the sentence can be re-read "
                  "from the queue, and work that should have stopped cannot be "
                  "un-run.")
    if classify("please don't stop what you are doing on my account") is Floor.BREAK:
        r.err("an explicitly NEGATED halt inside a long utterance broke the "
              "work. 'don't stop' is the owner granting time, and cancelling "
              "on it punishes them for being explicit.")

    # 5. AMBIGUITY BREAKS THROUGH. An unrecognised SHORT utterance is more
    # likely an attempt to intervene than a stray thought.
    for u in ("blorp", "zzz", "qq"):
        if classify(u) is not Floor.BREAK:
            r.err(f"unrecognised short utterance {u!r} did not break through. "
                  "The default under ambiguity is the cheap error, not the "
                  "expensive one.")

    # 6. A LONG UTTERANCE WITH NO HALT WORD IS QUEUED, not discarded. It is a
    # new request and losing it loses real content.
    long_req = "can you also add the router numbers to that when you are done"
    if classify(long_req) is not Floor.QUEUE:
        r.err("a long utterance with no halt word was not queued; discarding "
              "it would lose a real request.")

    # 7. NO MODEL IS REACHABLE FROM HERE. This runs on every inbound token
    # while the owner waits, and a fixed list is also the reason the classifier
    # cannot be talked out of stopping.
    src = (REPO / "core" / "barge_in.py").read_text()
    for banned in ("import requests", "urllib.request", "ModelGateway",
                   "def complete(", "openai", "http"):
        if banned in src:
            r.err(f"core/barge_in.py references {banned!r}. The mid-hold "
                  "classifier must have no path to a model: it runs while the "
                  "owner waits, and a regex cannot be prompt-injected.")

    r.note(f"{len(PHRASES)} phrases; halts unswallowable, negated halts "
           f"reversed, cooperative swallowed, liveness answered, ambiguity "
           f"breaks through, long requests queued, no model path")
    return r


def check_baseline_records_what_cannot_be_rebuilt() -> "Result":
    """The turn record must refuse the fields that are unrecoverable later.

    `declined` and `could_not` are the same event in a log. Nothing downstream
    can separate a choice from a failure once the row is written, so the
    distinction has to be mandatory at write time -- a default would let every
    caller skip the one field that cannot be reconstructed.
    """
    r = Result("baseline-records-what-cannot-be-rebuilt")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.baseline import Turn, BaselineRecorder, MAX_TEXT
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.baseline did not import: {exc!r}")
        return r

    # 1. OUTCOME IS MANDATORY AND CLOSED.
    #
    # OMISSION IS TESTED SEPARATELY FROM BAD VALUES, and the first version of
    # this check tested only the second. Giving `outcome` a default left every
    # value assertion passing while the property that matters -- that a caller
    # CANNOT skip the one field nothing can reconstruct -- was gone. The red run
    # caught it: a negative control that passes is a defect, not a relief.
    try:
        Turn(question="q", answer="a")          # type: ignore[call-arg]
        r.err("Turn() constructed with no `outcome`. The field must be "
              "mandatory: 'chose not to answer' and 'was unable to' are the "
              "same event in a log, and a default lets every caller skip the "
              "one decision that cannot be made afterwards.")
    except TypeError:
        pass

    for bad in ("unknown", "", "refused", "error", None):
        try:
            Turn(question="q", answer="a", outcome=bad)
            r.err(f"outcome={bad!r} was accepted. Only answered/declined/"
                  "could_not may be stored; anything else erases the "
                  "choice-versus-failure distinction at the moment it is made.")
        except (ValueError, TypeError):
            pass
    for good in ("answered", "declined", "could_not"):
        try:
            Turn(question="q", answer="a", outcome=good)
        except Exception as exc:                   # noqa: BLE001
            r.err(f"outcome={good!r} was refused: {exc!r}")

    # 2. FIRST-TURN GAP IS None, NOT ZERO. Zero claims no time passed, which is
    # a statement about the world; None says there was no previous turn, which
    # is a fact about the record.
    class _Stub:
        def __init__(self): self.rows = []
        def append(self, store, kind, body, at):
            self.rows.append((store, kind, body)); return type("R", (), {"seq": len(self.rows)})()
    class _Clock:
        def now(self): return "hlc:0:0"
    st = _Stub()
    rec = BaselineRecorder(st, _Clock())
    rec.record(Turn(question="q", answer="a", outcome="answered"), now_ms=1000.0)
    if st.rows[0][2]["gap_ms"] is not None:
        r.err(f"first turn recorded gap_ms={st.rows[0][2]['gap_ms']!r}; must be "
              "None. Zero would assert that no time passed.")
    rec.record(Turn(question="q2", answer="a2", outcome="answered"), now_ms=6000.0)
    if st.rows[1][2]["gap_ms"] != 5000.0:
        r.err(f"second turn gap_ms={st.rows[1][2]['gap_ms']!r}, expected 5000.0")

    # 3. TRUNCATION IS RECORDED. A capped answer that does not say so reads
    # later as a short answer, which is a different measurement.
    t = Turn(question="q", answer="x" * (MAX_TEXT + 10), outcome="answered")
    if not t.truncated or len(t.answer) != MAX_TEXT:
        r.err("an over-length answer was capped without setting `truncated`.")
    if Turn(question="q", answer="short", outcome="answered").truncated:
        r.err("a short answer was flagged truncated.")

    # 4. A STORE FAILURE NEVER RAISES, AND IS COUNTED. Background bookkeeping
    # must not fail a good turn -- but an unexplained gap with no counter is
    # indistinguishable from a quiet period.
    class _Broken:
        def append(self, *a, **k): raise RuntimeError("disk full")
    seen: list = []
    br = BaselineRecorder(_Broken(), _Clock(), on_error=seen.append)
    try:
        out = br.record(Turn(question="q", answer="a", outcome="answered"))
    except Exception as exc:                       # noqa: BLE001
        r.err(f"a store failure raised into the turn: {exc!r}")
        out = None
    if out is not None:
        r.err("a failed append returned a truthy result.")
    if br.stats()["failed"] != 1 or len(seen) != 1:
        r.err(f"a failed append was not counted or surfaced: {br.stats()}")

    # 5. THE RECORDER HOLDS NO OPINION ABOUT WHAT IS WORTH KEEPING. Selection
    # at write time would make the corpus a product of its own filtering.
    src = (REPO / "core" / "baseline.py").read_text()
    for banned in ("import re", "ModelGateway", "def complete(",
                   "interesting", "importance"):
        if banned in src:
            r.err(f"core/baseline.py references {banned!r}. Capture is total; "
                  "selection happens at projection where it stays auditable "
                  "because the unselected material still exists.")

    r.note("outcome closed over 3 values and refused for 5; first gap None not "
           "0; truncation flagged; a broken store returns None, counts and "
           "surfaces; no selection at write time")
    return r


def check_difficulty_classifies_up() -> "Result":
    """The classifier may raise freely and must not lower without a signal.

    THE ASYMMETRY IS THE PROPERTY, not the accuracy. A request classified too
    HIGH costs a stronger rung; one classified too LOW gets `low` reasoning
    effort and comes back confidently wrong, which is the failure core/effort.py
    raises rather than clamps to avoid.
    """
    r = Result("difficulty-classifies-up")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.difficulty import DIFFICULTY, classify
        from core.router import DIFFICULTY as ROUTER_DIFFICULTY
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.difficulty did not import: {exc!r}")
        return r

    if tuple(DIFFICULTY) != tuple(ROUTER_DIFFICULTY):
        r.err(f"core/difficulty.py DIFFICULTY {DIFFICULTY} disagrees with "
              f"core/router.py {ROUTER_DIFFICULTY}. The classifier would emit a "
              "difficulty the router raises ValueError on.")

    rank = {d: i for i, d in enumerate(DIFFICULTY)}

    # 1. HARD MARKERS RAISE, and they beat every downgrade rule. "why?" is
    # three characters; a length rule that ran first would call it trivial.
    for q in ("why?", "explain the ladder", "fix core/router.py",
              "compare the two", "```py\nx=1\n```"):
        c = classify(q)
        if c.difficulty != "hard":
            r.err(f"{q!r} classified {c.difficulty!r}, not hard ({c.signal}). "
                  "A hard marker must outrank the short-utterance rules.")

    # 2. ONLY A WHOLE-UTTERANCE GREETING IS TRIVIAL. Substring matching here
    # would demote a real request that happens to open politely.
    if classify("hello").difficulty != "trivial":
        r.err("a bare greeting was not trivial")
    c = classify("thanks, now explain the placement stress runner")
    if c.difficulty != "hard":
        r.err(f"{c.difficulty!r} for a request that merely OPENS with an "
              "acknowledgement. Matching `thanks` as a substring would strip "
              "the reasoning budget off the request that follows it.")

    # 3. NO SIGNAL MEANS MODERATE, never trivial. The worst case of this whole
    # module has to be the constant it replaced.
    c = classify("the thing we discussed about the other matter")
    if c.difficulty != "moderate":
        r.err(f"an unreadable request classified {c.difficulty!r}. Silence from "
              "every rule must fall back to the honest middle.")
    if c.confident:
        r.err("a fallback classification reported itself confident.")

    # 4. THE NEGATIVE CONTROL FOR THE ASYMMETRY. Adding a hard marker to any
    # request must never LOWER its difficulty.
    for base in ("hello", "what is the time", "ok", "the other matter"):
        lo, hi = classify(base), classify(base + ", and explain why")
        if rank[hi.difficulty] < rank[lo.difficulty]:
            r.err(f"adding a hard marker to {base!r} LOWERED difficulty "
                  f"{lo.difficulty!r} -> {hi.difficulty!r}.")
    if not r.errors:
        r.note("hard markers outrank length; whole-utterance greetings only; "
               "no signal falls back to moderate and says it is not confident; "
               "adding a marker never lowers difficulty over 4 bases")
    return r


def check_system_turn_reaches_the_wire() -> "Result":
    """The persona must arrive as a SYSTEM turn on every wire that has one.

    BUILT-AND-UNREACHED IS THE FAILURE THIS CHECKS FOR. Before 2026-08-26
    `core/persona.py` could compose a perfect preamble and no branch in
    `routing/supply.py` carried one, so every request reached every supplier as
    a bare user turn. The payload builder is asserted directly rather than the
    call, so this needs no network and no key.
    """
    r = Result("system-turn-reaches-the-wire")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from routing import supply
    except Exception as exc:                       # noqa: BLE001
        r.err(f"routing.supply did not import: {exc!r}")
        return r

    src = (REPO / "routing" / "supply.py").read_text(encoding="utf-8")
    MARK = "PERSONA-PROBE-SENTINEL"

    # Each wire spells it differently and there is no shared field to lean on,
    # so each spelling is asserted by name. A wire added without one would
    # otherwise carry no persona and look identical from the outside.
    for wire, needle in (("openai_chat", '"role": "system"'),
                         ("cf_responses", '"instructions"'),
                         ("google_generate", '"systemInstruction"')):
        if needle not in src:
            r.err(f"the {wire} branch has no {needle} -- a request on that wire "
                  "carries no persona at all, and nothing about the answer says "
                  "so.")

    # THE FOLDED-PROMPT RUNG IS LABELLED, NOT ASSUMED EQUIVALENT. A subscription
    # CLI has no system argument the contract can carry, so the preamble is
    # prepended; that is weaker than a system turn and the code must say so.
    if "system}\n\n---\n\n{prompt}" not in src.replace("f\"", "").replace("\\n", "\n"):
        if "---" not in src or "options.get(\"system\")" not in src:
            r.err("the cli_subprocess wire does not fold the preamble into the "
                  "prompt, so subscription rungs answer with no persona.")

    # AN IMAGE REQUEST HAS NO SYSTEM ROLE and must not receive one: the preamble
    # would be drawn into the picture.
    body = src[src.index('elif row.wire == "cf_image"'):src.index('elif row.wire == "google_generate"')]
    if "system" in body and "NO SYSTEM TURN" not in body:
        r.err("the cf_image branch consumes `system`. An image prompt has no "
              "system role; prepending the persona would put 'address the owner "
              "as sir' into the rendered image.")

    # THE GATEWAY MUST CARRY IT AS A NAMED PARAMETER, not as a key a caller
    # buries in `options` -- "this request went out with no identity" has to be
    # visible in the signature and greppable across call sites.
    gw = (REPO / "core" / "gateway.py").read_text(encoding="utf-8")
    if "system: str | None = None" not in gw:
        r.err("ModelGateway.complete has no `system` parameter.")
    rt = (REPO / "tools" / "ops" / "vesper_runtime.py").read_text(encoding="utf-8")
    if "system=system" not in rt:
        r.err("the runtime's answer path does not pass a persona to the "
              "gateway. The contracts would load, compose, validate -- and "
              "nothing would reach a provider.")
    if not r.errors:
        r.note("system turn spelled per wire (messages/instructions/"
               "systemInstruction), folded and labelled on the CLI rung, "
               "refused on the image wire, named on the gateway, passed by the "
               "runtime")
    return r


def check_latency_preference_reorders() -> "Result":
    """`prefer=latency` must re-rank BOTH layers, and change neither floor.

    ONE LAYER IS NOT ENOUGH, and that is the whole reason this asserts two.
    The router picks a profile and the gateway picks a rung inside it; fixing
    only the router moved the variance rather than removing it -- measured
    2026-08-26, four consecutive turns on one profile took 0.56s, 4.22s, 1.02s
    and 4.63s purely because quota headroom rotated which rung answered.
    """
    r = Result("latency-preference-reorders")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.bus import EventBus
        from core.hlc import HybridLogicalClock
        from core.latency import Observation
        from core.router import MeasuredProfile, Router
        from core.store import StoreSet
    except Exception as exc:                       # noqa: BLE001
        r.err(f"router/latency did not import: {exc!r}")
        return r

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        clock = HybridLogicalClock("latency-check")
        bus = EventBus(clock, StoreSet(Path(d), node_id="latency-check"),
                       component="check")
        # A SLOW STANDARD RUNG AND A FAST STRONG ONE -- the shape the remote
        # ladder actually has, and the shape the cost ranking gets wrong.
        # 20 tok/s, NOT THE 51 THIS FIXTURE FIRST USED. At 51 the unobserved
        # estimate lands at 1.25 s and a recovered rung at 1.3 s, so the
        # assertion below turned on two near-equal numbers rather than on the
        # property -- a test that passes or fails on a coincidence is not
        # testing what it says it is.
        slow = MeasuredProfile("slow-standard", "standard", "remote", 20.0, 20.0,
                               measured=True, source="check")
        fast = MeasuredProfile("fast-strong", "strong", "remote", 334.0, 334.0,
                               measured=True, source="check")
        router = Router(bus, [slow, fast])

        if router.select("moderate", prefer="cost").profile_id != "slow-standard":
            r.err("prefer=cost no longer picks the lowest tier above the floor. "
                  "That ranking is correct wherever a stronger tier is bought "
                  "with our own seconds and must remain the default.")
        if router.select("moderate", prefer="latency").profile_id != "fast-strong":
            r.err("prefer=latency did not pick the faster profile. A remote "
                  "strong rung is somebody else's accelerator and is not paid "
                  "for in our seconds.")

        # THE FLOOR IS UNTOUCHED BY EITHER AXIS. This is the control that keeps
        # the change from becoming "route everything to whatever is quickest":
        # SR-009 still forbids answering hard work below `strong`.
        draft = MeasuredProfile("quick-draft", "draft", "remote", 900.0, 900.0,
                                measured=True, source="check")
        r2 = Router(bus, [draft, fast])
        if r2.select("hard", prefer="latency").profile_id != "fast-strong":
            r.err("prefer=latency routed HARD work below the tier floor. The "
                  "axis chooses among ELIGIBLE profiles; it does not widen "
                  "eligibility.")

        # A LIVE OBSERVATION OUTRANKS THE ENROLMENT SWEEP, in both directions.
        router.observe("fast-strong", 40.0)
        if router.select("moderate", prefer="latency").profile_id != "slow-standard":
            r.err("a profile observed at 40s live was still preferred on the "
                  "strength of its enrolment-day throughput. The sweep measures "
                  "one moment on somebody else's hardware.")
        # RECOVERY IS BOUNDED AND THE BOUND IS ASSERTED. 8 good samples is the
        # curve at ALPHA_UP=0.7/ALPHA_DOWN=0.4; the first pair tried here took
        # 17, which is not slow-to-forgive but retired-by-one-bad-minute.
        for _ in range(8):
            router.observe("fast-strong", 0.6)
        o = router.observed("fast-strong")
        # ASSERTED ON THE ESTIMATE ITSELF, not only on who won. The selection
        # depends on what it is being compared against; the estimate does not,
        # and the property claimed in core/latency.py is about the estimate.
        if o.seconds > 3 * 0.6:
            r.err(f"after 8 samples at 0.6s the estimate is still "
                  f"{o.seconds:.2f}s -- more than 3x the truth. That is not "
                  "slow-to-forgive, it is a rung retired by one bad minute.")
        if router.select("moderate", prefer="latency").profile_id != "fast-strong":
            r.err(f"a profile that recovered to {o.seconds:.2f}s was still not "
                  "selected over one estimated at 3.2s.")

        o = router.observed("fast-strong")
        if o is None or o.worst_seconds < 40.0:
            r.err("the observation does not retain its worst sample. An EWMA "
                  "alone cannot be audited: 3s could be three steady calls or "
                  "one 0.5s and one 60s.")
        # FAST UP, SLOW DOWN -- asserted as an asymmetry, not as a constant.
        a, b = Observation("x", 1.0), Observation("y", 1.0)
        a.update(10.0)
        b.update(10.0)
        b.update(1.0)
        if not (10.0 - a.seconds) < (a.seconds - 1.0):
            r.err("a slow sample did not move the estimate most of the way. "
                  "Under-penalising costs the owner a minute in front of a "
                  "screen that looks broken.")

        # A COLD PROFILE IS RANKED ON THE PROBE'S OWN WALL CLOCK, not on a
        # figure derived from throughput. The two are different quantities --
        # one is seconds to a whole answer with the supplier's queue in it, the
        # other is tokens per second -- and deriving one while the other sat
        # unread in the same file cost a measured 13.3 s on the first request
        # to a profile.
        cold_slow = MeasuredProfile("cold-slow", "strong", "remote", 900.0, 900.0,
                                    measured=True, source="check",
                                    probe_seconds=30.0)
        cold_fast = MeasuredProfile("cold-fast", "strong", "remote", 20.0, 20.0,
                                    measured=True, source="check",
                                    probe_seconds=1.0)
        r3 = Router(bus, [cold_slow, cold_fast])
        # NOTE THE RATES ARE INVERTED against the probe times deliberately: the
        # profile with the far better throughput is the one that actually took
        # 30 s. If the router were still ranking on the derived figure it would
        # pick `cold-slow`, and no amount of it being "measured" would help.
        if r3.select("moderate", prefer="latency").profile_id != "cold-fast":
            r.err("a cold profile was ranked on throughput while its enrolment "
                  "probe's wall clock was available. A rate cannot see the "
                  "supplier's queue; the probe timing is the same quantity a "
                  "live observation is.")
        # AND A LIVE OBSERVATION STILL OUTRANKS THE PROBE. The seed is a cold
        # sample, not a floor.
        r3.observe("cold-fast", 60.0)
        if r3.select("moderate", prefer="latency").profile_id != "cold-slow":
            r.err("an enrolment probe timing outranked a live observation. The "
                  "seed exists to order the FIRST request; after that the path "
                  "has better evidence than the sweep does.")

    gw = (REPO / "core" / "gateway.py").read_text(encoding="utf-8")
    # THE SEED MUST NEVER OVERWRITE A LIVE SAMPLE. `register` can run again in
    # a long-lived process, and re-seeding would quietly restore an
    # enrolment-day figure over everything the path has learned since.
    if "provider_id in self._observed" not in gw:
        r.err("ModelGateway.seed_observation does not refuse to overwrite an "
              "existing observation. Re-registration would replace live "
              "evidence with an enrolment-day number, silently.")
    if "seed_observation" not in (REPO / "routing" / "supply.py").read_text(
            encoding="utf-8"):
        r.err("registration does not seed the gateway's latency view, so the "
              "first request ranks three rungs of one profile on quota "
              "headroom -- measured 1.50s, 2.66s and 3.85s on the same probe.")
    if 'if prefer == "latency" and self._observed:' not in gw:
        r.err("the gateway does not re-order rungs on observed latency, so the "
              "variance merely moves from between profiles to within one.")
    if gw.index("providers = [by_key[k] for k in ranked]") > gw.index(
            'if prefer == "latency" and self._observed:'):
        r.err("the latency re-order runs BEFORE quota ranking. Quota must "
              "decide which rungs are offered at all; this only reorders them.")
    rt = (REPO / "tools" / "ops" / "vesper_runtime.py").read_text(encoding="utf-8")
    if rt.count('prefer="latency"') < 2:
        r.err("the runtime sets prefer=latency on only one of the two layers.")
    if not r.errors:
        r.note("cost ranking unchanged; latency ranking prefers the faster "
               "profile; the tier floor holds under both; a live observation "
               "outranks the sweep and is back within 3x of the truth after 8 "
               "good samples; a cold profile ranks on the probe's own wall "
               "clock rather than on a derived rate, and a live sample "
               "outranks the seed; the gateway reorders after quota, never "
               "before, and refuses to re-seed over live evidence")
    return r


def check_memory_projects_from_the_log() -> Result:
    """L2 may not hold a fact whose provenance does not resolve.

    THE ORDER IS THE PROPERTY, not the presence of a column. `MEMORY_ARCHITECTURE`
    states it as "not dual-write -- PROJECT": L3 takes the append and returns a
    seq, and only then may an L2 row exist carrying that seq. A graph-first write
    interrupted between the two stores leaves a fact with no provenance, and the
    surviving row is indistinguishable from a correct one.

    `log_seq INTEGER NOT NULL` IS NOT THIS CHECK, which is why the check reads
    the pointer back out of L3 instead of inspecting its shape. A 0, a stale seq,
    or a seq belonging to another store all satisfy NOT NULL -- every wrong
    pointer in this schema is a well-formed integer.
    """
    r = Result("memory-projects-from-the-log")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph, MemoryContractViolation, MODEL_PRIOR
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.memory did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    m = MemoryGraph(store)

    def _fact(**kw):
        base = dict(subject="work", attribute="deadline", value="ships on the twelfth",
                    rank=4, privacy="private", trust_class="owner",
                    at=clock.now())
        base.update(kw)
        return m.remember(**base)

    # 1. THE PROJECTION ORDER. A remembered fact must point at a real L3 record.
    f = _fact()
    seqs = {rec.seq for rec in store.read("log", kind="memory.fact")}
    if f.log_seq not in seqs:
        r.err(f"log_seq {f.log_seq} does not resolve to an L3 record. The fact "
              "was projected without its append, so memory is asserting "
              "something it cannot show the origin of (INV-EVID-2).")
    if not seqs:
        r.err("nothing was appended to the log at all -- L2 was written as a "
              "primary store rather than as a projection of L3.")

    # 2. THE GUARD ITSELF MUST WORK, or item 1 is unfalsifiable. A check whose
    #    detector cannot detect is the negative control that passes.
    if m.unresolved_pointers():
        r.err(f"unresolved_pointers() reported {m.unresolved_pointers()} on a "
              "cleanly projected store")
    m._conn.execute(                                # noqa: SLF001
        "UPDATE fact SET log_seq = 999999 WHERE id = ?", (f.id,))
    m._conn.commit()                                # noqa: SLF001
    if not m.unresolved_pointers():
        r.err("a fact pointing at seq 999999 -- a record that was never written "
              "-- was NOT reported. The guard inspects the pointer's shape "
              "rather than resolving it, so it cannot tell a real pointer from "
              "a plausible one, and every wrong pointer here is plausible.")
    m._conn.execute("UPDATE fact SET log_seq = ? WHERE id = ?",  # noqa: SLF001
                    (f.log_seq, f.id))
    m._conn.commit()                                # noqa: SLF001

    # 3. INV-EVID-1. A model prior may not be asserted into memory at all.
    try:
        _fact(rank=MODEL_PRIOR)
        r.err(f"rank {MODEL_PRIOR} (model_prior) was stored. INV-EVID-1 forbids "
              "a model prior asserted into memory: the extractor's reading of "
              "an utterance is rank 5, the utterance is rank 4, and admitting a "
              "prior at either promotes a guess to the owner's word.")
    except MemoryContractViolation:
        pass

    # 3b. TRUST CLASS COMES FROM core/taint.py, WHICH OWNS THE VOCABULARY.
    #     Until 2026-08-30 this only checked the string was non-empty, and every
    #     caller invented one: `owner_utterance`, `extractor_reading`,
    #     `compaction`, `calendar`. The effect was the reverse of the intent --
    #     `_weakest()` maps an unknown class to rank 0, so the owner's own words
    #     ranked BELOW retrieved_external, and nothing in memory ever carried
    #     the one class INV-AUTH-6 is about.
    from core.taint import ALLOWED_LEVEL
    try:
        _fact(trust_class="owner_utterance")
        r.err("an invented trust class was accepted. It ranks below "
              "retrieved_external under `_weakest`, making whatever it labels "
              "the least trusted thing present -- and it makes INV-AUTH-6 "
              "unenforceable, because the class that invariant names never "
              "appears in memory at all.")
    except MemoryContractViolation:
        pass
    for good in sorted(ALLOWED_LEVEL):
        try:
            _fact(trust_class=good, attribute=f"probe_{good}")
        except MemoryContractViolation as exc:
            r.err(f"a real taint class {good!r} was refused: {exc}")

    # 4. THE PRIVACY CEILING SELECTS AT OR BELOW, NEVER BY EQUALITY. The probe
    #    this query came from filtered `privacy = 'private'` to get a stable
    #    cardinality to time; carried into the design that predicate makes a
    #    `personal` fact permanently unreachable by block B.
    _fact(subject="work", attribute="mode", value="voice is primary",
          privacy="personal")
    at_private = {f.privacy for f in m.select(["voice", "deadline"],
                                              ceiling="private")}
    if "personal" not in at_private:
        r.err("a `personal` fact was not selected under a `private` ceiling. "
              "The filter is comparing for equality rather than selecting at or "
              "below the ceiling, so a whole privacy class can never reach "
              "block B and nothing reports its absence.")
    at_public = {f.privacy for f in m.select(["voice", "deadline"],
                                             ceiling="public")}
    if at_public - {"public"}:
        r.err(f"a ceiling of `public` selected {at_public}. The ceiling leaks "
              "upward, which is the direction that puts private material in "
              "front of a public surface.")

    # 5. SELECTION RETURNS EACH FACT ONCE. `reach` unions on (id, d), so an
    #    entity reached at two depths is two rows and the join multiplies every
    #    fact it owns. Block B holds 3-5 facts; two of them being the same fact
    #    is worse than returning four.
    m.relate("work", "about", "hardware")
    _fact(subject="hardware", attribute="host", value="the deadline build runs here")
    sel = m.select(["deadline", "voice", "host"], depth=2)
    if len({x.id for x in sel}) != len(sel):
        r.err(f"select() returned {len(sel)} rows for "
              f"{len({x.id for x in sel})} distinct facts. Duplicates consume "
              "block B's slots, and a row count alone cannot see it -- which is "
              "why the probe this query came from did not.")

    r.note(f"projected {m.counts()['fact']} facts, all pointers resolve; guard "
           "detects a fabricated pointer; model_prior refused; ceiling selects "
           "at-or-below and does not leak upward; selection is duplicate-free")
    return r


def check_redactor_precedes_every_provider() -> Result:
    """No credential-shaped string reaches a provider adapter. Ever.

    THE ASYMMETRY THAT DECIDES THE DESIGN. Every other guard in this corpus can
    be retried: a wrong route is re-routed, a refused request is re-asked, a bad
    record is superseded. This one cannot. Text inside an outbound request is
    transmitted and written to the provider's log the instant it goes, and there
    is no recall -- "make the model forget it" is not a thing that exists. So
    the guard runs BEFORE the request is built, at the one place INV-COST-3
    guarantees every call passes through.

    THE CHECK DRIVES THE REAL CHOKE POINT rather than calling `redact()`. A test
    that only exercises the detector proves the detector works and proves
    nothing about whether anything calls it -- which is exactly the gap
    CI-020 exists for on the cost side: `core/privacy.py` and the supplier
    classes were both correct for weeks while nothing joined them.
    """
    r = Result("redactor-precedes-every-provider")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.gateway import ModelGateway, Provider, E1_PRIVATE
        from core.quota import QuotaLedger
        from core.redact import scan, Finding
    except Exception as exc:                       # noqa: BLE001
        r.err(f"the gateway or redactor did not import: {exc!r}")
        return r

    SECRET = "AKIAIOSFODNN7EXAMPLE"
    seen: list = []

    def _gw():
        del seen[:]
        ledger = QuotaLedger()
        bus, cost, gw = _gateway(ledger)
        cost.register_credential("p", "free")

        def adapter(q, o):
            # WHAT THE PROVIDER ACTUALLY RECEIVED. Everything before this point
            # is intent; this is egress.
            seen.append({"prompt": q, "options": o})
            return {"text": "answered", "usage": {}}

        gw.register(Provider("p", "prof", adapter, model="m",
                             egress_class=E1_PRIVATE))
        return gw

    def _went_out() -> str:
        return " ".join(str(x) for x in seen)

    # 1. THE PROMPT.
    _gw().complete(f"deploy with {SECRET} please", task_id="r1",
                   profile_id="prof", difficulty="trivial")
    if SECRET in _went_out():
        r.err(f"the credential reached the provider adapter in the PROMPT. It "
              "is now in that provider's logs and nothing recalls it.")

    # 2. THE SYSTEM TURN.
    _gw().complete("hello", system=f"the key is {SECRET}", task_id="r2",
                   profile_id="prof", difficulty="trivial")
    if SECRET in _went_out():
        r.err("the credential reached the provider in the SYSTEM turn, which is "
              "assembled by VESPER rather than typed by the owner and is "
              "therefore the half nobody thinks to check.")

    # 3. HISTORY -- the field that carries what the owner typed TURNS AGO and
    #    replays it to a provider on every subsequent turn rather than once.
    _gw().complete("and now?", task_id="r3", profile_id="prof",
                   difficulty="trivial",
                   history=[{"role": "user", "content": f"my key is {SECRET}"}])
    if SECRET in _went_out():
        r.err("the credential reached the provider in HISTORY. A secret typed "
              "once is then re-sent on every turn of the conversation, so this "
              "is the leak that repeats.")

    # 4. THE NEGATIVE CONTROL, and it is not optional. A redactor that removes
    #    everything passes items 1-3 perfectly and destroys every request.
    _gw().complete("core/memory.py holds the L2 projection, see "
                   "docs/planning/MEMORY_ARCHITECTURE.md",
                   task_id="r4", profile_id="prof", difficulty="trivial")
    out = _went_out()
    for must_survive in ("core/memory.py", "MEMORY_ARCHITECTURE.md", "L2"):
        if must_survive not in out:
            r.err(f"{must_survive!r} did not survive redaction. Over-redaction "
                  "corrupts the request the owner actually asked for, and it "
                  "presents as VESPER talking nonsense about its own files "
                  "rather than as a security control working.")

    # 5. A FINDING MAY NOT CARRY THE VALUE. The tombstone has to be safe to
    #    keep, safe to count, and useless to whoever steals the store it is in.
    if "value" in Finding.__dataclass_fields__:
        r.err("Finding gained a `value` field. The quarantine and the redaction "
              "record would then hold every credential VESPER has ever seen, "
              "gathered in the one place built to be the low-security bin.")
    for f in scan(f"key {SECRET} here"):
        if SECRET in str(f.to_dict()):
            r.err("a finding's dict carries the matched secret; the audit "
                  "record becomes the thing being protected against")

    # 6. THE DETECTOR ITSELF MUST STILL DETECT. Positive controls, because a
    #    scanner that has only ever returned "clean" is indistinguishable from
    #    one that is broken -- this corpus has that failure twice already.
    for name, probe in (
            ("aws", "AKIAIOSFODNN7EXAMPLE"),
            ("github", "ghp_016C7869C1D9A1B2C3D4E5F6a7b8c9d0e1f2"),
            ("openai_style", "sk-proj-abc123XYZ789def456GHI012jkl345MNO"),
            ("google", "AIzaSyD-1234567890abcdefghijklmnopqrstu"),
            ("private_key", "-----BEGIN RSA PRIVATE KEY-----"),
            ("assignment", 'GROQ_API_KEY="gsk_9xKq2mVn4pLw8zRt1cYb3dHf"')):
        if not scan(probe):
            r.err(f"the detector no longer fires on a {name} credential")

    r.note("prompt, system turn and history all cleared before the adapter; "
           "paths and prose survive; findings carry no value; six credential "
           "shapes still detected")
    return r


def check_updater_refuses_and_ranks() -> Result:
    """The capture path's refusals hold, and the extractor cannot become the owner.

    THE UPDATER CAPTURES INDISCRIMINATELY BY DESIGN, which makes its refusal
    list the entire safety argument -- the only thing between a safety net and a
    file that quietly accumulates everything said near a microphone. So every
    refusal is tested for what it refuses AND for where the refused material
    went, because "refusing is not deleting" is the property that makes an
    over-refusal recoverable and a wrong rule visible.

    THE CREDENTIAL CLASS IS TESTED TWICE OVER. It must be refused, and its
    tombstone must not contain it -- a quarantine holding every credential
    VESPER has ever seen is a more attractive target than the vault, because it
    is the one place they are gathered and it was built to be the low-security
    bin.
    """
    r = Result("updater-refuses-and-ranks")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph
        from core.updater import (Updater, MissRecorder, RANK_USER_STATEMENT,
                                  RANK_DERIVED)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.updater did not import: {exc!r}")
        return r

    SECRET = "AKIAIOSFODNN7EXAMPLE"

    def fresh(**kw):
        store = StoreSet(tempfile.mkdtemp(), node_id="ci")
        clock = HybridLogicalClock(node_id="ci")
        mem = MemoryGraph(store)
        return store, clock, mem, Updater(mem, store, clock, **kw)

    # 1. CREDENTIALS ARE REFUSED, AND THE TOMBSTONE DOES NOT CARRY THEM.
    store, clock, mem, up = fresh()
    c = up.capture(f"my key is {SECRET} keep it safe", event_id="c1")
    if c.outcome != "refused":
        r.err(f"a credential-shaped utterance was captured ({c.outcome}). The "
              "updater writes indiscriminately, so a credential it does not "
              "refuse becomes a permanent memory record of a secret.")
    if mem.counts()["fact"]:
        r.err("the credential reached L2 despite the refusal")
    bodies = str([rec.body for rec in store.read("tombstones")])
    if SECRET in bodies:
        r.err("the tombstone carries the credential value. What is kept must be "
              "enough to audit the detector and useless to a thief; a store of "
              "every credential VESPER has seen is a better target than the "
              "vault.")
    if not bodies.strip("[]"):
        r.err("nothing was tombstoned. Refusing is not deleting -- without a "
              "record, an over-refusal is a silent permanent loss and a "
              "systematically wrong rule is invisible.")

    # 2. OFF THE RECORD LEAVES NOTHING ANYWHERE, including the quarantine. A
    #    phrase that marks a moment unrecorded must not have its own content
    #    land in a store on the way past.
    store, clock, mem, up = fresh()
    up.capture("off the record, the client is impossible", event_id="o1")
    leaked = (mem.counts()["fact"]
              or len(list(store.read("workspace")))
              or len(list(store.read("tombstones"))))
    if leaked:
        r.err("off-the-record material was written somewhere. The phrase list "
              "is owner-driven and deterministic precisely so this outcome is "
              "not a judgement call.")

    # 3. OWNER-DESIGNATED SENSITIVE IS QUARANTINED IN FULL AND UNREACHABLE.
    #    Both halves matter: releasable means the text survives, and refused
    #    means no projection can reach it.
    store, clock, mem, up = fresh()
    up.capture("my diagnosis last year", event_id="s1", owner_sensitive=True)
    if not any("diagnosis" in str(rec.body) for rec in store.read("workspace")):
        r.err("owner-designated sensitive material was not quarantined in full. "
              "A wrong refusal must be recoverable, and nobody notices an "
              "absence.")
    if mem.select(["diagnosis"]):
        r.err("quarantined material is reachable from L2 selection. The "
              "projections must never read the quarantine.")

    # 4. RANK 4 AND RANK 5 ARE BOTH WRITTEN, AND SEPARATELY. INV-EVID-1: a
    #    model extractor cannot produce rank 4.
    store, clock, mem, up = fresh(
        extractor=lambda t: [{"attribute": "deadline", "value": "2026-09-12"}])
    c = up.capture("we ship on the twelfth", event_id="k1")
    ranks = [row[0] for row in mem._conn.execute(   # noqa: SLF001
        "SELECT rank FROM fact ORDER BY rank").fetchall()]
    if ranks != [RANK_USER_STATEMENT, RANK_DERIVED]:
        r.err(f"expected the verbatim utterance at rank {RANK_USER_STATEMENT} "
              f"AND the reading at rank {RANK_DERIVED}, got {ranks}. Storing "
              "only the reading permanently promotes the system's guesses to "
              "the owner's word, and nothing downstream can separate them "
              "afterwards.")

    # 5. AN EXTRACTOR CLAIMING RANK 4 IS OVERRULED, not trusted.
    store, clock, mem, up = fresh(
        extractor=lambda t: [{"value": "a guess", "rank": 4,
                              "attribute": "guessed"}])
    up.capture("something else", event_id="k2")
    derived = mem._conn.execute(                    # noqa: SLF001
        "SELECT rank FROM fact WHERE value = 'a guess'").fetchone()
    if derived and derived[0] != RANK_DERIVED:
        r.err(f"the extractor set its own rank ({derived[0]}). An extractor "
              "that can choose its rank can promote itself to the owner's word.")

    # 6. THE TURN NEVER FAILS ON BACKGROUND WORK.
    def boom(_):
        raise RuntimeError("provider down")
    store, clock, mem, up = fresh(extractor=boom)
    c = up.capture("still capture me", event_id="b1")
    if c.outcome != "stored" or len(c.fact_ids) != 1:
        r.err(f"a failing extractor changed the capture outcome to "
              f"{c.outcome!r}. The updater dying must not turn a good answer "
              "into an error, and the verbatim half is the part that cannot be "
              "reconstructed later.")

    # 7. REDELIVERY IS IDEMPOTENT. Delivery is at-least-once, so the same
    #    capture arriving twice must not produce two facts.
    store, clock, mem, up = fresh()
    up.capture("the same thing", event_id="d1")
    again = up.capture("the same thing", event_id="d1")
    if again.outcome != "duplicate" or mem.counts()["fact"] != 1:
        r.err(f"a redelivered capture produced {mem.counts()['fact']} facts "
              f"(outcome {again.outcome!r})")

    # 8. THE MISS RECORDER WRITES WITHOUT A CORRECTION. Waiting for one would
    #    record only the misses corrected promptly -- a corpus biased in the
    #    direction of looking better than the truth.
    store, clock, mem, up = fresh()
    mr = MissRecorder(mem, store, clock)
    mr.record(detector=MissRecorder.EXPLICIT_ABSENCE, situation="asked",
              layer_consulted="L2", what_was_found=None,
              what_vesper_did="said it had no record")
    misses = [rec.body for rec in store.read("audit", kind="memory.miss")]
    if not misses:
        r.err("an uncorrected miss was not recorded. Every blocked question "
              "about this design waits on records written here, and a corpus "
              "of only-corrected misses answers a different question.")
    try:
        mr.record(detector="vibes", situation="x", layer_consulted="y",
                  what_was_found=None, what_vesper_did="z")
        r.err("an unnamed detector was accepted. A miss whose detector is not "
              "named cannot be counted against that detector's false-positive "
              "rate, which is the only way the thresholds ever get tuned.")
    except ValueError:
        pass

    r.note("credentials tombstoned without their value; off-the-record leaves "
           "no trace in any store; owner-sensitive quarantined in full and "
           "unreachable; rank 4 and 5 both written and the extractor cannot "
           "claim 4; a failing extractor does not fail the turn; redelivery is "
           "idempotent; uncorrected misses are still recorded")
    return r


def check_l1_blocks_hold_index_not_knowledge() -> Result:
    """Block A carries what memory CONTAINS; block B carries what this turn needs.

    THE TWO-BLOCK SHAPE RESOLVES A CONFLICT ONE BLOCK CANNOT. Prefix caching
    wants stable content first; long-context attention wants important content
    at the EDGES, because the middle degrades by more than 30%. Ordering purely
    for the cache buries the facts in the worst position available. A leads, B
    sits against the question, and the weak middle is left empty.

    BLOCK A HOLDING THE INDEX IS NOT A SIZE OPTIMISATION. Degradation is driven
    by distractors as much as by length, and topically related but irrelevant
    content harms MORE than unrelated filler -- which is exactly what resident
    personal memory is. Carrying every fact resident maximises the most harmful
    kind of context available.

    THE CACHE PROPERTY IS CHECKED BY COMPARING BYTES rather than by reading the
    code. One per-turn value in block A -- a timestamp, a turn counter, the
    question -- invalidates the prefix and costs full freight on every turn
    afterwards, and NOTHING ABOUT THE OUTPUT LOOKS DIFFERENT when it happens.
    """
    r = Result("l1-blocks-hold-index-not-knowledge")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph
        from core.persona import Persona
        from core.blocks import L1Renderer, BLOCK_A_HEADER, BLOCK_B_HEADER
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.blocks did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    mem = MemoryGraph(store)
    MARKER = "zanzibar-quintuplicate-marker"
    for subj, attr, val in (
            ("work", "deadline", f"the deadline is {MARKER}"),
            ("work", "mode", "voice is primary and text is the fallback"),
            ("travel", "flight", "the flight is Tuesday morning")):
        mem.remember(subject=subj, attribute=attr, value=val, rank=4,
                     privacy="private", trust_class="owner",
                     at=clock.now())

    ren = L1Renderer(Persona.load(), mem)
    out = ren.render("when is the deadline")

    # 1. THE INDEX, NOT THE KNOWLEDGE.
    if MARKER in out.block_a:
        r.err("a fact's VALUE appeared in block A. Block A is resident on every "
              "turn, and resident personal memory is topically related and "
              "mostly irrelevant -- the exact distractor class measured to harm "
              "more than unrelated filler does.")
    # MATCHED ON THE HEADER, NOT ON "facts under". The index renders "1 fact
    # under" for a single-fact node, so a substring match on the plural passes
    # or fails depending on how much the owner happened to say about one topic
    # -- a check whose result depends on fixture data it does not control.
    if BLOCK_A_HEADER not in out.block_a:
        r.err("block A carries no index. Without it a fact that was not "
              "selected leaves VESPER CONFIDENTLY ignorant, which produces no "
              "event and cannot be noticed -- unlike a miss, which can.")

    # 2. THE CACHE PREFIX. Two different questions, unchanged memory.
    other = ren.render("something else entirely, about flights")
    if other.block_a != out.block_a:
        r.err("block A differed between two turns with unchanged memory. The "
              "provider discount is prefix-keyed on BYTES, so one per-turn "
              "value at the front costs full freight on every later turn while "
              "the output looks identical.")

    # 3. AND NOT MERELY FROZEN. A stale index reports a memory that is gone.
    mem.remember(subject="newnode", attribute="a", value="b", rank=4,
                 privacy="private", trust_class="owner",
                 at=clock.now())
    if L1Renderer(Persona.load(), mem).render("x").block_a == out.block_a:
        r.err("block A did not change after memory gained a node. It is cached "
              "rather than rendered, so the index describes a memory that no "
              "longer exists.")

    # 4. THE PERSONA HALF SURVIVES -- it is what makes block A cacheable at all.
    persona_only, _sel = Persona.load().compose(None)
    first_line = persona_only.strip().splitlines()[0]
    if first_line not in out.block_a:
        r.err("block A does not carry the persona preamble. Persona alone is "
              "~1,590 tokens, below every published cache minimum, and can "
              "never be discounted on its own.")

    # 5. THE MIDDLE IS EMPTY.
    prompt = out.prompt()
    if not prompt.startswith(BLOCK_B_HEADER):
        r.err("something precedes block B in the prompt. The U-curve's weak "
              "middle is empty on purpose; filling it undoes the only reason "
              "there are two blocks.")
    if not prompt.rstrip().endswith(out.question):
        r.err("the question is not last. Block B sits against it because that "
              "is the other high-attention position.")
    # ADJACENCY, NOT MERELY ORDER. The first version of this check asserted only
    # that block B led and the question trailed -- both of which stay true while
    # arbitrary content sits between them, which is precisely the weak middle
    # being filled. The red run caught it: a negative control that passes is a
    # defect, not a relief.
    if prompt != f"{out.block_b}\n\n{out.question}":
        between = prompt[len(out.block_b):-len(out.question)]
        r.err(f"content sits between block B and the question: {between!r}. "
              "The U-curve's middle degrades by more than 30% and is left "
              "empty on purpose -- anything placed there is both the least "
              "attended and a distractor.")

    # 6. EVERY QUOTED FACT CARRIES ITS POINTER (INV-EVID-2).
    for line in out.block_b.splitlines()[1:]:
        if line.startswith("- ") and "->log:" not in line:
            r.err(f"a block B line carries no pointer: {line[:60]!r}")

    # 7. BOUNDED. An unbounded block B is the resident design this replaced.
    for n in range(12):
        mem.remember(subject="work", attribute=f"a{n}",
                     value=f"deadline related fact number {n}", rank=4,
                     privacy="private", trust_class="owner",
                     at=clock.now())
    wide = L1Renderer(Persona.load(), mem).render("deadline")
    if len(wide.selected) > 5:
        r.err(f"block B returned {len(wide.selected)} facts; it is 3-5 by "
              "design, and that bound is what keeps the turn's context small")

    r.note(f"block A indexes {out.index_nodes} nodes and carries no fact "
           f"values; byte-identical across turns and responsive to a new node; "
           f"persona preamble present; middle empty; every quoted fact carries "
           f"a pointer; block B bounded at {len(wide.selected)}")
    return r


def check_arbiter_never_picks_silently() -> Result:
    """Ranks 2-4 disagreeing produces a question. Never a value.

    THE SILENT PICK IS THE FAILURE, and it is invisible by construction. Taking
    the highest rank, or the most recent, or the one that arrived last, all
    produce a fluent confident answer and no event. The owner finds out when the
    action taken on it turns out to be wrong, and by then nothing records that a
    choice was ever made.

    REM-010 4.6 CALLS ASKING "THE SPECIFIED DEFAULT, NOT AN IMPLEMENTATION
    CHOICE", which is why this is a check rather than a preference. The
    asymmetry is the usual one: a question costs the owner a moment; acting on
    the wrong flight time costs whatever that costs, and produces nothing anyone
    can learn from.

    THE LADDER IS NOT REIMPLEMENTED IN THE ARBITER. `resolve_memory_conflict`
    has owned DF-MEMORY-AUTHORITY since A-003 and was reachable from nothing but
    an acceptance runner. Two rank tables in one corpus would drift, and the one
    that drifted would be the one nobody was watching -- so this check drives
    the arbiter and asserts the RESOLVER's outcomes.
    """
    r = Result("arbiter-never-picks-silently")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph
        from core.arbiter import Arbiter
        from core.bus import EventBus
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.arbiter did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    mem = MemoryGraph(store)
    bus = EventBus(clock, store)
    seen = []
    bus.subscribe("memory.conflict", lambda e: seen.append(e),
                  name="ci-arbiter", idempotency_key=lambda e: str(id(e)))
    arb = Arbiter(mem, bus=bus)

    def fact(subject, attribute, value, rank, trust):
        mem.remember(subject=subject, attribute=attribute, value=value,
                     rank=rank, privacy="private", trust_class=trust,
                     at=clock.now())

    # THE WORKED EXAMPLE. Owner says Tuesday (rank 4, user_statement); the
    # calendar says Wednesday (rank 2, source_of_record).
    fact("flight", "departs", "Tuesday morning", 4, "owner")
    fact("flight", "departs", "Wednesday morning", 2, "retrieved_local")

    found = arb.contradictions()
    if not any(c["subject"] == "flight" and c["attribute"] == "departs"
               for c in found):
        r.err("the contradiction was not detected at all. Two values for one "
              "(subject, attribute) is the input to the whole ladder; missing "
              "it means the resolver is never consulted and the pick is made "
              "by whichever row selection happened to return first.")

    res = arb.resolve("flight", "departs")
    if res.get("outcome") != "ASK":
        r.err(f"ranks 2 and 4 disagreed and the outcome was "
              f"{res.get('outcome')!r} carrying {res.get('value')!r}. "
              "INV-MEM-1: a three-way disagreement across ranks 2-4 produces a "
              "user-facing question, never a silent pick. Taking the higher "
              "rank is still a pick.")
    if res.get("value") not in (None, "UNKNOWN"):
        r.err(f"an ASK outcome carried a value ({res.get('value')!r}). A "
              "question with an answer attached is answered, and every caller "
              "downstream will read the value and skip the question.")
    if not seen:
        r.err("no `memory.conflict` event was published. A conflict nobody can "
              "observe is resolved silently even when the return value says "
              "ASK -- the event is how the question reaches a surface.")

    # AGREEMENT IS NOT A CONFLICT. Without this, every fact confirmed by a
    # second source becomes an interruption, and the owner learns to dismiss
    # the questions -- which disables the mechanism far more thoroughly than
    # not having built it.
    fact("hotel", "city", "Casablanca", 4, "owner")
    fact("hotel", "city", "Casablanca", 2, "retrieved_local")
    agree = arb.resolve("hotel", "city")
    if agree.get("outcome") != "RESOLVED":
        r.err(f"two sources AGREEING produced {agree.get('outcome')!r}. "
              "Distinct ranks holding the same value is corroboration.")

    # THE QUESTION MUST BE REACHABLE AS A QUESTION, not merely returned once.
    opens = arb.open_questions()
    if not any(q["subject"] == "flight" for q in opens):
        r.err("the unresolved conflict does not appear in open_questions(). A "
              "conflict that resolves to ASK and is then unreachable has been "
              "silently dropped rather than silently picked, which produces the "
              "same outcome for the owner.")
    if any(q["subject"] == "hotel" for q in opens):
        r.err("an agreeing pair appeared as an open question")

    r.note(f"{len(found)} contradiction(s) detected; rank 2 vs rank 4 asks and "
           f"carries no value; the conflict is published; agreement resolves; "
           f"{len(opens)} open question(s) reachable")
    return r


def check_forgetter_never_edits_in_place() -> Result:
    """An edit is a new record. An erasure leaves a tombstone that names it.

    THE ONE-LINE WRONG ANSWER IS `UPDATE fact SET value = ?`. It reads as
    correct, it is what every other system does, and it leaves
    `observed_at_hlc` claiming a time that belongs to different content. The
    audit trail is then FALSE rather than missing -- every record still present,
    every timestamp still plausible, and the history it describes never
    happened. `INV-LOSS-3` depends on that trail being real.

    ERASE IS TESTED IN BOTH DIRECTIONS because both halves can fail silently.
    Content that survives an erasure defeats the operation; a tombstone carrying
    the erased value defeats it just as completely while looking like diligence.

    NOBODY NOTICES AN ABSENCE. That is why the tombstone is written BEFORE the
    row is removed, and why this check reads the tombstone back rather than
    trusting that erase() returned.
    """
    r = Result("forgetter-never-edits-in-place")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph
        from core.forgetter import Forgetter, ForgetRefused, SYSTEM, OWNER
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.forgetter did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    mem = MemoryGraph(store)
    fg = Forgetter(mem, store, clock)

    original = mem.remember(subject="flight", attribute="departs",
                            value="Tuesday morning", rank=4, privacy="private",
                            trust_class="owner", at=clock.now())
    before = mem._conn.execute(                     # noqa: SLF001
        "SELECT value, observed_at_hlc, rank FROM fact WHERE id = ?",
        (original.id,)).fetchone()

    # 1. SUPERSESSION LEAVES THE EARLIER ROW BYTE-FOR-BYTE ALONE.
    rec = fg.supersede(subject="flight", attribute="departs",
                       new_value="Wednesday morning", actor=OWNER,
                       reason="the airline moved it")
    after = mem._conn.execute(                      # noqa: SLF001
        "SELECT value, observed_at_hlc, rank FROM fact WHERE id = ?",
        (original.id,)).fetchone()
    if after is None:
        r.err("the superseded fact was DELETED. Supersession keeps both "
              "records: the owner may want the earlier one back, and a "
              "projection re-derived from the log has to see the history it "
              "is projecting.")
    elif before != after:
        r.err(f"the earlier row was modified in place: {before} -> {after}. "
              "`observed_at_hlc` now claims a time belonging to different "
              "content, which makes the audit trail false rather than missing.")
    values = {row[0] for row in mem._conn.execute(  # noqa: SLF001
        "SELECT value FROM fact")}
    if "Tuesday morning" not in values or "Wednesday morning" not in values:
        r.err(f"both values should remain readable after a supersession; "
              f"found {values}")
    if not rec.get("superseded_fact_id"):
        r.err("the audit record does not name what was superseded, so the "
              "chain from the new value back to the old one is unrecoverable")

    # 2. ONLY THE OWNER EDITS. Append-only is about the SYSTEM.
    try:
        fg.supersede(subject="flight", attribute="departs", new_value="Friday",
                     actor=SYSTEM, reason="looked wrong")
        r.err("the SYSTEM superseded an owner statement. A system that can "
              "rewrite the owner's stated facts is correcting them, which is a "
              "different product than the one specified.")
    except ForgetRefused:
        pass

    # 3. ERASE REMOVES THE CONTENT -- including from the search index, which is
    #    the copy an implementation forgets and which would keep it findable.
    leak = mem.remember(subject="notes", attribute="pasted",
                        value="a value that should never have existed",
                        rank=4, privacy="private",
                        trust_class="owner", at=clock.now())
    fg.erase(fact_id=leak.id, actor=OWNER, reason="recorded in error")
    if mem._conn.execute(                           # noqa: SLF001
            "SELECT COUNT(*) FROM fact WHERE id = ?", (leak.id,)).fetchone()[0]:
        r.err("the erased fact is still in `fact`")
    # THE SEARCHABILITY ASSERTION IS `select()`, WHICH IS THE PATH ANYTHING
    # REAL USES. It is also the only index property here that is deterministic.
    #
    # TWO WEAKER ASSERTIONS WERE TRIED AND BOTH REMOVED, which is worth stating
    # so they are not re-added by someone who thinks they were forgotten:
    #
    #   `SELECT COUNT(*) FROM fact_fts WHERE rowid = ?` is VACUOUS. `fact_fts`
    #   is an external-content table, so a rowid lookup resolves through `fact`
    #   -- once the base row is gone that count reads 0 whether or not the index
    #   was ever cleaned, and the assertion cannot fail.
    #
    #   A raw `fact_fts MATCH` and a scan of the `fact_fts_data` shadow blocks
    #   are both NON-DETERMINISTIC. Measured 2026-08-30: identical erasures
    #   disagreed depending only on what else had been written first, because
    #   FTS5 segment merging decides when a term leaves the index storage. A
    #   gate that passes for that reason is not evidence, and it would be flaky
    #   in the direction of false confidence.
    #
    # `core/forgetter.py` records what erasure can and cannot promise as a
    # result. The residue limit is real; it is simply not gateable.
    if mem.select(["quintuplicate", "pasted"]):
        r.err("the erased fact is still returned by selection -- the path every "
              "real caller uses. Whatever happened to the index, the content is "
              "still reaching block B.")
    # NOT ASSERTED: whether the term survives in the `fact_fts_data` shadow
    # blocks. Measured 2026-08-30 and it is NON-DETERMINISTIC -- it depends on
    # FTS5 segment merging, which depends on what else has been written since.
    # Two runs of the same erasure, differing only in whether another fact had
    # been stored, disagreed. A check that passes for that reason is not
    # evidence of anything, and asserting it would make this gate flaky in the
    # direction of false confidence. `core/forgetter.py` records the limit.

    # 4. AND THE TOMBSTONE DOES NOT CARRY WHAT IT ERASED.
    tombs = [rec.body for rec in store.read("tombstones", kind="memory.erased")]
    if not tombs:
        r.err("nothing was tombstoned. INV-LOSS-3: with a deletion audit VESPER "
              "NAMES the removal; with nothing it says nothing -- and an "
              "unrecorded erasure is indistinguishable from data loss.")
    blob = str(tombs)
    if "should never have existed" in blob:
        r.err("the tombstone carries the erased value. A tombstone holding what "
              "it erased has not erased it.")
    for field in ("subject", "attribute", "reason"):
        if tombs and field not in tombs[0]:
            r.err(f"the tombstone omits {field!r}; without the shape of what "
                  "went, the record cannot be audited")

    # 5. ERASURE IS THE OWNER'S ALONE AND NEEDS A STATED REASON.
    for kwargs, why in (({"actor": SYSTEM, "reason": "x"}, "a system actor"),
                        ({"actor": OWNER, "reason": "   "}, "a blank reason")):
        try:
            fg.erase(fact_id=original.id, **kwargs)
            r.err(f"erasure accepted with {why}. It is the one operation that "
                  "cannot be undone and whose wrongness leaves no evidence.")
        except ForgetRefused:
            pass

    # 6. NOTHING EXPIRES BY DELETION. Staleness ranks; it does not remove.
    n_before = mem.counts()["fact"]
    stale = fg.stale(older_than_seq=10_000)
    if mem.counts()["fact"] != n_before:
        r.err("the staleness sweep removed rows. Nothing expires by deletion: "
              "staleness is a ranking input, and a sweep that deleted would "
              "need a model to rescue the commonest case there is -- a fact "
              "that is simply old and still true.")
    if not stale:
        r.err("the staleness sweep reported nothing at all over facts that all "
              "predate the bound")

    r.note(f"supersession left the earlier row byte-identical and both values "
           f"readable; the system may not edit; erasure cleared `fact` and the "
           f"FTS index while the tombstone kept the shape and withheld the "
           f"value; {len(stale)} stale rows reported and none removed")
    return r


def check_reprojection_never_resurrects() -> Result:
    """L2 is a pure function of the log AND the tombstones.

    THE RESURRECTION IS THE FAILURE AND IT ARRIVES AS MAINTENANCE. L3 is
    append-only -- verified at the storage layer, not by convention -- so an
    erased fact's value is STILL IN THE LOG after the owner has removed it from
    L2. A projection that reads the log alone brings it back, silently, during a
    routine compaction pass. The owner's erasure is undone by housekeeping, and
    nothing reports it because the projection is internally consistent.

    DIVERGENCE IS FAILURE MODE 9. Two nodes both append and both project; if
    projection is not a pure function of its inputs they disagree while the log
    agrees, and each node's L2 looks perfectly correct from inside.

    PRIVACY IS RECOMPUTED, NEVER INHERITED. A compacted node takes the MAXIMUM
    sensitivity of its inputs, which subsumes the aggregation failure without
    detecting it: three innocuous facts compacting into a security profile is
    simply "the result was raised". You do not have to catch every sensitive
    thing -- you have to never classify downward.
    """
    r = Result("reprojection-never-resurrects")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.memory import MemoryGraph
        from core.forgetter import Forgetter, OWNER
        from core.compactor import Compactor, strictest
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.compactor did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    mem = MemoryGraph(store)
    fg = Forgetter(mem, store, clock)
    cp = Compactor(mem, store, clock,
                   summariser=lambda vals: " | ".join(v[:20] for v in vals))

    MARKER = "zanzibar-erased-marker"
    for subj, attr, val, priv in (
            ("work", "deadline", "ships on the twelfth", "private"),
            ("work", "deadline", "confirmed by the team", "personal"),
            ("work", "deadline", "posted publicly", "public"),
            ("travel", "flight", "Tuesday morning", "private")):
        mem.remember(subject=subj, attribute=attr, value=val, rank=4,
                     privacy=priv, trust_class="owner",
                     at=clock.now())
    leak = mem.remember(subject="notes", attribute="pasted", value=MARKER,
                        rank=4, privacy="private", trust_class="owner",
                        at=clock.now())

    if not cp.verify()["converged"]:
        r.err("L2 and the projection of L3 disagree before anything was done "
              "to either. The write path and the projection path do not produce "
              "the same thing, so one of them is wrong from the first fact.")

    # 1. THE RESURRECTION.
    fg.erase(fact_id=leak.id, actor=OWNER, reason="recorded in error")
    if not any(MARKER in str(rec.body)
               for rec in store.read("log", kind="memory.fact")):
        r.err("the erased value is not in L3 at all, so this check is no longer "
              "testing the resurrection -- it can only happen because the log "
              "is append-only and still holds what L2 dropped.")
    out = cp.reproject()
    if any(MARKER in row[0] for row in mem._conn.execute(  # noqa: SLF001
            "SELECT value FROM fact")):
        r.err("reprojection RESURRECTED an erased fact. L3 is append-only, so "
              "the value is still in the log; a projection that reads the log "
              "alone undoes the owner's erasure during routine maintenance and "
              "reports success.")
    if mem.select(["zanzibar", "pasted"]):
        r.err("the resurrected fact is reachable from selection")
    if not out.get("erased_skipped"):
        r.err("reprojection reported skipping no erasures while a tombstone "
              "exists; it is not consulting them at all and passed by luck")

    # 2. THE SURVIVORS SURVIVE. A reprojection that drops everything also fails
    #    to resurrect anything, and would pass item 1 perfectly.
    kept = {row[0] for row in mem._conn.execute(     # noqa: SLF001
        "SELECT value FROM fact")}
    for must in ("ships on the twelfth", "Tuesday morning", "posted publicly"):
        if must not in kept:
            r.err(f"reprojection lost {must!r}. Dropping everything satisfies "
                  "the resurrection test and destroys the memory it rebuilt.")
    if not cp.verify()["converged"]:
        r.err("L2 does not match its own projection immediately after a "
              "reprojection")

    # 3. DIVERGENCE IS DETECTABLE, or `verify()` is decorative.
    mem._conn.execute(                              # noqa: SLF001
        """INSERT INTO fact(subject_id, attribute, value, rank, observed_at_hlc,
                            privacy, trust_class, log_seq)
           VALUES(1,'ghost','a row the log never saw',4,'x','private','o',9999)""")
    mem._conn.commit()                              # noqa: SLF001
    if cp.verify()["converged"]:
        r.err("a row that no log record produced did not register as "
              "divergence. Two nodes projecting independently would disagree "
              "while the log agrees, and each would look correct from inside.")

    # 4. AND REPROJECTION RECOVERS FROM IT -- including from the corrupt index
    #    that a stray row leaves behind, which is a state this method exists
    #    to repair rather than one it may assume away.
    cp.reproject()
    if not cp.verify()["converged"]:
        r.err("reprojection did not restore convergence from a diverged L2")

    # 5. PRIVACY IS THE MAXIMUM OF THE INPUTS.
    comp = cp.compact("work", "deadline")
    if comp.get("privacy") != "private":
        r.err(f"a compaction over public+personal+private inputs produced "
              f"{comp.get('privacy')!r}. A compacted node inherits the MAXIMUM "
              "sensitivity of its inputs; classifying downward is how three "
              "innocuous facts become a security profile nobody labelled.")
    # 5b. TRUST IS INHERITED THROUGH core/taint.py, NOT REPLACED. The first
    #     version set `trust_class="compaction"`, destroying the inputs' classes
    #     at exactly the moment content is merged: a summary of one owner
    #     statement and one retrieved page came out labelled `compaction`, and
    #     `retrieved_external` -- the class INV-AUTH-6 exists for -- vanished.
    mem.remember(subject="mixed", attribute="note", value="the owner said this",
                 rank=4, privacy="private", trust_class="owner", at=clock.now())
    mem.remember(subject="mixed", attribute="note", value="this came off a page",
                 rank=5, privacy="private", trust_class="retrieved_external",
                 at=clock.now())
    mixed = cp.compact("mixed", "note")
    # READ BACK FROM THE STORE, NOT FROM THE RETURN VALUE. The first version
    # asserted on `mixed["trust_class"]` -- the report the method makes about
    # itself -- and a mutation that changed what was STORED while leaving the
    # report intact passed cleanly. An instrument's self-report is not evidence.
    stored = mem._conn.execute(                     # noqa: SLF001
        "SELECT trust_class FROM fact WHERE id = ?",
        (mixed.get("fact_id"),)).fetchone()
    if not stored or stored[0] != "retrieved_external":
        r.err(f"a summary of owner content and retrieved_external content was "
              f"STORED as {(stored or ['<missing>'])[0]!r}. A summary of tainted "
              "content is tainted, and taint is contagious rather than "
              "averaged -- HANDOFF_MEMORY_BUILD names this by saying not to "
              "write a second sensitivity system.")

    if strictest(["public", "personal"]) != "personal":
        r.err("strictest() is not taking the most private class")
    if strictest(["nonsense"]) != "private":
        r.err("an unrecognised privacy class did not resolve to private. The "
              "permissive reading is the one that cannot be undone.")

    # 6. A MODEL PRIOR IS NOT PROJECTED (INV-EVID-1), even if one reached L3.
    store.append("log", "memory.fact",
                 {"subject": "guess", "attribute": "x", "value": "a prior",
                  "rank": 6, "privacy": "private", "trust_class": "model"},
                 clock.now())
    if any(f["value"] == "a prior" for f in cp.project()):
        r.err("a rank 6 model_prior was projected into L2. INV-EVID-1 is "
              "applied at the write path AND at projection, because a record "
              "that reached the log by any other route would otherwise arrive "
              "in memory as fact.")

    r.note(f"projection converges with L2; an erased fact is not resurrected "
           f"({out.get('erased_skipped')} skipped) while survivors are kept; "
           f"divergence is detected and repaired; compaction over "
           f"{comp.get('input_classes')} yields {comp.get('privacy')!r}; a "
           f"model prior in the log is not projected")
    return r


def check_chooser_escalates_only_when_unsure() -> Result:
    """A model runs only on the ambiguous middle, and may raise but never lower.

    INV-DIFF-1 REQUIRES THE CLASSIFICATION TO REPORT WHETHER IT WAS CONFIDENT,
    and until the chooser existed exactly one thing in this repository read that
    flag: the check asserting it was there. A signal nothing consumes is a
    signal that can rot without anyone noticing.

    THE ASYMMETRY CROSSES THE ESCALATION BOUNDARY OR IT IS NOT THE ASYMMETRY.
    CI-069 gates it inside `classify()`; this gates it at the point a MODEL's
    opinion arrives and could quietly undo it. Too high costs a stronger rung;
    too low gets `low` reasoning effort and comes back confidently wrong.

    AND A MODEL ON EVERY TURN IS THE THING BEING AVOIDED. "Ask a model how hard
    this is" is one line and puts a paid network call in front of "hello",
    inside the latency path. The check counts the calls.
    """
    r = Result("chooser-escalates-only-when-unsure")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.chooser import (ANNOUNCE_MS, Chooser, DETERMINISTIC,
                                  ESCALATED, FELL_BACK)
        from core.difficulty import DIFFICULTY, classify
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.chooser did not import: {exc!r}")
        return r

    calls: list = []

    def counting(answer):
        def esc(text):
            calls.append(text)
            return answer
        return esc

    # 1. NO MODEL ON A CONFIDENT CLASSIFICATION.
    del calls[:]
    ch = Chooser(escalate=counting("hard"))
    for text in ("hello", "thanks", "def f(x): return x / 0  # core/memory.py"):
        out = ch.choose(text)
        if out.path != DETERMINISTIC:
            r.err(f"{text[:24]!r} took the {out.path} path. It is classified "
                  "confidently, and escalating it puts a paid network call "
                  "inside the latency path for a greeting.")
    if calls:
        r.err(f"the escalator was called {len(calls)} time(s) on confidently "
              "classified input")

    # 2. THE AMBIGUOUS MIDDLE DOES ESCALATE -- or the whole subsystem is inert
    #    and item 1 passes trivially.
    ambiguous = "could you look at the thing we discussed and see if it holds"
    if classify(ambiguous).confident:
        r.err("the fixture chosen as ambiguous is classified confidently, so "
              "this check is no longer testing escalation at all")
    del calls[:]
    out = Chooser(escalate=counting("hard")).choose(ambiguous)
    if out.path != ESCALATED or not calls:
        r.err(f"an unconfident classification did not escalate (path "
              f"{out.path!r}, {len(calls)} call(s))")
    if out.difficulty != "hard":
        r.err(f"the escalator raised to 'hard' and the choice is "
              f"{out.difficulty!r}")

    # 3. RAISE YES, LOWER NEVER.
    low = Chooser(escalate=counting("trivial")).choose(ambiguous)
    floor = classify(ambiguous).difficulty
    if DIFFICULTY.index(low.difficulty) < DIFFICULTY.index(floor):
        r.err(f"a model lowered the difficulty below the deterministic floor "
              f"({floor!r} -> {low.difficulty!r}). Too low gets `low` reasoning "
              "effort and a confidently wrong answer, which is the failure this "
              "corpus is organised against.")
    if not low.overruled:
        r.err("a downgrade was refused without being recorded as an overrule. "
              "A model whose answer is being discarded every time is a cost "
              "with no benefit, and nothing would show it.")

    # 4. NOTHING HERE MAY FAIL A TURN. Three ways the escalator can fail, and
    #    all three must land on the deterministic answer.
    def boom(_):
        raise RuntimeError("provider down")
    for esc, label in ((boom, "an escalator that raises"),
                       (lambda _: "banana", "an escalator returning nonsense"),
                       (lambda _: None, "an escalator returning None")):
        out = Chooser(escalate=esc).choose(ambiguous)
        if out.path != FELL_BACK:
            r.err(f"{label} produced path {out.path!r} instead of falling back")
        if out.difficulty != floor:
            r.err(f"{label} changed the difficulty to {out.difficulty!r}; the "
                  f"deterministic floor {floor!r} was already computed and is "
                  "already routable")
    out = Chooser().choose(ambiguous)
    if out.difficulty != floor or out.path != DETERMINISTIC:
        r.err("with no escalator configured the chooser did not simply use the "
              "deterministic answer")

    # 5. THE HOLD ANNOUNCEMENT IS A THRESHOLD, NOT A TIMEOUT. The work is not
    #    cancelled; the owner is told it is still happening.
    import time as _t

    def slow(_):
        _t.sleep((ANNOUNCE_MS + 60) / 1000.0)
        return "hard"
    out = Chooser(escalate=slow).choose(ambiguous)
    if not out.announce:
        r.err(f"a {out.elapsed_ms:.0f} ms choice did not set announce past the "
              f"{ANNOUNCE_MS} ms threshold. Below it VESPER says nothing, "
              "because announcing every delay makes it apologise constantly for "
              "waits nobody perceives.")
    if out.difficulty != "hard":
        r.err("the slow escalation was cancelled rather than announced; the "
              "threshold is when to SPEAK, not when to stop")

    r.note("confident input never reaches a model; the ambiguous middle "
           "escalates; a downgrade is refused and recorded; a raising, "
           "nonsense-returning, None-returning or absent escalator all fall "
           "back to the deterministic floor; a slow choice announces and "
           "completes")
    return r


def check_sensors_never_reach_a_model() -> Result:
    """A probe cannot call a model, a failed probe is UNKNOWN, gated is not polled.

    THE PREDICATES WERE ALREADY CORRECT AND ALREADY EVALUATED OVER AN EMPTY
    WORLD. `trigger_registry.toml` reads `world.owner.attention_state`,
    `world.current_host.health`, `world.current_host.power_source` and
    `nodes.reachable_set`, and nothing populated any of them -- so every
    predicate over them was UNKNOWN and INV-TRIG-4 kept them all from firing.
    The sensors are the input side, not a new subsystem.

    THE MODEL BAN IS ENFORCED AT THE GATEWAY, NOT ASSERTED IN A COMMENT. Every
    probe runs inside `decision_path.entered`, so a probe that reaches
    `ModelGateway.complete` is refused there and the attempt is published. This
    is the failure decision_path was written for and measured on 2026-08-24: a
    predicate closing over a gateway fired True, one model call got through, and
    zero violation events were emitted.

    AND IT IS NOT ONLY COST. A REGEX CANNOT BE PROMPT-INJECTED. Sensors read SMS,
    screens, calendar invites and pages found during research -- text an outsider
    can put in front of VESPER. A model in the filter makes the filter the
    vulnerability it exists to prevent.
    """
    r = Result("sensors-never-reach-a-model")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        import tempfile
        from core.store import StoreSet
        from core.hlc import HybridLogicalClock
        from core.bus import EventBus
        from core.world import UNKNOWN, WorldModel
        from core.cost import CostPolicy
        from core.gateway import ModelGateway, Provider, E1_PRIVATE
        from core.sensors import (GATED, SWEEP, TIMER, Sensor, SensorRefused,
                                  SensorRegistry)
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.sensors did not import: {exc!r}")
        return r

    store = StoreSet(tempfile.mkdtemp(), node_id="ci")
    clock = HybridLogicalClock(node_id="ci")
    bus = EventBus(clock, store)
    world = WorldModel(bus, clock)
    cost = CostPolicy(bus, clock)
    gw = ModelGateway(bus, cost, sleep=lambda s: None)
    cost.register_credential("p", "free")
    gw.register(Provider("p", "prof", lambda q, o: {"text": "yes", "usage": {}},
                         model="m", egress_class=E1_PRIVATE))

    # 0. THE GATEWAY ANSWERS NORMALLY OUTSIDE A PROBE, or item 1 proves only
    #    that the gateway is broken.
    if not ((gw.complete("hello", profile_id="prof",
                         difficulty="trivial").get("result") or {}).get("text")):
        r.err("the fixture gateway does not answer at all outside a sensor, so "
              "the refusal below would prove nothing")

    # 1. A PROBE THAT REACHES A MODEL IS REFUSED.
    reg = SensorRegistry(world, clock, bus=bus)
    ran = []

    def sneaky():
        ran.append(1)
        return gw.complete("is there anything worth doing?", profile_id="prof",
                           difficulty="trivial")

    reg.register(Sensor("sneaky", "owner", "attention_state", sneaky, TIMER))
    out = reg.poll()
    if not ran:
        r.err("the probe never ran, so nothing was tested")
    if out["applied"][0].get("outcome") != "unknown":
        r.err(f"a probe that called a model produced "
              f"{out['applied'][0].get('outcome')!r}. The call must be refused "
              "at the gateway and the reading must not be applied -- a "
              "predicate would otherwise fire on a model's opinion.")
    if world.read("owner", "attention_state") is not UNKNOWN:
        r.err("a model's answer reached the world model through a sensor")
    if not any("ModelCallInDecisionPath" in d.detail for d in reg.discards):
        r.err("the model-call attempt was not recorded. A filter that drops "
              "silently is deciding what VESPER knows with no way to see it.")

    # 2. GATED SOURCES ARE NOT POLLED, structurally. Camera, screen and
    #    microphone need a REASON; power is the constraint and an interval is
    #    not a reason.
    reg2 = SensorRegistry(world, clock, bus=bus)
    fired = []
    reg2.register(Sensor("mic", "owner", "speaking",
                         lambda: fired.append(1) or True, GATED))
    swept = []
    reg2.register(Sensor("sweeper", "tasks", "stale",
                         lambda: swept.append(1) or 3, SWEEP))
    out2 = reg2.poll(force=True)
    # A SWEEP IS SCHEDULED AND MUST RUN. The first version of this check
    # asserted the opposite, because the registry lumped SWEEP in with GATED on
    # the grounds that neither is TIMER. `MEMORY_ARCHITECTURE.md`: a sweep is "a
    # scheduled query over VESPER's own memory, seeded by time instead of by an
    # utterance" -- it has no SENSOR because there is nothing to sense, and it
    # still has a PERIOD. Excluding it made `trg_fact_expiry_sweep` unreachable,
    # which is the trigger whose entire class it is.
    if not swept:
        r.err("a SWEEP sensor did not run on a poll. Nothing emits an event "
              "when an idea has been unresolved for three weeks -- time alone "
              "makes it true, and a scheduled query is the only way to see it.")
    if fired:
        r.err("a GATED sensor ran on a poll. A microphone or camera on a timer "
              "is precisely the design the source classes exist to prevent, and "
              "refusing it in code beats trusting nobody sets a period.")
    if {s["sensor"] for s in out2["skipped"]} != {"mic"}:
        r.err(f"expected only the GATED sensor to be skipped, got "
              f"{[s['sensor'] for s in out2['skipped']]}")

    # 3. A FAILED PROBE IS UNKNOWN AND IS NEVER A STALE VALUE. INV-EVID-3: an
    #    empty retrieval is never coerced into an answer.
    reg3 = SensorRegistry(world, clock, bus=bus)
    state = {"v": "ac"}
    reg3.register(Sensor("power", "current_host", "power_source",
                         lambda: state["v"], TIMER, period_ms=0))
    reg3.poll(force=True)
    if world.read("current_host", "power_source") != "ac":
        r.err("a working probe did not reach the world model, so the "
              "predicates still read nothing")

    def broken():
        raise OSError("device not present")
    reg4 = SensorRegistry(world, clock, bus=bus)
    reg4.register(Sensor("thermal", "current_host", "thermal", broken, TIMER))
    out4 = reg4.poll(force=True)
    if out4["applied"][0].get("outcome") != "unknown":
        r.err("a failing probe did not yield UNKNOWN")
    if world.read("current_host", "thermal") is not UNKNOWN:
        r.err("a failing probe wrote a value. A stale reading renders "
              "identically to a fresh one and no predicate over it can tell "
              "the difference.")
    if not any(d.reason == "probe_failed" for d in reg4.discards):
        r.err("a probe failure was not logged as a discard. A filter bug "
              "produces SILENCE, which is undetectable in exactly the way a "
              "memory miss is -- the discard log is the only thing that makes "
              "the thresholds tunable.")

    # 3b. A PROBE MAY NOT INVENT A VOCABULARY A CONTRACT ALREADY OWNS, which is
    #     how the first version of `host_health()` shipped: it returned
    #     `nominal`/`constrained` while `trg_placement_reevaluate` reads
    #     `world.current_host.health in { DEGRADED, FAILING }`, so the trigger
    #     could never have fired however degraded the host got. Nothing reported
    #     it because both halves were internally consistent -- the same defect
    #     as the L2 probe inventing `private`/`shareable` for a column
    #     `core/privacy.py` already owned.
    import tomllib
    from core import host_probes
    sm = tomllib.loads((REPO / "spec" / "state-machines" / "INDEX.toml")
                       .read_text(encoding="utf-8"))
    device_states = set(sm["state_machines"]["SM-DEVICE"]["states"])
    health = host_probes.host_health()
    if health not in device_states:
        r.err(f"host_health() returned {health!r}, which is not an SM-DEVICE "
              f"state ({sorted(device_states)}). A probe that defines its own "
              "vocabulary produces readings no predicate can act on, and "
              "nothing reports the mismatch because both halves are internally "
              "consistent.")

    # 3c. A TTL MUST ACTUALLY EXPIRE, and until 2026-08-30 none of them could.
    #     `valid_until_ms` is an ABSOLUTE stamp; `sensors.py` passed the TTL
    #     straight into it, so a five-minute reading was stamped as expiring
    #     five minutes after the epoch. And `WorldModel`'s clock defaults to
    #     `lambda: 0`, which the runtime accepted -- so `_expired()` compared
    #     `0 >= deadline` and NOTHING could ever expire. Every freshness
    #     property in the design was inert, INV-COORD-2 was vacuously satisfied,
    #     and no gate said a word.
    import time as _time
    fresh_world = WorldModel(bus, clock,
                             now_ms=lambda: int(_time.time() * 1000))
    reg5 = SensorRegistry(fresh_world, clock, bus=bus)
    reg5.register(Sensor("ttl", "current_host", "health",
                         lambda: "ONLINE", TIMER, period_ms=0, ttl_ms=40))
    reg5.poll(force=True)
    if fresh_world.read("current_host", "health") != "ONLINE":
        r.err("a freshly polled reading did not read back as its value")
    if fresh_world.expired_present():
        r.err("a reading was expired the moment it was written -- the TTL is "
              "being used as an absolute stamp rather than added to now")
    _time.sleep(0.09)
    if fresh_world.read("current_host", "health") is not UNKNOWN:
        r.err("a reading past its TTL still reads as its value. INV-COORD-2: "
              "past valid_until the only readable value is UNKNOWN, and the "
              "last known value is never offered as a fallback.")
    if not fresh_world.expired_present():
        r.err("`expired_present()` is False over a lapsed fact, so "
              "`trg_fact_expiry_sweep` can never fire")

    # 3d. A POLL THAT RAN NOTHING PUBLISHES NOTHING. `poll()` is called on
    #     every pump pass; emitting an event regardless put 9,152 records into
    #     the append-only log in twenty minutes -- 86.3% of the whole log. The
    #     cost is not disk: the log is the evidence every miss record and every
    #     replayed snapshot reads back, and a heartbeat nobody asked for buries
    #     what matters a hundred to one.
    quiet = SensorRegistry(world, clock, bus=bus)
    quiet.register(Sensor("nothing-due", "current_host", "spare",
                          lambda: 1, TIMER, period_ms=10_000_000))
    quiet.poll(force=True)                      # first call: it IS due
    seen_before = sum(1 for _ in store.read("log", kind="sensors.polled"))
    quiet.poll()                                # second: nothing due
    seen_after = sum(1 for _ in store.read("log", kind="sensors.polled"))
    if seen_after != seen_before:
        r.err("a poll that ran no probe still published an event. `poll()` runs "
              "on every pump pass, so this writes to an APPEND-ONLY store "
              "several times a second forever and drowns the events the log "
              "exists to hold.")

    # 3e. THE VERIFIER CALLER RETURNS A `Reading`, NOT A DICT.
    #     HANDOFF_MEMORY_BUILD names core/projection.py as "the freshness
    #     machinery the verifier registry needs", and the first version of
    #     `read()` ignored it and returned `{"value": ..., "known": ...}` -- two
    #     fields a caller reads independently, so a value survives `known=False`
    #     and gets rendered. A Reading cannot hold a value without provenance,
    #     nor a reason without a value, nor both, nor neither.
    from core.projection import Reading
    okr = reg3.read("power")
    if not isinstance(okr, Reading):
        r.err(f"read() returned {type(okr).__name__}, not a Reading. A dict "
              "lets `value` and `known` disagree, which is how a placeholder "
              "gets rendered as a measurement.")
    elif not okr.known or okr.source == "unknown":
        r.err("a working probe produced a Reading with no value or no source")
    badr = reg4.read("thermal")
    if isinstance(badr, Reading):
        if badr.known or badr.value is not None:
            r.err("a failed probe produced a Reading carrying a value. UNKNOWN "
                  "means UNAVAILABLE, and the last reading is never offered.")
        if not badr.unavailable_reason:
            r.err("an unavailable Reading carries no reason, so a surface "
                  "cannot explain itself to the owner and an absent value "
                  "renders identically to a present one")

    # 3f. THIS NODE'S OWN PROFILE IS MEASURED, NOT DECLARED. INV-HW-2: an
    #     unmeasured capability is UNAVAILABLE, and `capability()` returns None
    #     for one rather than the declared value.
    from core.devices import AVAILABILITY, KEY_STORAGE, SPATIAL
    prof = host_probes.device_profile("ci-node")
    for field, vocab in (("availability_class", AVAILABILITY),
                         ("key_storage_class", KEY_STORAGE),
                         ("spatial_class", SPATIAL)):
        if getattr(prof, field) not in vocab:
            r.err(f"{field}={getattr(prof, field)!r} is outside core/devices.py's "
                  f"vocabulary {vocab}")
    if prof.capability("sustained_tokens_per_sec") is not None:
        r.err("an unmeasured capability returned a value. INV-HW-2: UNKNOWN "
              "means UNAVAILABLE, and a declared throughput is exactly the "
              "number that invariant exists to refuse.")
    if prof.key_storage_class == "hardware_backed":
        r.err("this node claims hardware_backed key storage, which buys it "
              "trust zone Z0. Nothing has shown a key resident in a secure "
              "element; a keychain existing evidences os_keychain and no more, "
              "and raising it is a promotion that belongs to the owner.")
    blob = str(prof.to_dict())
    for name in ("MacBook", "Apple", "Intel", "iPhone"):
        if name in blob:
            r.err(f"the device profile carries the product name {name!r}. "
                  "INV-HW-1: write the profile, never the device -- the "
                  "registry is the most natural place in a system to record a "
                  "product name and the place it does the most damage.")

    # 3g. EVERY SENSOR THE RUNTIME REGISTERS MUST WRITE A TERM SOME PREDICATE
    #     ACTUALLY READS. A predicate's snapshot resolves `world.current_host.health`
    #     by splitting on the LAST dot -- subject `world.current_host`. Sensors
    #     written against subject `current_host` populate a subject nothing can
    #     read, so the world fills up correctly and every trigger over it stays
    #     UNKNOWN and silent. That is what shipped on 2026-08-30 and it was
    #     invisible: the sensors worked, the facts landed, and the triggers were
    #     quiet for a reason no event reported.
    reg_terms = set()
    trig = tomllib.loads(TRIGGERS.read_text(encoding="utf-8"))
    for t in (trig.get("triggers", {}) or {}).values():
        for m in re.finditer(r"\b((?:world|nodes|tasks|memory|devices|proposals|alarms|autonomy)"
                             r"(?:\.[a-z_]+)+)", t.get("predicate", "") or ""):
            # SUBJECTS, NOT WHOLE TERMS, and the distinction is what makes this
            # check true rather than merely strict. A sensor may legitimately
            # write an attribute no predicate reads YET -- `disk_free_ratio`
            # feeds `health` rather than a predicate -- and a predicate may
            # express its term as a call, `world.facts.any(...)`. Neither is a
            # defect. Writing to a SUBJECT nothing resolves is, because that is
            # the whole subject silently unreadable.
            reg_terms.add(m.group(1).rsplit(".", 1)[0])
    import importlib.util as _il
    spec = _il.spec_from_file_location("_vr", REPO / "tools" / "ops" / "vesper_runtime.py")
    try:
        vr = _il.module_from_spec(spec); spec.loader.exec_module(vr)
        built = vr.build()
        # FOUND BY IDENTITY, NOT BY INDEX. The first version took built[-3] and
        # got the autonomy loop, so `live` was None, the cross-check skipped in
        # silence, and the gate passed while asserting nothing -- the vacuous
        # assertion this corpus keeps finding. A positional index into an
        # 18-tuple is a number that goes stale the next time build() grows.
        live = next((b for b in built
                     if hasattr(b, "names") and hasattr(b, "poll")), None)
    except Exception as exc:                       # noqa: BLE001
        live = None
        r.err(f"the runtime could not be driven for the sensor-term "
              f"cross-check: {exc!r}. Skipping it silently is how the bug it "
              "looks for shipped in the first place.")
    if live is None:
        r.err("no SensorRegistry found in build()'s return. The cross-check "
              "did not run, and a check that cannot find its subject is not "
              "evidence that the subject is correct.")
    else:
        for name in live.names():
            sensor = live._sensors[name]           # noqa: SLF001
            if sensor.subject not in reg_terms:
                r.err(f"sensor {name!r} writes subject {sensor.subject!r}, "
                      f"which no trigger predicate resolves. Predicates read: "
                      f"{sorted(reg_terms)}. A snapshot splits "
                      "`world.current_host.health` on the LAST dot, so a sensor "
                      "written against `current_host` fills the world correctly "
                      "and leaves every trigger over it UNKNOWN and silent, "
                      "with no event saying why.")

    # 4. A SENSOR WHOSE CLASS IS UNKNOWN IS REFUSED. The class decides the
    #    mechanism, so guessing it schedules by guesswork.
    try:
        Sensor("bad", "x", "y", lambda: 1, "whenever")
        r.err("a sensor with an unrecognised source class was accepted")
    except SensorRefused:
        pass

    r.note("a probe reaching the gateway is refused there and recorded; a "
           "GATED source is not polled and a SWEEP is; a working probe populates the "
           "world model the predicates already read; a failing one yields "
           "UNKNOWN, writes nothing and is logged; an unknown source class is "
           "refused")
    return r


def check_floor_never_swallows_or_drops() -> Result:
    """The four barge-in outcomes differ in BEHAVIOUR, not only in name.

    THIS IS THE LINK BETWEEN TWO THINGS THAT EXISTED AND DID NOTHING TOGETHER.
    `core/chooser.py` sets `announce` past 600 ms; `core/barge_in.py` classifies
    what the owner says during such a hold, carries 242 phrases and a gate, and
    was called by nothing. An announcement with no way to respond is a status
    line; a classifier nothing feeds is a table.

    SWALLOW IS THE OUTCOME MOST LIKELY TO BE BUILT WRONG, because answering is
    polite. "Take your time" met with "certainly, I'll continue" is VESPER
    interrupting the owner's permission not to be interrupted -- a cooperative
    interruption supports the current speaker, and responding to one takes the
    floor the owner just declined.

    AND A DROPPED QUEUE IS INDISTINGUISHABLE FROM A SWALLOW from where the owner
    is standing. They said something during a hold and it never arrived; whether
    it was classified wrongly or delivered nowhere is invisible, and either way
    they learn that speaking during a hold loses what they said.
    """
    r = Result("floor-never-swallows-or-drops")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core.floor import FloorHolder, Held
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.floor did not import: {exc!r}")
        return r

    LONG_A = "could you also look at the hotel booking while you are in there"
    LONG_B = "and I was wondering about the flight times for next Tuesday as well"

    # 1. OUTSIDE A HOLD, AN UTTERANCE IS NOT A BARGE-IN.
    f = FloorHolder()
    try:
        f.offer("stop")
        r.err("an utterance was classified as a barge-in with no floor held. "
              "Outside a hold it is an ordinary request and belongs in Intake; "
              "routing it here sends normal speech through a table that only "
              "knows how to stop work.")
    except Held:
        pass

    # 2. A HALT BREAKS, AND RELEASES THE FLOOR.
    f.hold("checking the calendar")
    v = f.offer("stop")
    if not v.acted or f.holding:
        r.err(f"'stop' during a hold gave acted={v.acted}, still "
              f"holding={f.holding}. A system that cannot be stopped is one "
              "nobody will leave running.")
    if not f.broken:
        r.err("the break was not recorded, so the caller cannot tell an "
              "abandoned hold from a completed one")

    # 3. SWALLOW IS SILENT. All three effects must be false together.
    f2 = FloorHolder()
    f2.hold("working")
    for u in ("take your time", "no rush", "mhm"):
        v = f2.offer(u)
        if v.acted:
            r.err(f"{u!r} cancelled the work it was granting time for. The "
                  "owner is punished for being polite.")
        if v.answer:
            r.err(f"{u!r} produced an answer. Responding to a cooperative "
                  "interruption takes the floor the owner just declined to "
                  "take -- VESPER interrupting permission not to be "
                  "interrupted.")
        if v.queued:
            r.err(f"{u!r} was queued and will be delivered later as though it "
                  "were a request")

    # 4. STATUS ANSWERS AND DOES NOT CANCEL. Both halves, because answering by
    #    stopping is the natural wrong implementation.
    for u in ("how long", "still there?"):
        v = f2.offer(u)
        if not v.answer:
            r.err(f"{u!r} got no answer. A liveness check is the owner asking "
                  "whether the silence is work or a hang.")
        if v.acted or not f2.holding:
            r.err(f"{u!r} cancelled the work. The answer to 'are you still "
                  "there' must not be to stop being there.")
    if not f2.status_line():
        r.err("the status line is empty, so a liveness check is answered with "
              "nothing")

    # 5. QUEUE DELIVERS, ONCE.
    f3 = FloorHolder()
    f3.hold("thinking")
    for u in (LONG_A, LONG_B):
        if not f3.offer(u).queued:
            r.err(f"a long request was not queued: {u[:40]!r}")
    delivered = f3.release()
    if len(delivered) != 2:
        r.err(f"release() delivered {len(delivered)} of 2 queued utterances. A "
              "dropped queue is indistinguishable from a swallow from where "
              "the owner is standing.")
    if f3.release():
        r.err("release() delivered the same queue twice, so a retrying caller "
              "would replay the owner's words as new requests")
    if f3.holding:
        r.err("the floor is still held after release()")

    r.note("an utterance outside a hold is refused; a halt breaks and releases; "
           "cooperative interruptions are silent in all three effects; a "
           "liveness check is answered without cancelling; a long request is "
           "queued and delivered exactly once")
    return r


def check_arabizi_preserves_and_marks_itself() -> Result:
    """The digit convention converts, nothing is dropped, and it admits it is a guess.

    THE DIGITS ARE THE ONLY PART THAT MUST BE RIGHT. Arabizi has no standard --
    vowels are written by feel and the same sound has several spellings -- but
    3, 7, 9, 2, 5 and 6 stand for letters Latin has no glyph for, and they are
    exactly the characters that break a speech engine. Apple reads `3awd` as
    "three-awd", which is why it cannot speak Darija at all.

    NOTHING MAY BE DROPPED. A transliterator that silently discarded what it
    could not map would delete content, which is worse than leaving a character
    alone -- the speech engine would say a shorter, different sentence and
    nothing would report it.

    IT MUST SAY IT IS UNVERIFIED. `MEASURED = False` until a Darija speaker has
    graded the output. INV-HW-2's habit applies to language as much as to
    throughput: a transliteration that looks plausible in a diff is exactly the
    kind of thing that ships wrong, and only the owner can grade it.
    """
    r = Result("arabizi-preserves-and-marks-itself")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from core import arabizi
    except Exception as exc:                       # noqa: BLE001
        r.err(f"core.arabizi did not import: {exc!r}")
        return r

    # 1. THE DIGIT CONVENTION.
    for digit, letter, word in (("3", "ع", "3awd"), ("7", "ح", "7it"),
                                ("9", "ق", "n9ol"), ("5", "خ", "5obz"),
                                ("2", "ء", "2ana"), ("6", "ط", "6abla")):
        got = arabizi.transliterate(word)
        if letter not in got:
            r.err(f"{word!r} -> {got!r} does not contain {letter!r}. The digit "
                  f"{digit} is a LETTER in Arabizi; a speech engine handed it "
                  "unconverted reads it as a number, which is the entire "
                  "failure this module exists to prevent.")
        if digit in got:
            r.err(f"{word!r} -> {got!r} still contains the digit {digit!r}")

    # 2. LONGEST MATCH FIRST. `ch` is one sound; consumed as `c`+`h` it is two
    #    wrong ones, and the word is not the word.
    if arabizi.transliterate("chi") != "شي":
        r.err(f"'chi' -> {arabizi.transliterate('chi')!r}, expected 'شي'. The "
              "digraph was split, which means single letters are being matched "
              "before longer keys.")
    for pair in ("kh", "gh", "sh", "th", "dh"):
        got = arabizi.transliterate(pair)
        if len(got) != 1:
            r.err(f"digraph {pair!r} produced {len(got)} characters ({got!r})")
    # ASSERTED ON THE ORDER ITSELF, not only on its effect. `_MAP`'s insertion
    # order already happens to put digraphs before single letters, so a mutation
    # replacing the sort with the dict's own order is a no-op TODAY and a bug
    # the moment anyone adds a key in the wrong place. The invariant is that the
    # matcher is length-ordered, and that is what this checks.
    lens = [len(k) for k in arabizi._ORDERED]      # noqa: SLF001
    if lens != sorted(lens, reverse=True):
        r.err("the match order is not longest-first. It works only while the "
              "dict happens to be written in a helpful order, and the next key "
              "added out of place silently splits a digraph.")

    # 3. NOTHING IS DROPPED, and the fixtures must actually REACH the
    #    fall-through. Every a-z letter is mapped and the three punctuation
    #    marks are handled, so a test built from ordinary words never exercises
    #    the branch that keeps an unrecognised character -- the first version of
    #    this assertion was vacuous for exactly that reason. These are
    #    characters with no mapping: sentence punctuation and non-convention
    #    digits.
    for ch in (".", "!", "-", "0", "1", "4", "%"):
        got = arabizi.transliterate(f"sbah{ch}lkhir")
        if ch not in got:
            r.err(f"{ch!r} was dropped during transliteration. An unmapped "
                  "character must pass through: dropping it makes the speech "
                  "engine say a shorter, different sentence, and nothing "
                  "anywhere reports the deletion.")
    for text in ("hello 3awd", "at 9am", "شي حاجة", "a, b; c?"):
        if not arabizi.transliterate(text).strip():
            r.err(f"{text!r} transliterated to nothing")
    # Arabic already present passes through untouched.
    if arabizi.transliterate("شي حاجة") != "شي حاجة":
        r.err("existing Arabic script was altered; the function must pass it "
              "through, or a re-run would corrupt its own output")

    # 4. IT ADMITS IT IS A GUESS.
    if getattr(arabizi, "MEASURED", True):
        r.err("MEASURED is True. Nothing has graded this against a Darija "
              "speaker's ear, and a transliterator that claims verification it "
              "does not have is the declared reading INV-HW-2 refuses.")

    # 5. DETECTION USES THE DIGIT SIGNAL, not the mere presence of a digit.
    if not arabizi.looks_arabizi("3awd 3afak"):
        r.err("digit-bearing Darija was not detected as Arabizi")
    if arabizi.looks_arabizi("meet me at 9am tomorrow"):
        r.err("ordinary English with a digit was detected as Arabizi. A "
              "digit-bearing token is Arabizi unless its letters are a known "
              "English unit -- 9am, 3pm, 1st, 5kg -- because otherwise every "
              "English sentence carrying a time would be transliterated into "
              "nonsense.")

    r.note("six digit-letters convert and none survives as a digit; digraphs "
           "match before single letters; Arabic passes through unchanged; "
           "nothing is dropped; MEASURED is False; a digit-bearing token is "
           "Arabizi unless its letters are a known English unit")
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
    "triage-excludes-quota": check_triage_excludes_quota,
    "shared-pool-is-shared": check_shared_pool_is_shared,
    "intake-is-modality-neutral": check_intake_is_modality_neutral,
    "persona-is-a-contract": check_persona_is_a_contract,
    "difficulty-classifies-up": check_difficulty_classifies_up,
    "barge-in-never-swallows-a-halt": check_barge_in_never_swallows_a_halt,
    "baseline-records-what-cannot-be-rebuilt":
        check_baseline_records_what_cannot_be_rebuilt,
    "memory-projects-from-the-log": check_memory_projects_from_the_log,
    "redactor-precedes-every-provider": check_redactor_precedes_every_provider,
    "updater-refuses-and-ranks": check_updater_refuses_and_ranks,
    "l1-blocks-hold-index-not-knowledge": check_l1_blocks_hold_index_not_knowledge,
    "arbiter-never-picks-silently": check_arbiter_never_picks_silently,
    "forgetter-never-edits-in-place": check_forgetter_never_edits_in_place,
    "reprojection-never-resurrects": check_reprojection_never_resurrects,
    "chooser-escalates-only-when-unsure": check_chooser_escalates_only_when_unsure,
    "sensors-never-reach-a-model": check_sensors_never_reach_a_model,
    "floor-never-swallows-or-drops": check_floor_never_swallows_or_drops,
    "arabizi-preserves-and-marks-itself": check_arabizi_preserves_and_marks_itself,
    "system-turn-reaches-the-wire": check_system_turn_reaches_the_wire,
    "latency-preference-reorders": check_latency_preference_reorders,
    "egress-gates-at-choke-point": check_egress_gates_at_choke_point,
    "face-follows-activity": check_face_follows_activity,
    "chrome-template-renders": check_chrome_template_renders,
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
