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
from core.home_state import HomeState                           # noqa: E402
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
from core.actor import Actor                                    # noqa: E402
from core import consent                                        # noqa: E402
from core.confirm import (ConfirmationBroker,                    # noqa: E402
                          NotTheQuestionInFront)
from core.confirm import requeue as consent_requeue             # noqa: E402
from core.evidence import ClaimChecker                          # noqa: E402
from core.interruption import InterruptionBudget                # noqa: E402
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
OUTBOX = STATE / "say.jsonl"
# The wake listener records and queues; the runtime transcribes and
# answers. The split is deliberate: the credential and the egress
# decision live here, and the microphone lives in the app that holds
# the permission for it.
HEARD = STATE / "heard.jsonl"
HEARD_OFFSET = STATE / "heard.offset"
OFFSET = STATE / "say.offset"

# How often the outbox is re-read. See the loop at the bottom for why it is
# this small: it is half of the owner-visible floor on a reply, and the other
# half is the chrome's own timer in HomeChrome.swift.
POLL_SECONDS = 0.15


# Where `tools/ops/vesper_arm.py` leaves a fresh token. VESPER cannot write
# here: `interlock` is a self-defeating path segment, refused by the prohibited
# tier at every level including under an L5 grant.
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
        interlock.present_token(EnableToken(
            token_id=str(d["token_id"]), issued_at_ms=int(d["issued_at_ms"]),
            ttl_ms=int(d["ttl_ms"]), issued_by=str(d["issued_by"]),
            signature=str(d.get("signature", ""))))
    except Exception:                              # noqa: BLE001
        return


def build(node: str = "vesper-runtime"):
    """Wire what already exists. Nothing here decides anything."""
    STATE.mkdir(parents=True, exist_ok=True)
    clock = HybridLogicalClock(node)
    store = StoreSet(STATE / "bus", node_id=node)
    bus = EventBus(clock, store, component="runtime")
    cost = CostPolicy(bus, clock)
    ledger = QuotaLedger(path=STATE / "quota.json", bus=bus)
    gw = ModelGateway(bus, cost, quota=ledger)

    report = supply.register(gw, cost, ledger, egress_class="E1_PRIVATE")
    rows = for_egress(load_rows()[0], "E1_PRIVATE")
    router = Router(bus, measured_profiles(rows, purpose="text"))

    home = HomeState(bus=bus, clock=clock)
    home.attach(bus)

    triage = TriageQueue(path=STATE / "triage.json", bus=bus, clock=clock)
    triage.attach(bus)

    # SPOKEN WHEN THE OWNER IS WAITING, which is what typing into the field
    # means. RB-006 governs the other case and this process does not have one
    # yet: everything it handles is a request somebody just made.
    announcer = Announcer(bus=bus)
    announcer.attach(bus, interruption_class="active_user_task",
                     next_rung="a local model")

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
    bench.attach(bus)

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

    return (bus, gw, router, home, intake, triage, report, persona, bench,
            renderer, updater, misses, chooser, world, sensors, autonomy,
            devices, repairer, presence, context_cmds, verifier, speech,
            transcriber, actor, floor, baseline, interlock, jobs, store)


def answer(gw, router, persona, utterance, renderer=None,
           updater=None, misses=None, chooser=None,
           context_cmds=None) -> str:
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
    seen = int(HEARD_OFFSET.read_text()) if HEARD_OFFSET.exists() else 0
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
    HEARD_OFFSET.write_text(str(seen))
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
         once: bool = False, renderer=None, updater=None,
         misses=None, chooser=None, sensors=None, autonomy=None,
         triage=None, repairer=None, presence=None,
         context_cmds=None, speech=None, transcriber=None, actor=None,
         floor=None, baseline=None, interlock=None, jobs=None,
         store=None) -> int:
    """Read new lines, answer them, publish the transcript. Offset-tracked."""
    # The last thing VESPER actually did, so the next turn's "it" resolves.
    last_action = None
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
                autonomy.dispatch(autonomy.tick())
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
            for item in (triage.open_items(CRITICAL_NOW) or [])[:1]:
                out = repairer.repair(item)
                bus.publish("repair.attempted", subject=item.provider_id,
                            payload=out.to_dict(), component="runtime")
        except Exception as exc:                   # noqa: BLE001
            bus.publish("repair.pass_failed", subject="repair",
                        payload={"error": repr(exc)}, component="runtime")
    # DRAIN WHAT THE WAKE LISTENER CAPTURED, before reading the input file --
    # so a clip captured this pass is answered this pass rather than next.
    if transcriber is not None:
        _drain_heard(bus, transcriber)

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
                        recent = [{"who": "owner", "text": u.text}
                                  for u in intake.history[-6:] if u.final]
                        if last_action is not None:
                            recent.append({"who": "vesper (did)",
                                           "text": last_action})
                        did = actor.maybe_act(spoken, recent=recent)
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
                    last_action = (f"{did.capability_id}: {did.said}"[:200]
                                   if did.said else did.capability_id)
                    bus.publish("act.outcome", subject=did.capability_id,
                                payload=did.to_dict(), component="runtime")
                    reply = did.said
                else:
                    reply = answer(gw, router, persona, intake.history[-1],
                                   renderer=renderer, updater=updater,
                                   misses=misses, chooser=chooser,
                                   context_cmds=context_cmds)
                # VESPER'S REPLY IS NOT AN UTTERANCE, and the first version put
                # it into `intake.history` as one. `Intake` is the record of
                # things said TO VESPER -- its confidence, its partials and its
                # dispatch gate all describe an inbound channel. Putting its own
                # words there makes them things it was told, which is wrong in
                # the record and would eventually be wrong in behaviour: a
                # replay of the transcript would feed VESPER its own answers as
                # instructions.
                said.append({"who": "vesper", "text": reply,
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
                    elif reply.startswith("no route:") or reply.startswith(
                            "every provider is spent"):
                        outcome = "could_not"
                    else:
                        outcome = "answered"
                    baseline.record(BaselineTurn(
                        question=text, answer=reply, outcome=outcome,
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
    args = ap.parse_args()

    (bus, gw, router, home, intake, triage, report, persona, bench,
     renderer, updater, misses, chooser, world, sensors,
     autonomy, devices, repairer, presence, context_cmds, verifier,
     speech, transcriber, actor, floor, baseline, interlock,
     jobs, store) = build()
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
                 once=True, renderer=renderer, updater=updater,
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
    print("vesper runtime: watching the field. ctrl-c to stop.")
    home.write()
    while True:
        try:
            pump(bus, gw, router, persona, bench, home, intake, transcript,
                 floor=floor, baseline=baseline, interlock=interlock,
                 jobs=jobs, store=store,
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
            print(f"pump error (continuing): {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
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
