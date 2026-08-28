#!/usr/bin/env python3.13
"""Does a repeated, unchanged prefix cost less AGAINST THE RATE LIMIT?

THE QUESTION THIS ANSWERS. The resident-memory design sends a memory graph in
every request. The binding constraint is not the context window (131,072
measured) but the per-minute token rate (8,000 measured on Groq, 2026-08-26).
So the design is affordable if and only if a stable prefix is DISCOUNTED
AGAINST THAT RATE. Whether it is discounted in dollars is a different question
and not the one that decides this.

TWO INDEPENDENT LINES OF EVIDENCE, AND THEY CAN DISAGREE.

  1. `usage.prompt_tokens_details.cached_tokens` -- the provider saying it
     served the prefix from cache.
  2. The drop in `x-ratelimit-remaining-tokens` across the call -- what the
     call actually COST against the ceiling.

(1) is the instrument's self-report and this corpus does not accept those as
evidence. A provider may honestly report a cache hit, bill it at a discount,
and still debit the full prompt against the rate limit -- in which case the
answer to the design question is NO while every docs page says yes. (2) is the
finding; (1) corroborates it or contradicts it, and a contradiction is the most
informative outcome available here.

THE NEGATIVE CONTROL IS THE THIRD CALL. Two calls can only show that the
second was cheaper, which a warm connection, a shorter completion or a refill
would also produce. Call C sends a DIFFERENT prefix of the same length: it
cannot be a cache hit. If C is discounted too, whatever B showed was not
prefix caching. A negative control that passes is a defect, not a relief.

REFILL CONTAMINATES THE DELTA. Groq's bucket refills continuously at ~133
tok/sec, so the remaining-tokens figure recovers between calls and a raw delta
understates the charge. Elapsed wall time is recorded per call and the refill
it implies is reported BESIDE the raw delta, never folded into it. What was
compared is recorded; deriving a single tidy number here would hide the one
term most likely to be wrong.

E1_PRIVATE ONLY. The memory graph is the owner's private content, so rule R6
puts the public rungs permanently out of reach for it however generous their
quota. Measuring the cache behaviour of a rung the graph can never use would
answer a question nobody asked.

Stdlib only. Reads keys from ~/.config/vesper/secrets.env; never prints one.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SUPPLY = ROOT / "contracts" / "policy" / "provider_supply.toml"
SECRETS = pathlib.Path.home() / ".config" / "vesper" / "secrets.env"
OUT = ROOT / "docs" / "spikes" / "data" / "cache_discount_probe.json"

# ~2,200 tokens of prefix. ABOVE THE COMMON MINIMUM: several providers refuse
# to cache a prefix under 1,024 or 2,048 tokens, so a smaller probe would
# report "no caching" for a rung that caches perfectly well at real sizes.
# BELOW THE GROQ CEILING: three calls at this size plus reservation come to
# ~6,700 against an 8,000/min bucket, so the probe fits COLD, without relying
# on refill between calls. Raising it invites a 429 mid-measurement, which is
# indistinguishable in the output from a rung that is down.
PREFIX_TOKENS = 2_200
MAX_TOKENS = 32          # the answer is not wanted; the accounting is
CHARS_PER_TOKEN = 4      # target only -- the provider's own count is the truth

USER_AGENT = "vesper-cache-probe/1"
TIMEOUT = 120.0

# Response headers worth keeping. Providers disagree on spelling, so this is
# matched loosely and the raw names are preserved rather than normalised into
# a shape that would lose which vendor said what.
HDR_RE = re.compile(r"(ratelimit|rate-limit|retry-after|cache)", re.I)


def load_secrets() -> None:
    """Load ~/.config/vesper/secrets.env into the environment.

    The file is `export NAME=value` lines. Values are never printed by this
    script; only the NAME and whether it resolved.
    """
    if not SECRETS.exists():
        sys.exit(f"no secrets file at {SECRETS}")
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_prefix(seed: int, approx_tokens: int) -> str:
    """Deterministic filler SHAPED LIKE THE THING THAT WILL REALLY BE SENT.

    Lorem would measure the cache on text with different entropy and different
    token boundaries than a memory graph has. These lines are the shape L1 is
    specified to carry -- subject, attribute, value, rank, pointer -- so the
    token count per node measured here transfers to the real design instead of
    having to be re-measured later.

    `seed` is what makes call C's prefix a genuine miss: same length, same
    shape, different content.
    """
    out, n = [], 0
    target = approx_tokens * CHARS_PER_TOKEN
    i = 0
    while n < target:
        i += 1
        h = (seed * 7919 + i * 104_729) % 100_000
        line = (f"node {h:05d} | subject=entity_{h % 997:03d} "
                f"attribute=attr_{h % 41:02d} value=v{h % 8641:04d} "
                f"rank=4 observed=hlc:{h}:{i} source=owner_statement "
                f"privacy=private pointer=log#{h % 50_000}\n")
        out.append(line)
        n += len(line)
    # TRUNCATED TO AN EXACT CHARACTER COUNT, and this is not tidiness. The
    # control prefix must differ from the stable one in CONTENT ONLY. Built to
    # a line boundary the two seeds land on different totals, so call C would
    # differ from call B in both content and size -- and a smaller charge on C
    # could then mean "no cache hit" or simply "fewer tokens", with no way to
    # tell which. A control that varies two things at once is not a control.
    return "".join(out)[:target]


def post(url: str, payload: dict, headers: dict) -> tuple[dict, dict, float]:
    """POST and KEEP THE RESPONSE HEADERS.

    `routing/http_completion.py:_post_json` returns the decoded body and drops
    the headers, which is correct for a completion and useless here: the whole
    measurement lives in `x-ratelimit-remaining-tokens`. Duplicated on purpose
    rather than widening the production helper -- a measurement should not
    change the thing it measures.
    """
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8")
            hdrs = {k: v for k, v in r.headers.items() if HDR_RE.search(k)}
            return json.loads(raw), hdrs, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:400]
        hdrs = {k: v for k, v in e.headers.items() if HDR_RE.search(k)}
        # A 429 here is a RESULT, not a crash: it says the ceiling was reached
        # and the headers that come with it are the same evidence a 200 gives.
        return ({"__http_error__": e.code, "__body__": raw}, hdrs,
                time.monotonic() - t0)
    except Exception as e:                      # noqa: BLE001
        return ({"__error__": f"{type(e).__name__}: {e}"}, {},
                time.monotonic() - t0)


def payload_for(wire: str, model: str, prefix: str, question: str,
                supports: list) -> dict:
    """Build the request. The prefix goes FIRST and is byte-identical across
    calls A and B; only the trailing question differs. Caching is prefix-keyed,
    so a single varying byte ahead of the block would make every call a miss
    and the probe would report "no caching" for a rung that has it."""
    if wire == "openai_chat":
        p = {
            "model": model,
            "messages": [
                {"role": "system", "content": prefix},
                {"role": "user", "content": question},
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }
        if "reasoning_effort" in (supports or []):
            # Reasoning tokens are charged as completion tokens (measured: 57
            # of 64 on a seven-character answer). Left at default, the model
            # spends the whole reservation thinking and the accounting this
            # probe reads gets noisier for no gain.
            p["reasoning_effort"] = "low"
        return p
    if wire == "cf_responses":
        return {"input": prefix + "\n\n" + question, "max_tokens": MAX_TOKENS}
    raise ValueError(f"unhandled wire {wire}")


def usage_of(d: dict) -> dict:
    u = d.get("usage") or (d.get("result") or {}).get("usage") or {}
    det = u.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": u.get("prompt_tokens", u.get("input_tokens")),
        "completion_tokens": u.get("completion_tokens",
                                   u.get("output_tokens")),
        "cached_tokens": det.get("cached_tokens"),
        "raw_usage": u,
    }


def remaining_tokens(hdrs: dict) -> tuple[float | None, str | None]:
    """Pull the TOKEN bucket out of whatever the vendor called it.

    DELIBERATELY STRICT, AND IT RETURNS THE HEADER NAME IT USED. Vendors spell
    this differently (`x-ratelimit-remaining-tokens`, `...bysize-remaining`),
    and the tempting fix -- match any header containing "remaining" -- would
    match `x-ratelimit-remaining-requests` on most of them. A request counter
    read as a token bucket does not fail; it produces a confident headline off
    by three orders of magnitude, which is the worst outcome this probe has.

    So: "remaining" AND (a token or volume word) AND NOT "request". Where that
    finds nothing the caller reports NOT FOUND rather than zero, and the full
    header set is in the raw output so the real spelling can be read off the
    evidence instead of guessed at here.
    """
    for k, v in hdrs.items():
        kl = k.lower()
        if "remaining" not in kl or "request" in kl:
            continue
        if not any(w in kl for w in ("token", "size", "byte")):
            continue
        m = re.match(r"([\d.]+)", str(v).strip())
        if m:
            return float(m.group(1)), k
    return None, None


def run_provider(p: dict, args: dict) -> dict:
    pid = p["id"]
    cred = os.environ.get(p.get("credential_env", ""), "")
    if not cred:
        return {"id": pid, "skipped": f"{p.get('credential_env')} not set"}

    endpoint = p["endpoint"]
    if "{account}" in endpoint:
        acct = os.environ.get(p.get("account_env", ""), "")
        if not acct:
            return {"id": pid, "skipped": f"{p.get('account_env')} not set"}
        endpoint = endpoint.replace("{account}", acct)
    endpoint = endpoint.replace("{model}", p["model"])

    stable = build_prefix(seed=1, approx_tokens=args["prefix"])
    other = build_prefix(seed=2, approx_tokens=args["prefix"])

    words = ["alpha", "bravo", "delta", "echo", "foxtrot", "golf"]
    # Repeats before the control. SOME PROVIDERS ONLY CACHE A PREFIX THEY HAVE
    # ALREADY SEEN TWICE -- the first request populates, the second is the
    # first that can hit. A two-call probe cannot distinguish "no caching"
    # from "caching that starts on the third call", and would report the
    # stronger claim.
    calls = [(f"A{i}_repeat" if i else "A0_cold", stable,
              f"Reply with the single word: {words[i % len(words)]}.")
             for i in range(max(1, args["repeats"] - 1))]
    # THE NEGATIVE CONTROL, ALWAYS LAST. Same length, same shape, different
    # bytes, so a cache hit is impossible. If it shows the same discount the
    # repeats did, the repeats were never hits and this probe's headline is
    # wrong. A negative control that passes is a defect, not a relief.
    calls.append(("Z_control", other, "Reply with the single word: zulu."))

    results, prev_remaining, prev_t = [], None, None
    for idx, (label, prefix, question) in enumerate(calls):
        if idx and args["spacing"]:
            time.sleep(args["spacing"])
        pl = payload_for(p["wire"], p["model"], prefix, question,
                         p.get("supports", []))
        hdr = {"Authorization": f"Bearer {cred}"}
        t_start = time.monotonic()
        body, hdrs, elapsed = post(endpoint, pl, hdr)
        u = usage_of(body)
        rem, rem_header = remaining_tokens(hdrs)

        gap = None if prev_t is None else t_start - prev_t
        row = {
            "call": label,
            "elapsed_s": round(elapsed, 3),
            "gap_since_prev_s": None if gap is None else round(gap, 3),
            "http_error": body.get("__http_error__"),
            "error": body.get("__error__"),
            "prompt_tokens": u["prompt_tokens"],
            "completion_tokens": u["completion_tokens"],
            "cached_tokens": u["cached_tokens"],
            "remaining_tokens": rem,
            "remaining_header": rem_header,   # None = no token bucket reported
            # RAW, NOT CORRECTED. The bucket refilled during `gap`, so this
            # understates the charge by an unknown amount that `gap` bounds.
            # Both are reported; folding the correction in would hide the term
            # most likely to be wrong.
            "raw_remaining_drop": (None if rem is None or prev_remaining is None
                                   else round(prev_remaining - rem, 2)),
            "headers": hdrs,
        }
        results.append(row)
        prev_remaining = rem if rem is not None else prev_remaining
        prev_t = t_start

    return {"id": pid, "wire": p["wire"], "model": p["model"],
            "endpoint_host": endpoint.split("/")[2], "calls": results}


def parse_args(argv: list[str]) -> dict:
    """Parameters, because "no discount" is only ever true OF A SIZE.

    The first run measured a ~2,800-token prefix and found no discount
    anywhere. That is a real result and it is also exactly what a rung with a
    4,096-token minimum cache size would produce, so reporting it as "this
    provider does not cache" would be an overreach. Size and repeat count are
    therefore arguments, not constants: the same instrument re-run at a larger
    prefix either confirms the finding or overturns it, and re-running the
    instrument is the only thing that can tell them apart.

    `--spacing` exists because Mistral's binding limit is 4 REQUESTS per
    minute. Fired back to back the later calls 429 and the run reports a dead
    rung instead of a cache measurement.
    """
    a = {"prefix": PREFIX_TOKENS, "repeats": 3, "only": None, "spacing": 0.0,
         "tag": "default"}
    it = iter(argv)
    for tok in it:
        if tok == "--prefix-tokens":
            a["prefix"] = int(next(it))
        elif tok == "--repeats":
            a["repeats"] = int(next(it))
        elif tok == "--only":
            a["only"] = next(it)
        elif tok == "--spacing":
            a["spacing"] = float(next(it))
        elif tok == "--tag":
            a["tag"] = next(it)
        else:
            sys.exit(f"unknown argument {tok}")
    return a


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    load_secrets()
    supply = tomllib.loads(SUPPLY.read_text())
    rows = [p for p in supply["provider"]
            if p.get("egress_class") == "E1_PRIVATE"
            and p.get("wire") in ("openai_chat", "cf_responses")
            and p.get("purpose", "text") == "text"]
    if args["only"]:
        rows = [p for p in rows if p["id"] == args["only"]]
        if not rows:
            sys.exit(f"no E1_PRIVATE row with id {args['only']}")

    print(f"prefix target ~{args['prefix']} tok | max_tokens {MAX_TOKENS} | "
          f"{args['repeats']} calls x {len(rows)} private rungs | "
          f"spacing {args['spacing']}s\n")

    out = {"probe": "cache_discount", "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "prefix_target_tokens": args["prefix"], "max_tokens": MAX_TOKENS,
           "repeats": args["repeats"], "spacing_s": args["spacing"],
           "tag": args["tag"], "providers": []}

    for p in rows:
        print(f"--- {p['id']} ({p['wire']}) ---")
        r = run_provider(p, args)
        out["providers"].append(r)
        if "skipped" in r:
            print(f"    skipped: {r['skipped']}\n")
            continue
        for c in r["calls"]:
            bits = [f"{c['call']:10}"]
            if c["http_error"]:
                bits.append(f"HTTP {c['http_error']}")
            elif c["error"]:
                bits.append(c["error"][:60])
            bits.append(f"prompt={c['prompt_tokens']}")
            bits.append(f"cached={c['cached_tokens']}")
            rem_s = ("NOT-REPORTED" if c["remaining_tokens"] is None
                     else c["remaining_tokens"])
            bits.append(f"remaining={rem_s}")
            bits.append(f"drop={c['raw_remaining_drop']}")
            bits.append(f"gap={c['gap_since_prev_s']}s")
            print("    " + "  ".join(str(b) for b in bits))
        print()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # TAGGED PER RUN. Overwriting would destroy the small-prefix result the
    # moment a large-prefix run followed it, and the comparison between the
    # two IS the finding.
    dest = OUT.with_name(f"{OUT.stem}_{args['tag']}.json")
    dest.write_text(json.dumps(out, indent=2))
    print(f"raw -> {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
