import SwiftUI
import WaiComputerKit

struct RecordingView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = RecordingViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                // Recording type selector
                Picker("Type", selection: $viewModel.recordingType) {
                    Text("Note").tag(RecordingType.note)
                    Text("Meeting").tag(RecordingType.meeting)
                    Text("Reflection").tag(RecordingType.reflection)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .disabled(viewModel.phase != .idle)

                // Recording status
                VStack(spacing: 16) {
                    // Waveform or status indicator
                    ZStack {
                        Circle()
                            .fill(outerIndicatorColor)
                            .frame(width: 200, height: 200)

                        Circle()
                            .fill(innerIndicatorColor)
                            .frame(width: 150, height: 150)
                            .scaleEffect(viewModel.canStopRecording ? 1.1 : 1.0)
                            .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: viewModel.canStopRecording)

                        Image(systemName: indicatorSymbolName)
                            .font(.system(size: 60))
                            .foregroundStyle(indicatorSymbolColor)
                    }

                    // Duration
                    Text(viewModel.formattedDuration)
                        .font(.system(size: 48, weight: .light, design: .monospaced))
                        .foregroundStyle(viewModel.phase == .idle ? .secondary : .primary)
                }

                // Live transcript preview
                if viewModel.shouldShowTranscript {
                    ScrollView {
                        Group {
                            if viewModel.currentTranscript.isEmpty {
                                Text(viewModel.emptyTranscriptText)
                                    .foregroundStyle(.secondary)
                                    .italic()
                            } else {
                                Text(viewModel.currentTranscript)
                                    .font(.body)
                            }
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 150)
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(12)
                    .padding(.horizontal)
                }

                Spacer()

                // Record button
                Button(action: {
                    Task {
                        if viewModel.canStopRecording {
                            await viewModel.stopRecording()
                        } else if viewModel.canStartRecording {
                            await viewModel.startRecording(
                                apiClient: appState.getAPIClient(),
                                webSocketManager: appState.getWebSocketManager()
                            )
                        }
                    }
                }) {
                    ZStack {
                        Circle()
                            .fill(buttonColor)
                            .frame(width: 80, height: 80)

                        if viewModel.canStopRecording {
                            RoundedRectangle(cornerRadius: 8)
                                .fill(.white)
                                .frame(width: 30, height: 30)
                        } else if viewModel.isBusy {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Circle()
                                .fill(.white)
                                .frame(width: 30, height: 30)
                        }
                    }
                }
                .disabled(viewModel.isBusy)

                // Status text
                Text(viewModel.statusText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.bottom)
            }
            .navigationTitle("Record")
            .alert("Error", isPresented: .constant(viewModel.error != nil)) {
                Button("OK") { viewModel.error = nil }
            } message: {
                Text(viewModel.error ?? "")
            }
        }
    }

    private var outerIndicatorColor: Color {
        switch viewModel.phase {
        case .recording:
            return Color.red.opacity(0.2)
        case .preparing, .finalizing:
            return Color.orange.opacity(0.18)
        case .idle:
            return Color.gray.opacity(0.1)
        }
    }

    private var innerIndicatorColor: Color {
        switch viewModel.phase {
        case .recording:
            return Color.red.opacity(0.4)
        case .preparing, .finalizing:
            return Color.orange.opacity(0.28)
        case .idle:
            return Color.gray.opacity(0.2)
        }
    }

    private var indicatorSymbolName: String {
        switch viewModel.phase {
        case .recording:
            return "waveform"
        case .preparing, .finalizing:
            return "hourglass"
        case .idle:
            return "mic.fill"
        }
    }

    private var indicatorSymbolColor: Color {
        switch viewModel.phase {
        case .recording:
            return .red
        case .preparing, .finalizing:
            return .orange
        case .idle:
            return .gray
        }
    }

    private var buttonColor: Color {
        switch viewModel.phase {
        case .recording:
            return .red
        case .preparing, .finalizing:
            return .gray
        case .idle:
            return .blue
        }
    }
}

#Preview {
    RecordingView()
        .environmentObject(AppState())
}
