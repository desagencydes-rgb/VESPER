#!/bin/bash
# Setup for a VESPER cloud session. Runs before work starts.
#
# WHY THIS EXISTS: on the owner's Mac `python3` is 3.9 and every gate in this
# repo dies on `import tomllib` -- while `checks.py` still exits 0 while doing
# it, so a session that trusts the exit code records a pass it never had.
# A cloud image may differ. This script does not assume; it CHECKS, and it
# fails loudly rather than letting a session run gates that silently no-op.
set -u

echo "=== VESPER cloud session setup ==="

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import tomllib' 2>/dev/null; then PY="$c"; break; fi
  fi
done

if [ -z "$PY" ]; then
  echo "FAIL: no python with tomllib (needs >= 3.11)."
  echo "      Every gate in this repo will fail on import AND may still exit 0."
  echo "      Install python3.11+ before running anything."
  exit 1
fi
echo "  python: $PY ($($PY --version 2>&1))"

echo
echo "=== gates available offline (no credentials needed) ==="
cat <<EOT
  $PY tools/ci/checks.py all          # 34 checks
  $PY tools/ci/self_test.py           # red-then-green, 88 cases
  $PY tools/traceability_lint.py
  $PY tools/reference_lint.py
  $PY verification/run_f0_acceptance.py   # ... f1 .. f6
  $PY verification/stress_placement.py    # 160k assertions
  $PY verification/stress_fabric.py       # 180k assertions
EOT

echo
echo "=== NOT available here, and must not be attempted ==="
cat <<'EOT'
  * live provider calls  -- no credentials in a cloud environment, by design
  * node 1               -- not on the tailnet from here
  * claude -p / codex exec against the subscriptions

  Build against tests/fixtures/provider-responses/ instead. Those are REAL
  captured responses, not hand-written doubles. A provider behaviour you have
  not observed is DECLARED, not measured -- INV-HW-2 applies here too.

  Read docs/planning/CLOUD_SESSION.md before starting.
EOT
