#!/usr/bin/env python3
"""Measure every configured remote provider, so the router may use them.

WHY THIS MUST RUN BEFORE ANYTHING IS ROUTED REMOTELY. INV-HW-2: throughput is
measured at enrollment, never declared, and UNKNOWN means UNAVAILABLE. Every
remote row in `contracts/policy/provider_supply.toml` arrives with a PUBLISHED
quota and no measured rate at all, so until this has run they are unroutable --
correctly, and fail-closed.

WHAT IT REFUSES TO DO. It does not write `capability_profiles.toml` and it does
not grade anything. Promotion into a contract is a separate reviewed act, and a
probe that decided its own passing grade would be a supplier raising its own
ceiling. It emits facts with the command that produced each.

TWO THINGS IT MEASURES THAT A NAIVE PROBE WOULD MISS, both found live on
2026-08-25:

  MODEL AVAILABILITY IS NOT WHAT THE CATALOGUE SAYS. A provider's `/models`
  listed 37 entries supporting generation; most 404 on these credentials, and
  the one that worked was named in an ERROR rather than in the listing. So the
  probe calls the configured model directly. A row whose model does not answer
  is reported UNAVAILABLE rather than assumed present.

  A 200 IS NOT AN ANSWER. One provider returned HTTP 200, finish_reason
  `length`, and empty content -- reasoning tokens had consumed the whole budget
  before any content was emitted. The probe therefore asserts on the TEXT, not
  on the status code, and records the completion tokens actually billed, which
  include reasoning.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUPPLY = REPO / "contracts" / "policy" / "provider_supply.toml"
SECRETS = Path.home() / ".config" / "vesper" / "secrets.env"

# One prompt for every provider, so the rows are comparable.
#
# IT ASKS FOR A LONG ANSWER ON PURPOSE, and the first version of this file did
# not. It asked for three colours, got five tokens back, and computed
# "0.37 tokens/sec" -- which is not a throughput measurement at all. On a
# five-token answer the wall clock is almost entirely round-trip latency, so
# the figure measures the network and calls it the model.
#
# THAT NUMBER WOULD HAVE BROKEN ROUTING RATHER THAN JUST BEING WRONG.
# `core/router.py` selects on `wall_tokens_per_sec` and prefers the faster
# candidate; handed 0.37 it would rank a working provider as unusably slow and
# never route to it again. INV-HW-2 exists to refuse declared numbers, and a
# measurement taken in conditions that cannot show the quantity is a declared
# number wearing a measurement's clothes. The instrument has to be able to see
# the thing before its reading is evidence.
PROMPT = ("Write a plain-English explanation, about 300 words, of why a "
          "system that retries a failed request should wait longer between "
          "each attempt. Do not use bullet points.")
# STEM, NOT A WHOLE WORD, and this cost a false failure to learn. The check was
# `"retry" in text`, a provider answered at length and correctly, and it was
# marked EMPTY-200 -- because the answer said "retries", which does not contain
# the substring "retry". The instrument reported a broken provider and the
# provider was fine. Second time in one day that a hand-written oracle produced
# a false negative; both times the fix was to make the oracle weaker and the
# evidence stronger.
EXPECT = ("retr",)                # matches retry / retries / retrying

# Below this, wall-clock is dominated by round-trip latency and the derived
# rate is not a throughput figure. Such a sample is REPORTED and FLAGGED rather
# than dropped -- the call still proves the provider answers, which is the
# other thing this probe is for.
MIN_TOKENS_FOR_RATE = 50


def load_secrets() -> dict:
    """Read the owner's credential file. NEVER printed, only read."""
    out = {}
    if not SECRETS.exists():
        return out
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*export\s+([A-Z0-9_]+)=(.*)', line)
        if not m:
            continue
        v = m.group(2).split("#", 1)[0].strip().strip('"').strip("'")
        if v.startswith("$"):                      # alias to another var
            v = out.get(v.lstrip("$"), "")
        out[m.group(1)] = v
    return out


def _post(url: str, payload: dict, headers: dict, timeout: float = 90.0):
    body = json.dumps(payload).encode("utf-8")
    # See routing/http_completion.py: the urllib default User-Agent is 403'd
    # by at least one provider's WAF, and 403 classifies as auth_failed.
    h = {"Content-Type": "application/json", "User-Agent": "vesper/1.0"}
    h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                         # noqa: BLE001
        return 0, {"error": {"message": f"{type(e).__name__}: {e}"}}


def call(row: dict, secrets: dict) -> dict:
    """One measured call. Returns facts, never a grade."""
    wire = row["wire"]
    key = secrets.get(row["credential_env"], "")
    model = row["model"]
    url = row["endpoint"].replace("{model}", model)
    if "{account}" in url:
        url = url.replace("{account}", secrets.get(row.get("account_env", ""), ""))

    if wire == "openai_chat":
        hdr = {"Authorization": f"Bearer {key}"}
        payload = {"model": model, "max_tokens": 2048,
                   "messages": [{"role": "user", "content": PROMPT}]}
    elif wire == "cf_responses":
        hdr = {"Authorization": f"Bearer {key}"}
        payload = {"input": PROMPT}
    elif wire == "google_generate":
        hdr = {"x-goog-api-key": key}
        payload = {"contents": [{"parts": [{"text": PROMPT}]}]}
    else:
        return {"ok": False, "reason": f"unknown wire format {wire!r}"}

    t0 = time.perf_counter()
    status, body = _post(url, payload, hdr)
    elapsed = time.perf_counter() - t0
    return {"status": status, "elapsed_s": round(elapsed, 3),
            **extract(wire, body), "raw_error": (body.get("error") or {}).get("message")}


def extract(wire: str, body: dict) -> dict:
    """Pull text and billed tokens out of three different response shapes."""
    text, completion, prompt_toks = None, None, None
    try:
        if wire == "openai_chat":
            c = (body.get("choices") or [{}])[0]
            text = (c.get("message") or {}).get("content")
            u = body.get("usage") or {}
            completion, prompt_toks = u.get("completion_tokens"), u.get("prompt_tokens")
        elif wire == "cf_responses":
            res = body.get("result") or {}
            for o in res.get("output") or []:
                if o.get("type") == "message":
                    text = "".join(p.get("text", "") for p in o.get("content") or [])
            u = res.get("usage") or {}
            completion, prompt_toks = u.get("output_tokens"), u.get("input_tokens")
        elif wire == "google_generate":
            cand = (body.get("candidates") or [{}])[0]
            text = "".join(p.get("text", "")
                           for p in (cand.get("content") or {}).get("parts") or [])
            u = body.get("usageMetadata") or {}
            completion = u.get("candidatesTokenCount")
            prompt_toks = u.get("promptTokenCount")
    except Exception as e:                          # noqa: BLE001
        return {"extract_error": f"{type(e).__name__}: {e}"}
    return {"text": text, "completion_tokens": completion,
            "prompt_tokens": prompt_toks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write results JSON here")
    ap.add_argument("--only", default=None, help="probe one provider id")
    args = ap.parse_args()

    secrets = load_secrets()
    rows = tomllib.loads(SUPPLY.read_text(encoding="utf-8"))["provider"]
    if args.only:
        rows = [r for r in rows if r["id"] == args.only]

    results, usable = [], 0
    for row in rows:
        pid = row["id"]
        if not secrets.get(row["credential_env"]):
            print(f"  {pid:<12} SKIP     no credential in {row['credential_env']}")
            results.append({"provider_id": pid, "usable": False,
                            "reason": "no credential present"})
            continue
        r = call(row, secrets)
        text = (r.get("text") or "").strip()
        # ASSERT ON THE TEXT, NOT THE STATUS. A 200 carrying empty content was
        # measured on this fabric; a probe trusting the status would enroll a
        # provider that cannot answer.
        answered = bool(text) and all(w in text.lower() for w in EXPECT)
        ok = r.get("status") == 200 and answered
        usable += 1 if ok else 0
        ctok = r.get("completion_tokens")
        # WHAT TO DO WHEN A PROVIDER WILL NOT SAY WHAT IT BILLED.
        #
        # Cloudflare reports input_tokens 0, output_tokens 0, neurons 0 on calls
        # that plainly worked (MULTI_ROUTE.md SS13.5). So its token rate cannot
        # be read from its own accounting -- and it is the single most valuable
        # row in the table: E1-PRIVATE, the largest free quota, and the only
        # vetted image supply. Leaving it unroutable to satisfy a rule would be
        # the rule defeating its own purpose.
        #
        # But throughput IS observable here, just in different units. The
        # response text is in hand, so CHARACTERS PER SECOND is a direct
        # measurement of a real quantity with nothing assumed. Only the
        # conversion to tokens carries an assumption, and it is a property of
        # English text rather than a claim about this provider.
        #
        # So the two are recorded SEPARATELY and honestly: chars/sec measured,
        # tokens/sec derived, with the divisor written down. A caller may then
        # decide what it is willing to route on, instead of being handed one
        # number whose pedigree has been laundered away.
        CHARS_PER_TOKEN = 4.0        # standard English approximation, not measured here
        chars = len(text)
        cps = (round(chars / r["elapsed_s"], 1)
               if r.get("elapsed_s") and chars else None)
        derived_tps = (round(cps / CHARS_PER_TOKEN, 2)
                       if cps and chars >= MIN_TOKENS_FOR_RATE * CHARS_PER_TOKEN
                       else None)
        latency_bound = bool(ctok is not None and ctok < MIN_TOKENS_FOR_RATE)
        rate = (round(ctok / r["elapsed_s"], 2)
                if ok and ctok and r.get("elapsed_s") and not latency_bound
                else None)
        # THREE OUTCOMES, NOT TWO, because they need different responses.
        # "EMPTY-200" previously labelled BOTH a genuinely empty answer and an
        # answer that simply failed the content check -- so a bug in the oracle
        # was indistinguishable from a real provider fault, which is the one
        # distinction a probe exists to draw.
        if ok:
            verdict = "OK"
        elif r.get("status") != 200:
            verdict = "FAIL"
        elif not text:
            verdict = "EMPTY-200"          # real: 200 carrying no answer
        else:
            verdict = "OFF-TOPIC"          # answered, but not what was asked
        detail = "" if ok else f"  {(r.get('raw_error') or text or '')[:52]}"
        shown = (f"tok/s={rate}" if rate is not None
                 else (f"tok/s~{derived_tps} (derived from chars)"
                       if derived_tps is not None
                       else ("tok/s=LATENCY-BOUND" if latency_bound else "tok/s=None")))
        print(f"  {pid:<12} {verdict:<9} {r.get('status')}  "
              f"{r['elapsed_s']:>6.2f}s  completion={ctok}  {shown}{detail}")
        results.append({
            "provider_id": pid, "usable": ok, "status": r.get("status"),
            "elapsed_s": r.get("elapsed_s"),
            "completion_tokens": ctok, "prompt_tokens": r.get("prompt_tokens"),
            "measured_tokens_per_sec": rate,
            # FAIL-CLOSED FOR THE ROUTER. None here means UNAVAILABLE, which is
            # the correct reading: we did not measure this provider's rate. It
            # must never be filled in from a latency-bound sample.
            "rate_is_measured": rate is not None,
            # MEASURED: nothing assumed, the text was counted.
            "output_chars": chars,
            "measured_chars_per_sec": cps,
            # DERIVED: chars/sec is measured, the divisor is an English-text
            # approximation. Kept in a separate field from the measured rate so
            # a consumer must opt in to the assumption rather than inherit it.
            "derived_tokens_per_sec": derived_tps,
            "derivation": f"measured_chars_per_sec / {CHARS_PER_TOKEN} chars-per-token (English approximation, NOT measured on this provider)",
            "latency_bound": latency_bound,
            "min_tokens_for_rate": MIN_TOKENS_FOR_RATE,
            "model": row["model"], "wire": row["wire"],
            "egress_class": row["egress_class"],
            "answered_correctly": answered,
            "error": r.get("raw_error"),
            # PROVENANCE TRAVELS WITH THE NUMBER.
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prompt": PROMPT,
            "note": ("wall-clock over one call. completion_tokens INCLUDES "
                     "reasoning tokens where the provider bills them that way, "
                     "which is what the ledger must charge against quota."),
        })

    print(f"\n  {usable}/{len(rows)} providers answered correctly")
    if args.out:
        p = Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "schema_version": 1,
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prompt": PROMPT, "results": results}, indent=2), encoding="utf-8")
        print(f"  wrote {p}")
    # A probe that finds nothing usable exits non-zero: fail-closed, and the
    # caller must not proceed to register providers it could not measure.
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
