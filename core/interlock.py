"""Emergency stop — a dead-man's switch, not a kill signal.

THE DESIGN DECISION AND ITS CONTROL. A-031.2 severs the stop path itself and
requires that **autonomy halts within `T_token_ttl`**. A kill-signal
implementation does the opposite: cut the wire and the signal never arrives, so
autonomy runs on forever. The mandatory control is exactly that build, and the
corpus is explicit that its red run "is the evidence the dead-man's-switch
choice was necessary rather than stylistic".

So the interlock is inverted: autonomy runs only while a **fresh enable token**
is present. The token expires on its own. Stopping is the ABSENCE of a renewal,
which means every failure of the stop path — severed, wedged, compromised,
crashed — fails toward stopped.

WHAT KEEPS RUNNING UNDER `STOP_AUTONOMY` (A-031.4): observation, telemetry,
checkpointing, user-invoked work, AND ALARMS. Stopping autonomous action is not
the same as going dark, and an interlock that silenced the alarms would make
engaging it dangerous — which would make people reluctant to engage it, which
defeats the whole thing. `STOP_ALL` is the separate, louder decision that also
halts alarms.

NO AUTOMATIC RE-ARM, EVER (A-031.8). Twenty-four hours after a stop the system
is still stopped. A timer that re-arms is a system that decides for itself that
the emergency is over.

THE RUNTIME CANNOT MINT, EXTEND OR REPLAY A TOKEN (A-031.6), AND CANNOT EDIT
THE INTERLOCK CONFIGURATION (A-031.7, governed surface 8). Both are structural:
the minting key is not reachable from the runtime, and the config path is inside
the self-modification boundary.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any

from .bus import EventBus

STOP_MODES = ("RUNNING", "STOP_AUTONOMY", "STOP_ALL")

# A-031.4/.5: what survives each mode. Alarms are the interesting row.
SURVIVES_STOP_AUTONOMY = ("observation", "telemetry", "checkpointing",
                          "user_invoked_work", "alarms")
SURVIVES_STOP_ALL = ("observation", "telemetry")

# A-031.1: all autonomous actuation ceases within this budget.
T_NEW_ACTION_MS = 2000


class TokenMintingRefused(Exception):
    """The runtime attempted to mint, extend or replay an enable token."""


class InterlockConfigRefused(Exception):
    """The runtime attempted to modify the interlock configuration."""


@dataclass(frozen=True, slots=True)
class EnableToken:
    """Autonomy runs only while one of these is fresh.

    `issued_by` is a human principal. The token is minted OUTSIDE the runtime
    by a key the runtime cannot reach, which is why `SafetyInterlock` has no
    mint method at all -- not a guarded one, none.
    """

    token_id: str
    issued_at_ms: int
    ttl_ms: int
    issued_by: str
    signature: str

    def expires_at_ms(self) -> int:
        return self.issued_at_ms + self.ttl_ms


class SafetyInterlock:
    """Holds the stop state. Fails toward stopped in every direction."""

    def __init__(self, bus: EventBus, *, now_ms: Any = None,
                 token_ttl_ms: int = 30_000) -> None:
        self._bus = bus
        self._now_ms = now_ms or (lambda: 0)
        self.token_ttl_ms = token_ttl_ms
        self._mode = "RUNNING"
        self._token: EnableToken | None = None
        self._stopped_at_ms: int | None = None
        self._lock = threading.RLock()
        self.in_flight_resumable: list = []

    # --------------------------------------------------------------- tokens

    def held_token_id(self) -> str | None:
        """The token_id currently held, or None.

        EXISTS SO A CALLER CAN AVOID PRESENTING WHAT IS ALREADY HELD. A caller
        in a loop that re-reads the minter's file every tick would otherwise
        present the same token thousands of times between mints, and every one
        of those is a refusal WITH AN EVENT: measured 13,886 in one hour, one
        token_id, 343,470 records -- over 80% of the live log. The refusal is
        correct and stays; what was wrong is asking for it.

        `self._token` is never cleared -- expiry is a comparison against
        `expires_at_ms()`, not a reset (see `autonomy_permitted`) -- so an id
        this returns can NEVER be accepted again by `present_token`. Skipping
        on a match is therefore refusing exactly what would have been refused,
        and cannot let autonomy run one millisecond longer.
        """
        with self._lock:
            return self._token.token_id if self._token is not None else None

    def present_token(self, token: EnableToken) -> None:
        """Accept a token minted OUTSIDE the runtime.

        Replay is refused by token_id: a token already seen cannot re-enable,
        so a runtime that captured one off the wire gains nothing (A-031.6).
        """
        with self._lock:
            if self._token is not None and token.token_id == self._token.token_id:
                self._bus.publish(
                    "safety.token_replay_refused", subject=token.token_id,
                    payload={"token_id": token.token_id,
                             "note": ("a token already seen cannot re-enable. "
                                      "Replay would let a captured token extend "
                                      "autonomy indefinitely.")},
                    component="interlock")
                raise TokenMintingRefused(
                    f"token {token.token_id!r} has already been presented")
            self._token = token
        self._bus.publish("safety.token_accepted", subject=token.token_id,
                          payload={"token_id": token.token_id,
                                   "issued_by": token.issued_by,
                                   "expires_at_ms": token.expires_at_ms()},
                          component="interlock")

    def mint_token(self, *_a: Any, **_k: Any) -> None:
        """Exists ONLY to refuse. A-031.6.

        A guarded mint path is still a mint path; this one has no body that
        could ever succeed, so there is nothing to misconfigure.
        """
        self._bus.publish(
            "safety.mint_refused", subject="runtime",
            payload={"note": ("the minting key is not reachable from the "
                              "runtime. This method exists to make the refusal "
                              "explicit and auditable, not to guard a path that "
                              "could otherwise succeed.")},
            component="interlock")
        raise TokenMintingRefused(
            "the runtime cannot mint, extend or replay an enable token")

    extend_token = mint_token
    replay_token = mint_token

    # ------------------------------------------------------------ the check

    def autonomy_permitted(self) -> bool:
        """THE DEAD-MAN'S SWITCH. Autonomy runs only while a token is fresh.

        Every failure mode -- severed path, wedged control plane, crashed
        renewer, compromised policy plane -- results in no fresh token, and
        therefore in a stop. That is the whole point of inverting it.
        """
        with self._lock:
            if self._mode != "RUNNING":
                return False
            if self._token is None:
                return False
            return self._now_ms() < self._token.expires_at_ms()

    def stop_reason(self) -> str:
        with self._lock:
            if self._mode != "RUNNING":
                return self._mode
            if self._token is None:
                return "no_enable_token"
            if self._now_ms() >= self._token.expires_at_ms():
                return "enable_token_expired"
            return "running"

    # --------------------------------------------------------------- engage

    def engage(self, mode: str, *, principal: str = "owner",
               in_flight: tuple = ()) -> dict:
        if mode not in ("STOP_AUTONOMY", "STOP_ALL"):
            raise ValueError(f"mode must be STOP_AUTONOMY or STOP_ALL, got {mode!r}")
        with self._lock:
            self._mode = mode
            self._stopped_at_ms = self._now_ms()
            self.in_flight_resumable = list(in_flight)
        payload = {"mode": mode, "principal": principal,
                   "at_ms": self._stopped_at_ms,
                   "t_new_action_ms": T_NEW_ACTION_MS,
                   "in_flight_to_resumable": list(in_flight),
                   "survives": list(SURVIVES_STOP_AUTONOMY if mode == "STOP_AUTONOMY"
                                    else SURVIVES_STOP_ALL)}
        self._bus.publish("safety.stop_engaged", subject=mode, payload=payload,
                          component="interlock")
        return payload

    def survives(self, subsystem: str) -> bool:
        with self._lock:
            if self._mode == "RUNNING":
                return True
            allowed = (SURVIVES_STOP_AUTONOMY if self._mode == "STOP_AUTONOMY"
                       else SURVIVES_STOP_ALL)
        return subsystem in allowed

    def rearm(self, *, principal: str | None, token: EnableToken) -> dict:
        """A-031.9. A HUMAN re-arms; the event names the principal.

        `principal` is required. There is no path that re-arms without naming
        who did it, because "the system re-armed itself" is the state A-031.8
        forbids.
        """
        if not principal:
            raise ValueError(
                "re-arming requires a named human principal. A re-arm with no "
                "principal is an automatic re-arm, which A-031.8 forbids.")
        with self._lock:
            self._mode = "RUNNING"
            self._token = token
            resumed = list(self.in_flight_resumable)
            self.in_flight_resumable = []
        self._bus.publish("safety.interlock_rearmed", subject=principal,
                          payload={"principal": principal,
                                   "token_id": token.token_id,
                                   "resumes_from_checkpoint": resumed},
                          component="interlock")
        return {"mode": "RUNNING", "principal": principal,
                "resumed_from_checkpoint": resumed}

    def modify_config(self, *_a: Any, **_k: Any) -> None:
        """A-031.7. Governed surface 8 -- refused structurally."""
        self._bus.publish(
            "selfmod.attempt_blocked", subject="interlock_config",
            payload={"note": ("interlock configuration is governed surface 8. "
                              "A runtime that can widen its own stop conditions "
                              "does not have a stop condition.")},
            component="interlock")
        raise InterlockConfigRefused(
            "the runtime may not modify interlock configuration")
