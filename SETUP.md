# VESPER — repository setup (human actions)

Three things engineering deliberately did **not** do, because they need you.

## 1. Initialise version control

Not done unprompted. The repository is a working tree with no git history.

```bash
cd /c/Projects/VESPER
git init
git add -A
git commit -m "VESPER engineering foundation: remediation, specification, contracts, verification"
git branch -M main
```

## 2. Enable branch protection (requires a hosting provider)

`CODEOWNERS` and `.github/workflows/ci.yml` exist but enforce nothing until `main` is protected on a host. Required settings:

- require pull request review before merge;
- require status checks to pass (`vesper-ci`);
- require review from Code Owners;
- no force-push, no direct pushes to `main`.

Then replace `@owner` in `CODEOWNERS` with your account.

> **Why this matters more here than usual.** REM-004's boundary has four layers. Layers 1–3 are structural and already specified. This step is what makes the *review* layer real, and `docs/COC/`, `contracts/policy/`, `verification/traceability/` and `safety/` are owner-only for a reason: they are the surfaces a compromised or over-eager runtime would target first.

## 3. Self-test every gate before trusting it

**A check that has only ever been green is not evidence.** Each check declares its self-test in `verification/ci/CHECKS.toml`. Run at least these three and confirm each fails red:

```bash
# CI-021 — should FAIL (exit 1)
sed -i 's/^FREE_TIME       = \["free"\]/FREE_TIME       = ["free", "paid"]/' contracts/policy/cost_policy.toml
python tools/ci/checks.py cost-policy ; echo "exit=$?"
git checkout contracts/policy/cost_policy.toml

# CI-003 — should FAIL: delete any SR row from the registry
# CI-002 — should FAIL: edit an SR body in docs/COC/ without a baseline bump
```

`CI-021` and `CI-028` have already been demonstrated red in this working tree; `CI-002` is specified but not yet implemented (see `python tools/ci/checks.py status`).

## Running the checks locally

```bash
python tools/traceability_lint.py                 # CI-003, engineering profile
python tools/traceability_lint.py --profile release   # adds owner-decision blockers
python tools/ci/checks.py all --self-test
python tools/ci/checks.py status                  # implemented vs specified-but-PENDING
python tools/vesper_ids.py                        # authoritative identifiers from the locked COC
```

Requires Python ≥ 3.11 (`tomllib`). No third-party dependencies, by design — CI must run on any node without an install step.

---

## Status of this checklist (2026-08-12)

**`git init` is DONE.** The repository was initialised on 2026-08-12 with `core.autocrlf=false` and **no `.gitattributes` normalisation** — deliberately. The corpus is genuinely mixed CRLF/LF, byte-exactness is load-bearing for the mutation harnesses in `tools/ci/self_test.py`, and `* text=auto` would have rewritten roughly a third of the files on checkout. The full verification suite has been re-executed from a fresh clone: `47/47` red runs, zero working-tree residue.

**Still outstanding, and all of it is host-side or owner-side:**

| # | Action | Who | What stays PENDING until then |
|---|---|---|---|
| 1 | Create the remote and push | Owner | Nothing mechanical; CI cannot run without a host |
| 2 | Enable branch protection with required status checks | Owner | `CI-002` (source immutability), `CI-044` (governed-surface owner review) |
| 3 | Replace `@owner` in `CODEOWNERS` with the real account | Owner | `CI-044` routing. Engineering cannot know the handle and must not guess one |

**Do not flip `CI-002` or `CI-044` to implemented merely because git now exists.** One commit is not review history, and branch protection is a setting on the host, not a file in the tree. `CI-016` enforces the half that *is* checkable without a host: every governed path has a `CODEOWNERS` line, so no governed path is left unrouted when protection is switched on.
