#!/usr/bin/env python3
"""Live-provider acceptance — the choke point with a real model behind it.

WHY THIS RUNNER EXISTS. F1 asserts A-004 against three lambdas. The cost
policy, the router, the planner and the verifier have all been green against
test doubles, and until 2026-08-24 no model call in this tree had ever left the
process. A doubled provider cannot fail the way a real one does: it does not
refuse a connection, does not return HTTP 400, and does not stop existing
half-way through a generation.

NOT HERMETIC, AND THEREFORE NOT PART OF `checks.py all`. It needs a live
endpoint. When there is none it reports NOT RUN and exits 2 -- it does NOT exit
0. A gate that goes green because its subject was absent is the vacuity defect
CI-007 was caught by, and this runner refuses to repeat it.

WHAT IT DOES NOT CLAIM. Throughput. `predicted_per_second` is echoed where the
endpoint reports it, but a rate measured by this runner is a single ad-hoc
request under whatever load the machine happens to carry. SPIKE-001 measures
throughput, over ten-minute runs, at a stated context, with a build tag.
INV-HW-2 is about exactly that distinction and nothing here is a substitute.

AND IT DOES NOT CLAIM THE RATE BELONGS TO THIS MACHINE. The profiles come from
`Router.from_spike_results`, which reads SPIKE-001 reports measured on ANOTHER
node. This host has no measured profile of its own yet, so the endpoint here is
served under a figure that describes different hardware. That is tolerable for
exercising the choke point and intolerable as a measurement, so L-001 asserts
the decision carries its `UNBOUND` marker: the profile names no node, nothing
ties its rate to whatever answers, and the decision says so out loud. When this
host is measured and enrolled, that marker becomes a `node_id` and A-042.4
starts applying here too.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.bus import EventBus  # noqa: E402
from core.cost import CostPolicy, CostPolicyViolation  # noqa: E402
from core.gateway import (AllProvidersExhausted, ModelGateway,  # noqa: E402
                          NoProviderForProfile, TERMINAL, TRANSIENT)
from core.hlc import HybridLogicalClock  # noqa: E402
from core.router import Router  # noqa: E402
from core.store import StoreSet  # noqa: E402
from routing.http_completion import (EndpointError,  # noqa: E402
                                     EndpointIdentity, build_provider,
                                     identify)

BASE_URL = os.environ.get("VESPER_LLAMA_SERVER", "http://127.0.0.1:8080")
RESULTS: list[dict] = []


class Case:
    def __init__(self, cid: str, title: str) -> None:
        self.cid, self.title = cid, title
        self.assertions: list[dict] = []
        self.error: str | None = None

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.assertions.append({"label": label, "ok": bool(ok), "detail": detail})

    def finish(self, error: str | None = None) -> None:
        self.error = error
        passed = error is None and all(a["ok"] for a in self.assertions)
        RESULTS.append({"id": self.cid, "passed": passed})
        print(f"[{'ok  ' if passed else 'FAIL'}] {self.cid:<16} "
              f"{'PASS' if passed else 'FAIL'}  {self.title}")
        for a in self.assertions:
            if not a["ok"]:
                print(f"           MISS: {a['label']}"
                      + (f" -- {a['detail']}" if a["detail"] else ""))
        if error:
            print(f"           ERROR: {error.strip().splitlines()[-1]}")


def _bus(tmp: Path, node: str):
    clock = HybridLogicalClock(node)
    return EventBus(clock, StoreSet(tmp / node, node_id=node),
                    component="live"), clock


def _counting(provider, box: list):
    """Wrap a provider so we can prove the adapter was never REACHED.

    `attempts_by_class` counts at the gateway boundary, which is what A-004.3
    asserts on. This counts one layer further out, at the provider itself, and
    the two answering the same way is the point: a refusal that increments the
    boundary counter but still calls the endpoint would satisfy A-004.3's
    letter while money left the machine.
    """
    inner = provider.call

    def counted(prompt, options):
        box.append(1)
        return inner(prompt, options)

    provider.call = counted
    return provider


# ===========================================================================
# L-001 — a routed call reaches a real model, and is attributable
# ===========================================================================
def l001_routed_live_call(tmp: Path, ident) -> None:
    c = Case("L-001", "Router decides, gateway routes, a real model answers")
    try:
        bus, clock = _bus(tmp, "l1")
        r = Router.from_spike_results(REPO / "docs/planning/spike-results", bus)
        d = r.select("trivial", host_ram_free_gb=6.0, task_id="L-001")

        cost = CostPolicy(bus, clock)
        cost.register_credential("local-free", "free")
        gw = ModelGateway(bus, cost)
        gw.register(build_provider("local-free", d.profile_id, BASE_URL,
                                   identity=ident))

        out = gw.complete("Reply with exactly: VESPER online.",
                          task_id="L-001", profile_id=d.profile_id,
                          options={"n_predict": 200, "temperature": 0.0,
                                   "enable_thinking": False})
        res = out["result"]
        c.check("the profile the router chose is the profile that answered",
                out["profile_id"] == d.profile_id,
                f"routed={d.profile_id} answered={out['profile_id']}")
        c.check("a real model produced text", bool(res["text"].strip()),
                repr(res["text"])[:80])
        c.check("the answer follows the instruction",
                "vesper online" in res["text"].strip().lower(),
                repr(res["text"].strip())[:80])
        # A figure without its build tag is not a measurement, and neither is
        # an answer without one: two runs cannot be compared if the thing that
        # produced them is unknown.
        c.check("the result carries the build that produced it",
                bool(res["endpoint"]["build_info"]),
                str(res["endpoint"]))
        c.check("no paid attempt on a free-credential call",
                gw.paid_attempts() == 0, str(gw.attempts_by_class))
        # The rate that decided this route was measured on other hardware.
        # That is survivable only while it is stated, so it is asserted.
        c.check("the decision admits its profile is not bound to this node",
                any("UNBOUND" in f for f in d.factors), str(d.factors))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# L-002 — the cost choke point refuses BEFORE the endpoint is reached
# ===========================================================================
def l002_cost_choke_point(tmp: Path, ident) -> None:
    c = Case("L-002", "A paid credential in FREE_TIME never reaches the endpoint")
    try:
        bus, clock = _bus(tmp, "l2")
        cost = CostPolicy(bus, clock)
        # A-021.5: cold start is FREE_TIME, always. No period is set here on
        # purpose -- the default is the assertion.
        cost.register_credential("paid-live", "paid")
        gw = ModelGateway(bus, cost)
        calls: list = []
        gw.register(_counting(
            build_provider("paid-live", "draft-accelerated-qwen1.7b",
                           BASE_URL, identity=ident), calls))

        c.check("cold start really is FREE_TIME", cost.period == "FREE_TIME",
                cost.period)
        exhausted = False
        try:
            gw.complete("this must never leave the machine", task_id="L-002",
                        profile_id="draft-accelerated-qwen1.7b",
                        options={"n_predict": 8})
        except AllProvidersExhausted:
            exhausted = True
        c.check("the task checkpoints rather than spending", exhausted)
        c.check("zero paid attempts at the gateway boundary (A-004.3)",
                gw.paid_attempts() == 0, str(gw.attempts_by_class))
        # The stronger claim: the endpoint was never called at all. A live
        # endpoint makes this checkable in a way a lambda never did.
        c.check("the ENDPOINT was never reached, not merely uncounted",
                len(calls) == 0, f"{len(calls)} live call(s) escaped")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# L-003 — exhaustion is not escalation, with both providers live
# ===========================================================================
def l003_exhaustion_not_escalation(tmp: Path, ident) -> None:
    c = Case("L-003", "Free revoked mid-task => zero paid attempts, both live")
    try:
        bus, clock = _bus(tmp, "l3")
        cost = CostPolicy(bus, clock)
        cost.register_credential("free-live", "free")
        cost.register_credential("paid-live", "paid")
        gw = ModelGateway(bus, cost)
        paid_calls: list = []
        gw.register(build_provider("free-live", "draft-accelerated-qwen1.7b",
                                   BASE_URL, identity=ident))
        gw.register(_counting(
            build_provider("paid-live", "draft-accelerated-qwen1.7b",
                           BASE_URL, identity=ident), paid_calls))

        # It works while the free provider is up...
        ok = gw.complete("Say OK.", task_id="L-003a",
                         profile_id="draft-accelerated-qwen1.7b",
                         options={"n_predict": 120, "temperature": 0.0,
                                  "enable_thinking": False})
        c.check("the free provider serves while it is available",
                ok["provider_id"] == "free-live", ok["provider_id"])

        # ...and revoking it does NOT promote the paid one, even though the
        # paid endpoint is live, healthy, and would answer instantly.
        gw.set_available("free-live", False)
        escalated = False
        try:
            gw.complete("Say OK.", task_id="L-003b",
                        profile_id="draft-accelerated-qwen1.7b",
                        options={"n_predict": 120})
        except AllProvidersExhausted:
            pass
        else:
            escalated = True
        c.check("exhaustion checkpoints; it does not escalate to paid",
                not escalated)
        c.check("zero paid attempts at the boundary after revocation",
                gw.paid_attempts() == 0, str(gw.attempts_by_class))
        c.check("the paid ENDPOINT was never reached",
                len(paid_calls) == 0, f"{len(paid_calls)} paid call(s) escaped")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# L-004 — TERMINAL is not retried; TRANSIENT is
# ===========================================================================
def l004_classification(tmp: Path, ident) -> None:
    c = Case("L-004", "Real failures classify, and classification decides retry")
    try:
        bus, clock = _bus(tmp, "l4")
        cost = CostPolicy(bus, clock)
        cost.register_credential("dead", "free")
        gw = ModelGateway(bus, cost, sleep=lambda s: None)
        # A port with nothing behind it. ICMP is blocked on this network, so
        # reachability is a TCP fact -- this is what "unreachable" looks like
        # at call time.
        # Its OWN identity, for the endpoint it actually addresses. Reusing
        # the live endpoint's identity here is what made this case pass against
        # a healthy server until 2026-08-24; the adapter now refuses it.
        dead_ident = EndpointIdentity(base_url="http://127.0.0.1:1",
                                      build_info=ident.build_info,
                                      model_path=ident.model_path,
                                      n_ctx=ident.n_ctx)
        dead = build_provider("dead", "draft-accelerated-qwen1.7b",
                              "http://127.0.0.1:1", identity=dead_ident)
        gw.register(dead)
        try:
            gw.complete("hello", task_id="L-004",
                        profile_id="draft-accelerated-qwen1.7b",
                        options={"n_predict": 8})
        except AllProvidersExhausted:
            pass
        att = [a for a in gw.history if a.provider_id == "dead"]
        c.check("a refused connection classifies as connection_error",
                any(a.classification == "connection_error" for a in att),
                str([a.classification for a in att]))
        c.check("connection_error is TRANSIENT, so it is RETRIED",
                len(att) >= 2, f"{len(att)} attempt(s)")
        c.check("a retry delay was published, not a silent immediate retry",
                any(a.retry_after_ms for a in att),
                str([a.retry_after_ms for a in att]))

        # TERMINAL: a live server, a request it will refuse outright.
        bus2, clock2 = _bus(tmp, "l4b")
        cost2 = CostPolicy(bus2, clock2)
        cost2.register_credential("bad", "free")
        gw2 = ModelGateway(bus2, cost2, sleep=lambda s: None)
        bad = build_provider("bad", "draft-accelerated-qwen1.7b",
                             BASE_URL, identity=ident)
        # n_predict is rejected by the endpoint as a bad request.
        orig = bad.call
        bad.call = lambda p, o: orig(p, {**o, "n_predict": -99999999})
        gw2.register(bad)
        try:
            gw2.complete("hello", task_id="L-004b",
                         profile_id="draft-accelerated-qwen1.7b",
                         options={"n_predict": 8})
        except AllProvidersExhausted:
            pass
        att2 = [a for a in gw2.history if a.provider_id == "bad"]
        terminal = [a for a in att2 if a.classification in TERMINAL]
        c.check("the live endpoint's refusal classifies as TERMINAL",
                bool(terminal), str([a.classification for a in att2]))
        c.check("a TERMINAL classification is NOT retried",
                len(att2) == 1, f"{len(att2)} attempts: "
                                f"{[a.classification for a in att2]}")
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# L-005 — the server stops existing half-way through a generation
# ===========================================================================
def l005_mid_call_kill(tmp: Path, ident, binary: Path, model: Path) -> None:
    c = Case("L-005", "A provider killed MID-CALL classifies and retries")
    proc = None
    try:
        port = 8099
        proc = subprocess.Popen(
            [str(binary), "-m", str(model), "-ngl", "99", "-fa", "on",
             "-c", "1024", "--port", str(port), "--host", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(60):
            time.sleep(1.0)
            try:
                identify(url, timeout=2.0)
                ready = True
                break
            except EndpointError:
                continue
        c.check("the second endpoint came up", ready)
        if not ready:
            c.finish()
            return

        bus, clock = _bus(tmp, "l5")
        cost = CostPolicy(bus, clock)
        cost.register_credential("doomed", "free")
        delays: list = []
        gw = ModelGateway(bus, cost, sleep=lambda s: delays.append(s))
        gw.register(build_provider("doomed", "draft-accelerated-qwen1.7b",
                                   url, timeout=120.0))

        # Kill it while a long generation is in flight. This is the failure a
        # test double cannot produce: the process the request is waiting on
        # ceases to exist, mid-stream, with the socket already open.
        def killer():
            time.sleep(3.0)
            proc.kill()

        threading.Thread(target=killer, daemon=True).start()
        try:
            gw.complete("Write a very long essay about the sea.",
                        task_id="L-005",
                        profile_id="draft-accelerated-qwen1.7b",
                        options={"n_predict": 4000, "temperature": 0.7})
        except AllProvidersExhausted:
            pass
        att = [a for a in gw.history if a.provider_id == "doomed"]
        c.check("the killed call was recorded as an error, not a success",
                any(a.outcome == "error" for a in att),
                str([a.outcome for a in att]))
        c.check("it classified into the TRANSIENT vocabulary, not 'unknown'",
                any(a.classification in TRANSIENT for a in att),
                str([a.classification for a in att]))
        c.check("the retry timing a human can act on was recorded (SR-004)",
                any(a.retry_after_ms for a in att),
                str([a.retry_after_ms for a in att]))
        c.check("the runtime actually WAITED before retrying",
                bool(delays), str(delays))
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))
    finally:
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    print("VESPER live-provider acceptance -- a real model behind the choke point")
    print(f"  endpoint: {BASE_URL}")
    try:
        ident = identify(BASE_URL, timeout=10.0)
    except EndpointError as e:
        print()
        print(f"  NOT RUN: no live endpoint at {BASE_URL} -- {e}")
        print("  Exiting 2. A gate that passes because its subject was absent")
        print("  is not a gate; see this file's header.")
        return 2
    if not ident.build_info:
        print()
        print("  NOT RUN: the endpoint did not report a build tag.")
        print("  A figure without its build tag is not a measurement, and an")
        print("  unattributable answer is not evidence. Exiting 2.")
        return 2
    print(f"  build:    {ident.build_info}")
    print(f"  model:    {ident.model_path}")
    print(f"  n_ctx:    {ident.n_ctx}")
    print()
    print("  NOTE: this host has no measured profile of its own. The route is")
    print("  decided on SPIKE-001 figures from another node, so the rate that")
    print("  chose it does not describe what answers. The gate exercises the")
    print("  choke point; it measures nothing.")
    print()

    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        l001_routed_live_call(tmp, ident)
        l002_cost_choke_point(tmp, ident)
        l003_exhaustion_not_escalation(tmp, ident)
        l004_classification(tmp, ident)
        binary = Path.home() / "VESPER-runtime" / "llama.cpp" / "llama-server"
        model = Path(ident.model_path or "")
        if not model.is_absolute():
            model = Path.home() / "VESPER-runtime" / str(model).lstrip("./")
        if binary.exists() and model.exists():
            l005_mid_call_kill(tmp, ident, binary, model)
        else:
            print("[skip] L-005           the mid-call kill needs a local binary "
                  "and model to start a second endpoint")

    passed = sum(1 for r in RESULTS if r["passed"])
    print()
    print(f"  cases {passed}/{len(RESULTS)} passed")
    ok = passed == len(RESULTS)
    print(f"  LIVE PROVIDER GATE: {'PASS' if ok else 'FAIL'}   ({time.time()-t0:.1f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
