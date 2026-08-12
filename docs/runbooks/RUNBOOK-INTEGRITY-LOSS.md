# RUNBOOK — Class C integrity loss

**RUNBOOK-ID:** RB-LOSS-001 · **Severity:** critical · **Owner:** Project Owner
**Required by** `INV-LOSS-2` · Referenced by `A-050.4`, `A-050.6` · Sources: REM-016, ADR-002 D2/D8

> `INV-LOSS-2` says a class C loss surfaces **as an incident, immediately, with no affect template, bypassing aggregation and the interruption budget**. It did not say what happens next. This runbook is what happens next.

---

## What you will see

VESPER will say something flat. Not *"sorry, I seem to have lost that"* — that is class A, and it is warm on purpose. A class C notification has **no charm in it at all**, and the absence is the signal:

> *"Integrity incident. The audit chain broke between 02:14 and 02:51. Nineteen records are unaccounted for. I have stopped autonomous actuation."*

**If it sounds apologetic, it is not class C.** The affect boundary is mechanical — `CI-048` fails any build in which an affect template is reachable from a class C path — so the tone difference is a reliable diagnostic, not a stylistic choice.

## What class C means

| Class | Contents | Treatment |
|---|---|---|
| A | ideas, backlog, caches, learned artifacts | ordinary forgetting; may be reported warmly |
| B | checkpoints, proposals, alarms, memory | plainly reported; the affected task goes `BLOCKED`, never `SUCCEEDED` |
| **C** | **governed surfaces, trigger registry, interlock configuration, audit log, tombstones** | **incident** |

Classification is a **deterministic property of the store the record lived in** (`DF-LOSS-CLASS`, `INV-LOSS-6`). No model participates. That is why the five stores in ADR-002 D2 are physically separate: a single-file design would make this a judgement call.

---

## Immediate actions

**1. Do not restart VESPER.** A restart replays the log and may overwrite the evidence of what happened. The system has already stopped autonomous actuation itself.

**2. Trigger the emergency stop** if it has not already engaged — `RUNBOOK-EMERGENCY-STOP.md`. Withhold the enable token. Autonomy halts within `T_token_ttl` without any cooperation from the runtime, which matters because you do not yet know whether the runtime is trustworthy.

**3. Preserve, do not repair.** Copy the affected store **and its neighbours** — `audit.db`, `tombstones.db`, and `log.db` at minimum — to offline media before touching anything. A repair attempt destroys the only record of the failure mode.

**4. Note the wall-clock time and what you were doing.** VESPER's own account of the window is one input; it is not the only one you should have.

---

## Deciding what happened

Three causes produce a class C loss, and they need different responses. Work through them in this order — **cheapest to rule out first, and least alarming last.**

### Hardware or filesystem failure

**Look for:** SMART errors, filesystem errors in the OS log, a store that fails to open at all, losses clustered in time rather than in content, a device that recently ran out of space or lost power mid-write.

**If this is it:** replace the medium, restore from the last verified backup (ADR-002 D10), replay the log forward. Record the incident. This is the ordinary case and it is not a security event.

### A defect

**Look for:** losses correlated with a specific operation, a recent promotion, or a code path that ran for the first time. Check whether the running artifact's content hash matches the last owner-approved promotion.

**If this is it:** the artifact is the suspect. Restore the previous known-good artifact, keep the divergent one as evidence, and file the defect. Do not re-promote until the cause is understood.

### Compromise

**Look for:** an audit chain break with **no** corresponding storage error; tombstones present for records that are gone with no deletion audit; losses concentrated in `policy/`, `security/`, `autonomy/triggers/` or `safety/interlock/`; a `selfmod.attempt_blocked` sequence before the window; a node that re-attested with a degraded key storage class.

> **The specific signature to look for:** a hash-chain break with an intact filesystem. Hardware failure damages *bytes*; a deletion damages *rows*. ADR-002 D8's `prev_hash` chain exists so that difference is visible without a second system.

**If this is it, or if you cannot rule it out:**

1. Keep the stop engaged. Do not re-arm.
2. Revoke the suspected node with the owner enrollment key (ADR-007 D5). **No quorum is required**, which is deliberate: compromise during a partition is exactly when quorum is unavailable.
3. Facts sourced from that node become `CONFLICTED` — **not deleted**. Deleting them would destroy the evidence of what it wrote.
4. Re-verify every `L4`+ external action originating from that node since its last clean re-attestation. Those are the irreversible ones.
5. Compare the running artifact's hash against the last owner-approved promotion. ADR-012 D1 makes *"has the running system changed?"* a hash comparison rather than an investigation — use it.

---

## What VESPER may and may not do while this is open

| May | May not |
|---|---|
| Observe, record telemetry, checkpoint | Actuate autonomously at `L2`+ |
| Answer you interactively | Re-arm the interlock — **re-arm is a human act, always** (`INV-STOP-7`) |
| Report what it knows about the window | Repair the affected store on its own initiative |
| Continue work you explicitly ask for | Present the loss as ordinary forgetting (`INV-LOSS-3`) |

A task whose class B record could not be reconstructed stays `BLOCKED`. It never becomes `SUCCEEDED`. **Forgetting is permitted; pretending the work happened is not** (`INV-LOSS-4`).

---

## Recovery

1. Establish the cause, or record explicitly that it could not be established. *"Cause unknown"* is an acceptable finding; *"probably the disk"* is not.
2. Restore from the last backup whose integrity chain verifies end to end.
3. Replay `log.db` forward from that point.
4. Reconcile the outbox — external effects already sent are reconciled, not repeated (`INV-EXT-2`).
5. Write the incident record: window, records affected, cause or its absence, actions taken, and what remains unrecovered.
6. **Re-arm the interlock deliberately**, as a separate act, after the record is written.

## Afterwards

Two questions worth answering while it is fresh:

- **Did detection work?** If you found this before VESPER told you, `DF-LOSS-CLASS` or the tombstone index has a gap. That is a higher-priority defect than whatever caused the loss.
- **Was the boundary respected?** Check that no class C notification carried an affect template, and that no class A loss was escalated into an incident. Both directions matter: an integrity loss dressed as forgetting is the failure REM-016 exists to prevent, and ordinary forgetting dressed as an incident makes the incident channel useless within a month.

## Validation status

**This runbook has never been executed.** Like `RUNBOOK-ALARM.md`, it is written and unvalidated. Validation is Phase 8 and requires a deliberately corrupted store on real hardware — the `A-019` fixture is the right vehicle. Until then, treat the step ordering as reasoned rather than proven.
