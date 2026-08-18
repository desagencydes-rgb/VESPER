#!/usr/bin/env python3
"""Property and stress harness for `DF-PLACE` / `DF-SURVIVAL-PROFILE`.

WHY THIS EXISTS SEPARATELY FROM THE ACCEPTANCE GATE. `run_f6_acceptance.py`
asserts the nine cases `A-048` names, on fixtures chosen to exercise them. That
is necessary and it is not sufficient: every fixture in it was written by the
same person who wrote the module, on the same afternoon, and a fixture chosen
to demonstrate a behaviour is the worst possible instrument for discovering the
behaviour is wrong somewhere else. The scoring defect found on the first run of
that gate -- an additive scalar that made a 20x throughput improvement read as
a 9% gain -- passed four of the nine cases before it was caught by the fifth.

So this runs the same decision function over RANDOMISED fabrics and asserts
properties that must hold for every input, not outcomes chosen for particular
ones. A property that survives ten thousand fabrics is a different kind of
evidence from a case that passes on one.

Deterministic by construction: the seed is fixed and printed, so a failure is
reproducible from the report alone. `Math.random`-style irreproducibility in a
verification tool is how a flake becomes folklore.

Stdlib only. Python >= 3.11.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.placement import (EnterSurvival, Hysteresis, Keep,  # noqa: E402
                            NodeProfile, Placement, Relocate,
                            SurvivalImpossible, TRUST_ZONE_RANK, is_full_host,
                            load_capability_requirements, planned_map,
                            planned_assignment_violations, survival_profile,
                            unplaceable)

ZONES = ("Z0", "Z1", "Z2", "Z3")
AVAIL = ("always_on", "usually_on", "intermittent", "foreground_only", "on_demand")
NETS = ("wired", "wifi", "cellular", "intermittent")
ACCELS = ("none", "vulkan", "cuda", "metal", "rocm", "npu")


class Failure(Exception):
    """A property did not hold. Carries the fabric that broke it."""


def rand_node(rng: random.Random, node_id: str) -> NodeProfile:
    measured = rng.random() < 0.7
    accel = rng.choice(ACCELS)
    return NodeProfile(
        node_id=node_id,
        trust_zone=rng.choice(ZONES),
        availability_class=rng.choice(AVAIL),
        ram_gb=round(rng.uniform(0.25, 128.0), 2),
        storage_gb=round(rng.uniform(1.0, 2000.0), 1),
        accelerator=accel,
        accelerator_memory_gb=(round(rng.uniform(0.5, 48.0), 1)
                               if accel != "none" and rng.random() < 0.9 else None),
        network_class=rng.choice(NETS),
        sustained_tokens_per_sec=(round(rng.uniform(0.1, 500.0), 2)
                                  if measured else None),
        measured=measured,
        survival_capable=rng.random() < 0.6,
        reachable=rng.random() < 0.85,
        degraded=rng.random() < 0.2,
    )


def rand_fabric(rng: random.Random, n: int) -> dict[str, NodeProfile]:
    return {f"n{i}": rand_node(rng, f"n{i}") for i in range(n)}


# ---------------------------------------------------------------------------
# The properties. Each takes a fabric and a decision, and raises on violation.
# ---------------------------------------------------------------------------

def prop_never_relocates_to_unreachable(fabric, current, d, reqs, inputs) -> None:
    if isinstance(d, (Relocate, EnterSurvival)):
        target = d.target if isinstance(d, Relocate) else d.node
        if not fabric[target].reachable:
            raise Failure(f"chose unreachable node {target}")


def prop_never_hosts_on_z2_or_worse(fabric, current, d, reqs, inputs) -> None:
    """INV-TRUST-1. A Z2/Z3 node may not hold state, so it may never be a
    relocation target, and may only be a survival host if it can carry the
    core -- which the zone requirements of the core capabilities forbid."""
    if isinstance(d, Relocate):
        z = fabric[d.target].trust_zone
        if TRUST_ZONE_RANK[z] > TRUST_ZONE_RANK["Z1"]:
            raise Failure(f"relocated onto {z} node {d.target}")
    if isinstance(d, EnterSurvival):
        if not d.profile.core_complete:
            raise Failure(f"entered survival on {d.node} with an incomplete core")


def prop_survival_only_without_full_host(fabric, current, d, reqs, inputs) -> None:
    """INV-PLACE-3: survival begins only when no FULL host is reachable."""
    live_hosts = [n for n, p in fabric.items() if p.reachable and is_full_host(p)]
    if isinstance(d, (EnterSurvival, SurvivalImpossible)) and live_hosts:
        raise Failure(f"survival path taken while full hosts {live_hosts} were live")


def prop_relocation_target_is_a_full_host(fabric, current, d, reqs, inputs) -> None:
    if isinstance(d, Relocate) and not is_full_host(fabric[d.target]):
        raise Failure(f"relocated onto non-full-host {d.target}")


def prop_never_relocates_to_current(fabric, current, d, reqs, inputs) -> None:
    if isinstance(d, Relocate) and d.target == current:
        raise Failure("relocated to the node it is already on")


def prop_every_capability_accounted(fabric, current, d, reqs, inputs) -> None:
    """Nothing vanishes: selected + degraded == the whole declared set.

    RB-022 in its strongest form. A capability that is neither running nor
    reported as degraded is a silent capability loss, which is the failure mode
    that makes a degraded system indistinguishable from a broken one.
    """
    prof = getattr(d, "profile", None)
    if prof is None:
        return
    seen = set(prof.capabilities) | {x.capability for x in prof.degradations}
    if seen != set(reqs):
        raise Failure(f"capabilities unaccounted for: {set(reqs) - seen}")
    if set(prof.capabilities) & {x.capability for x in prof.degradations}:
        raise Failure("a capability is both running and degraded")


def prop_every_degradation_has_a_reason(fabric, current, d, reqs, inputs) -> None:
    prof = getattr(d, "profile", None)
    if prof is None:
        return
    for x in prof.degradations:
        if not x.reason.strip():
            raise Failure(f"degradation {x.capability} carries no reason")


def prop_decision_is_deterministic(fabric, current, d, reqs, inputs) -> None:
    """Same inputs, same decision.

    THE FIRST VERSION OF THIS PROPERTY WAS THE BUG. It re-ran `decide` without
    passing `hysteresis` or `pressure`, so the replay used the default
    `since_last_move_s = inf` and sailed through a dwell gate the original call
    had been stopped by -- 87 "non-deterministic: Keep then Relocate" reports,
    every one of them the harness contradicting itself rather than the module
    misbehaving. Worth keeping the story: a property that does not hold its
    inputs fixed is not testing determinism, it is testing that two different
    questions have the same answer.
    """
    again = Placement(requirements=reqs).decide(
        reachable=fabric, current=current,
        hysteresis=inputs["hysteresis"], pressure=inputs["pressure"])
    if type(again) is not type(d):
        raise Failure(f"non-deterministic: {type(d).__name__} then "
                      f"{type(again).__name__}")
    if getattr(again, "target", None) != getattr(d, "target", None):
        raise Failure("non-deterministic target")


# Every property takes (fabric, current, decision, requirements, inputs).
# The last argument is what the decision was actually asked, and exists because
# omitting it is precisely how the determinism property first went wrong.
PROPERTIES = [prop_never_relocates_to_unreachable,
              prop_never_hosts_on_z2_or_worse,
              prop_survival_only_without_full_host,
              prop_relocation_target_is_a_full_host,
              prop_never_relocates_to_current,
              prop_every_capability_accounted,
              prop_every_degradation_has_a_reason,
              prop_decision_is_deterministic]


def run_properties(rng: random.Random, iterations: int, reqs) -> dict:
    counts = {"Keep": 0, "Relocate": 0, "EnterSurvival": 0, "SurvivalImpossible": 0}
    failures: list[dict] = []
    p = Placement(requirements=reqs)
    for i in range(iterations):
        fabric = rand_fabric(rng, rng.randint(1, 6))
        current = rng.choice([None, *fabric])
        inputs = {"hysteresis": Hysteresis(since_last_move_s=rng.choice(
                      [0.0, 5.0, 300.0, 1200.0, float("inf")])),
                  "pressure": rng.choice([0.0, 0.25, 0.5, 0.9])}
        try:
            d = p.decide(reachable=fabric, current=current, **inputs)
        except Exception as exc:  # a raise is itself a property failure
            failures.append({"iteration": i, "property": "decide() raised",
                             "detail": f"{type(exc).__name__}: {exc}",
                             "fabric": {k: v.node_id for k, v in fabric.items()}})
            continue
        counts[type(d).__name__] += 1
        for prop in PROPERTIES:
            try:
                prop(fabric, current, d, reqs, inputs)
            except Failure as f:
                failures.append({
                    "iteration": i, "property": prop.__name__, "detail": str(f),
                    "current": current,
                    "fabric": {k: {"zone": v.trust_zone,
                                   "avail": v.availability_class,
                                   "reachable": v.reachable,
                                   "degraded": v.degraded,
                                   "survival_capable": v.survival_capable}
                               for k, v in fabric.items()}})
    return {"iterations": iterations, "decisions": counts, "failures": failures}


def run_flap_stress(rng: random.Random, trials: int, hours: float) -> dict:
    """Long-run flap stress: comparable nodes, jitter inside the gain threshold.

    `A-048.3` runs one simulated hour on one pair. This runs many pairs over
    many hours, because a damping bug that needs a particular phase alignment
    to show up will not appear in a single deterministic sweep.
    """
    worst = 0
    worst_detail = ""
    total_moves = 0
    samples = int(hours * 3600 / 30)
    for t in range(trials):
        base = rng.uniform(5.0, 200.0)
        jitter = base * rng.uniform(0.01, 0.10)   # inside the 25% threshold
        p = Placement()
        current, moves, clock, last = "a", 0, 0.0, -1e9
        for i in range(samples):
            clock += 30.0
            swing = jitter if i % 2 == 0 else -jitter
            a = NodeProfile("a", "Z0", "always_on", ram_gb=8, storage_gb=100,
                            network_class="wired",
                            sustained_tokens_per_sec=base + swing,
                            measured=True, survival_capable=True)
            b = NodeProfile("b", "Z0", "always_on", ram_gb=8, storage_gb=100,
                            network_class="wired",
                            sustained_tokens_per_sec=base - swing,
                            measured=True, survival_capable=True)
            d = p.decide(reachable={"a": a, "b": b}, current=current,
                         hysteresis=Hysteresis(since_last_move_s=clock - last))
            if isinstance(d, Relocate):
                current, moves, last = d.target, moves + 1, clock
        total_moves += moves
        if moves > worst:
            worst, worst_detail = moves, f"base={base:.1f} jitter={jitter:.2f}"
    return {"trials": trials, "simulated_hours_each": hours,
            "total_relocations": total_moves, "worst_trial": worst,
            "worst_detail": worst_detail}


def run_survival_monotonicity(rng: random.Random, trials: int, reqs) -> dict:
    """A strictly better node must sustain a superset of capabilities.

    Not asserted anywhere in `A-048` and it should be: if adding RAM, storage
    or throughput could REMOVE a capability, `DF-SURVIVAL-PROFILE` would not be
    a "maximum sustainable" function at all, and 48.5 would be measuring noise.
    """
    breaks = []
    for t in range(trials):
        lean = NodeProfile(f"lean{t}", "Z0", "always_on",
                           ram_gb=rng.uniform(0.5, 8.0),
                           storage_gb=rng.uniform(1.0, 100.0),
                           accelerator="none",
                           network_class="wifi",
                           sustained_tokens_per_sec=rng.uniform(1.0, 50.0),
                           measured=True, survival_capable=True)
        rich = NodeProfile(f"rich{t}", "Z0", "always_on",
                           ram_gb=lean.ram_gb * rng.uniform(1.5, 8.0),
                           storage_gb=lean.storage_gb * rng.uniform(1.5, 8.0),
                           accelerator="vulkan",
                           accelerator_memory_gb=rng.uniform(4.0, 48.0),
                           network_class="wired",
                           sustained_tokens_per_sec=(lean.sustained_tokens_per_sec
                                                     * rng.uniform(1.5, 8.0)),
                           measured=True, survival_capable=True)
        a = set(survival_profile(lean, reqs).capabilities)
        b = set(survival_profile(rich, reqs).capabilities)
        if not a <= b:
            breaks.append({"trial": t, "lost": sorted(a - b),
                           "lean_ram": lean.ram_gb, "rich_ram": rich.ram_gb})
    return {"trials": trials, "monotonicity_breaks": breaks}


def _used(profile, reqs) -> tuple[float, float]:
    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
    ram = sum(num(reqs[c].get("min_memory_gb")) for c in profile.capabilities)
    sto = sum(num(reqs[c].get("min_storage_gb")) for c in profile.capabilities)
    return ram, sto


def run_pressure_monotonicity(rng: random.Random, trials: int, reqs) -> dict:
    """What rising pressure may and may not do.

    THE FIRST VERSION OF THIS ASSERTED THE WRONG THING -- "capabilities under
    higher pressure must be a subset of those under lower pressure" -- and it
    found a real defect anyway, which is worth separating out. The defect was
    that the survival CORE was being filled greedily, so on one node at
    pressure 0.75 a core member fell out for want of storage, and at 0.95 three
    others stopped fitting, released their budget, and it came back. A core
    that reappears as conditions worsen is not a core, and
    `DF-SURVIVAL-PROFILE` reserves it in one step precisely to prevent that.

    With the core fixed, strict subsetting is still too strong for the NON-core
    set, and correctly so: dropping one expensive capability can free room for
    a cheaper lower-value one, and taking it is exactly "the maximum it can
    get". Keeping the strict form would have left a property that happens to
    hold on 500 samples and is not actually true -- a flake waiting for a
    bigger run. So the two properties that must genuinely hold are asserted
    instead: the core never recovers as pressure rises, and total committed
    resource never rises.
    """
    breaks = []
    for t in range(trials):
        node = NodeProfile(f"p{t}", "Z0", "always_on",
                           ram_gb=rng.uniform(1.0, 64.0),
                           storage_gb=rng.uniform(5.0, 500.0),
                           accelerator="vulkan",
                           accelerator_memory_gb=rng.uniform(2.0, 24.0),
                           network_class="wired",
                           sustained_tokens_per_sec=rng.uniform(5.0, 200.0),
                           measured=True, survival_capable=True)
        prev_core: bool | None = None
        prev_used: tuple[float, float] | None = None
        for pressure in (0.0, 0.25, 0.5, 0.75, 0.95):
            prof = survival_profile(node, reqs, pressure)
            if prev_core is False and prof.core_complete:
                breaks.append({"trial": t, "pressure": pressure,
                               "why": "core_complete recovered as pressure rose"})
            used = _used(prof, reqs)
            if prev_used is not None and (used[0] > prev_used[0] + 1e-9
                                          or used[1] > prev_used[1] + 1e-9):
                breaks.append({"trial": t, "pressure": pressure,
                               "why": f"committed resource rose {prev_used} -> {used}"})
            prev_core, prev_used = prof.core_complete, used
    return {"trials": trials, "pressure_monotonicity_breaks": breaks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=20_000)
    ap.add_argument("--flap-trials", type=int, default=200)
    ap.add_argument("--flap-hours", type=float, default=4.0)
    ap.add_argument("--mono-trials", type=int, default=2_000)
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--out")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    reqs = load_capability_requirements()
    t0 = time.time()

    print(f"seed {args.seed} -- every result below is reproducible from it\n")

    props = run_properties(rng, args.iterations, reqs)
    flap = run_flap_stress(rng, args.flap_trials, args.flap_hours)
    mono = run_survival_monotonicity(rng, args.mono_trials, reqs)
    press = run_pressure_monotonicity(rng, args.mono_trials // 4, reqs)

    print(f"  properties      {args.iterations} random fabrics, "
          f"{len(PROPERTIES)} properties each "
          f"= {args.iterations * len(PROPERTIES):,} assertions")
    for k, v in props["decisions"].items():
        print(f"      {k:20} {v:>7,}")
    print(f"      failures             {len(props['failures']):>7,}")
    for f in props["failures"][:5]:
        print(f"        [{f['property']}] {f['detail']}")

    print(f"\n  flap stress     {flap['trials']} pairs x "
          f"{flap['simulated_hours_each']} h, jitter inside the gain threshold")
    print(f"      total relocations    {flap['total_relocations']:>7,}")
    print(f"      worst single trial   {flap['worst_trial']:>7,}"
          + (f"  ({flap['worst_detail']})" if flap["worst_detail"] else ""))

    print(f"\n  survival monotonicity  {mono['trials']} strictly-better pairs")
    print(f"      capability regressions {len(mono['monotonicity_breaks']):>5,}")

    print(f"\n  pressure monotonicity  {press['trials']} nodes x 5 pressures")
    print(f"      core recoveries / resource rises "
          f"{len(press['pressure_monotonicity_breaks']):>5,}")

    ok = (not props["failures"]
          and flap["total_relocations"] == 0
          and not mono["monotonicity_breaks"]
          and not press["pressure_monotonicity_breaks"])

    # A run in which nothing ever relocated would satisfy every property above
    # while testing nothing. The generator must be shown to reach every branch.
    reached = {k for k, v in props["decisions"].items() if v > 0}
    covered = reached >= {"Keep", "Relocate", "EnterSurvival", "SurvivalImpossible"}
    print(f"\n  branch coverage  {sorted(reached)}")
    if not covered:
        print("      NOT COVERED -- the generator never reached "
              f"{sorted({'Keep','Relocate','EnterSurvival','SurvivalImpossible'} - reached)}; "
              "a pass here would be vacuous")

    print(f"\n  PLACEMENT STRESS: {'PASS' if ok and covered else 'FAIL'}   "
          f"({time.time() - t0:.1f}s)")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1, "tool": "stress_placement", "seed": args.seed,
            "passed": bool(ok and covered), "branch_coverage": sorted(reached),
            "properties": props, "flap_stress": flap,
            "survival_monotonicity": mono, "pressure_monotonicity": press,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if (ok and covered) else 1


if __name__ == "__main__":
    raise SystemExit(main())
