"""Capability registry — argument-sensitive levels, refused constants (INV-AUTH-5).

THE ONE IDEA: A CAPABILITY'S AUTHORITY LEVEL IS A FUNCTION OF ITS ARGUMENTS,
NOT OF ITS NAME. `shell.run("ls")` and `shell.run("rm -rf ~")` are the same
capability and must resolve to different levels — A-013 states exactly that as
a concrete assertion. A registry keyed on tool name gives them the same level
and is therefore wrong before any grant is consulted.

A CONSTANT LEVEL IS REFUSED AT REGISTRATION, not warned about later (A-024.5).
The schema requires `declared_level_rules` to have at least two entries so that
a constant is UNEXPRESSIBLE, and this module enforces the same thing on the
callable form: a rule set that returns one level for every input it is probed
with is rejected. Registration is the only moment the mistake is cheap; after
it, the capability is in the system and every call site trusts it.

WHY THE PROBE IS ADVERSARIAL RATHER THAN TRUSTING. A registry could take the
developer's word that their function is argument-sensitive. This one calls it
with each rule's own declared example and checks that at least two distinct
levels come back. A function that claims sensitivity and delivers a constant is
the exact shape CI-011 exists to catch, and catching it needs evidence rather
than a promise.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
LEVEL_RANK = {l: i for i, l in enumerate(LEVELS)}

REVERSIBILITY = ("reversible", "compensatable", "irreversible")
ACTUATION_SCOPE = ("NONE", "AUTONOMOUS_ACTUATION", "ALARM_ACTUATION")


class ConstantLevelRefused(Exception):
    """A capability whose declared level does not vary with its arguments."""


class UnknownCapability(Exception):
    pass


@dataclass(slots=True)
class LevelRule:
    """One (predicate, level) pair, plus an example that exercises it.

    `example` is required. Without it the registry cannot probe the function
    and the constant check degrades to trusting the declaration — which is the
    thing being checked.
    """

    name: str
    level: str
    example: dict


@dataclass(slots=True)
class Capability:
    capability_id: str
    declared_level: Callable[[dict], str]
    rules: list
    reversibility: str = "reversible"
    actuation_scope: str = "NONE"
    external_effect: bool = False
    requires_owner_confirmation: bool = False
    owner_administrative: bool = False
    model_access: bool = False
    required_level: Callable[[dict], str] | None = None

    def required(self, args: dict) -> str:
        """`authorized <=> effective_level >= required_level(args)`.

        Defaults to the declared level. Kept separate because the two answer
        different questions: declared is "how much authority does doing this
        with THESE arguments amount to", required is "how much must you hold".
        """
        if self.required_level is not None:
            return self.required_level(args)
        return self.declared_level(args)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}
        self._lock = threading.RLock()

    def register(self, capability_id: str,
                 declared_level: Callable[[dict], str],
                 rules: list, **kw: Any) -> Capability:
        if len(rules) < 2:
            raise ConstantLevelRefused(
                f"{capability_id!r} declares {len(rules)} level rule(s). At least "
                "two are required so that a constant level is UNEXPRESSIBLE "
                "(INV-AUTH-5). A capability whose level does not depend on its "
                "arguments cannot distinguish `ls` from `rm -rf ~`.")

        # Probe adversarially: call the real function with each rule's own
        # example and demand that the answers are not all the same.
        seen: set[str] = set()
        for r in rules:
            lvl = declared_level(r.example)
            if lvl not in LEVELS:
                raise ValueError(
                    f"{capability_id!r} rule {r.name!r} produced level {lvl!r}, "
                    f"not in {LEVELS}")
            seen.add(lvl)
        if len(seen) < 2:
            raise ConstantLevelRefused(
                f"{capability_id!r} declares {len(rules)} rules but returns the "
                f"single level {seen.pop()!r} for every declared example. It is "
                "constant in fact whatever it claims in shape -- refused at "
                "registration (A-024.5), because after this point every call "
                "site would trust it.")

        cap = Capability(capability_id=capability_id,
                         declared_level=declared_level, rules=list(rules), **kw)
        with self._lock:
            self._caps[capability_id] = cap
        return cap

    def get(self, capability_id: str) -> Capability:
        try:
            return self._caps[capability_id]
        except KeyError:
            raise UnknownCapability(
                f"no capability {capability_id!r} is registered. There is no "
                "ambient authority: an unregistered capability has no level and "
                "cannot be invoked.") from None

    def ids(self) -> list[str]:
        return sorted(self._caps)
