// VESPER — the eleven ambience modes, and the wallpaper as the real desktop
// picture. Promoted out of `wallpaper.swift` and `ambience.swift`, which were
// probes, into the app that has to live with the consequences.
//
// THE OWNER REPLACED A DECISION HERE, 2026-08-23: "why not just assign the
// wallpapers in desktop 2 normally according to modes just like how the normal
// pc's wallpaper is set up?"
//
// HOME-ARCHITECTURE §1.1 had the wallpaper inside the field layer, painted by
// VESPER into its own full-screen window. F1 verified that window's geometry --
// 1728x1117 at y = 0, the whole frame -- and the owner still reported the menu
// bar showing the old picture, because THE MENU BAR SAMPLES THE DESKTOP
// PICTURE, not the windows beneath it. Painting a picture into a window
// underneath imitates something macOS simply does, and the imitation is
// visibly worse at the one place they differ.
//
// So the ground carries no wallpaper at all. It is transparent, and what is
// behind the face is the window server's own desktop.
//
// IT IS A CHANGE TO THE OWNER'S MACHINE, so it is reversible by construction:
// the first `apply` records the picture that was there, and `restore` puts it
// back. The recording is not a courtesy -- it is the difference between a
// setting and a loss.

import AppKit

struct Mode {
    let key: String        // "hall"      -- the image's own name
    let name: String       // "Home"      -- what it is called
    let when: String       // when this mode is the right one
    let accent: NSColor
    let ground: NSColor
    let ink: NSColor
    let prov: String       // "measured" | "curated" -- NEVER collapse these
    let light: Bool        // is this a light frame

    /// The wallpaper file, by lowercased name. Extensions differ per mode
    /// because the sources differ (png / jpg / avif); the caller does not
    /// need to know which, only that one exists or the mode is unusable.
    func wallpaper(in dir: String) -> URL? {
        for ext in ["png", "jpg", "jpeg", "avif", "heic"] {
            let p = dir + "/" + name.lowercased() + "." + ext
            if FileManager.default.fileExists(atPath: p) { return URL(fileURLWithPath: p) }
        }
        return nil
    }

    /// The moving version of this wallpaper, when the mode has one.
    ///
    /// THREE OF THE ELEVEN HAVE ONE -- `milestone`, `rest` and `speaking` --
    /// and until 2026-09-10 nothing in the app opened any of them. They shipped
    /// beside the stills, in the same folder, named by the same convention, and
    /// were reachable from no code path at all.
    ///
    /// AND THEY COULD NOT HAVE BEEN REACHED THROUGH THE OLD ROUTE.
    /// `setDesktopImageURL` takes a still image; there is no argument for a
    /// movie. So the animation requirement is not an addition to the desktop-
    /// picture approach, it is a second independent reason that approach had to
    /// go -- vesper paints its own ground layer now, and a layer can hold a
    /// video as easily as an image.
    func animated(in dir: String) -> URL? {
        let p = dir + "/" + name.lowercased() + "_animated.mp4"
        return FileManager.default.fileExists(atPath: p)
             ? URL(fileURLWithPath: p) : nil
    }
}

enum Ambience {

    /// Where the repo is, asked in the order that degrades honestly.
    ///
    /// The wallpapers are 44 MB of authored source and are NOT copied into the
    /// bundle, deliberately: `build.sh` begins with `rm -rf "$APP"`, and macOS
    /// stores the desktop picture as a persistent URL. A picture pointing into
    /// the bundle would be pointing at a deleted file after the next build,
    /// and the owner's desktop would break for a reason nothing on screen
    /// explains. The repo path survives a rebuild; the bundle path does not.
    static func repoRoot() -> String? {
        let fm = FileManager.default
        func isRepo(_ p: String) -> Bool {
            fm.fileExists(atPath: p + "/docs/design/assets/wallpapers")
        }
        if let e = ProcessInfo.processInfo.environment["VESPER_REPO"], isRepo(e) { return e }
        let cwd = fm.currentDirectoryPath
        if isRepo(cwd) { return cwd }
        // Walk up from the executable: covers the loose-binary dev loop, where
        // the binary sits at <repo>/app/island-macos/island.
        var u = URL(fileURLWithPath: CommandLine.arguments[0],
                    relativeTo: URL(fileURLWithPath: cwd)).standardizedFileURL
        for _ in 0..<8 {
            u = u.deletingLastPathComponent()
            if u.path.isEmpty || u.path == "/" { break }
            if isRepo(u.path) { return u.path }
        }
        return nil
    }

    static func wallpaperDir() -> String? {
        repoRoot().map { $0 + "/docs/design/assets/wallpapers" }
    }

    // MARK: - The catalogue

    private static var cache: [Mode]?

    /// The eleven, read from the file every surface reads. Never hardcoded
    /// here: `modes.json` is generated by `docs/design/source/final.py` from
    /// the owner's own images, and a second copy of these numbers in Swift
    /// would drift from it silently.
    static func modes() -> [Mode] {
        if let c = cache { return c }
        guard let root = repoRoot(),
              let data = FileManager.default.contents(
                  atPath: root + "/docs/design/source/modes.json"),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
        else { cache = []; return [] }

        let out: [Mode] = raw.compactMap { m in
            guard let key = m["key"] as? String, let name = m["mode"] as? String
            else { return nil }
            return Mode(key: key,
                        name: name,
                        when: (m["when"] as? String) ?? "",
                        accent: hex(m["accent"] as? String) ?? .white,
                        ground: hex(m["ground"] as? String) ?? .black,
                        ink:    hex(m["ink"]    as? String) ?? .white,
                        prov:  (m["prov"] as? String) ?? "unknown",
                        light: (m["light"] as? Bool) ?? false)
        }
        cache = out
        return out
    }

    static func mode(named n: String) -> Mode? {
        modes().first { $0.name.lowercased() == n.lowercased() }
    }

    static func hex(_ s: String?) -> NSColor? {
        guard var h = s else { return nil }
        if h.hasPrefix("#") { h.removeFirst() }
        guard h.count == 6, let v = Int(h, radix: 16) else { return nil }
        return NSColor(srgbRed: CGFloat((v >> 16) & 255) / 255,
                       green:   CGFloat((v >> 8) & 255) / 255,
                       blue:    CGFloat(v & 255) / 255, alpha: 1)
    }

    // MARK: - Reading the backdrop

    /// Mean luminance and variance of the desktop picture, inside one region of
    /// the SCREEN, sampled from the image file.
    ///
    /// DESIGN-FOUNDATION §3 step 1 says to sample the backdrop before choosing
    /// anything that sits on it. For a webview that means reading pixels behind
    /// the glass, which on macOS means a screen recording and a TCC grant. It
    /// does not mean that here: VESPER SET this wallpaper, so the backdrop is a
    /// file we already own the path to. No permission, no capture, and the
    /// answer is exact rather than sampled off a composite.
    ///
    /// The aspect-fill crop has to be reproduced or the samples come from the
    /// wrong part of the picture. `apply` sets `scaleProportionallyUpOrDown`
    /// with clipping, which is fill-and-centre-crop, and 13% of a 16:9 source is
    /// thrown away on this display -- so a region taken at image coordinates
    /// would be reading a part of the picture the owner cannot see.
    static func backdropStats(url: URL, region: CGRect, screen: NSScreen)
        -> (mean: Double, variance: Double)? {
        guard let img = NSImage(contentsOf: url)?
                .cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        let iw = CGFloat(img.width), ih = CGFloat(img.height)
        let sw = screen.frame.width, sh = screen.frame.height
        guard iw > 0, ih > 0, sw > 0, sh > 0 else { return nil }

        // Draw the picture into a small buffer the size of the REGION, with the
        // same fill-and-centre-crop the window server used. Sampling a scaled
        // draw rather than indexing the original is what keeps the crop honest.
        let w = 64, h = 64
        let n = w * h * 4
        let data = UnsafeMutablePointer<UInt8>.allocate(capacity: n)
        defer { data.deallocate() }
        data.initialize(repeating: 0, count: n)
        guard let ctx = CGContext(data: data, width: w, height: h, bitsPerComponent: 8,
                                  bytesPerRow: w * 4,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                                            | CGBitmapInfo.byteOrder32Big.rawValue)
        else { return nil }
        let scale = max(sw / iw, sh / ih)
        let dw = iw * scale, dh = ih * scale
        // Where the whole picture lands in screen coordinates...
        let ox = (sw - dw) / 2, oy = (sh - dh) / 2
        // ...then move that so the requested region fills the buffer.
        let k = CGFloat(w) / region.width
        ctx.scaleBy(x: k, y: CGFloat(h) / region.height)
        ctx.translateBy(x: -region.origin.x, y: -region.origin.y)
        ctx.draw(img, in: CGRect(x: ox, y: oy, width: dw, height: dh))

        var sum = 0.0, sumSq = 0.0
        for i in 0..<(w * h) {
            let o = i * 4
            let l = 0.2126 * Double(data[o]) / 255
                  + 0.7152 * Double(data[o + 1]) / 255
                  + 0.0722 * Double(data[o + 2]) / 255
            sum += l; sumSq += l * l
        }
        let mean = sum / Double(w * h)
        return (mean, max(0, sumSq / Double(w * h) - mean * mean))
    }

    // MARK: - The desktop picture

    /// Where the owner's own picture is recorded before VESPER first replaces
    /// it. Application Support, not the bundle -- a rebuild must not be able
    /// to destroy the only record of what to put back.
    static var savedOriginalPath: String {
        let dir = (NSSearchPathForDirectoriesInDomains(
            .applicationSupportDirectory, .userDomainMask, true).first
            ?? NSTemporaryDirectory()) + "/VESPER"
        try? FileManager.default.createDirectory(atPath: dir,
              withIntermediateDirectories: true)
        return dir + "/wallpaper_before_vesper.txt"
    }

    static func currentPicture(_ screen: NSScreen) -> URL? {
        NSWorkspace.shared.desktopImageURL(for: screen)
    }

    // `apply` IS GONE, AND ITS ABSENCE IS THE FEATURE.
    //
    // It set the system desktop picture for a mode. `setDesktopImageURL` has no
    // Space argument -- it repaints whichever Space is showing -- and a residency
    // guard in front of it was not enough: MEASURED 2026-09-10 from macOS's own
    // wallpaper store, ALL THREE of the owner's live Desktops were holding a
    // VESPER image, 37 of 42 entries in the store were ours, and the record that
    // was supposed to allow undoing it was empty.
    //
    // OWNER, 2026-09-10: *"i would like the default wallpaper from mac os that i
    // will apply everywhere to be separate from vesper's wallpaper system, and
    // viseversa, nothing touches the other's"*. Vesper paints its own ground
    // layer now, which cannot reach another Space by construction. The one write
    // path left in this file is `restore`, and the owner is the only caller.


    // `restore` IS GONE TOO, AND FOR A BETTER REASON THAN `apply` WAS.
    //
    // It existed to put the owner's own picture back after vesper had replaced
    // it. Vesper no longer replaces it, so there is nothing to put back -- and
    // the record it read from could never be populated again, because the only
    // thing that ever wrote it was `apply`, saving the picture it was about to
    // overwrite.
    //
    // KEEPING IT WOULD HAVE BEEN THE WORSE CHOICE. A reversal path for an action
    // nobody takes is dead code that still holds a live `setDesktopImageURL`,
    // and that call is the entire hazard: no Space argument, repaints whatever
    // is showing. One caller is one more than zero, and zero is now expressible.
    //
    // THE EXISTING DAMAGE IS THE OWNER'S TO CLEAR, ONCE. 37 entries in macOS's
    // wallpaper store hold a vesper image, including all three live Desktops.
    // `setDesktopImageURL` could only ever have fixed the Space that was
    // showing, so undoing it from here meant visiting each Desktop in turn.
    // System Settings > Wallpaper applies across Spaces in one act, and after
    // this file stopped writing there, nothing will undo it again.

}
