#!/usr/bin/env python3
"""End-to-end: a real request crossing the real ladder, against live providers.

WHAT THIS PROVES THAT NOTHING ELSE DOES. Every other gate in this repo runs
against doubles, and correctly so -- they must run in a cloud session with no
credentials. This one runs ONLY on the owner's machine, spends real quota, and
answers the one question the doubles cannot: does a request actually cross this
system and come back with an answer.

`MULTI_ROUTE.md` SS13 exists because four designs that read correctly were
falsified the first time a real call was made. This script is where the fifth
would be found.

IT SPENDS REAL QUOTA, so it is small by construction: a handful of short
prompts, never a loop. Run it to confirm the ladder works, not to benchmark it.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.bus import EventBus                                    # noqa: E402
from core.cost import CostPolicy                                 # noqa: E402
from core.gateway import AllProvidersExhausted, ModelGateway     # noqa: E402
from core.hlc import HybridLogicalClock                          # noqa: E402
from core.quota import QuotaLedger                               # noqa: E402
from core.store import StoreSet                                  # noqa: E402
from routing import supply                                       # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"\n         {detail}" if detail else ""))


def wiring(tmp: Path, node: str = "supply-acceptance"):
    clock = HybridLogicalClock(node)
    store = StoreSet(tmp / node, node_id=node)
    bus = EventBus(clock, store, component="supply")
    cost = CostPolicy(bus, clock)
    # A-021.5: cold start is FREE_TIME, and FREE_TIME permits only `free` and
    # provably-capped free tiers. That is the period this runs in, deliberately
    # -- if the ladder cannot serve a request under the strictest period it
    # cannot serve one at 3 a.m., which is when it matters.
    ledger = QuotaLedger()
    gw = ModelGateway(bus, cost, quota=ledger)
    return bus, cost, ledger, gw


def main() -> int:
    print("VESPER supply acceptance -- LIVE providers, real quota\n")
    events: list = []

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ---------------------------------------------------- 1. registration
        bus, cost, ledger, gw = wiring(tmp)
        # INV-COORD-5: delivery is at-least-once, so a consumer must be able
        # to recognise a repeat. This one only appends to a list for display,
        # and event_id is genuinely the right key for that -- the same event
        # delivered twice is the same event, not two attempts.
        bus.subscribe("gateway.attempt", lambda e: events.append(e), name="acc-attempt",
                      idempotency_key=lambda e: e.event_id)
        bus.subscribe("quota.exhausted", lambda e: events.append(e), name="acc-exhausted",
                      idempotency_key=lambda e: e.event_id)
        bus.subscribe("quota.unavailable_on_tier", lambda e: events.append(e), name="acc-tier",
                      idempotency_key=lambda e: e.event_id)

        rep = supply.register(gw, cost, ledger, egress_class="E1_PRIVATE")
        record("private ladder registers from the governed table",
               len(rep["registered"]) >= 2,
               f"registered={rep['registered']}")
        record("R6: no E2_PUBLIC supplier is in the private ladder",
               all("google" not in p and "openrouter" not in p
                   and "nvidia" not in p and "codex" not in p
                   for p in rep["registered"]),
               f"excluded by egress={rep['excluded_by_egress']}")
        record("skipped rows are named, never silently dropped",
               isinstance(rep["skipped"], list),
               f"skipped={rep['skipped'] or 'none'}")

        # PICK THE TEXT PROFILE BY NAME, NOT BY POSITION. This read
        # `profile_ids[0]` until the image rung was added, at which point the
        # list gained a second entry and a TEXT prompt was sent to an image
        # model -- which answered, with a picture. The run went red and that is
        # the acceptance test doing its job: an index into a list whose
        # contents can grow is a latent bug waiting for the list to grow.
        text_profiles = [p for p in rep["profile_ids"] if "-text-" in p]
        image_profiles = [p for p in rep["profile_ids"] if "-image-" in p]
        profile = text_profiles[0] if text_profiles else None
        record("the text and image ladders are separately addressable",
               bool(text_profiles) and bool(image_profiles),
               f"text={text_profiles} image={image_profiles}")

        # ------------------------------------------------ 2. a real answer
        try:
            out = gw.complete(
                "Reply with exactly the word: LADDER_OK",
                task_id="live-1", profile_id=profile, difficulty="trivial")
            text = (out.get("result") or {}).get("text") or ""
            record("a real request crosses the ladder and returns an answer",
                   "LADDER_OK" in text.upper(),
                   f"provider={out['provider_id']} text={text.strip()[:60]!r}")
        except AllProvidersExhausted as e:
            record("a real request crosses the ladder and returns an answer",
                   False, str(e)[:200])
            out = {}

        # ------------------------------------------------ 3. quota was booked
        booked = [r for r in ledger.report() if r["used"] > 0]
        record("the call was booked against quota",
               bool(booked),
               "; ".join(f"{r['provider_id']}/{r['model']} used={r['used']} "
                         f"measured={r['spend_is_measured']}" for r in booked[:3]))

        # ---------------------------------------- 4. failover, forced for real
        # Revoke whichever provider actually answered and require the ladder to
        # produce an answer from a DIFFERENT one. This is the property SR-003
        # names -- "automatic API switching when quota/error occurs" -- and it
        # cannot be shown with one provider registered.
        first = out.get("provider_id")
        if first:
            gw.set_available(first, False)
            try:
                out2 = gw.complete(
                    "Reply with exactly the word: FAILOVER_OK",
                    task_id="live-2", profile_id=profile, difficulty="trivial")
                t2 = (out2.get("result") or {}).get("text") or ""
                record("SR-003: revoking the answering rung fails over to another",
                       out2["provider_id"] != first and "FAILOVER_OK" in t2.upper(),
                       f"{first} revoked -> answered by {out2['provider_id']}")
            except AllProvidersExhausted as e:
                record("SR-003: revoking the answering rung fails over to another",
                       False, str(e)[:200])
            gw.set_available(first, True)

        # ------------------------------------------- 4b. image, same pool
        if image_profiles:
            try:
                img = gw.complete("a single grey square on a white background",
                                  task_id="live-img",
                                  profile_id=image_profiles[0],
                                  difficulty="trivial")
                res = img.get("result") or {}
                b64 = res.get("image_b64") or ""
                record("the image ladder returns real image data",
                       len(b64) > 1000,
                       f"provider={img['provider_id']} base64_chars={len(b64)}")
            except AllProvidersExhausted as e:
                record("the image ladder returns real image data", False, str(e)[:160])

            # THE POINT OF ONE LEDGER: an image call must appear against the
            # SAME account budget the text call drew on. If these were separate
            # ledgers both would look healthy while together overspending.
            pools = ledger.pool_report()
            shared = [p for p in pools if len(p["drawn_by"]) > 1]
            record("text and image book against ONE shared account pool",
                   bool(shared),
                   "; ".join(f"{p['account']}: used={p['used']} of {p['limit']} "
                             f"by {p['drawn_by']}" for p in pools) or "no pooled entries")

        # ------------------------------- 5. the public ladder is strictly wider
        bus_p, cost_p, ledger_p, gw_p = wiring(tmp, node="public")
        rep_p = supply.register(gw_p, cost_p, ledger_p, egress_class="E2_PUBLIC")
        record("public work may use every supplier; private work may not",
               len(rep_p["registered"]) > len(rep["registered"]),
               f"public={len(rep_p['registered'])} private={len(rep['registered'])}")

        # ---------------------------------------- 6. attempts are all free-class
        record("INV-COST-1: zero paid attempts left the gateway",
               gw.paid_attempts() == 0,
               f"attempts_by_class={gw.attempts_by_class}")

    print()
    bad = [r for r in results if r[0] == FAIL]
    print(f"{len(results) - len(bad)}/{len(results)} assertions passed")
    if bad:
        print("\nFAILED:")
        for _, name, detail in bad:
            print(f"  - {name}: {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
