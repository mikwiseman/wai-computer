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

enum RecordingConnectionState: Equatable {
    case connected
    case reconnecting(attempt: Int, maxAttempts: Int)
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
    @Published var connectionState: RecordingConnectionState = .connected

    private var committedTranscript = ""
    private var interimText = ""
    private var recording: Recording?
    private var apiClient: APIClient?
    private var audioCapture: MicrophoneCapture?
    private var audioEncoder: AudioEncoder?
    private var audioFileWriter: AudioFileWriter?
    private var webSocketManager: WebSocketManager?
    private var timerTask: Task<Void, Never>?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?

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
            return "Saving transcript..."
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
                for await event in eventStream {
                    guard !Task.isCancelled else { break }
                    guard let self else { break }
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect to Deepgram directly
            try await ws.connect()

            let capture = MicrophoneCapture()
            let encoder = AudioEncoder()
            audioCapture = capture
            audioEncoder = encoder

            // Create local audio file writer for persistence (local-first)
            try RecordingBackupStore.ensureDirectoryForRecording(recordingId: recordingId)
            let audioFileURL = try RecordingBackupStore.audioFileURL(recordingId: recordingId)
            let fileWriter = try AudioFileWriter(fileURL: audioFileURL)
            self.audioFileWriter = fileWriter
            try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)

            audioTask = Task { [weak self, weak ws] in
                for await buffer in capture.audioBuffers {
                    guard !Task.isCancelled else { break }
                    guard let self, let ws else { break }
                    if let data = encoder.encode(buffer) {
                        // Local-first: always write to disk before sending over network
                        fileWriter.writeEncodedPCM(data)
                        do {
                            try await ws.sendAudio(data: data)
                        } catch {
                            await self.handleStreamingFailure(error.localizedDescription)
                            return
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

        setPhase(.finalizing)

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        // Stop audio capture first so no more audio is generated
        await audioCapture?.stopRecording()
        audioCapture = nil

        let sendingTask = audioTask
        audioTask = nil
        _ = await sendingTask?.result

        // Finalize the local WAV file so it has correct header sizes
        try? audioFileWriter?.finalize()
        audioFileWriter = nil

        let didFinalize = await finishStreaming(webSocketManager)

        // Collect final segments, preserving the final interim phrase if Deepgram never finalized it.
        let segments = finalizedSegments(
            from: await webSocketManager?.collectedSegments ?? [],
            didFinalize: didFinalize
        )

        // Cancel transcript task and await completion, then disconnect
        let pendingTranscriptTask = transcriptTask
        transcriptTask = nil
        pendingTranscriptTask?.cancel()
        _ = await pendingTranscriptTask?.result

        await webSocketManager?.disconnect()
        webSocketManager = nil

        // Persist the finalized live transcript
        let client = self.apiClient
        self.apiClient = nil
        var transcriptSaved = false
        if let recordingId = currentRecordingId, let client {
            do {
                let detail = try await client.saveLiveTranscript(
                    recordingId: recordingId,
                    segments: segments,
                    durationSeconds: Int(duration.rounded())
                )
                try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                if detail.status == .failed {
                    error = detail.failureMessage ?? "Transcript was saved, but processing failed."
                } else {
                    error = nil
                    transcriptSaved = true
                }
            } catch {
                let failureMessage = error.localizedDescription
                if let recoveredDetail = try? await recoverServerTranscript(
                    recordingId: recordingId,
                    client: client
                ) {
                    try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                    transcriptSaved = recoveredDetail.status != .failed
                    if recoveredDetail.status == .failed {
                        self.error = recoveredDetail.failureMessage ?? "Transcript was saved, but processing failed."
                    } else {
                        self.error = nil
                    }
                } else {
                    let backup = try? saveTranscriptBackup(
                        recordingId: recordingId,
                        segments: segments
                    )
                    _ = try? RecordingBackupStore.recordSaveFailure(
                        recordingId: recordingId,
                        message: failureMessage
                    )
                    if backup != nil {
                        self.error = "Transcript save failed. Your audio recording and transcript were saved locally on this device.\n\n\(failureMessage)"
                    } else {
                        self.error = "Transcript save failed: \(failureMessage)"
                    }
                }
            }
        }

        isServerComplete = transcriptSaved
        recording = nil
        currentRecordingId = nil
        audioEncoder = nil
        setPhase(.idle)
    }

    /// Reset transcript and recording state.
    func resetState() {
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        currentRecordingId = nil
        isServerComplete = false
        connectionState = .connected
        duration = 0
    }

    // MARK: - Private

    private func saveTranscriptBackup(
        recordingId: String,
        segments: [LiveTranscriptSegment]
    ) throws -> RecordingBackup {
        let transcript = {
            let finalized = transcriptText(from: segments)
            if !finalized.isEmpty {
                return finalized
            }
            return currentTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        }()
        return try RecordingBackupStore.saveRecording(
            recordingId: recordingId,
            title: recording?.title,
            recordingType: recordingType,
            durationSeconds: duration,
            transcript: transcript.isEmpty ? nil : transcript,
            segments: segments
        )
    }

    private func transcriptText(from segments: [LiveTranscriptSegment]) -> String {
        segments
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private func finalizedSegments(
        from segments: [LiveTranscriptSegment],
        didFinalize: Bool
    ) -> [LiveTranscriptSegment] {
        let trimmedInterim = interimText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedInterim.isEmpty else { return segments }
        guard !didFinalize || segments.isEmpty else { return segments }

        if let last = segments.last,
           last.text.trimmingCharacters(in: .whitespacesAndNewlines) == trimmedInterim {
            return segments
        }

        let fallbackStart = max(segments.last?.endMs ?? 0, Int(max(duration, 0) * 1000) - 1_000)
        let fallbackEnd = max(fallbackStart, Int(max(duration, 0) * 1000))
        return segments + [
            LiveTranscriptSegment(
                text: trimmedInterim,
                speaker: nil,
                isFinal: true,
                startMs: fallbackStart,
                endMs: fallbackEnd,
                confidence: 0
            )
        ]
    }

    private func recoverServerTranscript(
        recordingId: String,
        client: APIClient
    ) async throws -> RecordingDetail? {
        let detail = try await client.getRecording(id: recordingId)
        if !detail.segments.isEmpty || detail.status == .ready {
            return detail
        }
        return nil
    }

    private func finishStreaming(_ manager: WebSocketManager?) async -> Bool {
        guard let manager else { return true }
        do {
            return try await manager.finishStreaming(timeout: .seconds(5))
        } catch {
            print("Failed to finalize Deepgram stream: \(error)")
            return false
        }
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

        let pendingAudioTask = audioTask
        audioTask = nil
        let pendingTranscriptTask = transcriptTask
        transcriptTask = nil

        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil
        try? audioFileWriter?.finalize()
        audioFileWriter = nil

        // Cancel and await both tasks after stopping audio (which finishes the stream)
        pendingAudioTask?.cancel()
        _ = await pendingAudioTask?.result
        pendingTranscriptTask?.cancel()
        _ = await pendingTranscriptTask?.result

        let ws = webSocketManager
        webSocketManager = nil
        apiClient = nil
        await ws?.disconnect()

        recording = nil
        currentRecordingId = nil
        isServerComplete = false
        setPhase(.idle)
    }

    /// Handle permanent reconnection failure — save what we have instead of discarding.
    private func handleReconnectionFailed(with message: String) async {
        guard phase == .recording else {
            error = message
            return
        }

        setPhase(.finalizing)

        if let recordingId = currentRecordingId {
            let segments = finalizedSegments(
                from: await webSocketManager?.collectedSegments ?? [],
                didFinalize: false
            )

            // Try saving collected segments to server
            if let client = apiClient, !segments.isEmpty {
                do {
                    let detail = try await client.saveLiveTranscript(
                        recordingId: recordingId,
                        segments: segments,
                        durationSeconds: Int(duration.rounded())
                    )
                    try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                    if detail.status != .failed {
                        isServerComplete = true
                        error = "Connection was lost but your transcript (\(segments.count) segments) was saved successfully."
                        await cleanupAfterFailure()
                        return
                    }
                } catch {
                    print("Server save after reconnection failure also failed: \(error)")
                }
            }

            // Local backup as last resort
            let backup = try? saveTranscriptBackup(recordingId: recordingId, segments: segments)
            _ = try? RecordingBackupStore.recordSaveFailure(recordingId: recordingId, message: message)

            if backup != nil {
                error = "Connection lost after retrying. Your audio recording and \(segments.count) transcript segments were saved locally.\n\n\(message)"
            } else if segments.isEmpty {
                error = "Connection lost: \(message)"
            } else {
                error = "Connection lost after retrying: \(message)"
            }
        } else {
            error = message
        }

        await cleanupAfterFailure()
    }

    private func cleanupAfterFailure() async {
        timerTask?.cancel()
        timerTask = nil

        let pendingAudioTask = audioTask
        audioTask = nil
        let pendingTranscriptTask = transcriptTask
        transcriptTask = nil

        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil
        try? audioFileWriter?.finalize()
        audioFileWriter = nil

        pendingAudioTask?.cancel()
        _ = await pendingAudioTask?.result
        pendingTranscriptTask?.cancel()
        _ = await pendingTranscriptTask?.result

        let ws = webSocketManager
        webSocketManager = nil
        apiClient = nil
        await ws?.disconnect()

        recording = nil
        currentRecordingId = nil
        isServerComplete = false
        connectionState = .connected
        setPhase(.idle)
    }

    private func handleStreamingFailure(_ message: String) async {
        guard phase == .recording else {
            if error == nil {
                error = message
            }
            return
        }

        setPhase(.finalizing)

        if let recordingId = currentRecordingId {
            let segments = finalizedSegments(
                from: await webSocketManager?.collectedSegments ?? [],
                didFinalize: false
            )

            // Try saving collected segments to server instead of deleting the recording
            if let client = apiClient, !segments.isEmpty {
                do {
                    let detail = try await client.saveLiveTranscript(
                        recordingId: recordingId,
                        segments: segments,
                        durationSeconds: Int(duration.rounded())
                    )
                    try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                    if detail.status != .failed {
                        isServerComplete = true
                        error = "Connection failed but your transcript (\(segments.count) segments) was saved."
                        await cleanupAfterFailure()
                        return
                    }
                } catch {
                    print("Server save after failure also failed: \(error)")
                }
            }

            // Local backup as last resort
            let backup = try? saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments
            )
            if let backup {
                _ = try? RecordingBackupStore.recordSaveFailure(recordingId: recordingId, message: message)
                error = "Recording connection failed. Your audio recording and transcript were saved locally on this device.\n\n\(message)"
                print("Saved local backup at \(backup.directoryURL.path)")
            } else {
                error = message
            }
        } else {
            error = message
        }

        await cleanupAfterFailure()
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
            if let err, phase == .recording {
                await handleStreamingFailure(err.localizedDescription)
            } else if let err, phase != .finalizing, phase != .idle {
                error = err.localizedDescription
            }
        case .reconnecting(let attempt, let maxAttempts):
            connectionState = .reconnecting(attempt: attempt, maxAttempts: maxAttempts)
        case .reconnected:
            connectionState = .connected
            error = nil
        case .reconnectionFailed(let err):
            connectionState = .connected
            await handleReconnectionFailed(
                with: err?.localizedDescription ?? "Connection lost after multiple retries"
            )
        }
    }

    deinit {
        timerTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
    }
}
