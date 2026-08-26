// Measure the chrome's LAID-OUT geometry in the engine that actually renders it.
//
// WHY THIS EXISTS RATHER THAN AN ASSERTION ABOUT THE CSS. `CI-065` checks that
// the template CONTAINS its rules and every token is substituted; it cannot
// tell you where anything ended up. The conversation cluster overlapped the
// face on the owner's display while that check was green, because "the rule is
// present" and "the card clears the face" are different claims and only the
// first had a gate.
//
// AND NOT A HEADLESS DOM EITHER. There is no JS runtime on this machine, and a
// stub would answer for a layout engine that is not the one shipping. WKWebView
// is what HomeChrome mounts, so it is what gets asked.
//
// Offscreen: no window, no Space, no Desktop. It runs while the owner is in
// another application.
import Cocoa
import WebKit

let args = CommandLine.arguments
guard let pathIdx = args.firstIndex(of: "--file"), pathIdx + 1 < args.count else {
    FileHandle.standardError.write("usage: layout_probe --file <html> [--width N --height N]\n".data(using: .utf8)!)
    exit(2)
}
let file = args[pathIdx + 1]
func intArg(_ name: String, _ dflt: Int) -> Int {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return dflt }
    return Int(args[i + 1]) ?? dflt
}
let w = intArg("--width", 2000), h = intArg("--height", 1300)

let JS = """
(function(){
  function r(sel){ var e=document.querySelector(sel); if(!e) return null;
    var b=e.getBoundingClientRect();
    return {l:Math.round(b.left),r:Math.round(b.right),t:Math.round(b.top),
            b:Math.round(b.bottom),w:Math.round(b.width),h:Math.round(b.height)}; }
  var out={viewport:[window.innerWidth,window.innerHeight],
           face:r('#facering'), convo:r('.convo'), stage:r('.stage'),
           history:r('.history'), dock:r('.dockrow'), field:r('.field'),
           card:r('.card')};
  var say=document.querySelector('.say')||document.body;
  out.font=getComputedStyle(say).fontFamily;
  return JSON.stringify(out);
})()
"""

final class Probe: NSObject, WKNavigationDelegate {
    let web: WKWebView
    init(size: NSSize) {
        let cfg = WKWebViewConfiguration()
        web = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: cfg)
        super.init()
        web.navigationDelegate = self
    }
    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        // ONE RUNLOOP TURN AFTER didFinish. `didFinish` fires when the document
        // has loaded, not when layout has settled -- reading immediately
        // returned zero-width boxes for the flex children, which would have
        // read as "the card is not there" rather than "the question was asked
        // too early".
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            v.evaluateJavaScript(JS) { res, err in
                if let s = res as? String { print(s) } else {
                    FileHandle.standardError.write("eval failed: \(String(describing: err))\n".data(using: .utf8)!)
                    exit(1)
                }
                exit(0)
            }
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let probe = Probe(size: NSSize(width: w, height: h))
let url = URL(fileURLWithPath: file)
probe.web.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
// A hard ceiling so a page that never finishes cannot hang a gate.
DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
    FileHandle.standardError.write("timed out waiting for layout\n".data(using: .utf8)!)
    exit(1)
}
app.run()
