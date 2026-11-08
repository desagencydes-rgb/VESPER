import Foundation
import AVFoundation
import Speech
import CoreAudio
import AppKit

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
    /// The apps playing sound, while vesper's ears are off for them. Empty
    /// means listening.
    private var pausedFor: [String] = []
    private var earsTimer: Timer?

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
        let playing = MacAudio.othersPlaying()
        if playing.isEmpty { try startTask() } else { earsOff(playing) }
        note("wake word active: say \(WAKE_PHRASES.map { "\"\($0)\"" }.joined(separator: ", "))")
        if playing.isEmpty { writeEars(listening: true, because: []) }
        watchTheSpeakers()
    }

    /// EARS OFF WHILE THE MAC PLAYS SOUND, ON WHEN IT STOPS.
    ///
    /// THE OWNER, 2026-11-08: *"if it's not possible [to listen through the
    /// music], make it stop the microphone by itself and know the music is
    /// running and show it on vesper's place, when music stops from the mac, or
    /// any sound played on speakers, microphone comes back on"*.
    ///
    /// WHY NOT LISTEN THROUGH IT. Measured the same evening: the built-in
    /// microphone hears the built-in speakers, and a recorded sentence played at
    /// 31% came back from this recogniser word for word -- lyrics included,
    /// "vesper" lost among them. Apple's voice processing (the canceller calls
    /// use) was tried and made it WORSE: it delivers nine channels instead of
    /// three, the recogniser accepted none of them, and five minutes of the
    /// owner speaking produced not one word. Hearing through music is a real
    /// feature, and it is not this one.
    ///
    /// ONCE A SECOND, PER APP, NOT PER DEVICE. The device-wide "is the output
    /// running" reading stayed true with the music paused, because macOS's own
    /// speech daemon holds the speakers open permanently -- read that way,
    /// vesper would never get its ears back.
    private func watchTheSpeakers() {
        earsTimer?.invalidate()
        earsTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self, !self.capturing else { return }
            let playing = MacAudio.othersPlaying()
            if !playing.isEmpty && self.pausedFor.isEmpty {
                self.earsOff(playing)
            } else if playing.isEmpty && !self.pausedFor.isEmpty {
                self.pausedFor = []
                note("ears on: nothing else is playing")
                writeEars(listening: true, because: [])
                try? self.startTask()
            } else if !playing.isEmpty && playing != self.pausedFor {
                self.pausedFor = playing
                writeEars(listening: false, because: playing)
            }
        }
    }

    private func earsOff(_ playing: [String]) {
        pausedFor = playing
        engine.inputNode.removeTap(onBus: 0)
        engine.stop(); task?.cancel(); task = nil; request = nil
        note("ears off: \(playing.joined(separator: ", ")) is playing")
        writeEars(listening: false, because: playing)
    }

    private func startTask() throws {
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true      // THE LINE. Nothing leaves.
        req.shouldReportPartialResults = true
        // "VESPER" IS NOT A COMMON WORD, and a recogniser with no hint writes
        // the nearest common one -- "vespa", "whisper", "hey esper" -- none of
        // which matches a wake phrase. The supported fix is to say which words
        // to expect; it biases, it does not force.
        req.contextualStrings = ["Vesper", "hey Vesper", "ok Vesper", "yo Vesper"]
        request = req

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buf, _ in
            // The owner's gain (Listener.swift, MicGain): the wake word hears
            // the same amplified copy the dictation does.
            req.append(MicGain.apply(buf))
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
            guard let self, !self.capturing, self.pausedFor.isEmpty else { return }
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
                if self?.pausedFor.isEmpty ?? false { try? self?.startTask() }
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

/// Which OTHER apps are sending sound to the speakers right now.
///
/// Per process (macOS 14+), and two kinds are left out: vesper itself, and
/// macOS's own processes under /System -- `corespeechd` holds the speakers open
/// permanently, measured, and counting it would keep vesper deaf forever.
enum MacAudio {
    static func othersPlaying() -> [String] {
        let sys = AudioObjectID(kAudioObjectSystemObject)
        var a = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
                                           mScope: kAudioObjectPropertyScopeGlobal,
                                           mElement: kAudioObjectPropertyElementMain)
        var size = UInt32(0)
        guard AudioObjectGetPropertyDataSize(sys, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
        var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(sys, &a, 0, nil, &size, &ids) == noErr else { return [] }
        let me = getpid()
        var names: [String] = []
        for id in ids {
            var out = UInt32(0), pid = pid_t(0)
            var sz = UInt32(MemoryLayout<UInt32>.size)
            var pa = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyIsRunningOutput,
                                                mScope: kAudioObjectPropertyScopeGlobal,
                                                mElement: kAudioObjectPropertyElementMain)
            guard AudioObjectGetPropertyData(id, &pa, 0, nil, &sz, &out) == noErr, out != 0 else { continue }
            sz = UInt32(MemoryLayout<pid_t>.size)
            pa.mSelector = kAudioProcessPropertyPID
            guard AudioObjectGetPropertyData(id, &pa, 0, nil, &sz, &pid) == noErr, pid != me else { continue }
            let app = NSRunningApplication(processIdentifier: pid)
            let path = app?.executableURL?.path ?? Self.path(of: pid)
            if path.hasPrefix("/System/") || path.hasPrefix("/usr/") { continue }
            // VESPER's OTHER PROCESSES TOO: the home, the wake agent and a
            // diagnostic all come from this bundle, and vesper speaking is not
            // the owner's music.
            if app?.bundleIdentifier == Bundle.main.bundleIdentifier, app?.bundleIdentifier != nil { continue }
            names.append(app?.localizedName ?? (path as NSString).lastPathComponent)
        }
        return Array(Set(names)).sorted()
    }

    private static func path(of pid: pid_t) -> String {
        var buf = [CChar](repeating: 0, count: 4096)
        return proc_pidpath(pid, &buf, UInt32(buf.count)) > 0 ? String(cString: buf) : ""
    }
}

/// What the wake listener is doing, for the home to show: a file, because the
/// runtime owns the flag bar and two writers on `home.json` would race.
private let earsPath = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/VESPER/ears.json")

func writeEars(listening: Bool, because playing: [String]) {
    let o: [String: Any] = ["listening": listening, "because": playing,
                            "at_s": Int(Date().timeIntervalSince1970)]
    guard let d = try? JSONSerialization.data(withJSONObject: o) else { return }
    let tmp = earsPath.deletingLastPathComponent()
        .appendingPathComponent("ears.json.\(getpid()).tmp")
    // rename(2) is atomic: the runtime never reads half a file.
    if (try? d.write(to: tmp)) != nil { rename(tmp.path, earsPath.path) }
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

private var wakeRetry: Timer?

/// KEEP LOOKING, because the permission usually arrives AFTER this ran.
///
/// THE FAILURE THIS FIXES, 2026-08-31. Home checked the grant once at startup,
/// found it missing, logged "wake word OFF" and never looked again. The owner
/// then granted it 25 minutes later -- correctly, with `open -n`, exactly as
/// the log told them to -- and nothing happened. They reported it as "I
/// accidentally ran the command that turned the wake word off". Nothing was
/// turned off and the grant had worked; the process holding the microphone had
/// simply stopped asking.
///
/// That ordering is not an edge case, it is the NORMAL one: every `build.sh`
/// re-signs ad-hoc, so TCC treats each build as a new app and revokes the
/// grant, and the owner necessarily re-grants while home is already running.
/// A one-shot check is wrong for a permission whose whole lifecycle is "revoked
/// by a build, restored by hand afterwards".
private func scheduleWakeRetry() {
    guard wakeRetry == nil else { return }          // one timer, not one per call
    wakeRetry = Timer.scheduledTimer(withTimeInterval: 15.0, repeats: true) { t in
        guard SFSpeechRecognizer.authorizationStatus() == .authorized,
              AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        else { return }
        // Cleared BEFORE the retry, or `startWakeWordInProcess` sees a live
        // timer and its `wakeRetry == nil` guard silently declines to rearm if
        // this attempt also fails.
        t.invalidate()
        wakeRetry = nil
        startWakeWordInProcess()
    }
}

/// The wake listener held by the HOME process.
private var inProcessWake: WakeListener?

/// Start the wake listener INSIDE home: non-blocking, and it never calls exit().
///
/// WHY IN-PROCESS RATHER THAN A SECOND LAUNCHAGENT. A separate process from
/// this bundle is what broke the globe key's guard (see `homeIsRunning`), and
/// two processes from one bundle both holding the microphone is a race with no
/// upside. Home is already the long-lived process the LaunchAgent keeps alive,
/// so the wake word inherits that lifetime for free.
///
/// `runWakeWord` stays for `--wake`, which is a diagnostic: it blocks on its
/// own run loop and exits with a code, both wrong inside a host application.
@discardableResult
func startWakeWordInProcess() -> Bool {
    guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
        note("wake word OFF: speech recognition is not authorized. Grant it "
           + "with `open -n app/VESPER.app --args --speech-consent` -- from a "
           + "shell TCC answers for the shell, not for VESPER. Still checking, "
           + "so granting it will turn the wake word on without a restart.")
        scheduleWakeRetry()
        return false
    }
    guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
        note("wake word OFF: the microphone is not authorized. Still checking.")
        scheduleWakeRetry()
        return false
    }
    guard let w = WakeListener(diagnose: false) else {
        note("wake word OFF: on-device recognition is unavailable, and this "
           + "listener will not fall back to sending the room to a server")
        return false
    }
    do {
        try w.start()
    } catch {
        note("wake word OFF: could not start audio: \(error)")
        return false
    }
    inProcessWake = w
    note("wake word ON: listening on-device")
    return true
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
