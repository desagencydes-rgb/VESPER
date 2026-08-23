// VESPER's home — the ground plane, inside VESPER.app.
//
// WHY THIS IS IN THE ISLAND'S PROCESS AND NOT ITS OWN.
//
// Three reasons, and the second is the one that would be expensive to get
// wrong later:
//
//  1. TCC. A permission granted to a loose binary is granted to the TERMINAL
//     that launched it. Bundling is the whole point of VESPER.app, and a
//     second executable dropped into Contents/MacOS/ is signed as a resource
//     of the bundle rather than as code with its own identity -- so it would
//     re-open exactly the question the bundle was built to close.
//
//  2. §2.6 needs ONE signal, not an IPC channel. "The island's visibility is
//     the inverse of the ground's occlusion state." In one process that is a
//     notification on a window we own. Across two it is a transport, a
//     liveness question, and a race -- new mechanism for a rule the
//     architecture explicitly says needs none.
//
//  3. One face at a time (§8) becomes structurally true. Island and home
//     never draw together because the same object decides which one is
//     drawing.
//
// THE FINDING THIS FILE IS BUILT AROUND, measured 2026-08-23: macOS does NOT
// throttle a covered window's Metal layer. A run reported the ground occluded
// in 15 of 15 samples and held 117.9 fps -- the display's full rate, behind
// whatever the owner was actually looking at. HOME-ARCHITECTURE §10 has
// occlusion driving three rules and the first is "stop rendering"; the system
// will not do that for us. So the ground stops DELIBERATELY, here, and the
// host's lifetime is the product.

import AppKit
import Metal

final class HomeController: NSObject {

    let screen: NSScreen
    let ground: NSWindow
    let host: NSView
    let face: FaceRenderer
    let metal: CAMetalLayer
    let motion = FaceDriver()

    /// §2.6, published for whoever owns the island. `true` means the owner is
    /// looking at the home, which is exactly when the island must not be
    /// there. Fired on the real notification, never inferred from a timer.
    var onVisibilityChange: ((Bool) -> Void)?

    /// Counts ATTEMPTS, not successes -- and that distinction is the whole
    /// reason the first face measurement was meaningless. A stalled renderer
    /// and a cheap one both report low CPU; only the frame count separates
    /// them.
    private(set) var framesDrawn = 0
    private(set) var rendering = false
    private var link: Any?          // CADisplayLink (14+) or Timer
    private var lastFrame = Date()

    init?(screen: NSScreen) {
        self.screen = screen

        // The plane F1 verified: below normal, Managed, the whole frame, and
        // TRANSPARENT -- the mode picture is the real desktop picture now, so
        // nothing of ours sits between the face and the window server's own
        // desktop.
        ground = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                          backing: .buffered, defer: false)
        ground.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
        ground.collectionBehavior = [.managed]
        // The ground does not animate into existence. Two reasons, and the
        // product one comes first: this window IS the desktop, and a desktop
        // that springs in from 99% is imitating a dialog. The other is that
        // the spring OVERSHOOTS -- ground_probe read 1730x1117 at (-1, 0) on a
        // 1728x1117 screen, and two consecutive samples agree at its apex, so
        // the animation can defeat a settle detector as well as the eye.
        ground.animationBehavior = .none
        ground.isOpaque = false
        ground.backgroundColor = .clear
        ground.hasShadow = false
        ground.ignoresMouseEvents = false

        host = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
        host.wantsLayer = true
        host.layer?.backgroundColor = NSColor.clear.cgColor
        ground.contentView = host

        // face.bin is the same cloud the island draws. `resourcePath` prefers
        // the bundle and falls back to the repo, so the dev loop and the
        // installed app read the same file by different routes.
        let cloud = resourcePath("face.bin", devFallback: "app/island-macos/face.bin")
        guard let f = FaceRenderer(cloudPath: cloud) else {
            // Say WHAT was looked for. "RENDERER FAILED to init" is equally
            // true of a missing file, an unreadable one, a Metal device that
            // would not create, and a shader that would not compile.
            print("home: FaceRenderer FAILED to init")
            print("  cloud path tried : \(cloud)")
            print("  exists           : \(FileManager.default.fileExists(atPath: cloud))")
            print("  metal device     : \(MTLCreateSystemDefaultDevice() != nil)")
            return nil
        }
        face = f

        metal = CAMetalLayer()
        metal.device = face.device
        metal.pixelFormat = .bgra8Unorm
        metal.framebufferOnly = true
        metal.isOpaque = false
        metal.contentsScale = screen.backingScaleFactor
        // The face as a bust at the centre -- the owner's home reference,
        // §14.1. The rail and the transcript line arrive with the chrome.
        let side = min(screen.frame.width, screen.frame.height) * 0.62
        metal.frame = CGRect(x: screen.frame.midX - side / 2,
                             y: screen.frame.midY - side / 2,
                             width: side, height: side)
        // THE LINE WHOSE ABSENCE MADE THE FIRST MEASUREMENT MEANINGLESS.
        // Without it nextDrawable() returns nil, every draw is a silent no-op,
        // and the run reports 0.1% CPU for a renderer that never ran.
        metal.drawableSize = CGSize(width: side * screen.backingScaleFactor,
                                    height: side * screen.backingScaleFactor)
        host.layer?.addSublayer(metal)

        face.uniforms.aspect = 1
        face.uniforms.alpha = 1
        // Derived from THIS layer, not inherited from the island's. See
        // FaceUniforms.pointSize -- the same cloud over a 3x wider layer is a
        // third of the density, and a face that renders and cannot be seen.
        face.uniforms.pointSize = FaceUniforms.pointSize(forLayerWidth: side)
        // Nothing of VESPER's is between the face and the desktop picture, so
        // the pass clears to nothing. At the island's default of 1 this paints
        // a black square the size of the layer, which is what the owner saw.
        face.clearAlpha = 0

        super.init()

        NotificationCenter.default.addObserver(
            self, selector: #selector(occlusionChanged),
            name: NSWindow.didChangeOcclusionStateNotification, object: ground)
    }

    var isVisible: Bool { ground.occlusionState.contains(.visible) }

    /// Where the face's layer sits, for whoever needs to READ that region
    /// rather than trust that something was drawn into it.
    var faceRect: CGRect { metal.frame }

    /// Re-lay the face at a different width, point size derived to match.
    ///
    /// This exists for the DENSITY BENCH and not for the product. The claim
    /// that point size should scale with the layer is a claim about two
    /// surfaces, and the island cannot be used as the second one: its panel is
    /// opaque, so a reader that measures paint measures the panel and returns
    /// 100% whatever the face does. Rendering both widths in THIS window --
    /// transparent, one reader, one run -- is what makes the comparison mean
    /// something.
    func setFaceWidth(_ w: CGFloat) {
        let side = max(1, w)
        metal.frame = CGRect(x: screen.frame.midX - side / 2,
                             y: screen.frame.midY - side / 2,
                             width: side, height: side)
        metal.drawableSize = CGSize(width: side * screen.backingScaleFactor,
                                    height: side * screen.backingScaleFactor)
        face.uniforms.pointSize = FaceUniforms.pointSize(forLayerWidth: side)
    }
    var groundWindow: NSWindow { ground }
    var faceTint: (Float, Float, Float) {
        (face.uniforms.tintR, face.uniforms.tintG, face.uniforms.tintB)
    }

    // MARK: - Presence

    /// Order the ground front. NOT a placement mechanism: this window is
    /// `.managed`, so it lands on whichever Desktop is active when it is
    /// created, and residency is the caller's problem (§2.3a, switch first,
    /// then create).
    func present() {
        ground.orderFrontRegardless()
        // `orderFrontRegardless` returning is not a window appearing. The
        // compositor has not necessarily placed it when this call comes back,
        // and a sampler started here reads a world that does not yet contain
        // the thing it is sampling -- which is exactly the phantom dropout
        // that cost a run.
        waitUntilComposited { [weak self] in
            guard let self else { return }
            self.startRendering()
            self.onVisibilityChange?(self.isVisible)
        }
    }

    /// Poll the window server, not ourselves, for whether the ground is on
    /// screen. Gives up rather than hanging: a ground that never composites is
    /// a fault to report, not a wait to extend.
    private func waitUntilComposited(_ then: @escaping () -> Void, attemptsLeft: Int = 40) {
        if SpaceWatch.onScreen().contains(where: { $0.number == Int(ground.windowNumber) })
            || attemptsLeft <= 0 {
            then(); return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
            self.waitUntilComposited(then, attemptsLeft: attemptsLeft - 1)
        }
    }

    @objc private func occlusionChanged() {
        let v = isVisible
        // The deliberate stop. See the file header: the system will not do
        // this, and a home rendering at 120 fps behind a full-screen editor is
        // the exact failure the host-lifetime goal exists to prevent.
        if v { startRendering() } else { stopRendering() }
        onVisibilityChange?(v)
    }

    // MARK: - The frame

    func startRendering() {
        guard !rendering else { return }
        rendering = true
        lastFrame = Date()
        if #available(macOS 14.0, *) {
            let l = host.displayLink(target: self, selector: #selector(frame))
            l.add(to: .main, forMode: .common)
            link = l
        } else {
            // Worse instrument, and named as one: a Timer approximating vsync
            // rather than the display's own callback. It is here because
            // Info.plist claims LSMinimumSystemVersion 13.0, and a claim the
            // binary cannot honour is worse than a degraded frame source.
            let t = Timer.scheduledTimer(timeInterval: 1.0 / 60.0, target: self,
                        selector: #selector(frame), userInfo: nil, repeats: true)
            RunLoop.main.add(t, forMode: .common)
            link = t
        }
    }

    func stopRendering() {
        guard rendering else { return }
        rendering = false
        if #available(macOS 14.0, *), let l = link as? CADisplayLink { l.invalidate() }
        else if let t = link as? Timer { t.invalidate() }
        link = nil
    }

    @objc private func frame() {
        // Real elapsed time, not the nominal 1/60. The display runs at 120 Hz
        // here and a fixed step would make every behaviour play at half speed
        // on one machine and full speed on another -- a motion vocabulary that
        // depends on the panel it lands on is not a vocabulary.
        let now = Date()
        let dt = min(now.timeIntervalSince(lastFrame), 0.1)
        lastFrame = now
        motion.step(dt)
        face.uniforms.yaw      = motion.headYaw
        face.uniforms.pitch    = motion.headPitch
        face.uniforms.eyeYaw   = motion.eyeYaw
        face.uniforms.eyePitch = motion.eyePitch
        face.uniforms.blink    = motion.blink
        face.uniforms.scale    = 0.96 * motion.breath
        face.draw(in: metal)
        framesDrawn += 1
    }

    // MARK: - Ambience

    /// Set the mode. The picture is the Space's own desktop picture, so this
    /// changes whichever Desktop is active -- the caller owns residency.
    @discardableResult
    func setMode(_ name: String, quiet: Bool = false) -> Bool {
        guard let m = Ambience.mode(named: name) else {
            if !quiet { print("  no mode named '\(name)'") }
            return false
        }
        // The face takes the mode's accent. It was derived from the light
        // source of the very picture now behind it, which is why they agree.
        if let c = m.accent.usingColorSpace(.sRGB) {
            face.uniforms.tintR = Float(c.redComponent)
            face.uniforms.tintG = Float(c.greenComponent)
            face.uniforms.tintB = Float(c.blueComponent)
        }
        return Ambience.apply(m, on: screen, quiet: quiet)
    }
}
