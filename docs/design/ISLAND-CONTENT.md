# The island — what each state can carry

Everything the island could show, per state, with **whether it can be hooked up
today**. Written so that building a design and wiring it are separate acts and
neither waits on the other: a panel whose producer does not exist yet is recorded
here as blocked, with the reason, and is not drawn with a plausible number in it.

## The three statuses, and the rule

| | |
|---|---|
| **LIVE** | wired and rendering real values now |
| **READY** | the producer exists in `core/`; only the binding is missing |
| **BLOCKED** | nothing on this machine can produce it. The reason is recorded, and it is **not drawn** |

**A BLOCKED item is reported, never approximated.** `INV-HW-2`: a number is
measured or it is `UNKNOWN`, and `UNKNOWN` means unavailable.
`core/projection.py` makes the alternative unconstructible — a `Reading` cannot
hold a value without provenance, and `to_scene()` omits rather than placeholds.
So "we'll fill it in later" is not a state this codebase can be left in.

## Shoulders — 370 × 48 pt

The resting state, and the only thing on screen most of the time. Two shoulders
with the camera between them; **nothing may enter x ∈ [771, 956] above y = 32**.

| Content | Source | Status |
|---|---|---|
| The mark, carrying presence | `Behaviour` / mark animator | **LIVE** — speaking, thinking, working, idle |
| Current task | `core/tasks.py` `Task`, `TaskStore` | READY |
| What is playing | no media binding | BLOCKED — nothing reads now-playing |
| Current mission | `core/tasks.py` outbox + `core/autonomy.py` | READY |
| Pause / resume | owner-routed **to island, "everywhere"** | READY — needs an autonomy control surface |
| One live meter | see *the meter question* below | BLOCKED |

**The meter question.** The reference draws three ring gauges on the right
shoulder. They were built, then removed: three hardcoded fractions are shape
wearing the costume of data. Before they come back, three real 0–1 quantities
have to be named. Candidates that genuinely exist: memory headroom
(`HostPressure.memory_available_gb`), battery (`charge_percent`), interruption
budget consumed (`core/interruption.py`). All three are READY. **The choice of
which three is the owner's, not a default.**

## Hanging — 624 × 192 pt, on hover

Status row over an instrument panel on the `#03141f` ground.

### The six status columns

| # | Column | Source | Status |
|---|---|---|---|
| 1 | Fabric — segments | `contracts/policy/network_fabric.toml` | **LIVE** — 3 segments |
| 1a | Fabric — node count | no enrolment registry exists | BLOCKED — "3 nodes" in the reference is not producible |
| 1b | Fabric — temperature | `HostPressure.thermal` | **BLOCKED as degrees.** This platform reports a *level* (`nominal`/`fair`/`serious`), never °C. The reference's "41 °C" is an absent instrument, not a missing wire. Available as a level: READY |
| 2 | Verification | `verification/stress_placement.py` | **LIVE** — 160,000 assertions, with its age and a 24 h TTL |
| 3 | Today | host clock | **LIVE** (date). Agenda BLOCKED — no calendar binding |
| 4 | Thinking / autonomy | `core/autonomy.py` `AutonomyLoop` | READY — loop is not running |
| 5 | Approvals waiting | `core/authorize.py` `PolicyDecisionPoint` | READY — no PDP running |
| 6 | Next ambience | `core/scene.py` + `source/modes.json` | BLOCKED — the eleven modes exist; nothing *schedules* transitions |

### The instrument panel

The reference draws four widget families. None is wired; each needs its quantity
named before it is drawn.

| Widget | Plausible real source | Status |
|---|---|---|
| Three ring gauges | host pressure / battery / interruption budget | READY, unassigned |
| Horizontal bar list | `core/telemetry.py` `BudgetStat` per path | READY |
| Donut + stacked bars | `core/placement.py` — capability distribution across nodes | READY |
| World map with points | `core/fabric.py` segments + `core/devices.py` registry | READY — meaningful only once a second node enrols |

## Expanded — 624 × 280 pt, on click

Content sits **directly on the shell**, not on the `#03141f` ground — that panel
belongs to Hanging. Measured: the instruments reference carries 16,129 px of
`#03141f`, the presence reference carries none.

| Content | Source | Status |
|---|---|---|
| The face | `face_cloud.py` → Metal, 39,805 points | **LIVE** — fourteen behaviours, 5–7% CPU |
| Eye glow | reference has hot irises; cloud carries no eye grouping | READY — needs eye regions tagged in the extractor |
| Eight hologram panel anchors | §8 | READY — the anchors are decided, the contents are the table above |
| Spoken caption line | no audio / no dialogue path | BLOCKED |
| Thinking trace | `core/autonomy.py`; owner-routed to **summon** | READY |
| Self-modification suggestions | owner-routed: "also island when suggesting" | READY — `core/selfmod.py` |
| Partition state | owner-routed **to island** | READY — `core/fabric.py` |

## Owner-routed to the island, from the 237-item catalogue

Recorded because it is the owner's own placement and predates the island
references — it is not superseded by them, it is additional.

| Item | Owner's note |
|---|---|
| Partition state | *"more important: island dock or main menu, your call"* |
| Pause / resume | *"island dock, everywhere"* |
| Self-modification boundary | *"also island when suggesting"* |
| Deadline tracker | *"also main menu; island when getting close"* |
| Study progress | *"also main menu; island when on an actual course"* |
| Coursework · Coding · AI/ML workbench · Spaced repetition | *"also island and main menu"* |
| Alarms | *"floating summoned card or island dock"* |

Two of these describe a **conditional** island presence — "when getting close",
"when on an actual course". That is a trigger, not a layout, and it belongs in
`contracts/policy/trigger_registry.toml` rather than in a rendering rule.

## Producible today but in no reference and no routing

The backend already carries these. Listing them so the design conversation can
include things the references did not think to ask for.

| | Source |
|---|---|
| Thermal level, memory headroom, swap, battery, charge | `core/host.py` `HostPressure` |
| Task states and the action outbox | `core/tasks.py` |
| Interruption budget remaining | `core/interruption.py` |
| Cost ceiling and credential state | `core/cost.py` |
| Per-path latency budget vs measured | `core/telemetry.py`, `contracts/policy/latency_budgets.toml` |
| Placement decisions and survival state | `core/placement.py` |
| Lease holders | `core/lease.py` |
| World-model facts and their provenance | `core/world.py` |
| Claim/evidence support | `core/evidence.py` |
| Alarm readiness rungs | `core/alarm.py` — the 09:00 alarm has a readiness report |

`core/alarm.py`'s `ReadinessReport` is the most island-shaped of these: it is
exactly one live thing with a state that changes through the night, which is what
the Shoulders body row is for.

## What blocks what

Only three things block everything else:

1. **No running backend.** Five of the six columns are READY rather than LIVE for
   one reason — nothing is running to produce them. The island reads a file
   snapshot today; §7 of the architecture calls for a socket.
2. **No second node enrolled.** The fabric widgets are honest but dull with one
   node, and the world map is meaningless.
3. **No audio path.** Speaking — for the mark and for the face's caption — is
   amplitude-driven by decision, so it stays still until real audio exists.

None of them blocks *designing* any of the above.
