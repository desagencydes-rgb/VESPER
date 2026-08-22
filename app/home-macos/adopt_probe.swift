// VESPER — Desktop adoption probe. F1c, and it exists because F1b passed while
// showing the wrong answer.
//
// THE GAP. residency_probe returned a clean PASS -- 151 samples, ground off in
// 54 and back in 97, switch independently evidenced -- and the owner then said
// the purple ground had appeared on Desktop 1, not Desktop 2. Both are true.
// The foreign counts correlate perfectly, 151 of 151: ground ON only where 2
// foreign windows were, OFF where 0 were. The ground took a Desktop and held
// it. It just took the wrong one.
//
// The cause is not a bug, it is the mechanism: A WINDOW IS BORN ON THE SPACE
// THAT IS ACTIVE WHEN IT IS ORDERED FRONT, and §2.1 already established there
// is no public API to name a Space, so there is none to open a window on one
// either. That is not a probe problem. It is the home's launch problem, every
// launch: if VESPER starts at login while Desktop 1 is showing, the ground is
// born on Desktop 1 and `.managed` faithfully keeps it there.
//
// WHAT MIGHT ANSWER IT. NSWindowCollectionBehavior has `.moveToActiveSpace`,
// and it is public. §2.4 declared `relocate_window` UNAVAILABLE for FOREIGN
// windows and that stands -- this is a different claim, about our own window,
// and it has to be checked rather than assumed, because "documented" is where
// this build step has been wrong four times already.
//
// The three outcomes this probe must be able to tell apart, and only one of
// them is the good one:
//
//   the ground appears, and the foreign windows are the NEW Desktop's
//        -> the window moved to us. This is what we want.
//   the ground appears, and the foreign windows are the OLD Desktop's
//        -> macOS switched the SPACE back to the window instead of moving the
//           window. That is the opposite of the desired behaviour and would be
//           read as success by anything that only checked "is it on screen".
//   the ground does not appear
//        -> nothing happened.
//
// The middle one is why this probe reads the foreign window set and not just
// its own visibility.

import AppKit

struct Seen { let layer: Int; let number: Int; let pid: Int }

func onScreen() -> [Seen] {
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
            as? [[String: Any]] else { return [] }
    return raw.compactMap { w in
        guard let n = w[kCGWindowNumber as String] as? Int,
              let l = w[kCGWindowLayer as String] as? Int,
              let p = w[kCGWindowOwnerPID as String] as? Int else { return nil }
        return Seen(layer: l, number: n, pid: p)
    }
}

let me = Int(ProcessInfo.processInfo.processIdentifier)
let LOG = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent().appendingPathComponent("f1c_last_run.log").path
var logBuf = ""
func say(_ l: String = "") {
    print(l); logBuf += l + "\n"
    try? logBuf.write(toFile: LOG, atomically: true, encoding: .utf8)
}

var failures = 0, undecided = 0
func check(_ n: String, _ ok: Bool, _ d: String) {
    say(ok ? "  PASS  \(n)  —  \(d)" : "  FAIL  \(n)  —  \(d)"); if !ok { failures += 1 }
}
func open_(_ n: String, _ d: String) { say("  ????  \(n)  —  \(d)"); undecided += 1 }

func foreignSet() -> Set<Int> {
    Set(onScreen().filter { $0.pid != me && $0.layer == 0 }.map(\.number))
}
func groundVisible(_ w: NSWindow) -> Bool {
    onScreen().contains { $0.pid == me && $0.number == w.windowNumber }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)   // never activate: activating can pull the
                                      // Space to us, which is the confound
guard let screen = NSScreen.main else { fatalError("no main screen") }

let ground = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                      backing: .buffered, defer: false)
ground.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
ground.collectionBehavior = [.managed]
ground.animationBehavior = .none
ground.isOpaque = false
ground.backgroundColor = NSColor(calibratedRed: 0.11, green: 0.07, blue: 0.16, alpha: 0.92)
let note = NSTextField(labelWithString: "VESPER ground — born on the wrong Desktop, on purpose.")
note.font = .systemFont(ofSize: 22, weight: .light)
note.textColor = NSColor(calibratedRed: 1, green: 0.72, blue: 0.60, alpha: 1)
note.alignment = .center
note.frame = NSRect(x: 0, y: screen.frame.height * 0.4, width: screen.frame.width, height: 40)
ground.contentView?.addSubview(note)

var homeForeign: Set<Int> = []      // the Desktop it was born on
var targetForeign: Set<Int> = []    // the Desktop we want it to move to

say("""

  VESPER — Desktop adoption probe (F1c)
  ══════════════════════════════════════════════════════════════════

  This one deliberately creates the ground on the WRONG Desktop —
  the one you are on right now — and then tries to make it move to
  the one you want, using public API only.

  Just follow the prompts. Two switches, that is all.

""")

// ---------------------------------------------------------------------------
// Small step runner: do a thing, then wait until the world agrees, or give up.
// Every wait here is a poll rather than a sleep, for the reason F1 spent four
// red runs learning: a delay is a guess about the world, a poll is a reading.
// ---------------------------------------------------------------------------
func waitUntil(_ what: String, timeout: Double,
               _ cond: @escaping () -> Bool, _ then: @escaping (Bool) -> Void) {
    let deadline = Date().addingTimeInterval(timeout)
    func poll() {
        if cond() { then(true) }
        else if Date() >= deadline { say("  (timed out waiting for \(what))"); then(false) }
        else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { poll() } }
    }
    poll()
}

DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
    ground.orderFrontRegardless()
    waitUntil("the ground to be composited", timeout: 6.0, { groundVisible(ground) }) { ok in
        guard ok else { open_("adopt/created", "the ground never appeared at all"); finish(); return }
        homeForeign = foreignSet()
        say("  ✓ ground created on THIS Desktop (\(homeForeign.count) foreign windows here)")
        say("")
        say("  ▸ NOW: switch to VESPER's Desktop (Ctrl+→ or Ctrl+2) and WAIT there.")

        // "The owner switched" is not "the ground went off screen for one
        // sample" -- F1b was fooled by exactly that. Off, and stayed off.
        var offStreak = 0
        waitUntil("you to switch Desktops", timeout: 60.0, {
            offStreak = groundVisible(ground) ? 0 : offStreak + 1
            return offStreak >= 8            // 8 x 0.2 s = 1.6 s
        }) { switched in
            guard switched else { open_("adopt/switched", "no Desktop switch was seen in 60 s"); finish(); return }
            targetForeign = foreignSet()
            say("  ✓ you are on a different Desktop now (\(targetForeign.count) foreign windows here)")
            phase1()
        }
    }
}

// --- phase 1: the negative control ----------------------------------------
// Plain orderFrontRegardless with [.managed] still set. If this ALONE brings
// the ground here, `.moveToActiveSpace` is not the mechanism and phase 2 would
// have taken credit for something that happens anyway.
func phase1() {
    say("")
    say("  phase 1 — orderFrontRegardless() with [.managed], the control")
    ground.orderFrontRegardless()
    waitUntil("a reaction", timeout: 3.0, { groundVisible(ground) }) { appeared in
        let now = foreignSet()
        if !appeared {
            check("adopt/control-does-nothing", true,
                  "a `.managed` window on another Desktop stayed there when ordered front — so anything phase 2 achieves is phase 2's doing")
        } else if now == homeForeign {
            check("adopt/control-does-nothing", false,
                  "the ground appeared, but the foreign windows are the ORIGINAL Desktop's — macOS switched the SPACE back to the window instead of moving the window. Ordering the ground front YANKS THE OWNER to another Desktop, which is worse than doing nothing")
        } else {
            check("adopt/control-does-nothing", false,
                  "plain orderFrontRegardless moved a `.managed` window across Desktops on its own — phase 2 cannot claim credit, and `.managed` is weaker than §2.2 assumes")
        }
        phase2()
    }
}

// --- phase 2: the mechanism ------------------------------------------------
func phase2() {
    say("")
    say("  phase 2 — collectionBehavior = [.moveToActiveSpace], then order front")
    ground.collectionBehavior = [.moveToActiveSpace]
    ground.orderFrontRegardless()
    waitUntil("the ground to arrive", timeout: 4.0, { groundVisible(ground) }) { appeared in
        let now = foreignSet()
        if !appeared {
            check("adopt/moves-to-us", false,
                  "`.moveToActiveSpace` did not bring the ground to this Desktop. The home cannot correct its own residency and onboarding must guarantee the launch Desktop instead")
        } else if now == homeForeign && homeForeign != targetForeign {
            check("adopt/moves-to-us", false,
                  "the ground is on screen but the foreign windows are the ORIGINAL Desktop's — the SPACE moved to the window, not the window to the Space. On a real machine that drags the owner out of the room they were in")
        } else {
            check("adopt/moves-to-us", true,
                  "the ground arrived on the Desktop the owner was already on, and the foreign windows are still this Desktop's — the window moved, the owner did not")
        }
        phase3()
    }
}

// --- phase 3: did it ADOPT the new Desktop, or become a follower? ----------
// `.moveToActiveSpace` left in place would make the ground follow the owner
// everywhere, which is exactly what §2.2 says the home must not do. Restoring
// `.managed` should re-pin it -- here.
func phase3() {
    ground.collectionBehavior = [.managed]
    say("")
    say("  phase 3 — [.managed] restored. Is it pinned HERE now, or following you?")
    say("  ▸ NOW: switch back to your other Desktop and wait a moment.")
    var offStreak = 0
    waitUntil("you to switch away again", timeout: 60.0, {
        offStreak = groundVisible(ground) ? 0 : offStreak + 1
        return offStreak >= 8
    }) { gone in
        if gone {
            check("adopt/re-pinned", true,
                  "after `.managed` was restored the ground stayed behind on its new Desktop — it adopted the room rather than following the owner")
        } else {
            check("adopt/re-pinned", false,
                  "the ground was still on screen after the switch — restoring `.managed` did not re-pin it, so a moved window keeps following and the home would appear on every Desktop")
        }
        finish()
    }
}

func finish() {
    say("")
    say(String(repeating: "═", count: 70))
    if failures == 0 && undecided == 0 { say("  F1c DESKTOP ADOPTION: PASS — the home can correct its own residency") }
    else if failures == 0 { say("  F1c DESKTOP ADOPTION: INCONCLUSIVE (\(undecided))") }
    else { say("  F1c DESKTOP ADOPTION: FAIL (\(failures)) — onboarding must guarantee the launch Desktop") }
    say(String(repeating: "═", count: 70))
    say("  log: \(LOG)")
    exit(failures == 0 && undecided == 0 ? 0 : 1)
}

app.run()
