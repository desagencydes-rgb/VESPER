// The owner's calendar and reminders, read the narrow way.
//
// WHY EVENTKIT AND NOT THE FILES. The stores live under
// `~/Library/Group Containers/group.com.apple.{calendar,reminders}` and every
// one of them answers `Operation not permitted` to anything without Full Disk
// Access -- measured 2026-09-05. Full Disk Access is the broadest grant macOS
// has: it would hand VESPER the owner's mail, messages, browser history and
// every other application's private store, to read a list of appointments.
// EventKit asks for exactly the two things it needs, in two dialogs the owner
// can read, and can be revoked separately.
//
// A DUMP ON DISK RATHER THAN A LIVE CALL, and the reason is process identity
// rather than convenience. TCC grants attach to THIS bundle; the Python
// runtime is a child interpreter and cannot inherit the entitlement to ask.
// So the app -- the thing that holds the grant -- writes what it can see, and
// the runtime reads a file. `core/agenda.py` treats a stale or missing dump as
// UNAVAILABLE rather than as an empty day, which is the `INV-HW-2` shape: a
// reading nobody took is not a reading of zero.
//
// AUTHORISATION IS RECORDED PER SOURCE, NOT ASSUMED FROM THE FILE EXISTING.
// The owner can grant calendar and deny reminders, and the dump says so for
// each: `"authorized": false` reaches the runtime as "VESPER has not been
// granted access to reminders", never as "you have no reminders".

import Foundation
import EventKit

private let agendaStore = EKEventStore()

private func agendaDir() -> URL {
    let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                        in: .userDomainMask)[0]
    let dir = base.appendingPathComponent("VESPER/agenda", isDirectory: true)
    try? FileManager.default.createDirectory(at: dir,
                                             withIntermediateDirectories: true)
    return dir
}

private func authorized(_ type: EKEntityType) -> Bool {
    let s = EKEventStore.authorizationStatus(for: type)
    if #available(macOS 14.0, *) {
        return s == .fullAccess || s == .authorized
    }
    return s == .authorized
}

/// Ask for both, then READ BACK. The callback firing is not the grant -- the
/// same lesson `SpeechConsent.swift` records: a dialog that never appeared
/// because a usage string was missing looks exactly like one the owner
/// dismissed, and only re-reading the framework tells them apart.
func requestAgendaConsent() {
    print("requesting as: \(Bundle.main.bundleIdentifier ?? "unknown")")
    let group = DispatchGroup()
    for (type, name) in [(EKEntityType.event, "calendar"),
                         (EKEntityType.reminder, "reminders")] {
        group.enter()
        if #available(macOS 14.0, *) {
            if type == .event {
                agendaStore.requestFullAccessToEvents { ok, err in
                    print("\(name): \(ok ? "granted" : "denied")"
                          + (err.map { " (\($0.localizedDescription))" } ?? ""))
                    group.leave()
                }
            } else {
                agendaStore.requestFullAccessToReminders { ok, err in
                    print("\(name): \(ok ? "granted" : "denied")"
                          + (err.map { " (\($0.localizedDescription))" } ?? ""))
                    group.leave()
                }
            }
        } else {
            agendaStore.requestAccess(to: type) { ok, err in
                print("\(name): \(ok ? "granted" : "denied")"
                      + (err.map { " (\($0.localizedDescription))" } ?? ""))
                group.leave()
            }
        }
    }
    _ = group.wait(timeout: .now() + 90)
    // Read back, because that is the only line here that is evidence.
    print("calendar, read back: \(authorized(.event) ? "authorized" : "NOT authorized")")
    print("reminders, read back: \(authorized(.reminder) ? "authorized" : "NOT authorized")")
}

func agendaStatus() {
    print("bundle: \(Bundle.main.bundleIdentifier ?? "unknown")")
    print("calendar: \(authorized(.event) ? "authorized" : "NOT authorized")")
    print("reminders: \(authorized(.reminder) ? "authorized" : "NOT authorized")")
    print("note: run this with `open -n`. From a shell TCC answers for the shell, not for VESPER.")
}

private func ms(_ d: Date) -> Int { Int(d.timeIntervalSince1970 * 1000) }

/// Write what VESPER can currently see. Always writes a file, even when both
/// sources are denied -- the runtime needs to know the bridge RAN, and a
/// missing file means something else entirely.
func dumpAgenda(daysAhead: Int = 7) {
    var out: [String: Any] = ["written_at_s": Date().timeIntervalSince1970]

    var calendar: [String: Any] = ["authorized": authorized(.event)]
    if authorized(.event) {
        let start = Date()
        let end = Calendar.current.date(byAdding: .day, value: daysAhead,
                                        to: start) ?? start
        let pred = agendaStore.predicateForEvents(withStart: start, end: end,
                                                  calendars: nil)
        calendar["items"] = agendaStore.events(matching: pred).map { ev -> [String: Any] in
            // ALL-DAY EVENTS CARRY NO USEFUL MINUTE. Giving one a due time of
            // midnight would make it the most urgent thing on the list every
            // morning; `core/agenda.py` ranks an item with no due time below
            // anything dated, which is the correct place for "sometime today".
            var row: [String: Any] = [
                "item_id": "calendar:\(ev.eventIdentifier ?? UUID().uuidString)",
                "title": ev.title ?? "(untitled event)",
                "importance": "high",
            ]
            if !ev.isAllDay { row["due_ms"] = ms(ev.startDate) }
            return row
        }
    }
    out["calendar"] = calendar

    var reminders: [String: Any] = ["authorized": authorized(.reminder)]
    if authorized(.reminder) {
        let sem = DispatchSemaphore(value: 0)
        var rows: [[String: Any]] = []
        let pred = agendaStore.predicateForIncompleteReminders(
            withDueDateStarting: nil, ending: nil, calendars: nil)
        agendaStore.fetchReminders(matching: pred) { found in
            for r in found ?? [] {
                var row: [String: Any] = [
                    "item_id": "reminders:\(r.calendarItemIdentifier)",
                    "title": r.title ?? "(untitled reminder)",
                    // A flagged reminder is the owner saying it matters; an
                    // unflagged one is not thereby unimportant, it is just
                    // undistinguished, which is what "normal" means.
                    "importance": r.priority > 0 && r.priority <= 4 ? "high" : "normal",
                ]
                if let d = r.dueDateComponents?.date { row["due_ms"] = ms(d) }
                rows.append(row)
            }
            sem.signal()
        }
        _ = sem.wait(timeout: .now() + 20)
        reminders["items"] = rows
    }
    out["reminders"] = reminders

    let url = agendaDir().appendingPathComponent("eventkit.json")
    // WHOLE FILE, THEN RENAME. A runtime reading this mid-write would see
    // truncated JSON, and `core/agenda.py` would report the dump unreadable --
    // an outage manufactured by the writer.
    let tmp = url.appendingPathExtension("tmp")
    if let data = try? JSONSerialization.data(withJSONObject: out,
                                              options: [.prettyPrinted]) {
        try? data.write(to: tmp)
        try? FileManager.default.removeItem(at: url)
        try? FileManager.default.moveItem(at: tmp, to: url)
    }
    let c = (calendar["items"] as? [[String: Any]])?.count ?? 0
    let r = (reminders["items"] as? [[String: Any]])?.count ?? 0
    print("agenda written: \(c) events, \(r) reminders -> \(url.path)")
    print("  calendar: \(authorized(.event) ? "authorized" : "NOT authorized")")
    print("  reminders: \(authorized(.reminder) ? "authorized" : "NOT authorized")")
}
