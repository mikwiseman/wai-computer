import Foundation
import AVFoundation
import SwiftUI
import os
import Sentry
import WaiComputerKit

private let audioLog = Logger(subsystem: "is.waiwai.computer.app", category: "audio")

enum MacRecordingInputSource: String, CaseIterable, Equatable {
    case dual        // mic + system audio (default)
    case microphone  // mic only
    case systemAudio = "system_audio"

    var label: String {
        localizedLabel(language: .english)
    }

    func localizedLabel(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .dual:
            return OnboardingL10n.text("Mic + System Audio", "Микрофон + звук Mac", language: language)
        case .microphone:
            return OnboardingL10n.text("Microphone", "Микрофон", language: language)
        case .systemAudio:
            return OnboardingL10n.text("System Audio", "Звук Mac", language: language)
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
        preparingText(language: .english)
    }

    func preparingText(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .dual:
            return OnboardingL10n.text("Preparing audio capture...", "Готовим захват аудио...", language: language)
        case .microphone:
            return OnboardingL10n.text("Preparing microphone...", "Готовим микрофон...", language: language)
        case .systemAudio:
            return OnboardingL10n.text("Preparing system audio...", "Готовим звук Mac...", language: language)
        }
    }

    var requestsSystemAudio: Bool {
        self == .dual || self == .systemAudio
    }
}

enum MacRecordingPhase: Equatable {
    case idle
    case preparing
    case recording
    case finalizing
}

enum RecordingConnectionState: Equatable {
    case connected
    case reconnecting(attempt: Int, maxAttempts: Int)
}

/// Typed classification for the current recording `error`, so alert actions
/// (e.g. "Open Microphone Settings") key off semantics instead of matching
/// localized message substrings — which silently broke for non-English UI.
enum RecordingErrorKind {
    case micPermission
    case systemAudio
    case general
}

@MainActor
class MacRecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String? {
        // Every new message defaults to .general; throw sites that know the
        // semantic cause overwrite the kind immediately after assigning.
        didSet { errorKind = .general }
    }
    @Published var errorKind: RecordingErrorKind = .general
    @Published var recordingType: RecordingType = .note
    @Published var recordingInputSource: MacRecordingInputSource = SystemAudioGate.isSupported ? .dual : .microphone
    @Published var duration: TimeInterval = 0
    @Published var hasSystemAudio = false
    var currentTranscript: String {
        combinedTranscript(committed: committedTranscript, interim: interimTranscript)
    }
    /// Final, committed transcript without the interim/predicted tail. Drives
    /// the high-contrast portion of the live view so users can ignore the
    /// faded interim text that streams ahead of their speech.
    private(set) var committedTranscript = ""
    private(set) var committedTranscriptChunks: [LiveTranscriptDisplayChunk] = []
    private(set) var committedTranscriptRevision = 0
    /// Latest interim partial — the model's running guess that may be revised.
    private(set) var interimTranscript = ""
    private(set) var interimTranscriptRevision = 0
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false
    @Published private(set) var phase: MacRecordingPhase = .idle
    @Published private(set) var isPaused = false
    @Published var systemAudioWarning: String?
    @Published var connectionState: RecordingConnectionState = .connected
    @Published private(set) var liveTranscriptionOffline = false

    /// Committed (final) transcript lines, with speaker labels when available.
    private var committedLines: [(speaker: String?, text: String)] = []
    private var committedTranscriptHasSpeakerLabels = false
    /// Current interim text (replaced on each new interim result)
    private var interimText = ""
    /// Speaker of the current interim result
    private var interimSpeaker: String?

    /// Guards against starting a new recording while cleanup is in progress
    private var isCleaningUp = false
    private let testingMode: MacTestingMode

    private var recording: Recording?
    private var apiClient: APIClient?
    /// Bumped on every start attempt and when a start is aborted. A start that is
    /// superseded (e.g. the user discards while audio capture is still preparing)
    /// checks this before flipping to `.recording`, so a stuck/slow start can never
    /// resurrect a phantom recording after the user has escaped it.
    private var startGeneration = 0
    private var audioCapture: (any AudioCaptureProtocol)?
    private var audioEncoder: AudioEncoder?
    private var audioFileWriter: AudioFileWriter?
    private var webSocketManager: WebSocketManager?
    private var timerTask: Task<Void, Never>?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?
    private var cleanupTask: Task<Void, Never>?
    private var systemAudioMonitorTask: Task<Void, Never>?
    private var recordingActivity: NSObjectProtocol?

    private enum RecordingPersistenceResult {
        case remoteSaved(notice: String?, breadcrumbMessage: String)
        case localBackup
        case localPermanentBackup(String)
        case failed(String)
    }


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

    var canPauseRecording: Bool {
        phase == .recording && !isPaused
    }

    var canResumeRecording: Bool {
        phase == .recording && isPaused
    }

    var statusText: String {
        statusText(language: LanguageManager.shared.current)
    }

    func statusText(language: LanguageManager.SupportedLanguage) -> String {
        switch phase {
        case .idle:
            return t("Ready to record", "Готово к записи", language: language)
        case .preparing:
            return t("Preparing recording", "Готовим запись", language: language)
        case .recording:
            if isPaused {
                return t("Paused", "Пауза", language: language)
            }
            return t("Recording", "Идет запись", language: language)
        case .finalizing:
            return t("Saving transcript...", "Сохраняем расшифровку...", language: language)
        }
    }

    /// Whether dual capture is mixing both sources into a single mono channel
    /// (for diarization-based speaker identification in group calls).
    private var isDualMixedToMono: Bool {
        if #available(macOS 14.2, *),
           let dualCapture = audioCapture as? DualAudioCapture {
            return dualCapture.mixToMono && hasSystemAudio
        }
        return false
    }

    /// Number of audio channels being streamed to the realtime transcription provider.
    var audioChannels: Int {
        if recordingInputSource == .dual && hasSystemAudio {
            if #available(macOS 14.2, *),
               let dualCapture = audioCapture as? DualAudioCapture,
               dualCapture.mixToMono {
                return 1  // Mono mix — provider-side speaker inference
            }
            return 2  // Multichannel mode
        }
        return 1
    }

    var emptyTranscriptText: String {
        emptyTranscriptText(language: LanguageManager.shared.current)
    }

    func emptyTranscriptText(language: LanguageManager.SupportedLanguage) -> String {
        switch phase {
        case .idle:
            return t("Ready to record.", "Готово к записи.", language: language)
        case .preparing:
            return recordingInputSource.preparingText(language: language)
        case .recording:
            if isPaused {
                return t("Paused.", "Пауза.", language: language)
            }
            return t("Listening...", "Слушаем...", language: language)
        case .finalizing:
            return t("Saving...", "Сохраняем...", language: language)
        }
    }

    init(testingMode: MacTestingMode = .current) {
        self.testingMode = testingMode
    }

    func startRecording(
        apiClient: APIClient,
        type: RecordingType,
        inputSource: MacRecordingInputSource = .dual,
        folderId: String? = nil
    ) async {
        // System audio (dual / system-only) needs macOS 14.2+ Core Audio process taps.
        // Below that floor, record microphone only — surfaced to users in onboarding and
        // Settings, never a silent error (the OS simply lacks the capability).
        let inputSource = SystemAudioGate.isSupported ? inputSource : .microphone

        // Wait for any in-progress cleanup to finish before starting a new recording
        if isCleaningUp {
            audioLog.info("Waiting for previous recording cleanup to complete")
            await cleanupTask?.value
        }

        if phase == .preparing {
            audioLog.info("Ignoring recording start while preparation is in progress")
            return
        }

        if phase == .recording || phase == .finalizing {
            audioLog.info("Stopping previous recording before starting a new one")
            await stopRecording()
        }

        guard phase == .idle else {
            audioLog.info("Ignoring recording start while phase=\(String(describing: self.phase), privacy: .public)")
            return
        }

        isLoading = true
        error = nil
        setLiveTranscript(committed: "", interim: "")
        committedLines = []
        committedTranscriptHasSpeakerLabels = false
        interimText = ""
        interimSpeaker = nil
        isServerComplete = false
        isPaused = false
        liveTranscriptionOffline = false
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
        startGeneration &+= 1
        let activeStartGeneration = startGeneration

        #if DEBUG
        if testingMode.isRecordingFlow {
            currentRecordingId = MacUITestFixtures.completedRecording.id
            setLiveTranscript(committed: "UI test live transcript.", interim: "")
            duration = TimeInterval(MacUITestFixtures.completedRecording.durationSeconds ?? 0)
            setPhase(.recording)
            isLoading = false
            return
        }
        #endif

        do {
            // Mic permission is always needed (dual and mic-only both use mic).
            // Use `AVCaptureDevice.requestAccess(for: .audio)` — the canonical
            // macOS API. `AVAudioApplication.requestRecordPermission` is iOS-
            // first and has been observed silently failing on macOS 26 (Tahoe),
            // which is why the in-app "Grant Permission" banner used to feel
            // dead.
            if inputSource == .dual || inputSource == .microphone {
                let currentStatus = AVCaptureDevice.authorizationStatus(for: .audio)
                if currentStatus == .authorized {
                    SentryHelper.addBreadcrumb(
                        category: "recording",
                        message: "mic permission already granted",
                        data: ["inputSource": inputSource.rawValue]
                    )
                } else {
                    SentryHelper.addBreadcrumb(
                        category: "recording",
                        message: "mic permission needs prompt",
                        data: [
                            "inputSource": inputSource.rawValue,
                            "status": currentStatus.statusName,
                        ]
                    )
                    let granted = await AVCaptureDevice.requestAccess(for: .audio)
                    SentryHelper.addBreadcrumb(
                        category: "recording",
                        message: "mic permission prompt resolved",
                        data: ["granted": granted]
                    )
                    guard granted else {
                        error = t(
                            "Microphone permission denied. Open System Settings -> Privacy & Security -> Microphone and enable WaiComputer.",
                            "Доступ к микрофону запрещен. Открой Системные настройки -> Конфиденциальность и безопасность -> Микрофон и включи WaiComputer."
                        )
                        errorKind = .micPermission
                        await resetAfterStartFailure()
                        return
                    }
                }
            }

            // Create recording on server
            let language = DictationLanguageSelectionPolicy.providerLanguage(store: nil)
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
            beginRecordingActivity(recordingId: recordingId, inputSource: inputSource)

            // Initialize audio capture first to know channel count
            let capture = try makeAudioCapture(for: inputSource)
            audioCapture = capture

            // Check if dual capture actually got system audio
            if #available(macOS 14.2, *), let dualCapture = capture as? DualAudioCapture {
                audioLog.info("Starting dual audio capture")
                try await capture.startRecording()
                hasSystemAudio = dualCapture.hasSystemAudio
                audioLog.info("Dual audio capture started systemAudio=\(self.hasSystemAudio, privacy: .public)")
            } else {
                audioLog.info("Starting audio capture")
                try await capture.startRecording()
            }

            // Now we know the real channel count. Local persistence keeps the
            // capture channel layout; realtime STT uses the server-declared
            // PCM format from the minted session.
            let channels = audioChannels
            let channelMode = isDualMixedToMono ? "mono-mix" : channels > 1 ? "multichannel" : "mono"
            audioLog.info("Audio capture channels=\(channels, privacy: .public) mode=\(channelMode, privacy: .public)")

            let ws = WebSocketManager(apiClient: apiClient, language: language, channels: channels)
            self.webSocketManager = ws
            var liveEncoder: RealtimePCMEncoder?

            // Set up event stream BEFORE connecting
            let eventStream = await ws.events

            // Start receiving transcripts BEFORE connecting
            transcriptTask = Task { [weak self] in
                guard let self else { return }
                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
                }
            }

            // Connect to the configured realtime transcription provider.
            var isLiveTranscriptionActive = true
            do {
                let liveSessionConfig = try await apiClient.createRealtimeTranscriptionSession(
                    language: language,
                    channels: channels,
                    purpose: .recording
                )
                liveEncoder = RealtimePCMEncoder(
                    targetSampleRate: liveSessionConfig.sampleRate,
                    channels: liveSessionConfig.channels
                )
                try await ws.connect(using: liveSessionConfig)
            } catch {
                audioLog.warning("Live transcription unavailable at recording start")
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

            let encoder = AudioEncoder(channels: channels)
            audioEncoder = encoder
            let realtimeEncoder = liveEncoder

            // Create local audio file writer for persistence (local-first)
            try RecordingBackupStore.ensureDirectoryForRecording(recordingId: recordingId)
            let audioFileURL = try RecordingBackupStore.audioFileURL(recordingId: recordingId)
            let fileWriter = try AudioFileWriter(fileURL: audioFileURL, sampleRate: 16000, channels: channels)
            self.audioFileWriter = fileWriter
            try RecordingBackupStore.markHasAudioFile(recordingId: recordingId)
            audioLog.info("Local recording audio file prepared recordingId=\(recordingId, privacy: .public)")

            // Start the audio-sending loop
            audioLog.info("Starting recording audio task")
            var bufferCount = 0
            let diskFullMessage = t(
                "Disk is full. Recording stopped to preserve what was captured.",
                "Диск заполнен. Запись остановлена для сохранения того, что успели записать."
            )
            audioTask = Task.detached(priority: .userInitiated) { [weak self] in
                guard let self else { return }
                audioLog.info("Recording audio task started")
                for await buffer in capture.audioBuffers {
                    bufferCount += 1
                    if bufferCount <= 5 || bufferCount % 50 == 0 {
                        audioLog.debug("Recording buffer count=\(bufferCount, privacy: .public) frames=\(buffer.frameLength, privacy: .public)")
                    }
                    if let data = encoder.encode(buffer) {
                        if bufferCount <= 5 || bufferCount % 50 == 0 {
                            audioLog.debug("Encoded recording audio bytes=\(data.count, privacy: .public)")
                        }
                        // Local-first: always write to disk before sending over network
                        let wrote = fileWriter.writeEncodedPCM(data)
                        if !wrote {
                            audioLog.error("Disk write failed — stopping recording to preserve data")
                            await MainActor.run {
                                self.error = diskFullMessage
                                // Actually stop, so the UI can't keep claiming
                                // "Recording" (timer ticking, red dot pulsing)
                                // while zero audio is captured. Fire-and-forget:
                                // stopRecording awaits this very audio task's
                                // result, so awaiting it inline would deadlock.
                                Task { await self.stopAfterAudioWriteFailure() }
                            }
                            return
                        }

                        if isLiveTranscriptionActive {
                            do {
                                guard let liveData = realtimeEncoder?.encode(buffer) else {
                                    throw WebSocketConnectionError.serverError("Failed to encode realtime audio")
                                }
                                try await ws.sendAudio(data: liveData)
                            } catch {
                                audioLog.warning("Realtime audio send failed; continuing with local backup only")
                                // Transcription dropped — fallback to local-only for the rest of this recording
                                isLiveTranscriptionActive = false
                                await continueRecordingWithoutLiveTranscription(
                                    reason: "realtime_audio_send_failed",
                                    error: error
                                )
                            }
                        }
                    }
                }
                audioLog.info("Recording audio task finished")
            }

            // If the user aborted while we were preparing (e.g. audio capture
            // stalled), don't flip to .recording — tear down the orphaned capture
            // and bail so the phase stays idle.
            guard activeStartGeneration == startGeneration else {
                audioLog.info("Abandoning superseded recording start")
                await capture.stopRecording()
                return
            }

            startTimer()

            // Monitor system audio stall status for telemetry and the compact
            // header state. Setup belongs in onboarding, not a live banner.
            if #available(macOS 14.2, *), let dualCapture = capture as? DualAudioCapture {
                startSystemAudioMonitor(for: dualCapture)
            }

            setPhase(.recording)
            isLoading = false

            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording started",
                data: ["recordingId": recordingId, "type": type.rawValue, "inputSource": inputSource.rawValue]
            )

        } catch {
            SentryHelper.captureError(error, extras: ["action": "startRecording", "inputSource": inputSource.rawValue])
            self.error = recordingErrorMessage(for: error, inputSource: inputSource)
            self.errorKind = recordingErrorKind(for: error, inputSource: inputSource)
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
                    try? self?.audioFileWriter?.finalize()
                    self?.audioFileWriter = nil
                    self?.endRecordingActivity(reason: "debug-stop")
                    self?.setPhase(.idle)
                    self?.isPaused = false
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
        let timerDuration = duration
        let capture = audioCapture
        let sendingTask = audioTask
        let fileWriter = audioFileWriter
        audioTask = nil
        webSocketManager = nil
        transcriptTask = nil
        self.apiClient = nil
        audioCapture = nil
        audioFileWriter = nil

        let task = Task { [weak self] in
            guard let self else { return }

            // Stop audio capture first so the encoder can drain the final buffers.
            await capture?.stopRecording()
            _ = await sendingTask?.result

            // Finalize the local WAV file so it has correct header sizes.
            let audioFinalizedForPersistence = self.finalizeRecordingAudioForPersistence(
                fileWriter,
                recordingId: recordingId
            )
            let finalizedAudioDuration = fileWriter?.durationSeconds
            let finalizedAudioBytes = fileWriter?.totalBytesWritten ?? 0
            let persistedDurationSeconds = self.persistedDurationSeconds(
                audioDuration: finalizedAudioDuration,
                timerDuration: timerDuration
            )
            if let fw = fileWriter {
                audioLog.info("Local audio finalized durationSeconds=\(fw.durationSeconds, privacy: .public) bytes=\(fw.totalBytesWritten, privacy: .public)")
            }
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "local audio finalized",
                data: [
                    "recordingId": recordingId ?? "unknown",
                    "audioDurationSeconds": finalizedAudioDuration ?? 0,
                    "timerDurationSeconds": timerDuration,
                    "persistedDurationSeconds": persistedDurationSeconds,
                    "audioBytes": finalizedAudioBytes,
                ]
            )
            let uploadableAudioFileURL = audioFinalizedForPersistence
                ? self.uploadableFinalizedAudioFileURL(
                    recordingId: recordingId,
                    fileWriter: fileWriter,
                    audioDuration: finalizedAudioDuration,
                    pcmBytesWritten: finalizedAudioBytes
                )
                : nil

            let didFinalize = await self.finishStreaming(ws)
            let segments = await ws?.collectedSegments ?? []
            let finalizedSegments = await MainActor.run {
                self.finalizedSegments(from: segments, didFinalize: didFinalize)
            }

            tTask?.cancel()
            await ws?.disconnect()

            let transcriptSaved: Bool
            if let recordingId {
                let persistenceResult = await self.persistRecordingForBackgroundSync(
                    recordingId: recordingId,
                    client: client,
                    segments: finalizedSegments,
                    durationSeconds: persistedDurationSeconds,
                    audioFileURL: uploadableAudioFileURL
                )
                transcriptSaved = await self.applyRecordingPersistenceResult(
                    persistenceResult,
                    recordingId: recordingId,
                    segmentsCount: finalizedSegments.count
                )
            } else {
                transcriptSaved = false
            }

            await MainActor.run {
                self.isServerComplete = transcriptSaved
                self.recording = nil
                self.currentRecordingId = nil
                self.audioEncoder = nil
                self.endRecordingActivity(reason: "stop")
                self.setPhase(.idle)
                self.isPaused = false
                self.isCleaningUp = false
                self.cleanupTask = nil
            }
        }
        cleanupTask = task
        await task.value
    }

    /// Honest-failure path for the audio loop: when disk writes start failing
    /// the recording must actually stop — leaving the phase at `.recording`
    /// would keep the timer ticking and the red dot pulsing while zero audio
    /// is captured, and the disk-full alert ("Recording stopped…") would lie.
    /// Routes through the same teardown as a user stop so whatever was
    /// captured is finalized and persisted.
    private func stopAfterAudioWriteFailure() async {
        switch phase {
        case .recording:
            await stopRecording()
        case .preparing:
            // Capture streams (and can fail to write) before start flips to
            // `.recording`. Supersede the in-flight start so it can't
            // resurrect a dead loop, then tear down — the same escape
            // discardRecording uses for a stalled start.
            startGeneration &+= 1
            await resetAfterStartFailure()
        case .idle, .finalizing:
            break
        }
    }

    /// Abort an in-progress recording without saving anything.
    ///
    /// Tears down the same capture/WS resources as `stopRecording`, but skips
    /// the cloud persistence step, deletes the partial server row, and removes
    /// the local audio file + backup so nothing about this take survives.
    func discardRecording() async {
        // Allow escaping a start that is still preparing (e.g. audio capture
        // stalled) — not only an active recording. Otherwise a stuck "Preparing
        // recording…" would trap the user with a dead Record button.
        if phase == .preparing {
            startGeneration &+= 1
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording start aborted while preparing",
                data: ["recordingId": currentRecordingId ?? "unknown"]
            )
            await resetAfterStartFailure()
            return
        }

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
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = nil
        systemAudioWarning = nil

        isCleaningUp = true

        let ws = webSocketManager
        let tTask = transcriptTask
        let recordingId = currentRecordingId
        let client = self.apiClient
        let capture = audioCapture
        let sendingTask = audioTask
        let fileWriter = audioFileWriter
        audioTask = nil
        webSocketManager = nil
        transcriptTask = nil
        self.apiClient = nil
        audioCapture = nil
        audioFileWriter = nil

        let task = Task { [weak self] in
            guard let self else { return }

            await capture?.stopRecording()
            _ = await sendingTask?.result

            tTask?.cancel()
            await ws?.disconnect()

            try? fileWriter?.finalize()
            if let fileURL = fileWriter?.fileURL {
                try? FileManager.default.removeItem(at: fileURL)
            }

            if let recordingId, let client {
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

            await MainActor.run {
                self.isServerComplete = false
                self.recording = nil
                self.currentRecordingId = nil
                self.setLiveTranscript(committed: "", interim: "")
                self.committedLines = []
                self.committedTranscriptHasSpeakerLabels = false
                self.interimText = ""
                self.interimSpeaker = nil
                self.audioEncoder = nil
                self.endRecordingActivity(reason: "discard")
                self.setPhase(.idle)
                self.isPaused = false
                self.isCleaningUp = false
                self.cleanupTask = nil
            }
        }
        cleanupTask = task
        await task.value
    }

    /// Reset transcript and recording state.
    func resetState() {
        setLiveTranscript(committed: "", interim: "")
        committedLines = []
        committedTranscriptHasSpeakerLabels = false
        interimText = ""
        interimSpeaker = nil
        currentRecordingId = nil
        isServerComplete = false
        systemAudioWarning = nil
        connectionState = .connected
        duration = 0
        isPaused = false
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

    func clearError() {
        error = nil
    }

    #if DEBUG
    func testingBeginRecordingForRealtimeFailure(
        recordingId: String,
        duration: TimeInterval = 0
    ) {
        currentRecordingId = recordingId
        self.duration = duration
        liveTranscriptionOffline = false
        isPaused = false
        connectionState = .connected
        error = nil
        setPhase(.recording)
    }

    func testingHandleWebSocketEvent(_ event: WebSocketEvent) async {
        await handleWebSocketEvent(event)
    }
    #endif

    // MARK: - Private

    private func beginRecordingActivity(recordingId: String, inputSource: MacRecordingInputSource) {
        endRecordingActivity(reason: "replace")
        let options: ProcessInfo.ActivityOptions = [
            .userInitiated,
            .idleSystemSleepDisabled,
            .suddenTerminationDisabled,
            .automaticTerminationDisabled,
        ]
        recordingActivity = ProcessInfo.processInfo.beginActivity(
            options: options,
            reason: "WaiComputer recording local audio"
        )
        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording activity started",
            data: ["recordingId": recordingId, "inputSource": inputSource.rawValue]
        )
    }

    private func endRecordingActivity(reason: String) {
        guard let activity = recordingActivity else { return }
        ProcessInfo.processInfo.endActivity(activity)
        recordingActivity = nil
        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording activity ended",
            data: ["reason": reason]
        )
    }

    private func persistedDurationSeconds(
        audioDuration: Double?,
        timerDuration: TimeInterval
    ) -> Int {
        guard let audioDuration, audioDuration > 0 else {
            return max(Int(timerDuration.rounded()), 0)
        }
        if timerDuration - audioDuration > 5 {
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording duration mismatch",
                level: .warning,
                data: [
                    "audioDurationSeconds": audioDuration,
                    "timerDurationSeconds": timerDuration,
                ]
            )
        }
        return max(Int(audioDuration.rounded()), 0)
    }

    private func uploadableFinalizedAudioFileURL(
        recordingId: String?,
        fileWriter: AudioFileWriter?,
        audioDuration: Double?,
        pcmBytesWritten: Int64
    ) -> URL? {
        guard let fileWriter else { return nil }
        guard FileManager.default.fileExists(atPath: fileWriter.fileURL.path) else { return nil }
        if fileWriter.hasWriteFailure {
            if let recordingId {
                discardLocalAudioFileForTranscriptOnlySync(
                    recordingId: recordingId,
                    reason: "write_failure"
                )
            }
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "local audio write failure blocked upload",
                level: .error,
                data: [
                    "recordingId": recordingId ?? "unknown",
                    "audioDurationSeconds": audioDuration ?? 0,
                    "audioBytes": pcmBytesWritten,
                ]
            )
            audioLog.error(
                "Skipping finalized audio upload after write failure durationSeconds=\(audioDuration ?? 0, privacy: .public) bytes=\(pcmBytesWritten, privacy: .public)"
            )
            return nil
        }
        if RecordingAudioUploadPolicy.canUploadFinalizedAudio(
            durationSeconds: audioDuration,
            pcmBytesWritten: pcmBytesWritten
        ) {
            return fileWriter.fileURL
        }

        if let recordingId {
            discardLocalAudioFileForTranscriptOnlySync(
                recordingId: recordingId,
                reason: "below_upload_minimum"
            )
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
        audioLog.warning(
            "Skipping finalized audio upload durationSeconds=\(audioDuration ?? 0, privacy: .public) bytes=\(pcmBytesWritten, privacy: .public)"
        )
        return nil
    }

    private func discardLocalAudioFileForTranscriptOnlySync(recordingId: String, reason: String) {
        do {
            try RecordingBackupStore.discardAudioFile(recordingId: recordingId)
        } catch {
            SentryHelper.captureError(
                error,
                extras: [
                    "action": "discardLocalAudioFileForTranscriptOnlySync",
                    "recordingId": recordingId,
                    "reason": reason,
                ]
            )
            audioLog.error("Failed to discard local audio file for transcript-only sync")
        }
    }

    private func finalizeRecordingAudioForPersistence(
        _ fileWriter: AudioFileWriter?,
        recordingId: String?
    ) -> Bool {
        guard let fileWriter else { return false }
        do {
            try fileWriter.finalize()
            return true
        } catch {
            SentryHelper.captureError(
                error,
                extras: [
                    "action": "finalizeRecordingAudio",
                    "context": "recording.audio.finalize_failed",
                    "recordingId": recordingId ?? "unknown",
                ]
            )
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "recording.audio.finalize_failed",
                level: .error,
                data: [
                    "recordingId": recordingId ?? "unknown",
                    "audioBytes": fileWriter.totalBytesWritten,
                ]
            )
            audioLog.error("Local audio finalization failed recordingId=\(recordingId ?? "unknown", privacy: .public)")

            do {
                try AudioFileWriter.repairWAVHeaderSizes(fileURL: fileWriter.fileURL)
                SentryHelper.addBreadcrumb(
                    category: "recording",
                    message: "recording.audio.finalize_repaired",
                    level: .warning,
                    data: [
                        "recordingId": recordingId ?? "unknown",
                        "audioBytes": fileWriter.totalBytesWritten,
                    ]
                )
                return true
            } catch {
                SentryHelper.captureError(
                    error,
                    extras: [
                        "action": "repairFinalizedRecordingAudio",
                        "context": "recording.audio.repair_after_finalize_failed",
                        "recordingId": recordingId ?? "unknown",
                    ]
                )
                SentryHelper.addBreadcrumb(
                    category: "recording",
                    message: "recording.audio.repair_after_finalize_failed",
                    level: .error,
                    data: [
                        "recordingId": recordingId ?? "unknown",
                        "audioBytes": fileWriter.totalBytesWritten,
                    ]
                )
                if let recordingId {
                    do {
                        try RecordingBackupStore.discardAudioFile(recordingId: recordingId)
                    } catch {
                        SentryHelper.captureError(
                            error,
                            extras: ["action": "discardUnfinalizedRecordingAudio", "recordingId": recordingId]
                        )
                    }
                }
                return false
            }
        }
    }

    private func saveTranscriptBackup(
        recordingId: String,
        segments: [LiveTranscriptSegment],
        durationSeconds: TimeInterval? = nil
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
            durationSeconds: durationSeconds ?? duration,
            transcript: transcript.isEmpty ? nil : transcript,
            segments: segments
        )
    }

    private func persistRecordingCloudFirst(
        recordingId: String,
        client: APIClient?,
        segments: [LiveTranscriptSegment],
        durationSeconds: Int,
        audioFileURL: URL?,
        directSaveNotice: String?,
        recoveredTranscriptNotice: String?
    ) async -> RecordingPersistenceResult {
        guard let client else {
            let technicalReason = "Recording client unavailable."
            return await saveLocalBackupForRetry(
                recordingId: recordingId,
                segments: segments,
                client: nil,
                durationSeconds: TimeInterval(durationSeconds),
                technicalReason: technicalReason
            ) ? .localBackup : .failed(technicalReason)
        }

        audioLog.info("Persisting transcript segments count=\(segments.count, privacy: .public) recordingId=\(recordingId, privacy: .public)")

        let shouldUploadAudio = audioFileURL.map { FileManager.default.fileExists(atPath: $0.path) } == true

        if shouldUploadAudio, let audioFileURL {
            let clientDurationSeconds = durationSeconds > 0 ? durationSeconds : nil
            let clientFileSizeBytes = (try? audioFileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize)
                .map(Int64.init)
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: "uploading finalized audio for transcription",
                data: [
                    "recordingId": recordingId,
                    "durationSeconds": durationSeconds,
                    "fileSizeBytes": clientFileSizeBytes ?? 0,
                ]
            )

            do {
                let detail = try await client.uploadAudio(
                    recordingId: recordingId,
                    fileURL: audioFileURL,
                    clientDurationSeconds: clientDurationSeconds,
                    clientFileSizeBytes: clientFileSizeBytes
                )
                guard detail.status != .failed else {
                    let technicalReason = UserFacingErrorFormatter.displayMessage(
                        detail.failureMessage,
                        fallback: "Recorded audio was uploaded, but processing failed.",
                        context: .recording
                    )
                    if !RecordingAudioFailurePolicy.isRetryableServerFailureCode(detail.failureCode) {
                        return await saveLocalBackupForPermanentAudioFailure(
                            recordingId: recordingId,
                            segments: segments,
                            durationSeconds: TimeInterval(durationSeconds),
                            technicalReason: technicalReason,
                            failureCode: detail.failureCode
                        ) ? .localPermanentBackup(technicalReason) : .failed(technicalReason)
                    }
                    return await saveLocalBackupForRetry(
                        recordingId: recordingId,
                        segments: segments,
                        client: client,
                        durationSeconds: TimeInterval(durationSeconds),
                        technicalReason: technicalReason
                    ) ? .localBackup : .failed(technicalReason)
                }

                guard detail.status == .ready else {
                    return await retainLocalBackupWhileServerProcessesAudio(
                        recordingId: recordingId,
                        segments: segments,
                        client: client,
                        durationSeconds: TimeInterval(durationSeconds),
                        status: detail.status
                    )
                }

                return .remoteSaved(
                    notice: directSaveNotice,
                    breadcrumbMessage: "audio uploaded for transcription"
                )
            } catch {
                SentryHelper.captureError(
                    error,
                    extras: ["action": "uploadRecordedAudioFallback", "recordingId": recordingId]
                )
                audioLog.warning("Audio upload fallback failed recordingId=\(recordingId, privacy: .public)")

                let technicalReason = error.userFacingMessage(context: .recording)
                return await saveLocalBackupForRetry(
                    recordingId: recordingId,
                    segments: segments,
                    client: client,
                    durationSeconds: TimeInterval(durationSeconds),
                    technicalReason: technicalReason
                ) ? .localBackup : .failed(technicalReason)
            }
        }

        do {
            let detail = try await client.saveLiveTranscript(
                recordingId: recordingId,
                segments: segments,
                durationSeconds: durationSeconds
            )
            guard detail.status != .failed else {
                let technicalReason = UserFacingErrorFormatter.displayMessage(
                    detail.failureMessage,
                    fallback: "Transcript was saved, but processing failed.",
                    context: .recording
                )
                return await saveLocalBackupForRetry(
                    recordingId: recordingId,
                    segments: segments,
                    client: client,
                    durationSeconds: TimeInterval(durationSeconds),
                    technicalReason: technicalReason
                ) ? .localBackup : .failed(technicalReason)
            }

            return .remoteSaved(notice: directSaveNotice, breadcrumbMessage: "transcript saved")
        } catch {
            SentryHelper.captureError(error, extras: ["action": "saveTranscript", "recordingId": recordingId])
            audioLog.warning("Transcript save failed recordingId=\(recordingId, privacy: .public)")

            let technicalReason = error.userFacingMessage(context: .recording)
            return await saveLocalBackupForRetry(
                recordingId: recordingId,
                segments: segments,
                client: client,
                durationSeconds: TimeInterval(durationSeconds),
                technicalReason: technicalReason
            ) ? .localBackup : .failed(technicalReason)
        }
    }

    private func persistRecordingForBackgroundSync(
        recordingId: String,
        client: APIClient?,
        segments: [LiveTranscriptSegment],
        durationSeconds: Int,
        audioFileURL: URL?
    ) async -> RecordingPersistenceResult {
        let hasAudioFile = audioFileURL.map { FileManager.default.fileExists(atPath: $0.path) } == true
        let audioBytes = audioFileURL.flatMap {
            try? $0.resourceValues(forKeys: [.fileSizeKey]).fileSize
        } ?? 0

        do {
            _ = try saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments,
                durationSeconds: TimeInterval(durationSeconds)
            )
        } catch {
            SentryHelper.captureError(
                error,
                extras: [
                    "action": "saveRecordingForBackgroundSync",
                    "recordingId": recordingId,
                    "hasAudioFile": hasAudioFile,
                ]
            )
            return .failed(error.userFacingMessage(context: .recording))
        }

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording queued for background sync",
            data: [
                "recordingId": recordingId,
                "segments": segments.count,
                "durationSeconds": durationSeconds,
                "hasAudioFile": hasAudioFile,
                "audioBytes": audioBytes,
            ]
        )

        if let client {
            await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        }

        return .localBackup
    }

    private func retainLocalBackupWhileServerProcessesAudio(
        recordingId: String,
        segments: [LiveTranscriptSegment],
        client: APIClient,
        durationSeconds: TimeInterval,
        status: RecordingStatus
    ) async -> RecordingPersistenceResult {
        do {
            _ = try saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments,
                durationSeconds: durationSeconds
            )
            try RecordingBackupStore.markServerProcessing(recordingId: recordingId)
        } catch {
            SentryHelper.captureError(
                error,
                extras: ["action": "retainAudioBackupWhileProcessing", "recordingId": recordingId]
            )
            return .failed(error.userFacingMessage(context: .recording))
        }

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "audio upload accepted; local backup retained",
            data: ["recordingId": recordingId, "status": status.rawValue]
        )
        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        return .localBackup
    }

    private func saveLocalBackupForRetry(
        recordingId: String,
        segments: [LiveTranscriptSegment],
        client: APIClient?,
        durationSeconds: TimeInterval? = nil,
        technicalReason: String
    ) async -> Bool {
        do {
            _ = try saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments,
                durationSeconds: durationSeconds
            )
        } catch {
            SentryHelper.captureError(
                error,
                extras: ["action": "saveLocalBackupForRetry", "recordingId": recordingId]
            )
            audioLog.error("Failed to save local recovery backup recordingId=\(recordingId, privacy: .public)")
            return false
        }

        do {
            _ = try RecordingBackupStore.recordSaveFailure(
                recordingId: recordingId,
                message: technicalReason
            )
        } catch {
            SentryHelper.captureError(
                error,
                extras: ["action": "recordLocalRecoveryReason", "recordingId": recordingId]
            )
            audioLog.error("Failed to record local recovery reason recordingId=\(recordingId, privacy: .public)")
        }

        reportLocalRecoveryFallback(
            recordingId: recordingId,
            segmentsCount: segments.count,
            technicalReason: technicalReason
        )

        if let client {
            await PendingRecordingSyncCoordinator.shared.scheduleSync(using: client)
        }

        return true
    }

    private func saveLocalBackupForPermanentAudioFailure(
        recordingId: String,
        segments: [LiveTranscriptSegment],
        durationSeconds: TimeInterval,
        technicalReason: String,
        failureCode: String?
    ) async -> Bool {
        do {
            _ = try saveTranscriptBackup(
                recordingId: recordingId,
                segments: segments,
                durationSeconds: durationSeconds
            )
        } catch {
            SentryHelper.captureError(
                error,
                extras: ["action": "saveLocalBackupForPermanentAudioFailure", "recordingId": recordingId]
            )
            audioLog.error("Failed to save permanent local recovery backup recordingId=\(recordingId, privacy: .public)")
            return false
        }

        do {
            _ = try RecordingBackupStore.recordSaveFailure(
                recordingId: recordingId,
                message: technicalReason
            )
            try RecordingBackupStore.markPermanentFailure(
                recordingId: recordingId,
                failureCode: failureCode
            )
        } catch {
            SentryHelper.captureError(
                error,
                extras: ["action": "recordPermanentAudioFailure", "recordingId": recordingId]
            )
            audioLog.error("Failed to mark permanent local recovery backup recordingId=\(recordingId, privacy: .public)")
            return false
        }

        SentryHelper.addBreadcrumb(
            category: "recording",
            message: "recording saved after terminal audio failure",
            level: .warning,
            data: [
                "recordingId": recordingId,
                "segments": segments.count,
                "reason": technicalReason,
                "failureCode": failureCode ?? "permanent_failure",
            ]
        )
        return true
    }

    private func applyRecordingPersistenceResult(
        _ result: RecordingPersistenceResult,
        recordingId: String,
        segmentsCount: Int
    ) async -> Bool {
        switch result {
        case .remoteSaved(let notice, let breadcrumbMessage):
            try? RecordingBackupStore.removeRecording(recordingId: recordingId)
            SentryHelper.addBreadcrumb(
                category: "recording",
                message: breadcrumbMessage,
                data: ["recordingId": recordingId, "segments": segmentsCount]
            )
            if let notice {
                postRecoveryNotice(notice)
            }
            error = nil
            return true
        case .localBackup:
            error = nil
            return false
        case .localPermanentBackup(let message):
            error = message
            return false
        case .failed(let message):
            error = message
            return false
        }
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
        RealtimeTranscriptSegmentFinalizer.finalizedSegments(
            providerSegments: segments,
            liveTranscript: currentTranscript,
            liveSpeaker: interimSpeaker,
            durationSeconds: duration,
            didFinalize: didFinalize
        )
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

    @available(macOS 14.2, *)
    private func startSystemAudioMonitor(for dualCapture: DualAudioCapture) {
        systemAudioMonitorTask?.cancel()
        systemAudioMonitorTask = Task { [weak self] in
            // Poll once a second so the warning surfaces ~immediately after
            // DualAudioCapture's 3-second early-stall detector fires. The
            // previous 5-second cadence added another ~5s of "Listening..." UI
            // with no feedback, which is exactly the experience users were
            // reporting.
            var warnedOnce = false
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { break }

                let stalled = dualCapture.systemAudioStalled
                let receivedAny = dualCapture.systemAudioReceivedAny

                await MainActor.run {
                    guard let self, self.phase == .recording else { return }
                    if SystemAudioWarningPolicy.shouldShowCaptureWarning(
                        systemAudioStalled: stalled,
                        systemAudioReceivedAny: receivedAny
                    ) {
                        self.systemAudioWarning = self.systemAudioUnavailableWarningText
                        if !warnedOnce {
                            warnedOnce = true
                            SentryHelper.addBreadcrumb(
                                category: "recording",
                                message: "system audio stalled",
                                level: .warning,
                                data: [
                                    "stalled": stalled,
                                    "receivedAny": receivedAny,
                                    "recordingId": self.currentRecordingId ?? "unknown",
                                    "recordingType": self.recordingType.rawValue,
                                ]
                            )
                        }
                    } else {
                        self.systemAudioWarning = nil
                    }
                }
            }
        }
    }

    private func resetAfterStartFailure() async {
        let recordingId = currentRecordingId
        let client = apiClient
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
        try? audioFileWriter?.finalize()
        audioFileWriter = nil

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
        recordingInputSource = SystemAudioGate.isSupported ? .dual : .microphone
        endRecordingActivity(reason: "start-failure")
        setPhase(.idle)
    }

    private func setPhase(_ newPhase: MacRecordingPhase) {
        if newPhase != .recording {
            isPaused = false
        }
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
            let committed: String
            if segment.isFinal {
                committed = appendCommittedTranscriptLine(segment)
                interimText = ""
                interimSpeaker = nil
            } else {
                interimText = segment.text
                interimSpeaker = segment.speaker
                if !committedTranscriptHasSpeakerLabels, Self.hasSpeakerLabel(segment.speaker) {
                    committedTranscriptHasSpeakerLabels = true
                    committed = buildCommittedTranscriptText()
                } else {
                    committed = committedTranscript
                }
            }

            // Interim events arrive several times per second. Keep committed
            // transcript construction incremental so those ticks only update
            // the rolling interim tail instead of joining every previous final
            // line again.
            let interim = buildInterimTranscriptText()
            setLiveTranscript(committed: committed, interim: interim)
        case .transcriptReplacement(let segment):
            let committed = replaceLastCommittedTranscriptLine(segment)
            interimText = ""
            interimSpeaker = nil
            setLiveTranscript(committed: committed, interim: buildInterimTranscriptText())
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
        if let error {
            SentryHelper.captureError(
                error,
                extras: [
                    "context": "recording.live_transcription.disabled",
                    "recordingId": currentRecordingId ?? "unknown",
                    "reason": reason,
                    "durationSeconds": duration,
                    "errorType": String(describing: type(of: error)),
                ]
            )
        }
        await webSocketManager?.stopRealtimeStreamingForLocalRecording(reason: reason)
    }

    /// Combine already-built committed + interim text for the full live
    /// transcript. Takes the pieces as parameters so callers can build each once.
    private func combinedTranscript(committed: String, interim: String) -> String {
        if interim.isEmpty { return committed }
        if committed.isEmpty { return interim }
        // Speaker mode uses paragraph break, single-channel uses space.
        return shouldShowSpeakers
            ? committed + "\n\n" + interim
            : committed + " " + interim
    }

    private static let liveTranscriptChunkLimit = 1_800

    private static func liveTranscriptDisplayChunks(from transcript: String) -> [LiveTranscriptDisplayChunk] {
        let normalized = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return [] }

        var chunks: [LiveTranscriptDisplayChunk] = []
        var chunkId = 0
        var start = normalized.startIndex

        while start < normalized.endIndex {
            let hardEnd = normalized.index(
                start,
                offsetBy: liveTranscriptChunkLimit,
                limitedBy: normalized.endIndex
            ) ?? normalized.endIndex
            var end = hardEnd

            if hardEnd < normalized.endIndex {
                let slice = normalized[start..<hardEnd]
                if let newline = slice.lastIndex(of: "\n"),
                   normalized.distance(from: start, to: newline) > liveTranscriptChunkLimit / 2 {
                    end = normalized.index(after: newline)
                } else if let space = slice.lastIndex(of: " "),
                          normalized.distance(from: start, to: space) > liveTranscriptChunkLimit / 2 {
                    end = normalized.index(after: space)
                }
            }

            let text = String(normalized[start..<end])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                chunks.append(LiveTranscriptDisplayChunk(id: chunkId, text: text))
                chunkId += 1
            }

            start = end
        }

        return chunks
    }

    private func setLiveTranscript(committed: String, interim: String) {
        guard committedTranscript != committed || interimTranscript != interim else { return }
        objectWillChange.send()
        if committedTranscript != committed {
            committedTranscriptChunks = Self.liveTranscriptDisplayChunks(from: committed)
            committedTranscriptRevision += 1
        }
        if interimTranscript != interim {
            interimTranscriptRevision += 1
        }
        committedTranscript = committed
        interimTranscript = interim
    }

    /// True when realtime metadata carries any non-empty speaker labels.
    private var shouldShowSpeakers: Bool {
        committedTranscriptHasSpeakerLabels || Self.hasSpeakerLabel(interimSpeaker)
    }

    private func appendCommittedTranscriptLine(_ segment: LiveTranscriptSegment) -> String {
        let previousUsesSpeakerLabels = committedTranscriptHasSpeakerLabels
        let previousSpeaker = committedLines.last?.speaker
        committedLines.append((speaker: segment.speaker, text: segment.text))

        if Self.hasSpeakerLabel(segment.speaker) {
            committedTranscriptHasSpeakerLabels = true
        }

        if !previousUsesSpeakerLabels, committedTranscriptHasSpeakerLabels {
            return buildCommittedTranscriptText()
        }

        guard committedTranscriptHasSpeakerLabels else {
            if committedTranscript.isEmpty {
                return segment.text
            }
            return committedTranscript + " " + segment.text
        }

        if committedTranscript.isEmpty {
            return "\(displaySpeaker(segment.speaker ?? "Speaker")): \(segment.text)"
        }
        if previousSpeaker == segment.speaker {
            return committedTranscript + " " + segment.text
        }
        return committedTranscript + "\n\n\(displaySpeaker(segment.speaker ?? "Speaker")): \(segment.text)"
    }

    private func replaceLastCommittedTranscriptLine(_ segment: LiveTranscriptSegment) -> String {
        if committedLines.isEmpty {
            return appendCommittedTranscriptLine(segment)
        }
        committedLines[committedLines.count - 1] = (speaker: segment.speaker, text: segment.text)
        committedTranscriptHasSpeakerLabels = committedLines.contains { line in
            Self.hasSpeakerLabel(line.speaker)
        }
        return buildCommittedTranscriptText()
    }

    private static func hasSpeakerLabel(_ speaker: String?) -> Bool {
        !(speaker?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
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

    /// Just the trailing interim text, with speaker prefix when relevant.
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
    /// label ("Говорящий 1" / "Speaker 1") for the live transcript (129).
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

    private func finishStreaming(_ manager: WebSocketManager?) async -> Bool {
        guard let manager else { return true }
        do {
            return try await manager.finishStreaming(timeout: .seconds(5))
        } catch {
            SentryHelper.addBreadcrumb(
                category: "recording.provider",
                message: "recording.provider.close_failed",
                level: .error,
                data: ["stage": "recording_finalize"]
            )
            SentryHelper.captureError(
                error,
                extras: [
                    "context": "recording.provider.close_failed",
                    "stage": "recording_finalize",
                ]
            )
            audioLog.error("Failed to finalize realtime transcription stream")
            return false
        }
    }

    private func makeAudioCapture(
        for inputSource: MacRecordingInputSource
    ) throws -> any AudioCaptureProtocol {
        switch inputSource {
        case .dual:
            guard #available(macOS 14.2, *) else {
                throw NSError(
                    domain: "MacRecordingViewModel",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "System audio capture requires macOS 14.2 or newer."]
                )
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
                _ = systemError
                return RecordingCopy.systemAudioCaptureUnavailableMessage(language: LanguageManager.shared.current)
            }
            if #available(macOS 14.2, *),
               let dualError = error as? DualAudioCaptureError {
                _ = dualError
                return RecordingCopy.systemAudioCaptureUnavailableMessage(language: LanguageManager.shared.current)
            }

            switch error {
            case AudioCaptureError.invalidFormat:
                return t(
                    "System audio capture returned an unsupported format.",
                    "Захват звука Mac вернул неподдерживаемый формат."
                )
            default:
                break
            }
        }

        return error.userFacingMessage(context: .recording)
    }

    /// Mirrors `recordingErrorMessage`'s classification so the alert can offer
    /// the right settings deep-link in any UI language.
    private func recordingErrorKind(
        for error: Error,
        inputSource: MacRecordingInputSource
    ) -> RecordingErrorKind {
        guard inputSource == .systemAudio || inputSource == .dual else { return .general }
        if #available(macOS 14.2, *) {
            if error is SystemAudioCaptureError || error is DualAudioCaptureError {
                return .systemAudio
            }
        }
        if case AudioCaptureError.invalidFormat = error {
            return .systemAudio
        }
        let nsError = error as NSError
        if nsError.domain == "MacRecordingViewModel", nsError.code == 1 {
            // makeAudioCapture's pre-14.2 guard.
            return .systemAudio
        }
        return .general
    }

    private func localTranscriptRecoveryMessage(segmentsCount: Int) -> String {
        if segmentsCount > 0 {
            return t(
                "Connection was interrupted, but your recording is safe on this Mac. We'll keep syncing it automatically in the background.",
                "Соединение прервалось, но запись сохранена на этом Mac. Мы продолжим автоматически синхронизировать ее в фоне."
            )
        }
        return t(
            "Connection was interrupted before speech could sync, but your recording is safe on this Mac.",
            "Соединение прервалось до синхронизации речи, но запись сохранена на этом Mac."
        )
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

    private func postRecoveryNotice(_ message: String) {
        NotificationCenter.default.post(
            name: .pendingRecordingRecoveryNotice,
            object: nil,
            userInfo: ["message": message]
        )
    }

    private var systemAudioUnavailableWarningText: String {
        t(
            "System audio is not reaching WaiComputer. Microphone audio is still being recorded.",
            "Звук Mac не доходит до WaiComputer. Микрофон продолжает записываться."
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
        systemAudioMonitorTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
        cleanupTask?.cancel()
    }
}

struct LiveTranscriptDisplayChunk: Identifiable, Equatable {
    let id: Int
    let text: String
}

private extension AVAuthorizationStatus {
    var statusName: String {
        switch self {
        case .notDetermined: return "notDetermined"
        case .restricted: return "restricted"
        case .denied: return "denied"
        case .authorized: return "authorized"
        @unknown default: return "unknown"
        }
    }
}
