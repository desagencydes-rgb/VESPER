# Node onboarding — the Kali laptop

**You are a Claude Code session running on the owner's Linux laptop.** This file is your
briefing. Read it fully before doing anything. Written 2026-08-14 from the site-A desktop,
which is node 1.

---

## 0. First moves

```bash
git clone https://github.com/desagencydes-rgb/VESPER.git
cd VESPER
python3 tools/traceability_lint.py && python3 tools/reference_lint.py && python3 tools/ci/checks.py all
```

All three must pass on a fresh clone. If they don't, that is your first finding — report it
and stop, because every later measurement would be taken against a tree that does not match
the one node 1 measured on.

Then read, in this order:

| File | Why |
|---|---|
| `VESPER_ENGINEERING_STATUS.md` | Where the whole project stands. It is the handoff, kept current. |
| `docs/planning/HARDWARE_INVENTORY.md` | Every device, its role, and what is known about it |
| `docs/spikes/INDEX.toml` | The twelve spikes: question, pass criteria, and what happens on failure |
| `docs/planning/spike-results/README.md` | Node 1's measurements and — more useful to you — the mistakes made getting them |

---

## 1. What this machine is for

VESPER is a personal AI system meant to run continuously across the owner's devices. The
site-A desktop (node 1) is the compute machine: an RX 6650 XT with 7.2 GB of usable VRAM,
measured, running llama.cpp on Vulkan. It has one disqualifying property — **it will be in
site-A while the owner is in site B, and VESPER cannot wake it** (SPIKE-010: the Ethernet
run is impossible in that room and the Wi-Fi dongle cannot do Wake-on-LAN).

**You are the candidate for what node 1 cannot be: the always-on control-plane host.**

`SPIKE-001` pass criterion 3 requires at least one node meeting `control_plane_host`,
which needs `trust_zone = Z0` **and** `availability_class ∈ {always_on, usually_on}`. No
enrolled node meets it today. That gap is the fabric's one known structural hole, and this
laptop is the only device that plausibly fills it. Establishing whether it does is your
highest-value work.

---

## 2. Your tasks, in priority order

### 2.1 Close `SPIKE-008` criterion 9 — cheapest, highest value

The owner accepted `ADR-002` (the persistence design) on 2026-08-14 on **seven of nine**
criteria. Criterion 9 — *"all five stores open on every candidate node class"* — was left
open for exactly one reason: only one node was enrolled. You are the second node class.

```bash
python3 tools/spike/validate_persistence.py all --writes 10000 --trials 500 --commits 500 \
  --out docs/planning/spike-results/SPIKE-008-adr002-validation-kali.json
```

Stdlib only, no install, ~10 minutes. Node 1 got: 0 stale writes accepted at 2/4/8 writers,
the mandatory non-compliant control failing (119/167/186 accepted), 500 crash trials with
zero tearing, checkpoint 1.17 ms p95 against a 200 ms budget.

**Do not tune anything to match those numbers.** A different result on different hardware is
a finding, not a failure — and a Linux result that differs from the Windows one is exactly
the kind of thing criterion 9 exists to surface. Report what you get.

Two things worth knowing, because they were bugs in this harness within the last day and the
same shapes will bite you elsewhere:
- The non-compliant control **must fail**. If it passes, the suite is measuring nothing and
  the compliant PASS beside it is worth nothing.
- Crash trials arm on the child having committed rows before the kill. Without that, a kill
  landing during interpreter startup scores as a crash-safety failure that is really a
  harness artefact — a false positive on a blocking criterion.

### 2.2 Profile this machine — `SPIKE-001`

```bash
python3 tools/spike/profile_node.py system      # no server needed
python3 tools/spike/profile_node.py memory
python3 tools/spike/profile_node.py storage --storage-path ~/vesper-runtime
```

For throughput you need llama.cpp and a model. Build llama.cpp for whatever accelerator this
laptop actually has — **check first, do not assume**; if it is CPU-only, that is the finding
and a CPU-only figure is still a real profile. Then:

```bash
llama-server -m <model.gguf> -ngl <N> -fa on --cache-type-k q8_0 --cache-type-v q8_0 \
  -c 2048 --parallel 1 --host 127.0.0.1 --port 8080
python3 tools/spike/profile_node.py throughput --tier small --minutes 10 --runs 3 \
  --launch-command "<that exact line>" --out docs/planning/spike-results/SPIKE-001-3.1-kali-small-idle.json
```

`--launch-command` is not optional. The flags **are** the configuration under test; a
throughput number without them is not reproducible and must never reach
`contracts/policy/capability_profiles.toml`.

Run the concurrent condition too (`--concurrent`). **Report the wall-clock rate, not the
generation rate** — node 1 learned this the hard way: under load the generation rate moved
−0.29% while real throughput moved −11%, because a generation-time metric is structurally
blind to CPU contention.

### 2.3 Answer the availability question honestly

This is judgement, not a script, and it is the one node 1 got wrong. Node 1 built a 7-day
sampler that ran *on the machine being measured* — which cannot observe the machine while
it is off. Do not repeat that.

What is actually needed: **is this laptop plausibly `always_on` or `usually_on`?** It travels
with the owner to site B. It is their working machine. Report what you can establish —
uptime history from `last`, `systemd` suspend/resume logs in the journal, whether it
suspends on lid close — and be explicit about the difference between *what the machine has
done* and *what the owner intends to do with it*. Only the first is a measurement.

---

## 3. Cleanup authorization, and its one limit

**The owner has explicitly authorized you to clean this machine up** — 2026-08-14, in their
words: nothing on it is important, take what you need, prepare and optimize it for VESPER,
and delete files or applications you do not need.

That authorization is real. Use it. This machine is being repurposed as a VESPER node and a
lean machine is the point.

**One limit, and it is not a hedge — it protects the owner from a generalization they made
in good faith.** *"Nothing here is important"* is a statement about their documents. It is
not a statement about the things that would lock them out of their own machine or accounts.

So: **inventory before you delete, and never delete anything you cannot identify.**

Never remove, regardless of the authorization above:
- SSH keys, GPG keys, `~/.ssh/`, `~/.gnupg/`, or any credential, token or password store
- Cloud/CLI auth state — `~/.config/gh`, `~/.aws`, `~/.config/gcloud`, browser profiles
- Network configuration, VPN profiles, Wi-Fi credentials
- Anything under a path you have not read enough of to name

Everything else — caches, old build trees, unused packages, downloads, dormant applications
— is fair game. Write what you removed and what you reclaimed into a report, and send the
list to the owner rather than only the total. A number is not a record.

---

## 4. How to work here

The house style is unusual and it is the reason this corpus is worth anything. It is not
decoration; ignore it and your work will be rejected by the same gates that rejected node 1's.

- **Measure, never declare.** `INV-HW-2`: `sustained_tokens_per_sec` is measured at
  enrollment, never declared. `CI-034` fails `capability_profiles.toml` if a figure appears
  while `measured = false`. Unmeasured is treated as *unavailable*, never as available.
- **A figure you cannot measure is `null` with a reason.** Never a guess, never a value
  carried from another machine, never a vendor number.
- **Record median and spread**, not just the median. Node 1 published a −12.2% finding that
  its own spread contradicted, and only caught it because someone asked why one row was
  three times noisier than the others.
- **A test that cannot fail is not a test.** Where a protocol names a negative control, run
  it, and if it passes, your suite is broken — not confirmed.
- **Never write to `contracts/`.** All spike output goes to
  `docs/planning/spike-results/`, which is outside `NORMATIVE_ROOTS`. Promotion into a
  contract is a separate, reviewed act.
- **Commit messages state what was found, not what was done.** Read `git log` for the shape.
  Include what a later reader would otherwise have to rediscover — especially your own
  mistakes.
- Branch: `plan/site-a-desktop-and-cross-site`. Push freely; branch protection is live on
  `main` only.

---

## 5. Things node 1 got wrong, so you do not repeat them

Listed because every one cost real time and none was visible until something specific was
checked.

1. **A 512-token cap in the harness** made the tier argument inert — `small` and `standard`
   produced byte-identical requests and differed only by which model was loaded. Three
   tiers, two distinct measurements.
2. **A flat 600 s request timeout** on a tier defined by being slow. An 8192-token request
   at ~10 tok/s needs ~775 s, so two runs in three died and the harness still emitted a
   median over the survivor.
3. **Checkpoints that fired on request returns, not on the clock.** At the `strong` tier one
   request outlasted the whole 10-minute window, so published figures landed on whichever
   checkpoint they happened to cross — one was the minute-1 value that the protocol names
   and explicitly forbids.
4. **A 7-day availability window that could not observe its own subject.** See §2.3.
5. **Ratifying by ID.** The owner was asked to accept `ADR-002` and `ADR-007` with only the
   IDs named, and had to ask what they were. Lay out what a record says — what it decides,
   what the alternatives were, what accepting it commits to — *before* asking for a call on
   it. This applies to you.

---

## 6. Report back

Write findings into `docs/planning/spike-results/` and commit. If you conclude this machine
**cannot** be the always-on control-plane host, that is a finding of equal value to the
opposite — `INV-TRUST-2` forbids designing continuity-critical capability onto a node that
cannot stay up, so a clear "no" protects the design. The fabric would then need another
always-on member, and the repaired desktop is the standing candidate.
