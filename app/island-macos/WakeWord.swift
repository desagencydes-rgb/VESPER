import Foundation
import AVFoundation
import Speech

// WAKE WORD -- always listening, and nothing leaves the machine until it fires.
//
// THAT SPLIT IS THE WHOLE DESIGN, not an optimisation. Continuous listening is
// only defensible if the continuous part is local, and it can be: `en-US` has
// on-device recognition on this machine (measured 2026-08-30) and "vesper" is
// an English-shaped word, so the always-on recogniser never sends a byte
// anywhere. Only AFTER the wake word does audio go out, and then it goes to the
// same E1_PRIVATE transcriber every other private thing uses.
//
// The alternative -- streaming everything to a cloud recogniser and matching
// the wake word there -- would put every conversation in the room, and every
// silence in it, on someone else's machines. `Listener.swift` already refuses
// that for Darija; doing it for a wake word would be the same mistake with a
// friendlier name.
//
// IT RECORDS AND DOES NOT TRANSCRIBE. The captured Darija goes to a queue file
// that the Python runtime drains, because the transcriber holds a credential
// and makes an egress decision, and neither belongs in a process whose job is
// to hold the microphone.

private let heardQueue = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/VESPER/heard.jsonl")

// The phrases that open a turn. Matched case-insensitively against the
// recogniser's running partial, because a wake word that only matched a FINAL
// result would wait for the owner to stop speaking before it started
// listening -- which is the opposite of what a wake word is for.
let WAKE_PHRASES = ["hey vesper", "yo vesper", "ok vesper", "vesper"]

// After the wake word, how long to capture before handing off. Not a guess at
// how long a sentence is: it is restarted by silence below, and this is the
// ceiling.
let WAKE_CAPTURE_SECONDS = 6.0

// A wake word heard twice in this window is one wake word. The recogniser
// revises its partials continuously, so "vesper" appears in a dozen successive
// partials of the same utterance and each would otherwise open a turn.
private let WAKE_DEBOUNCE_S = 3.0

final class WakeListener {
    private let engine = AVAudioEngine()
    private let recognizer: SFSpeechRecognizer
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var lastWake = Date.distantPast
    private var capturing = false
    private let diagnose: Bool
    private(set) var wakeCount = 0

    init?(diagnose: Bool) {
        guard let r = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) else {
            note("no en-US recogniser on this machine"); return nil
        }
        // THE SAME REFUSAL AS Listener.swift, and it has to be repeated here
        // rather than assumed: a wake listener that fell back to server
        // recognition would stream the room continuously, which is strictly
        // worse than the single-utterance case that refusal was written for.
        guard r.supportsOnDeviceRecognition else {
            note("REFUSING: en-US has no on-device recognition here, so a "
               + "wake word would mean streaming the room to Apple's servers")
            return nil
        }
        self.recognizer = r
        self.diagnose = diagnose
    }

    func start() throws {
        try startTask()
        note("wake word active: say \(WAKE_PHRASES.map { "\"\($0)\"" }.joined(separator: ", "))")
    }

    private func startTask() throws {
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true      // THE LINE. Nothing leaves.
        req.shouldReportPartialResults = true
        request = req

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buf, _ in
            req.append(buf)
        }
        engine.prepare()
        try engine.start()

        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self else { return }
            if let result {
                let heard = result.bestTranscription.formattedString.lowercased()
                if self.diagnose { note("  partial: \(heard)") }
                if self.matches(heard) { self.woke() }
            }
            if error != nil || (result?.isFinal ?? false) {
                // A RECOGNITION TASK DOES NOT RUN FOREVER. It ends on silence,
                // on error, and on its own duration limit, and a wake listener
                // that did not restart would go deaf minutes after starting
                // while every status still said "active".
                self.restartSoon()
            }
        }
    }

    private func matches(_ heard: String) -> Bool {
        guard !capturing else { return false }
        guard Date().timeIntervalSince(lastWake) > WAKE_DEBOUNCE_S else { return false }
        return WAKE_PHRASES.contains { heard.contains($0) }
    }

    private func restartSoon() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        task = nil; request = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            guard let self, !self.capturing else { return }
            try? self.startTask()
        }
    }

    // ---------------------------------------------------------------- woke

    private func woke() {
        lastWake = Date(); wakeCount += 1; capturing = true
        note("woke (\(wakeCount)) -- capturing \(WAKE_CAPTURE_SECONDS)s")
        // The wake recogniser must let go of the microphone before the
        // recorder takes it: two taps on one input node is the kind of thing
        // that works on the machine it was written on.
        engine.inputNode.removeTap(onBus: 0)
        engine.stop(); task?.cancel(); task = nil; request = nil

        let out = NSTemporaryDirectory() + "vesper-wake-\(Int(Date().timeIntervalSince1970)).caf"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let bytes = recordClip(seconds: WAKE_CAPTURE_SECONDS, out: out)
            if bytes > 4096 {
                appendHeard(["audio": out, "seconds": WAKE_CAPTURE_SECONDS])
                note("captured \(bytes) bytes -> queued")
            } else {
                // A TAP THAT NEVER FIRED LEAVES A VALID, EMPTY FILE, and
                // queueing it would spend a transcription on silence.
                note("captured only \(bytes) bytes -- not queued")
            }
            DispatchQueue.main.async {
                self?.capturing = false
                try? self?.startTask()
            }
        }
    }
}

/// Records to `out` and returns the file's own byte count. Shared by the wake
/// path and `--record`, so there is one recorder rather than two that drift.
func recordClip(seconds: Double, out: String) -> Int {
    let engine = AVAudioEngine()
    let input = engine.inputNode
    let format = input.outputFormat(forBus: 0)
    guard let file = try? AVAudioFile(forWriting: URL(fileURLWithPath: out),
                                      settings: format.settings) else { return 0 }
    input.installTap(onBus: 0, bufferSize: 1024, format: format) { buf, _ in
        try? file.write(from: buf)
    }
    engine.prepare()
    guard (try? engine.start()) != nil else { return 0 }
    Thread.sleep(forTimeInterval: seconds)
    engine.stop()
    input.removeTap(onBus: 0)
    let n = (try? FileManager.default.attributesOfItem(atPath: out)[.size] as? Int) ?? 0
    return n ?? 0
}

private func appendHeard(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj),
          var line = String(data: data, encoding: .utf8) else { return }
    line += "\n"
    try? FileManager.default.createDirectory(
        at: heardQueue.deletingLastPathComponent(),
        withIntermediateDirectories: true)
    if let h = try? FileHandle(forWritingTo: heardQueue) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    } else {
        try? line.write(to: heardQueue, atomically: true, encoding: .utf8)
    }
}

func runWakeWord(diagnose: Bool) {
    guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
        note("speech recognition is not authorized. Run --speech-consent with "
           + "`open -n`, not from a shell: TCC checks whoever launched it.")
        exit(1)
    }
    guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
        note("microphone is not authorized; run --speech-consent first")
        exit(1)
    }
    guard let w = WakeListener(diagnose: diagnose) else { exit(2) }
    do { try w.start() } catch {
        note("could not start audio: \(error)"); exit(3)
    }
    RunLoop.current.run()
}
