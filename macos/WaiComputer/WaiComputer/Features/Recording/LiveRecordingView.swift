import SwiftUI
import WaiComputerKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState

    var body: some View {
        VStack(spacing: 0) {
            recordingHeader

            WaiDivider()

            // Live transcript
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                        if appState.recordingViewModel.currentTranscript.isEmpty {
                            Text("Listening...")
                                .font(Typography.reading)
                                .foregroundStyle(Palette.textSecondary)
                                .italic()
                                .padding(Spacing.lg)
                        } else {
                            Text(appState.recordingViewModel.currentTranscript)
                                .font(Typography.reading)
                                .lineSpacing(6)
                                .textSelection(.enabled)
                                .padding(Spacing.lg)
                                .id("transcript-bottom")
                        }
                    }
                }
                .onChange(of: appState.recordingViewModel.currentTranscript) { _, _ in
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
                        Image(systemName: "stop.fill")
                        Text("Stop Recording")
                    }
                    .font(Typography.headingSmall)
                    .foregroundStyle(.white)
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.md)
                    .background(Palette.recording)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)

                Spacer()
            }
            .padding(Spacing.lg)
        }
    }

    private var recordingHeader: some View {
        HStack(spacing: Spacing.md) {
            // Pulsing red indicator
            Circle()
                .fill(Palette.recording)
                .frame(width: 12, height: 12)
                .modifier(PulseModifier())

            Text("Recording")
                .font(Typography.displaySmall)

            Text(appState.recordingViewModel.formattedDuration)
                .font(Typography.monoLarge)
                .foregroundStyle(Palette.textSecondary)

            Spacer()

            Text(appState.recordingViewModel.recordingType.rawValue.capitalized)
                .font(Typography.label)
                .foregroundStyle(Palette.typeColor(appState.recordingViewModel.recordingType))
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
