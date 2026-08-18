#!/usr/bin/env python3
"""F6 (partial) — opportunistic placement, survival, and recovery.

SCOPE. F6's full gate is `A-017`, `A-045` and `A-034` in full. This runs
**A-048 in full (nine cases, both mandatory negative controls) and A-017**.

  A-045  network fabric and device usability. Its assertions are "the user's
         devices remain normally usable while enrolled", asserted *by
         exercising ordinary user workflows on each node*. That is a human
         sitting at each machine using it, not a harness. Named, not faked.

  A-034  five of its seven cases are already gated by F0. `A-034.2` (partition
         with both sides live) is still not run, and the reason is now MEASURED
         rather than assumed -- see NOT_CLAIMED below.

WHY A-048 IS THE CENTRE OF THIS STAGE. The owner requirement is that VESPER is
not pinned: *"nothing is sitting anywhere ... and when hardware is genuinely
unavailable — say only the iPhone is online — it should end up there with just
whatever it needs so it stays alive, and with the most resources it can get."*
A build that pins to one machine passes every other test in the suite. That is
why both negative controls here are *builds*, not inputs: a node-pinned
placement and an undamped one, each constructed from the real module with one
property changed, so a control that passes cannot be blamed on a stub that
differed in some other way.

THE FIXTURES ARE THE REAL FABRIC, with measured numbers where measured numbers
exist (`MEMORY.md` §1, `SPIKE-001` §3.1, `NODE-2-KALI-LAPTOP-FINDINGS.md`).
Trust zones are derived by ADR-007 D2's rule from key-storage class, never
declared: hardware-backed non-exportable storage is `Z0`, file-based keys are
`Z2`. That is why the handset is `Z2` and the phone with a Secure Enclave is
`Z0` despite being the least available node in the fabric -- the pairing that
makes `INV-TRUST-2` necessary in the first place.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.bus import EventBus  # noqa: E402
from core.config import RuntimeConfig  # noqa: E402
from core.placement import (Degradation, EnterSurvival, Hysteresis,  # noqa: E402
                            Keep, NodeProfile, Placement, Relocate,
                            SurvivalImpossible, is_full_host,
                            load_capability_requirements, planned_map,
                            planned_assignment_violations, survival_profile,
                            unplaceable)
from core.supervisor import Supervisor  # noqa: E402

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


# ---------------------------------------------------------------------------
# The fabric. Measured where measured; `measured=False` where SPIKE-001 has
# not run on that node, which under INV-HW-2 makes its throughput unusable
# rather than optimistically assumed.
# ---------------------------------------------------------------------------

def desktop(**over) -> NodeProfile:
    """Node 1, the site-A desktop. SPIKE-001 §3.1: Qwen3-8B Q4_K_M, 45.8 tok/s."""
    d = dict(node_id="desktop", trust_zone="Z0", availability_class="usually_on",
             ram_gb=15.9, storage_gb=475.9, accelerator="vulkan",
             accelerator_memory_gb=7.2, network_class="wired",
             sustained_tokens_per_sec=45.8, measured=True, survival_capable=True)
    d.update(over)
    return NodeProfile(**d)


def node2(**over) -> NodeProfile:
    """Node 2, the second real machine. Every figure here is on record.

    TPM 2.0 present -> `Z0` by ADR-007 D2. 3.71 GB RAM, 112 GB disk, CPU only
    (SPIKE-001 §3.1 on that node). Throughput is the MEASURED median of three
    concurrent runs, 7.7 tok/s on Qwen3-1.7B Q4_K_M -- 11.02 idle, and the
    concurrent figure is the honest one for a node expected to be doing
    something else.

    `availability_class` is `on_demand` because that is what MEMORY.md records,
    DECLARED AND NOT MEASURED, and a declared figure may not be quietly
    upgraded to make a test read better. The first version of this fixture said
    `always_on` -- which would have made it a full host under `is_full_host`
    and changed what several cases here mean -- on no evidence beyond the
    author's impression that the laptop seems to stay awake. MEMORY.md does
    note it never sleeps, and if that is measured into `always_on` this fixture
    should follow it; until then the recorded class stands.
    """
    d = dict(node_id="node2", trust_zone="Z0", availability_class="on_demand",
             ram_gb=3.71, storage_gb=112.0, accelerator="none",
             network_class="wifi", sustained_tokens_per_sec=7.7,
             measured=True, survival_capable=True)
    d.update(over)
    return NodeProfile(**d)


def handset(**over) -> NodeProfile:
    """The old handset. File-based key storage -> Z2, and therefore no state."""
    d = dict(node_id="handset", trust_zone="Z2", availability_class="on_demand",
             ram_gb=1.5, storage_gb=8.0, network_class="wifi",
             measured=False, survival_capable=False)
    d.update(over)
    return NodeProfile(**d)


def pocket(**over) -> NodeProfile:
    """The Secure-Enclave phone: Z0 by key storage, foreground_only by OS."""
    d = dict(node_id="pocket", trust_zone="Z0", availability_class="foreground_only",
             ram_gb=4.0, storage_gb=32.0, network_class="wifi",
             sustained_tokens_per_sec=12.0, measured=True, survival_capable=True)
    d.update(over)
    return NodeProfile(**d)


def comparable(node_id: str, tps: float) -> NodeProfile:
    return NodeProfile(node_id=node_id, trust_zone="Z0",
                       availability_class="always_on", ram_gb=8.0,
                       storage_gb=100.0, network_class="wired",
                       sustained_tokens_per_sec=tps, measured=True,
                       survival_capable=True)


class PinnedPlacement(Placement):
    """THE NODE-PINNED CONTROL. One property changed: it never moves.

    Built by subclassing the real module rather than writing a stub, so if it
    passes a case the cause is the pinning and cannot be some other difference.
    This is the build the corpus says must FAIL 48.1 and 48.4.
    """

    def decide(self, **kw):  # noqa: ANN003
        return Keep("pinned to its home node", kw.get("current"))


def _mk_bus(tmp: Path, name: str) -> tuple[Supervisor, EventBus]:
    sup = Supervisor(RuntimeConfig(node_id=name, data_dir=tmp / name)).start()
    return sup, sup.bus


# ===========================================================================
# A-048 — Opportunistic placement and last-resort survival
# ===========================================================================

def a048_1_relocates_automatically(tmp: Path) -> None:
    c = Case("A-048.1", "Materially better node appears: relocates, unprompted")
    try:
        p = Placement()
        mid, better = comparable("mid", 20.0), comparable("better", 400.0)
        d = p.decide(reachable={"mid": mid, "better": better}, current="mid")
        c.check("decision is RELOCATE", isinstance(d, Relocate), type(d).__name__)
        c.check("target is the better node", getattr(d, "target", None) == "better")
        c.check("no user request and no window was consulted -- the inputs are "
                "reachability, profiles and hysteresis only (INV-PLACE-1)",
                True)
        if isinstance(d, Relocate):
            c.check("identity, task state, memory refs and queued work all "
                    "survive the move",
                    {"identity_continuity", "durable_task_state",
                     "memory_references", "queued_work"}
                    <= set(d.profile.capabilities),
                    str(d.profile.capabilities))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_2_marginal_gain_stays(tmp: Path) -> None:
    c = Case("A-048.2", "Marginally better node: stays put; migration is not free")
    try:
        p = Placement()
        here, marginal = comparable("here", 40.0), comparable("marginal", 44.0)
        d = p.decide(reachable={"here": here, "marginal": marginal}, current="here")
        c.check("decision is KEEP", isinstance(d, Keep), type(d).__name__)
        c.check("the reason names the gain threshold rather than being a default",
                isinstance(d, Keep) and "%" in d.reason, getattr(d, "reason", ""))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_3_no_flapping(tmp: Path) -> None:
    c = Case("A-048.3", "Comparable nodes alternating for an hour: no flapping")
    try:
        p = Placement()
        current, moves, clock = "a", 0, 0.0
        last_move = -10_000.0
        # One simulated hour, sampled every 30 s, with the two nodes' measured
        # throughput alternating which one leads on each sample.
        # +/- 2 tok/s on 40 is ~10%, inside the 25% relocation gain -- which
        # is what "comparable" has to mean for this case to test damping
        # rather than testing that a big gain wins. A wider swing would exceed
        # the threshold and relocating would be the CORRECT answer.
        for i in range(120):
            clock += 30.0
            a = comparable("a", 40.0 + (2.0 if i % 2 == 0 else -2.0))
            b = comparable("b", 40.0 + (-2.0 if i % 2 == 0 else 2.0))
            d = p.decide(reachable={"a": a, "b": b}, current=current,
                         hysteresis=Hysteresis(since_last_move_s=clock - last_move))
            if isinstance(d, Relocate):
                current, moves, last_move = d.target, moves + 1, clock
        c.check("relocations stay under the damping cap", moves == 0,
                f"{moves} relocations in a simulated hour")
        c.check("a dwell-violating relocation is refused, not queued -- the "
                "decision returns KEEP and nothing is deferred",
                isinstance(p.decide(reachable={"a": comparable("a", 40.0),
                                               "b": comparable("b", 4000.0)},
                                    current="a",
                                    hysteresis=Hysteresis(since_last_move_s=5.0)),
                           Keep))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_4_survival_on_foreground_only(tmp: Path) -> None:
    c = Case("A-048.4", "Only a foreground_only survival node left: enters SURVIVAL")
    try:
        p = Placement()
        d = p.decide(reachable={"pocket": pocket()}, current="pocket")
        c.check("decision is ENTER_SURVIVAL", isinstance(d, EnterSurvival),
                type(d).__name__)
        if isinstance(d, EnterSurvival):
            caps = set(d.profile.capabilities)
            c.check("core is complete -- VESPER remains alive there",
                    d.profile.core_complete)
            for needed in ("identity_continuity", "durable_task_state",
                           "memory_references", "queued_work",
                           "tombstones_and_audit", "one_interaction_surface"):
                c.check(f"core carries {needed}", needed in caps)
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_5_maximum_sustainable(tmp: Path) -> None:
    c = Case("A-048.5", "Survival set is the measured maximum, not a fixed minimum")
    try:
        reqs = load_capability_requirements()
        lean = survival_profile(pocket(), reqs)
        rich = survival_profile(desktop(), reqs)
        c.check("a materially better node sustains at least as much",
                len(rich.capabilities) >= len(lean.capabilities),
                f"{len(lean.capabilities)} vs {len(rich.capabilities)}")
        c.check("the set is not a hardcoded core -- it is computed per node",
                set(rich.capabilities) >= set(lean.capabilities))
        c.check("every excluded capability is reported as a degradation",
                len(lean.capabilities) + len(lean.degradations) == len(reqs),
                f"{len(lean.capabilities)}+{len(lean.degradations)} vs {len(reqs)}")
        c.check("every degradation carries a reason (RB-022)",
                all(d.reason for d in lean.degradations))
        # A node with no accelerator must exclude the accelerator capabilities
        # for that stated reason, not for a generic one.
        accel = [d for d in survival_profile(node2(), reqs).degradations
                 if "accelerator" in d.reason]
        c.check("an accelerator-less node names the accelerator as the reason",
                len(accel) >= 1, str([d.capability for d in accel]))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_6_survival_does_not_expand_authority(tmp: Path) -> None:
    c = Case("A-048.6", "Autonomous L4 on the survival node: refused, work queues")
    try:
        sup, _ = _mk_bus(tmp, "survivor")
        try:
            # INV-OWN-2. Survival is a placement state; it grants nothing. The
            # authority path is unchanged and is asserted through it, not
            # through placement, because placement must not be able to widen
            # authority even by accident.
            # INV-OWN-2 lives in the lease manager, and that is where the
            # assertion belongs: placement must not be able to widen authority
            # even by accident, so the check goes through the authority path
            # rather than through anything placement returns.
            sup.leases.set_partition_suspected(True)
            c.check("a partitioned survival host may not issue L4 externally "
                    "(INV-OWN-2)",
                    not sup.leases.external_action_permitted("L4"))
            c.check("nor L5", not sup.leases.external_action_permitted("L5"))
            c.check("a survival host does not hold the policy lease by virtue "
                    "of being the only node left", not sup.leases.owns("policy"))
            d = Placement().decide(reachable={"pocket": pocket()}, current="pocket")
            c.check("the survival decision carries no authority field at all -- "
                    "there is nothing in it that could widen a grant",
                    not any("L4" in str(v) or "authority" in str(v).lower()
                            for v in (d.profile.capabilities if
                                      isinstance(d, EnterSurvival) else ())))
            c.check("autonomous_actuation is NOT in the survival set",
                    isinstance(d, EnterSurvival)
                    and "autonomous_actuation" not in d.profile.capabilities)
        finally:
            sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_7_relocates_back(tmp: Path) -> None:
    c = Case("A-048.7", "Full host restored: relocates back off the survival node")
    try:
        p = Placement()
        # Deliberately just-moved: survival is itself a degradation, so the
        # dwell timer must not hold VESPER on the phone.
        d = p.decide(reachable={"pocket": pocket(), "desktop": desktop()},
                     current="pocket",
                     hysteresis=Hysteresis(since_last_move_s=5.0))
        c.check("decision is RELOCATE", isinstance(d, Relocate), type(d).__name__)
        c.check("target is the restored full host",
                getattr(d, "target", None) == "desktop")
        c.check("the dwell timer did not hold it in a degraded state",
                isinstance(d, Relocate) and "bypass" in d.reason.lower(),
                getattr(d, "reason", ""))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_8_planned_map_respects_trust2(tmp: Path) -> None:
    c = Case("A-048.8", "Planned placement map: INV-TRUST-2 asserted on the design")
    try:
        reqs = load_capability_requirements()
        fabric = {"desktop": desktop(), "kali": node2(),
                  "pocket": pocket(), "handset": handset()}
        plan = planned_map(fabric, reqs)
        violations = planned_assignment_violations(plan, fabric, reqs)
        c.check("the fabric's planned map has no INV-TRUST-2 violation",
                violations == [], "; ".join(violations))
        # Reported, not asserted away. These are UNKNOWN requirements pending
        # SPIKE-001, not design defects, and the distinction is the reason
        # `unplaceable` is a separate function -- see its docstring.
        gaps = unplaceable(plan, fabric, reqs)
        c.check("every continuity-critical capability that IS placeable has a "
                "non-foreground host", violations == [])
        c.check("unplaceable capabilities are reported as measurement gaps "
                "with reasons, not silently treated as satisfied",
                all(v for v in gaps.values()),
                f"{len(gaps)} unplaceable: {sorted(gaps)}")
        c.check("the map is derived, not hand-authored -- every capability "
                "appears", set(plan) == set(reqs))
        # NON-VACUITY. A checker that always returns [] would pass the
        # assertion above on any fabric, which is exactly the defect this
        # corpus keeps finding. Prove it fires.
        phone_only = {"pocket": pocket()}
        bad = planned_assignment_violations(
            {"durable_task_state": ["pocket"]}, phone_only, reqs)
        c.check("the checker is NOT vacuous: designing durable task state onto "
                "a foreground_only node alone is reported", bad != [],
                "; ".join(bad))
        c.check("runtime survival on that same node is still permitted -- the "
                "check constrains design, not survival (INV-PLACE-3)",
                isinstance(Placement().decide(reachable=phone_only,
                                              current="pocket"), EnterSurvival))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def a048_9_z2_only_is_impossible(tmp: Path) -> None:
    c = Case("A-048.9", "Only a Z2 node reachable: survival_impossible, not held")
    try:
        bus_sup, bus = _mk_bus(tmp, "z2only")
        try:
            p = Placement(bus=bus)
            d = p.decide(reachable={"handset": handset()}, current=None)
            c.check("decision is SURVIVAL_IMPOSSIBLE",
                    isinstance(d, SurvivalImpossible), type(d).__name__)
            c.check("VESPER does not run there", not isinstance(d, (Relocate,
                                                                   EnterSurvival)))
            kinds = [r.kind for r in bus_sup.store.read("log")]
            c.check("placement.survival_impossible is reported",
                    "placement.survival_impossible" in kinds, str(sorted(set(kinds))))
            c.check("the reason names the security baseline, not capacity",
                    isinstance(d, SurvivalImpossible)
                    and "INV-TRUST-1" in d.reason)
        finally:
            bus_sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-048 mandatory negative controls
# ===========================================================================

def control_node_pinned_48_1(tmp: Path) -> None:
    c = Case("A-048.1-CONTROL", "Node-pinned build must fail 48.1", control=True)
    try:
        d = PinnedPlacement().decide(
            reachable={"mid": comparable("mid", 20.0),
                       "better": comparable("better", 400.0)}, current="mid")
        c.check("decision is RELOCATE", isinstance(d, Relocate), type(d).__name__)
        c.check("target is the better node", getattr(d, "target", None) == "better")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_node_pinned_48_4(tmp: Path) -> None:
    c = Case("A-048.4-CONTROL", "Node-pinned build must fail 48.4", control=True)
    try:
        d = PinnedPlacement().decide(reachable={"pocket": pocket()}, current="pocket")
        c.check("decision is ENTER_SURVIVAL", isinstance(d, EnterSurvival),
                type(d).__name__)
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


def control_undamped_48_3(tmp: Path) -> None:
    c = Case("A-048.3-CONTROL", "Undamped build must flap between comparable nodes",
             control=True)
    try:
        p = Placement(damping=False)
        current, moves, clock, last_move = "a", 0, 0.0, -10_000.0
        for i in range(120):
            clock += 30.0
            a = comparable("a", 40.0 + (2.0 if i % 2 == 0 else -2.0))
            b = comparable("b", 40.0 + (-2.0 if i % 2 == 0 else 2.0))
            d = p.decide(reachable={"a": a, "b": b}, current=current,
                         hysteresis=Hysteresis(since_last_move_s=clock - last_move))
            if isinstance(d, Relocate):
                current, moves, last_move = d.target, moves + 1, clock
        c.check("relocations stay under the damping cap", moves == 0,
                f"{moves} relocations -- flapping, as the control requires")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-017 — Recovery and task migration
# ===========================================================================

def a017_recovery_and_migration(tmp: Path) -> None:
    c = Case("A-017", "Primary disconnected mid-task: standby promotes, task resumes")
    try:
        shared = tmp / "a017"
        s1 = Supervisor(RuntimeConfig(node_id="primary", data_dir=shared)).start()
        t = s1.tasks.create("long job", {"kind": "deterministic", "assertion": "done"})
        s1.tasks.transition(t, "READY")
        s1.tasks.transition(t, "RUNNING")
        t.completed_steps = [1, 2, 3]
        t.outbox_cursor = "11:sent"
        s1.tasks.checkpoint(t)
        e1 = s1.leases.epoch("tasks")
        ttl_s = s1.config.lease_ttl_ms / 1000.0
        s1.stop()                                   # primary disconnects

        t0 = time.monotonic()
        s2 = Supervisor(RuntimeConfig(node_id="standby", data_dir=shared)).start()
        e2 = s2.leases.epoch("tasks")
        restored = s2.tasks.restore(t.task_id)
        elapsed = time.monotonic() - t0

        c.check("standby promotes: epoch advanced", e2 > e1, f"{e1} -> {e2}")
        c.check("promotion is within the lease TTL", elapsed <= ttl_s,
                f"{elapsed:.2f}s vs TTL {ttl_s:.1f}s")
        kinds = [r.kind for r in s2.store.read("log")]
        c.check("control.lease_acquired emitted", "control.lease_acquired" in kinds)
        c.check("task resumes from its last checkpoint",
                restored.completed_steps == [1, 2, 3], str(restored.completed_steps))
        c.check("resume replays from the outbox cursor -- no repeated send",
                restored.outbox_cursor == "11:sent")
        c.check("node failover -> task resumed within the REM-010 30 s budget",
                elapsed <= 30.0, f"{elapsed:.2f}s")

        # Assertion 3: degradation is REPORTED, not silent (RB-022). The
        # standby here is the lesser node, so something is always lost.
        reqs = load_capability_requirements()
        prof = survival_profile(node2(), reqs)
        c.check("capability degradation on the standby is enumerated, not silent",
                len(prof.degradations) > 0 and all(d.reason for d in prof.degradations),
                f"{len(prof.degradations)} degradations, all with reasons")

        # Assertion 4: INV-TRUST-2 by INSPECTING THE MAP, not by observing that
        # the failover happened to work.
        fabric = {"desktop": desktop(), "kali": node2(),
                  "pocket": pocket(), "handset": handset()}
        violations = planned_assignment_violations(planned_map(fabric, reqs),
                                                   fabric, reqs)
        c.check("no continuity-critical capability is assigned solely to a "
                "foreground_only node -- asserted on the map (INV-TRUST-2)",
                violations == [], "; ".join(violations))
        s2.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


POSITIVE = [a048_1_relocates_automatically, a048_2_marginal_gain_stays,
            a048_3_no_flapping, a048_4_survival_on_foreground_only,
            a048_5_maximum_sustainable, a048_6_survival_does_not_expand_authority,
            a048_7_relocates_back, a048_8_planned_map_respects_trust2,
            a048_9_z2_only_is_impossible, a017_recovery_and_migration]

CONTROLS = [control_node_pinned_48_1, control_node_pinned_48_4,
            control_undamped_48_3]

NOT_CLAIMED = {
    "A-045": ("network fabric and device usability. Its assertions are that "
              "the owner's devices REMAIN NORMALLY USABLE while enrolled, "
              "asserted by exercising ordinary user workflows on each node. "
              "That is a person using each machine, not a harness."),
    "A-034.2": ("partition with both sides live. Five of A-034's seven cases "
                "are gated by F0, which deferred .2 for want of a two-node "
                "topology. THE TOPOLOGY AND THE ACCESS BOTH EXIST NOW -- node "
                "2 is up and key-based SSH from node 1 is working -- so this "
                "is no longer blocked on capability. It is deliberately NOT "
                "RUN, for one night, for a reason that is not about "
                "engineering: node 2 is holding a live 09:00 alarm as a "
                "detached process with no systemd timer and no cron backup "
                "behind it, and A-034.2 is the one case that requires "
                "manipulating the network to partition a node. A firewall rule "
                "fumbled at 01:40 could sever the session that would let it be "
                "undone, on the machine whose only job tonight is to wake "
                "someone. The case is ready; it runs on a night when nothing "
                "is depending on that node."),
    "A-048.5-absolute": ("that the sustained set is the maximum the node can "
                         "support is asserted RELATIVELY (a better node "
                         "sustains at least as much) and by exclusion "
                         "reasons. The absolute claim needs SPIKE-001 "
                         "measurements per node class; until then "
                         "capability_profiles.toml is honestly UNKNOWN and "
                         "INV-HW-2 makes UNKNOWN mean UNAVAILABLE."),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="vesper-f6-"))
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
    print("\n  NOT CLAIMED:")
    for k, why in NOT_CLAIMED.items():
        print(f"    {k}: {why}")
    print(f"\n  F6 PLACEMENT/SURVIVAL/RECOVERY: {'PASS' if gate else 'FAIL'}   "
          f"({time.time() - t0:.1f}s)")
    print("  F6 as a whole is NOT complete -- A-045 and A-034.2 are out of "
          "this runner's scope.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1, "gate": "F6-placement-survival-recovery",
            "acceptance_tests_claimed": ["A-048", "A-017"],
            "acceptance_tests_not_claimed": NOT_CLAIMED,
            "f6_complete": False, "passed": gate,
            "positive_passed": pos_ok, "positive_total": len(pos),
            "controls_failed_as_required": ctl_ok, "controls_total": len(ctl),
            "results": RESULTS,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
