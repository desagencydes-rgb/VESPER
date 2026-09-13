# VESPER — working instructions

Loaded automatically every session. Its job is to stop each session
rediscovering the same things. If a statement here contradicts a command's
output, **the command wins** and this file is stale — fix it.

## Read these before reasoning, not after

| File | What it holds |
|---|---|
| `MEMORY.md` | Hardware, measured numbers **with provenance**, mistakes already made, doctrine. Most of what looks like a judgement call has been measured |
| `VESPER_ENGINEERING_STATUS.md` | Where the build stands |
| `HANDOFF_TO_MACBOOK.md` | What a clone does not bring; per-node setup |
| `docs/spikes/INDEX.toml` | **The status authority for every spike.** The protocol documents' headers follow it, never the reverse (`RF-047`) |

Do **not** answer a hardware, model or throughput question from general
knowledge. It has almost certainly been measured on this fabric, and the answer
with its provenance is in `MEMORY.md` §1.

## The rules that are actually enforced

These are checked mechanically. Violating one turns a gate red rather than
producing an opinion.

- **`INV-HW-1` — no product names in routing, resource or policy paths.**
  Write the profile, never the device: not "the phone" but
  `availability_class = foreground_only`; not "the old handset" but
  `key_storage_class = file_based`. Enforced by `CI-007`, and it has caught
  first-party code.
- **`INV-HW-2` — throughput is measured at enrollment, never declared.**
  `UNKNOWN` means `UNAVAILABLE`, fail-closed. `CI-034` refuses a number while
  `measured = false`.
- **`INV-COORD-4` — wall clock never orders or supersedes. Only HLC does.**
  `CI-005` refuses a sort keyed on a timestamp and a comparison whose *both*
  sides are wall-clock. Asking "has 09:00 arrived" is neither and is fine.
- **`INV-PLACE-3` — VESPER is not pinned to a machine.** `A-048`'s two
  mandatory negative controls are node-pinned builds. A new node joins the
  fabric and wins placement on merit; it does not become the machine VESPER
  lives on.

## How work lands here

**A check lands with an executed red run or it does not land.** `CHECKS.toml`
declares each check's `self_test`; `tools/ci/self_test.py` *executes* it rather
than trusting the declaration. Adding a check means adding its case there and
watching it go red, then green.

**A negative control that passes is a defect, not a relief.** It means the test
cannot detect the fault it was written for.

**An instrument's self-report is not evidence.** `spd-say` exiting 0 is not a
sound in the room; a launcher returning 0 is not a running process; a payload
that rounds the number it is judged by is not an audit record. Re-read the
world after acting.

**Record what was compared.** Rounding is presentation and belongs to whoever
renders it.

## Verification, in the order that fails fastest

**On this Mac, `python3` is 3.9 and every gate below fails on it** with
`ModuleNotFoundError: No module named 'tomllib'` — and `checks.py` still exits
0 while doing it, so a session that trusts the exit code records a pass it never
had. Use `python3.13` (`~/.local/bin/python3.13`). Verified 2026-08-23.

```sh
python3.13 tools/ci/checks.py all       # 186 checks
python3.13 tools/ci/self_test.py        # red-then-green, 934 cases
python3.13 tools/traceability_lint.py
python3.13 tools/reference_lint.py
python3.13 verification/run_f0_acceptance.py   # ... f1 .. f6
python3.13 verification/stress_placement.py    # 160k property assertions
python3.13 verification/stress_fabric.py        # 180k property assertions
```

**EIGHTH DRIFT, 2026-09-06, AND THE FIRST ONE THE GATE CAUGHT RATHER THAN A
READER.** They read 131 and 588 while the commands printed 138 and 645. That is
the whole point of `CI-089` and it is worth saying plainly: for seven
corrections in a row, a human noticed. This time nobody had to. The gap is the
workbench chunk -- `CI-123` (commands card), `CI-124` (explanations),
`CI-125` (the board survives a restart), `CI-126` (a path is not a secret),
`CI-127` (auto mode does not ask and does not overreach), `CI-128` (changes),
`CI-129` (the owner's terminal) -- with 51 self-test cases between them.

**Corrected 2026-08-31, AND THEN GIVEN A GATE.** They read 57 and 223 while
the commands printed 78 and 333. **Seventh drift, and the last one that can
happen quietly:** `CI-089` now reads both figures out of this file and out of
`VESPER_ENGINEERING_STATUS.md` and compares them to what the commands produce,
so a stale number is a red gate rather than something a reader has to notice.

That is the actual fix, and it took seven corrections to see it. Every previous
one was made by a human reading the file; four of the seven were found that way
rather than by anything breaking. A number nobody acts on is a number nobody
re-reads -- so the answer was never a more careful correction, it was to give
the numbers a CONSUMER. Same move `INV-HW-2` makes for throughput: stop
declaring, start measuring. **Sixth drift, and the largest.** Thirteen checks landed overnight in
two groups that are worth telling apart, because they say different things about
where this corpus loses ground.

Seven gate work that was BUILT that night: `CI-085` (cache tiers and
DF-CACHE-ADMIT), `CI-086` (log receipts, so a memory-derived claim can carry
support at all), `CI-087` (the two machine-checkable verification strategies),
`CI-088` (the SR-007 knowledge map), and the three unregistered ones from
earlier in the same session -- arabizi, presence, and context control -- which
run and are held back from the registry until their invariants are ratified.

Six were DECLARED WHEN THE REGISTRY WAS FIRST WRITTEN and never implemented:
`CI-004`, `CI-011`, `CI-012`, `CI-013`, `CI-020`, `CI-033`. Every one guards a
subsystem that has been complete and correct since it was built -- so a
regression in `core/bus.py`, `core/taint.py`, `core/authorize.py`,
`core/capability.py`, `core/evidence.py` or the gateway's cost choke point would
have been caught by nothing at all. **18 of 122 registered checks are still
`impl = "PENDING"`**, and that number is the one worth watching now: it is a
better measure of this corpus's real coverage than the check count is, because
a PENDING entry looks like enforcement in every listing that does not read the
`impl` field. `python3.13 tools/ci/checks.py ci-registry` prints the honest
figure -- **92 of 145 invariants** are named by an implemented, bidirectionally
consistent, red-run, non-vacuous check.

**Corrected 2026-08-30:** they read 47 and 160 while the commands printed 57
and 223 -- the memory system landed overnight and brought ten checks with it
(`CI-074` and `CI-076`..`CI-082`, plus the redactor's check, which runs and is
deliberately unregistered). **Fifth drift of this pair.** Four of the five have
now been found by someone reading the file rather than by the file being wrong
in a way that broke something, which is the whole argument for the rule at the
top of this document: a number nobody acts on is a number nobody re-reads, and
these two are quoted far more often than they are checked.

**Corrected 2026-08-29:** they read 45 and 154 while the commands printed 47
and 160 -- `CI-072` (the mid-hold interruption classifier) and `CI-073` (the
baseline turn record) landed with three self-test cases each. Fourth drift of
this pair; the rule is unchanged and it is this file's opening line.

**Corrected 2026-08-26:** they read 34 and 88 while the commands printed 45 and
154 -- the third time this pair has drifted, and it drifted furthest the time
nobody was watching it. CI-068..CI-071 and three effort cases account for the
gap. The rule is this file's opening line and it keeps being the answer: the
command wins.

**Corrected 2026-08-25:** the two figures above read 31 and 79 while the
commands printed 32 and 80. Nothing depended on them, which is exactly why they
drifted — a number nobody acts on is a number nobody re-reads. They are now the
counts after `CI-059` and `CI-060` landed, and the rule that applies is this
file's own opening line: the command wins.

**Corrected 2026-08-21:** this file said `stress_placement` ran 320k assertions.
The runner's own headline is `20000 random fabrics, 8 properties each = 160,000
assertions`, and no section of its output reaches 320k. `stress_fabric`'s 180k
was right. The wrong number had already travelled: the owner's island UI
reference draws a status column reading "320k assertions", taken from here. A
number repeated without re-reading its source is exactly what `INV-HW-2` exists
to refuse, and this file is not exempt from it.

`--profile release` on the traceability lint is **expected to fail** on **two**
DEPTH errors (`SR-017`, `SR-034`). `SR-016` was raised to `SPECIFIED` on
2026-08-19 when the network fabric landed; `SR-017` depends on its contract and
is next; `SR-034` is held below `SPECIFIED` deliberately and permanently.

## Conventions worth matching

- **Stdlib only** in `tools/` and `verification/`. Python ≥ 3.11 for `tomllib`.
  `profile_node.py` is stdlib-only specifically so it runs unmodified on a new
  node with no setup step.
- **Comments carry the reason a thing is the way it is**, especially when the
  obvious alternative is wrong. The corpus is dense with "this looked right and
  was not" — that is deliberate and worth continuing.
- **Commit subjects state the finding, not the file touched.** "The stall record
  rounded the number it is judged by", not "fix autonomy.py".
- **Promotion into a contract is a separate reviewed act.** `profile_node.py`
  has no write path to `capability_profiles.toml`, deliberately.

## Machine-specific facts that bite

- **Node 1 has two `llama-server.exe` and only one is comparable** — build
  `b10405`, the 9 KB launcher under `VESPER-runtime\llama.cpp\`, not the 14 MB
  one in `C:\Tools`. A figure without its build tag is not a measurement.
- **Node 2 (Kali laptop) holds the 09:00 alarm.** Powering it off and on is
  safe — it restores itself within ~2 min. **Never suspend it**; suspend hangs
  the machine and needs a held power button.
- **ICMP is blocked both ways on this network.** Ping proves nothing. Test
  TCP/22.
- **A TCC prompt must be triggered with `open -n`, never from a shell.** Run
  `app/VESPER.app/Contents/MacOS/VESPER --speech-consent` from a terminal and it
  prints `requesting as: ai.vesper.island` -- correct, and not evidence. TCC
  attributes to the RESPONSIBLE PROCESS, which is the shell: the microphone came
  back "granted" with no dialog because it inherited the terminal's grant, and
  the speech request killed the process with SIGABRT complaining about a usage
  description that was demonstrably present. `Bundle.main.bundleIdentifier`
  cannot detect the difference. Measured 2026-08-30.
- **TCC consent does not survive a rebuild.** Grants for an **ad-hoc-signed**
  app are keyed to its cdhash and `build.sh` re-signs every build, so each build
  is a new app to TCC. Measured 2026-08-30: granted at cdhash `6bd67687...`,
  `notDetermined` at `59b04339...` five builds later. Re-grant with `open -n
  app/VESPER.app --args --speech-consent`; read it without prompting via
  `--speech-status`. This is the second concrete argument for a Developer ID
  certificate, alongside the login-item one `build.sh` already makes.
- **On-device speech recognition** (2026-08-30). On-device
  recognition is available for `en-US` and NOT for `ar-MA`, `ar-SA` or `fr-FR`
  -- those route audio to Apple's servers, which is egress outside
  `ModelGateway` and therefore outside the redactor.
- **This host runs on battery more often than you would assume.** 2026-08-30,
  mid-build: `power_source = battery`, 53%, discharging, no charger attached.
  `core/host_probes.py` reads it; `world.current_host.power_source` carries it.
  Check it before starting anything long rather than after.
- **`/code-review ultra` cannot run on this repo** — too large. Use a
  path-scoped local review and never gate a day on it.

## Efficiency

- Prefer `graphify` for "where does X live / how does Y relate to Z" once
  `graphify-out/` exists. It replaces repeated greps across a corpus this size.
- The acceptance runners are slow (F5 ≈ 15 s, placement stress ≈ 20 s). Run the
  single relevant gate while iterating; run `all` before committing.
- `tools/ci/checks.py <name>` runs one check. `status` and `ci-registry` are
  read-only and fast.
