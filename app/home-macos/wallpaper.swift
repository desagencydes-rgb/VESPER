// VESPER — the mode wallpaper as the ACTUAL desktop picture.
//
// The owner, 2026-08-23: "why not just assign the wallpapers in desktop 2
// normally according to modes just like how the normal pc's wallpaper is set
// up?" -- and that is right, and it is better than what HOME-ARCHITECTURE.md
// §1.1 had. It replaces a decision rather than working around one.
//
// WHAT THE OLD SHAPE GOT WRONG. §1.1 put the wallpaper inside the field layer,
// as something VESPER draws into its own full-screen window. That window is real
// and F1 verified its geometry: 1728x1117 at y = 0, the whole frame. But the
// owner then reported the menu bar still showing the system wallpaper, and that
// is not a bug in the window -- THE MENU BAR SAMPLES THE DESKTOP PICTURE, not
// the windows under it. §2.2 claimed the opposite, and its own last sentence was
// the clue nobody followed:
//
//   "the translucent menu bar sits over it, tinted by whatever ambience is
//    running. That is exactly what the desktop picture already does on this
//    machine."
//
// It IS what the desktop picture does -- because it is the desktop picture that
// does it. Painting a picture into a window underneath imitates something macOS
// will simply do, and the imitation is visibly worse at the one place they
// differ. It also explains the owner's "not taking full screen": the window does
// reach y = 0, but the menu bar band keeps rendering the old picture, so the
// ground reads as short.
//
// WHAT THIS BUYS beyond the menu bar: Mission Control shows the right Desktop at
// a glance; the picture fills correctly at any size without our own crop code;
// and a full-screen opaque window leaves the compositing path entirely, which
// changes SPIKE-013's question rather than just its answer.
//
// IT IS A CHANGE TO THE OWNER'S MACHINE, so it is reversible by construction:
// --set records the current picture before its first change, --restore puts it
// back. The recording is not a courtesy; it is the difference between a setting
// and a loss.

import AppKit

let args = CommandLine.arguments
let ws = NSWorkspace.shared
guard let screen = NSScreen.main else { fatalError("no screen") }

func repoRoot() -> String {
    URL(fileURLWithPath: args[0]).deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().path
}
let SAVED = URL(fileURLWithPath: args[0]).deletingLastPathComponent()
    .appendingPathComponent("wallpaper_before_vesper.txt").path

func current() -> URL? { ws.desktopImageURL(for: screen) }

func show() {
    print("\n  screen : \(Int(screen.frame.width))x\(Int(screen.frame.height)) points")
    print("  current desktop picture (THIS Space):")
    print("    \(current()?.path ?? "— none reported —")")
    if let o = ws.desktopImageOptions(for: screen), !o.isEmpty {
        print("  options: \(o.map { "\($0.key.rawValue)=\($0.value)" }.joined(separator: ", "))")
    }
    if FileManager.default.fileExists(atPath: SAVED),
       let s = try? String(contentsOfFile: SAVED, encoding: .utf8) {
        print("  saved original: \(s.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
    print("")
}

@discardableResult
func set(_ mode: String) -> Bool {
    let dir = repoRoot() + "/docs/design/assets/wallpapers/"
    var target: URL? = nil
    for ext in ["png", "jpg", "avif"] {
        let p = dir + mode.lowercased() + "." + ext
        if FileManager.default.fileExists(atPath: p) { target = URL(fileURLWithPath: p); break }
    }
    guard let url = target else { print("  no wallpaper for mode '\(mode)'"); return false }

    // Record BEFORE changing, and only the first time, so repeated mode changes
    // never overwrite the owner's original with one of ours.
    if !FileManager.default.fileExists(atPath: SAVED), let c = current() {
        try? c.path.write(toFile: SAVED, atomically: true, encoding: .utf8)
        print("  saved your original: \(c.path)")
    }
    let opts: [NSWorkspace.DesktopImageOptionKey: Any] = [
        // Fill the screen, no empty space, no reshaping -- the owner's rule,
        // handed to the window server instead of done by hand in our crop code.
        .imageScaling: NSImageScaling.scaleProportionallyUpOrDown.rawValue,
        .allowClipping: true
    ]
    do { try ws.setDesktopImageURL(url, for: screen, options: opts) }
    catch { print("  FAILED: \(error.localizedDescription)"); return false }

    // Re-read the world after acting. The call not throwing is its own report;
    // desktopImageURL(for:) is the world's.
    let now = current()
    if now?.path == url.path {
        print("  set  → \(url.lastPathComponent)   CONFIRMED by reading it back")
        return true
    }
    print("  set  → \(url.lastPathComponent)")
    print("  *** reading back gives \(now?.path ?? "nil") — NOT confirmed ***")
    return false
}

func restore() {
    guard let s = try? String(contentsOfFile: SAVED, encoding: .utf8) else {
        print("  nothing saved — VESPER has not changed this Space's picture"); return
    }
    let p = s.trimmingCharacters(in: .whitespacesAndNewlines)
    do { try ws.setDesktopImageURL(URL(fileURLWithPath: p), for: screen, options: [:]) }
    catch { print("  FAILED: \(error.localizedDescription)"); exit(1) }
    try? FileManager.default.removeItem(atPath: SAVED)
    print("  restored → \(p)")
}

switch args.dropFirst().first {
case "--set":     set(args.count > 2 ? args[2] : "home")
case "--restore": restore()
case "--cycle":
    let modes = ["home","idle","watch","listening","thinking","working",
                 "flow","speaking","alert","rest","milestone"]
    print("\n  cycling \(modes.count) modes on THIS Space, 3 s each\n")
    for m in modes { set(m); Thread.sleep(forTimeInterval: 3.0) }
    print("\n  done — `wallpaper --restore` puts your own picture back\n")
default: show()
}
