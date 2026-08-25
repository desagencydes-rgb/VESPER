# Owner setup — everything that needs your hands, in order

Companion to `docs/planning/MULTI_ROUTE.md`. Written 2026-08-25.

**Total: ~45 minutes**, split into three sessions you can do independently.
Session A is on the MacBook and unblocks my build. Session B is on node 1 and
needs the desktop powered on. Session C is a browser tab's worth of toggles.

**Nothing here needs to be done in one sitting**, and I can start building the
moment **A1** is done — that is the only hard blocker.

Rule throughout: **paste keys into files, never into chat.** I never need to
see a value, only the name and the confirmation that it's there.

---

## Session A — MacBook, ~15 min. Do A1 first; it unblocks everything

### A1. The two workhorse accounts — THE BLOCKER

These two carry the entire text ladder *and* the entire image ladder.
`secrets.env` currently holds only a Google key, which `PROVIDER_SUPPLY.md` §3
classifies `E1-FORBIDDEN`, so **VESPER has nothing it may route private work to
until this is done.**

**Cloudflare** — free account, no card.
1. Sign up at `dash.cloudflare.com`.
2. Copy your **Account ID** from the right-hand sidebar of the dashboard home.
3. *AI → Workers AI → Use REST API* → **Create a Workers AI API Token**.
4. Copy the token immediately; it is shown once.

**Groq** — free account, no card.
1. Sign up at `console.groq.com`.
2. *API Keys* → **Create API Key** → copy it.
3. **Then, before it can serve private work:** *Settings → Data Controls* →
   take the **logging opt-out**. `PROVIDER_SUPPLY.md` §3 makes this a
   precondition for Groq's `E1-PRIVATE` permission, not an optional extra.
   Without it Groq is restricted to public content only.

Append to `~/.config/vesper/secrets.env` (already `0600`):

```
export CLOUDFLARE_ACCOUNT_ID=...
export CLOUDFLARE_API_TOKEN=...
export GROQ_API_KEY=...
```

Then tell me "keys are in". **That is the whole blocker.**

### A2. The other permitted keys — worth doing, not blocking

I asked for two yesterday and that was an undercount. The full permitted set
from `PROVIDER_SUPPLY.md` §4a is nine credentials. These five add real
capacity, and each is independently useful — do as many as you like, in any
order, and skip any that annoy you.

| Provider | Why bother | Sign-up cost | Env var |
|---|---|---|---|
| **NVIDIA NIM** | ~1,000 dev credits, `strong` tier. Egress still **pending** §3 — I will register it public-only until its terms are confirmed in a contract | free, no card | `NVIDIA_NIM_API_KEY` |
| **Ollama Cloud** | Zero retention, zero training, `E1` clean. Quota is unpublished so it is opportunistic-only | free | `OLLAMA_API_KEY` |
| **Mistral** | $10/mo in credits on the free plan | free | `MISTRAL_API_KEY` |
| **OpenRouter** | **Public content only.** Its free endpoints require enabling "may train on inputs" | free | `OPENROUTER_API_KEY` |
| *(Google — already present)* | **Public content only.** Unpaid tier trains on input | — | *(already there)* |

> **Mistral has an opt-out too**, and it defaults the wrong way: *Admin Console
> → Privacy* → opt **out** of training. Until you do, Mistral is public-only
> like OpenRouter. Same shape as Groq's, opposite default from Cloudflare's.

**On the two public-only ones.** They are not second-class — they are a large
free pool for anything with no private content in it: summarising a public
page, drafting boilerplate, classifying a public document. Rule R6 in
`PROVIDER_SUPPLY.md` gates on egress class *before* quota, so VESPER will use
them freely for that work and never for yours.

### A3. Tailscale, MacBook side — ~3 min

**There is no Homebrew on this machine** (checked). Download the macOS package
from `pkgs.tailscale.com/stable/#macos` — the **standalone** build, not the App
Store one, whose sandbox restricts the CLI that VESPER needs.

Sign in (any provider — the account is free, Personal plan). Then, **and this
is the step that fixes your recurring problem**, in `login.tailscale.com` →
*Machines* → this MacBook's row → ⋯ → **Disable key expiry**.

That is the whole cause of "links always need an update after shutdown" (§9a).
Do it at install, not after it bites.

### A4. Confirm the Claude account split — 30 seconds, no keyboard

Tell me **which of your two Claude accounts is VESPER's.** I bind it
statically and build **no failover edge** to yours, at any level. That is not
caution — chaining two accounts to dodge a limit is what gets accounts banned,
and dedicating one gets you "leave room for me" by construction instead.

---

## Session B — node 1, ~20 min, desktop powered on

**Do not do this from memory — I have written you a script.** See
`docs/planning/NODE1_HANDOFF.md` and the call word at the end of this document.
Start a Claude session on the desktop, say the call word, and it will walk the
whole session and verify each step as it goes. What follows is the summary so
you know what you are agreeing to.

### B1. Four services, and the login screen stays exactly as it is

You asked whether there was an alternative to deleting the login screen.
**There is: Windows services run as SYSTEM at boot, before anyone logs in.**
Four of them make node 1 fully usable with nobody signed in:

| Service | What it gives | Notes |
|---|---|---|
| Tailscale | reachability from anywhere | service is the install default — just don't pick "tray only" |
| OpenSSH Server (`sshd`) | shell + file transfer | built into Windows; enable, don't install |
| `llama-server` | inference | wrapped as a service, build `b10405` only |
| VESPER node agent | presence, health, quota reporting | I write this; you just start it |

**No stored password, no auto-login, no second profile, no code entry.** Your
profile stays protected. Your desk experience is unchanged. See §9c of the plan
for why the design you sketched cannot bootstrap and why auto-login would cost
security for nothing.

### B2. Wi-Fi profile for all users — the one real trap

A per-user Wi-Fi profile connects only *after* someone logs in, and nobody
will be. The machine would boot on schedule, sit with no network, and present
as "powered on but unreachable" — the least diagnosable failure available.
One line, and the handoff session runs it:

```
netsh wlan set profileparameter name="YOUR_SSID" connectionmode=auto
```

### B3. Hibernate, not shutdown — this replaced the BIOS work

**Correction from yesterday, in your favour:** you do not need a BIOS schedule.
Wake timers work from **S4 hibernate**, which is powered-down, not sleep, and
draws essentially what a full shutdown draws. `tools/ops/alarm_night.py`
already builds the `-WakeToRun` task and reads the flag back to confirm.

So the desktop **hibernates** (`shutdown /h`) rather than shutting down, and
VESPER wakes it on the schedule it computed on Thursday.

**Optional, 2 min, while you're at the desk:** enable *Resume by RTC Alarm* in
BIOS (*Advanced → Wake Up Event Setup*). It buys recovery from a true power-off
— e.g. after a power cut. It is now a nice-to-have, not a dependency, and
**nothing waits for it.**

### B4. Tailscale key expiry on node 1

Same as A3 and it matters more here: *Machines* → node 1 → ⋯ → **Disable key
expiry**. Tailscale's docs name exactly this case — *"trusted servers ... or
remote IoT devices that are hard to reach."* A desktop you visit on weekends
qualifies.

---

## Session C — browser toggles, ~5 min

Three opt-outs. Each is per-account, and each is a precondition for that
provider carrying private work at all (`PROVIDER_SUPPLY.md` §3).

| # | Where | Setting | Default |
|---|---|---|---|
| C1 | Anthropic, **VESPER's account** | training **off** | on = 5 years retention in training pipelines |
| C2 | OpenAI — **TWO toggles** | *Data Controls → Improve the model for everyone* → off, **AND** Codex Settings → training on "full environments" → off. See `CREDENTIALS.md` §3d | both **on**; the second is independent |
| C3 | Mistral → *Admin Console → Privacy* | opt **out** of training | **in** |

C1 and C2 are what let rung 2 exist at all. Without them, both subscription
rungs are restricted to public content and the ladder loses its two strongest
fallbacks.

---

## What I do the moment A1 lands

Stages 1–8 of the plan's build order, none of which need node 1 or session C:
quota ledger, quota-ordered selection, the 10-attempt chain budget, the voice,
the Cloudflare and Groq adapters, the triage queue, tier-1 repair, and the
image router. That is the full text and image ladder, working, today.

Stages 9–11 — node presence, wake schedule, Thursday ritual — land after
session B.

---

## Node 1 handoff — the call word

When you're at the desktop, start a Claude Code session there and paste this:

> **`VESPER node-1 enrolment: read docs/planning/NODE1_HANDOFF.md and run it.`**

That document is self-contained: it assumes no memory of this conversation,
states what to verify before each step, and refuses to proceed on an unverified
one. It covers the four services, the Wi-Fi profile, hibernate, Tailscale, and
the enrolment probe that writes node 1's measured profile.

`NODE1_HANDOFF.md` is **written and ready now** — 263 lines, self-contained,
assumes no memory of this conversation. It carries the four services, the
Wi-Fi trap, the hibernate rehearsal, the enrolment probe, and a closing list
of five things on that machine that look like bugs and are not, so the session
does not burn an hour rediscovering them.

The one thing it cannot know in advance is your tailnet name — so it
**discovers** that in step 1a and reports it back, rather than having it
guessed at here.
