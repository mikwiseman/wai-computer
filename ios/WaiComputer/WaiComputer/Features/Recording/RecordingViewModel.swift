import Foundation
import AVFoundation
import Combine
import WaiComputerKit

@MainActor
class RecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var recordingType: RecordingType = .note
    @Published var duration: TimeInterval = 0
    @Published var currentTranscript = ""
    @Published var currentRecordingId: String?

    private var recording: Recording?
    private var audioCapture: MicrophoneCapture?
    private var audioEncoder: AudioEncoder?
    private var webSocketManager: WebSocketManager?
    private var timer: Timer?
    private var audioTask: Task<Void, Never>?
    private var transcriptTask: Task<Void, Never>?

    var formattedDuration: String {
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    var statusText: String {
        if isLoading {
            return "Connecting..."
        } else if isRecording {
            return "Recording in progress"
        } else {
            return "Tap to start recording"
        }
    }

    func startRecording(apiClient: APIClient, webSocketManager: WebSocketManager) async {
        isLoading = true
        error = nil
        currentTranscript = ""

        do {
            // Request microphone permission
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                error = "Microphone permission denied"
                isLoading = false
                return
            }

            // Create recording on server
            recording = try await apiClient.createRecording(
                type: recordingType,
                language: "en"
            )

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                isLoading = false
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

            // Initialize audio capture
            audioCapture = MicrophoneCapture()
            audioEncoder = AudioEncoder()

            // Start audio capture
            try await audioCapture?.startRecording()

            // Start timer with weak self to avoid retain cycle
            duration = 0
            timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.duration += 1
                }
            }

            // Start sending audio with weak self
            audioTask = Task { [weak self] in
                guard let self = self,
                      let audioCapture = self.audioCapture,
                      let encoder = self.audioEncoder,
                      let ws = self.webSocketManager else { return }

                for await buffer in audioCapture.audioBuffers {
                    if let data = encoder.encode(buffer) {
                        do {
                            try await ws.sendAudio(data: data)
                        } catch {
                            // Log error but continue - don't break the loop
                            print("Failed to send audio: \(error)")
                        }
                    }
                }
            }

            isRecording = true
            isLoading = false

        } catch {
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    func stopRecording() async {
        // Stop timer
        timer?.invalidate()
        timer = nil

        // Stop audio capture first so no more audio is generated
        await audioCapture?.stopRecording()
        audioCapture = nil

        // Cancel the audio sending task
        audioTask?.cancel()
        audioTask = nil

        // Send end signal to tell the server we're done
        do {
            try await webSocketManager?.sendEnd()
        } catch {
            print("Failed to send end signal: \(error)")
        }

        // Wait briefly for final transcripts from the server
        try? await Task.sleep(for: .seconds(2))

        // Now cancel transcript task and disconnect
        transcriptTask?.cancel()
        transcriptTask = nil

        // Disconnect WebSocket
        await webSocketManager?.disconnect()
        webSocketManager = nil

        isRecording = false
        duration = 0
        // NOTE: Do NOT clear currentTranscript or currentRecordingId here.
        // The transcript should remain visible after stopping.
    }

    /// Reset transcript and recording state.
    /// Call this when navigating away from the recording or starting a new one.
    func resetState() {
        currentTranscript = ""
        currentRecordingId = nil
        duration = 0
    }

    private func handleWebSocketEvent(_ event: WebSocketEvent) async {
        switch event {
        case .connected:
            break
        case .transcript(let message):
            if message.isFinal {
                if !currentTranscript.isEmpty {
                    currentTranscript += " "
                }
                currentTranscript += message.text
            }
        case .status(let status):
            if status.status == "error" {
                error = status.message
            }
        case .disconnected(let err):
            if let err = err {
                error = err.localizedDescription
            }
        }
    }

    deinit {
        timer?.invalidate()
        audioTask?.cancel()
        transcriptTask?.cancel()
    }
}
