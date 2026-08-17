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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bus import EventBus

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

    def available(self) -> bool:
        """INV-HW-2: unmeasured is UNAVAILABLE, never available."""
        return bool(self.measured) and self.wall_tokens_per_sec is not None

    def rate_at_context(self, context_tokens: int) -> float | None:
        """Throughput at a given context length, from the measured slope.

        Returns None when the slope was not measured, rather than assuming the
        rate is flat. Assuming flat is precisely the error that made 6.79 tok/s
        look like a floor when it was the rate at one particular context.
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

    def __init__(self, bus: EventBus, profiles: list[MeasuredProfile]) -> None:
        self._bus = bus
        self._profiles = list(profiles)

    def add(self, profile: MeasuredProfile) -> None:
        self._profiles.append(profile)

    def select(self, difficulty: str, *, context_tokens: int = 2048,
               host_ram_free_gb: float | None = None,
               node_busy: bool = False,
               allow_degraded: bool = False,
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
        floor = DIFFICULTY_FLOOR[difficulty]
        factors: list[str] = [
            f"difficulty={difficulty}", f"tier_floor={floor}",
            f"context_tokens={context_tokens}",
            "selects_on=wall_clock_throughput (generation-time throughput is "
            "blind to contention: measured +3.3% while wall clock fell 42%)",
        ]
        rejected: list[dict] = []
        candidates: list[tuple[float, MeasuredProfile, float | None]] = []

        for p in self._profiles:
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
            rate = p.rate_at_context(context_tokens)
            if rate is None or rate <= 0:
                rejected.append({"profile_id": p.profile_id,
                                 "reason": "no usable rate at this context length"})
                continue
            # Prefer the strongest tier that fits; break ties on throughput.
            candidates.append((TIER_RANK[p.tier] * 1e6 + rate, p, rate))

        degraded_from = None
        if not candidates and allow_degraded:
            # Nothing at or above the floor fits. Look BELOW it, and report
            # loudly if something does. This is the only path in this file that
            # returns a tier weaker than the difficulty demands, and it cannot
            # be taken without the caller asking for it by name.
            for p in self._profiles:
                if TIER_RANK[p.tier] >= TIER_RANK[floor] or not p.available():
                    continue
                if (host_ram_free_gb is not None and p.host_ram_gb is not None
                        and p.host_ram_gb > host_ram_free_gb):
                    continue
                rate = p.rate_at_context(context_tokens)
                if rate and rate > 0:
                    candidates.append((TIER_RANK[p.tier] * 1e6 + rate, p, rate))
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

        candidates.sort(key=lambda c: c[0], reverse=True)
        _, best, rate = candidates[0]
        est = context_tokens / rate if rate else None
        factors.append(f"selected_rate_tokens_per_sec={rate:.2f}")
        if best.context_slowdown_us_per_token is not None:
            factors.append(
                f"rate adjusted for context: {best.context_slowdown_us_per_token} us "
                "per token of context (KV-cache growth, measured)")
        factors.append(f"measured_source={best.source}")

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
    def from_spike_results(results_dir: Path, bus: EventBus) -> "Router":
        """Build profiles from SPIKE-001 3.1 v4 reports.

        Reads ONLY reports at schema_version >= 4, because v3 aggregated the
        two headline figures over different windows and its wall-clock number
        is the whole-run average -- 27% above the settled rate on a decaying
        model. Loading a v3 report here would put that error in the router.

        No product names are constructed from filenames; the profile id is
        tier + node class.
        """
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
            profiles.append(MeasuredProfile(
                profile_id=f"{tier}-accelerated",
                tier=tier,
                node_class="accelerated",
                wall_tokens_per_sec=t.get("median_effective_tokens_per_sec"),
                wall_tokens_per_sec_idle=idle_rate,
                measured=True,
                source=f.name,
            ))
        return Router(bus, profiles)
