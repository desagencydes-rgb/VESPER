# Menus v2 — Phase 2 handback

The owner approved all 17 main-bar icons and a wider bar on 2026-09-07. Names
and exact catalogue descriptions appear on hover and keyboard focus. The brief
now carries that amendment above its historical eight-slot instructions.

## Delivered

- Seventeen enabled destinations, each opening its own named panel. The native
  DOM measures the bar at 1,151 CSS px; with the 64 px instruments tile and
  14 px gap, the row is 1,229 px. Narrow surfaces scroll instead of shrinking
  or dropping icons. No live app rebuild, re-sign, or deployment occurred.
- All 51 instruments are resolved by catalogue name. Real observations retain
  their source and age; missing, failed, unstamped, future-dated and expired
  readings show UNAVAILABLE and a specific reason. Expiry is checked even
  when identical pushes continue or the producer stops.
- Generic menu rows are appended to the runtime's original five keys. The
  handoff's transport claim was right, but its publisher still explicitly
  selected only five keys. The minimal change in `tools/ops/vesper_runtime.py`
  supplies references to actual runtime objects and appends the projection.
  Slow probes run in one background worker, outside the conversation thread.
- Command-K searches all 68 surfaces. Before/after retains a baseline, compares
  only later fresh observations from the same source, and records both raw
  values and observation times. It does not claim causation.
- The onboarding wizard prepares a validated, visibly NOT_ENROLLED request.
  It has no admission write path. Simulation helpers use the existing placement
  and survival algorithms with no bus and no mutations. Clock offsets retain
  their request/response uncertainty interval.

**A destination opening is not a claim that its native action exists.** The
existing bridge has no independent stop, revoke-all, memory-transfer, enrollment,
remote-surface, or policy-edit command. Those operations remain explicitly
UNAVAILABLE. The emergency-stop panel gives the existing native stop chord
(hold Globe/Fn + Control + Option + Command for 0.6 s) instead of using a
runtime-dependent imitation. No stop or failover drill was executed.

## What the real snapshot established

This run provided **19 available observations and 49 explicit absences** across
68 catalogue entries. Eighteen instrument readings reached the native DOM;
one additional available entry was the event-header stream in the main bar.
These are observation counts, not a claim that 19 full capabilities are complete.
Some entries expose a measured subset and state which requested facets are absent.
The local palette, comparison and request-preparation tools are tested separately.

| Bucket | Available observations | Unavailable in standalone snapshot |
|---|---:|---:|
| A | 12 | 14 |
| B | 7 | 21 |
| C | 0 | 6 |
| D | 0 | 8 |

The standalone command deliberately does not construct substitute runtime
registries. After integration, the publisher's real device, authorization,
reconciliation, executor, autonomy, verifier and workbench objects supply their
read-only projections. The unit suite exercised these readers against actual
core registry implementations in isolated fixtures; those fixtures are not
reported as live fabric evidence.

### Bucket A

Host capacity retention, cycles, daily charge extrema, reclaimable memory,
pressure band, compressor/swap, process RSS, governed surfaces, capability
requirements, segment classes, attestation flag and durable lease records have
readers. Live registries supply profiles, assignments, grants and rule-dependent
capabilities when attached. In-flight undo plans, effective fabric trust and
live enrollment are not inferred from adjacent data. No authorization, admission,
placement or self-modification decision logic was changed.

### Bucket B and demotions

Storage inventory, Bluetooth state, bounded power-log tail and OS performance
warnings have public probes. The I/O algorithm is tested against comparable
counter pairs and resets. On this host the enumerated drivers returned only
zero cumulative counters, so active-storage coverage is unverified and the
reading stays UNAVAILABLE; those zeros are not rendered as an idle system.
USB inventory can be unavailable when the public profiler returns no entries.

Measured watts are still unavailable for display, radio and peripheral
attribution; reported budgets and states are labelled as such. `Costing me now`
is demoted to unavailable power attribution: CPU/RSS are not energy. Link
quality needs enrollment measurements rather than an ad-hoc ping or socket
connect. Role, mode, template, per-app, quiet-hours and maintenance definitions
are absent and are not invented. No privileged power probe or workaround ran.

Battery capacity retention is a calculation over recorded raw/design counters,
not the OS health algorithm or a prediction of remaining years. Thermal history
retains raw battery-sensor samples until unit provenance is established; it
never labels them as CPU or ambient temperature. Daily maximum charge is not a
configured charge limit.

### Bucket C

Read-only blast-radius, survival-set, migration-candidate and comparison helpers
are implemented and tested, including the unmeasured-throughput refusal. They
require supplied enrolled placement profiles with effective fabric admission;
the current runtime does not instantiate that input path, so the corresponding
live panels remain UNAVAILABLE. Clock skew similarly requires an actual exchange
from another node. No mock profiles are inserted to produce attractive results.
Approval history reads only owner-approved `act.resumed` event headers from the
bounded active log tail; outbox confirmations and automatic elevation are not
owner approvals. This is not a full historical approval ledger, and withdrawal
still lacks a public operation. The wizard prepares a request, not an enrollment.

### Bucket D

All eight remain explicitly UNAVAILABLE. Owner decisions about location rules,
charging and consent channels remain separate. Failover drill authorization was
not implied by approval of the icons. Ambient, fan/acoustic and privileged power
attribution are not fabricated.

## Verification and integration

Executed from `/Users/macbook/VESPER-codex-menus`:

- `python3.13 verification/test_menu_projection.py`: **13 tests passed**.
- `--negative-control`: deliberately exposed unmeasured throughput; **one
  expected failure**, then green after restoring the real implementation.
- `--negative-control-zero-counters`: deliberately called unverified zero
  counters idle; **one expected failure**, then green after restoration.
- `verification/probe_menus.py`: the copied app's actual WKWebView confirmed
  17 enabled icons, 51 rows, all 17 exact hover descriptions, stale-value
  rejection, literal markup rendering, named destination opening, horizontal
  scrolling, palette filtering, NOT_ENROLLED request output and before/after delta.
  Live snapshots and deliberately synthetic adversarial fixtures are labelled
  separately. The harness never writes the owner's `home.json`.
- Both lints: **PASS, zero errors and warnings**. JavaScript syntax, catalogue
  equality and `git diff --check` also pass.
- `python3.13 tools/ci/checks.py all`: **141/142 checks passed**. The only failure
  is `chrome-template-renders`: the generated inline fallback is intentionally
  unchanged under §6 of the brief. This is an integration requirement, not a
  green result. No check was disabled or relaxed.

The primary session must review the worktree diff, merge the approved changes,
regenerate the fallback there once, and run the full suite. The pinned Python
runtime also needs the changed publisher and new menu files before its live
pushes can expose runtime-object data. Source edits alone do not update a
running pinned runtime. There is no Swift source change requiring a new build.

The source catalogue is `tools/menu_catalogue.json`; the exact same catalogue is
embedded in the template and checked for equality. Per-item recorded evidence
and source hashes are in `MENUS-v2-EVIDENCE.json`. Raw private event payloads,
process arguments, device serials and key material are excluded.

## Per-item disposition in the recorded standalone run

| Item | Bucket | Recorded disposition | Limit or absence |
|---|---|---|---|
| Action outbox | A | UNAVAILABLE | The live reconciliation registry is not attached to this publisher. |
| Autonomy queue | A | UNAVAILABLE | The live autonomy loop is not attached to this publisher. |
| Emergency stop | A | UNAVAILABLE | The native bridge exposes no independent stop command. In the existing app, hold Globe/Fn + Control + Option + Command for 0.6 seconds to stop VESPER; Globe three times starts it again. This panel cannot invoke that native stop. |
| Grants | A | UNAVAILABLE | The running policy decision point is not attached to this publisher. |
| Verification state | A | UNAVAILABLE | The live verifier is not attached to this publisher. |
| Follow-me | B | UNAVAILABLE | No relocation-to-interface transport is registered on this surface. |
| Grant templates | B | UNAVAILABLE | No owner-defined grant template collection or governed apply operation exists. |
| Hardware access | B | UNAVAILABLE | The native bridge publishes neither active capture sessions nor complete permission state. Device presence is not access consent. |
| Import / export | B | UNAVAILABLE | No portable memory transfer operation is exposed by the native bridge. Copying live database files would lose WAL records. |
| Live activity stream | B | 100 recent event headers | Latest 100 event headers from the active log segment. Archived segments and event payloads are excluded. |
| Modes | B | UNAVAILABLE | The existing permission mode does not define study, travel, low-power, or hands-off configurations. Those presets need governed definitions before they can be applied. |
| Panic revoke | B | UNAVAILABLE | The policy decision point has no public revoke-all operation, and the native bridge has no revoke command. |
| Per-app rules | B | UNAVAILABLE | No per-application policy collection or governed editor exists. |
| Quiet-hours restrictions | B | UNAVAILABLE | No owner-defined quiet-hours authorization policy exists. Alarm overrides must remain intact. |
| Remote surfaces | B | UNAVAILABLE | No enrolled endpoint inventory is attached to this publisher. |
| Work rate | B | UNAVAILABLE | No bounded runtime completion history has been supplied. |
| macOS permissions | B | UNAVAILABLE | Permission status is not exported by the native bridge. Querying permissions from a helper would report the helper’s identity, not the app’s. |
| Attestation state | A | false | Governed attestation flag, not a new network attestation. Full-host admission remains fail-closed while false. |
| Battery health | A | 83.78% raw/design · 191 cycles | Capacity retention = raw full capacity / design capacity × 100. This differs from the OS health algorithm. Remaining years UNAVAILABLE: a single sample cannot establish a degradation rate. |
| Capability registry | A | UNAVAILABLE | The running capability registry is not attached to this publisher. |
| Charge policy | A | charge 12% | DailyMinSoc and DailyMaxSoc are observed charge extrema, not configured charge limits. Configured limit and charging control UNAVAILABLE. |
| Compensation | A | UNAVAILABLE | The running executor’s compensator registry is not attached to this publisher. |
| Compressor & swap | A | 6.39 GiB compressed · 2.71 GiB swap | Resident compressor footprint and allocated swap. Neither is cumulative SSD wear. |
| Control-plane lease | A | 0 held domains | Durable holder records and fencing epochs. This reader does not renew or self-promote, and does not establish current quorum or lease freshness. |
| Degradation ladder | A | 13 capability requirements | Governed survival-core and optional-capability requirements in contract order; these are requirements, not measured node capacities. |
| Endpoints | A | UNAVAILABLE | The live device registry is not attached to this publisher. |
| Enrollment | A | UNAVAILABLE | No live enrollment registry is instantiated by this runtime. Discovery and admission cannot be performed by the display. |
| Governed surfaces | A | 9 governed surfaces | Runtime changes require owner review before merge; reviewer enforcement also depends on repository protection. |
| Key & identity state | A | UNAVAILABLE | No enrolled device key-storage profiles were supplied. Key material is never read by this panel. |
| Memory headroom | A | 3.47 GiB | Adapter estimate: free + inactive + speculative pages. Purgeable pages are not added again. |
| Memory pressure band | A | 44 | Kernel band only. Never multiplied by memory size or converted to gigabytes. |
| Network segments | A | 3 declared segment classes | Declared classes and trust ceilings; no addresses and no claim of observed link quality. |
| Node profiles | A | UNAVAILABLE | No live enrolled measured profiles were supplied. |
| Owner working set | A | 544 processes observed | Top 20 RSS values across host processes. Shared pages can be counted in multiple processes; this is not unique physical memory or energy attribution. |
| Placement decisions | A | UNAVAILABLE | No live placement assignment or decision history was supplied. |
| Platform adapters | A | DarwinAdapter | Signals are translated by the platform adapter. Errors are not nominal. |
| Survival profile | A | UNAVAILABLE | No enrolled placement profile with measured resource budgets was supplied. |
| Trust zones | A | UNAVAILABLE | No enrolled effective trust assignments were supplied. A key-storage ceiling alone is not an effective trust zone. |
| Before/after | B | UNAVAILABLE | Capture a fresh baseline and a later reading in this panel to compare them. |
| Command palette | B | Command-K · search all 68 surfaces | Opens the selected surface. It never sends terminal commands. |
| Costing me now | B | UNAVAILABLE | Public process CPU and RSS counters do not measure battery energy. Per-process power attribution requires privileged powermetrics. |
| Disk I/O rate | B | UNAVAILABLE | Two comparable storage-counter samples are needed before a rate can be measured. Probe: ValueError: first sample retained; waiting for the next sample |
| Display power | B | UNAVAILABLE | The public display inventory does not report measured display watts. Brightness alone cannot establish power cost. |
| Link quality | B | UNAVAILABLE | No enrollment-measured per-path latency, throughput, and reliability record is published. A TCP reachability check is not that measurement. |
| Maintenance actions | B | UNAVAILABLE | No maintenance schedule or last-completed action ledger has been configured. |
| Node roles | B | UNAVAILABLE | The live enrollment registry has not published role assignments. Availability classes are not roles. |
| Peripherals | B | UNAVAILABLE | No public peripheral inventory was returned. Probe: ValueError: no USB inventory was returned |
| Radio state | B | Bluetooth controller state | Wi-Fi power, radio watts, and wake attribution UNAVAILABLE. Controller state is not power cost; addresses and paired-device identities are omitted. |
| Relocation history | B | UNAVAILABLE | No placement events are available in the supplied bounded log tail. |
| Retry policy | B | UNAVAILABLE | The running reconciler’s retry policy could not be read. |
| Sleep & wake log | B | 1 recent power-log lines | OS log order, retained as received; no cross-node ordering is inferred. Limited to the latest 100 matching lines. |
| Storage & SSD | B | 345.86 GiB container free | APFS container free space; snapshot FreeSpace is not usable headroom. Missing TRIM and lifetime-write counters remain UNAVAILABLE. SMART is the OS-reported status, not a lifetime guarantee. |
| Thermal history | B | 1 raw battery-temperature samples | Latest 120 samples in this publisher session. Raw sensor units retained; Celsius conversion and ambient comparison UNAVAILABLE until the unit is verified. Not CPU temperature. |
| Throttle events | B | OS performance-warning report | Note: No thermal warning level has been recorded Note: No performance warning level has been recorded Note: No CPU power status has been recorded This is the OS recorded status, not a complete throttle timeline. Workload correlation UNAVAILABLE. |
| Approval history | C | UNAVAILABLE | No approval records are available in the supplied bounded audit tail. Withdrawal is unavailable without a revoke operation. |
| Blast radius | C | UNAVAILABLE | No enrolled placement profiles and assignments were supplied for simulation. |
| Clock skew | C | UNAVAILABLE | No bounded request/response clock observations from other nodes were supplied. Local timestamps alone cannot establish skew. |
| Migration dry-run | C | UNAVAILABLE | No enrolled placement profiles were supplied for simulation. |
| Node comparison | C | UNAVAILABLE | At least two enrolled measured node profiles are needed for comparison. |
| Onboarding wizard | C | UNAVAILABLE | The native bridge has no discovery, measurement, or admission command. The wizard can prepare a request but cannot enroll a node. |
| Ambient estimate | D | UNAVAILABLE | There is no ambient-temperature sensor. Battery temperature is not room temperature. |
| Behaviour on / off this Mac | D | UNAVAILABLE | The owner has not defined the location-dependent policy. No policy is inferred. |
| Charging schedule | D | UNAVAILABLE | The owner has not supplied a charging schedule, and no governed charging-control action is available. |
| Consent channel policy | D | UNAVAILABLE | The owner has not decided which approval tiers may use voice versus an explicit tap. |
| Failover drill | D | UNAVAILABLE | This action deliberately kills a node. Separate explicit owner authorization is required; icon approval does not authorize a drill. |
| Fan & acoustics | D | UNAVAILABLE | No supported public fan-speed or acoustic-power sensor is exposed to this publisher. |
| Power draw | D | UNAVAILABLE | Whole-machine compute-versus-other power attribution requires privileged powermetrics. No root-access workaround is attempted. |
| Process energy | D | UNAVAILABLE | Per-process power attribution requires privileged powermetrics tasks. CPU usage is not watts. |
