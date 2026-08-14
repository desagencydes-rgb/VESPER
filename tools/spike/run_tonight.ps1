# Tonight's unattended batch, 2026-08-14.
#
# Two jobs, run SEQUENTIALLY and not in parallel. SPIKE-008 is CPU- and disk-bound
# and the throughput matrix has a concurrent-load condition that is also CPU-bound;
# running them together would put SPIKE-008's load into the matrix's idle baseline
# and silently make the idle and concurrent conditions the same measurement.
#
#   1. SPIKE-008 full run   ~20 min   the spike that gates F0
#   2. SPIKE-001 3.1 matrix ~6 h      re-measured under harness schema_version 3
#
# WHY THE WHOLE MATRIX IS RE-RUN, not just `small`. schema_version 3 replaced the
# non-streaming request with a streamed one so checkpoints fire on the wall clock
# instead of on request returns. Streaming costs ~4% of throughput (measured: the
# same model and flags gave 102.63 tok/s non-streamed and 98.59 streamed), so a v2
# figure and a v3 figure are not comparable. Mixing them ACROSS TIERS is the worst
# case, because comparing tiers is exactly what the router does. One method, all
# tiers, one internally consistent matrix.
#
# v2 reports are kept under their original names. v3 lands beside them.

$ErrorActionPreference = 'Continue'
$REPO = 'C:\Projects\VESPER'
$LOG  = 'C:\Projects\VESPER-runtime\tonight.log'

function Say([string]$m) {
    $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Output $line
    Add-Content -Path $LOG -Value $line -Encoding utf8
}

Say "batch started"

Say "SPIKE-008 -- ADR-002 persistence validation (full: 10k writes, 500 crash trials)"
Push-Location $REPO
python tools\spike\validate_persistence.py all --writes 10000 --trials 500 --commits 500 `
    --out "$REPO\docs\planning\spike-results\SPIKE-008-adr002-validation.json" 2>&1 |
    ForEach-Object { Say "  $_" }
Pop-Location
Say "SPIKE-008 done"

Say "SPIKE-001 3.1 matrix under schema_version 3 -- 6 configs x 2 conditions x 3 runs"
Push-Location $REPO
& powershell -NoProfile -ExecutionPolicy Bypass -File tools\spike\run_tier_matrix.ps1 2>&1 |
    ForEach-Object { Say "  $_" }
Pop-Location
Say "matrix done"

Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Say "batch complete -- machine left ON (no shutdown this time; say the word and it can)"
