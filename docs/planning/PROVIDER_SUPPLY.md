# What supplies VESPER's thinking — the provider table

**Status: DESIGN, 2026-08-25.** Lives in `docs/planning/` so it is outside
`NORMATIVE_ROOTS` and CI-free until it earns promotion. Nothing here is
promoted into `contracts/policy/` by this document; §8 lists what promotion
would take.

**Every number below carries where it came from and when.** Figures marked
PRIMARY were read off the vendor's own docs or terms on 2026-08-25. Figures
marked SECONDARY came from third-party roundups and are the weaker kind —
§7 records five figures from a roundup that were wrong when checked. Figures
marked MEASURED were produced by this fabric.

---

## 0. The shape, settled before the table

`SR-003`/`SR-005` and the owner's handwritten page 1 already fix the ordering,
and 2026-08-25's power work added a second reason for it:

- **Remote is primary for work.** A network request costs this host ~nothing.
- **Local is the offline backup, in bursts.** MEASURED: generation is 34–41 W
  against 5.1 W idle, and the levers cut that 2–3x at best because the floor is
  memory bandwidth. See `PLAN_2026-08-25-power.md` §6.
- **Neither alone.** A network-only VESPER dies with the router, which the
  survival core and `INV-PLACE-3` forbid.

So the question is never "API or local". It is *which* remote sources, in what
order, under what caps, allowed to see what.

---

## 1. The path that is closed, and why it is closed in writing

Driving a consumer chat product from a logged-in profile — meta.ai, ChatGPT
web, claude.ai — was the owner's idea on 2026-08-25 and was checked rather than
declined on judgement. It is prohibited in explicit terms by all three, PRIMARY:

> **Meta**, Terms of Service: "You may not access or collect data from our
> Products using automated means (without our prior permission)… **regardless of
> whether such automated access or collection is undertaken while logged-in to
> a Facebook account**." The same page requires one account per person, for
> personal purposes, and forbids circumventing technological access measures.

> **OpenAI**, Terms of Use: "Except as permitted through the API, use any
> automated or programmatic method to extract data or Output from the Services,
> including scraping, web harvesting, or web data extraction."

> **Anthropic**, Consumer Terms: "Except when you are accessing our Services via
> an Anthropic API Key **or where we otherwise explicitly permit it**, to access
> the Services through automated or non-human means, whether through a bot,
> script, or otherwise." Separately: account credentials may not be shared or
> made available to anyone else.

Meta's clause names the exact idea — being signed in as yourself is anticipated
and does not exempt it.

**It is enforced technically as well as contractually.** openai.com returned
**HTTP 403** to this session's own fetch of its terms page; their edge rejects
non-browser clients by default. Meta runs a dedicated anti-scraping team with
rate and data limits.

**The useful half:** all three carve out the same exception — the API, or a
client the vendor explicitly permits. That exception is where §4's subscription
row lives. The idea was not wrong; the door it used was.

---

## 2. Egress classes — vocabulary this document introduces

The corpus has trust zones for NODES (`Z0`/`Z1`/`Z2`, `admission_baseline.toml`)
and record classes for DURABILITY (`INV-LOSS-4`). It has **no** vocabulary for
what a given piece of content may be sent to. This document proposes one,
because the provider table is unreadable without it. It is **new here and not
promoted** — see §8.

| Egress class | Content | Rule |
|---|---|---|
| `E0-LOCAL` | Physiological and mood inference | **Never leaves this fabric.** `INV-PRIV-2` states it outright: owner-only, local-only, non-exportable. No provider row in §4 may carry it, including the paid ones |
| `E1-PRIVATE` | Owner memory, audit records, health, finances, home telemetry, personal correspondence, anything naming a household member | Only providers §3 classifies **PERMITTED**. Fail-closed: `UNKNOWN` is treated as forbidden |
| `E2-WORK` | This repo's code, specs, plans, public technical material | Any provider in §4 |
| `E3-PUBLIC` | Content already published | Any provider in §4 |

`INV-PRIV-1`'s discipline applies to the choice itself: when the class of a
piece of content is uncertain, it takes the **more** private route, never the
more public one. A default that resolves ambiguity toward `E2` is the bug this
row exists to prevent.

---

## 3. The data-usage sweep — who may see `E1-PRIVATE`

Swept 2026-08-25. **A silent policy is not a permissive one:** where a vendor's
published terms do not say, this table records `UNKNOWN` and the fail-closed
disposition, exactly as `INV-HW-2` treats an unmeasured throughput.

| Provider | Trains on input? | Retention | `E1-PRIVATE` |
|---|---|---|---|
| **Cloudflare Workers AI** | **No**, explicit — PRIMARY: *"Cloudflare does not use your Customer Content to (1) train any AI models made available on Workers AI or (2) improve any Cloudflare or third-party services, and would not do so unless we received your explicit consent"* | content retained only if you use CF storage bindings | **PERMITTED** |
| **Groq** | **No**, contractual — PRIMARY, Services Agreement: Groq is not permitted to use Inputs or Outputs for training or fine-tuning unless the customer instructs it | none by default; ≤30-day logs for reliability/abuse, **opt-out in Data Controls**; ZDR for eligible accounts | **PERMITTED once the logging opt-out is set** |
| **Ollama Cloud** | **No** — PRIMARY: no logging, no training, zero retention, required of their NVIDIA cloud partners as well | zero | **PERMITTED** |
| **NVIDIA NIM** | **No** — SECONDARY: product messaging says prompts and responses are not used for training and requests are stateless | minimal operational | **PERMITTED only after the contract itself is read.** A marketing page is an instrument's self-report |
| **Google AI Studio, unpaid** | **YES** — PRIMARY: *"Google uses the content you submit… and any generated responses to provide, improve, and develop Google products and services"*; *"Human reviewers may read, annotate, and process your API input and output"*; **"Do not submit sensitive, confidential, or personal information to the Unpaid Services"** | — | **FORBIDDEN.** Not a caution added here — an instruction in the terms |
| **OpenRouter `:free`** | **YES, by construction** — PRIMARY: free endpoints require enabling *"free endpoints that may train on inputs"* and commonly *"may publish prompts"*; with those off, free models return `404 No endpoints available matching your data policy`. OpenRouter itself does not train; the endpoints behind it do | varies by endpoint | **FORBIDDEN.** The free tier *is* the data trade |
| **Mistral, free (Experiment)** | **YES by default**, opt-**out** — PRIMARY: Admin Console → Privacy → *Anonymous improvement data*. Paid tiers are not used for training | paid: 30-day abuse window | **FORBIDDEN until opted out**, then permitted |
| **Anthropic, consumer plans** | **Account setting.** PRIMARY: if training is allowed, data is kept de-identified **up to 5 years** in training pipelines; the policy explicitly covers **Claude Code on those plans** | deleted chats purged ≤30 days | **PERMITTED only with training off — checked per account, both of them** |
| **OpenAI, ChatGPT Plus** | **ON by default** — PRIMARY: Settings → Data Controls → *Improve the model for everyone*; **CORRECTED 2026-08-25: this does NOT cover Codex.** Codex carries a separate, independent control for training on "full environments" in Codex Settings, which neither the ChatGPT toggle nor the privacy portal overrides. Both are required. See `CREDENTIALS.md` §3d | — | **PERMITTED only with the toggle off** |
| **Novita, Z.ai** | **UNKNOWN** — nothing published that was findable | UNKNOWN | **FORBIDDEN** (fail-closed) |

**The finding that changes the routing table:** the two sources with the
loosest free quotas — Google's unpaid tier and OpenRouter's `:free` catalogue —
are the two that cannot hold owner content. The permission and the generosity
are inversely correlated, and a router that picks on quota alone picks wrong.

---

## 4. The provider table

One reference answer is used throughout so the rows are comparable:
**1,000 input tokens, 300 output tokens.** Rounding is presentation; the neuron
and token arithmetic is shown so it can be re-derived.

### 4a. Key-based remote — the workhorses

| Source | Tier | Free capacity | Reference answers/day | `cost_class` | Egress |
|---|---|---|---|---|---|
| **Cloudflare Workers AI** · `gpt-oss-120b` | `strong` | 10,000 neurons/day, permanent, no card. 31,818 n/M in + 68,182 n/M out → **52.3 n/answer** | **191** | `metered_free_tier` | `E1` |
| **Cloudflare Workers AI** · `llama-3.3-70b-fp8-fast` | `standard` | same pool; 26,668 + 204,805 → **88.1 n/answer** | **113** | `metered_free_tier` | `E1` |
| **Cloudflare Workers AI** · `granite-4.0-h-micro` | `draft` | same pool; 1,542 + 10,158 → **4.59 n/answer** | **2,177** | `metered_free_tier` | `E1` |
| **Groq** · `gpt-oss-120b` / `qwen3.6-27b` | `strong` / `standard` | 30 RPM · 1,000 req/day · 8K TPM · **200K tok/day** | **153** (token-bound, not request-bound) | `metered_free_tier` | `E1` after logging opt-out |
| **NVIDIA NIM** | `strong` | ~1,000 developer credits, up to 5,000 on request; 2026 shifting to ~40 RPM/model | UNKNOWN | `metered_free_tier` | `E1` pending §3 |
| **Ollama Cloud** · `gpt-oss:120b` | `strong` | **unquantified** — "light usage", GPU-time not tokens, 1 concurrent model, 5-hour session + 7-day windows, deprioritised under load | **UNKNOWN — see §6** | `metered_free_tier` | `E1` |
| **Google AI Studio** | `standard` | **20/day MEASURED** on one model from its own 429 (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`); other models unpublished — see §7 | 20 on that model | `metered_free_tier` | **`E2` only** |
| **OpenRouter** `:free` | `standard` | 20 RPM · 50/day (1,000/day after a one-time $10 purchase) | 50 | `metered_free_tier` | **`E2` only** |
| **Mistral** | `standard` | Free plan: **$10/mo in API credits** | credit-bound | `metered_free_tier` | `E1` after opt-out |

**Permitted-for-`E1` free capacity, added up: ~340+ reference answers/day on
120B-class open weights, no card, no grey area** — Cloudflare 191 + Groq 153,
before NVIDIA and Ollama Cloud. Against the ESTIMATED load of 80–100/day
interactive and ~300/day with light autonomy, **the private-safe free tier alone
covers both.** Heavy autonomy (~1,000/day, ESTIMATED) needs the `draft` row —
Cloudflare's granite at 2,177/day — or local.

### 4b. Subscription-backed via MCP — the owner's accounts

This is §1's carve-out: an official client, subscription auth, a documented
programmatic surface. Not scraping, and not a third-party harness holding a
lifted OAuth token.

| Source | Surface | Tier | Metering | Egress |
|---|---|---|---|---|
| **Claude Pro** ×2 accounts | **CORRECTED 2026-08-25:** not MCP. `claude -p` headless CLI, per-account via `CLAUDE_CONFIG_DIR` (separate keychain item per dir, measured). VERIFIED live | `strong` | ~45 messages/5 h on chat; Claude Code ≈ **2x** that throughput on the same plan; **every surface draws from one pool** — claude.ai, Desktop and Claude Code all count against it. Weekly cap on top, unpublished. Pro is Sonnet-only | `E1` **only with training off on that account** |
| **ChatGPT Plus** ×1 | `codex` headless CLI — same shape (not MCP; see `CREDENTIALS.md` §4) | `strong` | **Token-metered since April 2026; no fixed message cap is published.** 5-hour rolling window plus a weekly cap; local CLI, cloud tasks and ChatGPT Work share one pool | `E1` **only with the toggle off** |

### 4c. Local — the offline backup

| Source | Tier | Notes |
|---|---|---|
| `~/VESPER-runtime` llama.cpp b10405, this host | `draft` / `small` | MEASURED 67–69 tok/s at 31 W. Burst-affordable, continuously unaffordable. Load-on-demand, unload when idle |
| Node 1 | `standard` / `strong` | Holds every model above the draft tier. Unreachable while powered off — MEASURED 2026-08-24 |

---

## 5. Rules the router must obey

**R1 — Rotate across providers, never within one.** Several keys from one
vendor to multiply a free quota is multi-accounting to evade a limit: a terms
violation and a ban risk. Several keys across different vendors is ordinary.
The gateway's ordered provider list is already the mechanism (`MEMORY.md` §4i).

**R2 — Never chain the two Claude accounts.** Holding more than one account is
not itself a violation; **using a second one because the first hit its limit
is** — that is limit evasion, and it is what the 2026 enforcement reports
describe, alongside OAuth tokens lifted into third-party harnesses. So:

- **Dedicate account 2 to VESPER, keep account 1 for the owner.** Static
  assignment by workload, decided once.
- **No failover edge between them, at any level.** When VESPER's account is
  exhausted the request falls through to §4a — never sideways.
- This satisfies the owner's "leave room for me" by construction rather than by
  a percentage, which is a stronger guarantee than a cap on a shared pool.

**R3 — The cap is enforced before the call, at the choke point.** `INV-COST-3`
already requires a single gateway choke point no caller may bypass. A budget
discovered by hitting a 429 has already spent the owner's headroom, which is the
thing the cap exists to protect. Fail-closed: an uncounted call does not go.

**R4 — Cap in the unit the vendor meters in.**

| Account | Vendor's unit | VESPER's budget | Basis |
|---|---|---|---|
| Claude Pro (VESPER's) | messages/5 h, shared across all surfaces | **27 requests per 5-hour window** (30% of ~90 Claude-Code-equivalent messages), plus a weekly counter seeded conservatively and raised only on observation | 45 msg/5 h chat, ~2x for Claude Code, SECONDARY |
| ChatGPT Plus | **tokens**, no published cap | **A token budget, not a request count** — seeded low, calibrated from the `usage` field each response returns | Token metering since April 2026, PRIMARY |

A request-count cap on a token-metered plan does not cap anything: one long
context can cost what fifty short ones do. This is the same error as judging a
3-second burst with a gauge that updates every few seconds — the unit has to
match what is actually being spent.

**R5 — 30% is a starting number, not a measurement.** Neither vendor publishes
the ceiling, so the percentage is applied to a SECONDARY figure. It becomes real
only when VESPER has recorded its own usage against a real limit — the same
discipline that turned "20 requests/day" from a guess into a fact by reading it
off the 429.

**R6 — Egress class gates provider selection before tier does.** An `E1` task
never reaches §3's FORBIDDEN rows, however cheap or strong they are. A router
that picks on quota or tier first and filters afterwards has already built the
request.

---

## 6. Ollama Cloud — real, mis-tiered before, and unplannable as it stands

Recorded because a previous session put it in the wrong bucket.

**It is not local inference.** It is a hosted API — the same CLI and
OpenAI-compatible surface as local Ollama, running on their hardware, needing an
ollama.com account and `OLLAMA_API_KEY`. Zero watts on this host. It belongs
with §4a, not with §4c, and the "Ollama means the 31–39 W problem" framing was
about *local* Ollama only.

**What disqualifies it as a planned tier:** the free plan publishes no number.
"Light usage, suitable for chatting and evaluating models" is the whole
specification, the quota is GPU-time on a rolling 5-hour window, one concurrent
model, and free is deprioritised under load. A ceiling discoverable only by
hitting it cannot have a duty cycle sized against it — which is what `INV-HW-2`
refuses in the hardware case for the same reason.

**Disposition:** opportunistic only, never a row the router depends on, until
its ceiling is MEASURED here the way the Gemini 20/day was.

---

## 7. Five figures corrected

All five were given to the owner on 2026-08-25 from third-party roundups and
were wrong when the primary source was read the same day.

| Stated | Actual, PRIMARY |
|---|---|
| GitHub Models — free with a GitHub account | **Retired 2026-07-30.** Playground, catalogue, inference API and BYOK all withdrawn |
| Groq ~14,400 req/day | That is `llama-prompt-guard`, a classifier. **Chat models: 1,000 req/day, 200K tokens/day, 8K TPM** |
| Cerebras ~1M tokens/day free | **$5 trial credits, expiring 30 days after grant**; access stops when they do. Not a recurring free tier |
| Mistral 1B tokens/month | Free plan is now **$10/mo in API credits** |
| Gemini 250–1,500 req/day | **Google no longer publishes per-model free limits** — the docs defer to an authenticated dashboard. The MEASURED 20/day remains the only verified number this fabric holds |

Also withdrawn since the roundups were written: **SambaNova**'s free tier, and
**Chutes**' free tier (2026-03-15).

The one figure that survived contact is the one read off a live 429. That is the
whole argument for `INV-HW-2`, restated in a domain it was not written for.

---

## 8. What promotion would take, and what is still UNKNOWN

Not done by this document:

1. **`contracts/policy/cost_policy.toml` credential entries.** `INV-COST-5`
   makes every one of these `metered_free_tier` and therefore **PAID by
   default** until it carries `provable_hard_cap = true` *with*
   `hard_cap_evidence` naming a mechanism that makes spending impossible. A
   card-free account that can only 429 is exactly such a mechanism; an account
   with a card attached is not. One entry per provider, owner-asserted.
2. **The egress classes of §2** are vocabulary invented here. Promoting them
   means an invariant, a policy file and a check — not a table in `planning/`.
3. **`INV-PRIV-2`'s non-exportable content has no enforcement path at the
   gateway today.** The rule exists; nothing at the choke point reads it.

UNKNOWN, fail-closed until measured or read:

- Ollama Cloud's free ceiling (§6).
- NVIDIA's actual contract, as opposed to its product page (§3).
- Novita's and Z.ai's data policies (§3).
- The real weekly caps on both subscriptions (§5, R5).
- VESPER's own request load: 80–100/day interactive, ~300 light, ~1,000 heavy
  are ESTIMATES and have never been observed.
