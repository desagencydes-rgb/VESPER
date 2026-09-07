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
import re
import signal
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


def _renumber(prefix: str, new: str):
    """Mutate the NUMBER that follows a fixed prefix, whatever it currently is.

    WHY NOT `_sub` WITH THE LITERAL. Three of these cases encoded the counts
    themselves -- "# 85 checks", "PASS 381/381" -- so every time the corpus grew
    they stopped applying, and a self-test that does not apply reports the
    artifact changed shape rather than that the check is fine. That is the
    documented-counts drift arriving one layer down, in the very cases written to
    catch it. The mutation should depend on the SHAPE of the line, not on today's
    value of the number it carries.
    """
    pat = re.compile(re.escape(prefix) + r"(\d+)")
    def apply(text: str) -> str:
        return pat.sub(lambda m: prefix + new, text, count=1)
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
    # MOVED 2026-08-31: the subject was CI-004, which is now implemented with
    # six red-run cases, so the mutation stopped applying and the runner said
    # so rather than passing quietly. Re-pointed at CI-002, still PENDING --
    # which is what the comment above prescribes and the third time this case
    # has had to move as the registry filled in.
    (["tools/ci/checks.py", "ci-registry"], "verification/ci/CHECKS.toml",
     _sub('[checks.CI-002]\nname = "source-immutability"\nenforces = ["INV-PROC-1"]\nkind = "process"\nimpl = "PENDING"',
          '[checks.CI-002]\nname = "source-immutability"\nenforces = ["INV-PROC-1"]\nkind = "process"\nimpl = "tools/ci/checks.py source-immutability"', 1),
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


# ---------------------------------------------------------------- safety

# THIS TOOL MUTATES THE LIVE WORKING TREE, and both of the ways that goes wrong
# happened on 2026-09-02, hours apart, to someone who had already written the
# rule down.
#
# TWO RUNS AT ONCE leave the tree broken. Each case reads a file, mutates it,
# runs a check and restores what IT read -- so a second process running the same
# case restores its own copy over the first's, and whichever finishes last wins.
# Eight `core/` modules were left holding `SpanVerdict(True)`, `if False:` and
# `permanent = False`, and the next suite reported 69 failures that were nothing
# but the schedule.
#
# AND A KILLED RUN SKIPS THE RESTORE. `finally` covers exceptions; SIGTERM
# terminates the process without unwinding, and a foreground timeout sends
# exactly that. The file stays mutated with no record of why.
LOCK = REPO / ".self_test.lock"
# The path currently mutated, so a signal handler can put it back. One at a
# time, because the loop is sequential -- if that ever stops being true this
# has to become a stack.
_IN_FLIGHT: dict = {}


def _lock_holder() -> int:
    """The pid holding the lock, 0 if none or if it is stale."""
    try:
        pid = int(LOCK.read_text().strip())
    except Exception:                                  # noqa: BLE001
        return 0
    try:
        os.kill(pid, 0)          # signal 0 asks "is it alive", changes nothing
    except (ProcessLookupError, ValueError):
        return 0
    except PermissionError:
        return pid               # alive and not ours
    return pid


def _acquire() -> None:
    held = _lock_holder()
    if held:
        raise SystemExit(
            f"self_test is already running as pid {held}. Refused rather than "
            "run: this tool mutates the working tree, and two runs restore "
            "each other's copies until the tree is left broken. Wait for it, "
            f"or remove {LOCK.name} if that process is gone.")
    LOCK.write_text(str(os.getpid()))


def _release() -> None:
    try:
        if _lock_holder() in (0, os.getpid()):
            LOCK.unlink(missing_ok=True)
    except Exception:                                  # noqa: BLE001
        pass


def _restore_and_die(signum, _frame):
    """Put the file back before going, however we were asked to go."""
    path, raw = _IN_FLIGHT.get("path"), _IN_FLIGHT.get("raw")
    if path is not None and raw is not None:
        try:
            restore(path, raw)
            print(f"\n  interrupted by signal {signum}; restored {path}",
                  file=sys.stderr)
        except Exception as exc:                       # noqa: BLE001
            print(f"\n  interrupted by signal {signum} and COULD NOT RESTORE "
                  f"{path}: {exc!r}", file=sys.stderr)
    _release()
    raise SystemExit(128 + int(signum))



def _resync_chrome_fallback(rel: str) -> list[tuple[Path, bytes]]:
    """Regenerate the Swift inline fallback after a mutation to `home.html`.

    Returns what to restore: the Swift file and its ORIGINAL bytes, or an empty
    list when nothing was touched. See the call site for why this is here.
    """
    if rel != CHROME_TPL:
        return []
    swift = REPO / CHROME_SW
    raw = swift.read_bytes()
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "_sync_chrome_fallback_selftest", REPO / "tools" / "sync_chrome_fallback.py")
    if spec is None or spec.loader is None:
        return []
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    swift.write_text(mod.render(), encoding="utf-8")
    return [(swift, raw)]


def main() -> int:
    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(_sig, _restore_and_die)
        except (ValueError, OSError):
            pass                 # not the main thread, or not this platform
    _acquire()
    try:
        return _run()
    finally:
        _release()


def _run() -> int:
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
        resynced: list[tuple[Path, bytes]] = []
        try:
            _IN_FLIGHT.update(path=path, raw=raw)
            write_mutated(path, mutated, crlf)
            # A CASE MUST GO RED FOR ITS OWN REASON AND FOR NO OTHER.
            #
            # `chrome-template-renders` now asserts that the Swift's inline
            # fallback is what `tools/sync_chrome_fallback.py` generates from
            # `home.html`. Without this, EVERY mutation of the template would
            # trip that assertion as well -- so all eight template cases would
            # go red whatever else was wrong, and each would keep passing after
            # the assertion it was actually written for had been deleted. That
            # is the "alive and useless" shape this harness exists to catch, and
            # a self-test is not exempt from it.
            #
            # A REAL EDIT RE-SYNCS, so the harness re-syncs too: the mutation
            # simulates someone changing the template, and the generated copy
            # follows it exactly as it would in the tree. What is left over is
            # only the assertion the case names. The drift itself is covered by
            # its own case, which mutates the FALLBACK and leaves the template
            # alone -- the honest shape of "the copy fell behind".
            resynced = _resync_chrome_fallback(rel)
            rc_red, out_red = run_check(check)
        finally:
            restore(path, raw)
            for spath, sraw in resynced:
                restore(spath, sraw)
            _IN_FLIGHT.clear()
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
ARABIZI_PY = "core/arabizi.py"
PRESENCE_PY = "core/presence.py"
CTRL_PY = "core/context_control.py"
CACHE_PY = "core/cache.py"
EVID_PY = "core/evidence.py"
VERIFY_PY = "core/verify.py"
VERIFIERS_PY = "core/verifiers.py"
KMAP_PY = "core/knowledge_map.py"
AUTHZ_PY = "core/authorize.py"
TAINT_PY = "core/taint.py"
BUS_PY = "core/bus.py"
GW_PY = "core/gateway.py"
SELFMOD_PY = "core/selfmod.py"
PLACE_PY = "core/placement.py"
STORE_PY = "core/store.py"
TASKS_PY = "core/tasks.py"
AUTON_PY = "core/autonomy.py"
AGENDA_PY = "core/agenda.py"
TELEM_PY = "core/telemetry.py"
FORGET_PY = "core/forgetter.py"
ENROL_PY = "core/enrollment.py"
CONFIRM_PY = "core/confirm.py"
SPEECH_PY = "core/speech.py"
EXTRACT_PY = "core/extract.py"
TRANSCRIBE_PY = "core/transcribe.py"
INTAKE_PY = "core/intake.py"
SUPPLY_TOML = "contracts/policy/provider_supply.toml"
UPDATER_PY = "core/updater.py"
MEMORY_PY = "core/memory.py"
INTBUD_TOML = "contracts/policy/interruption_budget.toml"
WAKE_SWIFT = "app/island-macos/WakeWord.swift"
FN_SWIFT = "app/island-macos/FnTrigger.swift"
MAIN_SWIFT = "app/island-macos/main.swift"
CAPS_PY = "core/capabilities.py"
ACTOR_PY = "core/actor.py"
INTENT_PY = "core/intent.py"
SUBAGENT_PY = "core/subagent.py"
CAPABILITY_PY = "core/capability.py"
MCP_PY = "core/mcp.py"
HTTP_PY = "routing/http_completion.py"
AGENTS_PY = "core/agents.py"
ADVISOR_PY = "core/advisor.py"
BACKGROUND_PY = "core/background.py"
RUNTIME_PY = "tools/ops/vesper_runtime.py"
CHECKS_PY = "tools/ci/checks.py"
COST_PY = "core/cost.py"
EXEC_PY = "core/executor.py"
CAP_PY = "core/capability.py"
ARB_PY = "core/arbiter.py"
BLOCKS3_PY = "core/blocks.py"
BLOCKS2_PY = "core/blocks.py"
GATEWAY_PY = "core/gateway.py"
ROUTER = "core/router.py"
LATENCY = "core/latency.py"
SUPPLY_PY = "routing/supply.py"
RUNTIME = "tools/ops/vesper_runtime.py"

CASES += [
    # ---------------------------------------------------------------- CI-087
    ("context-control-reaches-selection", CTRL_PY,
     _sub("        return [f for f in fragments\n"
          "                if not any(d and d in self._haystack(f) for d in drops)]",
          "        return list(fragments)", 1),
     "a drop stops removing anything: the owner says 'drop the calendar', the "
     "calendar comes back on the next turn, and the command is "
     "indistinguishable from not existing"),

    ("context-control-reaches-selection", CTRL_PY,
     _sub('        parts = [getattr(f, n, "") for n in\n'
          '                 ("fragment_id", "id", "kind", "subject", "attribute", "text", "value")]',
          '        parts = [getattr(f, n, "") for n in ("fragment_id", "text")]', 1),
     "the matcher reads only Fragment's field names, so every command against a "
     "MemoryFact matches nothing and silently does nothing at all"),

    ("context-control-reaches-selection", CTRL_PY,
     _sub("                        self.state.dropped.add(subj)\n"
          "                        self.state.pinned.discard(subj)",
          "                        self.state.pinned.discard(subj)", 1),
     "a drop implemented as an un-pin: the fragment returns to the automatic "
     "selector, which chooses it again immediately"),

    ("context-control-reaches-selection", BLOCKS2_PY,
     _sub("            facts = control.excluded(facts)", "            pass", 1),
     "block B stops honouring the exclusion, so the control is wired and the "
     "selection ignores it"),

    ("context-control-reaches-selection", BLOCKS2_PY,
     _sub("        want = limit if control is None else limit * 3",
          "        want = limit", 1),
     "no over-selection under manual control: dropping two of five leaves the "
     "turn three facts where five were available, and the owner is punished "
     "for narrowing the focus"),
]

CASES += [
    # ---------------------------------------------------------------- CI-086
    ("presence-withholds-and-never-expires", PRESENCE_PY,
     _sub('        return ("owner",) if self.state == ALONE else ("owner", UNKNOWN_PERSON)',
          '        return ("owner",)', 1),
     "UNKNOWN_PERSON dropped from persons(), so PrivacyRouter's ambiguity rule "
     "never fires and the owner's content stays on whatever screen a stranger "
     "is already looking at"),

    ("presence-withholds-and-never-expires", PRESENCE_PY,
     _sub("            observed_at_hlc=self._clock.now(), source=\"owner_declaration\",",
          "            observed_at_hlc=self._clock.now(), source=\"owner_declaration\",\n"
          "            valid_until_ms=60000,", 1),
     "the declaration given a TTL: it expires into UNKNOWN and VESPER returns "
     "to speaking freely in a room the owner never said had emptied"),

    ("presence-withholds-and-never-expires", PRESENCE_PY,
     _sub("        if any(p in flat for p in SOMEONE_PRESENT):", "        if False:", 1),
     "the declaration phrase list ignored, so telling VESPER someone is in the "
     "room does nothing at all -- which is the entire near-term mechanism"),

    ("presence-withholds-and-never-expires", PRESENCE_PY,
     _sub("        if any(p in flat for p in ALONE_AGAIN):", "        if True:", 1),
     "every utterance read as an all-clear: the first thing the owner says "
     "after declaring company silently undeclares it"),
]

CASES += [
    # ---------------------------------------------------------------- CI-085
    ("arabizi-preserves-and-marks-itself", ARABIZI_PY,
     _sub("_ORDERED = sorted(_MAP, key=len, reverse=True)",
          "_ORDERED = sorted(_MAP, key=len)", 1),
     "longest-match-first dropped, so `ch` is consumed as `c`+`h`: every "
     "digraph becomes two wrong sounds and the word is not the word"),

    ("arabizi-preserves-and-marks-itself", ARABIZI_PY,
     _sub('    "2": "ء", "3": "ع", "5": "خ", "6": "ط", "7": "ح", "8": "غ", "9": "ق",',
          '    "8": "غ",', 1),
     "the digit convention removed: 3, 7 and 9 reach the speech engine as "
     "digits and are read as numbers, which is exactly why Apple's voices "
     "cannot speak Darija"),

    ("arabizi-preserves-and-marks-itself", ARABIZI_PY,
     _sub("\nMEASURED = False\n", "\nMEASURED = True\n", 1),
     "a heuristic transliteration claiming verification nobody performed -- "
     "only a Darija speaker can grade it, and a plausible-looking diff is "
     "exactly what ships wrong"),

    ("arabizi-preserves-and-marks-itself", ARABIZI_PY,
     _sub("        if letters and letters not in _EN_UNITS:", "        if letters:", 1),
     "every English token mixing a digit with letters read as Darija, so "
     "'meet me at 9am' is transliterated into nonsense"),

    ("arabizi-preserves-and-marks-itself", ARABIZI_PY,
     _sub("        else:\n            out.append(ch); i += 1", "        else:\n            i += 1", 1),
     "unrecognised characters silently dropped: the speech engine says a "
     "shorter, different sentence and nothing reports the deletion"),
]

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
    ("sensors-never-reach-a-model", RUNTIME,
     _sub('    sensors.register(Sensor("host-health", "world.current_host", "health",',
          '    sensors.register(Sensor("host-health", "current_host", "health",', 1),
     "a sensor written against subject `current_host` while predicates resolve "
     "`world.current_host`: the world fills correctly, every trigger over it "
     "stays UNKNOWN, and nothing anywhere reports that the two never meet"),

    ("sensors-never-reach-a-model", HOST_PROBES_PY,
     _sub('    measured["sustained_tokens_per_sec"] = False',
          '    caps["sustained_tokens_per_sec"] = 42\n'
          '    measured["sustained_tokens_per_sec"] = True', 1),
     "a throughput this host has never measured declared as measured: INV-HW-2 "
     "exists for exactly this number, and MEMORY.md records that it is still "
     "unmeasured on this node"),

    ("sensors-never-reach-a-model", HOST_PROBES_PY,
     _sub('    return "os_keychain"', '    return "hardware_backed"', 1),
     "the node claims hardware-backed key storage on the strength of a keychain "
     "existing, buying itself trust zone Z0 -- which decides what "
     "continuity-critical state INV-TRUST-2 permits it to hold"),

    ("sensors-never-reach-a-model", SENSORS_PY,
     _sub("            return Reading.unavailable(\n"
          "                key, f\"sensor:{name}\",\n"
          "                f\"probe returned no value after {ms:.1f} ms\")",
          "            return Reading(key=key, source=f\"sensor:{name}\",\n"
          "                           value=\"UNKNOWN\")", 1),
     "a failed probe returns a Reading carrying the string UNKNOWN as its "
     "VALUE: it reads as known, renders like a measurement, and carries no "
     "reason a surface could show instead"),

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
     _sub("    return ONLINE\n", "    return 'nominal'\n", 1),
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
     _sub("            rank=5, privacy=ceiling, trust_class=tainted.trust_class,",
          "            rank=5, privacy=ceiling, trust_class='verified_local',", 1),
     "the compaction replaces its inputs' trust instead of inheriting it: a "
     "summary of an owner statement and a retrieved web page loses "
     "retrieved_external at exactly the moment content is merged, which is what "
     "core/taint.py was written to prevent"),

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
     _sub("            claims.append(Claim(text=value, memory_rank=rank,\n"
          "                                trust_class=trust_class, support=support))",
          "            claims.append(Claim(text=value,\n"
          "                                trust_class=trust_class, support=support))", 1),
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
     _sub("        if _is_benign(tok) or not _charset_mixed(_worst_segment(tok)):",
          "        if False:", 1),
     "the entropy net widened until it eats ordinary text: file paths and "
     "prose are redacted out of every request, which presents as VESPER "
     "talking nonsense about its own files rather than as a guard working"),
]

CASES += [
    # ---------------------------------------------------------------- CI-074
    ("memory-projects-from-the-log", MEMORY_PY,
     _sub("        if trust_class not in ALLOWED_LEVEL:",
          "        if not str(trust_class).strip():", 1),
     "trust_class validated for non-emptiness instead of against the vocabulary "
     "core/taint.py owns: an invented class ranks BELOW retrieved_external under "
     "_weakest, so the owner's own words become the least trusted thing present, "
     "and INV-AUTH-6 has nothing to act on because the class it names never "
     "appears"),

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

    ("chrome-template-renders", CHROME_SW,
     _sub('placeholder="say something to VESPER"',
          'placeholder="say something"', 1),
     "the inline fallback drifted from the template by one line -- the shape "
     "that was green for weeks at five hundred lines, because the gate "
     "compared only the two copies' substitution tokens"),

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
     _sub("        return self.confidence >= floor_for(self.meta)",
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


CASES += [
    # ---------------------------------------------------------------- CI-085
    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        return hit if decision.verdict == REUSE else None",
          "        return (hit.value if decision.verdict == REUSE and hit is not None\n"
          "                else None)", 1),
     "the cache returns the bare value on a hit: it went in tainted and comes "
     "out indistinguishable from trusted local data, which is A-025.8 and the "
     "reuse INV-AUTH-3 names by name"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        self._stores[tier].put(key, value)",
          "        self._stores[tier].put(\n"
          "            key, value if isinstance(value, Tainted)\n"
          "            else Tainted(value, \"verified_local\"))", 1),
     "a bare value coerced instead of refused: the cache invents a trust class "
     "it has no way to know, and everything stored through the convenient path "
     "reads back as locally verified"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        h.update(b\"\\x00\")\n", "", 1),
     "key parts concatenated without a separator, so ('ab','cd') and "
     "('abc','d') collide -- a HIT that returns the wrong answer, strictly "
     "worse than a miss and invisible to any test that only checks caching works"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        return content_key(SUMMARY, hashlib.sha256(content.encode()).hexdigest(),\n"
          "                           purpose)",
          "        return content_key(SUMMARY, hashlib.sha256(content.encode()).hexdigest())", 1),
     "purpose dropped from the summary key: a summary written for the compactor "
     "is served to the miss recorder, and both callers get a confident answer "
     "to a question neither asked"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub('            "INV-AUTH-6: the planner context never contains retrieved_external. "',
          'REFETCH,\n            "INV-AUTH-6: the planner context never contains retrieved_external. "', 1),
     "the planner refusal downgraded to REFETCH, which reads as the recoverable "
     "answer and is an infinite loop: the key is content-addressed, so the "
     "refetch returns the same external content and is refused identically"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        return hit if decision.verdict == REUSE else None", "        return hit", 1),
     "the admission decision computed and then ignored: DF-CACHE-ADMIT runs, "
     "the statistics are even correct, and the refused entry is handed over "
     "anyway -- enforcement that is only reported"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        verdict = admit(value, context)\n"
          "        if verdict.verdict != REUSE:\n"
          "            raise PermissionError(\n"
          "                f\"the produced value is not admissible here: {verdict.reason}\")\n", "", 1),
     "only cache HITS are admitted, so the first call through any key returns "
     "freshly produced external content straight to the planner and the "
     "invariant holds on every path except the one that runs first"),

    ("cache-preserves-taint-and-content-keys", CACHE_PY,
     _sub("        if tier not in TIERS:", "        if tier not in TIERS + (EMBEDDING_NOT_BUILT,):", 1),
     "the embedding tier accepted: nothing here produces an embedding, so it "
     "can never register a hit, and accepting it makes the five specified tiers "
     "look complete while one of them is decorative"),
]


CASES += [
    # ---------------------------------------------------------------- CI-086
    ("memory-citations-resolve-or-are-withheld", EVID_PY,
     _sub("        if not _contains(rec.body, self.quoted):", "        if False:", 1),
     "the receipt asserts only that the record exists and hashes correctly, so "
     "a claim that misquotes a real record cites it successfully -- one "
     "unsupported specific inside an otherwise grounded answer, which is the "
     "failure this module's own header names"),

    ("memory-citations-resolve-or-are-withheld", EVID_PY,
     _sub('            return SpanVerdict(\n'
          '                False, "no L3 store on the resolver, so this receipt cannot be "\n'
          '                       "re-read; unverifiable is not verified")',
          "            return SpanVerdict(True)", 1),
     "unverifiable treated as verified: with no L3 handle every memory-derived "
     "citation passes, and the guard disappears in exactly the configuration "
     "that cannot perform it"),

    ("memory-citations-resolve-or-are-withheld", EVID_PY,
     _sub("    if isinstance(body, dict):\n"
          "        return any(_contains(v, needle) for v in body.values())\n"
          "    if isinstance(body, (list, tuple)):\n"
          "        return any(_contains(v, needle) for v in body)\n"
          "    return needle in str(body)",
          "    return needle in json.dumps(body, sort_keys=True)", 1),
     "the quote matched against rendered JSON instead of the record's leaves, "
     "so a KEY NAME grounds a fact and punctuation between two unrelated fields "
     "can satisfy a quotation"),

    ("memory-citations-resolve-or-are-withheld", ARB_PY,
     _sub('                support = (LogReceipt.of("log", rec, value),)',
          '                support = (LogReceipt.of("log", rec, rec.body["value"]),)', 1),
     "the receipt quotes the record instead of the L2 value, so it agrees with "
     "itself by construction and detects nothing: memory that has drifted from "
     "the log it was projected from cites that log happily"),

    ("memory-citations-resolve-or-are-withheld", BLOCKS3_PY,
     _sub("        store = getattr(self._memory, \"_store\", None)\n"
          "        if store is None:\n"
          "            return [], list(facts)",
          "        store = getattr(self._memory, \"_store\", None)\n"
          "        if store is None:\n"
          "            return list(facts), []", 1),
     "block B fails OPEN with no reachable log: every fact is quoted into the "
     "context unchecked, which is the one configuration where none of them can "
     "be shown to come from anywhere"),

    ("memory-citations-resolve-or-are-withheld", BLOCKS3_PY,
     _sub('        if ungrounded:\n', '        if False:\n', 1),
     "the withheld facts are dropped silently: the turn is missing the fact "
     "that answered it and looks exactly like a turn where memory had nothing, "
     "which is A-032's named degradation failure"),
]


CASES += [
    # ---------------------------------------------------------------- CI-087
    ("machine-checkable-means-registered", VERIFY_PY,
     _sub("                and criteria.get(\"kind\") not in self.available())",
          "                and criteria.get(\"kind\") not in MACHINE_CHECKABLE)", 1),
     "eligibility read off the declared name again: a free-time task naming a "
     "strategy nothing implements is not deferred, runs, and is BLOCKED against "
     "a condition this process could never check -- INV-VERIF-2 says it queues"),

    ("machine-checkable-means-registered", VERIFIERS_PY,
     _sub("    checks = [k for k in ASSERTIONS if k in criteria]\n"
          "    if not checks:\n"
          "        return False, (",
          "    checks = [k for k in ASSERTIONS if k in criteria]\n"
          "    if False:\n"
          "        return False, (", 1),
     "zero assertions passes vacuously: a task whose criteria key was "
     "misspelled has nothing checked and reports SUCCEEDED in FREE_TIME, "
     "unattended, and the verdict is indistinguishable from a real one"),

    ("machine-checkable-means-registered", VERIFIERS_PY,
     _sub('        if not claims:\n'
          '            return False, (\n'
          '                "no claims to check: an output whose assertions were never "\n'
          '                "extracted has had nothing verified, and a pass here would be "\n'
          '                "most confident about the outputs least understood")',
          '        if not claims:\n'
          '            return True, "nothing to check"', 1),
     "an output nobody extracted claims from verifies, so the grounded strategy "
     "is most confident about exactly the outputs it understood least"),

    ("machine-checkable-means-registered", VERIFIERS_PY,
     _sub("        except Unsupported as exc:", "        except _NeverRaised as exc:", 1),
     "the gated refusal escapes as an exception and Verifier reports 'verifier "
     "raised Unsupported' -- an ungrounded OUTPUT read as a broken VERIFIER, "
     "which sends the next reader to fix the checker instead of the work"),

    ("machine-checkable-means-registered", VERIFIERS_PY,
     _sub("    if checker is not None:\n"
          '        verifier.register("retrieval_grounded", grounded(checker))\n'
          '        return ("deterministic", "retrieval_grounded")',
          '    if True:\n'
          '        verifier.register("retrieval_grounded", grounded(checker))\n'
          '        return ("deterministic", "retrieval_grounded")', 1),
     "retrieval_grounded registered with no ClaimChecker behind it, so a "
     "memory-less runtime reports the strategy available and every task using "
     "it fails inside the verifier rather than queueing"),

    ("machine-checkable-means-registered", "tools/ops/vesper_runtime.py",
     _sub("    available = register_all(verifier, checker)", "    available = ()", 1),
     "the runtime stops registering any strategy: every verifier above is still "
     "correct and gated, and the running system defers all free-time work "
     "because nothing reached it -- the defect one layer up"),
]


CASES += [
    # ---------------------------------------------------------------- CI-088
    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub('             "edges": [{"to": t, "relation": r} for t, r in self.edges],',
          '             "edges": [{"to": t, "relation": r} for t, r in self.edges],\n'
          '             "content": "",', 1),
     "a content field added to the serialised node: the schema forbids it and "
     "says why -- the first implementation under memory pressure populates it, "
     "and the map becomes the token dump SR-007 exists to replace"),

    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub("        spans = []\n"
          "        for _, n in scored[:budget]:\n"
          "            span = self.span_for(n)\n"
          "            if span is not None:\n"
          "                spans.append(span)",
          "        spans = [n.summary for _, n in scored[:budget]]", 1),
     "retrieval returns the map's own summaries instead of spans read from the "
     "locator: a RAG pipeline under another name, and a summary-of-a-summary "
     "standing in for a retrieval, which INV-EVID-2 refuses in as many words"),

    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub("        if not spans:\n", "        if False:\n", 1),
     "a miss returns an empty list rather than UNKNOWN, inviting the caller to "
     "report that the thing does not exist -- which a map of unmeasured "
     "coverage cannot support about its own corpus"),

    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub("            if n.stale or n.kind == \"directory\":",
          "            if n.kind == \"directory\":", 1),
     "stale nodes served: the recorded hash no longer matches the file, so "
     "anything read through one is cited against a hash that is already wrong"),

    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub("        if _hash(chunk) != n.content_hash:\n"
          "            # The node is stale and `refresh()` has not run. Refusing here means\n"
          "            # a map that is merely out of date cannot produce a wrong citation.\n"
          "            return None\n", "", 1),
     "the read-time hash check dropped, so a map that is merely out of date "
     "produces a citation whose bytes moved under it -- the span carries the "
     "hash it just computed and nothing compares it to what was indexed"),

    ("map-navigates-and-never-carries-content", KMAP_PY,
     _sub("        self.coverage_ratio: float | None = None",
          "        self.coverage_ratio: float | None = 1.0", 1),
     "coverage defaults to complete instead of UNMEASURED: a declared number "
     "standing in for a counted one, and an unbuilt map claims to cover its "
     "corpus entirely"),
]


CASES += [
    # ---------------------------------------------------------------- CI-013
    ("no-ambient-authority", AUTHZ_PY,
     _sub('            return self._deny(subject, cap, "no_grant", "L0",',
          '            return Decision(True, "L2", "authorized", capability_id,\n'
          '                            subject, "default")\n'
          '        if False:\n'
          '            return self._deny(subject, cap, "no_grant", "L0",', 1),
     "a code path that yields a level without a grant: REM-003 says default "
     "deny is not a setting but the ABSENCE of such a path, and this is the "
     "path"),

    ("no-ambient-authority", AUTHZ_PY,
     _sub("        child = replace(parent, grant_id=child_grant_id, subject=child_subject,\n"
          "                        parent_grant_id=parent.grant_id, delegable=False,\n"
          "                        consumed=False)",
          "        child = replace(parent, grant_id=child_grant_id, subject=child_subject,\n"
          "                        parent_grant_id=parent.grant_id,\n"
          "                        consumed=False)", 1),
     "the child inherits delegability, so one owner confirmation can be "
     "re-delegated indefinitely and attenuation bounds nothing past the first "
     "hop -- the escalation core/authorize.py names as the real one"),

    ("no-ambient-authority", AUTHZ_PY,
     _sub("        if not parent.delegable or parent.max_level in NEVER_DELEGABLE:",
          "        if not parent.delegable:", 1),
     "L4/L5 become delegable at attenuation time: one confirmation turns into "
     "an agent fleet's worth of external action"),

    ("no-ambient-authority", AUTHZ_PY,
     _sub("            with self._lock:\n"
          "                grant.consumed = True   # INV-AUTH-2: single use",
          "            with self._lock:\n"
          "                pass", 1),
     "the L4 grant is never spent, so one owner confirmation authorises a "
     "session rather than an action instance"),

    ("no-ambient-authority", AUTHZ_PY,
     # The gate gained `and consume` on 2026-09-02: the actor's pre-check asks
     # whether an action WOULD be permitted, to decide whether to turn a
     # refusal into a question, and spending the grant there left nothing for
     # the executor's binding check.
     _sub("        if grant.max_level in NEVER_DELEGABLE and consume:\n"
          "            with self._lock:\n"
          "                grant.consumed = True   # INV-AUTH-2: single use",
          "        if cap.requires_owner_confirmation and grant.max_level in NEVER_DELEGABLE and consume:\n"
          "            with self._lock:\n"
          "                grant.consumed = True   # INV-AUTH-2: single use", 1),
     "consumption keyed on the capability's declared confirmation again, not on "
     "the level: an L4 grant on a capability that does not declare it is never "
     "spent, and one confirmation authorises action after action. This is the "
     "exact state the owner decided against on 2026-08-31, and it leaked "
     "silently because A-024.2's fixture only ever exercised the declared case"),

    ("no-ambient-authority", EXEC_PY,
     _sub("            raise NotAuthorized(d)", "            pass", 1),
     "the refusal is computed, published, and then the implementation runs "
     "anyway -- enforcement that only reports"),

    ("no-ambient-authority", CAP_PY,
     _sub("        if len(seen) < 2:", "        if False:", 1),
     "the adversarial probe is dropped, so a capability that declares two rules "
     "and returns one level registers: constant in fact whatever it claims in "
     "shape, and after this point every call site trusts it"),
]


CASES += [
    # ---------------------------------------------------------------- CI-012
    ("taint-propagation", TAINT_PY,
     _sub("    return Tainted(value=out, trust_class=_weakest(classes), origin=origin,",
          "    return out  # type: ignore[return-value]\n"
          "    return Tainted(value=out, trust_class=_weakest(classes), origin=origin,", 1),
     "the summariser returns a plain string: the taint is lost not through "
     "malice but through the ordinary shape of the operation, which is the "
     "sentence REM-003 calls the whole defence and the one an implementation "
     "omits"),

    ("taint-propagation", TAINT_PY,
     _sub("    return min(classes, key=lambda c: LEVEL_RANK.get(ALLOWED_LEVEL.get(c, \"L0\"), 0))",
          "    return max(classes, key=lambda c: LEVEL_RANK.get(ALLOWED_LEVEL.get(c, \"L0\"), 0))", 1),
     "the STRONGEST input decides instead of the weakest: nine trusted "
     "paragraphs and one retrieved page summarise as owner content, and one "
     "hostile input is diluted by the company it keeps"),

    ("taint-propagation", TAINT_PY,
     _sub("        return min((f.ceiling() for f in fragments),\n"
          "                   key=lambda l: LEVEL_RANK[l])",
          "        return max((f.ceiling() for f in fragments),\n"
          "                   key=lambda l: LEVEL_RANK[l])", 1),
     "the context ceiling is the highest fragment rather than the lowest, so "
     "one trusted fragment in context raises the ceiling over everything "
     "external beside it"),

    ("taint-propagation", TAINT_PY,
     _sub("        self.proposals.append(proposal)", "        pass", 1),
     "the above-ceiling action is dropped instead of queued as a proposal: a "
     "silent capability loss (RB-022), and the control disappears in exactly "
     "the case the owner needs to see it"),

    ("taint-propagation", TAINT_PY,
     _sub("        if has_external:\n", "        if False:\n", 1),
     "no injection_suspected event while external content is in context and an "
     "above-ceiling action is requested: the refusal happens and nothing "
     "reports it, which is indistinguishable from an action never attempted"),

    ("taint-propagation", TAINT_PY,
     _sub("        bad = [f for f in planner_fragments if f.trust_class == EXTERNAL]",
          "        bad = []", 1),
     "the planner context stops being checked for external content, so raw "
     "retrieved text reaches the planner and INV-AUTH-6 is documented rather "
     "than enforced"),
]


CASES += [
    # ---------------------------------------------------------------- CI-033
    ("claim-support-required", EVID_PY,
     _sub("            if cl.memory_rank == NEVER_AUTHORITATIVE and policy_class in GATED_POLICY_CLASSES:",
          "            if False:", 1),
     "a model_prior claim becomes an assertion in a gated class as long as it "
     "is cited: INV-EVID-1 is not a grounding rule, and rank 6 is never "
     "authoritative however well it reads or how neatly it is sourced"),

    ("claim-support-required", EVID_PY,
     _sub("            if not cl.supported():", "            if False:", 1),
     "empty support stops being a problem, so a claim with no retrieved span "
     "is emitted -- and it is invented whatever the rest of the response does"),

    ("claim-support-required", EVID_PY,
     _sub("        if bad and policy_class in GATED_POLICY_CLASSES:",
          "        if bad and policy_class not in GATED_POLICY_CLASSES:", 1),
     "the gate fires everywhere EXCEPT the classes it exists for: research, "
     "memory writes, world facts and consequential actions pass freely while "
     "casual chat is refused"),

    ("claim-support-required", EVID_PY,
     _sub("            self._bus.publish(\"evidence.unsupported_claims\", subject=subject,",
          "            pass\n        if False:\n"
          "            self._bus.publish(\"evidence.unsupported_claims\", subject=subject,", 1),
     "the refusal stops being published: the rate exists only inside the "
     "checker, and a gate nobody can see the firing of cannot show a slow drift "
     "upward"),

    ("claim-support-required", EVID_PY,
     _sub("            self.total_claims += 1", "            pass", 1),
     "claims stop being counted, so A-003's release metric -- tracked as a "
     "RATE precisely because pass/fail hides drift -- has no denominator"),
]


CASES += [
    # ---------------------------------------------------------------- CI-011
    ("capability-argument-sensitivity", CAP_PY,
     _sub("        if len(seen) < 2:\n", "        if len(rules) < 2:\n", 1),
     "the adversarial probe becomes a rule COUNT: a declared_level that reads "
     "its arguments and returns the same level for every declared example "
     "registers -- constant in fact whatever it claims in shape, and the "
     "declaration is the thing being checked"),

    ("capability-argument-sensitivity", CAP_PY,
     _sub("        if len(rules) < 2:\n"
          "            raise ConstantLevelRefused(", "        if False:\n"
          "            raise ConstantLevelRefused(", 1),
     "a single-rule capability registers, so a constant level is expressible "
     "again rather than unrepresentable"),

    ("capability-argument-sensitivity", CAP_PY,
     _sub("            if lvl not in LEVELS:", "            if False:", 1),
     "a rule producing a level outside the vocabulary registers: it is compared "
     "with LEVEL_RANK at every call site and sorts as unknown there"),

    ("capability-argument-sensitivity", CAP_PY,
     _sub("    example: dict", "    example: dict = None  # type: ignore[assignment]", 1),
     "LevelRule.example gains a default, so a rule can be declared without one "
     "and the adversarial probe silently becomes a probe of nothing"),
]


CASES += [
    # ---------------------------------------------------------------- CI-004
    ("bus-consumer-idempotency", BUS_PY,
     _sub("        if idempotency_key is None:\n"
          "            raise ContractViolation(",
          "        if idempotency_key is None:\n"
          "            idempotency_key = lambda e: e.event_id\n"
          "        if False:\n"
          "            raise ContractViolation(", 1),
     "the missing key is DEFAULTED to event_id instead of refused: every "
     "consumer whose unit of work is a task, a subject or a command silently "
     "gets the wrong key while looking correct, and INV-COORD-5 calls the "
     "registration itself a build failure"),

    ("bus-consumer-idempotency", BUS_PY,
     _sub("        if key in sub.seen:\n"
          "            sub.suppressed_duplicates += 1\n"
          "            return", "        if False:\n            return", 1),
     "the consumer re-applies on replay, so recovery is not idempotent and "
     "replaying a stream twice does not leave state byte-identical (A-033.2)"),

    ("bus-consumer-idempotency", BUS_PY,
     _sub("            sub.suppressed_duplicates += 1\n", "", 1),
     "duplicates are skipped without being counted: a replay that did nothing "
     "becomes indistinguishable from one that never ran"),

    ("bus-consumer-idempotency", BUS_PY,
     _sub("        try:\n            sub.handler(ev)", "        sub.seen.add(key)\n"
          "        try:\n            sub.handler(ev)", 1),
     "the key is marked seen BEFORE the handler runs, so a consumer that raises "
     "is never retried: one crash becomes permanent, silent data loss for that "
     "consumer"),

    ("bus-consumer-idempotency", BUS_PY,
     _sub("            self._store.append(\"audit\", \"system.consumer_failed\", {",
          "            _ = ({", 1),
     "a failing consumer is swallowed without an audit record, so a handler "
     "that has been raising since startup looks exactly like one with nothing "
     "to do"),
]


CASES += [
    # ---------------------------------------------------------------- CI-020
    ("gateway-choke-point", COST_PY,
     _sub('DEFAULT_PERMITTED: dict[str, tuple[str, ...]] = {p: ("free",) for p in PERIODS}',
          'DEFAULT_PERMITTED: dict[str, tuple[str, ...]] = {p: COST_CLASSES for p in PERIODS}', 1),
     "no policy loaded permits every class: absence stops being safe, and it "
     "fails open on exactly the configuration a fresh node, a broken path or a "
     "bad deploy produces -- open in the direction of spending money"),

    ("gateway-choke-point", COST_PY,
     _sub("        if not self._policy_loaded:\n"
          "            # A-021.9: no policy loaded => free only.\n"
          '            return ("free",)', "        if False:\n"
          '            return ("free",)', 1),
     "the no-policy branch stops returning free-only, so an unconfigured "
     "gateway falls through to whatever the empty policy map yields"),

    ("gateway-choke-point", COST_PY,
     _sub('        if self.cost_class == "metered_free_tier" and not self.provable_hard_cap:',
          "        if False:", 1),
     "metered_free_tier resolves as free without a provable cap: the class that "
     "looks free and bills is admitted on the strength of a dashboard claim "
     "(INV-COST-5)"),

    ("gateway-choke-point", GW_PY,
     _sub("            try:\n                self._cost.check(p.provider_id, task_id=task_id)",
          "            try:\n                pass", 1),
     "the cost choke point is not consulted per provider, so a paid rung is "
     "reached under a free-only policy and the permitted list becomes "
     "decoration"),

    ("gateway-choke-point", GW_PY,
     _sub("                    self.attempts_by_class[eff] = self.attempts_by_class.get(eff, 0) + 1",
          "                    pass", 1),
     "attempts stop being counted at the boundary, so A-004.3's measurement of "
     "which cost classes are actually being reached has no denominator"),
]


CASES += [
    # ---------------------------------------------------------------- CI-015
    ("no-runtime-governed-write", SELFMOD_PY,
     _sub("        if not self.is_governed(rel):\n            return",
          "        return\n        if not self.is_governed(rel):\n            return", 1),
     "the boundary permits every write: the runtime can edit a governed surface "
     "directly, which is self-merge into a running configuration and the thing "
     "INV-SELF-1 says may never happen"),

    ("no-runtime-governed-write", SELFMOD_PY,
     _sub('        if not path.exists():\n            return (("",), ())',
          "        if not path.exists():\n            return ((), ())", 1),
     "a MISSING surfaces artifact governs NOTHING instead of everything: the "
     "boundary opens when its configuration goes missing, which is worse than "
     "no boundary because it still looks like it is working"),

    ("no-runtime-governed-write", SELFMOD_PY,
     _sub("        except (OSError, tomllib.TOMLDecodeError):\n"
          '            return (("",), ())',
          "        except (OSError, tomllib.TOMLDecodeError):\n"
          "            return ((), ())", 1),
     "a MALFORMED artifact is treated as an empty one, so a single typo in that "
     "file silently disables the boundary"),

    ("no-runtime-governed-write", SELFMOD_PY,
     _sub("        exact.append(GOVERNED_SURFACES_ARTIFACT)\n", "", 1),
     "the surfaces artifact stops governing itself, so the first governed write "
     "the runtime attempts is the one that removes every other restriction"),

    ("no-runtime-governed-write", SELFMOD_PY,
     _sub('        raise SelfModificationRefused(\n'
          '            f"deleting proposal {proposal_id!r} is refused; only the owner "\n'
          '            "resolves a proposal")',
          "        with self._lock:\n"
          "            self._proposals.pop(proposal_id, None)", 1),
     "the runtime can prune its own proposal queue: a refusal leaves no trace "
     "and the same change returns tomorrow as though never considered"),

    ("no-runtime-governed-write", SELFMOD_PY,
     _sub('            payload={"path": rel, "claimed_level": level,',
          '            payload={"path": rel,', 1),
     "the audit record drops the level that was CLAIMED, so an attempt at L5 "
     "reads identically to one at L1 -- and the parameter that exists only to "
     "be recorded is now ignored AND unrecorded"),
]


CASES += [
    # ---------------------------------------------------------------- CI-045
    ("placement-not-pinned", PLACE_PY,
     _sub("        best = max(hosts.values(), key=lambda p: p.score())",
          '        best = hosts.get("alpha") or max(hosts.values(), key=lambda p: p.score())', 1),
     "placement follows a node IDENTITY rather than a score, so a new node "
     "cannot win on merit however good it is -- and a two-node fixture that "
     "never swaps the names would not notice"),

    ("placement-not-pinned", PLACE_PY,
     _sub("            needed = cur.scalar_score() * (1.0 + self.relocation_gain)",
          "            needed = 0.0", 1),
     "the relocation gain threshold is removed: VESPER flaps between comparable "
     "nodes because migration is treated as free, which is A-048.3's negative "
     "control"),

    ("placement-not-pinned", PLACE_PY,
     _sub("            if hysteresis.since_last_move_s < self.min_dwell_s:",
          "            if False:", 1),
     "the minimum dwell disappears, so two comparable nodes can trade the host "
     "back and forth as fast as the loop runs"),

    ("placement-not-pinned", PLACE_PY,
     _sub("        forced = (cur is None or not cur.reachable or cur.degraded\n"
          "                  or not is_full_host(cur))",
          "        forced = cur is None", 1),
     "an unreachable or degraded current host no longer bypasses damping, so "
     "VESPER politely stays on a dead node for the rest of the dwell window -- "
     "the damping rule turned against the case it was never meant to cover"),

    ("placement-not-pinned", PLACE_PY,
     _sub('        gain = float(t["relocation_gain_threshold"]["default"])',
          "        gain = 0.0", 1),
     "the gain threshold stops coming from the tunables artifact and is zero: "
     "the code still reads as though it damps, and A-048.3's control can no "
     "longer be built without editing the module"),
]


CASES += [
    # ---------------------------------------------------------------- CI-009
    ("leased-write-epoch", STORE_PY,
     _sub("                   WHERE domain_state.written_by_epoch <= excluded.written_by_epoch\"\"\"",
          '                   \"\"\"', 1),
     "the fencing predicate is dropped from the upsert: every stale write "
     "lands, and a returning ex-owner overwrites the current holder's state "
     "with decisions made before it lost the lease"),

    ("leased-write-epoch", STORE_PY,
     _sub("                new_epoch = int(row[0]) + 1", "                new_epoch = int(row[0])", 1),
     "the epoch stops advancing on a claim, so the fencing token is reusable "
     "and an ex-owner's writes pass the fence with a number that looks current"),

    ("leased-write-epoch", STORE_PY,
     _sub("            if cur.rowcount == 0:", "            if False:", 1),
     "a refused write returns silently instead of raising: the stale writer "
     "believes it succeeded and its next decision is built on that belief -- "
     "worse than a rejection, because nothing anywhere records the divergence"),

    ("leased-write-epoch", STORE_PY,
     _sub("    def put_state(self, domain: str, key: str, body: dict, *,\n"
          "                  lease_epoch: int, at: HLC) -> None:",
          "    def put_state(self, domain: str, key: str, body: dict, *,\n"
          "                  lease_epoch: int = 0, at: HLC = None) -> None:", 1),
     "lease_epoch gains a default, so a caller that forgets it writes anyway "
     "and fences against a number nobody chose"),

    ("leased-write-epoch", STORE_PY,
     _sub("        if domain not in DOMAINS:\n"
          "            raise ValueError(f\"unknown domain {domain!r}\")\n"
          "        payload = json.dumps(body, sort_keys=True)",
          "        payload = json.dumps(body, sort_keys=True)", 1),
     "an unknown domain is accepted, so a typo creates a domain nobody leases "
     "and nothing fences -- fenced-looking writes to an unfenced place"),
]


CASES += [
    # ---------------------------------------------------------------- CI-010
    ("task-transition-table", TASKS_PY,
     _sub('    "RUNNING":   ("WAITING", "VERIFYING", "RESUMABLE", "BLOCKED",',
          '    "RUNNING":   ("SUCCEEDED", "WAITING", "VERIFYING", "RESUMABLE", "BLOCKED",', 1),
     "a RUNNING -> SUCCEEDED edge is added: finishing execution becomes "
     "evidence the work was done, which is exactly the equivalence INV-TASK-1 "
     "exists to break"),

    ("task-transition-table", TASKS_PY,
     _sub('    "BLOCKED":   ("READY", "RUNNING", "FAILED", "CANCELLED", "RESUMABLE"),',
          '    "BLOCKED":   ("READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RESUMABLE"),', 1),
     "SUCCEEDED becomes reachable from a second state: checking only the "
     "RUNNING edge would miss it, and a blocked task can now close itself "
     "without a verifier ever running"),

    ("task-transition-table", TASKS_PY,
     _sub('    "SUCCEEDED": (),', '    "SUCCEEDED": ("RUNNING",),', 1),
     "a terminal state gains an outgoing edge, so a finished task can be "
     "un-finished and every count taken from the store becomes a moving number"),

    ("task-transition-table", TASKS_PY,
     _sub('            if not (evidence or {}).get("passed"):', "            if False:", 1),
     "SUCCEEDED no longer requires a passing verdict: the path through "
     "VERIFYING is preserved and nothing is verified along it"),

    ("task-transition-table", TASKS_PY,
     _sub('            if task.verified_by in (None, "none_declared"):',
          "            if False:", 1),
     "'none_declared' is accepted as a verification strategy -- it is the "
     "absence of one, and accepting it makes every other verifier optional"),

    ("task-transition-table", TASKS_PY,
     _sub('                extra = (" -- INV-TASK-1: there is NO RUNNING->SUCCEEDED edge. "',
          '                extra = (" -- not permitted. "', 1),
     "the refusal stops naming INV-TASK-1, so an author who hits it has nothing "
     "to look up and routes around a rule they cannot read"),
]


CASES += [
    # ---------------------------------------------------------------- CI-024
    ("predicate-totality", AUTON_PY,
     _sub("        assert_terminating(trigger.predicate,\n"
          "                           tuple(trigger.clock_terms) + tuple(trigger.state_terms))\n",
          "", 1),
     "registration stops checking termination, so INV-TRIG-5 is enforced "
     "nowhere and a predicate that never returns takes the tick with it"),

    ("predicate-totality", AUTON_PY,
     _sub("        if isinstance(node, ast.While):", "        if False:", 1),
     "an unbounded `while` is accepted: the one construct whose termination "
     "cannot be read off the source is the one no longer looked for"),

    ("predicate-totality", AUTON_PY,
     _sub("        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \\\n"
          "                and node.func.id in own_names:",
          "        if False:", 1),
     "self-recursion is accepted, and its depth is a function of world state -- "
     "the exact input a predicate must not be able to diverge on"),

    ("predicate-totality", AUTON_PY,
     _sub("    except (OSError, TypeError) as exc:\n"
          "        raise NonTerminatingPredicate(",
          "    except (OSError, TypeError) as exc:\n"
          "        return {\"structural\": \"unreadable\", \"probe\": \"skipped\"}\n"
          "        raise NonTerminatingPredicate(", 1),
     "a predicate whose source cannot be read is waved through instead of "
     "refused: anyone building a predicate dynamically opts out of the whole "
     "check, and UNKNOWN stops meaning UNAVAILABLE"),

    ("predicate-totality", AUTON_PY,
     _sub("        if timed_out >= 2:", "        if False:", 1),
     "the bounded probe stops refusing a predicate that never returns, so a "
     "`for` over an unbounded generator registers -- it has no `while` and no "
     "recursion, and the structural rules cannot see it"),

    ("predicate-totality", AUTON_PY,
     _sub("        for _ in range(2):\n"
          "            done.clear()", "        for _ in range(1):\n"
          "            done.clear()", 1),
     "the loop runs once while the refusal still requires two timeouts, so "
     "`timed_out` never reaches 2 and a predicate that never returns is "
     "ACCEPTED. That is what the check detects; the retry's own purpose -- not "
     "refusing a good predicate on one scheduling hiccup -- is a timing "
     "property no deterministic assertion can prove, and it is documented at "
     "the code rather than claimed here"),

    ("predicate-totality", AUTON_PY,
     _sub("        if done and isinstance(done[0], Exception):", "        if False:", 1),
     "a predicate that RAISES on a legitimate snapshot registers: it does not "
     "evaluate to False, it takes the tick down and every other trigger in "
     "that tick with it"),
]


CASES += [
    # ---------------------------------------------------------------- CI-040
    ("telemetry-sensitivity-enforced", TELEM_PY,
     _sub('            "fields": _redact(fields),', '            "fields": fields,', 1),
     "the writer stops redacting: secrets reach the audit store in the clear "
     "and INV-OBS-1 falls back to caller discipline, which is a convention "
     "held at every call site forever and fails silently and once"),

    ("telemetry-sensitivity-enforced", TELEM_PY,
     _sub("            if any(s in str(k).lower() for s in REDACT_SUBSTRINGS):",
          "            if str(k).lower() in REDACT_SUBSTRINGS:", 1),
     "matching moves from substring to exact name, so `user_password_hint` and "
     "`X-Authorization-Header` leak -- which is the real shape of the failure, "
     "not a field called exactly `password`"),

    ("telemetry-sensitivity-enforced", TELEM_PY,
     _sub("    if isinstance(obj, (list, tuple)):\n"
          "        return [_redact(v, depth + 1) for v in obj]\n", "", 1),
     "lists stop being walked, so a credential inside a list of attempt records "
     "-- the ordinary shape of a request log -- survives every flat fixture"),

    ("telemetry-sensitivity-enforced", TELEM_PY,
     _sub("                out[k] = _redact(v, depth + 1)", "                out[k] = v", 1),
     "nested dicts stop being walked: only the top level is inspected, and a "
     "secret one level down is indistinguishable from one that was never there"),

    ("telemetry-sensitivity-enforced", BUS_PY,
     _sub("        if sensitivity in PAYLOAD_FORBIDDEN and payload:", "        if False:", 1),
     "an inline payload is accepted at `sensitive` and `secret`, so a purge can "
     "no longer remove content while leaving the skeleton and correlation chain "
     "intact"),

    ("telemetry-sensitivity-enforced", BUS_PY,
     _sub("        if sensitivity not in SENSITIVITY:", "        if False:", 1),
     "an invented sensitivity is accepted, and a class no rule names is a class "
     "no rule restricts"),
]


CASES += [
    # ---------------------------------------------------------------- CI-049
    ("tombstone-on-durable-write", FORGET_PY,
     _sub('        seq = self._store.append("tombstones", "memory.erased", tomb,\n'
          "                                 self._clock.now())",
          "        seq = 0", 1),
     "the erase writes no tombstone: the fact is gone with no record anything "
     "was ever there, so 'I don't remember' becomes a lie about the cause and "
     "is indistinguishable from a bug"),

    ("tombstone-on-durable-write", FORGET_PY,
     _sub('                "log_seq": row[3], "rank": row[4], "reason": reason,',
          '                "log_seq": row[3], "rank": row[4], "reason": reason,\n'
          '                "erased_value": self._memory._conn.execute(\n'
          '                    "SELECT value FROM fact WHERE id=?", (fact_id,)\n'
          '                ).fetchone()[0],', 1),
     "the tombstone carries the erased VALUE: a tombstone holding what it "
     "erased has not erased it, which is the same trap as quarantining a "
     "credential in full"),

    ("tombstone-on-durable-write", FORGET_PY,
     _sub("        if not reason.strip():", "        if False:", 1),
     "a blank reason is accepted, and the reason is the only record that "
     "survives -- 'something was removed here, cause unknown' reads back "
     "exactly like data loss"),

    ("tombstone-on-durable-write", FORGET_PY,
     _sub("        if actor not in MODE_ACTOR[ERASE]:", "        if False:", 1),
     "any actor may erase: an unattended process can destroy content, and a "
     "wrong erasure leaves nothing behind to show it was wrong"),
]


CASES += [
    # ---------------------------------------------------------------- CI-089
    ("documented-counts-match-commands", "CLAUDE.md",
     _renumber("python3.13 tools/ci/checks.py all       # ", "57"),
     "CLAUDE.md's check count goes stale again -- the eighth drift, and the "
     "first one a gate can see"),

    ("documented-counts-match-commands", "VESPER_ENGINEERING_STATUS.md",
     _renumber("tools/ci/self_test.py                         PASS   ", "295"),
     "the status table's self-test count goes stale: it had been four sessions "
     "wrong before this gate existed"),

    ("documented-counts-match-commands", "VESPER_ENGINEERING_STATUS.md",
     # ANCHORED ON THE SHAPE, NOT ON TODAY'S VALUES -- the third and last case
     # in this file that encoded a count as a literal. It broke on 2026-09-01
     # the moment CI-093 and CI-094 landed and 75/93 became 76/94, reporting
     # "the mutation did not apply" rather than anything about the check. Its
     # line carries THREE numbers, which is why `_renumber` (which rewrites
     # one) was not used for it when the other two were converted.
     lambda t: re.sub(
         r"(tools/ci/checks\.py status\s+)\d+/\d+( check IDs implemented, )\d+( PENDING)",
         r"\g<1>61/89\g<2>28\g<3>", t, count=1),
     "the PENDING count goes stale -- the figure that matters most, because a "
     "PENDING entry looks exactly like enforcement in any listing that does "
     "not read the impl field"),

    ("documented-counts-match-commands", CHECKS_PY,
     _sub('        (r"tools/ci/self_test\\.py\\s*#\\s*red-then-green,\\s*(\\d+)\\s*cases", cases, "self-test cases"),\n',
          "", 1),
     "one of the anchored patterns is dropped, so that figure silently stops "
     "being checked. Caught because the requirement is derived from the "
     "DOCUMENTS, not from the pattern list: the line it used to cover is now "
     "uncovered. A per-pattern guard could not see this -- deleting an entry "
     "deletes its own guard"),
]


CASES += [
    # ---------------------------------------------------------------- CI-035
    ("z2-capability-bound", ENROL_PY,
     _sub('Z2_FORBIDDEN = ("hold_state", "issue_command", "receive_secret")',
          'Z2_FORBIDDEN = ("hold_state", "issue_command")', 1),
     "receive_secret drops off the forbidden list: a credential can be sent to "
     "a limited-trust node, which is the one of the three that puts a secret "
     "somewhere it cannot be protected"),

    ("z2-capability-bound", ENROL_PY,
     _sub('        if n.trust_zone != "Z2":\n            return', "        return", 1),
     "the bound stops firing entirely, so a Z2 node may hold state, issue "
     "commands and receive secrets -- and the refusal event that would have "
     "shown it never appears either"),

    ("z2-capability-bound", ENROL_PY,
     _sub("        if action not in Z2_FORBIDDEN:", "        if False:", 1),
     "every action is refused for a Z2 node: limited trust becomes no trust, "
     "and a node admitted to do something useful can do nothing"),

    ("z2-capability-bound", ENROL_PY,
     _sub('    "DISCOVERED":        ("PENDING_ADMISSION", "REVOKED"),',
          '    "DISCOVERED":        ("PENDING_ADMISSION", "TRUSTED", "REVOKED"),', 1),
     "DISCOVERED -> TRUSTED becomes reachable: admission stops being a gate, "
     "and a node that has demonstrated only that it can send packets is trusted"),

    ("z2-capability-bound", ENROL_PY,
     _sub("        return (self.state == \"TRUSTED\"\n"
          "                and self.measured_tokens_per_sec is not None)",
          '        return self.state == "TRUSTED"', 1),
     "a TRUSTED node with no MEASURED throughput becomes routable, so work is "
     "sent to a node on a number nobody took -- INV-HW-2 inside enrollment"),
]


CASES += [
    # --------------------------------------------------------------- CI-046b
    #
    # A MUTATION MUST NOT WRITE ANY FILE BUT THE ONE IT MUTATES. The harness
    # restores the mutated path and nothing else, so a mutation whose code RUNS
    # and overwrites another file leaves that file destroyed after the case --
    # which is what the first version of the case below did to
    # contracts/policy/tunables.toml, taking it from 8577 bytes to 9. Restored
    # from HEAD. CI-046b is a SOURCE SCAN, so introducing the pattern in a
    # function nobody calls tests exactly what the check tests and executes
    # nothing.
    ("tunable-range-immutable-runtime", PLACE_PY,
     _sub("def load_placement_tunables(",
          "def _widen_the_range() -> None:\n"
          "    TUNABLES.write_text(\"# widened\", encoding=\"utf-8\")\n"
          "\n"
          "\n"
          "def load_placement_tunables(", 1),
     "a runtime module gains a path that writes the tunables artifact: a system "
     "that can widen its own range has no range, and self-tuning stops being "
     "HOW OFTEN and becomes WHAT IT IS ALLOWED TO DO"),

    ("tunable-range-immutable-runtime", PLACE_PY,
     _sub("        gain = float(t[\"relocation_gain_threshold\"][\"default\"])",
          "        t[\"relocation_gain_threshold\"][\"max\"] = 9.0\n"
          "        gain = float(t[\"relocation_gain_threshold\"][\"default\"])", 1),
     "a declared max is assigned to in memory without the file ever being "
     "opened -- mutating the parsed dict widens the range just as effectively, "
     "and a scan for file writes alone would never see it"),

    ("tunable-range-immutable-runtime", "contracts/policy/tunables.toml",
     _sub("[tunable.revisit_after]\nmin = 3600", "[tunable.revisit_after]\nmin = 700000", 1),
     "a declared default falls outside its own range, so the value the runtime "
     "reads is already out of bounds before anything tunes it"),
]


CASES += [
    # ---------------------------------------------------------------- CI-037
    ("outbox-before-effect", TASKS_PY,
     _sub("        cursor = self.intent(task.task_id, action, args,\n"
          "                             idempotency_key=idempotency_key, level=level)\n"
          "        if self.already_sent(cursor):\n"
          '            return {"skipped": True, "reason": "already sent", "cursor": cursor}\n'
          "        result = perform(args)",
          "        result = perform(args)\n"
          "        cursor = self.intent(task.task_id, action, args,\n"
          "                             idempotency_key=idempotency_key, level=level)", 1),
     "the intent is recorded AFTER the effect: bookkeeping that is blind to the "
     "one case that matters, a crash between the send and the record -- and a "
     "resumed task then re-sends something with no undo"),

    ("outbox-before-effect", TASKS_PY,
     _sub('                "level": level, "sent": False,', '                "level": level, "sent": True,', 1),
     "the intent is written already marked sent, so a crash BEFORE the effect "
     "is indistinguishable from a completed send -- in the direction that skips "
     "it forever"),

    ("outbox-before-effect", TASKS_PY,
     _sub('                "args": args, "idempotency_key": idempotency_key,',
          '                "args": args,', 1),
     "the idempotency key is dropped from the durable record, so a replay "
     "re-sends under a new key and the far side sees two distinct actions "
     "rather than a duplicate it can recognise"),

    ("outbox-before-effect", TASKS_PY,
     _sub("            if rec.seq <= floor:", "            if False:", 1),
     "a resume replays intents at or before the cursor too, re-sending "
     "everything the task already completed"),

    ("outbox-before-effect", TASKS_PY,
     _sub("        if not self._leases.external_action_permitted(level):", "        if False:", 1),
     "a partitioned node sends an L4 external action: both sides of the "
     "partition send it, and a duplicated irreversible action has no undo"),
]


CASES += [
    # ----------------------------------------------- confirmation ladder
    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     # ANCHORED ON THE LINE THAT FOLLOWS IT, because "            decays=False,"
     # is not unique: any MORE-indented `decays=False` contains those twelve
     # spaces as a substring, so when `requeue` gained a Candidate of its own
     # this mutation silently retargeted onto that one and left `request()`
     # untouched -- the check passed and the case stopped being evidence.
     _sub("            decays=False,\n            interruption_cost=0.8,",
          "            decays=True,\n            interruption_cost=0.8,", 1),
     "the question DECAYS, so when the owner is away and the budget is zero it "
     "is dropped instead of queued -- which the owner experiences as VESPER "
     "silently abandoning the thing they asked for, and it is the entire second "
     "branch of the ladder"),

    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     _sub("        if urgent:\n            return self._urgent(req, period, attention_state)\n",
          "", 1),
     "the urgent branch quietly becomes an ordinary queued question: something "
     "that could not wait now waits silently, which is the exact failure that "
     "branch exists to prevent"),

    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     _sub("        outcome = self._budget.allocate([cand], period=period,\n"
          "                                        attention_state=attention_state)",
          "        outcome = self._budget.allocate(\n"
          "            [cand], period=period,\n"
          '            attention_state=("available"\n'
          "                             if attention_state == ATTENTION_UNKNOWN\n"
          "                             else attention_state))", 1),
     "an unknown attention state is mapped to `available` before allocation: "
     "'I do not know if you are there' becomes 'speak now'. This is the "
     "declared-versus-measured error INV-HW-2 refuses, and nothing writes "
     "world.owner.attention_state yet -- so it is the state that will actually "
     "occur, not a corner case"),

    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     _sub('            f"May I go ahead?")',
          '            f"It needs {level}. May I go ahead?")', 1),
     "the spoken line names an authorization tier again. It tells the owner "
     "nothing they can act on, and the level available on a refusal is L0 -- so "
     "it says 'it needs L0' about an action that needs L4"),

    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     _sub('        if decision.reason not in CONFIRMABLE_REASONS:', "        if False:", 1),
     "every refusal becomes a question, including ones the owner cannot resolve "
     "by saying yes -- offering an approval that changes nothing"),

    ("confirmation-stops-explains-and-asks", CONFIRM_PY,
     _sub('        if getattr(decision, "authorized", False):', "        if False:", 1),
     "an AUTHORIZED action can be raised as a confirmation, which trains the "
     "owner to approve without reading"),

    ("confirmation-stops-explains-and-asks", INTBUD_TOML,
     _sub("phone_call     = false", "phone_call     = true", 1),
     "the phone channel is declared available when no enrolled node carries a "
     "SIM: a declared cost presented as a working channel, which is the same "
     "shape as a declared throughput"),
]


CASES += [
    # ------------------------------------------------------------- speech
    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        permitted = MAY_CARRY.get(privacy_class, frozenset())",
          '        permitted = frozenset({"E1_PRIVATE", "E2_PUBLIC"})', 1),
     "speech gets its own notion of what may leave the machine, so a private "
     "reply is sent to a public voice service. A second path to a provider is "
     "the shape INV-COST-3 refuses at the cost choke point, and privacy has "
     "the same shape"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        permitted = MAY_CARRY.get(privacy_class, frozenset())",
          '        permitted = MAY_CARRY.get(privacy_class, frozenset({"E2_PUBLIC"}))', 1),
     "an unrecognised privacy class becomes permissive: absence starts meaning "
     "'anything goes', which is what an unlisted cost-policy cell must never "
     "mean either"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        spoken_text = transliterate(reply) if converted else reply",
          "        spoken_text = reply\n"
          "        reply = transliterate(reply) if converted else reply", 1),
     "the converted script reaches the DISPLAY and the synthesiser gets the "
     "original: exactly inverted. INV-NARRATE-2 says what is on screen stays "
     "what the owner wrote, and the conversion exists only for the speaker"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("            degraded, degradation = True, LOCAL_MANGLES",
          "            degraded, degradation = False, \"\"", 1),
     "the local fallback stops reporting that it mangles Darija digits: the "
     "owner hears a worse reply with no way to find out why, which is A-032's "
     "silent degradation"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        if route.surface == WITHHOLD:", "        if False:", 1),
     "private content is spoken aloud with an unidentified person in the room. "
     "A reply read into a room is heard by whoever is in it, and this is the "
     "decision core/presence.py was built to feed"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub('            return {"spoke": False, "attempted": rid,\n'
          '                    "reason": "no credential in the environment or secrets file"}',
          '            return {"spoke": True, "attempted": rid}', 1),
     "a synthesis that could not be performed reports spoke=True: the owner "
     "hears nothing and the record says VESPER spoke -- an instrument's "
     "self-report standing in for evidence"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("            voice=self._voice_for(synth, converted),", "", 1),
     "the plan converts to Arabic script and names no voice, so the "
     "synthesiser uses its default -- English on this host. The owner hears "
     "the punctuation read aloud and nothing else: 0.48 seconds of 'comma' "
     "instead of a 3.4-second sentence, measured 2026-08-31"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        chosen = voice or plan.voice", "        chosen = voice", 1),
     "speak() ignores the voice the plan chose, so the selection is computed, "
     "recorded, and then not used -- the decision made and the instrument not "
     "told"),

    ("speech-is-egress-and-says-so", "tools/ops/vesper_runtime.py",
     _sub("                        plan = speech.plan(reply, privacy_class=\"private\",\n"
          "                                           persons=persons)",
          "                        plan = speech.plan(reply, privacy_class=\"private\")", 1),
     "the runtime stops passing presence to the speech plan, so a private reply "
     "is read aloud with a stranger in the room -- the module is wired and the "
     "one input that makes speaking safe is not"),
]


CASES += [
    # ------------------------------------------- memory stores facts
    ("memory-stores-facts-not-only-transcript", UPDATER_PY,
     _sub("        if self._extractor is not None:\n"
          "            for reading in self._readings(text):", "        if False:\n"
          "            for reading in self._readings(text):", 1),
     "readings stop being written, so memory holds only the owner's sentences "
     "verbatim. A question about Sami reaches nothing -- the sentence is there "
     "and the fact is not, which is what the owner hit"),

    ("memory-stores-facts-not-only-transcript", MEMORY_PY,
     _sub("                 ORDER BY (hit.id IS NULL) ASC,   -- direct matches before hub siblings\n"
          "                          hit.score ASC,          -- then how well they matched\n"
          "                          f.rank ASC,             -- then authority\n"
          "                          f.log_seq DESC          -- then recency",
          "                 ORDER BY f.rank ASC, f.log_seq DESC", 1),
     "relevance is computed by the FTS stage and discarded by the ORDER BY "
     "again, so the extracted fact exists and cannot be retrieved: rank-4 hub "
     "rows fill every slot and the rank-5 answer is left out"),

    ("memory-stores-facts-not-only-transcript", UPDATER_PY,
     _sub("                        rank=RANK_DERIVED, privacy=privacy,",
          "                        rank=RANK_USER_STATEMENT, privacy=privacy,", 1),
     "a model's reading is stored at the owner's own rank, so an extractor can "
     "promote itself to the owner's word and nothing downstream can tell them "
     "apart"),

    ("memory-stores-facts-not-only-transcript", UPDATER_PY,
     _sub('                        trust_class="model_generated",',
          '                        trust_class=trust_class,', 1),
     "the reading inherits the owner's trust class, hiding from every trust "
     "computation downstream that a model produced it"),

    ("memory-stores-facts-not-only-transcript", EXTRACT_PY,
     _sub("        if not value or not subject:\n            continue",
          "        if not value:\n            continue", 1),
     "a reading with no subject is kept, so the fact is filed under an empty "
     "name and is retrievable by nothing"),

    ("memory-stores-facts-not-only-transcript", EXTRACT_PY,
     _sub('    start, end = text.find("["), text.rfind("]")',
          '    start, end = text.find("{"), text.rfind("}")', 1),
     "the parser locates an OBJECT instead of an ARRAY, so a single malformed "
     "reading arrives shaped like a list of them and one bad response becomes "
     "a fact"),
]


CASES += [
    # ------------------------------------------------------ speech in
    ("speech-in-declares-language-and-measures-confidence", TRANSCRIBE_PY,
     _sub("    return round(weighted / total, 4) if total else 0.0",
          "    return round(weighted / total, 4) if total else 0.9", 1),
     "a response with no measured segments gets a confidence of 0.9, clearing "
     "Intake's action floor on a number nothing produced -- the one fabricated "
     "value that lets VESPER ACT on a mishearing"),

    ("speech-in-declares-language-and-measures-confidence", TRANSCRIBE_PY,
     _sub("        p *= (1.0 - min(max(float(sg.get(\"no_speech_prob\") or 0.0), 0.0), 1.0))",
          "        pass", 1),
     "silence scores like speech: a segment the model itself thinks is probably "
     "not speech contributes its token confidence unchanged"),

    ("speech-in-declares-language-and-measures-confidence", INTAKE_PY,
     _sub("TRANSCRIBED_CONFIDENCE_FLOOR = 0.37", "TRANSCRIBED_CONFIDENCE_FLOOR = 0.75", 1),
     "the transcriber is held to the on-device recogniser's floor again. The "
     "two report confidence on different scales, so a CORRECT Darija "
     "transcription scores 0.48 and is reflected as a mishearing -- nothing "
     "wrong with the transcription, the wrong ruler"),

    ("speech-in-declares-language-and-measures-confidence", INTAKE_PY,
     _sub('    if (meta or {}).get("instrument") == "transcriber":\n'
          "        return TRANSCRIBED_CONFIDENCE_FLOOR\n"
          "    return CONFIDENCE_FLOOR",
          "    return TRANSCRIBED_CONFIDENCE_FLOOR", 1),
     "every utterance gets the permissive floor, including one from an "
     "instrument that never named itself -- an unnamed instrument must be "
     "judged by the stricter default, not given the benefit of the looser one"),

    ("speech-in-declares-language-and-measures-confidence", INTAKE_PY,
     _sub("TRANSCRIBED_CONFIDENCE_FLOOR_MEASURED = False",
          "TRANSCRIBED_CONFIDENCE_FLOOR_MEASURED = True", 1),
     "a floor anchored on a published convention is marked MEASURED, so a "
     "citation can be quoted as a finding about this owner's voice in this room"),

    ("speech-in-declares-language-and-measures-confidence", TRANSCRIBE_PY,
     _sub('    return locale not in ON_DEVICE_LOCALES', "    return True", 1),
     "English is routed off the machine too, sending audio away that has an "
     "on-device recogniser -- incurring the exact cost this route exists to "
     "avoid"),
]


CASES += [
    # ------------------------------------------- wake word and single instance
    ("wake-word-listens-locally-and-starts-once", WAKE_SWIFT,
     _sub("req.requiresOnDeviceRecognition = true", "req.requiresOnDeviceRecognition = false", 1),
     "the always-on listener streams to Apple's servers. This is the whole "
     "difference between a microphone that is always on and a room that is "
     "always broadcast: every conversation held near this machine, and every "
     "silence between them, leaves it -- outside ModelGateway and so outside "
     "the redactor, continuously rather than per utterance"),

    ("wake-word-listens-locally-and-starts-once", WAKE_SWIFT,
     _sub("guard r.supportsOnDeviceRecognition else {", "if false {", 1),
     "the listener stops checking that on-device recognition is AVAILABLE "
     "before opening the microphone. Forcing the flag on a machine that cannot "
     "honour it is a request that fails, and its failure looks exactly like a "
     "room where nobody said the wake word"),

    ("wake-word-listens-locally-and-starts-once", RUNTIME_PY,
     _sub("    seen = int(HEARD_OFFSET.read_text()) if HEARD_OFFSET.exists() else 0",
          "    seen = 0", 1),
     "the wake queue is re-read from the top on every pass, so every clip ever "
     "captured is answered again on every pass -- the log fills with replies to "
     "things said once, hours ago"),

    ("wake-word-listens-locally-and-starts-once", RUNTIME_PY,
     _sub('                pathlib.Path(path).unlink()     # the audio is not kept',
          "                pass", 1),
     "raw recordings of the room accumulate on disk after they have been "
     "transcribed, past the processing window they were captured for"),

    ("wake-word-listens-locally-and-starts-once", RUNTIME_PY,
     _sub('bus.publish("wake.discarded"', 'bus.publish("wake.ok"', 1),
     "a clip that would not transcribe leaves no discard record, so a wake word "
     "that was heard and produced nothing is indistinguishable in the log from "
     "a wake word that was never heard at all"),

    ("wake-word-listens-locally-and-starts-once", FN_SWIFT,
     _sub("func homeIsRunning() -> Bool {",
          "func homeIsRunning() -> Bool {\n    let me = ProcessInfo.processInfo.processIdentifier\n"
          "    return NSRunningApplication.runningApplications(withBundleIdentifier: \"ai.vesper.island\")\n"
          "        .contains { $0.processIdentifier != me && !$0.isTerminated }\n"
          "    // unreachable:", 1),
     "the guard goes back to asking whether ANY process from this bundle is "
     "running. The wake listener shares the bundle, so with the wake word doing "
     "its job the triple-tap answers 'already running' and starts nothing -- "
     "measured dead on 2026-08-31, and invisible to the negative control "
     "because that control ran with zero processes, in a state the bug cannot "
     "occur in"),

    ("wake-word-listens-locally-and-starts-once", FN_SWIFT,
     _sub("CFMessagePortCreateRemote", "CFMessagePortCreateRemoteX", 1),
     "liveness stops being asked of something that dies with the process, so "
     "the answer needs validating against staleness and nothing validates it"),

    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub('if args.contains("--home") && homeIsRunning() {',
          'if args.contains("--home") && false {', 1),
     "home stops refusing to start when home is already running, leaving the "
     "starter's check as the only guard -- and it can only cover the launch "
     "paths it knows about, not `open -n` by hand"),

    ("wake-word-listens-locally-and-starts-once", WAKE_SWIFT,
     _sub("        scheduleWakeRetry()\n        return false\n    }\n"
          "    guard AVCaptureDevice", "        return false\n    }\n"
          "    guard AVCaptureDevice", 1),
     "the wake listener checks its permission once and stops asking. Every build "
     "re-signs and TCC revokes, so the grant ALWAYS arrives after home is "
     "already running -- the owner grants it correctly, nothing happens, and "
     "they report having turned the wake word off"),

    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub("    startWakeWordInProcess()\n", "", 1),
     "nothing starts the wake listener. It runs only when launched by hand, so "
     "it does not survive a crash, a logout or a reboot -- a feature that is "
     "fully correct and never running, which every behavioural assertion in "
     "this check would still pass"),

    ("wake-word-listens-locally-and-starts-once", "app/island-macos/build.sh",
     _sub("$ID.fnwatch.plist", "$ID.fnwatch.plist.disabled", 1),
     "the globe-key watcher loses its LaunchAgent, so the one thing whose job "
     "is to start home when nothing is running must itself be started by hand"),

    ("wake-word-listens-locally-and-starts-once", FN_SWIFT,
     _sub("guard ev.keyCode == FN_KEYCODE else { return }", "", 1),
     "the .function flag alone counts as a globe tap, and every arrow key raises "
     "it -- three quick presses scrolling a document start VESPER"),
]


CASES += [
    # ------------------------------------------------- capabilities and acting
    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     # The loop gained a root: relative arguments are resolved against the
     # directory the command will run in, so the classifier and the
     # execution agree on which tree is being levelled.
     _sub("        probe = tok\n"
          "            if not tok.startswith((\"/\", \"~\")):\n"
          "                probe = str(pathlib.Path(root) / tok)\n"
          "            base = _worst(base, fs_read_level({\"path\": probe}))\n",
          "        pass\n", 1),
     "`shell.run(\"cat ~/.ssh/id_rsa\")` drops back to L1 while `fs.read` of the "
     "same file stays L5. The credential rule is real and there are two doors "
     "to it, so every path protection on the read side is bypassed by asking "
     "for the file as a command instead"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if any(m in low for m in DESTRUCTIVE_MARKERS):\n        return "L5"\n',
          "", 1),
     "`rm -rf ~` stops resolving to L5 -- and A-013's OWN ASSERTION STILL "
     "PASSES, because `ls` and `rm -rf ~` still come back different. The one "
     "case the acceptance test states as concrete is satisfied by a classifier "
     "that has stopped recognising destruction"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if any(c in cmd for c in CHAINING):\n'
          '        return "L3"                      # composable, so not provably read-only\n',
          "", 1),
     "`echo x > out.txt` resolves to L1 -- a command that redirects into a file "
     "runs on standing authority with nobody asked. This case named `echo hi > "
     "/etc/hosts` until 2026-09-01 and stayed GREEN under the same deletion: "
     "that path is path-shaped, so the path rule levels it L3 by itself, and "
     "the other four composed probes were each caught by the destructive-marker "
     "rule. Every probe was defended by a DIFFERENT rule and the chaining "
     "branch by none"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if not cmd:\n        return "L5"                      # an empty command is not a safe one',
          '    if not cmd:\n        return "L1"', 1),
     "a command that cannot be analysed is treated as harmless. Fail-open on "
     "the one input nothing could reason about, which is the exact inversion of "
     "what INV-HW-2 does for an unmeasured throughput"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if any(m in p for m in SECRET_MARKERS):\n'
          '        # READING a credential is not a lesser act than writing one. It is the\n'
          '        # step that puts it in a context window, which is where it leaves.\n'
          '        return "L5"\n', "", 1),
     "credentials become ordinary files to READ. Reading one is the step that "
     "puts it in a context window and therefore in an egress path -- the "
     "asymmetry that treats reading as the lesser act is how a secret leaves "
     "without anything being written"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if any(f"/{g}" in p for g in GOVERNED_PREFIXES):\n'
          '        return "L5"\n', "", 1),
     "the contracts, the invariants and the checks become writable on standing "
     "authority: the gates are editable by the thing they gate"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub("    target = resolve(raw)\n    if _escapes(raw, target):\n        return \"L5\"\n",
          "    target = resolve(raw)\n", 1),
     "`workspace/../../../../etc/passwd` levels as VESPER's own scratch space "
     "because it BEGINS with `workspace/`, while the filesystem opens "
     "/etc/passwd. The classifier reads a string and the implementation opens a "
     "target -- the same split `shell_run` refuses `shell=True` to avoid, and it "
     "defeats the one sentence this design rests on: that safety does not depend "
     "on the proposer being right"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     # ANCHORED ON THE BRANCH HEAD, not on the whole if/else. The else-branch
     # gained an eight-line comment on 2026-09-04 explaining why a bare
     # relative path means the owner's home, and this literal -- which spanned
     # it -- silently stopped matching. Neutering the CONDITION sends every
     # `workspace/...` path down the non-workspace branch, which is the same
     # defect with a shorter anchor.
     _sub("        if parts and parts[0] == \"workspace\":\n"
          "            p = WORKSPACE.joinpath(*parts[1:])\n",
          "        if False:\n"
          "            p = WORKSPACE.joinpath(*parts[1:])\n", 1),
     "VESPER's writable space goes back to being module-relative, which inside "
     "the shipped bundle is `VESPER.app/Contents/Resources/runtime/workspace` -- "
     "a directory `build.sh` rewrites on every build. The write succeeds, the "
     "hash matches, the verifier agrees, and the note is gone at the next "
     "rebuild"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     # The run directory is computed now (a session may carry one), so the
     # literal `cwd=str(REPO)` is gone; removing the argument entirely is
     # still exactly the violation this case is about.
     _sub("timeout=timeout, check=False, cwd=run_cwd, env=env)",
          "timeout=timeout, check=False, env=env)", 1),
     "the working directory is inherited again. `workspace/` and `contracts/` "
     "are the whole basis of the level rules and they are relative, so the tree "
     "a command acts on becomes a function of who started the runtime -- a path "
     "levelled as a harmless workspace file, executed somewhere else"),

    ("capabilities-registered-and-levelled-by-argument", ACTOR_PY,
     _sub('STANDING_LEVEL = "L2"', 'STANDING_LEVEL = "L4"', 1),
     "VESPER holds standing L4. Every stop-and-ask this ladder exists for is "
     "silently pre-approved, and the owner's decision of 2026-08-31 -- stop, "
     "explain, ask by voice -- has nothing left to trigger it"),

    ("capabilities-registered-and-levelled-by-argument", ACTOR_PY,
     _sub("delegable=False, issued_by=\"owner\"", "delegable=True, issued_by=\"owner\"", 1),
     "the standing grant becomes delegable, so authority given to VESPER can be "
     "handed onward to anything it spawns (INV-AUTH-2)"),

    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    return {"verified": on_disk == intended,',
          '    return {"verified": True,', 1),
     "the write verifier agrees with the actor no matter what is on the disk. A "
     "verifier that cannot return False is not independent verification, it is "
     "the actor's claim wearing a second name"),

    ("capabilities-registered-and-levelled-by-argument", INTENT_PY,
     _sub('    if t.lstrip().startswith("["):\n        return None\n', "", 1),
     "a JSON array parses as a proposal by finding its first element, so a "
     "model that answered with three actions has one of them executed and the "
     "other two silently dropped"),

    ("capabilities-registered-and-levelled-by-argument", RUNTIME_PY,
     _sub("                 speech=speech, transcriber=transcriber, actor=actor)",
          "                 speech=speech, transcriber=transcriber)", 1),
     "one of the two pump() call sites stops passing the actor, so VESPER acts "
     "from one entry point and not the other -- the same half-wiring that let "
     "`--say` speak while the daemon stayed silent on 2026-08-31"),
]




# --------------------------------------------------------------------------
# CI-093 / CI-094 -- the ceiling reaches the act path, and a gated subsystem
# is reachable at all. Both landed 2026-09-01, after the THIRD instance of one
# shape: built, gated, correct, and connected to nothing.
# --------------------------------------------------------------------------
CHECKS_TOML = "verification/ci/CHECKS.toml"

# --------------------------------------------------------------------------
# The two checks that were NOT EVIDENCE, found 2026-09-01 by running the full
# suite rather than by trusting the previous session's "405/405". Both had the
# same shape: an assertion that a NAME appears, in a file where the name also
# appears somewhere the mutation did not touch.
# --------------------------------------------------------------------------
CASES += [
    ("capabilities-registered-and-levelled-by-argument", CAPS_PY,
     _sub('    if any(m in low for m in DESTRUCTIVE_MARKERS):\n'
          '        return "L5"\n'
          '    if any(c in cmd for c in CHAINING):\n'
          '        return "L3"                      # composable, so not provably read-only\n',
          '    if any(c in cmd for c in CHAINING):\n'
          '        return "L3"                      # composable, so not provably read-only\n'
          '    if any(m in low for m in DESTRUCTIVE_MARKERS):\n'
          '        return "L5"\n', 1),
     "the chaining test is reached BEFORE the destructive one, so `ls; rm -rf ~` "
     "resolves L3 instead of L5: composed-and-destructive is reported as merely "
     "composed, and the ladder loses the worse of the two answers"),

    ("wake-word-listens-locally-and-starts-once", WAKE_SWIFT,
     _sub("    wakeRetry = Timer.scheduledTimer(withTimeInterval: 15.0, repeats: true)",
          "    wakeRetry = Timer.scheduledTimer(withTimeInterval: 15.0, repeats: false)", 1),
     "the retry fires once and gives up -- the same defect with one extra "
     "attempt, and the owner still reports having turned the wake word off"),

    ("wake-word-listens-locally-and-starts-once", WAKE_SWIFT,
     _sub("        t.invalidate()\n        wakeRetry = nil\n", "        t.invalidate()\n", 1),
     "the timer is invalidated but never cleared, so `wakeRetry == nil` stays "
     "false: one failed attempt and nothing can ever rearm"),
]


CASES += [
    # ---------------------------------------------------------------- CI-093
    ("taint-ceiling-binds-the-act-path", ACTOR_PY,
     # ANCHORED ON THE ONE ARGUMENT THIS CASE IS ABOUT. The literal used to
     # span five lines of the call, so every argument added to it broke the
     # match: `command_id` and `consume=False` on 2026-09-02, `mode_ceiling`
     # on 2026-09-05. Twice this case reported "the artifact changed shape"
     # instead of testing anything, which is a self-test that decays every
     # time its subject is improved.
     _sub("                                target=self._target, context_ceiling=ceil,\n",
          "                                target=self._target,\n", 1),
     "the ceiling is computed and dropped at the authorize call -- exactly the "
     "state this corpus shipped in until 2026-09-01"),

    ("taint-ceiling-binds-the-act-path", ACTOR_PY,
     _sub("                                        context_ceiling=ceil,\n"
          "                                        authorization=strength,\n"
          "                                        current_lease_epoch=0)",
          "                                        authorization=strength,\n"
          "                                        current_lease_epoch=0)", 1),
     "the ceiling reaches the actor's pre-check and not the executor, which "
     "re-authorizes immediately before invoking and is the binding check"),

    ("taint-ceiling-binds-the-act-path", ACTOR_PY,
     _sub('        base = (list(fragments) if fragments is not None\n'
          '                else [Tainted(text, "owner", origin="utterance:live")])',
          '        base = [Tainted(text, "owner", origin="utterance:live")]', 1),
     "supplied provenance is ignored and every turn is classed an owner "
     "utterance: the plumbing is present and carries a constant"),

    ("taint-ceiling-binds-the-act-path", TAINT_PY,
     _sub('    "retrieved_external": "L1",', '    "retrieved_external": "L5",', 1),
     "external content is trusted like the owner, so the ladder is wired and "
     "flat -- what a check asserting only 'a ceiling was passed' cannot see"),

    # ---------------------------------------------------------------- CI-094
    # RETARGETED 2026-09-01. This named core/interlock.py, and the emergency
    # stop was WIRED earlier the same day -- so its OWED entry was correctly
    # removed from [unwired] and the mutation stopped matching anything. The
    # case had gone quiet in the good direction, which is the direction that is
    # hardest to notice: nothing was broken, the case was simply no longer
    # testing what it was written to test. core/cache.py is now the one module
    # genuinely OWED rather than deferred by design, so it carries the case.
    ("gated-subsystems-are-reachable", CHECKS_TOML,
     _sub('"core/cache.py" = """OWED', '"core/cache-py" = """OWED', 1),
     "an unreachable gated subsystem loses its declaration and goes silent "
     "again -- the cache, the one module still OWED rather than deferred"),

    ("gated-subsystems-are-reachable", CHECKS_TOML,
     _sub('[unwired]\n', '[unwired]\n"core/gateway.py" = "declared unwired while it has callers"\n', 1),
     "a stale exemption: core/gateway.py is imported all over the runtime and "
     "is declared unwired anyway, so the list rots and hides the next real one"),

    ("gated-subsystems-are-reachable", CHECKS_TOML,
     lambda t: re.sub(r'("core/cache\.py" = )"""[^"]*"""', r'\1"   "', t, count=1),
     "a declaration with no reason -- an exemption nobody had to justify is an "
     "exemption nobody looked at"),
]


# --------------------------------------------------------------------------
# CI-095 -- read-before-write. The most urgent open defect in the handoff:
# fs.write could destroy a file it had never read, and the verifier confirmed
# the destruction had been carried out faithfully.
# --------------------------------------------------------------------------
CASES += [
    ("write-never-destroys-what-was-not-read", CAPS_PY,
     _sub('    if target.exists() and not str(args.get("expect_sha256") or "").strip():\n'
          '        return "L4"\n', "", 1),
     "the escalation is dropped: replacing a file the turn has never read costs "
     "exactly what creating one costs, which is the state the handoff called "
     "the most urgent open defect"),

    ("write-never-destroys-what-was-not-read", CAPS_PY,
     _sub("        on_disk = hashlib.sha256(path.read_bytes()).hexdigest()",
          "        on_disk = hashlib.sha256(content.encode('utf-8')).hexdigest()", 1),
     "the token is compared against the CONTENT BEING WRITTEN instead of the "
     "disk, so the caller hashes its own input and always matches itself -- a "
     "check that can never disagree, passing every other assertion here"),

    ("write-never-destroys-what-was-not-read", CAPS_PY,
     _sub('            raise StaleWrite(', '            pass\n        if False:\n            raise StaleWrite(', 1),
     "a stale token is noticed and waved through: the write lands on content "
     "the proposal was never formed against"),

    ("write-never-destroys-what-was-not-read", CAPS_PY,
     # RETARGETED 2026-09-02, and the case now names the real hazard. It
     # used to hash the EXCERPT, which makes a write FAIL on mismatch --
     # over-strict, never permissive. The permissive direction is handing
     # back the WHOLE-file hash for a read that did not cover the file,
     # which is what `fs.read` did and what the check now refuses.
     _sub('    complete = offset == 0 and len(whole) <= limit',
          '    complete = True', 1),
     "a truncated read hands back the whole-file token, so a first page "
     "authorises replacing a file nobody saw the rest of"),

    ("write-never-destroys-what-was-not-read", ACTOR_PY,
     _sub('        if "previous" not in result:\n            return result',
          '        if True:\n            return result', 1),
     "the actor reports the raw result again, so act.outcome carries the entire "
     "previous contents of every overwritten file into the durable event store "
     "-- which Execution.to_dict deliberately leaves out"),
]


# --------------------------------------------------------------------------
# The agentic loop, and every way of not stopping. The breaker's cases are
# here rather than in a later commit for the reason the check states: without
# a loop a refusal is a dead end, and with one it is a grind.
# --------------------------------------------------------------------------
CASES += [
    ("loop-observes-and-is-bounded", ACTOR_PY,
     # The range gained a start, so a turn parked on a question resumes at the
     # step it stopped on rather than replaying the ones already taken.
     _sub("        for step in range(int(st.get(\"start_step\") or 0), max(1, int(max_steps))):",
          "        for step in range(1):", 1),
     "the loop takes one step again: VESPER cannot run a command, look at the "
     "output and open the file it found -- the omission everything else sat on"),

    ("loop-observes-and-is-bounded", ACTOR_PY,
     # `recent=recent` was added to this call on 2026-09-04 (the turns either
     # side of this one), so the literal stopped matching. Anchored on the
     # observations argument, which is what this case is about.
     _sub("                text, observations=observations if observations else None,",
          "                text,", 1),
     "the next step is proposed without being told what the last one did -- a "
     "loop that cannot observe is a retry, and it will repeat itself blind"),

    ("loop-observes-and-is-bounded", ACTOR_PY,
     _sub("            if signatures and sig == signatures[-1]:", "            if False:", 1),
     "an immediate repeat no longer stops the turn, so a proposer handed its "
     "own last action back re-authorizes and re-executes it to the budget"),

    ("loop-observes-and-is-bounded", ACTOR_PY,
     _sub("                if consecutive_refusals >= MAX_CONSECUTIVE_REFUSALS:",
          "                if False:", 1),
     "the refusal breaker is removed: a steered proposer grinds the ladder for "
     "the whole step budget, and every refusal that reaches the voice ask is a "
     "question asked of someone asleep"),

    ("loop-observes-and-is-bounded", ACTOR_PY,
     _sub("        base += [Tainted(o, observation_trust(str(o.get(\"capability\") or \"\")),\n"
          "                         origin=f\"observation:{o.get('capability')}\")\n"
          "                 for o in (observations or []) if isinstance(o, dict)]",
          "        base += []", 1),
     "observations stop tainting the context, so the step that could be steered "
     "by what was just read is the one step that does not have to ask -- "
     "INV-ACT-3 inverted exactly where it matters"),

    ("loop-observes-and-is-bounded", CAPS_PY,
     _sub('    return {"capability": capability_id, "observed": False}',
          '    return {"capability": capability_id, **result}', 1),
     "an unknown capability's raw result is passed straight into the planner "
     "context, so every capability added later is a hole in INV-AUTH-6 by "
     "default"),

    ("loop-observes-and-is-bounded", CAPS_PY,
     _sub("        out = str(text or \"\").splitlines()[:OBS_MAX_LINES]\n"
          "        return [ln[:OBS_MAX_LINE_CHARS] for ln in out]",
          "        out = str(text or \"\").splitlines()[:OBS_MAX_LINES]\n"
          "        return list(out)", 1),
     "the per-line bound is dropped, so one enormous line defeats the line "
     "count and a runaway command fills the context window anyway"),
]


# --------------------------------------------------------------------------
# Seatbelt containment. Ships WITH the loop rather than after it: a loop
# multiplies whatever safety posture exists, and classification alone was the
# posture.
# --------------------------------------------------------------------------
CASES += [
    ("shell-runs-contained", CAPS_PY,
     # The wrapped argv is built once and shared by the foreground and the
     # background path, so dropping the sandbox is now one edit that
     # affects BOTH -- which is the point of building it once.
     _sub("    argv_contained = [SEATBELT, \"-p\", _seatbelt_profile(level), *argv]",
          "    argv_contained = [*argv]", 1),
     "the sandbox is dropped from the invocation: shell.run is classified and "
     "not contained, which is the posture every path defect in this module has "
     "escaped through"),

    ("shell-runs-contained", CAPS_PY,
     _sub('    if not os.path.exists(SEATBELT):\n'
          '        raise ContainmentUnavailable(', '    if False:\n'
          '        raise ContainmentUnavailable(', 1),
     "a machine with no sandbox runs the command anyway -- falling back to no "
     "containment exactly when the machine is in a state nobody predicted"),

    ("shell-runs-contained", CAPS_PY,
     _sub('        parts.append("(deny file-write*)")',
          '        parts.append("(allow file-write*)")', 1),
     "the L1 profile stops denying writes, so `provably read-only` goes back to "
     "being a claim about a string rather than a property of the process"),

    ("shell-runs-contained", CAPS_PY,
     _sub("             '(deny network*)']", "             '(allow network*)']", 1),
     "a contained command may open a socket: a second egress with no redactor "
     "in front of it, whatever the owner approved the command for"),

    ("shell-runs-contained", CAPS_PY,
     # ANCHORED ON THE LOOP THAT EMITS THE CARVE-OUT, not on the list it
     # iterates. The writable list became mode-dependent on 2026-09-05 (auto
     # mode reaches the owner's home), and the old literal named the tuple
     # that no longer exists -- so the case stopped applying and reported a
     # changed artifact instead of testing containment.
     _sub('    for d in writable:\n'
          '        parts.append(f\'(allow file-write* (subpath "{d}"))\')',
          '    parts.append("(allow file-write*)")', 1),
     "the above-L1 carve-out becomes the whole filesystem, so an approved "
     "action that should have touched VESPER's own space can write anywhere"),
]


# --------------------------------------------------------------------------
# fs.edit -- surgical, unique-match-or-fail. Removes whole-file replacement as
# the only way to change a file, and takes the escalation off the safe path.
# --------------------------------------------------------------------------
CASES += [
    # THE UNIQUENESS IS STRUCTURAL, NOT GUARDED, and finding that out cost two
    # cases that reported green. Disabling either `n > 1` or `len(hits) > 1`
    # changes only WHICH refusal is raised: a replacement happens solely where
    # exactly one hit was found, so the other path still refuses. Those two
    # raises are message quality and defence in depth, and neither is
    # independently load-bearing. The mutation that DOES create the defect is
    # taking the first of many hits -- which is precisely Aider's
    # `search_and_replace` with its uniqueness check commented out.
    # UNIQUENESS HERE IS DEFENDED TWICE, AND EACH MUTATION ALONE IS MASKED BY
    # THE OTHER -- which cost four green cases to establish. The substring
    # guard refuses before `_locate` is ever reached, so taking the first of
    # several LINE hits changes nothing observable; and inside the substring
    # rung the `n > 1` raise sits above the replacement, so loosening the
    # replacement alone is unreachable. A case has to remove both layers to
    # produce the defect, and saying that plainly is better than shipping two
    # cases that look like coverage and are not.
    ("edit-names-one-place", CAPS_PY,
     lambda t: t.replace("    if n > 1:\n        raise EditNotUnique(",
                         "    if False:\n        raise EditNotUnique(", 1)
                .replace("        if len(hits) == 1:", "        if hits:", 1),
     "both uniqueness layers removed: the first of several matches is silently "
     "chosen out of many that looked the same, which is Aider's commented-out "
     "uniqueness check arriving here"),

    ("edit-names-one-place", CAPS_PY,
     lambda t: t.replace("    if n > 1:\n        raise EditNotUnique(",
                         "    if False:\n        raise EditNotUnique(", 1)
                .replace("    if n == 1:\n        after = before.replace(old, new, 1)",
                         "    if n >= 1:\n        after = before.replace(old, new, 1)", 1),
     "both layers removed on the substring path: an ambiguous substring is "
     "replaced at its first occurrence rather than refused"),

    ("edit-names-one-place", CAPS_PY,
     _sub("        deltas = [f - w for f, w in zip(found, wrote)] or [0]",
          "        deltas = [(found[0] - wrote[0]) if found and wrote else 0]", 1),
     "one indentation delta for the whole block again: a loosely matched block "
     "comes back flattened, and the edit reports success over a syntax error"),

    ("edit-names-one-place", CAPS_PY,
     _sub('    if not str(args.get("old") or ""):\n'
          '        # An edit with nothing to match is a whole-file write wearing the level\n'
          '        # of a surgical one, and it is the obvious way around this rule.\n'
          '        return "L5"',
          '    if False:\n        return "L5"', 1),
     "an edit with an empty `old` levels like a surgical change, so a "
     "whole-file replacement can be proposed as one and skip the escalation"),

    ("edit-names-one-place", INTENT_PY,
     # THE ELEMENT, NOT THE WHOLE TUPLE. Matching the entire `KNOWN` literal
     # meant every capability ever added broke this case: `agent.ask` with
     # delegation, `agent.run` with the specialised agents, `ui.open` on
     # 2026-09-04 -- which also wrapped it onto two lines. Three silent decays
     # for a case whose violation is one word.
     _sub('"fs.write", "fs.edit",', '"fs.write",', 1),
     "fs.edit is registered, implemented, verified and unreachable: the "
     "proposer cannot name it, so nothing can ever ask for one"),

    ("edit-names-one-place", CAPS_PY,
     _sub('    claimed = (result or {}).get("sha256")\n    return {"verified": on_disk == claimed,',
          '    claimed = (result or {}).get("sha256")\n    return {"verified": True,', 1),
     "the edit verifier cannot return False, so it is the actor's own claim "
     "wearing a second name"),
]


# --------------------------------------------------------------------------
# Shadow-git checkpoint and undo. Ranked first for safety per line, because it
# is the only defence here that does not depend on anything being right.
# --------------------------------------------------------------------------
CHECKPOINT_PY = "core/checkpoint.py"
EXECUTOR_PY = "core/executor.py"

CASES += [
    ("every-change-is-undoable", EXECUTOR_PY,
     _sub("        checkpoint_id = None\n        targets = touched_paths(capability_id, args)",
          "        checkpoint_id = None\n        targets = []", 1),
     "nothing is snapshotted before a write: the change happens and the world "
     "as it was when the decision was made is gone"),

    ("every-change-is-undoable", EXECUTOR_PY,
     _sub("            if self._shadow is None:", "            if False:", 1),
     "a write runs with no checkpoint store attached -- writing over the "
     "owner's data with the undo quietly unavailable, which is the one moment "
     "the undo exists for"),

    ("every-change-is-undoable", CAPS_PY,
     _sub('    "fs.edit": lambda args: [resolve(args.get("path"))],\n', "", 1),
     "fs.edit stops declaring what it touches, so surgical edits are the one "
     "kind of change with no undo behind them"),

    ("every-change-is-undoable", CAPS_PY,
     _sub('    "fs.write": lambda args: [resolve(args.get("path"))],',
          '    "fs.write": lambda args: [resolve(args.get("path"))],\n'
          '    "shell.run": lambda args: [resolve("workspace")],', 1),
     "shell.run claims to know what it touches: an undo that restores the "
     "wrong thing and reports success, which is worse than having none"),

    ("every-change-is-undoable", CHECKPOINT_PY,
     _sub("        return self.tree / str(p).lstrip(\"/\")",
          "        return self.tree / p.name", 1),
     "the shadow store is keyed on the basename, so two files called notes.txt "
     "in different folders overwrite each other's history -- and the undo "
     "restores one of them over the other"),

    ("every-change-is-undoable", CHECKPOINT_PY,
     _sub("                elif dst.exists():\n                    dst.unlink()", "                pass", 1),
     "a file that did not exist is not recorded as absent, so undoing its "
     "creation leaves the creation in place"),

    ("every-change-is-undoable", ACTOR_PY,
     _sub("SHADOW_ROOT = WORKSPACE.parent / \"shadow\"",
          "SHADOW_ROOT = REPO_APP_SHADOW", 1)
     if False else
     _sub('SHADOW_ROOT = WORKSPACE.parent / "shadow"',
          'SHADOW_ROOT = pathlib.Path("app/VESPER.app/Contents/Resources/shadow")', 1),
     "the undo history moves inside the app bundle, where build.sh deletes it "
     "-- so it disappears exactly when a rebuild makes it most useful"),
]


# --------------------------------------------------------------------------
# A tier no grant opens. Our ladder topped out at L5, so every safety property
# was contingent on one spoken yes from someone who may be half asleep.
# --------------------------------------------------------------------------
AUTHZ_PY2 = "core/authorize.py"

CASES += [
    ("prohibited-tier-no-grant-opens", AUTHZ_PY2,
     _sub("        why = prohibited(capability_id, args)\n"
          "        if why is not None:", "        why = None\n        if why is not None:", 1),
     "the prohibition is never consulted, so an L5 grant authorises erasing "
     "VESPER's own record of what it did"),

    ("prohibited-tier-no-grant-opens", AUTHZ_PY2,
     lambda t: t.replace(
         "        why = prohibited(capability_id, args)\n"
         "        if why is not None:\n"
         '            return self._deny(subject, cap, "prohibited", "L0", why)\n', "", 1)
       .replace("        grant = self.find(subject, capability_id)\n",
                "        why = prohibited(capability_id, args)\n"
                "        if why is not None and False:\n"
                '            return self._deny(subject, cap, "prohibited", "L0", why)\n'
                "        grant = self.find(subject, capability_id)\n", 1),
     "the prohibition moves below the grant lookup and stops firing: a tier a "
     "grant is consulted before is not a tier a grant cannot open"),

    ("prohibited-tier-no-grant-opens", CAPS_PY,
     # The tuple gained "interlock" when the stop landed, and this mutation
     # named the three-element version. It matched nothing from that moment on.
     _sub('SELF_DEFEATING_DIRS = ("shadow", "events", "audit", "interlock")',
          'SELF_DEFEATING_DIRS = ()', 1),
     "the self-defeating set is emptied, so the undo history and the event log "
     "are ordinary files again"),

    ("prohibited-tier-no-grant-opens", CAPS_PY,
     _sub("        parts = {q.lower() for q in target.parts}\n"
          "        if _under(target, WORKSPACE.parent) and parts & set(SELF_DEFEATING_DIRS):",
          "        p2 = str(target).lower()\n"
          "        if any(d in p2 for d in SELF_DEFEATING_DIRS):", 1),
     "path SEGMENTS become substrings and the scope is dropped: a note called "
     "'shadow puppets.txt' and the owner's own Documents/shadow folder both "
     "become unwritable -- a prohibition that catches everything is an outage"),

    ("prohibited-tier-no-grant-opens", CAPS_PY,
     _sub('        if raw and any(m in str(resolve(raw)).lower() for m in SECRET_MARKERS):\n'
          '            # READING IS THE STEP THAT PUTS IT IN A CONTEXT WINDOW, which is\n'
          '            # where it leaves. The ladder already says L5; this says that no\n'
          '            # answer to that question is yes.\n'
          '            return "this would read a credential into a model\'s context"',
          '        if False:\n            return "unreachable"', 1),
     "a credential can be read into a model's context on an L5 grant, which is "
     "the step that puts it where it leaves from"),
]


# --------------------------------------------------------------------------
# The outer loop gets hands. It ran on every pass of the runtime with one
# trigger registered and no reference to the actor -- a working engine with one
# instruction and nothing to do with the answer.
# --------------------------------------------------------------------------
AUTONOMY_PY = "core/autonomy.py"
SELF_DIRECTED_PY = "core/self_directed.py"

CASES += [
    ("autonomy-can-act-and-still-cannot-decide", AUTONOMY_PY,
     _sub("            if self._actor is None:", "            if True:", 1),
     "dispatch stops reaching the actor: triggers fire, publish an event, and "
     "nothing happens -- the state this closed"),

    ("autonomy-can-act-and-still-cannot-decide", SELF_DIRECTED_PY,
     # all_triggers grew host_pressure_trigger() and an optional compactor
     # trigger, so the two-element return this named no longer exists. Reducing
     # the list to one entry is still the mutation -- the check's claim is that
     # the loop has real work to consider, not that it has exactly two things.
     _sub("    out = [disk_pressure_trigger(), host_health_trigger(),\n"
          "           host_pressure_trigger()]",
          "    out = [disk_pressure_trigger()]", 1),
     "the loop is back to almost nothing to consider: it wakes, finds one "
     "thing, and sleeps"),

    ("autonomy-can-act-and-still-cannot-decide", SELF_DIRECTED_PY,
     _sub('        intent="check which directories are using the most disk space",',
          '        intent="",', 1),
     "a trigger fires with nothing to do, so it can only publish an event -- "
     "which is exactly what the whole layer could already do"),

    ("autonomy-can-act-and-still-cannot-decide", SELF_DIRECTED_PY,
     _sub("        return 0.0 <= float(v) < threshold", "        return True", 1),
     "the predicate stops reading the world and fires every tick: an action a "
     "healthy machine did not need, taken nightly, forever"),

    ("autonomy-can-act-and-still-cannot-decide", AUTONOMY_PY,
     _sub('                self._bus.publish(\n                    "autonomy.no_actor", subject=tid,',
          '                continue\n                self._bus.publish(\n                    "autonomy.no_actor", subject=tid,', 1),
     "a starved loop goes quiet instead of saying it has no hands, which is how "
     "this went unnoticed for as long as it did"),
]


# --------------------------------------------------------------------------
# Credentials out of the plaintext file. The one exact match between this
# system and OpenClaw's documented compromise.
# --------------------------------------------------------------------------
SUPPLY_PY2 = "routing/supply.py"

CASES += [
    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub("    for name in list(out):\n"
          "        got = keychain_secret(name)\n"
          "        if got:\n"
          "            out[name] = got\n", "", 1),
     "the keychain is never consulted, so a migrated credential is ignored and "
     "the plaintext file remains the only source"),

    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub("        got = keychain_secret(name)\n        if got:\n            out[name] = got",
          "        got = keychain_secret(name)\n        if got and name not in out:\n            out[name] = got", 1),
     "the file wins over the keychain, so migrating a credential means deleting "
     "it from the file in the same breath -- which is how one gets left behind"),

    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub('def keychain_secret(name: str, *, service: str | None = None) -> str:',
          'def keychain_secret(name: str, *, service: str = KEYCHAIN_SERVICE) -> str:', 1),
     "the service is bound as a default argument again: it looks identical, "
     "silently ignores the module constant it appears to read, and can never "
     "be varied by anything"),

    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub("    except Exception:                                # noqa: BLE001\n        return \"\"\n    if out.returncode != 0:\n        return \"\"",
          "    except Exception:                                # noqa: BLE001\n        raise\n    if out.returncode != 0:\n        return \"\"", 1),
     "a keychain that cannot be read raises instead of falling back: "
     "unattended, that takes every model away from VESPER over an item that "
     "was simply not there"),

    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub("_KEYCHAIN_TIMEOUT_S = 3.0", "_KEYCHAIN_TIMEOUT_S = 100000.0", 1),
     "the timeout is removed in all but name, so an access prompt nobody is "
     "awake to answer wedges the runtime instead of falling back"),
]


# --------------------------------------------------------------------------
# The second axis. Every level rule answers "how dangerous"; this answers "who
# wanted it", and only the second one sees a steered proposer.
# --------------------------------------------------------------------------
CASES += [
    ("authorization-strength-is-its-own-axis", AUTHZ_PY2,
     # ANCHORED ON THE ARGUMENT, not the whole call. `mode_ceiling` was
     # inserted into this `_min_level` on 2026-09-05 (the owner's permission
     # modes) and the five-line literal stopped matching, so the case reported
     # a changed artifact instead of testing the axis it is named for.
     _sub("                               mode_ceiling, auth_ceiling)",
          "                               mode_ceiling)", 1),
     "the axis is computed and dropped out of the minimum: an action nobody "
     "asked for carries the same authority as one the owner spoke"),

    ("authorization-strength-is-its-own-axis", AUTHZ_PY2,
     _sub('    "unknown": "L2",', '    "unknown": "L5",', 1),
     "a request nobody made is trusted like one the owner spoke aloud, which "
     "is the whole opening a steered proposer needs"),

    ("authorization-strength-is-its-own-axis", AUTHZ_PY2,
     _sub('    return AUTHORIZATION_CEILING.get(strength, "L0")',
          '    return AUTHORIZATION_CEILING.get(strength, "L5")', 1),
     "an unrecognised strength gets FULL authority, so a typo in a caller is "
     "more powerful than spelling it correctly"),

    ("authorization-strength-is-its-own-axis", ACTOR_PY,
     _sub('        if period == "free_time":\n            return "unknown"\n'
          '        return "owner_task" if observations else "owner_explicit"',
          '        return "owner_explicit"', 1),
     "every action claims the owner asked for it outright, including the ones "
     "an autonomous trigger produced while they were asleep"),

    ("authorization-strength-is-its-own-axis", AUTHZ_PY2,
     _sub('            if LEVEL_RANK[auth_ceiling] < LEVEL_RANK[required]:\n'
          '                reason = "weak_authorization"\n'
          '            elif',
          '            if False:\n                reason = "weak_authorization"\n'
          '            elif', 1),
     "the refusal stops naming the axis that bound it, so 'nobody asked for "
     "this' and 'a web page is in context' become the same answer to the owner"),
]


# --------------------------------------------------------------------------
# A decline is not an attempt. Found by reading the running system's own log:
# 610,931 repair.attempted events over 41 hours, all the same item, all the
# same answer -- most of a 1.6 GB durable log.
# --------------------------------------------------------------------------
TRIAGE_PY = "core/triage.py"

CASES += [
    ("a-decline-is-not-an-attempt", RUNTIME,
     _sub("            for item in (triage.open_items(CRITICAL_NOW) or [])[:1]:",
          "            for item in (triage.open_items() or [])[:1]:", 1),
     "the pump goes back to offering the head of the whole queue, so an item "
     "the repairer refuses by definition is declined into the durable log on "
     "every single pass -- 15,000 times an hour, measured"),

    ("a-decline-is-not-an-attempt", TRIAGE_PY,
     _sub("        return [i for i in items if i.grade == grade and i.resolution is None]",
          "        return [i for i in items if i.resolution is None]", 1),
     "open_items accepts a grade and ignores it: the pump's filter is present, "
     "reads correctly, and buys nothing"),

    ("a-decline-is-not-an-attempt", "core/repair.py",
     _sub("        if item.grade != CRITICAL_NOW:", "        if False:", 1),
     "unattended repair stops being limited to failures that are down and will "
     "stay down -- making the filter look unnecessary by removing the refusal "
     "it exists to avoid provoking"),
]


CASES += [
    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub("        if kc and kc != v:", "        if False:", 1),
     "a key rotated in the file after migration is no longer reported, so the "
     "keychain goes on serving the old value and nothing says so"),

    ("credentials-can-leave-the-plaintext-file", SUPPLY_PY2,
     _sub('        if kc and kc != v:\n            out.append({"name": name, "file_len": len(v), "keychain_len": len(kc),',
          '        if kc and kc != v:\n            out.append({"name": name, "file_value": v, "keychain_len": len(kc),', 1),
     "the mismatch report carries the credential itself, so a warning meant to "
     "protect a key prints it into every place the warning travels"),

    # THE WIRING, REMOVED RATHER THAN NEUTERED. Replacing the import with a
    # lambda that returns [] is the more realistic defect and a SOURCE check
    # cannot see it -- every name it looks for is still on the page. That is
    # the fourth time this session a name test has been satisfied by a name the
    # mutation did not touch, and the honest fix is to test what a source check
    # CAN see: the wiring being gone. The reporter's own behaviour is covered
    # by the two cases above, which drive it.
    ("credentials-can-leave-the-plaintext-file", RUNTIME,
     lambda t: t[:t.index("    try:\n        from routing.supply import credential_mismatches")]
               + t[t.index('                    payload={"error": repr(exc)}, component="runtime")\n',
                          t.index("from routing.supply import credential_mismatches"))
                   + len('                    payload={"error": repr(exc)}, component="runtime")\n'):],
     "the startup credential check is removed entirely, so a key rotated in the "
     "file after migration is detectable and undetected -- and the home card "
     "has no event to render"),
]


# --------------------------------------------------------------------------
# L1's budget is tokens, not a fact count. ContextBudgetManager was built for
# this and constructed only by tests -- the fifth "built, gated, reached by
# nothing", and one CI-094 could not see.
# --------------------------------------------------------------------------
BLOCKS_PY = "core/blocks.py"
CONTEXT_PY = "core/context.py"

CASES += [
    ("l1-spends-a-token-budget", BLOCKS_PY,
     _sub("        if self._budget is not None:", "        if False:", 1),
     "block B truncates at a fact COUNT again: five long facts overrun the "
     "provider's window and five short ones waste it, and nothing counts"),

    ("l1-spends-a-token-budget", RUNTIME,
     _sub("        renderer = L1Renderer(persona, memory,\n"
          "                              budget=ContextBudgetManager(\n"
          "                                  bus, budget_tokens=L1_BUDGET_TOKENS))",
          "        renderer = L1Renderer(persona, memory)", 1),
     "the runtime builds the renderer with no budget, so the manager goes back "
     "to being constructed only by its own tests"),

    ("l1-spends-a-token-budget", BLOCKS_PY,
     _sub("    return max(1, (len(text) + 3) // 4)", "    return 1", 1),
     "every fact is costed at one token, so the budget is consulted, always "
     "fits, and decides nothing -- the shape a check that only asserts 'a "
     "budget was passed' cannot see"),

    # THE SORT IS NOT WHAT PROTECTS A PINNED FRAGMENT -- `or f.pinned` in the
    # admission test is, and it short-circuits regardless of order. Mutating
    # the sort key changes the ORDER and drops nothing, so the case written
    # against it reported green. This one removes the guard that actually
    # holds.
    ("l1-spends-a-token-budget", CONTEXT_PY,
     _sub("            if out.tokens_used + f.tokens <= self.budget_tokens or f.pinned:",
          "            if out.tokens_used + f.tokens <= self.budget_tokens:", 1),
     "a pinned fragment is dropped to fit the budget: the owner named it, and "
     "manual mode becomes a suggestion the selector may overrule"),
]


CASES += [
    ("gated-subsystems-are-reachable", CHECKS_PY,
     _sub('    for f in sorted(REPO.glob("core/*.py")):\n'
          '        rel = f.relative_to(REPO).as_posix()\n'
          '        if f.name != "__init__.py":\n'
          '            subjects.setdefault(rel, [])\n', "", 1),
     "the sweep narrows back to modules some check happens to NAME as a "
     "subject -- 50 of 76 -- so a subsystem nobody wrote a check for is "
     "invisible to the check that exists to find subsystems nobody reaches"),
]


# --------------------------------------------------------------------------
# The consolidation loop. core/compactor.py holds the rule the whole memory
# design rests on and nothing in the running system imported it.
# --------------------------------------------------------------------------
CASES += [
    ("memory-repairs-its-own-drift", SELF_DIRECTED_PY,
     _sub("        return s.get(DRIFT_TERM) is True", "        return True", 1),
     "the predicate stops reading the world: L2 is dropped and rebuilt on every "
     "tick, which is a maintenance pass wearing a condition's clothes"),

    ("memory-repairs-its-own-drift", SELF_DIRECTED_PY,
     _sub("        report = compactor.verify()\n        if report.get(\"converged\"):\n"
          "            return {\"converged\": True, \"reprojected\": False}",
          "        report = compactor.verify()\n        if True:\n"
          "            return {\"converged\": True, \"reprojected\": False}", 1),
     "drift is noticed and never repaired: the finding is published and L2 goes "
     "on diverging from the log it is a view of"),

    ("memory-repairs-its-own-drift", SELF_DIRECTED_PY,
     _sub("        debounce_s=900,\n        handler=handler,", "        debounce_s=900,", 1),
     "the trigger loses its handler, so it fires and repairs nothing -- the "
     "state the whole autonomy layer was in until yesterday"),

    ("memory-repairs-its-own-drift", RUNTIME,
     _sub("        autonomy.register(memory_drift_trigger(compactor))", "        pass", 1),
     "the compactor is built and registered with nothing, so it goes back to "
     "being imported and never run"),
]


CASES += [
    ("contradictions-reach-the-owner", SELF_DIRECTED_PY,
     _sub("        return s.get(CONTRADICTION_TERM) is True", "        return True", 1),
     "the predicate stops reading the world and arbitrates on every tick, "
     "which is a sweep on a timer wearing a condition's clothes"),

    ("contradictions-reach-the-owner", SELF_DIRECTED_PY,
     # THE ROW ITSELF CARRIES NO VALUE FOR AN ASK -- the resolver
     # returns None rather than a pick -- so stringifying it leaks
     # nothing and the case written that way reported green. What
     # WOULD leak is attaching the claims, which is exactly what
     # somebody adds when debugging why a question was raised.
     _sub('                "questions": [f"{r[\'subject\']}/{r[\'attribute\']}" for r in asks]}', '                "questions": [f"{r[\'subject\']}/{r[\'attribute\']}" for r in asks],\n                "claims": [arbiter.claims_for(r[\'subject\'], r[\'attribute\']) for r in asks]}', 1),
     "the published question is enriched with the claims behind it, "
     "so both competing values reach an event anything can read -- "
     "and one of them is wrong, with nothing to tell them apart"),

    ("contradictions-reach-the-owner", SELF_DIRECTED_PY,
     _sub("        debounce_s=600,\n        handler=handler,", "        debounce_s=600,", 1),
     "the trigger loses its handler: contradictions are detected and never "
     "arbitrated, so the question never exists"),

    ("contradictions-reach-the-owner", RUNTIME,
     _sub("        autonomy.register(contradiction_trigger(arbiter))", "        pass", 1),
     "the arbiter is built and registered with nothing, so memory goes on "
     "contradicting itself and the updater -- which cannot ask -- is the only "
     "thing that ever sees it"),
]


# --------------------------------------------------------------------------
# The stop. core/interlock.py was built, gated by A-031, and reachable from
# nothing -- so VESPER could act and there was no stop to press.
# --------------------------------------------------------------------------
INTERLOCK_PY = "core/interlock.py"

CASES += [
    ("autonomy-stops-when-nothing-arms-it", AUTONOMY_PY,
     _sub("        if self._interlock is not None and not self._interlock.autonomy_permitted():",
          "        if False:", 1),
     "the loop stops consulting the interlock: an engaged stop changes nothing "
     "and a dead minter stops nothing"),

    ("autonomy-stops-when-nothing-arms-it", INTERLOCK_PY,
     _sub("            if self._token is None:\n                return False", "            if False:\n                return False", 1),
     "no token at all counts as armed, so a fresh install and a crashed minter "
     "both leave autonomy running -- the kill-signal failure mode, arrived at "
     "from the other direction"),

    ("autonomy-stops-when-nothing-arms-it", INTERLOCK_PY,
     _sub("            return self._now_ms() < self._token.expires_at_ms()",
          "            return True", 1),
     "an expired token still arms autonomy: the switch stops being dead-man's "
     "and becomes a one-time permission that never lapses"),

    ("autonomy-stops-when-nothing-arms-it", CAPS_PY,
     _sub('SELF_DEFEATING_DIRS = ("shadow", "events", "audit", "interlock")',
          'SELF_DEFEATING_DIRS = ("shadow", "events", "audit")', 1),
     "VESPER can write its own enable token, so a steered proposer arms the "
     "autonomy that is about to run its next proposal"),

    ("autonomy-stops-when-nothing-arms-it", RUNTIME,
     _sub("    autonomy.attach_interlock(interlock)", "    pass", 1),
     "the interlock is built and handed to nothing, which is exactly the state "
     "it was in before today"),
]


# --------------------------------------------------------------------------
# Exactly-once EFFECT. core/reconcile.py was built and reached by nothing --
# which mattered less when VESPER took one action per utterance than it does
# now that a turn can take six.
# --------------------------------------------------------------------------
CASES += [
    ("outbox-written-before-the-effect", EXECUTOR_PY,
     _sub("        outbox_id = None\n        if self._reconciler is not None and getattr(cap, \"external_effect\", False):",
          "        outbox_id = None\n        if False:", 1),
     "nothing is recorded before an external action: a crash between the send "
     "and the record leaves the system unable to tell 'not sent' from 'sent, "
     "result lost', and a resumed task re-sends"),

    ("outbox-written-before-the-effect", EXECUTOR_PY,
     _sub("        if outbox_id is not None:\n"
          "            self._reconciler.mark(outbox_id, \"CONFIRMED\", result)",
          "        if False:\n"
          "            self._reconciler.mark(outbox_id, \"CONFIRMED\", result)", 1),
     "a completed action is never confirmed, so recovery cannot tell it from "
     "one that never finished and re-sends it"),

    ("outbox-written-before-the-effect", EXECUTOR_PY,
     _sub('                self._reconciler.mark(outbox_id, "UNKNOWN")\n'
          "            return self._handle_failure(eid, cap, subject, args, key, e, task_id)",
          "            return self._handle_failure(eid, cap, subject, args, key, e, task_id)", 1),
     "an implementation that raised leaves no UNKNOWN: from in here a raise "
     "after the effect landed looks exactly like one before it, and treating "
     "it as a plain failure licences a retry of something already done"),

    ("outbox-written-before-the-effect", EXECUTOR_PY,
     _sub("                reconcilable=False))", "                reconcilable=True))", 1),
     "shell.run claims to be reconcilable, promising a probe that can ask "
     "whether a command landed -- there is none, which is why it has no "
     "independent verifier either, and recovery would retry instead of asking"),
]


# --------------------------------------------------------------------------
# SR-007's map, built and kept true. Everything, with submaps mapping their own
# parts -- the owner's instruction, and the shape build() already produces.
# --------------------------------------------------------------------------
MAP_PY = "core/knowledge_map.py"

CASES += [
    ("map-built-and-kept-true", SELF_DIRECTED_PY,
     _sub("        return s.get(MAP_TERM) is True", "        return True", 1),
     "the predicate stops reading the world and re-indexes on every tick, "
     "which is the nightly re-index REM-007 names as the wrong shape"),

    ("map-built-and-kept-true", SELF_DIRECTED_PY,
     _sub("            if stale:\n                # REBUILT, NOT PATCHED.", "            if False:\n                # REBUILT, NOT PATCHED.", 1),
     "staleness is noticed and the map is never rebuilt, so it goes on "
     "answering 'look here' with locators that have moved"),

    ("map-built-and-kept-true", MAP_PY,
     _sub("            current = self._hash_of(n)\n            if current != n.content_hash:",
          "            current = self._hash_of(n)\n            if False:", 1),
     "refresh stops comparing hashes, so a changed corpus never reads as stale "
     "and the map is frozen at whatever it was when it was built"),

    ("map-built-and-kept-true", RUNTIME,
     _sub("        autonomy.register(map_staleness_trigger(maps))", "        pass", 1),
     "the maps are built and nothing keeps them true -- which is worse than "
     "not building them, because a stale locator is a confident wrong answer"),
]


# --------------------------------------------------------------------------
# The self-modification boundary, finally asked. Built, gated by CI-015 against
# the real repository, and consulted by nothing.
# --------------------------------------------------------------------------
SELFMOD_PY = "core/selfmod.py"

CASES += [
    ("boundary-asked-before-the-write", EXECUTOR_PY,
     _sub("        if self._selfmod is not None:\n"
          "            for target in touched_paths(capability_id, args):",
          "        if False:\n"
          "            for target in touched_paths(capability_id, args):", 1),
     "the executor stops asking the boundary: a governed path in the running "
     "artifact is writable again under a sufficient grant, which is the state "
     "A-030's overnight injected-content fixture exists to catch"),

    ("boundary-asked-before-the-write", SELFMOD_PY,
     _sub("        if not self.is_governed(rel):\n            return",
          "        if True:\n            return", 1),
     "nothing is governed any more, so the boundary is consulted, answers yes "
     "to everything, and reads exactly like enforcement"),

    ("boundary-asked-before-the-write", SELFMOD_PY,
     # ONLY THE `in_workspace` HALF IS REACHABLE. No governed prefix lives
     # under `workspace/`, so the path half exits one line later at
     # `not is_governed` regardless, and deleting the whole line changes
     # nothing a path-based probe can see.
     _sub("        if in_workspace or rel.startswith(WORKSPACE_PREFIX):\n            return",
          "        if rel.startswith(WORKSPACE_PREFIX):\n            return", 1),
     "a caller stating the write is happening in a workspace copy is ignored, "
     "so A-030.6 fails: VESPER can no longer draft a governed change where it "
     "is allowed to and propose it in the morning -- the over-restriction "
     "PATCH-018's control exists to catch"),

    ("boundary-asked-before-the-write", ACTOR_PY,
     _sub("        self._selfmod = selfmod if selfmod is not None else SelfModificationBoundary(\n"
          "            bus, repo_root=REPO_ROOT)",
          "        self._selfmod = selfmod", 1),
     "the actor stops building a boundary, so nothing is passed to the "
     "executor and the check it performs is skipped entirely"),
]


# --------------------------------------------------------------------------
# The floor. core/barge_in.py had 242 phrases and a gate and was called by
# NOTHING; core/floor.py joins it to the hold and was reached by nothing.
# --------------------------------------------------------------------------
FLOOR_PY = "core/floor.py"

CASES += [
    ("floor-held-and-offered-to", RUNTIME,
     _sub("            if floor is not None and floor.holding:", "            if False:", 1),
     "the pump stops offering mid-hold utterances to the floor, so barge_in is "
     "uncalled again and every interruption becomes an ordinary new turn"),

    ("floor-held-and-offered-to", RUNTIME,
     _sub('                floor.hold("answering")', "                pass", 1),
     "nothing ever takes the floor, so no utterance is ever mid-hold and the "
     "classifier is reachable in principle and unreached in fact"),

    ("floor-held-and-offered-to", FLOOR_PY,
     _sub('            v = Verdict(floor=verdict.value, text=text, acted=False,\n                        answer=False, queued=False)\n        elif verdict is Floor.STATUS:', '            v = Verdict(floor=verdict.value, text=text, acted=False,\n                        answer=True, queued=False)\n        elif verdict is Floor.STATUS:', 1),
     "a cooperative interruption gets answered: 'take your time' met with a "
     "reply is VESPER interrupting the owner's permission not to be "
     "interrupted -- the outcome most likely to be got wrong, because "
     "answering is polite"),

    ("floor-held-and-offered-to", FLOOR_PY,
     _sub("            with self._lock:\n                self._queue.append(text)", "            pass", 1),
     "a follow-on request is classified as queued and never stored, so the "
     "owner learns that speaking during a hold loses what they said"),

    ("floor-held-and-offered-to", FLOOR_PY,
     _sub("        verdict = classify(text)", "        verdict = Floor.BREAK", 1),
     "every mid-hold utterance cancels the work: 'mhm' abandons the answer the "
     "owner was waiting for"),
]


# --------------------------------------------------------------------------
# The platform's own signals, translated. core/host.py exists because the
# numbers do not port, and it was imported by nothing.
# --------------------------------------------------------------------------
HOST_PY = "core/host.py"

CASES += [
    ("host-pressure-read-through-the-adapter", RUNTIME,
     _sub("            return bool(host_adapter.read_pressure().degraded)",
          "            return bool(host_adapter.read_pressure().memory_pressure_band > 60)", 1),
     "shared logic judges a raw platform number: a memory band meaning "
     "'healthy' on one host means 'about to fail' on another, which is the one "
     "thing core/host.py exists to prevent"),

    ("host-pressure-read-through-the-adapter", SELF_DIRECTED_PY,
     _sub('        intent="check which processes are using the most memory and cpu",',
          '        intent="kill the process using the most memory",', 1),
     "the trigger becomes a second scheduler reacting to the platform's own "
     "governor -- which is how two schedulers on one machine start oscillating, "
     "each responding to the other's response"),

    ("host-pressure-read-through-the-adapter", SELF_DIRECTED_PY,
     _sub("        return s.get(PRESSURE_TERM) is True", "        return True", 1),
     "the predicate stops reading the world and fires on every tick, so a "
     "healthy machine is investigated forever"),

    ("host-pressure-read-through-the-adapter", RUNTIME,
     _sub('    host_adapter = host_module.adapter_for_host()', '    host_adapter = None', 1),
     "no adapter is built, so the platform's signals reach nothing translated "
     "and core/host.py goes back to being imported and unused"),
]


# --------------------------------------------------------------------------
# The record of what VESPER answered. Built FIRST on purpose and reached by
# nothing, so no turn was ever recorded.
# --------------------------------------------------------------------------
BASELINE_PY = "core/baseline.py"

CASES += [
    ("every-turn-recorded-with-its-outcome", RUNTIME,
     _sub("                if baseline is not None:\n"
          "                    if did is not None:",
          "                if False:\n"
          "                    if did is not None:", 1),
     "no turn is recorded, so every comparative question about memory -- does "
     "it help, does it cost more than it returns -- stays unanswerable"),

    ("every-turn-recorded-with-its-outcome", RUNTIME,
     _sub('                                   "refused": "declined",\n'
          '                                   "failed": "could_not"}.get(did.kind,\n'
          '                                                              "could_not")',
          '                                   "refused": "declined",\n'
          '                                   "failed": "declined"}.get(did.kind,\n'
          '                                                              "declined")', 1),
     "a failure is recorded as a choice: afterwards nothing can tell an answer "
     "VESPER withheld from one it could not produce, and that is the single "
     "distinction this record exists to preserve"),

    ("every-turn-recorded-with-its-outcome", BASELINE_PY,
     _sub("    outcome: str                      #", "    outcome: str = \"answered\"  #", 1),
     "outcome gains a default, so every caller can skip the one decision that "
     "cannot be made afterwards -- and the log fills with 'answered'"),

    ("every-turn-recorded-with-its-outcome", BASELINE_PY,
     _sub("            self.failed += 1", "            pass", 1),
     "a failed write is not counted, so an unexplained gap in the record is "
     "indistinguishable from a quiet period"),
]


# --------------------------------------------------------------- CI-095/096
# REGISTERED 2026-09-02. Both checks had been red-run by hand and neither was in
# this file -- and `ci-registry` refused to count them for exactly that reason:
# it derives coverage from THIS list rather than from a claim, because "a
# coverage claim maintained by hand is the thing this is checking for".
# Declaring the mutations here turns those one-off runs into evidence that
# survives the next person moving the code.
CASES += [
    ("a-sub-agent-thinks-and-never-acts", CAPS_PY,
     _sub('    "agent.ask": EXTERNAL,', '    "agent.ask": "verified_local",', 1),
     "a sub-agent's answer becomes trusted local content, so delegation "
     "launders untrusted material into a proposal with no trace of its origin"),

    ("a-sub-agent-thinks-and-never-acts", CAPS_PY,
     # ANCHORED WITH ITS OWN COMMENT, because the line alone is no longer
     # unique: `agent_run_level` carries the identical test and is defined
     # FIRST, so a bare `_sub(..., 1)` retargeted onto it and left
     # `agent_ask_level` -- the function this case asserts on -- untouched. The
     # violation ran green. Fourth time a mutation has landed on the wrong copy
     # of a line in this session.
     _sub("    if len(material) > SUBAGENT_MATERIAL_L3:\n"
          "        # Sending a lot of the owner's material to a provider is a bigger act",
          "    if False:\n"
          "        # Sending a lot of the owner's material to a provider is a bigger act", 1),
     "shipping the owner's material to a provider in bulk costs the same as "
     "asking about a paragraph"),

    ("a-sub-agent-thinks-and-never-acts", SUBAGENT_PY,
     _sub('        mat = str(material or "")[:MAX_CONTEXT_CHARS]',
          '        mat = str(material or "")', 1),
     "a sub-agent accepts unbounded material, so delegation is a way to spend "
     "the parent's context somewhere it cannot be seen"),

    ("a-sub-agent-thinks-and-never-acts", INTENT_PY,
     # The element this case is actually about -- see the note on
     # `edit-names-one-place` for why the whole-tuple literal kept decaying.
     _sub('"agent.ask", "agent.run")', '"agent.run")', 1),
     "no proposal may name agent.ask, so delegation is built and reachable from "
     "nothing -- the state fifteen other subsystems were found in"),

    ("the-loop-ticks-at-the-cadence-it-declares", AUTONOMY,
     _sub("        if self._last_tick_ms is None:\n            return True",
          "        if True:\n            return True", 1),
     "due() is always true, so the loop runs at the pump's cadence again and the "
     "interval it declares is decoration"),

    ("the-loop-ticks-at-the-cadence-it-declares", AUTONOMY,
     _sub("        return (now - self._last_tick_ms) >= self.tick_interval_s * 1000.0",
          "        return False", 1),
     "due() is always false: the loop ticks once and never again"),

    ("the-loop-ticks-at-the-cadence-it-declares", RUNTIME,
     _sub("            if autonomy.due():", "            if True:", 1),
     "the pump stops consulting the declared cadence"),

    # THE STANDING-EXPIRY MUTATION BELONGS TO A DIFFERENT CHECK, and putting it
    # here was a labelling error caught by the harness on its first run: this
    # check knows nothing about grant expiry, so the violation ran green. The
    # assertion that expiry is relative lives in
    # `a-question-does-not-end-the-turn`, and moves there when that check is
    # registered. What belongs HERE is the ordering the stop depends on.
    ("the-loop-ticks-at-the-cadence-it-declares", RUNTIME,
     _sub("            if interlock is not None:\n                _present_enable_token(interlock)",
          "            if interlock is not None:\n                pass", 1),
     "the enable token is no longer presented on the fast pass, so nothing arms "
     "the interlock and autonomy fails toward stopped every interval -- A-031.1 "
     "declares a 2 s T_new_action budget and this is how it silently stops "
     "being true"),
]


# ------------------------------------------------- 2026-09-03: the night's own
# EVERY MUTATION BELOW WAS EXECUTED BY HAND when its check was written, and none
# of them was in this file -- so `ci-registry` refused to count any of those
# checks, correctly: it derives coverage from THIS list rather than from a
# claim, "because a coverage claim maintained by hand is the thing this is
# checking for". A red run I did once is not evidence that survives the next
# person moving the code. Declaring them here is what makes it one.
CASES += [
    ("silence-is-recorded-once-not-every-tick", AUTONOMY,
     _sub("                if changed or stale:", "                if True:", 1),
     "silence is written once per trigger per tick again: 619,063 identical "
     "records in 41.8 hours from ONE trigger, and five would have written 1.78 "
     "million a day"),

    ("silence-is-recorded-once-not-every-tick", AUTONOMY,
     _sub("                stale = (not changed\n"
          "                         and self.ticks - last_pub >= NOOP_KEEPALIVE_TICKS)",
          "                stale = False", 1),
     "the keepalive never fires, so a trigger whose world never changes is "
     "heard from exactly once and 'last heard from' becomes unbounded"),

    ("the-stop-reaches-work-already-running", ACTOR_PY,
     _sub("            if permitted is not None and not permitted():",
          "            if False:", 1),
     "the stop is asked nowhere inside the loop: pressing it mid-turn stops the "
     "NEXT dispatch and lets the remaining steps run, each a shell command or a "
     "file write the owner had already said to stop"),

    ("the-stop-reaches-work-already-running", AUTONOMY,
     _sub("                    permitted=(self._interlock.autonomy_permitted",
          "                    permitted=(None or self._interlock.autonomy_permitted", 1),
     "dispatch stops handing the interlock to the actor, so autonomous work is "
     "not covered by the stop at all"),

    ("the-stop-reaches-work-that-outlives-the-turn", BACKGROUND_PY,
     _sub("                os.killpg(os.getpgid(pid), sig)", "                os.kill(pid, sig)", 1),
     "the kill reaches the process and not its group: `npm test`'s children "
     "keep running after the stop with nothing holding a handle to them"),

    ("the-stop-reaches-work-that-outlives-the-turn", BACKGROUND_PY,
     _sub("                       and (period is None or j.period == period)]",
          "                       ]", 1),
     "stopping AUTONOMY also kills the work the owner asked for -- and an owner "
     "who loses their build to the stop will not press it again"),

    ("a-question-does-not-end-the-turn", CONFIRM_PY,
     _sub("            if not req.asked:\n                raise NotTheQuestionInFront(",
          "            if False:\n                raise NotTheQuestionInFront(", 1),
     "a bare 'yes' settles a question that is NOT in front of the owner: "
     "anything said while it was queued is a yes to something else, and acting "
     "on it is consent they never gave"),

    ("a-question-does-not-end-the-turn", AUTHZ_PY,
     _sub("        return max(usable, key=lambda g: LEVEL_RANK[g.max_level])",
          "        return cands[0]", 1),
     "find() returns the first grant by insertion order again, so the grant an "
     "answered question buys is unreachable behind the standing one and the "
     "owner can say yes with nothing happening"),

    ("advice-can-add-caution-and-never-remove-it", ADVISOR_PY,
     _sub('        verdict = STOP if "VERDICT: STOP" in upper else PROCEED',
          '        verdict = PROCEED if "VERDICT: PROCEED" in upper else STOP', 1),
     "a garbled answer halts the turn, so every provider hiccup surfaces as a "
     "warning and the owner learns to wave them through"),

    ("advice-can-add-caution-and-never-remove-it", ACTOR_PY,
     _sub('                if seen.get("verdict") == ADVISOR_STOP:',
          '                if seen.get("verdict") != ADVISOR_STOP:', 1),
     "PROCEED starts authorising things, which makes advice a way to "
     "manufacture the owner's consent: feed it material arguing for the action "
     "and receive approval"),

    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY,
     _sub("        if len(text) < MIN_ANSWER_CHARS:", "        if False:", 1),
     "empty output is passed on as an answer, and a blank reads as 'nothing to "
     "report' rather than 'nothing was produced'"),

    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY,
     _sub("        if truncated:\n            # TRUNCATION IS UNAVAILABILITY",
          "        if False:\n            # TRUNCATION IS UNAVAILABILITY", 1),
     "truncation becomes a shorter answer: a cut-off investigation reads as "
     "complete and stops before the part that mattered"),

    ("a-withdrawn-model-descends-instead-of-being-retried", HTTP_PY,
     _sub('    410: "bad_request",', '    410: "server_error",', 1),
     "410 Gone is retried again: a model the provider has WITHDRAWN is re-asked "
     "until the retry budget runs out, on every turn reaching that rung"),

    ("a-withdrawn-model-descends-instead-of-being-retried", HTTP_PY,
     _sub('    429: "rate_limited",', '    429: "bad_request",', 1),
     "a rate limit retires the rung, removing a working provider from the "
     "ladder over one busy moment"),

    ("a-compressed-archive-is-still-a-readable-log", STORE_PY,
     _sub("                        row[2] = self._inflate(bytes(row[2]), zdict)",
          "                        pass", 1),
     "reads stop decompressing, so a compressed archive is unreadable and the "
     "original has already been replaced by then"),

    ("a-compressed-archive-is-still-a-readable-log", STORE_PY,
     _sub("        if not same:\n            tmp.unlink(missing_ok=True)\n            raise ValueError(",
          "        if False:\n            tmp.unlink(missing_ok=True)\n            raise ValueError(", 1),
     "the copy is no longer verified before the original is deleted -- the one "
     "operation in this system that can lose history silently"),

    ("a-rotated-log-keeps-one-sequence-and-loses-nothing", STORE_PY,
     _sub('            fresh.execute("INSERT INTO sqlite_sequence(name, seq) VALUES(?,?)",',
          '            fresh.execute("SELECT ?, ?", ') if False else
     # THE *INSERT* IS THE SEEDING. Removing the DELETE beside it changes
     # nothing -- `sqlite_sequence` is empty in a fresh segment anyway, which
     # the comment there says outright -- so that mutation ran green.
     _sub('            seeded.execute(\n'
          '                "INSERT INTO sqlite_sequence(name, seq) VALUES(\'records\', ?)",\n'
          '                (high,))',
          '            pass', 1),
     "the sequence restarts at 1 in a new segment, so a tombstone for seq 42 in "
     "the old one silently erases a DIFFERENT record at seq 42 in the new"),

    ("a-shell-session-carries-context-not-a-shell", CAPS_PY,
     _sub("        if str(k).upper() in ENV_NEVER_SETTABLE:", '        if str(k) in ("NOPE",):', 1),
     "PATH becomes settable, so the argv the level rules classified is not the "
     "program that runs -- and nobody can see the difference between a fine "
     "PATH and an attack"),

    ("a-read-window-moves-and-proves-only-what-it-saw", CAPS_PY,
     _sub("    complete = offset == 0 and len(whole) <= limit", "    complete = True", 1),
     "a partial read hands back the whole-file token, so seeing one page "
     "authorises replacing all of it at a level the owner is never asked about"),

    ("a-batch-read-is-one-action-at-its-worst-level", CAPS_PY,
     _sub("        worst = \"L1\"\n"
          "        for one in batch:\n"
          "            worst = _worst(worst, fs_read_level({\"path\": one}))\n"
          "        return worst",
          "        return fs_read_level({\"path\": batch[0]})", 1),
     "a batch is levelled on its FIRST member, so burying a credential among "
     "ordinary files is a cheaper door to it"),

    ("compaction-never-eats-its-own-summaries", COMPACTOR_PY,
     _sub('            if int(f.get("rank", 0)) >= 5:\n                continue',
          "            if False:\n                continue", 1),
     "a compaction's own rank-5 output becomes its next input, so each run "
     "summarises the last summary and L2 drifts off the log it is a view of"),

    ("an-mcp-server-does-not-level-its-own-tools", MCP_PY,
     _sub('                "level": UNLEVELLED,', '                "level": t.get("level") or UNLEVELLED,', 1),
     "an MCP server levels its own tools, which is a server asserting the thing "
     "the ladder exists to decide"),

    ("the-runtime-resolves-every-name-it-uses", RUNTIME,
     _sub("         floor=None, baseline=None, interlock=None, jobs=None,",
          "         floor=None, baseline=None, jobs=None,", 1),
     "the pump reads `interlock` from another function's scope again: NameError "
     "every pass, swallowed by the broad handler, and the autonomy loop never "
     "ticks while reporting a handled failure"),

    ("a-level-rule-means-what-it-says-and-names-what-it-refuses", CAPABILITY_PY,
     _sub("            if lvl != r.level:\n                raise LevelRuleContradicted(",
          "            if False:\n                raise LevelRuleContradicted(", 1),
     "a rule may declare one level while its own example resolves another, so "
     "the declared levels a reader learns the ladder from are documentation "
     "rather than assertion"),

    ("a-level-rule-means-what-it-says-and-names-what-it-refuses", CAPABILITY_PY,
     _sub("                if got == r.level:\n                    raise LevelRuleContradicted(",
          "                if False:\n                    raise LevelRuleContradicted(", 1),
     "a counter-example that reaches the rule's own level registers, so the rule "
     "fails to distinguish the case it was written to distinguish and nothing "
     "says so"),
]


# --------------------------------------------------------------------------
# The wake path deletes the clip it just transcribed. INV-PRIV-3 says raw media
# is not kept beyond its processing window, and a continuously-open microphone
# is the one place in this system where that is a standing promise rather than
# a per-request one. Ratified as CI-104 on 2026-09-03; before that the check
# ran green in every sweep and counted toward nothing.
# --------------------------------------------------------------------------
CASES += [
    ("wake-word-listens-locally-and-starts-once", RUNTIME_PY,
     _sub("                pathlib.Path(path).unlink()     # the audio is not kept",
          "                pass  # the audio is kept", 1),
     "the captured clip is never deleted, so every wake-word utterance leaves a "
     "raw recording of the room on disk after it has been transcribed"),
]

# --------------------------------------------------------------------------
# A rung that is out of quota is not a rung that answered. Nine agent rungs
# share one Claude subscription; on 2026-09-03 it printed "You've hit your
# session limit" as ordinary stdout, 65 characters -- past every length bound
# in the runner, and returned as the agent's considered answer.
# --------------------------------------------------------------------------
AGENTS_PY_Q = "core/agents.py"

CASES += [
    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY_Q,
     _sub('    "hit your session limit",\n', "", 1),
     "a rung reporting it has hit its session limit is no longer recognised, "
     "so the quota notice is handed to the caller as the agent's finding while "
     "every lower rung sits idle"),

    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY_Q,
     _sub("    if len(text) > MAX_EXHAUSTION_CHARS:\n        return None\n",
          "    if False:\n        return None\n", 1),
     "the length bound is removed, so an agent DISCUSSING a rate limit at "
     "length is misread as a rung refusing for quota and a working rung is "
     "abandoned on the strength of its wording"),
]


# --------------------------------------------------------------------------
# Each rung's CLI takes its own flags. Claude's set was used for every binary,
# so codex agents exited 2 before reading their prompt: `-p` is --print to one
# and --profile to the other.
# --------------------------------------------------------------------------
CASES += [
    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY_Q,
     _sub('    if name.startswith("codex"):', "    if False:", 1),
     "codex is handed claude's flag set, so the prompt is parsed as a profile "
     "name and every codex agent exits before reading the question"),

    ("a-broken-agent-is-never-a-bad-answer", AGENTS_PY_Q,
     _sub('"-s", CODEX_SANDBOX_WRITE if tools else CODEX_SANDBOX_READONLY]',
          '"-s", CODEX_SANDBOX_WRITE]', 1),
     "a thinking agent is sandboxed workspace-write, so an agent that may only "
     "read is refused by nothing if it decides to write"),
]


# --------------------------------------------------------------------------
# A citation into an archived segment. `read()` -- the scan -- was segment-aware
# from the start; `record()` -- the point lookup every citation uses -- read the
# live file alone, so 1.9M rotated records resolved to None on the real archive.
# --------------------------------------------------------------------------
STORE_PY_CITE = "core/store.py"

CASES += [
    ("a-compressed-archive-is-still-a-readable-log", STORE_PY_CITE,
     _sub("        for row in self._rows(store, q, [int(seq)]):\n"
          "            return Record(row[0], row[1], json.loads(row[2]),\n"
          "                          HLC(row[3], row[4], row[5]), row[6])\n"
          "        return None",
          "        row = self._conns[store].execute(q, [int(seq)]).fetchone()\n"
          "        if row is None:\n"
          "            return None\n"
          "        return Record(row[0], row[1], json.loads(row[2]),\n"
          "                      HLC(row[3], row[4], row[5]), row[6])", 1),
     "the point lookup reads the live file alone again, so every citation into "
     "an archived segment resolves to None and the claims resting on them are "
     "withheld without anything reporting why"),
]


# --------------------------------------------------------------------------
# The minter is a mode of the bundle. It ran as a bare python3 outside the app,
# and it is the one process whose absence stops autonomy.
# --------------------------------------------------------------------------
MAIN_SWIFT = "app/island-macos/main.swift"
BUILD_SH = "app/island-macos/build.sh"

CASES += [
    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub('if args.contains("--arm") {', "if false {", 1),
     "the bundle loses its --arm mode, so the process that keeps autonomy "
     "alive runs outside the app and nothing ties its lifetime to VESPER's"),

    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub("guard let repo = vesperRepoRoot() else {",
          "guard let repo = Optional(FileManager.default.currentDirectoryPath) "
          "else {", 1),
     "--arm resolves its repo from the working directory again: '/' under "
     "launchd, so it works by hand and fails as a login item"),

    ("wake-word-listens-locally-and-starts-once", BUILD_SH,
     _sub('cp "$REPO/tools/ops/vesper_arm.py" '
          '"$APP/Contents/Resources/runtime/tools/ops/"', "true", 1),
     "the build stops packing the minter, so a relocated bundle cannot arm "
     "itself and autonomy stops one token lifetime later"),
]


# --------------------------------------------------------------------------
# What launchd is told to start. The --arm mode existed while the LaunchAgent
# still named `python3 .../vesper_arm.py`, so the process keeping autonomy
# alive stayed outside the bundle -- the fix committed, reality unchanged.
# --------------------------------------------------------------------------
ARM_PY = "tools/ops/vesper_arm.py"

CASES += [
    ("wake-word-listens-locally-and-starts-once", ARM_PY,
     _sub("    for app in cands:\n"
          "        if app.exists() and os.access(app, os.X_OK):\n"
          "            return [str(app), \"--arm\", \"--run\"]\n", "", 1),
     "the installer stops preferring the bundle, so launchd is pointed back at "
     "a bare interpreter and the process that keeps autonomy alive runs "
     "outside the app that autonomy belongs to"),
]


# --------------------------------------------------------------------------
# No transcriber may force a language on an owner who speaks three. Forcing the
# wrong one INVENTS rather than degrades: forcing `en` on Darija returns "What
# can you do for today's work?", which reads as a request and is not what was
# said.
# --------------------------------------------------------------------------
SUPPLY_TOML_LANG = "contracts/policy/provider_supply.toml"

CASES += [
    ("speech-in-declares-language-and-measures-confidence", SUPPLY_TOML_LANG,
     _sub('model = "@cf/openai/whisper-large-v3-turbo"',
          'model = "@cf/openai/whisper-large-v3-turbo"\nlanguage = "ar"', 1),
     "the transcriber forces Arabic again, so English and French utterances "
     "come back as hallucinated Arabic instead of as what was said"),
]


# --------------------------------------------------------------------------
# A rung out of quota is not the last rung. ElevenLabs' free tier is 10,000
# characters a MONTH -- roughly 40 replies -- and until this landed, a key
# that had spent its month left every later reply unspoken for the rest of it,
# with a working second key sitting unused in the same file.
# --------------------------------------------------------------------------
CASES += [
    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("from core.rung_credentials import expand_rows\n", "", 1),
     "speech_rows no longer expands numbered credentials, so a second "
     "ElevenLabs key added to secrets.env is never tried"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub("        for i, row in enumerate(candidates):",
          "        for i, row in enumerate(candidates[:1]):", 1),
     "only the first candidate is ever tried, so a rung out of characters "
     "ends the turn unspoken instead of falling to the next key"),

    ("speech-is-egress-and-says-so", SPEECH_PY,
     _sub('"speech.exhausted"', '"speech.exhausted_unused"', 1),
     "the exhaustion event is renamed, so a key running low on every rung "
     "is invisible until the turn nothing can save"),

    ("speech-is-egress-and-says-so", TRANSCRIBE_PY,
     _sub("from core.rung_credentials import expand_rows\n", "", 1),
     "transcribe_rows no longer expands numbered credentials, so a second "
     "transcriber credential added to secrets.env is never tried"),

    ("speech-is-egress-and-says-so", TRANSCRIBE_PY,
     _sub('if wire == "groq_whisper":', "if False:", 1),
     "the Groq wire is never reached, so a transcriber row declaring it "
     "fails every call regardless of credential"),

    ("speech-is-egress-and-says-so", TRANSCRIBE_PY,
     _sub('"transcribe.exhausted"', '"transcribe.exhausted_unused"', 1),
     "the exhaustion event is renamed, so a transcriber out of quota on "
     "every rung fails silently instead of being reported"),
]


# --------------------------------------------------------------------------
# The owner's stop, and the process leak found while building it. Asked for
# twice before it landed: there was no hotkey, no menu (an .accessory app has
# no menu bar), and any kill was undone by KeepAlive within seconds.
# --------------------------------------------------------------------------
CASES += [
    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub('if args.contains("--stop") {', "if false {", 1),
     "the bundle loses --stop, so stopping VESPER is a launchctl incantation "
     "the owner has to remember"),

    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     # THE CONDITION, NOT THE CONSTANT. Renaming `QUIT_HOLD_S` where it is
     # DECLARED leaves it at its use site, so a source-level check still finds
     # the name and stays green under a mutation that does not compile.
     _sub("    let chord = f.contains(.function) && f.contains(.control)",
          "    let chord = false && f.contains(.control)", 1),
     "the chord stops requiring fn, so the stop is either unreachable or "
     "fires on modifiers the owner presses for other reasons"),

    ("wake-word-listens-locally-and-starts-once", MAIN_SWIFT,
     _sub("    execv(py, &cargs)", "    _ = cargs", 1),
     "--arm goes back to spawn-and-wait, so every restart orphans a python "
     "minter onto launchd and they accumulate, all still minting"),

    ("wake-word-listens-locally-and-starts-once", BUILD_SH,
     _sub('"$APP/Contents/MacOS/VESPER" --reinstall-login-item', "true", 1),
     "the build stops re-registering the agents after signing, so a rebuild "
     "leaves launchd holding the old signature and the globe-key starter "
     "silently stops spawning"),
]


# --------------------------------------------------------------------------
# A path is not a secret. Judging one as a single token scored a home path at
# 4.06 bits against a 3.6 floor -- every segment sat between 1.92 and 3.10 --
# so a command's path was rewritten to [REDACTED:high_entropy_token], the
# mangled command levelled L5 instead of L3, and the owner was told VESPER
# needed a permission it had no way to ask for.
# --------------------------------------------------------------------------
CASES += [
    ("redactor-precedes-every-provider", REDACT_PY,
     # RESTORE THE BLOB BEHAVIOUR, which is what the bug was. Deleting the
     # early return makes the rule MORE lenient (everything judged per
     # segment) and the path still survives -- a mutation that cannot fail.
     #
     # AND IT MUST DEFEAT BOTH NARROWINGS, not one. Since 2026-09-06 the
     # charset test asks the same segment the entropy test does, so making the
     # ENTROPY judge the blob no longer redacts a path -- the charset test
     # still narrows and the case passed under its own violation. Mutating
     # `_worst_segment` is what puts the whole token back in front of both.
     _sub("    return max(segments, key=shannon_bits)",
          "    return tok", 1),
     "path tokens are judged as one blob again, so an ordinary absolute path "
     "is redacted as a secret and every command naming a file is corrupted "
     "before it runs"),

    ("redactor-precedes-every-provider", REDACT_PY,
     _sub("    return max(segments, key=shannon_bits)",
          "    return min(segments, key=shannon_bits)", 1),
     "a path is scored by its WEAKEST segment, so a real secret sitting in "
     "one segment of a path is averaged away and sent to the provider"),
]


# --------------------------------------------------------------------------
# CI-119 -- the enable token was presented on every tick, and every one after
# the first was correctly refused and loudly recorded. 343,470 of those events
# in the live log, over 80% of everything VESPER has ever written, into a store
# whose DELETE is refused at the storage layer.
# --------------------------------------------------------------------------
CASES += [
    ("enable-token-presented-once-per-mint", RUNTIME_PY,
     _sub("        if interlock.held_token_id() == token_id:\n"
          "            return\n", "", 1),
     "the loop presents the minter's file every tick again: one token, 239 "
     "refusals in 240 ticks, each one an event in an append-only store"),

    ("enable-token-presented-once-per-mint", RUNTIME_PY,
     _sub("        if interlock.held_token_id() == token_id:",
          "        if interlock.held_token_id() is not None:", 1),
     "the skip is keyed on HOLDING A TOKEN rather than holding THIS one, so "
     "the first token is accepted and no later mint ever is -- the log goes "
     "quiet because the dead-man's switch has stopped being re-armed, which "
     "passes the refusal count perfectly"),

    ("enable-token-presented-once-per-mint", INTERLOCK,
     _sub("                raise TokenMintingRefused(\n"
          '                    f"token {token.token_id!r} has already been presented")',
          "                pass", 1),
     "a replayed token presented directly is accepted: the storm is gone "
     "because INV-STOP-4's defence is gone, which is the one way of quieting "
     "this log that must never pass"),

    ("enable-token-presented-once-per-mint", INTERLOCK,
     _sub('            if self._now_ms() >= self._token.expires_at_ms():\n'
          '                return "enable_token_expired"',
          '            if self._now_ms() >= self._token.expires_at_ms():\n'
          '                self._token = None\n'
          '                return "enable_token_expired"', 1),
     "an expired token is cleared, which looks like tidying up and is the one "
     "change that makes the caller's skip unsafe: a re-minted token with the "
     "same id would now be acceptable, and the caller would skip it"),
]


# --------------------------------------------------------------------------
# CI-120 -- the permission mode is the owner's switch; it may only lower
# authority, never raise it, and a corrupted or absent file must never promote.
# --------------------------------------------------------------------------
PERMISSION_MODE = "core/permission_mode.py"
AUTHORIZE_PY = "core/authorize.py"

CASES += [
    ("permission-mode-ceiling-only-lowers", PERMISSION_MODE,
     _sub("    except Exception:                                   # noqa: BLE001\n"
          "        return ASK",
          "    except Exception:                                   # noqa: BLE001\n"
          "        return AUTO", 1),
     "a missing or malformed mode file returns AUTO rather than ASK: the "
     "dangerous failure, because a deleted file now gives VESPER full "
     "authority with no owner in the loop"),

    ("permission-mode-ceiling-only-lowers", PERMISSION_MODE,
     _sub("    return (NO_CEILING if contained(capability_id, args, workspace)\n"
          "            else ASK_LEVEL)",
          "    return NO_CEILING", 1),
     "ceiling_for in WORKSPACE mode always returns NO_CEILING: the mode never "
     "restricts anything, so an outside-workspace action goes through as if "
     "the mode were AUTO"),

    ("permission-mode-ceiling-only-lowers", PERMISSION_MODE,
     _sub("        if not tok:\n"
          "            return False",
          "        if not tok:\n"
          "            return False\n"
          "        if \" \" in tok:\n"
          "            return False", 1),
     "contained() rejects any path argument containing a space: this workspace "
     "is under ~/Library/Application Support/ so every path in it contains a "
     "space, and workspace mode refuses its own folder"),

    ("permission-mode-ceiling-only-lowers", AUTHORIZE_PY,
     _sub("        effective = _min_level(grant.max_level, declared, context_ceiling,\n"
          "                               mode_ceiling, auth_ceiling)",
          "        effective = _min_level(grant.max_level, declared, context_ceiling,\n"
          "                               auth_ceiling)", 1),
     "mode_ceiling is dropped from the _min_level call in the PDP: the "
     "owner's workspace switch is computed by the actor but the PDP ignores "
     "it, and an outside-workspace action passes as if the mode were AUTO"),
]


# --------------------------------------------------------------------------
# CI-121 -- the agenda trigger could see the owner's day and had no way to
# mention it. It fired, dispatched, and fell through `if not intent: continue`,
# passing every gate in the suite because every gate asked whether it FIRED.
# --------------------------------------------------------------------------
# The whole branch `read_eventkit` takes when the bridge has never run.
_CI121_EK_MISSING = (
    '        why = ("the calendar bridge has not run; VESPER has no reading of "\n'
    '               "your calendar or reminders")\n'
    '        return [], {"calendar": why, "reminders": why}'
)

CASES += [
    ("a-due-item-is-spoken-not-merely-noticed", RUNTIME_PY,
     _sub("agenda.agenda_trigger(handler=_agenda_due_handler)",
          "agenda.agenda_trigger()", 1),
     "the runtime registers the trigger with no handler again: the owner's day "
     "is watched, the trigger fires when something comes due, and nothing is "
     "ever said -- which is the state this check was written for"),

    ("a-due-item-is-spoken-not-merely-noticed", AUTON_PY,
     _sub("            if not intent:\n                continue\n", "", 1),
     "dispatch stops skipping a trigger that carries neither handler nor "
     "intent, so a handler-less trigger looks handled and the defect becomes "
     "invisible to the assertion that names it"),

    ("a-due-item-is-spoken-not-merely-noticed", AGENDA_PY,
     _sub(_CI121_EK_MISSING, "        return [], {}", 1),
     "a calendar the bridge never wrote reports as READ AND EMPTY, so an "
     "unseen day is indistinguishable from a clear one -- INV-HW-2 in the one "
     "place it costs the owner an appointment"),

    ("a-due-item-is-spoken-not-merely-noticed", AGENDA_PY,
     _sub("        return not self.unavailable and not self.due_now(now_ms)",
          "        return not self.due_now(now_ms)", 1),
     "`quiet()` stops caring whether a source could be read, so VESPER falls "
     "silent on a day it never managed to look at and the silence is "
     "indistinguishable from a free afternoon"),

    ("a-due-item-is-spoken-not-merely-noticed", RUNTIME_PY,
     # ANCHORED ON THE LOOP HEADER ALONE, not on the whole call. The call
     # grew `period=` and `attention_state=` arguments the same day this case
     # was written, and the literal stopped matching -- a self-test that does
     # not apply reports that the artifact changed shape, which is true and is
     # not what it was written to detect.
     _sub("                for _rec in (autonomy.dispatch(",
          "                autonomy.dispatch(", 1),
     "the pump throws away what autonomy did, so an announcement is spoken "
     "aloud and never appears on the surface -- audible and invisible, which "
     "reads as VESPER talking to itself"),
]


# --------------------------------------------------------------------------
# CI-122 -- the loop knew what went wrong and told neither the owner nor the
# next step. A rename failed, VESPER said "it ran and came back with error
# code 1", and the following proposal was formed with no record that anything
# had happened at all.
# --------------------------------------------------------------------------
CASES += [
    ("a-failure-is-something-the-next-step-can-see", ACTOR_PY,
     _sub('        why = str(getattr(proposal, "why", "") or "").strip().rstrip(".")\n'
          '        if why:\n'
          '            return f"Done — {why}."\n'
          '        return "Done."',
          '        return "it ran and printed nothing"', 1),
     "a silent success is reported as the absence of output again: the owner "
     "asks to rename a file, VESPER renames it, and answers by describing the "
     "mechanism instead of the outcome"),

    ("a-failure-is-something-the-next-step-can-see", ACTOR_PY,
     _sub("            why = err or out\n", "            why = out\n", 1),
     "a failing command's stderr is dropped, so `mv: Operation not permitted` "
     "reaches the owner as a bare exit code -- a number where the diagnosis "
     "was already in hand"),

    ("a-failure-is-something-the-next-step-can-see", ACTOR_PY,
     _sub("                observations.append(\n"
          "                    observe(p.capability_id, p.args,\n"
          "                            {**((out.detail or {}).get(\"result\") or {}),\n"
          "                             \"failed\": True,\n"
          "                             \"error\": (out.detail or {}).get(\"error\") or out.said}))\n",
          "", 1),
     "the failure branch records no observation again, so the next proposal is "
     "formed in ignorance of the error and VESPER reports a failure and stops "
     "-- the state the owner called 'no solution'"),

    ("a-failure-is-something-the-next-step-can-see", ACTOR_PY,
     _sub("                consecutive_refusals += 1\n",
          "                consecutive_refusals += 1\n"
          "                consecutive_refusals = 0\n", 1),
     "seeing the error also resets the refusal counter, so a proposer that "
     "fails every time never trips the breaker and grinds to the step budget "
     "on every turn -- which passes the observation assertion perfectly"),
]


# --------------------------------------------------------------------------
# CI-123 -- the owner could not see what VESPER ran. `shell.run` held the
# argv, the exit code, the stdout and the stderr, and the surface rendered one
# eighty-character status line; a failed rename reached the owner as "error
# code 1" while `mv` had already written down why.
# --------------------------------------------------------------------------
CASES += [
    ("commands-card-shows-what-ran", RUNTIME_PY,
     _sub("def _record_command(bench, capability_id, args, result) -> None:",
          "def _record_command_disabled(bench, capability_id, args, result) -> None:", 1),
     "nothing translates a finished step into a row, so the card renders an "
     "empty list forever while every command runs correctly -- the sixth "
     "instance of built-and-nothing-reaches-it in this tree"),

    ("commands-card-shows-what-ran", CAPS_PY,
     _sub('    return {"exit_code": p.returncode,\n            "argv": list(argv),\n',
          '    return {"exit_code": p.returncode,\n', 1),
     "the executor stops reporting the argv it handed the kernel, so the card "
     "can only show a command line rebuilt from the string it was split from "
     "-- a reconstruction that is right until the day it is not"),

    ("commands-card-shows-what-ran", CAPS_PY,
     _sub('            "stderr": p.stderr[:2000],\n            "contained": True,',
          '            "stderr": "",\n            "contained": True,', 1),
     "a failing command reaches the card with an empty stderr, so the surface "
     "can only offer an exit code -- the owner called that 'no solution'"),

    ("commands-card-shows-what-ran", RUNTIME_PY,
     _sub('    if capability_id != "shell.run" or bench is None:',
          '    if bench is None:', 1),
     "every capability lands on the commands card, so writing a file and "
     "opening a window appear as commands and the card becomes a second, "
     "worse copy of the actions column"),

    ("commands-card-shows-what-ran", WORKBENCH,
     _sub("    return out, cut", "    return out, False", 1),
     "output past the cap is trimmed and the cut is not declared, so the card "
     "shows a fragment as though it were the whole output -- a false statement "
     "the owner would act on"),

    ("commands-card-shows-what-ran", WORKBENCH,
     _sub("        lines = lines[:COMMAND_OUT_MAX_LINES]",
          "        lines = lines[-COMMAND_OUT_MAX_LINES:]", 1),
     "truncation keeps the END of the output: a traceback names its cause at "
     "the top, so this keeps the summary and discards the diagnosis"),

    ("commands-card-shows-what-ran", WORKBENCH,
     _sub("            self._commands.append(cmd)\n"
          "            del self._commands[:-COMMANDS_MAX]\n",
          "            self._commands.append(cmd)\n", 1),
     "the commands list is unbounded and grows for as long as VESPER runs, "
     "carrying up to sixteen kilobytes of output per row into home.json on "
     "every single tick"),

    ("commands-card-shows-what-ran", WORKBENCH,
     _sub('"commands": [c.to_dict() for c in self._commands]',
          '"commands": []', 1),
     "the record never reaches home.json, so the card is a renderer with "
     "nothing behind it and the whole path is correct up to the last joint"),

    ("commands-card-shows-what-ran", CHROME_TPL,
     # ANCHORED ON THE CALL ALONE. The first version quoted the three lines
     # that follow it, and adding `renderExplanations` beside it broke the
     # match -- the case reported N/A and tested nothing. A case anchored on
     # its subject's NEIGHBOURS decays every time the subject is improved.
     _sub("      renderCommands((w && w.commands) || []);\n",
          "", 1),
     "the render call is gone from `__vesperWork`, so every command is "
     "recorded, published and pushed into a page that draws none"),

    ("commands-card-shows-what-ran", CHROME_TPL,
     _sub("      cmdrows.textContent = '';", "      cmdrows.innerHTML = '';", 1),
     "the commands renderer goes back to markup, on rows carrying a command "
     "line and a process's own stderr straight off the wire"),

    ("commands-card-shows-what-ran", CHROME_TPL,
     _sub('<div class="pbody" id="cmdrows"></div>',
          '<div class="pbody" id="cmdrowsX"></div>', 1),
     "the pane's row container loses the id the renderer writes into, so every "
     "command is recorded, published and pushed into a page that draws none"),
]


# --------------------------------------------------------------------------
# CI-124 -- the reply is produced once and read by two consumers ninety lines
# apart. A split applied to one leaves the other reading four hundred words,
# or a sudo command, into whatever room VESPER is in.
# --------------------------------------------------------------------------
LONGFORM = "core/longform.py"

CASES += [
    ("an-explanation-is-shown-and-never-spoken", LONGFORM,
     _sub("    if not (has_code or long_enough):", "    if not long_enough:", 1),
     "a reply whose only longform signal is a fenced code block is spoken "
     "whole, so `sudo chown -R me /srv/data` is read into the room"),

    ("an-explanation-is-shown-and-never-spoken", LONGFORM,
     _sub("    spoken = _first_sentence(lead) or NO_PROSE",
          "    spoken = lead or NO_PROSE", 1),
     "the whole leading paragraph is spoken instead of its first sentence, so "
     "the cap that makes speech bearable stops applying"),

    ("an-explanation-is-shown-and-never-spoken", LONGFORM,
     _sub("    if not (has_code or long_enough):\n        return Split(spoken=reply)",
          "    if False:\n        return Split(spoken=reply)", 1),
     "every reply becomes an explanation, so the board fills with one-word "
     "answers and buries the explanations it exists to hold"),

    ("an-explanation-is-shown-and-never-spoken", LONGFORM,
     _sub('NO_PROSE = "That one is written out on the board."',
          'NO_PROSE = ""', 1),
     "a reply that is only code leaves the stage empty, so the owner asks a "
     "question and is answered by silence"),

    ("an-explanation-is-shown-and-never-spoken", WORKBENCH,
     _sub('        rows = [b for b in rows if b.get("kind") in ("text", "code", "list")]\n',
          "", 1),
     "untyped blocks reach the record, so whatever a model emitted is handed "
     "to a page that has a fixed template for three kinds and nothing for the "
     "rest"),

    ("an-explanation-is-shown-and-never-spoken", WORKBENCH,
     _sub('            self._explanations = [e for e in self._explanations\n'
          '                                  if e["id"] != entry["id"]]\n',
          "", 1),
     "re-running one turn stacks a second copy of its explanation, so the "
     "owner is shown the same answer twice under one question"),

    ("an-explanation-is-shown-and-never-spoken", WORKBENCH,
     _sub("            del self._explanations[:-EXPLANATIONS_MAX]\n", "", 1),
     "the explanations list is unbounded, and every one of them travels "
     "through home.json on every tick for as long as VESPER runs"),

    ("an-explanation-is-shown-and-never-spoken", WORKBENCH,
     _sub('                 "turn_id": turn_id,\n', '                 "turn_id": "",\n', 1),
     "the explanation stops carrying its turn, so the line on the stage and "
     "the text on the board can no longer find each other and `connected` "
     "becomes a claim"),

    ("an-explanation-is-shown-and-never-spoken", RUNTIME_PY,
     _sub("                reply = _split.spoken\n", "", 1),
     "the split is computed and the spoken half is never assigned, so the "
     "stage and the synthesiser both go back to reading the whole answer "
     "while the board looks correct"),

    ("an-explanation-is-shown-and-never-spoken", RUNTIME_PY,
     _sub("                        plan = speech.plan(reply, privacy_class=\"private\",",
          "                        plan = speech.plan(reply_full, privacy_class=\"private\",", 1),
     "the synthesiser is handed the FULL reply explicitly -- the one "
     "destination the long half must never reach"),

    ("an-explanation-is-shown-and-never-spoken", RUNTIME_PY,
     _sub("                        question=text, answer=reply_full, outcome=outcome,",
          "                        question=text, answer=reply, outcome=outcome,", 1),
     "the baseline corpus records the shortened line instead of the answer, so "
     "every comparative question about memory becomes unanswerable -- quietly, "
     "and only discoverable in hindsight"),

    ("an-explanation-is-shown-and-never-spoken", CHROME_TPL,
     _sub("      renderExplanations((w && w.explanations) || []);\n", "", 1),
     "the page loses its explanations renderer: every explanation is still "
     "split, recorded, published and pushed, and drawn by nothing"),

    ("an-explanation-is-shown-and-never-spoken", CHROME_TPL,
     _sub("      exprows.textContent = '';", "      exprows.innerHTML = '';", 1),
     "the explanations renderer goes back to markup, on blocks that are a "
     "model's own output"),
]


# --------------------------------------------------------------------------
# CI-125 -- the owner watched a card disappear. The board lived in memory and
# home.json was overwritten with an empty one on the first pump after every
# restart, so a rebuild blanked it while everything underneath worked.
# --------------------------------------------------------------------------
CASES += [
    ("the-board-survives-a-restart", WORKBENCH,
     _sub("    def seed(self, state: Any) -> int:",
          "    def seed_disabled(self, state: Any) -> int:", 1),
     "the board has no way back at all, so every rebuild and every login "
     "empties the commands and explanations panes and they hide themselves"),

    ("the-board-survives-a-restart", WORKBENCH,
     _sub("                self._seq = max(self._seq, len(self._commands))\n", "", 1),
     "the id counter restarts at zero after a restore, so the next command "
     "mints an id a restored row already has -- and the page, which keys its "
     "expanded rows on that id, opens two rows for one click"),

    ("the-board-survives-a-restart", WORKBENCH,
     _sub("            if not self._commands:\n", "            if True:\n", 1),
     "seeding a board that already holds rows appends a second copy of all of "
     "them, so one stray second call duplicates the whole history"),

    ("the-board-survives-a-restart", WORKBENCH,
     _sub('                    self._explanations.append(e)\n', "", 1),
     "explanations are not restored, so every answer VESPER wrote out is lost "
     "the next time the process starts"),

    ("the-board-survives-a-restart", RUNTIME_PY,
     _sub("        _n = bench.seed(_prior.get(\"workbench\") or {})\n", "", 1),
     "`Workbench.seed` exists and the runtime never calls it: built, correct, "
     "and reached by nothing -- the shape this tree has now found six times"),
]


# --------------------------------------------------------------------------
# CI-126 -- the redactor rewrote the owner's own file paths, twice, and both
# times every stage after it behaved correctly on corrupted input.
# --------------------------------------------------------------------------
REDACT_PY = "core/redact.py"

CASES += [
    ("a-path-is-not-a-secret", REDACT_PY,
     _sub("        if _is_benign(tok) or not _charset_mixed(_worst_segment(tok)):",
          "        if _is_benign(tok) or not _charset_mixed(tok):", 1),
     "the charset test goes back to reading the whole token while the entropy "
     "test reads one segment: a path mixes classes by being JOINED, so it "
     "passes a test meaning `this looks generated` -- the 2026-09-06 incident "
     "exactly"),

    ("a-path-is-not-a-secret", REDACT_PY,
     _sub("    return shannon_bits(_worst_segment(tok))",
          "    return shannon_bits(tok)", 1),
     "the entropy test goes back to scoring the whole path, which is the "
     "2026-09-04 incident: `python3 <path>/hey.py` became an unparseable "
     "token, scored L5, and was refused for authorization VESPER could not ask "
     "for"),

    ("a-path-is-not-a-secret", REDACT_PY,
     _sub("    return max(segments, key=shannon_bits)",
          "    return segments[-1]", 1),
     "the deciding segment becomes the filename rather than the worst one, so "
     "a credential dropped into a DIRECTORY name is judged by an innocent file "
     "beside it and walks through"),

    ("a-path-is-not-a-secret", REDACT_PY,
     _sub('    if not tok.startswith(("/", "./", "../", "~/")):\n        return None\n',
          "    return None\n", 1),
     "nothing is treated as a path any more, so every path is scored whole "
     "again and the narrowing is gone in both tests at once"),

    ("a-path-is-not-a-secret", REDACT_PY,
     _sub("    segments = [s for s in tok.split(\"/\") if s]\n    return segments or None",
          "    segments = [tok]\n    return segments or None", 1),
     "a path is treated as one segment, which is the same as not splitting it "
     "-- the guard is present, reads correct, and does nothing"),
]


# --------------------------------------------------------------------------
# CI-127 -- auto mode asked for permission, in the one mode whose meaning is
# that it does not; and the fix for that is an escalation, so most of these
# cases are about the ceilings it must not cross.
# --------------------------------------------------------------------------
CASES += [
    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub("        if mode != permission_mode.AUTO:\n            return d\n", "", 1),
     "every mode gains auto's authority, so `ask` -- the mode a cautious owner "
     "picks -- silently stops asking"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub("        top = _min_level(mode_ceiling, context_ceiling)",
          '        top = "L5"', 1),
     "the elevated grant ignores the context ceiling: a page VESPER read "
     "becomes a reason to act above the level that ceiling had already "
     "refused, which is INV-ACT-3 broken from inside the system where it looks "
     "like a setting"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub("                issued_for_command_id=command_id))",
          "                ))", 1),
     "the grant is no longer bound to one command instance, so it authorises "
     "the next action too -- which is the whole of what INV-AUTH-2 forbids"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub('    ELEVATABLE = ("below_required_level", "no_grant", "grant_consumed")',
          '    ELEVATABLE = ("below_required_level", "no_grant", "grant_consumed",\n'
          '                  "outside_workspace")', 1),
     "auto mode starts answering a refusal that is not about level at all: "
     "`outside_workspace` is a different objection and standing consent to act "
     "is not consent to act anywhere"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub("        return self._pdp.authorize(\n"
          "            subject=self._subject, capability_id=p.capability_id, args=p.args,",
          "        return Decision(True, top, \"authorized\", p.capability_id,\n"
          "                        self._subject) or self._pdp.authorize(\n"
          "            subject=self._subject, capability_id=p.capability_id, args=p.args,", 1),
     "elevation decides for itself instead of re-asking the ladder, so the "
     "target scope, the capability's own rules and every ceiling stop being "
     "consulted -- a second path to a level"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub('            payload={"capability_id": p.capability_id, "level": top,',
          '            payload={"capability_id": None, "level": top,', 1),
     "the elevation record stops naming the capability, so a mode that means "
     "`do not ask` also means `do not say` and nothing afterwards can tell "
     "which action ran above the standing level"),

    ("auto-mode-does-not-ask-and-does-not-overreach", ACTOR_PY,
     _sub("            d = self._elevate_in_auto(d, p, mode=mode, mode_ceiling=mode_ceiling,\n",
          "            d = d or self._elevate_in_auto(d, p, mode=mode, mode_ceiling=mode_ceiling,\n", 1),
     "the elevation is short-circuited away, so the code that stops auto mode "
     "asking is present, correct and never reached"),
]


# --------------------------------------------------------------------------
# CI-128 -- the changed-files board. Its worst failure is not being absent; it
# is being confidently wrong, which is what eighteen rows of "+0 -0" were.
# --------------------------------------------------------------------------
CHANGES_PY = "core/changes.py"

CASES += [
    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub("        root = repo_of(root or self._git_root or pathlib.Path.cwd()) or \"\"",
          "        root = root or self._git_root or str(pathlib.Path.cwd())", 1),
     "the repository root is trusted as handed rather than resolved: the "
     "runtime runs from inside the app bundle, so every path is made relative "
     "to the wrong root and every diff comes back empty while the card fills "
     "with rows and looks right"),

    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub("    added = sum(1 for r in rows if r.startswith(\"+\") and not r.startswith(\"+++\"))",
          "    added = 0", 1),
     "the counts stop describing the diff, so a card reads +0 over a screenful "
     "of additions"),

    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub("    if len(rows) > DIFF_MAX_LINES:\n        rows = rows[:DIFF_MAX_LINES]\n        cut = True\n",
          "    if False:\n        rows = rows[:DIFF_MAX_LINES]\n        cut = True\n", 1),
     "a diff of any size is carried whole into home.json and pushed through a "
     "webview four times a second, on a laptop the owner has twice asked not "
     "to heat up"),

    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub("            body = _redact(d.stdout)", "            body = d.stdout", 1),
     "file contents reach the screen unredacted -- and a file the owner is "
     "editing may hold the key VESPER is forbidden to send anywhere"),

    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub('        for topic, fn, name in (("tool.checkpointed", on_checkpoint, "changes-checkpoint"),\n'
          '                                ("tool.completed", on_completed, "changes-completed")):',
          '        for topic, fn, name in (("tool.nothing", on_checkpoint, "changes-checkpoint"),\n'
          '                                ("tool.nothing2", on_completed, "changes-completed")):', 1),
     "the board stops subscribing to the executor, so VESPER writes files and "
     "the changes pane never hears about any of them"),

    ("changes-are-shown-with-their-source", CHANGES_PY,
     _sub("CHANGES_MAX = 60", "CHANGES_MAX = 5000", 1),
     "the row list is unbounded in practice: a working tree mid-rebase carries "
     "thousands of rows through home.json on every refresh"),

    ("changes-are-shown-with-their-source", CHROME_TPL,
     _sub("      chgrows.textContent = '';", "      chgrows.innerHTML = '';", 1),
     "the changes renderer goes back to markup, on rows carrying file contents "
     "straight off the disk"),

    ("changes-are-shown-with-their-source", CHROME_TPL,
     _sub("  .dhunks .a{color:rgba(150,208,158,.92);background:rgba(120,190,130,.10);\n"
          "             display:block}", "", 1),
     "additions lose their rule, so the diff is one colour and the only thing "
     "separating an addition from a deletion is a character nobody styled"),
]


# --------------------------------------------------------------------------
# CI-129 -- the owner's shell. Every case here is a path from something VESPER
# rendered to something the machine executes, outside the seatbelt.
# --------------------------------------------------------------------------
TERM_SWIFT = "app/home-macos/TerminalBridge.swift"

CASES += [
    ("the-terminal-is-the-owners", TERM_SWIFT,
     _sub('        case "resize":\n            resize(cols: (body["cols"] as? Int) ?? 80,\n'
          '                   rows: (body["rows"] as? Int) ?? 24)',
          '        case "resize":\n            write((body["text"] as? String) ?? "")\n'
          '            resize(cols: (body["cols"] as? Int) ?? 80,\n'
          '                   rows: (body["rows"] as? Int) ?? 24)', 1),
     "a second message can write to the shell: a resize -- which the page "
     "sends on its own, unattended, whenever the pane changes size -- becomes "
     "a way to execute text"),

    ("the-terminal-is-the-owners", TERM_SWIFT,
     _sub('        case "input":', '        case "input", "paste":', 1),
     "paste gains a Swift path, so `run` and `paste` become one code path "
     "apart and the difference between showing the owner a command and running "
     "it is a string comparison"),

    ("the-terminal-is-the-owners", TERM_SWIFT,
     _sub('        let sh = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"',
          '        let sh = "/bin/zsh"', 1),
     "the pane stops using the owner's own shell, so their aliases, functions "
     "and PATH are absent from a window that looks exactly like their terminal"),

    ("the-terminal-is-the-owners", TERM_SWIFT,
     _sub("    func reapIfIdle() {", "    func reapIfIdleX() {", 1),
     "the login shell is never reaped, so opening the pane once holds one open "
     "for as long as the home is on the Desktop"),

    ("the-terminal-is-the-owners", CHROME_TPL,
     _sub("        setTimeout(function () {\n"
          "          if (tin) { tin.value = pasteb.getAttribute('data-paste'); tin.focus(); }\n"
          "        }, 220);",
          "        setTimeout(function () {\n"
          "          termInput(pasteb.getAttribute('data-paste') + '\\n');\n"
          "        }, 220);", 1),
     "the paste button runs the command instead of showing it -- the single "
     "most dangerous line this pane could contain, and it looks like a "
     "convenience"),

    ("the-terminal-is-the-owners", CHROME_TPL,
     _sub("    window.__vesperChanges = function (json) {\n"
          "      var payload;",
          "    window.__vesperChanges = function (json) {\n"
          "      termInput('');\n"
          "      var payload;", 1),
     "a renderer that runs on a timer, over data that came out of home.json, "
     "can reach the shell: a command VESPER only drew would be one it ran, "
     "with nobody at the machine"),
]


# The non-consuming pre-check is now keyed on WHERE it appears rather than on
# how many there are, so the case that guards it has to move a call rather than
# add one.
CASES += [
    ("a-question-does-not-end-the-turn", ACTOR_PY,
     _sub("    def _verify(self, proposal: Any, level: str, ex: Any) -> Outcome:",
          "    def _verify(self, proposal: Any, level: str, ex: Any) -> Outcome:\n"
          "        self._pdp.authorize(subject=self._subject,\n"
          "                            capability_id=proposal.capability_id,\n"
          "                            args=proposal.args, target=self._target,\n"
          "                            consume=False)", 1),
     "a non-consuming authorize appears in a function that ACTS rather than in "
     "one that decides whether to ask -- a way to learn a verdict without "
     "paying for it and then act on it"),
]


# The board's live half is restored too, since 2026-09-06 -- the owner reported
# the thoughts-and-actions card VANISHING on a restart, because `.work.idle`
# hides a card with nothing in it.
CASES += [
    ("the-board-survives-a-restart", WORKBENCH,
     _sub("                    if a.get(\"state\") not in (\"done\", \"failed\"):\n"
          "                        continue\n", "", 1),
     "a `live` action row is restored, so the board comes up with a pulsing "
     "spinner for work that stopped existing when the process did -- the same "
     "defect as a face stuck on `thinking`"),

    ("the-board-survives-a-restart", WORKBENCH,
     _sub("                for t in list(reversed(state.get(\"thoughts\") or []))[-MAX_THOUGHTS_KEPT:]:",
          "                for t in (state.get(\"thoughts\") or [])[-MAX_THOUGHTS_KEPT:]:", 1),
     "restored thoughts keep the PUBLISHED order instead of the stored one, so "
     "the card comes up backwards and the renderer spends its line budget on "
     "the oldest thought"),
]


# --------------------------------------------------------------------------
# CI-131 -- Notes as an agenda source. A note's BODY may hold anything the
# owner ever pasted into it, and this is the path VESPER uses to decide what to
# do next: a note reading "delete the old backups" is a note, not an order.
# --------------------------------------------------------------------------
AGENDA_PY = "core/agenda.py"
NOTES_SWIFT = "app/island-macos/NotesBridge.swift"

CASES += [
    ("notes-are-titles-and-never-instructions", AGENDA_PY,
     _sub('SOURCES = ("plan", "calendar", "reminders", "notes")',
          'SOURCES = ("plan", "calendar", "reminders")', 1),
     "notes drop out of SOURCES, so a denied or stale notes grant stops making "
     "the agenda unavailable and VESPER answers `nothing due` from a source it "
     "cannot actually see"),

    ("notes-are-titles-and-never-instructions", AGENDA_PY,
     _sub('        it = _item_from({**raw, "due_ms": None}, "notes")',
          '        it = _item_from(raw, "notes")', 1),
     "a due time from a note is trusted instead of stripped: the reader stops "
     "enforcing the rule and it holds only while the writer keeps following "
     "it, which is a promise rather than a guard"),

    ("notes-are-titles-and-never-instructions", AGENDA_PY,
     _sub("    if age > EVENTKIT_FRESH_S:\n"
          '        return [], {"notes": (f"the notes reading is {int(age // 60)} minutes "',
          "    if False:\n"
          '        return [], {"notes": (f"the notes reading is {int(age // 60)} minutes "', 1),
     "a stale notes dump is served as a fresh one, so a bridge that stopped "
     "running hours ago reports an empty agenda instead of an unknown one -- "
     "INV-HW-2 inverted, a reading nobody took returned as a reading of zero"),

    ("notes-are-titles-and-never-instructions", AGENDA_PY,
     _sub('    if not block.get("authorized", False):', "    if False:", 1),
     "a DENIED notes grant is reported as an empty notes list, so the owner is "
     "told there is nothing in their notes by a VESPER that was never allowed "
     "to look"),

    ("notes-are-titles-and-never-instructions", NOTES_SWIFT,
     _sub("(name of n)", "(body of n)", 1),
     "the bridge asks Notes for the BODY. Every word the owner ever pasted into "
     "a note -- an email, a web page, someone else's text -- becomes input to "
     "the thing that decides what VESPER does next"),
]


# --------------------------------------------------------------------------
# CI-132 -- step one of the owner's provider policy. Five cases need five
# responses; nothing could tell them apart because nothing read the text.
# --------------------------------------------------------------------------
SUPPLY_PY = "routing/supply.py"
GATEWAY_PY = "core/gateway.py"

CASES += [
    ("a-provider-failure-says-which-kind-it-is", SUPPLY_PY,
     _sub('    text = " ".join(x.strip() for x in (stdout or "", stderr or "") if x.strip())',
          '    text = (stderr or "").strip()', 1),
     "the classifier reads stderr only again -- and `claude` answers on STDOUT "
     "with an empty stderr, so every refusal becomes a bare exit code and the "
     "reason is not misclassified but DISCARDED"),

    ("a-provider-failure-says-which-kind-it-is", SUPPLY_PY,
     _sub('    (("session limit", "usage limit", "rate limit", "too many requests",\n'
          '      "try again later", "slow down"), "rate_limited"),\n', "", 1),
     "a session limit falls through to `server_error`: TRANSIENT, retried ten "
     "times against a subscription that resets in hours, and filed as VESPER's "
     "own defect"),

    ("a-provider-failure-says-which-kind-it-is", SUPPLY_PY,
     _sub("            after = (CLI_LIMIT_BACKOFF_MS\n"
          '                     if classification == "rate_limited" else None)',
          "            after = None", 1),
     "a limit that resets in hours is retried on the default backoff of about a "
     "second -- nine more identical failures, and the owner sees the rung "
     "thrash instead of failing over"),

    ("a-provider-failure-says-which-kind-it-is", GATEWAY_PY,
     _sub('            "budget_too_large", "model_gone")',
          '            "budget_too_large")', 1),
     "`model_gone` falls into neither TERMINAL nor TRANSIENT, so a model the "
     "provider has REMOVED is retried on a computed backoff -- a request that "
     "cannot succeed, repeated on a timer"),

    ("a-provider-failure-says-which-kind-it-is", SUPPLY_PY,
     _sub('    (("not logged in", "please run /login", "unauthorized", "invalid api key",\n'
          '      "authentication", "expired", "no credentials", "oauth"), "auth_failed"),\n',
          "", 1),
     "'Not logged in' is no longer recognised, so a credential the OWNER has to "
     "fix is retried by VESPER and then filed against VESPER's own wire format"),
]


# --------------------------------------------------------------------------
# CI-133 -- the other half of the owner's provider policy: WHERE each part of
# a failure goes. A repair used to produce a bus event and nothing else.
# --------------------------------------------------------------------------
REPAIR_PY = "core/repair.py"

CASES += [
    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub("                if changed:\n"
          "                    _surface_repair(bench, transcript, home, item, out)\n",
          "", 1),
     "a provider failure goes back to producing a bus event and nothing the "
     "owner can see -- the state they described as being told only `that "
     "provider returned an error`"),

    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub("                if changed:\n"
          "                    _surface_repair(bench, transcript, home, item, out)",
          "                if True:\n"
          "                    _surface_repair(bench, transcript, home, item, out)", 1),
     "the finding is re-announced on the keepalive, so a rung that stays broken "
     "repeats itself every half hour at VESPER's clock rather than when "
     "anything about it actually changed"),

    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub('    bench.explain(item.item_id, f"{rung}: {kind.replace(\'_\', \' \')}", blocks)',
          '    bench.explain("", f"{rung}: {kind}", blocks)', 1),
     "the explanation stops being keyed on the item, so a rung failing the same "
     "way twice stacks a second copy of one finding instead of updating it"),

    ("a-provider-failure-reaches-the-owner", REPAIR_PY,
     _sub('            "rate_limited": self._rate_limited,\n'
          '            "quota_exhausted": self._rate_limited,\n', "", 1),
     "a usage limit falls to the escalation path again, which files a GAP IN "
     "VESPER'S REPAIR RULES against a provider that refused exactly as "
     "designed -- a triage item, a repair attempt and a proposed patch for "
     "running out of allowance"),

    ("a-provider-failure-reaches-the-owner", REPAIR_PY,
     _sub('            "model_gone": self._model_gone,\n', "", 1),
     "a model the provider retired is escalated as an unknown fault instead of "
     "retiring its row and naming the contract that would restore it"),

    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub('        "auth_failed": f"{rung} will not accept its credential, and that is "\n'
          '                       f"yours to fix rather than mine. The board has the steps.",\n',
          "", 1),
     "an auth failure loses its own sentence and falls back to the generic one, "
     "so a credential only the OWNER can fix reads exactly like every other "
     "provider fault"),
]


# The owner's correction, 2026-09-07: a malformed request is VESPER's own and
# is fixed and re-sent silently, not proposed as a patch and not spoken.
CASES += [
    ("a-provider-failure-reaches-the-owner", GATEWAY_PY,
     _sub("                    if cls == \"bad_request\" and not repaired:", "                    if False:", 1),
     "the gateway stops correcting its own malformed request: `bad_request` is "
     "TERMINAL, so the rung is abandoned on a call VESPER built wrong and the "
     "repairer files a PATCH for something one corrected field away from "
     "working"),

    ("a-provider-failure-reaches-the-owner", GATEWAY_PY,
     _sub("                            repaired = True\n", "", 1),
     "the one-shot bound is gone, so a provider that rejects the corrected "
     "request is corrected and re-sent again -- an added attempt becomes a "
     "loop against a rung that will never accept it"),

    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub('SILENT_ON_THE_TALK = ("bad_request",)', "SILENT_ON_THE_TALK = ()", 1),
     "VESPER announces its own bookkeeping: a request it malformed and then "
     "corrected is read aloud as though the owner had something to decide"),

    ("a-provider-failure-reaches-the-owner", RUNTIME_PY,
     _sub("    if kind in SILENT_ON_THE_TALK:\n        return\n", "", 1),
     "the silence list is consulted by nothing -- present, correct, and "
     "reached by no code path"),
]


CASES += [
    ("triage-excludes-quota", "core/triage.py",
     _sub('    "quota_ledger_exhausted",\n', "", 1),
     "the ledger's own refusal is investigated again: a quota already absorbed "
     "is filed as a defect on every subsequent call, graded, repaired, and "
     "answered `no tier-1 handler for this classification`"),
]


# --------------------------------------------------------------------------
# CI-134 -- the island. Two clocks share one file, and the permission mode had
# no surface anywhere while being the difference between asking and acting.
# --------------------------------------------------------------------------
ISLAND_SNAP = "tools/island_snapshot.py"
ISLAND_SWIFT = "app/island-macos/main.swift"

CASES += [
    ("the-island-shows-vespers-own-state", RUNTIME_PY,
     _sub('        rows.append({"label": "Mode", "value": permission_mode.read()})\n', "", 1),
     "the permission mode loses its only surface: the owner switches it and "
     "then has to remember, while in `auto` it is the difference between "
     "VESPER asking and VESPER acting"),

    ("the-island-shows-vespers-own-state", RUNTIME_PY,
     _sub('        rows.append({"label": "Ran",\n'
          '                     "value": f"{len(cmds)}" + ("  !" if last.get("state") == "failed" else "")})',
          '        rows.append({"label": "Ran", "value": f"{len(cmds)}"})', 1),
     "a failed command stops being marked, so the count reads the same whether "
     "the last one worked or not -- a count rather than a status"),

    ("the-island-shows-vespers-own-state", ISLAND_SNAP,
     _sub("    existing.update({\"version\": proj.version.to_dict(), \"columns\": cols,\n"
          "                     \"gauges\": gs, \"panel\": panel})\n"
          "    out.write_text(json.dumps(existing, indent=1))",
          "    out.write_text(json.dumps({\"version\": proj.version.to_dict(), \"columns\": cols,\n"
          "                               \"gauges\": gs, \"panel\": panel}, indent=1))", 1),
     "the hourly snapshot overwrites the whole file again, so every key another "
     "writer owns is deleted once an hour -- and nothing notices for an hour"),

    ("the-island-shows-vespers-own-state", RUNTIME_PY,
     _sub("    sig = json.dumps(rows, sort_keys=True)\n"
          "    if sig == _island_sig[0]:\n"
          "        return                       # unchanged: do not rewrite the file\n"
          "    _island_sig[0] = sig\n", "", 1),
     "the island file is rewritten whether or not anything changed, on a loop "
     "that runs four times a second"),

    ("the-island-shows-vespers-own-state", ISLAND_SWIFT,
     _sub("        view.panel = loadVesperPanel(snapshotPath) + loadPanel(snapshotPath)",
          "        view.panel = loadPanel(snapshotPath)", 1),
     "one of the island's two refresh sites stops reading VESPER's rows, so "
     "they appear on first paint and vanish on the next refresh"),
]


if __name__ == "__main__":
    sys.exit(main())

