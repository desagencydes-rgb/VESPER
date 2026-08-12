# VESPER V0 — Implementation Roadmap & Release Gates
Version 1.0

## Phase 0 — Engineering Foundation
Repository, CI, branch protection, docs/ADR structure, configuration, secrets, logging, test harness, source registry, task templates.
Exit: clean build, CI green, source IDs usable in tasks, no credentials in repo.

## Phase 1 — Persistent Core
Supervisor, durable state, event bus, task state machine, configuration, telemetry and recovery.
Exit: task survives restart; event replay and degraded states work.

## Phase 2 — Model/Provider Fabric
Provider contract, local adapter, API adapter, router, quota/error state, fallback, performance telemetry, context budget.
Exit: provider failure switches path; retry state visible; local fallback works.

## Phase 3 — Knowledge, Maps & Memory
Source registry, BAG/project map, retrieval, working/episodic/semantic/procedural memory, provenance.
Exit: large project navigable without dumping repository into context; memory survives restart.

## Phase 4 — Agent/Task Fabric
Agent runtime, bounded capabilities, planner, verifier, parallel tasks, checkpoints and handoffs.
Exit: concurrent agents operate without shared-state corruption; failed agents can be replaced.

## Phase 5 — Tool Fabric
Capability gateway, shell/filesystem/browser adapters, dry-run, authorization, audit, rollback/compensation.
Exit: unauthorized calls denied; actions auditable; failed action never reported as success.

## Phase 6 — Perception + World Model
Microphone, camera, screen, OCR, media evidence, world model and device graph.
Exit: observations have provenance/time/confidence; world updates are event-driven; stale evidence expires.

## Phase 7 — Presence
Speech, listening, semantic scene engine, desktop/phone, projector and spatial/glass adapter interfaces.
Exit: endpoint selection works; interaction migrates on failure; chat is not the only control path.

## Phase 8 — Autonomy
Event-driven triggers, background queue, free-time policy, resource budgets, stop conditions, reporting, alarms.
Exit: autonomous work stays in policy; free-time never uses paid APIs; user work is protected.

## Phase 9 — Environment
Room/space model, lighting/audio/display control, richer topology and ambience.
Exit: authorized environmental actions are reversible or fail-safe.

## Phase 10 — Advanced Research
Spatial/holographic research, experimental sensing, novel interaction and local runtime optimization.
Exit: reproducible experiment, evidence, limitations; no unvalidated capability is treated as reliable.

## Release gates
Alpha: continuity + model fabric + tasks + tools.
Beta: perception + world model + presence + autonomy integrated.
Stable: acceptance, security, fault injection, hardware-in-loop, endurance and performance targets pass.

## Critical path
Foundation → core → model fabric → knowledge/memory → agents/tasks → tools → perception/world → presence → autonomy → environment.
