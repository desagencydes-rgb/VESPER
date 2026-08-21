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

// MARK: - Geometry, from docs/design/ANNEX-island-geometry.md

enum State: Int { case dormant, shoulders, expandedRest, expandedSpeaking }

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
        case .expandedRest:     return Metrics(width: 624, height: 192, fillet: 24, radius: 24)
        case .expandedSpeaking: return Metrics(width: 624, height: 280, fillet: 24, radius: 48)
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
    // used to be drawn here were shape wearing the costume of data.
    var gauges: [CGFloat] = []

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
        case .expandedRest, .expandedSpeaking: drawExpanded(ctx, w: w, h: h)
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
            let s: CGFloat = 20 * markScale
            m.draw(in: NSRect(x: pad + (20 - s) / 2, y: (h - s) / 2, width: s, height: s),
                   from: .zero, operation: .sourceOver, fraction: markBrightness)
        }
        guard !gauges.isEmpty else { return }
        let gw: CGFloat = 15, gap: CGFloat = 9
        var x = w - metrics.fillet - 14 - (gw * CGFloat(gauges.count) + gap * CGFloat(gauges.count - 1))
        for frac in gauges {
            let rect = NSRect(x: x, y: (h - gw) / 2, width: gw, height: gw)
            ctx.setLineWidth(2)
            ctx.setStrokeColor(NSColor(white: 1, alpha: 0.16).cgColor)
            ctx.addEllipse(in: rect.insetBy(dx: 1, dy: 1)); ctx.strokePath()
            ctx.setStrokeColor(IslandView.ember.cgColor)
            ctx.addArc(center: NSPoint(x: rect.midX, y: rect.midY), radius: gw / 2 - 1,
                       startAngle: .pi / 2, endAngle: .pi / 2 - 2 * .pi * frac, clockwise: true)
            ctx.strokePath()
            x += gw + gap
        }
    }

    private func drawExpanded(_ ctx: CGContext, w: CGFloat, h: CGFloat) {
        let inset = metrics.fillet
        // §9: the mark is on the left shoulder in EVERY island state, and the
        // shoulder band is y ∈ [0, inset] -- the one band that must clear the
        // camera. The mark sits far left, so it does; nothing else goes here.
        if let m = mark {
            let s: CGFloat = 20 * markScale
            m.draw(in: NSRect(x: inset + 14 + (20 - s) / 2,
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
            let value = text(c.value, 9, IslandView.dim)
            label.draw(at: NSPoint(x: x + (colW - label.size().width) / 2, y: rowTop - 15))
            value.draw(at: NSPoint(x: x + (colW - value.size().width) / 2, y: rowTop - 28))
        }

        // The ground, one step in.
        let bodyTop = rowTop - 38
        let body = NSRect(x: inset + 8, y: 14, width: w - (inset + 8) * 2, height: bodyTop - 14)
        if body.height > 20 {
            let rr = CGPath(roundedRect: body, cornerWidth: 18, cornerHeight: 18, transform: nil)
            ctx.addPath(rr)
            ctx.setFillColor(IslandView.ground.cgColor)
            ctx.fillPath()
            if columns.isEmpty {
                // Nothing is wired yet, and an empty body says so rather than
                // showing a plausible instrument panel. INV-HW-2: UNKNOWN means
                // UNAVAILABLE, and a surface that renders stale or invented state
                // is worse than one that renders none.
                let msg = text("no projection — backend not running", 10, IslandView.dim)
                msg.draw(at: NSPoint(x: body.midX - msg.size().width / 2, y: body.midY - 6))
            }
        }
    }

    var safeInset: CGFloat = 32
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
    private let snapshotPath: String

    init(screen: NSScreen, snapshotPath: String) {
        self.screen = screen
        self.snapshotPath = snapshotPath
        geo = Geometry(screen: screen)
        let m = geo.metrics(.dormant)
        sw = Spring(m.width); sh = Spring(m.height)
        view = IslandView()
        view.safeInset = geo.inset
        view.mark = NSImage(contentsOfFile:
            FileManager.default.currentDirectoryPath + "/docs/design/assets/vesper-icon.png")

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
        panel.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.statusWindow)) + 1)
        // Present on every Space and over fullscreen apps -- in fullscreen the
        // notch region goes black anyway, so the weld is free there.
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.contentView = view
        applyFrame(width: m.width, height: m.height)
        panel.orderFrontRegardless()
        retrack()
        reload()
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
        let m = geo.metrics(s)
        sw.target = m.width; sh.target = m.height
        view.metrics = m
        if timer == nil {
            let t = Timer(timeInterval: 1.0 / 120.0, repeats: true) { [weak self] _ in self?.tick() }
            RunLoop.main.add(t, forMode: .common); timer = t
        }
    }

    private func tick() {
        let a = sw.step(1.0 / 120.0), b = sh.step(1.0 / 120.0)
        applyFrame(width: sw.value, height: sh.value)
        if !a && !b { timer?.invalidate(); timer = nil; retrack() }
    }

    func reload() {
        view.columns = loadColumns(snapshotPath)
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

    @objc func mouseEntered(with event: NSEvent) { reload(); go(.expandedRest) }
    @objc func mouseExited(with event: NSEvent)  { go(.shoulders) }
}

// MARK: - main

let args = CommandLine.arguments
let seconds = args.firstIndex(of: "--seconds").flatMap { i -> Double? in
    i + 1 < args.count ? Double(args[i + 1]) : nil
}
let snapshot = args.firstIndex(of: "--snapshot").flatMap { i -> String? in
    i + 1 < args.count ? args[i + 1] : nil
} ?? "/tmp/vesper-island.json"

let app = NSApplication.shared
// .accessory: no Dock tile, no menu bar of our own. The island is presence.
app.setActivationPolicy(.accessory)

guard let screen = NSScreen.screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? NSScreen.main else {
    FileHandle.standardError.write("no screen\n".data(using: .utf8)!); exit(1)
}
let controller = Controller(screen: screen, snapshotPath: snapshot)
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
if args.contains("--expand") { controller.reload(); controller.go(.expandedRest) }

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
