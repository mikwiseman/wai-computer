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
    private var audioCapture: MicrophoneCapture?
    private var audioEncoder: AudioEncoder?
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
            return "Finalizing recording..."
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
            return "Preparing microphone and connection..."
        case .recording:
            return "Listening..."
        case .finalizing:
            return "Finalizing transcript..."
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

    func startRecording(apiClient: APIClient, webSocketManager: WebSocketManager) async {
        guard phase == .idle else { return }

        error = nil
        currentTranscript = ""
        committedTranscript = ""
        interimText = ""
        currentRecordingId = nil
        isServerComplete = false
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

            let capture = MicrophoneCapture()
            let encoder = AudioEncoder()
            audioCapture = capture
            audioEncoder = encoder
            let ws = webSocketManager

            audioTask = Task {
                for await buffer in capture.audioBuffers {
                    if let data = encoder.encode(buffer) {
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

        // Send end signal to tell the server we're done
        do {
            try await webSocketManager?.sendEnd()
        } catch {
            print("Failed to send end signal: \(error)")
        }

        let deadline = Date().addingTimeInterval(3.0)
        while !isServerComplete && Date() < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }

        // Now cancel transcript task and disconnect
        transcriptTask?.cancel()
        transcriptTask = nil

        // Disconnect WebSocket
        await webSocketManager?.disconnect()
        webSocketManager = nil

        recording = nil
        audioEncoder = nil
        setPhase(.idle)
        // NOTE: Do NOT clear currentTranscript or currentRecordingId here.
        // The transcript should remain visible after stopping.
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

    private func setPhase(_ newPhase: RecordingPhase) {
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
                if !committedTranscript.isEmpty {
                    committedTranscript += " "
                }
                committedTranscript += message.text
                interimText = ""
                currentTranscript = committedTranscript
            } else {
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
    }
}
