# Overnight report — 2026-08-30

**The memory build order is complete. Steps 1 through 7, all gated, all wired
into the running process.** What follows is what landed, what was found, and
what is waiting on the owner.

**Read this first if you read nothing else:** this machine was on **battery,
53%, discharging, no charger attached** at 01:5x while running unattended with
idle sleep disabled. `core/host_probes.py` found it — the first real reading the
new sensor layer took was about its own host. Plug it in before the next long
run.

---

## Where the build stands

| # | Build-order item | State | Gate |
|---|---|---|---|
| 1 | L2 graph store | done, wired | `CI-074` |
| 2 | Updater + miss recorder | done, wired | `CI-076` |
| 3 | Redactor | done, wired at the choke point | runs, **unregistered** — see below |
| 4 | Block A + Block B rendering | done, wired | `CI-077` |
| 5 | Chooser | done, wired | `CI-081` |
| 6 | Compactor · arbiter · forgetter | done | `CI-080` · `CI-078` · `CI-079` |
| 7 | Sensors | done, wired | `CI-082` |

**Gates: 56 checks, 206 self-tests, both lints green.** Every check landed with
an executed red run in `self_test.py`; nothing was declared.

Memory runs in the live app. `~/Library/Application Support/VESPER/l2.db` was
created by the supervised runtime, carries the full schema, and no
`memory.unavailable` event was published.

## Invariants that gained a CI enforcer tonight

| Invariant | Was enforced by | Now also |
|---|---|---|
| `INV-MEM-1` | `A-003` only | `CI-078` |
| `INV-EVID-3` | `A-003` only | `CI-082` |
| `INV-DIFF-1` | `CI-069` | `CI-081` |
| `INV-PRIV-5` | `A-037`, `A-039` | `CI-080` |
| `INV-LOSS-3` | `CI-049`, `A-050` | `CI-079` |

## Findings — the useful half

**The ~18 ms in `HANDOFF_MEMORY_BUILD.md` is the wrong row.** It is the
full-text stage in isolation. The actual block-B query measures **31.55 / 50.36 /
87.35 ms at 100k facts** — over the 25 ms budget at every depth, including depth
1. L2 is specified to hold 10⁴–10⁵, so the design is comfortable at the bottom
of its own range and breaks at the top. **Consequence not previously written
down: the compactor is load-bearing for latency, not only for context size.**
Raw output now in `docs/spikes/data/l2_query_probe.txt` — it was the only probe
storing none.

**The measuring instrument's own query carried two defects into the design.**
`reach` unions on `(id, d)`, so an entity reached at two depths returns each of
its facts twice — block B holds 3–5 facts and would have spent slots on repeats.
And `WHERE f.privacy = 'private'` would have made a `personal` fact permanently
unreachable. Neither was visible to the probe: `stage_full` counted rows, and a
duplicate count reads as a hit.

**Erase does not destroy content, and the architecture currently forbids it
doing so.** `UPDATE` and `DELETE` on the `log` store are refused at the storage
layer (ADR-002 D9), so an erased value stays in L3. Two consequences: a
reprojection resurrects it unless it reads the tombstones (it now does, gated by
`CI-080`), and **a credential that reached L2 must be rotated, not merely
erased.** A real erasure needs an owner-authorised path through the append-only
guard.

**Three ways of testing that erasure turned out to be untestable.** A rowid
lookup on `fact_fts` is vacuous (external-content tables resolve through the
base table). A raw `MATCH` and a scan of the shadow blocks are both
non-deterministic — identical erasures disagreed depending only on what else had
been written first, because FTS5 segment merging decides when a term leaves
index storage. The gate asserts `select()`, the only deterministic path; the
residue limit is recorded in `core/forgetter.py` rather than gated.

**The TCC responsible-process trap**, walked into immediately after writing the
warning about it. Running the bundle's executable from a shell prints the
correct bundle identifier and TCC still attributes to the shell: the microphone
returned "granted" with no dialog (inherited from Terminal) and the speech
request died with SIGABRT complaining about a usage string that was present.
**Both readings failed in the direction that looks like success.** `open -n` is
the fix; now in `CLAUDE.md`.

**Two of my own checks were wrong and the harness said so.** `CI-077` matched
the literal `"facts under"`, which renders `"1 fact under"` for a single-fact
node — a check whose result depended on how much the owner happened to say about
one topic. And its middle-is-empty assertion tested that block B led and the
question trailed, both of which stay true while arbitrary content sits between
them. A negative control that passes is a defect, not a relief.

## Waiting on the owner

1. **The scoping decision, and it is the big one.** The source requirement set
   does not fit in fourteen days on top of memory. Cut explicitly, extend, or
   defer — but cutting by silence is the one option the handoff forbids.
2. **`INV-PRIV-7`, proposed.** No invariant in the corpus says a credential may
   not reach a provider; the handwritten source never mentions credentials at
   all. The redactor's check therefore RUNS and is deliberately **not**
   registered in `CHECKS.toml`, because registering it means declaring an
   invariant it enforces and inventing one is the manufactured claim
   `ci-registry` exists to refuse. Ratify it and the check registers.
3. **Darija voice quality** — needs your ears, and it is **rendered and waiting**:
   run `~/VESPER-darija-ab/play.sh`. Four voices (`Majed` ar_001 MSA, `Thomas`
   fr_FR, `Amelie` fr_CA, `Samantha` en_US as the floor) across four lines,
   grouped by line so you hear the same sentence four ways. All 16 files
   verified as real audio with `afinfo`, not with an exit code. The `recall`
   line matters most — it is VESPER reading a memory back to you, which is what
   it will say most often once the corpus fills.
4. **STT route.** Recommended and unconfirmed: Groq for Darija, Apple on-device
   for `en-US`. `ar-MA` is not available on-device here, so Apple's own path
   egresses outside `ModelGateway` and outside the redactor.
5. **A log-backed span type.** `Claim.support` wants a `SourceSpan` — a byte
   range in a file with a `verify()` that re-reads it. An L2 fact's provenance
   is a log sequence. They do not compose, so memory-derived claims carry no
   support and `ClaimChecker` will refuse them under a gated policy class.
   Arbitration is unaffected.
6. **Provider accounts** — six, if each subsystem gets its own.
7. **Ambient recording of other people.** Half-settled: "speech from an
   unidentified person is never stored as the owner's memory" is decided, and
   failure mode #8 says "nothing implements either".

## What is deliberately not claimed

Every memory-quality property here rests on design argument, not measurement.
The corpus that would settle S2 and S4 started accumulating tonight — the
updater captures and the miss recorder pairs what VESPER did with what memory
held — and it accumulates at the speed the owner talks to VESPER.

Nothing was pushed. Local `git bundle` backups are in `~/VESPER-backups/`.
