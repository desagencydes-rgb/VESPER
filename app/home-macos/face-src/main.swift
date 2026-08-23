// VESPER — the face on the ground. F3's first slice, and the face's first
// honest measurement outside the island.
//
// WHY THIS EXISTS SEPARATELY FROM SPIKE-013. The owner asked whether the tests
// so far said the face was good. They did not -- they said the opposite of a
// measurement. SPIKE-013's first run reported 39,805 points costing 0.1% CPU,
// which is not a cheap renderer, it is a renderer that never ran: nothing set
// CAMetalLayer.drawableSize, so nextDrawable() returned nil and every draw
// silently did nothing. The only true thing that run established about the face
// is that FaceRenderer initialises and loads its cloud.
//
// So the face gets measured alone, before it gets measured under glass. A spike
// whose two halves were never seen apart cannot attribute a number to either,
// and F3's tiers are gated on knowing which half costs what.
//
// WHAT THE OWNER'S WALLPAPER CHANGE BOUGHT HERE. The mode picture is now the
// real desktop picture, so this window carries NO wallpaper -- it is transparent
// and holds only the face. That is not a saving in this probe, it is the
// architecture: an opaque full-screen layer of ours is out of the compositing
// path entirely, and what sits behind the face is the window server's own
// desktop.
//
// A SILENT NO-OP IS THE FAILURE MODE THIS FILE IS BUILT AGAINST. Every draw is
// counted, and so is every nextDrawable() that came back nil. A run that reports
// a low number and 0 successful draws is reporting nothing, and says so.

import AppKit
import Metal

func repoRoot() -> String {
    // <repo>/app/home-macos/face_ground -> three up. argv[0] can be relative
    // ("./app/home-macos/face_ground"), so resolve against cwd first, or the
    // three deletions eat a path that was never that deep.
    let exe = URL(fileURLWithPath: CommandLine.arguments[0],
                  relativeTo: URL(fileURLWithPath: FileManager.default.currentDirectoryPath))
        .standardizedFileURL
    return exe.deletingLastPathComponent()      // home-macos
              .deletingLastPathComponent()      // app
              .deletingLastPathComponent().path // repo
}

func selfCPUSeconds() -> Double {
    var u = rusage_info_v4()
    let r = withUnsafeMutablePointer(to: &u) {
        $0.withMemoryRebound(to: Optional<rusage_info_t>.self, capacity: 1) {
            proc_pid_rusage(getpid(), RUSAGE_INFO_V4, $0)
        }
    }
    return r == 0 ? Double(u.ri_user_time + u.ri_system_time) / 1e9 : 0
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard let screen = NSScreen.main else { fatalError("no screen") }

// The ground: F1's verified plane, now TRANSPARENT. What shows through is the
// owner's mode wallpaper, set as the actual desktop picture.
let win = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                   backing: .buffered, defer: false)
win.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
win.collectionBehavior = [.managed]
win.animationBehavior = .none
win.isOpaque = false
win.backgroundColor = .clear
win.hasShadow = false

let host = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
host.wantsLayer = true
host.layer?.backgroundColor = NSColor.clear.cgColor
win.contentView = host

let cloudPath = repoRoot() + "/app/island-macos/face.bin"
guard let face = FaceRenderer(cloudPath: cloudPath) else {
    // Say WHAT was looked for. The first failure here printed only "RENDERER
    // FAILED to init", which is true of a missing file, an unreadable file, a
    // Metal device that would not create, and a shader that would not compile.
    print("face: RENDERER FAILED to init")
    print("  cloud path tried : \(cloudPath)")
    print("  exists           : \(FileManager.default.fileExists(atPath: cloudPath))")
    print("  metal device     : \(MTLCreateSystemDefaultDevice() != nil)")
    exit(2)
}

let metal = CAMetalLayer()
metal.device = face.device
metal.pixelFormat = .bgra8Unorm
metal.framebufferOnly = true
metal.isOpaque = false
metal.contentsScale = screen.backingScaleFactor
// The face at home scale: a bust at the centre, per the owner's home reference.
let side = min(screen.frame.width, screen.frame.height) * 0.62
metal.frame = CGRect(x: screen.frame.midX - side / 2,
                     y: screen.frame.midY - side / 2, width: side, height: side)
// THE LINE WHOSE ABSENCE MADE THE FIRST MEASUREMENT MEANINGLESS.
metal.drawableSize = CGSize(width: side * screen.backingScaleFactor,
                            height: side * screen.backingScaleFactor)
// --nosync removes vsync from the loop. If the frame rate jumps, the 29 Hz was
// the compositor's pace and not the renderer's; if it does not, the cost is in
// the draw itself and the CPU figure has been telling the truth all along.
if CommandLine.arguments.contains("--nosync") { metal.displaySyncEnabled = false }
host.layer?.addSublayer(metal)

face.uniforms.aspect = 1
face.uniforms.scale = 1
face.uniforms.alpha = 1
// Nothing of VESPER's sits between the face and the desktop picture, so the pass
// must clear to nothing. At the island's default of 1 this paints a black square
// the size of the layer — which is what the owner saw.
face.clearAlpha = 0

// --verify renders one frame into a texture nobody presents and reads the pixels
// back. "The background is transparent now" should be a reading, not a claim
// about a line of code — this file has already produced five confident wrong
// explanations and does not need a sixth.
if CommandLine.arguments.contains("--verify") {
    let d = MTLTextureDescriptor.texture2DDescriptor(
        pixelFormat: .bgra8Unorm, width: 256, height: 256, mipmapped: false)
    d.usage = [.renderTarget, .shaderRead]
    d.storageMode = .shared
    guard let tex = face.device.makeTexture(descriptor: d) else {
        print("cannot make texture"); exit(2)
    }
    face.uniforms.yaw = 0; face.uniforms.pitch = 0
    face.render(to: tex)

    var px = [UInt8](repeating: 0, count: 256 * 256 * 4)
    px.withUnsafeMutableBytes { raw in
        tex.getBytes(raw.baseAddress!, bytesPerRow: 256 * 4,
                     from: MTLRegionMake2D(0, 0, 256, 256), mipmapLevel: 0)
    }
    func alpha(_ x: Int, _ y: Int) -> Int { Int(px[(y * 256 + x) * 4 + 3]) }
    func lum(_ x: Int, _ y: Int) -> Int {
        let o = (y * 256 + x) * 4
        return (Int(px[o]) + Int(px[o+1]) + Int(px[o+2])) / 3
    }
    let corners = [alpha(2,2), alpha(253,2), alpha(2,253), alpha(253,253)]
    var lit = 0
    for y in stride(from: 0, to: 256, by: 2) {
        for x in stride(from: 0, to: 256, by: 2) where lum(x, y) > 8 { lit += 1 }
    }
    print("")
    print("  corner alpha (0 = transparent) : \(corners)")
    print("  lit samples out of \(128*128)          : \(lit)")
    let bgClear = corners.allSatisfy { $0 == 0 }
    let hasFace = lit > 200
    print("")
    print(bgClear ? "  PASS  background is transparent — no black square"
                  : "  FAIL  background is opaque — the square is still there")
    print(hasFace ? "  PASS  the face is actually in the texture, so the check above is not"
                  + "\n        passing simply because nothing rendered at all"
                  : "  FAIL  nothing rendered — a transparent empty texture proves nothing")
    exit(bgClear && hasFace ? 0 : 1)
}

var angle: Float = 0
// OCCLUSION -- kept, but it was NOT the answer, and the wrong guess is left
// recorded because it was written into this file as if it were one.
//
// The reasoning was: 25 fps at 0.1% CPU is a stalled renderer, not a cheap one;
// CAMetalLayer's drawable pool is small; macOS stops compositing covered
// windows; the probe was launched from a Terminal sitting on top of a window
// that lives at level normal-1 by design. Plausible, and testable, and false.
// The very next run reported the window VISIBLE for 442 of 443 frames and still
// managed 28.8 fps at 0.1% CPU.
//
// What the instrumentation is still worth: 0.1% CPU means this process is
// BLOCKED, not working -- it is asleep inside nextDrawable() waiting for the
// compositor, which is handing out drawables at roughly 29 Hz for a reason not
// yet established. The candidates that remain are the display's own refresh
// rate, Low Power Mode, and vsync itself, and the run now reports the first two
// and can switch off the third with --nosync.
var visibleFrames = 0, occludedFrames = 0
func isVisible() -> Bool { win.occlusionState.contains(.visible) }

// FaceRenderer.draw returns nothing, so "did it draw" is asked of the layer:
// nextDrawable() is the thing that returns nil, and asking for one here would
// consume it. Instead the drawable count is inferred from the renderer running
// to completion, and a stalled layer shows up as a collapsed frame rate --
// which is why fps is reported next to CPU and not instead of it.
// THE FIFTH FAULT, and the first one where the instrument was throttling the
// thing it measured rather than misreading it.
//
// `drawn` counts ATTEMPTS, not successes -- so ~25 frames a second meant the
// DRIVER was only running 25 times a second, and the renderer was never the
// question. The previous version called win.occlusionState and
// proc_pid_rusage() inside every frame. occlusionState is an AppKit property
// that can round-trip to the window server; doing that sixty times a second on
// the main thread is enough to set the frame rate all by itself. Low Power Mode
// and vsync were both eliminated as causes before this was noticed, and neither
// hypothesis was wrong so much as looking in the wrong place.
//
// Occlusion and CPU are now sampled once a second, off the frame path. The draw
// itself is driven by CADisplayLink -- the display's own callback rather than a
// Timer approximating it, which is the correct mechanism regardless of what it
// fixes.
var visibleWall = 0.0, visibleCPU = 0.0
var lastMark = Date(), lastCPU = selfCPUSeconds()

// THE MOTION IS NOT WRITTEN HERE. The owner, on seeing this probe: "the one in
// the expanded island is already good, you can just use it, or maybe copy it if
// it's different?" -- and it is neither used nor copied, because Behaviour.swift
// is compiled into this binary exactly as FaceRenderer.swift already was.
//
// What this file had before was `sinf(angle) * 0.35` for yaw and a cosine for
// pitch, invented on the spot to make something move. FaceDriver is the real
// thing: fourteen behaviours, a breath, blink timing gated on speech, and an
// 80 ms delay line so THE EYES ARRIVE BEFORE THE HEAD -- move them together and
// it reads as a turret. None of that would have survived being reinvented here,
// and a second face with its own motion would have been a second face.
//
// Behaviour.swift imports Foundation and nothing else, so there was never
// anything to port. The face is one renderer and one behaviour, hosted twice.
final class Driver: NSObject {
    let face: FaceRenderer
    let layer: CAMetalLayer
    let motion = FaceDriver()
    var drawn = 0
    init(face: FaceRenderer, layer: CAMetalLayer) {
        self.face = face; self.layer = layer
    }
    @objc func frame() {
        motion.step(1.0 / 60.0)
        face.uniforms.yaw      = motion.headYaw
        face.uniforms.pitch    = motion.headPitch
        face.uniforms.eyeYaw   = motion.eyeYaw
        face.uniforms.eyePitch = motion.eyePitch
        face.uniforms.blink    = motion.blink
        face.uniforms.scale    = 0.96 * motion.breath
        face.draw(in: layer)
        drawn += 1
    }
}
let driver = Driver(face: face, layer: metal)

func sampleState() {
    let now = Date(), cpu = selfCPUSeconds()
    if isVisible() {
        visibleFrames += 1
        visibleWall += now.timeIntervalSince(lastMark)
        visibleCPU += cpu - lastCPU
    } else {
        occludedFrames += 1
    }
    lastMark = now; lastCPU = cpu
}

win.orderFrontRegardless()

let SECS = CommandLine.arguments.contains("--long") ? 40.0 : 15.0
print("""

  VESPER — the face on the ground
  ══════════════════════════════════════════════════════════════════
  \(face.count) points, \(Int(side))x\(Int(side)) at \(screen.backingScaleFactor)x
  = \(Int(side * screen.backingScaleFactor))x\(Int(side * screen.backingScaleFactor)) drawable

  Transparent window at level normal-1. Behind it is your real
  desktop picture — whatever mode you left it on.

  display   : \(screen.maximumFramesPerSecond) Hz max
  low power : \(ProcessInfo.processInfo.isLowPowerModeEnabled)
  vsync     : \(CommandLine.arguments.contains("--nosync") ? "OFF (--nosync)" : "on")

  Measuring \(Int(SECS)) s at 60 fps. Leave the machine alone.

""")

let t0 = Date(), c0 = selfCPUSeconds()
lastMark = t0; lastCPU = c0
let link = host.displayLink(target: driver, selector: #selector(Driver.frame))
link.add(to: .main, forMode: .common)
// Cycle the fourteen so they can be watched rather than described.
var behaviourIndex = 0
let all = Behaviour.allCases
driver.motion.behaviour = all[0]
print("  behaviour: \(all[0].rawValue)")
let cycler = Timer.scheduledTimer(withTimeInterval: 2.5, repeats: true) { _ in
    behaviourIndex = (behaviourIndex + 1) % all.count
    driver.motion.behaviour = all[behaviourIndex]
    print("  behaviour: \(all[behaviourIndex].rawValue)")
}
RunLoop.main.add(cycler, forMode: .common)
let sampler = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in sampleState() }
RunLoop.main.add(sampler, forMode: .common)

DispatchQueue.main.asyncAfter(deadline: .now() + SECS) {
    link.invalidate(); sampler.invalidate(); cycler.invalidate()
    let wall = Date().timeIntervalSince(t0)
    let cpu = (selfCPUSeconds() - c0) / wall * 100
    let drawn = driver.drawn
    let fps = Double(drawn) / wall

    print(String(repeating: "─", count: 66))
    print(String(format: "  frames drawn      %6d over %.1f s  =  %.1f fps overall", drawn, wall, fps))
    print(String(format: "  visible in        %6d of %d one-second samples",
                 visibleFrames, visibleFrames + occludedFrames))
    if visibleWall > 1.0 {
        print(String(format: "  CPU while visible   %5.1f%%", visibleCPU / visibleWall * 100))
    }
    print(String(format: "  CPU overall         %5.1f%%", cpu))
    print("")
    // Occlusion is REPORTED, never a verdict. It was guessed twice as the cause
    // of a low frame rate and disproven twice -- most conclusively by the run
    // that reported occluded in 15 of 15 samples and still held 119.7 fps, the
    // display's full rate. macOS does not throttle this layer for being covered,
    // whatever seemed obvious. The frame rate is the signal; occlusion is
    // context, and the architecture's plan to stop rendering when covered is
    // therefore something VESPER must do deliberately, not something the system
    // will do for it.
    if occludedFrames > visibleFrames {
        print("  (the window was covered for most of this run — reported, not held")
        print("   against the numbers: covered runs have measured the same fps)")
        print("")
    }
    if drawn == 0 {
        print("  ZERO FRAMES. Nothing was measured. This is the failure the first")
        print("  SPIKE-013 run reported as 0.1% CPU and called a reading.")
        exit(1)
    }
    if fps < 45 {
        print(String(format: "  fps is %.0f, well under the 60 asked for — the renderer is not", fps))
        print("  keeping up, so the CPU figure is the cost of falling behind, not")
        print("  the cost of running. Not a usable number.")
        exit(1)
    }
    print("  Comparison: the island measured 5-7% for the same cloud at island")
    print("  size. This is the same \(face.count) points at home scale, so a")
    print("  figure near that is the face being size-insensitive (fill-rate is")
    print("  not the cost, the points are); much higher means it is not.")
    print(String(repeating: "═", count: 66))
    exit(0)
}

app.run()
