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


if __name__ == "__main__":
    sys.exit(main())
