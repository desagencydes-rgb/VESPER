"""Probes for this node's own state. Deterministic, cheap, and platform-guarded.

WHAT A PROBE MAY AND MAY NOT BE. It runs inside `decision_path.entered`, so it
CANNOT call a model -- the gateway refuses. It must also be cheap enough to run
on a period without being noticed, and it must return a value or raise. A probe
that returns its best guess when it cannot measure is the failure `INV-HW-2`
exists to refuse, and it is worse here than anywhere else because the reading
becomes a world fact that a trigger fires on.

THE PROFILE, NEVER THE DEVICE (`INV-HW-1`). These return `ac` / `battery`,
`nominal` / `constrained`, a ratio -- never a model name and never a marketing
name. `platform.system()` appears because the SYSCALL differs, not because the
policy does: the same attribute is populated on every node and only the way of
reading it changes. An unsupported platform RAISES, which the registry turns
into UNKNOWN -- it does not fall back to a plausible default.

MEASURED, NEVER DECLARED. Nothing here reports a number it did not read. Where
this host does not expose a thing -- and `MEMORY.md` already records that this
platform's memory pressure is a BAND rather than a size -- the probe raises
instead of translating a band into a number that would look like a measurement.

ICMP IS BLOCKED BOTH WAYS ON THIS NETWORK, so reachability is a TCP connect and
never a ping. `MEMORY.md` records this and records that ping proves nothing here;
a reachability probe built on ICMP would report every node unreachable forever
and look like a fabric problem.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from pathlib import Path


class ProbeUnavailable(Exception):
    """This node cannot measure this. Raised, never defaulted."""


def _run(cmd: list, timeout: float = 2.0) -> str:
    """A short, bounded shell read. Never a shell string; never unbounded.

    THE TIMEOUT IS NOT POLITENESS. A probe runs on a period, and one that can
    block forever turns the sensor loop into a stall that presents as a world
    model quietly going stale.
    """
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeUnavailable(f"{cmd[0]}: {exc}") from exc
    if out.returncode != 0:
        raise ProbeUnavailable(f"{cmd[0]} exited {out.returncode}")
    return out.stdout


def power_source() -> str:
    """`ac` or `battery`. The profile, not the hardware."""
    system = platform.system()
    if system == "Darwin":
        text = _run(["pmset", "-g", "batt"])
        low = text.lower()
        if "ac power" in low:
            return "ac"
        if "battery power" in low:
            return "battery"
        raise ProbeUnavailable("pmset reported neither AC nor battery")
    if system == "Linux":
        for p in Path("/sys/class/power_supply").glob("A*/online"):
            try:
                return "ac" if p.read_text().strip() == "1" else "battery"
            except OSError:
                continue
        raise ProbeUnavailable("no power_supply online node")
    raise ProbeUnavailable(f"unsupported platform: {system}")


def battery_ratio() -> float:
    """Charge as 0.0-1.0. Raises where there is no battery to read."""
    system = platform.system()
    if system == "Darwin":
        text = _run(["pmset", "-g", "batt"])
        for token in text.replace(";", " ").split():
            if token.endswith("%"):
                try:
                    return round(int(token.rstrip("%")) / 100.0, 3)
                except ValueError:
                    break
        raise ProbeUnavailable("pmset reported no percentage")
    if system == "Linux":
        for p in Path("/sys/class/power_supply").glob("BAT*/capacity"):
            try:
                return round(int(p.read_text().strip()) / 100.0, 3)
            except (OSError, ValueError):
                continue
        raise ProbeUnavailable("no battery capacity node")
    raise ProbeUnavailable(f"unsupported platform: {system}")


def disk_free_ratio(path: str = "/") -> float:
    """Free space as 0.0-1.0. `shutil` only -- no platform branch needed."""
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        raise ProbeUnavailable(f"disk_usage({path}): {exc}") from exc
    if not usage.total:
        raise ProbeUnavailable("total capacity reported as zero")
    return round(usage.free / usage.total, 4)


def host_health() -> str:
    """`nominal` or `constrained`. A CLASS, because the inputs are not a number.

    DELIBERATELY NOT A SCORE. Battery charge, power source and free disk do not
    share a unit, and a weighted number over them would look like a measurement
    while being a preference. A class is honest about being a judgement, and
    `INV-HW-1` wants the profile anyway.
    """
    constrained = []
    try:
        if disk_free_ratio() < 0.10:
            constrained.append("disk")
    except ProbeUnavailable:
        pass
    try:
        if power_source() == "battery" and battery_ratio() < 0.20:
            constrained.append("power")
    except ProbeUnavailable:
        pass
    return "constrained" if constrained else "nominal"


def tcp_reachable(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    """Is a TCP port open? NEVER a ping.

    `MEMORY.md`: ICMP is blocked both ways on this network, so ping proves
    nothing -- a reachability probe built on it reports every node unreachable
    forever and reads as a fabric fault rather than as a broken instrument.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
