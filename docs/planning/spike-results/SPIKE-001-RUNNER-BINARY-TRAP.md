# Two `llama-server.exe` on node 1, and only one of them is comparable

**Recorded 2026-08-18 16:05, before the `B1`/`B2` re-runs, not after.**

## The finding

There are two `llama-server.exe` on node 1 and they are **different builds**.

| Path | Size | `--version` | Backends |
|---|---|---|---|
| `C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe` | 9 KB + 52 DLLs | **`build 10405, commit e79e4bf66`** | Vulkan, RPC, CPU |
| `C:\Tools\llama-cpp\llama-server.exe` | 14 MB | `version 8631 (dae2bf41c)` | Vulkan, RPC, CPU |

`MEMORY.md` §1 records node 1's runner as **`b10405-e79e4bf66`**, and every
published `SPIKE-001` §3.1 figure was measured with it. Its device probe also
matches the recorded hardware exactly:

```
Available devices:
  Vulkan0: AMD Radeon RX 6650 XT (8176 MiB, 7378 MiB free)
```

7378 MiB is the *"7.2 GB usable VRAM, measured"* in `MEMORY.md`. The
`C:\Tools` build is a **different and older** checkpoint (8631 < 10405).

## Why this mattered enough to write down

**`PLAN_2026-08-18` §3 opens with:** *"Verified present: `llama-server.exe` at
`C:\Tools\llama-cpp\`."* That is the wrong binary for these runs.

`B2` exists precisely because *"three published MoE figures came from three
different checkpoints; §3.1 forbids that."* Re-running the tier matrix against
build 8631 to fix a cross-checkpoint comparison would have **introduced a
fourth checkpoint** — and produced a clean-looking table of figures that could
not be compared to the ones they were meant to supersede.

The failure mode is the one this corpus keeps meeting: nothing errors. The
server starts, the model loads, tokens come out, the JSON report is well
formed. The number is simply not comparable to the number beside it, and
nothing in the artifact says so.

## The size is a red herring, and worth saying so

The comparable build is the **9 KB** file. It is a thin launcher against 52
sibling DLLs; the 14 MB file is the more statically linked one. "The bigger
executable is the real one" is the wrong instinct here, and it is the instinct
that would have picked the wrong binary.

## What to use

```
C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe
```

`tools/spike/run_tier_matrix.ps1` already resolves this correctly —
`$RT = 'C:\Projects\VESPER-runtime'`, `$EXE = "$RT\llama.cpp\llama-server.exe"`,
and it pins `$BUILD = 'b10405-e79e4bf66'`. **The script was right and the plan
was wrong.** Prefer the script over any hand-assembled command line.

Any `--launch-command` passed to `tools/spike/profile_node.py` must name that
path, and the resulting report's `launch_command` string must carry the build
tag, as the existing reports do:

```
llama-server.exe -m <model>.gguf -ngl <n> -fa on --cache-type-k q8_0
  --cache-type-v q8_0 -c <ctx> --parallel 1 --host 127.0.0.1 --port 8080
  [build b10405-e79e4bf66]
```

## Standing rule this produces

**A throughput figure without its build tag is not a measurement.** The tag is
already recorded in every existing report; the trap was never a missing field,
it was two binaries and a plan that named the convenient one.
