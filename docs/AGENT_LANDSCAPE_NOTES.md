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
