---
name: verify-instruments-before-asking-the-owner
description: Prove a measurement tool works end-to-end yourself before asking the owner to run it; three field runs were burned on the same instrument
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c1e3b554-00df-4078-b85d-b38ba177f6fb
  modified: 2026-08-18T00:59:16.633Z
---

**Never ask the owner to run a measurement tool you have not exercised end-to-end
yourself.** On the night of 2026-08-17 they ran the SPIKE-004 ghost instrument
**three times** and every run was void for a different instrument defect — dead
tap zones, then a geometry the layout forced on wrongly, then a page they had
never reloaded so the fix was not on the device. They said *"bro i'm so full of
this, it's too much"*, and they were right to.

**Why:** each round trip costs them real minutes at a phone in a dark room, and
a defect that survives one round trip usually survives the next — the operator
cannot see what the instrument failed to draw. My cost for checking first is a
browser session; theirs is the evening.

**How to apply:**
- Drive the tool myself first — every mode, every control — and only then hand
  it over. A desktop run does not prove the target device, but it proves the
  plumbing.
- Make the instrument record what it *is*: SPIKE-004's page now posts a
  capability probe on load and the server injects the served file's own hash as
  a build stamp, so "you were running the old page" is a fact in the record
  rather than a question I have to ask.
- When a reading looks wrong, suspect the instrument before the operator. A
  commit had already blamed them for recording defaults when four of six tests
  were rendering nothing at all.
- If a tool has burned an owner's time twice, stop asking and park it. See
  [[lead-with-the-critical-path-not-the-interesting-thing]] — SPIKE-004 blocks
  nothing, and spending their evening on it was my error of prioritisation as
  much as of engineering.
