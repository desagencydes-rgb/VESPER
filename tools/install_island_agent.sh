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

cat > "$LA/$ID.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID</string>
  <key>ProgramArguments</key><array><string>$BIN</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/island.err</string>
</dict></plist>
PLIST

launchctl bootout "gui/$(id -u)/$ID" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LA/$ID.plist"
echo "loaded $ID"
echo "remove with: tools/install_island_agent.sh --uninstall"
