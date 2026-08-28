#!/usr/bin/env python3.13
"""Does a SHORTENED version of a cached prefix still hit the cache?

THE CLAIM UNDER TEST, and it is mine. The design sends the same resident block
at different lengths to different rungs -- the full block to a rung with room,
a truncated one to a rung without. That only works if a truncation of a cached
prefix is itself a cache hit. I asserted it with the phrase "a truncated prefix
is still a prefix" and never checked it. It is entry U1 in the open-questions
register.

WHY IT MIGHT BE FALSE. Prefix caches are commonly keyed on BLOCKS of tokens
rather than on the raw byte stream -- a hash per fixed-size chunk. Under that
scheme a truncation lands mid-block and the final partial block misses, which
is harmless. But some implementations key on the whole prefix, or on its
length, and there the truncation misses ENTIRELY. The two are indistinguishable
from the outside, and the difference decides whether per-rung sizing works at
all or whether every rung needs its own cache entry paid for separately.

THE SHAPE. Three calls:

  1. FULL      -- the whole block, cold. Populates whatever gets populated.
  2. FULL AGAIN -- the POSITIVE CONTROL, and the first version of this probe
                 did not have it. Without it a miss on the truncation is
                 uninterpretable: "truncation does not hit" and "the cache
                 never populated on this run" produce byte-identical output.
                 That is not hypothetical here -- of two identical repeats
                 measured on 2026-08-28, one hit and one did not, so an
                 unpopulated cache is a live possibility on any given run and
                 the probe MUST prove population before testing anything else.
  3. TRUNC     -- the first 50% of exactly those bytes. If truncation hits, the
                 cached count should be ~half, not zero.
  4. CONTROL   -- a DIFFERENT block of the same truncated length. Cannot be a
                 hit. If this reports cached tokens, reading (3) proves nothing.

TWO CONTROLS, IN OPPOSITE DIRECTIONS, and the probe is only interpretable when
both behave. (2) must hit or the run is void. (4) must miss or the run is void.
Only between those two does (3) mean anything.
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

OUT = ROOT / "docs" / "spikes" / "data" / "cache_truncation_probe.json"
FULL_TOKENS = 5_000        # ~8.2k real tokens on Mistral, above the observed
                           # discount point
GAP_S = 20.0               # the discount was observed at a 17 s gap; stay above


def main() -> int:
    pid = sys.argv[1] if len(sys.argv) > 1 else "mistral-standard"
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

    full = build_prefix(seed=41, approx_tokens=FULL_TOKENS)
    # EXACT byte prefix of `full`, not a re-generation at half the size. A
    # regenerated half would differ in content as well as length and could not
    # distinguish truncation from a plain miss.
    trunc = full[: len(full) // 2]
    other = build_prefix(seed=42, approx_tokens=FULL_TOKENS)[: len(full) // 2]
    assert full.startswith(trunc) and len(other) == len(trunc)
    assert not full.startswith(other)

    plan = [("1_full", full, "alpha"),
            ("2_full_again", full, "bravo"),      # positive control
            ("3_truncated", trunc, "delta"),
            ("4_control", other, "echo")]         # negative control
    results = []
    for i, (label, text, word) in enumerate(plan):
        if i:
            time.sleep(GAP_S)
        pl = payload_for(row["wire"], row["model"], text,
                         f"Reply with the single word: {word}.",
                         row.get("supports", []))
        body, hdrs, elapsed = post(ep, pl, hdr)
        u = usage_of(body)
        rem, _ = remaining_tokens(hdrs)
        r = {"call": label, "chars": len(text), "prompt_tokens": u["prompt_tokens"],
             "cached_tokens": u["cached_tokens"],
             "query_cost": hdrs.get("x-ratelimit-tokens-query-cost"),
             "remaining": rem, "elapsed_s": round(elapsed, 3),
             "error": body.get("__http_error__") or body.get("__error__")}
        results.append(r)
        print(f"  {label:12} chars={len(text):6} prompt={r['prompt_tokens']} "
              f"cached={r['cached_tokens']} cost={r['query_cost']}"
              + (f"  ERR {r['error']}" if r["error"] else ""), flush=True)

    _fu, pos, tr, neg = results
    print()
    # THE CONTROLS ARE CHECKED BEFORE THE RESULT IS READ, not after. Reading
    # the interesting number first and only then asking whether the run was
    # valid is how a void run becomes a finding.
    if not pos["cached_tokens"]:
        print("  VOID — the positive control did not hit, so the cache never "
              "populated on\n  this run. The truncation result says nothing. "
              "Re-run; do not record a\n  finding from this.")
    elif neg["cached_tokens"]:
        print("  VOID — the negative control reported cached tokens, so a hit "
              "is not\n  evidence of prefix reuse on this provider.")
    elif tr["cached_tokens"]:
        share = tr["cached_tokens"] / max(1, tr["prompt_tokens"])
        print(f"  TRUNCATION HITS — {tr['cached_tokens']} of "
              f"{tr['prompt_tokens']} cached ({share:.0%}).\n"
              f"  Positive control hit {pos['cached_tokens']}, negative "
              f"control {neg['cached_tokens']}.\n"
              f"  Per-rung sizing of one block works.")
    else:
        print(f"  TRUNCATION MISSES — charged in full, while the positive "
              f"control hit\n  {pos['cached_tokens']} tokens on the same run. "
              f"Both controls behaved, so this\n  is a real result: every rung "
              f"needs its own cache entry, paid separately.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"probe": "cache_truncation", "provider": pid,
         "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "full_tokens_target": FULL_TOKENS, "gap_s": GAP_S,
         "calls": results}, indent=2))
    print(f"\nraw -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
