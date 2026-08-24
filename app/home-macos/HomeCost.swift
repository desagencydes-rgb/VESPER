// VESPER — SPIKE-013 §1, the half that needs no sudo.
//
// The spike's precondition was answered on 2026-08-23 and its actual question
// was not: what does the two-layer home COST? Everything now on screen runs at
// an unmeasured power budget, on a laptop whose stated goal is to stretch its
// own life, and §1 blocks build steps F1-F3 by its own `blocks` field.
//
// WHAT THIS DELIVERS AND WHAT IT DOES NOT, stated first so no line below can be
// read as more than it is.
//
//   pass criterion 3  ABSENT draws zero, proven by counter        DELIVERED
//   pass criterion 4  occluded draws zero, proven by counter      DELIVERED
//   pass criterion 1  the composite's cost                        CPU COLUMN ONLY
//   pass criterion 2  DISPERSED <= CENTRE on every axis           NOT MEASURABLE
//   pass criterion 5  a decided idle cadence and its power        NOT MEASURED
//   pass criterion 6  battery drain as hours of runtime           NOT MEASURED
//
// Criteria 5 and 6 need `powermetrics`, which needs sudo. Criterion 2 needs the
// four presence tiers of §8, and `HomeController` has one: the face draws or it
// does not. ATTENDANT and DISPERSED are design, not code, so measuring them
// would mean measuring something invented for the measurement -- which is worse
// than a gap, because a gap is visible.
//
// §3 of the protocol: "Not permitted: reporting a figure measured on mains as
// the battery figure." The power source is read from the system and printed on
// every run, and a mains run says so in its own header rather than in a footnote.
//
// THE CPU INSTRUMENT, and the two ways it has already been got wrong here.
//
//   proc_pid_rusage(getpid())  reports THIS process. WebKit renders in
//                              com.apple.WebKit.WebContent and composites in the
//                              GPU process, so the webview measures as nearly
//                              free -- wrong in the exact direction that makes
//                              the architecture look affordable.
//   host_processor_info        reports the whole machine. The first SPIKE-013
//                              run read 132% at "wallpaper only" and then
//                              measured the face as CHEAPER than the wallpaper,
//                              because an agent session dominated every sample.
//
// So the reading is OUR PROCESS TREE: this process plus the WebKit helpers that
// appeared after we started. It keeps the out-of-process cost that self CPU
// hides, and drops every process that has nothing to do with us. The helper set
// is baselined BEFORE the webview is constructed, which is what makes it ours
// rather than, say, Safari's.

import AppKit

enum HomeCost {

    // MARK: - The tree

    private static var pidsAtStart: Set<Int32> = []

    static func baselinePids() { pidsAtStart = allPids() }

    private static func allPids() -> Set<Int32> {
        var buf = [Int32](repeating: 0, count: 8192)
        let bytes = proc_listpids(UInt32(PROC_ALL_PIDS), 0, &buf,
                                  Int32(buf.count * MemoryLayout<Int32>.size))
        guard bytes > 0 else { return [] }
        return Set(buf.prefix(Int(bytes) / MemoryLayout<Int32>.size).filter { $0 != 0 })
    }

    private static func processName(_ pid: Int32) -> String {
        var n = [CChar](repeating: 0, count: 256)
        proc_name(pid, &n, UInt32(n.count))
        return String(cString: n)
    }

    private static func cpuSeconds(_ pid: Int32) -> Double {
        var usage = rusage_info_v4()
        let r = withUnsafeMutablePointer(to: &usage) {
            $0.withMemoryRebound(to: Optional<rusage_info_t>.self, capacity: 1) {
                proc_pid_rusage(pid, RUSAGE_INFO_V4, $0)
            }
        }
        return r == 0 ? Double(usage.ri_user_time + usage.ri_system_time) / 1e9 : 0
    }

    /// This process, plus any WebKit helper that was not running before we were.
    static func treePids() -> [Int32] {
        var out: [Int32] = [getpid()]
        for p in allPids() where !pidsAtStart.contains(p) {
            let n = processName(p)
            if n.contains("WebKit") || n.contains("WebContent") || n.contains("Networking") {
                out.append(p)
            }
        }
        return out
    }

    static func treeCPUSeconds() -> Double {
        treePids().reduce(0) { $0 + cpuSeconds($1) }
    }

    // MARK: - The world

    /// Battery or mains, read from the system. §3 forbids reporting one as the
    /// other, so it is read rather than assumed and printed rather than filed.
    static func powerSource() -> String {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/pmset")
        p.arguments = ["-g", "batt"]
        let pipe = Pipe()
        p.standardOutput = pipe
        do { try p.run() } catch { return "UNKNOWN (pmset would not run)" }
        let d = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        let s = String(data: d, encoding: .utf8) ?? ""
        let line = s.split(separator: "\n").first.map(String.init) ?? ""
        let pct = s.split(separator: "\t").dropFirst().first.map(String.init)?
            .split(separator: ";").first.map(String.init) ?? ""
        return line.replacingOccurrences(of: "Now drawing from ", with: "")
             + (pct.isEmpty ? "" : " · \(pct.trimmingCharacters(in: .whitespaces))")
    }

    // MARK: - A phase

    struct Reading {
        let name: String
        let cpu: Double         // % of one core, over the phase's wall time
        let fps: Double
        let frames: Int
        let note: String
    }

    private(set) static var readings: [Reading] = []

    /// Measure one phase, then hand control on. Frames come from the controller's
    /// own counter, which counts ATTEMPTS -- so a zero here is strong (nothing
    /// even tried) and a non-zero is weak on its own, which is why the pixel
    /// readers exist elsewhere.
    static func phase(_ name: String, seconds: Double, note: String = "",
                      frames: @escaping () -> Int,
                      then next: @escaping () -> Void) {
        let t0 = Date()
        let c0 = treeCPUSeconds()
        let f0 = frames()
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) {
            let wall = Date().timeIntervalSince(t0)
            let cpu = (treeCPUSeconds() - c0) / wall * 100
            let df = frames() - f0
            readings.append(Reading(name: name, cpu: cpu,
                                    fps: Double(df) / wall, frames: df, note: note))
            next()
        }
    }
}
