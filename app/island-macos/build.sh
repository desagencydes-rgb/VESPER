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
  main.swift FaceRenderer.swift Behaviour.swift SpeechConsent.swift AgendaBridge.swift NotesBridge.swift Listener.swift WakeWord.swift FnTrigger.swift Camera.swift \
  "$HOME_SRC/Home.swift" "$HOME_SRC/HomeAmbience.swift" "$HOME_SRC/SpaceWatch.swift" \
  "$HOME_SRC/HomeVerify.swift" "$HOME_SRC/GlassGuard.swift" \
  "$HOME_SRC/HomeChrome.swift" "$HOME_SRC/HomeSurfaces.swift" "$HOME_SRC/RuntimeHost.swift" "$HOME_SRC/HomeCost.swift" \
  "$HOME_SRC/ChromeProbe.swift" "$HOME_SRC/ActBridge.swift" "$HOME_SRC/WindowBridge.swift" "$HOME_SRC/SpacesHatch.swift" "$HOME_SRC/AppsBridge.swift" "$HOME_SRC/Grants.swift" "$HOME_SRC/GrantsRequest.swift" "$HOME_SRC/UIBridge.swift" \
  "$HOME_SRC/TerminalBridge.swift" "$HOME_SRC/Showcase.swift" \
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
# The showcase's markup ships the same way, and here the file is the ONLY copy --
# `Showcase.page()` falls back to the repo and then to a visible complaint,
# deliberately: this surface is opened on purpose to be looked at, so a missing
# resource should be loud rather than silently empty.
cp "$HOME_SRC/chrome/showcase.html" "$APP/Contents/Resources/showcase.html"

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
# WHERE THIS WAS BUILT FROM, recorded because the copy cannot work it out by
# looking at itself. `core/places.py` reads this back and CHECKS the directory
# still carries the project's markers before offering it -- a recorded path that
# no longer exists is reported absent, never used and found wrong later. Without
# it, "the project root" silently means this bundle: asked to list it, vesper
# answered with the five directories copied above.
printf 'project_root = "%s"\n' "$REPO" > "$APP/Contents/Resources/runtime/place.toml"
# THE MINTER SHIPS TOO. `VESPER --arm` is the process whose absence stops
# autonomy -- interlock is a dead-man's switch -- and a bundle that carries the
# runtime but not the thing that arms it is a bundle that cannot act.
cp "$REPO/tools/ops/vesper_arm.py" "$APP/Contents/Resources/runtime/tools/ops/"
# THE MENU PROJECTION SHIPS TOO, same class of omission as the REMOTE-SUPPLY
# table below: `vesper_runtime.py`'s `_metric_rows()` does
# `from tools.menu_snapshot import cached_rows`, and a copy list that carries
# the importer but not the module it imports fails at exactly that line --
# caught, logged nowhere the owner looks, and the runtime silently falls back
# to its original five keys while every catalogue row renders UNAVAILABLE.
# Measured 2026-09-07: exactly that. `menu_catalogue.json` has to land BESIDE
# `menu_snapshot.py`, not merely somewhere in the bundle -- the module reads
# it via `Path(__file__).with_name(...)`.
# THE INTERFACE CHECK SHIPS TOO, because it can only run as VESPER: launched
# from a shell, TCC answers for the terminal and every accessibility call is
# refused. `--ui-endtoend` runs this copy, and only this copy.
cp "$REPO/tools/ui_endtoend.py" "$APP/Contents/Resources/runtime/tools/"
cp "$REPO/tools/menu_snapshot.py" "$REPO/tools/menu_catalogue.json" \
   "$REPO/tools/home_snapshot.py" \
   "$APP/Contents/Resources/runtime/tools/"
# THE HOST CARD'S OWN LOADER WAS BROKEN THE SAME WAY, LONGER. `_metric_rows()`
# in vesper_runtime.py dynamically loads home_snapshot.py from
# `Path(__file__).resolve().parents[2] / "tools" / "home_snapshot.py"` --
# relative to WHEREVER THAT COPY OF vesper_runtime.py LIVES, so from the
# bundle this resolves inside Contents/Resources/runtime, and that file was
# never copied there at all. Not a regression from tonight: this has been
# true since home_snapshot.py started being loaded this way, silent because
# the dev-path launches this whole project mostly tests with (cwd = repo
# root) go through RuntimeHost's OWN "bundled first" check, find the bundled
# copy present, and never notice the copy is incomplete underneath it.
# spec_from_file_location does not fail at spec-creation on a missing file;
# it raises FileNotFoundError inside exec_module, one call up, where the
# calling code's `except Exception` swallows it into a bus event nobody was
# watching. Found by running the exact load by hand in the bundle's own
# environment, 2026-09-07, after two rebuilds still showed one stale row.

# THE MEASUREMENTS SHIP WITH THE RUNTIME, and forgetting them was not a small
# omission. INV-HW-2 refuses an unmeasured provider, so a bundle carrying the
# supply TABLE and not the measurements registers nothing at all: every row is
# skipped as UNAVAILABLE and the app answers "no route" to everything, while
# looking perfectly healthy. The table says who exists; the probe says who was
# measured to answer, and the runtime needs both.
# THE TWO DOCUMENTS THE RAIL'S OWN SURFACES READ (§11.7).
#
# `projects` reads the build order and `research` reads the spike index, and both
# are repository documents. The runtime runs from INSIDE the bundle, where
# `Path(__file__).parents[1]` is Resources/runtime and not the repo -- so without
# these the producers correctly reported "could not be read" and the owner saw
# UNAVAILABLE on both buttons. Measured 2026-09-11: 33 and 15 rows from the repo,
# 1 apiece from the bundle. Same shape as `_find_vesper_bin`, which worked only
# from the repo for the same reason.
mkdir -p "$APP/Contents/Resources/runtime/docs/design"
cp "$REPO/docs/design/HOME-WORKBENCH.md" \
   "$APP/Contents/Resources/runtime/docs/design/" 2>/dev/null || true
mkdir -p "$APP/Contents/Resources/runtime/docs/spikes"
cp "$REPO/docs/spikes/INDEX.toml" \
   "$APP/Contents/Resources/runtime/docs/spikes/" 2>/dev/null || true

mkdir -p "$APP/Contents/Resources/runtime/docs/planning/spike-results"
cp "$REPO"/docs/planning/spike-results/REMOTE-SUPPLY-*.json \
   "$APP/Contents/Resources/runtime/docs/planning/spike-results/" 2>/dev/null || \
   echo "WARNING: no REMOTE-SUPPLY measurement to bundle -- the app will have no route" >&2
# NOT TIDINESS: THE SIGNATURE. A .pyc inside the bundle breaks the seal, and a
# broken seal means macOS refuses to relaunch the app at all. This clears what a
# previous RUN left behind; the plist above is what stops it happening again.
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
  <!-- TCC PROMPTS CANNOT BE REQUESTED WITHOUT THESE, and their absence is not
       an error anywhere: the request simply returns "denied" and speech looks
       broken rather than unpermitted. Measured 2026-08-30 on this Mac, before
       these existed: SFSpeechRecognizer.authorizationStatus() == 0
       (notDetermined) with no way to move it.

       The strings are the only explanation the owner ever sees, in a dialog
       with no context around it, so they say where the audio actually goes.
       On-device recognition is available here for en-US and NOT for ar-MA,
       ar-SA or fr-FR (measured same day) -- so the second string must not
       claim everything stays on the machine, because for Darija it does not. -->
  <key>NSMicrophoneUsageDescription</key><string>VESPER listens for what you say to it. Nothing is captured until you allow this.</string>
  <key>NSCameraUsageDescription</key><string>VESPER looks only when you ask it to measure the camera or check who is at the machine. No picture is kept; only counts.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>VESPER turns speech into text so it can answer. English is recognised on this Mac; other languages are sent to a transcription service.</string>
  <!-- EventKit, and the reason these two exist rather than Full Disk Access:
       the raw stores under ~/Library/Group Containers answer "Operation not
       permitted" without FDA, which would hand VESPER mail, messages and
       browser history to read a list of appointments. These ask for the two
       things it needs and can be revoked one at a time. Both the legacy and
       the macOS 14+ key names are declared: the framework picks the one it
       wants and a missing string is a SIGABRT at request time, not a dialog
       the owner can decline. -->
  <key>NSCalendarsUsageDescription</key><string>VESPER reads your calendar so it knows what is coming up and when to bring it to you. It never writes to it.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>VESPER reads your calendar so it knows what is coming up and when to bring it to you. It never writes to it.</string>
  <key>NSRemindersUsageDescription</key><string>VESPER reads your reminders so it can rank what is due against everything else you have asked of it.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>VESPER reads your reminders so it can rank what is due against everything else you have asked of it.</string>
  <key>NSAppleEventsUsageDescription</key><string>VESPER reads the TITLES of your recent notes so it can rank them alongside your calendar and reminders. It never reads a note's contents.</string>
</dict>
</plist>
PLIST

# The login-item agent lives INSIDE the bundle, which is what SMAppService reads.
# Written to ~/Library/LaunchAgents instead, macOS registers the EXECUTABLE: Login
# Items then shows a generic `exec` icon, and a second entry appears for whatever
# interpreter the helper used. From inside the bundle it is one entry, with the
# app's own name and mark.
# BACKTICKS ARE FORBIDDEN INSIDE THESE HEREDOCS, and this comment is the only
# place that can say so. The delimiters are UNQUOTED because the bodies need
# `$APP`, `$ID` and `$HOME` expanded -- which also means the shell performs
# COMMAND SUBSTITUTION on them. Measured 2026-09-06: the arm plist's own
# explanatory comment quoted four flag names in backticks, bash ran each of
# them as a command, and the words vanished from the file the build wrote. The
# plist survived only because the pairs happened to fall inside an XML comment;
# a pair spanning a <string> would have deleted a launch argument silently,
# which is precisely the failure that comment was written to prevent. Quote
# with single quotes here.
# VESPER'S OWN PLACE MUST EXIST BEFORE LAUNCHD SPAWNS INTO IT (D6, 2026-09-13).
# Every agent below works there rather than in the repo or the bundle; a
# WorkingDirectory that is missing at spawn is a spawn failure, not a warning.
mkdir -p "$HOME/Library/Application Support/VESPER/workspace"
cat > "$APP/Contents/Library/LaunchAgents/$ID.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID</string>
  <key>EnvironmentVariables</key>
  <dict>
    <!-- PYTHON MUST NOT WRITE BYTECODE INTO THE BUNDLE.

         The runtime lives in Contents/Resources/runtime, so importing it creates
         __pycache__ directories there. Those files are not part of the signed
         seal, so the app invalidates its OWN code signature the first time it
         runs. Nothing notices until something asks macOS to relaunch the app,
         and then the kernel refuses it outright: "Code Signature Invalid, Launch
         Constraint Violation".

         Measured 2026-09-16: the owner accepted the Screen Recording grant, the
         system offered to quit and reopen VESPER, and it crashed four times in
         fourteen seconds until launchd gave up and the owner was told VESPER was
         not responding. 99 stray .pyc files were the whole cause. Deleting them
         restored the signature with the SAME cdhash, so the grant survived.

         The cleanup below runs at BUILD time and cannot help: the files appear
         at RUN time. The home passes its own environment to the runtime it
         spawns, so this one line reaches every python VESPER starts. -->
    <key>PYTHONDONTWRITEBYTECODE</key><string>1</string>
  </dict>
  <!-- THE WHOLE THING, AND IT DOES NOT STOP. Owner, 2026-08-24: "is it better
       to put everything built there and not stop it?" -- yes, and this is where
       that decision lives.

       --on-empty-desktop with NO --wait is deliberate. The home waits for a
       Desktop with none of the owner's windows on it, indefinitely, and never
       takes one that has. A --wait here would exit on timeout, and under
       KeepAlive an exit is a restart loop.

       The wait does not block: the island is up the moment the process is,
       whether or not a Desktop is free.

       AND THE WAIT ENDS ON A SUMMONS (2026-11-08). These arguments are fixed,
       so the globe key cannot ask for a different start -- it writes a
       come-here marker instead, and the home's wait takes it on its first
       tick and plants the ground on whichever Desktop is showing. That is
       the owner's decision: this flag governs vesper starting UNASKED, and
       being called is not taking. Only the globe key writes that marker;
       the unasked relaunches this KeepAlive produces cannot end a wait. -->
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--home</string>
    <string>--on-empty-desktop</string>
    <string>--mode</string><string>Home</string>
    <string>--chrome</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/Library/Application Support/VESPER/workspace</string>
  <key>RunAtLoad</key><true/>
  <!-- RESPAWN A CRASH, NOT A CLEAN EXIT. Measured 2026-09-13: with KeepAlive
       true and a home already started by hand, launchd spawned a second
       instance every 10 s for two hours (runs = 694); each hit the
       single-instance guard, wrote the summons and exited 0, and launchd's
       throttle brought the next one. A non-zero exit or a signal still
       restarts; a deliberate stop is still `bootout` (main.swift, "Stop VESPER
       for real"). -->
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/island.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/island.err</string>
</dict></plist>
PLIST

# THE WAKE LISTENER IS AN AGENT TOO, AND NOTHING STARTED IT UNTIL NOW. The
# always-on recogniser existed, was correct, forced on-device recognition, and
# ran only when someone launched it by hand -- so it did not survive a crash, a
# logout or a reboot, and in ordinary use it was simply never running.
# Measured 2026-09-04: no `--wake` process on the machine and `heard.jsonl`
# untouched since 2026-08-31, while the owner was telling VESPER it could not
# hear them. A feature that is fully correct and never running is not a feature.
#
# ITS OWN LABEL, for the reason the globe watcher has one: stopping VESPER must
# not require stopping the microphone, and restarting one must not restart the
# other.
cat > "$APP/Contents/Library/LaunchAgents/$ID.wake.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID.wake</string>
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--wake</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/Library/Application Support/VESPER/workspace</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- Interactive, like the others: it opens the microphone and talks to the
       on-device recogniser, both of which want a real session. -->
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/wake.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/wake.err</string>
</dict></plist>
PLIST

# THE CALENDAR BRIDGE IS AN AGENT AND NOT A THREAD OF THE RUNTIME, and the
# reason is TCC rather than tidiness. Calendar and Reminders access is granted
# to THIS BUNDLE; the Python runtime is a child interpreter and does not
# inherit the right to ask for it or to use it. So the thing that reads the
# calendar has to be the app, and the app has to be started by launchd.
#
# `StartInterval`, NOT `KeepAlive`. `--agenda-dump` writes a file and exits;
# KeepAlive would restart it instantly, forever. Ten minutes against a fifteen
# minute freshness window in `core/agenda.py`, so one missed run still leaves a
# reading the runtime will trust, and two missed runs read as UNAVAILABLE
# rather than as a clear day.
#
# `RunAtLoad` SO A COLD BOOT HAS AN AGENDA. Without it the first dump would be
# up to ten minutes after login, and for those ten minutes VESPER would
# correctly report it cannot see the calendar -- true, and needlessly true.
cat > "$APP/Contents/Library/LaunchAgents/$ID.agenda.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID.agenda</string>
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--agenda-dump</string>
    <!-- THE NOTES DUMP RIDES THE SAME AGENT, not a sixth one. Both write a
         freshness-stamped file the runtime reads, both are cheap, and both go
         stale on the same clock -- `EVENTKIT_FRESH_S`. A separate agent would
         be a second thing to notice when one of them stops. -->
    <string>--notes-dump</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/Library/Application Support/VESPER/workspace</string>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>600</integer>
  <!-- Background is correct HERE and wrong for the other three: this opens no
       window, no event tap and no microphone. It reads EventKit and writes a
       file. The fnwatch agent sat at EX_CONFIG for a day because it was
       declared Background and needed the window server; this one genuinely
       does not. -->
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/agenda.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/agenda.err</string>
</dict></plist>
PLIST

# THE MINTER, WHICH IS WHAT MAKES AUTONOMY POSSIBLE AT ALL. `VESPER --arm`
# writes the enable token the interlock needs; without it `autonomy_permitted()`
# is false, every fired trigger is recorded as `autonomy.stopped`, and the
# agenda watches the owner's day and may never act on it. Measured 2026-09-04:
# stopped since 19:13, reason `enable_token_expired`, no minter process
# anywhere on the machine.
#
# `KeepAlive`, NOT `StartInterval`, AND THE DIFFERENCE WAS MEASURED RATHER
# THAN ASSUMED. `tools/ops/vesper_arm.py` mints in its own `while True` with
# its own sleep, so it never exits; StartInterval would have launchd firing a
# second copy every interval on top of a process still running. That is how
# seven minters ended up on this machine at once, all presenting tokens, and
# the log recording a replay refusal for each. One supervised process, restarted
# if it dies.
#
# AS A MODE OF THE APP BINARY, never a bare `python3`. A minter running outside
# the bundle whose autonomy it keeps alive is a second identity on the machine
# with a claim on VESPER's authority.
cat > "$APP/Contents/Library/LaunchAgents/$ID.arm.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID.arm</string>
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--arm</string>
    <!-- '--run' OR IT PRINTS STATUS AND EXITS. 'vesper_arm.py' defaults to
         'status()'; only '--run' enters the minting loop. A plist missing this
         word installs cleanly, launches cleanly, exits 0, and mints nothing --
         and the interlock stops autonomy 90 seconds later with a reason that
         points at the token rather than at the launcher. -->
    <string>--run</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/Library/Application Support/VESPER/workspace</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/arm.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/arm.err</string>
</dict></plist>
PLIST

# THE GLOBE-KEY WATCHER IS ITS OWN AGENT, and it has to be. Its whole job is to
# start home when home is down, so it cannot live inside home. It also cannot
# share the island's Label: booting the island out to test something would take
# the starter down with it, and the starter is what brings the island back.
cat > "$APP/Contents/Library/LaunchAgents/$ID.fnwatch.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID.fnwatch</string>
  <key>ProgramArguments</key><array>
    <string>$APP/Contents/MacOS/VESPER</string>
    <string>--fn-watch</string>
  </array>
  <key>WorkingDirectory</key><string>$HOME/Library/Application Support/VESPER/workspace</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- Interactive, NOT Background, and the difference is whether it runs at
       all. This said Background -- honest about the job's importance and wrong
       about its needs: 'runFnWatch' opens an NSApplication and a global event
       tap, both of which want the window server, and launchd refused the spawn
       with EX_CONFIG rather than letting it start and fail visibly.

       MEASURED 2026-09-04: 'last exit code = 78: EX_CONFIG', empty stderr,
       never spawned -- for a full day, while '--login-item-status' reported
       the service "enabled" and every plist field matched the island agent
       that was working. The only field that differed was this one. -->
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/Library/Application Support/VESPER/fnwatch.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Application Support/VESPER/fnwatch.err</string>
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

# AND THE SMAppService AGENTS, which are the ones actually running. The block
# below refreshes a FILE-BASED agent under ~/Library/LaunchAgents; both agents
# in use are registered from inside the bundle instead, so nothing here touched
# them and the comment above about "EVERY build that changes the signature" was
# describing an intention rather than a step.
#
# MEASURED 2026-09-04: after two rebuilds, `ai.vesper.island.fnwatch` sat at
# `last exit code = 78: EX_CONFIG` and had not spawned since -- the globe-key
# starter, dead for a day, with an empty stderr because it never ran far enough
# to write one. `ai.vesper.island` survived only because it gets re-registered
# on the app's own launch.
# TWICE, WITH A SETTLE BETWEEN. Measured across four builds on 2026-09-04: the
# first pass after a build reports "re-registered" for every agent and they
# come up at `exit = 78: EX_CONFIG` anyway, while a second pass a few seconds
# later brings them up at 0. The old processes are still going down while the
# first registration lands, so launchd is handed a job whose previous instance
# has not finished dying. One pass looked correct and left the globe key and
# the microphone dead; the loop is what actually restores them.

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
  # LISTED IS NOT RUNNING. `launchctl list` keeps a job that has exited, with "-"
  # where its pid would be, and on 2026-09-14 this block printed "VESPER is
  # supervised (pid 58421)" for an island that then exited 0 on its
  # single-instance guard while the old instance was still going down. KeepAlive
  # restarts only an unsuccessful exit, so VESPER stayed down for hours, the
  # runtime with it, and every control queued meanwhile went unread. So the row
  # must carry a pid, the pid must still be the job's a few seconds later, and a
  # job that exited is started once more before the build reports anything.
  _vesper_pid() { launchctl list 2>/dev/null | awk -v l="$ID" '$3 == l && $1 ~ /^[0-9]+$/ {print $1}'; }
  _pid=""
  for _attempt in 1 2; do
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      _pid="$(_vesper_pid)"
      [ -n "$_pid" ] && break
      sleep 0.5
    done
    if [ -n "$_pid" ]; then
      sleep 3
      if kill -0 "$_pid" 2>/dev/null && [ "$(_vesper_pid)" = "$_pid" ]; then
        break
      fi
    fi
    _pid=""
    launchctl kickstart "gui/$(id -u)/$ID" 2>/dev/null || true
  done
  if [ -n "$_pid" ]; then
    echo "VESPER is supervised and still running 3 s later (pid $_pid)"
  elif launchctl list 2>/dev/null | grep -q "$ID"; then
    echo "WARNING: $ID is listed but NOT RUNNING after reload and a kickstart -- VESPER is DOWN." >&2
  else
    echo "WARNING: $ID is not in launchctl after reload." >&2
  fi
fi

# --------------------------------------------------------------- the agents
#
# AFTER the reload, not before, and VERIFIED rather than counted.
#
# This was two passes with `sleep 6` between them, on the measurement that a
# second pass "a few seconds later brings them up at 0". MEASURED 2026-09-04,
# on the build that added this block: both passes ran, the build printed
# "re-registered" six times and exited 0, and `ai.vesper.island.wake` and
# `.fnwatch` were BOTH sitting at `exit = 78: EX_CONFIG` when the build
# finished. A third pass by hand, seconds later, brought both up at 0.
#
# So the number of passes was never the variable -- the old processes finish
# dying when they finish dying, and a fixed count is a guess about that. Two
# guesses in a row still left the globe key and the microphone dead while the
# build said it had fixed them. This asks launchd for a PID after every pass
# and stops when it has one for all three, which is the only reading that
# distinguishes "registered" from "running". It also runs AFTER the LaunchAgent
# reload above, because that reload restarts the island underneath whatever the
# registration just did.
# WHAT "UP" MEANS, AND WHY IT IS NOT "HAS A PID". `ai.vesper.island.wake`
# exits 1 on purpose until the owner grants speech recognition, and KeepAlive
# restarts it, so at any instant it may legitimately have no PID. Requiring a
# PID here made the build print "the wake word will do nothing" on a correctly
# registered agent whose only problem was an ungranted permission -- a warning
# that sends the reader to the wrong place.
#
# `78` (EX_CONFIG) is the one that means REGISTRATION failed: launchd never got
# far enough to run the binary, which is the stale-record symptom this loop
# exists for. An agent that ran and exited is reached; an agent at 78 is not.
# THE THREE LABELS ARE WRITTEN OUT, NOT SPLIT FROM A STRING. Looping over an
# unquoted variable relies on word-splitting, which is a bash behaviour; zsh
# does not split, so the loop runs ONCE with all three labels glued together,
# matches nothing, and reports every agent down. Measured 2026-09-04: the
# string form said "NOT UP" about three agents, two of which were plainly
# running with PIDs. A predicate whose answer depends on which shell read it is
# worse than no predicate, and this file is run by hand as often as by its
# shebang.
_up() {
  for _a in "$ID" "$ID.fnwatch" "$ID.wake" "$ID.agenda" "$ID.arm"; do
    _row="$(launchctl list 2>/dev/null | awk -v l="$_a" '$3 == l {print $1 "|" $2}')"
    [ -z "$_row" ] && return 1                    # not registered at all
    case "${_row%%|*}" in
      ''|*[!0-9]*)                                # no PID -- judge by exit code
        [ "${_row##*|}" = "78" ] && return 1 ;;
    esac
  done
  return 0
}
for _pass in 1 2 3 4 5 6; do
  _up && break
  "$APP/Contents/MacOS/VESPER" --reinstall-login-item >/dev/null 2>&1 || true
  sleep 3
done
if _up; then
  echo "agents running:"
  for _a in "$ID" "$ID.fnwatch" "$ID.wake" "$ID.agenda" "$ID.arm"; do
    echo "  $_a (pid $(launchctl list 2>/dev/null | awk -v l="$_a" '$3 == l {print $1}'))"
  done
else
  echo "WARNING: an agent is registered but NOT RUNNING after 6 passes." >&2
  echo "         globe x3 and/or the wake word will do nothing. Status:" >&2
  for _a in "$ID" "$ID.fnwatch" "$ID.wake" "$ID.agenda" "$ID.arm"; do
    launchctl list 2>/dev/null | awk -v l="$_a" '$3 == l {print "         " l " pid=" $1 " exit=" $2}' >&2
  done
fi

# ASK FOR EVERY MISSING PERMISSION, NOW, WHILE THE OWNER IS STILL HERE.
#
# Grants are keyed to the cdhash and this build just changed it, so everything
# except Apple Events was revoked a second ago. The owner, 2026-09-13: "for
# stuff that need dialog on runtime, they should be raised right after vesper
# rebuilds and runs, so i won't have to go to settings anymore."
#
# `open -n` AND NOT THE BINARY. TCC attributes a request to the RESPONSIBLE
# process; asking from this shell would ask on behalf of the shell, which is the
# mistake MEMORY.md records costing a whole grant trip once already.
open -n "$APP" --args --request-grants

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
