// VESPER — ground plane probe.
//
// HOME-ARCHITECTURE.md §2.2 makes one claim that the whole home rests on:
//
//   "Level `normal - 1` is the whole trick and it is one integer. A window
//    below the normal level can never rise above a normal window, even when
//    it is clicked."
//
// and then says, in the same section, that the claim is *documented, unverified
// here* -- because `Managed` is documented as the default AT `.normal`, not as
// something that survives being paired with a level below it. This file is that
// verification. It is build step F1 and nothing above it should be built until
// it has been watched.
//
// WHY A LOOSE BINARY IS ACCEPTABLE HERE, when build.sh argues at length that it
// is not. That argument is about TCC: a permission granted to a bare executable
// is granted to the terminal that launched it and does not transfer to the
// bundle later. This probe requests no permission at all -- it reads owner,
// layer, bounds and window number from CGWindowList, none of which are gated.
// It never reads kCGWindowName, which is the one field that would need Screen
// Recording. So it spends no identity, and stays a diagnostic rather than
// becoming a surface.

import AppKit

// ---------------------------------------------------------------------------
// The instrument.
//
// Not the app's own report of where it put its windows -- the window server's.
// `ground.level` only says what was ASKED for. CGWindowListCopyWindowInfo says
// what the server assigned and, in array order, front to back, where it landed
// relative to every other window on the display including other processes'.
//
// The repo's standing rule is that an instrument's self-report is not evidence.
// A window object reporting its own level is exactly that report.
// ---------------------------------------------------------------------------

struct Seen {
    let owner: String
    let layer: Int
    let bounds: CGRect
    let number: Int
    let pid: Int
    let index: Int      // 0 == frontmost
}

func onScreen() -> [Seen] {
    // No .excludeDesktopElements: the desktop picture and the icon layer are
    // part of what is being checked. The ground has to land ABOVE them and
    // BELOW normal, and a probe that filtered them out could not tell.
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
            as? [[String: Any]] else { return [] }
    return raw.enumerated().compactMap { (i, w) in
        guard let num = w[kCGWindowNumber as String] as? Int,
              let layer = w[kCGWindowLayer as String] as? Int,
              let pid = w[kCGWindowOwnerPID as String] as? Int,
              let bd = w[kCGWindowBounds as String] as? [String: Any],
              let r = CGRect(dictionaryRepresentation: bd as CFDictionary)
        else { return nil }
        let owner = (w[kCGWindowOwnerName as String] as? String) ?? "?"
        return Seen(owner: owner, layer: layer, bounds: r,
                    number: num, pid: pid, index: i)
    }
}

// ---------------------------------------------------------------------------

let me = Int(ProcessInfo.processInfo.processIdentifier)
var failures = 0
var inconclusive = 0

func check(_ name: String, _ pass: Bool, _ detail: String) {
    if pass { print("  PASS  \(name)  —  \(detail)") }
    else    { print("  FAIL  \(name)  —  \(detail)"); failures += 1 }
}
func undecided(_ name: String, _ detail: String) {
    print("  ????  \(name)  —  \(detail)"); inconclusive += 1
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)   // the home will have a Dock tile; the island does not

guard let screen = NSScreen.main else { fatalError("no main screen") }

// --- the ground -----------------------------------------------------------
// screen.frame, NOT visibleFrame: §2.2 requires it to run to y = 0 so the
// translucent menu bar sits over it and is tinted by the ambience, which is
// what the desktop picture already does on this machine.
let ground = NSWindow(contentRect: screen.frame,
                      styleMask: [.borderless],
                      backing: .buffered, defer: false)
ground.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
ground.collectionBehavior = [.managed]
ground.isOpaque = false
ground.backgroundColor = NSColor(calibratedRed: 0.11, green: 0.07, blue: 0.16, alpha: 0.92)
ground.ignoresMouseEvents = false
// The ground does not animate into existence. Two reasons, and the product one
// comes first: this window IS the desktop, and a desktop that springs in from
// 99% is imitating a dialog. DESIGN-FOUNDATION's motion vocabulary is four
// approved springs and none of them is "the room arrives".
// The measurement reason is the second run of this probe: AppKit's default
// appearance animation is itself a spring WITH BOUNCE, and it was caught at
// 1714x1107 (undershoot) and then at 1730x1117 (overshoot) on two runs. A
// settle detector that samples an oscillation can always be fooled at its
// turning point, where two consecutive reads agree and the thing is still
// moving. Removing the motion beats out-sampling it.
ground.animationBehavior = .none
ground.setFrame(screen.frame, display: true)

let label = NSTextField(labelWithString: "VESPER ground plane probe — level normal−1, managed.\nThis window must not be able to rise above anything.")
label.font = .systemFont(ofSize: 22, weight: .light)
label.textColor = NSColor(calibratedRed: 1, green: 0.72, blue: 0.60, alpha: 1)
label.alignment = .center
label.frame = NSRect(x: 0, y: screen.frame.height * 0.35,
                     width: screen.frame.width, height: 70)
ground.contentView?.addSubview(label)
ground.orderFront(nil)

// --- the negative control -------------------------------------------------
// Same app, same everything, one integer different. If the ground ends up
// behind foreign windows and this one ALSO does, the probe is not measuring
// window level -- it is measuring the app being in the background, and would
// have reported PASS for the wrong reason. A negative control that passes is
// a defect, so this one is required to *rise*.
let control = NSWindow(contentRect: NSRect(x: screen.frame.width - 460,
                                           y: screen.frame.height - 260,
                                           width: 420, height: 150),
                       styleMask: [.titled, .closable],
                       backing: .buffered, defer: false)
control.title = "negative control — level normal"
control.level = .normal
control.collectionBehavior = [.managed]
control.orderFront(nil)

// ---------------------------------------------------------------------------

func report(_ phase: String) -> [Seen] {
    let all = onScreen()
    let mine = all.filter { $0.pid == me }
    let g = mine.first { $0.number == ground.windowNumber }
    let c = mine.first { $0.number == control.windowNumber }

    print("")
    print("── \(phase) " + String(repeating: "─", count: max(0, 62 - phase.count)))
    print("  on-screen windows: \(all.count)   ours: \(mine.count)")

    // What the server says the layers are, versus what was asked for.
    if let g { print("  ground   asked \(ground.level.rawValue)  server says layer \(g.layer)  z-index \(g.index)  \(Int(g.bounds.width))x\(Int(g.bounds.height)) @ (\(Int(g.bounds.minX)),\(Int(g.bounds.minY)))") }
    else     { print("  ground   NOT ON SCREEN") }
    if let c { print("  control  asked \(control.level.rawValue)  server says layer \(c.layer)  z-index \(c.index)") }
    else     { print("  control  NOT ON SCREEN") }

    let foreign = all.filter { $0.pid != me && $0.layer == 0 && $0.bounds.width > 200 && $0.bounds.height > 100 }
    print("  foreign windows at layer 0 (real app windows): \(foreign.count)")
    for f in foreign.prefix(6) {
        print("     z\(String(format: "%3d", f.index))  \(f.owner)  \(Int(f.bounds.width))x\(Int(f.bounds.height))")
    }
    return all
}

func judge(_ all: [Seen], _ phase: String) {
    let mine = all.filter { $0.pid == me }
    guard let g = mine.first(where: { $0.number == ground.windowNumber }),
          let c = mine.first(where: { $0.number == control.windowNumber }) else {
        undecided("\(phase)/on-screen", "one of our windows is not on screen; nothing can be judged")
        return
    }
    let foreign = all.filter { $0.pid != me && $0.layer == 0 && $0.bounds.width > 200 && $0.bounds.height > 100 }

    check("\(phase)/ground-layer", g.layer == -1,
          "server assigned layer \(g.layer); asked for -1")
    check("\(phase)/control-layer", c.layer == 0,
          "server assigned layer \(c.layer); asked for 0")

    if foreign.isEmpty {
        undecided("\(phase)/below-foreign",
                  "no foreign layer-0 window is on screen, so 'nothing was above me' is vacuous — open any app window and re-run")
        undecided("\(phase)/control-rises", "same reason")
    } else {
        // z-index counts from the front, so BEHIND means a LARGER index.
        let frontmostForeign = foreign.map(\.index).min()!
        check("\(phase)/below-foreign", g.index > foreign.map(\.index).max()!,
              "ground z\(g.index) vs rearmost foreign z\(foreign.map(\.index).max()!) — ground is behind every one of \(foreign.count)")
        check("\(phase)/control-rises", c.index < frontmostForeign,
              "control z\(c.index) vs frontmost foreign z\(frontmostForeign) — a normal window CAN get in front, so the test above is measuring level and not backgrounding")
    }

    // §2.2: spans the whole frame, not visibleFrame, so the menu bar sits over it.
    let f = screen.frame
    check("\(phase)/spans-full-frame",
          abs(g.bounds.width - f.width) < 1 && abs(g.bounds.height - f.height) < 1 && abs(g.bounds.minY) < 1,
          "ground is \(Int(g.bounds.width))x\(Int(g.bounds.height)) at y=\(Int(g.bounds.minY)); screen is \(Int(f.width))x\(Int(f.height)) — y=0 means it runs under the menu bar")

    // The desktop picture must stay below us: the ground replaces the wallpaper
    // visually but must not fall behind it.
    if let deepest = all.filter({ $0.pid != me }).map(\.layer).min() {
        check("\(phase)/above-desktop", g.layer > deepest,
              "deepest foreign layer on screen is \(deepest); ground at \(g.layer) sits above it")
    }
}

// ---------------------------------------------------------------------------
// Two observations. The second one is the one that matters: it comes AFTER the
// ground has been asked, as forcefully as AppKit allows, to come to the front.
// If it still cannot, the claim in §2.2 is not a preference the server happens
// to honour -- it is a rule.
// ---------------------------------------------------------------------------

// The first observation must not be taken on a guess, and "on screen" is not
// the same condition as "settled". This probe failed twice before it measured
// anything, both times for its own reasons:
//
//   run 1, fixed 1.0 s delay  -> INCONCLUSIVE: neither window was composited
//                                yet, and "nothing of ours is on screen" is a
//                                reading about the compositor, not about level.
//   run 2, poll for presence  -> FAIL on geometry: the ground was reported as
//                                1714x1107 at (7,5), which is 99.2% of the
//                                screen, centred. That is macOS scaling the
//                                window up as it appears. The window was in
//                                the list and still in motion.
//
// So the condition is: both windows present, AND the ground's bounds identical
// across two consecutive reads. Anything less measures an animation frame and
// calls it a defect -- which is the failure the whole `INV-HW-2` posture is
// about, one level down: a number read before the thing it measures holds still.
func whenSettled(timeout: Double, _ body: @escaping (Bool) -> Void) {
    let deadline = Date().addingTimeInterval(timeout)
    var recent: [CGRect] = []
    func poll() {
        let mine = onScreen().filter { $0.pid == me }
        let g = mine.first { $0.number == ground.windowNumber }
        let haveBoth = g != nil && mine.contains { $0.number == control.windowNumber }
        if haveBoth, let now = g?.bounds {
            recent.append(now)
            if recent.count > 3 { recent.removeFirst() }
        } else {
            recent.removeAll()
        }
        // THREE identical reads, not two. Two is exactly what a spring's turning
        // point produces: velocity passes through zero and consecutive samples
        // agree while the window is still in motion. Run 3 of this probe was
        // fooled that way at the overshoot peak.
        if recent.count == 3 && recent[0] == recent[1] && recent[1] == recent[2] {
            body(true)
        } else if Date() >= deadline {
            body(false)
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { poll() }
        }
    }
    poll()
}

whenSettled(timeout: 8.0) { composited in
    if !composited {
        undecided("p0/settled",
                  "our windows never reached a stable frame within 8 s")
    }
    let a = report("phase 1 — as opened")
    judge(a, "p1")

    print("")
    print("  ↑ asking the ground to come forward: activate + makeKeyAndOrderFront + orderFrontRegardless")
    NSApp.activate(ignoringOtherApps: true)
    ground.makeKeyAndOrderFront(nil)
    ground.orderFrontRegardless()

    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
        let b = report("phase 2 — after the ground was told to rise")
        judge(b, "p2")

        print("")
        print(String(repeating: "═", count: 70))
        if failures == 0 && inconclusive == 0 {
            print("  F1 GROUND PLANE: PASS — §2.2 holds on this machine.")
        } else if failures == 0 {
            print("  F1 GROUND PLANE: INCONCLUSIVE (\(inconclusive)) — not a pass.")
        } else {
            print("  F1 GROUND PLANE: FAIL (\(failures)) — §2.2 does not hold. Do not build on it.")
        }
        print(String(repeating: "═", count: 70))
        exit(failures == 0 && inconclusive == 0 ? 0 : 1)
    }
}

app.run()
