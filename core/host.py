"""Host collaboration -- reading the machine VESPER runs on, and acting on it
only through the declared vocabulary.

WHY THIS MODULE EXISTS, AND WHY IT IS NOT A SECOND SCHEDULER.

The operating system already contains a resource governor: it maps work onto
core types, compresses memory rather than paging, manages thermals and parks
idle clusters. VESPER contains one too. The failure mode when two schedulers
share a machine and cannot see each other is not inefficiency, it is
oscillation -- VESPER decides to run, the platform decides to throttle, and
each reacts to the other's reaction.

So this module does not schedule. It does two things:

  1. READS the platform's own signals, translated into VESPER's vocabulary by
     an adapter that knows what they mean HERE. This is the whole difficulty:
     the signals do not port. A number that means "healthy" on one platform
     means "about to fail" on another, and the shared logic must never see the
     raw value.
  2. REFUSES any action not in contracts/policy/host_actions.toml.

WHY REFUSAL IS THE INTERESTING HALF.

The platform offers no negotiation interface. There is no call that asks it for
permission and receives an answer -- signals flow outward and nothing flows
back. VESPER therefore cannot ask; it can only act and re-read the world.
That makes the action vocabulary the entire safety boundary, with nothing
behind it, which is why lookup here is fail-closed and why risk class is read
from the contract rather than judged at runtime. See INV-HOST-1/2 and CI-056.

UNAVAILABLE IS NOT NOMINAL. Every sensor below reports a value or reports that
it could not read one, and the second case is treated as PRESSURE rather than
as health. This is INV-HW-2's rule applied to sensors: UNKNOWN means
UNAVAILABLE, fail-closed. A thermal probe that fails and is read as "nominal"
removes exactly the backpressure it exists to provide, and it does so silently,
at the moment the machine is least able to afford it.
"""

from __future__ import annotations

import platform
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONTRACT_PATH = (Path(__file__).resolve().parents[1]
                 / "contracts" / "policy" / "host_actions.toml")

# Ordered weakest to strongest. Index comparison is the only ordering used;
# the strings are never compared lexically anywhere in this module.
EXECUTION_CLASSES = ("maintenance", "deferrable", "responsive", "interactive")

# Ordered benign to severe, so `>=` is a meaningful test. UNKNOWN sits at the
# severe end deliberately -- see the module docstring.
THERMAL_LEVELS = ("nominal", "fair", "serious", "critical", "unknown")

_SUBPROCESS_TIMEOUT_S = 10


class HostContractViolation(Exception):
    """The action vocabulary is malformed or absent.

    Raised rather than defaulted, for the same reason the fabric contract
    raises: a missing vocabulary is not an empty vocabulary. Empty means
    "VESPER may do nothing", which is safe; absent means the file that bounds
    what VESPER may do could not be read, and continuing past that point is
    running with the boundary unknown rather than closed.
    """


class ActionRefused(Exception):
    """An action was requested that the vocabulary does not permit."""


@dataclass(frozen=True)
class HostPressure:
    """What the platform is telling us about its own condition, translated.

    `memory_available_gb` is deliberately NOT "free memory". On at least one
    supported platform those differ by a factor of forty, and the free-memory
    reading is the one that looks alarming while the machine is entirely
    healthy. The adapter owns that translation; nothing above this dataclass
    may see a raw platform counter.

    `memory_pressure_band` is a band and never a size. It is carried alongside
    the gigabyte figure rather than instead of it because on the platform where
    it exists it does NOT track allocation -- measured 2026-08-20, it moved by
    the equivalent of 0.16 GB against a real 1.5 GB allocation. As a pressure
    signal it is useful; multiplied by total memory it overstates headroom by
    several gigabytes, which is how a model gets placed on a node that cannot
    hold it.
    """
    thermal: str
    memory_available_gb: float | None
    memory_pressure_band: int | None
    swap_in_use: bool | None
    on_battery: bool | None
    charge_percent: int | None
    errors: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        """True when the host is under pressure OR cannot be read.

        The `or cannot be read` half is the point. A caller asking "should I
        back off?" must get yes when the answer is unknown, because the cost of
        backing off unnecessarily is a slower background task and the cost of
        not backing off when the machine is in trouble is the owner's machine
        in trouble.
        """
        if self.errors:
            return True
        if THERMAL_LEVELS.index(self.thermal) >= THERMAL_LEVELS.index("fair"):
            return True
        if self.swap_in_use:
            return True
        return False


class HostAdapter:
    """Base adapter: reports nothing and admits it.

    The default implementation is not a stub to be filled in later -- it is the
    correct behaviour on an unrecognised platform. Every read returns an error
    string, HostPressure.degraded becomes True, and VESPER runs conservatively
    on a machine it cannot characterise. A base class that returned plausible
    defaults would make an unsupported platform indistinguishable from a
    healthy one.
    """

    name = "unsupported"

    def read_pressure(self) -> HostPressure:
        return HostPressure(
            thermal="unknown", memory_available_gb=None,
            memory_pressure_band=None, swap_in_use=None,
            on_battery=None, charge_percent=None,
            errors=(f"no host adapter for platform {platform.system()!r}",),
        )

    def execution_class_command(self, cls: str) -> list[str]:
        raise HostContractViolation(
            f"no host adapter for platform {platform.system()!r}; "
            f"execution class {cls!r} cannot be applied"
        )


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_SUBPROCESS_TIMEOUT_S, check=True).stdout
    except Exception:  # noqa: BLE001 -- any failure is "could not read"
        return None


class DarwinAdapter(HostAdapter):
    """Translations calibrated on this platform 2026-08-20, not read from docs.

    Each mapping below was settled by allocating a known quantity and observing
    which counter moved by its size. Three plausible readings of "available
    memory" disagreed by more than a factor of two, and the one that looked
    most authoritative -- the kernel's own single-number pressure level -- was
    the one that did not track allocation at all.
    """

    name = "darwin"

    # The platform reports thermal pressure as an integer over a notification
    # channel. The mapping is to VESPER's vocabulary, not to the platform's
    # own names, so that a caller comparing thermal levels never has to know
    # which platform produced the reading.
    _THERMAL = {0: "nominal", 1: "fair", 2: "serious", 3: "critical", 4: "critical"}

    _CLAMPS = {
        # MEASURED on this node: identical fixed workload, min of three runs.
        # interactive/responsive are unclamped and unclamped-equivalent -- the
        # utility clamp measured 0.735 s against 0.755 s unclamped, i.e. no
        # penalty, because it still reaches the performance cores. The
        # background clamp measured 3.962 s: a 5.25x cost, which is efficiency
        # core confinement and is the price of not competing with the owner.
        "interactive": [],
        "responsive": ["taskpolicy", "-c", "utility"],
        "deferrable": ["taskpolicy", "-c", "background"],
        "maintenance": ["taskpolicy", "-c", "maintenance"],
    }

    def execution_class_command(self, cls: str) -> list[str]:
        if cls not in EXECUTION_CLASSES:
            raise HostContractViolation(f"unknown execution class {cls!r}")
        return list(self._CLAMPS[cls])

    def read_pressure(self) -> HostPressure:
        errors: list[str] = []

        thermal = "unknown"
        out = _run(["notifyutil", "-g", "com.apple.system.thermalpressurelevel"])
        if out is None:
            errors.append("thermal pressure unreadable")
        else:
            m = re.search(r"(\d+)\s*$", out.strip())
            if m:
                thermal = self._THERMAL.get(int(m.group(1)), "unknown")
                if thermal == "unknown":
                    errors.append(f"unmapped thermal level {m.group(1)}")
            else:
                errors.append(f"unparseable thermal reading {out.strip()!r}")

        avail = None
        out = _run(["vm_stat"])
        if out is None:
            errors.append("vm_stat unreadable")
        else:
            m = re.search(r"page size of (\d+) bytes", out)
            page = int(m.group(1)) if m else 0
            pages: dict[str, int] = {}
            for line in out.splitlines():
                m = re.match(r'"?Pages? ([^:"]+)"?:\s+(\d+)', line.strip())
                if m:
                    pages[m.group(1).strip().lower()] = int(m.group(2))
            if page and pages:
                # free + inactive + speculative. NOT `free` alone, which read
                # 2.08 GB immediately before this machine absorbed 1.5 GB
                # without swapping, and NOT plus `purgeable`, which is a subset
                # of active/inactive and would double-count.
                n = sum(pages.get(k, 0) for k in ("free", "inactive", "speculative"))
                avail = round(n * page / (1024 ** 3), 2)
            else:
                errors.append("vm_stat gave no usable page accounting")

        band = None
        out = _run(["sysctl", "-n", "kern.memorystatus_level"])
        if out is not None and out.strip().lstrip("-").isdigit():
            band = int(out.strip())

        swap = None
        out = _run(["sysctl", "-n", "vm.swapusage"])
        if out is None:
            errors.append("swap state unreadable")
        else:
            m = re.search(r"used\s*=\s*([\d.]+)([KMG])", out)
            if m:
                mult = {"K": 1 / 1024, "M": 1.0, "G": 1024.0}[m.group(2)]
                swap = (float(m.group(1)) * mult) > 0.0
            else:
                errors.append("swap usage unparseable")

        on_batt, pct = None, None
        out = _run(["pmset", "-g", "batt"])
        if out is None:
            errors.append("power source unreadable")
        else:
            on_batt = "Battery Power" in out
            m = re.search(r"(\d+)%", out)
            if m:
                pct = int(m.group(1))

        return HostPressure(
            thermal=thermal, memory_available_gb=avail,
            memory_pressure_band=band, swap_in_use=swap,
            on_battery=on_batt, charge_percent=pct,
            errors=tuple(errors),
        )


def adapter_for_host() -> HostAdapter:
    return DarwinAdapter() if platform.system() == "Darwin" else HostAdapter()


@dataclass(frozen=True)
class Action:
    name: str
    tier: str
    enabled: bool
    reversible: bool
    inverse: str
    requires_owner_consent: str
    max_targets_per_window: int | None
    window_seconds: int | None


class ActionVocabulary:
    """The closed set of things VESPER may do to its host.

    Loading is strict and lookup is fail-closed. There is deliberately no
    `permit_unknown` switch and no way to add an action at runtime: the
    vocabulary is a reviewed artifact, and a process that can extend its own
    permitted set does not have a permitted set.
    """

    def __init__(self, path: Path | None = None) -> None:
        p = path or CONTRACT_PATH
        if not p.is_file():
            raise HostContractViolation(
                f"action vocabulary missing at {p}. An absent boundary is not "
                f"a closed one -- refusing to run rather than running unbounded."
            )
        doc = tomllib.loads(p.read_text(encoding="utf-8"))
        pol = doc.get("policy", {})
        if pol.get("fail_closed") is not True:
            raise HostContractViolation("policy.fail_closed is not true")
        self.provenance_required: str = pol.get("action_provenance_required", "")
        self.tiers: tuple[str, ...] = tuple(pol.get("tiers") or ())
        self.non_mutating: frozenset[str] = frozenset(pol.get("non_mutating_tiers") or ())
        read_line = pol.get("read_line")
        if read_line not in self.tiers:
            raise HostContractViolation(f"read_line {read_line!r} is not a declared tier")
        self._line = self.tiers.index(read_line)
        self._actions = {
            name: Action(
                name=name, tier=a["tier"], enabled=bool(a["enabled"]),
                reversible=bool(a["reversible"]), inverse=a.get("inverse", ""),
                requires_owner_consent=a["requires_owner_consent"],
                max_targets_per_window=a.get("max_targets_per_window"),
                window_seconds=a.get("window_seconds"),
            )
            for name, a in (doc.get("action") or {}).items()
        }
        if not self._actions:
            raise HostContractViolation("vocabulary declares no actions")

    def changes_host(self, name: str) -> bool:
        """True when the action reaches outside VESPER's own process.

        Not the same as "changes anything": the `self` tier sits below the read
        line and still mutates -- it changes VESPER's own scheduling and model
        residency. The line separates what belongs to the owner's machine from
        what belongs to VESPER.
        """
        a = self._actions.get(name)
        return a is not None and self.tiers.index(a.tier) > self._line

    def check(self, name: str, *, provenance: str,
              owner_authorisation: str | None = None) -> Action:
        """Return the action, or raise. There is no boolean form of this call.

        Returning False for "not permitted" invites `if not permitted: log()`
        and carry on. Raising means a caller that forgets to handle refusal
        stops, which on this boundary is the correct failure.
        """
        a = self._actions.get(name)
        if a is None:
            raise ActionRefused(
                f"{name!r} is not in the action vocabulary. The vocabulary is "
                f"closed: absence is refusal, not permission."
            )
        if provenance != self.provenance_required:
            raise ActionRefused(
                f"{name!r} requires {self.provenance_required!r} provenance and "
                f"was offered {provenance!r}. Advice may come from anywhere; "
                f"action on this machine may not."
            )
        if not a.enabled:
            raise ActionRefused(
                f"{name!r} is declared but disabled. Enabling it is a governed "
                f"act recorded against the contract, not a runtime decision."
            )
        if self.changes_host(name) and not owner_authorisation:
            raise ActionRefused(
                f"{name!r} changes the host and carries no owner authorisation. "
                f"Owner policy: VESPER reports a change and the owner applies it."
            )
        return a

    def enabled_actions(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, a in self._actions.items() if a.enabled))

    def __len__(self) -> int:
        return len(self._actions)
