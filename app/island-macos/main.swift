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

// LINE-BUFFER STDOUT. VESPER's normal life is as a LaunchAgent with its output
// redirected to a file, and a redirected stream is block-buffered: the process
// runs for hours and the log stays empty until 4 KB accumulates or it exits.
// A long-running process whose log does not appear is a process that cannot be
// observed, and this repo's whole position on instruments is that the thing
// being questioned does not get to be the only witness. Cheap here, and it is
// the difference between a hung run and a quiet one.
setvbuf(stdout, nil, _IOLBF, 0)

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
    // Row labels sit against the shell rather than the lighter ground, so `dim`
    // reads as almost-absent there. This is the same grey a step brighter.
    static let label  = NSColor(srgbRed: 0.78, green: 0.76, blue: 0.73, alpha: 1)
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
        // Gauges sit in the shoulder band for Hanging, and move into the body's
        // right cluster for Expanded -- which is where the owner's reference draws
        // them, larger and numbered, beside the face rather than above it.
        if state == .hanging {
            drawGauges(ctx, w: w, h: h, cy: h - safeInset / 2 - 3, ring: 19, showValue: true)
        }
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
        // Expanded puts its content on the shell; only Hanging has the inner ground
        // panel. Measured from the two references, not assumed alike -- so these are
        // two branches, not one branch with the panel painted conditionally. Nesting
        // Expanded's cluster inside the Hanging block is exactly how it silently
        // never drew.
        guard body.height > 20 else { return }
        if state == .expanded {
            drawRightCluster(ctx, in: body)
            return
        }
        let rr = CGPath(roundedRect: body, cornerWidth: 18, cornerHeight: 18, transform: nil)
        ctx.addPath(rr)
        ctx.setFillColor(IslandView.ground.cgColor)
        ctx.fillPath()
        if !panel.isEmpty {
            drawPanel(ctx, in: body)
        } else if columns.isEmpty {
            // Nothing is wired yet, and an empty body says so rather than showing a
            // plausible instrument panel. INV-HW-2: UNKNOWN means UNAVAILABLE, and a
            // surface that renders invented state is worse than one that renders none.
            let msg = text("no projection — backend not running", 10, IslandView.dim)
            msg.draw(at: NSPoint(x: body.midX - msg.size().width / 2, y: body.midY - 6))
        }
    }

    /// The Hanging instrument panel: what the host is actually doing, on the
    /// #03141f ground. One row of readings, because the reference's bar list is
    /// horizontal and a grid at this height would put four labels in 54 pt.
    ///
    /// ONLY GENUINE RATIOS GET A BAR. `Thermal` is a level -- nominal, fair,
    /// serious -- and a bar beneath it would invent an ordering with a magnitude
    /// the platform never claimed.
    private func drawPanel(_ ctx: CGContext, in body: NSRect) {
        let n = CGFloat(panel.count)
        guard n > 0 else { return }
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
            if i > 0 {
                ctx.setFillColor(NSColor(white: 1, alpha: 0.07).cgColor)
                ctx.fill(NSRect(x: x, y: body.minY + 14, width: 1, height: body.height - 34))
            }
        }
    }

    /// Expanded's right cluster: the numbered rings over the host readings, in the
    /// arrangement the reference draws. Everything here is absent-if-unproduced,
    /// so the cluster shrinks rather than filling with placeholders.
    private func drawRightCluster(_ ctx: CGContext, in body: NSRect) {
        // THE FACE IS AN OPAQUE SUBLAYER AND IT WINS. CAMetalLayer draws over the
        // view's own drawRect content, so anything painted under it is simply gone
        // -- the row labels were rendering correctly at x = 366 and being covered,
        // while the right-aligned values beside it showed fine. The cluster starts
        // clear of the face's right edge rather than assuming a fixed width.
        let faceRight = (bounds.width + min(230, bounds.width * 0.38)) / 2
        let x0 = max(body.minX, faceRight + 14)
        let cw = body.maxX - x0
        guard cw > 90 else { return }
        var y = body.maxY - 20

        if !gauges.isEmpty {
            let ring: CGFloat = 34, gap: CGFloat = 18
            let n = CGFloat(gauges.count)
            var gx = x0 + (cw - (ring * n + gap * (n - 1))) / 2
            for g in gauges {
                let r = NSRect(x: gx, y: y - ring, width: ring, height: ring)
                ctx.setLineWidth(2.6)
                ctx.setStrokeColor(NSColor(white: 1, alpha: 0.15).cgColor)
                ctx.addEllipse(in: r.insetBy(dx: 1.3, dy: 1.3)); ctx.strokePath()
                ctx.setStrokeColor(IslandView.ember.cgColor)
                ctx.addArc(center: NSPoint(x: r.midX, y: r.midY), radius: ring / 2 - 1.3,
                           startAngle: .pi / 2, endAngle: .pi / 2 - 2 * .pi * g.value, clockwise: true)
                ctx.strokePath()
                let v = text("\(Int((g.value * 100).rounded()))", 12, IslandView.ink, weight: .medium)
                v.draw(at: NSPoint(x: r.midX - v.size().width / 2, y: r.midY - 6))
                let l = text(g.label, 8, IslandView.dim)
                l.draw(at: NSPoint(x: r.midX - l.size().width / 2, y: r.minY - 12))
                gx += ring + gap
            }
            y -= ring + 26
        }

        // The host readings as labelled rows, which is the reference's bar list.
        for item in panel.prefix(4) {
            guard y > body.minY + 8 else { break }
            let l = text(item.label, 9.5, IslandView.label)
            l.draw(at: NSPoint(x: x0, y: y - 11))
            let v = text(item.value, 10, IslandView.ink, weight: .medium)
            v.draw(at: NSPoint(x: body.maxX - v.size().width, y: y - 11))
            if let r = item.ratio {
                ctx.setFillColor(NSColor(white: 1, alpha: 0.10).cgColor)
                ctx.fill(NSRect(x: x0, y: y - 16, width: cw, height: 2))
                ctx.setFillColor(IslandView.ember.cgColor)
                ctx.fill(NSRect(x: x0, y: y - 16, width: cw * r, height: 2))
            }
            y -= 22
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
        ) { [weak self] _ in
            // GATED ON THE RETREAT, and this guard is the whole reason §2.6 works.
            // Arriving on the home's Desktop IS a Space change, so an unconditional
            // re-order here would put the island back the instant it stepped away --
            // the one case the rule exists for, undone by the line that protects
            // every other case.
            guard let self, !self.retreated else { return }
            self.panel.orderFrontRegardless()
        }
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

    /// §2.6 -- the island's visibility is the INVERSE of the ground's occlusion
    /// state. One signal, two rules, no new mechanism.
    ///
    /// The island exists because VESPER is not on screen. Inside the home VESPER
    /// is fully present -- the face, the ground, ninety cards -- and an island
    /// there is the same entity saying the same thing twice, in a smaller voice,
    /// thirty points above its own face.
    ///
    /// A RETREAT, NOT A CUT. Dormant first, then out, so arriving on the home
    /// reads as presence consolidating into one place rather than as a component
    /// being switched off. Coming back is the same move reversed: on screen at
    /// dormant, then out to shoulders, so it grows rather than appears.
    private(set) var retreated = false
    func retreat(_ on: Bool) {
        guard on != retreated else { return }
        retreated = on
        if on {
            go(.dormant)
            // Long enough for the dormant spring to land. Ordering out mid-spring
            // is the cut this method exists to avoid.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { [weak self] in
                guard let self, self.retreated else { return }
                self.panel.orderOut(nil)
            }
        } else {
            panel.orderFrontRegardless()
            go(.shoulders)
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

    /// The face's layer rect, for whoever needs to READ that region rather than
    /// trust something was drawn into it. The home's face density is derived
    /// from this one's, so this one has to be measurable too -- otherwise the
    /// reference is a number in a comment.
    var faceLayerRect: CGRect { faceLayer.frame }

    private func layoutFace(width: CGFloat, height: CGFloat) {
        guard face != nil else { return }
        let top = height - geo.inset - 38
        // Centre third only. The reference flanks the face with instruments; a face
        // spanning the whole body leaves nowhere for them and reads as a portrait
        // rather than as one element among several.
        let fw = min(230, width * 0.38)
        let r = NSRect(x: (width - fw) / 2, y: 14, width: fw, height: max(0, top - 14))
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

if args.contains("--listen") {
    // Ahead of NSApplication for the same reason --speech-consent is: this is
    // a microphone session, not a window.
    let locale = args.firstIndex(of: "--locale").map { args[args.index(after: $0)] } ?? "en-US"
    let seconds = args.firstIndex(of: "--seconds").flatMap { Double(args[args.index(after: $0)]) } ?? 20
    runListener(locale: locale, seconds: seconds,
                diagnose: args.contains("--diagnose"))
    exit(0)
}

if args.contains("--fn-fire") {
    // THE TRIPLE-TAP'S CONSEQUENCE, WITHOUT THE TAP. Not a convenience: it is
    // the only way to confirm the single-instance guard without synthesising a
    // key event, which needs the same Accessibility grant the watcher is
    // waiting on. It calls the SAME `launchVesper()` the tap handler calls, so
    // what it proves is about the real door -- and the caller then counts
    // processes rather than believing the message this prints.
    print("running before: \(vesperIsRunning())")
    launchVesper()
    Thread.sleep(forTimeInterval: 2.0)
    exit(0)
}

if args.contains("--fn-watch") {
    // The starter. Lives outside VESPER because it starts VESPER.
    runFnWatch()
    exit(0)
}

if args.contains("--wake") {
    // Always listening, on-device only, nothing sent until the word is heard.
    runWakeWord(diagnose: args.contains("--diagnose"))
    exit(0)
}

if args.contains("--record") {
    // Records and does not recognise. See runRecorder for why it is separate
    // from --listen rather than a flag on it.
    let seconds = args.firstIndex(of: "--seconds").flatMap { Double(args[args.index(after: $0)]) } ?? 6
    let out = args.firstIndex(of: "--out").map { args[args.index(after: $0)] }
        ?? NSTemporaryDirectory() + "vesper-heard.caf"
    runRecorder(seconds: seconds, out: out)
    exit(0)
}

if args.contains("--speech-status") {
    speechStatus()
    exit(0)
}

if args.contains("--speech-consent") {
    // Deliberately before NSApplication.shared: the prompt is the whole job,
    // and bringing up the island's window layer to ask for a permission would
    // put VESPER's face over the owner's Desktop for no reason.
    requestSpeechConsent()
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

// THE REFERENCE THE HOME'S FACE IS TUNED AGAINST. FaceUniforms.pointSize scales
// the cloud's point size with the layer, on the claim that it preserves
// density. A claim about two surfaces has to be read on both of them, with one
// instrument, or it is arithmetic rather than a measurement.
if args.contains("--island-face-check") {
    controller.reload(); controller.go(.expanded)
    DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
        let r = controller.faceLayerRect
        guard let img = GlassGuard.windowImage(controller.panel) else {
            print("  *** no window server image of the island panel ***"); exit(2)
        }
        let size = controller.panel.frame.size
        let cov = GlassGuard.coverage(img, viewSize: size, rect: r)
        let pct = cov.total > 0 ? Double(cov.painted) / Double(cov.total) * 100 : 0
        print("")
        print("  island face — the density the home is tuned against")
        print(String(format: "  face rect     %.0fx%.0f", r.width, r.height))
        print(String(format: "  painted in it %d / %d px  (%.2f%%)  mean α %.3f",
                     cov.painted, cov.total, pct, cov.meanAlpha))
        exit(0)
    }
}

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

// MARK: - The home
//
// ONE PROCESS, and the reasons are in Home.swift's header. The short version:
// TCC grants key to app identity, §2.6 needs one signal rather than a transport,
// and "one face at a time" becomes structurally true when the same object
// decides which host is drawing.
//
// THE GROUND IS NOT PLACED HERE. It is `.managed`, so it lands on whichever
// Desktop is active at the moment it is created, and there is no public API
// that names a Space to put it on instead (§2.3a). Switch first, then create --
// so `--home` creates the ground on the Desktop the owner is looking at, and
// the switch that puts them there is a separate mechanism that needs an
// Accessibility grant this build has not asked for yet.
// THE GLASS HATCH'S ALARM. SPIKE-013 §0 measured that a WKWebView cannot be
// made transparent with public API, and the owner's decision was to take the
// private route and remove the SILENCE that made ISLAND-ARCHITECTURE §2 forbid
// it. This is where the silence is removed on demand; GlassGuard.verify carries
// its own controls, so a reader that has gone blind reports UNREADABLE rather
// than passing an opaque chrome.
// Reversibility that cannot be reached is not reversibility. Ambience.restore
// existed from the day the wallpaper became the real desktop picture, and until
// now nothing on the command line called it -- so the promise in the design doc
// was true of the code and false of the owner's machine.
if args.contains("--mode-restore") {
    Ambience.restore(on: NSScreen.main ?? screen)
    exit(0)
}

// THE OCCLUSION STOP, tested at 320x240 instead of full screen.
//
// Criterion 4 can only be exercised at full size by covering the whole display
// in black, which is a thing to do on VESPER's own Desktop and nowhere else.
// The MECHANISM does not care about size: the same OcclusionWatch, on a window
// with the ground's exact configuration -- borderless, transparent, level
// normal-1, .managed -- covered by an opaque window over it. This says whether
// the watch detects being covered at all, and WHICH of its two paths did it.
// §10's dock swap, isolated. It reported "system dock up" while the home was on
// VESPER's own Desktop, which means the Dock never went under -- and the swap is
// three things that can each fail silently: activation, the presentation option
// taking, and the Dock actually yielding its space.
if args.contains("--dock-check") {
    guard let sc = NSScreen.main else { exit(2) }
    // RE-FETCH, never hold. An NSScreen object caches its geometry, so a
    // reference taken before the change reports the world as it was and the
    // Dock looks like it refused to move.
    func spaceLine(_ tag: String) {
        guard let s = NSScreen.main else { return }
        print("  \(tag): visibleFrame.minY \(Int(s.visibleFrame.minY))"
            + "  (frame.minY \(Int(s.frame.minY)))"
            + "  dock reserves space: \(s.visibleFrame.minY > s.frame.minY + 1)")
    }
    print("")
    print("  dock swap — §10, one step at a time")
    print("  " + String(repeating: "─", count: 58))
    print("  active before: \(NSApp.isActive)")
    spaceLine("before")
    NSApp.activate(ignoringOtherApps: true)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
        print("  active after activate(): \(NSApp.isActive)")
        if NSApp.isActive {
            NSApp.presentationOptions.insert(.autoHideDock)
            print("  presentationOptions now contains .autoHideDock: "
                + "\(NSApp.presentationOptions.contains(.autoHideDock))")
        } else {
            print("  NOT ACTIVE — presentationOptions may only be set by the active app,")
            print("  and setting it anyway raises. This is where the swap stops.")
        }
        // HEALING, which is the property the owner's second bug was about.
        // Take the option away behind the reconciler's back -- exactly what
        // macOS does when VESPER stops being frontmost -- and see whether it
        // comes back on its own. A self-healing mechanism observed only while
        // nothing broke it is not evidence that it heals.
        func healCheck() {
            let swap = DockSwap(interval: 0.2) { true }
            swap.start()
            print("")
            print("  healing: taking .autoHideDock away behind its back")
            NSApp.presentationOptions.remove(.autoHideDock)
            let hDeadline = Date().addingTimeInterval(3.0)
            func check() {
                if NSApp.presentationOptions.contains(.autoHideDock) {
                    print("  healed — the reconciler put it back "
                        + "(\(swap.repairs) repair(s))")
                    swap.stop()
                    NSApp.presentationOptions.remove(.autoHideDock)
                    print("  " + String(repeating: "═", count: 58))
                    exit(0)
                }
                if Date() > hDeadline {
                    print("  NOT HEALED after 3 s — an aborted switch would leave the")
                    print("  Dock up until something else happened to fire.")
                    swap.stop()
                    print("  " + String(repeating: "═", count: 58))
                    exit(1)
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { check() }
            }
            check()
        }

        // POLL TO A DEADLINE, do not sample once. A fixed 0.8 s wait passed
        // twice and then failed, for a swap that had worked both times: the
        // window server had simply not re-laid the screen yet. That is the same
        // read-too-soon this session already fixed on the desktop picture, which
        // reported "NOT confirmed" while naming the exact value it had just set.
        let deadline = Date().addingTimeInterval(3.0)
        func settle() {
            let cur = NSScreen.main
            let won = (cur?.visibleFrame.minY ?? 1) <= (cur?.frame.minY ?? 0) + 1
            if !won && Date() < deadline {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { settle() }
                return
            }
            spaceLine("after ")
            print("")
            print(won ? "  PASS — the Dock went under."
                      : "  FAIL — the Dock still reserves its space after 3 s.")
            guard won else {
                NSApp.presentationOptions.remove(.autoHideDock)
                print("  " + String(repeating: "═", count: 58))
                exit(1)
            }
            healCheck()
        }
        settle()
    }
    app.run()
}

if args.contains("--occlusion-check") {
    guard let sc = NSScreen.main else { exit(2) }
    let r = CGRect(x: sc.frame.minX + 40, y: sc.frame.minY + 40, width: 320, height: 240)
    let probe = NSWindow(contentRect: r, styleMask: [.borderless],
                         backing: .buffered, defer: false)
    // FLOATING, and that is a deliberate departure from the ground's own
    // normal-1. At normal-1 in a screen corner the probe starts UNDER whatever
    // the owner has open, so it is occluded before the test begins and covering
    // it changes nothing -- which is exactly what the first run reported: zero
    // changes seen, by either path, for a mechanism that was never given a
    // visible window to watch. The level is raised so the test can begin at all;
    // the ground's real level is exercised by the full-screen criterion 4 run.
    probe.level = .floating
    probe.collectionBehavior = [.managed]
    probe.animationBehavior = .none
    probe.isOpaque = false
    probe.backgroundColor = .clear
    probe.hasShadow = false
    probe.ignoresMouseEvents = true
    let v = NSView(frame: CGRect(origin: .zero, size: r.size))
    v.wantsLayer = true
    v.layer?.backgroundColor = CGColor(red: 0.06, green: 0.19, blue: 0.75, alpha: 1)
    probe.contentView = v
    probe.orderFrontRegardless()

    let pollOnly = args.contains("--poll-only")
    let watch = OcclusionWatch(window: probe, observeNotification: !pollOnly)
    var covered: (Double, OcclusionWatch.Source)?
    var uncovered: (Double, OcclusionWatch.Source)?
    var t0 = Date()
    watch.onChange = { visible, source in
        let dt = Date().timeIntervalSince(t0)
        if !visible, covered == nil { covered = (dt, source) }
        else if visible, covered != nil, uncovered == nil { uncovered = (dt, source) }
    }
    watch.start()

    print("")
    print("  occlusion stop — the mechanism, at 320x240")
    print("  " + String(repeating: "─", count: 60))
    print(pollOnly
          ? "  NOTIFICATION DISCONNECTED — the poll alone, which is the path the"
          + "\n  full-screen ground at normal-1 actually has to rely on."
          : "  a window with the ground's exact configuration, covered and uncovered.")
    print("  the full-screen criterion 4 run belongs on VESPER's own Desktop.")

    var cover: NSWindow?
    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
        // A test that begins on an already-covered window measures nothing and
        // reports FAIL, which is the worst of both.
        guard probe.occlusionState.contains(.visible) else {
            print("")
            print("  the probe was ALREADY COVERED before the test began, so covering")
            print("  it could not be a change. Nothing was measured — this is not a")
            print("  failure of the mechanism, it is the test failing to start.")
            exit(2)
        }
        print("  probe starts visible — beginning")
        t0 = Date()
        let w = NSWindow(contentRect: r, styleMask: [.borderless],
                         backing: .buffered, defer: false)
        w.collectionBehavior = [.managed]
        w.level = NSWindow.Level(rawValue: NSWindow.Level.floating.rawValue + 1)
        w.isOpaque = true
        w.backgroundColor = .black
        w.animationBehavior = .none
        w.orderFrontRegardless()
        cover = w

        DispatchQueue.main.asyncAfter(deadline: .now() + 4.0) {
            cover?.orderOut(nil)
            t0 = Date()
            DispatchQueue.main.asyncAfter(deadline: .now() + 4.0) {
                probe.orderOut(nil)
                watch.stop()
                print("")
                if let c = covered {
                    // Interpolation, not String(format:). `%@` given a C string
                    // pointer is a SIGTRAP with no message -- the run that found
                    // that had already completed the measurement and died while
                    // printing it, which is the most annoying possible place.
                    print("  covered   DETECTED in "
                        + String(format: "%.2f", c.0) + " s, by the \(c.1.rawValue)")
                } else {
                    print("  covered   NOT DETECTED — the watch never saw it")
                }
                if let u = uncovered {
                    print("  uncovered DETECTED in "
                        + String(format: "%.2f", u.0) + " s, by the \(u.1.rawValue)")
                } else {
                    print("  uncovered NOT DETECTED")
                }
                print("  \(watch.provenance)")
                print("")
                let ok = covered != nil && uncovered != nil
                print(ok
                      ? "  PASS — the stop has a working signal in both directions."
                      : "  FAIL — the ground would keep drawing behind the owner's work.")
                print("  " + String(repeating: "═", count: 60))
                exit(ok ? 0 : 1)
            }
        }
    }
    app.run()
}

// THE CARD, READ BACK. A rebuilt binary that mounts a chrome is not a card
// showing the right numbers, and the only way this was checkable before was by
// looking at the screen -- which is not a check, and is unavailable on a
// headless node or over ssh. Prints exactly the markup the card will carry, so
// a producer change can be verified without a display and without a person.
if args.contains("--card-rows") {
    print(HomeChrome.metricRows())
    exit(0)
}

if args.contains("--glass-verify") {
    // --no-hatch is the NEGATIVE CONTROL: run the same alarm with the hatch
    // withheld, and require it to go RED. A negative control that passes is a
    // defect, not a relief -- it would mean the alarm cannot detect the fault
    // it exists for.
    let negative = args.contains("--no-hatch")
    GlassGuard.verify(applyHatch: !negative) { v in
        print(v.line)
        if negative {
            switch v {
            case .opaque:
                print("negative control: PASS — the alarm detects a chrome that paints")
                exit(0)
            default:
                let m = "negative control: FAILED — the hatch was withheld and the alarm "
                      + "still said \(v). It is not reading the hatch, so every green it "
                      + "has given was free.\n"
                FileHandle.standardError.write(m.data(using: .utf8)!)
                exit(3)
            }
        }
        if !v.mayMountChrome {
            FileHandle.standardError.write((v.line + "\n").data(using: .utf8)!)
        }
        // 0 transparent, 1 opaque, 2 unreadable. An unanswered question exits
        // differently from an answered no, because they need different repairs.
        switch v {
        case .transparent:  exit(0)
        case .opaque:       exit(1)
        case .unreadable:   exit(2)
        }
    }
    app.run()
}

if args.contains("--home-verify") {
    HomeVerify.identity()
    let secs = args.firstIndex(of: "--seconds").flatMap { i -> Double? in
        i + 1 < args.count ? Double(args[i + 1]) : nil
    } ?? 30
    let after = args.firstIndex(of: "--after").flatMap { i -> Double? in
        i + 1 < args.count ? Double(args[i + 1]) : nil
    } ?? 10
    // The control is the island's own panel -- the very window §2.6 proposes to
    // move. A control that is the claim beats a control that stands in for it.
    HomeVerify.occlusion(secs: secs, after: after, control: controller.panel,
        log: (Ambience.repoRoot() ?? NSTemporaryDirectory())
             + "/app/home-macos/home_verify_last_run.log")
    app.run()
}

var home: HomeController?
if args.contains("--home") {
    // THE RUNTIME STARTS WITH THE HOME AND STOPS WITH IT.
    //
    // Started here rather than by a second login item: two labels made VESPER
    // two things, and left a runtime that could be answering while no window
    // existed anywhere -- holding the owner's API keys with nothing on screen
    // to say so. One app, one lifetime.
    //
    // ITS RESULT IS PRINTED WHETHER OR NOT IT WORKED. A home with no runtime
    // looks exactly like a home whose runtime has nothing to say: the field
    // accepts what is typed, queues it, and nothing ever answers. Silence here
    // would make the two indistinguishable, and the field's own placeholder
    // only reports the case where the BRIDGE is missing, not the runtime.
    let runtimeHost = RuntimeHost()
    if !args.contains("--no-runtime") {
        print("runtime: \(runtimeHost.start())")
    } else {
        print("runtime: not started (--no-runtime); the field will queue and "
            + "nothing will answer")
    }

    // --after N delays creation by N seconds, and it exists for one reason:
    // the ground is `.managed`, so it lands on whichever Desktop is ACTIVE when
    // it is created, and there is no public API that names a Space to put it on
    // instead (§2.3a). The command is typed in a terminal, and the terminal is
    // not on VESPER's Desktop. Without this the ground appears on top of
    // whatever the owner was typing in, which is the opposite of the point.
    let homeAfter = args.firstIndex(of: "--after").flatMap { i -> Double? in
        i + 1 < args.count ? Double(args[i + 1]) : nil
    } ?? 0
    if homeAfter > 0 {
        print("home: waiting \(Int(homeAfter)) s — switch to VESPER's Desktop now.")
        print("      the ground is created THERE, on whichever Desktop is active.")
        Thread.sleep(forTimeInterval: homeAfter)
    }

    // --on-empty-desktop turns a deadline into a CONDITION, and that is the
    // difference between a command the owner has to be standing over and one
    // that can be left running.
    //
    // §2.3a: the ground is `.managed`, so it is created on whichever Desktop is
    // active, and no public API names a Space to put it on instead. --after
    // handles that with a stopwatch: switch within N seconds or the ground
    // lands on top of your work. This waits for the room to be EMPTY instead --
    // SpaceWatch.fingerprint() already excludes our own windows and counts only
    // ordinary ones, so "no foreign windows here" is exactly "this Desktop is
    // not the one you are working on".
    //
    // It fails CLOSED. No empty Desktop, no ground: taking the owner's Desktop
    // is worse than not starting.
    // --on-empty-desktop turns a deadline into a CONDITION, and that is the
    // difference between a command the owner has to stand over and one that can
    // be left running for good.
    //
    // §2.3a: the ground is `.managed`, so it is created on whichever Desktop is
    // ACTIVE, and no public API names a Space to put it on instead. --after
    // handles that with a stopwatch: switch within N seconds or the ground
    // lands on top of your work. This waits for the room to be EMPTY instead --
    // SpaceWatch.fingerprint() already excludes our own windows and counts only
    // ordinary ones, so "no foreign windows here" is exactly "this is not the
    // Desktop you are working on".
    //
    // IT DOES NOT BLOCK, and that matters for the login-item case: VESPER's
    // island must be up the moment the process is, not whenever a Desktop
    // happens to come free. The first version slept the main thread before
    // `app.run()`, which would have held the island hostage to the home.
    //
    // AND IT WILL NOT TAKE DESKTOP 1 AT LOGIN. At login every Desktop is empty,
    // including the owner's, so "first empty Desktop" would claim theirs. The
    // condition is therefore: an empty Desktop, AND a non-empty one seen at
    // least once first. VESPER waits until the machine is in use, then takes
    // the room nobody is in.
    if args.contains("--on-empty-desktop") {
        let limit = args.firstIndex(of: "--wait").flatMap { i -> Double? in
            i + 1 < args.count ? Double(args[i + 1]) : nil
        }
        print("home: waiting for an EMPTY Desktop — switch to VESPER's whenever you like.")
        print("      it refuses to create the ground on a Desktop with your windows on it.")
        var announced = false
        var t: Timer?
        t = Timer(timeInterval: 0.5, repeats: true) { timer in
            let fp = SpaceWatch.fingerprint()
            if !fp.isEmpty {
                if !announced {
                    print("      here now: \(fp.count) foreign window(s) — not VESPER's Desktop.")
                    announced = true
                }
                return
            }
            // Owner, 2026-08-24: "if both desktops are empty, say on boot for
            // example, it can just take one, and leave the other one untouched
            // ... not take something i have work on". So the condition is
            // exactly emptiness, and nothing else: an empty Desktop is fair
            // game whether or not the machine has been used yet.
            timer.invalidate(); t = nil
            print("home: empty Desktop — the ground is created HERE.")
            startHome()
        }
        RunLoop.main.add(t!, forMode: .common)
        if let limit {
            // A deadline only exists when one is asked for. Under launchd's
            // KeepAlive, exiting on a timeout is a restart loop; the agent case
            // waits indefinitely and takes nothing.
            DispatchQueue.main.asyncAfter(deadline: .now() + limit) {
                guard t != nil else { return }
                t?.invalidate()
                let msg = "home: no empty Desktop within \(Int(limit)) s — refusing to take "
                        + "one that is not VESPER's. Nothing was changed.\n"
                FileHandle.standardError.write(msg.data(using: .utf8)!)
                exit(3)
            }
        }
    } else {
        startHome()
    }
}

/// Everything the home needs, in one place, so it can be started immediately or
/// when a Desktop comes free without the two paths drifting apart.
func startHome() {
    guard let h = HomeController(screen: NSScreen.main ?? screen) else {
        FileHandle.standardError.write("home: could not start\n".data(using: .utf8)!)
        exit(2)
    }
    home = h
    // §2.6, wired. The ground's occlusion state is the ONLY signal, and it is
    // read from the notification rather than polled, so the island moves on the
    // same edge the owner sees.
    h.onVisibilityChange = { [weak controller] visible in
        controller?.retreat(visible)
        print("home: \(visible ? "visible  → island retreats" : "covered  → island returns")")
    }
    if let i = args.firstIndex(of: "--mode"), i + 1 < args.count {
        h.setMode(args[i + 1])
    }
    // --face-check reads the region the face occupies out of the WINDOW SERVER
    // rather than asking the renderer whether it rendered. `framesDrawn` counts
    // ATTEMPTS: a renderer that attempts 120 times a second and paints nothing
    // reports the same number as one that works, which is why the owner can see
    // an empty screen while the log looks healthy.
    if args.contains("--face-check") {
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            print("")
            print("  face check — read from the window server, not from the renderer")
            print("  ────────────────────────────────────────────────────────────")
            let t = h.faceTint
            print(String(format: "  frames attempted %d   tint r%.2f g%.2f b%.2f",
                         h.framesDrawn, t.0, t.1, t.2))
            print("  repo root        \(Ambience.repoRoot() ?? "*** NOT FOUND ***")")
            print("  modes loaded     \(Ambience.modes().count)")
            guard let img = GlassGuard.windowImage(h.groundWindow) else {
                print("  *** the window server returned no image of the ground ***")
                return
            }
            let size = h.groundWindow.frame.size
            let face = GlassGuard.coverage(img, viewSize: size, rect: h.faceRect)
            // The control. Outside the face's layer the ground paints NOTHING,
            // so this must be ~0. If it is not, the reader is picking up
            // something other than our window and the face figure means nothing.
            let outside = GlassGuard.coverage(img, viewSize: size,
                                              rect: CGRect(x: 0, y: 0, width: 80, height: 80))
            // THE PLATE AND THE FACE, read by LUMINANCE. Alpha stopped
            // discriminating the moment a backing went behind the face -- the
            // face rect returned 100% at alpha 1.000, which is true of the
            // window and says nothing about the face.
            // THE ICON MASK, proved rather than asserted. Icons and widgets sit
            // two billion window levels below the ground; the only way they
            // reach the owner's eye is through a transparent patch of it. So the
            // question is not "are the icons hidden" -- which would need a
            // screen recording -- but "is any part of this window see-through",
            // which our own window's alpha answers exactly.
            var opaque = 0, tiles = 0
            let step: CGFloat = 64
            var gx: CGFloat = 0
            while gx < size.width {
                var gy: CGFloat = 0
                while gy < size.height {
                    let c = GlassGuard.coverage(img, viewSize: size,
                                rect: CGRect(x: gx, y: gy, width: 8, height: 8))
                    tiles += 1
                    if c.meanAlpha >= 0.99 { opaque += 1 }
                    gy += step
                }
                gx += step
            }
            print(String(format: "  ground opacity  %d/%d tiles fully opaque (%.1f%%)",
                         opaque, tiles, tiles > 0 ? Double(opaque) / Double(tiles) * 100 : 0))
            print(opaque == tiles
                  ? "  nothing below the ground can show through — icons and widgets"
                  + " are covered on this Desktop"
                  : "  SOME OF THE GROUND IS SEE-THROUGH — the owner's icons and widgets"
                  + " will show there")

            let pr = h.plateRect
            // A corner of the plate the face never reaches: this is the plate
            // ALONE, and it is the reference every face number is read against.
            // THE FACE'S OWN GROUND is the fill directly under it, and with a
            // radial falloff that is no longer the same as the plate's rim. Read
            // it at a corner of the FACE's square: inside the centre plateau,
            // and far enough out that the head's points do not reach.
            let fr = h.faceRect
            // ABOVE the head, on the vertical axis. The first attempt read the
            // face square's CORNER, which sits at 0.86 of the plate's half
            // diagonal -- deep in the falloff, not on the plateau it was meant
            // to sample. It reported centre and rim as identical and the
            // gradient as broken; the gradient was fine and the probe was in
            // the wrong place. A radial plateau is bounded by the square's
            // INSCRIBED circle, never by its corners.
            let underFace = CGRect(x: fr.midX - 20, y: fr.maxY - 58, width: 40, height: 40)
            let plateOnly = GlassGuard.luma(img, viewSize: size, rect: underFace)
            // The rim, where the falloff has let the glass back through.
            let rim = CGRect(x: pr.minX + 16, y: pr.maxY - 76, width: 56, height: 56)
            let rimL = GlassGuard.luma(img, viewSize: size, rect: rim)
            // Outside the plate entirely: our window paints nothing there.
            let off = GlassGuard.luma(img, viewSize: size,
                                      rect: CGRect(x: 0, y: 0, width: 80, height: 80))
            print(String(format: "  plate %.0fx%.0f     luma %.3f  variance %.5f",
                         pr.width, pr.height, plateOnly.mean, plateOnly.variance))
            print(String(format: "  off-plate control  luma %.3f  (our window paints nothing there)",
                         off.mean))
            // WHAT THIS READING CANNOT TELL YOU, said here rather than implied.
            // The blur is an NSVisualEffectView with `.behindWindow`, and the
            // window server does that compositing against the desktop at screen
            // time -- our own window's buffer holds a flat stand-in for it. So a
            // variance of zero here is a fact about where the blur happens and
            // NOT evidence the glass is missing. What our buffer does hold, and
            // what this number is therefore good for, is the SCRIM: the solved
            // fill, which is the half that decides whether the face has a
            // ground to be seen against.
            print(String(format: "  under the face  %.3f   predicted on screen %.3f",
                         plateOnly.mean, h.plateBackdropLuma * (1 - h.plateFill)))
            print(String(format: "  at the rim      %.3f   %.1fx the centre — the falloff",
                         rimL.mean, plateOnly.mean > 0 ? rimL.mean / plateOnly.mean : 0))
            print("  (the blur itself is composited by the window server and is not in")
            print("   this buffer — only the owner's eyes settle that half)")

            // The face, against the plate it sits on. A margin rather than any
            // brightness: the plate is bright, and counting pixels brighter
            // than zero would count the plate.
            let margin = plateOnly.mean + 0.06
            // ONLY WHERE THE FILL IS UNIFORM. Comparing a whole rect against a
            // single reference stopped being valid the moment the plate got a
            // falloff: the face square's corners sit at rim brightness, which
            // is above any margin taken from the centre, so the plate's own
            // gradient got counted as face and the figure jumped to 22% of a
            // rect the head does not fill. The plateau is a circle; the largest
            // square inside it is the face square over root two, and inside
            // that one reference is true everywhere.
            let inner = CGRect(x: fr.midX - fr.width / 2.82842712,
                               y: fr.midY - fr.height / 2.82842712,
                               width: fr.width / 1.41421356,
                               height: fr.height / 1.41421356)
            let faceL = GlassGuard.luma(img, viewSize: size, rect: inner,
                                        brighterThan: margin)
            // THE CARD, if one is mounted. It sits in the left cluster, clear
            // of the plate, over a region where the ground paints NOTHING -- so
            // any paint there came from the chrome and from nowhere else. The
            // off-plate control reads 0.000 in the same buffer, which is what
            // makes this comparison worth anything.
            if h.chrome.mounted, h.chrome.cardRect != .zero {
                let cr = h.chrome.cardRect.insetBy(dx: 24, dy: 24)
                let card = GlassGuard.luma(img, viewSize: size, rect: cr)
                let cardA = GlassGuard.coverage(img, viewSize: size, rect: cr)
                print(String(format: "  card %.0fx%.0f      luma %.3f  %.1f%% painted",
                             h.chrome.cardRect.width, h.chrome.cardRect.height,
                             card.mean,
                             cardA.total > 0
                                ? Double(cardA.painted) / Double(cardA.total) * 100 : 0))
                print(cardA.painted == 0
                      ? "  the card is NOT painting — mounted is not the same as visible"
                      : "  the card paints where the ground paints nothing")
            }

            // THE MAIN MENU. Bottom-centre, at the Dock's position. Probed
            // separately from the card because they are different CSS and a bar
            // that failed to lay out would be invisible in the card's number.
            if h.chrome.mounted {
                let bar = CGRect(x: size.width / 2 - 120, y: 18, width: 240, height: 48)
                let b = GlassGuard.coverage(img, viewSize: size, rect: bar)
                let bl = GlassGuard.luma(img, viewSize: size, rect: bar)
                print(String(format: "  main menu       %.1f%% painted, luma %.3f",
                             b.total > 0 ? Double(b.painted) / Double(b.total) * 100 : 0,
                             bl.mean))
                print(b.painted == 0
                      ? "  the main menu is NOT painting"
                      : "  the main menu paints at the Dock's position")
            }

            let fpct = faceL.total > 0
                ? Double(faceL.brighter) / Double(faceL.total) * 100 : 0
            print(String(format: "  face over plate    %.2f%% of its rect is >%.3f luma  (plate is %.3f)",
                         fpct, margin, plateOnly.mean))
            print(fpct < 0.5
                  ? "  VERDICT: the face is not reading against its own plate."
                  : "  VERDICT: the face reads over the plate.")

            // THE DENSITY BENCH. Same window, same reader, same run: render the
            // cloud at the width the point size was tuned at, and at the home's
            // width, and require the coverage to agree. If it does, point size
            // scaling with the layer preserves density and the home's face is
            // as dense as the island's by construction rather than by hope.
            let tuned = FaceUniforms.tunedAtPoints
            let homeWidth = h.faceRect.width
            h.setFaceWidth(tuned)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                defer { h.setFaceWidth(min(screen.frame.width, screen.frame.height) * 0.62) }
                guard let img2 = GlassGuard.windowImage(h.groundWindow) else { return }
                let f2 = h.faceRect
                let inner2 = CGRect(x: f2.midX - f2.width / 2.82842712,
                                    y: f2.midY - f2.height / 2.82842712,
                                    width: f2.width / 1.41421356,
                                    height: f2.height / 1.41421356)
                let small = GlassGuard.luma(img2, viewSize: size, rect: inner2,
                                            brighterThan: margin)
                let spct = small.total > 0
                    ? Double(small.brighter) / Double(small.total) * 100 : 0
                print("")
                print("  density bench — the same cloud at two widths, one reader")
                print(String(format: "  at %.0f pt (tuned)  %.2f%% above plate  mean luma %.4f",
                             tuned, spct, small.mean))
                print(String(format: "  at %.0f pt (home)   %.2f%% above plate  mean luma %.4f",
                             homeWidth, fpct, faceL.mean))
                let ratio = spct > 0 ? fpct / spct : 0
                print(String(format: "  home / tuned       %.2fx  (1.00 would be density preserved)",
                             ratio))
                if ratio < 0.75 {
                    print("  the home's face is SPARSER than the size its point count was")
                    print("  chosen at. Scaling point size with the layer does not fully")
                    print("  recover density, and the shortfall is stated rather than rounded.")
                }
            }
        }
    }

    // SPIKE-013 §1, the sudo-free half. Five phases, each one differing from
    // the one before by exactly ONE thing, so a delta belongs to that thing.
    if args.contains("--cost-check") {
        let per = args.firstIndex(of: "--cost-seconds").flatMap { i -> Double? in
            i + 1 < args.count ? Double(args[i + 1]) : nil
        } ?? 15
        HomeCost.baselinePids()
        let frames: () -> Int = { h.framesDrawn }

        var cover: NSWindow?
        func canOcclude() -> Bool { SpaceWatch.fingerprint().isEmpty }
        func occlude() {
            let w = NSWindow(contentRect: (NSScreen.main ?? screen).frame,
                             styleMask: [.borderless], backing: .buffered, defer: false)
            w.collectionBehavior = [.managed]
            w.level = .normal
            w.isOpaque = true
            w.backgroundColor = .black
            w.animationBehavior = .none
            w.orderFrontRegardless()
            cover = w
        }

        func report() {
            cover?.orderOut(nil)
            let r = HomeCost.readings
            func f(_ n: String) -> HomeCost.Reading? { r.first { $0.name == n } }
            print("")
            print("  SPIKE-013 §1 — the composite's cost and the presence law")
            print("  " + String(repeating: "─", count: 68))
            print("  power source   \(HomeCost.powerSource())")
            print("  reading        our process tree (this pid + WebKit helpers"
                + " that appeared after us)")
            print("  phase length   \(Int(per)) s each — NOT the protocol's 10 min,"
                + " which is a POWER duration")
            print("")
            // EVERY RUN, before any aggregate. A mean hides the run that did
            // nothing, and a run that did nothing is a bug rather than a low
            // number -- SPIKE-001 §3.2 already recorded that the mean of a
            // coexistence test hides the moment it fails.
            print("  every phase, in order taken")
            for x in r {
                print("  " + HomeCost.pad(x.name, 14)
                    + HomeCost.pad(String(format: "%.3f", x.cpu), 9)
                    + HomeCost.pad(String(format: "%.1f fps", x.fps), 12)
                    + "\(x.frames) frames")
            }
            print("")
            print("  phase          CPU % mean [lo … hi]        fps    runs")
            var seen: [String] = []
            for x in r where !seen.contains(x.name) {
                seen.append(x.name)
                guard let a = HomeCost.aggregate(x.name) else { continue }
                let fps = r.filter { $0.name == x.name }.map(\.fps)
                let fmean = fps.reduce(0, +) / Double(fps.count)
                print("  " + HomeCost.pad(x.name, 14)
                    + HomeCost.pad(String(format: "%.3f [%.3f … %.3f]", a.mean, a.lo, a.hi), 24)
                    + HomeCost.pad(String(format: "%.1f", fmean), 7)
                    + HomeCost.pad("\(a.n)", 6) + x.note)
            }
            print("")
            if let a = HomeCost.aggregate("centre"), let b = HomeCost.aggregate("composite") {
                // The MEAN of centre, not its first sample. Differencing one
                // reading against a three-run mean mixes the units of the answer.
                print("  THE COMPOSITE'S COST   "
                    + String(format: "%+.3f", b.mean - a.mean)
                    + "% CPU  (composite − centre, means)")
                print("  One axis. GPU and package power are NOT in it.")
            }
            print("")
            // §8 pre-registered this BEFORE the reading existed, which is the
            // only reason it can be read as a result rather than a description.
            if let c = HomeCost.aggregate("centre"), let d = HomeCost.aggregate("dispersed") {
                print("  criterion 2  DISPERSED ≤ CENTRE, pre-registered in §8")
                print("               CPU over \(c.n) run(s) each, % of one core")
                print("               centre     "
                    + String(format: "%.3f  [%.3f … %.3f]", c.mean, c.lo, c.hi))
                print("               dispersed  "
                    + String(format: "%.3f  [%.3f … %.3f]", d.mean, d.lo, d.hi))
                // Ranges that overlap mean the axis cannot tell them apart. That
                // is neither a pass nor a fail; calling it either would be
                // reading a result out of noise.
                let separated = d.hi < c.lo || d.lo > c.hi
                if !separated {
                    print("               INCONCLUSIVE on CPU — the two ranges OVERLAP, so")
                    print("               this axis cannot separate the tiers at all. §3 says")
                    print("               the requirement is not relaxed to 'about the same',")
                    print("               and it is equally not MET by 'about the same'.")
                } else if d.hi < c.lo {
                    print("               PASS on CPU — dispersed is strictly below centre")
                } else {
                    print("               FAIL on CPU — dispersed is strictly above centre")
                }
                print("               GPU and package power are the axes that would settle")
                print("               it, and they need sudo. §3: every axis.")
            }
            print("")
            if let ab = f("absent") {
                print(ab.frames == 0
                      ? "  criterion 3  ABSENT draws zero — PASS, 0 frames attempted"
                      : "  criterion 3  ABSENT draws zero — FAIL, \(ab.frames) frames")
            }
            if let oc = f("occluded") {
                print(oc.frames == 0
                      ? "  criterion 4  occluded draws zero — PASS, 0 frames attempted"
                      : "  criterion 4  occluded draws zero — FAIL, \(oc.frames) frames")
                print("               \(h.occlusionProvenance)")
            } else {
                print("  criterion 4  NOT RUN — needs a Desktop with none of the owner's")
                print("               windows on it, because forcing occlusion means")
                print("               covering the whole display in black.")
            }
            print("")
            print("  STILL BLOCKED: criteria 1, 5 and 6 need GPU, package power and")
            print("  battery drain. powermetrics needs sudo.")
            print("  " + String(repeating: "═", count: 68))
            exit(0)
        }

        // Each step differs from the one before by exactly one thing.
        typealias Step = (String, String, () -> Void)
        let repeats = args.firstIndex(of: "--cost-repeats").flatMap { i -> Int? in
            i + 1 < args.count ? Int(args[i + 1]) : nil
        } ?? 3
        let tiers: [Step] = [
            ("centre",    "§8 Centre — head, full amplitude",  { h.setTier(.centre) }),
            ("attendant", "§8 Attendant — corner, 0.45 amp",   { h.setTier(.attendant) }),
            ("dispersed", "§8 Dispersed — attractor released", { h.setTier(.dispersed) }),
            ("absent",    "§8 Absent — no face, NO TIMER",     { h.setTier(.absent) }),
        ]
        // INTERLEAVED, not blocked. Three centres then three dispersals would
        // put any drift in the machine's own load straight into the difference
        // being measured.
        var steps: [Step] = [
            ("baseline",  "island only, ground not rendering", { h.stopRendering() })
        ]
        for _ in 0..<max(1, repeats) { steps.append(contentsOf: tiers) }
        var i = 0
        func step() {
            guard i < steps.count else { composite(); return }
            let (name, note, setup) = steps[i]; i += 1
            setup()
            // Dispersal is a 1.1 s motion; measuring across it would measure the
            // transition rather than the tier.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) {
                HomeCost.phase(name, seconds: per, note: note, frames: frames, then: step)
            }
        }
        func composite() {
            h.setTier(.centre)
            h.chrome.mount(over: h.hostView, faceRect: h.faceRect,
                           screen: NSScreen.main ?? screen, backdrop: nil) { v in
                guard v.mayMountChrome else {
                    print("  cost run ABORTED — \(v.line)")
                    print("  A composite that could not be mounted has no cost to report.")
                    exit(2)
                }
                HomeCost.phase("composite", seconds: per,
                               note: "+ transparent chrome over Centre", frames: frames) {
                    guard canOcclude() else {
                        print("")
                        print("  occluded phase SKIPPED — this Desktop has the owner's windows")
                        print("  on it, and forcing occlusion means covering the whole screen.")
                        report(); return
                    }
                    print("  occluding — this Desktop goes black for one phase")
                    occlude()
                    HomeCost.phase("occluded", seconds: per,
                                   note: "covered — the deliberate stop",
                                   frames: frames, then: report)
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { step() }
    }

    // FIRST LIGHT. The chrome mounts over the field, and only if GlassGuard
    // says the glass is actually clear -- SPIKE-013 SS0 is why that is a
    // question at all, and UNREADABLE is not a pass.
    if args.contains("--chrome") {
        let backdrop = args.firstIndex(of: "--mode").flatMap { i -> URL? in
            guard i + 1 < args.count, let m = Ambience.mode(named: args[i + 1]),
                  let dir = Ambience.wallpaperDir() else { return nil }
            return m.wallpaper(in: dir)
        }
        h.chrome.mount(over: h.hostView, faceRect: h.faceRect,
                       screen: NSScreen.main ?? screen, backdrop: backdrop) { v in
            print("  \(v.line)")
            if !v.mayMountChrome {
                let m = "home: chrome REFUSED — \(v.line). The field is up and bare "
                      + "rather than under a white rectangle.\n"
                FileHandle.standardError.write(m.data(using: .utf8)!)
            } else {
                print("  chrome: mounted over the field")
                // §10: the main menu dims while the system Dock is over it.
                h.onDockVisibilityChange = { [weak h] up in
                    h?.chrome.setDockUp(up)
                    print("  system dock \(up ? "up — main menu dims to 30%" : "down")")
                }
                h.watchSystemDock()
                h.startDockReconciler()
                let c = h.chrome
                print(c.cardAdapted
                      ? String(format: "  card: backdrop luma %.3f → fill %.3f → ground %.3f "
                                     + "(ratio proxy, not APCA)",
                               c.cardBackdropLuma, c.cardFill,
                               c.cardBackdropLuma * (1 - c.cardFill))
                      : "  card: backdrop UNSAMPLED — tier fill only, unadapted")
            }
        }
    }

    let fp = SpaceWatch.fingerprint()
    h.present()
    print("home: ground on the ACTIVE Desktop — \(fp.count) foreign windows here")
    print("      \(Ambience.modes().count) modes loaded from modes.json")
    if Ambience.repoRoot() == nil {
        print("      *** no repo found: wallpapers and modes are UNAVAILABLE ***")
    }
}

if let s = seconds {
    // A spike must not be able to leave a panel stuck over the menu bar.
    Timer.scheduledTimer(withTimeInterval: s, repeats: false) { _ in
        home?.stopRendering()
        NSApp.terminate(nil)
    }
}
app.run()
