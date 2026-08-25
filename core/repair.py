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
            "in ~/.config/vesper/secrets.env. Keep the same variable name.",
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
        """Ours to fix, and therefore a PROPOSAL rather than a repair.

        A malformed request is a defect in VESPER, so the fix is a code change
        -- and INV-SELF-1..7 forbid the runtime writing a governed path in the
        running artifact. Filing a patch into `workspace/` with its failing
        test is the sanctioned path, and it is deliberately not self-applying.
        """
        return RepairOutcome(
            item.item_id, TIER2, False,
            actions=["classified as a VESPER defect rather than a provider fault"],
            guide=[
                f"{item.provider_id} rejected our request as malformed "
                f"{item.count()}x. This will recur identically on every future "
                "call until the request changes -- it is not transient.",
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
