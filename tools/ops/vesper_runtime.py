#!/usr/bin/env python3
"""The process that closes the loop: reads what was typed, answers, shows it.

WHAT WAS MISSING. Every piece existed and nothing owned them together. The
field posted to Swift and Swift appended a line nobody read. `HomeState` derived
the face from bus events and no long-running process held a bus. The ladder
answered when something called it and nothing called it on the owner's behalf.
An engine, a steering wheel, and no ignition.

This is the ignition, and it is deliberately small: it owns the bus, wires the
five components that already work to each other, and pumps one file. Every
decision it appears to make is made somewhere else -- routing by `Router`,
permission by the gateway's choke point, wording by `narration.toml`, what
happens to a failure by `TriageQueue`. If this file grows a policy, the policy
is in the wrong place.

A FILE, NOT A SOCKET. The channel to the surface is a file because that channel
already existed in the other direction: `home.json` is written here and read by
the chrome. A socket would be a second kind of connection between the same two
processes, and `tools/ops/alarm_wake_linux.py` records what two mechanisms
governing one piece of state cost -- "one mechanism, one register, no hooks that
have to fire in the right order".

IT READS BY OFFSET AND NEVER TRUNCATES. Truncating the outbox would race the
writer: Swift appends without locking, and a truncation between its seek and its
write loses an utterance with nothing reporting it. Tracking a byte offset means
the two never touch the same bytes, and a restart re-reads from where it stopped
rather than replaying the day.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.bus import EventBus                                   # noqa: E402
from core.cost import CostPolicy                                # noqa: E402
from core.gateway import AllProvidersExhausted, ModelGateway    # noqa: E402
from core.hlc import HybridLogicalClock                         # noqa: E402
from core.home_state import HomeState                           # noqa: E402
from core.intake import Intake                                  # noqa: E402
from core.difficulty import classify                            # noqa: E402
from core.narration import Announcer                            # noqa: E402
from core.persona import Persona, Situation                     # noqa: E402
from core.quota import QuotaLedger                              # noqa: E402
from core.router import NoRouteAvailable, Router                # noqa: E402
from core.store import StoreSet                                 # noqa: E402
from core.triage import TriageQueue                             # noqa: E402
from routing import supply                                      # noqa: E402
from routing.supply import for_egress, load_rows, measured_profiles  # noqa: E402

STATE = Path.home() / "Library" / "Application Support" / "VESPER"
OUTBOX = STATE / "say.jsonl"
OFFSET = STATE / "say.offset"

# How often the outbox is re-read. See the loop at the bottom for why it is
# this small: it is half of the owner-visible floor on a reply, and the other
# half is the chrome's own timer in HomeChrome.swift.
POLL_SECONDS = 0.15


def build(node: str = "vesper-runtime"):
    """Wire what already exists. Nothing here decides anything."""
    STATE.mkdir(parents=True, exist_ok=True)
    clock = HybridLogicalClock(node)
    store = StoreSet(STATE / "bus", node_id=node)
    bus = EventBus(clock, store, component="runtime")
    cost = CostPolicy(bus, clock)
    ledger = QuotaLedger(path=STATE / "quota.json", bus=bus)
    gw = ModelGateway(bus, cost, quota=ledger)

    report = supply.register(gw, cost, ledger, egress_class="E1_PRIVATE")
    rows = for_egress(load_rows()[0], "E1_PRIVATE")
    router = Router(bus, measured_profiles(rows, purpose="text"))

    home = HomeState(bus=bus, clock=clock)
    home.attach(bus)

    triage = TriageQueue(path=STATE / "triage.json", bus=bus, clock=clock)
    triage.attach(bus)

    # SPOKEN WHEN THE OWNER IS WAITING, which is what typing into the field
    # means. RB-006 governs the other case and this process does not have one
    # yet: everything it handles is a request somebody just made.
    announcer = Announcer(bus=bus)
    announcer.attach(bus, interruption_class="active_user_task",
                     next_rung="a local model")

    intake = Intake(bus=bus, clock=clock)
    # LOADED ONCE, AT BUILD, AND ALLOWED TO STOP THE PROCESS. `Persona.load`
    # raises on a contract it cannot validate, and that raise is not caught
    # here: a runtime that starts without a persona answers fluently and
    # namelessly, which is indistinguishable from working and was the state of
    # this system until 2026-08-26.
    persona = Persona.load(bus=bus)
    return bus, gw, router, home, intake, triage, report, persona


def answer(gw, router, persona, utterance) -> str:
    """One request across the ladder. Difficulty routes it; the ladder serves it.

    `privacy_class` IS NOT PASSED, and that is the point of the default. Anything
    the owner types is theirs until something establishes otherwise, so it takes
    the gateway's strict default and reaches only E1_PRIVATE suppliers. A caller
    that wanted the public pool would have to say so, in writing, at the call.

    AND THAT DEFAULT NOW GOVERNS MORE THAN THE QUESTION. The composed persona
    carries whatever `voice.toml [owner]` holds, so the preamble is owner
    content and travels under the same strict class -- E1_PRIVATE rungs only,
    checked per provider at the choke point, before quota is even consulted.
    """
    task = utterance.hlc or "typed"
    kind = classify(utterance.text)
    try:
        # PREFER LATENCY, BECAUSE THE OWNER IS LOOKING AT THE SCREEN. That is
        # the whole justification and it is situational, which is why it is an
        # argument here and not a new default inside the router: a background
        # task at 3 a.m. should still rank on cost. `latency_budgets.toml` puts
        # `speech_end_to_response_onset` at 1200 ms, and this path was measured
        # at 25.9 s and 68.7 s on 2026-08-26 -- a 20-57x miss on a budget whose
        # `on_miss.prohibited` list starts with "relax budget_ms".
        decision = router.select(kind.difficulty, prefer="latency", task_id=task)
    except NoRouteAvailable as e:
        return f"no route: {e}"

    # THE SITUATION IS DERIVED, NOT STORED (DR-028's third layer). `normal`
    # because a typed request with the owner waiting is exactly that; the alarm
    # path builds its own and does not come through here.
    system, _ = persona.compose(Situation(urgency="normal"))

    t0 = time.perf_counter()
    try:
        # `prefer` IS PASSED TO BOTH LAYERS, and it has to be. The router picks
        # the profile and the gateway picks the rung inside it; setting it on
        # one leaves the other ranking on an axis unrelated to time, which just
        # moves the variance from between profiles to within one.
        out = gw.complete(utterance.text, task_id=task, system=system,
                          profile_id=decision.profile_id, prefer="latency",
                          difficulty=kind.difficulty)
    except AllProvidersExhausted:
        # NOT AN ERROR STRING. The narration layer has already spoken the real
        # sentence; this is what the transcript shows, and it says the true
        # thing: the task survives.
        return "every provider is spent — checkpointed and queued, nothing lost"
    finally:
        # OBSERVED WHETHER IT SUCCEEDED OR NOT, in a `finally`, because a rung
        # that took 40 s to fail is a slow rung and the next selection needs to
        # know. Recording only successes would let a supplier that times out
        # keep its enrolment-day estimate forever.
        router.observe(decision.profile_id, time.perf_counter() - t0)
    return ((out.get("result") or {}).get("text") or "").strip()


def pump(bus, gw, router, persona, home, intake, transcript: list,
         once: bool = False) -> int:
    """Read new lines, answer them, publish the transcript. Offset-tracked."""
    OUTBOX.touch(exist_ok=True)
    seen = int(OFFSET.read_text()) if OFFSET.exists() else 0
    handled = 0
    said: list = []
    with OUTBOX.open("r", encoding="utf-8") as f:
        f.seek(seen)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # A TORN LAST LINE IS NOT A CORRUPT FILE. Swift appends without
                # locking, so a read can catch a half-written line; skipping it
                # and not advancing past it means the next pass sees it whole.
                break
            text = (obj.get("text") or "").strip()
            if not text:
                continue
            res = intake.typed(text)
            said.append({"who": "owner", "text": text,
                         "source": res["utterance"]["source"],
                         "certain": res["utterance"]["certain"]})
            # SHOW THE OWNER THEIR OWN WORDS BEFORE ANSWERING, and this is not
            # a nicety. The transcript was written ONCE at the end of the pass,
            # so the owner's line was appended and immediately superseded by
            # the reply -- it never appeared on the stage at all. What the
            # owner saw was: the field clears, nothing, nothing, an answer.
            #
            # And the wait is real: measured 30 s on this exchange, and one
            # supplier in the table answers at 5 tok/s. Half a minute of no
            # feedback is indistinguishable from a system that did not hear.
            # Publishing here means the words land, the face turns to thinking,
            # and the dissolve happens when the answer actually arrives.
            transcript.extend(said)
            del transcript[:-40]
            said = []
            home.set_transcript(list(transcript))
            if res["outcome"] == "dispatched":
                reply = answer(gw, router, persona, intake.history[-1])
                # VESPER'S REPLY IS NOT AN UTTERANCE, and the first version put
                # it into `intake.history` as one. `Intake` is the record of
                # things said TO VESPER -- its confidence, its partials and its
                # dispatch gate all describe an inbound channel. Putting its own
                # words there makes them things it was told, which is wrong in
                # the record and would eventually be wrong in behaviour: a
                # replay of the transcript would feed VESPER its own answers as
                # instructions.
                said.append({"who": "vesper", "text": reply,
                             "source": "vesper", "certain": True})
            elif res["outcome"] == "reflected":
                said.append({"who": "vesper", "source": "vesper", "certain": True,
                             "text": "I heard that, but not clearly enough to "
                                     "act on it. Say it again?"})
            handled += 1
        seen = f.tell()
    OFFSET.write_text(str(seen))
    if said:
        transcript.extend(said)
        del transcript[:-40]
    home.set_transcript(list(transcript))
    home.write()
    return handled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="drain the outbox once and exit")
    ap.add_argument("--say", help="inject an utterance without the surface")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    bus, gw, router, home, intake, triage, report, persona = build()
    # WHAT WAS SAID, BY WHOM. Held here rather than in Intake because the two
    # are different records: Intake is the inbound channel and this is the
    # conversation.
    transcript: list = []

    if args.status:
        print(f"registered : {report['registered']}")
        print(f"profiles   : {report['profile_ids']}")
        print(f"skipped    : {report['skipped'] or 'none'}")
        print(f"face       : {home.state()}")
        return 0

    if args.say:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"text": args.say, "source": "typed",
                                "final": True}) + "\n")

    if args.once or args.say:
        n = pump(bus, gw, router, persona, home, intake, transcript, once=True)
        # THE SAME HONESTY THE INTERRUPT PATH APPLIES. A one-shot run that exits
        # leaving `thinking` on disk reports work that is not happening; the
        # 90 s staleness fallback would correct it eventually, and eventually is
        # not the same as correctly.
        home._set("resting", "the one-shot run finished")
        print(f"handled {n}")
        for line in transcript:
            who = "you" if line["who"] == "owner" else "VESPER"
            print(f"  {who:>6}: {line['text'][:120]}")
        return 0

    # GREET ON ARRIVAL. The owner asked for it, and it is doing real work
    # beyond courtesy: a home that shows an empty transcript is
    # indistinguishable from a home whose runtime never started. One line says
    # the whole chain is alive -- surface, bridge, runtime, ladder -- before
    # anything is asked of it.
    #
    # NOT MODEL-GENERATED. It must appear when the ladder is unreachable, which
    # is exactly when a generated greeting could not be produced.
    hour = time.localtime().tm_hour
    part = ("Good morning" if 5 <= hour < 12 else
            "Good afternoon" if 12 <= hour < 18 else
            "Good evening")
    transcript.append({"who": "vesper", "source": "vesper", "certain": True,
                       "text": f"{part}, sir. I'm here."})
    home.set_transcript(list(transcript))
    home._set("talking", "greeting the owner")
    try:
        Announcer(bus=bus).announce(
            "greeting", interruption_class="active_user_task")
    except Exception:                               # noqa: BLE001
        # A MISSING LINE MUST NOT STOP THE RUNTIME. The greeting is the first
        # thing that runs; a template problem here would look exactly like the
        # runtime failing to start at all.
        pass
    print("vesper runtime: watching the field. ctrl-c to stop.")
    home.write()
    while True:
        try:
            pump(bus, gw, router, persona, home, intake, transcript)
            # THE PLUMBING USED TO COST MORE THAN THE MODEL. 0.5 s here plus
            # 0.7 s in the chrome's own timer is up to 1.2 s of pure polling
            # around a call that now returns in ~0.7 s -- the transport was the
            # slower half of a conversation. An idle pass is a `seek` on a file
            # that has not changed; measured below 1 ms, so the cost of the
            # shorter interval is not on the same scale as what it buys.
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            raise
        except Exception as e:                      # noqa: BLE001
            # THE LOOP SURVIVES ONE BAD PASS. An exception here killed the
            # runtime outright, and the symptom was VESPER going silent -- no
            # error on screen, nothing in the home, the crash visible only in a
            # log nobody was watching. A supervisor would restart it, but the
            # app is the supervisor and it does not know the child died.
            #
            # Printed, not swallowed: a loop that hides its failures is how one
            # bad pass becomes a permanently degraded runtime that still looks
            # alive.
            print(f"pump error (continuing): {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
            time.sleep(1.0)
        except BaseException:
            # THE FACE MUST NOT BE LEFT MID-THOUGHT. A stopped runtime that
            # leaves `thinking` on disk reports work that is not happening --
            # the staleness fallback would fix it in 90 s, and being correct
            # immediately is better than being correct eventually.
            home._set("resting", "the runtime stopped")
            print("\nstopped; face returned to rest")
            return 0


if __name__ == "__main__":
    sys.exit(main())
