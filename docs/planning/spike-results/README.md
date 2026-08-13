# SPIKE-001 measurement reports

Raw harness output from `tools/spike/profile_node.py`. This directory is under
`docs/planning/`, outside `NORMATIVE_ROOTS`, and nothing here has a path into
`contracts/policy/capability_profiles.toml`. Promotion is a separate, deliberate act.

| File | Condition | Transcribable? |
|---|---|---|
| `SPIKE-001-3.1-small-unattended.json` | tier `small`, 3 x 10 min, idle/unattended | **yes** — full protocol, `--launch-command` recorded |
| `DESKTOP-F73BBDB-20260812T224722.json` | early harness shakedown | **NO** — `--quick` |
| `DESKTOP-F73BBDB-20260813T010244.json` | early harness shakedown | **NO** — `--quick` |

**The two `--quick` files are kept as a record of what was run, not as data.** Each
carries `QUICK_MODE_WARNING` in its own body. Their figures must never be copied
into `capability_profiles.toml`, quoted as a measurement, or compared against the
full-protocol run — a `--quick` pass skips the sustained window entirely, so its
number describes a cold machine over seconds, which is the exact error SPIKE-001
3.1 exists to prevent. They were committed alongside the real report by a broad
`git add`; they are labelled here rather than deleted, because erasing what was run
is a worse habit than naming it.

**`SPIKE-001-3.1-small-unattended.json` is one half of 3.1.** The protocol makes the
concurrent-load variant mandatory and its 5 forbids reporting the idle figure in
place of the concurrent one. The router uses the concurrent figure. Until that run
exists, 3.1 is incomplete and pass criterion 2 is not closed.
