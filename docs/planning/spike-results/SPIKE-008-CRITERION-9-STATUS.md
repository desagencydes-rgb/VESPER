# SPIKE-008 criterion 9 — status, and what is actually left

**Criterion 9:** *All five stores open on every candidate node class.*
**§1.6 adds:** byte-identical checksums after transfer.

## Why this could not close on either node so far

Both node 1 (Windows desktop) and node 2 (Kali laptop) ran the full blocking
suite and both recorded §1.6 as `NOT_RUN`. That was correct, not an omission:
**no single machine can answer this question.** It is a claim about a file that
has moved between node classes, so the test is an *emit* on one node and a
*verify* on another. `validate_persistence.py` runs on one node at a time and
would have gone on reporting `NOT_RUN` forever.

Node 2's own write-up made exactly this point and declined to claim closure.
That was the right call and this instrument is the follow-through.

## The instrument

`tools/spike/portability_probe.py` — three subcommands:

| | |
|---|---|
| `emit --dir <d>` | writes the five stores, checkpoints them so each `.db` is self-contained, records a manifest |
| `verify --dir <d>` | opens each store on *this* node, re-derives digests, checks the append-only guards survived |
| `control --dir <d>` | the negative control — see below |

**Two digests, deliberately, because §1.6's "byte-identical" conflates two
different claims:**

- `file_sha256` — did the bytes survive the transfer. A store failing this is
  corrupt.
- `logical_sha256` — a hash over the rows as SQLite reads them back in a
  deterministic order. Did the *data* survive, on this node's SQLite build.

**`logical_sha256` is the load-bearing one.** Two nodes can legitimately
disagree on file bytes — page layout, freelist state and format version headers
all differ between builds — while agreeing perfectly on every row. Reporting
only the file digest would fail a store that is perfectly portable; reporting
only the logical digest would miss a truncated transfer. Both are recorded, and
a logical match with a file mismatch is **a pass**, reported as such.

The probe also re-checks that the **append-only triggers survived the
transfer**. A store whose rows all match but whose ADR-002 D9 guard is missing
is not the same store, even though every digest agrees.

## The negative control, and the first version of it was worthless

The first control skipped the WAL checkpoint on the theory that the tail would
stay in a `-wal` sidecar and be lost when only the `.db` was copied. **It
passed** — because SQLite checkpoints on last-connection-close. The WAL was
always folded back in before anything was copied. It demonstrated nothing.

That is the same failure as the SPIKE-008 fencing control that initially passed:
**a test that has never been red is not evidence.**

The control now reproduces the scenario that actually loses data — copying the
stores **while the runtime still holds them open**, with `wal_autocheckpoint=0`,
which is exactly how a live ADR-002 D10 survival carry would be taken from a
running node. Measured on node 1:

| | |
|---|---|
| rows in the live store | 500 |
| rows in the copied store | **200** |
| **rows silently lost** | **300** |
| WAL bytes left behind | 45,352 |
| copied store opens | yes |
| `PRAGMA integrity_check` on the copy | **`ok`** |

**That last row is the point.** The copy opens cleanly and passes
`integrity_check` while missing 300 committed rows. A carry procedure that
checks only "does it open" would certify this store as good. `control` exits
non-zero if the loss does *not* occur, because a control that cannot demonstrate
the failure cannot certify its absence.

Report: `SPIKE-008-portability-negative-control-node1.json`.

## What is in the repository now

`SPIKE-008-portability-artifact/` — five stores emitted on node 1, checkpointed
and self-contained, plus `MANIFEST.json` carrying the expected digests and the
emitting node's identity. **The repository is the transfer medium**, which makes
the transfer itself auditable in git history rather than a file someone copied.

## What closes it, per node class

```
python tools/spike/portability_probe.py verify \
  --dir docs/planning/spike-results/SPIKE-008-portability-artifact \
  --out docs/planning/spike-results/SPIKE-008-portability-verify-<node>.json
```

| Node class | State |
|---|---|
| node 1 — Windows desktop | **emitted.** A same-host verify passes but the probe labels it as contributing nothing, by design |
| node 2 — Kali laptop (Linux, SQLite 3.46.1) | **PENDING** — one command, no setup, closes the second class |
| `foreground_only` (iPhone / J3) | **BLOCKED** — no Python host on either device today. This is the class criterion 9 names explicitly, and it is the one that will actually be hard |

**Criterion 9 does not close until the `foreground_only` class is answered.**
Two server-class nodes agreeing is real evidence and is not the criterion. If
that class cannot host a store, §3's disposition already applies and is not a
failure: it becomes a presence endpoint only, never a survival host — a
`capability_profiles` change, not a requirement change.

## Still open on this spike, unchanged

- ~~**Criterion 8** (`§1.5` read-time upcasting) — needs the F0 runtime codec.
  Not a hardware block; it is waiting on code that does not exist yet.~~
  **CLOSED 2026-08-16.** F0 shipped and the code now exists: `core/codec.py`.
  `validate_persistence.py upcasting` runs it with a non-compliant control that
  fails as required. Evidence:
  `docs/planning/spike-results/SPIKE-008-criterion8-upcasting.json`. Worth
  noting how long it sat: the block was lifted the moment F0 landed, and the
  deferral text went on reading as a block for two days after it had expired.
- **Power-cut crash trials.** Both nodes used `SIGKILL`, which does not exercise
  the drive's write cache the way pulling power does. The SQLite/WAL layer is
  validated; the storage device's flush-on-power-loss behaviour is not, on
  either node.
