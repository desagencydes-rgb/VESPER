# What data this is built on, and how it could be wrong

**Read the last section first if you read nothing else.** The single largest
risk in this programme is not a wrong measurement. It is a *missing baseline* —
and it expires the day the memory system is switched on.

---

## 1. The baseline expires. Everything else can wait; this cannot

Every question worth asking later is comparative: *does memory make VESPER
better?* That question is unanswerable without a record of VESPER **without**
memory, on real turns, from the same owner.

That record can only be collected before the memory system exists. Once it is
on, there is no way back to a clean before. **Nothing else in this document is
time-critical. This is.**

What the baseline must capture, per turn, starting now:

| Field | Why |
|---|---|
| The question, verbatim | The only durable input |
| The answer, verbatim | What is being judged |
| Which rung answered, tokens in/out, latency | Cost comparison later |
| Whether the owner corrected, repeated, or rephrased | The only observable signal of failure |
| Whether VESPER said it did not know | Distinguishes a miss from a refusal |
| Time since previous turn | Decides whether a cache would have survived |

None of that needs the memory system. All of it becomes impossible to
reconstruct afterwards.

**Cost: near zero.** It is an append to a log that already exists.

---

## 2. What each dataset can and cannot tell us

### 2.1 Provider behaviour — measurable now, expires fastest

| Collect | Cannot tell us |
|---|---|
| Cache discount, TTL, hit rate, size threshold | Anything about next month. Vendor policy changes silently and without notice |
| Latency distribution per rung | Anything from a small sample — this has already burned us once |
| Real rate limits, from refusals | The published figure, which is a docs page and not a measurement |
| Token density per tokenizer | Density on a model we have not tested |

**Three specific traps in this dataset.**

**Measuring consumes what is being measured.** Probe calls spend the same quota
the probe is characterising. A batch of probes exhausts the fastest rung, and
the resulting 429 looks identical to a rung that is down.

**The provider's self-report is not the charge.** A cache field saying 8,224
tokens were cached and a rate-limit header saying 30 tokens were debited are
two different claims. Only the second one is about what the design can afford.
They can disagree, and the disagreement is the finding.

**One observation is not a distribution.** The same call to the same rung with
the same payload measured 0.84 s, then 115 s, then timed out, inside one hour.
Any figure quoted from fewer than a few hundred samples across hours is
decoration.

### 2.2 The memory corpus — the foundation, and the most contaminated

Every later conclusion rests on this, and it has four defects that do not go
away with more of it.

**It is produced by the thing being judged.** The automatic capture decides
what enters the corpus. If it is selective in any way, every later measurement
inherits that selection and reads as a property of memory rather than of the
recorder. There is no external corpus to check it against.

*Partial mitigation, and it must be built in from the first write:* capture
**everything** at the archive layer and let selection happen only at
projection. Then the selection is auditable after the fact, because the
unselected material is still there. A recorder that filters at write time
destroys the evidence needed to evaluate its own filtering.

**One owner.** Everything measured describes one person, one working style, one
vocabulary. Nothing here generalises and nothing should be phrased as if it
does.

**Weeks, not years.** The interesting failures — drift, erosion, a summary of a
summary of a summary — are slow. A four-week run cannot observe them. It can
only observe the first derivative and extrapolate, which is a guess.

**Volume ≠ coverage.** Ten thousand turns about routing say nothing about how
memory behaves on the parts of life VESPER has not been used for yet. Recording
the *distribution of topics* alongside the turns is what makes this visible
rather than invisible.

### 2.3 Ground truth — the hard one, and the one most likely to be faked

To know whether an answer was right, something must know the right answer.
There are only three sources, and they are not interchangeable.

| Source | Cost | What it actually tests |
|---|---|---|
| **Synthetic**: plant a fact, ask about it | Free | Whether the system can *retrieve what it stored* |
| **The owner labels a sample** | Expensive, and nobody sustains it | Whether the answer was *useful* |
| **Corrections in the wild** | Free, but rare and biased | Only failures the owner happened to notice |

**The distinction that matters, and it is easy to lose.** Synthetic questions
test retrieval. They cannot test *whether the right things were stored in the
first place* — a system that reliably retrieves the wrong 5% will score
perfectly on synthetic and be useless in practice. Any headline number from
synthetic data must carry that caveat attached, or it will be read as a quality
score.

**Owner labelling is the only source that tests usefulness, and it will not be
sustained.** Plan for a small, bounded, occasional sample — twenty answers,
rarely — rather than a labelling habit that quietly stops after week two and
leaves a dataset that looks complete and is truncated.

### 2.4 Failure records — structurally incomplete

Three detectors are planned: the owner repeats something already stored; the
owner corrects an answer; VESPER says it does not know.

**All three require the owner to react.** A confident wrong answer that is
simply accepted produces no event of any kind. That class of failure is
invisible to every instrument in this design, and it is the same shape as the
problem the memory system exists to solve.

This is not fixable by a better detector. The only thing that reaches it is
periodically checking a sample of answers against the record — which is
expensive, and which is the same thing as owner labelling above.

**One thing must be recorded at the moment it happens or it is lost:** whether
VESPER *declined* to answer or *could not*. Those are the same event in a log
and cannot be told apart afterwards.

### 2.5 Cost and power

| Collect | Note |
|---|---|
| Tokens per turn, split preamble / memory / question / reservation | The reservation dominates and is the cheapest thing to cut |
| Battery drain attributable to VESPER | Goal one is host lifetime; this is the only number that measures it |
| Wake assertions held | Historically the largest single lifetime win on this host |
| Per-sensor cost | Blocked — sensors do not exist |

---

## 3. What would falsify the design

Stated in advance, because a threshold chosen after seeing the data is not a
threshold.

| Claim | Falsified if |
|---|---|
| Resident memory is affordable | The discount does not survive a realistic gap between turns |
| Carrying memory helps | Answers with it score no better than the baseline |
| The index-plus-selection split is right | One flat block scores the same or better |
| Selection finds the right facts | It misses facts that were present and relevant |
| Re-summarising is stable | Size grows without bound, or recall falls as it shrinks |
| Memory is worth its cost | Turns per minute drop and answers do not improve |

---

## 4. Collection order

1. **Baseline logging, now.** Cheap, and it stops being collectable the moment
   the memory system is on.
2. **Provider characterisation.** Cheap, expires fastest, so re-run rather than
   trust an old figure.
3. **Automatic capture + the failure record.** These generate the corpus; every
   blocked question waits on them.
4. **Weeks of ordinary use.** No shortcut exists.
5. **Synthetic ground truth**, built from the corpus once it has content.
6. **One small owner-labelled sample**, to check the synthetic score against
   something that measures usefulness rather than retrieval.

---

## 5. The honest summary

Three things in this plan are load-bearing and none of them are measurements.

- **The baseline is collectable only before the build**, and it is the control
  group for every later claim.
- **The corpus is generated by the system being judged**, so capture must be
  total at the archive and selective only at projection — otherwise the
  evidence needed to audit the selection is destroyed by the selection.
- **The most important failure mode is invisible to every planned instrument.**
  Any conclusion drawn from this data is a statement about failures the owner
  noticed, and must be written that way.
