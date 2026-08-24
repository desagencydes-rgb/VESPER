"""Model gateway — the single boundary every model call crosses.

WHY A GATEWAY AND NOT A LIBRARY CALL. INV-COST-3 requires the cost rule to be
enforced at ONE choke point that no caller may bypass. That is only true if
there is exactly one way to reach a provider, so this class owns the provider
handles and nothing else in the runtime holds one. A caller with a direct
provider reference is a caller outside the policy.

A-004.3 IS AN ASSERTION ON THIS BOUNDARY, NOT ON LOGS. "Revoke all free
providers mid-task during FREE_TIME => zero paid attempts asserted at the
gateway boundary." So the gateway counts attempts per cost class itself, and
the counter increments where the provider is actually invoked. Counting in the
caller would measure intent; counting here measures what left the machine.

FALLBACK IS ORDERED AND VISIBLE. SR-004 asks for error classification and retry
timing "just like Claude Code CLI" -- meaning a human can see what failed and
what happens next, rather than a spinner. Every attempt emits its classification
and the delay before the next one.

EXHAUSTION IS NOT ESCALATION. When every permitted provider is spent, the
gateway checkpoints and queues. It does not reach for a paid provider and does
not wake the owner for ordinary work. SR-003's "retry without stopping" is
satisfied within the permitted subset -- both requirements stand unmodified,
which is the point AR-005 missed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .bus import EventBus
from .cost import CostPolicy, CostPolicyViolation

# SR-004: an error a human can act on. Classification decides retry timing.
TRANSIENT = ("rate_limited", "timeout", "server_error", "connection_error")
TERMINAL = ("auth_failed", "quota_exhausted", "revoked", "bad_request")


class AllProvidersExhausted(Exception):
    """Every permitted provider failed or was refused. Task checkpoints."""


class NoProviderForProfile(Exception):
    """No registered provider serves the routed profile. Fail-closed.

    Deliberately NOT a fallback to the other providers. Falling through to
    whatever else is registered is the same shape as paid escalation: the
    caller asked for a capability, that capability is unavailable, and quietly
    substituting a different one returns an answer to a question nobody asked.
    A-022 exists to decide WHICH model answers; honouring the decision only
    when it happens to be satisfiable would make it advisory.
    """


@dataclass(slots=True)
class Provider:
    provider_id: str
    profile_id: str
    call: Callable[[str, dict], dict]
    available: bool = True


@dataclass(slots=True)
class Attempt:
    provider_id: str
    cost_class: str
    outcome: str
    classification: str | None
    retry_after_ms: int | None
    elapsed_ms: float
    # What the SERVER said, kept separately from what we DID. When a provider
    # says "retry in 33s" and we move to another provider instead, both facts
    # matter: the wait we skipped is why the next provider was tried, and it is
    # also how long this one stays unusable.
    server_retry_after_ms: int | None = None


class ModelGateway:
    """Every model call in VESPER goes through `complete`."""

    def __init__(self, bus: EventBus, cost: CostPolicy, *,
                 sleep: Callable[[float], None] | None = None) -> None:
        self._bus = bus
        self._cost = cost
        self._providers: list[Provider] = []
        self._lock = threading.RLock()
        # THE BOUNDARY COUNTERS. A-004.3 asserts on these.
        self.attempts_by_class: dict[str, int] = {"free": 0, "paid": 0,
                                                  "metered_free_tier": 0}
        self.history: list[Attempt] = []
        self._sleep = sleep or time.sleep

    def register(self, provider: Provider) -> None:
        with self._lock:
            self._providers.append(provider)

    def set_available(self, provider_id: str, available: bool) -> None:
        """Revoke or restore a provider mid-task (A-004.3's injection)."""
        with self._lock:
            for p in self._providers:
                if p.provider_id == provider_id:
                    p.available = available
        self._bus.publish("gateway.provider_availability_changed",
                          subject=provider_id,
                          payload={"provider_id": provider_id,
                                   "available": available},
                          component="gateway")

    # A server-stated wait longer than this is not something to sit through
    # while other providers exist. Five seconds is the point past which trying
    # somebody else is plainly faster than waiting.
    LONG_WAIT_MS = 5_000

    def _retry_delay_ms(self, classification: str, attempt_index: int,
                        server_hint_ms: int | None = None) -> int | None:
        if classification in TERMINAL:
            return None  # no point retrying; move to the next provider
        if server_hint_ms:   # truthy: absent and zero are the same thing
            # THE SERVER KNOWS AND WE DO NOT. A computed backoff is a guess
            # about a quota whose shape is invisible from here: measured
            # 2026-08-24, a free tier answered 429 with retryDelay 33s against
            # a limit of 20 requests PER DAY. A 500 ms exponential retry
            # against that is not patience, it is a second identical failure,
            # and then a third. A NON-POSITIVE hint is discarded upstream in
            # routing/http_completion.py for the same reason and is guarded
            # again here: a server answering "retry immediately" to a 429 is
            # not an instruction worth obeying.
            if server_hint_ms > self.LONG_WAIT_MS:
                # Move to the next provider NOW rather than sleeping. Returning
                # None ends this provider's retry loop without claiming the
                # failure was terminal -- the classification still says
                # otherwise, and the hint is recorded so the caller can see how
                # long this provider stays unusable.
                return None
            return int(server_hint_ms)
        return min(30_000, int(500 * (2 ** attempt_index)))

    def complete(self, prompt: str, *, task_id: str | None = None,
                 options: dict | None = None,
                 max_attempts_per_provider: int = 2,
                 profile_id: str | None = None) -> dict:
        """Call the first permitted, available provider that succeeds.

        Every provider passes the cost check IMMEDIATELY BEFORE invocation, not
        once at entry. A period can change mid-call chain, and a check done at
        entry would authorise a request made after the rule changed.

        `profile_id` IS THE SEAM TO THE ROUTER, AND IT DID NOT EXIST UNTIL
        2026-08-24. `Provider` has carried a `profile_id` field since F1, and
        this method never read it -- it was echoed into the result dict and
        nowhere else. So `Router.select` produced a decision, and the gateway
        then called providers in REGISTRATION ORDER. Registration order was the
        real routing rule, and A-022 could not see it: the router is asserted
        against `RouteDecision`, the gateway against `attempts_by_class`, and
        no test held the two ends of the same call.

        That is what made "wire a real provider" dangerous rather than merely
        premature. The danger was never that the router had nothing to offer --
        it loads six measured profiles. It was that the decision had no way to
        reach the call, so the first provider registered would have served
        every request and looked correct while doing it.

        Passing `profile_id` restricts the attempt set to providers serving
        that profile, and refuses rather than substituting when none does.
        Omitting it keeps the pre-existing behaviour and EMITS `gateway.unrouted`
        -- a call that bypassed routing is a fact about the system, and the
        F1 fallback chain (three providers at three different profiles) is a
        legitimate caller of the unrouted form. Recording it is what makes the
        eventual move to mandatory routing a measurement rather than a guess.
        """
        options = options or {}
        with self._lock:
            providers = list(self._providers)
        if profile_id is None:
            self._bus.publish(
                "gateway.unrouted", subject=task_id or "unassigned",
                payload={"task_id": task_id,
                         "registered_providers": [p.provider_id for p in providers],
                         "note": ("no routed profile supplied: provider order "
                                  "decides, not A-022. Recorded rather than "
                                  "assumed benign.")},
                component="gateway")
        else:
            matching = [p for p in providers if p.profile_id == profile_id]
            if not matching:
                self._bus.publish(
                    "gateway.no_provider_for_profile",
                    subject=task_id or "unassigned",
                    payload={"task_id": task_id, "profile_id": profile_id,
                             "registered_profiles": sorted(
                                 {p.profile_id for p in providers}),
                             "note": ("fail-closed: the routed capability has "
                                      "no provider. Substituting another "
                                      "profile would answer a different "
                                      "question.")},
                    component="gateway")
                raise NoProviderForProfile(
                    f"no registered provider serves profile {profile_id!r}. "
                    f"Registered profiles: "
                    f"{sorted({p.profile_id for p in providers})}. The task "
                    "defers rather than being answered by a capability it did "
                    "not ask for.")
            providers = matching
        last_error: Exception | None = None

        for p in providers:
            if not p.available:
                self._record(p, "skipped", "provider_unavailable", None, 0.0)
                continue

            # The choke point. Re-checked per provider, deliberately.
            try:
                self._cost.check(p.provider_id, task_id=task_id)
            except CostPolicyViolation as e:
                cred = self._cost.credential(p.provider_id)
                self._record(p, "refused_by_cost_policy", "cost_policy",
                             None, 0.0,
                             cost_class=cred.effective_class() if cred else "unknown")
                last_error = e
                continue

            cred = self._cost.credential(p.provider_id)
            eff = cred.effective_class() if cred else "unknown"

            for i in range(max_attempts_per_provider):
                t0 = time.perf_counter()
                # THE BOUNDARY. Counted here because this is the line that
                # actually reaches a provider; anywhere earlier counts intent.
                with self._lock:
                    self.attempts_by_class[eff] = self.attempts_by_class.get(eff, 0) + 1
                try:
                    result = p.call(prompt, options)
                except Exception as e:  # noqa: BLE001
                    ms = (time.perf_counter() - t0) * 1000.0
                    cls = getattr(e, "classification", "server_error")
                    hint = getattr(e, "retry_after_ms", None)
                    delay = self._retry_delay_ms(cls, i, hint)
                    self._record(p, "error", cls, delay, ms, cost_class=eff,
                                 server_retry_after_ms=hint)
                    last_error = e
                    if delay is None:
                        break  # terminal for this provider
                    self._sleep(delay / 1000.0)
                    continue
                ms = (time.perf_counter() - t0) * 1000.0
                self._record(p, "ok", None, None, ms, cost_class=eff)
                return {"provider_id": p.provider_id, "profile_id": p.profile_id,
                        "result": result}

        # Nothing permitted succeeded. Checkpoint and queue -- do NOT escalate.
        if task_id:
            self._cost.exhausted(task_id)
        raise AllProvidersExhausted(
            "every permitted provider was unavailable, refused or failed. "
            "Task checkpointed and queued for the next permitted period; no "
            "paid escalation (RB-017) and the owner was not woken (SR-042). "
            f"Last error: {last_error}")

    def _record(self, p: Provider, outcome: str, classification: str | None,
                retry_after_ms: int | None, elapsed_ms: float,
                cost_class: str = "unknown",
                server_retry_after_ms: int | None = None) -> None:
        a = Attempt(p.provider_id, cost_class, outcome, classification,
                    retry_after_ms, elapsed_ms, server_retry_after_ms)
        with self._lock:
            self.history.append(a)
        self._bus.publish("gateway.attempt", subject=p.provider_id,
                          payload={"provider_id": p.provider_id,
                                   "cost_class": cost_class, "outcome": outcome,
                                   "classification": classification,
                                   "retry_after_ms": retry_after_ms,
                                   "server_retry_after_ms": server_retry_after_ms,
                                   "elapsed_ms": round(elapsed_ms, 2)},
                          component="gateway")

    def paid_attempts(self) -> int:
        """A-004.3 asserts this is ZERO after the FREE_TIME revocation run."""
        with self._lock:
            return self.attempts_by_class.get("paid", 0)
