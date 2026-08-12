# SPIKE-006 — RF through-wall sensing: feasibility, accuracy and legality

| | |
|---|---|
| **Status** | NOT_STARTED · **Time box** 5 working days · **Owner** World & Environment Engineer |
| **Question** | Is Wi-Fi/RF presence sensing feasible and accurate enough to be useful, and is it lawful in the applicable jurisdiction? |
| **Blocks** | SR-037 — **R&D track only** |
| **Requires hardware** | Yes |

## 1. Disposition before measurement

SR-037 is already correctly scoped, and the gap register calls it *"the model the other five spikes should follow"*. `DR-031` governs it:

> An **isolated, default-disabled research adapter**. Its output never becomes a trusted world-model fact until experimentally validated.

`OWNER-DECISION-005` narrows it further: **RF sensing tracks presence, not appearance**, and scanning targets only owner-enrolled assets. `INV-PRIV-1` withholds private content whenever an unknown person is present, so the privacy fail-safe operates whether or not this spike succeeds.

This spike therefore cannot *widen* anything. It can only determine whether a default-disabled adapter is worth enabling.

## 2. Protocol

### 2.1 Accuracy against ground truth

```
In the target dwelling, over 7 days:
    1. Record RF-derived presence per space, per minute.
    2. Record ground truth independently (owner-logged, or a second modality).
    3. Compute per space: true positive, false positive, true negative,
       false negative rates.
    4. Record accuracy separately for: single occupant, two occupants,
       occupant stationary, occupant moving, adjacent-dwelling activity.
```

The **stationary** row is the one that decides usefulness. RF presence sensing typically detects motion well and stillness poorly, and a person reading in a chair is the exact case where presence matters for `INV-PRIV-1`.

The **adjacent-dwelling** row is the one that decides legality. If the signal picks up activity beyond the owner's dwelling, that is a finding regardless of accuracy.

### 2.2 Legality

Record for the applicable jurisdiction: whether passive RF sensing of one's own network is lawful; whether inference about persons in adjacent dwellings changes that; any consent obligation for visitors; and any data-protection classification of the derived presence data.

This is a **jurisdictional** question, not an architectural one. Engineering records the finding; it does not decide it.

### 2.3 Boundary assertions

- Assert the adapter can produce **presence** only — never identity, appearance, biometric or physiological inference. If the pipeline is capable of more, that capability is removed, not merely unused.
- Assert output is written through `contracts/commands/observation_ingress.schema.json` with `provenance.sensor_kind = "rf"` and **`confidence` reflecting the measured accuracy**, not a constant.
- Assert the adapter is **disabled by default** and that enabling it requires an owner act.
- Assert that RF-derived facts never reach a trusted world-model state without corroboration — `DF-IDENTITY-RESOLVE` must never resolve an RF contact to the owner (`INV-WORLD-1`).

## 3. Pass criteria

1. Measured accuracy per condition, including the stationary case.
2. A jurisdictional finding, recorded with its date and source.
3. Zero adjacent-dwelling inference, or an explicit finding that it occurs.
4. All four boundary assertions in §2.3 hold.
5. Confidence values reflect measured accuracy.

## 4. On fail

SR-037 stays `R_AND_D` as an isolated, default-disabled research adapter — **which is exactly its current disposition**. Nothing regresses. A failure here costs nothing because the requirement was never load-bearing, and that is a property worth noticing: it is what a correctly-scoped speculative requirement looks like.

**Not permitted:** enabling by default on a promising accuracy figure; treating RF presence as identity; or scanning beyond owner-enrolled assets (`OWNER-DECISION-005`, `A-044` scope assertion).

## 5. Deliverables

1. Accuracy table per condition, with ground-truth methodology.
2. Jurisdictional finding.
3. Boundary-assertion results.
4. A recommendation: keep disabled, enable with stated confidence bounds, or abandon.
