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
