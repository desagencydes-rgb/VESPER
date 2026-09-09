# HANDOFF — 2026-09-09, windows and modes

**Read `docs/design/HOME-WORKBENCH.md` first.** This document is the session's
record; the plan doc is the authority for what is next. Every section here names
the plan section it belongs to.

**One sentence for whoever picks this up:** window management and modes are
built and gated, four separate faults made them unusable to the owner and are
fixed, and **three things are verified only by me and not by the owner** — they
are listed in §6 and should be the first thing checked.

---

## 1. THE ONE MISTAKE THAT PRODUCED MOST OF THE OTHERS

Everything I tested imported `core/` **from the working tree**. The runtime that
actually runs is the **copy inside the app bundle**,
`app/VESPER.app/Contents/Resources/runtime/core/`. Drives, checks and self-tests
all took the repo path; only the shipped process took the other one.

Four faults lived in that gap, and every one of them passed every gate:

| Fault | What the owner saw |
|---|---|
| `VESPER_BIN` computed from the repo layout | *"I could not find that file"* for every window action |
| `parse()` rejected empty args, so `window.list` was unproposable | *"what windows do i have open"* answered with Linux `wmctrl` advice |
| `observe()` had no `window.*` branch | the list ran and its result reached nothing |
| `int()` on a zero-byte `heard.offset` | the pump died every tick; cards vanished, input ignored |

**The rule that follows, and it should be a check if it is not already one:**
"driven live" from the repo is not the same claim as "the owner can use it".
`CI-140` now asserts the shipped copy matches the repo, because a fix that lands
only in the repo is a fix the owner never gets.

---

## 2. WHAT IS BUILT AND GATED

Nine checks landed, all with executed red runs. Counts as of this handoff:
**154 runnable checks, 754 self-test cases.**

| Check | Red runs | Plan § | What it holds |
|---|---|---|---|
| `the-ground-gives-a-taken-desktop-back` | 8 | §11.0, §12 | the ground is judged after it EXISTS and retracts off an occupied Desktop |
| `a-window-is-claimed-only-by-the-app-that-opened-it` | 8 | §11.1c | a window may be claimed only by the app that opened it, and only if it postdates a cross-Desktop frontier |
| `every-flag-reaches-one-bar` | 8 | §11.9 | a degraded result reaches `home.json` and the bar, deduped by condition |
| `a-restored-stamp-is-corroborated` | 7 | §11.8 | provenance survives a VESPER restart, corroborated against the live window |
| `the-window-log-records-and-never-reopens` | 5 | §11.8 | the log records and **cannot** open a window |
| `the-shipped-runtime-can-reach-what-it-needs` | 3 | §1 above | the binary resolves from a bundle; empty args parse; the bundle matches the repo |
| `a-refusal-is-never-reported-as-done` | 4 | §11.1 | no capability reports success for `ok:false` |
| `the-wallpaper-changes-only-on-vespers-desktop` | 3 | §11.2 | the wallpaper switch is bounded to VESPER's own Desktop |
| `a-mode-is-a-pairing-of-two-axes` | 6 | §11.2 | a mode names a real stage and a real ambience, kept apart |

### Binary-mode controls (run them by hand; they refuse unearned passes)

```
--ground-retract-check      plant on an occupied Desktop, prove it retracts
--ground-resume-check       prove the resume does NOT replant while windows are there
--window-id-reuse-check     prove window numbers are not reused within a boot
--ax-order-check            prove the right one of two identical windows moves
--mode-residency-check      prove a mode does NOT repaint a Desktop that is not VESPER's
```

Each exits **4 / UNTESTED** rather than passing when its precondition is absent.

---

## 3. MEASUREMENTS THIS SESSION (do not re-derive these)

| Fact | Value | Why it matters |
|---|---|---|
| Ground becomes visible after `startHome()` | **0.06 s** | replaced a guessed 0.60 s delay; the guard now polls |
| Ground leaves the window list after `retract()` | **0.06 s** | a single read straight after was reporting failure |
| Window numbers reused within a boot | **never** — 41 created/destroyed, 41 distinct, strictly increasing | this is what makes the frontier and persisted provenance sound |
| Window-number allocation rate | ~4,460/day | `UInt32` overflow ≈ 2,638 years away |
| Accessibility reach | **only the Desktop that is showing** | every move/resize/close off it fails with an empty AX tree |
| First AX query on some apps | returns **empty**, correct a moment later | must be retried, not believed |
| `CGWindowListCopyWindowInfo` with no options | includes **phantoms** — Safari reported 3 windows while the list showed 6 | fine for inventory, wrong for acting |
| AX order vs window-list order | **agree** (`--ax-order-check`) | lets identical twins be told apart with public API only |
| macOS unsaved-work flag | **does not exist** generally — TextEdit exposes `AXDocument`, not `AXModified` | the rebuild rung refuses; this is a platform limit |
| Accessibility grant across rebuild | **survived** (unlike speech) | `CLAUDE.md` says consent dies on rebuild; that was measured for speech at cdhash level and does not hold here |
| New window placement | **not** always the active Desktop; mechanism **unknown** | so placement must be READ BACK, never predicted |

---

## 4. THE RECURRING DEFECT, NAMED

**Nine checks stopped detecting their own violations this session.** Every one
because an assertion asked *whether a name appears*, and a second place began
using that name:

- `"at_ms"` appeared in a second metrics row-builder
- `at_ms` appears twice in the HOST renderer (filtering, and scheduling)
- `actor=actor` appeared in an unrelated menu-context call
- `groundIsVisible()` / `armResumeWatch()` appeared in the diagnostic controls
- `verifyGroundLanding()` appeared in a control added hours later
- `retract` is a substring of the variable `retracted`
- `HEARD_OFFSET.read_text()` appeared in a **docstring** explaining why it no longer ran
- the pid/frontier predicate appeared at a second claim site
- a mutation anchored on a line two controls shared, and hit the wrong one

**The durable fix, applied each time: count the sites, or ask the AST. Never
test for a substring.** If you add code that reuses a helper, assume you have
just made some check vacuous, and run the full suite.

---

## 5. PLATFORM LIMITS — RECORDED, NOT WORKED AROUND

1. **Accessibility answers only for the Desktop that is showing.** VESPER can
   *see* windows everywhere and *act* only on the current Desktop. `_act`
   refuses the rest with a sentence naming the reason.
2. **No general unsaved-work signal.** The rebuild rung (§11.1a rung 3)
   therefore refuses for document apps. Treating "the app would not say" as
   "safe to close" would gamble with the owner's work.
3. **Placement is the system's choice.** A new window lands where macOS decides;
   the mechanism was not established. `window_open` reads back and flags.
4. **The accessibility tree carries no CGWindow number.** Windows are matched by
   geometry, and identical twins are separated by order (`--ax-order-check`).
   The private `_AXUIElementGetWindow` would remove this weakness and needs an
   owner decision under `INV-HOME-5`.

---

## 6. VERIFIED BY ME, NOT BY THE OWNER — CHECK THESE FIRST

**These are claims, not facts, until the owner exercises them.**

1. **Window management since the fixes.** The owner's last hands-on test predates
   every fix in commits `2f940ee` … `1f7ec88`. Ask them to retry: *open a new
   safari window here*, *what windows do i have open*, *move the notes window to
   your desktop* (two turns by design — it lists first).
2. **The flag bar has never been seen by the owner with a flag in it.** The
   receiver is mounted (`Flags:fn`, jsErrors=none) and the chain is driven, but
   the bar hides when empty and no live flag has been raised in front of them.
3. **`mode.set` has never been driven live end to end.** `home.json` still reads
   `mode: None`. The pairing resolves, the capability writes, and the home
   watches the file — but the wallpaper has never been observed changing on
   VESPER's Desktop through that path, because it needs VESPER's ground on the
   ACTIVE Desktop and that never coincided with a test. **This is the single
   biggest untested claim in the session.**

---

## 7. OWED, AND WHY

| Owed | Blocked on |
|---|---|
| §11.2a stage gating — `may_open`, `max_windows`, `owner_keeps` | nothing; contract exists, enforcement not written |
| §11.1a rung 3 rebuild actually running | platform: no unsaved-work signal |
| Steps 17 (apps), 18 (Notes in full), 19 (UI view) | not started |
| Steps 20–21 (settings, projects/research rail) | the owner stops the run before these deliberately |
| `INV-HOME-8` ratification | the owner's act; two window checks run unregistered pending it |
| Speech consent | `open -n app/VESPER.app --args --speech-consent`; wake word is off |
| A Developer ID certificate | would end TCC revocation on rebuild; argued for three times now |

---

## 8. DAMAGE AND DEBRIS I CAUSED

Recorded because a handoff that only lists wins is not a handoff.

1. **Three hours lost overnight** — the machine slept because I held no
   `caffeinate` assertion. Now held as `caffeinate -ims` (system awake, display
   free to sleep).
2. **The owner's original wallpaper is gone from the record.** The saved
   "original" held `rest.png` — a VESPER image — so it was captured after VESPER
   had already replaced the picture. `apply()` now refuses to record any picture
   from VESPER's wallpapers directory as the owner's, and the poisoned file was
   moved to `wallpaper_before_vesper.bad`. **What their picture actually was is
   not recoverable from here.**
3. **Two blank Safari "Start Page" windows** left from probes; AppleScript would
   not close them. Cmd-W clears them.
4. **A ground planted on the owner's Terminal Desktop** at ~09:04, because I
   launched with a bare `open -n` which bypasses `--on-empty-desktop`. Caught
   and killed within a minute. The LaunchAgent path is guarded; a bare launch is
   not, and **making the emptiness judgement the default rather than a flag is
   still owed.**
5. **An orphaned runtime at 13% CPU for 2h22m**, reparented after I killed its
   parent. Killing `VESPER.app` does not stop its Python child.
6. Numerous TextEdit/Calculator/Safari windows opened during drives, all cleaned
   up except (3).

---

## 9. HOW TO PICK THIS UP

```sh
python3.13 tools/ci/checks.py all          # expect 154/154
python3.13 tools/ci/self_test.py           # expect 754/754, ~50-70 min, run ALONE
python3.13 tools/traceability_lint.py
python3.13 tools/reference_lint.py
```

VESPER runs as:

```sh
./app/VESPER.app/Contents/MacOS/VESPER --home --on-empty-desktop --mode Home --chrome
```

**`--chrome` is not optional** — without it the Metal face renders with no
menu, no cards and no flag bar, which looks like a broken build and is not one.
**A bare `open -n app/VESPER.app` bypasses the empty-Desktop guard**; do not use
it.

After ANY Python change under `core/`, **rebuild** — the bundle carries its own
copy and `CI-140` will tell you, but only if you run it.
