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
