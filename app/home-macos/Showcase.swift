// VESPER's showcase — the window it shows things ON.
//
// THE OWNER'S ASK, 2026-09-15: show files at a line, images, video, a website it
// drives itself, a whiteboard, arrows, its own cursor — and put all of it on
// VESPER'S Desktop while he keeps working on his.
//
// WHY THIS IS ONE WINDOW AND NOT FIVE APPLICATIONS. `window_relocate`, in
// `core/capabilities.py`, carries the measurement: on this macOS a
// FOREIGN application's window does not move between Spaces for either private
// mechanism `SpacesHatch` tries. VESPER's own windows do. (The symbols are spelled
// in `SpacesHatch.swift` alone: `spaces-hatch-contained` counts any file that names
// one as a second carrier, and this file reaches the hatch only through that
// file's door -- the first draft named one in this comment and the gate caught it.) So "open a picture, a video, a page and a file on MY desktop" is
// reachable exactly one way: a surface VESPER owns. Opening Preview and QuickTime
// and dragging them would fail at the last step, silently, which is the worst
// place for it to fail.
//
// THREE LAYERS, AND THE MIDDLE ONE IS WHY.
//
//   base   a WKWebView drawing code, images, video, the whiteboard, text and run
//          output, and reporting back the RECT of every pane it drew
//   sites  one real WKWebView per `web` pane, positioned over the base's reported
//          rect — a real browser, because an iframe cannot be driven and read
//          back the way "drive a website end to end" needs
//   marks  a transparent WKWebView above both, drawing arrows, rings, ink, labels
//          and VESPER's cursor in absolute coordinates
//
// The marks layer exists BECAUSE of the sites layer. Draw the arrows in the base
// and every one that points at a website is underneath it. The layer refuses
// mouse events (`hitTest` returns nil), so it annotates without ever swallowing a
// click meant for the page below.
//
// NOTHING HERE IS BELIEVED WITHOUT A READBACK. §9r, verbatim: "every instrument
// used mounted its OWN webview and fired ONE push, which is a different question
// from 'is the surface the owner is looking at rendering'". Every push returns the
// pane ids that actually drew, every Space move is re-read, and both go into
// `showcase-said.json` where Python compares them against what it asked for. A
// pane that did not draw is NAMED, because the failure worth preventing is VESPER
// telling the owner to look at something that is not on the screen.

import AppKit
import ScreenCaptureKit
import WebKit

// MARK: - The marks layer

/// A web view that draws and never intercepts.
///
/// WITHOUT THIS, ANNOTATION BREAKS THE THING IT ANNOTATES. A transparent view
/// over the whole window is still a view: it takes the click, the website
/// underneath never sees it, and the symptom is "VESPER's browser stopped
/// responding" rather than "there is a pane in front of it".
final class PassThroughWeb: WKWebView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

// MARK: - Serving local files to the page

/// `vesper-file://` — the only way a picture or a video reaches the page.
///
/// A CUSTOM SCHEME RATHER THAN `allowingReadAccessTo:`. Granting the page read
/// access to a directory grants it the whole subtree for the window's lifetime,
/// and the page then decides what to fetch. Here Swift decides: one request, one
/// path, checked against the same refusal list `core/showcase.py` enforces, and a
/// refusal is an error the page renders as a broken pane rather than a silent
/// blank one.
final class ShowcaseFiles: NSObject, WKURLSchemeHandler {
    static let scheme = "vesper-file"

    /// Never served, whatever the scene says. The second lock, deliberately
    /// duplicating `core/showcase.py:NEVER_SHOWN` — the first one has been routed
    /// around in this corpus before, and a secret rendered onto a screen has been
    /// disclosed in a way no later edit takes back.
    static let refused = ["/.config/vesper/", "/.ssh/", "/.aws/", "/.gnupg/",
                          "/Library/Keychains/", "/.netrc"]

    static func mayServe(_ path: String) -> Bool {
        let resolved = URL(fileURLWithPath: path).resolvingSymlinksInPath().path + "/"
        return !refused.contains { resolved.contains($0) }
    }

    private static let types: [String: String] = [
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp", "heic": "image/heic",
        "svg": "image/svg+xml", "bmp": "image/bmp", "tiff": "image/tiff",
        "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime",
        "webm": "video/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg",
        "wav": "audio/wav", "pdf": "application/pdf",
    ]

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else {
            task.didFailWithError(NSError(domain: "showcase", code: 1)); return
        }
        // The path is the URL's path, percent-decoded. `url.path` already is.
        let path = url.path
        guard Self.mayServe(path) else {
            task.didFailWithError(NSError(
                domain: "showcase", code: 403,
                userInfo: [NSLocalizedDescriptionKey:
                            "vesper does not put that file on a screen"]))
            return
        }
        guard let data = FileManager.default.contents(atPath: path) else {
            task.didFailWithError(NSError(
                domain: "showcase", code: 404,
                userInfo: [NSLocalizedDescriptionKey: "no file at \(path)"]))
            return
        }
        let ext = (path as NSString).pathExtension.lowercased()
        let mime = Self.types[ext] ?? "application/octet-stream"
        let resp = URLResponse(url: url, mimeType: mime,
                               expectedContentLength: data.count,
                               textEncodingName: nil)
        task.didReceive(resp)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

// MARK: - The showcase

final class Showcase: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let shared = Showcase()

    /// Where the scene, the asks and the readback live.
    ///
    /// OVERRIDABLE FOR THE PROBE, AND ONLY FOR IT. Without this the probe and the
    /// running home write the same three files: the probe's scene appears on the
    /// owner's real showcase, and its readback overwrites the live one. A gate
    /// that disturbs the surface it is measuring is the fault
    /// `a-checks-red-run-must-not-damage-the-repo` was written about, in pixels.
    static var stateDirOverride: URL?
    static var stateDir: URL {
        stateDirOverride
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/VESPER")
    }
    static var scenePath: URL { stateDir.appendingPathComponent("showcase.json") }
    static var askPath: URL { stateDir.appendingPathComponent("showcase-ask.json") }
    static var saidPath: URL { stateDir.appendingPathComponent("showcase-said.json") }

    private var window: NSWindow?
    private var base: WKWebView?
    private var marks: PassThroughWeb?
    private var sites: [String: WKWebView] = [:]
    private var siteRects: [String: CGRect] = [:]
    private let files = ShowcaseFiles()

    private var timer: Timer?
    private var lastRevision = -1
    /// The revision that has actually been DRAWN, which is not the one that has
    /// been READ.
    ///
    /// THESE WERE ONE FIELD AND IT WAS A RACE. `writeSaid()` runs at the end of
    /// the tick; the push that draws the scene answers asynchronously, after it.
    /// So the readback said "revision 1" while `panes_drawn` was still empty, the
    /// Python side saw the revision it was waiting for, read no panes, and
    /// reported a scene that had drawn perfectly as a scene that had not drawn at
    /// all. Measured 2026-09-15, first live run. The fix is not a longer wait --
    /// a wait tuned to a race is a race that comes back on a slower day -- it is
    /// to publish the number only once the thing it claims has happened.
    private var drawnRevision = -1
    /// True when the glass door would not open for the marks layer. See `start()`.
    private var marksBlocked = false
    /// Both layers have finished loading. Pushing before this is the race above.
    private var baseLoaded = false
    /// VESPER has no Desktop of its own yet, so it has nowhere to show anything.
    private var awaitingDesktop = false
    private var marksLoaded = false
    private var lastScene: [String: Any] = [:]
    private var lastRunBodies: [String: String] = [:]
    /// Lines currently shown per `run` pane -- the live tail, made readable.
    private var runTails: [String: Int] = [:]
    private var lastAskSeq = 0
    private var answers: [String: Any] = [:]
    private var drawnPanes: [String] = []
    private var drawnMarks = 0
    private var pageErrors: [String] = []
    private var boardStrokes: [Any] = []
    private var grantsCache: [String: String] = [:]
    private var grantsAt = Date.distantPast

    /// A navigation that somebody is waiting on. Keyed by the pane, because two
    /// panes may be loading at once and the answer must reach the right ask.
    private var pendingNav: [String: Int] = [:]

    // MARK: Starting

    /// Open the window and begin reading. Idempotent.
    ///
    /// NOT OPENED AT LOGIN AND NOT SHOWN AT OPEN. The owner asked for work to
    /// happen with the screen activity HIDDEN while he works; so the window is
    /// built, ordered out, and only brought forward when a scene says `visible`.
    /// Building it early is what makes the reveal instant when it is asked for.
    func start() {
        guard window == nil else { return }
        let screen = NSScreen.main ?? NSScreen.screens.first
        let full = screen?.visibleFrame ?? CGRect(x: 0, y: 0, width: 1440, height: 900)
        // Inset, not full-screen: a showcase that covers everything cannot be
        // told apart from a takeover, and the owner asked for the opposite.
        let frame = full.insetBy(dx: full.width * 0.04, dy: full.height * 0.05)
        let w = NSWindow(contentRect: frame,
                         styleMask: [.titled, .closable, .miniaturizable, .resizable],
                         backing: .buffered, defer: false)
        w.title = "VESPER — showing"
        w.isReleasedWhenClosed = false
        w.collectionBehavior = [.managed]
        w.backgroundColor = NSColor(calibratedWhite: 0.06, alpha: 1)
        w.titlebarAppearsTransparent = true
        let host = NSView(frame: CGRect(origin: .zero, size: frame.size))
        host.autoresizingMask = [.width, .height]
        w.contentView = host

        let cfg = WKWebViewConfiguration()
        cfg.setURLSchemeHandler(files, forURLScheme: ShowcaseFiles.scheme)
        cfg.userContentController.add(self, name: "showcaseSaid")
        // THE ERROR TRAP BEFORE THE PAGE'S OWN SCRIPTS, for the reason HomeChrome
        // installs one: a throw in an early receiver silently kills every later
        // one and still reports a push that worked.
        cfg.userContentController.addUserScript(WKUserScript(source: """
            window.__vesperShowErrs = [];
            window.addEventListener('error', function (e) {
              if (window.__vesperShowErrs.length > 20) return;
              window.__vesperShowErrs.push((e.message || '?') + ' @'
                + (e.lineno || '?') + ':' + (e.colno || '?'));
            }, true);
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))

        let b = WKWebView(frame: host.bounds, configuration: cfg)
        b.autoresizingMask = [.width, .height]
        // THROUGH GLASSGUARD'S DOOR, NOT THE RAW SELECTOR. `glass-hatch-contained`
        // caught the first version reaching for the private background knob here
        // and in the marks layer -- two unreviewed copies of a hatch whose whole
        // licence is that it lives in one file beside its alarm. The base paints
        // its own ground, so a closed door costs it only a pale frame before load.
        _ = GlassGuard.makeTransparent(b)
        host.addSubview(b)
        base = b

        let markCfg = WKWebViewConfiguration()
        markCfg.setURLSchemeHandler(ShowcaseFiles(), forURLScheme: ShowcaseFiles.scheme)
        let m = PassThroughWeb(frame: host.bounds, configuration: markCfg)
        m.autoresizingMask = [.width, .height]
        // THE MARKS LAYER CANNOT LIVE WITHOUT THE DOOR. An opaque web view over the
        // whole window would paint every pane out, and the owner would see a
        // blank showcase that reports drawing perfectly. So a closed door HIDES
        // the layer and says so in the readback: the panes stay visible, the
        // arrows are named as missing, and nothing claims otherwise.
        if !GlassGuard.makeTransparent(m) {
            m.isHidden = true
            marksBlocked = true
        }
        host.addSubview(m)
        marks = m

        // THE DELEGATE IS SET ON BOTH LAYERS, not only on the site panes, so the
        // tick can tell "the page is not ready yet" from "the page is broken".
        b.navigationDelegate = self
        m.navigationDelegate = self
        let html = Self.page()
        b.loadHTMLString(Self.layered(html, "base"), baseURL: nil)
        m.loadHTMLString(Self.layered(html, "marks"), baseURL: nil)

        window = w
        w.orderOut(nil)
        startReading()
        print("showcase: built, hidden, reading \(Self.scenePath.path)")
    }

    private static func layered(_ html: String, _ layer: String) -> String {
        // The SAME page in both layers, told which half of itself to run. One
        // file means the gate that drives the DOM drives what the app loads,
        // rather than a copy of it that can drift.
        "<script>window.__vesperShowLayer=\"\(layer)\";</script>\n" + html
    }

    /// The page, from the bundle if it is there and from the repo if it is not.
    ///
    /// THE REPO FALLBACK IS FOR THIS MACHINE, where the app is run out of a
    /// working tree as often as out of a built bundle, and a missing resource
    /// would look like a rendering bug.
    static func page() -> String {
        if let url = Bundle.main.url(forResource: "showcase", withExtension: "html"),
           let s = try? String(contentsOf: url, encoding: .utf8) { return s }
        let here = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        for rel in ["app/home-macos/chrome/showcase.html",
                    "../app/home-macos/chrome/showcase.html"] {
            let u = here.appendingPathComponent(rel)
            if let s = try? String(contentsOf: u, encoding: .utf8) { return s }
        }
        return "<body><p style=\"color:#fff;font:14px -apple-system\">"
             + "showcase.html is not in the bundle and not in the repo</p></body>"
    }

    // MARK: Reading

    private func startReading() {
        timer?.invalidate()
        // 0.25 s, the same tick the home chrome uses and for the same reasons:
        // one small file and one evaluated string, measured at a fraction of a
        // percent of a core. Faster buys nothing a person can see; slower makes
        // a demonstration feel like it is lagging its narration.
        let t = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func readJSON(_ url: URL) -> [String: Any] {
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
        else { return [:] }
        return o
    }

    private func tick() {
        let scene = readJSON(Self.scenePath)
        let rev = (scene["revision"] as? NSNumber)?.intValue ?? 0
        var changed = rev != lastRevision
        // A RUN PANE IS LIVE WITHOUT A NEW REVISION. The owner asked to "keep
        // going with it live": the record on disk grows while nothing republishes,
        // so the tail is re-read here and a change is a redraw. Compared by
        // content rather than by mtime, because a file rewritten with the same
        // bytes is not news and a redraw every quarter second would make text
        // unreadable.
        var scene2 = scene
        if var panes = scene["panes"] as? [[String: Any]] {
            for i in panes.indices where (panes[i]["kind"] as? String) == "run" {
                let id = (panes[i]["id"] as? String) ?? ""
                let path = (panes[i]["path"] as? String) ?? ""
                let body = Self.tail(path, lines: (panes[i]["lines"] as? NSNumber)?.intValue ?? 60)
                panes[i]["body"] = body
                if lastRunBodies[id] != body { changed = true }
                lastRunBodies[id] = body
                // WHAT THE OWNER IS WATCHING GROW, MADE OBSERVABLE. Without this
                // the live tail is a claim: `panes_drawn` is identical whether
                // the run produced another line or died, and the only other way
                // to check would be a screenshot -- which needs a grant this
                // machine does not have. One number per run pane turns "it keeps
                // up with the run" into something a gate can assert.
                runTails[id] = body.isEmpty ? 0 : body.components(separatedBy: "\n").count
            }
            scene2["panes"] = panes
        }
        // NOTHING IS PUSHED INTO A PAGE THAT HAS NOT PARSED ITS OWN SCRIPT YET.
        // The receiver does not exist until then, and the throw that follows is
        // indistinguishable from a page with a real fault in it.
        guard baseLoaded, marksLoaded else { writeSaid(); return }
        if changed {
            lastRevision = rev
            lastScene = scene2
            push(scene2)
            place(scene2)
        }
        serveAsks()
        writeSaid()
    }

    private static func tail(_ path: String, lines: Int) -> String {
        guard !path.isEmpty, ShowcaseFiles.mayServe(path),
              let s = try? String(contentsOfFile: (path as NSString).expandingTildeInPath,
                                  encoding: .utf8) else { return "" }
        let all = s.components(separatedBy: "\n")
        let n = max(1, min(lines, 200))
        return all.suffix(n).joined(separator: "\n")
    }

    private func push(_ scene: [String: Any]) {
        guard let b = base,
              let d = try? JSONSerialization.data(withJSONObject: scene),
              let json = String(data: d, encoding: .utf8) else { return }
        let literal = Self.jsString(json)
        b.evaluateJavaScript("window.__vesperShow(\(literal));") { [weak self] val, err in
            guard let self else { return }
            if let err {
                // THE REVISION IS NOT ADVANCED. A caller waiting on it times out
                // and says the showcase is not drawing, which is the truth.
                //
                // AND THE TICK IS TOLD TO TRY AGAIN. Measured on the live window,
                // 2026-09-15: the first push after a restart raced the page load,
                // threw, and `lastRevision` had ALREADY been set to the scene it
                // failed on -- so no later tick saw a change and the showcase sat
                // dead until something published a new revision. It reported the
                // failure honestly and then never retried, which is the worst of
                // both: a surface the owner is looking at, blank, with a true
                // error nobody is watching. Forgetting the revision here makes
                // the next tick re-push it a quarter second later.
                self.pageErrors = ["base push failed: \(err.localizedDescription)"]
                self.drawnPanes = []
                self.lastRevision = -1
                self.writeSaid()
                return
            }
            let got = (val as? String).flatMap {
                (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            } ?? [:]
            self.drawnPanes = (got["panes"] as? [String]) ?? []
            self.pageErrors = (got["errors"] as? [String]) ?? []
            var rects: [String: CGRect] = [:]
            for (id, raw) in (got["rects"] as? [String: [String: NSNumber]]) ?? [:] {
                rects[id] = CGRect(x: raw["x"]?.doubleValue ?? 0,
                                   y: raw["y"]?.doubleValue ?? 0,
                                   width: raw["w"]?.doubleValue ?? 0,
                                   height: raw["h"]?.doubleValue ?? 0)
            }
            self.siteRects = rects
            self.layoutSites(scene)
            // THE MARKS LAYER IS PUSHED AFTER THE RECTS COME BACK, never before.
            // An arrow placed against a pane whose position is not yet known is an
            // arrow drawn at the origin, which looks like a rendering bug and is
            // an ordering one.
            self.pushMarks(scene, rects: rects,
                           revision: (scene["revision"] as? NSNumber)?.intValue ?? 0)
        }
    }

    private func pushMarks(_ scene: [String: Any], rects: [String: CGRect],
                           revision: Int) {
        guard let m = marks, !marksBlocked else {
            // NO MARKS LAYER IS STILL A FINISHED DRAW -- of the panes. Without this
            // the revision would never be published and every act would time out
            // claiming the showcase was not drawing, on a surface that had drawn.
            // What did NOT draw is said, so `showcase.scene` can name it.
            drawnMarks = 0
            if marksBlocked {
                pageErrors.append("the marks layer is hidden: the glass door is closed "
                    + "on this macOS, so arrows, rings, ink, labels and the cursor "
                    + "cannot draw")
            }
            drawnRevision = revision
            writeSaid()
            return
        }
        var payload = scene
        var r: [String: [String: Double]] = [:]
        for (id, rect) in rects {
            r[id] = ["x": rect.origin.x, "y": rect.origin.y,
                     "w": rect.size.width, "h": rect.size.height]
        }
        payload["rects"] = r
        guard let d = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: d, encoding: .utf8) else { return }
        m.evaluateJavaScript("window.__vesperShow(\(Self.jsString(json)));") {
            [weak self] val, _ in
            guard let self else { return }
            let got = (val as? String).flatMap {
                (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            } ?? [:]
            self.drawnMarks = (got["marks"] as? NSNumber)?.intValue ?? 0
            if let errs = got["errors"] as? [String], !errs.isEmpty {
                self.pageErrors += errs
            }
            // THE LAST THING TO FINISH PUBLISHES THE NUMBER. Everything for this
            // scene has now drawn, so "drew revision N" is true when it is said
            // rather than a quarter of a second before.
            self.drawnRevision = revision
            self.writeSaid()
        }
    }

    /// A JSON blob as a JavaScript string literal.
    ///
    /// THROUGH `JSONSerialization`, NOT BY HAND. Escaping a JSON document into a
    /// JavaScript source string by replacing quotes is the classic way to produce
    /// a page that works until a file path contains a backslash.
    private static func jsString(_ s: String) -> String {
        guard let d = try? JSONSerialization.data(withJSONObject: [s]),
              let arr = String(data: d, encoding: .utf8) else { return "\"\"" }
        return String(arr.dropFirst().dropLast())
    }

    // MARK: Web panes

    private func layoutSites(_ scene: [String: Any]) {
        guard let host = window?.contentView, let b = base else { return }
        let panes = (scene["panes"] as? [[String: Any]]) ?? []
        var wanted: [String: String] = [:]
        for p in panes where (p["kind"] as? String) == "web" {
            wanted[(p["id"] as? String) ?? ""] = (p["url"] as? String) ?? ""
        }
        for (id, view) in sites where wanted[id] == nil {
            view.removeFromSuperview()
            sites.removeValue(forKey: id)
        }
        for (id, url) in wanted where !id.isEmpty {
            let view: WKWebView
            if let existing = sites[id] {
                view = existing
            } else {
                let cfg = WKWebViewConfiguration()
                let v = WKWebView(frame: .zero, configuration: cfg)
                v.navigationDelegate = self
                // ABOVE THE BASE, BELOW THE MARKS. The order is the whole design
                // and getting it wrong is invisible until an arrow disappears.
                host.addSubview(v, positioned: .above, relativeTo: b)
                if let m = marks { host.addSubview(m, positioned: .above, relativeTo: v) }
                sites[id] = v
                view = v
                if let u = URL(string: url) { v.load(URLRequest(url: u)) }
            }
            if let rect = siteRects[id] {
                // CSS IS TOP-LEFT AND APPKIT IS BOTTOM-LEFT. The one conversion in
                // this file, in one place, named.
                let h = host.bounds.height
                view.frame = CGRect(x: rect.origin.x,
                                    y: h - rect.origin.y - rect.size.height,
                                    width: rect.size.width, height: rect.size.height)
            }
        }
    }

    private func site(_ pane: String?) -> (String, WKWebView)? {
        if let pane, let v = sites[pane] { return (pane, v) }
        if sites.count == 1, let first = sites.first { return (first.key, first.value) }
        return nil
    }

    // MARK: Placement

    private func place(_ scene: [String: Any]) {
        guard let w = window else { return }
        let visible = (scene["visible"] as? Bool) ?? false
        let desktop = (scene["desktop"] as? String) ?? "vesper"
        if desktop == "here" {
            // THE OWNER ASKED FOR IT HERE, so it comes here — and `.moveToActiveSpace`
            // is the supported way to say that. Nothing private is needed for the
            // direction that interrupts him; the hatch is only for the direction
            // that does not.
            var behaviour = w.collectionBehavior
            behaviour.insert(.moveToActiveSpace)
            w.collectionBehavior = behaviour
        } else {
            var behaviour = w.collectionBehavior
            behaviour.remove(.moveToActiveSpace)
            w.collectionBehavior = behaviour
            toVespersDesktop()
        }
        // NO GROUND MEANS NO DESKTOP OF ITS OWN -- and then "show it on yours"
        // cannot be honoured without doing the one thing the owner ruled out.
        // The home waits for an EMPTY Desktop before it creates its ground, so
        // until that happens there is nowhere of VESPER's to put this, and
        // ordering it front would drop it over the owner's work -- the exact
        // interruption this surface exists to avoid. It stays hidden and SAYS SO,
        // and `showcase.reveal` reports that rather than claiming a screen it
        // never took.
        awaitingDesktop = (desktop == "vesper" && Self.groundWindow() == nil)
        if visible && !awaitingDesktop {
            w.orderFrontRegardless()
        } else {
            w.orderOut(nil)
        }
    }

    /// Put the showcase where the home's ground is, and READ BACK whether it went.
    ///
    /// THE LADDER IS `window_relocate`'S, not a second one. Ask, re-read, and
    /// report what is true — never what was requested. `SpacesHatch.relocate`
    /// already does the re-read and already tries the second mechanism when the
    /// first silently does nothing, which is the measured behaviour on this host.
    private func toVespersDesktop() {
        guard let w = window, let ground = Self.groundWindow() else { return }
        let mine = Int(w.windowNumber)
        let ids = SpacesHatch.spaces(of: [mine, ground])
        guard let there = ids[ground] else { return }
        if ids[mine] == there { return }
        let out = SpacesHatch.relocate(windowId: mine, to: there)
        if (out["ok"] as? Bool) != true {
            print("showcase: could not reach vesper's desktop — \(out["reason"] ?? "")")
        }
    }

    private static func groundWindow() -> Int? {
        // The home's ground IS VESPER's Desktop — the same definition
        // `--windows-list` answers `vespers_desktop` with, so the two agree by
        // construction rather than by coincidence.
        for w in NSApp.windows where w is GroundWindow { return Int(w.windowNumber) }
        return nil
    }

    private func onVespersDesktop() -> Bool {
        guard let w = window, let ground = Self.groundWindow() else { return false }
        let ids = SpacesHatch.spaces(of: [Int(w.windowNumber), ground])
        guard let a = ids[Int(w.windowNumber)], let b = ids[ground] else { return false }
        return a == b
    }

    // MARK: Asks — driving the showcase's own browser

    private func serveAsks() {
        let file = readJSON(Self.askPath)
        guard let asks = file["asks"] as? [[String: Any]] else { return }
        for ask in asks {
            let seq = (ask["seq"] as? NSNumber)?.intValue ?? 0
            guard seq > lastAskSeq else { continue }
            lastAskSeq = seq
            run(ask, seq: seq)
        }
    }

    /// `finish` from off the main thread.
    ///
    /// EVERY ANSWER IS WRITTEN ON THE MAIN THREAD, because `answers` is also read
    /// there four times a second. Two threads and one dictionary is the shape of
    /// the temp-name race this corpus already paid for once.
    @MainActor
    private func answer(_ seq: Int, _ body: [String: Any]) {
        finish(seq, body)
    }

    private func finish(_ seq: Int, _ body: [String: Any]) {
        answers[String(seq)] = body
        if answers.count > 64 {
            // Bounded, and the OLDEST go: a waiter polls for its own sequence and
            // an answer nobody collected in sixty-four asks is an answer nobody is
            // waiting for.
            let keep = answers.keys.compactMap(Int.init).sorted().suffix(64)
            answers = answers.filter { keep.contains(Int($0.key) ?? -1) }
        }
        writeSaid()
    }

    private func run(_ ask: [String: Any], seq: Int) {
        let verb = (ask["verb"] as? String) ?? ""
        let pane = ask["pane"] as? String

        // ANSWERED HERE, BEFORE A WEB PANE IS LOOKED FOR, because this one is not
        // about a page at all.
        //
        // AND BECAUSE THIS PROCESS IS THE ONLY ONE THAT MAY BE ASKED. CLAUDE.md,
        // measured 2026-08-30: "TCC attributes to the RESPONSIBLE PROCESS, which
        // is the shell". A grant read from a process a terminal spawned is the
        // TERMINAL's grant, and `showcase.follow` did exactly that on its first live
        // run -- it answered "yes, vesper can see your screen" from a reading that
        // was not about VESPER. The home is launched by launchd as the bundle, so
        // its answer is the one that is true, and it is the only one taken.
        if verb == "screen" {
            let allowed = CGPreflightScreenCaptureAccess()
            guard allowed else {
                finish(seq, ["ok": false, "granted": false,
                             "reason": "screen recording is not granted to vesper"])
                return
            }
            // SCREENCAPTUREKIT, NOT `CGWindowListCreateImage`. The old call is
            // unavailable on this SDK -- the compiler refuses it outright, which
            // is a better outcome than the deprecation warning it used to be:
            // a build that still linked would have shipped a capture path that
            // returns a picture of the wallpaper when the grant is missing, and
            // "vesper photographed your screen" would have been false in exactly
            // the case that matters.
            guard #available(macOS 14.0, *) else {
                finish(seq, ["ok": false, "granted": true,
                             "reason": "this macOS is older than the capture route vesper uses"])
                return
            }
            Task { [weak self] in
                guard let self else { return }
                do {
                    let content = try await SCShareableContent.excludingDesktopWindows(
                        false, onScreenWindowsOnly: true)
                    guard let display = content.displays.first else {
                        await self.answer(seq, ["ok": false, "granted": true,
                                                "reason": "no display answered"])
                        return
                    }
                    let filter = SCContentFilter(display: display, excludingWindows: [])
                    let cfg = SCStreamConfiguration()
                    cfg.width = display.width
                    cfg.height = display.height
                    let img = try await SCScreenshotManager.captureImage(
                        contentFilter: filter, configuration: cfg)
                    let rep = NSBitmapImageRep(cgImage: img)
                    guard let png = rep.representation(using: .png, properties: [:]) else {
                        await self.answer(seq, ["ok": false, "granted": true,
                                                "reason": "the screen image would not encode"])
                        return
                    }
                    let out = Showcase.stateDir.appendingPathComponent("screen.png")
                    try FileManager.default.createDirectory(
                        at: Showcase.stateDir, withIntermediateDirectories: true)
                    try png.write(to: out)
                    await self.answer(seq, ["ok": true, "granted": true,
                                            "path": out.path,
                                            "width": img.width, "height": img.height,
                                            "line": "photographed the screen"])
                } catch {
                    // THE THROW IS THE HONEST SIGNAL. `SCShareableContent` refuses
                    // when the grant is missing, which is a stronger answer than
                    // any preflight: it is the capture itself saying no.
                    await self.answer(seq, ["ok": false, "granted": false,
                                            "reason": "vesper could not photograph the "
                                                    + "screen: \(error.localizedDescription)"])
                }
            }
            return
        }

        guard let (id, view) = site(pane) else {
            finish(seq, ["ok": false,
                         "reason": "there is no web pane on the showcase to drive"])
            return
        }
        switch verb {
        case "navigate":
            guard let raw = ask["url"] as? String, let u = URL(string: raw) else {
                finish(seq, ["ok": false, "reason": "that is not an address"]); return
            }
            pendingNav[id] = seq
            view.load(URLRequest(url: u))
        case "back":
            if view.canGoBack { pendingNav[id] = seq; view.goBack() }
            else { finish(seq, ["ok": false, "reason": "there is nothing to go back to"]) }
        case "reload":
            pendingNav[id] = seq
            view.reload()
        case "read":
            let sel = (ask["selector"] as? String) ?? "body"
            js(view, """
               (function(){var e=document.querySelector(\(Self.jsString(sel)));
                 return JSON.stringify({ok:!!e,found:!!e,
                   url:location.href,title:document.title,
                   text:(e?(e.innerText||e.textContent||''):'').slice(0,8000)});})()
               """, seq: seq)
        case "click":
            let sel = (ask["selector"] as? String) ?? ""
            js(view, """
               (function(){var e=document.querySelector(\(Self.jsString(sel)));
                 if(!e) return JSON.stringify({ok:false,found:false,
                   reason:'nothing on the page matches ' + \(Self.jsString(sel))});
                 e.scrollIntoView({block:'center'});
                 e.click();
                 return JSON.stringify({ok:true,found:true,url:location.href,
                   title:document.title,line:'clicked it'});})()
               """, seq: seq)
        case "type":
            let sel = (ask["selector"] as? String) ?? ""
            let text = (ask["text"] as? String) ?? ""
            js(view, """
               (function(){var e=document.querySelector(\(Self.jsString(sel)));
                 if(!e) return JSON.stringify({ok:false,found:false,
                   reason:'nothing on the page matches ' + \(Self.jsString(sel))});
                 e.focus();
                 var v=\(Self.jsString(text));
                 if('value' in e){ e.value=v; } else { e.textContent=v; }
                 e.dispatchEvent(new Event('input',{bubbles:true}));
                 e.dispatchEvent(new Event('change',{bubbles:true}));
                 // READ IT BACK OFF THE ELEMENT, not off the variable we set. A
                 // field that rejects or rewrites what was typed is common and
                 // reporting the intent instead of the result would hide it.
                 return JSON.stringify({ok:true,found:true,
                   text:(('value' in e)?e.value:e.textContent||'').slice(0,2000),
                   url:location.href,title:document.title,line:'typed it'});})()
               """, seq: seq)
        case "key":
            let key = (ask["key"] as? String) ?? "Enter"
            js(view, """
               (function(){var e=document.activeElement||document.body;
                 var k=\(Self.jsString(key));
                 ['keydown','keypress','keyup'].forEach(function(t){
                   e.dispatchEvent(new KeyboardEvent(t,{key:k,bubbles:true}));});
                 if(k==='Enter'&&e.form&&e.form.requestSubmit){e.form.requestSubmit();}
                 return JSON.stringify({ok:true,url:location.href,
                   title:document.title,line:'pressed '+k});})()
               """, seq: seq)
        case "scroll":
            let amount = (ask["amount"] as? NSNumber)?.doubleValue ?? 400
            js(view, """
               (function(){window.scrollBy(0,\(amount));
                 return JSON.stringify({ok:true,url:location.href,
                   title:document.title,line:'scrolled'});})()
               """, seq: seq)
        case "wait_for":
            waitFor(view, ask: ask, seq: seq,
                    deadline: Date().addingTimeInterval(
                        ((ask["timeout_ms"] as? NSNumber)?.doubleValue ?? 8000) / 1000))
        case "shot":
            let cfg = WKSnapshotConfiguration()
            view.takeSnapshot(with: cfg) { [weak self] img, err in
                guard let self else { return }
                guard let img, let tiff = img.tiffRepresentation,
                      let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    self.finish(seq, ["ok": false,
                                      "reason": err?.localizedDescription
                                              ?? "the page would not be photographed"])
                    return
                }
                let out = Showcase.stateDir
                    .appendingPathComponent("showcase-\(seq).png")
                try? png.write(to: out)
                self.finish(seq, ["ok": true, "path": out.path,
                                  "line": "photographed the page"])
            }
        default:
            finish(seq, ["ok": false, "reason": "\(verb) is not something vesper asks a page to do"])
        }
    }

    private func waitFor(_ view: WKWebView, ask: [String: Any], seq: Int, deadline: Date) {
        let sel = (ask["selector"] as? String) ?? ""
        let contains = (ask["contains"] as? String) ?? ""
        let probe = """
            (function(){
              var okSel = \(Self.jsString(sel)) ? !!document.querySelector(\(Self.jsString(sel))) : true;
              var okTxt = \(Self.jsString(contains))
                ? (document.body ? (document.body.innerText||'') : '').indexOf(\(Self.jsString(contains))) >= 0
                : true;
              return JSON.stringify({ok: okSel && okTxt, found: okSel && okTxt,
                url: location.href, title: document.title});})()
            """
        view.evaluateJavaScript(probe) { [weak self] val, _ in
            guard let self else { return }
            let got = (val as? String).flatMap {
                (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            } ?? [:]
            if (got["ok"] as? Bool) == true {
                self.finish(seq, got.merging(["line": "it appeared"]) { a, _ in a })
            } else if Date() >= deadline {
                // A TIMEOUT IS A REFUSAL AND SAYS SO. Reporting `ok` after giving
                // up is how a driven website silently walks off its script.
                self.finish(seq, ["ok": false, "found": false,
                                  "reason": "it did not appear before the time ran out",
                                  "url": got["url"] ?? "", "title": got["title"] ?? ""])
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    self.waitFor(view, ask: ask, seq: seq, deadline: deadline)
                }
            }
        }
    }

    private func js(_ view: WKWebView, _ source: String, seq: Int) {
        view.evaluateJavaScript(source) { [weak self] val, err in
            guard let self else { return }
            if let err {
                self.finish(seq, ["ok": false,
                                  "reason": "the page refused: \(err.localizedDescription)"])
                return
            }
            let got = (val as? String).flatMap {
                (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            } ?? ["ok": false, "reason": "the page answered nothing"]
            self.finish(seq, got)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if webView === base { baseLoaded = true }
        if webView === marks { marksLoaded = true }
        guard let id = sites.first(where: { $0.value === webView })?.key,
              let seq = pendingNav.removeValue(forKey: id) else { return }
        webView.evaluateJavaScript("JSON.stringify({url:location.href,title:document.title})") {
            [weak self] val, _ in
            let got = (val as? String).flatMap {
                (try? JSONSerialization.jsonObject(with: Data($0.utf8))) as? [String: Any]
            } ?? [:]
            self?.finish(seq, ["ok": true, "url": got["url"] ?? "",
                               "title": got["title"] ?? "", "line": "the page loaded"])
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        failNav(webView, error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        failNav(webView, error)
    }

    private func failNav(_ webView: WKWebView, _ error: Error) {
        guard let id = sites.first(where: { $0.value === webView })?.key,
              let seq = pendingNav.removeValue(forKey: id) else { return }
        finish(seq, ["ok": false, "reason": error.localizedDescription])
    }

    // MARK: The page talking back

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard message.name == "showcaseSaid",
              let body = message.body as? [String: Any] else { return }
        // THE OWNER MAY DRAW ON THE WHITEBOARD TOO, and what they draw comes back
        // here so VESPER can read it. A board VESPER can only write to is a slide.
        if let strokes = body["board"] as? [Any] { boardStrokes = strokes }
        if let errs = body["errors"] as? [String] { pageErrors = errs }
        writeSaid()
    }

    // MARK: Saying what is true

    private func writeSaid() {
        var out: [String: Any] = [
            "open": window != nil,
            "visible": window?.isVisible ?? false,
            // DRAWN, NOT READ. See `drawnRevision` for the race this closed.
            "revision": drawnRevision,
            "read_revision": lastRevision,
            "panes_drawn": drawnPanes,
            "marks_drawn": drawnMarks,
            "marks_blocked": marksBlocked,
            "run_tails": runTails,
            "errors": pageErrors,
            "answers": answers,
            "board": boardStrokes,
            "window_id": String(window?.windowNumber ?? 0),
            "desktop": (lastScene["desktop"] as? String) ?? "vesper",
            "on_vespers_desktop": onVespersDesktop(),
            "awaiting_desktop": awaitingDesktop,
            "sites": Array(sites.keys),
        ]
        out["hatch"] = SpacesHatch.verify().usable
        // VESPER'S OWN GRANTS, READ BY VESPER. Cached, because this is written
        // four times a second and a TCC query is not free -- and refreshed often
        // enough that a grant given during the session is noticed within ten
        // seconds rather than at the next restart.
        if Date().timeIntervalSince(grantsAt) > 10 {
            var g: [String: String] = [:]
            for row in Grants.all() {
                g[row.what.lowercased()
                    .replacingOccurrences(of: " ", with: "_")
                    .replacingOccurrences(of: "&", with: "and")] = row.state
            }
            grantsCache = g
            grantsAt = Date()
        }
        out["grants"] = grantsCache
        guard let d = try? JSONSerialization.data(withJSONObject: out,
                                                  options: [.prettyPrinted]) else { return }
        let p = Self.saidPath
        try? FileManager.default.createDirectory(at: Self.stateDir,
                                                 withIntermediateDirectories: true)
        // THE SAME ATOMIC RULE PYTHON FOLLOWS, and the same temp-name discipline:
        // process AND THREAD, because two writers sharing a temp name produced a
        // file that was neither. Checked by
        // `an-atomic-write-never-shares-its-temp-name` on the Python side; this
        // writer is its counterpart and obeys the rule for the same reason.
        //
        // `Thread.current`, NOT `ObjectIdentifier(self)`. The first version hashed
        // the singleton -- one constant for the whole process -- under a comment
        // claiming "process AND thread". Every caller today is on the main thread
        // so nothing raced, which is exactly why it would have sat there: the
        // defect was in the comment, in a file whose whole doctrine is that a
        // comment carries the reason a thing is the way it is.
        let thread = UInt(bitPattern: ObjectIdentifier(Thread.current).hashValue)
        let tmp = p.deletingLastPathComponent().appendingPathComponent(
            "\(p.lastPathComponent).\(getpid()).\(thread).tmp")
        do {
            try d.write(to: tmp)
            _ = try FileManager.default.replaceItemAt(p, withItemAt: tmp)
        } catch {
            try? FileManager.default.removeItem(at: tmp)
        }
    }

    // MARK: Diagnosis

    /// `--showcase-probe`: open it, draw a known scene, and print what came back.
    ///
    /// AN INSTRUMENT THAT DRIVES THE REAL WINDOW, because the alternative is a
    /// gate that proves the JSON is well-formed and proves nothing about whether
    /// anything appeared.
    static func probe() {
        // ITS OWN STATE DIRECTORY, so this can run while the home is running and
        // neither one sees the other's scene.
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("vesper-showcase-probe-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        stateDirOverride = dir
        shared.start()
        let scene: [String: Any] = [
            "revision": 999_000,
            "why": "a probe, so the showcase can be proved rather than assumed",
            "visible": true, "desktop": "vesper",
            "panes": [
                ["id": "note", "kind": "text", "title": "a note",
                 "text": "if you can read this, the base layer drew"],
                ["id": "board", "kind": "board", "title": "the whiteboard"],
            ],
            "marks": [
                ["kind": "arrow", "pane": "note", "from": [0.1, 0.8], "at": [0.5, 0.4]],
                ["kind": "ring", "pane": "board", "at": [0.5, 0.5]],
                ["kind": "label", "pane": "board", "at": [0.5, 0.7], "text": "here"],
            ],
            "cursor": ["pane": "note", "x": 0.5, "y": 0.4, "gesture": "tap",
                       "visible": true],
        ]
        if let d = try? JSONSerialization.data(withJSONObject: scene) {
            try? FileManager.default.createDirectory(at: stateDir,
                                                     withIntermediateDirectories: true)
            try? d.write(to: scenePath)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            let s = shared
            print("showcase probe")
            print(String(repeating: "-", count: 60))
            print("  window open        \(s.window != nil)")
            print("  visible            \(s.window?.isVisible ?? false)")
            print("  panes drawn        \(s.drawnPanes.joined(separator: ", "))")
            print("  marks drawn        \(s.drawnMarks)")
            print("  on vesper's desktop \(s.onVespersDesktop())")
            print("  page errors        \(s.pageErrors.isEmpty ? "none" : s.pageErrors.joined(separator: " | "))")
            // FOUR, NOT THREE: the arrow, the ring, the label AND VESPER's own
            // cursor. The first version of this assertion said three and went red
            // against a surface that was drawing correctly -- the cursor is a
            // mark on that layer and counts like one, which is worth stating
            // because the number is otherwise a reader's guess.
            let good = s.drawnPanes.contains("note") && s.drawnPanes.contains("board")
                && s.drawnMarks == 4 && s.pageErrors.isEmpty
            print(String(repeating: "-", count: 60))
            print(good ? "  the showcase drew what it was asked to draw"
                       : "  *** the showcase did NOT draw what it was asked to ***")
            if let dir = stateDirOverride { try? FileManager.default.removeItem(at: dir) }
            exit(good ? 0 : 2)
        }
    }
}
