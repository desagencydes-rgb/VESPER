import Foundation

/// The owner's Notes, as titles only, for the agenda's third source.
///
/// WHY THIS IS NOT A FOURTH LINE IN `AgendaBridge`. Calendar and Reminders have
/// EventKit: a public read API, a TCC class of their own, and an authorization
/// call that returns a real answer. Notes has none of that. The only route is
/// Apple Events -- scripting the Notes app -- which is a different permission
/// class (`NSAppleEventsUsageDescription`, Automation, consented per target
/// app), a different failure mode (the app is launched if it is not running),
/// and a different trust class for what comes back.
///
/// **TITLES ONLY. THE BODY IS NEVER READ, AND THAT IS THE WHOLE SAFETY
/// ARGUMENT.** A calendar entry was written by the owner. A note's BODY may
/// contain anything they ever pasted into it -- a web page, an email, someone
/// else's text, a phishing message they kept to look at later. That is
/// `retrieved_external` wearing a local file's clothes, and it would be
/// arriving on the path VESPER uses to decide what to do next. A note saying
/// "delete the old backups" is a note, not an order.
///
/// A TITLE is short, is almost always the owner's own words, and is all the
/// agenda actually needs: something to rank and something to say. Reading only
/// the title removes the entire question rather than answering it carefully,
/// which is the better trade when the careful answer would have to hold
/// forever.
///
/// AND IT IS STILL NOT AN INSTRUCTION. `core/agenda.py` ranks these and
/// `sentence()` mentions them; nothing here reaches a planner as a directive.
/// The `trust` field travels with every row so a later consumer cannot forget
/// where the text came from.
///
/// NSAppleScript, IN PROCESS, NOT `osascript` AS A SUBPROCESS. TCC attributes
/// an Apple Event to the responsible process, and the whole `--speech-consent`
/// lesson in `CLAUDE.md` is that spawning a helper hands the permission to the
/// helper's ancestry instead of to VESPER. The event has to originate here.
enum NotesBridge {

    /// How far back a note still counts as something the owner is working on.
    /// Older than this and it is archive, not agenda.
    static let recentDays = 14

    /// A hard cap on rows. A Notes library can hold thousands; the agenda is a
    /// ranking of what to do next, not a second Notes app.
    static let maxNotes = 40

    private static func agendaDir() -> URL {
        let d = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/agenda")
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    /// The script. Returns one line per note: `modified-epoch \t folder \t title`.
    ///
    /// FILTERED IN APPLESCRIPT, NOT IN SWIFT. Asking Notes for every note and
    /// discarding most of them here means the Apple Event carries the whole
    /// library across the process boundary -- slow, and it puts body-adjacent
    /// data in this process for no reason. `whose modification date > …` makes
    /// the app do the filtering and send back only what is wanted.
    private static func script(days: Int) -> String {
        // NO DATE LITERAL. The first version built the cutoff from
        // `date "Thursday, 1 January 1970 at 00:00:00"` and added an epoch to
        // it -- which AppleScript parses against the USER'S LOCALE, so on any
        // machine not set to that English format it fails, and `try` swallowed
        // the failure into an empty result. Measured 2026-09-07: "0 titles"
        // from a library with notes in it, and nothing anywhere said why.
        //
        // `(current date) - (n * days)` is arithmetic on values AppleScript
        // produced itself. There is no parsing and no locale.
        //
        // AND `container of n` IS RESOLVED IN TWO STEPS, which is the second
        // thing that made this return nothing. Written inline as
        // `name of container of n` inside a `whose` loop, AppleScript keeps the
        // container as an unresolved list-context reference and coercion fails:
        //   Can't make name of «class cntr» of item 1 of every «class note» …
        //     into type Unicode text. (-1700)
        // Binding it to a variable first forces the resolution. Measured
        // 2026-09-07 against a library of 161 notes, 5 of them recent.
        //
        // AND THE `try` NO LONGER HIDES IT. It was swallowing that error once
        // per note, so the script returned an empty string and the dump
        // reported "0 titles" from a library that had five -- a silence with
        // no reason attached, which is what this corpus calls a defect rather
        // than robustness. The count comes back now and is published.
        """
        set cutoff to (current date) - (\(days) * days)
        set out to ""
        set skipped to 0
        tell application "Notes"
            set matches to (notes whose modification date is greater than cutoff)
            repeat with n in matches
                try
                    set c to container of n
                    set out to out & (name of c) & tab & (name of n) & linefeed
                on error
                    set skipped to skipped + 1
                end try
            end repeat
        end tell
        return out & "SKIPPED" & tab & (skipped as string)
        """
    }

    /// Has the owner consented to VESPER scripting Notes?
    ///
    /// ASKED BY DOING THE SMALLEST POSSIBLE THING, because there is no
    /// `authorizationStatus` for Apple Events the way EventKit has one for
    /// calendars. `AEDeterminePermissionToAutomateTarget` exists but reports on
    /// a target bundle id and still prompts; a one-property script is the same
    /// question asked in the same words the real read will use.
    static func authorized() -> (ok: Bool, why: String) {
        var err: NSDictionary?
        let probe = NSAppleScript(source: "tell application \"Notes\" to return name")
        _ = probe?.executeAndReturnError(&err)
        if let err {
            let n = (err[NSAppleScript.errorNumber] as? Int) ?? 0
            // -1743 is "not authorised to send Apple events"; -600 is "the app
            // is not running", which is not a permission problem.
            if n == -1743 {
                return (false, "VESPER has not been allowed to control Notes")
            }
            return (false, "Notes could not be reached (\(n))")
        }
        return (true, "")
    }

    /// Ask for the Automation grant, with a dialog, once.
    static func requestConsent() {
        let (ok, why) = authorized()
        if ok {
            print("notes: already authorized")
            return
        }
        print("notes: \(why)")
        print("  If no dialog appeared, grant it by hand:")
        print("  System Settings > Privacy & Security > Automation > VESPER > Notes")
    }

    static func status() {
        let (ok, why) = authorized()
        print("notes: \(ok ? "authorized" : "NOT authorized — \(why)")")
    }

    /// Write `agenda/notes.json`, in the shape `core/agenda.py` already reads.
    ///
    /// WRITTEN EVEN WHEN THE SOURCE IS DENIED, exactly like `AgendaBridge`: the
    /// runtime needs to know the bridge RAN. A missing file and a denied source
    /// are different facts and `INV-HW-2` refuses to collapse them -- a reading
    /// nobody took is not a reading of zero.
    static func dump() {
        var out: [String: Any] = ["written_at_s": Date().timeIntervalSince1970]
        let (ok, why) = authorized()
        var notes: [String: Any] = ["authorized": ok]
        if !ok { notes["why"] = why }

        if ok {
            var err: NSDictionary?
            let s = NSAppleScript(source: script(days: recentDays))
            let res = s?.executeAndReturnError(&err)
            if let err {
                notes["authorized"] = false
                notes["why"] = "the Notes script failed "
                             + "(\((err[NSAppleScript.errorNumber] as? Int) ?? 0))"
            } else {
                var rows: [[String: Any]] = []
                var skipped = 0
                for line in (res?.stringValue ?? "").split(separator: "\n") {
                    // THE SKIP COUNT RIDES THE SAME CHANNEL. A per-note error
                    // swallowed in silence is what made this look empty rather
                    // than broken; if any note cannot be read, the number says
                    // so where the owner's runtime can see it.
                    if line.hasPrefix("SKIPPED\t") {
                        skipped = Int(line.dropFirst("SKIPPED\t".count)) ?? 0
                        continue
                    }
                    let parts = line.split(separator: "\t", omittingEmptySubsequences: false)
                    guard parts.count >= 2 else { continue }
                    // The TITLE is everything after the first tab, rejoined --
                    // a note may legitimately have a tab in its name and
                    // dropping the rest would silently truncate it.
                    let title = parts[1...].joined(separator: "\t")
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    if title.isEmpty { continue }
                    rows.append([
                        // KEYED ON THE TITLE, not on a Notes identifier. The
                        // script deliberately does not ask for `id`, because
                        // that is one more thing crossing the boundary for no
                        // gain -- and a note the owner renames IS a different
                        // item as far as an agenda is concerned.
                        "item_id": "notes:\(parts[0])/\(title)",
                        "title": title,
                        "folder": String(parts[0]),
                        // NO `due_ms`. A note has a MODIFICATION date, which is
                        // not a deadline. `core/agenda.py` ranks an item with
                        // no due time below anything dated, which is exactly
                        // where "sometime" belongs -- and inventing a due time
                        // from a modification date would put every note the
                        // owner touched today at the top of their agenda.
                        "importance": "normal",
                        // TRAVELS WITH THE ROW so a later consumer cannot
                        // forget where the text came from.
                        "trust": "retrieved_local",
                    ])
                    if rows.count >= maxNotes { break }
                }
                notes["items"] = rows
                if skipped > 0 { notes["skipped"] = skipped }
            }
        }
        out["notes"] = notes

        let url = agendaDir().appendingPathComponent("notes.json")
        // WHOLE FILE, THEN RENAME -- same reason as the EventKit dump. A
        // runtime reading this mid-write would see truncated JSON and report an
        // outage the writer manufactured.
        let tmp = url.appendingPathExtension("tmp")
        if let data = try? JSONSerialization.data(withJSONObject: out,
                                                  options: [.prettyPrinted]) {
            try? data.write(to: tmp)
            try? FileManager.default.removeItem(at: url)
            try? FileManager.default.moveItem(at: tmp, to: url)
        }
        let n = (notes["items"] as? [[String: Any]])?.count ?? 0
        print("notes written: \(n) titles -> \(url.path)")
        print("  notes: \(ok ? "authorized" : "NOT authorized — \(why)")")
    }
}
