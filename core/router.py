"""Difficulty-based model routing against MEASURED node capability (A-022).

TWO RULES DECIDE EVERY LINE HERE.

INV-HW-1: routing may never name a product. Not "prefer the desktop", not "the
phone is slow" -- those are facts about hardware that will be replaced, and a
routing table written in product names has to be rewritten when it is.
Substituting hardware must be a PROFILE change, never a migration. CI-007
scans this directory for product names, and the check is the cheap half; the
expensive half is that a profile-shaped router keeps working when the fabric
changes underneath it.

INV-HW-2: routing selects on MEASURED values, never declared ones. A profile
whose throughput is UNKNOWN is treated as UNAVAILABLE, never as available --
fail-closed, because the alternative routes real work to a node on the strength
of a datasheet.

WHAT SPIKE-001 CHANGED ABOUT THE SHAPE OF THIS FILE, and it is not just the
numbers:

  1. THE ROUTER MUST USE WALL-CLOCK THROUGHPUT, NOT GENERATION THROUGHPUT.
     Measured 2026-08-14: under concurrent load the generation rate reported
     the node getting FASTER (+3.3%) while wall-clock throughput fell 42%. A
     router calibrated on the generation figure sees no contention at all.

  2. A TIER'S RATE IS A FUNCTION OF CONTEXT, NOT A SCALAR. The strong tier
     decays 39-47% across a ten-minute run, attributed to KV-cache growth
     (~17.6 us per token of context). 6.79 tok/s is the rate at ~4.2k tokens of
     context, not a floor. So `estimate_seconds` takes the context length and
     applies the measured slope instead of multiplying by one number.

  3. RESIDENCY COSTS HOST RAM, NOT JUST VRAM. Measured: a fully GPU-offloaded
     model still costs ~3.7 GB of system RAM, and a partially-offloaded strong
     model costs ~13 GB. On a 15.9 GB node with the owner's working set
     present, the strong tier does not fit -- it pages at 660 pages/sec. A
     router that checks only VRAM will happily thrash the machine.

  4. UNDER LOAD, THE CHEAPEST-LOOKING TIER IS THE WORST BUY. Contention cost
     runs inversely to model speed (-42% at draft, -13% at small, unresolvable
     at standard), because per-request overhead is a large fraction of a short
     request. On identical weights, the longer-request tier beat the shorter
     one by 32% under load. So `select` weighs contention when the node is busy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bus import EventBus
from .latency import ALPHA_DOWN, ALPHA_UP, Observation  # noqa: F401

# contracts/entities/model_profile.schema.json capability_tier
TIERS = ("draft", "small", "standard", "strong")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

DIFFICULTY = ("trivial", "easy", "moderate", "hard")
# The minimum tier each difficulty is allowed to route to. A router may go
# STRONGER than this (capacity permitting) but never weaker: routing hard work
# to a draft model is the failure this mapping exists to prevent.
DIFFICULTY_FLOOR = {"trivial": "draft", "easy": "small",
                    "moderate": "standard", "hard": "strong"}

UNKNOWN = "UNKNOWN"

# The turn size a latency ESTIMATE is expressed in, so that a figure derived
# from throughput and a figure observed on the wire are the same quantity and
# can be compared at all. Anchored on `voice.toml [brevity] default_words = 40`
# -- roughly 60 tokens of English -- rather than picked: a conversational turn
# is what this axis is ordering.
#
# ITS VALUE DOES NOT CHANGE ANY ORDERING AMONG UNOBSERVED PROFILES, because it
# divides every one of them by the same constant. It matters only where an
# estimate is compared against a real observation, which is the comparison it
# exists to keep honest.
LATENCY_REFERENCE_TOKENS = 64


class NoRouteAvailable(Exception):
    """No profile satisfies the request. Fail-closed; never silently downgrade."""


@dataclass(slots=True)
class MeasuredProfile:
    """One measured (tier, node-class) capability. Every field is measured.

    `profile_id` is a PROFILE name, never a device name (INV-HW-1). The node it
    was measured on is recorded as a class -- `accelerated`, `cpu_only` -- so
    substituting hardware is a profile change.
    """

    profile_id: str
    tier: str
    node_class: str
    # Wall clock, minute-10, concurrent condition. The figure the router uses.
    wall_tokens_per_sec: float | None
    wall_tokens_per_sec_idle: float | None
    # Measured decay with context, microseconds of extra per-token cost per
    # token of context already generated. None where it was not measured.
    context_slowdown_us_per_token: float | None = None
    measured_at_context_tokens: int | None = None
    # Host RAM the model costs while resident. NOT VRAM -- see module docstring.
    host_ram_gb: float | None = None
    vram_gb: float | None = None
    measured: bool = False
    source: str = ""
    # WHICH NODE THESE NUMBERS DESCRIBE. A throughput figure is a fact about a
    # particular machine, and a profile that does not say which one can be
    # served by any machine at all -- which is how a call answered here came to
    # be attributed to a rate measured somewhere else on 2026-08-24. `None`
    # means the profile describes a node CLASS rather than an enrolled node;
    # `select` records that rather than treating it as a clean bill.
    node_id: str | None = None

    def available(self) -> bool:
        """INV-HW-2: unmeasured is UNAVAILABLE, never available."""
        return bool(self.measured) and self.wall_tokens_per_sec is not None

    def rate_at_context(self, context_tokens: int) -> float | None:
        """Throughput at a given context length, from the measured slope.

        WHERE NO SLOPE WAS MEASURED, THE RATE IS TREATED AS FLAT. This
        docstring said the opposite until 2026-08-24 -- "returns None rather
        than assuming the rate is flat" -- and the code has always returned the
        flat rate. The prose was describing a behaviour that would break the
        router: only the strong tier has a measured slope, so returning None
        would make draft, small and standard unroutable at every context
        length, and a fail-closed router that can reach nothing is not
        fail-closed, it is off.

        Flat is also the better-supported reading for those tiers: SPIKE-001
        3.1 measured them within +/-3% across a ten-minute run, in six runs
        each. The tier where it is NOT supported is exactly the one that has a
        slope -- the MoE lost 39-47% of its rate, sign-consistent in 6 of 6.

        But the assumption is still an assumption, and an unmeasured tier that
        decays would be silently overstated here. So `select` NAMES it in the
        decision rather than leaving the reader to infer it from an absent
        field.
        """
        if self.wall_tokens_per_sec is None:
            return None
        slope = self.context_slowdown_us_per_token
        base_ctx = self.measured_at_context_tokens
        if slope is None or base_ctx is None:
            return self.wall_tokens_per_sec
        ms_per_token = 1000.0 / self.wall_tokens_per_sec
        ms_per_token += slope * (context_tokens - base_ctx) / 1000.0
        if ms_per_token <= 0:
            return None
        return 1000.0 / ms_per_token


@dataclass(slots=True)
class RouteDecision:
    profile_id: str
    tier: str
    difficulty: str
    estimated_seconds: float | None
    factors: list = field(default_factory=list)
    rejected: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id, "tier": self.tier,
            "difficulty": self.difficulty,
            "estimated_seconds": self.estimated_seconds,
            "deciding_factors": self.factors,
            "rejected_candidates": self.rejected,
        }


class Router:
    """Selects a model profile for a task. Every decision is inspectable.

    A-022 requires the deciding factors to be NAMED in telemetry, not merely
    that a decision was recorded. A route nobody can explain cannot be argued
    with, and a router nobody can argue with is one that quietly gets worse.
    """

    def __init__(self, bus: EventBus, profiles: list[MeasuredProfile],
                 *, enrollment: Any = None) -> None:
        self._bus = bus
        self._profiles = list(profiles)
        # A-042.4: "a node with no measured profile is NEVER ROUTED TO." The
        # predicate has existed in `core/enrollment.py` since F4 as
        # `EnrolledNode.routable()`, and no routing decision has ever called
        # it: `MeasuredProfile` had no node to ask about. The invariant was
        # testable in isolation and inapplicable in practice, which is the same
        # gap the gateway had -- a rule with no seam to the thing it governs.
        #
        # Optional because a profile describing a node CLASS has no node to
        # check. It is NOT optional for a profile that names one: see `select`.
        self._enrollment = enrollment
        self._observed: dict[str, Observation] = {}

    def add(self, profile: MeasuredProfile) -> None:
        self._profiles.append(profile)

    def observe(self, profile_id: str, seconds: float) -> None:
        """Record what a real call to this profile actually cost in wall time.

        CALLED BY WHOEVER MADE THE CALL, not by the router, because the router
        does not make calls -- it names a profile and something else spends the
        seconds. An uncalled `observe` is the built-and-unreached shape again,
        so `CI-071` asserts the answer path calls it.
        """
        if seconds <= 0:
            return
        o = self._observed.get(profile_id)
        if o is None:
            self._observed[profile_id] = Observation(profile_id, seconds)
        else:
            o.update(seconds)

    def observed(self, profile_id: str) -> Observation | None:
        return self._observed.get(profile_id)

    def select(self, difficulty: str, *, context_tokens: int = 2048,
               host_ram_free_gb: float | None = None,
               node_busy: bool = False,
               allow_degraded: bool = False,
               exclude: set | None = None,
               prefer: str = "cost",
               task_id: str | None = None) -> RouteDecision:
        """Pick a profile. Fail-closed by default.

        WHAT HAPPENS WHEN THE REQUIRED TIER DOES NOT FIT is a real decision and
        not an error case to paper over. Measured 2026-08-15: with the owner's
        working set resident this node has 6.57 GB free and the strong tier
        needs ~13 GB, so `hard` work genuinely has no home while the owner is
        at the machine. Two honest answers exist and silently picking a weaker
        model is neither of them:

          allow_degraded=False (default) -- raise. The caller defers or queues
              the task for a period when the capacity exists. Routing hard work
              to a draft model produces a confidently wrong answer, which is
              worse than a late one.

          allow_degraded=True -- return the strongest profile that DOES fit,
              and emit `route.degraded` naming what was asked for, what was
              given, and why. RB-022: degradation is REPORTED, never silent.
        """
        if difficulty not in DIFFICULTY:
            raise ValueError(f"unknown difficulty {difficulty!r}, expected {DIFFICULTY}")
        if prefer not in ("cost", "latency"):
            raise ValueError(
                f"unknown prefer={prefer!r}, expected 'cost' or 'latency'. "
                "Refused rather than defaulted: a typo would silently restore "
                "the ranking this parameter exists to override.")
        floor = DIFFICULTY_FLOOR[difficulty]
        factors: list[str] = [
            f"difficulty={difficulty}", f"tier_floor={floor}",
            f"context_tokens={context_tokens}",
            "selects_on=wall_clock_throughput (generation-time throughput is "
            "blind to contention: measured +3.3% while wall clock fell 42%)",
        ]
        rejected: list[dict] = []
        candidates: list[tuple[float, MeasuredProfile, float | None]] = []

        excluded = set(exclude or ())
        for p in self._profiles:
            if p.profile_id in excluded:
                # Already tried and spent this run. Excluded rather than
                # deprioritised: a profile whose providers are exhausted will
                # be exhausted again a millisecond later, and re-selecting it
                # would spin rather than degrade.
                rejected.append({"profile_id": p.profile_id,
                                 "reason": "already attempted and exhausted "
                                           "for this request"})
                continue
            if TIER_RANK[p.tier] < TIER_RANK[floor]:
                rejected.append({"profile_id": p.profile_id,
                                 "reason": f"tier {p.tier} below floor {floor}"})
                continue
            if not p.available():
                # INV-HW-2, fail-closed.
                rejected.append({"profile_id": p.profile_id,
                                 "reason": "throughput UNKNOWN -- unmeasured is "
                                           "treated as UNAVAILABLE (INV-HW-2)"})
                continue
            if (host_ram_free_gb is not None and p.host_ram_gb is not None
                    and p.host_ram_gb > host_ram_free_gb):
                rejected.append({
                    "profile_id": p.profile_id,
                    "reason": (f"needs {p.host_ram_gb} GB host RAM, "
                               f"{host_ram_free_gb} GB free -- residency costs "
                               "system RAM, not only VRAM; measured 660 pages/sec "
                               "when this was ignored")})
                continue
            if p.node_id is not None:
                # A-042.4, applied to an actual decision. Fail-closed in BOTH
                # directions: an unroutable node is refused, and so is a
                # profile naming a node we have no registry to ask about --
                # unverifiable is UNAVAILABLE, exactly as UNKNOWN is.
                if self._enrollment is None:
                    rejected.append({
                        "profile_id": p.profile_id,
                        "reason": (f"profile is bound to node {p.node_id!r} but "
                                   "no enrollment registry is attached, so its "
                                   "routability cannot be checked (A-042.4)")})
                    continue
                n = self._enrollment.get(p.node_id)
                if n is None or not n.routable():
                    rejected.append({
                        "profile_id": p.profile_id,
                        "reason": (f"node {p.node_id!r} is not routable: "
                                   f"{'not enrolled' if n is None else n.state}"
                                   " -- a node with no measured profile is "
                                   "never routed to (A-042.4)")})
                    continue
            rate = p.rate_at_context(context_tokens)
            if rate is None or rate <= 0:
                rejected.append({"profile_id": p.profile_id,
                                 "reason": "no usable rate at this context length"})
                continue
            # SR-009, VERBATIM: "Model router sends EASY tasks to SMALLER
            # models and hard tasks to stronger models." The floor is the
            # REQUIREMENT, not the minimum bid -- every tier above it is paid
            # for in seconds, and the measured rates price that plainly: the
            # strong tier answers a trivial task in 202 s that the draft tier
            # answers in 25 s. So rank on DISTANCE ABOVE THE FLOOR ascending,
            # and break ties on throughput.
            #
            # Until 2026-08-24 this read `TIER_RANK[p.tier] * 1e6 + rate`
            # sorted descending -- "prefer the strongest tier that fits". The
            # guard was "that fits", and nothing ever made a stronger tier not
            # fit: `from_spike_results` left `host_ram_gb` None on every
            # profile it built, so the one constraint that could reject strong
            # was unreachable in production and present only in A-022's
            # hand-built doubles. Result: EVERY difficulty routed to strong,
            # with A-022 green the whole time.
            #
            # `idx` is a tiebreaker and not a preference. Without it, two
            # profiles at equal distance and equal rate would fall through to
            # comparing MeasuredProfile, which has slots and no ordering, and
            # the router would raise TypeError instead of routing.
            # WHICH AXIS RANKS THEM IS THE CALLER'S SITUATION, NOT A CONSTANT.
            #
            # `prefer="cost"` is the rule above and stays the default: distance
            # above the floor ascending, ties on throughput. It is correct
            # wherever a stronger tier is bought with seconds, which is true of
            # every rung on our own fabric -- strong answers a trivial task in
            # 202 s that draft answers in 25 s.
            #
            # IT IS EXACTLY WRONG FOR A REMOTE RUNG, and the premise is the part
            # that fails rather than the logic. "Strong" on a supplier's fabric
            # is somebody else's accelerator, and it is not paid for in our
            # seconds at all. Measured 2026-08-26 on the same 45-character
            # prompt: the standard rung this router preferred took 25.9 s and
            # 68.7 s on two consecutive tries; the strong rung it rejected as
            # too expensive answered in 0.63 s, 0.77 s and 0.61 s. It chose a
            # profile 40x slower in order to save a cost nobody was charging.
            #
            # So `prefer="latency"` ranks on estimated seconds-to-answer and
            # keeps distance-above-floor as the tiebreaker. THE FLOOR IS NOT
            # TOUCHED by either axis: SR-009 still forbids routing hard work
            # below `strong`, and this only decides which of the profiles
            # ALREADY ELIGIBLE gets the request.
            #
            # THE TWO ESTIMATES ARE NOT THE SAME QUANTITY, and the first
            # version of this got the SCALES wrong rather than the logic. It
            # derived the unobserved figure as `context_tokens / rate` -- the
            # time to emit 2048 tokens -- and compared it against observations
            # of single conversational turns. 40 s of enrolment-derived estimate
            # sat beside 40 s of measured misery and they are not the same 40 s;
            # a rung caught taking 40 s live still ranked ahead of a healthy one.
            # `CI-071` found it, which is what a negative control is for.
            #
            # So both sides are now expressed as SECONDS FOR ONE TURN. The
            # reference size cancels out entirely when ranking two unobserved
            # profiles against each other -- it is a common factor -- and it
            # matters only where an estimate meets an observation, which is
            # exactly the comparison it was chosen to make honest.
            #
            # The remaining bias is deliberate: a derived figure cannot see the
            # supplier's queue, so an unobserved profile is estimated
            # OPTIMISTICALLY, which is what makes it get tried at all. One
            # request later it has an observation and corrects itself. Pessimism
            # here would be self-sealing -- never chosen, never measured, never
            # chosen.
            o = self._observed.get(p.profile_id)
            seconds = (o.seconds if o is not None
                       else LATENCY_REFERENCE_TOKENS / rate)
            if prefer == "latency":
                key = (seconds, TIER_RANK[p.tier] - TIER_RANK[floor])
            else:
                key = (TIER_RANK[p.tier] - TIER_RANK[floor], -rate)
            candidates.append((key, len(candidates), p, rate))

        degraded_from = None
        if not candidates and allow_degraded:
            # Nothing at or above the floor fits. Look BELOW it, and report
            # loudly if something does. This is the only path in this file that
            # returns a tier weaker than the difficulty demands, and it cannot
            # be taken without the caller asking for it by name.
            for p in self._profiles:
                if p.profile_id in excluded:
                    continue
                if TIER_RANK[p.tier] >= TIER_RANK[floor] or not p.available():
                    continue
                if (host_ram_free_gb is not None and p.host_ram_gb is not None
                        and p.host_ram_gb > host_ram_free_gb):
                    continue
                rate = p.rate_at_context(context_tokens)
                if rate and rate > 0:
                    # Mirrored deliberately: distance from the floor, ascending,
                    # measured downward. Below the floor the nearest profile is
                    # the STRONGEST one available, which is what the docstring
                    # above promises a degraded route returns.
                    candidates.append(((TIER_RANK[floor] - TIER_RANK[p.tier],
                                        -rate), len(candidates), p, rate))
            if candidates:
                degraded_from = floor
                factors.append(
                    f"DEGRADED from {floor}: no profile at or above the floor "
                    "fits this node's measured capacity")

        if not candidates:
            self._bus.publish("route.no_route", subject=task_id or "unassigned",
                              payload={"difficulty": difficulty,
                                       "rejected": rejected,
                                       "allow_degraded": allow_degraded,
                                       "reason": ("fail-closed: no measured profile "
                                                  "satisfies the request. The task "
                                                  "defers or queues rather than "
                                                  "being answered badly.")},
                              component="router")
            raise NoRouteAvailable(
                f"no measured profile available for difficulty={difficulty!r} "
                f"at context={context_tokens}. Rejected: {rejected}")

        if node_busy:
            factors.append(
                "node_busy=True: contention cost runs INVERSELY to model speed "
                "(measured -42% draft, -31% draft-3B, -13% small, unresolvable "
                "at standard), so the fastest-looking tier loses the most")

        candidates.sort()
        *_, best, rate = candidates[0]
        obs = self._observed.get(best.profile_id)
        factors.append(
            f"prefer={prefer} ("
            + ("ranked on estimated seconds-to-answer, floor unchanged; a "
               "remote strong rung is not paid for in our seconds"
               if prefer == "latency" else
               "ranked on distance above the tier floor, ties on throughput")
            + ")")
        if obs is not None:
            # PROVENANCE ON THE LIVE FIGURE, same as every other number here.
            # `samples` and `worst` are carried because an EWMA alone cannot be
            # audited: 3 s could be three steady calls or one 0.5 s and one 60 s.
            factors.append(
                f"observed_seconds={obs.seconds:.2f} over {obs.samples} live "
                f"call(s), worst {obs.worst_seconds:.2f}s -- live wall clock, "
                "not the enrolment sweep")
        else:
            factors.append(
                "no live observation for this profile yet; ranked on the "
                "enrolment sweep, which cannot see the supplier's queue")
        est = context_tokens / rate if rate else None
        factors.append(f"selected_rate_tokens_per_sec={rate:.2f}")
        if best.context_slowdown_us_per_token is not None:
            factors.append(
                f"rate adjusted for context: {best.context_slowdown_us_per_token} us "
                "per token of context (KV-cache growth, measured)")
        factors.append(f"measured_source={best.source}")
        if best.context_slowdown_us_per_token is None:
            factors.append(
                "FLAT-ASSUMED: no context slope measured for this profile, so "
                f"the rate is treated as constant at {context_tokens} tokens. "
                "Measured on the tier that HAS a slope: 39-47% lost across a "
                "ten-minute run")
        if best.node_id is None:
            # RECORD WHAT WAS COMPARED. This profile names no node, so nothing
            # ties the rate above to the machine that will serve the call. It
            # is a class-level figure being used as if it were a node-level
            # one, which is defensible only while it is SAID.
            factors.append(
                "UNBOUND: this profile names no node, so its measured rate "
                "describes a node CLASS and not whatever answers (A-042.4 "
                "cannot be applied)")
        else:
            # READ BACK, NOT ASSERTED. An earlier version of this line printed
            # "(routable, A-042.4 checked)" from the fact that `node_id` was
            # set. A build with the check disabled emitted that string over an
            # unroutable node -- a decision testifying to an inspection it had
            # not performed, which is worse than silence because it reads as
            # evidence. The state is now re-read from the registry at the
            # moment it is recorded.
            n = self._enrollment.get(best.node_id) if self._enrollment else None
            factors.append(
                f"node_id={best.node_id} state="
                f"{n.state if n is not None else 'NOT_ENROLLED'} "
                f"routable={n.routable() if n is not None else False}")
        if host_ram_free_gb is not None and best.host_ram_gb is None:
            # RECORD WHAT WAS COMPARED. A RAM constraint was in force and this
            # profile was not weighed against it, because nothing has measured
            # what it costs to keep resident -- the rejection test reads a
            # missing figure as "no constraint recorded" and lets it through.
            #
            # That is permissive in the one direction INV-HW-2 is otherwise
            # strict about, and it is load-bearing today: SPIKE-001 3.2 measured
            # residency for exactly two models, so the strong tier's OTHER
            # profile passes this gate unweighed while 3.2's own finding is
            # "the strong tier and the owner's working set cannot coexist on
            # this node". Making the gap fail-closed here would reject the
            # draft and small tiers too -- 3.2 never measured those either --
            # and leave trivial work with no route at all. So the honest move
            # is to name it in the decision rather than to silently pass or
            # bluntly refuse. The fix is a measurement, not a branch.
            factors.append(
                "UNWEIGHED: residency cost for this profile is UNMEASURED, so "
                f"the {host_ram_free_gb} GB constraint could not be applied to "
                "it (SPIKE-001 3.2 covers two models only)")

        d = RouteDecision(best.profile_id, best.tier, difficulty, est,
                          factors, rejected)
        if degraded_from is not None:
            # RB-022: reported, never silent. A caller that gets a weaker model
            # than it asked for must be able to see that it did.
            self._bus.publish(
                "route.degraded", subject=task_id or "unassigned",
                payload={"difficulty": difficulty, "required_tier": degraded_from,
                         "granted_tier": best.tier, "profile_id": best.profile_id,
                         "rejected": rejected,
                         "note": ("capability degradation is REPORTED, never "
                                  "silent -- the answer from a weaker tier is "
                                  "not the answer that was asked for")},
                component="router")
        self._bus.publish("route.selected", subject=task_id or "unassigned",
                          payload={**d.to_dict(), "degraded_from": degraded_from},
                          component="router")
        return d

    # ------------------------------------------------------------------ load

    @staticmethod
    def _residency_costs(results_dir: Path) -> dict:
        """Measured host-RAM cost of keeping a model resident, per model.

        SPIKE-001 3.2 measured this and the router did not read it. That is the
        half of the residency defect the selection logic could not fix on its
        own: `select` has rejected on `host_ram_gb` since it was written, but
        `from_spike_results` never set the field, so the constraint was live in
        A-022's hand-built doubles and structurally unreachable in production.
        Every profile the router actually ran with had `host_ram_gb = None`,
        which the rejection test reads as "no constraint recorded".

        The cost is a DIFFERENCE against the no-model baseline, not the
        condition's own reading -- what the router needs to know is what
        loading the model takes away, and 3.2's absolute figures include the
        owner's working set. Both sides use `available_gb_min`, the worst
        sample in the window, because headroom that exists only on average is
        not headroom.

        Returns {model_key: (cost_gb, provenance)}. A model 3.2 did not measure
        is ABSENT rather than zero -- INV-HW-2, and a zero here would read as
        "free to keep resident", which is the most expensive possible mistake.
        """
        f = Path(results_dir) / "SPIKE-001-3.2-headroom-summary.json"
        if not f.exists():
            return {}
        d = json.loads(f.read_text(encoding="utf-8"))
        conditions = d.get("conditions") or []
        baseline = None
        for c in conditions:
            if "no model resident" in (c.get("label") or ""):
                baseline = c.get("available_gb_min")
                break
        if baseline is None:
            # Without the baseline the differences are not computable. Return
            # nothing rather than fall back to the absolute readings, which
            # would attribute the owner's whole working set to the model.
            return {}
        out: dict = {}
        for c in conditions:
            label = c.get("label") or ""
            avail = c.get("available_gb_min")
            if avail is None or "no model resident" in label:
                continue
            # 3.2 names the model inside the parentheses; 3.1 names it in
            # `model_path`. The two documents spell it differently, so the key
            # is the leading whitespace-delimited token of the parenthesised
            # part -- "Qwen3-8B Q4_K_M, -ngl 99, ..." -> "Qwen3-8B".
            m = re.search(r"\(([^),]+)", label)
            if not m:
                continue
            key = m.group(1).strip().split()[0]
            out[key] = (round(baseline - avail, 2),
                        f"SPIKE-001-3.2 headroom ({baseline} - {avail} GB measured)")
        return out

    @staticmethod
    def from_spike_results(results_dir: Path, bus: EventBus) -> "Router":
        """Build profiles from SPIKE-001 3.1 v4 reports.

        Reads ONLY reports at schema_version >= 4, because v3 aggregated the
        two headline figures over different windows and its wall-clock number
        is the whole-run average -- 27% above the settled rate on a decaying
        model. Loading a v3 report here would put that error in the router.

        The rate taken is `median_effective_tokens_per_sec`, which is the field
        each report's own `router_should_use` names: it is wall-clock and
        therefore sees contention that the generation-time figure is blind to.

        No DEVICE names are constructed from filenames (INV-HW-1). The profile
        id is tier + node class + the report's own variant token, which is what
        makes it UNIQUE: two draft reports and two strong reports exist, and
        until 2026-08-24 all four collapsed onto two ids, so a decision naming
        `strong-accelerated` could mean either the 7.12 tok/s MoE or the 3.05
        tok/s dense model. An audit record that cannot say which model ran is
        not an audit record. The variant token is read from data rather than
        written into this file, so no product literal enters `core/`.
        """
        residency = Router._residency_costs(Path(results_dir))
        profiles: list[MeasuredProfile] = []
        for f in sorted(Path(results_dir).glob("SPIKE-001-3.1-v3-*.json")):
            if "concurrent" not in f.name:
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("schema_version", 0) < 4:
                continue
            t = d.get("throughput") or {}
            tier = t.get("tier")
            if tier not in TIERS:
                continue
            idle_f = f.with_name(f.name.replace("concurrent", "idle"))
            idle_rate = None
            if idle_f.exists():
                di = json.loads(idle_f.read_text(encoding="utf-8"))
                idle_rate = (di.get("throughput") or {}).get(
                    "median_effective_tokens_per_sec")
            # SPIKE-001-3.1-v3-<tier>-<variant>-<condition>.json
            parts = f.stem.split("-")
            variant = parts[5] if len(parts) > 5 else str(len(profiles))
            model_path = (t.get("model_path") or "").replace("\\", "/")
            model_file = model_path.rsplit("/", 1)[-1]
            host_ram = None
            residency_src = ""
            for key, (cost, prov) in residency.items():
                # Anchored at the start and required to end on a separator, so
                # a shorter key cannot claim a longer model's report.
                if re.match(re.escape(key) + r"[-_.]", model_file):
                    host_ram, residency_src = cost, " + " + prov
                    break
            profiles.append(MeasuredProfile(
                profile_id=f"{tier}-accelerated-{variant.lower()}",
                tier=tier,
                node_class="accelerated",
                wall_tokens_per_sec=t.get("median_effective_tokens_per_sec"),
                wall_tokens_per_sec_idle=idle_rate,
                host_ram_gb=host_ram,
                measured=True,
                source=f.name + residency_src,
            ))
        return Router(bus, profiles)
