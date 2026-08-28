#!/usr/bin/env python3.13
"""How often does an identical repeat ACTUALLY hit the cache?

WHY THIS OUTRANKS EVERY OTHER CACHE QUESTION. The resident-memory design was
justified by a measured 99.6% discount: 8,224 of 8,250 tokens served from cache,
charged 30 against the rate limit. That number is real and it was observed once.
Since then the same call at the same size and gap has missed twice.

A discount that arrives one time in three is not a 99.6% discount. The figure
that matters is EXPECTED cost -- size x P(miss) -- and at a 33% hit rate an
8,000-token resident block costs ~5,300 tokens per turn on average, not 30. On
a rung whose entire allowance is 8,000 tokens per minute, those two numbers
imply completely different architectures.

MEASURING IT NEEDS INDEPENDENT PAIRS. Repeating one prefix N times measures
something else: every call after the first re-populates the entry, so a long
run converges on "cached" regardless of how unreliable population is. Each pair
therefore uses its OWN prefix -- cold, then repeat -- and no pair can benefit
from another's population.

A MISS IS ALSO A MEASUREMENT. Runs that miss are counted, not discarded and
retried until a hit appears. Retrying until the expected result shows up is how
a 33% effect becomes a reported 100% one.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cache_discount_probe import (        # noqa: E402
    ROOT, SUPPLY, build_prefix, load_secrets, payload_for, post,
    remaining_tokens, usage_of,
)

OUT = ROOT / "docs" / "spikes" / "data" / "cache_hitrate_probe.json"
_OUT_BASE = OUT
PAIRS = 10
PREFIX_TOKENS = 5_000      # ~8.2k real on Mistral, the size that hit before
GAP_S = 20.0               # within-pair gap
PACE_S = 21.0              # between calls; Mistral binds at 4 requests/min


def main() -> int:
    pid = sys.argv[1] if len(sys.argv) > 1 else "mistral-standard"
    pairs = int(sys.argv[2]) if len(sys.argv) > 2 else PAIRS
    # PACING IS PER RUNG AND MUST COME FROM ITS MEASURED CEILING. Groq binds on
    # 8,000 tokens/min and refills ~133/sec, so after a 6,300-token call it
    # needs ~35 s before it can afford another. Firing at Mistral's pace would
    # 429 mid-run, and a 429 is indistinguishable in this output from a rung
    # that does not cache -- which is the exact question being asked.
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else GAP_S
    pace = float(sys.argv[4]) if len(sys.argv) > 4 else PACE_S
    tok = int(sys.argv[5]) if len(sys.argv) > 5 else PREFIX_TOKENS
    load_secrets()
    supply = tomllib.loads(SUPPLY.read_text())
    row = next((p for p in supply["provider"] if p["id"] == pid), None)
    if row is None:
        sys.exit(f"no provider {pid}")
    cred = os.environ.get(row.get("credential_env", ""), "")
    if not cred:
        sys.exit(f"{row.get('credential_env')} not set")
    ep = row["endpoint"].replace("{model}", row["model"])
    hdr = {"Authorization": f"Bearer {cred}"}

    def call(text: str, word: str) -> dict:
        pl = payload_for(row["wire"], row["model"], text,
                         f"Reply with the single word: {word}.",
                         row.get("supports", []))
        body, hdrs, elapsed = post(ep, pl, hdr)
        u = usage_of(body)
        rem, _ = remaining_tokens(hdrs)
        return {"prompt_tokens": u["prompt_tokens"],
                "cached_tokens": u["cached_tokens"],
                "query_cost": hdrs.get("x-ratelimit-tokens-query-cost"),
                "remaining": rem, "elapsed_s": round(elapsed, 3),
                "error": body.get("__http_error__") or body.get("__error__")}

    print(f"{pairs} independent pairs on {pid}, ~{tok} target tokens,"
          f" {gap:.0f}s within pair, {pace:.0f}s pace\n", flush=True)
    results, last = [], 0.0
    for i in range(pairs):
        # Each pair its own prefix: no pair can be warmed by another.
        text = build_prefix(seed=500 + i, approx_tokens=tok)
        while time.monotonic() - last < pace:
            time.sleep(0.5)
        cold = call(text, "alpha"); last = time.monotonic()
        time.sleep(max(0.0, gap - (time.monotonic() - last)))
        while time.monotonic() - last < pace:
            time.sleep(0.5)
        warm = call(text, "bravo"); last = time.monotonic()

        hit = bool(warm["cached_tokens"])
        results.append({"pair": i, "cold": cold, "warm": warm, "hit": hit})
        print(f"  pair {i:>2}  cold prompt={cold['prompt_tokens']} "
              f"cached={cold['cached_tokens']}   "
              f"warm prompt={warm['prompt_tokens']} "
              f"cached={warm['cached_tokens']} cost={warm['query_cost']}  "
              f"{'HIT' if hit else 'miss'}", flush=True)

    ok = [r for r in results if not r["warm"]["error"] and not r["cold"]["error"]]
    hits = [r for r in ok if r["hit"]]
    n = len(ok)
    rate = len(hits) / n if n else 0.0
    size = sum(r["warm"]["prompt_tokens"] or 0 for r in ok) / max(1, n)
    charged = []
    for r in ok:
        c = r["warm"]["query_cost"]
        if c is not None:
            charged.append(float(c))
    expected = sum(charged) / len(charged) if charged else None

    print(f"\n  pairs usable        {n}")
    print(f"  hits                {len(hits)}")
    print(f"  HIT RATE            {rate:.0%}")
    print(f"  mean prompt size    {size:,.0f} tokens")
    if expected is not None:
        print(f"  MEAN ACTUAL CHARGE  {expected:,.0f} tokens per repeat")
        print(f"  vs {size:,.0f} with no cache, and "
              f"~30 if every repeat hit")
        print(f"\n  Effective discount across all attempts: "
              f"{100*(1-expected/size):.0f}%  (not the 99.6% one lucky call showed)")

    OUT_P = _OUT_BASE.with_name(f"cache_hitrate_{pid}.json")
    OUT_P.parent.mkdir(parents=True, exist_ok=True)
    OUT_P.write_text(json.dumps(
        {"probe": "cache_hitrate", "provider": pid,
         "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "pairs": pairs,
         "gap_s": gap, "pace_s": pace, "prefix_target": tok, "hit_rate": rate, "mean_prompt_tokens": size,
         "mean_charge": expected, "results": results}, indent=2))
    print(f"\nraw -> {OUT_P.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
