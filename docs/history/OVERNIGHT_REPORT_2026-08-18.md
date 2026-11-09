# VESPER — overnight session report, night of 2026-08-17/18

> ## ✅ THIS MACHINE IS SAFE TO POWER OFF — AND WAS POWERED OFF AT THE END
>
> **The endurance run is not in flight.** `A-029` is F5's gate, seventh of nine
> in the build order, and is scheduled for **week 3** alongside the work it
> actually gates. The 23 h partial is banked as evidence. Nothing on node 1 was
> holding a clock tonight.
>
> **The 09:00 alarm is on node 2 and node 1's shutdown does not touch it.** It
> was verified armed, read-only, at 01:35 — see §4.

---

## 1. The headline

**F6's placement half exists.** `DF-PLACE` and `DF-SURVIVAL-PROFILE` were
specified in REM-014 and implemented nowhere; `A-048` and `A-017` had no
coverage at all. Both now run — nine cases, both mandatory negative controls,
plus a property harness that found a defect all nine cases missed.

**And six CI checks stopped being prose.** `ENFORCED TODAY` moved **17/118 →
23/118**, which is the number a reader actually judges the release by.

| | |
|---|---|
| Commits tonight | 6, on `feat/f0-f1-endurance` |
| New runtime code | `core/placement.py` (~560 lines) |
| New verification | `run_f6_acceptance.py`, `stress_placement.py` |
| CI checks implemented | 15/56 → **21/56** |
| Invariants enforced today | 17/118 → **23/118** |
| Self-tests | 47/47 → **55/55** red-then-green |
| Acceptance gates green | F0, F1, F2, F3, F4, F5, **F6** |
| Owner action needed tonight | **none** |

---

## 2. What the placement work found

The nine hand-written `A-048` cases all passed while the module still contained
three defects. Each was found by something other than the cases.

**1. A ratio test on a magnitude whose ratios were meaningless.** The scalar
score was additive with availability weighted `+1000`, so a node with **twenty
times** the measured throughput (20 → 400 tok/s) scored 9% higher and placement
returned `KEEP`. Caught by case 48.1 — but only after four earlier cases had
passed over the same broken function.

**2. A survival core that came back.** The core was filled greedily with
everything else, making it *partially* satisfiable. The property harness found
the consequence: at pressure 0.75 one core member fell out for want of storage,
and at 0.95 three others stopped fitting, released their budget, and the first
one **reappeared**. A core that returns as conditions worsen is not a core.
`DF-SURVIVAL-PROFILE` reserves it in one step; so does the code now.

**3. A product name in a policy path.** `CI-007` caught my own module naming a
device, which `INV-HW-1` forbids. Rewritten in profile terms — what matters
about that device is `availability_class = foreground_only`, and a rule written
about the product stops applying the day the product changes.

### Two gaps in `DF-PLACE` itself, resolved and recorded

- **`hosts` filters on trust zone alone**, which makes `A-048.4` unsatisfiable:
  a `Z0 foreground_only` node would be a top-ranked *full* host and survival
  would never be entered on any topology. `INV-PLACE-3` ("no **full host**
  reachable") and `INV-TRUST-2` (design vs runtime survival) cohere only if such
  a node is never a full host. Encoded in `is_full_host`, with the alternative
  reading named in case the corpus meant the literal one.
- **The degradation bypass is listed after two gates that have already
  returned** — dead code as written. `INV-PLACE-2`'s prose governs, so it is
  evaluated first.

### The stress harness earned its place, and its own first property was wrong

320,000 property assertions over 40,000 randomised fabrics, 300 flap trials ×
4 simulated hours, monotonicity over 4,000 strictly-better node pairs — with
**branch coverage asserted**, because a run in which nothing ever relocated
would satisfy every property while testing nothing.

Its determinism check re-ran `decide()` without passing `hysteresis`, so 87
"non-deterministic: Keep then Relocate" reports were the harness asking two
different questions. Kept in the file: *a property that does not hold its inputs
fixed is not testing determinism.*

---

## 3. The six CI checks, and what `TR-067` caught

| | | |
|---|---|---|
| `CI-022` | cost-class-nonnull | `INV-COST-4` |
| `CI-025` | action-has-trigger | `INV-TRIG-1` |
| `CI-032` | verification-criteria-typed | `INV-VERIF-3` |
| `CI-047` | idea-retirement-reason | `INV-IDEA-4` |
| `CI-019` | interlock-independence | `INV-STOP-2` |
| `CI-023` | evaluator-no-model-capability | `INV-TRIG-2` |

Each refuses the **silent** version of its failure. `CI-022`'s failure mode is
not a missing field, it is an unclassified profile being *read* as free — so a
default and a nullable type are refused alongside the field leaving `required`.
`CI-047` asserts `RETIRED → disposition_reason` structurally, because the
property description already said MANDATORY and a description does not reject a
document.

**`CI-025` took three attempts and the first two were wrong instructively.**
Flagging every `autonomy.*` publication went red on a violation *diagnostic*
with no trigger in scope. Rescoped to the code's own convention — an event whose
**subject** is a trigger must carry `trigger_id` in its payload — it then
reported a correct site, because the payload came from a helper's return and the
resolver only understood literals. It now follows one hop **within the calling
function's scope**: searching the whole module had found a different `probe`, a
dict comprehension inside the helper itself.

Unresolvable payloads return neither true nor false. Guessing true lets a real
omission through; guessing false cries wolf until someone disables the check.

**`TR-067` fired three times** — an implemented check that no requirement names.
Each was placed by evidence rather than convenience: the SR already listed the
invariant's *other* declared enforcer (`SR-045`/`A-021`, `SR-049`/`A-031`,
`SR-042`/`A-011`+`A-029`).

---

## 4. The alarm, and what is fragile about it

Verified at 01:35, **read-only, no sound played and no volume touched**.
Evidence: `docs/planning/spike-results/ALARM-0900-armed-verification-20260818.json`

```
pid 32626   alarm_night.py fire --at 2026-08-18 09:00 --cap-s 900
            reparented to init, sleeping, preflight at 08:55
            logind no-sleep drop-in present · xfce presentation-mode true
            6 systemd inhibitors · analog sink live
```

> **The one thing worth knowing: it is a detached process, not a timer.** There
> is **no systemd timer and no cron entry** behind it. If the process dies or
> node 2 reboots, there is no alarm and nothing will announce that. It waits in
> a single long `time.sleep()` computed from the wall clock at launch.
>
> Not changed tonight. Adding a second firing path at 01:40 risks either a
> double alarm or a broken one, on the night it has to work. **Worth fixing on a
> day when nothing depends on it.**

---

## 5. SPIKE-004 — parked, and honestly

**Zero valid readings.** Every result file on disk is defaults recorded through
a broken instrument. Three field runs were lost last night in three different
ways, all of them the instrument's fault:

1. `#tapzones` used `inset: 0` (Chrome 87) on a Chrome 55 handset, so it
   measured **0 × 0** and the side taps had no hit target. Four of six tests
   also rendered nothing.
2. The first `baseline` pass ran with `flip` and `mirror` **on** — meaningless
   where there is no fold — so it measured how small *reversed* text can be
   read. `glyph height` came back at the largest value on the scale.
3. The next two ran on a page loaded before the fix, from a tab nobody
   reloaded, and nothing in the record said so.

Fixed: an on-load capability probe, a server-injected build stamp so a stale
page cannot hide, forced-off transforms in `baseline`, and three non-wrapping
layout buttons. **It blocks nothing** — SPIKE-004 §1 is explicit that an
unavailable `volumetric` rung is a degradation the ladder already handles.

Owner action, when convenient and not before: a flat clear sheet, and ~10
minutes for a baseline pass plus a ghost pass.

---

## 6. What is still blocked, and by what

| Item | Blocker | Changed tonight? |
|---|---|---|
| `A-034.2` partition, both sides live | Needs the network partitioned on the node holding the 09:00 alarm | **Yes** — topology and key-based SSH both exist now; only the timing is wrong |
| `A-045` network fabric | A person using each machine normally while enrolled | No |
| `SPIKE-004` readings | Owner's eyes + a flat clear sheet | Instrument fixed and proven on-device |
| `SR-016`, `SR-017` | F6 network-fabric work; `A-045` holds the assertions | No |
| `SR-034` | Deliberate — the corpus's worked example of a requirement correctly held below `SPECIFIED` | No |
| MacBook, iPhone app, cameras | Hardware | No |

---

## 7. Numbers, each produced by a command

```
tools/traceability_lint.py                     PASS   0 errors
tools/traceability_lint.py --profile release   FAIL   3 errors, DEPTH only, all deliberate
tools/reference_lint.py                        PASS   0 errors, 136 files
tools/reference_lint.py --self-test            PASS   5/5
tools/ci/checks.py all                         PASS   25/25
tools/ci/self_test.py                          PASS   55/55 red-then-green
tools/ci/checks.py status                             21/56 implemented, 35 PENDING
tools/ci/checks.py ci-registry                        ENFORCED TODAY: 23/118
verification/run_f0..f6_acceptance.py          PASS   all seven
verification/stress_placement.py               PASS   320,000 property assertions
```
