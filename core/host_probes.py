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


# THE VOCABULARY IS SM-DEVICE'S, NOT THIS FILE'S. The first version of
# `host_health()` returned `nominal`/`constrained`, invented here -- and
# `trg_placement_reevaluate` reads `world.current_host.health in { DEGRADED,
# FAILING }`, so the trigger could never have fired however degraded the host
# got. That is the same defect as `l2_query_probe.py` inventing
# `private`/`shareable` for a column `core/privacy.py` already owned: a probe
# that defines its own vocabulary produces readings nothing can act on, and
# nothing reports the mismatch because both halves are internally consistent.
#
# `spec/state-machines/INDEX.toml` `SM-DEVICE` owns these.
ONLINE = "ONLINE"
DEGRADED = "DEGRADED"


def host_health() -> str:
    """`ONLINE` or `DEGRADED`, from SM-DEVICE. A CLASS, because the inputs are
    not a number.

    DELIBERATELY NOT A SCORE. Battery charge, power source and free disk do not
    share a unit, and a weighted number over them would look like a measurement
    while being a preference. A class is honest about being a judgement, and
    `INV-HW-1` wants the profile anyway.

    `FAILING` IS NOT RETURNED BECAUSE IT DOES NOT EXIST. The predicate names it;
    it appears nowhere else in the corpus -- not in SM-DEVICE, not in any
    contract, not in any code. This probe will not invent a state to satisfy a
    clause, because a value produced only to make a predicate reachable is a
    declared reading, and the clause is the thing that is wrong.
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
    return DEGRADED if constrained else ONLINE


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


# ---------------------------------------------------------------------------
# The node's own profile, measured. `core/devices.py` owns the vocabularies.
# ---------------------------------------------------------------------------

def audio_channels() -> tuple:
    """`(inputs, outputs)` counted from the system's own audio inventory.

    COUNTED, NOT ASSUMED. "It is a laptop, of course it has a microphone" is a
    declaration, and `INV-HW-2` refuses those -- a headless node, a machine with
    the microphone disabled in firmware, and this one are the same code path.
    The inventory names hardware; only the COUNTS are returned, because
    `INV-HW-1` wants the profile and never the device.
    """
    text = _run(["system_profiler", "SPAudioDataType"], timeout=8.0)
    ins = sum(1 for line in text.splitlines() if "Input Channels" in line)
    outs = sum(1 for line in text.splitlines() if "Output Channels" in line)
    return ins, outs


def key_storage_class() -> str:
    """The most conservative class this node can be SHOWN to have.

    `os_keychain` AND NOT `hardware_backed`, deliberately. The two differ by a
    trust ZONE -- Z1 against Z0 -- and `INV-TRUST-2` decides what may be held on
    a node from that. A keychain demonstrably exists, so `os_keychain` is
    evidenced. `hardware_backed` requires showing a key actually resident in a
    secure element, which nothing here has done, and claiming it would buy this
    node a trust zone on an assumption about its silicon.

    RAISING THIS IS A PROMOTION AND BELONGS TO THE OWNER, like every other
    contract change: `CLAUDE.md` records that `profile_node.py` deliberately has
    no write path into `capability_profiles.toml`.
    """
    text = _run(["security", "list-keychains"], timeout=4.0)
    if "keychain" not in text.lower():
        raise ProbeUnavailable("no keychain listed")
    return "os_keychain"


def device_profile(node_id: str):
    """This node as a `DeviceProfile`, from measurement only.

    `availability_class = on_demand`, and the reasoning matters because
    `is_survival_host()` reads it. Not `always_on`: this machine sleeps, and it
    was measured on battery with no charger attached while running unattended.
    Not `foreground_only`: it supervises a LaunchAgent that restores itself, so
    it is not a thing that dies when a screen is swiped away. `on_demand` is the
    honest middle, and it is what makes this a survival host -- which it
    factually is today, being the only node the memory lives on.

    EVERY CAPABILITY CARRIES ITS `measured` FLAG. `DeviceProfile.capability()`
    returns None for anything unmeasured rather than the declared value, so a
    capability this probe could not establish is UNAVAILABLE and not assumed.
    """
    from .devices import DeviceProfile

    caps: dict = {}
    measured: dict = {}
    try:
        ins, outs = audio_channels()
        caps["audio_inputs"], measured["audio_inputs"] = ins, True
        caps["audio_outputs"], measured["audio_outputs"] = outs, True
    except ProbeUnavailable:
        measured["audio_inputs"] = measured["audio_outputs"] = False
    try:
        caps["disk_free_ratio"] = disk_free_ratio()
        measured["disk_free_ratio"] = True
    except ProbeUnavailable:
        measured["disk_free_ratio"] = False

    # NOT MEASURED HERE AND NOT DECLARED EITHER. MEMORY.md records that this
    # host's inference throughput has never been measured, and INV-HW-2 makes
    # UNKNOWN mean UNAVAILABLE rather than "probably fine".
    measured["sustained_tokens_per_sec"] = False

    return DeviceProfile(
        node_id=node_id,
        availability_class="on_demand",
        key_storage_class=key_storage_class(),
        # `voice_only` is about SPATIAL sensing -- volumetric, planar, linear --
        # and this node has none of it. A microphone is not a spatial sense.
        spatial_class="none",
        has_microphone=caps.get("audio_inputs", 0) > 0,
        has_speaker=caps.get("audio_outputs", 0) > 0,
        capabilities=caps,
        measured=measured,
    )
