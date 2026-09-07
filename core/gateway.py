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

WHAT THE FIRST LIVE CALLS CHANGED HERE, 2026-08-25. Six findings in
`docs/planning/MULTI_ROUTE.md` SS13/SS14 were taken against real endpoints, and
four of them contradicted code that already looked correct in this file:

  * THE RETRY BUDGET WAS PER PROVIDER AND UNBOUNDED ACROSS THE CHAIN. Two
    attempts each on a six-rung ladder is twelve calls for one request, and
    nothing in this module knew the number. MULTI_ROUTE SS2 "Where the 10
    retries go" says ten PER REQUEST, across the whole ladder. It is now a
    budget the chain spends, not a per-provider allowance that multiplies.

  * REGISTRATION ORDER WAS THE ROUTING RULE FOR *WHICH FREE PROVIDER*, exactly
    as it was for `profile_id` before 2026-08-24. `profile_id` fixed WHICH
    CAPABILITY answers; it never decided which of several providers serving
    that capability had any quota left. `QuotaLedger.rank` decides that now,
    per request, because which provider is biggest changes through the day.

  * A `429` DOES NOT ALWAYS MEAN "EXHAUSTED". Carrying `limit: 0` it means the
    tier never had an allowance, so the refusal is permanent and retrying it
    spends the budget every day forever. `rate_limited` is in TRANSIENT and
    always will be -- the fix is not to reclassify the status but to read the
    quota detail underneath it. See `_book_refusal`.

  * A `200` CAN CARRY NO ANSWER. `core.effort.guard_response` refuses one at
    this boundary rather than in an adapter, because an adapter guard is
    per-provider and this is the one place every call passes through.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import decision_path
from .redact import redact
from .bus import EventBus
from .cost import CostPolicy, CostPolicyViolation
from .effort import Effort, for_difficulty, guard_response
from .latency import Observation
from .quota import QuotaLedger, UNAVAILABLE_ON_TIER


def _limit_parse_suspect(message: str) -> bool:
    """Ask the adapter whether a refusal named an unreadable limit.

    IMPORTED LAZILY, AND THAT IS STRUCTURAL. `core/` must not depend on
    `routing/` at module load -- the adapter is a plug-in detail and the
    gateway is the boundary it plugs into. A missing adapter degrades to
    "no suspicion" rather than breaking the gateway, because a drift DETECTOR
    that can take the whole call path down is worse than the drift.
    """
    try:
        from routing.http_completion import quota_limit_parse_suspect
    except Exception:  # noqa: BLE001
        return False
    return quota_limit_parse_suspect(message)

# SR-004: an error a human can act on. Classification decides retry timing.
TRANSIENT = ("rate_limited", "timeout", "server_error", "connection_error")
# `budget_too_large` IS TERMINAL FOR THIS REQUEST AND NOT FOR THE RUNG, which
# is a distinction this tuple cannot express on its own -- so it lives here and
# `_book_refusal` is deliberately not given it. A rung that cannot accept a
# 9216-token reservation is perfectly able to accept a 640-token one, and the
# next request will find that out. Retrying THIS one is what must stop:
# measured 2026-08-26, a 413 classified `server_error` was retried against a
# ceiling it could never get under, twice per turn.
TERMINAL = ("auth_failed", "quota_exhausted", "revoked", "bad_request",
            "budget_too_large", "model_gone")

# `model_gone` IS TERMINAL FOR THIS ROW AND SAYS NOTHING ABOUT THE PROVIDER.
# The owner's rule: "if the provider dropped that model, vesper should mark that
# model as unavailable and use another one in the same provider". A rung IS a
# (provider, model) pair, so retiring the rung is exactly that -- the account,
# the credential and the egress class are all still good, and the ladder's next
# row may well be the same provider with a different model.
#
# IT MUST BE HERE RATHER THAN NOWHERE. A classification in neither tuple falls
# through to a computed backoff and is RETRIED -- which for a model the provider
# has removed is a request that cannot succeed, repeated on a timer.

# Classifications that mean "the provider refused on quota", and therefore that
# the refusal carries a QUOTA SHAPE worth booking. `rate_limited` is TRANSIENT
# and stays TRANSIENT: the distinction between a window that refills and a tier
# that excludes is NOT in the status code, it is in the `limit` field, and the
# whole finding of 2026-08-25 is that the two are indistinguishable from the
# status alone.
QUOTA_CLASSIFICATIONS = ("rate_limited", "quota_exhausted")


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


# What a provider may be shown, and what a request may be shown TO.
#
# TWO VOCABULARIES MET HERE AND HAD NEVER BEEN INTRODUCED. `core/privacy.py`
# has classified content as {public, personal, private} since A-010;
# `contracts/policy/provider_supply.toml` classifies suppliers as
# {E1_PRIVATE, E2_PUBLIC}. Both existed, both were correct, and NOTHING JOINED
# THEM -- the egress class was applied once at registration and the choke point
# had never heard of it. A caller registering a public ladder could send the
# owner's private content through it and no rule anywhere would object.
#
# INV-COST-3's argument applies unchanged: a rule enforced anywhere except the
# one place every call passes through is a rule with a bypass.
E1_PRIVATE, E2_PUBLIC = "E1_PRIVATE", "E2_PUBLIC"

# Which supplier classes may carry which content class.
#
# UNLABELLED CONTENT IS PRIVATE. Not "unclassified", not "assume public" --
# private. core/privacy.py states the asymmetry this rests on: withholding
# something the owner wanted costs a re-ask, and sending private content to a
# provider that trains on it cannot be undone. So the ambiguous case resolves
# to the cheap failure, exactly as the display router does.
MAY_CARRY = {
    "private":  frozenset({E1_PRIVATE}),
    "personal": frozenset({E1_PRIVATE}),
    "public":   frozenset({E1_PRIVATE, E2_PUBLIC}),
}


class EgressRefused(Exception):
    """A provider was refused because of what the content is, not what it costs."""


@dataclass(slots=True)
class Provider:
    provider_id: str
    profile_id: str
    call: Callable[[str, dict], dict]
    available: bool = True
    # THE LEDGER'S SECOND KEY. Quota is metered per (provider, model), not per
    # provider: one account can hold a spent model and an untouched one, and a
    # ledger keyed on the account alone would retire both when either is
    # refused. Empty string is a real key meaning "the endpoint's only model" --
    # it is not a missing value, and it must not be defaulted to `provider_id`,
    # which would make two models on one account share a line again.
    model: str = ""
    # WHAT THIS PROVIDER MAY BE SHOWN. Defaults to the STRICTEST class, not the
    # most permissive: a provider registered without one is a provider nobody
    # has vetted, and treating it as public-capable would let an unreviewed
    # endpoint receive the owner's private content by omission rather than by
    # decision.
    egress_class: str = E1_PRIVATE

    def quota_key(self) -> tuple[str, str]:
        return (self.provider_id, self.model)


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


def _completion_tokens(result: dict) -> int | None:
    """What the provider says it generated, across every shape we speak.

    ORDER IS DELIBERATE: the provider's own accounting first, the local
    runner's field last. A ZERO IS NOT AN ANSWER -- one provider reports zeros
    on calls that worked, so a falsy value falls through to the next key and
    ultimately to None, which the ledger books as UNMEASURED rather than free.
    """
    # `neurons` LEADS THE LIST because it is what the provider actually bills.
    # An image call reports neurons: 172.8 and completion_tokens: 0 -- reading
    # tokens first books a real 172.8-neuron generation as an unmeasured 1.0,
    # and the ledger then thinks the day holds thousands of images instead of
    # 58. Found by the acceptance run, which asserted the pool and got 1.0.
    usage = result.get("usage") or {}
    for key in ("neurons",                  # cf image -- the BILLED unit
                "completion_tokens",        # openai-shaped
                "output_tokens",            # cf responses
                "candidatesTokenCount"):    # google generateContent
        v = usage.get(key)
        if v:
            return int(v)
    v = result.get("tokens_predicted")      # local runner
    return int(v) if v else None


class ModelGateway:
    """Every model call in VESPER goes through `complete`."""

    def __init__(self, bus: EventBus, cost: CostPolicy, *,
                 sleep: Callable[[float], None] | None = None,
                 quota: QuotaLedger | None = None) -> None:
        self._bus = bus
        self._cost = cost
        self._providers: list[Provider] = []
        self._lock = threading.RLock()
        # THE BOUNDARY COUNTERS. A-004.3 asserts on these.
        self.attempts_by_class: dict[str, int] = {"free": 0, "paid": 0,
                                                  "metered_free_tier": 0}
        self.history: list[Attempt] = []
        # LIVE, PER-PROCESS, NEVER PERSISTED. See `core/latency.py` for why a
        # latency estimate read off disk at startup is a declared number in a
        # measured number's clothes.
        self._observed: dict[str, Observation] = {}
        self._sleep = sleep or time.sleep
        # THERE IS ALWAYS A LEDGER, and `quota=None` does not mean "no ordering".
        # A gateway without one falls back to registration order, which is the
        # exact defect `core/quota.py` was written to remove -- so the fallback
        # is an in-memory ledger for this process, never an absent one. Passing
        # a path-backed ledger makes the knowledge survive a restart; passing
        # nothing makes it survive the request, which is still better than
        # deciding routing by the order somebody happened to call `register`.
        self.quota = quota if quota is not None else QuotaLedger()

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

    # THE CHAIN-WIDE DEFAULT, from MULTI_ROUTE.md SS2 "Where the 10 retries go":
    # ten PER REQUEST across the whole ladder, not ten per rung. The number is
    # the owner's brief, not a measurement, and is named here so it is one
    # constant rather than a literal repeated at each call site.
    MAX_ATTEMPTS_PER_REQUEST = 10

    # What the gateway asks for when the caller states no difficulty. Used ONLY
    # to give `guard_response` something to report the budget in; it sets no
    # floor and injects nothing into the request. See `_effort_for`.
    UNSTATED = "UNSTATED"

    def _effort_for(self, difficulty: str | None, options: dict,
                    expected_output_tokens: int) -> tuple[Effort, dict]:
        """Derive the effort floor, and the options that carry it to the wire.

        EFFORT MAY BE RAISED AND NEVER LOWERED, and the load-bearing detail is
        WHERE a caller-supplied `reasoning_effort` goes. It is passed to
        `for_difficulty` as `raise_to`, never merged over the derived value
        afterwards -- a merge would be a bypass wearing the shape of an
        override, and `EffortFloorViolation` would never be raised because
        nothing would ever ask. `core/effort.py` raises rather than clamping for
        the same reason: a silent clamp is how a cost optimisation becomes a
        capability regression that no test sees.

        NO DIFFICULTY STATED MEANS NO FLOOR, NOT A DEFAULT ONE. Choosing a
        difficulty on the caller's behalf would be declaring a fact about a task
        nobody measured, and it would silently rewrite the token budget of every
        pre-existing caller of this method. So the unrouted form leaves the
        options untouched and reports the budget that was ACTUALLY in play --
        which is the caller's, and saying so is the honest reading.
        """
        if difficulty is None:
            budget = options.get("max_tokens") or options.get("n_predict") or 0
            return (Effort(reasoning_effort=str(options.get("reasoning_effort")
                                                or self.UNSTATED),
                           max_tokens=int(budget),
                           difficulty=self.UNSTATED,
                           rationale=("no difficulty was routed to this call, so no "
                                      "floor applies and none was invented; the "
                                      "budget reported here is the caller's own")),
                    dict(options))
        eff = for_difficulty(difficulty,
                             expected_output_tokens=expected_output_tokens,
                             raise_to=options.get("reasoning_effort"))
        out = dict(options)
        out["reasoning_effort"] = eff.reasoning_effort
        # BOTH KEYS, AND THEY MUST NOT DISAGREE. `max_tokens` is the OpenAI
        # spelling and `n_predict` is the local runner's; an adapter reads one
        # of the two, and a budget written to only the key the OTHER adapter
        # reads is a decision that never reaches the call -- the same shape as
        # the `profile_id` defect this module's docstring records.
        out["max_tokens"] = eff.max_tokens
        out["n_predict"] = eff.max_tokens
        return eff, out

    # What a provider's "that request was malformed" can be FIXED BY, here,
    # now, without anyone being asked.
    #
    # THE OWNER'S CORRECTION, 2026-09-07: "vesper doesn't propose a fix, it's
    # vesper's problem in the first place ... vesper should either fix it and
    # resend the request without actually saying it, it only shows up in
    # explanations, actions, and everywhere necessary."
    #
    # AND THEY WERE RIGHT ABOUT THE INVARIANT TOO. `INV-SELF-1..7` is about the
    # runtime editing its own SOURCE, and it was being cited to refuse
    # something else entirely: building the next request correctly. Constructing
    # a well-formed call is not self-modification, it is the job. The proposal
    # path still exists and is now what happens when the request CANNOT be
    # repaired -- a genuine defect in an adapter -- rather than the first answer
    # to every malformed call.
    #
    # EACH ENTRY IS (needles, what to change, how to say it). Keyed on what the
    # provider SAID, which is only readable at all because the CLI classifier
    # learned to capture it.
    REQUEST_REPAIRS: tuple = (
        (("context length", "too many tokens", "maximum context",
          "reduce the length", "max_tokens is too large", "exceeds the limit"),
         "shrink", "asked for fewer tokens than the provider will accept"),
        (("temperature", "top_p", "top_k"),
         "drop_sampling", "dropped the sampling knobs it would not take"),
        (("unknown option", "unrecognized argument", "unexpected keyword",
          "unsupported parameter", "invalid parameter", "not supported"),
         "drop_extras", "dropped the options it does not understand"),
        (("system", "system prompt", "system role"),
         "fold_system", "folded the preamble into the prompt instead of "
                        "sending it as a system turn"),
    )

    @staticmethod
    def _repair_request(options: dict, said: str) -> tuple:
        """One corrective edit to the request, or `(None, "")`.

        RETURNS THE CHANGE IT MADE, because this happens without telling the
        owner and a silent change nobody can inspect afterwards is the thing
        this tree refuses everywhere else. The sentence goes to the board and
        the actions column; it does not go to the talk, because VESPER
        correcting its own call is not news the owner has to act on.
        """
        low = (said or "").lower()
        for needles, how, told in ModelGateway.REQUEST_REPAIRS:
            if not any(n in low for n in needles):
                continue
            out = dict(options or {})
            if how == "shrink":
                cur = int(out.get("max_tokens") or out.get("n_predict") or 0)
                if cur <= 1:
                    continue                     # nothing left to give back
                new = max(1, cur // 2)
                if "max_tokens" in out:
                    out["max_tokens"] = new
                if "n_predict" in out:
                    out["n_predict"] = new
                return out, f"{told} ({cur} -> {new})"
            if how == "drop_sampling":
                gone = [k for k in ("temperature", "top_p", "top_k") if k in out]
                if not gone:
                    continue
                for k in gone:
                    out.pop(k, None)
                return out, f"{told}: {', '.join(gone)}"
            if how == "drop_extras":
                keep = {"max_tokens", "n_predict", "system", "history"}
                gone = [k for k in out if k not in keep]
                if not gone:
                    continue
                for k in gone:
                    out.pop(k, None)
                return out, f"{told}: {', '.join(sorted(gone))}"
            if how == "fold_system":
                if not out.get("system"):
                    continue
                out["_fold_system"] = True
                return out, told
        return None, ""

    @staticmethod
    def _grow_budget(options: dict, effort: Effort) -> dict:
        """Retry an empty answer with a LARGER budget, not the same one.

        MEASURED 2026-08-25: a `200` with `finish_reason: length` and no content
        means reasoning consumed the entire allowance before a content token was
        emitted. Retrying at the same budget reproduces it exactly -- the
        failure is deterministic in the budget, so an identical retry is not a
        retry, it is the same call made twice.

        Doubling rather than adding a fixed margin, because the shortfall is
        unknown: the provider reports what it spent, never what it needed.
        Unused budget costs nothing -- providers bill what was generated, not
        what was permitted -- so the asymmetry is total and the bias is upward.
        """
        current = int(options.get("max_tokens") or options.get("n_predict")
                      or effort.max_tokens or 0)
        grown = max(1, current) * 2
        out = dict(options)
        out["max_tokens"] = grown
        out["n_predict"] = grown
        return out

    def _book_refusal(self, p: Provider, exc: Exception,
                      retry_after_ms: int | None) -> bool:
        """Record a quota refusal against the ledger. True if it is PERMANENT.

        THE `limit` FIELD IS THE ONLY PLACE THE TWO CASES DIFFER. Measured
        2026-08-25 (`MULTI_ROUTE.md` SS13.1): an image model answered
        RESOURCE_EXHAUSTED with `limit: 0` -- the tier has no allowance at all,
        so the first request is refused and so is every one after it. An
        exhausted window returns tomorrow; a zero limit never returns. Same
        status, same classification, opposite fact.

        `quota_limit` is absent on every provider that does not publish one, and
        absent is NOT zero: `record_refusal(limit=None)` books EXHAUSTED, which
        rolls when the window does. Defaulting a missing field to zero would
        permanently retire a working model on its first ordinary rate limit,
        which is the more expensive of the two mistakes by a wide margin.
        """
        limit = getattr(exc, "quota_limit", None)
        if limit is None and _limit_parse_suspect(str(exc)):
            # THE SILENT DEGRADATION THIS EXISTS TO MAKE LOUD. The limit lives
            # only in the vendor's prose -- the structured quota block carries
            # metrics and ids and no limit at all. So a rewording turns a
            # PERMANENT refusal into one that looks temporary, and the ladder
            # retries a dead rung every day forever while every check stays
            # green, because the fixture is frozen and still parses.
            #
            # Routing is deliberately NOT changed here: EXHAUSTED stays the
            # safe default, since defaulting a missing limit to zero would
            # retire a working model on its first ordinary rate limit. This
            # only says so, which is the difference between a defect that gets
            # found and one that quietly costs a rung.
            self._bus.publish(
                "quota.limit_parse_suspect", subject=p.provider_id,
                payload={"provider_id": p.provider_id, "model": p.model,
                         "message_excerpt": str(exc)[:200],
                         "booked_as": "exhausted",
                         "note": ("this refusal names a limit in a shape the "
                                  "parser did not read. A zero limit would be "
                                  "indistinguishable from an ordinary spent "
                                  "window here. RE-MEASURE against a live "
                                  "refusal -- the fixture can no longer tell "
                                  "you.")},
                component="gateway")
        entry = self.quota.record_refusal(
            p.provider_id, p.model, limit=limit,
            retry_after_ms=retry_after_ms,
            source=f"gateway refusal from {p.provider_id}: {str(exc)[:160]}")
        return entry.state == UNAVAILABLE_ON_TIER

    def _book_spend(self, p: Provider, result: dict) -> None:
        """Book what the call cost, and say so when the provider would not.

        A REPORTED ZERO IS TREATED AS UNMEASURED, and this is the opposite of
        the rule `core/projection.py` applies to a reading of 0. The difference
        is that this line is only reached AFTER `guard_response` passed, so the
        response demonstrably carried content -- and a completion that produced
        text cannot have cost zero completion tokens. Measured 2026-08-25
        (`MULTI_ROUTE.md` SS13.5): a provider returned `input_tokens: 0,
        output_tokens: 0, neurons: 0` on a call that plainly worked. A ledger
        trusting that books zero spend forever and concludes the free tier is
        infinite. Here zero is a missing field wearing a number, so it is passed
        as `None` -- which `record_success` books as 1 unit and FLAGS.

        THE FIELD NAME IS NOT ONE FIELD NAME, and reading only one is how this
        method spent its first day booking every remote call as an unmeasured
        guess. It read `tokens_predicted`, which is the LOCAL runner's spelling;
        every remote provider reports under `usage`, and the three wire shapes
        spell it three ways again. So the ledger recorded 1.0 UNMEASURED for
        providers that had just handed it an exact number -- including the two
        that report honestly, which are precisely the ones worth being accurate
        about. Nothing failed; the figures were simply worthless. Same defect
        class as `n_predict` vs `max_tokens`: an adapter's vocabulary treated as
        the system's.
        """
        amount = _completion_tokens(result)
        measured = bool(amount)
        self.quota.record_success(
            p.provider_id, p.model,
            amount=amount if measured else None,
            unit="tokens" if measured else "UNKNOWN",
            measured=measured,
            source=f"gateway success from {p.provider_id}")

    def complete(self, prompt: str, *, task_id: str | None = None,
                 system: str | None = None,
                 history: list | None = None,
                 options: dict | None = None,
                 max_attempts_per_provider: int = 2,
                 max_attempts_per_request: int | None = None,
                 profile_id: str | None = None,
                 difficulty: str | None = None,
                 prefer: str = "cost",
                 expected_output_tokens: int = 1_024,
                 privacy_class: str = "private") -> dict:
        """Call the permitted provider with the most headroom that succeeds.

        Every provider passes the cost check IMMEDIATELY BEFORE invocation, not
        once at entry. A period can change mid-call chain, and a check done at
        entry would authorise a request made after the rule changed.

        THE ATTEMPT BUDGET IS CHAIN-WIDE, AND `max_attempts_per_provider` NO
        LONGER MULTIPLIES BY THE LADDER LENGTH. Two attempts each across six
        rungs is twelve calls for one request, and until 2026-08-25 nothing in
        this method knew that number: the per-provider allowance was the only
        bound, so the real cost of a request was a property of how many
        providers happened to be registered. `max_attempts_per_request` is the
        bound that actually holds, defaulting to
        `MAX_ATTEMPTS_PER_REQUEST`; the per-provider figure is now a cap on how
        long ONE rung may be retried before descending, which is what it always
        read like.

        TWO THINGS DO NOT SPEND IT, for different reasons.

          * A TERMINAL classification costs its one attempt and nothing more.
            MULTI_ROUTE SS2: "Terminal error -> descend immediately, no retry.
            Zero budget spent on a 401." The call happened, so it is counted;
            the RETRIES it would otherwise have bought are not.

          * A `limit == 0` refusal costs NOTHING AT ALL, and the asymmetry is
            deliberate. Discovering that a rung is permanently outside the tier
            is not a retry -- it is ledger maintenance that happens exactly once
            ever, and it benefits every later request. Charging the one request
            unlucky enough to find out would price a permanent improvement as a
            per-request failure. A `401` stays charged because it is not
            permanent knowledge: the credential can be replaced.

        PROVIDER ORDER IS THE LEDGER'S, NOT THE REGISTRY'S. `profile_id` fixed
        WHICH CAPABILITY answers (below); it never said which of several
        providers serving that capability had any quota left, so registration
        order still decided that. `QuotaLedger.rank` decides it now, computed
        per request because which provider is biggest changes through the day as
        each is spent -- and it drops a rung the ledger knows is spent or
        excluded rather than spending an attempt rediscovering it.

        `difficulty` DERIVES THE EFFORT FLOOR AND THE TOKEN BUDGET. Omitting it
        leaves both to the caller and applies no floor; supplying it means a
        caller-supplied `reasoning_effort` is read as a request to RAISE and
        raises `EffortFloorViolation` if it would lower. See `_effort_for`.

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
        # INV-AUTO-2, ENFORCED WHERE THE CAPABILITY IS rather than where the
        # rule is written. `core/autonomy.py` may not import this module --
        # CI-023 forbids it, and the ban is the point -- so the decision path
        # cannot check itself against a model gateway it is not allowed to see.
        # The gateway can check whether it has been reached from inside one.
        #
        # FIRST, before the cost check and before any provider is considered: a
        # violation that got as far as being priced has already been treated as
        # a legitimate request.
        if decision_path.active():
            decision_path.refuse("gateway.complete")

        # THE REDACTOR, AT THE CHOKE POINT AND NOWHERE ELSE. `INV-COST-3`
        # already guarantees no path reaches a provider adapter without passing
        # through here, so this is the one place a guard cannot be bypassed --
        # including by subsystems written later by someone who never read the
        # memory architecture. Nine callers today; the count is not the point,
        # the singularity of the path is.
        #
        # BEFORE THE COST CHECK AND BEFORE ANY PROVIDER IS CHOSEN, for the same
        # reason INV-AUTO-2 is checked first: a credential that got as far as
        # being priced has already been handled as legitimate freight. There is
        # no recall once it goes -- "make the model forget it" does not exist,
        # the bytes are transmitted and the provider's log holds them -- so the
        # only moment this can work is before the request is built.
        #
        # DETERMINISTIC ONLY. Asking a model whether the text contains a secret
        # IS the leak; core/redact.py carries the full argument.
        #
        # HISTORY IS REDACTED TOO, and forgetting it would be the natural bug:
        # conversation history is the one field that carries text the owner
        # typed turns ago, when nothing was watching, and it is replayed to a
        # provider on every subsequent turn rather than once.
        _leaks: list = []
        prompt, _f = redact(prompt, source="prompt")
        _leaks += _f
        if system is not None:
            system, _f = redact(system, source="system")
            _leaks += _f
        if history:
            _clean_history = []
            for _turn in history:
                if isinstance(_turn, dict) and isinstance(_turn.get("content"), str):
                    _text, _f = redact(_turn["content"], source="history")
                    _leaks += _f
                    _turn = {**_turn, "content": _text}
                _clean_history.append(_turn)
            history = _clean_history
        if _leaks:
            # RECORDED WITHOUT THE VALUE. `Finding` has no field the secret
            # could travel in, which is what makes this event safe to keep and
            # safe to ship in a bug report.
            self._bus.publish(
                "gateway.redacted", subject=task_id or "unassigned",
                payload={"task_id": task_id, "count": len(_leaks),
                         "findings": [f.to_dict() for f in _leaks],
                         "note": ("credential-shaped material was removed before "
                                  "egress; the values are deliberately absent "
                                  "from this record")},
                component="gateway")

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

        # THE EFFORT DECISION IS MADE ONCE, BEFORE ANY PROVIDER IS TRIED, and it
        # is allowed to abort the whole request. A floor violation is a defect in
        # the caller, not a property of any rung: discovering it on rung four
        # would mean three providers were already paid to answer a question at a
        # quality the task does not permit.
        effort, call_options = self._effort_for(difficulty, options,
                                                expected_output_tokens)

        # THE PERSONA, IF THE CALLER BROUGHT ONE. A named parameter rather than
        # a key the caller buries in `options`, so that "this request went out
        # with no identity" is visible in the signature and greppable across
        # call sites -- `core/persona.py` records what the absence sounded like.
        #
        # NOT COMPOSED HERE. The gateway is the choke point for what may LEAVE
        # (egress, cost, quota) and composing the preamble here would make it
        # the author of what is said as well, which is `core/persona.py`'s job
        # and answerable to two contracts this module does not read.
        #
        # NOT PUT IN TELEMETRY EITHER, only its length: the preamble carries
        # whatever `voice.toml [owner]` holds, and a field copied verbatim into
        # every `gateway.attempt` event would put it in every checkpoint and
        # every evidence record downstream of one.
        if system:
            call_options["system"] = system
        system_chars = len(system or "")

        # THE CONVERSATION SO FAR, ALREADY BUDGETED BY THE CALLER.
        #
        # A NAMED PARAMETER, LIKE `system`, AND FOR A SHARPER REASON. Until
        # 2026-08-27 `complete` sent one user message and nothing else, so every
        # turn was a cold start -- VESPER was not LOSING the conversation, it had
        # never been given one. A defect that total should be visible in the
        # signature, not buried in an options dict.
        #
        # NOT ASSEMBLED HERE. What goes in is a context decision answerable to
        # `core/context.py`'s budget and to the privacy class; this module
        # decides what may LEAVE, which is a different question about the same
        # bytes. Composing it here would make the choke point the author of the
        # request as well as its gate.
        #
        # COUNTED, NOT COPIED, into telemetry -- the same rule as the preamble.
        # The conversation is the most owner-specific thing in the request and a
        # field echoed into every `gateway.attempt` event would land in every
        # checkpoint downstream of one.
        if history:
            call_options["history"] = list(history)
        history_turns = len(history or ())

        if prefer not in ("cost", "latency"):
            raise ValueError(
                f"unknown prefer={prefer!r}, expected 'cost' or 'latency'. "
                "Refused rather than defaulted, for the same reason "
                "`core/router.py` refuses it: a typo would silently restore the "
                "ordering this parameter exists to override, and the symptom "
                "would be an occasional slow answer with nothing to point at.")

        # ORDER BY HEADROOM. Availability is settled first so that a revoked
        # provider is recorded as skipped exactly once (A-004.3 reads these), and
        # so the ledger is never asked to rank a rung that cannot be called at
        # all.
        callable_now: list[Provider] = []
        for p in providers:
            if not p.available:
                self._record(p, "skipped", "provider_unavailable", None, 0.0)
            else:
                callable_now.append(p)

        by_key: dict[tuple[str, str], Provider] = {}
        offered: list[tuple[str, str]] = []
        for p in callable_now:
            k = p.quota_key()
            if k not in by_key:
                by_key[k] = p
                offered.append(k)
            else:
                # TWO PROVIDERS ON ONE QUOTA LINE, RECORDED RATHER THAN DROPPED.
                # The ledger meters per (provider, model), so a second handle
                # with the same key is not a second budget -- ranking it twice
                # would offer one allowance to the chain as though it were two.
                # Only the first is tried, and the collapse is written down:
                # a rung that vanishes silently is indistinguishable from one
                # that was never registered, and the caller registered it.
                self._record(p, "skipped", "duplicate_quota_key", None, 0.0)
        ranked = self.quota.rank(offered)
        # WHAT THE LEDGER DROPPED IS RECORDED, NOT SILENTLY OMITTED. `rank`
        # returns only the AVAILABLE pairs, so an exhausted window and a
        # `limit: 0` exclusion both vanish from the order -- which is the point,
        # and is also how a rung disappears without anyone being told. The
        # skipped record carries the ledger's own state, so "never tried" and
        # "tried and refused" stay distinguishable in `history`.
        for k in offered:
            if k not in ranked:
                # `quota_ledger_` PREFIXED, not `quota_`. `quota_exhausted` is
                # already a TERMINAL classification meaning "the provider
                # refused us just now", and reusing it for "the ledger did not
                # offer this rung" would put two different events under one
                # label -- one of which involves a call and one of which does
                # not. The outcome field distinguishes them; the label should
                # not need it to.
                self._record(by_key[k], "skipped",
                             f"quota_ledger_{self.quota.entry(*k).state}",
                             None, 0.0)
        providers = [by_key[k] for k in ranked]

        # THEN, IF THE CALLER IS WAITING, RE-ORDER ON OBSERVED SECONDS.
        #
        # HEADROOM IS THE RIGHT PRIMARY KEY AND IT IS NOT A LATENCY KEY. Ranking
        # by headroom spends the largest pool first and keeps the small ones in
        # reserve, which is correct and stays the default. What it cannot see is
        # that the rungs behind one profile are not equally fast: measured
        # 2026-08-26, three rungs share `remote-strong-text-rung1-e1_private` and
        # answer the same greeting in 0.63 s, 2.58 s and 5.27 s. Headroom rotates
        # which one wins as quota is spent, so four consecutive turns took
        # 0.56 s, 4.22 s, 1.02 s and 4.63 s with nothing about the requests
        # differing. That is not a slow ladder, it is a ladder whose speed is
        # decided by an axis unrelated to speed.
        #
        # THE RE-ORDER IS STABLE AND TOTAL-ORDER-SAFE: `sorted` keeps the
        # ledger's sequence among rungs with no observation, so this only ever
        # moves a rung that has actually been timed on this path. A rung nobody
        # has called keeps its headroom position and gets its chance.
        #
        # IT DOES NOT SKIP ANYTHING. Every rung the ledger offered is still in
        # the list and still tried in turn if the ones before it fail; only the
        # order changes. Quota is still what decides whether a rung is offered
        # at all -- this runs strictly after `rank`.
        if prefer == "latency" and self._observed:
            def _seen(pr: Provider) -> tuple:
                o = self._observed.get(pr.provider_id)
                # Unobserved sorts FIRST among equals rather than last: the
                # alternative is self-sealing, a rung never tried is never
                # timed and so is never tried.
                return (0.0 if o is None else o.seconds,)
            providers = sorted(providers, key=_seen)

        budget = (self.MAX_ATTEMPTS_PER_REQUEST
                  if max_attempts_per_request is None
                  else int(max_attempts_per_request))
        # The ceiling, kept so an attempt can say WHICH of how many it is.
        # Derived from the starting budget rather than the class constant,
        # because a caller may pass its own and "attempt 3 of 10" would then be
        # a lie about a request that was only ever allowed 3.
        budget_cap = budget

        for p in providers:
            if budget <= 0:
                # THE LADDER STOPS WHERE THE BUDGET DOES. Recorded per untried
                # rung rather than once, because "we ran out at rung 3" and "we
                # ran out at rung 5" are different facts about the same request
                # and only the history distinguishes them.
                self._record(p, "skipped", "chain_budget_exhausted", None, 0.0)
                continue

            # THE EGRESS CHECK, AND IT RUNS BEFORE THE COST CHECK.
            #
            # Deliberately first: cost decides whether VESPER may SPEND on this
            # provider, egress decides whether this provider may SEE this
            # content. A refusal on price that happens to preempt a privacy
            # violation is luck, and a rule that depends on another rule failing
            # first is not enforced. It also keeps the ordering honest in the
            # record -- the reason recorded is the real reason.
            #
            # Re-checked per provider for the same reason cost is: the ladder
            # descends across suppliers with different egress classes, and a
            # check done once at entry would authorise every later rung.
            permitted_egress = MAY_CARRY.get(privacy_class)
            if permitted_egress is None:
                raise EgressRefused(
                    f"unknown privacy_class {privacy_class!r}; expected "
                    f"{sorted(MAY_CARRY)}. Refused rather than defaulted: a "
                    "typo would otherwise silently select the most permissive "
                    "reading of what may leave the machine.")
            if p.egress_class not in permitted_egress:
                self._record(p, "refused_by_egress", "egress_policy", None, 0.0)
                self._bus.publish(
                    "privacy.egress_refused", subject=p.provider_id,
                    payload={"provider_id": p.provider_id,
                             "provider_egress_class": p.egress_class,
                             "privacy_class": privacy_class,
                             "task_id": task_id,
                             "note": ("R6: egress gates the provider BEFORE "
                                      "quota does. Capacity never buys "
                                      "permission -- the two most generous "
                                      "free tiers available are both public-"
                                      "only, so a ladder ranked on headroom "
                                      "would reach exactly the wrong ones.")},
                    component="gateway")
                last_error = EgressRefused(
                    f"{p.provider_id} is {p.egress_class} and this content is "
                    f"{privacy_class!r}")
                continue

            # The cost choke point. Re-checked per provider, deliberately.
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

            # Grown in place when an empty answer is retried, so the SECOND
            # attempt on this rung is not a byte-identical repeat of the first.
            attempt_options = dict(call_options)
            # PER RUNG, NOT PER REQUEST. Each provider gets one chance to have
            # its own complaint answered -- a body one vendor rejects is often
            # exactly what the next one wants.
            repaired = False

            for i in range(max_attempts_per_provider):
                if budget <= 0:
                    self._record(p, "skipped", "chain_budget_exhausted",
                                 None, 0.0, cost_class=eff)
                    break
                t0 = time.perf_counter()
                # THE BOUNDARY. Counted here because this is the line that
                # actually reaches a provider; anywhere earlier counts intent.
                with self._lock:
                    self.attempts_by_class[eff] = self.attempts_by_class.get(eff, 0) + 1
                budget -= 1
                err: Exception | None = None
                answered_empty = False
                try:
                    result = p.call(prompt, attempt_options)
                except Exception as e:  # noqa: BLE001
                    err = e
                else:
                    # A SUCCESS STATUS IS NOT A SUCCESSFUL ANSWER, and this is
                    # the one boundary every call crosses. `routing/
                    # http_completion.py` carries a guard of its own and it is
                    # NOT a substitute: it is one adapter's, it keys on that
                    # vendor's field spelling for the reasoning text, and a
                    # response carrying reasoning under a different key walks
                    # straight through it with empty content. INV-COST-3's
                    # argument for a single choke point is the same argument.
                    try:
                        guard_response(result.get("text"),
                                       result.get("stop_reason"), effort)
                    except Exception as e:  # noqa: BLE001
                        err = e
                        answered_empty = True
                if err is not None:
                    ms = (time.perf_counter() - t0) * 1000.0
                    cls = getattr(err, "classification", "server_error")
                    hint = getattr(err, "retry_after_ms", None)
                    permanent = False
                    if cls in QUOTA_CLASSIFICATIONS:
                        permanent = self._book_refusal(p, err, hint)
                        if permanent:
                            # REFUNDED, and it is a refund rather than a
                            # never-charged because the shape is only knowable
                            # AFTER the call. See `complete`'s docstring for why
                            # this and a 401 are priced differently.
                            budget += 1
                    delay = None if permanent else self._retry_delay_ms(cls, i, hint)
                    if answered_empty:
                        attempt_options = self._grow_budget(attempt_options, effort)
                    # A MALFORMED REQUEST IS OURS. FIX IT AND SEND A GOOD ONE.
                    #
                    # Owner, 2026-09-07: "vesper doesn't propose a fix, it's
                    # vesper's problem in the first place ... vesper should
                    # either fix it and resend the request without actually
                    # saying it". `bad_request` is TERMINAL, so without this the
                    # rung is abandoned on a call VESPER built wrong -- and the
                    # repairer then filed a PATCH for something that was one
                    # corrected field away from working.
                    #
                    # ONCE PER RUNG, and that bound is the whole safety of it.
                    # `repaired` is set before the retry, so a provider that
                    # rejects the corrected request too is terminal exactly as
                    # it was: this can add one attempt, never a loop. A second
                    # rejection is a real defect and reaches the proposal path
                    # with an extra fact -- that the obvious correction did not
                    # help.
                    if cls == "bad_request" and not repaired:
                        fixed, told = self._repair_request(
                            attempt_options, str(getattr(err, "args", [""])[0]))
                        if fixed is not None:
                            repaired = True
                            attempt_options = fixed
                            delay = 0
                            # RECORDED WHERE THE OWNER CAN LOOK, NOT SAID.
                            # This is VESPER correcting its own call; it belongs
                            # on the boards and not in a sentence read aloud.
                            self._bus.publish(
                                "gateway.request_repaired",
                                subject=p.provider_id,
                                payload={"provider_id": p.provider_id,
                                         "said": str(getattr(err, "args", [""])[0])[:300],
                                         "changed": told,
                                         "task_id": task_id},
                                component="gateway")
                    self._record(p, "error",
                                 "quota_unavailable_on_tier" if permanent else cls,
                                 delay, ms, cost_class=eff,
                                 server_retry_after_ms=hint,
                                 # NO +1: the budget is decremented BEFORE the
                                 # call, so by the time an error is recorded
                                 # this attempt has already been paid for.
                                 # With the +1 the first attempt announced
                                 # itself as "2 of 10" -- a confident sentence
                                 # off by one, which is the kind of wrong the
                                 # owner has no reason to doubt.
                                 attempt=(budget_cap - budget),
                                 max_attempts=budget_cap)
                    last_error = err
                    if delay is None:
                        break  # terminal for this provider
                    self._sleep(delay / 1000.0)
                    continue
                ms = (time.perf_counter() - t0) * 1000.0
                self._book_spend(p, result)
                self._record(p, "ok", None, None, ms, cost_class=eff)
                return {"provider_id": p.provider_id, "profile_id": p.profile_id,
                        "system_chars": system_chars,
                        "history_turns": history_turns,
                        "result": result, "effort": effort.to_dict(),
                        "attempts_remaining": budget}

        # Nothing permitted succeeded. Checkpoint and queue -- do NOT escalate.
        if task_id:
            self._cost.exhausted(task_id)
        raise AllProvidersExhausted(
            "every permitted provider was unavailable, refused or failed. "
            "Task checkpointed and queued for the next permitted period; no "
            "paid escalation (RB-017) and the owner was not woken (SR-042). "
            f"Last error: {last_error}")

    def seed_observation(self, provider_id: str, seconds: float) -> None:
        """Prime a rung's latency estimate from an enrolment measurement.

        SEPARATE FROM THE INTERNAL RECORDING PATH so that "measured here, just
        now" and "measured at enrolment" cannot be confused at the call site --
        and it is a no-op if the rung has already been called, because a live
        sample is better evidence than a cold one and must never be overwritten
        by registration running again.
        """
        if seconds <= 0 or provider_id in self._observed:
            return
        with self._lock:
            self._observed[provider_id] = Observation(provider_id, seconds)

    def observed(self, provider_id: str) -> Observation | None:
        """Live wall-clock seconds for one rung, or None if never called here."""
        return self._observed.get(provider_id)

    def _record(self, p: Provider, outcome: str, classification: str | None,
                retry_after_ms: int | None, elapsed_ms: float,
                cost_class: str = "unknown",
                server_retry_after_ms: int | None = None,
                attempt: int | None = None,
                max_attempts: int | None = None) -> None:
        """Publish what happened, INCLUDING WHERE IN THE BUDGET IT HAPPENED.

        `attempt` and `max_attempts` are carried because SR-004 asks for the
        retry state to be SHOWN, and a subscriber cannot reconstruct it: the
        chain budget is spent across providers, so "which attempt is this"
        is a property of the request and not of any one rung. Without them the
        narration said "Attempt 1 of 10" on every line of a failover -- a
        confident, well-formed sentence carrying the wrong number, which is
        worse than saying nothing because the owner has no reason to doubt it.
        """
        a = Attempt(p.provider_id, cost_class, outcome, classification,
                    retry_after_ms, elapsed_ms, server_retry_after_ms)
        with self._lock:
            self.history.append(a)
            # RECORDED FROM THE SAME NUMBER THE RECORD ALREADY CARRIED. This
            # module has timed every attempt since it was written and used the
            # figure only for telemetry; the ordering above needed exactly it.
            # Bookkeeping that nothing reads is the cheapest thing in a system
            # to leave broken, which is why it was.
            #
            # SKIPS ARE EXCLUDED (elapsed 0.0) -- a rung that was never called
            # has no duration, and folding a zero in would make an untried rung
            # look like the fastest one on the ladder. Errors ARE included: a
            # rung that took 40 s to fail is a slow rung.
            if elapsed_ms > 0.0:
                o = self._observed.get(p.provider_id)
                if o is None:
                    self._observed[p.provider_id] = Observation(
                        p.provider_id, elapsed_ms / 1000.0)
                else:
                    o.update(elapsed_ms / 1000.0)
        self._bus.publish("gateway.attempt", subject=p.provider_id,
                          payload={"provider_id": p.provider_id,
                                   "cost_class": cost_class, "outcome": outcome,
                                   "classification": classification,
                                   "retry_after_ms": retry_after_ms,
                                   "server_retry_after_ms": server_retry_after_ms,
                                   "elapsed_ms": round(elapsed_ms, 2),
                                   "attempt": attempt,
                                   "max_attempts": max_attempts},
                          component="gateway")

    def paid_attempts(self) -> int:
        """A-004.3 asserts this is ZERO after the FREE_TIME revocation run."""
        with self._lock:
            return self.attempts_by_class.get("paid", 0)
