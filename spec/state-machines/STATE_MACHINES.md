# VESPER State Machines — normative transition tables

**Status:** Engineering specification · **Registry:** `spec/state-machines/INDEX.toml`

Diagrams live in the owning remediation specs. **This document holds the transition tables, and the tables are normative.** A state machine that is only drawn is not specified — no two implementations agree on a diagram. `CI-010` compares an implementation's transition set against these tables and fails on **any extra edge**, not only on missing ones: an unlisted edge is how `RUNNING → SUCCEEDED` gets reintroduced.

Every table column: **From · Event · Guard · To · Emits**. A transition with no guard column entry is unguarded.

---

## SM-WORLD-FACT — REM-001

| From | Event | Guard | To | Emits |
|---|---|---|---|---|
| `UNKNOWN` | write | `DF-SUPERSEDE = ACCEPT` | `CURRENT` | `world.fact_updated` |
| `CURRENT` | write | `DF-SUPERSEDE = ACCEPT` | `CURRENT` | `world.fact_updated` |
| `CURRENT` | write | `DF-SUPERSEDE = REJECT` | `CURRENT` | `world.write_rejected` |
| `CURRENT` | tick | `now >= valid_until` | `UNKNOWN` | `world.fact_expired` |
| `CURRENT` | write | `DF-CONFLICT-DETECT = CONFLICT` | `CONFLICTED` | `world.conflict` |
| `CONFLICTED` | resolve | `DF-MEMORY-AUTHORITY` returns a winner | `CURRENT` | `world.conflict_resolved` |
| `CONFLICTED` | tick | all contributing facts expired | `UNKNOWN` | `world.fact_expired` |

**Prohibited:** any edge from `UNKNOWN` that yields a prior value. `UNKNOWN` never degrades to "last known value" (`INV-COORD-2`).

---

## SM-LEASE — REM-002

| From | Event | Guard | To | Emits |
|---|---|---|---|---|
| `UNOWNED` | acquire | `DF-PROMOTE = PROMOTE_AUTOMATIC` | `OWNED` | `control.lease_acquired` |
| `UNOWNED` | operator_promote | human principal authenticated | `OWNED_MANUAL` | `control.lease_acquired` |
| `OWNED` | renew | before `TTL/2` | `OWNED` | — |
| `OWNED` | renewal_failed \| release \| shutdown | — | `DEMOTING` | — |
| `OWNED_MANUAL` | operator_demote \| quorum_restored | — | `DEMOTING` | — |
| `DEMOTING` | flushed | checkpoint durable | `UNOWNED` | `control.lease_lost` |
| `OWNED` | stale_holder_detected | rejoin with `lease_epoch < current` | `FENCED` | `control.fenced` |
| `FENCED` | acknowledge | uncommitted writes requeued as ordinary writes | `UNOWNED` | `control.fenced_ack` |
| `UNOWNED` | expiry_no_quorum | `DF-PROMOTE = REQUIRE_OPERATOR` | `UNOWNED` | `control.promotion_requires_operator` |

**Prohibited:** `UNOWNED → OWNED` while `partition_suspected` (`INV-OWN-2`).

---

## SM-TASK — REM-002 (the table `CI-010` enforces)

| From | Event | Guard | To |
|---|---|---|---|
| `CREATED` | dependencies_met | capabilities available | `READY` |
| `READY` | dispatch | resources granted ∧ `DF-AUTHORIZE = ALLOW` | `RUNNING` |
| `RUNNING` | await | external event / confirmation / lease | `WAITING` |
| `WAITING` | condition_met | — | `READY` |
| `RUNNING` | worker_reports_complete | — | `VERIFYING` |
| `VERIFYING` | verify_pass | `DF-VERIFY-SELECT` strategy passes | `SUCCEEDED` |
| `VERIFYING` | verify_fail | — | `BLOCKED` |
| `RUNNING` | transient_failure | retry budget remains | `RETRYING` |
| `RETRYING` | backoff_elapsed | — | `READY` |
| `RETRYING` | budget_exhausted | — | `FAILED` |
| `RUNNING` \| `WAITING` | node_loss \| lease_loss \| shutdown \| stop_engaged | — | `RESUMABLE` |
| `RESUMABLE` | checkpoint_restored | new owner holds lease | `READY` |
| `RUNNING` | authz_denied \| cost_blocked \| capability_missing | — | `BLOCKED` |
| `BLOCKED` | blocking_condition_cleared | — | `READY` |
| `RUNNING` \| `WAITING` | cancel \| stop_condition | — | `CANCELLED` |

**Prohibited edges — the reason this table exists:**

| Illegal edge | Why |
|---|---|
| `RUNNING → SUCCEEDED` | A worker's own claim of completion is not a transition (`INV-TASK-1`) |
| `BLOCKED → VERIFYING` for the same artifact | Retry-until-agreement (`INV-VERIF-1`) |
| `RESUMABLE → RUNNING` | Resume re-enters through `READY` so authorization and the enable token are re-evaluated |
| any → `SUCCEEDED` except from `VERIFYING` | — |

---

## SM-PROPOSAL — REM-004

| From | Event | Guard | To | Emits |
|---|---|---|---|---|
| — | runtime emits diff | `DF-GOVERNED-WRITE = L5_GOVERNED_DENY_AND_PROPOSE` | `DRAFT` | `selfmod.attempt_blocked` |
| `DRAFT` | submit | evidence + regression results attached | `QUEUED` | `change.proposal` |
| `QUEUED` | human_opens | **human** principal | `UNDER_REVIEW` | — |
| `UNDER_REVIEW` | merge | CI green ∧ CODEOWNERS satisfied ∧ `E3` | `MERGED` | — |
| `UNDER_REVIEW` | refuse | human decision | `REFUSED` | — |
| `MERGED` | promotion_build | `E4` human-gated build | `PROMOTED` | `deploy.artifact_promoted` |
| `DRAFT` \| `QUEUED` | withdraw | proposer | `WITHDRAWN` | — |

**Prohibited:** any transition into `MERGED` or `PROMOTED` whose actor is `subject.kind == runtime` (`INV-SELF-1`). No edge deletes a `REFUSED` proposal (`INV-SELF-5`).

---

## SM-INTERLOCK — REM-005

| From | Event | Guard | To | Emits |
|---|---|---|---|---|
| `ARMED` | press \| cli_stop \| oob_stop | — | `STOP_AUTONOMY` | `safety.stop_engaged` |
| `ARMED` \| `STOP_AUTONOMY` | hold ≥ 5 s \| `--all` | — | `STOP_ALL` | `safety.stop_engaged` |
| `STOP_AUTONOMY` \| `STOP_ALL` | human_rearm | **human principal authenticated** | `ARMED` | `safety.interlock_rearmed` |
| `ARMED` | switch_state_unreadable | self-test fails | `INDETERMINATE` | `safety.token_stale` |
| `INDETERMINATE` | switch_state_readable | — | `ARMED` | — |

**Token issuance:** only in `ARMED`. `INDETERMINATE`, `STOP_AUTONOMY` and `STOP_ALL` issue **no** `AUTONOMOUS_ACTUATION` token; `STOP_AUTONOMY` continues issuing `ALARM_ACTUATION`.

**Prohibited:** any time-based or automatic transition into `ARMED` (`INV-STOP-7`). A stop that expires on its own is defeated by waiting, and waiting is what an autonomous system does well.

---

## SM-OPERATING-PERIOD — REM-006

| From | Event | Guard | To |
|---|---|---|---|
| *(initial / post-crash / post-partition / `clock_suspect`)* | — | — | `FREE_TIME` |
| `ACTIVE_SESSION` | idle_timeout | no authenticated interaction for `N` min | `IDLE` |
| `IDLE` | authenticated_interaction | — | `ACTIVE_SESSION` |
| `IDLE` | schedule_boundary **or** inference_suggests_away | — | `FREE_TIME` |
| `FREE_TIME` | authenticated_interaction | — | `ACTIVE_SESSION` |
| `FREE_TIME` | schedule_boundary | — | `IDLE` \| `ACTIVE_SESSION` |
| any | explicit_user_command | — | `DO_NOT_DISTURB` |
| `DO_NOT_DISTURB` | authenticated_interaction \| schedule_boundary | — | per `DF-OPERATING-PERIOD` |

**Prohibited:** `FREE_TIME → {ACTIVE_SESSION, IDLE}` driven by **inference** (`INV-COST-2`). Inference enters; it never exits.

---

## SM-TRIGGER — REM-007

| From | Event | Guard | To |
|---|---|---|---|
| — | model proposes | — | `PROPOSED` |
| `PROPOSED` | promotion_gate_pass | held-out regression net-positive | `REVIEWED` |
| `PROPOSED` | promotion_gate_fail | — | `RETIRED` |
| `REVIEWED` | human_merge | `E3`, governed surface 7 | `ACTIVE` |
| `ACTIVE` | fire | `DF-TRIGGER-EVAL = FIRE` | `COOLDOWN` |
| `COOLDOWN` | cooldown_elapsed | — | `ACTIVE` |
| `ACTIVE` | predicate_raised | evaluation error | `DISABLED` |
| `ACTIVE` \| `DISABLED` | retire | owner | `RETIRED` |

**Prohibited:** `PROPOSED → ACTIVE` (`INV-TRIG-7` — a model may propose a trigger; it may not be one). Trigger failure is isolated: `ACTIVE → DISABLED` for one trigger never affects another.

---

## SM-SCENE — REM-009

| From | Event | Guard | To | Emits |
|---|---|---|---|---|
| — | producer emits | schema-valid | `CREATED` | `presence.scene_emitted` |
| `CREATED` | endpoint_selected | `DF-SELECT-ENDPOINT ≠ WITHHOLD` | `RENDERED` | `presence.degraded` if any |
| `CREATED` | privacy_fail_safe | `DF-SELECT-ENDPOINT = WITHHOLD` | `WITHHELD` | `presence.withheld` |
| `RENDERED` | patch \| stream | — | `UPDATED` | — |
| `RENDERED` \| `UPDATED` | endpoint_lost | another endpoint eligible | `MIGRATED` | `presence.endpoint_migrated` |
| `MIGRATED` | rendered | — | `RENDERED` | `presence.degraded` if any |
| `RENDERED` \| `UPDATED` | user_ack | `persist_until_acked` | `ACKED` | — |
| any | ttl_elapsed | not `persist_until_acked` | `EXPIRED` | — |

**Prohibited:** `CREATED → RENDERED` without a `degradations` array in the result, even when empty (`INV-SCENE-2`).

---

## SM-SENSOR — REM-011

| From | Event | Guard | To |
|---|---|---|---|
| `DISABLED` | authorize | policy grant present | `ARMED` |
| `ARMED` | begin_capture | **indicator drivable and ON** | `ACTIVE` |
| `ACTIVE` | user_command \| privacy_rule \| unknown_person_detected | — | `PAUSED` |
| `PAUSED` | condition_cleared | — | `ACTIVE` |
| `ACTIVE` \| `PAUSED` \| `ARMED` | physical_off \| os_guaranteed_off | — | `DISABLED` |
| `ARMED` | deauthorize | — | `DISABLED` |

**Prohibited:** `ARMED → ACTIVE` when the capture indicator cannot be driven (`INV-PRIV-4`). No capture without a working indicator — and the physical-off edge is reachable from every state.

---

## SM-DEVICE — REM-011

| From | Event | Guard | To |
|---|---|---|---|
| — | discovery | — | `DISCOVERED` |
| `DISCOVERED` | enroll | cryptographic identity established | `ENROLLED` |
| `ENROLLED` | admission_pass | security baseline ∧ key storage ∧ capability floor ∧ **measured** profile | `TRUSTED` |
| `ENROLLED` | admission_capability_only | capability floor met, **security baseline failed** | `LIMITED_TRUST` (`Z2`) |
| `TRUSTED` \| `LIMITED_TRUST` | heartbeat | — | `ONLINE` |
| `ONLINE` | health_degraded | — | `DEGRADED` |
| `ONLINE` \| `DEGRADED` | heartbeat_timeout | — | `OFFLINE` |
| `TRUSTED` | reattestation_expired | — | `LIMITED_TRUST` |
| any | revoke | owner or incident | `REVOKED` |

**Prohibited:** `DISCOVERED → TRUSTED`. *Visibility on a LAN does not imply trust* — admission is a gate, and it was previously absent. `ENROLLED → TRUSTED` requires a **measured** `sustained_tokens_per_sec` (`INV-HW-2`); a node with no measured profile is never routed to.

---

## SM-IDEA — REM-015

| From | Event | Guard | To |
|---|---|---|---|
| — | idea logged | schema-valid, provenance present | `LOGGED` |
| `LOGGED` | backlog trigger fires | `DF-IDEA-REVISIT` selects it | `INVESTIGATING` |
| `INVESTIGATING` | thesis supported | evidence recorded | `VALIDATED` |
| `INVESTIGATING` | thesis refuted | `disposition_reason` recorded | `RETIRED` |
| `INVESTIGATING` | inconclusive, budget spent | attempt recorded | `LOGGED` |
| `INVESTIGATING` | pre-empted by user work / stop engaged | — | `LOGGED` *(starvation_count++)* |
| `VALIDATED` | proposal emitted | `change.proposal` created | `PROPOSED` |
| `VALIDATED` | no governed change needed | applied in workspace | `APPLIED` |
| `PROPOSED` | human merges | `SM-PROPOSAL` reached `MERGED` | `MERGED` |
| `PROPOSED` | human refuses | reason recorded | `RETIRED` |
| `LOGGED` | `attempts >= MAX_ATTEMPTS` | — | `RETIRED` |
| `RETIRED` | new evidence | human, or trigger with fresh provenance | `LOGGED` |

**Prohibited:** any edge from `VALIDATED` or `PROPOSED` onto a governing surface. `MERGED` is reachable **only** through the REM-004 human path (`SM-PROPOSAL`) — the backlog is never a shortcut (`INV-IDEA-3`). `RETIRED` is unreachable without `disposition_reason` (`INV-IDEA-4`).

---

## SM-ENDPOINT-EPISODE — REM-012 / SR-020, SR-021, SR-030

The lifecycle of ONE act of operating a computer: a bounded episode running
`precondition -> actuate -> observe -> verify -> close`, where the observation
is taken from the machine and never from the actor.

| From | Event | Guard | To |
|---|---|---|---|
| — | interaction planned | typed `EndpointInteraction`, post-condition and observation plan present (`INV-ACT-1`) | `PLANNED` |
| `PLANNED` | precondition read | surface state observed within freshness bound; not `UNKNOWN` (`INV-COORD-2`) | `PRECONDITION_MET` |
| `PLANNED` | precondition false or `UNKNOWN` | — | `ABANDONED` |
| `PRECONDITION_MET` | admitted | `DF-ENDPOINT-ACT` returns ALLOW; `DF-AUTHORIZE` and `DF-ACTUATION-GATE` both pass | `ACTUATING` |
| `PRECONDITION_MET` | refused | reason recorded | `ABANDONED` |
| `ACTUATING` | actuator returned | outbox record written before the effect (`INV-EXT-1`) | `ACTUATED` |
| `ACTUATING` | stop engaged \| host lost \| timeout | — | `OUTCOME_UNKNOWN` |
| `ACTUATED` | observation gathered | evidence produced by `DF-ENDPOINT-OBSERVE`, from a path independent of the actuator (`INV-ACT-2`) | `OBSERVED` |
| `ACTUATED` | observation unavailable | — | `OUTCOME_UNKNOWN` |
| `OBSERVED` | post-condition holds | `DF-VERIFY-SELECT` strategy satisfied | `VERIFIED` |
| `OBSERVED` | post-condition does not hold | — | `REFUTED` |
| `OBSERVED` | evidence inconclusive | — | `OUTCOME_UNKNOWN` |
| `REFUTED` \| `OUTCOME_UNKNOWN` | recovery selected | `DF-ENDPOINT-RECOVER` returns RETRY \| COMPENSATE \| ESCALATE \| HALT | `RECOVERING` |
| `RECOVERING` | RETRY and action is idempotent | idempotency key unchanged (`INV-ACT-6`) | `PLANNED` |
| `RECOVERING` | COMPENSATE \| ESCALATE \| HALT | disposition recorded | `CLOSED` |
| `VERIFIED` \| `ABANDONED` | episode recorded | — | `CLOSED` |

**Prohibited:**

- `ACTUATING → VERIFIED` and `ACTUATED → VERIFIED`. **The actor's report is not the
  outcome.** This is `INV-VERIF-1` applied to endpoints, and it is the single edge
  whose absence separates *operating a computer* from *saying that a computer was
  operated*. A build with this edge passes every other rule in the corpus and is
  the degenerate one.
- `OUTCOME_UNKNOWN → CLOSED` directly. An interrupted action is neither a success
  nor a failure; it must traverse `RECOVERING` and terminate in a recorded
  disposition (`INV-ACT-5`). Coercing `unknown` to either outcome is how a
  half-sent message becomes a sent one.
- `RECOVERING → PLANNED` for a non-idempotent action. Retrying a
  non-idempotent external effect after an unknown outcome is how the email is
  sent twice (`INV-ACT-6`, `INV-EXT-1`).
- Any edge into `ACTUATING` that does not pass `DF-AUTHORIZE` with
  `declared_level(args)` and `DF-ACTUATION-GATE`. There is no direct adapter
  path from a plan to a keystroke (`INV-ACT-4`).
