// VESPER — does SpaceWatch.Anchor actually change what fingerprint() sees?
//
// §9f: the empty-Desktop poll read Desktop 1's windows while the owner was on
// Desktop 2, and the suspected cause is that VESPER had no `.managed` window
// anywhere at that moment. This probe isolates exactly that variable: read
// fingerprint() with zero windows, create the anchor, read it again. Nothing
// else in the real app runs, so a difference here is the anchor's doing and
// nothing else's.
//
// OWNER-DRIVEN, same as `residency_probe`: there is no public API to switch
// Spaces from here, so the read is only informative if you are NOT on
// Desktop 1 when you run it, with something open on Desktop 1 at the time.

import AppKit

struct Seen { let owner: String; let layer: Int; let number: Int; let pid: Int }

func onScreen() -> [Seen] {
    guard let raw = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
            as? [[String: Any]] else { return [] }
    return raw.compactMap { w in
        guard let n = w[kCGWindowNumber as String] as? Int,
              let l = w[kCGWindowLayer as String] as? Int,
              let p = w[kCGWindowOwnerPID as String] as? Int else { return nil }
        return Seen(owner: (w[kCGWindowOwnerName as String] as? String) ?? "?", layer: l, number: n, pid: p)
    }
}

func fingerprint() -> Set<Int> {
    let me = Int(ProcessInfo.processInfo.processIdentifier)
    return Set(onScreen().filter { $0.pid != me && $0.layer == 0 }.map(\.number))
}

func describe(_ label: String) {
    let all = onScreen()
    let me = Int(ProcessInfo.processInfo.processIdentifier)
    let foreign = all.filter { $0.pid != me && $0.layer == 0 }
    print("\(label): \(foreign.count) foreign window(s)")
    for w in foreign.prefix(10) {
        print("    \(w.owner)  #\(w.number)  layer \(w.layer)")
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

print("anchor_probe: pid \(ProcessInfo.processInfo.processIdentifier)")
describe("before anchor")

final class AnchorForProbe {
    let window: NSWindow
    init() {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1, height: 1),
                          styleMask: [.borderless], backing: .buffered, defer: false)
        w.isReleasedWhenClosed = false
        w.alphaValue = 0
        w.ignoresMouseEvents = true
        w.hasShadow = false
        w.collectionBehavior = [.managed]
        w.orderFrontRegardless()
        window = w
    }
}

let anchor = AnchorForProbe()

// One run-loop turn so the window server has registered the new window before
// the next read -- `orderFrontRegardless` returning is not proof it has.
RunLoop.main.run(until: Date().addingTimeInterval(0.3))

describe("after anchor")
print("anchor_probe: done")
exit(0)
