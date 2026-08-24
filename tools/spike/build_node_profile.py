#!/usr/bin/env python3
"""Build a NodeCapabilityProfile from SPIKE-001 reports. Stdlib only.

`contracts/entities/node_capability_profile.schema.json` was written 2026-08-20
and has never been instantiated. This is why, and the reason is worth stating
rather than working around:

  MOST OF A NODE CAPABILITY PROFILE IS NOT MEASURABLE BY A THROUGHPUT HARNESS.

`SPIKE-001` measures what a node DOES -- cores, memory, storage, tokens per
second. The schema also asks what a node may be TRUSTED with and how reliably
it is AWAKE, and those are not properties the machine can report about itself.
`security_baseline` decides `trust_zone` at admission, and the schema says
plainly why: "visibility on a LAN does not imply trust; this is what does." A
tool that inferred Z0 from a fast benchmark would be admitting a node on the
strength of its speed, which is exactly the mistake A-042.2 is written about.

SO THIS TOOL REFUSES RATHER THAN DEFAULTS. Every field it cannot derive is a
required argument, and omitting one is an error naming the field and why. There
is no `--yes` and no default trust zone. Defaulting `trust_zone` to Z2 would
look conservative and would still be a decision nobody made -- the same defect
as defaulting a cost class, which `A-021.7` already refuses.

AND IT HAS NO WRITE PATH. It prints. Promotion into the fabric is a separate
reviewed act, for the same reason `profile_node.py` cannot write to
`capability_profiles.toml`: the act of deciding a node is trusted should be
visible in a diff somebody approved, not a side effect of running a script.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.schema_validate import validate  # noqa: E402

SCHEMA = REPO / "contracts" / "entities" / "node_capability_profile.schema.json"
TIERS = ("draft", "small", "standard", "strong")


def derive_from_reports(results_dir: Path) -> tuple[dict, dict]:
    """Return (derived_fields, provenance). Only what was MEASURED."""
    derived: dict = {}
    prov: dict = {}

    # System facts: taken from a 3.2 report, which samples the machine while
    # the owner's real working set is present. A `--quick` run is not used even
    # if present; a figure from a different condition is a different figure.
    sysfile = results_dir / "SPIKE-001-3.2-workingset-nomodel.json"
    if sysfile.exists():
        d = json.loads(sysfile.read_text(encoding="utf-8"))
        s = d.get("system") or {}
        if s.get("cpu_cores_logical"):
            derived["cpu_cores"] = int(s["cpu_cores_logical"])
            prov["cpu_cores"] = sysfile.name
        if s.get("ram_gb"):
            derived["ram_gb"] = float(s["ram_gb"])
            prov["ram_gb"] = sysfile.name
        if s.get("os_family"):
            derived["os_family"] = s["os_family"]
            prov["os_family"] = sysfile.name

    storefile = results_dir / "SPIKE-001-3.3-storage.json"
    if storefile.exists():
        st = (json.loads(storefile.read_text(encoding="utf-8"))
              .get("storage") or {})
        if st.get("disk_total_gb"):
            derived["storage_gb"] = float(st["disk_total_gb"])
            prov["storage_gb"] = storefile.name

    # THROUGHPUT, PER MODEL CLASS, from the CONCURRENT condition. The idle
    # figure describes a machine nobody is using. `median_effective_tokens_per_sec`
    # is the field each report's own `router_should_use` names: wall-clock, so
    # it sees contention that the generation-time number is blind to.
    rates: dict = {}
    rate_prov: list = []
    builds: set = set()
    latest = ""
    for f in sorted(results_dir.glob("SPIKE-001-3.1-v3-*-concurrent.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("schema_version", 0) < 4:
            continue
        t = d.get("throughput") or {}
        tier = t.get("tier")
        rate = t.get("median_effective_tokens_per_sec")
        if tier not in TIERS or rate is None:
            continue
        # Several models can serve one tier. The profile records what the tier
        # SUSTAINS, so the slowest is wrong and the fastest overstates a tier
        # whose other model is slower. Recorded per model instead, keyed by the
        # report, and the tier key carries the best measured of them -- with
        # every contributing report named in provenance so the choice is
        # arguable rather than hidden.
        if tier not in rates or rate > rates[tier]:
            rates[tier] = float(rate)
        rate_prov.append(f"{f.name}={rate}")
        if t.get("build_info"):
            builds.add(t["build_info"])
        latest = max(latest, d.get("generated_at_utc", ""))
    if rates:
        derived["sustained_tokens_per_sec"] = rates
        prov["sustained_tokens_per_sec"] = "; ".join(sorted(rate_prov))
    if latest:
        derived["measured_at"] = latest
        prov["measured_at"] = "latest generated_at_utc across 3.1 reports"
    if builds:
        prov["build_info"] = ", ".join(sorted(builds))
    return derived, prov


# Fields the harness cannot answer, with the reason each is a decision.
ASSERTED = {
    "accelerator": "the reports record no backend -- `gpu_in_use` is null in "
                   "every one, because the server exposes no CPU/GPU split "
                   "over HTTP. A GPU's product name is not its backend.",
    "accelerator_memory_gb": "usable VRAM is not in any report; it is read "
                             "from the driver or the datasheet and confirmed "
                             "by what actually fits.",
    "memory_architecture": "unified vs discrete is a hardware fact the "
                           "harness does not query. SR-057 binds to it.",
    "trust_zone": "decided at ADMISSION from the security baseline, never "
                  "from capability. A-042.2: a fast, capable, unpatched "
                  "machine is Z2 however much throughput it offers.",
    "availability_class": "SR-058. How reliably the node is awake is an "
                          "operational fact about how it is used, orthogonal "
                          "to trust and invisible to a ten-minute benchmark.",
    "roles": "what the fabric is willing to ASK of this node. A capability "
             "measurement says what it could do, not what it is for.",
}


def main(argv: list) -> int:
    p = argparse.ArgumentParser(
        description="Derive a NodeCapabilityProfile. Prints; never writes.")
    p.add_argument("--results-dir", required=True, type=Path)
    p.add_argument("--node-id", required=True)
    for field in ASSERTED:
        p.add_argument(f"--{field.replace('_', '-')}",
                       default=None, nargs="*" if field == "roles" else None)
    p.add_argument("--security-baseline", default=None,
                   choices=["meets", "partial", "fails"])
    p.add_argument("--survival-capable", default=None,
                   choices=["true", "false"])
    p.add_argument("--thermal-class", default=None)
    p.add_argument("--power-source", default=None)
    p.add_argument("--network-class", default=None)
    a = p.parse_args(argv[1:])

    derived, prov = derive_from_reports(a.results_dir)
    if not derived.get("sustained_tokens_per_sec"):
        print("REFUSED: no measured throughput in "
              f"{a.results_dir}. INV-HW-2 -- a profile without a measured "
              "rate is not a profile, and a node with no measured profile is "
              "never routed to (A-042.4).", file=sys.stderr)
        return 2

    missing = [(f, why) for f, why in ASSERTED.items()
               if getattr(a, f) in (None, [])]
    if missing:
        print("REFUSED: these fields cannot be derived from a measurement and "
              "were not asserted.\n", file=sys.stderr)
        for f, why in missing:
            print(f"  --{f.replace('_', '-')}\n      {why}\n", file=sys.stderr)
        print("Pass each explicitly. There is no default: a default trust "
              "zone would look conservative and still be a decision nobody "
              "made.", file=sys.stderr)
        return 2

    profile = {"node_id": a.node_id, "schema_version": 1, **derived}
    profile["accelerator"] = a.accelerator
    if a.accelerator_memory_gb is not None:
        profile["accelerator_memory_gb"] = float(a.accelerator_memory_gb)
    profile["memory_architecture"] = a.memory_architecture
    profile["trust_zone"] = a.trust_zone
    profile["availability_class"] = a.availability_class
    profile["roles"] = list(a.roles)
    if a.security_baseline:
        profile["security_baseline"] = a.security_baseline
    if a.survival_capable is not None:
        profile["survival_capable"] = a.survival_capable == "true"
    for k, v in (("thermal_class", a.thermal_class),
                 ("power_source", a.power_source),
                 ("network_class", a.network_class)):
        if v:
            profile[k] = v

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = validate(profile, schema)
    if errors:
        print(f"INVALID against {SCHEMA.name}:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(json.dumps(profile, indent=2, sort_keys=True))
    print("\n# PROVENANCE -- every derived field, and the report it came from",
          file=sys.stderr)
    for k, v in sorted(prov.items()):
        print(f"#   {k}: {v}", file=sys.stderr)
    print("#\n# ASSERTED by the operator, not measured: "
          + ", ".join(sorted(ASSERTED)), file=sys.stderr)
    print("# NOT WRITTEN. Promotion into the fabric is a separate reviewed "
          "act.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
