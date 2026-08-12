"""
traceability_lint.py -- CI check CI-003.

Enforces INV-TRACE-1:

    Every SR names >= 1 architecture section, >= 1 interface contract, and
    >= 1 acceptance test ID, or carries an explicitly recorded R&D / EXCLUDED
    disposition. Every acceptance test names >= 1 SR. Every architecture
    section and every DR is referenced by >= 1 SR or is explicitly marked
    non-requirement-bearing. Every referenced artifact exists.

Design note: the locked COC is the authority for WHICH identifiers exist
(tools/vesper_ids.py). This linter never trusts the registry's own claim about
the identifier set -- that is exactly the failure mode that let COC Part XI
assert a PASS it did not have.

Profiles
    engineering (default)  unratified owner decisions are INFO
    release                unratified owner decisions are ERROR, and every SR
                           must reach status SPECIFIED or better

Exit code 0 only when there are zero ERROR findings.

Stdlib only. Python >= 3.11 (tomllib).
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vesper_ids import REPO_ROOT, parse_coc  # noqa: E402

REGISTRY = REPO_ROOT / "verification" / "traceability" / "registry.toml"
ACCEPTANCE_INDEX = REPO_ROOT / "verification" / "acceptance" / "INDEX.toml"
INVARIANT_INDEX = REPO_ROOT / "spec" / "invariants" / "INVARIANTS.toml"
STATE_MACHINE_INDEX = REPO_ROOT / "spec" / "state-machines" / "INDEX.toml"
DECISION_FN_INDEX = REPO_ROOT / "spec" / "decision-functions" / "INDEX.toml"
CI_INDEX = REPO_ROOT / "verification" / "ci" / "CHECKS.toml"

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

# Statuses that excuse a missing acceptance-test mapping (never both, and never
# silently -- each must carry a `note` recording the Part XIV.3 disposition).
DISPOSITION_STATUSES = {"R_AND_D", "EXCLUDED", "EXCLUDED_BY_SAFETY_POLICY"}
DEPTH_ORDER = [
    "UNMAPPED",
    "DESIGNED",
    "CONTRACTED",
    "SPECIFIED",
    "IMPLEMENTED",
    "VERIFIED",
    "ACCEPTED",
]
TERMINAL_STATUSES = {"R_AND_D", "PARTIAL_R_AND_D", "EXCLUDED", "EXCLUDED_BY_SAFETY_POLICY", "NARROWED_BY_OWNER_APPROVAL"}


class Findings:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # severity, code, message

    def add(self, severity: str, code: str, message: str) -> None:
        self.items.append((severity, code, message))

    def count(self, severity: str) -> int:
        return sum(1 for s, _, _ in self.items if s == severity)

    def report(self) -> None:
        order = {ERROR: 0, WARN: 1, INFO: 2}
        for severity, code, message in sorted(self.items, key=lambda i: (order[i[0]], i[1])):
            print(f"  [{severity:5}] {code:22} {message}")


def load_toml(path: Path, findings: Findings, code: str) -> dict:
    if not path.is_file():
        findings.add(
            ERROR,
            code,
            f"required registry missing: {path.relative_to(REPO_ROOT).as_posix()}",
        )
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        findings.add(ERROR, code, f"{path.relative_to(REPO_ROOT).as_posix()} is not valid TOML: {exc}")
        return {}


def declared_ids(doc: dict, section: str) -> set[str]:
    """Artifact index files use `[<section>.<ID>]` tables."""
    return set(doc.get(section, {}) or {})


def main() -> int:
    ap = argparse.ArgumentParser(description="VESPER traceability linter (CI-003)")
    ap.add_argument("--profile", choices=("engineering", "release"), default="engineering")
    args = ap.parse_args()

    f = Findings()
    coc = parse_coc()
    reg = load_toml(REGISTRY, f, "TR-000")
    if not reg:
        print("\nTRACEABILITY LINT: FAIL (registry unreadable)")
        f.report()
        return 1

    requirements: dict[str, dict] = reg.get("requirements", {}) or {}
    non_bearing: dict[str, str] = reg.get("non_requirement_bearing", {}) or {}
    derived: dict[str, list[str]] = reg.get("derived_requirements", {}) or {}
    source_gaps: dict[str, dict] = reg.get("source_gaps", {}) or {}

    acc_doc = load_toml(ACCEPTANCE_INDEX, f, "TR-001")
    inv_doc = load_toml(INVARIANT_INDEX, f, "TR-002")
    sm_doc = load_toml(STATE_MACHINE_INDEX, f, "TR-003")
    df_doc = load_toml(DECISION_FN_INDEX, f, "TR-004")
    ci_doc = load_toml(CI_INDEX, f, "TR-005")

    known_tests = declared_ids(acc_doc, "tests") | set(coc.a)
    known_invariants = declared_ids(inv_doc, "invariants")
    known_state_machines = declared_ids(sm_doc, "state_machines")
    known_decision_fns = declared_ids(df_doc, "decision_functions")
    known_ci = declared_ids(ci_doc, "checks")

    # ---------------------------------------------------------------- SR rows
    for sr in sorted(coc.sr):
        if sr not in requirements:
            f.add(ERROR, "TR-010", f"{sr} defined in the COC has no registry row (orphan source requirement)")
    for sr in sorted(requirements):
        if sr not in coc.sr:
            f.add(ERROR, "TR-011", f"registry row {sr} is not an SR defined in the locked COC")

    arch_refs: dict[str, set[str]] = defaultdict(set)
    ic_refs: dict[str, set[str]] = defaultdict(set)
    test_refs: dict[str, set[str]] = defaultdict(set)

    for sr, row in sorted(requirements.items()):
        status = row.get("status", "UNMAPPED")
        if status not in set(DEPTH_ORDER) | TERMINAL_STATUSES:
            f.add(ERROR, "TR-012", f"{sr} has unrecognised status {status!r}")
        if status in TERMINAL_STATUSES and not row.get("note"):
            f.add(
                ERROR,
                "TR-013",
                f"{sr} carries status {status} with no `note` -- COC Part XIV.3 requires a recorded "
                f"limitation and an R&D path, never a bare status",
            )

        for a in row.get("arch", []):
            arch_refs[a].add(sr)
            if a not in coc.arch:
                f.add(ERROR, "TR-014", f"{sr} references unknown architecture section {a}")
        if not row.get("arch") and status not in DISPOSITION_STATUSES:
            f.add(ERROR, "TR-015", f"{sr} maps to no architecture section")

        for ic in row.get("ic", []):
            ic_refs[ic].add(sr)
            if ic not in coc.ic:
                f.add(ERROR, "TR-016", f"{sr} references unknown interface contract {ic}")
        if not row.get("ic") and status not in DISPOSITION_STATUSES:
            f.add(ERROR, "TR-017", f"{sr} maps to no interface contract")

        for t in row.get("tests", []):
            test_refs[t].add(sr)
            if t not in known_tests:
                f.add(
                    ERROR,
                    "TR-018",
                    f"{sr} references acceptance test {t}, which is defined neither in the COC "
                    f"nor in verification/acceptance/INDEX.toml",
                )
        if not row.get("tests") and status not in DISPOSITION_STATUSES:
            f.add(ERROR, "TR-019", f"{sr} maps to no acceptance test and carries no recorded disposition")

        for c in row.get("contracts", []):
            if not (REPO_ROOT / c).is_file():
                f.add(ERROR, "TR-020", f"{sr} references contract file {c}, which does not exist")
        for i in row.get("invariants", []):
            if i not in known_invariants:
                f.add(ERROR, "TR-021", f"{sr} references undeclared invariant {i}")
        for s in row.get("state_machines", []):
            if s not in known_state_machines:
                f.add(ERROR, "TR-022", f"{sr} references undeclared state machine {s}")
        for d in row.get("decision_functions", []):
            if d not in known_decision_fns:
                f.add(ERROR, "TR-023", f"{sr} references undeclared decision function {d}")
        for c in row.get("ci", []):
            if c not in known_ci:
                f.add(ERROR, "TR-024", f"{sr} references undeclared CI check {c}")

        # Depth: a mechanism is not specified until it is executable.
        if status in ("CONTRACTED", "SPECIFIED") and not row.get("contracts"):
            f.add(ERROR, "TR-025", f"{sr} claims status {status} with no contract/schema artifact")
        if status == "SPECIFIED" and not (row.get("state_machines") or row.get("decision_functions")):
            f.add(
                ERROR,
                "TR-026",
                f"{sr} claims SPECIFIED with neither a state machine nor a decision function -- a schema "
                f"alone can be satisfied while behaviour is wrong",
            )
        if args.profile == "release" and status in DEPTH_ORDER and DEPTH_ORDER.index(status) < DEPTH_ORDER.index("SPECIFIED"):
            f.add(ERROR, "TR-027", f"{sr} is only {status}; release profile requires SPECIFIED or better")

        # An SR sitting below SPECIFIED must name the ARTIFACT that would raise
        # it. Without this, "not yet specified" is indistinguishable from
        # "nobody has looked", and the two have very different costs. The
        # disposition NEVER excuses the depth: TR-027 above still fails in the
        # release profile, so recording one cannot turn a FAIL into a PASS.
        if status in DEPTH_ORDER and DEPTH_ORDER.index(status) < DEPTH_ORDER.index("SPECIFIED"):
            if not row.get("depth_disposition"):
                f.add(
                    ERROR,
                    "TR-028",
                    f"{sr} is only {status} and records no `depth_disposition` naming the artifact "
                    f"required to reach SPECIFIED",
                )
            if not row.get("depth_note"):
                f.add(
                    ERROR,
                    "TR-029",
                    f"{sr} records a depth_disposition with no `depth_note` explaining why the artifact "
                    f"does not exist yet -- a bare disposition is a label, not a decision",
                )

    # ------------------------------------------------- reverse-orphan checks
    for arch in sorted(coc.arch):
        if arch not in arch_refs and arch not in non_bearing:
            f.add(
                ERROR,
                "TR-030",
                f"architecture section {arch} ({coc.arch[arch][:56]}) is referenced by zero SRs and is "
                f"not declared non-requirement-bearing",
            )
    for arch in sorted(non_bearing):
        if arch not in coc.arch:
            f.add(ERROR, "TR-031", f"non_requirement_bearing lists {arch}, which is not a COC architecture section")
        elif arch in arch_refs:
            f.add(WARN, "TR-032", f"{arch} is declared non-requirement-bearing but is referenced by {sorted(arch_refs[arch])}")

    for dr in sorted(coc.dr):
        srs = derived.get(dr)
        if not srs:
            f.add(ERROR, "TR-040", f"derived requirement {dr} ({coc.dr[dr][:48]}) is referenced by zero SRs")
            continue
        for sr in srs:
            if sr not in coc.sr:
                f.add(ERROR, "TR-041", f"{dr} references unknown {sr}")
    for dr in sorted(derived):
        if dr not in coc.dr:
            f.add(ERROR, "TR-042", f"derived_requirements lists {dr}, which the COC does not define")

    for ic in sorted(coc.ic):
        if ic not in ic_refs:
            f.add(ERROR, "TR-050", f"interface contract {ic} ({coc.ic[ic][:40]}) is referenced by zero SRs")

    for t in sorted(known_tests):
        if t not in test_refs:
            f.add(ERROR, "TR-060", f"acceptance test {t} maps to zero SRs (a test that traces to nothing gates nothing)")

    # Reverse-orphan for MECHANISMS. The same rule already applied to
    # architecture sections, DRs, ICs and tests was never applied to state
    # machines, decision functions or implemented CI checks -- and a sweep on
    # 2026-08-12 found 2 state machines, 2 decision functions and 4 implemented
    # checks tracing to nothing. Each was correct and load-bearing; none was
    # reachable from any requirement, so none would have been noticed if it had
    # been deleted.
    used_sm = {s for row in requirements.values() for s in row.get("state_machines", [])}
    used_df = {d for row in requirements.values() for d in row.get("decision_functions", [])}
    used_ci = {c for row in requirements.values() for c in row.get("ci", [])}

    for s in sorted(known_state_machines - used_sm):
        f.add(ERROR, "TR-065", f"state machine {s} is referenced by zero SRs (a mechanism that traces to nothing enforces nothing)")
    for d in sorted(known_decision_fns - used_df):
        f.add(ERROR, "TR-066", f"decision function {d} is referenced by zero SRs")
    implemented_ci = {
        c for c, entry in (ci_doc.get("checks", {}) or {}).items()
        if entry.get("impl") and entry.get("impl") != "PENDING"
    }
    for c in sorted(implemented_ci - used_ci):
        f.add(
            ERROR,
            "TR-067",
            f"CI check {c} is implemented and runs, but no SR names it -- enforcement that traces to no "
            f"requirement cannot be reported as coverage of one",
        )

    # A declared test ID is not a test. Every entry in the acceptance index must
    # point at a specification file that exists, so that declaring an ID can
    # never manufacture coverage.
    for tid, entry in sorted((acc_doc.get("tests", {}) or {}).items()):
        spec = entry.get("spec")
        if not spec:
            f.add(ERROR, "TR-061", f"acceptance test {tid} declares no `spec` file")
        elif not (REPO_ROOT / spec).is_file():
            f.add(ERROR, "TR-062", f"acceptance test {tid} references specification {spec}, which does not exist")
        else:
            # TR-068 -- CONTENT COUPLING, added 2026-08-12.
            #
            # TR-062 verifies the named file EXISTS. It never verified that the
            # file has anything to do with the test. A probe repointed A-029 --
            # the anti-cron discriminator, the single most important run in the
            # programme -- from AT-03 to AT-04, a file that never mentions
            # A-029, and this linter stayed PASS with 0 errors.
            #
            # Unrelated-artifact substitution is the cheapest way to keep a
            # traceability chain green while emptying it, and it is invisible in
            # a diff that only moves a filename. The same rule the CI registry
            # already applies to SM-/DF- ids is applied here.
            body = (REPO_ROOT / spec).read_text(encoding="utf-8", errors="replace")
            if tid not in body:
                f.add(
                    ERROR,
                    "TR-068",
                    f"acceptance test {tid} points at {spec}, which never mentions {tid}. A `spec` "
                    f"pointer that resolves to an unrelated file is traceability in name only.",
                )
        if not entry.get("gate"):
            f.add(ERROR, "TR-063", f"acceptance test {tid} declares no `gate` (release level at which it blocks)")

        # A test with no named wrong build has never been shown to discriminate.
        # Two honest answers are accepted and silence is not:
        #   negative_control            the specific non-compliant build that must FAIL
        #   negative_control_rationale  why a trivial build cannot pass this test
        # The second is not a loophole -- it is a claim, in writing, that a
        # reviewer can disagree with. An absent field is a claim nobody made.
        if not entry.get("negative_control") and not entry.get("negative_control_rationale"):
            f.add(
                ERROR,
                "TR-064",
                f"acceptance test {tid} names neither a `negative_control` (the wrong build that must "
                f"FAIL) nor a `negative_control_rationale` (why a trivial build cannot pass). A gate "
                f"that has only ever been green is not evidence.",
            )

    # ----------------------------------------------------- owner decisions
    unratified = [k for k, v in source_gaps.items() if v.get("disposition") == "AWAITING_OWNER_RATIFICATION"]
    if unratified:
        sev = ERROR if args.profile == "release" else INFO
        f.add(
            sev,
            "TR-070",
            f"{len(unratified)} handwritten source clause(s) still have no SR ID and await owner "
            f"ratification ({', '.join(sorted(unratified))}). No coverage claim may be made until these "
            f"are dispositioned. Ref docs/decisions/OWNER-DECISION-002.",
        )

    # ------------------------------------------------------------- report
    errors, warns, infos = f.count(ERROR), f.count(WARN), f.count(INFO)
    print(f"VESPER traceability lint (CI-003) -- profile={args.profile}")
    print(f"COC index: {coc.summary()}")
    print(
        f"registry: {len(requirements)} SR rows, {len(derived)} DR rows, "
        f"{len(known_tests)} known tests, {len(source_gaps)} recorded source gaps"
    )
    if f.items:
        print("\nFindings:")
        f.report()
    verdict = "FAIL" if errors else "PASS"
    print(f"\nTRACEABILITY LINT: {verdict}  (errors={errors} warnings={warns} info={infos})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
