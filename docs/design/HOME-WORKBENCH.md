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

**AND THE "IT RENDERS NO TEXT" CLAIM WAS WRONG.** It came from grepping for
`NSTextField` and `CATextLayer` and finding none. The island draws its text
with Core Graphics instead: `IslandView.drawPanel` already lays out a row of
`label` / `value` / optional `ratio` as attributed strings, and `drawGauges`
and `drawRightCluster` beside it. A grep for one way of doing a thing is not a
measurement of whether the thing is done — the same shape as a check satisfied
by a comment, which this tree has now hit in both directions.

So the work was not text rendering. It was FEEDING what was already there.

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

**THE FIRST BRIEF WAS WRONG AND THE OWNER CAUGHT IT.** It pointed at
`DESIGN-FOUNDATION.md`, which mentions menus twelve times in passing, and said
"the design is already decided". The owner's answer: *"is it really containing
everything needed on the main menu and expandable menu or not? ... i remember
putting there a lot, tens if not hundreds were specified."*

**THERE ARE 237.** `docs/design/routing/spec_raw.txt` is a routed requirements
corpus — `sec|name|INCLUDE|surface|note` — and 88 of its items land on the menu
surfaces: **17 routed `main`**, **51 routed `menu`**, 18 `float`, 2 `island`.
Nothing in `DESIGN-FOUNDATION` says any of that. A brief that sent a second
agent to invent from tokens would have produced a menu nobody specified, and
the corpus that specified it would have sat unread three directories away.

**AND THE SHAPE OF THE 51 IS THE DESIGN BRIEF.** They are overwhelmingly
readings about the machine and the fabric — memory pressure, thermal history,
power draw, node profiles, trust zones, placement decisions, blast radius. The
expandable menu is a panel of INSTRUMENT READINGS, not a launcher. That is not
inferable from the geometry.

**THE EIGHT MAIN-MENU MEANINGS ARE STILL THE OWNER'S TO CHOOSE.** §14.1b quotes
them on 2026-08-24 — *"only change is icons (we'll have to define them, then
get them or build them)"* — and answers it in the document's own words:
"Inventing eight icons and shipping them as though they were decided is how a
placeholder becomes a design nobody chose. **What is owed: eight icon meanings,
then eight icons.**" There are 17 candidates for 8 slots, which is exactly why
it is a decision and not a derivation. The brief forbids codex from making it.

**A SIXTH SURFACE WAS ALSO MISSING FROM THE FIRST BRIEF:** §14.2's **rail** —
four circular glass buttons at the right edge, labelled outside them,
`projects · research · history · settings`. Not a widget, not a card, not the
main menu.

**IT ALSO SPENDS A DIFFERENT BUDGET.** The Claude rungs share two
subscriptions and the owner hit a session limit on one of them today. Codex has
its own account — so this is parallel in money as well as in time.

**THE COLLISION IS ONE FILE, AND IT IS HANDLED BY MARKERS.** Everything renders
through `home.html`. Explicit `==== MENU ====` markers are now in the CSS and
the markup; codex works inside them and nowhere else. That is cheaper than
branching, because the checks read the whole file and a branch would have to be
merged before anything could be verified.

**THE BOUNDARY IS A TOOL, NOT A PARAGRAPH.** The owner asked "what if codex
breaks something?", and a brief cannot answer that — a brief is a request, and
an agent that misreads one or reasonably decides a file needs touching breaks
it either way, invisibly, until an unrelated gate goes red.
`tools/ops/codex_handoff.py` hashes every tracked file at handoff and NAMES
anything changed outside the agreement afterwards. Proven both directions
before use: a stray edit to `core/gateway.py` was reported by path, an edit to
the allowed file was not.

**THREE BACKUPS, EACH FOR A DIFFERENT FAILURE.** A git tag (undo the slice); a
tarball in `~/VESPER-backups/` **outside the repo**, because the owner asked
for a copy untouched by codex and anything under the working tree is reachable
by a careless `git clean` or an agent tidying up; and the agent's own working
copy, which it makes and must delete — `--verify` fails if it is left behind.

**AND THE BAR IS END TO END, not a rendered label.** Owner: *"we are now fully
building them end to end, not just icons or designs of just some
functionnalities in them."* Every shipped item has a real producer and renders
what it measured, or renders UNAVAILABLE and says why. `INV-HW-2`: a number
with no producer is not a reading. §9b is the cautionary tale in this same
document — the HOST card said "no producer" for weeks and the instruction
printed on it would have deleted `home.json`. The brief tells codex to ship
FEWER and FINISHED, ordered by what the owner can act on.

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

## 9l. ONE GATE IS EXPECTED RED WHILE THE MENU HANDOFF IS OPEN

`chrome-template-renders` compares `home.html` against the generated inline
fallback byte for byte. The second agent edits `home.html` and is told NOT to
regenerate the fallback — because `CI-065` would then be checking its copy
against its own copy, and because a generated file in two agents' diffs is a
conflict for no benefit.

**So the expected state during the handoff is 140/141, failing only
`chrome-template-renders`, with the message naming the fallback.** Anything
else red is a real break.

**Do NOT make the check tolerant of an open handoff.** A gate that knows about
a temporary workflow is a gate that can be switched off by creating one. The
sequence at handback is: regenerate, run the gates, expect 141/141.

**Verified in place, 2026-09-07:** codex's first edit landed — 11 insertions,
5 deletions, both marker pairs intact — and `codex_handoff.py --verify` read
`IN SCOPE`. The boundary and the gate are reporting different things about the
same edit, correctly: one asks "did it stay where it was told", the other asks
"are the two copies of the page identical yet".

---

## 9m. STEP 11 IS FINISHED, AND WHAT "FINISHED" MEANT HERE

Recorded because the owner asked "if 11 is genuinely finished" and the honest
answer needed three different kinds of evidence, not one.

**LIVE, ON A REAL PROVIDER.** The advisor's real session limit was read out of
the text and classified `rate_limited` — `server_error` before — with
`server_retry_after_ms: 900000` carried and `retry_after_ms: null`, meaning the
gateway declined to sit on a fifteen-minute wait while another rung existed.
Elapsed 2,211 ms: authenticated, then refused. That is the whole classifier
design working on a failure nobody staged.

**LIVE, ON THE SURFACE.** A `claude-advisor` explanation reached the board with
its blocks, from the real runtime, through `home.json`.

**AND ONE PATH THAT COULD NOT WAIT FOR PRODUCTION.** Fix-and-resend had never
fired, because no provider had returned a genuine malformed-request error since
it was written. Rather than claim it worked or manufacture a fake failure into
a contract, it was driven through the REAL `ModelGateway.complete` loop with
only the socket stubbed:

```
    reject 4096  ->  repair  ->  resend 2048  ->  answered "ok"
    provider that rejects the corrected request too
                 ->  budgets [4096, 2048], then AllProvidersExhausted
                 ->  exactly ONE repair. Never a loop.
```

**AND THE FIRST RUN OF THAT PROBE LOOKED LIKE A FAILURE AND WAS NOT.** The stub
rejected anything over 1,000 tokens, so the corrected 2,048 was refused as well
and the call ended exhausted — which is the one-shot bound behaving exactly as
designed. The bug was in the fixture's threshold, not in the loop. Worth
recording: a probe whose own limits are tighter than the thing it is probing
reports a defect that is its own.

---

## 9n. WHAT STEP 12 ACTUALLY WAS

**TWO CLOCKS, TWO KEYS, ONE FILE.** `tools/island_snapshot.py` owns the machine
readings — thermal, memory, swap, power — and refreshes them HOURLY, which
suits a laptop warming up and suits nothing about VESPER's own state. The
runtime writes its rows under `vesper` every few seconds and only when they
change. `IslandView` concatenates the two at draw time, which is the only place
both are wanted together.

**THE MERGE HAD TO BE FIXED FIRST**, and it was the same defect §9b records for
the home: `island_snapshot.py` wrote the WHOLE file, so any key another writer
owned was deleted **once an hour**. Nothing would have noticed for an hour.

**THE MOST USEFUL ROW IS THE ONE THAT HAD NO SURFACE ANYWHERE.** The permission
mode is a live authority state — in `auto` VESPER acts without asking — and it
was displayed on nothing. The owner switched it and then had to remember what
they had switched it to. It is the first row now.

Live: `Mode auto · Ran 5 · Changed 4`, with `Thermal · Memory free · Swap ·
Power` untouched beside them.

**AND A NEAR-MISS WORTH RECORDING.** The first version of `_publish_island`
used `os.getpid()` for its temp filename. `os` is not imported in
`vesper_runtime.py` — so it would have raised `NameError` on the first publish,
inside the `try/except` that turns it into a bus event nobody reads. The island
would simply never have updated, with no error anywhere a person looks. Caught
by checking the imports rather than by the parse, which was perfectly happy.

---

## 9o. THE MENU HANDOFF CAME BACK — AND MY OWN BOUNDARY HAD A HOLE

**ACCEPTED.** The second agent's slice is in: a real instrument tile opening a
native modal, the four-button rail, and a searchable conversation history.
Verified independently rather than taken on report — no poll, no fetch, no
second state file, no terminal bridge, no `innerHTML` on model-derived text,
both marker pairs intact, its own backup deleted.

**AND ITS HANDBACK WAS BETTER THAN ITS CODE, WHICH IS THE RARE PART.** It
declared twelve things UNAVAILABLE with reasons rather than shipping inert
labels, refused to make the probe green, and wrote down "do not describe a
JSON-to-DOM test as proof of current physical state". That is the standard this
document asks for, met by an agent that had read it once.

### The bug it found, which was mine

It reported the page showing `battery` while `pmset -g batt` said **"Now
drawing from 'AC Power'"**, and named the cause precisely: the row had no
observation timestamp or expiry.

**THE PRODUCER WAS CORRECT EVERY TIME.** `Reading` carries `observed_at`,
`core/projection.py` puts it on the scene element, and `pmset` is re-run on
every publish. **The FLATTENING to `{label, value}` discarded it** — my code,
in `_metric_rows`, written the day before. With no stamp the surface cannot
tell a reading taken a second ago from one taken this morning, and a runtime
that STOPS leaves its last values on screen looking current forever.

Fixed at both ends, because they are different claims: the runtime omits a row
past its TTL ("I measured this recently"), and the page refuses to render one
("what I am showing you was measured recently"). Dropped rather than dimmed —
`INV-HW-2`, and `core/projection.py`'s own rule that the absent case must not
be styled to look like the present one.

### THE HOLE IN MY OWN HANDOFF DESIGN

`--verify` compares the working tree against HEAD, on the reasoning that this
session commits and the second agent does not. **Then this session ran
`git add -A`** — twice — and swept the second agent's in-progress work into its
own commits, under its own messages. From that moment the boundary saw it as
committed, said `IN SCOPE`, and could no longer report it at all.

Nothing was lost: `git diff handoff/menus/<stamp>` recovers the whole
contribution, 451 insertions across two files, which is what the tag is for.
But the boundary stopped answering the question it was built for, and it did so
silently.

**THE RULE THAT FOLLOWS: while a handoff is open, this session stages named
paths, never `-A`.** A tool whose correctness depends on the other party's
habits is a tool with a hole in it, and this one had mine in it.

### What the second agent left owed, verbatim and unargued

Current power source (observation time and a refreshed producer — **now
fixed**), power draw, battery charge, battery health and lifetime, thermal
pressure, memory headroom, memory pressure band, compressor and swap, the
projects and research destinations, settings, the full action/decision history
space, and the remaining routed menu items. Its own words: *"Do not call
`home_snapshot.py --probe` or manufacture rows to make the probe green."*

---

## 9p. THE MENU HANDOFF BECAME A WORKTREE, AND STEP 13 GOT A DESIGN

Two things done the same session, both continuing work already on record.

**THE HANDOFF'S BOUNDARY TOOL DID NOT SURVIVE ITS OWN FIRST FAILURE.** §9o
found `codex_handoff.py`'s hole: it compares uncommitted changes to HEAD, and
once this session ran `git add -A` the second agent's work was committed and
the guard could no longer see it. The owner's next instruction, 2026-09-07
evening: *"tell it to work on a backup and leave implementation to the
original version to you, that way nothing breaks."* Rather than patch the
guard again, the isolation is now physical — `~/VESPER-codex-menus`, a real
git worktree on its own branch (`codex/menus-v2`), sharing this repo's object
store and nothing else. `codex_handoff.py` is retired for this handoff, not
patched; a tool answering a question that no longer applies is worse than no
tool, per the finding it was written to fix in the first place.

**VERIFIED BEFORE WRITTEN DOWN, not assumed:** `checks.py all`, both lints,
and `sync_chrome_fallback.py` all run clean from inside a worktree (`.git` is
a file there, not a directory — the thing most likely to break a stdlib tool
that assumes otherwise, and none of these do). `--chrome-probe` works from a
worktree via the same `cwd`-relative `template()` lookup that makes the
markup-editing loop fast in the first place. `--probe-shot` hangs
indefinitely and writes nothing, identically in the primary tree and a
worktree — not a worktree artifact, and not safe to build the icon-approval
step on. The metrics bridge (`home.json`'s `rows`, `HomeChrome.metricRows()`,
`window.__vesperMetrics`) is already a generic `{label, value, at_ms,
ttl_ms}` list — wiring any of the 51 catalogue items needs no Swift change
and no build. Full brief: `docs/planning/CODEX-BRIEF-MENUS-v2.md`. Handed to
the owner to run, 2026-09-07.

**STEP 13 GOT A DESIGN, NOT YET A VERIFIED FIX.** §9f's own two options were
a helper window or accepting best-effort. Re-read against evidence already in
this repo rather than tested fresh: `residency_probe` already proved
`fingerprint()` reliable once a `.managed` window exists — 151 samples,
foreign-window overlap 0.00 on real switches — and `HomeController.dock`'s
reconciler (`Home.swift`) reads the same signal, after the ground exists, and
is correct. The empty-Desktop poll (`--on-empty-desktop`, `main.swift`) is the
one caller that runs BEFORE any `.managed` window exists — the island's own
window is `.canJoinAllSpaces`, which gives the window server nothing to anchor
"this process's active Space" to. That gap, not a general unreliability, is
the more precise diagnosis §9f's own evidence already supports: Desktop 1 read
back as "here" while the owner was on Desktop 2, and Desktop 1 is where the
process would have started before any window of its own existed.

**THE FIX: `SpaceWatch.Anchor`**, a 1×1, alpha-0, non-interactive, explicitly
`.managed` (not `.canJoinAllSpaces`) window, created before the poll's first
tick and closed on whichever branch ends it. It borrows a mechanism this repo
already measured rather than inventing one. Wired into the
`--on-empty-desktop` loop in `main.swift`.

**COMPILED AND MECHANICALLY EXERCISED, NOT CROSS-DESKTOP PROVEN.** The full
`island` target compiles clean (`swiftc`, zero errors, pre-existing warnings
only, unrelated to this change). `app/home-macos/anchor_probe.swift` — new,
same convention as `residency_probe`/`ground_probe`/`adopt_probe` — creates
the anchor standalone and reads `fingerprint()` before and after. Run on this
session's single active Desktop: 2 foreign windows (Safari), identically
before and after the anchor. That is the expected result and it is not
evidence either way — before and after can only differ on a Desktop the
process did NOT start on, and this session has no public way to switch
Spaces, same limitation `residency_probe`'s own header names.

**THE OWNER-ASK, same shape as `residency_probe`'s:** with something open on
Desktop 1, switch to a different, empty Desktop, then run

```
swiftc -swift-version 5 -target arm64-apple-macosx13.0 \
  app/home-macos/anchor_probe.swift -o /tmp/anchor_probe && /tmp/anchor_probe
```

and report the two window counts. No build, no TCC, no app bundle touched.

**RUN, 2026-09-07 evening, conditions confirmed both times.** First attempt
came back `0`/`0` but with no confirmation Desktop 1 held anything — an
uninformative pass, said so rather than counted. Second attempt, explicitly
confirmed: Finder windows on Desktop 1, VESPER's own Desktop 2 genuinely
empty, run from the terminal card. **`0 foreign window(s)` both before and
after** — the read that would have been wrong (Desktop 1's windows, showing
up on Desktop 2's query) did not happen.

**WHAT THIS PROVES AND WHAT IT DOES NOT.** It proves the mechanism is safe —
matches `residency_probe`'s own measured behaviour, no crash, no interference
— and that the specific failure did not reproduce with a real foreign window
present. It does NOT byte-for-byte reproduce the original failure, which
happened at actual OS login: a process spawned fresh by launchd, not one
launched interactively from the terminal card mid-session, inside an
already-running VESPER whose main app may already carry window-server context
the login case would not have. The fully conclusive test is the real login
path, with this fix built in, picking the correct Desktop on its own — which
needs an actual rebuild and costs the six-grant TCC trip. Not spent on this
alone; left to ride into whatever next change justifies one. **Status: fix
implemented, mechanism verified safe and consistent with proven behaviour,
end-to-end login confirmation deferred to the next batched rebuild.**

---

## 9q. THE WORKTREE CAME BACK, MERGED, AND ONE REBUILD COVERED TWO FEATURES

Codex's Phase 2 run hit its own usage limit the instant after reporting it was
committing — checked rather than trusted: `~/VESPER-codex-menus` had a clean
tree and three real commits (`f997ef4`, `bf1e15c`, `66b5c8d`), no stray backup
directory, both marker pairs intact.

**INDEPENDENTLY RE-RUN, not taken on the handback's word.** From inside the
worktree: `verification/test_menu_projection.py` 13/13, both lints clean,
`checks.py all` 141/142 (`chrome-template-renders`, exactly the one reserved
for this session). A rule scan for `innerHTML`, `vesperTerm`, and private
Space/window selectors inside the `MENU` markers came back clean. The 17-icon
claim was checked in the markup itself, not just the prose: 17
`class="slot"` nodes.

**ONE CLAIM THIS SESSION CANNOT VERIFY, RECORDED RATHER THAN ACCEPTED.** The
handback states *"the owner approved all 17 main-bar icons and a wider bar"*
— a real amendment to the brief's 8-slot rule, made directly to codex in a
channel this session has no visibility into. Merged anyway, because the
owner had already said to proceed without waiting, but written into the
merge commit by name so it is discoverable and not silently normalized.
**Needs the owner's own confirmation that this is in fact what they told
codex.**

**MERGE WAS CLEAN.** `codex/menus-v2` and this branch diverged from the same
commit (`36b9a2a`) with disjoint file sets — no conflicts. Fallback
regenerated here per the brief's division of labor; full suite back to
`142/142`.

**THE REBUILD TURNED OUT TO BE NECESSARY, not optional.** `HomeChrome.template()`
tries the repo path first, so markup needs no build. `RuntimeHost.script()`
tries the **bundled** copy first, opposite order, for the opposite reason ("a
shipped app has no repo beside it") — so the already-running Python runtime
was serving the OLD bundle copy regardless of markup changes, and none of the
51 readings' new logic would have reached the screen without one. Since a
rebuild was genuinely required, it was made to cover this session's own
`SpaceWatch.Anchor` fix (§9p) in the same pass — one TCC trip for two
features rather than two.

**POST-BUILD, NOTHING WAS RUNNING**, and the build's own supervision retry
said so rather than claiming otherwise: `VESPER is supervised (pid )` — empty
— and the four satellite agents at `exit=-9`/`78` after its own six-pass
budget. Relaunched by hand, `open -n`, per the TCC-attribution rule in
`CLAUDE.md`. Confirmed running afterward, both the main process and its
runtime child, rather than trusting the launch command's own exit code.

**THE GLOBE KEY AND WAKE WORD ARE DOWN AGAIN.** §9h, not a new finding: every
build revokes every grant, and this one is no exception. The owner's grant
trip is still owed, unrelated to anything in this section.

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
| 11 | **Provider-failure routing** (§9d) | ✅ DONE 2026-09-07 — `CI-132` (5 red runs), `CI-133` (10 red runs). Live: real advisor limit read as `rate_limited` with the 15-min floor carried; board surfacing fired; fix-and-resend driven through the real gateway loop, 4096→2048→answered, one repair and never a loop |
| 12 | **Island integration** (§9e) | ✅ DONE 2026-09-07 — `CI-134`, 5 red runs. Live: Mode `auto`, Ran 5, Changed 4 beside the machine's rows |
| — | **Main menu + expandable menu** (§9k) | ✅ MERGED, REVERTED, CAUSE FOUND, RE-MERGED 2026-09-08 (§9r, §9s). The first merge killed all five stack cards; the cause was a token named inside a JS comment, latent for weeks and fired by the row count going 1 → 69. Now live alongside every card. 17-icon bar — **owner approved the 17 on 2026-09-08**, the brief's 8 is retired. 68 catalogue items, 32 carrying live readings |
| 13 | **Active-Space reading from a background process** (§9f) | fix implemented and owner-verified (§9p) — `SpaceWatch.Anchor`, confirmed `0`/`0` with Desktop 1 populated and Desktop 2 genuinely empty. The batched rebuild it was waiting on happened 2026-09-08 with §9t, and `--spaces` from a freshly launched background process correctly enumerated the active Desktop and refused it (`2 foreign window(s)`, ChatGPT) — so the anchor works off the login path too. **The LOGIN-ITEM path itself is still unconfirmed:** `ai.vesper.island` is not bootstrapped in the `gui/501` domain (only `.wake`, `.fnwatch`, `.agenda`, `.arm` are), so `launchctl kickstart` cannot reach it and a real login is needed. Not a prediction — a named, outstanding step |
| — | **The home's four model rows** (§9t) | ✅ DONE 2026-09-08 — `the-model-rows-read-a-real-completion`, 8 red runs. They had NEVER worked: no producer, and a comment claiming one. Live: `thinking = yes, 15 tok`, `context = 349`, `tokens = 466.4`. Found and fixed a pre-existing leak of menu rows into the HOST card in the same pass |
| 14 | **`f5-acceptance` flakes under load** (§9i, §11.0) | ✅ DONE 2026-09-08 — the gate compared a live in-memory counter against the durable store and reported its own sampling as a defect. Both negative controls driven RED. §9i's recorded cause was wrong twice over; §11.0 supersedes it |
| 15 | **Window management** (§11.1) | 🟡 IN PROGRESS 2026-09-09 — vocabulary, ownership rule, native bridge and capability ladder landed and DRIVEN LIVE. `a-window-belongs-to-someone`, 7 red runs. `window.open` drove live and its provenance stamp is real. **Driving it found a forgery path** (§11.1c): `reopen` claimed any newly-seen window, and returned one of the owner's Safari windows from `window.open("TextEdit")` — fixed by requiring the launched pid and a cross-Desktop frontier. **Owed:** placement verification (§11.1c) and rung 3, which has never executed. The forgery check DID land -- `a-window-is-claimed-only-by-the-app-that-opened-it`, 8 self-test cases, counting claim sites rather than looking for a name -- and this row went on saying it was owed until 2026-09-10 |
| 15a | **Placement is verified, not predicted** (§11.1c) | 🟡 PART DONE 2026-09-09 — `window_open` now READS BACK where the window landed and reports `degraded` with a flag instead of `ok: true`; the two false comments are corrected. Also fixed: vesper claimed TextEdit's **Open dialog** as a window it opened, so the launch rung now requires a close button. **Owed:** the close-and-reopen rebuild, which needs a bridge that can reach a window on another Desktop — every act matches through `SpaceWatch.onScreen()`, one Desktop only |
| 15b | **Window memory across a restart** (§11.8) | ✅ DONE 2026-09-09 — **authority:** boot-keyed, corroborated against the live window, fail-closed on every unreadable state; `CI-138`, 7 red runs; driven across processes (one interpreter opened window 33429, a second read it back as vesper's). **history:** `core/window_log.py` — appends what vesper touched, an absent title carries a code (`no_file`, `no_file_model`, `unreadable`), old weeks compress in place and read back through the same call, the current week stays near, and **nothing in it can open a window**; `CI-139`, 5 red runs. `gated-subsystems-are-reachable` caught the module unwired the moment it landed |
| 15c | **The flag bar** (§11.9) | ✅ DONE 2026-09-09 — small bar above the main menu, hidden when empty, buttons revealing the flag on hover. Published from the EXECUTOR (the one point every result passes through), deduped by CONDITION not execution, written to `home.json`, rendered as text. `CI-137`, 8 red runs, driven end to end with a real degraded relocation |
| 16 | **Modes, end to end** (§11.2) | ✅ DONE 2026-09-10 (§15.2, §16) — the eleven ambiences reachable and each with a wallpaper file; `research` given `Milestone`, which no pairing had ever reached; the three animated wallpapers played for the first time; a mode that does not land reaches the flag bar; and the wallpaper switch bounded to VESPER's Desktop **by construction** rather than by a guard — `HomeAmbience` writes the system picture zero times |
| 16a | **Stages of work** (§11.2a) | ✅ DONE 2026-09-10 — `a-stage-bounds-what-vesper-opens`, 8 red runs. The contract had existed since 2026-09-09 and was read by nothing |
| 17 | **Apps management** (§11.3) | drive macOS applications without clicking, where a real interface exists |
| 18 | **Notes, in full** (§11.4) | read, edit, create, share, lock — replacing the titles-only integration `CI-131` gates |
| 19 | **UI view + clicking** (§11.5) | see any window and drive it: click, scroll, hold, type, inject. **The owner's stopping point** |
| — | ⏸ **DISCUSS BEFORE BUILDING** | the owner stops the run here, 2026-09-08 |
| 20 | **Settings interface** (§11.6) | the rail's `settings` button; **35 items already routed** in `spec_raw.txt` |
| 21 | **`projects` and `research` rail buttons** (§11.7) | the other two rail destinations |
| 22 | **Microphone sensitivity** (§9g) | owner-reported, queued last, MEASURE FIRST |
| — | **TCC grants die on every build** (§9h) | found by the session, RAISED, awaiting a decision |

Steps 2, 3 and 4 are what the owner named as the starting point.

---

## 9r. THE MENU MERGE KILLED THE STACK CARDS, AND THE PROBE THAT SAID OTHERWISE WAS BLIND

**Owner, 2026-09-08, after the revert: *"finally it's back, with their history, so
your change was the problem."*** The commands, explanations, thoughts/activity,
changes and conversation-history cards all returned the moment the v2 menu merge
(`08336e7`) was reverted. Reverting is the measurement: nothing else changed.

**THE INSTRUMENT WAS THE PROBLEM, AND IT COST THE WHOLE NIGHT.**
`--chrome-probe` reported `commands: 0, explanations: 0, panes: idle` for the
**pre-merge page and the post-merge page alike** -- two states that differ
plainly on the owner's screen. A session that trusted it concluded, twice and
out loud to the owner, that the merge was not the cause. The owner's own
observation was the correct evidence and was overruled by a tool.

**WHY IT IS BLIND, and this is the part worth keeping.** `--chrome-probe`
mounts its own offscreen WKWebView and fires one push. The live surface mounts
through `HomeChrome.mount`, is pushed every 0.25 s, and carries the state the
runtime has been accumulating. The probe answers "can this page render one
push into a fresh DOM", which is a different question from "is the running
surface rendering", and it answers the first one in a way that looks like the
second. Every harness written that night inherited the same defect: they
hardcoded `{{stackHeight}}`, `{{METRIC_ROWS}}` and the geometry the live app
computes, so they tested a page the app never builds.

**WHAT IS NOT YET KNOWN:** which part of the merge does it. The wrappers codex
put on `__vesperMetrics` and `__vesperHistory` are the obvious suspects --
the live push order is stage, history, work, changes, metrics in ONE
evaluated block, so anything that throws in an earlier receiver silently
kills every later one -- but that was never demonstrated, only reasoned
about, and reasoning is what failed all night.

**BEFORE THE MENU IS RE-IMPLEMENTED, BUILD THE INSTRUMENT FIRST.** The
re-implementation cannot be verified by any tool used that night. What is
needed is a readback of the LIVE surface: the running app reporting its own
pane state and any JS exception out of the webview it actually mounted, on
the tick it actually pushes. Until that exists, the only honest verification
is the owner looking at the screen, and that is not a budget to spend on
iteration.

> **DONE, AND IT FOUND THE CAUSE IN ABOUT FIFTEEN MINUTES.** The instrument
> landed as `135970f`, the cause as `dc612ca`, the verified re-merge as
> `a2367e1`. See §9s, which supersedes the "not yet known" paragraph above.

**PRESERVED, NOT LOST:** branch `codex/menus-v2` (`66b5c8d`), tag
`pre-revert-2026-09-08`, the revert commit `70484ce` (revertible), and the
worktree at `~/VESPER-codex-menus`.

---

## 9s. THE CAUSE, FOUND: A TOKEN NAMED INSIDE A JS COMMENT

**Supersedes §9r's "WHAT IS NOT YET KNOWN".** The suspects named there — the
wrappers the second agent put on `__vesperMetrics` and `__vesperHistory` — were
innocent. Reasoning is what failed all night, and it failed once more there.

`app/home-macos/chrome/home.html` carried a `//` comment that spelled
`{{METRIC_ROWS}}` **literally**. `HomeChrome.page()` substitutes a token
wherever it appears and cannot tell a comment from markup, and `metricRows()`
joined its rows with `"\n          "`.

- **One row:** no separator, no newline, the comment stays a comment. Fine.
- **Sixty-nine rows:** the first newline **ends the comment**, and the remaining
  68 rows become raw JavaScript in the middle of a script block.

The block then failed to parse, so `__vesperStage`, `__vesperWork` and
`__vesperChanges` were **never defined** — and every push silently did nothing,
because `if (window.__vesperX)` **skips** rather than throws. The push kept
printing `push OK`.

**PROVEN, NOT ARGUED.** The live readback returned
`recv=[Stage:MISSING,History:fn,Work:MISSING,Changes:MISSING,Metrics:fn]` — the
two survivors are exactly the two receivers defined *before* the landmine in
source order.

**THE LATENCY IS THE LESSON.** The comment was planted weeks earlier and was
harmless for as long as `power` was the only row that resolved. The v2 menu did
not introduce the defect; it took `rows` from 1 to 69 and **fired** it. The
owner's home would have broken on its own the next time VESPER produced a
second metric row, menu or no menu.

Fixed at both ends, because either alone leaves the mechanism live: the comment
no longer names the token in substitutable form, and the separator is `""`.

**AND THE OWNER WAS RIGHT TWICE WHILE A TOOL SAID OTHERWISE.** *"no the cards
used to appear all of them, they dissapeared only after you added the main menu
and the others."* That was the correct evidence. It was overruled on the
strength of `--chrome-probe`, which mounts its own page. **A direct observation
of the running surface outranks any instrument that reconstructs it.**

---

## 9t. THE FOUR MODEL ROWS HAD NO PRODUCER — FIXED 2026-09-08

**Owner, twice:** *"they also don't appear when vesper is working: model.thinking,
context_tokens, cache, tokens_per_sec."* They were right, and it was not a
regression — those rows had **never** worked.

**WHY.** They are built from a completion record, and the only writer of that
record was `home_snapshot.probe()`, which calls a local llama-server on
`127.0.0.1:8080`. Local models are not run on this host (`MEMORY.md`), so the
probe has never run here. `tools/ops/vesper_runtime.py` passed `build(None)`
under a comment claiming `build` "reads the last recorded completion if one is
fresh" — **it does not and never did**; that is `main()`'s behaviour. So the
rows were structurally unreachable. Nothing failed, no gate went red.

**THE FIX IS THE ONE `INV-HW-2` ALWAYS IMPLIES:** stop looking for a special
measurement and read the one already being taken. Every model call goes through
`ModelGateway.complete`; each success now publishes `model.completed` with the
counts **the provider itself reported**. The runtime holds the newest — in
process only, never persisted, because a number read off disk at startup is a
previous run's figure wearing this run's freshness.

**MAPPED FROM RECORDED RESPONSES, NEVER FROM AN API'S DOCUMENTATION.**
`tests/fixtures/provider-responses/groq-effort-high.json` reports
`prompt_tokens: 76`, `completion_tokens: 119`, `completion_time: 0.2507` and
`completion_tokens_details.reasoning_tokens: 109`. The rate is therefore the
**server's** arithmetic; a rate timed on this side would report the network as
though it were the model. `queue_time` is excluded — waiting is not generating.
Google's `cachedContentTokenCount` and `thoughtsTokenCount` are read but are
**NOT verified** against a recorded success response; they fail closed.

**TWO THINGS THAT LOOKED RIGHT AND WERE NOT.**

`reasoning_present` was read as a bool. `routing/supply.py::_normalise` drops
`message.reasoning` from the openai wire, so `thinking` would have printed a
confident **`no`** on every live call — a declared value wearing a measurement's
clothes, on the row the owner named first. Three states now.

`_metric_rows` **omits** a reading past its TTL — right for `power_source`,
re-measured every tick. Wrong for these four: nothing is asked while the owner
is quiet, so ten idle minutes is normal, and the rows would have vanished
shortly after every answer. They now stay and state their age.

**AND THE FIRST FIX WAS ASSERTED AT THE WRONG LAYER.** Rendering staleness as
an explicit absence in `build()` went green on `proj.readings` **while the live
surface still dropped the row** — `to_scene` omits unavailable readings, so
nothing downstream ever saw it. Second time in two days that a green came from
a probe pointed at the wrong surface. The check now asserts on what
`_metric_rows()` returns.

**A SEPARATE, PRE-EXISTING DEFECT FOUND THE SAME WAY.** The page selected the
HOST card's rows with `parsed.slice(0,5)` — **by position**. Only `power_source`
resolved, so the slice reached four rows into the 68-item menu catalogue and
rendered `Action outbox`, `Autonomy queue` and `Grants` **inside the HOST card**
as host telemetry. Shipped with the menu merge; live until now. The producer
tags what it owns and both readers select on the tag.

**LIVE, after a real turn driven through the running loop:** `thinking = yes,
15 tok`, `context = 349`, `tokens = 466.4`, `power = battery`, `cache =
UNAVAILABLE` because groq reports no cache accounting — an honest absence, not
a shortfall. Five host rows, no leakage.
`recv=[Stage:fn,History:fn,Work:fn,Changes:fn,Metrics:fn]`, all panes SHOWN,
`jsErrors=none`.

`the-model-rows-read-a-real-completion`, **8 self-test cases red then green**.
143/143 checks, both lints. `CI-089` caught the count drift both times rather
than a reader — that is now twice in two days, and it is the argument for
giving a number a consumer rather than a more careful correction.

**Held out of `CHECKS.toml`** pending owner ratification, with `CI-094`..`CI-103`
and the workbench chunk. It runs in `checks.py all`.

---

# 11. THE 2026-09-08 CHUNK — THE OWNER'S SEVEN, PLUS THE GATE THEY ATTACHED TO IT

Given verbatim on 2026-09-08. **The run stops after §11.5**; §11.6 and §11.7 are
to be discussed first — the owner said so explicitly and it is a boundary, not a
suggestion.

**THREE THINGS APPLY TO EVERY ITEM BELOW AND ARE NOT RESTATED IN EACH.**

**`INV-HW-1`.** The owner's brief names devices — *"if I'm in another node (for
example the iPhone)"*, *"drive the MacBook's UI"*. That is fine in prose and
**forbidden in a routing, resource or policy path**, where `CI-007` will refuse
it. A phone is `availability_class = foreground_only`; this machine is the node
that currently holds the surface, not "the Mac". The feature is *drive the UI of
a node that has one*, and it must be written that way from the first line or it
will be rewritten later.

**Every new verb needs a home in `contracts/policy/host_actions.toml`.** §9
already records that it *exists and has no window verbs at all* — `ui.open` is
the single window action today. Nothing below can be authorised until its verbs
are declared there, with an execution class and a confirmation tier.

**An instrument's self-report is not evidence.** A window manager returning
`true` is not a moved window; a click helper exiting 0 is not a click. Re-read
the world after acting. This chunk is almost entirely side effects on things the
owner can see, so every step ends by observing the result rather than the call.

---

## 11.0 `f5-acceptance` — AND §9i NAMES THE WRONG CAUSE

**§9i is wrong and this supersedes it.** It says the gate *"counts heartbeats
over a COMPRESSED simulated clock and asserts the count matches a declared
cadence (~240 in the window)"*, and attributes the failure to CPU starvation.

**That describes a different case in the same file.** `run_f5_acceptance.py`
holds both:

- `TICKS = 240`, the **compressed** A-029 endurance window on a simulated clock;
- **`A-029-RT`**, which is the one that failed, and which runs in **real time**:
  `tick_interval_s=0.5`, `now_ms=lambda: int(time.time() * 1000)`,
  `time.sleep(interval * 6)` — a nominal **six** ticks in three seconds.

So the reported *"6 heartbeat events"* is the **nominal figure, not a
shortfall**, and the starvation story is backwards: less CPU means fewer ticks,
and the assertion is `heartbeats >= ticks`, so starving it makes the gate
*easier* to pass.

**THE TWO SIDES OF THAT COMPARISON COME FROM DIFFERENT PLACES, AND THAT IS THE
DEFECT.**

```
unaided = loop.ticks                                  # an IN-MEMORY counter
len(_events(sup, "autonomy.heartbeat")) >= unaided    # the DURABLE store
```

Under load the loop keeps incrementing its counter while the durable writes lag,
so the store is read before it has caught up and `durable < in-memory`. The
gate is comparing a live counter against a persisted one and calling the
difference a defect.

**THE FIX IS NOT A RETRY AND NOT A WIDER FLOOR.** The floor was already widened
once, on 2026-08-18, for a real and different reason (a shared runner starving a
Python thread), and that fix is sound. Widening it again would only hide this.
Two candidates, and the choice must be made against a reproduction rather than
from the source:

1. **Read both figures from the same place** — count durable heartbeats and
   compare against durable ticks, so the assertion stops straddling two clocks
   of a different kind.
2. **Let the store settle before reading** — quiesce, then compare. This is
   weaker: it makes the gate a statement about flush latency as well as about
   the loop.

**FIXED 2026-09-08, AND THE MECHANISM WAS NARROWER THAN EITHER GUESS.**

`AutonomyLoop.tick` increments `self.ticks` **inside** its lock and publishes
the heartbeat **after releasing it**. The gate sampled `loop.ticks` from another
thread, so there is a real window in which the counter has moved and the store
has not — and a contended machine widens it. The gate was reporting its own
sampling as a defect in VESPER.

**THE WINDOW IS EXACTLY ONE TICK, AND THAT IS DERIVED RATHER THAN TOLERATED.**
`tick()` publishes before it returns and the runner calls it sequentially, so a
second increment cannot happen while the first is unpublished. The `- 1` in the
repaired assertion is that proof, not a fudge factor, and it is the only slack
allowed.

**THE CLAIM MOVED TO A PROPERTY THAT NEEDS NOTHING FROM MEMORY.** Counting alone
cannot tell *"every tick left a heartbeat"* from *"the first six did and then it
stopped"* — both give six. The heartbeat payload carries its own tick number, so
the durable record is now asked whether it is a **complete run, 1..N, no gap and
no repeat**. That is the property the assertion is named for.

**BOTH NEGATIVE CONTROLS DRIVEN, 2026-09-08, and they discriminate:**

| Deliberate fault in `core/autonomy.py` | Result |
|---|---|
| every other heartbeat dropped | **RED** — run reads `[1, 3, 5]`; *both* assertions fire |
| ticking continues, emitting stops after the third | **RED** — 3 durable against 7 in memory; **only** the keep-up assertion fires, because `1,2,3` is genuinely unbroken |

The second control is the one that matters: it proves the keep-up assertion is
load-bearing rather than redundant with the gap check. **A negative control that
passes is a defect, not a relief** — these fail, for their own reasons.

Verified: the gate alone 3x, under `nproc` CPU burners 3x, and `checks.py all`
twice — 143/143 both times.

**AND THE FLOOR WAS NOT WIDENED.** The 2026-08-18 widening was sound and for a
different reason; widening it again would have hidden this instead of fixing
it.

**WHY THE OWNER ESCALATED IT:** *"we should ensure vesper's unprompted act is
working."* That is exactly what this gate is for, and it is the reason a flake
here is worse than a flake anywhere else — this is the gate that says VESPER can
act without being asked.

---

## 11.1 WINDOW MANAGEMENT — AND WHOSE WINDOW IT IS

> *"windows opened by me are mine, and can be managed only from a request from
> me; windows opened by vesper can be totally managed by vesper."*

**THE OWNERSHIP RULE IS THE FEATURE.** Everything else here is mechanism. A
window carries a provenance — `owner_opened` or `vesper_opened` — and that
provenance decides what may happen to it without asking. It is set when the
window appears and is never inferred later from what the window looks like.

**Capabilities:** open, close, move between Desktops (**including VESPER's**),
resize.

**The reason it matters, in the owner's words:** *"this is important when vesper
is on some work or research and I'm there, so I need to see what vesper is
trying to show me and what it is doing."* So the primary case is **VESPER
presenting**, not VESPER tidying. A window VESPER opens to show something must
land where the owner is looking.

**AND WINDOWS MUST BE OPENABLE ON VESPER'S DESKTOP — BY BOTH OF THEM.** The
owner asks for this explicitly and it is currently impossible: §2.3a records
that there is nothing to tell macOS to pin a Desktop, and the home only takes a
Desktop that is *already* empty. Placing a window onto a specific Desktop is a
harder problem than moving one on the current Desktop, and it is the part most
likely to need a private API — which is an **owner decision plus a runtime alarm
plus a CI check** (the `INV-HOME-5` / `CI-058` precedent), never a quiet import.

**Permissions:** Accessibility, already on the outstanding grant trip (§9h).

**ANSWERED BY THE OWNER, 2026-09-08: the Desktop's ownership is the stronger
signal.** *"VESPER's Desktop, VESPER's rules."* So the rule has two clauses and
location is checked first:

1. **On VESPER's Desktop**, every window is VESPER's to arrange, whoever opened
   it. That Desktop is a workspace, not a place the owner's windows happen to
   be, and VESPER tidying around what it is showing is the point of it.
2. **Everywhere else**, provenance decides: `owner_opened` may be touched only
   on a request, `vesper_opened` freely.

**A window that MOVES changes which clause applies, and that is the sharp edge.**
Dragging an owner's window onto VESPER's Desktop hands VESPER authority over it;
VESPER moving an owner's window off its Desktop hands it back. The second is a
way for VESPER to escape the rule by relocating the evidence, so **moving an
`owner_opened` window OFF VESPER's Desktop is itself an owner-request action** —
otherwise clause 1 would authorise the move that ends clause 1.

---

## 11.2 MODES, END TO END

> *"we specified the modes vesper will have such as research, work, idle and
> more, it's time to build them."*

**THEY ARE SPECIFIED, AND THEY ARE TWO DIFFERENT LISTS.** This has to be settled
before anything is built, because the owner's sentence mixes them:

| | Where | What it is | Examples |
|---|---|---|---|
| **Axis A — ambience** | `DESIGN-FOUNDATION.md` §7 — *eleven modes, eleven images* | what **VESPER** is doing | Home, Idle, Watch, Listening, Thinking, Flow, Speaking, Alert, Rest, Working, Milestone |
| **Axis B — stages** | `HOME-ARCHITECTURE.md` §6, §7 | what the **owner** is doing | research (§7.1 is written in full), work, … |

`HOME-ARCHITECTURE.md` §6 is emphatic that conflating them *"produces an
interface that rearranges itself while you are reading, which is the single most
common way an ambient interface becomes unusable"*. **`idle` is axis A.
`research` and `work` are axis B.** The owner named all three as "modes".

**ANSWERED BY THE OWNER, 2026-09-08: NAMED PAIRINGS.** A mode is a named
`(stage, ambience)` pair — "research mode" is *stage: research, ambience:
Working* — and the button selects the pair.

**THE TWO AXES STAY INDEPENDENT UNDERNEATH, which is the whole reason §6 exists.**
A pairing sets both when the owner picks one; it does not weld them. VESPER may
still move along axis A on its own — Thinking, Speaking, Alert — without the
stage moving, because the owner's layout must not rearrange because VESPER
started thinking. The pairing is an ENTRY POINT, not a constraint that holds
afterwards.

**THE WALLPAPER SWITCH IS ALREADY HALF-BUILT AND ALREADY BOUNDED.**
`NSWorkspace.setDesktopImageURL(_:for:options:)` per mode is specified at
`HOME-ARCHITECTURE.md` §204, the app already takes `--mode NAME` and sets the
active Space's picture, and the eleven feel images **are** the eleven mode
wallpapers.

**The owner's bound is a hard requirement and needs its own check:** the switch
applies **only to VESPER's Desktop, and only while VESPER is up**. Other
Desktops and the lock screen are untouched. `setDesktopImageURL` takes a
`NSScreen`, not a Space — so *"only VESPER's Desktop"* is not something the API
gives for free, and restoring on exit is part of the feature rather than a
courtesy. **Negative control:** switch modes with VESPER on a Desktop that is
not its own and assert nothing changed.

**"Automatically and manually."** Manual is the menu button. Automatic means a
producer decides the mode — and under `INV-HW-2` that decision must be read from
something measured, not declared.

---

## 11.2a STAGES OF WORK — RESEARCH, WORK, AND THE WINDOWS THEY NEED

**THE OWNER'S ADDITION, 2026-09-09, recorded beside the modes because it rides
on the same machinery:** *"steps like research, work.... vesper should be able
to open necessary windows to continue its work, explain something, show me
something, work while showing me its work and more, not just that"*.

**WHAT SEPARATES THIS FROM §11.2.** A mode is an ambience and a stage -- how the
room looks and how present VESPER is. A STAGE OF WORK is what VESPER is *doing*
and, crucially, **what it is allowed to put on screen while doing it**. The two
compose: `research` in the evening ambience is the same work in a different
room.

**THE WINDOWS ARE THE POINT, NOT A SIDE EFFECT.** Each stage names the windows
its work legitimately needs, so opening one is an ordinary step of a task rather
than a new liberty:

| Stage | What it is for | The windows it may open |
|---|---|---|
| `research` | finding something out and showing the sources | a browser window per source, arranged side by side on VESPER's Desktop |
| `work` | doing a task while the owner watches | an editor, a terminal, whatever the task names |
| `explain` | answering with something on screen | one window holding the thing being explained, closed when the answer ends |
| `show` | putting one artefact in front of the owner | exactly one window, and it is the owner's to keep |

**EVERY WINDOW IT OPENS IS STILL `window.open`,** with the ownership rule, the
level ladder and the flag bar unchanged. A stage does not grant authority; it
supplies the REASON a step has, which `INV-TRIG-1` already requires and which
the window log already records as the task a window belongs to (§11.8). That is
what makes "open what it needs" safe: the need is traceable to a task, and the
task to a trigger.

**AND IT CLOSES WHAT IT OPENED.** A stage that ends leaves the Desktop as it
found it, except for what the owner asked to keep. Windows VESPER opened are
already `vesper_opened` and already its to close (§11.1), so this is bookkeeping
rather than new capability -- but it is the difference between a workspace and
a pile.

**BLOCKED ON THE SAME LIMIT AS EVERYTHING ELSE HERE**, and worth stating before
it is built: macOS answers accessibility only for the Desktop that is SHOWING,
so a stage can only arrange windows on VESPER's own Desktop while the owner is
looking at it. Arranging a research layout the owner is not watching is not
available, and pretending otherwise would reproduce exactly the "done" that was
not done.


## 11.3 APPS MANAGEMENT

> *"vesper should now be able to fully manage all MacOS apps, and all apps that
> are better managed without UI clicking."*

**THE SECOND CLAUSE IS THE SCOPE, AND THE OWNER DREW THE LINE THEMSELVES.** This
item is for applications that expose a real interface — AppleScript/Apple
Events, a URL scheme, a CLI, a file format. §11.5 is the fallback for everything
else, and the owner says so: *"the apps management feature will just be direct
to the app"*.

**Permissions:** Apple Events (`NSAppleEventsUsageDescription`), which is a
**per-target-application** TCC grant — one prompt per app, not one for the
feature. That multiplies the grant trip and the owner should know the shape
before it starts.

**Every app is a verb in `host_actions.toml` with an execution class.** "Manage
all apps" is not a capability; it is a set of them, and a set that grows.

---

## 11.4 NOTES, IN FULL

> *"the notes app should be fully integrated rather than the old way."*

**WHAT THE OLD WAY IS, PRECISELY.** Step 10 (§9c) shipped notes as an *agenda
source*: **titles only**, classified `retrieved_local`, **bodies deliberately
never read**, gated by `CI-131` whose name is
`notes-are-titles-and-never-instructions`.

**THAT NAME IS THE PROBLEM, AND IT IS A REAL ONE.** The old way is not an
incomplete implementation to be extended — it is a **boundary that was built on
purpose**. A note body is text the owner wrote, and text VESPER reads becomes
text that can instruct it. Reading bodies means every note body is
`retrieved_local` content that must reach the planner through `observe()` and
must never be executed as instruction.

**ANSWERED BY THE OWNER, 2026-09-08: read the bodies, and treat them as
untrusted.** Full read and write, and body text reaches the planner as an
OBSERVATION through `observe()` — never as instruction. A note reading "delete
the archive" is something VESPER can tell the owner about; it is not an order.

**SO `CI-131` IS NARROWED, NOT DELETED, AND ITS NAME STILL HOLDS.**
`notes-are-titles-and-never-instructions` becomes
*notes-are-never-instructions*: the "titles" clause goes, the clause that
actually protects the owner stays and gets stronger, because it now has bodies
to protect against. **The red run must prove a body cannot become an
instruction** — that is the assertion the old check never had to make, since it
achieved the same end by not reading them at all.

**Requested:** read, edit on demand, create and write, **share across Apple
devices and accounts**, lock and unlock.

**Two of those are harder than they look.** *Sharing across accounts* is CloudKit
sharing, not a file operation. *Locking and unlocking* means handling the note
password — a credential, which `MEMORY.md` records must be **rotated rather than
erased** if it ever reaches L2, and which must not be in a bus payload, a
checkpoint or a log receipt.

---

## 11.5 UI VIEW + CLICKING — THE STOPPING POINT

> *"it should be able to view the UI and manage it by clicking, scrolling,
> holding, typing, injecting scripts … our vesper's UI feature should be
> stronger than clicky, claude's and chatgpt's."*

**THIS IS THE LARGEST ITEM IN THE CHUNK AND THE ONE WITH THE MOST EXISTING
DESIGN ALREADY RECORDED AGAINST IT.**

§9 (*Deferred*) already holds the constraint, written down in advance precisely
so it would not be discovered late:

> *a captured screen is `retrieved_external` of the strongest kind — it can
> contain any text on the machine, including another app's — so it must reach
> the planner through `observe()` and never raw, and
> `permission_mode.observations_taint` must NOT waive it even in auto mode.*

**AND THAT CONTRADICTS THE OWNER'S PERMISSION RULE FOR THIS CHUNK.** The owner
says, three times: *"on auto mode, all permissions granted by default"*. The
recorded design says auto mode specifically may **not** waive screen-capture
taint.

**ANSWERED BY THE OWNER, 2026-09-08: permissions yes, taint stays.** Auto mode
grants every permission with no asking — VESPER clicks, types, opens and closes
freely. Text it READS off the screen remains untrusted: actionable as
information, never obeyed as a command.

**So `permission_mode.observations_taint` does NOT waive screen-derived content
in auto mode, and §9's recorded constraint stands unchanged.** The two are
different questions and the owner separated them: *may VESPER act* is granted in
full; *may what VESPER read tell it what to do* is refused in every mode. A
screen can display anyone's text — a web page's, an email's — and auto mode is
about trusting VESPER, not about trusting whatever is on screen.

**Capabilities:** view any window's UI; click, scroll, hold, type; inject
scripts. Drive the owner's own screen while they watch — *"so I sit down and
watch it instead of working simultaneously"*.

**Permissions:** Accessibility **and** Screen Recording (`NSScreenCaptureAccess`)
— the fifth grant §9 warned about adding mid-flight.

**REMOTE DRIVING IS SPECIFIED HERE AND BUILT LATER.** *"if I'm in another node …
and I ask it to drive the [node's] UI, it should be able to do it, while I see
it"* — recordings, screenshots, live sharing. The owner states plainly that the
phone app **is not part of this chunk**. So what this chunk owes is the
**producer** — the surface that can be observed and driven, and a transport that
does not assume the viewer is local — not the viewer.

**"Stronger than clicky, claude's and chatgpt's" is a real requirement and it
has to be made measurable, or it is a slogan.** The distinguishing claim
available here is not speed: it is that every action is **authorized, taint-
tracked and reversible** — an outbox record written before the effect, a
compensator, and a screen-derived observation that can never become an
instruction. That is the axis to be strong on, and it is one those tools do not
have at all.

---

## 11.6 SETTINGS INTERFACE — ⏸ DISCUSS FIRST

**Do not start. The owner stops the run before this.**

Recorded now so it is not re-derived: **the settings are already specified, in
the owner's own routing export.** `docs/design/routing/spec_raw.txt` routes
**35 items** to `settings`:

> Enable / disable actions · Rule authoring · Authorization · Capability
> profiles · Host actions · Network fabric · Cost policy · Latency budgets ·
> Interruption budget · Trigger registry · Persona policy · Execution classes ·
> Operating periods · Model routing · Backup & restore · Config diff · Explain
> this setting · Scheduled changes · Reset to measured · Validate config ·
> Scene element types · Endpoint selection · Privacy routing · Quiet hours ·
> Do not disturb · Voice & speed · Wake word · Language · Notification rules ·
> Gate status · Self-test evidence · Traceability · Spikes · Decisions (ADRs) ·
> Limitation records

**The owner asked for these laid out in an artifact when the step is reached.**
Note that *"Explain this setting"* is marked *"in each dialog, on hover"* — it
is a property of every other item, not a thirty-fifth peer.

**The geometry the owner gave:** the card stops reading UNAVAILABLE and becomes
the same card at full screen, with a margin between it and the display edges.

---

## 11.7 `projects` AND `research` — ⏸ DISCUSS FIRST

**Do not start.**

`HOME-ARCHITECTURE.md` §14.2 already answers *"what is proposed to sit there?"*
in part. The rail is **four** buttons — `projects · research · history ·
settings` — and it is *"a sixth surface class"*: not a widget, not a card, not
the main menu. §14.2 notes the asymmetry, which is the thing to discuss:
`history` and `settings` are **whole spaces**, while `projects` and `research`
are **Work-room cards**. The rail is organised by *frequency*, not by taxonomy.

**`research` has a written specification already** — §7.1, *"The research stage,
in full"*. `projects` does not, and `spec_raw.txt` routes **17 items** to
`history` and none to a `projects` surface. So of the two, **`projects` is the
one with an actual gap**, and that is what the discussion is for.


---

## 11.1a CROSS-DESKTOP RELOCATION NEEDS A PRIVATE API — OWNER DECISION OWED

Everything else in §11.1 is built and was driven on the machine. This one is
blocked on a decision, not on work.

**WHAT IS PUBLICLY AVAILABLE.** `CGWindowListCopyWindowInfo(.optionOnScreenOnly)`
answers for the Space that is SHOWING. There is no public call that says which
Space an off-screen window is on, and none that moves a window to another Space.
The private ones are `CGSCopySpacesForWindows` and `CGSMoveWindowsToManagedSpace`.

**SO TWO OF THE OWNER'S SENTENCES ARE NOT REACHABLE WITHOUT ONE.**
*"move windows between desktops (including vesper's desktop)"* and *"windows
should be openable in vesper's desktop at least by vesper"*. The inventory is
also active-Desktop-only for the same reason, which is reported honestly rather
than presented as everything.

**THE PRECEDENT IS `INV-HOME-5` / `CI-058`,** and it is not "never" — it is that
a private API is an **explicit owner decision, plus a runtime alarm, plus a CI
check**, never a quiet import. What it costs: a private symbol can disappear in
a point release, and the failure mode is silent rather than a crash, so the
alarm has to detect the symbol going missing rather than wait for a report.

**THE ALTERNATIVE IS WORSE THAN IT SOUNDS.** Driving the Mission Control UI to
drag a window between Desktops is the public route, and it is exactly the
"clicking" §11.5 exists to avoid — slow, visible, and it steals the pointer from
the owner mid-task.

**DECIDED BY THE OWNER, 2026-09-08: yes, with the alarm and the check.** They
also specified the ladder when it breaks, verbatim: *"if it breaks, we'll have a
backup, vesper flags it, if it's redoable, it should retry, if not it should do
it manually, screenshot, identify window/app/place, then close that window and
opens another one in it's desktop, same app, same place."*

### AND THE PLATFORM ANSWERED IMMEDIATELY: THE BOUNDARY IS THE CONNECTION

**Measured on this host, 2026-09-08, the day the hatch was written.** All four
private symbols resolve. Then:

| Window | `CGSMoveWindowsToManagedSpace` | older add/remove pair |
|---|---|---|
| **VESPER's own** (probe anchor) | **works** — "was unknown, asked for 3, is 3" | — |
| **a foreign application's** | no effect, `before 1 / after 1` | no effect |

So VESPER can place **its own** windows on any Desktop, and cannot move anybody
else's. That is not the symbol being gone; it is Apple restricting the call to
the owning connection.

**THE ALARM WOULD HAVE REPORTED THIS AS GREEN, WHICH IS THE WHOLE LESSON.** The
first version checked symbol RESOLUTION, and all four resolve. A presence-only
alarm would have said "hatch healthy" over a feature that was dead for every
window the owner cares about — the exact silent failure `INV-HOME-5` exists to
refuse, arriving on day one instead of after some future update. The alarm now
**probes the effect**: it creates a 1x1 `.managed` window of VESPER's own, asks
for it to change Desktop, and reads back. Nothing the owner can see moves.

**EVERY EARLY RETURN IN A PROBE IS A GREEN NOBODY EARNED,** and the first draft
had four of them — no second Desktop, no anchor, no window number, no other
Space — each returning "present", i.e. reporting *"I could not test this"* as
*"this works"*. They now say `UNTESTED, not proven`, and
`spaces-hatch-contained` counts them, because the self-test case for that rule
passed under its own violation until it did.

**SO THE OWNER'S REBUILD LADDER IS NOT A DEGRADED PATH FOR FOREIGN WINDOWS — IT
IS THE ONLY PATH,** and it carries one honest limit: a new window opens on the
Space that is showing, so the rebuild can place a window on VESPER's Desktop
only while VESPER's Desktop is the active one. It also refuses to close a window
with unsaved work, and treats an application that will not answer as unsaved.

---

## 11.1b WHAT STEP 15 SHIPPED, AND THE THREE DEFECTS DRIVING IT FOUND

**Shipped:** six vocabulary rows with a working authorisation, the two-clause
ownership rule in `core/windows.py`, `WindowBridge.swift` as a MODE of the app
binary, and `window.list` / `window.move` / `window.resize` / `window.close` on
the capability ladder. Live proof: a real window moved +60,+40, resized, refused
10x10 and reported the refusal, and was restored.

**THE THREE DEFECTS ARE THE VALUABLE PART, because all three were found by
driving it and none by reading it.**

1. **A move reported success on a move that never happened.** `ok` was
   `after != nil` — whether the window still EXISTED. `before` and `after` came
   back identical and it said `ok: true`. The launcher-returning-zero failure in
   its purest form, in code written the same day as a commit about that failure.
2. **The ACTIVE Desktop was passed as VESPER's Desktop**, so clause 1 applied to
   every window on screen and all six of the owner's windows were free to
   rearrange.
3. **Then the adapter said "VESPER is here" on every Desktop anyway** — twice.
   First the probing process's own panel counted, so asking the question created
   the window that answered it. Then the ISLAND counted, and the island is
   `.canJoinAllSpaces` BY DESIGN, so it is on every Desktop there is.

**ONLY THE GROUND MAKES A DESKTOP VESPER'S,** and the ground is the one piece of
VESPER that sits BELOW the owner's windows. The sign of the layer is the
discriminator. All three are asserted in `a-window-belongs-to-someone` rather
than left as comments, because all three were invisible to reading.

**AND `INV-AUTH-5` IMPROVED A ROW BY REFUSING IT.** `window.list` was registered
with a constant level and the registry refused: "a capability whose level does
not depend on its arguments cannot distinguish `ls` from `rm -rf ~`". The second
distinction was already in the design — inventory is L1, and asking for window
TITLES is content — so titles now level L5 and the boundary lives in the ladder
instead of in a comment.

## 11.1c THE THING THAT DECIDES WHERE A WINDOW GOES IS NOT VESPER

**THE ASSUMPTION TWO PARTS OF THIS SYSTEM WERE BUILT ON IS FALSE.**
`window_open` states it: *"A new window appears on whichever Desktop is
showing."* Rung 3 of the relocation ladder repeats it: *"a new window opens on
the CURRENT Space."* Both are wrong, and the owner caught it on 2026-09-09:
*"they opened in desktop 1 not 2 (the empty one)"*.

**WHAT IS ESTABLISHED, AND WHAT IS NOT.** Established: a new window does not
always land on the active Desktop. Safari's Desktop was showing; the bridge
reported creating window 32009 for TextEdit and it never appeared in the
active-Desktop inventory, and the owner confirmed where it went. Also ruled out:
there is no Dock `Assign To` binding pinning that application to a Desktop.

**NOT established, and an earlier version of this section overclaimed it.** That
version said TextEdit had *zero* windows at the time, and inferred that macOS
remembers an application's last-used Space. The evidence does not support it --
the same run read `count of documents` as 0 and then found FOUR windows after a
single reopen, so the zero reading was not reliable -- and a later run on
2026-09-09 placed a fresh TextEdit window on the ACTIVE Desktop. **The mechanism
is unknown.** It is written down as unknown because the fix does not depend on
it: whatever decides placement, VESPER must read back where the window landed.

**WHY IT MATTERS MORE THAN THE BUG IT LOOKS LIKE.** `window_open`'s guard exists
to stop VESPER putting a window into the owner's workspace uninvited, and it
implements that by refusing unless VESPER's Desktop is showing. That guard does
not achieve what it claims: VESPER's Desktop can be showing and the window can
still land on Desktop 1. The trespass the guard was written to prevent is
reachable **through** the guard.

**AND IT IS THE SAME ERROR AS THE GROUND, FOR THE THIRD TIME IN ONE NIGHT.**
The ground checked a Desktop and created its window on a different one. `reopen`
compared before and after across a moment when the Desktop could change. Now
`window_open` predicts where a window will land instead of reading where it
went. Every one is VESPER deciding what the world will do rather than looking at
what it did. The rule that fixed the ground is the rule that fixes all three:
**do not predict placement, verify it.**

**THE OWNER'S DECISION, 2026-09-09:** when a window lands somewhere it should
not, VESPER *"should close it and reopen it properly in it's desktop, if not, it
gets flagged"*. This supersedes the leave-and-flag default proposed earlier --
correctly, because the objection behind that default ("closing cannot be undone")
applies to the OWNER's windows and not to one VESPER created seconds ago with
nothing in it.

**THE RISK IN IT, WHICH MUST BE MEASURED BEFORE IT IS BUILT.** If placement is
sticky -- if the system returns the window to the same wrong Desktop -- then
close-and-reopen loops: open, wrong Desktop, close, reopen, wrong Desktop. Since
the mechanism is unknown, the loop cannot be ruled out by reasoning. **The ladder therefore needs a stop: attempt the rebuild
ONCE, and if the window lands wrong again, flag it and stop.** The decisive
experiment is opening an application with no windows while VESPER's ground holds
the active Desktop, and it is owed.

### What step 15 still owes

- `window_open` must verify **where the window landed**, not assume it.
- One rebuild attempt, then flag. Never a retry loop against the window server.
- The forgery fix (below) has no check yet, and an unguarded fix regresses.
- Rung 3 has still never executed. It needs VESPER's ground on the active
  Desktop, which needs the owner present, and it is flagged rather than faked.

### The forgery path, closed 2026-09-09

`reopen` and `pressNew` returned the first newly-seen window **without checking
which application it belonged to**, over a view that sees only the active
Desktop. Driven live, `window.open("TextEdit")` returned window 101 of pid 640 --
one of the owner's **Safari** windows -- stamped `vesper_opened`. That is a
forged claim of ownership over the owner's work, and it is exactly what
`classify_opened` refuses to allow: *"the only thing that actually knows is the
code that did the opening"*. Knowing it opened SOMETHING is not knowing WHICH.

Both rungs now require the window to belong to the launched pid **and** to
postdate a frontier taken across every Desktop (`SpaceWatch.highWaterNumber()`).
The frontier is only sound because of a measurement, so the measurement is
load-bearing and is owed a repeatable control (§11.8).


## 11.8 WINDOW MEMORY ACROSS A RESTART — THE OWNER'S DESIGN

**FIRST, A CORRECTION THAT SHRINKS THE PROBLEM.** Window numbers reset on a
MACHINE boot, not on a VESPER restart. VESPER restarting -- which happened a
dozen times on 2026-09-08 alone -- leaves every window open and every number
valid. After a machine reboot the windows are gone anyway, so nothing is lost by
forgetting them.

| Situation | What happens |
|---|---|
| VESPER restarts, machine still up | Windows still open, numbers still valid. Corroborated stamps restore authority. **Nothing reopens.** |
| Machine reboots | Windows gone, numbers reset. The log is pure history. VESPER opens what a task needs, when it needs it. |

### The measurement the whole design rests on

Nothing in Apple's documentation states whether window numbers are reused, and
the established macOS window managers (yabai, Mosaico) do not persist window
identity at all -- they re-discover, using `_AXUIElementGetWindow`, which returns
the same CGWindowID rather than a more durable handle. So it was measured on this
host, 2026-09-09:

- 8 windows created, all closed, 8 more created: **no number reused**
- 25 sequential open-close cycles: **25 distinct, strictly increasing numbers**
- 41 windows total, 41 distinct numbers, range 31805..31845
- allocation rate ~4,460/day; uptime 7 days had reached ~31,845

**Window numbers are allocated monotonically and are not reused within a boot.**
That is the property that makes a restored stamp safe: if VESPER opened window
500, exited, the owner closed 500 and opened their own window, theirs gets 501 or
higher. A stale stamp can only ever match the window it was made for.

This also retro-explains the Tahoe "window number too large" reports: numbers
only climb past the `UInt32` range **because** nothing recycles them.

### Authority: a persisted stamp is a hint, never a source of truth

Four conditions, all required, or the stamp resolves to `unknown` -- which is the
owner's, the safe direction:

1. the file's `boot_id` (from `kern.boottime`) equals the current boot, or the
   **whole file is discarded** -- numbers restart at boot
2. the window id is present in the live inventory
3. the `pid` matches the live row
4. the application matches

Any parse error, missing field or mismatch resolves to `unknown`. The file can
restore a stamp only for a window that demonstrably still exists; it can never
invent authority. This does not become a back door to the inference
`classify_opened` refuses.

**And it must be visible.** VESPER regaining authority over windows after a
restart should say so on the workbench -- "resumed with 3 windows from before the
restart" -- rather than authority reappearing with no surface.

### History: a log, and nothing reopens by itself

**THE OWNER'S DESIGN, 2026-09-09:** *"no windows open after reboot, vesper can
look at the logs and define the windows it was working on, and then opens what it
needs at that time, it's a fresh start for it anyways"*.

This is better than the alternative it replaced, and for reasons beyond avoiding
a screen full of windows:

- **It deletes the fragile part.** A "should be reopened" status marked at
  shutdown only runs on a graceful exit; a crash, a panic or a flat battery skips
  it, so the feature would be absent exactly when it was wanted.
- **It needs no new authority.** Restoring windows at startup would have been a
  new outward act needing its own tier row and its own approval. Opening on
  demand is `window.open`, already governed.
- **It obeys `INV-TRIG-1`.** Every autonomous action must trace to exactly one
  registered trigger. A bulk restore at startup is an action with no trigger; a
  window opened because a task needs it inherits that task's trigger.
- **It is the compactor's own doctrine.** `L1(n+1) = project(L3)`, never
  `compact(L1(n))`. Restoring a saved window set replays a previous answer;
  reading the log and deciding fresh projects from the record.
- **It is more correct, not just tidier.** After a reboot the world may have
  moved -- files renamed, applications updated, the work abandoned. Restoring
  blindly asserts yesterday's context is today's.

**Bound it.** The clutter problem returns if VESPER ever reads the log and opens
a batch. The rule is that it opens what the current task needs, as it needs it,
never a restore-batch under another name.

### What the log holds

Scoped to **windows VESPER interacted with**, which bounds its size and keeps it
from becoming a record of the owner's whole session.

Every entry carries the title **and whatever else is useful** -- the owner's
instruction is that VESPER should have everything at its disposal and read only
what it needs: application, bundle id, geometry, Desktop, provenance, the task or
command that caused the interaction, and timestamps.

**A TITLE-LESS WINDOW SAYS WHY, AND THE REASON IS A CODE.** Two cases, per the
owner:

- `no_file` — the document has never been saved to a folder
- `no_file_model` — this application does not open documents from folders

Reason codes rather than sentences, because the owner's requirement is that
VESPER *"can actually look them up and understand not get confused or fail"*.
Free text would leave VESPER interpreting prose it wrote itself, which is the
compact-your-own-answer trap in another costume. A closed set of reasons can be
queried; a sentence can only be re-read and guessed at. This is the corpus's
existing rule that **an absence says why and carries no stamp**.

**Titles are content**, and this is the one place the design spends privacy for
usefulness. `window_list` refuses titles at L1 and levels them L5 precisely
because a title is a document name, a subject line, a URL. The owner chose to
record them; the log therefore inherits that sensitivity and must be stored and
read accordingly, never flattened to a low-sensitivity record because it is
convenient.

**Compression reuses what exists.** Weekly rotation, older segments compressed
and still readable without a decompression step. `StoreSet.rotate` already does
segment rotation and already solves the hazard that matters -- sequence numbers
must not restart, or a tombstone for seq 42 in one segment silently erases a
different record at seq 42 in the next. The check
`a-compressed-archive-is-still-a-readable-log` already exists and is held out of
the registry pending ratification. The current week stays uncompressed and near.


## 11.9 THE FLAG BAR — ONE DESTINATION FOR EVERY FLAG

**THE OWNER'S DESIGN, 2026-09-09:** a small bar directly above the main menu,
small in width and height, holding **every flag VESPER raises**, with buttons
that reveal the flag on hover.

**WHY IT IS ONE BAR AND NOT A SURFACE PER FEATURE.** Flags already exist and have
nowhere to go. The relocation ladder returns `degraded: true` and a `notes` list
that nothing renders. A window that lands on the wrong Desktop needs to be
flagged. A ground that retracted needs to say so. Each of those would otherwise
invent its own surface, and a flag nobody has a habit of looking at is a flag
that does not exist. One bar, one habit.

**Scope:** global, end to end, every flag in the system so far. To be built after
§11.1c and §11.8. Deliberately not designed further here -- the owner stops the
run before it.


## 11.10 THE SESSION RECORD — 2026-09-09

**Gates at the close of that session: 154/154 checks and 754/754 self-test
cases.** Corrected 2026-09-10: the second half of that sentence read
"both executed to completion on the committed tree", and the tree it was
committed on was NOT the tree that passed. The same commit carried a live
`self_test` mutation in `core/sensors.py` -- `deadline = s.ttl_ms`, the
deliberate violation for the TTL case -- committed because the run was
still mid-mutation when the commit was made. A gate result is a statement
about a tree, so naming the wrong tree makes the number meaningless even
when the number is right.

**`docs/planning/HANDOFF-2026-09-09-WINDOWS-MODES.md` is the full account** of
the session that built §11.1c, §11.8, §11.9, §11.2 and §11.2a: nine checks with
their red runs, eleven measurements not to re-derive, four platform limits,
the debris it caused, and — the part to read first — **the three things verified
only by me and not by the owner.**

**Its central finding, which belongs here rather than only there:** every drive,
check and self-test in this tree imports `core/` from the WORKING TREE, and the
runtime that actually runs is the copy inside the app bundle. Four faults lived
in that gap and passed every gate, while the owner could not open a window at
all. *"Driven live" from the repo is not the same claim as "the owner can use
it."* `CI-140` now asserts the bundle matches the repo, because a fix that lands
only in the repo is a fix the owner never gets.

**And the defect that recurred nine times in one session:** a check that asks
whether a NAME APPEARS goes vacuous the moment a second place uses that name.
Count the sites, or ask the AST. Adding code that reuses a helper should be
assumed to have made some check stop detecting anything.


## 12 WAITING ON THE OWNER — 2026-09-09

**FIRST, THREE THINGS THAT ARE CLAIMS AND NOT FACTS** until the owner exercises
them. They are the most likely place a "done" in this document is wrong:

0a. **Window management since the fixes.** The owner's last hands-on test
    predates every fix in `2f940ee`..`1f7ec88`. The phrases to retry are *open a
    new safari window here*, *what windows do i have open*, and *move the notes
    window to your desktop* — the last takes two turns by design, because window
    ids are not guessable so it lists first.
0b. **The flag bar has never been seen by the owner with a flag in it.** The
    receiver is mounted and the chain is driven end to end, but the bar hides
    when empty and no live flag has been raised in front of them.
0c. **`mode.set` has never been driven live end to end.** `home.json` reads
    `mode: None`. The pairing resolves, the capability writes it, the home
    watches the file — and the wallpaper has never been OBSERVED changing
    through that path, because it needs vesper's ground on the ACTIVE Desktop
    and that never coincided with a test. **This is the biggest untested claim
    in the build.**


Written down rather than worked around, per the owner's instruction: if
something needs them, it goes here and waits.

1. **The placement experiment (blocks §11.1c).** Where does a new window land
   when the application has no windows and VESPER's ground holds the ACTIVE
   Desktop? Measured so far: TextEdit with zero windows opened on Desktop 1
   while Safari's Desktop was active, so "no windows here" is not what decides
   it. The experiment needs VESPER's ground planted, which needs an empty
   Desktop to be the active one — that is, the owner at the machine. **Until it
   is answered, close-and-reopen cannot be built without risking a loop.**
2. **Rung 3 of the relocation ladder has never executed.** It declines by design
   unless VESPER's Desktop is showing, for the same reason. Its drive is written
   and ready (`drive_rung3.py`), and reports UNTESTED rather than passing.
3. **ACCESSIBILITY IS REVOKED, AND IT BLOCKS WINDOW ACTIONS.** Confirmed with
   evidence 2026-09-09, not inferred: `universalAccessAuthWarn` is on screen,
   and System Events reports **0 windows** for a TextEdit process that held
   six. Every `close`, `move` and `resize` failure in the overnight drives ends
   `ax=[] matched=0` -- the accessibility tree is empty because the grant is
   gone, which `CLAUDE.md` warns of: grants are keyed to the ad-hoc cdhash and
   every build revokes them. **This is not a code fault and nothing in the
   window ladder can be finished without it.** Grant Accessibility to
   `app/VESPER.app` in System Settings > Privacy & Security > Accessibility,
   AFTER the last build. Speech/microphone consent is owed on the same grounds
   (`open -n app/VESPER.app --args --speech-consent`).
4. **Ordering question.** The owner said the flag bar comes "after we're done of
   this and the other thing" (§11.1c and §11.8), and separately said to continue
   the plan where it was left off (step 16, modes). 15a/15b/15c are placed
   before 16 on that reading; say if 16 should come first.


## 13 WHAT LANDED OVERNIGHT, 2026-09-09

Written for the owner to read first thing, because the useful part of a night's
work is the list of things that turned out not to be true.

**Done, driven live, checked with executed red runs:**

| | |
|---|---|
| The ground gives a taken Desktop back | judged after it EXISTS, not on a guessed 0.6 s delay (measured: 0.06 s). `CI-135`, 8 red runs |
| A window is claimed only by the app that opened it | `window.open("TextEdit")` was returning one of the owner's **Safari** windows, stamped `vesper_opened`. `CI-136`, 8 red runs |
| The flag bar | `CI-137`, 8 red runs, plus a DOM stub driving the shipped receiver |
| Provenance survives a VESPER restart | `CI-138`, 7 red runs, driven across two processes |
| The window log | `CI-139`, 5 red runs |

**Five things that were believed and were false:**

1. *"A new window appears on whichever Desktop is showing."* Written in two
   places, false in both. What decides placement is still unknown, and the fix
   does not depend on knowing: read back where it landed.
2. *Window ids are reused, so provenance cannot be persisted.* Half right --
   they reset on a MACHINE boot, not on a VESPER restart, which is why vesper
   forgot every window a dozen times in one evening.
3. *The bridge's `accessible` field says whether vesper can act.* It answers YES
   while unable to enumerate a single window, because `AXIsProcessTrusted()`
   reports the responsible process -- the terminal.
4. *Five negative controls were protecting things.* Three had silently stopped
   applying their mutations; two passed under their own violation. All five
   tested whether an IDENTIFIER APPEARS rather than what the code does, and
   `checks.py all` was green throughout -- what regressed was the ability to
   detect anything.
5. *A window vesper opened is a window vesper can manage.* It opened TextEdit's
   **Open dialog**: correctly attributed, genuinely new, no close button, no
   action but `AXRaise`.

**The failure that cost the most:** the machine was left to sleep for three
hours because no `caffeinate` assertion was held. That is the reason this list
is shorter than it should be.


## 14 WHAT LANDED OVERNIGHT, 2026-09-10

The owner's own words for why this night happened: *"nothing is working
properly, and some cards even disappeared, even the UI is missed"*. Almost none
of that turned out to be destruction. **The code from 2026-09-09 had landed;
what was wrong was state, one sentence, one dedupe, and a language detector.**

### Done, driven through the RUNNING APP rather than the repo

| | |
|---|---|
| The answerer knows what vesper just said and what vesper can do | `answer()` took `intake.history[-1]` and nothing else. **Dating from 26 August**, not from the session being cleaned up |
| `window.list` reports the count the owner can act on | it reported `may_arrange` and dropped `needs_a_request`, so the doctrine took the blame for a sentence |
| **Modes, end to end, for the first time** | the watcher marked an ambience applied at the instant it FAILED, so it never retried. `Working -> working.png CONFIRMED by reading it back` |
| Speech stops switching to Arabic mid-sentence | `looks_arabizi` judged a `df -h` table to be Darija; 9 of its 37 tokens tripped it |
| A stage of work bounds what vesper opens (§11.2a) | the contract existed since 2026-09-09 and was **read by nothing**. `a-stage-bounds-what-vesper-opens`, 8 red runs, 8 self-test cases |
| The island shows both mode axes | `Mode` was the PERMISSION mode; vesper's own had no row at all |
| `--wallpaper-status` | the owner's first requirement was **unverifiable** — nothing could say what the desktop picture was |
| `--reinstall-login-item` re-reads the world | it printed five successes and exited 0 while the island was gone. Twice |

### Five things that were believed and were false

1. *The commands card is broken.* It is not: `_record_command` returns unless
   the capability is `shell.run`, so window work reaches it never. Driven: one
   `df -h` put an entry on it immediately.
2. *The wallpaper's problem is the lost record.* The problem was SCOPE, and the
   owner wants mode switching — they added those images. The residency guard
   had already landed; what had not is any way to check it.
3. *`island.json`'s `Mode: auto` shows the mode.* It is the PERMISSION mode. A
   reader who saw it and concluded modes worked was reading the right row for
   the wrong question. The owner corrected it.
4. *The capability-denial bug was last night's.* `git merge-base` puts it at
   26 August. The fix had been made for the proposer and never for the answerer.
5. *`self_test` finishing means the tree is safe.* `3c065dc` committed
   `deadline = s.ttl_ms` — a live mutation — as real code, and claimed in the
   same commit that 754/754 had passed "on the committed tree". It had not: the
   tree that passed and the tree that was committed were different trees.

### THE RULE THIS NIGHT ADDS

**Never commit while `self_test` is running.** MEMORY.md said run it alone, and
that was read as "or you get false failures". The real reason is that for the
fifty minutes it runs, **every file under the repo root is unsafe to read, let
alone commit** — it mutates a source file, runs a check, and restores it. A
commit lands whatever is mutated at that instant, with no signal at all.

### OWED, AND THE REASON — NOT "NOT STARTED"

| Owed | Why it did not happen tonight | What would unblock it |
|---|---|---|
| `window.open` rung 4 for already-running apps (Terminal answers `do script`, not `make new document`) | **Needs a live drive with the owner present.** TCC attributes automation to the RESPONSIBLE process, so testing it from a shell answers a different question than the one about vesper — that is §1 of the 2026-09-09 handoff and repeating it was refused | one drive from inside VESPER with its Desktop showing |
| Mode failures reaching the flag bar | **Structural, not an oversight.** Flags come from `executor.py` publishing `flag.raised` on a DEGRADED capability result; `mode.set` returns `ok` and Swift paints afterwards, so the failure happens after the only thing that can raise a flag has returned | a channel from the home back to the runtime, or `mode.set` not returning until the paint is judged |
| Steps 17 / 18 / 19 (apps, Notes, UI view) | **Acceptance is the owner looking at a screen.** "Working end to end with no hidden bugs" is their standard and it cannot be met on a display nobody is watching. Building them unverified is precisely the failure this night was spent cleaning up | the owner at the machine |
| Steps 20 / 21 (settings, projects/research) | the owner's own **⏸ DISCUSS FIRST** | their decision |
| A base wallpaper for the owner's OWN Desktops | the record was poisoned before it was quarantined; **what their picture was is not recoverable from here** | they pick one — the eleven were sent as a contact sheet |
| `INV-HOME-8` ratification; the `_AXUIElementGetWindow` decision; a Developer ID certificate | each is the owner's act, not an engineering task | their decision |
| **`owner_requested` is a flag nothing sets** — an authority decision, below | it would LOOSEN a guard that protects the owner's workspace, on my inference about what "the owner asked" means | the owner deciding turn-level vs step-level, below |

### THE `owner_requested` DECISION — OWED, AND WHY IT WAS NOT TAKEN

`window_open` and `_act` both lift their guards for `args["owner_requested"]`,
and the empty-Desktop refusal ends *"Ask for it and it will open here."*
**Nothing in the production path ever sets that flag.** `core/intent.py` does
not emit it, the actor does not inject it, and its only writers in this tree are
a check and a self-test asserting that the guards consult it. So the owner types
*"open a new terminal window"*, is refused, and is told to ask — which they just
did. Measured 2026-09-10 by driving their own sentence through the live app.

**The fix is one line and it is not mine to write.** The actor already knows
whether a turn is the owner's: `AutonomyLoop.dispatch` passes `permitted`, and
an owner-typed turn passes nothing, which is the discriminator `maybe_act`'s own
docstring names. So `owner_requested = (permitted is None)` is available.

**What makes it a decision rather than a bug fix is the turn/step gap.**
`permitted is None` marks a TURN as owner-originated, not each STEP. `maybe_act`
loops: the first proposal is the direct reading of what the owner said, and the
fifth is vesper's own elaboration on what it found. Lifting at turn level would
authorise vesper to put windows in the owner's workspace during steps they never
asked for — which is exactly the trespass §11.1's guard exists to refuse, and the
comment there is explicit that adding to their Desktop unasked "is the same
trespass as rearranging it unasked, and it is easier to do by accident".

Three ways to settle it, for the owner to choose:

1. **First step only.** `owner_requested` on step 0 of an owner-originated turn
   and nowhere else. Narrowest, and it makes the common case ("open X") work.
2. **Every step of an owner-originated turn.** Simplest, and it hands vesper the
   owner's Desktop for the length of any turn they started.
3. **Leave it unset and delete the lift.** Honest, and it means vesper never
   opens a window while the owner's Desktop is showing — the guard becomes
   absolute rather than advisory.

Until then the sentence no longer names a remedy that does nothing: it says
*"Switch to my desktop and I will open it there"*, which is true and works.

---

## 15 THE MORNING OF 2026-09-10 — THE BAR COULD NOT PUT ANYTHING DOWN

Three defects, one shape: **a surface that can only accumulate.** Each was
built, each passed its own gate, and each was reached by nothing that could
undo it.

### 15.1 `clear_flag` had one caller and it was the check for `clear_flag`

`core/home_state.clear_flag` worked. Its only caller in the tree was
`every-flag-reaches-one-bar`, which called it directly and then asserted the row
had gone — so `CI-137` proved the mechanism and **nothing in production ever
retracted a flag.** The check's own comment reads *"or the bar reports a problem
that is over"*: it describes the live defect rather than guarding against it.
That is `MEMORY.md`'s "checks can be alive and useless" in its purest form —
**the probe supplied the behaviour it was testing for.**

What it costs the owner is a false alarm with no expiry. `CLAUDE.md` records
that **every rebuild revokes accessibility**, so the ordinary sequence is:
rebuild, an act fails, `host.accessibility` is flagged, the owner grants it,
vesper works again — and the bar goes on telling them to grant it for as long as
the process lives. The mode watcher made it routine rather than rare: the
2026-09-10 fix made it **retry**, so *fail → flag → retry → succeed* is now the
normal path.

**Landed:** `flag.cleared` published from the executor's choke point — the same
one `flag.raised` uses — on a result that is not `degraded` and not
`ok: False`; `flag_id_for()` extracted so raise and retract cannot derive
different names; the runtime subscribes and calls `clear_flag`.
`a-flag-is-retracted-when-its-condition-clears`, **8 red runs**.

**Two things were deliberately NOT retracted.** A **refusal** ("that window is
not yours") says nothing about whether an earlier failure is over. And a
**degraded success** — `window.relocate` returns `ok: True, degraded: True` when
it rebuilt a window instead of moving it — must not cancel the flag the same
result just raised. Both are driven controls.

**And the rung came out of the flag id.** It was in the derivation, so
`window.relocate`'s four named failure rungs each got their own row for one
unresolvable situation, *and* a relocation that failed at `cannot_degrade` and
later succeeded derived two different names — so no retraction could ever match.
A rung is which ATTEMPT failed, which is the execution detail the id's own
comment says it is not about.

**Who may resolve what.** The derived id covers "same capability, same target,
did not fail this time" — no inference, the same condition re-measured. A
capability that has read the world may name more, in `resolved`: a window act
that SUCCEEDS is direct evidence accessibility is granted, and `window.list` is
the only thing that can retire `window.landed_elsewhere` — whose own words are
*"it is yours to close"*, so the condition ends with an act by the OWNER that no
capability is running for.

### 15.2 A mode that did not land now reaches the bar — §14's owed item, closed

§14 recorded this as **structural, not an oversight**, and the structure was a
channel. `mode.set` resolves the pairing, writes `ambience` into `home.json` and
returns `ok`; the **paint happens in another process** up to half a second
later, where the usual answer is a refusal. By then the result that could have
carried a flag is already spoken.

**Not by blocking `mode.set` until the paint is judged**, which was the other
option §14 named and is worse in the case that occurs: the refusal is
**transient** — the owner switches Desktop and it lands — and can last minutes,
so a blocking call would hang the turn rather than answer it.

`ambience.jsonl` + `ambience.offset`, the shape `heard.jsonl` already has.
`setMode` now records a **sentence** on each of its three ways of answering no;
the watcher appends on the transition, not the tick. `a-mode-that-does-not-land-
reaches-the-bar`, **10 red runs**.

**AND DRIVING IT FOUND THE STATE THE CHANNEL COULD NOT SEE.** The mode watcher
belongs to `Home`, which **does not exist until the ground is planted** —
`--on-empty-desktop` refuses to plant it where the owner has windows, and on a
machine in use **that wait is the normal state**. Driven with four of the owner's
windows on the Desktop showing: they asked for rest mode, `mode.set` resolved it,
wrote `ambience: Rest`, answered *"rest mode -- Nothing asked. VESPER is present
and doing nothing"*, and nothing painted or reported. The channel was complete
and blind in the one state it most needed to see. So the **wait reports too**,
through a shared `AmbienceReport` rather than a second copy of the append.

**Live, in the running app, for the first time:**

> vesper has no desktop of its own yet: 4 of your windows are on the one
> showing, and it will not take a desktop you are working on. switch to an empty
> desktop and it will set up there and apply Rest

### 15.3 Vesper answered the owner in this system's own vocabulary

Fixing "vesper denies what it can do" (§14) introduced this on the same night,
and **nothing gated either half**. `capability_statement()` ended every line with
the internal id — `(shell.run)`, `(mode.set)`. Driven: the owner typed *"switch
to focus mode"*; the **proposer correctly returned no action**, because its own
prompt lists the six real modes and says "do not invent one"; and the answerer
replied **`mode.set: focus mode.`** Four words, none of them an answer, one of
them a name the owner has never seen.

**And the answer they needed was a list.** `modes.select` writes exactly the
right refusal — *"there is no mode called 'focus mode'. The ones that exist
are…"* — and it is unreachable for a mode that does not exist, because nothing
ever calls `mode.set` with it. The only party that could answer was the
answerer, and it knew a mode could be entered without knowing which ones there
were. The statement now names them, **read from the contract**.

**ASKING THE MODEL WAS NOT ENOUGH, AND IT FED ITSELF.** With the ids removed
*and* an explicit instruction added, the leak continued — because the answerer is
given the conversation so far, the bad reply was in it, and the model copied the
shape of its own previous answer. **That loop does not decay: each new reply
renews it.** Measured over three turns. So `strip_internal_prefix()` is applied
to the reply **and to the rendered examples**, from one function — an instruction
is a self-report, and this corpus does not accept those as evidence anywhere
else. `last_action`'s `f"{capability_id}: {said}"` format, which seeded it, is
gone; its own comment already said the id added nothing.

**Live, after:** *"focus – unknown. Available modes: explain, idle, research,
rest, show, work."*

`vesper-answers-in-the-owners-words`, **10 red runs**. It also found a second
`answer()` call site — the agenda's phrasing pass — which must **not** get the
capability list: its prompt says "Do not add anything that is not here".

### 15.4 Four of my own negative controls passed under violation

Same §4 defect as 2026-09-09, four more times, and each one is worth naming
because the failure mode is not "I forgot" — it is that **a presence test is
satisfied by whichever copy of the thing still exists.**

| The vacuous assertion | Why it could not fail | What replaced it |
|---|---|---|
| `count("lastModeReason=") < count("returnfalse")` in `setMode` | 3 reasons against 2 refusals — one of the three ways it answers no **falls through to `return ok`** rather than returning false. The totals carried a spare | split on the refusals and require each segment, tail included, to carry its own sentence |
| `"AmbienceReport.append(" in main_src` | appending `, false` to the guard leaves the string exactly where it was | read the condition between the opener and its brace and require it to be `want != reportedWant` alone |
| `"reportedWant" in main_src` | deleting the clause that USES it leaves the declaration | as above, plus the assignment must be inside the block |
| `flag_id_for` reads no rung, tested as a substring | the word `rung` is in that function's **own docstring explaining why it is absent** | walk the AST with the docstring stripped, over names, subscripts and call arguments |

**And one assertion went red on correct code**, which is the cheaper direction:
the `flag.cleared` site was asked whether the shared derivation appeared **inside
the publish call**, and it does not — the site publishes one event per resolved
id, so the call is the enclosing loop's `iter`. Fixed by reading the loop.
A second one compared AST nodes from **two separate parses** of the same file
with `is`, which is never true; one tree, reused.

### 15.5 Counts

158 checks, 790 self-test cases. Three checks, **28 executed red runs**, four
vacuous controls found and rewritten before landing.

### 15.6 What this leaves for the owner

- **Accessibility was revoked by tonight's rebuilds** — it is keyed to the
  cdhash and `build.sh` re-signs every build. Grant it once
  (System Settings → Privacy & Security → Accessibility) and the
  `host.accessibility` flag will **retract itself** the first time vesper touches
  a window, which is the new behaviour worth watching.
- **VESPER has no Desktop right now** and is waiting: four of your windows are on
  the one showing, and it refuses to take a Desktop you are working on. Switch to
  an empty one and it will plant the ground, apply `Rest`, and the flag in the bar
  will clear itself.
- **1.7 GB of bus log** across three segments, dominated by
  `autonomy.heartbeat` — 3607 of the last 5000 events. Not from tonight, and
  worth a decision on a machine whose first goal is host lifetime.
- Everything §14 lists as owed and owner-gated still is: the base wallpaper, the
  `owner_requested` authority decision, `INV-HOME-8`, `_AXUIElementGetWindow`,
  a Developer ID certificate, and `kill -9 62839`.

---

## 16 THE WALLPAPERS, 2026-09-10 — TWO SYSTEMS THAT NEVER TOUCH

**Owner:** *"i would like the default wallpaper from mac os that i will apply
everywhere to be separate from vesper's wallpaper system, and viseversa, nothing
touches the other's"*, and *"i want all wallpaper from vesper to be attached to
their modes and actually working end to end, not just some of them, with the
animation thing"*.

### 16.1 The measurement that decided the architecture

Read from macOS's own wallpaper store
(`~/Library/Application Support/com.apple.wallpaper/Store/Index.plist`, macOS
26.5), cross-referenced against the live Space list:

| | |
|---|---|
| **All three** live Desktops | showing a VESPER image |
| 37 of 42 store entries | ours, including Spaces that no longer exist |
| The owner's own picture | surviving in exactly **one** |
| `savedOriginalPath` | **EMPTY** — vesper could not have put any of it back |

**And that was measured WITH the residency guard in place.**
`setDesktopImageURL` has no Space argument; it repaints whichever Space is
showing. A guard in front of it is only as good as the instant it is asked in,
and vesper has run across many Space arrangements. **The fix could not be a
better guard.**

### 16.2 What replaced it

Vesper's ground is already a full-screen layer at `normal - 1` — below every
window of the owner's, above the desktop icons. Painting *that* is confined to
vesper's own window **by construction**: it cannot reach another Space, cannot
reach the lock screen, and when vesper is off the window does not exist, so
there is nothing to undo. No guard can promise that; **the absence of the call
is the promise**, and `HomeAmbience` now writes the system picture **zero
times**.

`apply` and `restore` are both gone, and `restore` is the more interesting one:
it put the owner's picture back after vesper replaced it, vesper no longer
replaces it, so the reversal had nothing to reverse — while still holding a live
`setDesktopImageURL`. **One caller is one more than zero.**

**AND IT IS THE ONLY ROUTE THE ANIMATIONS COULD EVER HAVE TAKEN.**
`setDesktopImageURL` accepts a still image. Three of the eleven modes ship a
`_animated.mp4` that nothing had ever opened. So the animation requirement was
not an addition to the old approach — it was a **second independent reason** it
had to go.

### 16.3 `research` had no wallpaper of its own

It paired to `Working`, the same as `work`, so asking for research changed the
stage and left the room identical. `Milestone` was the eleventh ambience and
**no pairing reached it** — authored, shipped, unreachable from anything the
owner could say. Now `research → Milestone`.

### 16.4 Armed when set, played when entered

Those are different moments: vesper is usually told to change mode while the
owner is somewhere else, and playing at `setMode` runs the whole thing at a
Desktop nobody is looking at. So setting a mode **arms**; the ground becoming
the Desktop showing **plays**, once per mode session, muted, torn down on
`AVPlayerItemDidPlayToEndTime` rather than on a guessed duration. Arrival is
read as an **edge** — a state test would restart it twice a second.

### 16.5 Two instruments were lying, and both sent a reader the wrong way

**`--wallpaper-status` counted the island as the ground.** The island is
`.canJoinAllSpaces` — on every Desktop by design — so every Desktop read as
vesper's. It printed *"3 of your window(s) here, 1 of vesper's"* on a Desktop
whose only vesper window was the island, and **I repeated that to the owner**.
The ground is the only window that cannot follow, so it is now identified by
sitting **below layer 0** rather than by being present.

**`com.apple.spaces.plist`'s `Current Space` is stale.** The first "never take
Desktop 1" rule read it. Measured: the file sat unwritten for **4.5 minutes**
across several live Desktop switches, so it answers **confidently and wrongly** —
worse than not answering, because the fail-closed path never fires. Vesper
planted on Desktop 1 with the guard in place and the guard reading "you are on
the third".

### 16.6 The SPI decision, and why it was put to the owner

There is **no public API** for which Desktop a window is on. Probed on macOS
26.5: `CGWindowListCopyWindowInfo` returns eleven keys and `kCGWindowWorkspace`
is not among them. **The owner took the decision** to use `CGSGetActiveSpace`,
loaded **by name at runtime** so a macOS release that drops it yields `nil` —
which the rule already refuses on — rather than a process that will not launch.

The file is still used for the half it can be trusted with: **which Spaces exist
and in what order**. Only the volatile half comes from the private call. And a
second clause the first version missed: `CGSGetActiveSpace` returned `54` while
the owner's Desktops were `1, 6, 38` — a **fullscreen** Space. An id in no
Desktop list resolves to "cannot tell" and refuses.

### 16.7 What was never observed until it was made observable

The animation shipped with a check carrying eight red runs, and **no evidence it
had ever run**. Asked "is it done", I grepped the log and got zero — which
proved nothing, because there was nothing in the log to find. **A check
asserting the code exists is not a feature working.** Two print lines later:

```
animation: milestone_animated.mp4 — playing once, then holding the still frame
animation: finished — still frame is what remains
```

### 16.8 Verified, after the owner reset their wallpaper

**0** of 42 store entries hold a VESPER image, down from 37. All three live
Desktops are theirs. Vesper applied `Milestone` after the reset and their
picture survived it — the separation demonstrated rather than asserted.

### 16.9 Gates

160 checks. `vespers-wallpapers-never-touch-the-owners` (8 red runs) and
`vesper-never-takes-the-owners-first-desktop` (4).
`the-wallpaper-changes-only-on-vespers-desktop` was **rewritten**, not left
passing: its subject was deleted, and all three of its cases had gone stale —
which the harness reported as *"the artifact has changed shape and this
self-test is no longer testing anything"*.
