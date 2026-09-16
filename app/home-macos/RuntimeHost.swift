// The runtime, started by the app and dying with it.
//
// WHY THIS IS NOT A SECOND LOGIN ITEM. It was, briefly, and that was wrong:
// two labels, two identities, and a runtime that could be answering while no
// VESPER window existed anywhere -- holding the owner's API keys with nothing
// on screen to say so. One app means one thing to launch, one thing to quit,
// and a runtime whose lifetime is exactly the app's.
//
// THE SPLIT BETWEEN THE TWO IS STILL REAL, and keeping it is the point of
// running the runtime as a CHILD rather than as more Swift. The surface renders
// model output and holds no credentials; the runtime holds the keys and draws
// no pixels. Collapsing them into one process would give the layer that renders
// untrusted text the same address space as the layer holding the API keys.
// Separate processes, one lifetime.
//
// TERMINATION IS NOT LEFT TO THE PARENT DYING. A child of a killed parent is
// re-parented and keeps running, so an app that is force-quit would leave a
// runtime behind with no way to reach it. The handle terminates it explicitly,
// and `atexit` covers the paths that do not run a clean shutdown.

import Foundation

final class RuntimeHost {

    private var proc: Process?
    private static var shared: RuntimeHost?

    /// The interpreter. `python3.13`, and NOT `python3`.
    ///
    /// The system 3.9 dies on `tomllib`, and several gates in this tree exit 0
    /// while failing on that import -- so a runtime launched with the wrong
    /// interpreter would fail to load its own contracts and report success
    /// doing it. Checked rather than assumed: an absent interpreter is reported,
    /// not silently skipped, because a home with no runtime looks exactly like
    /// a home whose runtime has nothing to say.
    /// Shared with the `--ui-endtoend` mode, which has to launch python as
    /// VESPER rather than from a shell -- see that mode for why.
    static func interpreter() -> String? {
        let candidates = [
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent(".local/bin/python3.13").path,
            "/opt/homebrew/bin/python3.13",
            "/usr/local/bin/python3.13",
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    /// Bundled copy first, repo second.
    ///
    /// Same order as the chrome's markup and for the same reason: a shipped app
    /// has no repo beside it, and a developer wants their edits to be what runs.
    /// The bundled copy is what makes this one app rather than an app that
    /// depends on a checkout being present.
    private static func script() -> (String, String)? {
        if let res = Bundle.main.resourceURL {
            let bundled = res.appendingPathComponent("runtime/tools/ops/vesper_runtime.py")
            if FileManager.default.isReadableFile(atPath: bundled.path) {
                return (bundled.path, res.appendingPathComponent("runtime").path)
            }
        }
        let cwd = FileManager.default.currentDirectoryPath
        let dev = cwd + "/tools/ops/vesper_runtime.py"
        if FileManager.default.isReadableFile(atPath: dev) { return (dev, cwd) }
        return nil
    }

    @discardableResult
    func start() -> String {
        guard proc == nil else { return "already running" }
        guard let py = Self.interpreter() else {
            return "no python3.13 found — the runtime cannot start, so the "
                 + "field will queue what you type and nothing will answer it"
        }
        guard let (path, root) = Self.script() else {
            return "vesper_runtime.py not found in the bundle or the repo"
        }
        // SWEEP ORPHANS FIRST. The runtime holds a lock and refuses to be the
        // second, so this is not what makes it singular -- it is what stops a
        // STALE one from continuing to serve. An orphan from a previous build
        // holds older code and answers the same outbox, and the newest process
        // then loses a race it should never have been in.
        let sweep = Process()
        sweep.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        sweep.arguments = ["-f", "vesper_runtime.py"]
        try? sweep.run()
        sweep.waitUntilExit()

        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [path]
        // THE RUNTIME WORKS IN VESPER'S OWN PLACE, NOT WHERE ITS CODE IS (D6,
        // 2026-09-13). `root` is the bundle's runtime directory, which every
        // build deletes and rewrites; a relative path from a process working
        // there is a file the next build removes. Imports still come from
        // `root` through PYTHONPATH below, so nothing here depends on cwd.
        let work = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VESPER/workspace")
        try? FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
        p.currentDirectoryURL = work
        var env = ProcessInfo.processInfo.environment
        // The runtime imports `core` and `routing` relative to its root.
        env["PYTHONPATH"] = root
        // AND NEVER LET IT WRITE BYTECODE BACK INTO THE BUNDLE. The runtime is
        // inside a SIGNED app: a __pycache__ directory next to these modules
        // invalidates the seal, and macOS then refuses to relaunch VESPER --
        // measured 2026-09-16, four crashes in fourteen seconds after the owner
        // accepted a permission and the system offered to quit and reopen.
        // The LaunchAgent sets this too; here as well, because a home started by
        // hand inherits a shell environment that does not.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        p.environment = env
        do { try p.run() } catch {
            return "the runtime failed to start: \(error)"
        }
        proc = p
        Self.shared = self
        atexit { RuntimeHost.shared?.stop() }
        return "runtime started (pid \(p.processIdentifier)) from \(root)"
    }

    func stop() {
        guard let p = proc, p.isRunning else { return }
        p.terminate()
        proc = nil
    }

    var isRunning: Bool { proc?.isRunning ?? false }
}
