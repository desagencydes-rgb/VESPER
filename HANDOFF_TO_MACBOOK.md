# Moving the work to the MacBook — what the repo does not carry

**Written 2026-08-19 00:10, on node 1, for the first session that opens this
repo on the M1 Pro.**

The repo is the handoff. `MEMORY.md` holds the hardware, the measured numbers
and the doctrine; `VESPER_ENGINEERING_STATUS.md` holds the position;
`PLAN_2026-08-18.md` and `SESSION_2026-08-18.md` hold the last day's intent and
what actually happened to it. **Read `MEMORY.md` before reasoning about
hardware, models or doctrine** — most of what looks like a judgement call has
already been measured, and the answer is in there with its provenance.

This file covers only what a `git clone` does **not** bring, and what to do
first. It is deliberately short and it will go stale; when it contradicts a
command's output, the command wins.

---

## 0. SUPERSEDED 2026-08-19 — two of the three now travel

Section 1 below described three things a clone does not bring. Two of them have
since been put **inside the repo**, so they arrive with `git clone` and need no
manual copying:

| | Where it is now | What you do |
|---|---|---|
| **Skills** (`graphify`, `browse`) | `.claude/skills/` | **Nothing.** Project-scoped skills load automatically |
| **Memory files** | `docs/session-memory/` | Copy them once into your own memory directory — see that folder's README |
| **The node 2 SSH key** | **NOT in the repo, and never will be** | Move it by hand. See §1b |

**The key stays manual on purpose.** A private key in a git repository is
compromised the moment the repository is cloned, mirrored, or made public, and
it cannot be un-published by deleting it later. No convenience is worth that.

Section 1 is retained below as written, because its reasoning about *why* these
things do not travel is still the thing worth understanding.

## 1. Three things that do not travel

### a. The personal memory directory

Nine memory files live under the *session host's* config directory, not in the
repo:

```
~/.claude/projects/C--Projects-VESPER/memory/
```

They are keyed to the project path, so a clone at a different path on a
different machine starts with **none of them**. They record things the repo
deliberately does not: that `/code-review ultra` cannot run here because the
repo is too big, that browser automation fails on node 1, and the working
preferences this project has converged on.

**Copy that directory across**, or re-derive it and accept the cost. It is the
difference between a session that knows the shape of the work and one that
rediscovers it.

### b. SSH access to node 2 — inbound to the Mac is NOT needed

A first draft of this file asked the owner to enable **Remote Login** on the
MacBook. That was wrong and the owner caught it. The session runs **on** the
MacBook, so it needs no way to SSH *into* it; it reads its own hardware with
`system_profiler` directly. Enable Remote Login only if a *future* task needs
node 1 or node 2 to reach the Mac, and not before — it is an open listening
service on the owner's primary machine and should be bought with a reason.

What the Mac does need is **outbound** access to node 2:

The Kali laptop holds the alarm. Reaching it needs a private key that is not in
the repo and must never be:

```
~/.ssh/vesper_node2          ssh -i ~/.ssh/vesper_node2 csf@192.168.100.102
```

Copy the key pair, `chmod 600` the private half. **ICMP is blocked both ways on
this network — ping proves nothing. Test TCP/22.**

Node 2's sudo password is held by the owner and is written down nowhere in this
repo. Ask for it when a task genuinely needs root; most do not.

### c. The runtime and the models

`C:\Projects\VESPER-runtime\` — five GGUFs (~40 GB) and the llama.cpp build. Not
in the repo and should not be. On the MacBook this will be a different runner
entirely (Metal, not Vulkan), so treat it as a **new node to profile**, not as
something to copy.

> **The trap that nearly cost a day, recorded in `MEMORY.md` §1:** node 1 has
> **two** `llama-server.exe` and only one is comparable — build `b10405`, the
> 9 KB launcher at `VESPER-runtime\llama.cpp\`, not the 14 MB one under
> `C:\Tools`. A figure without its build tag is not a measurement. The same
> discipline applies to whatever runner the MacBook ends up with.

---

## 2. First actions on the MacBook, in order

**1. Enroll it as a node, do not enthrone it.** The owner called it "the main
device". For *sessions* that is right and costs nothing. For **placement** it is
wrong, and the corpus is explicit about why: `A-048`'s two mandatory negative
controls are node-pinned builds, `INV-HW-1` forbids naming a product in a
routing, resource or policy path at all, and the source requirement is that
*"nothing is sitting anywhere ... when hardware is genuinely unavailable — say
only the iPhone is online — it should end up there."* The M1 Pro joins the
fabric as its strongest node and will win most placement decisions on merit.
That is not the same as being the machine VESPER lives on.

**2. Run `SPIKE-001` on it.** `tools/spike/profile_node.py` is stdlib-only for
exactly this reason — it runs unmodified on a new node with no setup step.
`python3 tools/spike/profile_node.py system` first, then `throughput`. Record
the runner's build tag in `--launch-command`, as node 1's reports do.

**The prediction to test, from the bandwidth law:** the M1 Pro is ~200 GB/s and
its memory is **unified**, so it has no VRAM cliff. Node 1's whole performance
story is that cliff — it holds 7.2 GB, and past that it falls from ~200 GB/s to
42 GB/s.

| Model | node 1, measured | M1 Pro, predicted |
|---|---|---|
| Qwen3-8B, 5.0 GB | 45.8 tok/s | ~40 tok/s, comparable |
| Mistral-24B, 14.3 GB | **3.15 tok/s** | ~14 tok/s **if 32 GB** |
| Qwen3-30B-A3B MoE, 18.6 GB | **6.79 tok/s** | much faster if 32 GB — only ~3B params activate |

**RAM size decides which project this is.** 16 GB is an excellent second node;
32 GB makes the two models node 1 effectively cannot run become usable. Unknown
as of writing — **read it yourself, do not ask the owner**:

```sh
system_profiler SPHardwareDataType | egrep -i 'Chip|Memory|Model Identifier|Total Number'
```

The owner's standing preference, stated 2026-08-19: they will move the key pair
and the memory files and grant anything that needs granting; everything else on
that machine is the session's job, **retrieving its specifications included**.

Every figure in the table above is a **prediction and not a measurement**, and
`INV-HW-2` makes an unmeasured profile `UNKNOWN`, which means `UNAVAILABLE`.
Nothing about the M1 Pro enters `capability_profiles.toml` on the strength of a
law that has only been checked on a different machine.

**3. Consider it as the alarm's second rung.** `A-012` requires escalation
across a **device ladder**; today's ladder is depth 1, which is why every firing
so far records `gate_evidence: false`. A MacBook has real speakers and runs
Python, making it the cheapest path to depth 2 — cheaper than the iPhone, which
needs an Apple-reviewed AlarmKit entitlement
(`docs/planning/spike-results/SPIKE-003-ACK-CHANNEL-PARTIAL.md`).

**4. Fill in the macOS row of `SPIKE-003`.** Its nine-cell matrix is untouched
and macOS is one of its four platforms.

---

## 3. Standing facts about the other nodes

**Node 2 (Kali laptop) holds the 09:00 alarm.**

- It is armed for the next morning and guarded by `vesper-alarm-watchdog.timer`,
  which restores the primary within ~2 min if it dies.
- **Powering it off and on is safe.** Measured 2026-08-18: boot → `systemd
  --user` in 12 s → watchdog restored the alarm at +2 min, about five minutes
  *before* the owner logged in graphically. `Linger=yes` is what buys that.
- **Leaving it off overnight means no alarm.** That is the whole condition.
- **Never suspend it.** Suspend does not fail gracefully — it *hangs* with a
  dark screen and needs a held power button. The owner declined masking the
  sleep targets, so this is discipline, not structure. Lid close and idle are
  both verified safe.

**Node 1 (Windows desktop)** — `B1`/`B2` re-runs were in flight when this was
written; results land as `docs/planning/spike-results/SPIKE-001-3.1-v3-*.json`.

---

## 4. The one item worth doing before anything new

**`B4` — the first promotion into `contracts/policy/capability_profiles.toml`.**

That file is **entirely `UNKNOWN`** while measured numbers sit in
`spike-results/`. `INV-HW-2` makes `UNKNOWN` mean `UNAVAILABLE`, which is why
F6's survival set is currently the core and almost nothing else. It is the
single change that makes placement mean more than it does today.

Two constraints on doing it:

- `profile_node.py` **has no path to that file, deliberately** — promotion is a
  separate reviewed act, and `CI-034` guards it.
- Promote node 1's numbers **before** the MacBook joins, so there is a real
  profile to compare a new node against rather than an empty table.

---

## 5. Open, and owned by the owner

| | |
|---|---|
| `OWNER-DECISION-006(c)` | Ruled A on 2026-08-18 — no new ADR ids. Closed |
| Sleep-target masking on node 2 | **Declined.** Do not re-ask |
| lightdm autologin on node 2 | Not done, deliberately — it would remove the laptop's login password. Measured unnecessary: audio reaches a `systemd-run --user` unit with no graphical session |
| `A-008` camera audit | Instrument built and driven; needs the owner's devices. Serve it with `tools/spike/serve_camera_audit.py`, **not** the artifact — an artifact runs in a cross-origin iframe and never receives the camera |
| MacBook RAM | Unknown at time of writing. Decides the two rows above |

---

*Authority order when these disagree: a command's output, then `MEMORY.md`, then
this file. This one is the most likely to be stale — it was written on the way
out the door.*
