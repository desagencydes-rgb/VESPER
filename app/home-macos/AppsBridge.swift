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
    static let VERBS = ["permission", "documents", "document_body",
                        "document_create", "document_replace",
                        "document_delete"]

    /// The compiled script for a verb. Returns nil for anything not in `VERBS`.
    ///
    /// A `switch` over a closed set rather than a dictionary lookup, so that
    /// adding a case without adding it to `VERBS` is visible, and so that
    /// nothing here can be reached with a string assembled elsewhere.
    private static func script(_ verb: String, appName: String,
                               argument: String? = nil,
                               argument2: String? = nil) -> String? {
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
        case "document_create":
            // §11.4, "create and write". The TEXT is the second argument and is
            // quoted the same way the name is -- it is the owner's words, or
            // vesper's, and either way it is data. A note whose text contains
            // `" & (do shell script ...)` must create a note with that text in
            // it, not run anything.
            guard let name = argument, let text = argument2 else { return nil }
            if appName == "Notes" {
                // NOTES HAS NO `name` TO SET: the FIRST LINE of the body becomes
                // the title, measured 2026-09-11. So the title is written as the
                // first line rather than assigned.
                //
                // AND THE BODY IS HTML, WHICH THE FIRST ATTEMPT GOT WRONG. Joining
                // with AppleScript's `return` produced ONE line -- the note came
                // out titled "VESPER test 1789098419 first line of body..." with
                // the body swallowed into the title -- because Notes renders the
                // body as HTML and a carriage return is not a break there.
                //
                // SO THE TEXT IS ESCAPED BEFORE IT IS WRAPPED. `<` and `&` in the
                // owner's own words would otherwise be read as markup: a note
                // containing "a < b" would lose everything after the `<`, and
                // that is the owner's data being silently destroyed by the write
                // that was supposed to store it.
                return """
                tell application "\(appName)"
                    make new note at folder 1 with properties {body:\(quoted(htmlDiv(name) + htmlDiv(text)))}
                    return "MADE"
                end tell
                """
            }
            return """
            tell application "\(appName)"
                make new document with properties {name:\(quoted(name))}
                set text of document \(quoted(name)) to \(quoted(text))
                return "MADE"
            end tell
            """

        case "document_replace":
            guard let name = argument, let text = argument2 else { return nil }
            if appName == "Notes" {
                // THE TITLE IS THE FIRST LINE, SO REWRITING THE BODY RENAMES THE
                // NOTE -- AND THE FIRST VERSION DID EXACTLY THAT. Driven
                // 2026-09-11: a note called "VESPER check 1789098528" was asked
                // to hold "rewritten: 5 < 6"; it came back NAMED "rewritten: 5 <
                // 6", its body unreadable, and unfindable under the name it was
                // asked about -- while the verb reported `ok: true, done: true`.
                //
                // So the title line is written back with the new text under it.
                // Replacing a document's TEXT is not a request to rename it, and
                // a verb that silently does both is a verb whose effect the owner
                // cannot predict.
                return """
                tell application "\(appName)"
                    set hits to (every note whose name is \(quoted(name)))
                    if (count of hits) is 0 then return "NONE"
                    set body of item 1 of hits to \(quoted(htmlDiv(name) + htmlDiv(text)))
                    return "DONE"
                end tell
                """
            }
            return """
            tell application "\(appName)"
                set hits to (every \(itemWord(appName)) whose name is \(quoted(name)))
                if (count of hits) is 0 then return "NONE"
                set \(writeProperty(appName)) of item 1 of hits to \(quoted(writeValue(appName, text)))
                return "DONE"
            end tell
            """

        case "document_delete":
            // THE BRIDGE DOES NOT DECIDE WHETHER THIS IS ALLOWED. `core/apps.py`
            // and the capability above it refuse any document vesper has no
            // record of creating -- this verb only performs it. Putting the
            // ownership rule here as well would put it somewhere the checks do
            // not read, which is the split `host_actions.toml` insists on.
            guard let name = argument else { return nil }
            // DELETED BY ITS OWN IDENTITY, NOT BY THE NAME IT MATCHED.
            //
            // MEASURED 2026-09-11: `delete item 1 of hits` raised no error and
            // left the note in place for a note whose title contained a quote
            // character, while the same expression matched it perfectly well for
            // the `exists` query. So the match was never the problem -- the
            // reference was. `delete` on an element of a `whose` result is
            // evaluating against a filtered specifier that Notes does not honour
            // for removal; resolving the note to its own `id` first and deleting
            // THAT reference is unambiguous, and it also stops a second document
            // of the same name being the one that goes.
            return """
            tell application "\(appName)"
                set hits to (every \(itemWord(appName)) whose name is \(quoted(name)))
                if (count of hits) is 0 then return "NONE"
                set theId to id of item 1 of hits
                -- WHICH FOLDER HOLDS IT, FOUND BY WALKING THEM.
                --
                -- `container of note` and `folder of note` BOTH fail with -1728
                -- on this version, measured 2026-09-11, so the folder cannot be
                -- asked of the note. It can be asked of the folders. This is
                -- also why the check cannot simply name the trash: "Recently
                -- Deleted" is localised, and a proof that depends on the
                -- machine's language is a proof that fails on another machine.
                set homeId to ""
                repeat with f in every \(folderWord(appName))
                    if (count of (every \(itemWord(appName)) of f whose id is theId)) > 0 then
                        set homeId to id of f
                        exit repeat
                    end if
                end repeat
                delete (\(itemWord(appName)) id theId)
                return "GONE\t" & homeId
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

    /// Is a document of this name reachable right now? The proof for every write.
    ///
    /// A SEPARATE SCRIPT, RUN AFTER THE FACT, and deliberately not folded into
    /// the write itself: a write that reports on its own success is exactly the
    /// instrument this corpus refuses to believe. This one asks the application
    /// the same question the owner would ask -- is it there? -- and its answer is
    /// what `ok` is set from.
    private static func exists(name: String, appName: String,
                               inContainer: String = "") -> Bool {
        guard !name.isEmpty else { return false }
        // SCOPED TO ONE CONTAINER WHEN THE CALLER KNOWS WHICH, and unscoped when
        // it does not. A create or a rewrite only needs the document to be
        // reachable; a delete needs it gone from where it WAS, because a deleted
        // note still answers an unscoped query from the trash it now sits in.
        let scope = inContainer.isEmpty
            ? "every \(itemWord(appName)) whose name is \(quoted(name))"
            : "every \(itemWord(appName)) of (first \(folderWord(appName)) whose "
              + "id is \(quoted(inContainer))) whose name is \(quoted(name))"
        let src = """
        tell application "\(appName)"
            return (count of (\(scope))) as string
        end tell
        """
        var err: NSDictionary?
        let res = NSAppleScript(source: src)?.executeAndReturnError(&err)
        if err != nil { return false }
        return (Int(res?.stringValue ?? "0") ?? 0) > 0
    }

    /// What the application calls a group of documents.
    private static func folderWord(_ appName: String) -> String {
        appName == "Notes" ? "folder" : "folder"
    }

    /// Which property can be WRITTEN, which is not always the one that is read.
    ///
    /// Notes' `plaintext` is READ-ONLY -- it is the rendered text of the HTML in
    /// `body`. Reading `plaintext` and writing `body` is not an inconsistency to
    /// be tidied up; it is what the application allows, and writing to the
    /// read-only one fails with an error nobody would connect to the cause.
    private static func writeProperty(_ appName: String) -> String {
        appName == "Notes" ? "body" : "body"
    }

    private static func writeValue(_ appName: String, _ text: String) -> String {
        appName == "Notes" ? htmlDiv(text) : text
    }

    /// One line of HTML, with the text escaped rather than trusted.
    ///
    /// THREE CHARACTERS, AND `&` MUST GO FIRST. Escaping `<` before `&` would
    /// turn `<` into `&lt;` and then the `&` of `&lt;` into `&amp;lt;`, so the
    /// owner would see the escape sequence instead of their own character.
    private static func htmlDiv(_ raw: String) -> String {
        let escaped = raw
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        return "<div>" + escaped + "</div>"
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
                    argument: String? = nil,
                    argument2: String? = nil) -> [String: Any] {
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
              let src = script(verb, appName: name, argument: argument,
                               argument2: argument2) else {
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
        if ["document_create", "document_replace", "document_delete"].contains(verb) {
            // THE SCRIPT'S OWN WORD IS THE EVIDENCE, not the absence of an error.
            // A `set` that matched nothing raises no error in AppleScript, so
            // "no error" would report a rewrite that never happened -- the
            // success-shaped answer this tree keeps finding.
            if raw == "NONE" {
                return ["ok": false, "verb": verb, "bundle_id": bundleId,
                        "state": GRANTED, "found": false,
                        "why": "no document of that name in \(bundleId)"]
            }
            // THE DELETE CARRIES WHERE THE DOCUMENT WAS, and the verification
            // needs it.
            //
            // MEASURED 2026-09-11, AFTER THREE CLEAN CYCLES REPORTED FAILURE:
            // `delete` in Notes MOVES a note to "Recently Deleted" -- exactly
            // what the Notes interface does, and recoverable -- and `every note`
            // STILL MATCHES IT THERE. So "does a document of this name exist?"
            // answered yes about a note that had been deleted correctly, and the
            // verb reported failure three times in a row for work it had done.
            //
            // The right question is whether it is still in the folder it was IN.
            // Asked by container ID rather than by folder NAME, because
            // "Recently Deleted" is localised and a check that depends on the
            // machine's language is a check that fails on a different machine.
            var homeContainer = ""
            var word = raw
            if verb == "document_delete", let tab = raw.firstIndex(of: "\t") {
                word = String(raw[raw.startIndex..<tab])
                homeContainer = String(raw[raw.index(after: tab)...])
            }
            let expected = ["document_create": "MADE", "document_replace": "DONE",
                            "document_delete": "GONE"][verb] ?? ""
            if word != expected {
                return ["ok": false, "verb": verb, "bundle_id": bundleId,
                        "state": GRANTED,
                        "why": "the \(verb) script returned \(word.isEmpty ? "nothing" : word) "
                             + "rather than \(expected), so vesper cannot show it happened"]
            }
            // AND THE WORLD IS RE-READ, BECAUSE THE SCRIPT'S WORD IS NOT
            // EVIDENCE. `MEMORY.md`'s rule, and it was earned twice in one
            // minute on 2026-09-11: `document_replace` returned "DONE" having
            // destroyed the note, and `document_delete` returned "GONE" with the
            // note still sitting in the list. Both reported `ok: true`.
            //
            // A DELETE IS PROVED BY ABSENCE AND A WRITE BY PRESENCE. Notes moves
            // a deleted note to Recently Deleted rather than removing it, so
            // "the script did not error" says nothing at all about whether the
            // note is still reachable under its name.
            // POLLED FOR THE FACT, NOT SLEPT FOR A GUESS.
            //
            // A single 250 ms settle reported a delete as failed and the SAME
            // delete succeeded on the next attempt -- measured 2026-09-11, the
            // full cycle showing `verified: false` then `verified: true` with
            // nothing changed in between. That is honest (it never claimed a
            // success it did not have) and still wrong to ship: the owner asks
            // vesper to remove a note, the note goes, and vesper says it could
            // not. `window_open` learned the same lesson on 2026-09-09 and its
            // comment is the rule -- poll for the fact rather than assume how
            // long it takes to become one.
            //
            // AND IT STOPS AS SOON AS THE WORLD AGREES, so a fast application
            // costs one read rather than a fixed wait.
            let wantPresent = (verb != "document_delete")
            var stillThere = exists(name: argument ?? "", appName: name,
                                   inContainer: homeContainer)
            var waited = 0
            while stillThere != wantPresent && waited < 3_000_000 {
                usleep(150_000)
                waited += 150_000
                stillThere = exists(name: argument ?? "", appName: name,
                                   inContainer: homeContainer)
            }
            if verb == "document_delete" {
                if stillThere {
                    return ["ok": false, "verb": verb, "bundle_id": bundleId,
                            "state": GRANTED, "verified": false,
                            "why": "the delete reported success and the document "
                                 + "is still there under that name"]
                }
                return ["ok": true, "verb": verb, "bundle_id": bundleId,
                        "state": GRANTED, "done": true, "verified": true]
            }
            if !stillThere {
                return ["ok": false, "verb": verb, "bundle_id": bundleId,
                        "state": GRANTED, "verified": false,
                        "why": "the \(verb) reported success and no document of "
                             + "that name can be found afterwards -- the write "
                             + "either failed or renamed it"]
            }
            return ["ok": true, "verb": verb, "bundle_id": bundleId,
                    "state": GRANTED, "done": true, "verified": true]
        }
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
