import SwiftUI
import WaiComputerKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel

    var body: some View {
        VStack(spacing: 0) {
            recordingHeader

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

                Spacer()
            }
            .padding(Spacing.lg)
        }
    }

    private var recordingHeader: some View {
        HStack(spacing: Spacing.md) {
            if recordingVM.phase == .recording {
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

            Text(recordingVM.recordingType.rawValue.capitalized)
                .font(Typography.label)
                .foregroundStyle(Palette.typeColor(recordingVM.recordingType))
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
