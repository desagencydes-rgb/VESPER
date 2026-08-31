import Foundation
import AppKit
import CoreGraphics

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

func vesperIsRunning() -> Bool {
    let me = ProcessInfo.processInfo.processIdentifier
    return NSRunningApplication
        .runningApplications(withBundleIdentifier: "ai.vesper.island")
        .contains { $0.processIdentifier != me && !$0.isTerminated }
}

func launchVesper() {
    if vesperIsRunning() {
        note("globe x3 -- VESPER is already running, not starting a second one")
        return
    }
    let app = URL(fileURLWithPath: CommandLine.arguments[0])
        .deletingLastPathComponent()   // MacOS
        .deletingLastPathComponent()   // Contents
        .deletingLastPathComponent()   // VESPER.app
    note("globe x3 -- starting VESPER")
    let cfg = NSWorkspace.OpenConfiguration()
    cfg.arguments = ["--home", "--on-empty-desktop", "--mode", "Home", "--chrome"]
    cfg.createsNewApplicationInstance = false      // never a second copy
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
