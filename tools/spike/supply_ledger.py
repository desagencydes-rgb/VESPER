#!/usr/bin/env python3.13
"""A record of which declared models still answer, updated by probing them.

THE GAP THIS FILLS. `probe_remote_supply.py` already refuses to trust a
provider's catalogue and calls each configured model directly -- a row whose
model does not answer is reported UNAVAILABLE. But the report is printed and
then lost. Nothing accumulates it, so "this model 404s now" has to be
rediscovered on every run, and a model silently retired by its vendor looks
identical to a transient outage.

WHAT IT MAY AND MAY NOT WRITE, and the line is not stylistic. Measured
availability is an OBSERVATION -- this endpoint answered, this one returned
404 -- and observations are exactly what the hardware rule wants recorded
rather than declared. Contract changes are a different act: removing a row from
the supply table, or changing a model id, is a reviewed decision. So this
writes only to its own ledger and has no path to `provider_supply.toml`. The
runtime may propose a contract change; it may never apply one.

A SINGLE FAILURE IS NOT A RETIREMENT, which is the whole reason a ledger beats
a boolean. A rung that 404s once may be having a bad minute; a rung that has
404'd on every probe for a week has been retired by its vendor. Only a series
distinguishes them, so the ledger keeps first_seen, last_ok, last_fail and
consecutive_fails rather than a current state -- and `verdict` is derived from
the series at read time, never stored.
"""
from __future__ import annotations

import json
import pathlib
import time

LEDGER = (pathlib.Path(__file__).resolve().parents[2]
          / "docs" / "spikes" / "data" / "supply_ledger.json")

# Consecutive failed probes before a row is CALLED retired rather than flaky.
# Not a guess about vendors -- a statement that one bad probe is never enough,
# and that the cost of being slow to declare a retirement (occasionally trying
# a dead rung) is far below the cost of being fast (retiring a live rung during
# an outage, which is exactly when the remaining rungs are most loaded).
RETIRED_AFTER = 5


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"schema_version": 1, "rows": {}}


def record(provider_id: str, model: str, ok: bool, detail: str = "") -> dict:
    led = load()
    key = f"{provider_id}::{model}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    r = led["rows"].setdefault(key, {
        "provider": provider_id, "model": model, "first_seen": now,
        "last_ok": None, "last_fail": None, "consecutive_fails": 0,
        "ok_count": 0, "fail_count": 0, "last_detail": "",
    })
    if ok:
        r["last_ok"] = now
        r["ok_count"] += 1
        r["consecutive_fails"] = 0
    else:
        r["last_fail"] = now
        r["fail_count"] += 1
        r["consecutive_fails"] += 1
    r["last_detail"] = detail[:200]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, indent=2))
    return r


def verdict(row: dict) -> str:
    """Derived at read time from the series, never stored.

    A stored verdict would freeze a judgement made when the series was shorter,
    and the next reader would inherit it without the evidence.
    """
    if row["consecutive_fails"] >= RETIRED_AFTER:
        return "RETIRED?"          # question mark: propose, do not apply
    if row["consecutive_fails"] > 0:
        return "FLAKY"
    if row["ok_count"] == 0:
        return "NEVER-SEEN"
    return "OK"


def report() -> int:
    led = load()
    rows = led.get("rows", {})
    if not rows:
        print("ledger empty -- run probe_remote_supply.py to populate it")
        return 0
    print(f"{'provider':<20} {'model':<34} {'verdict':<10} {'ok':>4} "
          f"{'fail':>5} {'streak':>7}  last ok")
    print("-" * 100)
    for r in sorted(rows.values(), key=lambda x: (x["provider"], x["model"])):
        v = verdict(r)
        print(f"{r['provider']:<20} {r['model'][:34]:<34} {v:<10} "
              f"{r['ok_count']:>4} {r['fail_count']:>5} "
              f"{r['consecutive_fails']:>7}  {r['last_ok'] or '-'}")
    prop = [r for r in rows.values() if verdict(r) == "RETIRED?"]
    if prop:
        print(f"\n{len(prop)} row(s) have failed {RETIRED_AFTER}+ consecutive "
              f"probes. That is a PROPOSAL to review the supply table,\nnot a "
              f"change to it -- removing a row is a reviewed act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(report())
