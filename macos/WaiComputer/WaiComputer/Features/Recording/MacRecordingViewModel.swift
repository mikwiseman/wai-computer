import Foundation
import AVFoundation
import SwiftUI
import os
import WaiComputerKit

private let audioLog = Logger(subsystem: "com.waicomputer.app", category: "audio")

enum MacRecordingInputSource: String, CaseIterable, Equatable {
    case dual        // mic + system audio (default)
    case microphone  // mic only
    case systemAudio = "system_audio"

    var label: String {
        switch self {
        case .dual:
            return "Mic + System Audio"
        case .microphone:
            return "Microphone"
        case .systemAudio:
            return "System Audio"
        }
    }

    var systemImage: String {
        switch self {
        case .dual:
            return "waveform"
        case .microphone:
            return "mic"
        case .systemAudio:
            return "speaker.wave.2"
        }
    }

    var preparingText: String {
        switch self {
        case .dual:
            return "Preparing audio capture..."
        case .microphone:
            return "Preparing microphone..."
        case .systemAudio:
            return "Preparing system audio..."
        }
    }
}

enum MacRecordingPhase: Equatable {
    case idle
    case preparing
    case recording
    case finalizing
}

@MainActor
class MacRecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var recordingType: RecordingType = .note
    @Published var recordingInputSource: MacRecordingInputSource = .dual
    @Published var duration: TimeInterval = 0
    @Published var hasSystemAudio = false
    @Published var currentTranscript = ""
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false
    @Published private(set) var phase: MacRecordingPhase = .idle

    /// Committed (final) transcript lines — only final Deepgram results, with speaker labels
    private var committedLines: [(speaker: String?, text: String)] = []
    /// Current interim text (replaced on each new interim result)
    private var interimText = ""
    /// Speaker of the current interim result
    private var interimSpeaker: String?

    /// Guards against starting a new recording while cleanup is in progress
    private var isCleaningUp = false
    private let testingMode: MacTestingMode

    private var recording: Recording?
    private var apiClient: APIClient?
    private var audioCapture: (any AudioCaptureProtocol)?
    private var audioEncoder: AudioEncoder?
    private var webSocketManager: WebSocketManager?
    private var timerTask: Task<Void, Never>?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?
    private var cleanupTask: Task<Void, Never>?

    /// Audio data accumulated during recording for local save
    private var audioChunks: [Data] = []

    var formattedDuration: String {
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    var shouldPresentLiveView: Bool {
        phase != .idle
    }

    var canStopRecording: Bool {
        phase == .recording
    }

    var statusText: String {
        switch phase {
        case .idle:
            return "Ready to record"
        case .preparing:
            return "Preparing recording"
        case .recording:
            return "Recording"
        case .finalizing:
            return "Saving recording..."
        }
    }

    /// Number of audio channels being sent to Deepgram (1 = mono, 2 = multichannel)
    var audioChannels: Int {
        if recordingInputSource == .dual && hasSystemAudio {
            return 2
        }
        return 1
    }

    var emptyTranscriptText: String {
        switch phase {
        case .idle:
            return "Ready to record."
        case .preparing:
            return recordingInputSource.preparingText
        case .recording:
            return "Listening..."
        case .finalizing:
            return "Saving..."
        }
    }

    init(testingMode: MacTestingMode = .current) {
        self.testingMode = testingMode
    }

    func startRecording(
        apiClient: APIClient,
        type: RecordingType,
        inputSource: MacRecordingInputSource = .dual
    ) async {
        // Wait for any in-progress cleanup to finish before starting a new recording
        if isCleaningUp {
            NSLog("[Recording] Waiting for previous cleanup to complete...")
            await cleanupTask?.value
        }

        if phase == .preparing {
            NSLog("[Recording] Ignoring start while a recording is still preparing")
            return
        }

        if phase == .recording || phase == .finalizing {
            NSLog("[Recording] Force-stopping previous recording before starting new one")
            await stopRecording()
        }

        guard phase == .idle else {
            NSLog("[Recording] Ignoring start while phase is %@", String(describing: phase))
            return
        }

        isLoading = true
        error = nil
        currentTranscript = ""
        committedLines = []
        interimText = ""
        interimSpeaker = nil
        isServerComplete = false
        currentRecordingId = nil
        recordingType = type
        recordingInputSource = inputSource
        hasSystemAudio = false
        duration = 0
        recording = nil
        self.apiClient = apiClient
        audioCapture = nil
        audioEncoder = nil
        audioChunks = []

        setPhase(.preparing)

        #if DEBUG
        if testingMode.isRecordingFlow {
            currentRecordingId = MacUITestFixtures.recording.id
            currentTranscript = "UI test live transcript."
            duration = TimeInterval(MacUITestFixtures.recording.durationSeconds ?? 0)
            setPhase(.recording)
            isLoading = false
            return
        }
        #endif

        do {
            // Mic permission is always needed (dual and mic-only both use mic)
            if inputSource == .dual || inputSource == .microphone {
                let granted = await AVAudioApplication.requestRecordPermission()
                guard granted else {
                    error = "Microphone permission denied"
                    await resetAfterStartFailure()
                    return
                }
            }

            // Create recording on server
            let language = UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
            recording = try await apiClient.createRecording(type: recordingType, language: language)

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                await resetAfterStartFailure()
                return
            }

            currentRecordingId = recordingId

            // Initialize audio capture first to know channel count
            let capture = try makeAudioCapture(for: inputSource)
            audioCapture = capture

            // Check if dual capture actually got system audio
            if #available(macOS 14.2, *), let dualCapture = capture as? DualAudioCapture {
                NSLog("[Recording] Starting dual audio capture...")
                try await capture.startRecording()
                hasSystemAudio = dualCapture.hasSystemAudio
                NSLog("[Recording] Dual capture started — system audio: %@", hasSystemAudio ? "YES" : "NO (mic-only)")

                if inputSource == .dual && !hasSystemAudio {
                    error = "System audio unavailable — only your microphone will be recorded. Grant Audio Capture permission in System Settings > Privacy & Security."
                }
            } else {
                NSLog("[Recording] Starting audio capture...")
                try await capture.startRecording()
            }

            // Now we know the real channel count — create WebSocket with correct params
            let channels = audioChannels
            NSLog("[Recording] Audio channels: %d", channels)

            let ws = WebSocketManager(apiClient: apiClient, language: language, channels: channels)
            self.webSocketManager = ws

            // Set up event stream BEFORE connecting
            let eventStream = await ws.events

            // Start receiving transcripts BEFORE connecting
            transcriptTask = Task { [weak self] in
                guard let self else { return }
                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect to Deepgram directly (fetches temp token from backend)
            try await ws.connect()

            let encoder = AudioEncoder(channels: channels)
            audioEncoder = encoder

            // Start the audio-sending loop
            NSLog("[Recording] Starting audio task (detached)...")
            var bufferCount = 0
            audioTask = Task.detached(priority: .userInitiated) { [weak self] in
                guard let self else { return }
                NSLog("[Recording] Audio task started, waiting for buffers...")
                for await buffer in capture.audioBuffers {
                    bufferCount += 1
                    if bufferCount <= 5 || bufferCount % 50 == 0 {
                        NSLog("[Recording] Buffer #%d: %d frames", bufferCount, buffer.frameLength)
                    }
                    if let data = encoder.encode(buffer) {
                        // Accumulate audio chunks for local file
                        await self.appendAudioChunk(data)

                        if bufferCount <= 5 || bufferCount % 50 == 0 {
                            NSLog("[Recording] Encoded %d bytes, sending...", data.count)
                        }
                        do {
                            try await ws.sendAudio(data: data)
                        } catch {
                            NSLog("[Recording] Failed to send audio: %@", "\(error)")
                            await self.failActiveRecording(with: error.localizedDescription)
                            return
                        }
                    }
                }
                NSLog("[Recording] Audio task loop ended (stream finished)")
            }

            startTimer()
            setPhase(.recording)
            isLoading = false

        } catch {
            self.error = recordingErrorMessage(for: error, inputSource: inputSource)
            await resetAfterStartFailure()
        }
    }

    func stopRecording() async {
        if phase == .finalizing {
            await cleanupTask?.value
            return
        }

        guard phase == .recording else { return }
        setPhase(.finalizing)

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        #if DEBUG
        if testingMode.isRecordingFlow {
            isCleaningUp = true

            let task = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(150))

                await MainActor.run {
                    self?.isServerComplete = true
                    self?.recording = nil
                    self?.audioEncoder = nil
                    self?.setPhase(.idle)
                    self?.isCleaningUp = false
                    self?.cleanupTask = nil
                }
            }

            cleanupTask = task
            await task.value
            return
        }
        #endif

        // Cancel the audio sending task (stops sending new buffers)
        audioTask?.cancel()
        audioTask = nil

        isCleaningUp = true

        let ws = webSocketManager
        let tTask = transcriptTask
        let recordingId = currentRecordingId
        let chunks = audioChunks
        let client = self.apiClient
        let wavChannels = audioChannels
        let capture = audioCapture
        webSocketManager = nil
        transcriptTask = nil
        self.apiClient = nil
        audioCapture = nil

        let task = Task { [weak self] in
            // Send end signal to Deepgram BEFORE stopping capture
            try? await ws?.sendEnd()

            // Now stop audio capture (flushes remaining buffers)
            await capture?.stopRecording()

            // Brief wait for final transcripts from Deepgram
            try? await Task.sleep(for: .seconds(2))

            // Collect final segments from the WebSocket manager
            let segments = await ws?.collectedSegments ?? []

            // Clean up WebSocket
            tTask?.cancel()
            await ws?.disconnect()

            // Save audio locally and upload with segments
            if let recordingId, let client, !chunks.isEmpty {
                do {
                    let audioFileURL = try await self?.saveLocalAudioFile(chunks: chunks, recordingId: recordingId, channels: wavChannels)
                    if let audioFileURL {
                        NSLog("[Recording] Uploading audio + %d segments for recording %@", segments.count, recordingId)
                        _ = try await client.uploadAudio(
                            recordingId: recordingId,
                            fileURL: audioFileURL,
                            segments: segments.isEmpty ? nil : segments
                        )
                        try? FileManager.default.removeItem(at: audioFileURL)
                        NSLog("[Recording] Upload complete for recording %@", recordingId)
                    }
                } catch {
                    NSLog("[Recording] Upload failed: \(error)")
                    await MainActor.run {
                        self?.error = "Failed to upload recording: \(error.localizedDescription)"
                    }
                }
            }

            await MainActor.run {
                self?.isServerComplete = true
                self?.recording = nil
                self?.audioEncoder = nil
                self?.audioChunks = []
                self?.setPhase(.idle)
                self?.isCleaningUp = false
                self?.cleanupTask = nil
            }
        }
        cleanupTask = task
        await task.value
    }

    /// Reset transcript and recording state.
    func resetState() {
        currentTranscript = ""
        committedLines = []
        interimText = ""
        interimSpeaker = nil
        currentRecordingId = nil
        isServerComplete = false
        duration = 0
    }

    func clearError() {
        error = nil
    }

    // MARK: - Private

    private func appendAudioChunk(_ data: Data) {
        audioChunks.append(data)
    }

    private func saveLocalAudioFile(chunks: [Data], recordingId: String, channels: Int) throws -> URL {
        let tempDir = FileManager.default.temporaryDirectory
        let fileURL = tempDir.appendingPathComponent("\(recordingId).wav")

        // Write WAV file with proper header
        let pcmData = chunks.reduce(Data()) { $0 + $1 }
        let wavData = createWAVData(from: pcmData, sampleRate: 16000, channels: channels, bitsPerSample: 16)
        try wavData.write(to: fileURL)

        return fileURL
    }

    private func createWAVData(from pcmData: Data, sampleRate: Int, channels: Int, bitsPerSample: Int) -> Data {
        let dataSize = UInt32(pcmData.count)
        let fileSize = 36 + dataSize
        let byteRate = UInt32(sampleRate * channels * bitsPerSample / 8)
        let blockAlign = UInt16(channels * bitsPerSample / 8)

        var header = Data()
        header.append("RIFF".data(using: .ascii)!)
        header.append(withUnsafeBytes(of: fileSize.littleEndian) { Data($0) })
        header.append("WAVE".data(using: .ascii)!)
        header.append("fmt ".data(using: .ascii)!)
        header.append(withUnsafeBytes(of: UInt32(16).littleEndian) { Data($0) })  // chunk size
        header.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })   // PCM format
        header.append(withUnsafeBytes(of: UInt16(channels).littleEndian) { Data($0) })
        header.append(withUnsafeBytes(of: UInt32(sampleRate).littleEndian) { Data($0) })
        header.append(withUnsafeBytes(of: byteRate.littleEndian) { Data($0) })
        header.append(withUnsafeBytes(of: blockAlign.littleEndian) { Data($0) })
        header.append(withUnsafeBytes(of: UInt16(bitsPerSample).littleEndian) { Data($0) })
        header.append("data".data(using: .ascii)!)
        header.append(withUnsafeBytes(of: dataSize.littleEndian) { Data($0) })
        header.append(pcmData)

        return header
    }

    private func startTimer() {
        timerTask?.cancel()
        timerTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { break }
                await MainActor.run {
                    self?.duration += 1
                }
            }
        }
    }

    private func resetAfterStartFailure() async {
        timerTask?.cancel()
        timerTask = nil
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil
        audioChunks = []

        let ws = webSocketManager
        webSocketManager = nil
        apiClient = nil
        await ws?.disconnect()

        recording = nil
        currentRecordingId = nil
        isServerComplete = false
        recordingInputSource = .dual
        setPhase(.idle)
    }

    private func setPhase(_ newPhase: MacRecordingPhase) {
        // Animate transitions to/from idle so the detail column cross-fades smoothly
        if newPhase == .idle || phase == .idle {
            withAnimation(.easeInOut(duration: 0.25)) {
                phase = newPhase
                isRecording = newPhase == .recording
                isLoading = newPhase == .preparing
            }
        } else {
            phase = newPhase
            isRecording = newPhase == .recording
            isLoading = newPhase == .preparing
        }
    }

    private func handleWebSocketEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            break
        case .transcript(let segment):
            if segment.isFinal {
                committedLines.append((speaker: segment.speaker, text: segment.text))
                interimText = ""
                interimSpeaker = nil
                currentTranscript = buildTranscriptText()
            } else {
                interimText = segment.text
                interimSpeaker = segment.speaker
                currentTranscript = buildTranscriptText()
            }
        case .disconnected(let err):
            if let err, phase == .recording {
                await failActiveRecording(with: err.localizedDescription)
            } else if let err, phase != .finalizing, phase != .idle {
                error = err.localizedDescription
            }
        }
    }

    /// Build transcript text with speaker labels when multichannel is active.
    private func buildTranscriptText() -> String {
        let showSpeakers = audioChannels > 1

        var parts: [String] = []
        if showSpeakers {
            // Group consecutive segments by same speaker for cleaner display
            var currentSpeaker: String? = nil
            var currentText = ""

            for line in committedLines {
                let speaker = line.speaker ?? "Speaker"
                if speaker == currentSpeaker {
                    currentText += " " + line.text
                } else {
                    if !currentText.isEmpty, let s = currentSpeaker {
                        parts.append("\(s): \(currentText)")
                    }
                    currentSpeaker = speaker
                    currentText = line.text
                }
            }
            if !currentText.isEmpty, let s = currentSpeaker {
                parts.append("\(s): \(currentText)")
            }

            // Add interim text
            if !interimText.isEmpty {
                let speaker = interimSpeaker ?? "..."
                if speaker == currentSpeaker {
                    // Append to last line
                    if let last = parts.last {
                        parts[parts.count - 1] = last + " " + interimText
                    } else {
                        parts.append("\(speaker): \(interimText)")
                    }
                } else {
                    parts.append("\(speaker): \(interimText)")
                }
            }

            return parts.joined(separator: "\n\n")
        } else {
            // Single channel — no speaker labels
            let committed = committedLines.map(\.text).joined(separator: " ")
            if interimText.isEmpty {
                return committed
            } else if committed.isEmpty {
                return interimText
            } else {
                return committed + " " + interimText
            }
        }
    }

    private func failActiveRecording(with message: String) async {
        guard phase == .recording else {
            error = message
            return
        }

        error = message

        timerTask?.cancel()
        timerTask = nil
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        cleanupTask?.cancel()
        cleanupTask = nil

        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil
        audioChunks = []

        let ws = webSocketManager
        webSocketManager = nil
        await ws?.disconnect()

        recording = nil
        isServerComplete = false
        isCleaningUp = false
        recordingInputSource = .dual
        setPhase(.idle)
    }

    private func makeAudioCapture(
        for inputSource: MacRecordingInputSource
    ) throws -> any AudioCaptureProtocol {
        switch inputSource {
        case .dual:
            guard #available(macOS 14.2, *) else {
                // Fall back to mic-only on older macOS
                NSLog("[Recording] macOS < 14.2 — falling back to mic-only")
                return MicrophoneCapture()
            }
            return DualAudioCapture()
        case .microphone:
            return MicrophoneCapture()
        case .systemAudio:
            guard #available(macOS 14.2, *) else {
                throw NSError(
                    domain: "MacRecordingViewModel",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "System audio capture requires macOS 14.2 or newer."]
                )
            }
            return SystemAudioCapture()
        }
    }

    private func recordingErrorMessage(
        for error: Error,
        inputSource: MacRecordingInputSource
    ) -> String {
        if inputSource == .systemAudio || inputSource == .dual {
            if #available(macOS 14.2, *),
               let systemError = error as? SystemAudioCaptureError {
                return "System audio capture couldn't start (\(systemError)). Check Audio Capture permission in System Settings and try again."
            }

            switch error {
            case AudioCaptureError.invalidFormat:
                return "System audio capture returned an unsupported format."
            default:
                break
            }
        }

        return error.localizedDescription
    }

    deinit {
        timerTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
        cleanupTask?.cancel()
    }
}
