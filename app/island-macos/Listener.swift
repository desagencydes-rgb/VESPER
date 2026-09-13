// Speech-in. The half SR-046 calls primary and that nothing had built.
//
// `Intake.spoken()` has existed since the intake layer was written, with
// `final` and `confidence` on every utterance, and until 2026-08-30 it was
// called by NOTHING. That was deliberate -- the typed path was given the shape
// of the spoken one so that voice would arrive as a SOURCE rather than as a
// rewrite. This is the file that collects on that.
//
// ONE LINE DECIDES WHETHER THE OWNER'S VOICE LEAVES THIS MACHINE, and it is
// `requiresOnDeviceRecognition`. The API's default is FALSE -- meaning "use
// Apple's servers if you feel like it" -- and the transcription is equally good
// either way, so an implementation that omits it works perfectly and silently
// egresses every word spoken in the room. Measured on this Mac 2026-08-30:
// `supportsOnDeviceRecognition` is TRUE for en-US and FALSE for ar-MA, ar-SA
// and fr-FR. So English can be held here and Darija cannot, and the honest
// consequence is that Darija speech-in needs a route that passes through
// `ModelGateway` where the redactor lives -- not Apple's, which passes through
// nothing this repository can see.
//
// THIS FILE THEREFORE REFUSES RATHER THAN DEGRADES. If on-device is
// unavailable for the requested locale it stops and says so. Falling back to
// server recognition would be a silent change in where the owner's voice goes,
// decided by a library, at runtime, with no event.
//
// CONFIDENCE IS REPORTED, NOT INVENTED. Apple populates per-segment confidence
// on FINAL results only, and on-device results can report 0.0. `intake.py`'s
// floor is marked UNMEASURED for exactly this reason: nothing has yet watched
// this recogniser on this owner's voice in this room. `--diagnose` prints the
// confidences observed so the floor can be set from evidence instead of from a
// paper.

import Foundation
import AVFoundation
import Speech

private let outbox = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/VESPER/say.jsonl")

private func appendOutbox(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj),
          var line = String(data: data, encoding: .utf8) else { return }
    line += "\n"
    // APPEND WITHOUT LOCKING, which the runtime already expects: its reader
    // breaks on a torn last line and does not advance past it, so the next pass
    // sees the line whole. Matching that contract rather than inventing a lock
    // keeps one writer's assumption from becoming two.
    if let h = try? FileHandle(forWritingTo: outbox) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    } else {
        try? FileManager.default.createDirectory(
            at: outbox.deletingLastPathComponent(),
            withIntermediateDirectories: true)
        try? line.write(to: outbox, atomically: true, encoding: .utf8)
    }
}

// LAUNCHED WITH `open -n`, SO STDOUT GOES NOWHERE. Same lesson as
// SpeechConsent.swift and learned the same way: run from a shell this reports
// "speech recognition is not authorized" even though the BUNDLE holds the
// grant, because TCC checks the responsible process and the shell has only the
// microphone permission it inherited. A listener whose findings nobody can read
// is the buffered-probe failure this corpus already records.
private let listenReport = URL(fileURLWithPath: "/tmp/vesper-listen.txt")

// INTERNAL, not private: `WakeWord.swift` reports through the same file. Two
// reporters would mean two places to look when the listener goes quiet, and the
// one nobody checked would be the one holding the answer.
func note(_ line: String) {
    print(line)
    let stamped = line + "\n"
    if let h = try? FileHandle(forWritingTo: listenReport) {
        h.seekToEndOfFile(); h.write(stamped.data(using: .utf8)!); try? h.close()
    } else {
        try? stamped.write(to: listenReport, atomically: true, encoding: .utf8)
    }
}

/// Peak and RMS of one buffer, in dBFS. Measurement only -- nothing is changed.
///
/// §9g, owner 2026-09-07: *"vesper's microphone is working, but it still doesn't
/// hear me, i need to be screaming just so it can hear me."* The plan records
/// the capture path as having "no gain stage, no normalisation, no level
/// measurement and no automatic gain control anywhere in the file", and marks
/// the step MEASURE FIRST.
///
/// SO THIS MEASURES AND DOES NOT CORRECT. A gain applied before anyone has read
/// a level is a number chosen by guess, which is what `INV-HW-2` exists to
/// refuse -- and if the real cause is the system input volume or the wrong
/// input device, a software gain would amplify the noise floor and hide it.

/// What the microphone is actually delivering, kept so it can be reported.
///
/// BOUNDED AND CHEAP. Two floats and a count per buffer; a tap runs hundreds of
/// times a second and anything that allocates here is a cost paid forever.
final class Levels {
    static let shared = Levels()
    private let lock = NSLock()
    private var peak: Float = 0
    private var rmsSum: Float = 0
    private var n: Int = 0

    func observe(peak p: Float, rms r: Float) {
        lock.lock(); defer { lock.unlock() }
        if p > peak { peak = p }
        rmsSum += r
        n += 1
    }

    /// Peak dBFS, mean RMS dBFS, and how many buffers it was measured over.
    /// Returns nil when nothing has been heard -- an absence, never a zero.
    func reading() -> (peakDb: Float, rmsDb: Float, buffers: Int)? {
        lock.lock(); defer { lock.unlock() }
        if n == 0 { return nil }
        return (dbfs(peak), dbfs(rmsSum / Float(n)), n)
    }
}

func bufferLevel(_ buf: AVAudioPCMBuffer) -> (peak: Float, rms: Float) {
    guard let ch = buf.floatChannelData else { return (0, 0) }
    let n = Int(buf.frameLength)
    if n == 0 { return (0, 0) }
    var peak: Float = 0
    var sum: Float = 0
    for i in 0..<n {
        let v = abs(ch[0][i])
        if v > peak { peak = v }
        sum += ch[0][i] * ch[0][i]
    }
    return (peak, (sum / Float(n)).squareRoot())
}

func dbfs(_ v: Float) -> Float { v <= 0 ? -120 : 20 * log10(v) }

private func meanConfidence(_ t: SFTranscription) -> Double {
    let segs = t.segments
    guard !segs.isEmpty else { return 0.0 }
    return Double(segs.map { $0.confidence }.reduce(0, +)) / Double(segs.count)
}

final class Listener {
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let recognizer: SFSpeechRecognizer
    private let diagnose: Bool
    private(set) var finalCount = 0

    init?(locale: String, diagnose: Bool) {
        guard let r = SFSpeechRecognizer(locale: Locale(identifier: locale)) else {
            note("no recogniser for \(locale)")
            return nil
        }
        // THE REFUSAL, and it is checked before the microphone is ever opened:
        // capturing audio it would have to send away is worse than not capturing.
        guard r.supportsOnDeviceRecognition else {
            note("REFUSING: \(locale) has no on-device recognition on this "
               + "machine, so every word would go to Apple's servers -- egress "
               + "that bypasses ModelGateway and therefore the redactor. "
               + "Measured 2026-08-30: en-US yes; ar-MA, ar-SA, fr-FR no. "
               + "Route non-English speech through the gateway instead.")
            return nil
        }
        self.recognizer = r
        self.diagnose = diagnose
    }

    func start() throws {
        let req = SFSpeechAudioBufferRecognitionRequest()
        // THE LINE. Without it the default is server-side and nothing looks wrong.
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        request = req

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buf, _ in
            // MEASURED ON THE WAY PAST, NEVER CHANGED HERE. See `bufferLevel`:
            // the level is what §9g asks to be established before anything is
            // corrected, and a tap that quietly amplified would destroy the
            // evidence for the decision.
            let lv = bufferLevel(buf)
            Levels.shared.observe(peak: lv.peak, rms: lv.rms)
            req.append(buf)
        }
        engine.prepare()
        try engine.start()

        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self else { return }
            if let result {
                let text = result.bestTranscription.formattedString
                let conf = result.isFinal ? meanConfidence(result.bestTranscription) : 0.0
                if self.diagnose {
                    note(String(format: "  %@ conf=%.3f  %@",
                                 result.isFinal ? "FINAL  " : "partial",
                                 conf, text))
                }
                // PARTIALS ARE SENT TOO. `Intake` buffers them and dispatches
                // only finals -- dispatching every revision would answer four
                // questions nobody asked -- and the owner still sees their own
                // words land while the recogniser is still revising.
                appendOutbox(["text": text, "source": "spoken",
                              "confidence": conf, "final": result.isFinal])
                if result.isFinal { self.finalCount += 1 }
            }
            if error != nil || (result?.isFinal ?? false) {
                self.stop()
            }
        }
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        request?.endAudio()
        task?.cancel()
        task = nil
    }
}

func runListener(locale: String, seconds: Double, diagnose: Bool) {
    guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
        note("speech recognition is not authorized as the RESPONSIBLE "
           + "process. Run this with `open -n`, not from a shell: TCC checks "
           + "whoever launched it, and a terminal holds no speech grant.")
        exit(1)
    }
    guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
        note("microphone is not authorized; run --speech-consent first")
        exit(1)
    }
    guard let l = Listener(locale: locale, diagnose: diagnose) else { exit(2) }
    do { try l.start() } catch {
        note("could not start audio: \(error)")
        exit(3)
    }
    note("listening on \(locale), on-device, for \(seconds)s -- speak now")
    RunLoop.current.run(until: Date().addingTimeInterval(seconds))
    l.stop()
    note("stopped after \(l.finalCount) final result(s)")
}

// ---------------------------------------------------------------------------
// RECORDING, for the locales this machine cannot transcribe itself.
//
// `Listener` above refuses to open the microphone when the locale has no
// on-device recogniser, and refuses BEFORE opening it -- capturing audio it
// would have to send away is worse than not capturing. That refusal is right
// and it is also why Darija speech has no path at all through this file.
//
// The decision of 2026-08-31 is that Darija goes through OUR route: capture
// here, transcribe through the gateway, where the egress class and the quota
// are the same ones every other provider obeys. So this records and does not
// recognise. It makes no routing decision and holds no credential; it writes a
// file and says where.
//
// IT IS A SEPARATE ENTRY POINT ON PURPOSE. Adding a "just record" flag to
// `runListener` would put a path that never checks `supportsOnDeviceRecognition`
// inside the function whose whole job is to check it.
/// MEASURE the microphone for `seconds` and print what it delivered. §9g.
///
/// NOTHING IS CORRECTED HERE. The owner reported having to shout; the plan marks
/// the step MEASURE FIRST, and this is that measurement -- what the hardware
/// actually hands the recogniser, in dBFS, before anyone chooses a gain.
///
/// HOW TO READ IT. Speech at a normal desk distance should peak around -12 to
/// -6 dBFS with mean RMS near -30. A peak below about -35 means the signal is
/// genuinely quiet, and the next question is WHERE: the system input volume,
/// the selected input device, or the hardware itself. A software gain applied
/// before that question is answered would raise the noise floor with the voice
/// and hide the cause.
func runMicLevel(seconds: Double, out: String? = nil) {
    // WRITES TO A FILE WHEN ASKED, because `open -n` -- the only launch that
    // carries vesper's own TCC identity -- DISCARDS stdout. `Grants.report(to:)`
    // learned this first; a measurement nobody can read is not a measurement,
    // and reading the microphone from a shell would measure the shell's grant.
    var lines: [String] = []
    func say(_ t: String) {
        print(t)
        lines.append(t)
    }
    func finish(_ code: Int32) -> Never {
        if let out, !out.isEmpty {
            try? lines.joined(separator: "\n").write(toFile: out,
                                                     atomically: true,
                                                     encoding: .utf8)
        }
        exit(code)
    }
    // `init?` -- FAILABLE, and a missing recogniser is a different fact from a
    // quiet microphone. Said separately rather than folded into one message.
    guard let listener = Listener(locale: "en-US", diagnose: false) else {
        say("no speech recogniser for en-US on this node, so the capture "
            + "path cannot be opened to measure it.")
        finish(1)
    }
    do {
        try listener.start()
    } catch {
        say("microphone could not be opened: \(error)")
        finish(1)
    }
    say("measuring for \(Int(seconds))s -- speak normally, at your usual distance.")
    RunLoop.main.run(until: Date().addingTimeInterval(seconds))
    listener.stop()
    guard let r = Levels.shared.reading() else {
        // AN ABSENCE, NEVER A ZERO. No buffers means the tap never fired, which
        // is a different fact from a quiet room and has a different cause.
        say("no audio buffers arrived at all -- the tap never fired. That "
            + "is not a quiet microphone; it is no microphone on this input.")
        finish(1)
    }
    say(String(format: "peak %.1f dBFS, mean rms %.1f dBFS, over %d buffers",
               r.peakDb, r.rmsDb, r.buffers))
    if r.peakDb < -35 {
        say("that is QUIET. Before adding any gain, check the system input "
              + "volume and which input device is selected -- amplifying in "
              + "software would raise the noise floor with the voice.")
    } else {
        say("that is a usable level; if recognition is still poor the "
              + "cause is not the input level.")
    }
    finish(0)
}

func runRecorder(seconds: Double, out: String) {
    guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
        note("microphone is not authorized; run --speech-consent first")
        exit(1)
    }
    note("recording \(seconds)s -> \(out)  -- speak now")
    // ONE RECORDER, in WakeWord.swift, shared with the wake path. Two would
    // drift, and the one that drifted would be the one nobody ran by hand.
    let bytes = recordClip(seconds: seconds, out: out)
    note("recorded \(bytes) bytes")
    if bytes < 4096 {
        note("WARNING: too small to contain speech -- the tap may not have fired")
        exit(4)
    }
}
