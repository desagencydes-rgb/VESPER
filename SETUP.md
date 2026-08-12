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
