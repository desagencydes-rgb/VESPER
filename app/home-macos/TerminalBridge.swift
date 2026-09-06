import AppKit
import Darwin
import WebKit

/// The owner's shell, under the home's glass.
///
/// THIS IS NOT VESPER'S TERMINAL AND MUST NOT BECOME ONE. VESPER's commands run
/// through `shell.run`, inside a seatbelt, levelled by the ladder, recorded on
/// the commands card. This is the other thing entirely: the owner's own login
/// shell, their environment, their PATH, no sandbox -- because a terminal that
/// cannot run the owner's tools is not a terminal.
///
/// THE RULE THAT MAKES THAT SAFE, AND IT IS STRUCTURAL RATHER THAN CAREFUL:
///
///   **Nothing VESPER produces can reach this file descriptor.**
///
/// There is exactly one function that writes to the PTY, `write(_:)`, and
/// exactly one message that reaches it, `input`. That message is posted from
/// two places in the page and two only: the terminal's own keydown handler, and
/// the Run button's click handler. Both are gestures the owner made.
///
/// PASTE HAS NO BRIDGE AT ALL. The obvious design is a second message with a
/// `run: false` flag, and it is wrong -- a flag is one inverted condition away
/// from being a writer, and that inversion would be invisible in review. So
/// "paste without running" is done ENTIRELY in the page: it puts text in an
/// input element and returns. There is no Swift function for it, so there is
/// no code path from it to a file descriptor to get wrong.
///
/// Neither `home.json`, nor the state push, nor a model's output, nor a file
/// VESPER read has any route here. The state push touches `__vesperStage`,
/// `__vesperHistory`, `__vesperWork` and `__vesperChanges`; none of them is
/// this.
final class TerminalBridge: NSObject, WKScriptMessageHandler {
    static let name = "vesperTerm"
    weak var web: WKWebView?

    private var master: Int32 = -1
    private var shell: Process?
    private var reader: DispatchSourceRead?
    private var lastUse = Date()

    /// Idle before the shell is reaped. A shell nobody has typed into for
    /// fifteen minutes is not in use; one with a foreground job still running
    /// is, and `isRunning` is what tells them apart.
    private let idleKillAfter: TimeInterval = 900

    // ------------------------------------------------------------ lifecycle

    private func open() {
        guard shell == nil else { return }
        var m: Int32 = 0, s: Int32 = 0
        // A REAL PSEUDO-TERMINAL, not a pipe. A pipe makes every tool the owner
        // runs decide it is not talking to a terminal: no colour, no prompt
        // redraw, no `less`, and `git` quietly changes its own behaviour. The
        // point of this pane is that it behaves like their terminal.
        var win = winsize(ws_row: 24, ws_col: 80, ws_xpixel: 0, ws_ypixel: 0)
        guard openpty(&m, &s, nil, nil, &win) == 0 else {
            say("could not open a terminal\r\n")
            return
        }
        master = m

        let p = Process()
        // THE OWNER'S SHELL AND THE OWNER'S ENVIRONMENT. `$SHELL` is what they
        // chose; `/bin/zsh` is the fallback because it is the macOS default,
        // not because it is a preference of ours.
        let sh = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        p.executableURL = URL(fileURLWithPath: sh)
        // `-il`: interactive so the owner's `.zshrc` is sourced -- their
        // aliases, their PATH, their functions -- and login so `.zprofile` is
        // too. A shell that skips those has a different environment from every
        // other terminal on the machine, which is the sort of difference that
        // costs an hour to find.
        //
        // AND `nozle` FOR ZSH, WHICH IS THE WHOLE OF WHY THIS PANE IS
        // READABLE. zsh's line editor takes control of the terminal, sets its
        // own termios -- undoing an ECHO that was turned off a line earlier,
        // which is exactly what happened here -- and redraws the command as
        // each byte arrives, with cursor moves and a padded right-hand prompt.
        // A line-oriented renderer shows all of that: `echo readable` arrived
        // as three lines reading "ech", "o", "o readable". Turning the editor
        // OFF rather than fighting its redraw leaves an interactive shell that
        // reads its own configuration and simply executes lines.
        //
        // WHAT IT COSTS: tab completion and history-by-arrow inside this pane.
        // Both belong to the line editor, and neither is what the owner asked
        // this pane for. Only for zsh -- `-o nozle` is not a thing bash knows,
        // and passing it to one would leave the owner with no shell at all.
        if sh.hasSuffix("/zsh") || sh == "zsh" {
            // `nopromptsp`/`nopromptcr` TOO. zsh guards against a program
            // whose output lacks a final newline by printing an inverse `%`,
            // padding to the width of the terminal, and a carriage return --
            // designed for a screen that overwrites, and rendered by a
            // line-oriented pane as a stray `%` and a row of spaces before
            // every prompt. Measured here on every single command.
            p.arguments = ["-o", "nozle", "-o", "nopromptsp",
                           "-o", "nopromptcr", "-il"]
        } else {
            p.arguments = ["-il"]
        }
        var env = ProcessInfo.processInfo.environment
        env["TERM"] = "xterm-256color"
        // NOT SET: anything that would mark this as VESPER's. This is a plain
        // shell and tools that branch on an unfamiliar variable would behave
        // differently here than in the owner's own window.
        p.environment = env
        p.currentDirectoryURL = URL(fileURLWithPath: repoOrHome())
        let slave = FileHandle(fileDescriptor: s, closeOnDealloc: false)
        p.standardInput = slave
        p.standardOutput = slave
        p.standardError = slave
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.say("\r\n[the shell exited]\r\n")
                self?.teardown()
            }
        }
        do { try p.run() } catch {
            say("could not start \(sh): \(error)\r\n")
            close(m); close(s)
            master = -1
            return
        }
        // ECHO OFF, AND THIS IS A DESIGN DECISION RATHER THAN A TWEAK.
        //
        // The owner asked for a pane whose "design should be the same as
        // vesper's home design, not terminal's design". With echo on, zsh's
        // line editor redraws the command as each byte arrives -- cursor
        // moves, partial reprints, a right-hand prompt padded with spaces --
        // and a line-oriented renderer shows all of it. Measured on the first
        // real command this pane ran: `echo readable` came out as three lines
        // reading "ech", "o", "o readable".
        //
        // So the shell stops echoing and the PAGE prints the submitted line
        // once, in VESPER's own type. The transcript is then exactly: what was
        // asked, and what came back.
        //
        // WHAT THIS COSTS, honestly: a program that relies on the terminal
        // echoing for it sees none. Line-oriented tools do not; full-screen
        // ones already do not work here and the pane says so. A password
        // prompt not echoing is the correct behaviour anyway.
        var tio = termios()
        if tcgetattr(m, &tio) == 0 {
            tio.c_lflag &= ~UInt(ECHO)
            _ = tcsetattr(m, TCSANOW, &tio)
        }
        close(s)                       // the child holds it now
        shell = p
        lastUse = Date()

        let src = DispatchSource.makeReadSource(fileDescriptor: m,
                                                queue: .global(qos: .userInitiated))
        src.setEventHandler { [weak self] in
            guard let self, self.master >= 0 else { return }
            var buf = [UInt8](repeating: 0, count: 8192)
            let n = read(self.master, &buf, buf.count)
            guard n > 0 else { return }
            let text = String(decoding: buf[0..<n], as: UTF8.self)
            DispatchQueue.main.async { self.say(text) }
        }
        src.resume()
        reader = src
    }

    private func repoOrHome() -> String {
        let cwd = FileManager.default.currentDirectoryPath
        var d = URL(fileURLWithPath: cwd)
        for _ in 0..<6 {
            if FileManager.default.fileExists(atPath: d.appendingPathComponent(".git").path) {
                return d.path
            }
            d = d.deletingLastPathComponent()
        }
        return FileManager.default.homeDirectoryForCurrentUser.path
    }

    private func teardown() {
        reader?.cancel()
        reader = nil
        if master >= 0 { close(master) }
        master = -1
        shell = nil
    }

    /// THE ONLY FUNCTION IN THIS FILE THAT WRITES TO THE TERMINAL.
    ///
    /// Called from one place: the `input` case below. If a second caller ever
    /// appears, the property this class exists to hold is gone -- so the rule
    /// is stated here, where anyone adding one would be reading.
    private func write(_ text: String) {
        guard master >= 0, let d = text.data(using: .utf8) else { return }
        lastUse = Date()
        _ = d.withUnsafeBytes { Darwin.write(master, $0.baseAddress, d.count) }
    }

    private func resize(cols: Int, rows: Int) {
        guard master >= 0, cols > 0, rows > 0 else { return }
        var w = winsize(ws_row: UInt16(min(rows, 300)), ws_col: UInt16(min(cols, 500)),
                        ws_xpixel: 0, ws_ypixel: 0)
        _ = ioctl(master, TIOCSWINSZ, &w)
    }

    /// Reap a shell nobody is using. A foreground job blocks it: the owner may
    /// have left something running on purpose, and killing that to save a file
    /// descriptor is the wrong trade in every case.
    func reapIfIdle() {
        guard let p = shell else { return }
        guard Date().timeIntervalSince(lastUse) > idleKillAfter else { return }
        p.terminate()
        teardown()
    }

    // -------------------------------------------------------------- the page

    func userContentController(_ c: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let kind = body["kind"] as? String else { return }
        switch kind {
        case "open":
            open()
        case "input":
            // THE ONE WRITER. See the class header for why nothing else may
            // reach this line.
            open()
            write((body["text"] as? String) ?? "")
        case "resize":
            resize(cols: (body["cols"] as? Int) ?? 80,
                   rows: (body["rows"] as? Int) ?? 24)
        case "close":
            shell?.terminate()
            teardown()
        default:
            return
        }
    }

    /// Terminal output, into the page. Escaped the same way every other push
    /// is: this is a shell's output and it is not markup.
    private func say(_ text: String) {
        let safe = text
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")
            .replacingOccurrences(of: "$", with: "\\$")
        web?.evaluateJavaScript(
            "if (window.__vesperTermOut) window.__vesperTermOut(`\(safe)`);",
            completionHandler: nil)
    }
}
