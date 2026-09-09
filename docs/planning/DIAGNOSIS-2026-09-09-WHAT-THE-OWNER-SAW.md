# DIAGNOSIS — 2026-09-09, the four things the owner reported

Written BEFORE any fix, so the reading survives whatever the fixes do to the
tree. Every claim below names how it was established. Where the previous
session's handoff says something different, the difference is stated.

**The headline: almost nothing was destroyed. The code landed. What is wrong is
state, one sentence, and one call site that has been wrong since 26 August.**

---

## 0. WHAT WAS CHECKED FIRST, AND WHY IT MATTERS

`app/home-macos/chrome/home.html` — the file that draws every card — **was not
touched by any commit in `4f5c979..HEAD`**, and the copy inside the bundle is
byte-identical to the repo copy. `diff -rq --exclude=__pycache__ core/
app/VESPER.app/Contents/Resources/runtime/core/` is **empty**: the shipped
runtime matches the repo. The running process (pid 94323, launched 21:36) came
from the 21:32 build, so it *has* the session's fixes in it.

A wholesale revert of the session's 1,929 lines would therefore have destroyed
real work and not changed the screen. It was considered and rejected on this
evidence.

---

## 1. "SOME CARDS DISAPPEARED" — they are empty, not gone

`home.json`, read live:

| feed | entries | rendered? |
|---|---|---|
| `actions` | 27 | yes |
| `explanations` | 1 | yes |
| `thoughts` | 4 | yes |
| `commands` | **0** | **no** — `pcmds.classList.add('idle')` |
| `flags` | **0** | **no** — the bar hides when empty |

Both panes hide themselves when their feed is empty. The handoff's §6.2 already
conceded the flag bar "has never been seen by the owner with a flag in it".

**Open, and not yet answered:** whether `commands` is empty because nothing ran
or because its producer is dead. `actions` has 27 entries from the same board,
so the board is alive; the commands feed specifically is not arriving. That is a
different fault from "the UI broke" and is not fixed by this document.

---

## 2. "IT LOST THE DEFAULT BACKGROUND" — a scope bug that is already fixed,
   and a change that cannot be undone

The owner's correction, which the handoff got wrong: **those images are theirs,
added deliberately, and mode-driven switching is wanted.** The requirement is
not "stop changing the wallpaper", it is **"change only VESPER's Desktop, never
the owner's other Desktops, never the lock screen."**

The mechanism: `NSWorkspace.setDesktopImageURL` has no Space argument and never
has had one — it applies to whichever Space is showing. So a mode set while the
owner was looking at their own Desktop replaced *their* picture.

`app/home-macos/Home.swift:844` now asks the window server whether VESPER's
ground is on the showing Space and refuses otherwise. **That guard is present,
looks correct, and shipped in the 21:32 build** (`e1725d4`).

Two things it does not do:

1. **It cannot undo the change already made.** `wallpaper_before_vesper.txt`
   does not exist; only `wallpaper_before_vesper.bad`, holding
   `docs/design/assets/wallpapers/rest.png` — one of VESPER's own images,
   recorded after VESPER had already replaced the picture. The owner's original
   is not in the record. `desktoppicture.db` would not open.
2. **The lock screen is unverified.** On current macOS the Lock Screen picture
   can be linked to the Desktop picture at the OS level. Whether the guard is
   sufficient there is NOT established, and must be measured rather than
   assumed.

---

## 3. "MODES DON'T WORK" — correct, and the handoff says so

`island.json` reads `Mode: auto`. `home.json` has **no `mode` key at all** —
not `mode: None` as the handoff states; the key is absent.

Handoff §6.3, unprompted: *"`mode.set` has never been driven live end to end …
the wallpaper has never been observed changing on VESPER's Desktop through that
path."* It shipped as done in the commit subject "Modes existed as pictures and
as nothing the owner could enter". The owner is right; this is the session's own
largest unverified claim.

---

## 4. THE CONVERSATION THE OWNER SHOWED — four turns, and the worst bug is not
   from this session

```
YOU     move the safari window in the other desktop to this desktop
VESPER  33 window(s) open, 0 of them mine to arrange
YOU     open a new terminal, and safari window
VESPER  that did not go through: the application would not open a new window …
YOU     why is that?
VESPER  Sir, could you clarify what "that" refers to?
YOU     the shit you just said about windows
VESPER  Sir, I can only display text in this console. I have no capability to
        spawn a separate terminal or manipulate GUI windows such as the Notes app.
```

### 4a. Turn 1 — the count is real, the sentence is wrong

`window_list` computes **both** `may_arrange` and `needs_a_request`.
`core/actor.py:1268` reports `may_arrange` and **discards `needs_a_request`**.

`may_arrange` is the count VESPER may touch *unprompted*. `vespers_desktop` is
`null` unless VESPER's ground is on the showing Space, so clause 1 of the
ownership rule cannot apply, so every window is `unknown`, so the unprompted
count is legitimately 0.

**But the owner had just asked.** `may_act(..., owner_requested=True)` returns
True for every one of those 33. The sentence reports the one number that is
irrelevant to a request the owner just made, and reads as a refusal that the
rule does not actually impose.

The real blocker for *that specific request* is a measured platform limit —
accessibility reaches only the Desktop that is showing — and the sentence never
mentions it.

**`authority()` must not be loosened to make the count non-zero.** The doctrine
is the owner's own decision and loosening it would hand VESPER their whole
session. This is a presentation defect.

### 4b. Turns 3 and 4 are ONE bug, and it dates from 26 August

`tools/ops/vesper_runtime.py:2084`:

```python
reply = answer(gw, router, persona, intake.history[-1], ...)
```

The conversational path is handed **the last utterance and nothing else** — no
conversation history, no record of what VESPER just said, no capability list.

- *"why is that?"* → nothing in scope for "that" → asks for clarification.
- *"the shit you just said about windows"* → no capability registry in the
  prompt → the model answers from its own priors, denies a capability it had
  used correctly two turns earlier, and invents "the Notes app", which nobody
  mentioned.

Twelve lines above that call, the **actor** path carefully assembles `recent`
from `intake.history[-6:]` plus `last_action`, with a comment explaining that
"run it" names nothing without the turns either side. **That fix was made for
the proposer and never for the answerer.**

`git log -S` puts the call site at `e01c299`, **Wed 26 Aug** —
`git merge-base --is-ancestor e01c299 4f5c979` confirms it predates the
session entirely. This is the bug that makes VESPER look most broken, and last
night did not cause it.

`transcript` in `pump()` already holds both sides of the conversation, capped at
`CONVERSATION_MAX`, and is already published to the home surface. The material
the answerer needs is built and thrown away.

---

## 5. WHAT THIS CHANGES ABOUT THE HANDOFF

| Handoff said | Established here |
|---|---|
| owner's wallpaper unrecoverable, a loss | still unrecoverable, but the owner WANTS mode switching; it is a scope requirement, not a loss to mourn |
| `home.json` reads `mode: None` | the key is absent entirely |
| three claims unverified by the owner | the owner has now exercised two of them and both failed in ways the gates did not see |

---

## 6. THE RULE THIS SESSION ADDS

Every gate imports `core/` from the working tree, and the handoff's §1 already
names that gap. **These four faults extend it: none of them is reachable from
`core/` at all.** Two live in `tools/ops/vesper_runtime.py`, one in a Swift
call site, one in a sentence in `actor.py`. A corpus that gates `core/` and
drives nothing the owner types will keep shipping "done" for turns like the four
above.

**The owner's transcript is the instrument no check replaces.**
