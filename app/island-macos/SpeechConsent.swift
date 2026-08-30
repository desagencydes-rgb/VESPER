// The one thing that makes a TCC prompt possible: something inside the bundle
// asking for it.
//
// WHY THIS IS NOT A SCRIPT OR A LOOSE BINARY. TCC grants are keyed to app
// identity, and `build.sh`'s header already states the consequence: a request
// made from a bare executable is granted to the TERMINAL that launched it,
// appears in System Settings as "Terminal", and does not transfer to VESPER
// afterwards. The probe that measured this Mac's recogniser on 2026-08-30 was
// exactly such a binary, which is why it could report availability and could
// NOT establish consent. The request has to come from in here.
//
// TWO PROMPTS, NOT ONE, AND THEY ARE DIFFERENT PERMISSIONS. Microphone access
// is permission to CAPTURE; speech recognition is permission to TRANSCRIBE, and
// on this Mac transcription for anything other than en-US happens on Apple's
// servers -- measured the same day: `supportsOnDeviceRecognition` is true for
// en-US and false for ar-MA, ar-SA and fr-FR. Granting one does not grant the
// other and the owner should see both, because they authorise different things.
//
// LAUNCH IT WITH `open -n`, NEVER FROM A SHELL, and the bundle identity printed
// below is NOT evidence that you did. Measured 2026-08-30: run as
// `app/VESPER.app/Contents/MacOS/VESPER --speech-consent` from a terminal, this
// prints `requesting as: ai.vesper.island` -- correct -- and TCC still attributes
// the request to the RESPONSIBLE PROCESS, which is the shell. The microphone
// then returned "granted" with no dialog at all, because it inherited the
// terminal's existing grant, and the speech request killed the process with
// SIGABRT and `namespace: TCC`, complaining that the usage description was
// missing from an Info.plist that demonstrably contains it. Both readings were
// wrong in the direction that looks like success.
//
// RE-READS THE WORLD AFTER ASKING. The callback firing is not the grant: the
// owner may have clicked Deny, or the dialog may never have appeared because a
// usage string was missing from Info.plist -- which is the failure this whole
// path exists to fix, and it returns "denied" rather than an error. So the
// final line prints the status read back out of the framework, not the value
// the callback handed us.

import Foundation
import AVFoundation
import Speech

// WHERE THE RESULT GOES, and why it is not just stdout. This must be launched
// by LaunchServices (`open -n`), not from a shell -- see requestSpeechConsent()
// -- and a detached launch has no terminal to print to. A permission check whose
// answer nobody can read is the same defect as a probe that buffers its output
// until the end: the work happens and the finding does not arrive.
private let consentReport = URL(fileURLWithPath: "/tmp/vesper-speech-consent.txt")

private func report(_ line: String) {
    print(line)
    let stamped = line + "\n"
    if let h = try? FileHandle(forWritingTo: consentReport) {
        h.seekToEndOfFile(); h.write(stamped.data(using: .utf8)!); try? h.close()
    } else {
        try? stamped.write(to: consentReport, atomically: true, encoding: .utf8)
    }
}

private func speechStatusName(_ s: SFSpeechRecognizerAuthorizationStatus) -> String {
    switch s {
    case .notDetermined: return "notDetermined (no dialog has been answered)"
    case .denied:        return "denied"
    case .restricted:    return "restricted (policy forbids it; not the owner's choice)"
    case .authorized:    return "authorized"
    @unknown default:    return "unknown(\(s.rawValue))"
    }
}

func requestSpeechConsent() {
    let bundle = Bundle.main.bundleIdentifier ?? "NOT IN A BUNDLE"
    report("requesting as: \(bundle)")
    if bundle == "NOT IN A BUNDLE" {
        report("REFUSING: no bundle identity. A grant made from here would be "
              + "recorded against whatever launched this, not against VESPER.")
        return
    }

    // Microphone first: it is the permission that gates capture, and a speech
    // grant without it authorises transcribing audio that can never be read.
    let micGate = DispatchSemaphore(value: 0)
    var micGranted = false
    AVCaptureDevice.requestAccess(for: .audio) { granted in
        micGranted = granted
        micGate.signal()
    }
    // A dialog the owner never answers must not hang a supervised process.
    if micGate.wait(timeout: .now() + 120) == .timedOut {
        report("microphone: NO ANSWER within 120s -- nothing was granted")
    } else {
        report("microphone: \(micGranted ? "granted" : "DENIED")")
    }

    let speechGate = DispatchSemaphore(value: 0)
    SFSpeechRecognizer.requestAuthorization { _ in speechGate.signal() }
    if speechGate.wait(timeout: .now() + 120) == .timedOut {
        report("speech recognition: NO ANSWER within 120s")
    }

    // The re-read. This is the only line that is evidence.
    let now = SFSpeechRecognizer.authorizationStatus()
    report("speech recognition, read back: \(speechStatusName(now))")
    let mic = AVCaptureDevice.authorizationStatus(for: .audio)
    report("microphone, read back: \(mic == .authorized ? "authorized" : "NOT authorized (\(mic.rawValue))")")
}
