# VESPER — TONIGHT'S RELEASE PLAN, 2026-09-13

**Written ~18:10 by the Opus 5 session that did the orientation.** The owner is
switching Claude accounts tonight and that chat will not be reachable afterwards,
so **this file is the state.** Read it once, top to bottom, before touching
anything. It is written to be sufficient on its own, because a Fable session
re-deriving this context from the corpus is the single most expensive thing that
can happen tonight.

- **The track is still `docs/design/HOME-WORKBENCH.md`** (the owner's working
  agreement, 2026-09-07). This file sequences tonight across models and carries
  the **ledger (§9)** that every session appends to.
- Every rule in `CLAUDE.md` applies. If this file and a command disagree, the
  command wins and this file gets fixed.
- **Add to this file, never compress it.** That is the owner's standing
  instruction for every handoff artifact.

---

## 0. THE FOUR CONSTRAINTS, IN THE ORDER THEY BIND

| # | constraint | value, and where it came from |
|---|---|---|
| 1 | **Battery** | `pmset -g batt` at 17:58: 26%, "2:46 remaining". **Re-read at 18:19: 22%, discharging, "1:53 remaining", still no charger. The Mac stops around 20:12**, before the acceptance drive and the microphone, and sooner under build load. **Charger first, before any work.** |
| 2 | **Deadline** | Sunset **19:48** (local time), computed for 2026-09-13. The owner stretched it: **hard stop 21:00.** |
| 3 | **Subscription usage** | This account (Sonnet 5, Opus 5) is near its limit. It is used **first**. |
| 4 | **$100 of credits** | The other account (Fable). Used when the subscription runs out, **or at the 18:50 tripwire** (§4, D5). If the credits end, **Opus 5** continues from the ledger. |

**§4's timeline assumes the charger is in. If it is not, the order inverts.** Only
the acceptance drive and the microphone reading need both a live machine and a live
owner. `self_test` needs neither, and can be recorded as `STALE` (`CI-089` accepts
that word). So, without a charger:

1. Freeze as soon as F1 is done. Do F2 only if it fits.
2. Run R1 (the build), then R4 (the grant trip), then R5 (the acceptance drive),
   then R6 (the microphone).
3. Run R2's gates, then R3's `self_test`, **only if power remains.** Never spend
   the last 40 minutes of battery on a test suite before the owner has spoken into
   the microphone.
4. Commit and append a ledger row after **every** step, because the machine may
   stop mid-sequence. The final `git bundle` goes before the battery drops below
   10%.

---

## 1. WHERE IT STANDS: READ BY COMMAND 17:47–17:58, NOT RECALLED

**Repository.** `feat/macos-host-profile` at `91c3ca9`, tree clean. **38 commits
exist only on this Mac** (not on GitHub). The branch is 457 commits ahead of
`main`. A local backup was made and verified at 17:58:
`~/VESPER-backups/vesper-20260913-175811-91c3ca9.bundle` (`git bundle verify`:
okay, 25 refs).

**Gates.**
- `checks.py ci-registry`, run 17:48: PASS. ENFORCED TODAY 92/145 invariants;
  18/122 check IDs PENDING; **78 runnable checks are in no registry entry**.
- From `VESPER_ENGINEERING_STATUS.md` (not re-run by this session): `checks.py all`
  186/186 on 2026-09-13, and **`self_test.py` STALE**. Its last full run was 900/900
  on 2026-09-12, and the re-run was killed by a restart.

**The running app (17:51).**
- Home (`--home --on-empty-desktop --mode Home --chrome`) with its `python3.13`
  runtime child, plus `--fn-watch`, `--wake`, and `vesper_arm.py --run` (running
  as `python3.13`).
- **`ai.vesper.island.agenda`'s last exit is 78.** `MEMORY` names 78 (EX_CONFIG)
  as the code to care about. `agenda.out` last wrote at 02:14.

**The bundle.**
- `codesign -dv` reports `Signature=adhoc` and `TeamIdentifier=not set`.
- The runtime interpreter is `~/.local/bin/python3.13`, which resolves to uv
  CPython 3.13.15, **outside the bundle**.
- `place.toml` pins the project root to this repo's path.

**Found tonight, and in no document yet:** `island.err` holds **16
`FileNotFoundError`s renaming `heard.offset.<n>.tmp` to `heard.offset`**, reported
as "pump error (continuing)". The file was last written at 03:37. The cause is two
writers racing on one offset file.

**Branches.**
- `codex/menus-v2` (worktree `/Users/macbook/VESPER-codex-menus`) holds **2
  commits not in HEAD**. They are the expandable-menu proposal, still waiting for
  the owner to look at it (D2).
- `worktree-agent-a97bd11c4db1816e3` (under `.claude/worktrees/`) is fully
  contained in HEAD and clean.
- `backup/pre-afternoon-2026-09-01` and `backup/pre-overnight-2026-09-01` also
  exist.

### The build order (`HOME-WORKBENCH.md` §10, read with §48)

| state | steps |
|---|---|
| ✅ done | 2, 3, 4, 6, 8, 10, 11, 12, 13, 14, 15b, 15c, 16, 16a, 19a, 20, 21, 23, 24, 25, 26; the menus (§9k); the model rows (§9t); the flag bar's three kinds of trouble (§20) |
| done, but the gate is unregistered (§48) | 1, 5, 7, 9 |
| 🟡 partial | **15/15a:** close-and-reopen placement is owed and rung 3 has never executed. **15d:** move works; resize and close are refused by measurement (owner deferred them, §37.1). **17:** the verbs that CHANGE an app are not built. **18:** Notes sharing and lock/unlock are owed. **19:** UI acts are built, but only the refusals are proved (the acts need Accessibility + Screen Recording). |
| **open** | **22 microphone.** The instrument is committed (`91c3ca9`) and has never been read with the owner speaking. |
| specified, not built | 27 camera · 28 J3 node · 29 messaging and calling · 30 memory stress |
| last, by the owner | 31 phone app |

### Open findings outside the table

| finding | source | blocks tonight? |
|---|---|---|
| §26.2: "i am on the keyboard now" was answered `work.` | HOME-WORKBENCH §26.2 | should fix (A4) |
| §26.3: one failure was told twice | §26.3 | should fix (A5) |
| §26.8: narration says "moving to a local model" when there is no local model, repeats it per retry, and never reads the interruption budget's RATE | §26.8 | should fix (F2) |
| §41: pointing VESPER at the real project was recorded as **the owner's call**. Commit `5f95c1b`, "The project root is told, not derived", landed the same day. Confirm what it changed and that the owner approved it | §41, `5f95c1b` | **confirm before release** (F1) |
| §36: the drift gate compares `core/*.py` only (read at `tools/ci/checks.py` 22507–22540), not the documents the surfaces read | §36 | no. The final build copies fresh documents; the gate is for next time (A2) |
| the `heard.offset` rename race | `island.err`, tonight | no (A3) |
| the redactor turns camelCase identifiers in diffs into `[REDACTED:high_entropy_token]` | `HANDOFF_2026-09-07.md`; never recorded as fixed; `core/redact.py` has no camelCase handling | no (A6) |
| §40: can screen recording see a window off the showing Desktop? | §40, a measurement never made | no (Q8) |
| §41 shape 2: a path-bearing answer should name its directory | §41 | no (Q9) |
| §44/§45 residue: the memory graph has **0 edges** (nothing calls `relate()`), and what a turn retrieved is **unobservable** | §44, §45 | no (F3) |
| `repair.attempted`: 610,931 in a rotated segment, 0 live, never diagnosed | `HANDOFF_2026-09-05.md` §6 | no (Q17) |

---

## 2. WHAT "PRODUCTION" MEANS TONIGHT, AND WHAT IT CANNOT MEAN

**Release 1, by 21:00, includes:**
- everything built through step 26;
- the user-facing defects above either fixed or named;
- **one** final build, with the grants given back after it;
- the owner driving every capability once in the running app;
- the gates green on the committed tree;
- the documents true, the repo clean, and a fresh local backup.

The microphone is measured last, as the owner ordered.

**Not production tonight: steps 27–31. None of it is dropped (§8).** Each needs
something that no amount of model time replaces:
- a camera model's cost measured on the node that runs it (`INV-HW-2`: unmeasured
  means unavailable);
- a device enrolled (the J3, the webcam);
- a spike that has not started (the SPIKE-004 rig readings, SPIKE-005 for calling,
  SPIKE-007/014 for the phone);
- or a token only the owner can create (Telegram).

Shipping any of them unmeasured is exactly what this corpus's first invariant
refuses.

---

## 3. MODELS, EFFORT, AND MONEY

| model | $ per million tokens, in · out | tonight it does | effort |
|---|---|---|---|
| **Sonnet 5** | 2 · 10 | checks that edit nothing, hygiene, documents, diagnosis | medium |
| **Opus 5** | 5 · 25 | code with its red-run gate, the build, the finishing sequence | high (xhigh when writing a new check) |
| **Fable 5.1** (take 5.1 if offered: same price as 5.0, but cache reads cost $0.25 instead of 5.0's usual 0.1×) | 10 · 50 | the **FABLE-ONLY** list (§6), then whatever finishing work is left | **xhigh** on FABLE-ONLY, **high** otherwise, **never max** |

Set both the model **and** the effort in the app's model menu before the first
message of a session.

**"FABLE-ONLY" does not mean Opus cannot do it.** It means these are the items
where a stronger model most changes the outcome. The evidence is in this tree.
Last night's session wrote five corrections of itself (§40, §44, §45, §46, §47),
and four of them had concluded an **absence from a partial read**:
- a registry read for cameras;
- a registry read for the J3;
- an event query with a row cap;
- a six-rung ladder read as one rung.

The FABLE-ONLY items are where that error is most likely and costs the most.

### The arithmetic (rough; check the balance at every checkpoint)

- **Output dominates the bill.** Fable thinks on every turn, and output costs
  $50 per million tokens.
- **Reading context that is already cached is nearly free** ($0.25 per million
  on 5.1).
- **Every new token in context costs more:** a tool result or a file read is
  written to the cache at **2× the input price** on a 1-hour cache, which is
  $20 per million on Fable.
- So a Fable turn costs roughly **$0.15–0.35**, and **$100 is roughly 300–500
  turns at high on 5.1**, fewer at xhigh or on 5.0.
- Tonight's Fable work (F1, F2, part of the finishing) is estimated at **$25–40**,
  which leaves room after 21:00.

### Rules that save both the usage limit and the credits

1. **One session at a time on this repo.** No parallel sessions and no
   subagents: §9o records a session sweeping another agent's work into its own
   commits.
2. **Never pour large output into context.**
   - Pipe every gate through `| tail -20`.
   - Run `grep -n` first, then Read with an offset.
   - **Never Read `HOME-WORKBENCH.md` whole** (5,188 lines, about 290 KB).
   - `island.out` is 14 MB: use `tail` only.
3. **Stay in one long session** rather than restarting, because a restart
   re-writes the whole prefix at 2×. Start a new session only when the model or
   the account changes.
4. **Commit each item green, then append a ledger row (§9).** An interrupted
   session then loses nothing.
5. **With less than about $15 of credits left, start nothing new.** Finish or
   cleanly abandon the item in hand (tree clean, ledger says exactly where it
   stopped), and hand off to Opus.
6. **VESPER's own model calls can also spend money.** Its `claude-sub` and
   `claude-advisor` rungs run the `claude` CLI under their own config directories:
   `~/.config/vesper/claude-vesper`, and the one `VESPER_CLAUDE_ADVISOR_CONFIG_DIR`
   names. If either is logged into the **credits** account, testing VESPER spends
   the same $100. **A1 checks this before the switch.**

---

## 4. THE TIMELINE

| clock | who | what |
|---|---|---|
| now | **owner** | **plug in the charger**, then answer D1–D5 (§5) in one message |
| 18:15 | new subscription session: Sonnet 5, medium | **A1** preflight |
| 18:25 | switch that session to Opus 5, high | **A4** (§26.2), then diagnose **A5** (§26.3) |
| **18:50** | **TRIPWIRE** | If the subscription has not run out, **switch to Fable anyway** (D5). F1 and F2 cost the same credits whenever they run, and after 18:50 they no longer fit before the freeze. |
| 18:50–19:40 | Fable, xhigh | **F1** day-one audit, then **F2** narration; then P1 items (A2, A3, A6) only if time remains |
| **19:40** | active session | **CODE FREEZE**: commit, **R1** the one build, **R2** the gates |
| 19:55 | active session | **R3**: the full `self_test` starts (about 50–70 min) |
| 19:55–20:05 | **owner** | **R4** grant trip (§11) |
| 20:05–20:35 | **owner** + session | **R5** acceptance drive (§11) |
| 20:35–20:50 | **owner** | **R6** microphone (§12), last as ordered |
| 20:50–21:00 | active session | **R7** wrap-up; **R3** finishes around 20:45–21:05 |
| after 21:00 | per §8 | the queue |

**If the subscription runs out early,** Fable simply starts earlier and works
further down the same order.

**If something at R2 is red,** fix or revert that one item. Never retry until it
goes green (§9i).

---

## 5. DECISIONS ONLY THE OWNER CAN MAKE: ANSWER D1–D5 NOW

Each one says what it is, what happens if it is decided wrong, and what it costs
you.

**D1: Push to GitHub tonight?**
- **What:** 38 commits, plus tonight's, live only on this Mac. Your standing rule
  (2026-08-30) is to back up locally and push only when you say so, and then
  **the feature branch only, never `main`, never forced**.
- **If wrong:** a disk failure loses everything since the last push, because the
  backup bundle is on the same disk.
- **Costs you:** one word.
- **Default if unanswered:** no push.

**D2: The expandable-menu proposal (`codex/menus-v2`).**
- **What:** a second agent's version of the menu's contents, never built into
  the app. Open `docs/planning/expandable-menu-review.html` inside
  `/Users/macbook/VESPER-codex-menus` and pick one:
  - **yes:** merged before the freeze;
  - **no:** deleted after 21:00;
  - **later:** left as it is.
- **If wrong:** a menu you don't like ships, or one you liked waits.
- **Costs you:** about 2 minutes.
- **Default:** later.

**D3: Ratify the unregistered checks.**
- **What:** 78 checks run and pass but name no rule, so they count toward no
  coverage figure. You approved ratifying them twice (for 23 of them, 2026-09-05)
  and were unhappy about the delay.
- **Yes means:** the rule text is written and the checks are registered after
  21:00. VESPER's behaviour does not change; the coverage numbers do.
- **Costs you:** a yes or a no.
- **Default:** yes, after 21:00.

**D4: Narration wording (F2 needs this).**
- **What:** VESPER says *"moving to a local model"* when there is no local model
  to move to, and says it again on every retry. The wording lives in
  `contracts/policy/narration.toml`, a file VESPER may never change on its own,
  so **you approve the exact lines.**
- **Approving in principle now means:** Fable shows you the diff during F2 and
  waits for your yes.
- **Costs you:** one look at a diff.

**D5: The 18:50 tripwire.**
- **What:** switch to Fable at 18:50 even if this account still has usage left?
- **If no:** Opus does F1 and F2 at xhigh. That is cheaper, and more likely to
  repeat last night's partial-read mistakes.
- **Default:** yes.

**Later, not tonight** (each one is in §8):
- the CI-013 security question (F4 writes you a five-line brief);
- an Arabic-capable voice (Q16);
- the Telegram bot token (Q14);
- merging to `main` (Q15);
- OWNER-DECISION-006, the ADR-001/012 authority question, and INV-HOME-8.

---

## 6. FABLE-ONLY: CREDITS, TOP-DOWN

### F1: The day-one audit of what the owner RUNS · xhigh · about 25 min

**What.** Find what breaks the first time the owner uses the released app, by
reading the **running system**, not the repo:
- the exit codes from `launchctl list | grep vesper`;
- the `tail` of `~/Library/Application Support/VESPER/island.err` and
  `island.out` (never the whole file);
- the shape of `home.json`;
- the event store, **with no row caps** (§45);
- `/tmp/vesper-grants.txt`, once R4 has run.

**Also.** Confirm what commit `5f95c1b` changed about where VESPER's commands run
(§41), and whether the owner approved it. §41 recorded it as a containment
decision and the owner's call. If it was not approved, put it to the owner before
the freeze, in plain words.

**Must not.**
- Write to `home.json` or anything else the runtime reads. §46: *an instrument
  that writes is not an observer.*
- Call anything ABSENT without first asking what the thing doing the looking can
  see (§47).

**Done when.** A findings table is appended under §9. Each finding is either a
release blocker, fixed now with a gate, or a known issue in §10 with its cause.

**Time-box.** 25 minutes, then stop and list what is left.

### F2: §26.8, the narration · xhigh · about 25 min · needs D4

Two defects on one path:

1. **The false destination.** The descent sentence says "a local model" on a
   node that has no local rung. The phrasing itself is `INV-HW-1`-correct;
   `narration.toml`'s own header says *"The user hears a capability, never an
   inventory"*. **The fact is what's wrong:** the destination clause must describe
   the rung that was actually chosen.
2. **The repetition.** Narration fires on every non-ok `gateway.attempt`,
   including each retry of a single request. `narration.py` reads only
   `speak_when` and never `max_contacts_per_hour` or `max_cost_per_hour` from
   `contracts/policy/interruption_budget.toml`. A declared limit of two contacts
   an hour sits unread.

**Governed surface.** The templates change only through review: show the owner
the diff (D4) and wait. `CI-007` scans that file, so no product names.

**Done when:**
- a burst of retries narrates **once** (red run: the per-attempt build speaks N
  times);
- no node without a local rung ever says "local model" (red run);
- the rate is actually read (red run);
- A5's finding is folded in, if it has the same cause.

### F3: Memory residue (§44/§45) · xhigh · about 30 min · after 21:00 unless time remains

1. Nothing calls `relate()`, and the graph holds **0 edges**. Either call it
   where an extraction yields a relation, **or** remove the graph and say so.
   Removal is the owner's call.
2. Make L1 retrieval **observable.** Publish what a turn retrieved as ids and
   counts, never content. `map-navigates-and-never-carries-content`,
   `sensors-never-reach-a-model` and the redactor all bind here.

After this, step 30's stress harness (Q1) can test the right property. §44 says
to stress after this, not before.

### F4: The CI-013 brief · high · about 10 min · after 21:00

Five plain lines for the owner. The issue: an L4 grant on a capability that does
not declare owner confirmation is **not spent by use** (see the "One security
question is open" paragraph in `VESPER_ENGINEERING_STATUS.md`). Say what it is,
what happens if it is left, and what each answer costs. The owner must choose
before VESPER is production for real.

### F5: The sign-off · high · about 10 min · at R7

Write §10's *verified / not verified* lists from **ledger evidence only**. Nothing
recalled, and nothing inferred from a green check that constructs its own
subject.

---

## 7. ANY MODEL: SUBSCRIPTION FIRST; OPUS INHERITS WHAT FABLE DOES NOT REACH

### Before the freeze

**A1: Preflight** · Sonnet · medium · 10 min
- `pmset -g batt | tail -1` must say `AC Power`. If it doesn't, tell the owner
  again.
- Find which accounts VESPER's `claude` rungs are logged into (§3, rule 6) and
  write a ledger row. If one of them is the credits account, **tell the owner
  before anyone switches**.
- **Is `self_test` safe to run in a separate worktree?** Run
  `grep -n "/Users/macbook" tools/ci/self_test.py tools/ci/checks.py | head`.
  - Any absolute repo path means **no**, because it would mutate the main tree.
  - A worktree also holds only tracked files, so a case that needs an ignored file
    can fail there without being a regression.
  - R3 depends on this answer: write it in the ledger.
- Find why `ai.vesper.island.agenda` exited 78: run
  `launchctl print gui/$(id -u)/ai.vesper.island.agenda | grep -i -E "last exit|state"`
  and read the tail of `agenda.err`. A revoked grant is fixed by R4; any other
  cause is a finding for Opus.

**A4: §26.2, `work.`** · Opus · high · about 20 min

The suspicion (not yet a finding) is the current mode's name leaking into the
answer path; the turn proposed no action. Read that turn's events **without a row
cap**, fix it, and add a gate whose red run reproduces the one-word reply.

**A5: §26.3, told twice** · Opus · high · about 15 min

Find out which of these it is:
- the reply is appended by the actor and again by the answerer; or
- one failure is described once per retry rung (the action log showed
  `groq-strong — rate_limited` followed by a descent).

If it is per-rung narration, **hand it to F2** rather than fixing it twice.

### P1: before the freeze only if time remains; otherwise first after 21:00

**A2: §36, the drift gate** · Opus · high · about 20 min

Widen `the-shipped-runtime-can-reach-what-it-needs` from `core/*.py` to
**everything `build.sh` copies, derived from `build.sh`'s own copy lines**. Never
write a second list: a second list is what drifted eight times and got `CI-089`
built. Red run: change a shipped document in the repo only, and the gate goes red.

**A3: The `heard.offset` race** · Opus · high · about 15 min

Give each writer its own unique temp name, or keep a single writer. Add a gate in
which two concurrent writers never raise.

**A6: The redactor vs camelCase** · Opus · high · about 15 min

First confirm it still reproduces. Fix it without widening what counts as
not-a-credential: `redactor-precedes-every-provider` and the changes-card gate
must stay green.

**Counts.** Any check added, or given a new self-test case, changes the counts
that `CLAUDE.md` and `VESPER_ENGINEERING_STATUS.md` quote. Update both in the
**same commit**, or `CI-089` turns red. A new check runs **unregistered** by
default; registering it is D3's business.

### The finishing sequence, R1 to R8: whichever model is active

**R1: The ONE build, at the freeze commit**

Run `app/island-macos/build.sh 2>&1 | tail -25`, then:
- `python3.13 tools/ci/checks.py the-shipped-runtime-can-reach-what-it-needs | tail -5`
  must be green.
- `launchctl list | grep vesper`: note anything at 78. R4 may fix it; recheck
  afterwards.
- If the home is not up, launch it with
  `open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --home --on-empty-desktop --mode Home --chrome`.
  - **Never a bare `open -n`:** it skips the empty-Desktop guard.
  - **Never the binary straight from a shell:** TCC would attribute its
    permissions to Terminal, and every grant test after that would be about
    Terminal.
- If VESPER has vanished, run
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.vesper.island.plist`.
- Killing `VESPER.app` does not stop its Python child, so check for an orphaned
  runtime.

**R2: The gates, on the committed tree** (after R1, so the drift gate can pass)

Run each of these through `| tail`:
- `checks.py all`
- `traceability_lint.py` and `reference_lint.py`
- `run_f0_acceptance.py` through `run_f6_acceptance.py`
- `stress_placement.py` and `stress_fabric.py`

If anything is red, fix or revert that item.

**R3: The full `self_test`, on the freeze commit**
- **If A1 said the worktree is safe:** run
  `git worktree add /Users/macbook/Projects/VESPER-selftest <freeze-sha>`, then
  from inside that directory
  `nohup ~/.local/bin/python3.13 tools/ci/self_test.py > ~/VESPER-selftest.log 2>&1 &`.
  The main tree stays free for R7's commits.
- **If not:** run it the same way in the main tree, and **commit nothing until
  its completion line appears.** A sabotage mutation was committed on 2026-09-10.
- Poll with `tail -3 ~/VESPER-selftest.log`.
  - **Never** use `pgrep -f self_test.py`: it matches its own waiter.
  - **Never** kill the run: the restore is skipped.
- It may touch `~/Library/Application Support/VESPER` while the owner is testing.
  Anything odd in R5 is checked against the log's timestamps **before** anyone
  calls it a defect.
- If it cannot finish by 21:00, the status row says **`STALE`** (`CI-089` accepts
  that word), and the result is recorded when it lands.

**R4: The owner's grant trip** (§11), then read `/tmp/vesper-grants.txt`.

**R5: The owner's acceptance drive** (§11). A failure becomes a ledger row and a
§10 known issue, **not a hot-fix rebuild**, because a rebuild costs another grant
trip.

**R6: Microphone, step 22** (§12). Last, by the owner's order.

**R7: Wrap-up**
- **Status doc.** `VESPER_ENGINEERING_STATUS.md`'s header (dated 2026-08-31) and
  its "Next actions" section are stale: they still say A-029 is in flight and that
  engineering has run out of work. Point them here. `reference_lint.py` scans that
  file and `README.md`, so every path they name must exist.
- **Workbench.** Update the `HOME-WORKBENCH.md` §10 rows for anything finished
  tonight.
- **Hygiene, named paths only.**
  - Re-check that `git log HEAD..worktree-agent-a97bd11c4db1816e3` is empty and
    that worktree's status is clean. Then run
    `git worktree remove .claude/worktrees/agent-a97bd11c4db1816e3` and
    `git branch -d worktree-agent-a97bd11c4db1816e3` (`-d` refuses if the branch
    is unmerged).
  - `.layoutcheck_bd.html` is tracked, at the root. Run
    `git grep -n layoutcheck_bd` first, and remove it only if nothing names it.
  - **Not tonight:** moving the root handoff, plan and report files (they are
    cited across the corpus), `output/` (the owner's blueprint PDF), the backup
    branches, `codex/menus-v2` (D2), or anything in `~/VESPER-backups`.
- **Stale auto-memory notes.**
  - `vesper-can-act-now` says the interlock is wired to nothing, but
    `tools/ops/vesper_runtime.py` imports it now. Verify before rewriting.
  - `checks-run-unregistered-pending-ratification` says ten; there are 78.
  - `vesper-memory-system-is-built` is superseded by §44/§45.
- **Finish.** Put the F5 sign-off into §10. Make a fresh backup with
  `git bundle create ~/VESPER-backups/vesper-<date>-<sha>.bundle --all` and check
  it with `git bundle verify`. Push only if D1 said yes.

**R8: The login test** (§38.1; the owner's order: last; optional tonight)

Do this only after R7 is committed and bundled, because a restart ends every
session and VESPER. Restart the Mac, then confirm VESPER comes back on its own.

---

## 8. AFTER 21:00: THE QUEUE (nothing here is dropped)

| # | item | model · effort | needs from the owner |
|---|---|---|---|
| Q1 | **F3** memory residue, then **step 30** stress: property-based like `stress_placement.py`; re-drive every earlier memory defect **against the bundle**. A stress run that cannot make memory fail indicts the harness | Fable xhigh → Opus xhigh | — |
| Q2 | **F4** CI-013 brief, then the owner's decision | Fable high | a decision |
| Q3 | Ratification (D3): first the three new invariants and four fold-ins in `docs/planning/UNRATIFIED_CHECKS_2026-09-03.md` §Recommendation, then the rest. Each needs an SR home or `TR-067` fails | Opus high | D3 |
| Q4 | A2, A3, A6, plus A5 if F2 did not absorb it | Opus high | — |
| Q5 | **Everything runs as VESPER from the bundle** (owner requirement, 2026-09-01): the runtime and the arm show as `python3.13` and run from outside the bundle. Try bundling the uv CPython under VESPER's name (verify it relocates on this Mac), and move `--arm` into a Swift mode. **The runtime must never mint its own enable token** | Opus xhigh; Fable reviews the arm/minter boundary | — |
| Q6 | Steps 15/15a: close-and-reopen placement and rung 3 (`drive_rung3.py` reports UNTESTED until it runs). Needs VESPER's Desktop showing, plus Accessibility | Opus high | about 10 min at the Mac |
| Q7 | Step 17: the verbs that CHANGE an application. They land with the grant trip that measures them (`verified_local`, `execution_class`) | Opus xhigh | a grant trip |
| Q8 | §40: can screen recording capture a window off the showing Desktop? A measurement | Opus high | Screen Recording granted |
| Q9 | §41 shape 2: every path-bearing answer names its directory (check `55b533f`/`5f95c1b` first) | Opus medium | — |
| Q10 | Step 18: Notes sharing (CloudKit) and lock/unlock. **A note password must never reach a bus payload, a checkpoint or a log receipt** | Fable xhigh (design) → Opus | whether you want lock/unlock at all |
| Q11 | Step 21's research STAGE layout (§7.1: subject right, canvas left, face dispersed). Check whether step 25 already covers it | Sonnet medium → Opus | — |
| Q12 | **Step 27, camera:** enroll this Mac's webcam with `profile_node.py`; measure a recognition model's cost on the node before choosing one (§38.3 is an expectation, not a reading). The design is `docs/design/VISION-IDENTITY.md`; **do not re-derive it** | Fable xhigh (plan and measurement design) → Opus | the webcam, about 10 min |
| Q13 | **Step 28, the J3:** enroll it; take the SPIKE-004 readings (brightness, viewing angle, sustained output without throttling, legibility at distance). Its microphone only captures and streams to the Mac, rarely, switched on from the main menu's remote surfaces (§37.3). Recognition in ar-MA or fr-FR is egress to Apple's servers, outside the redactor | Opus high; Fable for the SPIKE-004 analysis | the J3 and the rig |
| Q14 | **Step 29, messaging:** Telegram first (your 2026-09-05 decision). It needs a bot **you** create, with its token stored as `TELEGRAM_BOT_TOKEN` in `~/.config/vesper/secrets.env` (absent tonight). Outbox before effect (`INV-ACT-6`). Then WhatsApp keep-alive, iMessage/FaceTime on your account, and SIM calls through the J3. **Calling waits for SPIKE-005: a call VESPER places must never be mistakable for you** | Fable xhigh (design) → Opus | the bot token |
| Q15 | Merge to `main`: 457+ commits. Branch protection needs your review, and this Mac has no `gh`, so use a compare URL with the body on the clipboard. First confirm `git log HEAD..feat/f6-network-fabric` is empty | Sonnet medium | your review on GitHub |
| Q16 | Voice: `darija_voice_id` is "Daniel – Steady Broadcaster" (`contracts/policy/voice.toml`), and the 2026-09-05 handoff says an Arabic-capable voice is still to be chosen, along with the voice model from the three samples, if not already done | Sonnet low | your pick |
| Q17 | `repair.attempted` (610,931 in a rotated segment, 0 live): diagnose and record | Sonnet medium | — |
| Q18 | **Self-signed certificate: not as currently written.** `build.sh`'s signing comment and §9h record that it makes launchd refuse the login item (`OS_REASON_CODESIGNING`); §37.2 and §38.2 missed that. The one unmeasured variant is a file-based LaunchAgent under a self-signed identity | Opus high | whether surviving grants is worth that test |
| Q19 | **Step 31, the phone app.** Last, by your order: a web surface served by the Mac that gives full management of the MacBook (§37.1, §43); SPIKE-007 and SPIKE-014 | Opus xhigh | — |
| Q20 | Governance, unchanged: OWNER-DECISION-006 (a) and (c); the ADR-001/012 authority question; INV-HOME-8; the open questions in `MEMORY.md` §5 | — | decisions |
| Q21 | Gates that need hardware or elapsed time, unchanged: A-029 (24 h), A-031, A-020 (latency chain, needs the phone node), SPIKE-001's remaining sections on node 1 (never on this Mac), the alarm runbook validated at night. `--profile release` failing on SR-017/SR-034 is deliberate | — | hardware, time |
| Q22 | The permission-mode control the owner asked for "later" (2026-09-05). Settings is read-only by design (§25), so ask where a mode switch belongs before building one | Sonnet low (ask) → Opus | an answer |

---

## 9. LEDGER: APPEND A ROW PER ITEM; NEVER EDIT A ROW

| time | model · effort | item | commit | evidence | state |
|---|---|---|---|---|---|
| 17:58 | Opus 5 · max | local backup | — | `vesper-20260913-175811-91c3ca9.bundle`; `git bundle verify` okay, 25 refs | ✅ |
| ~18:10 | Opus 5 · max | this plan, the `CLAUDE.md` pointer, `HOME-WORKBENCH.md` §49 | the commit that adds this file | `documented-counts-match-commands` and `reference_lint.py`, run before the commit | ✅ |
| 18:19 | Opus 5 · max | plan committed | `64fb89b` | `the-projects-dashboard-is-what-the-owner-asked-for` PASS; documented counts PASS (7 figures); reference lint PASS (190 files) | ✅ |
| 18:19 | — | battery re-read | — | `pmset`: 22%, discharging, "1:53 remaining", so about 20:12 unplugged; §0 corrected | ⚠️ |
| ~18:25 | owner | charger | — | **The owner plugs in at 20%.** §4's timeline stands; §0's no-charger order is only the fallback | ✅ decided |
| ~18:25 | Opus 5 · max | A1, worktree question only | the commit that adds this row | `grep -rn "/Users/macbook/Projects/VESPER" --include='*.py' verification core tools`: the only hits are two fixture strings in `tools/ci/checks.py` (lines 13978 and 13981). `self_test.py:51` and `checks.py:32` both derive `REPO` from `__file__`. Positive control: a grep for `REPO` in `tools/ci` found 2 files. **So R3 may run in a worktree.** Caveats still apply: a worktree lacks ignored files, and test cases share `~/Library/Application Support/VESPER` with the live app. The first attempt printed a false 0, because zsh expanded the unquoted `*.py` and grep never ran | ✅ |
| — | — | A1, the rest | — | still owed by the Sonnet session: which accounts VESPER's `claude` rungs use; why `.agenda` exited 78; that `pmset` shows AC power | open |

### F1 findings

*(Fable appends here.)*

---

## 10. RELEASE NOTES: FILL AT R7

### Verified tonight

*(F5 fills this from the ledger.)*

### Not verified tonight

*(F5 fills this from the ledger.)*

### Known limits, already measured or decided, and true as shipped

- **Ad-hoc signed.** Every build revokes every grant except Apple Events. The
  owner declined the paid certificate (§37.2).
- **The runtime is `~/.local/bin/python3.13`, outside the bundle,** and it shows
  as `python3.13` in Activity Monitor (Q5). The bundle points at this repo's path
  through `place.toml`, so moving the repo breaks it.
- **Accessibility reaches only the showing Desktop.** A window elsewhere can be
  moved (by the window server) but not resized or closed (§22; deferred by the
  owner, §37.1). Another application's window cannot be moved to a different
  Desktop (§40).
- **macOS has no general unsaved-work signal,** so the rebuild rung refuses
  document apps.
- **Speech recognition is on-device for `en-US` only.** `ar-MA`, `ar-SA` and
  `fr-FR` go to Apple's servers, which is egress outside the redactor.
- **Remote speech:** ElevenLabs key 1 is spent, and the ladder advances through
  keys 2–6 (§47). Free tiers are quota-bound (Gemini allows 20 requests a day per
  model).
- **A-029 and A-031 have never run.** Spike status lives in
  `docs/spikes/INDEX.toml`.

---

## 11. OWNER GUIDE: THE GRANT TRIP AND THE ACCEPTANCE DRIVE

**Do this only after the final build (R1).** Every build takes these grants away
again.

### The grant trip (about 5 minutes)

1. Open **System Settings → Privacy & Security → Accessibility** and add VESPER.
   If it is already listed, remove it and add it back.
2. In **Screen & System Audio Recording**, add VESPER.
3. In **Microphone**, turn VESPER on.
4. In **Calendars** (and **Reminders**, if VESPER is listed there), turn VESPER on.
5. In Terminal, run the command below. It is safe from Terminal because `open -n`
   makes VESPER itself the one asking. Click **Allow**.

   ```
   open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --speech-consent
   ```

6. Read everything back. This command asks for nothing:

   ```
   open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --grants --out /tmp/vesper-grants.txt
   ```

   Then tell the session "grants done", and it reads the file.

Apple Events for Notes survives builds, so it is not part of the trip.

### The acceptance drive (about 30 minutes)

Type each one into VESPER's home, one at a time. After each, say "ok" or describe
what happened; the session records it in the ledger.

1. `what windows do i have open`
2. `open a new safari window here`: it must appear on **your** Desktop (step 23).
3. `move the notes window to your desktop`: this takes two turns by design,
   because it lists the windows first.
4. `list my notes`
5. `make me a note called Test with the text hello`. Check that it's in Notes,
   then ask VESPER to remove it.
6. Ask VESPER to switch mode. The wallpaper must change **only on VESPER's
   Desktop**.
7. Ask for something VESPER must refuse. A chip appears on the flag bar; click it
   to see the history with timestamps.
8. Open **settings** from the rail: 34 rows, each with a value or a reason.
9. Open **projects** from the rail: the dashboard, with the build order showing
   every row through step 31.
10. Open **research** from the rail: the room opens. Leave and come back, and it
    must restore.
11. Ask VESPER to press a button in a TextEdit window. This needs steps 1–2 of the
    grant trip.
12. VESPER speaks a reply out loud; then try the wake word.
13. **The stop.** While VESPER is doing something, use its stop. The session looks
    up the exact control in `docs/runbooks/` and the arm agent before asking you.
    The work must stop.
14. **Main menu.** Click each of the 17 icons, and say which ones do nothing or
    open the wrong thing.
15. **Expandable menu.** Open it, and say which items are missing, empty, or not
    important to you. As of 2026-09-08 it had 68 catalogue items, 32 of them with
    live readings. If D2 is yes, check it after that merge.

### Your "not complete" list (written 2026-09-12): where each item is

The drive above now visits every one of these. **For each, say in your own words
what is still missing.** The session writes each answer as a ledger row. Anything
that needs code joins the §8 queue after 21:00, with the model shown here.

**Nothing is built during the drive:** a fix means a rebuild, and a rebuild costs
another grant trip. Items 14 and 15 add about 5 minutes; the rest of the timeline
is unchanged.

| your item | already in the plan | in the drive | after 21:00, if it needs work |
|---|---|---|---|
| Settings | step 20: done, read-only by design, 15 of 34 rows UNAVAILABLE with a reason; Q22 | item 8 | Opus · high |
| Research | step 25 done; Q11 (the research stage layout) | item 10 | Opus · high |
| **Main menu** | **was not in the plan.** The 17 icons were approved on 2026-09-08; whether each one opens something is unverified | **item 14 (new)** | Opus · high |
| Camera | step 27, Q12 | — (not built yet) | Fable xhigh → Opus, as Q12 |
| Voice sensitivity | step 22, §12 (R6) | §12 | as §12 says |
| Modes | step 16 done | item 6 | Opus · high |
| Memory | F3, and Q1 (step 30) | — | Fable xhigh → Opus, as F3/Q1 |
| **Expandable menu** | **only D2 was in the plan, not its contents:** 68 items, 32 with live readings | **item 15 (new)** | Opus · high |
| UI driving + app management | step 19 (the acts need the grants) and step 17 (the app-changing verbs aren't built); Q6, Q7 | item 11 | Opus · xhigh, as Q7 |

---

## 12. MICROPHONE, STEP 22: THE OWNER'S GUIDE (LAST)

**What this measures:** how loud your voice arrives at VESPER, before anyone
changes anything. Your words, 2026-09-07: *"i need to be screaming just so it can
hear me."* A gain chosen before a reading is a guess.

**Before you start:**
- Turn the music off. Otherwise it measures the speakers, not you.
- Sit where you normally sit.
- Use your normal voice.

1. Open **System Settings → Sound → Input.** Note which device is selected and
   where the **Input volume** slider sits. **Don't change anything yet:** the
   as-found reading is the first measurement.
2. Run the command below. As soon as it starts, **read any paragraph aloud for 8
   seconds** at your normal volume.

   ```
   open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --mic-level --seconds 8 --out /tmp/vesper-mic-1.txt
   ```

3. Tell the session **"mic 1 done"**. It reads the file, which says
   `peak … dBFS, mean rms … dBFS, over N buffers`. The instrument's own reference
   (`Listener.swift`) says normal speech at a desk **peaks around −12 to −6 dBFS,
   with mean RMS near −30. A peak below about −35 is genuinely quiet.**
4. **If the file says "no audio buffers arrived at all":** that is not a quiet
   microphone; there is no microphone on that input. Check the selected input
   device and repeat step 2.
5. **If it is quiet and the slider was low:** raise the slider to about
   three-quarters and repeat step 2 with `--out /tmp/vesper-mic-2.txt`. If the
   reading is now normal, **that was the fix, and no code changes.**
6. **If it is quiet with the slider already high:** the session proposes a gain
   **calculated from your measured RMS**, not a constant somebody liked. That is a
   code change, so it needs a build, and a build means another grant trip. Your
   call: tonight, or the next session.
7. **If the level is normal but VESPER still misses you,** the problem is
   recognition, not loudness. The session checks the confidence values, and
   whether the failure is in the **wake word** or in the **dictation**; they fail
   for different reasons.

**Never changes, whatever the reading:** `requiresOnDeviceRecognition = true`.
That line keeps what the microphone hears off Apple's servers.

---

## 13. START PROMPTS: PASTE ONE AS THE FIRST MESSAGE OF EACH NEW SESSION

**Subscription session (set Sonnet 5 · medium first):**

> Read `PLAN_2026-09-13-RELEASE.md` top to bottom, then `CLAUDE.md`. Do A1. Then
> tell me to switch this session to Opus 5 · high, and continue with A4 and A5.
> Commit each item green with named paths and `git commit -F -`, and append a
> ledger row to §9 after each one. Stop at the 18:50 tripwire or when usage runs
> out.

**Fable session (on the credits account):**

> Read `PLAN_2026-09-13-RELEASE.md` top to bottom, especially the money rules in
> §3 and the §9 ledger, then `CLAUDE.md`. Continue from the first item the ledger
> does not show as done: F1, then F2, then P1 items until the 19:40 freeze, then
> R1, R2, R3 … R7 with me. Use xhigh on FABLE-ONLY items and high otherwise.
> Append a ledger row after every item. Below $15 of credits, start nothing new and
> hand off.

**Opus session (if the credits run out):**

> Read `PLAN_2026-09-13-RELEASE.md` and its §9 ledger. Continue from the first
> item not marked done. Any FABLE-ONLY item left undone is yours now: do it at
> xhigh, following its "must not" and "done when" exactly.

---

## 14. ONE SESSION RUNS EVERYTHING: THE STOP-AND-SWITCH PROTOCOL (added ~18:45)

**This section replaces §4's timeline and tripwire, and §13's prompts.**

- **Everything runs on this one account. There is no account switch.** Its
  subscription usage comes first (about half was left at ~18:45), and Fable runs
  on the $100 of credits.
- The owner wants **one session** that does everything and tells them when to
  switch.
- **If the usage limit cuts a reply off mid-item,** the owner switches to Fable ·
  xhigh and types "continue". The session runs `git status` first, then finishes
  or discards the interrupted item using the ledger.

### The rule

At every ⏸ in the table below:

1. Finish and commit the current item, or leave the tree clean and say where it
   stopped.
2. Append the ledger row (§9).
3. End the reply with **exactly one line**, in one of these two forms:
   - `⏸ SWITCH → <model> · <effort>, then type "continue"`
   - `⏸ YOUR TURN → <the one thing to do>`
4. Do nothing more until the owner replies.

A model switch only applies from the owner's next message, so never start work
that depends on the switch in the same reply. Keep context lean (§3's rules): a
model switch re-reads the whole conversation uncached.

### The order (the owner's answers applied, ~19:00)

**D5 resolves to b.** The credits are untouched, and Fable's estimated spend for
everything below is $60–80. If the owner reports the balance below $40 at any stop,
the remaining work switches to **a**: Opus 5 · high on usage.

**Estimated finish: about 23:00, not 21:00.** The owner's answers put three pieces of
work before the build (F6, D2 and D3). D7 asks the owner whether that is OK.

| # | model · effort | work | ends with |
|---|---|---|---|
| 0 | **Sonnet 5 · medium** (usage) | Copy the answers table below into the ledger. If D7 is blank: ⏸ YOUR TURN → answer D7. Then A1, the preflight. | ⏸ SWITCH → Fable · xhigh |
| 1 | **Fable · xhigh** (credits) | **F1**, time-boxed to 15 min. **F2**, folding in §26.3: ⏸ YOUR TURN → approve the exact narration sentences. **F6** (D6), VESPER's own place (below). | ⏸ SWITCH → Fable · high |
| 2 | **Fable · high** | **D2**, the menu proposal (below). | — |
| 3 | same | **D3**, ratification (below). ⏸ YOUR TURN → skim the list of new rule sentences, one line each, and say ok. Then register them and run the gates. | — |
| 4 | same | The freeze commit, R1 build, R2 gates, and R3 `self_test` in a worktree (worktree-safe per the ledger). | ⏸ YOUR TURN → the grant trip (§11) |
| 5 | same | Read `/tmp/vesper-grants.txt`. R5: drive items 1–15, one ⏸ YOUR TURN per item, logging each answer. | ⏸ YOUR TURN → the microphone (§12) |
| 6 | same | R6: read each microphone file and say what it means, one ⏸ YOUR TURN per step. | — |
| 7 | same | R7 wrap-up; poll `self_test` to its completion line; F5's sign-off lists; the final `git bundle`; **push `feat/macos-host-profile` to origin (D1): never `main`, never forced.** | ⏸ YOUR TURN → the optional restart test (R8), then done |

**A4, A2, A3, A6, and A5 unless F2 absorbed it,** go to Opus on usage after the
release, with the same protocol.

### F6: VESPER's own place (D6) · Fable · xhigh · before the freeze

The owner, 2026-09-13: *"change to its own place, create then change then verify and
test."*

1. **Read** what `5f95c1b` changed (`place.toml`, `core/capabilities.py`'s `REPO`,
   `shell_run`'s `base_cwd`) and write it in the ledger.
2. **Create** VESPER's own working directory.
   - It must be **outside the owner's repo AND outside the app bundle**, because
     `build.sh` rewrites the bundle and deletes whatever is inside it.
   - It must survive rebuilds.
3. **Change** where VESPER's commands run, and where its relative paths and writes
   land, to that directory.
   - **Keep read-only access** to what the surfaces need from the real project:
     `projects` and `research` read the build order and the spike index, and must
     not go blank.
   - The seatbelt, `host_actions.toml` and the taint seam are unchanged.
4. **Verify and test.** Add a gate whose red run is "a command lands in the owner's
   repo, or in the bundle". Drive it live after R1, as part of drive item 1: ask
   VESPER *"list the files in your project root"* and *"where are you working?"*.

### D2: the menu proposal · Fable · high · before the freeze

The owner: *"verify, if it adds value (features, fixes), verify working then add; if
bullshit, throw."*

Read `git log -p main..codex/menus-v2` (2 commits, 5 files). **Value** means a
feature or fix the build does not already have.

- **If it has value:** cherry-pick it onto the feature branch. Run its test
  (`verification/test_menu_receiver.js`, in the Node DOM stub) plus the menu and
  dashboard checks, and keep it only if they pass. Drive item 15 then shows it to
  the owner.
- **If not:** record why in the ledger, then run
  `git worktree remove /Users/macbook/VESPER-codex-menus` and
  `git branch -D codex/menus-v2`. The 17:58 backup bundle still holds a copy.

### D3: ratification · Fable · high · right before the build

The owner said yes, and placed it right before the final build.

1. Start from `docs/planning/UNRATIFIED_CHECKS_2026-09-03.md` §Recommendation (3 new
   invariants and 4 fold-ins), then write the rest.
2. Each check needs:
   - an invariant sentence in `INVARIANTS.toml`;
   - a `CHECKS.toml` entry naming it;
   - an SR that names the check, or `TR-067` fails.
3. Before writing any of it into the registries, show the owner every new rule as
   one line (⏸ YOUR TURN). Promotion into a contract is a reviewed act, and that list
   is the review.
4. **Done when** `checks.py ci-registry`, `traceability_lint.py` and
   `documented-counts-match-commands` all pass, and the note about runnable checks
   in no registry entry reads 0 (or names each exception and why).

This touches `spec/` and `verification/`, which the bundle does not carry. It changes
the counts, not the build.

**Credits:** the owner watches the balance. If they say it is below $15, finish the
item in hand and stop; the next session resumes from the ledger.

**After tonight:** work the §8 queue with the same protocol, and only when the owner
says to go on.

### The owner's answers (2026-09-13, ~18:55)

| # | question | answer |
|---|---|---|
| D1 | Push tonight's work to GitHub (feature branch only, never `main`)? | **Yes.** At R7, after the final bundle. |
| D2 | The other agent's expandable-menu proposal? | **Verify it.** If it adds value (features, fixes), check that it works, then add it. If not, throw it away. |
| D3 | Write and register the rules for the 78 uncounted checks? | **Yes, right before the final production build and finalization.** |
| D4 | Fix the "moving to a local model" narration? | **Yes.** The owner sees the exact sentences first. |
| D5 | When does Fable take over? | **b if it fits, otherwise a.** It fits (see "The order"). |
| D6 | VESPER working in the real project folder? | **Change it to its own place: create it, change to it, then verify and test.** That is F6. |
| D7 | These answers move the finish to about 23:00. OK, or which of D2 / D3 / F6 moves to after the release? | *(If blank, step 0 asks.)* |
