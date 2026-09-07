# Codex brief v2 — build the main bar and the expandable panel, all 68, end to end

> **Owner amendment, 2026-09-07:** All 17 main-bar icons and the wider bar are approved, with name + exact description on hover. This supersedes every eight-slot selection instruction below. Phase 2 is authorized for 17 main items + 51 instruments. Bucket D decisions and destructive-drill authorization remain separate.

Supersedes `docs/planning/CODEX-BRIEF-MENUS.md`. That brief's read of the spec
(237 items, 17 `main`, 51 `menu`) still stands and is not repeated here except
as the table below. Three things changed since it was written, all owner
instructions, 2026-09-07 evening:

1. **The scope is now all 68, working end to end — not "ship fewer, finished."**
   The old brief hedged toward a small shipped subset. That hedge is gone.
2. **A visual approval step comes first.** Codex proposes an icon + name +
   hover label for each of the 17 main-bar candidates. The owner approves 8
   before any of them are wired.
3. **The isolation is physical now, not a shared file with markers.** Codex
   works in its own git worktree — a separate directory, its own branch,
   sharing this repo's history and nothing else. `tools/ops/codex_handoff.py`
   does not apply to this handoff; §3 explains what replaced it and why.

## 0. What was verified before this brief was written, and what it settled

Four things were checked against the running repo rather than assumed, because
the last handoff's problems were tooling assumptions, not codex's work:

- **The metrics bridge is generic already.** `home.json`'s `rows` key is an
  arbitrary `[{label, value, at_ms, ttl_ms}]` list — not a fixed schema.
  `HomeChrome.metricRows()` (Swift, mount-time) and `window.__vesperMetrics`
  (JS, live push) both render whatever rows are present. `tools/home_snapshot.py`
  already builds this list from `Reading` objects
  (`core/projection.py`) and calls `HomeState.set_rows()`
  (`core/home_state.py`), which merges rather than clobbers other writers.
  **Conclusion: delivering a new reading needs zero Swift changes and zero
  build**, for any item whose value can be computed in Python and added to
  `tools/home_snapshot.py`'s row list.
- **The one thing that IS hardcoded is inside your own markers.** The
  expandable panel's `renderInstruments()` (`home.html`, inside
  `MENU`) currently iterates a fixed 8-entry `definitions` array instead of
  rendering whatever labels arrive. That is JS you own and can rewrite — see
  §5, step 1. It is not a build-gated problem, it just looks like one.
- **`--probe-shot` is broken, not just unproven, and not a worktree artifact.**
  Tested both in the primary tree and in a scratch worktree: it hangs
  indefinitely and writes no file, identically in both. The likely cause is in
  its own header comment (`ChromeProbe.swift` line 163): a snapshot API gated
  on a TCC grant this Mac does not currently hold, failing by hanging rather
  than by erroring. **Do not build the icon-approval step around it.** §4
  names what to build instead. `--chrome-probe` (DOM readback, no screenshot)
  and `--probe-menu`/`--probe-expand` were exercised successfully in the same
  test and are fine to use for verification.
- **`checks.py all`, both lints, and `sync_chrome_fallback.py` all run clean
  from inside a worktree.** No `.git`-as-file breakage in any of them. Ground
  truth at handoff time: **142/142**, `chrome-template-renders` passing (the
  fallback is currently in sync — you are not starting behind).

## 1. The protocol — physical isolation, not shared markers

```
~/VESPER-codex-menus/          <- your worktree. A real, separate checkout.
  (branch: codex/menus-v2)
```

This is set up before you are handed this brief — you do not run `git worktree
add` yourself. Work **only** inside that directory. Never touch
`/Users/macbook/Projects/VESPER` (the primary tree) — you have no reason to
and no path there is yours.

**Commit your own work, as often as you want, on your own branch.** Nobody
else writes to this branch. There is no marker convention to observe and no
shared file to collide on — the whole repo, every file, is yours inside that
directory.

**`tools/ops/codex_handoff.py` does not apply here and you do not run it.**
It compares uncommitted changes in a shared tree against HEAD; in a worktree
model your changes are committed, on a different branch, in a different
directory, and that tool would report `IN SCOPE` forever whether or not it
was true. Physical separation is the boundary now. Integration and review
happen the ordinary way: the primary session runs
`git diff feat/macos-host-profile...codex/menus-v2` from
`/Users/macbook/Projects/VESPER` — it can do this without ever entering your
worktree, because a worktree shares the repo's object store.

**Your worktree already has a built, launchable `app/VESPER.app`** (copied in,
since the bundle is gitignored and a fresh worktree would not otherwise have
one). Use it to verify. **Do not run `app/island-macos/build.sh`** — you do
not need to (see §0: template and CSS changes need no build at all) and there
is a real footgun if you do: `build.sh` resolves its target from its OWN file
path, not from your current directory. Run *your worktree's own copy* by a
path inside your worktree and it can only ever touch your worktree's own app
— but an absolute path into `/Users/macbook/Projects/VESPER` would rebuild
and re-sign the OWNER'S LIVE APP and silently revoke all six of their TCC
grants, a mistake that has already cost a manual System Settings trip twice
this project. There is no reason to invoke it either way. Don't.

**If anything in your worktree goes wrong, it cannot reach the primary
tree.** The whole directory is disposable — worst case, it gets deleted and
recreated from the last good commit. You do not need a separate backup
mechanism inside it; the worktree itself is the backup boundary.

## 2. What "end to end" means — same standard as v1, restated because it decides everything below

| | |
|---|---|
| **It has a real producer** | the value on screen came from something that measured it, this run |
| **It renders that value** | not a mock, not a placeholder number, not lorem |
| **Or it says UNAVAILABLE** | and says WHY, in a sentence |
| **Its action works** | if it does something, doing it has an observable effect |

**A correctly-rendered, correctly-reasoned UNAVAILABLE is a finished item, not
a shortfall.** Several of the 68 below are permanently in that state — see
bucket D. "All 68 working end to end" does not mean 68 live numbers; it means
68 items each honestly resolved, whichever way the evidence goes. Inventing a
number to avoid saying UNAVAILABLE is the one failure mode this project has a
named invariant against (`INV-HW-2`) and it is checked.

**Every row you add needs `at_ms` and `ttl_ms`.** This is not new — it's the
bug the last handoff found in the primary session's own code (§9o of
`HOME-WORKBENCH.md`): a row with no observation timestamp looks current
forever, even after the producer that made it has stopped running. Copy the
pattern already in `tools/home_snapshot.py`'s `power_source()`, don't
reinvent it.

## 3. The workflow — two phases, and the second does not start without the owner

### Phase 1 — propose, don't wire

Build a **self-contained standalone HTML page** — no app launch, no build, no
TCC, opens in any browser — showing all **17** main-bar candidates from the
table below, each with:

- an icon you design for it (SVG, inline, matching the dock-tier glass tokens
  already decided — blur 42px / saturate 200% / fill .085 / radius 34, ink
  `#f4e6dc`, motion `cubic-bezier(.32,.72,0,1)`)
- its name
- a real hover tooltip using that item's **exact `what` text from the table
  below** — not a paraphrase, the owner should see their own catalogue's words

Nothing in this page is wired to `home.html`, `home.json`, or any producer.
It is a proposal surface, clearly labeled as one. Put it at
`docs/planning/codex-menu-icons-proposal.html` in your worktree and say so in
your first handback message.

**Stop here and report back.** The owner picks 8 of the 17 (and may ask for
icon changes). You do not choose, and you do not proceed to Phase 2 until
that answer comes back. This is the same rule v1 had — *"the eight meanings
are the owner's to choose"* — just delivered as something they can actually
look at instead of a bare list.

### Phase 2 — wire the approved 8, build all 51, in bucket order

1. **First, fix `renderInstruments()`.** Rewrite the panel's fixed 8-entry
   `definitions` array (inside your `MENU` markers) into a generic renderer:
   iterate whatever rows `home.json` actually delivers, look each one up
   against the 51-item catalogue below for its display text and its
   UNAVAILABLE reason, and render only what's real. This one change is what
   lets every later step actually reach the screen.
2. Wire the 8 approved main-bar items into the placeholder slots.
3. Work the 51 expandable items in bucket order — **A before B before C**,
   and treat **D as a decision to report, not a producer to chase** (see the
   table). Bucket A is entirely reading already-live `core/` state
   (`fabric.py`, `placement.py`, `enrollment.py`, `devices.py`, `lease.py`,
   `capability.py`, `selfmod.py`, `host.py`, `host_probes.py`,
   `executor.py`) into a `Reading` and appending it to
   `tools/home_snapshot.py`'s row list — read-only consumption of modules
   that already compute this data for their own reasons, never a change to
   their logic. That boundary is a quality one, not a physical one — a diff
   that stays inside `home.html`, `tools/home_snapshot.py`, and small new
   files under `core/host_probes.py` is one the primary session can review
   and merge quickly; a diff that edits `authorize.py`'s decision logic is
   not, no matter how isolated the worktree is.

## 4. The full catalogue — what was routed where, and the bucket that decides build order

Source: `docs/design/routing/spec_raw.txt` (your own export, 237 items,
committed `84cc71e`). Bucket assigned this session against verified `core/`
evidence — grep hits are named per item where relevant, not asserted from
memory.

- **A · projection-only** — a live `core/` module already computes this;
  wiring is read + `Reading` + append. Cheapest, do first.
- **B · needs a new probe** — no existing module, but a plausible public OS
  command exists (`pmset`, `diskutil`, `ioreg`, `system_profiler`, `log
  show`). Confirm the exact command works **before** committing to shipping
  it live; if it turns out to need root or a private API, it demotes to D and
  should be reported as such, not forced.
- **C · needs new core logic** — not a reading at all, but a simulation,
  comparison, or log that has to be built from scratch (blast radius,
  migration dry-run, onboarding wizard...). Real engineering, budget time
  accordingly.
- **D · UNAVAILABLE or owner decision first** — `powermetrics` per-process
  and whole-machine wattage need root on this OS; there is no ambient-temperature
  sensor to read; `Behaviour on / off this Mac` and `Consent channel policy`
  are owner policy calls, not producers; `Failover drill` deliberately kills a
  node and should not be auto-built without an explicit go-ahead given what it
  does. **Ship these as UNAVAILABLE with the specific reason from this table.
  Do not spend time trying to route around root access or invent a sensor.**

### Main bar — 17 candidates for 8 slots

| Item | Bucket | What it is | Source | Note |
|---|---|---|---|---|
| **Action outbox** | A · projection-only | Every external side effect, durably recorded before it happens, with reconciliation state. | `INV-EXT ×2` | you decide which menu |
| **Autonomy queue** | A · projection-only | What VESPER intends to do unprompted, before it does it. | `autonomy · INV-AUTO ×5` |  |
| **Emergency stop** | A · projection-only | Halt everything. Independent of the thing it stops, by design. | `INV-STOP ×7` |  |
| **Grants** | A · projection-only | Standing permissions, their scope, and their expiry. | `grant.schema` |  |
| **Verification state** | A · projection-only | What's been verified, what's asserted, and the refusal to let repetition count as success. | `verify` |  |
| **Follow-me** | B · needs a new probe | The interface moving with VESPER as it relocates. | `survival core` | could be requested from conversation |
| **Grant templates** | B · needs a new probe | Reusable permission sets — 'study mode', 'travel mode', 'hands off'. | `—` |  |
| **Hardware access** | B · needs a new probe | Camera, microphone, screen, files — what's granted, what's in use, and a capture indicator that can't lie. | `INV-PRIV ×5` |  |
| **Import / export** | B · needs a new probe | Take your memory with you, or seed it from somewhere else. | `—` |  |
| **Live activity stream** | B · needs a new probe | A running narration of what VESPER is doing, at a granularity you set. | `telemetry` |  |
| **Modes** | B · needs a new probe | Study / travel / low-power / hands-off — whole configurations you switch between. | `—` |  |
| **Panic revoke** | B · needs a new probe | Drop every standing grant at once, without stopping VESPER. | `—` |  |
| **Per-app rules** | B · needs a new probe | What VESPER may touch in each application, separately. | `—` |  |
| **Quiet-hours restrictions** | B · needs a new probe | Narrower permissions at night than during the day. | `—` |  |
| **Remote surfaces** | B · needs a new probe | Reaching VESPER from a phone or another machine. | `devices` |  |
| **Work rate** | B · needs a new probe | Throughput over time — is VESPER actually getting things done. | `—` |  |
| **macOS permissions** | B · needs a new probe | Accessibility, Screen Recording, Automation — what's granted, what's needed for which feature, and why. | `TCC` |  |

### Expandable panel — 51 readings

| Item | Bucket | What it is | Source | Note |
|---|---|---|---|---|
| **Attestation state** | A · projection-only | Whether a VESPER-controlled segment exists and is attested. Today: false, so no node is a full host. | `INV-NET ×3` |  |
| **Battery health** | A · projection-only | Capacity, cycles, temperature history, daily charge range. The numbers that decide the ten-year question. | `AppleSmartBattery` | with life calculation; simple algorithms that don't cost much |
| **Capability registry** | A · projection-only | Every capability, its level, and the constants that are refused outright. | `INV-AUTH ×8` |  |
| **Charge policy** | A · projection-only | Charge limit state, and whether the machine is sitting at high charge — the mechanism that aged this pack to 84% in a shop. | `DailyMaxSoc` |  |
| **Compensation** | A · projection-only | What each in-flight action would undo if it fails partway. | `executor` |  |
| **Compressor & swap** | A · projection-only | How hard the compressor is working, and whether swap has turned on. Swap is the SSD-wear tripwire. | `vm.swapusage` |  |
| **Control-plane lease** | A · projection-only | Which node holds control, its fencing token, and its refusal to self-promote. | `lease` |  |
| **Degradation ladder** | A · projection-only | What VESPER gives up first when it must give something up. | `degradation_ladder` |  |
| **Endpoints** | A · projection-only | Every surface VESPER can reach you through, as profiles rather than device names. | `devices` |  |
| **Enrollment** | A · projection-only | Admit a new machine, measure it, and watch it earn placement on merit. | `enrollment` | has its own summoned panel when clicked |
| **Governed surfaces** | A · projection-only | Which files require review, and who reviews them. | `governed_surfaces` |  |
| **Key & identity state** | A · projection-only | Each node's keys, where they're stored, and which never leave the device. | `key_storage_class` |  |
| **Memory headroom** | A · projection-only | Real reclaimable memory, translated — not the alarming 'free' figure that reads 0.16 GB on a healthy machine. | `vm_stat` |  |
| **Memory pressure band** | A · projection-only | The kernel's own signal, shown as a band. Never converted to gigabytes — it doesn't track allocation. | `kern.memorystatus_level` |  |
| **Network segments** | A · projection-only | Private / shared / outside, each with its trust ceiling. No addresses, no product names. | `network_fabric` |  |
| **Node profiles** | A · projection-only | What each machine measurably sustains. UNKNOWN means unavailable, and shows as such. | `INV-HW-2` |  |
| **Owner working set** | A · projection-only | What's resident right now, so a headroom number is interpretable rather than just a figure. | `SPIKE-001 §3.2` |  |
| **Placement decisions** | A · projection-only | Where each capability currently runs and why it was placed there, including what lost. | `DF-PLACE` |  |
| **Platform adapters** | A · projection-only | Per-platform translation of host signals. The knowledge lives in the adapter, never in shared logic. | `core/host.py` |  |
| **Survival profile** | A · projection-only | What VESPER carries onto the last device standing, and what it drops. | `DF-SURVIVAL-PROFILE` |  |
| **Trust zones** | A · projection-only | Z0–Z3 per node, with the reason each landed where it did. | `INV-TRUST ×2` |  |
| **Before/after** | B · needs a new probe | Measure a change you made and show whether it actually helped. | `—` |  |
| **Command palette** | B · needs a new probe | Keyboard-first access to every surface in this document. | `—` |  |
| **Costing me now** | B · needs a new probe | Live ranked list of what is draining the battery this minute. | `—` |  |
| **Disk I/O rate** | B · needs a new probe | Live read/write throughput, and cumulative writes against SSD endurance. | `—` |  |
| **Display power** | B · needs a new probe | Brightness and its real cost. The display dominates idle drain, so this is a bigger lever than CPU. | `—` |  |
| **Link quality** | B · needs a new probe | Latency, throughput and reliability per path — measured at enrollment, never declared. | `INV-HW-2` |  |
| **Maintenance actions** | B · needs a new probe | Things worth doing occasionally, surfaced when they're due rather than remembered. | `—` |  |
| **Node roles** | B · needs a new probe | What each machine is FOR — always-on server, travelling laptop, phone endpoint. | `—` |  |
| **Peripherals** | B · needs a new probe | What's plugged in, what it draws, and what it keeps awake. | `—` |  |
| **Radio state** | B · needs a new probe | Wi-Fi and Bluetooth power cost, and what's keeping them awake. | `—` |  |
| **Relocation history** | B · needs a new probe | When VESPER moved, what triggered it, and the damping that stopped it flapping. | `INV-PLACE-2` |  |
| **Retry policy** | B · needs a new probe | What VESPER does when something fails, per task class. | `reconcile` |  |
| **Sleep & wake log** | B · needs a new probe | Every sleep, wake, and what woke it. Where mystery battery drain gets explained. | `—` |  |
| **Storage & SSD** | B · needs a new probe | Free space, TRIM, SMART, and cumulative write pressure. | `diskutil` |  |
| **Thermal history** | B · needs a new probe | Temperature over time against ambient — the variable that matters most in site B heat. | `—` |  |
| **Throttle events** | B · needs a new probe | When the machine actually throttled, and what was running. | `—` |  |
| **Approval history** | C · needs new core logic | Everything you've ever approved, and the chance to withdraw any of it. | `—` |  |
| **Blast radius** | C · needs new core logic | What breaks if a given node dies — simulated before it happens. | `—` |  |
| **Clock skew** | C · needs new core logic | How far apart the nodes' clocks are — and the reminder that HLC, not wall clock, decides order. | `INV-COORD-4` |  |
| **Migration dry-run** | C · needs new core logic | Move VESPER somewhere, in simulation, and see what degrades. | `—` |  |
| **Node comparison** | C · needs new core logic | Two machines side by side on every measured axis. | `—` |  |
| **Onboarding wizard** | C · needs new core logic | Walk a new machine from nothing to enrolled and measured. | `—` |  |
| **Ambient estimate** | D · UNAVAILABLE or owner decision first | Inferred room temperature — the ceiling the battery can never get below. | `—` |  |
| **Behaviour on / off this Mac** | D · UNAVAILABLE or owner decision first | Different rules when VESPER is here versus running on another node. | `—` |  |
| **Charging schedule** | D · UNAVAILABLE or owner decision first | When to charge, given your day, to minimise time at high state of charge. | `—` |  |
| **Consent channel policy** | D · UNAVAILABLE or owner decision first | Which tiers may be approved by voice and which need a tap you make yourself. | `INV-ALARM-2` |  |
| **Failover drill** | D · UNAVAILABLE or owner decision first | Deliberately kill a node and prove recovery works. A negative control for the fabric. | `—` |  |
| **Fan & acoustics** | D · UNAVAILABLE or owner decision first | Fan speed and noise — heat you can hear before you can measure it. | `—` |  |
| **Power draw** | D · UNAVAILABLE or owner decision first | Whole-machine watts split into compute vs everything else. Compute is 8% at idle — the split is the insight. | `powermetrics` |  |
| **Process energy** | D · UNAVAILABLE or owner decision first | Per-process power attribution — who is actually costing you battery, ranked. | `powermetrics tasks` |  |

## 5. Rules enforced mechanically — unchanged from v1, still checked

- **`textContent`, never `innerHTML`** for anything derived from `home.json`.
  These strings can carry a model's output.
- **Nothing may reach the terminal.** `CI-129` asserts no renderer can post to
  `vesperTerm`.
- **Never edit `HomeChrome.fallbackTemplate()`.** It's generated by
  `tools/sync_chrome_fallback.py` and `CI-065` compares byte-for-byte. The
  primary session regenerates it at integration — see §6.
- Every list capped, every cap named.
- Design tokens are already decided (dock glass, ink, motion curve above) —
  don't invent new ones.

## 6. Handback

Report, per phase:

- **Phase 1:** the proposal page's path, a one-line description of your icon
  choices, and that it's unwired.
- **Phase 2, once the 8 are approved:** what you shipped in each bucket, what
  you demoted from B to D and why, the full `checks.py all` line **from your
  worktree**, and the `--chrome-probe` output showing real rows. Do not
  regenerate the fallback — that stays with the primary session, same reason
  as v1 (`CI-065` would be comparing your worktree's copy against itself).

**Your worktree commits are the deliverable.** The primary session reviews
`git diff feat/macos-host-profile...codex/menus-v2`, merges what's ready,
regenerates the fallback once, runs `checks.py all` in the primary tree, and
does the one owner-authorized build if a build ever turns out to be needed
(current answer: no template/CSS change needs one). You are not rewritten —
you are merged.

