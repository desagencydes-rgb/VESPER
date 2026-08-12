# SPIKE-003 — Kernel and OS access envelope per platform

| | |
|---|---|
| **Status** | NOT_STARTED · **Time box** 5 working days · **Owner** Platform Engineer · Security Engineer |
| **Question** | What kernel/OS-level access is actually available per platform, at what privilege, under what entitlement, with what user consent? |
| **Blocks** | SR-026 disposition · `A-043` kernel half |
| **Requires hardware** | No — entitlement and API research, validated by a minimal probe per platform |

## 1. Why this is open

SR-026 asks VESPER to *read kernel-level information*. `REM-012` split it: the **telemetry half** is core and buildable now; the **kernel-access half** carries a COC Part XIV.3 limitation record. SR-026's registry status is `PARTIAL_R_AND_D` and `tools/traceability_lint.py` prevents it being set to `IMPLEMENTED` while either half is open.

The prior review raised a question that must be answered first and is not a technical one:

> **What is "read kernel" actually for?** Deep resource telemetry (SR-011) and security/intrusion monitoring (SR-038) have very different feasible implementations, and the answer determines whether a supported non-privileged path exists at all.

Start there. A supported API that delivers the *purpose* is a better outcome than a privileged hack that delivers the *literal words*.

## 2. Protocol

For each of macOS, Windows, Android, iOS, and for each capability below, record: **available (yes/no) · required privilege · required entitlement or signing requirement · consent surface shown to the user · whether a supported non-privileged path delivers the same information · stability across OS versions**.

| Capability | Consumer |
|---|---|
| Per-process CPU/memory attribution | SR-011 resource governor |
| GPU/NPU utilisation and memory | SR-011, model routing |
| Thermal state and throttling signals | SR-005, SPIKE-001 |
| Disk and network I/O per process | SR-011 |
| Open network connections and listening ports | SR-038 |
| Process creation and termination events | SR-038 |
| Filesystem change notification | SR-038, `trg_map_stale` |
| Kernel extension / driver loading | SR-038 |
| Power and battery state | REM-014 placement |

Validate each *available* cell with a minimal probe that actually reads the value. **A documentation citation is not a measurement** — entitlements are frequently documented and unobtainable in practice.

## 3. Pass criteria

1. The matrix is complete — every cell filled for all four platforms, with no cell left blank.
2. Every `available = yes` cell is backed by a working probe.
3. For every `available = no` cell, the **non-privileged alternative** column is filled in or explicitly marked as none.
4. The purpose question (§1) is answered by the owner or the Security Engineer, and recorded.

## 4. On fail

SR-026 stays `PARTIAL_R_AND_D`. The telemetry half ships and is verified by `A-043`; the kernel half keeps its limitation record and R&D path.

**Not permitted:** marking SR-026 `IMPLEMENTED` because the telemetry half works; requesting a privilege escalation that the platform's consent model does not support in order to satisfy the literal wording; or shipping a privileged helper without the security review that `AUTHORITY_AND_PRECEDENCE §5` reserves to the owner.

## 5. Deliverables

1. The per-platform feasibility matrix.
2. Probe code and its output per available cell.
3. A recommendation per capability: supported path, privileged path with named risk, or limitation record.
4. Updated limitation record text for `SR-026`.
