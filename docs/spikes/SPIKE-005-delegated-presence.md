# SPIKE-005 — Delegated presence: programmatic call origination without deceptive impersonation

| | |
|---|---|
| **Status** | NOT_STARTED · **Time box** 5 working days · **Owner** Platform Engineer |
| **Question** | Is programmatic call/FaceTime-style delegated presence achievable on the target platform **without deceptive impersonation**? |
| **Blocks** | SR-031 disposition |
| **Requires hardware** | No — platform API research plus one working origination |

## 1. The constraint that is not negotiable

SR-031 authorises VESPER to act on the owner's behalf. **RB-012 forbids impersonation.** The corpus already resolved the semantics — *delegated attribution*: VESPER identifies itself as acting for the owner, and the recipient is never led to believe they are speaking with the owner. `REM-012` records this, and the registry note on SR-031 is explicit that this is a **feasibility item, not a contradiction**.

So the spike measures feasibility only. **The attribution requirement is not among the variables.** If a platform path exists that works only by presenting the owner's identity as the speaker, that path has failed this spike, not passed it cheaply.

## 2. Protocol

For each candidate channel — platform-native calling, VoIP/SIP, messaging with voice, a dedicated line:

| Question | Record |
|---|---|
| Can a call be originated programmatically? | API, entitlement, account requirement |
| Is the *originating identity* controllable and honest? | Whether VESPER can present as itself acting for the owner |
| What does the recipient see before answering? | Caller ID string, avatar, any owner-identifying element |
| Can an opening attribution be guaranteed? | Whether the first utterance is deliverable before recipient speech |
| Terms-of-service position | Whether automated origination is permitted at all |
| Recording and consent | Jurisdictional obligations if the call is recorded |

Then run **one end-to-end origination** on the most promising channel to a consenting test recipient, and record what the recipient actually experienced — not what the API documentation promised. Ask them directly whether at any point they believed they were speaking with the owner.

## 3. Pass criteria

1. At least one channel originates a call programmatically.
2. The recipient sees an identity that is **not** the owner's, or sees the owner's with an unambiguous "on behalf of" indication.
3. An attribution statement is delivered at the **start** of the call, before any request.
4. The consenting test recipient reports that they were never misled.
5. Terms of service permit the usage.

Criterion 4 is the one that matters. Criteria 1–3 are mechanisms; 4 is the property.

## 4. On fail

SR-031 stays `R_AND_D` with its existing limitation record and `SPIKE-005` reference. The outbox, reconciliation probe and reversibility classification (`REM-012`, `A-035`) are unaffected — they are channel-independent and proceed.

**Not permitted:** satisfying SR-031 by dropping the attribution requirement; presenting the owner's caller ID without an "on behalf of" indication; or delivering the attribution only if the recipient asks.

## 5. Deliverables

1. Per-channel feasibility table.
2. The end-to-end origination record, including the recipient's reported experience.
3. Either a viable channel with its attribution mechanism, or an updated limitation record for SR-031.
