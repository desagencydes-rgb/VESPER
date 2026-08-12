# VESPER V0 — COC TRACEABILITY MATRIX (Independent Audit)

**Review date:** 2026-08-11
**Audited against:** COC + Rulebook v1.1 Parts I–XVI; Engineering Foundation v1.0; Engineering Baseline v1.0 (00–07)
**Supersedes for review purposes:** COC Part XI (see AR-012 — Part XI is a generated bundle-join, not an audit)

---

## Grading rule (applied without exception)

A requirement is **PASS** only if the architecture provides **both**:

1. a **credible implementation path** — a named mechanism, not a restatement of the goal; and
2. a **credible verification path** — a named acceptance test (A-xxx) or specified test that **would actually fail** if the requirement were unmet.

**"Acceptance test required" is a placeholder, not a verification path.** COC Part XI contains that identical string in all 51 verification cells, and the corpus contains **no acceptance-test-to-SR mapping anywhere** (AR-013). The `Verification` column below therefore records *this review's* best-effort reconstruction of which A-test would exercise each SR, flagged where none exists. Where an A-test exists but tests a neighbouring mechanism rather than the SR itself, it is marked `partial`.

**Status vocabulary:**

| Status | Meaning |
|---|---|
| **PASS** | Mechanism + falsifiable verification both present |
| **PARTIAL** | Mechanism present but incomplete, or verification weak/indirect |
| **GAP** | Named in the corpus, but no mechanism and/or no verification exists |
| **CONTRADICTION** | The corpus contains internally conflicting instructions for this SR |
| **UNVERIFIABLE** | Cannot be falsified as currently specified |

**Release relevance:** `R0`=foundation, `R1`=local intelligence, `R2`=device/presence, `R3`=perception/world, `R4`=autonomy, `R5`=integrated V0, `R&D`=research track.

---

## Result summary

| Status | Count | SR IDs |
|---|---|---|
| **PASS** | **1** | SR-004 |
| **PARTIAL** | **27** | SR-001, 003, 005, 007, 008, 010, 011, 012, 014, 015, 019, 020, 021, 022, 025, 026, 029, 031, 037, 040, 041, 042, 043, 044, 048, 049, 050 |
| **GAP** | **18** | SR-002, 006, 009, 013, 016, 017, 023, 024, 027, 028, 030, 032, 033, 034, 035, 036, 038, 046 |
| **CONTRADICTION** | **4** | SR-018, 039, 045, 051 |
| **UNVERIFIABLE** | **1** | SR-047 |

**One requirement of fifty-one currently meets the PASS bar.** This is not a claim that fifty of fifty-one are unaddressed — most are architecturally *represented*, which is why PARTIAL dominates. It is a claim that the corpus, as delivered, cannot demonstrate that it satisfies them.

---

## Matrix

Legend for `Contract`: `—` = no contract in IC-001…IC-010 covers this requirement.

### SR-001 → SR-012 (Provider fabric, routing, context, telemetry)

| SR | Original requirement | Engineering treatment | Architecture location | Contract | Verification | Rel. | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| **SR-001** | AI assistant on weak hardware; API switch system may be required | Provider gateway with pool of free APIs + separately authorized paid providers | Arch §9, §24; 04 §9; 06 Phase 2 | IC-002 | A-004 `partial` | R1 | **PARTIAL** | Pool is undifferentiated — no `cost_class` on credentials, so the free/paid boundary SR-045 depends on does not exist. AR-005, AR-033 |
| **SR-002** | Present via projector, glass screen, 3D hologram, MacBook Neo | "Physical/spatial presentation is a core capability family" | Arch §6, §20; 05 §2 | IC-005 | A-009 `partial` | R2 | **GAP** | IC-005 is one sentence; no scene schema exists, so A-009 is satisfiable by rendering the same markdown twice. AR-001 |
| **SR-003** | Auto-switch on quota/error, retry without stopping | Classify → switch → retry → expose state | Arch §9, §24 | IC-002 | A-004 | R1 | **PARTIAL** | No error taxonomy, no quota model, no mid-stream failure semantics (AR-031). "Retry without stopping" actively conflicts with SR-045 via the uncost-filtered ladder (AR-005) |
| **SR-004** | Show error type and time of retry | User-visible operational status during failure/retry | Arch §9 | IC-002 | **A-004** | R1 | **PASS** | A-004 explicitly requires "visible error classification, retry timing" — falsifiable, and the mechanism (gateway state exposure) is named. The only SR meeting both halves of the bar |
| **SR-005** | Offline backup: best practical local model | "Local inference is a first-class continuity path" | Arch §9, §24; 05 §11 | IC-002 | A-004 `partial` | R1 | **PARTIAL** | No minimum hardware profile declared, so "best practical" is unevaluable against any candidate machine — the requirement cannot be checked before hardware purchase. AR-017 |
| **SR-006** | Local model architecture optimizing compute + thinking | "Model/runtime selection must be benchmarked" | Arch §9, §13 | IC-002 | **none** | R1 | **GAP** | No acceptance test; no benchmark obligation bound to this SR; handwritten specifics (Metal, unified memory, no swap, few models loaded) have no SR of their own. AR-011, AR-017 |
| **SR-007** | Mapping system instead of dumping tokens/files/code | Project/knowledge maps as first-class navigation | Arch §10; 04 §8 | — | A-006 | R1 | **PARTIAL** | A-006 is a genuinely good test. But no map schema, no contract, ADR-004 unresolved. Related: "BAG instead of RAG" has no SR at all (AR-011) |
| **SR-008** | Context management by intent; automatic + manual modes | "Persistent subsystem with policy-driven and explicit user control" | Arch §10 | — | A-006 `partial` | R1 | **PARTIAL** | **Manual mode is untested** — A-006 exercises retrieval efficiency only. No context contract in IC-001…IC-010 |
| **SR-009** | Router: easy → small models, hard → strong models | "Dynamic model routing is core" | Arch §9; 04 §9 | IC-002 | **none** | R1 | **GAP** | A-004 tests *provider failover*, a different mechanism. No test asserts difficulty-based routing. No complexity-classification method specified. AR-013 |
| **SR-010** | Context Budget Manager | "Context/token/resource budgeting is core" | Arch §10, §13 | — | A-006 `partial` | R1 | **PARTIAL** | Budget enforcement point undefined; verification cost is not budgeted as a line item (AR-015, AR-024) |
| **SR-011** | Perf monitor: model, context, time, tokens, RAM, GPU, CPU, quality — visible to model, actionable | Telemetry queryable by decision systems | Arch §13, §25; 04 §16 | — | A-005 `partial` | R0 | **PARTIAL** | Model-visible + model-actionable creates a closed control loop with no damping, hysteresis, or dwell time. AR-032 |
| **SR-012** | Fallback: retry with better prompt/model or escalate | "Explicit decision tree, not a generic error handler" | Arch §9, §24 | IC-002 | A-004 | R1 | **PARTIAL** | The ladder exists and is correctly shaped, but carries no cost-class predicate (AR-005) and no error taxonomy to branch on (AR-031) |

### SR-013 → SR-019 (Agents, nodes, network)

| SR | Original requirement | Engineering treatment | Architecture location | Contract | Verification | Rel. | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| **SR-013** | Task planner + verifier (one plans, another checks) | "Planning and verification are separate control stages" | Arch §11, §12; 04 §12 | IC-007 | **none** | R1 | **GAP** | Verifier is named in six places and specified in none: no strategy taxonomy, no disagreement handling, no typed acceptance condition, no cost model. AR-015 |
| **SR-014** | Multiple agents on demand; no number limit but hardware | "No artificial ceiling; dynamic hardware/resource/policy limits" | Arch §11; 02 §17 | IC-007 | **A-007** | R1 | **PARTIAL** | A-007 is well-formed and directly targets the requirement. Blocked by: no resource-accounting mechanism behind "constrained by actual resources", and no authority attenuation across the spawn boundary (AR-006) |
| **SR-015** | Multiple hardware nodes: desktop, laptop, J3, iPhone, Neo | "Distributed across heterogeneous capability nodes" | Arch §2; 05 §2 | IC-004 | A-010, A-017 | R2 | **PARTIAL** | Node fabric is well described. Control-plane topology, ownership, and partition behavior are undefined — the distributed part of "distributed" is missing. AR-002, AR-003 |
| **SR-016** | Dedicated network on portable modem; devices stay normally usable | "Dedicated control/data plane on the portable router" | 05 §5, §6, §7 | IC-004, IC-009 | **none** | R2 | **GAP** | No test. The modem is a single point of failure for the whole control plane and this is nowhere addressed; LAN-bound vs. overlay is deferred to unresolved ADR-012, and the answer changes device identity, discovery and the offline story. AR-002, AR-009 |
| **SR-017** | Desktop accessible through an interface when needed | DR-023 human-environment interface | DR-023; 05 §12 | — | **none** | R2 | **GAP** | Represented only as a derived requirement sentence. No interface specification, no contract, no test |
| **SR-018** | J3 has its own assistant OS/space + backend + 2D/3D holographic output | "Dedicated assistant node with its own runtime, backend services as assigned, and visual-output stack" | Arch §20; 05 §2 | IC-004, IC-005 | A-009 `partial` | R2 | **CONTRADICTION** | Admits two incompatible architectures — thin presence endpoint vs. autonomous trusted node — and the corpus never chooses. Compounded by 05 §4 having **no enrollment admission criteria**. AR-018 |
| **SR-019** | Neo = main space; desktop = secondary/fallback/main-if-Neo-absent; iPhone additive | "Node roles are dynamic and capability-based" | 05 §11, §12; Arch §24 | IC-004 | A-017 | R2 | **PARTIAL** | The source explicitly describes **promotion** ("main assistant's space if Macbook not available"). No election, lease, replication, or split-brain mechanism exists to perform it. AR-002 |

### SR-020 → SR-028 (Perception, execution, media, learning, displays)

| SR | Original requirement | Engineering treatment | Architecture location | Contract | Verification | Rel. | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| **SR-020** | Speak, listen, see space via cameras, see screens, self-interact everywhere | "Multimodal perception and cross-device interaction are core" | Arch §7, §8 | IC-005 | A-008, A-013 | R3 | **PARTIAL** | Perception plane and provenance model are sound. No sensor lifecycle state machine, no consent model, no guaranteed-off path, no non-owner person concept. AR-027 |
| **SR-021** | Run/execute code, scripts, commands | "Controlled execution capability is core" | Arch §8; 04 §10 | IC-003 | A-013 | R1 | **PARTIAL** | *Part XI maps this to Architecture §1 (Mission and Identity) — evidence of the bundle-join defect, AR-012.* Real gaps: no authorization decision function (AR-006), no injection ceiling on a context that can reach `shell.execute` (AR-007) |
| **SR-022** | Extract/read from all files | "File/document ingestion and exact-source retrieval" | Arch §10 | IC-003, IC-006 | A-006 | R1 | **PARTIAL** | Retrieval path is credible. Claim-level evidence binding absent, so "exact-source" is not enforceable at output time. AR-014 |
| **SR-023** | Generate images locally or via API | "May use local or provider-backed paths" | Arch §9 | IC-002, IC-003 | **none** | R2 | **GAP** | No test; no artifact provenance requirement for generated media; no local/remote selection policy |
| **SR-024** | Read videos: frames, motion comparison, length, audio, captions, metadata | Media evidence pipeline producing structured derived evidence | DR-026; Arch §7 | IC-003 | **none** | R3 | **GAP** | DR-026's framing is correct ("provenance-aware derived artifacts instead of opaque model guesses") but has no schema, no pipeline spec, and no test |
| **SR-025** | Search web; search files/inside files/patterns | "Unified retrieval across local and web sources" | Arch §10 | IC-003 | A-006 `partial` | R1 | **PARTIAL** | A-006 covers local retrieval only. Web retrieval is the primary injection vector and has no containment (AR-007) |
| **SR-026** | Monitor hardware so it doesn't choke; **read kernel** | "Resource/OS telemetry and controlled remediation are core" | Arch §13 | — | A-005 (monitor half only) | R0/R&D | **PARTIAL** | The interpretation covers monitoring and **silently drops the kernel half**. Kernel access requires privileged, per-OS mechanisms and entitlements and differs on every OS in the fleet. **Part XIV §3's procedure for infeasible SRs was applied to SR-037 but not here.** AR-020 |
| **SR-027** | Ability to learn (agentic + LLM) | "Learning loop subject to validation and versioning" | Arch §21; DR-012 | — | A-016 `nominal` | R5 | **GAP** | No promotion unit, no validation gate, no rollback unit, no drift detection. The default implementation (system-prompt accretion) violates RB-020 while appearing compliant. AR-022 |
| **SR-028** | Change displays; define their place from network + cameras; unified or separate | Display topology + spatial/environment model | Arch §5, §6, §20; DR-024 | IC-004, IC-005 | A-009/A-010 `partial` | R3 | **GAP** | "Define their place" is a localization requirement with **no chosen spatial representation** (topological/metric/relational). Presence-by-proximity (05 §10) is therefore unimplementable. AR-019, AR-001 |

### SR-029 → SR-040 (Adaptation, communication, artifacts, security, sensing)

| SR | Original requirement | Engineering treatment | Architecture location | Contract | Verification | Rel. | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| **SR-029** | Infer physiology/mentality/mood/vibe; act when necessary | "Uncertain evidence only; never present inference as fact" | Arch §16; DR-011 | IC-006 | **none** | R3 | **PARTIAL** | DR-011 is one of the corpus's better derived requirements. Two problems: no test, and this explicitly-untrusted signal is what gates the **absolute** SR-045 cost prohibition (AR-004). No `Person` typing, so inference may run on non-owners (AR-027) |
| **SR-030** | Adapt via words, humor, ambience, lights, visuals, hologram, music, research, action | "Behavior adaptation and environmental actuation are first-class" | Arch §17 | IC-005 | **none** | R4 | **GAP** | No test. Ambience ownership, fail-safe defaults, and priority relative to alarm/task are undefined (AR-026). Depends on the missing scene contract (AR-001) |
| **SR-031** | Call/FaceTime on user's behalf; appear on user's behalf | Controlled external action with explicit delegated identity | Arch §18; DR-025; RB-012 | IC-003 | A-018 `partial` | R4 | **PARTIAL** | No outbox or reconciliation probe, so "did the call happen?" is unanswerable after a crash (AR-028). Platform feasibility for programmatic calling is unassessed — same procedural defect class as AR-020 |
| **SR-032** | Send messages, notes, calendar, plans in HTML, showcase on web | "Productivity and communication tools are core" | Arch §18 | IC-003 | **none** | R4 | **GAP** | No test; irreversible external effects (invites to third parties) have no reversibility classification (AR-028) |
| **SR-033** | Generate useful/funny photos; research output as HTML | "Artifact generation and presentation are core" | Arch §12 | IC-003, IC-010 | **none** | R4 | **GAP** | *Part XI maps this to Arch §11/§12/§21 (agents/research/learning) — a mis-bundle.* No artifact registry contract, no test |
| **SR-034** | MD/TXT/PDF reports with clean hierarchy, format, design, vocabulary | "Structured artifact generation is core" | — | IC-003 | **none** | R2 | **GAP** | *Part XI maps this to Architecture §1 (Mission and Identity) — the fallback bucket, AR-012.* No architecture section actually owns artifact generation |
| **SR-035** | Explain, play music, weather, news, jokes, impressions; personality | "Personality and contextual interaction are part of the behavioral spec" | Arch §17; RB-033; DR-028 | — | **none** | R4 | **GAP** | DR-028 ("testable personality") asserts tests exist for honesty, uncertainty, initiative, interaction mode — **none of the four is written**. Note: one handwritten item on this page was excluded on safety grounds without receiving an SR ID (AR-029) |
| **SR-036** | Take actions when elected/authorized; identify → talk or act | "Select interaction/action mode from situational context and policy" | Arch §4, §6, §12 | IC-008 | **none** | R4 | **GAP** | This is the initiative requirement. The trigger model that would produce it is forbidden-by-negation (Part V §28) and undefined-by-omission. AR-008 |
| **SR-037** | Wi-Fi / through-wall sensing; may need Raspberry Pi | Isolated research adapter, disabled by default, provenance-tracked, barred from trusted world-model fact | DR-031; 05 §17 | IC-004 | **none** (correctly R&D) | R&D | **PARTIAL** | **Best-handled speculative requirement in the corpus.** DR-031 is the correct pattern and should be the template for SR-026 and SR-031. Only defect: no explicit `R&D` status label in the matrix, so it reads as untested rather than deliberately deferred. AR-013, AR-020 |
| **SR-038** | Identify breaches/vulnerabilities/intruders in network/hardware | Authorized security monitoring and incident detection | Arch §19; DR-015 | IC-009 | A-014 `partial` | R5 | **GAP** | A-014 tests rejecting unauthorized requests and surviving injection — a different mechanism entirely. No detection specification, no baseline, no anomaly model, no test for SR-038's actual content |
| **SR-039** | Bypass/workarounds to reach goals on all hardware (explain and ask first) | Narrowed to "legitimate alternative paths; never bypass access controls without authorized administrative context" | Arch §8, §19; RB-013, RB-014 | IC-003 | A-013 `partial` | R4 | **CONTRADICTION** | Two defects. **Procedural:** the narrowing is a change in SR meaning absorbed into interpretation text with no recorded owner-approved deviation (P-001, RB-036 require one). **Functional:** no `owner_administrative` capability class exists at any level, so legitimate privileged action on the owner's own hardware — exactly the source's intent, complete with its own "explain and ask first" gate — has **no authorized path**. AR-021 |
| **SR-040** | Read physical notes/stickers/numbers/books/images/handwriting via camera | "OCR/vision over physical artifacts is core" | Arch §7 | IC-005, IC-006 | **A-008** | R3 | **PARTIAL** | A-008 directly targets this and is well-formed. Held back by absent retention policy for OCR output and absent third-party handling — reading whatever is in frame includes documents held by guests. AR-027 |

### SR-041 → SR-051 (Behavior, autonomy, integrity, governance)

| SR | Original requirement | Engineering treatment | Architecture location | Contract | Verification | Rel. | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| **SR-041** | Strong humor/sarcasm; absolute honesty; no lies; no guessing; paranoid/skeptical | Behavioral policy enforcing honesty, uncertainty, skepticism, personality | RB-001…RB-036; DR-028; P-004 | — | A-003 | R1 | **PARTIAL** | **The only SR in Part XI with no architecture reference at all** — it maps solely to "Rulebook RB-001..RB-036", which is a behavioral layer, not an implementation. No-guessing has no mechanism: no claim-level evidence binding, no output gate, no first-class UNKNOWN. A-003's single test case cannot establish a behavioral property. AR-014 |
| **SR-042** | Work at night autonomously; read/code/generate/research/build; don't wake user | "Overnight autonomous operation is core, subject to policy and budgets" | Arch §14; DR-005 | IC-008 | A-011 | R4 | **PARTIAL** | IC-008's field list is the right shape. Three blockers: trigger model undefined (AR-008), free-time predicate undefined (AR-004), and no injection ceiling on unattended tool-enabled web access (AR-007) |
| **SR-043** | Wake user on time; loud, parallel outputs across all devices; must not stop | "Alarm/intervention orchestration is first-class with escalation policy" | Arch §15 | IC-008 | A-012 | R4 | **PARTIAL** | No priority lattice permitting the alarm to override RB-034/RB-015/RB-006 — a quiet-hours policy could silently suppress it. No distributed alarm ownership or failover. No escalation ceiling, duration cap, or non-ASR acknowledgment path. AR-026 |
| **SR-044** | Real professor/scientific research; search, experiment, imagine, build, act | Research engine: evidence → hypothesis → experiment → measurement → report | Arch §12; DR-016 | **IC-010** | A-015 | R5 | **PARTIAL** | IC-010 is among the better contracts and correctly makes "insufficient evidence" a valid conclusion. Cannot run unattended safely without the AR-007 injection ceiling and the AR-014 claim-evidence envelope that RB-023 depends on |
| **SR-045** | Free-time activities use free models only; no paid API calls | "Absolute: free/local only; queue, pause, degrade or stop rather than pay" | Arch §14; DR-013; RB-016, RB-017 | IC-008 | A-011 `partial` | R4 | **CONTRADICTION** | Two live contradictions. (1) **Arch §24's fallback ladder** — "classify → retry → alternate provider/model → local fallback" — has no cost-class predicate, so free-tier exhaustion routes onto a paid provider by design (AR-005). (2) The prohibition is **absolute** but its trigger ("free-time") is an **inference** the corpus separately declares untrustworthy (SR-029/DR-011), and is never defined as a machine-evaluable predicate (AR-004) |
| **SR-046** | Primary interaction = hearing/talking/visual/acting; text & keyboard are fallback | Interaction manager prefers multimodal/presence channels | Arch §6; RB-007; Part V §28 | IC-005 | **none** | R2 | **GAP** | *Part XI maps this to Architecture §9 (Model Routing) + DR-013 (Cost Governor) — neither has any relationship to it (AR-012).* **No test anywhere asserts that a chat box is not required to reach any core capability.** This is the single most important untested property in the corpus: it is the definition of the anti-chatbot requirement. AR-001, AR-013 |
| **SR-047** | Interactions fast, realtime, realistic, fun, impressive | "Latency/experience targets must be measurable and optimized" | DR-018; 04 §18 | — | A-020 `circular` | R2 | **UNVERIFIABLE** | The Foundation instructs: *"Measure first on target hardware… convert measured baselines into ADR-backed targets."* A target defined as whatever was measured **can never fail**. No quantification of SR-047 exists anywhere — no number, no range, no reference point. Compounded by AR-024: voice-primary × realtime × mandatory verification × free-local-only has never been costed |
| **SR-048** | Be helpful; find fixes/workarounds; no lies/guessing; be active; learn | Behavior engine + continuous improvement loop | RB-005, RB-006, RB-014; DR-012 | — | A-016 `partial` | R5 | **PARTIAL** | RB-005 ("don't wait, don't be lazy") and RB-006 ("don't act merely because you can") point in opposite directions with **no arbitration metric, no interruption budget, no rate limit** — an implementer must invent it and either choice violates one rule (AR-025). Learning half blocked by AR-022 |
| **SR-049** | System/rules/code/network/hardware are sacred; protect, secure, don't break | "System integrity and recoverability are top-level priorities" | Arch §19, §23, §24; RB-009, RB-027; P-010 | IC-009 | A-019 | R5 | **PARTIAL** | *Part XI maps this to Arch §2/§5/§8/§13 — **not** §19 (Security Ops), **not** §23 (Authorization), **not** §24 (Recovery). The three sections that actually implement it are unreferenced (AR-012).* Real exposure: no enrollment security baseline (AR-018), no injection ceiling (AR-007), no delegation attenuation (AR-006) |
| **SR-050** | Hardware ecosystem: J3, iPhone, cameras, glass cube, MacBook, desktop, laptop, projector, interactive desk | "Hardware abstraction must accommodate present and future nodes" | 05 §2; Foundation "Hardware abstraction" | IC-004 | A-010 | R2 | **PARTIAL** | The principle is stated correctly in three documents. **No capability profile schema exists**, no accelerator abstraction, no per-subsystem minimum profile — so nothing forces a hardware substitution to be checked. AR-017, AR-034 |
| **SR-051** | COC + rules become the project's bible | Source immutability, traceability, change control, release gates | Part XIV; P-001, P-006; RB-036 | — | A-001 | R0 | **CONTRADICTION** | **Part XIV is genuinely strong** — especially §8 ("'Not implemented yet' is a release status, not a reinterpretation"). But A-001's claim of complete source-and-test traceability is falsified by three independent findings: the SR registry is lossy against Part I (AR-011), Part XI is a bundle-join (AR-012), and no SR↔A-test mapping exists (AR-013). Part XV then records "Source-to-architecture traceability present: **PASS**" and "Release decision: **CLOSED**". The lock was granted on self-audit evidence that does not hold, and Part XIV's immutability now protects the defect |

---

## Cross-cutting observations

**1. Part XI is machine-verifiably not an audit.** Independently confirmed by parsing all 51 rows:

- **Nine of twenty-eight architecture sections are referenced by zero SRs:** §3 (Persistent Vesper Runtime), §4 (Observation→World Model→Decision→Action Loop), §22 (Data Architecture), §23 (Security/Authorization Model), §24 (Failure/Recovery/Continuity), §25 (Observability), §26 (Development/Release), §27 (Definition of Done), §28 (Explicit Non-Interpretation Rules). §3 and §4 are the two most load-bearing sections in the entire document.
- **One of thirty-one DRs appears anywhere in the matrix:** DR-013, bundled onto 15 unrelated SRs. DR-002 (Persistent Identity), DR-003 (World Model), DR-004 (Presence Engine) appear zero times.
- **All 51 verification cells contain the identical placeholder string.**
- **Architecture §1 (Mission and Identity) is the evident fallback bucket** — SR-021 (execute code), SR-034 (generate reports), and SR-051 (change control) all land there.

**2. Nineteen SRs have no acceptance test at all** under this review's best-effort reconstruction: SR-006, 009, 013, 016, 017, 023, 024, 027 (nominal only), 029, 030, 032, 033, 034, 035, 036, 037 (correctly R&D), 038, 046. Twenty acceptance tests are asserted to cover fifty-one requirements, with zero documented mapping between them.

**3. Handwritten source content with no SR ID** (AR-011) — these cannot appear in this matrix because they have no ID to trace: "BAG instead of RAG" as a binding retrieval constraint; prompt compression / memory summaries with immediate recording; the five-tier cache architecture; the multi-step reasoning pipeline; speculative decoding; Metal / unified-memory / no-swap / few-models-loaded constraints; node availability and partition profiles; and one item excluded on safety grounds (AR-029). The omissions are concentrated in the **engineering-load-bearing** material, which is precisely where the immutable layer most needed to constrain implementation.

**4. What is genuinely well-traced.** SR-004 (PASS), SR-014 (A-007 is a well-formed test of a correctly-stated requirement), SR-040 (A-008 directly targets it), SR-037 (DR-031's quarantine is the correct pattern for a speculative requirement), and SR-044 (IC-010 is a real contract with the right shape). These demonstrate that the corpus is capable of the standard — which is why the remaining gaps read as incompleteness rather than incapability.
