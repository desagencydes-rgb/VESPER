// VESPER — what folding the home into the bundle actually bought, measured.
//
// TWO CLAIMS ARE BEING CHECKED, and neither is checkable by looking at code.
//
// 1. IDENTITY. "The home now runs as VESPER, not as Terminal" is the whole
//    reason for step 1, and `Bundle.main.bundleIdentifier` is this process's
//    opinion of itself. TCC does not read that -- it reads the code signature.
//    So the signing identifier is read back out of the binary with `codesign`,
//    an instrument that is not us.
//
//    What this still does NOT prove: that a permission dialog says VESPER. That
//    is observed in a dialog or not at all, and the first dialog is the
//    Accessibility grant, which this build has deliberately not asked for.
//    Recorded as unproven rather than implied.
//
// 2. §2.6's SIGNAL. "The island's visibility is the inverse of the ground's
//    occlusion state" assumes NSWindowOcclusionState changes when the owner
//    switches Desktops. It has never been measured. What HAS been measured is
//    that it changes when a window is COVERED -- and covered and elsewhere are
//    different questions that happen to share an answer's name.
//
// THE NEGATIVE CONTROL, and it is the point of the run. A second window with
// `.canJoinAllSpaces` FOLLOWS the owner to every Desktop, so its occlusion must
// NOT go dark on a switch. If both windows report occluded, this instrument is
// reporting "the app deactivated" -- true on every Space change and useless for
// residency -- and §2.6 needs a different signal. A control that passes is a
// defect, not a relief.

import AppKit

enum HomeVerify {

    /// Everything printed, kept for the log. `open -a` gives the owner no
    /// stdout at all -- launched as the app, which is the ONE launch route
    /// where the identity readout means what it says, the terminal sees
    /// nothing. A run whose output only exists in a window nobody is watching
    /// is not a run that reported anything.
    private static var lines: [String] = []
    private static func say(_ s: String = "") { print(s); lines.append(s) }

    /// Other processes running THIS executable, by RESOLVED path.
    ///
    /// `proc_pidpath` and not `ps`, and that is a correction with a red run
    /// behind it. The first version parsed `ps -Ao pid=,comm=` and compared
    /// against `Bundle.main.executablePath`. `comm` reports the path AS
    /// INVOKED -- `./app/VESPER.app/Contents/MacOS/VESPER` -- so the compare
    /// never matched, and the guard sat there returning an empty list while a
    /// sibling was demonstrably running three feet away. A guard that cannot
    /// fire is worse than no guard: it reads as a clean bill of health.
    ///
    /// libproc gives the kernel's own absolute path for a pid, so the
    /// invocation form cannot matter. Public API, no subprocess.
    static func runningSiblings() -> [Int32] {
        let me = ProcessInfo.processInfo.processIdentifier
        let mine = URL(fileURLWithPath: Bundle.main.executablePath
                        ?? CommandLine.arguments[0],
                       relativeTo: URL(fileURLWithPath: FileManager.default.currentDirectoryPath))
                   .standardizedFileURL.resolvingSymlinksInPath().path

        let cap = proc_listpids(UInt32(PROC_ALL_PIDS), 0, nil, 0)
        guard cap > 0 else { return [] }
        var pids = [pid_t](repeating: 0, count: Int(cap) / MemoryLayout<pid_t>.size)
        let got = pids.withUnsafeMutableBufferPointer {
            proc_listpids(UInt32(PROC_ALL_PIDS), 0, $0.baseAddress, cap)
        }
        guard got > 0 else { return [] }

        var found: [Int32] = []
        var buf = [CChar](repeating: 0, count: 4096)   // PROC_PIDPATHINFO_MAXSIZE, which Swift does not import
        for pid in pids.prefix(Int(got) / MemoryLayout<pid_t>.size) where pid > 0 && pid != me {
            let n = proc_pidpath(pid, &buf, UInt32(buf.count))
            guard n > 0 else { continue }
            if String(cString: buf) == mine { found.append(pid) }
        }
        return found
    }

    static func identity() {
        let b = Bundle.main
        say("")
        say("  IDENTITY — what TCC will attribute a grant to")
        say("  " + String(repeating: "─", count: 62))
        say("  bundle identifier : \(b.bundleIdentifier ?? "— none: this is a loose binary —")")
        say("  executable        : \(b.executablePath ?? CommandLine.arguments[0])")
        say("  bundle path       : \(b.bundlePath)")

        // Not our self-report. codesign reads the signature the kernel reads.
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        p.arguments = ["-dv", "--verbose=2", b.bundlePath]
        let pipe = Pipe(); p.standardError = pipe; p.standardOutput = pipe
        var out = ""
        do {
            try p.run()
            out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(),
                         encoding: .utf8) ?? ""
            p.waitUntilExit()
        } catch { out = "codesign could not run: \(error.localizedDescription)" }

        for line in out.split(separator: "\n") where
            line.hasPrefix("Identifier=") || line.hasPrefix("Signature=")
            || line.hasPrefix("TeamIdentifier=") {
            say("  codesign says     : \(line)")
        }
        if b.bundleIdentifier == nil {
            say("")
            say("  *** LOOSE BINARY. Any permission granted to this run is granted to")
            say("      the terminal that launched it. Run it as:")
            say("      open -a app/VESPER.app --args --home-verify")
        }
        say("")
    }

    /// Sample the ground, the control and the window server together, for
    /// `secs`, and let the owner drive the Desktop switch. An owner-driven
    /// test is honest for a mechanism that is owner-driven -- nothing here may
    /// move the thing it is reading.
    ///
    /// `after` is switch-first-then-create, done by hand. The ground is
    /// `.managed`, so it lands on whichever Desktop is active WHEN IT IS
    /// CREATED, and the owner is necessarily on their terminal's Desktop when
    /// they start this. Counting down first lets them get to the home's
    /// Desktop before the ground exists, which is the same ordering §2.3a
    /// specifies for the real thing.
    ///
    /// `control` is THE ISLAND'S OWN PANEL, and that is a correction to this
    /// file's first attempt. That version used a second full-screen window at
    /// the ground's level, which the first run showed to be useless: a
    /// full-screen terminal covers both windows, both read covered, and the
    /// control cannot separate "elsewhere" from "underneath". The island panel
    /// is `.canJoinAllSpaces` AND above every ordinary window, so nothing can
    /// cover it and no Desktop can be without it. If IT ever reports covered,
    /// this instrument is measuring something other than residency -- and it
    /// is also the exact window §2.6 proposes to move, so the control is the
    /// claim rather than a stand-in for it.
    static func occlusion(secs: Double, after: Double, control: NSWindow?, log: String?) {
        guard let screen = NSScreen.main else { print("no screen"); return }

        // REFUSE TO RUN BESIDE ANOTHER VESPER, because the control cannot
        // survive it and the failure looks like a finding.
        //
        // The LaunchAgent keeps an instance alive, so a verify run started by
        // hand is a SECOND one. Both draw an island panel, same level, same
        // place; the older sits on top and the newer reports itself covered in
        // every sample. That is exactly the reading that means "this instrument
        // is measuring something else" -- so the run would report a real fault
        // in §2.6 which is nothing but two copies of VESPER.
        //
        // Measured, not reasoned: the control read 0 covered, then 12 of 12
        // across three consecutive runs, then 0 again the moment the stray pid
        // was killed. Nothing about the window changed in between.
        let others = runningSiblings()
        if !others.isEmpty {
            say("")
            say("  ANOTHER VESPER IS ALREADY RUNNING — pid \(others.map(String.init).joined(separator: ", "))")
            say("")
            say("  Its island panel sits over this one's, so the control would report")
            say("  itself covered in every sample and the run would look like a §2.6")
            say("  failure. Stop the other one first:")
            say("")
            say("    launchctl bootout gui/$(id -u)/ai.vesper.island   # if the agent is loaded")
            say("    kill \(others.map(String.init).joined(separator: " "))")
            say("")
            exit(3)
        }

        struct Sample {
            let t: Double
            let groundVisible: Bool     // NSWindowOcclusionState, the ground
            let controlVisible: Bool    // NSWindowOcclusionState, the island
            let groundOnScreen: Bool    // the window server's own report
            let foreign: Set<Int>
        }
        var samples: [Sample] = []

        say("")
        say("  §2.6 — IS LEAVING THE DESKTOP ENOUGH TO DARKEN THE GROUND?")
        say("  " + String(repeating: "═", count: 62))
        say("  ground  : .managed          — lives on ONE Desktop")
        say("  control : the island panel  — on EVERY Desktop, above everything,")
        say("            so nothing can cover it. It must never report covered.")
        say("")
        say("  Nothing may be covering the ground on VESPER's Desktop, or it is")
        say("  never lit and the run measures nothing. The empty Desktop is right.")
        say("")
        say("  1. In the next \(Int(after)) s, switch to VESPER's Desktop (the empty one).")
        say("  2. The ground is created THERE — switch-first-then-create.")
        say("  3. Then switch away, wait, and come back. \(Int(secs)) s of sampling.")
        say("")

        // Switch first, THEN create. Nothing exists until the countdown ends.
        var home: HomeController?
        DispatchQueue.main.asyncAfter(deadline: .now() + after) {
            guard let h = HomeController(screen: screen) else { exit(2) }
            home = h
            h.present()
            say("  ground created on the Desktop you are on now.")

            let t0 = Date()
            let timer = Timer(timeInterval: 0.25, repeats: true) { _ in
                let dt = Date().timeIntervalSince(t0)
                let s = Sample(t: dt,
                               groundVisible: h.ground.occlusionState.contains(.visible),
                               controlVisible: control?.occlusionState.contains(.visible) ?? true,
                               groundOnScreen: SpaceWatch.isOnActiveSpace(Int(h.ground.windowNumber)),
                               foreign: SpaceWatch.fingerprint())
                samples.append(s)
            }
            RunLoop.main.add(timer, forMode: .common)

            DispatchQueue.main.asyncAfter(deadline: .now() + secs) {
            timer.invalidate()
            home?.stopRendering()

            var passed = 0, failed = 0, undecided = 0
            func check(_ n: String, _ ok: Bool, _ d: String) {
                say("  \(ok ? "PASS" : "FAIL")  \(n)  —  \(d)")
                ok ? (passed += 1) : (failed += 1)
            }
            func open(_ n: String, _ d: String) {
                say("  ????  \(n)  —  \(d)"); undecided += 1
            }

            // Independent switch detection: the owner's OWN windows, which
            // neither of our windows can influence.
            var minOverlap = 1.0
            for i in samples.indices {
                for j in samples.indices where j > i {
                    minOverlap = Swift.min(minOverlap,
                                 SpaceWatch.overlap(samples[i].foreign, samples[j].foreign))
                }
            }
            let switched = minOverlap < 0.5

            let gOn   = samples.filter { $0.groundVisible }.count
            let gOff  = samples.count - gOn
            let cOff  = samples.filter { !$0.controlVisible }.count
            let wsOff = samples.filter { !$0.groundOnScreen }.count

            // THE CRITERION IS AN IMPLICATION, NOT AN AGREEMENT, and the first
            // version of this file had it wrong.
            //
            // It asked whether occlusion AGREES with the window server, and a
            // dry run answered 0% while nobody switched anything: the ground was
            // on the active Desktop in all 24 samples and reported covered in
            // all 24, because a full-screen terminal was over it. That is not
            // occlusion failing. It is occlusion answering the question it
            // actually answers -- "is anything on top of me" -- which is
            // STRICTLY STRONGER than residency and is exactly what §2.6 and §10
            // ask for. Both rules want "the owner cannot see the home", and a
            // window on top means they cannot.
            //
            // So the requirement is one-directional: leaving the Desktop must be
            // ENOUGH to darken the ground. Dark while present is legitimate and
            // is reported rather than judged; LIT WHILE ABSENT is the fault,
            // because that is the island staying hidden while the owner is in
            // another room.
            let litWhileAbsent = samples.filter { !$0.groundOnScreen && $0.groundVisible }.count
            let darkWhilePresent = samples.filter { $0.groundOnScreen && !$0.groundVisible }.count

            say(String(repeating: "─", count: 66))
            say(String(format: "  %d samples over %.0f s", samples.count, secs))
            say(String(format: "  least foreign-window overlap between any two samples: %.2f", minOverlap))
            say("  → a Desktop switch was \(switched ? "OBSERVED" : "NOT observed")")
            say("")
            say(String(format: "  ground  occlusion   lit %3d / covered %3d", gOn, gOff))
            say(String(format: "  window server says  on  %3d / off     %3d   (the authority)",
                       samples.count - wsOff, wsOff))
            say(String(format: "  lit while ABSENT    %3d   ← must be 0", litWhileAbsent))
            say(String(format: "  dark while present  %3d   ← legitimate: something was over it",
                       darkWhilePresent))
            say(String(format: "  control (island)    covered in %3d samples   ← must be 0", cOff))
            say("")

            if !switched {
                open("space/switch-happened",
                     "the owner's windows never changed enough to show a Desktop switch, so "
                     + "nothing about §2.6 is proven either way. Re-run and switch away and back.")
            } else {
                // §2.2 first. If the ground followed the owner, everything
                // downstream is measuring the wrong window.
                check("space/windowserver-saw-the-ground-leave", wsOff > 0,
                      wsOff > 0
                      ? "the ground was off the active Space in \(wsOff) samples, which is §2.2 holding"
                      : "a switch happened and the ground was on screen in every sample — it FOLLOWED the owner, so it is not behaving as .managed")

                // THE GUARD THAT MAKES THE NEXT CHECK NON-VACUOUS. If the ground
                // was covered for the whole run, "it went dark when you left" is
                // true of a window that was never lit in the first place. The dry
                // run that corrected this file scored gOn = 0, and every check
                // downstream would have passed on nothing.
                check("space/ground-was-lit-at-some-point", gOn > 0,
                      gOn > 0
                      ? "the ground was visible in \(gOn) samples, so darkness later is an EDGE and not a constant"
                      : "the ground reported covered in EVERY sample, so it was never lit and nothing below means anything. Something was over it on its own Desktop — move that window off VESPER's Desktop and run again")

                check("space/leaving-the-desktop-darkens-the-ground", litWhileAbsent == 0,
                      litWhileAbsent == 0
                      ? "the ground never reported itself visible while off the active Desktop — leaving is enough to darken it, which is what §2.6 and §10 both read"
                      : "the ground reported VISIBLE in \(litWhileAbsent) samples where the window server said it was on another Desktop. §2.6 would leave the island hidden while the owner is in another room; the signal has to come from NSWorkspace.activeSpaceDidChangeNotification instead")

                // THE CONTROL. It is on every Desktop and above every ordinary
                // window, so it cannot be left behind and cannot be covered.
                check("space/control-stayed-lit", cOff == 0,
                      cOff == 0
                      ? "the island panel never reported covered, so the ground's readings are residency and covering — not the whole app deactivating"
                      : "the island panel reported covered in \(cOff) samples. It is on EVERY Desktop and above every ordinary window, so it can be neither left behind nor covered — this instrument is reading something else, and the ground's \(gOff) is not evidence of anything")
            }

            say("")
            say(String(repeating: "═", count: 66))
            let verdict = failed == 0 && undecided == 0 && passed > 0
            say("  §2.6 OCCLUSION SIGNAL: \(failed > 0 ? "FAIL (\(failed))" : undecided > 0 ? "INCONCLUSIVE" : "PASS (\(passed))")")
            say(String(repeating: "═", count: 66))
            say("")

            if let path = log {
                try? lines.joined(separator: "\n").write(toFile: path, atomically: true,
                                                         encoding: .utf8)
                print("  log: \(path)")
            }
            exit(verdict ? 0 : 1)
            }
        }
    }
}
