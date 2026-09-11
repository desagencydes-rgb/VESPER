import AppKit

// spaces-hatch-ok
//
// THE SECOND NAMED PRIVATE-API EXCEPTION, AND IT IS GRANTED ON THE SAME TERMS
// AS THE FIRST.
//
// `ISLAND-ARCHITECTURE.md` §2 forbids private API and gives its reason: "the
// failure mode is SILENT". `INV-HOME-5` generalises that and `CI-058` enforces
// it for the glass hatch -- one reviewed file, carrying the alarm that turns
// the silence into noise. This file is the second such hatch and it is written
// to that shape deliberately rather than by resemblance.
//
// WHY IT WAS NEEDED. macOS publishes no way to move a window to another Space,
// and no way to ask which Space an off-screen window is on.
// `CGWindowListCopyWindowInfo(.optionOnScreenOnly)` answers only for the Space
// that is showing. The owner asked for two things that need exactly this --
// "move windows between desktops (including vesper's desktop)" and "windows
// should be openable in vesper's desktop" -- and authorised the private route
// on 2026-09-08 after being shown the cost.
//
// THE PUBLIC ALTERNATIVE WAS CONSIDERED AND IS WORSE. Driving Mission Control
// to drag a window across is public, and it is slow, takes over the screen and
// steals the pointer mid-task -- the precise behaviour §11.5 exists to avoid.
//
// EVERYTHING IS RESOLVED AT RUNTIME THROUGH `dlsym`, NEVER LINKED.
// A missing private symbol must be a READING, not a launch failure and not a
// crash: VESPER has to keep running and report that relocation is unavailable,
// the same way `INV-HW-2` turns an unmeasurable throughput into an explicit
// UNAVAILABLE rather than a guess. Linking these would make a macOS point
// release stop the whole app instead of one feature.
enum SpacesHatch {

    // SkyLight is where these live on current macOS; they were in CoreGraphics
    // historically, so both are tried. A symbol that has MOVED is a different
    // fact from one that is GONE, and only the second should disable a feature.
    private static let frameworks = [
        "/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight",
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
    ]

    private typealias MainConnectionID = @convention(c) () -> Int32
    private typealias CopySpacesForWindows =
        @convention(c) (Int32, Int32, CFArray) -> CFArray?
    private typealias MoveWindowsToManagedSpace =
        @convention(c) (Int32, CFArray, UInt64) -> Void
    private typealias CopyManagedDisplaySpaces = @convention(c) (Int32) -> CFArray?
    // The older pair. A DIFFERENT MECHANISM, not a synonym: these add and
    // remove Space membership rather than asking the window server to perform a
    // move. Tried because "the symbol resolves and the call does nothing" is a
    // statement about ONE call, and concluding the whole capability is gone
    // from one experiment is the reasoning this session has already been wrong
    // with twice.
    // MOVING A WINDOW'S POSITION WITHOUT THE ACCESSIBILITY TREE.
    //
    // MEASURED 2026-09-11, and it is the finding that shapes cross-Desktop work:
    // the accessibility tree reached 2 windows on the showing Desktop and 0 of 69
    // on the others. So the tree cannot move a window that is not on screen, and
    // the owner has asked for exactly that -- "vesper should be able to open and
    // fully manage all windows in any other desktop if it was requested to do
    // it."
    //
    // `CGSMoveWindow` takes a window id and a point. It is the window server's
    // own call, so it does not care which Space the window is on and nothing has
    // to be brought over to be touched. `CGSSetWindowBounds` is NOT on this node
    // (probed the same day), which is why this buys POSITION and not size.
    private typealias MoveWindow = @convention(c) (Int32, Int32, UnsafePointer<CGPoint>) -> Int32
    private typealias AddWindowsToSpaces = @convention(c) (Int32, CFArray, CFArray) -> Void
    private typealias RemoveWindowsFromSpaces = @convention(c) (Int32, CFArray, CFArray) -> Void

    /// Every symbol the hatch needs, named so the alarm can say which is gone.
    static let required = ["CGSMainConnectionID", "CGSCopySpacesForWindows",
                           "CGSMoveWindowsToManagedSpace",
                           "CGSCopyManagedDisplaySpaces",
                           // Added 2026-09-11. Not optional: without it a window
                           // on another Desktop cannot be moved at all, which is
                           // the thing the owner asked for.
                           "CGSMoveWindow"]

    private static var handles: [UnsafeMutableRawPointer] = {
        frameworks.compactMap { dlopen($0, RTLD_LAZY) }
    }()

    private static func symbol(_ name: String) -> UnsafeMutableRawPointer? {
        for h in handles {
            if let s = dlsym(h, name) { return s }
        }
        return nil
    }

    // MARK: - The alarm

    enum Verdict {
        case present
        case missing([String])
        case ineffective          // symbols resolve; the call does nothing
        case noFramework

        var line: String {
            switch self {
            case .present:
                // DELIBERATELY NARROW WORDING. Measured 2026-09-08 on this
                // host: VESPER's own probe window relocated correctly ("was
                // unknown, asked for 3, is 3") while a foreign application's
                // window did not move for either mechanism. So a green here
                // means VESPER can place ITS OWN windows on any Desktop -- it
                // is not a claim about anybody else's, and writing it as one
                // would put the overclaim in the one place everyone reads.
                return "spaces hatch: \(required.count) symbols resolve and "
                     + "VESPER's own windows relocate. Foreign windows are the "
                     + "rebuild fallback's job."
            case .missing(let names):
                return "spaces hatch: MISSING \(names.joined(separator: ", ")) -- "
                     + "cross-Desktop window moves are UNAVAILABLE on this macOS. "
                     + "This is the silent-failure mode the exception was granted "
                     + "against; it is being reported instead."
            case .ineffective:
                return "spaces hatch: every symbol resolves and the call HAS NO "
                     + "EFFECT -- a probe window was asked to change Desktop and "
                     + "did not move. Cross-Desktop relocation is UNAVAILABLE on "
                     + "this macOS and the rebuild fallback is the only route."
            case .noFramework:
                return "spaces hatch: neither SkyLight nor CoreGraphics could be "
                     + "opened -- cross-Desktop window moves are UNAVAILABLE"
            }
        }
        var usable: Bool { if case .present = self { return true }; return false }
    }

    /// Resolve every symbol and say so. THE WHOLE POINT OF THE EXCEPTION.
    ///
    /// A private symbol that disappears in a macOS point release does not
    /// crash and does not warn -- the call simply does nothing, and a window
    /// that did not move looks exactly like a window that did not need to. This
    /// is checked at startup and again before every relocation, because "it
    /// worked when the app launched" is not a statement about now.
    ///
    /// `withhold` is the NEGATIVE CONTROL. A verifier that cannot go red has
    /// never proven anything, and this tree's rule is that a negative control
    /// which passes is a defect rather than a relief.
    static func verify(withhold: Bool = false) -> Verdict {
        if handles.isEmpty { return .noFramework }
        var missing: [String] = []
        for name in required {
            if withhold && name == "CGSMoveWindowsToManagedSpace" {
                missing.append(name)
                continue
            }
            if symbol(name) == nil { missing.append(name) }
        }
        return missing.isEmpty ? .present : .missing(missing)
    }

    /// Does the call actually DO anything? Asked with a probe window of our own.
    ///
    /// RESOLVING IS NOT WORKING, AND THAT DISTINCTION IS THE WHOLE EXCEPTION.
    /// `verify()` above only asks whether the symbols are there. Measured on
    /// this host 2026-09-08: all four resolve, and BOTH mechanisms --
    /// `CGSMoveWindowsToManagedSpace` and the older
    /// `CGSAddWindowsToSpaces`/`CGSRemoveWindowsFromSpaces` pair -- leave the
    /// window exactly where it was. `before_space` and `after_space` both read
    /// 1 for every managed Space requested.
    ///
    /// A symbol-presence alarm would have called that GREEN and the feature
    /// would have been silently dead -- which is the precise failure the owner
    /// was asked to accept a risk on, arriving immediately rather than after
    /// some future update. So the alarm moves a window of VESPER'S OWN and
    /// reads it back.
    ///
    /// THE PROBE IS VESPER'S, NEVER THE OWNER'S. It creates a 1x1 `.managed`
    /// window, tries to relocate it, and closes it. Nothing the owner can see
    /// moves, and an instrument that disturbed the owner's session to find out
    /// whether it could disturb the owner's session would be its own argument
    /// against running.
    /// What the probe actually observed, so a verdict can be believed.
    ///
    /// EVERY EARLY RETURN IN A PROBE IS A GREEN NOBODY EARNED. The first
    /// version had four of them -- no second Desktop, no anchor, no window
    /// number, no other Space -- and each returned `.present`, meaning "I could
    /// not test this" was reported as "this works". That is the same shape as a
    /// negative control that passes, and it hid the fact that the probe had not
    /// run at all.
    static var probeReport = "not run"

    static func effective() -> Verdict {
        let base = verify()
        guard base.usable else { probeReport = "symbols missing"; return base }
        let targets = desktops()
        guard targets.count >= 2 else {
            probeReport = "only \(targets.count) Desktop(s) -- UNTESTED, not proven"
            return .present
        }
        let anchor = SpaceWatch.Anchor()
        defer { anchor.close() }
        guard let num = anchor.windowNumber else {
            probeReport = "the probe window has no number -- UNTESTED, not proven"
            return .present
        }
        let here = spaces(of: [num])[num]
        guard let elsewhere = targets.first(where: { $0 != here }) else {
            probeReport = "no Desktop to move to -- UNTESTED, not proven"
            return .present
        }
        _ = relocate(windowId: num, to: elsewhere, probing: true)
        let after = spaces(of: [num])[num]
        let landed = after == elsewhere
        probeReport = "probe window \(num): was "
            + (here.map(String.init) ?? "unknown") + ", asked for \(elsewhere), is "
            + (after.map(String.init) ?? "unknown")
        return landed ? .present : .ineffective
    }

    // MARK: - Reading

    /// Which Space each window is on -- the thing no public call answers.
    static func spaces(of windowIds: [Int]) -> [Int: UInt64] {
        guard verify().usable,
              let cidSym = symbol("CGSMainConnectionID"),
              let copySym = symbol("CGSCopySpacesForWindows") else { return [:] }
        let cid = unsafeBitCast(cidSym, to: MainConnectionID.self)()
        let copy = unsafeBitCast(copySym, to: CopySpacesForWindows.self)
        var out: [Int: UInt64] = [:]
        for wid in windowIds {
            let arr = [wid] as CFArray
            // 0x7 asks for every Space kind rather than only the visible one,
            // which is the whole reason this call is needed.
            guard let spaces = copy(cid, 0x7, arr) as? [NSNumber],
                  let first = spaces.first else { continue }
            out[wid] = first.uint64Value
        }
        return out
    }

    /// Every managed Space, in display order, so a Desktop has a stable name.
    ///
    /// THIS ALSO REPLACES A WEAK IDENTITY. Without it a Desktop was named by a
    /// fingerprint of the window numbers on it, which changes whenever any
    /// window opens or closes -- usable for "did the Space switch", useless as
    /// an identity to move a window TO.
    static func desktops() -> [UInt64] {
        guard verify().usable,
              let cidSym = symbol("CGSMainConnectionID"),
              let listSym = symbol("CGSCopyManagedDisplaySpaces") else { return [] }
        let cid = unsafeBitCast(cidSym, to: MainConnectionID.self)()
        let list = unsafeBitCast(listSym, to: CopyManagedDisplaySpaces.self)
        guard let displays = list(cid) as? [[String: Any]] else { return [] }
        var ids: [UInt64] = []
        for d in displays {
            guard let spaces = d["Spaces"] as? [[String: Any]] else { continue }
            for s in spaces {
                if let n = s["ManagedSpaceID"] as? NSNumber { ids.append(n.uint64Value) }
            }
        }
        return ids
    }

    // MARK: - Acting

    /// Move a window to a Space. Returns what was OBSERVED afterwards.
    ///
    /// RE-READ, ALWAYS. `CGSMoveWindowsToManagedSpace` returns void: it cannot
    /// tell anyone whether it worked, which is exactly the silence this hatch
    /// was granted against. So the only honest report is to ask again where the
    /// window is and compare. A move that quietly did nothing and a move that
    /// worked are otherwise indistinguishable -- and after a macOS update the
    /// first becomes the normal case.
    /// Move a window to a point, on whatever Desktop it is on.
    ///
    /// RE-READ, ALWAYS, like `relocate` below and for the same reason: the call
    /// returns a status about the REQUEST, and "the symbol resolved and the call
    /// did nothing" has already happened twice in this file's history. The bounds
    /// are read back afterwards and the caller is told what actually moved.
    ///
    /// NOT A SUBSTITUTE FOR THE ACCESSIBILITY PATH ON THE SHOWING DESKTOP. That
    /// one goes through the application, so the app knows its window moved and
    /// can lay out accordingly. This reaches past the app to the window server,
    /// which is why it is the FALLBACK and not the default -- it is the only
    /// thing that works when the tree cannot see the window at all.
    static func moveWindow(windowId: Int, to point: CGPoint) -> [String: Any] {
        guard let cidSym = symbol("CGSMainConnectionID"),
              let moveSym = symbol("CGSMoveWindow") else {
            return ["ok": false,
                    "reason": "this node has no CGSMoveWindow, so a window on "
                            + "another desktop cannot be moved at all"]
        }
        let before = bounds(of: windowId)
        let cid = unsafeBitCast(cidSym, to: MainConnectionID.self)()
        let move = unsafeBitCast(moveSym, to: MoveWindow.self)
        var p = point
        let err = withUnsafePointer(to: &p) { move(cid, Int32(windowId), $0) }
        // SETTLE, THEN READ. The window server answers asynchronously; reading
        // immediately reports the old rectangle and looks like a silent failure.
        usleep(120_000)
        let after = bounds(of: windowId)
        let moved = after != nil && after != before
        var out: [String: Any] = ["ok": moved, "cgs_error": Int(err)]
        if let b = after {
            out["x"] = Int(b.origin.x); out["y"] = Int(b.origin.y)
            out["w"] = Int(b.size.width); out["h"] = Int(b.size.height)
        }
        if !moved {
            out["reason"] = "CGSMoveWindow returned \(err) and the window's "
                          + "rectangle did not change"
        }
        return out
    }

    /// Where the window server says a window is. Works off the showing Desktop.
    static func bounds(of windowId: Int) -> CGRect? {
        guard let info = CGWindowListCopyWindowInfo(
                [.optionIncludingWindow], CGWindowID(windowId)) as? [[String: Any]],
              let first = info.first,
              let d = first["kCGWindowBounds"] as? [String: Any],
              let x = d["X"] as? CGFloat, let y = d["Y"] as? CGFloat,
              let w = d["Width"] as? CGFloat, let h = d["Height"] as? CGFloat
        else { return nil }
        return CGRect(x: x, y: y, width: w, height: h)
    }

    static func relocate(windowId: Int, to space: UInt64,
                         probing: Bool = false) -> [String: Any] {
        // THE PROBE MUST NOT ASK THE ALARM THAT CALLS THE PROBE. `effective()`
        // reaches this function, so consulting it here would recurse forever.
        let v = probing ? verify() : effective()
        guard v.usable else { return ["ok": false, "reason": v.line] }
        guard let cidSym = symbol("CGSMainConnectionID"),
              let moveSym = symbol("CGSMoveWindowsToManagedSpace") else {
            return ["ok": false, "reason": "the move symbol vanished between the "
                  + "alarm and the call"]
        }
        let before = spaces(of: [windowId])[windowId]
        let cid = unsafeBitCast(cidSym, to: MainConnectionID.self)()
        let move = unsafeBitCast(moveSym, to: MoveWindowsToManagedSpace.self)
        move(cid, [windowId] as CFArray, space)
        var after = spaces(of: [windowId])[windowId]
        // SECOND MECHANISM, only if the first silently did nothing. Measured
        // 2026-09-08 on this host: `CGSMoveWindowsToManagedSpace` resolves and
        // has no effect -- `before_space` and `after_space` both read 1 for
        // every managed Space requested. That is precisely the silence this
        // hatch was granted against, caught by the readback rather than by a
        // crash, and it is why the fallback below exists at all.
        if after != space,
           let addSym = symbol("CGSAddWindowsToSpaces"),
           let remSym = symbol("CGSRemoveWindowsFromSpaces"),
           let from = before {
            let add = unsafeBitCast(addSym, to: AddWindowsToSpaces.self)
            let rem = unsafeBitCast(remSym, to: RemoveWindowsFromSpaces.self)
            add(cid, [windowId] as CFArray, [space] as CFArray)
            rem(cid, [windowId] as CFArray, [from] as CFArray)
            after = spaces(of: [windowId])[windowId]
        }
        let landed = (after == space)
        return ["ok": landed,
                "before_space": before.map(String.init) ?? "unknown",
                "after_space": after.map(String.init) ?? "unknown",
                "requested_space": String(space),
                "reason": landed ? "" :
                    "the window did not arrive on the requested Desktop. The "
                  + "private call reports nothing, so this is read back rather "
                  + "than assumed -- either the Space id is not a managed "
                  + "Desktop, or this macOS no longer honours the call."]
    }
}
