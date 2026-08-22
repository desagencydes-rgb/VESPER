// VESPER — Desktop residency probe. The second half of build step F1.
//
// ground_probe.swift settled the z-order law: level normal-1 cannot rise above
// a foreign normal window, and a negative control at level 0 can. That is one
// of the two things F1 owes. The other is residency:
//
//   HOME-ARCHITECTURE.md §2.2 — "`Managed` keeps it on one Desktop,
//   participating in Mission Control like anything else."
//
// WHY THIS ONE NEEDS A HAND ON THE KEYBOARD. §2.1 checked and there is no
// public API to create, name or enumerate a Space, which means there is also no
// public way to ASK which Space a window is on. The absence is not an obstacle
// here -- it is the instrument. CGWindowList's .optionOnScreenOnly returns only
// what is on the ACTIVE Space, so "the ground vanished from the list while the
// process is still running" is exactly the reading "the ground stayed behind on
// its own Desktop". Nothing else has to be asked.
//
// So the probe cannot switch Spaces (that would need the CGEvent path and a
// Keyboard shortcut that may not be enabled yet). The owner switches; the probe
// reads. An owner-driven test is honest for a mechanism that is owner-driven.

import AppKit

struct Seen { let owner: String; let layer: Int; let number: Int; let pid: Int }

func onScreen() -> [Seen] {
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
            as? [[String: Any]] else { return [] }
    return raw.compactMap { w in
        guard let n = w[kCGWindowNumber as String] as? Int,
              let l = w[kCGWindowLayer as String] as? Int,
              let p = w[kCGWindowOwnerPID as String] as? Int else { return nil }
        return Seen(owner: (w[kCGWindowOwnerName as String] as? String) ?? "?",
                    layer: l, number: n, pid: p)
    }
}

let me = Int(ProcessInfo.processInfo.processIdentifier)
let app = NSApplication.shared
// .accessory, not .regular, and NOTHING here calls NSApp.activate. Activating
// would let macOS pull the active Space back to wherever this app already has a
// window -- which is the very thing being measured. The probe must not be able
// to move the thing it is reading.
app.setActivationPolicy(.accessory)

guard let screen = NSScreen.main else { fatalError("no main screen") }

// The ground: exactly what §2.2 specifies. Managed, below normal, full frame.
let ground = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                      backing: .buffered, defer: false)
ground.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
ground.collectionBehavior = [.managed]
ground.animationBehavior = .none
ground.isOpaque = false
ground.backgroundColor = NSColor(calibratedRed: 0.11, green: 0.07, blue: 0.16, alpha: 0.90)

let note = NSTextField(labelWithString: "VESPER ground — this must stay on this Desktop.\nSwitch away and it should disappear. The pill above should not.")
note.font = .systemFont(ofSize: 22, weight: .light)
note.textColor = NSColor(calibratedRed: 1, green: 0.72, blue: 0.60, alpha: 1)
note.alignment = .center
note.frame = NSRect(x: 0, y: screen.frame.height * 0.4, width: screen.frame.width, height: 70)
ground.contentView?.addSubview(note)

// The negative control, and it is the island's own collection behaviour rather
// than an invented one: [.canJoinAllSpaces, .stationary]. If BOTH windows
// vanish on a Space switch, the probe has measured the app going away and would
// have reported the ground's residency as a pass for the wrong reason.
let pill = NSPanel(contentRect: NSRect(x: screen.frame.midX - 140,
                                       y: screen.frame.maxY - 90, width: 280, height: 44),
                   styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
pill.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.statusWindow)) + 1)
pill.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
pill.animationBehavior = .none
pill.isOpaque = false
pill.backgroundColor = .clear
pill.hasShadow = false
let pv = NSView(frame: pill.contentView!.bounds)
pv.wantsLayer = true
pv.layer?.backgroundColor = NSColor(calibratedRed: 0.04, green: 0.03, blue: 0.06, alpha: 0.96).cgColor
pv.layer?.cornerRadius = 22
let pl = NSTextField(labelWithString: "follows you everywhere")
pl.font = .systemFont(ofSize: 13, weight: .medium)
pl.textColor = NSColor(calibratedRed: 1, green: 0.72, blue: 0.60, alpha: 1)
pl.alignment = .center
pl.frame = NSRect(x: 0, y: 13, width: 280, height: 18)
pv.addSubview(pl)
pill.contentView = pv

// ---------------------------------------------------------------------------

let LEAD = 12.0          // seconds before the windows are created
let RUN  = 45.0          // seconds of sampling
var samples: [(t: Double, ground: Bool, pill: Bool, foreign: Int)] = []
var t0 = Date()

print("""

  VESPER — Desktop residency probe (F1b)
  ══════════════════════════════════════════════════════════════════

  1.  You have \(Int(LEAD)) seconds. SWITCH TO VESPER'S DESKTOP NOW
      (Ctrl+→, or Mission Control and click it).
      The ground is created wherever you are when the countdown ends,
      and that Desktop becomes the one it is supposed to stay on.

  2.  Then, for \(Int(RUN)) seconds: switch AWAY and BACK a few times.

  What should happen, and what the probe is watching for:
      the dark ground  — disappears when you leave, returns when you come back
      the small pill   — stays on screen the whole time, every Desktop

""")

func tick() {
    let dt = Date().timeIntervalSince(t0)
    if dt >= LEAD { return }
    print("  starting in \(Int(LEAD - dt))s …")
    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { tick() }
}
tick()

DispatchQueue.main.asyncAfter(deadline: .now() + LEAD) {
    // orderFrontRegardless, never activate: see the policy note above.
    ground.orderFrontRegardless()
    pill.orderFrontRegardless()
    print("\n  windows created. Switch Desktops now.\n")
    t0 = Date()

    func sample() {
        let dt = Date().timeIntervalSince(t0)
        let all = onScreen()
        let nums = Set(all.filter { $0.pid == me }.map(\.number))
        let g = nums.contains(ground.windowNumber)
        let p = nums.contains(pill.windowNumber)
        let foreign = all.filter { $0.pid != me && $0.layer == 0 }.count
        samples.append((dt, g, p, foreign))
        print(String(format: "  %5.1fs   ground %@   pill %@   foreign layer-0 windows: %d",
                     dt, g ? "ON " : "off", p ? "ON " : "off", foreign))
        if dt < RUN { DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { sample() } }
        else { verdict() }
    }
    sample()
}

func verdict() {
    var failures = 0, undecided = 0
    func check(_ n: String, _ ok: Bool, _ d: String) {
        print(ok ? "  PASS  \(n)  —  \(d)" : "  FAIL  \(n)  —  \(d)"); if !ok { failures += 1 }
    }
    func open(_ n: String, _ d: String) { print("  ????  \(n)  —  \(d)"); undecided += 1 }

    let present = samples.filter(\.ground).count
    let absent  = samples.filter { !$0.ground }.count
    let pillOn  = samples.filter(\.pill).count

    print("\n" + String(repeating: "─", count: 70))
    print("  \(samples.count) samples — ground on screen in \(present), off in \(absent); pill on in \(pillOn)")

    if absent == 0 {
        open("residency/left-the-desktop",
             "the ground was never off screen, so no Space switch was observed. Nothing is proven — re-run and switch away.")
        open("residency/pill-follows", "same reason: no switch to follow.")
    } else if present == 0 {
        open("residency/came-back",
             "the ground was never on screen at all — it may have been created on a Desktop you then left and never returned to.")
    } else {
        check("residency/managed-stays-put", absent > 0 && present > 0,
              "off screen in \(absent) samples and back in \(present) — a `.managed` window at level normal-1 belongs to ONE Desktop")
        // The negative control. Its whole job is to be ON in the samples where
        // the ground is OFF. If it is not, both windows simply went away and the
        // line above measured nothing.
        let awaySamples = samples.filter { !$0.ground }
        let pillHeld = awaySamples.allSatisfy(\.pill)
        check("residency/pill-follows", pillHeld,
              pillHeld ? "in all \(awaySamples.count) samples where the ground was gone, the .canJoinAllSpaces pill was still there — so the ground's absence is residency, not the app disappearing"
                       : "the pill vanished too, in \(awaySamples.filter { !$0.pill }.count) of \(awaySamples.count) samples. This test measured nothing about residency.")
    }

    print(String(repeating: "═", count: 70))
    if failures == 0 && undecided == 0 { print("  F1b DESKTOP RESIDENCY: PASS") }
    else if failures == 0 { print("  F1b DESKTOP RESIDENCY: INCONCLUSIVE (\(undecided)) — not a pass.") }
    else { print("  F1b DESKTOP RESIDENCY: FAIL (\(failures))") }
    print(String(repeating: "═", count: 70) + "\n")
    exit(failures == 0 && undecided == 0 ? 0 : 1)
}

app.run()
