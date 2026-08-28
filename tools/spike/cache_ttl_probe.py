#!/usr/bin/env python3.13
"""Cache TTL, and size-vs-waiting, measured as a GRID with one variable moving.

WHY THIS EXISTS. `cache_discount_probe.py` found a repeated 8,249-token prefix
charged 30 tokens instead of 8,249 -- and its two runs changed prefix size AND
inter-call gap together, so which one buys the discount is unknown. This probe
moves one at a time.

THE TRAP THIS AVOIDS, AND IT IS THE WHOLE DESIGN. The obvious TTL probe sends
one prefix and re-sends it at 1, 5, 15 and 25 minutes, watching for the hit to
stop. That measures nothing, because **every access refreshes the entry**. The
30-second re-send resets the clock the 5-minute re-send is trying to read, so
the series reports "still cached" at every gap and concludes the TTL is longer
than the run -- which is the answer it would give for ANY TTL above 30 seconds.

So each cell gets its OWN prefix, touched exactly twice: once cold, once at its
gap. Seven independent experiments, interleaved to save wall time, no cell
observing another.

THE GRID. Two series sharing one cell:

    TTL series   size fixed at ~8k, gaps 60s / 300s / 900s / 1500s
    SIZE series  gap fixed at 60s, sizes ~1k / 2k / 4k / 8k

The 8k-at-60s cell belongs to both, so seven cells cover eight readings.

RATE. Mistral binds on 4 REQUESTS/min, not tokens (250,000/min, measured). The
scheduler therefore paces on requests and ignores volume; a token-paced version
of this would fire four calls in a second and read the 429 as a dead rung.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cache_discount_probe import (           # noqa: E402
    SUPPLY, ROOT, MAX_TOKENS, build_prefix, load_secrets, payload_for,
    post, remaining_tokens, usage_of,
)
import tomllib                               # noqa: E402

OUT = ROOT / "docs" / "spikes" / "data" / "cache_ttl_probe.json"
MIN_REQUEST_SPACING_S = 21.0     # 4 req/min is the ceiling; 21s keeps any 60s window at 3

# (cell name, approx prefix tokens, gap seconds)
CELLS = [
    ("ttl_60",    5_000,    60),   # shared with size_8k
    ("ttl_300",   5_000,   300),
    ("ttl_900",   5_000,   900),
    ("ttl_1500",  5_000,  1500),
    ("size_1k",     600,    60),
    ("size_2k",   1_250,    60),
    ("size_4k",   2_500,    60),
]


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else "mistral-standard"
    load_secrets()
    supply = tomllib.loads(SUPPLY.read_text())
    row = next((p for p in supply["provider"] if p["id"] == only), None)
    if row is None:
        sys.exit(f"no provider row {only}")

    import os
    cred = os.environ.get(row.get("credential_env", ""), "")
    if not cred:
        sys.exit(f"{row.get('credential_env')} not set")
    endpoint = row["endpoint"].replace("{model}", row["model"])
    hdr = {"Authorization": f"Bearer {cred}"}

    def call(cell: str, phase: str, prefix: str, word: str) -> dict:
        pl = payload_for(row["wire"], row["model"], prefix,
                         f"Reply with the single word: {word}.",
                         row.get("supports", []))
        body, hdrs, elapsed = post(endpoint, pl, hdr)
        u = usage_of(body)
        rem, rem_hdr = remaining_tokens(hdrs)
        # Mistral states the cost outright rather than leaving it to be inferred
        # from a difference between two observations. Prefer it where present.
        cost = hdrs.get("x-ratelimit-tokens-query-cost")
        r = {"cell": cell, "phase": phase, "t": round(time.monotonic() - t0, 1),
             "prompt_tokens": u["prompt_tokens"], "cached_tokens": u["cached_tokens"],
             "query_cost": cost, "remaining": rem, "remaining_header": rem_hdr,
             "elapsed_s": round(elapsed, 3),
             "http_error": body.get("__http_error__"), "error": body.get("__error__")}
        print(f"  [{r['t']:>7.1f}s] {cell:9} {phase:6} "
              f"prompt={str(r['prompt_tokens']):5} cached={str(r['cached_tokens']):5} "
              f"cost={cost}" + (f"  ERR {r['http_error'] or r['error']}"
                                if r["http_error"] or r["error"] else ""),
              flush=True)
        return r

    # Each cell gets a distinct prefix. `seed` differs per cell so no two cells
    # share a cache entry -- two cells on one entry would make the second cell's
    # cold call a hit and the grid would read as "cached at every size".
    prefixes = {c: build_prefix(seed=100 + i, approx_tokens=n)
                for i, (c, n, _) in enumerate(CELLS)}

    # Schedule: every cold first (paced by the request limit), each repeat at
    # its own gap after its own cold. Sorted into one timeline so the waits
    # overlap instead of running end to end.
    events, t_cold = [], 0.0
    for i, (cell, _, gap) in enumerate(CELLS):
        t_cold = i * MIN_REQUEST_SPACING_S
        events.append((t_cold, cell, "cold"))
        events.append((t_cold + gap, cell, "repeat"))
    events.sort()

    t0 = time.monotonic()
    results, last_call = [], -1e9
    print(f"{len(CELLS)} cells, {len(events)} calls, "
          f"~{events[-1][0]/60:.0f} min wall\n", flush=True)
    for when, cell, phase in events:
        target = t0 + when
        while time.monotonic() < target:
            time.sleep(min(2.0, target - time.monotonic()))
        # Never let the schedule violate the request limit, even where two
        # events land close together.
        gap_needed = MIN_REQUEST_SPACING_S - (time.monotonic() - last_call)
        if gap_needed > 0:
            time.sleep(gap_needed)
        word = "alpha" if phase == "cold" else "bravo"
        results.append(call(cell, phase, prefixes[cell], word))
        last_call = time.monotonic()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"probe": "cache_ttl_and_size", "provider": only,
         "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "cells": [{"cell": c, "approx_tokens": n, "gap_s": g}
                   for c, n, g in CELLS],
         "calls": results}, indent=2))
    print(f"\nraw -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
