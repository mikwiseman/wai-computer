import AppKit
import SwiftUI
import WaiComputerKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var showingDiscardConfirm = false

    var body: some View {
        VStack(spacing: 0) {
            recordingHeader

            WaiDivider()

            if let reason = recordingVM.conversationEndPromptReason {
                conversationEndBanner(reason: reason)
            }

            recordingStatusBody

            WaiDivider()

            // Stop + Discard buttons
            HStack(spacing: Spacing.md) {
                Spacer()

                Button {
                    // While still preparing nothing has been captured yet, so
                    // abort immediately (no confirmation) — this is the escape
                    // hatch from a stalled "Preparing recording…".
                    if recordingVM.phase == .preparing {
                        discardRecording()
                    } else {
                        showingDiscardConfirm = true
                    }
                } label: {
                    Label {
                        Text(recordingVM.phase == .preparing
                             ? t("Cancel", "Отмена")
                             : t("Discard", "Не сохранять"))
                    } icon: {
                        Image(systemName: "trash")
                    }
                    .font(Typography.headingSmall)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(!recordingVM.canStopRecording && recordingVM.phase != .preparing)
                .accessibilityIdentifier("discard-recording-button")

                Button(action: togglePause) {
                    Label {
                        Text(recordingVM.canResumeRecording ? t("Resume", "Продолжить") : t("Pause", "Пауза"))
                            .lineLimit(1)
                    } icon: {
                        Image(systemName: recordingVM.canResumeRecording ? "play.fill" : "pause.fill")
                    }
                    .font(Typography.headingSmall)
                    .frame(minWidth: 120)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(!recordingVM.canPauseRecording && !recordingVM.canResumeRecording)
                .accessibilityIdentifier(recordingVM.canResumeRecording ? "resume-recording-button" : "pause-recording-button")

                Button(action: stopRecording) {
                    Label {
                        // Fixed label: phase status lives in the header only.
                        // Morphing the button into a second status line made
                        // the same string render twice and the button resize.
                        Text(t("Stop", "Остановить"))
                            .lineLimit(1)
                    } icon: {
                        Image(systemName: "stop.fill")
                    }
                    .font(Typography.headingSmall)
                    .frame(minWidth: 150)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(Palette.recording)
                .disabled(!recordingVM.canStopRecording)
                .accessibilityIdentifier("stop-recording-button")

                Spacer()
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xl)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("live-recording-view")
        .confirmationDialog(
            // RU stays in the "не сохранять" verb family end-to-end (trigger →
            // title → confirm), matching the native macOS "Don't Save" pattern
            // and the iOS confirm. "Удалить" is reserved for deleting saved
            // recordings; the message below still spells out the consequence.
            t("Discard this recording?", "Не сохранять запись?"),
            isPresented: $showingDiscardConfirm,
            titleVisibility: .visible
        ) {
            Button(role: .destructive) {
                discardRecording()
            } label: {
                Text(t("Discard", "Не сохранять"))
            }
            .accessibilityIdentifier("discard-recording-confirm")
            Button(role: .cancel) { } label: {
                Text(t("Cancel", "Отмена"))
            }
        } message: {
            Text(t(
                "Audio and transcript will be deleted. This can't be undone.",
                "Аудио и расшифровка будут удалены. Восстановить их нельзя."
            ))
        }
    }

    private func conversationEndBanner(reason: ConversationEndReason) -> some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: reason == .callEnded ? "phone.down.fill" : "waveform.slash")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Palette.warning)

            VStack(alignment: .leading, spacing: 2) {
                Text(reason == .callEnded
                     ? t("The call has ended.", "Звонок завершился.")
                     : t("Sounds like the conversation is over.", "Похоже, разговор закончился."))
                    .font(Typography.headingSmall)
                Text(conversationEndCountdownText)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .accessibilityAddTraits(.updatesFrequently)
            }

            Spacer()

            Button {
                recordingVM.continueConversationFromPrompt()
            } label: {
                Text(t("Keep recording", "Продолжить запись"))
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("conversation-end-continue-button")

            Button(action: stopRecording) {
                Text(t("Stop now", "Остановить сейчас"))
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier("conversation-end-stop-button")
        }
        .padding(.horizontal, Spacing.xxl)
        .padding(.vertical, Spacing.md)
        .background(Palette.warning.opacity(0.12))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("conversation-end-banner")
    }

    private var conversationEndCountdownText: String {
        let seconds = max(recordingVM.conversationEndCountdownSeconds, 0)
        if RecordingAutoStopSettings.action() == .pause {
            return t(
                "Recording will pause in \(seconds)s unless the conversation continues.",
                "Запись встанет на паузу через \(seconds) с, если разговор не продолжится."
            )
        }
        return t(
            "Recording will stop and be saved in \(seconds)s unless the conversation continues.",
            "Запись остановится и сохранится через \(seconds) с, если разговор не продолжится."
        )
    }

    private var recordingStatusBody: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: recordingVM.phase == .finalizing ? "text.badge.checkmark" : "waveform")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(recordingVM.phase == .finalizing ? Palette.accent : Palette.textSecondary)
                .frame(width: 48, height: 48)
                .accessibilityHidden(true)

            Text(recordingVM.emptyTranscriptText)
                .font(Typography.reading)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 560)
                .accessibilityIdentifier("recording-final-transcription-status")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, Spacing.xxl)
    }

    private var recordingHeader: some View {
        HStack(spacing: Spacing.md) {
            if recordingVM.phase == .recording, recordingVM.isPaused {
                // Paused: a static pause glyph. The pulsing red dot is the
                // universal "live capture" signal and must never show while
                // the header says "Paused".
                Image(systemName: "pause.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 12, height: 12)
            } else if recordingVM.phase == .recording {
                Circle()
                    .fill(Palette.recording)
                    .frame(width: 12, height: 12)
                    .modifier(PulseModifier())
            } else {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 12, height: 12)
            }

            Text(recordingVM.statusText)
                .font(Typography.displaySmall)

            // TimelineView keeps the 1 Hz clock refresh inside this one text
            // node instead of publishing a tick through the whole window.
            TimelineView(.periodic(from: .now, by: 1)) { timeline in
                Text(RecordingDurationClock.formatted(
                    recordingVM.durationClock.elapsed(at: timeline.date)
                ))
                .font(Typography.monoLarge)
                .foregroundStyle(Palette.textSecondary)
                .accessibilityAddTraits(.updatesFrequently)
            }

            Spacer()

            HStack(spacing: Spacing.sm) {
                if recordingVM.phase == .recording, !recordingVM.isPaused {
                    voiceDetectionIndicator
                }
                if recordingVM.recordingInputSource == .dual {
                    recordingAudioIndicator
                } else {
                    Label(
                        recordingVM.recordingInputSource.localizedLabel(language: languageManager.current),
                        systemImage: recordingVM.recordingInputSource.systemImage
                    )
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }
                // Recording-type badge removed (119): every recording was typed
                // "meeting", so the badge was always-on and confusing.
            }
        }
        .padding(.horizontal, Spacing.xxl)
        .padding(.vertical, Spacing.xl)
    }

    /// Live speech-detection state: proof the classifier hears the room.
    /// "Voice" while sustained speech is confirmed; once quiet, the running
    /// clock that feeds the auto-stop timeout. Hidden when detection is off.
    @ViewBuilder
    private var voiceDetectionIndicator: some View {
        if let voiceDetected = recordingVM.voiceDetected {
            HStack(spacing: 4) {
                if voiceDetected {
                    Image(systemName: "waveform")
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.success)
                    Text(t("Voice", "Голос"))
                        .font(Typography.label)
                        .foregroundStyle(Palette.success)
                } else {
                    Image(systemName: "waveform.slash")
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.textSecondary)
                    // 1 Hz refresh stays inside this node, same pattern as
                    // the duration clock above.
                    TimelineView(.periodic(from: .now, by: 1)) { timeline in
                        Text(quietLabel(at: timeline.date))
                            .font(Typography.label)
                            .foregroundStyle(Palette.textSecondary)
                            .accessibilityAddTraits(.updatesFrequently)
                    }
                }
            }
            .help(t(
                "Speech detection: the recording offers to stop after a long stretch without voice.",
                "Распознавание речи: после долгой тишины запись предложит остановиться."
            ))
            .accessibilityIdentifier("voice-detection-indicator")
        }
    }

    private func quietLabel(at date: Date) -> String {
        guard let seconds = recordingVM.autoStopQuietSeconds(at: date), seconds >= 5 else {
            return t("Quiet", "Тихо")
        }
        let minutes = seconds / 60
        let rest = seconds % 60
        return t("Quiet", "Тихо") + " " + String(format: "%d:%02d", minutes, rest)
    }

    @ViewBuilder
    private var recordingAudioIndicator: some View {
        let indicator = SystemAudioWarningPolicy.headerIndicator(
            requestedSystemAudio: recordingVM.recordingInputSource == .dual,
            hasSystemAudio: recordingVM.hasSystemAudio,
            warning: recordingVM.systemAudioWarning
        )
        HStack(spacing: 4) {
            Image(systemName: indicatorIcon(indicator))
                .font(.system(size: 10))
                .foregroundStyle(indicatorColor(indicator))
            Text(indicatorLabel(indicator))
                .font(Typography.label)
                .foregroundStyle(indicatorColor(indicator))
        }
        .help(indicatorHelp(indicator))
    }

    private func indicatorIcon(_ indicator: SystemAudioWarningPolicy.HeaderIndicator) -> String {
        switch indicator {
        case .micAndSystem:
            return "checkmark.circle.fill"
        case .systemAudioStarting:
            return "waveform"
        case .systemAudioDegraded:
            return "exclamationmark.triangle.fill"
        case .microphoneOnly:
            return recordingVM.recordingInputSource.systemImage
        }
    }

    private func indicatorColor(_ indicator: SystemAudioWarningPolicy.HeaderIndicator) -> Color {
        switch indicator {
        case .micAndSystem, .systemAudioStarting, .microphoneOnly:
            return Palette.textSecondary
        case .systemAudioDegraded:
            return Palette.warning
        }
    }

    private func indicatorLabel(_ indicator: SystemAudioWarningPolicy.HeaderIndicator) -> String {
        switch indicator {
        case .micAndSystem:
            return t("Mic + System", "Микрофон + Mac")
        case .systemAudioStarting:
            return t("Starting Mac Audio", "Подключаем звук Mac")
        case .systemAudioDegraded:
            return t("Mac Audio Issue", "Проблема со звуком Mac")
        case .microphoneOnly:
            return recordingVM.recordingInputSource.label
        }
    }

    private func indicatorHelp(_ indicator: SystemAudioWarningPolicy.HeaderIndicator) -> String {
        switch indicator {
        case .micAndSystem:
            return t("Recording mic and system audio (2 channels)", "Записывается микрофон и звук Mac (2 канала)")
        case .systemAudioStarting:
            return t("Waiting for the system-audio tap to start.", "Ждем запуска записи звука Mac.")
        case .systemAudioDegraded:
            return t(
                "Microphone is recording. System audio capture is degraded; check Audio Capture permission in System Settings.",
                "Микрофон записывается. Запись звука Mac нарушена; проверь доступ к записи аудио в системных настройках."
            )
        case .microphoneOnly:
            return t("Only microphone audio is being recorded", "Записывается только микрофон")
        }
    }

    private func stopRecording() {
        Task {
            await appState.stopRecording()
        }
    }

    private func togglePause() {
        Task {
            if recordingVM.canResumeRecording {
                await appState.resumeRecording()
            } else {
                await appState.pauseRecording()
            }
        }
    }

    private func discardRecording() {
        Task {
            await recordingVM.discardRecording()
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func recordingTypeLabel(_ type: RecordingType) -> String {
        switch type {
        case .meeting:
            return t("Meeting", "Встреча")
        case .note:
            return t("Note", "Заметка")
        case .reflection:
            return t("Reflection", "Рефлексия")
        }
    }
}

struct PulseModifier: ViewModifier {
    @State private var isPulsing = false

    func body(content: Content) -> some View {
        content
            .opacity(isPulsing ? 0.4 : 1.0)
            .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: isPulsing)
            .onAppear { isPulsing = true }
    }
}
