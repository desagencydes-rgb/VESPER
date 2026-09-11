import AppKit
import ApplicationServices
import Foundation

/// Seeing a window's interface, and driving it (§11.5).
///
/// WHAT MAKES THIS DIFFERENT FROM EVERY OTHER BRIDGE HERE: what it reads is the
/// STRONGEST untrusted content in the system. §9 wrote the constraint down before
/// any of this existed -- *"a captured screen is `retrieved_external` of the
/// strongest kind -- it can contain any text on the machine, including another
/// app's -- so it must reach the planner through `observe()` and never raw"* --
/// and the owner ratified it on 2026-09-08 as *"permissions yes, taint stays"*.
///
/// So a label read off the screen is data. `permission_mode.NEVER_WAIVED_SOURCES`
/// names `ui.view`, which means auto mode grants VESPER every permission to ACT
/// and still refuses to let what it READ lift its ceiling. That is enforced above
/// this file; this file's job is to make sure what it hands up is bounded and
/// honestly labelled.
///
/// AN ELEMENT IS IDENTIFIED BY PATH AND CORROBORATED BY WHAT IT IS.
/// `AXUIElement` cannot be serialised and handed back later, so a click has to
/// find its target again. A bare index path is not enough: interfaces relayout,
/// and clicking "whatever is now third" is how an automation presses Delete
/// because a row appeared above it. So `view` returns the path AND the role and
/// label, `act` re-resolves the path and REFUSES when either has changed. The
/// same discipline `WindowBridge.element(forPID:windowId:)` uses when two windows
/// share geometry: refuse rather than guess.
///
/// ONE DESKTOP, MEASURED. The accessibility tree answers only for the Desktop
/// that is showing -- re-measured 2026-09-11 from inside the bundle with the
/// grant present: 2 windows reachable on the showing Desktop, 0 of 69 elsewhere.
/// There is no fallback for this one: `CGSMoveWindow` can move a window vesper
/// cannot see, but nothing can press a button vesper cannot see.
enum UIBridge {

    /// How deep the tree is walked, and why there is a limit at all.
    ///
    /// A full accessibility tree of a browser is tens of thousands of elements,
    /// and every label in it is untrusted text heading for a planner. The limit
    /// is a taint budget as much as a performance one.
    static let MAX_DEPTH = 12
    static let MAX_ELEMENTS = 400
    static let MAX_LABEL = 200

    /// The actions VESPER may perform on an element. A closed set, like the app
    /// verbs: what reaches the accessibility interface is a name the compiler
    /// knew, never a string assembled from something the planner read.
    static let ACTIONS = ["press", "focus", "type", "scroll_up", "scroll_down"]

    static func accessible() -> Bool { AXIsProcessTrusted() }

    private static func attr(_ el: AXUIElement, _ name: String) -> CFTypeRef? {
        var v: CFTypeRef?
        return AXUIElementCopyAttributeValue(el, name as CFString, &v) == .success ? v : nil
    }

    private static func str(_ el: AXUIElement, _ name: String) -> String {
        (attr(el, name) as? String) ?? ""
    }

    /// What this element is CALLED, from whichever attribute carries it.
    ///
    /// FOUR ATTRIBUTES, IN ORDER, AND THE ORDER IS THE POINT. A button's words
    /// live in `AXTitle`; a field's in `AXDescription` or its placeholder; a row's
    /// in `AXValue`. Reading only one produces a tree full of unnamed elements
    /// that VESPER cannot describe to the owner and cannot be asked to click.
    private static func label(_ el: AXUIElement) -> String {
        for name in [kAXTitleAttribute, kAXDescriptionAttribute,
                     kAXValueAttribute, "AXPlaceholderValue"] {
            let s = str(el, name as String).trimmingCharacters(in: .whitespacesAndNewlines)
            if !s.isEmpty { return String(s.prefix(MAX_LABEL)) }
        }
        return ""
    }

    private static func rect(_ el: AXUIElement) -> CGRect? {
        guard let p = attr(el, kAXPositionAttribute as String),
              let s = attr(el, kAXSizeAttribute as String) else { return nil }
        var origin = CGPoint.zero, size = CGSize.zero
        guard AXValueGetValue(p as! AXValue, .cgPoint, &origin),
              AXValueGetValue(s as! AXValue, .cgSize, &size) else { return nil }
        return CGRect(origin: origin, size: size)
    }

    /// The window element for a CGWindowID, or nil.
    ///
    /// Uses `WindowBridge`'s own matcher so there is ONE place that maps a window
    /// id to an accessibility element. A second mapping would drift from the
    /// first, and the first is the one that already refuses an ambiguous match.
    private static func windowElement(pid: Int, windowId: String) -> AXUIElement? {
        WindowBridge.elementForAct(pid: pid, windowId: windowId)
    }

    /// Describe a window's interface as a flat, bounded list.
    ///
    /// FLAT AND NOT NESTED, deliberately: the owner asks "click Send", and a list
    /// of (path, role, label) is what answers that. A nested tree is a prettier
    /// shape that the planner would have to walk, and every level of walking is
    /// another chance for untrusted text to be read as structure.
    static func view(pid: Int, windowId: String) -> [String: Any] {
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to "
                  + "VESPER, so it cannot see any window's interface"]
        }
        guard let root = windowElement(pid: pid, windowId: windowId) else {
            return ["ok": false, "reason": "that window is not on the desktop "
                  + "that is showing, and the accessibility interface only "
                  + "answers for the one that is -- come to it and ask again"]
        }
        var rows: [[String: Any]] = []
        var truncated = false

        func walk(_ el: AXUIElement, _ path: [Int], _ depth: Int) {
            if rows.count >= MAX_ELEMENTS { truncated = true; return }
            if depth > MAX_DEPTH { truncated = true; return }
            let role = str(el, kAXRoleAttribute as String)
            let name = label(el)
            let actions = availableActions(el)
            // LISTED ONLY IF IT CAN BE NAMED OR USED. A tree of anonymous groups
            // is noise that costs the planner context and tells the owner
            // nothing; an element with neither a label nor an action is
            // structure, not interface.
            if !name.isEmpty || !actions.isEmpty {
                var row: [String: Any] = ["path": path.map(String.init).joined(separator: "."),
                                          "role": role, "label": name]
                if !actions.isEmpty { row["can"] = actions }
                if let r = rect(el) {
                    row["x"] = Int(r.origin.x); row["y"] = Int(r.origin.y)
                    row["w"] = Int(r.size.width); row["h"] = Int(r.size.height)
                }
                rows.append(row)
            }
            guard let kids = attr(el, kAXChildrenAttribute as String) as? [AXUIElement]
            else { return }
            for (i, kid) in kids.enumerated() {
                walk(kid, path + [i], depth + 1)
            }
        }
        walk(root, [], 0)
        return ["ok": true, "window_id": windowId, "count": rows.count,
                "truncated": truncated, "elements": rows]
    }

    /// Which of VESPER's actions this element actually supports.
    ///
    /// ASKED OF THE ELEMENT, NOT ASSUMED FROM ITS ROLE. A role is a hint; the
    /// action list is the answer, and an element whose role looks clickable and
    /// whose action list is empty is one VESPER must not claim it can press.
    private static func availableActions(_ el: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(el, &names) == .success,
              let list = names as? [String] else { return [] }
        var out: [String] = []
        if list.contains(kAXPressAction as String) { out.append("press") }
        if str(el, kAXRoleAttribute as String) == (kAXTextFieldRole as String)
            || str(el, kAXRoleAttribute as String) == (kAXTextAreaRole as String) {
            out.append("type")
        }
        // THE CONSTANT FOR THIS ACTION IS NOT EXPOSED IN SWIFT, so the string
        // is written out. Named here rather than silently dropped: a role that
        // can be brought into view is one vesper can focus, and losing the
        // capability because a constant is missing would be a silent narrowing.
        if list.contains("AXScrollToVisible") { out.append("focus") }
        return out
    }

    /// Re-resolve a path and refuse if the element is not what it was.
    private static func resolve(root: AXUIElement, path: String,
                               expectRole: String, expectLabel: String)
        -> (AXUIElement?, String) {
        var el = root
        if !path.isEmpty {
            for part in path.split(separator: ".") {
                guard let i = Int(part),
                      let kids = attr(el, kAXChildrenAttribute as String) as? [AXUIElement],
                      i >= 0, i < kids.count else {
                    return (nil, "the interface has changed shape since it was "
                          + "read: there is nothing at that position any more")
                }
                el = kids[i]
            }
        }
        // CORROBORATED, AND THIS IS THE WHOLE SAFETY OF THE PATH SCHEME.
        // Interfaces relayout. Clicking "whatever is now at 3.1.4" is how an
        // automation presses Delete because a row appeared above the one it
        // meant. So what was read is checked against what is there, and a
        // mismatch refuses rather than proceeding.
        let role = str(el, kAXRoleAttribute as String)
        if !expectRole.isEmpty && role != expectRole {
            return (nil, "that position now holds a \(role.isEmpty ? "different element" : role) "
                  + "rather than a \(expectRole), so vesper will not touch it")
        }
        let now = label(el)
        if !expectLabel.isEmpty && now != expectLabel {
            return (nil, "that element is now labelled differently, so vesper "
                  + "will not touch it -- read the interface again")
        }
        return (el, "")
    }

    /// Perform one action on one element.
    static func act(pid: Int, windowId: String, path: String, action: String,
                    expectRole: String, expectLabel: String,
                    text: String?) -> [String: Any] {
        guard ACTIONS.contains(action) else {
            return ["ok": false, "reason": "'\(action)' is not something vesper "
                  + "does to an interface. The set is closed: absence is refusal."]
        }
        guard accessible() else {
            return ["ok": false, "reason": "accessibility is not granted to "
                  + "VESPER, so it cannot drive any interface"]
        }
        guard let root = windowElement(pid: pid, windowId: windowId) else {
            return ["ok": false, "reason": "that window is not on the desktop "
                  + "that is showing, and nothing can press a button vesper "
                  + "cannot see"]
        }
        let (found, why) = resolve(root: root, path: path,
                                  expectRole: expectRole, expectLabel: expectLabel)
        guard let el = found else { return ["ok": false, "reason": why] }

        switch action {
        case "press":
            let err = AXUIElementPerformAction(el, kAXPressAction as CFString)
            return ["ok": err == .success, "action": action,
                    "ax_error": Int(err.rawValue),
                    "reason": err == .success ? "" :
                        "the element refused the press (AXError \(err.rawValue))"]
        case "focus":
            let err = AXUIElementSetAttributeValue(
                el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            return ["ok": err == .success, "action": action,
                    "ax_error": Int(err.rawValue)]
        case "type":
            guard let text else {
                return ["ok": false, "reason": "there is no text to type"]
            }
            // SET, NOT SYNTHESISED. Writing the value goes to THIS element;
            // synthesising key events sends them wherever focus happens to be,
            // which on a machine the owner is using is not necessarily here.
            let err = AXUIElementSetAttributeValue(
                el, kAXValueAttribute as CFString, text as CFTypeRef)
            if err != .success {
                return ["ok": false, "action": action, "ax_error": Int(err.rawValue),
                        "reason": "that field would not take the text "
                                + "(AXError \(err.rawValue))"]
            }
            // RE-READ, because an instrument's self-report is not evidence: a
            // field can accept the assignment and hold something else.
            let now = str(el, kAXValueAttribute as String)
            return ["ok": now == text, "action": action, "value": now,
                    "reason": now == text ? "" :
                        "the field took the assignment and holds something else"]
        case "scroll_up", "scroll_down":
            guard let r = rect(el) else {
                return ["ok": false, "reason": "vesper cannot tell where that "
                      + "element is, so it will not scroll blindly"]
            }
            let dy: Int32 = action == "scroll_up" ? 3 : -3
            guard let ev = CGEvent(scrollWheelEvent2Source: nil, units: .line,
                                   wheelCount: 1, wheel1: dy, wheel2: 0, wheel3: 0)
            else { return ["ok": false, "reason": "the scroll event could not be made"] }
            ev.location = CGPoint(x: r.midX, y: r.midY)
            ev.post(tap: .cghidEventTap)
            // A SCROLL HAS NO ACKNOWLEDGEMENT, AND THIS SAYS SO RATHER THAN
            // CLAIMING ONE. The event is posted; whether the view moved is not
            // something the accessibility interface reports for every element,
            // so `ok` means "sent" and the field below says exactly that.
            return ["ok": true, "action": action, "verified": false,
                    "note": "the scroll was sent; scrolling has no "
                          + "acknowledgement to read back"]
        default:
            return ["ok": false, "reason": "unreachable"]
        }
    }

    static func emit(_ obj: Any) { WindowBridge.emit(obj) }
}
