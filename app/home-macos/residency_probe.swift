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
// --negative is the mandatory red run. The repo's rule is that a negative
// control which passes is a defect, not a relief: if this probe cannot be made
// to FAIL, its PASS is not evidence that `.managed` pins anything — it may
// simply be evidence that the probe reports PASS. So `--negative` gives the
// ground the ISLAND's collection behaviour instead of its own. A
// .canJoinAllSpaces ground follows you to every Desktop, is therefore never
// absent, and must be reported as `residency/managed-stays-put FAIL — it
// followed`. Run it once and watch it go red; then the green run means
// something.
ground.collectionBehavior = CommandLine.arguments.contains("--negative")
    ? [.canJoinAllSpaces, .stationary]
    : [.managed]
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

// --selftest runs the whole path with nobody switching Desktops. It is not a
// residency test and cannot pass: it exists to prove the run completes and that
// the no-switch path reports INCONCLUSIVE rather than PASS. An instrument that
// cannot be caught being vacuous is not an instrument.
let SELFTEST = CommandLine.arguments.contains("--selftest")
let LEAD = SELFTEST ? 1.0 : 10.0    // seconds before the windows are created
let RUN  = SELFTEST ? 8.0 : 40.0    // seconds of sampling
// 250 ms, not 1 s. At one sample a second a Space transition is aliased away
// entirely -- it happens between two samples and is invisible, so a sample that
// lands inside one is indistinguishable from a sample that did not. At 250 ms
// the transition is several samples wide and can be identified and excluded
// instead of guessed at. This is the ground probe's lesson carried over: the
// first three runs of that probe all failed because something was read while it
// was still moving.
let PERIOD = 0.25
// The foreign window NUMBERS, not a count. A count cannot tell "you switched
// Desktops" from "one window closed", and the verdict below needs to know
// whether a switch happened INDEPENDENTLY of our own windows -- see the note
// on the three-way verdict.
var samples: [(t: Double, ground: Bool, pill: Bool, foreign: Set<Int>)] = []
var t0 = Date()

// Everything printed also lands in a file, so the run can be read after the
// fact instead of being retyped out of a terminal.
// Next to the binary, not next to wherever you happened to be standing. The
// owner's PASS run wrote to the repo root and the self-test wrote to
// app/home-macos/, which is two logs with one name and no way to tell them apart.
let LOG = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent().appendingPathComponent("f1b_last_run.log").path
var logBuf = ""
func say(_ line: String = "") {
    print(line)
    logBuf += line + "\n"
    try? logBuf.write(toFile: LOG, atomically: true, encoding: .utf8)
}

say("""
  VESPER — Desktop residency probe (F1b)\(CommandLine.arguments.contains("--negative") ? "   [NEGATIVE CONTROL — this run MUST fail]" : "")
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

    // Do not start the clock until the window server can actually SEE both
    // windows. `orderFrontRegardless` returning is not a window appearing — the
    // same distinction the repo states as "a launcher returning 0 is not a
    // running process". Sampling from the instant of the call put the first
    // sample BEFORE compositing, where both windows read `off`, and that single
    // sample is the entire "the pill vanished in 1 of 24" failure.
    func startWhenVisible(_ attemptsLeft: Int) {
        let nums = Set(onScreen().filter { $0.pid == me }.map(\.number))
        let ready = nums.contains(ground.windowNumber) && nums.contains(pill.windowNumber)
        if ready || attemptsLeft == 0 {
            if !ready { say("  WARNING: the windows never appeared on screen; sampling anyway") }
            say("\n  windows on screen — SWITCH DESKTOPS NOW, away and back, a few times.\n")
            t0 = Date()
            sample()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { startWhenVisible(attemptsLeft - 1) }
        }
    }

    func sample() {
        let dt = Date().timeIntervalSince(t0)
        let all = onScreen()
        let nums = Set(all.filter { $0.pid == me }.map(\.number))
        let g = nums.contains(ground.windowNumber)
        let p = nums.contains(pill.windowNumber)
        let foreign = Set(all.filter { $0.pid != me && $0.layer == 0 }.map(\.number))
        samples.append((dt, g, p, foreign))
        say(String(format: "  %5.1fs   ground %@   pill %@   foreign layer-0 windows: %d",
                   dt, g ? "ON " : "off", p ? "ON " : "off", foreign.count))
        if dt < RUN { DispatchQueue.main.asyncAfter(deadline: .now() + PERIOD) { sample() } }
        else { verdict() }
    }
    startWhenVisible(60)
}

func verdict() {
    var failures = 0, undecided = 0
    func check(_ n: String, _ ok: Bool, _ d: String) {
        say(ok ? "  PASS  \(n)  —  \(d)" : "  FAIL  \(n)  —  \(d)"); if !ok { failures += 1 }
    }
    func open(_ n: String, _ d: String) { say("  ????  \(n)  —  \(d)"); undecided += 1 }

    // ── Did a Space switch actually happen? ────────────────────────────────
    //
    // THIS IS THE FIX FOR A REAL DEFECT IN THE FIRST VERSION. It judged
    // residency from `absent == 0` alone and called that INCONCLUSIVE — "no
    // switch was observed". But `absent == 0` has TWO causes and they are
    // opposites:
    //
    //     the owner never switched          -> INCONCLUSIVE, nothing measured
    //     the ground FOLLOWED to every Desktop -> FAIL, §2.2 is wrong
    //
    // Reporting the second as the first is a negative control that passes: the
    // exact failure the repo's doctrine calls a defect rather than a relief.
    // So the switch has to be detected from something that is not our window.
    //
    // The foreign layer-0 windows are that something. Two samples taken on
    // different Desktops share few or no windows; two taken on the same Desktop
    // share nearly all of them. Jaccard over the window numbers, and two empty
    // sets count as identical rather than as a switch.
    func jaccard(_ a: Set<Int>, _ b: Set<Int>) -> Double {
        if a.isEmpty && b.isEmpty { return 1.0 }
        return Double(a.intersection(b).count) / Double(a.union(b).count)
    }
    var switched = false
    var minOverlap = 1.0
    for i in samples.indices {
        for j in samples.indices where j > i {
            let k = jaccard(samples[i].foreign, samples[j].foreign)
            minOverlap = Swift.min(minOverlap, k)
            if k < 0.5 { switched = true }
        }
    }

    let present = samples.filter(\.ground).count
    let absent  = samples.filter { !$0.ground }.count
    let pillOn  = samples.filter(\.pill).count

    say("\n" + String(repeating: "─", count: 70))
    say("  \(samples.count) samples — ground on screen in \(present), off in \(absent); pill on in \(pillOn)")
    say(String(format: "  least overlap between any two samples' foreign windows: %.2f  → Desktop switch %@",
               minOverlap, switched ? "OBSERVED" : "not observed"))

    if !switched {
        open("residency/switch-happened",
             "the set of foreign windows never changed enough to show a Desktop switch. Nothing about residency is proven either way — re-run and switch away and back.")
    } else if absent == 0 {
        // The switch is independently evidenced and the ground was on screen
        // the whole way through. It came along. That is the mechanism failing,
        // not the test being vacuous.
        check("residency/managed-stays-put", false,
              "a Desktop switch WAS observed and the ground was on screen in every one of \(samples.count) samples — it followed. `.managed` at level normal-1 did not pin it to one Desktop, and §2.2 is wrong on this machine")
    } else if present == 0 {
        open("residency/came-back",
             "the ground was never on screen — it was probably created on a Desktop that was then left and not returned to.")
    } else {
        check("residency/managed-stays-put", true,
              "switch observed; ground off screen in \(absent) samples and back in \(present) — a `.managed` window at level normal-1 belongs to ONE Desktop")
        // ── The negative control, and the second defect this probe had ──────
        //
        // Its job is to be ON in the samples where the ground is OFF; if it is
        // not, both windows simply went away and the line above measured the
        // app disappearing rather than residency.
        //
        // The first version asked `away.allSatisfy(\.pill)` — all-or-nothing
        // over every sample — and the owner's run failed it on ONE sample out
        // of 44, with the pill present in 43. That is not a reading that the
        // pill does not follow. It is the third time in this build step that
        // something was sampled while it was in motion:
        //
        //   ground probe run 1  a window read before it was composited
        //   ground probe run 2  a window read mid appearance-spring, twice
        //   this                a window read mid Space transition
        //
        // The evidence that it is an artifact and not the mechanism is a run of
        // this same probe with NOBODY SWITCHING DESKTOPS AT ALL: 36 samples, and
        // the GROUND — which could not possibly have left a Desktop nobody left —
        // still read `off` for exactly one of them. Single-sample dropouts are
        // noise in this instrument, independent of Spaces.
        //
        // So: a dropout has to LAST to be a state. The threshold barely matters
        // and that is the point — a pill that genuinely did not follow would be
        // absent for the entire time spent on the other Desktop, which is tens
        // of samples, while the artifact is one. Any threshold between 2 and 20
        // gives the same verdict, so this is not a number tuned until the test
        // went green.
        let RUNLEN = 4                       // 4 x 250 ms = 1 s
        var longestMiss = 0, current = 0
        var missRows: [Int] = []
        for (i, smp) in samples.enumerated() where !smp.ground {
            if smp.pill { current = 0 } else {
                current += 1; missRows.append(i)
                longestMiss = Swift.max(longestMiss, current)
            }
        }
        let away = samples.filter { !$0.ground }
        let misses = away.filter { !$0.pill }.count

        // Show the dropouts next to what the foreign windows were doing, so a
        // transition frame is visible as a transition rather than inferred.
        for i in missRows.prefix(8) {
            let moving = i > 0 && samples[i].foreign != samples[i - 1].foreign
            say(String(format: "        pill dropout at %5.1fs — foreign set %@ at this sample",
                       samples[i].t, moving ? "CHANGED (mid Space transition)" : "unchanged"))
        }

        let held = longestMiss < RUNLEN
        check("residency/pill-follows", held,
              held ? "the .canJoinAllSpaces pill was on screen in \(away.count - misses) of \(away.count) samples where the ground was gone; longest unbroken absence \(longestMiss) sample(s) < \(RUNLEN) — so the ground's absence is residency, not the app going away"
                   : "the pill was absent for \(longestMiss) consecutive samples (≥ \(RUNLEN)) while the ground was gone. That is long enough to be a state, not a transition frame: this run measured nothing about residency.")
    }

    say(String(repeating: "═", count: 70))
    if failures == 0 && undecided == 0 { say("  F1b DESKTOP RESIDENCY: PASS") }
    else if failures == 0 { say("  F1b DESKTOP RESIDENCY: INCONCLUSIVE (\(undecided)) — not a pass, and not a failure either") }
    else { say("  F1b DESKTOP RESIDENCY: FAIL (\(failures))") }
    say(String(repeating: "═", count: 70))
    say("  full log written to \(LOG)")
    exit(failures == 0 && undecided == 0 ? 0 : 1)
}

app.run()
