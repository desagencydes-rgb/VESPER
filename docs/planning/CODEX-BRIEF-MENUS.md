# Codex brief — the main menu, the expandable menu, and the rail

Rewritten 2026-09-07. **The first version of this brief was wrong** and the
owner caught it: it pointed at `DESIGN-FOUNDATION.md`, which mentions menus
twelve times in passing. The actual specification is a routed requirements
corpus of **237 items**, and **88 of them land on the
surfaces in this brief**. Do not design from the foundation document alone.

## 0. THE PROTOCOL — run these, they are not optional

The owner's words, 2026-09-07: *"what if codex breaks something? ... this
project is sensitive at this state ... a local backup untouched by codex in
case something happens, as well as codex should have it's backup but deletes it
after finishing ... make sure codex does the job, results working end to end,
and it does not break anything."*

**A BRIEF CANNOT ENFORCE ANY OF THAT, SO IT IS A TOOL.**
`tools/ops/codex_handoff.py` hashes every tracked file before you start and
names anything you changed outside the agreement afterwards. It is already
open. You do not run `--open`.

### Before you touch anything

```
mkdir -p /tmp/codex-vesper-backup && cp -R app docs core routing tools /tmp/codex-vesper-backup/
```

**Yours, outside the repo, and DELETE IT when you are done.** A copy of the
tree inside the tree is how a later session spends an hour editing the wrong
file — `--verify` fails if it finds one.

### Before you hand back — all three must pass

```
python3.13 tools/ops/codex_handoff.py --verify
```
Must print `IN SCOPE`. If it names a file, you changed something you were not
given. Revert it; do not argue it was necessary — say so in the handback and
let the owner decide.

```
python3.13 tools/ci/checks.py all
```
Must print `141/141`. **Not 140.** A gate you did not know about is still a
gate you broke.

```
app/VESPER.app/Contents/MacOS/VESPER --chrome-probe
```
Must show your surfaces rendered with real content. See §"Done means".

```
rm -rf /tmp/codex-vesper-backup
```

### If you break something

```
git -C /Users/macbook/Projects/VESPER reset --hard handoff/menus/<stamp>
```
The tag is printed by `--verify`. There is also a full tarball in
`~/VESPER-backups/`, outside the repo, for the case `.git` itself is lost.
**Say what happened.** A reverted mistake that was reported costs an hour; one
that was quietly fixed costs the next person a day.

---

## Read these, in this order

| Source | What it holds |
|---|---|
| `docs/design/routing/spec_raw.txt` | **The requirements.** 237 lines, `sec|name|INCLUDE|surface|note`. The `surface` column is the routing decision. `routed.json` is the same data as JSON. |
| `docs/design/HOME-ARCHITECTURE.md` §14.1b | The main menu as BUILT, and exactly what is still owed |
| `docs/design/HOME-ARCHITECTURE.md` §14.2 | The reference composition — the bar, the separate tile, and **the rail** |
| `docs/design/HOME-ARCHITECTURE.md` §10 | Behaviour everywhere on the Mac: the Dock swap, the 30% dim |
| `docs/design/DESIGN-FOUNDATION.md` §4, §5 | Glass tiers and the type stack. Tokens only — it does not specify menu CONTENT |

## THE ONE THING YOU MUST NOT DO

§14.1b, quoting the owner on 2026-08-24: *"only change is icons (we'll have to
define them, then get them or build them)."* The document's own answer:

> **The eight slots carry placeholder glyphs and are named, not drawn.**
> Inventing eight icons and shipping them as though they were decided is how a
> placeholder becomes a design nobody chose. **What is owed: eight icon
> meanings, then eight icons.**

**The eight meanings are the OWNER'S to choose, and they have not chosen yet.**
Do not pick them. Build the bar so that eight meanings can be dropped in, and
leave the placeholders until the owner names them. The candidates are the
`main`-routed items below — there are 17 of them for 8 slots, which is
precisely why it is a decision and not a derivation.

## The main menu — 17 candidates for 8 slots

Routed `main` in the spec. **The owner picks eight.**

- **Autonomy queue**
- **Action outbox** — you decide which menu
- **Emergency stop**
- **Verification state**
- **Live activity stream**
- **Work rate**
- **Grants**
- **Hardware access**
- **macOS permissions**
- **Panic revoke**
- **Per-app rules**
- **Grant templates**
- **Quiet-hours restrictions**
- **Import / export**
- **Modes**
- **Remote surfaces**
- **Follow-me** — could be requested from conversation

## The expandable menu — 51 items

Routed `menu`. This is the tile at the bar's right end, and §14.2 is explicit
that it is **separate** — "a ninth slot in the bar would not be that".

These are overwhelmingly *readings about the machine and the fabric*: memory,
power, thermals, storage, nodes, trust zones, placement. That shape is the
design brief. It is a panel of instrument readings, not a launcher.

- **Command palette**
- **Memory headroom**
- **Memory pressure band**
- **Compressor & swap**
- **Battery health** — with life calculation; simple algorithms that don't cost much
- **Charge policy**
- **Power draw**
- **Process energy**
- **Owner working set**
- **Storage & SSD**
- **Thermal history**
- **Fan & acoustics**
- **Display power**
- **Radio state**
- **Disk I/O rate**
- **Sleep & wake log**
- **Throttle events**
- **Ambient estimate**
- **Charging schedule**
- **Costing me now**
- **Maintenance actions**
- **Peripherals**
- **Before/after**
- **Node profiles**
- **Trust zones**
- **Network segments**
- **Attestation state**
- **Placement decisions**
- **Relocation history**
- **Survival profile**
- **Enrollment** — has its own summoned panel when clicked
- **Endpoints**
- **Control-plane lease**
- **Link quality**
- **Node comparison**
- **Blast radius**
- **Migration dry-run**
- **Clock skew**
- **Key & identity state**
- **Onboarding wizard**
- **Node roles**
- **Failover drill**
- **Compensation**
- **Retry policy**
- **Capability registry**
- **Governed surfaces**
- **Behaviour on / off this Mac**
- **Consent channel policy**
- **Approval history**
- **Degradation ladder**
- **Platform adapters**

## The rail — a SIXTH surface class, four buttons

§14.2: four circular glass buttons at the right edge, labelled OUTSIDE them:
**projects · research · history · settings**. Vertically centred.

It is not a widget (holds no reading), not a card (never dismissed), and not
the main menu (horizontal, at the Dock's position, holds actions). It is
persistent navigation into four destinations. The owner chose four, and two of
them are whole spaces — the rail is about **frequency**, not taxonomy.

## Everywhere-features that touch these surfaces — 20 items

Routed `float` and `island`. Not yours to build, but they land on or beside the
bar and the tile, so build so they can.

- **Island dock** — OWNER-ADDED. Most-used frontend access; editable in settings
- **Interactive session**
- **Annotation layer**
- **Window choreography**
- **Explain this** — an everywhere feature
- **Impact preview** — wherever the change would occur
- **Voice in** — everywhere
- **Voice out** — everywhere
- **Scene rendering** — available everywhere
- **Notifications**
- **Alarms** — floating summoned card or island dock
- **Handoff**
- **Barge-in** — literally everywhere; tied to conversation
- **Ambient status** — tied to conversation
- **Overlay HUD** — tied to conversation
- **Open proposals** — surfaces with voice; stored in home
- **Explain yourself** — everywhere; VESPER always talking unless stopped in settings or by the shutdown button
- **What are you unsure about?** — surfaces with talking; stored in home
- **Partition state** — more important: island dock or main menu, your call
- **Pause / resume** — island dock, everywhere

## The three constraints. Breaking any costs more than the work saves.

### 1. Stay inside the markers in `home.html`

Everything renders through one file and another session edits it too. Work only
between:

```
/* ==== MENU: codex owns everything between these markers ==== */
/* ==== /MENU ==== */
```

There is a pair in the CSS and a pair around the markup. Do not edit outside
them; do not reformat the file.

### 2. Never run `build.sh`

**Every build re-signs the bundle ad-hoc, and macOS keys TCC grants to the
signature.** A build silently revokes all six of the owner's grants —
microphone, speech recognition, calendar, reminders, accessibility, Apple
Events — each one a manual trip through System Settings. It has already
happened twice today.

You do not need it. `HomeChrome.template()` reads
`app/home-macos/chrome/home.html` from the repo FIRST, so markup and CSS land
on the next mount. Verify with:

```
app/VESPER.app/Contents/MacOS/VESPER --chrome-probe
```

which loads the page offscreen in a real WKWebView and prints the DOM back.

### 3. Never edit `HomeChrome.fallbackTemplate()`

It is GENERATED from `home.html` by `tools/sync_chrome_fallback.py`, and
`CI-065` compares them byte for byte. The other session regenerates it.

## Rules enforced mechanically

- **`textContent`, never `innerHTML`** for anything derived from `home.json`.
  `CI-127` parses for it; these strings carry a model's output.
- **Nothing may reach the terminal.** `CI-129` asserts no renderer can post to
  `vesperTerm`. Do not add one.
- Every list capped, every cap named.

## Design tokens — already decided, do not invent

- Dock tier: `blur(42px) saturate(200%)`, fill `.085`, radius `34`
- Ink `--ink: #f4e6dc`; secondary `.62`, tertiary `.34`
- `--face-body` only; never introduce a face
- Motion `cubic-bezier(.32,.72,0,1)`, 220–280 ms
- Slot hover is specified: `translateY(-6px) scale(1.06)`

## Done means — END TO END, and this is the part that changed

The owner, 2026-09-07: *"we are now fully building them end to end, not just
icons or designs of just some functionnalities in them, each built one should
be working end to end."*

**A rendered label is not a delivered item.** For every item you ship:

| | |
|---|---|
| **It has a real producer** | the value on screen came from something that measured it, this run |
| **It renders that value** | not a mock, not a placeholder number, not lorem |
| **Or it says UNAVAILABLE** | and says WHY, in a sentence |
| **Its action works** | if it does something, doing it has an observable effect |

**NEVER INVENT A READING. This is `INV-HW-2` and it is enforced.** A number
with no producer behind it is not a reading, and the absent case must not be
styled to look like the present case. `core/projection.py` already drops an
unavailable reading rather than rendering one — follow it.

This exact mistake cost this project a card. The HOST card read *"no producer —
run home_snapshot.py"* for weeks because the producer existed and nothing
called it, and the instruction printed on the card would have **overwritten
`home.json`** and deleted the face, the transcript and the workbench. See
`HOME-WORKBENCH.md` §9b.

**Producers that already exist — use them, do not write second ones:**

- `core/host_probes.py` — `power_source()`, `battery_ratio()`,
  `disk_free_ratio()`, `host_health()`, `audio_channels()`,
  `key_storage_class()`, `tcp_reachable()`, `device_profile()`
- `core/host.py` — the platform adapter. **Never read a raw platform number
  in shared logic**: `memorystatus_level` is a BAND on macOS, not a size, and a
  band meaning "healthy" on one host means "about to fail" on another. That is
  what `core/host.py` exists to prevent and there is a gate on it.
- `world.current_host` — carries the probed facts the runtime already holds
- `home.json` — the contract the page reads. **One poll, one register.** Do not
  add a second timer or a second state file.

**SHIP FEWER, FINISHED.** Eight items that read real values beat fifty-one
labels. Order them by what the owner can act on: power, thermal and memory
first — they change while they are being looked at. If an item has no producer
and writing one is out of scope, render it UNAVAILABLE with the reason and list
it in the handback as owed. That is an honest delivery; a fake number is not.

**Hand back:** the diff, the `--verify` output, the `checks.py all` line, the
`--chrome-probe` output showing real values, and a list of what you shipped
UNAVAILABLE and why. The other session regenerates the fallback and builds once
at the end.
