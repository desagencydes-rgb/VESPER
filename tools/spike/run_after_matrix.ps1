# Phase 2 of tonight's work. Waits for the 3.1 matrix to finish, then closes out
# the rest of SPIKE-001 on this node.
#
# WHY IT WAITS RATHER THAN RUNNING NOW. Everything here touches memory, disk or
# GPU counters, and the matrix currently running has an IDLE condition whose whole
# purpose is to be idle. Starting these alongside it would put this script's load
# into the matrix's idle baseline and make the idle and concurrent conditions the
# same measurement -- the exact error 3.1's concurrent variant exists to detect.
#
# Sections closed here:
#   3.2  memory headroom, with and without a model resident
#   3.3  storage: sequential/random write, and the synchronous=FULL commit figure
#        that SPIKE-008 1.3 consumes
#   3.6  thermal and power, to the extent this node can report them
#
# 3.4 is DECLARED by owner policy (2026-08-14), not measured. 3.5 is skipped for
# this node by owner direction. Neither is pending.

$ErrorActionPreference = 'Continue'
$REPO = 'C:\Projects\VESPER'
$OUT  = "$REPO\docs\planning\spike-results"
$LOG  = 'C:\Projects\VESPER-runtime\tonight.log'
$P2   = 'C:\Projects\VESPER-runtime\phase2.log'

function Say([string]$m) {
    $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Output $line
    Add-Content -Path $P2 -Value $line -Encoding utf8
}

Say "phase 2 armed -- waiting for the 3.1 matrix to report complete"

# Poll rather than assume a duration: the matrix is ~6 h but a fit-probe backoff
# on a strong-tier config can extend it, and finishing early should not leave the
# machine idle either.
$deadline = (Get-Date).AddHours(9)
while ((Get-Date) -lt $deadline) {
    if ((Test-Path $LOG) -and (Select-String -Path $LOG -Pattern 'matrix done' -Quiet)) { break }
    Start-Sleep -Seconds 60
}
if (-not (Select-String -Path $LOG -Pattern 'matrix done' -Quiet)) {
    Say "matrix did not report complete within 9 h -- stopping rather than measuring against an unknown machine state"
    exit 1
}
Say "matrix complete; starting phase 2"

Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5

Push-Location $REPO

# --- 3.2 memory headroom, no model resident -------------------------------
Say "3.2 memory headroom -- baseline, no model resident"
python tools\spike\profile_node.py memory --out "$OUT\SPIKE-001-3.2-memory-baseline.json" 2>&1 |
    ForEach-Object { Say "  $_" }

# --- 3.3 storage ----------------------------------------------------------
Say "3.3 storage -- sequential and random write on C:"
python tools\spike\profile_node.py storage --storage-path C:\Projects\VESPER-runtime `
    --out "$OUT\SPIKE-001-3.3-storage.json" 2>&1 | ForEach-Object { Say "  $_" }

# The synchronous=FULL commit figure 3.3 is asked to hand to SPIKE-008. Measured
# by the SPIKE-008 harness because that is where the five-store schema lives --
# one implementation, not two that can drift.
Say "3.3 checkpoint commit at synchronous=FULL (the figure 3.3 hands to SPIKE-008)"
python tools\spike\validate_persistence.py checkpoint --commits 1000 2>&1 |
    Select-Object -First 40 | ForEach-Object { Say "  $_" }

# --- 3.6 thermal and power ------------------------------------------------
# Recorded with an explicit null-and-reason wherever this node cannot report a
# figure. 3.6 asks for battery drain and noise; this is a mains-powered desktop
# with no wall meter, so those are structurally unavailable here rather than
# merely unmeasured, and saying so is the honest result.
Say "3.6 thermal and power readback"
$therm = @{
    schema_version = 1
    spike = "SPIKE-001"; section = "3.6"
    generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    sustained_load_before_throttle = "NOT_OBSERVED -- minute 10 matched minute 1 in every 3.1 run at draft, small and standard, in both conditions. This node did not throttle within a 10-minute window, so no throttle point exists to record."
    battery_drain_per_hour = $null
    battery_drain_reason = "Mains-powered desktop. No battery. Structurally not applicable to this node class, not merely unmeasured."
    wall_power_draw_watts = $null
    wall_power_reason = "No wall meter available. SPIKE-011 names one as its instrument; until then every power figure in the planning docs is marked EXPECTED, never MEASURED."
    noise_at_sustained_load = $null
    noise_reason = "No calibrated meter, and a phone-app reading is not a measurement. Recorded as unmeasured rather than estimated."
    owner_usable_during_load = "DECLARED, not measured -- the 3.4 policy lock treats this node as VESPER-dedicated, so 'usable for the owner during load' is not the condition this node is operated under."
}
try {
    $t = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop
    $therm.acpi_thermal_zones_celsius = @($t | ForEach-Object { [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1) })
} catch {
    $therm.acpi_thermal_zones_celsius = $null
    $therm.acpi_thermal_reason = "MSAcpi_ThermalZoneTemperature unavailable on this board/driver. Common on desktop boards; not a failure of the measurement."
}
$therm | ConvertTo-Json -Depth 5 | Set-Content -Path "$OUT\SPIKE-001-3.6-thermal-power.json" -Encoding utf8
Say "  wrote SPIKE-001-3.6-thermal-power.json"

Pop-Location
Say "phase 2 complete -- SPIKE-001 3.2, 3.3 and 3.6 closed on this node"
Say "machine left ON"
