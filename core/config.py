"""Runtime configuration, and the difference between measured and declared.

ONE RULE CARRIES THIS FILE: a value that was MEASURED and a value that was
DECLARED are different kinds of thing, and the config may never quietly turn
one into the other. INV-HW-2 forbids declaring what was not measured, and
CI-034 guards `capability_profiles.toml` against exactly that. So every
capability figure here carries its provenance, and a caller asking for a
measured figure that does not exist gets an error rather than a default.

The tempting design is `get("tokens_per_sec", default=50)`. That default is a
declared number wearing a measured number's clothes, and by the time it reaches
a routing decision nobody can tell which it was.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


class NotMeasured(Exception):
    """A measured figure was requested and only a declared one exists."""


@dataclass(frozen=True, slots=True)
class Provenanced:
    """A value that knows where it came from."""

    value: Any
    provenance: str  # "measured" | "declared" | "default"
    source: str

    def require_measured(self) -> Any:
        if self.provenance != "measured":
            raise NotMeasured(
                f"value from {self.source} is {self.provenance!r}, not measured. "
                "INV-HW-2: a declared figure may not stand in for a measured one."
            )
        return self.value


@dataclass(slots=True)
class RuntimeConfig:
    node_id: str
    data_dir: Path
    lease_ttl_ms: int = 15_000
    heartbeat_ms: int = 2_000
    checkpoint_budget_ms: float = 200.0
    max_clock_regression_ms: int = 300_000
    # Trust zone of this node's key storage sets a CEILING on what it may hold
    # (ADR-007). Declared per node, never inferred from what happens to work.
    trust_zone: str = "Z2"

    @classmethod
    def from_env(cls, **overrides: Any) -> "RuntimeConfig":
        node_id = (overrides.pop("node_id", None)
                   or os.environ.get("VESPER_NODE_ID"))
        if not node_id:
            raise ValueError(
                "VESPER_NODE_ID is unset. ADR-007 D1: node_id is a fingerprint of "
                "this node's public key, never a self-asserted name -- so there is "
                "no safe default and one is not invented here."
            )
        data_dir = Path(overrides.pop("data_dir", None)
                        or os.environ.get("VESPER_DATA_DIR")
                        or (REPO.parent / "VESPER-runtime" / "state"))
        return cls(node_id=node_id, data_dir=Path(data_dir), **overrides)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "data_dir": str(self.data_dir),
            "lease_ttl_ms": self.lease_ttl_ms,
            "heartbeat_ms": self.heartbeat_ms,
            "checkpoint_budget_ms": self.checkpoint_budget_ms,
            "max_clock_regression_ms": self.max_clock_regression_ms,
            "trust_zone": self.trust_zone,
        }


def load_capability_profile(path: Path | None = None) -> dict[str, Provenanced]:
    """Read capability_profiles.toml, keeping provenance attached.

    Fields the corpus marks UNKNOWN come back as declared-with-no-value rather
    than being dropped, so a caller that needs a measured figure fails loudly
    instead of silently routing on a hole.
    """
    p = path or (REPO / "contracts" / "policy" / "capability_profiles.toml")
    if not p.exists():
        return {}
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    out: dict[str, Provenanced] = {}

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            measured = node.get("measured")
            for k, v in node.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    walk(v, key)
                elif k != "measured":
                    prov = "measured" if measured is True else "declared"
                    if v == "UNKNOWN":
                        prov = "declared"
                    out[key] = Provenanced(v, prov, p.name)

    walk(raw, "")
    return out
