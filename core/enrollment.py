"""Node enrollment — admission is a gate, and Z2 is a real bound.

A-042.1: `DISCOVERED -> TRUSTED` IS UNREACHABLE DIRECTLY. Not "discouraged",
unreachable: the transition table has no such edge, so admission cannot be
skipped by a caller who is in a hurry. A node that appears on the network has
demonstrated that it can send packets and nothing else.

A-042.3: A `Z2` NODE MAY NOT HOLD STATE, ISSUE COMMANDS, OR RECEIVE SECRETS
(INV-TRUST-1). All three are refused, and they are refused separately because
they fail differently: holding state loses data when the node goes away, issuing
commands lets an under-verified node act, and receiving secrets puts a key
somewhere it cannot be protected. A single "is Z2 allowed" check would let one
of the three slip through when the others were considered.

A-042.4: `sustained_tokens_per_sec` IS MEASURED AT ENROLLMENT, NEVER DECLARED
(INV-HW-2), and a node with no measured profile is NEVER ROUTED TO. Fail-closed:
the alternative sends real work to a node on the strength of a datasheet.

A-042.5: RE-ATTESTATION EXPIRY DEMOTES `TRUSTED -> LIMITED_TRUST` AND EMITS A
CAPABILITY DEGRADATION. The emission is half the requirement. A node quietly
losing trust is a fabric that shrinks without anyone noticing, which is exactly
the state in which someone plans work for capacity that is no longer there.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus

STATES = ("DISCOVERED", "PENDING_ADMISSION", "LIMITED_TRUST", "TRUSTED",
          "REVOKED")

# The table IS the invariant (same construction as INV-TASK-1). Note the absence
# of DISCOVERED -> TRUSTED.
ALLOWED: dict[str, tuple] = {
    "DISCOVERED":        ("PENDING_ADMISSION", "REVOKED"),
    "PENDING_ADMISSION": ("LIMITED_TRUST", "TRUSTED", "REVOKED"),
    "LIMITED_TRUST":     ("TRUSTED", "REVOKED"),
    "TRUSTED":           ("LIMITED_TRUST", "REVOKED"),
    "REVOKED":           (),
}

TRUST_ZONES = ("Z0", "Z1", "Z2")

# INV-TRUST-1. Refused separately, because they fail in different ways.
Z2_FORBIDDEN = ("hold_state", "issue_command", "receive_secret")


class AdmissionRefused(Exception):
    """A state transition the admission gate does not permit."""


class Z2BoundViolation(Exception):
    """A Z2 node attempted something INV-TRUST-1 forbids."""


@dataclass(slots=True)
class EnrolledNode:
    node_id: str
    state: str = "DISCOVERED"
    trust_zone: str = "Z2"
    security_baseline_passed: bool = False
    capability_floor_passed: bool = False
    # INV-HW-2: None until MEASURED. A declared value never lands here.
    measured_tokens_per_sec: float | None = None
    reattestation_due_ms: int | None = None
    roles: tuple = ()

    def routable(self) -> bool:
        """A node with no measured profile is never routed to (A-042.4)."""
        return (self.state == "TRUSTED"
                and self.measured_tokens_per_sec is not None)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "state": self.state,
                "trust_zone": self.trust_zone,
                "security_baseline_passed": self.security_baseline_passed,
                "capability_floor_passed": self.capability_floor_passed,
                "measured_tokens_per_sec": self.measured_tokens_per_sec,
                "routable": self.routable(), "roles": list(self.roles)}


class EnrollmentRegistry:
    def __init__(self, bus: EventBus, *, now_ms: Any = None) -> None:
        self._bus = bus
        self._nodes: dict[str, EnrolledNode] = {}
        self._now_ms = now_ms or (lambda: 0)
        self._lock = threading.RLock()

    def discover(self, node_id: str) -> EnrolledNode:
        n = EnrolledNode(node_id=node_id, state="DISCOVERED")
        with self._lock:
            self._nodes[node_id] = n
        self._bus.publish("node.discovered", subject=node_id,
                          payload=n.to_dict(), component="enrollment")
        return n

    def transition(self, node_id: str, to: str) -> EnrolledNode:
        n = self._nodes[node_id]
        if to not in ALLOWED[n.state]:
            extra = ""
            if n.state == "DISCOVERED" and to == "TRUSTED":
                extra = (" -- A-042.1: DISCOVERED->TRUSTED is UNREACHABLE. "
                         "Admission is a gate, not a formality. A node that "
                         "appeared on the network has demonstrated that it can "
                         "send packets and nothing else.")
            raise AdmissionRefused(
                f"{n.state} -> {to} is not permitted (allowed: "
                f"{ALLOWED[n.state] or 'none, terminal'}){extra}")
        prev, n.state = n.state, to
        self._bus.publish("node.state_changed", subject=node_id,
                          payload={"node_id": node_id, "from": prev, "to": to},
                          component="enrollment")
        return n

    def admit(self, node_id: str, *, capability_floor_passed: bool,
              security_baseline_passed: bool,
              measured_tokens_per_sec: float | None = None,
              reattestation_due_ms: int | None = None) -> EnrolledNode:
        """The gate. A node that passes capability but fails security is Z2.

        A-042.2 is specific about this combination because it is the one people
        get wrong: a fast, capable, unpatched machine is tempting, and it lands
        in LIMITED_TRUST regardless of how much throughput it offers.
        """
        n = self._nodes[node_id]
        if n.state == "DISCOVERED":
            self.transition(node_id, "PENDING_ADMISSION")
        n.capability_floor_passed = capability_floor_passed
        n.security_baseline_passed = security_baseline_passed
        n.measured_tokens_per_sec = measured_tokens_per_sec
        n.reattestation_due_ms = reattestation_due_ms

        if capability_floor_passed and security_baseline_passed:
            self.transition(node_id, "TRUSTED")
            n.trust_zone = "Z1"
        else:
            self.transition(node_id, "LIMITED_TRUST")
            n.trust_zone = "Z2"
            self._bus.publish(
                "node.limited_trust", subject=node_id,
                payload={"node_id": node_id,
                         "capability_floor_passed": capability_floor_passed,
                         "security_baseline_passed": security_baseline_passed,
                         "trust_zone": "Z2",
                         "reason": ("a node passing the capability floor but "
                                    "failing the security baseline is Z2 however "
                                    "much throughput it offers")},
                component="enrollment")
        return n

    def check_z2_bound(self, node_id: str, action: str) -> None:
        """INV-TRUST-1. Raises for a Z2 node attempting a forbidden action."""
        if action not in Z2_FORBIDDEN:
            return
        n = self._nodes[node_id]
        if n.trust_zone != "Z2":
            return
        self._bus.publish(
            "security.z2_bound_enforced", subject=node_id,
            payload={"node_id": node_id, "action": action, "trust_zone": "Z2",
                     "reason": ("INV-TRUST-1: a Z2 node may not hold state, "
                                "issue commands, or receive secrets. Checked "
                                "per action because the three fail differently.")},
            component="enrollment")
        raise Z2BoundViolation(
            f"node {node_id!r} is Z2 and may not {action!r} (INV-TRUST-1)")

    def check_reattestation(self, node_id: str) -> bool:
        """A-042.5. Expiry demotes AND emits a capability degradation."""
        n = self._nodes[node_id]
        if (n.reattestation_due_ms is None
                or self._now_ms() < n.reattestation_due_ms
                or n.state != "TRUSTED"):
            return True
        self.transition(node_id, "LIMITED_TRUST")
        n.trust_zone = "Z2"
        self._bus.publish(
            "capability.degraded", subject=node_id,
            payload={"node_id": node_id, "from_state": "TRUSTED",
                     "to_state": "LIMITED_TRUST", "trust_zone": "Z2",
                     "cause": "reattestation_expired",
                     "note": ("emitted, not silent -- a fabric that shrinks "
                              "quietly is one where someone plans work for "
                              "capacity that is no longer there")},
            component="enrollment")
        return False

    def routable_nodes(self) -> list:
        return sorted(n.node_id for n in self._nodes.values() if n.routable())

    def get(self, node_id: str) -> EnrolledNode | None:
        return self._nodes.get(node_id)
