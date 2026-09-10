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

    /// Every window, on every Desktop, not only the one showing.
    ///
    /// `onScreen()` passes `.optionOnScreenOnly` and therefore answers about
    /// ONE Desktop. That is right for judging ownership -- the rule is about
    /// the room VESPER is in -- and wrong for FINDING a window to act on, and
    /// the two were the same call. Measured 2026-09-09: `reopen` created two
    /// TextEdit windows on another Desktop, could not see either, reported
    /// "the application would not open a new window", and left them behind.
    /// It had done the thing it said it had failed to do.
    ///
    /// Public API throughout: passing no options returns windows regardless of
    /// which Space they are on. No private symbol is needed to look.
    static func allWindows() -> [SeenWindow] {
        guard let raw = CGWindowListCopyWindowInfo([], kCGNullWindowID)
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

    /// The highest window number in existence right now, on EVERY Desktop.
    ///
    /// A FRONTIER, NOT A COUNT. `onScreen()` sees only the active Desktop, so a
    /// before/after comparison built on it calls every window on a DIFFERENT
    /// Desktop "new" the moment the active Desktop changes -- which is how
    /// `reopen` came to hand back one of the owner's Safari windows as a window
    /// VESPER had just opened (measured 2026-09-09, live).
    ///
    /// This is sound because window numbers are allocated monotonically and are
    /// not reused within a boot. MEASURED on this host, 2026-09-09: 41 windows
    /// created and destroyed, including 25 sequential open-close cycles, gave 41
    /// distinct strictly increasing numbers and no reuse. So a window whose
    /// number exceeds the frontier taken before an action was created after it,
    /// wherever it happens to live. A reboot resets the counter, which is why
    /// nothing here is persisted across one.
    static func highWaterNumber() -> Int {
        guard let raw = CGWindowListCopyWindowInfo([], kCGNullWindowID)
                as? [[String: Any]] else { return 0 }
        return raw.compactMap { $0[kCGWindowNumber as String] as? Int }.max() ?? 0
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
        /// The probe in `SpacesHatch.effective()` needs something to ask
        /// "which Desktop is this on" about, and this window is the only one
        /// VESPER can move without touching the owner's session.
        var windowNumber: Int? { window.map { Int($0.windowNumber) } }

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

/// WHICH DESKTOP IS SHOWING, BY ORDER RATHER THAN BY CONTENTS.
///
/// THE OWNER'S RULE, 2026-09-10: *"never take Desktop 1"*. It supersedes their
/// 2026-08-24 one ("if both desktops are empty, say on boot for example, it can
/// just take one"), and it supersedes it for a reason they hit that morning: at
/// BOOT every Desktop is empty, so "the first empty Desktop" is Desktop 1 — the
/// one they come back to. `foreign=0` in the ground log was true and beside the
/// point.
///
/// `WindowBridge.desktopId()` CANNOT ANSWER THIS. It hashes the window numbers
/// present, so every empty Desktop is the same string, `desktop-empty` — which
/// is exactly the state this rule is about. Contents cannot distinguish rooms
/// that are all empty; only ORDER can.
///
/// AND THE ORDER IS A FILE, NOT A PRIVATE CALL. `CGSGetActiveSpace` and friends
/// are SPI, and §11.1a already owes the owner a decision about one private API;
/// adding a second unasked would be taking that decision for them. The
/// WindowServer writes the ordered Space list to `com.apple.spaces.plist`, and
/// reading a file the user owns is neither SPI nor a new permission.
///
/// FULLSCREEN SPACES ARE NOT DESKTOPS. Measured 2026-09-10 on this Mac: the list
/// held `[(1, type 0), (3, type 4, fs_wid), (6, type 0)]` — two real Desktops
/// and one fullscreen window sitting between them in the order. Counting the
/// raw list would make Desktop 2 look like Desktop 3 the moment anything is
/// full-screened, so `type == 0` is the filter and it is load-bearing.
enum SpaceOrder {
    static let plist = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Preferences/com.apple.spaces.plist")

    /// The Space showing RIGHT NOW, live, or nil if that cannot be asked.
    ///
    /// THIS IS A PRIVATE API AND THE OWNER TOOK THAT DECISION, 2026-09-10, after
    /// being shown the measurement that forced it. There is no public route:
    /// `CGWindowListCopyWindowInfo` on macOS 26.5 returns eleven keys and
    /// `kCGWindowWorkspace` is not among them -- probed, not assumed.
    ///
    /// AND THE FILE COULD NOT STAND IN FOR IT. `com.apple.spaces.plist` carries
    /// a `Current Space`, and the first version of this rule read it. Measured
    /// the same afternoon: the file sat unwritten for 4.5 minutes across several
    /// of the owner's Desktop switches, so it answers with a stale value
    /// CONFIDENTLY -- which is worse than not answering, because the fail-closed
    /// path never fires. Vesper planted on Desktop 1 with the guard in place and
    /// the guard reading "you are on the third".
    ///
    /// THE FILE IS STILL USED FOR THE PART THAT IS STABLE. Which Spaces exist
    /// and in what ORDER changes only when the owner adds or removes one; that
    /// is not the volatile half and it needs no private call.
    ///
    /// LOADED BY NAME AT RUNTIME, NEVER LINKED. A macOS update that removes the
    /// symbol then produces `nil` here -- which this file's callers already
    /// treat as "cannot tell" and refuse on -- instead of a process that will
    /// not start. An SPI that fails loudly and safely is the only kind worth
    /// taking, and this makes its absence a measurable condition rather than a
    /// crash.
    private static let activeSpaceFn: ((Int32) -> UInt64)? = {
        typealias Conn = @convention(c) () -> Int32
        typealias Active = @convention(c) (Int32) -> UInt64
        guard let h = dlopen("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
                             RTLD_LAZY),
              let c = dlsym(h, "CGSMainConnectionID"),
              let a = dlsym(h, "CGSGetActiveSpace") else { return nil }
        let conn = unsafeBitCast(c, to: Conn.self)
        let active = unsafeBitCast(a, to: Active.self)
        let cid = conn()
        return { _ in active(cid) }
    }()

    static func activeSpaceId() -> Int? {
        guard let f = activeSpaceFn else { return nil }
        let v = f(0)
        return v == 0 ? nil : Int(v)
    }

    /// Is the Desktop showing the FIRST one? `nil` when that cannot be told.
    ///
    /// NIL IS NOT FALSE, AND THE CALLER MUST NOT TREAT IT AS ONE. Unreadable,
    /// unparseable, a shape this does not recognise, or a current Space that is
    /// not in the list at all — every one of those means "cannot tell", and the
    /// only answer that honours "never take Desktop 1" is to decline to plant.
    /// Returning false on a bad read would take the owner's Desktop precisely
    /// when vesper had least idea where it was.
    ///
    /// READ FRESH EVERY TIME, never cached: the answer changes when the owner
    /// switches Desktop, which is the whole reason it is being asked.
    static func onFirstDesktop() -> Bool? {
        guard let data = try? Data(contentsOf: plist),
              let root = try? PropertyListSerialization.propertyList(
                  from: data, options: [], format: nil) as? [String: Any],
              let cfg = root["SpacesDisplayConfiguration"] as? [String: Any],
              let mgmt = cfg["Management Data"] as? [String: Any],
              let monitors = mgmt["Monitors"] as? [[String: Any]]
        else { return nil }
        // THE LIVE ID, NOT THE FILE'S. `Current Space` in this plist is stale --
        // measured at 4.5 minutes across several switches -- and a stale answer
        // here is the one that takes the owner's Desktop.
        guard let curId = activeSpaceId() else { return nil }
        for m in monitors {
            guard let spaces = m["Spaces"] as? [[String: Any]] else { continue }
            let desktops = spaces.compactMap { s -> Int? in
                ((s["type"] as? Int) ?? 0) == 0 ? s["ManagedSpaceID"] as? Int : nil
            }
            guard let first = desktops.first else { continue }
            // ONLY THE MONITOR WHOSE LIST HOLDS THIS SPACE ANSWERS. With two
            // displays each has its own set, and the one vesper is about to
            // plant on is the one containing the Space that is showing.
            if desktops.contains(curId) { return curId == first }
        }
        // NOT A PLAIN DESKTOP AT ALL, which is a real case and was missed by the
        // first version. `CGSGetActiveSpace` returned 54 on this Mac while the
        // owner's three Desktops were 1, 6 and 38: 54 is a FULLSCREEN space, and
        // the plist lists those interleaved with the Desktops. Vesper has no
        // business planting a ground inside somebody's fullscreen window, so an
        // id that is in no Desktop list resolves to "cannot tell" and refuses.
        return nil
    }

    /// The owner's sentence for why vesper is not setting up here.
    static func refusal(_ answer: Bool?) -> String? {
        switch answer {
        case .some(true):
            return "this is desktop 1, and you asked vesper never to take that "
                 + "one — it is where you come back to. switch to another empty "
                 + "desktop and vesper will set up there"
        case .none:
            return "vesper cannot tell which desktop this is, and you asked it "
                 + "never to take desktop 1 — so it is not taking this one "
                 + "either. either macos would not say which space is showing, "
                 + "or this is a fullscreen space rather than a desktop"
        case .some(false):
            return nil
        }
    }
}
