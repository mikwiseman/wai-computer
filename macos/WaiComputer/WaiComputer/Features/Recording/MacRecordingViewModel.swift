import Foundation
import AVFoundation
import os
import WaiComputerKit

private let audioLog = Logger(subsystem: "com.waicomputer.app", category: "audio")

enum MacRecordingInputSource: String, CaseIterable, Equatable {
    case microphone
    case systemAudio = "system_audio"

    var label: String {
        switch self {
        case .microphone:
            return "Microphone"
        case .systemAudio:
            return "System Audio"
        }
    }

    var systemImage: String {
        switch self {
        case .microphone:
            return "mic"
        case .systemAudio:
            return "speaker.wave.2"
        }
    }

    var preparingText: String {
        switch self {
        case .microphone:
            return "Preparing microphone and connection..."
        case .systemAudio:
            return "Preparing system audio and connection..."
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
    @Published var recordingInputSource: MacRecordingInputSource = .microphone
    @Published var duration: TimeInterval = 0
    @Published var currentTranscript = ""
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false
    @Published private(set) var phase: MacRecordingPhase = .idle

    /// Committed (final) transcript text — only final Deepgram results
    private var committedTranscript = ""
    /// Current interim text (replaced on each new interim result)
    private var interimText = ""

    /// Guards against starting a new recording while cleanup is in progress
    private var isCleaningUp = false
    private let testingMode: MacTestingMode

    private var recording: Recording?
    private var audioCapture: (any AudioCaptureProtocol)?
    private var audioEncoder: AudioEncoder?
    private var webSocketManager: WebSocketManager?
    private var timerTask: Task<Void, Never>?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?
    private var cleanupTask: Task<Void, Never>?

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
            return "Finalizing recording"
        }
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
            return "Finalizing transcript..."
        }
    }

    init(testingMode: MacTestingMode = .current) {
        self.testingMode = testingMode
    }

    func startRecording(
        apiClient: APIClient,
        webSocketManager: WebSocketManager,
        type: RecordingType,
        inputSource: MacRecordingInputSource = .microphone
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
        committedTranscript = ""
        interimText = ""
        isServerComplete = false
        currentRecordingId = nil
        recordingType = type
        recordingInputSource = inputSource
        duration = 0
        recording = nil
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
            if inputSource == .microphone {
                let granted = await AVAudioApplication.requestRecordPermission()
                guard granted else {
                    error = "Microphone permission denied"
                    await resetAfterStartFailure()
                    return
                }
            }

            // Create recording on server — use language from Settings
            let language = UserDefaults.standard.string(forKey: "transcriptionLanguage") ?? "multi"
            recording = try await apiClient.createRecording(type: recordingType, language: language)

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                await resetAfterStartFailure()
                return
            }

            currentRecordingId = recordingId

            // Set up WebSocket and event stream BEFORE connecting
            // to ensure no events are missed
            self.webSocketManager = webSocketManager
            let eventStream = await webSocketManager.events

            // Start receiving transcripts BEFORE connecting
            // so the listener is ready when events start flowing
            transcriptTask = Task { [weak self] in
                guard let self = self else { return }

                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
                }
            }

            // Now connect WebSocket
            try await webSocketManager.connect(recordingId: recordingId)

            // Initialize audio capture and encoder
            let capture = try makeAudioCapture(for: inputSource)
            let encoder = AudioEncoder()
            audioCapture = capture
            audioEncoder = encoder
            let ws = webSocketManager

            // Start the audio-sending loop BEFORE starting the engine so
            // the `for await` consumer is ready when the first buffer arrives.
            // Use Task.detached to avoid inheriting @MainActor — the audio tap
            // fires on an audio thread, and the WebSocket send should not
            // compete with UI work on the main actor.
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
                            if bufferCount <= 5 {
                                NSLog("[Recording] Audio sent successfully!")
                            }
                        } catch {
                            NSLog("[Recording] Failed to send audio: %@", "\(error)")
                            await self.failActiveRecording(with: error.localizedDescription)
                            return
                        }
                    } else {
                        NSLog("[Recording] Encoder returned nil for buffer #%d", bufferCount)
                    }
                }
                NSLog("[Recording] Audio task loop ended (stream finished)")
            }

            // Now start the engine — the consumer loop above is already waiting
            NSLog("[Recording] Starting audio engine...")
            try await capture.startRecording()
            NSLog("[Recording] Audio engine started successfully")

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

        // Stop audio capture first so no more audio is generated
        await audioCapture?.stopRecording()
        audioCapture = nil

        // Cancel the audio sending task
        audioTask?.cancel()
        audioTask = nil

        // Keep the live view mounted while the server flushes final transcript/audio.
        isCleaningUp = true

        // Capture references for background cleanup
        let ws = webSocketManager
        let tTask = transcriptTask
        webSocketManager = nil
        transcriptTask = nil

        // Track the cleanup task so startRecording can await it
        let task = Task { [weak self] in
            // Send end signal to tell the server we're done
            do {
                try await ws?.sendEnd()
            } catch {
                NSLog("[Recording] Failed to send end signal: \(error)")
            }

            // Brief wait for final transcripts (server sends Close to Deepgram)
            let deadline = Date().addingTimeInterval(3.0)
            while await self?.isServerComplete != true && Date() < deadline {
                try? await Task.sleep(for: .milliseconds(200))
            }

            // Clean up
            tTask?.cancel()
            await ws?.disconnect()

            if await self?.isServerComplete == true {
                NSLog("[Recording] Server confirmed complete")
            } else {
                NSLog("[Recording] Server complete not received (timed out)")
            }

            // Mark cleanup as done (on MainActor since self is @MainActor)
            await MainActor.run {
                self?.recording = nil
                self?.audioEncoder = nil
                self?.setPhase(.idle)
                self?.isCleaningUp = false
                self?.cleanupTask = nil
            }
        }
        cleanupTask = task
        await task.value
    }

    /// Reset transcript and recording state.
    /// Call this when navigating away from the recording or starting a new one.
    func resetState() {
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        currentRecordingId = nil
        isServerComplete = false
        duration = 0
    }

    func clearError() {
        error = nil
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

        let ws = webSocketManager
        webSocketManager = nil
        await ws?.disconnect()

        recording = nil
        currentRecordingId = nil
        isServerComplete = false
        recordingInputSource = .microphone
        setPhase(.idle)
    }

    private func setPhase(_ newPhase: MacRecordingPhase) {
        phase = newPhase
        isRecording = newPhase == .recording
        isLoading = newPhase == .preparing
    }

    private func handleWebSocketEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            break
        case .transcript(let message):
            if message.isFinal {
                // Append final text to committed transcript
                if !committedTranscript.isEmpty {
                    committedTranscript += " "
                }
                committedTranscript += message.text
                // Clear interim since final replaces it
                interimText = ""
                currentTranscript = committedTranscript
            } else {
                // Show interim result for real-time feedback
                interimText = message.text
                if committedTranscript.isEmpty {
                    currentTranscript = interimText
                } else {
                    currentTranscript = committedTranscript + " " + interimText
                }
            }
        case .status(let status):
            if status.status == "error" {
                error = status.message
            } else if status.status == "complete" {
                isServerComplete = true
            }
        case .disconnected(let err):
            if let err = err, phase == .recording {
                await failActiveRecording(with: err.localizedDescription)
            } else if let err = err, phase != .finalizing, phase != .idle {
                error = err.localizedDescription
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

        let ws = webSocketManager
        webSocketManager = nil
        await ws?.disconnect()

        recording = nil
        isServerComplete = false
        isCleaningUp = false
        recordingInputSource = .microphone
        setPhase(.idle)
    }

    private func makeAudioCapture(
        for inputSource: MacRecordingInputSource
    ) throws -> any AudioCaptureProtocol {
        switch inputSource {
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
        if inputSource == .systemAudio {
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
