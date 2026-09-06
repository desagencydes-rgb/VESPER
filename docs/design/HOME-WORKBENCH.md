# HOME WORKBENCH — commands, activity, changes, terminal

Owner's request, 2026-09-06. This document is the specification for the whole
chunk. The owner has said they will not read it, so it carries the full
decision record and every acceptance condition; its real consumer is a future
session that has none of this context.

**It states steps, never intentions.** The defect this corpus keeps finding is
a comment that describes what should happen beside code that does not do it
(`build.sh`'s "every build that changes the signature", the wake listener
nothing started, the task ranker the runtime never called, the agenda trigger
with no handler — five instances in this repo's own history). Every section
below names the file, the anchor, the check, and what red looks like.

---

## 0. THE RULE THIS CHUNK IS BUILT UNDER

**A step is finished when three things are true, and not before:**

1. **A check exists and has been seen red**, then green. `CHECKS.toml` declares
   the self-test; `tools/ci/self_test.py` executes it. A check that has only
   ever been green is not evidence.
2. **The behaviour has been driven end-to-end against the running surface** —
   the real `home.json`, the real bundle, the real webview. Not a unit test,
   not a fixture. The pattern this guards against is "the feature works and the
   thing that reaches it does not", which has cost this project more time than
   every other class of bug combined.
3. **The bundle is confirmed current.** `app/VESPER.app/Contents/Resources/`
   must match the repo for every file the step touched. A correct fix sitting
   in the repo while the app runs the previous build is indistinguishable from
   no fix.

Anything reported as done without all three is a false report.

---

## 1. WHAT EXISTS TODAY, AND WHAT THE NEW WORK RIDES ON

Grounding, so nothing below invents a mechanism that already exists.

| Piece | Where | What it does |
|---|---|---|
| `home.json` | `~/Library/Application Support/VESPER/home.json` | The runtime's whole view of the surface: `face`, `transcript`, `workbench`. Written by `core/home_state.py`, read by Swift. |
| The poll | `HomeChrome.swift` `startRefresh()` | One timer. Reads `home.json`, pushes into the page. |
| The push | `HomeChrome.swift` ~1044 | `window.__vesperStage`, `__vesperHistory`, `__vesperWork`, plus `data-face`. |
| The page | `app/home-macos/chrome/home.html` | Template. Geometry arrives as `{{left}}`, `{{top}}`, `{{cardWidth}}`, `{{cardHeight}}`, `{{convoLeft}}`, `{{fill}}` from `HomeChrome.page()`. |
| Page → Swift | `SayBridge` (`WKScriptMessageHandler`) | Three channels today: `vesperSay`, `vesperFocus`, `vesperSpeaking`. |
| The workbench | `core/workbench.py` | `observe()` real thoughts, `acted()` capability actions. Already feeds `.think` and `.acts`. |

**ONE POLL, ONE REGISTER.** `HomeChrome.swift` says it in its own comment:
*"a second timer reading the same file is how the two come to disagree."*
Commands, explanations and changes all ride the existing tick and the existing
`home.json`. **No second poller. No second state file.** The terminal PTY is
the single exception and is justified in §6: it is a stream, not state.

---

## 2. LAYOUT

The left column becomes a stack. Today it is `.work` (think + acts) above one
`.card` (host).

```
   ┌─ .work ────────────┐   thoughts + actions   (exists)
   ├─ HOST ─────────────┤   metrics              (exists)
   ├─ COMMANDS ─────────┤   §3   NEW
   ├─ EXPLANATIONS ─────┤   §4   NEW
   ├─ CHANGES ──────────┤   §5   NEW
   └─ TERMINAL bar ─────┘   §6   NEW, collapsed by default
```

**GEOMETRY IS COMPUTED IN SWIFT AND PASSED THROUGH `page()`. It is never a CSS
constant.** *(Built. Two tokens, `{{stackTop}}` and `{{stackHeight}}`, and the
panes are a FLEX COLUMN inside that box rather than four absolute offsets —
opening one moves the others, and four hardcoded `top`s would have to be
re-solved on every toggle. Swift pulls the whole left cluster UP when centring
the host card on the face would leave the stack less room than its four bars
need; the floor at 158 is the work card's own minimum.)* `.card` is absolutely positioned at `{{left}}/{{top}}` with a fixed
`{{cardHeight}}`, and `.work` above it is bounded by `calc({{top}}px - 58px)`.
Hardcoding four more offsets breaks on the first screen that is not this one.

`HomeChrome.page()` gains one parameter, `stack: [StackSlot]`, where
`StackSlot = (id: String, top: Int, height: Int)`. The template gains
`{{STACK_CSS}}`, a generated block of `#cmds{top:..;height:..}` rules. Swift
computes the stack from `cardRect` and the screen, top-down, with a fixed
`GAP = 14`. Every card is the same `width: {{cardWidth}}`, left `{{left}}` —
the owner's requirement that the terminal bar be "same width as the cards above
it" is satisfied by construction rather than by a matching literal.

**Collapsed heights** (the resting state, so the stack fits without scrolling):

| Card | Collapsed | Expanded |
|---|---|---|
| Commands | bar | fills the free column |
| Explanations | bar | fills the free column |
| Changes | bar | fills the free column |
| Terminal | bar | fills the free column |

**CORRECTED BY THE BUILD.** The fixed heights above were wrong twice over.
First, they do not fit: the left column is about 250 pt on this display and
132 + 148 + 156 + 34 is 470. Second, a shut pane sized to its contents is not
a bar — measured at 108 px for a single command, because `overflow:hidden`
clips the body without removing it from the layout. Every pane is now exactly
its 41 px header while shut (`.pbody{display:none}`) and takes the free column
when open, so a pane holding fifty commands is the same height as one holding
none, and the resting stack fits on any screen by construction.

Only one card may be expanded at a time; expanding one collapses the others.
This is what keeps the stack from needing a scroll container, and it is
enforced in the page, not by discipline.

---

## 3. CARD A — COMMANDS

**What the owner asked for:** *"add a card under 'host' card, where it shows
the commands it runs, expand to the result, exactly like how claude code does
it."*

### 3.1 Data

`home.json.workbench` gains `commands: [Command]`, newest first, capped at
`COMMANDS_MAX = 50` in `core/workbench.py`.

```jsonc
{
  "id": "cmd_01H...",            // stable; the page keys rows on it
  "argv": ["python3", "hey.py"], // the ARGV, not a reconstructed string
  "display": "python3 hey.py",   // shell-quoted for reading and for copy
  "cwd": "~/Library/.../workspace",
  "state": "running|ok|failed",
  "exit_code": 0,
  "started_ms": 1788...,
  "elapsed_ms": 412,
  "stdout": "hey there",         // capped, see 3.3
  "stderr": "",
  "truncated": false
}
```

**ARGV IS THE RECORD; `display` IS THE RENDERING.** `shell_run` refuses
`shell=True`, so the argv list is what actually ran. A single string is a
reconstruction and can differ from it — which is precisely the class of bug
where a classifier reads one thing and the kernel runs another. `display` is
built by `shlex.join` for the owner's eye and for the copy button; nothing ever
parses it back.

### 3.2 Where it is written

`shell_run` returns exit code, stdout and stderr, and now also `argv` and
`elapsed_ms` — added, because the card exists to say what RAN and the argv is
the only record of that which is not a reconstruction.

**BUILT AT THE RUNTIME'S CALL SITE, NOT IN `core/actor.py`.** The doc said the
actor would call `bench.command(...)`; the actor has no reference to the
workbench and the established pattern is that the RUNTIME translates a finished
step into a board row — `bench.acted(...)` is called there, from the same
`steps` list. `_record_command` sits beside it. Following the existing joint
was right; inventing a second one would have given the board two writers.

**AND THE SINGLE-STEP TURN NEEDED ITS OWN BRANCH.** `Actor` attaches `steps`
only when a turn took more than one step, so recording from `steps` alone
showed nothing for the ordinary case — one request, one command — which is most
of what the owner watches.

### 3.3 Bounds

`STDOUT_MAX_BYTES = 16_384` per stream, `STDOUT_MAX_LINES = 400`, per-line
`OBS_MAX_LINE_CHARS` (reuse the existing constant — a second bound that can
drift from the first is a bug waiting). When cut, `truncated: true`, and the
card renders *"… output truncated at 400 lines"* — never a silent cut. Silent
truncation reads as "the command printed nothing more", which is a lie the
owner would act on.

### 3.4 Rendering

Collapsed row: a status dot, `display` on one line ellipsised at the card
width, elapsed on the right. Colour by state, from the existing palette —
`ok` uses `--ink` at .72, `failed` uses the existing warm red, `running`
pulses at 1.1 s (`prefers-reduced-motion` removes the pulse, not the colour).

Expanded (click the row): `cwd`, the full `display` in a mono block, then
stdout and stderr in separate blocks each with their own label. Both blocks
`overflow:auto`, both selectable, each with a copy button.

**A FAILED COMMAND SHOWS ITS STDERR WITHOUT BEING EXPANDED.** The owner spent a
day being told "error code 1" while the reason sat one field away. A `failed`
row renders the first line of stderr under the command, dimmed, always.

### 3.5 Gate

`CI-123 commands-card-shows-what-ran` — **landed, 11 red runs.** Assertions:

1. Every `shell.run` execution produces exactly one command entry.
2. The entry's `argv` equals what the executor invoked — compared to the
   executor's own record, not to a re-parse of `display`.
3. Output beyond the cap sets `truncated: true` and the entry retains the
   FIRST lines, not the last (the failure is usually at the top).
4. A failed command's `stderr` is non-empty in the entry when the process wrote
   to stderr — the field is not dropped by `_reportable`.
5. The list is capped at `COMMANDS_MAX` and drops OLDEST.
6. `home.json` round-trips the list: written by the runtime, parsed back,
   identical.

Red run: remove the `truncated` flag; key rows on index instead of `id`; write
`display` and derive argv from it.

---

## 4. CARD B — EXPLANATIONS

**What the owner asked for:** *"add the card where it's explanations and big
text will go, it will not say them, they just show up there, what it says stays
on the dialog that was made for it, they should be connected."*

### 4.1 The split, which is the whole point of this card

VESPER produces two kinds of text and they have different destinations:

| | Goes to | Spoken |
|---|---|---|
| **The reply** | the existing conversation card (`.convo` / `#stage`) | yes |
| **The explanation** | this card | **never** |

An explanation is the long form: reasoning, a list of steps, a block of code,
a table. It must not be spoken — reading four hundred words aloud is the
failure this split exists to prevent.

**CONNECTED, AND THE CONNECTION IS THE `turn_id`.** Every explanation carries
the `turn_id` of the reply it belongs to. Clicking a reply in the conversation
scrolls this card to its explanation and highlights it for 1.2 s; clicking an
explanation highlights its reply. Neither card owns the other — they share a
key, which is what lets either be rebuilt from `home.json` alone.

### 4.2 Data

`home.json.workbench.explanations: [Explanation]`, capped at
`EXPLANATIONS_MAX = 30`.

```jsonc
{
  "id": "exp_...",
  "turn_id": "...",              // the reply this belongs to
  "title": "why the rename failed",
  "blocks": [                    // TYPED, never raw markdown
    {"kind": "text", "text": "..."},
    {"kind": "code", "lang": "bash", "text": "mv a b"},
    {"kind": "list", "items": ["...", "..."]}
  ],
  "at_ms": 1788...
}
```

**TYPED BLOCKS, NOT MARKDOWN.** A markdown string would have to be parsed in
the page, and a parser in the page is a place model output becomes markup.
The runtime emits typed blocks; the page renders each kind with a fixed
template and `textContent`. **Nothing in this card is ever assigned via
`innerHTML`.** That is a hard rule and §8 gates it.

### 4.3 Where it is written

`core/speech.py` already decides what may be spoken. The explanation is
produced by the same turn and routed by `core/workbench.py::explain(turn_id,
title, blocks)`. The runtime calls it where it currently discards the long form.

### 4.4 Gate

`CI-124 an-explanation-is-shown-and-never-spoken` — **landed, 13 red runs.**
The split itself is `core/longform.py`; the runtime applies it at ONE point,
before either consumer sees the reply, and keeps `reply_full` for the records
underneath (`baseline` is a corpus of what VESPER actually answered, and
shortening it there makes every comparative question about memory
unanswerable). Assertions:

1. An explanation never reaches `speech.plan` — asserted by driving a turn that
   produces one and checking the spoken plan's text does not contain it.
2. Every explanation's `turn_id` resolves to a transcript entry.
3. Blocks are typed; an unknown `kind` is dropped with a visible note, never
   rendered as raw text.
4. The page assigns block content with `textContent` — parsed from the source,
   not grepped (`innerHTML` appearing anywhere in the explanations renderer is
   red).

Red run: route the explanation into the reply; drop `turn_id`; render a block
with `innerHTML`.

---

## 5. CARD C — CHANGES

**What the owner asked for:** *"for the edits on files, you decide how they can
show up… comprehensive clean way, totally manageable, user friendly, card can
expand to bigger screen, i can copy from it, i can push, pull, create or from a
button, compare between removings and addings there, each file collapse in a
list, and is expandable on demand, it can open the selected file on the default
IDE when i click it's button, i can change how they show up and select between
what to show, and how to show and how to sort all of them."*

### 5.1 Two sources, labelled, never merged into a fake git view

VESPER writes to paths that are in no repository — the workspace,
`~/Downloads`. Git covers repository files the owner also edits. The owner
asked for both, so both are in one list with a `source` field per row:

| `source` | Where it comes from | Git buttons |
|---|---|---|
| `vesper` | VESPER's own `fs.write` / `fs.edit` / file-touching `shell.run` | disabled |
| `git` | `git status --porcelain=v2` in the active repo | enabled |

A row that is both (VESPER edited a repo file) is `git` with
`by_vesper: true` — the git view is the more useful one and the flag keeps the
authorship visible.

### 5.2 The diff store, and why it is not the event log

`fs_write` returns `previous`, the entire prior contents. `Actor._reportable`
**strips it deliberately** so the durable audit store never carries file
contents, keeping `previous_sha256` instead. That decision stands.

**THE DESIGN CHANGED HERE, AND FOR THE BETTER.** The doc proposed a bespoke
`changes.jsonl` holding `previous` bytes. It is not needed:
`core/checkpoint.py`'s `ShadowGit` ALREADY mirrors, by absolute path, every
file VESPER is about to touch — it has to, because the executor fails closed on
a capability whose pre-state it cannot record. So the "before" of every write
is already committed to a real git repository, keyed by the execution that made
it. `core/changes.py` reads that. A second store beside it would be a second
answer to a question that already has one, and the two would eventually
disagree about the same file.

What survives from the plan below is every constraint on it:

- **This file is a VIEW CACHE. It is not evidence, it is not append-only, and
  nothing may cite it.** A future session must not mistake it for an audit
  trail; the audit trail is `bus/log.db` and does not contain file contents.
- Bounded: `CHANGES_MAX = 60` rows, `DIFF_MAX_LINES = 300` and
  `DIFF_MAX_BYTES = 32_000` per file, and — the bound that actually mattered —
  `DIFF_TOTAL_MAX_BYTES = 140_000` across all of them. The per-file caps were
  satisfied while one Swift file still carried 36 KB; twelve of those is a
  megabyte rewritten into `home.json` and pushed through a webview on every
  tick, on a laptop the owner has asked twice not to heat up. Rows past the
  budget keep their counts, which come from one `git diff --numstat` and cost
  nothing, and say plainly that the diff was not loaded.
- The runtime publishes the board only when it CHANGES. `refresh_git` is
  throttled to six seconds and the payload is compared before `set_changes`
  rewrites the file.
- Each row: `{path, name, source, status, added, removed, hunks, by_vesper,
  in_repo, truncated, binary}` — `hunks` is a unified diff already computed,
  and the page never diffs anything.
- **Redacted before it is written.** `core/redact.py` runs over both sides. A
  file VESPER wrote may contain a key it was asked to write.

### 5.3 View controls

A control strip in the card header, state persisted in `home.json.workbench.
changes_view` so it survives a restart:

- **Show**: `all` / `vesper only` / `git only` / `unstaged` / `staged`
- **Sort**: `recent` (default) / `path` / `most changed`
- **Display**: `list` (default) / `compact` (one line each) / `split` (side by
  side in the expanded overlay only)

### 5.4 The expanded overlay

The card expands to a full-surface overlay — not a bigger card. It keeps
VESPER's glass tier (blur 24, saturate 180%, the card's solved `fill`), with
the face dimmed behind it. Escape and a close button both dismiss.

Inside: the file list on the left (collapsed rows, expandable), the selected
file's diff on the right. Additions and deletions are compared by colour and
by a `+`/`-` gutter, both selectable, with a copy button per hunk and one for
the whole diff.

### 5.5 Buttons

| Button | Does | Guard |
|---|---|---|
| **Open in IDE** | `open -a <default editor> <path>` via `/usr/bin/open`, outside the seatbelt | The path must be one in this row; never a value from the page |
| **Copy** | the hunk or the whole diff | — |
| **Pull** | `git pull --ff-only` in the active repo | **Confirms first.** Never `--rebase`, never a merge that could conflict silently |
| **Push** | `git push` current branch to its upstream | **Confirms first**, and shows the branch and remote in the confirmation |
| **Create** | `git add -A && git commit` with a message the owner types | **Confirms first**, message required, never empty |

**EVERY GIT BUTTON IS A CONFIRMED ACTION AND NAMES ITS TARGET.** These are
outward-facing and hard to reverse. The confirmation shows the exact command,
the repo, and the branch. A button that pushes without naming the remote is how
work reaches the wrong place.

**The path is taken from the row's record, never from the page's DOM.** A page
that can hand Swift an arbitrary path is a page that can open or commit
anything.

### 5.6 Gate

`CI-128 changes-are-shown-with-their-source` — **landed, 8 red runs.** Its
redaction assertion is DRIVEN, not grepped: a temporary git repository with a
real AWS key in a tracked file, because `_redact(` appears at several call
sites and a search over the file passed while the one that mattered had been
removed.

**A BUG THE BUILD FOUND AND THE PLAN COULD NOT HAVE.** The runtime executes
from inside the app bundle, so its `REPO` constant is a directory INSIDE the
owner's repository but not its top level. `git status` there still worked, the
card filled with eighteen rows, and every single diff came back empty — "+0
−0" on all of them. A card that is confidently wrong is worse than one that is
missing. `refresh_git` now RESOLVES the root through `git rev-parse
--show-toplevel` rather than trusting what it is handed. Assertions:

1. Every VESPER file write produces exactly one changes entry with a real diff
   (added/removed counts match `difflib` over the same two texts).
2. A git-tracked path is labelled `git`; a workspace path is labelled `vesper`;
   git buttons are disabled on `vesper` rows — asserted on the rendered state,
   not on intent.
3. The diff store is capped and trims OLDEST; it never exceeds
   `CHANGES_MAX_ENTRIES`.
4. Secrets are redacted: a write containing a known key pattern produces an
   entry with the key replaced, on BOTH sides of the diff.
5. `changes.jsonl` is not consulted by any evidence path — a grep for it in
   `core/evidence.py`, `core/verify.py` and `core/memory.py` is red.
6. Deletion is represented: removing a file produces a `status: deleted` entry
   with the removed content as the diff's minus side.

Red run: emit an entry with counts that disagree with `difflib`; enable git
buttons on a workspace row; skip the redactor; let the store grow unbounded.

---

## 6. THE TERMINAL BAR

**What the owner asked for:** *"an expanding bar under the changes card, same
width as the cards above it, expands to my terminal where i can run my
commands, design should be the same as vesper's home design, not terminal's
design."*

### 6.1 The safety requirement, which comes before every feature in this section

**This is the owner's shell, and no path may exist from VESPER, from
`home.json`, from a model, or from any file VESPER writes, to a PTY write.**

The only things that write to the PTY:

1. a keystroke the owner typed into the terminal element, and
2. an explicit click on a **Run** button, in a gesture the owner made.

**BUILT STRONGER THAN THE PLAN.** The doc proposed two message names, one of
which writes and one of which does not. The stronger form, and the one that
shipped: **paste has no bridge at all.** `TerminalBridge` has one writer,
`write(_:)`, reached by one message, `input`, posted from exactly two gestures
— a keypress in the terminal's field, and a click on Run. "Paste without
running" happens entirely in the page: it sets an input element's value and
returns. There is no Swift function for it, so there is no code path from it to
a file descriptor to get wrong. A second message with a `run: false` flag would
have been one inverted condition away from being a writer, and that inversion
is invisible in review.

### 6.2 The PTY

Spawned by Swift with `posix_openpt` / `forkpty`:

- The **owner's** login shell (`$SHELL`, falling back to `/bin/zsh`), the
  **owner's** environment, the **owner's** `PATH` — this is their terminal, not
  VESPER's. It is **not** seatbelted; the sandbox in `core/capabilities.py`
  bounds VESPER's actions, and this is not one.
- `TERM=xterm-256color`, cwd = the enclosing repository, resized on open.
- Reaped after 900 s idle; a running process blocks it.
- Output is streamed to the page and rendered by a **minimal ANSI renderer**
  (SGR colour, CR, backspace, cursor forward/back, erase-to-end-of-line).
  **No xterm.js**: the owner asked for VESPER's design, not a terminal's.

**THREE THINGS THE FIRST RUN TAUGHT.** The pane worked on its first command and
was unreadable, and each cause is worth recording because none was predictable
from the plan:

1. **The CSI pattern did not accept `?`.** Bracketed paste is `ESC [ ? 2 0 0 4
   h`, so every private-mode sequence a shell emits fell through and printed as
   `?2004h`.
2. **zsh's line editor re-enabled echo.** Turning `ECHO` off in termios was
   undone the moment ZLE started, and ZLE redraws the command as each byte
   arrives — `echo readable` arrived as three lines reading "ech", "o", "o
   readable". The fix is not to fight the redraw but to turn the editor OFF:
   `zsh -o nozle -il` still sources the owner's `.zshrc`, so their aliases,
   functions and PATH are all present, and the page prints the submitted line
   once in VESPER's own prompt colour. The cost, stated plainly: no tab
   completion and no arrow-key history inside this pane. Only for zsh — `-o
   nozle` would leave a bash user with no shell at all.
3. **`nopromptsp`/`nopromptcr`.** zsh guards against output with no trailing
   newline by printing an inverse `%`, padding to the terminal width, and a
   carriage return. Designed for a screen that overwrites; rendered by a
   line-oriented pane as a stray `%` and a row of spaces before every prompt.

**AND WHAT IT DOES NOT DO**, said once here and once on screen the first time
it matters: full-screen programs. `vim`, `htop` and `less` repaint with cursor
addressing this renderer does not implement, and the pane says so rather than
leaving the owner to work it out from the mess.

### 6.3 Rendering

VESPER's glass, VESPER's type stack, VESPER's palette. Mono is the one
departure — a terminal that reflows proportionally is unusable — and it uses
the same mono the code blocks in §3 and §4 use. The bar collapsed is 34 px with
a single line of the last output, dimmed.

### 6.4 Gate

`CI-129 the-terminal-is-the-owners` — **landed, 6 red runs**, and it is the one
check in this chunk that must never be weakened for convenience: every
assertion is about something NOT existing. Three of its first six probes passed
under their own violation and had to be rewritten — a `case "input", "paste":`
that a regex anchored on `case "paste"` cannot see; a `reapIfIdleX` that still
contains the substring `reapIfIdle`; and a region read 900 characters from
where the paste BUTTON is created rather than from where it is HANDLED. Assertions:

1. **No call path reaches PTY-write except from the two named gestures.**
   Parsed from the Swift source: the function that writes the file descriptor
   is called from exactly the input handler and the run handler, and from
   nothing else.
2. `vesperTermPaste` holds no reference to the PTY — asserted structurally.
3. The PTY is spawned with the owner's `$SHELL` and environment, and **is not**
   wrapped in `sandbox-exec`.
4. Nothing in `home.json` can reach the terminal: the poll's push touches
   `__vesperStage`, `__vesperHistory`, `__vesperWork` and the new card
   functions, and **not** the terminal's input.
5. Idle kill fires, and does not fire while a foreground process runs.

Red run: give Paste the PTY handle; call the write from the state-push path;
wrap the shell in the seatbelt; remove the idle kill.

---

## 7. COMMAND BUTTONS IN THE CARDS

**What the owner asked for:** *"the commands vesper puts in the answers card or
explanations card should have a button to either run them on that terminal,
paste them on that terminal without running, or ask vesper about them (they go
with the prompt), copy them."*

Any `{"kind": "code", "lang": "bash|sh|zsh"}` block, in the explanations card
or the conversation card, renders four buttons:

| Button | Channel | Effect |
|---|---|---|
| **Run** | `vesperTermInput` | Expands the terminal, writes the command + newline |
| **Paste** | `vesperTermPaste` | Expands the terminal, fills the input buffer, **runs nothing** |
| **Ask** | `vesperSay` | Sends `"about this command: <cmd>"` as a turn |
| **Copy** | — | Clipboard |

**RUN IS ALWAYS A DELIBERATE CLICK AND IS NEVER DEFAULTED.** No keyboard
shortcut, no Enter-to-run, no "run on expand". The command is visible in full
before the click — a truncated command with a Run button is forbidden, because
the owner must be able to read what they are about to execute.

Gate: folded into `CI-129` — a paste handler that reaches the terminal channel
is red, and so is any renderer that can.

**ONLY ON SHELL BLOCKS.** A `python` block is code to read, not a line to hand
to zsh, and a Run button on one is an invitation to paste a program into a
prompt. `bash`, `sh`, `zsh`, `shell` and `console` get the bar; nothing else
does.

---

## 8. CROSS-CUTTING RULES

These apply to every card above and are gated once, in
`CI-127 the-surface-never-renders-model-output-as-markup`:

1. **No `innerHTML` anywhere content derived from `home.json` is rendered.**
   `textContent` only. Parsed from the page source, not grepped.
2. **Every value crossing Swift → page is escaped**, using the existing `esc()`.
   The comment there already says why: *"the day one carries a model's output is
   the day that stops being theoretical."* That day is this chunk.
3. **Every list is capped and every cap is named**, with the truncation visible
   in the surface.
4. **Nothing new polls.** One tick.
5. **Collapsed by default.** The stack fits on the smallest supported screen
   with every card collapsed; that is asserted against the computed geometry.

---

## 9. DEFERRED, WITH WHAT THEY WOULD NEED

The owner named these in the same chunk and they are deliberately not in the
build order below.

**Screen observation** — *"it needs to see my screen activity and be able to act
on it when i tell it to"*. Needs `NSScreenCaptureAccess`, a new TCC grant. The
owner has an outstanding grant trip already (speech, calendar, reminders,
accessibility); adding a fifth mid-flight multiplies a trip that has already
been wasted twice by rebuilds. **Design constraint to record now:** a captured
screen is `retrieved_external` of the strongest kind — it can contain any text
on the machine, including another app's — so it must reach the planner through
`observe()` and never raw, and `permission_mode.observations_taint` must NOT
waive it even in auto mode. That is a deliberate exception to §auto and is
noted here so it is not discovered later.

**Window control** — *"it needs to open windows and work inside them"*. Needs
Accessibility (already on the grant trip) plus a window-target vocabulary in
`contracts/policy/host_actions.toml`, which exists and has no window verbs yet.
`ui.open` is the one window action today.

---

## 10. BUILD ORDER

Each step ends with the §0 gate. **No step begins before the previous one has
been driven against the running surface.**

| # | Step | Ships |
|---|---|---|
| 1 | Stack geometry in Swift + `{{STACK_CSS}}` | Three empty cards in the right places, correct on a resize |
| 2 | **Commands card** (§3) | `CI-123`, live: a real `shell.run` appears with its output |
| 3 | **Explanations card** (§4) | `CI-124`, live: a long answer lands here and is not spoken |
| 4 | **Changes card** (§5), list + diff + open-in-IDE | `CI-125`, live: a real write appears with a real diff |
| 5 | Changes overlay, view controls, git buttons | live: push/pull/create each confirmed and executed once |
| 6 | **Terminal** (§6) | `CI-126`, live: the owner types and gets a shell |
| 7 | **Command buttons** (§7) | live: Run runs, Paste does not |
| 8 | `CI-127` cross-cutting | red-run on each of its five rules |

Steps 2, 3 and 4 are what the owner named as the starting point.
