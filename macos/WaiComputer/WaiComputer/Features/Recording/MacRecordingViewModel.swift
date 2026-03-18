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
    @Published var systemAudioWarning: String?

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
    private var systemAudioMonitorTask: Task<Void, Never>?

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
            return "Saving transcript..."
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
                    error = "System audio unavailable — only your microphone will be recorded. Other participants in calls (Zoom, Meet, etc.) will NOT be transcribed.\n\nTo fix: System Settings → Privacy & Security → Audio Capture → enable WaiComputer."
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

            // Monitor system audio stall status so the user gets immediate feedback
            if #available(macOS 14.2, *), let dualCapture = capture as? DualAudioCapture {
                startSystemAudioMonitor(for: dualCapture)
            }

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

        // Stop timer and system audio monitor
        timerTask?.cancel()
        timerTask = nil
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = nil
        systemAudioWarning = nil

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

        isCleaningUp = true

        let ws = webSocketManager
        let tTask = transcriptTask
        let recordingId = currentRecordingId
        let client = self.apiClient
        let recordingDuration = duration
        let capture = audioCapture
        let sendingTask = audioTask
        audioTask = nil
        webSocketManager = nil
        transcriptTask = nil
        self.apiClient = nil
        audioCapture = nil

        let task = Task { [weak self] in
            guard let self else { return }

            // Stop audio capture first so the encoder can drain the final buffers.
            await capture?.stopRecording()
            _ = await sendingTask?.result

            let didFinalize = await self.finishStreaming(ws)
            let segments = await ws?.collectedSegments ?? []
            let finalizedSegments = await MainActor.run {
                self.finalizedSegments(from: segments, didFinalize: didFinalize)
            }

            tTask?.cancel()
            await ws?.disconnect()

            var transcriptSaved = false

            if let recordingId, let client {
                do {
                    NSLog("[Recording] Saving %d transcript segments for recording %@", segments.count, recordingId)
                    let detail = try await client.saveLiveTranscript(
                        recordingId: recordingId,
                        segments: finalizedSegments,
                        durationSeconds: Int(recordingDuration.rounded())
                    )
                    transcriptSaved = detail.status != .failed
                    try? RecordingBackupStore.removeRecording(recordingId: recordingId)

                    if detail.status == .failed {
                        await MainActor.run {
                            self.error = detail.failureMessage ?? "Transcript was saved, but processing failed."
                        }
                    } else {
                        NSLog("[Recording] Transcript saved for recording %@", recordingId)
                    }
                } catch {
                    NSLog("[Recording] Transcript save failed: \(error)")
                    let failureMessage = error.localizedDescription
                    if let recoveredDetail = try? await self.recoverServerTranscript(
                        recordingId: recordingId,
                        client: client
                    ) {
                        try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                        transcriptSaved = recoveredDetail.status != .failed
                        await MainActor.run {
                            if recoveredDetail.status == .failed {
                                self.error = recoveredDetail.failureMessage ?? "Transcript was saved, but processing failed."
                            } else {
                                self.error = nil
                            }
                        }
                    } else {
                        let backup = try? await MainActor.run {
                            try self.saveTranscriptBackup(recordingId: recordingId, segments: finalizedSegments)
                        }
                        _ = try? RecordingBackupStore.recordSaveFailure(
                            recordingId: recordingId,
                            message: failureMessage
                        )

                        await MainActor.run {
                            if let backup {
                                self.error = "Transcript save failed. A local backup was saved at \(backup.directoryURL.path).\n\n\(failureMessage)"
                            } else {
                                self.error = "Transcript save failed: \(failureMessage)"
                            }
                        }
                    }
                }
            }

            await MainActor.run {
                self.isServerComplete = transcriptSaved
                self.recording = nil
                self.currentRecordingId = nil
                self.audioEncoder = nil
                self.setPhase(.idle)
                self.isCleaningUp = false
                self.cleanupTask = nil
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
        systemAudioWarning = nil
        duration = 0
    }

    func clearError() {
        error = nil
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
            .map { segment in
                let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return nil }
                if let speaker = segment.speaker, !speaker.isEmpty {
                    return "\(speaker): \(text)"
                }
                return text
            }
            .compactMap { $0 }
            .joined(separator: "\n\n")
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

    private func finalizedSegments(
        from segments: [LiveTranscriptSegment],
        didFinalize: Bool
    ) -> [LiveTranscriptSegment] {
        let trimmedInterim = interimText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedInterim.isEmpty else { return segments }
        guard !didFinalize || segments.isEmpty else { return segments }

        if let last = segments.last,
           last.text.trimmingCharacters(in: .whitespacesAndNewlines) == trimmedInterim,
           last.speaker == interimSpeaker {
            return segments
        }

        let fallbackStart = max(segments.last?.endMs ?? 0, Int(max(duration, 0) * 1000) - 1_000)
        let fallbackEnd = max(fallbackStart, Int(max(duration, 0) * 1000))
        return segments + [
            LiveTranscriptSegment(
                text: trimmedInterim,
                speaker: interimSpeaker,
                isFinal: true,
                startMs: fallbackStart,
                endMs: fallbackEnd,
                confidence: 0
            )
        ]
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

    @available(macOS 14.2, *)
    private func startSystemAudioMonitor(for dualCapture: DualAudioCapture) {
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled else { break }

                let stalled = dualCapture.systemAudioStalled
                let receivedAny = dualCapture.systemAudioReceivedAny

                await MainActor.run {
                    guard let self, self.phase == .recording else { return }
                    if stalled || !receivedAny {
                        self.systemAudioWarning = "System audio not detected — other participants may not be recorded"
                    } else {
                        self.systemAudioWarning = nil
                    }
                }
            }
        }
    }

    private func resetAfterStartFailure() async {
        timerTask?.cancel()
        timerTask = nil
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = nil
        systemAudioWarning = nil
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil

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

        setPhase(.finalizing)

        if let recordingId = currentRecordingId {
            let segments = finalizedSegments(
                from: await webSocketManager?.collectedSegments ?? [],
                didFinalize: false
            )
            let backupMessage = "Recording connection failed. A local transcript backup was saved on this Mac."
            let backup = try? saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments
            )
            _ = try? RecordingBackupStore.recordSaveFailure(recordingId: recordingId, message: message)
            if let client = apiClient {
                try? await client.deleteRecording(id: recordingId, permanent: true)
            }
            if let backup {
                error = "\(backupMessage)\n\n\(backup.directoryURL.path)\n\n\(message)"
            } else {
                error = message
            }
        } else {
            error = message
        }

        timerTask?.cancel()
        timerTask = nil
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = nil
        systemAudioWarning = nil
        audioTask?.cancel()
        audioTask = nil
        transcriptTask?.cancel()
        transcriptTask = nil
        cleanupTask?.cancel()
        cleanupTask = nil

        await audioCapture?.stopRecording()
        audioCapture = nil
        audioEncoder = nil

        let ws = webSocketManager
        webSocketManager = nil
        await ws?.disconnect()

        recording = nil
        currentRecordingId = nil
        apiClient = nil
        isServerComplete = false
        isCleaningUp = false
        recordingInputSource = .dual
        setPhase(.idle)
    }

    private func finishStreaming(_ manager: WebSocketManager?) async -> Bool {
        guard let manager else { return true }
        do {
            return try await manager.finishStreaming(timeout: .seconds(5))
        } catch {
            audioLog.error("Failed to finalize Deepgram stream: \(error.localizedDescription)")
            return false
        }
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
        systemAudioMonitorTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
        cleanupTask?.cancel()
    }
}
