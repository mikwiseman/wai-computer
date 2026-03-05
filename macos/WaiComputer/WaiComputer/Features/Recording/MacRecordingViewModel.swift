import Foundation
import AVFoundation
import os
import WaiComputerKit

private let audioLog = Logger(subsystem: "com.waicomputer.app", category: "audio")

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

    private var recording: Recording?
    private var audioCapture: MicrophoneCapture?
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
            return "Preparing microphone and connection..."
        case .recording:
            return "Listening..."
        case .finalizing:
            return "Finalizing transcript..."
        }
    }

    func startRecording(apiClient: APIClient, webSocketManager: WebSocketManager, type: RecordingType) async {
        // Wait for any in-progress cleanup to finish before starting a new recording
        if isCleaningUp {
            NSLog("[Recording] Waiting for previous cleanup to complete...")
            await cleanupTask?.value
        }

        // If somehow still recording, stop first
        if shouldPresentLiveView {
            NSLog("[Recording] Force-stopping previous recording before starting new one")
            await stopRecording()
            await cleanupTask?.value
        }

        isLoading = true
        error = nil
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        isServerComplete = false
        currentRecordingId = nil
        recordingType = type
        duration = 0
        recording = nil
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
            let capture = MicrophoneCapture()
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
            audioTask = Task.detached(priority: .userInitiated) {
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
                            await MainActor.run {
                                self.error = error.localizedDescription
                            }
                            break
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

        // Keep the live view mounted while the server flushes final transcript/audio.
        setPhase(.finalizing)
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
            if let err = err {
                error = err.localizedDescription
            }
        }
    }

    deinit {
        timerTask?.cancel()
        audioTask?.cancel()
        transcriptTask?.cancel()
        cleanupTask?.cancel()
    }
}
