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

            // Reconnection banner
            if case .reconnecting(let attempt, let maxAttempts) = recordingVM.connectionState {
                HStack(spacing: Spacing.sm) {
                    ProgressView()
                        .controlSize(.small)
                    Text(t("Reconnecting…", "Переподключение…") + " (\(attempt)/\(maxAttempts))")
                        .font(Typography.label)
                        .foregroundStyle(.white)
                    Spacer()
                    Text(t("Audio is being buffered", "Аудио сохраняется локально"))
                        .font(Typography.label)
                        .foregroundStyle(.white.opacity(0.7))
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
                        .foregroundStyle(.white)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("Live transcription unavailable", "Живая транскрипция недоступна"))
                            .font(Typography.label)
                            .foregroundStyle(.white)
                        Text(t(
                            "Audio is recording locally. Transcript will be generated when you stop.",
                            "Аудио записывается локально. Транскрипт появится после остановки."
                        ))
                            .font(Typography.caption)
                            .foregroundStyle(.white.opacity(0.85))
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
            // is still revising ahead of their speech.
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                        if recordingVM.currentTranscript.isEmpty {
                            Text(recordingVM.emptyTranscriptText)
                                .font(Typography.reading)
                                .foregroundStyle(Palette.textSecondary)
                                .italic()
                                .padding(.horizontal, Spacing.xxl)
                                .padding(.vertical, Spacing.xl)
                        } else {
                            VStack(alignment: .leading, spacing: Spacing.xs) {
                                if !recordingVM.committedTranscript.isEmpty {
                                    Text(recordingVM.committedTranscript)
                                        .font(Typography.reading)
                                        .lineSpacing(6)
                                        .textSelection(.enabled)
                                }
                                if !recordingVM.interimTranscript.isEmpty {
                                    Text(recordingVM.interimTranscript)
                                        .font(Typography.reading.italic())
                                        .lineSpacing(6)
                                        .foregroundStyle(Palette.textTertiary)
                                        .textSelection(.enabled)
                                        .accessibilityLabel(Text("recording.transcript.interim", bundle: .main))
                                }
                            }
                            .padding(.horizontal, Spacing.xxl)
                            .padding(.vertical, Spacing.xl)
                            .id("transcript-bottom")
                        }
                    }
                }
                .onChange(of: recordingVM.currentTranscript) { _, _ in
                    withAnimation {
                        proxy.scrollTo("transcript-bottom", anchor: .bottom)
                    }
                }
            }

            WaiDivider()

            // Stop + Discard buttons
            HStack(spacing: Spacing.md) {
                Spacer()

                Button {
                    showingDiscardConfirm = true
                } label: {
                    Label {
                        Text("recording.discard", bundle: .main)
                    } icon: {
                        Image(systemName: "trash")
                    }
                    .font(.system(size: 13, weight: .medium))
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(!recordingVM.canStopRecording)
                .accessibilityIdentifier("discard-recording-button")

                Button(action: stopRecording) {
                    Label {
                        Text(recordingVM.canStopRecording
                            ? String(localized: "recording.stop", bundle: .main)
                            : recordingVM.statusText
                        )
                        .lineLimit(1)
                    } icon: {
                        Image(systemName: "stop.fill")
                    }
                    .font(.system(size: 13, weight: .semibold))
                    .frame(minWidth: 150)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(recordingVM.canStopRecording ? .red : .gray)
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
            Text("recording.discardConfirm.title", bundle: .main),
            isPresented: $showingDiscardConfirm,
            titleVisibility: .visible
        ) {
            Button(role: .destructive) {
                discardRecording()
            } label: {
                Text("recording.discardConfirm.confirm", bundle: .main)
            }
            .accessibilityIdentifier("discard-recording-confirm")
            Button(role: .cancel) { } label: {
                Text("recording.cancel", bundle: .main)
            }
        } message: {
            Text("recording.discardConfirm.body", bundle: .main)
        }
    }

    private var recordingHeader: some View {
        HStack(spacing: Spacing.md) {
            if recordingVM.phase == .recording,
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

            Spacer()

            HStack(spacing: Spacing.sm) {
                if recordingVM.recordingInputSource == .dual {
                    let systemOk = recordingVM.hasSystemAudio && recordingVM.systemAudioWarning == nil
                    HStack(spacing: 4) {
                        Image(systemName: systemOk ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .font(.system(size: 10))
                            .foregroundStyle(systemOk ? .green : .yellow)
                        Text(systemOk ? t("Mic + System", "Микрофон + Mac") : t("Microphone", "Микрофон"))
                            .font(Typography.label)
                            .foregroundStyle(systemOk ? Palette.textSecondary : .yellow)
                    }
                    .help(systemOk
                        ? t("Recording mic and system audio (2 channels)", "Записывается микрофон и звук Mac (2 канала)")
                        : t("Only microphone audio is being recorded", "Записывается только микрофон")
                    )
                } else {
                    Label(recordingVM.recordingInputSource.label, systemImage: recordingVM.recordingInputSource.systemImage)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }

                Text(recordingVM.recordingType.rawValue.capitalized)
                    .font(Typography.label)
                    .foregroundStyle(Palette.typeColor(recordingVM.recordingType))
            }
        }
        .padding(.horizontal, Spacing.xxl)
        .padding(.vertical, Spacing.xl)
    }

    private func stopRecording() {
        Task {
            await appState.stopRecording()
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
