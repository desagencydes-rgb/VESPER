#!/usr/bin/env python3
"""Measure the NodeCapabilityProfile fields SPIKE-001 structurally cannot. Stdlib only.

WHY THIS FILE EXISTS. `build_node_profile.py` refuses six fields, and its
reason for each is correct: a throughput harness measures what a node DOES, and
those six are not that. But "not measurable by SPIKE-001" was silently read as
"a decision somebody must assert", and for five of the six that is false. They
are measurable by a DIFFERENT INSTRUMENT, and asserting them by hand when an
instrument exists is exactly the declared-not-measured defect INV-HW-2 forbids.

  accelerator            the inference runtime ENUMERATES its own backends.
                         `llama-server --list-devices` reports the device that
                         will actually be used, which is strictly better than a
                         datasheet: it answers "what will this build run on"
                         rather than "what silicon is installed". The HTTP API
                         genuinely cannot answer it -- that part of the original
                         refusal stands -- but the binary can, and nobody asked
                         the binary.
  accelerator_memory_gb  the same line carries the device's memory budget.
  memory_architecture    unified vs discrete is a kernel fact, one sysctl away.
  security_baseline      FileVault, SIP and the firewall are queryable without
                         sudo. This file MEASURES them; it does not grade them.
                         The verdict belongs to a reviewed contract
                         (contracts/policy/admission_baseline.toml), because a
                         probe that decides its own passing grade is a node
                         raising its own ceiling, which ADR-007 D2 forbids.
  key_storage_class      determined by where VESPER's node key ACTUALLY lives,
                         found by looking. Absent is not file_based-by-default;
                         absent means there is no identity yet, and a node with
                         no key is not enrollable at all (ADR-007 D2, last row).

ONE OF THE SIX IS A REAL DECISION AND STAYS ONE. `roles` -- what the fabric is
willing to ASK of this node -- is not a property of the hardware and no
instrument will ever return it. It remains an owner assertion in
`build_node_profile.py`, which is the correct place for the one field that
genuinely is one.

AND ONE IS MEASURABLE ONLY IN PART. `availability_class` describes how reliably
the node is awake, and this host's own instrument will not answer it honestly --
see `measure_availability`. A refusal with the instrument's defect named is the
output, not a plausible-looking fraction.

NO WRITE PATH, like `profile_node.py` and `build_node_profile.py`. It prints.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The runtime's device enumeration, as printed by llama.cpp. `MTL0`, `CUDA0`,
# `ROCm0`, `Vulkan0` are the backend's own device prefixes; mapping them to the
# schema's enum here keeps the product name (which the same line carries) out
# of everything downstream -- INV-HW-1. The NAME is recorded as evidence in the
# raw capture and never propagates into a profile field.
BACKEND_PREFIX = {"MTL": "metal", "CUDA": "cuda", "ROCm": "rocm",
                  "Vulkan": "vulkan", "SYCL": "vulkan", "CANN": "npu"}

# Devices that are not accelerators. BLAS is a CPU math library and llama.cpp
# lists it alongside real devices; counting it as an accelerator would report
# `accelerator` on a machine that has none.
NOT_ACCELERATORS = ("BLAS", "CPU", "RPC")

# Processes permitted to listen on a non-loopback interface. Deliberately an
# ALLOWLIST rather than a count: "two listeners" passes forever while the two
# change underneath it. Each entry is a decision somebody made once, visible in
# a diff. `rapportd` is the platform's own continuity service and is present on
# a stock install; it is listed because it is expected, not because it is
# required -- removing it from here should turn the check red, not be tidied
# away.
EXPECTED_LISTENERS = {"rapportd"}


def _run(cmd: list, timeout: float = 20.0) -> tuple[int, str, str]:
    """Run a command, never raise. A missing instrument is a finding."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s: {' '.join(cmd)}"
    except OSError as e:                       # permissions, exec format, ...
        return 126, "", f"{type(e).__name__}: {e}"


def measure_accelerator(runtime_dir: Path) -> dict:
    """Ask the inference runtime which devices it will use.

    `--list-devices` is the honest instrument for three reasons. It is the
    BUILD's own answer, so a CPU-only build on an accelerated machine reports
    no accelerator -- which is the true answer to "what will this run on". It
    reports memory as the backend sees it. And it needs no model loaded, so it
    costs nothing and cannot be confused with a throughput measurement.
    """
    out: dict = {"instrument": "llama-server --list-devices"}
    server = runtime_dir / "llama.cpp" / "llama-server"
    if not server.exists():
        out["refused"] = (f"no runtime at {server}. The backend a node will "
                          "use is a property of the BUILD, so a profile "
                          "written without one is a guess about a binary that "
                          "is not there.")
        return out

    rc, so, se = _run([str(server), "--list-devices"])
    text = so + se
    out["raw"] = text.strip()[:2000]
    if rc != 0 and not text.strip():
        out["refused"] = f"--list-devices exited {rc}: {se.strip()[:200]}"
        return out

    # "  MTL0: Apple M1 Pro (12124 MiB, 12123 MiB free)"
    devices = []
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z]+)(\d*):\s*(.+?)\s*(?:\((\d+)\s*MiB"
                     r"(?:,\s*(\d+)\s*MiB free)?\))?\s*$", line)
        if not m or m.group(1) in ("Available", "load", "version", "built"):
            continue
        prefix, name, total_mib = m.group(1), m.group(3), m.group(4)
        if prefix in NOT_ACCELERATORS:
            devices.append({"prefix": prefix, "class": None,
                            "name_evidence": name,
                            "total_mib": int(total_mib) if total_mib else None,
                            "counted": False,
                            "why": "CPU-side math library, not an accelerator"})
            continue
        cls = BACKEND_PREFIX.get(prefix)
        devices.append({"prefix": prefix, "class": cls, "name_evidence": name,
                        "total_mib": int(total_mib) if total_mib else None,
                        "counted": cls is not None,
                        "why": None if cls else f"unmapped backend prefix {prefix!r}"})
    out["devices"] = devices

    counted = [d for d in devices if d["counted"]]
    if not counted:
        # No accelerator is a legitimate measured answer, not a failure.
        out["accelerator"] = "none"
        out["accelerator_memory_gb"] = None
        out["accelerator_memory_note"] = "no accelerator device enumerated"
        return out
    if len({d["class"] for d in counted}) > 1:
        out["refused"] = ("more than one accelerator class enumerated "
                          f"({sorted({d['class'] for d in counted})}). The "
                          "schema has one field; which one serves inference "
                          "is a launch-configuration fact this probe cannot "
                          "see.")
        return out

    first = counted[0]
    out["accelerator"] = first["class"]
    if first["total_mib"] is not None:
        out["accelerator_memory_gb"] = round(first["total_mib"] / 1024.0, 2)
        out["accelerator_memory_note"] = (
            f"{first['total_mib']} MiB as the BACKEND reports it. On unified "
            "memory this is a budget carved from system RAM, not a separate "
            "pool -- so it is not additive with ram_gb and the two must never "
            "be summed. Confirmed by what actually fits, never by a datasheet.")
    else:
        out["accelerator_memory_gb"] = None
        out["accelerator_memory_note"] = "device enumerated without a memory figure"
    return out


def measure_memory_architecture() -> dict:
    """unified vs discrete, from the kernel rather than from a product name."""
    out: dict = {}
    system = platform.system()
    if system == "Darwin":
        rc, so, _ = _run(["sysctl", "-n", "hw.optional.arm64"])
        arm = rc == 0 and so.strip() == "1"
        out["instrument"] = "sysctl hw.optional.arm64"
        out["raw"] = so.strip()
        if arm:
            # On this platform an arm64 kernel implies one physical memory pool
            # shared by CPU and GPU. This is an architectural fact, not a
            # per-model one, which is why it is safe to conclude from the flag.
            out["memory_architecture"] = "unified"
            out["why"] = ("arm64 kernel: CPU and GPU address one physical "
                          "pool. SR-057 binds to this, not to a product name.")
        else:
            out["memory_architecture"] = "discrete"
            out["why"] = "non-arm64 kernel on this platform: discrete GPU memory"
        return out
    if system == "Linux":
        # Integrated-vs-discrete on Linux is not one flag, and guessing from
        # /proc would be a declaration wearing a measurement's clothes.
        out["refused"] = ("no single kernel fact separates unified from "
                          "discrete here. Read it from the accelerator's own "
                          "device enumeration at enrollment.")
        return out
    out["refused"] = f"no instrument implemented for {system}"
    return out


def measure_security_inputs() -> dict:
    """Measure the INPUTS to the baseline. The verdict is a contract's job.

    A-042.2 is the reason for the split: a node that graded its own security
    baseline would be a node raising its own ceiling, and ADR-007 D2 says
    plainly that it cannot. So this returns facts with the command that
    produced each, and `admission_baseline.toml` decides what they add up to.
    """
    out: dict = {"instruments": {}}
    system = platform.system()
    if system != "Darwin":
        out["refused"] = f"no instrument set implemented for {system}"
        return out

    rc, so, _ = _run(["fdesetup", "status"])
    out["instruments"]["disk_encryption"] = {
        "cmd": "fdesetup status", "rc": rc, "raw": so.strip(),
        "value": True if "FileVault is On" in so else
                 False if "FileVault is Off" in so else None}

    rc, so, _ = _run(["csrutil", "status"])
    out["instruments"]["kernel_integrity_protection"] = {
        "cmd": "csrutil status", "rc": rc, "raw": so.strip(),
        "value": True if "status: enabled" in so else
                 False if "status: disabled" in so else None}

    # THE FIREWALL WAS THE WRONG INSTRUMENT, and measuring it proved that.
    # The application firewall is per-application, does not filter loopback,
    # and permits signed binaries by default -- so it can be ON while a service
    # sits bound to 0.0.0.0, and OFF while nothing is exposed at all, which is
    # this host's actual state. As an admission gate it produces both false
    # passes and false failures.
    #
    # What the requirement was reaching for is answerable directly: IS ANYTHING
    # UNEXPECTED REACHABLE FROM THE NETWORK. That is one command, it stays true
    # when VESPER's fabric later serves on the LAN (the check becomes "the
    # listener set is exactly the expected set"), and it cannot be satisfied by
    # a toggle that changes nothing about what is listening.
    fw = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    rc, so, _ = _run([fw, "--getglobalstate"]) if Path(fw).exists() else (127, "", "")
    out["instruments"]["host_firewall_advisory"] = {
        "cmd": f"{fw} --getglobalstate", "rc": rc, "raw": so.strip(),
        "value": True if "State = 1" in so or "State = 2" in so else
                 False if "State = 0" in so else None,
        "advisory": ("recorded as context, NOT graded. See "
                     "no_unexpected_external_listeners.")}

    rc, so, _ = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=25)
    listeners = []
    for line in so.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        addr = parts[8]
        # Loopback-bound services are not reachable from the network. Counting
        # them would fail every host that runs anything locally, which is every
        # host that runs VESPER.
        if addr.startswith("127.0.0.1:") or addr.startswith("[::1]:"):
            continue
        listeners.append({"command": parts[0], "pid": parts[1], "addr": addr})
    unexpected = [l for l in listeners if l["command"] not in EXPECTED_LISTENERS]
    out["instruments"]["no_unexpected_external_listeners"] = {
        "cmd": "lsof -nP -iTCP -sTCP:LISTEN", "rc": rc,
        "raw": "; ".join(f"{l['command']}@{l['addr']}" for l in listeners) or "none",
        "external_listeners": listeners,
        "expected_allowlist": sorted(EXPECTED_LISTENERS),
        "unexpected": unexpected,
        "value": (rc == 0) and not unexpected}

    # Patch state is deliberately NOT queried with `softwareupdate -l`: it
    # takes a network round trip, can hang for minutes, and a probe that
    # sometimes blocks is a probe that gets skipped. The OS build is recorded
    # instead and the contract compares it against a floor.
    rc, so, _ = _run(["sw_vers", "-productVersion"])
    rc2, so2, _ = _run(["sw_vers", "-buildVersion"])
    out["instruments"]["os_version"] = {
        "cmd": "sw_vers", "rc": max(rc, rc2),
        "raw": f"{so.strip()} ({so2.strip()})",
        "value": so.strip() or None}
    return out


def measure_key_storage(runtime_dir: Path) -> dict:
    """Where does VESPER's node key actually live? Found by looking.

    ADR-007 D2's last row is the one that matters here: NO usable key storage
    means NOT ENROLLABLE. That is a different state from `file_based`, and
    collapsing the two would hand a node an identity it does not have. So the
    absence of a key is reported as absence, and the class is left unset.
    """
    out: dict = {"searched": []}
    candidates = [Path.home() / ".config" / "vesper" / "node_key",
                  Path.home() / ".config" / "vesper" / "node_key.pem",
                  runtime_dir / "node_key",
                  Path.home() / "Library" / "Application Support" / "VESPER" / "node_key"]
    found = []
    for c in candidates:
        out["searched"].append(str(c))
        if c.exists():
            found.append({"path": str(c), "mode": oct(c.stat().st_mode & 0o777)})
    out["files_found"] = found

    keychain = None
    if platform.system() == "Darwin" and shutil.which("security"):
        rc, so, se = _run(["security", "find-generic-password", "-s",
                           "ai.vesper.node_key"])
        keychain = (rc == 0)
        out["keychain_query"] = {"cmd": "security find-generic-password -s "
                                        "ai.vesper.node_key",
                                 "rc": rc, "found": keychain}
    if keychain:
        out["key_storage_class"] = "os_keychain"
        out["why"] = "node key resolves in the OS keychain"
    elif found:
        out["key_storage_class"] = "file_based"
        out["why"] = ("node key is a file protected by filesystem permissions "
                      "only. ADR-007 D2: ceiling Z2 -- may render and observe, "
                      "may not hold state, issue commands or receive secrets.")
    else:
        out["key_storage_class"] = None
        out["not_enrollable"] = True
        out["why"] = ("NO NODE KEY EXISTS ON THIS HOST. ADR-007 D2 last row: a "
                      "node that cannot keep a secret cannot have an identity, "
                      "so it is not enrollable -- which is not the same as "
                      "being enrolled at Z2, and must not be recorded as it.")
    return out


def measure_availability() -> dict:
    """How reliably is this node awake? Refused, with the instrument's defect.

    THE PLATFORM'S OWN LOG WILL NOT ANSWER THIS HONESTLY, and the way it fails
    is worth recording because the number it yields looks entirely reasonable.
    `pmset -g log` prints each power state with a trailing duration -- but it
    prints one for nearly every Sleep and for almost no Wake. Summing what is
    printed therefore divides a near-complete numerator by a near-empty
    denominator and reports a machine that is asleep ~95% of the time. Deriving
    the same fraction from timestamp GAPS instead gives ~0.2% asleep, because
    consecutive Sleep/DarkWake pairs collapse. Two methods, the same log, two
    orders of magnitude apart: neither is a measurement.

    What the field actually asks -- can a peer reach this node when it needs to
    -- is answered by SAMPLING reachability over days, which is what
    `expected_availability` is for. Until that sampler has run, the honest
    output is the raw counts and a refusal.
    """
    out: dict = {"instrument": "pmset -g log"}
    if platform.system() != "Darwin":
        out["refused"] = "no instrument implemented for this platform"
        return out
    rc, so, _ = _run(["pmset", "-g", "log"], timeout=60)
    if rc != 0:
        out["refused"] = f"pmset exited {rc}"
        return out

    pat = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) [+-]\d{4}\s+"
                     r"(Sleep|Wake|DarkWake)\s+(.*)$")
    counts = {"Sleep": 0, "Wake": 0, "DarkWake": 0}
    with_duration = {"Sleep": 0, "Wake": 0, "DarkWake": 0}
    first = last = None
    for line in so.splitlines():
        m = pat.match(line)
        if not m:
            continue
        counts[m.group(2)] += 1
        if re.search(r"(\d+)\s+secs\s*$", m.group(3)):
            with_duration[m.group(2)] += 1
        first = first or m.group(1)
        last = m.group(1)

    out["window"] = {"first_event": first, "last_event": last}
    out["events"] = counts
    out["events_carrying_a_duration"] = with_duration
    out["refused"] = (
        "expected_availability is NOT computed. pmset reports a duration for "
        f"{with_duration['Sleep']}/{counts['Sleep']} Sleep events but only "
        f"{with_duration['Wake']}/{counts['Wake']} Wake events, so any "
        "fraction summed from it is biased by the instrument rather than by "
        "the machine. Sample reachability over days instead.")
    out["availability_class_candidates"] = ["on_demand", "foreground_only"]
    out["why_candidates"] = (
        "a host that sleeps whenever its lid closes and wakes on demand is not "
        "always_on under any reading. Which of the two it is depends on how "
        "the owner uses it, and that is an assertion, not a reading.")
    return out


def main(argv: list) -> int:
    p = argparse.ArgumentParser(
        description="Measure the profile fields SPIKE-001 cannot. Prints; never writes.")
    p.add_argument("--runtime-dir", type=Path,
                   default=Path.home() / "VESPER-runtime",
                   help="where the inference runtime lives (outside the repo)")
    p.add_argument("--node-id", default=platform.node())
    a = p.parse_args(argv[1:])

    report = {
        "schema_version": 1,
        "probe": "host-facts",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "node_id": a.node_id,
        "os_family": platform.system(),
        "runtime_dir": str(a.runtime_dir),
        "accelerator": measure_accelerator(a.runtime_dir),
        "memory": measure_memory_architecture(),
        "security": measure_security_inputs(),
        "key_storage": measure_key_storage(a.runtime_dir),
        "availability": measure_availability(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
