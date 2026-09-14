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


# The charge below which a host counts as about to stop. Read from
# `contracts/policy/tunables.toml`, which owns it -- a threshold hard-coded here
# would be a policy dial living outside the governed surface that exists for
# policy dials, and `INV-TUNE-1` is the rule about exactly that.
def _critical_ratio() -> float:
    import tomllib
    from pathlib import Path as _P
    t = _P(__file__).resolve().parents[1] / "contracts" / "policy" / "tunables.toml"
    try:
        return float(tomllib.loads(t.read_text())["tunable"]["battery_critical_ratio"]["default"])
    except Exception:                              # noqa: BLE001
        # FAIL TOWARD FIRING. If the contract cannot be read, a host on battery
        # is treated as critical sooner rather than later: the trigger this
        # feeds exists to move work OFF a dying machine, and being early costs
        # one relocation while being late costs the work.
        return 0.20


def camera_presence(path=None, now_ms=None):
    """`someone`, `nobody`, or None (UNKNOWN) from the last camera probe.

    THE CAMERA IS GATED AND THIS IS NOT THE CAMERA. `docs/design/VISION-
    IDENTITY.md`: presence is a flag set when the camera is asked, read from
    memory like any fact. The probe (`VESPER --camera-probe`, the owner's
    press) writes `presence.json`; this reads it, and past 120 s it reads
    UNKNOWN -- `INV-COORD-2`: an expired fact is never its last value, and
    unknown fails toward withholding. Detection, not identity.
    """
    import json as _json
    import pathlib as _pl
    import time as _t
    p = _pl.Path(path) if path else (_pl.Path.home() / "Library" / "Application Support" / "VESPER" / "presence.json")
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
        now = float(now_ms) if now_ms is not None else _t.time() * 1000
        if now - float(d.get("at_ms", 0)) > 120_000:
            return None
        return "someone" if d.get("someone") else "nobody"
    except Exception:                                     # noqa: BLE001
        return None


def power_source() -> str:
    """`ac`, `battery`, or `battery_critical`. The profile, not the hardware.

    `battery_critical` EXISTS BECAUSE A PREDICATE ALREADY READ IT.
    `trg_placement_reevaluate` has always tested
    `world.current_host.power_source == battery_critical`, and until 2026-08-31
    that value appeared nowhere else in the corpus -- no contract defined it and
    this probe produced only `ac`/`battery`, so the clause could never match and
    that third of the trigger was dead. The machine ran unattended to 27% on
    battery the night before, which is precisely the state it was written for.
    """
    system = platform.system()
    if system == "Darwin":
        text = _run(["pmset", "-g", "batt"])
        low = text.lower()
        if "ac power" in low:
            return "ac"
        if "battery power" in low:
            # THE CHARGE IS READ HERE RATHER THAN BY THE CALLER, because
            # "on battery" and "on battery and about to stop" are different
            # facts about the world and a caller comparing two readings could
            # see them from different moments.
            try:
                return "battery_critical" if battery_ratio() < _critical_ratio() else "battery"
            except ProbeUnavailable:
                return "battery"
        raise ProbeUnavailable("pmset reported neither AC nor battery")
    if system == "Linux":
        for p in Path("/sys/class/power_supply").glob("A*/online"):
            try:
                if p.read_text().strip() == "1":
                    return "ac"
                try:
                    return ("battery_critical"
                            if battery_ratio() < _critical_ratio() else "battery")
                except ProbeUnavailable:
                    return "battery"
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
FAILING = "FAILING"


def host_health() -> str:
    """`ONLINE` or `DEGRADED`, from SM-DEVICE. A CLASS, because the inputs are
    not a number.

    DELIBERATELY NOT A SCORE. Battery charge, power source and free disk do not
    share a unit, and a weighted number over them would look like a measurement
    while being a preference. A class is honest about being a judgement, and
    `INV-HW-1` wants the profile anyway.

    THREE STATES, AND THE DIFFERENCE BETWEEN THE LAST TWO IS TIME.
    `DEGRADED` is impaired and still working -- it can be lived with. `FAILING`
    is about to stop, and it is the one `trg_placement_reevaluate` needs in
    order to move work off this host while there is still a host to move it
    from. The trigger's own note is "waiting politely while the host dies is the
    wrong failure direction".

    `FAILING` WAS ADDED TO SM-DEVICE ON 2026-08-31 rather than invented here.
    Until then the predicate read a state no state machine defined, and this
    probe deliberately refused to produce it -- a value made up only to satisfy
    a clause is a declared reading, and inventing one would have hidden that the
    contract was the thing missing.
    """
    # FAILING FIRST. Losing power is not a degree of impairment, it is the end
    # of the host, and a check ordered the other way would report DEGRADED for a
    # machine with minutes left.
    try:
        if power_source() == "battery_critical":
            return FAILING
    except ProbeUnavailable:
        pass
    try:
        if disk_free_ratio() < 0.10:
            return DEGRADED
    except ProbeUnavailable:
        pass
    # ON BATTERY IS NOT DEGRADED. A laptop away from a socket is a laptop, and
    # reporting it impaired would make the ordinary state of this host an
    # exception -- the earlier version did exactly that.
    return ONLINE


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
