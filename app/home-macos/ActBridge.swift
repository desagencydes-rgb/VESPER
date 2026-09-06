import AppKit
import WebKit

/// What the page is allowed to ask the machine to do, and nothing else.
///
/// THE PAGE IS NOT TRUSTED, AND IT CANNOT BE. Its rows are built from
/// `home.json`, which carries a model's output, file paths off the disk and a
/// process's own stderr. A click is the owner's, but the PAYLOAD attached to
/// that click was rendered from data VESPER produced -- so "the owner clicked
/// the button" authorises the ACTION and says nothing about the argument.
///
/// So every argument is re-derived here from the file the runtime published:
///
///   * a path may be opened only if it appears in the current changes list.
///     Not "looks like a path", not "is under the repo" -- is one of the rows
///     the runtime just published. A path the page invented resolves to
///     nothing and is refused.
///   * git runs in the repository the runtime named, never one the page did.
///   * every command is an ARGV array. There is no shell here, so there is no
///     quoting to get wrong and no interpolation to escape.
///   * push, pull and commit CONFIRM FIRST, and the confirmation names the
///     exact command, the repository and the branch. These are outward-facing
///     and hard to reverse; a button that pushes without saying where is how
///     work reaches the wrong place.
///
/// AND THE TERMINAL IS NOT HERE. Writing to the owner's shell is a different
/// channel with a different rule (`TerminalBridge`), deliberately not reachable
/// from this class.
final class ActBridge: NSObject, WKScriptMessageHandler {
    static let name = "vesperAct"
    weak var web: WKWebView?

    private static var stateURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/home.json")
    }

    /// The changes the runtime last published: the only paths that may be
    /// opened, and the only repository git may be run in.
    private static func published() -> (paths: Set<String>, repo: String) {
        guard let d = try? Data(contentsOf: stateURL),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let c = o["changes"] as? [String: Any]
        else { return ([], "") }
        let rows = (c["changes"] as? [[String: Any]]) ?? []
        let paths = Set(rows.compactMap { $0["path"] as? String })
        return (paths, (c["repo"] as? String) ?? "")
    }

    @discardableResult
    private static func run(_ argv: [String], cwd: String?) -> (Int32, String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: argv[0])
        p.arguments = Array(argv.dropFirst())
        if let cwd, !cwd.isEmpty { p.currentDirectoryURL = URL(fileURLWithPath: cwd) }
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        do { try p.run() } catch { return (127, "\(error)") }
        let out = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus,
                String(data: out, encoding: .utf8) ?? "")
    }

    /// Where a push would go and what a commit would cover, read from git
    /// rather than guessed, so the confirmation names the real target.
    private static func gitPlan(_ op: String, repo: String) -> (argv: [String], says: String) {
        let git = "/usr/bin/git"
        let branch = run([git, "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"], cwd: repo)
            .1.trimmingCharacters(in: .whitespacesAndNewlines)
        switch op {
        case "pull":
            // `--ff-only`, NEVER a merge or a rebase. A pull that can produce
            // conflicts from a button is a pull that leaves the owner's tree in
            // a state they did not ask for and cannot see from this card.
            return ([git, "-C", repo, "pull", "--ff-only"],
                    "git pull --ff-only  (fast-forward \(branch), or refuse)")
        case "push":
            let remote = run([git, "-C", repo, "remote"], cwd: repo)
                .1.split(separator: "\n").first.map(String.init) ?? "origin"
            return ([git, "-C", repo, "push", remote, branch],
                    "git push \(remote) \(branch)")
        default:
            return ([], "")
        }
    }

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let kind = body["kind"] as? String else { return }
        let (paths, repo) = Self.published()

        switch kind {
        case "copy":
            // The clipboard, from AppKit rather than from `navigator.clipboard`
            // -- which a WKWebView with no origin cannot use.
            let text = (body["text"] as? String) ?? ""
            guard !text.isEmpty else { return }
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            reply(["kind": "copy", "ok": true, "says": "copied"])

        case "open":
            // OPENED ONLY IF THE RUNTIME PUBLISHED IT. A path the page made up
            // is not in this set and goes nowhere.
            let path = (body["path"] as? String) ?? ""
            guard paths.contains(path) else {
                reply(["kind": "open", "ok": false,
                       "says": "that file is not one of the changes VESPER published"])
                return
            }
            let (code, out) = Self.run(["/usr/bin/open", path], cwd: nil)
            reply(["kind": "open", "ok": code == 0,
                   "says": code == 0 ? "opened in your editor"
                                     : "could not open it: \(out.prefix(200))"])

        case "git":
            let op = (body["op"] as? String) ?? ""
            let confirmed = (body["confirm"] as? Bool) ?? false
            guard !repo.isEmpty else {
                reply(["kind": "git", "op": op, "ok": false,
                       "says": "there is no repository here"])
                return
            }
            if op == "commit" {
                let msg = ((body["message"] as? String) ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                // A COMMIT WITH NO MESSAGE IS REFUSED rather than given one.
                // An invented subject is a lie in the history of the owner's
                // own repository.
                guard !msg.isEmpty else {
                    reply(["kind": "git", "op": op, "ok": false,
                           "says": "a commit needs a message"])
                    return
                }
                guard confirmed else {
                    reply(["kind": "git", "op": op, "ok": true, "armed": true,
                           "says": "git add -A && git commit  in \(repo)"])
                    return
                }
                let git = "/usr/bin/git"
                let (ac, ao) = Self.run([git, "-C", repo, "add", "-A"], cwd: repo)
                if ac != 0 {
                    reply(["kind": "git", "op": op, "ok": false,
                           "says": "git add failed: \(ao.prefix(200))"])
                    return
                }
                let (cc, co) = Self.run([git, "-C", repo, "commit", "-m", msg], cwd: repo)
                reply(["kind": "git", "op": op, "ok": cc == 0,
                       "says": cc == 0 ? "committed" : String(co.prefix(300))])
                return
            }
            let plan = Self.gitPlan(op, repo: repo)
            guard !plan.argv.isEmpty else {
                reply(["kind": "git", "op": op, "ok": false,
                       "says": "not an operation this card performs"])
                return
            }
            guard confirmed else {
                reply(["kind": "git", "op": op, "ok": true, "armed": true,
                       "says": plan.says])
                return
            }
            let (code, out) = Self.run(plan.argv, cwd: repo)
            reply(["kind": "git", "op": op, "ok": code == 0,
                   "says": code == 0 ? (out.isEmpty ? "done" : String(out.prefix(300)))
                                     : String(out.prefix(300))])

        default:
            return
        }
    }

    /// Say what happened, back into the page. A button that does its work in
    /// silence is a button the owner presses twice.
    private func reply(_ payload: [String: Any]) {
        guard let d = try? JSONSerialization.data(withJSONObject: payload),
              let s = String(data: d, encoding: .utf8) else { return }
        let safe = s
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")
            .replacingOccurrences(of: "$", with: "\\$")
        DispatchQueue.main.async { [weak self] in
            self?.web?.evaluateJavaScript(
                "if (window.__vesperActResult) window.__vesperActResult(`\(safe)`);",
                completionHandler: nil)
        }
    }
}
