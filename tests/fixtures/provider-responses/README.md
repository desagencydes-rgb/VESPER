# Real provider responses, captured 2026-08-25

**Every file here is a verbatim response from a live provider.** None is
hand-written, and that is the entire point: each one is a shape that
contradicted the plan, and four of them would not have been imagined.

## Why these exist

Secrets never leave the owner's machine — Anthropic's own guidance is that
cloud environments have no secrets store and must not be given API keys. So a
cloud session can write the gateway but cannot call a provider to check it.

That is a real gap, because on 2026-08-25 the design was corrected **four
times in one hour**, every time by a live call rather than by reasoning. A
session that cannot make live calls will re-derive plans it has no way to
falsify.

These fixtures close most of that gap. **A cloud session can build and test
every guard against the exact bytes that motivated it**, with no key present.

## What each one proves

| File | The trap |
|---|---|
| `google-429-limit-zero.json` | `RESOURCE_EXHAUSTED` carrying **`limit: 0`**. Not exhausted — *never had any*. Retried as if temporary, it burns the retry budget every day forever. |
| `google-404-model-retired.json` | `gemini-2.5-flash` *"no longer available to new users"* — while `GET /models` still lists 37 models including ones that 404. **A listing is not availability.** |
| `groq-200-empty-content.json` | HTTP **200**, `finish_reason: length`, `content: ''`. Reasoning tokens consumed the whole budget before any content. A success status carrying no answer. |
| `cloudflare-200-zeroed-usage.json` | A call that plainly worked, reporting `input_tokens: 0, output_tokens: 0, neurons: 0`. A ledger trusting this books zero spend forever. |
| `groq-effort-low.json` / `-high.json` | 26 vs 119 completion tokens for the **identical answer** `OK`. The 4.6x that effort control exists to reclaim. |

## Rules for using them

**Do not edit these to make a test pass.** They are evidence. If a fixture
disagrees with the code, the code is wrong or the provider changed — and a
provider change is a finding to record, not a fixture to adjust.

**They expire.** Providers change response shapes without notice; the retired
model above is proof. A fixture is a record of what was true on 2026-08-25,
not a guarantee about today. Anything load-bearing gets re-measured on the
owner's machine before it is trusted again.

**They are not a substitute for a live call.** They cover shapes that were
already seen. The next correction will come from a shape nobody has seen yet,
and only a real call can produce it.

No credential appears in any file — scanned against all seven providers' key
formats before commit.
