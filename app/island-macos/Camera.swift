import AVFoundation
import Vision
import Foundation

/// The camera, MEASURED before anything is chosen (`INV-HW-2`), and presence as
/// a flag rather than a per-turn check (`docs/design/VISION-IDENTITY.md`).
///
/// WHAT THIS IS AND IS NOT. `docs/design/VISION-IDENTITY.md` is the owner's
/// design: two standalone models -- face authentication and body/movement
/// identification -- that run on the device holding the camera and set a
/// presence flag VESPER reads from memory. Neither model exists on this Mac,
/// and `MEMORY.md` records that a local model heats this host in a minute. So
/// this file does the two things that can be done honestly tonight:
///
///   1. `--camera-probe`: open the webcam for N seconds, run Apple's on-device
///      face DETECTION (Vision, `VNDetectFaceRectanglesRequest`; no model is
///      downloaded and nothing leaves the machine), and MEASURE: frames per
///      second, faces per second, CPU seconds spent, so the cost of a
///      recognition model can be argued from a reading rather than a guess.
///   2. `--presence`: the same capture, written as a flag -- `someone` / `nobody`
///      with the face count -- to `presence.json`. Detection, not identity: it
///      says a person is at the machine and never who. Identity is the design's
///      standalone model and stays unbuilt until one is measured.
///
/// GATED, NEVER ALWAYS-ON. The camera opens only when a mode asks for N seconds
/// and closes after. No frame is persisted (`INV-PRIV-3`); only counts leave.
final class CameraProbe: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "ai.vesper.camera")
    private let lock = NSLock()
    private var frames = 0
    private var frameWithFace = 0
    private var facesSeen = 0
    private var maxFaces = 0
    private var lastError = ""

    func open() -> String? {
        guard let dev = AVCaptureDevice.default(for: .video) else { return "no camera on this node" }
        do {
            let input = try AVCaptureDeviceInput(device: dev)
            session.beginConfiguration()
            session.sessionPreset = .vga640x480          // enough for detection, cheap
            guard session.canAddInput(input) else { return "the camera input was refused" }
            session.addInput(input)
            output.alwaysDiscardsLateVideoFrames = true
            output.setSampleBufferDelegate(self, queue: queue)
            guard session.canAddOutput(output) else { return "the video output was refused" }
            session.addOutput(output)
            session.commitConfiguration()
        } catch {
            return "camera could not be opened: \(error)"
        }
        session.startRunning()
        return nil
    }

    func close() { session.stopRunning() }

    func captureOutput(_ o: AVCaptureOutput, didOutput sample: CMSampleBuffer,
                       from c: AVCaptureConnection) {
        guard let px = CMSampleBufferGetImageBuffer(sample) else { return }
        let req = VNDetectFaceRectanglesRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: px, orientation: .up, options: [:])
        var n = 0
        do {
            try handler.perform([req])
            n = (req.results ?? []).count
        } catch {
            lock.lock(); lastError = "\(error)"; lock.unlock()
        }
        lock.lock()
        frames += 1
        if n > 0 { frameWithFace += 1; facesSeen += n; if n > maxFaces { maxFaces = n } }
        lock.unlock()
    }

    struct Reading {
        let frames: Int, framesWithFace: Int, facesSeen: Int, maxFaces: Int
        let seconds: Double, cpuSeconds: Double, error: String
        var fps: Double { seconds > 0 ? Double(frames) / seconds : 0 }
        var faceFrameRatio: Double { frames > 0 ? Double(framesWithFace) / Double(frames) : 0 }
    }

    func reading(seconds: Double, cpuSeconds: Double) -> Reading {
        lock.lock(); defer { lock.unlock() }
        return Reading(frames: frames, framesWithFace: frameWithFace, facesSeen: facesSeen,
                       maxFaces: maxFaces, seconds: seconds, cpuSeconds: cpuSeconds, error: lastError)
    }
}

/// CPU seconds this process has used (user + system), for a before/after delta.
func processCPUSeconds() -> Double {
    var ru = rusage()
    getrusage(RUSAGE_SELF, &ru)
    let u = Double(ru.ru_utime.tv_sec) + Double(ru.ru_utime.tv_usec) / 1e6
    let s = Double(ru.ru_stime.tv_sec) + Double(ru.ru_stime.tv_usec) / 1e6
    return u + s
}

/// `--camera-probe --seconds N --out FILE [--presence FILE]`.
/// Asks for the camera as VESPER (the responsible process), measures, reports.
func runCameraProbe(seconds: Double, out: String?, presenceOut: String?) -> Never {
    var lines: [String] = []
    func say(_ t: String) { print(t); lines.append(t) }
    func finish(_ code: Int32) -> Never {
        if let out, !out.isEmpty {
            try? lines.joined(separator: "\n").write(toFile: out, atomically: true, encoding: .utf8)
        }
        exit(code)
    }
    let status = AVCaptureDevice.authorizationStatus(for: .video)
    if status == .notDetermined {
        // ASKED HERE, AS VESPER. From a shell the grant would be the shell's.
        let sem = DispatchSemaphore(value: 0)
        AVCaptureDevice.requestAccess(for: .video) { _ in sem.signal() }
        _ = sem.wait(timeout: .now() + 60)
    }
    let after = AVCaptureDevice.authorizationStatus(for: .video)
    guard after == .authorized else {
        say("camera: not granted (status \(after.rawValue)). Grant it in System Settings → Privacy & Security → Camera, or press Allow when asked.")
        finish(1)
    }
    let probe = CameraProbe()
    if let why = probe.open() {
        say("camera: \(why)")
        finish(1)
    }
    let cpu0 = processCPUSeconds()
    let t0 = Date()
    say("camera open -- measuring for \(Int(seconds))s with on-device face detection (nothing is stored, nothing leaves).")
    RunLoop.main.run(until: Date().addingTimeInterval(seconds))
    probe.close()
    let elapsed = Date().timeIntervalSince(t0)
    let r = probe.reading(seconds: elapsed, cpuSeconds: processCPUSeconds() - cpu0)
    if r.frames == 0 {
        say("no frames arrived in \(Int(elapsed))s -- the camera opened and delivered nothing. That is not an empty room; it is no picture." + (r.error.isEmpty ? "" : " Last error: \(r.error)"))
        finish(1)
    }
    say(String(format: "frames %d in %.1fs = %.1f fps; faces in %.0f%% of frames (max %d at once); cpu %.2fs = %.0f%% of one core",
               r.frames, elapsed, r.fps, r.faceFrameRatio * 100, r.maxFaces, r.cpuSeconds,
               elapsed > 0 ? r.cpuSeconds / elapsed * 100 : 0))
    let someone = r.faceFrameRatio >= 0.2
    say(someone ? "presence: someone is at the machine (detection, not identity)"
                : "presence: nobody in view")
    if let presenceOut, !presenceOut.isEmpty {
        let obj: [String: Any] = ["at_ms": Int(Date().timeIntervalSince1970 * 1000),
                                  "someone": someone, "max_faces": r.maxFaces,
                                  "face_frame_ratio": r.faceFrameRatio, "fps": r.fps,
                                  "cpu_share": elapsed > 0 ? r.cpuSeconds / elapsed : 0,
                                  "seconds": elapsed, "identity": "unknown",
                                  "note": "detection by Vision on-device; identity needs the standalone face-auth model of VISION-IDENTITY.md, which is not built"]
        if let d = try? JSONSerialization.data(withJSONObject: obj) {
            try? d.write(to: URL(fileURLWithPath: presenceOut), options: .atomic)
        }
    }
    finish(0)
}
