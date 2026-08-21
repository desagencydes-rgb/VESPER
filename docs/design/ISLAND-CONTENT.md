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

### The three gauges — decided 2026-08-21

Owner: *"show something needed more and that can't be found easily … it's just at
the top, easily accessible to me."* The island holds the most valuable strip of
screen on the machine, so a gauge spent on something the menu bar already shows is
a gauge wasted. Battery and the clock stay where they are.

These are the **three budgets VESPER spends on the owner's behalf**, and none of
them is visible anywhere else on this Mac.

| # | Gauge | Reads | Source | Status |
|---|---|---|---|---|
| 1 | **Attention** | interruption allowance consumed this hour | `core/interruption.py` + `contracts/policy/interruption_budget.toml` (8/hr focused, 24/hr available) | BLOCKED — no budget instance running to record spend |
| 2 | **Spend** | cost accrued against `[ceilings]` | `core/cost.py` + `contracts/policy/cost_policy.toml` | BLOCKED — no gateway running to accrue |
| 3 | **Machine** | memory pressure band | `core/host.py` `DarwinAdapter` | **LIVE** — reading 65% |

Attention, money, machine: what VESPER will cost you in each.

**The band is shown as pressure, which is what it is.** `MEMORY.md` records that
this platform's `memory_pressure_band` is a band and never a size, and that
multiplying it by total memory overstates headroom by gigabytes. Rendered as a
pressure gauge it is exactly itself, and needs no translation to be honest.

**Two of three render as absent, not as zero.** A ring resting at 0% because
nothing is tracking it is indistinguishable from a ring at 0% because nothing has
been spent, and those are opposite facts. So the shoulder shows one gauge today.

## Hanging — 624 × 192 pt, on hover

Status row over an instrument panel on the `#03141f` ground.

### The six status columns

| # | Column | Source | Status |
|---|---|---|---|
| 1 | Fabric — segments | `contracts/policy/network_fabric.toml` | **LIVE** — 3 segments |
| 1a | Fabric — node count | no enrolment registry exists | BLOCKED — "3 nodes" in the reference is not producible |
| 1b | Fabric — temperature | `core/host.py` `DarwinAdapter` | **BLOCKED as degrees, LIVE as a level.** The adapter works and reports `thermal='nominal'`, plus swap, battery and charge. It does not report °C and no backend work will make it — the reference's "41 °C" is an absent instrument, not an unwired one |
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

## When each thing appears — decided 2026-08-21

**ALWAYS** = unconditional in that state. **WHEN** = a trigger, and a trigger
belongs in `contracts/policy/trigger_registry.toml`, never in a rendering rule.

| Content | Dormant | Shoulders | Hanging | Expanded | Appears |
|---|:--:|:--:|:--:|:--:|---|
| The mark | — | ● | ● | ● | **ALWAYS** — §9, every state |
| Three gauges | — | ● | ● | ● | **ALWAYS** (each gauge individually absent without a producer) |
| Current task / mission | — | ● | ● | ● | WHEN a task is running |
| Six status columns | — | — | ● | ● | **ALWAYS** in Hanging and Expanded |
| Instrument panel | — | — | ● | — | **ALWAYS** in Hanging |
| The face | — | — | — | ● | **ALWAYS** in Expanded |
| Hologram panels | — | — | — | ● | WHEN the thing each describes is live |
| Caption line | — | — | — | ● | WHEN speaking — BLOCKED, no audio path |
| Thinking trace | — | — | — | ● | WHEN autonomy is reasoning |
| Self-modification suggestion | — | — | — | ● | WHEN a proposal is unreviewed |
| **Alert** | ◐ | ◐ | ◐ | ◐ | WHEN one approval waits. Interrupts **any** state and returns to it. Never two |
| Deadline | — | ◐ | ● | ● | WHEN "getting close" — threshold undefined |
| Study progress | — | ◐ | ● | ● | WHEN on an actual course |
| Alarm readiness | — | ◐ | ● | ● | WHEN an alarm is armed |
| Partition state | — | — | ● | ● | WHEN the fabric is partitioned |
| Pause / resume | — | ● | ● | ● | **ALWAYS** — owner: "island dock, everywhere" |

● shown · ◐ can pull the island into that state

**Two consequences worth stating.** *Pause/resume* being "everywhere" means it
cannot be an Expanded-only control; on Shoulders the mark itself is the target.
And *Alert* interrupts from **Dormant** too — an approval arriving while the
island is a bare notch must still surface, or Dormant becomes the place things go
missing.

**Three thresholds are the owner's and are not invented here:** how close is
"getting close" for a deadline, what counts as "on an actual course", and whether
Alert may interrupt during a Focus mode.
