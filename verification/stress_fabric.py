#!/usr/bin/env python3
"""Property and stress harness for `DF-FABRIC-ADMIT` (SR-016, INV-NET-1/2/3).

WHY THIS EXISTS SEPARATELY FROM CI-055. `CI-055` asserts that the SHIPPED
contract is well-formed -- one contract, the one in the tree. That is a
different question from whether the DECISION FUNCTION is correct over the space
of contracts and nodes it will actually meet, and the second question is the one
that bites later: a fabric gains segments as nodes are enrolled, and the shipped
file is the single input least likely to be wrong.

So this runs `admit()` over randomised contracts, zones, ownerships and segment
bindings, and asserts properties that must hold for EVERY input rather than
outcomes chosen for particular ones.

THE PROPERTY THAT MATTERS MOST is non-elevation. `INV-NET-2` makes a segment a
ceiling, and the failure mode is not a crash -- it is a system that grants its
strongest trust over its least controlled path, which looks identical in a diff
and passes any test that merely checks "a ceiling was applied". `prop_never_
elevates` is the assertion that a `max` did not quietly become a `min`.

Deterministic by construction: the seed is fixed and printed, so a failure is
reproducible from the report alone.

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

from core.fabric import (TRUST_ZONE_RANK, Admission,  # noqa: E402
                         FabricContractViolation, admit, effective_trust_zone,
                         load_contract, segments)
from core.placement import NodeProfile, is_full_host  # noqa: E402

ZONES = ("Z0", "Z1", "Z2", "Z3")
OWNERSHIPS = ("vesper_owned", "user_owned")
AVAIL = ("always_on", "usually_on", "intermittent", "foreground_only", "on_demand")


def rand_contract(rng: random.Random) -> dict:
    """A random but STRUCTURALLY LEGAL fabric.

    `unlisted_segment_disposition` is never randomised. It is not a parameter of
    the fabric, it is the invariant -- `admit()` raises on any other value, and a
    generator that produced fail-open contracts would be exploring a space the
    system refuses to enter rather than the space it operates in.
    """
    n = rng.randint(1, 4)
    seg = {}
    for i in range(n):
        controlled = rng.random() < 0.4
        seg[f"seg_{i}"] = {
            # An uncontrolled segment may legally carry any ceiling in the
            # DECISION space; CI-055 is what forbids the strong ones in the
            # SHIPPED file. Keeping them reachable here is deliberate: it is the
            # only way prop_never_elevates gets to see a ceiling that would
            # elevate if the comparison were inverted.
            "trust_zone_ceiling": rng.choice(ZONES),
            "vesper_controlled": controlled,
            "admits_ownership": rng.choice(
                [[], ["vesper_owned"], ["user_owned"],
                 ["vesper_owned", "user_owned"]]),
            "carries_control_plane": controlled and rng.random() < 0.5,
        }
    return {
        "schema_version": 1,
        "attested": rng.random() < 0.5,
        "unlisted_segment_disposition": "UNREACHABLE",
        "segment": seg,
    }


def rand_case(rng: random.Random) -> tuple[str, str, str | None, dict]:
    c = rand_contract(rng)
    names = list(c["segment"]) + [None, "undeclared_segment"]
    return rng.choice(ZONES), rng.choice(OWNERSHIPS), rng.choice(names), c


# ----------------------------------------------------------------- properties
def prop_refusal_carries_nothing(a: Admission, *_)-> str | None:
    if a.admitted:
        return None
    if a.effective_trust_zone is not None:
        return "refused admission carries a trust zone -- refusal must not look like a weak yes"
    if a.administrable:
        return "refused node marked administrable (INV-NET-3)"
    return None


def prop_admission_names_a_zone(a: Admission, *_) -> str | None:
    if a.admitted and a.effective_trust_zone not in TRUST_ZONE_RANK:
        return f"admitted at {a.effective_trust_zone!r}, which is not a zone"
    return None


def prop_never_elevates(a: Admission, zone, own, seg_name, contract) -> str | None:
    """INV-NET-2. The effective zone is never STRONGER than either input."""
    if not a.admitted:
        return None
    seg = segments(contract)[seg_name]
    eff = TRUST_ZONE_RANK[a.effective_trust_zone]
    if eff < TRUST_ZONE_RANK[zone]:
        return (f"effective {a.effective_trust_zone} is STRONGER than the node's own "
                f"{zone} -- a segment elevated a node's trust")
    if eff < TRUST_ZONE_RANK[seg.trust_zone_ceiling]:
        return (f"effective {a.effective_trust_zone} is STRONGER than the segment "
                f"ceiling {seg.trust_zone_ceiling} -- the ceiling did not hold")
    return None


def prop_effective_is_exactly_the_weaker(a: Admission, zone, own, seg_name, contract) -> str | None:
    if not a.admitted:
        return None
    seg = segments(contract)[seg_name]
    expect = max(zone, seg.trust_zone_ceiling, key=lambda z: TRUST_ZONE_RANK[z])
    if a.effective_trust_zone != expect:
        return (f"effective {a.effective_trust_zone} != weaker_of({zone}, "
                f"{seg.trust_zone_ceiling}) = {expect}")
    return None


def prop_administrable_requires_both(a: Admission, zone, own, seg_name, contract) -> str | None:
    """INV-NET-3. Ownership AND a controlled path. Either alone is not enough."""
    if not a.administrable:
        return None
    if own != "vesper_owned":
        return f"a {own} node was marked administrable -- INV-NET-3 bounds administration to vesper_owned"
    if not segments(contract)[seg_name].vesper_controlled:
        return "administrable over a segment VESPER does not control -- administration without a vouched channel"
    return None


def prop_unattested_admits_no_controlled_segment(a: Admission, zone, own, seg_name, contract) -> str | None:
    if contract.get("attested"):
        return None
    if a.admitted and segments(contract)[seg_name].vesper_controlled:
        return "admitted onto a vesper_controlled segment while the fabric is unattested"
    return None


def prop_unknown_segment_never_admits(a: Admission, zone, own, seg_name, contract) -> str | None:
    if seg_name is None or seg_name not in contract["segment"]:
        if a.admitted:
            return f"admitted on segment {seg_name!r}, which is not declared -- INV-NET-1 is fail-closed"
    return None


def prop_admission_never_adds_host_eligibility(a: Admission, zone, own, seg_name, contract) -> str | None:
    """The fabric may only ever REMOVE full-host eligibility, never grant it.

    This is the cross-module property, and it is the reason the fabric is not
    ceremony: `core/placement.py` decides hosting from `trust_zone`, so if
    admission could raise a zone it could promote a node into HOST_ZONES over a
    path VESPER does not control.
    """
    if not a.admitted:
        return None
    before = NodeProfile(node_id="n", trust_zone=zone, availability_class="always_on")
    after = NodeProfile(node_id="n", trust_zone=a.effective_trust_zone,
                        availability_class="always_on")
    if is_full_host(after) and not is_full_host(before):
        return (f"admission promoted a non-host {zone} node to full host at "
                f"{a.effective_trust_zone}")
    return None


def prop_deterministic(a: Admission, zone, own, seg_name, contract) -> str | None:
    again = admit(zone, own, seg_name, contract)
    if (again.admitted, again.effective_trust_zone, again.administrable) != \
       (a.admitted, a.effective_trust_zone, a.administrable):
        return "two calls with identical inputs disagreed"
    return None


PROPERTIES = [prop_refusal_carries_nothing,
              prop_admission_names_a_zone,
              prop_never_elevates,
              prop_effective_is_exactly_the_weaker,
              prop_administrable_requires_both,
              prop_unattested_admits_no_controlled_segment,
              prop_unknown_segment_never_admits,
              prop_admission_never_adds_host_eligibility,
              prop_deterministic]


def run_properties(rng: random.Random, iterations: int) -> dict:
    failures, outcomes = [], {}
    for _ in range(iterations):
        zone, own, seg_name, contract = rand_case(rng)
        a = admit(zone, own, seg_name, contract)
        key = "ADMIT" if a.admitted else a.reason.split(":")[0].split(" --")[0][:34]
        outcomes[key] = outcomes.get(key, 0) + 1
        for prop in PROPERTIES:
            detail = prop(a, zone, own, seg_name, contract)
            if detail:
                failures.append({"property": prop.__name__, "detail": detail,
                                 "zone": zone, "ownership": own,
                                 "segment": seg_name, "contract": contract})
    return {"failures": failures, "outcomes": outcomes}


def run_ceiling_monotonicity(rng: random.Random, trials: int) -> dict:
    """Weakening a segment's ceiling must never strengthen the effective zone.

    A direct test of the comparison's direction that does not depend on any
    contract being well-formed.
    """
    breaks = []
    for _ in range(trials):
        node = rng.choice(ZONES)
        a, b = rng.choice(ZONES), rng.choice(ZONES)
        if TRUST_ZONE_RANK[a] > TRUST_ZONE_RANK[b]:
            a, b = b, a                      # a is the STRONGER ceiling
        ea, eb = effective_trust_zone(node, a), effective_trust_zone(node, b)
        if TRUST_ZONE_RANK[eb] < TRUST_ZONE_RANK[ea]:
            breaks.append({"node": node, "stronger_ceiling": a,
                           "weaker_ceiling": b, "got": [ea, eb]})
    return {"trials": trials, "breaks": breaks}


def run_shipped_contract_check() -> dict:
    """The shipped fabric, exercised rather than parsed.

    CI-055 reads the file. This ASKS IT QUESTIONS -- the distinction the corpus
    keeps making between a declaration and an executed run.
    """
    c = load_contract()
    segs = segments(c)
    findings = []
    for name, seg in segs.items():
        for zone in ZONES:
            for own in OWNERSHIPS:
                a = admit(zone, own, name, c)
                if a.admitted and TRUST_ZONE_RANK[a.effective_trust_zone] < TRUST_ZONE_RANK[seg.trust_zone_ceiling]:
                    findings.append(f"{name}/{zone}/{own}: elevated above ceiling")
                if a.admitted and seg.vesper_controlled and not c.get("attested"):
                    findings.append(f"{name}/{zone}/{own}: admitted on unattested controlled segment")
    host_capable = []
    for name, seg in segs.items():
        for zone in ZONES:
            a = admit(zone, "vesper_owned", name, c)
            if a.admitted and is_full_host(NodeProfile("n", a.effective_trust_zone, "always_on")):
                host_capable.append(f"{name}@{zone}")
    return {"segments": len(segs), "attested": c.get("attested"),
            "findings": findings, "host_capable_today": host_capable}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=20_000)
    ap.add_argument("--mono-trials", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=20260819)
    ap.add_argument("--out")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    t0 = time.time()
    print(f"seed {args.seed} -- every result below is reproducible from it\n")

    props = run_properties(rng, args.iterations)
    mono = run_ceiling_monotonicity(rng, args.mono_trials)
    shipped = run_shipped_contract_check()

    total = args.iterations * len(PROPERTIES)
    print(f"  properties      {args.iterations:,} random fabrics, "
          f"{len(PROPERTIES)} properties each = {total:,} assertions")
    for k, v in sorted(props["outcomes"].items()):
        print(f"      {k:36} {v:>7,}")
    print(f"      failures                             {len(props['failures']):>7,}")
    for f in props["failures"][:5]:
        print(f"        [{f['property']}] {f['detail']}")

    print(f"\n  ceiling monotonicity   {mono['trials']:,} pairs")
    print(f"      elevations under a weaker ceiling    {len(mono['breaks']):>7,}")

    print(f"\n  shipped contract, exercised")
    print(f"      segments {shipped['segments']}, attested={shipped['attested']}")
    print(f"      findings                             {len(shipped['findings']):>7,}")
    for f in shipped["findings"][:5]:
        print(f"        {f}")
    print(f"      full-host-capable admissions today: "
          f"{shipped['host_capable_today'] or 'NONE -- fail-closed, no attested fabric'}")

    # A run that refused everything would satisfy every property while testing
    # nothing. The generator must be shown to reach admission AND each refusal.
    reached = {k for k, v in props["outcomes"].items() if v > 0}
    covered = "ADMIT" in reached and len(reached) >= 4
    print(f"\n  branch coverage  {len(reached)} distinct outcomes: {sorted(reached)}")

    ok = (not props["failures"] and not mono["breaks"]
          and not shipped["findings"] and covered)
    if not covered:
        print("      INSUFFICIENT: the generator did not reach both admission and refusal")

    dt = time.time() - t0
    print(f"\n  FABRIC STRESS: {'PASS' if ok else 'FAIL'}   ({dt:.1f}s)")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"seed": args.seed, "iterations": args.iterations,
             "assertions": total, "properties": props, "monotonicity": mono,
             "shipped": shipped, "ok": ok}, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
