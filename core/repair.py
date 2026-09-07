"""Attempting to fix a graded failure, and admitting when it cannot be fixed.

THE HONEST SHAPE OF THIS PROBLEM. Very few provider failures can be repaired
from inside the runtime, and a repair layer that pretends otherwise produces
theatre: a sequence of confident-looking actions that change nothing, followed
by the same failure. So this module does three things and says which one it did.

  TIER 1 -- autonomous. Reversible, inside the runtime's own state, touching no
  governed surface. Rotating to a sibling credential already present, standing
  a rung down until a stated time, re-reading an endpoint's identity. No
  approval, because nothing here can do damage that is not undone by doing it
  again.

  TIER 2 -- proposed, never applied. Anything whose fix is a change to VESPER
  itself. `core/selfmod.py` and INV-SELF-1..7 forbid the runtime writing a
  governed path in the running artifact; it may write the same content to
  `workspace/`, run the gate, and file a proposal. A-030.6 requires that path
  to SUCCEED -- it is the intended way for VESPER to fix itself, and it is
  deliberately not self-application.

  TIER 3 -- the owner's hands. Anything on a provider's console: billing, key
  rotation, plan toggles, privacy settings. VESPER produces the exact steps and
  does not drive the browser. A repair path that logs into the owner's provider
  account is one injected error message away from being steered, and the error
  text being reacted to came FROM the provider -- it is data, not instruction.

WHEN ALL THREE FAIL, THE ESCALATION IS THE DELIVERABLE. Not "I could not fix
it" but a guide naming what was tried, what each attempt returned, what that
rules out, and the exact remaining steps. That is the brief's "full detailed
guide", and it is worth treating as a first-class output rather than an
apology.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .triage import CRITICAL_NOW, TriageItem

TIER1, TIER2, TIER3 = "tier1_autonomous", "tier2_proposed", "tier3_owner"


@dataclass
class RepairOutcome:
    """What was attempted and what actually changed. Never a bare verdict."""

    item_id: str
    tier: str
    fixed: bool
    actions: list = field(default_factory=list)
    guide: list = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "tier": self.tier, "fixed": self.fixed,
                "actions": self.actions, "guide": self.guide, "note": self.note}


class RepairAgent:
    """Attempts tier-1 repair; escalates with a guide when it cannot."""

    def __init__(self, *, ledger: Any = None, gateway: Any = None,
                 supply_rows: list | None = None, bus: Any = None) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._rows = list(supply_rows or [])
        self._bus = bus
        self._lock = threading.RLock()

    # ------------------------------------------------------------- entry

    def repair(self, item: TriageItem) -> RepairOutcome:
        """Only CRITICAL_NOW is acted on without the owner.

        A CRITICAL_DEFERRED item has a workaround that is holding, and acting
        on it anyway spends risk to buy nothing -- the ladder already routed
        around it. CAN_WAIT and NO_FIX_NEEDED are reports, not work.
        """
        if item.grade != CRITICAL_NOW:
            return RepairOutcome(
                item.item_id, TIER1, False,
                note=(f"grade is {item.grade!r}, not {CRITICAL_NOW}. Only a "
                      "failure that is down AND will stay down is repaired "
                      "unattended; the rest are reported. Acting on a "
                      "problem whose workaround is holding spends risk to "
                      "buy nothing."))

        handler = {
            "auth_failed": self._auth_failed,
            "bad_request": self._bad_request,
            "no_provider_for_profile": self._no_provider,
            "rate_limited": self._rate_limited,
            "quota_exhausted": self._rate_limited,
            "model_gone": self._model_gone,
        }.get(item.classification)

        if handler is None:
            return self._escalate(item, [
                f"No tier-1 action exists for {item.classification!r}.",
                "This is a gap in the repair rules, not a fault in the "
                "provider -- record it as such rather than reading it as "
                "'nothing can be done'.",
            ], note="no tier-1 handler for this classification")
        out = handler(item)
        if self._bus is not None:
            self._bus.publish("repair.attempted", subject=item.item_id,
                              payload=out.to_dict(), component="repair")
        return out

    # -------------------------------------------------------- tier-1 actions

    def _rate_limited(self, item: TriageItem) -> RepairOutcome:
        """A limit. Nothing to repair -- the owner's case ONE.

        THEIR RULE, IN THEIR WORDS: "normal retrying should be only when the
        usage hits its limit". The request was well formed, the credential is
        good, the model exists; what ran out was allowance, and allowance comes
        back on its own. There is no edit that makes this call succeed sooner.

        SO THE REPAIR IS TO DO NOTHING, AND TO SAY SO. Before this handler
        existed a limit fell through to `_escalate`, which reported "no tier-1
        action exists for this classification" -- filing a GAP IN VESPER'S
        REPAIR RULES against a provider that was behaving exactly as designed.
        Measured 2026-09-07 on `claude-advisor`: an exhausted session limit
        produced a triage item, a repair attempt, and a proposed patch.

        THE GUIDE STILL SAYS SOMETHING USEFUL, because "wait" is not the whole
        answer when the owner is sharing the account.
        """
        return RepairOutcome(
            item.item_id, TIER1, False,
            actions=["recorded as a limit that returns on its own; no request "
                     "was changed and no rung was retired"],
            guide=[f"{item.provider_id} refused on allowance, not on anything "
                   f"about the request. It returns when the window rolls.",
                   "If this rung is shared with something else -- the owner's "
                   "own use of the same account, another modality on the same "
                   "key -- the two are competing for one limit, and the fix is "
                   "a separate credential rather than a change here.",
                   "Nothing to apply. This item closes itself when the next "
                   "call succeeds."],
            note="a limit that resets: retry is the correct and only response")

    def _model_gone(self, item: TriageItem) -> RepairOutcome:
        """The provider dropped this model. Use another of ITS models.

        THE OWNER'S CASE THREE: "if the provider dropped that model, vesper
        should mark that model as unavailable and use another one in the same
        provider". A rung is a (provider, model) pair, so the model going away
        retires the ROW and says nothing about the account, the credential or
        the egress class -- all of which are still good.

        `model_gone` IS TERMINAL IN `core/gateway.py`, which is what already
        stops the row being retried. This handler's job is the other half: to
        say plainly that the row is gone rather than leaving the ladder one
        rung shorter for a reason nobody wrote down, and to name what would
        restore it.

        NOT DONE HERE: editing `provider_supply.toml`. That contract is the
        owner's, `INV-SELF-1..7` keeps the runtime out of its own definition,
        and a model substitution chosen unattended is a routing decision made
        by the thing being routed.
        """
        return RepairOutcome(
            item.item_id, TIER1, False,
            actions=[f"marked {item.model or 'this model'} unavailable on "
                     f"{item.provider_id}; the rung is terminal and the ladder "
                     f"moves to the next row"],
            guide=[f"{item.provider_id} no longer serves "
                   f"{item.model or 'that model'}. The account and the "
                   f"credential are fine -- only the model is gone.",
                   f"If {item.provider_id} has another model at this tier, add "
                   f"a row for it in contracts/policy/provider_supply.toml. "
                   f"That file is the owner's; the runtime does not edit its "
                   f"own routing.",
                   "Until then the ladder is one rung shorter at this tier, "
                   "which is a real reduction in cover rather than a nuisance."],
            note="the model is gone; the provider is not")

    def _auth_failed(self, item: TriageItem) -> RepairOutcome:
        """Rotate to a sibling credential if one exists; otherwise escalate.

        A SIBLING IS A DIFFERENT KEY FOR THE SAME SERVICE, and rotating to one
        is tier 1 because it uses a credential the owner already provided --
        nothing is created, nothing is stored, nothing is spent that was not
        already available. When the whole service is down to one key, there is
        nothing to rotate to and this becomes tier 3 immediately.
        """
        actions = []
        family = _family(item.provider_id)
        siblings = [r for r in self._rows
                    if _family(_row_id(r)) == family and _row_id(r) != item.provider_id]

        if self._ledger is not None:
            # Stand the failing rung down so the ladder stops offering it while
            # the credential is bad. Reversible: the window rolls on its own.
            e = self._ledger.entry(item.provider_id, item.model)
            e.state = "exhausted"
            actions.append(
                f"stood {item.provider_id} down in the ledger so the ladder "
                "stops offering a rung whose credential is refused (reversible "
                "-- the window rolls on its own)")

        if siblings:
            names = [_row_id(r) for r in siblings]
            actions.append(
                f"{len(siblings)} sibling credential(s) for this service remain "
                f"usable: {names}. The ladder will reach them without any "
                "change -- rotation here is the ABSENCE of an action, not an "
                "action, because the ranking already skips a stood-down rung.")
            return RepairOutcome(
                item.item_id, TIER1, True, actions=actions,
                note=("service still reachable through a sibling credential; "
                      "the owner is told at the daily summary rather than "
                      "interrupted"))

        return self._escalate(item, [
            f"Open the provider's console for {family!r}.",
            "Check whether the API key has expired, been revoked, or had its "
            "permissions changed. A key that worked and now returns 401/403 "
            "usually means one of those three.",
            "If the key is dead, create a new one and replace the value of "
            f"`{_env_of(self._rows, item.provider_id) or 'its environment variable'}` "
            "with tools/ops/vesper_keychain.py --migrate after putting it in "
            "~/.config/vesper/secrets.env. Keep the same variable name. "
            "The keychain overlays the file, so editing the file alone "
            "changes nothing once a key has been migrated.",
            "Re-run: python3.13 tools/ops/check_credentials.py",
            "Then: python3.13 tools/spike/probe_remote_supply.py "
            f"--only {item.provider_id}",
            "That last command is the confirmation -- it makes a real call. A "
            "key that is present in the file is not a key that works.",
        ], actions=actions,
           note=("no sibling credential exists for this service, so the whole "
                 "rung is down until a person replaces the key. VESPER cannot "
                 "obtain one: creating credentials is the owner's, by rule."))

    def _bad_request(self, item: TriageItem) -> RepairOutcome:
        """The request could not be corrected at send time. NOW it is a defect.

        THIS IS NO LONGER THE FIRST ANSWER TO A MALFORMED CALL, and it used to
        be. `ModelGateway._repair_request` gets there first: it reads what the
        provider said, corrects the request -- fewer tokens, drop the option
        the vendor does not take, fold the system turn into the prompt -- and
        sends a good one, once per rung, without telling anybody. The owner's
        correction, 2026-09-07: "it's vesper's problem in the first place ...
        vesper should either fix it and resend the request without actually
        saying it".

        AND THE INVARIANT WAS BEING MISCITED. `INV-SELF-1..7` is about the
        runtime editing its own SOURCE. Building the next request correctly is
        not self-modification, it is the job, and quoting the invariant at it
        turned a one-field correction into a patch for the owner to review.

        REACHING HERE NOW MEANS SOMETHING SHARPER: the obvious correction was
        tried and the provider rejected the request anyway. That IS a defect in
        the adapter's wire format, it will recur identically, and a code change
        is the honest answer -- proposed, never self-applied.
        """
        return RepairOutcome(
            item.item_id, TIER2, False,
            actions=["the request was corrected and re-sent once at the "
                     "gateway and was rejected again; only then is this a "
                     "defect rather than a badly built call"],
            guide=[
                f"{item.provider_id} rejected our request as malformed "
                f"{item.count()}x, INCLUDING after the gateway corrected it and "
                f"re-sent. The obvious repairs -- a smaller budget, dropping "
                f"the options this vendor does not take, folding the system "
                f"turn into the prompt -- did not help, which is what makes "
                f"this a wire-format defect rather than a badly built call.",
                "The evidence is on the triage item: each attempt's detail is "
                "stored, not a summary of them.",
                "The fix belongs in the adapter for this provider's wire "
                "format, in routing/. A patch plus its failing test goes to "
                "workspace/ for review; the runtime may not apply it to itself "
                "(INV-SELF-1..7, A-030.6).",
            ],
            note=("tier 2: VESPER's own defect. Proposed, never self-applied "
                  "-- a runtime that can edit its own governed paths can "
                  "neutralise every other boundary."))

    def _no_provider(self, item: TriageItem) -> RepairOutcome:
        """A routed capability with nothing serving it. Configuration, not fault."""
        return self._escalate(item, [
            "The router selected a capability and no registered provider "
            "serves it. Nothing failed -- the ladder was never built for that "
            "profile.",
            "Check contracts/policy/provider_supply.toml for a row at the "
            "required tier and egress class.",
            "If a row exists, it was skipped at registration. Run: python3.13 "
            "-c \"import sys;sys.path.insert(0,'.');from routing.supply import "
            "load_rows;print(load_rows()[1])\" -- the skip reason is printed, "
            "never silent.",
        ], note="configuration gap; the fix is a reviewed row, not a runtime action")

    # ----------------------------------------------------------- escalation

    def _escalate(self, item: TriageItem, steps: list, *,
                  actions: list | None = None, note: str = "") -> RepairOutcome:
        """Build the guide. WHAT WAS TRIED IS PART OF IT, not a footnote.

        A guide that lists only the remaining steps makes the owner repeat work
        already done and hides what has been ruled out. The attempts come
        first, then what they eliminate, then what is left.
        """
        header = [
            f"FAILURE: {item.classification} on {item.provider_id} "
            f"({item.model}), {item.count()} occurrence(s).",
            f"WHY THIS NEEDS YOU: {item.grade_reason}",
        ]
        tried = ([f"ALREADY ATTEMPTED: {a}" for a in (actions or [])]
                 or ["ALREADY ATTEMPTED: nothing -- no autonomous action "
                     "applies to this failure."])
        return RepairOutcome(item.item_id, TIER3, False,
                             actions=list(actions or []),
                             guide=header + tried + ["REMAINING STEPS:"] + steps,
                             note=note)


def _family(provider_id: str) -> str:
    """Service family: `google-a1` and `google-a2` are the same service.

    Split on the first hyphen because the supply table names rows
    `<service>-<variant>`. A row with no hyphen is its own family.
    """
    return provider_id.split("-", 1)[0]


def _row_id(row: Any) -> str:
    return getattr(row, "provider_id", None) or (
        row.get("id") if isinstance(row, dict) else str(row))


def _env_of(rows: list, provider_id: str) -> str | None:
    for r in rows:
        if _row_id(r) == provider_id:
            return (getattr(r, "credential_env", None)
                    or (r.get("credential_env") if isinstance(r, dict) else None))
    return None
