import AppKit
import ApplicationServices

// THE PLATFORM HALF OF WINDOW MANAGEMENT, AND NOTHING ELSE.
//
// `core/windows.py` decides WHICH window may be touched and `contracts/policy/
// host_actions.toml` declares WHAT may be done to one. This file knows neither.
// It enumerates and it acts, and every refusal it produces is a refusal of the
// platform -- no grant, no such window, no accessibility handle -- never a
// refusal of policy. That split is the same one the action vocabulary makes
// when its header says rows name an abstract effect and the adapter owns the
// mechanism.
//
// A HELPER IS A MODE OF THIS BINARY, NEVER A LOOSE SCRIPT. The runtime shells
// out to `VESPER --windows-list` rather than to a python or shell helper of its
// own, so everything that touches the owner's machine runs as VESPER, with
// VESPER's identity, and inherits VESPER's TCC answers rather than a terminal's.
//
// TITLES ARE NOT READ, and this is not an oversight to be corrected later.
// `SpaceWatch` already refuses `kCGWindowName` because it needs Screen
// Recording, and `host_actions.toml`'s observe tier says plainly that anything
// reading CONTENT is a new row and a new decision. A window title is a document
// name or a subject line. Enumerating windows is inventory; reading their
// titles is content, and it belongs to the UI-view decision.
enum WindowBridge {

    // Layers below zero are the system's own furniture -- the wallpaper, the
    // Dock, the menu bar shadow. `SpaceWatch.fingerprint()` counts layer 0
    // only for the same reason: they are not windows anyone opened.
    private static func manageable(_ w: SeenWindow) -> Bool {
        w.layer == 0 && w.bounds.width > 40 && w.bounds.height > 40
    }

    /// Everything on the ACTIVE Desktop, as inventory.
    ///
    /// ONLY THE ACTIVE DESKTOP, AND THAT IS A PLATFORM LIMIT RATHER THAN A
    /// CHOICE. `CGWindowListCopyWindowInfo(.optionOnScreenOnly)` answers for
    /// the Space that is showing. There is no public call that says which Space
    /// an off-screen window is on -- the private one is `CGSCopySpacesForWindows`
    /// -- so a full cross-Desktop inventory is not available without a decision
    /// the owner has to make. Reporting the active Desktop honestly is better
    /// than reporting a partial list as though it were everything, so the
    /// payload says which Desktop it covers and the caller can say so too.
    static func list() -> [[String: Any]] {
        let fp = SpaceWatch.fingerprint()
        return SpaceWatch.onScreen().filter(manageable).map { w in
            [
                "window_id": String(w.number),
                "pid": w.pid,
                // THE APPLICATION NAME IS A LABEL FOR THE OWNER TO READ. It is
                // carried so a line can say "the editor on vesper's desktop",
                // and `core/windows.py` is explicit that no rule may branch on
                // it -- INV-HW-1 applied to software instead of hardware.
                "app_label": w.owner,
                "x": Int(w.bounds.origin.x), "y": Int(w.bounds.origin.y),
                "width": Int(w.bounds.width), "height": Int(w.bounds.height),
                // The active Desktop has no stable public identifier, so it is
                // named by the fingerprint that already decides Desktop
                // identity everywhere else in this app. Two reads of the same
                // Desktop agree; a switch changes it, which is the property
                // `SpaceWatch.switched` is built on.
                "desktop_id": desktopId(fp),
                "on_active_desktop": true,
            ]
        }
    }

    /// Is the Desktop showing right now the one VESPER's ground is on?
    ///
    /// THIS WAS THE MOST DANGEROUS BUG IN THE FIRST DRAFT AND IT LOOKED LIKE
    /// NOTHING. The inventory reported the ACTIVE Desktop's id, and the caller
    /// passed that same id as "VESPER's Desktop" -- so every window was
    /// trivially on VESPER's Desktop, clause 1 of the ownership rule applied to
    /// all of them, and all six of the owner's windows came back as free for
    /// VESPER to arrange. The owner would have discovered it as "it moved my
    /// windows", which is exactly the trust this feature cannot afford to spend.
    ///
    /// THE ACTIVE DESKTOP IS NOT VESPER'S DESKTOP. It is only VESPER's while
    /// VESPER's ground is on it, so that is what gets checked: a window owned
    /// by this same bundle, present on the Space that is showing. The home
    /// process and this short-lived one run from one binary, so they report the
    /// same owner name -- and this process has no window of its own to be
    /// confused by.
    ///
    /// NO GROUND, NO CLAUSE 1. When VESPER holds no Desktop the answer is
    /// `null`, and `core/windows.py` then falls through to provenance for every
    /// window. That is the correct reading rather than a degraded one: there is
    /// no workspace to tidy.
    static func vespersDesktop() -> String? {
        let name = ProcessInfo.processInfo.processName
        let selfPid = Int(ProcessInfo.processInfo.processIdentifier)
        // THIS PROCESS'S OWN WINDOWS DO NOT COUNT, and leaving them in made the
        // answer always yes. `main.swift` builds a controller with a panel
        // before reaching any of these modes, so the very act of asking "is
        // VESPER's ground here" created a VESPER window on the Desktop being
        // asked about -- and it is a `.canJoinAllSpaces` panel, so it would
        // have answered yes on EVERY Desktop.
        //
        // main.swift's own header says probes go "before anything that opens a
        // window ... an instrument that disturbs the thing it measures is not
        // one". This is that rule biting the one instrument whose wrong answer
        // hands VESPER the owner's entire session.
        // AND NEITHER DOES THE ISLAND, WHICH IS THE HARDER HALF. Measured
        // 2026-09-08: with the home still WAITING for an empty Desktop and no
        // ground anywhere, this matched a VESPER window at layer 1001, 370x48
        // -- the island. It is `.canJoinAllSpaces` ON PURPOSE, which is the
        // whole point of `SpaceWatch.Anchor`'s comment that `.managed` is "NOT
        // canJoinAllSpaces -- the whole point". So the island is on EVERY
        // Desktop, and matching it would have declared every Desktop VESPER's.
        //
        // THE GROUND IS THE ONLY THING THAT MAKES A DESKTOP VESPER'S. It sits
        // BELOW the owner's windows -- `--home` describes it as "ground at
        // normal-1" -- while every piece of VESPER's chrome floats above them.
        // The sign of the layer is therefore the discriminator, and the size
        // test refuses a small stray: a ground covers the display it is on.
        let present = SpaceWatch.onScreen().contains {
            $0.owner == name && $0.pid != selfPid && $0.layer < 0
                && $0.bounds.width > 400 && $0.bounds.height > 300
        }
        return present ? desktopId() : nil
    }

    static func desktopId(_ fp: Set<Int> = SpaceWatch.fingerprint()) -> String {
        fp.isEmpty ? "desktop-empty"
                   : "desktop-" + String(fp.sorted().map(String.init).joined(separator: "-").hashValue,
                                         radix: 36)
    }

    // MARK: - Acting

    /// Is the Accessibility grant present? Asked WITHOUT prompting.
    ///
    /// `AXIsProcessTrustedWithOptions` with the prompt option shows a dialog,
    /// and a dialog raised by a background process the owner is not looking at
    /// is a dialog they will dismiss. The runtime needs to be able to REPORT
    /// that the grant is missing -- an honest UNAVAILABLE with a reason -- which
    /// is a different thing from asking for it.
    static func accessible() -> Bool { AXIsProcessTrusted() }

    private static func element(forPID pid: Int, windowId: String) -> AXUIElement? {
        let app = AXUIElementCreateApplication(pid_t(pid))
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString,
                                            &value) == .success,
              let windows = value as? [AXUIElement] else { return nil }
        // THE ACCESSIBILITY TREE DOES NOT CARRY THE CGWindow NUMBER, so the
        // window is identified by matching geometry against the inventory that
        // was just read. That is a real weakness and it is named rather than
        // hidden: two windows of one process at identical size and position are
        // indistinguishable here, and the match is refused rather than guessed.
        guard let target = SpaceWatch.onScreen().first(where: {
            String($0.number) == windowId && $0.pid == pid }) else { return nil }
        var matches: [AXUIElement] = []
        for w in windows {
            var pv: CFTypeRef?
            var sv: CFTypeRef?
            guard AXUIElementCopyAttributeValue(w, kAXPositionAttribute as CFString, &pv) == .success,
                  AXUIElementCopyAttributeValue(w, kAXSizeAttribute as CFString, &sv) == .success
            else { continue }
            var p = CGPoint.zero, s = CGSize.zero
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
            if abs(p.x - target.bounds.origin.x) < 2, abs(p.y - target.bounds.origin.y) < 2,
               abs(s.width - target.bounds.width) < 2, abs(s.height - target.bounds.height) < 2 {
                matches.append(w)
            }
        }
        lastMatchReport = "cg=(\(Int(target.bounds.origin.x)),\(Int(target.bounds.origin.y)) "
            + "\(Int(target.bounds.width))x\(Int(target.bounds.height))) ax=["
            + axGeometries(windows).joined(separator: " ") + "] matched=\(matches.count)"
        return matches.count == 1 ? matches[0] : nil
    }

    /// What the accessibility tree says, so a failed match can be diagnosed
    /// from evidence rather than from a theory about coordinate spaces.
    static var lastMatchReport = ""

    private static func axGeometries(_ windows: [AXUIElement]) -> [String] {
        windows.compactMap { w in
            var pv: CFTypeRef?
            var sv: CFTypeRef?
            guard AXUIElementCopyAttributeValue(w, kAXPositionAttribute as CFString, &pv) == .success,
                  AXUIElementCopyAttributeValue(w, kAXSizeAttribute as CFString, &sv) == .success
            else { return nil }
            var p = CGPoint.zero, s = CGSize.zero
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
            return "(\(Int(p.x)),\(Int(p.y)) \(Int(s.width))x\(Int(s.height)))"
        }
    }

    /// Move or resize. Returns the geometry OBSERVED AFTERWARDS, never the
    /// geometry that was requested.
    ///
    /// CLAUDE.md: "an instrument's self-report is not evidence ... re-read the
    /// world after acting". `AXUIElementSetAttributeValue` returning `.success`
    /// means the message was accepted, not that the window moved -- a window
    /// can refuse a size below its minimum, or be snapped by the system, and
    /// report success either way. So the caller is handed what is true now and
    /// can compare it to what it asked for.
    static func geometry(pid: Int, windowId: String,
                         x: Int?, y: Int?, w: Int?, h: Int?) -> [String: Any] {
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to VESPER, "
                  + "so no window can be moved or resized. Grant it with "
                  + "`open -n app/VESPER.app --args --accessibility-consent`."]
        }
        guard let el = element(forPID: pid, windowId: windowId) else {
            return ["ok": false, "reason": "no unique accessibility handle for window "
                  + "\(windowId) of pid \(pid) -- it is gone, on another Desktop, "
                  + "or indistinguishable from a sibling at the same geometry. "
                  + lastMatchReport]
        }
        let before = SpaceWatch.onScreen().first { String($0.number) == windowId }
        var codes: [String] = []
        if let x, let y {
            var p = CGPoint(x: CGFloat(x), y: CGFloat(y))
            if let v = AXValueCreate(.cgPoint, &p) {
                codes.append("pos=\(AXUIElementSetAttributeValue(el, kAXPositionAttribute as CFString, v).rawValue)")
            }
        }
        if let w, let h {
            var s = CGSize(width: CGFloat(w), height: CGFloat(h))
            if let v = AXValueCreate(.cgSize, &s) {
                codes.append("size=\(AXUIElementSetAttributeValue(el, kAXSizeAttribute as CFString, v).rawValue)")
            }
        }
        // RE-READ FROM THE ACCESSIBILITY TREE, NOT FROM `CGWindowList`.
        //
        // The first version of this read the window list back and reported
        // `ok: after != nil` -- which asks only whether the window still
        // EXISTS. It returned `ok: true` on a move that plainly did not
        // happen, with `before` and `after` both at the original position,
        // because the window was of course still there. That is precisely the
        // failure CLAUDE.md names: a launcher returning 0 is not a running
        // process, and a move reporting success is not a moved window.
        //
        // `CGWindowList` was also the wrong instrument for the re-read. It is
        // a snapshot the window server updates on its own schedule, so a read
        // taken immediately after a set can legitimately still show the old
        // frame -- the answer would then depend on timing rather than on what
        // happened. The accessibility tree answers for the window itself.
        var ax = axFrame(el)
        let wantedPos = (x != nil && y != nil)
        let wantedSize = (w != nil && h != nil)
        var landed = true
        if wantedPos { landed = landed && abs(ax.origin.x - CGFloat(x!)) < 3
                                       && abs(ax.origin.y - CGFloat(y!)) < 3 }
        if wantedSize { landed = landed && abs(ax.size.width - CGFloat(w!)) < 3
                                        && abs(ax.size.height - CGFloat(h!)) < 3 }
        return ["ok": landed,
                "before": rect(before?.bounds), "after": rect(ax),
                "ax_result": codes.joined(separator: " "),
                // A WINDOW REFUSING A GEOMETRY IS NOT AN ERROR, and the
                // difference matters to whoever reads this. Applications
                // enforce minimum sizes and the system snaps to displays, so
                // "asked for 200x200, got 400x300" is the window exercising a
                // constraint it is entitled to. What must never happen is that
                // being reported as success.
                "reason": landed ? "" : "the window did not take the requested "
                    + "geometry -- it may enforce a minimum size, be full-screen, "
                    + "or be managed by the system. Asked for "
                    + (wantedPos ? "(\(x!),\(y!)) " : "")
                    + (wantedSize ? "\(w!)x\(h!) " : "")
                    + "and it is at (\(Int(ax.origin.x)),\(Int(ax.origin.y))) "
                    + "\(Int(ax.size.width))x\(Int(ax.size.height))"]
    }

    /// The window's own frame, straight from the accessibility tree.
    private static func axFrame(_ el: AXUIElement) -> CGRect {
        var pv: CFTypeRef?
        var sv: CFTypeRef?
        var p = CGPoint.zero, s = CGSize.zero
        if AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &pv) == .success {
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
        }
        if AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sv) == .success {
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
        }
        return CGRect(origin: p, size: s)
    }

    /// Close a window through its own close button.
    ///
    /// `AXPress` ON THE CLOSE BUTTON, not a termination. The distinction is the
    /// whole safety story: pressing the button is what the owner clicking it
    /// would do, so an application with unsaved work gets to put up its own
    /// "save changes?" sheet. Killing the process would take the decision away
    /// from the one party entitled to make it, and `host_actions.toml` already
    /// keeps `terminate_process` disabled for that reason.
    static func close(pid: Int, windowId: String) -> [String: Any] {
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to VESPER"]
        }
        guard let el = element(forPID: pid, windowId: windowId) else {
            return ["ok": false, "reason": "no unique accessibility handle for that "
                  + "window. " + lastMatchReport]
        }
        var btn: CFTypeRef?
        guard AXUIElementCopyAttributeValue(el, kAXCloseButtonAttribute as CFString,
                                            &btn) == .success else {
            return ["ok": false, "reason": "this window has no close button to press"]
        }
        AXUIElementPerformAction(btn as! AXUIElement, kAXPressAction as CFString)
        // RE-READ, because a modal "save changes?" sheet means the window is
        // still there and the honest answer is that it did not close.
        let gone = !SpaceWatch.onScreen().contains { String($0.number) == windowId }
        return ["ok": gone,
                "reason": gone ? "" : "the close was pressed and the window is still "
                                    + "open -- the application is likely asking the "
                                    + "owner whether to save"]
    }

    private static func rect(_ r: CGRect?) -> [String: Int] {
        guard let r else { return [:] }
        return ["x": Int(r.origin.x), "y": Int(r.origin.y),
                "width": Int(r.width), "height": Int(r.height)]
    }

    static func emit(_ obj: Any) {
        if let d = try? JSONSerialization.data(withJSONObject: obj),
           let s = String(data: d, encoding: .utf8) { print(s) }
    }
}
