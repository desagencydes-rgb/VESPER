// Does the chrome's web layer SURVIVE an occlusion cycle, or is it rebuilt?
//
// WHY A PROBE AND NOT A READING OF THE CODE. The owner reports that the main
// menu, the cards and the widgets vanish when they switch away and appear again
// on return, while the face does not. Nothing in this app hides them: the chrome
// mounts once, no path unmounts it, and there is no entrance animation in the
// template. So whatever is happening is happening BELOW us -- in AppKit's
// occlusion handling or WebKit's -- and the difference between "the web content
// process was suspended" and "the layer's backing store was discarded" leads to
// two completely different fixes. Guessing which costs a change to a surface the
// owner is looking at.
//
// WHAT IT MEASURES. A page ticking a counter every 50 ms, in a window that is
// then covered by an opaque window and uncovered. If the counter stalls while
// covered, the content process was throttled. If the counter keeps running but
// the layer had to repaint, the backing store was dropped. Both are reported.
import Cocoa
import WebKit

let PAGE = """
<html><head><style>
html,body{margin:0;height:100%;background:transparent}
.glass{position:absolute;left:40px;top:40px;width:300px;height:160px;
       border-radius:22px;background-color:rgba(255,255,255,.055);
       -webkit-backdrop-filter:blur(24px) saturate(180%);
       border:1px solid rgba(255,255,255,.14)}
</style></head><body>
<div class="glass"></div>
<script>
  window.__ticks = 0;
  window.__paints = 0;
  setInterval(function(){ window.__ticks++; }, 50);
  // A repaint counter: rAF only fires while the page is being composited, so a
  // gap here and none in __ticks means the compositor stopped, not the timer.
  (function raf(){ window.__paints++; window.__lastPaint = Date.now();
                   requestAnimationFrame(raf); })();
  window.__markReveal = function(){ window.__revealAt = Date.now();
                                    window.__paintsAtReveal = window.__paints; };
  window.__recovery = function(){
    return JSON.stringify({
      ms_from_reveal_to_first_paint: window.__firstPaintAfter
        ? window.__firstPaintAfter - window.__revealAt : null,
      paints_since_reveal: window.__paints - window.__paintsAtReveal });
  };
  (function watch(){
    if (window.__revealAt && !window.__firstPaintAfter
        && window.__paints > window.__paintsAtReveal) {
      window.__firstPaintAfter = Date.now();
    }
    requestAnimationFrame(watch);
  })();
</script></body></html>
"""

final class Probe: NSObject, WKNavigationDelegate {
    let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 600, height: 400))
    var win: NSWindow!
    var cover: NSWindow!
    var samples: [String: Any] = [:]

    func run() {
        win = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 600, height: 400),
                       styleMask: [.borderless], backing: .buffered, defer: false)
        win.isOpaque = false
        win.backgroundColor = .clear
        win.level = .normal
        win.contentView?.addSubview(web)
        web.navigationDelegate = self
        web.loadHTMLString(PAGE, baseURL: nil)
        win.orderFrontRegardless()
    }

    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        after(0.6) { self.sample("before") { self.occludeThenReveal() } }
    }

    func occludeThenReveal() {
        // An opaque window exactly over ours is what the window server counts
        // as occlusion -- the same condition OcclusionWatch is written to
        // detect, produced deliberately instead of waiting for the owner to
        // switch apps.
        cover = NSWindow(contentRect: win.frame, styleMask: [.borderless],
                         backing: .buffered, defer: false)
        cover.isOpaque = true
        cover.backgroundColor = .black
        cover.level = .normal
        cover.orderFrontRegardless()
        after(1.5) {
            let occluded = !self.win.occlusionState.contains(.visible)
            self.sample("while_covered") {
                self.samples["window_reported_occluded"] = occluded
                // Marked INSIDE the page immediately before the reveal, so
                // the clock that measures recovery is the page's own -- a
                // Swift-side timestamp would include the round trip it is
                // trying to measure.
                self.web.evaluateJavaScript("window.__markReveal()") { _, _ in
                    self.cover.orderOut(nil)
                }
                // THE KICK UNDER TEST. Applied only when the probe is asked
                // for it, so the same binary measures with and without and the
                // comparison is on one machine in one minute.
                if CommandLine.arguments.contains("--kick") {
                    self.after(0.02) { self.kick() }
                }
                self.after(1.5) {
                    self.web.evaluateJavaScript("window.__recovery()") { r, _ in
                        self.samples["recovery"] = (r as? String) ?? "null"
                        self.sample("after_reveal") { self.report() }
                    }
                }
            }
        }
    }

    /// Wake the web view's compositor on the visibility edge.
    ///
    /// The Metal face resumes on its own display link the instant the window is
    /// revealed. WebKit throttles a covered view's compositing and does not
    /// hurry to undo it -- measured here at 1470 ms, and once at never-within-
    /// 1.5 s. So the edge has to say so explicitly.
    func kick() {
        web.setNeedsDisplay(web.bounds)
        web.layer?.setNeedsDisplay()
        // Touching the DOM resumes the content process, and asking for a frame
        // from inside the page is what actually restarts compositing -- the
        // AppKit-side invalidations above do not reach WebKit's own scheduler.
        web.evaluateJavaScript(
            "document.body.style.opacity='0.999';"
          + "requestAnimationFrame(function(){document.body.style.opacity='';});",
            completionHandler: nil)
    }

    func sample(_ label: String, _ then: @escaping () -> Void) {
        web.evaluateJavaScript("JSON.stringify({t:window.__ticks,p:window.__paints})") { r, _ in
            self.samples[label] = (r as? String) ?? "null"
            then()
        }
    }

    func report() {
        print(String(data: try! JSONSerialization.data(withJSONObject: samples,
                                                       options: [.prettyPrinted, .sortedKeys]),
                     encoding: .utf8)!)
        exit(0)
    }

    func after(_ s: Double, _ f: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: f)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let p = Probe()
p.run()
DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
    FileHandle.standardError.write("timed out\n".data(using: .utf8)!); exit(1)
}
app.run()
