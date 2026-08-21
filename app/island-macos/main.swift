// The island — the macOS shell.
//
// PUBLIC API ONLY, DELIBERATELY. The owner's requirement is that this reads as a
// feature of the operating system and is never harmed by an OS update. Those two
// only hold together on supported surfaces: an NSPanel at a documented window
// level, and NSScreen's own notch geometry. Nothing here reaches for a private
// interface, and nothing may start to -- a private call keeps working for three
// releases and then removes the island the morning after an update, with no
// compile error and no failing test to notice it.
//
// GEOMETRY IS ASKED FOR, NEVER ASSUMED. `safeAreaInsets` and the auxiliary top
// areas report the ACTUAL display. The 185 pt / 32 pt figures in
// docs/design/ANNEX-island-geometry.md are what this machine happens to answer,
// not constants to trust -- a build that hardcodes 185 is a build pinned to one
// laptop, which is exactly what INV-PLACE-3 refuses.

import AppKit
import QuartzCore
import ServiceManagement

// MARK: - Geometry, from docs/design/ANNEX-island-geometry.md

// Renamed 2026-08-21 on the owner's reading of the two expanded references: the
// instrument-panel one IS Hanging, reached on hover, and Expanded is the one with
// the face, reached on click. That also settles the §10 incoherence where Hanging
// was specced at 720 wide -- WIDER than the measured Expanded at 624. It is the
// same width; only the body and the height differ.
enum State: Int { case dormant, shoulders, hanging, expanded }

struct Metrics {
    var width: CGFloat, height: CGFloat, fillet: CGFloat, radius: CGFloat
}

final class Geometry {
    let notch: CGFloat          // measured off the display, not declared
    let inset: CGFloat
    let hasNotch: Bool

    init(screen: NSScreen) {
        let f = screen.frame
        if let l = screen.auxiliaryTopLeftArea, let r = screen.auxiliaryTopRightArea {
            notch = f.width - l.width - r.width
            hasNotch = true
        } else {
            // No notch: an external display, or a Mac without one. The island is
            // a built-in-display component -- see ISLAND-ARCHITECTURE.md §5 --
            // so this is a real answer, not a fallback to pretend with.
            notch = 0
            hasNotch = false
        }
        inset = screen.safeAreaInsets.top > 0 ? screen.safeAreaInsets.top : 32
    }

    func metrics(_ s: State) -> Metrics {
        switch s {
        // Dormant IS the notch. Not "hidden" -- a state, so nothing ever
        // unmounts and remounts and flickers the illusion away.
        case .dormant:   return Metrics(width: notch, height: inset, fillet: 0, radius: 12)
        // 2 x the notch, built as the relationship. If a display reports a
        // different notch this follows it, and 370 was never the point.
        case .shoulders: return Metrics(width: notch * 2, height: inset + 16, fillet: 12, radius: 16)
        // One width across both expanded bodies; it grows downward only.
        case .hanging:  return Metrics(width: 624, height: 192, fillet: 24, radius: 24)
        case .expanded: return Metrics(width: 624, height: 280, fillet: 24, radius: 48)
        }
    }
}

// MARK: - The shape

// The panel flows OUT of the bezel rather than butting into it: an inverted
// fillet at each side where it meets the bezel line, top radius 0 always. One
// point of air at the top edge kills the illusion the whole component rests on.
//
// Corners here are circular arcs. The annex asks for CONTINUOUS corners, because
// this display's own corners are continuous and a circular corner reads as a
// sticker stuck on the screen rather than part of it. At these radii the
// difference is small but real, and it is the first refinement to make.
func islandPath(w: CGFloat, h: CGFloat, fillet f: CGFloat, radius r0: CGFloat) -> CGPath {
    let p = CGMutablePath()
    let r = min(r0, h / 2, (w - 2 * f) / 2)
    let bodyL = f, bodyR = w - f
    p.move(to: CGPoint(x: 0, y: h))                                  // top-left, at the bezel
    if f > 0 {                                                       // inverted fillet, concave into the panel
        p.addArc(center: CGPoint(x: 0, y: h - f), radius: f,
                 startAngle: .pi / 2, endAngle: 0, clockwise: true)
    }
    p.addLine(to: CGPoint(x: bodyL, y: r))
    p.addArc(center: CGPoint(x: bodyL + r, y: r), radius: r,
             startAngle: .pi, endAngle: .pi * 1.5, clockwise: false)
    p.addLine(to: CGPoint(x: bodyR - r, y: 0))
    p.addArc(center: CGPoint(x: bodyR - r, y: r), radius: r,
             startAngle: .pi * 1.5, endAngle: .pi * 2, clockwise: false)
    p.addLine(to: CGPoint(x: bodyR, y: h - f))
    if f > 0 {
        p.addArc(center: CGPoint(x: w, y: h - f), radius: f,
                 startAngle: .pi, endAngle: .pi / 2, clockwise: true)
    }
    p.closeSubpath()                                                 // along the bezel line
    return p
}

// MARK: - Spring

// --snappy, the default: SwiftUI Spring(duration: 0.5, bounce: 0.15). The four
// springs plus the Dock magnification falloff are the ENTIRE motion vocabulary
// until the owner adds to it, so this is not a place to invent an easing curve.
final class Spring {
    private var v: CGFloat = 0
    var value: CGFloat
    var target: CGFloat
    private let k: CGFloat, c: CGFloat
    init(_ x: CGFloat, duration: CGFloat = 0.5, bounce: CGFloat = 0.15) {
        value = x; target = x
        let omega = 2 * .pi / duration
        k = omega * omega
        c = 2 * omega * (1 - bounce)
    }
    func step(_ dt: CGFloat) -> Bool {
        let a = k * (target - value) - c * v
        v += a * dt
        value += v * dt
        if abs(target - value) < 0.05 && abs(v) < 0.05 { value = target; v = 0; return false }
        return true
    }
}

// MARK: - The mark is alive

// Owner addition to the motion vocabulary, 2026-08-21. See DESIGN-FOUNDATION §6.
// Each state owns ONE channel -- speaking and thinking move scale, working moves
// lightness -- because a state that both pulsed and brightened would read as a
// third state at 20 pt across a room.
enum Presence: String { case idle, thinking, working, speaking }

final class MarkAnimator {
    var presence: Presence = .idle
    // Set by the audio path. NOT a synthesised waveform: a sine pretending to be
    // speech is the same failure as a status column reading 41 C on a host with
    // no thermometer -- it looks like data and is not. With no audio, `level`
    // stays 0, the mark does not move, and that is the honest render.
    var level: CGFloat = 0
    var synthetic = false          // --demo only, and it says so on stdout

    private var t: CGFloat = 0
    private var env: CGFloat = 0   // envelope follower, so speaking tracks rather than jitters

    var animates: Bool { presence != .idle }

    func step(_ dt: CGFloat) -> (scale: CGFloat, brightness: CGFloat) {
        t += dt
        switch presence {
        case .idle:
            env = 0
            return (1, 1)
        case .thinking:
            // Slow and clean. No bounce: this is the one motion that must not
            // look eager, because it is what VESPER shows while it has nothing
            // to say yet.
            return (1 + 0.055 * sin(2 * .pi * t / 2.4), 1)
        case .working:
            // Size holds still; only brightness breathes. Consistent period, no
            // drift -- "slowly and consistently" is the requirement.
            return (1, 0.60 + 0.40 * (0.5 + 0.5 * sin(2 * .pi * t / 3.0)))
        case .speaking:
            let target = synthetic
                ? max(0, sin(2 * .pi * t * 3.1) * 0.5 + 0.5) * (0.55 + 0.45 * sin(2 * .pi * t * 0.7))
                : level
            // Fast attack, slower release: how a voice actually reads.
            let k: CGFloat = target > env ? 26 : 11
            env += (target - env) * min(1, k * dt)
            return (1 + 0.22 * env, 1)
        }
    }
}

// MARK: - What the island is allowed to say

// A column read from the projection snapshot. There is NO initialiser that
// produces a value without provenance, mirroring core/projection.py: the whole
// point of that module is that "41 °C" cannot be invented by the surface that
// wants a column to look full. Anything unavailable never reaches this type --
// the projection omits it before it is written.
struct Column {
    let label: String
    let value: String
}

struct GaugeReading { let label: String; let value: CGFloat }
struct PanelItem { let label: String; let value: String; let ratio: CGFloat? }

func loadPanel(_ path: String) -> [PanelItem] {
    guard let data = FileManager.default.contents(atPath: path),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let items = obj["panel"] as? [[String: Any]] else { return [] }
    return items.compactMap { d in
        guard let l = d["label"] as? String, let v = d["value"] as? String else { return nil }
        let r = d["ratio"] as? Double
        return PanelItem(label: l, value: v, ratio: r.map { CGFloat(max(0, min(1, $0))) })
    }
}

func loadGauges(_ path: String) -> [GaugeReading] {
    guard let data = FileManager.default.contents(atPath: path),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let items = obj["gauges"] as? [[String: Any]] else { return [] }
    return items.compactMap { d in
        guard let l = d["label"] as? String, let v = d["value"] as? Double else { return nil }
        return GaugeReading(label: l, value: CGFloat(max(0, min(1, v))))
    }
}

func loadColumns(_ path: String) -> [Column] {
    guard let data = FileManager.default.contents(atPath: path),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let items = obj["columns"] as? [[String: Any]] else { return [] }
    return items.compactMap { d in
        guard let l = d["label"] as? String, let v = d["value"] as? String else { return nil }
        return Column(label: l, value: v)
    }
}

// MARK: - The view

final class IslandView: NSView {
    var state: State = .dormant
    var metrics = Metrics(width: 185, height: 32, fillet: 0, radius: 12)
    var columns: [Column] = []
    var mark: NSImage?
    var markScale: CGFloat = 1
    var markBrightness: CGFloat = 1
    // Empty until something real produces them. The three fixed fractions that
    // used to be drawn here were shape wearing the costume of data. A gauge that
    // has no producer is ABSENT, never a ring resting at zero -- zero-because-
    // untracked and zero-because-unspent look identical and are opposite facts.
    var gauges: [GaugeReading] = []
    var panel: [PanelItem] = []

    // The shell is #000000, NOT our black. #03141f is a very dark blue-teal and,
    // welded to the true-black camera housing beside it, reads as a lighter
    // patch. Our black is used one step in, as the ground contents sit on --
    // and that is what the owner's own reference measures, 16129 px of it.
    static let shell  = NSColor.black
    static let ground = NSColor(srgbRed: 0x03/255.0, green: 0x14/255.0, blue: 0x1f/255.0, alpha: 1)
    static let ink    = NSColor(srgbRed: 0.93, green: 0.92, blue: 0.90, alpha: 1)
    static let dim    = NSColor(srgbRed: 0.62, green: 0.60, blue: 0.58, alpha: 1)
    static let ember  = NSColor(srgbRed: 0xB9/255.0, green: 0x66/255.0, blue: 0x45/255.0, alpha: 1)

    override var isFlipped: Bool { false }
    var onClick: (() -> Void)?
    override func mouseDown(with event: NSEvent) { onClick?() }

    override func draw(_ dirtyRect: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        let w = bounds.width, h = bounds.height
        let path = islandPath(w: w, h: h, fillet: metrics.fillet, radius: metrics.radius)

        ctx.saveGState()
        ctx.addPath(path); ctx.clip()
        ctx.setFillColor(IslandView.shell.cgColor)
        ctx.fill(bounds)

        switch state {
        case .dormant:   break                       // it IS the notch. Nothing to say.
        case .shoulders: drawShoulders(ctx, w: w, h: h)
        case .hanging, .expanded: drawExpanded(ctx, w: w, h: h)
        }
        ctx.restoreGState()
    }

    private func text(_ s: String, _ size: CGFloat, _ color: NSColor, weight: NSFont.Weight = .regular) -> NSAttributedString {
        // Type is NOT decided -- DESIGN-FOUNDATION §11 lists sizes and weights as
        // open. The system face at these sizes is a placeholder that reads
        // correctly, not a decision being made here by default.
        NSAttributedString(string: s, attributes: [
            .font: NSFont.systemFont(ofSize: size, weight: weight),
            .foregroundColor: color])
    }

    // The shoulder row must clear the camera: anything in the band y ∈ [0, inset]
    // stays off the middle. The owner's own shoulders reference does this -- 0 px
    // of ink inside the notch's x-range -- while both expanded references do not.
    private func drawShoulders(_ ctx: CGContext, w: CGFloat, h: CGFloat) {
        let pad = metrics.fillet + 14
        if let m = mark {
            // The mark carries VESPER's state in every island state -- it is the
            // only mark on screen most of the time, so presence lives here.
            let s: CGFloat = markSize * markScale
            m.draw(in: NSRect(x: pad + (markSize - s) / 2, y: (h - s) / 2, width: s, height: s),
                   from: .zero, operation: .sourceOver, fraction: markBrightness)
        }
        drawGauges(ctx, w: w, h: h, cy: h / 2, ring: 15, showValue: false)
    }

    /// The three budgets VESPER spends on the owner's behalf: attention, spend,
    /// machine. Chosen because macOS shows none of them anywhere -- the menu bar
    /// already has the battery and the clock, so a gauge spent on those is wasted.
    private func drawGauges(_ ctx: CGContext, w: CGFloat, h: CGFloat,
                            cy: CGFloat, ring: CGFloat, showValue: Bool) {
        guard !gauges.isEmpty else { return }
        let gap: CGFloat = showValue ? 16 : 9
        let n = CGFloat(gauges.count)
        var x = w - metrics.fillet - 14 - (ring * n + gap * (n - 1))
        for g in gauges {
            let rect = NSRect(x: x, y: cy - ring / 2, width: ring, height: ring)
            ctx.setLineWidth(showValue ? 2.4 : 2)
            ctx.setStrokeColor(NSColor(white: 1, alpha: 0.16).cgColor)
            ctx.addEllipse(in: rect.insetBy(dx: 1, dy: 1)); ctx.strokePath()
            ctx.setStrokeColor(IslandView.ember.cgColor)
            // Clockwise from twelve, so a fuller ring reads as more spent.
            ctx.addArc(center: NSPoint(x: rect.midX, y: rect.midY), radius: ring / 2 - 1,
                       startAngle: .pi / 2, endAngle: .pi / 2 - 2 * .pi * g.value,
                       clockwise: true)
            ctx.strokePath()
            if showValue {
                let v = text("\(Int((g.value * 100).rounded()))", 9, IslandView.ink, weight: .medium)
                v.draw(at: NSPoint(x: rect.midX - v.size().width / 2, y: rect.midY - 5))
                let l = text(g.label, 8, IslandView.dim)
                l.draw(at: NSPoint(x: rect.midX - l.size().width / 2, y: rect.minY - 12))
            }
            x += ring + gap
        }
    }

    private func drawExpanded(_ ctx: CGContext, w: CGFloat, h: CGFloat) {
        let inset = metrics.fillet
        drawGauges(ctx, w: w, h: h, cy: h - safeInset / 2 - 3, ring: 19, showValue: true)
        // §9: the mark is on the left shoulder in EVERY island state, and the
        // shoulder band is y ∈ [0, inset] -- the one band that must clear the
        // camera. The mark sits far left, so it does; nothing else goes here.
        if let m = mark {
            let s: CGFloat = markSize * markScale
            m.draw(in: NSRect(x: inset + 14 + (markSize - s) / 2,
                              y: h - safeInset + (safeInset - s) / 2, width: s, height: s),
                   from: .zero, operation: .sourceOver, fraction: markBrightness)
        }
        // THE STATUS ROW STARTS AT THE SAFE INSET, not where the composites put
        // it. Both expanded references place their first ink 8.6 pt too high, so
        // three of six columns land under the physical camera. Canva has no
        // camera; this display does.
        let rowTop = h - safeInset
        let colW = (w - inset * 2) / CGFloat(max(columns.count, 1))

        for (i, c) in columns.enumerated() {
            let x = inset + CGFloat(i) * colW
            let label = text(c.label, 10.5, IslandView.ink, weight: .medium)
            // The reference's second line is ember, not grey. It is the line that
            // carries the actual reading, and it is coloured like the mark.
            let value = text(c.value, 9, IslandView.ember)
            label.draw(at: NSPoint(x: x + (colW - label.size().width) / 2, y: rowTop - 15))
            value.draw(at: NSPoint(x: x + (colW - value.size().width) / 2, y: rowTop - 28))
        }

        // The ground, one step in.
        let bodyTop = rowTop - 38
        let body = NSRect(x: inset + 8, y: 14, width: w - (inset + 8) * 2, height: bodyTop - 14)
        // Expanded puts its content on the shell; only Hanging has the inner
        // ground panel. Measured from the two references, not assumed alike.
        if state == .hanging, body.height > 20 {
            let rr = CGPath(roundedRect: body, cornerWidth: 18, cornerHeight: 18, transform: nil)
            ctx.addPath(rr)
            ctx.setFillColor(IslandView.ground.cgColor)
            ctx.fillPath()
            if !panel.isEmpty {
                drawPanel(ctx, in: body)
            } else if columns.isEmpty {
                // Nothing is wired yet, and an empty body says so rather than
                // showing a plausible instrument panel. INV-HW-2: UNKNOWN means
                // UNAVAILABLE, and a surface that renders stale or invented state
                // is worse than one that renders none.
                let msg = text("no projection — backend not running", 10, IslandView.dim)
                msg.draw(at: NSPoint(x: body.midX - msg.size().width / 2, y: body.midY - 6))
            }
        }
    }

    /// The instrument panel: what the host is actually doing, on the #03141f
    /// ground. One row of readings, because the reference's bar list is horizontal
    /// and a grid at this height would put four labels in 54 pt of space.
    ///
    /// ONLY GENUINE RATIOS GET A BAR. `Thermal` is a level -- nominal, fair,
    /// serious -- and a bar under it would invent an ordering with a magnitude the
    /// platform never claimed.
    private func drawPanel(_ ctx: CGContext, in body: NSRect) {
        let n = CGFloat(panel.count)
        let cell = body.width / n
        for (i, item) in panel.enumerated() {
            let x = body.minX + CGFloat(i) * cell
            let mid = x + cell / 2
            let l = text(item.label, 9, IslandView.dim)
            l.draw(at: NSPoint(x: mid - l.size().width / 2, y: body.maxY - 26))
            let v = text(item.value, 13, IslandView.ink, weight: .medium)
            v.draw(at: NSPoint(x: mid - v.size().width / 2, y: body.maxY - 46))
            if let r = item.ratio {
                let bw = cell - 44, bx = mid - bw / 2, by = body.maxY - 58
                ctx.setFillColor(NSColor(white: 1, alpha: 0.12).cgColor)
                ctx.fill(NSRect(x: bx, y: by, width: bw, height: 3))
                ctx.setFillColor(IslandView.ember.cgColor)
                ctx.fill(NSRect(x: bx, y: by, width: bw * r, height: 3))
            }
            if i > 0 {   // hairline between readings, as the reference divides them
                ctx.setFillColor(NSColor(white: 1, alpha: 0.07).cgColor)
                ctx.fill(NSRect(x: x, y: body.minY + 14, width: 1, height: body.height - 34))
            }
        }
    }

    var safeInset: CGFloat = 32
    // Raised from 20 pt on the owner's note that it read too small. The mark is
    // the only thing on screen most of the time, so it carries more than a glyph.
    var markSize: CGFloat = 26
}

/// Resources live in the bundle once VESPER is an app, and in the repo when the
/// binary is run bare during development. Both paths are supported deliberately:
/// the bundle is what the owner's Mac must see -- TCC grants are keyed to app
/// identity, so a permission granted to a loose binary is granted to the TERMINAL
/// and does not transfer -- while the bare path keeps the edit-build-look loop
/// short.
func resourcePath(_ name: String, devFallback: String) -> String {
    if let r = Bundle.main.resourcePath {
        let p = (r as NSString).appendingPathComponent(name)
        if FileManager.default.fileExists(atPath: p) { return p }
    }
    return FileManager.default.currentDirectoryPath + "/" + devFallback
}

// MARK: - The panel

final class IslandPanel: NSPanel {
    // Non-activating is the whole point: the island is presence, not a window.
    // Clicking it must never steal focus from what the owner is actually doing.
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class Controller: NSObject {
    let panel: IslandPanel
    let view: IslandView
    let geo: Geometry
    let screen: NSScreen
    var state: State = .dormant
    private let sw: Spring, sh: Spring
    private var timer: Timer?
    private var markTimer: Timer?
    private var tracking: NSTrackingArea?
    let anim = MarkAnimator()
    let driver = FaceDriver()
    private var face: FaceRenderer?
    private let faceLayer = CAMetalLayer()
    // The island's own silhouette, as a mask on the whole view. The Metal layer is
    // a rectangle and its corners were poking out past the shell's rounded bottom
    // -- reported by the owner 2026-08-21 as "a black rectangle with sharp edges".
    // Rounding the sublayer's own corners would only hide it at one size; masking
    // the view to the real path means NOTHING can escape the shell, at any state,
    // at any point mid-animation.
    private let shellMask = CAShapeLayer()
    private var faceTimer: Timer?
    private let snapshotPath: String

    init(screen: NSScreen, snapshotPath: String, levelKey: CGWindowLevelKey = .statusWindow) {
        self.screen = screen
        self.snapshotPath = snapshotPath
        geo = Geometry(screen: screen)
        let m = geo.metrics(.dormant)
        sw = Spring(m.width); sh = Spring(m.height)
        view = IslandView()
        view.safeInset = geo.inset
        view.mark = NSImage(contentsOfFile: resourcePath("vesper-icon.png",
                            devFallback: "docs/design/assets/vesper-icon.png"))

        panel = IslandPanel(contentRect: NSRect(x: 0, y: 0, width: m.width, height: m.height),
                            styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        super.init()

        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovable = false
        // NSPanel defaults hidesOnDeactivate to TRUE, unlike NSWindow. Switching
        // Space deactivates the app, so the island vanished for the length of the
        // transition -- reported by the owner 2026-08-21. The island is presence:
        // it is there whenever VESPER is running, and "the owner looked at another
        // Space" is not a reason for VESPER to stop existing.
        panel.hidesOnDeactivate = false
        // Floating panels are exempt from some of the window server's transition
        // handling, which is the other half of surviving a Space switch cleanly.
        panel.isFloatingPanel = true
        panel.ignoresMouseEvents = false
        // Above the menu bar, and it stays there. Documented level, not a magic
        // number: the same one every menu-bar utility uses.
        panel.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(levelKey)) + 1)
        // .canJoinAllSpaces puts the panel on EVERY Space. .stationary keeps it
        // from being swept up in Exposé and Space transitions.
        //
        // .fullScreenAuxiliary is deliberately NOT here by default. It means "this
        // window may appear on the same Space as a full-screen window" -- it makes
        // the panel AUXILIARY TO THAT WINDOW, joining its Space rather than
        // floating above all of them. Reported by the owner 2026-08-21: switching
        // between full-screen windows, the island "is sticked to the top of the
        // window, so it moves". That is a panel that belongs to a Space instead of
        // to the screen. `--fsaux` puts it back for comparison.
        var behaviour: NSWindow.CollectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        if CommandLine.arguments.contains("--fsaux") { behaviour.insert(.fullScreenAuxiliary) }
        panel.collectionBehavior = behaviour
        panel.contentView = view
        view.wantsLayer = true
        view.layer?.mask = shellMask
        face = FaceRenderer(cloudPath: resourcePath("face.bin",
                            devFallback: "app/island-macos/face.bin"))
        if face == nil {
            FileHandle.standardError.write("face: RENDERER FAILED to init\n".data(using: .utf8)!)
        }
        if let f = face {
            faceLayer.device = f.device
            faceLayer.pixelFormat = .bgra8Unorm
            faceLayer.framebufferOnly = true
            faceLayer.isOpaque = false
            faceLayer.cornerRadius = 18
            faceLayer.isHidden = true
            view.layer?.addSublayer(faceLayer)
        }
        view.onClick = { [weak self] in self?.toggleExpanded() }
        view.gauges = loadGauges(snapshotPath)
        view.panel = loadPanel(snapshotPath)
        applyFrame(width: m.width, height: m.height)
        panel.orderFrontRegardless()
        // A Space change can drop the panel behind, even with .canJoinAllSpaces.
        // Re-ordering on the workspace's own notification is the supported way to
        // reassert it -- no private API, and it costs nothing while nothing changes.
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in self?.panel.orderFrontRegardless() }
        retrack()
        reload()
        // The projection is produced by a separate agent; re-read it slowly so a
        // running island stays current without the owner having to touch it. 20 s
        // is far below any column's TTL and costs one small file read.
        let rt = Timer(timeInterval: 20, repeats: true) { [weak self] _ in self?.reload() }
        RunLoop.main.add(rt, forMode: .common)
    }

    // Welded: the panel's TOP edge is the screen's top edge. Every state grows
    // downward and outward from the notch's own silhouette.
    private func applyFrame(width: CGFloat, height: CGFloat) {
        let f = screen.frame
        panel.setFrame(NSRect(x: (f.width - width) / 2 + f.minX,
                              y: f.maxY - height,
                              width: width, height: height), display: true)
        view.metrics = geo.metrics(state)
        view.metrics.width = width; view.metrics.height = height
        view.state = state
        // Rebuilt every frame: the shape changes with the spring, so a mask set
        // once at the target size clips wrongly for the whole transition.
        let m = geo.metrics(state)
        CATransaction.begin(); CATransaction.setDisableActions(true)
        shellMask.frame = CGRect(x: 0, y: 0, width: width, height: height)
        shellMask.path = islandPath(w: width, h: height, fillet: m.fillet, radius: m.radius)
        CATransaction.commit()
        layoutFace(width: width, height: height)
        view.needsDisplay = true
    }

    private func retrack() {
        if let t = tracking { view.removeTrackingArea(t) }
        let t = NSTrackingArea(rect: view.bounds,
                               options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                               owner: self, userInfo: nil)
        view.addTrackingArea(t); tracking = t
    }

    func go(_ s: State) {
        guard s != state else { return }
        state = s
        faceRunning(s == .expanded)
        let m = geo.metrics(s)
        sw.target = m.width; sh.target = m.height
        view.metrics = m
        if timer == nil {
            let t = Timer(timeInterval: 1.0 / 120.0, repeats: true) { [weak self] _ in self?.tick() }
            RunLoop.main.add(t, forMode: .common); timer = t
        }
    }

    /// The face runs only while it is on screen. §7 of the architecture: this
    /// thing is continuous while VESPER works, on a laptop we are trying to keep
    /// alive -- so "continuous" means continuous WHEN VISIBLE, and a collapsed
    /// island renders nothing at all.
    private func faceRunning(_ on: Bool) {
        faceLayer.isHidden = !on
        if on, faceTimer == nil, face != nil {
            let t = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
                guard let self, let f = self.face else { return }
                self.driver.step(1.0 / 60.0)
                f.uniforms.yaw = self.driver.headYaw
                f.uniforms.pitch = self.driver.headPitch
                f.uniforms.eyeYaw = self.driver.eyeYaw
                f.uniforms.eyePitch = self.driver.eyePitch
                f.uniforms.blink = self.driver.blink
                f.uniforms.scale = 0.96 * self.driver.breath
                f.draw(in: self.faceLayer)
            }
            RunLoop.main.add(t, forMode: .common); faceTimer = t
        } else if !on {
            faceTimer?.invalidate(); faceTimer = nil
        }
    }

    private func layoutFace(width: CGFloat, height: CGFloat) {
        guard face != nil else { return }
        let inset = geo.metrics(.expanded).fillet
        let top = height - geo.inset - 38
        let r = NSRect(x: inset + 8, y: 14, width: width - (inset + 8) * 2, height: max(0, top - 14))
        faceLayer.frame = r
        faceLayer.contentsScale = screen.backingScaleFactor
        faceLayer.drawableSize = CGSize(width: r.width * screen.backingScaleFactor,
                                        height: r.height * screen.backingScaleFactor)
    }

    private func tick() {
        let a = sw.step(1.0 / 120.0), b = sh.step(1.0 / 120.0)
        applyFrame(width: sw.value, height: sh.value)
        if !a && !b { timer?.invalidate(); timer = nil; retrack() }
    }

    func reload() {
        view.columns = loadColumns(snapshotPath)
        view.gauges = loadGauges(snapshotPath)
        view.panel = loadPanel(snapshotPath)
        view.needsDisplay = true
    }

    // Animation starts when there is a state to show and STOPS when there is not.
    // VESPER's stated goal is to stretch this host's lifetime; a mark that
    // animates continuously while nothing is happening spends the battery to say
    // nothing. Idle is a still mark and a dead timer, not a loop at scale 1.
    func setPresence(_ p: Presence) {
        anim.presence = p
        if anim.animates {
            if markTimer == nil {
                let t = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
                    guard let self else { return }
                    let (sc, br) = self.anim.step(1.0 / 60.0)
                    self.view.markScale = sc; self.view.markBrightness = br
                    self.view.needsDisplay = true
                }
                RunLoop.main.add(t, forMode: .common); markTimer = t
            }
        } else {
            markTimer?.invalidate(); markTimer = nil
            view.markScale = 1; view.markBrightness = 1
            view.needsDisplay = true
        }
    }

    // Expanded is CLICK-triggered, per the owner 2026-08-21. Hover no longer
    // expands: a panel that opens because the cursor crossed the top of the screen
    // on its way somewhere else is a panel that opens by accident all day.
    // Hover opens Hanging; a click opens Expanded; a click while Expanded closes
    // all the way to Shoulders. Owner, 2026-08-21 -- collapsing to Hanging left
    // the island open behind a cursor that had already left, so the click that
    // meant "done" read as "half done".
    func toggleExpanded() {
        reload()
        go(state == .expanded ? .shoulders : .expanded)
    }
    // THE SELECTOR MUST BE SPELLED OUT. NSTrackingArea messages its owner with
    // `mouseEntered:`, and NSResponder gets that Swift renaming for free -- but
    // Controller is a plain NSObject, where `@objc func mouseEntered(with:)`
    // generates `mouseEnteredWith:` instead. The tracking area then fires into
    // nothing: no error, no warning, hover simply never happened.
    @objc(mouseEntered:) func mouseEntered(with event: NSEvent) {
        reload(); if state == .shoulders { go(.hanging) }
    }
    @objc(mouseExited:) func mouseExited(with event: NSEvent) {
        if state == .hanging { go(.shoulders) }
    }
}

// MARK: - staying alive

/// Register the login item from INSIDE the bundle.
///
/// A LaunchAgent written into ~/Library/LaunchAgents pointing at the executable
/// works, but macOS then registers the EXECUTABLE: Login Items showed a generic
/// `exec` icon named VESPER, and the projection producer appeared beside it as a
/// second, separate entry called "python3.13". SMAppService reads its plist from
/// Contents/Library/LaunchAgents, so the agent belongs to the app -- one entry,
/// VESPER's own name and mark, and `unregister()` to undo it.
func installLoginItem() {
    guard #available(macOS 13.0, *) else { return }
    let svc = SMAppService.agent(plistName: "ai.vesper.island.plist")
    switch svc.status {
    case .enabled:
        return
    case .requiresApproval:
        // The owner has to allow it in Login Items. Say so rather than retrying,
        // which would never succeed and would look like a hang.
        FileHandle.standardError.write(
            "login item needs approval in System Settings > General > Login Items\n"
                .data(using: .utf8)!)
    default:
        do { try svc.register() } catch {
            FileHandle.standardError.write("login item registration failed: \(error)\n"
                .data(using: .utf8)!)
        }
    }
}

/// Refresh the projection from inside the app, rather than from a second agent.
/// One background item instead of two, and the owner sees VESPER rather than a
/// stray interpreter. `--auto` re-measures only when a reading is going stale.
func startSnapshotRefresh(repo: String) {
    let py = ["/Users/macbook/.local/bin/python3.13", "/usr/bin/python3", "/usr/local/bin/python3"]
        .first { FileManager.default.isExecutableFile(atPath: $0) }
    guard let py else { return }
    let script = (repo as NSString).appendingPathComponent("tools/island_snapshot.py")
    guard FileManager.default.fileExists(atPath: script) else { return }
    func run() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [script, "--auto"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try? p.run()
    }
    run()
    let t = Timer(timeInterval: 3600, repeats: true) { _ in run() }
    RunLoop.main.add(t, forMode: .common)
}

// MARK: - main

let args = CommandLine.arguments
let seconds = args.firstIndex(of: "--seconds").flatMap { i -> Double? in
    i + 1 < args.count ? Double(args[i + 1]) : nil
}
let snapshot = args.firstIndex(of: "--snapshot").flatMap { i -> String? in
    i + 1 < args.count ? args[i + 1] : nil
} ?? ((FileManager.default.homeDirectoryForCurrentUser.path as NSString)
      .appendingPathComponent("Library/Application Support/VESPER/island.json"))

// Undo path, before the install path -- a login item you cannot remove is not a
// convenience. `VESPER.app/Contents/MacOS/VESPER --uninstall-login-item`.
// Ask the system what it thinks, rather than inferring it from launchctl -- an
// SMAppService agent does not appear under its own label there, so its absence
// proves nothing either way.
if args.contains("--login-item-status") {
    if #available(macOS 13.0, *) {
        let st = SMAppService.agent(plistName: "ai.vesper.island.plist").status
        let name: String
        switch st {
        case .enabled: name = "enabled"
        case .requiresApproval: name = "requiresApproval -- allow VESPER in System Settings > General > Login Items"
        case .notRegistered: name = "notRegistered"
        case .notFound: name = "notFound -- the plist is not in the bundle"
        @unknown default: name = "unknown(\(st.rawValue))"
        }
        print("login item: \(name)")
    }
    exit(0)
}

// Rebuilding replaces the bundle, and the registration macOS is holding still
// refers to the OLD signature. `installLoginItem()` sees status .enabled and
// returns early, so the stale record survives and launchd kills every spawn with
// OS_REASON_CODESIGNING while the same binary runs fine by hand. The build calls
// this after signing, so the record always matches what is on disk.
if args.contains("--reinstall-login-item") {
    if #available(macOS 13.0, *) {
        let svc = SMAppService.agent(plistName: "ai.vesper.island.plist")
        try? svc.unregister()
        Thread.sleep(forTimeInterval: 1.0)
        do { try svc.register(); print("login item re-registered") }
        catch { print("re-registration failed: \(error)") }
    }
    exit(0)
}

if args.contains("--uninstall-login-item") {
    if #available(macOS 13.0, *) {
        try? SMAppService.agent(plistName: "ai.vesper.island.plist").unregister()
        print("login item unregistered")
    }
    exit(0)
}

let app = NSApplication.shared
// .accessory: no Dock tile, no menu bar of our own. The island is presence.
app.setActivationPolicy(.accessory)

guard let screen = NSScreen.screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? NSScreen.main else {
    FileHandle.standardError.write("no screen\n".data(using: .utf8)!); exit(1)
}
// Window level is a flag so the Space behaviour can be tested without a rebuild.
// Default raised to .screenSaverWindow: at .statusWindow the island still went
// missing across full-screen Space transitions. `--level-status` goes back.
let levelKey: CGWindowLevelKey = args.contains("--level-status") ? .statusWindow
    : args.contains("--level-max") ? .maximumWindow : .screenSaverWindow
let controller = Controller(screen: screen, snapshotPath: snapshot, levelKey: levelKey)
// installLoginItem() is NOT called. SMAppService could not be made to spawn this
// app -- launchd killed every attempt with OS_REASON_CODESIGNING -- so persistence
// is a plain LaunchAgent from tools/install_island_agent.sh. The function and its
// --login-item-status / --uninstall-login-item flags stay for diagnosis and for
// the day a Developer ID certificate makes SMAppService viable; registering here
// as well would leave two jobs fighting over one label.
if Bundle.main.bundleIdentifier != nil {
    startSnapshotRefresh(repo: FileManager.default.currentDirectoryPath)
}
let g = controller.geo
print("island: notch \(g.notch) pt, inset \(g.inset) pt, hasNotch \(g.hasNotch)")
print("        screen \(screen.frame.width)x\(screen.frame.height) pt")
if !g.hasNotch {
    print("        NO NOTCH on this display -- the island is a built-in-display component")
}
// Start visible rather than dormant, so a run demonstrably shows something.
controller.go(.shoulders)

// --demo cycles the mark's states so they can be SEEN before the audio path and
// the autonomy loop exist to drive them. It is labelled on stdout every time it
// changes, because a demonstration that is not announced becomes a claim.
// Verification only: start expanded so the body can be inspected without moving
// the owner's cursor onto the island to trigger hover.
if args.contains("--expand") { controller.reload(); controller.go(.expanded) }

if args.contains("--demo") {
    controller.anim.synthetic = true
    let order: [Presence] = [.thinking, .working, .speaking, .idle]
    var i = 0
    print("demo: cycling the mark every 5 s. `speaking` uses a SYNTHETIC envelope,")
    print("      not audio -- the real one is amplitude-driven and does not exist yet.")
    controller.setPresence(order[0]); print("mark: \(order[0].rawValue)")
    Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
        i = (i + 1) % order.count
        controller.setPresence(order[i]); print("mark: \(order[i].rawValue)")
    }
}

if let s = seconds {
    // A spike must not be able to leave a panel stuck over the menu bar.
    Timer.scheduledTimer(withTimeInterval: s, repeats: false) { _ in NSApp.terminate(nil) }
}
app.run()
