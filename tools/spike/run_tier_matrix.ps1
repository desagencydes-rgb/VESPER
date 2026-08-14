# SPIKE-001 3.1 tier matrix -- runs every tier in both load conditions, unattended.
#
# Each tier is 3 runs x 10 min x 2 conditions = ~60 min. The whole matrix is ~5 h.
# Designed to be started and left alone.
#
# It deliberately does NOT touch capability_profiles.toml. Reports land in
# docs/planning/spike-results/, outside NORMATIVE_ROOTS. Promotion is a separate act.

$ErrorActionPreference = 'Continue'
$RT      = 'C:\Projects\VESPER-runtime'
$EXE     = "$RT\llama.cpp\llama-server.exe"
$MODELS  = "$RT\models"
$OUT     = 'C:\Projects\VESPER\docs\planning\spike-results'
$REPO    = 'C:\Projects\VESPER'
$BUILD   = 'b10405-e79e4bf66'

# -c must exceed the tier's generation length plus prompt room; the harness refuses
# to run otherwise rather than silently measuring a truncated request.
#
# ngl 99 = all layers on GPU. Neither `strong` candidate fits 7.2 GB of measured VRAM,
# so both get a partial offload -- that is the tier's purpose, not a failure. Their ngl
# values are STARTING ESTIMATES corrected by the fit probe below.
#
# MODEL SELECTION, revised 2026-08-13 after the owner asked whether the first picks
# were chosen wisely. They were not. Two defects in the original set:
#
#   1. MIXED TOKENIZER FAMILIES. Llama-3.2-1B/3B and Llama-3.1-8B share a tokenizer,
#      but Mistral-24B does not. Speculative decoding (SR-056, the stated reason the
#      `draft` tier exists at all) requires draft and target to share a tokenizer, so
#      the original set could never speculate into its own top tier. A single-family
#      ladder keeps that option open instead of foreclosing it before it is tried.
#
#   2. DENSE-ONLY `strong`. On a VRAM-starved node this is the wrong default. A dense
#      24B touches every parameter per token, so the half that lives in system RAM is
#      paid for on every token. A Mixture-of-Experts model activates a fraction of its
#      parameters per token -- 30B total, ~3B active -- so offloaded weight costs far
#      less compute per token. EXPECTED to matter a great deal here; measured rather
#      than assumed, which is why BOTH candidates are in the matrix.
#
# Llama-3.2-3B is kept at `small` and `draft` because it is already on disk, costs no
# download, and gives a cross-family reference point.
$MATRIX = @(
  @{ tier='small';    model='Llama-3.2-3B-Instruct-Q4_K_M.gguf';              ctx=2048; ngl=99; label='small-llama3B'  },
  @{ tier='draft';    model='Qwen3-1.7B-Q4_K_M.gguf';                         ctx=1024; ngl=99; label='draft-qwen1.7B' },
  @{ tier='draft';    model='Llama-3.2-3B-Instruct-Q4_K_M.gguf';              ctx=1024; ngl=99; label='draft-llama3B'  },
  @{ tier='standard'; model='Qwen3-8B-Q4_K_M.gguf';                           ctx=8448; ngl=99; label='standard-qwen8B'},
  @{ tier='strong';   model='Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf';        ctx=8448; ngl=12; label='strong-moe30B'  },
  @{ tier='strong';   model='Mistral-Small-24B-Instruct-2501-Q4_K_M.gguf';    ctx=8448; ngl=16; label='strong-dense24B'}
)

function Stop-Server {
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
}

function Start-Server([string]$modelPath, [int]$ctx, [int]$ngl) {
    $a = @('-m',$modelPath,'-ngl',$ngl,'-fa','on','--cache-type-k','q8_0','--cache-type-v','q8_0',
           '-c',$ctx,'--parallel','1','--host','127.0.0.1','--port','8080')
    Start-Process -FilePath $EXE -ArgumentList $a -RedirectStandardOutput "$RT\server.log" `
                  -RedirectStandardError "$RT\server.log.err" -WindowStyle Hidden
    for ($i=0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-RestMethod 'http://127.0.0.1:8080/health' -TimeoutSec 3 -ErrorAction Stop
            if ($r.status -eq 'ok') { return $true }
        } catch {}
    }
    return $false
}

function Get-GpuMiB {
    $s = (Get-Counter "\GPU Adapter Memory(*)\Dedicated Usage" -ErrorAction SilentlyContinue).CounterSamples |
         Where-Object CookedValue -gt 0 | Sort-Object CookedValue -Descending | Select-Object -First 1
    if ($s) { [math]::Round($s.CookedValue/1MB,1) } else { $null }
}

Write-Output "SPIKE-001 3.1 TIER MATRIX  --  started $(Get-Date -Format o)"
Write-Output ("{0} configurations, ~60 min each, ~{1} h total" -f $MATRIX.Count, ($MATRIX.Count))
Write-Output ""

Stop-Server
$idleGpu = Get-GpuMiB
Write-Output "GPU at rest: $idleGpu MiB"
Write-Output ""

foreach ($cfg in $MATRIX) {
    $mp = Join-Path $MODELS $cfg.model
    Write-Output ("======== {0}  (tier={1}, -c {2}, -ngl {3}) ========" -f $cfg.label, $cfg.tier, $cfg.ctx, $cfg.ngl)

    if (-not (Test-Path $mp)) { Write-Output "  SKIP - model not present: $mp"; Write-Output ""; continue }
    Write-Output ("  model: {0} MB" -f [math]::Round((Get-Item $mp).Length/1MB,1))

    Stop-Server
    $ngl = $cfg.ngl

    # Fit probe. A partial-offload tier can fail to start, or start with fewer layers
    # than asked. Backing off is recorded, not silently absorbed -- the layer split is
    # part of what `strong` is measuring.
    if (-not (Start-Server $mp $cfg.ctx $ngl)) {
        Write-Output "  server did not become healthy at -ngl $ngl; backing off"
        foreach ($try in @(12, 8, 4, 0)) {
            Stop-Server
            Write-Output "  retry at -ngl $try"
            if (Start-Server $mp $cfg.ctx $try) { $ngl = $try; Write-Output "  started at -ngl $try"; break }
            $ngl = $null
        }
        if ($null -eq $ngl) {
            Write-Output "  FAILED to start at any offload level. Recording as a finding and moving on."
            Get-Content "$RT\server.log.err" -Tail 15 -ErrorAction SilentlyContinue
            Write-Output ""
            continue
        }
    }

    $loadedGpu = Get-GpuMiB
    Write-Output ("  healthy. GPU {0} -> {1} MiB (delta {2} MiB)" -f $idleGpu, $loadedGpu, [math]::Round($loadedGpu - $idleGpu,1))

    $launch = "llama-server.exe -m $($cfg.model) -ngl $ngl -fa on --cache-type-k q8_0 --cache-type-v q8_0 -c $($cfg.ctx) --parallel 1 --host 127.0.0.1 --port 8080  [build $BUILD, Vulkan; GPU delta $([math]::Round($loadedGpu - $idleGpu,1)) MiB]"

    foreach ($cond in @('idle','concurrent')) {
        $dest = Join-Path $OUT ("SPIKE-001-3.1-v3-{0}-{1}.json" -f $cfg.label, $cond)
        Write-Output ("  -- {0} condition -> {1}" -f $cond, (Split-Path $dest -Leaf))
        Push-Location $REPO
        if ($cond -eq 'concurrent') {
            python tools\spike\profile_node.py throughput --tier $cfg.tier --minutes 10 --runs 3 --concurrent --launch-command $launch --out $dest | Out-Null
        } else {
            python tools\spike\profile_node.py throughput --tier $cfg.tier --minutes 10 --runs 3 --launch-command $launch --out $dest | Out-Null
        }
        Pop-Location
        if (Test-Path $dest) {
            $j = Get-Content $dest -Raw | ConvertFrom-Json
            $t = $j.throughput
            Write-Output ("     gen {0} tok/s   wall {1} tok/s" -f $t.median_sustained_tokens_per_sec, $t.median_effective_tokens_per_sec)
            if ($t.run_results[0].error) { Write-Output ("     ERROR: {0}" -f $t.run_results[0].error) }
        } else { Write-Output "     no report written" }
    }
    Write-Output ""
}

Stop-Server
Write-Output "GPU released: $(Get-GpuMiB) MiB"
Write-Output "TIER MATRIX COMPLETE  --  $(Get-Date -Format o)"
