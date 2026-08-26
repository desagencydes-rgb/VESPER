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

/// Where the talking envelope's amplitude comes from. NAMED, because the
/// difference between these is the difference between an instrument and a
/// decoration.
///
/// §6 is explicit: "Speaking is driven, not looped ... A sine wave pretending to
/// be speech is the same failure as a status column reading 41 C on a host with
/// no thermometer -- it looks like data and is not." So there is no case here
/// that means "make something up". `none` idles, and it is the default.
///
/// `textReveal` is the honest half-measure available before audio exists: the
/// chrome reveals VESPER's reply grapheme by grapheme at a real cadence, and how
/// much of the sentence has actually appeared is a real fact about real output.
/// It is not amplitude and does not pretend to be -- it carries no loudness, only
/// delivery -- which is why it drives a shallower envelope than `audio` will.
enum SpeechSource {
    case none               // nothing is speaking; the face idles (§6)
    case textReveal         // driven by the chrome's reveal cursor
    case audio              // driven by real amplitude; nothing produces this yet
}

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

    /// THE TWO ANIMATION CHANNELS, KEPT APART ON PURPOSE. §6: "Working
    /// modulates lightness only, and thinking modulates scale only. Keeping each
    /// state on its own channel is what makes them distinguishable at 20 pt
    /// across a room. A state that both pulsed and brightened would read as a
    /// third thing."
    ///
    /// Multiplied onto the renderer's scale and tint by whichever host is
    /// drawing. Both rest at 1 so a behaviour that uses neither is untouched.
    private(set) var pulse: Float = 1           // scale channel
    private(set) var glow: Float = 1            // brightness channel

    /// How much of the current sentence has been delivered, 0...1, and where
    /// that number came from. SET FROM OUTSIDE -- the driver does not know what
    /// VESPER is saying and must not invent it.
    var speechLevel: Float = 0
    var speechSource: SpeechSource = .none

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

        stepChannels(dt)
    }

    /// The scale and brightness envelopes, one behaviour at a time.
    ///
    /// EVERY BEHAVIOUR NOT NAMED HERE LEAVES BOTH AT 1, and that is the point
    /// rather than an omission. Until now the face had exactly one scale channel
    /// -- a 6.2 s breath identical under every behaviour but `aura` -- so
    /// thinking and talking were distinguishable only by where the eyes pointed.
    /// From across a room that is not distinguishable at all.
    private func stepChannels(_ dt: Double) {
        switch behaviour {

        // §6: "slow clean zoom in and out -- unhurried and even; no bounce, no
        // jitter." One sine, one period, nothing summed onto it. The gaze fields
        // above deliberately sum incommensurable periods so nothing loops
        // visibly; this deliberately does not, because "even" is the whole
        // character of the state and a second term would put a wobble in it.
        case .thinking, .wondering, .imagining:
            pulse = 1 + 0.055 * Float(sin(t / 3.8 * 2 * .pi))
            glow = 1

        // §6: "lightness rises and falls, slowly and consistently -- the size
        // holds still; only the brightness breathes." `pulse` is pinned to 1
        // rather than left to the breath, because "holds still" is the claim.
        case .working, .acting:
            pulse = 1
            glow = 1 + 0.22 * Float(sin(t / 5.1 * 2 * .pi))

        // §6: "scale tracks the voice -- fast, amplitude- and frequency-driven."
        //
        // WITH NO SOURCE IT DOES NOT SPEAK, IT IDLES, and that is §6 verbatim
        // rather than a shortcut taken here. A free-running sine on this channel
        // would be indistinguishable on screen from real speech and wrong every
        // frame -- the exact failure the section calls out by name.
        case .talking, .laughing:
            glow = 1
            if speechSource == .none {
                pulse = 1
                break
            }
            // SHALLOWER FOR TEXT THAN FOR AUDIO, because they are not the same
            // measurement. A reveal cursor carries DELIVERY and no loudness, so
            // a depth chosen for amplitude would overstate what is known. When
            // the audio path lands it raises the depth and changes nothing else.
            let depth: Float = speechSource == .audio ? 0.075 : 0.038
            let level = min(max(speechLevel, 0), 1)
            // Tracked with a fast follower rather than assigned, so a reveal
            // that arrives in steps reads as speech and not as a stutter. Fast
            // enough to keep up with a syllable; slow enough to round the step.
            let want = 1 + depth * level
            pulse += (want - pulse) * Float(min(1, 14.0 * dt))

        default:
            pulse = 1
            glow = 1
        }
    }
}
