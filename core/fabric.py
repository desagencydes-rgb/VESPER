"""Network fabric admission -- DF-FABRIC-ADMIT.

Implements SR-016: a dedicated control/data plane, with the user's own devices
left alone. Three invariants, one per clause of the source requirement:

  INV-NET-1  every node is reached through exactly one DECLARED segment;
             an undeclared/unlisted/unattested segment means UNREACHABLE.
  INV-NET-2  effective trust zone is the WEAKER of the node's own zone and the
             segment's ceiling. A segment may lower it and may never raise it.
  INV-NET-3  administrative control reaches vesper_owned nodes only, and
             control traffic carries a reservation media cannot consume.

WHY THIS IS A SEPARATE MODULE AND NOT A FIELD ON NodeProfile.

`NodeProfile` carries what enrollment MEASURED about a machine. Which segment
that machine is reached over is not a property of the machine at all -- the
same node moves between segments without changing any of its own attributes,
and a laptop carried from a controlled network to an uncontrolled one is
exactly the case the fabric exists to catch. Putting the segment on the profile
would make a relational fact look like an intrinsic one, and the trust
consequence would then travel with the machine instead of with the path.

WHY ADMISSION RUNS UPSTREAM OF PLACEMENT AND NOT INSIDE IT.

`core/placement.py` already consumes `NodeProfile.reachable` and
`NodeProfile.trust_zone`. The fabric decides both. Running admission first and
handing placement corrected profiles keeps one decision in one place: placement
answers "where should VESPER run among nodes it may use", the fabric answers
"which nodes may it use, and how far". Folding the segment rule into
`is_full_host` would have put two different questions behind one predicate,
which is the defect `is_full_host`'s own docstring already records for trust
zone and availability class.

FAIL-CLOSED, AND WHY THE DEFAULT IS NOT Z3.

An unknown segment does not yield a weak admission; it yields no admission.
Degrading an unknown path to "weakest zone" would leave it usable for rendering
and observation -- which is what Z2/Z3 permit -- and an uncharacterised network
path is the one thing that should not be permitted to observe. INV-HW-2 had to
learn the equivalent lesson on the hardware axis: UNKNOWN was made to MEAN
UNAVAILABLE rather than be treated as it, because "treated as" decays.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Zone ranks are duplicated from placement rather than imported, deliberately:
# a module that gates admission must not be able to fail open because a
# placement refactor moved a constant. The two are asserted equal by CI-055.
# LOWER RANK IS STRONGER -- Z0 is the strongest zone, Z3 the weakest.
TRUST_ZONE_RANK = {"Z0": 0, "Z1": 1, "Z2": 2, "Z3": 3}

OWNERSHIP_CLASSES = ("vesper_owned", "user_owned")

CONTRACT_PATH = (Path(__file__).resolve().parents[1]
                 / "contracts" / "policy" / "network_fabric.toml")


class FabricContractViolation(Exception):
    """The fabric contract or a segment binding is malformed.

    Raised rather than defaulted. A malformed fabric is the one condition where
    guessing is worse than stopping: every safe default here is also the
    default an attacker would choose for us.
    """


@dataclass(frozen=True)
class Segment:
    name: str
    trust_zone_ceiling: str
    vesper_controlled: bool
    admits_ownership: tuple[str, ...]
    carries_control_plane: bool


@dataclass(frozen=True)
class Admission:
    """DF-FABRIC-ADMIT's return type.

    `admitted` is a separate field from `effective_trust_zone` on purpose. If
    refusal were encoded as a weak zone, every caller would have to remember
    that one particular zone means "not actually reachable", and callers do not
    remember. `effective_trust_zone` is None exactly when `admitted` is False,
    so a caller that ignores the flag gets a TypeError rather than a silent
    admission at the weakest zone.
    """

    admitted: bool
    effective_trust_zone: str | None
    administrable: bool
    reason: str

    def __post_init__(self) -> None:
        if self.admitted and self.effective_trust_zone is None:
            raise FabricContractViolation(
                "admitted with no effective trust zone -- an admission that "
                "does not say how far is not an admission")
        if not self.admitted and self.effective_trust_zone is not None:
            raise FabricContractViolation(
                f"refused admission still carries zone "
                f"{self.effective_trust_zone!r}; refusal must not look like a "
                f"weak yes")
        if not self.admitted and self.administrable:
            raise FabricContractViolation(
                "refused node marked administrable -- INV-NET-3")


def load_contract(path: Path | None = None) -> dict:
    p = CONTRACT_PATH if path is None else path
    if not p.is_file():
        raise FabricContractViolation(
            f"network fabric contract missing at {p} -- INV-NET-1 has no "
            f"segment declarations to read, and absence is not permission")
    return tomllib.loads(p.read_text(encoding="utf-8"))


def segments(contract: dict) -> dict[str, Segment]:
    out: dict[str, Segment] = {}
    for name, raw in sorted(contract.get("segment", {}).items()):
        ceiling = raw.get("trust_zone_ceiling")
        if ceiling not in TRUST_ZONE_RANK:
            raise FabricContractViolation(
                f"segment {name!r}: trust_zone_ceiling {ceiling!r} not in "
                f"{tuple(TRUST_ZONE_RANK)}")
        for own in raw.get("admits_ownership", []):
            if own not in OWNERSHIP_CLASSES:
                raise FabricContractViolation(
                    f"segment {name!r}: ownership class {own!r} not in "
                    f"{OWNERSHIP_CLASSES}")
        out[name] = Segment(
            name=name,
            trust_zone_ceiling=ceiling,
            vesper_controlled=bool(raw.get("vesper_controlled", False)),
            admits_ownership=tuple(raw.get("admits_ownership", [])),
            carries_control_plane=bool(raw.get("carries_control_plane", False)),
        )
    return out


def effective_trust_zone(node_zone: str, segment_ceiling: str) -> str:
    """INV-NET-2: the WEAKER of the two. A ceiling never elevates.

    Weaker is the HIGHER rank number, so this is a max over ranks and not a
    min. Written out because the direction is genuinely easy to invert, and
    inverting it produces a system that grants its strongest trust to its least
    controlled path while every test that only checks "a ceiling was applied"
    still passes.
    """
    if node_zone not in TRUST_ZONE_RANK:
        raise FabricContractViolation(f"node trust_zone {node_zone!r} unknown")
    if segment_ceiling not in TRUST_ZONE_RANK:
        raise FabricContractViolation(
            f"segment ceiling {segment_ceiling!r} unknown")
    weaker = max(node_zone, segment_ceiling, key=lambda z: TRUST_ZONE_RANK[z])
    return weaker


def admit(node_zone: str,
          ownership: str,
          segment_name: str | None,
          contract: dict) -> Admission:
    """DF-FABRIC-ADMIT.

    Returns UNREACHABLE(reason) or ADMIT(effective_trust_zone, administrable).
    """
    if ownership not in OWNERSHIP_CLASSES:
        raise FabricContractViolation(
            f"ownership {ownership!r} not in {OWNERSHIP_CLASSES} -- INV-NET-3 "
            f"cannot be evaluated without it, and defaulting it would default "
            f"the permissive way")

    disposition = contract.get("unlisted_segment_disposition")
    if disposition != "UNREACHABLE":
        raise FabricContractViolation(
            f"unlisted_segment_disposition is {disposition!r}, not "
            f"'UNREACHABLE' -- INV-NET-1 is fail-closed by definition and a "
            f"contract that opens it is not a weaker policy, it is a different "
            f"invariant")

    declared = segments(contract)

    # INV-NET-1. Both arms are the same refusal: no declared segment, no
    # admission. Named separately only so the audit record says which.
    if segment_name is None:
        return Admission(False, None, False,
                         "no segment binding: INV-NET-1 admits only a node "
                         "reached through a declared segment")
    if segment_name not in declared:
        return Admission(False, None, False,
                         f"segment {segment_name!r} is not declared in the "
                         f"fabric contract")

    seg = declared[segment_name]

    # An unattested fabric may not carry the control plane. This is the clause
    # that keeps `attested = false` honest: without it the contract could
    # declare a dedicated segment that nobody has stood up, and placement would
    # host continuity-critical capability on an aspiration.
    if seg.vesper_controlled and not contract.get("attested", False):
        return Admission(False, None, False,
                         f"segment {segment_name!r} claims vesper_controlled "
                         f"while the fabric is not attested -- a dedicated "
                         f"network that has not been stood up is a plan, not a "
                         f"path")

    if ownership not in seg.admits_ownership:
        return Admission(False, None, False,
                         f"segment {segment_name!r} does not admit "
                         f"{ownership!r} nodes")

    zone = effective_trust_zone(node_zone, seg.trust_zone_ceiling)

    # INV-NET-3. BOTH conditions, and the second is the one that matters:
    # ownership alone would let VESPER administer its own node over a path it
    # does not control, which is administration without a channel it can
    # vouch for.
    administrable = (ownership == "vesper_owned") and seg.vesper_controlled

    return Admission(True, zone, administrable,
                     f"admitted on {segment_name!r} at {zone} "
                     f"(node {node_zone}, ceiling {seg.trust_zone_ceiling})")


def apply_fabric(profiles, bindings: dict[str, str | None],
                 contract: dict | None = None):
    """Gate a set of NodeProfiles through the fabric before placement sees them.

    Returns new profiles with `reachable` and `trust_zone` set to what the
    fabric decided. Profiles are replaced rather than mutated so a caller
    cannot end up holding one object that means two things.

    A node absent from `bindings` is treated as having NO binding, which is
    UNREACHABLE. Absence is not "unchanged": a node nobody bound is a node
    nobody characterised.
    """
    from dataclasses import replace

    doc = load_contract() if contract is None else contract
    out = []
    for p in profiles:
        decision = admit(p.trust_zone, getattr(p, "ownership", "vesper_owned"),
                         bindings.get(p.node_id), doc)
        if not decision.admitted:
            out.append(replace(p, reachable=False))
        else:
            out.append(replace(p, reachable=p.reachable,
                               trust_zone=decision.effective_trust_zone))
    return out
