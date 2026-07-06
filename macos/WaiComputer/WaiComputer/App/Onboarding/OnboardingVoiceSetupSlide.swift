import AVFoundation
import SwiftUI
import WaiComputerKit

/// Combined microphone test + voice-enrollment step.
/// Wispr Flow pattern: the user reads a fixed paragraph; the recording validates
/// the mic and seeds a Person voiceprint in one motion.
struct OnboardingVoiceSetupSlide: View {
    let isActive: Bool
    let hasMicrophonePermission: Bool
    let onAdvance: () -> Void

    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var recorder = VoiceEnrollmentRecorder()

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text(t("Optional: identify your voice", "Опционально: распознавать твой голос"))
                    .font(Typography.displayLarge)
                    .foregroundStyle(Palette.textPrimary)
                Text(
                    t(
                        "Record a short sample so WaiComputer can recognize you in future meetings without manual speaker tagging. Takes about 20 seconds.",
                        "Запиши короткий образец: WaiComputer будет узнавать твой голос во встречах без ручной разметки спикеров. Это займет около 20 секунд."
                    )
                )
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
                Text(t(
                    "Record at least 5 seconds. This also checks the same microphone path used for dictation.",
                    "Запиши минимум 5 секунд. Так мы проверим тот же микрофонный путь, который потом используется для диктовки."
                ))
                .font(Typography.label)
                .foregroundStyle(Palette.textTertiary)
            }
            .multilineTextAlignment(.center)
            .frame(maxWidth: 540)

            promptCard
                .frame(maxWidth: 640)

            controls
                .frame(maxWidth: 640)

            footer
                .frame(maxWidth: 640)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
        .onChangeCompat(of: isActive) { _, active in
            if !active && recorder.state == .recording {
                recorder.cancel()
            }
        }
    }

    private var promptCard: some View {
        Text(promptText)
            .font(Typography.reading)
            .lineSpacing(6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Spacing.lg)
            .background(
                RoundedRectangle(cornerRadius: Radius.lg)
                    .fill(Palette.surfaceSubtle)
                    .overlay(
                        RoundedRectangle(cornerRadius: Radius.lg)
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

    @ViewBuilder
    private var controls: some View {
        HStack(alignment: .center, spacing: Spacing.lg) {
            recordButton
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(statusLabel)
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                ProgressView(value: recorder.progress)
                    .progressViewStyle(.linear)
                    .frame(width: 220)
                if let error = recorder.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(Palette.danger)
                }
            }
            Spacer()
        }
    }

    private var recordButton: some View {
        Button(action: handleRecordTap) {
            ZStack {
                Circle()
                    .fill(recorder.state == .recording ? Color.red : Palette.accent)
                    .frame(width: 72, height: 72)
                Image(systemName: recorder.state == .recording ? "stop.fill" : "mic.fill")
                    .font(.system(size: 28, weight: .semibold))
                    // White passes the 3:1 non-text threshold on the red
                    // recording fill; on the accent fill it must be the
                    // WCAG-computed Palette.onAccent (white fails on amber).
                    .foregroundStyle(recorder.state == .recording ? Color.white : Palette.onAccent)
            }
        }
        .buttonStyle(.plain)
        .disabled(!hasMicrophonePermission || recorder.state == .uploading)
    }

    @ViewBuilder
    private var footer: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Button(t("Skip for now", "Пропустить пока"), action: skipAndAdvance)
                    .buttonStyle(WaiGhostButtonStyle())
                Spacer()
                if recorder.state == .recorded {
                    Button(t("Re-record", "Записать заново"), action: handleRecordTap)
                        .buttonStyle(WaiGhostButtonStyle())
                    Button(t("Use this take", "Использовать запись"), action: submit)
                        .buttonStyle(WaiPrimaryButtonStyle(isDisabled: recorder.state == .uploading || !recorder.hasMinimumDuration))
                        .disabled(recorder.state == .uploading || !recorder.hasMinimumDuration)
                        // The slide owns the primary CTA on this page (the
                        // shared footer hides its Continue), so Return
                        // submits the take instead of discarding it.
                        .keyboardShortcut(.defaultAction)
                }
            }
            Text(t(
                "We store a 192-number signature, not your audio. The recording is deleted after the signature is created.",
                "Мы храним 192-числовую подпись, а не аудио. Запись удаляется после создания подписи."
            ))
                .font(.caption)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    // MARK: - Actions

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
            recorder.isMeteringEnabled = true
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
