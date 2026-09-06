import AppKit
import WebKit

/// Ask the page what it PAINTED, offscreen, without taking a Desktop.
///
/// WHY THIS EXISTS. This tree's rule is that an instrument's self-report is not
/// evidence: `spd-say` exiting 0 is not a sound in the room, and a renderer that
/// was handed data is not a row on screen. Every surface built before this one
/// was verified by a person looking at it, which does not scale to a stack of
/// panes and does not run in a gate at all.
///
/// AND THE OBVIOUS ALTERNATIVES DO NOT WORK. A headless HTML file in a browser
/// preview is served with `script-src 'none'`, so the renderer never runs and
/// the page reports an empty card that is empty for the wrong reason. A DOM
/// stub under Node exercises the JavaScript and knows nothing about CSS, which
/// is where the layout defects are -- a pane that fits is a claim about a real
/// engine, real fonts and a real backdrop filter.
///
/// So this loads the SAME `HomeChrome.page(...)` into a real WKWebView with no
/// window attached, pushes the SAME `home.json` the live surface reads, and
/// reads the DOM back out. It never mounts over anything and never touches the
/// owner's Desktop.
///
/// A MODE OF THE APP BINARY, NOT A SCRIPT BESIDE IT -- everything here runs as
/// VESPER, from the bundle, with VESPER's identity.
enum ChromeProbe {

    /// Geometry solved the way `mount` solves it, from a real screen, so the
    /// probe reports on the layout the owner would actually get rather than on
    /// a set of numbers invented for the test.
    struct Geometry {
        let cw = 300, ch = 236
        let left: Int, top: Int, convoLeft: Int
        let stackTop: Int, stackHeight: Int
        let height: Int

        init(screen: NSScreen) {
            let h = Int(screen.frame.height)
            // The face's square, centred, at the size the home uses.
            let faceSide = Int(Double(h) * 0.46)
            let faceMinX = Int(screen.frame.width) / 2 - faceSide / 2
            left = max(48, faceMinX - cw - 72)
            convoLeft = faceMinX + faceSide + 40
            var t = max(48, h / 2 - ch / 2)
            let stackGap = 12, stackBarH = 40, stackPanes = 4
            let floor = h - 96
            let needs = stackPanes * stackBarH + (stackPanes - 1) * stackGap
            let deficit = (t + ch + stackGap + needs) - floor
            if deficit > 0 { t = max(158, t - deficit) }
            top = t
            stackTop = t + ch + stackGap
            stackHeight = max(0, floor - stackTop)
            height = h
        }
    }

    /// What the probe asks the page, once it has been pushed a state.
    ///
    /// EVERY ANSWER IS MEASURED OFF THE RENDERED BOX, not read back out of the
    /// data that was pushed in. `rows` counts elements that exist; `fits` is a
    /// comparison of two `getBoundingClientRect()`s. A report keyed on what was
    /// SENT would be green for a page that dropped all of it.
    static let readback = """
    (function () {
      function box(el) {
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return {top: Math.round(r.top), bottom: Math.round(r.bottom),
                left: Math.round(r.left), width: Math.round(r.width),
                height: Math.round(r.height)};
      }
      var stack = document.getElementById('stack');
      var panes = [].slice.call(document.querySelectorAll('.pane'));
      var out = {
        stack: box(stack),
        viewport: {w: window.innerWidth, h: window.innerHeight},
        panes: panes.map(function (p) {
          return {id: p.id,
                  idle: p.classList.contains('idle'),
                  open: p.classList.contains('open'),
                  box: box(p)};
        }),
        commands: [].slice.call(document.querySelectorAll('.cmd')).map(function (c) {
          return {id: c.getAttribute('data-cmd'),
                  state: c.className.replace('cmd', '').trim(),
                  open: c.classList.contains('open'),
                  display: (c.querySelector('.cdisp') || {}).textContent || '',
                  why: (c.querySelector('.cwhy') || {}).textContent || '',
                  stdout: (c.querySelector('.cout') || {}).textContent || '',
                  stderr: (c.querySelector('.cerr') || {}).textContent || ''};
        }),
        explanations: [].slice.call(document.querySelectorAll('.exp')).map(function (e) {
          return {turn: e.getAttribute('data-turn'),
                  lit: e.classList.contains('lit'),
                  title: (e.querySelector('.etitle') || {}).textContent || '',
                  text: [].slice.call(e.querySelectorAll('.btext'))
                          .map(function (n) { return n.textContent; }),
                  code: [].slice.call(e.querySelectorAll('.bcode'))
                          .map(function (n) { return n.textContent; }),
                  list: [].slice.call(e.querySelectorAll('.blist li'))
                          .map(function (n) { return n.textContent; }),
                  skipped: [].slice.call(e.querySelectorAll('.bskip')).length};
        }),
        changes: [].slice.call(document.querySelectorAll('.chg')).map(function (c) {
          return {path: c.getAttribute('data-path'),
                  src: c.getAttribute('data-src'),
                  status: c.getAttribute('data-status'),
                  open: c.classList.contains('open'),
                  added: (c.querySelector('.dadd') || {}).textContent || '',
                  removed: (c.querySelector('.drem') || {}).textContent || '',
                  plus: c.querySelectorAll('.dhunks .a').length,
                  minus: c.querySelectorAll('.dhunks .r').length,
                  diff: (c.querySelector('.dhunks') || {}).textContent || ''};
        }),
        gitDisabled: [].slice.call(document.querySelectorAll('.gbtn[data-git]'))
                       .map(function (b) { return b.disabled; }),
        historyTurns: [].slice.call(document.querySelectorAll('.hrow'))
                        .map(function (h) { return h.getAttribute('data-turn') || ''; }),
        litHistory: [].slice.call(document.querySelectorAll('.hrow.lit'))
                      .map(function (h) { return h.getAttribute('data-turn') || ''; }),
        metricRows: [].slice.call(document.querySelectorAll('#metrics .row'))
                      .map(function (r) {
                        return ((r.querySelector('.k')||{}).textContent || '') + '='
                             + ((r.querySelector('.v')||{}).textContent || '');
                      }),
        terminal: (document.getElementById('tout') || {}).textContent || '',
        cmdButtons: [].slice.call(document.querySelectorAll('.cmdbar button'))
                      .map(function (b) { return b.textContent; }),
        summary: (document.getElementById('cmdsum') || {}).textContent || '',
        count: (document.getElementById('cmdcount') || {}).textContent || ''
      };
      // THE ONE QUESTION A SCREENSHOT ANSWERS AND A UNIT TEST CANNOT: does the
      // stack, as laid out by a real engine with real fonts, stay inside the
      // box Swift gave it? Every pane's lower edge against the container's.
      var lastBottom = 0;
      out.panes.forEach(function (p) {
        if (p.box && p.box.bottom > lastBottom) lastBottom = p.box.bottom;
      });
      out.fits = !out.stack || lastBottom <= out.stack.bottom + 1;
      out.overflowBy = out.stack ? (lastBottom - out.stack.bottom) : 0;
      return JSON.stringify(out);
    })();
    """

    static func run(expand: String?, click: String?,
                    clickTurn: String? = nil,
                    runLine: String? = nil) -> Never {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let g = Geometry(screen: screen)
        let page = HomeChrome.page(cardWidth: g.cw, cardHeight: g.ch,
                                   left: g.left, top: g.top,
                                   convoLeft: g.convoLeft,
                                   stackTop: g.stackTop,
                                   stackHeight: g.stackHeight,
                                   fill: 0.34)

        // NO WINDOW. The view is sized to the screen and never added to one, so
        // WebKit lays out at the real dimensions and nothing appears anywhere.
        // THE REAL BRIDGES, so the probe exercises the thing that ships. A
        // probe whose page has no message handlers verifies a renderer and
        // reports nothing about whether a button does anything -- which is the
        // half that matters for the terminal.
        let cfg = WKWebViewConfiguration()
        let term = TerminalBridge()
        let acts = ActBridge()
        cfg.userContentController.add(term, name: TerminalBridge.name)
        cfg.userContentController.add(acts, name: ActBridge.name)
        let web = WKWebView(frame: NSRect(x: 0, y: 0,
                                          width: screen.frame.width,
                                          height: screen.frame.height),
                            configuration: cfg)
        term.web = web
        acts.web = web
        web.loadHTMLString(page, baseURL: nil)

        let work = HomeChrome.workbenchJSON()
        var finished = false

        func report() {
            // Pushed through the SAME entry point the live surface uses. A
            // probe that called `renderCommands` directly would verify a
            // function the running chrome never reaches.
            let safe = work
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            // THE HISTORY IS PUSHED TOO. The link between a reply and its
            // explanation lives across the two renderers, so a probe that
            // pushed only the workbench could never see it.
            let histSafe = HomeChrome.historyJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let chgSafe = HomeChrome.changesJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let metSafe = HomeChrome.metricsJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            var js = "if (window.__vesperWork) window.__vesperWork(`\(safe)`);"
                   + "if (window.__vesperMetrics) window.__vesperMetrics(`\(metSafe)`);"
                   + "if (window.__vesperChanges) window.__vesperChanges(`\(chgSafe)`);"
                   + "if (window.__vesperHistory) window.__vesperHistory(`\(histSafe)`);"
            if let pane = expand {
                js += "var _h=document.querySelector('[data-pane=\"\(pane)\"]');"
                    + "if(_h)_h.click();"
            }
            if let turn = clickTurn {
                js += "var _t=document.querySelector('.hrow[data-turn=\"\(turn)\"]');"
                    + "if(_t)_t.click();"
            }
            if let line = runLine {
                // Straight through the terminal's own input path -- the same
                // one a keypress uses, so this measures the shell and not a
                // shortcut around it.
                js += "if (window.termOpenForProbe) window.termOpenForProbe();"
                    + "if (window.termInputForProbe) window.termInputForProbe(`\(line)\n`);"
            }
            if let cmd = click {
                js += "var _c=document.querySelector('[data-cmd=\"\(cmd)\"] .chead');"
                    + "if(_c)_c.click();"
            }
            web.evaluateJavaScript(js) { _, _ in
                // A FRAME LATER. Opening a pane changes a flex basis, and the
                // boxes it moves are not final until the engine has laid out
                // again -- reading in the same turn reports the geometry from
                // before the click and calls it the result of the click.
                DispatchQueue.main.asyncAfter(deadline: .now() + (runLine == nil ? 0.35 : 3.0)) {
                    web.evaluateJavaScript(readback) { val, err in
                        if let s = val as? String {
                            print(s)
                        } else {
                            FileHandle.standardError.write(
                                "chrome-probe: no readback (\(String(describing: err)))\n"
                                    .data(using: .utf8)!)
                        }
                        finished = true
                        exit(val is String ? 0 : 70)
                    }
                }
            }
        }

        // Give the page time to load, then report. Polled rather than driven by
        // a navigation delegate because the page is loaded from a STRING and
        // there is no navigation to observe -- `isLoading` is the fact.
        var waited = 0.0
        func settle() {
            if !web.isLoading || waited > 8.0 { report(); return }
            waited += 0.1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { settle() }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { settle() }

        // A CEILING, SO A PROBE THAT NEVER ANSWERS FAILS RATHER THAN HANGS. A
        // gate that waits forever is a gate nobody runs.
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
            if !finished {
                FileHandle.standardError.write(
                    "chrome-probe: timed out with no readback\n".data(using: .utf8)!)
                exit(75)
            }
        }
        NSApplication.shared.setActivationPolicy(.prohibited)
        NSApplication.shared.run()
        exit(0)
    }
}
