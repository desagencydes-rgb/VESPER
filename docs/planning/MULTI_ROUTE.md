# Multi-route mode — the ladder, the voice, the triage, and the desktop

Status: **PLAN, not built.** Written 2026-08-25 against the owner's brief of the
same day. Every number here is either read off a primary source (cited) or
marked `UNKNOWN` and left fail-closed. Nothing below is measured on this fabric
yet, and `INV-HW-2` applies to this document as much as to a node profile.

Companion to `docs/planning/PROVIDER_SUPPLY.md`, which decided *who may see
what*. This decides *what order they are called in, what happens when one
fails, and who says so out loud*.

---

## 0. Lead: the plan is unblocked except for one thing, and it needs your hands

`~/.config/vesper/secrets.env` holds exactly two credentials today, and they
are the same key twice:

```
GEMINI_API_KEY, GOOGLE_API_KEY
```

`PROVIDER_SUPPLY.md` §3 classifies Google's unpaid tier **`E1-FORBIDDEN`** —
it trains on submitted content and its own terms say not to send anything
confidential. So **VESPER currently has zero credentials it is permitted to
route private work to.** The two providers the whole ladder rests on —
Cloudflare and Groq — have no account yet.

That is ~10 minutes of owner time (§10, step 1) and it gates everything else.
I cannot do it: creating accounts and entering credentials is yours by rule,
not by preference. Everything else in this document I can build without you.

Also absent, and all trivially installable: `tailscale`, `codex`, `ollama`.
Present and usable: `claude`, `/usr/bin/say`, `/usr/bin/afplay`.
`node1:22` is **unreachable right now** — expected, the desktop is off.

---

## 1. What already exists, so we build less than the brief implies

The brief reads as a large new subsystem. Most of its spine is already in the
tree and green. Reading it first changes the build from "write a router" to
"add five things to a router that works".

| Brief asks for | Already there | Where |
|---|---|---|
| Error classification | `TRANSIENT` / `TERMINAL` vocabulary, HTTP status → class map | `core/gateway.py:41`, `routing/http_completion.py:95` |
| Retry timing a human can act on | Server `retry-after` preferred over computed backoff; a hint > 5 s moves on instead of sleeping | `core/gateway.py:_retry_delay_ms` |
| Automatic switching on quota/error | Ordered fallback across providers, per-provider cost re-check | `core/gateway.py:complete` |
| "Never escalate to paid to keep going" | Exhaustion checkpoints and queues; `AllProvidersExhausted` | `core/gateway.py` |
| Route by capability, not by product | Tier selection on **measured** wall-clock throughput | `core/router.py` |
| One choke point nothing bypasses | `INV-COST-3`, `CI-020` | `core/cost.py` |
| Degradation is reported, never silent | `route.degraded` event; ladder incl. a voice rung | `contracts/policy/degradation_ladder.toml` |

**So SR-003 and SR-004 are already partly satisfied.** What the brief adds is
ordering by *quota*, a chain-wide retry budget, a voice, a triage queue, and
three more rungs on the ladder.

### The five real gaps

1. **Provider order is registration order, not quota order.** The gateway takes
   the first matching provider from a list. Nothing knows which has the most
   headroom left. Needs a quota ledger.
2. **No chain-wide retry cap.** `max_attempts_per_provider=2` is per provider,
   so a six-rung ladder can spend 12 attempts. The brief says 10, total.
3. **No voice at all.** `degradation_ladder.toml` has voice rungs and nothing
   implements them; `grep` finds no `say`, `afplay` or speech-synthesis call
   anywhere in `core/`. This is new code, not a wiring job.
4. **No triage queue.** Failures are published to the bus and forgotten. Nothing
   holds an error for later investigation.
5. **The router is text-tier-only.** `TIERS = (draft, small, standard, strong)`
   are *text* capability tiers. Image and audio need their own axis.

---

## 2. The ladder

Order is fixed by the brief and it is a good order — quota-rich and cheap
first, scarce and expensive last.

```
RUNG 1  APIs, biggest remaining quota first    Cloudflare → Groq
RUNG 2  Subscription MCP, one account each     Claude (VESPER's) → Codex
RUNG 3  Local, smallest capable model          MacBook, load-on-demand
RUNG 4  Desktop                                node 1, weekends, if reachable
RUNG 5  Checkpoint + queue + say so            not a failure — see §8
```

**Rung 1 ordering is dynamic and that is the point.** "Biggest quota to
smallest" cannot be a static list, because which provider is biggest changes
through the day as each is spent. It is computed per request from remaining
headroom, normalised to a common unit (§3). Cloudflare leads at the start of
a day (10,000 neurons ≈ 191 reference answers) and can fall behind Groq
(200K tokens ≈ 153 answers) by evening.

**Rung 2 is dedicate-don't-chain, as settled in `PROVIDER_SUPPLY.md` §5.**
Claude account 2 is VESPER's; account 1 is yours. There is **no failover edge
between the two Claude accounts at any level** — that is limit evasion and it
is what gets accounts banned. When VESPER's account is spent the ladder falls
*through* to rung 3, never sideways to yours. Your manual retrigger after
switching accounts is a **new session**, not a failover: you make the call,
VESPER does not.

**Rung 3 respects "don't stress the MacBook."** Smallest capable model,
load-on-demand, unloaded when idle. `SPIKE-015` selected the small tier;
measured 67–69 tok/s at 31 W. It is burst-affordable and continuously
unaffordable, which the router already knows how to express.

**Rung 4 is conditional on reachability, never on the calendar.** A weekend
does not mean the desktop is on. The rung tests TCP, because `MEMORY.md` §1
records that ICMP is blocked both ways on this network and ping proves
nothing.

### Where the 10 retries go

Not 10 per provider — 10 **per request, across the whole ladder**. Spent
adaptively, reusing the rule the gateway already implements:

- Transient error, no server hint → retry this rung once, then descend.
- Server hint ≤ 5 s → sleep and retry this rung. Cheaper than descending.
- Server hint > 5 s → **do not sleep**. Descend now, record how long this rung
  stays unusable, and let it re-enter the order when the clock says so.
- Terminal error → descend immediately, no retry. Zero budget spent on a `401`.

Measured precedent for why the hint wins over a computed backoff: on
2026-08-24 a free tier answered `429` with `retryDelay: 33s` against a limit of
**20 requests per day**. A 500 ms exponential retry there is not patience, it
is a second identical failure and then a third.

---

## 3. The finding that changes the modality design: one ledger, not four

The brief says image, video and music get "their own routing systems". They get
their own **policy**. They must share one **ledger**, and this is not a
preference — it falls out of Cloudflare's pricing.

Workers AI meters everything in one currency, **neurons, 10,000/day, shared
across every modality.** Text, image, speech-to-text and text-to-speech all
draw the same pool. From Cloudflare's published per-model rates:

| Work | Published rate | Cost of one unit | Units/day if it took the whole pool |
|---|---|---|---|
| Text, `gpt-oss-120b` | — | 52.3 neurons/answer | 191 answers |
| Image, `flux-1-schnell` 512² | 4.80/tile + 9.60/step | **43.2** neurons @ 4 steps | **231 images** |
| Image, `flux-1-schnell` 1024² | 4 tiles | 57.6 neurons @ 4 steps | 173 images |
| TTS, MeloTTS | 18.63/audio-min | 18.63 | 536 audio-min |
| STT, Whisper | 41.14/audio-min | 41.14 | 243 audio-min |

**One image costs 0.83 of a text answer.** Four independent modality routers
each believing they hold 10,000 neurons would together authorise 4× the real
budget, and the overspend would land as `429`s on whichever modality asked
last — most likely the interactive one, i.e. you.

So: **`QuotaLedger` is per-provider-account, not per-modality.** Modality
routers are consumers of it, and each carries a *reservation floor* so a batch
image job cannot eat the day's conversation. Suggested opening floors, to be
revised once measured: text 60%, image 25%, audio 15%, all soft — an unused
floor is lent out, a floor is only enforced under contention.

> **The neuron-per-image figure is DERIVED, not measured.** 43.2 is
> `4.80 + 4×9.60` from the published formula at schnell's default 4 steps.
> Secondary write-ups claim "~2,000 images/day", implying ~5 neurons each,
> i.e. the tile cost with the step cost dropped. Someone is wrong and it is
> not resolvable from documents. `INV-HW-2`: this ships as `measured = false`
> and the first real generation reads the actual neuron spend off the
> Cloudflare dashboard before the router is allowed to plan with it.

---

## 4. Modality availability, honestly

Researched today against primary sources. The answer is not uniform and the
gaps are real.

| Modality | Vetted free supply | Verdict |
|---|---|---|
| **Text** | Cloudflare + Groq, both `E1-PRIVATE` permitted | **Full ladder.** ~344 answers/day |
| **Image** | Cloudflare: Flux 1 schnell, Flux 2 dev/klein, SDXL, SDXL-Lightning, Dreamshaper-8-LCM, Leonardo Lucid/Phoenix | **Full ladder, same account, same vetting.** No new privacy review needed |
| **Speech (TTS/STT)** | Cloudflare: MeloTTS, Aura, Whisper, Nova-3 | Available, but see §5 — the *narration* does not use it |
| **Music** | **None.** Workers AI has no music category. ACE-Step 1.5 is Apache-2.0 **open weights**, not a free API | **Local only.** Rung 3/4 only, no rung 1 |
| **Video** | **None found with acceptable terms.** | **Do not build a video router yet** |

**On video, specifically.** The search space is saturated with SEO listicles
promising "free, no credit card". Following them to primary sources gives
trial credits expiring in days, browser-only tiers with no API, watermarked
output, or no published data-usage terms at all. Under the `PROVIDER_SUPPLY.md`
rule — **no published terms means forbidden, fail-closed** — none qualifies for
even public content, let alone `E1-PRIVATE`. The honest move is to build the
modality-router *shape* so a video provider can be added as configuration
later, and register **zero** video providers today. A router with no providers
fails closed and says so; a router pointed at an unvetted endpoint leaks.

**On music.** ACE-Step 1.5 generates a full track in ~20 s on an A100. Node 1's
RX 6650 XT is not an A100 and nothing has measured it there. Music is therefore
**node-1-only, weekend-only, and `UNKNOWN` until measured** — it does not run on
the MacBook, per the standing "don't stress it" instruction.

### Why ChatGPT can make images and the Codex rung cannot

Fair challenge, and the answer is a distinction between a *product* and a
*programmatic surface*, not a claim that OpenAI lacks image models.

ChatGPT-the-product generates images. Your Plus subscription reaches that
through the ChatGPT web app and mobile app **only**. The programmatic surface
Plus gives you is the **Codex CLI**, and Codex is a coding agent: its published
tool surface is code generation, explanation, debugging, refactoring, tests and
docs, plus image **input** for multimodal reading. It *"can't generate images
natively"* — image output is not among its tools. There is no MCP server that
exposes ChatGPT's image generation, because the subscription's image quota is
not exposed programmatically at all.

Three consequences, all load-bearing:

1. **The Plus image quota cannot be reached from a rung.** Not a policy choice
   — there is no interface to call.
2. **Driving the ChatGPT app to get at it is the path closed in
   `PROVIDER_SUPPLY.md` §1**, by OpenAI's own Terms: *"Except as permitted
   through the API, use any automated..."*. That was settled before this brief.
3. **Third-party image MCP servers exist and do not help.** They route to
   *other* paid image APIs behind their own billing. Adding one would not spend
   your Plus allowance; it would open a new paid account with an unvetted
   egress path. Refused on both counts.

OpenAI's image API (`gpt-image-1`) is billed separately from Plus and is not
free, so it does not qualify for a free-tier rung either.

**So the rule stands, with a sharper reason than I first gave.** Claude and
Codex appear in the **text ladder only**. The image and music ladders have no
rung 2 at all: rung 1 → rung 3 → rung 4 → checkpoint. Cloudflare's Flux is not
a lesser substitute here — it is the *only* free image supply that is both
programmatically reachable and vetted for `E1-PRIVATE`.

---

## 5. The voice — templated, local, model-free

The brief is explicit: what VESPER says during failure is **not produced by a
model**. Three reasons this is correct beyond the aesthetic one:

1. The thing that failed is the model layer. Asking a model to narrate its own
   unavailability is a dependency loop that is broken exactly when needed.
2. A generated sentence cannot be tested. A template renders identically every
   time, so `self_test.py` can assert the exact string.
3. It costs nothing and leaves no egress. `/usr/bin/say` is on this machine,
   offline, free, and already used by the alarm stack's design.

### Shape

`contracts/policy/narration.toml` — a **governed surface**, so the runtime may
propose lines and never rewrite its own script. One row per
`(classification, ladder_position)`, each a format string over a closed set of
fields the gateway already has: `provider_class`, `attempt`, `max_attempts`,
`retry_in_seconds`, `next_rung`.

```
rate_limited     → "Rate limited. Retrying in {retry_in_seconds} seconds.
                    Attempt {attempt} of {max_attempts}."
quota_exhausted  → "Daily quota spent on that provider. Moving to {next_rung}."
auth_failed      → "Credentials refused. Moving to {next_rung}, and I've
                    queued that for investigation."
connection_error → "No route to that provider. Moving to {next_rung}."
exhausted_all    → "Every provider is spent. I've checkpointed the task and
                    queued it. Nothing is lost."
```

No product names appear in any line — `INV-HW-1`, and `CI-007` scans for
exactly this. "Moving to the desktop" is a violation; "moving to a local
model" is the profile talking, and is fine.

### The restraint that keeps this from becoming noise

Narration is subject to `contracts/policy/interruption_budget.toml`, whose
lattice is `alarm_safety > active_user_task > ambience > proactive`, with
**preparation explicitly unbudgeted**.

- You are waiting on this request → `active_user_task`. Speak. This is SR-004
  being satisfied, and it is the case the brief is about.
- Autonomous overnight work → `proactive`. **Do not speak per retry.** Log
  every attempt, narrate only the terminal outcome, and only if it needs you.

A system that announces all 10 retries of a 3 a.m. background task has
implemented the letter of SR-004 and violated RB-006 (proportionality). The
budget already arbitrates this; the announcer must ask it rather than
re-deciding.

---

## 6. Error triage — what gets investigated, and what does not

The brief draws the right line: quota errors are classified, routed, and
forgotten. Everything else is held for investigation. The gateway's existing
vocabulary already splits almost exactly along that seam.

| Classification | Triage | Why |
|---|---|---|
| `rate_limited` | **None.** Record, route, continue | A working provider doing its job |
| `quota_exhausted` | **None.** Record window, route, continue | Expected. Investigating "we used what we had" produces nothing |
| `auth_failed` | **Investigate — usually critical** | An expired or revoked key removes a whole rung and will not self-heal |
| `bad_request` | **Investigate — critical** | Almost always our defect. It will recur identically forever |
| `server_error` | Investigate **only if repeated** | One is a blip; a pattern across a window is a real change |
| `connection_error` | Investigate **only if repeated** | Same, plus it may be local network state |
| `no_provider_for_profile` | **Investigate — critical** | A capability was routed to and nothing serves it. Config gap |

**Investigation runs when a model is back up, never during the outage** — the
brief is right and the reason is structural: triage needs a working model, and
during the outage there isn't one. So failures land in a durable
`ErrorTriageQueue` (survives restart, HLC-ordered — `INV-COORD-4`, wall clock
never orders) and drain when a rung reports healthy again.

Each item is graded into exactly one of four, and only the first gets acted on
without you:

- `CRITICAL_NOW` — a rung is down and will stay down. Attempt repair (§7).
- `CRITICAL_DEFERRED` — real, but the workaround holds. Propose, don't act.
- `CAN_WAIT` — degraded, not broken. Batch into the morning report.
- `NO_FIX_NEEDED` — transient, self-resolved. Close with the evidence.

**A grade needs the evidence that produced it.** "Recurring `server_error`" is
not a finding; "9 of 11 attempts to that rung in 40 minutes, all `503`, while
two other rungs succeeded" is. The queue stores attempt records, not
summaries — rounding is presentation and belongs to whoever renders it.

---

## 7. Repair — three tiers, and I want to flag the middle one

The brief asks VESPER to fix things "either by driving my UI, connecting to my
account then perform fixing on the platform, or from code and requests". Two
boundaries already in this repo constrain that, and neither is my invention:

- **`core/selfmod.py` / `INV-SELF-1..7`.** The runtime may **not** write to
  governed paths in the running artifact. It may write the same content to
  `workspace/`, run it against the tests, and file a proposal. A-030.6 requires
  that path to *succeed* — this is the intended way for VESPER to fix itself,
  and it is deliberately not self-application. An L5 grant does not lift it.
- **Credentials and accounts.** Entering passwords or driving a logged-in
  account is not something I'll do autonomously, and a repair path that logs
  into your provider console is one injected error message away from being
  steered. The error text VESPER is reacting to came *from the provider* — it
  is data, not instruction.

So repair lands as three tiers, autonomous only where it is safely reversible:

**Tier 1 — autonomous, in-runtime, non-governed.** No approval, no proposal.
Rotate to a backup credential; re-fetch `/props` after a restart; reduce
context and retry; drop a stale cached model id; mark a rung unusable until a
stated time; re-resolve a hostname. All reversible, all inside the runtime's
own state, none touching a governed surface. **This is where most real
recoveries live** and it is worth building well.

**Tier 2 — patch proposed, not applied.** VESPER writes the fix *and its
failing test* into `workspace/`, runs the gate, and files a proposal with the
red-then-green evidence. You merge in the morning. This satisfies "fix from
code" without letting the runtime edit the thing that governs it.

**Tier 3 — owner guide.** Anything on a provider's web console: billing, key
rotation, plan toggles, the training opt-outs from `PROVIDER_SUPPLY.md` §3.
VESPER produces the exact URL, the exact control, the exact expected state, and
what to check afterward to confirm it took. It does not drive the browser.

**The flag:** UI-driving as an autonomous repair is the one part of the brief
I'd build differently, and the reason is the injection surface, not caution
about capability. If you want it anyway it should be an explicit per-provider
opt-in with a recorded scope — say so and I'll build it that way; it's your
call and I'll implement what you decide.

**When all three fail, the escalation is the deliverable.** Not "I could not
fix it" — a guide with what was tried, what each attempt returned, what it
rules out, the exact remaining steps, and how to verify. That is the brief's
"full detailed guide" and it is worth treating as a first-class artifact.

---

## 8. "So good it never fails and stops" — what that actually buys

Worth being precise, because the literal version is not purchasable and the
achievable version is better than it sounds.

Never *failing* would require the last rung to always succeed. The last rung is
a local model, and "always available" contradicts the standing instruction not
to stress this machine — a model kept permanently resident to guarantee
availability is exactly the continuous cost that instruction refuses.

What is achievable, and what the gateway already implements: **the task never
dies.** When every rung is spent, the request checkpoints, queues, and resumes
in the next permitted period. Nothing is lost, nothing silently downgrades,
nothing escalates to paid to keep the illusion of progress, and you are not
woken for ordinary work.

**So the terminal state is not an error — it is a spoken, recorded deferral.**
That is rung 5, it is a success path, and `AllProvidersExhausted` should stop
reading as a failure in the narration layer even though it is an exception in
the call layer. A system that never stops *working* is real. A system that
never *waits* is a system that spends your money at 3 a.m.

---

## 9. The desktop — reach, wake, login, and the Thursday ritual

Four separate problems. **Two of my answers on 2026-08-25 were wrong and are
corrected here**, both in the direction of the design getting simpler.

### 9a. Reach: Tailscale, and the expiry setting that caused your problem

You said links always need updating after a shutdown. **That is real, it is a
known Tailscale behaviour, and it is not the DNS name.** MagicDNS names and
Tailscale IPs are stable per device and do not change across reboots.

What expires is the **node key**. Tailscale's own docs: *"By default, keys
expire every 180 days"*, after which *"Tailscale marks the device as Needs
Reauthentication ... and the tailscaled daemon disconnects the node from the
tailnet."* A device that has been off for a while comes back up disconnected
and wants a browser login. That presents exactly as "the link stopped working
after a shutdown".

**The fix is one click per device, permanent:** admin console → *Machines* →
the device's row → ⋯ menu → **Disable key expiry**. Tailscale documents this
as the intended setting for *"trusted servers, subnet routers, or remote IoT
devices that are hard to reach"* — which is precisely node 1's situation.

With expiry disabled on both machines, there is nothing to update, ever. No
subdomain, no dynamic DNS, no panel. **Do this at install time, not after the
first failure** — it is the difference between the design working and your
previous experience of it.

> If a device ever *must* keep expiry (it must not, here), the documented
> alternative is an ephemeral auth key so the node re-registers fresh each
> boot. Noted only so the option is on record; we are not using it.

**On Google: still no.** Domains went to Squarespace in 2023; there is no free
subdomain product to evaluate, and the Google inference tier is already
`E1-FORBIDDEN` in `PROVIDER_SUPPLY.md` §3.

### 9b. Wake — CORRECTED. Hibernate, and no BIOS schedule at all

**I was wrong yesterday**, and you were right to push. Two things I got wrong:

**First**, I framed the BIOS RTC alarm as a *schedule* and worried it might
only offer "daily" and force four pointless boots a week. That worry was
misplaced. This project already established the correct model, in
`tools/ops/alarm_wake_linux.py`: the BIOS setting is a one-time **enable**, and
the *time* lives in the hardware RTC register, which software writes. Its own
header records the finding — the RTC alarm *"lives in the hardware clock, not
in the kernel. It survives suspend, power-off, and losing mains power."* So the
schedule is software's to set, arbitrary and changeable, and the BIOS toggle is
just on/off.

**Second**, and this is the one that removes BIOS from the critical path
entirely: **we do not need S5.** Your requirement was "not sleep" — and
**hibernate (S4) is not sleep.** In S4 the machine is powered down, RAM is
written to disk, and draw is essentially identical to a full shutdown. The
difference that matters:

| State | Wake timers / `-WakeToRun` | Needs BIOS |
|---|---|---|
| S3 sleep | ✅ | no |
| **S4 hibernate** | **✅** | **no** |
| S5 full shutdown | ❌ — *"Task Scheduler has no effect"* | yes, RTC alarm or WoL |

So: **hibernate the desktop instead of shutting it down, and the existing code
already works.** `tools/ops/alarm_night.py:195` already builds
`New-ScheduledTaskSettingsSet -WakeToRun` and reads the flag back to confirm it
took. That is the mechanism, already written and already verified on this
machine.

**Consequence: the BIOS photo is no longer blocking.** Enable *Resume by RTC
Alarm* if you are in there anyway — it is a free belt-and-braces for a true S5,
e.g. after a power cut — but the design no longer depends on it and nothing
waits for it.

### 9c. Login — CORRECTED. You do not need to remove it

You asked whether there is a workaround short of deleting the login screen.
**There is, it is the standard one, and it makes the whole two-profile design
unnecessary: Windows services run as SYSTEM at boot, before any user logs in.**

That is exactly how Tailscale itself works, and it generalises. Everything node
1 needs to do for VESPER can run as a service:

| Job | As a service |
|---|---|
| Network reachability | Tailscale service (already the install default) |
| Inference | `llama-server.exe` under a service wrapper |
| Shell access | OpenSSH Server (`sshd`), a built-in Windows service |
| VESPER's node agent | one service, auto-start, delayed |

**With those four running, node 1 is fully usable by VESPER with nobody logged
in and the login screen untouched.** No stored password, no auto-login, no
second profile, no code entry. Your profile stays protected exactly as it is
now, and the machine at your desk behaves normally.

**Why the design you sketched cannot work as described, briefly.** It has a
bootstrap problem: at power-on, before any login, VESPER is not running on that
machine, so there is nothing there to "present proof" and request entry.
Something must run first — and the thing that can run first is a service.
Once you have the service, the login it was going to unlock is redundant.

**And auto-login would cost real security for no gain.** It stores a
recoverable password in LSA and leaves the machine sitting at an unlocked
desktop from the moment it powers on — so anyone who presses the power button
has your session. That also works against `admission_baseline.toml`, which
grades a node on protecting state at rest. Windows additionally has no
mechanism for a third party to attest "I am authorised, here is proof" into an
interactive session; services *are* that mechanism, expressed the supported way.

So: **keep the login screen, run four services.** If you still want auto-login
after reading this, it is your machine and your call — say so and I will write
it up — but I would be recommending against a change that buys nothing.

### 9d. Handoff between local and desktop

Already supported; no new mechanism. Node 1's profiles are `standard`/`strong`,
the MacBook's are `draft`/`small`, and `Router.select` picks on measured
throughput with `exclude` for spent profiles. The only new part is **presence**:
node 1's profiles become routable when it appears and unroutable when it does
not, via `core/enrollment.py`'s `EnrolledNode.routable()` driven by a TCP probe
— never ICMP, which `MEMORY.md` §1 records as blocked both ways here.

### 9e. The Thursday-night ritual

**What it is.** Every Thursday night, before you sleep, VESPER reads the
calendar and the completed-work history, estimates next week's load from what
past weeks actually took, lays out next week's calendar, and from that sets the
desktop's wake schedule. The schedule is therefore **derived from planned work**,
not a fixed weekend guess — if next week has no heavy jobs, the desktop is not
woken at all, which is the outcome that serves goal 1 (host lifetime).

**It must remind you, and the reminder is part of the ritual.** VESPER tells
you Thursday evening not to shut the MacBook, because the ritual runs on this
machine. That reminder is `active_user_task` class in
`interruption_budget.toml`, so it is permitted to speak.

**Lid closed: yes, with one condition — mains power.** A LaunchDaemon runs as
root, pre-login, and survives the lid closing. macOS on **AC power** with the
lid shut will hold a power assertion and stay awake for the run; on **battery**
with the lid shut it sleeps regardless of assertions, and no software setting
overrides that. So the ritual is: `pmset schedule wake` for the slot, a
LaunchDaemon that fires it, and `caffeinate -i` held for the duration.

> **Therefore the Thursday reminder is: leave it plugged in, lid may be shut.**
> That is a better ask than "leave it open", and it is the honest one — telling
> you the lid can be closed on battery would produce a ritual that silently
> does not run.

One `pmset` limit worth recording: only **one** repeating power-on/power-off
pair may exist at a time, stored in
`/Library/Preferences/SystemConfiguration/com.apple.AutoWake.plist`. One pair is
all this needs, but a second feature wanting a repeat later will collide, and
the collision would be silent.

**The ritual is preparation, not interruption**, and
`interruption_budget.toml` says preparation is unbudgeted. So the planning
itself may run as long as it needs; only the reminder and any morning summary
are budgeted.

---

## 10. Your guide

Moved to its own document: **`docs/planning/OWNER_SETUP.md`**. It covers every
account, key, opt-out, install and setting in the order they should be done,
with what each one unblocks. This section previously listed two API keys, which
was an undercount — the permitted set is nine credentials plus two accounts.

---

## 11. Build order for today, once step 1 lands

Ordered so each stage is verifiable before the next depends on it, and so the
things that need your accounts come after the things that don't.

| # | Build | Gate |
|---|---|---|
| 1 | `QuotaLedger` — per-account, cross-modality, persisted, with reservation floors | Unit: two modality consumers cannot together exceed one pool |
| 2 | Quota-ordered provider selection in `ModelGateway` | Red run: registration order ≠ quota order, and quota order wins |
| 3 | Chain-wide 10-attempt budget | Red run: a 6-rung ladder spends 10, not 12 |
| 4 | `narration.toml` + `Announcer`, wired to the interruption budget | `CI-007` clean (no product names); exact-string assertions; silent under `proactive` |
| 5 | Cloudflare + Groq adapters over `routing/http_completion.py` | Live call each; neuron/token spend read back and compared to the derived figures in §3 |
| 6 | `ErrorTriageQueue` — durable, HLC-ordered, quota classes excluded | Red run: a `quota_exhausted` never enters the queue |
| 7 | Triage grader + tier-1 repair executor | Negative control: a grader that grades everything `CRITICAL_NOW` must fail |
| 8 | Image modality router on the shared ledger | One generation, actual neuron cost measured, §3's 43.2 confirmed or corrected |
| 9 | Node-1 presence probe → `routable()` | TCP/22, never ICMP |
| 10 | Wake schedule — hibernate + `-WakeToRun`, existing code | Read the flag back, then a live wake rehearsal |
| 11 | Thursday ritual: LaunchDaemon + `pmset` + `caffeinate` | Lid-shut, on mains, run observed end to end |

Stages 1–4 need **none** of your accounts and I can start on them the moment
you've read this. Stage 5 is where step 1 becomes blocking.

**Realistic scope for "fully working by end of today":** stages 1–8 are
achievable — the whole text and image ladder with voice, quota ordering, the
retry budget, the triage queue and tier-1 repair. Stages 9–11 need node 1
powered on and the services installed, which is your §1 session on that machine.
**The BIOS photo no longer gates anything** (§9b).
Music stays `UNKNOWN` until something measures ACE-Step on that GPU, and video
has no permitted provider to build against — I'd rather say that now than ship
a router pointed at an unvetted endpoint.

---

## 12. What is still UNKNOWN, stated so it is not quietly assumed

- **Neurons per image.** Derived, not measured. §3. First generation settles it.
- **Whether image and text really share one Cloudflare pool.** Strongly implied
  by one published price list in one unit; not yet confirmed by observing both
  decrement the same counter.
- **Groq's per-model token accounting** at the free tier — the 200K/day figure
  is per-model, and how a second model interacts with it is unread.
- ~~Node 1's BIOS RTC granularity.~~ **RESOLVED** — moot. Hibernate (S4)
  supports wake timers natively; BIOS is off the critical path (§9b).
- **ACE-Step throughput on an RX 6650 XT.** No measurement, anywhere, and
  Vulkan-vs-CUDA makes the published A100 figure useless as an estimate.
- **`INV-PRIV-2` still has no enforcement path at the gateway**, carried
  forward unresolved from `PROVIDER_SUPPLY.md` §8. The egress classes in §4
  are policy that nothing at the choke point currently reads. **Multi-route
  makes this worse, not better** — more providers means more egress
  destinations governed by a rule with no enforcement. It should be stage 0
  of the next block of work, and I'd argue for doing it before the ladder
  grows any further.


---

## 13. MEASURED 2026-08-25 — six findings from the first live calls

Every provider below was called for real. These replace or correct planning
assumptions, and three of them change code that was already designed.

**1. `429` does not always mean "exhausted". Sometimes it means "never had any."**
Google's image model answered `RESOURCE_EXHAUSTED` with, in its own quota
detail, **`limit: 0`** — the free tier has no image allowance at all. Same
HTTP status, same classification vocabulary, opposite meaning: an exhausted
quota returns tomorrow, a zero quota never does. **The gateway must read the
`limit` field**, not just the status. Retrying a limit-0 refusal spends the
retry budget forever on something that cannot succeed, and today's classifier
would do exactly that (`rate_limited` is `TRANSIENT`).

**2. A model listing is not model availability.** `GET /v1beta/models` returned
**37 models** supporting `generateContent`. Called directly, `gemini-2.5-flash`,
`gemini-flash-latest`, `gemini-3-flash-preview` and `gemini-3.5-flash` all
returned `404` on these keys. Only `gemini-3.6-flash` answered — the model the
*error message* named, not the listing. **Capability must be probed, never read
off a catalogue.** This is `INV-HW-2` in a form the corpus had not met: the
declaration here is the provider's own index, and it is still a declaration.

**3. `200 OK` with empty content is a silent failure.** Groq at
`max_tokens=16` returned `200`, `finish_reason: length`, `content: ''` —
reasoning consumed the entire budget before any content was emitted. The
gateway records that as `ok` and hands back an empty string. **Needs an
explicit guard:** empty content plus `finish_reason: length` is a failure and
must be retried with a larger budget, not returned.

**4. Reasoning tokens are not in the capacity arithmetic, and they dominate
short answers.** Measured on Groq `gpt-oss-120b`: a reply of `GROQ_OK`
(7 characters) cost **64 completion tokens**, of which ~57 were reasoning.
The reference answer in `PROVIDER_SUPPLY.md` §4 ("1,000 in / 300 out") and the
**153 answers/day** derived from it therefore overstate real capacity by an
unmeasured margin. Both figures are downgraded to ESTIMATED until re-measured
across realistic prompts.

**5. Cloudflare reports its own usage as zero.** A call that demonstrably
worked returned `{'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0,
'neurons': 0}`. **So §3's plan — have the ledger self-calibrate by reading
neuron spend off each response — does not work.** Built as designed, the ledger
would have recorded zero spend forever and concluded the free tier was
infinite. Needs the dashboard or the GraphQL analytics API instead; until then
neuron spend is INFERRED, and the §3 figure of 43.2 neurons/image stays
underived.

**6. The Codex rung has ~6,400 tokens of overhead per call.** `codex exec`
answering `CODEX_OK` — nine characters — reported **6,393 tokens used**. Against
a plan metered in tokens rather than messages, that overhead is the dominant
cost of any short call. **Codex is therefore a poor fit for small frequent
requests** and should be reserved for work large enough to amortise it. This
is a routing rule, not a note: sending trivial tasks there wastes the rung.

### What this changes in the build order

- Stage 2 (quota-ordered selection): must read `limit`, not just status.
- Stage 3 (retry budget): a limit-0 refusal is TERMINAL and must not consume
  the 10-attempt budget.
- Stage 1 (quota ledger): cannot self-calibrate on Cloudflare. Needs a second
  source, and must be honest that spend is inferred until it has one.
- Provider registration: probe capability at enrolment; never trust `/models`.
- Rung 2 ordering: Codex last among subscription rungs for short tasks.

**Landed 2026-08-25, in a cloud session with no credentials.** Stages 2 and 3
are wired into `core/gateway.py` and guarded by `CI-059` and `CI-060`, both
red-run against the fixtures beside this file rather than against a live call.
`build_provider` now carries the model into the ledger's key, and
`CompletionService` passes the routed difficulty to the gateway so the effort
floor reaches the wire instead of stopping at the router.

Three things on this list are **not** done and cannot be done without a key:

- **Stage 1's second source for neuron spend.** The gateway books a reported
  ZERO as unmeasured — the only correct move available from here — but that
  makes spend an honest guess, not a measurement. The dashboard or the GraphQL
  analytics path still has to be read on the owner's machine.
- **Capability probing at enrolment.** `identify` still consults `/models`,
  which finding 2 proves is a declaration. Replacing a listing with a probe
  means making calls.
- **The limit-0 parser is the most perishable line in the tree.** The captured
  refusal carries `limit: 0` **only in the prose of its `message`** — the
  structured `QuotaFailure` block does not contain it — so
  `_quota_limit_from` reads a regex over vendor prose. A rewording removes the
  only signal separating a permanent refusal from a temporary one, and nothing
  goes red when it does; the ladder simply starts retrying a dead rung again.
  That is a live re-measurement, and it is the first thing to re-check.


---

## 14. Effort vs capability — measured, and it corrects my own assumption

The owner's constraint on 2026-08-25: *"make sure they are still capable and
smart, even on hardest tasks, not just minimizes and makes them dumb."*
Correct, and it is the more expensive failure of the two. So it was measured
rather than assumed.

### The trivial case — effort is pure waste

Same prompt, same answer `OK`, gpt-oss-120b:

| reasoning_effort | completion tokens |
|---|---|
| low | 26 |
| medium | 34 |
| *(unset — provider default)* | 64 |
| high | 119 |

**4.6x for an identical answer**, and the provider default sits near the top of
that range. This is the waste worth removing.

### The hard case — and here the assumption was wrong

A problem with a code-computed ground truth (integers 1..1000 divisible by 3 or
5 but not 7: COUNT=401, SUM=200995 — verified in Python, not recalled):

| reasoning_effort | result | completion tokens |
|---|---|---|
| low | **CORRECT** | 691 |
| medium | **CORRECT** | 1,265 |
| high | **CORRECT** | 3,145 |

**Low effort answered the hard problem correctly, for 4.6x fewer tokens than
high.** And note what low spent: **691 tokens here against 26 on the trivial
prompt.** The same setting produced a 26x difference in deliberation.

**So `reasoning_effort` is not a capability cap. It is a deliberation style,
and the model already scales its own thinking to the problem.** The mental
model this file was built on — "low effort means a dumber model" — is not what
the instrument shows.

### What this does and does not license

It does **not** license dropping the floor. Two problems is not an eval set,
and the failure it guards against — a confidently wrong answer on a hard task —
is both expensive and silent. `core/effort.py` keeps the floor as insurance,
priced at a premium the measurements say is small.

It **does** mean the floor is cheaper insurance than expected, and that the
efficiency case does not trade against the capability case nearly as sharply
as assumed. The saving comes almost entirely from **not overpaying on trivial
work**, which is where the 4.6x actually lives.

**Open, and named rather than resolved:** whether low effort holds on problems
harder than these two. That needs a real eval set with verifiable answers, not
anecdotes. Until it exists the floor stands, and `FLOOR` in `core/effort.py`
should not be lowered on the strength of this section.

### A correction worth recording

The first attempt at this used a bat-and-ball variant, and the expected answer
written into the test was **wrong** — the models returned $7.75, the test
called it WRONG, and $7.75 was correct. A test oracle computed in the head
rather than in code produced a false capability regression, which would have
argued for exactly the wrong design change. **The ground truth in the table
above is computed by `python3.13`, and that is the only reason it can be
trusted.**
