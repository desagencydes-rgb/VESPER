# VESPER's home — what it can carry

Every card, widget, window and stage the home holds, with **whether it can be
hooked up today**. Written so that designing a surface and wiring it are
separate acts and neither waits on the other — the same split
`ISLAND-CONTENT.md` makes for the island's six columns, over ninety cards.

Architecture is in `HOME-ARCHITECTURE.md`. Primitives are in
`DESIGN-FOUNDATION.md`. The room assignment and its arithmetic are derived by
`source/home_rooms.py` and not asserted here.

## The four statuses

| | |
|---|---|
| **FRONTEND** | needs no producer at all. Presentation, interaction, or a file already on disk. **Buildable today** |
| **READY** | the producer exists in `core/`; only the binding is missing. It will render *empty* until something runs, and empty is a real answer |
| **BLOCKED** | nothing on this machine can produce it. The reason is recorded, and it is **not drawn** |
| **SUPERSEDED** | a decision already made removes it. Recorded rather than deleted, because the decision is the useful part |

**A BLOCKED card is reported, never approximated.** `core/projection.py` makes
the alternative unconstructible: a `Reading` cannot hold a value without
provenance, and `to_scene()` omits rather than placeholds.

## What the count actually is

```
$ python3 docs/design/source/home_rooms.py
HOME CARDS  90
  P  producer exists in core/, needs the projection only    26
  B  needs a producer that does not run yet                 64
```

That is the derivation's **first cut**, taken from the catalogue's own `st`
field. Reading the modules instead of the field moves it a long way, and the
move is the reason this file exists:

| Status | Cards | |
|---|---|---|
| **FRONTEND** | **17** | buildable with no backend at all |
| **READY** | **39** | producer exists; binding only |
| **BLOCKED** | **33** | named producer missing, per card below |
| **SUPERSEDED** | **1** | |
| | **90** | |

**Fifty-six of ninety cards can be built before a single producer runs**, not
twenty-six. The naive cut under-counted because `st = "sug"` describes how the
idea arrived, not what it costs — and eleven of those suggestions turn out to be
walks over structures that already exist (`evidence.SpanIndex`, `store`'s
append-only `log`, `Fact.confidence`, `Grant.expiry_ms`).

---

## The nine rooms

`DESIGN-FOUNDATION.md` §10 named six rooms and four front doors. Recomputed
2026-08-22 from the owner's routing: that accounts for 81 of the 90, names two
more as front doors without giving them a room, and leaves **seven cards
unmentioned**. The home has **nine** rooms.

| Room | Cards | Kind | Detail lives |
|---|---|---|---|
| Frame | 8 | the shell — mounted in every stage | — |
| Memory | 22 | room | in the room |
| Work | 25 | room | in the room |
| Doing | 10 | room | in the room |
| Beyond | 7 | room | in the room |
| Permissions | 6 | room | in the room |
| Introspection | 5 | room | in the room |
| Presence | 3 | room | in the room |
| Machine | 1 | **front door** | main menu, 27 items |
| Fabric | 1 | **front door** | main menu, 21 items |
| Tunables | 1 | **front door** | Settings, 35 items |
| History | 1 | **front door** | History, 17 items |

Machine, Fabric, Tunables and History are one card each: a front door is a card
whose job is to be the way in, not to hold the contents.

---

## Frame — 8

Mounted in every stage. This is the part that does not change when the work does.

| Card | Source | Status |
|---|---|---|
| Presence indicator | `core/supervisor.py` `Supervisor` | READY |
| Say something | — | **FRONTEND** — a text field. What it dispatches into is Phase B |
| Current attention | `core/tasks.py` `TaskStore` + `core/autonomy.py` | READY — the loop is not running |
| Needs you | `core/authorize.py` `PolicyDecisionPoint` | READY — no PDP running |
| Emergency stop | `core/interlock.py` `SafetyInterlock` · `INV-STOP` ×7 | READY |
| What changed since I looked | `core/telemetry.py` + a last-seen mark | BLOCKED — nothing records a last-seen mark, and a digest over an empty log is not a digest |
| Density control | — | **FRONTEND** |
| Shortcut map | — | **FRONTEND**, and it is owed: the owner's note on Focus mode already asks for *"a list of all shortcuts somewhere"* |

## Memory — 22

`core/evidence.py` · `core/world.py` · `core/store.py` · `core/taint.py`

| Card | Source | Status |
|---|---|---|
| Memory browser | `store.StoreSet` | READY |
| Provenance | `evidence.Claim`, `SourceSpan` | READY |
| World model | `world.WorldModel`, `Fact` | READY |
| Conflicts | `Fact.conflicting` + `evidence.resolve_memory_conflict` | READY |
| Evidence & claims | `evidence.ClaimChecker`, `SpanIndex` | READY |
| Promotion review | `selfmod.Proposal`, `SelfModificationBoundary` | READY |
| Rollback | `store` epochs + `selfmod` | READY |
| Record loss | `store` gap accounting, `StaleEpochWrite` | READY |
| Forget this | `store`'s **append-only `tombstones`** store — the deletion is itself evidence | READY |
| Why do you think that? | `evidence.SpanIndex` traversal | READY — a walk over a structure that already exists |
| Contradiction inbox | `world` conflicts, held rather than resolved | READY — the inbox is presentation over facts already kept apart |
| Confidence & decay | `Fact.confidence`, `Fact.valid_until_ms` | READY — both fields exist, and expiry to `UNKNOWN` is already the semantics |
| Memory diff | `store`'s append-only `log` | READY — a week's diff is a range over an append-only log |
| Correct me | `evidence` supersede + `world.Observation` | READY |
| Learning kinds | — | BLOCKED — five kinds named in the catalogue, typed nowhere |
| Lifetime lessons | — | BLOCKED — no lessons store. The nearest thing that exists is `MEMORY.md`, which is engineering's, not VESPER's |
| OS practice | — | BLOCKED — and this is the most expensive absence in the room: it is where *"this action caused that, verified here rather than read online"* would accumulate |
| Owner model | `core/privacy.py` governs it; nothing holds it | BLOCKED |
| Personality | — | BLOCKED — **and it wants a contract, not a store.** Dials per context with ranges immutable at runtime is exactly the shape of the fifteen contracts already in `contracts/policy/` |
| Knowledge maps | — | BLOCKED — specified, nothing builds one |
| Pinned facts | — | BLOCKED — `Fact` has no pin field |
| Redaction | — | BLOCKED — no redaction flag. `telemetry._redact` redacts *output*, which is a different thing and must not be mistaken for this |

## Work — 25

`core/context.py` · `core/scene.py` · REM-015

| Card | Source | Status |
|---|---|---|
| Experiments | `docs/spikes/INDEX.toml` — 12 spikes, each with `pass_criteria` and `on_fail` | **FRONTEND** — the registry is a file |
| Session replay | the stage store + the window ledger (`HOME-ARCHITECTURE.md` §9) | **FRONTEND** — both are the home's own state |
| Layout templates | the stage store | **FRONTEND** |
| Freeform canvas | — | **FRONTEND** — and the largest single frontend piece in the home |
| Reading queue | documents the home already holds | **FRONTEND** |
| Citation manager | — | **FRONTEND** |
| Prompt library | — | **FRONTEND** |
| Local models | `config.load_capability_profile`, `capability_profiles.toml` | READY — and it renders mostly `UNKNOWN`, which is the **correct** render: one field in that contract is measured |
| Context budget | `context.ContextBudgetManager`, `AssembledContext` | READY |
| Improvement backlog | `INV-IDEA` ×6 | READY |
| Code review | `selfmod.Proposal` | READY — for VESPER's own changes, which is what the card says |
| Lab notebook | `store`'s append-only `log` | READY — dated and append-only is what the store already is |
| Research | REM-015 | BLOCKED **as a record**; the research *stage* is FRONTEND — see the stage table |
| Projects | — | BLOCKED — no project entity |
| Coursework | — | BLOCKED |
| Coding | — | BLOCKED — needs a repository binding |
| AI / ML workbench | — | BLOCKED |
| Files | `artifact.schema` | BLOCKED — no file-scope registry running |
| Driving other AIs | Accessibility | BLOCKED — needs the AX driver and a per-app grant |
| Spaced repetition | — | BLOCKED — needs a card store and a scheduler |
| Deadline tracker | — | BLOCKED — needs a calendar binding, as an adapter behind an abstract capability (`ISLAND-ARCHITECTURE.md` §2b) |
| Notebook | — | BLOCKED — executable notes need an execution path |
| Dataset browser | — | BLOCKED |
| Run comparison | — | BLOCKED |
| Study progress | — | BLOCKED |

## Doing — 10

`core/autonomy.py` · `core/tasks.py` · `core/interlock.py` · `core/executor.py`

| Card | Source | Status |
|---|---|---|
| Task graph | `tasks.Task`, `TaskStore` | READY |
| Reprioritise | `tasks.TaskStore` | READY — the store orders; the drag is frontend |
| Stall detection | `autonomy` stall watchdog · `INV-AUTO-1` | READY — the detector exists and is tested; the loop is not running |
| Scheduled work | `alarm.AlarmInstance`, `autonomy.Trigger` | READY — triggers and alarms are typed; none are armed here |
| Model calls | `gateway.ModelGateway`, `Attempt` | BLOCKED — no gateway process; nothing routes a call |
| Cost & period | `cost.CostPolicy` + `cost_policy.toml` | BLOCKED — the *policy* renders, the *spend* does not. Same finding as the island's Spend gauge |
| Interruption budget | `interruption.InterruptionBudget` | BLOCKED — no budget instance recording spend. Same finding as the island's Attention gauge |
| Interject | `autonomy.AutonomyLoop` | BLOCKED — no loop to interject into |
| Lookahead | — | BLOCKED — nothing plans past the current step |
| Dry run | `core/executor.py` | BLOCKED — needs effect suppression through the executor, and nothing runs plans. *The owner's "Jarvis simulation" — worth building properly rather than early* |

## Permissions — 6

| Card | Source | Status |
|---|---|---|
| Host action vocabulary | `contracts/policy/host_actions.toml` — **13 actions, 5 tiers, inverses declared** | **FRONTEND** — a contract file. Nothing needs to run |
| What could you do now? | `host_actions.toml` + `capability.CapabilityRegistry` + `fabric.effective_trust_zone` | READY — computable from contracts and the fabric today, and the most useful card in the room |
| Taint & context ceiling | `taint.ContextCeiling`, `Tainted` | READY |
| Time-limited grants | `authorize.Grant.expiry_ms` | READY — the type already carries expiry; no PDP issues one |
| Refusal log | `authorize.Decision`, `selfmod.SelfModificationRefused` | BLOCKED — refusals are *raised*; nothing records them |
| Permission inbox | `authorize.PolicyDecisionPoint` | BLOCKED — no PDP holding pending requests |

## Beyond — 7

| Card | Source | Status |
|---|---|---|
| Cross-node behaviour | `core/placement.py` · `INV-PLACE-3` | READY |
| Offline | `placement.Degradation`, `SurvivalProfile` | READY |
| External world | `tasks.Outbox` — recorded before it happens | READY |
| Sync status | `store`'s `SYNC_FULL` sets + `core/hlc.py` | READY |
| Guest safety | `privacy.PrivacyRouter` | READY |
| Phone companion | `devices.DeviceProfile` | **FRONTEND** — *"what it deliberately isn't"* is a written answer, not a producer |
| Travel mode | — | BLOCKED — needs a network-context signal |

## Introspection — 5

**Four of five are FRONTEND, and this room is the cheapest real content in the
home.** Everything it reads is a file in this repository.

| Card | Source | Status |
|---|---|---|
| Invariants | `spec/invariants/INVARIANTS.toml` | **FRONTEND** — read at render time, never from a written-down count. See the correction below |
| Build state | `docs/spikes/INDEX.toml`, `VESPER_ENGINEERING_STATUS.md`, `IMPLEMENTATION_SEQUENCE.md` | **FRONTEND** |
| Module map | the modules under `core/` | **FRONTEND** — an import scan, and `graphify-out/` already exists |
| Coverage map | `CHECKS.toml` + `tools/ci/self_test.py` | **FRONTEND** — *"what is tested, what merely runs"* is exactly what a red-then-green execution distinguishes from a declaration |
| VESPER's own performance | `telemetry.BudgetStat` | READY |

### Two numbers in the catalogue are stale, and the fix is structural

Checked 2026-08-22:

| Catalogue says | Registry says | |
|---|---|---|
| *"All 138 across 37 families"* | **123** ids, **37** families | 37 is right; 138 is not, and no file in the tree produces it |
| *"the 34 runtime modules"* | **35** | `core/projection.py` landed 2026-08-21, after the catalogue was written |

Neither is a defect in the catalogue so much as a demonstration of why these
cards must read the registry rather than render a figure. It is the same failure
`CLAUDE.md` corrected on itself on 2026-08-21 — the island reference drew "320k
assertions" because a stale line in `CLAUDE.md` said so, and the runner's own
headline says 160k. **A count in a design document is a copy. The card renders
the original.**

## Presence — 3

| Card | Source | Status |
|---|---|---|
| Floating dialogs | `scene.SceneRenderer` — the front door; the dialogs are the Float plane | READY |
| Transcripts | — | BLOCKED — no ASR path |
| Menu bar | — | **SUPERSEDED** — `DESIGN-FOUNDATION.md` §9 refused a menu-bar extra: *"the island already owns top-centre, and a second mark competes with the notch for the only scarce space on this display."* The card is kept here so the refusal is discoverable from the surface it applies to |

## The four front doors — 1 card each

| Card | Source | Status |
|---|---|---|
| Thermal pressure (**Machine**) | `host.DarwinAdapter` | READY — as a **level**, never degrees. `thermal='nominal'` is what this platform exposes, and `MEMORY.md` records that no backend work changes that |
| Node graph (**Fabric**) | `fabric.segments` · `enrollment.EnrollmentRegistry` | READY for **segments** (3, live). The node half renders empty: the registry exists and nothing has enrolled. The owner has a phone, a J3 and a Linux box available on request — build it, connect it on enrolment |
| Tunables (**Settings**) | `config.RuntimeConfig` + the 15 contracts in `contracts/policy/` | **FRONTEND** — the contracts are files, and *"a dial may be moved, never widened"* is already the contract's own rule |
| Conversation history (**History**) | `core/telemetry.py`, `core/hlc.py`, `core/codec.py` | BLOCKED — nothing holds a conversation. Ordering, when it exists, is by HLC and never by wall clock (`INV-COORD-4`) |

---

## Widgets

The owner's seventeen widget kinds, against the two hosts in
`HOME-ARCHITECTURE.md` §4. **In-home** is the home's own layer; **system** is a
WidgetKit extension on the desktop.

| Widget | In-home | System | Note |
|---|---|---|---|
| Calendar | FRONTEND | FRONTEND | contents BLOCKED — no calendar binding |
| Roadmap | **FRONTEND** | FRONTEND | `IMPLEMENTATION_SEQUENCE.md` + the spike registry are files |
| Metrics | READY | READY | one measured number per `INV-HW-2`, with its age, or nothing |
| Data map / Data visuals | READY | READY | `placement` distribution, `fabric` segments |
| Infographic | FRONTEND | FRONTEND | must be backed, never decorative — the reference's `REASONING 110%` is refused |
| Maps | FRONTEND | FRONTEND | the world map is `fabric` segments + `devices`; **build it now**, connect on enrolment |
| Images / videos | FRONTEND | FRONTEND | |
| Previews | FRONTEND | **no** | WidgetKit renders snapshots; a live preview is not one |
| Smaller versions of windows | **config** | **config** | this is §1's claim in one row: the same scene at `max_elements = 3` |
| Theories / ideas / notes | READY | READY | `Improvement backlog`, `INV-IDEA` ×6 |
| Critical study of ideas | BLOCKED | BLOCKED | needs the research record |
| Prototyping | FRONTEND | **no** | interactive |
| 3D diagrams | FRONTEND | **no** | WidgetKit cannot host Metal |
| Rendering | FRONTEND | **no** | as above |
| War-rooms | BLOCKED | **no** | needs live task + fabric + approval state at once |

**Every "no" in the system column is the same fact stated five times:** a system
widget is a snapshot the OS caches and re-renders on its own schedule. Anything
continuous, interactive or GPU-backed is an in-home widget and stays home. That
is not a limitation to route around; it is what a widget *is* on this platform.

## Windows

Seven, per `HOME-ARCHITECTURE.md` §5.

| Window | Status |
|---|---|
| Previews — pdf, markdown, images, video, web | **FRONTEND** — `QLPreviewView` + `WKWebView` |
| VESPER's browser | **FRONTEND** for the view; the **taint boundary is drawn at the window**, `core/taint.py` |
| Freeform | **FRONTEND** |
| Notes | **FRONTEND** — the hand splits by author, see §5 of the architecture |
| VESPER's terminal | **FRONTEND** for the view. A command it runs is a host action at its tier and is Phase B |
| Any installed app | needs Accessibility. **Arranged, never adopted** — §2.4 |
| Research space | a **stage**, not a window |

## Stages

Twelve, per `HOME-ARCHITECTURE.md` §7. A stage is data; what it *arranges* is
what decides its status.

| Stage | Layout | Content it arranges |
|---|---|---|
| **Home** | FRONTEND | 8 frame cards — 4 READY, 3 FRONTEND, 1 BLOCKED |
| **Research** | **FRONTEND** | previews + freeform, both FRONTEND. **This is why it is built first** |
| **Study** | FRONTEND | deadlines and progress BLOCKED; the reading and note halves are not |
| **Analysis** | FRONTEND | dataset browser and run comparison BLOCKED |
| **Design** | FRONTEND | the canvas is the surface; nothing to arrange |
| **Prototyping** | FRONTEND | canvas + preview + terminal, all FRONTEND |
| **Watching** | FRONTEND | one window, face Absent |
| **Resting** | FRONTEND | ambience only |
| **Free work** | FRONTEND | whatever was pinned |
| **Coding / building** | FRONTEND | repository binding BLOCKED; `Code review` over `selfmod.Proposal` is READY |
| **Improving itself** | FRONTEND | `Build state`, `Invariants`, `Coverage map` FRONTEND; `Promotion review` READY. **The most complete stage in the product today** |
| **Home / no work** | FRONTEND | — |

**Every stage's layout is frontend.** What varies is how much of what it
arranges is real, and the two stages that are almost entirely real —
**Research** and **Improving itself** — are the two to build first. One is the
owner's flagship use case and the other is VESPER working on itself in front of
the owner, which is the only stage where every card it holds is already true.
