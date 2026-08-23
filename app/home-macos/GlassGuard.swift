// VESPER — the glass hatch, and the alarm that makes it acceptable.
//
// glass-hatch-ok
//
// THIS IS THE ONLY FILE IN VESPER THAT MAY TOUCH `_setDrawsBackground:`.
// `CI-051` refuses that selector anywhere else, and refuses it here too unless
// this file also contains the reader below. The hatch may not ship without its
// alarm; that pairing is the whole decision.
//
// WHY THE HATCH EXISTS AT ALL.
//
// `SPIKE-013` §0, measured 2026-08-23 on macOS 26.5: a `WKWebView` cannot be
// made transparent with public API. Every public configuration paints #FFFFFF
// over the ground, including `underPageBackgroundColor = .clear`, which is set,
// held, reads back at alpha 0.00 and changes nothing -- it is the scroll-bounce
// colour its own SDK header says it is, and it is the entire public surface.
// Two routes do work: this private selector, and the legacy WebKit1 `WebView`,
// whose `drawsBackground` is public and deprecated since 10.14 and forecloses
// Tauri. §0.5 then measured that once transparency exists BY EITHER ROUTE, the
// glass really does blur the ground behind it -- 41-42 pt of smeared edge
// inside a card against 0 pt outside, over a real CAMetalLayer. So the look is
// achievable and only the transparency was missing.
//
// WHY THE HATCH IS ACCEPTABLE, WHICH IS A DIFFERENT QUESTION.
//
// `ISLAND-ARCHITECTURE.md` §2 forbids private API, and it gives its reason:
//
//   "the failure mode is SILENT: a private call keeps working for three OS
//    releases and then removes the island the morning after an update, with no
//    compile error and no test failure."
//
// The reason is silence, not the selector. Owner decision, 2026-08-23: take the
// hatch and remove the silence. `SPIKE-013` produced a reader that sees the
// REAL composite -- the window server's own image of our window, which is the
// only reader that sees layers WebKit draws out of process -- so the morning
// after that OS update, VESPER knows, says so, and refuses to mount a chrome
// it cannot see through. That is what turns a silent failure into a loud one.
//
// WHAT WOULD MAKE THIS FILE A LIE.
//
// A reader that cannot see WebKit content reports a transparent page and an
// opaque one identically, and would green-light a white screen over the face.
// Two earlier instruments did exactly that: `takeSnapshot` composites onto an
// opaque bitmap, and `cacheDisplay` draws only the view tree THIS process owns.
// So `verify` carries its own controls and runs them every time, in an order
// where each one can only fail for its own reason:
//
//   1  ground alone            must read OPAQUE      -- the reader reaches our window
//   2  ground + magenta page   must read DIFFERENT   -- the reader SEES WebKit
//   3  ground + clear page     must read like 1      -- the hatch still works
//
// Step 2 is the one that matters. Without it, a blind reader passes step 3 for
// free, because a window it cannot read looks exactly like a window it can read
// through.
//
// Nothing here declares a colour. Step 1 MEASURES what the ground reads as and
// steps 2 and 3 are compared against that measurement -- the same correction
// `SPIKE-013` §0.1 had to make when a declared #1030C0 came back #1249CC,
// because the window server composites in the display's space.

import AppKit
import WebKit

enum GlassGuard {

    // MARK: - The hatch

    /// Makes `web` transparent, and says whether the route still exists.
    ///
    /// Returns `false` when the selector is gone -- which is the OS update this
    /// whole file is built around. A `false` here is not an error to log and
    /// carry on from: the caller must refuse to mount the chrome, because the
    /// alternative is a white rectangle over the face.
    @discardableResult
    static func makeTransparent(_ web: WKWebView) -> Bool {
        // Set first and kept, even though SPIKE-013 measured it doing nothing.
        // It is the supported knob; if WebKit ever wires it up, this file stops
        // needing the line below and the check that guards it.
        web.underPageBackgroundColor = .clear

        let sel = NSSelectorFromString("_setDrawsBackground:")
        guard web.responds(to: sel) else { return false }
        web.setValue(false, forKey: "drawsBackground")
        return true
    }

    // MARK: - The alarm

    enum Verdict: Equatable {
        /// The ground read through the webview. The chrome may mount.
        case transparent
        /// The webview painted over the ground. What it painted is carried.
        case opaque(String)
        /// The reader could not answer, and an unanswered question is not a
        /// pass. `INV-HW-2`'s rule, applied to a colour: UNKNOWN is UNAVAILABLE.
        case unreadable(String)

        var mayMountChrome: Bool { self == .transparent }

        var line: String {
            switch self {
            case .transparent:      return "glass: TRANSPARENT — the ground reads through the chrome"
            case .opaque(let what): return "glass: OPAQUE — the chrome painted \(what) over the face"
            case .unreadable(let w): return "glass: UNREADABLE — \(w)"
            }
        }
    }

    private struct Px: Equatable {
        var r = 0.0, g = 0.0, b = 0.0, a = 0.0
        var label: String {
            a < 0.004 ? "nothing"
                      : String(format: "#%02X%02X%02X", Int(r * 255 + 0.5),
                               Int(g * 255 + 0.5), Int(b * 255 + 0.5))
        }
        func near(_ o: Px, _ tol: Double = 0.05) -> Bool {
            guard abs(a - o.a) <= tol else { return false }
            if a < 0.004 && o.a < 0.004 { return true }
            return abs(r - o.r) <= tol && abs(g - o.g) <= tol && abs(b - o.b) <= tol
        }
    }

    /// A page that paints nothing, transparently.
    private static let CLEAR_PAGE = """
    <!doctype html><meta charset="utf-8">
    <style>html,body{margin:0;height:100%;background:transparent}</style>
    """

    /// A page that paints, unmistakably. The control's whole job is to be
    /// impossible to confuse with a ground, a desktop or a system panel.
    private static let PAINTED_PAGE = """
    <!doctype html><meta charset="utf-8">
    <style>html,body{margin:0;height:100%;background:#ff00ff}</style>
    """

    private final class Nav: NSObject, WKNavigationDelegate {
        var done: (() -> Void)?
        func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
            let d = done; done = nil; d?()
        }
    }

    /// Runs the three steps on a throwaway 64×64 window and answers.
    ///
    /// `applyHatch: false` is THE NEGATIVE CONTROL, and it is a permanent
    /// capability rather than something a session does once in a scratch build.
    /// An alarm that has only ever gone green has not been shown to key on the
    /// thing it claims to key on -- so with the hatch withheld, step 3 must
    /// report OPAQUE. If it still reports TRANSPARENT, the alarm is not reading
    /// the hatch at all and every green it has ever given was free.
    ///
    /// The window is small, at the ground's own level so anything else on
    /// screen covers it, and torn down immediately. It is on screen rather than
    /// off it because an off-screen window is not composited, and a reader
    /// pointed at an uncomposited window returns transparent black -- which is
    /// indistinguishable from the pass this is looking for.
    static func verify(applyHatch: Bool = true, _ done: @escaping (Verdict) -> Void) {
        guard let screen = NSScreen.main else {
            done(.unreadable("no screen")); return
        }
        let side: CGFloat = 64
        let frame = CGRect(x: screen.frame.minX + 8, y: screen.frame.minY + 8,
                           width: side, height: side)
        let win = NSWindow(contentRect: frame, styleMask: [.borderless],
                           backing: .buffered, defer: false)
        win.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
        win.collectionBehavior = [.managed]
        win.animationBehavior = .none
        win.isOpaque = false
        win.backgroundColor = .clear
        win.hasShadow = false
        win.ignoresMouseEvents = true

        let ground = NSView(frame: CGRect(origin: .zero, size: CGSize(width: side, height: side)))
        ground.wantsLayer = true
        // Never compared against a declared value -- only against itself, read
        // back through the same path. See the header.
        ground.layer?.backgroundColor = CGColor(red: 0.063, green: 0.188, blue: 0.753, alpha: 1)
        win.contentView = ground
        win.orderFrontRegardless()

        let nav = Nav()
        var web: WKWebView?
        func finish(_ v: Verdict) {
            // `WKWebView.navigationDelegate` is WEAK, and this delegate is a
            // local. Between step 2 and step 3 the only strong reference to it
            // was the closure stored in `nav.done` -- which `Nav` clears BEFORE
            // invoking, precisely so a handler cannot fire twice. So the
            // delegate died mid-run, `didFinish` never arrived for the clear
            // page, and the first run of this file reported
            // "the clear page did not load in 3 s".
            //
            // It reported UNREADABLE rather than passing, which is the whole
            // point of the three steps -- but the fault was the alarm's, not
            // the world's. `finish` is captured by every closure that can reach
            // it, so naming `nav` here is what keeps the delegate alive for the
            // whole run.
            withExtendedLifetime(nav) {}
            web?.navigationDelegate = nil
            web?.removeFromSuperview()
            win.orderOut(nil)
            done(v)
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            // ---- 1. the ground alone
            guard let ref = sample(win, side) else {
                finish(.unreadable("the window server returned no image of our own window"))
                return
            }
            guard ref.a > 0.9 else {
                finish(.unreadable("a solid ground read back as \(ref.label) α\(String(format: "%.2f", ref.a)) — "
                                   + "the reader is not reaching our window, and a window it cannot read "
                                   + "looks exactly like one it can read through"))
                return
            }

            // ---- 2. can the reader see WebKit at all
            let w = WKWebView(frame: ground.bounds)
            w.navigationDelegate = nav
            if applyHatch {
                makeTransparent(w)
            } else {
                // The public knob alone, which SPIKE-013 measured doing nothing.
                // This is what the chrome would look like if the hatch vanished.
                w.underPageBackgroundColor = .clear
            }
            ground.addSubview(w)
            web = w

            var fired = false
            let timeout = DispatchWorkItem {
                guard !fired else { return }; fired = true
                finish(.unreadable("the control page did not load in 3 s"))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.0, execute: timeout)

            nav.done = {
                guard !fired else { return }; fired = true
                timeout.cancel()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                    guard let painted = sample(win, side) else {
                        finish(.unreadable("no image during the control")); return
                    }
                    guard !painted.near(ref) else {
                        finish(.unreadable("a page painted edge to edge read the same as the bare "
                                           + "ground — the reader cannot see WebKit content, so it "
                                           + "would pass an opaque chrome as readily as a clear one"))
                        return
                    }

                    // ---- 3. the question itself
                    var fired3 = false
                    let t3 = DispatchWorkItem {
                        guard !fired3 else { return }; fired3 = true
                        finish(.unreadable("the clear page did not load in 3 s"))
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3.0, execute: t3)
                    nav.done = {
                        guard !fired3 else { return }; fired3 = true
                        t3.cancel()
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                            guard let clear = sample(win, side) else {
                                finish(.unreadable("no image during the reading")); return
                            }
                            finish(clear.near(ref) ? .transparent : .opaque(clear.label))
                        }
                    }
                    w.loadHTMLString(CLEAR_PAGE, baseURL: nil)
                }
            }
            w.loadHTMLString(PAINTED_PAGE, baseURL: nil)
        }
    }

    // MARK: - The reader
    //
    // The window server's composite of OUR OWN window. In-process readers
    // cannot answer this: WebKit renders in com.apple.WebKit.WebContent, so
    // `cacheDisplay` sees a placeholder and `takeSnapshot` flattens onto an
    // opaque bitmap. Both were tried, and both reported confidently.

    private static func sample(_ win: NSWindow, _ side: CGFloat) -> Px? {
        guard let img = CGWindowListCreateImage(
                .null, [.optionIncludingWindow], CGWindowID(win.windowNumber),
                [.boundsIgnoreFraming, .bestResolution]) else { return nil }
        let w = img.width, h = img.height
        guard w > 0, h > 0 else { return nil }
        let n = w * h * 4
        let data = UnsafeMutablePointer<UInt8>.allocate(capacity: n)
        defer { data.deallocate() }
        data.initialize(repeating: 0, count: n)
        guard let ctx = CGContext(data: data, width: w, height: h, bitsPerComponent: 8,
                                  bytesPerRow: w * 4,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                                            | CGBitmapInfo.byteOrder32Big.rawValue)
        else { return nil }
        ctx.clear(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        let x = w / 2, y = h / 2
        let o = (y * w + x) * 4
        let a = Double(data[o + 3]) / 255
        guard a > 0 else { return Px() }
        return Px(r: Double(data[o]) / 255 / a,
                  g: Double(data[o + 1]) / 255 / a,
                  b: Double(data[o + 2]) / 255 / a, a: a)
    }
}
