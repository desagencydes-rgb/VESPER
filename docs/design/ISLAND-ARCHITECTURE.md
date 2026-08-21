# The island — architecture

What the island is, what backs every pixel of it, how it behaves everywhere on
this Mac, and the order it gets built in. Geometry lives in
`ANNEX-island-geometry.md`; the references and their measurement live in
`ui-refs/`. This file is about behaviour and wiring.

## 1. The seat: the island is an endpoint, not a special case

The temptation is to build the island as a bespoke macOS thing with its own
data path. That would violate `INV-PLACE-3` on the first commit — VESPER is not
pinned to a machine, and a surface that reads the fabric through its own private
wiring makes this laptop the place VESPER lives.

`core/scene.py` already has the right seat. `SceneRenderer` renders a
`SemanticScene` against any `EndpointCapability`, and one of its declared spatial
classes is `pseudo_3d_glass` — which is precisely what the island is. So:

```
EndpointCapability(
    endpoint_id   = "island",
    spatial_class = "pseudo_3d_glass",
    modalities    = ("visual", "text"),
    max_elements  = 6,           # the six status columns; the body is one element
)
```

Everything the island shows is a `SemanticScene` that VESPER would have produced
anyway. The island renders it here; a headless node degrades the same scene to
`linear` and logs it; a phone-class endpoint takes `2d`. **No new data path, and
nothing on this laptop that another node cannot also receive.** The macOS-shaped
part is the presentation and nothing else.

This also gets the degradation story for free. `RenderResult.degradations` is
already required-even-when-empty (`INV-SCENE-2`), so an island that truncates six
columns to four reports it rather than silently dropping two.

## 2. The constraint that shapes everything: surviving OS updates

Owner: *"the island dock should be considered as a feature of the operating
system itself, and it should not be harmed by any [OS] update."*

Those two halves pull in opposite directions, and the resolution is the single
most important engineering decision here. **It must look like a system feature
and be built from nothing but public, stable API.** Anything that reaches for
the notch through a private interface — undocumented window levels, SkyLight,
a kernel extension, disabling SIP — buys the illusion at the cost of breaking on
an OS update, which is the one thing forbidden.

| Need | Built with | Stable because |
|---|---|---|
| A panel welded at y = 0 over the menu bar | `NSPanel`, `.nonactivatingPanel`, level `.statusBar + 1`, `collectionBehavior` `.canJoinAllSpaces` `.fullScreenAuxiliary` | ordinary public AppKit; the same thing every menu-bar utility does |
| Knowing the notch's real geometry | `NSScreen.safeAreaInsets` + `auxiliaryTopLeftArea` / `auxiliaryTopRightArea` | public since the notch shipped; reports the *actual* display, so a different Mac just works |
| Hiding the system Dock | `NSApplicationPresentationAutoHideDock` | the API fullscreen apps use; macOS reverts it when we stop being frontmost |
| Never occluding the menu bar's own items | we own only the notch band and grow downward | no API needed — a layout decision |

**No private API, no accessibility-API screen scraping, no injection. Ever.**
The rule is worth stating as an invariant candidate rather than a preference,
because the failure mode is silent: a private call keeps working for three OS
releases and then removes the island the morning after an update, with no
compile error and no test failure.

`NSScreen.safeAreaInsets` doing the work also means the 185 pt and 32 pt anchors
in the annex are *defaults to check against*, never constants to trust. A build
that hardcodes 185 is a build that is pinned to this laptop.

**Permissions.** The Dock swap is VESPER changing its own presentation, so it is
`self` tier in `contracts/policy/host_actions.toml` — full freedom, zero blast
radius, alongside `set_own_execution_class`. It is not a host mutation and takes
no per-instance approval. Nothing else the island does touches the host at all.

## 2b. Binding into the OS without becoming pinned to it

Owner, 2026-08-21: *"this is not a simple project any more, we're now binding
VESPER inside of the operating system itself and making them connected and
collaborating."*

Taken as a decision, and it makes §2's rule load-bearing rather than cautious.
Deep integration and "not harmed by any OS update" are only compatible on public,
supported surfaces — the deeper the binding, the more expensive one private call
becomes. The available surfaces are real and are enough: App Intents (which puts
VESPER in Shortcuts, Spotlight and Siri for free), Focus status, Notification
Center, the Services menu, Core Spotlight indexing, `SMAppService` for login
items, EventKit / Contacts / Photos under their normal permission prompts, and
the Accessibility API where the owner grants it. None of these is a hack and
none of them breaks on an update.

**The risk this creates is `INV-PLACE-3`, and it is the main one.** Integration
this deep is exactly how VESPER stops being a fabric and becomes "the thing that
lives on the MacBook". The invariant says a new node joins and wins placement on
merit; a capability that only exists as a macOS binding cannot be won by anything
else, and the fabric quietly becomes decoration around one laptop.

The guard is a shape, not a promise: **the capability is declared abstractly and
the macOS binding is an adapter behind it.** "Read the owner's calendar" is a
capability; EventKit is one implementation of it. "Announce" is a capability;
Notification Center is one implementation. A node with no calendar access
declares it cannot serve that capability and loses placement for it — which is
the fabric working, not failing. The day a decision path names EventKit
directly, VESPER is pinned, and `INV-HW-1` already refuses that shape of naming
in routing, resource and policy paths.

Practically, this means every OS binding lands as a pair: a capability entry the
fabric can reason about, and a host action in
`contracts/policy/host_actions.toml` at the right tier. Reads are `observe`.
Anything that changes the host is `adjust_reversible` or `destructive` and takes
the owner's approval per instance. The Dock swap is the one exception already
argued in §2, and it is `self` because VESPER is changing only itself.

## 2c. Staying alive — bundle, agents, persistence

Owner, 2026-08-21: it must run all the time, not stop suddenly, and start again
after a reboot.

**VESPER is an app bundle, and that is not cosmetic.** `app/VESPER.app`,
identifier `ai.vesper.island`, `LSUIElement` so it takes no Dock slot.
**TCC permission grants are keyed to app identity**: every permission granted
while this ran as a loose binary was granted to the *Terminal* that launched it,
appeared in System Settings as "Terminal", and would not have transferred when
the bundle arrived. Bundling early means grants accumulate against VESPER from
the first one rather than being re-asked for later.

Signed ad-hoc, which is a real limitation and is recorded rather than hidden: a
Developer ID certificate would hold TCC grants across rebuilds, and ad-hoc may
re-prompt when the binary changes.

**The login item lives inside the bundle, registered with `SMAppService`.**
`Contents/Library/LaunchAgents/ai.vesper.island.plist`, `RunAtLoad` +
`KeepAlive`, registered by the app itself on first launch.

The first attempt wrote LaunchAgents into `~/Library/LaunchAgents` pointing at
executables. It worked, and it looked wrong: macOS registers the **executable**,
so Login Items showed a generic `exec` icon labelled VESPER, and the projection
producer appeared beside it as a second, unrelated entry called `python3.13`.
From inside the bundle it is one entry, carrying the app's own name and mark.

For the same reason the projection is refreshed **by the island itself**, hourly,
rather than by a second agent — one background item instead of two, and no stray
interpreter in the owner's settings. It re-runs the 12 s placement stress only
when that reading is going stale; burning the host hourly to keep one column
fresh would be a strange way to treat a machine whose stated goal is to last
longer.

`--login-item-status` asks the system what it thinks, because an SMAppService
agent does not appear under its own label in `launchctl list` and its absence
there proves nothing. `--uninstall-login-item` removes it: an undo path, written
before the install path, because a login item you cannot remove is not a
convenience.

**State lives in `~/Library/Application Support/VESPER/`, not `/tmp`.** `/tmp` is
cleared on reboot, and an island that comes back from a restart with no columns
looks broken rather than empty.

**Verified, not assumed.** `launchctl` printing "loaded" is not evidence of
anything, and neither is `register()` returning without throwing. The status was
read back from the system (`login item: enabled`), and the island was killed with
`-9` and returned by launchd under a new pid with the panel back on screen.

Restart-after-reboot rests on `RunAtLoad` and has **not** been observed here. It
is the documented mechanism and the login item reports enabled, but nothing in
this session has actually rebooted this machine — so it is recorded as untested
rather than as working.

**This is a host mutation.** A login item is not the `self` tier the Dock swap
sits in: it survives VESPER not running, which is the entire point of it. It was
requested explicitly by the owner.

**Signed with a stable local identity**, created by
`tools/make_signing_cert.sh`: a self-signed code-signing certificate, trusted for
code signing only, in the login keychain. TCC keys its grants to a signature's
designated requirement, and ad-hoc signing has no stable one — so without this,
macOS can re-ask for every permission each time the binary changes. The app now
reports `valid on disk` and `satisfies its Designated Requirement`, with the
hardened runtime on.

**What that does not buy.** System Settings will still say "Item from unidentified
developer". Gatekeeper wants a **Developer ID** certificate — the paid Apple
Developer Program, $99/year — plus notarisation, and no local certificate
substitutes for it. That only matters for running VESPER on a Mac that is not the
owner's; for permissions persisting on this one, the self-signed identity is
sufficient and free. Ad-hoc remains the build's fallback so a fresh clone still
builds without the certificate.

Two traps worth recording, both of which present as something else. An
empty-password PKCS#12 fails to import as *"MAC verification failed (wrong
password?)"*, which sends you hunting for an algorithm mismatch that is not there
— macOS's `openssl` is LibreSSL and its defaults are already compatible. And
importing the certificate is not enough: `security find-identity -v -p
codesigning` still reports **zero**, because `-v` lists *valid* identities and an
untrusted self-signed certificate is not one.

## 3. The state machine

Five states, from `ANNEX-island-geometry.md`. Transitions are the existing motion
vocabulary — `--snappy` for growth and retreat, `--bouncy` for Alert's arrival —
and **no new animation may be invented** without the owner, per the standing
correction in `docs/design/README.md`.

```
                    ┌──────────┐
   nothing to say   │ DORMANT  │  185 × 32 — indistinguishable from the notch
                    └────┬─────┘
        something live   │   ▲  idle 8 s and nothing live
                    ┌────▼─────┴───┐
                    │  SHOULDERS   │  370 × 48 — the resting state
                    └────┬─────────┘
         hover / ⌘-click │   ▲  pointer leaves, or Esc
                    ┌────▼─────────┴──┐
                    │ EXPANDED at rest│  624 × 192 — instrument panel
                    └────┬────────────┘
           VESPER speaks │   ▲  utterance ends + 2 s
                    ┌────▼────────────┴┐
                    │ EXPANDED speaking│  624 × 280 — the face, one caption
                    └──────────────────┘

   ALERT  624 × 96 — interrupts from any state, returns to the one it interrupted
```

**Dormant is a real state, not "hidden".** The island is always mounted; dormant
means it is exactly the notch's silhouette and reads as hardware. Unmounting and
remounting would flicker on every transition and break the illusion that this is
a physical object.

**Alert never stacks.** One approval, or one thing that needs the owner, never
two — `contracts/policy/interruption_budget.toml` already governs the rate, and
the island must honour it rather than keeping its own queue.

## 4. The six status columns, and what actually backs each

The composite's columns are placeholders with plausible-looking values. Under
`INV-HW-2` a number is measured or it is `UNKNOWN`, and `UNKNOWN` means
unavailable — so each column binds to a real producer or it does not ship.

| Column | Composite showed | Real source | State when unknown |
|---|---|---|---|
| 1 | "Fabric quiet · 3 nodes 41 °C" | `core/fabric.py` segments + admissions; temperature from the host profile | node count always known; **temperature omitted entirely** if unmeasured, never zero |
| 2 | "320k assertions · placement stress" | last `verification/stress_placement.py` run | "not run" — never a stale count without its age |
| 3 | "Thu 21 · nothing for today" | `core/alarm.py`, `core/tasks.py` | empty day is a real answer and says so |
| 4 | "Thinking · gaze up-left" | `core/autonomy.py` loop state | idle is a real state |
| 5 | "2 approvals · waiting on you" | `core/authorize.py` pending decisions | zero is a real answer |
| 6 | "Rest at 23:40 · ambience shifts" | `core/scene.py` + the eleven modes in `source/modes.json` | next transition is always computable |

Two of these are worth calling out because the composite gets them subtly wrong
in a way that is easy to copy:

**Column 1's "41 °C" must not be faked.** `MEMORY.md` records that macOS metrics
need translation and that this platform's numbers are not the ones a Linux node
reports — `memorystatus_level` is a band, not a size. A temperature the host does
not actually expose is omitted; it is not filled with a plausible number because
the column looks empty without one. An empty column is the honest render.

**Column 2 is a measurement with an age.** "320k assertions" without "when" is
the failure `INV-HW-2` exists to prevent. The column carries its age or it
carries nothing.

## 5. Behaviour everywhere on the Mac

The island is not an app window and does not behave like one.

| Situation | Behaviour | Why |
|---|---|---|
| Any app frontmost | island stays, at `.statusBar + 1`, non-activating | it is presence, not a window; clicking it must never steal focus |
| Fullscreen app | island persists and stays black | in fullscreen the notch region goes black anyway — §10 — so the weld is free and the island simply keeps going |
| Mission Control / Spaces | joins all spaces | `.canJoinAllSpaces` `.fullScreenAuxiliary` |
| Menu bar auto-hides | island holds the notch band | we never occupy menu-bar item space, so there is nothing to fight |
| Screen locked / screensaver | island is not drawn | presence off the lock screen is a privacy decision, not a technical limit |
| Display sleep, then wake | returns to the state it held | dormant-on-wake would read as a crash |
| External display attached | island is on the **built-in** display only | no notch elsewhere; a floating pill on an external monitor is a different component and is not designed |
| Clamshell, external only | no island | same reason; the shoulders content moves nowhere and simply is not shown |
| Screen recording / screenshot | island is captured normally | hiding it would be the surprising behaviour |
| Inside VESPER's own workspace | Dock swap applies (§10) | `NSApplicationPresentationAutoHideDock`, `self` tier |
| VESPER backend not running | island shows Dormant, and nothing else | a surface that renders stale state is worse than one that renders none |

That last row is the one most likely to be got wrong. The island is a view of a
running system. When the system is not running, the honest render is the notch.

## 6. The face

Owner: *"the face should not be at all a simple image, but a whole interactive
fast 3d design, actively moving all the time non stop, so this is very big."*

Taken as a decision. `ui-refs/face-and-hologram-panels.jpg` is the **target it
must look like**, never an asset to composite. This is the largest single piece
of work the island implies and it is scoped as its own build phase, after the
island is real without it.

What is already decided and must not be re-litigated (§8): eyes lead the head by
80 ms — *"move them together and it reads as a turret"* — head yaw ±18°, pitch
±12°, eye range ±25° beyond the head, return to centre after 1.2 s idle, blink
every 3–7 s for 120 ms and never mid-sentence. Eight panel anchors, clockwise
from twelve.

What is not decided: how the point cloud is generated and rendered, its point
count, and its budget. Those are a spike, not a guess, and the spike has a hard
constraint the rest of the system imposes — this thing runs *continuously* on a
laptop whose stated goal is to stretch host lifetime. A presence layer that costs
15 W is a presence layer that loses the machine. **Its power draw is measured
before its point count is chosen.**

§8's refusal of the fiction stands and gets sharper now that the panel language
is confirmed. The reference carries `REASONING 110%`, `MEMORY ARCHIVE
241-F8-J-1000 PB`, and lorem-filled readouts. Every panel is backed by a live
reasoning stream, the real task graph, a real plan, or a measured number. There
is no filler panel and no decorative readout.

## 7. What has to exist in the backend first

The owner's instruction: build the backend across the whole Mac, not just the
island, *"so it's consistent, then little by little, other [surfaces] get
unblocked."* That is the right shape — every item here is a surface-agnostic
capability the island happens to be the first consumer of.

1. **A state projection.** One read-only snapshot of "what is true now",
   assembled from `fabric`, `authorize`, `tasks`, `alarm`, `autonomy`, `scene`.
   Every surface reads this; none reach into modules directly. Without it, six
   columns become six ad-hoc couplings and the home's 90 cards become ninety.
2. **A subscription with a real idempotency key.** `core/bus.py` *refuses*
   registration without one, by design. The island's key is the projection
   version, not `event_id`: it must render the latest state once, not every
   event once.
3. **A local transport.** The renderer is not in the Python process. Unix domain
   socket, newline-delimited JSON, snapshot-then-deltas.
4. **A latency budget.** `contracts/policy/latency_budgets.toml` has budgets per
   path and `measured = false` is the honest state today. The island needs its
   own path entry; a presence surface that lags its own system is worse than no
   presence surface.
5. **An endpoint registration**, so the island is a declared endpoint rather than
   an assumed one, and so a second endpoint is a config change.

## 8. Build order

Each step is watchable on screen before the next begins, and none of them
invents a number that `INV-HW-2` would refuse.

| # | Step | Done when |
|---|---|---|
| 1 | State projection + endpoint registration, headless | a test renders all six columns to `linear` with no island at all |
| 2 | The shell: `NSPanel`, welded, Dormant ↔ Shoulders, real `safeAreaInsets` | it survives a display change and a reboot, and reads as hardware |
| 3 | Transport + live columns | the six columns are true, and `UNKNOWN` renders as absent rather than as a number |
| 4 | Expanded at rest, the instrument panel | the body is real instruments on `#03141f`, no filler |
| 5 | Alert, and the interruption budget | one approval, never two, at the contract's rate |
| 6 | The Dock swap | `self` tier, reverts correctly when we stop being frontmost |
| 7 | The face — its own spike first, power measured before point count | it runs continuously without costing the machine |

Steps 1 and 3 are the ones that unblock every other surface. The home's 90 cards
read the same projection over the same transport; when the owner's home
references arrive, the work is presentation, not plumbing.

## 9. Open

Type sizes and weights, icon style, density (compact or comfortable), and the
instrument panel's internal layout. Language and RTL — Arabic or French would
change the shoulder row's mirroring and is not designed. Every surface that is
not the island still has no reference set.
