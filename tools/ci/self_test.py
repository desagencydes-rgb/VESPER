"""
tools/ci/self_test.py -- the red-run harness.

verification/ci/CHECKS.toml requires every check to declare a `self_test`: the
deliberate violation that MUST be shown failing before the check is trusted.
A declared self-test string is not a red run, and the difference is not
academic -- CI-022 and CI-044 both declared self-tests while their claimed
implementations never inspected the subject of the invariant they enforced.

This harness executes those self-tests. For each case it:

    1. mutates the artifact to the deliberately non-compliant state
    2. runs the check and requires exit 1
    3. restores the artifact byte-for-byte
    4. runs the check again and requires exit 0

A mutation that fails to apply is a FAILURE, not a skip: it means the harness
is testing a file that has changed shape, and a self-test that silently stops
testing is worse than none.

BYTE SAFETY. Every read and restore in this harness goes through read_bytes /
write_bytes, never read_text / write_text. On Windows, write_text translates
"\n" to "\r\n", so restoring an LF-terminated file with write_text rewrites
every line ending in it while leaving the visible text identical. The corpus is
genuinely mixed CRLF/LF -- docs/COC/, the ADR records and several contracts are
LF -- so a text-mode restore silently rewrites governed-surface bytes on every
run. Found 2026-08-12 by a probe that converted the live COC v1.2 additive
baseline from LF to CRLF; the restore compared equal as text and unequal as
bytes. A harness that mutates a governed surface must be byte-exact or it is
itself an integrity defect.

Usage:
    python tools/ci/self_test.py            # run every case
    python tools/ci/self_test.py <check>    # run one check's cases

Stdlib only. Python >= 3.11.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read(path: Path) -> tuple[str, bytes, bool]:
    """Return (LF-normalised text, original bytes, file-was-CRLF).

    The mutation patterns below are written with "\\n". Normalising for the
    MATCH keeps them readable; carrying the original bytes and the file's
    newline convention keeps the RESTORE byte-exact.
    """
    raw = path.read_bytes()
    return raw.decode("utf-8").replace("\r\n", "\n"), raw, b"\r\n" in raw


def write_mutated(path: Path, text: str, crlf: bool) -> None:
    """Write the transient mutated state in the file's own newline convention."""
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def restore(path: Path, raw: bytes) -> None:
    """Restore the ORIGINAL BYTES. Never write_text -- see BYTE SAFETY above."""
    path.write_bytes(raw)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

TRIGGERS = "contracts/policy/trigger_registry.toml"
LADDER = "contracts/policy/degradation_ladder.toml"
TUNABLES = "contracts/policy/tunables.toml"
CAPS = "contracts/policy/capability_profiles.toml"
LATENCY = "contracts/policy/latency_budgets.toml"
COST = "contracts/policy/cost_policy.toml"
SCENE = "contracts/entities/semantic_scene.schema.json"
GOVERNED = "contracts/policy/governed_surfaces.toml"


def _sub(old: str, new: str, count: int = 0):
    """Build a mutation that must actually change the text."""
    def apply(text: str) -> str:
        return text.replace(old, new) if count == 0 else text.replace(old, new, count)
    return apply


# (check-name, file, mutation, what the mutation represents)
CASES: list[tuple[str, str, object, str]] = [
    # ---------------------------------------------------------------- CI-026
    ("non-schedule-trigger-present", TRIGGERS,
     lambda t: t.replace('predicate_class = "COMPOSITE"', 'predicate_class = "SCHEDULE"')
                .replace('predicate_class = "STATE"', 'predicate_class = "SCHEDULE"')
                .replace('predicate_class = "EVENT"', 'predicate_class = "SCHEDULE"'),
     "the C1 cron build: every shipped trigger becomes SCHEDULE-class"),

    ("non-schedule-trigger-present", TRIGGERS,
     _sub('source = "REM-015 · owner requirement 2026-08-12 · SR-027, SR-044, SR-048"\n', '', 1),
     "a filler trigger: a row that names no requirement"),

    ("non-schedule-trigger-present", TRIGGERS,
     _sub('[triggers.trg_improvement_backlog]', '[triggers.trg_backlog_removed]', 1),
     "REM-015's backlog trigger quietly removed during cleanup"),

    # ------------------------------------------------------------------
    # SEMANTIC anti-cron cases, added 2026-08-12. The three cases above
    # mutate the LABEL or the row's existence. An independent probe showed
    # that replacing the PREDICATE BODY with a cron expression, leaving the
    # label at COMPOSITE, left CI-026 green and printing "8/8 enabled and
    # non-SCHEDULE". The check now parses the predicate; these cases are the
    # red runs that keep it parsing.
    # ------------------------------------------------------------------
    ("non-schedule-trigger-present", TRIGGERS,
     _sub("""predicate = \"\"\"
  world.system.operating_period in { IDLE, FREE_TIME }
  AND tasks.count(RUNNING) == 0
  AND world.owner.attention_state != focused
  AND backlog.count(state = LOGGED, staleness > staleness_floor) > 0
  AND schedule.elapsed_since(last_backlog_investigation) > idle_threshold
\"\"\"""",
          """predicate = \"\"\"
  schedule.cron("0 3 * * *")
\"\"\"""", 1),
     "PREDICATE BODY replaced with pure cron, label left COMPOSITE (the C1 build)"),

    ("non-schedule-trigger-present", TRIGGERS,
     _sub('  AND schedule.elapsed_since(last_backlog_investigation) > idle_threshold\n',
          '  OR schedule.elapsed_since(last_backlog_investigation) > idle_threshold\n', 1),
     "the clock term promoted from AND-guard to OR-disjunct (fires on the clock alone)"),

    ("non-schedule-trigger-present", TRIGGERS,
     lambda t: t.replace(
         '[triggers.trg_improvement_backlog]\nname = "Investigate a backlog idea during genuine idle"\nsource = "REM-015 · owner requirement 2026-08-12 · SR-027, SR-044, SR-048"\nenabled = true',
         '[triggers.trg_improvement_backlog]\nname = "Investigate a backlog idea during genuine idle"\nsource = "REM-015 · owner requirement 2026-08-12 · SR-027, SR-044, SR-048"\nenabled = false', 1),
     "the backlog trigger DISABLED rather than removed (quieter than deletion)"),

    ("non-schedule-trigger-present", TRIGGERS,
     _sub('  world.facts.any(valid_until_passed AND value != UNKNOWN)\n',
          '  ticker.every("30s")\n', 1),
     "a state predicate replaced by an invented clock namespace the vocabulary does not know"),

    ("non-schedule-trigger-present", TRIGGERS,
     _sub('[triggers.trg_fact_expiry_sweep]', '[triggers.trg_fact_expiry_DELETED]', 1),
     "a load-bearing STATE-class row deleted while the backlog row survives"),

    # ---------------------------------------------------------------- CI-030
    ("degradation-ladder-complete", LADDER,
     _sub('  { spatial_class = "none",           degraded = true,  action = "visual_to_narrative", rendering = "Spoken structural summary: nodes, edges, and the ONE relationship that matters", reason = "no visual modality" },\n', '', 1),
     "the diagram voice-only rung dropped"),

    ("degradation-ladder-complete", LADDER,
     _sub('action = "visual_to_narrative", rendering = "Spoken, prosody', 'action = "spoken_aloud", rendering = "Spoken, prosody', 1),
     "an action invented outside the scene schema's closed enum"),

    # ---------------------------------------------------------------- CI-046
    ("tunable-range-immutable", TUNABLES,
     _sub('[tunable.revisit_after]\nmin = 3600', '[tunable.revisit_after]\ncurrent = 99999\nmin = 3600', 1),
     "runtime state written into governed configuration (SPEC-26)"),

    ("tunable-range-immutable", TUNABLES,
     _sub('  "cost_class ceilings and every value in cost_policy.toml",\n', '', 1),
     "cost policy removed from the not-tunable list"),

    ("tunable-range-immutable", TUNABLES,
     _sub('max = 14400           # 4 hours\ndefault = 1200', 'max = 14400           # 4 hours\ndefault = 99999999', 1),
     "a default outside its own declared range"),

    # ---------------------------------------------------------------- CI-034
    ("measured-not-declared", CAPS,
     _sub('description = "SR-005 local fallback at capability_tier = small"\nmin_memory_gb = "UNKNOWN"',
          'description = "SR-005 local fallback at capability_tier = small"\nsustained_tokens_per_sec_min = 45\nmin_memory_gb = "UNKNOWN"', 1),
     "a throughput figure filled in from a datasheet while measured = false"),

    ("measured-not-declared", CAPS,
     _sub('[capability.identity_continuity]\nsurvival_core = true', '[capability.identity_continuity]\nsurvival_core = true\nrequires_always_on = true', 1),
     "a survival-core capability that needs an always-on node"),

    ("measured-not-declared", CAPS,
     _sub('unmeasured_disposition = "UNAVAILABLE"', 'unmeasured_disposition = "AVAILABLE"', 1),
     "unmeasured capabilities treated as available (a hardware assumption presented as fact)"),

    ("measured-not-declared", CAPS,
     _sub('[degradation_reporting]\nrequired = true', '[degradation_reporting]\nrequired = false', 1),
     "excluded capabilities no longer reported as degradations (INV-PLACE-3 clause 3)"),

    # ---------------------------------------------------------------- CI-031
    ("latency-budgets-declared", LATENCY,
     _sub('{ id = "plan",                budget_ms = 200', '{ id = "plan",                budget_ms = 600', 1),
     "stage budgets that no longer sum inside the end-to-end budget (AR-024 open)"),

    ("latency-budgets-declared", LATENCY,
     _sub('independent_of_total = true', 'independent_of_total = false', 1),
     "first-audio latency no longer asserted independently of total completion"),

    ("latency-budgets-declared", LATENCY,
     _sub('  "relax budget_ms",\n', '', 1),
     "relaxing a failed budget removed from the prohibited list"),

    # ---------------------------------------------------------------- CI-021
    ("cost-policy", COST,
     _sub('FREE_TIME       = ["free"]', 'FREE_TIME       = ["free", "paid"]', 1),
     "a paid cost class admitted during FREE_TIME"),

    # ---------------------------------------------------------------- CI-028
    ("scene-no-escape-hatch", SCENE,
     _sub('"schema_version": { "type": "integer", "minimum": 1 },',
          '"markdown": { "type": "string" },\n    "schema_version": { "type": "integer", "minimum": 1 },', 1),
     "a free-form markdown escape hatch added to the scene schema"),

    # ---------------------------------------------------------------- CI-016
    ("governed-surfaces-integrity", GOVERNED,
     _sub('paths = ["verification/", "tools/", "spec/", ".github/workflows/", "CODEOWNERS"]',
          'paths = ["tools/", "spec/", ".github/workflows/", "CODEOWNERS"]', 1),
     "surface 6 (the tests themselves) removed from GOVERNED_PATHS"),

    ("governed-surfaces-integrity", GOVERNED,
     _sub('paths = ["verification/", "tools/", "spec/", ".github/workflows/", "CODEOWNERS"]',
          'paths = ["v", "t", "s", ".github/workflows/", "CODEOWNERS"]', 1),
     "surface 6 degraded to string-prefix stubs that protect nothing"),

    ("governed-surfaces-integrity", GOVERNED,
     lambda t: t.replace('paths = ["contracts/policy/trigger_registry.toml", "autonomy/triggers/"]',
                         'paths = ["autonomy/triggers/"]', 1)
                .replace('paths = ["policy/", "contracts/policy/"]', 'paths = ["policy/"]', 1),
     "the shipped trigger registry left governed by nothing (S7 path drift + S1 narrowed)"),

    ("governed-surfaces-integrity", GOVERNED,
     _sub('paths = ["policy/", "contracts/policy/"]', 'paths = ["policy/", "contracts/policy/cost_policy.toml"]', 1),
     "S1 narrowed from the contracts/policy/ subtree to one file inside it"),

    ("governed-surfaces-integrity", GOVERNED,
     _sub('paths = ["verification/", "tools/", "spec/", ".github/workflows/", "CODEOWNERS"]',
          'paths = ["verification/", "tools/", ".github/workflows/", "CODEOWNERS"]', 1),
     "spec/ dropped: the invariants themselves left editable by the runtime"),
]


# --------------------------------------------------------------------------
# CREATE-cases: violations expressed by ADDING a file rather than editing one.
# Needed for the checks whose violation is "a file that should not exist" --
# notably CI-007, whose scan directories do not exist at all until production
# code does, so mutation has nothing to bite on.
#
# (check, relative path, contents, description)
# --------------------------------------------------------------------------
CREATE_CASES: list[tuple[str, str, str, str]] = [
    ("no-product-names", "routing/_selftest_probe.py",
     "# deliberate violation for tools/ci/self_test.py\nPREFERRED_NODE = 'MacBook Neo'\n",
     "a product name inside routing/ (INV-HW-1)"),
]

# --------------------------------------------------------------------------
# SCENARIO-cases: a violation that needs SEVERAL simultaneous changes, and an
# expected exit code that is sometimes 0.
#
# A gate proved only in the red direction has not been shown to key on the
# thing it claims to key on. CI-008 must fail when F0 code exists under an open
# ADR gate -- and it must PASS when the same code exists under a closed one, or
# all it has demonstrated is that it dislikes files.
#
# (check, [(path, contents)] to create, [(path, old, new)] to substitute,
#  expected exit code, description)
# --------------------------------------------------------------------------
ADR002 = "docs/ADR/ADR-002-persistence.md"
REGISTER = "docs/ADR/ADR-REGISTER.md"
_F0_PROBE = ("core/_selftest_probe.py", "# deliberate violation for tools/ci/self_test.py\n")
_ACCEPT_ADR002_FILE = (ADR002, "| **Status** | **PROPOSED**", "| **Status** | **ACCEPTED**")
_ACCEPT_ADR002_REG = (REGISTER, "| **ADR-002** | Persistence engine: task state, memory, provenance, migration and recovery | **PROPOSED** |",
                      "| **ADR-002** | Persistence engine: task state, memory, provenance, migration and recovery | **ACCEPTED** |")

SCENARIO_CASES: list[tuple[str, list[tuple[str, str]], list[tuple[str, str, str]], int, str]] = [
    ("adr-gate", [_F0_PROBE], [], 1,
     "CI-008: F0 code under core/ while ADR-002 is PROPOSED"),

    ("adr-gate", [_F0_PROBE], [_ACCEPT_ADR002_FILE], 1,
     "CI-008: the ADR record flipped to ACCEPTED while the register still says PROPOSED"),

    ("adr-gate", [_F0_PROBE], [_ACCEPT_ADR002_FILE, _ACCEPT_ADR002_REG], 0,
     "CI-008 DISCRIMINATION: the same F0 code passes once ADR-002 is genuinely ACCEPTED"),

    ("adr-gate", [], [(ADR002, "| **Status** | **PROPOSED**", "| **Status** | **WITHDRAWN**")], 1,
     "CI-008: an ADR status outside the decision vocabulary"),
]

# --------------------------------------------------------------------------
# LINT-cases: checks implemented by a linter rather than by checks.py.
# (command argv, relative path, mutation, description)
# --------------------------------------------------------------------------
LINT_CASES: list[tuple[list[str], str, object, str]] = [
    (["tools/traceability_lint.py"], "verification/traceability/registry.toml",
     _sub('[requirements.SR-001]', '[requirements.SR_REMOVED_001]', 1),
     "CI-003: an SR defined in the COC with no registry row"),

    (["tools/traceability_lint.py"], "verification/traceability/registry.toml",
     _sub('status = "R_AND_D"\nnote = "Source says', 'status = "R_AND_D"\nnnote = "Source says', 1),
     "CI-038: a terminal status with no Part XIV.3 limitation note"),

    (["tools/traceability_lint.py"], "verification/acceptance/INDEX.toml",
     _sub('negative_control = "A build that re-initialises identity on restart', 'nnegative_control = "A build that re-initialises identity on restart', 1),
     "TR-064: a test naming neither a negative control nor a rationale"),

    # TR-068 content coupling. TR-062 checked only that the named file EXISTS,
    # so A-029 -- the anti-cron discriminator -- could be repointed at a file
    # that never mentions it and traceability stayed PASS with 0 errors.
    (["tools/traceability_lint.py"], "verification/acceptance/INDEX.toml",
     lambda t: t.replace(
         'title = "Zero-input autonomy three-part gate incl. the anti-cron discriminator (NV-03)"\nspec = "verification/acceptance/AT-03-autonomy-and-cost.md"',
         'title = "Zero-input autonomy three-part gate incl. the anti-cron discriminator (NV-03)"\nspec = "verification/acceptance/AT-04-presence-and-perception.md"', 1),
     "TR-068: A-029's spec pointer repointed to an unrelated acceptance file"),

    # TR-029 guards HAND EDITS: the patch script that created the dispositions
    # always wrote both fields together, so without this case the branch would
    # never have been executed. An untested branch in a linter whose purpose is
    # catching untested branches is not acceptable.
    (["tools/traceability_lint.py"], "verification/traceability/registry.toml",
     _sub('depth_note = "A dedicated-network contract', 'ddepth_note = "A dedicated-network contract', 1),
     "TR-029: a depth_disposition with the depth_note removed"),

    (["tools/ci/checks.py", "ci-registry"], "spec/invariants/INVARIANTS.toml",
     _sub('[invariants.INV-COORD-1]\nstatement', '[invariants.INV-SELFTEST-WISH]\nstatement = "a wish"\nowner_rem = "REM-001"\nenforced_by = []\nkind = "runtime"\n\n[invariants.INV-COORD-1]\nstatement', 1),
     "CI-041: an invariant with an empty enforced_by -- a wish, not an invariant"),

    (["tools/ci/checks.py", "ci-registry"], "verification/ci/CHECKS.toml",
     _sub('[checks.CI-003]\nname = "traceability-lint"', '[checks.CI-999]\nname = "no-self-test-declared"\nenforces = ["INV-TRACE-1"]\nkind = "process"\nimpl = "PENDING"\nblocking = "pr"\n\n[checks.CI-003]\nname = "traceability-lint"', 1),
     "CI-043: a check registered with no self_test field"),

    # CI-041 bidirectional half. Until 2026-08-12 the registry was linted in one
    # direction only, and four false enforcement records survived it -- one on a
    # ratified security clause, pointing at an implemented, passing check.
    (["tools/ci/checks.py", "ci-registry"], "verification/ci/CHECKS.toml",
     _sub('[checks.CI-028]\nname = "scene-no-escape-hatch"\nenforces = ["INV-SCENE-3"]',
          '[checks.CI-028]\nname = "scene-no-escape-hatch"\nenforces = ["INV-SCENE-3", "INV-STOP-1"]', 1),
     "CI-041: a check claiming an invariant that does not name it back"),

    (["tools/ci/checks.py", "ci-registry"], "spec/invariants/INVARIANTS.toml",
     _sub('[invariants.INV-SCENE-3]', '[invariants.INV-SCENE-3]\nfalse_claim_probe = 0', 1)
     if False else
     lambda t: t.replace('enforced_by = ["CI-044", "A-030"]', 'enforced_by = ["CI-028", "A-030"]', 1),
     "CI-041: an invariant claiming enforcement by a check that does not perform it"),

    # CI-041 red-run coverage half. Mark a check implemented, forget the harness
    # case, and the registry used to stay green -- the "checks that only verify
    # their own existence" antipattern.
    (["tools/ci/checks.py", "ci-registry"], "verification/ci/CHECKS.toml",
     _sub('[checks.CI-025]\nname = "action-has-trigger"\nenforces = ["INV-TRIG-1"]\nkind = "structural"\nimpl = "PENDING"',
          '[checks.CI-025]\nname = "action-has-trigger"\nenforces = ["INV-TRIG-1"]\nkind = "structural"\nimpl = "tools/ci/checks.py action-has-trigger"', 1),
     "CI-041: a check marked implemented with no executed red run"),

]

# ------------------------------------------------------------------- CI-050
# reference_lint declares its own cases. They are IMPORTED rather than restated
# so that `implemented => red-run` is computable from one source, and so that
# this file contains no literal dangling path (reference_lint now scans tools/
# including itself, and a restated probe token would make it permanently red).
sys.path.insert(0, str(REPO / "tools"))
import reference_lint  # noqa: E402

LINT_CASES += [
    (["tools/reference_lint.py"], rel, _sub(old, new, 1), f"CI-050: {desc}")
    for rel, old, new, desc in reference_lint.SELF_TEST_CASES
]


def run_check(name: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "ci" / "checks.py"), name],
        capture_output=True, text=True, cwd=REPO,
    )
    return p.returncode, p.stdout + p.stderr


def run_argv(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(REPO / argv[0]), *argv[1:]],
        capture_output=True, text=True, cwd=REPO,
    )
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cases = [c for c in CASES if only is None or c[0] == only]
    if not cases and not any(
        c[0] == only for c in list(CREATE_CASES) + [(s[0],) for s in SCENARIO_CASES]
    ):
        print(f"no self-test cases for {only!r}")
        return 1

    failures = 0
    print(f"{'CHECK':32} {'DELIBERATE VIOLATION':66} {'RED':>5} {'GREEN':>6}")
    print("-" * 113)

    for check, rel, mutate, desc in cases:
        path = REPO / rel
        original, raw, crlf = read(path)
        before = digest(path)
        mutated = mutate(original)
        if mutated == original:
            print(f"{check:32} {desc:66} {'N/A':>5} {'--':>6}")
            print(f"    FAILURE: the mutation did not apply to {rel}. The artifact has changed shape "
                  f"and this self-test is no longer testing anything.")
            failures += 1
            continue
        try:
            write_mutated(path, mutated, crlf)
            rc_red, out_red = run_check(check)
        finally:
            restore(path, raw)
        if digest(path) != before:
            failures += 1
            print(f"    FAILURE: {rel} was not restored byte-for-byte.")
        rc_green, out_green = run_check(check)

        red_ok, green_ok = rc_red == 1, rc_green == 0
        print(f"{check:32} {desc:66} {('exit1' if red_ok else f'exit{rc_red}'):>5} "
              f"{('exit0' if green_ok else f'exit{rc_green}'):>6}")
        if not red_ok:
            failures += 1
            print(f"    FAILURE: the check did not fail on a deliberate violation. It is not evidence.")
            for line in out_red.splitlines()[:8]:
                print("      " + line)
        if not green_ok:
            failures += 1
            print(f"    FAILURE: the check did not return green after restore.")
            for line in out_green.splitlines()[:8]:
                print("      " + line)

    # ---------------------------------------------------------- create-cases
    create = [c for c in CREATE_CASES if only is None or c[0] == only]
    for check, rel, contents, desc in create:
        path = REPO / rel
        existed = path.exists()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents.encode("utf-8"))
            rc_red, out_red = run_check(check)
        finally:
            if not existed and path.exists():
                path.unlink()
            # Remove the directory only if this harness created it and it is now empty.
            try:
                path.parent.rmdir()
            except OSError:
                pass
        rc_green, _ = run_check(check)
        red_ok, green_ok = rc_red == 1, rc_green == 0
        print(f"{check:32} {desc:66} {('exit1' if red_ok else f'exit{rc_red}'):>5} "
              f"{('exit0' if green_ok else f'exit{rc_green}'):>6}")
        if not red_ok:
            failures += 1
            print("    FAILURE: the check did not fail on a deliberately planted violation.")
            for line in out_red.splitlines()[:6]:
                print("      " + line)
        if not green_ok:
            failures += 1
            print("    FAILURE: the check did not return green after cleanup.")

    # -------------------------------------------------------- scenario-cases
    scenarios = [c for c in SCENARIO_CASES if only is None or c[0] == only]
    for check, creates, subs, want_rc, desc in scenarios:
        created: list[Path] = []
        saved: list[tuple[Path, bytes]] = []
        applied = True
        try:
            for rel, contents in creates:
                path = REPO / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents.encode("utf-8"))
                created.append(path)
            for rel, old, new in subs:
                path = REPO / rel
                text, raw, crlf = read(path)
                saved.append((path, raw))
                if old not in text:
                    applied = False
                    print(f"{check:32} {desc:66} {'N/A':>5} {'--':>6}")
                    print(f"    FAILURE: substitution target absent in {rel}; this case tests nothing.")
                    failures += 1
                    break
                write_mutated(path, text.replace(old, new, 1), crlf)
            if applied:
                rc, out = run_check(check)
        finally:
            for path, raw in saved:
                restore(path, raw)
            for path in created:
                if path.exists():
                    path.unlink()
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
        if not applied:
            continue
        ok = rc == want_rc
        rc_after, _ = run_check(check)
        clean = rc_after == 0
        print(f"{check:32} {desc:66} {('exit' + str(rc)):>5} {('exit0' if clean else f'exit{rc_after}'):>6}")
        if not ok:
            failures += 1
            print(f"    FAILURE: expected exit {want_rc}, got exit {rc}. The gate does not key on what it claims to.")
            for line in out.splitlines()[:8]:
                print("      " + line)
        if not clean:
            failures += 1
            print("    FAILURE: the check did not return green after restore.")

    # ------------------------------------------------------------ lint-cases
    lints = [] if only else LINT_CASES
    for argv, rel, mutate, desc in lints:
        label = argv[0].split("/")[-1].replace(".py", "")
        path = REPO / rel
        original, raw, crlf = read(path)
        before = digest(path)
        mutated = mutate(original)
        if mutated == original:
            print(f"{label:32} {desc:66} {'N/A':>5} {'--':>6}")
            print(f"    FAILURE: the mutation did not apply to {rel}.")
            failures += 1
            continue
        try:
            write_mutated(path, mutated, crlf)
            rc_red, out_red = run_argv(argv)
        finally:
            restore(path, raw)
        if digest(path) != before:
            failures += 1
            print(f"    FAILURE: {rel} was not restored byte-for-byte.")
        rc_green, _ = run_argv(argv)
        red_ok, green_ok = rc_red == 1, rc_green == 0
        print(f"{label:32} {desc:66} {('exit1' if red_ok else f'exit{rc_red}'):>5} "
              f"{('exit0' if green_ok else f'exit{rc_green}'):>6}")
        if not red_ok:
            failures += 1
            print("    FAILURE: the linter did not fail on a deliberate violation.")
            for line in out_red.splitlines()[:8]:
                print("      " + line)
        if not green_ok:
            failures += 1
            print("    FAILURE: the linter did not return green after restore.")

    total = len(cases) + len(create) + len(scenarios) + len(lints)
    print("-" * 113)
    passed = total - failures
    print(f"{passed}/{total} self-tests behaved correctly (red under violation, green after restore)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
