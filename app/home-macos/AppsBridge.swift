import AppKit
import ApplicationServices
import Foundation

/// Driving other applications through the interface they actually expose.
///
/// WHY THIS IS NOT `NotesBridge` GENERALISED, AND WHY THAT FILE IS LEFT ALONE.
/// `NotesBridge` is an agenda SOURCE: one app, one script, read on a timer, and
/// it is gated by `CI-131`. This is a VOCABULARY -- a closed set of verbs that
/// name an effect, with the application as a runtime target. §11.4 rewrites
/// Notes on top of this; refactoring it here would mean rewriting the same file
/// twice and leaving a working agenda source broken in between.
///
/// THE VERBS ARE COMPILED IN AND THE SCRIPT IS NEVER PASSED FROM OUTSIDE.
/// This is the whole safety property of the file. If the runtime could hand
/// this code an AppleScript string, then every gate above it -- the action
/// vocabulary, `core/apps.py`, the authorisation ladder -- would be reasoning
/// about a verb name while something else entirely reached the app. Worse, the
/// planner reads untrusted text: a note body, a web page, a window title. Text
/// that reaches a planner which can compose scripts is text that can drive this
/// machine. So the argument is a verb the compiler knows and a target the
/// vocabulary allows, and there is deliberately no escape hatch.
///
/// PERMISSION IS READ BEFORE ACTING, NEVER DISCOVERED BY ACTING. Measured on
/// this node 2026-09-10: `AEDeterminePermissionToAutomateTarget` with
/// `askUserIfNeeded: false` returns a status in 30-79 ms and RAISES NO DIALOG.
/// `NotesBridge`'s comment says the opposite -- "still prompts" -- and step 10
/// therefore probed permission by sending a real Apple Event, which is the one
/// approach that cannot be used unattended: an app VESPER has never been
/// granted returns `errAEEventWouldRequireUserConsent` and macOS puts a consent
/// dialog on the owner's screen. During an autonomous run there is nobody there
/// to answer it, and the owner comes back to a modal box they did not ask for.
///
/// So an ungranted app is REFUSED, not attempted. That is what makes "auto mode
/// grants every permission" survivable: VESPER acts freely wherever the owner
/// has already granted it, and says what it needs everywhere else, instead of
/// converting its own autonomy into a queue of dialogs.
enum AppsBridge {

    // ---------------------------------------------------------------- states
    //
    // FIVE, AND THE LAST TWO ARE THE ONES THAT COST A MEASUREMENT.
    //
    // `-600` came back IDENTICALLY for `com.apple.TextEdit`, which is installed
    // and merely not running, and for `com.nonexistent.fake`, which does not
    // exist at all. The Apple Events layer cannot tell those apart, so a naive
    // reading reports "not running" about an application it has no evidence
    // exists. LaunchServices can tell them apart and also does not prompt, so
    // the two are separated here rather than collapsed.
    //
    // AND `unknown` IS NOT `denied`. An app that is not running has a
    // permission this process could not read, which `INV-HW-2` makes
    // UNAVAILABLE rather than a value. Reporting it as denied would be a
    // confident wrong answer -- the owner would be told VESPER lacks a grant it
    // may well hold -- and reporting it as granted would be worse.
    static let GRANTED = "granted"
    static let DENIED = "denied"
    static let NEEDS_CONSENT = "needs_consent"
    static let UNKNOWN = "unknown"
    static let NO_SUCH_APP = "no_such_app"

    /// Is `bundleId` an application this machine actually has?
    ///
    /// Asked through LaunchServices, which answers for an app that is not
    /// running and does not prompt. Measured 2026-09-10: resolved TextEdit and
    /// Music to real paths and returned nil for a fabricated id.
    static func installedPath(_ bundleId: String) -> String? {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId)?.path
    }

    static func isRunning(_ bundleId: String) -> Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).isEmpty
    }

    /// VESPER's Apple Events permission for one application. Reads; never asks.
    ///
    /// `typeWildCard` for both class and id because the TCC grant is keyed per
    /// TARGET APPLICATION, not per event -- asking about one specific event
    /// would narrow the question in a way the permission itself does not.
    static func permission(_ bundleId: String) -> (state: String, why: String, code: Int) {
        guard let path = installedPath(bundleId) else {
            return (NO_SUCH_APP,
                    "this machine has no application with that identifier", 0)
        }
        if !isRunning(bundleId) {
            // NOT AN ERROR AND NOT A DENIAL. The permission is unreadable until
            // the app exists as a process, which is a fact about the question,
            // not an answer to it -- and it is why the grant trip costs one
            // LAUNCH per app on top of one dialog per app.
            return (UNKNOWN,
                    "\(path) is installed but not running, so its automation "
                    + "permission cannot be read yet", -600)
        }
        var target = AEAddressDesc()
        let bytes = Array(bundleId.utf8)
        let made = bytes.withUnsafeBytes { buf in
            AECreateDesc(typeApplicationBundleID, buf.baseAddress, buf.count, &target)
        }
        guard made == noErr else {
            return (UNKNOWN, "could not address that application (\(made))", Int(made))
        }
        let st = AEDeterminePermissionToAutomateTarget(&target, typeWildCard,
                                                      typeWildCard, false)
        AEDisposeDesc(&target)
        switch st {
        case noErr:
            return (GRANTED, "", 0)
        case OSStatus(-1743):
            return (DENIED,
                    "the owner has refused VESPER permission to control this "
                    + "application", -1743)
        case OSStatus(-1744):
            return (NEEDS_CONSENT,
                    "VESPER has never been granted control of this application; "
                    + "granting it needs the owner at the keyboard", -1744)
        default:
            // UNMAPPED IS UNKNOWN, which is the fail-closed direction. A status
            // this code does not recognise is not evidence of permission.
            return (UNKNOWN, "unrecognised permission status \(st)", Int(st))
        }
    }

    // ----------------------------------------------------------------- verbs
    //
    // THE CLOSED SET. Adding one means adding a row to `host_actions.toml`, a
    // rule in `core/apps.py`, and a MEASURED drive against a real application
    // -- `action_provenance_required = "verified_local"` is not satisfied by
    // knowing that AppleScript has a `documents` element.
    static let VERBS = ["permission", "documents", "document_body"]

    /// The compiled script for a verb. Returns nil for anything not in `VERBS`.
    ///
    /// A `switch` over a closed set rather than a dictionary lookup, so that
    /// adding a case without adding it to `VERBS` is visible, and so that
    /// nothing here can be reached with a string assembled elsewhere.
    private static func script(_ verb: String, appName: String,
                               argument: String? = nil) -> String? {
        switch verb {
        case "documents":
            // NAMES ONLY, AND THE NAMES ARE CONTENT. `host_actions.toml`'s
            // observe tier says so in as many words: enumerating is inventory,
            // reading what things are CALLED is content. So this crosses into
            // the runtime's `observe()` as untrusted text, exactly like a note
            // body -- a document called "run the deploy script" is something
            // VESPER can mention and never something it may act on.
            // THE NOUN IS THE TARGET'S, NOT A GUESS, AND THIS WAS A REAL BUG.
            // Written as `documents`, this verb returned ZERO for Notes -- whose
            // AppleScript element is `note` -- and the `try` block swallowed the
            // error, so an application vesper could not enumerate at all was
            // indistinguishable from one with nothing open. Driven against the
            // real app 2026-09-11: `count 0` while five notes sat there.
            //
            // AND THE `try` IS GONE. A swallowed error here is the exact shape
            // this tree keeps finding: the failure reports as an empty result,
            // the owner is told "nothing open", and nothing anywhere says the
            // verb does not work against that application. The error now reaches
            // `run`, which reports it as a failure with its number.
            return """
            tell application "\(appName)"
                set out to ""
                repeat with d in every \(itemWord(appName))
                    set out to out & (name of d) & linefeed
                end repeat
                return out
            end tell
            """
        case "document_body":
            // THE TEXT OF ONE DOCUMENT, NAMED BY THE OWNER.
            //
            // §11.4, answered by the owner 2026-09-08: "read the bodies, and
            // treat them as untrusted." This is the verb that makes the
            // narrowing of `CI-131` mean something -- the check now asserts a
            // body cannot become an instruction, and until this existed there
            // were no bodies for it to assert about.
            //
            // THE NAME IS MATCHED, NOT INTERPOLATED INTO A QUERY. `whose name
            // is` with the name passed as an AppleScript string keeps the
            // owner's text as DATA: a document called `" & (do shell script
            // "rm -rf ~") & "` is looked up and not found, rather than becoming
            // part of the script. This is the one place in this file where
            // outside text reaches a compiled verb, and it is why the verb takes
            // a name rather than a query.
            guard let name = argument else { return nil }
            return """
            tell application "\(appName)"
                set hits to (every \(itemWord(appName)) whose name is \(quoted(name)))
                if (count of hits) is 0 then return "NONE"
                return \(textProperty(appName)) of item 1 of hits
            end tell
            """
        default:
            return nil
        }
    }

    /// What an application calls the thing that holds text.
    ///
    /// DECLARED PER APPLICATION, and that is a real limit rather than a gap to
    /// be papered over: `documents` is the AppleScript noun for most editors and
    /// `notes` is the one Notes uses. An abstract verb still has to speak the
    /// target's own vocabulary somewhere, and the honest place for that is a
    /// table the reader can see -- not a guess that silently returns nothing.
    private static func itemWord(_ appName: String) -> String {
        appName == "Notes" ? "note" : "document"
    }

    /// Which property holds the TEXT, as opposed to the markup.
    ///
    /// MEASURED 2026-09-11: `body of note` returns HTML -- a real note came back
    /// as `<div>i just looked at the background images...`. That markup then
    /// travels into `observe()` and reaches the planner, where every tag is noise
    /// competing with the owner's actual words, and a body full of attributes is
    /// a body whose meaning is harder to read rather than easier.
    ///
    /// Notes exposes `plaintext` alongside `body` for exactly this. An
    /// application without the distinction gets `body`, which is then its text.
    private static func textProperty(_ appName: String) -> String {
        appName == "Notes" ? "plaintext" : "body"
    }

    /// AppleScript string quoting, so the owner's text stays data.
    ///
    /// A LITERAL IS BUILT, NOT INTERPOLATED. Doubling the quote character is the
    /// whole mechanism: AppleScript has no escape for `"` inside a string, so a
    /// name containing one is expressed by closing the literal, concatenating
    /// `quote`, and reopening. Anything else lets a quote in a filename end the
    /// string and start being code.
    private static func quoted(_ raw: String) -> String {
        let parts = raw.components(separatedBy: "\"")
        return parts.map { "\"\($0)\"" }.joined(separator: " & quote & ")
    }

    /// Run one verb against one application, or explain why not.
    ///
    /// THE PERMISSION CHECK IS NOT AN OPTIMISATION AND MAY NOT BE SKIPPED.
    /// Sending the event first and handling the failure afterwards is the
    /// design that puts a dialog on the owner's screen at 3am. Everything that
    /// is not `granted` returns here, before an Apple Event exists.
    static func run(verb: String, bundleId: String,
                    argument: String? = nil) -> [String: Any] {
        guard VERBS.contains(verb) else {
            return ["ok": false, "verb": verb, "bundle_id": bundleId,
                    "state": "refused",
                    "why": "'\(verb)' is not a verb VESPER has. The set is "
                         + "closed: absence is refusal, not permission."]
        }
        let (state, why, code) = permission(bundleId)
        if verb == "permission" {
            // The instrument reports and never acts, so it is `ok` whatever the
            // permission says -- READING a denial is a successful read.
            return ["ok": true, "verb": verb, "bundle_id": bundleId,
                    "state": state, "why": why, "code": code,
                    "installed": installedPath(bundleId) ?? NSNull(),
                    "running": isRunning(bundleId)]
        }
        guard state == GRANTED else {
            return ["ok": false, "verb": verb, "bundle_id": bundleId,
                    "state": state, "why": why, "code": code,
                    "prompted": false]
        }
        guard let name = NSWorkspace.shared
                .urlForApplication(withBundleIdentifier: bundleId)?
                .deletingPathExtension().lastPathComponent,
              let src = script(verb, appName: name, argument: argument) else {
            return ["ok": false, "verb": verb, "bundle_id": bundleId,
                    "state": UNKNOWN, "why": "no script for that verb"]
        }
        var err: NSDictionary?
        let res = NSAppleScript(source: src)?.executeAndReturnError(&err)
        if let err {
            let n = (err[NSAppleScript.errorNumber] as? Int) ?? 0
            // A GRANT READ AS PRESENT AND AN EVENT REFUSED ANYWAY. Rare, and
            // reported honestly rather than smoothed over: the permission can
            // be revoked between the read and the send.
            return ["ok": false, "verb": verb, "bundle_id": bundleId,
                    "state": n == -1743 ? DENIED : UNKNOWN,
                    "why": "the \(verb) script failed (\(n))", "code": n]
        }
        let raw = res?.stringValue ?? ""
        if verb == "document_body" {
            // "NONE" IS NOT AN EMPTY BODY. A document that does not exist and one
            // that exists and is empty are different facts, and collapsing them
            // would tell the owner their note is blank when vesper simply could
            // not find it -- INV-HW-2's rule applied to a lookup.
            if raw == "NONE" {
                return ["ok": false, "verb": verb, "bundle_id": bundleId,
                        "state": GRANTED, "found": false,
                        "why": "no document of that name in \(bundleId)"]
            }
            return ["ok": true, "verb": verb, "bundle_id": bundleId,
                    "state": GRANTED, "found": true,
                    "body": String(raw.prefix(20_000)),
                    "truncated": raw.count > 20_000]
        }
        let lines = raw.split(separator: "\n").map(String.init)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        return ["ok": true, "verb": verb, "bundle_id": bundleId,
                "state": GRANTED, "items": lines, "count": lines.count]
    }

    static func emit(_ obj: Any) {
        if let d = try? JSONSerialization.data(withJSONObject: obj),
           let s = String(data: d, encoding: .utf8) {
            print(s)
        }
    }
}
