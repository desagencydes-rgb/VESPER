# VESPER system blueprint — source map and accuracy record

Snapshot: **2026-09-11**, repository commit **7cddca1**. The working tree was clean before artifact creation. This is a source-grounded architecture plate, not a certification of the currently running deployment. No providers were called, no credentials were read, and no hardware was enrolled to make it.

The existing graphify graph was queried initially as a locator. The owner confirmed it is old and incomplete. **It is not an authority for any final claim.** Current code, build wiring, contracts and dated measurements underpin the poster. README and historical status sections contain superseded descriptions; those were not copied as current status.

## Status vocabulary

- **CURRENT**: implemented in the inspected source. This does not mean every adapter is granted OS access, every provider is reachable, or every acceptance case has passed on real hardware.
- **EXPERIMENTAL**: measurements or hardware validation remain in progress. A completed individual measurement can appear within a running spike.
- **PLANNED / OPEN**: specified, proposed or not yet established. No invented completion dates.
- The conceptual ambition is continuity of an operating presence across replaceable components. The figure makes no consciousness claim and no comparative claim against fictional assistants.

## Identity and the official icon

Primary asset: `docs/design/assets/vesper-icon.png`, **1024 × 1024 RGB**. `app/island-macos/build.sh:107` copies it to the application resources and the following iconset step uses the same file to make the app icon. `docs/design/DESIGN-FOUNDATION.md:281` identifies the mark and its primary island placement.

`docs/design/source/refs/icon.png` is a lower-resolution 520 × 520 reference. It was not substituted. The poster embeds the primary image without redrawing, cropping, retouching, recoloring or upscaling. It occupies 242 points, giving **1024 × 72 / 242 = 304.66 PPI**. The surrounding ellipses and star marks are independently authored vector ornament. They are explicitly labeled as metaphor, not measured trajectories or mathematical algorithms.

The palette draws on the actual asset and design foundation: warm ivory, gold, muted rose and violet over a near-black ground. Georgia and Liberation Sans are used as available embedded typefaces; the poster does not pretend to contain the unpurchased Canela/Aeonik fonts named in the design specification.

## Internal project map

### 1. Purpose, runtime and continuity

`README.md` describes persistence of identity, goals, state, policy, memory and capabilities despite replacement of models, devices, interfaces or network paths. Its implementation status is historical; the thesis is consistent with current modules.

`tools/ops/vesper_runtime.py:663` constructs the live graph of runtime components. Its `pump()` dispatches input, routes action requests through the actor, and falls back to `answer()` for conversational responses. `core/supervisor.py`, `core/tasks.py`, `core/lease.py` and `core/store.py` implement supervision, durable task state, lease ownership and storage. `app/island-macos/build.sh` packages Python code and policy with the Swift application, while `app/home-macos/RuntimeHost.swift` provides the host-side process boundary. The current host is a concrete deployment; it is not the definition of where VESPER must live.

### 2. The central information/action diagram

The diagram is a deliberate condensation of the main turn, not a generic perception–LLM–tools diagram:

1. Intake receives text or final speech with confidence gating (`core/intake.py`; runtime `pump()`).
2. `actor.maybe_act()` is offered an actionable utterance with recent context. `IntentProposer.propose()` returns a known capability with arguments, completion or no action (`core/intent.py`, `core/actor.py:437`).
3. If no action is proposed, `answer()` is used (`tools/ops/vesper_runtime.py:1479`; `pump()` around line 2430). The chooser selects difficulty, the router selects a profile, and **then** L1 and current context are rendered. This order was checked against the function body.
4. The assembled request goes to `ModelGateway.complete()` with the selected profile. Gateway logic enforces the decision-path ban, privacy routing, redaction and cost/supply rules. The response is returned and the utterance is captured asynchronously; miss recording is also asynchronous.
5. For an action, `_one_step()` resolves permission, then the executor reauthorizes immediately before acting. Checkpoints protect file mutations and the external-action outbox precedes effects (`core/executor.py:232`).
6. `_verify()` uses `INDEPENDENT_VERIFIERS` where available; it reports an absent verifier rather than inventing verification (`core/actor.py:1201`). Observations feed the bounded next-step loop.
7. Outcomes reach transcript and presentation/speech paths. `core/longform.py` separates concise spoken replies from longer explanation blocks.

The actor's default bounds are **MAX_STEPS = 6**, **MAX_CONSECUTIVE_REFUSALS = 3** (`core/actor.py:77`). The poster does not claim these are global budgets for every kind of background work. A model used by the intent proposer also crosses the gateway; the drawing's separate conversational gateway box is not a bypass for action proposals.

### 3. Memory, knowledge and context

`core/memory.py:181` writes to the append-only log before projecting a fact into L2. Each projected row carries the actual returned sequence pointer. L2 uses SQLite tables `entity`, `fact`, `edge` and the `fact_fts` FTS5 index. `select()` uses full-text matching and bounded recursive graph traversal; `MAX_DEPTH = 3`, `TOP_N = 5` (`core/memory.py:83`). Ranking follows authority and recency.

Authority ranks (`core/memory.py:75`) are system rule, source of record, current observation, user statement and derived fact. Model prior is named as rank 6 but is not admissible as a stored fact. The small poster rank line uses `>` to mean preference, not numeric greater-than.

`core/blocks.py:131` renders L1: block A is stable persona/rules plus an index; block B is fresh selected evidence near the question. `core/context.py` provides token budgets, priority, pinning, reported dropping and UNKNOWN propagation. Recent dialogue, capability statements and live mode state are composed in the runtime's answer path. `core/persona.py` reads persona/voice rules; this is personality construction, not evidence of an inner conscious entity.

`core/updater.py` captures utterances; `core/extract.py` derives structured facts through a permitted model path. `core/arbiter.py` handles conflicts separately from capture. `core/forgetter.py` separates expiry, explicit erasure and judgment pruning. `core/compactor.py` reprojects from L3 rather than recursively summarizing its own prior summary. Deletion from L2 does **not** erase the L3 log; tombstones matter during reprojection.

`core/knowledge_map.py` maps directories, files, symbols, sections and other locators with source hashes. Retrieval returns exact source spans; map summaries are navigation metadata, not citable evidence. An incomplete map's miss is UNKNOWN, not proof of absence. This runtime knowledge map must not be confused with the old developer graphify output.

`core/cache.py` implements file-hash, chunk, summary and prompt-prefix bookkeeping with taint preservation. Its embedding tier is explicitly **not built**. The current memory retrieval path has no vector database, no embedding step and no cosine-similarity formula. None was invented for the poster.

### 4. Models, providers and agents

`core/difficulty.py`, `core/chooser.py` and `core/router.py` separate request difficulty, escalation of ambiguous classifications and measured profile selection. The interactive answer path explicitly prefers latency at both router and gateway. A throughput figure is not interchangeable with time to first visible output or complete-answer latency.

`routing/http_completion.py` implements provider transport; `routing/supply.py` loads configured supply. `contracts/policy/provider_supply.toml` includes Cloudflare, Groq, Gemini, Ollama and Mistral routes, other text suppliers, and separate purposes for memory work, speech, transcription and agents. This inventory is **configuration**, not a live-availability claim. `core/quota.py`, `core/cost.py`, `core/latency.py` and `core/rung_credentials.py` support quota, cost, latency observation and credential-specific supply expansion.

`contracts/policy/subagents.toml` declares nine specialized roles: advisor, investigator, implementer, tester, researcher, navigator, auditor, drafter and briefer. `core/agents.py` dispatches bounded agents and returns explicit UNAVAILABLE outcomes. Most roster roles are read-only; the tester has a restricted gate-command allowlist. `core/advisor.py` is one-directional: STOP can add a question, PROCEED cannot grant authority. The poster's educational definition of an agent summarizes these boundaries rather than advertising an unrestricted autonomous swarm.

### 5. Authorization, privacy and recovery

The poster's equation is transcribed from the **current five-input expression**, not the older three-input module docstring: `core/authorize.py:318` computes the minimum of grant maximum, argument-declared level, context ceiling, mode ceiling and authorization-strength ceiling. Its symbols E, G, D, C, M and A are all defined on the plate. Additional checks include expiry, target scope, lease epoch, required level, prohibition and confirmation/self-modification boundaries. The minimum alone is not sufficient authorization.

`core/permission_mode.py` implements the owner's ASK / WORKSPACE / AUTO choices. Its historical comments and the current `_elevate_in_auto()` logic should not be flattened into an assertion that every L4/L5 action always produces a new dialog. The poster says **ask when required** and makes no stronger claim. `core/consent.py` parses answers deterministically; `core/confirm.py` parks questions and resumes work.

`core/taint.py` preserves content trust through summaries and caches. Source content may not raise authority. Privacy and trust are separate axes: privacy asks whether content may leave; trust limits what it can authorize. The gateway's `MAY_CARRY` table and redaction precede text-provider calls (`core/gateway.py:778`). `core/redact.py` detects credentials deterministically; it does not send potential secrets to a model to ask whether they are secrets.

Credential tooling supports Keychain storage with an existing file fallback (`tools/ops/vesper_keychain.py`; `routing/supply.py`). No claim is made that all deployment credentials have been migrated. `core/checkpoint.py` uses shadow Git to preserve pre-change state. `core/background.py` tracks work that outlives a turn and its stoppable process groups. `core/selfmod.py` permits proposal work while refusing runtime writes to governed surfaces and self-merge into the running configuration.

### 6. World model, autonomy and alarms

`core/sensors.py` polls registered sensors; `core/host_probes.py` reads host power, health and related machine facts. `core/world.py` enforces expiration to UNKNOWN and ordered updates. `core/hlc.py` defines lexicographic ordering on physical milliseconds, a logical counter and node ID. These are ordering semantics, not a claim that wall time is unused for deadlines.

`core/autonomy.py` evaluates terminating state predicates. `core/decision_path.py` and the gateway enforce the prohibition on model calls in the decision path. Runtime registration includes expiry, self-directed triggers, drift, contradictions, map staleness and due agenda work. The diagram's handler is the post-decision boundary, not a model inside a predicate.

`core/agenda.py`, `AgendaBridge.swift` and `NotesBridge.swift` provide owner-day input from calendar/reminder and Notes surfaces, subject to their actual permissions. The runtime agenda handler has a deterministic notification sentence and optional model phrasing; an unavailable model does not have to silence the notification.

`core/interlock.py` requires a fresh external enable token for autonomous actuation. `core/interruption.py` budgets interruptions. Alarms are an explicit special path: `core/alarm.py` requires an actuable, acknowledgeable rung, and historical alarm evidence lives in `MEMORY.md` and spike results. The poster does not claim the historical alarm is currently armed or that a complete multi-device ladder has been validated.

### 7. Input, voice, application control and presence

`app/island-macos/Listener.swift` implements on-device recognition where available; `WakeWord.swift` implements local wake listening with consent checks; `FnTrigger.swift` handles physical activation. `core/transcribe.py` routes Darija audio to permitted suppliers, with no fictitious on-device Darija fallback. `core/speech.py` treats external synthesis as egress and supports local synthesis fallback; `core/arabizi.py` handles speech-boundary script conversion. `core/floor.py` and `core/barge_in.py` distinguish stop, cooperative backchannel, status request and queued work. Build-dependent OS grants remain an operational constraint.

`core/capabilities.py` binds file read/write/edit, shell, agent, app, window and UI capabilities. `core/apps.py` and `core/windows.py` define target-sensitive policy. Current Swift bridges include `AppsBridge.swift`, `WindowBridge.swift` and `UIBridge.swift`. In `UIBridge.swift`, an element path is corroborated against role and label before acting; reading a tree and clicking an old index are not treated as equivalent. Its recorded 2026-09-11 scope is the **showing Desktop**. `SpacesHatch.swift` contains newer cross-Space mechanisms, so older documents claiming no relocation adapter were not used as current status.

`core/presence.py` currently accepts owner declarations. `docs/design/VISION-IDENTITY.md` is a camera-identity design with open implementation questions. It is labeled PLANNED. RF sensing, delegated calling and volumetric output are not advertised as current perception abilities.

### 8. Presentation, storage and the fabric

The build compiles Swift/AppKit, Metal and WebKit source directly. It is not a shipped Tauri or React app simply because historical design discussions mention those possibilities. `app/home-macos/chrome/home.html` contains the web chrome. `core/scene.py` defines semantic scenes; `core/projection.py`, `core/home_state.py` and `core/workbench.py` feed surfaces. The presence artwork is an interface, not the reasoning engine itself.

`core/store.py` separates five physical SQLite stores: append-only log, audit and tombstones; mutable state and workspace. L2 is an additional derived graph database, not one of those five record-loss classes.

`core/placement.py:634` and `survival_profile()` implement placement/survival decision logic. `core/fabric.py` uses the weaker trust zone of node and segment; `contracts/policy/network_fabric.toml` still declares **attested = false**. Therefore the poster distinguishes implemented decision machinery from an established roaming deployment. It does not assume that available computers constitute admitted full hosts.

## Numbers, dates and development state

| Poster detail | Source / scope |
|---|---|
| 6 steps; 3 consecutive refusals | `core/actor.py:77`, default turn-loop bounds |
| L2 depth 3; up to 5 facts | `core/memory.py:83`, with token budgeting in `core/blocks.py` |
| 45.8 tokens/s | `MEMORY.md` §1: node-1 Qwen3-8B Q4_K_M, llama.cpp b10405-e79e4bf66, Vulkan, median of three 10-minute runs, 2026-08-17. Historical sustained throughput, not a new benchmark or end-to-end voice latency |
| 24 August first routed call | `MEMORY.md` §4h; real router/profile/gateway call recorded with build identity |
| 30 August L2 committed | Git history: `a6c45b9`, `3b315d0`; engineering status memory integration record |
| 31 August voice and act path joined | Git history: `bcddda6`, `740bbcf` |
| 1–11 September agency/host control | Git history from bounded multi-step actions through current app/UI control commits, including `7cddca1` |
| 104/122 check IDs implemented, 18 pending | Executed `tools/ci/checks.py status` on 2026-09-11 with Python 3.13-compatible bundled runtime. This is registry status, explicitly not a fresh full gate run |
| A2 size | 420 × 594 mm, computed using 72 points/inch and 25.4 mm/inch |
| Official icon ~305 PPI | Native 1024 px / (242 pt / 72), no synthetic resolution increase |

`docs/spikes/INDEX.toml` is the spike-status authority. Inspected state:

- RUNNING: SPIKE-001 node profiles; 004 pseudo-volumetric output; 008 persistence validation; 013 home-composite cost; 015 small-tier model selection.
- NOT_STARTED: SPIKE-002 voice latency chain; 003 OS access envelope; 005 delegated calling; 006 RF sensing; 007 foreground-only survival; 009 cross-site connectivity; 010 remote wake; 011 service dormancy; 012 residency manager; 014 system widgets.

Existing software in one area does not automatically close the corresponding hardware spike. The poster's future strip selects the open questions most central to this architecture; it does not invent a promised schedule.

## Print production and verification

- Master: `VESPER_SYSTEM_BLUEPRINT_MASTER.pdf`, one A2 portrait page.
- Preview: `VESPER_SYSTEM_BLUEPRINT_PREVIEW.png`, rendered from the final PDF at 300 DPI.
- Real embedded-font text; vector rules, diagrams, orbits and geometry.
- One unaltered raster asset: the official icon, embedded losslessly.
- Critical copy is inside the frame; no information depends on bleeding to the page edge.
- Primary explanatory copy is approximately 9.6–10.4 points at final A2 size; smaller source locators are secondary.
- Reproducible authoring source: `build_poster.py`. `layout_audit.json` records paragraph rectangles; final production checks are in `QA_REPORT.json`.
- The final PDF was rendered and visually inspected, including detail crops. A character-spacing state leak was corrected during QA, margins were moved inward, and the central call order was rechecked against the runtime.

Print at **actual size / 100%** on A2. The file is an RGB vector master with a lossless RGB icon; a press-specific ICC conversion or PDF/X derivative would require the print shop's production specification. No unrequested printer profile was guessed.
