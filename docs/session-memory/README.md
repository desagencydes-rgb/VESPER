# Session memory, staged so it travels

**These are not repo documentation.** They are the previous session's personal
memory files, kept here only so a clone carries them to a new machine.

## Why they need staging at all

Personal memory lives under the *session host's* config directory, keyed to the
project path:

```
~/.claude/projects/<path-derived-slug>/memory/
```

The slug is derived from where the repo sits, so it differs on every machine —
`C--Projects-VESPER` on the Windows node is not what macOS will produce. A clone
therefore starts with none of them, and a session that assumes otherwise loses
the working preferences this project converged on.

## What a new session should do, once

Copy every `.md` file here **except this README** into your own memory
directory, then read them. You know where yours is; nobody else does.

```sh
# from the repo root, after finding your own memory path
cp docs/session-memory/*.md "$YOUR_MEMORY_DIR"/
rm "$YOUR_MEMORY_DIR"/README.md
```

`MEMORY.md` in that set is the **index** — one line per memory. It is not the
repo's own `MEMORY.md` at the root, which is a different and much larger file.

## Keeping them honest

These are a **snapshot**, and they go stale the moment a session learns
something new. The live copy is whatever sits in the active memory directory.
When they disagree, the live copy wins.

Re-stage them here only when moving to another machine. Do not treat this
directory as the place memories are maintained.
