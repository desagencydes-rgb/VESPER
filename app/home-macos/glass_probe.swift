// VESPER — SPIKE-013, restarted at its precondition.
//
// THE QUESTION. HOME-ARCHITECTURE §1.1 puts the home in one window with two
// layers: Metal below carrying the ambience and the face, a WKWebView above
// carrying the cards. That only works if the webview is TRANSPARENT where no
// card sits. Can it be, with PUBLIC API only?
//
// The public surface, read out of this machine's own SDK rather than from
// memory (MacOSX.sdk, macOS 26.5):
//
//   WKWebView.h:617  underPageBackgroundColor   macOS 12+   <- the only knob
//   WKWebView.h:607  "...the background color under the page's content, such
//                     as for scroll bouncing areas."
//   WebView.h:504    drawsBackground            <- PUBLIC, but on the LEGACY
//                     WebKit1 WebView, a different and deprecated class
//
// There is no macOS 26 addition; `grep macos(26` across WebKit's headers turns
// up Screen Time, instant back, obscured content insets and data restore, and
// nothing about background. So `underPageBackgroundColor` is the whole public
// surface, and whether it does the job is a measurement, not a reading.
//
// WHY THIS FILE EXISTS AT ALL — the two instruments that already failed.
//
//   takeSnapshot()     composites onto an OPAQUE bitmap. It returned alpha 1.00
//                      for a page that may well have been perfectly transparent.
//                      A precondition that fails for a page that is fine is as
//                      useless as one that passes for a page that is not.
//   cacheDisplay(in:)  draws the view tree THIS process owns. WebKit renders in
//                      com.apple.WebKit.WebContent, so the webview contributes
//                      its placeholder, not its content. That is what produced
//                      "OPAQUE (Δ 2.992)" -- a delta of nearly the maximum
//                      possible 3.0, which is the instrument's own artefact and
//                      not a page.
//
// Both are IN-PROCESS, and the content is not. So this instrument asks the
// WINDOW SERVER for the composite of our own window -- the only reader that
// sees every layer regardless of which process drew it.
//
// AND THE WINDOW SERVER'S ANSWER IS ALSO NOT TRUSTED ON ITS WORD.
// CGWindow.h:264 says: "If no windows meet the specified criteria, or the
// windows can't be read, then a TRANSPARENT BLACK IMAGE will be returned."
// Transparent black is exactly what "the webview is transparent" looks like.
// A blocked capture and a perfect success are the same pixel. So the run opens
// with three controls, and the third is the one both earlier instruments would
// have failed:
//
//   A1  ground only, split blue/red     capture reaches our window at all,
//                                       and pins which way up the buffer is
//   A2  ground clear, no webview        capture PRESERVES alpha
//   B1  webview painting opaque magenta capture SEES WEBKIT CONTENT
//
// If B1 does not come back magenta, this instrument is blind to the very thing
// it was built to look at and every reading after it is void. It aborts there
// rather than printing a verdict, which is what the first SPIKE-013 run did not
// do.
//
// AND THE FIRST RUN OF THIS FILE FAILED ITS OWN FIRST CONTROL, for a reason
// worth leaving in. It declared the ground as CGColor(red:0.063,...) -- device
// RGB -- and then asserted the capture would read #1030C0 back. It read
// #1249CC. Nothing was wrong with the capture: the window server composites in
// the display's space and this reader converts to sRGB, so an authored colour
// and a captured one are two different numbers for the same paint. The fix is
// not a wider tolerance. It is to stop declaring the reference at all: A1 now
// MEASURES what the ground reads as, and every later case is compared against
// that measurement. INV-HW-2 in a colour space.
//
// Build:  swiftc -O -swift-version 5 -target arm64-apple-macosx13.0 \
//                glass_probe.swift -o glass_probe
// The deployment target is deliberate: CGWindowListCreateImage is marked
// obsoleted=15.0 in the SDK. 13.0 is the bundle's own LSMinimumSystemVersion,
// so this is the floor the app already declares, not a floor invented here.

import AppKit
import WebKit
import Metal
import QuartzCore

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------

let LOG = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent()
    .appendingPathComponent("glass_probe_last_run.log").path
var logBuf = ""
func pad(_ s: String, _ n: Int) -> String {
    s.count >= n ? s : s + String(repeating: " ", count: n - s.count)
}

func say(_ l: String = "") {
    print(l)
    logBuf += l + "\n"
    try? logBuf.write(toFile: LOG, atomically: true, encoding: .utf8)
}

let ARGS = CommandLine.arguments
let FLOAT_LEVEL = ARGS.contains("--float")
let HOLD = ARGS.firstIndex(of: "--hold").flatMap { i -> Double? in
    i + 1 < ARGS.count ? Double(ARGS[i + 1]) : nil
} ?? 0

// ---------------------------------------------------------------------------
// Colours. Chosen to be unmistakable and unlike anything the system paints:
// a white page background, a black desktop and a grey panel all read as
// clearly not-these.
// ---------------------------------------------------------------------------

let GROUND_BLUE = CGColor(red: 0.063, green: 0.188, blue: 0.753, alpha: 1)  // #1030C0
let GROUND_RED  = CGColor(red: 0.753, green: 0.188, blue: 0.063, alpha: 1)  // #C03010
let PX_CLEAR = Px(r: 0, g: 0, b: 0, a: 0)

/// What the ground ACTUALLY reads as through this capture path, filled in by
/// A1 and used by every case after it. Not declared here, because the run above
/// proved a declared colour and a captured one are different numbers.
var REF_BLUE: Px?

struct Px {
    var r = 0.0, g = 0.0, b = 0.0, a = 0.0
    var label: String {
        a < 0.004 ? "transparent" :
        String(format: "#%02X%02X%02X α%.2f",
               Int(r * 255 + 0.5), Int(g * 255 + 0.5), Int(b * 255 + 0.5), a)
    }
    /// Per-channel, not a summed distance. A summed distance lets a large error
    /// in one channel hide under three small ones.
    func near(_ o: Px, _ tol: Double = 0.05) -> Bool {
        guard abs(a - o.a) <= tol else { return false }
        if a < 0.004 && o.a < 0.004 { return true }   // both transparent: rgb is meaningless
        return abs(r - o.r) <= tol && abs(g - o.g) <= tol && abs(b - o.b) <= tol
    }
}

// ---------------------------------------------------------------------------
// The window under test, configured as HomeController configures the ground:
// borderless, transparent, below normal, Managed, no animation. Small rather
// than full-screen -- the owner is working on this machine, and window SIZE is
// not a variable in "does WebKit paint a background".
// ---------------------------------------------------------------------------

let VIEW = CGSize(width: 640, height: 420)

/// Flipped so layer geometry and the captured buffer and the HTML all agree on
/// where the top is. Three coordinate systems disagreeing is how an orientation
/// bug becomes a transparency finding.
final class Ground: NSView {
    override var isFlipped: Bool { true }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard let screen = NSScreen.main else { fatalError("no screen") }

let origin = CGPoint(x: screen.frame.minX + 120,
                     y: screen.frame.maxY - VIEW.height - 140)
let win = NSWindow(contentRect: CGRect(origin: origin, size: VIEW),
                   styleMask: [.borderless], backing: .buffered, defer: false)
win.level = FLOAT_LEVEL ? .floating
                        : NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
win.collectionBehavior = [.managed]
win.animationBehavior = .none
win.isOpaque = false
win.backgroundColor = .clear
win.hasShadow = false
win.ignoresMouseEvents = true

let ground = Ground(frame: CGRect(origin: .zero, size: VIEW))
ground.wantsLayer = true
ground.layer?.backgroundColor = CGColor(gray: 0, alpha: 0)
win.contentView = ground
win.orderFrontRegardless()

// ---------------------------------------------------------------------------
// The grounds
// ---------------------------------------------------------------------------

enum GroundKind { case split, blue, clear, metalBlue }

var splitTop: CALayer?
var splitBottom: CALayer?
var metalLayer: CAMetalLayer?

func setGround(_ kind: GroundKind) {
    splitTop?.removeFromSuperlayer(); splitTop = nil
    splitBottom?.removeFromSuperlayer(); splitBottom = nil
    metalLayer?.removeFromSuperlayer(); metalLayer = nil
    ground.layer?.backgroundColor = CGColor(gray: 0, alpha: 0)

    switch kind {
    case .clear:
        break
    case .blue:
        ground.layer?.backgroundColor = GROUND_BLUE
    case .split:
        let t = CALayer(); t.frame = CGRect(x: 0, y: 0, width: VIEW.width, height: VIEW.height / 2)
        t.backgroundColor = GROUND_BLUE
        let b = CALayer(); b.frame = CGRect(x: 0, y: VIEW.height / 2, width: VIEW.width, height: VIEW.height / 2)
        b.backgroundColor = GROUND_RED
        ground.layer?.addSublayer(t); ground.layer?.addSublayer(b)
        splitTop = t; splitBottom = b
    case .metalBlue:
        // A CAMetalLayer, not a CALayer with a colour on it. The home's ground
        // IS a Metal layer, and "a webview over a Metal layer" is not proven by
        // "a webview over a coloured layer" -- different layer type, different
        // path through the compositor.
        guard let dev = MTLCreateSystemDefaultDevice(),
              let q = dev.makeCommandQueue() else {
            say("  metal: NO DEVICE — case skipped"); return
        }
        let m = CAMetalLayer()
        m.device = dev
        m.pixelFormat = .bgra8Unorm
        m.framebufferOnly = false
        m.isOpaque = true
        m.contentsScale = screen.backingScaleFactor
        m.frame = CGRect(origin: .zero, size: VIEW)
        m.drawableSize = CGSize(width: VIEW.width * screen.backingScaleFactor,
                                height: VIEW.height * screen.backingScaleFactor)
        ground.layer?.addSublayer(m)
        metalLayer = m
        // One frame of flat blue. Enough: the question is whether the webview
        // paints OVER it, not what it paints.
        if let d = m.nextDrawable(), let cb = q.makeCommandBuffer() {
            let rp = MTLRenderPassDescriptor()
            rp.colorAttachments[0].texture = d.texture
            rp.colorAttachments[0].loadAction = .clear
            rp.colorAttachments[0].storeAction = .store
            rp.colorAttachments[0].clearColor = MTLClearColor(red: 0.063, green: 0.188,
                                                              blue: 0.753, alpha: 1)
            cb.makeRenderCommandEncoder(descriptor: rp)?.endEncoding()
            cb.present(d)
            cb.commit()
            cb.waitUntilCompleted()
        } else {
            say("  metal: NO DRAWABLE — the layer would have drawn nothing")
        }
    }
    CATransaction.flush()
}

// ---------------------------------------------------------------------------
// The pages
// ---------------------------------------------------------------------------

/// The control: unmistakably opaque, edge to edge. If the capture cannot see
/// this, it cannot see anything WebKit draws.
let PAGE_MAGENTA = """
<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#ff00ff}</style>
"""

/// Nothing at all, transparently. Any non-ground pixel here was painted by the
/// webview and by nobody else.
let PAGE_EMPTY = """
<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:transparent}</style>
"""

/// The real chrome: iOS-26 glass over the ground, with the top-left quadrant
/// deliberately EMPTY. The empty region is where transparency is read; the card
/// is where "the blur has something real behind it" is read.
let PAGE_GLASS = """
<!doctype html><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:transparent;overflow:hidden;
            font-family:-apple-system,system-ui,sans-serif;color:#f4e6dc}
  .card{position:absolute;left:300px;top:200px;width:280px;height:170px;
        box-sizing:border-box;border-radius:22px;padding:20px;
        background:rgba(255,255,255,.10);
        -webkit-backdrop-filter:blur(26px) saturate(160%);
        backdrop-filter:blur(26px) saturate(160%);
        border:1px solid rgba(255,255,255,.16)}
  .k{font-size:10px;letter-spacing:.14em;text-transform:uppercase;opacity:.6}
  .v{font-size:30px;font-weight:200;margin-top:8px}
</style>
<div class="card"><div class="k">context</div><div class="v">UNAVAILABLE</div></div>
"""

// ---------------------------------------------------------------------------
// The reader
// ---------------------------------------------------------------------------

/// Top-left origin, in view points. P_EMPTY is in the quadrant every page
/// leaves bare.
let P_EMPTY = CGPoint(x: 60, y: 60)
let P_LOWER = CGPoint(x: 60, y: 360)      // below the split line, for A1
let P_CARD  = CGPoint(x: 440, y: 285)     // inside PAGE_GLASS's card

func capture() -> CGImage? {
    CGWindowListCreateImage(.null, [.optionIncludingWindow],
                            CGWindowID(win.windowNumber),
                            [.boundsIgnoreFraming, .bestResolution])
}

func samples(_ img: CGImage, _ pts: [CGPoint]) -> [Px] {
    let w = img.width, h = img.height
    guard w > 0, h > 0 else { return [] }
    let n = w * h * 4
    let data = UnsafeMutablePointer<UInt8>.allocate(capacity: n)
    defer { data.deallocate() }
    data.initialize(repeating: 0, count: n)
    guard let ctx = CGContext(data: data, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: w * 4,
                              space: CGColorSpace(name: CGColorSpace.sRGB)!,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                                        | CGBitmapInfo.byteOrder32Big.rawValue)
    else { return [] }
    ctx.clear(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
    let sx = Double(w) / Double(VIEW.width), sy = Double(h) / Double(VIEW.height)
    return pts.map { p in
        let x = min(w - 1, max(0, Int(Double(p.x) * sx)))
        let y = min(h - 1, max(0, Int(Double(p.y) * sy)))
        let o = (y * w + x) * 4
        let a = Double(data[o + 3]) / 255
        guard a > 0 else { return PX_CLEAR }
        return Px(r: Double(data[o]) / 255 / a,
                  g: Double(data[o + 1]) / 255 / a,
                  b: Double(data[o + 2]) / 255 / a, a: a)
    }
}

// ---------------------------------------------------------------------------
// The matrix
// ---------------------------------------------------------------------------

struct Case {
    let id: String
    let what: String
    let ground: GroundKind
    let page: String?          // nil: no webview in the hierarchy at all
    let knobs: (WKWebView) -> Void
    let control: Bool          // a control aborts the run when it fails
    /// Given (empty, lower, card), returns nil to pass or the reason it failed.
    let check: ((Px, Px, Px) -> String?)?
    /// The legacy WebKit1 `WebView` instead of `WKWebView`. Declared last with a
    /// default so every row above is unchanged.
    var legacy: Bool = false
}

func noKnobs(_ w: WKWebView) {}

let CASES: [Case] = [
    Case(id: "A1", what: "ground only, blue over red — does the capture reach our window",
         ground: .split, page: nil, knobs: noKnobs, control: true, check: { e, l, _ in
             if e.a < 0.98 || l.a < 0.98 { return "an opaque window read back transparent" }
             if e.near(l, 0.20) { return "top and bottom read alike — this is not our window" }
             if !(e.b > e.r && l.r > l.b) { return "top is not the blue half, or bottom is not the red half — the buffer is not the way up this file assumes" }
             REF_BLUE = e
             return nil
         }),
    Case(id: "A2", what: "ground clear, no webview — does the capture preserve alpha",
         ground: .clear, page: nil, knobs: noKnobs, control: true, check: { e, _, _ in
             e.a < 0.02 ? nil : "a window with nothing in it read \(e.label)"
         }),
    Case(id: "B1", what: "webview painting #FF00FF — does the capture SEE WebKit",
         ground: .blue, page: PAGE_MAGENTA, knobs: noKnobs, control: true, check: { e, _, _ in
             guard let g = REF_BLUE else { return "A1 left no reference" }
             if e.near(g) { return "read the GROUND (\(e.label)) through a page painted edge to edge in magenta" }
             if !(e.r > 0.5 && e.g < 0.35 && e.b > 0.5) { return "read \(e.label), which is not magenta" }
             return nil
         }),

    Case(id: "C1", what: "default WKWebView, page background: transparent",
         ground: .blue, page: PAGE_EMPTY, knobs: noKnobs, control: false, check: nil),
    Case(id: "C2", what: "+ underPageBackgroundColor = .clear",
         ground: .blue, page: PAGE_EMPTY,
         knobs: { $0.underPageBackgroundColor = .clear }, control: false, check: nil),
    Case(id: "C3", what: "+ underPageBackgroundColor = .clear, layer.isOpaque = false",
         ground: .blue, page: PAGE_EMPTY,
         knobs: { $0.underPageBackgroundColor = .clear; $0.layer?.isOpaque = false },
         control: false, check: nil),
    Case(id: "C4", what: "uPBC = .clear over a CLEAR ground — the whole stack",
         ground: .clear, page: PAGE_EMPTY,
         knobs: { $0.underPageBackgroundColor = .clear }, control: false, check: nil),
    Case(id: "C5", what: "uPBC = .clear, the real glass chrome",
         ground: .blue, page: PAGE_GLASS,
         knobs: { $0.underPageBackgroundColor = .clear }, control: false, check: nil),
    Case(id: "C6", what: "uPBC = .clear over a CAMetalLayer — the home's actual ground",
         ground: .metalBlue, page: PAGE_GLASS,
         knobs: { $0.underPageBackgroundColor = .clear }, control: false, check: nil),

    // NOT A SHIPPING OPTION. `_setDrawsBackground:` is private, and
    // ISLAND-ARCHITECTURE §2 rules out KVC onto non-public properties because
    // the failure mode is silent and arrives with an OS update. It is here as
    // the DISCRIMINATING control: if the public knobs read opaque and this one
    // reads transparent, the instrument can tell the two apart and the public
    // answer is a real no. If this one also reads opaque, the instrument cannot
    // see transparency at all and nothing above it means anything.
    Case(id: "D1", what: "PRIVATE _setDrawsBackground:false — reference only, never ships",
         ground: .blue, page: PAGE_EMPTY,
         knobs: { w in
             if w.responds(to: NSSelectorFromString("_setDrawsBackground:")) {
                 w.setValue(false, forKey: "drawsBackground")
             } else {
                 say("       (selector absent on this WebKit — case is a no-op)")
             }
         }, control: false, check: nil),

    // THE OTHER PUBLIC drawsBackground, and it is not on WKWebView.
    // WebView.h:504 declares `@property (nonatomic) BOOL drawsBackground;` on
    // the legacy WebKit1 `WebView` -- public, documented, and deprecated since
    // 10.14. If it works, "no public route exists" would be false and the
    // sentence has to be "no public route exists ON WKWebView". Its cost is
    // large and stated in the report rather than here: WebKit1 is in-process,
    // frozen, and forecloses Tauri, whose macOS backend is a WKWebView.
    Case(id: "E1", what: "LEGACY WebView.drawsBackground = false — public, deprecated",
         ground: .blue, page: PAGE_EMPTY, knobs: noKnobs, control: false, check: nil,
         legacy: true),
]

// ---------------------------------------------------------------------------
// The driver
// ---------------------------------------------------------------------------

final class Nav: NSObject, WKNavigationDelegate {
    var done: (() -> Void)?
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        let d = done; done = nil; d?()
    }
}
let nav = Nav()

final class LegacyNav: NSObject, WebFrameLoadDelegate {
    var done: (() -> Void)?
    func webView(_ sender: WebView!, didFinishLoadFor frame: WebFrame!) {
        let d = done; done = nil; d?()
    }
}
let legacyNav = LegacyNav()

var web: WKWebView?
var legacyWeb: WebView?
var results: [(String, Px, Px, Px, Bool)] = []   // id, empty, lower, card, visible
var idx = 0

func teardownWeb() {
    web?.navigationDelegate = nil
    web?.removeFromSuperview()
    web = nil
    legacyWeb?.frameLoadDelegate = nil
    legacyWeb?.removeFromSuperview()
    legacyWeb = nil
}

func runCase(_ c: Case) {
    say("  \(pad(c.id, 4))\(c.what)")
    teardownWeb()
    setGround(c.ground)

    guard let page = c.page else {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { read(c) }
        return
    }

    if c.legacy {
        let lw = WebView(frame: CGRect(origin: .zero, size: VIEW))
        lw.drawsBackground = false
        lw.frameLoadDelegate = legacyNav
        ground.addSubview(lw)
        legacyWeb = lw
        var lfired = false
        legacyNav.done = {
            guard !lfired else { return }; lfired = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { read(c) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            guard !lfired else { return }; lfired = true
            say("       legacy load did not finish in 3 s — reading anyway, and saying so")
            read(c)
        }
        lw.mainFrame.loadHTMLString(page, baseURL: nil)
        return
    }

    let cfg = WKWebViewConfiguration()
    let w = WKWebView(frame: CGRect(origin: .zero, size: VIEW), configuration: cfg)
    w.navigationDelegate = nav
    c.knobs(w)
    // A knob that does not hold its value is a different finding from a knob
    // that holds it and does nothing. Read it back rather than assuming the set
    // took -- the property is null_resettable, so nil here means WebKit put its
    // own colour back.
    if let u = w.underPageBackgroundColor {
        let rgb = u.usingColorSpace(.sRGB)
        say("       underPageBackgroundColor reads back "
            + (rgb.map { String(format: "r%.2f g%.2f b%.2f α%.2f",
                                $0.redComponent, $0.greenComponent,
                                $0.blueComponent, $0.alphaComponent) } ?? "\(u)"))
    }
    ground.addSubview(w)
    web = w

    var fired = false
    nav.done = {
        guard !fired else { return }; fired = true
        // Loaded is not painted. Give the compositor two display intervals
        // before asking the window server what it has.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { read(c) }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
        guard !fired else { return }; fired = true
        say("       load did not finish in 3 s — reading anyway, and saying so")
        read(c)
    }
    w.loadHTMLString(page, baseURL: nil)
}

func read(_ c: Case) {
    let visible = win.occlusionState.contains(.visible)
    guard let img = capture() else {
        say("       CAPTURE RETURNED NIL — no window server image.")
        say("       Every reading in this run is void. Stopping.")
        exit(2)
    }
    let px = samples(img, [P_EMPTY, P_LOWER, P_CARD])
    guard px.count == 3 else {
        say("       could not sample the captured image — stopping"); exit(2)
    }
    results.append((c.id, px[0], px[1], px[2], visible))
    say("       empty \(pad(px[0].label, 20))lower \(pad(px[1].label, 20))"
        + "card \(pad(px[2].label, 20))"
        + "\(visible ? "visible" : "OCCLUDED") \(img.width)x\(img.height)")

    if let fail = c.check?(px[0], px[1], px[2]), c.control {
        say("")
        say("  *** CONTROL \(c.id) FAILED: \(fail) ***")
        switch c.id {
        case "A1":
            say("  The window server did not hand back our own window. On macOS 15+")
            say("  CGWindowListCreateImage is obsoleted, and CGWindow.h:264 says an")
            say("  unreadable window comes back as TRANSPARENT BLACK — indistinguishable")
            say("  from a perfectly transparent one. That is why this control runs first.")
            say("  This instrument is dead here. The remaining honest one is the owner's")
            say("  eyes: --look.")
        case "A2":
            say("  The capture flattened alpha. A transparent window came back opaque,")
            say("  so 'transparent' can never be read out of it — the same defect")
            say("  takeSnapshot has.")
        case "B1":
            say("  The capture cannot see WebKit content. An opaque magenta page read")
            say("  as something else, which means every C-case reading would be the")
            say("  GROUND showing through a webview the instrument simply cannot see —")
            say("  a false PASS, in the direction that flatters the design.")
            say("  This is exactly the failure cacheDisplay had, in the other direction.")
        default: break
        }
        say("  Aborting rather than printing a verdict off an invalid instrument.")
        exit(1)
    }
    next()
}

func next() {
    if idx < CASES.count {
        let c = CASES[idx]; idx += 1
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { runCase(c) }
    } else {
        verdict()
    }
}

func verdict() {
    func at(_ id: String) -> Px? { results.first { $0.0 == id }?.1 }
    say("")
    say(String(repeating: "─", count: 74))

    guard let refBlue = REF_BLUE else {
        say("  A1 recorded no reference colour — nothing below can be judged."); exit(2)
    }
    let publicIDs = ["C1", "C2", "C3", "C5", "C6"]
    let transparentPublic = publicIDs.filter { at($0)?.near(refBlue) == true }
    let c4 = at("C4")
    let priv = at("D1")

    say("  the ground READS as \(refBlue.label) through this capture path — measured")
    say("  in A1, not declared. That value at the empty point means the webview")
    say("  painted nothing there.")
    say("")
    for id in publicIDs + ["C4", "D1", "E1"] {
        guard let p = at(id) else { continue }
        let want = (id == "C4") ? PX_CLEAR : refBlue
        say("    \(pad(id, 5))\(pad(p.label, 22))"
            + (p.near(want) ? "ground shows through" : "webview painted over it"))
    }
    say("")

    let e1 = at("E1")
    let publicWorks = !transparentPublic.isEmpty || (c4?.near(PX_CLEAR) == true)
    let privateWorks = priv?.near(refBlue) == true

    if publicWorks {
        say("  ANSWER: YES. A WKWebView can be transparent over the face with public")
        say("  API only — \(transparentPublic.joined(separator: ", ")) read the ground through it.")
        say("  §1.1's two-layer home stands and the card work is not throwaway.")
    } else if privateWorks {
        say("  ANSWER: NO, not with public API. The private _setDrawsBackground: DID")
        say("  read transparent on the same instrument in the same run, so the")
        say("  instrument can tell the two apart and this is a real no, not a blind")
        say("  spot. §1.1's three named fallbacks are now the decision.")
        if e1?.near(refBlue) == true {
            say("")
            say("  AND E1 QUALIFIES THAT. The legacy WebKit1 WebView, whose")
            say("  drawsBackground IS public (WebView.h:504), read the ground through")
            say("  it on this same instrument. So the finding is not 'no public route")
            say("  exists' — it is 'no public route exists ON WKWebView', and the one")
            say("  that does costs a deprecated in-process engine and forecloses")
            say("  Tauri, whose macOS backend is a WKWebView.")
        }
    } else {
        say("  ANSWER: NOT ESTABLISHED. Neither the public knobs nor the private one")
        say("  read transparent. Every configuration reading the same way is what a")
        say("  blind instrument looks like, even with B1 passing. Do not record a NO")
        say("  off this run.")
    }
    say(String(repeating: "═", count: 74))
    say("  log: \(LOG)")

    if HOLD > 0 {
        say("")
        say("  holding the last configuration on screen for \(Int(HOLD)) s — look at it.")
        DispatchQueue.main.asyncAfter(deadline: .now() + HOLD) { exit(0) }
    } else {
        exit(0)
    }
}

say("""

  VESPER — SPIKE-013 precondition: can a WKWebView be transparent, publicly?
  ══════════════════════════════════════════════════════════════════════════
  macOS \(ProcessInfo.processInfo.operatingSystemVersionString)
  window level \(FLOAT_LEVEL ? "floating" : "normal-1 (the ground's own)"), \(Int(VIEW.width))x\(Int(VIEW.height)) at \(Int(origin.x)),\(Int(origin.y))
  reader: the window server's composite of OUR OWN window.
  three controls first — a capture that cannot see WebKit reads every
  transparent page and every opaque one exactly the same.

""")

DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { next() }
app.run()
