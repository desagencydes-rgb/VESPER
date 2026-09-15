#!/usr/bin/env python3
"""The process that closes the loop: reads what was typed, answers, shows it.

WHAT WAS MISSING. Every piece existed and nothing owned them together. The
field posted to Swift and Swift appended a line nobody read. `HomeState` derived
the face from bus events and no long-running process held a bus. The ladder
answered when something called it and nothing called it on the owner's behalf.
An engine, a steering wheel, and no ignition.

This is the ignition, and it is deliberately small: it owns the bus, wires the
five components that already work to each other, and pumps one file. Every
decision it appears to make is made somewhere else -- routing by `Router`,
permission by the gateway's choke point, wording by `narration.toml`, what
happens to a failure by `TriageQueue`. If this file grows a policy, the policy
is in the wrong place.

A FILE, NOT A SOCKET. The channel to the surface is a file because that channel
already existed in the other direction: `home.json` is written here and read by
the chrome. A socket would be a second kind of connection between the same two
processes, and `tools/ops/alarm_wake_linux.py` records what two mechanisms
governing one piece of state cost -- "one mechanism, one register, no hooks that
have to fire in the right order".

IT READS BY OFFSET AND NEVER TRUNCATES. Truncating the outbox would race the
writer: Swift appends without locking, and a truncation between its seek and its
write loses an utterance with nothing reporting it. Tracking a byte offset means
the two never touch the same bytes, and a restart re-reads from where it stopped
rather than replaying the day.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.advisor import Advisor                                 # noqa: E402
from core.agents import AgentRunner, AgentRosterError            # noqa: E402
from core.background import BackgroundJobs                       # noqa: E402
from core.bus import EventBus                                   # noqa: E402
from core.cost import CostPolicy                                # noqa: E402
from core.gateway import AllProvidersExhausted, ModelGateway    # noqa: E402
from core.hlc import HybridLogicalClock                         # noqa: E402
from core.home_state import HomeState, HOME_JSON  # noqa: E402
from core.intake import Intake                                  # noqa: E402
from core.knowledge_map import KnowledgeMap                     # noqa: E402
from core.interlock import EnableToken, SafetyInterlock         # noqa: E402
from core.chooser import Chooser                                # noqa: E402
from core import host as host_module                            # noqa: E402
from core import host_probes                                    # noqa: E402
from core.autonomy import AutonomyLoop, PredicateEvaluator      # noqa: E402
from core.devices import CONTINUITY_CRITICAL, DeviceRegistry    # noqa: E402
from core.repair import RepairAgent                             # noqa: E402
from core.floor import FloorHolder                              # noqa: E402
from core.forgetter import expiry_trigger                       # noqa: E402
from core.self_directed import all_triggers as self_directed_triggers  # noqa: E402
from core.self_directed import memory_drift_trigger             # noqa: E402
from core.self_directed import contradiction_trigger            # noqa: E402
from core.self_directed import map_staleness_trigger            # noqa: E402
from core.sensors import Sensor, SensorRegistry, SWEEP, TIMER   # noqa: E402
from core.world import WorldModel                               # noqa: E402
from core.difficulty import classify                            # noqa: E402
from core.effort import EXPECTED_OUTPUT                         # noqa: E402
from core.narration import Announcer                            # noqa: E402
from core.persona import Persona, Situation                     # noqa: E402
from core.context_control import ContextCommands                # noqa: E402
from core.presence import Presence                              # noqa: E402
from core.speech import Speech, speech_rows                     # noqa: E402
from core.baseline import BaselineRecorder                      # noqa: E402
from core.baseline import Turn as BaselineTurn                  # noqa: E402
from core.blocks import L1Renderer                              # noqa: E402
from core.arbiter import Arbiter                                 # noqa: E402
from core.compactor import Compactor                            # noqa: E402
from core.context import ContextBudgetManager                   # noqa: E402
from core.actor import Actor, ACTIVE_SESSION                    # noqa: E402
from core.intent import capability_statement, strip_internal_prefix  # noqa: E402
from core import permission_mode                                # noqa: E402
from core import agenda                                         # noqa: E402
from core import consent                                        # noqa: E402
from core.confirm import (ConfirmationBroker,                    # noqa: E402
                          NotTheQuestionInFront)
from core.confirm import requeue as consent_requeue             # noqa: E402
from core.confirm import ATTENTION_UNKNOWN                      # noqa: E402
from core.evidence import ClaimChecker                          # noqa: E402
from core.interruption import (InterruptionBudget,              # noqa: E402
                               Candidate)
from core.memory import MemoryGraph                             # noqa: E402
from core.extract import FactExtractor                          # noqa: E402
from core.updater import MissRecorder, Updater                  # noqa: E402
from core.quota import QuotaLedger                              # noqa: E402
from core.router import NoRouteAvailable, Router                # noqa: E402
from core.store import StoreSet                                 # noqa: E402
from core.transcribe import Transcriber, transcribe_rows        # noqa: E402
from core.triage import CRITICAL_NOW, TriageQueue               # noqa: E402
from core.verify import Verifier                                # noqa: E402
from core.verifiers import register_all                         # noqa: E402
from core.workbench import Workbench                            # noqa: E402
from core.changes import Changes                                # noqa: E402
from core.checkpoint import ShadowGit                           # noqa: E402
from core.actor import SHADOW_ROOT                              # noqa: E402
from core import longform                                       # noqa: E402
from routing import supply                                      # noqa: E402
from routing.supply import for_egress, load_rows, measured_profiles  # noqa: E402

STATE = Path.home() / "Library" / "Application Support" / "VESPER"

# What block B may spend. Conservative on purpose: the smallest
# context window in router.toml is what this has to fit inside, and
# the cost of being too small is a fact left out rather than a request
# refused by a provider.
L1_BUDGET_TOKENS = 1500
# WHAT COMPACTION ASKS FOR, and the shape of the ask is load-bearing. The result
# is written back to L2 at rank 5 as the system's reading of the owner's words,
# so a summariser that editorialises, guesses, or resolves a contradiction on its
# own has put an invention where a record should be. Contradictions belong to
# core/arbiter.py, which exists precisely because the thing that WRITES memory
# must not be the thing that decides which memory is right.
COMPACTION_SYSTEM = (
    "You merge several recorded statements about one topic into a single "
    "faithful summary. Keep every distinct fact. Do not add anything that is "
    "not in the input, do not guess, and do not resolve disagreements -- if the "
    "statements conflict, say that they conflict and give both. Reply with the "
    "summary only.")
COMPACTION_PROMPT = "Statements to merge:\n{items}"
# WHEN THE LIVE LOG IS ARCHIVED AND A FRESH ONE STARTED. `StoreSet.rotate` keeps
# the old file whole, continues the sequence past its high-water mark, and reads
# walk every segment -- so this bounds the file the runtime writes to and queries
# against, and loses nothing.
#
# HALF A GIGABYTE IS A THRESHOLD, NOT A MEASUREMENT, and is written here rather
# than in a contract because it is a property of this host's disk rather than of
# the design. The measured facts behind it: the live log reached 1.68 GB, of
# which 545 MB was a repair storm fixed at source and 420 MB was silence written
# one record per tick. Both of those are fixed; what remains grows at roughly 30
# MB/day, so this rotates on the order of a fortnight rather than daily.
#
# CHECKED ON A SLOW PERIOD, because `stat` on every pass is a syscall six times a
# second for an answer that changes over weeks. The same reasoning the host
# sensors use for their `period_ms`.
ROTATE_LOG_ABOVE_BYTES = 512 * 1024 * 1024
ROTATE_CHECK_EVERY_S = 600.0
# Module-level so the throttle survives across pump passes, which are separate
# calls rather than one long-lived loop body.
_LAST_ROTATE_CHECK = [0.0]

# The last changes payload's shape, so an unchanged board is not republished.
_changes_sig: list = [None]
OUTBOX = STATE / "say.jsonl"
# The wake listener records and queues; the runtime transcribes and
# answers. The split is deliberate: the credential and the egress
# decision live here, and the microphone lives in the app that holds
# the permission for it.
HEARD = STATE / "heard.jsonl"
HEARD_OFFSET = STATE / "heard.offset"
# WHAT THE OWNER ASKED FOR WITH A BUTTON. Appended by the Swift host's
# ControlBridge, drained here, applied by core/controls.py.
CONTROL = STATE / "control.jsonl"
CONTROL_OFFSET = STATE / "control.offset"
# When the settings rows and menu cards were last rebuilt (monotonic seconds).
_LAST_SURFACE_REFRESH = 0.0

# HOW THE HOME TELLS THE RUNTIME A MODE DID NOT LAND.
#
# The same shape as the pair above and for the same reason: the fact is produced
# in one process and needed in another, and `home.json` is written by THIS side
# so it cannot carry a report from the other. `mode.set` returns `ok` the moment
# it has resolved the pairing; the paint happens in the home up to half a second
# later, so the failure occurs after the only thing that can raise a flag has
# already returned. Driven 2026-09-09: the owner asked for a mode, vesper said
# done, and the picture never changed.
AMBIENCE = STATE / "ambience.jsonl"
AMBIENCE_OFFSET = STATE / "ambience.offset"


def _read_heard_offset() -> int:
    """How far the heard log has been consumed. An unreadable file is ZERO.

    `int(HEARD_OFFSET.read_text())` raised on an EMPTY file, and an empty file
    is exactly what a kill between truncate and write produces. The pump caught
    the ValueError and continued -- and then hit it again on the next tick, and
    every tick after, forever. A loop that fails identically every pass is not
    degraded, it is stopped, and this one stopped while still printing that it
    was continuing.

    ZERO IS THE SAFE ANSWER, not the last known value: re-reading lines already
    seen is idempotent here, while skipping ahead past unread ones loses what
    the owner said.
    """
    try:
        raw = HEARD_OFFSET.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0
OFFSET = STATE / "say.offset"

# How often the outbox is re-read. See the loop at the bottom for why it is
# this small: it is half of the owner-visible floor on a reply, and the other
# half is the chrome's own timer in HomeChrome.swift.
POLL_SECONDS = 0.15

# Consecutive failing passes before VESPER says so on the surface.
PUMP_FAIL_LOUD = 3


# Where `tools/ops/vesper_arm.py` leaves a fresh token. VESPER cannot write
# here: `interlock` is a self-defeating path segment, refused by the prohibited
# tier at every level including under an L5 grant.
# HOW LONG AN OWNER UTTERANCE PROVES THE OWNER IS THERE. Deliberately short:
# it is not "how long until they leave", it is "how long may this pump lag
# before the reading it took stops being a reading". A turn is dispatched and
# acted on in the same iteration, so the normal age here is milliseconds; a
# value this size only ever matters when something has gone wrong, and then it
# fails back to UNKNOWN rather than vouching for a presence nobody observed.
PRESENCE_FRESH_S = 20.0

# How long an unchanged repair verdict may stay silent before it says so
# anyway. Same purpose as `NOOP_KEEPALIVE_TICKS` in the autonomy loop: without
# it, "the repairer has nothing new" and "the repairer is dead" produce
# identical silence.
#
# IN SECONDS, NOT IN PASSES, AND THAT WAS MEASURED. As a pass count of 500 the
# keepalive fired every TWO MINUTES, because the pump turns over about four
# times a second -- so a constant chosen to mean "rarely" meant "constantly",
# and its meaning would drift again the next time the loop's cadence changed.
# A keepalive is a statement about elapsed time; counting passes makes it a
# statement about how busy VESPER is.
REPAIR_KEEPALIVE_S = 30 * 60

# The last verdict per triage item, and the wall second it was published on.
# Module level because `pump` is called fresh for a one-shot run and in a loop
# for the real one, and the point is to be quiet ACROSS passes.
#
# WALL CLOCK HERE IS NOT AN ORDERING. INV-COORD-4 forbids a timestamp deciding
# which record came first or superseding another; this asks "has half an hour
# passed", which is the same permitted shape as "has 09:00 arrived". Nothing is
# sorted or compared across nodes by it.
_repair_state: dict = {}

ENABLE_TOKEN_PATH = STATE / "interlock" / "enable_token.json"

# WHAT GETS MAPPED. The owner's instruction was "map literally everything, with
# submaps mapping their own parts" -- and submaps are already the shape
# `build()` produces: a directory is a node, its files hang off it, and a
# Python file's symbols hang off the file.
#
# THE ROOTS ARE DECLARED HERE RATHER THAN DISCOVERED, and that is deliberate.
# The map holds locators, hashes and a ONE-LINE SUMMARY -- never content, by
# contract -- but a summary is still derived from the file, so pointing this at
# a tree is a decision about what VESPER reads. The repository and VESPER's own
# workspace are unambiguous. Adding the owner's documents is one line and is
# theirs to add, not mine to assume.
MAP_ROOTS = (
    ("repo", REPO),
    ("workspace", STATE / "workspace"),
    # ("documents", Path.home() / "Documents"),   # owner's call
)



def _present_enable_token(interlock) -> None:
    """Hand the interlock whatever the minter last wrote, if it is new.

    EVERY FAILURE HERE IS SILENCE, AND SILENCE MEANS STOPPED. A missing file,
    malformed JSON, a half-written token, a token already seen -- all of them
    leave the interlock holding what it had, which expires on its own. That is
    the whole shape of a dead-man's switch: nothing this function can do
    wrongly results in autonomy running longer than it should.
    """
    try:
        raw = ENABLE_TOKEN_PATH.read_text(encoding="utf-8")
        d = json.loads(raw)
        token_id = str(d["token_id"])
        # "IF IT IS NEW" WAS IN THIS DOCSTRING AND NOWHERE IN THE CODE. This
        # runs every tick of the main loop; the minter rewrites the file every
        # couple of minutes. Between two mints the same token was presented
        # ~4 times a second, each one correctly refused as a replay and each
        # refusal published: 13,886 events in one hour, 343,470 in the live
        # log -- over 80% of every record VESPER has written. Nothing was
        # attacking it. It was asking itself the same question 4 times a
        # second and writing down the answer.
        #
        # Asking the interlock what it holds, rather than remembering what we
        # last sent, is what makes this safe: a fresh interlock holds nothing
        # and the token is presented normally. `_token` is never cleared, so
        # a match here is a token `present_token` would refuse anyway.
        if interlock.held_token_id() == token_id:
            return
        interlock.present_token(EnableToken(
            token_id=token_id, issued_at_ms=int(d["issued_at_ms"]),
            ttl_ms=int(d["ttl_ms"]), issued_by=str(d["issued_by"]),
            signature=str(d.get("signature", ""))))
    except Exception:                              # noqa: BLE001
        return



def _record_command(bench, capability_id, args, result) -> None:
    """Put one `shell.run` step on the commands card, or do nothing.

    ONLY `shell.run`. `fs.write` and `ui.open` are not commands and a card
    that showed them would be a second, worse copy of the actions column.

    ARGV FROM THE RESULT, NOT FROM THE ARGS. `args["cmd"]` is the string the
    proposer wrote; `result["argv"]` is the list `shell_run` split it into and
    handed the kernel. They are the same thing until the day they are not, and
    the card exists to say what RAN. The string is the fallback for a record
    that predates the field, not the preference.
    """
    if capability_id != "shell.run" or bench is None:
        return
    res = result if isinstance(result, dict) else {}
    a = args if isinstance(args, dict) else {}
    argv = res.get("argv") or a.get("cmd") or ""
    if not argv:
        return
    bench.command(argv,
                  cwd=str(res.get("cwd") or ""),
                  exit_code=res.get("exit_code"),
                  stdout=str(res.get("stdout") or ""),
                  stderr=str(res.get("stderr") or ""),
                  elapsed_ms=res.get("elapsed_ms"))



# THE METRICS CARD'S ROWS, and the seventh "built and reached by nothing" in
# this tree. `tools/home_snapshot.py` has produced them since it was written
# and `core/home_state.set_rows` has accepted them for just as long; nothing
# ever called either, so the HOST card read "no producer -- run
# home_snapshot.py" for weeks while both halves sat there working.
#
# NEVER PROBES A MODEL. `home_snapshot.probe()` runs a real routed completion
# against a local llama.cpp, and MEMORY.md's rule for this machine is explicit:
# local models heat it in a minute and cost tens of per cent of the battery in
# five, so they are not to be run OR measured here.
#
# AND UNTIL 2026-09-08 THAT LEFT THE FOUR MODEL ROWS WITH NO PRODUCER AT ALL.
# This block used to pass `build(None)` and claim in a comment that `build`
# "reads the last recorded completion if one is fresh" -- it does not and never
# did. Reading the evidence file is something `home_snapshot.main()` does;
# `build(None)` returns four unavailable readings immediately, and the only
# writer of that file was the probe this machine must not run. So `thinking`,
# `context`, `cache` and `tokens` were structurally unreachable, which is what
# the owner reported: they "don't appear when vesper is working".
#
# THE FIX IS THE ONE INV-HW-2 ALWAYS IMPLIES -- stop looking for a special
# measurement and read the one already being taken. Every model call in VESPER
# goes through `ModelGateway.complete`, and each success now publishes
# `model.completed` with the counts the provider itself reported. `_on_completed`
# below holds the newest, and it is a REAL completion the owner caused rather
# than a synthetic probe fired to populate a card.
#
# What always resolves is `host.power_source`, which is the row that actually
# matters on a laptop: MEMORY.md's own note is "this host runs on battery more
# often than you would assume -- check it before starting anything long".
METRICS_EVERY_S = 30.0
_metrics_at = [0.0]
_metrics_mod = [None]
_menu_context = {}  # Read-only references to live registries; never replacement instances.
# THE LAST COMPLETION, IN THIS PROCESS ONLY. Deliberately not persisted: read
# off disk at startup it would be a number from a previous run wearing this
# run's freshness, which is the defect `core/latency.py` refuses for the same
# reason. If nothing has been asked since VESPER started, the honest answer is
# that there is no measurement, and `home_snapshot.build(None)` gives it.
_last_completion = [None]


def _metric_rows():
    """The rows the HOST card renders, or None if they cannot be produced."""
    if _metrics_mod[0] is None:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location(
            "_home_snapshot", REPO / "tools" / "home_snapshot.py")
        if spec is None or spec.loader is None:
            return None
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _metrics_mod[0] = mod
    mod = _metrics_mod[0]
    proj = mod.build(_last_completion[0])
    scene = proj.to_scene("home-metrics", columns=mod.HOME_METRIC_KEYS)
    # THE OBSERVATION TIME TRAVELS WITH THE VALUE, AND A STALE ROW IS DROPPED.
    #
    # `Reading` carries `observed_at` and `core/projection.py` puts it on the
    # scene element -- and this function used to copy `label` and `value` and
    # throw the stamp away. The surface then had no way to tell a reading taken
    # a second ago from one taken this morning, and if the publisher ever
    # stopped, the last value would sit there looking current forever.
    #
    # FOUND BY THE SECOND AGENT, 2026-09-07, and it was a real catch: the page
    # said `battery` while `pmset -g batt` said `Now drawing from 'AC Power'`.
    # The producer was measuring correctly every time; the flattening was
    # discarding the evidence that it had.
    #
    # PAST THE TTL THE ROW IS OMITTED, not dimmed. `INV-HW-2`: UNKNOWN means
    # UNAVAILABLE, fail-closed -- and `core/projection.py` already drops an
    # unavailable reading rather than rendering one, "so the absent case cannot
    # be styled into looking like the present case". A stale number shown as
    # current is worse than no number, because the owner acts on it.
    now_ms = int(time.time() * 1000)
    rows = []
    for e in scene.elements:
        at = e.content.get("observed_at") or {}
        at_ms = int(at.get("physical_ms") or 0) if isinstance(at, dict) else 0
        if at_ms and (now_ms - at_ms) > mod.TTL_MS:
            continue
        rows.append({"label": mod.LABELS.get(e.element_id, e.element_id),
                     "value": str(e.content["value"]),
                     # WHOSE CARD THIS ROW BELONGS TO. See the block below --
                     # without it the HOST card was rendering menu readings.
                     "card": "host",
                     "at_ms": at_ms,
                     "ttl_ms": mod.TTL_MS})

    # THE ABSENT ONES TRAVEL TOO, AND THE PROJECTION IS WHY THEY HAVE TO.
    #
    # `to_scene` DROPS an unavailable reading rather than rendering one, "so
    # the absent case cannot be styled into looking like the present case".
    # That is right for the scene, and it means `scene.elements` above can
    # never carry the reason a row is empty -- so a row with nothing to say
    # simply disappears from the card, and the owner cannot tell "nothing has
    # been asked recently" from "the producer is broken".
    #
    # THIS WAS MEASURED, NOT REASONED. `home_snapshot.build` was changed on
    # 2026-09-08 to render a stale completion as an explicit absence, its check
    # asserted that on `proj.readings`, the check went green -- and the row
    # still vanished on the live surface, because nothing downstream of
    # `to_scene` ever saw it. A layer nobody renders is not a layer worth
    # asserting on.
    #
    # So the absences are read from the projection directly and shipped with
    # `status` and `reason`, the same shape `tools/menu_snapshot.py` already
    # uses for its 68 rows and the same shape the page already renders.
    # `at_ms` STAYS ZERO: nothing was observed, so there is no time to record,
    # and stamping `now` on an unobserved reading is the "value with an excuse
    # attached" that `Reading.__post_init__` refuses one layer up.
    shown = {r["label"] for r in rows}
    for key in mod.HOME_METRIC_KEYS:
        label = mod.LABELS.get(key, key)
        if label in shown:
            continue
        reading = proj.readings.get(key)
        rows.append({"label": label,
                     "value": "UNAVAILABLE",
                     "status": "unavailable",
                     "reason": (getattr(reading, "unavailable_reason", None)
                                or "this reading has no producer"),
                     "card": "host",
                     "at_ms": 0, "ttl_ms": 0})

    # The bridge is generic, but the original projection selected only five
    # keys. Append the catalogue here so the live pump reaches all menu rows.
    # OS acquisition runs in one background worker; old observations retain
    # their original at_ms and ttl_ms while it works.
    #
    # THESE ARE NOT HOST ROWS AND CARRY NO `card`, which is what keeps them out
    # of the HOST card. Until 2026-09-08 the page took the first five rows by
    # POSITION -- and `power_source` was the only host row that ever resolved,
    # so four menu readings were rendered inside the HOST card as though they
    # were host telemetry. Measured on the live surface: `Action outbox`, an
    # available menu row carrying a real stamp, sat in that slice and passed
    # the freshness filter. Position is not identity; the tag is.
    from tools.menu_snapshot import cached_rows
    rows.extend(cached_rows(_menu_context))
    return rows



# Failures VESPER caused and can answer itself. They reach the board and the
# actions column; they never reach the voice.
SILENT_ON_THE_TALK = ("bad_request",)

def _surface_repair(bench, transcript: list, home, item, out) -> None:
    """Put a provider failure where the owner can see it, and say one line.

    TWO SURFACES, TWO DIFFERENT JOBS, as the owner set them out. The BOARD gets
    what broke, what was tried and what would fix it -- long, typed, never
    spoken. The TALK gets one sentence, because a question the owner has to
    answer belongs where they are already looking and a paragraph read aloud is
    the failure `core/longform.py` exists to prevent.

    THE SENTENCE NAMES THE RUNG AND THE KIND. "That provider returned an error"
    is what the owner saw for weeks and it is true of five different situations
    that want five different responses from them -- wait, act, ignore, decide.
    """
    if bench is None:
        return
    kind = str(getattr(item, "classification", "") or "unknown")
    rung = str(getattr(item, "provider_id", "") or "a rung")
    blocks = []
    if out.note:
        blocks.append({"kind": "text", "text": out.note})
    if out.actions:
        blocks.append({"kind": "list", "items": list(out.actions)})
    if out.guide:
        blocks.append({"kind": "list", "items": list(out.guide)})
    if not blocks:
        return
    # KEYED ON THE ITEM, not on a conversation turn. `explain` replaces an
    # entry with the same id, so a rung that fails again in the same way
    # updates its explanation instead of stacking a second copy.
    bench.explain(item.item_id, f"{rung}: {kind.replace('_', ' ')}", blocks)

    # THE ONE SENTENCE. Shaped by what the owner can actually do about it,
    # which is the whole reason the classifier was taught to read the text.
    said = {
        "rate_limited": f"{rung} is out of allowance for now. It comes back on "
                        f"its own; I have written down what I found.",
        "quota_exhausted": f"{rung} has no allowance left. That one does not "
                           f"come back on its own -- the board has the detail.",
        "auth_failed": f"{rung} will not accept its credential, and that is "
                       f"yours to fix rather than mine. The board has the steps.",
        "model_gone": f"{rung} no longer serves that model. I have dropped the "
                      f"rung and written down what would restore it.",
    }.get(kind, f"{rung} is failing in a way I do not have a rule for. I have "
                f"written down what I saw.")
    # VESPER'S OWN MISTAKES DO NOT GO TO THE TALK.
    #
    # Owner, 2026-09-07: a malformed request "it's vesper's problem in the first
    # place ... it only shows up in explanations, actions, and everywhere
    # necessary". The board still gets the whole of it -- what was rejected,
    # what was changed, whether it worked -- because a silent correction nobody
    # can inspect is the thing this tree refuses everywhere else. What it does
    # not get is a sentence read aloud, because there is nothing for the owner
    # to decide.
    if kind in SILENT_ON_THE_TALK:
        return
    transcript.append({"who": "vesper", "source": "vesper", "certain": True,
                       "text": said, "id": item.item_id})
    del transcript[:-CONVERSATION_MAX]
    home.set_transcript(list(transcript))



# THE ISLAND'S VIEW OF VESPER ITSELF, on VESPER's clock rather than the
# machine's.
#
# `tools/island_snapshot.py` owns the machine readings -- thermal, memory,
# swap, power -- and refreshes them HOURLY, which suits a reading that moves at
# the speed of a laptop warming up. It suits nothing about VESPER's own state:
# the permission mode changes the moment the owner changes it, and a command
# runs in a second.
#
# SO THIS IS A SECOND KEY, NOT A SECOND FILE. `island.json` already merges
# (fixed 2026-09-07, it used to overwrite hourly), and one file with one writer
# per key is the rule `core/home_state.py` sets out and the reason the home has
# never had two clocks disagreeing about one moment.
#
# WHAT GOES HERE IS A GLANCE, NOT A BOARD. The island is 185pt wide. Counts and
# states; the detail lives on the home's cards where there is room to read it.
ISLAND_EVERY_S = 5.0
_island_at = [0.0]
_island_sig = [None]


_home_mode_cache: list = [0.0, ""]


def _home_mode() -> str:
    """The (stage, ambience) pairing the owner chose, or "" if none has been.

    THE EMPTY STRING IS A REAL ANSWER HERE and it is why the row is omitted
    rather than shown blank: until `mode.set` runs, `home.json` carries no
    `mode` key at all, and a row reading "Mode: —" would state that a mode is
    set to nothing. It is not set.
    """
    path = STATE / "home.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    if mtime == _home_mode_cache[0]:
        return _home_mode_cache[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mode = str(data.get("mode") or "").strip() if isinstance(data, dict) else ""
    except (json.JSONDecodeError, OSError):
        mode = _home_mode_cache[1]          # keep the last good read
    _home_mode_cache[0] = mtime
    _home_mode_cache[1] = mode
    return mode


def _island_vesper(bench, changes, mode: str = "") -> list:
    """The things about VESPER worth a glance, or fewer.

    `mode` IS A PARAMETER AND NOT A READ. `the-island-shows-vespers-own-state`
    extracts this function by AST and execs it with `permission_mode` alone in
    scope, so a module-level helper called from in here is a `NameError` under
    the check and works fine in production -- which is the worse direction of
    the two. Taking it as an argument keeps the function pure, keeps the check
    able to drive it, and lets the check drive the BOTH-MODES case that no
    live run would reach on demand.
    """
    rows = []
    # THE PERMISSION MODE FIRST, because it is a live authority state with no
    # indicator anywhere on any surface. The owner switches it and then has to
    # remember what they switched it to -- and in `auto` VESPER acts without
    # asking, which is precisely the state worth being able to see at a glance.
    #
    # LABELLED "Permission", NOT "Mode", SINCE 2026-09-10. It read "Mode", and
    # VESPER's own mode -- the (stage, ambience) pairing -- appeared on this
    # surface nowhere at all. A reader looking at `Mode: auto` and asking
    # whether modes worked got the wrong answer from the right row; that
    # happened, and the owner had to correct it. Two different axes cannot
    # share one word on a surface 185pt wide.
    try:
        rows.append({"label": "Permission", "value": permission_mode.read()})
    except Exception:                               # noqa: BLE001
        pass
    # AND THE MODE THE OWNER ACTUALLY CHOSE. Read from `home.json`, which is
    # where `core/modes.select` publishes it -- not from `HomeState`, whose
    # copy is written only by a caller that has one and `mode.set` does not.
    #
    # ONLY WHEN THE FILE HAS MOVED. `home.json` is ~140 KB and this runs every
    # five seconds; re-parsing it on a tick that has nothing to say is work
    # done to learn nothing, so the mtime gates it.
    if mode:
        rows.append({"label": "Mode", "value": mode})
    st = bench.state() if bench is not None else {}
    cmds = st.get("commands") or []
    if cmds:
        last = cmds[-1]
        rows.append({"label": "Ran",
                     "value": f"{len(cmds)}" + ("  !" if last.get("state") == "failed" else "")})
    try:
        n = len((changes.state().get("changes") or [])) if changes is not None else 0
    except Exception:                               # noqa: BLE001
        n = 0
    if n:
        rows.append({"label": "Changed", "value": str(n)})
    return rows


def _publish_island(bench, changes, bus) -> None:
    """Merge VESPER's own rows into island.json. Never the machine's keys."""
    now = time.time()
    if now - _island_at[0] < ISLAND_EVERY_S:
        return
    _island_at[0] = now
    rows = _island_vesper(bench, changes, mode=_home_mode())
    sig = json.dumps(rows, sort_keys=True)
    if sig == _island_sig[0]:
        return                       # unchanged: do not rewrite the file
    _island_sig[0] = sig
    path = STATE / "island.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    existing["vesper"] = rows
    # A UNIQUE TEMP PER WRITE, and `threading.get_ident()` rather than
    # `os.getpid()` because `os` is not imported in this module -- the first
    # version used it and would have raised NameError on the first publish,
    # inside the try/except that turns it into a bus event nobody reads.
    tmp = path.with_name(f"island.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(existing, indent=1), encoding="utf-8")
    tmp.replace(path)

# ------------------------------------------------------------------ one only
#
# ONE RUNTIME, AND THE OWNER PAID TO LEARN WHY. Killing the home app does NOT
# kill the python runtime it spawned: the child is reparented to launchd and
# keeps running, so every restart stranded another one. Measured 2026-09-13 --
# THREE runtimes alive at once, two of them orphans with ppid 1. Each reads
# `say.jsonl`, each answers every utterance, and each speaks. The owner reported
# "too many fucking voices at the same time, with lot of rate limit responses",
# and that is what it was: one question answered three times, three times the
# provider calls, three voices over each other.
#
# AN ADVISORY LOCK RATHER THAN A PID FILE. A pid file records an intention and
# goes stale the moment a process dies badly; a flock is held by the KERNEL and
# is released when the holder exits for any reason, including a kill -9. The
# file is opened and deliberately never closed -- the handle must outlive this
# function or the lock goes with it.
_RUNTIME_LOCK = []


def _only_one_runtime() -> None:
    """Exit rather than become the second voice in the room."""
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True)
    fh = open(STATE / "runtime.lock", "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another vesper runtime already holds the lock; this one exits "
              "rather than answering every utterance a second time.",
              flush=True)
        raise SystemExit(0)
    fh.write(str(os.getpid()))
    fh.flush()
    _RUNTIME_LOCK.append(fh)          # never closed: the lock lives with it


def build(node: str = "vesper-runtime"):
    """Wire what already exists. Nothing here decides anything."""
    STATE.mkdir(parents=True, exist_ok=True)
    clock = HybridLogicalClock(node)
    store = StoreSet(STATE / "bus", node_id=node)
    bus = EventBus(clock, store, component="runtime")
    cost = CostPolicy(bus, clock)
    ledger = QuotaLedger(path=STATE / "quota.json", bus=bus)
    gw = ModelGateway(bus, cost, quota=ledger)

    # THE HOME'S FOUR MODEL ROWS GET THEIR PRODUCER HERE. See the block above
    # `_metric_rows` for why they had none. The gateway publishes counts the
    # provider reported; this keeps the newest and `_metric_rows` renders it.
    _last_hlc = [None]

    def _on_completed(e) -> None:
        # ORDERED BY HLC, NEVER BY THE `at_ms` IN THE PAYLOAD. INV-COORD-4:
        # wall clock does not order or supersede, and "which completion is
        # newer" is exactly a supersession question. `at_ms` is carried for
        # DISPLAY -- it is how the row states its own age to the owner -- and
        # comparing two of them here would be the violation `CI-005` refuses.
        if _last_hlc[0] is not None and e.observed_at_hlc < _last_hlc[0]:
            return
        _last_hlc[0] = e.observed_at_hlc
        _last_completion[0] = dict(e.payload)

    # `event_id` IS GENUINELY THE RIGHT KEY, which INV-COORD-5 asks to be said
    # explicitly rather than passed silently. Each completion is its own
    # measurement -- two calls to the same rung a second apart are two facts,
    # not one repeated -- so nothing coarser would be correct, and a redelivery
    # of one event re-applies an assignment that is already its own value.
    bus.subscribe("model.completed", _on_completed, name="home-model-metrics",
                  idempotency_key=lambda e: e.event_id)

    report = supply.register(gw, cost, ledger, egress_class="E1_PRIVATE")
    rows = for_egress(load_rows()[0], "E1_PRIVATE")
    router = Router(bus, measured_profiles(rows, purpose="text"))

    home = HomeState(bus=bus, clock=clock)

    # EVERY FLAG REACHES THE BAR. The executor publishes `flag.raised` from the
    # one point every capability's result passes through; without this
    # subscription those events are produced and consumed by nothing, which is
    # the built-and-unreached shape this tree keeps finding.
    def _on_flag(e) -> None:
        pay = e.payload or {}
        # THE RE-PROOF TRAVELS WITH THE FLAG, so a flag that outlives this
        # process can be retired by evidence rather than by whatever happened to
        # raise it running again. See HomeState.raise_flag.
        home.raise_flag(str(pay.get("id") or "flag"), str(pay.get("text") or ""),
                        recheck=pay.get("recheck"))

    # `event_id` IS THE KEY, and INV-COORD-5 asks for it to be said. A flag is
    # raised by one execution; a redelivery of that event re-raises the same
    # condition with the same id, which `raise_flag` collapses rather than
    # duplicating -- so the subscription is idempotent in the way that matters.
    bus.subscribe("flag.raised", _on_flag, name="home-flags",
                  idempotency_key=lambda e: e.event_id)

    # AND EVERY RETRACTION REACHES IT TOO, or the bar is a list of things that
    # were once wrong. `clear_flag` had exactly one caller before this line and
    # it was the CHECK for the flag bar, which called it itself and asserted the
    # row disappeared -- so the mechanism was proven and reached by nothing. The
    # cost is a false alarm with no expiry: accessibility is revoked by every
    # rebuild, the owner grants it, vesper works, and the bar goes on saying it
    # is not granted until the process restarts.
    def _off_flag(e) -> None:
        fid = str((e.payload or {}).get("id") or "").strip()
        if fid:
            home.clear_flag(fid)

    bus.subscribe("flag.cleared", _off_flag, name="home-flags-cleared",
                  idempotency_key=lambda e: e.event_id)
    # FLAGS INHERITED FROM THE LAST PROCESS ARE KEPT, AND MARKED AS INHERITED.
    #
    # `build.sh` restarts this runtime on every build, and until 2026-09-11 that
    # emptied the bar whether or not the problems were over -- the owner's
    # complaint, and the reason a real warning about a missing grant vanished
    # twenty minutes after it was raised. `HomeState` now loads them back.
    #
    # WHAT THIS DELIBERATELY DOES NOT DO IS RE-RUN THEM. The first version did:
    # it looked up each flag's capability implementation and called it. That
    # invents an execution path with no authorization, no taint handling and no
    # record, at process start, for a capability the ladder governs everywhere
    # else -- and it referenced a module this file does not even import, so it
    # would have raised at startup. A boundary that one code path steps around
    # is not a boundary, and "it was only a read" is the argument every such
    # step-around makes.
    #
    # SO A CARRIED FLAG IS HELD AS UNPROVEN RATHER THAN ASSERTED AS TRUE, and it
    # leaves the bar the one way flags already leave it: the next time that
    # condition is genuinely exercised and succeeds, `flag.cleared` retracts it.
    # The cost is that a problem the owner fixes may show for a while after they
    # fix it. That is the direction to be wrong in -- forgetting a live problem
    # loses the only notice they get; keeping a resolved one costs a glance, and
    # the row says it has not been re-checked so the glance is informed.
    def _mark_carried_flags() -> None:
        # `print`, BECAUSE THIS MODULE HAS NO `log`. The first version called
        # one, there is no such function here, and the NameError killed the
        # runtime AT STARTUP -- vesper was simply down, and the gates were all
        # green because none of them start the process. Driving it end to end is
        # what found it, which is the whole argument for doing that.
        carried = home.carried_flags()
        for f in carried:
            print(f"flag carried across restart, not yet re-checked: "
                  f"{f.get('id')} — {str(f.get('text'))[:80]}", flush=True)
        if carried:
            print(f"{len(carried)} flag(s) survived the restart; each retracts "
                  f"when its condition is next exercised and clears", flush=True)

    home.attach(bus)
    _mark_carried_flags()
    # THE SETTINGS SURFACE'S VALUES, READ ONCE AT STARTUP (§11.6). The owner's
    # note is that the card "stops reading UNAVAILABLE", and that only happens if
    # something produces the readings -- a screen naming thirty-four settings and
    # showing a value for none of them is the UNAVAILABLE card with more words.
    try:
        _n = home.refresh_settings()
        print(f"settings surface: {_n} item(s) read", flush=True)
    except Exception as exc:                              # noqa: BLE001
        print(f"settings surface could not be read: {exc!r}", flush=True)

    triage = TriageQueue(path=STATE / "triage.json", bus=bus, clock=clock)
    triage.attach(bus)

    # SPOKEN WHEN THE OWNER IS WAITING, which is what typing into the field
    # means. RB-006 governs the other case and this process does not have one
    # yet: everything it handles is a request somebody just made. The
    # destination of a descent is no longer handed in here: it comes from
    # `gateway.descended`, with the row's measured locality, and the budget
    # cell comes from `narration.toml`'s `waiting_cell`.
    announcer = Announcer(bus=bus)
    announcer.attach(bus, interruption_class="active_user_task")

    intake = Intake(bus=bus, clock=clock)
    # LOADED ONCE, AT BUILD, AND ALLOWED TO STOP THE PROCESS. `Persona.load`
    # raises on a contract it cannot validate, and that raise is not caught
    # here: a runtime that starts without a persona answers fluently and
    # namelessly, which is indistinguishable from working and was the state of
    # this system until 2026-08-26.
    persona = Persona.load(bus=bus)
    # SUBSCRIBES, LIKE THE FACE DOES. Nothing on the request path calls into it:
    # a board somebody has to remember to update is accurate until the first
    # time somebody forgets.
    bench = Workbench()
    # WHAT VESPER IS WAITING FOR THE OWNER TO DO. Not answers -- CONDITIONS.
    # See core/waiting.py: the owner asked that doing the thing be enough, and
    # that they never have to say they did it.
    from core.waiting import Waiting as _Waiting
    waiting = _Waiting()
    bench.attach(bus)
    # THE BOARD SURVIVES A RESTART. Without this, every rebuild and every login
    # blanked the commands and explanations panes -- which the owner saw and
    # reported as a card disappearing. `home.json` is already the contract with
    # the chrome and already persists; this reads back what it holds before the
    # first pump overwrites it.
    try:
        _prior = json.loads(HOME_JSON.read_text(encoding="utf-8"))
        _n = bench.seed(_prior.get("workbench") or {})
        if _n:
            bus.publish("workbench.restored", subject="workbench",
                        payload={"rows": _n}, component="runtime")
    except (OSError, json.JSONDecodeError, ValueError):
        # A MISSING OR TORN FILE IS A COLD START, NOT AN ERROR. The board is
        # empty, which is correct, and nothing about the turn ahead depends on
        # what was on screen before it.
        pass

    # THE CHANGED-FILES BOARD. Reads the SAME shadow repository the executor
    # already snapshots into -- `core/checkpoint.py` mirrors every file VESPER
    # is about to touch, because a capability that changes files does not run
    # when its pre-state cannot be recorded. So the "before" of every write
    # already exists in a real git repository, and this reads it rather than
    # keeping a second copy that would eventually disagree.
    changes = Changes(shadow=ShadowGit(SHADOW_ROOT))
    changes.attach(bus)

    # MEMORY DEGRADES; IT DOES NOT STOP THE PROCESS, and that is a different
    # decision from the one made about the persona ten lines up. A runtime with
    # no persona answers fluently and namelessly, which is indistinguishable
    # from working and is the state this system was in until 2026-08-26 -- so
    # that one raises. A runtime with no MEMORY is a well-defined thing:
    # `core/baseline.py` exists precisely to record what VESPER answers without
    # it, and that record is the comparison every question about this design
    # depends on.
    #
    # WHAT MAY NOT HAPPEN IS DEGRADING SILENTLY. A turn answered without memory
    # looks exactly like a turn answered with it -- fluent, confident, and
    # missing whatever it should have known. So the failure is published, and
    # `renderer is None` is what every downstream branch reads.
    # THE CHOOSER WITH NO ESCALATOR IS EXACTLY TODAY'S BEHAVIOUR, which is
    # what makes wiring it now safe rather than premature. It runs the same
    # deterministic classifier the runtime already called, reports the same
    # difficulty, and calls nothing -- while putting the escalation path,
    # the raise-only rule and the hold threshold in place for the moment a
    # rung is chosen to serve it. `MEMORY_ARCHITECTURE.md` puts the chooser on
    # Groq at 0.42-0.67 s measured, which is a decision with a cost and is the
    # owner's to take.
    chooser = Chooser(bus=bus)
    # PRESENCE, DECLARED BY THE OWNER. Costs a phrase-list match per utterance
    # and nothing else -- the layered per-turn identity check was designed and
    # dropped as too expensive, and this covers the same ground until cameras
    # exist. `PrivacyRouter` has always resolved an unknown person toward the
    # most private surface and has never had anything to tell it one was there.
    presence = None

    # THE WORLD MODEL AND ITS SENSORS. `trigger_registry.toml`'s predicates read
    # `world.current_host.power_source` and `world.current_host.health`; nothing
    # has ever written them, so every predicate over them has been UNKNOWN and
    # INV-TRIG-4 has correctly stopped all eight triggers from firing. These are
    # the first two facts that make any of them evaluable.
    #
    # TIMER CLASS, GENEROUS PERIODS, AND NOT BECAUSE THE PROBES ARE SLOW. They
    # take microseconds. The period is about not waking a sleeping machine to
    # ask it how it feels -- MEMORY.md records the owner's instruction not to
    # stress this host, and a sensor loop is exactly the kind of thing that
    # looks free and is not.
    # THE CLOCK IS NOT OPTIONAL AND ITS DEFAULT IS `lambda: 0`. Without it
    # `_expired()` compares `0 >= valid_until_ms` and NOTHING EVER EXPIRES: the
    # world model happily reports a reading from an hour ago as current,
    # INV-COORD-2 is vacuously satisfied, and `trg_fact_expiry_sweep` can never
    # fire. Every freshness property in the design is inert without this line,
    # and nothing anywhere would say so.
    # THE SUBJECT IS `world.current_host`, NOT `current_host`, and the
    # difference is the whole point of these sensors existing. A predicate's
    # snapshot resolves `world.current_host.health` by splitting on the LAST
    # dot -- subject `world.current_host`, attribute `health`. Sensors written
    # against subject `current_host` populate a subject no predicate can read,
    # so the world fills up correctly and every trigger over it stays UNKNOWN
    # and silent. Found 2026-08-31 by driving trg_placement_reevaluate end to
    # end instead of trusting that the facts were landing.
    world = WorldModel(bus, clock, now_ms=lambda: int(time.time() * 1000))
    presence = Presence(world, clock, bus=bus)
    # SR-008's manual mode, reachable at last. `ContextBudgetManager` has pinned
    # fragments and refused to drop them since it was written, and is
    # constructed in exactly one place in this repository -- an acceptance
    # runner. What was missing was never the mode; it was a surface the owner
    # could speak to, and anything at all reaching it.
    context_cmds = ContextCommands(bus=bus)
    sensors = SensorRegistry(world, clock, bus=bus)
    sensors.register(Sensor("host-power", "world.current_host", "power_source",
                            host_probes.power_source, TIMER,
                            period_ms=60_000, ttl_ms=300_000))
    sensors.register(Sensor("host-health", "world.current_host", "health",
                            host_probes.host_health, TIMER,
                            period_ms=120_000, ttl_ms=600_000))
    sensors.register(Sensor("host-disk", "world.current_host", "disk_free_ratio",
                            host_probes.disk_free_ratio, TIMER,
                            period_ms=300_000, ttl_ms=900_000))
    # PRESENCE FROM THE CAMERA, AS A FLAG (VISION-IDENTITY.md). The camera is a
    # GATED source and is never on this timer: what is polled here is the FILE
    # the owner's probe wrote, cheap to read, and it reads UNKNOWN 120 s after
    # the probe rather than the last value. Detection, not identity.
    sensors.register(Sensor("camera-presence", "world.owner", "presence",
                            host_probes.camera_presence, TIMER,
                            period_ms=15_000, ttl_ms=120_000))

    # THE PLATFORM'S OWN VERDICT, TRANSLATED. `core/host.py` exists so the raw
    # numbers never reach the shared logic -- a value meaning "healthy" on one
    # platform means "about to fail" on another -- and it was imported by
    # nothing. It is NOT a second scheduler: two schedulers sharing a machine
    # and unable to see each other oscillate, so this reads and does not act.
    # Measured on this Mac: 0.03 s per read, so a minute is comfortable.
    host_adapter = host_module.adapter_for_host()

    def _host_pressure_degraded() -> Any:
        try:
            return bool(host_adapter.read_pressure().degraded)
        except Exception:                          # noqa: BLE001
            return None                            # UNKNOWN, never False

    sensors.register(Sensor("host-pressure", "world.current_host",
                            "pressure_degraded", _host_pressure_degraded,
                            TIMER, period_ms=60_000, ttl_ms=300_000))
    # REPAIR, OVER THE FAILURES TRIAGE IS ALREADY COLLECTING. `TriageQueue`
    # has been grading provider failures into an open list since it was wired,
    # and nothing has ever tried to fix one -- so the queue is a record of
    # things that went wrong and stayed wrong.
    #
    # THE MODULE IS ALREADY HONEST ABOUT ITS LIMITS, which is why wiring it is
    # safe: tier 1 is autonomous and reversible (rotate to a sibling credential,
    # stand a rung down until a stated time); tier 2 is PROPOSED and never
    # applied, because INV-SELF-1..7 forbid the runtime writing a governed path
    # in the running artifact; tier 3 says plainly that it cannot be fixed from
    # in here. A repair layer that pretended otherwise would produce a sequence
    # of confident-looking actions that change nothing, followed by the same
    # failure.
    repairer = RepairAgent(gateway=gw, bus=bus)

    # THE DEVICE REGISTRY, AND THIS NODE IN IT, MEASURED. `INV-HW-2`: a
    # capability is measured at enrollment or it is UNAVAILABLE, and
    # `DeviceProfile.capability()` returns None for anything whose `measured`
    # flag is False rather than the declared value. Registering this node is
    # what lets `INV-TRUST-2` be checked at all -- no continuity-critical
    # capability on a foreground-only node -- and it is checked here rather than
    # assumed because there is exactly one node today and that is precisely when
    # the assumption is invisible.
    #
    # A FAILURE HERE DOES NOT STOP THE PROCESS. An unregistered device means
    # placement cannot be reasoned about; it does not mean VESPER cannot answer.
    devices = DeviceRegistry(bus)
    try:
        profile = devices.register(host_probes.device_profile(node))
        devices.assign("memory", [node])
        bus.publish("devices.self_registered", subject=node,
                    payload={**profile.to_dict(),
                             "survival_host": profile.is_survival_host(),
                             "trust_zone_ceiling": profile.trust_zone_ceiling()},
                    component="runtime")
    except Exception as exc:                       # noqa: BLE001
        bus.publish("devices.self_registration_failed", subject=node,
                    payload={"error": repr(exc),
                             "note": ("placement cannot be reasoned about "
                                      "without a profile; answering is "
                                      "unaffected")},
                    component="runtime")

    # THE SWEEP. Nothing EMITS an event when a fact lapses -- time alone makes
    # it true -- so the only way to see it is to ask. `expired_present` is the
    # term `trg_fact_expiry_sweep` reads, and it cannot be expressed as a dotted
    # world term any other way: a predicate snapshot resolves `subject.attribute`
    # through `read()`, and "any fact" is not that shape.
    sensors.register(Sensor("fact-expiry", "world.facts", "expired_present",
                            world.expired_present, SWEEP, period_ms=30_000))

    # THE OWNER'S DAY, WHICH NOTHING WATCHED UNTIL NOW. Same sweep shape and
    # the same reason: an appointment becoming imminent emits nothing, so the
    # only way to see it is to ask. `core/agenda.py` reads VESPER's own plan
    # file plus whatever the app's EventKit bridge last wrote, and reports an
    # unreadable calendar as UNAVAILABLE rather than as a clear day -- so this
    # term is False both when there is nothing due AND when VESPER cannot see,
    # and the two are told apart in words rather than by acting on the second
    # as though it were the first.
    sensors.register(Sensor("agenda-due", "world.agenda", "item_due",
                            agenda.item_due, SWEEP, period_ms=60_000))

    # THE AUTONOMY LOOP. `tick()` DECIDES AND PUBLISHES; IT DOES NOT ACT --
    # actuation is a separate concern with its own gate, and the interlock is
    # what will stand in front of it. Wiring the decision half now means the
    # eight triggers stop evaluating over an empty world, and every firing
    # arrives with the snapshot that is its evidence (A-029 Part 2) and with
    # `model_involved_in_decision: False` (INV-AUTO-2), which the evaluator
    # enforces structurally rather than reporting.
    #
    # ONE TRIGGER IS WIRED HERE AND SEVEN ARE NOT, and that is honest rather
    # than partial: the other seven read terms nothing populates yet
    # (`nodes.reachable_set`, `proposals.count`, `world.owner.attention_state`).
    # A trigger registered over a term no sensor writes evaluates UNKNOWN and
    # never fires, which looks identical to one that is working and quiet.
    autonomy = AutonomyLoop(bus, world, PredicateEvaluator(bus, world),
                            now_ms=lambda: int(time.time() * 1000))
    autonomy.register(expiry_trigger())
    # THE LOOP HAD ONE INSTRUCTION UNTIL 2026-09-01. It woke on every pass,
    # found memory expiry the only thing to consider, and went back to sleep.
    for _t in self_directed_triggers():
        autonomy.register(_t)

    memory = renderer = updater = misses = compactor = arbiter = None
    try:
        memory = MemoryGraph(store, path=str(STATE / "l2.db"))
        # THE CONSOLIDATION LOOP, WHICH HAD NEVER RUN. core/compactor.py holds
        # the rule this memory design rests on -- project(L3), never
        # compact(L1) -- and nothing in the running system imported it, so
        # nothing had ever noticed L2 drifting from the log it is a view of.
        # THE SUMMARISER, ON THE COMPACTOR'S OWN RUNGS. `purpose="compactor"`
        # routes this to mistral-compactor and cf-compactor rather than to the
        # text rungs a turn uses -- separate accounts, separate ledgers, so a
        # night of compaction cannot spend the budget the owner talks to VESPER
        # through. Checked against the contract before wiring: of 26 declared
        # credentials only two are shared between purposes, and neither is the
        # compactor's.
        #
        # BOTH RUNGS ARE metered_free_tier WITH provable_hard_cap = true, which
        # is the only reason this may run in FREE_TIME at all: INV-COST-5 treats
        # a metered free tier as PAID unless the cap is provable, and the
        # contract carries the evidence for each.
        #
        # IT RAISES RATHER THAN RETURNING A PLACEHOLDER. A summariser that
        # returned "" or "unavailable" would have that text written into L2 as a
        # rank-5 fact -- the system's own reading of the owner's words -- and the
        # failure would become memory. Raising is what lets the trigger's handler
        # record it as `failed` instead.
        compactor_profiles = measured_profiles(rows, purpose="compactor")
        compactor_router = (Router(bus, compactor_profiles)
                            if compactor_profiles else None)

        def _compactor_summarise(values: list) -> str:
            if compactor_router is None:
                raise RuntimeError("no compactor rung is enrolled")
            joined = "\n".join(f"- {v}" for v in values)
            decision = compactor_router.select("moderate", prefer="cost",
                                               task_id="memory-compaction")
            out = gw.complete(
                COMPACTION_PROMPT.format(items=joined),
                task_id="memory-compaction", system=COMPACTION_SYSTEM,
                profile_id=decision.profile_id, prefer="cost",
                expected_output_tokens=256, difficulty="moderate")
            text = ((out.get("result") or {}).get("text") or "").strip()
            if not text:
                raise RuntimeError("the summariser returned nothing")
            return text

        compactor = Compactor(memory, store, clock, bus=bus,
                              summariser=(_compactor_summarise
                                          if compactor_profiles else None))
        # THE ARBITER, WHICH THE UPDATER CANNOT BE. The updater runs after the
        # act and must never block a turn, so it has no way to surface anything
        # and no business deciding what happens when two things it wrote
        # disagree. That is why this is a separate subsystem -- and it has been
        # reachable from nothing since it was built.
        arbiter = Arbiter(memory, bus=bus)
        # L1'S BUDGET IS TOKENS AND IT HAD NONE. `ContextBudgetManager` was
        # built for this and constructed only by tests, so block B truncated at
        # a fact COUNT -- five long facts could overrun a provider's window
        # while five short ones wasted it. The number is a conservative default
        # rather than a measurement: it is the first consumer this budget has
        # ever had, and INV-HW-2's discipline says a figure nobody measured is
        # not presented as one. Per-provider budgets are the next step now that
        # something reads it at all.
        renderer = L1Renderer(persona, memory,
                              budget=ContextBudgetManager(
                                  bus, budget_tokens=L1_BUDGET_TOKENS))
        # THE EXTRACTOR, without which memory is a transcript. `Updater` has
        # always had this slot and nothing ever filled it, so every fact landed
        # as `owner/said` at rank 4 -- the owner's sentence, verbatim, findable
        # only by someone who already remembered the sentence. Told a fact
        # about Sami on 2026-08-31 and asked to recall it, VESPER answered
        # UNKNOWN: the words were in memory and the FACT was not.
        #
        # Its readings land at rank 5 as `model_generated`, so a wrong reading
        # can never outrank the verbatim row sitting beside it.
        updater = Updater(memory, store, clock, bus=bus,
                          extractor=FactExtractor(gw, bus=bus))
        misses = MissRecorder(memory, store, clock, bus=bus)
    except Exception as exc:                       # noqa: BLE001
        bus.publish("memory.unavailable", subject="l2",
                    payload={"error": repr(exc),
                             "note": ("answering WITHOUT memory. This is the "
                                      "baseline condition, and it is published "
                                      "because a turn without memory is "
                                      "indistinguishable from one with it.")},
                    component="runtime")

    # DOES L2 STILL MATCH WHAT L3 PROJECTS? Registered here because it needs
    # both memory and the compactor, and both are None if memory failed to open.
    #
    # COUNTING IS THE CHEAP HALF; the authority is `Compactor.verify()`, which
    # the trigger's handler runs. A sensor that projected the whole log every
    # ten minutes would be a maintenance pass pretending to be a probe.
    if memory is not None and compactor is not None:
        def _l2_drifted() -> Any:
            try:
                l2 = int(memory.counts().get("fact", 0))
                rows = store.read("log", kind="memory.fact", limit=1_000_000)
                return l2 != max(0, len(rows) - len(compactor.erased_seqs()))
            except Exception:                       # noqa: BLE001
                # UNKNOWN, NOT FALSE. A probe that cannot answer must not
                # report drift: the predicate treats UNKNOWN as "do nothing",
                # and returning False here would rebuild L2 on every transient
                # read error.
                return None

        sensors.register(Sensor("l2-drifted", "world.memory",
                                "l2_drifted", _l2_drifted, SWEEP,
                                period_ms=600_000))
        autonomy.register(memory_drift_trigger(compactor))

        def _contradictions_present() -> Any:
            try:
                return bool(arbiter.contradictions())
            except Exception:                       # noqa: BLE001
                return None                         # UNKNOWN, never False

        sensors.register(Sensor("memory-contradictions", "world.memory",
                                "contradictions_present",
                                _contradictions_present, SWEEP,
                                period_ms=600_000))
        autonomy.register(contradiction_trigger(arbiter))

    # THE MAP, WHICH SR-007 EXISTS FOR: navigate the corpus instead of dumping
    # it into context. Built here, kept true by the trigger below. Failure to
    # build one root does not stop the others -- a partial map reports its own
    # coverage rather than pretending to be complete.
    maps = []
    for _name, _root in MAP_ROOTS:
        try:
            if not Path(_root).is_dir():
                continue
            maps.append(KnowledgeMap(_root, map_id=f"map-{_name}").build())
        except Exception as exc:                    # noqa: BLE001
            bus.publish("map.build_failed", subject=_name,
                        payload={"root": str(_root), "error": repr(exc)},
                        component="runtime")
    if maps:
        bus.publish("map.built", subject="startup",
                    payload={"maps": [{"map_id": m.map_id,
                                       "nodes": len(m.nodes),
                                       "coverage": m.coverage_ratio}
                                      for m in maps]},
                    component="runtime")

        def _map_stale() -> Any:
            try:
                return any(m.refresh() for m in maps)
            except Exception:                       # noqa: BLE001
                return None                         # UNKNOWN, never False

        # MEASURED, NOT CHOSEN. On this repository the map is 8,561 nodes --
        # 210 directories, 1,704 files, 6,647 symbols -- and costs 3.95 s to
        # build and 1.02 s to re-hash, holding roughly 4.3 MB. A five-minute
        # sweep would re-read every mapped file twelve times an hour for a
        # second each; fifteen minutes is a 0.1% duty cycle, which is the right
        # trade on a laptop that is usually on battery. Measured 2026-09-01.
        sensors.register(Sensor("map-staleness", "world.map", "stale_present",
                                _map_stale, SWEEP, period_ms=900_000))
        autonomy.register(map_staleness_trigger(maps))

    # VERIFICATION, REGISTERED RATHER THAN DECLARED. `core/verify.py` listed two
    # machine-checkable strategies and `Verifier` was a registry with nothing in
    # it, so every task naming one reached a verdict of "no verifier registered"
    # -- fail-closed, therefore invisible. `should_defer` now asks the registry,
    # which means a runtime that registers nothing DEFERS free-time work instead
    # of running it into a BLOCKED verdict; that only helps if something
    # actually registers here.
    #
    # THE CHECKER IS PASSED ONLY WHEN MEMORY LOADED. Without it
    # `retrieval_grounded` cannot ground anything, and claiming it is available
    # would put the runtime back in the state this replaced.
    # SPEAKING IS EGRESS, so the synthesiser choice reads the same supply table
    # every other provider decision reads. No row declares purpose = "speech"
    # today, so this resolves to local synthesis -- which is correct and is
    # ALSO audibly worse for Darija, and `core/speech.py` reports that rather
    # than letting the owner wonder why the voice changed.
    # SPEECH ROWS, NOT THE TEXT LADDER'S. `load_rows` enforces INV-HW-2's
    # measured-throughput rule, which every synthesiser fails for a reason that
    # does not apply to it -- a voice is not routed by tokens per second.
    speech = Speech(bus, supply=speech_rows())
    transcriber = Transcriber(bus, supply=transcribe_rows())

    verifier = Verifier(bus)
    checker = (ClaimChecker(bus, REPO, store=store)
               if memory is not None else None)
    available = register_all(verifier, checker)
    bus.publish("verify.registry", subject="startup",
                payload={"available": list(available),
                         "note": ("what can actually be checked here. A "
                                  "strategy name is not a strategy, and "
                                  "DF-VERIFY-SELECT takes available_verifiers "
                                  "as an input for this reason.")},
                component="runtime")

    # THE THING THAT CAN ACT. Built with the confirmation broker attached, so a
    # refusal is a question rather than a dead end -- that is the owner's own
    # decision of 2026-08-31: stop, explain, ask by voice, and wait if nobody is
    # there. Without the broker it would still be safe and would simply say no,
    # which is safe in the way a system that cannot do anything is safe.
    jobs = BackgroundJobs(bus)
    # THE SPECIALISED AGENTS. The roster is a contract, so a missing or broken
    # one is a deployment fault rather than "no agents configured" -- recorded
    # and carried on from, because an unreadable roster must not stop VESPER
    # answering the owner.
    try:
        runner = AgentRunner(bus=bus)
    except AgentRosterError as exc:
        bus.publish("agent.roster_unreadable", subject="agents",
                    payload={"error": repr(exc)}, component="runtime")
        runner = None
    # THE ADVISOR, ON ITS OWN ACCOUNT, AND ONLY IF THAT ACCOUNT EXISTS.
    # `purpose="advisor"` routes to `claude-advisor`, which is bound to a
    # SECOND config dir -- so advice cannot consume the account the arbiter and
    # forgetter run on, and a spent advisor does not take them down with it.
    #
    # NO ROW, NO ADVISOR, AND THAT IS NOT A DEGRADED MODE. Until that directory
    # is authenticated the rung does not enrol and the act path is exactly what
    # it was: a missing reviewer never becomes a reason to be more permissive
    # than a system that never had one.
    advisor_profiles = measured_profiles(rows, purpose="advisor")
    advisor = (Advisor(gw, router=Router(bus, advisor_profiles), bus=bus)
               if advisor_profiles else None)
    actor = Actor(bus, gw, jobs=jobs, advisor=advisor, runner=runner,
                  broker=ConfirmationBroker(bus, InterruptionBudget(bus)))
    autonomy.attach_actor(actor)

    # THE STOP. `core/interlock.py` has been built, gated by A-031 and reachable
    # from nothing -- so VESPER could act and there was no stop to press. It is
    # a dead-man's switch rather than a kill signal, and A-031.2 gives the
    # reason: a kill signal fails OPEN. Cut the wire and the stop never
    # arrives; cut this one and the tokens stop arriving.
    #
    # WITH NO MINTER RUNNING, AUTONOMY IS OFF. That is the correct default and
    # not a degradation: `tools/ops/vesper_arm.py --install` is what turns it
    # on, and until somebody does that deliberately VESPER answers, observes
    # and records but does not act on its own.
    # THE FLOOR. `core/barge_in.py` classifies what the owner says during a
    # hold -- 242 phrases and a gate -- and was called by nothing;
    # `core/floor.py` is what makes its four outcomes differ in behaviour.
    # Neither is useful alone: an announcement with no way to respond to it
    # is a status line, and a classifier nothing feeds is a table.
    floor = FloorHolder(bus=bus)
    baseline = BaselineRecorder(store, clock,
                                on_error=lambda e: bus.publish(
                                    "baseline.write_failed", subject="baseline",
                                    payload={"error": repr(e)}, component="runtime"))
    interlock = SafetyInterlock(bus, now_ms=lambda: int(time.time() * 1000))
    autonomy.attach_interlock(interlock)

    # A ROTATED KEY THAT NEVER TOOK EFFECT IS SILENT, AND THIS IS THE ONLY
    # MOMENT IT IS CHEAP TO CATCH. The keychain overlays the file, so once a
    # credential has been migrated, editing it in `secrets.env` changes
    # nothing -- and pasting a new key into that file is exactly where a
    # rotation goes, because that is where credentials have always lived.
    # A disagreement between the two stores is the signature of that mistake.
    try:
        from routing.supply import credential_mismatches
        stale = credential_mismatches()
        if stale:
            bus.publish("credentials.stale_file_value", subject="startup",
                        payload={"variables": [m["name"] for m in stale],
                                 "detail": stale,
                                 "note": ("these were edited in secrets.env after "
                                          "being migrated to the keychain. The "
                                          "KEYCHAIN value is the one in use. Run "
                                          "tools/ops/vesper_keychain.py --migrate "
                                          "to make the file's value take effect.")},
                        component="runtime")
    except Exception as exc:                       # noqa: BLE001
        bus.publish("credentials.check_failed", subject="startup",
                    payload={"error": repr(exc)}, component="runtime")

    # WHAT VESPER DOES WHEN SOMETHING COMES DUE. Registered here rather than
    # beside its sensor, because the handler needs the voice and the voice is
    # built two hundred lines further down than the sensor registry is.
    #
    # THE TRIGGER SHIPPED WITHOUT THIS AND WAS CALLED "LANDED". It fired,
    # dispatched, hit `if not intent: continue`, and did nothing -- the sensing
    # half of the owner's loop with no acting half, which is the exact defect
    # this session spent its length finding elsewhere.
    #
    # THE MODEL PHRASES IT; IT DOES NOT DECIDE IT. What is due, and whether
    # anything is, was settled by the predicate and the ranking before this
    # runs -- no model touches the decision path (INV-AUTO-2). The model is
    # asked only to say a sentence well. So its failure is a DEGRADATION and
    # never a silence: `agenda.sentence()` is rendered first, the model is
    # offered the chance to improve it, and anything that goes wrong leaves the
    # deterministic line standing. The owner being told is the requirement; the
    # phrasing is the nicety.
    # ITS OWN BUDGET INSTANCE, NOT THE BROKER'S. The broker's allowance is for
    # questions it must ask to finish a turn; this is VESPER volunteering
    # something. Sharing one counter would let a busy afternoon of
    # confirmations silence the calendar, and vice versa.
    _interruptions = InterruptionBudget(bus)

    def _agenda_due_handler(*, period: str = "FREE_TIME",
                            attention_state: str = "UNKNOWN") -> dict:
        now_ms = int(time.time() * 1000)
        ag = agenda.build()
        due = ag.due_now(now_ms)
        if not due:
            # The predicate and the handler read the agenda at slightly
            # different instants. Nothing due by the time we got here is not a
            # failure, and announcing an empty list would be worse than quiet.
            return {"said": "", "note": "nothing due by the time it was read"}
        line = agenda.sentence(ag, now_ms)

        # MAY VESPER SPEAK RIGHT NOW? Asked BEFORE the model is called, so a
        # question nobody will hear does not cost a rung.
        #
        # WHY THIS EXISTS. `LEAD_S` is fifteen minutes, so this fires a quarter
        # hour before a calendar event -- right while the owner is up, and
        # wrong at three in the morning. Nothing else in this path knows what
        # hour it is: the ranking is about importance and time-until-due, not
        # about whether a person is available to be interrupted. That is what
        # `InterruptionBudget` is for, and it was built and reached by nothing
        # here.
        #
        # DECAYS = FALSE, so an item that cannot be surfaced now QUEUES rather
        # than being dropped: a meeting is worth the same when the owner wakes
        # up. `is_alarm` is deliberately NOT set -- an alarm bypasses the budget
        # entirely, and a calendar entry is not an alarm. The 09:00 alarm has
        # its own path and its own rung ladder.
        #
        # THE PERIOD AND ATTENTION ARE READ, NOT ASSUMED. `dispatch` hands them
        # down; its defaults are FREE_TIME and ABSENT, which is the fail-closed
        # pair -- budget 0, so an announcement waits until something establishes
        # that the owner is there. Defaulting to "available" here would be the
        # same declared-vs-measured error the yes-loop was.
        allowed = _interruptions.allocate(
            [Candidate(candidate_id="agenda", expected_value=0.8,
                       decays=False, interruption_cost=0.3)],
            period=period, attention_state=attention_state)
        if "agenda" not in allowed.surfaced:
            bus.publish("agenda.withheld", subject="agenda",
                        payload={"said": line,
                                 "due": [i.item_id for i in due],
                                 "period": period,
                                 "attention_state": attention_state,
                                 "note": ("the interruption budget for this "
                                          "period and attention state is spent "
                                          "or zero; the announcement is queued, "
                                          "not dropped")},
                        component="runtime")
            return {"said": "", "withheld": True}

        try:
            from core.intake import Utterance as _U
            prompt = (
                "Tell the owner what is due, in one short spoken sentence, in "
                "your own voice. Do not add anything that is not here. The "
                f"facts: {line}")
            spoken = answer(gw, router, persona,
                            _U(text=prompt, source="scheduled"),
                            renderer=renderer, updater=updater, misses=misses,
                            chooser=chooser)
            if spoken and spoken.strip():
                line = spoken.strip()
        except Exception as exc:                    # noqa: BLE001
            bus.publish("agenda.phrasing_failed", subject="agenda",
                        payload={"error": repr(exc), "fallback": line,
                                 "note": ("the deterministic line is spoken "
                                          "instead; the owner is still told")},
                        component="runtime")
        try:
            plan = speech.plan(line, privacy_class="private",
                               persons=(presence.persons()
                                        if presence is not None else ("owner",)))
            speech.speak(plan)
        except Exception as exc:                    # noqa: BLE001
            # Losing the audio is a degradation; the line still reaches the
            # surface through the record below and the pump's transcript.
            bus.publish("speech.failed", subject="agenda",
                        payload={"error": repr(exc)}, component="runtime")
        bus.publish("agenda.announced", subject="agenda",
                    payload={"said": line,
                             "due": [i.item_id for i in due],
                             "unavailable": dict(ag.unavailable)},
                    component="runtime")
        return {"said": line}

    autonomy.register(agenda.agenda_trigger(handler=_agenda_due_handler))

    # THE SERVED FACE (HOME-WORKBENCH §32): VESPER's face served to a display node
    # over the local network while VESPER runs, unless the owner turns it off.
    # Only the page, the face's cloud and what the face is doing cross the
    # network (core/face_surface.py). A port that cannot be bound is recorded and
    # changes nothing else about the runtime.
    try:
        from core import face_surface as _face_surface
        from core import preferences as _prefs_face
        if _prefs_face.read().get("face_surface.enabled", True):
            _face_server = _face_surface.start()
            bus.publish("face_surface.started", subject="face_surface",
                        payload={"port": _face_server.server_address[1],
                                 "face_bin": str(_face_surface.face_bin_path() or "")},
                        component="runtime")
    except Exception as exc:                              # noqa: BLE001
        bus.publish("face_surface.failed", subject="face_surface",
                    payload={"error": repr(exc)}, component="runtime")

    _menu_context.clear()
    _menu_context.update(devices=devices, actor=actor, autonomy=autonomy,
                         verifier=verifier, interlock=interlock, bench=bench)
    return (bus, gw, router, home, intake, triage, report, persona, bench,
            renderer, updater, misses, chooser, world, sensors, autonomy,
            devices, repairer, presence, context_cmds, verifier, speech,
            transcriber, actor, floor, baseline, interlock, jobs, store,
            changes, waiting)


def _render_mode_now(state: dict) -> str:
    """What mode vesper is in, for the turn that is about to answer for it.

    THE OWNER ASKED "hey there, what mode are you on?" AND WAS TOLD
    `idle -- present and awaiting commands`. Neither half is in this repository:
    the answerer invented the sentence and picked the name out of the list of
    modes that EXIST, which had been handed to it hours earlier so it would stop
    inventing mode names. Giving a model the legal answers without the actual one
    does not stop it guessing -- it tells it which guesses will look right.

    AND IT PICKED THE STAGE, WHICH IS THE PART WORTH SAYING OUT LOUD. `rest` mode
    is the pairing (stage `idle`, ambience `Rest`), so `idle` was not random: it
    is the other axis of the very mode the owner had set. HOME-ARCHITECTURE §6
    keeps those axes independent underneath, and the island had this exact
    confusion the other way round on 2026-09-09, showing the PERMISSION mode
    where vesper's own belonged. A reader who cannot tell the axes apart will
    answer with whichever one is nearer.

    PER TURN, NEVER IN THE SYSTEM POSITION. The capability statement is static so
    it stays the cached prefix; this changes whenever the owner changes it, and
    putting it there would cost a cache miss on every turn to say a sentence that
    is usually the same. It goes with the conversation, which is per-turn already.
    """
    mode = str((state or {}).get("mode") or "").strip()
    stage = str((state or {}).get("stage") or "").strip()
    ambience = str((state or {}).get("ambience") or "").strip()
    if not mode:
        # SAYING "NONE" IS THE POINT, not a reason to omit the block. An absent
        # block is what produced the invented answer; an explicit "no mode" is
        # the true one and it is not guessable.
        return ("No mode has been chosen yet. If the owner asks what mode you "
                "are on, say that plainly -- do not name one.")
    parts = [f"You are in {mode} mode right now."]
    if stage or ambience:
        parts.append(
            "A mode is a PAIR: "
            + " and ".join(x for x in
                           (f"the work you are set up for is {stage!r}" if stage else "",
                            f"the look is {ambience!r}" if ambience else "") if x)
            + ".")
    parts.append(f"If the owner asks what mode you are on, the answer is "
                 f"{mode!r} -- the mode's name, never the stage or the look.")
    return " ".join(parts)


def _render_conversation(recent: list) -> str:
    """The last few turns, BOTH SIDES, for the path that is not acting.

    NOT `intent._render_recent`, WHICH DROPS VESPER'S PROSE ON PURPOSE. That
    one feeds the proposer, whose job is to pick a capability, and its comment
    is right that the assistant's prose is the part most likely to talk it into
    re-proposing finished work. This one feeds the answerer, and here vesper's
    own last sentence IS the antecedent: "why is that?" refers to the reason
    vesper gave, and nothing else in the turn contains it.

    NOT THE WHOLE TRANSCRIPT EITHER -- `CONVERSATION_MAX` is 200 and this runs
    on rungs that fail on tokens per minute long before they fail on money.
    """
    lines = []
    for item in recent[-8:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        who = "you" if item.get("who") == "owner" else "vesper"
        # THE EXAMPLES ARE CLEANED, NOT ONLY THE OUTPUT, because this is where
        # the loop lived. A reply that leaked an internal name became the next
        # turn's example of how to answer, and the model copied it -- measured
        # three turns running on 2026-09-10, each one renewing the pattern for
        # the next. Cleaning only what vesper says now would leave every reply
        # already in the transcript teaching the old shape.
        lines.append(f"  {who}: {strip_internal_prefix(text)[:400]}")
    if not lines:
        return ""
    # AND THEY ARE THE PAST, NOT AN ANSWER TO REUSE.
    #
    # The comment above records the copying problem and the fix that was made
    # for it -- cleaning the TEXT of past replies so a leaked internal name
    # stopped teaching the next turn. It did not stop whole replies being
    # reused. Measured 2026-09-13: a sentence that exists nowhere in this
    # codebase came back five times across a dozen restarts and every code
    # change, because it was in the transcript and the answerer kept repeating
    # it as though it were this turn's result. The owner saw it and said so.
    #
    # SO THE BLOCK SAYS WHAT IT IS FOR. It resolves pronouns. It is not a source
    # of findings, and a past reply is not evidence about the present -- which
    # is the same rule this corpus applies to an instrument's self-report.
    return ("The conversation so far, most recent last. When the owner says "
            "\"that\", \"it\" or \"what you just said\", this is what they "
            "mean.\n"
            "THESE ARE PAST TURNS, NOT RESULTS. Never repeat an earlier reply "
            "as your answer to a new question, and never state something as "
            "having just happened because a past reply says it did -- report "
            "only what THIS turn found or did.\n"
            + "\n".join(lines))


def _what_was_tried(steps: list, final: str) -> str:
    """One sentence for a turn that took several goes at something.

    THE OWNER ASKED FOR DIAGNOSIS AND GOT IT, AND WAS TOLD ALMOST NONE OF IT.
    Measured 2026-09-13: asked to cat a file that does not exist, vesper tried
    `cat`, then `ls -l` the directory, then `find -name`, then `grep -R` -- four
    genuinely different approaches, exactly what was asked for -- and answered
    "it ran and came back with exit code 1, and said nothing on either output",
    because the reply is `did.said` and `did` is the LAST step. It did the work
    and reported the last line of it.

    WHAT THE OWNER NEEDS IS WHAT WAS TRIED AND WHAT STOPPED IT, which is also
    what lets them tell "it failed" from "it failed four different ways, so the
    thing genuinely is not there".

    THE COMMANDS THEMSELVES, ABBREVIATED, NEVER SUMMARISED BY A MODEL. A model
    paraphrase of what was run is a claim about the past that nothing checks --
    the same shape as the fabricated button names. These strings come from the
    step records.
    """
    # READ FROM `detail.result`, NOT FROM `args`. A step record carries
    # capability_id, detail, kind, level and said -- and NO args. The first
    # version of this read `st["args"]`, found nothing on every step, and
    # produced a summary naming nothing; it was written against the shape of a
    # PROPOSAL rather than the shape of a STEP, and the two differ.
    # DESCRIBE THE ACT, NEVER THE RESULT. The first version fell back to the
    # step's `said`, which is its OUTCOME sentence -- so a turn that listed
    # windows and then failed to read one reported "I tried 2 things: 27
    # window(s) open. None are mine, so I will not rearrange them on my o; that
    # did not go through: that window is not on the desktop that is sho." Two
    # results, stitched together and cut mid-word. The owner saw it and said so.
    #
    # A SHORT PHRASE PER CAPABILITY, and never a sentence from somewhere else.
    def _phrase(cid: str, res: dict) -> str:
        argv = res.get("argv")
        if cid == "shell.run" and isinstance(argv, list) and argv:
            return " ".join(str(a) for a in argv)
        if cid == "window.list":
            return "listed your windows"
        if cid == "ui.view":
            wid = res.get("window_id") or ""
            return f"looked inside window {wid}".strip()
        if cid == "ui.act":
            return f"tried to {res.get('action') or 'use'} an element"
        if cid in ("fs.read", "fs.write", "fs.edit") and res.get("path"):
            return f"{cid.split('.')[-1]} {res['path']}"
        if cid == "window.open":
            return "opened a window"
        if cid == "app.query":
            return f"asked the application ({res.get('verb') or 'something'})"
        return cid or "a step"

    def _clip(t: str, n: int = 58) -> str:
        """Cut at a word, never through one. Mid-word truncation looks broken."""
        t = " ".join(str(t).split())
        if len(t) <= n:
            return t
        cut = t[:n].rsplit(" ", 1)[0]
        return (cut or t[:n]) + "..."

    tried: list = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        cid = str(st.get("capability_id") or "")
        det = st.get("detail") if isinstance(st.get("detail"), dict) else {}
        res = det.get("result") if isinstance(det.get("result"), dict) else {}
        what = _phrase(cid, res)
        if what:
            tried.append(_clip(what))
    if len(tried) < 2:
        return final
    shown = "; ".join(tried[:4])
    more = f" (and {len(tried) - 4} more)" if len(tried) > 4 else ""
    # "I TRIED N THINGS", NOT "NONE OF THEM WORKED". Some steps in a failed
    # turn succeed -- a `find` that returns nothing exits 0 -- and claiming they
    # all failed is a small lie about the past in a sentence whose whole job is
    # to be accurate about it.
    return f"I tried {len(tried)} things: {shown}{more}. The last one: {final}"


def answer(gw, router, persona, utterance, renderer=None,
           updater=None, misses=None, chooser=None,
           context_cmds=None, can_do=None, recent=None, state=None,
           flags=None, acted_this_turn=None) -> str:
    """One request across the ladder. Difficulty routes it; the ladder serves it.

    `privacy_class` IS NOT PASSED, and that is the point of the default. Anything
    the owner types is theirs until something establishes otherwise, so it takes
    the gateway's strict default and reaches only E1_PRIVATE suppliers. A caller
    that wanted the public pool would have to say so, in writing, at the call.

    AND THAT DEFAULT NOW GOVERNS MORE THAN THE QUESTION. The composed persona
    carries whatever `voice.toml [owner]` holds, so the preamble is owner
    content and travels under the same strict class -- E1_PRIVATE rungs only,
    checked per provider at the choke point, before quota is even consulted.
    """
    task = utterance.hlc or "typed"
    # THROUGH THE CHOOSER, NOT classify() DIRECTLY. Same answer today -- with
    # no escalator it IS the deterministic classifier -- but the confidence
    # flag now reaches something that acts on it, and the raise-only rule sits
    # between a model's future opinion and the routed difficulty rather than
    # being added afterwards, when the call site would already look finished.
    if chooser is not None:
        choice = chooser.choose(utterance.text)
        kind = classify(utterance.text)
        difficulty = choice.difficulty
    else:
        kind = classify(utterance.text)
        difficulty = kind.difficulty
    try:
        # PREFER LATENCY, BECAUSE THE OWNER IS LOOKING AT THE SCREEN. That is
        # the whole justification and it is situational, which is why it is an
        # argument here and not a new default inside the router: a background
        # task at 3 a.m. should still rank on cost. `latency_budgets.toml` puts
        # `speech_end_to_response_onset` at 1200 ms, and this path was measured
        # at 25.9 s and 68.7 s on 2026-08-26 -- a 20-57x miss on a budget whose
        # `on_miss.prohibited` list starts with "relax budget_ms".
        decision = router.select(difficulty, prefer="latency", task_id=task)
    except NoRouteAvailable as e:
        return f"no route: {e}"

    # THE SITUATION IS DERIVED, NOT STORED (DR-028's third layer). `normal`
    # because a typed request with the owner waiting is exactly that; the alarm
    # path builds its own and does not come through here.
    situation = Situation(urgency="normal")

    # L1, IF MEMORY IS UP. Block A goes in the system position and is the cached
    # prefix -- it already CONTAINS the composed persona, which is what lifts
    # persona over the cache minimum it sits below on its own. Block B goes at
    # the end of the prompt, against the question, and nothing goes between.
    #
    # WITH NO MEMORY THIS IS THE BASELINE PATH, unchanged from what it was
    # before any of this existed, which is exactly what makes the two
    # comparable. `core/baseline.py` records that condition on purpose.
    if renderer is not None:
        rendered = renderer.render(utterance.text, situation=situation,
                                   control=context_cmds)
        system, request = rendered.system(), rendered.prompt()
        bus_payload = rendered.to_dict()
    else:
        system, _ = persona.compose(situation)
        request, bus_payload = utterance.text, None

    # WHAT VESPER CAN DO, AND WHAT IT JUST SAID. Neither reached here until
    # 2026-09-10, and the owner's transcript is what found it:
    #
    #   YOU     why is that?
    #   VESPER  Sir, could you clarify what "that" refers to?
    #   YOU     the shit you just said about windows
    #   VESPER  Sir, I can only display text in this console. I have no
    #           capability to spawn a separate terminal or manipulate GUI
    #           windows such as the Notes app.
    #
    # Two turns earlier `window.open` had run and reported a real failure with
    # a real reason. This path was handed `intake.history[-1]` and nothing
    # else, so "that" named nothing and the registry was absent -- and a model
    # with no registry answers from its priors, which is where "the Notes app"
    # came from. Nobody had mentioned Notes.
    #
    # TWELVE LINES ABOVE THE CALL SITE, the actor path already assembles
    # `recent` from the turns either side, with a comment explaining that "run
    # it" names nothing without them. THAT FIX WAS MADE FOR THE PROPOSER AND
    # NEVER FOR THE ANSWERER -- the same gap, one path over, for a fortnight.
    #
    # THE CAPABILITY STATEMENT GOES IN THE SYSTEM POSITION and the history does
    # not. The statement is static -- derived once from `intent.KNOWN` -- so it
    # stays part of the cached prefix; the history changes every turn and would
    # cost a cache miss on every turn if it went there.
    if can_do:
        system = f"{system}\n\n{can_do}" if system else can_do
    # BEFORE BLOCK B, NEVER BETWEEN IT AND THE QUESTION. `Rendered.prompt` is
    # documented as "Block B then the question, in that order and nothing
    # between them", so the conversation is prepended to the whole thing rather
    # than inserted into it.
    # WHAT IS ON THE FLAG BAR, READ AT THE TOP OF THE TURN.
    #
    # The owner, 2026-09-13: "vesper should look at the flag bar right on the
    # next working request, so after the first working request vesper checks
    # that quickly and sees if there is anything critical." Until this line,
    # NOTHING in a turn ever read the bar -- `carried_flags` was called once at
    # startup and never again. The surface whose whole job is to carry what went
    # wrong was written to by the executor and consulted by nobody who could act
    # on it, so vesper answered "checkpointed and queued" while the reason sat
    # on screen next to it.
    # WHAT VESPER DID THIS TURN, STATED, SO IT CANNOT INVENT ONE.
    #
    # Measured 2026-09-13: told "i am on the keyboard now" -- a statement asking
    # for nothing -- vesper replied "Opened System Settings as a new window.
    # Bring it to the current desktop, then I'll list the buttons." The intent
    # for that turn was `none`, no window was opened, and no System Settings
    # process existed. It invented an action, in the past tense, from earlier
    # conversation about that window.
    #
    # THIS IS THE FABRICATED BUTTON NAMES ONE STEP WORSE. A wrong name is a
    # wrong description of the world; a claimed ACTION is a wrong description of
    # what VESPER itself has done, and the owner has no way to check it short of
    # going to look. The answerer runs only when the actor took no action, so at
    # this point "nothing was done" is a FACT this code holds and never said.
    if acted_this_turn is None:
        request = ("YOU HAVE TAKEN NO ACTION THIS TURN. You have not opened, "
                   "run, written, changed, moved or created anything. Do not "
                   "say that you have. If the owner's words call for an action "
                   "you did not take, say what you would do and ask, or simply "
                   "answer them.\n\n") + request
    if flags:
        try:
            from core.intent import render_flags
            bar = render_flags(flags)
        except Exception:                              # noqa: BLE001
            # A TURN STILL ANSWERS WITHOUT THE BAR. Taking the reply down over
            # context about a past failure would be a worse failure than the one
            # it is describing.
            bar = ""
        if bar:
            request = bar + "\n\n" + request
    if recent:
        conversation = _render_conversation(recent)
        if conversation:
            request = conversation + "\n\n" + request
    # AND WHAT IS TRUE RIGHT NOW, nearest the question. The conversation says
    # what was said; this says what IS -- and without it the answerer had the
    # list of modes that exist and no idea which one it was in, so it named a
    # plausible one and wrote a description to match.
    if state:
        now = _render_mode_now(state)
        if now:
            request = now + "\n\n" + request

    t0 = time.perf_counter()
    try:
        # `prefer` IS PASSED TO BOTH LAYERS, and it has to be. The router picks
        # the profile and the gateway picks the rung inside it; setting it on
        # one leaves the other ranking on an axis unrelated to time, which just
        # moves the variance from between profiles to within one.
        # `expected_output_tokens` IS DECLARED, NOT DEFAULTED, and the default
        # was 1024 for every request including "hello". A free tier does not run
        # out of billing, it runs out of TOKENS PER MINUTE, and a live 429 on
        # 2026-08-26 read `Limit 8000, Used 5118, Requested 3155` for a turn
        # that came back twelve words long. The budget is not spent -- it is
        # withheld from the next request, which is why this looked free.
        out = gw.complete(request, task_id=task, system=system,
                          profile_id=decision.profile_id, prefer="latency",
                          expected_output_tokens=EXPECTED_OUTPUT[difficulty],
                          difficulty=difficulty)
    except AllProvidersExhausted:
        # NOT AN ERROR STRING. The narration layer has already spoken the real
        # sentence; this is what the transcript shows, and it says the true
        # thing: the task survives.
        return "every provider is spent — checkpointed and queued, nothing lost"
    finally:
        # OBSERVED WHETHER IT SUCCEEDED OR NOT, in a `finally`, because a rung
        # that took 40 s to fail is a slow rung and the next selection needs to
        # know. Recording only successes would let a supplier that times out
        # keep its enrolment-day estimate forever.
        router.observe(decision.profile_id, time.perf_counter() - t0)

    reply = ((out.get("result") or {}).get("text") or "").strip()

    # CAPTURE AFTER THE ANSWER, ON ITS OWN THREAD, AND NEVER IN THE WAY. The
    # turn must not wait on its own bookkeeping -- a turn that does is slower
    # than one with no memory at all -- and a capture that fails must not turn a
    # good answer into an error. `Updater.capture` already swallows and records
    # its own exceptions; the thread is what guarantees the owner never waits
    # for a disk write.
    #
    # KEYED ON THE HLC, because delivery is at-least-once and the same utterance
    # arriving twice must not become two facts. The HLC is the only identifier
    # that survives a redelivery.
    if updater is not None:
        threading.Thread(
            target=updater.capture, args=(utterance.text,),
            kwargs={"event_id": utterance.hlc or f"turn:{task}",
                    "source": utterance.source},
            daemon=True, name="updater-capture").start()

    # THE MISS RECORD, AND IT IS THE ONLY REASON ANY OF THIS CAN BE JUDGED.
    # A memory miss produces NO EVENT: no query returns empty, nothing raises,
    # VESPER simply does not know and answers anyway, fluently. It is catchable
    # only retrospectively, by pairing what VESPER did with what memory held --
    # and that pairing exists no other way.
    #
    # TWO DETECTORS RUN HERE AND NEITHER NEEDS A MODEL. Repetition asks whether
    # memory ALREADY held what the owner just said, which is a selection miss
    # rather than a capture miss and is a different defect. Explicit absence
    # reads VESPER's own reply for it saying it did not know -- the one miss
    # that announces itself.
    #
    # ALSO ON A THREAD, for the same reason the capture is: a turn must not wait
    # on its own bookkeeping, and this runs an FTS query.
    if misses is not None:
        def _record_miss():
            try:
                hit = misses.repetition(utterance.text)
                if hit:
                    misses.record(
                        detector=hit["detector"],
                        situation=f"owner restated something memory held: "
                                  f"{utterance.text[:120]}",
                        layer_consulted="L2 select, ceiling=private",
                        what_was_found={"fact_id": hit["held_fact_id"],
                                        "rank": hit["rank"]},
                        what_vesper_did=reply[:200])
                absent = misses.explicit_absence(reply)
                if absent:
                    misses.record(
                        detector=absent["detector"],
                        situation=utterance.text[:120],
                        layer_consulted="L2 select, ceiling=private",
                        what_was_found=None,
                        what_vesper_did=reply[:200])
            except Exception:                      # noqa: BLE001
                # The corpus is worth less if a miss recorder crash can take a
                # turn with it. Losing one record is survivable; losing the turn
                # is the failure this whole layer is forbidden to cause.
                pass
        threading.Thread(target=_record_miss, daemon=True,
                         name="miss-recorder").start()
    return reply


def _drain_heard(bus, transcriber) -> int:
    """Transcribe every clip the wake listener queued, into the ordinary input.

    OFFSET-TRACKED LIKE `say.jsonl`, for the same reason: the queue is appended
    by another process and read here, and re-reading it from the top would
    answer every clip again on every pass.

    A CLIP THAT WILL NOT TRANSCRIBE IS DROPPED AND SAID SO. Leaving it in the
    queue would retry it on every pass forever, spending a transcription each
    time on audio that has already failed.
    """
    if not HEARD.exists():
        return 0
    seen = _read_heard_offset()
    done = 0
    with HEARD.open("r", encoding="utf-8") as f:
        f.seek(seen)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                break                      # torn last line; see the say.jsonl note
            path = obj.get("audio") or ""
            if not path or not pathlib.Path(path).exists():
                continue
            heard = transcriber.transcribe(path)
            try:
                pathlib.Path(path).unlink()     # the audio is not kept
            except OSError:
                pass
            if not heard.ok or not heard.text.strip():
                bus.publish("wake.discarded", subject="wake",
                            payload={"reason": heard.reason or "empty",
                                     "note": "dropped rather than retried; a "
                                             "clip that failed once will fail "
                                             "again and cost a transcription "
                                             "every pass"},
                            component="runtime")
                continue
            with OUTBOX.open("a", encoding="utf-8") as out:
                out.write(json.dumps({"text": heard.text, "source": "spoken",
                                      "final": True,
                                      "confidence": heard.confidence,
                                      "instrument": "transcriber"},
                                     ensure_ascii=False) + "\n")
            bus.publish("wake.heard", subject="wake",
                        payload={"confidence": heard.confidence,
                                 "language": heard.language,
                                 "chars": len(heard.text)},
                        component="runtime")
            done += 1
        seen = f.tell()
    # ATOMIC, because a kill between truncate and write leaves an EMPTY file
    # and the reader used to raise on it forever. Measured 2026-09-09: the pump
    # died with `ValueError: invalid literal for int() with base 10: ''` on
    # every tick, so nothing the owner typed was processed, the cards stopped
    # updating and every model row read UNAVAILABLE -- from a zero-byte file.
    _tmp = HEARD_OFFSET.with_name(
        f"heard.offset.{os.getpid()}.{threading.get_ident()}.tmp")
    _tmp.write_text(str(seen), encoding="utf-8")
    _tmp.replace(HEARD_OFFSET)
    return done


def _drain_control(bus, home, *, path=None, offset_path=None, outbox=None,
                   preferences_path=None, actor=None) -> int:
    """Apply every control the home posted since the last pass.

    OWNER, 2026-09-13: every surface showed readings and managed nothing. This
    is the runtime's half of the management channel: the Swift host appends
    `{action, args}` lines as the owner presses things, and each is applied by
    `core/controls.py` -- a preference written, a governed change recorded for
    the host to confirm, or an act queued through the ordinary typed path.

    OFFSET-TRACKED LIKE `heard.jsonl`, and the offset file's temp name is unique
    per writer for the reason `island.err` recorded sixteen times tonight. After
    a preference changes the settings rows are re-read at once, so the screen
    the owner is looking at shows the value they just set rather than the one
    from the last ten-minute refresh.
    """
    from core import controls as C
    p = pathlib.Path(path) if path else CONTROL
    op = pathlib.Path(offset_path) if offset_path else CONTROL_OFFSET
    if not p.exists():
        return 0
    try:
        seen = int(op.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        seen = 0
    done = 0
    changed_pref = False
    with p.open("r", encoding="utf-8") as f:
        f.seek(seen)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                break                      # torn last line; see the say.jsonl note
            res = C.apply(obj, ctx={"bus": bus, "outbox": outbox or OUTBOX,
                                    "preferences_path": preferences_path,
                                    # THE ACTOR, so a workflow's experiment runs
                                    # through the same door a typed sentence does.
                                    "actor": actor})
            bus.publish("control.applied" if res.get("ok") else "control.refused",
                        subject=str(obj.get("action") or "?"),
                        payload={**res, "args": obj.get("args"),
                                 "at_ms": obj.get("at_ms")},
                        component="runtime")
            if res.get("ok") and res.get("kind") in (C.PREFERENCE, C.PERMISSION, C.HOST, C.EXPORT, C.BOARD):
                changed_pref = True
            done += 1
        seen = f.tell()
    _tmp = op.with_name(f"{op.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    _tmp.write_text(str(seen), encoding="utf-8")
    _tmp.replace(op)
    if changed_pref and home is not None:
        try:
            home.refresh_settings()
            home.write()
        except Exception as _exc:                          # noqa: BLE001
            bus.publish("control.refresh_failed", subject="settings",
                        payload={"error": repr(_exc)}, component="runtime")
    return done


# WHICH AMBIENCE CONDITIONS THIS PROCESS HAS FLAGGED. Kept here rather than in
# `home.json` because it answers a question about THIS run: the flags list is
# rebuilt empty at startup, so a stale id could not survive a restart anyway,
# and reading the file back to find out what to retract would make the drain
# depend on the surface it writes to.
_AMBIENCE_FLAGGED: set = set()


def _drain_ambience(bus) -> int:
    """Turn the home's report of a mode that did not land into a flag.

    ONE CONDITION PER AMBIENCE, AND A SUCCESS RETIRES ALL OF THEM. The owner has
    exactly one ambience at a time, so asking for `Focus` and getting it means
    the earlier complaint about `Working` is over -- they are not waiting for
    `Working` any more. Retracting only the id that just succeeded would leave a
    flag about a mode nobody is asking for, which is the "a bar that shows
    resolved problems teaches the owner to stop reading it" failure.

    A LINE WITH NO REASON STILL RAISES. The home records the sentence at the
    moment of failure; if that sentence is missing the mode still did not land,
    and saying so without the reason beats saying nothing.
    """
    if not AMBIENCE.exists():
        return 0
    try:
        seen = int((AMBIENCE_OFFSET.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        # ZERO IS THE SAFE ANSWER, for the reason `_read_heard_offset` gives at
        # length: re-reading a line already seen re-raises or re-clears the same
        # condition, which `raise_flag` and `clear_flag` both collapse, while
        # skipping ahead loses a failure the owner is waiting to be told about.
        seen = 0
    done = 0
    with AMBIENCE.open("r", encoding="utf-8") as f:
        f.seek(seen)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(row.get("ambience") or "").strip()
            if not name:
                continue
            fid = f"mode.ambience:{name}"
            if row.get("ok"):
                for stale in sorted(_AMBIENCE_FLAGGED | {fid}):
                    bus.publish("flag.cleared", subject="home",
                                payload={"id": stale,
                                         "capability_id": "mode.set"},
                                component="runtime")
                _AMBIENCE_FLAGGED.clear()
            else:
                _AMBIENCE_FLAGGED.add(fid)
                bus.publish("flag.raised", subject="home",
                            payload={"id": fid, "capability_id": "mode.set",
                                     "text": (str(row.get("reason") or "").strip()
                                              or f"vesper could not switch to "
                                                 f"{name} and did not say why")},
                            component="runtime")
            done += 1
        seen = f.tell()
    _tmp = AMBIENCE_OFFSET.with_name(
        f"ambience.offset.{os.getpid()}.{threading.get_ident()}.tmp")
    _tmp.write_text(str(seen), encoding="utf-8")
    _tmp.replace(AMBIENCE_OFFSET)
    return done


# How much of the conversation the surface carries forward. The owner asked for
# no visible sessions -- "at least the whole week" -- and a restart used to open
# on an empty transcript, which is why starting VESPER felt like meeting a
# stranger who had your history filed somewhere else.
CONVERSATION_DAYS = 7
CONVERSATION_MAX = 200


def _recent_conversation(store, *, days: int = CONVERSATION_DAYS,
                         limit: int = CONVERSATION_MAX) -> list:
    """The last week of turns, rebuilt from the log, newest last.

    THE LOG ALREADY HELD ALL OF IT. `turn` records carry `question` and
    `answer` for every dispatched turn, so the conversation was durable the
    whole time -- it simply was not read back, and the in-memory list started
    empty on every launch. Restoring it is a read, not a new store: there is
    one record of what was said and this is a view of it.

    NEVER RAISES INTO STARTUP. A surface that opens without its history is a
    worse morning than one that opens without a face; a runtime that refuses to
    start because it could not read the history is worse than both.
    """
    out: list = []
    try:
        cutoff_ms = (time.time() - days * 86400) * 1000.0
        for rec in store.read("log", kind="turn"):
            body = rec.body if isinstance(rec.body, dict) else {}
            p = body.get("payload") or body
            q, a = str(p.get("question") or ""), str(p.get("answer") or "")
            at = rec.hlc.physical_ms if getattr(rec, "hlc", None) else None
            if at is not None and at < cutoff_ms:
                continue
            if q:
                out.append({"who": "owner", "source": "typed",
                            "certain": True, "text": q})
            if a:
                out.append({"who": "vesper", "source": "vesper",
                            "certain": True, "text": a})
    except Exception:                                  # noqa: BLE001
        return []
    return out[-limit:]


def pump(bus, gw, router, persona, bench, home, intake, transcript: list,
         changes=None,
         once: bool = False, renderer=None, updater=None,
         misses=None, chooser=None, sensors=None, autonomy=None,
         triage=None, repairer=None, presence=None,
         context_cmds=None, speech=None, transcriber=None, actor=None,
         floor=None, baseline=None, interlock=None, jobs=None,
         store=None, waiting=None) -> int:
    """Read new lines, answer them, publish the transcript. Offset-tracked."""
    # ANYTHING THE OWNER HAS NOW DONE, PICKED UP WITHOUT BEING TOLD.
    #
    # The owner, 2026-09-13: "the time i do it, it should keep going, not wait
    # for me to respond or tell it i did it... i should never tell it i did it,
    # only i do it, and it keeps going."
    #
    # RE-ASKED THROUGH THE ORDINARY PATH rather than resumed mid-turn: the
    # request goes back on the queue exactly as the owner first said it, so it
    # runs through intent, authorization, the ladder and the flag bar like any
    # other. A resume that skipped those would be a second path into acting,
    # which INV-AUTH-1 refuses.
    if waiting is not None:
        try:
            for _item in waiting.ready():
                _txt = str((_item.get("payload") or {}).get("text") or "")
                if not _txt:
                    continue
                # OUTBOX, not SAY. `the-runtime-resolves-every-name-it-uses`
                # caught this before it ever ran: a NameError inside the
                # broad except below would have left the watcher silently
                # dead while reporting a handled failure.
                with OUTBOX.open("a", encoding="utf-8") as _fh:
                    _fh.write(json.dumps(
                        {"text": _txt, "source": "typed",
                         # MARKED, SO IT CANNOT PARK AGAIN. Without this, a
                         # request that still fails the same way would re-park
                         # and re-inject forever -- a loop the owner would
                         # experience as vesper talking to itself.
                         "resumed": True,
                         "at_ms": int(time.time() * 1000)}) + "\n")
                bus.publish("act.resumed_by_condition", subject=str(_item.get("key")),
                            payload={"condition": _item.get("condition"),
                                     "args": _item.get("args")},
                            component="runtime")
            for _item in waiting.expired():
                bus.publish("act.wait_expired", subject=str(_item.get("key")),
                            payload={"condition": _item.get("condition"),
                                     "note": ("waited and the world did not "
                                              "change; dropped rather than "
                                              "left silent")},
                            component="runtime")
        except Exception as _exc:                      # noqa: BLE001
            # A WATCHER THAT FAILS MUST NOT STOP THE PUMP. Answering is the job.
            bus.publish("act.wait_failed", subject="waiting",
                        payload={"error": repr(_exc)}, component="runtime")
    # The last thing VESPER actually did, so the next turn's "it" resolves.
    last_action = None
    # WHEN THE OWNER WAS LAST DEMONSTRABLY HERE. Survives across pump
    # iterations, unlike the per-turn reading the yes-loop takes, because
    # the autonomy dispatch happens at the TOP of an iteration -- before
    # anything the owner might say in it. Starts at 0, which is "never
    # observed" and reads as UNKNOWN, so a fresh runtime volunteers
    # nothing until the owner speaks to it once.
    _last_owner_s = 0.0
    # SENSORS FIRST, AND THE PERIOD DECIDES WHETHER ANYTHING ACTUALLY RUNS.
    # `poll()` returns immediately for any sensor that is not due, so calling it
    # every pass costs a dictionary lookup rather than a probe. Before the turn,
    # because a predicate that fires during this pass should read the world as
    # it is now and not as it was one pass ago.
    #
    # NEVER FAILS THE PUMP. Sensor failures are already UNKNOWN-and-logged
    # inside the registry; this catch is for the registry itself going wrong,
    # and the rule is the same one the updater follows -- bookkeeping may not
    # take a turn with it.
    if sensors is not None:
        try:
            sensors.poll()
        except Exception as exc:                   # noqa: BLE001
            bus.publish("sensors.loop_failed", subject="sensors",
                        payload={"error": repr(exc)}, component="runtime")
    # AFTER THE SENSORS, because a predicate should read the world as it is now
    # and not as it was one pass ago. Same rule as the sensors above: a failure
    # here is recorded and does not take the turn with it.
    if autonomy is not None:
        try:
            # DECIDE, THEN ACT ON WHAT WAS DECIDED. Two calls rather than one
            # because `tick` must hold no reference to the actor: that is what
            # keeps "no model in the decision path" structural.
            # PRESENT WHATEVER THE MINTER LEFT, BEFORE DECIDING. A token
            # already seen is refused by token_id, so this is idempotent and a
            # captured token cannot extend autonomy twice.
            # A PARAMETER, AND IT WAS A NAME FROM ANOTHER FUNCTION. `interlock`
            # is built in `build()` and this line lives in `pump()`, so it
            # resolved to nothing: every pass raised NameError, the broad
            # `except Exception` below caught it and published
            # `autonomy.loop_failed`, and the autonomy loop never ticked at all.
            # Nothing looked broken -- the failure had a name, a record and a
            # handler -- and the arming path for the emergency stop was
            # unreachable the whole time. The stop landed today and the runtime
            # has not been started since, which is the only reason the log
            # holds zero of those records.
            if interlock is not None:
                _present_enable_token(interlock)
                # THE STOP REACHES WORK THAT OUTLIVES THE TURN. A background
                # command has no step boundary to ask at, so the question is
                # asked HERE instead, on the pass that already consults the
                # interlock. `INV-STOP-2` forbids the interlock from holding
                # the process table itself -- a dead-man's switch may not
                # depend on anything that can hang -- so the side that holds
                # the processes does the killing.
                #
                # `free_time` ONLY. STOP_AUTONOMY stops what VESPER started for
                # itself; a build the owner asked for is not autonomous work,
                # and an owner who loses it will not use the stop again.
                if jobs is not None and not interlock.autonomy_permitted():
                    jobs.terminate_all(period="free_time",
                                       reason="autonomy_not_permitted")
            # PACED BY THE LOOP'S OWN DECLARED CADENCE, not by the pump's.
            # POLL_SECONDS is 0.15 because the SPEECH path needs it -- the
            # comment at the sleep says so -- and autonomy was hitched to the
            # same pass, so it ran 6.7x faster than the `tick_interval_s = 1.0`
            # it declares. Measured on the live log: a 163 ms median gap
            # between heartbeats, 625,172 of them in 41.8 hours, 208 MB/day.
            #
            # The fastest thing any trigger can do is 300 s away (the shortest
            # debounce in core/self_directed.py), so a 1 s cadence is still 300
            # passes ahead of anything that could act on it. This is the same
            # treatment SensorRegistry already gives its sensors, which run at
            # 60-300 s inside this very pump.
            #
            # `_present_enable_token` stays on the FAST pass deliberately: it
            # is the stop path, and A-031.1 declares a 2 s T_new_action budget.
            # Presenting a token is not deciding anything.
            if autonomy.due():
                # DECIDE, THEN ACT ON WHAT WAS DECIDED. Two calls rather than
                # one because `tick` must hold no reference to the actor: that
                # is what keeps "no model in the decision path" structural.
                # THE RETURN VALUE WAS DISCARDED, so anything autonomy did
                # was audible and invisible: spoken aloud, absent from the
                # surface the owner is looking at.
                # WHEN IT IS, MEASURED. `dispatch`'s own defaults are
                # FREE_TIME and UNKNOWN -- budget zero, so a volunteered
                # announcement waits rather than speaking into an empty room.
                # The pump is the one place that knows better: an owner
                # utterance was dispatched here, milliseconds ago. Same
                # measurement the yes-loop uses, same decay back to UNKNOWN
                # when the pump falls behind, and for the same reason --
                # defaulting to "available" would turn "I do not know if you
                # are there" into "speak now".
                _auto_attention = (
                    "available"
                    if (time.time() - _last_owner_s) <= PRESENCE_FRESH_S
                    else "UNKNOWN")
                for _rec in (autonomy.dispatch(
                        autonomy.tick(),
                        period=(ACTIVE_SESSION if _auto_attention == "available"
                                else "FREE_TIME"),
                        attention_state=_auto_attention) or []):
                    _said = ((_rec.get("result") or {}).get("said") or "").strip()
                    if _said:
                        transcript.append({"who": "vesper", "source": "vesper",
                                           "certain": True, "text": _said})
                        home.set_transcript(list(transcript))
        except Exception as exc:                   # noqa: BLE001
            bus.publish("autonomy.loop_failed", subject="autonomy",
                        payload={"error": repr(exc)}, component="runtime")

    # THE LIVE LOG IS BOUNDED, ON A SLOW CLOCK. Rotation keeps the old segment
    # whole and continues the sequence, so nothing is lost and nothing is
    # rewritten -- which is the only archival form the append-only triggers
    # permit. The check is throttled because the answer changes over weeks.
    #
    # PUBLISHED WHEN IT HAPPENS. A file the owner has been watching grow
    # suddenly being small is a surprise unless the system says what it did.
    if store is not None:
        now_s = time.time()
        if now_s - _LAST_ROTATE_CHECK[0] >= ROTATE_CHECK_EVERY_S:
            _LAST_ROTATE_CHECK[0] = now_s
            try:
                live = store.root / "log.db"
                if live.exists() and live.stat().st_size > ROTATE_LOG_ABOVE_BYTES:
                    was = live.stat().st_size
                    info = store.rotate("log")
                    bus.publish("store.rotated", subject="log",
                                payload={**info, "was_bytes": was,
                                         "threshold_bytes": ROTATE_LOG_ABOVE_BYTES},
                                component="runtime")
            except Exception as exc:                   # noqa: BLE001
                bus.publish("store.rotate_failed", subject="log",
                            payload={"error": repr(exc)}, component="runtime")

    # ONE REPAIR ATTEMPT PER PASS, OLDEST FIRST, AND NEVER A SWEEP. Repairing
    # everything open on every pass would retry a dead provider several times a
    # second -- which is not repair, it is the failure again at a higher rate,
    # and it is what the module's own header calls theatre. One item per pass
    # means a queue of ten drains over ten passes and a permanently broken rung
    # is retried at the pump's cadence rather than in a loop.
    if repairer is not None and triage is not None:
        try:
            # GRADE BEFORE REPAIRING, because `grade_all()` was called by
            # NOTHING and an ungraded item is one the repairer correctly
            # refuses: "only a failure that is down AND will stay down is
            # repaired unattended". Triage collected failures, repair declined
            # every one of them for want of a grade, and the step between them
            # existed and was reached by neither side.
            #
            # Its docstring says "called when a rung reports healthy", which is
            # the cheaper trigger; the pump is the honest one until a rung
            # actually reports.
            triage.grade_all()
            # ASK ONLY FOR WHAT THE REPAIRER WILL ACT ON. `repair()` refuses
            # anything that is not CRITICAL_NOW -- "CAN_WAIT and NO_FIX_NEEDED
            # are reports, not work" -- and `open_items()` was being called
            # with no grade, so the first item in the queue was handed over and
            # declined on EVERY pump pass, publishing a durable
            # `repair.attempted` each time.
            #
            # Measured 2026-09-01 from the event log: 610,931 attempts over 41
            # hours, ~15,000/hour, every one of them the same item
            # (`claude-sub::unknown::server_error`) with the same answer. That
            # is most of a 1.6 GB log, and it is a decision that could never
            # change being re-taken a quarter of a million times a day.
            #
            # A decline is not an attempt. The filter already existed on
            # `open_items`; nothing was passing it.
            # AND PUBLISHED ON CHANGE, NOT ON PASS. The filter above fixed
            # half of it: a DECLINED item is no longer attempted. What it did
            # not fix is an item that IS critical, is attempted, and comes back
            # with the same answer every time.
            #
            # Measured 2026-09-05, after that fix: 6,884 events in ten minutes
            # -- ~11 a second -- every one of them
            # `claude-advisor::unknown::bad_request`, every one `tier2_proposed`
            # with `fixed: false`. Tier 2 means VESPER'S OWN DEFECT, and the
            # tier's whole rule is that the runtime proposes a patch and may
            # never apply it to itself. So this outcome CANNOT change by being
            # re-taken; the loop was re-deriving an unchangeable answer eleven
            # times a second and writing each one to an append-only store.
            #
            # THE SHAPE IS BORROWED FROM `autonomy.noop`, which solved exactly
            # this: publish when the ANSWER changes, plus a keepalive so a long
            # silence is distinguishable from a dead repairer. The record then
            # says "this has held since pass N" instead of repeating itself,
            # and a reader can still reconstruct any pass in between.
            for item in (triage.open_items(CRITICAL_NOW) or [])[:1]:
                # THE GATE IS ON THE CALL, NOT ON THE PUBLISH, and the first
                # version of this fix got that wrong. `Repairer.repair` publishes
                # `repair.attempted` ITSELF (core/repair.py), so gating only the
                # runtime's own publish silenced the duplicate and left the
                # original firing on every pass -- measured 401 events in 90
                # seconds after the "fix", every one with `reason: None`, which
                # is precisely how you tell them apart. Two emitters, one gated.
                #
                # SO NOTHING IS RE-DERIVED AT ALL WHEN NOTHING CAN HAVE CHANGED.
                # The verdict is a function of the item, so the item is the key:
                # its id, how many attempts it carries, and its grade. Any of
                # those moving is real news and runs the repairer again;
                # otherwise the pass costs nothing, which is also the honest
                # answer, because tier 2 means VESPER may never apply the fix to
                # itself and the answer cannot change by being asked twice.
                sig = (item.item_id, len(item.attempts or ()), item.grade)
                now_s = time.time()
                prev = _repair_state.get(item.item_id)
                changed = prev is None or prev[0] != sig
                stale = (not changed
                         and (now_s - prev[1]) >= REPAIR_KEEPALIVE_S)
                if not (changed or stale):
                    continue
                _repair_state[item.item_id] = (sig, now_s)
                out = repairer.repair(item)
                bus.publish("repair.attempted", subject=item.provider_id,
                            payload={**out.to_dict(),
                                     "unchanged_for_s": (0 if changed
                                                         else int(now_s - prev[1])),
                                     "reason": ("changed" if changed
                                                else "keepalive")},
                            component="runtime")
                # AND THE OWNER IS TOLD, ON THE TWO SURFACES THEY NAMED.
                #
                # Their rule, in their words: "explanation goes in the
                # explanation card, asking for permission and raising the issue
                # goes to vesper's talk, and the card where vesper's talking
                # goes". Until now a repair produced a bus event and nothing
                # else -- the owner learned about a dead rung by noticing that
                # answers had gone strange.
                #
                # ONLY ON A CHANGE, never on the keepalive. The gate above
                # re-runs a repair every half hour so a stale item does not go
                # quiet; re-announcing the same finding on that clock would be
                # VESPER telling the owner the same thing forever.
                if changed:
                    _surface_repair(bench, transcript, home, item, out)
        except Exception as exc:                   # noqa: BLE001
            bus.publish("repair.pass_failed", subject="repair",
                        payload={"error": repr(exc)}, component="runtime")
    # DRAIN WHAT THE WAKE LISTENER CAPTURED, before reading the input file --
    # so a clip captured this pass is answered this pass rather than next.
    if transcriber is not None:
        _drain_heard(bus, transcriber)
    # THE BUTTONS AND THE CARDS DO NOT DEPEND ON HEARING (2026-09-14). The control
    # drain and the surface refresh sat inside the transcriber's branch above, so
    # a VESPER without speech would apply no button the owner pressed and refresh
    # no card -- management gated on a microphone permission it has nothing to
    # do with.
    try:
        _drain_control(bus, home, actor=actor)
    except Exception as _exc:                              # noqa: BLE001
        # A CONTROL THAT FAILS MUST NOT STOP THE PUMP. Answering is the job.
        bus.publish("control.drain_failed", subject="control",
                    payload={"error": repr(_exc)}, component="runtime")
    # THE MANAGEMENT SURFACES RE-READ EVERY 30 s. Until 2026-09-14 the
    # settings rows and the menu cards were built once at startup and again
    # only after a control landed, so a card showed the arm agent's pid from
    # before the last build for as long as nobody pressed anything. Thirty
    # seconds is the most a person waits after doing something outside VESPER
    # (granting a permission, stopping an agent) before looking at the card.
    # `time.monotonic()`: an elapsed interval, which INV-COORD-4 permits.
    global _LAST_SURFACE_REFRESH
    _now_m = time.monotonic()
    if _now_m - _LAST_SURFACE_REFRESH >= 30.0:
        _LAST_SURFACE_REFRESH = _now_m
        try:
            home.refresh_settings()
        except Exception as _exc:                          # noqa: BLE001
            bus.publish("surface.refresh_failed", subject="settings",
                        payload={"error": repr(_exc)}, component="runtime")
    # AND HOW THE LAST MODE WENT. Read every pass, because the failure it
    # reports is one the owner is looking at right now -- their own Desktop
    # showing while they wait for vesper's picture to change.
    _drain_ambience(bus)

    OUTBOX.touch(exist_ok=True)
    seen = int(OFFSET.read_text()) if OFFSET.exists() else 0
    handled = 0
    said: list = []
    with OUTBOX.open("r", encoding="utf-8") as f:
        f.seek(seen)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # A TORN LAST LINE IS NOT A CORRUPT FILE. Swift appends without
                # locking, so a read can catch a half-written line; skipping it
                # and not advancing past it means the next pass sees it whole.
                break
            text = (obj.get("text") or "").strip()
            if not text:
                continue
            # A LINE THAT IS ITSELF A RESUME MAY NOT PARK AGAIN. The watcher
            # re-injects the owner's original words when the world satisfies a
            # condition; if that attempt still fails the same way, parking it a
            # second time would re-inject forever.
            _is_resumed = bool(obj.get("resumed"))
            # SPOKEN AND TYPED TAKE DIFFERENT DOORS, and `Intake` has had both
            # since it was written -- `spoken()` exists precisely so that voice
            # arriving later is a SOURCE and not a rewrite. Until now nothing
            # called it.
            #
            # THE DIFFERENCE IS NOT THE DEVICE. A typed utterance is certain and
            # complete the moment the owner presses return. A spoken one arrives
            # in fragments, each revising the last, every word carrying a
            # confidence that may be low. `spoken()` buffers the partials and
            # gates the finals; routing voice through `typed()` would assert
            # certainty the recogniser never claimed, and a 61%-sure "delete the
            # archive" would execute instead of being reflected back.
            # OFFERED EVERY UTTERANCE, and it returns None for all but a
            # declaration -- so this costs one phrase-list match and never
            # branches the turn. The sentence still goes on to Intake: telling
            # VESPER someone is present is also a thing VESPER should hear.
            # WORK IS ALREADY IN FLIGHT THIS PASS, so this line is not a new
            # turn -- it is an interruption of the one before it. `core/
            # barge_in.py` classifies these, has 242 phrases and a gate, and
            # was called by NOTHING; `core/floor.py` is what makes the four
            # outcomes differ in BEHAVIOUR rather than in name.
            #
            # SWALLOW IS THE ONE MOST LIKELY TO BE GOT WRONG, because answering
            # is polite. "Take your time" met with "certainly, I'll continue"
            # is VESPER interrupting the owner's permission not to be
            # interrupted -- so a swallow says nothing at all.
            # `holding` IS A PROPERTY, NOT A METHOD, and `Verdict` carries
            # `floor` plus three behaviour flags rather than an `outcome`
            # string. Both were got wrong first and would have raised on the
            # first spoken interruption -- a path no test exercised, because
            # nothing had ever called this module.
            if floor is not None and floor.holding:
                verdict = floor.offer(text)
                if verdict.answer:
                    # STATUS: a liveness check. Answer it, cancel nothing.
                    said.append({"who": "vesper", "text": floor.status_line(),
                                 "source": "vesper", "certain": True})
                    transcript.extend(said)
                    del transcript[:-CONVERSATION_MAX]
                    said = []
                    home.set_transcript(list(transcript))
                    continue
                if verdict.queued:
                    continue     # held; put back on release
                if not verdict.acted:
                    continue     # SWALLOW: cooperative, and silence IS the reply
                # BREAK: the owner took the floor, so this line becomes the
                # turn. `offer` has already dropped the hold.

            if presence is not None:
                presence.offer(text)
            if context_cmds is not None:
                context_cmds.offer(text)
            if obj.get("source") == "spoken":
                res = intake.spoken(
                    text,
                    confidence=float(obj.get("confidence") or 0.0),
                    final=bool(obj.get("final", True)),
                    # WHICH INSTRUMENT MEASURED IT. Apple's recogniser and the
                    # transcriber report confidence on different scales, so the
                    # floor is chosen by who produced the number. An utterance
                    # that does not say is judged against the stricter default.
                    meta={"instrument": obj.get("instrument")}
                    if obj.get("instrument") else None)
                if res["outcome"] in ("buffered", "reflected", "ignored"):
                    # NOT DISPATCHED, AND THE OWNER STILL SEES IT. A partial is
                    # the recogniser thinking out loud; a reflected utterance is
                    # heard-but-not-acted-on. Both belong on the stage, and
                    # neither may reach the gateway.
                    home.set_partial(text) if hasattr(home, "set_partial") else None
                    continue
            else:
                res = intake.typed(text)
            said.append({"who": "owner", "text": text,
                         "source": res["utterance"]["source"],
                         "certain": res["utterance"]["certain"]})
            # SHOW THE OWNER THEIR OWN WORDS BEFORE ANSWERING, and this is not
            # a nicety. The transcript was written ONCE at the end of the pass,
            # so the owner's line was appended and immediately superseded by
            # the reply -- it never appeared on the stage at all. What the
            # owner saw was: the field clears, nothing, nothing, an answer.
            #
            # And the wait is real: measured 30 s on this exchange, and one
            # supplier in the table answers at 5 tok/s. Half a minute of no
            # feedback is indistinguishable from a system that did not hear.
            # Publishing here means the words land, the face turns to thinking,
            # and the dissolve happens when the answer actually arrives.
            transcript.extend(said)
            del transcript[:-CONVERSATION_MAX]
            said = []
            home.set_transcript(list(transcript))
            if res["outcome"] == "dispatched" and floor is not None:
                # HELD FOR THE REST OF THIS PASS. The pump answers
                # synchronously, so the window in which the owner can interrupt
                # is the rest of the batch: they said two things quickly, and
                # the second is a response to the first being worked on rather
                # than a new request. A fully concurrent hold needs a
                # non-blocking answer, which this pump does not have -- and
                # saying so is better than pretending the window is wider.
                floor.hold("answering")

            if res["outcome"] == "dispatched":
                # ACTING IS TRIED FIRST, AND IT USUALLY DECLINES. Almost every
                # turn is a question, a greeting, or something to remember, and
                # `maybe_act` returns None for all of them -- so the normal path
                # costs one extra call on the fastest rung and the answer below
                # runs exactly as it did before.
                #
                # WHEN IT DOES ACT, THE RESULT IS THE ANSWER. Asking the model
                # to also narrate a command it did not run would put a fluent
                # description of an imagined outcome beside the real one, which
                # is the competition INV-VERIF-1 exists to forbid: the actor's
                # story standing in for what happened.
                # IS THIS AN ANSWER TO A QUESTION VESPER IS ASKING? Checked
                # BEFORE the utterance becomes new work, because it is not new
                # work -- and checked deterministically, never by a model:
                # `core/consent.py` opens with the reason, which is that a
                # model deciding whether the owner agreed is a model that can
                # be talked into agreeing on their behalf.
                #
                # ANYTHING NOT RECOGNISED RE-QUEUES THE QUESTION rather than
                # settling it. The owner adding a task, changing the subject or
                # asking what the action would actually do are all "not an
                # answer", and all of them mean the question is no longer the
                # thing in front of them: it goes back to the queue and must be
                # ASKED AGAIN before a bare yes can settle it. Silence is not
                # consent and neither is having been nearby.
                did = None
                spoken = intake.history[-1].text
                # THE OWNER IS HERE, AND UNTIL NOW NOTHING SAID SO.
                #
                # `world.owner.attention_state` has no producer -- `core/
                # confirm.py` says so in its own docstring -- so every call
                # into the actor carried the default UNKNOWN. An unknown
                # attention state means `budget_for` returns DEFAULT_BUDGET = 0,
                # which means every confirmation was QUEUED instead of asked,
                # which sets `asked = False`, which is exactly the flag
                # `Actor.answerable` requires before a "yes" may settle a
                # question. So no "yes" the owner has ever said could resolve
                # anything: measured 2026-09-05, three of them in a row, each
                # one re-planned from scratch into a new parked turn.
                #
                # THIS IS A MEASUREMENT AND NOT A DEFAULT, which is the whole
                # distinction `confirm.py` warns about: hard-coding "available"
                # would turn "I do not know if you are there" into "speak now",
                # and that is the declared-versus-measured error INV-HW-2
                # exists to refuse. What is measured here is narrow and true:
                # an utterance FROM THE OWNER was dispatched in this very
                # iteration, milliseconds ago. If the pump ever falls behind,
                # the age check below returns the state to UNKNOWN on its own
                # rather than vouching for a presence nobody observed.
                dispatched_at_s = time.time()
                _last_owner_s = dispatched_at_s
                if actor is not None and actor.parked():
                    verdict, rest = consent.classify(spoken)
                    if verdict == consent.OTHER or not actor.answerable():
                        # Nothing is being asked, so nothing they said settles
                        # anything: the questions go back to the queue and are
                        # put in front of them again.
                        consent_requeue(actor.broker)
                    else:
                        # THE QUESTION IN FRONT OF THEM, not the oldest one
                        # waiting. This read `parked()[0]` -- insertion order --
                        # so with two questions open a "yes" would settle a
                        # different one and run ITS action, with a record
                        # saying the owner agreed to it.
                        pending = actor.answerable()
                        try:
                            actor.broker.answer(pending,
                                          granted=(verdict == consent.YES))
                        except NotTheQuestionInFront:
                            # Queued, not in front of them: it is re-asked
                            # rather than settled by something said meanwhile.
                            consent_requeue(actor.broker)
                        except (KeyError, ValueError):
                            pass
                        else:
                            # THE STOP FOLLOWS THE ANSWER IN. A turn parked
                            # on a question has by definition been waiting --
                            # long enough for the owner to have changed their
                            # mind and pressed the stop -- and only autonomous
                            # work is subject to it, which is why the parked
                            # turn's own period decides.
                            was_auto = next(
                                (t.get("period") == "free_time"
                                 for t in actor.parked()
                                 if t["request_id"] == pending), False)
                            did = actor.resume(
                                pending, granted=(verdict == consent.YES),
                                instead=rest if verdict == consent.NO else "",
                                permitted=(interlock.autonomy_permitted
                                           if (was_auto and interlock is not None)
                                           else None))
                            # WORK ATTACHED TO AN ANSWER IS KEPT. "yes, and also
                            # check the logs" is an answer and an instruction;
                            # dropping the remainder makes the owner repeat
                            # themselves, and it goes down the ladder from the
                            # beginning as its own turn.
                            spoken = rest if (verdict == consent.YES and rest) else ""
                if actor is not None and did is None and spoken:
                    try:
                        # THE TURNS EITHER SIDE OF THIS ONE. "run it" names
                        # nothing on its own, and the proposer used to see
                        # nothing else -- so a follow-up to a request it had
                        # just satisfied came back "none" and the owner was
                        # told VESPER could not do it.
                        # BOTH SIDES, AND THE OWNER FOUND THIS THE HARD WAY.
                        #
                        # This built the acting context from `intake.history`,
                        # which holds the OWNER'S utterances only. So the half of
                        # vesper that decides whether to ACT never saw its own
                        # replies -- while the half that TALKS was handed the full
                        # `transcript` twenty lines below, in this same function,
                        # with a comment saying "vesper's own last sentence IS the
                        # antecedent".
                        #
                        # MEASURED 2026-09-11, and it is the owner's own example:
                        # "can you control safari?" -> "not yet: that one needs you
                        # at the keyboard" -> "i am on the keyboard now". The word
                        # `keyboard` appears ONLY in vesper's reply, so the proposer
                        # had no antecedent and the follow-up resolved to nothing.
                        # Vesper could discuss context it could not act on.
                        #
                        # THE ORIGINAL WORRY WAS REAL AND IS ANSWERED BY LABELLING
                        # RATHER THAN BY DELETING. `_render_recent`'s comment warns
                        # that the assistant's prose is what talks a proposer into
                        # re-proposing finished work -- so vesper's lines are marked
                        # as SAID, `last_action` still marks what was DONE, and the
                        # actor's own no-progress guard still refuses an immediate
                        # repeat. Removing the antecedent was too blunt a fix for a
                        # problem that labelling solves.
                        recent = []
                        for row in (transcript or [])[-8:]:
                            if not isinstance(row, dict):
                                continue
                            who = str(row.get("who") or "owner")
                            # `line_text`, NOT `said`. This loop variable was
                            # called `said` and the enclosing function already
                            # has a `said` -- the LIST of this batch's utterances,
                            # built at the top of the pump and appended to again
                            # at the bottom. Binding a string to that name here
                            # destroyed the list for the rest of the turn, and
                            # every turn died at `said.append(...)` with
                            # "'str' object has no attribute 'append'". Vesper
                            # answered nothing at all and the face sat at
                            # `thinking`; the pump caught it and continued, so
                            # the process stayed up while doing none of its job.
                            line_text = str(row.get("text") or "").strip()
                            if not line_text:
                                continue
                            recent.append({
                                "who": "owner" if who == "owner" else "vesper (said)",
                                "text": line_text})
                        if last_action is not None:
                            recent.append({"who": "vesper (did)",
                                           "text": last_action})
                        # Presence decays: fresh only while the utterance
                        # that proves it is fresh.
                        attention = ("available"
                                     if (time.time() - dispatched_at_s)
                                     <= PRESENCE_FRESH_S else ATTENTION_UNKNOWN)
                        did = actor.maybe_act(spoken, recent=recent,
                                              attention_state=attention,
                                              period=ACTIVE_SESSION)
                        # THE REAL THOUGHT, in the words the decision was made
                        # in. Until now every line on the thinking column came
                        # from the phrasebook in voice.toml, so the surface
                        # showed a mood and never a reason -- the owner noticed
                        # and said so. `why` is the proposer's own sentence
                        # about what it is doing and why.
                        if did is not None and bench is not None:
                            why = (did.detail or {}).get("why") if isinstance(did.detail, dict) else None
                            bench.observe(why or did.said or did.capability_id)
                            # EVERY STEP ON THE BOARD, not just the model call
                            # that answered afterwards. A multi-step turn wrote
                            # a file and then ran it; the surface showed
                            # "answered / groq-strong" and nothing about
                            # either.
                            det = did.detail if isinstance(did.detail, dict) else {}
                            steps = det.get("steps") or []
                            for st in steps:
                                if not isinstance(st, dict):
                                    continue
                                sd = st.get("detail") if isinstance(st.get("detail"), dict) else {}
                                res = sd.get("result") if isinstance(sd.get("result"), dict) else {}
                                bench.acted(
                                    st.get("capability_id") or "",
                                    st.get("args") or {},
                                    state="done",
                                    output=str(res.get("stdout")
                                              or res.get("opened") or ""))
                                _record_command(bench, st.get("capability_id"),
                                                st.get("args"), res)
                            # THE SINGLE-STEP TURN HAS NO `steps` AT ALL.
                            # `Actor` only attaches the list when a turn took
                            # MORE THAN ONE step, so recording commands from
                            # `steps` alone would have shown nothing for the
                            # ordinary case -- one request, one command -- which
                            # is most of what the owner watches. The loop above
                            # already covers the final outcome when the list
                            # exists, so this fires only when it does not.
                            if not steps:
                                _record_command(
                                    bench, did.capability_id, det.get("args"),
                                    det.get("result")
                                    if isinstance(det.get("result"), dict) else {})
                            bench.acted(
                                did.capability_id, det.get("args") or {},
                                state=("done" if did.kind == "acted" else "failed"),
                                output=str(((det.get("result") or {}) if isinstance(det.get("result"), dict) else {}).get("stdout") or ""))
                    except Exception as exc:           # noqa: BLE001
                        bus.publish("act.pass_failed", subject="actor",
                                    payload={"error": repr(exc)},
                                    component="runtime")
                if did is not None:
                    # WHAT WAS JUST DONE, kept for the next turn's pronoun.
                    # `Outcome` carries no args -- `said` is the sentence the
                    # owner was given, which is exactly the description a
                    # pronoun in the next turn needs.
                    # THE SENTENCE, WITHOUT THE IDENTIFIER IN FRONT OF IT. This
                    # read `f"{did.capability_id}: {did.said}"`, and the comment
                    # above already says why the id is not needed: `said` is the
                    # description a pronoun in the next turn wants. What the
                    # prefix DID do was put `mode.set: ...` into model-visible
                    # text, which is the exact shape that came back out of the
                    # answerer and into the owner's transcript.
                    last_action = (str(did.said)[:200] if did.said
                                   else did.capability_id)
                    bus.publish("act.outcome", subject=did.capability_id,
                                payload=did.to_dict(), component="runtime")
                    reply = did.said
                    # IF THE REFUSAL NAMES SOMETHING THE OWNER CAN CHANGE, WAIT
                    # FOR IT. The turn does not end here: the request is parked
                    # against a live condition and re-asked the moment the world
                    # satisfies it, so the owner does the thing and vesper
                    # carries on without being told.
                    _res = (did.detail or {}).get("result") \
                        if isinstance(did.detail, dict) else None
                    _wf = (_res or {}).get("wait_for") if isinstance(_res, dict) else None
                    if _wf and isinstance(_wf, dict) and not _is_resumed:
                        try:
                            _key = (str(getattr(intake.history[-1], "hlc", "")
                                        or "turn") + ":"
                                    + str(_wf.get("condition")))
                            waiting.park(_key,
                                         str(_wf.get("condition")),
                                         dict(_wf.get("args") or {}),
                                         {"text": text})
                            reply = (f"{reply} I will carry on by myself the "
                                     f"moment that is done -- you do not need "
                                     f"to tell me.")
                        except Exception as exc:       # noqa: BLE001
                            # A CONDITION NOTHING CAN CHECK IS NOT A WAIT. Said
                            # plainly rather than parked into silence.
                            bus.publish("act.wait_refused", subject=_key,
                                        payload={"error": repr(exc)},
                                        component="runtime")
                    # A TURN THAT TRIED FOUR THINGS MUST NOT REPORT ONLY THE
                    # FOURTH. `steps` is attached only when a turn took more
                    # than one, so a single-step turn is untouched.
                    _steps = (did.detail or {}).get("steps") \
                        if isinstance(did.detail, dict) else None
                    # KEYED ON WHETHER ANY STEP FAILED, NOT ON THE LAST ONE.
                    # This read `did.kind in ("refused", "failed")` and missed
                    # the case it was written for: asked for a file that does
                    # not exist, vesper tried cat, ls, find and grep -- and
                    # `find` returning nothing exits 0, so the TURN looked
                    # successful while the goal was never met. The owner was
                    # told "Done", about a search that found nothing.
                    def _any_step_failed(steps: list) -> bool:
                        for st in steps:
                            if not isinstance(st, dict):
                                continue
                            det = st.get("detail") if isinstance(st.get("detail"), dict) else {}
                            res = det.get("result") if isinstance(det.get("result"), dict) else {}
                            code = res.get("exit_code")
                            if (isinstance(code, int) and code != 0) \
                                    or res.get("ok") is False \
                                    or st.get("kind") in ("refused", "failed"):
                                return True
                        return False

                    if isinstance(_steps, list) and len(_steps) > 1 \
                            and (did.kind in ("refused", "failed")
                                 or _any_step_failed(_steps)):
                        reply = _what_was_tried(_steps, str(reply or ""))
                else:
                    # STRIPPED ON THE WAY OUT. The statement asks the answerer
                    # never to read an internal name aloud, and an instruction is
                    # a self-report -- which this corpus does not accept as
                    # evidence anywhere else either.
                    reply = strip_internal_prefix(
                        answer(gw, router, persona, intake.history[-1],
                               # EXPLICIT, THOUGH THIS BRANCH ONLY RUNS WHEN
                               # `did` IS None. Relying on the default would
                               # make the guard depend on a call site rather
                               # than on the fact, and the fact is what it is.
                               acted_this_turn=did,
                               flags=(home.open_flags() if home is not None else None),
                               renderer=renderer, updater=updater,
                               misses=misses, chooser=chooser,
                               context_cmds=context_cmds,
                               can_do=capability_statement(),
                               recent=transcript,
                               state=home.mode_now()))
                # VESPER'S REPLY IS NOT AN UTTERANCE, and the first version put
                # it into `intake.history` as one. `Intake` is the record of
                # things said TO VESPER -- its confidence, its partials and its
                # dispatch gate all describe an inbound channel. Putting its own
                # words there makes them things it was told, which is wrong in
                # the record and would eventually be wrong in behaviour: a
                # replay of the transcript would feed VESPER its own answers as
                # instructions.
                # THE SPLIT: WHAT IS SAID AND WHAT IS SHOWN.
                #
                # The owner's instruction was that explanations and long text
                # "will not say them, they just show up there, what it says
                # stays on the dialog that was made for it". So one reply
                # becomes two things at exactly one point, HERE, before either
                # destination can see it -- the stage and the synthesiser both
                # read `reply` below, and a split made in only one of them
                # would leave the other reading four hundred words aloud.
                #
                # `reply_full` KEEPS THE WHOLE ANSWER for the records beneath.
                # `baseline.record` is a corpus of what VESPER actually
                # answered, and writing the shortened line there would quietly
                # make every comparative question about memory unanswerable.
                reply_full = reply
                _turn_id = str(getattr(intake.history[-1], "hlc", "") or "")
                _split = longform.split(reply_full, question=text)
                if _split.blocks and bench is not None:
                    bench.explain(_turn_id, _split.title, _split.blocks)
                # AND `reply` BECOMES THE SPOKEN LINE, deliberately taking the
                # name the two consumers below already use. A third consumer
                # added later gets the short form by default; anything that
                # genuinely needs the whole answer has to reach for
                # `reply_full` and say so.
                reply = _split.spoken
                said.append({"who": "vesper", "text": reply,
                             "id": _turn_id, "explained": bool(_split.blocks),
                             "source": "vesper", "certain": True})

                # THE RECORD OF WHAT VESPER ANSWERED. `core/baseline.py` was
                # built first on purpose -- every question worth asking about
                # memory is comparative, and none is answerable without a
                # record of real turns -- and it was reached by nothing.
                #
                # THE PRISTINE "BEFORE MEMORY" WINDOW IS ALREADY GONE. Memory
                # landed 2026-08-30 and the module says plainly that afterwards
                # there is no way back to a clean before. So what starts here
                # is the OTHER arm of the comparison, not the one it was
                # designed to capture, and pretending otherwise would make
                # every later conclusion drawn from it wrong. Whether memory
                # was up for a given turn is recoverable by joining on
                # `memory.unavailable` in the same log.
                #
                # `declined` vs `could_not` IS DECIDED HERE AND NOWHERE ELSE.
                # In a log they are the same event, and afterwards nothing can
                # tell a choice from a failure.
                if baseline is not None:
                    if did is not None:
                        outcome = {"acted": "answered", "asked": "declined",
                                   "refused": "declined",
                                   "failed": "could_not"}.get(did.kind,
                                                              "could_not")
                    elif reply_full.startswith("no route:") or reply_full.startswith(
                            "every provider is spent"):
                        outcome = "could_not"
                    else:
                        outcome = "answered"
                    baseline.record(BaselineTurn(
                        question=text, answer=reply_full, outcome=outcome,
                        difficulty=None, language=None))
                # AND SAY IT. Until 2026-08-31 the reply was rendered and never
                # spoken -- every voice decision in the corpus governed a
                # modality the process did not have.
                #
                # `persons` COMES FROM PRESENCE, which is the whole reason that
                # module exists: a reply read into a room is heard by whoever is
                # in it, so speaking is an exposure decision and not an output
                # one. With someone else present this plans to WITHHOLD and the
                # answer stays on the screen it is already on.
                #
                # The privacy class is the gateway's own default -- anything the
                # owner types is theirs until something establishes otherwise --
                # so today every reply is private and every reply is spoken
                # locally. That is the fail-closed answer, and it is why the
                # good voice is not being used yet.
                if speech is not None:
                    try:
                        persons = (presence.persons() if presence is not None
                                   else ("owner",))
                        plan = speech.plan(reply, privacy_class="private",
                                           persons=persons)
                        speech.speak(plan)
                    except Exception as exc:       # noqa: BLE001
                        # A FAILURE TO SPEAK NEVER FAILS THE TURN. The answer is
                        # already on the screen; losing the audio is a
                        # degradation, and losing the reply would not be.
                        bus.publish("speech.failed", subject="reply",
                                    payload={"error": repr(exc)},
                                    component="runtime")
            elif res["outcome"] == "reflected":
                said.append({"who": "vesper", "source": "vesper", "certain": True,
                             "text": "I heard that, but not clearly enough to "
                                     "act on it. Say it again?"})
                # COULD_NOT, NOT DECLINED. VESPER did not choose to withhold an
                # answer; it was unable to be sure what was said. That
                # distinction cannot be recovered from the log afterwards.
                if baseline is not None:
                    baseline.record(BaselineTurn(
                        question=text,
                        answer="(reflected: below the confidence floor)",
                        outcome="could_not"))
            handled += 1
        seen = f.tell()
    OFFSET.write_text(str(seen))

    # THE QUEUE MUST ACTUALLY BE DELIVERED. A queued utterance that is dropped
    # when the work lands is indistinguishable from one that was swallowed, and
    # the owner learns that speaking during a hold loses what they said. So the
    # floor is released at the end of every pass and whatever it held is put
    # back where the next pass will read it -- the same input file typing uses,
    # so a queued line takes the ordinary route rather than a private one.
    if floor is not None and floor.holding:
        for queued in floor.release():
            text = queued if isinstance(queued, str) else (
                queued.get("text") if isinstance(queued, dict) else str(queued))
            if not text:
                continue
            with open(HEARD, "a", encoding="utf-8") as out:
                out.write(json.dumps({"text": text, "source": "typed",
                                      "requeued_from": "floor"}) + "\n")

    if said:
        transcript.extend(said)
        del transcript[:-CONVERSATION_MAX]
    home.set_transcript(list(transcript))
    # PUBLISHED EVERY PASS, including the passes that handled nothing -- a row
    # that opened during a call has to be seen to close, and closing is an event
    # that arrives while this loop is otherwise idle.
    home.set_workbench(bench.state())
    if changes is not None:
        # THROTTLED INSIDE, not here. The pump runs four times a second and
        # `git status` plus a diff per file is not free on a laptop the owner
        # has asked twice not to heat up; `GIT_REFRESH_S` owns that decision so
        # it cannot be re-tuned by accident at a call site.
        try:
            changes.refresh_git(str(REPO))
            _cs = changes.state()
            # PUBLISHED ONLY WHEN IT CHANGED. `set_changes` rewrites the whole
            # of `home.json`, and this payload is tens of kilobytes of diff
            # text; doing that four times a second for a board that only moves
            # every six is disk traffic for nothing, on a laptop the owner has
            # asked twice not to heat up. The workbench above is small and
            # genuinely changes every pass, which is why it is not gated the
            # same way.
            _sig = (len(_cs.get("changes") or []), _cs.get("repo"),
                    sum(len(c.get("hunks") or "") for c in (_cs.get("changes") or [])))
            if _sig != _changes_sig[0]:
                _changes_sig[0] = _sig
                home.set_changes(_cs)
        except Exception as exc:                   # noqa: BLE001
            bus.publish("changes.refresh_failed", subject="changes",
                        payload={"error": repr(exc)}, component="runtime")

    # THE HOST CARD, on its own slow clock. Power source is read from the
    # system and the model rows come from the last recorded completion; neither
    # changes at pump speed and `power_source()` shells out.
    _now = time.time()
    if _now - _metrics_at[0] >= METRICS_EVERY_S:
        _metrics_at[0] = _now
        try:
            _rows = _metric_rows()
            if _rows:
                home.set_rows(_rows)
        except Exception as exc:                   # noqa: BLE001
            # ITS OWN TOPIC. This block was pasted next to the changes refresh
            # and inherited its subject, so a metrics failure would have been
            # reported as a changes failure -- an event naming the wrong
            # subsystem is worse than none, because it sends the next reader to
            # the wrong file.
            bus.publish("metrics.refresh_failed", subject="metrics",
                        payload={"error": repr(exc)}, component="runtime")
    # THE ISLAND, on its own slow clock and only when something moved.
    try:
        _publish_island(bench, changes, bus)
    except Exception as exc:                       # noqa: BLE001
        bus.publish("island.publish_failed", subject="island",
                    payload={"error": repr(exc)}, component="runtime")
    home.write()
    return handled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="drain the outbox once and exit")
    ap.add_argument("--say", help="inject an utterance without the surface")
    ap.add_argument("--status", action="store_true")
    # DARIJA SPEECH IN. The machine has no on-device recogniser for it, and the
    # island refuses to open the microphone for a locale it cannot transcribe
    # itself -- so this is the route the 2026-08-31 decision names: capture
    # here, transcribe through the gateway, land in the same input file typing
    # uses. One entry point, so voice and text are the same conversation.
    ap.add_argument("--hear", nargs="?", const=6, type=float, metavar="SECONDS",
                    help="record, transcribe through the gateway, and answer")
    ap.add_argument("--permission-mode", metavar="MODE",
                    help="set how much VESPER may do without asking: "
                         + " | ".join(permission_mode.MODES))
    ap.add_argument("--permission-mode-status", action="store_true",
                    help="print the current permission mode and exit")
    args = ap.parse_args()

    # BEFORE ANYTHING IS BUILT OR READ. A second runtime that gets as far as
    # opening the stores has already begun competing for them.
    _only_one_runtime()

    # BEFORE `build()`, AND THAT IS THE WHOLE REASON THESE TWO ARE HERE RATHER
    # THAN INSIDE THE PUMP. Reading or setting the mode must not require a
    # working gateway, a model, a microphone or an enable token: the owner
    # reaches for this switch precisely when something is not working, and a
    # switch that needs the system it governs to be healthy is not a switch.
    if args.permission_mode_status:
        m = permission_mode.read()
        print(f"permission mode: {m}")
        print(f"  {permission_mode.DESCRIPTION[m]}")
        print(f"  standing level: {permission_mode.standing_level(m)}")
        return 0
    if args.permission_mode:
        try:
            rec = permission_mode.write(args.permission_mode, principal="owner")
        except permission_mode.ModeRefused as exc:
            print(f"refused: {exc}")
            return 2
        print(f"permission mode: {rec['mode']}")
        print(f"  {permission_mode.DESCRIPTION[rec['mode']]}")
        return 0

    (bus, gw, router, home, intake, triage, report, persona, bench,
     renderer, updater, misses, chooser, world, sensors,
     autonomy, devices, repairer, presence, context_cmds, verifier,
     speech, transcriber, actor, floor, baseline, interlock,
     jobs, store, changes, waiting) = build()
    # WHAT WAS SAID, BY WHOM. Held here rather than in Intake because the two
    # are different records: Intake is the inbound channel and this is the
    # conversation.
    transcript: list = _recent_conversation(store)

    if args.status:
        print(f"registered : {report['registered']}")
        print(f"profiles   : {report['profile_ids']}")
        print(f"skipped    : {report['skipped'] or 'none'}")
        print(f"face       : {home.state()}")
        return 0

    if args.hear:
        import subprocess as _sp
        import tempfile as _tf
        wav = str(pathlib.Path(_tf.gettempdir()) / "vesper-heard.caf")
        app = REPO / "app" / "VESPER.app" / "Contents" / "MacOS" / "VESPER"
        if not app.exists():
            print("the app is not built; run app/island-macos/build.sh")
            return 1
        # `open -n`, NOT a direct exec. TCC attributes a microphone request to
        # the RESPONSIBLE process, which from a shell is the shell -- the same
        # trap that made --speech-consent look granted when it was not.
        _sp.run(["open", "-n", str(REPO / "app" / "VESPER.app"), "--args",
                 "--record", "--seconds", str(args.hear), "--out", wav],
                check=False)
        time.sleep(float(args.hear) + 2.0)
        heard = Transcriber(bus, supply=transcribe_rows()).transcribe(wav)
        if not heard.ok:
            print(f"heard nothing: {heard.reason}")
            return 1
        print(f"  heard ({heard.language} {heard.confidence:.2f}): {heard.text}")
        # THE MEASURED CONFIDENCE GOES WITH IT. `Intake` gates ACTION on this
        # and treats a missing value as 0.0, so the first version of `--hear`
        # wrote none and every spoken turn came back "I heard that, but not
        # clearly enough to act on it" -- reflected, never answered. The number
        # is the transcriber's own, not a constant chosen to clear the floor.
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"text": heard.text, "source": "spoken",
                                "final": True,
                                "confidence": heard.confidence,
                                "instrument": "transcriber"},
                               ensure_ascii=False) + "\n")
        from core.intake import floor_for as _floor
        _f = _floor({"instrument": "transcriber"})
        if heard.confidence < _f:
            print(f"  (below the {_f} action floor for this instrument -- "
                  f"VESPER will ask you to repeat rather than act on it)")

    if args.say:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"text": args.say, "source": "typed",
                                "final": True}) + "\n")

    if args.once or args.say or args.hear:
        n = pump(bus, gw, router, persona, bench, home, intake, transcript,
                 floor=floor, baseline=baseline, interlock=interlock,
                 jobs=jobs, store=store,
                 once=True, waiting=waiting, renderer=renderer, updater=updater,
                 misses=misses, chooser=chooser, sensors=sensors,
                 autonomy=autonomy, triage=triage, repairer=repairer,
                 presence=presence, context_cmds=context_cmds,
                 speech=speech, transcriber=transcriber, actor=actor)
        # THE SAME HONESTY THE INTERRUPT PATH APPLIES. A one-shot run that exits
        # leaving `thinking` on disk reports work that is not happening; the
        # 90 s staleness fallback would correct it eventually, and eventually is
        # not the same as correctly.
        home._set("resting", "the one-shot run finished")
        print(f"handled {n}")
        for line in transcript:
            who = "you" if line["who"] == "owner" else "VESPER"
            print(f"  {who:>6}: {line['text'][:120]}")
        return 0

    # GREET ON ARRIVAL. The owner asked for it, and it is doing real work
    # beyond courtesy: a home that shows an empty transcript is
    # indistinguishable from a home whose runtime never started. One line says
    # the whole chain is alive -- surface, bridge, runtime, ladder -- before
    # anything is asked of it.
    #
    # NOT MODEL-GENERATED. It must appear when the ladder is unreachable, which
    # is exactly when a generated greeting could not be produced.
    hour = time.localtime().tm_hour
    part = ("Good morning" if 5 <= hour < 12 else
            "Good afternoon" if 12 <= hour < 18 else
            "Good evening")
    transcript.append({"who": "vesper", "source": "vesper", "certain": True,
                       "text": f"{part}, sir. I'm here."})
    home.set_transcript(list(transcript))
    home._set("talking", "greeting the owner")
    try:
        Announcer(bus=bus).announce(
            "greeting", interruption_class="active_user_task")
    except Exception:                               # noqa: BLE001
        # A MISSING LINE MUST NOT STOP THE RUNTIME. The greeting is the first
        # thing that runs; a template problem here would look exactly like the
        # runtime failing to start at all.
        pass
    # How many passes may fail in a row before the surface says so. One is a
    # bad pass; three is a runtime that is not working.
    _pump_fails = 0
    print("vesper runtime: watching the field. ctrl-c to stop.")
    home.write()
    while True:
        # A RUNTIME WITH NO HOME ENDS ITSELF (2026-09-14). The home spawns this
        # process. When the home dies without ending it -- a stop that SIGTERMs
        # the home, a crash -- this is reparented to launchd (ppid 1), and until
        # now it kept pumping with its actor and its autonomy: after the owner
        # pressed stop it ran autonomous turns for hours. Nothing supervises a
        # runtime but its home, so a runtime that has lost its home stops.
        if os.getppid() == 1:
            bus.publish("runtime.orphaned", subject="runtime",
                        payload={"note": "the home that spawned this runtime is gone; it stops"},
                        component="runtime")
            print("vesper runtime: the home that started me is gone; stopping.", flush=True)
            return 0
        try:
            pump(bus, gw, router, persona, bench, home, intake, transcript,
                 changes=changes,
                 floor=floor, baseline=baseline, interlock=interlock,
                 jobs=jobs, store=store, waiting=waiting,
                 renderer=renderer, updater=updater, misses=misses,
                 chooser=chooser, sensors=sensors, autonomy=autonomy,
                 triage=triage, repairer=repairer, presence=presence,
                 context_cmds=context_cmds, speech=speech,
                 transcriber=transcriber, actor=actor)
            # THE PLUMBING USED TO COST MORE THAN THE MODEL. 0.5 s here plus
            # 0.7 s in the chrome's own timer is up to 1.2 s of pure polling
            # around a call that now returns in ~0.7 s -- the transport was the
            # slower half of a conversation. An idle pass is a `seek` on a file
            # that has not changed; measured below 1 ms, so the cost of the
            # shorter interval is not on the same scale as what it buys.
            time.sleep(POLL_SECONDS)
            # RESET ONLY WHERE THE PASS ACTUALLY COMPLETED. A `finally` would
            # clear the counter on the failing passes too and the breaker would
            # never trip -- which is the same defect as a refusal counter reset
            # by the branch that observes the refusal.
            if _pump_fails:
                bus.publish("runtime.loop_recovered", subject="pump",
                            payload={"after": _pump_fails}, component="runtime")
                _pump_fails = 0
        except KeyboardInterrupt:
            raise
        except Exception as e:                      # noqa: BLE001
            # THE LOOP SURVIVES ONE BAD PASS. An exception here killed the
            # runtime outright, and the symptom was VESPER going silent -- no
            # error on screen, nothing in the home, the crash visible only in a
            # log nobody was watching. A supervisor would restart it, but the
            # app is the supervisor and it does not know the child died.
            #
            # Printed, not swallowed: a loop that hides its failures is how one
            # bad pass becomes a permanently degraded runtime that still looks
            # alive.
            import traceback as _tb
            print("pump error traceback:\n" + _tb.format_exc(), file=sys.stderr,
                  flush=True)
            print(f"pump error (continuing): {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
            # AND A LOOP THAT FAILS EVERY PASS SAYS SO ON THE SCREEN.
            #
            # MEASURED 2026-09-06, and it is why this exists. A NameError in
            # the pump's ARGUMENT LIST raised before the body ran, on every
            # pass, for eleven minutes. `home.json` kept its timestamp because
            # the greeting had already written it, the face sat at rest, and
            # the surface was indistinguishable from a VESPER with nothing to
            # do. The stderr line above was correct and went to a file nobody
            # was watching -- which is this tree's oldest failure shape wearing
            # a print statement.
            #
            # ONE PASS IS A BAD PASS AND IS NOT WORTH A WORD. Three in a row is
            # a runtime that is not working, and the owner is entitled to learn
            # that from the surface rather than from a log.
            _pump_fails += 1
            if _pump_fails == PUMP_FAIL_LOUD:
                line = (f"Something in my own loop is failing and I am not "
                        f"getting past it: {type(e).__name__}: {e}"[:400])
                transcript.append({"who": "vesper", "source": "vesper",
                                   "certain": True, "text": line})
                try:
                    home.set_transcript(list(transcript))
                    home._set("resting", "the loop is failing")
                except Exception:                   # noqa: BLE001
                    # THE REPORT MUST NOT BECOME THE SECOND FAILURE. If the
                    # surface cannot be written either, the stderr line above
                    # is what is left and it has already been printed.
                    pass
                bus.publish("runtime.loop_failing", subject="pump",
                            payload={"error": f"{type(e).__name__}: {e}",
                                     "consecutive": _pump_fails},
                            component="runtime")
            time.sleep(1.0)
        except BaseException:
            # THE FACE MUST NOT BE LEFT MID-THOUGHT. A stopped runtime that
            # leaves `thinking` on disk reports work that is not happening --
            # the staleness fallback would fix it in 90 s, and being correct
            # immediately is better than being correct eventually.
            home._set("resting", "the runtime stopped")
            print("\nstopped; face returned to rest")
            return 0


if __name__ == "__main__":
    sys.exit(main())
