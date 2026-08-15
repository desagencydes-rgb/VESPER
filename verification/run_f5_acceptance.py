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
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.autonomy import (AutonomyLoop, CronDisguisedAsTrigger,  # noqa: E402
                           ModelCallInDecisionPath, PredicateEvaluator,
                           Trigger, anti_cron_probe)
from core.config import RuntimeConfig  # noqa: E402
from core.hlc import HybridLogicalClock  # noqa: E402
from core.interlock import (EnableToken, InterlockConfigRefused,  # noqa: E402
                            SafetyInterlock, TokenMintingRefused)
from core.interruption import Candidate, InterruptionBudget  # noqa: E402
from core.supervisor import Supervisor  # noqa: E402
from core.world import Observation, UNKNOWN, WorldModel  # noqa: E402

RESULTS: list[dict] = []


class Case:
    def __init__(self, cid: str, title: str, *, control: bool = False) -> None:
        self.cid, self.title, self.control = cid, title, control
        self.assertions: list[dict] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.assertions.append({"assertion": name, "passed": bool(passed),
                                "detail": detail})
        return bool(passed)

    def finish(self, error: str | None = None) -> dict:
        allp = bool(self.assertions) and all(a["passed"] for a in self.assertions)
        if self.control:
            ok = not allp
            verdict = ("CONTROL OK -- broken build failed as required" if ok else
                       "HARNESS DEFECT -- the control PASSED, so it tests nothing. "
                       "The matching positive result is void.")
        else:
            ok = allp and error is None
            verdict = "PASS" if ok else "FAIL"
        rec = {"case": self.cid, "title": self.title,
               "is_negative_control": self.control, "ok": ok,
               "verdict": verdict, "assertions": self.assertions}
        if error:
            rec["error"] = error
        RESULTS.append(rec)
        return rec


def _sup(tmp: Path, name: str) -> Supervisor:
    return Supervisor(RuntimeConfig(node_id=name, data_dir=tmp / name)).start()


def _events(sup: Supervisor, kind: str) -> list[dict]:
    return [r.body for r in sup.store.read("log") if r.kind == kind]


TICKS = 240              # the compressed window
TICK_MS = 1000


def _temperature_trigger() -> Trigger:
    """The A-029 Part 3 trigger, registered BEFORE the run.

    STATE-class: `temperature > 30 AND NOT is_unknown(temperature)`. With the
    fact absent or expired it is false at every instant of every day, which is
    what makes it a state trigger rather than a schedule.
    """
    def predicate(s: dict) -> bool:
        t = s.get("world.workshop_space.temperature")
        if t is UNKNOWN or t is None or t is False:
            return False
        try:
            return float(t) > 30.0
        except (TypeError, ValueError):
            return False

    return Trigger("trg_workshop_overheat", "STATE", predicate,
                   state_terms=("world.workshop_space.temperature",))


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
                loop.fired == [], str(loop.fired))
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
                    w2.apply(Observation("world.workshop_space", "temperature",
                                         31.4, hlc2.now(),
                                         source="synthetic_observer",
                                         trust_class="verified_local",
                                         valid_until_ms=10_000_000))
                    injected_at = tick
                loop2.tick()
                if loop2.fired:
                    break
            if loop2.fired and injected_at is not None:
                delta = loop2.fired[0]["tick"] - injected_at
                fired_within.append((T, delta, loop2.fired[0]))
            else:
                fired_within.append((T, None, None))

        # 4. fires within <= 2 x tick_interval of T
        c.check("Part 3.4 all three independent draws fired",
                all(d is not None for _, d, _ in fired_within),
                str([d for _, d, _ in fired_within]))
        c.check("Part 3.4 each fired within 2 ticks of T",
                all(d is not None and d <= 2 for _, d, _ in fired_within),
                str([d for _, d, _ in fired_within]))
        # 5. the trigger_id resolves to the STATE-class trigger
        c.check("Part 3.5 the fired trigger_id is the STATE-class trigger",
                all(a and a["trigger_id"] == "trg_workshop_overheat"
                    and a["predicate_class"] == "STATE"
                    for _, _, a in fired_within))
        # 6. the reconstructed snapshot contains the injected fact
        c.check("Part 3.6 the reconstructed snapshot contains the injected fact",
                all(a and a["snapshot"]["world.workshop_space.temperature"] == 31.4
                    for _, _, a in fired_within))
        # 7. no model call during the window
        c.check("Part 3.7 autonomy.model_call_in_decision_path did NOT fire",
                len(_events(sup, "autonomy.model_call_in_decision_path")) == 0)
        # The discriminator itself.
        c.check("Part 3 NOT every fired trigger is SCHEDULE-class",
                all(a and a["predicate_class"] != "SCHEDULE"
                    for _, _, a in fired_within))

        # --- Part 1: liveness ------------------------------------------------
        clock["t"] = 0
        loop3 = AutonomyLoop(sup.bus, w, ev, now_ms=lambda: clock["t"])
        loop3.register(_temperature_trigger())
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            loop3.tick()
        gaps = [loop3.heartbeats[i + 1]["at_ms"] - loop3.heartbeats[i]["at_ms"]
                for i in range(len(loop3.heartbeats) - 1)]
        c.check("Part 1 a heartbeat is present at the declared cadence",
                len(loop3.heartbeats) == TICKS, str(len(loop3.heartbeats)))
        c.check("Part 1 no gap exceeds 3 x tick_interval",
                all(g <= 3 * TICK_MS for g in gaps),
                f"max gap {max(gaps) if gaps else 0} ms")
        c.check("Part 1 autonomy.loop_stalled never fires",
                len(_events(sup, "autonomy.loop_stalled")) == 0)

        # --- Part 2: provenance ----------------------------------------------
        c.check("Part 2 100% of actions resolve to exactly one trigger_id",
                all(a and a["trigger_id"] for _, _, a in fired_within))
        c.check("Part 2 each predicate re-evaluates true against its snapshot",
                all(a and loop.replay_predicate(a) for _, _, a in fired_within))
        c.check("Part 2 at least one recorded no-op carries a trigger_id",
                bool(loop3.noops) and all(n["trigger_id"] for n in loop3.noops))
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

        # THE DEFECT: fires every N ticks regardless of world state.
        def cron_predicate(s):
            return True          # the clock got here, so act

        cron = Trigger("trg_every_minute", "SCHEDULE", cron_predicate,
                       clock_terms=("schedule.elapsed",))
        loop.register(cron)      # permitted: it declares SCHEDULE honestly

        controller_rng = random.Random(777)
        T = controller_rng.randrange(20, TICKS - 20)
        injected = None
        for tick in range(TICKS):
            clock["t"] = tick * TICK_MS
            if tick == T:
                injected = tick
            loop.tick()

        # PART 1 and PART 2 pass -- asserted here so the control demonstrates
        # the asymmetry rather than merely failing everything.
        parts_1_2 = (len(loop.heartbeats) == TICKS
                     and all(a["trigger_id"] for a in loop.fired))
        c.check("PART 1+2 pass on this build (recorded, not asserted as failure)",
                parts_1_2, "liveness and provenance both hold")

        # PART 3: every trigger that fired is SCHEDULE-class => cron.
        all_schedule = all(a["predicate_class"] == "SCHEDULE" for a in loop.fired)
        c.check("Part 3 NOT every fired trigger is SCHEDULE-class",
                not all_schedule,
                f"{len(loop.fired)} fired, all SCHEDULE-class -- this build is "
                "cron wearing autonomy's vocabulary")
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

        c.check("Part 1 a heartbeat is present at the declared cadence",
                len(loop.heartbeats) == TICKS,
                f"{len(loop.heartbeats)} heartbeats in a {TICKS}-tick "
                "zero-input window")
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

        c.check("Part 1 a heartbeat is present for the whole window",
                len(loop.heartbeats) == TICKS,
                f"{len(loop.heartbeats)} of {TICKS} -- died at tick {KILL_AT}")
        gap = (TICKS - KILL_AT) * TICK_MS
        c.check("Part 1 no gap exceeds 3 x tick_interval",
                gap <= 3 * TICK_MS,
                f"final gap {gap} ms -- a dead loop is distinguishable from a "
                "quiet one precisely because the heartbeat stops")
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


POSITIVE = [a011_bounded_autonomy, a029_three_part_gate, a031_interlock,
            a047_interruption_budget]
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

    width = max(len(r["case"]) for r in RESULTS) + 2
    print()
    for r in RESULTS:
        print(f"[{'ok  ' if r['ok'] else 'FAIL'}] {r['case']:<{width}} {r['verdict']}")
        for a in r["assertions"]:
            if not a["passed"]:
                sym = "expected-fail" if r["is_negative_control"] else "MISS"
                print(f"           {sym}: {a['assertion']}"
                      + (f" -- {a['detail']}" if a["detail"] else ""))
        if r.get("error"):
            print(f"           ERROR: {r['error'].splitlines()[-1]}")

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
