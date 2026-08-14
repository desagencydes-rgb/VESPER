"""Re-derives the SPIKE-001 3.1 aggregates from run_results already on disk.

WHY THIS EXISTS. schema_version 3 published two headline figures taken over
different windows: `median_sustained_tokens_per_sec` was the minute-10
generation rate, while `median_effective_tokens_per_sec` averaged the WHOLE run
on the wall clock. On a config that holds flat the two agree within about 1% and
the defect is invisible. On the Qwen3-30B MoE, which loses ~45% of its rate
between minute 1 and minute 10, the published wall figure came out 27% high --
8.63 tok/s against a settled 6.79 -- and that is the number a router would have
been calibrated on.

WHY IT RE-AGGREGATES RATHER THAN RE-MEASURES. The defect is in the summary, not
the measurement: every run already carries `sustained_effective_tokens_per_sec`,
the minute-10 wall rate, and it was simply never aggregated. The raw samples are
correct and untouched. Re-running the matrix would cost about six hours and
produce the same run_results, so the honest fix is to recompute the summary and
say so in the file.

Idempotent: a report already at the target schema version is left alone.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

TARGET_SCHEMA = 4
RESULTS = Path(__file__).resolve().parents[2] / "docs" / "planning" / "spike-results"

CORRECTION = (
    "Aggregates re-derived from this file's own run_results by "
    "tools/spike/reaggregate.py. The samples are unchanged and were never wrong. "
    "What changed: median_effective_tokens_per_sec is now the median of the "
    "per-run minute-10 wall rate (sustained_effective_tokens_per_sec), matching "
    "the window median_sustained_tokens_per_sec already used. Under "
    "schema_version 3 it was the whole-run average, which sits above the settled "
    "rate by however much the model decays across the run. The whole-run figure "
    "is retained under median_whole_run_effective_tokens_per_sec."
)


def _vals(runs: list[dict], key: str) -> list[float]:
    return [r[key] for r in runs if r.get(key) is not None]


def _agg(result: dict, runs: list[dict]) -> bool:
    """Rewrite result's aggregate fields in place. True if anything changed."""
    sustained = _vals(runs, "sustained_tokens_per_sec")
    settled = _vals(runs, "sustained_effective_tokens_per_sec")
    whole = _vals(runs, "effective_tokens_per_sec")
    if not settled:
        return False

    before = result.get("median_effective_tokens_per_sec")

    if sustained:
        result["median_sustained_tokens_per_sec"] = round(statistics.median(sustained), 2)
        result["spread_tokens_per_sec"] = {
            "min": round(min(sustained), 2), "max": round(max(sustained), 2),
            "values": sustained,
        }
    result["median_effective_tokens_per_sec"] = round(statistics.median(settled), 2)
    result["spread_effective_tokens_per_sec"] = {
        "min": round(min(settled), 2), "max": round(max(settled), 2), "values": settled,
    }
    result["effective_window"] = (
        "minute 10 -- the same window as median_sustained_tokens_per_sec, so the "
        "two are comparable to each other."
    )
    if whole:
        result["median_whole_run_effective_tokens_per_sec"] = round(statistics.median(whole), 2)
        result["spread_whole_run_effective_tokens_per_sec"] = {
            "min": round(min(whole), 2), "max": round(max(whole), 2), "values": whole,
        }
        result["whole_run_vs_settled_note"] = (
            "median_whole_run_effective_tokens_per_sec averages the entire run, "
            "including the fast early minutes. It is ABOVE the settled rate by "
            "however much the model decays. Do not quote it as a sustained figure."
        )
    result["aggregate_correction"] = CORRECTION
    result["superseded_median_effective_tokens_per_sec"] = before
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glob", default="SPIKE-001-3.1-v3-*.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(RESULTS.glob(args.glob))
    if not files:
        print(f"no reports matched {args.glob} in {RESULTS}", file=sys.stderr)
        return 1

    changed = 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("schema_version", 0) >= TARGET_SCHEMA:
            print(f"  skip (already v{d['schema_version']}): {f.name}")
            continue
        t = d.get("throughput")
        if not isinstance(t, dict) or not t.get("run_results"):
            print(f"  skip (no run_results): {f.name}")
            continue

        before = t.get("median_effective_tokens_per_sec")
        if not _agg(t, t["run_results"]):
            print(f"  skip (no settled wall rate in any run): {f.name}")
            continue
        after = t["median_effective_tokens_per_sec"]
        d["schema_version"] = TARGET_SCHEMA

        delta = "" if not before else f"  ({(after - before) / before * 100:+.1f}%)"
        print(f"  {f.name}: wall {before} -> {after}{delta}")
        if not args.dry_run:
            f.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        changed += 1

    print(f"\n{changed} report(s) re-aggregated{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
