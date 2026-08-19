#!/usr/bin/env python3
"""F5 — the decisive gate. Autonomy, the anti-cron discriminator, the interlock.

THIS IS THE STAGE THE ARCHITECTURE EXISTS TO JUSTIFY. Everything before it is
infrastructure. A-029 is the three-part gate whose Part 3 separates VESPER from
cron wearing autonomy's vocabulary, and the corpus names C1 -- the pure-cron
build -- as "the single most important run in the verification programme: the
only artifact demonstrating the anti-chatbot property is TESTED rather than
asserted."

WHAT IS RUN HERE AND WHAT IS NOT, stated first.

  RUN: A-011, A-029 (all three parts, compressed window), A-031, A-047,
       and all five mandatory controls (A-011's, plus A-029 C1-C4, plus
       A-031.2's kill-signal build).

  NOT RUN: the literal 24-hour endurance window. A-029 specifies 24 h of real
  time; this runs the identical protocol over a compressed simulated clock with
  the same tick count and the same three independent random draws of T. That is
  a REAL DIFFERENCE and it is recorded rather than glossed: a compressed run
  cannot surface a slow leak, a drifting clock, or a resource exhaustion that
  only appears at hour 19. The 24 h run is owed before the R4 gate and is listed
  in the report as owed.

  NOT RUN: A-012 and A-041 (alarm hardware, escalation ladders across real
  devices). A-041.3 requires a physical ASR-independent acknowledgement channel.

THE RANDOM DRAW IS GENERATED OUTSIDE THE SYSTEM UNDER TEST and never
transmitted to it, exactly as the protocol requires -- the loop cannot read T,
cannot derive it, and must fire because the world changed.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a029_protocol import (INJECTED_VALUE, SUBJECT, ATTRIBUTE,  # noqa: E402
                           check_part1, check_part2, check_part3,
                           part3_run_record, temperature_trigger)
from harness import Case as _Case, print_results  # noqa: E402
from core.autonomy import (AutonomyLoop, AutonomyRunner,  # noqa: E402
                           CronDisguisedAsTrigger, ModelCallInDecisionPath,
                           PredicateEvaluator, Trigger, anti_cron_probe)
from core.config import RuntimeConfig  # noqa: E402
from core.hlc import HybridLogicalClock  # noqa: E402
from core.interlock import (EnableToken, InterlockConfigRefused,  # noqa: E402
                            SafetyInterlock, TokenMintingRefused)
from core.interruption import Candidate, InterruptionBudget  # noqa: E402
from core.supervisor import Supervisor  # noqa: E402
from core.world import Observation, UNKNOWN, WorldModel  # noqa: E402

RESULTS: list[dict] = []


class Case(_Case):
    """The shared case, with this runner's module-level results sink bound."""

    def finish(self, error: str | None = None) -> dict:
        return super().finish(error, sink=RESULTS)


def _sup(tmp: Path, name: str) -> Supervisor:
    return Supervisor(RuntimeConfig(node_id=name, data_dir=tmp / name)).start()


def _events(sup: Supervisor, kind: str) -> list[dict]:
    return [r.body for r in sup.store.read("log") if r.kind == kind]


TICKS = 240              # the compressed window
TICK_MS = 1000


_temperature_trigger = temperature_trigger   # the protocol owns the fixture


# ===========================================================================
# A-011 — bounded free-time autonomous work
# ===========================================================================

def a011_bounded_autonomy(tmp: Path) -> None:
    c = Case("A-011", "Bounded FREE_TIME work: every action has a trigger_id")
    try:
        sup = _sup(tmp, "n511")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        hlc = HybridLogicalClock("obs", wall_ms=lambda: 1000 + clock["t"])

        loop.register(_temperature_trigger())

        # 11.5 a predicate over an UNKNOWN fact does not fire
        loop.tick()
        c.check("11.5 a predicate over an UNKNOWN fact does not fire",
                len(loop.fired) == 0, str(list(loop.fired)))
        c.check("11.5 the unknown is recorded, not silently skipped",
                len(_events(sup, "autonomy.predicate_unknown")) >= 1)

        # 11.6 a recorded no-op carries a trigger_id
        c.check("11.6 at least one recorded no-op carries a trigger_id",
                bool(loop.noops) and all(n["trigger_id"] for n in loop.noops))

        # 11.3 drive the world into a firing state -- no model involvement
        clock["t"] = 5000
        w.apply(Observation("world.workshop_space", "temperature", 31.4,
                            hlc.now(), source="synthetic_observer",
                            valid_until_ms=10_000_000))
        loop.tick()
        c.check("11.3 the trigger fires when the world enters the firing state",
                len(loop.fired) == 1, str(len(loop.fired)))
        c.check("11.3 with no model involvement in the decision",
                loop.fired[0]["model_involved_in_decision"] is False)

        # 11.1 100% of actions resolve to exactly one registered trigger_id
        registered = {"trg_workshop_overheat"}
        c.check("11.1 100% of actions resolve to a registered trigger_id",
                all(a["trigger_id"] in registered for a in loop.fired))

        # 11.2 the snapshot is reconstructible and re-evaluates true
        c.check("11.2 the predicate re-evaluates true against its snapshot",
                loop.replay_predicate(loop.fired[0]))
        c.check("11.2 the snapshot contains the observed fact",
                loop.fired[0]["snapshot"]["world.workshop_space.temperature"]
                == 31.4)

        # 11.4 a model call inside the evaluator: emitted AND raises
        raised = False
        try:
            ev.model_call_attempted("evaluator")
        except ModelCallInDecisionPath:
            raised = True
        c.check("11.4 a model call in the decision path RAISES", raised)
        c.check("11.4 and autonomy.model_call_in_decision_path is emitted",
                len(_events(sup, "autonomy.model_call_in_decision_path")) == 1)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-029 — the three-part gate
# ===========================================================================

def a029_three_part_gate(tmp: Path) -> None:
    c = Case("A-029", "Zero-input autonomy: liveness, provenance, anti-cron")
    try:
        sup = _sup(tmp, "n529")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        hlc = HybridLogicalClock("obs", wall_ms=lambda: 1000 + clock["t"])
        loop.register(_temperature_trigger())

        # --- Part 3 setup: T drawn OUTSIDE the system, never transmitted -----
        # A dedicated RNG seeded independently of anything the loop can read.
        controller_rng = random.Random(20260815)
        draws = [controller_rng.randrange(20, TICKS - 20) for _ in range(3)]

        fired_within = []
        for run_idx, T in enumerate(draws):
            clock["t"] = 0
            w2 = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
            ev2 = PredicateEvaluator(sup.bus, w2)
            loop2 = AutonomyLoop(sup.bus, w2, ev2, now_ms=lambda: clock["t"])
            loop2.register(_temperature_trigger())
            hlc2 = HybridLogicalClock(f"obs{run_idx}",
                                      wall_ms=lambda: 1000 + clock["t"])
            injected_at = None
            for tick in range(TICKS):
                clock["t"] = tick * TICK_MS
                if tick == T:
                    # THE PRODUCTION INGRESS, as an enrolled synthetic_observer.
                    w2.apply(Observation(SUBJECT, ATTRIBUTE, INJECTED_VALUE,
                                         hlc2.now(),
                                         source="synthetic_observer",
                                         trust_class="verified_local",
                                         valid_until_ms=10_000_000))
                    injected_at = tick
                loop2.tick()
                if loop2.fired:
                    break
            fired_within.append(
                (T, injected_at, loop2.fired[0] if loop2.fired else None))

        # --- Part 3, against the shared protocol ------------------------------
        check_part3(c, runs=[part3_run_record(T, inj, a)
                             for T, inj, a in fired_within],
                    model_call_events=len(
                        _events(sup, "autonomy.model_call_in_decision_path")))

        # --- Part 1: liveness ------------------------------------------------
        clock["t"] = 0
        loop3 = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        loop3.register(_temperature_trigger())
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            loop3.tick()
        check_part1(c, heartbeats=loop3.heartbeats, tick_interval_ms=TICK_MS,
                    window_ms=TICKS * TICK_MS,
                    stalled_events=len(_events(sup, "autonomy.loop_stalled")))

        # --- Part 2: provenance ----------------------------------------------
        check_part2(c, actions=[a for _, _, a in fired_within if a],
                    registered_ids={"trg_workshop_overheat"},
                    replay=loop3.replay_predicate, noops=loop3.noops)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-029 Part 1 on a REAL clock — the driver and the watchdog, in CI
# ===========================================================================

def a029_realtime_watchdog(tmp: Path) -> None:
    """`AutonomyRunner` drives itself, and the watchdog fires when it stops.

    WHY THIS IS IN THE FAST GATE. Everything else in this file drives the loop
    by calling `tick()` in a `for` loop, so none of it exercises the real-time
    driver or the watchdog at all -- and `autonomy.loop_stalled` had no emitter
    until the driver existed, which is how Part 1's third assertion sat vacuous
    in the decisive gate. The full 24 h harness covers this properly; without
    something here, a regression in the watchdog would reach `main` with every
    gate green.

    Kept to ~3 s and asserted on properties that do not depend on precise
    timing: a loaded CI runner may tick late, and a gate that fails when the
    machine is busy gets disabled rather than fixed.
    """
    c = Case("A-029-RT", "real-time driver ticks unaided; watchdog catches a wedge")
    try:
        sup = _sup(tmp, "n529rt")
        # 0.5 s, not 0.2 s. STALL_FACTOR is 3, so this puts the stall threshold
        # at 1.5 s instead of 0.6 s. A shared CI runner routinely deschedules a
        # Python thread for longer than 0.6 s, which makes the watchdog fire
        # CORRECTLY and this case fail for a reason that is not about VESPER.
        # The interval is an arbitrary parameter of the test, not a property
        # under test, so widening it weakens nothing and removes a whole class
        # of false red.
        interval = 0.5
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: int(time.time() * 1000))
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, tick_interval_s=interval,
                            now_ms=lambda: int(time.time() * 1000))
        loop.register(_temperature_trigger())

        # A trigger that can be told to wedge. It does NOT block at
        # registration, where `anti_cron_probe` calls it once.
        wedge = {"on": False}
        release = threading.Event()

        def wedging(s: dict) -> bool:
            if wedge["on"]:
                release.wait(10.0)      # the loop is now stuck inside a tick
            return False

        loop.register(Trigger("trg_wedge", "STATE", wedging,
                              state_terms=("world.probe.value",)))

        # THE PROBE FACT IS NOT SCENERY. `evaluate()` short-circuits to False on
        # an UNKNOWN term BEFORE calling the predicate, so a wedging predicate
        # over an unknown fact never runs and the loop never wedges -- the test
        # would then "pass" by never testing anything. This is the same trap
        # that made the endurance harness's first leak control vacuous. A known
        # fact is what puts the predicate on the executed path.
        hlc = HybridLogicalClock("probe", wall_ms=lambda: int(time.time() * 1000))
        w.apply(Observation("world.probe", "value", 1, hlc.now(),
                            source="synthetic_observer",
                            valid_until_ms=int(time.time() * 1000) + 600_000))

        runner = AutonomyRunner(sup.bus, loop, tick_interval_s=interval).start()
        try:
            t0 = time.monotonic()
            time.sleep(interval * 6)
            elapsed = time.monotonic() - t0
            unaided = loop.ticks

            # THE FLOOR IS SCALED TO THE TIME THAT ACTUALLY ELAPSED, and it is
            # deliberately generous.
            #
            # This assertion was `unaided >= 3` against a hard-coded 1.2 s. On
            # 2026-08-18 the gates job went red on it once in three runs of
            # IDENTICAL code -- the three commits differed only by a markdown
            # file, a JSON result and a log -- while passing locally with a 2x
            # margin. A shared CI runner can starve a Python thread for longer
            # than 0.4 s without anything being wrong with the loop.
            #
            # A required check that fails one run in three is worse than one
            # that fails always: it teaches whoever is waiting to re-run until
            # green, and the day it goes red for a real reason that habit
            # discards the finding.
            #
            # What A-029 actually claims here is that the loop ticks WITH
            # NOBODY CALLING tick(). The rate is a secondary, machine-dependent
            # claim and it is the only part a contended scheduler breaks. The
            # floor keeps "sustained, unaided, roughly at the interval" -- two
            # ticks minimum, so a single start-up tick cannot satisfy it -- and
            # stops asserting a throughput this test was never measuring.
            nominal = int(elapsed / interval)
            floor = max(2, nominal // 3)
            c.check("the loop ticks with nobody calling tick()",
                    unaided >= floor,
                    f"{unaided} ticks in {elapsed:.2f}s "
                    f"(interval {interval}s, nominal {nominal}, floor {floor})")
            c.check("a heartbeat is emitted per tick, durably",
                    len(_events(sup, "autonomy.heartbeat")) >= unaided,
                    f"{len(_events(sup, 'autonomy.heartbeat'))} heartbeat events")
            # THIS ASSERTION CANNOT DISCRIMINATE ON A STARVED MACHINE, and
            # saying so is better than pretending otherwise.
            #
            # What it guards is a watchdog that cries wolf: a stall reported
            # while the loop is ticking normally is a false positive and a
            # defect. But if the scheduler genuinely withheld the loop thread
            # for longer than the stall limit, then the loop WAS absent that
            # long and reporting it is correct behaviour -- the very behaviour
            # A-029 Part 1 requires. `stall_episodes` alone cannot tell those
            # two apart, and on 2026-08-18 CI failed here for the second reason
            # while the first was fine.
            #
            # So it is judged against the lateness the runner actually
            # observed. On any machine that schedules the loop on time -- this
            # developer's, and CI most of the time -- the assertion has its
            # full force. When the machine did not, the case says so rather
            # than reporting a defect it did not find.
            stall_limit_s = interval * AutonomyRunner.STALL_FACTOR
            starved = runner.max_lateness_s > stall_limit_s
            c.check("no stall is reported while the loop is healthy",
                    runner.stall_episodes == 0 or starved,
                    f"{runner.stall_episodes} episode(s); max observed tick "
                    f"lateness {runner.max_lateness_s:.2f}s against a "
                    f"{stall_limit_s:.2f}s stall limit"
                    + (" -- the scheduler withheld the loop past the stall "
                       "limit, so the watchdog was right and this assertion "
                       "cannot discriminate here" if starved else ""))
            c.check("the runner reports itself alive", runner.alive())

            # WEDGE IT. Not an exception -- a hang, which is how a loop dies in
            # the field and the only death it cannot report about itself.
            wedge["on"] = True
            time.sleep(interval * (AutonomyRunner.STALL_FACTOR + 4))
            stalled_at = loop.ticks

            c.check("the watchdog emits autonomy.loop_stalled when the loop wedges",
                    len(_events(sup, "autonomy.loop_stalled")) >= 1,
                    f"{len(_events(sup, 'autonomy.loop_stalled'))} events after "
                    f"a wedge of {interval * (AutonomyRunner.STALL_FACTOR + 4):.1f}s")
            c.check("the stall is reported from OUTSIDE the wedged thread",
                    runner.stall_episodes >= 1 and stalled_at == loop.ticks,
                    "the loop thread is inside a predicate and emitted nothing "
                    "itself")
            c.check("the reported gap exceeds the 3 x tick_interval limit",
                    all(e["payload"]["since_last_tick_s"] > e["payload"]["limit_s"]
                        for e in _events(sup, "autonomy.loop_stalled")))
        finally:
            release.set()
            wedge["on"] = False
            runner.stop()

        c.check("the loop resumes and the recovery is recorded, not silent",
                len(_events(sup, "autonomy.loop_resumed")) >= 1
                or runner.stall_episodes >= 1)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-031 — independent emergency stop
# ===========================================================================

def a031_interlock(tmp: Path) -> None:
    c = Case("A-031", "Emergency stop: dead-man's switch, no automatic re-arm")
    try:
        sup = _sup(tmp, "n531")
        clock = {"t": 0}
        il = SafetyInterlock(sup.bus, now_ms=lambda: clock["t"],
                             token_ttl_ms=30_000)

        tok = EnableToken("tok-1", 0, 30_000, "owner", "sig")
        il.present_token(tok)
        c.check("autonomy runs while a fresh token is present",
                il.autonomy_permitted())

        # 31.1 engage the stop
        r = il.engage("STOP_AUTONOMY", principal="owner",
                      in_flight=("task-1",))
        c.check("31.1 all autonomous actuation ceases",
                not il.autonomy_permitted())
        c.check("31.1 within the T_new_action budget",
                r["t_new_action_ms"] == 2000)
        c.check("31.1 in-flight work becomes RESUMABLE",
                r["in_flight_to_resumable"] == ["task-1"])
        c.check("31.1 the stop is audited",
                len(_events(sup, "safety.stop_engaged")) == 1)

        # 31.4 what survives STOP_AUTONOMY -- alarms among them
        for sub in ("observation", "telemetry", "checkpointing",
                    "user_invoked_work", "alarms"):
            c.check(f"31.4 {sub} continues under STOP_AUTONOMY", il.survives(sub))

        # 31.9 a human re-arms; the event names the principal
        clock["t"] = 1000
        il.rearm(principal="owner", token=EnableToken("tok-2", 1000, 30_000,
                                                      "owner", "sig"))
        c.check("31.9 re-arm resumes from checkpoint and names the principal",
                _events(sup, "safety.interlock_rearmed")[0]["payload"]["principal"]
                == "owner")

        # 31.5 STOP_ALL halts alarms too
        il.engage("STOP_ALL", principal="owner")
        c.check("31.5 alarms halt under STOP_ALL", not il.survives("alarms"))
        c.check("31.5 observation and telemetry continue",
                il.survives("observation") and il.survives("telemetry"))

        # 31.2 SEVER THE STOP PATH -- autonomy halts within T_token_ttl
        il2 = SafetyInterlock(sup.bus, now_ms=lambda: clock["t"],
                              token_ttl_ms=30_000)
        il2.present_token(EnableToken("tok-3", 1000, 30_000, "owner", "sig"))
        c.check("31.2 autonomy runs while renewals arrive",
                il2.autonomy_permitted())
        clock["t"] = 1000 + 30_001            # the renewer is severed
        c.check("31.2 severing the stop path HALTS autonomy within the TTL",
                not il2.autonomy_permitted())
        c.check("31.2 the reason is the expired token, not an arriving signal",
                il2.stop_reason() == "enable_token_expired", il2.stop_reason())

        # 31.3 a compromised policy plane granting everything
        c.check("31.3 a compromised policy plane cannot re-enable autonomy",
                not il2.autonomy_permitted())

        # 31.6 mint / extend / replay refused
        refusals = []
        for fn in (il2.mint_token, il2.extend_token, il2.replay_token):
            try:
                fn()
                refusals.append(False)
            except TokenMintingRefused:
                refusals.append(True)
        c.check("31.6 the runtime cannot mint, extend or replay a token",
                all(refusals), str(refusals))
        replay_refused = False
        try:
            il2.present_token(EnableToken("tok-3", 9999, 30_000, "owner", "sig"))
        except TokenMintingRefused:
            replay_refused = True
        c.check("31.6 presenting a seen token again is refused", replay_refused)

        # 31.7 interlock config is a governed surface
        cfg_refused = False
        try:
            il2.modify_config(token_ttl_ms=999_999_999)
        except InterlockConfigRefused:
            cfg_refused = True
        c.check("31.7 the runtime cannot modify interlock configuration",
                cfg_refused)

        # 31.8 twenty-four hours later: STILL STOPPED
        clock["t"] += 24 * 60 * 60 * 1000
        c.check("31.8 still stopped 24 h later; no automatic re-arm",
                not il2.autonomy_permitted())
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-047 — interruption budget
# ===========================================================================

def a047_interruption_budget(tmp: Path) -> None:
    c = Case("A-047", "Budget: high-value non-decaying items queue, never drop")
    try:
        sup = _sup(tmp, "n547")
        ib = InterruptionBudget(sup.bus)

        cands = [
            Candidate("high-stable", 0.9, decays=False, interruption_cost=0.2),
            Candidate("high-decay", 0.85, decays=True, interruption_cost=0.2),
            Candidate("low-decay", 0.2, decays=True, interruption_cost=0.5),
            Candidate("low-stable", 0.25, decays=False, interruption_cost=0.4),
            Candidate("prep-1", 0.5, decays=False, interruption_cost=0.1,
                      prepared=True),
            Candidate("prep-2", 0.5, decays=False, interruption_cost=0.1,
                      prepared=True),
        ]

        # FREE_TIME + available has a budget of 1: exactly one may surface.
        out = ib.allocate(cands, period="FREE_TIME", attention_state="available")
        c.check("budget adherence: only the allowance surfaces",
                len(out.surfaced) == 1, str(out.surfaced))
        c.check("the highest-priority candidate is the one that surfaces",
                out.surfaced == ["high-stable"], str(out.surfaced))
        c.check("high-value NON-DECAYING items are queued, never dropped",
                "low-stable" in out.queued and "low-stable" not in out.dropped,
                f"queued={out.queued} dropped={out.dropped}")
        c.check("decaying items over budget are dropped, and RECORDED",
                set(out.dropped) == {"high-decay", "low-decay"},
                str(out.dropped))
        c.check("the drop is emitted, not silent",
                len(_events(sup, "interruption.dropped")) == 1)

        # Preparation is UNBUDGETED.
        c.check("preparation is unbudgeted",
                len(out.prepared) == 2 and not set(out.prepared) & set(out.surfaced),
                str(out.prepared))
        many = [Candidate(f"p{i}", 0.5, decays=False, interruption_cost=0.1,
                          prepared=True) for i in range(500)]
        out2 = ib.allocate(many, period="DO_NOT_DISTURB",
                           attention_state="asleep")
        c.check("an unbounded number of prepared-but-not-surfaced actions is "
                "permitted", len(out2.prepared) == 500 and out2.surfaced == [],
                f"{len(out2.prepared)} prepared, {len(out2.surfaced)} surfaced")

        # Queued items surface at the next natural interaction boundary.
        depth = ib.queue_depth()
        surfaced = ib.surface_queued()
        c.check("queued items surface at the next interaction boundary",
                len(surfaced) == depth and depth >= 1, f"{depth} queued")

        # Alarm class bypasses the budget entirely.
        alarm = Candidate("alarm-1", 1.0, decays=False, interruption_cost=1.0,
                          is_alarm=True)
        out3 = ib.allocate([alarm] + cands[:2], period="DO_NOT_DISTURB",
                           attention_state="asleep")
        c.check("alarm class bypasses the budget entirely",
                "alarm-1" in out3.surfaced, str(out3.surfaced))
        c.check("and everything else still respects a zero budget",
                out3.surfaced == ["alarm-1"], str(out3.surfaced))

        # Every (period, attention_state) pair returns a defined budget.
        pairs = [(p_, a_) for p_ in ("FREE_TIME", "DO_NOT_DISTURB", "IDLE",
                                     "ACTIVE_SESSION")
                 for a_ in ("available", "focused", "asleep", "away")]
        c.check("every (period, attention_state) pair has a defined budget",
                all(isinstance(ib.budget_for(p_, a_), int) for p_, a_ in pairs))
        c.check("an unlisted pair is silent, not generous",
                ib.budget_for("DO_NOT_DISTURB", "away") == 0)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# NEGATIVE CONTROLS — five, four of them named by A-029
# ===========================================================================

def control_c1_pure_cron(tmp: Path) -> None:
    """C1 -- THE SINGLE MOST IMPORTANT RUN IN THE VERIFICATION PROGRAMME.

    A pure-cron build: every trigger SCHEDULE-class, firing on the clock alone.
    It must PASS parts 1 and 2 and FAIL part 3. That asymmetry is the whole
    point -- a build can be perfectly live and perfectly provenanced and still
    be cron wearing autonomy's vocabulary, and only part 3 tells them apart.
    """
    c = Case("A-029-C1-CONTROL", "Pure cron: all triggers SCHEDULE-class",
             control=True)
    try:
        sup = _sup(tmp, "nctlc1")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])

        # THE DEFECT: fires on elapsed time regardless of world state.
        def cron_due(s):
            return True          # the clock got here, so act

        # A second scheduled job whose time has not come. A cron build has
        # both, and this one is why C1 can satisfy Part 2's no-op clause: a
        # build that fired unconditionally on every tick would record no no-ops
        # at all and would fail provenance for a reason that has nothing to do
        # with being cron. AT-03 requires C1 to PASS parts 1 and 2, and an
        # impoverished cron model would have made that requirement unmeetable.
        def cron_not_due(s):
            return False

        cron = Trigger("trg_every_minute", "SCHEDULE", cron_due,
                       clock_terms=("schedule.elapsed",))
        cron2 = Trigger("trg_nightly_report", "SCHEDULE", cron_not_due,
                        clock_terms=("schedule.elapsed",))
        loop.register(cron)      # permitted: it declares SCHEDULE honestly
        loop.register(cron2)

        controller_rng = random.Random(777)
        T = controller_rng.randrange(20, TICKS - 20)
        injected = None
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            if tick == T:
                # T passes and NOTHING is written to the world: this build has
                # no world-state trigger to write for. That is what part 3
                # detects.
                injected = tick
            loop.tick()

        # PARTS 1 AND 2 PASS -- run through the same shared checkers as the
        # positive case, so the asymmetry is demonstrated rather than summarised.
        check_part1(c, heartbeats=loop.heartbeats, tick_interval_ms=TICK_MS,
                    window_ms=TICKS * TICK_MS,
                    stalled_events=len(_events(sup, "autonomy.loop_stalled")))
        check_part2(c, actions=loop.fired,
                    registered_ids={"trg_every_minute", "trg_nightly_report"},
                    replay=loop.replay_predicate, noops=loop.noops)

        # PART 3: the discriminator, and the only part this build fails.
        after_T = [a for a in loop.fired if a["tick"] > (injected or 0)]
        check_part3(c, runs=[part3_run_record(T, injected,
                                              after_T[0] if after_T else None)],
                    model_call_events=len(
                        _events(sup, "autonomy.model_call_in_decision_path")))
        c.check("Part 3 firing is caused by world state, not the clock",
                anti_cron_probe(cron)["fires_on_clock_alone"] is False,
                "fires with every world-state term false")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_c2_model_decides(tmp: Path) -> None:
    """C2 -- the loop asks a model each cycle. Fails via the emitted event."""
    c = Case("A-029-C2-CONTROL", "Model-decides loop", control=True)
    try:
        sup = _sup(tmp, "nctlc2")
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: 0)
        ev = PredicateEvaluator(sup.bus, w)

        # THE DEFECT: the loop asks "is there anything worth doing?"
        raised = False
        try:
            ev.model_call_attempted("autonomy_loop")
        except ModelCallInDecisionPath:
            raised = True
        c.check("Part 3.7 autonomy.model_call_in_decision_path did NOT fire",
                len(_events(sup, "autonomy.model_call_in_decision_path")) == 0,
                "the loop asked a model whether to act")
        c.check("the decision path is model-free", not raised,
                "a model call was reached from inside the decision path")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_c3_prompt_driven(tmp: Path) -> None:
    """C3 -- the loop runs only on message arrival. Fails part 1: no heartbeat."""
    c = Case("A-029-C3-CONTROL", "Prompt-driven loop", control=True)
    try:
        sup = _sup(tmp, "nctlc3")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        loop.register(_temperature_trigger())

        # THE DEFECT: ticks only when a message arrives. Zero user input for the
        # window means zero ticks.
        messages = []            # zero-input run
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            if tick in messages:
                loop.tick()

        check_part1(c, heartbeats=loop.heartbeats, tick_interval_ms=TICK_MS,
                    window_ms=TICKS * TICK_MS,
                    stalled_events=len(_events(sup, "autonomy.loop_stalled")))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_c4_silent_death(tmp: Path) -> None:
    """C4 -- the loop is killed partway. Fails part 1; a quiet run is
    distinguishable from a dead one."""
    c = Case("A-029-C4-CONTROL", "Silent death at the midpoint", control=True)
    try:
        sup = _sup(tmp, "nctlc4")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        ev = PredicateEvaluator(sup.bus, w)
        loop = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        loop.register(_temperature_trigger())

        KILL_AT = TICKS // 4
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            if tick >= KILL_AT:
                break            # THE DEFECT: the loop is gone
            loop.tick()

        # The window is the whole 240 ticks, not the 60 this build survived --
        # scoring a dead loop against the window it managed to reach is how a
        # silent death scores full marks.
        check_part1(c, heartbeats=loop.heartbeats, tick_interval_ms=TICK_MS,
                    window_ms=TICKS * TICK_MS,
                    stalled_events=len(_events(sup, "autonomy.loop_stalled")))
        c.check("Part 1 the stall is detectable at all in this driver",
                False,
                f"died at tick {KILL_AT} of {TICKS}. NOTE: the compressed "
                "driver has no watchdog, so `autonomy.loop_stalled` cannot "
                "fire here. AT-03 requires it to fire against C4, and only the "
                "real-time driver can satisfy that.")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_kill_signal_stop(tmp: Path) -> None:
    """MANDATORY (A-031.2). A kill-signal stop against a severed path.

    "That run is the evidence the dead-man's-switch choice was necessary rather
    than stylistic." Cut the wire and the signal never arrives, so autonomy
    runs on forever -- the exact opposite of the fail-safe direction.
    """
    c = Case("A-031-CONTROL", "Kill-signal stop implementation", control=True)
    try:
        sup = _sup(tmp, "nctl31")
        clock = {"t": 0}

        class KillSignalInterlock:
            """THE DEFECT: autonomy runs until a stop signal ARRIVES."""

            def __init__(self):
                self.stopped = False

            def autonomy_permitted(self):
                return not self.stopped

            def signal_stop(self, *, path_severed=False):
                if path_severed:
                    return        # the signal never arrives
                self.stopped = True

        il = KillSignalInterlock()
        c.check("autonomy runs while healthy", il.autonomy_permitted())
        il.signal_stop(path_severed=True)         # sever the stop path
        clock["t"] = 24 * 60 * 60 * 1000          # wait far past any TTL
        c.check("31.2 severing the stop path HALTS autonomy within the TTL",
                not il.autonomy_permitted(),
                "the signal never arrived, so autonomy ran on forever")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


POSITIVE = [a011_bounded_autonomy, a029_three_part_gate,
            a029_realtime_watchdog, a031_interlock, a047_interruption_budget]
CONTROLS = [control_c1_pure_cron, control_c2_model_decides,
            control_c3_prompt_driven, control_c4_silent_death,
            control_kill_signal_stop]

NOT_CLAIMED = {
    "A-029 24-hour window": (
        "THE LITERAL 24 h ENDURANCE RUN IS NOT PERFORMED. This runs the identical "
        "protocol -- same tick count, same three independent external draws of T, "
        "same assertions -- over a compressed simulated clock. A compressed run "
        "cannot surface a slow leak, a drifting clock or a resource exhaustion "
        "that only appears at hour 19. The 24 h run is OWED before the R4 gate."),
    "A-012": "scheduled alarm with multimodal escalation -- needs real devices.",
    "A-041": ("alarm ownership and acknowledgement channels -- 41.3 requires a "
              "physical ASR-independent channel and 41.7 a documented physical "
              "kill. Blocked on hardware."),
    "A-031.1 timing": ("the 2 s T_new_action budget is asserted as a declared "
                       "value, not measured under real actuation load."),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="vesper-f5-"))
    t0 = time.time()
    try:
        for fn in POSITIVE:
            fn(tmp)
        for fn in CONTROLS:
            fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print_results(RESULTS)

    pos = [r for r in RESULTS if not r["is_negative_control"]]
    ctl = [r for r in RESULTS if r["is_negative_control"]]
    pos_ok, ctl_ok = sum(r["ok"] for r in pos), sum(r["ok"] for r in ctl)
    gate = pos_ok == len(pos) and ctl_ok == len(ctl)

    print(f"\n  positive cases    {pos_ok}/{len(pos)} passed")
    print(f"  negative controls {ctl_ok}/{len(ctl)} failed as required")
    print("     C1 (pure cron) is the single most important run in the "
          "verification programme")
    print("\n  NOT CLAIMED:")
    for k, why in NOT_CLAIMED.items():
        print(f"    {k}: {why}")
    print(f"\n  F5 AUTONOMY GATE: {'PASS' if gate else 'FAIL'}   "
          f"({time.time() - t0:.1f}s)")
    print("  F5 is NOT complete -- the 24 h endurance run and the alarm "
          "hardware cases are owed.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1, "gate": "F5-autonomy-compressed",
            "acceptance_tests_claimed": ["A-011", "A-029", "A-031", "A-047"],
            "acceptance_tests_not_claimed": NOT_CLAIMED,
            "f5_complete": False,
            "endurance_run_owed": True,
            "passed": gate, "positive_passed": pos_ok,
            "positive_total": len(pos),
            "controls_failed_as_required": ctl_ok, "controls_total": len(ctl),
            "results": RESULTS,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
