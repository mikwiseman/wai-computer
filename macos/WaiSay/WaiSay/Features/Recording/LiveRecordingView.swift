import SwiftUI
import WaiSayKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel

    var body: some View {
        VStack(spacing: 0) {
            recordingHeader

            // Reconnection banner
            if case .reconnecting(let attempt, let maxAttempts) = recordingVM.connectionState {
                HStack(spacing: Spacing.sm) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Reconnecting… (\(attempt)/\(maxAttempts))")
                        .font(Typography.label)
                        .foregroundStyle(.white)
                    Spacer()
                    Text("Audio is being buffered")
                        .font(Typography.label)
                        .foregroundStyle(.white.opacity(0.7))
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.sm)
                .background(Color.orange)
                .accessibilityIdentifier("reconnection-banner")
            }

            // System audio stall warning
            if let warning = recordingVM.systemAudioWarning {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.yellow)
                    Text(warning)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    Spacer()
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.sm)
                .background(Color.yellow.opacity(0.1))
                .accessibilityIdentifier("system-audio-warning")
            }

            WaiDivider()

            // Live transcript
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                        if recordingVM.currentTranscript.isEmpty {
                            Text(recordingVM.emptyTranscriptText)
                                .font(Typography.reading)
                                .foregroundStyle(Palette.textSecondary)
                                .italic()
                                .padding(Spacing.lg)
                        } else {
                            Text(recordingVM.currentTranscript)
                                .font(Typography.reading)
                                .lineSpacing(6)
                                .textSelection(.enabled)
                                .padding(Spacing.lg)
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

            // Stop button
            HStack {
                Spacer()

                Button {
                    Task {
                        await appState.stopRecording()
                    }
                } label: {
                    HStack(spacing: Spacing.sm) {
                        if recordingVM.canStopRecording {
                            Image(systemName: "stop.fill")
                            Text("Stop Recording")
                        } else {
                            ProgressView()
                                .controlSize(.small)
                            Text(recordingVM.statusText)
                        }
                    }
                    .font(Typography.headingSmall)
                    .foregroundStyle(.white)
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.md)
                    .background(recordingVM.canStopRecording ? Palette.recording : Palette.border)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .disabled(!recordingVM.canStopRecording)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(recordingVM.canStopRecording ? "Stop Recording" : recordingVM.statusText)
                .accessibilityIdentifier("stop-recording-button")

                Spacer()
            }
            .padding(Spacing.lg)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("live-recording-view")
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
                        Text(systemOk ? "Mic + System" : "Mic Only")
                            .font(Typography.label)
                            .foregroundStyle(systemOk ? Palette.textSecondary : .yellow)
                    }
                    .help(systemOk
                        ? "Recording mic and system audio (2 channels)"
                        : "System audio unavailable — only mic is recording")
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
        .padding(Spacing.lg)
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
