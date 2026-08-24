// VESPER — HOME-ARCHITECTURE §10's dock swap, held rather than fired.
//
// "Inside VESPER's workspace the system Dock goes under the screen and VESPER's
// main menu takes its position... VESPER sets NSApplicationPresentationAutoHideDock
// while its window is frontmost -- the same API a fullscreen app uses -- and
// macOS reverts it the moment VESPER stops being frontmost."
//
// THAT LAST CLAUSE IS THE WHOLE DIFFICULTY. macOS reverting the option is not an
// event anybody publishes, and it happens for reasons that have nothing to do
// with the ground's occlusion state. The first implementation fired once on the
// occlusion edge and the owner found both faults it produces:
//
//   1. The Dock FLASHES on every switch in. Nothing began until the ground was
//      confirmed visible, and then a fixed 0.15 s wait ran before the option was
//      set -- with a `guard NSApp.isActive else { return }` that gave up
//      silently if activation had not landed by then.
//
//   2. An ABORTED switch leaves the Dock up for good. Beginning a switch and
//      coming back DEACTIVATES VESPER, macOS reverts the option, and the
//      ground's occlusion never changed -- so an edge-triggered swap has nothing
//      to fire on. The Dock stayed until a real Space change happened by.
//
// Both are one mistake: the desired state was ASSERTED ONCE, when it needed to
// be MAINTAINED. So this states what should be true and makes it true from
// whatever the world currently is, as often as it is asked. Deactivation, an
// aborted switch, a dropped notification and a slow activation all repair
// themselves on the next tick, because none of them is a special case here.
//
// WHY IT IS ITS OWN TYPE. `wants` is injected, so the real reconciler -- not a
// copy of its logic -- can be driven by `--dock-check` with a stub predicate and
// shown to HEAL: set the option, take it away behind its back the way macOS
// does, and watch it come back. A self-healing mechanism that has only ever been
// observed working is not evidence that it heals.

import AppKit

final class DockSwap {

    /// Should the Dock be under the screen right now? Injected, because the
    /// answer is the home's business and the mechanics are not.
    private let wants: () -> Bool
    private let interval: TimeInterval
    private var timer: Timer?

    private(set) var repairs = 0
    private(set) var activations = 0

    init(interval: TimeInterval = 0.25, wants: @escaping () -> Bool) {
        self.wants = wants
        self.interval = interval
    }

    deinit {
        timer?.invalidate()
        NotificationCenter.default.removeObserver(self)
        NSWorkspace.shared.notificationCenter.removeObserver(self)
    }

    func start() {
        guard timer == nil else { return }
        let nc = NotificationCenter.default
        for name in [NSApplication.didBecomeActiveNotification,
                     NSApplication.didResignActiveNotification] {
            nc.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.tick()
            }
        }
        // EARLIER than the ground's own occlusion change, which is what shortens
        // the flash rather than merely repairing it afterwards.
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil, queue: .main) { [weak self] _ in self?.tick() }

        let t = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
        tick()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// One reconciliation. Safe to call as often as you like.
    func tick() {
        let hidden = NSApp.presentationOptions.contains(.autoHideDock)
        if wants() {
            guard NSApp.isActive else {
                // presentationOptions may only be set by the active app, and
                // setting it while inactive RAISES -- a raise here would take
                // the whole home down for a Dock. Activate, and let the next
                // tick set it.
                activations += 1
                NSApp.activate(ignoringOtherApps: true)
                return
            }
            if !hidden {
                repairs += 1
                NSApp.presentationOptions.insert(.autoHideDock)
            }
        } else if NSApp.isActive, hidden {
            NSApp.presentationOptions.remove(.autoHideDock)
        }
    }

    /// Does the Dock currently reserve screen space?
    ///
    /// Re-fetched, never held: an `NSScreen` object caches its geometry, and a
    /// reference taken before a change reports the world as it was. That cost
    /// one wrong diagnosis already -- the swap looked like it had refused to
    /// move when it had already moved.
    static func dockReservesSpace() -> Bool {
        guard let s = NSScreen.main else { return false }
        return s.visibleFrame.minY > s.frame.minY + 1
    }
}
