"""A stronger model reviews a risky action before it happens — and can only stop it.

WHAT THIS IS FOR. VESPER forms a plan with the model that fits the task, which
is usually the cheapest one that can do it. For an action that cannot be undone
— replacing a file it has not read, running something outside the workspace,
touching its own code — a second opinion from a stronger model is worth one call.
That is the same shape as the advisor the owner watched being used to build this
system, and it is where the idea came from.

THE ASYMMETRY IS THE WHOLE DESIGN, AND WITHOUT IT THIS IS AN ATTACK. An advisor
that could say "go ahead" and have that mean something is a way to MANUFACTURE
the owner's consent: feed it a document that argues for the action, receive
approval, act. `INV-ACT-3` exists because content entering the system must never
raise the authority of anything, and advice is content entering the system.

So the verdict is one-directional. `PROCEED` changes NOTHING — the action faces
the identical ladder it faced before, and the advisor's opinion is recorded as an
observation. Only `STOP` has an effect, and its effect is to make VESPER ask the
owner. An advisor can add caution and can never remove it, which makes it useful
and useless as a way in.

IT IS CONSULTED ON WHAT CANNOT BE UNDONE, not on everything. Advice on every
`fs.read` would be a tax on the ordinary path, and an advisor consulted about
trivia is an advisor whose warnings stop being read. The trigger is the
capability's own declared reversibility and level, both of which the ladder has
already computed by the time this is reached.

AND ITS SILENCE IS NOT APPROVAL. A rung that is missing, unauthenticated, slow or
broken yields `UNAVAILABLE`, which is treated as exactly what it is: no advice.
The action proceeds down its normal ladder, because an advisor that is absent
must not become a reason to be MORE permissive than a system with no advisor at
all — and must not become a reason to halt everything either, which would make an
unauthenticated directory a denial of service on the owner's own machine.
"""

from __future__ import annotations

from typing import Any

PROCEED = "proceed"
STOP = "stop"
UNAVAILABLE = "unavailable"

# How much of the plan the advisor is shown, and how much it may say back. It
# reads the action and its context, not the turn's whole history: a reviewer
# given everything reviews nothing in particular.
MAX_CONTEXT_CHARS = 8000
MAX_ADVICE_CHARS = 2000
ADVISOR_TIMEOUT_S = 60.0

SYSTEM = (
    "You are reviewing one action another system is about to take on its "
    "owner's computer, before it happens. You are not deciding whether it is "
    "allowed -- a permission system already does that. You are asked whether it "
    "looks like a mistake: something irreversible aimed at the wrong target, a "
    "misreading of what was asked, or a step whose consequences the owner would "
    "not expect.\n\n"
    "Answer in this form and nothing else:\n"
    "VERDICT: PROCEED or STOP\n"
    "BECAUSE: one sentence.\n\n"
    "Say STOP only if you would want the owner asked first. If it looks "
    "ordinary, say PROCEED -- saying PROCEED does not authorise anything, it "
    "only declines to add a warning.")


class Advisor:
    """One review, one verdict, no authority."""

    def __init__(self, gateway: Any, *, router: Any = None, bus: Any = None,
                 profile_id: str = "") -> None:
        self._gw = gateway
        self._router = router
        self._bus = bus
        self._profile_id = profile_id

    def available(self) -> bool:
        return self._gw is not None and (
            self._router is not None or bool(self._profile_id))

    def review(self, *, capability_id: str, args: dict, why: str = "",
               asked_for: str = "", level: str = "") -> dict:
        """Ask, and return a verdict that can only ever add caution."""
        if not self.available():
            return self._verdict(UNAVAILABLE, "no advisor rung is enrolled",
                                 capability_id)
        plan = (f"The owner asked: {str(asked_for)[:1000]}\n"
                f"The action: {capability_id} (authorisation level {level})\n"
                f"Its arguments: {str(args)[:2000]}\n"
                f"Its stated reason: {str(why)[:500]}")[:MAX_CONTEXT_CHARS]
        try:
            profile = self._profile_id
            if not profile and self._router is not None:
                profile = self._router.select(
                    "hard", prefer="cost", task_id="advisor").profile_id
            out = self._gw.complete(
                plan, task_id="advisor", system=SYSTEM,
                profile_id=profile, prefer="cost",
                expected_output_tokens=200, difficulty="hard")
            text = ((out.get("result") or {}).get("text") or "").strip()
        except Exception as exc:                       # noqa: BLE001
            # A BROKEN ADVISOR IS NO ADVICE, NOT A HALT. Otherwise an
            # unauthenticated directory becomes a denial of service on the
            # owner's own machine, and a flaky rung becomes one intermittently.
            return self._verdict(UNAVAILABLE,
                                 f"the advisor could not be reached: "
                                 f"{type(exc).__name__}", capability_id)

        # PARSED CONSERVATIVELY, AND ANYTHING UNCLEAR IS *NOT* A STOP. An
        # advisor whose garbled answer halted the turn would make every provider
        # hiccup look like a warning, and the owner would learn to wave them
        # through -- which is how a confirmation becomes a formality.
        head = text[:MAX_ADVICE_CHARS]
        upper = head.upper()
        verdict = STOP if "VERDICT: STOP" in upper else PROCEED
        because = ""
        for line in head.splitlines():
            if line.strip().upper().startswith("BECAUSE:"):
                because = line.split(":", 1)[1].strip()
                break
        return self._verdict(verdict, because or head[:200], capability_id,
                             advice=head)

    def _verdict(self, verdict: str, because: str, capability_id: str,
                 advice: str = "") -> dict:
        out = {"verdict": verdict, "because": because,
               "capability_id": capability_id, "advice": advice,
               # ADVICE IS CONTENT ENTERING THE SYSTEM, and is classed as such
               # whatever it says. This is the field that stops a reviewer's
               # words being read as an instruction later.
               "trust_class": "retrieved_external",
               "note": ("advice can add caution and can never remove it: "
                        "PROCEED changes nothing and the action faces the same "
                        "ladder it already faced")}
        if self._bus is not None:
            try:
                self._bus.publish("advisor.reviewed", subject=capability_id,
                                  payload={k: v for k, v in out.items()
                                           if k != "advice"},
                                  component="advisor")
            except Exception:                          # noqa: BLE001
                pass
        return out


def worth_reviewing(cap: Any, level: str) -> bool:
    """Is this action worth one call to a stronger model?

    IRREVERSIBILITY FIRST, because it is the property that makes a mistake
    permanent rather than merely wrong, and it is declared on the capability
    rather than inferred here. Then the levels the ladder itself treats as
    grave: L4 and L5 are the tiers that are never delegable and are spent by the
    single action they were granted for.

    A CHEAP READ IS NOT REVIEWED. An advisor consulted about trivia is an
    advisor whose warnings stop being read, which costs more than the calls do.
    """
    if getattr(cap, "external_effect", False):
        return True
    if str(getattr(cap, "reversibility", "")) == "irreversible":
        return True
    return str(level) in ("L4", "L5")
