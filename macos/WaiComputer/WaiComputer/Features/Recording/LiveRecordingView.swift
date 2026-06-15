import AppKit
import SwiftUI
import WaiComputerKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var showingDiscardConfirm = false
    /// Whether the live transcript should auto-follow new words. Scrolling up
    /// past the threshold suspends following so the user can read back or
    /// select earlier text; the "Jump to latest" pill resumes it.
    @State private var isPinnedToBottom = true

    /// How far (pt) above the bottom the user may drift while still counting
    /// as "at the bottom". Generous enough that one streamed paragraph can't
    /// spuriously suspend auto-follow before the follow-up scroll lands.
    private static let bottomPinThreshold: CGFloat = 120

    private var transcriptHasContent: Bool {
        !recordingVM.committedTranscriptChunks.isEmpty || !recordingVM.interimTranscript.isEmpty
    }

    private var transcriptScrollToken: LiveTranscriptScrollToken {
        LiveTranscriptScrollToken(
            committedRevision: recordingVM.committedTranscriptRevision,
            interimRevision: recordingVM.interimTranscriptRevision
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            recordingHeader

            // Reconnection banner
            if case .reconnecting(let attempt, let maxAttempts) = recordingVM.connectionState {
                HStack(spacing: Spacing.sm) {
                    ProgressView()
                        .controlSize(.small)
                    Text(t("Reconnecting…", "Переподключение…") + " (\(attempt)/\(maxAttempts))")
                        .font(Typography.label)
                        .foregroundStyle(.black)
                    Spacer()
                    Text(t("Audio is being buffered", "Аудио сохраняется локально"))
                        .font(Typography.label)
                        .foregroundStyle(.black.opacity(0.7))
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.sm)
                .background(Color.orange)
                .accessibilityIdentifier("reconnection-banner")
            }

            // Offline transcription banner
            if recordingVM.liveTranscriptionOffline && recordingVM.phase == .recording {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "wifi.exclamationmark")
                        .foregroundStyle(.black)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("Live transcription unavailable", "Живая расшифровка недоступна"))
                            .font(Typography.label)
                            .foregroundStyle(.black)
                        Text(t(
                            "Audio is recording locally. Transcript will be generated when you stop.",
                            "Аудио записывается локально. Расшифровка появится после остановки."
                        ))
                            .font(Typography.caption)
                            .foregroundStyle(.black.opacity(0.7))
                    }
                    Spacer()
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.sm)
                .background(Color.orange)
                .accessibilityIdentifier("live-transcription-offline-banner")
            }

            WaiDivider()

            // Live transcript — committed text renders sharp; the rolling
            // interim guess is faded so users don't fixate on words the model
            // is still revising ahead of their speech. Auto-follow only while
            // the user is at the bottom: scrolling up sticks (read-back,
            // selection), and a "Jump to latest" pill resumes following.
            GeometryReader { viewport in
                ScrollViewReader { proxy in
                    List {
                        if !transcriptHasContent {
                            Text(recordingVM.emptyTranscriptText)
                                .font(Typography.reading)
                                .foregroundStyle(Palette.textSecondary)
                                .italic()
                                .padding(.vertical, Spacing.xl)
                                .liveTranscriptListRow()
                        } else {
                            ForEach(recordingVM.committedTranscriptChunks) { chunk in
                                Text(chunk.text)
                                    .font(Typography.reading)
                                    .lineSpacing(6)
                                    .textSelection(.enabled)
                                    .accessibilityAddTraits(.updatesFrequently)
                                    .padding(.vertical, Spacing.xs)
                                    .liveTranscriptListRow()
                            }

                            if !recordingVM.interimTranscript.isEmpty {
                                Text(recordingVM.interimTranscript)
                                    .font(Typography.reading.italic())
                                    .lineSpacing(6)
                                    .foregroundStyle(Palette.textSecondary)
                                    .textSelection(.enabled)
                                    .accessibilityHidden(true)
                                    .accessibilityLabel(t(
                                        "Interim transcript — may change as you speak",
                                        "Промежуточная расшифровка — текст может уточняться"
                                    ))
                                    .padding(.vertical, Spacing.xs)
                                    .liveTranscriptListRow()
                            }

                            Color.clear
                                .frame(height: 1)
                                .id("transcript-bottom")
                                .background(
                                    GeometryReader { content in
                                        Color.clear.preference(
                                            key: TranscriptBottomDistanceKey.self,
                                            value: content.frame(in: .named("live-transcript-scroll")).maxY
                                        )
                                    }
                                )
                                .liveTranscriptListRow()
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .coordinateSpace(name: "live-transcript-scroll")
                    .accessibilityIdentifier("live-transcript-list")
                    .onPreferenceChange(TranscriptBottomDistanceKey.self) { contentMaxY in
                        let pinned = contentMaxY - viewport.size.height < Self.bottomPinThreshold
                        if pinned != isPinnedToBottom {
                            isPinnedToBottom = pinned
                        }
                    }
                    .onChangeCompat(of: transcriptScrollToken) { _, _ in
                        // Unanimated on purpose: events land several times a
                        // second during speech, and a mid-animation layout
                        // would briefly read as "not at bottom" and break the
                        // pin. Instant follow is also what live tails expect.
                        guard isPinnedToBottom else { return }
                        proxy.scrollTo("transcript-bottom", anchor: .bottom)
                    }
                    .overlay(alignment: .bottom) {
                        if !isPinnedToBottom && transcriptHasContent {
                            Button {
                                proxy.scrollTo("transcript-bottom", anchor: .bottom)
                                isPinnedToBottom = true
                            } label: {
                                Label(t("Jump to latest", "К последним словам"), systemImage: "arrow.down")
                                    .font(Typography.label)
                                    .foregroundStyle(Palette.onAccent)
                                    .padding(.horizontal, Spacing.md)
                                    .padding(.vertical, Spacing.xs)
                                    .background(Palette.accent)
                                    .clipShape(Capsule())
                                    .shadow(color: .black.opacity(0.2), radius: 4, y: 1)
                            }
                            .buttonStyle(.plain)
                            .padding(.bottom, Spacing.md)
                            .accessibilityIdentifier("transcript-jump-to-latest")
                        }
                    }
                }
            }

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
                .tint(.red)
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
            } else if recordingVM.phase == .recording,
               case .reconnecting = recordingVM.connectionState {
                Circle()
                    .fill(Color.orange)
                    .frame(width: 12, height: 12)
                    .modifier(PulseModifier())
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

            Text(recordingVM.formattedDuration)
                .font(Typography.monoLarge)
                .foregroundStyle(Palette.textSecondary)
                .accessibilityAddTraits(.updatesFrequently)

            Spacer()

            HStack(spacing: Spacing.sm) {
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
            return .yellow
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

/// Bottom edge (maxY) of the live-transcript content measured in the scroll
/// view's coordinate space. Compared against the viewport height to detect
/// whether the user is pinned to the latest words.
private struct TranscriptBottomDistanceKey: PreferenceKey {
    static let defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct LiveTranscriptScrollToken: Equatable {
    let committedRevision: Int
    let interimRevision: Int
}

private extension View {
    func liveTranscriptListRow() -> some View {
        self
            .frame(maxWidth: 920, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowInsets(EdgeInsets(
                top: 0,
                leading: Spacing.xxl,
                bottom: 0,
                trailing: Spacing.xxl
            ))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
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
