"""Opportunistic placement — `DF-PLACE` and `DF-SURVIVAL-PROFILE`. REM-014 / SR-060.

VESPER IS NOT PINNED TO A MACHINE. That is the whole content of this module and
it is a requirement, not an optimisation: *"nothing is sitting anywhere, Vesper
eventually gets moved automatically where it feels comfortable, and when
hardware is genuinely unavailable — say only the [foreground_only handset] is
online — it should end up there with just whatever it needs so it stays alive,
and with the most resources it can get."* A build that pins to one host passes
every other acceptance test in the suite and fails this requirement completely,
which is why `A-048` exists and why its negative control is a node-pinned build.

The owner named a device; this module may not. `INV-HW-1` keeps product names
out of every routing, resource and policy path, and `CI-007` enforces it -- it
caught this file on the first run after it was written. The substitution is the
point rather than a formality: what matters about that device is
`availability_class = foreground_only`, and a rule written about the product
would silently stop applying the day the product is replaced.

THE DECISION IS A PREDICATE, NEVER A MODEL CALL. Like the resource governor
(REM-007), placement is a deterministic function of measured node state. A
model asked "where should I run?" would be non-reproducible, unauditable, and
would put an inference dependency inside the mechanism that has to work when
inference is exactly what is unavailable.

THE FOUR THINGS THAT ARE EASY TO GET WRONG, each a named invariant:

  INV-PLACE-1  Relocation is AUTOMATIC AND UNPROMPTED. No user request, no
               scheduled window. `KEEP` must be a decision the function
               reaches, never a default it falls back to.

  INV-PLACE-2  It is DAMPED. Two comparable nodes must not trade VESPER back
               and forth — migration costs more than the marginal gain. But
               damping applies only to *improvements*: degradation or loss of
               the current host bypasses both gates, because waiting politely
               while the host dies is the wrong failure direction.

  INV-PLACE-3  When no full host is reachable, VESPER ENTERS SURVIVAL rather
               than ceasing to exist — carrying the core, plus the MAXIMUM the
               node can measurably sustain. Not a fixed minimal profile: "not
               everything, but the maximum it can get."

  INV-TRUST-2  Constrains the PLANNED assignment map, not the runtime. No
               continuity-critical capability may be *designed* to depend
               solely on a `foreground_only` or `on_demand` node — and yet such
               a node may legitimately *host survival* when it is all that is
               left. Conflating the two is what previously excluded the phone
               from the fabric altogether, so the two are checked by two
               different functions here: `planned_assignment_violations` reads
               the plan, `decide` reads what is reachable now.

WHERE THIS DEPARTS FROM THE PSEUDOCODE, AND WHY. `DF-PLACE` as written in
`spec/decision-functions/DECISION_FUNCTIONS.md` lists the degradation bypass
*after* the gain and dwell gates:

    if score(best) < score(current) * RELOCATE_GAIN: return KEEP
    if hysteresis.since_last_move < MIN_DWELL:       return KEEP
    if current is unreachable or degraded:           pass

The third line is unreachable as ordered — both gates have already returned.
`INV-PLACE-2` is unambiguous in prose ("Degradation or loss of the current host
bypasses both"), and an invariant outranks a loose transcription, so the bypass
is evaluated FIRST here. Recorded rather than silently fixed: a reader
comparing the two should find the difference explained, not discover it.

UNMEASURED MEANS UNAVAILABLE. `capability_profiles.toml` declares
`unmeasured_disposition = "UNAVAILABLE"`, so a capability whose requirement is
`UNKNOWN`, or which needs a throughput figure this node has not measured,
cannot be shown to fit and is excluded — and every exclusion is reported as a
degradation (RB-022). On today's tree that means the survival set is the core
and little else, which is the honest answer until `SPIKE-001` fills the
numbers in. A build that guessed would look better and be wrong.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bus import EventBus

REPO = Path(__file__).resolve().parents[1]
CAPABILITY_PROFILES = REPO / "contracts" / "policy" / "capability_profiles.toml"
TUNABLES = REPO / "contracts" / "policy" / "tunables.toml"

# Zone strength, strongest first. `min_trust_zone: "Z1"` means Z1 *or better*,
# so a node satisfies a requirement when its rank is <= the requirement's.
TRUST_ZONE_RANK = {"Z0": 0, "Z1": 1, "Z2": 2, "Z3": 3}

# INV-TRUST-1: a Z2 node may not hold state, so it cannot be a host. It can
# still be an endpoint -- `one_interaction_surface` declares `min_trust_zone =
# "Z2"` precisely so a survival host may render through a surface it does not
# trust with state.
HOST_ZONES = ("Z0", "Z1")

AVAILABILITY_RANK = {"always_on": 4, "usually_on": 3, "intermittent": 2,
                     "foreground_only": 1, "on_demand": 0}

NETWORK_RANK = {"wired": 3, "wifi": 2, "cellular": 1, "intermittent": 0}

# INV-TRUST-2 names these two classes explicitly.
NON_CONTINUITY_CLASSES = ("foreground_only", "on_demand")


def is_full_host(profile: "NodeProfile") -> bool:
    """Can this node be a FULL host, as opposed to a survival host?

    THE PSEUDOCODE IS LOOSE HERE AND THE ACCEPTANCE TEST IS NOT. `DF-PLACE`
    writes `hosts = [n for n in reachable if profiles[n].trust_zone in {Z0,
    Z1}]` -- trust zone alone. Read literally, a `Z1 foreground_only` node is a
    full host, and then `A-048.4` ("remove every node except one
    foreground_only survival-capable node -> VESPER **enters SURVIVAL**") can
    never pass: the node would simply be kept as an ordinary host and survival
    would never be entered on any topology.

    The resolution is in `INV-PLACE-3`'s own wording -- survival begins "when no
    **full host** is reachable" -- and in the pair `INV-TRUST-2` forms with it.
    `INV-TRUST-2` forbids *designing* continuity onto a `foreground_only` or
    `on_demand` node while explicitly permitting *runtime survival* there. Those
    two statements only cohere if such a node is never a full host and can
    still be a survival host, which is exactly this predicate.

    It matches the real inventory, and the zone half makes the availability
    half *more* necessary rather than less. ADR-007 D2 grants `Z0` -- the
    STRONGEST zone -- to any node with hardware-backed non-exportable key
    storage, and that class of node includes ones whose OS may evict the
    process at any moment, i.e. `availability_class = foreground_only`. On
    trust zone alone such a node is not merely a host but a top-ranked one, and
    continuity would be designed onto the node least able to provide it. A node
    with file-based key storage earns `Z2` instead and is neither host nor
    survival host, which is `A-048.9`.

    Stated in profile terms on purpose (`INV-HW-1`): the pairing that makes
    this predicate necessary is *strong key storage with weak availability*,
    and that pairing is a property of a class of device, not of one product.

    Recorded rather than quietly assumed: if the corpus intends the literal
    reading, this predicate is the single place to change, and `A-048.4` is the
    test that would then have to be renegotiated.
    """
    return (profile.trust_zone in HOST_ZONES
            and profile.availability_class not in NON_CONTINUITY_CLASSES)

UNKNOWN = "UNKNOWN"


class PlacementContractViolation(Exception):
    """The placement inputs are malformed in a way that must not be defaulted."""


@dataclass(frozen=True, slots=True)
class NodeProfile:
    """The measured half of `node_capability_profile.schema.json`.

    `measured` is carried per node rather than read from the contract file
    because it is a property of an enrollment, not of the corpus: two nodes
    with identical spec sheets differ, which is the entire reason enrollment
    measures rather than declares (INV-HW-2).
    """

    node_id: str
    trust_zone: str
    availability_class: str
    ram_gb: float = 0.0
    storage_gb: float = 0.0
    accelerator: str = "none"
    accelerator_memory_gb: float | None = None
    network_class: str = "wifi"
    sustained_tokens_per_sec: float | None = None
    measured: bool = False
    survival_capable: bool = False
    reachable: bool = True
    degraded: bool = False

    def __post_init__(self) -> None:
        if self.trust_zone not in TRUST_ZONE_RANK:
            raise PlacementContractViolation(
                f"node {self.node_id!r}: trust_zone {self.trust_zone!r} not in "
                f"{tuple(TRUST_ZONE_RANK)}")
        if self.availability_class not in AVAILABILITY_RANK:
            raise PlacementContractViolation(
                f"node {self.node_id!r}: availability_class "
                f"{self.availability_class!r} not in {tuple(AVAILABILITY_RANK)}")

    @property
    def measured_throughput(self) -> float:
        """Throughput, or 0.0 when it was never measured.

        INV-HW-2: a declared figure may not stand in for a measured one, and an
        absent one may not be optimistically assumed. Scoring an unmeasured
        node as zero makes it rank below any measured node, which is the
        correct direction -- it does not get relocated *to* on a promise.
        """
        if not self.measured or self.sustained_tokens_per_sec is None:
            return 0.0
        return float(self.sustained_tokens_per_sec)

    def score(self) -> tuple:
        """Lexicographic key from `DF-PLACE`'s stated order.

        `best_by(hosts, [availability_class_rank, sustained_throughput,
        accelerator_memory, network_class])` -- availability dominates, because
        a fast node that is usually asleep is not a host.
        """
        return (AVAILABILITY_RANK[self.availability_class],
                self.measured_throughput,
                float(self.accelerator_memory_gb or 0.0),
                NETWORK_RANK.get(self.network_class, 0))

    def scalar_score(self) -> float:
        """A single magnitude, for the relocation-gain RATIO only.

        The lexicographic key answers "which is best"; the gain threshold needs
        "by how much", and a tuple has no ratio.

        IT IS MULTIPLICATIVE, AND THAT IS THE WHOLE POINT. The first version of
        this was additive with availability weighted at 1000 -- and that made
        the gain threshold meaningless on the axis it exists to measure: a node
        with TWENTY TIMES the measured throughput (20 -> 400 tok/s) scored only
        9% higher, so `A-048.1` returned KEEP and the system would have sat on
        a node it should obviously have left. A ratio test needs a magnitude
        whose ratios mean something, and a large additive constant destroys
        exactly that.

        Multiplying instead keeps both properties the corpus asks for: a node
        one availability class better is worth a fixed multiple (categorical,
        as it should be), while throughput and accelerator ratios survive
        intact into the comparison. The `1 +` guards the degenerate case of an
        unmeasured node, whose throughput is 0 by INV-HW-2 -- without it every
        such node would score zero and every ratio against it would be
        infinite.
        """
        capability = (1.0
                      + self.measured_throughput
                      + float(self.accelerator_memory_gb or 0.0) * 10.0
                      + NETWORK_RANK.get(self.network_class, 0))
        return (1.0 + AVAILABILITY_RANK[self.availability_class]) * capability

    def satisfies_zone(self, min_trust_zone: str) -> bool:
        req = TRUST_ZONE_RANK.get(min_trust_zone)
        if req is None:
            raise PlacementContractViolation(
                f"min_trust_zone {min_trust_zone!r} not in {tuple(TRUST_ZONE_RANK)}")
        return TRUST_ZONE_RANK[self.trust_zone] <= req


@dataclass(frozen=True, slots=True)
class Hysteresis:
    """State the damping gates read. Held by the caller, not by this module."""

    since_last_move_s: float = float("inf")


@dataclass(frozen=True, slots=True)
class Degradation:
    """A capability that is not running, and why. RB-022 requires the why."""

    capability: str
    reason: str


@dataclass(frozen=True, slots=True)
class SurvivalProfile:
    node_id: str
    capabilities: tuple[str, ...]
    degradations: tuple[Degradation, ...]
    core_complete: bool
    # Which core members could not be shown to fit, when the core as a whole
    # does not. Kept separate from `degradations` so the partition
    # `capabilities | degradations == every declared capability` stays exact:
    # the core is still *attempted* when it does not fit, per
    # DF-SURVIVAL-PROFILE's "return core # attempt anyway".
    core_shortfall: tuple[Degradation, ...] = ()


@dataclass(frozen=True, slots=True)
class Keep:
    reason: str
    current: str | None = None


@dataclass(frozen=True, slots=True)
class Relocate:
    target: str
    profile: SurvivalProfile
    reason: str


@dataclass(frozen=True, slots=True)
class EnterSurvival:
    node: str
    profile: SurvivalProfile
    reason: str


@dataclass(frozen=True, slots=True)
class SurvivalImpossible:
    """Nothing reachable can carry the core. Reported, never quietly attempted.

    `A-048.9`: with only a `Z2 limited_trust` node reachable, VESPER does not
    run there. Holding state on a node that fails the security baseline is a
    worse outcome than being unavailable, and `INV-TRUST-1` is not a
    performance guideline.
    """

    reason: str
    degradations: tuple[Degradation, ...] = ()


Decision = Keep | Relocate | EnterSurvival | SurvivalImpossible


def load_capability_requirements(path: Path | None = None) -> dict[str, dict]:
    """Read the capability table from the governed surface, order preserved.

    ORDER IS VALUE ORDER. `DF-SURVIVAL-PROFILE` takes capabilities in
    `ordered_by_value`, and the corpus declares no explicit ranking. Inventing
    one here would be a policy decision made in a module rather than in a
    governed surface, so the file's own declaration order is used and an
    optional `value_rank` overrides it when the corpus chooses to state one.
    """
    doc = tomllib.loads((path or CAPABILITY_PROFILES).read_text(encoding="utf-8"))
    caps = doc.get("capability", {})
    if not caps:
        raise PlacementContractViolation(
            "capability_profiles.toml declares no capabilities -- "
            "DF-SURVIVAL-PROFILE has nothing to select from")
    ordered = sorted(enumerate(caps.items()),
                     key=lambda p: (p[1][1].get("value_rank", p[0]), p[0]))
    return {name: spec for _, (name, spec) in ordered}


def load_placement_tunables(path: Path | None = None) -> tuple[float, float]:
    """`(relocation_gain_threshold, placement_min_dwell_s)` from `tunables.toml`.

    Read rather than hardcoded: `INV-TUNE-1` makes the range governed, and a
    second copy of a governed number in code is a second thing to keep in step.
    """
    doc = tomllib.loads((path or TUNABLES).read_text(encoding="utf-8"))
    t = doc.get("tunable", {})
    try:
        gain = float(t["relocation_gain_threshold"]["default"])
        dwell = float(t["placement_min_dwell_s"]["default"])
    except KeyError as exc:
        raise PlacementContractViolation(
            f"tunables.toml is missing {exc} -- DF-PLACE's damping is governed "
            "configuration and is not defaulted in code") from exc
    return gain, dwell


def _numeric(value: Any) -> float | None:
    """A declared minimum, or None when the corpus says UNKNOWN.

    `UNKNOWN` is not zero. Zero would mean "needs nothing" and would admit the
    capability everywhere; None means "cannot be shown to fit", which under
    `unmeasured_disposition = UNAVAILABLE` excludes it.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _fit_failure(spec: dict, node: NodeProfile,
                 used_ram: float, used_storage: float,
                 pressure: float) -> str | None:
    """Why the capability does not fit on `node`, or None when it does."""
    if not node.satisfies_zone(spec.get("min_trust_zone", "Z0")):
        return (f"node trust zone {node.trust_zone} is weaker than the required "
                f"{spec.get('min_trust_zone')} (INV-TRUST-1)")

    if spec.get("requires_accelerator") and node.accelerator == "none":
        return "requires an accelerator; this node has none"

    if spec.get("requires_always_on") and node.availability_class != "always_on":
        return (f"requires an always_on node; this one is "
                f"{node.availability_class}")

    headroom = max(0.0, 1.0 - pressure)

    need_ram = _numeric(spec.get("min_memory_gb"))
    if need_ram is None:
        return ("min_memory_gb is UNKNOWN, so the fit cannot be demonstrated "
                "(unmeasured_disposition = UNAVAILABLE)")
    if used_ram + need_ram > node.ram_gb * headroom:
        return (f"needs {need_ram} GB RAM; {node.ram_gb * headroom - used_ram:.2f} GB "
                f"available at pressure {pressure}")

    need_storage = _numeric(spec.get("min_storage_gb"))
    if need_storage is None:
        return "min_storage_gb is UNKNOWN, so the fit cannot be demonstrated"
    if used_storage + need_storage > node.storage_gb * headroom:
        return (f"needs {need_storage} GB storage; "
                f"{node.storage_gb * headroom - used_storage:.2f} GB available")

    need_accel = _numeric(spec.get("min_accelerator_memory_gb"))
    if need_accel is not None and (node.accelerator_memory_gb or 0.0) < need_accel:
        return (f"needs {need_accel} GB accelerator memory; node has "
                f"{node.accelerator_memory_gb or 0.0}")

    min_tps = spec.get("sustained_tokens_per_sec_min")
    if min_tps != UNKNOWN and _numeric(min_tps) is not None:
        if not node.measured:
            return ("declares a sustained throughput minimum and this node's "
                    "throughput is not measured (INV-HW-2)")
        if node.measured_throughput < float(min_tps):
            return (f"needs {min_tps} tok/s sustained; node measured "
                    f"{node.measured_throughput}")

    return None


def survival_profile(node: NodeProfile,
                     requirements: dict[str, dict] | None = None,
                     pressure: float = 0.0) -> SurvivalProfile:
    """`DF-SURVIVAL-PROFILE` — the maximum this node can measurably sustain.

    The core is attempted first and is not negotiable: identity, task state,
    memory references, queued work, the event-log tail and one interaction
    surface. If the core does not fit, the caller gets `core_complete = False`
    and every missing piece named -- the corpus is explicit that this is
    reported, never silently partial.

    Then capabilities are added in value order while they fit. Every one that
    does not is returned as a `Degradation` with its reason, because
    `degradation_reporting.required = true` and a degraded system that cannot
    say what it lost is indistinguishable from a broken one.
    """
    if not 0.0 <= pressure < 1.0:
        raise PlacementContractViolation(
            f"pressure {pressure!r} must be in [0, 1) -- 1.0 would mean no node "
            "can host anything, which is a caller error, not a placement answer")
    reqs = requirements if requirements is not None else load_capability_requirements()

    core = {n: s for n, s in reqs.items() if s.get("survival_core")}
    extras = {n: s for n, s in reqs.items() if not s.get("survival_core")}

    # THE CORE IS ALL-OR-NOTHING, and this was got wrong the first time.
    # Folding it into the same greedy value-ordered loop as everything else
    # made it *partially* satisfiable, and the stress harness found what that
    # produces: on one node at pressure 0.75 the core lost `queued_work`
    # because earlier core members had eaten the storage budget, and at
    # pressure 0.95 three of them stopped fitting, freed their budget, and
    # `queued_work` CAME BACK. A core that reappears as conditions worsen is
    # not a core. `DF-SURVIVAL-PROFILE` reserves it in one step -- `set = core`
    # after a single `fits(core, node)` -- and that is what happens here.
    core_shortfall: list[Degradation] = []
    core_ram = sum(_numeric(s.get("min_memory_gb")) or 0.0 for s in core.values())
    core_storage = sum(_numeric(s.get("min_storage_gb")) or 0.0 for s in core.values())
    for name, spec in core.items():
        why = _fit_failure(spec, node, 0.0, 0.0, pressure)
        if why is not None:
            core_shortfall.append(Degradation(name, why))
    headroom = max(0.0, 1.0 - pressure)
    if core_ram > node.ram_gb * headroom:
        core_shortfall.append(Degradation(
            "<core as a whole>",
            f"the core needs {core_ram:.2f} GB RAM together; the node offers "
            f"{node.ram_gb * headroom:.2f} GB at pressure {pressure}"))
    if core_storage > node.storage_gb * headroom:
        core_shortfall.append(Degradation(
            "<core as a whole>",
            f"the core needs {core_storage:.2f} GB storage together; the node "
            f"offers {node.storage_gb * headroom:.2f} GB at pressure {pressure}"))

    core_complete = not core_shortfall
    selected: list[str] = list(core)
    degraded: list[Degradation] = []

    if not core_complete:
        # "attempt anyway; degradation reported". Nothing beyond the core is
        # added onto a node that cannot carry the core -- piling optional work
        # onto an over-committed host is the opposite of surviving.
        for name in extras:
            degraded.append(Degradation(
                name, "the survival core does not fit on this node, so no "
                      "capability beyond the core is attempted"))
        return SurvivalProfile(node.node_id, tuple(selected), tuple(degraded),
                               False, tuple(core_shortfall))

    used_ram, used_storage = core_ram, core_storage
    for name, spec in extras.items():
        why = _fit_failure(spec, node, used_ram, used_storage, pressure)
        if why is None:
            selected.append(name)
            used_ram += _numeric(spec.get("min_memory_gb")) or 0.0
            used_storage += _numeric(spec.get("min_storage_gb")) or 0.0
        else:
            degraded.append(Degradation(name, why))

    return SurvivalProfile(node.node_id, tuple(selected), tuple(degraded),
                           True, ())


def planned_map(profiles: dict[str, NodeProfile],
                requirements: dict[str, dict] | None = None,
                pressure: float = 0.0) -> dict[str, list[str]]:
    """The DESIGNED assignment: capability -> nodes that could carry it.

    `A-048.8` says to inspect "the planned capability placement map", and no
    such artifact exists in `contracts/`. Hand-authoring one would be a second
    copy of facts already in `capability_profiles.toml` and the enrollment
    profiles, and the two would drift. So it is DERIVED BY RULE, the way
    ADR-007 D2 derives a trust zone rather than accepting a declared one.

    THE AVAILABILITY FILTER IS DELIBERATELY ABSENT HERE. Including it would
    make `planned_assignment_violations` vacuous by construction -- it would be
    checking a map built to satisfy the very rule it checks, and would pass on
    every fabric including one where the phone is the only thing that could
    hold the control plane. The map answers "who *could* be designed to carry
    this"; the violation check answers "is that set acceptable".
    """
    reqs = requirements if requirements is not None else load_capability_requirements()
    out: dict[str, list[str]] = {}
    for name, spec in reqs.items():
        eligible = [nid for nid, p in sorted(profiles.items())
                    if _fit_failure(spec, p, 0.0, 0.0, pressure) is None]
        out[name] = eligible
    return out


def planned_assignment_violations(
        planned: dict[str, list[str]],
        profiles: dict[str, NodeProfile],
        requirements: dict[str, dict] | None = None) -> list[str]:
    """`INV-TRUST-2` over the PLAN, which is the only place it applies.

    `A-048.8` asserts this by inspecting the map rather than by observing that
    nothing bad happened at runtime, and the distinction is the point: a plan
    that assigns a continuity-critical capability to the phone alone is
    defective even on a day the phone stays awake. Runtime survival on such a
    node is `INV-PLACE-3` and is explicitly permitted.

    `planned` maps capability -> the node ids designed to carry it.
    """
    reqs = requirements if requirements is not None else load_capability_requirements()
    violations: list[str] = []

    for capability, node_ids in sorted(planned.items()):
        spec = reqs.get(capability)
        if spec is None:
            violations.append(
                f"{capability}: planned but not declared in capability_profiles.toml")
            continue
        # Continuity-critical == the survival core plus anything the corpus
        # marks as needing an always-on host.
        critical = bool(spec.get("survival_core")) or bool(spec.get("requires_always_on"))
        if not critical:
            continue
        if not node_ids:
            # NOT AN INV-TRUST-2 VIOLATION, and conflating the two would be a
            # false report. A capability with no eligible node on this fabric
            # is unplaceable -- usually because its requirements are still
            # `UNKNOWN` and INV-HW-2 makes UNKNOWN mean UNAVAILABLE. That is a
            # measurement gap, not a design that leans on the phone.
            # `unplaceable()` reports it through its own channel.
            continue
        classes = []
        for nid in node_ids:
            p = profiles.get(nid)
            if p is None:
                violations.append(f"{capability}: planned on unknown node {nid!r}")
                classes = []
                break
            classes.append(p.availability_class)
        if classes and all(c in NON_CONTINUITY_CLASSES for c in classes):
            violations.append(
                f"{capability}: continuity-critical but every planned host is "
                f"{sorted(set(classes))} -- INV-TRUST-2 forbids DESIGNING a "
                f"continuity-critical capability onto foreground_only/on_demand "
                f"nodes alone")

    return violations


def unplaceable(plan: dict[str, list[str]],
                profiles: dict[str, NodeProfile],
                requirements: dict[str, dict] | None = None) -> dict[str, str]:
    """Capabilities no node on this fabric can be shown to carry, and why.

    Reported separately from `planned_assignment_violations` because the two
    are different failures with different remedies. An `INV-TRUST-2` violation
    is a DESIGN defect: rewrite the assignment. An unplaceable capability is a
    MEASUREMENT gap: run the spike and fill the number in.

    On today's tree this is not empty, and it should not be pretended away.
    `control_plane_host`, `local_inference_*`, `voice_interaction`,
    `perception_vision`, `autonomous_actuation` and
    `background_continuous_operation` all declare `UNKNOWN` minimums pending
    `SPIKE-001`, so `unmeasured_disposition = "UNAVAILABLE"` makes them
    unplaceable by rule. That is the honest state: the fabric cannot yet
    demonstrate it can host its own control plane, and a build that assumed it
    could would look complete and be guessing.
    """
    reqs = requirements if requirements is not None else load_capability_requirements()
    out: dict[str, str] = {}
    for capability, node_ids in sorted(plan.items()):
        if node_ids:
            continue
        spec = reqs.get(capability, {})
        reasons = sorted({_fit_failure(spec, p, 0.0, 0.0, 0.0) or ""
                          for p in profiles.values()} - {""})
        out[capability] = "; ".join(reasons) or "no reachable node"
    return out


class Placement:
    """`DF-PLACE`, holding only what the decision needs.

    No node is this object's home and it stores no preference. The only state
    it keeps is the damping configuration, which is governed.
    """

    def __init__(self, *, bus: EventBus | None = None,
                 requirements: dict[str, dict] | None = None,
                 relocation_gain: float | None = None,
                 min_dwell_s: float | None = None,
                 damping: bool = True) -> None:
        gain, dwell = load_placement_tunables()
        self.bus = bus
        self.requirements = (requirements if requirements is not None
                             else load_capability_requirements())
        self.relocation_gain = gain if relocation_gain is None else relocation_gain
        self.min_dwell_s = dwell if min_dwell_s is None else min_dwell_s
        # `damping=False` exists so A-048.3's negative control can be built
        # from the real module rather than from a hand-written stub that might
        # differ in some other way and pass for the wrong reason.
        self.damping = damping

    def _emit(self, type: str, subject: str, payload: dict) -> None:
        if self.bus is not None:
            self.bus.publish(type, subject, payload, component="placement")

    def decide(self, *, reachable: dict[str, NodeProfile], current: str | None,
               hysteresis: Hysteresis | None = None,
               pressure: float = 0.0) -> Decision:
        hysteresis = hysteresis or Hysteresis()
        live = {nid: p for nid, p in reachable.items() if p.reachable}

        hosts = {nid: p for nid, p in live.items() if is_full_host(p)}

        # 1. Nothing capable of hosting -> survive on the best thing left.
        if not hosts:
            candidates = {nid: p for nid, p in live.items() if p.survival_capable}
            if not candidates:
                degs = tuple(
                    Degradation(nid, f"trust zone {p.trust_zone}, survival_capable="
                                     f"{p.survival_capable}")
                    for nid, p in sorted(live.items()))
                self._emit("placement.survival_impossible", current or "-",
                           {"reachable": sorted(live), "reason": "no survival-capable node"})
                return SurvivalImpossible(
                    "no reachable node can host and none is survival_capable; "
                    "holding state on a node that fails the security baseline is "
                    "not the fallback (INV-TRUST-1)", degs)

            best = max(candidates.values(), key=lambda p: (p.score()))
            prof = survival_profile(best, self.requirements, pressure)
            if not prof.core_complete:
                self._emit("placement.survival_impossible", best.node_id,
                           {"node": best.node_id,
                            "missing": [d.capability for d in prof.degradations]})
                return SurvivalImpossible(
                    f"{best.node_id} is survival_capable but cannot carry the core",
                    prof.degradations)
            self._emit("placement.survival_entered", best.node_id,
                       {"node": best.node_id, "capabilities": list(prof.capabilities),
                        "degradations": [d.capability for d in prof.degradations]})
            for d in prof.degradations:
                self._emit("placement.capability_degraded", best.node_id,
                           {"capability": d.capability, "reason": d.reason})
            return EnterSurvival(best.node_id, prof,
                                 "no full host reachable (INV-PLACE-3)")

        best = max(hosts.values(), key=lambda p: p.score())

        if current is not None and best.node_id == current:
            return Keep("already on the best reachable host", current)

        cur = reachable.get(current) if current else None
        # INV-PLACE-2, and see the module docstring on why this precedes the
        # gates rather than following them: degradation or loss of the current
        # host bypasses both.
        #
        # RUNNING IN SURVIVAL IS ITSELF A DEGRADATION, so a survival node is
        # never held onto by the dwell timer once a full host returns. Without
        # this, A-048.7 ("restore a full host -> VESPER relocates back off the
        # survival node") would depend on how long survival happened to last:
        # under ten minutes and the system would politely stay degraded.
        forced = (cur is None or not cur.reachable or cur.degraded
                  or not is_full_host(cur))
        if forced:
            prof = survival_profile(best, self.requirements, pressure)
            self._emit("placement.relocating", best.node_id,
                       {"from": current, "to": best.node_id, "forced": True})
            return Relocate(best.node_id, prof,
                            "current host is unreachable or degraded -- damping "
                            "bypassed (INV-PLACE-2)")

        if self.damping:
            needed = cur.scalar_score() * (1.0 + self.relocation_gain)
            if best.scalar_score() < needed:
                return Keep(
                    f"{best.node_id} scores {best.scalar_score():.1f}, under the "
                    f"{needed:.1f} required to beat {current} by "
                    f"{self.relocation_gain:.0%} -- migration is not free",
                    current)
            if hysteresis.since_last_move_s < self.min_dwell_s:
                return Keep(
                    f"moved {hysteresis.since_last_move_s:.0f}s ago, under the "
                    f"{self.min_dwell_s:.0f}s minimum dwell -- refused, not queued",
                    current)

        prof = survival_profile(best, self.requirements, pressure)
        self._emit("placement.relocating", best.node_id,
                   {"from": current, "to": best.node_id, "forced": False})
        for d in prof.degradations:
            self._emit("placement.capability_degraded", best.node_id,
                       {"capability": d.capability, "reason": d.reason})
        return Relocate(best.node_id, prof,
                        f"{best.node_id} beats {current} by more than "
                        f"{self.relocation_gain:.0%}")
