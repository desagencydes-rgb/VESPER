import AppKit
import ApplicationServices
import AVFoundation
import CoreGraphics
import EventKit
import Foundation
import Speech

/// Every permission VESPER needs, read in one pass, asking for none of them.
///
/// WHY THIS EXISTS RATHER THAN FIVE SEPARATE STATUS FLAGS. There already are
/// five -- `--speech-status`, `--notes-status`, `--agenda-status`, the
/// accessibility line in `--fn-status`, and `--apps-run --verb permission`. Each
/// answers one question, and the owner's grant trip is the OTHER shape: one pass
/// through everything, in the order the dialogs have to be answered, with the
/// ones already granted skipped. Five commands that each answer correctly still
/// make the owner assemble the list themselves, and they will assemble it from
/// whatever they remember rather than from what the machine says.
///
/// AND EVERY BUILD REVOKES ALL OF IT. `MEMORY.md` records grants for an
/// ad-hoc-signed app as keyed to its cdhash, re-signed on every build -- so each
/// build is a new app to TCC and the whole list resets. That is why the trip has
/// to come after the last build of a session, and why a reader that takes one
/// second is worth more than notes from the last trip.
///
/// NOTHING HERE PROMPTS. Every probe below is the non-asking variant, chosen
/// deliberately: `AXIsProcessTrusted()` rather than
/// `AXIsProcessTrustedWithOptions([prompt: true])`,
/// `CGPreflightScreenCaptureAccess()` rather than the requesting call, and
/// `AEDeterminePermissionToAutomateTarget(..., askUserIfNeeded: false)` --
/// measured on this node 2026-09-10 to return in 30-79 ms with no dialog. A
/// STATUS reader that prompts cannot be run to find out what to ask for; it
/// becomes the asking.
enum Grants {

    struct Row {
        let what: String
        let state: String        // granted | denied | undetermined | unknown
        let why: String
        let howToGrant: String
    }

    static let GRANTED = "granted"
    static let DENIED = "denied"
    static let UNDETERMINED = "undetermined"
    static let UNKNOWN = "unknown"

    /// Accessibility -- window management (§11.1) and the globe-key trigger.
    static func accessibility() -> Row {
        let ok = AXIsProcessTrusted()
        return Row(what: "Accessibility",
                   state: ok ? GRANTED : UNDETERMINED,
                   why: ok ? "" : "vesper cannot move, resize or close a window",
                   howToGrant: "System Settings > Privacy & Security > Accessibility > VESPER")
    }

    /// Screen Recording -- §11.5's UI view, and window TITLES.
    ///
    /// TITLES ARE THE PART THAT SURPRISES. `CGWindowListCopyWindowInfo`
    /// enumerates windows without this grant but omits their names, so a bar
    /// that reads "31 windows" and cannot say what any of them are is this
    /// permission missing rather than a bug.
    static func screenRecording() -> Row {
        let ok = CGPreflightScreenCaptureAccess()
        return Row(what: "Screen Recording",
                   state: ok ? GRANTED : UNDETERMINED,
                   why: ok ? "" : "vesper cannot see the screen or read window titles",
                   howToGrant: "System Settings > Privacy & Security > Screen & System Audio Recording > VESPER")
    }

    static func microphone() -> Row {
        let st = AVCaptureDevice.authorizationStatus(for: .audio)
        let s: String
        switch st {
        case .authorized:    s = GRANTED
        case .denied:        s = DENIED
        case .restricted:    s = DENIED
        case .notDetermined: s = UNDETERMINED
        @unknown default:    s = UNKNOWN
        }
        return Row(what: "Microphone",
                   state: s,
                   why: s == GRANTED ? "" : "the wake word and listening are off",
                   howToGrant: "System Settings > Privacy & Security > Microphone > VESPER")
    }

    static func speech() -> Row {
        let st = SFSpeechRecognizer.authorizationStatus()
        let s: String
        switch st {
        case .authorized:    s = GRANTED
        case .denied:        s = DENIED
        case .restricted:    s = DENIED
        case .notDetermined: s = UNDETERMINED
        @unknown default:    s = UNKNOWN
        }
        return Row(what: "Speech Recognition",
                   state: s,
                   why: s == GRANTED ? "" : "vesper cannot turn what it hears into words",
                   howToGrant: "granted by the first request: "
                             + "open -n app/VESPER.app --args --speech-consent")
    }

    /// Calendar and Reminders -- the agenda (§9c).
    static func calendar() -> Row {
        let st = EKEventStore.authorizationStatus(for: .event)
        let s: String
        switch st {
        case .fullAccess:    s = GRANTED
        case .denied:        s = DENIED
        case .restricted:    s = DENIED
        case .notDetermined: s = UNDETERMINED
        case .writeOnly:     s = GRANTED
        @unknown default:    s = UNKNOWN
        }
        return Row(what: "Calendar",
                   state: s,
                   why: s == GRANTED ? "" : "the agenda has no calendar to read",
                   howToGrant: "System Settings > Privacy & Security > Calendars > VESPER")
    }

    /// Apple Events, PER TARGET APPLICATION. This is the one that multiplies.
    ///
    /// AND IT COSTS A LAUNCH AS WELL AS A DIALOG. Measured 2026-09-10:
    /// `AEDeterminePermissionToAutomateTarget` answers `-600 procNotFound` for an
    /// application that is installed but not running, and identically for a
    /// bundle id that does not exist at all -- so an app that is not running has
    /// a permission that CANNOT BE READ, which is not the same as not granted.
    /// The owner has to open each target app before its row means anything.
    static func automation(_ bundleId: String) -> Row {
        let label = "Automation → \(bundleId)"
        let how = "granted by the first request, or: System Settings > "
                + "Privacy & Security > Automation > VESPER"
        guard let path = NSWorkspace.shared
                .urlForApplication(withBundleIdentifier: bundleId)?.path else {
            return Row(what: label, state: UNKNOWN,
                       why: "this machine has no application with that identifier",
                       howToGrant: how)
        }
        if NSRunningApplication
            .runningApplications(withBundleIdentifier: bundleId).isEmpty {
            return Row(what: label, state: UNKNOWN,
                       why: "\(path) is installed but NOT RUNNING, so its "
                          + "permission cannot be read -- open it first",
                       howToGrant: how)
        }
        var target = AEAddressDesc()
        let bytes = Array(bundleId.utf8)
        let made = bytes.withUnsafeBytes { buf in
            AECreateDesc(typeApplicationBundleID, buf.baseAddress, buf.count, &target)
        }
        guard made == noErr else {
            return Row(what: label, state: UNKNOWN,
                       why: "could not address that application (\(made))",
                       howToGrant: how)
        }
        let st = AEDeterminePermissionToAutomateTarget(&target, typeWildCard,
                                                      typeWildCard, false)
        AEDisposeDesc(&target)
        switch st {
        case noErr:
            return Row(what: label, state: GRANTED, why: "", howToGrant: how)
        case OSStatus(-1743):
            return Row(what: label, state: DENIED,
                       why: "the owner has refused this one", howToGrant: how)
        case OSStatus(-1744):
            return Row(what: label, state: UNDETERMINED,
                       why: "never asked", howToGrant: how)
        default:
            return Row(what: label, state: UNKNOWN,
                       why: "unrecognised status \(st)", howToGrant: how)
        }
    }

    /// The applications VESPER has a reason to drive today.
    ///
    /// NOT "EVERY APP INSTALLED". `host_actions.toml` says rows name an effect
    /// and the application is a target; this list is the targets something in
    /// the tree actually asks for -- Notes for the agenda (§9c, §11.4) and the
    /// two §11.3 verbs exercise whatever the owner names. A list of everything
    /// in /Applications would turn the grant trip into a chore and teach the
    /// owner to click through it without reading.
    static let TARGETS = ["com.apple.Notes"]

    static func all() -> [Row] {
        var rows = [accessibility(), screenRecording(), microphone(), speech(),
                    calendar()]
        rows.append(contentsOf: TARGETS.map(automation))
        return rows
    }

    // ---------------------------------------------------- window reach
    //
    // CAN VESPER REACH A WINDOW ON A DESKTOP THAT IS NOT SHOWING?
    //
    // Owner, 2026-09-11: "vesper should be able to open and fully manage all
    // windows in any other desktop if it was requested to do it." That settles
    // the AUTHORITY question. It does not settle the MECHANISM one, and
    // `WindowBridge.element(forPID:windowId:)` carries a measurement from
    // 2026-09-09 saying the accessibility tree "answers only for the Desktop
    // that is showing" -- on which the whole one-Desktop limit rests.
    //
    // THAT MEASUREMENT IS WORTH RE-TAKING, because the session that made it was
    // also fighting a separate bug in the same function: Safari answers the
    // window query with an EMPTY list on the first attempt and its real windows
    // a moment later. A conclusion drawn while that was biting could have
    // mistaken "asked too early" for "another Desktop is unreachable".
    //
    // SO THIS COMPARES THE TWO LISTS DIRECTLY. Every on-screen window from the
    // window server, against every window the accessibility tree will hand over,
    // matched by CGWindowID rather than by geometry -- `_AXUIElementGetWindow`
    // resolves on this node, measured 2026-09-11, which is what makes an exact
    // match possible at all. Two windows of one process at identical size and
    // position used to be indistinguishable here.
    private typealias GetWindowFn =
        @convention(c) (AXUIElement, UnsafeMutablePointer<CGWindowID>) -> AXError

    private static func axWindowId(_ el: AXUIElement) -> CGWindowID? {
        guard let sym = dlsym(dlopen(nil, RTLD_LAZY),
                              "_AXUIElementGetWindow") else { return nil }
        let fn = unsafeBitCast(sym, to: GetWindowFn.self)
        var wid: CGWindowID = 0
        return fn(el, &wid) == .success && wid != 0 ? wid : nil
    }

    static func windowReach() {
        print("")
        print("window reach — can vesper touch a window that is not on screen?")
        print(String(repeating: "-", count: 72))
        guard AXIsProcessTrusted() else {
            print("  cannot tell: Accessibility is not granted to this process.")
            print("  This reads the grant of whoever LAUNCHED vesper, so run it")
            print("  as vesper (open -n) rather than from a shell.")
            return
        }
        let opts: CGWindowListOption = [.excludeDesktopElements]
        let all = (CGWindowListCopyWindowInfo(opts, kCGNullWindowID)
                   as? [[String: Any]]) ?? []
        let onScreen = Set(((CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]]) ?? []).compactMap { $0["kCGWindowNumber"] as? Int })

        var byPid: [pid_t: [Int]] = [:]
        for w in all {
            guard let pid = w["kCGWindowOwnerPID"] as? pid_t,
                  let num = w["kCGWindowNumber"] as? Int,
                  (w["kCGWindowLayer"] as? Int) == 0 else { continue }
            byPid[pid, default: []].append(num)
        }
        var reachableOff = 0, unreachableOff = 0, reachableOn = 0
        for (pid, nums) in byPid {
            let app = AXUIElementCreateApplication(pid)
            var value: CFTypeRef?
            guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString,
                                                &value) == .success,
                  let ws = value as? [AXUIElement] else { continue }
            let axIds = Set(ws.compactMap { axWindowId($0) }.map(Int.init))
            for n in nums {
                let here = onScreen.contains(n)
                if axIds.contains(n) {
                    if here { reachableOn += 1 } else { reachableOff += 1 }
                } else if !here {
                    unreachableOff += 1
                }
            }
        }
        print("  on the showing Desktop, reachable via accessibility: \(reachableOn)")
        print("  on ANOTHER Desktop, reachable via accessibility:     \(reachableOff)")
        print("  on ANOTHER Desktop, NOT reachable:                   \(unreachableOff)")
        if reachableOff > 0 {
            print("  → the 2026-09-09 measurement does not hold: the tree DOES")
            print("    answer for other Desktops, so cross-Desktop management")
            print("    needs no relocation trick at all.")
        } else if unreachableOff > 0 {
            print("  → confirmed: accessibility answers only for the showing")
            print("    Desktop. Cross-Desktop acts need another mechanism.")
        } else {
            print("  → inconclusive: no windows on any other Desktop to test")
            print("    with. Leave a window on a second Desktop and re-run.")
        }
    }

    /// The trip, in the order the owner should walk it.
    ///
    /// ORDERED BY WHAT BLOCKS WHAT, not alphabetically: a missing grant early in
    /// this list stops whole features, and one late stops one verb.
    static func report(to path: String? = nil) {
        if let path {
            // `open -n` DISCARDS STDOUT, and this reader exists to be run that
            // way -- as vesper, so the grants it reports are vesper's. A report
            // whose only output channel is a terminal cannot be produced by the
            // one launch method that answers correctly.
            let pipe = Pipe()
            let saved = dup(STDOUT_FILENO)
            dup2(pipe.fileHandleForWriting.fileDescriptor, STDOUT_FILENO)
            report(to: nil)
            windowReach()
            fflush(stdout)
            dup2(saved, STDOUT_FILENO)
            close(saved)
            pipe.fileHandleForWriting.closeFile()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            try? data.write(to: URL(fileURLWithPath: path))
            return
        }
        let rows = all()
        let missing = rows.filter { $0.state != GRANTED }
        print("VESPER — permissions, read without asking for any of them")
        print(String(repeating: "-", count: 72))
        for row in rows {
            let mark: String
            switch row.state {
            case GRANTED:      mark = "[ok]     "
            case DENIED:       mark = "[REFUSED]"
            case UNDETERMINED: mark = "[ask]    "
            default:           mark = "[?]      "
            }
            print("\(mark) \(row.what)")
            if !row.why.isEmpty { print("          \(row.why)") }
            if row.state != GRANTED { print("          → \(row.howToGrant)") }
        }
        print(String(repeating: "-", count: 72))
        if missing.isEmpty {
            print("nothing to grant. every permission vesper needs is in place.")
        } else {
            print("\(missing.count) of \(rows.count) still to grant: "
                  + missing.map(\.what).joined(separator: ", "))
            // SAID EVERY TIME, because it is the thing that wastes the trip.
            print("")
            print("REBUILDING VESPER REVOKES ALL OF THESE. Grants are keyed to "
                  + "the app's cdhash and")
            print("every build re-signs it, so do this AFTER the last build or "
                  + "do it twice.")
        }
    }
}
