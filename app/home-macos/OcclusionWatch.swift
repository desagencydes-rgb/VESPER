// VESPER — knowing whether a window is covered, from the window server, on a
// schedule rather than on an edge.
//
// WHAT THIS REPLACES AND WHY, because it reverses a decision HOME-ARCHITECTURE
// §2.6 made deliberately.
//
// §2.6: "Fired on the real notification, never inferred from a timer." The
// ground observed `NSWindow.didChangeOcclusionStateNotification` and stopped
// rendering when it said covered. On 2026-08-24, `SPIKE-013` §1's criterion 4
// measured the ground holding 116.8 fps while a full-screen opaque window sat
// over it, and a delivery counter added to the handler answered why:
//
//   the window server says the ground is COVERED
//   the renderer says it is RUNNING
//   didChangeOcclusionStateNotification has been delivered ZERO times
//
// Not late, not ignored, never delivered. The evidence that had made the
// notification look sound was a POLLING sampler in `HomeVerify` and one
// `onVisibilityChange` call `present()` makes directly -- neither of which
// touches the notification at all. So the deliberate stop, which Home.swift's
// header calls the mechanism the host's lifetime rests on, had never once run.
//
// THE DISTINCTION §2.6 WAS ACTUALLY DEFENDING, and this keeps it.
//
// "Never inferred from a timer" is a rule against GUESSING -- deciding a window
// is probably covered because some seconds have passed. That is not what this
// does. `NSWindow.occlusionState` IS the window server's own answer, and it was
// correct on every reading during the failure; only its DELIVERY was broken.
// The authority does not change here. Only how often we ask.
//
// The notification is kept and counted alongside. If it ever starts arriving it
// is the faster path and costs nothing to have; and if it stays silent, the
// counter says so on every run rather than the mechanism quietly resting on a
// notification that is not coming.

import AppKit

final class OcclusionWatch {

    enum Source: String { case notification, poll, initial }

    private let window: NSWindow
    private let interval: TimeInterval
    private var timer: Timer?
    private(set) var visible: Bool

    private(set) var notificationsDelivered = 0
    private(set) var pollDetections = 0

    /// Called only when the answer CHANGES, with how it was found out.
    var onChange: ((Bool, Source) -> Void)?

    /// `observeNotification: false` is the CONTROL, and it is the only way to
    /// find out whether the poll can carry this alone. With the notification
    /// connected it wins every race -- measured at 0.03 s against a 0.5 s poll
    /// -- so a passing run proves nothing about the fallback that exists
    /// precisely for the case where the notification does not come.
    init(window: NSWindow, interval: TimeInterval = 0.5,
         observeNotification: Bool = true) {
        self.window = window
        self.interval = interval
        self.visible = window.occlusionState.contains(.visible)
        guard observeNotification else { return }
        NotificationCenter.default.addObserver(
            self, selector: #selector(notified),
            name: NSWindow.didChangeOcclusionStateNotification, object: window)
    }

    deinit {
        timer?.invalidate()
        NotificationCenter.default.removeObserver(self)
    }

    func start() {
        guard timer == nil else { return }
        // .common so a tracking loop -- a drag, a menu -- cannot silence the one
        // mechanism that stops a 120 fps renderer.
        let t = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            self?.sample(.poll)
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    @objc private func notified() {
        notificationsDelivered += 1
        sample(.notification)
    }

    private func sample(_ source: Source) {
        let now = window.occlusionState.contains(.visible)
        guard now != visible else { return }
        visible = now
        if source == .poll { pollDetections += 1 }
        onChange?(now, source)
    }

    /// One line for a report: which mechanism is actually carrying this.
    var provenance: String {
        "occlusion: \(notificationsDelivered) notification(s) delivered, "
        + "\(pollDetections) change(s) caught by the \(interval)s poll"
    }
}
