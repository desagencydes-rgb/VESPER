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
  -o island

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Library/LaunchAgents"
cp island "$APP/Contents/MacOS/VESPER"
cp face.bin "$APP/Contents/Resources/face.bin"
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
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/VESPER</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
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
  "$REPO/tools/install_island_agent.sh" >/dev/null 2>&1 && echo "LaunchAgent reloaded"
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
echo "  --mode NAME   sets the DESKTOP PICTURE of the active Space to that mode"
echo "  --home-verify identity + the occlusion<->Desktop measurement"
echo "  --glass-verify the glass hatch's alarm: 0 transparent, 1 opaque, 2 unreadable"
echo
echo "the app registers its own login item on first launch."
echo "to remove it:  app/VESPER.app/Contents/MacOS/VESPER --uninstall-login-item"
