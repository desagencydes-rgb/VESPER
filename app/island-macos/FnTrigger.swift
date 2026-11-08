import Foundation
import AppKit
import CoreGraphics
import ServiceManagement

// TRIPLE-TAP THE GLOBE KEY TO START VESPER.
//
// THE CHICKEN AND EGG IS THE WHOLE SHAPE OF THIS FILE. The thing that starts
// VESPER cannot live inside VESPER, so this is a separate, tiny mode of the
// same binary whose only job is to watch for the key and launch. It holds no
// state, opens no window, and touches nothing else.
//
// AND IT REFUSES TO START A SECOND ONE. The owner's requirement, and it is not
// cosmetic: two runtimes share one input file and one offset, so the second
// would silently eat turns the first was waiting for -- which is exactly the
// `handled 0` confusion that cost an hour earlier today. `NSRunningApplication`
// is asked, rather than a pid file, because a pid file outlives a crash and
// would refuse to start after one.
//
// THE GLOBE KEY IS NOT AN ORDINARY MODIFIER. It does not appear in
// `NSEvent.modifierFlags` as a normal flag on every Mac, and on keyboards with
// a physical Fn it is reported through `.function` alongside the arrow and
// function keys -- so watching `.function` alone fires on every arrow press.
// The discriminator is that a GLOBE tap changes the flags with NO key attached:
// keyCode 63 on Apple keyboards, and no character.

private let FN_KEYCODE: UInt16 = 63
private let TRIPLE_WINDOW_S = 1.2

private var taps: [Date] = []

/// The name a LIVE home process holds. A Mach port name, not a pid file: it is
/// held by a running process and vanishes with it, so there is no staleness to
/// validate and nothing to clean up after a crash -- which was the whole
/// objection to a pid file, answered without giving up specificity.
private let HOME_PORT_NAME = "ai.vesper.island.home" as CFString

private var homeMarkerPort: CFMessagePort?

/// Called by the home process at startup. Idempotent.
func publishHomeMarker() {
    guard homeMarkerPort == nil else { return }
    homeMarkerPort = CFMessagePortCreateLocal(kCFAllocatorDefault, HOME_PORT_NAME,
                                              nil, nil, nil)
    if homeMarkerPort == nil {
        note("could not publish the home marker -- the globe key cannot tell "
           + "whether home is up, and will refuse to start it")
    }
}

/// IS **HOME** RUNNING -- not "is any process from this bundle running".
///
/// THE BUG THIS REPLACES, measured 2026-08-31. The old form asked
/// `NSRunningApplication.runningApplications(withBundleIdentifier:)` and
/// excluded only its own pid. `--wake` and `--fn-watch` run from the SAME
/// bundle, so in the intended steady state -- wake listener up, home down -- a
/// triple-tap answered "already running" and started nothing. The trigger was
/// dead exactly when the wake word was doing its job.
///
/// It was not caught by the negative control, because that control ran with
/// zero processes, BEFORE the wake listener was launched. A control that
/// establishes the absence of a bug in a state the bug cannot occur in has
/// established nothing.
func homeIsRunning() -> Bool {
    guard let port = CFMessagePortCreateRemote(kCFAllocatorDefault, HOME_PORT_NAME)
    else { return false }
    return CFMessagePortIsValid(port)
}

/// "COME HERE, NOW" -- THE GESTURE, WRITTEN DOWN.
///
/// A SUMMONS CANNOT BE A LAUNCH ARGUMENT, which is the whole reason this type
/// exists. The home that has to answer one is either already running, or is
/// about to be started by launchd from the LOGIN agent's plist -- whose
/// arguments are fixed and carry `--on-empty-desktop`. There is no argument to
/// add, so the request is left on disk and the home reads it.
///
/// MEASURED 2026-11-02, AND REPORTED IN THE OWNER'S WORDS FOR THE SECOND TIME:
/// *"i click the globe button 3 times, the microphone turns on for vesper, and
/// i hear 'i'm here' but i don't see vesper nowhere"*. The 2026-09-06 fix below
/// -- launch WITHOUT `--on-empty-desktop`, because being called is not taking
/// -- had been made unreachable by the 2026-09-14 one: the globe path
/// bootstraps the file-based agent, the home publishes its marker BEFORE the
/// wait, `homeIsRunning()` is therefore true 2.5 s later, and the flag-free
/// launch further down is never reached. The home sat waiting for an empty
/// Desktop with its microphone open and no ground anywhere. Supervision was the
/// right fix; it just routed the summons through the login agent's arguments.
///
/// SO THE MARKER CARRIES WHO ASKED. An ordinary second launch writes one too
/// (main.swift's single-instance guard), and launchd's KeepAlive and build.sh
/// produce those UNASKED -- 694 of them in two hours on 2026-09-13. A waiting
/// home that honoured any marker would plant itself on whichever Desktop was
/// showing with nobody having asked, which is the owner's one hard rule
/// (2026-09-10: never take Desktop 1). Only `globe` may end a wait.
///
/// AND IT GOES STALE. A marker outlives the process that could not answer it: a
/// home killed while waiting leaves one behind, and at the next login every
/// Desktop is empty -- the exact state the Desktop-1 rule exists for. A summons
/// is a human gesture, so two minutes is the whole of its life.
enum Summons {
    enum By: String {
        /// The owner, pressing the globe key three times.
        case globe
        /// A second launch of the bundle. It moves a ground that EXISTS and
        /// never ends a wait, because launchd and build.sh produce these with
        /// nobody asking.
        case launch
    }

    /// A GESTURE, NOT A SETTING. Long enough for a cold start under launchd
    /// (measured: the home reaches its first tick in about two seconds), short
    /// enough that a marker left by a killed home cannot answer for the owner
    /// at the next login.
    static let FRESH_S = 120.0

    static var path: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/come-here")
    }

    static func ask(by who: By) {
        try? Data(who.rawValue.utf8).write(to: path)
    }

    /// Take a fresh summons, or answer false.
    ///
    /// REMOVED WHETHER OR NOT IT IS ANSWERED. The alternative is a marker that
    /// sits on disk until some later start happens to honour it -- a Desktop
    /// taken minutes after the owner asked for something else entirely.
    static func consume(requiring who: By? = nil) -> Bool {
        let p = path
        guard let asked = try? Data(contentsOf: p) else { return false }
        let by = String(data: asked, encoding: .utf8) ?? ""
        let attrs = try? FileManager.default.attributesOfItem(atPath: p.path)
        let written = (attrs?[.modificationDate] as? Date) ?? Date.distantPast
        let fresh = Date().timeIntervalSince(written) <= FRESH_S
        try? FileManager.default.removeItem(at: p)
        guard fresh else { return false }
        if let who = who, by != who.rawValue { return false }
        return true
    }
}

func launchVesper() {
    // GLOBE x3 IS A TOGGLE, and that is the whole point of it being the same
    // gesture. The owner already knows this key starts VESPER; asking them to
    // learn a four-modifier chord to stop it was inventing a second vocabulary
    // for one idea. Running -> stop. Not running -> start.
    //
    // THE WATCHER DOES NOT EXIT WITH IT. `exitAfter: false` because this is
    // the starter's own process: booting out the island must not take down the
    // thing that brings it back.
    if homeIsRunning() {
        // AND "IS IT RUNNING" IS NOT THE QUESTION THE OWNER IS ASKING.
        //
        // A home can be up with no ground anywhere -- waiting for an empty
        // Desktop is the NORMAL state on a machine in use -- or with its ground
        // on a Desktop the owner is not looking at. Both read as "vesper is not
        // here", and both used to answer the triple-tap by STOPPING: the owner
        // pressed the key because they could not see vesper, and vesper
        // answered by taking its microphone and its island away too. They then
        // pressed again to get it back, so the gesture did the opposite of what
        // it is for, twice, and the second press was the one that worked.
        //
        // THE GROUND IS THE DISCRIMINATOR, because it is the only window of
        // vesper's that cannot follow the owner between Desktops (main.swift:
        // "THE GROUND IS THE ONLY WINDOW THAT MEANS THIS DESKTOP IS MINE"). It
        // answers RESIDENCY, not visibility -- a ground under the owner's
        // windows is still on this Desktop -- and residency is the right
        // question here: this gesture is about which room vesper is in, not
        // about what is stacked on top of it.
        if groundIsVisible() {
            note("globe x3 -- VESPER is here, stopping it")
            stopVesper(exitAfter: false)
        } else {
            Summons.ask(by: .globe)
            note("globe x3 -- VESPER is up with no ground on this Desktop; "
               + "called it here rather than stopping it")
        }
        return
    }
    let app = URL(fileURLWithPath: CommandLine.arguments[0])
        .deletingLastPathComponent()   // MacOS
        .deletingLastPathComponent()   // Contents
        .deletingLastPathComponent()   // VESPER.app
    note("globe x3 -- starting VESPER")

    // THE SUMMONS GOES DOWN BEFORE THE START, AND THAT IS THE FIX.
    //
    // The bootstrap below starts the home from the LOGIN agent's plist, which
    // carries `--on-empty-desktop` and cannot be handed a different argument.
    // So the request is on disk before the process exists, and the home's wait
    // takes it on its first tick: pressing the globe three times plants the
    // ground on whichever Desktop is showing, Desktop 1 included.
    //
    // THE OWNER TOOK THAT DECISION, 2026-11-08, on being shown that their two
    // rules collide here. "Never take Desktop 1" (2026-09-10) governs vesper
    // starting UNASKED; being called is not taking. Nothing but the globe key
    // writes a `globe` summons, so nothing unasked can reach that exception.
    Summons.ask(by: .globe)

    // SUPERVISED, NOT MERELY RUNNING. `--stop` boots the agent out of launchd,
    // so opening the bundle after one gives an instance with no `KeepAlive`
    // behind it: VESPER is up, and a crash now leaves it down for good. That
    // is a worse state than the one before the stop, arrived at by using the
    // stop -- so the start has to undo what the stop did, not just put a
    // process back.
    //
    // `register()` throws when the service is already registered, which is the
    // ordinary case and not an error; the result is discarded and the open
    // below still runs if nothing came up.
    // THE ISLAND BELONGS TO LAUNCHCTL WHEN build.sh HAS WRITTEN ITS PLIST, and
    // SMAppService cannot register a label a file already owns. The
    // `register()` below brought nothing back, so every globe x3 after a stop
    // fell through to the unsupervised open further down (measured 2026-09-14
    // through `--start`, which had no such fallback and left VESPER down).
    let islandPlist = NSHomeDirectory() + "/Library/LaunchAgents/ai.vesper.island.plist"
    let islandFileBased = FileManager.default.fileExists(atPath: islandPlist)
    if islandFileBased {
        let boot = Process()
        boot.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        boot.arguments = ["bootstrap", "gui/\(getuid())", islandPlist]
        boot.standardOutput = FileHandle.nullDevice
        boot.standardError = FileHandle.nullDevice
        try? boot.run(); boot.waitUntilExit()
    }
    if #available(macOS 13.0, *) {
        if !islandFileBased {
            try? SMAppService.agent(plistName: "ai.vesper.island.plist").register()
        }
        // THE LISTENER COMES BACK WITH VESPER. The stop boots the wake agent out
        // -- it holds the microphone, and a stopped VESPER must not listen -- so
        // the start re-registers it. Unregister first: a bare register() over a
        // booted-out record is a no-op (see `--start`). The minter is NOT
        // restored here; autonomy after a stop is re-armed by a person.
        let wake = SMAppService.agent(plistName: "ai.vesper.island.wake.plist")
        try? wake.unregister()
        Thread.sleep(forTimeInterval: 1.0)
        try? wake.register()
        Thread.sleep(forTimeInterval: 1.5)
        if homeIsRunning() {
            note("globe x3 -- VESPER restored under launchd supervision")
            return
        }
    }
    let cfg = NSWorkspace.OpenConfiguration()
    // NO `--on-empty-desktop` HERE, AND THAT IS THE WHOLE POINT OF THIS PATH.
    //
    // That flag exists so VESPER does not STEAL a Desktop the owner is working
    // on -- it belongs on the LOGIN agent, which starts unasked. Pressing the
    // globe three times is not unasked: it is the owner saying "come here,
    // now". Making that request wait for an empty Desktop means the owner
    // presses the key, nothing appears, and the only place VESPER says why is
    // a log file they have no reason to open.
    //
    // MEASURED 2026-09-06, and reported in exactly those words: "i hit the
    // globe 3 times and i see no vesper". The runtime was up, the home was
    // alive, and it was printing "here now: 5 foreign window(s) -- not
    // VESPER's Desktop" to `island.out` on a two-second timer.
    //
    // The owner's own rule (2026-08-24) is about not taking "something i have
    // work on" -- which is about VESPER helping itself, not about VESPER
    // answering when called.
    cfg.arguments = ["--home", "--mode", "Home", "--chrome"]
    // TRUE, AND THAT IS NOT A LOOSENING. `false` means "activate an existing
    // instance of this bundle instead of launching" -- and the wake listener is
    // an instance of this bundle. So the triple-tap raised the LISTENER and
    // never launched home: measured 2026-08-31, "starting VESPER" printed and
    // nothing started. The coarse mechanism was doing the single-instance job
    // badly AND blocking the launch; now that `homeIsRunning()` answers the
    // real question, this one only gets in the way. Exactly one home is
    // enforced twice over: here before launching, and by home itself refusing
    // to start when the marker is already held.
    cfg.createsNewApplicationInstance = true
    NSWorkspace.shared.openApplication(at: app, configuration: cfg) { _, err in
        if let err { note("could not start VESPER: \(err)") }
    }
}

func runFnWatch() {
    // A GLOBAL TAP NEEDS ACCESSIBILITY, and asking for it up front is better
    // than a watcher that runs, sees nothing, and reports itself healthy.
    let trusted = AXIsProcessTrustedWithOptions(
        [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
    if !trusted {
        note("Accessibility permission is needed to watch the globe key. "
           + "Grant VESPER in System Settings > Privacy & Security > "
           + "Accessibility, then run this again.")
    }

    NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { ev in
        // Only a bare globe tap. An arrow key also raises `.function`, and
        // counting those would start VESPER while the owner scrolled.
        guard ev.keyCode == FN_KEYCODE else { return }
        // flagsChanged fires on press AND release; count the presses only.
        guard ev.modifierFlags.contains(.function) else { return }

        let now = Date()
        taps.append(now)
        taps = taps.filter { now.timeIntervalSince($0) <= TRIPLE_WINDOW_S }
        if taps.count >= 3 {
            taps.removeAll()
            launchVesper()
        }
    }
    note("watching the globe key: three taps within \(TRIPLE_WINDOW_S)s starts VESPER")
    NSApplication.shared.setActivationPolicy(.accessory)   // no dock icon
    NSApplication.shared.run()
}
