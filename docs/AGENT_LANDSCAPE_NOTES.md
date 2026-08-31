# Deep investigation — what the leading agents have that VESPER doesn't

Working notes. Appended as I go. Final deliverable: an artifact.

**Owner's framing:** VESPER is for coding, projects, studies, research. Projects
are critical — one small mistake can blow the whole thing. So safety and
efficiency outrank feature count. Goal: as good as Claude Code at coding, Gemini
at research, Codex at what it's best at, and steal from everything else.

**Standing filter for every finding** (established earlier tonight):
1. Is it expressible as a capability whose **level varies with its arguments**?
   The registry executes each rule's example and refuses a constant.
2. Is it **Python-only** (no Swift rebuild → no TCC grant revocation)?
3. Does it reduce the chance of **breaking a project**? That's the owner's
   stated top concern.

**Deferred, by owner's instruction:** Gemini for research capability — note it,
do it when we get to research.

---

## SOURCES

| System | Licence / access | Route |
|---|---|---|
| Claude Code | proprietary, compiled | my own tool inventory (primary) + public docs |
| Codex | **Apache-2.0, source public** | github.com/openai/codex + learn.chatgpt.com/codex |
| Gemini CLI | Apache-2.0 (to confirm) | later, per owner |
| Others | varies | docs/repos |

---

## FINDINGS

(filled in below as I go)

---

## CODEX (Apache-2.0, cloned and read as source — docs/ are stubs pointing at the website)

### C1. Containment, not just classification — THE STRUCTURAL FINDING
`codex-rs/sandboxing/src/seatbelt_base_policy.sbpl`, ~120 lines, adapted from
Chrome's macOS sandbox policy. Opens with `(deny default)` and allowlists
specific syscalls, sysctls, IOKit classes and paths. Layered on top at runtime:
writable roots (`/tmp`, `/private/tmp`, `/var/tmp`), and a SEPARATE network
policy (`seatbelt_network_policy.sbpl`) plus a whole `codex-network-proxy`
crate. `seatbelt.rs` is 1043 lines.

Modes: `read-only` / `workspace-write` / `danger-full-access`.
Approvals: `untrusted` / `on-request` / `never`.

**VESPER comparison — and this is the headline.** Our ladder is FINER than
theirs: six levels computed per-argument, versus three global modes. But ours is
**advisory**. `core/capabilities.py` classifies, then `subprocess.run` executes
with the owner's full privileges. If the classifier is wrong nothing catches it
— and it was wrong three times in one night (`ls; rm -rf ~`,
`workspace/../../etc/passwd`, `cat ~/.ssh/id_rsa`). Codex's confinement does not
need to be right about the command.

**Verified available here:** `/usr/bin/sandbox-exec` exists and works —
a deny rule made `~/.ssh/id_rsa` return "No such file or directory" to `cat`,
while unrelated commands still ran. Python-only, no Swift rebuild.

### C2. `execpolicy` — rules carry NEGATIVE examples, validated at load
Starlark `prefix_rule(pattern, decision, justification, match, not_match)`.
Decisions: `allow` / `prompt` / `forbidden`. The `match` / `not_match` examples
are "validated at load time (think of them as unit tests)".

**VESPER comparison.** We independently converged on the same idea —
`CapabilityRegistry.register` EXECUTES each `LevelRule.example` and refuses a
constant. But ours has only POSITIVE examples. Theirs declares what a rule must
NOT match, checked at load. That is precisely this corpus's own doctrine ("a
negative control that passes is a defect") applied to the level rules, and we do
not do it. **Directly actionable, Python-only.**

Also: `justification` per rule, surfaced in the approval prompt. We carry the
proposer's `why`, which is the MODEL's reason; theirs is the RULE's reason,
which is the one the owner needs to judge the request.

### C3. `apply-patch` — 5106 lines for editing files, and one idea we lack
Notably: "A failed patch application together with the textual mutations that
were **definitely committed before the failure was observed**." Partial-failure
accounting for multi-file edits. Also explicit symlink policy, and
`seek_sequence.rs` for locating a hunk that has drifted.

**VESPER comparison.** `fs.write` replaces WHOLE FILE CONTENTS. That is the
single most dangerous primitive we have for the owner's stated fear: a truncated
or partial model output silently destroys a file, and our hash verification
would happily confirm we wrote exactly the truncated thing. No surgical edit
primitive exists.

### C4. Crates worth a second look
`code-mode`, `agent-roles`, `agent-identity`, `agent-graph-store`,
`codex-mcp`, `bwrap` (Linux containment), `cloud-tasks`.

---

## CLAUDE CODE (proprietary binary; read from my own tool contracts + public docs)

### CC1. Read-before-edit is ENFORCED, and we have nothing like it
`Edit`: *"You must Read the file in this conversation before editing, or the
call will fail."* `Write`: *"Overwriting an existing file you haven't Read will
fail."* Not advice — a refusal.

`Edit` also requires the `old_string` to match **exactly and uniquely**; an
ambiguous or absent match fails rather than guessing.

**PROBE RUN AGAINST VESPER, 2026-09-01.** A five-line file in the workspace.
`fs.write` with one line of content:
  - level required: **L2** — silent, no permission asked
  - prior read required: **none**
  - independent verifier: **verified = True**

The file went from five lines to one, and our verification CONFIRMED it. The
verifier compares the disk to what the write INTENDED, so a truncated intent is
a truncated success. This is exactly the owner's stated fear -- "one small
mistake can blow the whole project" -- and it is reachable today with no
confirmation.

Three separate defences are missing: no read-before-write, no surgical edit, and
a verifier that cannot tell destruction from intent.

### CC2. Hooks — an OWNER-EDITABLE veto on every tool call
Events: `SessionStart/End`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`, `PostToolBatch`,
`Stop`, `StopFailure`. `PreToolUse` can DENY with a reason the model then sees;
exit code 2 blocks unconditionally. Matchers select by tool name plus an `if`
pattern on the arguments.

**VESPER comparison — an architectural inconsistency of our own.** Our entire
capability policy is HARD-CODED IN PYTHON: `READ_ONLY_VERBS`,
`DESTRUCTIVE_MARKERS`, `SECRET_MARKERS`, `GOVERNED_PREFIXES` all live in
`core/capabilities.py`. The owner cannot say "never touch this directory"
without editing my code. That contradicts this corpus's own architecture, where
policy lives in `contracts/policy/*.toml` and "promotion into a contract is a
separate reviewed act". The capability policy is the one policy I did not put in
a contract.

`PostToolUse` for lint-after-write is the analogue of our independent verifiers,
except theirs is owner-supplied and ours is a fixed table.

### CC3. Mechanisms we have no equivalent for
- **Deferred tool schemas (`ToolSearch`)** — tools listed by NAME, full schema
  fetched on demand. This is literally the handwritten requirement: "instead of
  tons of tokens/md/txt files/codebase ... a map where the model navigates."
- **Permission modes** — default / plan / auto / bypassPermissions, as a session
  stance, orthogonal to per-call levels.
- **Plan mode** — propose a plan, get approval, then act. Partially overlaps our
  stop-and-ask.
- **Background execution + re-invocation on completion**; `Monitor` to wait on a
  condition rather than poll.
- **Scheduled work** (cron) — the owner's "work at night on its own".
- **Subagents with git-worktree isolation** — parallel work that cannot collide.
- **LSP** — real language diagnostics rather than grep.
- **Skills** — packaged, named instruction sets loaded on demand.
- **MCP** — one protocol for external tools, so calendar/notes/messages do not
  each need bespoke code.
- **File-state tracking** — the harness knows what has been read/edited, which is
  what makes read-before-edit enforceable at all.

---

## AIDER (Apache-2.0, Python — closest language match to us)

### A1. Repo map: tree-sitter symbols ranked by PageRank
`aider/repomap.py` extracts symbol tags with tree-sitter, builds a graph of
references between files, and runs `networkx.pagerank` over it to decide what
the model is shown. Cached in SQLite, versioned.

**VESPER comparison.** This is a concrete, working answer to the handwritten
requirement "a map where the model navigates" instead of dumping files. We have
`graphify` for our own use, and nothing VESPER itself can navigate. Python, and
our corpus is stdlib-only in `tools/` -- tree-sitter and networkx would be the
first third-party dependencies, which is a real decision, not a detail.

### A2. Every AI edit is a git commit, and undo refuses to touch YOURS
`cmd_undo` reverts the last commit only if its hash is in
`aider_commit_hashes` -- commits aider made in this session. Otherwise it
refuses and tells you to use `git reset` yourself.

**VESPER comparison.** Our `fs_write_compensator` restores the previous contents,
but only from the in-memory result of that one execution, for one file, within
that call. Once the turn is over there is no undo at all.

## CLINE — shadow git, better shape than Aider's for us
A shadow Git repository SEPARATE from the project's real history, committed
after EVERY tool use. Restores three ways: files only, conversation only, or
both. The owner's own git history stays clean.

**Better for VESPER than Aider's model**: VESPER should not be writing commits
into the owner's project history for every action, but it must be able to undo
anything it did. This is the single strongest available answer to "one small
mistake can blow the whole project".

## OPENCLAW / CLAWDBOT / MOLTBOT (Peter Steinberger) — THE CLOSEST THING TO VESPER
Self-hosted personal assistant bridging WhatsApp / Telegram / Signal / Discord /
Slack to a coding agent with full system access, persistent memory, a web
control UI, and capabilities installable on the fly. Went viral Jan 2026. It is
essentially VESPER's shape, including the phone bridge the J3 is meant to be.

### PROBED VESPER AGAINST ITS DOCUMENTED SECURITY FAILURES (2026-09-01)

| Their failure | VESPER |
|---|---|
| Unauthenticated loopback WebSocket on :18789, any local process drives the bot | **Not present.** The runtime is FILE-DRIVEN by explicit design -- `vesper_runtime.py` argues for a file over a socket. No listening TCP socket; `lsof` confirms. |
| 1,673 instances exposed to the internet (Shodan, Jan 2026) | **Not reachable.** No network listener to expose. |
| RCE via that port at user privilege | **Not reachable** by the same route. |
| **Credentials in plaintext JSON/MD, no OS keychain** | **SAME FAILURE.** `~/.config/vesper/secrets.env`, 0600, ASCII, ~9.6 KB, ~30 API keys in the clear. macOS Keychain is right there and unused. |
| Memory poisoning — persistent memory lets an attacker change BEHAVIOUR, not just steal data | **Partly defended.** `core/memory.py` carries a `trust_class` column whose stated question is "may this be ACTED ON?", plus rank. Stronger than theirs; needs a probe that it is actually enforced on the acting path now that acting exists. |

Two of five are architectural wins we already had. One is an exact match and is
the most valuable single thing to fix from this whole investigation, because it
is a documented real-world failure of the nearest comparable system.

---

## TRIAGE OF THE REST (honest, rather than a section per name)

- **Kimi** — Kimi Code CLI (Jan 2026), K2.6/K2.7 open weights (Modified MIT),
  self-hostable. One harness idea worth the name: a **"swarm supervisor" wired in
  by default**, i.e. multi-agent orchestration as the default posture rather
  than an opt-in. Model weights matter to VESPER's supplier table, not its
  harness.
- **Grok** — has a CLI; nothing found that is a harness idea we do not already
  have from Codex/Claude Code. Revisit if a specific claim surfaces.
- **Hermes, Venice** — these are MODELS / inference providers, not agent
  harnesses. There is no harness feature to take. Venice is interesting for a
  different and narrower reason: privacy-positioned inference, which touches
  VESPER's `E1_PRIVATE` supplier story, not its tooling.
- **Gemini** — DEFERRED BY THE OWNER to the research phase. Note kept: Gemini CLI
  is Apache-2.0 and its research/grounding behaviour is the thing to study when
  we build VESPER's research capability.

---

## PROBE: can a poisoned memory steer an ACTION? (2026-09-01)

Asked because OpenClaw's documented memory-poisoning risk is about changing
BEHAVIOUR, and VESPER only started acting yesterday.

`core/intent.py` references neither memory nor persona. `propose(text)` takes
the raw utterance and nothing else, and the runtime calls
`actor.maybe_act(intake.history[-1].text)`.

**So memory reaches the ANSWER path and not the ACT path.** A poisoned fact can
make VESPER say something wrong; it cannot make VESPER do something.

This is real isolation and it was ACCIDENTAL -- I wrote the proposer that way
for simplicity, not for this reason. It should be made deliberate and GATED,
because the obvious future "improvement" is to give the proposer context so it
proposes better actions, and that change would silently connect an
attacker-influenceable store to the thing that runs commands.

---

## WHAT TO ACTUALLY BUILD, RANKED

Ranked by the owner's own criterion -- reduce the chance of blowing a project --
then by cost. All are Python-only unless marked.

1. **Shadow-git checkpoint + undo** (from Cline). Commit every file-touching
   action to a shadow repo; restore files, or the turn, or both. Nothing else on
   this list buys as much safety per line.
2. **Read-before-write, enforced** (from Claude Code). Refuse `fs.write` on an
   existing file this turn has not read. Closes the probe above.
3. **`fs.edit` — surgical old→new, unique-match-or-fail** (Claude Code / Codex
   apply-patch). Removes whole-file replacement as the default way to change a
   file.
4. **Seatbelt containment for `shell.run`** (from Codex). `sandbox-exec` is
   present and proven on this machine. Classification stops being the only
   defence.
5. **Credentials into the macOS Keychain** (from OpenClaw's real compromise).
   Our plaintext `secrets.env` is the one exact match to a documented failure.
6. **Negative examples in `LevelRule`, validated at registration** (from Codex
   execpolicy `not_match`). Our own doctrine, not yet applied to level rules.
7. **Capability policy into `contracts/policy/`** (from Claude Code hooks). The
   owner cannot currently constrain VESPER without editing Python.
8. **Gate the memory/act isolation** so it cannot be "improved" away.
9. **Repo map** (from Aider) — tree-sitter + PageRank. Answers the handwritten
   navigation requirement. Costs the stdlib-only rule; a real decision.
10. **MCP client** — one protocol instead of bespoke code per integration.
    Biggest multiplier for calendar/notes/messages, but it is surface area, so
    it comes after containment.

---
---

# PART TWO — THE CORE I MISSED: how commands actually get work done

The first pass was about SAFETY and missed the thing the owner actually values:
the way these systems work with commands to achieve a goal cleanly. That is not
a feature, it is the shape of the whole loop, and VESPER does not have it.

## THE OMISSION, PROBED (2026-09-01)

`core/actor.py`: `propose(text)` once → `execute()` once → return. The only
`for` in the file is the grant issuer. `vesper_runtime.py` calls
`actor.maybe_act(...)` exactly once per utterance.

**VESPER CANNOT TAKE A SECOND STEP.** It cannot run `ls`, look at the output,
and then read the file it found. It cannot try something, see it fail, and fix
it. Everything the owner describes as magical about Claude Code and Codex is
that loop, and we have a straight line.

Every item below is downstream of this. A better tool set with no loop is still
one action per sentence.

---

## A. COMMAND ERGONOMICS — why it feels clean

### A1. A PERSISTENT SHELL SESSION (Codex `zsh_fork` / `unified_exec`)
`core/src/tools/runtimes/zsh_fork.rs` forks a real zsh and "keeps the escalation
server alive **for the session**". So `cd`, exported variables, an activated
virtualenv, a running dev server — all survive between calls.

Claude Code takes a deliberate middle position, stated in its own contract:
*"Working directory persists between calls, but shell state (env vars,
functions) does not persist; the shell is initialized from the user's profile."*
A considered tradeoff, not an accident — reproducibility over convenience.

**VESPER:** `subprocess.run(shlex.split(cmd), cwd=REPO)`. Every command starts
from nothing. `cd` is meaningless. There is no session at all.

### A2. PARALLEL INDEPENDENT CALLS
Claude Code's standing instruction: *"If you intend to call multiple tools and
there are no dependencies between the calls, make all of the independent calls
in the same block."* Codex has `core/src/tools/parallel.rs` and a
`PostToolBatch` hook that fires after parallel calls resolve.

**VESPER:** one action per turn. Not "one at a time" — literally one.

### A3. BACKGROUND EXECUTION WITH RE-INVOCATION
Claude Code `Bash(run_in_background)`: *"runs the command detached: it keeps
running across turns and re-invokes you when it exits."* Plus `Monitor` to wait
on a condition instead of polling. Codex has `sleep` and
`wait_for_environment` as first-class tools.

**VESPER:** a 20-second default timeout and nothing else. A build, a test suite
or a long install cannot be run at all.

### A4. TIMEOUTS AS A PARAMETER
Claude Code: default 120 s, max 600 s, per call. **VESPER:** 20 s, and the model
cannot ask for more.

---

## B. TURN CONTROL — the model steering its own execution

Codex exposes these AS TOOLS (`core/src/tools/handlers/`). None exist here:

| Codex tool | What it buys | VESPER |
|---|---|---|
| `plan` | write a plan, then work it | absent |
| `request_permissions` | the model asks for elevation MID-TASK and continues | absent — our refusal ends the attempt |
| `request_user_input` | ask a question without ending the turn | absent — `core/confirm.py` asks, then the turn is over |
| `send_user_message_async` | tell the owner something while still working | absent |
| `sleep`, `wait_for_environment` | waiting as a deliberate action | absent |
| `view_image` | look at an image | absent |
| `current_time` | ask the clock | we shell out to `date` |
| `multi_agents`, `multi_agents_v2` | delegate a sub-task | absent |
| `tool_search` | find a tool | absent (we have 3) |

**`request_permissions` is the important one.** Our ladder refuses and the turn
ends. Theirs refuses, the model ASKS, and on approval the SAME task continues.
That is the difference between a gate and a dead end — and it makes the
stop-and-ask ladder we already built far more useful than it currently is.

---

## C. CONTEXT ECONOMY — the corpus's own "map" requirement, solved

### C1. `get_context_remaining` — a TOOL for the model to check its own budget
Codex lets the model ask how much context it has left, and decide accordingly.

### C2. `new_context_window` — a deliberate fresh start
The model can choose to reset rather than degrade.

### C3. Compaction, manual and automatic
`core/src/compact*.rs` — ~12 files including `compact_token_budget.rs`,
`run_manual_compact_task` and `run_inline_auto_compact_task`, plus a remote
compaction path and an image budget. Claude Code summarizes automatically when
the conversation grows long.

**VESPER has `core/compactor.py`.** Present. Needs checking against the acting
path now that turns can carry tool output.

### C4. MARKED FRAGMENTS — injected context is recognizable later
`context-fragments/src/fragment.rs`: fragments carry START/END markers "used to
recognize injected context later".

**VESPER:** `core/context.py` Fragments carry NO markers. Once context is
injected we cannot find it again to prune or replace it.

### C5. DEFERRED TOOL SCHEMAS
Both have it (`tool_search` / `ToolSearch`): tools listed by NAME, full schema
fetched on demand. This is the handwritten requirement verbatim — "a map where
the model navigates" — and it is the mechanism, not an analogy.

---

## D. FILE PRIMITIVES — the details that stop damage

Claude Code's `Read`: `offset`/`limit` for large files; images rendered; PDFs by
page range; notebooks as cells with outputs. `Edit`: `replace_all` for renames.
And a doctrine worth copying verbatim: *"Do NOT re-read a file you just edited
to verify — Edit/Write would have errored if the change failed, and the harness
tracks file state for you."*

**That last line is the whole efficiency argument.** The harness tracks file
state, so the model does not spend a call confirming what the tool already
guaranteed. VESPER tracks nothing between calls.

**VESPER `fs.read`:** a `limit` only, no `offset`, text only. No images, no PDFs.

---

## E. PROJECT INSTRUCTIONS AS A CONVENTION
Claude Code auto-loads `CLAUDE.md`; Codex has `AGENTS.md` as a documented
convention. Per-project standing instructions, loaded every session.

**VESPER** has its own memory and `MEMORY.md`, but nothing that reads a
project's own instruction file when it works inside that project. If VESPER is
to work on projects other than itself, this is how it learns each one's rules.

---

## F. WHAT THIS ADDS TO THE BUILD LIST

Inserted ABOVE most of the safety list, because a straight line cannot be made
safe by adding guards to it — and because the loop is what the owner is asking
for. Numbering continues the earlier list conceptually; order is what changes.

- **L1. The agentic loop.** propose → execute → OBSERVE → propose again, until
  done or a step limit. Everything else is downstream.
- **L2. A persistent shell session.** So `cd`, env and a venv survive.
- **L3. Parallel independent actions** in one step.
- **L4. Background execution + a wait/monitor primitive**, and a timeout the
  model can set.
- **L5. `request_permissions` mid-task** — turn our dead end into a gate.
- **L6. `request_user_input`** — ask without ending the turn.
- **L7. `fs.read` offset + images/PDF; `fs.edit` replace_all.**
- **L8. Context budget tools** — `get_context_remaining`, marked fragments.
- **L9. Project instruction files** (`AGENTS.md` / `CLAUDE.md` convention).
- **L10. Delegation** — sub-agents for sub-tasks.

---

# PART THREE — THE OUTER LOOP: keeping going on its own

Owner's addition, 2026-09-01: the loop should not stop when the asked-for task
is done. It should look for something else to do, decide INTENTIONALLY whether
to advance its own work (ideas, research, projects), keep going, ask if
necessary, and stop when there is nothing to do — or nothing that should be done
*at that time*, or nothing *necessary* at that time.

## THIS IS ALREADY BUILT, AND IT IS STARVED

`core/autonomy.py` has `Trigger`, `PredicateEvaluator`, `AutonomyLoop`,
`AutonomyRunner`. It RUNS — `vesper_runtime.py` line 591 calls it every pass.

And it is not a naive scheduler. It is careful in exactly the ways the owner's
sentence requires:

- **`CronDisguisedAsTrigger`** — refuses a trigger that fires on the clock
  alone, whatever it is labelled. That is "not at that time to do" enforced.
- **`NonTerminatingPredicate`** + `assert_terminating` — a predicate that cannot
  be shown to terminate is refused AT REGISTRATION, before it is ever run.
- **Predicates are CALLABLES, not strings.** The comment says why: "a string
  predicate needs an interpreter, and an interpreter is a place a model call can
  hide."
- **`ModelCallInDecisionPath`** — the gateway REFUSES a model call in the
  decision path.
- Predicate classes: `STATE`, `EVENT`, `COMPOSITE`, `SCHEDULE`, with declared
  `clock_terms` / `state_terms` and an `anti_cron_probe` that checks the
  declaration.
- `debounce_s` per trigger; an interruption budget by period and attention state.

**What is missing is not the machinery. It is two connections and some content:**

1. **ONE trigger is registered.** `autonomy.register(expiry_trigger())` — memory
   expiry, and nothing else. The loop wakes up, finds nothing to consider, and
   goes back to sleep. It is a working engine with one instruction.
2. **The autonomy layer has NO reference to the actor.** `grep actor
   core/autonomy.py` returns nothing but an unrelated comment. So even when a
   trigger fires, autonomy cannot DO anything — it can publish an event. The
   capability system landed yesterday and was never joined to it.

## THE DESIGN TENSION THE OWNER'S REQUEST CREATES — worth stating before building

"Decide if it would like to do something else intentionally" sounds like
judgement, and judgement sounds like a model call. **This corpus refuses model
calls in the decision path**, deliberately, and refuses string predicates for
the same reason.

The resolution is a split, and it should be explicit in the design:

- **WHETHER to wake** is decided by deterministic predicates over declared state
  — is the machine idle, is it charging, is it FREE_TIME, is the owner absent,
  is there an open item in `TriageQueue`, did a project's tests start failing.
  No model. This is the part `core/autonomy.py` already enforces.
- **WHAT to do once awake** may be a model call — proposing work, ranking ideas,
  drafting a plan — because by then the decision to act at all has already been
  made by something auditable.

That split preserves the invariant and still gives the owner what they asked
for. Building it the other way — a model deciding, in the predicate, whether it
feels like working — would break the one rule this layer exists to enforce, and
would do it invisibly.

## WHAT THE FIELD DOES HERE

Weaker than what we already have, which is worth knowing before copying anything:

- **Claude Code**: `CronCreate`/`CronList`/`CronDelete` for scheduled sessions;
  background tasks that re-invoke on completion; `ScheduleWakeup` for self-paced
  loops with a stop condition. Scheduling, mostly — clock-driven, which is the
  thing `CronDisguisedAsTrigger` refuses.
- **Codex**: `cloud-tasks` crate, `wait_for_environment`, `sleep`. Also
  scheduling and waiting.
- **OpenClaw**: runs persistently and reacts to messages. Reactive, not
  self-directed.
- **Kimi**: a "swarm supervisor" as the default posture.

**Nobody in the field has a condition-based autonomy layer with a cron refusal
and a terminating-predicate proof.** On this one axis VESPER's design is ahead
of the systems being studied, and it has been sitting unused with a single
trigger registered.

## ADDS TO THE BUILD LIST

- **L11. Join autonomy to the actor.** A fired trigger should be able to reach
  the capability path, under the same ladder — with FREE_TIME as the period, so
  the standing level and the confirmation behaviour differ from an owner-present
  turn.
- **L12. Register real triggers.** Idle + charging + FREE_TIME; an open triage
  item; a failing gate; an unfinished item in the owner's own project list.
- **L13. A self-directed work queue** — VESPER's own ideas/projects, so "advance
  its own stuff" has a referent. `core/tasks.py` and `TriageQueue` are the
  places this belongs.
- **L14. A stop condition that is not a timer** — "nothing to do, or nothing
  necessary now" expressed as predicates, which is exactly what this layer
  already refuses to let be a clock.
