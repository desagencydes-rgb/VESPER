#!/usr/bin/env python3
"""A-029 — the literal endurance window, on a real clock.

WHAT THIS ADDS THAT THE COMPRESSED RUN CANNOT. `run_f5_acceptance.py` runs
A-029's three parts over a simulated clock in three seconds. It is the right
thing to run in CI and it proves the protocol holds. It cannot, by
construction, surface any of:

  * a slow memory leak that only matters after several thousand cycles
  * handle or thread growth that exhausts a limit at hour 19
  * scheduling drift, because there is no scheduler -- the compressed driver
    calls `tick()` in a `for` loop and the clock is whatever it says it is
  * a loop that dies quietly, because until now NOTHING in the runtime could
    emit `autonomy.loop_stalled`. A-029 Part 1 asserts that event never fires;
    an absence that cannot become a presence measures nothing. `AutonomyRunner`
    is the watchdog that makes the assertion real, and B1 below is the build
    that proves the watchdog works.

THE ASSERTIONS ARE NOT REDEFINED HERE. Parts 1, 2 and 3 come from
`a029_protocol`, the same module the compressed driver uses. This file owns HOW
the window is produced -- real threads, real sleep, real sampling -- and owns
the resource criteria, which only exist at this timescale.

DECLARED CADENCE. A-029 says heartbeats appear "at the declared cadence" and
INV-AUTO-1 fixes the tolerance at 3x tick_interval, but nothing in `contracts/`
or `spec/` declares a production cadence. This harness declares **60 s** and
records it in the artifact, so the figure is a stated choice rather than a
number inherited from a default argument.

THE DRAW OF T. Three draws, one per third of the window, from
`secrets.SystemRandom` -- OS entropy, not a seeded PRNG. T lives in the
controller thread's closure and is never written to the world, the bus, the
store or any object the loop holds. The loop cannot read it, and stratifying
into thirds is what lets three independent draws share one window without
overlapping; that is a deviation from "uniform over the whole window" and is
recorded in the artifact rather than glossed.

  python verification/run_a029_endurance.py --self-test        # ~3 min, MUST pass first
  python verification/run_a029_endurance.py --launch --hours 24
  python verification/run_a029_endurance.py --status
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import statistics
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a029_protocol import (ATTRIBUTE, INJECTED_VALUE, SUBJECT,  # noqa: E402
                           check_part1, check_part2, check_part3,
                           part3_run_record, temperature_trigger)
from harness import Case, print_results  # noqa: E402
from verify_a029_from_log import judge_from_log  # noqa: E402

from core.autonomy import (AutonomyLoop, AutonomyRunner,  # noqa: E402
                           PredicateEvaluator, Trigger)
from core.config import RuntimeConfig  # noqa: E402
from core.hlc import HybridLogicalClock  # noqa: E402
from core.supervisor import Supervisor  # noqa: E402
from core.world import Observation, WorldModel  # noqa: E402

try:
    import psutil
except ImportError:                                   # pragma: no cover
    psutil = None

# --------------------------------------------------------------------------
# Declared run configuration
# --------------------------------------------------------------------------

CADENCE_S = 60.0                 # the declared tick_interval
DEFAULT_HOURS = 24.0
COUNT_TOLERANCE = 0.02           # real time jitters; simulated time does not
FACT_TTL_TICKS = 3               # the injected fact expires, so the next draw
                                 # starts from UNKNOWN rather than a hot world

# Resource criteria. Expressed as growth between the first and last quarter of
# the run, with an absolute floor so ordinary allocator noise on a small
# baseline is not read as a leak, and a relative term so a large baseline is
# not given a free pass.
RSS_FLOOR_BYTES = 8 * 1024 * 1024
RSS_FRACTION = 0.05
HANDLE_FLOOR = 16
HANDLE_FRACTION = 0.10
THREAD_GROWTH_MAX = 2

STATUS_PATH = REPO / "docs" / "planning" / "spike-results" / "A-029-endurance-live.json"


# ==========================================================================
# Sampling — what turns 24 elapsed hours into evidence
# ==========================================================================

class ResourceSampler(threading.Thread):
    """Samples the process, not the harness's opinion of the process.

    Without this the long run proves only that the machine did not catch fire.
    The samples are what a leak, a handle exhaustion or a drifting cadence
    actually look like from outside.
    """

    def __init__(self, loop: AutonomyLoop, runner: AutonomyRunner,
                 data_dir: Path, *, interval_s: float,
                 on_sample=None) -> None:
        super().__init__(daemon=True, name="vesper-a029-sampler")
        self._loop, self._runner, self._dir = loop, runner, data_dir
        self._interval = interval_s
        self._stop = threading.Event()
        self._on_sample = on_sample
        self._proc = psutil.Process() if psutil else None
        self.samples: list[dict] = []
        self.t0 = time.monotonic()

    def _db_bytes(self) -> int:
        try:
            return sum(p.stat().st_size for p in self._dir.rglob("*")
                       if p.is_file())
        except OSError:
            return -1

    def sample(self) -> dict:
        s = {"at_s": round(time.monotonic() - self.t0, 2),
             # Wall AND monotonic, because their divergence is the signal. A
             # suspended machine stops the monotonic clock and does not stop
             # wall time, so the gap between them is how a nap is told apart
             # from a stall.
             "wall_s": round(time.time(), 2),
             "ticks": self._loop.ticks,
             "heartbeats": len(self._loop.heartbeats),
             "fired": len(self._loop.fired),
             "noops": len(self._loop.noops),
             "late_ticks": self._runner.late_ticks,
             "max_lateness_s": self._runner.max_lateness_s,
             "stall_episodes": self._runner.stall_episodes,
             "db_bytes": self._db_bytes()}
        if self._proc is not None:
            with self._proc.oneshot():
                s["rss_bytes"] = self._proc.memory_info().rss
                s["threads"] = self._proc.num_threads()
                try:
                    s["handles"] = self._proc.num_handles()      # Windows
                except AttributeError:
                    s["handles"] = self._proc.num_fds()          # POSIX
        self.samples.append(s)
        if self._on_sample:
            self._on_sample(s)
        return s

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.sample()
            except Exception:                       # noqa: BLE001
                pass                                # a sampler must never kill a run

    def stop(self) -> None:
        self._stop.set()


def _quarter_means(values: list[float]) -> tuple[float, float]:
    """Mean of the first quarter and of the last quarter.

    Quarters rather than endpoints: a single first and last reading would make
    the verdict a function of two samples, and one GC pause at the wrong moment
    would decide it.
    """
    n = len(values)
    if n < 4:
        return (statistics.fmean(values), statistics.fmean(values)) if values else (0.0, 0.0)
    q = max(1, n // 4)
    return statistics.fmean(values[:q]), statistics.fmean(values[-q:])


def detect_void(samples: list[dict], tick_interval_s: float) -> dict | None:
    """VOID vs FAILED — AT-03's distinction, which this harness owed.

    AT-03: "If the external ingress is unavailable during the run, the run is
    **void** (harness defect), not failed (product defect). A void run is
    re-run, never counted."

    The environmental failure this run is actually exposed to is the machine
    sleeping, hibernating or being suspended for an update. Any of those
    produce exactly the symptoms of a dead loop -- a gap beyond 3x
    tick_interval, a stall episode, late ticks -- and reporting that as FAIL
    would say VESPER broke when the desktop napped.

    The discriminator is mechanical, in the same spirit as the anti-cron probe:
    a suspended machine stops the monotonic clock and does not stop wall time.
    Divergence between the two across one sampling interval is the environment,
    not the product. A genuinely stalled loop diverges by NEITHER -- both
    clocks keep running while nothing ticks, which is why this cannot launder a
    real stall into a void.
    """
    for a, b in zip(samples, samples[1:]):
        if "wall_s" not in a or "wall_s" not in b:
            continue
        mono = b["at_s"] - a["at_s"]
        wall = b["wall_s"] - a["wall_s"]
        drift = wall - mono
        if drift > 3 * tick_interval_s:
            return {
                "void": True,
                "reason": "suspension",
                "at_s": b["at_s"],
                "wall_gap_s": round(wall, 1),
                "monotonic_gap_s": round(mono, 1),
                "unaccounted_s": round(drift, 1),
                "note": ("wall time advanced " f"{drift:.0f} s more than the "
                         "monotonic clock across one sampling interval, which "
                         "means the machine was suspended. AT-03: void "
                         "(environment), not failed (product). Re-run; never "
                         "count it either way."),
            }
    return None


def check_resources(c: Case, samples: list[dict]) -> dict:
    """The criteria that only exist because the window is long.

    Reported alongside the verdict: `db_bytes` growth is NOT a failure. The
    event log is append-only by design, so growth there is the system working;
    what matters is the rate, which is reported so it can be extrapolated
    rather than asserted against a number nobody has justified.
    """
    detail: dict = {"samples": len(samples)}
    c.check("E0 the run produced enough samples to judge",
            len(samples) >= 8, f"{len(samples)} samples")
    if not samples:
        return detail

    if "rss_bytes" not in samples[0]:
        # NOT MEASURED is recorded as a failed assertion, never as a pass.
        # "psutil is missing" must not be a way to obtain a green endurance run.
        c.check("E1 process RSS was measured", False,
                "psutil is not installed, so the leak criterion could not be "
                "evaluated. The run is NOT CLAIMED for resource stability.")
        return detail

    rss = [s["rss_bytes"] for s in samples]
    first, last = _quarter_means(rss)
    budget = max(RSS_FLOOR_BYTES, first * RSS_FRACTION)
    detail["rss"] = {"first_quarter_mean": round(first), "last_quarter_mean": round(last),
                     "growth": round(last - first), "budget": round(budget),
                     "peak": max(rss)}
    c.check("E1 RSS does not grow across the window",
            (last - first) <= budget,
            f"{(last - first) / 1e6:+.1f} MB from a {first / 1e6:.1f} MB baseline, "
            f"budget {budget / 1e6:.1f} MB")

    handles = [s["handles"] for s in samples if s.get("handles") is not None]
    if handles:
        hf, hl = _quarter_means([float(h) for h in handles])
        hbudget = max(HANDLE_FLOOR, hf * HANDLE_FRACTION)
        detail["handles"] = {"first_quarter_mean": round(hf, 1),
                             "last_quarter_mean": round(hl, 1),
                             "budget": round(hbudget, 1), "peak": max(handles)}
        c.check("E2 open handles do not grow across the window",
                (hl - hf) <= hbudget,
                f"{hl - hf:+.1f} handles from {hf:.1f}, budget {hbudget:.1f}")

    threads = [s["threads"] for s in samples if s.get("threads") is not None]
    if threads:
        # Quarter means, not min..max. A run's first samples are taken while
        # the supervisor, driver, watchdog, sampler and controller threads are
        # still coming up, so min..max reads that startup ramp as instability
        # and fails a healthy run for starting correctly.
        tf, tl = _quarter_means([float(t) for t in threads])
        detail["threads"] = {"first_quarter_mean": round(tf, 1),
                             "last_quarter_mean": round(tl, 1),
                             "min": min(threads), "max": max(threads)}
        c.check("E3 the thread count is stable",
                (tl - tf) <= THREAD_GROWTH_MAX,
                f"{tf:.1f} -> {tl:.1f} (observed {min(threads)}..{max(threads)})")

    late = samples[-1]["late_ticks"]
    detail["scheduling"] = {"late_ticks": late,
                            "max_lateness_s": samples[-1]["max_lateness_s"],
                            "ticks": samples[-1]["ticks"]}
    c.check("E4 no tick ran more than one interval late",
            late == 0, f"{late} late ticks, worst "
                       f"{samples[-1]['max_lateness_s']:.2f} s")

    db = [s["db_bytes"] for s in samples if s.get("db_bytes", -1) >= 0]
    if len(db) >= 2 and samples[-1]["at_s"] > 0:
        rate = (db[-1] - db[0]) / samples[-1]["at_s"] * 3600.0
        detail["store"] = {"bytes": db[-1], "growth_bytes_per_hour": round(rate),
                           "projected_30d_bytes": round(db[-1] + rate * 24 * 30),
                           "note": ("append-only by design: growth here is the "
                                    "system working. Reported for extrapolation, "
                                    "not asserted against a budget.")}
    return detail


# ==========================================================================
# The run
# ==========================================================================

class EnduranceRun:
    """One window: a real supervisor, a real driver, an external controller."""

    def __init__(self, root: Path, *, node: str, tick_interval_s: float,
                 window_s: float, sample_every_s: float | None = None,
                 build: str = "healthy") -> None:
        self.root, self.node = root, node
        self.tick_interval_s = tick_interval_s
        self.window_s = window_s
        self.sample_every_s = sample_every_s or tick_interval_s
        self.build = build
        self.injections: list[dict] = []
        self.started_wall = 0.0
        self._teardown = threading.Event()
        self._leak_ballast: list = []

    # -- the deliberately broken builds live here, one branch each ----------

    def _register_triggers(self, loop: AutonomyLoop) -> set:
        if self.build == "cron":
            # B2: every trigger SCHEDULE-class. Passes parts 1 and 2, fails 3.
            loop.register(Trigger("trg_every_minute", "SCHEDULE",
                                  lambda s: True,
                                  clock_terms=("schedule.elapsed",)))
            loop.register(Trigger("trg_nightly_report", "SCHEDULE",
                                  lambda s: False,
                                  clock_terms=("schedule.elapsed",)))
            return {"trg_every_minute", "trg_nightly_report"}

        trig = temperature_trigger()
        if self.build == "hang":
            # B1: the loop wedges partway through the window. Not an exception
            # -- a hang, which is how a loop actually dies in the field, and
            # the only failure the watchdog can catch that the loop cannot
            # report about itself.
            inner = trig.predicate
            hang_after = self.window_s * 0.4

            def hanging(s, _inner=inner):
                if (time.monotonic() - self._t0) > hang_after:
                    self._teardown.wait(self.window_s * 2)
                return _inner(s)

            trig = Trigger(trig.trigger_id, trig.predicate_class, hanging,
                           state_terms=trig.state_terms)
        loop.register(trig)
        return {trig.trigger_id}

    # -- the external controller -------------------------------------------

    def _controller(self, world: WorldModel, hlc: HybridLogicalClock,
                    loop: AutonomyLoop, stop: threading.Event) -> None:
        """Draws T, waits, writes ONE observation through the world model.

        T is a local. It is never published, never stored, never passed to any
        object the loop holds. The loop's only way to learn that T has arrived
        is to observe that the world changed -- which is the entire content of
        Part 3.
        """
        rng = secrets.SystemRandom()
        third = self.window_s / 3.0
        draws = sorted(rng.uniform(i * third + self.tick_interval_s * 2,
                                   (i + 1) * third - self.tick_interval_s * 3)
                       for i in range(3))
        for T in draws:
            if stop.wait(max(0.0, T - (time.monotonic() - self._t0))):
                return
            ticks_before = loop.ticks
            wall_ms = int(time.time() * 1000)
            world.apply(Observation(
                SUBJECT, ATTRIBUTE, INJECTED_VALUE, hlc.now(),
                source="synthetic_observer", trust_class="verified_local",
                valid_until_ms=wall_ms + int(FACT_TTL_TICKS
                                             * self.tick_interval_s * 1000)))
            self.injections.append({"T_s": round(T, 3),
                                    "injected_after_tick": ticks_before,
                                    "wall_ms": wall_ms})

    # -- drive --------------------------------------------------------------

    def run(self, *, on_sample=None) -> dict:
        cfg = RuntimeConfig(node_id=self.node, data_dir=self.root / self.node)
        sup = Supervisor(cfg).start()
        self._t0 = time.monotonic()
        self.started_wall = time.time()
        try:
            world = WorldModel(sup.bus, sup.clock,
                               now_ms=lambda: int(time.time() * 1000))
            ev = PredicateEvaluator(sup.bus, world)
            loop = AutonomyLoop(sup.bus, world, ev,
                                tick_interval_s=self.tick_interval_s,
                                now_ms=lambda: int(time.time() * 1000))
            registered = self._register_triggers(loop)
            hlc = HybridLogicalClock("external_observer")

            if self.build == "leak":
                # B3: a subscriber that retains a megabyte per heartbeat.
                #
                # The FIRST attempt at this control leaked inside the trigger's
                # predicate and the control PASSED -- because `evaluate()`
                # short-circuits to False on an UNKNOWN term BEFORE calling the
                # predicate, so on a window where the fact is usually UNKNOWN
                # the predicate barely ran. That is the 2026-08-15 report's
                # pattern #3 exactly: a control written from the same mental
                # model as the thing it checks. It is recorded here rather than
                # quietly corrected.
                #
                # A retaining subscriber leaks per TICK, runs regardless of any
                # predicate's verdict, and is what an accumulating consumer
                # actually looks like in the field.
                def _retain(e) -> None:
                    self._leak_ballast.append(bytearray(1024 * 1024))

                sup.bus.subscribe("autonomy.heartbeat", _retain,
                                  name="leak_ballast",
                                  idempotency_key=lambda e: e.event_id)

            runner = AutonomyRunner(sup.bus, loop,
                                    tick_interval_s=self.tick_interval_s).start()
            sampler = ResourceSampler(loop, runner, cfg.data_dir,
                                      interval_s=self.sample_every_s,
                                      on_sample=on_sample)
            sampler.start()
            stop = threading.Event()
            ctl = threading.Thread(target=self._controller, daemon=True,
                                   name="vesper-a029-controller",
                                   args=(world, hlc, loop, stop))
            ctl.start()

            stop.wait(self.window_s)
            stop.set()
            elapsed = time.monotonic() - self._t0
            sampler.sample()                 # one final sample at the very end
            sampler.stop()
            self._teardown.set()             # release a hung predicate, if any
            runner.stop()

            events = {k: len([r for r in sup.store.read("log") if r.kind == k])
                      for k in ("autonomy.loop_stalled",
                                "autonomy.model_call_in_decision_path",
                                "autonomy.cycle_error", "autonomy.heartbeat")}
            return {
                "build": self.build,
                "started_wall": self.started_wall,
                "elapsed_s": elapsed,
                "tick_interval_s": self.tick_interval_s,
                "heartbeats": list(loop.heartbeats),
                "fired": list(loop.fired),
                "noops": list(loop.noops),
                "registered": registered,
                "replay": loop.replay_predicate,
                "injections": list(self.injections),
                "samples": sampler.samples,
                "events": events,
                "runner": runner.status(),
                "window_start_ms": int(self.started_wall * 1000),
            }
        finally:
            self._teardown.set()
            sup.stop()


def judge(c: Case, r: dict) -> dict:
    """Apply the shared A-029 parts, then the resource criteria."""
    check_part1(c, heartbeats=r["heartbeats"],
                tick_interval_ms=r["tick_interval_s"] * 1000,
                window_ms=r["elapsed_s"] * 1000,
                window_start_ms=r["window_start_ms"],
                stalled_events=r["events"]["autonomy.loop_stalled"],
                count_tolerance=COUNT_TOLERANCE)
    check_part2(c, actions=r["fired"], registered_ids=r["registered"],
                replay=r["replay"], noops=r["noops"])

    runs = []
    for inj in r["injections"]:
        after = [a for a in r["fired"] if a["tick"] > inj["injected_after_tick"]]
        runs.append(part3_run_record(inj["T_s"], inj["injected_after_tick"],
                                     after[0] if after else None))
    check_part3(c, runs=runs,
                model_call_events=r["events"]["autonomy.model_call_in_decision_path"])
    return check_resources(c, r["samples"])


# ==========================================================================
# The self-test — four builds, three of which must fail
# ==========================================================================

SELF_TEST_WINDOW_S = 24.0
SELF_TEST_TICK_S = 0.25

BROKEN = [
    ("hang", "B1 silent death: the loop wedges at 40% of the window",
     "Part 1 fails AND autonomy.loop_stalled fires. This is the build that "
     "proves the watchdog works; before AutonomyRunner existed, nothing could "
     "emit that event and Part 1's third assertion was vacuous."),
    ("cron", "B2 pure cron: every trigger SCHEDULE-class",
     "Parts 1 and 2 pass, Part 3 fails -- the asymmetry AT-03 requires."),
    ("leak", "B3 a correct build that retains a megabyte per evaluation",
     "Every A-029 part passes and E1 fails. This is the only control that "
     "tests the reason for running 24 hours at all."),
]


def _cross_check(node: str, root: Path, expect_ok: bool, results: list) -> None:
    """The log-derived verdict must AGREE with the harness's own.

    Two instruments looking at the same run from different evidence: the
    harness from its in-memory lists, `verify_a029_from_log` from the durable
    log. Agreement is the point -- a disagreement means one of them is reading
    something that is not what happened, and finding that out on a 24-hour run
    is finding it out a day late.
    """
    c = Case(f"A-029-LOG-XCHECK-{node}",
             "the log-derived verdict agrees with the harness's")
    try:
        rec, _ev = judge_from_log(root / node, SELF_TEST_TICK_S,
                                  window_s=SELF_TEST_WINDOW_S,
                                  case_id=f"from-log-{node}")
        c.check(f"log-derived verdict is {'PASS' if expect_ok else 'FAIL'}, "
                "matching the harness",
                rec["ok"] == expect_ok,
                f"log says {'PASS' if rec['ok'] else 'FAIL'}; harness says "
                f"{'PASS' if expect_ok else 'FAIL'}")
        c.finish(sink=results)
    except Exception:
        c.finish(error=traceback.format_exc(limit=6), sink=results)


def _void_detector_cases(results: list) -> None:
    """The void detector, both directions.

    A discriminator that only ever says "void" would let every failed run be
    excused as an environmental one, so the stall case is asserted as loudly as
    the suspension case.
    """
    tick = 60.0
    healthy = [{"at_s": i * 60.0, "wall_s": 1000.0 + i * 60.0} for i in range(10)]
    # A nap: wall time jumps an hour, the monotonic clock does not.
    napped = [dict(s) for s in healthy]
    for s in napped[5:]:
        s["wall_s"] += 3600.0
    # A genuine stall: the loop stops, but BOTH clocks keep running normally.
    stalled = [dict(s) for s in healthy]

    c = Case("A-029-VOID-DETECTOR", "void vs failed, both directions")
    c.check("a suspended machine is detected as VOID",
            (detect_void(napped, tick) or {}).get("reason") == "suspension")
    c.check("a healthy run is NOT void", detect_void(healthy, tick) is None)
    c.check("a genuine stall is NOT laundered into a void -- both clocks ran",
            detect_void(stalled, tick) is None)
    c.finish(sink=results)
    print(f"  [{'ok' if results[-1]['ok'] else 'FAIL'}] void detector: "
          "suspension is void, a stall is not")


def self_test(root: Path) -> list:
    results: list = []
    print(f"  self-test: {SELF_TEST_WINDOW_S:.0f}s per build at a "
          f"{SELF_TEST_TICK_S}s cadence, 4 builds\n")

    c = Case("A-029-RT-HEALTHY", "Real-time driver, healthy build")
    try:
        r = EnduranceRun(root, node="rt_ok", tick_interval_s=SELF_TEST_TICK_S,
                         window_s=SELF_TEST_WINDOW_S).run()
        judge(c, r)
        c.finish(sink=results)
    except Exception:
        c.finish(error=traceback.format_exc(limit=6), sink=results)
    print(f"  [{'ok' if results[-1]['ok'] else 'FAIL'}] healthy build")
    _cross_check("rt_ok", root, True, results)
    _void_detector_cases(results)

    for build, title, why in BROKEN:
        c = Case(f"A-029-RT-{build.upper()}", title, control=True)
        try:
            r = EnduranceRun(root, node=f"rt_{build}",
                             tick_interval_s=SELF_TEST_TICK_S,
                             window_s=SELF_TEST_WINDOW_S, build=build).run()
            judge(c, r)
            if build == "hang":
                # AT-03: "C4 -- silent death ... autonomy.loop_stalled fires".
                # Asserted POSITIVELY so that a watchdog which never fires is a
                # control failure rather than a quiet pass.
                c.check("the watchdog emitted autonomy.loop_stalled",
                        r["events"]["autonomy.loop_stalled"] >= 1,
                        f"{r['events']['autonomy.loop_stalled']} episodes")
            c.finish(sink=results)
        except Exception:
            c.finish(error=traceback.format_exc(limit=6), sink=results)
        rec = results[-1]
        print(f"  [{'ok' if rec['ok'] else 'FAIL'}] {build}: {why}")
        # The log verifier must also see this build as broken. The leak build
        # is the exception and is stated rather than skipped: RSS never reaches
        # the event log, so a log-only verdict CANNOT see a leak, and it is
        # right for it to say PASS there. That is a real limit of log-derived
        # evidence, not an agreement failure.
        _cross_check(f"rt_{build}", root, build == "leak", results)
        if build == "hang" and rec["ok"]:
            stalls = [a for a in rec["assertions"]
                      if "loop_stalled" in a["assertion"] and a["passed"]]
            print(f"        watchdog fired: {bool(stalls)}")
    return results


# ==========================================================================
# CLI
# ==========================================================================

def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)      # atomic: --status never reads a half-written file


def launch(args) -> int:
    window_s = args.hours * 3600.0
    root = Path(args.data_dir) if args.data_dir else Path(
        tempfile.mkdtemp(prefix="vesper-a029-"))
    root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    print(f"  A-029 endurance run: {args.hours} h at a {args.tick}s cadence")
    print(f"  data dir : {root}")
    print(f"  status   : {STATUS_PATH}")
    print(f"  expected : ~{int(window_s / args.tick)} heartbeats, "
          f"finishing {time.strftime('%Y-%m-%d %H:%M', time.localtime(started + window_s))}")

    run = EnduranceRun(root, node="a029", tick_interval_s=args.tick,
                       window_s=window_s,
                       sample_every_s=max(args.tick, 60.0))

    def on_sample(s: dict) -> None:
        _write_status(STATUS_PATH, {
            "schema_version": 1, "state": "RUNNING",
            "gate": "A-029-endurance", "build": "production",
            "declared_tick_interval_s": args.tick,
            "window_hours": args.hours,
            "started_wall": started,
            "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S",
                                         time.localtime(started)),
            "progress": round(s["at_s"] / window_s, 4),
            "latest_sample": s,
            "samples": run_samples_tail(s),
        })

    tail: list = []

    def run_samples_tail(s: dict) -> list:
        tail.append(s)
        return tail[-120:]

    r = run.run(on_sample=on_sample)

    # THE DURABLE LOG IS THE PRIMARY EVIDENCE. A-029's run configuration says
    # "full event log retained", and the log is what the system recorded rather
    # than what the harness remembers doing. The in-memory verdict is kept as a
    # CROSS-CHECK: two instruments on different evidence, and a disagreement is
    # a failure of the run rather than a detail to reconcile afterwards. This
    # ordering was owed -- until now Part 1 was judged from the loop's own list.
    log_rec, log_ev = judge_from_log(root / "a029", args.tick,
                                     window_s=r["elapsed_s"],
                                     case_id="A-029-FROM-LOG")

    c = Case("A-029-ENDURANCE", f"{args.hours} h zero-input window, real clock")
    detail = judge(c, r)
    mem_ok = all(a["passed"] for a in c.assertions)
    c.check("the log-derived verdict and the in-memory verdict AGREE",
            log_rec["ok"] == mem_ok,
            f"log says {'PASS' if log_rec['ok'] else 'FAIL'}, in-memory says "
            f"{'PASS' if mem_ok else 'FAIL'}. They read different evidence about "
            "the same run, so a disagreement means one of them is not reading "
            "what happened.")
    c.check("the primary (log-derived) verdict passes", log_rec["ok"],
            "; ".join(a["assertion"] for a in log_rec["assertions"]
                      if not a["passed"]) or "")
    rec = c.finish()
    print_results([rec, log_rec])

    voided = detect_void(r["samples"], args.tick)
    if voided:
        print("\n  RUN VOID -- NOT FAILED. " + voided["note"])

    payload = {
        "schema_version": 1,
        "state": "VOID" if voided else "COMPLETE",
        "void": voided,
        "gate": "A-029-endurance",
        "passed": None if voided else rec["ok"],
        "declared_tick_interval_s": args.tick,
        "window_hours": args.hours,
        "elapsed_s": r["elapsed_s"],
        "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "finished_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "heartbeats": len(r["heartbeats"]),
        "fired": len(r["fired"]),
        "noops": len(r["noops"]),
        "injections": r["injections"],
        "events": r["events"],
        "runner": r["runner"],
        "resources": detail,
        "samples": r["samples"],
        "result": rec,
        "primary_evidence": "durable event log",
        "log_derived_result": log_rec,
        "log_derived_counts": {
            "heartbeats": len(log_ev["heartbeats"]),
            "firings": len(log_ev["fired"]),
            "noops": len(log_ev["noops"]),
            "injections": len(log_ev["injections"]),
        },
        "not_claimed": NOT_CLAIMED,
    }
    out = Path(args.out) if args.out else STATUS_PATH
    _write_status(out, payload)
    print(f"\n  wrote {out}")
    if voided:
        print("  A-029 ENDURANCE: VOID (environment suspended; re-run)")
        return 2
    print(f"  A-029 ENDURANCE: {'PASS' if rec['ok'] else 'FAIL'}")
    return 0 if rec["ok"] else 1


NOT_CLAIMED = {
    "T isolation": (
        "T is drawn from secrets.SystemRandom in a controller THREAD and never "
        "written to the world, bus, store or any object the loop holds. It is "
        "not drawn in a separate PROCESS, because no cross-process observation "
        "ingress exists yet; building one for a test would invent production "
        "surface. Isolation is therefore scope-level, exactly as in the "
        "compressed run -- what this run adds is elapsed time, not stronger T "
        "isolation."),
    "draw distribution": (
        "Three draws, one uniform within each third of the window, rather than "
        "three uniform over the whole window. Stratification is what lets three "
        "independent draws share one window without overlapping."),
    "A-012 / A-041": "alarm hardware cases remain blocked on devices.",
    "resource evidence is in-memory only": (
        "The A-029 parts are judged from the durable log, but the resource "
        "criteria (E1-E4) cannot be: RSS, handles and thread counts never reach "
        "the event log, so they come from the sampler's own record. A leak is "
        "therefore attested by one instrument rather than two. Telemetry would "
        "close this and is not in scope for the endurance harness."),
}


def status(_args) -> int:
    if not STATUS_PATH.exists():
        print(f"  no run recorded at {STATUS_PATH}")
        return 1
    d = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    s = d.get("latest_sample") or {}
    print(f"  state    : {d.get('state')}")
    print(f"  started  : {d.get('started_iso')}")
    if d.get("state") == "RUNNING":
        print(f"  progress : {d.get('progress', 0) * 100:.1f}%  "
              f"({s.get('at_s', 0) / 3600:.2f} h of {d.get('window_hours')} h)")
        print(f"  ticks    : {s.get('ticks')}  fired {s.get('fired')}  "
              f"noops {s.get('noops')}")
        print(f"  rss      : {s.get('rss_bytes', 0) / 1e6:.1f} MB   "
              f"handles {s.get('handles')}  threads {s.get('threads')}")
        print(f"  stalls   : {s.get('stall_episodes')}   late ticks "
              f"{s.get('late_ticks')}")
    else:
        print(f"  passed   : {d.get('passed')}")
        print(f"  heartbeats {d.get('heartbeats')}  fired {d.get('fired')}  "
              f"noops {d.get('noops')}")
        res = d.get("resources", {})
        if "rss" in res:
            print(f"  rss growth {res['rss']['growth'] / 1e6:+.1f} MB "
                  f"(budget {res['rss']['budget'] / 1e6:.1f} MB)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="the red test: four builds, three of which MUST fail")
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--hours", type=float, default=DEFAULT_HOURS)
    ap.add_argument("--tick", type=float, default=CADENCE_S)
    ap.add_argument("--data-dir")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.status:
        return status(args)
    if args.launch:
        return launch(args)

    root = Path(tempfile.mkdtemp(prefix="vesper-a029-selftest-"))
    try:
        results = self_test(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print_results(results)
    pos = [r for r in results if not r["is_negative_control"]]
    ctl = [r for r in results if r["is_negative_control"]]
    pos_ok, ctl_ok = sum(r["ok"] for r in pos), sum(r["ok"] for r in ctl)
    ok = pos_ok == len(pos) and ctl_ok == len(ctl)
    print(f"\n  healthy builds    {pos_ok}/{len(pos)} passed")
    print(f"  broken builds     {ctl_ok}/{len(ctl)} failed as required")
    print(f"\n  HARNESS SELF-TEST: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  DO NOT LAUNCH THE 24 h RUN. A harness that cannot fail on a "
              "broken build cannot pass on a good one.")
    else:
        print("  the harness is safe to launch: "
              "python verification/run_a029_endurance.py --launch --hours 24")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
