import AVFoundation
import SwiftUI
import WaiComputerKit

/// iOS combined mic-test + voice-enrollment step (Wispr Flow pattern).
struct OnboardingVoiceSetupSlide: View {
    let isActive: Bool
    let hasMicrophonePermission: Bool
    let onAdvance: () -> Void

    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var recorder = VoiceEnrollmentRecorder()

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Spacer(minLength: Spacing.lg)

            Text(t("VOICE", "ГОЛОС"))
                .font(Typography.labelSmall)
                .tracking(1.6)
                .foregroundStyle(Palette.accent)

            Text(t("Teach Wai your voice", "Научи Wai узнавать твой голос"))
                .font(Typography.displayMedium)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textPrimary)

            Text(t(
                "Read the prompt for ~20 seconds. Wai will recognise you in future meetings automatically.",
                "Прочитай текст около 20 секунд. Wai будет узнавать тебя на будущих встречах автоматически."
            ))
                .font(Typography.bodyLarge)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textSecondary)
                .padding(.horizontal, Spacing.lg)

            Text(t(
                "Record at least 5 seconds. This also checks the same microphone path used for recordings.",
                "Запиши минимум 5 секунд. Так мы проверим тот же микрофонный путь, который используется для записей."
            ))
                .font(Typography.caption)
                .multilineTextAlignment(.center)
                .foregroundStyle(Palette.textTertiary)
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
                Button(t("Skip for now", "Пропустить пока"), action: skipAndAdvance)
                    .buttonStyle(WaiGhostButtonStyle())
                Spacer()
                if recorder.state == .recorded {
                    Button(t("Re-record", "Записать заново"), action: handleRecordTap)
                        .buttonStyle(WaiGhostButtonStyle())
                    Button(t("Use this take", "Использовать запись"), action: submit)
                        .buttonStyle(WaiPrimaryButtonStyle(
                            isDisabled: recorder.state == .uploading || !recorder.hasMinimumDuration
                        ))
                        .disabled(recorder.state == .uploading || !recorder.hasMinimumDuration)
                }
            }
            .padding(.horizontal, Spacing.xl)

            Text(t(
                "We store a 192-number signature, not your audio. The recording is deleted after the signature is created.",
                "Мы храним 192-числовую подпись, а не аудио. Запись удаляется после создания подписи."
            ))
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
        Text(promptText)
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

    private var promptText: String {
        t(
            "Hi, I'm setting up Wai Computer. It records meetings, calls, and ideas through my day so I don't have to remember them all. Wai listens, transcribes the people I talk to, and keeps the moments that matter.",
            "Привет, я настраиваю WaiComputer. Он записывает встречи, звонки и идеи в течение дня, чтобы мне не приходилось все запоминать. Wai слушает, расшифровывает людей, с которыми я говорю, и сохраняет важные моменты."
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
        .disabled(!hasMicrophonePermission || recorder.state == .uploading)
        .accessibilityIdentifier("onboarding-voice-record-button")
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
            guard recorder.hasMinimumDuration else {
                recorder.errorMessage = t(
                    "Record at least 5 seconds before submitting.",
                    "Перед отправкой запиши минимум 5 секунд."
                )
                return
            }
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
            return hasMicrophonePermission
                ? t("Press the mic to start", "Нажми микрофон, чтобы начать")
                : t("Grant microphone access first", "Сначала разреши микрофон")
        case .recording:
            return t(
                "Recording… \(Int(recorder.elapsedSeconds))s / 20s",
                "Запись… \(Int(recorder.elapsedSeconds)) c / 20 c"
            )
        case .recorded:
            if !recorder.hasMinimumDuration {
                return t(
                    "Recorded \(Int(recorder.elapsedSeconds))s. Minimum is 5s.",
                    "Записано \(Int(recorder.elapsedSeconds)) c. Нужно минимум 5 c."
                )
            }
            return t(
                "Recorded \(Int(recorder.elapsedSeconds))s. Re-record or submit.",
                "Записано \(Int(recorder.elapsedSeconds)) c. Можно перезаписать или отправить."
            )
        case .uploading:
            return t("Uploading voice signature…", "Загружаем голосовую подпись…")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
    private let minDurationSeconds: Double = 5.0

    /// A voiceprint needs a minimum amount of speech to be reliable. The
    /// submit button stays disabled until this clears. Mirrors macOS.
    var hasMinimumDuration: Bool {
        elapsedSeconds >= minDurationSeconds
    }

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
