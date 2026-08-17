#!/usr/bin/env python3
"""F4 (partial) — world model, privacy routing, node enrollment.

SCOPE, STATED FIRST BECAUSE IT IS THE HONEST PART. F4's full gate is A-008,
A-010, A-028, A-039, A-042. Three of those need physical sensors that do not
exist on this fabric yet:

  A-008  perception with provenance -- needs a camera and a handwritten note
  A-028  media evidence pipeline   -- needs video ingest
  A-039  sensor lifecycle          -- needs a driveable capture indicator, and
                                      4 of its 5 assertions are about hardware

This runs **A-010 (both parts) and A-042**, which are pure software, plus the
world-model half of A-033 that F0 deferred. The perception half of F4 is BLOCKED
ON HARDWARE, not on engineering, and is not claimed.

IT ALSO CLOSES TWO F0 SCOPE LIMITS. F0's report recorded A-033.3 (facts expiring
to UNKNOWN) and A-033.4 (conflict emission) as needing the world model. The
world model now exists, so they run here.

ONE NEGATIVE CONTROL IS NAMED BY THE SPEC:

  A-010  "A build routing by 'largest available display' must FAIL every
          owner+unknown and low-confidence cell."
"""

from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.config import RuntimeConfig  # noqa: E402
from core.enrollment import (AdmissionRefused,  # noqa: E402
                             EnrollmentRegistry, Z2BoundViolation)
from core.hlc import HybridLogicalClock  # noqa: E402
from core.privacy import (PRIVACY_CLASSES, SURFACE_PRIVACY_ORDER,  # noqa: E402
                          WITHHOLD, PrivacyRouter)
from core.supervisor import Supervisor  # noqa: E402
from core.world import (CONFLICTED, UNKNOWN, UNKNOWN_PERSON,  # noqa: E402
                        Observation, WorldModel)

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


# ===========================================================================
# A-033.3 / A-033.4 — the two F0 deferred to the world model
# ===========================================================================

def a033_3_expiry_to_unknown(tmp: Path) -> None:
    c = Case("A-033.3", "Partitioned 2 h: every expired fact reads UNKNOWN")
    try:
        sup = _sup(tmp, "n4331")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        hlc = HybridLogicalClock("node-b", wall_ms=lambda: 1000 + clock["t"])

        for i, (subj, attr, val) in enumerate([
                ("kitchen", "occupancy", "occupied"),
                ("owner", "location", "kitchen"),
                ("front_door", "state", "closed")]):
            w.apply(Observation(subj, attr, val, hlc.now(), source="node-b",
                                valid_until_ms=60_000))
        c.check("facts read their value while fresh",
                w.read("kitchen", "occupancy") == "occupied")

        # Partition node B for two simulated hours, then flush.
        clock["t"] = 2 * 60 * 60 * 1000
        reads = {k: w.read(*k) for k in [("kitchen", "occupancy"),
                                         ("owner", "location"),
                                         ("front_door", "state")]}
        c.check("every fact past valid_until reads UNKNOWN",
                all(v == UNKNOWN for v in reads.values()), str(reads))
        c.check("NONE reads its last known value",
                not any(v in ("occupied", "kitchen", "closed")
                        for v in reads.values()), str(reads))
        detail = w.read_detail("owner", "location")
        c.check("the reason names expiry, not absence",
                "expired" in detail.get("reason", ""), detail.get("reason", ""))
        expired = w.sweep_expired()
        c.check("the sweep reports all three", len(expired) == 3, str(len(expired)))
        c.check("expiry is emitted, not silent",
                len(_events(sup, "world.facts_expired")) == 1)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a033_4_conflict(tmp: Path) -> None:
    c = Case("A-033.4", "Two valid contradictory sources: no value changes")
    try:
        sup = _sup(tmp, "n4334")
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: 0)
        a = HybridLogicalClock("src-a", wall_ms=lambda: 1000)
        b = HybridLogicalClock("src-b", wall_ms=lambda: 2000)

        w.apply(Observation("owner", "location", "kitchen", a.now(), source="cam-a"))
        before = w.read("owner", "location")
        c.check("first observation applies", before == "kitchen", str(before))

        r = w.apply(Observation("owner", "location", "study", b.now(),
                                source="cam-b"))
        c.check("the contradicting write is NOT applied", not r["applied"],
                str(r))
        c.check("NO attribute value changed",
                w.read_detail("owner", "location")["source"] == "cam-a",
                w.read_detail("owner", "location")["source"])
        c.check("the reader receives CONFLICTED",
                w.read("owner", "location") == CONFLICTED,
                str(w.read("owner", "location")))
        ev = _events(sup, "world.conflict")
        c.check("world.conflict emitted", len(ev) == 1)
        c.check("both sources named in the conflict",
                bool(ev) and sorted(ev[0]["payload"]["sources"])
                == ["cam-a", "cam-b"], str(ev[0]["payload"]["sources"]) if ev else "")
        c.check("no winner was picked",
                bool(ev) and "NONE" in ev[0]["payload"]["resolution"])
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-010 Part A — environment model
# ===========================================================================

def a010_part_a(tmp: Path) -> None:
    c = Case("A-010-A", "Topological spatial model; stale entries expire")
    try:
        sup = _sup(tmp, "n410a")
        clock = {"t": 0}
        w = WorldModel(sup.bus, sup.clock, now_ms=lambda: clock["t"])
        hlc = HybridLogicalClock("node-a", wall_ms=lambda: 500)

        w.relate("kitchen", "adjacent_to", "hallway")
        w.relate("hallway", "connects_to", "study")
        c.check("spatial relations are topological",
                ("adjacent_to", "kitchen") in w.related("hallway"),
                str(w.related("hallway")))
        c.check("adjacency is symmetric without coordinates",
                ("adjacent_to", "hallway") in w.related("kitchen"))

        # INV-WORLD-2: a metric relation is refused outright.
        refused = False
        try:
            w.relate("kitchen", "3.2_metres_from", "study")
        except ValueError:
            refused = True
        c.check("a metric relation is refused (INV-WORLD-2)", refused)

        # Observations carry confidence and freshness; stale expires to UNKNOWN.
        w.apply(Observation("printer", "health", "ok", hlc.now(), source="probe",
                            confidence=0.9, valid_until_ms=1000))
        c.check("observation carries confidence",
                w.read_detail("printer", "health")["confidence"] == 0.9)
        clock["t"] = 5000
        c.check("a stale entry expires to UNKNOWN",
                w.read("printer", "health") == UNKNOWN)

        # INV-WORLD-1: an unknown person is never resolved to the owner.
        c.check("a weak match resolves to unknown_person, not the owner",
                w.identify_person([("owner", 0.72), ("guest", 0.31)])
                == UNKNOWN_PERSON)
        c.check("an ambiguous strong match also resolves to unknown_person",
                w.identify_person([("owner", 0.97), ("sibling", 0.96)])
                == UNKNOWN_PERSON)
        c.check("a single strong match does resolve",
                w.identify_person([("owner", 0.99)]) == "owner")
        c.check("the non-resolution is emitted",
                len(_events(sup, "world.person_unresolved")) == 2)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-010 Part B — the full routing cross-product
# ===========================================================================

PERSON_SETS = {
    "none": (),
    "owner": ("owner",),
    "owner+known": ("owner", "known_guest"),
    "owner+unknown": ("owner", UNKNOWN_PERSON),
    "unknown_only": (UNKNOWN_PERSON,),
}
CONFIDENCES = ("high", "low", UNKNOWN)
AVAILABLE = ("private_earpiece", "personal_handheld", "shared_display",
             "public_display")


def a010_part_b(tmp: Path) -> None:
    c = Case("A-010-B", "Full cross-product: every ambiguous cell resolves private")
    try:
        sup = _sup(tmp, "n410b")
        r = PrivacyRouter(sup.bus)
        cells = list(itertools.product(PRIVACY_CLASSES, PERSON_SETS.items(),
                                       CONFIDENCES))
        c.check("the fixture is the full cross-product",
                len(cells) == 3 * 5 * 3, f"{len(cells)} cells")

        violations = []
        ambiguous_count = 0
        for pc, (pname, persons), conf in cells:
            d = r.route(privacy_class=pc, persons=persons,
                        location_confidence=conf, available=AVAILABLE,
                        subject=f"{pc}/{pname}/{conf}")
            is_amb = UNKNOWN_PERSON in persons or conf in ("low", UNKNOWN)
            if is_amb:
                ambiguous_count += 1
                # THE assertion: most private available, or WITHHOLD. Never
                # a shared or public surface.
                if d.surface in ("shared_display", "public_display"):
                    violations.append((pc, pname, conf, d.surface))
        c.check("every ambiguous cell avoids shared and public surfaces",
                not violations, str(violations[:4]))
        # Derived, not hardcoded: 3 privacy classes x 5 person-sets x 3
        # confidences = 45 cells. Only (owner | owner+known | none) x high is
        # unambiguous -- 3 x 3 = 9 -- so 36 cells are ambiguous. A hardcoded
        # count is a number to re-derive by hand every time the fixture grows.
        expected_unambiguous = len(PRIVACY_CLASSES) * 3    # 3 clean person-sets
        expected_ambiguous = len(cells) - expected_unambiguous
        c.check("the cross-product's ambiguous cells are the majority",
                ambiguous_count == expected_ambiguous,
                f"{ambiguous_count} ambiguous of {len(cells)}, "
                f"expected {expected_ambiguous}")

        # Spot-checks that pin the specific behaviour.
        d1 = r.route(privacy_class="private", persons=("owner", UNKNOWN_PERSON),
                     location_confidence="high", available=AVAILABLE)
        c.check("private content with a stranger present goes to the earpiece",
                d1.surface == "private_earpiece", d1.surface)
        d2 = r.route(privacy_class="private", persons=("owner", UNKNOWN_PERSON),
                     location_confidence="high",
                     available=("shared_display", "public_display"))
        c.check("with no private surface available it WITHHOLDS",
                d2.surface == WITHHOLD, d2.surface)
        d3 = r.route(privacy_class="public", persons=("owner",),
                     location_confidence=UNKNOWN, available=AVAILABLE)
        c.check("UNKNOWN confidence is treated as ambiguous, not guessed",
                d3.ambiguous and d3.surface != "public_display", d3.surface)
        d4 = r.route(privacy_class="public", persons=("owner",),
                     location_confidence="high", available=AVAILABLE)
        c.check("the unambiguous public case still uses the public display",
                d4.surface == "public_display", d4.surface)

        # INV-PRIV-2: non-exportable, refused rather than filtered.
        refused = False
        try:
            r.export_inference("mood", "owner", destination="cloud-analytics")
        except PermissionError:
            refused = True
        c.check("physiological/mood inference export is REFUSED (INV-PRIV-2)",
                refused)
        c.check("the refusal is recorded",
                len(_events(sup, "privacy.export_refused")) == 1)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-042 — node enrollment admission and Z2 bounds
# ===========================================================================

def a042_enrollment(tmp: Path) -> None:
    c = Case("A-042", "Admission is a gate; Z2 is a real bound")
    try:
        sup = _sup(tmp, "n442")
        clock = {"t": 0}
        reg = EnrollmentRegistry(sup.bus, now_ms=lambda: clock["t"])

        # 1. DISCOVERED -> TRUSTED is unreachable directly.
        reg.discover("node-x")
        unreachable = False
        try:
            reg.transition("node-x", "TRUSTED")
        except AdmissionRefused:
            unreachable = True
        c.check("1. DISCOVERED -> TRUSTED is unreachable directly", unreachable)

        # 2. capability floor passed, security baseline FAILED => Z2.
        n = reg.admit("node-x", capability_floor_passed=True,
                      security_baseline_passed=False,
                      measured_tokens_per_sec=85.3)
        c.check("2. capable but insecure lands in LIMITED_TRUST",
                n.state == "LIMITED_TRUST", n.state)
        c.check("2. and its trust zone is Z2", n.trust_zone == "Z2", n.trust_zone)

        # 3. a Z2 node is refused all three, separately.
        refusals = {}
        for action in ("hold_state", "issue_command", "receive_secret"):
            try:
                reg.check_z2_bound("node-x", action)
                refusals[action] = False
            except Z2BoundViolation:
                refusals[action] = True
        c.check("3. a Z2 node may not hold state, issue commands, or receive "
                "secrets", all(refusals.values()), str(refusals))
        c.check("3. each refusal is recorded",
                len(_events(sup, "security.z2_bound_enforced")) == 3)

        # 4. a node with no MEASURED profile is never routed to.
        reg.discover("node-y")
        ny = reg.admit("node-y", capability_floor_passed=True,
                       security_baseline_passed=True,
                       measured_tokens_per_sec=None)
        c.check("4. trusted but unmeasured is NOT routable",
                ny.state == "TRUSTED" and not ny.routable(), str(ny.to_dict()))
        reg.discover("node-z")
        reg.admit("node-z", capability_floor_passed=True,
                  security_baseline_passed=True, measured_tokens_per_sec=46.6,
                  reattestation_due_ms=10_000)
        c.check("4. trusted AND measured is routable",
                reg.routable_nodes() == ["node-z"], str(reg.routable_nodes()))

        # 5. re-attestation expiry demotes and emits a degradation.
        clock["t"] = 20_000
        still = reg.check_reattestation("node-z")
        c.check("5. expiry demotes TRUSTED -> LIMITED_TRUST",
                not still and reg.get("node-z").state == "LIMITED_TRUST",
                reg.get("node-z").state)
        c.check("5. and emits a capability degradation",
                len(_events(sup, "capability.degraded")) == 1)
        c.check("5. the demoted node is no longer routable",
                reg.routable_nodes() == [], str(reg.routable_nodes()))
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# NEGATIVE CONTROL — named by A-010
# ===========================================================================

def control_largest_display(tmp: Path) -> None:
    """MANDATORY (A-010). Routing by "largest available display" must FAIL every
    owner+unknown and low-confidence cell."""
    c = Case("A-010-CONTROL", "Routing by largest available display",
             control=True)
    try:
        sup = _sup(tmp, "nctl410")

        def route_by_size(privacy_class, persons, confidence, available):
            """THE DEFECT: capability-first routing. Reads as helpful, and puts
            private content on the living-room screen with a guest present."""
            for surface in reversed(SURFACE_PRIVACY_ORDER):   # largest first
                if surface in available:
                    return surface
            return WITHHOLD

        violations = []
        for pc, (pname, persons), conf in itertools.product(
                PRIVACY_CLASSES, PERSON_SETS.items(), CONFIDENCES):
            surface = route_by_size(pc, persons, conf, AVAILABLE)
            if UNKNOWN_PERSON in persons or conf in ("low", UNKNOWN):
                if surface in ("shared_display", "public_display"):
                    violations.append((pc, pname, conf, surface))
        c.check("every ambiguous cell avoids shared and public surfaces",
                not violations, f"{len(violations)} ambiguous cells routed public")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


POSITIVE = [a033_3_expiry_to_unknown, a033_4_conflict, a010_part_a,
            a010_part_b, a042_enrollment]
CONTROLS = [control_largest_display]

NOT_CLAIMED = {
    "A-008": ("perception with provenance -- needs a camera and a physical "
              "handwritten note. BLOCKED ON HARDWARE, not on engineering."),
    "A-028": "media evidence pipeline -- needs video ingest. Blocked on hardware.",
    "A-039": ("sensor lifecycle and privacy -- 4 of its 5 assertions are about "
              "physical capture indicators and an OS-level off path. Blocked on "
              "hardware. INV-PRIV-2's non-exportability is covered under A-010-B."),
    "A-042.6": ("role separation names specific devices. The registry enforces "
                "the PROFILE rule (INV-TRUST-2, in core/devices.py, gated under "
                "F2); binding it to particular handsets is an enrollment-time "
                "act, not a test."),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="vesper-f4-"))
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
    print("\n  NOT CLAIMED -- blocked on hardware, not on engineering:")
    for k, why in NOT_CLAIMED.items():
        print(f"    {k}: {why}")
    print(f"\n  F4 WORLD/PRIVACY/ENROLLMENT: {'PASS' if gate else 'FAIL'}   "
          f"({time.time() - t0:.1f}s)")
    print("  F4 as a whole is NOT complete -- the perception half needs sensors.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1, "gate": "F4-world-privacy-enrollment",
            "acceptance_tests_claimed": ["A-010", "A-042", "A-033.3", "A-033.4"],
            "acceptance_tests_not_claimed": NOT_CLAIMED,
            "f4_complete": False,
            "closes_f0_scope_limits": ["A-033.3", "A-033.4"],
            "passed": gate, "positive_passed": pos_ok,
            "positive_total": len(pos),
            "controls_failed_as_required": ctl_ok, "controls_total": len(ctl),
            "results": RESULTS,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
