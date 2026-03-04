import Foundation
import AVFoundation
import WaiComputerKit

@MainActor
class MacRecordingViewModel: ObservableObject {
    @Published var isRecording = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var recordingType: RecordingType = .meeting
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

    func startRecording(apiClient: APIClient, webSocketManager: WebSocketManager, type: RecordingType) async {
        isLoading = true
        error = nil
        currentTranscript = ""
        recordingType = type

        do {
            // Request microphone permission
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                error = "Microphone permission denied"
                isLoading = false
                return
            }

            // Create recording on server
            recording = try await apiClient.createRecording(type: recordingType, language: "en")

            guard let recordingId = recording?.id else {
                error = "Failed to create recording"
                isLoading = false
                return
            }

            currentRecordingId = recordingId

            // Connect WebSocket
            self.webSocketManager = webSocketManager
            try await webSocketManager.connect(recordingId: recordingId)

            // Initialize audio capture
            audioCapture = MicrophoneCapture()
            audioEncoder = AudioEncoder()

            // Start audio capture
            try await audioCapture?.startRecording()

            // Start timer
            duration = 0
            timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.duration += 1
                }
            }

            // Start sending audio
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
                            print("Failed to send audio: \(error)")
                        }
                    }
                }
            }

            // Start receiving transcripts
            let eventStream = await webSocketManager.events
            transcriptTask = Task { [weak self] in
                guard let self = self else { return }

                for await event in eventStream {
                    await self.handleWebSocketEvent(event)
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
        timer?.invalidate()
        timer = nil

        await audioCapture?.stopRecording()
        audioCapture = nil

        do {
            try await webSocketManager?.sendEnd()
        } catch {
            print("Failed to send end signal: \(error)")
        }

        audioTask?.cancel()
        transcriptTask?.cancel()
        audioTask = nil
        transcriptTask = nil

        await webSocketManager?.disconnect()
        webSocketManager = nil

        isRecording = false
        duration = 0
        currentTranscript = ""
        currentRecordingId = nil
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
