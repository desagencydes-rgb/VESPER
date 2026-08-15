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

    def _retry_delay_ms(self, classification: str, attempt_index: int) -> int | None:
        if classification in TERMINAL:
            return None  # no point retrying; move to the next provider
        return min(30_000, int(500 * (2 ** attempt_index)))

    def complete(self, prompt: str, *, task_id: str | None = None,
                 options: dict | None = None,
                 max_attempts_per_provider: int = 2) -> dict:
        """Call the first permitted, available provider that succeeds.

        Every provider passes the cost check IMMEDIATELY BEFORE invocation, not
        once at entry. A period can change mid-call chain, and a check done at
        entry would authorise a request made after the rule changed.
        """
        options = options or {}
        with self._lock:
            providers = list(self._providers)
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
                    delay = self._retry_delay_ms(cls, i)
                    self._record(p, "error", cls, delay, ms, cost_class=eff)
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
                cost_class: str = "unknown") -> None:
        a = Attempt(p.provider_id, cost_class, outcome, classification,
                    retry_after_ms, elapsed_ms)
        with self._lock:
            self.history.append(a)
        self._bus.publish("gateway.attempt", subject=p.provider_id,
                          payload={"provider_id": p.provider_id,
                                   "cost_class": cost_class, "outcome": outcome,
                                   "classification": classification,
                                   "retry_after_ms": retry_after_ms,
                                   "elapsed_ms": round(elapsed_ms, 2)},
                          component="gateway")

    def paid_attempts(self) -> int:
        """A-004.3 asserts this is ZERO after the FREE_TIME revocation run."""
        with self._lock:
            return self.attempts_by_class.get("paid", 0)
