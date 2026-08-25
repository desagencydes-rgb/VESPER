"""The one path from a task to an answer: route, call, degrade, report.

WHY THIS FILE EXISTS. Until 2026-08-24 nothing in `core/` consumed the gateway
and nothing consumed the router. `Router.select` produced a decision, the
gateway called a provider, and the two were joined only inside acceptance
tests -- which is how a router that sent every difficulty to the strong tier
and a gateway that ignored routing entirely both stayed green for weeks. A seam
that exists only in a test is a seam the product does not have.

TWO KINDS OF FALLING BACK, AND THEY ARE NOT THE SAME THING.

  SR-003 -- "automatic API switching when quota/error occurs, with retry
  without stopping". That is PROVIDER-level, it happens WITHIN one capability
  profile, and `ModelGateway` already does it: an ordered provider list, each
  re-checked against the cost policy immediately before invocation. Two API
  keys serving the same tier are interchangeable, so swapping them needs no
  report and produces no loss.

  SR-005 -- "OFFLINE/NO-API backup using the best practical local model". That
  is TIER-level, and it is not a swap. A remote flash model and a local 1.7B
  are not interchangeable; substituting one for the other changes what the
  answer is worth. RB-022 calls that a capability degradation and requires it
  to be REPORTED. Doing it inside the gateway, under one profile id, would make
  it silent -- and a degraded system that cannot be distinguished from a
  healthy one is the failure mode INV-SCENE-2 exists to prevent.

So the gateway switches providers and this switches TIERS, loudly.

DEGRADATION MUST BE ASKED FOR. `allow_degraded` defaults to False and the
default path raises. A task that cannot be answered at the capability it needs
should queue for when it can be, because an answer from a model too weak for
the question is worse than a late one -- the caller cannot tell it apart from a
good one, which is exactly what makes it expensive.

NOTHING HERE TOUCHES COST. There is no branch that reaches for a paid provider
when a free one is spent: RB-017 forbids it, `ModelGateway` enforces it at the
choke point, and a second opinion about it here would be a second place to get
it wrong.
"""

from __future__ import annotations

from typing import Any

from .bus import EventBus
from .gateway import AllProvidersExhausted, NoProviderForProfile
from .router import NoRouteAvailable


class CompletionUnavailable(Exception):
    """No capability could answer. The task checkpoints and queues."""


class CompletionService:
    """Routes a request, calls it, and degrades only when asked and only aloud."""

    def __init__(self, bus: EventBus, router: Any, gateway: Any) -> None:
        self._bus = bus
        self._router = router
        self._gateway = gateway

    def complete(self, prompt: str, *, difficulty: str,
                 task_id: str | None = None,
                 options: dict | None = None,
                 context_tokens: int = 2048,
                 host_ram_free_gb: float | None = None,
                 node_busy: bool = False,
                 allow_degraded: bool = False,
                 max_attempts: int = 4) -> dict:
        """Answer at the capability the difficulty demands, or say why not."""
        tried: set = set()
        first = None
        last: Exception | None = None

        for _ in range(max_attempts):
            try:
                d = self._router.select(
                    difficulty, context_tokens=context_tokens,
                    host_ram_free_gb=host_ram_free_gb, node_busy=node_busy,
                    # The FIRST attempt is never degraded: the floor is what
                    # the difficulty requires. Degradation is only ever a
                    # response to the required capability being unavailable,
                    # never a first preference.
                    allow_degraded=allow_degraded and bool(tried),
                    exclude=tried, task_id=task_id)
            except NoRouteAvailable as e:
                last = e
                break
            if first is None:
                first = d

            try:
                out = self._gateway.complete(
                    prompt, task_id=task_id, options=options,
                    profile_id=d.profile_id,
                    # THE DIFFICULTY GOES TO THE GATEWAY TOO, and not passing it
                    # would repeat this file's own founding defect one level
                    # down. `difficulty` already chose the TIER here; it also
                    # decides how hard that tier is told to think, and
                    # `core/effort.py` is the floor for the second question. A
                    # difficulty that stops at the router leaves the effort
                    # floor reachable only by a caller who states it twice --
                    # which is a seam that exists in a test and not in the
                    # product.
                    difficulty=difficulty)
            except (AllProvidersExhausted, NoProviderForProfile) as e:
                last = e
                tried.add(d.profile_id)
                self._bus.publish(
                    "completion.profile_exhausted",
                    subject=task_id or "unassigned",
                    payload={"task_id": task_id, "profile_id": d.profile_id,
                             "tier": d.tier, "difficulty": difficulty,
                             "reason": str(e)[:400],
                             "will_degrade": bool(allow_degraded)},
                    component="completion")
                if not allow_degraded:
                    # FAIL-CLOSED. The task queues for a period when the
                    # capability it needs exists, rather than being answered
                    # by one that does not.
                    raise CompletionUnavailable(
                        f"no provider could serve {d.profile_id!r} for "
                        f"difficulty={difficulty!r}, and degradation was not "
                        f"requested. The task checkpoints and queues. "
                        f"Underlying: {e}") from e
                continue

            if d.profile_id != first.profile_id:
                # RB-022: reported, never silent. Named in full -- what was
                # asked for, what was given, and what was spent trying --
                # because "I am running on less than usual, and here is what I
                # cannot do" is a required behaviour, not a courtesy.
                self._bus.publish(
                    "completion.degraded", subject=task_id or "unassigned",
                    payload={"task_id": task_id, "difficulty": difficulty,
                             "required_profile": first.profile_id,
                             "required_tier": first.tier,
                             "granted_profile": d.profile_id,
                             "granted_tier": d.tier,
                             "exhausted": sorted(tried),
                             "note": ("capability degradation: the answer came "
                                      "from a weaker tier than the difficulty "
                                      "asked for. It is not the answer that "
                                      "was requested and must not be presented "
                                      "as one.")},
                    component="completion")
            return {**out, "route": d.to_dict(),
                    "degraded_from": (first.profile_id
                                      if d.profile_id != first.profile_id
                                      else None)}

        self._bus.publish(
            "completion.unavailable", subject=task_id or "unassigned",
            payload={"task_id": task_id, "difficulty": difficulty,
                     "exhausted": sorted(tried), "reason": str(last)[:400]},
            component="completion")
        raise CompletionUnavailable(
            f"no capability could answer difficulty={difficulty!r}. Exhausted: "
            f"{sorted(tried)}. The task checkpoints and queues rather than "
            f"being answered badly. Underlying: {last}")
