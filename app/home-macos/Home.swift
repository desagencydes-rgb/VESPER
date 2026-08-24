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
    /// The plate the face sits on. Owner, 2026-08-24, looking at the face over
    /// the `hall` wallpaper: "add a glass background behind the face... now
    /// it's not well visible."
    ///
    /// NSVisualEffectView with `.behindWindow` is REAL glass and it is public
    /// AppKit -- the window server blurs what is actually behind the window,
    /// which here is the desktop picture itself. Worth saying plainly because
    /// SPIKE-013 SS0 just established there is no public route to a transparent
    /// WKWebView: the CARDS need the hatch, this plate does not.
    let plate = NSVisualEffectView()
    private let plateShadow = NSView()
    /// The measured half of the glass. `NSVisualEffectView` supplies the blur;
    /// this supplies the DARKNESS, and how dark is solved rather than styled.
    /// A SIBLING ABOVE the effect view, not a sublayer inside it. Added to
    /// `plate.layer` the scrim measured as having no effect at all: an
    /// NSVisualEffectView composites its material over its own layer's
    /// sublayers, so a black layer put inside it is painted over by the very
    /// thing it was meant to darken. The reading that caught it was the plate
    /// still measuring luma 0.512 after the fill was solved at 0.757.
    private let scrim = NSView()
    /// The falloff. A FLAT scrim at the solved fill is what the owner saw on
    /// 2026-08-24 and it read as a slab, not as glass -- at 0.757 there is
    /// almost no blurred wallpaper left anywhere on the plate. But the contrast
    /// target only has to be met WHERE THE FACE IS. Outside the face's own
    /// layer the fill can fall away and let the glass be glass, and the point
    /// the falloff starts at is not a taste decision: it is where the face
    /// stops.
    private let fill = CAGradientLayer()

    /// DESIGN-FOUNDATION §4, Dock tier. The floor, never the answer: §3 step 3
    /// says solve until the contrast target is met, and a fill that cannot go
    /// past its tier's nominal value cannot solve anything over a bright
    /// photograph.
    static let dockFill = 0.085
    /// What the face needs behind it. The island's face reads because it sits
    /// on a near-black panel; an ember wireframe over a sunlit limestone lobby
    /// has almost no contrast at all, which is what the owner saw.
    static let faceGroundTarget = 0.12
    /// How much of the centre's fill survives at the plate's rim. Chosen so the
    /// glass is unmistakably glass out there while the panel still reads as one
    /// surface rather than a vignette.
    static let edgeFraction = 0.42

    private func setFill(centre: Double, edge: Double) {
        fill.colors = [
            NSColor(white: 0, alpha: centre).cgColor,
            NSColor(white: 0, alpha: centre).cgColor,
            NSColor(white: 0, alpha: edge).cgColor,
        ]
    }

    private(set) var plateAdapted = false
    private(set) var plateBackdropLuma = 0.0
    private(set) var plateFill = 0.0
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
        // THE PLATE GOES IN FIRST so the face draws over it. Two views rather
        // than one because a corner radius needs `masksToBounds` and a cast
        // shadow is clipped by it -- DESIGN-FOUNDATION SS4 asks for both on every
        // glass tier, so the shadow lives on a container that does not clip.
        let pw = side * 1.16, ph = side * 1.16
        plateShadow.frame = CGRect(x: screen.frame.midX - pw / 2,
                                   y: screen.frame.midY - ph / 2,
                                   width: pw, height: ph)
        plateShadow.wantsLayer = true
        plateShadow.layer?.shadowColor = NSColor.black.cgColor
        plateShadow.layer?.shadowOpacity = 0.28
        plateShadow.layer?.shadowRadius = 34
        plateShadow.layer?.shadowOffset = CGSize(width: 0, height: -8)

        plate.frame = CGRect(origin: .zero, size: CGSize(width: pw, height: ph))
        plate.autoresizingMask = [.width, .height]
        // Dock tier: the heaviest glass in SS4, because this is the largest
        // surface in the composition and the thing every other surface is
        // arranged around (SS14.1). A Sheet-tier blur under a full-screen
        // photograph leaves the photograph legible through it, which is the
        // whole problem being fixed.
        plate.material = .hudWindow
        plate.blendingMode = .behindWindow
        plate.state = .active
        plate.appearance = NSAppearance(named: .darkAqua)
        plate.wantsLayer = true
        plate.layer?.cornerRadius = 34
        plate.layer?.cornerCurve = .continuous
        plate.layer?.masksToBounds = true
        plate.layer?.borderWidth = 1
        plate.layer?.borderColor = NSColor(white: 1, alpha: 0.16).cgColor
        plateShadow.addSubview(plate)

        // THE MEASURED HALF OF THE GLASS, and a SIBLING ABOVE the effect view
        // rather than a sublayer inside it: NSVisualEffectView composites its
        // material over its own layer's sublayers, so a scrim put inside is
        // painted over by the very thing it exists to darken.
        scrim.frame = CGRect(origin: .zero, size: CGSize(width: pw, height: ph))
        scrim.autoresizingMask = [.width, .height]
        scrim.wantsLayer = true
        scrim.layer?.backgroundColor = NSColor.clear.cgColor
        scrim.layer?.cornerRadius = 34
        scrim.layer?.cornerCurve = .continuous
        scrim.layer?.masksToBounds = true
        scrim.layer?.opacity = 1
        fill.frame = CGRect(origin: .zero, size: CGSize(width: pw, height: ph))
        fill.type = .radial
        fill.startPoint = CGPoint(x: 0.5, y: 0.5)
        fill.endPoint = CGPoint(x: 1, y: 1)
        // Where the face's square ends, as a fraction of the plate's half
        // WIDTH.
        //
        // The first version divided by the half DIAGONAL, on the assumption
        // that `endPoint` of (1, 1) reaches the layer's corner. It does not: a
        // CAGradientLayer's radial endPoint describes the layer's INSCRIBED
        // ellipse, so location 1.0 is the half width and everything beyond it,
        // the corners included, is clamped to the last colour. The plateau came
        // out at 245 pt where the face needs 346, the head sat in the falloff,
        // and the fill under it measured 0.216 where 0.124 was predicted.
        //
        // The probe found it because the two routes to that number disagreed --
        // which is the entire reason both are computed.
        fill.locations = [0, NSNumber(value: Double((side / 2) / (pw / 2))), 1]
        scrim.layer?.addSublayer(fill)
        plateShadow.addSubview(scrim, positioned: .above, relativeTo: plate)

        host.addSubview(plateShadow)

        // The specular top edge SS4 asks for on every tier: one hairline of light
        // along the top, which is what makes a panel read as a lit surface
        // rather than as a hole cut in the wallpaper.
        let specular = CALayer()
        specular.frame = CGRect(x: 34, y: ph - 1, width: pw - 68, height: 1)
        specular.backgroundColor = NSColor(white: 1, alpha: 0.30).cgColor
        // On the scrim, which by now HAS a layer. Attached before
        // `wantsLayer` was set, this call went to a nil layer and the hairline
        // simply never existed -- silently, like the scrim itself did for three
        // measurements.
        scrim.layer?.addSublayer(specular)

        host.layer?.addSublayer(metal)
        // Ordering across a subview's layer and a directly-added sublayer is not
        // something to leave to insertion order.
        metal.zPosition = 10

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

        // The notification alone had never once fired -- see OcclusionWatch's
        // header, and SPIKE-013 SS1 criterion 4 for the measurement that found it.
        watch = OcclusionWatch(window: ground)
        watch?.onChange = { [weak self] visible, source in
            guard let self else { return }
            self.occlusionNotifications += 1
            print("  home: ground \(visible ? "visible" : "covered") "
                + "(detected by \(source.rawValue))")
            // The deliberate stop. See the file header: the system will not do
            // this for us, and a home rendering at 120 fps behind a full-screen
            // editor is the exact failure the host-lifetime goal exists to
            // prevent -- measured at 116.8 fps on 2026-08-24, while covered.
            if visible { self.startRendering() } else { self.stopRendering() }
            self.onVisibilityChange?(visible)
        }
        watch?.start()
    }

    private var watch: OcclusionWatch?
    /// What is actually carrying the signal, for whoever writes the report.
    var occlusionProvenance: String { watch?.provenance ?? "no watch" }

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
    var plateRect: CGRect { plateShadow.frame }
    var hostView: NSView { host }
    let chrome = HomeChrome()
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

    /// Counts DELIVERIES, so "the notification never arrived" and "it arrived
    /// and the handler did nothing" can be told apart. They are different
    /// faults with different repairs, and INV-HOME-4 rests on this path.
    private(set) var occlusionNotifications = 0

    @available(*, deprecated, message: "kept only so the old wiring is visibly gone")
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

    /// DESIGN-FOUNDATION §3, steps 1-3 and 5, on the plate behind the face.
    ///
    /// Step 1 samples the backdrop. The rule was written for a webview, where
    /// sampling means reading the screen; here the backdrop is a file VESPER
    /// set itself, so the sample is exact and needs no permission.
    ///
    /// Step 3 solves ONE degree of freedom -- how dark the plate is -- until
    /// the face has a ground it can be seen against. Compositing black at
    /// `a` over a backdrop of luminance `L` leaves `L * (1 - a)`, so the fill
    /// that hits a target is `1 - target/L` and nothing about that is a taste
    /// decision. A bright backdrop gets more scrim, a dark one gets less, and
    /// on a wallpaper already darker than the target the tier's own .085 is
    /// what remains.
    ///
    /// Step 5 fails closed: an unsampleable backdrop is UNKNOWN, and UNKNOWN
    /// does not get treated as a good value. It takes the tier's nominal fill
    /// and says it is unadapted, rather than guessing a number that would look
    /// measured.
    @discardableResult
    func adaptPlate(toBackdrop url: URL?) -> Bool {
        guard let url,
              let st = Ambience.backdropStats(url: url, region: plateShadow.frame,
                                              screen: screen) else {
            setFill(centre: Self.dockFill, edge: Self.dockFill)
            plateAdapted = false
            plateBackdropLuma = 0
            plateFill = Self.dockFill
            return false
        }
        let a = min(0.88, max(Self.dockFill,
                              1 - Self.faceGroundTarget / max(st.mean, 0.001)))
        // The edge keeps enough fill to hold the panel's shape and its border,
        // and no more. Below the tier's own .085 it would stop being a surface.
        setFill(centre: a, edge: max(Self.dockFill, a * Self.edgeFraction))
        plateAdapted = true
        plateBackdropLuma = st.mean
        plateFill = a
        return true
    }

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
        let ok = Ambience.apply(m, on: screen, quiet: quiet)
        // The plate is adapted to the picture that is now behind it, not to the
        // one that was there when the process started.
        let url = Ambience.wallpaperDir().flatMap { m.wallpaper(in: $0) }
        let adapted = adaptPlate(toBackdrop: url)
        if !quiet {
            print(adapted
                  ? String(format: "  plate: backdrop luma %.3f → fill %.3f → face ground %.3f",
                           plateBackdropLuma, plateFill,
                           plateBackdropLuma * (1 - plateFill))
                  : "  plate: backdrop UNSAMPLED — tier fill \(Self.dockFill), unadapted")
        }
        return ok
    }
}
