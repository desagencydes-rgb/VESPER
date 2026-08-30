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
import itertools
import os
import time
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


# A counter, not a clock. See _bump_mtime.
_MTIME_TICK = itertools.count(1)


def _bump_mtime(path: Path) -> None:
    """Force the source's mtime to a value no .pyc can already be holding.

    FOUND 2026-08-21, landing CI-057. CPython validates cached bytecode against
    the source's (mtime, size) and stores that mtime WITH ONE-SECOND GRANULARITY.
    A mutation that preserves byte length -- inverting a comparison, say, which is
    exactly what a self-test case wants to do -- and lands in the same second as
    the preceding restore is therefore INVISIBLE: the subprocess revalidates the
    stale .pyc and imports the UNMUTATED module. The check goes green on a real
    violation and the harness reports "not evidence" against a check that is fine.

    This bit only runtime-fixture checks, which import repo modules; the file-
    reading checks that make up most of this suite never noticed. It would have
    bitten every future runtime-fixture check silently.

    Stepping the mtime by a whole second per write is enough and is cheaper than
    deleting bytecode trees or recompiling the world with PYTHONPYCACHEPREFIX.
    """
    t = time.time() + next(_MTIME_TICK)
    os.utime(path, (t, t))


def write_mutated(path: Path, text: str, crlf: bool) -> None:
    """Write the transient mutated state in the file's own newline convention."""
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))
    _bump_mtime(path)

def restore(path: Path, raw: bytes) -> None:
    """Restore the ORIGINAL BYTES. Never write_text -- see BYTE SAFETY above.

    AND DISCARD THE BYTECODE, which byte-exactness alone does not do.

    Found 2026-08-19 by a negative control on the fabric harness. CPython
    validates a cached .pyc against the source's (mtime, size). A mutation that
    preserves LENGTH -- `max` -> `min`, or inverting the values in
    TRUST_ZONE_RANK, both of which are real cases in this file -- changes
    neither, and when mutate-and-restore complete inside one filesystem mtime
    tick the interpreter keeps serving bytecode compiled from the MUTATED
    source while the file on disk is provably correct. sha256 of the source
    matched, `diff` was empty, and the module still computed the violation.

    That is the `spd-say` lesson in a new place: the restore's own report of
    success is not the state of the world. It cost twenty minutes of believing
    a correct file was wrong, and the same trap silently arms any check that
    IMPORTS a mutated module rather than reading it as text -- today that is
    every acceptance runner under verification/, since self_test mutates
    core/autonomy.py, core/bus.py, core/interlock.py and core/fabric.py.
    """
    path.write_bytes(raw)
    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for stale in cache.glob(f"{path.stem}.*.pyc"):
            stale.unlink(missing_ok=True)
    _bump_mtime(path)

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
    ("glass-hatch-contained", "app/home-macos/_selftest_glass_hatch.swift",
     "// deliberate violation for tools/ci/self_test.py -- no glass-hatch marker\n"
     "func selftestHatch(_ web: AnyObject) {\n"
     "    web.setValue(false, forKey: \"drawsBackground\")\n"
     "}\n",
     "a second copy of the private WKWebView background hatch, unmarked (INV-HOME-5)"),
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

# ==========================================================================
# Red runs for the four checks implemented 2026-08-18. Each mutation is the
# deliberate violation CHECKS.toml declares for that check -- a declared
# self-test string is not a red run, and the difference is the whole reason
# this harness exists.
# ==========================================================================

MODEL_PROFILE = "contracts/entities/model_profile.schema.json"
IDEA = "contracts/entities/improvement_idea.schema.json"
TASK = "contracts/entities/task.schema.json"
AUTONOMY = "core/autonomy.py"

CASES += [
    # ---------------------------------------------------------------- CI-022
    ("cost-class-nonnull", MODEL_PROFILE,
     _sub('"required": ["profile_id", "schema_version", "cost_class", '
          '"locality", "capability_tier", "min_node_profile"]',
          '"required": ["profile_id", "schema_version", '
          '"locality", "capability_tier", "min_node_profile"]', 1),
     "a model profile fixture with no cost_class: the field leaves `required`"),

    ("cost-class-nonnull", MODEL_PROFILE,
     _sub('"cost_class": {\n      "enum"',
          '"cost_class": {\n      "default": "free",\n      "enum"', 1),
     "a default cost class -- the silent classification INV-COST-4 forbids"),

    # ---------------------------------------------------------------- CI-047
    ("idea-retirement-reason", IDEA,
     _sub('"$comment": "INV-IDEA-4 -- nothing leaves the backlog silently.",\n'
          '      "if": {\n        "properties": {\n          "status": {\n'
          '            "const": "RETIRED"',
          '"$comment": "INV-IDEA-4 -- nothing leaves the backlog silently.",\n'
          '      "if": {\n        "properties": {\n          "status": {\n'
          '            "const": "MERGED"', 1),
     "the RETIRED clause quietly rebound to another state, leaving retirement "
     "reasonless while the description still claims MANDATORY"),

    # ---------------------------------------------------------------- CI-032
    ("verification-criteria-typed", TASK,
     _sub('"$ref": "https://vesper.local/contracts/entities/'
          'verification_strategy.schema.json"',
          '"type": "string"', 1),
     "verification_criteria as free text -- RB-004's machine-checkable "
     "acceptance condition becomes a sentence"),

    # ---------------------------------------------------------------- CI-025
    ("action-has-trigger", AUTONOMY,
     _sub('noop = {"trigger_id": t.trigger_id, "tick": self.ticks,',
          'noop = {"tick": self.ticks,', 1),
     "a recorded no-op that drops its trigger_id, so a quiet night and a dead "
     "loop become indistinguishable (INV-TRIG-6)"),
]


INTERLOCK = "core/interlock.py"

CASES += [
    # ---------------------------------------------------------------- CI-019
    ("interlock-independence", INTERLOCK,
     _sub("from .bus import EventBus",
          "from .bus import EventBus\nfrom .lease import LeaseManager", 1),
     "the stop path taking a lease dependency -- a stop that needs ownership "
     "cannot happen during the partition you most want to stop in"),

    # ---------------------------------------------------------------- CI-023
    ("evaluator-no-model-capability", AUTONOMY,
     _sub("from .bus import EventBus",
          "from .bus import EventBus\nfrom .gateway import ModelGateway", 1),
     "the evaluator importing the model gateway -- 'is there anything worth "
     "doing?' asked of a model is a chatbot talking to itself"),

    ("evaluator-no-model-capability", AUTONOMY,
     _sub('        raise ModelCallInDecisionPath(\n'
          '            f"a model call was attempted inside {where}; the '
          'evaluator has no "\n'
          '            "model path by construction and this call is refused")',
          "        return None", 1),
     "a build that emits its own violation and carries on -- A-011.4 requires "
     "the attempt to be raised, not merely logged"),
]

BUS = "core/bus.py"

CASES += [
    # ---------------------------------------------------------------- CI-005
    # The registry's declared self-test, verbatim: "Sort a collection by
    # observed_at_wall without a WALL-CLOCK-OK annotation." bus.py is where it
    # belongs -- its own header claims observed_at_wall is "structurally
    # excluded from every ordering path in this file", and a claim in a
    # docstring is exactly the kind that stops being true quietly.
    ("no-wall-clock-ordering", BUS,
     _sub("    observed_at_wall: str",
          "    observed_at_wall: str\n\n"
          "    def _replay_order(self, events):\n"
          "        return sorted(events, key=lambda e: e.observed_at_wall)", 1),
     "replay ordered by observed_at_wall -- two nodes a second apart would "
     "silently disagree about which write won, and the loser is discarded "
     "with nobody told"),

    ("no-wall-clock-ordering", BUS,
     _sub("    observed_at_wall: str",
          "    observed_at_wall: str\n\n"
          "    def supersedes(self, other):\n"
          "        return self.observed_at_wall > other.observed_at_wall", 1),
     "supersession decided by comparing two wall clocks -- the shape "
     "INV-COORD-4 refuses, as distinct from asking whether a moment "
     "has arrived"),
]

REGISTER = "docs/ADR/ADR-REGISTER.md"
_F0_PROBE = ("core/_selftest_probe.py", "# deliberate violation for tools/ci/self_test.py\n")

# THE DIRECTION OF THESE CASES INVERTED ON 2026-08-14, and the reason is worth
# keeping: the owner ACCEPTED ADR-002, and these cases had been written to
# borrow the tree's then-current PROPOSED status as their premise. The moment
# the real decision changed, the premise went false and the suite failed --
# reporting "the gate does not key on what it claims to" about a gate that was
# working correctly.
#
# The lesson is not "update the strings". It is that A SELF-TEST MUST CONSTRUCT
# BOTH HALVES OF ITS OWN PRECONDITION rather than depend on the state of the
# tree it runs against, because the tree is exactly the thing that changes.
# These cases now build the blocked state themselves, and the discriminating
# case reads the tree's genuine ACCEPTED status instead of manufacturing it --
# which makes it a stronger control than the version it replaces.
_PROPOSE_ADR002_FILE = (ADR002, "| **Status** | **ACCEPTED**", "| **Status** | **PROPOSED**")
_PROPOSE_ADR002_REG = (
    REGISTER,
    "| **ADR-002** | Persistence engine: task state, memory, provenance, migration and recovery | **ACCEPTED** 2026-08-14 |",
    "| **ADR-002** | Persistence engine: task state, memory, provenance, migration and recovery | **PROPOSED** |")

SCENARIO_CASES: list[tuple[str, list[tuple[str, str]], list[tuple[str, str, str]], int, str]] = [
    # RED. Both record and register pushed back to PROPOSED, so the gate is
    # genuinely closed, and F0 code under core/ must be blocked.
    ("adr-gate", [_F0_PROBE], [_PROPOSE_ADR002_FILE, _PROPOSE_ADR002_REG], 1,
     "CI-008: F0 code under core/ while ADR-002 is PROPOSED"),

    # DISCRIMINATION, and the direction that matters most. The SAME probe file,
    # with NO substitution at all, must PASS -- because ADR-002 is genuinely
    # ACCEPTED in this tree. Without this the suite would only have shown that
    # the gate dislikes files under core/, not that it keys on the decision.
    ("adr-gate", [_F0_PROBE], [], 0,
     "CI-008 DISCRIMINATION: the same F0 code passes because ADR-002 is genuinely ACCEPTED"),

    # DIVERGENCE. Record and register disagreeing must fail on its own, with no
    # probe file present -- a gate reading two sources cannot be trusted while
    # they contradict each other, regardless of what is under core/.
    ("adr-gate", [], [_PROPOSE_ADR002_FILE], 1,
     "CI-008: the record says PROPOSED while the register still says ACCEPTED"),

    ("adr-gate", [], [(ADR002, "| **Status** | **ACCEPTED**", "| **Status** | **WITHDRAWN**")], 1,
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
    #
    # REPOINTED 2026-08-19, and the reason is the harness's own standing lesson
    # a few hundred lines up. This case used to key on SR-016's depth_note --
    # "A dedicated-network contract..." -- and SR-016 was raised to SPECIFIED
    # that day, which deleted the string the case depended on. The case then
    # reported "the mutation did not apply", i.e. it correctly announced that it
    # had stopped testing anything, which is the behaviour that makes this
    # harness worth having.
    #
    # It now keys on SR-034, chosen because SR-034 is the ONE row the corpus
    # holds below SPECIFIED deliberately and permanently -- its own note calls
    # it "the worked example of the discriminator". Anchoring a self-test to the
    # requirement designed never to move is the closest thing available to
    # constructing its own precondition without inventing an SR id the COC does
    # not contain, which would fail a different rule first and go red for the
    # wrong reason.
    (["tools/traceability_lint.py"], "verification/traceability/registry.toml",
     _sub('depth_note = "Shares SR-023\'s Artifact type.', 'ddepth_note = "Shares SR-023\'s Artifact type.', 1),
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
    # Repointed from CI-025 to CI-004 on 2026-08-18, because CI-025 was
    # implemented that day and the mutation stopped applying -- which the
    # harness reported as "the mutation did not apply", exactly as it should.
    # A self-test that silently stops testing is worse than none, so the
    # subject moves to a check that is still PENDING rather than the case
    # being quietly dropped.
    (["tools/ci/checks.py", "ci-registry"], "verification/ci/CHECKS.toml",
     _sub('[checks.CI-004]\nname = "bus-consumer-idempotency"\nenforces = ["INV-COORD-5"]\nkind = "structural"\nimpl = "PENDING"',
          '[checks.CI-004]\nname = "bus-consumer-idempotency"\nenforces = ["INV-COORD-5"]\nkind = "structural"\nimpl = "tools/ci/checks.py bus-consumer-idempotency"', 1),
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


# ---------------------------------------------------------------- CI-057
# The runtime half of INV-HW-2. Each case is a way a surface starts showing a
# number nobody measured -- and the third is the one drawn in the owner's own
# reference: an empty column filled with a plausible value because it looked
# wrong empty.
PROJECTION = "core/projection.py"

CASES += [
    ("projection-unknown-absent", PROJECTION,
     _sub("        if has_value and self.observed_at is None:", "        if False:", 1),
     "the provenance guard removed: a value may be constructed with no observation time"),

    ("projection-unknown-absent", PROJECTION,
     _sub("        has_value = self.value is not None", "        has_value = bool(self.value)", 1),
     "an `is None` test replaced by truthiness: a genuine reading of 0 becomes UNKNOWN"),

    ("projection-unknown-absent", PROJECTION,
     _sub("            if not r.known:\n                continue\n",
          "            if not r.known:\n"
          "                r = Reading(key=r.key, source=r.source, value=0,\n"
          "                            observed_at=self.version)\n", 1),
     "the empty column filled in: an unavailable reading rendered as 0 rather than omitted"),

    ("projection-unknown-absent", PROJECTION,
     _sub("        return other.version < self.version",
          "        return self.version < other.version", 1),
     "supersedes inverted: an older projection wins, and INV-COORD-4's ordering is lost"),
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


# --------------------------------------------------------------------------
# CI-055 -- the network fabric. Eight cases, chosen so each is a plausible
# EDIT rather than an obvious sabotage: every mutation below reads like a
# reasonable relaxation in a diff, which is the only kind that actually ships.
# --------------------------------------------------------------------------
HOST_ACTIONS = "contracts/policy/host_actions.toml"
FABRIC = "contracts/policy/network_fabric.toml"
FABRIC_IMPL = "core/fabric.py"


def _elevate_uncontrolled(text: str) -> str:
    """Raise the ceiling on the UNCONTROLLED segment only.

    Written as a function rather than a _sub because it must bite on
    shared_household specifically -- a blind replace would also move the
    dedicated segment and the case would stop being about elevation.
    """
    head, sep, tail = text.partition("[segment.shared_household]")
    if not sep:
        return text
    return head + sep + tail.replace('trust_zone_ceiling = "Z2"',
                                     'trust_zone_ceiling = "Z0"', 1)



# ---------------------------------------------------------------------- CI-056
#
# The first case is the one this check exists for. Enabling an above-the-line
# row is a single word in a diff, reads as configuration, and hands VESPER the
# ability to change a machine the owner said it may only report on. Everything
# else here is a way the vocabulary can claim a safety property it does not
# have.
CASES += [
    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('tier = "adjust_reversible"\nenabled = false', 'tier = "adjust_reversible"\nenabled = true', 1),
     "an above-the-read-line action enabled -- owner policy is that VESPER "
     "reports a change and the owner applies it; this is the one-word edit that "
     "silently reverses that and looks like configuration"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub("fail_closed = true", "fail_closed = false", 1),
     "the vocabulary made permit-unless-forbidden -- the permitted set becomes "
     "unbounded and no audit can enumerate what the system may do"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('action_provenance_required = "verified_local"',
          'action_provenance_required = "model_generated"', 1),
     "host actions allowed to run on model-generated belief -- VESPER reads "
     "somewhere that stopping some process is safe, believes it, and does it here"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('inverse = "restore_process_scheduling"', 'inverse = "unpin_process"', 1),
     "a claimed undo that is not in the vocabulary -- the row advertises "
     "reversibility the system cannot deliver, discovered mid-incident"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub("restores_baseline = true\ntier = \"adjust_reversible\"",
          "tier = \"adjust_reversible\"", 1),
     "the undo flag dropped from a restore row -- the cap rule loses its "
     "direction and stops noticing an undo scarcer than what it undoes"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('max_targets_per_window = 32', 'max_targets_per_window = 1', 1),
     "the undo capped below the action it reverses -- both rows look "
     "responsibly bounded and the system can enter a state it cannot leave"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('reversible = false\ninverse = ""\nrequires_owner_consent = "per_instance"',
          'reversible = false\ninverse = ""\nrequires_owner_consent = "per_rule"', 1),
     "the only irreversible action downgraded from per-instance to per-rule "
     "consent -- one approval then covers every future firing"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('non_mutating_tiers = ["observe", "advise"]', 'non_mutating_tiers = []', 1),
     "the non-mutating tier list emptied -- every read is then treated as a "
     "mutation and asked for an undo it cannot have"),

    ("host-action-vocabulary", HOST_ACTIONS,
     _sub('source = "SR-060 · placement needs the node\'s live condition, not its declared one"',
          'source = ""', 1),
     "an action with no source -- a row invented to keep the check green is "
     "visible only by having nothing that asked for it"),
]

CASES += [
    ("fabric-segment-declared", FABRIC,
     _sub('unlisted_segment_disposition = "UNREACHABLE"',
          'unlisted_segment_disposition = "REACHABLE"', 1),
     "the fabric made fail-open -- a node on an uncharacterised path becomes "
     "reachable, which is the one default an attacker would also choose"),

    ("fabric-segment-declared", FABRIC, _elevate_uncontrolled,
     "an uncontrolled segment given a Z0 ceiling -- HOST_ZONES is (Z0, Z1), so "
     "this silently restores full-host eligibility on the path VESPER controls "
     "least. INV-NET-2 makes a segment a CEILING; this inverts it"),

    ("fabric-segment-declared", FABRIC,
     _sub('administrative_control_scope = "vesper_owned_only"',
          'administrative_control_scope = "all_nodes"', 1),
     "administrative control widened to every node on the segment -- SR-016's "
     "grant kept and its bound dropped"),

    ("fabric-segment-declared", FABRIC,
     _sub("control_traffic_reserved = true", "control_traffic_reserved = false", 1),
     "the control-traffic reservation removed -- A-045's no-starvation "
     "assertion left with nothing behind it"),

    ("fabric-segment-declared", FABRIC,
     _sub("[traffic.control]\nreserved_share = 0.2\nstarvable = false",
          "[traffic.control]\nreserved_share = 0.2\nstarvable = true", 1),
     "control traffic marked starvable while still carrying a reserved share "
     "-- the two fields disagreeing is how a reservation becomes advisory"),

    ("fabric-segment-declared", FABRIC,
     _sub("user_owned_preemptible = false", "user_owned_preemptible = true", 1),
     "the user's own devices made preemptible -- 'usable normally' quietly "
     "redefined as 'usable when VESPER is idle'"),

    ("fabric-segment-declared", FABRIC,
     _sub("carries_control_plane = false\n\n[segment.untrusted_external]",
          "carries_control_plane = true\n\n[segment.untrusted_external]", 1),
     "the control plane run over a segment VESPER does not control"),

    ("fabric-segment-declared", FABRIC_IMPL,
     _sub('TRUST_ZONE_RANK = {"Z0": 0, "Z1": 1, "Z2": 2, "Z3": 3}',
          'TRUST_ZONE_RANK = {"Z0": 3, "Z1": 2, "Z2": 1, "Z3": 0}', 1),
     "zone ranks inverted in the fabric only -- admission and placement now "
     "disagree about which zone is stronger, and every test that merely checks "
     "'a ceiling was applied' still passes"),
]


# ---------------------------------------------------------------- CI-059/060
#
# The gateway wired to the quota ledger and the effort floor. Every mutation
# here is a PLAUSIBLE EDIT rather than a sabotage, and three of them are edits
# somebody would make while tidying: `content.strip()` looks redundant next to
# an `is not None`, a caller-supplied `reasoning_effort` looks like something a
# caller should be allowed to set, and a refund inside a retry loop looks like
# an off-by-one. Each one restores a defect that was MEASURED against a live
# provider on 2026-08-25 and that no gate could see before these checks existed.
GATEWAY = "core/gateway.py"
HTTP_COMPLETION = REPO / "routing" / "http_completion.py"
NARRATION = "core/narration.py"
NARRATION_TOML = "contracts/policy/narration.toml"
CHROME_TPL = "app/home-macos/chrome/home.html"
CHROME_SW = "app/home-macos/HomeChrome.swift"
HOME_STATE = "core/home_state.py"
INTAKE = "core/intake.py"
QUOTA_PY = "core/quota.py"
TRIAGE = "core/triage.py"
REPAIR = "core/repair.py"
EFFORT = "core/effort.py"
PERSONA_PY = "core/persona.py"
WORKBENCH = "core/workbench.py"
BEHAVIOUR_SW = "app/island-macos/Behaviour.swift"
HOME_SW = "app/home-macos/Home.swift"
PERSONA_TOML = "contracts/policy/persona.toml"
VOICE_TOML = "contracts/policy/voice.toml"
DIFFICULTY = "core/difficulty.py"
BARGE_IN = "core/barge_in.py"
BASELINE = "core/baseline.py"
MEMORY_PY = "core/memory.py"
REDACT_PY = "core/redact.py"
UPDATER_PY = "core/updater.py"
BLOCKS_PY = "core/blocks.py"
ARBITER_PY = "core/arbiter.py"
FORGETTER_PY = "core/forgetter.py"
COMPACTOR_PY = "core/compactor.py"
CHOOSER_PY = "core/chooser.py"
SENSORS_PY = "core/sensors.py"
HOST_PROBES_PY = "core/host_probes.py"
FLOOR_PY = "core/floor.py"
GATEWAY_PY = "core/gateway.py"
ROUTER = "core/router.py"
LATENCY = "core/latency.py"
SUPPLY_PY = "routing/supply.py"
RUNTIME = "tools/ops/vesper_runtime.py"

CASES += [
    # ---------------------------------------------------------------- CI-083
    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("            v = Verdict(floor=verdict.value, text=text, acted=False,\n"
          "                        answer=False, queued=False)\n"
          "        elif verdict is Floor.STATUS:",
          "            v = Verdict(floor=verdict.value, text=text, acted=False,\n"
          "                        answer=True, queued=False)\n"
          "        elif verdict is Floor.STATUS:", 1),
     "a cooperative interruption gets answered: 'take your time' met with a "
     "reply is VESPER interrupting the owner's permission not to be "
     "interrupted, and it takes the floor they just declined to take"),

    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("        if verdict is Floor.BREAK:\n"
          "            with self._lock:\n"
          "                self.broken = True\n"
          "                self._held = False",
          "        if verdict is Floor.BREAK:\n"
          "            with self._lock:\n"
          "                self.broken = False", 1),
     "a halt no longer releases the floor or records the break, so 'stop' is "
     "classified correctly and changes nothing -- a system that cannot be "
     "stopped is one nobody will leave running"),

    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("            queued, self._queue = list(self._queue), []",
          "            queued, self._queue = [], self._queue", 1),
     "the queue is emptied without being delivered: from where the owner is "
     "standing that is identical to having been swallowed, and they learn that "
     "speaking during a hold loses what they said"),

    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("            queued, self._queue = list(self._queue), []",
          "            queued = list(self._queue)", 1),
     "release() returns the queue without clearing it, so a caller that "
     "releases twice replays the owner's words as new requests"),

    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("            if not self._held:\n                raise Held(",
          "            if False:\n                raise Held(", 1),
     "an utterance outside a hold is classified as a barge-in, routing ordinary "
     "speech through a table that only knows how to stop work"),

    ("floor-never-swallows-or-drops", FLOOR_PY,
     _sub("            v = Verdict(floor=verdict.value, text=text, acted=False,\n"
          "                        answer=True, queued=False)\n"
          "        else:",
          "            v = Verdict(floor=verdict.value, text=text, acted=True,\n"
          "                        answer=True, queued=False)\n"
          "            with self._lock:\n"
          "                self._held = False\n"
          "        else:", 1),
     "a liveness check cancels the work: the answer to 'are you still there' "
     "must not be to stop being there"),
]

CASES += [
    # ---------------------------------------------------------------- CI-082
    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("        if applied:\n            self._emit(\"sensors.polled\", out)",
          "        self._emit(\"sensors.polled\", out)", 1),
     "an event published on every poll whether or not a probe ran: measured at "
     "9,152 records in twenty minutes, 86.3% of the entire append-only log, "
     "burying the evidence every miss record and replayed snapshot reads back"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            deadline = (self._world.now_ms() + s.ttl_ms\n"
          "                        if s.ttl_ms is not None else None)",
          "            deadline = s.ttl_ms", 1),
     "the TTL passed straight into `valid_until_ms`, which is an ABSOLUTE "
     "stamp: a five-minute reading is stamped as expiring five minutes after "
     "the epoch, and whether that reads as always-expired or never-expired "
     "depends on which clock the world model happened to be given"),

    ("sensors-never-reach-a-model", HOST_PROBES_PY,
     _sub("    return DEGRADED if constrained else ONLINE",
          "    return 'constrained' if constrained else 'nominal'", 1),
     "the probe invents its own health vocabulary again: "
     "`trg_placement_reevaluate` reads `health in { DEGRADED, FAILING }`, so "
     "the trigger can never fire however degraded the host gets, and nothing "
     "reports it because both halves stay internally consistent"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            with decision_path.entered(self._bus, f\"sensor:{sensor.name}\"):\n"
          "                value = sensor.probe()",
          "            value = sensor.probe()", 1),
     "the decision-path guard removed from the probe path: a sensor may then "
     "ask a model 'is there anything worth doing', which is a chatbot talking "
     "to itself and a filter that can be prompt-injected by the SMS it reads"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            if s.source_class not in POLLABLE:", "            if False:", 1),
     "gated sources put on a timer: the camera and the microphone run on an "
     "interval rather than for a reason, which is the design the source classes "
     "exist to prevent and the one power cannot afford"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            self._discard(sensor.name, \"probe_failed\", repr(exc))\n"
          "            return UNKNOWN, elapsed",
          "            return getattr(self, '_last_value', 'ac'), elapsed", 1),
     "a failed probe returns a stale value instead of UNKNOWN: the reading "
     "renders identically to a fresh one, no predicate over it can tell, and "
     "the failure is never logged"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            if value is UNKNOWN:", "            if False:", 1),
     "UNKNOWN written into the world model as a value, making a failed probe "
     "indistinguishable from a fact that legitimately expired"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("        if self.source_class not in SOURCE_CLASSES:", "        if False:", 1),
     "a sensor registered with an unrecognised source class, so the thing that "
     "decides its MECHANISM is a typo and it is scheduled by guesswork"),
]

CASES += [
    # ---------------------------------------------------------------- CI-081
    ("chooser-escalates-only-when-unsure", CHOOSER_PY,
     _sub("        if c.confident:", "        if False:", 1),
     "the confidence flag stops gating escalation, so a paid network call runs "
     "in front of every 'hello' -- inside the latency path, on the owner's "
     "critical path, forever"),

    ("chooser-escalates-only-when-unsure", CHOOSER_PY,
     _sub("        if DIFFICULTY.index(answer) < DIFFICULTY.index(c.difficulty):",
          "        if False:", 1),
     "a model allowed to LOWER the difficulty below the deterministic floor: "
     "too low takes `low` reasoning effort and comes back confidently wrong, "
     "which is the failure this corpus is organised against"),

    ("chooser-escalates-only-when-unsure", CHOOSER_PY,
     _sub("        if answer not in DIFFICULTY:", "        if False:", 1),
     "an escalator's answer used without checking it is a difficulty at all, so "
     "a malformed reply routes the turn at a level that does not exist"),

    ("chooser-escalates-only-when-unsure", CHOOSER_PY,
     _sub("        except Exception as exc:                   # noqa: BLE001\n"
          "            # A DEAD ESCALATOR IS NOT A DEAD TURN.",
          "        except ZeroDivisionError as exc:           # noqa: BLE001\n"
          "            # A DEAD ESCALATOR IS NOT A DEAD TURN.", 1),
     "a provider failure inside the chooser propagates into the turn: the "
     "deterministic answer was already computed and already routable, and the "
     "escalation was an improvement on it rather than a dependency of it"),

    ("chooser-escalates-only-when-unsure", CHOOSER_PY,
     _sub("announce=elapsed >= ANNOUNCE_MS", "announce=False", 1),
     "the hold announcement never fires, so a wait past the point where a pause "
     "stops reading as thinking and starts reading as broken passes in silence"),
]

CASES += [
    # ---------------------------------------------------------------- CI-080
    ("reprojection-never-resurrects", COMPACTOR_PY,
     _sub("            if rec.seq in erased:\n"
          "                continue                 # the owner removed this; it stays gone",
          "            if False:\n"
          "                continue", 1),
     "the projection stops consulting the tombstones: L3 is append-only, so a "
     "routine compaction pass silently undoes the owner's erasure and reports "
     "success"),

    ("reprojection-never-resurrects", COMPACTOR_PY,
     _sub("            if int(b.get(\"rank\", MODEL_PRIOR)) == MODEL_PRIOR:\n"
          "                continue                 # INV-EVID-1, applied at projection too",
          "            if False:\n"
          "                continue", 1),
     "a rank 6 model_prior reaching the log by any route is projected into "
     "memory as fact, where nothing downstream can tell it from the owner's "
     "own word"),

    ("reprojection-never-resurrects", COMPACTOR_PY,
     _sub("    return max(known, key=PRIVACY_CLASSES.index)",
          "    return min(known, key=PRIVACY_CLASSES.index)", 1),
     "compaction classifies DOWNWARD, so three innocuous facts merge into a "
     "security profile carrying the least private of their labels -- the "
     "aggregation failure, arriving as a summary"),

    ("reprojection-never-resurrects", COMPACTOR_PY,
     _sub('        return "private"', '        return "public"', 1),
     "an unrecognised privacy class resolves permissively; unlabelled content "
     "is private everywhere else in this system precisely because the "
     "permissive reading is the one that cannot be undone"),

    ("reprojection-never-resurrects", COMPACTOR_PY,
     _sub('        return {"converged": expected == actual,',
          '        return {"converged": True,', 1),
     "verify() always reports convergence: two nodes projecting independently "
     "diverge while the log agrees, and the only instrument that could see it "
     "says everything is fine"),
]

CASES += [
    # ---------------------------------------------------------------- CI-079
    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub("        fact = self._memory.remember(\n"
          "            subject=subject, attribute=attribute, value=new_value, rank=rank,\n"
          "            privacy=privacy, trust_class=trust_class, at=self._clock.now())",
          "        self._memory._conn.execute(\n"
          "            'UPDATE fact SET value = ? WHERE id = ?', (new_value, prior[0]))\n"
          "        self._memory._conn.commit()\n"
          "        fact = self._memory.remember(\n"
          "            subject=subject, attribute=attribute, value=new_value, rank=rank,\n"
          "            privacy=privacy, trust_class=trust_class, at=self._clock.now())", 1),
     "the one-line wrong answer: an edit done in place, so observed_at_hlc "
     "claims a time belonging to different content and the audit trail becomes "
     "false rather than missing"),

    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub("        seq = self._store.append(\"tombstones\", \"memory.erased\", tomb,\n"
          "                                 self._clock.now())",
          "        seq = 0", 1),
     "an erasure with no tombstone: the content is gone and nothing records "
     "that anything was there, which is indistinguishable from data loss when "
     "the owner asks where it went"),

    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub('                "at": str(self._clock.now()),\n'
          '                "note": ("the erased VALUE is deliberately absent. A tombstone "',
          '                "at": str(self._clock.now()),\n'
          '                "value": self._memory._conn.execute(\n'
          '                    "SELECT value FROM fact WHERE id = ?", (fact_id,)).fetchone()[0],\n'
          '                "note": ("the erased VALUE is deliberately absent. A tombstone "', 1),
     "the tombstone keeps what it erased, which is diligence-shaped and erases "
     "nothing at all"),

    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub('                "DELETE FROM fact WHERE id = ?", (fact_id,))',
          '                "SELECT ?", (fact_id,))', 1),
     "erase writes its tombstone and then does not remove the row: it reports "
     "success, the audit says the content is gone, and selection still returns "
     "it -- the failure mode where the record and the reality disagree and the "
     "record is the one that gets believed"),

    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub("        if actor not in MODE_ACTOR[SUPERSEDE]:", "        if False:", 1),
     "the system allowed to supersede the owner's own statements, which is a "
     "system that corrects the owner rather than one that remembers them"),

    ("forgetter-never-edits-in-place", FORGETTER_PY,
     _sub('                 "note": "a ranking input, not a deletion candidate"}',
          '                 "note": "a ranking input, not a deletion candidate"}\n'
          '                for r in [] or self._purge(older_than_seq)]  # noqa\n'
          '        return [{"fact_id": r[0], "subject": r[1], "attribute": r[2],\n'
          '                 "rank": r[3], "log_seq": r[4],\n'
          '                 "note": "deleted"}', 1),
     "expiry made to delete: nothing expires by deletion in this design, and a "
     "sweep that removed would need a model to rescue the commonest case there "
     "is -- a fact that is simply old and still true"),
]

CASES += [
    # ---------------------------------------------------------------- CI-078
    ("arbiter-never-picks-silently", ARBITER_PY,
     _sub("        claims = self.claims_for(subject, attribute)\n"
          "        return resolve_memory_conflict(",
          "        claims = self.claims_for(subject, attribute)\n"
          "        if claims:\n"
          "            return {'outcome': 'RESOLVED', 'value': claims[0].text,\n"
          "                    'reason': 'highest rank wins'}\n"
          "        return resolve_memory_conflict(", 1),
     "the arbiter takes the highest rank instead of asking: the single most "
     "natural wrong answer here, it looks entirely reasonable, and REM-010 4.6 "
     "calls asking the specified default rather than a design choice"),

    ("arbiter-never-picks-silently", ARBITER_PY,
     _sub("               HAVING vals > 1", "               HAVING vals > 99", 1),
     "contradictions stop being detected, so the resolver is never consulted "
     "and the value used is whichever row selection happened to return first"),

    ("arbiter-never-picks-silently", ARBITER_PY,
     _sub("        return [Claim(text=r[0], memory_rank=r[1], trust_class=r[2])",
          "        return [Claim(text=r[0], trust_class=r[2])", 1),
     "memory_rank dropped in translation, so every candidate arrives at the "
     "resolver as the default rank 5 and no rank 2/3/4 disagreement can ever "
     "be seen -- the ladder is intact and nothing reaches it"),

    ("arbiter-never-picks-silently", ARBITER_PY,
     _sub('        return [r for r in self.sweep(ceiling=ceiling) if r["outcome"] == "ASK"]',
          "        return []", 1),
     "the questions become unreachable: a conflict that resolves to ASK and is "
     "then dropped produces the same outcome for the owner as a silent pick"),
]

CASES += [
    # ---------------------------------------------------------------- CI-077
    ("l1-blocks-hold-index-not-knowledge", BLOCKS_PY,
     _sub("            lines.append(f\"- {n['facts']} {noun} under \\\"{n['node']}\\\" \"\n"
          "                         f\"({n['kind']}) ->log:{n['pointer']}\")",
          "            for _f in self._memory.select([n['node']], limit=99):\n"
          "                lines.append(f\"- {_f.value}\")", 1),
     "block A carries the FACTS instead of the index: resident personal memory "
     "is topically related and mostly irrelevant to any one turn, which is the "
     "distractor class measured to harm more than unrelated filler"),

    ("l1-blocks-hold-index-not-knowledge", BLOCKS_PY,
     _sub('        lines = [preamble.rstrip(), "", BLOCK_A_HEADER]',
          '        import time as _t\n'
          '        lines = [preamble.rstrip(), f"turn at {_t.time()}", BLOCK_A_HEADER]', 1),
     "one per-turn value at the front of block A: the prefix cache is keyed on "
     "bytes, so every turn now pays full freight and the output looks exactly "
     "the same as when it did not"),

    ("l1-blocks-hold-index-not-knowledge", BLOCKS_PY,
     _sub("        preamble, _sel = self._persona.compose(situation)",
          "        preamble = ''", 1),
     "the persona preamble dropped from block A: persona alone is ~1,590 "
     "tokens, below every published cache minimum, so it can never be "
     "discounted on its own -- and VESPER answers fluent and nameless"),

    ("l1-blocks-hold-index-not-knowledge", BLOCKS_PY,
     _sub('        return f"{self.block_b}\\n\\n{self.question}" if self.block_b else self.question',
          '        return f"{self.block_b}\\n\\n(recent context omitted)\\n\\n{self.question}" if self.block_b else self.question', 1),
     "content inserted between block B and the question, filling the U-curve's "
     "weak middle that the two-block split exists to leave empty"),

    ("l1-blocks-hold-index-not-knowledge", BLOCKS_PY,
     _sub('            lines.append(f"- {f.subject}/{f.attribute}: {f.value} "\n'
          '                         f"[rank {f.rank} ->log:{f.log_seq}]")',
          '            lines.append(f"- {f.subject}/{f.attribute}: {f.value}")', 1),
     "block B quotes facts with no pointer: INV-EVID-2 needs a resolvable span, "
     "and a fact without one can only be asserted, never cited"),
]

CASES += [
    # ---------------------------------------------------------------- CI-076
    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub("        findings = scan(text, generous=True, source=source)",
          "        findings = []", 1),
     "the credential refusal removed from the capture path: the updater writes "
     "indiscriminately by design, so a key spoken once becomes a permanent "
     "memory record of a secret"),

    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub('                 "findings": [f.to_dict() for f in findings],',
          '                 "findings": [f.to_dict() for f in findings], "text": text,', 1),
     "the tombstone gains the raw text: the low-security bin becomes the one "
     "place every credential VESPER has ever seen is gathered, which is a "
     "better target than the vault it was protecting"),

    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub("        if any(p in low for p in OFF_THE_RECORD):",
          "        if False:", 1),
     "off-the-record ignored -- the owner's explicit, deterministic instruction "
     "not to record a moment, overridden by the capture path it was written to "
     "override"),

    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub("                        rank=RANK_DERIVED, privacy=privacy,",
          "                        rank=reading.get('rank', RANK_DERIVED), privacy=privacy,", 1),
     "the extractor allowed to choose its own rank: a model's reading of an "
     "utterance can then claim rank 4 and become indistinguishable from the "
     "owner's own word, permanently and with nothing to see"),

    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub("            if event_id in self._seen:", "            if False:", 1),
     "idempotency dropped: delivery is at-least-once, so one redelivered "
     "capture writes the same fact twice and repetition -- which is what "
     "promotes an observation to a trait -- becomes an artifact of the "
     "transport"),

    ("updater-refuses-and-ranks", UPDATER_PY,
     _sub("        if detector not in (self.REPETITION, self.CORRECTION,",
          "        if False and detector not in (self.REPETITION, self.CORRECTION,", 1),
     "an unnamed miss detector accepted, so no detector's false-positive rate "
     "can be counted and the thresholds can never be tuned from the corpus"),
]

CASES += [
    # ---------------------------------------------------------------- CI-075
    ("redactor-precedes-every-provider", GATEWAY_PY,
     _sub('        prompt, _f = redact(prompt, source="prompt")',
          '        _f = []', 1),
     "the prompt no longer redacted at the choke point: the owner pastes a key "
     "into a question and it is in the provider's log before anything else in "
     "this corpus gets a chance to object"),

    ("redactor-precedes-every-provider", GATEWAY_PY,
     _sub("            history = _clean_history", "            pass", 1),
     "history left unredacted -- the field that replays what the owner typed "
     "turns ago to a provider on EVERY subsequent turn, so one paste leaks "
     "once per turn for the rest of the conversation"),

    ("redactor-precedes-every-provider", REDACT_PY,
     _sub("    for f in sorted(findings, key=lambda f: f.start, reverse=True):",
          "    for f in []:", 1),
     "redact() detects and then substitutes nothing: every caller sees a "
     "findings list that says it worked, and the text goes out intact"),

    ("redactor-precedes-every-provider", REDACT_PY,
     _sub("    for kind, pat in PATTERNS:", "    for kind, pat in ():", 1),
     "the pattern floor removed, leaving only the entropy net -- which by\n"
     "     construction cannot see a PEM header or any other low-entropy\n"
     "     credential, and reports a clean scan while missing them"),

    ("redactor-precedes-every-provider", REDACT_PY,
     _sub("        if _is_benign(tok) or not _charset_mixed(tok):",
          "        if False:", 1),
     "the entropy net widened until it eats ordinary text: file paths and "
     "prose are redacted out of every request, which presents as VESPER "
     "talking nonsense about its own files rather than as a guard working"),
]

CASES += [
    # ---------------------------------------------------------------- CI-074
    ("memory-projects-from-the-log", MEMORY_PY,
     _sub('        seq = int(self._store.append("log", "memory.fact", body, at))',
          '        seq = 0', 1),
     "L2 written as a primary store: the fact lands with a pointer that never "
     "had an append behind it, and the row is indistinguishable from a correct "
     "one afterwards"),

    ("memory-projects-from-the-log", MEMORY_PY,
     _sub("if s not in live", "if s is None", 1),
     "the guard inspects the pointer's SHAPE instead of resolving it -- which "
     "is exactly what NOT NULL already does, and every wrong pointer in this "
     "schema is a well-formed integer"),

    ("memory-projects-from-the-log", MEMORY_PY,
     _sub("    return PRIVACY_CLASSES[:PRIVACY_CLASSES.index(ceiling) + 1]",
          "    return (ceiling,)", 1),
     "the probe's `privacy = 'private'` predicate restored as an equality: a "
     "`personal` fact becomes permanently unreachable by block B and nothing "
     "reports the absence"),

    ("memory-projects-from-the-log", MEMORY_PY,
     _sub("                  JOIN (SELECT DISTINCT id FROM reach) r ON f.subject_id = r.id",
          "                  JOIN reach r ON f.subject_id = r.id", 1),
     "the reach CTE's duplicates return: an entity reached at two depths "
     "multiplies its facts, and block B spends its 3-5 slots on repeats"),

    ("memory-projects-from-the-log", MEMORY_PY,
     _sub("        if rank == MODEL_PRIOR:", "        if False:", 1),
     "INV-EVID-1 dropped: a model prior is asserted into memory, where nothing "
     "downstream can tell it from the owner's own word"),
]

CASES += [
    ("face-follows-activity", HOME_STATE,
     _sub("                and len(entries) > len(previous))",
          "                and True)", 1),
     "`talking` re-derived from an unchanged transcript: set_transcript runs on "
     "every pump pass, so the face re-opens forever and never stops answering"),

    ("face-follows-activity", HOME_STATE,
     _sub("        if is_new_reply:", "        if False:", 1),
     "answering no longer counts as talking -- back to `talking` being "
     "reachable only when a status line is spoken aloud, so every reply lands "
     "with the face still thinking"),

    ("face-follows-activity", BEHAVIOUR_SW,
     _sub("            glow = 1 + 0.22 * Float(sin(t / 5.1 * 2 * .pi))",
          "            glow = 1 + 0.22 * Float(sin(t / 5.1 * 2 * .pi)); pulse = 1 + 0.1", 1),
     "working made to change SIZE as well as lightness -- SS6 keeps each state "
     "on its own channel precisely so two of them do not read as a third "
     "thing, and working is the one whose size must hold still"),

    ("face-follows-activity", BEHAVIOUR_SW,
     _sub("            if speechSource == .none {",
          "            if false {\\n                pulse = 1\\n                break\\n            }", 1),
     "the talking envelope runs with no speech source -- a free-running curve "
     "that looks exactly like speech on screen and is wrong every frame, which "
     "SS6 names as the failure by name"),

    ("face-follows-activity", HOME_SW,
     _sub("        face.uniforms.scale    = 0.96 * motion.breath * motion.pulse",
          "        face.uniforms.scale    = 0.96 * motion.breath", 1),
     "the scale channel computed every frame and applied by nothing, so "
     "thinking and talking look identical again and the driver looks correct"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("{{fill}}", "{{fillx}}", 1),
     "a token the Swift does not substitute: it renders literally into a CSS "
     "declaration, the parser DROPS the declaration silently, and the card "
     "paints with no fill over a bright wallpaper -- present, and unreadable"),

    ("chrome-template-renders", CHROME_TPL,
     _sub('<style', '<styl3', 1),
     "the stylesheet element gone -- every surface paints unstyled while the "
     "chrome still reports itself mounted"),

    ("chrome-template-renders", CHROME_SW,
     _sub("static func fallbackTemplate() -> String {",
          "static func fallbackTemplateX() -> String {", 1),
     "the inline fallback removed, so a missing template file blanks a layer "
     "covering the owner's whole Desktop"),

    ("face-follows-activity", HOME_STATE,
     _sub('THINKING = "thinking"', 'THINKING = "working"', 1),
     "the constants transposed again -- three names, three valid behaviours, "
     "and the face shows the wrong expression for every event while nothing "
     "raises"),

    ("face-follows-activity", HOME_STATE,
     _sub("            if (self._behaviour != RESTING\n                    and time.time() - self._since > STALE_AFTER_S):\n                return RESTING",
          "            if False:\n                return RESTING", 1),
     "staleness removed: a face stuck on `thinking` after the run stopped "
     "reports work that is not happening, which nothing else would correct"),

    ("face-follows-activity", HOME_STATE,
     _sub("        if behaviour not in DERIVABLE:", "        if False:", 1),
     "an expression nothing measures becomes reachable -- a face that can be "
     "told to look happy eventually looks happy about something it never "
     "evaluated"),

    ("face-follows-activity", HOME_STATE,
     _sub("            existing[\"face\"] = self.state()",
          "            existing = {}; existing[\"face\"] = self.state()", 1),
     "the snapshot rewritten whole instead of merged, so the face state and "
     "the metrics rows delete each other and the loser is whichever ran last"),

    ("egress-gates-at-choke-point", GATEWAY,
     _sub("            if p.egress_class not in permitted_egress:",
          "            if False:", 1),
     "the egress check removed from the choke point: private content reaches a "
     "public-only supplier that trains on it, and the two most generous free "
     "tiers available are exactly the wrong ones"),

    ("egress-gates-at-choke-point", GATEWAY,
     _sub('                 privacy_class: str = "private") -> dict:',
          '                 privacy_class: str = "public") -> dict:', 1),
     "unlabelled content defaulted to PUBLIC -- every caller that does not pass "
     "a class silently opts the owner's data out of the boundary"),

    ("egress-gates-at-choke-point", GATEWAY,
     _sub('    egress_class: str = E1_PRIVATE', '    egress_class: str = E2_PUBLIC', 1),
     "a provider registered with no declared class becomes public-capable, so "
     "an unvetted endpoint is trusted by omission rather than by decision"),

    ("intake-is-modality-neutral", INTAKE,
     _sub("        return self.confidence >= CONFIDENCE_FLOOR",
          "        return True", 1),
     "the confidence gate removed -- a 61%-sure `delete the archive` is "
     "executed instead of reflected, and the owner finds out from the result"),

    ("intake-is-modality-neutral", INTAKE,
     _sub("            if not u.final:", "            if False:", 1),
     "every partial dispatched: a recogniser's revisions each run as their own "
     "request, and an incomplete sentence can be a valid instruction with the "
     "opposite meaning"),

    ("intake-is-modality-neutral", INTAKE,
     _sub("                self._emit(\"intake.reflected\", u)",
          "                self._emit(\"intake.reflected\", u); self.history.pop()", 1),
     "a reflected utterance dropped from the transcript, so the owner cannot "
     "tell `did not hear` from `heard and declined`"),

    ("shared-pool-is-shared", QUOTA_PY,
     _sub("        rem = self.spendable(e.account, e.purpose)\n        return rem is None or rem > 0",
          "        return True", 1),
     "the shared pool ignored: an entry healthy on its own books passes while "
     "the account it draws from is empty, so two consumers of one budget both "
     "proceed and together authorise twice it"),

    ("shared-pool-is-shared", QUOTA_PY,
     _sub("            return sum(cap * f for (a, p), f in self._floors.items()\n                       if a == account and p != purpose)",
          "            return 0.0", 1),
     "reservation floors dropped -- a batch of images spends the day before "
     "the owner asks their first question, and every step of it looks fine"),

    ("triage-excludes-quota", TRIAGE,
     _sub('    "rate_limited",                 # a working provider doing its job',
          '    # "rate_limited",  # a working provider doing its job', 1),
     "quota failures admitted for investigation -- the queue fills with items "
     "whose only resolution is `yes, we used what we had`, and the real "
     "findings go down with the backlog nobody opens"),

    ("triage-excludes-quota", TRIAGE,
     _sub("        return classification not in NOT_INVESTIGATED",
          "        return classification in ('auth_failed', 'bad_request')", 1),
     "an unrecognised classification declined -- the one failure most worth a "
     "person's attention, and every future unknown discarded silently"),

    ("triage-excludes-quota", TRIAGE,
     _sub("            if n >= REPEAT_THRESHOLD:", "            if n >= 0:", 1),
     "a single transient blip graded critical: the queue fills with noise the "
     "ladder already absorbed, and a grader that escalates everything grades "
     "nothing"),

    ("triage-excludes-quota", REPAIR,
     _sub("        if item.grade != CRITICAL_NOW:", "        if False:", 1),
     "a CRITICAL_DEFERRED item repaired unattended -- its workaround was "
     "holding, so the risk is spent to buy nothing"),

    ("triage-excludes-quota", REPAIR,
     _sub('f"`{_env_of(self._rows, item.provider_id) or \'its environment variable\'}` "',
          '"`its environment variable` "', 1),
     "the escalation guide stops naming the environment variable to replace, "
     "so the owner must go and look up what the system already knew"),

    ("narration-complete", NARRATION_TOML,
     _sub('classification = "exhausted_all"', 'classification = "exhausted_all_DISABLED"', 1),
     "the line for `every provider is spent` deleted -- the one outcome where "
     "the owner most needs to hear `nothing is lost` renders into silence, and "
     "they reasonably assume the work died"),

    ("narration-complete", NARRATION,
     _sub("        if missing:\n            # NOT rendered with blanks.",
          "        if False:\n            # NOT rendered with blanks.", 1),
     "a sentence rendered with a hole in it -- `Retrying in  seconds` reads as "
     "a bug to a listener and costs trust in every other line"),

    ("narration-complete", NARRATION,
     _sub("        may_speak = interruption_class in self._speak_when",
          "        may_speak = True", 1),
     "every retry of an unattended 3 a.m. run narrated aloud: the letter of "
     "SR-004 satisfied and RB-006 proportionality violated"),

    ("narration-complete", NARRATION,
     _sub("        may_speak = interruption_class in self._speak_when",
          "        may_speak = False", 1),
     "nothing ever spoken -- RB-006 satisfied by deleting SR-004, and a failing "
     "request is indistinguishable from a hung one"),

    ("chain-budget-bounded", GATEWAY,
     _sub("    MAX_ATTEMPTS_PER_REQUEST = 10", "    MAX_ATTEMPTS_PER_REQUEST = 100", 1),
     "the chain budget raised past the ladder length -- it stops binding, and "
     "the cost of a request goes back to being per-provider attempts times "
     "however many providers happen to be registered"),

    ("chain-budget-bounded", GATEWAY,
     _sub("                budget -= 1\n", "", 1),
     "the budget counted but never spent: every rung is tried in full and the "
     "bound reads as enforced in every log line"),

    ("chain-budget-bounded", GATEWAY,
     _sub("        ranked = self.quota.rank(offered)", "        ranked = offered", 1),
     "the ledger consulted and its answer discarded -- registration order "
     "decides routing again, and a rung the ledger knows is dead is offered "
     "back to every request"),

    ("chain-budget-bounded", GATEWAY,
     _sub("permanent = self._book_refusal(p, err, hint)", "permanent = False", 1),
     "a limit-0 refusal read as an ordinary rate limit: same status, opposite "
     "fact, and the budget is spent on it every day forever"),

    ("chain-budget-bounded", GATEWAY,
     _sub("                            budget += 1", "                            pass", 1),
     "the refund dropped, so the one request that discovers a rung is "
     "permanently outside the tier pays for knowledge every later request uses"),

    ("chain-budget-bounded", GATEWAY,
     _sub('    for key in ("neurons",                  # cf image -- the BILLED unit',
          '    for key in ("tokens_predicted",  # cf image -- the BILLED unit', 1),
     "spend read from the local runner's field name only -- every remote "
     "provider books 1.0 UNMEASURED while reporting an exact count, and the "
     "ledger's figures are worthless without anything going red"),

    ("chain-budget-bounded", HTTP_COMPLETION,
     _sub("    return bool(_QUOTA_LIMIT_SUSPECT.search(m))", "    return False", 1),
     "the parser-drift detector silenced -- a vendor rewording turns a "
     "PERMANENT limit-0 refusal into one that looks temporary, the ladder "
     "retries a dead rung every day forever, and every check stays green "
     "because the fixture is frozen and still parses"),

    ("chrome-template-renders", CHROME_TPL,
     _sub(".convo{position:absolute;left:{{convoLeft}}px;right:26px;bottom:104px;",
          ".convo{position:absolute;right:26px;bottom:104px;width:min(38vw,520px);", 1),
     "the conversation cluster put back on a viewport-derived position: it "
     "cannot avoid an element it cannot see, and it sat over the face on the "
     "owner's display while this check was green"),

    ("chrome-template-renders", CHROME_SW,
     _sub("let convoLeft = Int(faceRect.maxX) + 40",
          "let convoLeft = Int(host.bounds.width) - 460", 1),
     "the token kept and its derivation cut loose from the face -- the same "
     "defect wearing a token, which is what a check asserting only that the "
     "rule is present would miss"),

    ("face-follows-activity", HOME_SW,
     _sub("            self.motion.behaviour = b", "            _ = b", 1),
     "the face is never told which behaviour it is in: it holds `resting` for "
     "the life of the process while home.json, the status dot and every other "
     "assertion in this check go on agreeing the behaviour is derived correctly"),

    ("face-follows-activity", HOME_SW,
     _sub("            self.chrome.wake()", "            // self.chrome.wake()", 1),
     "only the Space-change edge wakes the chrome: switching APPS brings the "
     "face back on its display link while the cards and the main menu stay on "
     "WebKit's throttled schedule, which is what the owner reported"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("      if (pendingTimer) { pending = { text: text, who: who }; return; }",
          "      if (false) { pending = { text: text, who: who }; return; }", 1),
     "one dissolve timer per arrival again: the owner's line and the reply both "
     "land inside the same 860 ms window, so the first paints and is wiped a "
     "few milliseconds later with no dissolve -- on every single turn"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("      restagger(stage, 'out');", "      ;", 1),
     "the outgoing line keeps its ARRIVAL delays, so the dissolve frays from "
     "the middle outward exactly like the arrival instead of coming apart from "
     "its ends -- the `out` branch in paint goes back to being unreachable"),

    ("chrome-template-renders", CHROME_SW,
     _sub("              var gs = all.slice(0, ANIMATED_MAX);",
          "              var gs = all;", 1),
     "the fallback goes back to animating every glyph of a long reply, so a "
     "missing template file degrades to a surface that builds hundreds of "
     "elements for text the card clips"),

    ("chrome-template-renders", CHROME_SW,
     _sub("        w.setNeedsDisplay(w.bounds)",
          "        w.setNeedsDisplay(w.bounds)\n"
          "        w.evaluateJavaScript(\"document.body.style.opacity='0.999'\", "
          "completionHandler: nil)", 1),
     "the compositor woken by putting an opacity on `body`: it becomes a "
     "backdrop root, every glass panel loses the Desktop it filters, and the "
     "cards render as bare translucent fill with the text barely legible"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("    window.__vesperWork = function (json) {",
          "    window.__renamedReceiver = function (json) {", 1),
     "the page loses its workbench receiver: VESPER's thoughts and actions are "
     "still derived from the bus, still written to home.json, still pushed on "
     "every tick, and rendered by nothing"),

    ("chrome-template-renders", CHROME_SW,
     _sub("    static func workbenchJSON() -> String {",
          "    static func benchState() -> String {", 1),
     "HomeChrome stops reading the workbench out of home.json, so the card sits "
     "empty while the runtime fills the file behind it"),

    ("effort-floor-and-null-answer", EFFORT,
     _sub("    if content is not None and content.strip():",
          "    if content is not None:", 1),
     "the emptiness test reduced to a null test -- `''` is not None, so a 200 "
     "carrying no answer is handed back as one, which is the exact shape "
     "measured on 2026-08-25"),

    ("effort-floor-and-null-answer", GATEWAY,
     _sub('raise_to=options.get("reasoning_effort"))', "raise_to=None)", 1),
     "the caller's effort dropped instead of being read as a request to RAISE: "
     "the floor is never asked about, so it can never be violated, and a build "
     "that lowers effort passes every test"),

    ("effort-floor-and-null-answer", EFFORT,
     _sub("        if EFFORT_RANK[raise_to] < EFFORT_RANK[floor]:", "        if False:", 1),
     "the floor comparison disabled -- lowering is accepted in silence, which "
     "is how budget pressure turns into a quality regression nothing detects"),
]


# --------------------------------------------------------------------------
# CI-068..CI-071. The persona, difficulty and latency surfaces, all landed
# 2026-08-26. Each defect below is either one that was ACTUALLY LIVE in this
# tree that day, or the specific way the property fails silently -- which for
# personality is every way, because a persona that renders empty still returns
# a fluent answer.
# --------------------------------------------------------------------------
CASES += [
    ("persona-is-a-contract", PERSONA_TOML,
     _sub("humour_during_alarm = true", "humour_during_alarm = false", 1),
     "a hard refusal turned into a setting: the alarm register may joke, and "
     "the joke is spent out of the owner's acknowledgement time"),

    ("persona-is-a-contract", PERSONA_TOML,
     _sub('register_id = "none"\nhumour = "none"',
          'register_id = "none"\nhumour = "full"', 1),
     "the alarm register given humour -- the schema states the rule in prose "
     "and cannot express it as a constraint, so nothing but this would catch it"),

    ("persona-is-a-contract", VOICE_TOML,
     _sub("[register.plain]", "[register.plainx]", 1),
     "the `plain` register left with no guidance: it renders as an empty tone "
     "instruction, which does not fail -- it just sounds chatty during a refusal"),

    ("persona-is-a-contract", PERSONA_PY,
     _sub('        sel = Selection(reg, reason, degraded_from)',
          '        sel = Selection(reg, reason, None)', 1),
     "the downgrade to `plain` made silent, so the deterministic layer becomes "
     "unobservable and A-036 has nothing to observe"),

    ("difficulty-classifies-up", DIFFICULTY,
     _sub("    if _MATERIAL.search(raw):", "    if False:", 1),
     "a request carrying code or a stack trace no longer raises -- it falls "
     "through to the length rules and a four-word bug report is answered at "
     "`easy` with the reasoning budget stripped off it"),

    ("difficulty-classifies-up", DIFFICULTY,
     _sub("    flat = _normalise(raw)\n    if flat in GREETINGS:",
          "    flat = _normalise(raw)\n    if any(g in flat for g in GREETINGS):", 1),
     "acknowledgements matched as substrings: `thanks, now explain the "
     "placement stress runner` is classified as a thank-you and answered at "
     "trivial effort"),

    ("difficulty-classifies-up", DIFFICULTY,
     _sub('    return Classification(\n        "moderate", "no confident signal either way',
          '    return Classification(\n        "trivial", "no confident signal either way', 1),
     "the no-signal fallback demoted to trivial, so every request the rules "
     "cannot read is answered at the weakest tier the ladder offers"),

    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("        for phrase in _HALT + _SILENCE + _URGENT:\n"
          "            if re.search(rf\"\\b{re.escape(phrase)}\\b\", flat):\n"
          "                return Floor.BREAK",
          "        pass", 1),
     "a halt word inside a LONG utterance stops breaking the work: \"I need you "
     "to stop what you are doing right now\" is queued instead of obeyed, and "
     "work that should have stopped cannot be un-run"),

    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("    return Floor.QUEUE", "    return Floor.BREAK", 1),
     "every long utterance treated as a halt, so saying anything substantive "
     "while VESPER is working cancels it -- the owner is punished for talking"),

    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("    if not _NEGATED.search(flat):", "    if True:", 1),
     "an explicitly negated halt inside a long utterance breaks the work: "
     "\"please don't stop\" is the owner granting time, and cancelling on it "
     "punishes them for being explicit"),
    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("    (_HALT, Floor.BREAK), (_REVERSE, Floor.BREAK), (_RECORRECT, Floor.BREAK),",
          "    (_HALT, Floor.SWALLOW), (_REVERSE, Floor.BREAK), (_RECORRECT, Floor.BREAK),", 1),
     "halts reclassified as cooperative -- the owner says `stop` while the "
     "chooser holds the floor and it is discarded as encouragement, so the "
     "work cannot be interrupted at all"),

    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("        return Floor.BREAK\n\n    # A long utterance is a new request",
          "        return Floor.SWALLOW\n\n    # A long utterance is a new request", 1),
     "the default under ambiguity flipped to swallow: every unrecognised short "
     "utterance is discarded, and the asymmetry that a wrong swallow costs far "
     "more than a wrong break is inverted"),

    ("barge-in-never-swallows-a-halt", BARGE_IN,
     _sub("    (_NEGATED_HALT, Floor.SWALLOW),      # before _HALT; longest-match anyway",
          "    ((), Floor.SWALLOW),      # negated halts removed", 1),
     "negated halts removed, so `don't stop` matches the halt list and cancels "
     "the work the owner just asked to continue"),

    ("baseline-records-what-cannot-be-rebuilt", BASELINE,
     _sub('    outcome: str                      # "answered" | "declined" | "could_not"',
          '    outcome: str = "answered"         # defaulted', 1),
     "`outcome` given a default, so a caller may omit the one field nothing can "
     "reconstruct -- `declined` and `could_not` become the same row and no "
     "later pass can tell a choice from a failure"),

    ("baseline-records-what-cannot-be-rebuilt", BASELINE,
     _sub("        return None if prev is None else round(now - prev, 1)",
          "        return 0.0 if prev is None else round(now - prev, 1)", 1),
     "the first turn records a gap of 0.0 rather than None, asserting that no "
     "time passed -- a claim about the world -- where there was simply no "
     "previous turn"),

    ("baseline-records-what-cannot-be-rebuilt", BASELINE,
     _sub("            self.failed += 1",
          "            pass  # not counted", 1),
     "a failed append stops being counted, so a gap in the turn log is "
     "indistinguishable from a quiet period and the loss is silent"),

    ("latency-preference-reorders", ROUTER,
     _sub('            if prefer == "latency":\n                key = (seconds, TIER_RANK[p.tier] - TIER_RANK[floor])',
          '            if False:\n                key = (seconds, TIER_RANK[p.tier] - TIER_RANK[floor])', 1),
     "the latency axis silently ignored -- selection falls back to cost and a "
     "conversational turn goes to the rung measured at 25.9s over one measured "
     "at 0.63s, with the decision record still claiming prefer=latency"),

    ("latency-preference-reorders", ROUTER,
     _sub("            if TIER_RANK[p.tier] < TIER_RANK[floor]:",
          "            if False:", 1),
     "the tier floor dropped: prefer=latency stops choosing among eligible "
     "profiles and starts widening eligibility, so hard work routes to whatever "
     "is quickest and SR-009 is gone"),

    ("latency-preference-reorders", LATENCY,
     _sub("        a = ALPHA_UP if seconds > self.seconds else ALPHA_DOWN",
          "        a = ALPHA_UP if seconds > self.seconds else 0.0", 1),
     "a demoted rung never forgiven -- one slow minute retires it for the life "
     "of the process, and the ladder quietly narrows to whatever was fast first"),

    ("latency-preference-reorders", ROUTER,
     _sub("            elif p.probe_seconds:\n                seconds = p.probe_seconds",
          "            elif False:\n                seconds = p.probe_seconds", 1),
     "the enrolment probe's own wall clock ignored on a cold profile, so the "
     "first request to one is ranked on throughput -- a quantity that cannot "
     "see the supplier's queue, and the request that discovers it cost 13.3s"),

    ("latency-preference-reorders", GATEWAY,
     _sub("        if seconds <= 0 or provider_id in self._observed:",
          "        if seconds <= 0:", 1),
     "re-registration allowed to overwrite a live observation with the "
     "enrolment-day figure, so everything the path learned is silently "
     "replaced by a number from the sweep"),

    ("latency-preference-reorders", SUPPLY_PY,
     _sub("            gateway.seed_observation(row.provider_id, row.probe_elapsed_s)",
          "            pass", 1),
     "the gateway left cold at registration: the first request ranks three "
     "rungs of one profile on quota headroom, measured at 1.50s, 2.66s and "
     "3.85s on the same probe"),

    ("latency-preference-reorders", GATEWAY,
     _sub('        if prefer == "latency" and self._observed:',
          '        if False and self._observed:', 1),
     "the gateway's re-order removed: the router picks the fast profile and "
     "quota headroom then picks the slow rung inside it, which is how four "
     "consecutive turns measured 0.56s, 4.22s, 1.02s and 4.63s"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("        if (i === 0) { continue; }", "        if (false) { continue; }", 1),
     "the newest thought tested against the line budget like any other: a long "
     "one is dropped entirely, so VESPER thinks something and shows nothing"),

    ("chrome-template-renders", CHROME_TPL,
     _sub("      var budget = lh * lines + gap * (lines - 1);",
          "      var budget = lh * lines;", 1),
     "the gaps between lines left out of the budget: two one-line thoughts "
     "measure 51.00px against 50.92px and the second vanishes, SS5's `~two "
     "lines` decided by eight hundredths of a pixel"),

    ("chrome-template-renders", WORKBENCH,
     _sub("            return {\"thoughts\": list(reversed(self._thoughts)),",
          "            return {\"thoughts\": list(self._thoughts),", 1),
     "thoughts published oldest-first again, so the renderer spends its budget "
     "on stale lines and the newest is the one that runs out of room"),

    ("effort-floor-and-null-answer", HTTP_COMPLETION,
     _sub('    413: "budget_too_large",', '    # 413 unclassified', 1),
     "413 falls through to `server_error` again: TRANSIENT, so the chain "
     "retries a request that cannot get under the ceiling and then reports a "
     "provider that is working perfectly as broken"),

    ("effort-floor-and-null-answer", GATEWAY,
     _sub('TERMINAL = ("auth_failed", "quota_exhausted", "revoked", "bad_request",\n            "budget_too_large")',
          'TERMINAL = ("auth_failed", "quota_exhausted", "revoked", "bad_request")', 1),
     "`budget_too_large` left with no rule in the chain: neither retried nor "
     "abandoned, on an error that fails identically every time"),

    ("system-turn-reaches-the-wire", SUPPLY_PY,
     _sub('                msgs.append({"role": "system", "content": system})',
          '                pass', 1),
     "the persona dropped from the openai_chat wire -- composed, validated, "
     "and never sent, which is the built-and-unreached failure this tree keeps "
     "rediscovering"),

    ("system-turn-reaches-the-wire", SUPPLY_PY,
     _sub('                payload["instructions"] = system', '                pass', 1),
     "the persona dropped from the cf_responses wire, so one rung on the "
     "ladder answers as nobody and the others answer as VESPER"),

    ("effort-floor-and-null-answer", EFFORT,
     _sub('EXPECTED_OUTPUT = {"trivial": 128, "easy": 256, "moderate": 512, "hard": 1_024}',
          'EXPECTED_OUTPUT = {"trivial": 1_024, "easy": 1_024, "moderate": 1_024, "hard": 1_024}', 1),
     "the declared output allowance flattened back to the 1024 default: a "
     "greeting reserves 1536 tokens of a TPM limit measured at 8000, so a rung "
     "that could serve dozens of turns a minute serves five"),

    ("effort-floor-and-null-answer", EFFORT,
     _sub('EXPECTED_OUTPUT = {"trivial": 128, "easy": 256, "moderate": 512, "hard": 1_024}',
          'EXPECTED_OUTPUT = {"trivial": 128, "easy": 256, "moderate": 1_024, "hard": 512}', 1),
     "the output allowance made non-monotonic -- a HARD request is allotted "
     "less room to answer in than a moderate one, which is the capability "
     "regression the effort floor exists to refuse, arriving through the other "
     "half of the budget"),

    ("effort-floor-and-null-answer", EFFORT,
     _sub('REASONING_HEADROOM = {"low": 512, "medium": 2_048, "high": 8_192}',
          'REASONING_HEADROOM = {"low": 128, "medium": 2_048, "high": 8_192}', 1),
     "reasoning headroom cut to pay for the same saving: a starved reasoning "
     "budget does not shorten the answer, it returns NO answer with a 200"),

    ("system-turn-reaches-the-wire", RUNTIME,
     _sub("        out = gw.complete(request, task_id=task, system=system,",
          "        out = gw.complete(request, task_id=task,", 1),
     "the runtime stops passing a persona: both contracts still load, both "
     "still validate, and nothing reaches a provider"),
]


if __name__ == "__main__":
    sys.exit(main())

