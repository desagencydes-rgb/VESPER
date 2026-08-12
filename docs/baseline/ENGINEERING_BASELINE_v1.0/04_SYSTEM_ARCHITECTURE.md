# VESPER V0 — System Architecture Specification
Version 1.0

## 1. Architectural invariant
VESPER is a persistent distributed system. Models are replaceable workers; devices are replaceable nodes; interfaces are contracts; runtime state is the continuity substrate.

## 2. Planes
Control: identity, policy, events, tasks, orchestration, routing, resources, observability.
Intelligence: model runtimes, provider gateway, router, planner, verifier, agents, research.
Knowledge: BAG, maps, memory, source registry, indexes, artifacts.
Perception: microphones, cameras, screen capture, OCR, media and telemetry.
World: environment model, device graph, spatial topology and capability graph.
Action: tools, filesystem, shell, browser, applications, OS, communications and device control.
Presence: voice, listening, semantic scenes, projector, glass/spatial outputs, desktop/phone and ambience.
Security: identity, trust, authorization, secrets, isolation, audit, detection and recovery.

## 3. Logical runtime components
vesperd supervisor; eventd; taskd; routerd; memoryd; worldd; agentd; toold; perceptiond; presenced; deviced; securityd; telemetryd; researchd; autonomyd.

These are logical boundaries. Early deployment may co-locate components while preserving contracts.

## 4. Event model
Events are immutable facts: event_id, timestamp, source, subject, type, payload, confidence, provenance, correlation_id.
Commands are requests: command_id, actor, capability, target, args, authorization, deadline, idempotency key.
Results contain status, evidence, output, errors, side effects and timestamps.
A command is never proof that an action happened.

## 5. Task state
CREATED → READY → RUNNING → WAITING → VERIFYING → SUCCEEDED.
Recovery: RETRYING, BLOCKED, FAILED, CANCELLED, RESUMABLE.

## 6. World model
Entities: User, Space, Device, Node, Sensor, Actuator, Display, Application, NetworkLink, Capability, Model, Task, Observation, Event.
Relationships include device-in-space, observes, displays-in, hosts-model, provides-capability and connected-to.
Observations carry timestamp, source, confidence, freshness and provenance.

## 7. Memory
Working, episodic/task, semantic/project, procedural and source/artifact memory are distinct. Durable records carry provenance and retention.

## 8. Knowledge maps
The map represents project structure, requirements, interfaces, dependencies, decisions, artifacts, evidence and active tasks. Retrieval navigates the map to select only needed context.

## 9. Model gateway
Provider adapters expose one normalized contract. Router considers complexity, modality, context, latency, quality, hardware, availability and cost policy. Provider failure: classify → switch → retry → verify → report.

## 10. Tool gateway
Every tool has capability ID, schema, authorization level, dry-run/preview where possible, execution, result, rollback/compensation and audit.

## 11. Presence
Presence consumes task, urgency, user context, privacy, environment and endpoint availability, then emits a semantic presentation plan. Adapters render it. The chat box is not the system's default interface.

## 12. Autonomy
trigger → eligibility → plan → authorize → execute → verify → checkpoint → report. No-op is valid.

## 13. Security
Trusted core, controlled workers, device nodes, untrusted artifacts and external providers are distinct trust zones. Cross-zone actions require explicit capability grants.

## 14. Persistence
Critical state survives process restart, model replacement, provider loss and node transition.

## 15. Failure domains
Model, provider, node, network, tool, storage, perception and security failures have explicit detection, containment, degraded mode, recovery and evidence.

## 16. Resource governance
CPU, RAM, GPU/accelerator, unified memory/VRAM, storage, network, tokens, API cost, battery and thermal state where available.

## 17. Deployment strategy
Start as a modular monolith with strict internal contracts if that accelerates delivery. Split processes only when isolation, reliability, scaling or security justify it.

## 18. Acceptance
No subsystem is accepted without contract tests, failure tests, observability, security boundary, persistence behavior, resource profile and source traceability.
