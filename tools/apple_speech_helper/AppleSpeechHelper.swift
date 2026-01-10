import AppKit
import AVFoundation
import Foundation
import Speech

struct Options {
    var inputFile: URL
    var outputJSON: URL
    var doneFile: URL?
    var localeIdentifier: String
    var chunkSeconds: Double
    var overlapSeconds: Double
    var perChunkTimeoutSeconds: Double
    var punctuation: Bool
    var contextPhrases: [String]
}

enum HelperError: Error, CustomStringConvertible {
    case message(String, code: String = "ERROR")

    var description: String {
        switch self {
        case .message(let message, _): return message
        }
    }
}

func printUsage() {
    let exe = (CommandLine.arguments.first as NSString?)?.lastPathComponent ?? "AppleSpeechHelper"
    print(
        """
        Usage:
          \(exe) --input-file PATH --output-json PATH [--done-file PATH] [--locale en-US] [--chunk-seconds 20] [--overlap-seconds 1.0] [--timeout-seconds 60] [--punctuation 1] [--context-json PATH]

        Notes:
          - Forces on-device recognition (requiresOnDeviceRecognition = true).
          - Uses chunking+overlap to avoid dropped context on longer files.
        """
    )
}

func parseArgs() throws -> Options {
    let fm = FileManager.default
    let cwd = URL(fileURLWithPath: fm.currentDirectoryPath)

    var inputFile: URL?
    var outputJSON: URL?
    var doneFile: URL?
    var localeIdentifier = "en-US"
    var chunkSeconds = 20.0
    var overlapSeconds = 1.0
    var timeoutSeconds = 60.0
    var punctuation = true
    var contextJSON: URL?
    var contextPhrases: [String] = []

    var i = 1
    while i < CommandLine.arguments.count {
        let arg = CommandLine.arguments[i]
        switch arg {
        case "--help", "-h":
            printUsage()
            exit(0)
        case "--input-file":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --input-file", code: "BAD_ARGS") }
            inputFile = URL(fileURLWithPath: CommandLine.arguments[i + 1], relativeTo: cwd).standardizedFileURL
            i += 1
        case "--output-json":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --output-json", code: "BAD_ARGS") }
            outputJSON = URL(fileURLWithPath: CommandLine.arguments[i + 1], relativeTo: cwd).standardizedFileURL
            i += 1
        case "--done-file":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --done-file", code: "BAD_ARGS") }
            doneFile = URL(fileURLWithPath: CommandLine.arguments[i + 1], relativeTo: cwd).standardizedFileURL
            i += 1
        case "--locale":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --locale", code: "BAD_ARGS") }
            localeIdentifier = CommandLine.arguments[i + 1]
            i += 1
        case "--chunk-seconds":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --chunk-seconds", code: "BAD_ARGS") }
            chunkSeconds = Double(CommandLine.arguments[i + 1]) ?? chunkSeconds
            i += 1
        case "--overlap-seconds":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --overlap-seconds", code: "BAD_ARGS") }
            overlapSeconds = Double(CommandLine.arguments[i + 1]) ?? overlapSeconds
            i += 1
        case "--timeout-seconds":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --timeout-seconds", code: "BAD_ARGS") }
            timeoutSeconds = Double(CommandLine.arguments[i + 1]) ?? timeoutSeconds
            i += 1
        case "--punctuation":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --punctuation", code: "BAD_ARGS") }
            punctuation = (CommandLine.arguments[i + 1].trimmingCharacters(in: .whitespacesAndNewlines) != "0")
            i += 1
        case "--context-json":
            guard i + 1 < CommandLine.arguments.count else { throw HelperError.message("Missing value for --context-json", code: "BAD_ARGS") }
            contextJSON = URL(fileURLWithPath: CommandLine.arguments[i + 1], relativeTo: cwd).standardizedFileURL
            i += 1
        default:
            throw HelperError.message("Unknown argument: \(arg)", code: "BAD_ARGS")
        }
        i += 1
    }

    guard let inputFile else { throw HelperError.message("Missing --input-file", code: "BAD_ARGS") }
    guard let outputJSON else { throw HelperError.message("Missing --output-json", code: "BAD_ARGS") }
    if !fm.fileExists(atPath: inputFile.path) {
        throw HelperError.message("Input file not found: \(inputFile.path)", code: "NO_INPUT_FILE")
    }

    if chunkSeconds <= 0 { chunkSeconds = 20.0 }
    if overlapSeconds < 0 { overlapSeconds = 0 }
    if overlapSeconds >= chunkSeconds { overlapSeconds = max(0, chunkSeconds / 4.0) }
    if timeoutSeconds <= 0 { timeoutSeconds = 60.0 }

    if let contextJSON {
        do {
            let data = try Data(contentsOf: contextJSON)
            let obj = try JSONSerialization.jsonObject(with: data, options: [])
            if let list = obj as? [String] {
                contextPhrases = list
            } else if let dict = obj as? [String: Any], let list = dict["phrases"] as? [String] {
                contextPhrases = list
            }
        } catch {
            throw HelperError.message("Failed to read context JSON: \(error)", code: "BAD_CONTEXT")
        }
    }

    return Options(
        inputFile: inputFile,
        outputJSON: outputJSON,
        doneFile: doneFile,
        localeIdentifier: localeIdentifier,
        chunkSeconds: chunkSeconds,
        overlapSeconds: overlapSeconds,
        perChunkTimeoutSeconds: timeoutSeconds,
        punctuation: punctuation,
        contextPhrases: contextPhrases
    )
}

func writeJSONAtomically(_ obj: [String: Any], to path: URL) throws {
    let data = try JSONSerialization.data(withJSONObject: obj, options: [])
    try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
    try data.write(to: path, options: [.atomic])
}

func writeDoneFile(_ doneFile: URL?, exitCode: Int32, error: [String: Any]? = nil) {
    guard let doneFile else { return }
    var payload: [String: Any] = [
        "exit_code": exitCode,
        "timestamp": ISO8601DateFormatter().string(from: Date()),
    ]
    if let error { payload["error"] = error }
    do {
        try writeJSONAtomically(payload, to: doneFile)
    } catch {
        // ignore
    }
}

func requestSpeechAuthorization(timeoutSeconds: Double = 30) throws {
    let sem = DispatchSemaphore(value: 0)
    var status: SFSpeechRecognizerAuthorizationStatus = .notDetermined
    DispatchQueue.main.async {
        SFSpeechRecognizer.requestAuthorization { newStatus in
            status = newStatus
            sem.signal()
        }
    }
    let didTimeout = (sem.wait(timeout: .now() + timeoutSeconds) == .timedOut)
    if didTimeout { status = .notDetermined }

    switch status {
    case .authorized:
        return
    case .denied:
        throw HelperError.message("Speech recognition authorization denied.", code: "PERMISSION_DENIED")
    case .restricted:
        throw HelperError.message("Speech recognition authorization restricted.", code: "PERMISSION_RESTRICTED")
    case .notDetermined:
        throw HelperError.message("Speech recognition authorization not determined.", code: "PERMISSION_NOT_DETERMINED")
    @unknown default:
        throw HelperError.message("Unknown speech recognition authorization status.", code: "PERMISSION_UNKNOWN")
    }
}

func normalizeWords(_ text: String) -> [String] {
    let lowered = text.lowercased()
    let cleaned = lowered.replacingOccurrences(of: "[^a-z0-9\\s']+", with: " ", options: .regularExpression)
    let compact = cleaned.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).trimmingCharacters(in: .whitespacesAndNewlines)
    return compact.isEmpty ? [] : compact.split(separator: " ").map(String.init)
}

func longestOverlapSuffixPrefix(existing: [String], incoming: [String], maxCheck: Int) -> Int {
    if existing.isEmpty || incoming.isEmpty { return 0 }
    let maxK = min(maxCheck, existing.count, incoming.count)
    if maxK <= 0 { return 0 }
    for k in stride(from: maxK, through: 1, by: -1) {
        let suf = existing.suffix(k)
        let pre = incoming.prefix(k)
        if suf.elementsEqual(pre) {
            return k
        }
    }
    return 0
}

func transcribeChunkOnDevice(
    recognizer: SFSpeechRecognizer,
    url: URL,
    timeoutSeconds: Double,
    punctuation: Bool,
    contextPhrases: [String]
) throws -> String {
    let request = SFSpeechURLRecognitionRequest(url: url)
    request.shouldReportPartialResults = false
    request.requiresOnDeviceRecognition = true
    request.taskHint = .dictation
    if punctuation {
        // `addsPunctuation` is not available on all OS versions/SDKs. Use KVC safely.
        if request.responds(to: NSSelectorFromString("setAddsPunctuation:")) {
            request.setValue(true, forKey: "addsPunctuation")
        }
    }
    if !contextPhrases.isEmpty {
        request.contextualStrings = contextPhrases
    }

    let sem = DispatchSemaphore(value: 0)
    var bestText: String?
    var bestError: Error?

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let error {
            bestError = error
            sem.signal()
            return
        }
        guard let result else { return }
        if result.isFinal {
            bestText = result.bestTranscription.formattedString
            sem.signal()
        }
    }

    let timedOut = (sem.wait(timeout: .now() + timeoutSeconds) == .timedOut)
    if timedOut {
        task.cancel()
        throw HelperError.message("Chunk timeout after \(timeoutSeconds)s", code: "SESSION_TIMEOUT")
    }
    if let bestError {
        throw HelperError.message(bestError.localizedDescription, code: "RECOGNITION_ERROR")
    }
    return (bestText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
}

func chunkedTranscribe(
    recognizer: SFSpeechRecognizer,
    inputFile: URL,
    chunkSeconds: Double,
    overlapSeconds: Double,
    perChunkTimeoutSeconds: Double,
    punctuation: Bool,
    contextPhrases: [String]
) throws -> (text: String, chunks: Int) {
    let audioFile = try AVAudioFile(forReading: inputFile)
    let format = audioFile.processingFormat
    let sr = format.sampleRate
    let channels = Int(format.channelCount)

    // Your app saves 16kHz mono 16-bit PCM WAV. Enforce to keep behavior predictable.
    if channels != 1 || sr < 8000 {
        throw HelperError.message("Unsupported audio format: sampleRate=\(sr) channels=\(channels)", code: "BAD_AUDIO_FORMAT")
    }

    let chunkFrames = max(1, AVAudioFrameCount(chunkSeconds * sr))
    let overlapFrames = max(0, AVAudioFrameCount(overlapSeconds * sr))
    let stepFrames = max(1, chunkFrames > overlapFrames ? (chunkFrames - overlapFrames) : chunkFrames)

    var combinedPretty = ""
    var combinedNormWords: [String] = []
    var chunkIndex = 0

    let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(
        "AppleSpeechHelper-\(UUID().uuidString)",
        isDirectory: true
    )
    try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: tempDir) }

    var startFrame: AVAudioFramePosition = 0
    let totalFrames = audioFile.length
    while startFrame < totalFrames {
        chunkIndex += 1
        audioFile.framePosition = startFrame
        let remaining = totalFrames - startFrame
        let framesToRead = AVAudioFrameCount(min(Int64(chunkFrames), remaining))
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: framesToRead) else {
            throw HelperError.message("Failed to allocate audio buffer", code: "AUDIO_READ_ERROR")
        }
        try audioFile.read(into: buffer, frameCount: framesToRead)

        // Write chunk to a temp WAV for URL recognition.
        let tempURL = tempDir.appendingPathComponent("chunk\(chunkIndex).caf")
        if FileManager.default.fileExists(atPath: tempURL.path) {
            try? FileManager.default.removeItem(at: tempURL)
        }
        defer { try? FileManager.default.removeItem(at: tempURL) }

        let out = try AVAudioFile(forWriting: tempURL, settings: audioFile.processingFormat.settings)
        try out.write(from: buffer)

        let chunkTextPretty = try transcribeChunkOnDevice(
            recognizer: recognizer,
            url: tempURL,
            timeoutSeconds: perChunkTimeoutSeconds,
            punctuation: punctuation,
            contextPhrases: contextPhrases
        )

        let incomingNorm = normalizeWords(chunkTextPretty)
        let overlapK = longestOverlapSuffixPrefix(
            existing: combinedNormWords,
            incoming: incomingNorm,
            maxCheck: 24
        )

        if !combinedPretty.isEmpty && !chunkTextPretty.isEmpty {
            // Prefer simple whitespace join; normalization drives dedup only.
            if overlapK > 0 {
                // Append only the new tail (best-effort). We don’t reconstruct “pretty” words exactly; keep text stable.
                // If Apple repeats overlap, typical output has identical phrase boundaries; this is good enough for paste.
                let incomingWordsPretty = chunkTextPretty.split(separator: " ").map(String.init)
                let tailPretty = incomingWordsPretty.dropFirst(min(overlapK, incomingWordsPretty.count))
                if !tailPretty.isEmpty {
                    combinedPretty += " " + tailPretty.joined(separator: " ")
                }
            } else {
                combinedPretty += " " + chunkTextPretty
            }
        } else if !chunkTextPretty.isEmpty {
            combinedPretty = chunkTextPretty
        }

        // Update normalized words based on the combinedPretty (keeps alignment roughly consistent).
        combinedNormWords = normalizeWords(combinedPretty)

        startFrame += AVAudioFramePosition(stepFrames)
    }

    return (combinedPretty.trimmingCharacters(in: .whitespacesAndNewlines), chunkIndex)
}

final class HelperAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.global(qos: .userInitiated).async {
            let exitCode = self.run()
            DispatchQueue.main.async {
                NSApp.terminate(exitCode == 0 ? nil : self)
            }
        }
    }

    private func run() -> Int32 {
        do {
            let options = try parseArgs()
            try requestSpeechAuthorization(timeoutSeconds: 30)

            let locale = Locale(identifier: options.localeIdentifier)
            guard let recognizer = SFSpeechRecognizer(locale: locale) else {
                throw HelperError.message("Unable to create recognizer for locale: \(options.localeIdentifier)", code: "LOCALE_UNSUPPORTED")
            }
            if !recognizer.supportsOnDeviceRecognition {
                throw HelperError.message("On-device recognition not supported for locale \(options.localeIdentifier) on this machine.", code: "NO_ON_DEVICE_SUPPORT")
            }

            let start = Date()
            let result = try chunkedTranscribe(
                recognizer: recognizer,
                inputFile: options.inputFile,
                chunkSeconds: options.chunkSeconds,
                overlapSeconds: options.overlapSeconds,
                perChunkTimeoutSeconds: options.perChunkTimeoutSeconds,
                punctuation: options.punctuation,
                contextPhrases: options.contextPhrases
            )
            let processingSeconds = Date().timeIntervalSince(start)

            let payload: [String: Any] = [
                "success": true,
                "text": result.text,
                "chunks": result.chunks,
                "processing_s": processingSeconds,
                "locale": options.localeIdentifier,
                "requires_on_device": true,
            ]
            try writeJSONAtomically(payload, to: options.outputJSON)
            writeDoneFile(options.doneFile, exitCode: 0)
            return 0
        } catch {
            let code: String
            if let helperError = error as? HelperError, case let .message(_, c) = helperError {
                code = c
            } else { code = "ERROR" }
            let errObj: [String: Any] = [
                "success": false,
                "code": code,
                "message": String(describing: error),
            ]
            // Best-effort write output json as well
            do {
                if let options = try? parseArgs() {
                    try? writeJSONAtomically(errObj, to: options.outputJSON)
                    writeDoneFile(options.doneFile, exitCode: 1, error: errObj)
                }
            }
            fputs("Error: \(error)\n", stderr)
            printUsage()
            return 1
        }
    }
}

@main
struct AppleSpeechHelperApp {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let delegate = HelperAppDelegate()
        app.delegate = delegate
        app.run()
    }
}
