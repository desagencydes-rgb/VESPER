#!/usr/bin/env python3.13
"""Latency DISTRIBUTIONS per rung, because single observations have lied twice.

WHY THIS EXISTS. The routing design placed the chooser on the fastest rung and
named Mistral as failover, on the strength of four calls. Hours later the same
call to the same rung with the same payload measured 0.84 s, then 115 s, then
timed out. A median from four samples is decoration; what a latency budget has
to survive is the TAIL, and the tail is invisible at small n.

WHAT IT DELIBERATELY DOES NOT DO. It does not compute a headline "provider
speed". A rate quoted without saying which percentile it is, over what window,
at what payload size, is two different numbers wearing one label -- and the
first version of the cache probe made exactly that mistake by changing two
variables at once. Every sample carries its timestamp and payload size so the
distribution can be recut later without re-spending quota.

PACING IS PER ROW AND CONSERVATIVE. Mistral binds on 4 requests/min; Cloudflare
bills a daily neuron pool that a tight loop would drain in an afternoon; Groq
binds on tokens. One pace per rung, each set below its own ceiling, because a
429 in the middle of a latency sweep is indistinguishable in the output from a
rung that went down -- which is the very confusion this probe exists to remove.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cache_discount_probe import (        # noqa: E402
    ROOT, SUPPLY, load_secrets, payload_for, post, remaining_tokens, usage_of,
)

OUT = ROOT / "docs" / "spikes" / "data" / "latency_sweep.json"

# Seconds between calls, per rung. Set from the MEASURED binding constraint,
# not the published one: Mistral's 4 req/min is the real ceiling and 25 s keeps
# any 60-second window at 3.
PACE = {
    "groq-strong": 20.0,
    "mistral-standard": 25.0,
    "ollama-strong": 30.0,
    "cf-strong": 120.0,      # daily neuron pool, not a rate -- probe sparsely
}
# Small payload on purpose. This measures the rung's RESPONSE behaviour, not
# how long it takes to read a large prompt; prompt-size effects were measured
# separately and mixing them would confound this the way the first cache probe
# was confounded.
PROMPT = ("Answer with one word: what colour is a clear midday sky? "
          "Do not explain.")
MAX_TOKENS = 16


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    only = sys.argv[2:] or None
    load_secrets()
    supply = tomllib.loads(SUPPLY.read_text())
    rows = [p for p in supply["provider"]
            if p.get("egress_class") == "E1_PRIVATE"
            and p.get("wire") in ("openai_chat", "cf_responses")
            and p.get("purpose", "text") == "text"
            and (only is None or p["id"] in only)]

    live = []
    for p in rows:
        cred = os.environ.get(p.get("credential_env", ""), "")
        if not cred:
            print(f"skip {p['id']}: no credential"); continue
        ep = p["endpoint"]
        if "{account}" in ep:
            acct = os.environ.get(p.get("account_env", ""), "")
            if not acct:
                print(f"skip {p['id']}: no account id"); continue
            ep = ep.replace("{account}", acct)
        live.append((p, ep.replace("{model}", p["model"]), cred,
                     PACE.get(p["id"], 30.0)))

    print(f"{len(live)} rungs, {minutes:.0f} min\n", flush=True)
    t0 = time.monotonic()
    deadline = t0 + minutes * 60
    next_at = {p["id"]: t0 for p, _, _, _ in live}
    samples: dict[str, list] = {p["id"]: [] for p, _, _, _ in live}

    while time.monotonic() < deadline:
        now = time.monotonic()
        due = [x for x in live if next_at[x[0]["id"]] <= now]
        if not due:
            time.sleep(min(2.0, max(0.2, min(next_at.values()) - now)))
            continue
        for p, ep, cred, pace in due:
            pid = p["id"]
            pl = payload_for(p["wire"], p["model"], PROMPT, "",
                             p.get("supports", []))
            body, hdrs, elapsed = post(ep, pl, {"Authorization": f"Bearer {cred}"})
            u = usage_of(body)
            rem, _ = remaining_tokens(hdrs)
            err = body.get("__http_error__") or body.get("__error__")
            samples[pid].append({
                "t": round(time.monotonic() - t0, 1),
                "elapsed_s": round(elapsed, 3),
                "prompt_tokens": u["prompt_tokens"],
                "completion_tokens": u["completion_tokens"],
                "remaining": rem,
                "error": str(err) if err else None,
            })
            next_at[pid] = time.monotonic() + pace
            if err:
                print(f"  [{samples[pid][-1]['t']:>6.0f}s] {pid:18} "
                      f"{elapsed:6.2f}s  ERR {str(err)[:60]}", flush=True)

    out = {"probe": "latency_sweep", "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "minutes": minutes, "prompt_tokens_target": len(PROMPT) // 4,
           "samples": samples, "summary": {}}

    print(f"\n{'rung':<18} {'n':>4} {'ok':>4} {'p50':>8} {'p90':>8} "
          f"{'p99':>8} {'max':>8}  errors")
    print("-" * 74)
    for pid, xs in samples.items():
        good = sorted(s["elapsed_s"] for s in xs if not s["error"])
        errs = [s for s in xs if s["error"]]
        if not good:
            print(f"{pid:<18} {len(xs):>4} {0:>4}  no successful calls")
            out["summary"][pid] = {"n": len(xs), "ok": 0,
                                   "errors": len(errs)}
            continue

        def pct(q):
            return good[min(len(good) - 1, int(len(good) * q))]
        s = {"n": len(xs), "ok": len(good), "errors": len(errs),
             "p50": round(statistics.median(good), 3), "p90": round(pct(.90), 3),
             "p99": round(pct(.99), 3), "max": round(good[-1], 3),
             # THE RATIO IS THE POINT. A rung whose worst call is 3x its median
             # is usable behind a timeout; one at 100x is not, whatever its
             # median says, and the median is what a small sample reports.
             "tail_ratio": round(good[-1] / statistics.median(good), 1)}
        out["summary"][pid] = s
        print(f"{pid:<18} {s['n']:>4} {s['ok']:>4} {s['p50']:>7.2f}s "
              f"{s['p90']:>7.2f}s {s['p99']:>7.2f}s {s['max']:>7.2f}s"
              f"  {s['errors']}  (worst/median {s['tail_ratio']}x)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nraw -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
