#!/bin/sh
# Keep VESPER running: at login, after a reboot, after a crash.
#
# WHY A PLAIN LaunchAgent AND NOT SMAppService. SMAppService is the modern API and
# gives a nicer Login Items entry -- the app's own name and mark instead of a
# generic `exec` icon. It also could not be made to spawn this app: launchd killed
# every attempt with OS_REASON_CODESIGNING, verified across ad-hoc and self-signed
# certificates, with and without the hardened runtime, with the LaunchServices
# record refreshed and the registration rebuilt after every signature change. The
# same binary launched by hand runs perfectly.
#
# A plain LaunchAgent spawns it and keeps it alive, verified by killing it with -9
# and watching launchd return it under a new pid. Working beats tidy.
#
# Reversible: `--uninstall`.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LA="$HOME/Library/LaunchAgents"
ID=ai.vesper.island
BIN="$REPO/app/VESPER.app/Contents/MacOS/VESPER"

if [ "$1" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$ID" 2>/dev/null || true
  rm -f "$LA/$ID.plist"; echo "removed $ID"; exit 0
fi

[ -x "$BIN" ] || { echo "build first: ./app/island-macos/build.sh"; exit 1; }
mkdir -p "$LA" "$HOME/Library/Application Support/VESPER"

# ONE DEFINITION, COPIED -- not a second one written here.
#
# This script used to write its own plist while build.sh wrote another inside the
# bundle, and on 2026-08-24 they drifted: build.sh gained the home's arguments,
# this file kept spawning the island alone, and `launchctl` reported "LaunchAgent
# reloaded" for a plist that had not changed. Two definitions of what VESPER is
# means the one that runs is whichever was written last.
SRC="$REPO/app/VESPER.app/Contents/Library/LaunchAgents/$ID.plist"
[ -f "$SRC" ] || { echo "no plist in the bundle: ./app/island-macos/build.sh"; exit 1; }
cp "$SRC" "$LA/$ID.plist"

# WAIT FOR THE BOOTOUT TO ACTUALLY COMPLETE BEFORE BOOTSTRAPPING.
#
# `bootout` returns before launchd has finished unloading the job, and
# bootstrapping into that window fails with `5: Input/output error` -- which
# reads like a permissions or plist problem and is neither. The build reported
# "VESPER is not supervised" twice for an agent that loaded correctly the moment
# it was retried by hand, and the false alarm cost a real investigation both
# times.
#
# This is the same read-too-soon shape HANDOFF_HOME_STEP1 records four times
# over, arriving as a WRITE-too-soon: the previous state had not finished
# leaving when the next one was asked to arrive.
launchctl bootout "gui/$(id -u)/$ID" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  launchctl list 2>/dev/null | grep -q "$ID" || break
  sleep 0.25
done
launchctl bootstrap "gui/$(id -u)" "$LA/$ID.plist"
echo "loaded $ID"
echo "remove with: tools/install_island_agent.sh --uninstall"
