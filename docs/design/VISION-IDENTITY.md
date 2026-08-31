# Vision, identity and presence — owner's design, 2026-08-31

**Status: DESIGN ONLY. Hardware-blocked (cameras).** Recorded now so it is not
re-derived badly later. This is the owner's design, captured close to verbatim
in structure; the annotations are engineering notes on it.

**This is about PEOPLE, not nodes.** It is world-and-people recognition, and it
is deliberately not bound to any particular device. A camera happens to live on
some machine; the identity model does not belong to that machine.

---

## The shape

**Two models, not one.** They answer different questions and have different
costs, and merging them would make the cheap one as expensive as the dear one.

| Model | Answers |
|---|---|
| **Face authentication** | Is this the owner's face? |
| **Body / movement identification** | Is this the owner, from shape, posture, gait, clothing — when no face is available |

**Both run standalone, on whatever device holds the camera**, and talk to VESPER
rather than living inside it. That is what keeps the host light: the machine
VESPER answers from does not also carry the vision load.

## Presence is a flag in memory, not a per-turn check

The model runs **on first sight**, decides, and sets a flag. VESPER then reads
presence from memory like any other fact — no identity check on every turn, which
is what made the earlier layered design too expensive to run.

| Observation | Flag |
|---|---|
| Owner recognised | present |
| No owner (not necessarily no face) | absent |
| Owner recognised alongside others | present, with unknown people |
| A face that is not the owner's | someone else at the machine |
| A person but no usable face | snapshot to VESPER; identify by body, movement, clothing |

## When it is not the owner

A face that is not the owner's means someone else is at the machine. VESPER
**warns the owner on another node** — the phone is the best fit — and **calls**
if no other device is reachable. J3 carries a SIM and will be VESPER's, so the
call is VESPER's to place.

## Learning people

The vision model builds a fingerprint **from the face**. Given a name and a
profile — the owner introducing someone — VESPER profiles them from then on, and
recognises them in future interactions. Identity is therefore extensible by
introduction rather than by configuration.

---

## Engineering notes on this design

**It replaces the layered check that was dropped.** An earlier proposal ran
camera, then voice, then a fingerprint prompt, per interaction. It was dropped
as too expensive per turn and too heavy on the system — correctly. Flag-on-first-
sight has the same coverage at a fraction of the cost, because the expensive
question is asked when the world changes rather than when the owner speaks.

**It satisfies both halves of failure mode 8**, which the layered design did not.
"Present with unknown people" answers *who else is here* — a question speaker
verification structurally cannot answer, because a verified owner can have
someone standing beside them.

**Open, and worth deciding before it is built:**

- **Degradation when the camera node is off.** Presence then has no source.
  Absent, unknown, or last-known? `INV-COORD-2` says an expired fact reads
  UNKNOWN and never falls back to its last value, which argues for unknown --
  and unknown must fail toward withholding, not toward disclosing.
- **Where the flag is written.** It is a world fact (`world.owner.presence`),
  which makes it a sensor of the GATED class -- a camera needs a reason, and
  "the world changed" is one.
- **The models never run inside the always-on filter.** They are gated and
  event-driven. A model in the always-on path is the prompt-injection surface
  the sensor doctrine exists to refuse.
