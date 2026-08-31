"""The two machine-checkable strategies, which were declared and never built.

`core/verify.py` lists `MACHINE_CHECKABLE = ("deterministic",
"retrieval_grounded")` and `Verifier` is a registry with nothing registered in
it. The consequence is not a crash, which is why it survived: a free-time task
declaring either kind passes `should_defer` as verifiable, reaches `verify()`,
finds no registered function, and comes back `passed=False, "no verifier
registered"` -- BLOCKED, so `INV-VERIF-1` holds and nothing looks wrong. What
was lost is `INV-VERIF-2`: unverifiable free-time work is supposed to QUEUE, and
a queued task runs again when a verifier exists while a BLOCKED one is a failure
record. The task also spent a free-time slot producing work that could never
have been admitted.

DF-VERIFY-SELECT TAKES `available_verifiers` AS AN INPUT and `should_defer` read
only the declared kind. A strategy NAME is not a strategy. That is the same
class of error as `INV-HW-2`'s -- a declared capability standing in for a
measured one -- and it is fixed here the same way: ask what is actually
registered.

NEITHER VERIFIER MAY CALL A MODEL. `DF-VERIFY-SELECT` is `model_access = false`,
and the reason is `INV-VERIF-3`: a model judging output is the least reliable
verifier available, and admitting one through the machine-checkable door would
make `self_model`'s prohibition decorative -- the same opinion, relabelled.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .evidence import Unsupported

# The assertion keys `deterministic` understands. TYPED, and a criteria dict
# carrying none of them is an ERROR rather than a trivially satisfied test --
# see `deterministic` for why that distinction is the whole point.
ASSERTIONS = ("equals", "contains", "not_contains", "matches", "min_length")


def _text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for k in ("text", "value", "result", "answer"):
            v = output.get(k)
            if isinstance(v, str):
                return v
    return str(output)


def deterministic(output: Any, criteria: dict) -> tuple:
    """Typed predicates over the output. No shell, no model, no network.

    AN EMPTY CRITERIA DICT FAILS, and this is the case worth being careful
    about. The natural implementation walks the declared assertions and returns
    `all(results)` -- which is `True` for zero assertions. A task whose criteria
    key was misspelled then has NOTHING checked and reports SUCCEEDED, in
    FREE_TIME, unattended. Vacuous truth is the most dangerous verdict this
    module can return, because it is indistinguishable from a real pass.
    """
    checks = [k for k in ASSERTIONS if k in criteria]
    if not checks:
        return False, (
            f"no assertion in verification criteria: expected at least one of "
            f"{ASSERTIONS}, got keys {sorted(criteria)}. Zero assertions is not "
            "a passing test -- it is an unchecked task that reports success.")

    text = _text(output)
    failures = []
    for k in checks:
        want = criteria[k]
        if k == "equals" and text != want:
            failures.append(f"equals: {text[:60]!r} != {str(want)[:60]!r}")
        elif k == "contains" and str(want) not in text:
            failures.append(f"contains: {str(want)[:60]!r} absent")
        elif k == "not_contains" and str(want) in text:
            failures.append(f"not_contains: {str(want)[:60]!r} present")
        elif k == "matches" and not re.search(str(want), text):
            failures.append(f"matches: {str(want)[:60]!r} did not match")
        elif k == "min_length" and len(text) < int(want):
            failures.append(f"min_length: {len(text)} < {int(want)}")
    if failures:
        return False, "; ".join(failures)
    return True, f"{len(checks)} assertion(s) held: {', '.join(checks)}"


def grounded(checker: Any) -> Callable[[Any, dict], tuple]:
    """`retrieval_grounded`, built on `ClaimChecker`.

    THIS IS WHAT THE STRATEGY MEANT ALL ALONG and could not do until a
    memory-derived claim could carry support: every assertion in the output
    resolves to a span that re-reads, or the task is not verified. A file span
    re-reads its bytes; a log receipt re-reads its record and confirms the
    quoted text is in it.

    NO CLAIMS IS NOT A PASS. An output nobody extracted claims from has had
    nothing checked, and returning True there would make the strategy report
    success most confidently on the outputs it understood least.

    IT NEVER RAISES `Unsupported` OUT OF HERE. `Verifier.verify` catches an
    exception into a failed verdict, so raising would work -- and would report
    "verifier raised Unsupported" as though the VERIFIER were broken rather than
    the output ungrounded. The distinction matters when someone reads the
    verdict later to decide whether to retry.
    """

    def _run(output: Any, criteria: dict) -> tuple:
        claims = criteria.get("claims")
        if claims is None and isinstance(output, dict):
            claims = output.get("claims")
        if not claims:
            return False, (
                "no claims to check: an output whose assertions were never "
                "extracted has had nothing verified, and a pass here would be "
                "most confident about the outputs least understood")
        try:
            report = checker.check(list(claims),
                                   policy_class=criteria.get("policy_class",
                                                             "world_fact"))
        except Unsupported as exc:
            # CAUGHT HERE ON PURPOSE. `ClaimChecker` RAISES in a gated policy
            # class -- that is its contract, and it is right: an unsupported
            # claim must not reach an emission path. But `Verifier.verify`
            # converts any exception into "verifier raised X", which reports the
            # VERIFIER as broken when what is actually wrong is the OUTPUT. The
            # distinction decides whether someone later retries the task or
            # fixes the checker.
            return False, f"claims do not resolve: {exc}"
        if report["unsupported"]:
            worst = [d for d in report["detail"] if d["problems"]]
            return False, (
                f"{report['unsupported']} of {report['claims']} claims do not "
                f"resolve to a reproducible span. First: "
                f"{worst[0]['problems'][0][:160]}")
        return True, (f"all {report['claims']} claims resolve to spans that "
                      "re-read to what was cited")

    return _run


def register_all(verifier: Any, checker: Any = None) -> tuple:
    """Register the machine-checkable strategies that are actually available.

    RETURNS WHAT IT REGISTERED rather than assuming. With no `ClaimChecker` --
    a runtime with no memory, which `vesper_runtime` supports and records --
    `retrieval_grounded` genuinely is not available, and saying so is what lets
    `should_defer` queue those tasks instead of running them into a BLOCKED
    verdict that reads like a failure of the work.
    """
    verifier.register("deterministic", deterministic)
    if checker is not None:
        verifier.register("retrieval_grounded", grounded(checker))
        return ("deterministic", "retrieval_grounded")
    return ("deterministic",)
