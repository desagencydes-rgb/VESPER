"""
tools/reference_lint.py -- CI check CI-050 (reference integrity).

WHY THIS EXISTS

On 2026-08-12 a sweep of the corpus found:

  * 11 REM specifications citing a "Decision record" at docs/ADR/ADR-0xx-*.md
    where the file had never been created -- including ADR-002, which INV-ADR-1
    makes a hard merge gate for everything under core/, tasks/ and memory/;
  * 4 of those citations naming ADR ids (017-020) outside the Foundation's
    authoritative ADR-001..016 namespace;
  * 13 contract paths named in REM sections titled "Contract / state machine /
    decision function" that had never been created, including
    contracts/entities/lease.schema.json and contracts/entities/task.schema.json,
    both of which F0 depends on;
  * CI-045, declared by REM-014, absent from verification/ci/CHECKS.toml.

None of this was detectable. tools/traceability_lint.py validates artifact paths
listed in registry.toml (TR-020) and nothing else, so a specification could name
an artifact that did not exist and every gate stayed green.

The rule this enforces:

    A NORMATIVE DOCUMENT MAY NOT NAME AN ARTIFACT THAT DOES NOT EXIST.

Scope is deliberately limited to normative directories. docs/review/ and
docs/baseline/ are historical records: the review documents legitimately propose
paths that were later created elsewhere or not at all, and rewriting history to
satisfy a linter would destroy the audit trail they exist to provide.

Usage:
    python tools/reference_lint.py
    python tools/reference_lint.py --self-test

Stdlib only. Python >= 3.11.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Directories whose contents are NORMATIVE and must not dangle.
NORMATIVE_ROOTS = [
    "docs/remediation",
    "docs/architecture",
    "docs/ADR",
    "docs/runbooks",
    "docs/decisions",
    "docs/spikes",
    "spec",
    "verification",
    "contracts",
    "tools",
    # SCOPE EXTENSION 2026-08-12. An independent probe repointed the workflow's
    # check step at a checks script that does not exist, and this linter stayed
    # GREEN: the file naming every tool CI runs was itself unscanned. The
    # workflow is the one document whose dangling reference DISABLES enforcement
    # rather than merely misdescribing it.
    ".github/workflows",
]
NORMATIVE_FILES = [
    "README.md",
    "SETUP.md",
    "VESPER_ENGINEERING_STATUS.md",
    "CODEOWNERS",
    "docs/AUTHORITY_AND_PRECEDENCE.md",
    "docs/DECISION_LOG.md",
    "docs/WORK_REPORT_2026-08-12.md",
    "docs/FINAL_PRE_F0_VERIFICATION_REPORT.md",
    # THE LIVE RULEBOOK. docs/COC/ was excluded wholesale as "historical". Two
    # of its files are not: v1.1 is the locked baseline and v1.2-additive is the
    # ratified extension, and both sit SECOND in the authority hierarchy, above
    # everything in docs/remediation/. A probe planted a dangling tools/ path in
    # the v1.2 additive and this linter stayed green. Superseded COC documents
    # stay excluded -- rewriting a retired baseline to satisfy a linter would
    # destroy the record it exists to be.
    "docs/COC/VESPER_V0_DEFINITIVE_COC_AND_RULEBOOK_v1.1.md",
    "docs/COC/VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md",
]

# Historical records. Referenced-but-absent paths here are the audit trail.
EXCLUDED_ROOTS = ["docs/review", "docs/baseline", "docs/COC", "docs/source"]

ADR_REGISTER = REPO / "docs" / "ADR" / "ADR-REGISTER.md"
SPIKE_INDEX = REPO / "docs" / "spikes" / "INDEX.toml"

PATH_RE = re.compile(r"(?<![\w/.-])((?:docs|contracts|spec|verification|tools)/[A-Za-z0-9_./-]+\.(?:md|json|toml|py|yml|yaml))")
ADR_ID_RE = re.compile(r"\bADR-(\d{3})\b")
SPIKE_ID_RE = re.compile(r"\bSPIKE-(\d{3})\b")

# The Foundation's Initial ADR Register defines the namespace. It stands to ADR
# ids as the COC stands to SR ids: authority for WHICH identifiers exist.
FOUNDATION_ADR_MAX = 16


class Findings:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def err(self, code: str, msg: str) -> None:
        self.items.append(("ERROR", code, msg))

    def warn(self, code: str, msg: str) -> None:
        self.items.append(("WARN", code, msg))

    @property
    def errors(self) -> int:
        return sum(1 for s, _, _ in self.items if s == "ERROR")

    def report(self) -> None:
        order = {"ERROR": 0, "WARN": 1}
        for sev, code, msg in sorted(self.items, key=lambda i: (order[i[0]], i[1])):
            print(f"  [{sev:5}] {code:10} {msg}")


def normative_files() -> list[Path]:
    out: list[Path] = []
    for root in NORMATIVE_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in {".md", ".toml", ".json", ".py", ".yml", ".yaml"}:
                continue
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(REPO).as_posix()
            if any(rel.startswith(x) for x in EXCLUDED_ROOTS):
                continue
            out.append(p)
    for f in NORMATIVE_FILES:
        p = REPO / f
        if p.is_file():
            out.append(p)
    return sorted(set(out))


def check(f: Findings) -> None:
    files = normative_files()

    # ---------------------------------------------------------------- RF-010
    # Every path named by a normative document must exist.
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(REPO).as_posix()
        for m in PATH_RE.finditer(text):
            target = m.group(1)
            # A file may describe its own future siblings only if they exist.
            if not (REPO / target).exists():
                f.err("RF-010", f"{rel} names {target}, which does not exist")

    # ---------------------------------------------------------------- RF-020
    # Every ADR id referenced must appear in the register, and the register
    # may not invent ids outside the Foundation namespace.
    if not ADR_REGISTER.is_file():
        f.err("RF-020", "docs/ADR/ADR-REGISTER.md is missing -- ADR ids have no authority")
        registered: set[str] = set()
    else:
        reg_text = ADR_REGISTER.read_text(encoding="utf-8")
        # REGISTER ROWS ONLY. The register's prose legitimately discusses ids
        # outside the namespace -- §2 records the ADR-017..020 citation defect
        # and how it was resolved. Deleting that discussion to satisfy a linter
        # would erase the only record that the defect existed.
        registered = {
            m.group(1)
            for m in re.finditer(r"^\|\s*\*\*(ADR-\d{3})\*\*\s*\|", reg_text, re.M)
        }
        if not registered:
            f.err("RF-023", "ADR-REGISTER.md contains no register rows (expected '| **ADR-0xx** |' table rows)")
        # RF-021 applies to REGISTER ROWS ONLY, and is evaluated BEFORE retired
        # ids are merged in. A retired id may be discussed; it may never occupy
        # a register row.
        for adr in sorted(registered):
            n = int(adr.split("-")[1])
            if n > FOUNDATION_ADR_MAX:
                f.err(
                    "RF-021",
                    f"ADR register lists {adr} as a register row, outside the Foundation namespace "
                    f"ADR-001..ADR-{FOUNDATION_ADR_MAX:03d}. Extending the namespace is a baseline "
                    f"change, not a bookkeeping act.",
                )

        # Retired ids: never existed, recorded so the corrective sentences in
        # REM-003..006 may keep naming them. The record of a defect is worth
        # more than a clean grep. A NEW reference to anything neither registered
        # nor retired still fails RF-022.
        m_ret = re.search(r"retired_ids\s*=\s*\[([^\]]*)\]", reg_text)
        retired = set(re.findall(r"ADR-\d{3}", m_ret.group(1))) if m_ret else set()
        registered |= retired

    for p in files:
        if p.relative_to(REPO).as_posix() == "docs/ADR/ADR-REGISTER.md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(REPO).as_posix()
        for m in ADR_ID_RE.finditer(text):
            adr = m.group(0)
            if adr not in registered:
                f.err("RF-022", f"{rel} references {adr}, which is not in docs/ADR/ADR-REGISTER.md")

    # ---------------------------------------------------------------- RF-030
    # Every ADR whose status requires a filed record must have one, and every
    # filed ADR must declare a Status.
    for adr_file in sorted((REPO / "docs" / "ADR").glob("ADR-*.md")):
        if adr_file.name == "ADR-REGISTER.md":
            continue
        head = adr_file.read_text(encoding="utf-8")[:1500]
        if "**Status**" not in head:
            f.err("RF-030", f"{adr_file.name} declares no Status -- an undated, unstatused decision record is a draft")
        elif not re.search(r"\*\*Status\*\*\s*\|\s*\*{0,2}(ACCEPTED|PROPOSED|SUPERSEDED|REJECTED|DEFERRED)", head):
            f.err("RF-031", f"{adr_file.name} Status is not one of ACCEPTED / PROPOSED / SUPERSEDED / REJECTED / DEFERRED")

    # ---------------------------------------------------------------- RF-040
    # Every SPIKE referenced must have a protocol with measurable criteria.
    if not SPIKE_INDEX.is_file():
        f.err("RF-040", "docs/spikes/INDEX.toml is missing -- spike ids have no registry")
        spikes: dict = {}
    else:
        spikes = tomllib.loads(SPIKE_INDEX.read_text(encoding="utf-8")).get("spikes", {})
        for sid, s in sorted(spikes.items()):
            proto = s.get("protocol")
            if not proto:
                f.err("RF-041", f"{sid} declares no protocol file")
            elif not (REPO / proto).is_file():
                f.err("RF-042", f"{sid} references protocol {proto}, which does not exist")
            if not s.get("pass_criteria"):
                f.err(
                    "RF-043",
                    f"{sid} declares no pass_criteria -- a spike with no failure condition returns "
                    f"'we looked into it', which is not a deliverable",
                )
            if not s.get("on_fail"):
                f.err("RF-044", f"{sid} declares no on_fail disposition")

    referenced_spikes: set[str] = set()
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(REPO).as_posix()
        for m in SPIKE_ID_RE.finditer(text):
            sid = m.group(0)
            referenced_spikes.add(sid)
            if spikes and sid not in spikes:
                f.err("RF-045", f"{rel} references {sid}, which is not in docs/spikes/INDEX.toml")

    for sid in sorted(spikes):
        if sid not in referenced_spikes:
            f.warn("RF-046", f"{sid} is registered but referenced by no normative document")

    # ---------------------------------------------------------------- RF-050
    # Every CI check named by a REM specification must be in CHECKS.toml.
    checks_path = REPO / "verification" / "ci" / "CHECKS.toml"
    if checks_path.is_file():
        known = set(tomllib.loads(checks_path.read_text(encoding="utf-8")).get("checks", {}))
        ci_re = re.compile(r"\bCI-(\d{3}[a-z]?)\b")
        for p in files:
            rel = p.relative_to(REPO).as_posix()
            if not rel.startswith(("docs/remediation/", "docs/architecture/", "spec/", "verification/acceptance/")):
                continue
            for m in ci_re.finditer(p.read_text(encoding="utf-8", errors="replace")):
                cid = m.group(0)
                if cid not in known:
                    f.err("RF-050", f"{rel} relies on {cid}, which is not registered in verification/ci/CHECKS.toml")


# The probe tokens are ASSEMBLED rather than written out, so that this file
# contains no literal dangling path and no literal out-of-namespace ADR id.
# Until 2026-08-12 the scanner skipped itself for exactly that reason -- an
# excluded file inside the scan root is a hole, and this linter's whole purpose
# is that nothing normative goes unscanned. tools/ is governed surface S6; the
# tool that guards the corpus should not be the one file exempt from it.
_MISSING_CONTRACT = "contracts/entities/lease" + "_MISS" + "ING.schema.json"
_OUT_OF_NAMESPACE_ADR = "| **ADR-" + "0" + "99**"

_MISSING_TOOL = "tools/ci/checks" + "_MISS" + "ING.py"

SELF_TEST_CASES = [
    (
        "docs/remediation/REM-002-control-plane-ownership.md",
        "contracts/entities/lease.schema.json",
        _MISSING_CONTRACT,
        "a REM naming a contract that does not exist",
    ),
    (
        "docs/ADR/ADR-REGISTER.md",
        "| **ADR-002**",
        _OUT_OF_NAMESPACE_ADR,
        "an ADR id outside the Foundation namespace",
    ),
    # SCOPE red runs, added 2026-08-12. Each of these three mutations was GREEN
    # before the scan scope was extended.
    (
        ".github/workflows/ci.yml",
        "tools/ci/checks.py",
        _MISSING_TOOL,
        "the workflow pointed at a checks script that does not exist",
    ),
    (
        "docs/COC/VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md",
        "## Part VII-A",
        "See " + _MISSING_TOOL + " for enforcement.\n\n## Part VII-A",
        "a dangling tool path planted in the LIVE COC v1.2 additive baseline",
    ),
    # ANCHOR ON THE PATH, NOT THE HANDLE. This case originally matched
    # "/spec/  @owner" and broke the moment the placeholder was replaced with a
    # real account -- the harness reported "the mutation did not apply", which
    # is the correct behaviour and is why the case is anchored differently now.
    # The governed PATH is the stable part of the line; the reviewer identity
    # is owner data and will change again.
    (
        "CODEOWNERS",
        "\n/spec/",
        "\n# see " + _MISSING_CONTRACT + "\n/spec/",
        "a dangling contract path planted in CODEOWNERS",
    ),
]


def self_test() -> int:
    """Mutate, require ERROR; restore, require clean."""
    failures = 0
    print(f"{'DELIBERATE VIOLATION':56} {'RED':>6} {'GREEN':>6}")
    print("-" * 72)
    for rel, old, new, desc in SELF_TEST_CASES:
        p = REPO / rel
        # BYTE SAFETY: read_bytes/write_bytes, never read_text/write_text. On
        # Windows write_text rewrites every "\n" as "\r\n", so restoring an
        # LF-terminated normative document silently changes its bytes while its
        # text compares equal. Several scanned files (docs/COC/, the ADR
        # records) are LF. See the same note in tools/ci/self_test.py.
        original_bytes = p.read_bytes()
        original = original_bytes.decode("utf-8")
        if old not in original:
            print(f"{desc:56} {'N/A':>6} {'--':>6}")
            print(f"    FAILURE: mutation target absent in {rel}; this self-test tests nothing.")
            failures += 1
            continue
        try:
            p.write_bytes(original.replace(old, new, 1).encode("utf-8"))
            f_red = Findings()
            check(f_red)
        finally:
            p.write_bytes(original_bytes)
        if p.read_bytes() != original_bytes:
            failures += 1
            print(f"    FAILURE: {rel} was not restored byte-for-byte.")
        f_green = Findings()
        check(f_green)
        red_ok = f_red.errors > 0
        green_ok = f_green.errors == 0
        print(f"{desc:56} {('ERR' if red_ok else 'none'):>6} {('clean' if green_ok else f'{f_green.errors} err'):>6}")
        if not red_ok:
            failures += 1
            print("    FAILURE: no error raised on a deliberate violation.")
        if not green_ok:
            failures += 1
            print("    FAILURE: not clean after restore:")
            f_green.report()
    print("-" * 72)
    print(f"{len(SELF_TEST_CASES) - failures}/{len(SELF_TEST_CASES)} self-tests behaved correctly")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="VESPER reference-integrity lint (CI-050)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    f = Findings()
    check(f)
    print("VESPER reference-integrity lint (CI-050)")
    print(f"scanned {len(normative_files())} normative files")
    if f.items:
        print("\nFindings:")
        f.report()
    warns = len(f.items) - f.errors
    verdict = "FAIL" if f.errors else "PASS"
    print(f"\nREFERENCE LINT: {verdict}  (errors={f.errors} warnings={warns})")
    return 1 if f.errors else 0


if __name__ == "__main__":
    sys.exit(main())
