"""Device registry — endpoints as PROFILES, never as product names.

INV-HW-1 AGAIN, AND IT IS THE WHOLE FILE. A device registry is the most natural
place in a system to write down product names, and the place where doing so
does the most damage: every routing, placement and degradation decision then
reads a name that will be wrong the moment the hardware is replaced. The
registry stores *classes* — `availability_class`, `key_storage_class`,
`spatial_class` — so substituting hardware is a profile change, never a
migration.

A device is registered by what it can be OBSERVED to do. `capabilities` are
measured or declared with the distinction recorded (INV-HW-2), and an unmeasured
capability is UNAVAILABLE rather than assumed.

INV-TRUST-2: NO CONTINUITY-CRITICAL CAPABILITY ON A FOREGROUND-ONLY NODE. A
phone that can be swiped away is not a survival host, however capable it is
while the screen is on. `assign` refuses that placement rather than warning
about it, because a warning during setup is a warning nobody reads at 3 a.m.
when the process the warning was about has been killed.

KEY STORAGE SETS A TRUST-ZONE CEILING (ADR-007). A node whose keys sit in a
file cannot be Z0 no matter how trusted its owner is, because the ceiling is a
property of where the secret lives, not of intent.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus

AVAILABILITY = ("always_on", "on_demand", "foreground_only", "unavailable")
KEY_STORAGE = ("hardware_backed", "os_keychain", "file_based")
SPATIAL = ("volumetric", "planar", "linear", "voice_only", "none")

# ADR-007: key storage sets the CEILING on the trust zone a node may occupy.
TRUST_ZONE_CEILING = {"hardware_backed": "Z0", "os_keychain": "Z1",
                      "file_based": "Z2"}

# INV-TRUST-2. These may never be placed solely on a foreground-only node.
CONTINUITY_CRITICAL = ("tasks", "memory", "alarms", "autonomy_queue", "policy")


class PlacementRefused(Exception):
    """A placement that INV-TRUST-2 forbids. Refused, not warned about."""


@dataclass(slots=True)
class DeviceProfile:
    node_id: str
    availability_class: str
    key_storage_class: str
    spatial_class: str = "none"
    has_microphone: bool = False
    has_speaker: bool = False
    capabilities: dict = field(default_factory=dict)
    measured: dict = field(default_factory=dict)

    def trust_zone_ceiling(self) -> str:
        return TRUST_ZONE_CEILING.get(self.key_storage_class, "Z2")

    def is_survival_host(self) -> bool:
        """Can this node hold continuity-critical state alone?"""
        return self.availability_class in ("always_on", "on_demand")

    def capability(self, name: str) -> Any:
        """UNMEASURED IS UNAVAILABLE (INV-HW-2), never assumed present."""
        if not self.measured.get(name, False):
            return None
        return self.capabilities.get(name)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id,
                "availability_class": self.availability_class,
                "key_storage_class": self.key_storage_class,
                "spatial_class": self.spatial_class,
                "trust_zone_ceiling": self.trust_zone_ceiling(),
                "is_survival_host": self.is_survival_host(),
                "capabilities": {k: v for k, v in self.capabilities.items()
                                 if self.measured.get(k, False)},
                "unmeasured": sorted(k for k in self.capabilities
                                     if not self.measured.get(k, False))}


class DeviceRegistry:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._devices: dict[str, DeviceProfile] = {}
        self._placements: dict[str, list] = {}
        self._lock = threading.RLock()

    def register(self, profile: DeviceProfile) -> DeviceProfile:
        if profile.availability_class not in AVAILABILITY:
            raise ValueError(f"availability_class must be one of {AVAILABILITY}")
        if profile.key_storage_class not in KEY_STORAGE:
            raise ValueError(f"key_storage_class must be one of {KEY_STORAGE}")
        if profile.spatial_class not in SPATIAL:
            raise ValueError(f"spatial_class must be one of {SPATIAL}")
        with self._lock:
            self._devices[profile.node_id] = profile
        self._bus.publish("device.registered", subject=profile.node_id,
                          payload=profile.to_dict(), component="devices")
        return profile

    def get(self, node_id: str) -> DeviceProfile | None:
        return self._devices.get(node_id)

    def assign(self, domain: str, node_ids: list, *,
               subject: str = "placement") -> dict:
        """Place a state domain on one or more nodes.

        INV-TRUST-2 is enforced on the SET, not per node: a continuity-critical
        domain placed on a foreground-only node AND an always-on node is fine;
        placed only on foreground-only nodes it is not. Checking per node would
        reject the legitimate case and checking nothing would accept the fatal
        one.
        """
        profiles = [self._devices[n] for n in node_ids if n in self._devices]
        missing = [n for n in node_ids if n not in self._devices]
        if missing:
            raise ValueError(f"unregistered node(s): {missing}")

        if domain in CONTINUITY_CRITICAL:
            hosts = [p for p in profiles if p.is_survival_host()]
            if not hosts:
                payload = {
                    "domain": domain, "nodes": node_ids,
                    "reason": ("INV-TRUST-2: no continuity-critical capability may "
                               "be assigned solely to foreground-only nodes. A node "
                               "that can be swiped away is not a survival host, "
                               "however capable it is while the screen is on."),
                    "availability_classes": [p.availability_class for p in profiles],
                }
                self._bus.publish("placement.refused", subject=subject,
                                  payload=payload, component="devices")
                raise PlacementRefused(payload["reason"])

        with self._lock:
            self._placements[domain] = list(node_ids)
        result = {"domain": domain, "nodes": node_ids,
                  "survival_hosts": [p.node_id for p in profiles
                                     if p.is_survival_host()]}
        self._bus.publish("placement.assigned", subject=subject, payload=result,
                          component="devices")
        return result

    def placement(self, domain: str) -> list:
        return list(self._placements.get(domain, ()))

    def survival_hosts(self) -> list:
        return sorted(p.node_id for p in self._devices.values()
                      if p.is_survival_host())

    def all(self) -> list:
        return [p.to_dict() for p in self._devices.values()]
