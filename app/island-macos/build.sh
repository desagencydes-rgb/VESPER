#!/bin/sh
# Build VESPER.app — the island, as a real macOS application.
#
# WHY A BUNDLE AND NOT A LOOSE BINARY. TCC permission grants are keyed to app
# identity. Every permission granted while this runs as a bare executable is
# granted to the TERMINAL that launched it, shows up in System Settings as
# "Terminal", and does not transfer when the bundle arrives later. Bundling now
# means grants accumulate against VESPER from the first one.
#
# No package manager and no dependencies: swiftc, the system SDK, and plists.
set -e
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"
APP="$REPO/app/VESPER.app"
ID="ai.vesper.island"

# face.bin is derived, not authored -- regenerate rather than commit 600 KB.
[ -f face.bin ] || (cd "$REPO" && python3 docs/design/source/face_cloud.py)

# ONE BINARY, ISLAND AND HOME. Not a convenience: a second executable dropped
# into Contents/MacOS/ is signed as a RESOURCE of the bundle rather than as code
# with an identity of its own, which re-opens exactly the TCC question the
# bundle was built to close. See Home.swift's header for the other two reasons.
HOME_SRC=../home-macos
# -target ...13.0 matches the LSMinimumSystemVersion this bundle already
# declares, and it is what makes GlassGuard's reader compile: the SDK marks
# CGWindowListCreateImage obsoleted=15.0. Every call above 13.0 in these
# sources is already behind #available, so the floor costs nothing.
swiftc -O -swift-version 5 -target arm64-apple-macosx13.0 \
  main.swift FaceRenderer.swift Behaviour.swift \
  "$HOME_SRC/Home.swift" "$HOME_SRC/HomeAmbience.swift" "$HOME_SRC/SpaceWatch.swift" \
  "$HOME_SRC/HomeVerify.swift" "$HOME_SRC/GlassGuard.swift" \
  "$HOME_SRC/HomeChrome.swift" "$HOME_SRC/HomeSurfaces.swift" "$HOME_SRC/RuntimeHost.swift" "$HOME_SRC/HomeCost.swift" \
  "$HOME_SRC/OcclusionWatch.swift" "$HOME_SRC/DockSwap.swift" \
  -o island

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Library/LaunchAgents"
cp island "$APP/Contents/MacOS/VESPER"
cp face.bin "$APP/Contents/Resources/face.bin"
# The chrome's markup ships as a RESOURCE so a designer can edit it without a
# rebuild. The binary still carries an inline copy: a missing file must never
# blank a layer that sits over the owner's whole Desktop.
cp "$HOME_SRC/chrome/home.html" "$APP/Contents/Resources/home.html"

# THE RUNTIME SHIPS INSIDE THE BUNDLE, and is started BY the app rather than by
# a second login item.
#
# A separate LaunchAgent made VESPER two things: two labels, two identities, and
# a runtime that could be answering while the app was not running -- holding the
# owner's API keys with no window anywhere to say so. One app means one thing to
# launch, one thing to quit, and a runtime whose lifetime is the app's.
#
# Contents/Resources, not Contents/MacOS: a second executable in MacOS/ is
# signed as a RESOURCE of the bundle rather than as code with an identity, which
# is the same TCC question this build already answered once.
mkdir -p "$APP/Contents/Resources/runtime"
cp -R "$REPO/core" "$REPO/routing" "$REPO/contracts" \
      "$APP/Contents/Resources/runtime/" 2>/dev/null
mkdir -p "$APP/Contents/Resources/runtime/tools/ops"
cp "$REPO/tools/ops/vesper_runtime.py" "$APP/Contents/Resources/runtime/tools/ops/"

# THE MEASUREMENTS SHIP WITH THE RUNTIME, and forgetting them was not a small
# omission. INV-HW-2 refuses an unmeasured provider, so a bundle carrying the
# supply TABLE and not the measurements registers nothing at all: every row is
# skipped as UNAVAILABLE and the app answers "no route" to everything, while
# looking perfectly healthy. The table says who exists; the probe says who was
# measured to answer, and the runtime needs both.
mkdir -p "$APP/Contents/Resources/runtime/docs/planning/spike-results"
cp "$REPO"/docs/planning/spike-results/REMOTE-SUPPLY-*.json \
   "$APP/Contents/Resources/runtime/docs/planning/spike-results/" 2>/dev/null || \
   echo "WARNING: no REMOTE-SUPPLY measurement to bundle -- the app will have no route" >&2
find "$APP/Contents/Resources/runtime" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp "$REPO/docs/design/assets/vesper-icon.png" "$APP/Contents/Resources/vesper-icon.png"

# The mark, as the app icon -- it is what appears in the permission dialogs.
ICONSET=/tmp/vesper.iconset
rm -rf $ICONSET; mkdir -p $ICONSET
for sz in 16 32 64 128 256 512; do
  sips -z $sz $sz "$REPO/docs/design/assets/vesper-icon.png" \
       --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1
  sips -z $((sz*2)) $((sz*2)) "$REPO/docs/design/assets/vesper-icon.png" \
       --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/VESPER.icns" 2>/dev/null || true

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>VESPER</string>
  <key>CFBundleDisplayName</key><string>VESPER</string>
  <key>CFBundleIdentifier</key><string>$ID</string>
  <key>CFBundleExecutable</key><string>VESPER</string>
  <key>CFBundleIconFile</key><string>VESPER.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <!-- Accessory: no Dock tile and no menu bar of its own. The island is
       presence, not a window, and an app that is only a panel should not
       take a Dock slot. -->
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# The login-item agent lives INSIDE the bundle, which is what SMAppService reads.
# Written to ~/Library/LaunchAgents instead, macOS registers the EXECUTABLE: Login
# Items then shows a generic `exec` icon, and a second entry appears for whatever
# interpreter the helper used. From inside the bundle it is one entry, with the
# app's own name and mark.
cat > "$APP/Contents/Library/LaunchAgents/$ID.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID</string>
  <!-- THE WHOLE THING, AND IT DOES NOT STOP. Owner, 2026-08-24: "is it better
       to put everything built there and not stop it?" -- yes, and this is where
       that decision lives.

       --on-empty-desktop with NO --wait is deliberate. The home waits for a
       Desktop with none of the owner's windows on it, indefinitely, and never
       takes one that has. A --wait here would exit on timeout, and under
       KeepAlive an exit is a restart loop.

       The wait does not block: the island is up the moment the process is,
       whether or not a Desktop is free. -->
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--home</string>
    <string>--on-empty-desktop</string>
    <string>--mode</string><string>Home</string>
    <string>--chrome</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/island.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/island.err</string>
</dict></plist>
PLIST

# AD-HOC, AND THAT IS A MEASURED DECISION, NOT A DEFAULT.
#
# A self-signed certificate gives a stable identity so TCC grants survive rebuilds.
# It also makes launchd REFUSE to spawn the login item: the job dies instantly with
# OS_REASON_CODESIGNING, verified with and without the hardened runtime, and with
# the LaunchServices registration freshly refreshed. Ad-hoc spawns and stays up --
# killed with -9, back under a new pid.
#
# So the two wants are in conflict and only one can be had here:
#   ad-hoc       login item works. TCC may re-ask when the binary changes.
#   self-signed  stable TCC identity. Login item never starts.
#
# The owner's requirement is that VESPER runs all the time and comes back after a
# reboot, so persistence wins and re-prompts are the price.
#
# A DEVELOPER ID certificate is what buys both, and this is the concrete reason to
# want one -- not the cosmetic "unidentified developer" label.
codesign --force --sign - --identifier "$ID" "$APP" 2>/dev/null \
  && echo "signed ad-hoc as $ID (see the note above before changing this)" \
  || echo "WARNING: codesign failed -- macOS will treat this as unidentified"

# RE-SIGNING INVALIDATES THE CACHED LAUNCH REQUIREMENT. macOS remembers the app's
# code requirement in its LaunchServices / Background Task Management records, so
# after a re-sign launchd refuses to spawn the login item and kills it with
# OS_REASON_CODESIGNING -- 181 failed spawns before this was noticed, while the
# same binary launched by hand ran perfectly. Refreshing the registration is what
# clears it, and it must happen on EVERY build that changes the signature.
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -x "$LSREG" ] && "$LSREG" -f "$APP" && echo "LaunchServices registration refreshed"

# Reload the LaunchAgent if it is installed, so a rebuild does not leave launchd
# supervising a binary that no longer exists.
if [ -f "$HOME/Library/LaunchAgents/$ID.plist" ]; then
  # NOT SILENCED. This was `>/dev/null 2>&1 && echo` until 2026-08-24, and on a
  # rebuild it failed, printed nothing, and left VESPER DOWN -- the build
  # reported "built:" and exited 0 with no supervised process anywhere. A build
  # step that stops the thing it just built and says nothing is the same defect
  # as a runner exiting 0 on a traceback.
  if "$REPO/tools/install_island_agent.sh"; then
    echo "LaunchAgent reloaded"
  else
    echo "WARNING: LaunchAgent reload FAILED -- VESPER is not supervised." >&2
    echo "         run tools/install_island_agent.sh by hand." >&2
  fi
  # And re-read the world rather than trusting the exit code: launchctl
  # accepting a bootstrap is not a running process.
  # POLL, DO NOT SLEEP ONCE. A single `sleep 2` reported "VESPER is not
  # supervised" for an agent that loaded correctly a second later, and the
  # false alarm cost a real investigation. HANDOFF_HOME_STEP1 names this class
  # four times over: "when a reading says a mechanism did nothing, suspect the
  # reading first". A fixed wait is a guess about how long something takes;
  # polling asks the world until it answers or the budget runs out.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    launchctl list 2>/dev/null | grep -q "$ID" && break
    sleep 0.5
  done
  if launchctl list 2>/dev/null | grep -q "$ID"; then
    echo "VESPER is supervised (pid $(pgrep -f "VESPER.app/Contents/MacOS/VESPER" | head -1))"
  else
    echo "WARNING: $ID is not in launchctl after reload." >&2
  fi
fi

echo "built: $APP"
echo
echo "run, from the REPO ROOT:"
echo "  python3 tools/island_snapshot.py --measure   # produce the projection"
echo "  open app/VESPER.app                          # as VESPER"
echo "  ./app/island-macos/island --demo             # bare binary, dev loop"
echo "  --expand / --seconds N / --level-status / --fsaux"
echo
echo "the home (one process, same bundle, same identity):"
echo "  ./app/island-macos/island --home --mode Rest --seconds 30"
echo "  --home        ground at normal-1 on the ACTIVE Desktop, face on it"
echo "  --after N     wait N s first, so you can switch to VESPER's Desktop"
echo "  --chrome      mount the card layer over the field (first light)"
echo "  --on-empty-desktop  wait for a Desktop with none of your windows on it,"
echo "                and refuse to start rather than take one that has"
echo "  --mode NAME   sets the DESKTOP PICTURE of the active Space to that mode"
echo "  --home-verify identity + the occlusion<->Desktop measurement"
echo "  --glass-verify the glass hatch's alarm: 0 transparent, 1 opaque, 2 unreadable"
echo
echo "the app registers its own login item on first launch."
echo "to remove it:  app/VESPER.app/Contents/MacOS/VESPER --uninstall-login-item"
