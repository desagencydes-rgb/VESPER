# VESPER V0 — Tool & Model Assignment / Benchmark Plan
Version 1.0

## 1. Principle
Do not permanently assign a model because it is fashionable. Assign by measured task fitness.

## 2. Verified tool capabilities (2026-08-10)
Claude Code: explicit model selection, plan permission mode, resumable sessions, JSON output and MCP.
Kiro: Specs, Steering, Hooks, MCP, CLI and autonomous/spec-driven workflows.
Antigravity: agent-first execution, asynchronous agents, browser capabilities, artifacts and multi-agent orchestration.
Cursor: Agent/Ask/Manual/Custom modes and Background Agents.
These are capability observations, not architectural dependencies.

## 3. Initial model tiers
Tier A: strongest available reasoning model from at least two independent families for architecture, hard debugging, threat modeling and ADR critique.
Tier B: strongest reliable coding model for primary implementation.
Tier C: fast smaller model for mechanical changes, tests, documentation and simple routing.
Tier D: local/offline models selected only after hardware benchmarks.

## 4. Benchmark suite
B01 repository comprehension.
B02 contract implementation.
B03 surgical refactor.
B04 distributed debugging.
B05 security boundary.
B06 failure recovery.
B07 context engineering.
B08 multimodal reasoning.
B09 test generation.
B10 architecture critique.

## 5. Scoring
Correctness 25%; regression safety 15%; requirement fidelity 15%; test quality 15%; security 10%; resource efficiency 10%; maintainability 5%; handoff quality 5%.

## 6. Routing
task class → risk → modality → context → latency → hardware → cost policy → reliability.

## 7. Recommended initial use
Kiro for formal spec-to-task workflows.
Claude Code for deep repo implementation and debugging.
Antigravity for parallel asynchronous work and browser/end-to-end tasks.
Cursor for interactive development and controlled background experiments.
VS Code for human integration.

## 8. External verification
Run the same benchmark suite across at least two model families. Claude can be an adversarial reviewer, but must not be the sole authority.

## 9. Versioning
Record model ID, provider, tool version, date, hardware and benchmark results. Model updates trigger revalidation.
