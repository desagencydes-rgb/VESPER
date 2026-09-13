import AppKit
import ApplicationServices
import AVFoundation
import CoreGraphics
import EventKit
import Foundation
import Speech

/// ASKING for permissions, kept apart from reading them.
///
/// `Grants.swift` is a pure READER and `a-permission-reader-never-asks` enforces
/// that: "a reader that prompts cannot be run to find out what to ask for -- it
/// becomes the asking, and unattended it puts a dialog on the owner's screen
/// with nobody there to answer it." That rule is right, and the first version of
/// this code broke it by putting the asker in the reader's file -- the check
/// caught it the same minute.
///
/// SO THEY ARE TWO FILES. Reading is safe to do at any time, from anywhere,
/// including a status sweep nobody is watching. Asking is a deliberate act with
/// a person present, and it lives here where nothing routine will call it.
enum GrantsRequest {
/// ASK for everything still missing, raising each system dialog once.
///
/// THE OWNER, 2026-09-13: *"if it was a dialog, vesper should immediately
/// raise it while working, and whenever i see it, i grant it, so vesper's
/// work works automatically, then vesper gets the return and keeps going...
/// for stuff that need dialog on runtime, they should be raised right after
/// vesper rebuilds and runs, so i won't have to go to settings anymore."*
///
/// AND THEY WERE RIGHT TO DOUBT "no automated fix". Every permission here
/// has an asking variant; this file deliberately used only the non-asking
/// ones, which is correct for a STATUS READER -- "a status reader that
/// prompts cannot be run to find out what to ask for" -- and left the
/// system with no path that asks at all. Reading and asking are different
/// acts and now there are two functions.
///
/// ONLY WHAT IS MISSING. Asking for something already granted raises
/// nothing on some of these and a redundant dialog on others; either way it
/// teaches the owner that VESPER's dialogs are noise.
///
/// ACCESSIBILITY AND SCREEN RECORDING OPEN SETTINGS RATHER THAN GRANTING
/// IN PLACE. That is macOS's design, not a shortcut: the prompt is a dialog
/// with a button that takes the owner to the right pane. It still beats
/// telling them a pane name and letting them find it.
static func request() {
    var asked: [String] = []

    if !AXIsProcessTrusted() {
        // The ONE prompting variant of the call this file otherwise avoids.
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue()
        _ = AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
        asked.append("Accessibility")
    }
    if !CGPreflightScreenCaptureAccess() {
        _ = CGRequestScreenCaptureAccess()
        asked.append("Screen Recording")
    }
    if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
        AVCaptureDevice.requestAccess(for: .audio) { _ in }
        asked.append("Microphone")
    }
    if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
        SFSpeechRecognizer.requestAuthorization { _ in }
        asked.append("Speech Recognition")
    }
    if EKEventStore.authorizationStatus(for: .event) == .notDetermined {
        // GUARDED: `requestFullAccessToEvents` is macOS 14+, and this
        // bundle's deployment target is lower. The older call asks the same
        // question on every version this runs on.
        if #available(macOS 14.0, *) {
            EKEventStore().requestFullAccessToEvents { _, _ in }
        } else {
            EKEventStore().requestAccess(to: .event) { _, _ in }
        }
        asked.append("Calendar")
    }

    // WAIT FOR THE DIALOGS TO BE ANSWERED, but not forever. The requests
    // above are asynchronous; exiting immediately would tear down the
    // process holding the dialog.
    if asked.isEmpty {
        print("every permission vesper needs is already granted; asked for nothing.")
        return
    }
    print("asked for: " + asked.joined(separator: ", "))
    print("grant them as they appear -- vesper carries on by itself once they are given.")
    RunLoop.main.run(until: Date().addingTimeInterval(90))
}
}
