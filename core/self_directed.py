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


def all_triggers() -> list:
    """Everything VESPER runs for itself. One place, so it can be counted."""
    return [disk_pressure_trigger(), host_health_trigger()]
