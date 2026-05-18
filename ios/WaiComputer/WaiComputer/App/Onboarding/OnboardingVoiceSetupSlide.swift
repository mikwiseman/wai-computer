import AVFoundation
import SwiftUI
import WaiComputerKit

/// iOS combined mic-test + voice-enrollment step (Wispr Flow pattern).
struct OnboardingVoiceSetupSlide: View {
    let isActive: Bool
    let onAdvance: () -> Void

    @EnvironmentObject var appState: AppState
    @StateObject private var recorder = VoiceEnrollmentRecorder()

    private static let promptText =
        "Hi, I'm setting up Wai Computer. It records meetings, calls, and ideas through my day so I don't have to remember them all. Wai listens, transcribes the people I talk to, and keeps the moments that matter."

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Spacer(minLength: Spacing.lg)

            Text("VOICE")
                .font(Typography.labelSmall)
                .tracking(1.6)
                .foregroundStyle(Palette.accent)

            Text("Teach Wai your voice")
                .font(Typography.displayMedium)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textPrimary)

            Text("Read the prompt for ~20 seconds. Wai will recognise you in future meetings automatically.")
                .font(Typography.bodyLarge)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textSecondary)
                .padding(.horizontal, Spacing.lg)

            promptCard

            recordButton

            ProgressView(value: recorder.progress)
                .progressViewStyle(.linear)
                .padding(.horizontal, Spacing.xl)

            Text(statusLabel)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)

            if let error = recorder.errorMessage {
                Text(error)
                    .font(Typography.caption)
                    .foregroundStyle(.red)
            }

            HStack {
                Button("Skip for now", action: skipAndAdvance)
                    .buttonStyle(WaiGhostButtonStyle())
                Spacer()
                if recorder.state == .recorded {
                    Button("Re-record", action: handleRecordTap)
                        .buttonStyle(WaiGhostButtonStyle())
                    Button("Use this take", action: submit)
                        .buttonStyle(WaiPrimaryButtonStyle())
                        .disabled(recorder.state == .uploading)
                }
            }
            .padding(.horizontal, Spacing.xl)

            Text("We store a 192-number signature, not your audio. The recording is deleted after the signature is created.")
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Spacing.xl)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.xl)
        .onChange(of: isActive) { _, active in
            if !active && recorder.state == .recording {
                recorder.cancel()
            }
        }
    }

    private var promptCard: some View {
        Text(Self.promptText)
            .font(Typography.reading)
            .lineSpacing(6)
            .multilineTextAlignment(.leading)
            .padding(Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Palette.surfaceSubtle)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14)
                            .strokeBorder(Palette.border, lineWidth: 1)
                    )
            )
    }

    private var recordButton: some View {
        Button(action: handleRecordTap) {
            ZStack {
                Circle()
                    .fill(recorder.state == .recording ? Color.red : Palette.accent)
                    .frame(width: 88, height: 88)
                Image(systemName: recorder.state == .recording ? "stop.fill" : "mic.fill")
                    .font(.system(size: 32, weight: .semibold))
                    .foregroundStyle(.white)
            }
        }
        .buttonStyle(.plain)
        .disabled(recorder.state == .uploading)
    }

    private func handleRecordTap() {
        if recorder.state == .recording {
            recorder.stop()
        } else {
            recorder.start()
        }
    }

    private func submit() {
        Task {
            guard let data = recorder.recordedData else { return }
            recorder.state = .uploading
            do {
                _ = try await appState.getAPIClient().enrollVoice(
                    audio: data,
                    filename: "enrollment.wav",
                    mimeType: "audio/wav",
                    displayName: nil,
                    personId: nil
                )
                recorder.reset()
                onAdvance()
            } catch {
                recorder.errorMessage = error.localizedDescription
                recorder.state = .recorded
            }
        }
    }

    private func skipAndAdvance() {
        recorder.cancel()
        onAdvance()
    }

    private var statusLabel: String {
        switch recorder.state {
        case .idle:
            return "Press the mic to start"
        case .recording:
            return "Recording… \(Int(recorder.elapsedSeconds))s / 20s"
        case .recorded:
            return "Recorded \(Int(recorder.elapsedSeconds))s. Re-record or submit."
        case .uploading:
            return "Uploading voice signature…"
        }
    }
}

@MainActor
final class VoiceEnrollmentRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    enum State {
        case idle
        case recording
        case recorded
        case uploading
    }

    @Published var state: State = .idle
    @Published var elapsedSeconds: Double = 0
    @Published var errorMessage: String?
    private(set) var recordedData: Data?

    private var recorder: AVAudioRecorder?
    private var fileURL: URL?
    private var timer: Timer?
    private let maxDurationSeconds: Double = 20.0

    var progress: Double {
        min(elapsedSeconds / maxDurationSeconds, 1.0)
    }

    func start() {
        cancelTimers()
        errorMessage = nil
        recordedData = nil

        do {
            try AVAudioSession.sharedInstance().setCategory(.record, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            errorMessage = "Audio session error: \(error.localizedDescription)"
            return
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-enroll-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        do {
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.delegate = self
            guard recorder.record() else {
                errorMessage = "Could not start the microphone."
                return
            }
            self.recorder = recorder
            self.fileURL = url
            self.elapsedSeconds = 0
            self.state = .recording
            startTimer()
        } catch {
            errorMessage = "Microphone error: \(error.localizedDescription)"
        }
    }

    func stop() {
        guard state == .recording else { return }
        recorder?.stop()
        cancelTimers()
        loadRecordedData()
        state = .recorded
    }

    func cancel() {
        cancelTimers()
        recorder?.stop()
        recorder = nil
        if let url = fileURL { try? FileManager.default.removeItem(at: url) }
        fileURL = nil
        recordedData = nil
        elapsedSeconds = 0
        state = .idle
        errorMessage = nil
    }

    func reset() {
        cancel()
    }

    private func startTimer() {
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.elapsedSeconds += 0.1
                if self.elapsedSeconds >= self.maxDurationSeconds {
                    self.stop()
                }
            }
        }
    }

    private func cancelTimers() {
        timer?.invalidate()
        timer = nil
    }

    private func loadRecordedData() {
        guard let url = fileURL else { return }
        recordedData = try? Data(contentsOf: url)
        try? FileManager.default.removeItem(at: url)
        fileURL = nil
    }

    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor in
            if self.state == .recording {
                self.cancelTimers()
                self.loadRecordedData()
                self.state = .recorded
            }
        }
    }
}
