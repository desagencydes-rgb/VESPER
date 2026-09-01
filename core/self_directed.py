"""What VESPER does when nobody has asked it anything.

THE ENGINE WAS BUILT AND STARVED. `core/autonomy.py` refuses a trigger that
fires on the clock alone, refuses a predicate that cannot be shown to
terminate, refuses a string predicate because an interpreter is a place a model
call can hide, and refuses a model call in the decision path outright. Nobody
else in the field has that. It had ONE trigger registered -- memory expiry --
so it woke every pass, found nothing to consider, and went back to sleep.

THE SPLIT THIS FILE IS BUILT ON. "Decide intentionally whether to do something
else" sounds like judgement, and judgement sounds like a model call. It is
resolved by separating the two questions:

  WHETHER to wake   deterministic predicates over declared world state. No
                    model. This is what `core/autonomy.py` already enforces.
  WHAT to do awake  may be a model call, because by then the decision to act
                    at all has been made by something auditable.

So every trigger here reads state a sensor actually writes, and carries an
`intent` -- a sentence handed to the actor exactly as a spoken request would
be. The intent is never consulted while deciding.

WHY EVERY INTENT HERE IS AN OBSERVATION. The standing grant is L2 and these run
in FREE_TIME with the owner absent. An intent that needed more would be refused
for `below_required_level`, which is not in `CONFIRMABLE_REASONS`, so it would
not even become a question -- it would be a nightly refusal nobody sees.
Looking at the machine is genuinely useful, is exactly what L1 authorises, and
leaves the decision about what to DO with the finding to a person who is awake.
"""

from __future__ import annotations

from typing import Any

from .autonomy import Trigger

# Below this share of the disk free, the machine is worth looking at. Not a
# tunable yet: it is one number with one consumer, and inventing a contract for
# it before anything else reads it would be ceremony.
DISK_PRESSURE_RATIO = 0.10

DISK_TERM = "world.current_host.disk_free_ratio"
HEALTH_TERM = "world.current_host.health"


def disk_pressure_trigger(threshold: float = DISK_PRESSURE_RATIO) -> Trigger:
    """Fires when the disk is genuinely low, never because time passed.

    NO CLOCK TERM AT ALL, so `anti_cron_probe` cannot fail it: there is no
    combination of clock values that makes this fire. The disk has to actually
    be full.

    AND AN UNKNOWN DISK DOES NOT FIRE. `PredicateEvaluator.evaluate` returns
    False when any term is UNKNOWN, which is the acting side of INV-COORD-2 --
    a sensor that has not reported yet is not the same as a healthy disk, and
    only one of those two readings is safe to act on.
    """
    def predicate(s: dict) -> bool:
        v = s.get(DISK_TERM)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
        return 0.0 <= float(v) < threshold

    return Trigger(
        trigger_id="trg_disk_pressure",
        predicate_class="STATE",
        predicate=predicate,
        state_terms=(DISK_TERM,),
        debounce_s=3600,
        intent="check which directories are using the most disk space",
    )


def host_health_trigger() -> Trigger:
    """Fires when the host reports itself unhealthy.

    `health` is written by the `host-health` sensor. The predicate is total over
    the shapes that term takes -- a string, a missing fact, a boolean -- because
    `assert_terminating` probes it with all of them at registration and a
    predicate that raises on one of them is refused before it ever runs.
    """
    def predicate(s: dict) -> bool:
        v = s.get(HEALTH_TERM)
        return isinstance(v, str) and v.strip().lower() in ("degraded", "unhealthy")

    return Trigger(
        trigger_id="trg_host_unhealthy",
        predicate_class="STATE",
        predicate=predicate,
        state_terms=(HEALTH_TERM,),
        debounce_s=1800,
        intent="check the machine's load and memory pressure",
    )


# L2 AND L3 DISAGREEING IS THE ONLY HONEST SIGNAL FOR THIS. A trigger that
# fired on "it is 3am and we are on mains" would pass the anti-cron probe --
# power source is world state -- and would still be a scheduled job wearing a
# predicate's clothes. Counting is cheap, cannot fire on the clock, and is
# false exactly when there is work to do.
DRIFT_TERM = "world.memory.l2_drifted"


def memory_drift_trigger(compactor: Any) -> Trigger:
    """Fires when L2 has stopped being what L3 projects, and repairs it.

    WHY THIS IS A HANDLER AND NOT AN INTENT. Re-deriving L2 from L3 is
    deterministic maintenance with one right answer. Asking a model to propose
    it would put a model in front of a decision already made, and the summary
    it might write is a different job -- `compact()` -- which needs a
    summariser and a token budget and is not this.

    REPROJECTION IS THE RECOVERY PATH AND IT IS SAFE TO REPEAT. It drops L2 and
    rebuilds it from the log AND the tombstones, so an erasure the owner asked
    for is not resurrected by a maintenance pass. Running it twice produces the
    same L2 as running it once.

    VERIFY BEFORE REBUILDING. `verify()` is a pure comparison; `reproject()`
    throws away a table. Doing the cheap check first means the expensive one
    only happens when there is something to fix, and the finding is published
    either way -- a drift that was repaired silently is a divergence nobody
    ever learns the cause of.
    """
    def predicate(s: dict) -> bool:
        # NAMED FOR THE CONDITION THAT MATTERS, and that is not cosmetic. The
        # first version read `world.memory.l2_matches_log` and fired when it
        # was FALSE -- and `anti_cron_probe` refused it at registration, on the
        # grounds that a predicate firing with every state term false is
        # indistinguishable from one that fires unconditionally. It was right:
        # such a trigger runs on an empty world, which is the clock.
        #
        # Inverting the term makes firing require a POSITIVE observation of
        # drift. UNKNOWN and False both mean "do nothing", which is also the
        # acting side of INV-COORD-2 -- a probe that has not answered is not
        # evidence that L2 is broken.
        return s.get(DRIFT_TERM) is True

    def handler() -> dict:
        report = compactor.verify()
        if report.get("converged"):
            return {"converged": True, "reprojected": False}
        out = compactor.reproject()
        after = compactor.verify()
        return {"converged": False, "reprojected": True,
                "expected": report.get("expected"),
                "actual": report.get("actual"),
                "projected": out.get("projected"),
                "converged_after": after.get("converged")}

    return Trigger(
        trigger_id="trg_memory_drift",
        predicate_class="STATE",
        predicate=predicate,
        state_terms=(DRIFT_TERM,),
        debounce_s=900,
        handler=handler,
    )


# THE SAME POLARITY LESSON AS THE DRIFT TERM. Named for the condition that
# matters, so firing needs a positive observation rather than the absence of
# one -- a predicate that fires on an empty world is the clock.
CONTRADICTION_TERM = "world.memory.contradictions_present"


def contradiction_trigger(arbiter: Any) -> Trigger:
    """Fires when L2 holds two values for the same thing, and arbitrates.

    WHY THIS IS NOT THE UPDATER'S JOB. The updater runs in the background,
    after the act, and must never block or fail a turn -- so it has no way to
    surface anything to the owner and no business deciding what happens when
    two things it wrote disagree. That is the whole reason the arbiter is its
    own subsystem, and it has been reachable from nothing.

    A HANDLER, AND THE HANDLER NEVER PICKS. `sweep()` hands each contradiction
    to `resolve_memory_conflict`, which is DF-MEMORY-AUTHORITY and lives in
    core/evidence.py. Three outcomes are available and the third is the one
    people forget: RESOLVED where rank settles it, ASK where the ranks
    disagree, and HOLD BOTH -- a state VESPER sits in, acting on neither. A
    system that must always produce an answer produces a wrong one here,
    confidently, and the owner never sees that it happened.

    THE QUESTIONS ARE PUBLISHED, NOT ASKED. `interruption_budget.toml` governs
    when a question reaches the owner and this trigger does not get to overrule
    it. What it guarantees is that the question EXISTS rather than having been
    silently resolved away -- which is the whole point of the subsystem.
    """
    def predicate(s: dict) -> bool:
        return s.get(CONTRADICTION_TERM) is True

    def handler() -> dict:
        swept = arbiter.sweep()
        asks = [r for r in swept if r.get("outcome") == "ASK"]
        held = [r for r in swept if r.get("outcome") == "HOLD_BOTH"]
        return {"examined": len(swept),
                "resolved": len([r for r in swept if r.get("outcome") == "RESOLVED"]),
                "open_questions": len(asks),
                "holding_both": len(held),
                # SUBJECT AND ATTRIBUTE ONLY, NEVER THE VALUES. A summary that
                # quoted the two competing values would put the contradiction's
                # content into an event anything can read, and one of the two is
                # wrong -- publishing both is publishing a falsehood beside a
                # truth with no way to tell them apart.
                "questions": [f"{r['subject']}/{r['attribute']}" for r in asks]}

    return Trigger(
        trigger_id="trg_memory_contradiction",
        predicate_class="STATE",
        predicate=predicate,
        state_terms=(CONTRADICTION_TERM,),
        debounce_s=600,
        handler=handler,
    )


# STALENESS IS A HASH MISMATCH, NEVER AN AGE. `valid_until` schedules the next
# rebuild; it does not decide what is true now, and a file edited one second
# after a rebuild reads as fresh for the rest of the window under a time rule.
MAP_TERM = "world.map.stale_present"


def map_staleness_trigger(maps: Any) -> Trigger:
    """Fires when a mapped file no longer hashes to what the map recorded.

    THE MAP IS NAVIGATION, NOT CONTENT, and a stale map is worse than no map:
    it answers where to look with a locator that has moved. SR-007 exists so
    the corpus is never dumped into context, and the whole bargain depends on
    the locators being true.

    `maps` IS A LIST OF ROOTS, EACH ITS OWN MAP. The owner's instruction was to
    map everything with submaps mapping their own parts -- which is the shape
    `build()` already produces: a directory is a node, its files are nodes with
    it as parent, and a Python file's symbols are nodes under the file. What
    was missing was more than one root and anything at all keeping them true.

    A HANDLER, NOT AN INTENT. Re-hashing is deterministic and has one right
    answer; nothing here needs a model, and asking one would put it in front of
    a decision already made.
    """
    def predicate(s: dict) -> bool:
        return s.get(MAP_TERM) is True

    def handler() -> dict:
        out = []
        for m in maps:
            stale = m.refresh()
            if stale:
                # REBUILT, NOT PATCHED. `refresh` marks what moved; a map that
                # marked staleness and left the locators alone would keep
                # answering with the ones that moved.
                m.build()
            out.append({"map_id": getattr(m, "map_id", "?"),
                        "stale": len(stale),
                        "nodes": len(getattr(m, "nodes", {}) or {}),
                        "coverage": getattr(m, "coverage_ratio", None)})
        return {"maps": out, "rebuilt": sum(1 for o in out if o["stale"])}

    return Trigger(
        trigger_id="trg_map_stale",
        predicate_class="STATE",
        predicate=predicate,
        state_terms=(MAP_TERM,),
        debounce_s=300,
        handler=handler,
    )


def all_triggers(compactor: Any = None) -> list:
    """Everything VESPER runs for itself. One place, so it can be counted.

    `compactor` is optional so a caller with no memory still gets the host
    triggers. A None compactor means the drift trigger is not registered at
    all, rather than registered and quietly doing nothing -- a trigger that
    fires and cannot act is the state this whole layer was in until yesterday.
    """
    out = [disk_pressure_trigger(), host_health_trigger()]
    if compactor is not None:
        out.append(memory_drift_trigger(compactor))
    return out
