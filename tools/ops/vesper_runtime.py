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
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.bus import EventBus                                   # noqa: E402
from core.cost import CostPolicy                                # noqa: E402
from core.gateway import AllProvidersExhausted, ModelGateway    # noqa: E402
from core.hlc import HybridLogicalClock                         # noqa: E402
from core.home_state import HomeState                           # noqa: E402
from core.intake import Intake                                  # noqa: E402
from core.chooser import Chooser                                # noqa: E402
from core import host_probes                                    # noqa: E402
from core.autonomy import AutonomyLoop, PredicateEvaluator      # noqa: E402
from core.devices import CONTINUITY_CRITICAL, DeviceRegistry    # noqa: E402
from core.repair import RepairAgent                             # noqa: E402
from core.forgetter import expiry_trigger                       # noqa: E402
from core.sensors import Sensor, SensorRegistry, SWEEP, TIMER   # noqa: E402
from core.world import WorldModel                               # noqa: E402
from core.difficulty import classify                            # noqa: E402
from core.effort import EXPECTED_OUTPUT                         # noqa: E402
from core.narration import Announcer                            # noqa: E402
from core.persona import Persona, Situation                     # noqa: E402
from core.context_control import ContextCommands                # noqa: E402
from core.presence import Presence                              # noqa: E402
from core.speech import Speech, speech_rows                     # noqa: E402
from core.blocks import L1Renderer                              # noqa: E402
from core.evidence import ClaimChecker                          # noqa: E402
from core.memory import MemoryGraph                             # noqa: E402
from core.extract import FactExtractor                          # noqa: E402
from core.updater import MissRecorder, Updater                  # noqa: E402
from core.quota import QuotaLedger                              # noqa: E402
from core.router import NoRouteAvailable, Router                # noqa: E402
from core.store import StoreSet                                 # noqa: E402
from core.triage import TriageQueue                             # noqa: E402
from core.verify import Verifier                                # noqa: E402
from core.verifiers import register_all                         # noqa: E402
from core.workbench import Workbench                            # noqa: E402
from routing import supply                                      # noqa: E402
from routing.supply import for_egress, load_rows, measured_profiles  # noqa: E402

STATE = Path.home() / "Library" / "Application Support" / "VESPER"
OUTBOX = STATE / "say.jsonl"
OFFSET = STATE / "say.offset"

# How often the outbox is re-read. See the loop at the bottom for why it is
# this small: it is half of the owner-visible floor on a reply, and the other
# half is the chrome's own timer in HomeChrome.swift.
POLL_SECONDS = 0.15


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

    memory = renderer = updater = misses = None
    try:
        memory = MemoryGraph(store, path=str(STATE / "l2.db"))
        renderer = L1Renderer(persona, memory)
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

    return (bus, gw, router, home, intake, triage, report, persona, bench,
            renderer, updater, misses, chooser, world, sensors, autonomy,
            devices, repairer, presence, context_cmds, verifier, speech)


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


def pump(bus, gw, router, persona, bench, home, intake, transcript: list,
         once: bool = False, renderer=None, updater=None,
         misses=None, chooser=None, sensors=None, autonomy=None,
         triage=None, repairer=None, presence=None,
         context_cmds=None, speech=None) -> int:
    """Read new lines, answer them, publish the transcript. Offset-tracked."""
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
            autonomy.tick()
        except Exception as exc:                   # noqa: BLE001
            bus.publish("autonomy.loop_failed", subject="autonomy",
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
            for item in (triage.open_items() or [])[:1]:
                out = repairer.repair(item)
                bus.publish("repair.attempted", subject=item.provider_id,
                            payload=out.to_dict(), component="runtime")
        except Exception as exc:                   # noqa: BLE001
            bus.publish("repair.pass_failed", subject="repair",
                        payload={"error": repr(exc)}, component="runtime")
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
            if presence is not None:
                presence.offer(text)
            if context_cmds is not None:
                context_cmds.offer(text)
            if obj.get("source") == "spoken":
                res = intake.spoken(
                    text,
                    confidence=float(obj.get("confidence") or 0.0),
                    final=bool(obj.get("final", True)))
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
            del transcript[:-40]
            said = []
            home.set_transcript(list(transcript))
            if res["outcome"] == "dispatched":
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
            handled += 1
        seen = f.tell()
    OFFSET.write_text(str(seen))
    if said:
        transcript.extend(said)
        del transcript[:-40]
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
    args = ap.parse_args()

    (bus, gw, router, home, intake, triage, report, persona, bench,
     renderer, updater, misses, chooser, world, sensors,
     autonomy, devices, repairer, presence, context_cmds, verifier,
     speech) = build()
    # WHAT WAS SAID, BY WHOM. Held here rather than in Intake because the two
    # are different records: Intake is the inbound channel and this is the
    # conversation.
    transcript: list = []

    if args.status:
        print(f"registered : {report['registered']}")
        print(f"profiles   : {report['profile_ids']}")
        print(f"skipped    : {report['skipped'] or 'none'}")
        print(f"face       : {home.state()}")
        return 0

    if args.say:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"text": args.say, "source": "typed",
                                "final": True}) + "\n")

    if args.once or args.say:
        n = pump(bus, gw, router, persona, bench, home, intake, transcript,
                 once=True, renderer=renderer, updater=updater,
                 misses=misses, chooser=chooser, sensors=sensors,
                 autonomy=autonomy, triage=triage, repairer=repairer,
                 presence=presence, context_cmds=context_cmds,
                 speech=speech)
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
                 renderer=renderer, updater=updater, misses=misses,
                 chooser=chooser, sensors=sensors, autonomy=autonomy,
                 triage=triage, repairer=repairer, presence=presence,
                 context_cmds=context_cmds, speech=speech)
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
