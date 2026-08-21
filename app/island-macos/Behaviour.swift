// What the face is doing, and how that looks.
//
// The owner's vocabulary, 2026-08-21: looking, thinking, acting, working,
// resting, wondering, imagining, talking, listening, laughing, joking, angry,
// happy, aura. Each is a behaviour, not a canned clip -- the face is animated
// continuously while VESPER works, so these are motion FIELDS sampled forever,
// never timelines that end.
//
// THE ENVELOPE IS ALREADY DECIDED AND IS NOT RE-OPENED HERE. §8: yaw +/-18,
// pitch +/-12, eyes +/-25 beyond the head, eyes lead by 80 ms, return to centre
// after 1.2 s idle, blink every 3-7 s for 120 ms and never mid-sentence. A
// behaviour chooses WHERE to look and HOW URGENTLY; it may not exceed the
// envelope, and the clamp lives in one place so none of them can.

import Foundation

enum Behaviour: String, CaseIterable {
    case looking, thinking, acting, working, resting, wondering, imagining
    case talking, listening, laughing, joking, angry, happy, aura
}

struct Gaze { var yaw: Float; var pitch: Float }

final class FaceDriver {
    static let maxYaw: Float = 18 * .pi / 180
    static let maxPitch: Float = 12 * .pi / 180
    static let maxEye: Float = 25 * .pi / 180
    static let eyeLead: Double = 0.080          // seconds the eyes arrive first

    var behaviour: Behaviour = .resting
    var speaking = false                        // gates blinking; see §8
    private(set) var headYaw: Float = 0, headPitch: Float = 0
    private(set) var eyeYaw: Float = 0, eyePitch: Float = 0
    private(set) var blink: Float = 0
    private(set) var breath: Float = 1

    private var t: Double = 0
    private var history: [(Double, Gaze)] = []
    private var nextBlink: Double = 3
    private var blinkStart: Double = -1

    /// Where this behaviour wants to look at time `t`, in units of the envelope.
    /// Sums of incommensurable periods, so nothing loops visibly -- a face on a
    /// four-second loop is a screensaver, and this is on screen all day.
    private func target(_ t: Double) -> Gaze {
        func w(_ p: Double, _ ph: Double = 0) -> Float { Float(sin(t / p * 2 * .pi + ph)) }
        switch behaviour {
        case .resting:    return Gaze(yaw: 0.25 * w(11.3), pitch: 0.20 * w(9.1, 1.2) - 0.15)
        case .looking:    return Gaze(yaw: 0.85 * w(4.7) + 0.20 * w(1.9), pitch: 0.35 * w(6.1))
        case .thinking:   return Gaze(yaw: -0.55 + 0.22 * w(7.3), pitch: 0.70 + 0.18 * w(5.2))
        case .wondering:  return Gaze(yaw: 0.60 * w(8.9) + 0.25 * w(3.3), pitch: 0.55 + 0.25 * w(6.7))
        case .imagining:  return Gaze(yaw: 0.70 * w(13.1), pitch: 0.60 + 0.30 * w(7.9, 0.8))
        case .working:    return Gaze(yaw: 0.15 * w(5.9), pitch: -0.62 + 0.10 * w(4.1))
        case .acting:     return Gaze(yaw: 0.55 * w(2.3), pitch: -0.20 + 0.25 * w(1.7))
        case .listening:  return Gaze(yaw: 0.18 * w(6.3), pitch: 0.12 + 0.08 * w(4.9))
        case .talking:    return Gaze(yaw: 0.30 * w(2.9) + 0.12 * w(1.3), pitch: 0.18 * w(2.1))
        case .laughing:   return Gaze(yaw: 0.20 * w(1.1), pitch: 0.75 + 0.30 * Float(abs(sin(t * 7.5))))
        case .joking:     return Gaze(yaw: 0.45 + 0.30 * w(3.7), pitch: 0.30 * w(2.7))
        case .angry:      return Gaze(yaw: 0.30 * w(1.9), pitch: -0.55 + 0.12 * w(1.3))
        case .happy:      return Gaze(yaw: 0.35 * w(5.3), pitch: 0.40 + 0.15 * w(3.9))
        case .aura:       return Gaze(yaw: 0.10 * w(17.0), pitch: 0.10 * w(14.0))
        }
    }

    /// How urgently the head follows. Urgency belongs to the behaviour.
    private var responsiveness: Float {
        switch behaviour {
        case .acting, .angry, .laughing: return 9.0
        case .talking, .happy, .joking:  return 6.0
        case .looking, .listening:       return 4.5
        case .thinking, .wondering, .working, .imagining: return 2.6
        case .resting, .aura:            return 1.4
        }
    }

    func step(_ dt: Double) {
        t += dt
        let g = target(t)

        // THE EYES ARRIVE FIRST, and not as an impression of the idea: the head
        // reads the gaze target from 80 ms ago out of a delay line while the eyes
        // read it now. Move them together and it reads as a turret.
        history.append((t, g))
        while history.count > 2, history[1].0 <= t - FaceDriver.eyeLead { history.removeFirst() }
        let delayed = history.first?.1 ?? g

        let k = responsiveness
        headYaw += (delayed.yaw * FaceDriver.maxYaw - headYaw) * min(1, k * Float(dt))
        headPitch += (delayed.pitch * FaceDriver.maxPitch - headPitch) * min(1, k * Float(dt))
        let ey = g.yaw * FaceDriver.maxEye, ep = g.pitch * FaceDriver.maxEye
        eyeYaw += (ey - headYaw - eyeYaw) * min(1, (k + 6) * Float(dt))
        eyePitch += (ep - headPitch - eyePitch) * min(1, (k + 6) * Float(dt))

        // Blink: every 3-7 s, 120 ms, and NEVER mid-sentence.
        if blinkStart < 0, t > nextBlink, !speaking { blinkStart = t }
        if blinkStart >= 0 {
            let p = (t - blinkStart) / 0.120
            if p >= 1 {
                blink = 0; blinkStart = -1; nextBlink = t + Double.random(in: 3...7)
            } else {
                blink = Float(sin(p * .pi))          // shut and open again inside 120 ms
            }
        }

        // A slow scale breath, so the cloud is never perfectly static. `aura` is
        // the behaviour that is nothing but this.
        let depth: Float = behaviour == .aura ? 0.045 : 0.014
        breath = 1 + depth * Float(sin(t / (behaviour == .aura ? 3.4 : 6.2) * 2 * .pi))
    }
}
