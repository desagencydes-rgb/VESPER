---
name: vesper-repo-memory-file
description: "VESPER carries its own MEMORY.md at the repo root — read it before reasoning about hardware, models or doctrine"
metadata: 
  node_type: memory
  type: project
  originSessionId: 752ebc2c-4e42-45fd-9e8f-08e69c2177af
  modified: 2026-08-17T00:27:34.364Z
---

**`C:/Projects/VESPER/MEMORY.md`** is the project's own durable memory, created 2026-08-17 at
the owner's request. Read it at the start of any VESPER session — it is faster than
re-deriving, and `VESPER_ENGINEERING_STATUS.md` now points at it.

It holds what is **not** derivable from the code, the specification or the git history:

- **Measured hardware figures with provenance**, including GGUF sizes read off disk.
- **The bandwidth law** — `tokens/sec ≈ memory bandwidth ÷ bytes read per token`. The three
  models that fit in the 7.2 GB VRAM land at 176/186/214 GB/s; the one that does not lands at
  42 GB/s. A **~5× cliff at the VRAM boundary**. This predicts throughput before downloading
  anything, and it is why swap, a bigger pagefile, more `-ngl` and CPU→GPU shifts all fail —
  they act on the wrong side of the division. **MoE with a small active-parameter count is the
  only lever that works on node 1.**
- **Mistakes already made**, including summing VRAM with free RAM, and copying a live SQLite
  store (SPIKE-008 lost 300 committed rows that way — use `con.backup()` or `mode=ro`, and
  always verify the copy's record count).
- **Doctrine** — measured-or-absent, pre-register the reading before the result, VOID vs
  FAILED, a control differs in exactly one variable, "I could not check it" never reads as
  "it passed".
- **Open questions** recorded rather than resolved.

Maintained by appending; wrong entries are corrected in place rather than deleted, because the
correction is usually the useful part. **If it contradicts a command's output, the command
wins** and the file is stale.

Related: [[a029-endurance-run-in-flight]].
