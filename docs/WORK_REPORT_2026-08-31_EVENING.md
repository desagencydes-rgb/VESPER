# Session report — 2026-08-31, afternoon and evening

Written for the owner, who left mid-session and asked for the work to continue.

---

## What you asked for, and where each item stands

1. **A wake word** — "vesper", "hey vesper", "yo vesper", no buttons. **Built,
   gated, and confirmed acoustically.** Not currently running: see *The one
   thing that needs you* below.
2. **Triple-tap the globe key to start VESPER, without ever starting a second
   copy.** **Built, gated, all three branches measured working.**
3. **"It can't act yet — no capabilities are registered."** **Closed.** VESPER
   holds three real capabilities and used them, in Darija and in English.

---

## 1. The wake word

**The design point.** A microphone that is always open and a room that is always
broadcast are different things, and only the first is acceptable. `en-US` has
on-device recognition on this Mac and "vesper" is an English-shaped word, so the
always-on recogniser is forced on-device and **refuses to open the microphone at
all** if the machine cannot honour that. Nothing leaves until the word is heard.
Only then is a six-second clip captured and sent to the same private transcriber
your Darija speech already uses.

The alternative — streaming to a cloud recogniser and matching the wake word
there — would put every conversation in this room, and every silence in it, on
someone else's machines. `Listener.swift` already refuses that for a single
utterance; doing it continuously is the same mistake at a larger scale.

**Confirmed by playing it into the room**, not by reading a return code: "hey
vesper" spoken aloud woke it, a clip was captured and queued, the runtime drained
it, transcribed Darija at 0.80 confidence and answered. The audio was deleted
from disk afterwards.

**One honest gap.** I first tested by speaking English after the wake word, and
it came back as "موسيقى موسيقى موسيقى". That was my test's fault, not the
system's: the transcriber is pinned to Arabic, which is what fixed the
French-detection bug. Whisper forced into Arabic on English audio hallucinates
exactly like that. **English speech after the wake word will not transcribe
correctly.** Worth a decision later; it does not block anything.

## 2. The globe key, and a bug the earlier test could not have caught

The triple-tap works, and the single-instance guard works — but the version I
confirmed working earlier today was **dead in the state it will normally be in.**

The guard asked "is any process from this bundle running". The wake listener runs
from that same bundle. So with the wake word doing its job and home down, a
triple-tap answered *"already running"* and started nothing.

**The negative control that was supposed to catch this ran with zero processes**,
before the wake listener was launched. It passed, and it could not have failed:
it tested for the absence of the bug in the only state where the bug cannot
occur. Re-run with the listener present, it reproduced on the first try.

Fixing it exposed a second half. `createsNewApplicationInstance = false` means
"activate an existing instance of this bundle" — and the wake listener *is* an
instance of this bundle. With the guard corrected, the launch printed "starting
VESPER" and raised the listener instead. The coarse mechanism had been doing the
single-instance job badly *and* blocking the launch; it only became visible once
the precise one stopped hiding it.

Identity now answers the question twice: a Mach port name that a live home
process holds and that vanishes with it, plus home's own refusal to start when
that name is taken. All three branches measured.

**And nothing started either listener.** The check asserted everything about the
wake listener's behaviour and nothing about it being *launched* — so it stayed
green on a feature that only ever ran because I typed it. "No buttons" is an
autostart requirement. The wake listener now starts inside home; the globe
watcher has its own LaunchAgent, because its job is to start home when home is
down and it cannot live there.

## 3. VESPER can act

Everything needed to act was already built and gated, and none of it was
reachable. The only `shell.run` in this repository lived inside a **test
fixture**. The corpus had already diagnosed this in its own verification report:
*"No subsystem, no decision function, no contract covers endpoint interaction."*
So VESPER could decide perfectly about actions it had no way to take.

**Three capabilities are now real**: `shell.run`, `fs.read`, `fs.write`.

**The standing grant is L2, and that is the whole safety argument.** VESPER may
look at the machine and write inside its own workspace. It has **no** standing
authority over your documents, the contracts, the credentials, or any command
that is not provably read-only. Those are not forbidden — they are refused
*pending an answer*, and the refusal becomes the spoken question you asked for on
your first decision: stop, explain, ask by voice, wait if nobody is there.

The safety therefore does not depend on the proposer being right. A model
proposing `rm -rf ~` produces an L5 request that no standing grant satisfies.

**Measured, end to end:**

| You said | What happened |
|---|---|
| "what files are in this folder" | ran `ls`, answered with the real listing |
| "how much disk space is left" | ran `df`, answered with real figures |
| "chhal men sa3a daba?" | ran `date`, gave the real time |
| "ktebli f workspace/test.txt: salam" | wrote the file, verified it by hash |
| "save a note in documents/plan.txt" | **stopped and asked** — needs permission at L3 |
| "kifash rak?" | not treated as an action at all — answered in Darija |

**The trap worth knowing about.** A-013, the acceptance test for this, only
asserts that `shell.run("ls")` and `shell.run("rm -rf ~")` resolve to different
levels. A classifier can satisfy that completely while admitting `ls; rm -rf ~`
at the lowest level — it begins with an allowlisted verb, and both halves are
honest. Chaining is now checked *before* the verb, destructive forms before the
allowlist, and anything unanalysable is top level. The self-test proves the gap
exists: deleting the destructive check leaves A-013's own assertion **passing**.

---

## Four defects found by testing through the real door

**A path that levelled as VESPER's own scratch space and opened `/etc/passwd`.**
`workspace/../../../../etc/passwd` *begins* with `workspace/`, so the classifier
called it L2 to write and L1 to read — VESPER's own workspace, no question asked
— while the filesystem would have opened the real file. The classifier was
reading a **string** and the implementation was opening a **target**: the exact
split `shell.run` refuses `shell=True` to avoid, arriving through the other door.
It also defeated the one sentence this whole design rests on — that safety does
not depend on the proposer being right — because a traversal argument is
precisely what a wrong or steered proposer produces. Paths are now levelled
after being fully resolved, and anything that ends up outside the root its own
prefix claimed is top level.

**A note that was written, verified, and doomed.** Asked in Darija to save a
note, VESPER understood it, wrote the file, read the bytes back, matched the
hash, and reported success. Every step was correct. The file landed inside
`VESPER.app`, because the bundle carries a *copy* of the runtime — and
`build.sh` deletes that directory on every build. The failure was invisible to
every instrument pointed at it, because the thing that destroys the file is the
build, not the runtime. VESPER's writable space now lives beside its **state**,
not beside its **code**.

**Two checks went green on prose.** A clause refusing pid files matched the
comment explaining why there is no pid file; a clause forbidding bundle-wide
enumeration matched the comment explaining why it was wrong. In a corpus whose
comments record what was tried and why it failed, the sentence describing a
defect reads exactly like the defect. Swift is now stripped of comments before
any assertion is made about it.

**A verifier tested only through the door that returns early.** The write
verifier was probed with a path that does not exist — which returns before the
hash comparison, so replacing that comparison with a constant `True` changed
nothing the check could see.

---

## The one thing that needs you

**Speech recognition is not granted to the current build**, so the wake word is
not listening right now. This is not a bug — macOS keys permissions to the app's
signature, and `build.sh` re-signs on every build, so each build is a new app as
far as the system is concerned. I rebuilt several times tonight.

Run this once, and click **Allow**:

```bash
open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --speech-consent
```

It must be `open -n` — run from a terminal, macOS attributes the request to the
terminal instead of to VESPER. That trap cost time tonight: I polled the status
from a shell and it reported "not determined" while VESPER's own read said
"authorized".

Then confirm it actually came up:

```bash
grep "wake word" ~/Library/Application\ Support/VESPER/island.out | tail -2
```

You want to see **`wake word ON`**. I have never observed that line — the
in-process wake listener is new code and has only ever taken its refusal branch,
because the grant was already dead by the time it was wired in.

For the globe key, Accessibility is a separate grant and dies the same way on
each build. **The watcher itself is installed and running** — it registered its
own LaunchAgent and both jobs are live (`ai.vesper.island` and
`ai.vesper.island.fnwatch`). Its log says exactly what it needs:

> Accessibility permission is needed to watch the globe key. Grant VESPER in
> System Settings › Privacy & Security › Accessibility, then run this again.
> watching the globe key: three taps within 1.2s starts VESPER

So the globe key is one toggle away, not one build away. To check what VESPER
itself sees, without triggering a prompt:

```bash
open -n /Users/macbook/Projects/VESPER/app/VESPER.app --args --fn-status && cat /tmp/vesper-fn-status.txt
```

This is now the third concrete argument for a Developer ID certificate.

---

## State of the gates

- **87 checks pass.** **404 of 405** self-test cases go red under deliberate
  violation and green after restore. The one that does not is named below — it
  is pre-existing and not from tonight's work, and stating "405" here while
  disclosing a hole four lines down would be two claims that cannot both be
  true.
- Traceability and reference lints pass. F0–F6 acceptance pass. Placement and
  fabric stress pass.
- **One known hole, pre-existing and not mine:** `context-control-reaches-selection`
  has a case — "no over-selection under manual control" — that stays **green
  under deliberate violation**. By this corpus's own rule that check is not
  evidence for that property. I left it rather than spend the session's
  remaining time on it; it is worth a look.
- `--fn-fire` is a **test door that ships**. It calls the real launch path,
  because that is the only way to confirm the single-instance guard without
  synthesising a key event — which needs the same grant the watcher is waiting
  on. It is bounded by home's own refusal, and that ordering is now asserted.
