---
name: lay-out-records-before-working-on-them
description: "Before working on any VESPER spike, ADR, or measurement, summarize what it actually says before asking for a decision or starting work"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e67d9ac4-f143-4554-883c-36afecd47f73
  modified: 2026-08-14T17:06:14.952Z
---

Before working on any VESPER record — a spike protocol, an ADR, a measurement
report — lay out what it actually says first: what it decides, what the options
were, what accepting it commits to. Do this unprompted, before asking for a
decision or starting the work.

**Why:** The corpus is ~37,800 lines across 161 files. The owner cannot hold the
measures and records in their head, and should not have to go read a file to
follow what we are doing or to make a call on it. On 2026-08-14 they were asked
to ratify `ADR-007` and to accept `ADR-002` with only the IDs named — they had to
ask what they were. Naming an ID is not laying out a decision.

**How to apply:** When a record comes up, summarize in plain language: what it
decides, what the real alternatives were and why they lost, and — for anything
needing owner sign-off — the concrete consequences they are agreeing to live
with. Distinguish clearly between what the record covers and what it does not,
since adjacent records get conflated (ADR-007 is device *identity*, not the
encrypted tunnel, which is SPIKE-009). Do this before the ask, not after.

Related: [[vesper-owner-wants-speed-and-density]]
