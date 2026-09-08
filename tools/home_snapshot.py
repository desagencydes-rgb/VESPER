"""Build the home metrics card's projection from a real model call.

THE CARD HAS SAID `UNAVAILABLE` FIVE TIMES SINCE IT WAS DRAWN, and correctly:
`HomeChrome.swift` says so in its own header -- "a number with no producer
behind it is not a reading". This is the producer.

WHAT IT REFUSES TO DO. It does not compute a rate. `predicted_per_second` is
taken from the endpoint's own timings for the call that actually happened, and
where the endpoint does not report timings the reading is UNAVAILABLE with that
as the reason. A rate this tool derived from its own stopwatch would be a
measurement of Python, and SPIKE-001 is what measures throughput -- over
ten-minute runs, at a stated context, with a build tag. INV-HW-2 is about
exactly that difference.

EVERY READING CARRIES A TTL. A card showing the token rate of a call made four
hours ago is showing a number that renders identically to a fresh one, and
`core/projection.py` is explicit that stale and fresh must not be
indistinguishable. The readings expire and the card goes back to blank, which is
the honest end state for a system that is not currently doing anything.

`--probe` makes ONE real routed call to produce fresh evidence. Without it the
tool reads the last recorded call and lets the TTL decide. Probing on every
refresh would spend a request to keep a status line warm -- and on the API route
that is one of twenty for the day.

Stdlib only, per the convention for tools/.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.hlc import HLC                                       # noqa: E402
from core.projection import (HOME_METRIC_KEYS, Projection,     # noqa: E402
                             Reading)

STATE = Path.home() / "Library" / "Application Support" / "VESPER"
DEFAULT_OUT = STATE / "home.json"
EVIDENCE = STATE / "last-completion.json"

# Ten minutes. Long enough that the card is not blank while the owner is
# actually working, short enough that it cannot present a morning's number in
# the afternoon.
TTL_MS = 10 * 60 * 1000

LABELS = {
    "model.thinking": "thinking",
    "model.context_tokens": "context",
    "model.cache": "cache",
    "model.tokens_per_sec": "tokens",
    "host.power_source": "power",
}


def now_hlc() -> HLC:
    return HLC(physical_ms=int(time.time() * 1000), logical=0, node_id="macbook")


def power_source() -> Reading:
    """From `pmset`, which is the host's own answer rather than an inference."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception as e:                                     # noqa: BLE001
        return Reading.unavailable("host.power_source", "pmset", f"pmset: {e}")
    if "AC Power" in out:
        v = "AC"
    elif "Battery Power" in out:
        v = "battery"
    else:
        return Reading.unavailable("host.power_source", "pmset",
                                   "pmset reported neither AC nor battery")
    return Reading(key="host.power_source", source="pmset -g batt",
                   value=v, observed_at=now_hlc())


def probe() -> dict:
    """One real routed call, through the router and the cost choke point.

    Deliberately NOT a direct adapter call. The card is meant to show what
    VESPER's model path did, and a number produced by bypassing the router and
    the gateway would describe a path the product does not use.
    """
    import tempfile
    from core.bus import EventBus
    from core.cost import CostPolicy
    from core.gateway import ModelGateway
    from core.router import Router
    from core.store import StoreSet
    from routing.http_completion import build_provider, identify

    url = "http://127.0.0.1:8080"
    ident = identify(url, timeout=10.0)
    tmp = Path(tempfile.mkdtemp())
    clock = HLC.__new__(HLC)  # placeholder; the bus needs a real clock below
    from core.hlc import HybridLogicalClock
    clock = HybridLogicalClock("macbook")
    bus = EventBus(clock, StoreSet(tmp, node_id="macbook"), component="home")
    router = Router.from_spike_results(REPO / "docs/planning/spike-results", bus)
    d = router.select("trivial", host_ram_free_gb=6.0, task_id="home-probe")
    cost = CostPolicy(bus, clock)
    cost.register_credential("local", "free")
    gw = ModelGateway(bus, cost)
    gw.register(build_provider("local", d.profile_id, url, identity=ident))
    out = gw.complete("Say OK.", task_id="home-probe", profile_id=d.profile_id,
                      options={"n_predict": 200, "temperature": 0.0,
                               "enable_thinking": False})
    r = out["result"]
    ev = {
        "at_ms": int(time.time() * 1000),
        "profile_id": out["profile_id"],
        "endpoint": r["endpoint"],
        "tokens_predicted": r.get("tokens_predicted"),
        "tokens_evaluated": r.get("tokens_evaluated"),
        "tokens_cached": r.get("tokens_cached"),
        "predicted_per_second": r.get("predicted_per_second"),
        "reasoning_present": bool(r.get("reasoning")),
        "stop_reason": r.get("stop_reason"),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(ev, indent=1))
    return ev


def build(ev: dict | None) -> Projection:
    v = now_hlc()
    rs: list = [power_source()]

    if ev is None:
        why = ("no completion recorded on this host yet -- these four are read "
               "off a call VESPER actually made, so they arrive with the first "
               "answer and are never produced by anything else")
        rs += [Reading.unavailable(k, "completion", why)
               for k in ("model.thinking", "model.context_tokens",
                         "model.cache", "model.tokens_per_sec")]
        return Projection(version=v, readings={r.key: r for r in rs})

    ident = ev.get("endpoint") or {}
    src = ("last completion via "
           + str(ident.get("provider_id") or ident.get("build_info")
                 or ident.get("model") or ev.get("provider_id") or "unknown"))
    obs = HLC(physical_ms=ev["at_ms"], logical=0, node_id="macbook")

    # AN OLD COMPLETION BECOMES AN EXPLICIT ABSENCE, NOT A DISAPPEARING ROW.
    #
    # `to_rows` below and the identical loop in `tools/ops/vesper_runtime.py`
    # OMIT any reading whose stamp is past `TTL_MS`, because "a stale number
    # shown as current is worse than no number". That rule was written for
    # `power_source`, which is re-measured on every tick and therefore can only
    # go stale if the producer has died -- in which case vanishing is right.
    #
    # THESE FOUR ARE NOT LIKE THAT. They are the last completion, and there is
    # no completion to make while the owner is not asking anything, so ten
    # quiet minutes is normal rather than a fault. Left on the old rule the
    # rows silently disappear from the home shortly after every answer, which
    # is EXACTLY the complaint that started this work -- the owner said these
    # four "don't appear when vesper is working". So the staleness is caught
    # here instead, and rendered as a reason with the age in it: an absence
    # that explains itself cannot be mistaken for a current reading, which is
    # the whole thing the omit rule was protecting.
    age_ms = int(time.time() * 1000) - int(ev["at_ms"])
    if age_ms > TTL_MS:
        why = (f"the last completion was {age_ms // 60000} min ago; nothing "
               "has been asked since, so there is no newer measurement")
        rs += [Reading.unavailable(k, src, why)
               for k in ("model.thinking", "model.context_tokens",
                         "model.cache", "model.tokens_per_sec")]
        return Projection(version=v, readings={r.key: r for r in rs})

    rate = ev.get("predicted_per_second")
    rs.append(Reading.unavailable(
        "model.tokens_per_sec", src,
        "this endpoint reports no timings; a rate timed from here would "
        "measure the client, not the model")
        if rate is None else
        Reading(key="model.tokens_per_sec", source=src, value=round(rate, 1),
                unit="tok/s", observed_at=obs, ttl_ms=TTL_MS))

    ctx = ev.get("tokens_evaluated")
    rs.append(Reading.unavailable(
        "model.context_tokens", src, "endpoint reported no prompt token count")
        if ctx is None else
        Reading(key="model.context_tokens", source=src, value=int(ctx),
                unit="tok", observed_at=obs, ttl_ms=TTL_MS))

    cached = ev.get("tokens_cached")
    rs.append(Reading.unavailable(
        "model.cache", src,
        "endpoint reports no cache accounting, so a hit rate here would be "
        "invented")
        if cached is None else
        Reading(key="model.cache", source=src, value=int(cached),
                unit="tok cached", observed_at=obs, ttl_ms=TTL_MS))

    # ZERO IS A VALUE and so is False -- but "the wire never said" is NEITHER,
    # and reading this as a bool is how that third state got erased.
    #
    # This line used to be `"yes" if ev.get("reasoning_present") else "no"`,
    # which is correct only where a reasoning channel is reported at all. It is
    # not: `routing/supply.py::_normalise` reduces the openai wire to
    # `{text, stop_reason, usage}` and drops `message.reasoning` on the floor,
    # so a missing key and a model that did not think produced the same
    # confident `no`. `core/gateway.py::_reasoning` now returns None for the
    # third case and the count where one is reported, so a `no` here means the
    # provider said so.
    thought = ev.get("reasoning_present")
    if thought is None:
        rs.append(Reading.unavailable(
            "model.thinking", src,
            "this endpoint reports no reasoning channel and no reasoning token "
            "count, so whether the model thought is not observable from here"))
    else:
        n = ev.get("reasoning_tokens")
        rs.append(Reading(key="model.thinking", source=src,
                          value=(f"yes, {int(n)} tok" if thought and n
                                 else ("yes" if thought else "no")),
                          observed_at=obs, ttl_ms=TTL_MS))
    return Projection(version=v, readings={r.key: r for r in rs})


def main() -> int:
    out = (Path(sys.argv[sys.argv.index("--out") + 1])
           if "--out" in sys.argv else DEFAULT_OUT)
    ev = None
    if "--probe" in sys.argv:
        try:
            ev = probe()
        except Exception as e:                                 # noqa: BLE001
            print(f"probe failed: {e}", file=sys.stderr)
            print("continuing with the last recorded completion, if any",
                  file=sys.stderr)
    if ev is None and EVIDENCE.exists():
        ev = json.loads(EVIDENCE.read_text())

    proj = build(ev)
    scene = proj.to_scene("home-metrics", columns=HOME_METRIC_KEYS)
    # THE STAMP TRAVELS. See the same note in `tools/ops/vesper_runtime.py`:
    # dropping `observed_at` here left the surface unable to tell a reading
    # taken a second ago from one taken this morning.
    now_ms = int(time.time() * 1000)
    rows = []
    for e in scene.elements:
        at = e.content.get("observed_at") or {}
        at_ms = int(at.get("physical_ms") or 0) if isinstance(at, dict) else 0
        if at_ms and (now_ms - at_ms) > TTL_MS:
            continue
        rows.append({"label": LABELS.get(e.element_id, e.element_id),
                     "value": str(e.content["value"]),
                     "at_ms": at_ms, "ttl_ms": TTL_MS})
    # No stand-in runtime is started by this command. In-process-only state
    # remains UNAVAILABLE here; the running publisher supplies real objects.
    from tools.menu_snapshot import Collector
    state = (Path(sys.argv[sys.argv.index("--state-dir") + 1])
             if "--state-dir" in sys.argv else STATE)
    collector = Collector(state=state)
    menu_rows = collector.collect()
    rows.extend(menu_rows)
    # WRITTEN THROUGH `HomeState`, WHICH MERGES. This wrote the whole file --
    # `{"version": ..., "rows": ...}` over the top of `home.json` -- so running
    # the command the metrics card itself tells you to run DELETED the face,
    # the transcript, the workbench and the changes board. Measured 2026-09-06.
    #
    # `core/home_state.py` already owns that merge and says why in its own
    # header: "one file, one writer per key". It has had a `set_rows` for
    # exactly this since it was written, and nothing had ever called it.
    #
    # The `--out` escape hatch still writes a standalone file, because a
    # projection dumped somewhere for inspection is a different thing from the
    # surface's live state and must not need the merge.
    out.parent.mkdir(parents=True, exist_ok=True)
    if out == DEFAULT_OUT:
        from core.home_state import HomeState
        HomeState(path=out).set_rows(rows)
    else:
        out.write_text(json.dumps(
            {"version": proj.version.to_dict(), "rows": rows}, indent=1))

    print(f"{len(rows)} projected rows (5 host keys + 68 menu items) "
          f"-> {out}")
    for r in rows:
        print(f"  {r['label']:<10} {r['value']}")
    for k in HOME_METRIC_KEYS:
        r = proj.readings.get(k)
        if r is not None and not r.at(proj.version).known:
            print(f"  {LABELS.get(k, k):<10} (omitted) "
                  f"{r.unavailable_reason or 'expired'}")
    available = sum(r["status"] == "available" for r in menu_rows)
    print(f"menus: {available}/68 available; {68-available}/68 explicitly unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
