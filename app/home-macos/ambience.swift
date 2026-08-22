// VESPER — F2, first slice: the ambience ground.
//
// F1 verified the plane this sits on: level normal-1, `.managed`, full screen
// frame, no appearance animation. Nothing here re-litigates that; it fills it.
//
// WHAT THIS IS AND IS NOT. This is the WALLPAPER half of the field layer. The
// face is the other half and is Metal (`FaceRenderer.swift`, already measured at
// 5-7% CPU for 39,805 points) and is not here. Splitting them is deliberate:
// SPIKE-013 is about what the two cost composited, and a spike whose two halves
// were never seen apart cannot attribute a number to either.
//
// IT IS ALSO VISIBLY AN INSTRUMENT, not the home. The repo's rule for Phase F is
// that a fixture must be visibly a fixture -- the whole INV-HW-2 culture leaks
// the moment a demo renders in the same style as the real thing. So the caption
// block says F2 and reports provenance, and no part of this pretends to be a
// card.
//
// Two entry points, and the second one is why this file is shaped this way:
//
//   (no args)          the live ground, cycling the eleven modes on a timer
//   --stills <dir>     the same composite rendered OFFSCREEN to PNG
//
// The offscreen path exists so the composition can be CHECKED rather than
// described. Reading it back off the screen would need Screen Recording, and a
// permission granted to a loose binary is granted to the terminal that launched
// it -- build.sh argues that at length. Rendering the same draw code to a bitmap
// costs no permission and produces the same pixels.

import AppKit

// ---------------------------------------------------------------------------
// The eleven modes, read from the file that owns them. Never restated here:
// modes.json is what every surface reads, and a second copy of a colour is a
// second thing to get out of sync.
// ---------------------------------------------------------------------------

struct Mode {
    let name, key, accent, ground, ink, prov, when: String
    let light: Bool
    var wallpaper: String { name.lowercased() }
}

func repoRoot() -> String {
    // The binary lives at <repo>/app/home-macos/, so the repo is two up. Derived
    // rather than assumed from the working directory, because F1b already
    // produced two log files with one name by trusting cwd.
    URL(fileURLWithPath: CommandLine.arguments[0])
        .deletingLastPathComponent()   // home-macos
        .deletingLastPathComponent()   // app
        .deletingLastPathComponent().path
}

func loadModes() -> [Mode] {
    let p = repoRoot() + "/docs/design/source/modes.json"
    guard let d = FileManager.default.contents(atPath: p),
          let arr = try? JSONSerialization.jsonObject(with: d) as? [[String: Any]]
    else { FileHandle.standardError.write("cannot read \(p)\n".data(using: .utf8)!); exit(2) }
    return arr.map {
        Mode(name: $0["mode"] as? String ?? "?",
             key: $0["key"] as? String ?? "?",
             accent: $0["accent"] as? String ?? "#888888",
             ground: $0["ground"] as? String ?? "#111111",
             ink: $0["ink"] as? String ?? "#eeeeee",
             prov: $0["prov"] as? String ?? "?",
             when: $0["when"] as? String ?? "",
             light: $0["light"] as? Bool ?? false)
    }
}

func hex(_ s: String) -> NSColor {
    var v: UInt64 = 0
    Scanner(string: s.replacingOccurrences(of: "#", with: "")).scanHexInt64(&v)
    return NSColor(srgbRed: CGFloat((v >> 16) & 255) / 255,
                   green: CGFloat((v >> 8) & 255) / 255,
                   blue: CGFloat(v & 255) / 255, alpha: 1)
}

// ---------------------------------------------------------------------------
// The composite. ONE function, used by both the live window and the offscreen
// render, so what gets checked is what gets shown.
// ---------------------------------------------------------------------------

/// Aspect-FILL with a centre crop. The wallpapers are 1672x941 (16:9) and the
/// screen is 1728x1117 (1.547), so filling costs width. How much is measured
/// and printed rather than waved at -- it is the evidence for whether these
/// need re-rendering at the display's own aspect, which is an open question
/// for the owner and not a call to make here.
func drawWallpaper(_ img: NSImage, in rect: NSRect) -> (kept: Double, axis: String) {
    let iw = img.size.width, ih = img.size.height
    let scale = max(rect.width / iw, rect.height / ih)
    let w = iw * scale, h = ih * scale
    let dst = NSRect(x: rect.midX - w / 2, y: rect.midY - h / 2, width: w, height: h)
    img.draw(in: dst, from: .zero, operation: .copy, fraction: 1.0)
    // What fraction of the source survives the crop, on the axis that lost.
    let keptW = rect.width / w, keptH = rect.height / h
    return keptW < keptH ? (keptW, "width") : (keptH, "height")
}

@discardableResult
func drawScene(_ m: Mode, in rect: NSRect, index: Int, total: Int) -> String {
    var report = ""
    let wpDir = repoRoot() + "/docs/design/assets/wallpapers/"
    var loaded = false
    for ext in ["png", "jpg", "avif"] {
        let path = wpDir + m.wallpaper + "." + ext
        if FileManager.default.fileExists(atPath: path), let img = NSImage(contentsOfFile: path) {
            let (kept, axis) = drawWallpaper(img, in: rect)
            report = String(format: "%-11s %-6s %4.0fx%-4.0f  keeps %3.0f%% of %s",
                            (m.name as NSString).utf8String!, (ext as NSString).utf8String!,
                            img.size.width, img.size.height, kept * 100,
                            (axis as NSString).utf8String!)
            loaded = true
            break
        }
    }
    if !loaded {
        hex(m.ground).setFill(); rect.fill()
        report = "\(m.name)  *** NO WALLPAPER LOADED ***"
    }

    // ── the caption block ────────────────────────────────────────────────────
    // Visibly an instrument. It reports the mode, its accent WITH ITS
    // PROVENANCE, and nothing that could be mistaken for a card.
    // The box is MEASURED from its content, not guessed. At a fixed 560 the
    // provenance note on the three curated modes ran out past the rounded
    // corner and sat on the wallpaper -- caught by rendering it and looking,
    // which is the entire reason --stills exists.
    let noteText = m.prov == "measured" ? ""
        : "— accent is not this picture's light source, by decision"
    let noteW = noteText.isEmpty ? 0 : (noteText as NSString).size(withAttributes: [
        .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)]).width
    let whenW = (m.when as NSString).size(withAttributes: [
        .font: NSFont.systemFont(ofSize: 12, weight: .regular)]).width
    let pad: CGFloat = 44
    let bw = max(560, 26 + 176 + 26 + noteW + 26, 26 + whenW + 26)
    let bh: CGFloat = 150
    let box = NSRect(x: pad, y: pad, width: bw, height: bh)
    let glass = NSBezierPath(roundedRect: box, xRadius: 22, yRadius: 22)
    hex(m.ground).withAlphaComponent(m.light ? 0.82 : 0.72).setFill()
    glass.fill()
    hex(m.accent).withAlphaComponent(0.55).setStroke()
    glass.lineWidth = 1
    glass.stroke()

    let ink = hex(m.ink)
    func put(_ s: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat,
             _ w: NSFont.Weight, _ c: NSColor, mono: Bool = false) {
        let f = mono ? NSFont.monospacedSystemFont(ofSize: size, weight: w)
                     : NSFont.systemFont(ofSize: size, weight: w)
        (s as NSString).draw(at: NSPoint(x: x, y: y),
            withAttributes: [.font: f, .foregroundColor: c])
    }
    put("F2 · AMBIENCE CHECK — \(index + 1) of \(total)", box.minX + 26, box.maxY - 34, 10, .semibold,
        ink.withAlphaComponent(0.55), mono: true)
    put(m.name, box.minX + 26, box.maxY - 74, 30, .light, ink)
    put(m.when, box.minX + 26, box.maxY - 102, 12, .regular, ink.withAlphaComponent(0.72))

    // accent swatch, its hex, and whether that hex was MEASURED or CURATED.
    // The provenance is not decoration: `prov` is the difference between a
    // reading and a judgement call, and three of the eleven are judgement calls.
    let sw = NSRect(x: box.minX + 26, y: box.minY + 22, width: 26, height: 26)
    hex(m.accent).setFill(); NSBezierPath(ovalIn: sw).fill()
    put(m.accent.uppercased(), sw.maxX + 12, sw.minY + 6, 13, .medium, ink, mono: true)
    let provColour = m.prov == "measured" ? ink.withAlphaComponent(0.72) : hex(m.accent)
    put(m.prov.uppercased(), sw.maxX + 108, sw.minY + 7, 11, .semibold, provColour, mono: true)
    if !noteText.isEmpty {
        put(noteText, sw.maxX + 176, sw.minY + 7, 11, .regular,
            ink.withAlphaComponent(0.6))
    }
    return report
}

// ---------------------------------------------------------------------------

let modes = loadModes()
let args = CommandLine.arguments

if let i = args.firstIndex(of: "--stills") {
    // Offscreen. Same drawScene, no window, no permission, real pixels.
    let outDir = i + 1 < args.count ? args[i + 1] : "/tmp/vesper-ambience"
    try? FileManager.default.createDirectory(atPath: outDir,
        withIntermediateDirectories: true)
    let size = NSSize(width: 1728, height: 1117)   // this display, in points
    print("rendering \(modes.count) modes at \(Int(size.width))x\(Int(size.height)) → \(outDir)\n")
    for (n, m) in modes.enumerated() {
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil,
                pixelsWide: Int(size.width), pixelsHigh: Int(size.height),
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { continue }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let report = drawScene(m, in: NSRect(origin: .zero, size: size),
                               index: n, total: modes.count)
        NSGraphicsContext.restoreGraphicsState()
        let path = "\(outDir)/\(String(format: "%02d", n + 1))-\(m.name.lowercased()).png"
        if let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
        }
        print("  " + report)
    }
    print("\ndone")
    exit(0)
}

// --- the live ground -------------------------------------------------------
final class GroundView: NSView {
    var index = 0
    override func draw(_ dirty: NSRect) {
        drawScene(modes[index], in: bounds, index: index, total: modes.count)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard let screen = NSScreen.main else { fatalError("no screen") }

let ground = NSWindow(contentRect: screen.frame, styleMask: [.borderless],
                      backing: .buffered, defer: false)
ground.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
ground.collectionBehavior = [.managed]
ground.animationBehavior = .none          // F1: the desktop does not spring in
ground.isOpaque = true
let view = GroundView(frame: NSRect(origin: .zero, size: screen.frame.size))
ground.contentView = view
ground.orderFrontRegardless()

print("""

  VESPER — F2 ambience ground, live.
  Cycling \(modes.count) modes, 4 s each. Ctrl+C to stop.
  It sits BELOW your windows — the verified plane — so bring
  something to the front and it should not be able to cover it.

""")
var n = 0
Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { _ in
    n = (n + 1) % modes.count
    view.index = n
    view.needsDisplay = true
    print("  \(modes[n].name)")
}
app.run()
