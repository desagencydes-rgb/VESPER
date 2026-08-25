# Working VESPER from a cloud session

Written 2026-08-25, when the owner moved this work to a cloud session.

**The short version: a cloud session can build everything and verify almost
nothing.** That is not a limitation to route around — it is the division of
labour, and getting it wrong wastes a session.

---

## 1. Why the keys are not there, and must not be

Anthropic's own guidance on cloud environments is explicit:

> cloud environments have no dedicated secrets store, so don't add API keys or
> other credentials — anyone who uses the environment can read the values

So `~/.config/vesper/secrets.env` stays on the owner's machine. It is outside
the repo by design and must remain so. **Do not add credentials to a cloud
environment's variables, do not commit an `.env`, and do not ask the owner to
paste a key into a session.**

### What that costs, stated honestly

On 2026-08-25 the design was corrected **four times in one hour**, and every
correction came from a live call rather than from reasoning:

- a `429` that meant `limit: 0` — never had any, not exhausted
- a `200` carrying empty content
- a provider reporting its own usage as zero on a call that worked
- a model catalogue listing models that `404`

**A session that cannot call a provider cannot find the fifth one.** It will
produce plans that look right, because looking right is exactly what the first
four did.

---

## 2. The division of labour

### A cloud session SHOULD

- Write and refactor code — `core/`, `routing/`, `tools/`
- Run every gate: `checks.py all`, `self_test.py`, both lints, the acceptance
  runners, the stress runners. **All of these are offline and all of them
  work** — they are the majority of this repo's verification
- Build against `tests/fixtures/provider-responses/` — real captured bytes for
  every trap found so far
- Write red-then-green cases, per `CHECKS.toml` discipline
- Read, plan, document, commit, push

### A cloud session MUST NOT

- Call a provider. There is no key, and there must not be
- Claim a provider behaviour it has not observed. **`INV-HW-2` applies to a
  cloud session exactly as it applies to a node profile** — a shape read off a
  docs page is declared, not measured
- Reach node 1. It is not on the tailnet from there
- Use the VESPER Claude account. Its credential is in the owner's macOS
  Keychain, machine-local, and correctly so

### Only the owner's machine can

- Make a live provider call
- Measure real token, neuron and latency cost
- Reach node 1
- Run `claude -p` / `codex exec` against the subscriptions

**So the loop is: build in the cloud, verify on the Mac, record the finding in
the repo.** The repo is the only channel between them, which is why findings
go into `MULTI_ROUTE.md` §13/§14 rather than staying in a transcript.

---

## 3. Keeping a cloud session going

1. **Configure the environment once.** Network access, environment variables
   (non-secret only), and a setup script that runs before work starts. The same
   environment is used by the web, `claude --cloud`, routines, mobile and
   desktop — configure it once and every surface inherits it.

2. **Give it a setup script that installs the toolchain**, so a session does
   not spend its first minutes rediscovering that `python3` is 3.9. See
   `.claude/cloud-setup.sh` in this commit.

3. **Work in branches and push.** A cloud session's output is commits. Nothing
   else survives it.

4. **Hand it a task with a verifiable end**, not an open brief. "Wire the
   chain-wide retry budget and make `self_test.py` go red then green on it" is
   a session. "Improve routing" is not.

5. **Anything it could not verify comes back as a question**, and gets answered
   by a live run on the Mac. That queue is the point of contact.

---

## 4. Self-management — what VESPER may change about itself

The owner's ask on 2026-08-25: VESPER should manage its own routing, effort,
context, models, providers, keys and MCPs, autonomously or on request.

That is right, and it splits into three tiers with a line that already exists
in this codebase (`INV-SELF-1..7`, `core/selfmod.py`).

### Tier A — runtime state. VESPER's own business, no approval

Reversible, inside the runtime, governed by nothing:

- which provider to try, and in what order
- reasoning effort **at or above the floor**
- context size and truncation strategy
- which model within an already-permitted set
- marking a rung unusable until a stated time
- rotating to a backup credential **already present** in the file
- retry pacing within the chain budget

This is where self-management actually lives, and it is most of what the owner
asked for.

### Tier B — governed config. Propose, never apply

`cost_policy.toml`, `capability_profiles.toml`, `narration.toml`,
`governed_surfaces.toml`, **and the effort `FLOOR` itself.**

VESPER writes the change plus its test into `workspace/`, runs the gate, and
files a proposal. The owner merges. A-030.6 requires that path to *succeed* —
this is the intended way for VESPER to improve its own governance.

> **Why the effort floor is Tier B and not Tier A, which is the important one.**
> VESPER feels budget pressure — that is the whole purpose of the quota ledger.
> A system that feels budget pressure *and* can lower its own quality floor
> will quietly get dumber, in exactly the situations where being sharp matters
> most, and every step will look locally justified. Separating them means
> budget pressure can change **routing** and can never change **standards**.
> `core/effort.py` raises rather than clamps for the same reason.

### Tier C — owner only

Creating or storing new credentials, account creation, privacy toggles,
anything on a provider's web console. VESPER can *detect* that a key is dead,
*route around it*, and *produce a step-by-step guide* — it cannot obtain a new
one, and a repair path that logs into the owner's provider console is one
injected error message away from being steered.

### On "or from my request"

An owner request moves an item from "VESPER decides" to "VESPER does". It does
**not** move it between tiers. Asking VESPER to lower the effort floor still
produces a proposal, because the tier is about *what kind of change it is*, not
about who wanted it. The owner can then merge it in one click — which is a
review, not an obstacle.
