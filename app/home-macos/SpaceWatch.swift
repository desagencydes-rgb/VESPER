// VESPER — reading which Desktop is active, when the OS will not say.
//
// Promoted out of `residency_probe.swift`, where it was the instrument. It is
// in the app now because §2.3a's placement rule needs it at runtime, not only
// in a test: there is no public API that names a Space, so VESPER cannot ask
// to be put on Desktop 2. It posts the switch and then CONFIRMS IT LANDED,
// and only then creates the ground. Switch first, then create.
//
// HOW THE ABSENCE OF AN API BECAME THE INSTRUMENT. `CGWindowListCopyWindowInfo`
// with `.optionOnScreenOnly` returns the windows on the ACTIVE Space and no
// others -- the same limitation that makes Spaces unaddressable makes this
// list a residency signal. Two samples taken on different Desktops share few
// or no windows; two taken on the same Desktop share nearly all of them.
//
// FOREIGN WINDOWS ONLY, and window NUMBERS rather than a count. A count cannot
// tell "you switched Desktops" from "you opened something" -- both change it
// by one. Our own windows are excluded because the question is where the owner
// is, and a window of ours that follows the owner would answer it wrong in
// precisely the case that matters.
//
// kCGWindowName is NOT read. It would require Screen Recording, and none of
// owner / layer / bounds / number does. An instrument that costs a permission
// it does not need is a bad trade.

import AppKit

struct SeenWindow {
    let owner: String
    let layer: Int
    let number: Int
    let pid: Int
    let bounds: CGRect
}

enum SpaceWatch {

    static func onScreen() -> [SeenWindow] {
        guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
                as? [[String: Any]] else { return [] }
        return raw.compactMap { w in
            guard let n = w[kCGWindowNumber as String] as? Int,
                  let l = w[kCGWindowLayer as String] as? Int,
                  let p = w[kCGWindowOwnerPID as String] as? Int else { return nil }
            var r = CGRect.zero
            if let b = w[kCGWindowBounds as String] as? [String: Any] {
                r = CGRect(x: (b["X"] as? CGFloat) ?? 0, y: (b["Y"] as? CGFloat) ?? 0,
                           width: (b["Width"] as? CGFloat) ?? 0,
                           height: (b["Height"] as? CGFloat) ?? 0)
            }
            return SeenWindow(owner: (w[kCGWindowOwnerName as String] as? String) ?? "?",
                              layer: l, number: n, pid: p, bounds: r)
        }
    }

    /// Is the system Dock occupying screen space right now?
    ///
    /// HOME-ARCHITECTURE §10 wants VESPER's main menu to dim to 30% "while
    /// occluded" by the system Dock. The obvious route -- find the Dock's window
    /// in `CGWindowListCopyWindowInfo` and look at its bounds -- does not work,
    /// and the way it fails is silent. Measured 2026-08-24: the Dock process
    /// owns exactly two on-screen windows and both are 1728x1117, the whole
    /// display. The bar is drawn INSIDE one of them, so its bounds say nothing
    /// about whether it is showing, and a height filter over that list returns
    /// false forever while looking like a working check.
    ///
    /// `NSScreen.visibleFrame` is a real reading of the same fact: the window
    /// server insets it by whatever the Dock reserves.
    ///
    /// WHAT THIS CANNOT SEE, and it is the case §10 actually describes. With
    /// autohide on -- which is precisely what VESPER sets while it is frontmost
    /// -- the Dock's cursor-to-edge reveal reserves NO space, so `visibleFrame`
    /// does not move and this returns false while the Dock is visibly over the
    /// main menu. There is no public API for the transient reveal. The
    /// alternative is to watch the cursor near the bottom edge, which is
    /// watching the CAUSE and reporting it as the effect, and this file is not
    /// going to do that quietly. So the dim covers the persistent Dock and the
    /// transient reveal is a named gap.
    /// Takes the screen only to identify WHICH one; the geometry is re-fetched,
    /// because an NSScreen object caches its frames and a reference held from
    /// before a change reports the world as it was.
    static func systemDockVisible(on screen: NSScreen) -> Bool {
        let s = NSScreen.screens.first { $0.frame == screen.frame } ?? NSScreen.main ?? screen
        return s.visibleFrame.minY > s.frame.minY + 1
    }

    /// The fingerprint of the Desktop that is active right now: the numbers of
    /// every ordinary window that is not ours.
    static func fingerprint() -> Set<Int> {
        let me = Int(ProcessInfo.processInfo.processIdentifier)
        return Set(onScreen().filter { $0.pid != me && $0.layer == 0 }.map(\.number))
    }

    /// Two empty sets count as identical, not as a switch. An empty Desktop is
    /// a real thing on this machine -- the owner's Desktop 2 is empty by
    /// design -- and calling "nothing here, nothing there" a change would
    /// report a switch every time VESPER looked at its own room twice.
    static func overlap(_ a: Set<Int>, _ b: Set<Int>) -> Double {
        if a.isEmpty && b.isEmpty { return 1.0 }
        return Double(a.intersection(b).count) / Double(a.union(b).count)
    }

    /// Did the active Desktop change, relative to a fingerprint taken before?
    ///
    /// The 0.5 threshold is deliberately loose. It is not trying to detect a
    /// window opening; it is trying to detect a room changing, and those
    /// differ by an order of magnitude. A tight threshold would turn every
    /// Slack notification into a Desktop switch.
    static func switched(from before: Set<Int>, threshold: Double = 0.5) -> Bool {
        overlap(before, fingerprint()) < threshold
    }

    /// Is a window of ours on the active Desktop right now? Asked of the
    /// window server, not of the window -- `NSWindow.isVisible` is the
    /// window's own opinion and stays true on a Desktop nobody is looking at.
    static func isOnActiveSpace(_ number: Int) -> Bool {
        onScreen().contains { $0.number == number }
    }

    // MARK: - The anchor, for when there is no ground window yet

    /// A window whose only job is to exist, so the window server has
    /// something to answer "which Space is this process on" with.
    ///
    /// §9f, measured 2026-09-07: the empty-Desktop poll (`--on-empty-desktop`)
    /// read Desktop 1's five windows while the owner was on Desktop 2 -- and at
    /// the moment it asked, VESPER had no `.managed` window anywhere, only the
    /// island's own `.canJoinAllSpaces` one. `residency_probe` already proved
    /// `fingerprint()` reliable AFTER a `.managed` window exists: 151 samples,
    /// foreign-window overlap 0.00 on real switches. `HomeController.dock`'s
    /// reconciler (`Home.swift`) reads it the same way, after its ground
    /// exists, and is correct. The gap is only the moment before any `.managed`
    /// window has been created -- exactly the moment this poll runs in.
    ///
    /// So this exists to CLOSE that gap, not to read anything itself: a 1x1,
    /// alpha-0, non-interactive `.managed` window, ordered onto whichever
    /// Space is active the instant it is created -- the same placement rule
    /// `residency_probe` measured for the real ground. Once it exists,
    /// `fingerprint()` is answering the question this file already proved it
    /// can answer.
    ///
    /// NOT YET CROSS-DESKTOP VERIFIED. Compiles, creates and closes cleanly on
    /// a single Desktop. The claim this fixes needs the same kind of check
    /// `residency_probe` needed -- the owner switching Desktops while it runs
    /// -- because there is no public way to do that from here. See
    /// `HOME-WORKBENCH.md` §9f for the ask.
    final class Anchor {
        private var window: NSWindow?

        init() {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1, height: 1),
                              styleMask: [.borderless], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false
            w.alphaValue = 0
            w.ignoresMouseEvents = true
            w.hasShadow = false
            w.collectionBehavior = [.managed]   // NOT canJoinAllSpaces -- the whole point
            w.orderFrontRegardless()
            window = w
        }

        /// Idempotent: the poll loop closes this once, on whichever branch it
        /// takes (found an empty Desktop, or gave up at the deadline).
        func close() {
            window?.orderOut(nil)
            window?.close()
            window = nil
        }
    }

    // MARK: - Switching, and why it is a keystroke

    /// macOS binds "switch to Desktop N" to a symbolic hotkey, and that is the
    /// ONLY public route to a specific Desktop. `com.apple.symbolichotkeys`
    /// ids 118 and 119 are Desktop 1 and 2; the parameters measured on this
    /// machine are (65535, 19, 262144) -- keycode 19, which is the "2" key,
    /// with Control. Bound BY KEYCODE, so it is the physical key and not the
    /// character, and a different layout does not change it.
    ///
    /// Posting it needs Accessibility, granted once to VESPER.app. That grant
    /// is why this lives in the app and not in a probe: granted to a loose
    /// binary it would be granted to the Terminal.
    ///
    /// NOT WIRED YET -- deliberately. The grant has not been asked for, and
    /// asking for it from a build that is still moving would spend the owner's
    /// one clean first prompt on a binary that is about to change.
    static let switchHotkeyNote = """
        Control + <N>, posted as a keycode. Requires Accessibility, granted to \
        VESPER.app. See HOME-ARCHITECTURE §2.3a.
        """
}
