# VESPER — open work, problems and constraints

**This is the active place.** One document for what is broken, what is unfinished,
what is not solved, what is hard, and what cannot be changed. Every session reads
it before starting and updates it before stopping.

**Updated:** 2026-11-08, 19:30.

## How this document is kept honest

1. **An item leaves only with evidence.** Moving something to §7 means naming the
   command, the gate or the image that shows it. "It should work now" is not a
   close.
2. **A bug the owner found is written in his words first**, then in mine. The
   gap between the two is usually where the real defect is.
3. **Nothing here is aspirational.** If something is not built, it is in §3 or
   §4, not described as though it exists.
4. **Anything measured gets its number and its date.** A figure without those is
   a guess wearing a decimal point.

---

## 1. RIGHT NOW

| | |
|---|---|
| **Branch** | `main` on the public repo `desagencydes-rgb/VESPER` |
| **Gates** | **202/203 checks** — `speech-is-egress-and-says-so` is red and was before today's work: nothing sets `plan.voice`, so `speak()` computes a voice, publishes it and discards it (§2.2). 1090 self-test cases, both lints clean |
| **The app** | Built, signature valid, bundle clean of bytecode |
| **VESPER's own Desktop** | **It arrives when called.** Globe x3 now plants the ground on whichever Desktop is showing -- the owner's included -- because being called is not taking (2026-11-08, driven four ways; see §7.1). Vesper still never TAKES a Desktop unasked, so "on its own desktop, away from mine" is still waiting on an empty one |
| **Model access** | **None.** Both Claude accounts are past the owner's own limits (agents 88% of the week vs 70%; advisor 51% vs 40%). No other provider key is configured. VESPER cannot hold a conversation or decide anything with a model until a window resets or a limit moves |
| **Open source** | **Public since 2026-11-08, MIT.** This repository is a CLEANED copy of the original history: 643 commits with their original messages and dates, and every author mapped to the owner's GitHub noreply address. The owner's emails, cities, school and first name, and a personal screenshot, were removed from every commit, not only the tip. The unedited original, with its pull requests, is the private `VESPER-Archive`. **Commit hashes quoted in documents written before 2026-11-08 name the archive's commits, not this repository's.** Find one here by its subject line. README showroom: `docs/SHOWROOM_BRIEF.md` |
| **2026-11-08 evening** | BUILT AND DRIVEN: busy-Desktop take with the showcase full screen (probe: table 8/8, window = visible screen, panes fill); face no longer off-screen on a second display (built, not yet seen there); ears off while another app plays sound, flag on the home, back on when it stops (driven with Spotify). PROVEN END TO END at 23:16: the owner said "hey vesper, what time is it" -> woke -> captured -> transcribed ("What time is it? Have us", confidence 0.45) -> answered ("Sun Nov 8 23:16:39"). FIXED AND DRIVEN 23:32 (c99bf61): one listener per machine (the home stands by while the agent listens); the empty-Desktop test reads only the focused display -- the owner switched to an empty Desktop and vesper took it (`foreign=0`), glass TRANSPARENT, chrome mounted, full home on the second display. STILL OPEN: `recordGroundPlanted` still lists windows from every display in `layer0_on_this_desktop`, so the log names windows that were not on vesper's Desktop; WAS OPEN: BOTH wake listeners (home in-process and the `--wake` agent) wake on one utterance and record into the SAME temp file name in the same second -- the fix is one listener per machine, by lock; the 15 s grant retry never sees a grant made after the process started (the status is cached per process), so a restart was needed; the probe photo shows no marks though 4 are reported drawn; the runtime takes 1-2 min to start after a restart; hearing THROUGH music (voice processing gives 9 channels the recogniser rejects) is unsolved |
| **Grants** | automation, calendar, speech: granted. **accessibility: WIPED by the 2026-11-08 build, and the globe key does nothing without it** (`open -n app/VESPER.app --args --fn-status` reads `accessibility: false`). microphone, screen recording: wiped |

---

## 2. OPEN BUGS — confirmed, with evidence

### 2.1 The showcase collapses its panes into a strip
> *"don't you realize there some black shit hiding the whole page except top?"*

`#grid` in `app/home-macos/chrome/showcase.html` sets `align-content: start`, so
grid rows are sized to their CONTENT rather than stretched. A web pane's body is
an empty div until the site view is laid over it, so it collapses to about
100 px and the rest of the window is the black ground showing through.

- **Seen:** the owner's screenshot, 2026-09-16 15:30, and again at 15:43.
- **Fix:** stretch the rows (`grid-auto-rows: minmax(160px, 1fr)`, drop
  `align-content: start`), then LOOK at a photograph of the window before
  claiming it.
- **Why no gate caught it:** the readback reports `panes_drawn`, which is about
  structure. Nothing asserted a pane's SIZE. The DOM sweep stubs
  `getBoundingClientRect`, so it cannot see layout at all.

### 2.2 VESPER speaks in the wrong voice
> *"what i heard just now is a woman's voice, not jarvis's voice"*

Nothing sets `plan.voice`, so `say` uses the host default. This machine has
`Daniel (en_GB)` — the British male voice — plus Oliver/Eddy (en_GB).
`contracts/policy/voice.toml` governs the PERSONA (name, rules), not the
synthesiser, and `vesper_runtime.py` says in a comment that "the good voice is
not being used yet". Owner has to choose; I should not pick his assistant's voice
for him.

### 2.3 Speaking blocks everything for as long as it speaks
> *"vesper can actually talk while all those are running right? because it should be"*

`speech.speak()` runs the synthesiser through a blocking `subprocess.run`, called
INLINE on the pump — the one thread that hears, decides, acts and answers.

- **Measured 2026-09-16:** a 19-word sentence took **6.1 s**, and for all 6.1 s
  the pump was deaf and still.
- **Half-done:** `core/speech.Voice` is written (queue, worker, `interrupt()` for
  barge-in) and is reached by NOTHING. The runtime still calls the blocking path
  at `vesper_runtime.py:1431` and `:2987`. No gate, no self-test. See §3.1.

### 2.4 A web pane that changes address kept showing the old page — FIXED, keep the lesson
The pane header read `duckduckgo.com` over example.com's content, because
`layoutSites` reused a view by pane id and never navigated it. Fixed 2026-09-16
and confirmed by photograph. **The lesson stands:** `panes_drawn` said the pane
drew, which was true, and the content was wrong. A readback describes structure;
only an image shows content.

### 2.5 VESPER is slow — FOR CONTRIBUTORS, not yet worked on
> *"it's working with a lot of defect, it's slow af, very slow"* — the owner, 2026-11-08

Measured 2026-11-08 from VESPER's own records, on the MacBook, mains power:

| Where the time goes | Measured | Read from |
|---|---|---|
| Spoken question → answer on screen | **~30 s** (`gap_ms` 29876 for one turn) | the `turn` event on the bus |
| Recording after the wake word | **a fixed 6.0 s**, however short the sentence | `WAKE_CAPTURE_SECONDS` in `WakeWord.swift`; its comment says silence should end it, and nothing does |
| Runtime start after a restart | **60–120 s** before it answers anything | `runtime started` → `watching the field` in `island.out` |
| Model ladder | **13 of 15 rungs skipped** as `quota_ledger_exhausted` (every Groq and Mistral row); only Ollama answered | `gateway.attempt` events for one turn |
| Context gathering | two `osascript` calls to System Events fail every turn (`-1728`, `-54`: no Automation grant) | the Commands card |

Starting points, cheapest first: end the capture on silence instead of a
fixed 6 s; check whether the quota ledger's "exhausted" is real or stale (the
keys are present and `check_credentials.py` reads them); stop running the
System Events probes when the grant is absent; profile runtime startup.
Speed is a feature here — a 30 s round trip reads as "it did not hear me".

---

## 3. UNFINISHED — started, not landed

### 3.1 The non-blocking voice (§2.3)
Wire `Voice` into the runtime at both call sites, give it a gate ("speaking never
blocks the turn" — `say()` returns in under 100 ms while a sentence is still
playing; `interrupt()` stops mid-sentence and drops the queue), and self-test
cases. Then prove it live: speak a long line and run work at the same time.

### 3.2 Typing through the accessibility bridge is not proven on this machine
`ui.view` and `ui.act` now run under VESPER's identity (as a mode of the app
binary — see §5.3). Focus, scroll and the refusals are exercised. **Typing is
not**, because no window with a text field was reachable on the Desktop that was
showing. The run was interrupted before it finished.

### 3.3 Screenshot verification is not built into the harnesses
> *"you should take screenshots of visual stuff after testing them and look at them"*

The capability exists now — `shot_window` photographs VESPER's own window by
compositing its three layers and needs no grant; `screen` photographs the display
and needs the grant. Neither is wired into `showcase_endtoend.py`,
`showcase_soak.py` or `ui_endtoend.py`, and no gate asserts a pane's size or
position from an image.

### 3.4 Showing and talking are still scripted by hand
> *"they are talkative, and reactive, they could differ at each case, so i do not
> want some generic hardcoded bullshit, i want vesper to actively decide, choose
> and act each time, fast"*

Every scene and demonstration so far was composed BY ME in a test, not by VESPER
deciding what to show. The mechanism is right (a scene is data; a demonstration
is a checked script), and the judgement is missing. VESPER must compose the scene
and the words per situation. **Blocked on model access (§1).**

### 3.5 Documentation
`VESPER_ENGINEERING_STATUS.md` has counts and a ledger row; it does not describe
the showcase as a subsystem.

### 3.6 Release items carried from `docs/history/PLAN_2026-09-13-RELEASE.md`
- **D3** — write and register rules for the ~88 unregistered checks, immediately
  before the final build.
- **J3 face page** — last, by the owner's call.
- **Wake word and microphone end to end**, with the owner speaking. Needs the
  grants back.
- An honest write-up of what the camera can and cannot do.

---

## 4. NOT SOLVED — no known answer yet

### 4.1 VESPER has no Desktop of its own *unless it is called to one*
Its ground refuses to land on a Desktop holding the owner's windows — his own
rule, and right. So until he switches to an empty Desktop once, "show it on your
desktop, not mine" cannot be honoured. The showcase now REFUSES that reveal and
says why rather than dropping a window over his work. **There is no way around
this that does not break the rule.**

**NARROWED 2026-11-08.** The rule governs vesper starting UNASKED. Globe x3 is
the owner asking, so it now writes a `globe` summons that the home's wait takes
on its first tick and plants the ground on the Desktop that is showing, Desktop 1
included — recorded as `called=globe foreign=N` in `ground-log.txt` with the
windows that were on screen. What has NOT changed: vesper takes nothing by
itself, and a ground called onto a busy Desktop is `.managed`, so it stays on
that Space when the owner moves. Another globe x3 brings it along; the ground
cannot follow on its own, and §4.2 is why.

### 4.2 macOS will not move another application's window between Desktops
Measured 2026-09-08/09: neither `CGSMoveWindowsToManagedSpace` nor the older
add/remove pair moves a foreign window. VESPER's own windows move. This is why
the showcase is one window VESPER owns rather than a herd of applications.

### 4.3 Accessibility answers only for the Desktop that is showing
So driving the owner's windows works only on the Desktop currently displayed. A
window elsewhere can be SEEN in the inventory and not touched.

### 4.4 A new window does not reliably land on the active Desktop
Measured 2026-09-09 and again 2026-09-16: the TextEdit window VESPER opened
landed somewhere else, which is why §3.2 had nothing to type into.

### 4.5 TCC grants and rebuilds — the rule is more specific than it was
Believed: every grant dies on every rebuild. **Measured 2026-09-16:**
accessibility, automation and calendar SURVIVED a rebuild; microphone, screen
recording and speech did not. The rule needs re-deriving; until then, assume the
three sensitive ones die and plan the grant trip after the last build.

### 4.6 No model, therefore no judgement
§1. Everything in §3.4 waits on this. The owner's limits are working exactly as
designed; the decision to raise one is his.

---

## 5. HARD — solved, and the answer is worth keeping

### 5.1 An instrument's own faults look exactly like the system's
The soak's first three "findings" were all its own: `ps %cpu` is a decaying
average (reported 31% for a 3.5% process); the watchdog held a dead pid across a
deliberate restart and measured the leak-hunting phase for zero seconds while
still printing a slope; the slope straddled that restart. **Drive the instrument
before believing it.**

### 5.2 VESPER invalidated its own code signature every time it ran
The bundled runtime wrote `__pycache__` into the signed bundle, so macOS refused
to relaunch the app the one moment it mattered — after a permission grant. Four
crashes in fourteen seconds. Fixed, gated, and deleting the files restored the
SAME cdhash so the grants survived.

### 5.3 TCC answers the responsible process, not the one that asked
A harness run from a shell gets the TERMINAL's grants. `ui_endtoend.py` was
refused "accessibility is not granted to VESPER" while VESPER plainly had it. A
helper that needs a grant must be a MODE of the app binary, launched with
`open -n`.

### 5.4 A surface must report what it DREW, not what it was asked to draw
Everything on the showcase is verified against the window's own readback, and a
scene another writer replaced first is reported superseded rather than counted.

---

## 6. CONSTRAINTS — standing, not negotiable in passing

**The owner's rules**
- Windows he opened are his; VESPER's are VESPER's. His are `ON_REQUEST` (rule 31).
- Surfaces are free in every permission mode; only the WORK inside them is priced (§30).
- Never take the Desktop he is working on.
- Claude spend stops at HIS numbers: agents 70%, advisor 40%, set in Settings.
- Never change his billing or account settings.
- Downloads need his explicit permission.

**The machine**
- `python3.13` (`~/.local/bin/python3.13`). System `python3` is 3.9 and every
  gate dies on `tomllib` while still exiting 0.
- Stdlib only in `tools/` and `verification/`.
- No local models on this Mac; don't stress it.
- A TCC prompt must be triggered with `open -n`, never from a shell.
- The home waits for an empty Desktop; anything that must exist regardless
  belongs in the `--home` entry block, not after the ground lands.
- The globe key cannot pass an argument: it bootstraps the LOGIN agent's plist,
  whose arguments are fixed. A gesture that needs to change how the home starts
  is a `Summons` marker, read inside the wait (FnTrigger.swift).

**The corpus**
- A check lands with an executed red run or it does not land.
- A negative control that passes is a defect.
- An instrument's self-report is not evidence; read the world back.
- `INV-HW-1` no product names in routing/resource/policy paths · `INV-HW-2`
  measured, never declared · `INV-COORD-4` wall clock never orders ·
  `INV-STOP-2` the stop never goes through the runtime.
- Never commit while `self_test.py` is running; commit messages via `git commit -F`.
- This repository is PUBLIC. Never commit a key, a personal path, a screenshot of the owner's screen, or anything the owner would not post. Push branches; never force-push `main`.

---

## 7. WAITING ON THE OWNER

1. **Re-grant Accessibility** — System Settings → Privacy & Security →
   Accessibility, tick VESPER. The 2026-11-08 build changed the signature and
   wiped it, and the globe key is a global event tap: without this, pressing it
   three times does nothing at all. Everything below depends on it.
   Read it back with `open -n app/VESPER.app --args --fn-status`, never from a
   shell.
2. **The grant trip, after the last build** — microphone, screen recording:
   `open -n app/VESPER.app --args --request-grants`.
3. **Switch to an empty Desktop once** if he wants vesper to have a Desktop of
   its own rather than one it was called to (§4.1).
4. **Choose the voice** (§2.2). `Daniel (en_GB)` is the British male on this
   machine; Oliver and Eddy are the other en_GB options.
5. **Whether to raise a Claude limit** so VESPER can think and talk again (§1,
   §3.4), or wait for the week to reset (agents: Wed 16 Sep 19:00).

---

## 8. CLOSED RECENTLY — with what proves it

| what | proof |
|---|---|
| The showcase: panes, marks, its own cursor, its own browser, a whiteboard, a live run tail | 203/203 checks, 1081 cases, 396 end-to-end assertions over five rounds |
| It survives a long crowded run | 1972 acts, 8 min sustained, three writers at once, 7.9% cpu, 73→76 MB settling to 75, p95 283 ms |
| It never claims a scene it did not draw | drew / half-drew / not-drawing / superseded each answered separately, gated |
| Following the owner's screen | a real 1728×1117 frame, confirmed by the owner |
| The app can be reopened after a grant | §5.2, gated by `the-app-does-not-invalidate-its-own-signature` |
| A pane that changes address goes there | §2.4, confirmed by photograph |
