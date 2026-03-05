import Foundation
import AVFoundation
import os
import WaiComputerKit

private let audioLog = Logger(subsystem: "com.waicomputer.app", category: "audio")

@MainActor
class MacRecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var recordingType: RecordingType = .meeting
    @Published var duration: TimeInterval = 0
    @Published var currentTranscript = ""
    @Published var currentRecordingId: String?
    @Published var isServerComplete = false

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

    func startRecording(apiClient: APIClient, webSocketManager: WebSocketManager, type: RecordingType) async {
        // Wait for any in-progress cleanup to finish before starting a new recording
        if isCleaningUp {
            NSLog("[Recording] Waiting for previous cleanup to complete...")
            await cleanupTask?.value
        }

        // If somehow still recording, stop first
        if isRecording {
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

        // Set isRecording IMMEDIATELY so the UI (timer, header, transcript area)
        // is live while async setup (API call, WebSocket, audio) completes.
        isRecording = true
        isLoading = false

        do {
            // Request microphone permission
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                error = "Microphone permission denied"
                isRecording = false
                return
            }

            // Start timer right away so the user sees it ticking
            timerTask = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(1))
                    guard !Task.isCancelled else { break }
                    self?.duration += 1
                }
            }

            // Create recording on server
            recording = try await apiClient.createRecording(type: recordingType, language: "en")

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                timerTask?.cancel()
                timerTask = nil
                isRecording = false
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

        } catch {
            self.error = error.localizedDescription
            timerTask?.cancel()
            timerTask = nil
            isRecording = false
        }
    }

    func stopRecording() async {
        guard isRecording else { return }

        // Stop timer
        timerTask?.cancel()
        timerTask = nil

        // Stop audio capture first so no more audio is generated
        await audioCapture?.stopRecording()
        audioCapture = nil

        // Cancel the audio sending task
        audioTask?.cancel()
        audioTask = nil

        // Update UI IMMEDIATELY — no waiting
        isRecording = false
        duration = 0
        isCleaningUp = true

        // Capture references for background cleanup
        let ws = webSocketManager
        let tTask = transcriptTask
        webSocketManager = nil
        transcriptTask = nil

        // Track the cleanup task so startRecording can await it
        cleanupTask = Task { [weak self] in
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
                self?.isCleaningUp = false
            }
        }
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
