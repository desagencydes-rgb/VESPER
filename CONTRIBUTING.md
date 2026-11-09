# Contributing to VESPER

VESPER is open for anyone to pick up. The original author has stepped back, so
there is no roadmap owner waiting to approve a direction. The corpus is the
roadmap: [`VESPER_OPEN_WORK.md`](VESPER_OPEN_WORK.md) lists what is broken,
unfinished and unsolved, and [`docs/INSTALL.md`](docs/INSTALL.md) gets you
running.

This file is short on purpose. It covers the handful of rules that are
**mechanically enforced**, meaning a gate goes red, and the traps that cost
earlier contributors whole sessions.

## Before you reason, read

| File | Why |
|---|---|
| [`VESPER_OPEN_WORK.md`](VESPER_OPEN_WORK.md) | What is broken, unfinished, unsolved, and the standing constraints |
| [`MEMORY.md`](MEMORY.md) | Measured numbers **with provenance**, mistakes already made, doctrine |
| [`VESPER_ENGINEERING_STATUS.md`](VESPER_ENGINEERING_STATUS.md) | Where the build stands |
| [`docs/spikes/INDEX.toml`](docs/spikes/INDEX.toml) | The status authority for every spike |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | Working instructions for AI coding agents. Humans should read them too |

Most questions about hardware, models or throughput that look like judgement
calls have already been measured. Look in `MEMORY.md` §1 before answering one
from general knowledge.

## The first trap: `python3` is not enough

Every gate needs Python ≥ 3.11 (`tomllib`). macOS ships 3.9. On 3.9 the gates
fail with `ModuleNotFoundError: No module named 'tomllib'` **and `checks.py`
still exits 0**. A contributor who trusts the exit code records a pass that
never happened. Use an explicit interpreter:

```sh
python3.13 tools/ci/checks.py all        # every check
python3.13 tools/traceability_lint.py
python3.13 tools/reference_lint.py
python3.13 tools/ci/self_test.py         # red-then-green; see the warning below
```

`tools/` and `verification/` are **stdlib only**. Do not add a dependency there.

## Rules that are enforced

- **`INV-HW-1`: no product names in routing, resource or policy paths.** Write
  the profile, not the device: `availability_class = foreground_only`, not "the
  phone". Enforced by `CI-007`.
- **`INV-HW-2`: throughput is measured at enrollment, never declared.** `UNKNOWN`
  means `UNAVAILABLE`, and the system fails closed.
- **`INV-COORD-4`: wall clock never orders or supersedes; only HLC does.**
- **`INV-PLACE-3`: VESPER is not pinned to a machine.** A new node wins
  placement on merit.
- **A check lands with an executed red run, or it does not land.** Every check
  in `verification/ci/CHECKS.toml` declares a `self_test`. `tools/ci/self_test.py`
  *executes* it, mutating the code to the violation and watching the check go
  red. Adding a check means adding its case there.
- **A negative control that passes is a defect, not a relief.** It means the
  test cannot detect the fault it was written for.

## Traps worth knowing before your first commit

- **`self_test.py` mutates the live working tree.** Run it alone and never
  commit while it runs. A sabotage mutation was once committed as real code.
  Never `pkill` it mid-run either: that skips the restore.
- **About a third of the tracked files use CRLF line endings.** Measure with
  `file` before rewriting one; do not normalise them in passing.
- **Never casually run `docs/design/source/final.py`.** It regenerates
  `modes.json`, which every surface reads, from reconstructed inputs.
- **TCC grants are keyed to the app's signature.** An ad-hoc-signed rebuild can
  wipe Microphone, Screen Recording and Speech. Do the grant trip after your last
  build (see `docs/INSTALL.md`).
- **A TCC prompt must come from the app, launched with `open -n`**, never from a
  shell. macOS attributes the request to the *responsible process*, which is
  your terminal.
- **An instrument's self-report is not evidence.** A launcher returning 0 is
  not a running process, and `say` exiting 0 is not a sound in the room. Read the
  world back after acting.

## Commits

- **Subjects state the finding, not the file touched.** "The stall record
  rounded the number it is judged by", not "fix autonomy.py".
- **Comments carry the reason a thing is the way it is**, especially when the
  obvious alternative is wrong. The corpus is full of "this looked right and
  was not". That is deliberate; keep it going.
- Finding-shaped subjects contain backticks and `>`. Write the message to a
  file and use `git commit -F` so the shell does not run them.
- Stage by path. Do not `git add -A`.

## Where help is most valuable

See [`docs/SHOWROOM_BRIEF.md`](docs/SHOWROOM_BRIEF.md) §4 for the current
inventory. In short:

1. **Latency.** A spoken question takes about 30 s to answer and the runtime
   1–2 minutes to start. Measured breakdown and starting points:
   `VESPER_OPEN_WORK.md` §2.5.
2. **Windows and Linux surfaces.** The Python core runs there and its
   acceptance suites were run there. The visual shell (island, home, showcase)
   exists only for macOS. The decided frontend for everything except the island
   is Tauri.
3. **The non-blocking voice**: `core/speech.Voice` is written and reached by
   nothing (`VESPER_OPEN_WORK.md` §2.3, §3.1).
4. **Model-driven composition.** The showcase's scenes are still scripted by
   hand (§3.4).
5. **The 18 checks still `impl = "PENDING"`** in `verification/ci/CHECKS.toml`.
   That count is a better measure of real coverage than the check total.
