# VESPER's home — architecture

What the home *is*, what macOS will and will not give it, how the same content
becomes a widget or a card or a window, how work chooses the layout, where the
face goes when the work needs the screen, and the order it gets built in.

Primitives — palette, glass, type, motion, the eleven ambience modes, the face
envelope — are decided in `DESIGN-FOUNDATION.md` and are not restated here. The
island is a separate surface with its own file, `ISLAND-ARCHITECTURE.md`; this
one is its sibling, not its parent. Card-by-card content lives in
`HOME-CONTENT.md`.

**Status.** The mechanisms below are decided and buildable. Three of them are
recorded as *documented but unverified on this machine* and say so where they
appear — the repo's standing rule is that a mechanism's own documentation is not
a reading from the world. Two are open spikes (`SPIKE-013`, `SPIKE-014`). The
owner's UI reference set still covers **the island only**; nothing here decides
what a card looks like, only what one is.

---

## 1. The home is a place, and the seat is already built

The temptation is to build the home as a big window with ninety views in it.
`core/projection.py` already refused that shape on the island's behalf and its
docstring names this surface by name: *"the island has six status columns; the
home has ninety cards. Six ad-hoc couplings would be survivable and ninety would
not."*

So the home takes the same seat the island took. Every surface is an
`EndpointCapability` over a `SemanticScene`, and the three new ones are sizes of
the same thing rather than three implementations:

```
EndpointCapability(endpoint_id="home",          spatial_class="pseudo_3d_glass", max_elements=64)
EndpointCapability(endpoint_id="card",          spatial_class="pseudo_3d_glass", max_elements=12)
EndpointCapability(endpoint_id="widget",        spatial_class="2d",              max_elements=3)
EndpointCapability(endpoint_id="widget-system", spatial_class="2d",              max_elements=3)
EndpointCapability(endpoint_id="window",        spatial_class="pseudo_3d_glass", max_elements=64)
```

**This is the load-bearing claim of the whole document.** A card is not a small
window and a widget is not a small card. They are the *same scene* rendered at
three element budgets, which is why the owner's "smaller versions of windows"
widget is a config line and not a second codebase, and why `RenderResult.
degradations` (`INV-SCENE-2`, required even when empty) already reports the cut
when a widget can only hold three of a card's twelve elements.

**What follows from it, and is worth stating so nobody re-litigates it later:**
promoting a card to a window, or pinning a card out to the desktop as a widget,
is a change of endpoint. Not a rewrite, not a variant component, not a `isSmall`
flag threaded through a view tree.

### 1.1 What renders it: two layers, one window

The home is **one window with two layers**, and the split follows the same
`INV-PLACE-3` argument that put the island in Swift and the home in Tauri.

| Layer | Holds | Built with | Why |
|---|---|---|---|
| **Field** (below) | the ambience ground, the face and its four tiers | Metal, in-process | `FaceRenderer.swift` already exists and already costs a measured 5–7% CPU at 39,805 points. A second implementation in WebGL would be a second face with a different power profile, and the host's lifetime is the product |
| **Chrome** (above) | widgets, cards, the main menu, every one of the 90 cards | the webview, transparent background | this is the portable half. It renders on a Linux node, a phone-class endpoint or a headless log without change, which is the whole reason the home is not native |

**The face does not move into the webview and the cards do not move into Metal.**
The dividing line is exactly the line between what is pinned to this display and
what is not — the same cut `ISLAND-ARCHITECTURE.md` made between the island and
everything else, one level down.

**The cost of the composite is unmeasured and is `SPIKE-013`.** A full-screen
transparent webview over a 60 fps Metal layer is not free, and on a laptop whose
stated goal is to stretch its own life, "not free" needs a number before it needs
a design. The spike names the three fallbacks in advance so the choice is not
made by whoever is holding the failing figure.

---

## 2. The Space — what macOS actually provides, checked rather than assumed

The owner: *"vesper's home is not just a window, it's a different workspace,
using what macos already provides with some additions to it."*

`ISLAND-ARCHITECTURE.md` §2 established the rule that governs every line below:
**public, stable API only — no private interface, no SkyLight, no injection,
ever.** The failure mode of breaking it is silent, and arrives the morning after
an OS update.

### 2.1 What was checked, and what it returned

| Question | How it was checked, 2026-08-22 | Answer |
|---|---|---|
| Is there a public API to create, name or enumerate a Space? | `grep` for `CGSSpace` / `SpaceID` / `ManagedDisplay` across the public CoreGraphics headers in the macOS 26.5 SDK | **No.** Zero hits |
| Can Accessibility read or set which Space a window is on? | `grep` for space attributes in `AXAttributeConstants.h` | **No.** `AXWindow`, `AXWindows`, position, size, minimised, fullscreen — no space attribute exists |
| What *can* an app say about its own window and Spaces? | `NSWindowCollectionBehavior` in `NSWindow.h` | `CanJoinAllSpaces`, `MoveToActiveSpace`, `Managed`, `Transient`, `Stationary`, `FullScreenPrimary/Auxiliary/None`, tiling |
| Does the toolchain here even build the SwiftUI/WidgetKit surfaces? | `swiftc -parse` against `WidgetKit`, `SwiftUI`, `WebKit`, `AppIntents` | **Yes** — all four resolve under Command Line Tools alone. There is no Xcode on this machine |

Two of those are negative results and they are the important ones. A negative
result checked is worth more than a positive one assumed, and both of these
would otherwise have been discovered in week three of the build.

### 2.2 The decision: the home is a ground window on a Desktop of its own

**Not a native-fullscreen window.** Native fullscreen would hand us a real Space
for free — and it is the wrong one. A fullscreen Space admits exactly two kinds
of foreign window: a `FullScreenAuxiliary` panel, and one Split View tile. The
owner's home is supposed to hold *windows of apps*, plural, arranged. A
fullscreen Space is a room with no doors.

`DESIGN-FOUNDATION.md` §10 already assumed the non-fullscreen mechanism without
naming it: the Dock swap is specified as `NSApplicationPresentationAutoHideDock`
*"while its window is frontmost"*, which is a thing a normal window does and a
thing a fullscreen window has no need to do.

So:

| Plane | What sits here | Construction |
|---|---|---|
| **Ground** | the home itself — ambience field, the face, widgets, the main menu | one window, screen-sized, `Managed`, level `normal − 1` |
| **Work** | app windows: VESPER's own, and the owner's | ordinary windows at `.normal` |
| **Float** | cards, dialogs, the annotation layer | `NSPanel`, `.floating`, non-activating |
| **Presence** | the island | `.statusBar + 1`, `canJoinAllSpaces` — above everything, already built |

**Level `normal − 1` is the whole trick and it is one integer.** A window below
the normal level can never rise above a normal window, even when it is clicked.
So clicking the home's background raises VESPER without burying the owner's
work, which is the behaviour a *place* has and a window does not. `Managed`
keeps it on one Desktop, participating in Mission Control like anything else.

*Documented, unverified here.* `Managed` is documented as the default at
`.normal` rather than as exclusive to it. The pairing of `Managed` with a
below-normal level is build step 1 and is verified by watching it, not by
reading this table.

### 2.3 What the owner does once, and why it cannot be automated

There is no public API to create a Desktop. Three one-time steps, and they are
onboarding rather than a limitation to be worked around:

1. Create a second Desktop in Mission Control.
2. Enable its switch shortcut in Keyboard → Shortcuts → Mission Control. The
   owner's own catalogue note already anticipated this: *"Ctrl+1 confirmed
   working; enable Desktop 2 once VESPER's Space exists."*
3. Grant Accessibility, once, to `VESPER.app`.

After that, `Global summon` and `Space switching` (both routed to `backend`)
post a `CGEvent` for the shortcut. That is the "some additions to it" the owner
asked for: macOS provides the Space, VESPER provides everything in it.

### 2.4 The one thing that cannot be done, and what replaces it

The owner: *"vesper can still act, see, read in any other workspace when I ask
it to, or when I leave it and tell it to keep working on it, then he can move
them to his workspace until I come back, then he puts them back to their old
places."*

**Moving a foreign window between Desktops has no public implementation.** §2.1
checked and it is not in AppKit and not in Accessibility. Reaching for it means
reaching for SkyLight, which is the one thing forbidden.

The replacement is not a smaller feature; it is a different mechanism for the
same outcome. **Re-open, never teleport.**

- VESPER keeps a **window ledger**: for each piece of work it is asked to carry,
  the application, the document (a file URL, a repository path, a web URL), the
  window frame, and whatever position-in-document the app exposes through
  Accessibility. Never a window id — those do not survive a relaunch and the
  ledger's whole job is to.
- To take work with it, VESPER opens that document on its own Desktop. A new
  window opens on the active Desktop; that part is free.
- To hand it back, VESPER closes its copy and re-opens on the owner's Desktop at
  the recorded frame.

**Declared as a capability, with the macOS binding as an adapter**, exactly as
`ISLAND-ARCHITECTURE.md` §2b requires so that `INV-PLACE-3` survives:

| Capability | Adapter | State |
|---|---|---|
| `arrange_work` — put this work where I can see it | `AXUIElement` position / size / raise, within one Desktop | available, needs Accessibility |
| `carry_work` — keep working on this while I am away | ledger + re-open | available |
| `relocate_window` — move *this window object* to another Desktop | none | **UNAVAILABLE.** No public implementation. Fail closed, report it, never approximate it |

The third row is written down rather than omitted because `INV-PLACE-3`'s whole
posture is that an excluded capability is *reported*, never silently dropped —
and because the day someone finds a private call that does it, this row is the
argument against using it.

### 2.5 The z-order law

One sentence, because everything above reduces to it: **ground never rises,
float never sinks, presence is always on top.** A card that can end up behind an
app window is a card the owner will lose; an app window that can end up behind
the ground is work the owner will think VESPER closed.

---

## 3. The five surface classes

The owner gave the rule and it is better than any rule derived from content:
*"Elements that stay there always will be shown as widgets… cards show up either
on demand via window pop up, or pop up cards."*

**Class is a function of residency, not of subject matter.**

| Class | Residency | Summoned by | Dismissed by | Elements | Leaves the home? |
|---|---|---|---|---|---|
| **Widget** | always resident | nothing — it is simply there | never | 3 | **yes** — system desktop, Notification Centre |
| **Card** | transient | the owner, VESPER, or a voice line | Esc, click-away, or its subject ending | 12 | as a floating panel, anywhere |
| **Window** | until closed | opening a document or a session | closing it | 64 | it *is* elsewhere — it lives in the Work plane |
| **Dialog** | until answered | VESPER needing the owner | answering | 1 | yes — every Space, above everything |
| **Island** | permanent | — | — | 6 | it is never anywhere else |

**One content model, three renderings, one mounted at a time.** The same
catalogue item may have a widget form, a card form and a window form. Exactly
one is mounted; pinning a card out to the desktop unmounts the card and mounts
the widget. Two live renderings of one subject is how two truths about the same
number end up on screen at once.

**Dialogs are already split and that split is not reopened here.**
`DESIGN-FOUNDATION.md` §10 decided which floating things stay dialogs (approval,
clarify, alert, capture) and which became cards (surfaces, backlog, history).

---

## 4. Widgets, and the honest limit of leaving home

The owner: *"just like every other widget on the MacBook, except these are
vesper's widgets, following ios26 theme, but with vesper's color theme, they
stay in vesper's home, can be added in other workspaces via the add widget
feature."*

That is **two different objects** with different physics, and pretending
otherwise would produce one of them badly.

| | In-home widget | System widget |
|---|---|---|
| Host | VESPER's ground plane | macOS, via a WidgetKit extension |
| Renderer | the home's own layer | SwiftUI only. No webview, no Metal |
| Motion | continuous, the full motion vocabulary | **none.** The system renders snapshots |
| Data | live over the transport | a timeline the system asks for and then caches |
| Refresh | as the projection changes | **a system budget**, not a choice |
| Interaction | full | `Button` / `Toggle` bound to an App Intent |
| Adaptive colour (§3 of the foundation) | full — it can sample its backdrop | **cannot sample the wallpaper.** Falls to the theme's static accent, marked unadapted, per the rule's own step 5 |

### The finding that has to be built against

**WidgetKit will render a four-hour-old number with no indication that it is
old, and that is its normal behaviour, not a failure.** This is the `41 °C`
column from the island's reference — a plausible number where there should be
an absence — except that here the OS is the author of the staleness rather than
a designer.

`core/projection.py` already has the instrument: a `Reading` carries `ttl_ms`
and goes `UNAVAILABLE` when it expires rather than going stale, *"because a
stale number renders identically to a fresh one and nobody can see the
difference."* The widget's timeline entry must carry `observed_at` and the view
must evaluate the TTL **at render time, not at timeline-build time**. A widget
whose freshness was decided when the entry was built is a widget that is
confidently wrong for as long as the system chooses to keep showing it.

→ **`INV-HOME-2` candidate: a widget renders its reading's age, or renders
nothing.**

### What is verified and what is not

Verified 2026-08-22: `WidgetKit`, `SwiftUI`, `AppIntents` and `WebKit` all parse
under `swiftc` with Command Line Tools and no Xcode, targeting macOS 26.

Not verified: whether a `.appex` **assembled by hand** — the way `build.sh`
assembles `VESPER.app` — registers with the widget system, and what the refresh
budget actually is on this machine. Both are `SPIKE-014`. Until it reports, the
in-home widget is buildable and the system widget is not designed against a
measured cadence.

---

## 5. Windows — the seven the owner named

| # | Owner's name | What it is on macOS | Status |
|---|---|---|---|
| 1 | Notes, handwriting font | VESPER's own note surface. See the type note below | frontend |
| 2 | VESPER's terminal | a PTY view VESPER owns. A command it *runs* is a host action at its tier — the view is not the authority | frontend + policy |
| 3 | Any other installed app | a foreign window in the Work plane, **arranged, never adopted** (§2.4) | needs Accessibility |
| 4 | Freeform | two things: Apple's Freeform is a foreign app (row 3); *"Freeform canvas"* is a home card and a VESPER window class | frontend |
| 5 | Previews — pdf, markdown, diagrams, images, video, web | `QLPreviewView` for documents, `WKWebView` for markup and web, the diagram renderer for workflows | frontend |
| 6 | VESPER's own browser | `WKWebView`, its own profile. **Not Safari, and that is a security decision** — see below | frontend + taint |
| 7 | Research space | not a window: a **stage** (§7), and the flagship one | frontend |

**The browser is where untrusted content enters the system**, and it is the only
one of the seven that changes VESPER's threat model. `core/taint.py` exists for
exactly this: what the browser renders is tainted, and tainted knowledge may not
drive a host action. The owner's own catalogue says it in the memory section's
note — *"knowledge that drives an action on your machine must be measured here,
never something VESPER read somewhere and believed."* The browser window is the
door that rule was written for, so the taint boundary is drawn at the window,
not somewhere downstream where it is easy to forget.

**The handwriting question, and it is a real conflict.** The owner asked for the
notes window in the handwriting font. `DESIGN-FOUNDATION.md` §5 — also
owner-given — says Learning Curve is *VESPER writing in the first person,
unprompted; never a system message, never a number, never anything the owner
asked for directly*. A whole notes surface in it breaks that rule, and it would
also be the least legible surface in the product at length.

Resolved narrowly, and flagged rather than decided: **the notes surface is the
one place the two rules meet, so it splits by author.** VESPER's own lines are
Learning Curve; the owner's typing is Aeonik. If the owner wants their own text
in the hand as well, that is an owner decision and it changes §5's rule rather
than making an exception to it.

---

## 6. Two axes: what VESPER is, and what the owner is doing

The owner listed nine *modes* and ten *types of work*. Treating those as one
list produces a ninety-cell table that nobody can hold, and hides the fact that
they answer different questions.

**The nine modes are the eleven, minus two.** The owner's list — Home, Idle,
Watch, Listening, Thinking, Flow, Speaking, Alert, Rest — is
`DESIGN-FOUNDATION.md` §7's eleven with `Working` and `Milestone` absent.
Nothing is being dropped: the eleven stand, and the two are the ones a list
written from memory would naturally omit, since one is the ordinary case and one
is rare and earned.

| Axis | Question it answers | It selects |
|---|---|---|
| **A — VESPER's state** | what is VESPER doing right now? | the ambience mode (11), the face behaviour (14), the island state (5), the mark's channel |
| **B — the owner's work** | what is the *owner* doing right now? | the stage (§7), the face's presence tier (§8), the permission posture, which widgets are resident |

They move independently and at different rates. VESPER can be Thinking while the
owner is Watching; the ambience shifts and the layout does not. **A stage never
changes because VESPER changed state, and ambience never changes because the
owner opened a paper.** Conflating them produces an interface that rearranges
itself while you are reading, which is the single most common way an ambient
interface becomes unusable.

---

## 7. Stages — one layout per kind of work

A **stage** is a named arrangement, and it is data, not code:

```
Stage = {
  grid            how the ground is divided
  resident        which widgets are mounted
  slots           where windows land, and how many
  face_tier       §8
  ambience        the default mode; axis A may override it, the stage may not
  enter / exit    which spring, and what animates
}
```

**A stage never invents content.** It arranges what the projection has. This is
the rule that keeps ten layouts from becoming ten opportunities to draw a
plausible number, and it is the same rule `tools/island_snapshot.py` already
enforces by writing three columns instead of six.

| # | Work | Stage | Face | Windows | What is resident |
|---|---|---|---|---|---|
| 1 | **Research** | subject right, freeform left | **dispersed** | 2, fixed | reading queue, citations, context budget |
| 2 | **Coding / building** | editor centre, terminal below, review right | attendant | 3 + foreign | repo state, code review, experiments |
| 3 | **Analysis** | data centre, notebook right | dispersed | 2 | dataset browser, run comparison, metrics |
| 4 | **Study** | material right, notes + cards left | dispersed | 2 | deadlines, study progress, spaced repetition |
| 5 | **Design** | canvas full, references floating | **absent** | 1 + palettes | none — the canvas is the surface |
| 6 | **Prototyping** | canvas left, preview right, terminal below | attendant | 3 | improvement backlog, experiments |
| 7 | **Watching** | content full-bleed | **absent** | 1 | none. The island carries presence |
| 8 | **Resting** | ambience only | centre, still | 0 | nothing that can interrupt |
| 9 | **Improving itself** | proposals right, diff left, checks below | attendant | 3 | build state, invariants, self-mod boundary |
| 10 | **Free work** | the owner's own arrangement, remembered | attendant | any | whatever was pinned |
| — | **Home** (no work) | the face, the rooms, the input line | **centre** | 0 | the frame's eight cards |

Stage 9 is not decoration: `Self-modification boundary`, `Open proposals`,
`Build state`, `Invariants` and `Coverage map` are all already in the owner's
catalogue, and VESPER working on itself in front of the owner is what
`core/selfmod.py`'s proposal-never-merge posture is *for*.

### 7.1 The research stage, in full

The owner described this one twice, and it is the one to build first because it
exercises every mechanism in this document at once.

> *"got an interesting research paper you might want to look at, tell me if
> you'd like me to break it down to you"* — and on the owner's word, the paper
> takes the right side and a freeform card takes the left.

| | |
|---|---|
| **Entry** | the owner says *break it down*, or opens a paper from the reading queue, or drops a PDF on the ground |
| **Right half** | the subject: `QLPreviewView` for a PDF, `WKWebView` for a page. Scroll position is ledgered (§2.4) so the stage can be left and resumed |
| **Left half** | the freeform canvas: VESPER's notes and the owner's, diagrams, workflows, tables, images, video, further sources, equations, arrows, drawing by either of them |
| **The face** | **disperses** on entry (§8). The screen belongs to the work |
| **Ambience** | `Working` by default; axis A overrides while VESPER thinks or speaks |
| **VESPER's hand** | margin notes on the left half are Learning Curve — this is precisely the *"VESPER writing in the first person, unprompted"* case §5 of the foundation reserves it for |
| **Exit** | the session is saved as a `Session replay` (already a home card), which is what makes *"re-open a past interactive session exactly as it was arranged"* buildable rather than aspirational |

**Both halves are the same freeform surface with different content**, which is
why the left one can hold a preview and the right one can be drawn on. Two
different canvas implementations either side of a divider is how the arrows stop
working across the middle.

---

## 8. The face's claim on the screen — the presence law

The owner: *"vesper's space is not supposed to always show his face… for some
use cases where we need big screen and things taking most of the space, face can
get smaller or disappear behind, or dissolve (particles disperse)."*

**The face's claim is inverse to the work's claim.** Four tiers, chosen by the
stage:

| Tier | What is on screen | Cost | When |
|---|---|---|---|
| **Centre** | the head, the eight panel anchors, the full behaviour set | the measured 5–7% CPU / 59 MB baseline | Home, Rest, conversation, wake |
| **Attendant** | the head at a corner anchor, same envelope, reduced amplitude | less — fewer visible points, same timer | work the owner does *with* VESPER |
| **Dispersed** | the point cloud with the head's attractor released. The points become the ambience field the widgets sit in | **must be ≤ Centre. Pre-registered, measured in `SPIKE-013`** | research, study, analysis — reading and thinking work |
| **Absent** | no face, **no timer**, no points. The island's mark carries presence alone | zero | watching, design, focus mode, battery critical |

**The dissolve is the second addition to the motion vocabulary**, owner-given
2026-08-22. `docs/design/README.md`'s standing correction says the four springs
plus the Dock falloff are the whole vocabulary until the owner adds to it; the
mark's four state motions were the first addition, and this is the second.

**It is a release, not a fade.** The same 39,805-point cloud that
`FaceRenderer.swift` already draws, with the attractor that holds the head shape
turned off; the points drift to a low-energy field and stay there, alive. A
cross-fade to a different asset would be a new asset, a second renderer, and a
visible cut where the owner asked for a dispersal.

**Three rules that come straight from decisions already made:**

- **The stage owns the tier, and a behaviour may not raise its own.** Identical
  in shape to §8 of the foundation: *"a behaviour chooses where to look and how
  urgently. It may not change the envelope."* An `acting` behaviour in a
  dispersed stage is dispersed and urgent, not re-materialised.
- **Absent runs no timer**, for the same reason the mark's idle state runs none:
  the stated goal is to stretch this host's lifetime, and a cloud that animates
  to say nothing spends the battery to say nothing.
- **One face at a time.** The island renders a face in Expanded-speaking. If the
  home holds the face at Centre or Attendant, the island stays at Shoulders and
  does not draw one. Two faces of the same entity on one screen is not presence,
  it is a bug with a budget.

**Dispersed must be cheaper than Centre, and that is a requirement rather than
an expectation.** It is easy to build a particle field that costs more than the
head it replaced — more points visible, no culling, no attractor to keep the
work bounded. Pre-registering the reading before the result exists is the
`A-029-E1` pattern, and it is the reason this sentence is here and not in a
retrospective.

---

## 9. What has to exist behind it

`ISLAND-ARCHITECTURE.md` §7 lists five things and every one of them is shared.
The home adds five more, and **none of them is macOS-shaped** — that is the test
of whether the seat in §1 was taken properly.

1. **Endpoint registration** for `home`, `card`, `widget`, `widget-system`,
   `window`. A sixth endpoint should be a config change, and if it is not, §1 is
   not true yet.
2. **A stage store** — which stage is current, what is pinned, what the owner
   rearranged. `~/Library/Application Support/VESPER/`, never `/tmp`: the island
   already learned that a surface that comes back from a reboot empty looks
   broken rather than clean.
3. **The window ledger** (§2.4) — app, document, frame, position-in-document.
   Never a window id.
4. **Latency budget entries.** `contracts/policy/latency_budgets.toml` is a
   governed surface and gains paths, not values, in a separate reviewed act:
   `card_open_visible`, `stage_switch_settled`, `widget_timeline_build`. The
   catalogue's own note on window choreography — *"must be fast or it feels
   broken"* — is a budget waiting to be written down, and `INV-PERF-1` says it
   is written **before** it is measured.
5. **Host actions**, likewise proposed here and landed there separately:

| Action | Tier | Why |
|---|---|---|
| `autohide_own_dock` | `self` | VESPER changing its own presentation. Already argued in the foundation §10 |
| `arrange_window` | `adjust_reversible` | moves another app's window. Reversible — the ledger holds the old frame, which is what makes it reversible rather than merely undoable-in-principle |
| `open_document` | `adjust_reversible` | opens work on a Desktop |
| `switch_desktop` | `adjust_reversible` | changes what the *owner* is looking at. It is not `self`: VESPER is moving the owner's view, not its own |

The last row is the one worth arguing about, and the argument is the point. A
`self`-tier reading of "VESPER switches to its own Desktop" is available and
wrong: the owner's screen is not VESPER's own presentation.

---

## 10. Behaviour everywhere on the Mac

| Situation | Behaviour | Why |
|---|---|---|
| Home Desktop active, VESPER frontmost | full home. Dock auto-hidden, main menu in its position | the foundation's dock swap, `self` tier |
| Home Desktop active, a work window frontmost | ground stays put and stays behind. Cards remain on the Float plane | ground never rises (§2.5) |
| Another Desktop active | **the home renders nothing** — `NSWindowOcclusionState` says it is not visible | a full-screen 60 fps surface nobody can see is the clearest possible waste of the host's life |
| A fullscreen app on another Desktop | unchanged. The island rides along; the home does not follow | the home is a place, and a place does not chase you |
| Display sleep, then wake | the stage it held, the tier it held | same rule the island uses: dormant-on-wake reads as a crash |
| Screen locked | not drawn | privacy decision, same as the island |
| External display attached | the home moves to the display the owner puts it on; the island stays built-in | there is no notch elsewhere; the ground has no such constraint |
| Clamshell, external only | home yes, island no | the island's rule, unchanged |
| `prefers-reduced-transparency` | every glass tier collapses to opaque | the foundation §4. A system that claims to collaborate with its host does not override its accessibility choices |
| `prefers-reduced-motion` | springs become cuts; the face holds its tier and stops moving; dispersed becomes a still field | as above. Note the face **does not fall back to Absent** — losing presence is not what the setting asked for |
| Battery critical | face → Absent, ambience → still, widgets → longest TTL | the lifetime goal is the product, not a mode of it |
| VESPER's backend not running | the ground draws, the ambience runs, **every card reports UNAVAILABLE** | the island's hardest-won row. A surface that renders stale state is worse than one that renders none — and unlike the island, the home has something honest to draw without it |

---

## 11. Build order

The owner: *"we'll try to build what we can build just frontend (or frontend
with easy backend with it), then build stuff that require backend."* That is the
right split and it maps cleanly onto what already exists.

`docs/design/source/home_rooms.py` derives the split from the owner's own
catalogue rather than from an estimate:

```
HOME CARDS  90
  P  producer exists in core/, needs the projection only    26
  B  needs a producer that does not run yet                 64
```

### Phase F — frontend only, no backend at all

Nothing here reads a producer. Everything is watchable on screen.

| # | Step | Done when |
|---|---|---|
| F1 | The three planes: ground at `normal − 1` `Managed`, work, float. Desktop residency | a foreign window sits above the ground and the ground cannot be raised over it. **This verifies §2.2** |
| F2 | Ambience field + the eleven modes + theme + the adaptive rule | the ground is alive and correct in light, dark and auto, with the hysteresis damping in (§3 of the foundation — the step that is easy to leave out) |
| F3 | Face tiers: Centre, Attendant, Dispersed, Absent, and the dissolve | the four tiers switch on `--smooth`, and Absent runs no timer. Gated on `SPIKE-013` for the cost pre-registration |
| F4 | The stage engine + the twelve stages, as data | every stage enters and leaves, and every card in every stage renders its **UNAVAILABLE** state, because there is no producer yet |
| F5 | Chrome: widget, card and window frames; main menu; density; shortcut map | the same fixture scene renders at 3, 12 and 64 elements and reports its degradations |
| F6 | The research stage end to end, with a real PDF and a real canvas | the owner can say *break it down*, get two halves, draw across both, and reopen it tomorrow |

**The rule that makes Phase F safe: a fixture must be visibly a fixture.** The
whole `INV-HW-2` culture leaks the moment a demo number renders in the same
style as a measured one. `core/projection.py` makes the honest version
unconstructible — a `Reading` cannot hold a value without provenance — so
fixtures do not enter the projection at all. They are a separate source with its
own render, and it does not look like data.

### Phase P — frontend plus the projection that already exists

26 cards whose producers are in `core/` today, plus the transport the island
already needs. Nothing new in the backend; this is binding work.

### Phase B — needs a producer that does not run yet

64 cards, each waiting on a named thing: the autonomy loop running, a policy
decision point holding pending approvals, a cost gateway accruing, an
interruption-budget instance recording spend, a calendar binding, a media
binding, an ambience scheduler. `HOME-CONTENT.md` carries the per-card list;
`ISLAND-CONTENT.md` already carries the same accounting for six columns and the
shape is identical.

---

## 12. Invariant candidates

Candidates, not invariants. `spec/invariants/INVARIANTS.toml` requires an
`enforced_by`, and *"a statement with no enforced_by is not an invariant; it is
a wish."* Enacting one is a separate reviewed act.

| Candidate | Statement | The failure it prevents | What would detect it |
|---|---|---|---|
| `INV-HOME-1` | No surface reaches a runtime module. Every widget, card and window reads the projection | ninety couplings, each with its own idea of what unknown looks like | a check that no home surface imports from `core/` except `projection` |
| `INV-HOME-2` | A widget renders its reading's age, or renders nothing | WidgetKit showing a four-hour-old number confidently (§4) | a render test at `now + ttl + 1` |
| `INV-HOME-3` | The stage owns the face's presence tier; no behaviour may raise its own | `acting` re-materialising the face over the owner's work | property test over behaviour × stage |
| `INV-HOME-4` | The home renders nothing while occluded | a 60 fps surface nobody can see, on a host whose lifetime is the product | occlusion transition test with a frame counter |
| `INV-HOME-5` | No surface uses private API | the island's silent failure mode, on a bigger surface | a symbol scan of the built binary |

`INV-HOME-5` generalises what `ISLAND-ARCHITECTURE.md` §2 already calls an
invariant candidate. It belongs to surfaces, not to the island.

---

## 13. Open — not specified here

**Blocking the visual language, and unchanged since the foundation:** there is
no UI reference set for the home. `ui-refs/` covers the island only. Nothing in
this file decides what a card *looks* like — only what one is, what backs it,
and where it may appear.

**Open questions this document raises and does not answer:**

- Does the owner want their own typing in the hand as well (§5)?
- Grid units for the ground. The island got a measured geometry annex; the home
  has no reference to measure.
- Whether a stage may be authored by the owner, or only chosen. "Free work"
  assumes the former and nothing else does.
- What a widget does when its card is open — mirror, defer, or dim.
- Multi-monitor: which display the ground claims when two are attached, and
  whether stages are per-display.
- The main menu's contents. 51 items routed to `menu` and this file does not
  lay them out.

**Waiting on a measurement:** `SPIKE-013` (the ground's composite and its power
cost) and `SPIKE-014` (a widget extension without Xcode, and its real refresh
budget). Neither blocks Phase F beyond the two steps that name them.
