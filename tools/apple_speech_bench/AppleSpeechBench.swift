import AppKit
import AVFoundation
import Foundation
import Speech

struct Options {
    var inputDir: URL
    var outputPath: URL
    var doneFile: URL?
    var localeIdentifier: String
    var maxFiles: Int
    var timeoutSeconds: Double
    var shuffle: Bool
}

enum BenchError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let message): return message
        }
    }
}

func printUsage() {
    let exe = (CommandLine.arguments.first as NSString?)?.lastPathComponent ?? "AppleSpeechBench"
    print(
        """
        Usage:
          \(exe) [--input-dir PATH] [--output PATH] [--done-file PATH] [--locale en-US] [--max-files N] [--timeout-seconds S] [--shuffle]

        Notes:
          - Forces on-device recognition (requiresOnDeviceRecognition = true).
          - Outputs JSON Lines (one JSON object per audio file).
        """
    )
}

func parseArgs() throws -> Options {
    let fileManager = FileManager.default
    let cwd = URL(fileURLWithPath: fileManager.currentDirectoryPath)
    var inputDir = cwd.appendingPathComponent("../../data/history/audio").standardizedFileURL
    var outputPath = cwd.appendingPathComponent("apple_speech_results.jsonl").standardizedFileURL
    var doneFile: URL?
    var localeIdentifier = "en-US"
    var maxFiles = 30
    var timeoutSeconds = 30.0
    var shuffle = false

    var i = 1
    while i < CommandLine.arguments.count {
        let arg = CommandLine.arguments[i]
        switch arg {
        case "--help", "-h":
            printUsage()
            exit(0)
        case "--input-dir":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --input-dir") }
            inputDir = URL(fileURLWithPath: CommandLine.arguments[i + 1]).standardizedFileURL
            i += 1
        case "--output":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --output") }
            outputPath = URL(fileURLWithPath: CommandLine.arguments[i + 1]).standardizedFileURL
            i += 1
        case "--done-file":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --done-file") }
            doneFile = URL(fileURLWithPath: CommandLine.arguments[i + 1]).standardizedFileURL
            i += 1
        case "--locale":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --locale") }
            localeIdentifier = CommandLine.arguments[i + 1]
            i += 1
        case "--max-files":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --max-files") }
            maxFiles = Int(CommandLine.arguments[i + 1]) ?? maxFiles
            i += 1
        case "--timeout-seconds":
            guard i + 1 < CommandLine.arguments.count else { throw BenchError.message("Missing value for --timeout-seconds") }
            timeoutSeconds = Double(CommandLine.arguments[i + 1]) ?? timeoutSeconds
            i += 1
        case "--shuffle":
            shuffle = true
        default:
            throw BenchError.message("Unknown argument: \(arg)")
        }
        i += 1
    }

    if !fileManager.fileExists(atPath: inputDir.path) {
        throw BenchError.message("Input dir not found: \(inputDir.path)")
    }

    if maxFiles <= 0 { maxFiles = 1 }
    if timeoutSeconds <= 0 { timeoutSeconds = 30.0 }

    return Options(
        inputDir: inputDir,
        outputPath: outputPath,
        doneFile: doneFile,
        localeIdentifier: localeIdentifier,
        maxFiles: maxFiles,
        timeoutSeconds: timeoutSeconds,
        shuffle: shuffle
    )
}

func jsonLine(_ obj: [String: Any]) -> Data {
    let data = (try? JSONSerialization.data(withJSONObject: obj, options: [])) ?? Data()
    var line = data
    line.append(0x0A) // \n
    return line
}

func listWavFiles(in dir: URL) throws -> [URL] {
    let fileManager = FileManager.default
    let items = try fileManager.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isRegularFileKey], options: [.skipsHiddenFiles])
    return items
        .filter { $0.pathExtension.lowercased() == "wav" }
        .sorted { $0.lastPathComponent < $1.lastPathComponent }
}

func audioDurationSeconds(url: URL) -> Double {
    let asset = AVURLAsset(url: url)
    let duration = asset.duration
    if duration.isIndefinite { return 0 }
    return max(0, duration.seconds)
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
    if didTimeout {
        status = .notDetermined
    }

    switch status {
    case .authorized:
        return
    case .denied:
        throw BenchError.message("Speech recognition authorization denied.")
    case .restricted:
        throw BenchError.message("Speech recognition authorization restricted.")
    case .notDetermined:
        throw BenchError.message("Speech recognition authorization not determined (no response).")
    @unknown default:
        throw BenchError.message("Unknown speech recognition authorization status.")
    }
}

func transcribeFileOnDevice(
    recognizer: SFSpeechRecognizer,
    url: URL,
    timeoutSeconds: Double
) -> (text: String?, error: String?, processingSeconds: Double) {
    let start = Date()
    let request = SFSpeechURLRecognitionRequest(url: url)
    request.shouldReportPartialResults = false
    request.requiresOnDeviceRecognition = true

    let sem = DispatchSemaphore(value: 0)
    var bestText: String?
    var bestError: String?

    let task = recognizer.recognitionTask(with: request) { result, error in
        if let error {
            bestError = error.localizedDescription
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
        bestError = "Timeout after \(timeoutSeconds)s"
    }

    return (bestText, bestError, Date().timeIntervalSince(start))
}

final class BenchAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.global(qos: .userInitiated).async {
            let exitCode = self.runBench()
            DispatchQueue.main.async {
                NSApp.terminate(exitCode == 0 ? nil : self)
            }
        }
    }

    private func writeDoneFile(_ doneFile: URL?, exitCode: Int32, error: String? = nil) {
        guard let doneFile else { return }
        let obj: [String: Any?] = [
            "exit_code": exitCode,
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "error": error,
        ]
        let compact = obj.compactMapValues { $0 }
        let data = jsonLine(compact)
        try? FileManager.default.createDirectory(at: doneFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: doneFile, options: [.atomic])
    }

    private func runBench() -> Int32 {
        var doneFile: URL?
        do {
            let options = try parseArgs()
            doneFile = options.doneFile
            try requestSpeechAuthorization(timeoutSeconds: 30)

            let locale = Locale(identifier: options.localeIdentifier)
            guard let recognizer = SFSpeechRecognizer(locale: locale) else {
                throw BenchError.message("Unable to create SFSpeechRecognizer for locale: \(options.localeIdentifier)")
            }

            let onDeviceSupported = recognizer.supportsOnDeviceRecognition
            if !onDeviceSupported {
                throw BenchError.message("On-device recognition not supported for locale \(options.localeIdentifier) on this machine.")
            }

            var files = try listWavFiles(in: options.inputDir)
            if files.isEmpty {
                throw BenchError.message("No .wav files found in: \(options.inputDir.path)")
            }
            if options.shuffle {
                files.shuffle()
            }
            files = Array(files.prefix(options.maxFiles))

            let fileManager = FileManager.default
            if fileManager.fileExists(atPath: options.outputPath.path) {
                try fileManager.removeItem(at: options.outputPath)
            }
            fileManager.createFile(atPath: options.outputPath.path, contents: nil)
            let outHandle = try FileHandle(forWritingTo: options.outputPath)
            defer { try? outHandle.close() }

            let header: [String: Any] = [
                "type": "run_info",
                "timestamp": ISO8601DateFormatter().string(from: Date()),
                "input_dir": options.inputDir.path,
                "locale": options.localeIdentifier,
                "max_files": options.maxFiles,
                "timeout_seconds": options.timeoutSeconds,
                "on_device_supported": onDeviceSupported,
            ]
            try outHandle.write(contentsOf: jsonLine(header))

            for (idx, url) in files.enumerated() {
                let duration = audioDurationSeconds(url: url)
                let result = transcribeFileOnDevice(
                    recognizer: recognizer,
                    url: url,
                    timeoutSeconds: options.timeoutSeconds
                )
                let rtf: Double? = duration > 0 ? (result.processingSeconds / duration) : nil

                let row: [String: Any?] = [
                    "type": "file_result",
                    "index": idx + 1,
                    "file": url.lastPathComponent,
                    "path": url.path,
                    "duration_s": duration,
                    "processing_s": result.processingSeconds,
                    "rtf": rtf,
                    "text": result.text,
                    "error": result.error,
                ]

                let compact = row.compactMapValues { $0 }
                try outHandle.write(contentsOf: jsonLine(compact))

                let statusText = result.error == nil ? "ok" : "error"
                let rtfText = rtf == nil ? "-" : String(format: "%.2f", rtf!)
                print("[\(idx + 1)/\(files.count)] \(statusText) rtf=\(rtfText) \(url.lastPathComponent)")
            }

            print("Wrote results to: \(options.outputPath.path)")
            writeDoneFile(doneFile, exitCode: 0)
            return 0
        } catch {
            fputs("Error: \(error)\n", stderr)
            printUsage()
            writeDoneFile(doneFile, exitCode: 1, error: String(describing: error))
            return 1
        }
    }
}

@main
struct AppleSpeechBenchApp {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let delegate = BenchAppDelegate()
        app.delegate = delegate
        app.run()
    }
}
