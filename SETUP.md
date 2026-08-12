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

**All three host-side actions are now DONE (2026-08-12, same day):**

| # | Action | Status | Evidence |
|---|---|---|---|
| 1 | Create the remote and push | **DONE** | `github.com/desagencydes-rgb/VESPER`, private. `vesper-ci` executed on the host and passed — the first execution of `.github/workflows/ci.yml` anywhere, on Linux/Python 3.14 rather than the Windows tree it was written on |
| 2 | Enable branch protection with required status checks | **DONE** | Active branch ruleset on the default branch: PR required, 1 approval, **code-owner review required**, `gates` status check required, deletion and force-push blocked, **`bypass_actors` empty — the rule binds the owner too**. Read back from the API, not from this document |
| 3 | Replace `@owner` in `CODEOWNERS` with the real account | **DONE** | `@desagencydes-rgb` across all 25 lines |

**`CI-002` and `CI-044` REMAIN `PENDING`, and that is not an oversight.** The distinction is worth stating precisely, because it is the one this corpus exists to keep:

- **The merge boundary is now enforced.** GitHub will refuse a merge to `main` without an owner review and a green `gates` run. That is real, and it is a genuine upgrade over documentation.
- **No artifact in this tree verifies that it was enforced.** `CI-044` is the check that would read the merge record and assert an owner review happened. It does not exist yet. Crediting it as implemented because the platform setting is on would be exactly the `CI-022` defect this corpus was built to catch: **a control credited to a check that does not perform it.**

The practical consequence: a silent change to the host configuration is currently invisible from inside the repository. `CI-016` still enforces the half that is checkable without a host — every governed path has a `CODEOWNERS` line, so nothing is left unrouted.

**Side effect worth knowing:** with `bypass_actors` empty, direct pushes to `main` now fail for everyone including the owner. All changes go through a pull request. This is the intended shape — it is the same boundary that will later stop the VESPER runtime from merging its own proposals.
