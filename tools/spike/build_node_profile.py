#!/usr/bin/env python3
"""Build a NodeCapabilityProfile from SPIKE-001 reports. Stdlib only.

`contracts/entities/node_capability_profile.schema.json` was written 2026-08-20
and has never been instantiated. This is why, and the reason is worth stating
rather than working around:

  MOST OF A NODE CAPABILITY PROFILE IS NOT MEASURABLE BY A THROUGHPUT HARNESS.

`SPIKE-001` measures what a node DOES -- cores, memory, storage, tokens per
second. The schema also asks what a node may be TRUSTED with and how reliably
it is AWAKE, and those are not properties a THROUGHPUT HARNESS can report. A
tool that inferred Z0 from a fast benchmark would be admitting a node on the
strength of its speed, which is exactly the mistake A-042.2 is written about.

CORRECTED 2026-08-24: THE HARNESS IS NOT THE ONLY INSTRUMENT. This file
originally required six fields as hand-typed assertions, on the reasoning above.
The reasoning is sound and the conclusion was wrong for four of them: "SPIKE-001
cannot see it" is a fact about SPIKE-001, not about the field. The runtime's own
device enumeration reports the accelerator and its memory budget; one sysctl
reports the memory architecture; three platform queries report the security
posture. `tools/spike/probe_host_facts.py` is that instrument, and asserting
those four by hand while it exists is the declared-not-measured defect INV-HW-2
refuses. Four assertions became measurements, and one -- `trust_zone` -- became
a DERIVATION, because ADR-007 D2 says the zone follows from key storage and the
security baseline "by rule, not declared" and no rule had ever been written
down. It is now `contracts/policy/admission_baseline.toml`.

TWO REMAIN ASSERTIONS AND SHOULD. `availability_class` describes how the owner
USES the machine, and `roles` is what the fabric is willing to ASK of it.
Neither is a property of the hardware. There is still no `--yes` and no default:
a default trust zone would look conservative and still be a decision nobody
made -- the same defect as defaulting a cost class, which `A-021.7` refuses.

AND IT HAS NO WRITE PATH. It prints. Promotion into the fabric is a separate
reviewed act, for the same reason `profile_node.py` cannot write to
`capability_profiles.toml`: the act of deciding a node is trusted should be
visible in a diff somebody approved, not a side effect of running a script.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
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


# Fields no instrument answers, with the reason each is genuinely a decision.
#
# THIS SET WAS SIX AND IS NOW TWO, and the correction is worth stating because
# the original reasoning was persuasive and wrong. Four of the six were called
# decisions on the grounds that SPIKE-001 cannot measure them. That is true and
# it does not follow: "the throughput harness cannot see it" is a fact about
# the harness, not about the field. A DIFFERENT instrument -- the runtime's own
# device enumeration, one sysctl, and three platform security queries -- answers
# all four, and `tools/spike/probe_host_facts.py` is that instrument.
#
# Asserting a field by hand while an instrument for it exists is the
# declared-not-measured defect INV-HW-2 forbids. The refusal was right to block
# a default; it was wrong about which fields had to be typed by a human.
ASSERTED = {
    "availability_class": "SR-058. How reliably the node is awake is an "
                          "operational fact about how it is USED. The probe "
                          "narrows it to a candidate set and refuses to pick: "
                          "the platform's own power log reports durations for "
                          "nearly every sleep and almost no wake, so a fraction "
                          "summed from it measures the instrument.",
    "roles": "what the fabric is willing to ASK of this node. A capability "
             "measurement says what it could do, not what it is for. No "
             "instrument will ever return this one.",
}

# Fields DERIVED from the host-facts probe rather than asserted or measured by
# SPIKE-001. Named here so `--help` and the refusal message stay honest about
# where each value comes from.
FROM_PROBE = ("accelerator", "accelerator_memory_gb", "memory_architecture",
              "security_baseline", "trust_zone")


def _grade_baseline(probe: dict, policy: dict) -> tuple[str, dict]:
    """Apply admission_baseline.toml to the probe's facts. Fail-closed.

    The probe measures and this applies the contract, because a probe that
    graded itself would be a node raising its own ceiling (ADR-007 D2).
    """
    instruments = ((probe.get("security") or {}).get("instruments") or {})
    reqs = (policy.get("requirement") or {})
    detail: dict = {}
    held = failed = 0
    for name, spec in reqs.items():
        if not spec.get("required"):
            continue
        got = instruments.get(name, {})
        value = got.get("value")
        # UNKNOWN IS NOT A PASS. A null means the instrument returned nothing,
        # and admitting on that is how a broken probe becomes a trusted node.
        ok = value is True or (name == "os_supported" and bool(value))
        if name == "os_supported":
            ok = bool(instruments.get("os_version", {}).get("value"))
            got = instruments.get("os_version", {})
        detail[name] = {"held": ok, "raw": got.get("raw"),
                        "instrument": got.get("cmd")}
        held += ok
        failed += not ok
    if failed == 0 and held > 0:
        return "meets", detail
    if held > 0:
        return "partial", detail
    return "fails", detail


def derive_from_host_facts(probe: dict, policy: dict) -> tuple[dict, dict]:
    """Return (derived_fields, provenance) for what the probe measured.

    `trust_zone` is DERIVED, never asserted: ADR-007 D2 says the zone follows
    from key storage and the security baseline "by rule, not declared", and
    this is that rule --

        zone = MIN( ceiling(key_storage_class), cap(security_baseline) )

    Two independent bounds and the lower wins, because they answer different
    questions: can this node keep a secret, and is the platform holding that
    secret intact.
    """
    derived: dict = {}
    prov: dict = {}
    acc = probe.get("accelerator") or {}
    if "accelerator" in acc:
        derived["accelerator"] = acc["accelerator"]
        prov["accelerator"] = acc.get("instrument", "probe_host_facts")
        if acc.get("accelerator_memory_gb") is not None:
            derived["accelerator_memory_gb"] = acc["accelerator_memory_gb"]
            prov["accelerator_memory_gb"] = acc.get("accelerator_memory_note", "")

    mem = probe.get("memory") or {}
    if mem.get("memory_architecture"):
        derived["memory_architecture"] = mem["memory_architecture"]
        prov["memory_architecture"] = mem.get("instrument", "probe_host_facts")

    baseline, detail = _grade_baseline(probe, policy)
    derived["security_baseline"] = baseline
    failing = sorted(k for k, v in detail.items() if not v["held"])
    prov["security_baseline"] = (
        f"admission_baseline.toml over probe facts; failing: "
        f"{failing or 'none'}")

    ceilings = policy.get("zone_ceiling_by_key_storage") or {}
    caps = policy.get("zone_cap_by_baseline") or {}
    ks = (probe.get("key_storage") or {}).get("key_storage_class")
    ceiling = ceilings.get(ks or "none", "NOT_ENROLLABLE")
    if isinstance(ceiling, dict):                # the [.notes] subtable
        ceiling = "NOT_ENROLLABLE"
    cap = caps.get(baseline, "Z2")
    if ceiling == "NOT_ENROLLABLE":
        prov["trust_zone"] = (
            f"NOT DERIVED. key_storage_class={ks!r} -> {ceiling}. "
            "ADR-007 D2 last row: a node that cannot keep a secret cannot "
            "have an identity. This is not Z2 and must not be recorded as it.")
    else:
        # The MORE RESTRICTIVE of the two bounds wins. Trust runs Z0 > Z1 > Z2,
        # so more-restrictive is the larger Z-number and therefore the string
        # max -- written out because `max` reads like "the better one" here and
        # it is the opposite.
        zone = max(ceiling, cap)
        derived["trust_zone"] = zone
        prov["trust_zone"] = (
            f"DERIVED by admission_baseline.toml: min(ceiling({ks})={ceiling}, "
            f"cap({baseline})={cap}) = {zone}")
    return derived, prov


def main(argv: list) -> int:
    p = argparse.ArgumentParser(
        description="Derive a NodeCapabilityProfile. Prints; never writes.")
    p.add_argument("--results-dir", required=True, type=Path)
    p.add_argument("--node-id", required=True)
    p.add_argument("--host-facts", type=Path, required=True,
                   help="JSON from tools/spike/probe_host_facts.py. Required: "
                        "four profile fields are MEASURED by it, and typing "
                        "them by hand while an instrument exists is the "
                        "declared-not-measured defect INV-HW-2 refuses.")
    p.add_argument("--baseline-policy", type=Path,
                   default=REPO / "contracts" / "policy" / "admission_baseline.toml")
    for field in ASSERTED:
        p.add_argument(f"--{field.replace('_', '-')}",
                       default=None, nargs="*" if field == "roles" else None)
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

    probe = json.loads(a.host_facts.read_text(encoding="utf-8"))
    policy = tomllib.loads(a.baseline_policy.read_text(encoding="utf-8"))
    host_derived, host_prov = derive_from_host_facts(probe, policy)
    derived.update(host_derived)
    prov.update(host_prov)

    # NOT ENROLLABLE is a refusal, not a low zone. A node with no key has no
    # identity (ADR-007 D2), and writing it into a profile at Z2 would hand it
    # one -- Z2 is an ENROLLED node with a bounded role, which is a different
    # thing from a machine the fabric has never admitted.
    if "trust_zone" not in derived:
        print(f"REFUSED: {prov.get('trust_zone')}\n", file=sys.stderr)
        print("Give this host a node key first. Until then no profile is "
              "correct, because every value one could carry would claim an "
              "identity it does not have.", file=sys.stderr)
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

    # `derived` already carries accelerator, accelerator_memory_gb,
    # memory_architecture, security_baseline and trust_zone -- measured by the
    # probe and graded by the contract. Only the two genuine assertions are
    # applied here.
    profile = {"node_id": a.node_id, "schema_version": 1, **derived}
    profile["availability_class"] = a.availability_class
    profile["roles"] = list(a.roles)
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
