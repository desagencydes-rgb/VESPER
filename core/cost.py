"""Operating period and the cost choke point — INV-COST-1..7.

THE ABSOLUTE RULE, AND WHY IT IS ABSOLUTE. INV-COST-1: zero paid-provider
requests may leave the gateway during FREE_TIME, **under any inference input**.
Not "unless the model is confident the user is awake". Not "unless the task is
important". The rule is unconditional because the alternative is a system that
spends the owner's money on the strength of its own guess, and a guess is
exactly what an inference is.

THE ASYMMETRY THAT AR-005 GOT WRONG, and A-021's negative control exists to
prove was a real defect rather than a reading:

    "user is asleep" during ACTIVE_SESSION  -> MAY enter FREE_TIME
    "user is awake"  during FREE_TIME       -> MUST NOT leave it

Both are inferences of the same kind and the same confidence. They are treated
differently because their failure costs differ: wrongly entering FREE_TIME
delays work, and wrongly leaving it spends money that cannot be unspent. Only
an authenticated interaction — evidence, not inference — exits FREE_TIME.

FAIL-CLOSED EVERYWHERE. Cold start, post-crash, post-partition, and a suspect
clock all resolve to FREE_TIME. A credential with no declared cost_class is
refused rather than assumed free. With no policy file loaded at all, only the
`free` class is permitted — so the ABSENCE of configuration is already safe,
which is the property that makes this survivable when something goes wrong at
3 a.m.

metered_free_tier IS TREATED AS PAID unless a provable hard cap exists. A free
tier on an account with a payment method attached bills on overage; without a
provable cap the absolute rule leaks through the one door nobody watches.
"""

from __future__ import annotations

import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bus import EventBus
from .hlc import HybridLogicalClock

REPO = Path(__file__).resolve().parents[1]

PERIODS = ("FREE_TIME", "DO_NOT_DISTURB", "IDLE", "ACTIVE_SESSION")
COST_CLASSES = ("free", "metered_free_tier", "paid")

# INV-COST-6: with no policy artifact loaded, `free` only. The absence of
# configuration must be the safe state, not an unconfigured one.
DEFAULT_PERMITTED: dict[str, tuple[str, ...]] = {p: ("free",) for p in PERIODS}


class CostPolicyViolation(Exception):
    """A request was refused at the choke point. The gateway raises this."""


class CredentialRefused(Exception):
    """A credential was registered without a declared cost class (A-021.7)."""


@dataclass(frozen=True, slots=True)
class Credential:
    provider_id: str
    cost_class: str
    # INV-COST-5. Only a PROVABLE hard cap downgrades metered_free_tier to
    # free; "the dashboard says there is a limit" is not provable.
    provable_hard_cap: bool = False
    # THE PROOF TRAVELS WITH THE CLAIM. A boolean alone records that somebody
    # asserted a cap, never what makes it one, so an auditor reading
    # `provable_hard_cap = True` six months later has no way to check it and no
    # way to notice when it stopped being true. Mandatory whenever the flag is
    # set -- see `register_credential`.
    hard_cap_evidence: str = ""

    def effective_class(self) -> str:
        if self.cost_class == "metered_free_tier" and not self.provable_hard_cap:
            return "paid"
        if self.cost_class == "metered_free_tier":
            return "free"
        return self.cost_class


class CostPolicy:
    """The single choke point. No caller may bypass it (INV-COST-3, CI-020)."""

    def __init__(self, bus: EventBus, clock: HybridLogicalClock, *,
                 policy_path: Path | None = None) -> None:
        self._bus = bus
        self._clock = clock
        self._lock = threading.RLock()
        # A-021.5: cold start is FREE_TIME. Always. There is no persisted
        # period to restore, on purpose -- restoring ACTIVE_SESSION across a
        # crash would let a crash authorise spending.
        self._period = "FREE_TIME"
        self._period_cause = "cold_start"
        self._clock_suspect = False
        self._credentials: dict[str, Credential] = {}
        self._declared: dict = {}
        self._permitted, self._policy_loaded = self._load(policy_path)

    def _load(self, path: Path | None) -> tuple[dict[str, tuple[str, ...]], bool]:
        p = path or (REPO / "contracts" / "policy" / "cost_policy.toml")
        if not p.exists():
            return dict(DEFAULT_PERMITTED), False
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        self._declared = raw.get("credentials") or {}
        table = raw.get("permitted_cost_classes")
        if not table:
            return dict(DEFAULT_PERMITTED), False
        return ({k: tuple(v) for k, v in table.items()}, True)

    # ---------------------------------------------------------------- period

    @property
    def period(self) -> str:
        with self._lock:
            # A-021.6: a suspect clock resolves to FREE_TIME regardless of what
            # the stored period says. Period boundaries are wall-clock windows,
            # so a clock that cannot be trusted means periods cannot be either.
            return "FREE_TIME" if self._clock_suspect else self._period

    def period_and_cause(self) -> tuple[str, str]:
        """A-021.4 / RB-019: both retrievable at any time."""
        with self._lock:
            if self._clock_suspect:
                return "FREE_TIME", "clock_suspect"
            return self._period, self._period_cause

    def set_clock_suspect(self, suspect: bool) -> None:
        with self._lock:
            self._clock_suspect = suspect
        if suspect:
            self._bus.publish("cost.period_forced", subject="operating_period",
                              payload={"period": "FREE_TIME",
                                       "cause": "clock_suspect",
                                       "note": ("period windows are wall-clock; an "
                                                "untrusted clock cannot authorise "
                                                "spending")},
                              component="cost")

    def observe_inference(self, claim: str, confidence: float) -> bool:
        """Feed an INFERENCE about the owner's state. Returns True if it moved.

        This is the method A-021.1 attacks: a high-confidence "user is awake"
        during FREE_TIME must move nothing and spend nothing, however confident
        the model is. The permitted direction is the cheap-failure one.
        """
        with self._lock:
            cur = self._period
            moved = False
            if claim == "user_is_asleep" and cur == "ACTIVE_SESSION":
                # A-021.2: permitted. Failure mode is a delay.
                self._period, self._period_cause = "FREE_TIME", "inference:user_is_asleep"
                moved = True
            elif claim == "user_is_awake" and cur == "FREE_TIME":
                # A-021.1: REFUSED, at any confidence. Failure mode is money.
                pass
        if claim == "user_is_awake" and cur == "FREE_TIME":
            self._bus.publish(
                "cost.inference_refused_as_period_change", subject="operating_period",
                payload={"claim": claim, "confidence": confidence,
                         "period": "FREE_TIME", "transitioned": False,
                         "reason": ("INV-COST-1 is unconditional. Leaving FREE_TIME "
                                    "on an inference would let a guess authorise "
                                    "spending; only an authenticated interaction "
                                    "exits. Evidence recorded.")},
                component="cost")
        elif moved:
            self._emit_period_change("inference:user_is_asleep")
        return moved

    def authenticated_interaction(self) -> None:
        """A-021.3: real evidence of presence. Exits FREE_TIME immediately."""
        with self._lock:
            if self._period == "ACTIVE_SESSION":
                return
            self._period = "ACTIVE_SESSION"
            self._period_cause = "authenticated_interaction"
        self._emit_period_change("authenticated_interaction")

    def set_period(self, period: str, cause: str) -> None:
        if period not in PERIODS:
            raise ValueError(f"unknown period {period!r}")
        with self._lock:
            self._period, self._period_cause = period, cause
        self._emit_period_change(cause)

    def on_crash_or_partition(self, reason: str) -> None:
        """A-021.5. Recovery lands in FREE_TIME, never in a spending period."""
        with self._lock:
            self._period, self._period_cause = "FREE_TIME", f"recovery:{reason}"
        self._emit_period_change(f"recovery:{reason}")

    def _emit_period_change(self, cause: str) -> None:
        p, c = self.period_and_cause()
        self._bus.publish("cost.period_changed", subject="operating_period",
                          payload={"period": p, "cause": c}, component="cost")

    # ----------------------------------------------------------- credentials

    def register_credential(self, provider_id: str, cost_class: str | None, *,
                            provable_hard_cap: bool = False,
                            hard_cap_evidence: str = "") -> Credential:
        """A-021.7: a credential with no cost_class is REFUSED, not defaulted.

        Defaulting it to `free` would be the same bug as defaulting it to
        `paid`, only quieter: an unclassified credential is one nobody decided
        about, and the choke point cannot enforce a decision that was never made.
        """
        if cost_class is None:
            self._bus.publish("cost.credential_refused", subject=provider_id,
                              payload={"provider_id": provider_id,
                                       "reason": "no cost_class declared"},
                              component="cost")
            raise CredentialRefused(
                f"credential {provider_id!r} declares no cost_class. Refused -- "
                "an unclassified credential cannot be governed, and defaulting "
                "it would be a decision nobody made.")
        if cost_class not in COST_CLASSES:
            raise CredentialRefused(
                f"cost_class {cost_class!r} not in {COST_CLASSES}")
        if provable_hard_cap and not (hard_cap_evidence or "").strip():
            # INV-COST-5 is a rule about EVIDENCE, not about a flag.
            # `override_requires = "provable_hard_cap"` in cost_policy.toml
            # asks for a provable cap; a bare `True` proves nothing and is
            # precisely the "the dashboard says there is a limit" the
            # invariant was written about. Refused rather than downgraded: an
            # unproven claim is not a weaker claim, it is the claim at issue.
            self._bus.publish(
                "cost.credential_refused", subject=provider_id,
                payload={"provider_id": provider_id,
                         "reason": "provable_hard_cap asserted without evidence"},
                component="cost")
            raise CredentialRefused(
                f"credential {provider_id!r} sets provable_hard_cap without "
                "hard_cap_evidence. INV-COST-5 requires a PROVABLE cap, and a "
                "boolean proves nothing -- name the mechanism that makes "
                "spending impossible, not the intention not to spend.")
        cred = Credential(provider_id, cost_class, provable_hard_cap,
                          (hard_cap_evidence or "").strip())
        with self._lock:
            self._credentials[provider_id] = cred
        return cred

    def load_declared_credentials(self) -> list:
        """Register every credential declared in the policy file.

        THE SWITCH LIVES IN THE POLICY, NOT AT A CALL SITE. A cost class set
        where a provider happens to be constructed is a decision buried in code
        that the owner cannot review and CODEOWNERS does not govern --
        `contracts/policy/` is owner-only precisely so that this kind of choice
        is visible in one reviewable place. Flipping `provable_hard_cap` there
        changes what leaves the machine, with no code change and no redeploy.

        Refusals PROPAGATE. A declared credential that cannot be registered is
        a policy file that says something the rule will not accept, and
        starting anyway with that provider silently absent would be a fabric
        quietly smaller than its own configuration says.
        """
        out = []
        for provider_id, row in (self._declared or {}).items():
            out.append(self.register_credential(
                provider_id, row.get("cost_class"),
                provable_hard_cap=bool(row.get("provable_hard_cap", False)),
                hard_cap_evidence=row.get("hard_cap_evidence", "")))
        return out

    def declared_credentials(self) -> dict:
        """What the policy file declares, before any of it is registered."""
        return dict(self._declared or {})

    def credential(self, provider_id: str) -> Credential | None:
        return self._credentials.get(provider_id)

    # ----------------------------------------------------------- the decision

    def permitted_classes(self) -> tuple[str, ...]:
        if not self._policy_loaded:
            # A-021.9: no policy loaded => free only.
            return ("free",)
        return self._permitted.get(self.period, ("free",))

    def check(self, provider_id: str, *, task_id: str | None = None) -> None:
        """THE choke point. Raises CostPolicyViolation, or returns None.

        Every model call passes through here. There is deliberately no
        `force=True`, no `bypass`, and no per-caller exemption: INV-COST-3 says
        no caller may bypass it, and a parameter that allows bypassing is the
        bypass.
        """
        cred = self._credentials.get(provider_id)
        if cred is None:
            self._refuse(provider_id, "unregistered credential", task_id)
        eff = cred.effective_class()
        allowed = self.permitted_classes()
        if eff not in allowed:
            detail = f"{eff!r} not permitted in {self.period}"
            if cred.cost_class == "metered_free_tier" and not cred.provable_hard_cap:
                detail += (" -- metered_free_tier without a provable hard cap is "
                           "treated as paid (INV-COST-5): a free tier on an account "
                           "with a payment method bills on overage")
            self._refuse(provider_id, detail, task_id)

    def _refuse(self, provider_id: str, reason: str, task_id: str | None) -> None:
        self._bus.publish("cost.request_refused", subject=provider_id,
                          payload={"provider_id": provider_id, "reason": reason,
                                   "period": self.period, "task_id": task_id,
                                   "permitted_classes": list(self.permitted_classes())},
                          component="cost")
        raise CostPolicyViolation(
            f"request to {provider_id!r} refused at the cost choke point: {reason}")

    def exhausted(self, task_id: str) -> None:
        """Every permitted provider is exhausted (A-004.3).

        checkpoint_and_queue. Does NOT wake the user for ordinary work (SR-042)
        and does NOT escalate to paid (RB-017). SR-003's "retry without
        stopping" is satisfied by continuing within the free subset and queueing
        when it is empty -- both requirements stand unmodified.
        """
        self._bus.publish("autonomy.blocked_on_cost_policy", subject=task_id,
                          payload={"task_id": task_id, "period": self.period,
                                   "action": "checkpoint_and_queue",
                                   "woke_user": False, "escalated_to_paid": False},
                          component="cost")
