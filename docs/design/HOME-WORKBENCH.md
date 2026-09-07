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

## 0b. HOW THIS DOCUMENT IS WORKED

**Owner's instruction, 2026-09-07, and it governs every session from here.**
This file is the TRACK. It is not a record of a finished chunk; it is the
thing being executed, and §10's build order is the position marker.

| What happens | What the session does |
|---|---|
| The owner adds something, or asks for something | **Append it to the plan**, then keep going from where the track was. |
| The owner reports something wrong, or a bug | **Fix it**, then resume at exactly the point the track was left. |
| The session finds a bug or issue the owner has NOT raised | **First** write it into this doc — what it is, why it happens, how to fix it. **Then** raise it with the owner. **Then keep going on the track** without waiting. |
| The owner reviews that finding and approves it, or proposes a different approach | **Append the outcome** and mark the item **planned**. |
| The owner says "do it now" | Do it now, mark it **done**, then return to the track where it was left. |

**THE ORDER MATTERS AND IT IS THE POINT.** A finding raised in conversation and
not written here is a finding that survives exactly as long as the context
window does. This corpus has lost work that way before -- the whole reason §0
opens with "it states steps, never intentions". So: **doc first, then the
owner, then carry on.** Never the reverse, and never "I will write it up
after".

**AND NOTHING WAITS ON A REPLY.** The owner explicitly does not want the
session stopping to report. A finding is written, raised, and left; the track
continues. Approval changes the item's status, not the session's momentum.

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

## 9b. THE HOST CARD HAD A PRODUCER AND NOTHING CALLED IT — FIXED

Not part of the owner's request; found while building the stack, and fixed
because the card sits in the middle of it reading "no producer".

**THE SEVENTH "BUILT AND REACHED BY NOTHING" IN THIS TREE.**
`tools/home_snapshot.py` has produced the rows since it was written and
`core/home_state.set_rows` has accepted them for just as long. Nothing ever
called either.

**AND THE CARD'S OWN INSTRUCTION WOULD HAVE BROKEN THE HOME.** It read "run
home_snapshot.py", and `main()` wrote `{"version": ..., "rows": ...}` over the
whole of `home.json` — deleting the face, the transcript, the workbench and the
changes board. It writes through `HomeState.set_rows` now, which merges;
`--out` still writes a standalone file, because a projection dumped for
inspection is not the surface's live state.

**IT NEVER PROBES A MODEL.** `probe()` runs a real routed completion against a
local llama.cpp, and `MEMORY.md`'s rule for this machine is explicit: local
models heat it in a minute and cost tens of per cent of the battery in five, so
they are not to be run *or measured* here. The runtime calls `build(None)`,
which reads the last recorded completion if one is fresh and otherwise omits
those rows — `core/projection.py` drops an unavailable reading rather than
rendering one, "so the absent case cannot be styled into looking like the
present case". What always resolves is the power source, which is the row that
actually matters on a laptop.

**AND IT IS PUSHED ON THE TICK.** `{{METRIC_ROWS}}` fills the card once at
mount, so it was frozen at whatever was true when the home came up — and the
power source is exactly the row that changes while nobody is reloading.

---

## 9c. NOTES — QUEUED, AND NOT STARTED

**Owner's instruction, 2026-09-06: "put notes in the plan doc as next after
finishing everything else and leave them for now."** So this is the next item
after §10's remaining steps and the two deferrals above it, and nothing about
it is built.

**WHAT IS TRUE TODAY, SAID PLAINLY.** `core/agenda.py`'s own docstring quotes
the owner's loop as running on "calendar, notes, plans". `SOURCES` is
`("plan", "calendar", "reminders")`. **Notes appears in that sentence and
nowhere else in the tree** — no reader, no bridge, no usage description. A
docstring naming a source that does not exist is the exact defect this document
opens by warning about, and it has been sitting in that file since it was
written.

**WHY IT IS NOT A FIFTH LINE IN `AgendaBridge`.** Calendar and Reminders have
EventKit: a public read API, a TCC class of their own, and an authorization
call that returns a real answer. Notes has none of that. Reading it means Apple
Events — scripting the Notes app — which is a different permission class
(`NSAppleEventsUsageDescription`, Automation, and per-target consent), a
different failure mode (the app must be running or gets launched), and a
different trust class for what comes back.

**WHAT IT WILL NEED, so the next session does not re-derive it:**

1. `NSAppleEventsUsageDescription` in `build.sh`'s Info.plist, and a
   `--notes-consent` mode beside `--agenda-consent`. This is a SIXTH grant on
   a trip that already has five; it must be added to the same trip, not
   discovered later.
2. A `NotesBridge.swift` that scripts Notes for title, modified date, folder
   and body, and writes `agenda/notes.json` with the same shape and the same
   `written_at_s` freshness field `eventkit.json` uses — `EVENTKIT_FRESH_S`
   exists precisely so a stale source is UNAVAILABLE rather than quietly old.
3. `SOURCES` gains `"notes"`, and `quiet()` stays False while it is
   unavailable — the existing rule, which is what stops a missing source
   reading as an empty one.
4. **The trust class is the part to get right.** A calendar entry was written
   by the owner. A note may contain anything they pasted into it — a web page,
   an email, someone else's text. It is `retrieved_local` at best and must
   reach the planner through `observe()`, never as an instruction. A note
   saying "delete the old backups" is a note, not an order.

---

## 9d. PROVIDER FAILURES — THE OWNER'S POLICY, NOT YET BUILT

**Owner's instruction, 2026-09-06, in their words, recorded here so it stops
being re-explained.** They have said this before and it has not been built. It
is queued immediately after §9b (Notes).

Today every provider failure lands in one place: retry, then classify, then a
triage item the owner never sees, and a sentence on the stage reading *"that
provider returned an error"*. That sentence is the whole of what the owner
gets, and it is true of five completely different situations that call for five
different responses.

**THE FIVE CASES AND WHAT EACH ONE OWES THE OWNER:**

| The failure | What VESPER does |
|---|---|
| **Usage limit hit** | Retry. This is the ONLY case where plain retrying is the right answer — the request was fine and the world will change on its own. |
| **Bad request / VESPER's own mistake** | **Fix the request and send a good one.** Not retry the same malformed call: the wire format, the argv, the field that was wrong is VESPER's to correct, and re-sending it unchanged is the definition of a loop. |
| **The provider dropped that model** | Mark THAT MODEL unavailable and use another **from the same provider**. Not a failover down the whole ladder — the account, the credential and the egress class are all still good; one row's `model` is not. |
| **Anything else** | **Investigate, prepare a fix plan, and ASK.** Permission granted → do it. |
| **A fix VESPER cannot make** | **Explain it, and give a manual guide.** |

**AND WHERE EACH PART GOES ON THE SURFACE, which is the half that is new:**

- The **explanation** — what broke, what was tried, why — goes to the
  **explanations card**. It is long, it is not spoken, and §4's split already
  routes exactly this shape.
- **Asking for permission, and raising the issue at all**, goes to **VESPER's
  talk** — the stage and the conversation card. A question the owner has to
  answer belongs where they are already looking, not on a board.

That division is the owner's, stated twice, and it matches the split §4 already
built: the sentence is spoken, the detail is shown, and the two are joined by
the turn.

**WHAT EXISTS TO BUILD ON.** `core/triage.py` already grades and stores
attempts with their detail; `core/repair.py` already proposes a patch and
already refuses to apply it to the running system (`INV-SELF-1..7`, `A-030.6` —
a patch plus its failing test goes to `workspace/` for review). `gateway.py`
already has `TERMINAL` and a classifier. What is missing is the ROUTING: which
class goes to which of the five, and the two surfaces above. The classifier
also has to stop conflating cases — 2026-09-05's `FileNotFoundError` was filed
as `bad_request`, so triage recorded VESPER'S OWN DEFECT and the repairer
proposed a patch to a wire format that was never wrong.

**TWO MEASURED TRAPS TO CARRY IN, AND THEY WERE THE SAME SYMPTOM.**

`claude-advisor` returned `server_error` for weeks. It was two different faults
wearing one classification, and the second only became visible once the first
was gone.

1. **The credential was unreachable** — fixed 2026-09-06. It lives in the login
   keychain; a launchd job cannot read it, because the item's ACL names the
   binaries allowed to read it without prompting and a background job cannot
   answer a prompt. No amount of request-fixing helps, the model was never
   dropped, and it was not a usage limit. That is case FOUR — investigate,
   explain, ask. Fixed with a per-account headless token.

2. **A REAL USAGE LIMIT, STILL CALLED `server_error`** — measured 2026-09-07
   with the token in place and the runtime's exact environment:

   ```
   You've hit your session limit · resets 3:50am (Africa/Casablanca)
   ```

   That is case ONE, the only case where plain retrying is correct — and the
   classifier calls it a server fault and retries it **ten times** against a
   limit that resets in hours. The elapsed time is the tell and nothing reads
   it: 31 ms when the binary could not authenticate, 2,295 ms when it
   authenticated and was refused.

**SO THE FIRST THING THIS WORK MUST DO IS READ THE CLI'S STDERR.** Both faults
say plainly what they are — `Not logged in · Please run /login` and `You've hit
your session limit` — and both arrived as `server_error` because nothing looks
at the text. A classifier that cannot tell an exhausted subscription from a
broken wire format cannot route any of the five cases, and every case above
depends on it. That is step one of §9d, not a detail of it.

**AND THE ADVISOR SHARES THE OWNER'S OWN ACCOUNT.**
`~/.config/vesper/claude-advisor` is `<owner-email>`, which is also
the account the owner's own Claude Code runs on — so VESPER's advice competes
with the owner for one session limit, and the owner hits that limit without
VESPER having done anything unusual. The separation the contract describes is
real (`claude-vesper` is a genuinely different account, with its own keychain
item) but it protects VESPER's ORDINARY WORK, not the owner. Owner's decision,
recorded 2026-09-07: the advisor stays on their account deliberately. The
routing should therefore treat an advisor usage limit as expected weather
rather than as a fault — it is the owner and VESPER sharing a room.

---

## 9e. THE ISLAND HAS NOT CAUGHT UP — QUEUED LAST

**Owner's instruction, 2026-09-06: "the island also doesn't show some stuff we
just built, it was blocked before because they weren't built yet, but now we
have them and they should be integrated there."** Queued LAST, at their
request, after §9c (Notes) and §9d (provider failures).

The island is the notch element — the surface that is visible when the home is
not. Several of its slots were left empty because the thing they would show did
not exist. It now does: commands, explanations, the changes board, the
terminal's state, and the permission mode.

**AND IT RENDERS NO TEXT AT ALL TODAY.** Measured 2026-09-06 while looking for
somewhere to put a status line: there is no label, no `NSTextField`, no
`CATextLayer` anywhere in `app/island-macos/`. Whatever is integrated has to
bring its own text rendering, and that is the bulk of this work rather than the
wiring.

---

## 9f. "5 FOREIGN WINDOWS" ON AN EMPTY DESKTOP — MEASURED, PARTLY FIXED

The owner pressed the globe three times and no VESPER appeared. The home was
alive and printing `here now: 5 foreign window(s) — not VESPER's Desktop` to a
log file on a two-second timer. The owner's answer: *"desktop 2, it's desktop
was already empty, no windows were open there"*.

**WHAT THE FIVE ACTUALLY WERE.** A count is not a diagnosis, so `--spaces` was
added — a mode that prints every on-screen window with its owner, layer and
size instead of a number. It named them: Terminal, Finder, Notes, Reminders and
Calendar. **Those are Desktop 1's windows.** The owner was on Desktop 2.

**SO THE READING IS NOT RELIABLE FROM A BACKGROUND PROCESS.**
`CGWindowListCopyWindowInfo(.optionOnScreenOnly)` is documented as the active
Space's windows, and for a process with no window on the active Space it does
not track the Space the OWNER is looking at. `SpaceWatch.fingerprint()` is
therefore answering a different question from the one the home asks it, and it
fails in the direction that refuses to start.

**WHAT WAS FIXED, AND WHAT WAS NOT.** The explicit path no longer consults it:
the globe launch drops `--on-empty-desktop` entirely, because pressing that key
three times is the owner saying "come here, now", and their own rule
(2026-08-24) is about VESPER not taking "something i have work on" — which is
about VESPER helping itself, not about VESPER answering when called. The LOGIN
agent keeps the flag, because that one does start unasked and erring toward
refusing is correct there.

**WHAT IS STILL OPEN:** a reading of the owner's active Space that works from a
background process. Without one, the login path can still decline to start on a
Desktop that is genuinely empty. The public API does not appear to offer it;
the honest options are a helper window on each Space, or accepting that the
login path is best-effort and the globe is the reliable one. Not decided.

---

## 9g. THE MICROPHONE HEARS, BUT ONLY IF YOU SHOUT — QUEUED LAST

**Owner, 2026-09-07: "vesper's microphone is working, but it still doesn't hear
me, i need to be screaming just so it can hear me."** They could not test it
properly — people were asleep next to them — so the cause is REPORTED, not
established. Queued after §9e.

**WHAT THE CAPTURE PATH ACTUALLY DOES TODAY** (`app/island-macos/Listener.swift`):

```swift
let format = input.outputFormat(forBus: 0)
input.installTap(onBus: 0, bufferSize: 1024, format: format) { buf, _ in
    req.append(buf)
}
```

Whatever the hardware produces is handed straight to the recogniser. **There is
no gain stage, no normalisation, no level measurement and no automatic gain
control anywhere in the file.** If the built-in microphone's input level is
low, the recogniser receives a quiet signal and behaves exactly as reported:
it works, and only for a raised voice.

**MEASURE BEFORE CHANGING ANYTHING — `INV-HW-2` applies here as much as it does
to throughput.** Four readings, in this order, and none of them needs the owner
to speak loudly:

1. **The system input level for the built-in microphone.** If it is low, this
   is over before it starts and no code changes.
2. **The RMS of the tap buffers while the owner speaks normally.** `Listener`
   already has a `diagnose` flag; it prints the transcript and confidence and
   NOT the level. Add the level. A number here separates "the signal is quiet"
   from "the signal is fine and the recogniser is strict".
3. **The confidence values on those same utterances**, which `--diagnose`
   already prints. Low confidence on a clean loud signal is a different fault
   from no result at all.
4. **Whether it is the WAKE WORD or the dictation.** The wake path matches
   against a fixed vocabulary and the dictation path does not; "it does not
   hear me" may be one of them and not the other, and they fail for different
   reasons.

**LIKELY FIXES, IN THE ORDER THEY SHOULD BE TRIED** — each cheap, each
reversible, none to be applied before the measurement above says which:

- Raise the device input level, if that is what reading 1 shows. No code.
- Apply gain to the buffer before `req.append`, scaled from a measured RMS
  target rather than a constant somebody liked.
- Lower the confidence floor the wake matcher uses, IF reading 3 shows good
  transcripts being discarded. This is the one to be most careful with: a lower
  floor is also more false wakes, and `core/floor.py`'s whole design is about
  not acting on things the owner did not say.

**WHAT MUST NOT CHANGE.** `requiresOnDeviceRecognition = true`. The comment
above it calls it "THE LINE": the API default is server-side, and turning it
off would send every word the microphone hears to Apple — egress that bypasses
`ModelGateway` and therefore the redactor. Nothing about a loudness problem
justifies touching it.

---

## 9h. EVERY BUILD COSTS THE OWNER A FIVE-GRANT TRIP — FOUND, NOT RAISED BEFORE

**Found by the session, 2026-09-07. Not reported by the owner.** Recorded here
first, per §0b.

**THE FACT.** `build.sh` re-signs the bundle ad-hoc on every build. macOS keys
TCC grants to the code signature's cdhash, so **every build makes VESPER a new
application to TCC and all five grants revert to `notDetermined`.** Already
measured and written into `CLAUDE.md`: granted at cdhash `6bd67687…`,
`notDetermined` at `59b04339…` five builds later.

**WHY IT NOW MATTERS MORE THAN IT DID.** It used to cost one grant. It now
costs five -- microphone, speech recognition, calendar, reminders,
accessibility -- across two `open -n` commands and one manual System Settings
step. Notes (§9c) makes it six. The owner has already done this trip three
times in two days, and **every remaining item on the build order requires a
rebuild**: §9c adds an Info.plist key and a Swift file, §9d changes the bundled
runtime, §9e is Swift. So the cost is not occasional, it is per-item.

**THE HONEST OPTIONS, none of them free:**

1. **A Developer ID certificate** ($99/yr Apple Developer Program). A stable
   signing identity means a stable TCC identity, and grants survive every
   build. This is the actual fix and it is the owner's money and their Apple ID
   to decide about.
2. **BATCH THE BUILDS.** Change nothing structural; do all repo work for
   several plan items, build ONCE at the end, and spend one grant trip for the
   batch. Costs nothing but delays live verification -- and §0's rule 2 says a
   step is not finished until it has been driven against the running surface,
   so items would be "code complete, unverified" until the batch build. That is
   a real weakening of the gate and must be stated when it is used.
3. **Do nothing** and pay the trip per item.

**WHAT IS NOT AN OPTION.** A self-signed certificate. It gives the stable TCC
identity AND makes launchd refuse to spawn the login item with
`OS_REASON_CODESIGNING` -- already tried, already in `CLAUDE.md`, and the
keychain still holds the unused cert from that attempt.

**RECOMMENDED:** option 2 as the working default -- batch the builds, state
plainly which items are code-complete-but-unverified at any moment -- and
option 1 raised to the owner as the thing that actually ends it.

**STATUS: raised, awaiting the owner's decision.**

---

## 9i. `f5-acceptance` FLAKES UNDER THE FULL SUITE — FOUND, NOT RAISED BEFORE

**Found by the session, 2026-09-07. Not reported by the owner.**

`checks.py all` reported `f5-acceptance` FAILED with *"a heartbeat is emitted
per tick, durably — 6 heartbeat events"*. Run on its own, seconds later, the
same gate PASSES — twice, with the runtime up both times, and
`run_f5_acceptance.py` directly reports `A-029-RT PASS`.

**WHY IT IS A FLAKE AND NOT A REGRESSION.** A-029-RT counts heartbeats over a
COMPRESSED simulated clock and asserts the count matches a declared cadence
(~240 in the window). Under the full suite it saw 6. A count that low is not a
broken heartbeat; it is a gate that did not get enough CPU to tick while a
hundred and thirty-eight other checks were running beside it.

**WHY THAT MATTERS MORE THAN THE FLAKE.** This gate's own text says the literal
24-hour endurance run is OWED and that the compressed run stands in for it. A
compressed run whose result depends on machine load is not standing in for
anything — it will pass on a quiet machine and fail on a busy one, and both
answers are about the load rather than about autonomy. **A gate that flakes is
not evidence, and this tree's rule is that a check which cannot fail for its
own reason is not a check.**

**THE FIX IS NOT A RETRY.** Re-running until green is how a flaky gate becomes
permanent. Either the cadence assertion is made independent of wall-clock
scheduling — the simulated clock should be driven by the test, not raced
against — or the gate declares itself unrunnable under load and says so
instead of failing.

Not fixed here: it is not on the owner's list, and changing an acceptance gate
that guards an OWED endurance run is not a thing to do in passing.

---

## 9j. WHAT STEP 11 ACTUALLY CHANGED

Recorded because the owner stated this policy twice before it was built, and a
future session should be able to see what landed without re-deriving it.

**THE CLASSIFIER READS THE TEXT** (`routing/supply.py`). Every non-zero exit
from a CLI rung was `server_error` unconditionally, and the message was built
from `cp.stderr` alone — while `claude` answers on STDOUT and leaves stderr
empty. The record said `claude-advisor exited 1: ` and nothing else. Both
streams are read now, the reason travels with the classification, and
`CLI_FAILURE_PATTERNS` maps the text onto the owner's cases. The pattern ORDER
is load-bearing and asserted: "invalid api key" contains "invalid", and a model
"no longer available" contains "available".

**A SESSION LIMIT CARRIES A REAL BACKOFF.** `CLI_LIMIT_BACKOFF_MS` is fifteen
minutes — a floor, not a parse. The gateway's `LONG_WAIT_MS` then moves to the
next rung immediately rather than sleeping, which is the correct reading of
"retry": the world will change, but not while anyone waits for it.

**`model_gone` IS A CLASSIFICATION AND IS TERMINAL** (`core/gateway.py`). A
rung is a (provider, model) pair, so the model going away retires the ROW and
says nothing about the account. A classification in neither TERMINAL nor
TRANSIENT falls through to a computed backoff and is RETRIED, which for a
removed model is a request that cannot succeed, on a timer.

**TWO OF THE FIVE CASES HAD NO HANDLER** (`core/repair.py`). `rate_limited`
and `model_gone` fell to `_escalate`, which reports "no tier-1 action exists" —
filing a gap in VESPER's own repair rules against a provider behaving exactly
as designed. Measured: an exhausted session limit produced a triage item, a
repair attempt and a proposed patch.

**AND IT REACHES BOTH SURFACES** (`_surface_repair` in the runtime). The board
gets typed blocks; the talk gets ONE sentence that differs by case. Only on a
CHANGE, never on the half-hourly keepalive, and the explanation is keyed on the
item so a rung failing the same way twice updates rather than stacks.

**THE GATE CAUGHT THE THING A NEW CLASSIFICATION BREAKS.**
`narration-complete` refused to load: every classification the gateway can
produce needs a spoken line, or the owner gets silence at the moment they are
waiting to be told something. `model_gone`'s line was added with it.

**CASE TWO, CORRECTED BY THE OWNER THE SAME DAY.** This section first said
case two "stops at PROPOSING a patch", citing `INV-SELF-1..7`. The owner's
answer: *"no vesper doesn't propose a fix, it's vesper's problem in the first
place ... vesper should either fix it and resend the request without actually
saying it, it only shows up in explanations, actions, and everywhere
necessary."*

**THEY WERE RIGHT, AND THE INVARIANT WAS BEING MISCITED.** `INV-SELF-1..7` is
about the runtime editing its own SOURCE. Building the next request correctly
is not self-modification — it is the job. Quoting the invariant at it turned a
one-field correction into a patch for the owner to review.

**SO THE GATEWAY FIXES IT AND RE-SENDS.** `ModelGateway._repair_request` reads
what the provider said and corrects the request: halve a budget the vendor will
not take, drop the sampling knobs it does not accept, drop an unknown option,
fold a system turn into the prompt. Then it retries — **once per rung**, and
that bound is the whole safety of it. `repaired` is set before the retry, so a
provider that rejects the corrected request is terminal exactly as it was: this
can add one attempt, never a loop.

**AND IT DOES NOT SAY SO.** `bad_request` is in `SILENT_ON_THE_TALK`. The
board still gets all of it — what was rejected, what changed, whether it worked
— because a silent correction nobody can inspect is what this tree refuses
everywhere else. What it does not get is a sentence read aloud, because there
is nothing for the owner to decide.

**THE PROPOSAL PATH SURVIVES AND MEANS SOMETHING SHARPER NOW.** Reaching
`RepairAgent._bad_request` means the obvious correction was tried and the
provider rejected the request anyway. That IS a wire-format defect, it will
recur identically, and a code change is the honest answer — proposed, never
self-applied.

---

## 9k. THE MENUS ARE HANDED TO A SECOND AGENT — PARALLEL, NOT SEQUENTIAL

**Owner, 2026-09-07: "any way of having another agent (codex) working on all of
them simultaneously while you do your work? it's just we don't have much time
left (only one week)."**

Yes, and the menus are the right slice: visual and interaction work, no
invariant touched, currently placeholders. Brief:
`docs/planning/CODEX-BRIEF-MENUS.md`.

**IT ALSO SPENDS A DIFFERENT BUDGET.** The Claude rungs share two
subscriptions and the owner hit a session limit on one of them today. Codex has
its own account — so this is parallel in money as well as in time.

**THE COLLISION IS ONE FILE, AND IT IS HANDLED BY MARKERS.** Everything renders
through `home.html`. Explicit `==== MENU ====` markers are now in the CSS and
the markup; codex works inside them and nowhere else. That is cheaper than
branching, because the checks read the whole file and a branch would have to be
merged before anything could be verified.

**TWO RULES THE SECOND AGENT CANNOT BE EXPECTED TO KNOW, so the brief leads
with them:**

1. **Never run `build.sh`.** Every build re-signs ad-hoc and macOS keys TCC to
   the signature, so a build silently revokes all six grants and costs the
   owner a manual trip. `HomeChrome.template()` reads the repo copy first —
   markup changes need no build at all, and `--chrome-probe` verifies them.
2. **Never edit `fallbackTemplate()`.** It is generated; `CI-065` compares it
   byte for byte. This session regenerates it.

**WHAT STAYS HERE:** anything touching the authority ladder, the provider
routing, the terminal, or a taint class. Those are where a plausible-looking
mistake is expensive, and they are not parallelisable across agents that cannot
see each other's reasoning.

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
| 9 | **HOST card producer** (§9b) | `CI-130`, live: the card shows a real reading |
| 10 | **Notes as an agenda source** (§9c) | ✅ DONE 2026-09-07 — `CI-131`, 5 red runs, live: 5 titles, `retrieved_local`, no bodies |
| 11 | **Provider-failure routing** (§9d) | ⚠️ CODE DONE 2026-09-07 — `CI-132` (5 red runs), `CI-133` (10 red runs), all five cases incl. fix-and-resend. NOT yet driven live: §9h, the rebuild costs the grant trip |
| 12 | **Island integration** (§9e) | owner-queued LAST, not started |
| — | **Main menu + expandable menu** (§9k) | HANDED TO CODEX 2026-09-07, brief written, markers carved |
| 13 | **Active-Space reading from a background process** (§9f) | open, no decided approach |
| 14 | **Microphone sensitivity** (§9g) | owner-reported, queued last, MEASURE FIRST |
| — | **TCC grants die on every build** (§9h) | found by the session, RAISED, awaiting a decision |
| — | **`f5-acceptance` flakes under load** (§9i) | found by the session, RAISED, awaiting a decision |

Steps 2, 3 and 4 are what the owner named as the starting point.
