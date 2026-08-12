# SPEC-B — Knowledge and intelligence planes

Subsystems **06, 07, 08, 09, 10, 11**. Index: [SPEC-00](SPEC-00-INDEX.md).

---

## SPEC-06 — World model

**Purpose.** Maintain persistent, time-aware environmental state — **not** a document index. This is one of the four artifacts that separate VESPER from *LLM + memory + tools*.

| Field | Definition |
|---|---|
| **Responsibility** | Entities, spaces, devices, capabilities, relationships, observations; supersession, TTL/expiry, conflict emission; the external observation ingress |
| **Boundaries — in** | Facts about the *environment* and their freshness |
| **Boundaries — out** | Facts about *the user's history* (07 memory); retrieved *documents* (08 BAG). The distinction is load-bearing: a world fact expires, a memory record supersedes |
| **Authority** | `world` leased domain. Writes require the lease; `Z2` observers may write **observations** through the ingress but hold no lease |
| **State owned** | `WorldFact` per `(subject, attribute)`; `Space` graph; `Person` typing; entity keying |
| **Entities** | `User`, `Person`, `Space`, `Device`, `Node`, `Sensor`, `Actuator`, `Display`, `Application`, `NetworkLink`, `Capability`, `Model`, `Task`, `Observation` |
| **Relationships** | `device-in-space`, `camera-observes-space`, `display-in-space`, `node-hosts-model`, `device-provides-capability`, `space-adjacent-to` |
| **Inputs** | Perception (18), node telemetry, external services, **enrolled synthetic observers**, user statements |
| **Outputs** | `world.fact_updated` / `fact_expired` / `conflict` / `write_rejected`; queryable snapshot by HLC |
| **Persistence** | Facts durable with `supersedes` retained; **reconstructible by replaying the log to a given HLC** — which is what makes trigger provenance auditable |
| **Concurrency** | Single writer per lease; supersession makes replay order-insensitive |
| **Lifecycle** | `SM-WORLD-FACT`: `UNKNOWN ↔ CURRENT ↔ CONFLICTED` |
| **Invariants** | `INV-COORD-1`…`3`, `INV-WORLD-1` (an unknown person is never resolved to the owner), `INV-WORLD-2` (topological, not metric), `INV-AUTO-4` (external ingress exists in production) |
| **Failure modes** | Stale fact → `UNKNOWN` at TTL, **never "last known value"**; contradictory sources → `CONFLICTED` + `world.conflict`, no silent winner; unknown subject → `UNKNOWN`, which does not fire triggers |
| **Recovery** | Replay from checkpoint; expired facts do not resurrect |
| **Observability** | Fact counts by state, expiry rate, conflict rate, ingress source mix |
| **Security** | `trust_class` per fact; unknown provenance treated as `retrieved_external`; inference is owner-only and non-exportable |
| **Verification** | `A-010`, `A-033`, `A-029` part 3 |
| **Dependencies** | REM-001, REM-011, 18 |

> **Jarvis-divergence.** *No.* Clause: **`UNKNOWN` is a first-class state a fact transitions *into* at a declared TTL (`INV-COORD-2`).** A retrieval-over-documents system has no mechanism that turns a remembered fact into "I no longer know this" at a specified time — retrieval either finds the old text or does not. `A-033.3` fails such a build. Second clause: **`INV-AUTO-4`**, a production ingress letting the world write into VESPER independently of VESPER's own activity.

---

## SPEC-07 — Memory

**Purpose.** Durable, provenance-carrying memory with a **stated total order** for conflict resolution, so that "the system remembers" has a decidable meaning when sources disagree.

| Field | Definition |
|---|---|
| **Responsibility** | Working, episodic/task, semantic/project, procedural, and source/artifact memory; provenance; retention; conflict resolution |
| **Boundaries — in** | Durable recollection and its authority |
| **Boundaries — out** | Environmental state (06); retrieval mechanics (08); learned operational artifacts (REM-012 §1) |
| **Authority** | `memory` leased domain. **User-directed memories are recorded immediately** and remain distinct from system rules |
| **State owned** | `MemoryRecord {memory_id, type, content, provenance, confidence, timestamps, scope, retention, schema_version, source_refs, supersedes, trust_class}` |
| **Conflict order** | 1 system rules · 2 declared source-of-record for that attribute · 3 current observation within TTL · 4 explicit user statement · 5 derived/inferred · 6 model prior (**never authoritative**) |
| **Persistence** | Corrections write `supersedes`; **provenance survives correction**. Retention/expiry is an actual background process with a test, not a documented intention |
| **Invariants** | `INV-MEM-1` (ranks 2–4 disagreeing ⇒ **ask the user**, never a silent pick), `INV-EVID-3`, `INV-PRIV-5` |
| **Failure modes** | Three-way disagreement → surface and ask; retrieval empty → `UNKNOWN`, never a plausible substitute; corruption → restore, preserve evidence, prevent corrupted state becoming authoritative |
| **Recovery** | Checkpoint restore; superseded chain intact |
| **Observability** | Write rate by type, conflict rate, questions raised, retention purges |
| **Security** | `trust_class` per record; secrets never in memory content; deletion removes derived artifacts |
| **Verification** | `A-003.5`, `A-003.6`, `A-037` |
| **Dependencies** | REM-010, 03 |

> **Jarvis-divergence.** *Partly — closed by one clause.* A chatbot can have a vector memory. The clause that does not fit: **`INV-MEM-1` — a three-way disagreement across the calendar, a live observation and something the user said produces a question.** That presupposes a declared source-of-record per attribute and a live observation stream. `A-003.5` is unsatisfiable without both.

---

## SPEC-08 — BAG / context retrieval

**Purpose.** Source-grounded, exact retrieval — *"BAG instead of RAG… NO GUESSING"*. The distinction is enforceable rather than nominal.

| Field | Definition |
|---|---|
| **Responsibility** | Project/knowledge maps, exact retrieval, semantic retrieval, summaries, context assembly and budgeting, automatic and manual modes |
| **Boundaries — in** | Selecting and assembling context; grounding claims to retrieved spans |
| **Boundaries — out** | Cache mechanics (09); claim emission (10 / `DF-OUTPUT-GATE`) |
| **Authority** | `L0`–`L1`. **Retrieval never carries authority**; retrieved content is data (RB-025, DR-020) |
| **State owned** | Maps, indexes, source registry, assembled context fragments |
| **Inputs** | Files, project registry, web, patterns, exact documents, memory, world model |
| **Outputs** | `ContextFragment[]` with `trust_class`, `derived_from`, `context_role`; `UNKNOWN` on empty |
| **Concurrency** | Read-mostly; index updates are single-writer per index |
| **Invariants** | **`INV-EVID-2`** (no answer cites a source it did not retrieve; a similarity score is never sufficient grounding), `INV-AUTH-3` (taint through summarisation), `INV-AUTH-6` (planner context holds no `retrieved_external` fragment), `INV-EVID-3` |
| **Two-context pattern** | The high-authority planner context **never ingests raw external content**. A low-authority extraction context ingests it and returns only schema-validated structured data. This is architectural, not optional |
| **Failure modes** | Empty result → `UNKNOWN`; budget overrun → drop lowest priority **with a reported degradation**, never silent truncation; span not reproducible → the claim is dropped by `DF-OUTPUT-GATE` |
| **Recovery** | Index rebuild from source; maps are derived and disposable |
| **Observability** | Retrieval latency, span reproducibility rate, context size, taint distribution, mode (auto/manual) |
| **Security** | Every fragment carries taint; a fragment with unknown provenance is `retrieved_external` |
| **Verification** | `A-006`, `A-003`, `A-025` (incl. 25.7 summary-of-injected-page), `A-032` |
| **Dependencies** | REM-003, REM-010, 09 |

> **Jarvis-divergence.** *No.* Clause: **the two-context pattern (`INV-AUTH-6`) — the planner context structurally cannot contain externally-retrieved text.** An agentic chatbot has one context that ingests retrieved text and then calls tools; `A-025.7` and `25.8` fail any single-context design. Second clause: `INV-EVID-2` makes "BAG not RAG" a testable property (a cited span must be byte-reproducible) rather than a class name.

---

## SPEC-09 — Cache architecture

**Purpose.** Avoid reprocessing everything every time, without becoming a taint-laundering channel.

| Field | Definition |
|---|---|
| **Responsibility** | File-hash, chunk, embedding, summary and prompt-prefix caches (where the runtime supports them), plus reusable computation |
| **Boundaries — in** | Storage, invalidation, reuse |
| **Boundaries — out** | What is worth caching (08) |
| **Authority** | `L0` |
| **State owned** | Cache entries keyed by content hash, each carrying `trust_class` and `derived_from` |
| **Invariants** | **`INV-AUTH-3` — taint propagates through cache reuse.** A cache entry with no `trust_class` is a **cache miss**, not a trusted hit |
| **Invalidation** | Per tier: file-hash on content change; chunk with its file; embedding with its chunk **and** model version; summary with any input; prefix with the prompt template version |
| **Failure modes** | Stale entry → hash mismatch → miss; corrupted entry → evict + rebuild; **untyped entry → miss** |
| **Recovery** | Caches are fully derivable; loss costs latency only |
| **Observability** | Hit rate per tier, eviction cause, taint distribution of hits |
| **Security** | Never caches secrets; a cached summary of tainted content **remains tainted** — this is the second-order propagation case `A-025.8` exists for |
| **Verification** | `A-006`, `A-025.8` |
| **Dependencies** | REM-003, 08 |

> **Jarvis-divergence.** *Partly.* A chatbot can cache. The clause that does not fit: **an untyped cache entry is a miss.** Ordinary caches key on content and return strings; VESPER's must refuse to return a value whose provenance it cannot state, because a cached summary of an injected page is the cheapest possible injection vector.

---

## SPEC-10 — Model gateway

**Purpose.** One normalized contract across every provider and local runtime, and **the single choke point** where cost class is enforced.

| Field | Definition |
|---|---|
| **Responsibility** | Request/stream/response/health/cancellation/quota/error/capability/usage normalization; provider adapters; the filtered fallback ladder |
| **Boundaries — in** | Provider abstraction, error taxonomy, quota tracking, cost-class admission |
| **Boundaries — out** | Which model to pick (11); what to say (12, 16) |
| **Authority** | Enforces `INV-COST-1`. **No caller may reach a provider adapter without traversing `DF-PROVIDER-ADMIT`** |
| **State owned** | Provider health, per-credential quota with rolling windows, `cost_class` per credential and profile |
| **Fallback ladder** | `classify → retry/backoff → alternate provider [SKIP if cost class not permitted] → local fallback → queue/pause/degrade/stop`. **Not escalate-to-paid** |
| **Error taxonomy** | Versioned enum: `retry_worthy \| switch_worthy \| fatal \| content_policy \| quota \| authorization \| cost_policy \| halted_by_interlock`, each with a declared policy |
| **Invariants** | `INV-COST-1`…`INV-COST-6` |
| **Failure modes** | Quota → local backoff (free tiers rarely expose introspection, so quota is inferred locally and pessimistically); mid-stream failure → **per modality**: for voice the spoken prefix is committed and continuation is *semantically resumable*, never silently restarted; all free exhausted in `FREE_TIME` → checkpoint, queue, `autonomy.blocked_on_cost_policy`, **do not wake the user** |
| **Observability** | SR-004 requires **user-visible** error class and retry timing, not merely logged — *"just like Claude Code CLI"* |
| **Security** | Credentials from the secret store (27), never in model context or telemetry |
| **Verification** | `A-004` (incl. mid-stream voice kill), `A-021` |
| **Dependencies** | REM-006, 27 |

> **Jarvis-divergence.** *Partly.* A chatbot can have a provider gateway. The clause that does not fit: **`INV-COST-1` asserted at the gateway boundary during an unattended `FREE_TIME` run** — the gateway must refuse a paid call when no human is present and the alternative is to queue work overnight. `A-004`'s extended case is a statement about behaviour with nobody watching.

---

## SPEC-11 — Model routing

**Purpose.** Send easy tasks to smaller models and hard tasks to stronger ones, selecting against **measured** hardware rather than product names.

| Field | Definition |
|---|---|
| **Responsibility** | Task-class classification, profile selection, node placement, context budgeting input, speculative decoding where supported |
| **Boundaries — in** | *Which* model/profile/node |
| **Boundaries — out** | *How* to reach it (10); resource governance (SPEC-D 19) |
| **Authority** | `L0`. Routing decisions are advisory to the governor, never a direct actuator |
| **Inputs** | Task complexity, latency target, modality, context need, quality requirement, **measured** `NodeCapabilityProfile`, availability, cost policy, reliability |
| **Invariants** | **`INV-HW-1`** (no routing path references a product name), `INV-HW-2` (measured, not declared), `INV-COST-3` |
| **Failure modes** | No profile meets the minimum → degrade to the strongest available **and report the degradation**; no measured profile for a node → **not routed to**; oscillation → the damped governor, not the router, decides |
| **Recovery** | Re-route on node loss; task state survives (05) |
| **Observability** | Routing decisions with the deciding factors named and inspectable **by VESPER itself** (SR-011) |
| **Verification** | `A-022`, `A-042` profile matrix, `A-005` |
| **Dependencies** | REM-006, REM-011, 04, 10 |

> **Jarvis-divergence.** *Partly.* Model routing is ordinary. The clause that does not fit: **routing selects across *nodes* by measured throughput, and `INV-HW-1` forbids naming a machine.** A chatbot routes between APIs; VESPER routes work onto physical machines whose capability was measured at enrollment, and must keep working when one leaves the house.
