# Every credential VESPER needs — table, privacy guides, MCP setup

Written 2026-08-25. Companion to `PROVIDER_SUPPLY.md` (who may see what) and
`MULTI_ROUTE.md` (the ladder). This is the doing document.

**Three parts.** §1 is the table — get the keys. §3 is the privacy work, which
is what makes four of them usable for your private data at all. §4 is MCP,
where you log in and I do the wiring.

---

## 0. Where keys go, and the one rule

Everything lands in `~/.config/vesper/secrets.env`, already `0600`, already
holding your Google key. Append; don't rewrite.

```bash
chmod 600 ~/.config/vesper/secrets.env      # confirm, costs nothing
```

**Paste values into that file, never into chat.** I never need to see one —
only the variable name and your confirmation it's there. If a key ever does
land in a message, treat it as compromised and roll it; that is cheap and
certain, whereas "probably fine" is neither.

`L-006` asserts a canary key appears in no result, no published record, and no
file a run wrote — the codebase already holds credentials in a closure that
reaches the request header and nothing else, deliberately, because a key on a
provenance object gets persisted by telemetry and the leak looks exactly like
correct record-keeping.

---

## 1. The table

**Nine credentials, two accounts.** None requires a card. The `Privacy action`
column is the one that matters: **four of these default to training on your
input**, and until you change that they are restricted to public content.

| # | Provider | What it unlocks | Env var(s) | Privacy action | Egress after |
|---|---|---|---|---|---|
| 1 | **Cloudflare Workers AI** | **Text + ALL image generation.** 10,000 neurons/day, shared pool | `CLOUDFLARE_ACCOUNT_ID`<br>`CLOUDFLARE_API_TOKEN` | **None** — contractual already | `E1-PRIVATE` |
| 2 | **Groq** | Text, `strong` tier, 200K tokens/day | `GROQ_API_KEY` | **§3a — ZDR** | `E1` after |
| 3 | **Ollama Cloud** | Text, `strong`. Quota unpublished → opportunistic | `OLLAMA_API_KEY` | **None** — zero retention published | `E1-PRIVATE` |
| 4 | **Mistral** | Text, $10/mo credits | `MISTRAL_API_KEY` | **§3b — required** | `E1` after |
| 5 | **NVIDIA NIM** | Text, `strong`, ~1,000 credits | `NVIDIA_NIM_API_KEY` | Terms unconfirmed | **`E2` pending** |
| 6 | **OpenRouter** | Text, 50/day | `OPENROUTER_API_KEY` | **Cannot be fixed** — see note | **`E2` only** |
| 7 | *Google AI Studio* | *already in the file* | *(present)* | **Cannot be fixed** | **`E2` only** |
| 8 | **Tailscale** | Desktop reachability | *(account, not a key)* | n/a | n/a |
| 9 | **Claude Pro** ×1 | MCP rung 2, text | *(OAuth — §4)* | **§3c** | `E1` after |
| 10 | **ChatGPT Plus** | MCP rung 2, text | *(OAuth — §4)* | **§3d — TWO toggles** | `E1` after |

**`E1-PRIVATE`** = may see your private content. **`E2`** = public content
only. Rule R6 in `PROVIDER_SUPPLY.md`: **egress class gates the provider before
quota does**, so a big free quota never wins access to private data.

> **Why 6 and 7 can't be fixed, and it isn't an oversight.** OpenRouter's free
> endpoints *only appear* if you enable "free endpoints that may train on
> inputs" — with it off you get `404 No endpoints available matching your data
> policy`. Training consent is the price of the free tier by construction.
> Google's unpaid tier says in its own terms not to submit confidential
> information. Both are still genuinely useful for public work, and VESPER will
> use them for exactly that.

**Rough order of value if you want to stop early:** 1 and 2 are the whole
ladder — do those. 3 and 4 are free capacity for ten minutes' work. 5 and 6 are
optional. 8 is needed only for the desktop.

---

## 2. Getting each key

**1. Cloudflare** — `dash.cloudflare.com`
- **Account ID**: dashboard home, right-hand sidebar. Copy it.
- **Token**: *AI → Workers AI → Use REST API → Create a Workers AI API Token*.
- Shown **once**. Copy it before closing the dialog.

**2. Groq** — `console.groq.com` → *API Keys* → *Create API Key*.
Then **§3a immediately** — the key is not usable for private work until then.

**3. Ollama Cloud** — `ollama.com` → sign in → *Settings → Keys*.
No privacy step; zero retention and no training are published, and they
require the same of their GPU partners.

**4. Mistral** — `console.mistral.ai` → *API Keys*.
Then **§3b** — free tier defaults **into** training.

**5. NVIDIA NIM** — `build.nvidia.com` → sign in → any model → *Get API Key*.
~1,000 credits, more on request. I register this **public-only** until its
data terms are confirmed in an actual contract rather than a product page —
`PROVIDER_SUPPLY.md` §3 already flags it as `pending` for that reason.

**6. OpenRouter** — `openrouter.ai/keys`. Leave the data-policy toggles as
they are; VESPER routes only public content here regardless.

**8. Tailscale** — `login.tailscale.com`, any sign-in provider. Free Personal.

> **Correction to what I told you yesterday:** I wrote
> `brew install --cask tailscale`. **There is no Homebrew on this machine**
> (checked — no `brew`, no `/opt/homebrew`, no `/usr/local/bin/brew`). Download
> the macOS package directly from `pkgs.tailscale.com/stable/#macos` instead.
> Prefer the **standalone** build over the App Store one — the App Store
> sandbox restricts the CLI, and VESPER needs the CLI.
>
> **Then: Machines → this device → ⋯ → Disable key expiry.** This is the fix
> for "links always need updating after shutdown" — node keys expire at 180
> days and the device drops off the tailnet until someone re-auths in a browser.

---

## 3. The privacy guides

Four providers. Each is per-account, each takes under a minute, and each is a
**precondition**, not a hardening extra: until it's done, that provider is
restricted to public content and the ladder is shorter.

### 3a. Groq — Zero Data Retention

`console.groq.com/settings/data-controls` → enable **Zero Data Retention (ZDR)**

Groq's contract is already good: their Services Agreement forbids training or
fine-tuning on your Inputs or Outputs unless you instruct it, and their docs
state *"By default, Groq does not retain customer data for inference
requests."* What remains is up to 30 days of retention for reliability
monitoring and abuse prevention. **ZDR turns that off too.**

- **Verify:** the Data Controls page shows ZDR enabled.
- **Note:** ZDR disables features that need persistence — batch processing and
  fine-tuning. VESPER uses neither.

### 3b. Mistral — opt out, because free tier defaults in

`admin.mistral.ai` → **Privacy** → under *Anonymous improvement data*, disable
the toggle.

This is the path for **Studio/API**, which is what VESPER uses. Mistral's own
help documents the defaults plainly: Team, Enterprise and pay-as-you-go are
opted **out** by default; **free tier users must opt out manually** and their
data may otherwise be included in training.

- **Verify:** the toggle reads disabled after a page reload.
- If you also use their chat app, it has a *separate* control
  (*Manage → Vibe → Privacy → "Allow your interactions to be used to train our
  models"*). Not needed for VESPER, worth knowing.

### 3c. Anthropic — Help Improve Claude, on VESPER's account

Settings menu (your name) → **Settings → Privacy → Help Improve Claude** → off.

The retention difference is large and worth knowing before you choose which
account is VESPER's: **on** means data may be kept de-identified for **up to
five years** in model training pipelines; **off** returns you to the standard
**30-day** retention.

**It explicitly covers Claude Code** — Anthropic's policy names *"consumer
products such as Claude Free, Pro, Max and when accounts from those plans use
Claude Code."* So this toggle governs the MCP rung directly.

- **Do it on VESPER's account.** Do your own as you prefer; that one is yours.
- **Verify:** reload Settings → Privacy and confirm it reads off.
- Already-started training runs and already-trained models are unaffected.
  That's stated in their policy and is true of every opt-out here.

### 3d. OpenAI — TWO toggles, and this corrects what I told you

**I told you on 2026-08-25 that one control covers Codex too. That is wrong,
and it matters because it would have left the Codex rung training on your
code while you believed it was off.**

**Toggle 1 — ChatGPT:**
Profile → **Settings → Data Controls → "Improve the model for everyone"** → off.
Default is **on**. Applies account-wide across devices, on Free, Plus and Pro.

**Toggle 2 — Codex, separate and independent:**
Open **Codex Settings** and switch off the control allowing training on
**"full environments."** Multiple sources state this is independent of both
the ChatGPT toggle and the privacy portal — the portal opt-out does **not**
override it.

> **Source quality, stated plainly.** OpenAI's own help-centre pages return
> 403 to automated fetching, so I could not read the primary source. This rests
> on several consistent secondary accounts. **Treat toggle 2 as unconfirmed
> until you see it in the UI** — and when you're in Codex Settings, tell me
> what the control is actually called and what it was set to. That converts
> this from a report into a measurement, and I'll correct the record either way.

- **Verify:** both settings read off after a reload.

### Who needs nothing

**Cloudflare** and **Ollama Cloud**. Cloudflare's terms already state they do
not use your content to train models or improve their services; Ollama Cloud
publishes no logging, no training, zero retention. Nothing to toggle — which
is exactly why they lead the ladder.

---

## 4. The subscription rungs — CORRECTED 2026-08-25, verified live

**Two corrections to what I wrote earlier today**, both found by actually
running the thing rather than reading about it.

### 4.0 It is not MCP, and the apps cannot do it

I called this "MCP" and pointed at `claude mcp serve`. **Wrong surface, and the
error is a direction mismatch.**

- `claude mcp serve` makes Claude Code an MCP **server**, exposing its *tools*
  — read a file, run bash, edit — to some MCP **client**. It does not offer
  "run this prompt and give me the text back."
- The Claude desktop app and the ChatGPT app are MCP **clients**. They
  *consume* MCP servers you add to them. Neither can serve VESPER.
- **VESPER is the client here.** It needs something that answers a prompt. That
  is **headless CLI mode**, not MCP:

```bash
CLAUDE_CONFIG_DIR=~/.config/vesper/claude-vesper claude -p "<prompt>"
```

**VERIFIED 2026-08-25**: that exact command returned a completion through the
isolated config. Rung 2 works, and it is a subprocess call — simpler than MCP,
with no server to keep alive.

This also matches doctrine already recorded on this project for the same class
of problem: **use the headless CLI, never the subagent path.**

> **So the app question answers itself: no, and not because of a policy.** The
> apps are the wrong end of the pipe. There is no setting in either app that
> makes it callable by VESPER — and driving the apps' UI instead is the path
> closed in `PROVIDER_SUPPLY.md` §1 by both vendors' terms.

### 4.1 `CLAUDE_CONFIG_DIR` does isolate the account — but it grabbed the wrong one

Good news first: the isolation is real, and better than I could promise this
morning. Claude Code derives a **per-config-dir keychain service name**, so the
two accounts do not share credentials. Measured on this Mac:

```
Claude Code-credentials             <- default ~/.claude
Claude Code-credentials-7a8c62da    <- ~/.config/vesper/claude-vesper
```

Two separate keychain items, so VESPER's login and yours are genuinely
independent.

**The problem:** running the command opened a session that reused the login
already in the browser, so **both config dirs are currently bound to the same
account** — `<owner-email>`, the owner's own. Measured by reading
`oauthAccount.emailAddress` out of each `.claude.json`.

That is the opposite of the design. Rung 2 exists so VESPER draws on its **own**
account and leaves the owner's 5-hour window untouched; pointed at the owner's
account it competes with the owner for the same pool.

**The fix — inside the isolated session only:**

```bash
CLAUDE_CONFIG_DIR=~/.config/vesper/claude-vesper claude
```
then, at the prompt:
```
/login
```
Sign out if offered, and sign in as **VESPER's** account. You may need a private
browser window, or to sign out of the other account first — the flow follows
whatever session the browser already has, which is exactly how it picked wrong.

**Verify before trusting it** — the instrument's self-report is not evidence:

```bash
python3 -c "import json,pathlib;d=json.loads((pathlib.Path.home()/'.config/vesper/claude-vesper/.claude.json').read_text());print(d.get('oauthAccount',{}).get('emailAddress'))"
```

That must print **VESPER's** address, not yours. If it prints yours, the login
did not take and rung 2 is pointed at your quota.

Then do **§3c** (*Help Improve Claude* → off) **on VESPER's account**, not
yours — it is a per-account setting and the account it matters for is the one
VESPER is about to send work through.

### 4.2 Codex — same shape, same correction

Not MCP either. Codex has a headless mode; VESPER calls it as a subprocess.

`codex` is absent, and so are `node` and `npm` (checked). Two routes:

- **Route A:** Node LTS from `nodejs.org`, then `npm install -g @openai/codex`.
  Watch the name — `npm i -g codex` is an **unrelated** package that installs
  silently and does nothing.
- **Route B (recommended):** the standalone binary from the `openai/codex`
  GitHub releases. No JS toolchain on this machine otherwise.

Then `codex login` — browser OAuth against your Plus subscription. One account,
so no isolation problem here.

Then **§3d, both toggles.** Until toggle 2 is confirmed in the UI, I register
Codex **public-content-only**.

### 4.3 What I do

- both rungs registered as `Provider` handles behind the gateway, at **rung 2
  only**, so they can never be reached ahead of the free APIs
- the `CLAUDE_CONFIG_DIR` binding, with **no failover edge** between Claude
  accounts at any level
- egress-class enforcement per rung
- your manual retrigger stays a **new session**, never a failover — you make
  that call, VESPER never does

---

## 5. Checklist

Tick these off and tell me; I don't need values, just names.

```
[ ] 1  CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN     <- unblocks my build
[ ] 2  GROQ_API_KEY            + §3a ZDR                <- unblocks my build
[ ] 3  OLLAMA_API_KEY
[ ] 4  MISTRAL_API_KEY         + §3b opt-out
[ ] 5  NVIDIA_NIM_API_KEY                               (public-only for now)
[ ] 6  OPENROUTER_API_KEY                               (public-only, always)
[ ] 8  Tailscale account + Disable key expiry on this Mac
[ ] 9  Claude: /login as VESPER's account in the isolated dir + verify + §3c
[ ] 10 Codex installed + logged in         + §3d BOTH toggles
```

**Items 1 and 2 are the only hard blockers.** Say "1 and 2 are in" and I start
building — everything else can land while I work.
