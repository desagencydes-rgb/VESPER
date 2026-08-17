"""Read-time upcasting — ADR-002 D4/D5, and the reason the log is never rewritten.

WHAT THIS IS FOR. `INV-SCHEMA-2` says the event log is never rewritten and
migration is read-time upcasting. That is not a performance preference: an
offline migration step requires a moment when every node is present, and this
system explicitly allows the handset and the desktop to be absent for days
(SR-058). There is no such moment, so there can be no such step.

THE REGISTRY HOLDS NO STORE HANDLE, AND THAT IS THE ENFORCEMENT. `SPIKE-008`
criterion 8 requires that stored bytes never mutate on read. The way an
implementation fails that is by "fixing up" the record it just read while it
happens to have both the old and new form in hand. This class cannot: it is
given a dict and returns a new dict, and has no path to `StoreSet` to write
through. Same construction as `PredicateEvaluator`, which cannot call a model
because it was never handed anything that could.

A MISSING UPCASTER RAISES. It does not return the old form, it does not drop
the unknown field, and it does not log-and-continue. Criterion 8 names this
specifically because the silent version is the one that ships: a reader that
receives an N-1 body, finds no upcaster, and hands the caller a dict missing
the field the caller is about to read produces a `None` three call frames away
with nothing connecting it to a schema change.

UPCASTERS ARE GOVERNED CODE. They live here, under `core/`, inside
`GOVERNED_PATHS` -- deliberately, per ADR-002 D4: an upcaster is the one place
where a runtime able to edit its own code could rewrite history without ever
touching the append-only log.
"""

from __future__ import annotations

import copy
from typing import Callable

# The version writers emit. Mirrors ENVELOPE_SCHEMA_VERSION in bus.py, which is
# the envelope's own declaration; this module is version-agnostic and is told
# which version a reader wants.
Upcaster = Callable[[dict], dict]


class SchemaVersionError(Exception):
    """Base for every refusal in this module. Never raised bare."""


class MissingUpcaster(SchemaVersionError):
    """No upcaster registered for a step in the chain. SPIKE-008 criterion 8."""


class NewerThanReader(SchemaVersionError):
    """The stored body is NEWER than this reader. Downcasting is not a thing.

    A node that has been offline across a version bump reads records written by
    a newer node. There is no honest way to turn an N+1 body into an N one --
    the information a reader would have to invent is exactly the information
    the bump added -- so this refuses instead of guessing.
    """


class BrokenUpcaster(SchemaVersionError):
    """An upcaster returned a body that does not declare the version it claims.

    Without this check a chain whose step forgot to bump `schema_version` loops
    forever, and the symptom is a hung read rather than a bad migration.
    """


class UpcasterRegistry:
    """Upcasters keyed by `(event_type, from_version)`, applied on read.

    The key is the pair, not the type alone: a chain is a sequence of single
    steps, so an event type that has been through three bumps has three
    registered functions and the reader walks them in order.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], Upcaster] = {}

    def register(self, event_type: str, from_version: int,
                 fn: Upcaster) -> None:
        key = (event_type, int(from_version))
        if key in self._by_key:
            raise SchemaVersionError(
                f"an upcaster is already registered for {event_type!r} at "
                f"version {from_version}. Two upcasters for one step means the "
                "chain's result depends on registration order, which is not a "
                "property a migration may have.")
        self._by_key[key] = fn

    def registered(self) -> list[tuple[str, int]]:
        return sorted(self._by_key)

    def has(self, event_type: str, from_version: int) -> bool:
        return (event_type, int(from_version)) in self._by_key

    # ------------------------------------------------------------------ read

    def upcast(self, body: dict, *, to_version: int,
               event_type: str | None = None) -> dict:
        """Return the body at `to_version`. The argument is never modified.

        The deep copy is taken FIRST and every step runs against the copy, so
        an upcaster that mutates its input in place -- the ordinary way to
        write one -- still cannot reach the caller's dict, and through it the
        stored record.
        """
        etype = event_type or body.get("type")
        if etype is None:
            raise SchemaVersionError(
                "cannot upcast a body with no event type: the upcaster chain "
                "is keyed by (event_type, from_version) and half a key selects "
                "nothing.")

        current = copy.deepcopy(body)
        from_version = int(current.get("schema_version", 1))
        to_version = int(to_version)

        if from_version > to_version:
            raise NewerThanReader(
                f"{etype!r} was written at schema_version {from_version} and "
                f"this reader is at {to_version}. ADR-002 D5's dual-read window "
                "runs forward (readers accept N and N-1); there is no downcast, "
                "because the fields a bump added cannot be un-added by "
                "guessing.")

        guard = 0
        while from_version < to_version:
            fn = self._by_key.get((etype, from_version))
            if fn is None:
                raise MissingUpcaster(
                    f"no upcaster registered for {etype!r} from schema_version "
                    f"{from_version} to {from_version + 1}. The record is NOT "
                    "returned in its old form and no field is dropped: a reader "
                    "that silently hands back an N-1 body produces a None three "
                    "frames away with nothing connecting it to a schema change "
                    "(SPIKE-008 criterion 8).")
            current = fn(current)
            if not isinstance(current, dict):
                raise BrokenUpcaster(
                    f"the upcaster for {etype!r} at {from_version} returned "
                    f"{type(current).__name__}, not a body dict.")
            declared = int(current.get("schema_version", from_version))
            if declared <= from_version:
                raise BrokenUpcaster(
                    f"the upcaster for {etype!r} at {from_version} returned a "
                    f"body still declaring schema_version {declared}. Each step "
                    "must bump the version it produces, or the chain cannot "
                    "terminate.")
            from_version = declared
            guard += 1
            if guard > 64:                       # unreachable via the check above
                raise BrokenUpcaster(
                    f"the upcaster chain for {etype!r} did not converge on "
                    f"{to_version} within 64 steps.")

        if from_version != to_version:
            raise BrokenUpcaster(
                f"the chain for {etype!r} overshot: landed on {from_version}, "
                f"reader wants {to_version}.")
        return current

    def read(self, body: dict, *, to_version: int) -> dict:
        """`upcast` under the name a caller reaching for a reader will look for."""
        return self.upcast(body, to_version=to_version)
