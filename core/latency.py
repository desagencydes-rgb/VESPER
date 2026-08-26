"""How fast a rung ACTUALLY answered, as opposed to how fast it once did.

SHARED BY TWO LAYERS THAT MAKE THE SAME MISTAKE INDEPENDENTLY. `core/router.py`
chooses a profile and `core/gateway.py` chooses a provider inside it, and until
2026-08-26 both ranked on something that is not time -- the router on distance
above the tier floor, the gateway on quota headroom. Measured that day on one
profile with three rungs behind it, consecutive conversational turns took
0.56 s, 4.22 s, 1.02 s and 4.63 s purely because headroom rotated which rung
answered. Fixing one layer and not the other moves the variance rather than
removing it, so the record they both need lives here.

IT DOES NOT WEAKEN INV-HW-2. Everything here is measured -- more of it, more
recently, and on the path that actually serves requests rather than on an
enrolment sweep. Nothing is declared, and a rung with no observation is not
invented one: it keeps the sweep's figure and the decision says so.
"""

from __future__ import annotations

from dataclasses import dataclass

# WHY A SECOND SOURCE OF TRUTH ABOUT SPEED EXISTS AT ALL. The supply sweep
# measures each rung ONCE. For a rung on somebody else's hardware that is not a
# measurement of the rung, it is a measurement of one moment on it -- measured
# 2026-08-26, the same 45-character prompt to one standard rung took 4.3 s,
# 16.6 s, 29.4 s and 48.3 s within a few minutes, while the strong rung beside
# it took 0.6-0.8 s every time. The sweep's 51 tok/s for the first is not wrong;
# it is a sample from a distribution whose spread is the whole story, and a
# router that reads only the mean routes the owner into the tail.
#
# FAST UP, SLOW DOWN, and the asymmetry is the point. A rung that was slow once
# is likely slow again in the next minute, and the two errors are not priced
# alike: over-penalising costs a slightly stronger rung, under-penalising costs
# the owner a minute in front of a screen that looks broken. So a bad sample
# moves the estimate most of the way immediately and a good one earns its way
# back.
#
# THIS DOES NOT WEAKEN INV-HW-2. Everything here is measured -- more of it, more
# recently, on this path. Nothing is declared, and a profile with no observation
# is not invented one: it keeps the sweep's figure and says so.
# CHOSEN AGAINST THE RECOVERY CURVE, not by feel. At 0.6/0.2 -- the first pair
# written here -- one 40 s spike left a rung ranked behind a healthy one for 17
# consecutive good calls, which is not "slow to forgive", it is retired by one
# bad minute. At 0.7/0.4 a spike still moves the estimate 70% of the way
# immediately and the rung is back in front after 8 good samples.
#
# DEPRIORITISED IS NOT RETIRED, and that is what makes 8 acceptable. A demoted
# rung stays in the chain and is still tried in turn if the ones above it fail;
# it loses first place, not its place. Nothing here can remove a rung -- only
# the quota ledger and the egress check can, and both run before this.
ALPHA_UP = 0.7
ALPHA_DOWN = 0.4


@dataclass(slots=True)
class Observation:
    """Live wall-clock seconds-to-answer for one profile. Never persisted.

    NOT PERSISTED DELIBERATELY. A stale latency estimate read off disk at
    startup is a declared number wearing a measured number's clothes; a cold
    router should route on the sweep and re-learn, which costs a handful of
    requests and cannot be silently wrong for a week.
    """
    profile_id: str
    seconds: float
    samples: int = 1
    # SEEDED FROM THE FIRST SAMPLE IN `__post_init__`, not defaulted to 0.0 and
    # left there. It read `worst 0.00s` beside a real 0.70s observation, which
    # is a field reporting a number smaller than every value it has ever seen.
    worst_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.worst_seconds = max(self.worst_seconds, self.seconds)

    def update(self, seconds: float) -> None:
        a = ALPHA_UP if seconds > self.seconds else ALPHA_DOWN
        self.seconds = (1 - a) * self.seconds + a * seconds
        self.samples += 1
        self.worst_seconds = max(self.worst_seconds, seconds)
