#!/bin/sh
# SPIKE-013 criteria 1, 5, 6 -- the power run. ONE command, run with sudo.
#
# WHY THIS IS A SCRIPT AND NOT A LIST OF STEPS. The measurement needs
# `powermetrics` (root) sampling WHILE the ground renders (the owner's session),
# and the two have to be aligned in time or the slices are meaningless. Done by
# hand that is: open a terminal, start powermetrics, switch, start the cost
# check, remember which phase began when, stop both. Every one of those is a
# place to mis-order something, and a mis-ordered power run looks exactly like a
# valid one afterwards.
#
# IT REFUSES RATHER THAN WARNS, on the two conditions SPIKE-013's own on_fail
# calls impermissible:
#
#   * ON MAINS. "Not permitted: a figure measured on mains reported as the
#     battery figure." A run that starts plugged in is not a run to be labelled
#     carefully -- it is a run that must not happen.
#   * A SLEEPING MACHINE. If the display sleeps mid-run the phases after it
#     measure a dark screen, and the numbers are lower and wrong rather than
#     absent, which is worse.
#
# IT DOES NOT COMPUTE A VERDICT. It captures two aligned artifacts and says
# where they are. Reading them against the criteria is a separate reviewed act,
# for the same reason promotion into a contract is: a script that both produced
# the numbers and graded them is one that can be tuned until it passes.

set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$REPO/docs/planning/spike-results"
STAMP="$(date +%Y%m%dT%H%M%S)"
PM_LOG="$OUT/SPIKE-013-power-$STAMP.txt"
PHASE_LOG="$OUT/SPIKE-013-phases-$STAMP.txt"
VESPER="$REPO/app/VESPER.app/Contents/MacOS/VESPER"
AGENT="ai.vesper.island"

SECONDS_PER_PHASE="${VESPER_COST_SECONDS:-60}"
REPEATS="${VESPER_COST_REPEATS:-3}"

if [ "$(id -u)" -ne 0 ]; then
  echo "REFUSED: run with sudo. powermetrics needs root; the render does not," >&2
  echo "         so the ground is driven back as the console user." >&2
  echo "  sudo $0" >&2
  exit 2
fi
if [ -z "${SUDO_USER:-}" ]; then
  echo "REFUSED: no SUDO_USER. Run as 'sudo $0' from your own shell, not as a" >&2
  echo "         root login -- the ground must render in YOUR session." >&2
  exit 2
fi
if [ ! -x "$VESPER" ]; then
  echo "REFUSED: no built VESPER at $VESPER. Build first." >&2
  exit 2
fi

POWER_SOURCE="$(pmset -g batt | head -1)"
case "$POWER_SOURCE" in
  *"AC Power"*)
    echo "REFUSED: on mains. SPIKE-013 on_fail: a figure measured on mains" >&2
    echo "         reported as the battery figure is NOT PERMITTED." >&2
    echo "         Unplug, wait for '$(printf "Battery Power")', run again." >&2
    exit 2 ;;
esac
CHARGE="$(pmset -g batt | sed -n 's/.*[^0-9]\([0-9]\{1,3\}\)%.*/\1/p' | head -1)"
if [ -n "$CHARGE" ] && [ "$CHARGE" -lt 25 ]; then
  echo "REFUSED: battery at ${CHARGE}%. A run that ends in a low-power state" >&2
  echo "         measures the throttle, not the composite." >&2
  exit 2
fi

echo "SPIKE-013 power run"
echo "  power source   $POWER_SOURCE"
echo "  phases         baseline + ${REPEATS}x(centre, attendant, dispersed, absent) + composite"
echo "  phase length   ${SECONDS_PER_PHASE}s"
echo "  powermetrics   $PM_LOG"
echo "  phase log      $PHASE_LOG"
echo ""

# The supervised instance owns the ground. A second one would render a second
# field and the sampler cannot tell two grounds apart from one.
if launchctl print "gui/$(id -u "$SUDO_USER")/$AGENT" >/dev/null 2>&1; then
  echo "  booting out the supervised island for the duration"
  launchctl bootout "gui/$(id -u "$SUDO_USER")/$AGENT" || true
  RESTORE_AGENT=1
else
  RESTORE_AGENT=0
fi

cleanup() {
  [ -n "${PM_PID:-}" ] && kill "$PM_PID" 2>/dev/null || true
  [ -n "${CAF_PID:-}" ] && kill "$CAF_PID" 2>/dev/null || true
  if [ "$RESTORE_AGENT" = "1" ]; then
    echo "  restoring the supervised island"
    launchctl bootstrap "gui/$(id -u "$SUDO_USER")" \
      "/Users/$SUDO_USER/Library/LaunchAgents/$AGENT.plist" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Keep display and system awake for the whole run. -d display, -i idle,
# -m disk, -s system, -u asserts user activity.
# `-is`, NEVER `-dimsu`. The `-d` in that flag set prevents DISPLAY sleep, and
# this script is meant to hold a MEASUREMENT open, not to keep a screen lit in
# a room somebody is sleeping in. The owner reported exactly that on
# 2026-09-06: "make sure the pc can turn its screen off, all this time it's
# been on, it didn't let me fucking sleep."
#
# `-i` prevents idle system sleep and `-s` prevents sleep on AC, which is the
# whole of what a long run needs. The display stays free to go dark, which
# changes nothing about the measurement.
caffeinate -is &
CAF_PID=$!

# cpu_power and gpu_power are criteria 1 and 5; battery is criterion 6. One
# second, because a phase is tens of seconds and the criteria are read from the
# WORST sample -- a 5 s default would give a dozen samples per phase to find it in.
powermetrics --samplers cpu_power,gpu_power,battery -i 1000 \
  --show-process-gpu --hide-cpu-duty-cycle > "$PM_LOG" 2>&1 &
PM_PID=$!

# AN INSTRUMENT'S SELF-REPORT IS NOT EVIDENCE. powermetrics backgrounding
# successfully is not powermetrics sampling; it exits non-zero into the log on
# an unsupported sampler and the run would proceed against an empty file.
sleep 4
if ! kill -0 "$PM_PID" 2>/dev/null; then
  echo "REFUSED: powermetrics exited immediately. Its output:" >&2
  head -20 "$PM_LOG" >&2
  exit 1
fi
if ! grep -q "Sampled system activity" "$PM_LOG" 2>/dev/null; then
  echo "REFUSED: powermetrics is running but has produced no sample after 4 s." >&2
  head -20 "$PM_LOG" >&2
  exit 1
fi
echo "  powermetrics sampling (pid $PM_PID), first sample confirmed in the log"
echo ""

{
  echo "SPIKE-013 phase log"
  echo "run_started_utc  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "power_source     $POWER_SOURCE"
  echo "charge_percent   ${CHARGE:-unknown}"
  echo "powermetrics_log $(basename "$PM_LOG")"
  echo "seconds_per_phase $SECONDS_PER_PHASE"
  echo "repeats          $REPEATS"
  echo "---"
} > "$PHASE_LOG"

# Driven back as the console user: the ground must render in the owner's
# session, and a root-owned window would not composite into it.
sudo -u "$SUDO_USER" "$VESPER" --cost-check \
  --cost-seconds "$SECONDS_PER_PHASE" --cost-repeats "$REPEATS" \
  2>&1 | while IFS= read -r line; do
    printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$line"
  done | tee -a "$PHASE_LOG"

echo ""
echo "run_ended_utc    $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$PHASE_LOG"
kill "$PM_PID" 2>/dev/null || true
wait "$PM_PID" 2>/dev/null || true

SAMPLES="$(grep -c "Sampled system activity" "$PM_LOG" || true)"
echo "  powermetrics stopped -- $SAMPLES samples captured"
echo ""
echo "  Two aligned artifacts, both timestamped UTC:"
echo "    $PM_LOG"
echo "    $PHASE_LOG"
echo ""
echo "  Reading them against criteria 1, 5 and 6 is the next step and is"
echo "  deliberately NOT done here."
