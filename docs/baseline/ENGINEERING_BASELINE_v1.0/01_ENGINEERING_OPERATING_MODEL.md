# VESPER V0 — Engineering Operating Model
Version 1.0

## 1. Lifecycle
SOURCE → SPEC → DESIGN → TASKS → IMPLEMENT → VERIFY → REVIEW → INTEGRATE → ACCEPT → RELEASE → OBSERVE

## 2. Work item types
ADR, RFC, Feature Spec, Spike, Bug, Hardening, Runbook, Benchmark, Acceptance Test.

## 3. Definition of Ready
Objective, non-goals, source IDs, affected interfaces, dependencies, permissions/security impact, measurable acceptance criteria, test strategy, rollback/containment, owner.

## 4. Definition of Done
Implementation complete; tests pass; acceptance criteria pass; telemetry exists; degraded/error behavior exists; contracts/docs updated; security review completed where required; diff reviewed; rollback known; no source requirement weakened.

## 5. Repository control
main = releasable. Feature/fix/spike/research branches use isolated worktrees or equivalent. No direct pushes to main.

## 6. PR gates
Every PR declares source IDs, ADR IDs, interfaces changed, tests, security impact, resource impact, migration impact, rollback and limitations.

## 7. Agent handoff
Every handoff includes objective, files changed, decisions, assumptions, tests, evidence, failures, risks, unresolved questions and next action. Code alone is not a handoff.

## 8. Agent isolation
Concurrent agents use separate branches/worktrees/workspaces. Shared mutable state requires an explicit coordination contract.

## 9. Authority
Agents may implement within granted scope. They may not change immutable source requirements, silently change security policy, change public contracts without an ADR, grant themselves permissions, or conceal failures.

## 10. Verification
High-risk changes use separation of duties: implementer → verifier → owner acceptance.

## 11. Research vs production
Research is disposable and reproducible. Production requires provenance, tests, security/license review, resource profile and rollback.

## 12. CI
Formatting/lint, type/static checks, unit, integration, contract, security/dependency checks, build/package validation. Later add hardware-in-loop, multimodal regression, performance and fault injection.

## 13. Observability
Structured events cover lifecycle, health, latency, resource pressure, model/provider choice, tool execution, authorization, state transitions, checkpoints and recovery.

## 14. Failure policy
Prefer retry → alternate path → degraded capability → checkpoint → queue → explicit failure over fabricated success.

## 15. Release
DEV → INTERNAL → HARDWARE-INTEGRATED → V0-ALPHA → V0-BETA → V0-STABLE.

## 16. Change control
Only an approved COC baseline change may alter an SR. ADRs and implementation documents may evolve without changing SR meaning.
