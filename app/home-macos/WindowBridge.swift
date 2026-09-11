import AppKit
import ApplicationServices

// THE PLATFORM HALF OF WINDOW MANAGEMENT, AND NOTHING ELSE.
//
// `core/windows.py` decides WHICH window may be touched and `contracts/policy/
// host_actions.toml` declares WHAT may be done to one. This file knows neither.
// It enumerates and it acts, and every refusal it produces is a refusal of the
// platform -- no grant, no such window, no accessibility handle -- never a
// refusal of policy. That split is the same one the action vocabulary makes
// when its header says rows name an abstract effect and the adapter owns the
// mechanism.
//
// A HELPER IS A MODE OF THIS BINARY, NEVER A LOOSE SCRIPT. The runtime shells
// out to `VESPER --windows-list` rather than to a python or shell helper of its
// own, so everything that touches the owner's machine runs as VESPER, with
// VESPER's identity, and inherits VESPER's TCC answers rather than a terminal's.
//
// TITLES ARE NOT READ, and this is not an oversight to be corrected later.
// `SpaceWatch` already refuses `kCGWindowName` because it needs Screen
// Recording, and `host_actions.toml`'s observe tier says plainly that anything
// reading CONTENT is a new row and a new decision. A window title is a document
// name or a subject line. Enumerating windows is inventory; reading their
// titles is content, and it belongs to the UI-view decision.
enum WindowBridge {

    // Layers below zero are the system's own furniture -- the wallpaper, the
    // Dock, the menu bar shadow. `SpaceWatch.fingerprint()` counts layer 0
    // only for the same reason: they are not windows anyone opened.
    private static func manageable(_ w: SeenWindow) -> Bool {
        w.layer == 0 && w.bounds.width > 40 && w.bounds.height > 40
    }

    /// Everything on the ACTIVE Desktop, as inventory.
    ///
    /// ONLY THE ACTIVE DESKTOP, AND THAT IS A PLATFORM LIMIT RATHER THAN A
    /// CHOICE. `CGWindowListCopyWindowInfo(.optionOnScreenOnly)` answers for
    /// the Space that is showing. There is no public call that says which Space
    /// an off-screen window is on. The private route exists and lives in one
    /// reviewed place, `SpacesHatch.swift`, which is the only file permitted to
    /// name those symbols -- naming one here would make this a second carrier
    /// -- so a full cross-Desktop inventory is not available without a decision
    /// the owner has to make. Reporting the active Desktop honestly is better
    /// than reporting a partial list as though it were everything, so the
    /// payload says which Desktop it covers and the caller can say so too.
    static func list() -> [[String: Any]] {
        // EVERY DESKTOP, AND EACH WINDOW SAYS WHICH ONE IT IS ON.
        //
        // This listed only the active Desktop and then hardcoded
        // `on_active_desktop: true` for every row, so the field carried no
        // information and the ownership rule could not judge a window anywhere
        // else. That made clause 2 -- "everywhere else, provenance decides" --
        // unreachable in practice: vesper could open a window, have the system
        // place it on another Desktop, and then be told its own window "is not
        // on the active desktop, so it cannot be judged or acted on".
        //
        // A WINDOW ELSEWHERE GETS A SENTINEL, NOT A GUESS. Without the private
        // Spaces API there is no public way to name the Space a non-active
        // window sits on, so every one of them reads `desktop-elsewhere`. That
        // is honest about the limit and it is SAFE for the rule: `vespers_desktop`
        // is non-null only when vesper's ground is on the Desktop showing, so a
        // sentinel can never equal it, clause 1 cannot apply, and provenance
        // decides -- which is exactly what clause 2 says should happen. The
        // limit it does carry, stated rather than discovered: two windows on
        // two DIFFERENT non-active Desktops are indistinguishable here.
        let fp = SpaceWatch.fingerprint()
        let here = Set(SpaceWatch.onScreen().map(\.number))
        return SpaceWatch.allWindows().filter(manageable).map { w in
            [
                "window_id": String(w.number),
                "pid": w.pid,
                // THE APPLICATION NAME IS A LABEL FOR THE OWNER TO READ. It is
                // carried so a line can say "the editor on vesper's desktop",
                // and `core/windows.py` is explicit that no rule may branch on
                // it -- INV-HW-1 applied to software instead of hardware.
                "app_label": w.owner,
                "x": Int(w.bounds.origin.x), "y": Int(w.bounds.origin.y),
                "width": Int(w.bounds.width), "height": Int(w.bounds.height),
                // The active Desktop has no stable public identifier, so it is
                // named by the fingerprint that already decides Desktop
                // identity everywhere else in this app. Two reads of the same
                // Desktop agree; a switch changes it, which is the property
                // `SpaceWatch.switched` is built on.
                "desktop_id": here.contains(w.number) ? desktopId(fp)
                                                      : "desktop-elsewhere",
                "on_active_desktop": here.contains(w.number),
            ]
        }
    }

    /// Is the Desktop showing right now the one VESPER's ground is on?
    ///
    /// THIS WAS THE MOST DANGEROUS BUG IN THE FIRST DRAFT AND IT LOOKED LIKE
    /// NOTHING. The inventory reported the ACTIVE Desktop's id, and the caller
    /// passed that same id as "VESPER's Desktop" -- so every window was
    /// trivially on VESPER's Desktop, clause 1 of the ownership rule applied to
    /// all of them, and all six of the owner's windows came back as free for
    /// VESPER to arrange. The owner would have discovered it as "it moved my
    /// windows", which is exactly the trust this feature cannot afford to spend.
    ///
    /// THE ACTIVE DESKTOP IS NOT VESPER'S DESKTOP. It is only VESPER's while
    /// VESPER's ground is on it, so that is what gets checked: a window owned
    /// by this same bundle, present on the Space that is showing. The home
    /// process and this short-lived one run from one binary, so they report the
    /// same owner name -- and this process has no window of its own to be
    /// confused by.
    ///
    /// NO GROUND, NO CLAUSE 1. When VESPER holds no Desktop the answer is
    /// `null`, and `core/windows.py` then falls through to provenance for every
    /// window. That is the correct reading rather than a degraded one: there is
    /// no workspace to tidy.
    static func vespersDesktop() -> String? {
        let name = ProcessInfo.processInfo.processName
        let selfPid = Int(ProcessInfo.processInfo.processIdentifier)
        // THIS PROCESS'S OWN WINDOWS DO NOT COUNT, and leaving them in made the
        // answer always yes. `main.swift` builds a controller with a panel
        // before reaching any of these modes, so the very act of asking "is
        // VESPER's ground here" created a VESPER window on the Desktop being
        // asked about -- and it is a `.canJoinAllSpaces` panel, so it would
        // have answered yes on EVERY Desktop.
        //
        // main.swift's own header says probes go "before anything that opens a
        // window ... an instrument that disturbs the thing it measures is not
        // one". This is that rule biting the one instrument whose wrong answer
        // hands VESPER the owner's entire session.
        // AND NEITHER DOES THE ISLAND, WHICH IS THE HARDER HALF. Measured
        // 2026-09-08: with the home still WAITING for an empty Desktop and no
        // ground anywhere, this matched a VESPER window at layer 1001, 370x48
        // -- the island. It is `.canJoinAllSpaces` ON PURPOSE, which is the
        // whole point of `SpaceWatch.Anchor`'s comment that `.managed` is "NOT
        // canJoinAllSpaces -- the whole point". So the island is on EVERY
        // Desktop, and matching it would have declared every Desktop VESPER's.
        //
        // THE GROUND IS THE ONLY THING THAT MAKES A DESKTOP VESPER'S. It sits
        // BELOW the owner's windows -- `--home` describes it as "ground at
        // normal-1" -- while every piece of VESPER's chrome floats above them.
        // The sign of the layer is therefore the discriminator, and the size
        // test refuses a small stray: a ground covers the display it is on.
        let present = SpaceWatch.onScreen().contains {
            $0.owner == name && $0.pid != selfPid && $0.layer < 0
                && $0.bounds.width > 400 && $0.bounds.height > 300
        }
        return present ? desktopId() : nil
    }

    /// Where a window is, answered for EVERY Desktop rather than the showing one.
    ///
    /// WHY THIS EXISTS: THE OWNER CAUGHT A WRONG ANSWER, 2026-09-11. VESPER
    /// opened a window, reported "the system placed it on another desktop, where
    /// vesper cannot reach it", and the owner replied "no it opened in your
    /// desktop not another one". They were right.
    ///
    /// THE CAUSE IS THAT ONE ABSENCE MEANT THREE DIFFERENT THINGS.
    /// `window_open` looks its new window up in the inventory, and the inventory
    /// is `SpaceWatch.onScreen()` -- the showing Desktop only. So "not in the
    /// list" collapsed:
    ///
    ///   1. the window exists on VESPER's Desktop and is not LISTED yet (a cold
    ///      application takes longer to appear than the poll allowed),
    ///   2. the window exists on another Desktop (the only case the message
    ///      described),
    ///   3. the application never made one.
    ///
    /// All three produced the same sentence, and the first is the one that reads
    /// as a confident lie: the owner is looking straight at the window while
    /// being told it is somewhere unreachable.
    ///
    /// SO EXISTENCE AND MEMBERSHIP ARE ASKED SEPARATELY, and neither goes through
    /// the accessibility tree. `CGWindowListCopyWindowInfo` without
    /// `.optionOnScreenOnly` sees every Space; `CGSCopySpacesForWindows` says
    /// which Space a window belongs to and answers off the showing Desktop --
    /// both verified on this node.
    static func whereIs(windowId: Int) -> [String: Any] {
        let all = (CGWindowListCopyWindowInfo([.excludeDesktopElements],
                                              kCGNullWindowID)
                   as? [[String: Any]]) ?? []
        let row = all.first { ($0["kCGWindowNumber"] as? Int) == windowId }
        guard let row else {
            return ["exists": false,
                    "why": "no window with that id on any desktop"]
        }
        // VESPER'S GROUND, FOUND ACROSS EVERY SPACE. `vespersDesktop()` uses the
        // on-screen list and therefore cannot answer while VESPER's Desktop is
        // not showing -- which is exactly the situation this function is for.
        let me = ProcessInfo.processInfo.processIdentifier
        let name = ProcessInfo.processInfo.processName
        let ground = all.first {
            ($0["kCGWindowOwnerName"] as? String) == name
                && ($0["kCGWindowOwnerPID"] as? pid_t) != me
                && ($0["kCGWindowLayer"] as? Int ?? 0) < 0
        }
        var out: [String: Any] = ["exists": true]
        out["app"] = (row["kCGWindowOwnerName"] as? String) ?? ""
        let ids = [windowId] + (ground.flatMap { $0["kCGWindowNumber"] as? Int }
                                      .map { [$0] } ?? [])
        let spaces = SpacesHatch.spaces(of: ids)
        if let mine = spaces[windowId] { out["space"] = String(mine) }
        if let g = ground?["kCGWindowNumber"] as? Int, let gs = spaces[g] {
            out["vespers_space"] = String(gs)
            // THE COMPARISON IS THE ANSWER, and it is `nil` rather than `false`
            // when either side is unknown: a missing Space id is not evidence the
            // window is somewhere else, and saying so would be the same confident
            // wrong answer in a new place.
            if let mine = spaces[windowId] { out["on_vespers_desktop"] = (mine == gs) }
        } else {
            out["why"] = "vesper has no ground on any desktop, so there is no "
                       + "desktop of its own to compare against"
        }
        return out
    }

    static func desktopId(_ fp: Set<Int> = SpaceWatch.fingerprint()) -> String {
        fp.isEmpty ? "desktop-empty"
                   : "desktop-" + String(fp.sorted().map(String.init).joined(separator: "-").hashValue,
                                         radix: 36)
    }

    // MARK: - Acting

    /// Is the Accessibility grant present? Asked WITHOUT prompting.
    ///
    /// `AXIsProcessTrustedWithOptions` with the prompt option shows a dialog,
    /// and a dialog raised by a background process the owner is not looking at
    /// is a dialog they will dismiss. The runtime needs to be able to REPORT
    /// that the grant is missing -- an honest UNAVAILABLE with a reason -- which
    /// is a different thing from asking for it.
    static func accessible() -> Bool { AXIsProcessTrusted() }

    private static func element(forPID pid: Int, windowId: String) -> AXUIElement? {
        let app = AXUIElementCreateApplication(pid_t(pid))
        var value: CFTypeRef?
        // EVERY EXIT SETS THE REPORT, or the failure describes a DIFFERENT CALL.
        //
        // These two early returns left `lastMatchReport` holding whatever the
        // previous attempt wrote, so a message about Safari carried `ax=[]`
        // from an earlier window entirely -- and I spent an hour concluding
        // Safari exposed nothing to accessibility on the strength of a
        // stale sentence. An instrument that reports the last thing it saw
        // rather than the thing being asked about is worse than no instrument.
        // THE FIRST ANSWER IS NOT ALWAYS THE ANSWER.
        //
        // MEASURED 2026-09-09: Safari answers this query with an EMPTY list the
        // first time and with its real windows a moment later, so a single
        // attempt concluded that Safari exposes nothing to accessibility -- and
        // the owner was told vesper could not touch a window that was sitting
        // right there. The same shape as every other too-early read found
        // today: ask once, believe the first thing the system says, be wrong.
        var err = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString,
                                                &value)
        for _ in 0..<10 {
            if err == .success, let ws = value as? [AXUIElement], !ws.isEmpty { break }
            usleep(80_000)
            err = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString,
                                               &value)
        }
        guard err == .success else {
            lastMatchReport = "the accessibility query for pid \(pid) failed "
                            + "with AXError \(err.rawValue)"
            return nil
        }
        guard let windows = value as? [AXUIElement] else {
            lastMatchReport = "pid \(pid) answered the accessibility query with "
                            + "something that is not a window list"
            return nil
        }
        // THE ACCESSIBILITY TREE DOES NOT CARRY THE CGWindow NUMBER, so the
        // window is identified by matching geometry against the inventory that
        // was just read. That is a real weakness and it is named rather than
        // hidden: two windows of one process at identical size and position are
        // indistinguishable here, and the match is refused rather than guessed.
        // THE ACTIVE DESKTOP, AND DELIBERATELY SO.
        //
        // This was widened to `allWindows()` to let vesper act on a window
        // anywhere. It cannot: MEASURED 2026-09-09, the accessibility tree
        // answers only for the Desktop that is showing, so the wider search
        // bought nothing and cost precision. `allWindows()` passes no options
        // to `CGWindowListCopyWindowInfo`, which returns stale and non-window
        // surfaces as well as live ones -- Safari reported THREE windows while
        // that list showed SIX, two of them phantoms sharing exact geometry
        // with a real one. Since this function identifies its target by
        // geometry, those phantoms made real windows ambiguous, and the match
        // is refused rather than guessed. So the owner's window became
        // untouchable because of windows that no longer existed.
        //
        // `_act` already refuses anything not on the active Desktop, so this
        // narrower list is the same set it is allowed to act on -- and it is
        // the authoritative one.
        guard let target = SpaceWatch.onScreen().first(where: {
            String($0.number) == windowId && $0.pid == pid }) else { return nil }
        var matches: [AXUIElement] = []
        for w in windows {
            var pv: CFTypeRef?
            var sv: CFTypeRef?
            guard AXUIElementCopyAttributeValue(w, kAXPositionAttribute as CFString, &pv) == .success,
                  AXUIElementCopyAttributeValue(w, kAXSizeAttribute as CFString, &sv) == .success
            else { continue }
            var p = CGPoint.zero, s = CGSize.zero
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
            if abs(p.x - target.bounds.origin.x) < 2, abs(p.y - target.bounds.origin.y) < 2,
               abs(s.width - target.bounds.width) < 2, abs(s.height - target.bounds.height) < 2 {
                matches.append(w)
            }
        }
        // TWO WINDOWS THAT LOOK ALIKE ARE THE NORMAL CASE, NOT AN EDGE ONE.
        //
        // Two default-sized windows of one application have identical geometry,
        // and matching on geometry alone then refuses both -- so the owner's
        // second Safari window was untouchable simply for being the second.
        // Reported 2026-09-09 as "cannot resize it, move it anywhere inside its
        // desktop".
        //
        // DISAMBIGUATED BY ORDER, AND ONLY AMONG TRUE TWINS. Both lists are
        // front-to-back for a given process: `CGWindowListCopyWindowInfo` with
        // `.optionOnScreenOnly` returns front-to-back, and `kAXWindows` does
        // too. So the Nth window of this pid at this exact geometry in one list
        // is the Nth in the other. That correspondence is ASSUMED nowhere else
        // and is measured by `--ax-order-check`; if a macOS release breaks it,
        // that control goes red rather than vesper silently moving the wrong
        // window.
        //
        // NO TITLES ARE READ. `window_list` puts titles at L5 because a title
        // is content, and using one to pick between windows would be reading it
        // by another name.
        var chosen: AXUIElement? = matches.count == 1 ? matches[0] : nil
        if matches.count > 1 {
            let twins = SpaceWatch.onScreen().filter {
                $0.pid == pid
                && abs($0.bounds.origin.x - target.bounds.origin.x) < 2
                && abs($0.bounds.origin.y - target.bounds.origin.y) < 2
                && abs($0.bounds.width - target.bounds.width) < 2
                && abs($0.bounds.height - target.bounds.height) < 2
            }
            if let idx = twins.firstIndex(where: { String($0.number) == windowId }),
               idx < matches.count, twins.count == matches.count {
                chosen = matches[idx]
            }
        }
        lastMatchReport = "cg=(\(Int(target.bounds.origin.x)),\(Int(target.bounds.origin.y)) "
            + "\(Int(target.bounds.width))x\(Int(target.bounds.height))) ax=["
            + axGeometries(windows).joined(separator: " ") + "] matched=\(matches.count)"
            + (matches.count > 1 ? (chosen != nil ? " disambiguated-by-order"
                                                  : " order did not line up") : "")
        return chosen
    }

    /// What the accessibility tree says, so a failed match can be diagnosed
    /// from evidence rather than from a theory about coordinate spaces.
    static var lastMatchReport = ""

    private static func axGeometries(_ windows: [AXUIElement]) -> [String] {
        windows.compactMap { w in
            var pv: CFTypeRef?
            var sv: CFTypeRef?
            guard AXUIElementCopyAttributeValue(w, kAXPositionAttribute as CFString, &pv) == .success,
                  AXUIElementCopyAttributeValue(w, kAXSizeAttribute as CFString, &sv) == .success
            else { return nil }
            var p = CGPoint.zero, s = CGSize.zero
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
            return "(\(Int(p.x)),\(Int(p.y)) \(Int(s.width))x\(Int(s.height)))"
        }
    }

    /// Move or resize. Returns the geometry OBSERVED AFTERWARDS, never the
    /// geometry that was requested.
    ///
    /// CLAUDE.md: "an instrument's self-report is not evidence ... re-read the
    /// world after acting". `AXUIElementSetAttributeValue` returning `.success`
    /// means the message was accepted, not that the window moved -- a window
    /// can refuse a size below its minimum, or be snapped by the system, and
    /// report success either way. So the caller is handed what is true now and
    /// can compare it to what it asked for.
    static func geometry(pid: Int, windowId: String,
                         x: Int?, y: Int?, w: Int?, h: Int?) -> [String: Any] {
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to VESPER, "
                  + "so no window can be moved or resized. Grant it with "
                  + "`open -n app/VESPER.app --args --accessibility-consent`."]
        }
        guard let el = element(forPID: pid, windowId: windowId) else {
            // THE WINDOW IS NOT ON THE SHOWING DESKTOP, AND THE OWNER ASKED FOR
            // THAT CASE. "vesper should be able to open and fully manage all
            // windows in any other desktop if it was requested to do it"
            // (2026-09-11). The accessibility tree cannot serve it: MEASURED the
            // same day, it reached 2 windows on the showing Desktop and 0 of 69
            // on the others.
            //
            // SO POSITION FALLS BACK TO THE WINDOW SERVER, AND SIZE DOES NOT.
            // `CGSMoveWindow` moves a window on any Desktop; there is no
            // `CGSSetWindowBounds` on this node, and an application owns its own
            // size, so a resize genuinely cannot be served this way. Reporting a
            // move as though it had resized would be the success-shaped answer
            // this tree keeps finding, so the two are answered separately.
            //
            // AND THIS IS NOT AN AUTHORITY SHORTCUT. `core/windows.py` decides
            // WHICH windows may be touched and has already said yes before this
            // runs; what changes here is only the mechanism, not the permission.
            // The alternative -- relocating the window onto the showing Desktop
            // to make the tree answer -- is the move that file refuses outright:
            // "a rule that can be escaped by relocating the evidence is not a
            // rule."
            guard let wid = Int(windowId) else {
                return ["ok": false, "reason": noHandleReason(pid: pid, windowId: windowId)]
            }
            if w != nil || h != nil {
                return ["ok": false, "off_desktop": true,
                        "reason": "that window is on another desktop. vesper can "
                                + "MOVE it there, but resizing goes through the "
                                + "application and the application only answers "
                                + "for the desktop that is showing -- bring it "
                                + "over, or switch to that desktop, and it will "
                                + "resize"]
            }
            guard let x, let y else {
                return ["ok": false, "reason": noHandleReason(pid: pid, windowId: windowId)]
            }
            var out = SpacesHatch.moveWindow(windowId: wid,
                                            to: CGPoint(x: CGFloat(x), y: CGFloat(y)))
            out["off_desktop"] = true
            // THE ROUTE IS REPORTED, because the two paths are not equivalent:
            // the accessibility path goes THROUGH the application, so the app
            // knows its window moved; this one reaches past it to the window
            // server. A caller that cannot tell which happened cannot explain
            // the difference to the owner when an app redraws oddly.
            out["route"] = "window-server"
            return out
        }
        let before = SpaceWatch.onScreen().first { String($0.number) == windowId }
        var codes: [String] = []
        if let x, let y {
            var p = CGPoint(x: CGFloat(x), y: CGFloat(y))
            if let v = AXValueCreate(.cgPoint, &p) {
                codes.append("pos=\(AXUIElementSetAttributeValue(el, kAXPositionAttribute as CFString, v).rawValue)")
            }
        }
        if let w, let h {
            var s = CGSize(width: CGFloat(w), height: CGFloat(h))
            if let v = AXValueCreate(.cgSize, &s) {
                codes.append("size=\(AXUIElementSetAttributeValue(el, kAXSizeAttribute as CFString, v).rawValue)")
            }
        }
        // RE-READ FROM THE ACCESSIBILITY TREE, NOT FROM `CGWindowList`.
        //
        // The first version of this read the window list back and reported
        // `ok: after != nil` -- which asks only whether the window still
        // EXISTS. It returned `ok: true` on a move that plainly did not
        // happen, with `before` and `after` both at the original position,
        // because the window was of course still there. That is precisely the
        // failure CLAUDE.md names: a launcher returning 0 is not a running
        // process, and a move reporting success is not a moved window.
        //
        // `CGWindowList` was also the wrong instrument for the re-read. It is
        // a snapshot the window server updates on its own schedule, so a read
        // taken immediately after a set can legitimately still show the old
        // frame -- the answer would then depend on timing rather than on what
        // happened. The accessibility tree answers for the window itself.
        var ax = axFrame(el)
        let wantedPos = (x != nil && y != nil)
        let wantedSize = (w != nil && h != nil)
        var landed = true
        if wantedPos { landed = landed && abs(ax.origin.x - CGFloat(x!)) < 3
                                       && abs(ax.origin.y - CGFloat(y!)) < 3 }
        if wantedSize { landed = landed && abs(ax.size.width - CGFloat(w!)) < 3
                                        && abs(ax.size.height - CGFloat(h!)) < 3 }
        return ["ok": landed,
                "before": rect(before?.bounds), "after": rect(ax),
                "ax_result": codes.joined(separator: " "),
                // A WINDOW REFUSING A GEOMETRY IS NOT AN ERROR, and the
                // difference matters to whoever reads this. Applications
                // enforce minimum sizes and the system snaps to displays, so
                // "asked for 200x200, got 400x300" is the window exercising a
                // constraint it is entitled to. What must never happen is that
                // being reported as success.
                "reason": landed ? "" : "the window did not take the requested "
                    + "geometry -- it may enforce a minimum size, be full-screen, "
                    + "or be managed by the system. Asked for "
                    + (wantedPos ? "(\(x!),\(y!)) " : "")
                    + (wantedSize ? "\(w!)x\(h!) " : "")
                    + "and it is at (\(Int(ax.origin.x)),\(Int(ax.origin.y))) "
                    + "\(Int(ax.size.width))x\(Int(ax.size.height))"]
    }

    /// The window's own frame, straight from the accessibility tree.
    private static func axFrame(_ el: AXUIElement) -> CGRect {
        var pv: CFTypeRef?
        var sv: CFTypeRef?
        var p = CGPoint.zero, s = CGSize.zero
        if AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &pv) == .success {
            AXValueGetValue(pv as! AXValue, .cgPoint, &p)
        }
        if AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sv) == .success {
            AXValueGetValue(sv as! AXValue, .cgSize, &s)
        }
        return CGRect(origin: p, size: s)
    }

    /// Close a window through its own close button.
    ///
    /// `AXPress` ON THE CLOSE BUTTON, not a termination. The distinction is the
    /// whole safety story: pressing the button is what the owner clicking it
    /// would do, so an application with unsaved work gets to put up its own
    /// "save changes?" sheet. Killing the process would take the decision away
    /// from the one party entitled to make it, and `host_actions.toml` already
    /// keeps `terminate_process` disabled for that reason.
    /// Can VESPER dismiss this window if it decides to?
    ///
    /// Asked BEFORE claiming a window, because claiming one that cannot be
    /// closed leaves the owner to tidy up after VESPER -- and the whole basis
    /// for VESPER managing a window it opened is that it can also put it away.
    /// A false answer here costs one refusal; a false claim costs the owner a
    /// window they did not ask for and cannot attribute.
    /// Why a window has no accessibility handle -- and the two reasons differ.
    ///
    /// AN EMPTY TREE IS NOT AN AMBIGUOUS MATCH. Measured 2026-09-09: Safari and
    /// Music expose NO accessibility windows to vesper at all, while TextEdit,
    /// Calculator and Notes expose theirs normally. Both are Apple's, both were
    /// already running, and the difference is that the two silent ones are
    /// delivered in a CRYPTEX (`/System/Volumes/Preboot/Cryptexes/App/...`).
    /// So the honest sentence for those is that the application does not answer,
    /// not that vesper could not tell two windows apart -- and the owner can act
    /// on the first (use another application, or move the window themselves)
    /// while the second is vesper's problem to solve.
    static func noHandleReason(pid: Int, windowId: String) -> String {
        let app = NSRunningApplication(processIdentifier: pid_t(pid))
        let name = app?.localizedName ?? "that application"
        var ref: CFTypeRef?
        let axApp = AXUIElementCreateApplication(pid_t(pid))
        let ok = AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString,
                                               &ref) == .success
        let n = (ref as? [AXUIElement])?.count ?? 0
        if !ok || n == 0 {
            return "\(name) does not expose its windows to vesper. Some of "
                 + "apple's own applications -- safari and music among them -- "
                 + "refuse this, and vesper cannot move, resize or close their "
                 + "windows however they were opened. \(lastMatchReport)"
        }
        return "vesper could not tell that window apart from another of "
             + "\(name)'s at the same size and position, and will not guess "
             + "between them. \(lastMatchReport)"
    }

    static func dismissable(pid: Int, windowId: String) -> Bool {
        guard accessible(), let el = element(forPID: pid, windowId: windowId)
        else { return false }
        var btn: CFTypeRef?
        return AXUIElementCopyAttributeValue(el, kAXCloseButtonAttribute as CFString,
                                             &btn) == .success && btn != nil
    }

    static func close(pid: Int, windowId: String) -> [String: Any] {
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to VESPER"]
        }
        guard let el = element(forPID: pid, windowId: windowId) else {
            return ["ok": false, "reason": noHandleReason(pid: pid, windowId: windowId)]
        }
        // NOT EVERY WINDOW HAS A CLOSE BUTTON, and one VESPER opened itself may
        // well not. Driven 2026-09-09: `window.open("TextEdit")` on an
        // application with no documents produced TextEdit's **Open dialog** --
        // a real window, correctly attributed, titled "Open", 880x448, with no
        // close button. VESPER had opened it, could not close it, and reported
        // "this window has no close button to press" as a dead end.
        //
        // So the second rung is what a person does to a dialog: cancel it.
        // `kAXCancelAction` is the accessibility interface's own name for the
        // Escape key, which is structure rather than a keystroke aimed at
        // whatever happens to be focused.
        var btn: CFTypeRef?
        if AXUIElementCopyAttributeValue(el, kAXCloseButtonAttribute as CFString,
                                         &btn) == .success, let b = btn {
            AXUIElementPerformAction(b as! AXUIElement, kAXPressAction as CFString)
        } else if AXUIElementPerformAction(el, kAXCancelAction as CFString) != .success {
            return ["ok": false, "reason": "this window has neither a close button "
                  + "nor a cancel action, so there is no way to dismiss it that "
                  + "does not involve typing at whatever is focused"]
        }
        // RE-READ, because a modal "save changes?" sheet means the window is
        // still there and the honest answer is that it did not close.
        //
        // AND POLL, BECAUSE PRESSING IS NOT DISAPPEARING. Reading once, on the
        // line after the press, asks the window server before it has caught up.
        // Measured 2026-09-09: a Calculator window closed correctly and this
        // reported `ok: false`, because the check ran first. That is the FOURTH
        // too-early read found in one day -- the ground retraction, the window
        // list after opening, the placement readback, and this -- so the answer
        // is the same one each time: wait for the fact rather than assume how
        // long it takes to become one. A window that is still there after a
        // second really is still there, and that is the sheet case.
        var gone = false
        for _ in 0..<20 {
            if !SpaceWatch.allWindows().contains(where: { String($0.number) == windowId }) {
                gone = true
                break
            }
            usleep(50_000)
        }
        return ["ok": gone,
                "reason": gone ? "" : "the close was pressed and the window is still "
                                    + "open -- the application is likely asking the "
                                    + "owner whether to save"]
    }


    // MARK: - Relocation, and the rung below it

    /// Everything needed to REBUILD this window somewhere else if moving fails.
    ///
    /// THE OWNER'S FALLBACK, 2026-09-08: "if it's redoable, it should retry, if
    /// not it should do it manually ... identify window/app/place, then close
    /// that window and opens another one in it's desktop, same app, same
    /// place." This is the "identify" half; the orchestration is in
    /// `core/capabilities.py` because retry-then-degrade is a policy decision
    /// and this file is mechanism.
    static func identity(pid: Int, windowId: String) -> [String: Any] {
        let app = NSRunningApplication(processIdentifier: pid_t(pid))
        // EVERY DESKTOP FOR THE GEOMETRY, and a REFUSAL when there is no window.
        //
        // This read `onScreen()`, so for a window on any other Desktop `w` was
        // nil, every dimension defaulted to 0, and the call still answered
        // `ok: true`. Measured 2026-09-09: identity on five real windows
        // returned `ok:true` with `0x0 at (0,0)` for all five. A caller reading
        // `ok` was told the window had been inspected; what it got was the
        // default value of a missing optional. That is the same defect as
        // reporting a move that never happened, one layer further in.
        guard let w = SpaceWatch.allWindows().first(where: {
            String($0.number) == windowId }) else {
            return ["ok": false, "reason": "there is no window with that number "
                  + "on any desktop -- it has been closed"]
        }
        // WHETHER IT CAN BE ACTED ON AT ALL, stated rather than discovered.
        // MEASURED 2026-09-09: the accessibility tree only answers for windows
        // on the Desktop that is SHOWING. Every move, resize and close the
        // owner asked for failed with `ax=[] matched=0`, because their windows
        // were on a different Desktop from vesper's ground -- and each failure
        // was then reported to them as "done".
        let reachable = SpaceWatch.onScreen().contains { String($0.number) == windowId }
        var out: [String: Any] = [
            "ok": true,
            "reachable": reachable,
            "bundle_id": app?.bundleIdentifier ?? "",
            "app_label": app?.localizedName ?? w.owner,
            "x": Int(w.bounds.origin.x), "y": Int(w.bounds.origin.y),
            "width": Int(w.bounds.width), "height": Int(w.bounds.height),
        ]
        // UNSAVED WORK MAKES THE FALLBACK REFUSE, AND UNKNOWN COUNTS AS UNSAVED.
        //
        // The fallback CLOSES the owner's window and opens a fresh one. That is
        // safe for a window with nothing pending and destructive for one with
        // edits in it -- and `host_actions.toml` keeps `close_window`
        // deliberately outside the owner's authorisation for exactly this
        // reason. `AXDocument`-bearing windows expose an edited flag; where the
        // application does not answer, the honest reading is that we do not
        // know, and INV-HW-2's posture applies: UNKNOWN means the restrictive
        // answer, so the fallback declines rather than gambling with the
        // owner's work.
        var edited = "unknown"
        if let el = element(forPID: pid, windowId: windowId) {
            var v: CFTypeRef?
            if AXUIElementCopyAttributeValue(el, "AXModified" as CFString, &v) == .success,
               let b = v as? Bool {
                edited = b ? "yes" : "no"
            }
            var doc: CFTypeRef?
            if edited == "unknown",
               AXUIElementCopyAttributeValue(el, kAXDocumentAttribute as CFString, &doc) == .success,
               doc == nil {
                // No document at all -- a palette, an inspector, a browser
                // window. Nothing to lose by rebuilding it.
                edited = "no"
            }
        }
        out["edited"] = edited
        return out
    }

    /// Open a fresh window of the same application. The "same app" half.
    static func reopen(bundleId: String) -> [String: Any] {
        guard !bundleId.isEmpty,
              let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId)
        else { return ["ok": false, "reason": "no application to reopen for that window"] }
        // A NEW WINDOW IS ONE WITH A HIGHER NUMBER THAN ANY THAT EXISTED, AND
        // ONE BELONGING TO THE APPLICATION WE LAUNCHED. Both halves were
        // missing, and the live drive on 2026-09-09 caught what that costs:
        // `window.open("TextEdit")` returned window 101 of pid 640 -- one of
        // the owner's SAFARI windows -- stamped `vesper_opened`, which is a
        // forged claim of ownership over the owner's work. Two faults, one
        // shape. `onScreen()` sees only the ACTIVE Desktop, so when the Desktop
        // changed during the launch every window over there looked new; and
        // nothing checked WHOSE the new window was. It is the same defect as
        // the ground taking an occupied Desktop: a before/after comparison
        // across a moment when the world is free to move.
        let frontier = SpaceWatch.highWaterNumber()
        let cfg = NSWorkspace.OpenConfiguration()
        cfg.createsNewApplicationInstance = false
        // NOT ACTIVATED, AND THIS IS A SAFETY RULE RATHER THAN A PREFERENCE.
        //
        // Activating an application asks the window server to bring its windows
        // forward, which on macOS can SWITCH THE ACTIVE SPACE. That makes a
        // window-opening call able to move the owner between Desktops as a side
        // effect -- and on 2026-09-08 this ran repeatedly on the owner's live
        // machine while VESPER was deciding which Desktop to take. Whether or
        // not it caused what they saw, a call that can relocate the owner's
        // attention as a side effect of opening a window is not one VESPER
        // should be making unasked.
        cfg.activates = false
        let done = DispatchSemaphore(value: 0)
        var failed: String?
        var launched: NSRunningApplication?
        NSWorkspace.shared.openApplication(at: url, configuration: cfg) { running, err in
            launched = running
            failed = err?.localizedDescription
            done.signal()
        }
        _ = done.wait(timeout: .now() + 10)
        if let failed { return ["ok": false, "reason": failed] }
        // RE-READ FOR A WINDOW THAT WAS NOT THERE BEFORE. Activating an app
        // that is already running often opens nothing at all, and reporting
        // that as success is the same defect as reporting an unmoved window as
        // moved.
        // WITHOUT A PID THERE IS NOTHING TO VERIFY AGAINST, so the call
        // refuses rather than claiming whatever appeared.
        guard let launchedPid = launched?.processIdentifier else {
            return ["ok": false, "reason": "the application did not report a "
                  + "process, so no window could be attributed to it"]
        }
        // AND IT MUST BE A WINDOW, NOT A DIALOG THE APPLICATION THREW UP.
        //
        // Driven 2026-09-09: `window.open("TextEdit")` against an application
        // with no documents produced TextEdit's **Open panel** -- correctly
        // attributed, genuinely new, and useless. It exposes no buttons and no
        // action but `AXRaise`, so VESPER opened a window it could not close,
        // move or resize, and stamped it as its own. A window VESPER cannot
        // dismiss is not one it should claim: the request was for something to
        // put on the Desktop, and a modal asking the owner a question is not
        // that. The close button is the discriminator because it is exactly the
        // capability that was missing.
        var sawUndismissable = false
        for _ in 0..<20 {
            usleep(150_000)
            let cands = SpaceWatch.allWindows().filter {
                $0.pid == Int(launchedPid) && $0.number > frontier && $0.layer == 0
            }
            for c in cands {
                if dismissable(pid: c.pid, windowId: String(c.number)) {
                    return ["ok": true, "window_id": String(c.number), "pid": c.pid]
                }
                sawUndismissable = true
            }
        }
        // A DIALOG IS NOT A DEAD END, IT IS A REASON TO TRY THE NEXT RUNG.
        // Returning here skipped `pressNew` entirely, so an application that
        // greets a launch with its Open panel could never be asked for a real
        // document window -- and the Open panel is exactly what TextEdit does.
        // The refusal below is reached only when the menu rung fails too.
        // ACTIVATING AN APP THAT IS ALREADY RUNNING OPENS NOTHING, which is
        // correct behaviour and useless on its own. So the second rung is the
        // route a PERSON would take: the File menu's New item, pressed through
        // the accessibility interface. Public API, and it is the same action
        // the owner would perform, which is the standard §11.5 sets for
        // anything VESPER does on their behalf.
        if let fresh = pressNew(pid: Int(launchedPid), since: frontier) {
            return fresh
        }
        // THIRD RUNG: ASK THE APPLICATION ITSELF, IN ITS OWN LANGUAGE.
        //
        // Pressing File > New through the accessibility interface only works
        // while the application is FRONTMOST, and vesper deliberately launches
        // with `activates: false` because activating can drag the owner to
        // another Space. So for an application that is already running and not
        // in front -- which is every "open a new safari window here" the owner
        // has asked for -- the menu rung silently does nothing.
        //
        // MEASURED 2026-09-09: with Safari holding four windows on other
        // Desktops, launching opened nothing and File > New opened nothing,
        // while `make new document` opened a window every time. Scripting is
        // the route a person would take when the menu is out of reach, and it
        // needs no activation.
        //
        // IT DOES NOT CHOOSE THE DESKTOP EITHER. The window lands where the
        // system puts it, so the caller still reads back where it went and
        // flags it when that is not vesper's own Desktop.
        if let name = NSRunningApplication(processIdentifier: launchedPid)?
                        .localizedName, !name.isEmpty {
            let script = "tell application \"\(name)\" to make new document"
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            task.arguments = ["-e", script]
            task.standardOutput = Pipe()
            task.standardError = Pipe()
            try? task.run()
            task.waitUntilExit()
            for _ in 0..<20 {
                usleep(150_000)
                if let f = SpaceWatch.allWindows().first(where: {
                    $0.pid == Int(launchedPid) && $0.number > frontier && $0.layer == 0
                }) {
                    return ["ok": true, "window_id": String(f.number), "pid": f.pid,
                            "via": "script:new document"]
                }
            }
        }
        if sawUndismissable {
            return ["ok": false, "reason": "the application put up a dialog rather "
                  + "than opening a window, and neither its File > New nor asking "
                  + "it to make a new document produced one -- it is asking the "
                  + "owner something, and vesper will not claim a window it "
                  + "cannot close"]
        }
        return ["ok": false, "reason": "the application would not open a new window: "
              + "launching it did nothing, its File > New menu item is only "
              + "reachable while it is frontmost, and it does not answer a "
              + "request to make a new document"]
    }

    /// Press the application's own New menu item, and re-read for a window.
    ///
    /// MATCHED ON THE KEYBOARD SHORTCUT, NOT ON A TITLE OR A MENU POSITION.
    /// Two earlier attempts were wrong in the same way -- assuming structure
    /// that is really convention. The first took menu index 1 as File; the menu
    /// bar's children are Apple, then the APPLICATION menu, then File, so it
    /// was pressing something in the wrong menu entirely. The second matched
    /// titles beginning "new", which is English and French and nothing else.
    ///
    /// Command-N is New in every Mac application, in every language, and the
    /// accessibility interface reports the shortcut as data: `AXMenuItemCmdChar`
    /// is the character and `AXMenuItemCmdModifiers` is 0 for command alone.
    /// That is structure rather than wording, which is the same distinction
    /// INV-HW-1 draws between a profile and a product name.
    private static func pressNew(pid: Int, since frontier: Int) -> [String: Any]? {
        guard accessible() else { return nil }
        let app = AXUIElementCreateApplication(pid_t(pid))
        var barRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXMenuBarAttribute as CFString,
                                            &barRef) == .success,
              let bar = barRef else { return nil }
        var menusRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(bar as! AXUIElement,
                                            kAXChildrenAttribute as CFString,
                                            &menusRef) == .success,
              let menus = menusRef as? [AXUIElement] else { return nil }

        for menu in menus {
            var groupRef: CFTypeRef?
            guard AXUIElementCopyAttributeValue(menu, kAXChildrenAttribute as CFString,
                                                &groupRef) == .success,
                  let groups = groupRef as? [AXUIElement], let group = groups.first
            else { continue }
            var itemsRef: CFTypeRef?
            guard AXUIElementCopyAttributeValue(group, kAXChildrenAttribute as CFString,
                                                &itemsRef) == .success,
                  let items = itemsRef as? [AXUIElement] else { continue }
            for item in items {
                var charRef: CFTypeRef?
                var modRef: CFTypeRef?
                guard AXUIElementCopyAttributeValue(item, "AXMenuItemCmdChar" as CFString,
                                                    &charRef) == .success,
                      let ch = charRef as? String, ch.uppercased() == "N",
                      AXUIElementCopyAttributeValue(item, "AXMenuItemCmdModifiers" as CFString,
                                                    &modRef) == .success,
                      let mods = modRef as? Int, mods == 0
                else { continue }
                var titleRef: CFTypeRef?
                _ = AXUIElementCopyAttributeValue(item, kAXTitleAttribute as CFString, &titleRef)
                let title = (titleRef as? String) ?? "?"
                AXUIElementPerformAction(item, kAXPressAction as CFString)
                for _ in 0..<20 {
                    usleep(150_000)
                    // THE SAME TWO CONDITIONS. This rung already held the pid
                    // and did not consult it, so pressing New in one application
                    // could return a window that belonged to another.
                    // NO `dismissable` TEST ON THIS RUNG. What File > New
                    // produces IS a document window by construction, and adding
                    // the check here broke the rung that worked: the AX close
                    // button is not readable the instant the window appears in
                    // the window list, so the filter rejected a perfectly good
                    // window and the whole call reported that the application
                    // would not open one. The dialog problem belongs to the
                    // LAUNCH path, which is where the test stays.
                    if let f = SpaceWatch.allWindows().first(where: {
                        $0.pid == pid && $0.number > frontier && $0.layer == 0
                    }) {
                        return ["ok": true, "window_id": String(f.number), "pid": f.pid,
                                "via": "menu:\(title)"]
                    }
                }
                return nil
            }
        }
        return nil
    }

    static func relocate(windowId: String, to space: String) -> [String: Any] {
        guard let n = Int(windowId), let s = UInt64(space) else {
            return ["ok": false, "reason": "window id and space must be numeric"]
        }
        return SpacesHatch.relocate(windowId: n, to: s)
    }

    private static func rect(_ r: CGRect?) -> [String: Int] {
        guard let r else { return [:] }
        return ["x": Int(r.origin.x), "y": Int(r.origin.y),
                "width": Int(r.width), "height": Int(r.height)]
    }

    static func emit(_ obj: Any) {
        if let d = try? JSONSerialization.data(withJSONObject: obj),
           let s = String(data: d, encoding: .utf8) { print(s) }
    }
}
