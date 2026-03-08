import Foundation
import AVFoundation
import Combine
import WaiComputerKit

enum RecordingPhase: Equatable {
    case idle
    case preparing
    case recording
    case finalizing
}

@MainActor
class RecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var recordingType: RecordingType = .note
    @Published var duration: TimeInterval = 0
    @Published var currentTranscript = ""
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false
    @Published private(set) var phase: RecordingPhase = .idle

    private var committedTranscript = ""
    private var interimText = ""
    private var recording: Recording?
    private var apiClient: APIClient?
    private var audioCapture: MicrophoneCapture?
    private var audioEncoder: AudioEncoder?
    private var webSocketManager: WebSocketManager?
    private var timerTask: Task<Void, Never>?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?

    /// Audio data accumulated during recording for local save
    private var audioChunks: [Data] = []

    var formattedDuration: String {
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    var statusText: String {
        switch phase {
        case .idle:
            return "Tap to start recording"
        case .preparing:
            return "Preparing recording..."
        case .recording:
            return "Recording..."
        case .finalizing:
            return "Saving recording..."
        }
    }

    var shouldShowTranscript: Bool {
        phase != .idle || !currentTranscript.isEmpty
    }

    var emptyTranscriptText: String {
        switch phase {
        case .idle:
            return "Start a recording to see live transcription."
        case .preparing:
            return "Preparing microphone..."
        case .recording:
            return "Listening..."
        case .finalizing:
            return "Saving..."
        }
    }

    var canStartRecording: Bool {
        phase == .idle
    }

    var canStopRecording: Bool {
        phase == .recording
    }

    var isBusy: Bool {
        phase == .preparing || phase == .finalizing
    }

    func startRecording(apiClient: APIClient) async {
        guard phase == .idle else { return }

        error = nil
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        currentRecordingId = nil
        isServerComplete = false
        duration = 0
        recording = nil
        self.apiClient = apiClient
        audioCapture = nil
        audioEncoder = nil
        audioChunks = []
        setPhase(.preparing)

        do {
            // Request microphone permission
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                error = "Microphone permission denied"
                await resetAfterStartFailure()
                return
            }

            let language = UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
            recording = try await apiClient.createRecording(
                type: recordingType,
                language: language
            )

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                await resetAfterStartFailure()
                return
            }

            currentRecordingId = recordingId

            // Create direct Deepgram WebSocket connection
            let ws = WebSocketManager(apiClient: apiClient, language: language)
            self.webSocketManager = ws
            let eventStream = await ws.events

            transcriptTask = Task { [weak self] in
                guard let self else { return }
                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect to Deepgram directly
            try await ws.connect()

            let capture = MicrophoneCapture()
            let encoder = AudioEncoder()
            audioCapture = capture
            audioEncoder = encoder

            audioTask = Task { [weak self] in
                guard let self else { return }
                for await buffer in capture.audioBuffers {
                    if let data = encoder.encode(buffer) {
                        await self.appendAudioChunk(data)
                        do {
                            try await ws.sendAudio(data: data)
                        } catch {
                            await MainActor.run {
                                self.error = error.localizedDescription
                            }
                            break
                        }
                    }
                }
            }

            try await capture.startRecording()
            startTimer()
            setPhase(.recording)

        } catch {
            self.error = error.localizedDescription
            await resetAfterStartFailure()
        }
    }

    func stopRecording() async {
        guard phase == .recording else { return }

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        // Stop audio capture first so no more audio is generated
        await audioCapture?.stopRecording()
        audioCapture = nil

        // Cancel the audio sending task
        audioTask?.cancel()
        audioTask = nil

        setPhase(.finalizing)

        // Send end signal to Deepgram
        do {
            try await webSocketManager?.sendEnd()
        } catch {
            print("Failed to send end signal: \(error)")
        }

        // Brief wait for final transcripts
        try? await Task.sleep(for: .seconds(2))

        // Collect final segments
        let segments = await webSocketManager?.collectedSegments ?? []

        // Now cancel transcript task and disconnect
        transcriptTask?.cancel()
        transcriptTask = nil

        await webSocketManager?.disconnect()
        webSocketManager = nil

        // Upload audio + segments
        let client = self.apiClient
        self.apiClient = nil
        if let recordingId = currentRecordingId, let client, !audioChunks.isEmpty {
            do {
                let audioFileURL = try saveLocalAudioFile(chunks: audioChunks, recordingId: recordingId)
                _ = try await client.uploadAudio(
                    recordingId: recordingId,
                    fileURL: audioFileURL,
                    segments: segments.isEmpty ? nil : segments
                )
                try? FileManager.default.removeItem(at: audioFileURL)
            } catch {
                print("Upload failed: \(error)")
            }
        }

        isServerComplete = true
        recording = nil
        audioEncoder = nil
        audioChunks = []
        setPhase(.idle)
    }

    /// Reset transcript and recording state.
    func resetState() {
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        currentRecordingId = nil
        isServerComplete = false
        duration = 0
    }

    // MARK: - Private

    private func appendAudioChunk(_ data: Data) {
        audioChunks.append(data)
    }

    private func saveLocalAudioFile(chunks: [Data], recordingId: String) throws -> URL {
        let tempDir = FileManager.default.temporaryDirectory
        let fileURL = tempDir.appendingPathComponent("\(recordingId).wav")

        let pcmData = chunks.reduce(Data()) { $0 + $1 }
        let wavData = createWAVData(from: pcmData, sampleRate: 16000, channels: 1, bitsPerSample: 16)
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
        header.append(withUnsafeBytes(of: UInt32(16).littleEndian) { Data($0) })
        header.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })
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
        setPhase(.idle)
    }

    private func setPhase(_ newPhase: RecordingPhase) {
        phase = newPhase
        isRecording = newPhase == .recording
        isLoading = newPhase == .preparing
    }

    private func handleWebSocketEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            break
        case .transcript(let segment):
            if segment.isFinal {
                if !committedTranscript.isEmpty {
                    committedTranscript += " "
                }
                committedTranscript += segment.text
                interimText = ""
                currentTranscript = committedTranscript
            } else {
                interimText = segment.text
                if committedTranscript.isEmpty {
                    currentTranscript = interimText
                } else {
                    currentTranscript = committedTranscript + " " + interimText
                }
            }
        case .disconnected(let err):
            if let err {
                error = err.localizedDescription
            }
        }
    }

    deinit {
        timerTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
    }
}
