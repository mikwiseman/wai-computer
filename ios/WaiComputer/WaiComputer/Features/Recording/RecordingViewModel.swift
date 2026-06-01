import Foundation
import AVFoundation
import Combine
import SwiftUI
import os
import Sentry
import WaiComputerKit

private let recordingLog = Logger(subsystem: "is.waiwai.computer.ios", category: "recording")

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
    @Published var recordingType: RecordingType = .meeting
    @Published var duration: TimeInterval = 0
    @Published var currentTranscript = ""
    /// Final, committed transcript without the interim/predicted tail. Drives
    /// the high-contrast portion of the live view so users can ignore the
    /// faded interim text that streams ahead of their speech.
    @Published var committedTranscript = ""
    /// Latest interim partial — the model's running guess that may be revised.
    @Published var interimTranscript = ""
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false
    @Published private(set) var phase: RecordingPhase = .idle
    @Published private(set) var isPaused = false
    @Published var connectionState: RecordingConnectionState = .connected
    @Published private(set) var liveTranscriptionOffline = false

    /// Committed (final) transcript lines, with speaker labels when available.
    private var committedLines: [(speaker: String?, text: String)] = []
    /// Current interim text (replaced on each new interim result).
    private var interimText = ""
    /// Speaker of the current interim result.
    private var interimSpeaker: String?

    /// Guards against starting a new recording while cleanup is in progress.
    private var isCleaningUp = false
    private var cleanupTask: Task<Void, Never>?

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
        statusText(language: LanguageManager.shared.current)
    }

    func statusText(language: LanguageManager.SupportedLanguage) -> String {
        switch phase {
        case .idle:
            return t("Tap to start recording", "Нажмите, чтобы начать запись", language: language)
        case .preparing:
            return t("Preparing recording...", "Готовим запись...", language: language)
        case .recording:
            if isPaused { return t("Paused", "Пауза", language: language) }
            return t("Recording...", "Идет запись...", language: language)
        case .finalizing:
            return t("Saving transcript...", "Сохраняем расшифровку...", language: language)
        }
    }

    var shouldShowTranscript: Bool {
        phase != .idle || !currentTranscript.isEmpty
    }

    var emptyTranscriptText: String {
        emptyTranscriptText(language: LanguageManager.shared.current)
    }

    func emptyTranscriptText(language: LanguageManager.SupportedLanguage) -> String {
        switch phase {
        case .idle:
            return t("Start a recording to see live transcription.", "Начните запись, чтобы увидеть живую расшифровку.", language: language)
        case .preparing:
            return t("Preparing microphone...", "Готовим микрофон...", language: language)
        case .recording:
            if isPaused { return t("Paused.", "Пауза.", language: language) }
            return t("Listening...", "Слушаем...", language: language)
        case .finalizing:
            return t("Saving...", "Сохраняем...", language: language)
        }
    }

    var canStartRecording: Bool {
        phase == .idle
    }

    var canStopRecording: Bool {
        phase == .recording
    }

    var canPauseRecording: Bool {
        phase == .recording && !isPaused
    }

    var canResumeRecording: Bool {
        phase == .recording && isPaused
    }

    var canDiscardRecording: Bool {
        phase == .recording
    }

    var isBusy: Bool {
        phase == .preparing || phase == .finalizing
    }

    func startRecording(apiClient: APIClient, folderId: String? = nil) async {
        // Wait for any in-progress cleanup to finish before starting a new recording.
        if isCleaningUp {
            recordingLog.info("Waiting for previous recording cleanup to complete")
            await cleanupTask?.value
        }

        guard phase == .idle else { return }

        error = nil
        currentTranscript = ""
        committedTranscript = ""
        interimTranscript = ""
        committedLines = []
        interimText = ""
        interimSpeaker = nil
        currentRecordingId = nil
        isServerComplete = false
        isPaused = false
        liveTranscriptionOffline = false
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
                error = t(
                    "Microphone permission denied. Open Settings → WaiComputer → Microphone to enable it.",
                    "Доступ к микрофону запрещен. Откройте Настройки → WaiComputer → Микрофон, чтобы включить его."
                )
                await resetAfterStartFailure()
                return
            }

            let language = UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
            recording = try await apiClient.createRecording(
                type: recordingType,
                language: language,
                folderId: folderId
            )

            guard let recordingId = recording?.id else {
                error = t("Failed to create recording", "Не удалось создать запись")
                await resetAfterStartFailure()
                return
            }

            currentRecordingId = recordingId

            // Create a provider-backed realtime transcription connection.
            let ws = WebSocketManager(apiClient: apiClient, language: language, channels: 1)
            self.webSocketManager = ws
            var liveEncoder: RealtimePCMEncoder?
            let eventStream = await ws.events

            transcriptTask = Task { [weak self] in
                for await event in eventStream {
                    guard !Task.isCancelled else { break }
                    guard let self else { break }
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect to the configured transcription provider.
            var isLiveTranscriptionActive = true
            do {
                let liveSessionConfig = try await apiClient.createRealtimeTranscriptionSession(
                    language: language,
                    channels: 1,
                    purpose: .recording
                )
                liveEncoder = RealtimePCMEncoder(
                    targetSampleRate: liveSessionConfig.sampleRate,
                    channels: liveSessionConfig.channels
                )
                try await ws.connect(using: liveSessionConfig)
            } catch {
                recordingLog.warning("Live transcription unavailable at recording start recordingId=\(recordingId, privacy: .public)")
                SentryHelper.addBreadcrumb(
                    category: "recording",
                    message: "live transcription unavailable at recording start",
                    level: .warning,
                    data: [
                        "recordingId": recordingId,
                        "reason": error.localizedDescription,
                    ]
                )
                isLiveTranscriptionActive = false
                liveTranscriptionOffline = true
            }

            let capture = MicrophoneCapture()
            let encoder = AudioEncoder()
            audioCapture = capture
            audioEncoder = encoder
            let realtimeEncoder = liveEncoder

            // Create local audio file writer for persistence (local-first)
            try RecordingBackupStore.ensureDirectoryForRecording(recordingId: recordingId)
            let audioFileURL = try RecordingBackupStore.audioFileURL(recordingId: recordingId)
            let fileWriter = try AudioFileWriter(fileURL: audioFileURL)
            self.audioFileWriter = fileWriter
            try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)

            let diskFullMessage = t(
                "Disk is full. Recording stopped to preserve what was captured.",
                "Диск заполнен. Запись остановлена, чтобы сохранить то, что успели записать."
            )

            audioTask = Task { [weak self, weak ws] in
                for await buffer in capture.audioBuffers {
                    guard !Task.isCancelled else { break }
                    guard let self, let ws else { break }
                    if let data = encoder.encode(buffer) {
                        // Local-first: always write to disk before sending over network.
                        let wrote = fileWriter.writeEncodedPCM(data)
                        if !wrote {
                            recordingLog.error("Disk write failed — stopping recording to preserve data")
                            await MainActor.run { self.error = diskFullMessage }
                            break
                        }

                        if isLiveTranscriptionActive {
                            do {
                                guard let liveData = realtimeEncoder?.encode(buffer) else {
                                    throw WebSocketConnectionError.serverError("Failed to encode realtime audio")
                                }
                                try await ws.sendAudio(data: liveData)
                            } catch {
                                recordingLog.warning("Realtime audio send failed; continuing with local backup only")
                                // Transcription dropped — fallback to local-only for the rest of this recording.
                                isLiveTranscriptionActive = false
                                await MainActor.run { self.liveTranscriptionOffline = true }
                            }
                        }
                    }
                }
            }

            try await capture.startRecording()
            startTimer()
            setPhase(.recording)

            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording started",
                data: ["recordingId": recordingId, "type": recordingType.rawValue]
            )

        } catch {
            SentryHelper.captureError(error, extras: ["action": "startRecording"])
            self.error = error.userFacingMessage(context: .recording)
            await resetAfterStartFailure()
        }
    }

    func stopRecording() async {
        if phase == .finalizing {
            await cleanupTask?.value
            return
        }

        guard phase == .recording else { return }

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording stopped",
            data: ["recordingId": currentRecordingId ?? "unknown", "duration": duration]
        )

        setPhase(.finalizing)
        isPaused = false

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        isCleaningUp = true

        let task = Task { [weak self] in
            guard let self else { return }

            // Stop audio capture first so no more audio is generated.
            await self.audioCapture?.stopRecording()
            self.audioCapture = nil

            let sendingTask = self.audioTask
            self.audioTask = nil
            _ = await sendingTask?.result

            // Capture finalized audio metrics before nilling the writer so we can
            // gate the upload on the shared min-duration policy.
            let fileWriter = self.audioFileWriter
            try? fileWriter?.finalize()
            self.audioFileWriter = nil
            let finalizedAudioDuration = fileWriter?.durationSeconds
            let finalizedAudioBytes = fileWriter?.totalBytesWritten ?? 0
            let uploadableAudioFileURL = self.uploadableFinalizedAudioFileURL(
                recordingId: self.currentRecordingId,
                fileWriter: fileWriter,
                audioDuration: finalizedAudioDuration,
                pcmBytesWritten: finalizedAudioBytes
            )

            let didFinalize = await self.finishStreaming(self.webSocketManager)

            // Collect final segments, preserving the last interim phrase if the provider never finalizes it.
            let segments = self.finalizedSegments(
                from: await self.webSocketManager?.collectedSegments ?? [],
                didFinalize: didFinalize
            )

            // Cancel transcript task and await completion, then disconnect.
            let pendingTranscriptTask = self.transcriptTask
            self.transcriptTask = nil
            pendingTranscriptTask?.cancel()
            _ = await pendingTranscriptTask?.result

            await self.webSocketManager?.disconnect()
            self.webSocketManager = nil

            // Persist the finalized live transcript.
            let client = self.apiClient
            self.apiClient = nil
            var transcriptSaved = false
            if let recordingId = self.currentRecordingId, let client {
                do {
                    let shouldUploadAudio = uploadableAudioFileURL != nil

                    let detail: RecordingDetail
                    if shouldUploadAudio, let uploadableAudioFileURL {
                        SentryHelper.addBreadcrumb(
                            category: "recording",
                            message: "uploading finalized audio for transcription",
                            data: ["recordingId": recordingId]
                        )
                        detail = try await client.uploadAudio(recordingId: recordingId, fileURL: uploadableAudioFileURL)
                    } else {
                        detail = try await client.saveLiveTranscript(
                            recordingId: recordingId,
                            segments: segments,
                            durationSeconds: Int(self.duration.rounded())
                        )
                    }
                    if detail.status == .failed {
                        let failureMessage = UserFacingErrorFormatter.displayMessage(
                            detail.failureMessage,
                            fallback: "Transcript was saved, but processing failed.",
                            context: .recording
                        )
                        let backup = try? self.saveTranscriptBackup(recordingId: recordingId, segments: segments)
                        _ = try? RecordingBackupStore.recordSaveFailure(recordingId: recordingId, message: failureMessage)
                        if backup != nil {
                            self.reportLocalRecoveryFallback(recordingId: recordingId, segmentsCount: segments.count, technicalReason: failureMessage)
                            await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
                            self.error = nil
                        } else {
                            self.error = failureMessage
                        }
                    } else if detail.status == .processing || detail.status == .uploading {
                        _ = try? self.saveTranscriptBackup(recordingId: recordingId, segments: segments)
                        do {
                            try RecordingBackupStore.markServerProcessing(recordingId: recordingId)
                        } catch {
                            SentryHelper.captureError(
                                error,
                                extras: ["action": "markServerProcessing", "recordingId": recordingId]
                            )
                            throw error
                        }
                        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
                        self.error = nil
                    } else {
                        try? RecordingBackupStore.removeRecording(recordingId: recordingId)
                        self.error = nil
                        transcriptSaved = true
                        SentryHelper.addBreadcrumb(
                            category: "recording",
                            message: shouldUploadAudio ? "audio uploaded for transcription" : "transcript saved",
                            data: ["recordingId": recordingId, "segments": segments.count]
                        )
                    }
                } catch {
                    SentryHelper.captureError(error, extras: ["action": "saveTranscript", "recordingId": recordingId])
                    let failureMessage = error.userFacingMessage(context: .recording)
                    let backup = try? self.saveTranscriptBackup(recordingId: recordingId, segments: segments)
                    _ = try? RecordingBackupStore.recordSaveFailure(recordingId: recordingId, message: failureMessage)
                    if backup != nil {
                        self.reportLocalRecoveryFallback(recordingId: recordingId, segmentsCount: segments.count, technicalReason: failureMessage)
                        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
                        self.error = nil
                    } else {
                        self.error = UserFacingErrorFormatter.message(
                            for: APIError.httpError(statusCode: 500, message: failureMessage),
                            context: .recording
                        )
                    }
                }
            }

            self.isServerComplete = transcriptSaved
            self.recording = nil
            self.currentRecordingId = nil
            self.audioEncoder = nil
            self.isPaused = false
            self.setPhase(.idle)
            self.isCleaningUp = false
            self.cleanupTask = nil
        }
        cleanupTask = task
        await task.value
    }

    /// Abort an in-progress recording without saving anything.
    ///
    /// Tears down the same capture/WS resources as `stopRecording`, but skips
    /// the cloud persistence step, deletes the partial server row, and removes
    /// the local audio file + backup so nothing about this take survives.
    func discardRecording() async {
        guard phase == .recording else { return }

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording discarded",
            data: ["recordingId": currentRecordingId ?? "unknown", "duration": duration]
        )

        setPhase(.finalizing)
        isPaused = false

        timerTask?.cancel()
        timerTask = nil

        isCleaningUp = true

        let task = Task { [weak self] in
            guard let self else { return }

            await self.audioCapture?.stopRecording()
            self.audioCapture = nil

            let sendingTask = self.audioTask
            self.audioTask = nil
            _ = await sendingTask?.result

            let pendingTranscriptTask = self.transcriptTask
            self.transcriptTask = nil
            pendingTranscriptTask?.cancel()
            _ = await pendingTranscriptTask?.result

            await self.webSocketManager?.disconnect()
            self.webSocketManager = nil

            let fileWriter = self.audioFileWriter
            self.audioFileWriter = nil
            try? fileWriter?.finalize()
            if let fileURL = fileWriter?.fileURL {
                try? FileManager.default.removeItem(at: fileURL)
            }

            let client = self.apiClient
            self.apiClient = nil
            if let recordingId = self.currentRecordingId, let client {
                do {
                    try await client.deleteRecording(id: recordingId, permanent: true)
                } catch {
                    SentryHelper.captureError(
                        error,
                        extras: ["action": "discardRecording", "recordingId": recordingId]
                    )
                }
                try? RecordingBackupStore.removeRecording(recordingId: recordingId)
            }

            self.isServerComplete = false
            self.recording = nil
            self.currentRecordingId = nil
            self.currentTranscript = ""
            self.committedTranscript = ""
            self.interimTranscript = ""
            self.committedLines = []
            self.interimText = ""
            self.interimSpeaker = nil
            self.audioEncoder = nil
            self.isPaused = false
            self.setPhase(.idle)
            self.isCleaningUp = false
            self.cleanupTask = nil
        }
        cleanupTask = task
        await task.value
    }

    func pauseRecording() async {
        guard canPauseRecording else { return }
        do {
            try await audioCapture?.pauseRecording()
            isPaused = true
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording paused",
                data: ["recordingId": currentRecordingId ?? "unknown", "duration": duration]
            )
        } catch {
            SentryHelper.captureError(error, extras: ["action": "pauseRecording", "recordingId": currentRecordingId ?? "unknown"])
            self.error = error.userFacingMessage(context: .recording)
        }
    }

    func resumeRecording() async {
        guard canResumeRecording else { return }
        do {
            try await audioCapture?.resumeRecording()
            isPaused = false
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording resumed",
                data: ["recordingId": currentRecordingId ?? "unknown", "duration": duration]
            )
        } catch {
            SentryHelper.captureError(error, extras: ["action": "resumeRecording", "recordingId": currentRecordingId ?? "unknown"])
            self.error = error.userFacingMessage(context: .recording)
        }
    }

    /// Reset transcript and recording state.
    func resetState() {
        currentTranscript = ""
        committedTranscript = ""
        interimTranscript = ""
        committedLines = []
        interimText = ""
        interimSpeaker = nil
        currentRecordingId = nil
        isServerComplete = false
        connectionState = .connected
        duration = 0
        isPaused = false
    }

    // MARK: - Private

    private func uploadableFinalizedAudioFileURL(
        recordingId: String?,
        fileWriter: AudioFileWriter?,
        audioDuration: Double?,
        pcmBytesWritten: Int64
    ) -> URL? {
        guard let fileWriter else { return nil }
        guard FileManager.default.fileExists(atPath: fileWriter.fileURL.path) else { return nil }

        if RecordingAudioUploadPolicy.canUploadFinalizedAudio(
            durationSeconds: audioDuration,
            pcmBytesWritten: pcmBytesWritten
        ) {
            return fileWriter.fileURL
        }

        if let recordingId {
            try? RecordingBackupStore.discardAudioFile(recordingId: recordingId)
        }
        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "local audio below upload minimum",
            level: .warning,
            data: [
                "recordingId": recordingId ?? "unknown",
                "audioDurationSeconds": audioDuration ?? 0,
                "audioBytes": pcmBytesWritten,
                "minimumDurationSeconds": RecordingAudioUploadPolicy.minimumDurationSeconds,
            ]
        )
        recordingLog.warning(
            "Skipping finalized audio upload durationSeconds=\(audioDuration ?? 0, privacy: .public) bytes=\(pcmBytesWritten, privacy: .public)"
        )
        return nil
    }

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

    private func finishStreaming(_ manager: WebSocketManager?) async -> Bool {
        guard let manager else { return true }
        do {
            return try await manager.finishStreaming(timeout: .seconds(5))
        } catch {
            recordingLog.warning("Failed to finalize realtime transcription stream")
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
                    guard let self, !self.isPaused else { return }
                    self.duration += 1
                }
            }
        }
    }

    private func resetAfterStartFailure() async {
        let recordingId = currentRecordingId
        let client = apiClient
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

        // Cancel and await both tasks after stopping audio (which finishes the stream).
        pendingAudioTask?.cancel()
        _ = await pendingAudioTask?.result
        pendingTranscriptTask?.cancel()
        _ = await pendingTranscriptTask?.result

        let ws = webSocketManager
        webSocketManager = nil
        apiClient = nil
        await ws?.disconnect()

        if let recordingId, let client {
            do {
                try await client.deleteRecording(id: recordingId, permanent: true)
            } catch {
                SentryHelper.captureError(
                    error,
                    extras: ["action": "deleteAbortedRecording", "recordingId": recordingId]
                )
            }
            try? RecordingBackupStore.removeRecording(recordingId: recordingId)
        }

        recording = nil
        currentRecordingId = nil
        isServerComplete = false
        isPaused = false
        setPhase(.idle)
    }

    private func setPhase(_ newPhase: RecordingPhase) {
        if newPhase != .recording {
            isPaused = false
        }
        // Animate transitions to/from idle so the controls cross-fade smoothly.
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
            } else {
                interimText = segment.text
                interimSpeaker = segment.speaker
            }
            currentTranscript = buildTranscriptText()
            committedTranscript = buildCommittedTranscriptText()
            interimTranscript = buildInterimTranscriptText()
        case .disconnected(let err):
            if let err, phase == .recording {
                await continueRecordingWithoutLiveTranscription(
                    reason: "websocket_disconnected",
                    error: err
                )
            } else if let err, phase != .finalizing, phase != .idle {
                error = err.userFacingMessage(context: .recording)
            }
        case .reconnecting(let attempt, let maxAttempts):
            connectionState = .reconnecting(attempt: attempt, maxAttempts: maxAttempts)
        case .reconnected:
            connectionState = .connected
            error = nil
        case .reconnectionFailed(let err):
            connectionState = .connected
            if phase == .recording {
                await continueRecordingWithoutLiveTranscription(
                    reason: "websocket_reconnection_failed",
                    error: err
                )
            } else if phase != .finalizing, phase != .idle {
                error = err?.userFacingMessage(context: .recording)
                    ?? UserFacingErrorFormatter.message(
                        for: WebSocketConnectionError.reconnectionExhausted(10),
                        context: .recording
                    )
            }
        }
    }

    /// When the realtime stream drops mid-recording, keep capturing audio
    /// locally instead of finalizing — the transcript is generated server-side
    /// on the uploaded audio when the user stops. The offline banner surfaces
    /// this so continuing isn't silent.
    private func continueRecordingWithoutLiveTranscription(
        reason: String,
        error: Error?
    ) async {
        guard phase == .recording else {
            if let error, phase != .finalizing, phase != .idle {
                self.error = error.userFacingMessage(context: .recording)
            }
            return
        }

        connectionState = .connected
        liveTranscriptionOffline = true
        self.error = nil

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "live transcription disabled while local recording continues",
            level: .warning,
            data: [
                "recordingId": currentRecordingId ?? "unknown",
                "reason": reason,
                "durationSeconds": duration,
                "errorType": error.map { String(describing: type(of: $0)) } ?? "none",
            ]
        )
        await webSocketManager?.stopRealtimeStreamingForLocalRecording(reason: reason)
    }

    /// Combined committed + interim text used by accessibility/legacy consumers.
    private func buildTranscriptText() -> String {
        let committed = buildCommittedTranscriptText()
        let interim = buildInterimTranscriptText()
        if interim.isEmpty { return committed }
        if committed.isEmpty { return interim }
        // Speaker mode uses a paragraph break, single-channel uses a space.
        return shouldShowSpeakers
            ? committed + "\n\n" + interim
            : committed + " " + interim
    }

    /// True when realtime metadata carries any non-empty speaker labels.
    private var shouldShowSpeakers: Bool {
        committedLines.contains { speaker, _ in
            guard let speaker else { return false }
            return !speaker.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        } || !(interimSpeaker?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
    }

    /// Committed lines only — never includes the rolling interim guess.
    private func buildCommittedTranscriptText() -> String {
        guard shouldShowSpeakers else {
            return committedLines.map(\.text).joined(separator: " ")
        }
        var parts: [String] = []
        var currentSpeaker: String? = nil
        var currentText = ""
        for line in committedLines {
            let speaker = line.speaker ?? "Speaker"
            if speaker == currentSpeaker {
                currentText += " " + line.text
            } else {
                if !currentText.isEmpty, let s = currentSpeaker {
                    parts.append("\(displaySpeaker(s)): \(currentText)")
                }
                currentSpeaker = speaker
                currentText = line.text
            }
        }
        if !currentText.isEmpty, let s = currentSpeaker {
            parts.append("\(displaySpeaker(s)): \(currentText)")
        }
        return parts.joined(separator: "\n\n")
    }

    /// Just the trailing interim text, with a speaker prefix when relevant.
    private func buildInterimTranscriptText() -> String {
        guard !interimText.isEmpty else { return "" }
        if !shouldShowSpeakers {
            return interimText
        }
        // Avoid duplicating the speaker prefix when the interim line continues
        // the same (raw) speaker as the most recent committed line.
        let lastSpeaker = committedLines.last?.speaker
        if interimSpeaker == lastSpeaker {
            return interimText
        }
        let speaker = interimSpeaker.map(displaySpeaker) ?? "..."
        return "\(speaker): \(interimText)"
    }

    /// Localize a raw diarization label ("speaker_0") to the app-language display
    /// label ("Говорящий 1" / "Speaker 1") for the live transcript.
    private func displaySpeaker(_ rawLabel: String) -> String {
        SpeakerLabelCopy.userFacingLabel(rawLabel, languageCode: speakerLanguageCode)
            ?? t("Speaker", "Говорящий")
    }

    private var speakerLanguageCode: String {
        switch LanguageManager.shared.current {
        case .followSystem:
            return LanguageManager.shared.preferredLocale.identifier
        case .english, .russian:
            return LanguageManager.shared.current.rawValue
        }
    }

    private func reportLocalRecoveryFallback(
        recordingId: String,
        segmentsCount: Int,
        technicalReason: String
    ) {
        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording saved to local recovery fallback",
            level: .warning,
            data: [
                "recordingId": recordingId,
                "segments": segmentsCount,
                "reason": technicalReason,
            ]
        )
        postRecoveryNotice(localTranscriptRecoveryMessage(segmentsCount: segmentsCount))
    }

    private func localTranscriptRecoveryMessage(segmentsCount: Int) -> String {
        if segmentsCount > 0 {
            return t(
                "Connection was interrupted, but your recording is safe on this device. We'll keep syncing it automatically in the background.",
                "Соединение прервалось, но запись сохранена на этом устройстве. Мы продолжим автоматически синхронизировать ее в фоне."
            )
        }
        return t(
            "Connection was interrupted before speech could sync, but your recording is safe on this device.",
            "Соединение прервалось до синхронизации речи, но запись сохранена на этом устройстве."
        )
    }

    private func postRecoveryNotice(_ message: String) {
        NotificationCenter.default.post(
            name: .pendingRecordingRecoveryNotice,
            object: nil,
            userInfo: ["message": message]
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        t(english, russian, language: LanguageManager.shared.current)
    }

    private func t(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        OnboardingL10n.text(english, russian, language: language)
    }

    deinit {
        timerTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
        cleanupTask?.cancel()
    }
}
