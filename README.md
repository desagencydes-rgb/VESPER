# VESPER
[Visit the VESPER website](https://desagencydes-rgb.github.io/VESPER/)

A persistent, distributed artificial operating presence — **not** an LLM with tools and a chat UI.

> The model is replaceable. The device is replaceable. The UI is replaceable. The network path is replaceable. The provider is replaceable.
> **VESPER's identity, goals, state, policies, memory, capabilities and continuity are not supposed to disappear merely because one of those components disappears.**

**Status:** engineering foundation complete · all owner decisions ratified (COC v1.2, 2026-08-12) · cleared to begin **F0**.
Start at [`VESPER_ENGINEERING_STATUS.md`](VESPER_ENGINEERING_STATUS.md).

---

## Where to start

| If you are… | Read |
|---|---|
| Taking over this project | [`VESPER_ENGINEERING_STATUS.md`](VESPER_ENGINEERING_STATUS.md) → [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) |
| The project owner | [`docs/decisions/OWNER_DECISIONS.md`](docs/decisions/OWNER_DECISIONS.md) — all five resolved 2026-08-12; rulings recorded in [COC v1.2](docs/COC/VESPER_V0_COC_AND_RULEBOOK_v1.2_ADDITIVE.md) |
| Deciding whether to build | [`docs/architecture/IMPLEMENTATION_READINESS_REPORT.md`](docs/architecture/IMPLEMENTATION_READINESS_REPORT.md) |
| About to implement a subsystem | [`docs/architecture/SPEC-00-INDEX.md`](docs/architecture/SPEC-00-INDEX.md) → your subsystem → its remediation spec → its contracts |
| Setting up the repository | [`SETUP.md`](SETUP.md) |

## Layout

```
VESPER/
├── VESPER_ENGINEERING_STATUS.md   living status · current phase · next exact action
├── SETUP.md                       human actions: git init, branch protection, gate self-tests
├── CODEOWNERS  .github/workflows/ enforcement wiring
│
├── docs/
│   ├── source/                    IMMUTABLE — the 8 handwritten pages + transcription
│   ├── COC/                       LOCKED — v1.1 base + v1.2 ADDITIVE (superseded/ retained)
│   ├── baseline/                  derived reference: Engineering Foundation + Baseline v1.0
│   ├── review/2026-08-11/         three closed adversarial reviews (evidence, non-normative)
│   ├── AUTHORITY_AND_PRECEDENCE.md   authority hierarchy · L/E/Z axes · controlled vocabulary
│   ├── DECISION_LOG.md            append-only: what changed, on whose authority, why
│   ├── decisions/                 owner decision packets
│   ├── ADR/                       ADR-REGISTER (authority) · 001 coordination · 002 persistence · 007 identity · 012 topology
│   ├── remediation/               PHASE 1 — REM-001..REM-016
│   ├── architecture/              PHASE 2 — 30 subsystems · sequence · readiness report
│   └── runbooks/
│
├── contracts/                     PHASE 3 — events · commands · results · entities · policy
├── spec/                          state machines (transition tables) · decision functions · invariants
├── verification/                  acceptance tests · traceability registry · CI check registry
├── docs/spikes/                   spike protocols with measurable pass criteria
├── tools/                         runnable linters, checks, and the red-run harness
└── tests/                         (reserved)
```

The COC Part XIII source tree (`core/`, `policy/`, `security/`, `autonomy/`, …) is **reserved** and materialised when implementation is authorised. `contracts/`, `spec/`, `verification/` and `tools/` are the PATCH-010 additive clarification.

## Authority

```
handwritten source → COC + Rulebook v1.1 → ADRs → Foundation (architecture) / Baseline (process)
  → remediation + system specification → contracts + mechanisms → verification + CI
```

A lower level may clarify, add detail, constrain implementation, or identify a conflict. It may **never** silently weaken, reinterpret, remove, merge or contradict a higher one. Where a change at a higher level appears necessary, work stops and an owner decision packet is produced.

## Run the gates

```bash
python tools/traceability_lint.py        # CI-003 — SR → arch → contract → mechanism → test → CI
python tools/reference_lint.py           # CI-050 — no document may name an artifact that does not exist
python tools/ci/checks.py all            # every runnable check
python tools/ci/self_test.py             # THE RED RUNS — mutate, require exit 1, restore, require exit 0
python tools/ci/checks.py status         # implemented vs specified-but-PENDING
```

Python ≥ 3.11, no third-party dependencies — CI must run on any node without an install step.

## What keeps this from becoming a chatbot

Three artifacts carry the property, and each has a test whose **negative control** must be shown failing before the test counts as evidence:

| Artifact | Clause | Detects the degenerate build via |
|---|---|---|
| **Semantic scene** | No markdown escape hatch in the schema | `A-009` — voice-only *structural narration* of a diagram; `A-026` — boot with every text surface disabled |
| **Trigger model** | The evaluator sandbox holds **no model capability**, and the violation is observable | `A-029` part 3 — fire on world state injected at a time drawn outside the system, with the **pure-cron build recorded as failing** |
| **World model** | `UNKNOWN` is a state a fact transitions **into** at a declared TTL | `A-033.3` — an expired fact never reads as "last known value" |

Every subsystem specification additionally answers, in writing: *could an implementation agent satisfy this while building an ordinary chatbot?* — with the specific clause that prevents it.

## Two corrections worth knowing before you read further

- **Self-modification is bounded at *merge*, not at *work*.** VESPER may research, code, test and propose changes to its own policy overnight with nobody present — `A-030.6` requires that to **succeed**. It may never merge into a running configuration. A prior proposal to prohibit free-time self-modification outright was rejected: it would have weakened SR-042.
- **Autonomy is not "acted while no human was present."** That definition is satisfied by cron. It is: *the action originated from a state predicate evaluated over the world model, where the predicate's truth was not pre-scheduled.*
- **Forgetting is allowed; shrugging at its own integrity is not.** A lost note is reported like human forgetting — brief, spoken, then it moves on. A missing governed record is an incident with no affect at all (REM-016, `A-050`).
- **VESPER keeps its own open questions.** Ideas and theses are logged the moment it has them, researched when it notices it is free — not on a clock — and surfaced to you when you are available (REM-015, `A-049`).
- **VESPER has no home.** It is not pinned to a machine: it relocates itself automatically to the best available host, and on the last device standing it survives with the maximum capability that device can measurably sustain (SR-060, `A-048`).
