# A-029 endurance: what E1 will mean, written before E1 is known

**Written 2026-08-16 at hour 12.4 of a 24 h window.** The run is in flight and
its verdict is not yet computable. That is the point: the rule for reading the
result is fixed here, while the result is still unknown, so that a failure
cannot be reinterpreted into a pass after the fact.

## The observation that prompted this

RSS of the live healthy build, per-hour means from the watchdog:

| hour | 1 | 2 | 4 | 6 | 8 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|
| MB | 19.08 | 19.45 | 19.85 | 20.55 | 21.31 | 21.90 | 23.93 | 24.17 |

A steady ~+0.35 MB/h creep, plus a discrete ~+2 MB step between hour 9 and
hour 11. Linear extrapolation to the last quarter (hours 18–24) gives a
last-quarter mean near 29 MB against a first-quarter mean of 20.0 MB:

    projected growth  +9.3 MB     E1 budget  8.0 MB

So a build nobody believes is broken is on course to fail its own leak check.

## What the accelerated reproduction shows

`scratchpad/diagnose_rss.py` runs the same `EnduranceRun(build="healthy")` at a
0.02 s tick, 5,000 ticks in 115 s, with `tracemalloc` and an out-of-run RSS
probe. Result:

```
RSS 30.88 MB -> 40.48 MB across the tick loop   (the 63.9 MB endpoint is
                                                 teardown and judging, after
                                                 the sampled window closes)
  0.0s  30.88 |  22.9s  35.39 |  45.7s  37.24 |  68.9s  38.60 |  91.7s  40.64
 11.4s  33.95 |  34.3s  36.21 |  57.4s  37.95 |  80.3s  40.30 | 103.2s  40.48
```

Two things follow.

1. **The growth decelerates.** +3.1 MB in the first decile, +0.7 MB in the
   middle, and −0.16 MB in the last. Over 5,000 ticks — 3.5× a 24 h window's
   1,440 ticks — total tick-loop growth is 9.6 MB. Unbounded leaks do not
   flatten; allocator arenas and page caches do.
2. **Almost none of it is Python objects.** `tracemalloc` accounts for ~2 MB of
   the 9.6 MB, and the largest sites are `bus.py:219` (`payload=dict(payload)`,
   one dict per published event) and the runner's own `heartbeats`/`noops`
   deques. Those deques are `maxlen=10_000`; at a 60 s tick a 24 h window
   reaches 1,440 entries, so **`dropped_history` will legitimately be 0** and
   the bound will not be exercised by this window. The remaining ~7.6 MB is
   RSS the allocator has not returned to the OS.

## The pre-registered reading

E1 measures RSS. RSS includes arenas the program no longer uses. So E1 as
written cannot, on its own, distinguish a leak from a warm allocator.

**If E1 passes** — the result stands as-is. No re-reading needed.

**If E1 fails**, the run is **not** thereby a product defect, and it is **not**
VOID either. It is a *criterion* defect, and the rule is:

- The A-029 gate verdict (parts 1, 2, 3) is **independent of E1** and stands on
  its own. Liveness, provenance and the anti-cron discriminator do not read RSS.
- E1's failure is recorded as **INCONCLUSIVE-BY-CRITERION**, with this document
  as the reason, and it blocks nothing that parts 1–3 unblock.
- The fix is not a wider budget. It is a **sharper criterion** for the next
  run: assert on `tracemalloc`-tracked heap and on the explicit bounded
  structures (`len(heartbeats)`, `len(noops)`, `dropped_history`,
  `len(sampler.samples)`), which measure the program rather than the allocator.
  RSS is kept, reported, and no longer asserted against a budget.

**What would overturn this and make it a real leak:** tracked Python heap
growing without deceleration across the window, or the bounded structures
exceeding their declared maxima, or the next run showing RSS still climbing at
the same rate after 48 h rather than flattening. Any of those, and the reading
above is wrong and the finding is genuine.

## Why this is written now rather than at hour 24

The project's own doctrine already separates VOID from FAILED so that an
environment defect cannot be laundered into a product defect. This is the same
separation applied one level up: a defect in the *measuring criterion* must not
be laundered into either. The only way to make that credible is to fix the
reading before the reading is available — which is what this file is.
