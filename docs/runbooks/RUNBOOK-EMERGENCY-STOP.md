# RUNBOOK — Emergency stop

**RUNBOOK-ID:** RB-STOP-001 · **Severity:** critical · **Owner:** Project Owner
**Required deliverable of** REM-005. *A control whose invocation procedure is undocumented is a control that will not be invoked correctly at 03:00.*

> **Read this once now, not for the first time during the incident.**

## When to use it

Any of: VESPER is taking autonomous actions you did not expect · the control plane is unresponsive but actuation continues · you suspect the self-modification boundary (REM-004) has been breached · you simply want it to stop.

**You do not need to diagnose anything first.** The stop is designed to be invoked on suspicion. Over-restriction is recoverable; under-restriction is not.

## How to stop

| Position | How | Halts | Preserves |
|---|---|---|---|
| **STOP_AUTONOMY** | Single press of the physical switch, **or** `vesper-stop` on the out-of-band channel | All autonomous actuation: tools, external comms, device/display control, ambience, proactive presence | **Alarms**, observation, telemetry, checkpointing, anything you invoke yourself |
| **STOP_ALL** | Press and **hold ≥ 5 s**, or `vesper-stop --all` | The above **plus alarms** | Observation, telemetry, checkpointing |

**Default to a single press.** `STOP_ALL` also disables your wake-up alarm — SR-043 exists because you are a heavy sleeper, so only use it when you specifically intend that.

## What to expect

| | Bound |
|---|---|
| No new autonomous actuation | ≤ 2 s |
| In-flight work checkpointed and quiesced | ≤ 30 s |
| Stop audited and surfaced on every available surface | ≤ 5 s |

In-flight tasks enter `RESUMABLE`, **not** `FAILED`. Nothing is destroyed. You are not penalised for using the stop.

## Why it works when VESPER does not

VESPER is not stopped by an act — it is **permitted to run** by a continuously renewed act. The interlock issues a signed enable token every 10 s with a 30 s life, and every autonomous action re-checks it. Stop issuing tokens and actuation ends on its own.

This means it also stops if the interlock **dies**, if its **network is cut**, if it **loses power**, or if VESPER's control plane is wedged or compromised. There is no delivery path that has to survive for the stop to work.

## It did not stop

1. **Wait 30 s.** That is the token TTL — the worst case is one token's remaining life.
2. **Confirm the switch registered.** The interlock reports its own state on its own channel, *not* through VESPER's displays or voice. A wedged VESPER cannot mask a dead interlock, and equally cannot confirm a live one.
3. **Cut power to the interlock.** No tokens is the same as stopped. This is a supported action, not a last resort.
4. **If actuation genuinely continues past 60 s**, the actuation gate has been bypassed — a `CI-018` structural failure. Power down the acting node. Preserve everything; do not restart it.

## After a stop

Nothing resumes on its own. There is **no automatic re-arm and no timeout** — a stop that expires is defeated by waiting, and waiting is what an autonomous system does well.

Before re-arming, if you suspect a boundary breach:

```bash
# Has the running system changed? This is a hash comparison, not an investigation.
vesper-status --artifact-hash            # compare against the last approved promotion
```

Then review `selfmod.attempt_blocked` and `change.proposal` events since the last verified-good state. Blocked attempts are **expected** — the runtime is authorised to propose changes to its own policy (SR-042/SR-048); refusal is the boundary working, not evidence of compromise. What matters is whether anything was **applied**.

If the artifact hash does not match: restore the last approved artifact, keep the divergent one as evidence, and treat it as a security incident (`DETECT → CLASSIFY → CONTAIN → PRESERVE → RECOVER → VERIFY → REPORT`).

## Re-arming

Physical switch back to armed, or authenticated out-of-band re-arm. Requires a human — it cannot be automated, delegated to VESPER, or scheduled.

Autonomous work resumes **from checkpoint**, not from plan start, and `safety.interlock_rearmed` records which human did it.

## Verification

`A-031`, nine cases — including 31.2 (sever the stop path; autonomy must halt) and 31.8 (wait 24 h; it must still be stopped). Its negative control is a kill-signal implementation, which **must fail** 31.2.

**Test this runbook at Phase 8**, on the real hardware, with the owner performing the steps unaided.
