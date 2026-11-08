// VESPER's home — the chrome layer. First light.
//
// HOME-ARCHITECTURE §1.1: the home is one window with two layers, a Metal field
// below carrying the ambience and the face, and a TRANSPARENT WEBVIEW above
// carrying the widgets, the cards and the main menu. The field has existed
// since F1. This is the first time anything has been mounted on top of it.
//
// WHAT HAD TO BE TRUE FIRST, and was not. `SPIKE-013` §0, measured 2026-08-23:
// a `WKWebView` cannot be made transparent with public API on macOS 26.5. Every
// public configuration paints #FFFFFF over the ground. §0.5 then measured that
// once transparency exists by any route, `backdrop-filter` genuinely does blur
// what is behind the webview -- 41-42 pt of smeared edge inside a card against
// 0 pt outside, over a real CAMetalLayer. That is what makes this layer worth
// having: the cards are glass over the LIVE FIELD, not glass over a picture of
// it.
//
// So the chrome mounts through `GlassGuard`, and it mounts CONDITIONALLY.
// GlassGuard.verify runs three controls and answers TRANSPARENT, OPAQUE or
// UNREADABLE, and only the first of those is allowed to mount anything.
// UNREADABLE is not a pass: a reader that cannot see WebKit content reports a
// clear chrome and an opaque one identically, and the failure it would wave
// through is a white rectangle over the owner's whole screen.
//
// THE CARD SAYS `UNAVAILABLE`, AND THAT IS THE POINT. `INV-HW-2` and the
// projection's own rule: a surface renders its reading or it renders nothing,
// and a number with no producer behind it is not a reading. There is no
// producer wired to the home yet, so the card says so in the place where the
// number will go. A plausible-looking figure here would be the exact defect the
// island's `projection-unknown-is-absent` check exists to refuse.

import AppKit
import WebKit
import ServiceManagement

// MARK: - The two directions between the page and the runtime

/// What the owner typed, on its way to the runtime.
///
/// THE WEBVIEW CANNOT REACH PYTHON AND MUST NOT TRY. It has no socket, no
/// interpreter and no business holding one: the page is a SURFACE, and a
/// surface that can start a process is a surface that can be talked into
/// starting one. So the field posts to Swift, Swift appends a line to a file,
/// and the runtime -- which already owns the bus, the ladder and the cost
/// policy -- picks it up. That is the same direction home.json already runs in,
/// reversed, rather than a second kind of channel.
///
/// APPEND, NEVER REWRITE. Two utterances typed a moment apart must both
/// survive; a whole-file write would drop whichever lost the race and report
/// nothing. One JSON object per line, which is also what makes a partial write
/// recoverable -- a torn last line is one lost utterance, not a lost file.
final class SayBridge: NSObject, WKScriptMessageHandler {

    static let name = "vesperSay"
    /// The page asking to be typed into.
    ///
    /// VESPER IS AN ACCESSORY APP (`LSUIElement`), so it has no Dock tile and
    /// does not become active by being clicked the way an ordinary app does.
    /// The ground can become key -- but only while the application is active,
    /// and nothing was making it active. So the field could be clicked, showed
    /// a caret, and still received no keystrokes.
    ///
    /// Requested by the PAGE rather than taken on every click: activating on
    /// any mouse-down anywhere would steal focus from whatever the owner is
    /// doing every time the cursor crossed the desktop, which is the behaviour
    /// SS10 refuses for the Dock and refuses here for the same reason.
    static let focusName = "vesperFocus"
    /// The page reporting how far through VESPER's own sentence it is.
    ///
    /// A CHANNEL, NOT A TRIGGER. The chrome does not tell the face to "look
    /// like it is talking" -- it reports which word of the reply is on screen,
    /// and Behaviour.swift decides what that looks like. Keeping the decision
    /// on the Swift side is what lets the audio path replace the SOURCE later
    /// without touching a line of the animation.
    static let speakingName = "vesperSpeaking"
    /// Set when a speaking report arrives. Read by the host's render tick.
    ///
    /// Held here rather than pushed straight at the driver because the message
    /// handler runs on the main queue between frames and the driver is stepped
    /// inside one -- writing a level the frame is halfway through reading is a
    /// tear nobody would ever see and nobody could ever explain.
    private(set) var speechLevel: Float = 0
    private(set) var speechIsFromText = false
    static var outbox: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/say.jsonl")
    }

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        if message.name == Self.focusName {
            NSApp.activate(ignoringOtherApps: true)
            if let w = message.webView?.window {
                w.makeKeyAndOrderFront(nil)
                w.makeFirstResponder(message.webView)
            }
            return
        }
        if message.name == Self.speakingName {
            guard let raw = message.body as? String,
                  let d = raw.data(using: .utf8),
                  let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
            else { return }
            let lvl = (o["level"] as? NSNumber)?.floatValue ?? 0
            // `none` IS AN EXPLICIT STATE, not the absence of a report. A page
            // that stops posting because it was torn down mid-sentence would
            // otherwise leave the face mouthing forever; the host's staleness
            // fallback would eventually correct it, and eventually is not the
            // same as correctly.
            speechIsFromText = (o["source"] as? String) == "textReveal"
            speechLevel = speechIsFromText ? min(max(lvl, 0), 1) : 0
            return
        }
        guard message.name == Self.name,
              let text = message.body as? String else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // TYPED, SO CERTAIN AND FINAL, and said explicitly rather than left to
        // a default. core/intake.py distinguishes `confidence: null` -- meaning
        // certainty is not a question on this channel -- from a recogniser's
        // 1.0, and the record cannot be audited later if the two collapse.
        let obj: [String: Any] = ["text": trimmed, "source": "typed",
                                  "final": true,
                                  "at_ms": Int(Date().timeIntervalSince1970 * 1000)]
        guard let data = try? JSONSerialization.data(withJSONObject: obj),
              var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"

        let url = Self.outbox
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            _ = try? h.seekToEnd()
            try? h.write(contentsOf: Data(line.utf8))
        } else {
            try? Data(line.utf8).write(to: url)
        }
    }
}


/// What the owner asked for with a BUTTON, on its way to the runtime.
///
/// THE OWNER, 2026-09-13: every surface showed readings and managed nothing.
/// This is the fourth channel out of the page, kept apart from the other
/// three for the same reason they are kept apart from each other: `vesperSay`
/// is a sentence, `vesperAct` is a re-derived argv, `vesperTerm` is the
/// owner's shell, and this is a MANAGEMENT REQUEST -- `{action, args}` -- that
/// the runtime applies through `core/controls.py`, where each action's KIND
/// decides who may apply it. Nothing is executed here: the page is not trusted
/// with arguments (see ActBridge), and this bridge only records what was
/// pressed, stamped with when and by which channel, into `control.jsonl` for
/// the runtime to drain. A preference is applied by the runtime; a governed
/// change is only RECORDED by it and confirmed by the host; an act goes back
/// through the typed path like any other request.
final class ControlBridge: NSObject, WKScriptMessageHandler {
    static let name = "vesperControl"
    static var queue: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/control.jsonl")
    }

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard message.name == Self.name,
              let raw = message.body as? String,
              let d = raw.data(using: .utf8),
              var o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let action = o["action"] as? String, !action.isEmpty
        else { return }
        o["at_ms"] = Int(Date().timeIntervalSince1970 * 1000)
        o["source"] = "home"
        // THE HOST'S OWN ACTIONS. `host.*` never reaches the runtime as a
        // request: the stop must not traverse the control plane it stops
        // (INV-STOP-2), a System Settings pane is the host's to open, and a
        // TCC reset is the owner's own machine speaking. Each is done here, on
        // the click, and what happened is then appended as `host.done` so the
        // runtime puts it on the bus beside everything else.
        if action.hasPrefix("host.") {
            let args = (o["args"] as? [String: Any]) ?? [:]
            let (ok, detail) = HostActions.perform(action, args)
            print("control: \(action) -> \(ok ? "ok" : "refused"): \(detail)")
            o = ["action": "host.done",
                 "args": ["what": action, "ok": ok, "detail": detail],
                 "at_ms": Int(Date().timeIntervalSince1970 * 1000),
                 "source": "host"]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: o),
              var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"
        let url = Self.queue
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let h = try? FileHandle(forWritingTo: url) {
            defer { try? h.close() }
            _ = try? h.seekToEnd()
            try? h.write(contentsOf: Data(line.utf8))
        } else {
            try? Data(line.utf8).write(to: url)
        }
        print("control: \(action) queued")
    }
}


/// The things only the host may do for a button: stop and re-arm autonomy,
/// open a privacy pane, read the grants, request speech consent, run the
/// gates, drop every grant. Each is a closed case; there is no generic "run".
enum HostActions {
    static let bundleID = Bundle.main.bundleIdentifier ?? "ai.vesper.island"
    static let state = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/VESPER")
    /// The panes a button may open. An allowlist, not a prefix match: a URL
    /// the page invented resolves to nothing.
    static let panes: Set<String> = [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars",
    ]

    @discardableResult
    static func run(_ argv: [String], cwd: String? = nil, wait: Bool = true,
                    stdout: URL? = nil) -> (Int32, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: argv[0])
        p.arguments = Array(argv.dropFirst())
        if let cwd { p.currentDirectoryURL = URL(fileURLWithPath: cwd) }
        var pipe: Pipe? = nil
        if let stdout {
            try? "".write(to: stdout, atomically: true, encoding: .utf8)
            if let h = try? FileHandle(forWritingTo: stdout) { p.standardOutput = h; p.standardError = h }
        } else {
            pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
        }
        do { try p.run() } catch { return (127, "\(error)") }
        if !wait { return (0, "started, pid \(p.processIdentifier)") }
        let out = pipe?.fileHandleForReading.readDataToEndOfFile() ?? Data()
        p.waitUntilExit()
        return (p.terminationStatus, String(data: out, encoding: .utf8) ?? "")
    }

    /// Where the project is, as the build recorded it (core/places.py reads the
    /// same line). Empty when the record is missing.
    static func projectRoot() -> String {
        guard let res = Bundle.main.resourceURL,
              let text = try? String(contentsOf: res.appendingPathComponent("runtime/place.toml"), encoding: .utf8)
        else { return "" }
        for line in text.split(separator: "\n") where line.hasPrefix("project_root") {
            let v = line.split(separator: "=", maxSplits: 1).last.map(String.init) ?? ""
            return v.trimmingCharacters(in: CharacterSet(charactersIn: " \"'"))
        }
        return ""
    }

    static func perform(_ action: String, _ args: [String: Any]) -> (Bool, String) {
        switch action {
        case "host.stop":
            // THE STOP. Unregistering the arm agent stops the minter; the
            // enable token expires within its TTL and autonomy halts
            // (INV-STOP-3). No dialog: a stop that asks first is not a stop.
            if #available(macOS 13.0, *) {
                do { try SMAppService.agent(plistName: "ai.vesper.island.arm.plist").unregister() }
                catch { return (false, "unregister failed: \(error)") }
                return (true, "arm agent unregistered; token expires within its TTL")
            }
            return (false, "needs macOS 13")
        case "host.rearm":
            if #available(macOS 13.0, *) {
                do { try SMAppService.agent(plistName: "ai.vesper.island.arm.plist").register() }
                catch { return (false, "register failed: \(error)") }
                return (true, "arm agent registered by the owner's click")
            }
            return (false, "needs macOS 13")
        case "host.open_url":
            guard let s = args["url"] as? String, panes.contains(s), let u = URL(string: s) else {
                return (false, "not an allowed pane")
            }
            NSWorkspace.shared.open(u)
            return (true, "opened \(s.split(separator: "?").last ?? "")")
        case "host.speech_consent":
            let (rc, out) = run(["/usr/bin/open", "-n", Bundle.main.bundlePath, "--args", "--speech-consent"])
            return (rc == 0, rc == 0 ? "consent requested as \(bundleID)" : out)
        case "host.read_grants":
            let out = state.appendingPathComponent("grants.txt").path
            let (rc, msg) = run(["/usr/bin/open", "-n", Bundle.main.bundlePath, "--args", "--grants", "--out", out])
            return (rc == 0, rc == 0 ? "grants being written to \(out)" : msg)
        case "host.mic_level":
            // §9g: MEASURE FIRST. Eight seconds of the owner's normal voice,
            // reported in dBFS, before any gain is chosen.
            let out = state.appendingPathComponent("mic-level.txt").path
            let (rc, msg) = run(["/usr/bin/open", "-n", Bundle.main.bundlePath, "--args",
                                 "--mic-level", "--seconds", "8", "--out", out])
            return (rc == 0, rc == 0 ? "measuring for 8 s -- speak normally; the reading lands in mic-level.txt" : msg)
        case "host.camera_probe":
            // The camera, measured: fps, faces, cpu -- and presence as a flag.
            let out = state.appendingPathComponent("camera-probe.txt").path
            let pres = state.appendingPathComponent("presence.json").path
            let (rc, msg) = run(["/usr/bin/open", "-n", Bundle.main.bundlePath, "--args",
                                 "--camera-probe", "--seconds", "5", "--out", out, "--presence-out", pres])
            return (rc == 0, rc == 0 ? "camera opening for 5 s as \(bundleID); the reading lands in camera-probe.txt" : msg)
        case "host.run_gates":
            let root = projectRoot()
            guard !root.isEmpty else { return (false, "the build recorded no project root") }
            // The gates need python >= 3.11 (tomllib); macOS ships 3.9. Look where a
            // per-user install lands rather than at one machine's home folder.
            guard let py = [NSHomeDirectory() + "/.local/bin/python3.13", "/opt/homebrew/bin/python3.13",
                            "/usr/local/bin/python3.13"]
                .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
                return (false, "no python3.13 found in ~/.local/bin, /opt/homebrew/bin or /usr/local/bin")
            }
            let log = state.appendingPathComponent("gates.log")
            let (_, msg) = run([py, "tools/ci/checks.py", "all"], cwd: root, wait: false, stdout: log)
            return (true, "gates \(msg); output in gates.log")
        case "host.panic_revoke":
            // THE ONE HOST ACTION THAT ASKS, because it costs the owner a grant
            // trip to undo. NSAlert, on the main thread where this handler runs.
            let a = NSAlert()
            a.messageText = "Revoke every grant?"
            a.informativeText = "This resets Accessibility, Screen Recording, Microphone, Camera, Speech, Automation and Calendars for \(bundleID) and stops autonomy. VESPER keeps running. Re-granting takes the grant trip."
            a.addButton(withTitle: "Revoke everything")
            a.addButton(withTitle: "Cancel")
            a.alertStyle = .critical
            guard a.runModal() == .alertFirstButtonReturn else { return (false, "cancelled by the owner") }
            let (rc, out) = run(["/usr/bin/tccutil", "reset", "All", bundleID])
            if #available(macOS 13.0, *) {
                try? SMAppService.agent(plistName: "ai.vesper.island.arm.plist").unregister()
            }
            return (rc == 0, rc == 0 ? "every TCC grant for \(bundleID) reset; arm agent unregistered" : out)
        default:
            return (false, "\(action) is not a host action")
        }
    }
}


final class HomeChrome {

    private(set) var web: WKWebView?
    private(set) var mounted = false
    /// Where the card landed, in the HOST's coordinates, so the region can be
    /// READ. "mounted" is the chrome's own word for what it did; whether a card
    /// is painting is a question for the window server.
    private(set) var cardRect: CGRect = .zero

    /// Sheet tier out of `DESIGN-FOUNDATION` §4 -- blur 24px, saturate 180%,
    /// fill α .055, radius 22px -- because these are cards, and §4 names Sheet
    /// for cards. The plate behind the face is Dock tier for the opposite
    /// reason: it is the largest surface in the composition.
    ///
    /// The card is placed in the left cluster of §14.1's ring, clear of the
    /// face's own square, so first light shows the two layers COEXISTING rather
    /// than one covering the other.
    /// The ink the card writes in — `DESIGN-FOUNDATION`'s warm off-white.
    static let inkLuma = 0.855      // relative luminance of #f4e6dc
    /// What the card's composited surface has to come down to for that ink to
    /// be readable on it. Solved from the ratio below, not chosen.
    static let inkContrastTarget = 4.5

    /// SOLVE THE CARD'S FILL, the same way the plate's was solved, for a
    /// different reason.
    ///
    /// The plate is solved so the FACE has a ground. A card is solved so its
    /// TEXT does. `DESIGN-FOUNDATION` §3 step 3 is explicit that lightness moves
    /// until the contrast target is met and that the target is measured against
    /// the COMPOSITED glass rather than the raw backdrop -- which is why a card
    /// that simply carries §4's `.055` fill is unadapted by definition: .055 is
    /// the tier's look, not an answer to what is behind it.
    ///
    /// NOT APCA, AND SAID SO. §3 names APCA `Lc ≥ 60` for text. This solves a
    /// WCAG-style luminance ratio instead, because APCA's exponents and
    /// coefficients are not something to reproduce from memory -- a contrast
    /// figure that is confidently wrong is worse than one that is honestly
    /// approximate. The ratio is a proxy, it is named as one here and in the
    /// readout, and §3's real target needs APCA's constants from source before
    /// this can claim to meet it.
    static func solvedFill(backdrop L: Double) -> Double {
        // (inkL + .05) / (groundL + .05) >= target  =>  groundL <= ...
        let ground = (inkLuma + 0.05) / inkContrastTarget - 0.05
        guard L > ground else { return 0 }
        return min(0.90, max(0, 1 - ground / max(L, 0.001)))
    }

    /// The eight slots the main menu holds, as NAMES not pictures.
    ///
    /// Owner, 2026-08-24: "same style as macos, only change is icons (we'll have
    /// to define them, then get them or build them)." So the geometry, the
    /// glass, the spacing and the behaviour are built to §10 and §14.2, and
    /// every slot carries a PLACEHOLDER glyph that is obviously one. Inventing
    /// eight icons and shipping them as though they were decided is how a
    /// placeholder becomes a design nobody chose.
    static let menuSlots = ["talk", "work", "make", "know",
                            "watch", "places", "time", "self"]

    /// The metrics card's rows, from the projection snapshot on disk.
    ///
    /// WHAT CHANGED, AND WHY THE ROWS ARE NOT HARDCODED `UNAVAILABLE` ANY MORE.
    /// This card carried five literal `UNAVAILABLE` rows since it was drawn, and
    /// the header above explains why that was right: a number with no producer
    /// behind it is not a reading. There is a producer now --
    /// `tools/home_snapshot.py` -- and it writes exactly the rows that resolved
    /// from a real routed call.
    ///
    /// OMISSION, NOT A PLACEHOLDER. `core/projection.py`'s `to_scene` already
    /// drops an unavailable reading rather than rendering one, "so the absent
    /// case cannot be styled into looking like the present case". Re-adding a
    /// row here for a key the snapshot omitted would rebuild in the surface
    /// exactly what the projection removed, and it would be this surface
    /// deciding what unknown looks like -- which is the coupling that file
    /// exists to prevent. So this renders what it is given and nothing else.
    ///
    /// WITH NOTHING TO SHOW IT SAYS SO ONCE. An empty card reads as broken and
    /// a card full of `UNAVAILABLE` reads as five failures; neither is true.
    /// One line naming the missing producer is a statement about the SYSTEM
    /// rather than a fake reading about the model, and it is the same choice
    /// `tools/island_snapshot.py` made when it wrote three columns instead of
    /// six.
    static func metricRows() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        var rows: [(String, String)] = []
        if let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let raw = obj["rows"] as? [[String: Any]] {
            for r in raw {
                // ONLY THIS CARD'S OWN ROWS. `home.json` carries the HOST
                // card's handful and the menu catalogue's 68 in one array,
                // and this loop used to take every one of them -- so the
                // first paint put all 72 readings inside the HOST card until
                // the first push replaced them. The producer tags what it
                // owns; a row without the tag belongs to another surface.
                guard (r["card"] as? String) == "host" else { continue }
                if let k = r["label"] as? String, let v = r["value"] as? String {
                    rows.append((k, v))
                }
            }
        }
        if rows.isEmpty {
            return "<div class=\"row\"><span class=\"k\">no producer</span>"
                 + "<span class=\"v\">run home_snapshot.py</span></div>"
        }
        return rows.map { k, v in
            "<div class=\"row\"><span class=\"k\">\(esc(k))</span>"
          + "<span class=\"v\">\(esc(v))</span></div>"
        // JOINED WITHOUT A NEWLINE, deliberately. This string is substituted
        // into the page by `page()`, which replaces the token wherever it
        // appears -- and a newline inside injected content ends any `//`
        // comment it lands in, turning the rest into raw JavaScript. That is
        // exactly what happened on 2026-09-08 (§9r): the token was mentioned
        // in a comment, this separator carried 68 newlines into it, the script
        // block failed to parse, and three receivers were never defined. The
        // comment is fixed too; this removes the mechanism rather than only
        // the instance.
        }.joined(separator: "")
    }

    /// What VESPER is doing, read from the state the runtime writes.
    ///
    /// THE FACE WAS BUILT AND NEVER CONNECTED. `Behaviour.swift` carries
    /// fourteen behaviours with distinct gaze, blink, breath and dispersal, and
    /// the only thing that has ever selected one is `--demo`, cycling them on a
    /// timer so they could be seen. So a face able to express thinking,
    /// listening and talking has been resting through every call VESPER has
    /// made -- the same built-and-unreached shape as `Provider.profile_id`
    /// sitting unread, and the egress class applied at registration and never
    /// at the choke point.
    ///
    /// READ, NOT PUSHED, and polled rather than notified. The runtime is a
    /// separate process; a push would need a second channel between the same
    /// two processes, and `tools/ops/alarm_wake_linux.py` records what two
    /// mechanisms writing one piece of state costs. The snapshot is already
    /// the channel.
    ///
    /// AN ABSENT FILE MEANS `resting`, WHICH IS THE TRUE READING. Nothing is
    /// running, so nothing is happening -- unlike a stale `thinking`, which
    /// would report work that is not occurring.
    /// VESPER's thoughts and actions, as the runtime last published them.
    ///
    /// READ FROM THE SAME FILE ON THE SAME TICK as the behaviour and the stage
    /// line. A second poll would be a second clock over one register, and the
    /// two would eventually disagree about the same moment.
    static func workbenchJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let w = o["workbench"],
              let out = try? JSONSerialization.data(withJSONObject: w)
        else { return "{}" }
        return String(data: out, encoding: .utf8) ?? "{}"
    }

    /// The changed-files board, as the runtime last published it.
    ///
    /// READ FROM THE SAME FILE ON THE SAME TICK as everything else. One poll,
    /// one register: a second timer over one file is how the two come to
    /// disagree about the same moment.
    static func changesJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let c = o["changes"],
              let out = try? JSONSerialization.data(withJSONObject: c)
        else { return "{}" }
        return String(data: out, encoding: .utf8) ?? "{}"
    }

    /// The metrics card's rows, as the runtime last published them.
    ///
    /// PUSHED ON THE TICK, NOT ONLY SUBSTITUTED AT MOUNT. `{{METRIC_ROWS}}` is
    /// filled once when the page is loaded, so the card was frozen at whatever
    /// was true when the home came up -- and the row that matters most on a
    /// laptop is the power source, which is precisely the one that changes
    /// while nobody is reloading anything.
    static func metricsJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let rows = o["rows"],
              let out = try? JSONSerialization.data(withJSONObject: rows)
        else { return "[]" }
        return String(data: out, encoding: .utf8) ?? "[]"
    }

    /// Every flag VESPER is currently raising, as the runtime published them.
    ///
    /// ONE DESTINATION FOR ALL OF THEM, per the owner 2026-09-09. Flags already
    /// existed and had nowhere to go: the relocation ladder returns
    /// `degraded: true` with a `notes` list that nothing renders, and
    /// `window_open` now reports a window the system placed on a Desktop VESPER
    /// cannot reach. Each of those would otherwise invent its own surface, and
    /// a flag nobody has a habit of looking at is a flag that does not exist.
    static func flagsJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let f = o["flags"],
              let out = try? JSONSerialization.data(withJSONObject: f)
        else { return "[]" }
        return String(data: out, encoding: .utf8) ?? "[]"
    }

    /// The flag HISTORY, which is a different question from the flag BAR.
    ///
    /// §21, owner 2026-09-11: "when i click the bar, i can see the full history
    /// with timestamps, and whether it's fixed or not". The bar answers "what is
    /// wrong now"; this answers "what has been wrong, and did it get fixed" --
    /// and before this there was no record to answer from at all.
    static func flagHistoryJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let f = o["flag_history"],
              let out = try? JSONSerialization.data(withJSONObject: f)
        else { return "[]" }
        return String(data: out, encoding: .utf8) ?? "[]"
    }

    /// The settings surface's rows (§11.6), read from the file the runtime writes.
    static func settingsJSON() -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let f = o["settings"],
              let out = try? JSONSerialization.data(withJSONObject: f)
        else { return "[]" }
        return String(data: out, encoding: .utf8) ?? "[]"
    }

    /// The rail's two Work-room cards (§11.7), from the file the runtime writes.
    static func railJSON(_ key: String) -> String {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let f = o[key],
              let out = try? JSONSerialization.data(withJSONObject: f)
        else { return "[]" }
        return String(data: out, encoding: .utf8) ?? "[]"
    }

    static func faceBehaviour() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let face = obj["face"] as? [String: Any],
              let b = face["behaviour"] as? String, !b.isEmpty
        else { return "resting" }
        return b
    }

    /// The whole conversation, as JSON, for the history bar.
    ///
    /// PUSHED AS DATA, NOT AS MARKUP. The page builds the rows and sets each
    /// line with `textContent`, so a model's output cannot become an element.
    /// Handing over pre-built HTML would put that decision in the one place
    /// least able to make it -- the layer whose whole job is to render.
    static func historyJSON() -> String {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = obj["transcript"] as? [[String: Any]]
        else { return "[]" }
        // THE TURN ID TRAVELS WITH THE ROW. Without it the history bar and the
        // explanations pane are two lists of text with no way to say that one
        // line and one explanation are halves of the same turn -- which is the
        // whole of what the owner asked for when they said the two "should be
        // connected". Empty for rows that predate the field and for the
        // owner's own lines, which have no explanation to point at.
        let rows: [[String: String]] = entries.compactMap { e in
            guard let text = e["text"] as? String, !text.isEmpty else { return nil }
            return ["who": (e["who"] as? String) ?? "owner", "text": text,
                    "id": (e["id"] as? String) ?? ""]
        }
        guard let out = try? JSONSerialization.data(withJSONObject: rows),
              let s = String(data: out, encoding: .utf8) else { return "[]" }
        return s
    }

    /// The latest line and who said it, for the stage.
    ///
    /// ONE LINE, NOT A LIST. The bottom of the home is a stage: what the owner
    /// said appears, comes apart, and the answer lands in the same place. A
    /// scrolling transcript would make this a chat window, and the thing it
    /// becomes once speech lands has nothing to scroll.
    ///
    /// Returned as (text, who) rather than as markup, because the page builds
    /// one element per character to dissolve it and cannot be handed a string
    /// that is already HTML.
    static func stageLine() -> (String, String) {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = obj["transcript"] as? [[String: Any]],
              let last = entries.last,
              let text = last["text"] as? String, !text.isEmpty
        else { return ("", "vesper") }
        return (text, (last["who"] as? String) ?? "owner")
    }

    /// The snapshot is data VESPER produced, but it is still interpolated into
    /// a page. Escaped because a value is not markup, and the day one carries a
    /// model's output is the day that stops being theoretical.
    private static func esc(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
    }

    static func page(cardWidth: Int, cardHeight: Int, left: Int, top: Int,
                     convoLeft: Int, stackTop: Int, stackHeight: Int,
                     fill: Double) -> String {
        let slots = menuSlots.enumerated().map { i, name in
            """
            <button class="slot" title="\(name) — placeholder">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="3.5" y="3.5" width="17" height="17" rx="5"/>
                <circle cx="12" cy="12" r="\(3 + i % 3)"/>
              </svg>
            </button>
            """
        }.joined()
        let t = template()
        return t.source
            .replacingOccurrences(of: "{{convoLeft}}",  with: String(convoLeft))
            .replacingOccurrences(of: "{{cardWidth}}",  with: String(cardWidth))
            .replacingOccurrences(of: "{{cardHeight}}", with: String(cardHeight))
            .replacingOccurrences(of: "{{left}}",       with: String(left))
            .replacingOccurrences(of: "{{top}}",        with: String(top))
            .replacingOccurrences(of: "{{stackTop}}",   with: String(stackTop))
            .replacingOccurrences(of: "{{stackHeight}}", with: String(stackHeight))
            .replacingOccurrences(of: "{{fill}}",       with: String(fill))
            .replacingOccurrences(of: "{{slots}}",      with: slots)
            .replacingOccurrences(of: "{{METRIC_ROWS}}", with: metricRows())
            .replacingOccurrences(of: "{{FACE}}", with: faceBehaviour())
    }

    /// Where the chrome's markup came from, and it is REPORTED rather than
    /// assumed.
    struct Template { let source: String; let origin: String }

    /// The shipped fallback. Byte-identical to the file at the time it was
    /// extracted.
    ///
    /// A MISSING TEMPLATE MUST NOT BLANK THE CHROME. This layer sits over the
    /// owner's whole Desktop; the failure mode of "file not found" cannot be a
    /// transparent webview with nothing in it, because that is indistinguishable
    /// from a working home with no cards. So the binary always carries a copy it
    /// can paint, and says when it fell back to it.
    static func fallbackTemplate() -> String {
        return """
        <!doctype html><meta charset="utf-8">
        <body data-face="{{FACE}}">
        <style>
          /* SS5's stack, in the order the specification sets it.
             Aeonik and Canela are named FIRST even though neither is licensed yet: the
             day they are bought and installed they take over with no code change, and
             until then the cascade falls through. `Outfit` is the substitute
             DESIGN-FOUNDATION itself names; Futura is what this machine actually has
             that shares Aeonik's geometric construction. -apple-system last, so there
             is always a face.

             THE EMOJI FACE IS DECLARED EXPLICITLY. Without it the cascade hands a
             colour emoji to whichever text face matched first, and a geometric
             grotesque has no glyph for one -- which is half of why they rendered as
             boxes. The other half was the dissolve splitting them; see the script. */
          :root{--ink:#f4e6dc;
                --face-body:"Aeonik","Outfit","Futura",-apple-system,system-ui,
                            "Helvetica Neue",sans-serif;
                --face-emoji:"Apple Color Emoji";
                /* A COMMAND IS NOT PROSE AND MUST NOT BE SET LIKE IT. Proportional
                   digits and a variable space turn `mv  a   b` into something the owner
                   cannot compare against what they typed, and an ellipsised
                   proportional path hides exactly the characters that distinguish two
                   similar ones. This is the single departure from SS5's stack, and it
                   is confined to the things that came off a terminal. */
                --face-mono:"Berkeley Mono","SF Mono","Menlo",ui-monospace,monospace;
                --face-hand:"Learning Curve","Bradley Hand","Noteworthy",
                            "Snell Roundhand"}
          /* TEXT IS SELECTABLE. Nothing set `user-select` at all, and a WKWebView
           chrome defaults to refusing it -- so the owner could not copy a single line
           VESPER had written, including the ones they most wanted to keep: a command,
           a path, an error. Reported 2026-09-04. The face and the ambient layers stay
           unselectable so a drag across the field does not paint a selection over it. */
        .say,.think,.acts,.history,.hrow,.htext,.cmd,.cdisp,.cout,.cerr,.ccwd,
        .btext,.bcode,.blist,.etitle,.dpath,.dhunks
          {-webkit-user-select:text;user-select:text;
          cursor:text}
        html,body{margin:0;height:100%;background:transparent;overflow:hidden;
                    font-family:var(--face-body),var(--face-emoji);
                    -webkit-font-smoothing:antialiased;
                    color:var(--ink)}

          /* ---- the metrics card (§14.2) ---------------------------------- */
          .card{position:absolute;left:{{left}}px;top:{{top}}px;
                width:{{cardWidth}}px;height:{{cardHeight}}px;box-sizing:border-box;
                padding:22px 24px;border-radius:22px;
                background-color:rgba(255,255,255,.055);
                background-image:linear-gradient(rgba(0,0,0,{{fill}}),
                                                 rgba(0,0,0,{{fill}}));
                -webkit-backdrop-filter:blur(24px) saturate(180%);
                backdrop-filter:blur(24px) saturate(180%);
                border:1px solid rgba(255,255,255,.14);
                box-shadow:0 8px 32px rgba(0,0,0,.22),
                           inset 0 1px 0 rgba(255,255,255,.22)}
          .t{font-size:10px;letter-spacing:.16em;text-transform:uppercase;
             color:rgba(244,230,220,.55);margin-bottom:16px}
          .row{display:flex;justify-content:space-between;align-items:baseline;
               padding:7px 0;border-top:1px solid rgba(255,255,255,.07)}
          .row:first-of-type{border-top:0}
          .k{font-size:12px;color:rgba(244,230,220,.72)}
          .v{font-size:12px;letter-spacing:.04em;color:rgba(244,230,220,.38)}

          /* ---- the work stack, under the host card --------------------------------

             A FLEX COLUMN, NOT FOUR ABSOLUTE OFFSETS. The panes below open and close,
             and every pane under an opened one has to move. Four hardcoded `top`s
             would be four numbers that have to be re-solved on every toggle and on
             every screen -- and the first display with a different height would put
             the last pane through the floor. The container is placed by Swift, which
             is the only layer that knows where the host card ended and where the main
             menu begins; inside it the browser does the arithmetic.

             ONE OPEN AT A TIME, ENFORCED IN THE SCRIPT rather than left to the owner.
             The column is about 250 px on this display. Two open panes would each get
             half of it and neither would be readable, so opening one closes the rest --
             which is also what makes the resting state fit on any screen: every pane
             is a bar until it is asked for. */
          .stack{position:absolute;left:{{left}}px;top:{{stackTop}}px;
                 width:{{cardWidth}}px;height:{{stackHeight}}px;
                 display:flex;flex-direction:column;gap:12px;box-sizing:border-box}
          .pane{flex:0 0 auto;box-sizing:border-box;overflow:hidden;
                display:flex;flex-direction:column;
                border-radius:22px;
                background-color:rgba(255,255,255,.055);
                background-image:linear-gradient(rgba(0,0,0,{{fill}}),
                                                 rgba(0,0,0,{{fill}}));
                -webkit-backdrop-filter:blur(24px) saturate(180%);
                backdrop-filter:blur(24px) saturate(180%);
                border:1px solid rgba(255,255,255,.14);
                box-shadow:0 8px 32px rgba(0,0,0,.22),
                           inset 0 1px 0 rgba(255,255,255,.22);
                transition:flex-grow .28s cubic-bezier(.32,.72,0,1)}
          /* EMPTY MEANS ABSENT, the same rule the workbench card follows. A pane
             holding a heading and no rows says VESPER did something and will not say
             what. */
          .pane.idle{display:none}
          .pane.open{flex:1 1 auto;min-height:0}
          /* The header is the whole collapsed pane, so the bar IS the hit target. */
          .phead{flex:0 0 auto;display:flex;align-items:center;gap:10px;
                 padding:13px 20px;cursor:default;
                 transition:background .2s ease}
          .phead:hover{background:rgba(255,255,255,.045)}
          .ptitle{font-size:10px;letter-spacing:.16em;text-transform:uppercase;
                  color:rgba(244,230,220,.55)}
          .pcount{font-size:10px;letter-spacing:.06em;
                  color:rgba(244,230,220,.32);font-variant-numeric:tabular-nums}
          .pgrow{flex:1}
          /* THE SUMMARY IS WHAT THE PANE SAYS WHILE IT IS SHUT. A bar reading only
             "COMMANDS" is a drawer; a bar reading the last command is a status line
             that happens to open. */
          .psum{max-width:58%;font-size:11px;color:rgba(244,230,220,.42);
                font-family:var(--face-mono);
                overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .pane.open .psum{opacity:0;transition:opacity .18s ease}
          .pchev{flex:0 0 auto;width:9px;height:9px;
                 border-right:1.4px solid rgba(244,230,220,.38);
                 border-bottom:1.4px solid rgba(244,230,220,.38);
                 transform:rotate(45deg) translate(-1px,-1px);
                 transition:transform .28s cubic-bezier(.32,.72,0,1)}
          .pane.open .pchev{transform:rotate(-135deg) translate(-1px,-1px)}
          /* A SHUT PANE IS EXACTLY ITS BAR, AND `overflow:hidden` DOES NOT ACHIEVE
             THAT. The first version left the body in the layout and clipped it, so the
             pane's own height still grew with its contents -- measured at 108 px for a
             single command against the 40 px a bar should be, which by the fourth pane
             would have pushed the stack through the main menu. The body is REMOVED
             from the flow while shut, so a pane holding fifty commands is the same
             height as one holding none. */
          .pbody{display:none}
          .pane.open .pbody{display:block;flex:1 1 auto;min-height:0;overflow-y:auto;
                 padding:0 20px 16px;scrollbar-width:none}
          .pbody::-webkit-scrollbar{display:none}

          /* ---- one command ---------------------------------------------------- */
          .cmd{border-top:1px solid rgba(255,255,255,.07)}
          .cmd:first-child{border-top:0}
          .chead{display:flex;align-items:baseline;gap:9px;padding:7px 0;
                 cursor:default}
          .cdot{flex:0 0 auto;width:5px;height:5px;border-radius:50%;
                background:rgba(244,230,220,.34);transform:translateY(-2px)}
          .cmd.running .cdot{background:rgba(244,230,220,.85);
                             box-shadow:0 0 8px rgba(244,230,220,.45);
                             animation:pulse 1.6s ease-in-out infinite}
          .cmd.failed .cdot{background:rgba(232,130,110,.90);
                            box-shadow:0 0 8px rgba(232,130,110,.40)}
          .cdisp{flex:1;min-width:0;font-family:var(--face-mono);font-size:11.5px;
                 line-height:1.45;color:rgba(244,230,220,.74);
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .cmd.failed .cdisp{color:rgba(240,178,166,.82)}
          .cms{flex:0 0 auto;font-size:10px;color:rgba(244,230,220,.32);
               font-variant-numeric:tabular-nums}
          /* A FAILED COMMAND SHOWS ITS REASON WITHOUT BEING OPENED. The owner spent a
             day being told "it ran and came back with error code 1" while the sentence
             that explained it sat one field away, unread. One line, always. */
          .cwhy{padding:0 0 7px 14px;font-family:var(--face-mono);font-size:10.5px;
                line-height:1.4;color:rgba(232,130,110,.72);
                overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .cbody{display:none;padding:2px 0 12px 14px}
          .cmd.open .cbody{display:block}
          .cmd.open .cwhy{display:none}
          .ccwd{font-size:10px;letter-spacing:.03em;color:rgba(244,230,220,.34);
                font-family:var(--face-mono);margin-bottom:8px;
                overflow-wrap:anywhere}
          .clab{font-size:9px;letter-spacing:.15em;text-transform:uppercase;
                color:rgba(244,230,220,.30);margin:8px 0 4px}
          .cout,.cerr{font-family:var(--face-mono);font-size:11px;line-height:1.5;
                      white-space:pre-wrap;overflow-wrap:anywhere;
                      max-height:180px;overflow:auto;scrollbar-width:none;
                      padding:8px 10px;border-radius:10px;
                      background:rgba(0,0,0,.22)}
          .cout::-webkit-scrollbar,.cerr::-webkit-scrollbar{display:none}
          .cout{color:rgba(244,230,220,.72)}
          .cerr{color:rgba(240,178,166,.80)}
          /* A CUT IS SAID OUT LOUD. Silent truncation reads as "there was no more
             output", which is a false statement the owner would act on. */
          .ccut{font-size:10px;letter-spacing:.04em;color:rgba(244,230,220,.34);
                margin-top:6px}

          /* ---- one explanation ---------------------------------------------------

             THE LONG HALF OF A REPLY, AND IT IS NEVER SPOKEN. `core/longform.py` makes
             the split; this is where the half that is shown lands. The stage keeps the
             sentence, and the two are joined by the turn's HLC rather than by both
             being the newest of their kind -- see the click handler. */
          .exp{border-top:1px solid rgba(255,255,255,.07);padding:10px 0 4px}
          .exp:first-child{border-top:0}
          /* THE LINK, MADE VISIBLE FOR A MOMENT. Clicking a line in the conversation
             lights its explanation and the other way round, because "connected" that
             the owner cannot see is a claim rather than a feature. */
          .exp.lit,.hrow.lit{background:rgba(255,255,255,.075);border-radius:10px}
          .etitle{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
                  color:rgba(244,230,220,.42);margin-bottom:8px;
                  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .btext{margin:0 0 9px;font-size:12.5px;line-height:1.55;
                 color:rgba(244,230,220,.80)}
          .blist{margin:0 0 9px;padding-left:16px;font-size:12.5px;line-height:1.55;
                 color:rgba(244,230,220,.80)}
          .blist li{margin:0 0 3px}
          .bcodewrap{position:relative;margin:0 0 10px}
          .blang{font-size:9px;letter-spacing:.15em;text-transform:uppercase;
                 color:rgba(244,230,220,.30);margin-bottom:4px}
          .bcode{font-family:var(--face-mono);font-size:11px;line-height:1.5;
                 white-space:pre-wrap;overflow-wrap:anywhere;margin:0;
                 max-height:220px;overflow:auto;scrollbar-width:none;
                 padding:9px 11px;border-radius:10px;
                 background:rgba(0,0,0,.24);color:rgba(244,230,220,.80)}
          .bcode::-webkit-scrollbar{display:none}
          /* A BLOCK KIND NOBODY RENDERS IS SAID OUT LOUD RATHER THAN DROPPED. A future
             kind silently vanishing would show the owner a partial explanation that
             looks complete. */
          .bskip{font-size:10px;letter-spacing:.04em;color:rgba(232,130,110,.60);
                 margin:0 0 8px}

          /* ---- the changed files -------------------------------------------------

             TWO SOURCES IN ONE LIST, LABELLED. VESPER writes to paths in no repository
             at all; git covers files the owner also edits. The owner asked for both,
             so both are here with a badge saying which -- and the git buttons are
             disabled on a row git has never heard of, rather than the list pretending
             everything is a repository file. */
          .ctlrow{display:flex;align-items:center;gap:6px;padding:0 0 10px;
                  flex-wrap:wrap}
          .seg{display:flex;border-radius:9px;overflow:hidden;
               border:1px solid rgba(255,255,255,.11)}
          .seg button{border:0;background:rgba(255,255,255,.03);
                      color:rgba(244,230,220,.46);
                      font-family:inherit;font-size:9px;letter-spacing:.11em;
                      text-transform:uppercase;padding:5px 9px;cursor:default;
                      transition:background .18s ease,color .18s ease}
          .seg button + button{border-left:1px solid rgba(255,255,255,.09)}
          .seg button:hover{background:rgba(255,255,255,.075)}
          .seg button.on{background:rgba(255,255,255,.14);color:rgba(244,230,220,.86)}
          .gitbtns{display:flex;gap:6px;margin-left:auto}
          .gbtn{border:1px solid rgba(255,255,255,.13);border-radius:9px;
                background:rgba(255,255,255,.04);color:rgba(244,230,220,.62);
                font-family:inherit;font-size:9px;letter-spacing:.11em;
                text-transform:uppercase;padding:5px 10px;cursor:default;
                transition:background .18s ease}
          .gbtn:hover{background:rgba(255,255,255,.10)}
          .gbtn[disabled]{opacity:.32}
          .gbtn.arm{border-color:rgba(232,178,110,.55);color:rgba(244,214,178,.92);
                    background:rgba(232,178,110,.14)}

          .chg{border-top:1px solid rgba(255,255,255,.07)}
          .chg:first-child{border-top:0}
          .dhead{display:flex;align-items:baseline;gap:8px;padding:7px 0;cursor:default}
          .dsrc{flex:0 0 auto;font-size:8px;letter-spacing:.12em;text-transform:uppercase;
                padding:2px 5px;border-radius:5px;
                border:1px solid rgba(255,255,255,.13);color:rgba(244,230,220,.40)}
          .chg[data-src="vesper"] .dsrc{border-color:rgba(232,178,110,.38);
                                        color:rgba(240,206,160,.72)}
          .dpath{flex:1;min-width:0;font-family:var(--face-mono);font-size:11.5px;
                 color:rgba(244,230,220,.74);
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
                 direction:rtl;text-align:left}
          .dstat{flex:0 0 auto;font-size:9px;letter-spacing:.1em;text-transform:uppercase;
                 color:rgba(244,230,220,.34)}
          .chg[data-status="deleted"] .dpath{color:rgba(240,178,166,.74);
                                             text-decoration:line-through}
          .dadd{flex:0 0 auto;font-size:10px;color:rgba(150,208,158,.80);
                font-variant-numeric:tabular-nums}
          .drem{flex:0 0 auto;font-size:10px;color:rgba(232,130,110,.80);
                font-variant-numeric:tabular-nums}
          .dbody{display:none;padding:2px 0 12px 8px}
          .chg.open .dbody{display:block}
          .drow{display:flex;gap:6px;margin-bottom:8px}
          .dhunks{font-family:var(--face-mono);font-size:11px;line-height:1.5;
                  white-space:pre;overflow:auto;scrollbar-width:none;margin:0;
                  max-height:240px;padding:9px 11px;border-radius:10px;
                  background:rgba(0,0,0,.24);color:rgba(244,230,220,.66)}
          .dhunks::-webkit-scrollbar{display:none}
          /* ADDITIONS AND DELETIONS COMPARED BY COLOUR AND BY THE GUTTER CHARACTER
             BOTH. Colour alone fails for anyone who cannot separate these two hues,
             and the `+`/`-` is already the first character of every line. */
          .dhunks .a{color:rgba(150,208,158,.92);background:rgba(120,190,130,.10);
                     display:block}
          .dhunks .r{color:rgba(240,150,132,.92);background:rgba(210,110,95,.10);
                     display:block}
          .dhunks .h{color:rgba(244,230,220,.34);display:block}

          /* ---- the terminal ------------------------------------------------------

             VESPER'S DESIGN, NOT A TERMINAL'S -- the owner asked for that in as many
             words. Same glass, same type stack, same palette as every card above it.
             The one departure is the mono face, because a shell's output is columnar
             and a proportional face makes `ls` unreadable.

             AND NO VENDORED EMULATOR. xterm.js brings its own look, its own theme
             system and 300 KB of it; what this pane needs is CR, LF, backspace and
             SGR colour, which is a page of code and stays in VESPER's design. What it
             therefore does NOT do is full-screen curses -- `vim` and `htop` will not
             paint correctly here, and the pane says so the first time one is run
             rather than leaving the owner to work it out from the mess. */
          .pane.term .pbody{padding:0 16px 12px}
          .tout{font-family:var(--face-mono);font-size:11.5px;line-height:1.5;
                white-space:pre-wrap;overflow-wrap:anywhere;margin:0;
                color:rgba(244,230,220,.76);
                overflow-y:auto;scrollbar-width:none;max-height:100%}
          .tout::-webkit-scrollbar{display:none}
          .tin{display:flex;align-items:center;gap:8px;padding:7px 0 2px}
          .tps{flex:0 0 auto;font-family:var(--face-mono);font-size:11.5px;
               color:rgba(232,178,110,.72)}
          .tfield{flex:1;background:transparent;border:0;outline:none;
                  font-family:var(--face-mono);font-size:11.5px;
                  color:rgba(244,230,220,.92);caret-color:rgba(232,178,110,.9)}
          /* The 16 ANSI colours, pulled toward VESPER's palette rather than taken from
             a terminal theme -- warm neutrals, the same reds and greens the diff uses. */
          .tout .c30,.tout .c90{color:rgba(244,230,220,.34)}
          .tout .c31,.tout .c91{color:rgba(240,150,132,.92)}
          .tout .c32,.tout .c92{color:rgba(150,208,158,.92)}
          .tout .c33,.tout .c93{color:rgba(232,196,130,.92)}
          .tout .c34,.tout .c94{color:rgba(150,184,224,.92)}
          .tout .c35,.tout .c95{color:rgba(206,162,220,.92)}
          .tout .c36,.tout .c96{color:rgba(150,206,206,.92)}
          .tout .c37,.tout .c97{color:rgba(244,230,220,.92)}
          .tout .bold{font-weight:600;color:rgba(244,230,220,.96)}

          /* ---- a command inside an answer ---------------------------------------
             Four things the owner can do with a command VESPER wrote, and RUN is never
             the default: no shortcut, no enter-to-run, no run-on-expand. */
          .cmdbar{display:flex;gap:6px;margin-top:6px}
          .cmdbar button{border:1px solid rgba(255,255,255,.13);border-radius:8px;
                         background:rgba(255,255,255,.04);color:rgba(244,230,220,.58);
                         font-family:inherit;font-size:9px;letter-spacing:.11em;
                         text-transform:uppercase;padding:4px 9px;cursor:default;
                         transition:background .18s ease}
          .cmdbar button:hover{background:rgba(255,255,255,.10)}
          .cmdbar button.run{border-color:rgba(232,178,110,.42);
                             color:rgba(244,214,178,.86)}

          /* ---- the main menu (§10, §14.2) -------------------------------- */
          /* Dock tier: blur 42, saturate 200%, fill .085, radius 34. The bar
             sits at the Dock's own position, bottom-centre, because §10 says
             VESPER's main menu TAKES that position rather than sharing it. */
          /* THE FLAG BAR. One destination for every flag VESPER raises, sitting
             directly above the main menu. Small in both dimensions on purpose: it is
             an indicator, not a panel, and it is HIDDEN ENTIRELY when there is nothing
             to say -- a permanent empty strip trains the eye to skip the place a flag
             will appear. */
          /* §21, THE OWNER'S OWN SPECIFICATION, 2026-09-11: "i want the width to be
             bigger, it can be very big, just not bigger than the main menu ... titles no
             icons, on hover shows the actual full flag, with our fonts, and when i click
             the bar, i can see the full history with timestamps".

             THE WIDTH CAP IS MEASURED FROM THE MENU AND NOT WRITTEN HERE. `.dockrow` is
             `left:0;right:0` and centres its content, so the main menu's real width is a
             LAYOUT FACT, not a number in a stylesheet. `--flagbar-max` is set at runtime
             from the menu's own rectangle -- reading it from where the menu reads it,
             rather than copying a figure by eye, which is the defect `MEMORY.md` opens by
             warning about. The fallback stands in only before the first measurement. */
          .flagbar{position:absolute;left:0;right:0;bottom:92px;display:flex;
                   justify-content:center;pointer-events:none;z-index:3}
          .flagbar .flags{display:flex;align-items:center;gap:7px;padding:6px 10px;
                   border-radius:13px;pointer-events:auto;cursor:pointer;
                   max-width:var(--flagbar-max,560px);
                   overflow-x:auto;scrollbar-width:none;
                   background:rgba(22,19,17,.62);border:1px solid rgba(255,255,255,.08);
                   backdrop-filter:blur(14px) saturate(1.1)}
          .flagbar .flags::-webkit-scrollbar{display:none}
          /* TITLES, NOT ICONS. A 16px square told the owner something was wrong and
             nothing about what; a title says which thing without a hover. VESPER's own
             type -- `--face-mono` is the same face the commands and changes cards use,
             so the bar reads as part of the surface rather than as a browser default. */
          .flagbar button{padding:3px 9px;border:0;border-radius:8px;flex:0 0 auto;
                   font-family:var(--face-mono);font-size:10.5px;letter-spacing:.02em;
                   max-width:220px;overflow:hidden;text-overflow:ellipsis;
                   white-space:nowrap;
                   background:rgba(185,102,69,.9);color:rgba(28,22,19,.96);
                   cursor:pointer}
          .flagbar button:hover,.flagbar button:focus-visible{background:rgba(206,120,84,1)}
          /* CARRIED, NOT CURRENT: hollow rather than filled, so the bar distinguishes
             a problem something just hit from one inherited from a dead process. */
          .flagbar button.carried{background:transparent;color:rgba(206,120,84,.95);
            box-shadow:inset 0 0 0 1.5px rgba(206,120,84,.85)}
          /* THE HISTORY PANEL. Opened by clicking the bar, which is what the owner
             asked for, and closed by clicking away or pressing Escape. */
          /* §11.6, THE OWNER'S GEOMETRY: "the card stops reading UNAVAILABLE and becomes
             the same card at full screen, with a margin between it and the display
             edges." The SAME card -- same glass, same type, same radius -- at full
             screen, not a different surface that happens to open from the same button. */
          /* §11.6's geometry, applied to the ONE panel rather than to a second card:
             the same card at full screen with a margin between it and the display. */
          .menu-panel[data-view="settings"],

          .dash-top{display:flex;flex-direction:column;gap:10px;margin-bottom:14px}
          .dash-switch{display:flex;flex-direction:column;gap:5px}
          .dash-switch-label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;opacity:.62}
          .dash-switch-row{display:flex;flex-wrap:wrap;gap:6px}
          .dash-chip{font:inherit;font-size:12px;padding:4px 11px;border-radius:999px;cursor:pointer;
                     border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.05);color:inherit}
          .dash-chip:hover{background:rgba(255,255,255,.10)}
          .dash-chip.is-on{background:rgba(255,255,255,.20);border-color:rgba(255,255,255,.38)}
          .dash-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:10px}
          .dash-panel{border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:11px 12px;
                      background:rgba(255,255,255,.035);display:flex;flex-direction:column;gap:5px}
          /* DIMMED, NOT HIDDEN: switching mode reveals what was already there. */
          .dash-panel.is-other-mode{opacity:.42}
          .dash-panel-name{margin:0;font-size:13px;font-weight:600}
          .dash-value{font-size:15px}
          .dash-panel-what{margin:0;font-size:11.5px;opacity:.74;line-height:1.42}
          .dash-source{margin:0;font-size:10.5px;opacity:.5}
          .dash-tag{font-size:10px;letter-spacing:.08em;opacity:.62}
          .menu-panel[data-view="projects"],
          .menu-panel[data-view="research"]{
            inset:28px;right:28px;bottom:28px;width:auto;max-width:none;max-height:none}
          .rail-list{display:flex;flex-direction:column;gap:0}
          .rail-row{display:grid;grid-template-columns:1fr auto;gap:12px;padding:9px 0;
            border-top:1px solid rgba(255,255,255,.06);align-items:start}
          .rail-name{font-size:11.5px;color:rgba(244,214,178,.92)}
          .rail-detail{font-size:10.5px;color:rgba(244,214,178,.48);line-height:1.4;
            margin-top:2px}
          .rail-waiting{font-size:10px;color:rgba(206,120,84,.9);margin-top:3px}
          .rail-where,.rail-value{font-size:10px;color:rgba(244,214,178,.42);
            text-align:right;white-space:nowrap}
          .rail-value{font-size:11px;color:rgba(206,180,140,.95)}
          .rail-state{display:inline-block;font-size:9.5px;letter-spacing:.06em;
            text-transform:uppercase;padding:2px 6px;border-radius:6px;white-space:nowrap;
            background:rgba(255,255,255,.08);color:rgba(244,214,178,.7)}
          .rs-done{background:rgba(120,160,120,.32);color:rgba(230,244,225,.92)}
          .rs-partial,.rs-running{background:rgba(185,102,69,.85);color:rgba(28,22,19,.96)}
          .rs-unmarked,.rs-notstarted,.rs-not_started{background:transparent;
            box-shadow:inset 0 0 0 1px rgba(244,214,178,.28)}
          .rs-unreadable{background:transparent;
            box-shadow:inset 0 0 0 1px rgba(206,120,84,.8);color:rgba(206,120,84,.95)}
          .settings{position:fixed;inset:28px;z-index:8;overflow-y:auto;
                   border-radius:18px;padding:20px 22px;
                   background:rgba(18,15,13,.94);border:1px solid rgba(255,255,255,.10);
                   backdrop-filter:blur(20px) saturate(1.1);
                   font-family:var(--face-mono);font-size:11.5px;
                   color:rgba(244,214,178,.88)}
          .settings[hidden]{display:none!important}
          .settings h3{margin:0 0 4px;font-size:12px;letter-spacing:.10em;
                   text-transform:uppercase;color:rgba(244,214,178,.62)}
          .settings .st-sub{margin:0 0 14px;color:rgba(244,214,178,.45);font-size:10.5px}
          .st-row{display:grid;grid-template-columns:1fr auto;gap:10px;
                   padding:9px 0;border-top:1px solid rgba(255,255,255,.06)}
          .st-name{font-size:11.5px;color:rgba(244,214,178,.92)}
          /* "EXPLAIN THIS SETTING" IS A PROPERTY OF EVERY ITEM, not a thirty-fifth peer
             -- the owner's routing export marks it "in each dialog, on hover", and §11.6
             says so explicitly. So it is the row's own hover text rather than a row. */
          .st-what{font-size:10.5px;color:rgba(244,214,178,.50);line-height:1.4;
                   max-height:0;overflow:hidden;transition:max-height .18s ease}
          .st-row:hover .st-what,.st-row:focus-within .st-what{max-height:120px}
          .st-value{text-align:right;font-size:11px;white-space:nowrap;
                   color:rgba(206,180,140,.95)}
          .st-row[data-available="false"] .st-value{color:rgba(206,120,84,.9)}
          .st-source{font-size:9.5px;color:rgba(244,214,178,.38);text-align:right}
          .st-gov{font-size:9px;letter-spacing:.06em;text-transform:uppercase;
                   color:rgba(244,214,178,.35)}
          .flaghist{position:absolute;left:50%;transform:translateX(-50%);
                   bottom:124px;width:min(var(--flagbar-max,560px),92vw);
                   max-height:46vh;overflow-y:auto;z-index:6;pointer-events:auto;
                   border-radius:14px;padding:10px 12px;
                   background:rgba(18,15,13,.92);border:1px solid rgba(255,255,255,.10);
                   backdrop-filter:blur(18px) saturate(1.1);
                   font-family:var(--face-mono);font-size:11px;
                   color:rgba(244,214,178,.86)}
          .flaghist[hidden]{display:none!important}
          .flaghist h4{margin:0 0 8px;font-size:10.5px;letter-spacing:.10em;
                   text-transform:uppercase;color:rgba(244,214,178,.55)}
          .fh-row{display:grid;grid-template-columns:64px 1fr auto;gap:8px;
                   align-items:start;padding:6px 0;
                   border-top:1px solid rgba(255,255,255,.06)}
          .fh-when{color:rgba(244,214,178,.45);font-size:10px;white-space:nowrap}
          .fh-what{min-width:0;word-break:break-word;line-height:1.35}
          .fh-state{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;
                   padding:2px 6px;border-radius:6px;white-space:nowrap}
          .fh-open{background:rgba(185,102,69,.85);color:rgba(28,22,19,.96)}
          .fh-resolved{background:rgba(120,160,120,.35);color:rgba(230,244,225,.9)}
          .fh-carried,.fh-unproven{background:transparent;
                   box-shadow:inset 0 0 0 1px rgba(206,120,84,.7);
                   color:rgba(206,120,84,.95)}
          .fh-fix{margin-top:5px;padding:3px 8px;border:0;border-radius:7px;
                   font-family:var(--face-mono);font-size:10px;cursor:pointer;
                   background:rgba(255,255,255,.10);color:rgba(244,214,178,.85)}
          .fh-fix:hover{background:rgba(255,255,255,.16)}
          .flag-tip{position:absolute;bottom:calc(100% + 8px);left:50%;
                   transform:translateX(-50%);max-width:min(46ch,80vw);
                   padding:8px 11px;border-radius:10px;font-size:12px;line-height:1.45;
                   background:rgba(28,24,22,.96);color:rgba(244,240,236,.94);
                   border:1px solid rgba(255,255,255,.10);pointer-events:none;
                   white-space:normal;text-align:left}
          .flag-tip[hidden]{display:none!important}
          .dockrow{position:absolute;left:0;right:0;bottom:10px;
                   display:flex;justify-content:center;align-items:flex-end;
                   gap:14px;
                   transition:opacity .28s cubic-bezier(.32,.72,0,1)}
          /* §10: "It dims to 30% while occluded so it is visibly still there
             rather than apparently gone." Driven from Swift, which reads the
             Dock's own window rather than guessing from the cursor. */
          body.dock-up .dockrow{opacity:.30}
          .bar,.tile{box-sizing:border-box;
                     background-color:rgba(255,255,255,.085);
                     background-image:linear-gradient(rgba(0,0,0,.34),
                                                      rgba(0,0,0,.34));
                     -webkit-backdrop-filter:blur(42px) saturate(200%);
                     backdrop-filter:blur(42px) saturate(200%);
                     border:1px solid rgba(255,255,255,.13);
                     border-radius:34px;
                     box-shadow:0 10px 34px rgba(0,0,0,.30),
                                inset 0 1px 0 rgba(255,255,255,.20)}
          .bar{display:flex;align-items:center;gap:10px;padding:9px 12px}
          .tile{display:flex;align-items:center;justify-content:center;
                width:64px;height:64px;padding:0}
          .slot{width:52px;height:52px;padding:0;border:0;border-radius:15px;
                background:rgba(255,255,255,.05);
                display:flex;align-items:center;justify-content:center;
                cursor:default;
                transition:transform .22s cubic-bezier(.32,.72,0,1),
                           background .22s ease}
          .slot:hover{transform:translateY(-6px) scale(1.06);
                      background:rgba(255,255,255,.11)}
          .slot svg{width:26px;height:26px;fill:none;
                    stroke:rgba(244,230,220,.62);stroke-width:1.4}
          /* The owner's avatar (§14.2), separated from the actions the way the
             system Dock separates its trash. */
          .sep{width:1px;height:34px;background:rgba(255,255,255,.13);margin:0 4px}
          .avatar{width:52px;height:52px;border-radius:50%;
                  background:linear-gradient(160deg,rgba(255,255,255,.20),
                                                    rgba(255,255,255,.05));
                  border:1px solid rgba(255,255,255,.18);
                  display:flex;align-items:center;justify-content:center;
                  font-size:15px;letter-spacing:.06em;
                  color:rgba(244,230,220,.78)}
          .tile svg{width:24px;height:24px;fill:none;
                    stroke:rgba(244,230,220,.62);stroke-width:1.5}
          /* Every glyph in this bar is a placeholder and says so on hover.
             The dotted underline is the tell. */
          .slot,.tile{position:relative}

          /* ==== MENU: codex owns everything between these markers ==== */
          /* These overrides live here because the surrounding chrome has another owner. */
          .dockrow{z-index:20}
          .dockrow .tile{cursor:pointer;color:var(--ink)}
          .dockrow .tile:hover{background-color:rgba(255,255,255,.14)}
          .dockrow button:focus-visible,.menu-rail button:focus-visible,
          .menu-panel button:focus-visible,.menu-panel input:focus-visible,
          .menu-panel summary:focus-visible{outline:2px solid var(--ink);outline-offset:4px}
          .menu-rail{position:fixed;right:18px;top:50%;transform:translateY(-50%);
            display:flex;flex-direction:column;gap:18px;z-index:21}
          .menu-rail button{display:flex;justify-content:flex-end;align-items:center;gap:12px;
            padding:0;border:0;background:none;color:rgba(244,230,220,.62);
            font:12px var(--face-body);cursor:pointer}
          .menu-rail .menu-orb{display:grid;place-items:center;width:42px;height:42px;
            border:1px solid rgba(255,255,255,.16);border-radius:50%;
            background-color:rgba(255,255,255,.055);
            background-image:linear-gradient(rgba(0,0,0,{{fill}}),rgba(0,0,0,{{fill}}));
            -webkit-backdrop-filter:blur(24px) saturate(180%);
            backdrop-filter:blur(24px) saturate(180%);
            box-shadow:0 5px 20px rgba(0,0,0,.20),inset 0 1px 0 rgba(255,255,255,.20);
            transition:transform .24s cubic-bezier(.32,.72,0,1),background .24s ease}
          .menu-rail button:hover{color:var(--ink)}
          .menu-rail button:hover .menu-orb{transform:scale(1.06);background-color:rgba(255,255,255,.11)}
          .menu-orb svg{width:18px;height:18px;fill:none;stroke:currentColor;
            stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}
          .menu-panel{position:fixed;inset:auto 92px 100px auto;margin:0;
            width:min(420px,calc(100vw - 48px));max-height:calc(100vh - 136px);
            padding:0;box-sizing:border-box;border-radius:22px;
            border:1px solid rgba(255,255,255,.18);color:var(--ink);
            background-color:rgba(255,255,255,.055);
            background-image:linear-gradient(rgba(0,0,0,{{fill}}),rgba(0,0,0,{{fill}}));
            font:13px/1.55 var(--face-body);
            -webkit-backdrop-filter:blur(24px) saturate(180%);
            backdrop-filter:blur(24px) saturate(180%);
            box-shadow:0 20px 70px rgba(0,0,0,.42),inset 0 1px 0 rgba(255,255,255,.20);
            overflow:auto;-webkit-user-select:text;user-select:text}
          .menu-panel[data-view="instruments"]{right:max(24px,calc(50% - 320px))}
          .menu-panel::backdrop{background:rgba(0,0,0,.50);
            -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
          .menu-panel[open]{animation:menu-arrive .24s cubic-bezier(.32,.72,0,1)}
          @keyframes menu-arrive{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
          .menu-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;
            padding:20px 22px 10px}
          .menu-heading h2{margin:0;font:500 20px/1.3 var(--face-body);letter-spacing:-.03em}
          .menu-close{border:1px solid rgba(255,255,255,.13);border-radius:50%;width:30px;height:30px;
            background:rgba(255,255,255,.055);color:var(--ink);font:20px var(--face-body);cursor:pointer;flex:none}
          .menu-intro{margin:0;padding:0 22px 18px;color:rgba(244,230,220,.62);font-size:12px}
          .menu-content{padding:0 22px 22px}
          .menu-reading{padding:13px 0;border-top:1px solid rgba(255,255,255,.09)}
          .menu-reading summary{display:flex;align-items:baseline;justify-content:space-between;
            gap:12px;cursor:pointer;list-style:none}
          .menu-reading summary::-webkit-details-marker{display:none}
          .menu-reading summary::after{content:'+';color:rgba(244,230,220,.34)}
          .menu-reading[open] summary::after{content:'−'}
          .menu-reading-name{flex:1}
          .menu-reading-value{font-size:11px;color:rgba(244,230,220,.62)}
          .menu-reading[data-available="true"] .menu-reading-value{color:var(--ink);font-size:15px}
          .menu-reading p,.menu-note{color:rgba(244,230,220,.62);font-size:12px;margin:8px 0 0}
          .menu-reading[data-available="false"] .menu-reading-value{font-size:9px;letter-spacing:.09em}
          .menu-search{width:100%;box-sizing:border-box;border:1px solid rgba(255,255,255,.18);
            border-radius:10px;background:rgba(255,255,255,.045);color:var(--ink);
            padding:10px 12px;font:12px var(--face-body);margin:0 0 12px}
          .menu-history-list{margin:0;padding:0;list-style:none}
          .menu-history-list li{border-top:1px solid rgba(255,255,255,.09);padding:14px 0}
          .menu-history-list strong{font-size:10px;font-weight:400;letter-spacing:.12em;text-transform:uppercase;
            color:rgba(244,230,220,.62)}
          .menu-history-list p{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
          .menu-status{display:block;font-size:10px;letter-spacing:.10em;color:rgba(244,230,220,.62)}
          .menu-empty-title{font-size:18px;margin:10px 0}
          @media(max-width:760px){
            .dockrow{gap:8px;bottom:10px}.dockrow .bar{gap:4px;padding:7px}
            .dockrow .slot{width:34px;height:40px}.dockrow .slot svg{width:21px;height:21px}
            .dockrow .avatar{width:36px;height:36px}.dockrow .sep{margin:0 2px}
            .dockrow .tile{width:48px;height:56px}.menu-rail{right:12px;gap:12px}
            .menu-rail button{gap:7px;font-size:10px}.menu-rail .menu-orb{width:36px;height:36px}
            .menu-panel,.menu-panel[data-view="instruments"]{right:24px;bottom:84px;max-height:calc(100vh - 108px)}
          }
          @media(prefers-reduced-motion:reduce){
            .menu-panel[open]{animation:none}.menu-rail .menu-orb,.dockrow,.dockrow .slot{transition:none}
            .menu-rail button:hover .menu-orb,.dockrow .slot:hover{transform:none}
          }
          @media(prefers-reduced-transparency:reduce){
            .menu-panel::backdrop{-webkit-backdrop-filter:none;backdrop-filter:none}
            .menu-panel,.menu-rail .menu-orb,.dockrow .bar,.dockrow .tile{background:#242225;
              -webkit-backdrop-filter:none;backdrop-filter:none}
          }

          /* All 17 were approved 2026-09-07. Keep legible targets; overflow is
             navigation on narrow surfaces, never an invisible seventeenth action. */
          .dockrow{padding:0 12px;box-sizing:border-box}
          .dockrow .bar{min-width:0;max-width:calc(100vw - 102px);overflow-x:auto;
            scrollbar-width:thin;padding:15px 12px 9px;gap:10px}
          .dockrow .slot{flex:0 0 52px;width:52px;height:52px;cursor:pointer}
          .dockrow .slot svg{width:26px;height:26px;stroke:var(--ink)}
          .dockrow .avatar{flex:0 0 52px;width:52px;height:52px;box-sizing:border-box}
          .dockrow .sep{flex:0 0 1px}
          .dockrow .tile{flex:0 0 64px;width:64px;height:64px}
          .menu-tooltip{position:fixed;z-index:30;width:280px;max-width:calc(100vw - 24px);
            padding:14px 16px;box-sizing:border-box;border:1px solid rgba(244,230,220,.25);
            border-radius:16px;background:#292529;color:var(--ink);font:13px/1.5 var(--face-body);
            box-shadow:0 8px 35px #0007;pointer-events:none}
          .menu-tooltip[hidden]{display:none}.menu-tooltip strong{display:block;margin-bottom:5px}
          .menu-panel,.menu-panel[data-view="instruments"]{right:24px;bottom:110px;
            width:min(640px,calc(100vw - 48px));max-height:calc(100vh - 145px)}
          .menu-reading-value{max-width:48%;text-align:right;overflow-wrap:anywhere}
          .menu-data{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;
            font:11px/1.6 var(--face-mono);background:rgba(0,0,0,.12);padding:12px;border-radius:12px}
          .menu-action{padding:9px 12px;margin:8px 8px 8px 0;border:1px solid rgba(244,230,220,.25);
            border-radius:12px;background:rgba(255,255,255,.085);color:var(--ink);font:inherit;cursor:pointer}
          .menu-action:disabled{opacity:.4;cursor:default}.menu-palette{display:flex;flex-direction:column}
          .menu-palette .menu-action{text-align:left}.menu-tools{margin-bottom:14px}
          .menu-caption{display:block;margin:10px 0;color:rgba(244,230,220,.65);font-size:12px}
          .menu-heading h2{flex:1}
          .menu-back{flex:none;border:1px solid rgba(244,230,220,.18);border-radius:50%;
            width:32px;height:32px;background:rgba(255,255,255,.055);color:var(--ink);cursor:pointer;font:18px var(--face-body)}
          .menu-back[hidden],.menu-reading[hidden],.menu-group[hidden]{display:none}
          .menu-filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
          .menu-filter-label{flex:1;min-width:160px;font-size:11px;color:rgba(244,230,220,.70)}
          .menu-filter-label select{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:9px 10px;
            border:1px solid rgba(244,230,220,.18);border-radius:10px;background:#292529;color:var(--ink);font:12px var(--face-body)}
          .menu-panel select:focus-visible{outline:2px solid var(--ink);outline-offset:3px}
          .menu-group{margin-top:20px}.menu-group h3{margin:0 0 7px;font:500 13px var(--face-body);color:var(--ink)}
          .menu-group-count{font-weight:400;font-size:11px;color:rgba(244,230,220,.62);margin-left:8px}
          .menu-results{font-size:12px;color:rgba(244,230,220,.70);margin:12px 0}
          .menu-evidence summary{font-size:11px;color:rgba(244,230,220,.70);cursor:pointer;margin:10px 0}
          .menu-reading .menu-evidence summary{display:list-item;list-style:disclosure-closed}
          .menu-reading .menu-evidence[open] summary{list-style:disclosure-open}
          .menu-reading .menu-evidence summary::after{content:none}
          .menu-evidence[hidden]{display:none}
          @media(max-width:480px){.menu-heading{padding:16px 16px 10px}.menu-content{padding:0 16px 16px}
            .menu-intro{padding:0 16px 14px}.menu-reading summary{flex-wrap:wrap}.menu-reading-value{max-width:100%}}
          /* ==== /MENU ==== */

          /* ---- the field, top right (SS14.2) --------------------------------
             Moved off the bottom because the bottom is now the STAGE. Two surfaces
             competing for the same edge is how a composition stops reading, and the
             one that has to be looked at while typing is not the one that should sit
             under the face. */
          .field{position:absolute;top:38px;right:28px;width:360px;
                 box-sizing:border-box;display:flex;align-items:center;gap:12px;
                 padding:13px 18px;border-radius:18px;z-index:6;
                 background-color:rgba(255,255,255,.055);
                 background-image:linear-gradient(rgba(0,0,0,0.42),rgba(0,0,0,0.42));
                 -webkit-backdrop-filter:blur(24px) saturate(180%);
                 backdrop-filter:blur(24px) saturate(180%);
                 border:1px solid rgba(255,255,255,.18);
                 box-shadow:0 8px 32px rgba(0,0,0,.22),
                            inset 0 1px 0 rgba(255,255,255,.22);
                 transition:border-color .3s ease, box-shadow .3s ease}
          .field:focus-within{border-color:rgba(255,255,255,.34);
                 box-shadow:0 10px 38px rgba(0,0,0,.28),
                            inset 0 1px 0 rgba(255,255,255,.30)}
          .field input{flex:1;background:transparent;border:0;outline:0;
                       font-family:inherit;font-size:13.5px;color:#f4e6dc;
                       letter-spacing:.01em}
          .field input::placeholder{color:rgba(244,230,220,.32)}

          /* The state dot: VESPER's activity, read from the same key the face is
             driven from, so it cannot disagree with the expression above it. */
          .dot{width:8px;height:8px;border-radius:50%;flex:0 0 auto;
               background:rgba(244,230,220,.34);
               transition:background .4s ease, box-shadow .4s ease}
          body[data-face="thinking"] .dot,
          body[data-face="working"]  .dot{background:rgba(244,230,220,.88);
               box-shadow:0 0 10px rgba(244,230,220,.45);
               animation:pulse 1.6s ease-in-out infinite}
          body[data-face="talking"]  .dot{background:rgba(180,220,255,.92);
               box-shadow:0 0 12px rgba(180,220,255,.50);
               animation:pulse 1.1s ease-in-out infinite}
          body[data-face="listening"] .dot{background:rgba(180,255,210,.90);
               box-shadow:0 0 12px rgba(180,255,210,.45);
               animation:pulse 2.2s ease-in-out infinite}
          body[data-face="wondering"] .dot{background:rgba(244,190,150,.90);
               box-shadow:0 0 12px rgba(244,190,150,.45)}
          @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}


          /* ---- the workbench, top left -----------------------------------------
             TWO COLUMNS OF DIFFERENT KINDS OF CLAIM, and the type is what keeps them
             apart. Thoughts are VESPER in the first person, in the HAND (SS5). Actions
             are the instrument -- a provider, an outcome, a duration -- in the body
             face, because SS5 forbids the hand to carry a number and the owner needs
             the number.

             SS5 NAMES LEARNING CURVE AND IT IS NOT INSTALLED HERE. It is free and
             installable today, so it is named FIRST and takes over the moment it
             arrives; Bradley Hand is what this machine actually has that shares its
             character -- informal, single-stroke, unjoined. Snell Roundhand is behind
             it as formal copperplate rather than as an equal.

             ABOVE THE HOST CARD IN THE SAME COLUMN, sharing its `left` so the two read
             as one cluster rather than two decisions. */
          /* THE CARD IS BOUNDED BY THE HOST CARD BELOW IT, not by a guess. `{{top}}`
             is where the metrics card starts, computed in Swift off the face, so this
             can grow to fill the gap and never into it. */
          .work{position:absolute;left:{{left}}px;top:38px;width:{{cardWidth}}px;
                max-height:calc({{top}}px - 58px);
                display:flex;flex-direction:column;
                box-sizing:border-box;padding:18px 20px 14px;border-radius:22px;
                background-color:rgba(255,255,255,.055);
                background-image:linear-gradient(rgba(0,0,0,{{fill}}),
                                                 rgba(0,0,0,{{fill}}));
                -webkit-backdrop-filter:blur(24px) saturate(180%);
                backdrop-filter:blur(24px) saturate(180%);
                border:1px solid rgba(255,255,255,.14);
                box-shadow:0 8px 32px rgba(0,0,0,.22),
                           inset 0 1px 0 rgba(255,255,255,.22);
                transition:opacity .5s cubic-bezier(.32,.72,0,1)}
          /* EMPTY MEANS ABSENT, not an empty box. A card holding a heading and nothing
             else says VESPER is doing something and declining to say what. */
          .work.idle{opacity:0;pointer-events:none}
          /* NEWEST FIRST AND BRIGHTEST. It rendered the other way round: thoughts were
             appended chronologically and `nth-child(2)` was the dimmed rule, so the
             NEW thought was the faded one under a stale bright one. */
          .think{font-family:var(--face-hand),cursive;
                 font-size:19px;line-height:1.34;letter-spacing:.005em;
                 color:rgba(244,230,220,.82);min-height:26px;
                 margin:0 0 14px;
                 transition:opacity .45s ease}
          /* NO CLIPPING AND NO SHRINKING, DELIBERATELY, AND THIS IS THE WHOLE POINT.
             Clipping is what "packed and hidden" looks like. The line budget is spent
             by REMOVING older thoughts in the script, so whatever survives is whole --
             and `flex:0 0 auto` means the newest thought is never the thing that gives
             way when the card runs short. The ACTIONS give way instead: they are a log
             and a log can scroll, whereas a half-shown thought is just wrong. */
          /* SCROLLABLE, ADDED 2026-09-04 AT THE OWNER'S REQUEST. The budget above
             keeps the NEWEST thought whole, which is right; what it also did was make
             older ones unreachable -- they were dropped before the renderer saw them,
             so there was nothing to scroll back to. The budget now governs how much is
             VISIBLE at rest, and the rest is reachable by scrolling rather than gone. */
          .think{flex:0 0 auto;max-height:min(30vh,220px);overflow-y:auto;
                 scrollbar-width:none}
          .think::-webkit-scrollbar{display:none}
          .think p{margin:0 0 2px}
          .think p + p{color:rgba(244,230,220,.46);font-size:17px}
          .think p + p + p{color:rgba(244,230,220,.30)}
          /* Past the fold: present and reachable by scrolling, visibly older. */
          .think p.folded{color:rgba(244,230,220,.26);font-size:16px}
          .acts{border-top:1px solid rgba(255,255,255,.09);padding-top:10px;
                flex:1 1 auto;min-height:0;overflow-y:auto;
                scrollbar-width:none}
          .acts::-webkit-scrollbar{display:none}
          .act{display:flex;align-items:baseline;gap:9px;padding:4px 0;
               font-size:11.5px;line-height:1.4}
          .adot{flex:0 0 auto;width:5px;height:5px;border-radius:50%;
                background:rgba(244,230,220,.30);transform:translateY(-2px)}
          .act.live .adot{background:rgba(244,230,220,.85);
                          box-shadow:0 0 8px rgba(244,230,220,.45);
                          animation:pulse 1.6s ease-in-out infinite}
          .act.failed .adot{background:rgba(232,130,110,.90);
                            box-shadow:0 0 8px rgba(232,130,110,.40)}
          .averb{flex:0 0 auto;min-width:52px;font-size:9px;letter-spacing:.15em;
                 text-transform:uppercase;color:rgba(244,230,220,.34)}
          .adet{flex:1;color:rgba(244,230,220,.66);
                overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .asec{flex:0 0 auto;font-size:10px;letter-spacing:.03em;
                color:rgba(244,230,220,.34);font-variant-numeric:tabular-nums}
          /* THE MACHINERY'S OWN NAME AND THE CLOCK, on a second line so the sentence
             above stays a sentence. The owner asked for "more details" here; putting
             them on the same row at eleven pixels makes the row unreadable, which is
             less detail rather than more. */
          .ameta{display:flex;gap:8px;padding:0 0 3px 14px;font-size:9px;
                 letter-spacing:.09em;color:rgba(244,230,220,.26)}
          .ameta .at{margin-left:auto;font-variant-numeric:tabular-nums}

          /* ---- the conversation, bottom right ---------------------------------
             A CARD, not a bare line on the ground. The line read as a caption over the
             wallpaper; at this length it needs a ground of its own to stay legible,
             and SS4 names Sheet for cards.

             BOTTOM RIGHT AND ABOVE THE DOCK ROW rather than beside it. The main menu
             is centred and grows with its contents, so anything sharing its band gets
             pushed into it the moment a slot is added. Sitting above it is stable
             under a menu of any width.

             AND ANCHORED TO THE FACE, NOT TO THE VIEWPORT. `right: 26px` with a
             `min(38vw, 520px)` width put this cluster over the face card on the
             owner's display: a viewport-derived width cannot avoid an element it
             cannot see, so the two were only ever coincidentally clear of each other.
             `{{convoLeft}}` is `faceRect.maxX + 40` computed in Swift, which is how
             the HOST card on the left has always been placed. `max-width` with
             `margin-left:auto` then keeps it from sprawling on a wide screen while
             still starting no further left than the face allows. */
          .convo{position:absolute;left:{{convoLeft}}px;right:26px;bottom:104px;
                 max-width:420px;margin-left:auto;
                 display:flex;flex-direction:column;gap:10px;z-index:7}

          /* The history bar: the OLDEST line, one row, until it is asked to open. */
          .history{box-sizing:border-box;border-radius:16px;overflow:hidden;
                   background-color:rgba(255,255,255,.045);
                   background-image:linear-gradient(rgba(0,0,0,0.40),rgba(0,0,0,0.40));
                   -webkit-backdrop-filter:blur(22px) saturate(175%);
                   backdrop-filter:blur(22px) saturate(175%);
                   border:1px solid rgba(255,255,255,.11);cursor:default;
                   max-height:44px;
                   transition:max-height .46s cubic-bezier(.32,.72,0,1),
                              border-color .3s ease, background-color .3s ease}
          .history:hover{border-color:rgba(255,255,255,.20);
                         background-color:rgba(255,255,255,.065)}
          .history.open{max-height:min(46vh,420px);overflow-y:auto}
          .hrow{display:flex;gap:10px;align-items:baseline;padding:11px 16px;
                font-size:12.5px;line-height:1.45;
                border-top:1px solid rgba(255,255,255,.055)}
          .hrow:first-child{border-top:0}
          .history:not(.open) .hrow:not(:first-child){display:none}
          .hwho{flex:0 0 auto;min-width:46px;font-size:9px;letter-spacing:.15em;
                text-transform:uppercase;color:rgba(244,230,220,.30)}
          .htext{flex:1;color:rgba(244,230,220,.66);
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
          .history.open .htext{white-space:normal;overflow:visible}
          .hcue{flex:0 0 auto;font-size:9px;letter-spacing:.13em;text-transform:uppercase;
                color:rgba(244,230,220,.26);transition:opacity .3s ease}

          /* The card: the current exchange, and the only thing that animates. */
          .stage{box-sizing:border-box;padding:18px 20px;border-radius:20px;
                 min-height:66px;display:flex;align-items:flex-end;
                 background-color:rgba(255,255,255,.055);
                 background-image:linear-gradient(rgba(0,0,0,0.44),rgba(0,0,0,0.44));
                 -webkit-backdrop-filter:blur(24px) saturate(180%);
                 backdrop-filter:blur(24px) saturate(180%);
                 border:1px solid rgba(255,255,255,.15);
                 box-shadow:0 10px 36px rgba(0,0,0,.26),
                            inset 0 1px 0 rgba(255,255,255,.22)}
          .say{font-size:14px;line-height:1.55;letter-spacing:.004em;
               color:rgba(244,230,220,.94);max-height:132px;overflow:hidden}
          .say.vesper{color:rgba(230,240,255,.92)}
          .say b{display:inline-block;font-weight:inherit;white-space:pre-wrap;
                 will-change:transform,opacity,filter}
          .say.in b{animation:arrive .40s cubic-bezier(.22,.9,.24,1) both}
          .say.out b{animation:scatter .74s cubic-bezier(.4,0,.7,.2) both}
          @keyframes arrive{
            from{opacity:0;filter:blur(6px);transform:translateY(8px) scale(.98)}
            to  {opacity:1;filter:blur(0);transform:none}}
          /* THE DISSOLVE. Every glyph takes its own direction from a per-character
             custom property, so the line comes apart rather than sliding away as a
             block -- the same idea as the face's dispersal tier, where each point
             drifts to its own resting place instead of translating together. */
          @keyframes scatter{
            0%  {opacity:1;filter:blur(0);transform:none}
            100%{opacity:0;filter:blur(8px);
                 transform:translate(var(--dx),var(--dy)) rotate(var(--rot)) scale(.74)}}

        </style>

        <div class="work idle" id="work">
          <div class="think" id="think"></div>
          <div class="acts" id="acts"></div>
        </div>
        <div class="card">
          <div class="t">host</div>
          <div id="metrics">{{METRIC_ROWS}}</div>
        </div>

        <!-- The work stack. Every pane is a bar until it is opened, and the rows are
             built by the script from data pushed out of home.json -- never as markup,
             because these carry a command line and a process's own stderr. -->
        <div class="stack" id="stack">
          <div class="pane idle" id="pcmds">
            <div class="phead" data-pane="pcmds">
              <span class="ptitle">commands</span>
              <span class="pcount" id="cmdcount"></span>
              <span class="pgrow"></span>
              <span class="psum" id="cmdsum"></span>
              <span class="pchev"></span>
            </div>
            <div class="pbody" id="cmdrows"></div>
          </div>
          <div class="pane idle" id="pexps">
            <div class="phead" data-pane="pexps">
              <span class="ptitle">explanations</span>
              <span class="pcount" id="expcount"></span>
              <span class="pgrow"></span>
              <span class="psum" id="expsum"></span>
              <span class="pchev"></span>
            </div>
            <div class="pbody" id="exprows"></div>
          </div>
          <div class="pane idle" id="pchgs">
            <div class="phead" data-pane="pchgs">
              <span class="ptitle">changes</span>
              <span class="pcount" id="chgcount"></span>
              <span class="pgrow"></span>
              <span class="psum" id="chgsum"></span>
              <span class="pchev"></span>
            </div>
            <div class="pbody" id="chgbody">
              <div class="ctlrow">
                <div class="seg" id="chgshow">
                  <button data-show="all" class="on">all</button>
                  <button data-show="vesper">vesper</button>
                  <button data-show="git">git</button>
                </div>
                <div class="seg" id="chgsort">
                  <button data-sort="recent" class="on">recent</button>
                  <button data-sort="path">path</button>
                  <button data-sort="size">most changed</button>
                </div>
                <div class="gitbtns">
                  <button class="gbtn" data-git="pull">pull</button>
                  <button class="gbtn" data-git="push">push</button>
                  <button class="gbtn" data-git="commit">create</button>
                </div>
              </div>
              <div id="chgrows"></div>
            </div>
          </div>
          <!-- The owner's shell. Nothing VESPER produces reaches it; see
               TerminalBridge.swift for why that is structural rather than careful. -->
          <div class="pane term" id="pterm">
            <div class="phead" data-pane="pterm">
              <span class="ptitle">terminal</span>
              <span class="pgrow"></span>
              <span class="psum" id="termsum">your shell</span>
              <span class="pchev"></span>
            </div>
            <div class="pbody">
              <pre class="tout" id="tout"></pre>
              <div class="tin">
                <span class="tps">›</span>
                <input class="tfield" id="tin" type="text" autocomplete="off"
                       spellcheck="false" placeholder="run something">
              </div>
            </div>
          </div>
        </div>


        <div class="field">
          <span class="dot" title="what VESPER is doing"></span>
          <input id="say" type="text" autocomplete="off" spellcheck="false"
                 placeholder="say something to VESPER">
        </div>


        <div class="convo">
          <div class="history" id="history">
            <div class="rows" id="hrows"></div>
          </div>
          <div class="stage"><div class="say" id="stage"></div></div>
        </div>

        <!-- THE FLAG BAR sits above the menu and is deliberately OUTSIDE the codex
             markers below, so the two can be edited without colliding. -->
        <div class="settings" id="settings" role="dialog" aria-label="Settings" hidden></div>
        <div class="flaghist" id="flaghist" role="dialog" aria-label="Flag history" hidden></div>
        <div class="flagbar" id="flagbar" hidden>
          <div class="flags" id="flags" role="group" aria-label="Flags vesper is raising">
            <div class="flag-tip" id="flag-tip" role="tooltip" hidden></div>
          </div>
        </div>
        <!-- ==== MENU: codex owns everything between these markers ==== -->
        <div class="dockrow">
          <div class="bar" role="group" aria-label="Main menu — seventeen approved destinations">
            <template id="legacy-menu-slots">{{slots}}</template>
            <button class="slot" type="button" data-menu-view="action-outbox" aria-label="Action outbox" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 14v6h16v-6M4 14h5l2 3h2l2-3h5M12 13V3m-4 4 4-4 4 4"/></svg></button>
            <button class="slot" type="button" data-menu-view="autonomy-queue" aria-label="Autonomy queue" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h10M4 11h7M4 17h7m5-7 5 4-5 4z"/><circle cx="19" cy="5" r="1"/></svg></button>
            <button class="slot" type="button" data-menu-view="emergency-stop" aria-label="Emergency stop" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 3-5 5v8l5 5h8l5-5V8l-5-5z"/><rect x="9" y="9" width="6" height="6" rx=".5"/></svg></button>
            <button class="slot" type="button" data-menu-view="grants" aria-label="Grants" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/></svg></button>
            <button class="slot" type="button" data-menu-view="verification-state" aria-label="Verification state" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7M8 3l1 2M3 8l2 1M16 21l-1-2"/></svg></button>
            <button class="slot" type="button" data-menu-view="follow-me" aria-label="Follow-me" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="7" height="10" rx="2"/><rect x="15" y="10" width="6" height="10" rx="2"/><path d="M13 5h6l-2-2m2 2-2 2M11 19H5l2-2m-2 2 2 2"/></svg></button>
            <button class="slot" type="button" data-menu-view="grant-templates" aria-label="Grant templates" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h11l3 3v13H7zM7 7H3v14h14v-2M17 3v5h4M11 12h6M11 15h4"/></svg></button>
            <button class="slot" type="button" data-menu-view="hardware-access" aria-label="Hardware access" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8h4l2-3h6l2 3h4v12H3z"/><circle cx="12" cy="13" r="3"/><circle cx="19" cy="5" r="1"/></svg></button>
            <button class="slot" type="button" data-menu-view="import-export" aria-label="Import / export" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3v13m-4-4 4 4 4-4M16 21V8m-4 4 4-4 4 4M3 21h7M14 3h7"/></svg></button>
            <button class="slot" type="button" data-menu-view="live-activity-stream" aria-label="Live activity stream" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12h4l3-7 5 14 3-7h5"/></svg></button>
            <button class="slot" type="button" data-menu-view="modes" aria-label="Modes" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="7"/><circle cx="9" cy="12" r="3"/><path d="M17 10v4"/></svg></button>
            <button class="slot" type="button" data-menu-view="panic-revoke" aria-label="Panic revoke" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4a5 5 0 1 0 0 10l4 4h3v3h4v-5l-6-6M3 21 21 3"/></svg></button>
            <button class="slot" type="button" data-menu-view="per-app-rules" aria-label="Per-app rules" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 16h7M14 20h7M17 14v4M19 18v4"/></svg></button>
            <button class="slot" type="button" data-menu-view="quiet-hours-restrictions" aria-label="Quiet-hours restrictions" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3a9 9 0 1 0 7 13A9 9 0 0 1 14 3Z M17 5v5M20 5v5"/></svg></button>
            <button class="slot" type="button" data-menu-view="remote-surfaces" aria-label="Remote surfaces" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="4" width="13" height="10" rx="2"/><path d="M5 19h7M8 14v5"/><rect x="17" y="10" width="5" height="11" rx="1"/><path d="M19 18h1"/></svg></button>
            <button class="slot" type="button" data-menu-view="work-rate" aria-label="Work rate" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 20V4M3 20h18M7 16v-4M12 16V8M17 16V5"/><path d="m6 8 5-4 4 1 5-3"/></svg></button>
            <button class="slot" type="button" data-menu-view="macos-permissions" aria-label="macOS permissions" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3"/><rect x="9" y="10" width="6" height="5" rx="1"/><path d="M10 10V8a2 2 0 0 1 4 0v2"/></svg></button>
            <div class="sep"></div>
            <div class="avatar" title="the owner's avatar — placeholder">A</div>
          </div>
          <!-- The instrument tile is separate from the seventeen approved destinations. -->
          <button class="tile" id="menu-toggle" type="button" aria-label="Host instruments"
                  aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false" title="Host instruments">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 8h16M4 12h16M4 16h10" stroke-linecap="round"/>
              <path d="M17.5 15.5l2.5 2.5-2.5 2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
        <div class="menu-tooltip" id="menu-tooltip" role="tooltip" hidden><strong></strong><span></span></div>
        <nav class="menu-rail" aria-label="Home destinations">
          <button type="button" data-menu-view="projects" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false">
            <span>projects</span><span class="menu-orb"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h7l2 2h9v10H3zM3 7V5h7l2 2"/></svg></span>
          </button>
          <button type="button" data-menu-view="research" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false">
            <span>research</span><span class="menu-orb"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5M7 10h6M10 7v6"/></svg></span>
          </button>
          <button type="button" data-menu-view="history" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false">
            <span>history</span><span class="menu-orb"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8a9 9 0 1 1-1 7M4 3v5h5M12 7v5l3 2"/></svg></span>
          </button>
          <button type="button" data-menu-view="settings" aria-haspopup="dialog" aria-controls="menu-panel" aria-expanded="false">
            <span>settings</span><span class="menu-orb"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg></span>
          </button>
        </nav>
        <dialog class="menu-panel" id="menu-panel" aria-labelledby="menu-title" aria-describedby="menu-intro">
          <header class="menu-heading"><button type="button" class="menu-back" aria-label="Back to previous menu" hidden>←</button><h2 id="menu-title"></h2>
            <button type="button" class="menu-close" aria-label="Close panel" autofocus>×</button>
          </header>
          <p class="menu-intro" id="menu-intro"></p>
          <div class="menu-content" id="menu-content"></div>
        </dialog>
        <script>
        (function () {
         'use strict';
         document.addEventListener('DOMContentLoaded',function(){
          var CATALOGUE = [{"id": "action-outbox", "name": "Action outbox", "bucket": "A", "area": "main", "what": "Every external side effect, durably recorded before it happens, with reconciliation state.", "reason": "The live reconciliation registry is not attached to this publisher."}, {"id": "autonomy-queue", "name": "Autonomy queue", "bucket": "A", "area": "main", "what": "What VESPER intends to do unprompted, before it does it.", "reason": "The live autonomy loop is not attached to this publisher."}, {"id": "emergency-stop", "name": "Emergency stop", "bucket": "A", "area": "main", "what": "Halt everything. Independent of the thing it stops, by design.", "reason": "The native bridge exposes no independent stop command. In the existing app, hold Globe/Fn + Control + Option + Command for 0.6 seconds to stop VESPER; Globe three times starts it again. This panel cannot invoke that native stop."}, {"id": "grants", "name": "Grants", "bucket": "A", "area": "main", "what": "Standing permissions, their scope, and their expiry.", "reason": "The running policy decision point is not attached to this publisher."}, {"id": "verification-state", "name": "Verification state", "bucket": "A", "area": "main", "what": "What's been verified, what's asserted, and the refusal to let repetition count as success.", "reason": "The live verifier is not attached to this publisher."}, {"id": "follow-me", "name": "Follow-me", "bucket": "B", "area": "main", "what": "The interface moving with VESPER as it relocates.", "reason": "No relocation-to-interface transport is registered on this surface."}, {"id": "grant-templates", "name": "Grant templates", "bucket": "B", "area": "main", "what": "Reusable permission sets — 'study mode', 'travel mode', 'hands off'.", "reason": "No owner-defined grant template collection or governed apply operation exists."}, {"id": "hardware-access", "name": "Hardware access", "bucket": "B", "area": "main", "what": "Camera, microphone, screen, files — what's granted, what's in use, and a capture indicator that can't lie.", "reason": "The native bridge publishes neither active capture sessions nor complete permission state. Device presence is not access consent."}, {"id": "import-export", "name": "Import / export", "bucket": "B", "area": "main", "what": "Take your memory with you, or seed it from somewhere else.", "reason": "No portable memory transfer operation is exposed by the native bridge. Copying live database files would lose WAL records."}, {"id": "live-activity-stream", "name": "Live activity stream", "bucket": "B", "area": "main", "what": "A running narration of what VESPER is doing, at a granularity you set.", "reason": "No runtime event stream has been supplied to this publisher."}, {"id": "modes", "name": "Modes", "bucket": "B", "area": "main", "what": "Study / travel / low-power / hands-off — whole configurations you switch between.", "reason": "The existing permission mode does not define study, travel, low-power, or hands-off configurations. Those presets need governed definitions before they can be applied."}, {"id": "panic-revoke", "name": "Panic revoke", "bucket": "B", "area": "main", "what": "Drop every standing grant at once, without stopping VESPER.", "reason": "The policy decision point has no public revoke-all operation, and the native bridge has no revoke command."}, {"id": "per-app-rules", "name": "Per-app rules", "bucket": "B", "area": "main", "what": "What VESPER may touch in each application, separately.", "reason": "No per-application policy collection or governed editor exists."}, {"id": "quiet-hours-restrictions", "name": "Quiet-hours restrictions", "bucket": "B", "area": "main", "what": "Narrower permissions at night than during the day.", "reason": "No owner-defined quiet-hours authorization policy exists. Alarm overrides must remain intact."}, {"id": "remote-surfaces", "name": "Remote surfaces", "bucket": "B", "area": "main", "what": "Reaching VESPER from a phone or another machine.", "reason": "No enrolled endpoint inventory is attached to this publisher."}, {"id": "work-rate", "name": "Work rate", "bucket": "B", "area": "main", "what": "Throughput over time — is VESPER actually getting things done.", "reason": "No bounded runtime completion history has been supplied."}, {"id": "showcase", "name": "Showcase", "bucket": "A", "area": "main", "what": "The window VESPER shows things on: a file at a line, an image, a video, a browser it drives itself, a whiteboard, arrows and its own cursor, built on its Desktop while you work on yours and revealed when you ask.", "reason": "The showcase window is not open, so nothing can be put on it."}, {"id": "macos-permissions", "name": "macOS permissions", "bucket": "B", "area": "main", "what": "Accessibility, Screen Recording, Automation — what's granted, what's needed for which feature, and why.", "reason": "Permission status is not exported by the native bridge. Querying permissions from a helper would report the helper’s identity, not the app’s."}, {"id": "attestation-state", "name": "Attestation state", "bucket": "A", "area": "instruments", "what": "Whether a VESPER-controlled segment exists and is attested. Today: false, so no node is a full host.", "reason": "The network fabric contract could not be read."}, {"id": "battery-health", "name": "Battery health", "bucket": "A", "area": "instruments", "what": "Capacity, cycles, temperature history, daily charge range. The numbers that decide the ten-year question.", "reason": "No usable battery capacity and cycle counters were returned."}, {"id": "capability-registry", "name": "Capability registry", "bucket": "A", "area": "instruments", "what": "Every capability, its level, and the constants that are refused outright.", "reason": "The running capability registry is not attached to this publisher."}, {"id": "charge-policy", "name": "Charge policy", "bucket": "A", "area": "instruments", "what": "Charge limit state, and whether the machine is sitting at high charge — the mechanism that aged this pack to 84% in a shop.", "reason": "The OS did not return battery charge range or charge-limit state."}, {"id": "compensation", "name": "Compensation", "bucket": "A", "area": "instruments", "what": "What each in-flight action would undo if it fails partway.", "reason": "The running executor’s compensator registry is not attached to this publisher."}, {"id": "compressor-swap", "name": "Compressor & swap", "bucket": "A", "area": "instruments", "what": "How hard the compressor is working, and whether swap has turned on. Swap is the SSD-wear tripwire.", "reason": "The OS did not return compressor and swap counters."}, {"id": "control-plane-lease", "name": "Control-plane lease", "bucket": "A", "area": "instruments", "what": "Which node holds control, its fencing token, and its refusal to self-promote.", "reason": "No readable leased-domain state was supplied."}, {"id": "degradation-ladder", "name": "Degradation ladder", "bucket": "A", "area": "instruments", "what": "What VESPER gives up first when it must give something up.", "reason": "The governed degradation contract could not be read."}, {"id": "endpoints", "name": "Endpoints", "bucket": "A", "area": "instruments", "what": "Every surface VESPER can reach you through, as profiles rather than device names.", "reason": "The live device registry is not attached to this publisher."}, {"id": "enrollment", "name": "Enrollment", "bucket": "A", "area": "instruments", "what": "Admit a new machine, measure it, and watch it earn placement on merit.", "reason": "No live enrollment registry is instantiated by this runtime. Discovery and admission cannot be performed by the display."}, {"id": "governed-surfaces", "name": "Governed surfaces", "bucket": "A", "area": "instruments", "what": "Which files require review, and who reviews them.", "reason": "The governed-surface artifact could not be read."}, {"id": "key-identity-state", "name": "Key & identity state", "bucket": "A", "area": "instruments", "what": "Each node's keys, where they're stored, and which never leave the device.", "reason": "No enrolled device key-storage profiles were supplied. Key material is never read by this panel."}, {"id": "memory-headroom", "name": "Memory headroom", "bucket": "A", "area": "instruments", "what": "Real reclaimable memory, translated — not the alarming 'free' figure that reads 0.16 GB on a healthy machine.", "reason": "The host adapter could not read reclaimable memory."}, {"id": "memory-pressure-band", "name": "Memory pressure band", "bucket": "A", "area": "instruments", "what": "The kernel's own signal, shown as a band. Never converted to gigabytes — it doesn't track allocation.", "reason": "The kernel did not expose a pressure band."}, {"id": "network-segments", "name": "Network segments", "bucket": "A", "area": "instruments", "what": "Private / shared / outside, each with its trust ceiling. No addresses, no product names.", "reason": "The declared network segments could not be read."}, {"id": "node-profiles", "name": "Node profiles", "bucket": "A", "area": "instruments", "what": "What each machine measurably sustains. UNKNOWN means unavailable, and shows as such.", "reason": "No live enrolled measured profiles were supplied."}, {"id": "owner-working-set", "name": "Owner working set", "bucket": "A", "area": "instruments", "what": "What's resident right now, so a headroom number is interpretable rather than just a figure.", "reason": "The OS process resident-memory inventory was unavailable."}, {"id": "placement-decisions", "name": "Placement decisions", "bucket": "A", "area": "instruments", "what": "Where each capability currently runs and why it was placed there, including what lost.", "reason": "No live placement assignment or decision history was supplied."}, {"id": "platform-adapters", "name": "Platform adapters", "bucket": "A", "area": "instruments", "what": "Per-platform translation of host signals. The knowledge lives in the adapter, never in shared logic.", "reason": "The host adapter could not be loaded."}, {"id": "survival-profile", "name": "Survival profile", "bucket": "A", "area": "instruments", "what": "What VESPER carries onto the last device standing, and what it drops.", "reason": "No enrolled placement profile with measured resource budgets was supplied."}, {"id": "trust-zones", "name": "Trust zones", "bucket": "A", "area": "instruments", "what": "Z0–Z3 per node, with the reason each landed where it did.", "reason": "No enrolled effective trust assignments were supplied. A key-storage ceiling alone is not an effective trust zone."}, {"id": "before-after", "name": "Before/after", "bucket": "B", "area": "instruments", "what": "Measure a change you made and show whether it actually helped.", "reason": "Capture a fresh baseline and a later reading in this panel to compare them."}, {"id": "command-palette", "name": "Command palette", "bucket": "B", "area": "instruments", "what": "Keyboard-first access to every surface in this document.", "reason": "The palette is available locally through the instruments panel or Command-K."}, {"id": "costing-me-now", "name": "Costing me now", "bucket": "B", "area": "instruments", "what": "Live ranked list of what is draining the battery this minute.", "reason": "Public process CPU and RSS counters do not measure battery energy. Per-process power attribution requires privileged powermetrics."}, {"id": "disk-i-o-rate", "name": "Disk I/O rate", "bucket": "B", "area": "instruments", "what": "Live read/write throughput, and cumulative writes against SSD endurance.", "reason": "Two comparable storage-counter samples are needed before a rate can be measured."}, {"id": "display-power", "name": "Display power", "bucket": "B", "area": "instruments", "what": "Brightness and its real cost. The display dominates idle drain, so this is a bigger lever than CPU.", "reason": "The public display inventory does not report measured display watts. Brightness alone cannot establish power cost."}, {"id": "link-quality", "name": "Link quality", "bucket": "B", "area": "instruments", "what": "Latency, throughput and reliability per path — measured at enrollment, never declared.", "reason": "No enrollment-measured per-path latency, throughput, and reliability record is published. A TCP reachability check is not that measurement."}, {"id": "maintenance-actions", "name": "Maintenance actions", "bucket": "B", "area": "instruments", "what": "Things worth doing occasionally, surfaced when they're due rather than remembered.", "reason": "No maintenance schedule or last-completed action ledger has been configured."}, {"id": "node-roles", "name": "Node roles", "bucket": "B", "area": "instruments", "what": "What each machine is FOR — always-on server, travelling laptop, phone endpoint.", "reason": "The live enrollment registry has not published role assignments. Availability classes are not roles."}, {"id": "peripherals", "name": "Peripherals", "bucket": "B", "area": "instruments", "what": "What's plugged in, what it draws, and what it keeps awake.", "reason": "No public peripheral inventory was returned."}, {"id": "radio-state", "name": "Radio state", "bucket": "B", "area": "instruments", "what": "Wi-Fi and Bluetooth power cost, and what's keeping them awake.", "reason": "No public radio-state observation was returned."}, {"id": "relocation-history", "name": "Relocation history", "bucket": "B", "area": "instruments", "what": "When VESPER moved, what triggered it, and the damping that stopped it flapping.", "reason": "No placement events are available in the supplied bounded log tail."}, {"id": "retry-policy", "name": "Retry policy", "bucket": "B", "area": "instruments", "what": "What VESPER does when something fails, per task class.", "reason": "The running reconciler’s retry policy could not be read."}, {"id": "sleep-wake-log", "name": "Sleep & wake log", "bucket": "B", "area": "instruments", "what": "Every sleep, wake, and what woke it. Where mystery battery drain gets explained.", "reason": "The public power-management log could not be read."}, {"id": "storage-ssd", "name": "Storage & SSD", "bucket": "B", "area": "instruments", "what": "Free space, TRIM, SMART, and cumulative write pressure.", "reason": "The public disk inventory could not be read."}, {"id": "thermal-history", "name": "Thermal history", "bucket": "B", "area": "instruments", "what": "Temperature over time against ambient — the variable that matters most in site B heat.", "reason": "No battery-temperature samples have been collected. Ambient temperature is unavailable."}, {"id": "throttle-events", "name": "Throttle events", "bucket": "B", "area": "instruments", "what": "When the machine actually throttled, and what was running.", "reason": "The public power-management interface returned no recorded performance-warning status."}, {"id": "approval-history", "name": "Approval history", "bucket": "C", "area": "instruments", "what": "Everything you've ever approved, and the chance to withdraw any of it.", "reason": "No approval records are available in the supplied bounded audit tail. Withdrawal is unavailable without a revoke operation."}, {"id": "blast-radius", "name": "Blast radius", "bucket": "C", "area": "instruments", "what": "What breaks if a given node dies — simulated before it happens.", "reason": "No enrolled placement profiles and assignments were supplied for simulation."}, {"id": "clock-skew", "name": "Clock skew", "bucket": "C", "area": "instruments", "what": "How far apart the nodes' clocks are — and the reminder that HLC, not wall clock, decides order.", "reason": "No bounded request/response clock observations from other nodes were supplied. Local timestamps alone cannot establish skew."}, {"id": "migration-dry-run", "name": "Migration dry-run", "bucket": "C", "area": "instruments", "what": "Move VESPER somewhere, in simulation, and see what degrades.", "reason": "No enrolled placement profiles were supplied for simulation."}, {"id": "node-comparison", "name": "Node comparison", "bucket": "C", "area": "instruments", "what": "Two machines side by side on every measured axis.", "reason": "At least two enrolled measured node profiles are needed for comparison."}, {"id": "onboarding-wizard", "name": "Onboarding wizard", "bucket": "C", "area": "instruments", "what": "Walk a new machine from nothing to enrolled and measured.", "reason": "The native bridge has no discovery, measurement, or admission command. The wizard can prepare a request but cannot enroll a node."}, {"id": "ambient-estimate", "name": "Ambient estimate", "bucket": "D", "area": "instruments", "what": "Inferred room temperature — the ceiling the battery can never get below.", "reason": "There is no ambient-temperature sensor. Battery temperature is not room temperature."}, {"id": "behaviour-on-off-this-mac", "name": "Behaviour on / off this Mac", "bucket": "D", "area": "instruments", "what": "Different rules when VESPER is here versus running on another node.", "reason": "The owner has not defined the location-dependent policy. No policy is inferred."}, {"id": "charging-schedule", "name": "Charging schedule", "bucket": "D", "area": "instruments", "what": "When to charge, given your day, to minimise time at high state of charge.", "reason": "The owner has not supplied a charging schedule, and no governed charging-control action is available."}, {"id": "consent-channel-policy", "name": "Consent channel policy", "bucket": "D", "area": "instruments", "what": "Which tiers may be approved by voice and which need a tap you make yourself.", "reason": "The owner has not decided which approval tiers may use voice versus an explicit tap."}, {"id": "failover-drill", "name": "Failover drill", "bucket": "D", "area": "instruments", "what": "Deliberately kill a node and prove recovery works. A negative control for the fabric.", "reason": "This action deliberately kills a node. Separate explicit owner authorization is required; icon approval does not authorize a drill."}, {"id": "fan-acoustics", "name": "Fan & acoustics", "bucket": "D", "area": "instruments", "what": "Fan speed and noise — heat you can hear before you can measure it.", "reason": "No supported public fan-speed or acoustic-power sensor is exposed to this publisher."}, {"id": "power-draw", "name": "Power draw", "bucket": "D", "area": "instruments", "what": "Whole-machine watts split into compute vs everything else. Compute is 8% at idle — the split is the insight.", "reason": "Whole-machine compute-versus-other power attribution requires privileged powermetrics. No root-access workaround is attempted."}, {"id": "process-energy", "name": "Process energy", "bucket": "D", "area": "instruments", "what": "Per-process power attribution — who is actually costing you battery, ranked.", "reason": "Per-process power attribution requires privileged powermetrics tasks. CPU usage is not watts."}];
          var MAX_MENU_READINGS=51, MAX_MAIN_ITEMS=17, MAX_MENU_METRIC_ROWS=100;
          var MAX_MENU_HISTORY=60, MAX_MENU_TEXT=6000, MAX_DATA_CHARS=16000;
          var MAX_SEARCH=200, MAX_NUMERIC_FIELDS=100, MAX_DEPTH=5;
          var panel=document.getElementById('menu-panel'),title=document.getElementById('menu-title');
          var intro=document.getElementById('menu-intro'),content=document.getElementById('menu-content');
          var tile=document.getElementById('menu-toggle'),tooltip=document.getElementById('menu-tooltip');
          var triggers=Array.from(document.querySelectorAll('[data-menu-view]'));
          var active='',opener=null,rows=new Map(),catalogue=new Map(CATALOGUE.map(function(i){return [i.id,i];}));
          var history=null,historyQuery='',historyTruncated=false,historyNodes=null;
          var lastMetrics=null,expiryTimer=null,baseline=null,receiveVersion=0;
          var MAX_MENU_NAV=12,trail=[],back=panel.querySelector('.menu-back');
          var instrumentQuery='',instrumentTopic='all',instrumentStatus='all',expanded=new Set();
          var instrumentControls=null;
          // These topics are navigation only. Engineering buckets must not imply that
          // an unavailable observation is less useful or disappear from the catalogue.
          var TOPICS=[
           {id:'power',name:'Battery & energy',items:['battery-health','charge-policy','charging-schedule','costing-me-now','display-power','power-draw','process-energy']},
           {id:'health',name:'Memory, storage & thermals',items:['memory-headroom','memory-pressure-band','compressor-swap','owner-working-set','disk-i-o-rate','storage-ssd','thermal-history','throttle-events','ambient-estimate','fan-acoustics']},
           {id:'fabric',name:'Nodes & connections',items:['attestation-state','endpoints','enrollment','key-identity-state','network-segments','node-profiles','platform-adapters','trust-zones','link-quality','node-roles','peripherals','radio-state','clock-skew','node-comparison','onboarding-wizard']},
           {id:'continuity',name:'Placement & continuity',items:['control-plane-lease','degradation-ladder','placement-decisions','survival-profile','relocation-history','blast-radius','migration-dry-run','failover-drill']},
           {id:'governance',name:'Permissions & activity',items:['capability-registry','compensation','governed-surfaces','maintenance-actions','retry-policy','sleep-wake-log','approval-history','behaviour-on-off-this-mac','consent-channel-policy']},
           {id:'tools',name:'Comparison & search',items:['before-after','command-palette']}
          ];
          var instrumentItems=CATALOGUE.filter(function(i){return i.area==='instruments';}).slice(0,MAX_MENU_READINGS);
          var topicFor=new Map();TOPICS.forEach(function(t){t.items.forEach(function(id){topicFor.set(id,t.id);});});
          function node(tag,cls,text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
          function bounded(v){return typeof v==='string'?v.slice(0,MAX_MENU_TEXT):'';}
          function action(label,fn){var b=node('button','menu-action',label);b.type='button';b.addEventListener('click',fn);return b;}
          function focusHost(){try{window.webkit.messageHandlers.vesperFocus.postMessage('1');}catch(e){}}
          function hideTooltip(){tooltip.hidden=true;}
          function showTooltip(b,item){
           if(panel.open)return;
           tooltip.querySelector('strong').textContent=item.name;tooltip.querySelector('span').textContent=item.what;
           tooltip.hidden=false;var r=b.getBoundingClientRect();
           tooltip.style.left=Math.max(12,Math.min(r.left+r.width/2-tooltip.offsetWidth/2,window.innerWidth-tooltip.offsetWidth-12))+'px';
           tooltip.style.top=Math.max(12,r.top-tooltip.offsetHeight-12)+'px';
          }
          // §11.6 AND §11.7: THE RAIL'S OWN DESTINATIONS.
          //
          // `settings` opens the full-screen card. `research` and `projects` are Work-room
          // cards rather than whole spaces -- HOME-ARCHITECTURE §14.2 records that
          // asymmetry as the thing to discuss -- and `projects` has NO SPECIFICATION:
          // `spec_raw.txt` routes 17 items to `history` and NONE to a projects surface.
          // So `projects` says that, in one sentence, rather than showing an invented
          // surface. A screen that guesses at seventeen features nobody asked for is
          // worse than one that admits the gap, and §11.7 says the gap is what the
          // discussion is for.
          triggers.forEach(function(b){var item=catalogue.get(b.dataset.menuView);if(!item)return;
           b.setAttribute('aria-description',item.what);
           b.addEventListener('pointerenter',function(){showTooltip(b,item);});
           b.addEventListener('focus',function(){showTooltip(b,item);});
           b.addEventListener('pointerleave',hideTooltip);b.addEventListener('blur',hideTooltip);
          });
          document.querySelector('.bar').addEventListener('scroll',hideTooltip);
          window.addEventListener('resize',hideTooltip);
          function fresh(r){var now=Date.now();return !!r && r.status==='available' && typeof r.value==='string' && typeof r.source==='string' && r.source.length>0
           && Number.isFinite(r.at_ms) && r.at_ms>0 && Number.isFinite(r.ttl_ms) && r.ttl_ms>0
           && r.at_ms<=now && now-r.at_ms<=r.ttl_ms;}
          function reason(item,r){
           if(!r)return item.reason;
           if(r.status==='unavailable')return bounded(r.reason)||item.reason;
           if(!fresh(r))return 'The observation is expired, unstamped, or clock-invalid. Waiting for a fresh measurement.';
           return '';
          }
          function putText(el,text){if(el.textContent!==text)el.textContent=text;}
          function dataText(data){try{var text=JSON.stringify(data,null,2)||'';return text.length>MAX_DATA_CHARS?text.slice(0,MAX_DATA_CHARS)+'\\n… display limited to '+MAX_DATA_CHARS+' characters':text;}catch(e){return 'Details could not be decoded.';}}
          function updateReading(el,item){
           var r=rows.get(item.id),known=fresh(r);
           el.dataset.available=String(known);
           putText(el.querySelector('.menu-reading-value'),known?bounded(r.value):'UNAVAILABLE');
           var message=known?bounded(r.details):reason(item,r);
           if(known)message+=' Source: '+bounded(r.source)+'. Observed '+new Date(r.at_ms).toLocaleTimeString()+'.';
           putText(el.querySelector('.menu-reason'),message);
           var pre=el.querySelector('.menu-data'),text=known&&r.data!==null&&r.data!==undefined?dataText(r.data):'';
           pre.hidden=!text;putText(pre,text);el.querySelector('.menu-evidence').hidden=!text;
          }
          function reading(item,open){
           var el=node('details','menu-reading');el.dataset.item=item.id;el.open=!!open;
           var summary=node('summary');summary.append(node('span','menu-reading-name',item.name),node('span','menu-reading-value'));
           var evidence=node('details','menu-evidence');
           evidence.append(node('summary','','Observation details'),node('pre','menu-data'));
           el.append(summary,node('p','',item.what),node('p','menu-reason'),evidence);
           el.addEventListener('toggle',function(e){if(e.target!==el)return;if(el.open)expanded.add(item.id);else expanded.delete(item.id);});
           if(['before-after','command-palette','enrollment','onboarding-wizard'].includes(item.id)){
            el.append(action('Open '+item.name,function(){show(item.id,opener);}));
           }
           // WHAT CAN BE DONE FROM THIS INSTRUMENT (core/menu_cards.instrument_actions):
           // every reading carries at least an explain act; the ones VESPER can change
           // carry the host action that changes it. Owner, 2026-09-13: readings alone
           // were "a bunch of data showing up".
           var iacts=(cardsData&&cardsData._instruments&&cardsData._instruments[item.id])||[];
           if(iacts.length)el.append(actionButtons(iacts));
           updateReading(el,item);return el;
          }
          function renderInstruments(){
           if(!instrumentControls){
            content.textContent='';
            var tools=node('div','menu-tools');
            tools.append(action('Search all surfaces · ⌘K',function(){show('command-palette');}),action('Before / after',function(){show('before-after');}));
            var search=node('input','menu-search');search.type='search';search.maxLength=MAX_SEARCH;
            search.placeholder='Find an instrument';search.setAttribute('aria-label','Find an instrument');search.value=instrumentQuery;
            var filters=node('div','menu-filters');
            function select(label,choices,value){var wrap=node('label','menu-filter-label',label),el=node('select');
             choices.forEach(function(c){var option=node('option','',c[1]);option.value=c[0];el.append(option);});
             el.value=value;wrap.append(el);filters.append(wrap);return el;
            }
            var topic=select('Topic',[['all','All topics']].concat(TOPICS.map(function(t){return [t.id,t.name];})),instrumentTopic);
            var status=select('Availability',[['all','All observations'],['available','Current readings'],['unavailable','Unavailable']],instrumentStatus);
            var count=node('p','menu-results');count.setAttribute('role','status');count.setAttribute('aria-live','polite');
            var empty=node('p','menu-note','No instruments match these filters.');empty.hidden=true;
            var reset=action('Clear filters',function(){instrumentQuery='';instrumentTopic='all';instrumentStatus='all';
             search.value='';topic.value='all';status.value='all';renderInstruments();search.focus();});
            content.append(search,filters,reset,tools,count,empty);
            TOPICS.forEach(function(t){var section=node('section','menu-group');section.dataset.topic=t.id;
             var heading=node('h3','',t.name);heading.id='menu-topic-'+t.id;
             heading.append(node('span','menu-group-count'));section.setAttribute('aria-labelledby',heading.id);section.append(heading);
             instrumentItems.filter(function(i){return topicFor.get(i.id)===t.id;}).forEach(function(i){section.append(reading(i,expanded.has(i.id)));});content.append(section);
            });
            instrumentControls={count:count,empty:empty,reset:reset};
            search.addEventListener('input',function(){instrumentQuery=search.value;renderInstruments();});
            topic.addEventListener('change',function(){instrumentTopic=topic.value;renderInstruments();});
            status.addEventListener('change',function(){instrumentStatus=status.value;renderInstruments();});
           }
           var query=instrumentQuery.trim().toLowerCase(),shown=0,current=0;
           // Update existing nodes: a producer tick must not collapse an open row,
           // move keyboard focus, reset a search, or replace unchanged evidence text.
           content.querySelectorAll('.menu-reading').forEach(function(el){var item=catalogue.get(el.dataset.item);
            updateReading(el,item);var known=el.dataset.available==='true';if(known)current++;
            el.hidden=!(instrumentTopic==='all'||topicFor.get(item.id)===instrumentTopic)
             ||!(instrumentStatus==='all'||(instrumentStatus==='available')===known)
             ||!(item.name+' '+item.what).toLowerCase().includes(query);
            if(!el.hidden)shown++;
           });
           content.querySelectorAll('.menu-group').forEach(function(group){var n=group.querySelectorAll('.menu-reading:not([hidden])').length;
            group.hidden=n===0;putText(group.querySelector('.menu-group-count'),String(n));});
           putText(instrumentControls.count,'Showing '+shown+' of '+instrumentItems.length+' instruments');
           instrumentControls.empty.hidden=shown>0;
           instrumentControls.reset.hidden=!query&&instrumentTopic==='all'&&instrumentStatus==='all';
           putText(intro,current+' current readings · '+(instrumentItems.length-current)+' unavailable. Every instrument includes its description and evidence or a reason.');
          }
          // ---- the rail's own destinations (§11.6, §11.7) -------------------------
          //
          // ONE PANEL SYSTEM, ONE PLACE. Settings first rendered as a SEPARATE
          // full-screen card while `show()` still fell through to its UNAVAILABLE
          // message -- so the owner saw both at once, which is what they reported.
          // These are branches of `show()` now; the panel is styled full-screen for the
          // settings view alone, which is the geometry §11.6 asked for.
          var railData = {projects: null, research: null, dashboard: null};
          window.__vesperRail = function (which, json) {
            try { railData[which] = JSON.parse(json); } catch (e) { railData[which] = null; }
            // THE DASHBOARD ARRIVES UNDER ITS OWN NAME AND IS SHOWN UNDER ANOTHER. The
            // view is `projects`; the payload is `dashboard`. Comparing the two
            // directly meant the data landed while the surface was open and nothing
            // redrew -- the owner would be looking at UNAVAILABLE with the answer
            // already in the page.
            var showing = (which === 'dashboard') ? 'projects' : which;
            if (active === showing) show(showing, opener);
          };
          function stateChip(state){
            var el = node('span', 'rail-state ' + 'rs-' + String(state || 'unknown').replace(/[^a-z_]/g,''));
            el.textContent = String(state || 'unknown').replace(/_/g, ' ');
            return el;
          }
          function railList(rows, emptyWhy){
            if (!Array.isArray(rows) || !rows.length){
              content.append(node('span','menu-status','UNAVAILABLE'),
                             node('p','menu-note', emptyWhy));
              return;
            }
            // AN UNAVAILABLE ROW IS A ROW, NOT AN EMPTY LIST. A producer that could not
            // read its file says so in a row with its reason, and that must reach the
            // owner rather than being rendered as nothing.
            var counts = {};
            rows.forEach(function(r){ var k = r.status === 'available' ? (r.state||'unknown') : 'unreadable';
                                      counts[k] = (counts[k]||0)+1; });
            var summary = Object.keys(counts).sort().map(function(k){ return counts[k]+' '+k.replace(/_/g,' '); }).join(' · ');
            content.append(node('p','menu-note', rows.length + ' — ' + summary));
            var list = node('div','rail-list');
            rows.forEach(function(r){
              var row = node('div','rail-row');
              var left = node('div');
              left.append(node('div','rail-name', r.name || r.id || 'untitled'));
              if (r.status !== 'available'){
                left.append(node('div','rail-detail', r.reason || 'no reason given'));
              } else {
                if (r.detail) left.append(node('div','rail-detail', r.detail));
                if (r.waiting) left.append(node('div','rail-waiting', 'waiting on: ' + r.waiting));
              }
              var right = node('div');
              right.append(stateChip(r.status === 'available' ? r.state : 'unreadable'));
              if (r.where) right.append(node('div','rail-where', r.where));
              row.append(left, right);
              list.append(row);
            });
            content.append(list);
          }
          // §28. THE DASHBOARD, NOT A LIST. The owner: "when i click the projects side
          // button, its dashboard pops up, has at the top places where i can switch
          // between phases ... or switch between engineering modes".
          //
          // THREE SWITCHES AND THEY ARE NOT ONE CONTROL. The project's own phase is
          // CORRECTIVE -- "if they were not chosen well" -- so choosing it again must
          // lose nothing; the engineering MODE is a different axis, practice against
          // work. Rendering them as one row of tabs would merge two questions that have
          // different answers.
          var dashPhase = '', dashMode = 'work';

          function dashSwitch(label, rows, current, onPick){
            var wrap = node('div','dash-switch');
            wrap.append(node('span','dash-switch-label', label));
            var group = node('div','dash-switch-row');
            group.setAttribute('role','group');
            group.setAttribute('aria-label', label);
            rows.forEach(function(r){
              var b = node('button','dash-chip', r.name || r.id);
              b.type = 'button';
              b.dataset.id = r.id;
              var on = (r.id === current);
              b.setAttribute('aria-pressed', String(on));
              if (on) b.classList.add('is-on');
              // THE EXPLANATION IS THE CONTRACT'S OWN SENTENCE, never invented here.
              if (r.what) b.title = r.what;
              b.addEventListener('click', function(){ onPick(r.id); });
              group.append(b);
            });
            wrap.append(group);
            return wrap;
          }

          function renderProjects(){
            var d = railData.dashboard;
            if (!d || !Array.isArray(d.panels) || !d.panels.length){
              content.append(node('span','menu-status','UNAVAILABLE'),
                             node('p','menu-note','The dashboard producer has not run yet.'));
              return;
            }
            // WHICH PROJECT THIS IS ABOUT, SAID OUT LOUD. Vesper answered "the project
            // root" with the bundle's contents once; a surface about a directory names
            // the directory.
            intro.textContent = d.project_root
              ? ('The project at ' + d.project_root + '.')
              : ('No project directory is known, so nothing below can be read. '
                 + 'The dashboard refuses to guess which directory it is about.');

            var phases = Array.isArray(d.phases) ? d.phases : [];
            var modes  = Array.isArray(d.modes)  ? d.modes  : [];
            if (!dashPhase && phases.length) dashPhase = phases[0].id;

            var top = node('div','dash-top');
            top.append(dashSwitch('Phase', phases, dashPhase, function(id){
              dashPhase = id; show('projects', opener);
            }));
            top.append(dashSwitch('Engineering', modes, dashMode, function(id){
              dashMode = id; show('projects', opener);
            }));
            content.append(top);

            var here = phases.filter(function(p){ return p.id === dashPhase; })[0];
            if (here && here.what) content.append(node('p','menu-note', here.what));

            var grid = node('div','dash-grid');
            d.panels.forEach(function(p){
              // A PANEL OF THE OTHER MODE IS SHOWN DIMMED, NOT DELETED, so switching
              // reveals something the owner already knew was there.
              var card = node('div','dash-panel');
              if (p.mode && p.mode !== dashMode) card.classList.add('is-other-mode');
              card.append(node('h4','dash-panel-name', p.name || p.id));
              if (p.status === 'composed'){
                card.append(node('span','dash-tag','COMPOSED'));
                card.append(node('p','dash-panel-what', p.composes || p.what || ''));
              } else if (p.status === 'available'){
                card.append(node('span','dash-value', String(p.value || '')));
                card.append(node('p','dash-panel-what', p.what || ''));
                if (p.source) card.append(node('p','dash-source', 'read from ' + p.source));
              } else {
                // UNAVAILABLE CARRIES ITS REASON. A false zero looks measured and is not.
                card.append(node('span','menu-status','UNAVAILABLE'));
                card.append(node('p','dash-panel-what', p.value || p.what || ''));
              }
              grid.append(card);
            });
            content.append(grid);
            content.append(renderBoard('projects'));
          }
          // THE WORKSPACE ON A BOARD (core/boards.py). Owner, 2026-09-13: "windows and
          // cards should appear there ... with full management i choose from a pop up
          // list". A picker of the LIVE windows and of the cards VESPER has; the chosen
          // ones listed with their status and the acts that manage each; and the
          // stage's open-a-window acts. Every button posts a control; nothing here
          // moves a window itself.
          function boardPost(action,args){
            try{window.webkit.messageHandlers.vesperControl.postMessage(JSON.stringify({action:action,args:args||{}}));}
            catch(e){(window.__vesperErrs=window.__vesperErrs||[]).push('control: '+(e&&e.message));}
          }
          function actionButtons(actions){
            var bar=node('div','menu-actions');bar.style.cssText='display:flex;flex-wrap:wrap;gap:6px;margin-top:6px';
            (actions||[]).forEach(function(a){
              var b=node('button','menu-action',a.label);b.type='button';b.dataset.control=(a.control&&a.control.action)||'';
              b.addEventListener('click',function(){if(!a.control)return;boardPost(a.control.action,a.control.args||{});b.disabled=true;var was=b.textContent;b.textContent=was+' — sent';setTimeout(function(){b.disabled=false;b.textContent=was;},2500);});
              bar.append(b);
            });
            return bar;
          }
          function renderBoard(kind){
            var all=railData.boards, b=all&&all[kind];
            var sect=node('section','board');sect.dataset.board=kind;
            var h=node('h3','',kind==='projects'?'Workspace: windows and cards on this board':'Room: windows and cards in this research');
            sect.append(h);
            if(!b){sect.append(node('p','menu-note','The board producer has not run yet; the picker fills in when it does.'));return sect;}
            // The picker: a live window, added to the board.
            var pick=node('div','board-pick');pick.style.cssText='display:flex;gap:8px;align-items:center;margin:8px 0';
            var sel=node('select','st-ctl');sel.setAttribute('aria-label','Add a window to the board');
            var o0=node('option','', (b.available_windows||[]).length?'Choose a window to add…':(b.inventory_why?'No window list: '+b.inventory_why:'Every open window is already on the board'));o0.value='';sel.append(o0);
            (b.available_windows||[]).forEach(function(w){var o=node('option','',(w.app_label||'?')+' — window '+w.window_id+(w.provenance==='vesper_opened'?' (VESPER\\'s)':' (yours)'));o.value=w.window_id;sel.append(o);});
            var add=node('button','menu-action','Add window');add.type='button';
            add.addEventListener('click',function(){var w=(b.available_windows||[]).filter(function(x){return String(x.window_id)===sel.value;})[0];if(!w)return;boardPost('board.add_window',{kind:kind,window:{window_id:w.window_id,app_label:w.app_label,pid:w.pid}});});
            pick.append(sel,add);sect.append(pick);
            var csel=node('select','st-ctl');csel.setAttribute('aria-label','Add a card to the board');
            var c0=node('option','',(b.available_cards||[]).length?'Choose a card to add…':'Every card is already on the board');c0.value='';csel.append(c0);
            (b.available_cards||[]).forEach(function(c){var o=node('option','',c.name);o.value=c.id;o.title=c.what||'';csel.append(o);});
            var cadd=node('button','menu-action','Add card');cadd.type='button';
            cadd.addEventListener('click',function(){if(!csel.value)return;boardPost('board.add_card',{kind:kind,card_id:csel.value});});
            var cpick=node('div','board-pick');cpick.style.cssText='display:flex;gap:8px;align-items:center;margin:8px 0';cpick.append(csel,cadd);sect.append(cpick);
            // What is on the board, with its status and its acts.
            var list=node('div','rail-list');
            (b.chosen_windows||[]).forEach(function(w){
              var row=node('div','rail-row');var left=node('div');left.append(node('div','rail-name',(w.app_label||'?')+' — window '+w.window_id));
              left.append(node('div','rail-detail',String(w.status)+' · '+String(w.provenance||'unknown').replace(/_/g,' ')));
              var right=node('div');right.append(actionButtons(w.actions));row.append(left,right);list.append(row);
            });
            (b.chosen_cards||[]).forEach(function(c){
              var row=node('div','rail-row');var left=node('div');left.append(node('div','rail-name',c.name));left.append(node('div','rail-detail','card'));
              var right=node('div');right.append(actionButtons(c.actions));row.append(left,right);list.append(row);
            });
            if(!(b.chosen_windows||[]).length&&!(b.chosen_cards||[]).length)list.append(node('p','menu-note','Nothing chosen yet. Pick a window or a card above.'));
            sect.append(list);
            sect.append(node('p','menu-note','Open a window on this Desktop:'));sect.append(actionButtons(b.open_actions));
            // THE WORK ITSELF (core/workflows.py): start a research question or a
            // project goal, and watch each step land with its files.
            if(b.start_control){
              var sc=b.start_control,wrow=node('div','board-pick');wrow.style.cssText='display:flex;gap:8px;align-items:center;margin:12px 0 6px';
              var q=node('input','st-ctl');q.type='text';q.placeholder=sc.placeholder||'';q.size=42;q.setAttribute('aria-label',sc.label);
              var go=node('button','menu-action',sc.label);go.type='button';
              go.addEventListener('click',function(){var t=q.value.trim();if(t.length<8)return;boardPost(sc.action,kind==='research'?{question:t}:{goal:t});q.value='';go.disabled=true;go.textContent=sc.label+' — started';setTimeout(function(){go.disabled=false;go.textContent=sc.label;},4000);});
              wrow.append(q,go);sect.append(wrow);
            }
            var runs=b.workflows||[];
            if(runs.length){
              var rl=node('div','rail-list');
              runs.forEach(function(r){
                var row=node('div','rail-row');row.dataset.run=r.id;var left=node('div');
                left.append(node('div','rail-name',String(r.title)));
                var steps=(r.steps||[]).map(function(s){return s.name+':'+s.status;}).join(' · ');
                left.append(node('div','rail-detail',(r.status||'')+(steps?' — '+steps:'')+(r.dir?' — '+r.dir:'')));
                if(r.summary)left.append(node('div','rail-detail',String(r.summary).slice(0,400)));
                var right=node('div');right.append(stateChip(r.status==='done'?'available':r.status==='running'?'running':'unavailable'));
                row.append(left,right);rl.append(row);
              });
              sect.append(node('p','menu-note',runs.length+' run(s), newest first:'));sect.append(rl);
            }
            if(kind==='research'){
              var ss=node('div','board-pick');ss.style.cssText='display:flex;gap:8px;align-items:center;margin:8px 0';
              var name=node('input','st-ctl');name.type='text';name.placeholder='new research session name';name.value=b.session||'';name.setAttribute('aria-label','Research session name');
              var setb=node('button','menu-action',b.session?'Rename / switch session':'Start a session');setb.type='button';
              setb.addEventListener('click',function(){if(!name.value.trim())return;boardPost('board.research_session',{session:name.value.trim()});});
              ss.append(name,setb);sect.append(ss);
              if((b.session_actions||[]).length)sect.append(actionButtons(b.session_actions));
              var sess=b.sessions||[];sect.append(node('p','menu-note',sess.length?sess.length+' recorded session(s): '+sess.map(function(s){return s.session_id;}).join(', '):'no recorded sessions yet'));
            }
            return sect;
          }
          function renderResearch(){
            intro.textContent = 'Every question settled by measurement, with the status the '
              + 'spike index gives it — never a document\\'s own header, which is the thing '
              + 'that has been wrong before.';
            content.append(renderBoard('research'));
            railList(railData.research,
                     'The spike index has not arrived on this surface yet.');
          }
          // THE CONTROL ON A SETTINGS ROW, and the one way it leaves the page. Owner,
          // 2026-09-13: a settings screen that shows values and changes nothing is not
          // settings. Each row that is the owner's to set carries `controls` from the
          // producer -- key, kind, bounds, current value -- and this renders exactly
          // that and nothing the page invented: the runtime re-checks the value against
          // the same schema before writing it. Shared by the rail's settings card and
          // the side-button panel, so both manage and neither drifts.
          window.__vesperSettingControls = function(r){
            var ctls = Array.isArray(r && r.controls) ? r.controls : [];
            if (!ctls.length) return null;
            var wrap = document.createElement('div'); wrap.className = 'st-ctls';
            wrap.style.cssText = 'display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:6px';
            function post(action, args){
              try { window.webkit.messageHandlers.vesperControl.postMessage(JSON.stringify({action: action, args: args})); }
              catch (e) { (window.__vesperErrs = window.__vesperErrs || []).push('control: ' + (e && e.message)); }
            }
            ctls.forEach(function(c){
              var el = null, shown = null;
              if (c.kind === 'bool') {
                el = document.createElement('input'); el.type = 'checkbox'; el.checked = !!c.value;
                el.addEventListener('change', function(){ post('preference.set', {key: c.key, value: el.checked}); });
              } else if (c.kind === 'choice') {
                el = document.createElement('select');
                (c.options || []).forEach(function(o){ var op = document.createElement('option'); op.value = o; op.textContent = o; if (o === c.value) op.selected = true; el.appendChild(op); });
                el.addEventListener('change', function(){ post('preference.set', {key: c.key, value: el.value}); });
              } else if (c.kind === 'range') {
                // THE NUMBER IS ON THE SCREEN, NOT IN A TOOLTIP. A slider the owner is
                // asked to set a percentage with has to show that percentage while they
                // drag it; `title` appears on hover, after a pause, and never at all on
                // a trackpad tap. The unit comes from the producer (preferences.UNITS),
                // because "70" and "0" beside each other say nothing and "70%" and
                // "0 dB" say what they are.
                el = document.createElement('input'); el.type = 'range'; el.min = c.min; el.max = c.max; el.step = c.step; el.value = c.value; el.title = String(c.value);
                shown = document.createElement('span'); shown.className = 'st-val';
                shown.setAttribute('data-for', c.key || '');
                shown.style.cssText = 'font:12px var(--face-body);color:var(--ink);opacity:.72;min-width:36px;text-align:right';
                shown.textContent = String(c.value) + (c.unit || '');
                el.addEventListener('input', function(){ shown.textContent = el.value + (c.unit || ''); });
                el.addEventListener('change', function(){ el.title = el.value; shown.textContent = el.value + (c.unit || ''); post('preference.set', {key: c.key, value: Number(el.value)}); });
              } else if (c.kind === 'text') {
                el = document.createElement('input'); el.type = 'text'; el.value = c.value == null ? '' : String(c.value); el.size = 6;
                el.addEventListener('change', function(){ post('preference.set', {key: c.key, value: el.value}); });
              }
              if (el) {
                el.className = 'st-ctl'; el.setAttribute('data-key', c.key || '');
                el.setAttribute('aria-label', c.label || c.key || 'setting');
                el.style.cssText = 'font:12px var(--face-body);color:var(--ink);background:rgba(255,255,255,.06);border:1px solid rgba(244,230,220,.18);border-radius:8px;padding:3px 6px';
                wrap.appendChild(el);
                if (shown) wrap.appendChild(shown);
              }
            });
            return wrap;
          };
          function renderSettings(){
            var rows = [];
            try { rows = JSON.parse(window.__vesperSettingsData || '[]'); } catch (e) { rows = []; }
            if (!Array.isArray(rows) || !rows.length){
              content.append(node('span','menu-status','UNAVAILABLE'),
                             node('p','menu-note','The settings producer has not run yet.'));
              return;
            }
            var known = rows.filter(function(r){ return r && r.status === 'available'; }).length;
            intro.textContent = known + ' of ' + rows.length + ' read a real value. '
              + 'Governed rows say where they are changed rather than offering a toggle '
              + 'that would skip the review that governs them.';
            var list = node('div','rail-list');
            rows.forEach(function(r){
              if (!r || typeof r.name !== 'string') return;
              var row = node('div','rail-row');
              var left = node('div');
              left.append(node('div','rail-name', r.name));
              var why = String(r.what || '');
              if (r.status !== 'available' && r.reason) why += '  — ' + r.reason;
              else if (r.governed && r.change_by) why += '  — changed by ' + r.change_by;
              left.append(node('div','rail-detail', why));
              var right = node('div');
              right.append(node('div','rail-value',
                                r.status === 'available' ? String(r.value) : 'UNAVAILABLE'));
              if (r.status === 'available' && r.source) right.append(node('div','rail-where', String(r.source)));
              var ctl = window.__vesperSettingControls(r); if (ctl) right.append(ctl);
              right.append(stateChip(r.governed ? 'governed' : 'yours to set'));
              row.append(left, right);
              list.append(row);
            });
            content.append(list);
          }
          function renderHistory(){
           if(!historyNodes)return;var list=historyNodes.list;list.textContent='';
           if(history===null){historyNodes.note.textContent='The conversation has not arrived on this surface yet.';return;}
           var shown=history.filter(function(r){return (r.who+' '+r.text).toLowerCase().includes(historyQuery.toLowerCase());});
           historyNodes.note.textContent=shown.length+' of '+history.length+' supplied entries'+(historyTruncated?' · newest '+MAX_MENU_HISTORY+', older ones are in the log.':'.');
           // NEWEST FIRST. The owner opens this to see what just happened, and scrolling
           // to the bottom of sixty entries to find it is the same defect as showing the
           // oldest sixty -- which is what `slice(0, ...)` did until 2026-09-11.
           // EACH ENTRY CAN BE ACTED ON (owner, 2026-09-13: the side buttons showed
           // data and managed nothing). What you said can be asked again; what VESPER
           // said can be explained. Both go through the typed path, like a sentence.
           shown.slice().reverse().forEach(function(r){var el=node('li');el.append(node('strong','',r.who),node('p','',r.text));
            var acts=node('div','menu-actions');acts.style.cssText='display:flex;gap:6px;margin-top:4px';
            var b=node('button','menu-action',r.who==='you'?'Ask again':'Explain this');b.type='button';b.dataset.control='act';
            b.addEventListener('click',function(){menuPost('act',{text:r.who==='you'?r.text:'explain what you meant when you said: '+String(r.text).slice(0,300)});b.disabled=true;b.textContent=b.textContent+' — sent';});
            acts.append(b);el.append(acts);list.append(el);});
          }
          function palette(){
           intro.textContent='Search all 68 surfaces by name or description. Opening a surface does not execute its action.';
           var search=node('input','menu-search');search.type='search';search.maxLength=MAX_SEARCH;search.placeholder='Find a surface';search.setAttribute('aria-label','Find a surface');
           var list=node('div','menu-palette');content.append(search,list);
           function filter(){list.textContent='';var query=search.value.toLowerCase();
            var matches=CATALOGUE.filter(function(i){return (i.name+' '+i.what).toLowerCase().includes(query);});
            if(!matches.length)list.append(node('p','menu-note','No matching surface.'));
            matches.slice(0,MAX_MENU_READINGS+MAX_MAIN_ITEMS).forEach(function(i){list.append(action(i.name,function(){show(i.id,opener);}));});
           }search.addEventListener('input',filter);filter();return search;
          }
          function numeric(data,prefix,out,depth){
           if(depth>MAX_DEPTH||!data||typeof data!=='object')return;
           Object.keys(data).slice(0,MAX_NUMERIC_FIELDS).forEach(function(k){if(Object.keys(out).length>=MAX_NUMERIC_FIELDS)return;
            var v=data[k],path=prefix?prefix+'.'+k:k;
            if(typeof v==='number'&&Number.isFinite(v)&&!/(^|[._])(at_ms|pid|expiry_ms|epoch|cycles)$/.test(path))out[path]=v;
            else if(v&&typeof v==='object'&&!Array.isArray(v))numeric(v,path,out,depth+1);
           });
          }
          function capture(){
           var out={};['memory-headroom','memory-pressure-band','compressor-swap','storage-ssd','disk-i-o-rate','battery-health'].forEach(function(id){
            var r=rows.get(id);if(fresh(r)){var fields={};numeric(r.data,'',fields,0);if(Object.keys(fields).length)out[id]={name:r.label,source:r.source,at_ms:r.at_ms,fields:fields};}
           });return out;
          }
          function beforeAfter(){
           intro.textContent='Compare two fresh observations from the same producers. A change is a measured difference, not proof that your action caused it.';
           var note=node('p','menu-note'),output=node('pre','menu-data');
           function describe(){note.textContent=baseline?'Baseline captured with '+Object.keys(baseline.values).length+' readings. Wait for the next producer update, then compare.':'No baseline captured in this session.';}
           content.append(action('Capture baseline',function(){var values=capture();if(!Object.keys(values).length){note.textContent='UNAVAILABLE — no fresh numeric readings are available.';return;}
            baseline={values:values,version:receiveVersion};output.textContent=dataText(values);describe();}),
            action('Compare latest',function(){
             if(!baseline){note.textContent='Capture a baseline first.';return;}
             if(receiveVersion===baseline.version){note.textContent='Waiting for a new producer update.';return;}
             var latest=capture(),compared=[];
             Object.keys(baseline.values).forEach(function(id){var a=baseline.values[id],b=latest[id];
              if(!b||a.source!==b.source||a.at_ms===b.at_ms)return;
              Object.keys(a.fields).forEach(function(k){if(Object.prototype.hasOwnProperty.call(b.fields,k))compared.push({reading:a.name,field:k,before:a.fields[k],after:b.fields[k],delta:b.fields[k]-a.fields[k],before_at_ms:a.at_ms,after_at_ms:b.at_ms});});
             });
             note.textContent=compared.length?'Compared '+compared.length+' fields. Raw numbers and both observation times are retained.':'UNAVAILABLE — no later comparable fresh observations.';
             output.textContent=dataText(compared);
            }),note,output);describe();
          }
          function onboarding(){
           var item=catalogue.get('onboarding-wizard');intro.textContent=item.what;
           content.append(node('p','menu-note',item.reason));
           var label=node('label','menu-caption','New node identifier'),input=node('input','menu-search');input.id='menu-node-id';input.maxLength=64;label.htmlFor=input.id;
           input.placeholder='A stable profile identifier';var output=node('pre','menu-data');
           content.append(label,input,action('Prepare enrollment request',function(){
            var id=input.value.trim();if(!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/.test(id)){output.textContent='Use 1–64 letters, digits, dots, underscores or hyphens; begin with a letter or digit.';return;}
            output.textContent=dataText({kind:'enrollment-request',node_id:id,status:'NOT_ENROLLED',steps:[
             'Discover through an authorized transport.','Read key-storage and availability profiles.',
             'Measure resource capacity and sustained throughput at enrollment.',
             'Validate security baseline, capability floor and attested segment.',
             'Submit admission through the live enrollment registry; compare placement on merit.'
            ],missing:'Native enrollment transport and live registry are unavailable. This request changes no registry or policy.'});
           }),output);
          }
          // THE CARDS BEHIND THE SEVENTEEN MAIN DESTINATIONS (core/menu_cards.py).
          // Owner, 2026-09-13: "its buttons need to open cards where i can manage
          // stuff". A card is rows with sources, settings rows borrowed from the
          // settings producer (same control, same schema), and action buttons whose
          // payload is a control -- posted through vesperControl and applied by the
          // runtime or the host according to its kind. Nothing here is invented by the
          // page: every row, control and action arrives from the producer.
          var cardsData={};
          window.__vesperCards=function(json){
           try{cardsData=JSON.parse(json)||{};}catch(e){cardsData={};}
           if(panel.open&&active&&cardsData[active])show(active,null,true);
          };
          function menuPost(action,args){
           try{window.webkit.messageHandlers.vesperControl.postMessage(JSON.stringify({action:action,args:args||{}}));}
           catch(e){(window.__vesperErrs=window.__vesperErrs||[]).push('control: '+(e&&e.message));}
          }
          function renderCard(card){
           var wrap=node('div','menu-card');
           if(card.summary)wrap.append(node('p','menu-note',card.summary));
           var list=node('div','rail-list');
           (card.rows||[]).forEach(function(r){
            var row=node('div','rail-row');var left=node('div');left.append(node('div','rail-name',String(r.label)));
            if(r.detail)left.append(node('div','rail-detail',String(r.detail)));
            var right=node('div');right.append(node('div','rail-value',String(r.value)));
            if(r.source)right.append(node('div','rail-where',String(r.source)));
            row.append(left,right);list.append(row);
           });
           wrap.append(list);
           var srows=[];try{srows=JSON.parse(window.__vesperSettingsData||'[]');}catch(e){srows=[];}
           (card.settings||[]).forEach(function(id){
            var r=(srows||[]).filter(function(x){return x&&x.id===id;})[0];if(!r)return;
            var row=node('div','rail-row');var left=node('div');left.append(node('div','rail-name',r.name));
            left.append(node('div','rail-detail',String(r.what||'')));
            var right=node('div');right.append(node('div','rail-value',String(r.value)));
            var c=window.__vesperSettingControls(r);if(c)right.append(c);
            row.append(left,right);wrap.append(row);
           });
           if((card.controls||[]).length){
            var c2=window.__vesperSettingControls({controls:card.controls});if(c2)wrap.append(c2);
           }
           if((card.actions||[]).length){
            var bar=node('div','menu-actions');bar.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin-top:12px';
            card.actions.forEach(function(a){
             var b=node('button','menu-action',a.label);b.type='button';b.dataset.control=(a.control&&a.control.action)||'';
             if(a.note)b.title=a.note;
             if(a.danger)b.style.borderColor='rgba(255,120,120,.6)';
             b.addEventListener('click',function(){
              if(!a.control)return;menuPost(a.control.action,a.control.args||{});
              b.disabled=true;var was=b.textContent;b.textContent=was+' — sent';
              setTimeout(function(){b.disabled=false;b.textContent=was;},2500);
             });
             bar.append(b);
            });
            wrap.append(bar);
           }
           return wrap;
          }
          function show(view,trigger,restoring){
           if(panel.open&&active!==view&&!restoring){trail.push({view:active,scroll:panel.scrollTop});if(trail.length>MAX_MENU_NAV)trail.shift();}
           if(!panel.open){trail=[];opener=trigger&&trigger.isConnected?trigger:tile;}
           focusHost();hideTooltip();active=view;panel.dataset.view=view;content.textContent='';historyNodes=null;instrumentControls=null;
           back.hidden=trail.length===0;
           var item=catalogue.get(view),focus=null;
           title.textContent=item?item.name:({instruments:'Host & fabric instruments',projects:'Projects',research:'Research',history:'Conversation history',settings:'Settings'}[view]||'UNAVAILABLE');
           intro.textContent=item?item.what:'';
           if(view==='instruments')renderInstruments();
           else if(view==='command-palette')focus=palette();
           else if(view==='before-after')beforeAfter();
           else if(view==='onboarding-wizard'||view==='enrollment')onboarding();
           else if(item&&item.area==='main'&&cardsData[view]){content.append(renderCard(cardsData[view]));}
           else if(item){content.append(reading(item,true));}
           else if(view==='settings'){renderSettings();}
           else if(view==='projects'){renderProjects();}
           else if(view==='research'){renderResearch();}
           else if(view==='history'){
            intro.textContent='Conversation entries in their supplied order. This is not the full action log.';
            var search=node('input','menu-search');search.type='search';search.maxLength=MAX_SEARCH;search.placeholder='Find in conversation';search.setAttribute('aria-label','Find in conversation');search.value=historyQuery;
            var exp=node('button','menu-action','Export conversation');exp.type='button';exp.dataset.control='history.export';
            exp.addEventListener('click',function(){menuPost('history.export',{});exp.disabled=true;exp.textContent='Export conversation — sent to your Desktop';});
            var note=node('p','menu-note'),list=node('ol','menu-history-list');content.append(search,exp,note,list);historyNodes={note:note,list:list};
            search.addEventListener('input',function(){historyQuery=search.value;renderHistory();});renderHistory();
           }else{content.append(node('span','menu-status','UNAVAILABLE'),node('p','menu-note','This destination has no collection or save operation connected to this surface.'));}
           tile.setAttribute('aria-expanded',String(view==='instruments'));
           triggers.forEach(function(b){b.setAttribute('aria-expanded',String(b.dataset.menuView===view));});
           if(!panel.open)panel.showModal();panel.scrollTop=0;
           if(focus)focus.focus();else panel.querySelector('.menu-close').focus();
          }
          back.addEventListener('click',function(){var previous=trail.pop();if(!previous)return;
           show(previous.view,null,true);panel.scrollTop=previous.scroll;
          });
          tile.addEventListener('click',function(){show('instruments',tile);});
          triggers.forEach(function(b){b.addEventListener('click',function(){show(b.dataset.menuView,b);});});
          panel.querySelector('.menu-close').addEventListener('click',function(){panel.close();});
          panel.addEventListener('click',function(e){var r=panel.getBoundingClientRect();if(e.target===panel&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))panel.close();});
          panel.addEventListener('close',function(){if(panel.open)return;active='';tile.setAttribute('aria-expanded','false');triggers.forEach(function(b){b.setAttribute('aria-expanded','false');});if(opener&&opener.isConnected)opener.focus();trail=[];});
          document.addEventListener('keydown',function(e){
           if(e.key==='Escape')hideTooltip();
           if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();show('command-palette',document.activeElement);}
          });
          function refresh(){
           if(active==='instruments')renderInstruments();
           else if(catalogue.has(active))content.querySelectorAll('.menu-reading').forEach(function(el){updateReading(el,catalogue.get(el.dataset.item));});
           if(expiryTimer!==null)clearTimeout(expiryTimer);expiryTimer=null;
           if(document.hidden)return;
           var now=Date.now(),next=Infinity;
           rows.forEach(function(r){if(fresh(r))next=Math.min(next,r.at_ms+r.ttl_ms-now+1);});
           if(Number.isFinite(next))expiryTimer=setTimeout(refresh,Math.min(next,2147483647));
          }
          var previousMetrics=window.__vesperMetrics;
          window.__vesperMetrics=function(json){
           // The HOST receiver owns its tags. Forward the original payload even if
           // menu rendering fails; filtering its input by menu names loses unrelated
           // readings, and an early throw must not silence the other card.
           try{
            var incoming=[];
            try{var parsed=JSON.parse(json);if(Array.isArray(parsed))incoming=parsed.filter(function(r){
             if(!r||typeof r!=='object')return false;var item=catalogue.get(r.id);
             return item&&r.area===item.area&&r.label===item.name;
            }).slice(0,MAX_MENU_METRIC_ROWS);}catch(e){}
            if(json!==lastMetrics){lastMetrics=json;receiveVersion++;rows.clear();
             incoming.forEach(function(r){rows.set(r.id,r);});
            }
            refresh();
           }finally{
            if(typeof previousMetrics!=='function')throw new Error('HOST metrics receiver is missing');
            previousMetrics(json);
           }
          };
          var previousHistory=window.__vesperHistory,lastHistory=null;
          window.__vesperHistory=function(json){
           if(json!==lastHistory){lastHistory=json;history=null;historyTruncated=false;
            try{var parsed=JSON.parse(json);if(Array.isArray(parsed)){historyTruncated=parsed.length>MAX_MENU_HISTORY;
             history=parsed.slice(-MAX_MENU_HISTORY).filter(function(r){return r&&typeof r.text==='string';}).map(function(r){return {who:r.who==='owner'?'you':bounded(r.who)||'unknown',text:bounded(r.text)};});
            }}catch(e){}if(active==='history')renderHistory();
           }if(typeof previousHistory==='function')previousHistory(json);
          };
          document.addEventListener('visibilitychange',refresh);refresh();
         },{once:true});
        })();
        </script>
        <!-- ==== /MENU ==== -->

        <script>
          // The field's only job: hand the text to Swift and clear itself. It does not
          // render the result -- the transcript is pushed back in by the runtime, so
          // what the owner sees is what VESPER actually recorded rather than an
          // optimistic echo that might never have arrived.
          (function () {
            var f = document.getElementById('say');
            if (!f) return;
            // ASK FOR FOCUS ON POINTER-DOWN, before the click resolves. VESPER is an
            // accessory app and does not activate by being clicked; without this the
            // field shows a caret and receives nothing.
            ['pointerdown', 'focus'].forEach(function (ev) {
              f.addEventListener(ev, function () {
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); }
                catch (err) { /* no bridge: the keydown handler reports it */ }
              });
            });
            f.addEventListener('keydown', function (e) {
              if (e.key !== 'Enter') return;
              var v = f.value.trim();
              if (!v) return;
              try {
                window.webkit.messageHandlers.vesperSay.postMessage(v);
                f.value = '';
              } catch (err) {
                // NO SILENT SWALLOW. If the bridge is absent the owner has just typed
                // into a void, and the field saying so is the only way they would know.
                f.value = '';
                f.placeholder = 'not connected to the runtime';
              }
            });
          })();
        </script>

        <script>
          // THE CONVERSATION SURFACE. The card animates the current exchange; the bar
          // above it holds the history. Both are driven entirely from data pushed by
          // Swift -- the page keeps no record of its own, so a refresh cannot disagree
          // with the runtime about what was said.
          (function () {
            var stage = document.getElementById('stage');
            var hist  = document.getElementById('history');
            var hrows = document.getElementById('hrows');
            if (!stage) return;
            var showing = '';

            // SPLIT BY GRAPHEME, NOT BY INDEX. `text[i]` walks UTF-16 CODE UNITS, so
            // an emoji -- a surrogate pair, often several joined by ZWJ -- was torn
            // into halves that are not characters at all. That is why they rendered as
            // boxes: the dissolve had already destroyed them before the font was ever
            // asked for a glyph. Intl.Segmenter is the correct instrument; Array.from
            // is the fallback and at least keeps surrogate pairs whole.
            var seg = (typeof Intl !== 'undefined' && Intl.Segmenter)
              ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;
            function graphemes(s) {
              if (seg) return Array.from(seg.segment(s), function (g) { return g.segment; });
              return Array.from(s);
            }

            // HOW MANY GLYPHS THE CARD CAN ACTUALLY SHOW, measured rather than picked:
            // 48 characters per line at the real type size in a 420 px card, and
            // `max-height: 132px` over a 21.7 px line box is six lines. 288.
            //
            // EVERY GLYPH PAST IT WAS BEING SPLIT, GIVEN ITS OWN SCATTER VECTOR, ITS
            // OWN DELAY AND ITS OWN ANIMATION, AND THEN CLIPPED BY `overflow: hidden`.
            // A 250-word reply built hundreds of elements to animate text nobody could
            // see. The margin is there because the card's width is derived from the
            // face's position and a narrower face means more lines.
            var ANIMATED_MAX = 320;

            function paint(text, who, mode) {
              stage.className = 'say' + (who === 'vesper' ? ' vesper' : '') + ' ' + mode;
              stage.innerHTML = '';
              var all = graphemes(text);
              var gs = all.slice(0, ANIMATED_MAX);
              var n = gs.length;
              for (var i = 0; i < n; i++) {
                var b = document.createElement('b');
                b.textContent = gs[i];
                var a = Math.random() * Math.PI * 2;
                var d = 22 + Math.random() * 62;
                b.style.setProperty('--dx', (Math.cos(a) * d).toFixed(1) + 'px');
                b.style.setProperty('--dy', (Math.sin(a) * d - 20).toFixed(1) + 'px');
                b.style.setProperty('--rot', ((Math.random() - 0.5) * 42).toFixed(1) + 'deg');
                // Staggered from the middle outwards so the line frays rather than
                // wiping left to right, which reads as a transition effect.
                var mid = Math.abs(i - n / 2) / (n / 2 || 1);
                b.style.animationDelay = ((mode === 'out' ? (1 - mid) : mid) * 240).toFixed(0) + 'ms';
                stage.appendChild(b);
              }
              // APPENDED AFTER THE LOOP, not before it. Appended first it came out at
              // the FRONT of the card -- the tail of the sentence rendered ahead of its
              // own beginning, which is a worse bug than the one being fixed.
              if (all.length > n) {
                // The remainder still goes in -- clipped today, and the card is not
                // guaranteed to stay this size. It arrives as ONE element with no
                // per-glyph treatment, because a per-glyph treatment on text that
                // cannot be seen is the cost without the effect.
                var rest = document.createElement('b');
                rest.textContent = all.slice(n).join('');
                rest.style.animationDelay = '240ms';
                stage.appendChild(rest);
              }
            }

            // WHAT THE FACE IS TOLD WHILE VESPER IS TALKING.
            //
            // §6 is explicit that speaking is DRIVEN AND NOT LOOPED -- "a sine wave
            // pretending to be speech is the same failure as a status column reading
            // 41 C on a host with no thermometer". There is no audio path yet, so the
            // honest driver available is the delivery itself: which word of the reply
            // is on screen right now. That is a real fact about real output. It is not
            // amplitude and is not reported as amplitude -- Swift receives it tagged
            // `textReveal`, and Behaviour.swift drives a shallower envelope for it than
            // it will for `audio`, because a reveal cursor carries no loudness.
            //
            // PER WORD, NOT PER FRAME OF A RAMP. A monotonic ramp would render as a
            // slow zoom, which is the THINKING channel and would make the two states
            // indistinguishable -- the exact thing §6 keeps them on separate channels
            // to avoid. Word boundaries are real structure in the real sentence, so the
            // envelope rises and falls on them and the face moves the way the sentence
            // is shaped.
            var speakTimer = null;
            function tellFace(level, source) {
              try {
                window.webkit.messageHandlers.vesperSpeaking.postMessage(
                  JSON.stringify({ level: level, source: source }));
              } catch (e) {}
            }
            function stopSpeaking() {
              if (speakTimer) { clearInterval(speakTimer); speakTimer = null; }
              tellFace(0, 'none');
            }
            function speakOut(text) {
              stopSpeaking();
              var words = String(text).split(/\\s+/).filter(Boolean);
              if (!words.length) return;
              // Cadence from the text, not a constant: a long word occupies the mouth
              // for longer than a short one. ~165 wpm is unhurried speech; the per-word
              // share is proportional to its length so the total tracks the sentence.
              var totalChars = words.join('').length || 1;
              var totalMs = Math.min(14000, (words.length / 165) * 60000);
              var t0 = Date.now(), acc = [], run = 0;
              for (var i = 0; i < words.length; i++) {
                var share = (words[i].length / totalChars) * totalMs;
                acc.push([run, run + share, words[i].length]);
                run += share;
              }
              speakTimer = setInterval(function () {
                var el = Date.now() - t0;
                if (el >= run) { stopSpeaking(); return; }
                for (var i = 0; i < acc.length; i++) {
                  if (el >= acc[i][0] && el < acc[i][1]) {
                    // Within a word: open toward the middle, close toward its end.
                    // Height from the word's own length, capped -- a fifteen-letter
                    // word does not open the mouth three times as far as a five.
                    var p = (el - acc[i][0]) / Math.max(1, acc[i][1] - acc[i][0]);
                    var h = Math.min(1, 0.45 + acc[i][2] / 12);
                    tellFace(h * Math.sin(p * Math.PI), 'textReveal');
                    return;
                  }
                }
              }, 33);
            }

            // ONE PENDING TRANSITION, NOT ONE PER ARRIVAL.
            //
            // This scheduled a fresh `setTimeout(next, 860)` on every call, with `text`
            // captured per closure. A typed turn publishes the owner's line and then
            // the reply, and since replies now come back in about half a second BOTH
            // land inside the same 860 ms dissolve -- so two timers were pending, each
            // holding a different line. The first painted, and a few milliseconds later
            // the second wiped it and painted over. The owner's own words appeared for
            // a few frames and vanished with no dissolve at all, on every single turn.
            // Reproduced offscreen 2026-08-26 with `layout_probe --eval`.
            //
            // Now the dissolve is started once and the QUEUED TEXT is replaced. A line
            // superseded before it was ever shown is simply never shown, which is the
            // honest outcome: the card holds one line, and the newest is the one that
            // matters.
            var pending = null, pendingTimer = null;

            function arrive(text, who) {
              showing = text;
              paint(text, who, 'in');
              // ONLY VESPER'S OWN LINES SPEAK. The owner's line appears on the same
              // card and is not VESPER talking; driving the face from it would have
              // the face mouthing the owner's words back at them.
              if (who === 'vesper') speakOut(text); else stopSpeaking();
            }

            // The mirror of `paint`'s delay line, applied to children that already
            // exist. Kept here rather than inside `paint` because the outgoing line is
            // never re-created -- re-creating it would restart it from its `from` frame,
            // which is a flash, not a dissolve.
            function restagger(el, mode) {
              var kids = el.children, n = kids.length;
              for (var i = 0; i < n; i++) {
                var mid = Math.abs(i - n / 2) / (n / 2 || 1);
                kids[i].style.animationDelay =
                  ((mode === 'out' ? (1 - mid) : mid) * 240).toFixed(0) + 'ms';
              }
            }

            window.__vesperStage = function (text, who) {
              if (!text || text === showing) return;
              // WHAT THE STAGE HOLDS, so the list below does not print it a second
              // time. See __vesperHistory.
              window.__stageText = text;
              if (pendingTimer) { pending = { text: text, who: who }; return; }
              if (!showing) { arrive(text, who); return; }

              // DISSOLVE FIRST, THEN ARRIVE. The wait matches the scatter animation
              // plus its stagger; cutting it short would overlap two lines in the
              // one place they share, which is the whole reason this is a card and
              // not a list.
              //
              // RE-STAGGERED ON THE WAY OUT, and until now it never was. `paint` has
              // always computed a mirrored delay for `out` -- edges first, middle last,
              // so the line comes apart from its ends -- and `paint(text, who, 'out')`
              // was never once called. The outgoing children kept the delays they were
              // given when they arrived, so the dissolve played the ARRIVAL's stagger
              // backwards-in-name-only. Measured: the two delay sequences were
              // identical, element for element.
              restagger(stage, 'out');
              stage.classList.remove('in');
              stage.classList.add('out');
              pending = { text: text, who: who };
              pendingTimer = setTimeout(function () {
                pendingTimer = null;
                var p = pending; pending = null;
                if (p) arrive(p.text, p.who);
              }, 860);
            };


            // The workbench. Rows are pushed as DATA and written with textContent --
            // these lines carry provider names and error classifications straight off
            // the wire, and the day one contains a tag is the day that stops being
            // theoretical.
            var work = document.getElementById('work');
            var thinkEl = document.getElementById('think');
            var actsEl = document.getElementById('acts');
            var lastWork = '';
            window.__vesperWork = function (json) {
              if (json === lastWork) return;
              lastWork = json;
              var w;
              try { w = JSON.parse(json); } catch (e) { return; }
              var thoughts = (w && w.thoughts) || [], actions = (w && w.actions) || [];
              // THE PANES ARE RENDERED BEFORE THE EARLY RETURN BELOW, and that
              // ordering is the whole of why they work. The thoughts-and-actions card
              // returns as soon as it has nothing to draw, so anything written after
              // that line is painted only on ticks where VESPER happens to be thinking
              // -- which is the "built and nothing reaches it" shape this tree has
              // found five times. Commands outlive the turn that produced them.
              renderCommands((w && w.commands) || []);
              renderExplanations((w && w.explanations) || []);
              if (!work) return;
              if (!thoughts.length && !actions.length) { work.classList.add('idle'); return; }
              work.classList.remove('idle');
              // THE LINE BUDGET IS SPENT NEWEST-FIRST, AND THE NEWEST IS NEVER THE
              // CASUALTY.
              //
              // SS5's rule is about LINES on screen -- "never more than ~two lines" --
              // and it had been implemented as a cap of two THOUGHTS, discarded before
              // the renderer ever saw them. That is wrong in both directions: one long
              // thought is already several lines and passed the count, while two short
              // ones are one line each and hit the ceiling. And with exactly two
              // strings arriving there was no way to prefer the new one, so a fresh
              // thought had to share the budget with a stale one even when it needed
              // all of it.
              //
              // MEASURED, NOT ASSUMED. A line is a rendered height, which only the
              // engine knows -- a character count would be a guess that is wrong at
              // every width and every typeface, and the hand is a typeface nobody has
              // measured. So each older thought is appended and KEPT only if the block
              // still fits; the first is appended unconditionally and never tested.
              thinkEl.textContent = '';
              var lh = parseFloat(getComputedStyle(thinkEl).lineHeight) || 26;
              var lines = w.max_lines || 2;
              // THE GAPS BETWEEN THE LINES ARE PART OF THE BUDGET. Without them two
              // one-line thoughts measured 51.00 px against a budget of 50.92 and the
              // second was dropped -- SS5's "~two lines" decided by eight hundredths of
              // a pixel. Read from the DOM rather than hardcoded, so a change to the
              // paragraph spacing does not silently re-tune what fits.
              var probe = document.createElement('p');
              thinkEl.appendChild(probe);
              var gap = parseFloat(getComputedStyle(probe).marginBottom) || 0;
              thinkEl.removeChild(probe);
              var budget = lh * lines + gap * (lines - 1);
              for (var i = 0; i < thoughts.length; i++) {
                var p = document.createElement('p');
                p.textContent = thoughts[i];
                thinkEl.appendChild(p);
                // THE NEWEST IS APPENDED AND NEVER TESTED. The first version gave it a
                // ceiling of six lines and clipped it past that -- which is the defect
                // being fixed, arriving through the guard meant to prevent a different
                // one. A long thought is still a thought; what gives way when the card
                // runs short is the actions list below, which scrolls.
                // KEPT, NOT DROPPED -- CHANGED 2026-09-04. This removed every thought
                // past the line budget, so the budget decided what EXISTED rather than
                // what was visible, and the owner could not scroll back to anything
                // because there was nothing behind the fold. The budget now marks where
                // the fold IS: the block is capped in CSS and scrolls, and the older
                // thoughts stay in the DOM behind it, dimmed by the `p + p` rules.
                if (i === 0) { continue; }
                if (thinkEl.getBoundingClientRect().height > budget) {
                  p.classList.add('folded');
                }
              }
              actsEl.textContent = '';
              // NEWEST FIRST. The board is read at a glance and the thing that just
              // happened is the thing being looked for.
              for (var j = actions.length - 1; j >= 0; j--) {
                var a = actions[j];
                var row = document.createElement('div');
                row.className = 'act ' + (a.state || 'done');
                var dot = document.createElement('span'); dot.className = 'adot';
                var verb = document.createElement('span'); verb.className = 'averb';
                verb.textContent = a.verb || '';
                var det = document.createElement('span'); det.className = 'adet';
                det.textContent = a.detail || '';
                var sec = document.createElement('span'); sec.className = 'asec';
                // ROUNDED HERE AND NOWHERE ELSE. Rounding is presentation and belongs
                // to whoever renders it; the record keeps what was measured.
                sec.textContent = (typeof a.seconds === 'number')
                  ? a.seconds.toFixed(a.seconds < 10 ? 2 : 1) + 's' : '';
                row.appendChild(dot); row.appendChild(verb);
                row.appendChild(det); row.appendChild(sec);
                actsEl.appendChild(row);
                // The second line, and only when there is something on it. An empty
                // strip under every row is noise that looks like a layout bug.
                if (a.meta || a.at_ms) {
                  var m = document.createElement('div');
                  m.className = 'ameta';
                  if (a.meta) {
                    var mk = document.createElement('span');
                    mk.textContent = a.meta;
                    m.appendChild(mk);
                  }
                  if (a.at_ms) {
                    var t = document.createElement('span');
                    t.className = 'at';
                    // LOCAL CLOCK TIME, not "12 seconds ago". A relative label is
                    // wrong the moment the surface stops re-rendering, and this one
                    // re-renders on a timer that can stall -- a board that says "just
                    // now" about something from an hour ago is worse than no time.
                    var d = new Date(a.at_ms);
                    t.textContent = String(d.getHours()).padStart(2, '0') + ':'
                                  + String(d.getMinutes()).padStart(2, '0') + ':'
                                  + String(d.getSeconds()).padStart(2, '0');
                    m.appendChild(t);
                  }
                  actsEl.appendChild(m);
                }
              }
            };

            // ---- the host card's rows ---------------------------------------------
            //
            // RE-RENDERED ON THE TICK. The METRIC-ROWS token fills this once at mount,
            // so
            //
            // THE TOKEN'S NAME IS NOT WRITTEN HERE IN ITS SUBSTITUTABLE FORM, and that
            // is not fussiness. `page()` replaces every occurrence in the file, and it
            // does not know a comment from markup: written literally, this line
            // received 69 rows of HTML whose separator is "\\n          ", the first
            // newline ENDED THIS `//` COMMENT, and the remaining rows became raw
            // JavaScript. The whole script block then failed to parse, so
            // `__vesperStage`, `__vesperWork` and `__vesperChanges` were never
            // defined -- and every push silently did nothing, because
            // `if (window.__vesperWork)` skips rather than throws.
            //
            // IT ONLY BIT WHEN THE ROW COUNT ROSE. One row has no separator and no
            // newline, so this survived for as long as `power` was the only row that
            // resolved. The v2 menu took `rows` from 1 to 69 and the home lost its
            // commands, explanations, thoughts, changes and history cards -- measured
            // 2026-09-08, §9r. The latency between planting this and it firing is the
            // reason the token is spelled out rather than left as a live one.
            // without a push the card showed whatever was true when the home came up
            // -- and on a laptop the row that changes is the one worth reading.
            var metricsEl = document.getElementById('metrics');
            var lastMetrics = '', hostRows = [], hostExpiry = null;
            function renderHostMetrics() {
              if (!metricsEl) return;
              var now=Date.now();
              // AN EXPLICIT ABSENCE IS NOT A STALE READING and must not be aged out.
              // The freshness test exists so a dead producer's last number stops
              // looking current; a row that says UNAVAILABLE carries no number to go
              // stale, and dropping it is how the four model rows silently vanished
              // from this card instead of explaining themselves.
              var fresh=hostRows.filter(r => r && typeof r.label==='string' && typeof r.value==='string'
                && (r.status==='unavailable'
                    || (Number.isFinite(r.at_ms) && Number.isFinite(r.ttl_ms) && r.at_ms>0 && r.ttl_ms>0
                        && r.at_ms<=now && now-r.at_ms<=r.ttl_ms)));
              // Only replace when the rendered answer changes, preserving selections.
              var signature=JSON.stringify(fresh.map(r => [r.label,r.value]));
              if(signature!==lastMetrics){lastMetrics=signature;metricsEl.textContent='';
                fresh.forEach(function(r){var row=el('div','row');row.appendChild(el('span','k',r.label));row.appendChild(el('span','v',r.value));metricsEl.appendChild(row);});
                if(!fresh.length){var row=el('div','row');row.appendChild(el('span','k','no fresh producer'));metricsEl.appendChild(row);}
              }
              if(hostExpiry!==null)clearTimeout(hostExpiry);hostExpiry=null;
              if(!document.hidden && fresh.length)hostExpiry=setTimeout(renderHostMetrics,Math.min.apply(null,fresh.map(function(r){return r.at_ms+r.ttl_ms-now+1;})));
            }
            window.__vesperMetrics = function (json) {
              // SELECTED BY TAG, NEVER BY POSITION. This read `parsed.slice(0,5)`,
              // which was only ever correct while the HOST card's five keys happened
              // to sit at the front of the array. They did not: `power_source` was
              // the sole host reading that resolved, so the slice reached four rows
              // into the menu catalogue and rendered `Action outbox` and its
              // neighbours as host telemetry -- measured on the live surface,
              // 2026-09-08. The producer says which card owns each row; a count is
              // not an identity, and the cap below is a bound rather than a filter.
              try{var parsed=JSON.parse(json);
                hostRows=Array.isArray(parsed)
                  ?parsed.filter(function(r){return r&&r.card==='host';}).slice(0,8):[];
              }catch(e){hostRows=[];}
              renderHostMetrics();
            };
            document.addEventListener('visibilitychange',renderHostMetrics);

            // ---- the commands pane ------------------------------------------------
            //
            // WHAT IS OPEN SURVIVES A RE-RENDER. The state push runs every 700 ms and
            // rebuilds these rows from scratch; without a record of which rows the
            // owner had opened, any row they opened would shut again within the second
            // -- reading, from the owner's side, as a card that refuses to stay open.
            // Keyed on the command's id, which is stable for the life of the record.
            var openCmds = Object.create(null);
            var cmdrows = document.getElementById('cmdrows');
            var cmdcount = document.getElementById('cmdcount');
            var cmdsum = document.getElementById('cmdsum');
            var pcmds = document.getElementById('pcmds');

            function ms(n) {
              if (typeof n !== 'number') return '';
              return n < 1000 ? n + 'ms' : (n / 1000).toFixed(n < 10000 ? 2 : 1) + 's';
            }

            // EVERY ONE OF THESE IS textContent. The strings below are a command line
            // the owner may have dictated, a path off the filesystem, and a process's
            // own stderr -- three sources, none of which this page is entitled to
            // treat as markup.
            function el(tag, cls, text) {
              var e = document.createElement(tag);
              if (cls) e.className = cls;
              if (text !== undefined && text !== null) e.textContent = text;
              return e;
            }

            function renderCommands(cmds) {
              if (!cmdrows || !pcmds) return;
              if (!cmds.length) { pcmds.classList.add('idle'); return; }
              pcmds.classList.remove('idle');
              cmdcount.textContent = String(cmds.length);
              // The bar says what ran LAST, which is what someone glancing at a shut
              // pane is looking for.
              cmdsum.textContent = (cmds[cmds.length - 1] || {}).display || '';
              cmdrows.textContent = '';
              // NEWEST FIRST, like the actions column. The record stays chronological;
              // the reversal is a presentation decision and is made here.
              for (var i = cmds.length - 1; i >= 0; i--) {
                var c = cmds[i];
                var row = el('div', 'cmd ' + (c.state || 'ok'));
                if (openCmds[c.id]) row.classList.add('open');
                row.setAttribute('data-cmd', c.id);

                var head = el('div', 'chead');
                head.appendChild(el('span', 'cdot'));
                head.appendChild(el('span', 'cdisp', c.display || ''));
                head.appendChild(el('span', 'cms', ms(c.elapsed_ms)));
                row.appendChild(head);

                // The first line of stderr, shown whether or not the row is open.
                if (c.state === 'failed') {
                  var why = String(c.stderr || '').split('\\n')[0]
                         || String(c.stdout || '').split('\\n')[0]
                         || ('exit ' + c.exit_code);
                  row.appendChild(el('div', 'cwhy', why));
                }

                var body = el('div', 'cbody');
                if (c.cwd) body.appendChild(el('div', 'ccwd', c.cwd));
                if (c.stdout) {
                  body.appendChild(el('div', 'clab', 'output'));
                  body.appendChild(el('pre', 'cout', c.stdout));
                }
                if (c.stderr) {
                  body.appendChild(el('div', 'clab', 'errors'));
                  body.appendChild(el('pre', 'cerr', c.stderr));
                }
                if (!c.stdout && !c.stderr) {
                  body.appendChild(el('div', 'clab',
                    c.exit_code === 0 ? 'finished without printing anything'
                                      : 'exit ' + c.exit_code + ', nothing on either stream'));
                }
                if (c.truncated) {
                  body.appendChild(el('div', 'ccut',
                    'output truncated — this is not all of it'));
                }
                row.appendChild(body);
                cmdrows.appendChild(row);
              }
            }

            // ---- the explanations pane --------------------------------------------
            var exprows = document.getElementById('exprows');
            var expcount = document.getElementById('expcount');
            var expsum = document.getElementById('expsum');
            var pexps = document.getElementById('pexps');

            function renderExplanations(exps) {
              if (!exprows || !pexps) return;
              if (!exps.length) { pexps.classList.add('idle'); return; }
              pexps.classList.remove('idle');
              expcount.textContent = String(exps.length);
              expsum.textContent = (exps[exps.length - 1] || {}).title || '';
              exprows.textContent = '';
              for (var i = exps.length - 1; i >= 0; i--) {
                var e = exps[i];
                var box = el('div', 'exp');
                box.setAttribute('data-turn', e.turn_id || '');
                box.appendChild(el('div', 'etitle', e.title || ''));
                var blocks = e.blocks || [];
                for (var j = 0; j < blocks.length; j++) {
                  var b = blocks[j];
                  if (b.kind === 'text') {
                    box.appendChild(el('p', 'btext', b.text || ''));
                  } else if (b.kind === 'list') {
                    var ul = el('ul', 'blist');
                    var items = b.items || [];
                    for (var k = 0; k < items.length; k++) ul.appendChild(el('li', '', items[k]));
                    box.appendChild(ul);
                  } else if (b.kind === 'code') {
                    var wrap = el('div', 'bcodewrap');
                    if (b.lang) wrap.appendChild(el('div', 'blang', b.lang));
                    wrap.appendChild(el('pre', 'bcode', b.text || ''));
                    // FOUR THINGS THE OWNER CAN DO WITH A COMMAND VESPER WROTE.
                    //
                    // RUN IS ALWAYS A DELIBERATE CLICK. No keyboard shortcut, no
                    // enter-to-run, no run-on-expand -- and the command is rendered in
                    // full above, never elided, because the owner has to be able to
                    // read what they are about to execute. A truncated command with a
                    // Run button beside it is the one arrangement this must not have.
                    //
                    // Only for shells. A python block is code to read, not a line to
                    // hand to zsh, and a Run button on one would be an invitation to
                    // paste a program into a prompt.
                    var lang = String(b.lang || '').toLowerCase();
                    if (lang === 'bash' || lang === 'sh' || lang === 'zsh'
                        || lang === 'shell' || lang === 'console') {
                      var bar = el('div', 'cmdbar');
                      var mk = function (label, attr, cls) {
                        var btn = el('button', cls || '', label);
                        btn.setAttribute(attr, b.text || '');
                        bar.appendChild(btn);
                      };
                      mk('run', 'data-run', 'run');
                      mk('paste', 'data-paste');
                      mk('ask vesper', 'data-ask');
                      mk('copy', 'data-copycmd');
                      wrap.appendChild(bar);
                    }
                    box.appendChild(wrap);
                  } else {
                    // SAID OUT LOUD RATHER THAN DROPPED. A kind this page does not know
                    // how to draw is a partial explanation, and a partial one that
                    // looks complete is worse than a visible gap.
                    box.appendChild(el('p', 'bskip',
                      'a part of this explanation is in a form this surface cannot '
                      + 'draw yet (' + String(b.kind) + ')'));
                  }
                }
                exprows.appendChild(box);
              }
            }

            // ---- the changed files ------------------------------------------------
            var chgrows = document.getElementById('chgrows');
            var chgcount = document.getElementById('chgcount');
            var chgsum = document.getElementById('chgsum');
            var pchgs = document.getElementById('pchgs');
            var openChgs = Object.create(null);
            // THE VIEW SURVIVES A RE-RENDER, like the open rows above: the state push
            // rebuilds this list every 700 ms and a filter that reset itself within
            // the second would be unusable. Per-viewer and per-session, which is what
            // `localStorage` is for -- and it is wrapped, because a webview can refuse
            // it and a card that throws is worse than one that forgets.
            var chgView = {show: 'all', sort: 'recent'};
            try {
              var stored = localStorage.getItem('vesper.chgView');
              if (stored) chgView = JSON.parse(stored);
            } catch (e) {}
            function saveView() {
              try { localStorage.setItem('vesper.chgView', JSON.stringify(chgView)); }
              catch (e) {}
            }
            var lastChanges = [];

            // A DIFF IS COLOURED BY ITS GUTTER CHARACTER, and the character stays.
            // Colour alone fails for anyone who cannot separate these two hues, and
            // the +/- is already the first thing on every line.
            function paintDiff(pre, text) {
              pre.textContent = '';
              var rows = String(text || '').split('\\n');
              for (var i = 0; i < rows.length; i++) {
                var line = rows[i];
                var cls = line.charAt(0) === '+' ? 'a'
                        : line.charAt(0) === '-' ? 'r'
                        : line.charAt(0) === '@' ? 'h' : '';
                // +++ and --- are the file headers, not an addition and a deletion.
                if (line.indexOf('+++') === 0 || line.indexOf('---') === 0) cls = 'h';
                pre.appendChild(el('span', cls, line + '\\n'));
              }
            }

            function sortChanges(rows) {
              var out = rows.slice();
              if (chgView.sort === 'path') {
                out.sort(function (a, b) { return (a.path || '') < (b.path || '') ? -1 : 1; });
              } else if (chgView.sort === 'size') {
                out.sort(function (a, b) {
                  return ((b.added || 0) + (b.removed || 0)) - ((a.added || 0) + (a.removed || 0));
                });
              }
              // 'recent' is the order the runtime published, which is the order things
              // happened. Re-deriving it from a timestamp here would be a second
              // opinion about an ordering the record already has.
              return out;
            }

            function renderChanges(payload) {
              if (!chgrows || !pchgs) return;
              var rows = (payload && payload.changes) || [];
              lastChanges = rows;
              if (!rows.length) { pchgs.classList.add('idle'); return; }
              pchgs.classList.remove('idle');
              var shown = rows.filter(function (c) {
                return chgView.show === 'all' || c.source === chgView.show;
              });
              chgcount.textContent = String(shown.length)
                + (shown.length !== rows.length ? ' of ' + rows.length : '');
              chgsum.textContent = shown.length ? (shown[0].name || '') : 'nothing shown';
              // The controls reflect the view they are controlling.
              var segs = document.querySelectorAll('#chgshow button, #chgsort button');
              for (var s = 0; s < segs.length; s++) {
                var k = segs[s].getAttribute('data-show') || segs[s].getAttribute('data-sort');
                var mine = segs[s].hasAttribute('data-show') ? chgView.show : chgView.sort;
                segs[s].classList.toggle('on', k === mine);
              }
              chgrows.textContent = '';
              var list = sortChanges(shown);
              for (var i = 0; i < list.length; i++) {
                var c = list[i];
                var row = el('div', 'chg');
                row.setAttribute('data-src', c.source || '');
                row.setAttribute('data-status', c.status || '');
                row.setAttribute('data-path', c.path || '');
                if (openChgs[c.path]) row.classList.add('open');
                var head = el('div', 'dhead');
                head.appendChild(el('span', 'dsrc', c.source === 'vesper' ? 'vesper' : 'git'));
                // The PATH, not just the name: two files called `index.html` are the
                // whole reason a list like this becomes useless. `direction:rtl` keeps
                // the filename visible when the middle is elided.
                head.appendChild(el('span', 'dpath', c.path || ''));
                head.appendChild(el('span', 'dstat', c.status || ''));
                if (c.added) head.appendChild(el('span', 'dadd', '+' + c.added));
                if (c.removed) head.appendChild(el('span', 'drem', '−' + c.removed));
                row.appendChild(head);

                var body = el('div', 'dbody');
                var bar = el('div', 'drow');
                var ide = el('button', 'gbtn', 'open in editor');
                ide.setAttribute('data-open', c.path || '');
                bar.appendChild(ide);
                var cp = el('button', 'gbtn', 'copy diff');
                cp.setAttribute('data-copy', c.path || '');
                bar.appendChild(cp);
                body.appendChild(bar);
                if (c.binary) {
                  body.appendChild(el('div', 'ccut',
                    'a binary file — changed, and there is no diff to show'));
                } else if (c.hunks) {
                  var pre = el('pre', 'dhunks');
                  paintDiff(pre, c.hunks);
                  body.appendChild(pre);
                } else {
                  body.appendChild(el('div', 'ccut', 'no textual difference'));
                }
                if (c.truncated) {
                  body.appendChild(el('div', 'ccut',
                    'diff truncated — this is not all of it'));
                }
                row.appendChild(body);
                chgrows.appendChild(row);
              }
              // A ROW GIT HAS NEVER HEARD OF CANNOT BE PUSHED. Disabled rather than
              // hidden, so the buttons stay where the owner left them.
              var anyGit = rows.some(function (c) { return c.in_repo; });
              var gb = document.querySelectorAll('.gbtn[data-git]');
              for (var g = 0; g < gb.length; g++) gb[g].disabled = !anyGit;
            }

            // EVERY FLAG, IN ONE PLACE. The owner's design, 2026-09-09: a small bar
            // above the main menu, buttons revealing the flag on hover.
            //
            // NEVER innerHTML -- a flag carries a window title, an application name and
            // a system error string, all of them content VESPER did not write.
            // NO STAMP, NO ROW: a flag with no text is not rendered as an empty button,
            // because a control that reveals nothing on hover is indistinguishable from
            // one that is broken.
            window.__vesperFlags = function (json) {
              var bar = document.getElementById('flagbar');
              var host = document.getElementById('flags');
              var tip = document.getElementById('flag-tip');
              if (!bar || !host || !tip) return;
              var list;
              try { list = JSON.parse(json); } catch (e) { return; }
              if (!Array.isArray(list)) list = [];
              var rows = list.filter(function (f) {
                return f && typeof f.text === 'string' && f.text.length > 0;
              });
              var sig = JSON.stringify(rows.map(function (f) {
                return [f.id, f.text, f.carried ? 1 : 0];
              }));
              if (sig === window.__vesperFlagSig) return;
              window.__vesperFlagSig = sig;
              while (host.firstChild && host.firstChild !== tip) host.removeChild(host.firstChild);
              if (!rows.length) { bar.hidden = true; tip.hidden = true; return; }
              bar.hidden = false;
              // THE WIDTH IS MEASURED FROM THE MAIN MENU, EVERY RENDER.
              //
              // The owner's constraint is "not bigger than the main menu", and the menu's
              // width is its CONTENT's width -- `.dockrow` is left:0;right:0 and centres
              // what it holds. So it is read from the menu's own rectangle rather than
              // copied as a number, and re-read each time because the menu's width
              // changes with the icons in it and with the display.
              var dock = document.querySelector('.dockrow');
              if (dock) {
                var w = Math.round(dock.getBoundingClientRect().width);
                // A MENU THAT HAS NOT LAID OUT YET MEASURES 0, and capping the bar at 0
                // would hide every flag while reporting none of that. Below a floor the
                // measurement is not believed and the fallback stands.
                if (w > 120) document.documentElement.style.setProperty('--flagbar-max', w + 'px');
              }
              rows.forEach(function (f) {
                var b = document.createElement('button');
                b.type = 'button';
                // A FLAG CARRIED ACROSS A RESTART SAYS SO. It was raised by a process
                // that is gone, and nothing has re-proved it since -- which is not the
                // same as a flag raised by something that just happened. Both are shown;
                // only one of them can claim to be current.
                var words = f.carried
                  ? f.text + '  (raised before the last restart; not re-checked since)'
                  : f.text;
                if (f.carried) b.classList.add('carried');
                b.setAttribute('aria-label', words);
                // THE TITLE IS THE FLAG'S OWN FIRST CLAUSE, not a category name. Flag
                // text is written as a sentence about what is wrong, so its opening reads
                // as a title already -- inventing a separate short name would be a second
                // string to keep true.
                b.textContent = String(f.title || f.text).split(/[:.\\u2014]/)[0].trim().slice(0, 48);
                var show = function () { tip.textContent = words; tip.hidden = false; };
                var hide = function () { tip.hidden = true; };
                b.addEventListener('pointerenter', show);
                b.addEventListener('focus', show);
                b.addEventListener('pointerleave', hide);
                b.addEventListener('blur', hide);
                host.insertBefore(b, tip);
              });
              // CLICKING THE BAR OPENS THE HISTORY, which is what the owner asked for.
              // Bound on the CONTAINER rather than on each chip, so a click anywhere on
              // the bar opens it -- including the gaps, which is where a pointer lands
              // when the chips are narrow.
              host.onclick = function () { window.__vesperFlagHistory(); };
            };

            // ---- settings (§11.6) -------------------------------------------------
            //
            // READ-ONLY, AND THAT IS A DESIGN DECISION RATHER THAN AN UNFINISHED ONE.
            // Most of what the owner routed here are GOVERNED CONTRACTS:
            // `host_actions.toml` says in its own header that enabling a row is "a
            // governed act, not a configuration tweak", and `governed_surfaces.toml`
            // names who reviews each file. A toggle next to `enabled = false` would route
            // around every one of those reviews from a button -- and the gates would stay
            // green, because the file they read would have been edited by something the
            // owner approved once.
            //
            // So each governed row says WHERE it is changed. The rows that are genuinely
            // the owner's own preference are marked `governed: false` by the producer and
            // are the ones that can become editable.
            window.__vesperSettings = function (json) {
              var panel = document.getElementById('settings');
              if (!panel) return;
              if (json !== undefined) { window.__vesperSettingsData = json; return; }
              if (!panel.hidden) { panel.hidden = true; return; }
              var list;
              try { list = JSON.parse(window.__vesperSettingsData || '[]'); } catch (e) { list = []; }
              if (!Array.isArray(list)) list = [];
              while (panel.firstChild) panel.removeChild(panel.firstChild);
              var h = document.createElement('h3');
              h.textContent = 'settings';
              panel.appendChild(h);
              var sub = document.createElement('p');
              sub.className = 'st-sub';
              var known = list.filter(function (r) { return r && r.status === 'available'; }).length;
              // THE COUNT IS STATED, INCLUDING THE PART THAT IS NOT READ. A surface that
              // shows nineteen values and stays quiet about fifteen absences is claiming
              // completeness it does not have.
              sub.textContent = list.length
                ? known + ' of ' + list.length + ' read a real value \\u2014 hover any row for what it is'
                : 'nothing has been read yet';
              panel.appendChild(sub);
              list.forEach(function (r) {
                if (!r || typeof r.name !== 'string') return;
                var row = document.createElement('div');
                row.className = 'st-row';
                row.tabIndex = 0;
                row.setAttribute('data-available', String(r.status === 'available'));
                var left = document.createElement('div');
                var nm = document.createElement('div');
                nm.className = 'st-name';
                nm.textContent = r.name;
                var what = document.createElement('div');
                what.className = 'st-what';
                what.textContent = String(r.what || '');
                if (r.status !== 'available' && r.reason) {
                  what.textContent += '  \\u2014 ' + r.reason;
                } else if (r.governed && r.change_by) {
                  what.textContent += '  \\u2014 changed by ' + r.change_by;
                }
                left.appendChild(nm); left.appendChild(what);
                var right = document.createElement('div');
                var val = document.createElement('div');
                val.className = 'st-value';
                val.textContent = r.status === 'available' ? String(r.value) : 'UNAVAILABLE';
                right.appendChild(val);
                var ctl = (window.__vesperSettingControls || function () { return null; })(r);
                if (ctl) right.appendChild(ctl);
                if (r.status === 'available' && r.source) {
                  var srcEl = document.createElement('div');
                  srcEl.className = 'st-source';
                  srcEl.textContent = String(r.source);
                  right.appendChild(srcEl);
                }
                var gov = document.createElement('div');
                gov.className = 'st-gov';
                gov.textContent = r.governed ? 'governed' : 'yours to set';
                right.appendChild(gov);
                row.appendChild(left); row.appendChild(right);
                panel.appendChild(row);
              });
              panel.hidden = false;
              var esc = function (ev) {
                if (ev.key !== 'Escape') return;
                panel.hidden = true;
                document.removeEventListener('keydown', esc, true);
              };
              document.addEventListener('keydown', esc, true);
            };

            // ---- the flag history -------------------------------------------------
            //
            // THREE STATES, NOT A BOOLEAN, and the third is the one with a choice in it.
            // `open` is live, `resolved` stopped being true and says when, and
            // `carried`/`unproven` was raised by a process that is gone and has NOT been
            // re-proved -- neither fixed nor confirmed broken. Collapsing that into
            // either answer would assert something no measurement supports.
            //
            // "ASK VESPER TO FIX IT" IS A REQUEST, NEVER AN EXECUTION. The button sends a
            // TURN through the same channel a typed message uses, so the request climbs
            // the authorization ladder like anything else. A button that dispatched the
            // fix directly would be a path where text vesper READ off a failing thing
            // reaches an action with no ladder in front of it -- and flag text is written
            // by whatever failed, including applications and web pages.
            window.__vesperFlagHistory = function (json) {
              var panel = document.getElementById('flaghist');
              if (!panel) return;
              if (json !== undefined) { window.__vesperFlagHistData = json; return; }
              if (!panel.hidden) { panel.hidden = true; return; }
              var list;
              try { list = JSON.parse(window.__vesperFlagHistData || '[]'); } catch (e) { list = []; }
              if (!Array.isArray(list)) list = [];
              while (panel.firstChild) panel.removeChild(panel.firstChild);
              var h = document.createElement('h4');
              h.textContent = list.length ? 'flags — newest last' : 'no flags recorded yet';
              panel.appendChild(h);
              list.forEach(function (row) {
                if (!row || typeof row.text !== 'string') return;
                var wrap = document.createElement('div');
                wrap.className = 'fh-row';
                var when = document.createElement('div');
                when.className = 'fh-when';
                // THE CLOCK IS PRESENTATION. The rows are ordered as they were appended;
                // INV-COORD-4 refuses a sort keyed on wall time, and this only PRINTS it.
                var t = Number(row.resolved_at_s || row.last_at_s || row.at_s || 0);
                when.textContent = t ? new Date(t * 1000).toLocaleTimeString([], {
                  hour: '2-digit', minute: '2-digit'}) : '--:--';
                var what = document.createElement('div');
                what.className = 'fh-what';
                var line = document.createElement('div');
                line.textContent = row.text;
                what.appendChild(line);
                if (Number(row.seen || 1) > 1) {
                  var again = document.createElement('div');
                  again.className = 'fh-when';
                  again.textContent = 'seen ' + row.seen + ' times';
                  what.appendChild(again);
                }
                if (row.state !== 'resolved') {
                  var fix = document.createElement('button');
                  fix.type = 'button';
                  fix.className = 'fh-fix';
                  fix.textContent = 'ask vesper to fix this';
                  fix.onclick = function (ev) {
                    ev.stopPropagation();
                    try {
                      window.webkit.messageHandlers.vesperSay.postMessage(
                        'about this flag, is it a real problem and can you fix it: ' + row.text);
                      fix.textContent = 'asked';
                      fix.disabled = true;
                    } catch (e) { fix.textContent = 'could not ask'; }
                  };
                  what.appendChild(fix);
                }
                var st = document.createElement('div');
                st.className = 'fh-state fh-' + (row.state || 'open');
                st.textContent = row.state || 'open';
                wrap.appendChild(when); wrap.appendChild(what); wrap.appendChild(st);
                panel.appendChild(wrap);
              });
              panel.hidden = false;
              // CLOSABLE BY ESCAPE AND BY CLICKING AWAY. A panel that only closes by
              // clicking the thing that opened it is a panel the owner has to remember
              // how to dismiss, and this one covers the surface it sits on.
              var away = function (ev) {
                if (panel.hidden) return;
                if (panel.contains(ev.target)) return;
                var bar = document.getElementById('flags');
                if (bar && bar.contains(ev.target)) return;   // the bar toggles itself
                panel.hidden = true;
                document.removeEventListener('pointerdown', away, true);
              };
              document.addEventListener('pointerdown', away, true);
              var esc = function (ev) {
                if (ev.key !== 'Escape') return;
                panel.hidden = true;
                document.removeEventListener('keydown', esc, true);
              };
              document.addEventListener('keydown', esc, true);
            };

            window.__vesperChanges = function (json) {
              var payload;
              try { payload = JSON.parse(json); } catch (e) { return; }
              renderChanges(payload);
            };

            // ---- the owner's terminal ---------------------------------------------
            //
            // THE ONE RULE: `termInput` is the only function that posts `input`, and
            // it is called from exactly two gestures -- a keypress in the field below,
            // and a click on a Run button. Paste does NOT call it and has no bridge at
            // all: it writes to the input element and returns, so there is no path
            // from a command VESPER wrote to the shell without the owner pressing
            // something. Nothing in the state push touches any of this.
            var tout = document.getElementById('tout');
            var tin = document.getElementById('tin');
            var pterm = document.getElementById('pterm');
            // Bounded scrollback. A `find /` left running would otherwise grow the DOM
            // until the surface stops painting.
            var TERM_MAX_CHARS = 60000;
            var termSeenAlt = false;

            function termSend(payload) {
              try { window.webkit.messageHandlers.vesperTerm.postMessage(payload); }
              catch (e) {}
            }
            function termInput(text) {
              // THE PAGE PRINTS THE LINE, ONCE, because the shell no longer echoes it
              // -- see TerminalBridge.swift for why. Printed in VESPER's own prompt
              // colour so what the owner asked and what came back are told apart by
              // the design rather than by guessing.
              var shown = String(text).replace(/\\n$/, '');
              if (shown) appendTerm('\\n› ' + shown + '\\n', 'c33');
              termSend({kind: 'input', text: text});
              if (tout) tout.scrollTop = tout.scrollHeight;
            }
            // EXPOSED FOR THE OFFSCREEN PROBE, and it is the SAME function the keydown
            // handler calls -- a probe with its own private path to the shell would
            // verify a path that does not ship.
            window.termInputForProbe = termInput;

            // A SMALL ANSI RENDERER, deliberately. It handles what a shell session
            // actually emits between prompts -- SGR colour, carriage return, backspace
            // -- and DECLINES the rest. A full-screen program repaints with cursor
            // addressing this does not implement, so rather than showing the owner a
            // scrambled screen and letting them work out why, the pane says so once.
            var termBuf = '';
            var sgr = '';
            function termWrite(text) {
              if (!tout) return;
              if (!termSeenAlt && /\\x1b\\[\\?1049[hl]/.test(text)) {
                termSeenAlt = true;
                appendTerm('\\n[this pane draws line output, not full-screen programs — '
                         + 'vim, htop and less will not paint correctly here]\\n', 'c33');
              }
              var i = 0, plain = '';
              while (i < text.length) {
                var ch = text.charAt(i);
                if (ch === '\\x1b') {
                  // `?` AND `>` BELONG IN THE PARAMETER PART. Without them the
                  // private-mode sequences a shell emits constantly -- bracketed
                  // paste is `ESC [ ? 2 0 0 4 h` -- fail to match, fall through to
                  // the two-character skip below, and the page prints `?2004h` as
                  // text. Measured on the first real command this pane ever ran.
                  var m = /^\\x1b\\[([?>!0-9;]*)([A-Za-z])/.exec(text.slice(i));
                  if (m) {
                    var priv = /^[?>!]/.test(m[1]);
                    if (m[2] === 'm' && !priv) {
                      if (plain) { appendTerm(plain, sgr); plain = ''; }
                      sgr = sgrClass(m[1]);
                    } else if (m[2] === 'K' && !priv) {
                      // erase-to-end-of-line: drop the tail of the current line
                      if (plain) { appendTerm(plain, sgr); plain = ''; }
                      trimCurrentLine();
                    } else if (m[2] === 'C' && !priv) {
                      // CURSOR FORWARD, RENDERED AS SPACES. Dropping it entirely is
                      // what split the shell's own echo across three lines on the
                      // first real command: zsh's line editor redraws with cursor
                      // moves, and a renderer that keeps the text and discards the
                      // positioning turns one line into several.
                      plain += " ".repeat(Math.min(parseInt(m[1] || "1", 10) || 1, 200));
                    } else if (m[2] === 'D' && !priv) {
                      var back = Math.min(parseInt(m[1] || "1", 10) || 1, 200);
                      for (var bk = 0; bk < back; bk++) {
                        if (plain) plain = plain.slice(0, -1); else backspaceTerm();
                      }
                    }
                    i += m[0].length;
                    continue;
                  }
                  // An escape this renderer does not implement is DROPPED, not shown.
                  // Printing the raw bytes is how a terminal pane fills with `[?2004h`.
                  var m2 = /^\\x1b[\\]P^_].*?(\\x07|\\x1b\\\\)/.exec(text.slice(i));
                  i += m2 ? m2[0].length : 2;
                  continue;
                }
                if (ch === '\\r') {
                  if (plain) { appendTerm(plain, sgr); plain = ''; }
                  trimCurrentLine();
                  i++;
                  continue;
                }
                if (ch === '\\b') {
                  if (plain) { plain = plain.slice(0, -1); }
                  else { backspaceTerm(); }
                  i++;
                  continue;
                }
                if (ch === '\\x07') { i++; continue; }      // the bell is not a glyph
                plain += ch;
                i++;
              }
              if (plain) appendTerm(plain, sgr);
              tout.scrollTop = tout.scrollHeight;
            }
            function sgrClass(codes) {
              var out = '';
              var parts = String(codes || '0').split(';');
              for (var i = 0; i < parts.length; i++) {
                var n = parseInt(parts[i], 10);
                if (n === 0) out = '';
                else if (n === 1) out += ' bold';
                else if ((n >= 30 && n <= 37) || (n >= 90 && n <= 97)) out += ' c' + n;
              }
              return out.trim();
            }
            function appendTerm(text, cls) {
              var span = document.createElement('span');
              if (cls) span.className = cls;
              span.textContent = text;                 // NEVER innerHTML: this is a shell
              tout.appendChild(span);
              while (tout.textContent.length > TERM_MAX_CHARS && tout.firstChild) {
                tout.removeChild(tout.firstChild);
              }
            }
            function trimCurrentLine() {
              // Remove trailing text back to the last newline, which is what \\r and
              // erase-to-end-of-line both mean for a line-oriented renderer.
              while (tout.lastChild) {
                var t = tout.lastChild.textContent || '';
                var nl = t.lastIndexOf('\\n');
                if (nl >= 0) { tout.lastChild.textContent = t.slice(0, nl + 1); return; }
                tout.removeChild(tout.lastChild);
              }
            }
            function backspaceTerm() {
              if (!tout.lastChild) return;
              var t = tout.lastChild.textContent || '';
              if (t.length > 1) tout.lastChild.textContent = t.slice(0, -1);
              else tout.removeChild(tout.lastChild);
            }
            window.__vesperTermOut = function (text) { termWrite(String(text)); };

            if (tin) {
              tin.addEventListener('keydown', function (ev) {
                // GESTURE ONE. The owner typed a line and pressed return.
                if (ev.key === 'Enter') {
                  termInput(tin.value + '\\n');
                  tin.value = '';
                  ev.preventDefault();
                } else if (ev.key === 'c' && ev.ctrlKey) {
                  termInput('\\x03');
                  ev.preventDefault();
                } else if (ev.key === 'd' && ev.ctrlKey) {
                  termInput('\\x04');
                  ev.preventDefault();
                } else if (ev.key === 'Tab') {
                  termInput(tin.value + '\\t');
                  ev.preventDefault();
                }
              });
              tin.addEventListener('focus', focusVesper);
            }

            // Opened lazily: no shell is spawned until the owner opens the pane, so a
            // home that sits on the Desktop all day is not also a login shell all day.
            function termOpen() {
              termSend({kind: 'open'});
              if (tout) {
                var cw = 7.0, ch = 17.0;                 // the mono face's box at 11.5px
                termSend({kind: 'resize',
                          cols: Math.max(20, Math.floor(tout.clientWidth / cw)),
                          rows: Math.max(6, Math.floor(tout.clientHeight / ch))});
              }
              try { tin.focus(); } catch (e) {}
            }
            window.termOpenForProbe = termOpen;

            // THE CONNECTION, AND IT IS KEYED ON THE TURN. Clicking a line VESPER said
            // opens its explanation and lights it; clicking an explanation lights the
            // line. Pairing them by "the newest of each" would be right until the first
            // turn that produces one and not the other.
            function lightTurn(turn, openPane) {
              if (!turn) return;
              var was = document.querySelectorAll('.lit');
              for (var i = 0; i < was.length; i++) was[i].classList.remove('lit');
              var hits = document.querySelectorAll('[data-turn="' + turn + '"]');
              for (var j = 0; j < hits.length; j++) hits[j].classList.add('lit');
              if (openPane && pexps && !pexps.classList.contains('idle')) {
                var panes = document.querySelectorAll('.pane');
                for (var k = 0; k < panes.length; k++) panes[k].classList.remove('open');
                pexps.classList.add('open');
                var target = exprows.querySelector('[data-turn="' + turn + '"]');
                if (target && target.scrollIntoView) target.scrollIntoView({block: 'nearest'});
              }
            }

            // VESPER IS AN ACCESSORY APP, so a click does not make it active on its
            // own and the field beside these cards stays untypable without this. Every
            // handler below calls it for the same reason the history bar always has.
            // ONE OPEN AT A TIME, in one place. The column is short enough that two
            // open panes are two unreadable ones.
            function openPane(id) {
              var panes = document.querySelectorAll('.pane');
              for (var i = 0; i < panes.length; i++) panes[i].classList.remove('open');
              var pane = document.getElementById(id);
              if (pane) pane.classList.add('open');
            }

            function focusVesper() {
              try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
            }

            function act(payload) {
              try { window.webkit.messageHandlers.vesperAct.postMessage(payload); }
              catch (e) {}
            }

            // PUSH, PULL AND CREATE CONFIRM FIRST, AND THE CONFIRMATION NAMES THE
            // COMMAND. These are outward-facing and hard to reverse. The first click
            // asks Swift what it WOULD run -- the real remote, the real branch, read
            // out of git rather than guessed -- and puts that on the button; the
            // second click, within the window below, runs it.
            var armed = {op: '', until: 0, says: ''};
            var ARM_MS = 8000;
            function onGit(btn) {
              var op = btn.getAttribute('data-git');
              var now = Date.now();
              if (armed.op === op && now < armed.until) {
                var msg = '';
                if (op === 'commit') {
                  var field = document.getElementById('cmsg');
                  msg = field ? field.value : '';
                }
                act({kind: 'git', op: op, confirm: true, message: msg});
                disarm();
                return;
              }
              disarm();
              armed = {op: op, until: now + ARM_MS, says: ''};
              btn.classList.add('arm');
              btn.textContent = 'asking…';
              if (op === 'commit') showCommitField();
              act({kind: 'git', op: op, confirm: false,
                   message: (document.getElementById('cmsg') || {}).value || ''});
              setTimeout(function () { if (armed.op === op) disarm(); }, ARM_MS);
            }
            function disarm() {
              armed = {op: '', until: 0, says: ''};
              var gb = document.querySelectorAll('.gbtn[data-git]');
              for (var i = 0; i < gb.length; i++) {
                gb[i].classList.remove('arm');
                gb[i].textContent = gb[i].getAttribute('data-git') === 'commit'
                  ? 'create' : gb[i].getAttribute('data-git');
              }
              var f = document.getElementById('cmsgwrap');
              if (f) f.remove();
            }
            function showCommitField() {
              if (document.getElementById('cmsgwrap')) return;
              var wrap = el('div', 'drow');
              wrap.id = 'cmsgwrap';
              var inp = document.createElement('input');
              inp.id = 'cmsg';
              inp.type = 'text';
              inp.placeholder = 'what this commit does';
              inp.setAttribute('autocomplete', 'off');
              inp.style.cssText = 'flex:1;background:rgba(0,0,0,.24);border:1px solid '
                + 'rgba(255,255,255,.13);border-radius:9px;padding:6px 10px;'
                + 'color:rgba(244,230,220,.86);font-family:inherit;font-size:11.5px;'
                + 'outline:none';
              wrap.appendChild(inp);
              var body = document.getElementById('chgbody');
              if (body) body.insertBefore(wrap, document.getElementById('chgrows'));
              try { inp.focus(); } catch (e) {}
            }

            // WHAT SWIFT SAYS CAME BACK, ON THE BUTTON. A button that does its work in
            // silence is a button the owner presses twice -- and the second press of a
            // push is not free.
            window.__vesperActResult = function (json) {
              var res;
              try { res = JSON.parse(json); } catch (e) { return; }
              var line = String(res.says || '');
              if (res.kind === 'git') {
                var btn = document.querySelector('.gbtn[data-git="' + res.op + '"]');
                if (btn) {
                  btn.textContent = res.armed ? (line + '  — again to run') : line;
                  btn.classList.toggle('arm', !!res.armed);
                  if (!res.armed) setTimeout(disarm, 4000);
                }
                if (!res.armed) armed = {op: '', until: 0, says: ''};
                return;
              }
              var sum = document.getElementById('chgsum');
              if (sum) {
                var was = sum.textContent;
                sum.textContent = line;
                setTimeout(function () { sum.textContent = was; }, 2200);
              }
            };

            // ONE DELEGATED LISTENER, ON A CONTAINER THAT IS NEVER REPLACED. Attaching
            // a handler per row would attach a new set every 700 ms to elements the
            // next tick discards, which leaks for as long as VESPER is running.
            document.addEventListener('click', function (ev) {
              var head = ev.target.closest ? ev.target.closest('.phead') : null;
              if (head) {
                var id = head.getAttribute('data-pane');
                var pane = document.getElementById(id);
                if (!pane) return;
                var wasOpen = pane.classList.contains('open');
                // ONE OPEN AT A TIME. The column is short enough that two open panes
                // are two unreadable ones.
                var panes = document.querySelectorAll('.pane');
                for (var i = 0; i < panes.length; i++) panes[i].classList.remove('open');
                if (!wasOpen) {
                  pane.classList.add('open');
                  // THE SHELL STARTS WHEN THE PANE DOES, not when the home does.
                  if (id === 'pterm') setTimeout(termOpen, 60);
                }
                // Focus first: VESPER is an accessory app, so a click does not make it
                // active on its own and the field beside it stays untypable without
                // this. Same reason the history bar does it.
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
                return;
              }
              // ---- a command VESPER wrote --------------------------------------
              var runb = ev.target.closest ? ev.target.closest('[data-run]') : null;
              if (runb) {
                openPane('pterm');
                setTimeout(termOpen, 60);
                // GESTURE TWO, and the only other one. See TerminalBridge.swift.
                setTimeout(function () {
                  termInput(runb.getAttribute('data-run') + '\\n');
                }, 220);
                focusVesper();
                return;
              }
              var pasteb = ev.target.closest ? ev.target.closest('[data-paste]') : null;
              if (pasteb) {
                // PASTE HAS NO BRIDGE. It writes to an input element and returns;
                // there is no function anywhere that could carry this to the shell.
                openPane('pterm');
                setTimeout(termOpen, 60);
                setTimeout(function () {
                  if (tin) { tin.value = pasteb.getAttribute('data-paste'); tin.focus(); }
                }, 220);
                focusVesper();
                return;
              }
              var askb = ev.target.closest ? ev.target.closest('[data-ask]') : null;
              if (askb) {
                try {
                  window.webkit.messageHandlers.vesperSay.postMessage(
                    'about this command: ' + askb.getAttribute('data-ask'));
                } catch (e) {}
                focusVesper();
                return;
              }
              var copyc = ev.target.closest ? ev.target.closest('[data-copycmd]') : null;
              if (copyc) {
                act({kind: 'copy', text: copyc.getAttribute('data-copycmd')});
                focusVesper();
                return;
              }

              // ---- the changes card's controls and buttons -----------------------
              var seg = ev.target.closest ? ev.target.closest('.seg button') : null;
              if (seg) {
                if (seg.hasAttribute('data-show')) chgView.show = seg.getAttribute('data-show');
                else chgView.sort = seg.getAttribute('data-sort');
                saveView();
                renderChanges({changes: lastChanges});
                focusVesper();
                return;
              }
              var opener = ev.target.closest ? ev.target.closest('[data-open]') : null;
              if (opener) {
                act({kind: 'open', path: opener.getAttribute('data-open')});
                focusVesper();
                return;
              }
              var copier = ev.target.closest ? ev.target.closest('[data-copy]') : null;
              if (copier) {
                var want = copier.getAttribute('data-copy');
                for (var ci = 0; ci < lastChanges.length; ci++) {
                  if (lastChanges[ci].path === want) {
                    act({kind: 'copy', text: lastChanges[ci].hunks || ''});
                    break;
                  }
                }
                focusVesper();
                return;
              }
              var gb = ev.target.closest ? ev.target.closest('.gbtn[data-git]') : null;
              if (gb) {
                onGit(gb);
                focusVesper();
                return;
              }
              var dhead = ev.target.closest ? ev.target.closest('.dhead') : null;
              if (dhead) {
                var crow = dhead.parentNode;
                var cp = crow.getAttribute('data-path');
                if (openChgs[cp]) { delete openChgs[cp]; crow.classList.remove('open'); }
                else { openChgs[cp] = true; crow.classList.add('open'); }
                focusVesper();
                return;
              }
              var exp = ev.target.closest ? ev.target.closest('.exp') : null;
              if (exp) { lightTurn(exp.getAttribute('data-turn'), false); return; }
              var hrow = ev.target.closest ? ev.target.closest('.hrow') : null;
              if (hrow && hrow.getAttribute('data-turn')) {
                lightTurn(hrow.getAttribute('data-turn'), true);
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
                return;
              }
              var chead = ev.target.closest ? ev.target.closest('.chead') : null;
              if (chead) {
                var rowEl = chead.parentNode;
                var cid = rowEl.getAttribute('data-cmd');
                if (!cid) return;
                if (openCmds[cid]) { delete openCmds[cid]; rowEl.classList.remove('open'); }
                else { openCmds[cid] = true; rowEl.classList.add('open'); }
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
              }
            });

            // The history bar. Collapsed it shows the OLDEST line, which is what makes
            // it a way back into the conversation rather than a duplicate of the card.
            var lastJSON = '';
            window.__vesperHistory = function (json) {
              if (json === lastJSON) return;
              lastJSON = json;
              var rows;
              try { rows = JSON.parse(json); } catch (e) { return; }
              if (!rows.length) {
                hrows.innerHTML = '<div class="hrow"><span class="hwho">—</span>'
                                + '<span class="htext" style="opacity:.4">'
                                + 'nothing said yet</span></div>';
                return;
              }
              // THE LINE ON STAGE IS NOT REPEATED UNDERNEATH IT. The stage shows the
              // newest line and this list showed every line INCLUDING that one, so
              // every reply appeared twice in a row under one "vesper" label -- which
              // is what the owner kept seeing and reported on 2026-09-04. The card and
              // the log are two views of one conversation, not two conversations.
              if (rows.length > 1 && window.__stageText
                  && rows[0] && rows[0].text === window.__stageText) {
                rows = rows.slice(1);
              }
              var html = '';
              for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                var cue = (i === 0 && rows.length > 1)
                  ? '<span class="hcue">' + (rows.length - 1) + ' more</span>' : '';
                html += '<div class="hrow"><span class="hwho">'
                     + (r.who === 'vesper' ? 'vesper' : 'you') + '</span>'
                     + '<span class="htext"></span>' + cue + '</div>';
              }
              hrows.innerHTML = html;
              // TEXT SET AS textContent, NEVER AS MARKUP. These lines carry a model's
              // output, and the day one contains a tag is the day that stops being
              // theoretical.
              var cells = hrows.querySelectorAll('.htext');
              for (var j = 0; j < rows.length; j++) cells[j].textContent = rows[j].text;
              // THE TURN ID RIDES THE ROW so a reply can find its explanation, and it
              // is set through the DOM rather than interpolated into the markup above.
              //
              // THE FIRST VERSION INTERPOLATED IT AND SANITISED IT ON THE WAY IN --
              // which is correct for markup and silently broke the link: an HLC is
              // `<ms>.<counter>@<node>`, the filter dropped the `@`, and the row's id
              // no longer equalled the explanation's. Everything rendered, nothing
              // matched, and no error was raised anywhere. Set as a property, the
              // value is never markup, needs no filter, and cannot be altered on the
              // way to the attribute.
              var hcells = hrows.querySelectorAll('.hrow');
              for (var k = 0; k < rows.length; k++) {
                hcells[k].setAttribute('data-turn', String(rows[k].id || ''));
              }
            };

            if (hist) {
              hist.addEventListener('click', function () {
                // Focus first: VESPER is an accessory app and a click does not make it
                // active on its own, so without this the expand works and the field
                // beside it still cannot be typed into.
                try { window.webkit.messageHandlers.vesperFocus.postMessage('1'); } catch (e) {}
                hist.classList.toggle('open');
              });
            }
          })();
        </script>
        """
    }

    /// Load the markup: repo first for a live loop, bundle second, inline last.
    ///
    /// WHY THE REPO PATH IS TRIED FIRST, and why that is not a hazard in a
    /// shipped build. Every CSS change cost a 19-second `swiftc` rebuild while
    /// this markup was a string literal, and iteration speed is what actually
    /// limits how good a surface looks -- a designer at 19 s per attempt
    /// produces worse work than the same designer at one second, whatever
    /// renderer is underneath. A shipped copy has no repo beside it, so the
    /// branch simply does not fire; an installed VESPER reads its own bundle.
    static func template() -> Template {
        let fm = FileManager.default
        let devPath = URL(fileURLWithPath: fm.currentDirectoryPath)
            .appendingPathComponent("app/home-macos/chrome/home.html")
        if let s = try? String(contentsOf: devPath, encoding: .utf8), !s.isEmpty {
            return Template(source: s, origin: "repo:\(devPath.path)")
        }
        if let u = Bundle.main.url(forResource: "home", withExtension: "html"),
           let s = try? String(contentsOf: u, encoding: .utf8), !s.isEmpty {
            return Template(source: s, origin: "bundle")
        }
        return Template(source: fallbackTemplate(), origin: "inline-fallback")
    }

    /// Mount the chrome over `host`, but only if the glass is actually clear.
    ///
    /// `onVerdict` is called with the guard's answer either way, so a refusal is
    /// reported rather than being a chrome that quietly never appeared.
    private(set) var cardBackdropLuma = 0.0
    private(set) var cardFill = 0.0
    private(set) var cardAdapted = false

    static var pushFailures = 0
    static var pushCount = 0
    private let bridge = SayBridge()
    private let acts = ActBridge()
    private let term = TerminalBridge()
    private let control = ControlBridge()

    /// What the page last reported about VESPER's own delivery, for the host's
    /// render tick. `(level, isDriven)` -- and `isDriven` is not redundant with
    /// a zero level: a real sentence passes through zero at every word boundary,
    /// and a face that dropped its source on each of those would stutter.
    /// The behaviour this tick read out of `home.json`, for the host that owns
    /// the face. Optional because the chrome runs in contexts with no renderer
    /// behind it -- `--chrome` over a bare field, and the verify probes.
    var onFaceBehaviour: ((String) -> Void)?

    var speech: (level: Float, isDriven: Bool) {
        (bridge.speechLevel, bridge.speechIsFromText)
    }
    private var refresh: Timer?

    /// Push the runtime's state into the live page.
    ///
    /// PUSHED FROM SWIFT RATHER THAN FETCHED BY THE PAGE. The page is loaded
    /// from a string with no base URL, so it has no origin and cannot read a
    /// file -- and giving it one so it could would hand a surface the ability
    /// to read the disk, which is a much larger thing than a transcript needs.
    ///
    /// RE-RENDERS ONLY WHAT CHANGED. Reloading the page each tick would clear
    /// the field the owner is typing into, which is the one thing the loop must
    /// not do. So it writes the transcript's innerHTML and the body's face
    /// attribute and touches nothing else.
    ///
    /// 700 ms, not faster. This is a status surface, not an animation -- the
    /// FACE animates continuously in Metal below, driven by its own driver at
    /// frame rate, and this only tells it which behaviour to hold. SPIKE-013's
    /// cost table is why: the composite already costs +0.053% of one core, and
    /// a JS evaluation four times a second buys nothing a person can perceive.
    /// Ask the page what it painted. Not what it was told to paint.
    static func reportStage(_ w: WKWebView) {
        let js = """
        (function(){
          function d(sel){
            var e = document.querySelector(sel);
            if (!e) return sel + ': ABSENT';
            var r = e.getBoundingClientRect();
            var s = getComputedStyle(e);
            return sel + ': "' + (e.textContent||'').trim().slice(0,42) + '"'
                 + ' box=' + Math.round(r.x) + ',' + Math.round(r.y)
                 + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)
                 + ' opacity=' + s.opacity + ' display=' + s.display
                 + ' vis=' + s.visibility;
          }
          // THE PANES, FROM THE SURFACE THAT IS ACTUALLY MOUNTED. §9r: the
          // offscreen probe answered this question about a page the app never
          // builds, and was believed over the owner. `idle` is read from the
          // class the renderer sets AND the height the layout gave it, because
          // a pane can carry the right class and still be given no room.
          function p(id){
            var e = document.getElementById(id);
            if (!e) return id + ':ABSENT';
            var h = Math.round(e.getBoundingClientRect().height);
            return id + ':' + (e.classList.contains('idle') ? 'idle' : 'SHOWN') + '/' + h;
          }
          var panes = ['pcmds','pexps','pchgs','pterm','work']
                        .map(p).join(' ');
          // THE HOST CARD'S PAINTED ROW COUNT, not its receiver's existence.
          // `Metrics:fn` above says only that the function is defined, and
          // `jsErrors=none` says only that nothing threw -- neither can tell
          // an empty card from a full one, and on 2026-09-08 this card was
          // both rendering four MENU readings as host telemetry and dropping
          // its own absences. An adjacent signal standing in for the one you
          // need is the same defect as asserting on a layer nobody renders.
          var mEl = document.getElementById('metrics');
          var metrics = mEl ? mEl.children.length + ':'
              + Array.prototype.map.call(mEl.children, function (c) {
                  var k = c.querySelector('.k');
                  return k ? k.textContent : '?'; }).join(',')
            : 'ABSENT';
          // AND THE MENU, FROM THE SAME MOUNTED WEBVIEW (codex/menus-v2, merged
          // 2026-09-13). Two readbacks, both kept: `metrics=` is the HOST card's
          // painted rows, `menu=` is the instrument list's state.
          // Read the menu from THIS mounted webview on the real push tick.
          // Counts in a reconstructed DOM missed the previous regression.
          // Bound the report to catalogue capacity and read actual visibility,
          // focus, expanded rows and text; no renderer-supplied success flag.
          var menu = document.getElementById('menu-panel');
          var menuRows = menu ? Array.from(menu.querySelectorAll('.menu-reading')).slice(0,51) : [];
          function painted(e) {
            var r = e.getBoundingClientRect(), s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.display !== 'none'
                && s.visibility !== 'hidden' && Number(s.opacity) > 0;
          }
          var menuState = menu ? {
            open: menu.open, view: menu.dataset.view, painted: painted(menu),
            title: (menu.querySelector('h2') || {}).textContent,
            rows: menuRows.length,
            matched: menuRows.filter(function(e){ return !e.hidden; }).map(function(e){ return e.dataset.item; }),
            visible: menuRows.filter(function(e){
              var r = e.getBoundingClientRect(), box = menu.getBoundingClientRect();
              return painted(e) && r.bottom > box.top && r.top < box.bottom
                && r.right > box.left && r.left < box.right;
            }).map(function(e){ return e.dataset.item; }),
            expanded: menuRows.filter(function(e){ return e.open; }).map(function(e){ return e.dataset.item; }),
            detailLimit: 8,
            details: menuRows.filter(function(e){ return e.open; }).slice(0,8).map(function(e){
              return {id: e.dataset.item,
                value: (e.querySelector('.menu-reading-value').textContent || '').slice(0,160),
                reason: (e.querySelector('.menu-reason').textContent || '').slice(0,500)};
            }),
            current: menuRows.filter(function(e){ return e.dataset.available === 'true'; }).length,
            missingReasons: menuRows.filter(function(e){ return e.dataset.available === 'false'
              && !(e.querySelector('.menu-reason').textContent || '').trim(); }).map(function(e){ return e.dataset.item; }),
            result: (menu.querySelector('.menu-results') || {}).textContent,
            search: (menu.querySelector('.menu-search') || {}).value,
            filters: Array.from(menu.querySelectorAll('.menu-filters select')).map(function(e){ return e.value; }),
            back: !!menu.querySelector('.menu-back:not([hidden])'),
            focus: document.activeElement ? document.activeElement.tagName : '',
            scroll: menu.scrollTop,
            fits: menu.getBoundingClientRect().left >= 0 && menu.getBoundingClientRect().right <= window.innerWidth
              && menu.getBoundingClientRect().top >= 0 && menu.getBoundingClientRect().bottom <= window.innerHeight
          } : {missing: true};
          var errs = (window.__vesperErrs || []);
          // DO THE RECEIVERS EXIST AT ALL? `if (window.__vesperWork)` skips
          // silently when they do not, which looks identical to a push that
          // worked and rendered nothing -- §9r's whole failure in one line.
          var recv = ['__vesperStage','__vesperHistory','__vesperWork',
                      '__vesperChanges','__vesperMetrics','__vesperFlags',
                      '__vesperFlagHistory','__vesperSettings','__vesperRail']
                     .map(function(n){ return n.replace('__vesper','')
                        + ':' + (typeof window[n] === 'function' ? 'fn' : 'MISSING'); })
                     .join(',');
          return [d('#stage'), d('.field'), d('#say'), 'recv=[' + recv + ']',
                  'viewport=' + window.innerWidth + 'x' + window.innerHeight,
                  'face=' + document.body.getAttribute('data-face'),
                  'panes=[' + panes + ']',
                  'metrics=[' + metrics + ']',
                  'menu=' + JSON.stringify(menuState),
                  'jsErrors=' + (errs.length ? JSON.stringify(errs.slice(0,3)) : 'none')
                 ].join(' | ');
        })();
        """
        w.evaluateJavaScript(js) { val, err in
            if let err { print("chrome: stage READBACK failed: \(err)") }
            else { print("chrome: READBACK \(val ?? "nil")") }
        }
    }

    func startRefresh() {
        refresh?.invalidate()
        // 0.25 s, DOWN FROM 0.7 s. Together with the runtime's own poll this
        // was up to 1.2 s of transport around a model call that now returns in
        // well under a second -- the plumbing was the slower half of the
        // conversation, and it was the half nobody had measured because the
        // provider was always blamed first. Each tick reads one small JSON file
        // and evaluates a string; the composite cost recorded in §0.5 is
        // +0.053% of one core, and this multiplies that term by 2.8, not the
        // window's whole cost.
        let timer = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in
            guard let self, let w = self.web else { return }
            let face = Self.faceBehaviour()
            // AND THE FACE ITSELF, WHICH HAD NEVER BEEN TOLD.
            //
            // This tick has read the behaviour out of `home.json` since it was
            // written, and pushed it into the PAGE -- where it drives a status
            // dot. `FaceDriver.behaviour` was set by nothing anywhere in this
            // app: it defaulted to `.resting` and stayed there for the process's
            // whole life. `core/home_state.py` derived the behaviour correctly,
            // the file carried it correctly, the dot showed it correctly, and
            // the face was resting through every request VESPER ever answered.
            //
            // Built-and-unreached, again, and this time it silently invalidated
            // an entire feature: the scale and brightness channels added for
            // thinking and talking all live on `behaviour`, so none of them had
            // ever run.
            //
            // REUSING THIS POLL rather than adding a second one. One mechanism,
            // one register -- a second timer reading the same file is how the
            // two come to disagree.
            self.onFaceBehaviour?(face)
            let (line, who) = Self.stageLine()
            let metSafe = Self.metricsJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let chgSafe = Self.changesJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let workSafe = Self.workbenchJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let flagSafe = Self.flagsJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let flagHistSafe = Self.flagHistoryJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            func esc(_ v: String) -> String {
                v.replacingOccurrences(of: "\\", with: "\\\\")
                 .replacingOccurrences(of: "`", with: "\\`")
                 .replacingOccurrences(of: "$", with: "\\$")
            }
            let projSafe = esc(Self.railJSON("projects"))
            let resSafe = esc(Self.railJSON("research"))
            // §28. The dashboard is a DICT rather than a list, which railJSON
            // serialises just as happily; the page reads `panels` off it and shows
            // UNAVAILABLE when the producer has not run.
            let dashSafe = esc(Self.railJSON("project_dashboard"))
            // The main menu's seventeen cards (core/menu_cards.py): rows,
            // borrowed settings rows and actions, keyed by destination id.
            let cardsSafe = esc(Self.railJSON("menu_cards"))
            // The projects and research boards (core/boards.py).
            let boardsSafe = esc(Self.railJSON("boards"))
            let setSafe = Self.settingsJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let histSafe = Self.historyJSON()
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let safe = line
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "`", with: "\\`")
                .replacingOccurrences(of: "$", with: "\\$")
            let js = """
            (function(){
              // EACH RECEIVER GUARDED SEPARATELY, and the failure NAMED.
              //
              // §9r: these five were one unguarded sequence, so a throw in an
              // early one silently killed every later one -- and the block
              // still reported "push OK" because the throw was caught nowhere
              // a reader looks. That is the shape that cost a night: the
              // owner's cards stopped rendering and every instrument said the
              // push had succeeded. A receiver that fails now says WHICH one.
              function step(name, fn) {
                try { fn(); }
                catch (e) {
                  window.__vesperErrs = window.__vesperErrs || [];
                  if (window.__vesperErrs.length <= 20) {
                    window.__vesperErrs.push('receiver ' + name + ': '
                      + ((e && e.message) ? e.message : String(e)));
                  }
                }
              }
              document.body.setAttribute('data-face', '\(face)');
              step('stage',   function(){ if (window.__vesperStage) window.__vesperStage(`\(safe)`, '\(who)'); });
              step('history', function(){ if (window.__vesperHistory) window.__vesperHistory(`\(histSafe)`); });
              step('work',    function(){ if (window.__vesperWork) window.__vesperWork(`\(workSafe)`); });
              step('changes', function(){ if (window.__vesperChanges) window.__vesperChanges(`\(chgSafe)`); });
              step('metrics', function(){ if (window.__vesperMetrics) window.__vesperMetrics(`\(metSafe)`); });
              step('flags',   function(){ if (window.__vesperFlags) window.__vesperFlags(`\(flagSafe)`); });
              // THE HISTORY IS HANDED OVER, NOT RENDERED. Passing it with an
              // argument stores it; the panel is drawn only when the owner clicks
              // the bar, so a poll every second does not rebuild a panel nobody
              // opened -- and does not close one they are reading.
              step('flaghist', function(){ if (window.__vesperFlagHistory) window.__vesperFlagHistory(`\(flagHistSafe)`); });
              step('settings', function(){ if (window.__vesperSettings) window.__vesperSettings(`\(setSafe)`); });
              step('projects', function(){ if (window.__vesperRail) window.__vesperRail('projects', `\(projSafe)`); });
              step('research', function(){ if (window.__vesperRail) window.__vesperRail('research', `\(resSafe)`); });
              step('dashboard', function(){ if (window.__vesperRail) window.__vesperRail('dashboard', `\(dashSafe)`); });
              step('cards',     function(){ if (window.__vesperCards) window.__vesperCards(`\(cardsSafe)`); });
              step('boards',    function(){ if (window.__vesperRail) window.__vesperRail('boards', `\(boardsSafe)`); });
              // AND IT RETURNS SOMETHING WebKit CAN CARRY BACK. An IIFE whose
              // completion value is `undefined` is handed to the completion
              // handler as WKError "JavaScript execution returned a result of an
              // unsupported type" -- measured twice in 1 800 pushes on this
              // machine (island.out, 2026-09-15). Nothing was wrong with the
              // push: every receiver had run. The owner's log said FAILED
              // anyway, which is the same class of defect as a silent success
              // and costs the next reader the same hour.
              return true;
            })();
            """
            // REPORT WHAT THE PUSH DID. `completionHandler: nil` swallowed
            // every JavaScript error: a throw inside the injected snippet --
            // an undefined function, a bad template literal -- left the page
            // unchanged and said nothing, which is indistinguishable from a
            // timer that never fired. The whole pipeline can be working and
            // the surface still show nothing, which is exactly what happened.
            w.evaluateJavaScript(js) { _, err in
                if let err {
                    Self.pushFailures += 1
                    if Self.pushFailures <= 3 {
                        print("chrome: stage push FAILED: \(err)")
                    }
                } else {
                    // PERIODIC, NOT ONCE. A single readback at mount goes stale
                    // the moment anything changes, and it then describes a
                    // layout that no longer exists -- which is worse than no
                    // readback, because it reads like current evidence. Every
                    // 40th push is roughly every 28 s.
                    Self.pushCount += 1
                    if Self.pushCount == 1 || Self.pushCount % 40 == 0 {
                        print("chrome: stage push OK (#\(Self.pushCount))")
                    // READ THE WORLD AFTER ACTING. "push OK" only means the
                    // snippet did not throw; it says nothing about whether a
                    // glyph is on screen. A stage that is empty, transparent,
                    // zero-height or positioned off the display would report
                    // exactly the same success. So the PAGE is asked what it
                    // actually rendered -- text, box and opacity -- which is
                    // the closest thing to looking at it available without a
                    // screen-recording grant.
                        // WHAT WAS ACTUALLY PUSHED, not what the file holds.
                        // §9r: the panes reported idle while home.json plainly
                        // carried the data, so the only remaining question is
                        // whether the string this tick SENT carried it too.
                        print("chrome: pushed workbench \(workSafe.count) B"
                            + " commands=\(workSafe.contains("\"commands\""))"
                            + " thoughts=\(workSafe.contains("\"thoughts\""))"
                            + " | rows \(metSafe.count) B"
                            + " | transcript \(histSafe.count) B")
                        Self.reportStage(w)
                    }
                }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        refresh = timer
    }

    func stopRefresh() { refresh?.invalidate(); refresh = nil }

    func mount(over host: NSView, faceRect: CGRect, screen: NSScreen,
               backdrop: URL?,
               onVerdict: @escaping (GlassGuard.Verdict) -> Void) {
        GlassGuard.verify { [weak self] verdict in
            // ONVERDICT FIRES LAST ON THE SUCCESS PATH, and it has to. Called
            // first, it ran before the card had been solved and reported the
            // struct's defaults -- "backdrop UNSAMPLED, unadapted" -- for a
            // card that was adapting correctly. The same shape as the phantom
            // dropout §2.2 records: a sampler started before the thing it
            // samples exists reads a world that does not contain it yet.
            guard let self, verdict.mayMountChrome else { onVerdict(verdict); return }

            // The page's only way to reach anything. Registered on the
            // configuration BEFORE the view exists, because a handler added
            // afterwards is not visible to a page that has already loaded.
            let cfg = WKWebViewConfiguration()
            // THE ERROR TRAP, INSTALLED BEFORE THE PAGE'S OWN SCRIPTS RUN.
            //
            // §9r: an entire night was spent concluding, wrongly and out loud,
            // that a merge had not broken the stack cards -- because every
            // instrument used mounted its OWN webview and fired ONE push, which
            // is a different question from "is the surface the owner is looking
            // at rendering". The receivers here swallow their own failures by
            // design (`try { JSON.parse } catch (e) { return; }`) and the push
            // block is one evaluated string, so a throw in an early receiver
            // silently kills every later one and still reports "push OK".
            //
            // AT documentStart, NOT AFTER LOAD. A handler added once the page
            // has parsed cannot see a syntax or execution error raised while it
            // was parsing, which is exactly the failure worth catching.
            let trap = WKUserScript(source: """
                window.__vesperErrs = [];
                window.addEventListener('error', function (e) {
                  if (window.__vesperErrs.length > 20) return;
                  window.__vesperErrs.push((e.message || '?')
                    + ' @' + (e.lineno || '?') + ':' + (e.colno || '?'));
                }, true);
                """, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            cfg.userContentController.addUserScript(trap)
            cfg.userContentController.add(self.bridge, name: SayBridge.name)
            cfg.userContentController.add(self.bridge, name: SayBridge.focusName)
            cfg.userContentController.add(self.bridge, name: SayBridge.speakingName)
            // The card's buttons. A SEPARATE handler from `SayBridge`, because
            // these ask the machine to do things and that channel must be
            // readable on its own -- see ActBridge's header for what it will
            // and will not accept from a page.
            cfg.userContentController.add(self.acts, name: ActBridge.name)
            // The owner's shell. A THIRD handler, kept apart from the other
            // two on purpose: this one writes to a file descriptor with no
            // sandbox in front of it, and the rule that keeps that safe is
            // that only two gestures can reach it. A channel like that has to
            // be readable on its own line.
            cfg.userContentController.add(self.term, name: TerminalBridge.name)
            // The settings controls and every management button. A FOURTH
            // handler, because a management request is neither a sentence, an
            // argv nor a keystroke -- see ControlBridge's header.
            cfg.userContentController.add(self.control, name: ControlBridge.name)
            let w = WKWebView(frame: host.bounds, configuration: cfg)
            w.autoresizingMask = [.width, .height]
            GlassGuard.makeTransparent(w)
            // The chrome sits ABOVE the field. The face's Metal layer carries
            // zPosition 10 on the host's own layer, so the webview's layer has
            // to be told to go higher -- ordering between a subview's layer and
            // a directly-added sublayer is not something to leave to insertion
            // order.
            w.wantsLayer = true
            w.layer?.zPosition = 20
            host.addSubview(w)
            self.web = w
            self.acts.web = w
            self.term.web = w
            self.mounted = true

            // Left cluster: clear of the face's square, vertically centred on
            // it. Placed off the FACE rather than off the screen, so it stays
            // right when the face moves.
            let cw = 300, ch = 236
            let left = max(48, Int(faceRect.minX) - cw - 72)
            // THE RIGHT-HAND CLUSTER IS ANCHORED THE SAME WAY THE LEFT ONE IS,
            // and it was not. The HOST card has always been placed from
            // `faceRect.minX`, so it clears the face at any window size; the
            // conversation card was positioned in pure CSS as `right: 26px`
            // with a `min(38vw, 520px)` width, which knows nothing about where
            // the face is and overlapped it on this display. A viewport-derived
            // width cannot avoid an element it cannot see -- the two are only
            // ever coincidentally clear of each other.
            //
            // 40 px of gap, then the card takes whatever is left, capped in CSS
            // so it does not sprawl on a wide screen.
            let convoLeft = Int(faceRect.maxX) + 40
            let top = Int(host.bounds.height - faceRect.midY) - ch / 2
            var t = max(48, top)

            // THE WORK STACK'S ROOM IS SOLVED, NOT ASSUMED, AND THE CLUSTER
            // MOVES RATHER THAN THE PANES FALLING OFF THE BOTTOM.
            //
            // The host card is centred on the face, which on this display puts
            // its lower edge around two-thirds of the way down -- leaving the
            // panes beneath it a couple of hundred points to share with the
            // main menu. Fixed offsets would have put the last of them through
            // the floor on the first screen that was not this one, which is
            // exactly the kind of geometry this tree has had to redo before
            // (see `convoLeft`, and the card that sat over the face).
            //
            // So: the stack states the minimum it needs, and if centring the
            // card would leave less, the WHOLE left cluster moves up until it
            // fits. The floor at 158 is the work card's own minimum -- its top
            // edge is at 38 and it must keep something like 120 points to be a
            // card rather than a strip.
            let stackGap = 12
            let stackBarH = 40          // one shut pane: 13 + 13 padding + a 10px line
            let stackPanes = 4          // commands, explanations, changes, terminal
            let stackFloor = Int(host.bounds.height) - 96   // clear of the main menu
            let stackNeeds = stackPanes * stackBarH + (stackPanes - 1) * stackGap
            let deficit = (t + ch + stackGap + stackNeeds) - stackFloor
            if deficit > 0 { t = max(158, t - deficit) }
            let stackTop = t + ch + stackGap
            // NEVER NEGATIVE. A negative height is a CSS value the parser
            // discards, and a container with no height lays its children out
            // at full size over whatever is beneath them -- the panes would
            // paint across the main menu rather than not painting at all,
            // which is the harder failure to read.
            let stackHeight = max(0, stackFloor - stackTop)
            self.cardRect = CGRect(x: CGFloat(left),
                                   y: host.bounds.height - CGFloat(t + ch),
                                   width: CGFloat(cw), height: CGFloat(ch))

            // §3 step 1: sample what is behind THIS card, not the screen's
            // average. A card in the left cluster sits over a different part of
            // the picture than one on the right, and one fill for both is the
            // "unadapted" the rule exists to refuse.
            //
            // §3 step 5: an unsampleable backdrop takes the tier's nominal fill
            // and is reported unadapted rather than looking solved.
            if let backdrop,
               let st = Ambience.backdropStats(url: backdrop, region: self.cardRect,
                                               screen: screen) {
                self.cardBackdropLuma = st.mean
                self.cardFill = Self.solvedFill(backdrop: st.mean)
                self.cardAdapted = true
            } else {
                self.cardBackdropLuma = 0
                self.cardFill = 0
                self.cardAdapted = false
            }

            w.loadHTMLString(Self.page(cardWidth: cw, cardHeight: ch,
                                       left: left, top: t, convoLeft: convoLeft,
                                       stackTop: stackTop,
                                       stackHeight: stackHeight,
                                       fill: self.cardFill),
                             baseURL: nil)
            self.startRefresh()
            onVerdict(verdict)
        }
    }

    /// §10's dim. Driven from Swift because the fact lives in the window
    /// server -- the page has no way to know a system Dock is over it.
    /// Wake the web layer on the edge where the ground becomes visible again.
    ///
    /// THE FACE AND THE CHROME DO NOT RESUME ALIKE, and the owner sees the
    /// difference. The face is a Metal layer on a `CADisplayLink`; the moment
    /// the ground is revealed it is already drawing. The chrome is a WKWebView,
    /// and WebKit throttles compositing for a view in a covered window and does
    /// not hurry to undo it -- so the face is back and the cards, the main menu
    /// and the widgets arrive some time afterwards, which reads as them
    /// disappearing while the owner is away and reappearing when they return.
    ///
    /// MEASURED, AND NOT RELIABLY. `occlusion_repaint_probe` recorded 1470 ms
    /// from reveal to first paint on one run and no paint at all within 1.5 s on
    /// another -- and then 19-27 ms on five consecutive runs afterwards, with or
    /// without this call. So the slow path is real and was observed, and this
    /// fix is NOT proven to be what removes it. It is here because it is a
    /// single call on an edge that already exists, it measured no cost when
    /// recovery was already fast, and the alternative is leaving a surface the
    /// owner is looking at on WebKit's own schedule.
    ///
    /// The AppKit invalidations alone do not reach WebKit's scheduler; touching
    /// the DOM and asking the page itself for a frame is what restarts it.
    func wake() {
        guard let w = web, mounted else { return }
        w.setNeedsDisplay(w.bounds)
        // NOT `document.body.style.opacity`, WHICH IS WHAT THIS DID AND IT WAS
        // A REAL REGRESSION THE OWNER SAW WITHIN THE HOUR.
        //
        // Any opacity below 1 makes that element a BACKDROP ROOT. Every glass
        // panel in this page is `backdrop-filter: blur(24px) saturate(180%)`,
        // and a backdrop filter samples what is painted behind the element
        // WITHIN its backdrop root -- so rooting it at `body` left them
        // sampling an empty transparent page instead of the Desktop. The blur
        // had nothing to blur and the cards rendered as bare translucent fill:
        // washed out, and the text on them barely legible.
        //
        // AND IT COULD NOT UNDO ITSELF. The reset was queued in
        // `requestAnimationFrame`, which is precisely the callback WebKit does
        // not run while a view is throttled -- the exact state this function
        // exists to leave. So the page could sit rooted for as long as the
        // throttle lasted, which is the whole problem it was meant to solve,
        // now with the glass broken as well.
        //
        // A dedicated 1x1 element off the top-left corner instead: mutating it
        // forces a compositing update, it creates its own stacking context and
        // nobody's backdrop is rooted at it, and there is nothing to reset.
        w.evaluateJavaScript("""
            (function(){
              var k = document.getElementById('__wake');
              if (!k) {
                k = document.createElement('div');
                k.id = '__wake';
                k.style.cssText = 'position:fixed;left:-4px;top:-4px;width:1px;'
                                + 'height:1px;pointer-events:none;opacity:0.01';
                document.documentElement.appendChild(k);
              }
              k.style.transform = 'translateZ(0) rotate(' + (Date.now() % 360) + 'deg)';
            })();
            """, completionHandler: nil)
    }

    func setDockUp(_ up: Bool) {
        web?.evaluateJavaScript(
            "document.body.classList.toggle('dock-up', \(up))", completionHandler: nil)
    }

    func unmount() {
        web?.removeFromSuperview()
        web = nil
        mounted = false
    }
}
