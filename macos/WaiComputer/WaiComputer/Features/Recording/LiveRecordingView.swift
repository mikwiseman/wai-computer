import SwiftUI
import WaiComputerKit

struct LiveRecordingView: View {
    @EnvironmentObject var appState: MacAppState

    var body: some View {
        VStack(spacing: 0) {
            // Recording header
            recordingHeader

            Divider()

            // Live transcript
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        if appState.recordingViewModel.currentTranscript.isEmpty {
                            Text("Listening...")
                                .foregroundStyle(.secondary)
                                .italic()
                                .padding()
                        } else {
                            Text(appState.recordingViewModel.currentTranscript)
                                .font(.body)
                                .padding()
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

            Divider()

            // Stop button
            HStack {
                Spacer()

                Button {
                    Task {
                        await appState.stopRecording()
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "stop.fill")
                        Text("Stop Recording")
                    }
                    .font(.headline)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                    .background(.red)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)

                Spacer()
            }
            .padding()
        }
    }

    private var recordingHeader: some View {
        HStack(spacing: 12) {
            // Pulsing red indicator
            Circle()
                .fill(.red)
                .frame(width: 12, height: 12)
                .modifier(PulseModifier())

            Text("Recording")
                .font(.title2)
                .fontWeight(.semibold)

            Text(appState.recordingViewModel.formattedDuration)
                .font(.system(.title3, design: .monospaced))
                .foregroundStyle(.secondary)

            Spacer()

            TypeBadge(type: appState.recordingViewModel.recordingType)
        }
        .padding()
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
