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

---

## Codex handback — 2026-09-07

**The frontend slice is implemented. End-to-end live host instrumentation is
NOT accepted yet.** The current state channel carries one host row, `power`,
and that row failed an independent freshness check: the page and `home.json`
said `battery`, while `pmset -g batt` said `Now drawing from 'AC Power'`.
The row has no observation timestamp or expiry. Repeated delivery of the same
file is not evidence of repeated measurement.

### What is implemented

- The separate instrument tile is a real button opening a native modal dialog.
  Eight bounded rows disclose their source or missing measurement. The source
  row explicitly says **“Power source · last report”** and the always-visible
  introduction says **“Freshness UNAVAILABLE: the reported source may be stale.”**
  It must not be counted as a verified current power reading.
- The rail has four circular glass buttons with labels outside. History opens
  a searchable view of the supplied conversation, capped at 60 entries and
  6,000 characters per entry, with truncation disclosed. This is conversation
  history, not the still-owed full action/decision audit space.
- Projects, research and settings open explicit UNAVAILABLE destinations with
  reasons. There are no pretend project-opening actions or settings saves.
- Eight main-menu glyphs remain placeholders. Their buttons are disabled and
  have accessible “meaning not chosen” labels. No owner meanings were selected.
- Native dialog focus containment/cancellation, a close button, backdrop
  dismissal and focus return; responsive sizing; reduced motion/transparency
  rules; the existing body face and glass tiers.
- The menu wraps the existing `__vesperMetrics` and `__vesperHistory` receivers
  after DOMContentLoaded, forwards every push to the original receivers, and
  renders only changed data. It adds no poll, fetch, state file or terminal
  bridge. Model-derived text is written with `textContent`.

### Unavailable / still owed

| Surface | What is missing |
|---|---|
| Current power source | Observation time/expiry and a reliably refreshed producer. The last report is displayed with freshness explicitly unavailable. |
| Power draw | No measured wattage reaches this renderer. |
| Battery charge | `core/host_probes.py::battery_ratio` exists, but no charge row is delivered here. |
| Battery health / lifetime | No health/lifetime measurement reaches this renderer. Charge percentage is not health. |
| Thermal pressure | `core/host.py` has the platform adapter; its thermal result is not projected here. Thermal history is still owed separately. |
| Memory headroom | The adapter's available-memory reading is not projected here. |
| Memory pressure band | The adapter's band is not projected here; it must never be converted into a memory size. |
| Compressor & swap | No compressor measurement or adapter swap reading reaches this renderer. |
| Projects / research | No collection or opening action is connected to these rail destinations. |
| Settings | No settings reader/save action is connected. |
| Full history space | Only conversation history is delivered; action/decision/audit logs are not connected. |
| Remaining routed menu items | Deliberately not built as a long list of inert labels. |

Connecting the existing host adapter and probes to a timestamped, expiring
projection in the SAME `home.json` register requires work outside this slice.
The current native bridge only forwards the existing metric rows, so adding
fields elsewhere in the file alone would not deliver them to this menu.
Do not call `home_snapshot.py --probe` or manufacture rows to make the probe
green. Do not describe a JSON-to-DOM test as proof of current physical state.

### Verification and integration notes

- WebKit layout instrument: **25/25 assertions at each of 1728×1117,
  1280×800, 760×600 and 430×740 (100/100)**. Tests used a temporary template
  populated from the real register, then explicit test fixtures for updates,
  missing/malformed data and inert model text. The fixtures never touched
  the live register. Checked dialog bounds, all four destinations, rail/dock
  bounds, clearing absent power, preservation of expanded rows, history
  search, bounded entries and text, and undecided slots.
- Additional WebKit focus tests: **8/8**. Close returns focus and clears
  expanded state; a history update preserves search focus; native dialog
  cancellation closes and returns focus; a queued close event cannot reset a
  reopened dialog; unchanged pushes preserve selectable text nodes; backdrop
  dismissal restores focus. These exercise WebKit's native `requestClose`
  path, not a physical keyboard press in the live home.
- Offscreen WebKit screenshots inspected at desktop and narrow sizes. The
  temporary screenshot harness was compiled in `/tmp`; no VESPER bundle was
  built, signed or modified by Codex. This validates layout, not the Metal
  composite or a live Desktop mount.
- The required app `--chrome-probe` ran successfully and reported
  `metricRows: ["power=battery"]`, `fits: true`. Its fixed readback does not
  include the new menu selectors. The separate layout instrument supplies
  those assertions. The battery/AC mismatch above means this output is NOT
  evidence of a fresh host reading.
- First complete `checks.py all`: **140/141**, solely
  `chrome-template-renders` / CI-065 (generated fallback differs). All other
  checks passed. A final run is recorded below when complete.
- Own source edits are confined to the two MENU regions in `home.html` and
  this handback. The rest of the HTML was compared byte-for-byte against the
  pre-edit backup. No core, bridge, guard, test-registry or fallback edits
  were made by Codex.

**Concurrent integration matters:** while Codex was testing, commit `7558aa8`
incorporated the first menu version and `cb891f2` updated the generated
fallback. Codex made neither commit. Therefore a plain `git diff` only shows
subsequent refinements. To inspect the whole menu slice, use:

```sh
git diff handoff/menus/20260907T031948 -- app/home-macos/chrome/home.html
```

The guard also changed concurrently. It now checks **uncommitted changes
against HEAD**, rather than comparing protected files to the frozen hashes.
Its `IN SCOPE` output does not prove that committed files are unchanged, or
attribute a change to an agent. It still does not enforce the MENU markers or
check `/tmp/codex-vesper-backup`; those were checked separately.

**Claude integration required:** regenerate the fallback from the FINAL
HTML, rerun `checks.py all` to obtain an actual 141/141, then perform the
single owner-authorized final build/mount. Codex has left CI-065 visible,
not bypassed it or changed its expectation. The producer/freshness work above
is separately required before calling these live host instruments finished.

Final scope and cleanup readback:

```text
PASS: byte-identical outside MENU markers
PASS: agent backup removed
handoff menus, opened 20260907T031948
  IN SCOPE: no uncommitted change outside the agreement.
Final app probe: {"fits": true, "metricRows": ["power=battery"]}
```

Review artifacts (temporary, local only):

- `/tmp/vesper-menu-handoff.patch` — complete HTML diff from the handoff tag.
- `/tmp/vesper-menu-tests.json` — named WebKit assertions and viewport results.
- `/tmp/vesper-menu-final-ui.txt` — the four 25/25 summaries.
- `/tmp/vesper-menu-final-chrome-probe.txt` — unabridged app probe output.
- `/tmp/vesper-menu-final-scope.txt` — final guard output.
- `/tmp/vesper-menu-final-checks.txt` — final full-suite output.

The owner's archive and handoff manifest were not modified by Codex. The
handoff remains open for Claude's integration. `/tmp/codex-vesper-backup` was
removed and its absence re-read; cleanup is not inferred from the guard.

Final complete-suite result (after the menu refinements):

```text
[FAIL] chrome-template-renders
  ERROR: the inline fallback does not match app/home-macos/chrome/home.html.
140/141 checks passed
```

The final targeted CI-065 rerun also fails for the same reason; no other full
suite check failed. **141/141 has not been achieved and is not claimed.**
Commit `e432d1f`, made concurrently by the other session, incorporated the final
HTML refinements and the first portion of this report. Both current MENU
regions were re-compared with the tested preview and match. Codex created no
commits. The remaining changes in this brief are the final evidence above.

**Final concurrent-work caveat:** after the clean scope readback above, new
uncommitted edits appeared in `tools/island_snapshot.py` and
`tools/ops/vesper_runtime.py`. The latest `--verify` therefore reports both as
CHANGED and exits 1. Codex did not edit either file; they appeared after its
full suite completed. They were left intact, not reverted to make the guard
green. This exposes the remaining attribution limit of the HEAD-based guard:
ongoing uncommitted work from the other session is still reported as though it
belonged to this slice. The integration owner must reconcile/commit that work
and rerun scope verification. The earlier clean scope output is historical,
not a claim that the concurrently changing working tree is still clean.
