// VESPER — SPIKE-013: what does the two-layer home cost?
//
// HOME-ARCHITECTURE.md §1.1 puts the home in ONE window with TWO layers: a
// Metal field below carrying the ambience and the face, a transparent webview
// above carrying the cards. It then says, in the same section:
//
//   "The cost of the composite is unmeasured and is SPIKE-013. A full-screen
//    transparent webview over a 60 fps Metal layer is not free, and on a laptop
//    whose stated goal is to stretch its own life, 'not free' needs a number
//    before it needs a design."
//
// This is that number. It is the last unmeasured thing that can still change
// the architecture, which is why it runs before F3 rather than after.
//
// THE INTERACTION BEING MEASURED, stated up front so the phases make sense.
// iOS 26 glass is `backdrop-filter: blur()`, and a backdrop filter has to be
// RECOMPUTED whenever what is behind it changes. Behind it is a Metal layer
// redrawing at 60 fps. So the question is not "what does a webview cost" and
// not "what does the face cost" -- both are already known or cheap. It is
// whether putting them together costs more than the sum, and how much.
//
// Hence four phases, and the third exists only to isolate that:
//
//   1 ground      wallpaper only                        the floor
//   2 field       wallpaper + face at 60 fps            FaceRenderer alone
//   3 glass       wallpaper + webview glass, face STILL blur over a static
//                                                       backdrop
//   4 composite   wallpaper + face at 60 fps + glass    blur over a MOVING
//                                                       backdrop -- the home
//
// If 4 ≈ 2 + 3 − 1, the layers are independent and the design stands. If 4 runs
// well above that, the blur is re-running per frame and §1.1's three named
// fallbacks are on the table.

import AppKit
import WebKit
import QuartzCore

// ---------------------------------------------------------------------------
// THE INSTRUMENT, and the trap it is built around.
//
// WebKit is multi-process. The web content renders in com.apple.WebKit.WebContent
// and compositing happens in the GPU process, NEITHER of which is this pid. So
// proc_pid_rusage(getpid()) -- the obvious call -- would report the webview as
// very nearly free, and would be wrong in the exact direction that makes the
// architecture look affordable. That is the kind of number this repo exists to
// refuse.
//
// So the primary reading is SYSTEM-WIDE CPU from host_processor_info, taken
// against a measured idle baseline. It captures every process regardless of who
// owns it. Self CPU is reported alongside, and the GAP between them is the
// out-of-process cost made visible rather than hidden.
// ---------------------------------------------------------------------------

// FIRST RUN, 2026-08-23, threw all three of its readings away. Recorded here
// because the instrument is the deliverable and its failures are the design:
//
//   system CPU 132% at "wallpaper only", and "field" then measured LOWER than
//   "ground" -- the face apparently made the machine less busy. System-wide CPU
//   is dominated by whatever else is running (an agent session, in that case),
//   and the signal was nowhere in it.
//
// So the primary reading is now OUR PROCESS TREE: this process plus the WebKit
// helper processes that appeared after we started. That keeps the out-of-process
// cost -- the whole reason system CPU was reached for -- while dropping every
// process that has nothing to do with us. Baselining the WebKit pids BEFORE the
// webview is constructed is what makes it ours rather than, say, Safari's.

func allPids() -> Set<Int32> {
    var buf = [Int32](repeating: 0, count: 8192)
    let bytes = proc_listpids(UInt32(PROC_ALL_PIDS), 0, &buf,
                              Int32(buf.count * MemoryLayout<Int32>.size))
    guard bytes > 0 else { return [] }
    return Set(buf.prefix(Int(bytes) / MemoryLayout<Int32>.size).filter { $0 != 0 })
}

func processName(_ pid: Int32) -> String {
    var n = [CChar](repeating: 0, count: 256)
    proc_name(pid, &n, UInt32(n.count))
    return String(cString: n)
}

func cpuSeconds(_ pid: Int32) -> Double {
    var usage = rusage_info_v4()
    let r = withUnsafeMutablePointer(to: &usage) {
        $0.withMemoryRebound(to: Optional<rusage_info_t>.self, capacity: 1) {
            proc_pid_rusage(pid, RUSAGE_INFO_V4, $0)
        }
    }
    return r == 0 ? Double(usage.ri_user_time + usage.ri_system_time) / 1e9 : 0
}

let PIDS_AT_START = allPids()

/// This process plus any WebKit helper that was not running before we were.
func ourTreePids() -> [Int32] {
    var out: [Int32] = [getpid()]
    for p in allPids() where !PIDS_AT_START.contains(p) {
        let n = processName(p)
        if n.contains("WebKit") || n.contains("WebContent") || n.contains("Networking") {
            out.append(p)
        }
    }
    return out
}

func treeCPUSeconds() -> Double { ourTreePids().reduce(0) { $0 + cpuSeconds($1) } }

func systemCPUTicks() -> (busy: Double, total: Double) {
    var count = mach_msg_type_number_t(0)
    var cpuCount = natural_t(0)
    var info: processor_info_array_t?
    guard host_processor_info(mach_host_self(), PROCESSOR_CPU_LOAD_INFO,
                              &cpuCount, &info, &count) == KERN_SUCCESS,
          let data = info else { return (0, 0) }
    defer { vm_deallocate(mach_task_self_, vm_address_t(bitPattern: data),
                          vm_size_t(count) * vm_size_t(MemoryLayout<integer_t>.size)) }
    var busy = 0.0, total = 0.0
    for i in 0..<Int(cpuCount) {
        let o = i * Int(CPU_STATE_MAX)
        let user = Double(data[o + Int(CPU_STATE_USER)])
        let sys  = Double(data[o + Int(CPU_STATE_SYSTEM)])
        let nice = Double(data[o + Int(CPU_STATE_NICE)])
        let idle = Double(data[o + Int(CPU_STATE_IDLE)])
        busy += user + sys + nice
        total += user + sys + nice + idle
    }
    return (busy, total)
}

func selfCPUSeconds() -> Double {
    var usage = rusage_info_v4()
    let r = withUnsafeMutablePointer(to: &usage) {
        $0.withMemoryRebound(to: Optional<rusage_info_t>.self, capacity: 1) {
            proc_pid_rusage(getpid(), RUSAGE_INFO_V4, $0)
        }
    }
    guard r == 0 else { return 0 }
    return Double(usage.ri_user_time + usage.ri_system_time) / 1e9
}

let CORES = Double(ProcessInfo.processInfo.activeProcessorCount)

struct Reading { let phase: String; let systemPct: Double; let selfPct: Double }
var readings: [Reading] = []

let LOG = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent().appendingPathComponent("spike013_last_run.log").path
var logBuf = ""
func say(_ l: String = "") {
    print(l); logBuf += l + "\n"
    try? logBuf.write(toFile: LOG, atomically: true, encoding: .utf8)
}

func repoRoot() -> String {
    URL(fileURLWithPath: CommandLine.arguments[0])
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().path
}

// ---------------------------------------------------------------------------
// The chrome. It must render what the home will actually render, not a page of
// text -- a page of text would measure nothing. Twelve translucent cards with a
// real backdrop blur, which is the iOS 26 glass the foundation specifies and the
// single most expensive thing the chrome does.
// ---------------------------------------------------------------------------

let GLASS_HTML = """
<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:transparent;overflow:hidden;
            font-family:-apple-system,system-ui,sans-serif;color:#f4e6dc}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:22px;padding:56px;
        height:100%;box-sizing:border-box}
  .card{border-radius:22px;padding:20px;
        background:rgba(255,255,255,.10);
        -webkit-backdrop-filter:blur(26px) saturate(160%);
        backdrop-filter:blur(26px) saturate(160%);
        border:1px solid rgba(255,255,255,.16);
        box-shadow:0 8px 32px rgba(0,0,0,.22)}
  .k{font-size:10px;letter-spacing:.14em;text-transform:uppercase;opacity:.6}
  .v{font-size:30px;font-weight:200;margin-top:8px}
  .s{font-size:11px;opacity:.55;margin-top:6px}
</style></head><body><div class="grid" id="g"></div><script>
  const names=["context","cache","tokens","power","thermal","memory","fabric",
               "placement","hlc drift","queue","stage","endpoint"];
  document.getElementById('g').innerHTML = names.map(n=>
    `<div class="card"><div class="k">${n}</div>
     <div class="v">UNAVAILABLE</div>
     <div class="s">no producer — fixture</div></div>`).join('');
</script></body></html>
"""

// ---------------------------------------------------------------------------

final class Field: NSView {
    let metal = CAMetalLayer()
    var face: FaceRendererShim?
    var animating = false
    var wallpaper: CGImage?

    override func draw(_ r: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        if let w = wallpaper {
            let iw = CGFloat(w.width), ih = CGFloat(w.height)
            let s = max(bounds.width / iw, bounds.height / ih)
            let dw = iw * s, dh = ih * s
            ctx.draw(w, in: CGRect(x: bounds.midX - dw/2, y: bounds.midY - dh/2,
                                   width: dw, height: dh))
        } else { NSColor.black.setFill(); r.fill() }
    }
}

// FaceRenderer.swift is compiled in beside this file; this alias keeps the
// spike readable about which parts are borrowed and which are its own.
typealias FaceRendererShim = FaceRenderer

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard let screen = NSScreen.main else { fatalError("no screen") }

let win = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                   backing: .buffered, defer: false)
win.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
win.collectionBehavior = [.managed]
win.animationBehavior = .none
win.isOpaque = true

let field = Field(frame: NSRect(origin: .zero, size: screen.frame.size))
field.wantsLayer = true
if let img = NSImage(contentsOfFile: repoRoot() + "/docs/design/assets/wallpapers/thinking.png"),
   let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) {
    field.wallpaper = cg
}
win.contentView = field

// the Metal face layer, wired the way main.swift wires it
field.face = FaceRendererShim(cloudPath: repoRoot() + "/app/island-macos/face.bin")
let metal = field.metal
if let f = field.face {
    metal.device = f.device
    metal.pixelFormat = .bgra8Unorm
    metal.framebufferOnly = true
    metal.isOpaque = false
    metal.contentsScale = screen.backingScaleFactor
    let side = min(screen.frame.width, screen.frame.height) * 0.62
    metal.frame = CGRect(x: screen.frame.midX - side/2,
                         y: screen.frame.midY - side/2, width: side, height: side)
    // Without this, nextDrawable() hands back nil and every draw silently does
    // nothing -- which is what the first run measured and reported as 0.1% CPU.
    metal.drawableSize = CGSize(width: side * screen.backingScaleFactor,
                                height: side * screen.backingScaleFactor)
    f.uniforms.aspect = 1
    f.uniforms.scale = 1
    field.layer?.addSublayer(metal)
}

// the webview, transparent, on top
let cfg = WKWebViewConfiguration()
let web = WKWebView(frame: NSRect(origin: .zero, size: screen.frame.size), configuration: cfg)
// PUBLIC API ONLY. The usual route to a transparent WKWebView is
// setValue(false, forKey: "drawsBackground"), which is KVC onto a non-public
// property -- exactly what ISLAND-ARCHITECTURE §2 rules out, and the failure
// mode is silent and arrives after an OS update. underPageBackgroundColor is
// public from macOS 12.
web.underPageBackgroundColor = .clear
web.setValue(false, forKey: "allowsMagnification")
web.isHidden = true
field.addSubview(web)
web.loadHTMLString(GLASS_HTML, baseURL: nil)

win.orderFrontRegardless()

// --- the driver ------------------------------------------------------------

var faceAngle: Float = 0
// Counted, not assumed. The first run reported self CPU of 0.1% while
// supposedly drawing 39,805 points at 60 fps, which is not a cheap renderer --
// it is a renderer that never ran. `nextDrawable()` returns nil when the layer
// has no drawableSize, and nothing in the old code ever set one.
var facesDrawn = 0

func startFace() {
    field.animating = true
    Timer.scheduledTimer(withTimeInterval: 1.0/60.0, repeats: true) { t in
        guard field.animating else { t.invalidate(); return }
        faceAngle += 0.012
        field.face?.uniforms.yaw = sinf(faceAngle) * 0.35
        field.face?.uniforms.pitch = cosf(faceAngle * 0.7) * 0.12
        if let f = field.face { f.draw(in: metal); facesDrawn += 1 }
    }
}

func measure(_ phase: String, seconds: Double, _ done: @escaping () -> Void) {
    let t0 = Date()
    let tree0 = treeCPUSeconds()
    let s0 = systemCPUTicks()
    let frames0 = facesDrawn
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds) {
        let wall = Date().timeIntervalSince(t0)
        let treePct = (treeCPUSeconds() - tree0) / wall * 100
        let s1 = systemCPUTicks()
        let dTotal = s1.total - s0.total
        let sysPct = dTotal > 0 ? (s1.busy - s0.busy) / dTotal * 100 * CORES : 0
        let fps = Double(facesDrawn - frames0) / wall
        readings.append(Reading(phase: phase, systemPct: treePct, selfPct: sysPct))
        say(String(format: "  %-11s  ours %6.1f%%   (machine %6.1f%%)   face %5.1f fps",
                   (phase as NSString).utf8String!, treePct, sysPct, fps))
        done()
    }
}

say("""

  VESPER — SPIKE-013, the composite cost
  ══════════════════════════════════════════════════════════════════
  \(Int(CORES)) cores. System CPU is the primary reading because WebKit
  renders out of process — self CPU alone would report the webview
  as nearly free, in the direction that flatters the design.

  Four phases, 12 s each. Please leave the machine alone.

""")

let DUR = 12.0

func phaseGround() {
    say("  1 ground — wallpaper only")
    measure("ground", seconds: DUR) { phaseField() }
}
func phaseField() {
    say("  2 field — + face at 60 fps (\(field.face?.count ?? 0) points)")
    startFace()
    measure("field", seconds: DUR) { phaseGlass() }
}
func phaseGlass() {
    say("  3 glass — + webview glass, face HELD STILL")
    field.animating = false
    web.isHidden = false
    measure("glass", seconds: DUR) { phaseComposite() }
}
func phaseComposite() {
    say("  4 composite — + face at 60 fps under the glass")
    startFace()
    measure("composite", seconds: DUR) { verdict() }
}

func verdict() {
    field.animating = false
    let g = readings.first { $0.phase == "ground" }?.systemPct ?? 0
    let f = readings.first { $0.phase == "field" }?.systemPct ?? 0
    let gl = readings.first { $0.phase == "glass" }?.systemPct ?? 0
    let c = readings.first { $0.phase == "composite" }?.systemPct ?? 0

    let predicted = f + gl - g          // if the layers were independent
    let excess = c - predicted

    say("")
    say(String(repeating: "─", count: 66))
    say(String(format: "  face alone above ground      %+6.1f%%", f - g))
    say(String(format: "  glass alone above ground     %+6.1f%%", gl - g))
    say(String(format: "  composite if independent     %6.1f%%", predicted))
    say(String(format: "  composite measured           %6.1f%%", c))
    say(String(format: "  EXCESS from compositing      %+6.1f%%", excess))
    say("")
    if excess < 3 {
        say("  The layers are close to independent. §1.1's two-layer home stands.")
    } else if excess < 10 {
        say("  Real but bounded. The blur is re-running over a moving backdrop.")
        say("  Worth a fallback, not a redesign — see §1.1's three.")
    } else {
        say("  The composite costs far more than its parts. A full-screen backdrop")
        say("  blur over a 60 fps layer is being recomputed per frame. §1.1's")
        say("  fallbacks are not optional.")
    }
    say(String(repeating: "═", count: 66))
    say("  log: \(LOG)")
    exit(0)
}

// The glass must actually be transparent or phase 3 and 4 measure a blur with
// nothing behind it. Checked by snapshotting the webview and reading a corner
// pixel's alpha -- no permission, and it is the difference between a real
// number and a flattering one.
/// Sample one point of the ACTUAL composite, in the grid's padding where no card
/// sits, with the webview hidden and then shown. If the pixel does not change,
/// the webview is painting nothing there and the glass has the wallpaper behind
/// it. If it changes, the webview is opaque.
///
/// The first run asked WKWebView for a snapshot and read its corner alpha, got
/// 1.00, and called the glass opaque. That check was not measuring the page --
/// takeSnapshot composites onto an opaque bitmap, so it returns alpha 1.00 for a
/// perfectly transparent page. A precondition that fails for a page that is fine
/// is as useless as one that passes for a page that is not; both stop the run
/// from meaning anything.
func sampleComposite() -> NSColor? {
    let probe = NSRect(x: 12, y: 12, width: 4, height: 4)
    guard let rep = field.bitmapImageRepForCachingDisplay(in: probe) else { return nil }
    field.cacheDisplay(in: probe, to: rep)
    return rep.colorAt(x: 1, y: 1)
}

DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
    web.isHidden = true
    let without = sampleComposite()
    web.isHidden = false
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
        let with = sampleComposite()
        web.isHidden = true

        guard let a = without, let b = with else {
            say("  precondition · glass transparency: CANNOT SAMPLE — aborting")
            say("  A run whose precondition could not be checked is not a measurement.")
            exit(2)
        }
        let d = abs(a.redComponent - b.redComponent)
              + abs(a.greenComponent - b.greenComponent)
              + abs(a.blueComponent - b.blueComponent)
        if d > 0.06 {
            say(String(format: "  precondition · glass transparency: *** OPAQUE (Δ %.3f) ***", d))
            say("")
            say("  The webview paints over the wallpaper where no card sits, so phases 3")
            say("  and 4 would measure a backdrop blur with nothing behind it. That number")
            say("  would be lower than the truth and would flatter the design.")
            say("  ABORTING rather than reporting it. The first run did not abort, and")
            say("  printed a verdict off three invalid readings.")
            exit(1)
        }
        say(String(format: "  precondition · glass transparency: PASS (Δ %.3f) — the blur has the wallpaper behind it", d))
        say("")
        phaseGround()
    }
}

app.run()
